"""Tool handlers, fed the typed returns `client.py` produces as of 2026-09-16.

Six client methods now return models from `models.py` (audit finding API-11). The models
are mappings over exactly what IBKR sent, so `.get`, `[]`, `in`, `len` and iteration all
carry over — but `json.dumps` does not know them, and a handler that serialises a
response fails where it used to work.

The rest of the suite could not see that: `toolkit._client` is a MagicMock, so every
test hands its handler whatever it wrote itself, which is always a dict. These tests
hand the handlers the real thing — models built from a captured live response.
"""

import json
from pathlib import Path

import pytest

from ibkr_core_mcp.models import AccountSummary, Contract, Notification, Order, Position, Trade, parse_many, parse_one
from tests.claude_tools.conftest import assert_tool_succeeded

LIVE = json.loads((Path(__file__).parents[1] / "fixtures" / "ibkr_live_shapes.json").read_text())


@pytest.fixture
def typed_toolkit(toolkit):
    """A toolkit whose client returns what the real one now returns."""
    c = toolkit._client
    c.get_accounts.return_value = [{"accountId": "U1234567"}]
    c.search_contract.return_value = parse_many(Contract, LIVE["search_contract"])
    c.get_positions.return_value = parse_many(Position, LIVE["positions"])
    c.get_trades.return_value = parse_many(Trade, LIVE["trades"])
    c.get_live_orders.return_value = parse_many(Order, LIVE["live_orders"])
    c.get_notifications.return_value = parse_many(Notification, LIVE["notifications"])
    c.get_unread_count.return_value = 3
    c.get_account_summary.return_value = parse_one(AccountSummary, LIVE["account_summary"])
    return toolkit


@pytest.mark.parametrize(
    ("tool", "inputs"),
    [
        ("search_contract", {"symbol": "AAPL"}),
        ("get_positions", {}),
        ("get_account_summary", {}),
        ("get_notifications", {}),
        ("get_live_orders", {}),
        ("get_trades", {"source": "live"}),
    ],
)
def test_a_handler_survives_the_typed_return(typed_toolkit, tool, inputs):
    text, _figure = typed_toolkit.execute(tool, inputs)

    assert_tool_succeeded(text)
    assert "not JSON serializable" not in text


def test_search_contract_emits_every_field_ibkr_sent(typed_toolkit):
    """The non-STK branch json.dumps the response — STK goes through the resolver.

    IND and BOND still pass through /iserver/secdef/search unchanged, so that is the one
    path where a Contract model reaches json.dumps.
    """
    text, _ = typed_toolkit.execute("search_contract", {"symbol": "AAPL", "sec_type": "IND"})

    assert_tool_succeeded(text)
    assert json.loads(text) == LIVE["search_contract"]


def test_get_positions_reads_the_typed_rows(typed_toolkit):
    text, _ = typed_toolkit.execute("get_positions", {})

    assert_tool_succeeded(text)
    for row in LIVE["positions"]:
        if row["position"]:
            assert row["contractDesc"] in text


def test_get_notifications_reads_ibkrs_own_field_names(typed_toolkit):
    """Before the model fix every notification rendered blank: the model read
    id/date/headline/body while /fyi/notifications sends D/ID/MS/MD/R."""
    text, _ = typed_toolkit.execute("get_notifications", {})

    assert_tool_succeeded(text)
    assert LIVE["notifications"][0]["MS"] in text


def test_notifications_survive_a_failing_unread_count(typed_toolkit):
    """The list is the answer; the count is decoration, and must not take it down.

    `/fyi/unreadnumber` returned `HTTP 423 {"status":"waiting for reply"}` on four
    consecutive attempts against a healthy authenticated gateway on 2026-09-16, while
    `/fyi/notifications` answered normally throughout. The handler called it unguarded,
    so a notification list that had arrived would have been discarded and the tool would
    have reported an error instead.
    """
    from ibkr_core_mcp.exceptions import IBKRAPIError

    typed_toolkit._client.get_unread_count.side_effect = IBKRAPIError("HTTP 423", status_code=423)

    text, _ = typed_toolkit.execute("get_notifications", {})

    assert_tool_succeeded(text)
    assert LIVE["notifications"][0]["MS"] in text
