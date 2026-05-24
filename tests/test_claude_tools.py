import pytest
from unittest.mock import MagicMock, patch
from datetime import date


@pytest.fixture
def toolkit(mock_config):
    from ibkr_core_mcp.claude_tools import ClaudeToolkit
    client = MagicMock()
    cache = MagicMock()
    store = MagicMock()
    return ClaudeToolkit(client, cache, store, mock_config)


def test_tools_returns_list_of_dicts(toolkit):
    tools = toolkit.tools
    assert isinstance(tools, list)
    assert len(tools) >= 14
    for t in tools:
        assert "name" in t
        assert "description" in t
        assert "input_schema" in t


def test_all_tools_have_required_fields(toolkit):
    for tool in toolkit.tools:
        assert isinstance(tool["name"], str)
        assert isinstance(tool["description"], str)
        schema = tool["input_schema"]
        assert schema.get("type") == "object"
        assert "properties" in schema


def test_execute_unknown_tool_returns_error(toolkit):
    text, fig = toolkit.execute("nonexistent_tool", {})
    assert "unknown" in text.lower() or "error" in text.lower()
    assert fig is None


def test_execute_check_cache_hit(toolkit):
    toolkit._cache.check.return_value = True
    text, fig = toolkit.execute("check_cache", {
        "symbol": "AAPL", "timeframe": "1D", "period": "1Y", "end": "2026-05-22"
    })
    assert "HIT" in text
    assert fig is None


def test_execute_check_cache_miss(toolkit):
    toolkit._cache.check.return_value = False
    text, fig = toolkit.execute("check_cache", {
        "symbol": "AAPL", "timeframe": "1D", "period": "1Y", "end": "2026-05-22"
    })
    assert "MISS" in text


def test_execute_get_account_summary(toolkit):
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.get_account_summary.return_value = {
        "netliquidation": {"amount": 100000},
        "totalcashvalue": {"amount": 50000},
    }
    text, fig = toolkit.execute("get_account_summary", {})
    assert fig is None
    assert len(text) > 0


def test_execute_get_trades(toolkit):
    toolkit._client.get_trades.return_value = [
        {"symbol": "AAPL", "side": "BUY", "size": 10, "price": 180, "time": "2026-05-22"}
    ]
    toolkit._store.upsert_trades.return_value = None
    text, fig = toolkit.execute("get_trades", {})
    assert "AAPL" in text or len(text) > 0


def test_execute_get_notifications(toolkit):
    toolkit._client.get_notifications.return_value = [
        {"id": "1", "title": "Test alert", "body": "Something happened", "isRead": False}
    ]
    toolkit._client.get_unread_count.return_value = 1
    text, fig = toolkit.execute("get_notifications", {})
    assert len(text) > 0
    assert fig is None
