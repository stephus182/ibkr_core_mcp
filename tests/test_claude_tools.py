from unittest.mock import MagicMock, patch

import pytest


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
        {"execution_id": "E1", "symbol": "AAPL", "side": "BUY", "size": 10,
         "price": 180, "time": "2026-05-22T10:00:00"}
    ]
    toolkit._store.upsert_trades.return_value = None
    text, fig = toolkit.execute("get_trades", {"source": "live"})
    assert "AAPL" in text
    assert fig is None


# --- _parse_live_trades unit tests ---

from ibkr_core_mcp.claude_tools import _parse_live_trades


def _raw(overrides: dict) -> dict:
    base = {
        "execution_id": "EX1", "symbol": "AAPL", "side": "B",
        "size": 10, "price": 180.0, "time": "2026-05-22T10:00:00",
        "commission": -1.0, "account": "U123456",
    }
    base.update(overrides)
    return base


def test_parse_live_trades_side_normalization():
    parsed, skipped = _parse_live_trades([_raw({"side": "B"}), _raw({"side": "S", "execution_id": "EX2"})])
    assert skipped == 0
    assert parsed[0]["side"] == "BUY"
    assert parsed[1]["side"] == "SELL"


def test_parse_live_trades_already_normalized_side():
    parsed, skipped = _parse_live_trades([_raw({"side": "BUY"}), _raw({"side": "SELL", "execution_id": "EX2"})])
    assert skipped == 0
    assert parsed[0]["side"] == "BUY"
    assert parsed[1]["side"] == "SELL"


def test_parse_live_trades_commission_abs():
    parsed, _ = _parse_live_trades([_raw({"commission": -2.5})])
    assert parsed[0]["commission"] == 2.5


def test_parse_live_trades_skips_missing_execution_id():
    # No fallback to loop index — record must be skipped
    t = _raw({})
    del t["execution_id"]
    parsed, skipped = _parse_live_trades([t])
    assert len(parsed) == 0
    assert skipped == 1


def test_parse_live_trades_skips_missing_symbol():
    parsed, skipped = _parse_live_trades([_raw({"symbol": "", "ticker": ""})])
    assert len(parsed) == 0
    assert skipped == 1


def test_parse_live_trades_skips_invalid_side():
    parsed, skipped = _parse_live_trades([_raw({"side": "X"})])
    assert len(parsed) == 0
    assert skipped == 1


def test_parse_live_trades_skips_missing_time():
    t = _raw({"time": "", "trade_time": ""})
    parsed, skipped = _parse_live_trades([t])
    assert len(parsed) == 0
    assert skipped == 1


def test_parse_live_trades_alternate_field_names():
    # IBKR API uses different field names in different endpoints
    t = {
        "execId": "EX99", "ticker": "CL", "side": "B",
        "filledQuantity": 5, "avgPrice": 78.5,
        "trade_time": "2026-05-22T14:30:00", "commission": -0.85,
        "acctID": "U999999",
    }
    parsed, skipped = _parse_live_trades([t])
    assert skipped == 0
    assert parsed[0]["execution_id"] == "EX99"
    assert parsed[0]["symbol"] == "CL"
    assert parsed[0]["side"] == "BUY"
    assert parsed[0]["size"] == 5
    assert parsed[0]["price"] == 78.5
    assert parsed[0]["commission"] == 0.85
    assert parsed[0]["account"] == "U999999"


def test_parse_live_trades_upsert_error_surfaced(toolkit):
    toolkit._client.get_trades.return_value = [
        {"execution_id": "E1", "symbol": "AAPL", "side": "B", "size": 10,
         "price": 180, "time": "2026-05-22T10:00:00"}
    ]
    toolkit._store.upsert_trades.side_effect = RuntimeError("DB locked")
    text, fig = toolkit.execute("get_trades", {"source": "live"})
    # Raw exception must NOT leak to LLM — only a controlled message appears
    assert "DB locked" not in text
    assert "could not be saved" in text.lower()


def test_execute_get_notifications(toolkit):
    toolkit._client.get_notifications.return_value = [
        {"id": "1", "title": "Test alert", "body": "Something happened", "isRead": False}
    ]
    toolkit._client.get_unread_count.return_value = 1
    text, fig = toolkit.execute("get_notifications", {})
    assert len(text) > 0
    assert fig is None


def test_tools_count_at_least_19(toolkit):
    assert len(toolkit.tools) >= 19


def test_execute_add_indicators(toolkit):
    import numpy as np
    import pandas as pd
    n = 100
    np.random.seed(0)
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    df = pd.DataFrame({
        "open": close, "high": close + 0.5, "low": close - 0.5,
        "close": close, "volume": np.ones(n) * 1e6,
    }, index=pd.date_range("2025-01-01", periods=n, freq="B"))
    toolkit._cache.check.return_value = True
    toolkit._cache.load.return_value = df
    text, fig = toolkit.execute("add_indicators", {
        "symbol": "AAPL", "timeframe": "1D", "period": "1Y", "end": "2026-05-22"
    })
    assert len(text) > 0
    assert fig is None


def test_execute_run_backtest_tool(toolkit):
    import numpy as np
    import pandas as pd
    n = 100
    np.random.seed(0)
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    df = pd.DataFrame({
        "open": close, "high": close + 0.5, "low": close - 0.5,
        "close": close, "volume": np.ones(n) * 1e6,
    }, index=pd.date_range("2025-01-01", periods=n, freq="B"))
    toolkit._cache.check.return_value = True
    toolkit._cache.load.return_value = df
    toolkit._store.save_backtest.return_value = 1
    text, fig = toolkit.execute("run_backtest", {
        "code": "df['signal'] = 1",
        "symbol": "AAPL", "timeframe": "1D", "period": "1Y",
        "end": "2026-05-22", "strategy_name": "test"
    })
    assert len(text) > 0


def test_execute_generate_pinescript_tool(toolkit):
    text, fig = toolkit.execute("generate_pinescript", {
        "symbol": "AAPL", "indicators": ["rsi", "macd"]
    })
    assert "//@version=5" in text


def test_execute_get_analytics_tool(toolkit):
    import numpy as np
    import pandas as pd
    n = 100
    np.random.seed(0)
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    df = pd.DataFrame({
        "open": close, "high": close + 0.5, "low": close - 0.5,
        "close": close, "volume": np.ones(n) * 1e6,
    }, index=pd.date_range("2025-01-01", periods=n, freq="B"))
    toolkit._cache.check.return_value = True
    toolkit._cache.load.return_value = df
    text, fig = toolkit.execute("get_analytics", {
        "symbol": "AAPL", "timeframe": "1D", "period": "1Y", "end": "2026-05-22"
    })
    assert "sharpe" in text.lower() or "Sharpe" in text


def test_execute_get_market_snapshot_warns_on_partial_resolution(toolkit):
    # AAPL resolves; BADTICKER does not — output must name the skipped symbol
    def search_side_effect(sym, sec_type):
        if sym == "AAPL":
            return [{"conid": 265598, "exchange": "NASDAQ"}]
        return []
    toolkit._client.search_contract.side_effect = search_side_effect
    toolkit._client.get_market_snapshot.return_value = [{"conid": 265598, "31": "185.0"}]
    text, fig = toolkit.execute("get_market_snapshot", {"symbols": ["AAPL", "BADTICKER"]})
    assert "BADTICKER" in text
    assert "omitted" in text.lower() or "could not resolve" in text.lower()
    assert fig is None


def test_execute_get_market_snapshot_invalid_conid_skipped(toolkit):
    toolkit._client.search_contract.return_value = [{"conid": "N/A"}]
    toolkit._client.get_market_snapshot.return_value = []
    text, fig = toolkit.execute("get_market_snapshot", {"symbols": ["AAPL"]})
    assert "Could not resolve" in text
    toolkit._client.get_market_snapshot.assert_not_called()


def test_execute_get_live_orders_filters_filled(toolkit):
    # The client-layer filtering is already tested in test_client.py;
    # this confirms the tool correctly labels an empty working set.
    toolkit._client.get_live_orders.return_value = []
    text, fig = toolkit.execute("get_live_orders", {})
    assert "No open orders" in text
    assert fig is None


def test_execute_get_live_orders_shows_working_orders(toolkit):
    toolkit._client.get_live_orders.return_value = [
        {"orderId": 1, "ticker": "AAPL", "side": "BUY",
         "totalSize": 100, "price": 185.0, "status": "Submitted"},
    ]
    text, fig = toolkit.execute("get_live_orders", {})
    assert "AAPL" in text
    assert "Submitted" in text
    assert fig is None


def test_execute_get_alerts_empty(toolkit):
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.get_alerts.return_value = []
    text, fig = toolkit.execute("get_alerts", {})
    assert "No price alerts" in text
    assert fig is None


def test_execute_get_alerts_returns_json(toolkit):
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.get_alerts.return_value = [
        {"orderId": 1, "alertName": "AAPL >= 200", "alertActive": 1}
    ]
    text, fig = toolkit.execute("get_alerts", {})
    assert "AAPL" in text
    assert fig is None


def test_execute_create_price_alert_resolves_symbol(toolkit):
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.search_contract.return_value = [{"conid": 265598, "symbol": "AAPL", "exchange": "NASDAQ"}]
    toolkit._client.create_alert.return_value = {"orderId": 42, "alertName": "AAPL >= 200"}
    text, fig = toolkit.execute("create_price_alert", {
        "symbol": "AAPL", "operator": ">=", "price": 200.0
    })
    toolkit._client.search_contract.assert_called_once_with("AAPL", "STK")
    toolkit._client.create_alert.assert_called_once()
    call_alert = toolkit._client.create_alert.call_args[0][1]
    assert call_alert["conditions"][0]["conid"] == 265598
    assert call_alert["conditions"][0]["operator"] == ">="
    assert call_alert["conditions"][0]["value"] == "200.0"
    assert call_alert["conditions"][0]["exchange"] == "NASDAQ"
    assert call_alert["conditions"][0]["conditionType"] == "Price"
    assert fig is None


def test_execute_create_price_alert_futures_uses_contract_exchange(toolkit):
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.search_contract.return_value = [{"conid": 12345, "symbol": "CL", "exchange": "NYMEX"}]
    toolkit._client.create_alert.return_value = {"orderId": 7}
    toolkit.execute("create_price_alert", {
        "symbol": "CL", "sec_type": "FUT", "operator": ">=", "price": 85.0
    })
    call_alert = toolkit._client.create_alert.call_args[0][1]
    assert call_alert["conditions"][0]["exchange"] == "NYMEX"


def test_execute_create_price_alert_invalid_conid_returns_error(toolkit):
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.search_contract.return_value = [{"conid": "N/A", "symbol": "AAPL"}]
    text, fig = toolkit.execute("create_price_alert", {
        "symbol": "AAPL", "operator": ">=", "price": 200.0
    })
    assert "Invalid conid" in text
    toolkit._client.create_alert.assert_not_called()


def test_execute_create_price_alert_no_contract(toolkit):
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.search_contract.return_value = []
    text, fig = toolkit.execute("create_price_alert", {
        "symbol": "FAKE", "operator": "<=", "price": 50.0
    })
    assert "No contract found" in text
    toolkit._client.create_alert.assert_not_called()


def test_execute_create_price_alert_custom_name(toolkit):
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.search_contract.return_value = [{"conid": 265598}]
    toolkit._client.create_alert.return_value = {"orderId": 5}
    toolkit.execute("create_price_alert", {
        "symbol": "AAPL", "operator": ">=", "price": 200.0, "name": "My alert"
    })
    call_alert = toolkit._client.create_alert.call_args[0][1]
    assert call_alert["alertName"] == "My alert"


def test_execute_delete_alert(toolkit):
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.delete_alert.return_value = {"success": True}
    text, fig = toolkit.execute("delete_alert", {"alert_id": "42"})
    toolkit._client.delete_alert.assert_called_once_with("U123", "42")
    assert fig is None


def test_execute_activate_alert_default_true(toolkit):
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.activate_alert.return_value = {"success": True}
    toolkit.execute("activate_alert", {"alert_id": "42"})
    toolkit._client.activate_alert.assert_called_once_with("U123", "42", True)


def test_execute_activate_alert_deactivate(toolkit):
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.activate_alert.return_value = {"success": True}
    toolkit.execute("activate_alert", {"alert_id": "42", "activate": False})
    toolkit._client.activate_alert.assert_called_once_with("U123", "42", False)


# ── _safe_error — all exception branches ────────────────────────────────────

def test_safe_error_ibkr_auth():
    from ibkr_core_mcp.claude_tools import _safe_error
    from ibkr_core_mcp.exceptions import IBKRAuthError
    msg = _safe_error("some_tool", IBKRAuthError("session expired"))
    assert "authenticated" in msg.lower()


def test_safe_error_rate_limit():
    from ibkr_core_mcp.claude_tools import _safe_error
    from ibkr_core_mcp.exceptions import IBKRRateLimitError
    msg = _safe_error("some_tool", IBKRRateLimitError("429"))
    assert "rate limit" in msg.lower()


def test_safe_error_api_error():
    from ibkr_core_mcp.claude_tools import _safe_error
    from ibkr_core_mcp.exceptions import IBKRAPIError
    msg = _safe_error("some_tool", IBKRAPIError("error", status_code=500))
    assert "500" in msg


def test_safe_error_cache():
    from ibkr_core_mcp.claude_tools import _safe_error
    from ibkr_core_mcp.exceptions import CacheError
    msg = _safe_error("some_tool", CacheError("drive down"))
    assert "drive" in msg.lower() or "cache" in msg.lower()


def test_safe_error_backtest_syntax():
    from ibkr_core_mcp.claude_tools import _safe_error
    from ibkr_core_mcp.exceptions import BacktestSyntaxError
    msg = _safe_error("run_backtest", BacktestSyntaxError("bad indent"))
    assert "syntax" in msg.lower()


def test_safe_error_backtest_runtime():
    from ibkr_core_mcp.claude_tools import _safe_error
    from ibkr_core_mcp.exceptions import BacktestRuntimeError
    msg = _safe_error("run_backtest", BacktestRuntimeError("ZeroDivision"))
    assert "runtime" in msg.lower()


def test_safe_error_backtest_generic():
    from ibkr_core_mcp.claude_tools import _safe_error
    from ibkr_core_mcp.exceptions import BacktestError
    msg = _safe_error("run_backtest", BacktestError("failed"))
    assert "backtest" in msg.lower()


def test_safe_error_flex_query():
    from ibkr_core_mcp.claude_tools import _safe_error
    from ibkr_core_mcp.exceptions import FlexQueryError
    msg = _safe_error("sync_flex_trades", FlexQueryError("timeout"))
    assert "flex" in msg.lower()


def test_safe_error_config():
    from ibkr_core_mcp.claude_tools import _safe_error
    from ibkr_core_mcp.exceptions import ConfigError
    msg = _safe_error("some_tool", ConfigError("missing key"))
    assert "configuration" in msg.lower()


def test_safe_error_key_error():
    from ibkr_core_mcp.claude_tools import _safe_error
    msg = _safe_error("some_tool", KeyError("symbol"))
    assert "missing" in msg.lower() or "field" in msg.lower()


def test_safe_error_unexpected():
    from ibkr_core_mcp.claude_tools import _safe_error
    msg = _safe_error("some_tool", RuntimeError("something odd"))
    assert "unexpected" in msg.lower()


# ── _fetch_market_data — live (cache-miss) path ──────────────────────────────

def test_fetch_market_data_live_path(toolkit):
    import pandas as pd
    import numpy as np

    n = 50
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    df = pd.DataFrame({
        "open": close, "high": close + 0.5, "low": close - 0.5,
        "close": close, "volume": np.ones(n) * 1e6,
    }, index=pd.date_range("2025-01-01", periods=n, freq="B"))

    toolkit._cache.check.return_value = False
    toolkit._client.search_contract.return_value = [{"conid": 265598}]
    # Simulate IBKR raw response that bars_to_dataframe can parse
    data_rows = [
        {"t": int(ts.timestamp() * 1000), "o": r["open"], "h": r["high"],
         "l": r["low"], "c": r["close"], "v": r["volume"]}
        for ts, r in df.iterrows()
    ]
    toolkit._client.get_market_history_paginated.return_value = {"data": data_rows}

    text, fig = toolkit.execute("fetch_market_data", {
        "symbol": "AAPL", "period": "1Y", "bar": "1d"
    })
    assert "AAPL" in text
    assert "IBKR" in text
    toolkit._cache.save.assert_called_once()


def test_fetch_market_data_no_contract(toolkit):
    toolkit._cache.check.return_value = False
    toolkit._client.search_contract.return_value = []
    text, fig = toolkit.execute("fetch_market_data", {"symbol": "FAKE", "period": "1Y", "bar": "1d"})
    assert "No contract" in text


def test_fetch_market_data_empty_data(toolkit):
    """Paginated endpoint returning empty → error message with 'no data'."""
    toolkit._cache.check.return_value = False
    toolkit._client.search_contract.return_value = [{"conid": 265598}]
    toolkit._client.get_market_history_paginated.return_value = {"data": []}
    text, fig = toolkit.execute("fetch_market_data", {"symbol": "AAPL", "period": "1Y", "bar": "1d"})
    assert "no data" in text.lower()


# ── _sync_flex_trades — missing token ────────────────────────────────────────

def test_sync_flex_trades_no_token(toolkit):
    text, fig = toolkit.execute("sync_flex_trades", {})
    assert "IBKR_FLEX_TOKEN" in text


# ── _get_positions — empty and field fallback ─────────────────────────────────

def test_get_positions_empty(toolkit):
    toolkit._client.get_accounts.return_value = [{"accountId": "U1234"}]
    toolkit._client.get_positions.return_value = []
    text, fig = toolkit.execute("get_positions", {})
    assert "No open positions" in text


def test_get_positions_filters_zero_size(toolkit):
    """position=0 means flat — excluded regardless of instrument type."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U1234"}]
    toolkit._client.get_positions.return_value = [
        {"contractDesc": "AAPL", "position": 100, "mktValue": 18000.0, "unrealizedPnl": 500.0},
        {"contractDesc": "CLOSED_STOCK", "position": 0, "mktValue": 0.0, "unrealizedPnl": 0.0},
        {"contractDesc": "CLOSED_FUTURE", "position": 0, "mktValue": 0.0, "unrealizedPnl": 0.0},
        {"contractDesc": "CLOSED_OPTION", "position": 0, "mktValue": 0.0, "unrealizedPnl": 0.0},
    ]
    text, fig = toolkit.execute("get_positions", {})
    assert "AAPL" in text
    assert "CLOSED_STOCK" not in text
    assert "CLOSED_FUTURE" not in text
    assert "CLOSED_OPTION" not in text
    assert "Open positions (1)" in text


def test_get_positions_all_zero_returns_empty(toolkit):
    """All-zero portfolio returns 'No open positions'."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U1234"}]
    toolkit._client.get_positions.return_value = [
        {"contractDesc": "FLAT_A", "position": 0, "mktValue": 0.0, "unrealizedPnl": 0.0},
        {"contractDesc": "FLAT_B", "position": 0, "mktValue": 0.0, "unrealizedPnl": 0.0},
    ]
    text, fig = toolkit.execute("get_positions", {})
    assert "No open positions" in text


def test_get_positions_field_fallback(toolkit):
    """Position summary should use contractDesc → ticker → symbol in that order."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U1234"}]
    toolkit._client.get_positions.return_value = [
        {"contractDesc": "AAPL", "position": 100, "mktValue": 18000.0, "unrealizedPnl": 500.0},
        {"ticker": "TSLA", "position": 10, "mktValue": 2500.0, "unrealizedPnl": -50.0},
        {"symbol": "GOOG", "position": 5, "mktValue": 7500.0, "unrealizedPnl": 100.0},
    ]
    text, fig = toolkit.execute("get_positions", {})
    assert "AAPL" in text
    assert "TSLA" in text
    assert "GOOG" in text


# ── _get_ledger ───────────────────────────────────────────────────────────────

def test_get_ledger_formats_usd(toolkit):
    """Ledger formats key fields from the USD currency block."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U1234"}]
    toolkit._client.get_account_ledger.return_value = {
        "USD": {
            "netliquidationvalue": 67516.82,
            "cashbalance": 22637.43,
            "stockmarketvalue": 44879.61,
            "futuresonlymv": 1150.0,
            "unrealizedpnl": -10359.37,
            "realizedpnl": 1145.50,
            "futuresonlypnl": 1150.0,
            "accruals": -44.22,
            "dividends": 44.0,
        }
    }
    text, fig = toolkit.execute("get_ledger", {})
    assert "67,516.82" in text
    assert "22,637.43" in text
    assert "USD" in text
    assert "Futures Market Value" in text
    assert "1,150.00" in text
    assert fig is None


def test_get_ledger_omits_zero_futures(toolkit):
    """Futures rows are suppressed when futures market value and P&L are zero."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U1234"}]
    toolkit._client.get_account_ledger.return_value = {
        "USD": {
            "netliquidationvalue": 50000.0,
            "cashbalance": 10000.0,
            "stockmarketvalue": 40000.0,
            "futuresonlymv": 0,
            "unrealizedpnl": -500.0,
            "realizedpnl": 0,
            "futuresonlypnl": 0,
        }
    }
    text, fig = toolkit.execute("get_ledger", {})
    assert "Futures Market Value" not in text
    assert "Futures P&L" not in text


def test_get_ledger_empty(toolkit):
    toolkit._client.get_accounts.return_value = [{"accountId": "U1234"}]
    toolkit._client.get_account_ledger.return_value = {}
    text, fig = toolkit.execute("get_ledger", {})
    assert "No ledger data" in text


# ── _get_pnl — empty and non-numeric guards ──────────────────────────────────

def test_get_pnl_empty(toolkit):
    toolkit._client.get_pnl.return_value = {}
    text, fig = toolkit.execute("get_pnl", {})
    assert "No P&L" in text or "P&L" in text


def test_get_pnl_skips_non_numeric(toolkit):
    toolkit._client.get_pnl.return_value = {
        "U1234": {
            "265598": {"ticker": "AAPL", "uPnl": "N/A", "dPnl": "N/A"},
        }
    }
    text, fig = toolkit.execute("get_pnl", {})
    # Should not raise; AAPL line skipped, total should still print
    assert "Total" in text


# ── _preview_order — LMT includes price in order payload ─────────────────────

def test_preview_order_lmt_includes_price(toolkit):
    toolkit._client.get_accounts.return_value = [{"accountId": "U1234"}]
    toolkit._client.search_contract.return_value = [{"conid": 265598}]
    toolkit._client.get_order_preview.return_value = {
        "commission": "1.05",
        "equity": {"amount": 99000, "change": -18200},
        "initMarginChange": "500",
        "maintMarginChange": "300",
    }
    text, fig = toolkit.execute("preview_order", {
        "symbol": "AAPL", "action": "BUY", "quantity": 100,
        "order_type": "LMT", "limit_price": 182.50,
    })
    call_order = toolkit._client.get_order_preview.call_args[0][1]
    assert call_order["price"] == 182.50
    assert "Order Preview" in text


def test_preview_order_mkt_no_price(toolkit):
    toolkit._client.get_accounts.return_value = [{"accountId": "U1234"}]
    toolkit._client.search_contract.return_value = [{"conid": 265598}]
    toolkit._client.get_order_preview.return_value = {"commission": "0.00"}
    toolkit.execute("preview_order", {
        "symbol": "AAPL", "action": "BUY", "quantity": 10, "order_type": "MKT"
    })
    call_order = toolkit._client.get_order_preview.call_args[0][1]
    assert "price" not in call_order


# ---------------------------------------------------------------------------
# _format_coverage — pure formatting helper for trade history summaries
# ---------------------------------------------------------------------------

def test_format_coverage_no_gaps():
    from ibkr_core_mcp.claude_tools import _format_coverage
    cov = {"oldest": "2024-01-01", "newest": "2024-12-31",
           "total_trades": 500, "stale": False, "gaps": []}
    text = "\n".join(_format_coverage(cov))
    assert "no periods" in text
    assert "gap(s)" not in text


def test_format_coverage_with_gaps():
    from ibkr_core_mcp.claude_tools import _format_coverage
    cov = {
        "oldest": "2024-01-01", "newest": "2024-12-31",
        "total_trades": 500, "stale": False,
        "gaps": [{
            "gap_start": "2024-03-01", "gap_end": "2024-06-01",
            "calendar_days": 92,
            "request_from": "2024-03-02", "request_to": "2024-05-31",
        }],
    }
    text = "\n".join(_format_coverage(cov))
    assert "1 period" in text
    assert "inactivity or missing data" in text
    assert "2024-03-01" in text


def test_format_coverage_stale_flag():
    from ibkr_core_mcp.claude_tools import _format_coverage
    cov = {"oldest": "2024-01-01", "newest": "2024-06-01",
           "total_trades": 100, "stale": True, "days_since_newest": 15, "gaps": []}
    text = "\n".join(_format_coverage(cov))
    assert "STALE" in text
    assert "15" in text


# ---------------------------------------------------------------------------
# verify_flex_import
# ---------------------------------------------------------------------------

_FLEX_XML_A = b"""<?xml version="1.0"?>
<FlexQueryResponse>
  <FlexStatements>
    <FlexStatement>
      <Trades>
        <Trade tradeID="EX001" symbol="GLD" buySell="BUY" quantity="10"
               tradePrice="180.0" dateTime="20240101;120000" ibCommission="-1.0"
               accountId="U123" assetCategory="STK"/>
        <Trade tradeID="EX002" symbol="GLD" buySell="SELL" quantity="-10"
               tradePrice="185.0" dateTime="20240201;120000" ibCommission="-1.0"
               accountId="U123" assetCategory="STK"/>
      </Trades>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>"""

_FLEX_XML_B = b"""<?xml version="1.0"?>
<FlexQueryResponse>
  <FlexStatements>
    <FlexStatement>
      <Trades>
        <Trade tradeID="EX003" symbol="QQQ" buySell="BUY" quantity="5"
               tradePrice="400.0" dateTime="20240301;120000" ibCommission="-1.0"
               accountId="U123" assetCategory="STK"/>
      </Trades>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>"""


def test_verify_flex_import_all_present(toolkit):
    """All tradeIDs in auto-synced XML present in SQLite, hash matches manifest → hash verified."""
    import hashlib
    content_a = _FLEX_XML_A
    sha256_a = hashlib.sha256(content_a).hexdigest()
    toolkit._cache.download_account_files.return_value = [("flex_U123_2024-01-01_REF.xml", content_a)]
    toolkit._store.get_all_execution_ids.return_value = {"EX001", "EX002"}
    toolkit._store.get_flex_import_entry.return_value = {
        "sha256": sha256_a, "imported_at": "2024-01-01T00:00:00", "verified_at": None
    }

    result, _ = toolkit.execute("verify_flex_import", {})
    assert "hash verified" in result
    assert "Missing from SQLite             : 0" in result


def test_verify_flex_import_missing_records(toolkit):
    """tradeID in XML but absent from SQLite → flagged as missing."""
    toolkit._cache.download_account_files.return_value = [("flex_U123_2024-01-01_REF.xml", _FLEX_XML_A)]
    toolkit._store.get_all_execution_ids.return_value = {"EX001"}  # EX002 missing
    toolkit._store.get_flex_import_entry.return_value = None  # first encounter

    result, _ = toolkit.execute("verify_flex_import", {})
    assert "1 missing" in result
    assert "EX002" in result
    assert "re-import" in result


def test_verify_flex_import_manual_pre_validated(toolkit):
    """Manual archive (ClaudIA_Full_Activity_*.xml) reported as pre-validated, not cross-checked."""
    toolkit._cache.download_account_files.return_value = [
        ("ClaudIA_Full_Activity_123120.xml", _FLEX_XML_A)
    ]
    toolkit._store.get_all_execution_ids.return_value = {"EX001", "EX002"}
    toolkit._store.get_flex_import_entry.return_value = None  # first encounter

    result, _ = toolkit.execute("verify_flex_import", {})
    assert "pre-validated" in result
    # Manual files are not cross-checked against SQLite
    assert "missing" not in result.lower() or "0" in result


def test_verify_flex_import_no_drive(toolkit):
    """No Drive configured → clear error message."""
    toolkit._cache = None
    result, _ = toolkit.execute("verify_flex_import", {})
    assert "GOOGLE_DRIVE_FOLDER_ID" in result


def test_verify_flex_import_no_xml_files(toolkit):
    """No XML files in account_data/ → actionable message."""
    toolkit._cache.download_account_files.return_value = []
    result, _ = toolkit.execute("verify_flex_import", {})
    assert "No .xml files found" in result


def test_extract_execution_ids():
    """extract_execution_ids returns (unique_ids, raw_count) from <Trade> elements."""
    from ibkr_core_mcp.flex_query import FlexQueryClient
    unique_ids, raw_count = FlexQueryClient.extract_execution_ids(_FLEX_XML_A.decode())
    assert unique_ids == {"EX001", "EX002"}
    assert raw_count == 2


def test_extract_execution_ids_skips_empty():
    """extract_execution_ids counts blank-tradeID elements in raw_count but not unique_ids."""
    from ibkr_core_mcp.flex_query import FlexQueryClient
    xml = b"""<FlexQueryResponse><FlexStatements><FlexStatement><Trades>
        <Trade tradeID="" symbol="X" buySell="BUY"/>
        <Trade tradeID="GOOD1" symbol="Y" buySell="SELL"/>
    </Trades></FlexStatement></FlexStatements></FlexQueryResponse>"""
    unique_ids, raw_count = FlexQueryClient.extract_execution_ids(xml.decode())
    assert unique_ids == {"GOOD1"}
    assert raw_count == 2  # both <Trade> elements counted, only one has a valid tradeID


def test_extract_execution_ids_within_file_duplicate():
    """raw_count > len(unique_ids) when the same tradeID appears twice in one XML."""
    from ibkr_core_mcp.flex_query import FlexQueryClient
    xml = b"""<FlexQueryResponse><FlexStatements><FlexStatement><Trades>
        <Trade tradeID="DUP1" symbol="X" buySell="BUY"/>
        <Trade tradeID="DUP1" symbol="X" buySell="BUY"/>
    </Trades></FlexStatement></FlexStatements></FlexQueryResponse>"""
    unique_ids, raw_count = FlexQueryClient.extract_execution_ids(xml.decode())
    assert unique_ids == {"DUP1"}
    assert raw_count == 2  # duplicate detected: raw(2) != unique(1)


# ============================================================================
# Firecrawl handler tests
# ============================================================================


def _make_toolkit():
    """Return a ClaudeToolkit with all dependencies mocked."""
    from ibkr_core_mcp.claude_tools import ClaudeToolkit
    from ibkr_core_mcp.config import Config
    from pathlib import Path
    cfg = Config(
        gateway_url="http://localhost",
        anthropic_api_key="sk-test",
        gdrive_folder_id="root-id",
        sqlite_path=Path("/tmp/store.db"),
        gdrive_token_file=Path("/tmp/token.json"),
        gdrive_credentials_file=Path("/tmp/creds.json"),
        firecrawl_api_key="fc-test",
    )
    toolkit = ClaudeToolkit(
        client=MagicMock(),
        cache=MagicMock(),
        store=MagicMock(),
        config=cfg,
    )
    return toolkit


def test_firecrawl_search_returns_no_key_message_when_key_missing():
    from ibkr_core_mcp.claude_tools import ClaudeToolkit
    from ibkr_core_mcp.config import Config
    from pathlib import Path
    cfg = Config(
        gateway_url="http://localhost",
        anthropic_api_key="sk-test",
        gdrive_folder_id="root-id",
        sqlite_path=Path("/tmp/store.db"),
        gdrive_token_file=Path("/tmp/token.json"),
        gdrive_credentials_file=Path("/tmp/creds.json"),
        firecrawl_api_key="",
    )
    toolkit = ClaudeToolkit(client=MagicMock(), cache=MagicMock(), store=MagicMock(), config=cfg)
    result, fig = toolkit.execute("firecrawl_search", {"query": "test"})
    assert "FIRECRAWL_API_KEY" in result
    assert fig is None


@patch("ibkr_core_mcp.web_scraper.FirecrawlClient")
def test_firecrawl_search_returns_formatted_results(mock_fc_cls):
    toolkit = _make_toolkit()
    mock_fc = MagicMock()
    mock_fc.search.return_value = [
        {"url": "https://example.com", "title": "Example", "markdown": "# Hello"}
    ]
    mock_fc_cls.return_value = mock_fc

    result, fig = toolkit.execute("firecrawl_search", {"query": "IBKR API", "limit": 3})
    assert "example.com" in result  # lgtm[py/incomplete-url-substring-sanitization] — text output assertion, not a URL guard
    assert fig is None
    mock_fc.search.assert_called_once_with("IBKR API", limit=3)


@patch("ibkr_core_mcp.web_scraper.FirecrawlClient")
@patch("ibkr_core_mcp.web_scraper.WebDocsStore")
def test_firecrawl_search_saves_to_drive_when_requested(mock_wds_cls, mock_fc_cls):
    toolkit = _make_toolkit()
    mock_fc = MagicMock()
    mock_fc.search.return_value = [{"url": "u", "title": "t", "markdown": "m"}]
    mock_fc_cls.return_value = mock_fc
    mock_wds = MagicMock()
    mock_wds.save_search.return_value = "file-id-123"
    mock_wds_cls.return_value = mock_wds

    result, _ = toolkit.execute("firecrawl_search", {"query": "test", "save_to_drive": True})
    mock_wds.save_search.assert_called_once()
    assert "file-id-123" in result or "Drive" in result


def test_firecrawl_crawl_blocks_private_url():
    toolkit = _make_toolkit()
    result, fig = toolkit.execute("firecrawl_crawl", {"url": "http://localhost:5055/api"})
    assert "Blocked" in result
    assert fig is None


def test_firecrawl_crawl_returns_no_key_message_when_key_missing():
    from ibkr_core_mcp.claude_tools import ClaudeToolkit
    from ibkr_core_mcp.config import Config
    from pathlib import Path
    cfg = Config(
        gateway_url="http://localhost",
        anthropic_api_key="sk-test",
        gdrive_folder_id="root-id",
        sqlite_path=Path("/tmp/store.db"),
        gdrive_token_file=Path("/tmp/token.json"),
        gdrive_credentials_file=Path("/tmp/creds.json"),
        firecrawl_api_key="",
    )
    toolkit = ClaudeToolkit(client=MagicMock(), cache=MagicMock(), store=MagicMock(), config=cfg)
    result, fig = toolkit.execute("firecrawl_crawl", {"url": "https://example.com"})
    assert "FIRECRAWL_API_KEY" in result
    assert fig is None


@patch("ibkr_core_mcp.web_scraper.FirecrawlClient")
@patch("ibkr_core_mcp.web_scraper.WebDocsStore")
def test_firecrawl_crawl_saves_pages_to_drive(mock_wds_cls, mock_fc_cls):
    toolkit = _make_toolkit()
    mock_fc = MagicMock()
    mock_fc.crawl.return_value = [
        {"url": "https://example.com/page", "markdown": "# Page"}
    ]
    mock_fc_cls.return_value = mock_fc
    mock_wds = MagicMock()
    mock_wds.save_crawl.return_value = {
        "url": "https://example.com",
        "crawled_at": "2026-01-01T00:00:00+00:00",
        "pages": [{"url": "https://example.com/page", "file_id": "fid"}],
    }
    mock_wds_cls.return_value = mock_wds

    result, fig = toolkit.execute("firecrawl_crawl", {"url": "https://example.com"})
    assert "example.com" in result  # lgtm[py/incomplete-url-substring-sanitization] — text output assertion, not a URL guard
    assert "1" in result  # 1 page saved
    assert fig is None
    mock_wds.save_crawl.assert_called_once()


# ============================================================================
# _diagnose_orders
# ============================================================================


def test_diagnose_orders_happy_path(toolkit):
    """Returns formatted order lines when orders list is non-empty."""
    toolkit._client._get.side_effect = [
        None,  # first call: instantiate (return value not used)
        {"orders": [
            {"orderId": 99, "ticker": "AAPL", "side": "BUY",
             "totalSize": 10, "price": 182.5, "status": "Submitted",
             "clientId": "42", "orderRef": "ref1"}
        ]},
    ]
    text, fig = toolkit.execute("diagnose_orders", {})
    assert fig is None
    assert "orderId=99" in text
    assert "AAPL" in text
    assert "/iserver/account/orders" in text


def test_diagnose_orders_empty_list(toolkit):
    """Returns 'genuinely empty' message when orders list is []."""
    toolkit._client._get.side_effect = [None, {"orders": []}]
    text, fig = toolkit.execute("diagnose_orders", {})
    assert fig is None
    assert "genuinely empty" in text.lower()


def test_diagnose_orders_unexpected_shape(toolkit):
    """Returns shape-error message when IBKR returns a non-list response."""
    toolkit._client._get.side_effect = [None, "bad_string"]
    text, fig = toolkit.execute("diagnose_orders", {})
    assert fig is None
    assert "Unexpected response shape" in text


def test_diagnose_orders_shows_filtered_status(toolkit):
    """Filled orders are labelled [FILTERED by get_live_orders]."""
    toolkit._client._get.side_effect = [
        None,
        {"orders": [
            {"orderId": 1, "ticker": "TSLA", "side": "SELL",
             "totalSize": 5, "price": 200.0, "status": "Filled",
             "clientId": "1"}
        ]},
    ]
    text, fig = toolkit.execute("diagnose_orders", {})
    assert "FILTERED" in text


# ============================================================================
# _get_pa_performance
# ============================================================================


def test_get_pa_performance_happy_path(toolkit):
    """Returns JSON performance blob for the requested period."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.get_pa_performance.return_value = {
        "nav": [{"date": "2026-06-01", "navReturns": 0.05}]
    }
    text, fig = toolkit.execute("get_pa_performance", {"period": "1M"})
    assert fig is None
    assert len(text) > 0
    assert "nav" in text


def test_get_pa_performance_error(toolkit):
    """Propagates exception through _safe_error."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.get_pa_performance.side_effect = RuntimeError("PA down")
    text, fig = toolkit.execute("get_pa_performance", {"period": "1M"})
    assert fig is None
    assert "unexpected" in text.lower()


# ============================================================================
# _get_pa_transactions
# ============================================================================


def test_get_pa_transactions_happy_path(toolkit):
    """Returns formatted transaction list for a valid period."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.get_pa_transactions.return_value = [
        {"date": "2026-06-01", "desc": "BUY AAPL", "symbol": "AAPL", "amount": -18250.0},
        {"date": "2026-06-02", "desc": "SELL AAPL", "symbol": "AAPL", "amount": 18500.0},
    ]
    text, fig = toolkit.execute("get_pa_transactions", {"period": "1M"})
    assert fig is None
    assert "AAPL" in text
    assert "2 records" in text


def test_get_pa_transactions_empty(toolkit):
    """Returns 'No transactions' when IBKR returns empty list."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.get_pa_transactions.return_value = []
    text, fig = toolkit.execute("get_pa_transactions", {"period": "1D"})
    assert "No transactions" in text
    assert fig is None


def test_get_pa_transactions_http_400_fallback(toolkit):
    """On HTTP 400, handler fetches valid periods and returns them in the error."""
    from ibkr_core_mcp.exceptions import IBKRAPIError
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.get_pa_transactions.side_effect = IBKRAPIError("bad period", status_code=400)
    toolkit._client.get_pa_periods.return_value = ["1D", "7D", "1M"]
    text, fig = toolkit.execute("get_pa_transactions", {"period": "BAD"})
    assert fig is None
    assert "HTTP 400" in text
    assert "1D" in text or "7D" in text


def test_get_pa_transactions_non_400_error_propagates(toolkit):
    """Non-400 IBKRAPIError re-raises through _safe_error."""
    from ibkr_core_mcp.exceptions import IBKRAPIError
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.get_pa_transactions.side_effect = IBKRAPIError("server error", status_code=500)
    text, fig = toolkit.execute("get_pa_transactions", {"period": "1M"})
    assert fig is None
    assert "500" in text


# ============================================================================
# _get_contract_info
# ============================================================================


def test_get_contract_info_happy_path(toolkit):
    """Returns JSON contract details when conid resolves."""
    toolkit._client.search_contract.return_value = [{"conid": 265598}]
    toolkit._client.get_contract_info_and_rules.return_value = {
        "symbol": "AAPL", "secType": "STK", "currency": "USD"
    }
    text, fig = toolkit.execute("get_contract_info", {"symbol": "AAPL"})
    assert fig is None
    assert "AAPL" in text
    assert "STK" in text


def test_get_contract_info_no_contract(toolkit):
    """Returns error when search_contract finds nothing."""
    toolkit._client.search_contract.return_value = []
    text, fig = toolkit.execute("get_contract_info", {"symbol": "FAKESYM"})
    assert fig is None
    assert "No contract" in text


def test_get_contract_info_error(toolkit):
    """Propagates client exception through _safe_error."""
    toolkit._client.search_contract.return_value = [{"conid": 265598}]
    toolkit._client.get_contract_info_and_rules.side_effect = RuntimeError("timeout")
    text, fig = toolkit.execute("get_contract_info", {"symbol": "AAPL"})
    assert fig is None
    assert "unexpected" in text.lower()


# ============================================================================
# _get_option_chain
# ============================================================================


def test_get_option_chain_happy_path(toolkit):
    """Returns JSON option chain data."""
    toolkit._client.get_option_chain.return_value = {
        "expirations": ["2026-07-18", "2026-08-15"],
        "strikes": [180, 185, 190],
    }
    text, fig = toolkit.execute("get_option_chain", {"symbol": "AAPL"})
    assert fig is None
    assert "expirations" in text
    assert "180" in text
    toolkit._client.get_option_chain.assert_called_once_with("AAPL", exchange="SMART")


def test_get_option_chain_custom_exchange(toolkit):
    """Passes custom exchange to the client."""
    toolkit._client.get_option_chain.return_value = {}
    toolkit.execute("get_option_chain", {"symbol": "SPX", "exchange": "CBOE"})
    toolkit._client.get_option_chain.assert_called_once_with("SPX", exchange="CBOE")


def test_get_option_chain_error(toolkit):
    """Propagates exception through _safe_error."""
    toolkit._client.get_option_chain.side_effect = RuntimeError("chain unavailable")
    text, fig = toolkit.execute("get_option_chain", {"symbol": "AAPL"})
    assert fig is None
    assert "unexpected" in text.lower()


# ============================================================================
# _run_scanner
# ============================================================================


def test_run_scanner_happy_path(toolkit):
    """Returns formatted scanner results."""
    toolkit._client.run_iserver_scanner.return_value = [
        {"symbol": "AAPL", "contractDescription": {"exchange": "NASDAQ"}},
        {"symbol": "MSFT", "contractDescription": {"exchange": "NASDAQ"}},
    ]
    text, fig = toolkit.execute("run_scanner", {
        "scan_code": "TOP_VOLUME_RATE", "instrument": "STK"
    })
    assert fig is None
    assert "AAPL" in text
    assert "MSFT" in text
    assert "2 results" in text


def test_run_scanner_no_results(toolkit):
    """Returns 'no results' message when scanner is empty."""
    toolkit._client.run_iserver_scanner.return_value = []
    text, fig = toolkit.execute("run_scanner", {"scan_code": "TOP_VOLUME_RATE"})
    assert fig is None
    assert "no results" in text.lower()


def test_run_scanner_error(toolkit):
    """Propagates exception through _safe_error."""
    toolkit._client.run_iserver_scanner.side_effect = RuntimeError("scanner down")
    text, fig = toolkit.execute("run_scanner", {"scan_code": "TOP_VOLUME_RATE"})
    assert fig is None
    assert "unexpected" in text.lower()


# ============================================================================
# _get_watchlists
# ============================================================================


def test_get_watchlists_happy_path(toolkit):
    """Returns watchlist summary and raw JSON."""
    toolkit._client.get_watchlists.return_value = [
        {
            "id": "wl1",
            "name": "My Watchlist",
            "rows": [{"ST": "AAPL"}, {"ST": "TSLA"}],
        }
    ]
    text, fig = toolkit.execute("get_watchlists", {})
    assert fig is None
    assert "My Watchlist" in text
    assert "AAPL" in text
    assert "TSLA" in text


def test_get_watchlists_empty(toolkit):
    """Returns 'No watchlists' when IBKR returns empty list."""
    toolkit._client.get_watchlists.return_value = []
    text, fig = toolkit.execute("get_watchlists", {})
    assert fig is None
    assert "No watchlists" in text


def test_get_watchlists_error(toolkit):
    """Propagates exception through _safe_error."""
    toolkit._client.get_watchlists.side_effect = RuntimeError("watchlist timeout")
    text, fig = toolkit.execute("get_watchlists", {})
    assert fig is None
    assert "unexpected" in text.lower()


# ============================================================================
# _get_trading_schedule
# ============================================================================


def test_get_trading_schedule_happy_path(toolkit):
    """Returns JSON trading schedule."""
    toolkit._client.get_trading_schedule.return_value = {
        "tradingScheduleDate": [
            {"prop": [{"name": "TRADING_HOURS", "value": "0930-1600"}]}
        ]
    }
    text, fig = toolkit.execute("get_trading_schedule", {"symbol": "AAPL"})
    assert fig is None
    assert "TRADING_HOURS" in text
    toolkit._client.get_trading_schedule.assert_called_once_with("STK", "AAPL", "SMART")


def test_get_trading_schedule_custom_params(toolkit):
    """Passes custom asset_class and exchange to client."""
    toolkit._client.get_trading_schedule.return_value = {}
    toolkit.execute("get_trading_schedule", {
        "symbol": "CL", "asset_class": "FUT", "exchange": "NYMEX"
    })
    toolkit._client.get_trading_schedule.assert_called_once_with("FUT", "CL", "NYMEX")


def test_get_trading_schedule_error(toolkit):
    """Propagates exception through _safe_error."""
    toolkit._client.get_trading_schedule.side_effect = RuntimeError("schedule unavailable")
    text, fig = toolkit.execute("get_trading_schedule", {"symbol": "AAPL"})
    assert fig is None
    assert "unexpected" in text.lower()


# ============================================================================
# _get_allocation
# ============================================================================


def test_get_allocation_happy_path(toolkit):
    """Returns JSON allocation data."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.get_account_allocation.return_value = {
        "assetClass": {"long": {"STK": 0.85, "CASH": 0.15}}
    }
    text, fig = toolkit.execute("get_allocation", {})
    assert fig is None
    assert "assetClass" in text
    assert "STK" in text


def test_get_allocation_error(toolkit):
    """Propagates exception through _safe_error."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.get_account_allocation.side_effect = RuntimeError("allocation unavailable")
    text, fig = toolkit.execute("get_allocation", {})
    assert fig is None
    assert "unexpected" in text.lower()


# ============================================================================
# _get_order_status
# ============================================================================


def test_get_order_status_happy_path(toolkit):
    """Returns JSON order status for the given order ID."""
    toolkit._client.get_order_status.return_value = {
        "orderId": 42, "status": "Submitted", "filledQuantity": 0
    }
    text, fig = toolkit.execute("get_order_status", {"order_id": "42"})
    assert fig is None
    assert "Submitted" in text
    assert "42" in text
    toolkit._client.get_order_status.assert_called_once_with("42")


def test_get_order_status_error(toolkit):
    """Propagates exception through _safe_error."""
    toolkit._client.get_order_status.side_effect = RuntimeError("order not found")
    text, fig = toolkit.execute("get_order_status", {"order_id": "99"})
    assert fig is None
    assert "unexpected" in text.lower()


# ============================================================================
# _delete_cache
# ============================================================================


def test_delete_cache_happy_path(toolkit):
    """Deletes cache entry and returns confirmation."""
    toolkit._cache.check.return_value = True
    text, fig = toolkit.execute("delete_cache", {
        "symbol": "AAPL", "timeframe": "1D", "period": "1Y", "end": "2026-05-22"
    })
    assert fig is None
    assert "Deleted" in text
    assert "AAPL" in text
    toolkit._cache.delete.assert_called_once_with("AAPL", "1D", "1Y", "2026-05-22")


def test_delete_cache_miss(toolkit):
    """Returns 'No cached entry' when the entry does not exist."""
    toolkit._cache.check.return_value = False
    text, fig = toolkit.execute("delete_cache", {
        "symbol": "FAKE", "timeframe": "1D", "period": "1Y", "end": "2026-05-22"
    })
    assert fig is None
    assert "No cached entry" in text
    toolkit._cache.delete.assert_not_called()


# ============================================================================
# _modify_price_alert
# ============================================================================


def test_modify_price_alert_happy_path(toolkit):
    """Modifies price and operator on an existing alert and returns result."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.get_alert.return_value = {
        "alertName": "AAPL >= 200",
        "tif": "GTC",
        "conditions": [{"value": "200.0", "operator": ">="}],
    }
    toolkit._client.create_alert.return_value = {"orderId": 7, "alertName": "AAPL >= 210"}
    text, fig = toolkit.execute("modify_price_alert", {
        "alert_id": "7", "price": 210.0, "operator": ">="
    })
    assert fig is None
    assert len(text) > 0
    # Confirm the patched value was sent
    sent = toolkit._client.create_alert.call_args[0][1]
    assert sent["conditions"][0]["value"] == "210.0"


def test_modify_price_alert_not_found(toolkit):
    """Returns 'not found' when get_alert returns empty."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.get_alert.return_value = {}
    text, fig = toolkit.execute("modify_price_alert", {
        "alert_id": "999", "price": 200.0
    })
    assert fig is None
    assert "not found" in text.lower()
    toolkit._client.create_alert.assert_not_called()


def test_modify_price_alert_name_update(toolkit):
    """Updates alertName field when 'name' is provided."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.get_alert.return_value = {
        "alertName": "old name", "tif": "GTC", "conditions": []
    }
    toolkit._client.create_alert.return_value = {"orderId": 3}
    toolkit.execute("modify_price_alert", {"alert_id": "3", "name": "new name"})
    sent = toolkit._client.create_alert.call_args[0][1]
    assert sent["alertName"] == "new name"


def test_modify_price_alert_error(toolkit):
    """Propagates exception through _safe_error."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.get_alert.side_effect = RuntimeError("alert service down")
    text, fig = toolkit.execute("modify_price_alert", {"alert_id": "1", "price": 200.0})
    assert fig is None
    assert "unexpected" in text.lower()


# ============================================================================
# _sync_flex_archive
# ============================================================================


def test_sync_flex_archive_happy_path(toolkit):
    """Returns import summary when files are found and trades imported."""
    from unittest.mock import patch, MagicMock

    store_cov = {
        "oldest": "2024-01-01", "newest": "2026-05-22",
        "total_trades": 150, "stale": False, "gaps": []
    }
    toolkit._store.get_trade_date_coverage.return_value = store_cov

    mock_flex_instance = MagicMock()
    mock_flex_instance.sync_archive_from_drive.return_value = {
        "files": 2,
        "trades": 150,
        "processed": [
            {"file": "flex_U123_2024.xml", "trades": 80, "range": "2024-01-01 → 2024-12-31"},
            {"file": "flex_U123_2025.xml", "trades": 70, "range": "2025-01-01 → 2025-12-31"},
        ],
    }

    with patch("ibkr_core_mcp.flex_query.FlexQueryClient", return_value=mock_flex_instance):
        text, fig = toolkit.execute("sync_flex_archive", {})

    assert fig is None
    assert "150 trades" in text
    assert "flex_U123_2024.xml" in text


def test_sync_flex_archive_no_files(toolkit):
    """Returns 'No XML files' message when archive is empty."""
    from unittest.mock import patch, MagicMock

    mock_flex_instance = MagicMock()
    mock_flex_instance.sync_archive_from_drive.return_value = {"files": 0, "trades": 0, "processed": []}

    with patch("ibkr_core_mcp.flex_query.FlexQueryClient", return_value=mock_flex_instance):
        text, fig = toolkit.execute("sync_flex_archive", {})

    assert fig is None
    assert "No XML files" in text


def test_sync_flex_archive_file_not_found(toolkit):
    """Returns FileNotFoundError message when Drive folder is missing."""
    from unittest.mock import patch, MagicMock

    mock_flex_instance = MagicMock()
    mock_flex_instance.sync_archive_from_drive.side_effect = FileNotFoundError("account_data/ not found")

    with patch("ibkr_core_mcp.flex_query.FlexQueryClient", return_value=mock_flex_instance):
        text, fig = toolkit.execute("sync_flex_archive", {})

    assert fig is None
    assert "account_data/" in text or "not found" in text.lower()


# ============================================================================
# _import_flex_file
# ============================================================================


def test_import_flex_file_happy_path(toolkit, tmp_path):
    """Imports trades from a file under the allowed root (~/.ibkr_core)."""
    from unittest.mock import patch, MagicMock

    allowed_root = tmp_path / ".ibkr_core"
    allowed_root.mkdir()
    xml_file = allowed_root / "flex_test.xml"
    xml_file.write_text("<FlexQueryResponse/>")

    store_cov = {
        "oldest": "2024-01-01", "newest": "2024-06-30",
        "total_trades": 5, "stale": False, "gaps": []
    }
    toolkit._store.get_trade_date_coverage.return_value = store_cov

    mock_flex_instance = MagicMock()
    mock_flex_instance.import_from_file.return_value = [
        {"time": "2024-03-01T10:00:00", "symbol": "AAPL"},
        {"time": "2024-06-30T15:00:00", "symbol": "MSFT"},
    ]

    with patch("pathlib.Path.home", return_value=tmp_path), \
         patch("ibkr_core_mcp.flex_query.FlexQueryClient", return_value=mock_flex_instance):
        text, fig = toolkit.execute("import_flex_file", {"path": str(xml_file)})

    assert fig is None
    assert "2 trades" in text
    assert "flex_test.xml" in text


def test_import_flex_file_blocked_path(toolkit, tmp_path):
    """Path outside ~/.ibkr_core is rejected — prevents LLM from reading arbitrary files."""
    with patch("pathlib.Path.home", return_value=tmp_path):
        text, fig = toolkit.execute("import_flex_file", {"path": "/etc/passwd"})
    assert fig is None
    assert "Blocked" in text


def test_import_flex_file_not_found(toolkit, tmp_path):
    """Returns 'File not found' for a valid-root path that does not exist."""
    with patch("pathlib.Path.home", return_value=tmp_path):
        nonexistent = tmp_path / ".ibkr_core" / "missing.xml"
        text, fig = toolkit.execute("import_flex_file", {"path": str(nonexistent)})
    assert fig is None
    assert "File not found" in text


def test_import_flex_file_no_trades(toolkit, tmp_path):
    """Returns 'No trades found' when the XML has no trade records."""
    from unittest.mock import patch, MagicMock

    allowed_root = tmp_path / ".ibkr_core"
    allowed_root.mkdir()
    xml_file = allowed_root / "empty.xml"
    xml_file.write_text("<FlexQueryResponse/>")

    mock_flex_instance = MagicMock()
    mock_flex_instance.import_from_file.return_value = []

    with patch("pathlib.Path.home", return_value=tmp_path), \
         patch("ibkr_core_mcp.flex_query.FlexQueryClient", return_value=mock_flex_instance):
        text, fig = toolkit.execute("import_flex_file", {"path": str(xml_file)})

    assert fig is None
    assert "No trades" in text


# ============================================================================
# _check_flex_coverage
# ============================================================================


def test_check_flex_coverage_happy_path(toolkit):
    """Returns coverage report when trade history exists."""
    toolkit._store.get_trade_date_coverage.return_value = {
        "oldest": "2024-01-01",
        "newest": "2026-05-22",
        "total_trades": 300,
        "stale": False,
        "gaps": [],
    }
    text, fig = toolkit.execute("check_flex_coverage", {})
    assert fig is None
    assert len(text) > 0
    # _format_coverage output should mention the date range
    assert "2024-01-01" in text


def test_check_flex_coverage_empty_store(toolkit):
    """Returns 'No trade history' when store is empty."""
    toolkit._store.get_trade_date_coverage.return_value = {
        "oldest": None, "newest": None, "total_trades": 0, "stale": False, "gaps": []
    }
    text, fig = toolkit.execute("check_flex_coverage", {})
    assert fig is None
    assert "No trade history" in text


def test_check_flex_coverage_error(toolkit):
    """Propagates exception through _safe_error."""
    toolkit._store.get_trade_date_coverage.side_effect = RuntimeError("db error")
    text, fig = toolkit.execute("check_flex_coverage", {})
    assert fig is None
    assert "unexpected" in text.lower()


# ============================================================================
# _get_pa_periods — empty fallback path
# ============================================================================


def test_get_pa_periods_empty_falls_back_to_raw(toolkit):
    """When get_pa_periods returns [], raw _post response is returned."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.get_pa_periods.return_value = []
    toolkit._client._post.return_value = {"periods": ["1D", "7D", "1M"]}
    text, fig = toolkit.execute("get_pa_periods", {})
    assert fig is None
    # Raw response must appear in output
    assert "1D" in text or "periods" in text


def test_get_pa_periods_returns_valid_periods(toolkit):
    """When get_pa_periods returns periods, they are listed."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.get_pa_periods.return_value = ["1D", "7D", "MTD", "1M", "YTD", "1Y"]
    text, fig = toolkit.execute("get_pa_periods", {})
    assert fig is None
    assert "1D" in text
    assert "1Y" in text
