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


def test_mcp_server_importable():
    from ibkr_core_mcp.mcp_server import build_server
    assert callable(build_server)


async def test_server_has_40_tools(toolkit, store):
    from mcp.types import ListToolsRequest

    from ibkr_core_mcp.claude_tools import TOOL_DEFINITIONS
    from ibkr_core_mcp.mcp_server import build_server
    server = build_server(toolkit, store)
    req = ListToolsRequest(method="tools/list")
    result = await server.request_handlers[type(req)](req)
    tool_names = [t.name for t in result.root.tools]
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
        toolkit, store,
    )
    assert "AAPL" in result
    assert store.get_alerts(active_only=True)[0]["threshold"] == 190.0


def test_dispatch_add_price_alert_invalid_direction(toolkit, store):
    from ibkr_core_mcp.mcp_server import _dispatch
    result = _dispatch(
        "add_price_alert",
        {"conid": 265598, "symbol": "AAPL", "threshold": 190.0, "direction": "sideways"},
        toolkit, store,
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
    from mcp.types import ReadResourceRequest
    from pydantic import AnyUrl
    from ibkr_core_mcp.mcp_server import build_server

    toolkit._client.get_accounts.return_value = [{"accountId": "U1234"}]
    server = build_server(toolkit, store)
    req = ReadResourceRequest(method="resources/read", params={"uri": AnyUrl("ibkr://accounts")})
    result = await server.request_handlers[type(req)](req)
    content = result.root.contents[0].text
    accounts = json.loads(content)
    assert isinstance(accounts, list)
    assert accounts[0]["accountId"] == "U1234"


@pytest.mark.asyncio
async def test_resource_positions_current(toolkit, store):
    import json
    from mcp.types import ReadResourceRequest
    from pydantic import AnyUrl
    from ibkr_core_mcp.mcp_server import build_server

    toolkit._client.get_accounts.return_value = [{"accountId": "U1234"}]
    toolkit._client.get_positions.return_value = [
        {"symbol": "AAPL", "position": 100, "mktValue": 18000}
    ]
    server = build_server(toolkit, store)
    req = ReadResourceRequest(method="resources/read", params={"uri": AnyUrl("ibkr://positions/current")})
    result = await server.request_handlers[type(req)](req)
    content = result.root.contents[0].text
    positions = json.loads(content)
    assert positions[0]["symbol"] == "AAPL"


@pytest.mark.asyncio
async def test_resource_trades_recent(toolkit, store):
    import json
    from mcp.types import ReadResourceRequest
    from pydantic import AnyUrl
    from ibkr_core_mcp.mcp_server import build_server

    store.upsert_trades([{
        "execution_id": "E1", "symbol": "AAPL", "side": "BUY",
        "size": 10, "price": 180, "time": "2026-01-01T10:00:00+00:00",
        "commission": 1.0, "account": "U1234",
    }])
    server = build_server(toolkit, store)
    req = ReadResourceRequest(method="resources/read", params={"uri": AnyUrl("ibkr://trades/recent")})
    result = await server.request_handlers[type(req)](req)
    content = result.root.contents[0].text
    trades = json.loads(content)
    assert any(t["symbol"] == "AAPL" for t in trades)


@pytest.mark.asyncio
async def test_resource_unknown_uri_returns_empty(toolkit, store):
    from mcp.types import ReadResourceRequest
    from pydantic import AnyUrl
    from ibkr_core_mcp.mcp_server import build_server

    server = build_server(toolkit, store)
    req = ReadResourceRequest(method="resources/read", params={"uri": AnyUrl("ibkr://unknown/path")})
    result = await server.request_handlers[type(req)](req)
    content = result.root.contents[0].text
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

    with patch("ibkr_core_mcp.mcp_server._stream_loop", side_effect=flaky_loop), \
         patch("asyncio.sleep", new=AsyncMock()):
        with pytest.raises(asyncio.CancelledError):
            await _stream_loop_with_retry(MagicMock(), MagicMock())

    assert call_count == 2


@pytest.mark.asyncio
async def test_stream_loop_cancelled_propagates():
    """CancelledError from _stream_loop must propagate immediately (no retry)."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch
    from ibkr_core_mcp.mcp_server import _stream_loop_with_retry

    async def always_cancel(toolkit, store):
        raise asyncio.CancelledError

    with patch("ibkr_core_mcp.mcp_server._stream_loop", side_effect=always_cancel):
        with pytest.raises(asyncio.CancelledError):
            await _stream_loop_with_retry(MagicMock(), MagicMock())
