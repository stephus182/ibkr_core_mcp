import pytest

pytestmark = pytest.mark.pa_analytics


def test_execute_get_analytics_tool(toolkit):
    import numpy as np
    import pandas as pd

    n = 100
    np.random.seed(0)
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    df = pd.DataFrame(
        {
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": np.ones(n) * 1e6,
        },
        index=pd.date_range("2025-01-01", periods=n, freq="B"),
    )
    toolkit._cache.check.return_value = True
    toolkit._cache.load.return_value = df
    text, fig = toolkit.execute(
        "get_analytics", {"symbol": "AAPL", "timeframe": "1D", "period": "1Y", "end": "2026-05-22"}
    )
    assert "sharpe" in text.lower() or "Sharpe" in text


def test_get_pa_performance_happy_path(toolkit):
    """Returns JSON performance blob for the requested period."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.get_pa_performance.return_value = {"nav": [{"date": "2026-06-01", "navReturns": 0.05}]}
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
    """Resolves symbol to conid, passes it (not a period) to client.get_pa_transactions."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.search_contract.return_value = [{"conid": 265598, "symbol": "AAPL"}]
    toolkit._client.get_pa_transactions.return_value = [
        {"date": "2026-06-01", "desc": "BUY AAPL", "symbol": "AAPL", "amount": -18250.0},
        {"date": "2026-06-02", "desc": "SELL AAPL", "symbol": "AAPL", "amount": 18500.0},
    ]
    text, fig = toolkit.execute("get_pa_transactions", {"symbol": "AAPL"})
    assert fig is None
    assert "AAPL" in text
    assert "2 records" in text
    toolkit._client.get_pa_transactions.assert_called_once_with(["U123"], [265598], "USD", None)


def test_get_pa_transactions_custom_currency_and_days(toolkit):
    """currency and days pass through to client.get_pa_transactions unchanged."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.search_contract.return_value = [{"conid": 265598, "symbol": "AAPL"}]
    toolkit._client.get_pa_transactions.return_value = []
    toolkit.execute("get_pa_transactions", {"symbol": "AAPL", "currency": "CAD", "days": 30})
    toolkit._client.get_pa_transactions.assert_called_once_with(["U123"], [265598], "CAD", 30)


def test_get_pa_transactions_empty(toolkit):
    """Returns 'No transactions' when IBKR returns empty list."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.search_contract.return_value = [{"conid": 265598, "symbol": "AAPL"}]
    toolkit._client.get_pa_transactions.return_value = []
    text, fig = toolkit.execute("get_pa_transactions", {"symbol": "AAPL"})
    assert "No transactions" in text
    assert fig is None


def test_get_pa_transactions_conid_resolution_failure(toolkit):
    """When the symbol can't be resolved to a conid, the error is returned and IBKR is never called."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.search_contract.return_value = []
    text, fig = toolkit.execute("get_pa_transactions", {"symbol": "BOGUS"})
    assert fig is None
    assert "BOGUS" in text
    toolkit._client.get_pa_transactions.assert_not_called()


def test_get_pa_transactions_error_propagates(toolkit):
    """IBKRAPIError from the transactions call re-raises through _safe_error."""
    from ibkr_core_mcp.exceptions import IBKRAPIError

    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.search_contract.return_value = [{"conid": 265598, "symbol": "AAPL"}]
    toolkit._client.get_pa_transactions.side_effect = IBKRAPIError("server error", status_code=500)
    text, fig = toolkit.execute("get_pa_transactions", {"symbol": "AAPL"})
    assert fig is None
    assert "500" in text


# ============================================================================
# _get_contract_info
# ============================================================================


def test_get_pa_periods_empty_falls_back_to_raw(toolkit):
    """When get_pa_periods returns [], the raw response is fetched via the public
    get_pa_periods_raw() — not client._post (audit register item 11)."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.get_pa_periods.return_value = []
    toolkit._client.get_pa_periods_raw.return_value = {"periods": ["1D", "7D", "1M"]}
    text, fig = toolkit.execute("get_pa_periods", {})
    assert fig is None
    assert "1D" in text
    toolkit._client.get_pa_periods_raw.assert_called_once_with(["U123"])
    toolkit._client._post.assert_not_called()


def test_get_pa_periods_returns_valid_periods(toolkit):
    """When get_pa_periods returns periods, they are listed."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.get_pa_periods.return_value = ["1D", "7D", "MTD", "1M", "YTD", "1Y"]
    text, fig = toolkit.execute("get_pa_periods", {})
    assert fig is None
    assert "1D" in text
    assert "1Y" in text


def test_execute_get_analytics_annualizes_by_timeframe(toolkit):
    """Intraday timeframe must use intraday periods/yr, not daily 252 (audit defect)."""
    import numpy as np
    import pandas as pd

    from ibkr_core_mcp import analytics

    n = 100
    np.random.seed(1)
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    df = pd.DataFrame(
        {
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": np.ones(n) * 1e6,
        },
        index=pd.date_range("2026-06-01 09:30", periods=n, freq="h"),
    )
    toolkit._cache.check.return_value = True
    toolkit._cache.load.return_value = df

    text, _ = toolkit.execute(
        "get_analytics", {"symbol": "AAPL", "timeframe": "1h", "period": "1M", "end": "2026-07-01"}
    )

    returns = df["close"].pct_change().dropna()
    expected = analytics.sharpe(returns, periods=1638)
    wrong_daily = analytics.sharpe(returns, periods=252)
    assert f"{expected:.2f}" in text
    assert f"{wrong_daily:.2f}" not in text


def test_execute_get_analytics_unknown_timeframe_falls_back_with_caveat(toolkit):
    """Unrecognized timeframe → daily annualisation plus an explicit caveat in output."""
    import numpy as np
    import pandas as pd

    n = 50
    np.random.seed(2)
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    df = pd.DataFrame(
        {
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": np.ones(n) * 1e6,
        },
        index=pd.date_range("2026-01-01", periods=n, freq="B"),
    )
    toolkit._cache.check.return_value = True
    toolkit._cache.load.return_value = df

    text, _ = toolkit.execute(
        "get_analytics", {"symbol": "AAPL", "timeframe": "weird", "period": "1Y", "end": "2026-07-01"}
    )
    assert "not recognized" in text.lower() or "unrecognized" in text.lower()
    assert "252" in text
