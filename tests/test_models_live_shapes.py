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
