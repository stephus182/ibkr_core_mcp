import pytest

pytestmark = pytest.mark.backtest_pinescript


def _ohlcv_df(n=60):
    import numpy as np
    import pandas as pd

    np.random.seed(3)
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": np.ones(n) * 1e6,
        },
        index=pd.date_range("2026-01-01", periods=n, freq="B"),
    )


def test_execute_run_backtest_tool(toolkit):
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
    toolkit._store.save_backtest.return_value = 1
    text, fig = toolkit.execute(
        "run_backtest",
        {
            "code": "df['signal'] = 1",
            "symbol": "AAPL",
            "timeframe": "1D",
            "period": "1Y",
            "end": "2026-05-22",
            "strategy_name": "test",
        },
    )
    assert len(text) > 0


def test_execute_generate_pinescript_tool(toolkit):
    text, fig = toolkit.execute("generate_pinescript", {"symbol": "AAPL", "indicators": ["rsi", "macd"]})
    assert "//@version=5" in text


def test_generate_pinescript_from_backtest_uses_stored_result(toolkit):
    """source='backtest' must call the tested strategy_from_backtest generator on
    the most recent stored run — not leave the LLM to hand-write strategy() syntax
    (audit register item 13, live hallucination surface observed 2026-07-06)."""
    toolkit._store.get_backtests.return_value = [
        {
            "id": 7,
            "run_at": "2026-07-06T15:00:00+00:00",
            "symbol": "AAPL",
            "strategy_name": "RSI Mean Reversion",
            "total_return": 0.12,
            "sharpe": 1.4,
            "sortino": 1.9,
            "max_drawdown": -0.08,
            "num_trades": 23,
            "win_rate": 0.61,
            "metadata": None,
        }
    ]
    toolkit._cache.check.return_value = False
    text, _ = toolkit.execute(
        "generate_pinescript",
        {
            "symbol": "AAPL",
            "source": "backtest",
        },
    )
    assert "strategy(" in text
    assert "RSI Mean Reversion" in text
    assert "1.40" in text  # Sharpe from the stored run, not a made-up figure
    toolkit._store.get_backtests.assert_called_once_with(symbol="AAPL", strategy=None)


def test_generate_pinescript_from_backtest_filters_by_strategy_name(toolkit):
    toolkit._store.get_backtests.return_value = [
        {
            "id": 9,
            "run_at": "2026-07-06T16:00:00+00:00",
            "symbol": "AAPL",
            "strategy_name": "MACD Cross",
            "total_return": 0.05,
            "sharpe": 0.9,
            "sortino": 1.1,
            "max_drawdown": -0.11,
            "num_trades": 40,
            "win_rate": 0.5,
            "metadata": None,
        }
    ]
    toolkit._cache.check.return_value = False
    text, _ = toolkit.execute(
        "generate_pinescript",
        {
            "symbol": "AAPL",
            "source": "backtest",
            "strategy_name": "MACD Cross",
        },
    )
    assert "MACD Cross" in text
    toolkit._store.get_backtests.assert_called_once_with(symbol="AAPL", strategy="MACD Cross")


def test_generate_pinescript_from_backtest_no_stored_run_errors(toolkit):
    toolkit._store.get_backtests.return_value = []
    text, _ = toolkit.execute(
        "generate_pinescript",
        {
            "symbol": "TSLA",
            "source": "backtest",
        },
    )
    assert "run_backtest" in text
    assert "strategy(" not in text


def test_run_backtest_runtime_error_detail_reaches_llm(toolkit):
    """The live 2026-07-02 failure: strategy referenced df['rsi'] on raw OHLCV and
    the LLM only saw 'strategy raised a runtime error' — no key, no columns.
    The failing key, exception type, and available columns must reach the LLM."""
    toolkit._cache.check.return_value = True
    toolkit._cache.load.return_value = _ohlcv_df()
    text, _ = toolkit.execute(
        "run_backtest",
        {
            "symbol": "AAPL",
            "timeframe": "1D",
            "period": "6M",
            "end": "2026-07-01",
            "code": "df['signal'] = 0\ndf.loc[df['rsi'] < 30, 'signal'] = 1",
        },
    )
    assert "rsi" in text
    assert "KeyError" in text
    assert "close" in text  # available columns listed
    assert "unexpected error" not in text.lower()


def test_run_backtest_syntax_error_detail_reaches_llm(toolkit):
    toolkit._cache.check.return_value = True
    toolkit._cache.load.return_value = _ohlcv_df()
    text, _ = toolkit.execute(
        "run_backtest",
        {
            "symbol": "AAPL",
            "timeframe": "1D",
            "period": "6M",
            "end": "2026-07-01",
            "code": "df['signal] = 0",
        },
    )
    assert "syntax" in text.lower()
    assert "line" in text.lower()  # position detail present


def test_run_backtest_missing_signal_shows_contract(toolkit):
    toolkit._cache.check.return_value = True
    toolkit._cache.load.return_value = _ohlcv_df()
    text, _ = toolkit.execute(
        "run_backtest",
        {
            "symbol": "AAPL",
            "timeframe": "1D",
            "period": "6M",
            "end": "2026-07-01",
            "code": "x = 1",
        },
    )
    assert "df['signal']" in text
    assert "1=long" in text or "1 = long" in text
