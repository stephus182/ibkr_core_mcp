"""The client's return types, driven by responses IBKR actually sent.

`client.py`'s module docstring has claimed since the package was written that it returns
"typed models from `models.py` where the shape is stable". Until 2026-09-16 not one of
its 74 methods did (audit finding API-11). These tests pin the ones that now do.

Each stub is a payload from `tests/fixtures/ibkr_live_shapes.json`, so a model that
cannot parse a real response fails here rather than in production. Every assertion also
checks the response survives the trip: `dict(result) == raw`. A typed view that narrows
a 51-key position to seven fields would be a worse defect than the missing types.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ibkr_core_mcp.models import AccountSummary, Contract, Notification, Order, Position, Trade

FIXTURES = Path(__file__).parent / "fixtures" / "ibkr_live_shapes.json"


@pytest.fixture(scope="module")
def live():
    return json.loads(FIXTURES.read_text())


def _respond(client, payload):
    """Patch the session so every GET returns `payload`."""
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = payload
    return patch.object(client._session, "get", return_value=response)


def test_search_contract_returns_contracts(client, live):
    raw = live["search_contract"]
    with _respond(client, raw):
        result = client.search_contract("AAPL")

    assert [type(c) for c in result] == [Contract] * len(raw)
    assert [dict(c) for c in result] == raw
    assert result[0].symbol == raw[0]["symbol"]


def test_get_secdef_returns_contracts(client, live):
    raw = live["secdef"]
    with _respond(client, raw):
        result = client.get_secdef([265598])

    assert [type(c) for c in result] == [Contract] * len(raw)
    assert [dict(c) for c in result] == raw
    assert result[0].symbol == raw[0]["ticker"], "secdef rows spell the symbol `ticker`"


def test_get_positions_returns_positions(client, live):
    raw = live["positions"]
    with _respond(client, raw):
        result = client.get_positions("U1234567")

    assert [type(p) for p in result] == [Position] * len(raw)
    assert [dict(p) for p in result] == raw
    assert len(result[0]) > 40, "the 50-odd keys IBKR sends must survive the typed view"
    assert result[0].mkt_value == raw[0]["mktValue"]


def test_get_account_summary_returns_a_summary(client, live):
    raw = live["account_summary"]
    with _respond(client, raw):
        result = client.get_account_summary("U1234567")

    assert type(result) is AccountSummary
    assert dict(result) == raw
    assert result.net_liquidation == raw["netliquidation"]["amount"]
    assert result["netliquidation"]["currency"] == "USD", "the currency the model drops stays readable"


def test_get_notifications_returns_notifications(client, live):
    raw = live["notifications"]
    with _respond(client, raw):
        result = client.get_notifications(5)

    assert [type(n) for n in result] == [Notification] * len(raw)
    assert [dict(n) for n in result] == raw
    assert result[0].headline == raw[0]["MS"]


def test_get_live_orders_returns_orders(client, live):
    raw = live["live_orders"]
    with _respond(client, {"orders": raw, "snapshot": True}):
        result = client.get_live_orders()

    assert [type(o) for o in result] == [Order] * len(raw)
    assert [dict(o) for o in result] == raw
    assert result[0].order_id == str(raw[0]["orderId"])


def test_get_trades_returns_trades(client, live):
    raw = live["trades"]
    with _respond(client, raw):
        result = client.get_trades()

    assert [type(t) for t in result] == [Trade] * len(raw)
    assert [dict(t) for t in result] == raw
    assert result[0].time == raw[0]["trade_time"]


def test_a_malformed_record_does_not_lose_the_whole_response(client):
    """One unparseable row must not cost the caller the rows that were fine.

    IBKR adds fields without notice and has shipped rows missing ones it documents as
    required. Dropping the batch would turn a partial oddity into "you have no
    positions" — the shape of defect this audit found in market history and in the
    three endpoints that returned [] for data that had arrived.
    """
    good = {"conid": 265598, "contractDesc": "AAPL", "position": 10.0, "mktValue": 2300.0}
    bad = {"conid": 8314, "contractDesc": "IBM", "position": "not a number"}
    with _respond(client, [good, bad]):
        result = client.get_positions("U1234567")

    assert [type(p) for p in result] == [Position, dict]
    assert dict(result[0]) == good
    assert result[1] == bad, "an unparseable row is passed through untouched, never dropped"


# ---------------------------------------------------------------------------
# API-11, second tranche (2026-09-17)
# ---------------------------------------------------------------------------


def test_get_accounts_returns_accounts(client, live):
    from ibkr_core_mcp.models import Account

    raw = live["accounts"]
    with _respond(client, raw):
        result = client.get_accounts()

    assert [type(a) for a in result] == [Account] * len(raw)
    assert [dict(a) for a in result] == raw
    assert result[0].account_id == raw[0]["accountId"]


def test_get_account_meta_returns_an_account(client, live):
    from ibkr_core_mcp.models import Account

    raw = live["account_meta"]
    with _respond(client, raw):
        result = client.get_account_meta("U1234567")

    assert type(result) is Account
    assert dict(result) == raw


def test_get_subaccounts_returns_accounts(client, live):
    """`/portfolio/subaccounts` rows carry the same 24 keys as `/portfolio/accounts`."""
    from ibkr_core_mcp.models import Account

    raw = live["subaccounts"]
    with _respond(client, raw):
        result = client.get_subaccounts()

    assert [type(a) for a in result] == [Account] * len(raw)
    assert [dict(a) for a in result] == raw
    assert result[0].account_id == raw[0]["accountId"]


def test_get_auth_status_returns_a_status(client, live):
    from ibkr_core_mcp.models import AuthStatus

    raw = live["auth_status"]
    with _respond(client, raw):
        result = client.get_auth_status()

    assert type(result) is AuthStatus
    assert dict(result) == raw
    assert result.authenticated is raw["authenticated"]


def test_get_alerts_returns_alerts(client, live):
    from ibkr_core_mcp.models import Alert

    raw = live["alerts"]
    with _respond(client, raw):
        result = client.get_alerts("U1234567")

    assert [type(a) for a in result] == [Alert] * len(raw)
    assert [dict(a) for a in result] == raw


def test_get_currency_pairs_returns_pairs(client, live):
    from ibkr_core_mcp.models import CurrencyPair

    raw = live["currency_pairs"]
    with _respond(client, raw):
        result = client.get_currency_pairs("USD")

    assert [type(p) for p in result] == [CurrencyPair] * len(raw)
    assert [dict(p) for p in result] == raw


def test_get_watchlists_returns_watchlists_from_both_shapes(client, live):
    """IBKR wraps the lists in `{"data": {"user_lists": [...]}}` and has never sent a bare
    array — the bare branch is tolerance only. **Both are driven here**, because a mutation
    that removed the typing from the wrapped branch alone survived the suite on 2026-09-17:
    the annotation still named the model and nothing checked the value.
    """
    from ibkr_core_mcp.models import Watchlist

    raw = live["watchlists"]

    with _respond(client, {"data": {"user_lists": raw}, "action": "content"}):
        wrapped = client.get_watchlists()
    assert [type(w) for w in wrapped] == [Watchlist] * len(raw), "the wrapped shape is the real one"
    assert [dict(w) for w in wrapped] == raw

    with _respond(client, raw):
        bare = client.get_watchlists()
    assert [type(w) for w in bare] == [Watchlist] * len(raw), "the tolerance branch must type too"


def test_get_all_positions_returns_positions(client, live):
    """The paging helper added for API-17 was annotated `list[Position | dict]` and never
    had its type driven — found 2026-09-17 by the coverage guard below, on its first run.

    Two pages: a full one, then an empty one to end the walk.
    """
    raw = live["positions"]
    responses = []
    empty: list[dict[str, object]] = []
    for payload in (raw, empty):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = payload
        responses.append(response)

    with patch.object(client._session, "get", side_effect=responses):
        result = client.get_all_positions("U1234567")

    assert [type(p) for p in result] == [Position] * len(raw)
    assert [dict(p) for p in result] == raw


def test_every_method_annotated_as_returning_a_model_is_driven_here():
    """The gap that let the survivor through: every guard checked the *annotation*.

    Removing `parse_many(Watchlist, ...)` from `client.py` while leaving the return
    annotation in place passed the whole suite — the module-docstring guard, the
    api-reference guard and mypy all read the label, and nothing read the value. This test
    closes that by requiring a behavioural test in this file for each typed method, so a
    new one cannot be added with its type unproven.
    """
    import ast

    import ibkr_core_mcp.client as client_mod

    package = Path(client_mod.__file__).parent
    model_tree = ast.parse((package / "models.py").read_text())
    models = {
        n.name
        for n in ast.walk(model_tree)
        if isinstance(n, ast.ClassDef) and any(isinstance(b, ast.Name) and b.id == "IBKRResponse" for b in n.bases)
    }

    client_tree = ast.parse((package / "client.py").read_text())
    annotated = {
        n.name
        for n in ast.walk(client_tree)
        if isinstance(n, ast.FunctionDef)
        and not n.name.startswith("_")
        and n.returns is not None
        and any(m in ast.unparse(n.returns) for m in models)
    }

    own = ast.parse(Path(__file__).read_text())
    driven = {
        node.func.attr
        for node in ast.walk(own)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "client"
    }

    assert annotated, "no method is annotated as returning a model — update or remove this guard"
    missing = sorted(annotated - driven)
    assert not missing, (
        f"these methods say they return a model but no test here proves they do: {missing}. "
        "An annotation is a label; only driving the method checks the value."
    )


# ---------------------------------------------------------------------------
# API-11, third tranche (2026-09-17) — the contract family
# ---------------------------------------------------------------------------


def _respond_post(client, payload):
    """Patch the session so every POST returns `payload`."""
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = payload
    return patch.object(client._session, "post", return_value=response)


def test_get_secdef_info_returns_secdef_info(client, live):
    from ibkr_core_mcp.models import SecDefInfo

    raw = live["secdef_info"]
    with _respond(client, raw):
        result = client.get_secdef_info(265598)

    assert type(result) is SecDefInfo
    assert dict(result) == raw
    assert result.conid == raw["conid"]


def test_get_contract_info_returns_contract_details(client, live):
    from ibkr_core_mcp.models import ContractDetails

    raw = live["contract_info"]
    with _respond(client, raw):
        result = client.get_contract_info(265598)

    assert type(result) is ContractDetails
    assert dict(result) == raw
    assert result.conid == raw["con_id"], "IBKR spells it con_id on this endpoint"


def test_get_contract_info_and_rules_returns_contract_details(client, live):
    from ibkr_core_mcp.models import ContractDetails

    raw = live["contract_info_and_rules"]
    with _respond(client, raw):
        result = client.get_contract_info_and_rules(265598)

    assert type(result) is ContractDetails
    assert dict(result) == raw
    assert result.rules, "the rules block must reach the caller"


def test_get_contract_rules_returns_contract_rules(client, live):
    from ibkr_core_mcp.models import ContractRules

    raw = live["contract_rules"]
    with _respond_post(client, raw):
        result = client.get_contract_rules(265598)

    assert type(result) is ContractRules
    assert dict(result) == raw
    assert result.order_types == raw["orderTypes"]


def test_get_futures_returns_future_contracts(client, live):
    from ibkr_core_mcp.models import FutureContract

    raw = live["futures"]
    with _respond(client, {"ES": raw}):
        result = client.get_futures(["ES"])

    assert [type(f) for f in result] == [FutureContract] * len(raw)
    assert [dict(f) for f in result] == raw
    assert result[0].expiration_date == raw[0]["expirationDate"]


def test_get_stocks_returns_stock_search_results(client, live):
    from ibkr_core_mcp.models import StockSearchResult

    raw = live["stocks"]
    with _respond(client, {"AAPL": raw}):
        result = client.get_stocks(["AAPL"])

    assert [type(s) for s in result] == [StockSearchResult] * len(raw)
    assert [dict(s) for s in result] == raw
    assert result[0].contracts == raw[0]["contracts"]


def test_get_contract_algos_returns_algos(client, live):
    from ibkr_core_mcp.models import Algo

    raw = live["contract_algos"]
    with _respond(client, {"algos": raw}):
        result = client.get_contract_algos(265598)

    assert [type(a) for a in result] == [Algo] * len(raw)
    assert [dict(a) for a in result] == raw


def test_get_trading_schedule_returns_schedules(client, live):
    from ibkr_core_mcp.models import TradingSchedule

    raw = live["trading_schedule"]
    assert raw, "the fixture's schedule is empty — this test would assert nothing"
    with _respond(client, raw):
        result = client.get_trading_schedule("STK", "AAPL")

    assert [type(s) for s in result] == [TradingSchedule] * len(raw)
    assert [dict(s) for s in result] == raw
    assert result[0].id == raw[0]["id"]


def test_get_trading_schedule_answers_a_list_when_ibkr_sends_an_object(client):
    """The annotation says `list`; the method returned whatever arrived until 2026-09-17."""
    with _respond(client, {"error": "Bad Request"}):
        assert client.get_trading_schedule("STK", "AAPL") == []


# ---------------------------------------------------------------------------
# API-11, fourth tranche (2026-09-17) — market data
# ---------------------------------------------------------------------------


def test_get_market_history_returns_market_history(client, live):
    from ibkr_core_mcp.models import MarketHistory

    raw = live["market_history"]
    with _respond(client, raw):
        result = client.get_market_history(265598, period="1d", bar="1h")

    assert type(result) is MarketHistory
    assert dict(result) == raw
    assert result.data == raw["data"]
    assert result.high == raw["high"], "the %h/%v/%t composite must arrive unchanged"


def test_get_market_history_paginated_returns_market_history(client, live):
    from ibkr_core_mcp.models import MarketHistory

    raw = live["market_history"]
    with _respond(client, raw):
        result = client.get_market_history_paginated(265598, period="1d", bar="1h")

    assert type(result) is MarketHistory
    assert result.data, "the merged bars must reach the caller"


def test_get_market_history_paginated_still_answers_an_empty_dict_for_no_bars(client, live):
    """`{}` means "no bars" and must stay falsy — a caller's `if not history:` depends on it.

    Left as a plain dict rather than an empty model on purpose: `MarketHistory()` would be
    a valid, truthy object claiming a symbol of `""` and zero points, which reads like an
    answer. See API-R5 for the same distinction inside `IBKRResponse`.
    """
    with _respond(client, {"data": []}):
        result = client.get_market_history_paginated(265598, period="5y", bar="1d")

    assert result == {}
    assert not result


def test_get_option_chain_returns_an_option_chain(client, live):
    from ibkr_core_mcp.models import OptionChain

    search = [{"conid": 265598, "sections": [{"secType": "OPT", "months": "JAN26;FEB26"}]}]
    strikes = {"call": [100.0, 105.0], "put": [100.0, 105.0]}
    response = MagicMock()
    response.status_code = 200
    response.json.side_effect = [search, strikes]
    with patch.object(client._session, "get", return_value=response):
        result = client.get_option_chain("aapl")

    assert type(result) is OptionChain
    assert result.symbol == "AAPL"
    assert result.conid == 265598
    assert result.month == "JAN26"
    assert result.months == ["JAN26", "FEB26"]
    assert result.call == strikes["call"]
    assert dict(result)["put"] == strikes["put"]


# ---------------------------------------------------------------------------
# API-11, fifth tranche (2026-09-17) — session, watchlist detail, MTA alert
# ---------------------------------------------------------------------------


def test_get_brokerage_accounts_returns_a_session(client, live):
    from ibkr_core_mcp.models import BrokerageSession

    raw = live["brokerage_accounts"]
    with _respond(client, raw):
        result = client.get_brokerage_accounts()

    assert type(result) is BrokerageSession
    assert dict(result) == raw
    assert result.selected_account == raw["selectedAccount"]
    assert result.is_paper is raw["isPaper"]


def test_get_watchlist_returns_a_watchlist_detail(client, live):
    from ibkr_core_mcp.models import WatchlistDetail

    raw = live["watchlist"]
    with _respond(client, raw):
        result = client.get_watchlist("1111.11")

    assert type(result) is WatchlistDetail
    assert dict(result) == raw
    assert result.instruments == raw["instruments"]


def test_get_mta_alert_returns_an_mta_alert(client, live):
    from ibkr_core_mcp.models import MTAAlert

    raw = live["mta_alert"]
    with _respond(client, raw):
        result = client.get_mta_alert()

    assert type(result) is MTAAlert
    assert dict(result) == raw
    assert result.order_id == str(raw["order_id"])


# ---------------------------------------------------------------------------
# API-11's closing property
# ---------------------------------------------------------------------------

# Why a captured endpoint may return no model. Every entry is a DECISION with a reason,
# not a to-do: the guard below fails when a captured endpoint appears in neither set, so a
# new capture forces the decision to be made rather than skipped. The oracle itself —
# which endpoints exist, which method each was captured from, which methods return models
# — is derived from the capture script, `client.py` and `models.py`. This list is only the
# answer to "and why not this one", which is the part no derivation can supply.
_NO_MODEL_BY_DESIGN = {
    "account_allocation": "three blocks keyed by asset class, group and sector — their own keys are the data",
    "account_ledger": "keyed by currency; the currencies are the data",
    "delivery_options": "keyed by delivery channel",
    "pnl": "one key, `upnl`, keyed by `<account>.Core`",
    "pa_performance": "cps/nav/tpps are nested open blocks, and the scalars beside them are IBKR internals",
    "scanner_params": "an open catalogue of scanner definitions, not a record",
    "market_snapshot": "fields are IBKR numeric codes (31, 84, 86), so the keys vary per request",
    "orders_raw": "a `_raw` method exists to hand back exactly what arrived",
    "pa_periods_raw": "a `_raw` method exists to hand back exactly what arrived",
    "pa_periods": "returns list[str] — there is no object to model",
    "combo_positions": "the capture is empty; a model could only be tested against a shape we invented",
    "pa_transactions": "the capture is empty; a model could only be tested against a shape we invented",
    "positions_by_conid": "the capture is empty; a model could only be tested against a shape we invented",
}


def _capture_endpoint_methods():
    """fixture key -> client method, read from the capture script's own endpoint table."""
    import ast

    tree = ast.parse((Path(__file__).parents[1] / "scripts" / "audit" / "capture_live_response_shapes.py").read_text())
    mapping = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values, strict=True):
            if not (isinstance(key, ast.Constant) and isinstance(key.value, str) and isinstance(value, ast.Lambda)):
                continue
            for call in ast.walk(value):
                if (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and isinstance(call.func.value, ast.Name)
                    and call.func.value.id == "client"
                ):
                    mapping[key.value] = call.func.attr
                    break
    return mapping


def test_every_captured_endpoint_is_typed_or_reasoned(live):
    """API-11's closing property: no captured endpoint is untyped by accident.

    The finding was "zero of 74 methods return a Pydantic model" while the docs claimed
    otherwise. Typing every method was never the goal — `CLAUDE.md` says to return a model
    "when the response has a shape worth naming; otherwise return the decoded response and
    annotate it as such". The defect was that "otherwise" had never been decided for
    anything; it was just what happened.

    So this asserts the decision exists, endpoint by endpoint, against the endpoints we can
    actually check: the ones in the live capture. A method with no captured response cannot
    be typed honestly at all — a model tested against a dict we wrote proves only that the
    model agrees with itself, which is how all six original models shipped broken.

    Both directions, so a stale exclusion cannot outlive its reason either.
    """
    import ast
    import re

    models = {
        node.name
        for node in ast.walk(ast.parse((Path(__file__).parents[1] / "ibkr_core_mcp" / "models.py").read_text()))
        if isinstance(node, ast.ClassDef)
        and any(isinstance(b, ast.Name) and b.id == "IBKRResponse" for b in node.bases)
    }
    assert len(models) >= 20, f"only {len(models)} models found — the derivation is broken"

    returns = {
        node.name: ast.unparse(node.returns)
        for node in ast.walk(ast.parse((Path(__file__).parents[1] / "ibkr_core_mcp" / "client.py").read_text()))
        if isinstance(node, ast.FunctionDef) and node.returns is not None
    }
    captured = _capture_endpoint_methods()
    assert len(captured) >= 40, f"only {len(captured)} endpoints read from the capture script"

    undecided, stale = [], []
    for key in sorted(live):
        method = captured.get(key)
        assert method, f"fixture holds {key!r} but the capture script no longer records how it was captured"
        typed = any(re.search(rf"\b{m}\b", returns.get(method, "")) for m in models)
        if typed and key in _NO_MODEL_BY_DESIGN:
            stale.append(f"{key} ({method}) returns a model now — drop its exclusion")
        elif not typed and key not in _NO_MODEL_BY_DESIGN:
            undecided.append(f"{key} ({method}) -> {returns.get(method)}")

    for key in _NO_MODEL_BY_DESIGN:
        if key not in live:
            stale.append(f"{key} is excluded but is no longer in the fixture")

    assert not undecided, (
        "these captured endpoints return no model and no reason is recorded. Either return "
        "a model from models.py, tested against the capture, or add the endpoint to "
        f"_NO_MODEL_BY_DESIGN with why: {undecided}"
    )
    assert not stale, f"_NO_MODEL_BY_DESIGN is out of date: {stale}"
