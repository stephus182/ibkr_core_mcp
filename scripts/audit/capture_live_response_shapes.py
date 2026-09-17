"""Capture verbatim IBKR Client Portal responses as model test fixtures.

Run against a live, authenticated gateway. Writes the JSON consumed by
`tests/test_models_live_shapes.py`:

    source /path/to/.env
    python scripts/audit/capture_live_response_shapes.py tests/fixtures/ibkr_live_shapes.json

Everything the account holder can be identified by is stripped before the file is
written; only the SHAPE is kept. `redact_live_payload.py` holds the rules and the reasons.

This used to read "account numbers are rewritten ... nothing else is altered", and that is
exactly what it did. The check afterwards looked for account numbers too, so it passed
while the committed fixture published the holder's legal name, net liquidation value, cash
balance, buying power, open positions, four executed futures fills with their IBKR
execution IDs, a resting order and every watchlist name — to a PUBLIC repository
(finding SEC-13, 2026-09-16). A control scoped to one field of ten is not a control.

Two payloads are reduced after capture, and both are labelled in the fixture's README:
`scanner_params` (218 KB of static reference data) keeps the first two entries of every
list, and `market_snapshot` legitimately returns only `conid`/`conidEx` on a first call.

Run this in ONE process. `EndpointPacer`'s budget is per process while IBKR's limit is
per IP, so a second concurrent capture can earn the fifteen-minute penalty box.
"""

import json
import sys
from collections.abc import Callable
from typing import Any

from redact_live_payload import ACCOUNT_ID_RE, PUBLIC_ENDPOINTS, redact_capture

from ibkr_core_mcp import Config, IBKRClient, IBKRResponse


def _shape(obj: Any) -> Any:
    """Keys, nesting and scalar types — everything the fixture exists to record.

    Account-shaped **keys** are normalised to their position, because redaction is
    supposed to rename them: `/iserver/accounts`'s `acctProps` and `/pnl/partitioned` are
    keyed by account number, and comparing the raw names would report every correct
    redaction as a shape change (which it did, 2026-09-17).

    Positional, not a constant, so the check still catches what it is for: every account
    id masks to the *same* `U1234567`, so two account keys collapse into one and silently
    lose an account's data. Two keys normalise to `<account:0>` and `<account:1>` before
    redaction and to a single `<account:0>` after — a difference this reports.
    """
    if isinstance(obj, dict):
        # An account id is not always the whole key: `/pnl/partitioned` is keyed
        # `U1234567.Core`, so substitute wherever it appears and keep the rest of the key,
        # which stays part of the compared shape.
        found: list[str] = sorted({m for k in obj if isinstance(k, str) for m in ACCOUNT_ID_RE.findall(k)})
        index = {account: position for position, account in enumerate(found)}
        out: dict[Any, Any] = {}
        for k, v in sorted(obj.items(), key=lambda kv: str(kv[0])):
            key: Any = ACCOUNT_ID_RE.sub(lambda m: f"<account:{index[m.group(0)]}>", k) if isinstance(k, str) else k
            out[key] = _shape(v)
        return out
    if isinstance(obj, list):
        return [_shape(v) for v in obj]
    return type(obj).__name__


def _scalars(obj: Any, key: str | None = None) -> list[Any]:
    """Every leaf value, paired with nothing — the caller only needs the values."""
    if isinstance(obj, dict):
        return [v for k, sub in obj.items() for v in _scalars(sub, k if isinstance(k, str) else None)]
    if isinstance(obj, list):
        return [v for sub in obj for v in _scalars(sub, key)]
    return [(key, obj)]


def _is_placeholder(pair: Any) -> bool:
    from redact_live_payload import STRUCTURAL

    key, value = pair
    if isinstance(value, bool) or value is None or value in (0, 1):
        return True
    if value in ("REDACTED", "1111.11", "U1234567", 1111111, 1111.11):
        return True
    return bool(key and key.lower() in STRUCTURAL)


def truncate(obj: Any, keep: int = 2) -> Any:
    """Keep the first `keep` entries of every list, preserving the key structure."""
    if isinstance(obj, list):
        return [truncate(v, keep) for v in obj[:keep]]
    if isinstance(obj, dict):
        return {k: truncate(v, keep) for k, v in obj.items()}
    return obj


def _first_watchlist_id(client: Any) -> str:
    """The account's first watchlist id, so the detail endpoint can be captured at all.

    Returns "" when the account has none, which makes that one capture fail and be skipped
    rather than taking the run down — the loop already reports and counts a failure.
    """
    lists = client.get_watchlists()
    return str(lists[0].get("id", "")) if lists else ""


def _as_payload(value: Any) -> Any:
    """Reduce any response model back to the payload IBKR sent.

    Fourteen client methods return `IBKRResponse` subclasses since API-11 (2026-09-17), and
    this file exists to record **what IBKR sent**, not how this package views it. Models
    broke the run twice over: the redactor walks dicts and lists, so a model fell through to
    its scalar branch untouched, and `json.dump` then refused it outright — the same gap
    that made `models.json_default` necessary for the resource handlers.

    `dict(model)` is the untouched payload: `IBKRResponse` serves the mapping protocol over
    the response exactly as it arrived.
    """
    if isinstance(value, IBKRResponse):
        return _as_payload(dict(value))
    if isinstance(value, dict):
        return {k: _as_payload(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_as_payload(v) for v in value]
    return value


def _shape_difference(before: Any, after: Any, path: str = "") -> str | None:
    """The first place two shapes disagree, as a readable path.

    A bare `assert shapes match` tells you the redaction broke something and nothing about
    where, which on 2026-09-17 meant a captured gateway session was spent learning only
    that. The raw capture is deliberately never written to disk while this fails — it
    holds the operator's real account number, and the whole point of the redactor is that
    it is the only thing that writes.
    """
    if type(before) is not type(after):
        return f"{path or '<root>'}: {type(before).__name__} became {type(after).__name__}"
    if isinstance(before, dict):
        if set(before) != set(after):
            lost = sorted(set(before) - set(after))
            gained = sorted(set(after) - set(before))
            return f"{path or '<root>'}: {len(before)} keys became {len(after)} — lost {lost[:4]}, gained {gained[:4]}"
        for k in before:
            if (found := _shape_difference(before[k], after[k], f"{path}.{k}" if path else str(k))) is not None:
                return found
        return None
    if isinstance(before, list):
        if len(before) != len(after):
            return f"{path or '<root>'}: {len(before)} items became {len(after)}"
        for i, (b, a) in enumerate(zip(before, after, strict=True)):
            if (found := _shape_difference(b, a, f"{path}[{i}]")) is not None:
                return found
        return None
    return None if before == after else f"{path}: {before!r} became {after!r}"


def main(out_path: str) -> int:
    client = IBKRClient(Config.from_env())
    account = client.get_accounts()[0]
    account_id = str(account.get("accountId") or account.get("id"))
    conid = 265598  # AAPL — a contract, deliberately not a held position
    print(f"account: {account_id}", file=sys.stderr)

    calls: dict[str, Callable[[], Any]] = {
        "accounts": lambda: client.get_accounts(),
        "positions": lambda: client.get_positions(account_id),
        "account_summary": lambda: client.get_account_summary(account_id),
        "account_ledger": lambda: client.get_account_ledger(account_id),
        "account_meta": lambda: client.get_account_meta(account_id),
        "account_allocation": lambda: client.get_account_allocation(account_id),
        "combo_positions": lambda: client.get_combo_positions(account_id),
        "positions_by_conid": lambda: client.get_positions_by_conid(conid),
        "live_orders": lambda: client.get_live_orders(),
        "trades": lambda: client.get_trades(),
        "search_contract": lambda: client.search_contract("AAPL"),
        "contract_info": lambda: client.get_contract_info(conid),
        "secdef": lambda: client.get_secdef([conid]),
        "stocks": lambda: client.get_stocks(["AAPL"]),
        "currency_pairs": lambda: client.get_currency_pairs("USD"),
        # No exchange: SMART is an order router with no published hours and returns [],
        # which is why this endpoint was captured empty until 2026-09-16 (TOOL-R1).
        "trading_schedule": lambda: client.get_trading_schedule("STK", "AAPL"),
        "market_snapshot": lambda: client.get_market_snapshot([conid], ["31", "84", "86"]),
        "notifications": lambda: client.get_notifications(5),
        "delivery_options": lambda: client.get_delivery_options(),
        "unread_count": lambda: client.get_unread_count(),
        "alerts": lambda: client.get_alerts(account_id),
        "watchlists": lambda: client.get_watchlists(),
        "auth_status": lambda: client.get_auth_status(),
        "pnl": lambda: client.get_pnl(),
        "brokerage_accounts": lambda: client.get_brokerage_accounts(),
        "scanner_params": lambda: client.get_scanner_params(),
        "pa_periods": lambda: client.get_pa_periods([account_id]),
        # ---- second capture pass, 2026-09-17 (API-11's remaining 61) --------------
        # Read-only only. Nothing here writes, and no order or alert endpoint appears:
        # `get_order_preview` simulates but still POSTs an order body, so it is captured
        # only with the owner present and asking for it.
        "subaccounts": lambda: client.get_subaccounts(),
        "orders_raw": lambda: client.get_orders_raw(),
        "secdef_info": lambda: client.get_secdef_info(conid),
        "contract_algos": lambda: client.get_contract_algos(conid),
        "contract_rules": lambda: client.get_contract_rules(conid),
        "contract_info_and_rules": lambda: client.get_contract_info_and_rules(conid),
        "market_history": lambda: client.get_market_history(conid, period="1d", bar="1h"),
        "option_chain": lambda: client.get_option_chain("AAPL"),
        "mta_alert": lambda: client.get_mta_alert(),
        "pa_periods_raw": lambda: client.get_pa_periods_raw([account_id]),
        "pa_performance": lambda: client.get_pa_performance([account_id], "1M"),
        "pa_transactions": lambda: client.get_pa_transactions([account_id], [conid]),
        # Event contracts (`/forecast/*`) are deliberately NOT captured: this account holds
        # no event-contract subscription, so every call would record an error envelope rather
        # than a shape. Add them here the day the subscription exists (API-R4).
        # Futures: worth capturing while a futures session is open, since several of these
        # shapes differ from the equity ones.
        "futures": lambda: client.get_futures(["ES"]),
        # A single watchlist, keyed off the first one the account actually has — the list
        # endpoint is already captured, this is the detail shape.
        "watchlist": lambda: client.get_watchlist(_first_watchlist_id(client)),
    }

    captured: dict[str, Any] = {}
    failures = 0
    for name, call in calls.items():
        try:
            value = call()
        except Exception as exc:
            failures += 1
            print(f"  {name:<22} FAILED  {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        value = _as_payload(value)
        if name == "scanner_params":
            value = {"__truncated__": "first 2 entries of every list; see tests/fixtures/README.md", **truncate(value)}
        captured[name] = value
        size = len(value) if isinstance(value, (list, dict)) else 1
        print(f"  {name:<22} ok      ({type(value).__name__}, {size})", file=sys.stderr)

    redacted = redact_capture(captured)
    difference = _shape_difference(_shape(captured), _shape(redacted))
    if difference is not None:
        print(f"\nREDACTION CHANGED THE SHAPE — nothing written.\n  {difference}", file=sys.stderr)
        print("  Fix scripts/audit/redact_live_payload.py, then re-run.", file=sys.stderr)
        return 1

    with open(out_path, "w") as fh:
        json.dump(redacted, fh, indent=2, sort_keys=True)
        fh.write("\n")

    # Two assertions, because the one that existed before checked a single field class and
    # passed while nine others went out. `tests/security/test_published_identifiers.py`
    # holds the same properties against the committed file, so a hand-edit cannot restore
    # what this strips.
    written = open(out_path).read()
    leaked = ACCOUNT_ID_RE.findall(written)
    assert set(leaked) <= {"U1234567"}, f"un-redacted account numbers in the fixture: {sorted(set(leaked))}"
    for endpoint, payload in redacted.items():
        if endpoint in PUBLIC_ENDPOINTS:
            continue
        surviving = [v for v in _scalars(payload) if not _is_placeholder(v)]
        assert not surviving, f"{endpoint}: real values survived redaction: {surviving[:5]}"

    print(f"wrote {out_path}: {len(captured)} endpoints, {failures} failed", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures/ibkr_live_shapes.json"))
