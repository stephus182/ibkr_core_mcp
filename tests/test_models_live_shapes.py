"""Every response model, validated against what IBKR actually sent.

`tests/test_models.py` builds each model's input by hand, so it asserts that the model
agrees with itself. These tests read `tests/fixtures/ibkr_live_shapes.json` — captured
from a live authenticated gateway — so they can disagree with the model, and on
2026-09-16 four of the six did.

Assert on keys and types. The payloads come from one account at one moment, so the
instruments and values in them are not facts about IBKR.
"""

import json
from pathlib import Path

import pytest

from ibkr_core_mcp.models import AccountSummary, Contract, Notification, Order, Position, Trade

FIXTURES = Path(__file__).parent / "fixtures" / "ibkr_live_shapes.json"


@pytest.fixture(scope="module")
def live():
    return json.loads(FIXTURES.read_text())


def _first(live, key):
    """The first record of an endpoint's payload, with a vacuity guard."""
    payload = live[key]
    if isinstance(payload, list):
        assert payload, f"fixture {key!r} is empty — the test below would assert nothing"
        return payload[0]
    return payload


# ---------------------------------------------------------------------------
# Models that raised on real data
# ---------------------------------------------------------------------------


def test_order_validates_a_real_live_order(live):
    """IBKR returns orderId as an int; the model declared str and raised."""
    raw = _first(live, "live_orders")
    assert isinstance(raw["orderId"], int), "fixture no longer exercises the int case"

    order = Order.model_validate(raw)

    assert order.order_id == str(raw["orderId"])
    assert order.symbol == raw["ticker"]
    assert order.order_type == raw["orderType"]


def test_contract_validates_a_trsrv_secdef_row(live):
    """Contract's docstring names /trsrv/secdef, whose rows carry `ticker`, not `symbol`."""
    raw = _first(live, "secdef")
    assert "symbol" not in raw and "ticker" in raw, "fixture no longer exercises the ticker case"

    contract = Contract.model_validate(raw)

    assert contract.conid == raw["conid"]
    assert contract.symbol == raw["ticker"]


# ---------------------------------------------------------------------------
# Models that validated but carried nothing
# ---------------------------------------------------------------------------


def test_notification_carries_ibkr_fields(live):
    """/fyi/notifications returns D/ID/FC/MD/MS/R — the model read none of them.

    Source: https://www.interactivebrokers.com/docs/web-api/v1/endpoints/fy-is-and-notifications/get-a-list-of-notifications.md
    """
    raw = _first(live, "notifications")
    assert {"D", "ID", "MS", "MD", "R"} <= set(raw), "fixture no longer has IBKR's documented keys"

    note = Notification.model_validate(raw)

    assert note.id == raw["ID"]
    assert note.date == raw["D"]
    assert note.headline == raw["MS"]
    assert note.body == raw["MD"]
    assert note.is_read is bool(raw["R"])


def test_trade_time_is_populated(live):
    """The trades endpoint spells the timestamp `trade_time`; the model read `time`."""
    raw = _first(live, "trades")
    assert "time" not in raw and "trade_time" in raw, "fixture no longer exercises the alias"

    trade = Trade.model_validate(raw)

    assert trade.time == raw["trade_time"]


# ---------------------------------------------------------------------------
# Losslessness — a typed view must not throw IBKR's payload away
# ---------------------------------------------------------------------------


LOSSLESS_CASES = [
    (Contract, "search_contract"),
    (Contract, "secdef"),
    (Position, "positions"),
    (Trade, "trades"),
    (Order, "live_orders"),
    (AccountSummary, "account_summary"),
    (Notification, "notifications"),
]


@pytest.mark.parametrize(("model", "endpoint"), LOSSLESS_CASES, ids=lambda v: getattr(v, "__name__", v))
def test_model_keeps_every_field_ibkr_sent(live, model, endpoint):
    raw = _first(live, endpoint)
    assert len(raw) > len(model.model_fields), f"{endpoint} is not wider than {model.__name__} — nothing to lose"

    parsed = model.model_validate(raw)

    assert dict(parsed) == raw


@pytest.mark.parametrize(("model", "endpoint"), LOSSLESS_CASES, ids=lambda v: getattr(v, "__name__", v))
def test_model_supports_dict_access(live, model, endpoint):
    """Callers treated these responses as dicts for the package's whole life."""
    raw = _first(live, endpoint)
    key, value = next(iter(raw.items()))

    parsed = model.model_validate(raw)

    assert parsed[key] == value
    assert parsed.get(key) == value
    assert parsed.get("no-such-key-in-any-ibkr-payload") is None
    assert parsed.get("no-such-key-in-any-ibkr-payload", "fallback") == "fallback"
    assert key in parsed
    assert "no-such-key-in-any-ibkr-payload" not in parsed
    assert sorted(parsed.keys()) == sorted(raw)
    assert len(parsed) == len(raw)


def test_validation_does_not_mutate_the_callers_payload(live):
    """A guard, not a fix: validation never mutated the caller's dict, and must not start.

    The `_normalize` validators call `setdefault` on their input, and the new wrap
    validator snapshots it. Both work on copies today; this fails if either stops.
    """
    raw = _first(live, "positions")
    before = json.dumps(raw, sort_keys=True)

    Position.model_validate(raw)

    assert json.dumps(raw, sort_keys=True) == before


def test_contract_reads_the_company_name_from_a_secdef_row(live):
    """/trsrv/secdef publishes the company name as `name`; `fullName` is the ticker."""
    raw = _first(live, "secdef")
    assert raw["name"] != raw["fullName"], "fixture no longer distinguishes the two"

    contract = Contract.model_validate(raw)

    assert contract.description == raw["name"]
    assert contract.sec_type == raw["assetClass"]
    assert contract.exchange == raw["listingExchange"]
    assert contract.currency == raw["currency"]


def test_position_fields_read_the_live_payload(live):
    """Every named Position attribute, against a real portfolio row.

    Added because a mutation that broke the `mktValue` alias left the whole suite green:
    the losslessness tests read the raw payload, and nothing read the typed view.
    """
    raw = _first(live, "positions")
    assert {"conid", "contractDesc", "position", "mktPrice", "mktValue", "unrealizedPnl"} <= set(raw)

    position = Position.model_validate(raw)

    assert position.conid == raw["conid"]
    assert position.symbol == raw["contractDesc"]
    assert position.position == raw["position"]
    assert position.mkt_price == raw["mktPrice"]
    assert position.mkt_value == raw["mktValue"]
    assert position.unrealized_pnl == raw["unrealizedPnl"]
    assert position.realized_pnl == raw["realizedPnl"]


def test_account_summary_reduces_the_live_payload(live):
    """AccountSummary is a reduction; check it reduces the right keys."""
    raw = _first(live, "account_summary")
    assert isinstance(raw["netliquidation"], dict), "fixture no longer has the nested amount shape"

    summary = AccountSummary.model_validate(raw)

    assert summary.net_liquidation == raw["netliquidation"]["amount"]
    assert summary.total_cash == raw["totalcashvalue"]["amount"]
    assert summary["netliquidation"]["currency"], "the currency AccountSummary drops must stay reachable"


def test_account_summary_reports_absent_keys_as_none(live):
    """The measured response carries no P&L key; absent must not read as zero.

    /portfolio/{accountId}/summary publishes an open key/value structure — "a total of
    45-135 unique values" — and documents no profit-and-loss entry. The capture of
    2026-09-16 returned 108 keys, none of them matching *pnl*. Whether some other
    account or segment publishes one is not established, so the model reports what it
    found rather than substituting 0.0 for what it did not.

    Realised and unrealised P&L are published by /iserver/account/pnl/partitioned,
    which `IBKRClient.get_pnl()` returns as `upnl.{account}.{upl,dpl}`.

    Source: https://www.interactivebrokers.com/docs/web-api/v1/endpoints/portfolio/portfolio-summary.md
    """
    raw = _first(live, "account_summary")
    assert not [k for k in raw if "pnl" in k.lower()], "fixture now has a P&L key — re-read the endpoint"

    summary = AccountSummary.model_validate(raw)

    assert summary.unrealized_pnl is None
    assert summary.realized_pnl is None
    assert summary.net_liquidation is not None


def test_account_summary_treats_a_null_amount_as_absent(live):
    """IBKR documents `amount` as "May return null if price value not required".

    No key in the 2026-09-16 capture exercised that branch, so this payload is built
    from the endpoint's documented shape rather than from the wire — the one test here
    that is. It is the documented null, not an invented field.

    Source: https://www.interactivebrokers.com/docs/web-api/v1/endpoints/portfolio/portfolio-summary.md
    """
    raw = _first(live, "account_summary")
    assert not [k for k, v in raw.items() if isinstance(v, dict) and v.get("amount") is None], (
        "the capture now has a null amount — assert against it instead of the documented shape"
    )
    documented_null = dict(raw) | {"netliquidation": {"amount": None, "currency": "USD", "isNull": True}}

    summary = AccountSummary.model_validate(documented_null)

    assert summary.net_liquidation is None


def test_a_null_field_falls_back_to_the_default(live):
    """IBKR sends `null` for "not applicable", and that must not fail the whole record.

    Searching /iserver/secdef/search for AAPL returns four equity listings and a bond
    aggregate — `{"bondid": 4, "companyHeader": "Corporate Fixed Income",
    "conid": "2147483647", "symbol": null, "companyName": null, ...}`. A null is the
    absence of a value, so the typed attribute takes its default; IBKR's null stays
    readable through the mapping protocol.
    """
    rows = live["search_contract"]
    bond = next((r for r in rows if r.get("symbol") is None), None)
    assert bond is not None, "fixture no longer contains a row with a null field"

    contract = Contract.model_validate(bond)

    assert contract.symbol == ""
    assert contract.description == ""
    assert contract["symbol"] is None, "the null IBKR sent must stay readable"
    assert contract.conid == 2147483647


@pytest.mark.parametrize(("model", "endpoint"), LOSSLESS_CASES, ids=lambda v: getattr(v, "__name__", v))
def test_iterating_a_model_yields_ibkrs_keys(live, model, endpoint):
    """`for k in model` must mean what it means for the dict the model replaced.

    Pydantic's BaseModel iterates `(name, value)` pairs, which made `sorted(summary)` a
    list of tuples and broke a live test that had read the endpoint's keys that way for
    months. Everything else here — `in`, `len`, `keys`, `get`, `[]` — already spoke the
    mapping protocol, so iteration disagreeing with all of them was a trap.
    """
    raw = _first(live, endpoint)

    parsed = model.model_validate(raw)

    assert list(parsed) == list(raw)
    assert sorted(parsed) == sorted(raw)
    assert {k: parsed[k] for k in parsed} == raw


# ── The mapping surface that had no test ───────────────────────────────────────
#
# `IBKRResponse` was added by this audit so a typed return could never narrow a 51-key
# position to seven fields. `test_model_supports_dict_access` covers `keys()`,
# `__getitem__`, `get()`, `__contains__` and `__len__` — and not `items()`, `values()` or
# the public `.raw` property, which were 3 of the 6 uncovered lines in `models.py` when
# `docs/test-coverage.md` was re-measured. All three behave correctly; nothing pinned them.


@pytest.mark.parametrize(("model", "endpoint"), LOSSLESS_CASES, ids=lambda v: getattr(v, "__name__", v))
def test_items_and_values_agree_with_what_ibkr_sent(live, model, endpoint):
    raw = _first(live, endpoint)
    parsed = model.model_validate(raw)

    assert dict(parsed.items()) == raw
    assert sorted(parsed.values(), key=repr) == sorted(raw.values(), key=repr)
    assert list(parsed.keys()) == [k for k, _ in parsed.items()]


@pytest.mark.parametrize(("model", "endpoint"), LOSSLESS_CASES, ids=lambda v: getattr(v, "__name__", v))
def test_raw_is_a_copy_of_the_payload_and_not_a_view(live, model, endpoint):
    """`.raw` is documented as "a copy of the response exactly as IBKR sent it". Both
    halves matter: a view would let a caller mutate the model's own record of the wire."""
    raw = _first(live, endpoint)
    parsed = model.model_validate(raw)

    assert parsed.raw == raw
    parsed.raw["injected-by-the-caller"] = True
    assert "injected-by-the-caller" not in parsed.raw, ".raw handed out a live reference"
    assert "injected-by-the-caller" not in raw, ".raw aliased the caller's own dict"


# ---------------------------------------------------------------------------
# API-11, second tranche — models derived from the capture, never from a guess
# ---------------------------------------------------------------------------


def test_account_validates_a_real_portfolio_account(live):
    """`/portfolio/accounts` rows carry both `accountId` and `id`, and they match here."""
    from ibkr_core_mcp.models import Account

    raw = _first(live, "accounts")
    account = Account.model_validate(raw)

    assert account.account_id == raw["accountId"]
    assert account.account_type == raw["type"], "IBKR's `type` must not shadow a Python builtin"
    assert account.currency == raw["currency"]
    assert dict(account) == raw, "the mapping protocol must round-trip the payload"


def test_one_account_model_serves_both_endpoints(live):
    """`/portfolio/accounts` rows and `/portfolio/{id}/meta` carry identical keys — measured
    2026-09-17, so one model serves both rather than two that can drift apart."""
    from ibkr_core_mcp.models import Account

    row, meta = _first(live, "accounts"), _first(live, "account_meta")
    assert set(row) == set(meta), "the two endpoints no longer share a shape; split the model"

    assert Account.model_validate(meta).account_id == meta["accountId"]


def test_auth_status_validates_a_real_session(live):
    """The four flags a caller branches on are booleans, and `competing` is the one that
    means another session has taken the gateway."""
    from ibkr_core_mcp.models import AuthStatus

    raw = _first(live, "auth_status")
    status = AuthStatus.model_validate(raw)

    for flag in ("authenticated", "connected", "competing"):
        assert isinstance(raw[flag], bool), f"fixture no longer exercises {flag} as a bool"
        assert getattr(status, flag) is raw[flag]
    assert status.server_info == raw["serverInfo"]


def test_alert_keeps_ibkrs_enum_ints_as_ints(live):
    """`alert_active` and `alert_repeatable` are IBKR enum ints (0/1) while `alert_triggered`
    is a real bool — measured, in the same record. Declaring the first two as `bool` would
    silently rewrite 0/1 into False/True and lose which spelling IBKR used, the mistake the
    alert-body work already had to undo once."""
    from ibkr_core_mcp.models import Alert

    raw = _first(live, "alerts")
    assert isinstance(raw["alert_active"], int) and not isinstance(raw["alert_active"], bool)
    assert isinstance(raw["alert_triggered"], bool), "fixture no longer exercises the asymmetry"

    alert = Alert.model_validate(raw)

    assert alert.alert_active == raw["alert_active"]
    assert type(alert.alert_active) is int
    assert alert.alert_triggered is raw["alert_triggered"]
    assert alert.order_id == str(raw["order_id"]), "the id is re-used in a URL path, so it is text"


def test_watchlist_keeps_a_dotted_id_as_text(live):
    """Watchlist ids look numeric and are not — `"1111.11"` here. Declaring `int` or `float`
    would corrupt the value that goes back into `/iserver/watchlist?id=`."""
    from ibkr_core_mcp.models import Watchlist

    raw = _first(live, "watchlists")
    assert isinstance(raw["id"], str), "fixture no longer exercises the string id"

    watchlist = Watchlist.model_validate(raw)

    assert watchlist.id == raw["id"]
    assert watchlist.name == raw["name"]
    assert watchlist.read_only is raw["read_only"]


def test_currency_pair_validates_a_real_pair(live):
    """`/iserver/currency/pairs` — `ccyPair` is the quote currency, `symbol` the full pair."""
    from ibkr_core_mcp.models import CurrencyPair

    raw = _first(live, "currency_pairs")
    pair = CurrencyPair.model_validate(raw)

    assert pair.ccy_pair == raw["ccyPair"]
    assert pair.conid == raw["conid"]
    assert pair.symbol == raw["symbol"]
