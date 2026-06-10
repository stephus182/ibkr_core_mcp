import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def signals():
    idx = pd.date_range("2025-01-01", periods=100, freq="B")
    vals = ([1] * 30 + [0] * 20 + [-1] * 20 + [1] * 30)
    return pd.Series(vals, index=idx)


@pytest.fixture
def backtest_result():
    from ibkr_core_mcp.backtest import BacktestResult
    return BacktestResult(
        symbol="AAPL",
        strategy_name="RSI Mean Reversion",
        total_return=0.15,
        sharpe=1.2,
        sortino=1.8,
        max_drawdown=-0.08,
        num_trades=24,
        win_rate=0.58,
        equity_curve=pd.Series([1.0, 1.05, 1.10, 1.08, 1.15]),
    )


@pytest.fixture
def ohlcv():
    np.random.seed(1)
    n = 100
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    return pd.DataFrame({
        "open": close, "high": close + 0.5, "low": close - 0.5,
        "close": close, "volume": np.ones(n) * 1e6,
    }, index=pd.date_range("2025-01-01", periods=n, freq="B"))


def test_strategy_from_signals_is_string(signals):
    from ibkr_core_mcp.pinescript import strategy_from_signals
    script = strategy_from_signals("Test Strategy", signals, "AAPL", "1D")
    assert isinstance(script, str)
    assert len(script) > 100


def test_strategy_from_signals_has_pine_header(signals):
    from ibkr_core_mcp.pinescript import strategy_from_signals
    script = strategy_from_signals("Test Strategy", signals, "AAPL", "1D")
    assert "//@version=5" in script
    assert "strategy(" in script


def test_strategy_from_signals_has_entry_exit(signals):
    from ibkr_core_mcp.pinescript import strategy_from_signals
    script = strategy_from_signals("Test Strategy", signals, "AAPL", "1D")
    assert "strategy.entry" in script or "strategy.long" in script or "longCondition" in script


def test_indicator_script_returns_string():
    from ibkr_core_mcp.pinescript import indicator_script
    script = indicator_script("My Indicators", ["rsi", "macd"], {})
    assert isinstance(script, str)
    assert "//@version=5" in script
    assert "indicator(" in script


def test_indicator_script_includes_rsi():
    from ibkr_core_mcp.pinescript import indicator_script
    script = indicator_script("RSI Study", ["rsi"], {"rsi_period": 14})
    assert "rsi" in script.lower()
    assert "ta.rsi" in script or "RSI" in script


def test_indicator_script_includes_macd():
    from ibkr_core_mcp.pinescript import indicator_script
    script = indicator_script("MACD Study", ["macd"], {})
    assert "macd" in script.lower()


def test_indicator_script_includes_bb():
    from ibkr_core_mcp.pinescript import indicator_script
    script = indicator_script("BB Study", ["bollinger_bands"], {})
    assert "bollinger" in script.lower() or "bb" in script.lower() or "ta.bb" in script


def test_strategy_from_backtest_returns_string(backtest_result, ohlcv):
    from ibkr_core_mcp.pinescript import strategy_from_backtest
    script = strategy_from_backtest(backtest_result, ohlcv)
    assert isinstance(script, str)
    assert "//@version=5" in script
    assert "strategy(" in script


def test_strategy_from_backtest_includes_symbol(backtest_result, ohlcv):
    from ibkr_core_mcp.pinescript import strategy_from_backtest
    script = strategy_from_backtest(backtest_result, ohlcv)
    assert "AAPL" in script or "RSI Mean Reversion" in script


def test_strategy_from_backtest_has_metrics_comment(backtest_result, ohlcv):
    from ibkr_core_mcp.pinescript import strategy_from_backtest
    script = strategy_from_backtest(backtest_result, ohlcv)
    assert "Sharpe" in script or "sharpe" in script or "Total Return" in script


# ---------------------------------------------------------------------------
# _sanitize — injection prevention
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("malicious_input,expected_absent", [
    ('My Strat")', '"'),                # double-quote closes string literal
    ('Strat\nmalicious_line()', '\n'),  # newline injects new PineScript line
    ('Strat\rinjected', '\r'),          # carriage return
    ('A" + alert("pwned") //', '"'),    # quote + alert injection attempt
])
def test_sanitize_strips_injection_chars(malicious_input, expected_absent):
    from ibkr_core_mcp.pinescript import _sanitize
    result = _sanitize(malicious_input)
    assert expected_absent not in result


def test_sanitize_truncates_to_128_chars():
    from ibkr_core_mcp.pinescript import _sanitize
    result = _sanitize("A" * 300)
    assert len(result) <= 128


def test_sanitize_preserves_normal_name():
    from ibkr_core_mcp.pinescript import _sanitize
    assert _sanitize("RSI Mean Reversion") == "RSI Mean Reversion"


# ---------------------------------------------------------------------------
# _infer_timeframe — non-DatetimeIndex fallback
# ---------------------------------------------------------------------------

def test_infer_timeframe_returns_1D_on_integer_index():
    import pandas as pd

    from ibkr_core_mcp.pinescript import _infer_timeframe
    df = pd.DataFrame({"close": [1, 2, 3]})  # RangeIndex, not DatetimeIndex
    assert _infer_timeframe(df) == "1D"


def test_infer_timeframe_returns_1D_on_empty_dataframe():
    import pandas as pd

    from ibkr_core_mcp.pinescript import _infer_timeframe
    assert _infer_timeframe(pd.DataFrame()) == "1D"
