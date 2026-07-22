from unittest.mock import MagicMock

import pytest


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
    assert "error" in result.lower() or "direction" in result.lower() or "unexpected" in result.lower()


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
    # active should report none; all should include the triggered one
    assert "No" in active_result or "AAPL" not in active_result
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
async def test_resource_unknown_uri_returns_empty(toolkit, store):
    from ibkr_core_mcp.mcp_server import build_server

    server = build_server(toolkit, store)
    content = await _read_resource_text(server, "ibkr://unknown/path")
    assert content == "[]"


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
    ):
        with pytest.raises(asyncio.CancelledError):
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

    with patch("ibkr_core_mcp.mcp_server._stream_loop", side_effect=always_cancel):
        with pytest.raises(asyncio.CancelledError):
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
