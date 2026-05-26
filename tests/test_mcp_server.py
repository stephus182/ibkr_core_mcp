import json
import pytest
from unittest.mock import MagicMock


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


async def test_server_has_22_tools(toolkit, store):
    from ibkr_core_mcp.mcp_server import build_server
    from ibkr_core_mcp.claude_tools import TOOL_DEFINITIONS
    from mcp.types import ListToolsRequest
    server = build_server(toolkit, store)
    req = ListToolsRequest(method="tools/list")
    result = await server.request_handlers[type(req)](req)
    tool_names = [t.name for t in result.root.tools]
    assert len(tool_names) >= 22
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
