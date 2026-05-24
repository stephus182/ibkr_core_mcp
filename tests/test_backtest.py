import pytest
import numpy as np
import pandas as pd


@pytest.fixture
def ohlcv():
    np.random.seed(0)
    n = 200
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    high = close + np.random.uniform(0.1, 1.0, n)
    low = close - np.random.uniform(0.1, 1.0, n)
    open_ = close + np.random.randn(n) * 0.2
    volume = np.random.randint(500_000, 2_000_000, n).astype(float)
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx)


def test_simple_long_strategy(ohlcv):
    from ibkr_core_mcp.backtest import run_backtest, BacktestResult
    code = "df['signal'] = 1"  # always long
    result = run_backtest(code, ohlcv, strategy_name="always_long", symbol="TEST")
    assert isinstance(result, BacktestResult)
    assert result.strategy_name == "always_long"
    assert result.symbol == "TEST"
    assert isinstance(result.total_return, float)
    assert isinstance(result.sharpe, float)
    assert isinstance(result.max_drawdown, float)
    assert isinstance(result.num_trades, int)
    assert len(result.equity_curve) > 0


def test_flat_signal_zero_trades(ohlcv):
    from ibkr_core_mcp.backtest import run_backtest
    code = "df['signal'] = 0"  # always flat
    result = run_backtest(code, ohlcv)
    assert result.total_return == 0.0
    assert result.num_trades == 0


def test_rsi_strategy(ohlcv):
    from ibkr_core_mcp.backtest import run_backtest
    code = """
delta = df['close'].diff()
gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
rs = gain / loss.replace(0, float('nan'))
rsi = 100 - (100 / (1 + rs))
df['signal'] = 0
df.loc[rsi < 30, 'signal'] = 1
df.loc[rsi > 70, 'signal'] = -1
"""
    result = run_backtest(code, ohlcv, strategy_name="rsi_mean_reversion")
    assert isinstance(result.total_return, float)


def test_syntax_error_raises(ohlcv):
    from ibkr_core_mcp.backtest import run_backtest
    from ibkr_core_mcp.exceptions import BacktestSyntaxError
    with pytest.raises(BacktestSyntaxError):
        run_backtest("df['signal'] = (", ohlcv)


def test_runtime_error_raises(ohlcv):
    from ibkr_core_mcp.backtest import run_backtest
    from ibkr_core_mcp.exceptions import BacktestRuntimeError
    with pytest.raises(BacktestRuntimeError):
        run_backtest("df['signal'] = 1 / 0", ohlcv)


def test_no_network_access(ohlcv):
    from ibkr_core_mcp.backtest import run_backtest
    from ibkr_core_mcp.exceptions import BacktestRuntimeError
    with pytest.raises((BacktestRuntimeError, Exception)):
        run_backtest("import urllib.request; urllib.request.urlopen('http://example.com')", ohlcv)


def test_no_file_access(ohlcv):
    from ibkr_core_mcp.backtest import run_backtest
    from ibkr_core_mcp.exceptions import BacktestRuntimeError
    with pytest.raises((BacktestRuntimeError, Exception)):
        run_backtest("open('/etc/passwd', 'r')", ohlcv)


def test_result_to_dict(ohlcv):
    from ibkr_core_mcp.backtest import run_backtest
    result = run_backtest("df['signal'] = 1", ohlcv, symbol="AAPL")
    d = result.to_dict()
    assert "equity_curve" not in d
    assert "total_return" in d
    assert "sharpe" in d
