import pytest

from .conftest import assert_tool_succeeded

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
    text, _fig = toolkit.execute(
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
    assert_tool_succeeded(text)
    assert "Total Return" in text
    assert "Sharpe" in text


def test_execute_generate_pinescript_tool(toolkit):
    text, _fig = toolkit.execute("generate_pinescript", {"symbol": "AAPL", "indicators": ["rsi", "macd"]})
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


def test_run_backtest_annualises_with_the_requested_timeframe(toolkit):
    """One strategy, one set of bars, two tools — they must not disagree.

    `_run_backtest` reads `timeframe` to locate the cached bars and then dropped it, so the
    metrics were always annualised as if daily. `_get_analytics` threads
    `periods_for_timeframe(timeframe)`, so asking the two tools about the same 5-minute
    backtest returned Sharpe figures sqrt(19656/252) = 8.8x apart.

    Asserted as the scaling law between two timeframes rather than a fixed number, so the
    test states the property and not the arithmetic of the metric.
    """
    import math
    import re

    from ibkr_core_mcp.analytics import periods_for_timeframe

    df = _ohlcv_df(120)
    toolkit._cache.check.return_value = True
    toolkit._cache.load.return_value = df
    toolkit._store.save_backtest.return_value = 1

    code = "df['signal'] = (df['close'] > df['close'].shift(1)).astype(int)"

    def _sharpe_for(timeframe):
        text, _ = toolkit.execute(
            "run_backtest",
            {"code": code, "symbol": "TEST", "timeframe": timeframe, "period": "1Y", "end": "2026-01-01"},
        )
        assert_tool_succeeded(text)
        match = re.search(r"Sharpe[^\-\d]*(-?\d+\.\d+)", text)
        assert match, f"no Sharpe in tool output: {text[:300]}"
        return float(match.group(1))

    daily = _sharpe_for("1d")
    intraday = _sharpe_for("5min")

    assert daily != 0, "degenerate fixture — the ratio below would be vacuous"
    intraday_periods = periods_for_timeframe("5min")
    assert intraday_periods is not None, "unrecognised bar size — the comparison would be vacuous"
    expected = math.sqrt(intraday_periods / 252)
    assert intraday / daily == pytest.approx(expected, rel=1e-2), (
        f"5min Sharpe {intraday} vs daily {daily}: ratio {intraday / daily:.3f}, "
        f"expected {expected:.3f}. The handler is not threading the bar size."
    )
