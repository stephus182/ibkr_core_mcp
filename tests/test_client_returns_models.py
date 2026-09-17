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
