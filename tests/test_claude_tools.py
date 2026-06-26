from unittest.mock import MagicMock

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
    toolkit._client.get_hmds_history.return_value = {"data": data_rows}

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
    """Both HMDS and iserver fallback returning empty → error message with 'no data'."""
    toolkit._cache.check.return_value = False
    toolkit._client.search_contract.return_value = [{"conid": 265598}]
    toolkit._client.get_hmds_history.return_value = {"data": []}
    toolkit._client.get_market_history.return_value = {"data": []}  # fallback also empty
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
