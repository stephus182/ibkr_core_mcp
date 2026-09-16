from unittest.mock import MagicMock

import pytest

from .claude_tools.conftest import assert_tool_failed, assert_tool_succeeded


@pytest.fixture
def toolkit(mock_config):
    from ibkr_core_mcp.claude_tools import ClaudeToolkit

    return ClaudeToolkit(MagicMock(), MagicMock(), MagicMock(), mock_config)


@pytest.fixture
def store(tmp_db, mock_config):
    from ibkr_core_mcp.store import SQLiteStore

    return SQLiteStore(mock_config)


async def _list_tool_names(server) -> list[str]:
    """Drive the low-level tools/list handler and narrow its ServerResult union."""
    from mcp.types import ListToolsRequest, ListToolsResult

    req = ListToolsRequest(method="tools/list")
    result = await server.request_handlers[type(req)](req)
    assert isinstance(result.root, ListToolsResult)
    return [t.name for t in result.root.tools]


async def _read_resource_text(server, uri: str) -> str:
    """Drive the low-level resources/read handler and narrow its ServerResult union."""
    from mcp.types import ReadResourceRequest, ReadResourceRequestParams, ReadResourceResult, TextResourceContents
    from pydantic import AnyUrl

    req = ReadResourceRequest(method="resources/read", params=ReadResourceRequestParams(uri=AnyUrl(uri)))
    result = await server.request_handlers[type(req)](req)
    assert isinstance(result.root, ReadResourceResult)
    content = result.root.contents[0]
    assert isinstance(content, TextResourceContents)
    return content.text


def test_mcp_server_importable():
    from ibkr_core_mcp.mcp_server import build_server

    assert callable(build_server)


async def test_server_has_44_tools(toolkit, store):
    from ibkr_core_mcp.claude_tools import TOOL_DEFINITIONS
    from ibkr_core_mcp.mcp_server import build_server

    server = build_server(toolkit, store)
    tool_names = await _list_tool_names(server)
    assert len(tool_names) == len(TOOL_DEFINITIONS) + 2  # +2 for add_price_alert, get_price_alerts
    assert "add_price_alert" in tool_names
    assert "get_price_alerts" in tool_names
    for td in TOOL_DEFINITIONS:
        assert td["name"] in tool_names


def test_dispatch_get_price_alerts_empty(toolkit, store):
    from ibkr_core_mcp.mcp_server import _dispatch

    result = _dispatch("get_price_alerts", {"active_only": True}, toolkit, store)
    assert "No" in result


def test_dispatch_add_price_alert(toolkit, store):
    from ibkr_core_mcp.mcp_server import _dispatch

    result = _dispatch(
        "add_price_alert",
        {"conid": 265598, "symbol": "AAPL", "threshold": 190.0, "direction": "above"},
        toolkit,
        store,
    )
    assert "AAPL" in result
    assert store.get_alerts(active_only=True)[0]["threshold"] == 190.0


def test_dispatch_add_price_alert_invalid_direction(toolkit, store):
    from ibkr_core_mcp.mcp_server import _dispatch

    result = _dispatch(
        "add_price_alert",
        {"conid": 265598, "symbol": "AAPL", "threshold": 190.0, "direction": "sideways"},
        toolkit,
        store,
    )
    # Was three or'd substrings, one of which ("unexpected") is _safe_error's catch-all
    # for EVERY exception — so any incidental KeyError or TypeError satisfied it and the
    # test never established that direction validation is what fired.
    assert_tool_failed(result)
    # The property that actually matters: no alert was created.
    assert store.get_alerts(active_only=False) == []


def test_dispatch_add_price_alert_valid_direction_is_accepted(toolkit, store):
    """The control for the test above: if everything errored, that one would still pass."""
    from ibkr_core_mcp.mcp_server import _dispatch

    result = _dispatch(
        "add_price_alert",
        {"conid": 265598, "symbol": "AAPL", "threshold": 190.0, "direction": "above"},
        toolkit,
        store,
    )
    assert_tool_succeeded(result)
    assert len(store.get_alerts(active_only=False)) == 1


def test_dispatch_unknown_tool_returns_error(toolkit, store):
    from ibkr_core_mcp.mcp_server import _dispatch

    result = _dispatch("nonexistent_tool", {}, toolkit, store)
    assert "unknown" in result.lower()


def test_dispatch_get_price_alerts_with_results(toolkit, store):
    from ibkr_core_mcp.mcp_server import _dispatch

    store.add_alert(265598, "AAPL", 190.0, "above")
    result = _dispatch("get_price_alerts", {"active_only": True}, toolkit, store)
    assert "AAPL" in result


def test_dispatch_get_price_alerts_all_includes_triggered(toolkit, store):
    from ibkr_core_mcp.mcp_server import _dispatch

    aid = store.add_alert(265598, "AAPL", 190.0, "above")
    store.mark_alert_triggered(aid)
    active_result = _dispatch("get_price_alerts", {"active_only": True}, toolkit, store)
    all_result = _dispatch("get_price_alerts", {"active_only": False}, toolkit, store)
    # active should report none; all should include the triggered one.
    # The second disjunct of `"No" in active_result or "AAPL" not in active_result` was
    # satisfied by any failure whatsoever, since an error string contains no "AAPL".
    assert_tool_succeeded(active_result)
    assert "No price alerts" in active_result
    assert "AAPL" in all_result


# ── Resource handlers ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resource_ibkr_accounts(toolkit, store):
    import json

    from ibkr_core_mcp.mcp_server import build_server

    toolkit._client.get_accounts.return_value = [{"accountId": "U1234"}]
    server = build_server(toolkit, store)
    content = await _read_resource_text(server, "ibkr://accounts")
    accounts = json.loads(content)
    assert isinstance(accounts, list)
    assert accounts[0]["accountId"] == "U1234"


@pytest.mark.asyncio
async def test_resource_positions_current(toolkit, store):
    import json

    from ibkr_core_mcp.mcp_server import build_server

    toolkit._client.get_accounts.return_value = [{"accountId": "U1234"}]
    toolkit._client.get_positions.return_value = [{"symbol": "AAPL", "position": 100, "mktValue": 18000}]
    server = build_server(toolkit, store)
    content = await _read_resource_text(server, "ibkr://positions/current")
    positions = json.loads(content)
    assert positions[0]["symbol"] == "AAPL"


@pytest.mark.asyncio
async def test_resource_trades_recent(toolkit, store):
    import json

    from ibkr_core_mcp.mcp_server import build_server

    store.upsert_trades(
        [
            {
                "execution_id": "E1",
                "symbol": "AAPL",
                "side": "BUY",
                "size": 10,
                "price": 180,
                "time": "2026-01-01T10:00:00+00:00",
                "commission": 1.0,
                "account": "U1234",
            }
        ]
    )
    server = build_server(toolkit, store)
    content = await _read_resource_text(server, "ibkr://trades/recent")
    trades = json.loads(content)
    assert any(t["symbol"] == "AAPL" for t in trades)


@pytest.mark.asyncio
async def test_resource_unknown_uri_says_so_rather_than_returning_empty(toolkit, store):
    """Was `assert content == "[]"`, pinning the defect as the contract.

    A URI this server does not serve is not an empty collection. Returning "[]" made
    a typo'd resource name indistinguishable from a real, empty one — the same
    conflation that made a down gateway read as an empty portfolio.
    """
    import json

    from ibkr_core_mcp.mcp_server import build_server

    server = build_server(toolkit, store)
    payload = json.loads(await _read_resource_text(server, "ibkr://unknown/path"))
    assert payload["error"] == "unknown resource: ibkr://unknown/path"


# ── _stream_loop_with_retry — retry and cancel ────────────────────────────────


@pytest.mark.asyncio
async def test_stream_loop_retry_on_error():
    """A transient error in _stream_loop should trigger a retry, not propagate."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    from ibkr_core_mcp.mcp_server import _stream_loop_with_retry

    call_count = 0

    async def flaky_loop(toolkit, store):
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise ConnectionError("transient")
        # Second call: raise CancelledError to exit the infinite while-loop
        raise asyncio.CancelledError

    with (
        patch("ibkr_core_mcp.mcp_server._stream_loop", side_effect=flaky_loop),
        patch("asyncio.sleep", new=AsyncMock()),
        pytest.raises(asyncio.CancelledError),
    ):
        await _stream_loop_with_retry(MagicMock(), MagicMock())

    assert call_count == 2


@pytest.mark.asyncio
async def test_stream_loop_cancelled_propagates():
    """CancelledError from _stream_loop must propagate immediately (no retry)."""
    import asyncio
    from unittest.mock import MagicMock, patch

    from ibkr_core_mcp.mcp_server import _stream_loop_with_retry

    async def always_cancel(toolkit, store):
        raise asyncio.CancelledError

    with (
        patch("ibkr_core_mcp.mcp_server._stream_loop", side_effect=always_cancel),
        pytest.raises(asyncio.CancelledError),
    ):
        await _stream_loop_with_retry(MagicMock(), MagicMock())


# ── _stream_loop — dispatch on tagged union (str/spl/smd) ────────────────────


@pytest.mark.asyncio
async def test_stream_loop_dispatches_execution_pnl_and_quote(toolkit, store):
    """Feed one TradeExecution, one PnLUpdate, one LiveQuote through a fake listen();
    assert each lands in the right place and subscribe_executions/subscribe_pnl are
    each called exactly once (not per-message)."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from ibkr_core_mcp.mcp_server import _stream_loop
    from ibkr_core_mcp.streaming import LiveQuote, PnLUpdate, TradeExecution

    execution = TradeExecution(
        execution_id="E1",
        symbol="AAPL",
        side="B",
        size=10.0,
        price=180.0,
        trade_time="20260706-14:30:00",
        account="U1234",
        sec_type="STK",
    )
    pnl = PnLUpdate(account="DU1234567.Core", row_type=1, dpl=12.5, nl=10000.0, upl=3.0, uel=9000.0, mv=5000.0)
    quote = LiveQuote(conid=265598, symbol="AAPL", last=190.0)

    async def fake_listen():
        for item in (execution, pnl, quote):
            yield item

    fake_ws = MagicMock()
    fake_ws.connect = AsyncMock()
    fake_ws.disconnect = AsyncMock()
    fake_ws.subscribe_executions = AsyncMock()
    fake_ws.subscribe_pnl = AsyncMock()
    fake_ws.listen = fake_listen

    with (
        patch("ibkr_core_mcp.auth.BrowserCookieAuth"),
        patch("ibkr_core_mcp.streaming.IBKRWebSocket", return_value=fake_ws),
    ):
        await _stream_loop(toolkit, store)

    trades = store.get_trades(symbol="AAPL")
    assert any(t["execution_id"] == "E1" for t in trades)

    latest_pnl = store.get_latest_pnl()
    assert latest_pnl is not None
    assert latest_pnl["account"] == "DU1234567.Core"
    assert latest_pnl["dpl"] == 12.5

    fake_ws.subscribe_executions.assert_awaited_once()
    fake_ws.subscribe_pnl.assert_awaited_once()


# ── ibkr://pnl/live resource ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resource_pnl_live_populated(toolkit, store):
    from ibkr_core_mcp.mcp_server import build_server

    store.record_pnl_snapshot(
        account="DU1234567.Core", row_type=1, dpl=12.5, nl=10000.0, upl=3.0, uel=9000.0, mv=5000.0
    )
    server = build_server(toolkit, store)
    content = await _read_resource_text(server, "ibkr://pnl/live")
    import json

    data = json.loads(content)
    assert data["account"] == "DU1234567.Core"
    assert data["dpl"] == 12.5


@pytest.mark.asyncio
async def test_resource_pnl_live_empty_when_never_recorded(toolkit, store):
    from ibkr_core_mcp.mcp_server import build_server

    server = build_server(toolkit, store)
    content = await _read_resource_text(server, "ibkr://pnl/live")
    assert content == "{}"


# ============================================================================
# read_resource: "the gateway is down" must not read as "you have nothing"
# ============================================================================


async def test_read_resource_reports_a_failure_instead_of_an_empty_portfolio(toolkit, store):
    """`text = "[]"` was set before the try, and the handler logged only
    type(exc).__name__. A down gateway therefore produced a *successful* resource
    response whose body was an empty array, and the model read "the portfolio is
    empty". The exception message was discarded entirely."""
    import json

    from ibkr_core_mcp.exceptions import IBKRAuthError
    from ibkr_core_mcp.mcp_server import build_server

    toolkit._client.get_accounts.side_effect = IBKRAuthError("session expired")
    server = build_server(toolkit, store)

    content = await _read_resource_text(server, "ibkr://positions/current")

    assert content != "[]", "a failed read must never look like an empty portfolio"
    payload = json.loads(content)
    assert "error" in payload
    assert "session expired" in payload["error"], "the message, not just the exception class name"


async def test_read_resource_reports_a_missing_account_rather_than_empty(toolkit, store):
    """`if account_id:` left text as "[]" with no exception raised at all — a silent
    branch producing the same empty array as a real empty portfolio."""
    import json

    from ibkr_core_mcp.mcp_server import build_server

    toolkit._client.get_accounts.return_value = []
    server = build_server(toolkit, store)

    payload = json.loads(await _read_resource_text(server, "ibkr://positions/current"))

    assert isinstance(payload, dict) and "error" in payload


async def test_read_resource_still_returns_real_data(toolkit, store):
    """The control: a working gateway must keep returning the plain array."""
    import json

    from ibkr_core_mcp.mcp_server import build_server

    toolkit._client.get_accounts.return_value = [{"accountId": "U1"}]
    toolkit._client.get_positions.return_value = [{"conid": 265598, "position": 100}]
    server = build_server(toolkit, store)

    payload = json.loads(await _read_resource_text(server, "ibkr://positions/current"))

    assert payload[0]["conid"] == 265598


# ── _stream_loop — price alerts actually reaching the wire ────────────────────


class _FakeStreamWS:
    """A stand-in for IBKRWebSocket that records subscriptions and serves a script.

    The loop body had no test at all — `test_stream_loop_retry_on_error` patches
    `_stream_loop` out entirely — which is how a deadlock survived inside it.
    """

    def __init__(self, items):
        self._items = list(items)
        self.subscribed: list[int] = []
        self.unsubscribed: list[int] = []
        self.executions_subscribed = False
        self.pnl_subscribed = False
        self.disconnected = False

    async def connect(self):
        return None

    async def subscribe(self, conid, fields=None):
        self.subscribed.append(conid)

    async def unsubscribe(self, conid):
        self.unsubscribed.append(conid)

    async def subscribe_executions(self, realtime_updates_only=False, days=1):
        self.executions_subscribed = True

    async def subscribe_pnl(self):
        self.pnl_subscribed = True

    async def disconnect(self):
        self.disconnected = True

    async def listen(self):
        for item in self._items:
            yield item


def _alert_row(conid=265598, symbol="AAPL"):
    return {
        "id": 1,
        "conid": conid,
        "symbol": symbol,
        "threshold": 100.0,
        "direction": "above",
        "triggered_at": None,
        "created_at": "2026-09-16T00:00:00+00:00",
    }


@pytest.mark.asyncio
async def test_stream_loop_subscribes_to_alert_conids_before_any_quote_arrives():
    """A price alert could never fire under `--stream`, because subscribing to its
    conid happened only inside the `isinstance(item, LiveQuote)` branch.

    A LiveQuote is parsed only from a `smd+` frame, and the gateway sends `smd+` only
    after an `smd+{conid}` subscription. So: no subscription, no quote; no quote, no
    subscription. The only subscriptions made before the loop are executions and P&L,
    neither of which enters that branch. The alerts are local SQLite rows written by
    `add_price_alert`, nothing to do with IBKR's own alert API, so this is a working
    feature that was silently dead.

    Here the stream carries only a P&L tick — exactly what a real session looks like
    before any market-data subscription exists.
    """
    from unittest.mock import MagicMock, patch

    from ibkr_core_mcp.mcp_server import _stream_loop
    from ibkr_core_mcp.streaming import PnLUpdate

    store = MagicMock()
    store.get_alerts.return_value = [_alert_row()]
    fake_ws = _FakeStreamWS([PnLUpdate(account="U1", row_type=1, dpl=1.0)])

    with (
        patch("ibkr_core_mcp.streaming.IBKRWebSocket", return_value=fake_ws),
        patch("ibkr_core_mcp.auth.BrowserCookieAuth", return_value=MagicMock()),
    ):
        await _stream_loop(MagicMock(), store)

    assert 265598 in fake_ws.subscribed, "no market-data subscription was ever sent, so the alert can never trigger"


@pytest.mark.asyncio
async def test_stream_loop_drops_a_subscription_once_its_alert_is_gone():
    """The counter-case, and the reason the reconcile cannot simply be "subscribe to
    everything once at startup": a triggered or deleted alert must release its
    subscription, or a long-lived server accumulates stale ones."""
    from unittest.mock import MagicMock, patch

    from ibkr_core_mcp.mcp_server import _stream_loop
    from ibkr_core_mcp.streaming import PnLUpdate

    store = MagicMock()
    # Present on the first reconcile, gone on the second.
    store.get_alerts.side_effect = [[_alert_row()], [], [], []]
    fake_ws = _FakeStreamWS([PnLUpdate(account="U1", row_type=1, dpl=1.0)])

    with (
        patch("ibkr_core_mcp.streaming.IBKRWebSocket", return_value=fake_ws),
        patch("ibkr_core_mcp.auth.BrowserCookieAuth", return_value=MagicMock()),
    ):
        await _stream_loop(MagicMock(), store)

    assert 265598 in fake_ws.subscribed
    assert 265598 in fake_ws.unsubscribed, "a stale subscription was never released"


@pytest.mark.asyncio
async def test_positions_resource_resolves_an_account_row_that_has_only_id(toolkit, store):
    """`ibkr://positions/current` inlined `get_accounts()` and read only `"accountId"`.

    IBKR varies that key by endpoint, which is why `ClaudeToolkit._first_account_id()`
    exists and why CLAUDE.md says to use it rather than inline the call — this was the
    package's single violation of that rule (audit finding TOOL-06).

    Verified live 2026-09-16: this account's rows carry BOTH `accountId` and `id`, with the
    same value, so nothing was broken here — which is exactly why it survived. A row
    carrying only `id` took the "no account could be resolved" branch and read no positions
    at all, reporting a resolution failure for an account that had resolved fine everywhere
    else in the package.
    """
    import json

    from ibkr_core_mcp.mcp_server import build_server

    toolkit._client.get_accounts.return_value = [{"id": "U9999999"}]  # no "accountId"
    toolkit._client.get_positions.return_value = [{"symbol": "GLD", "position": 10}]

    server = build_server(toolkit, store)
    content = await _read_resource_text(server, "ibkr://positions/current")

    assert "no account could be resolved" not in content, content
    positions = json.loads(content)
    assert positions[0]["symbol"] == "GLD"
    toolkit._client.get_positions.assert_called_once_with("U9999999")


@pytest.mark.asyncio
async def test_positions_resource_serialises_the_typed_return(toolkit, store):
    """`ibkr://positions/current` json.dumps the client's return directly.

    `IBKRClient.get_positions` returns `Position` models as of 2026-09-16. They are
    mappings over IBKR's payload, so every `.get`/`[]`/`in` in the tool layer carries
    over — but `json.dumps` does not know them, and this handler catches every exception
    and answers with an error object. A serialisation failure would therefore not crash:
    the resource would quietly stop carrying positions while still looking like it
    worked, which is the failure this file already guards against twice above.

    The payload is a real portfolio row from tests/fixtures/ibkr_live_shapes.json.
    """
    import json
    from pathlib import Path

    from ibkr_core_mcp.mcp_server import build_server
    from ibkr_core_mcp.models import Position, parse_many

    raw = json.loads((Path(__file__).parent / "fixtures" / "ibkr_live_shapes.json").read_text())["positions"]
    typed = parse_many(Position, raw)
    assert all(isinstance(p, Position) for p in typed), "fixture no longer exercises the typed path"

    toolkit._client.get_accounts.return_value = [{"accountId": "U1234567"}]
    toolkit._client.get_positions.return_value = typed
    server = build_server(toolkit, store)

    content = await _read_resource_text(server, "ibkr://positions/current")

    assert json.loads(content) == raw, "the resource must emit every key IBKR sent"
