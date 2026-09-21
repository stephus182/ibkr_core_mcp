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


def _dated(days: int) -> int:
    """A YYYYMMDD int `days` from today — computed, never hardcoded (gap #58)."""
    from datetime import timedelta

    from ibkr_core_mcp.claude_tools import _today_date

    return int((_today_date() + timedelta(days=days)).strftime("%Y%m%d"))


@pytest.fixture
def typed_toolkit(toolkit):
    """A toolkit whose client returns what the real one now returns."""
    c = toolkit._client
    c.get_accounts.return_value = [{"accountId": "U1234567"}]
    c.search_contract.return_value = parse_many(Contract, LIVE["search_contract"])
    c.get_positions.return_value = parse_many(Position, LIVE["positions"])
    # `_get_positions` reads every page since API-17; `get_positions` is the single-page
    # call and stays stubbed for anything that still uses it directly.
    c.get_all_positions.return_value = parse_many(Position, LIVE["positions"])
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


# ---------------------------------------------------------------------------
# API-11, third and fourth tranches (2026-09-17)
# ---------------------------------------------------------------------------
#
# A typed return is NOT a dict. `isinstance(row, dict)` is False for an `IBKRResponse`,
# and three handlers filtered on exactly that — so typing `get_futures`,
# `get_secdef_info` and `get_contract_info` turned a full answer into an empty one with
# the whole unit suite green. None of the three helpers had a test; the mocks in the rest
# of this suite hand them dicts, which is the gap this file exists to close.


@pytest.fixture
def typed_contract_toolkit(toolkit):
    """A toolkit whose client returns the models the contract endpoints now return."""
    from ibkr_core_mcp.models import ContractDetails, FutureContract, MarketHistory, OptionChain, SecDefInfo

    c = toolkit._client
    # The capture's date fields are redacted to `1111111`, which is not a valid YYYYMMDD.
    # That was harmless while nothing read them, but front-month selection now asks whether a
    # contract can still be traded (gap #58), and a non-date can never answer yes. Give the
    # rows plausible ascending dates so this file keeps testing what it is about — typed rows
    # surviving the handlers — rather than failing on redaction.
    futures = [dict(r) for r in LIVE["futures"]]
    for offset, row in enumerate(futures):
        row["expirationDate"] = row["ltd"] = _dated(30 + offset * 90)
    c.get_futures.return_value = parse_many(FutureContract, futures)
    c.get_secdef_info.return_value = parse_one(SecDefInfo, LIVE["secdef_info"])
    c.get_contract_info.return_value = parse_one(ContractDetails, LIVE["contract_info"])
    c.get_market_history_paginated.return_value = parse_one(MarketHistory, LIVE["market_history"])
    c.get_option_chain.return_value = parse_one(OptionChain, LIVE["option_chain"])
    return toolkit


def test_get_futures_still_returns_its_rows_when_they_are_typed(typed_contract_toolkit):
    """`_sorted_with_front_month` filtered with `isinstance(r, dict)`, which dropped all 21."""
    text, _ = typed_contract_toolkit.execute("get_futures", {"symbols": ["ES"]})

    assert_tool_succeeded(text)
    rows = json.loads(text)
    assert len(rows) == len(LIVE["futures"]), "every row IBKR sent must survive the typed return"
    assert sum(1 for r in rows if r.get("front_month")) == 1, "exactly one row is the front month"


def test_the_listing_currency_is_still_read_from_a_typed_secdef_info(typed_contract_toolkit):
    """`_listing_currency` filtered with `isinstance(row, dict)` and answered None instead.

    A None here is not cosmetic: the toolkit must then say *currency unknown*, so a typed
    return silently downgraded every price it reports.
    """
    conid = LIVE["secdef_info"]["conid"]

    assert typed_contract_toolkit._listing_currency(conid) == LIVE["secdef_info"]["currency"]


def test_the_futures_identity_is_still_read_from_a_typed_contract_info(typed_contract_toolkit):
    """`_futures_identity` returned None for a typed `get_contract_info`, so the front-month
    row lost its `_contract` block — the block that exists so the model never guesses."""
    identity = typed_contract_toolkit._futures_identity(LIVE["contract_info"]["con_id"])

    assert identity is not None
    assert identity["local_symbol"] == LIVE["contract_info"]["local_symbol"]


def test_a_secdef_info_list_still_passes_through_untyped(typed_contract_toolkit):
    """`/iserver/secdef/info` answered a LIST on 2026-07-28 and an OBJECT on 2026-09-17.

    Both are still handled: `parse_one` hands a list back unchanged rather than raising, so
    the list branch of `_listing_currency` keeps working. Neither shape is assumed away.
    """
    typed_contract_toolkit._client.get_secdef_info.return_value = [{"conid": 265598, "currency": "MXN"}]

    assert typed_contract_toolkit._listing_currency(265598) == "MXN"


# ---------------------------------------------------------------------------
# The serialiser, not the four call sites that happened to break
# ---------------------------------------------------------------------------
#
# `json.dumps` does not know an `IBKRResponse`. `models.json_default` exists for exactly
# that and was added with the first tranche — but only the handlers that broke *then* were
# given it, so every later tranche re-opened the same hole. `get_alerts` shipped broken on
# this branch on 2026-09-17 and nothing noticed for a day. These four are the ones that
# were broken; `test_every_json_dumps_in_the_tool_layer_can_serialise_a_model` is the one
# that stops a fifth.


@pytest.fixture
def typed_serialising_toolkit(toolkit):
    """A toolkit whose client returns models on the paths that json.dumps a response."""
    from ibkr_core_mcp.models import Alert, ContractDetails, OptionChain, TradingSchedule

    c = toolkit._client
    c.get_alerts.return_value = parse_many(Alert, LIVE["alerts"])
    c.get_contract_info_and_rules.return_value = parse_one(ContractDetails, LIVE["contract_info_and_rules"])
    c.get_option_chain.return_value = parse_one(OptionChain, LIVE["option_chain"])
    c.get_trading_schedule.return_value = parse_many(TradingSchedule, LIVE["trading_schedule"])
    return toolkit


def test_get_alerts_serialises_its_typed_rows(typed_serialising_toolkit):
    """Broken on this branch since the 2026-09-17 `Alert` tranche."""
    text, _ = typed_serialising_toolkit.execute("get_alerts", {})

    assert_tool_succeeded(text)
    assert json.loads(text) == LIVE["alerts"]


def test_get_option_chain_serialises_its_typed_response(typed_serialising_toolkit):
    text, _ = typed_serialising_toolkit.execute("get_option_chain", {"symbol": "AAPL"})

    assert_tool_succeeded(text)
    assert json.loads(text) == LIVE["option_chain"]


def test_get_trading_schedule_serialises_its_typed_rows(typed_serialising_toolkit):
    text, _ = typed_serialising_toolkit.execute("get_trading_schedule", {"asset_class": "STK", "symbol": "AAPL"})

    assert_tool_succeeded(text)
    assert json.loads(text) == LIVE["trading_schedule"]


def test_every_json_dumps_in_the_tool_layer_can_serialise_a_model():
    """No bare `json.dumps` in the tool layer — every one must carry a `default=`.

    Four handlers serialised a client response with no `default=`, and each new typed
    method silently armed another. Listing the broken ones is not a fix: the next tranche
    adds the fifth. This reads the source instead, so the rule holds for code nobody has
    written yet.
    """
    import ast
    import pathlib

    import ibkr_core_mcp.claude_tools as tools_mod
    import ibkr_core_mcp.mcp_server as server_mod

    offenders = []
    for module in (tools_mod, server_mod):
        assert module.__file__, f"{module.__name__} has no file to read"
        path = pathlib.Path(module.__file__)
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "dumps"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "json"
                and not any(
                    kw.arg == "default" and isinstance(kw.value, ast.Name) and kw.value.id == "json_default"
                    for kw in node.keywords
                )
            ):
                offenders.append(f"{path.name}:{node.lineno}")

    assert not offenders, (
        "these json.dumps calls cannot render an IBKRResponse as the payload IBKR sent — "
        f"pass default=json_default: {offenders}"
    )
