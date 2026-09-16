"""Capture verbatim IBKR Client Portal responses as model test fixtures.

Run against a live, authenticated gateway. Writes the JSON consumed by
`tests/test_models_live_shapes.py`:

    source /path/to/.env
    python scripts/audit/capture_live_response_shapes.py tests/fixtures/ibkr_live_shapes.json

Account numbers are rewritten to U1234567 wherever they appear, in values and in keys
alike — `/pnl/partitioned` and `/iserver/accounts` both key sub-objects by account.
Nothing else is altered.

Two payloads are reduced after capture, and both are labelled in the fixture's README:
`scanner_params` (218 KB of static reference data) keeps the first two entries of every
list, and `market_snapshot` legitimately returns only `conid`/`conidEx` on a first call.

Run this in ONE process. `EndpointPacer`'s budget is per process while IBKR's limit is
per IP, so a second concurrent capture can earn the fifteen-minute penalty box.
"""

import json
import re
import sys
from collections.abc import Callable
from typing import Any

from ibkr_core_mcp import Config, IBKRClient

ACCOUNT_ID_RE = re.compile(r"\bU\d{6,9}\b")


def redact(obj: Any) -> Any:
    """Rewrite every account number in the payload, in keys as well as values."""
    if isinstance(obj, dict):
        return {ACCOUNT_ID_RE.sub("U1234567", k) if isinstance(k, str) else k: redact(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    if isinstance(obj, str):
        return ACCOUNT_ID_RE.sub("U1234567", obj)
    return obj


def truncate(obj: Any, keep: int = 2) -> Any:
    """Keep the first `keep` entries of every list, preserving the key structure."""
    if isinstance(obj, list):
        return [truncate(v, keep) for v in obj[:keep]]
    if isinstance(obj, dict):
        return {k: truncate(v, keep) for k, v in obj.items()}
    return obj


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
        "trading_schedule": lambda: client.get_trading_schedule("STK", "AAPL", "SMART"),
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
    }

    captured: dict[str, Any] = {}
    failures = 0
    for name, call in calls.items():
        try:
            value = redact(call())
        except Exception as exc:
            failures += 1
            print(f"  {name:<22} FAILED  {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        if name == "scanner_params":
            value = {"__truncated__": "first 2 entries of every list; see tests/fixtures/README.md", **truncate(value)}
        captured[name] = value
        size = len(value) if isinstance(value, (list, dict)) else 1
        print(f"  {name:<22} ok      ({type(value).__name__}, {size})", file=sys.stderr)

    with open(out_path, "w") as fh:
        json.dump(captured, fh, indent=2, sort_keys=True)
        fh.write("\n")

    leaked = ACCOUNT_ID_RE.findall(open(out_path).read())
    assert set(leaked) <= {"U1234567"}, f"un-redacted account numbers in the fixture: {sorted(set(leaked))}"

    print(f"wrote {out_path}: {len(captured)} endpoints, {failures} failed", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures/ibkr_live_shapes.json"))
