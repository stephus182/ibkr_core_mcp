import pytest
import numpy as np
import pandas as pd


@pytest.fixture
def ohlcv():
    """250 bars of synthetic OHLCV data with known properties."""
    np.random.seed(42)
    n = 250
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    high = close + np.random.uniform(0.1, 1.0, n)
    low = close - np.random.uniform(0.1, 1.0, n)
    open_ = close + np.random.randn(n) * 0.2
    volume = np.random.randint(500_000, 2_000_000, n).astype(float)
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx)


def test_sma_length(ohlcv):
    from ibkr_core_mcp.indicators import sma
    result = sma(ohlcv, period=20)
    assert isinstance(result, pd.Series)
    assert len(result) == len(ohlcv)
    assert result.iloc[:19].isna().all()  # first 19 are NaN
    assert not result.iloc[19:].isna().any()


def test_ema_length(ohlcv):
    from ibkr_core_mcp.indicators import ema
    result = ema(ohlcv, period=20)
    assert isinstance(result, pd.Series)
    assert len(result) == len(ohlcv)
    assert result.notna().any()


def test_rsi_bounds(ohlcv):
    from ibkr_core_mcp.indicators import rsi
    result = rsi(ohlcv, period=14)
    valid = result.dropna()
    assert (valid >= 0).all() and (valid <= 100).all()


def test_macd_columns(ohlcv):
    from ibkr_core_mcp.indicators import macd
    result = macd(ohlcv)
    assert isinstance(result, pd.DataFrame)
    assert set(result.columns) == {"macd", "signal", "histogram"}
    assert len(result) == len(ohlcv)


def test_macd_histogram_is_diff(ohlcv):
    from ibkr_core_mcp.indicators import macd
    result = macd(ohlcv)
    diff = (result["macd"] - result["signal"]).round(10)
    assert (diff.dropna() == result["histogram"].dropna().round(10)).all()


def test_bollinger_bands_columns(ohlcv):
    from ibkr_core_mcp.indicators import bollinger_bands
    result = bollinger_bands(ohlcv, period=20)
    assert set(result.columns) == {"bb_upper", "bb_mid", "bb_lower"}
    valid = result.dropna()
    assert (valid["bb_upper"] >= valid["bb_mid"]).all()
    assert (valid["bb_mid"] >= valid["bb_lower"]).all()


def test_atr_positive(ohlcv):
    from ibkr_core_mcp.indicators import atr
    result = atr(ohlcv, period=14)
    assert result.dropna().gt(0).all()


def test_vwap_positive(ohlcv):
    from ibkr_core_mcp.indicators import vwap
    result = vwap(ohlcv)
    assert result.dropna().gt(0).all()


def test_stochastic_bounds(ohlcv):
    from ibkr_core_mcp.indicators import stochastic
    result = stochastic(ohlcv)
    assert set(result.columns) == {"stoch_k", "stoch_d"}
    valid_k = result["stoch_k"].dropna()
    assert (valid_k >= 0).all() and (valid_k <= 100).all()


def test_williams_r_bounds(ohlcv):
    from ibkr_core_mcp.indicators import williams_r
    result = williams_r(ohlcv, period=14)
    valid = result.dropna()
    assert (valid >= -100).all() and (valid <= 0).all()


def test_keltner_channels_columns(ohlcv):
    from ibkr_core_mcp.indicators import keltner_channels
    result = keltner_channels(ohlcv)
    assert set(result.columns) == {"kc_upper", "kc_mid", "kc_lower"}
    valid = result.dropna()
    assert (valid["kc_upper"] >= valid["kc_mid"]).all()


def test_obv_cumulative(ohlcv):
    from ibkr_core_mcp.indicators import obv
    result = obv(ohlcv)
    assert isinstance(result, pd.Series)
    assert len(result) == len(ohlcv)


def test_volume_sma_length(ohlcv):
    from ibkr_core_mcp.indicators import volume_sma
    result = volume_sma(ohlcv, period=20)
    assert result.iloc[:19].isna().all()


def test_volume_ratio_around_one(ohlcv):
    from ibkr_core_mcp.indicators import volume_ratio
    result = volume_ratio(ohlcv, period=20)
    # Average of ratios should be close to 1
    assert abs(result.dropna().mean() - 1.0) < 0.2


def test_add_all_columns(ohlcv):
    from ibkr_core_mcp import indicators
    result = indicators.add_all(ohlcv)
    expected_cols = {
        "sma_20", "ema_20", "rsi", "macd", "macd_signal", "macd_hist",
        "vwap", "bb_upper", "bb_mid", "bb_lower", "atr",
        "stoch_k", "stoch_d", "williams_r",
        "kc_upper", "kc_mid", "kc_lower",
        "obv", "volume_sma", "volume_ratio",
    }
    assert expected_cols.issubset(set(result.columns))


def test_add_all_preserves_ohlcv(ohlcv):
    from ibkr_core_mcp import indicators
    result = indicators.add_all(ohlcv)
    assert set(["open", "high", "low", "close", "volume"]).issubset(set(result.columns))
    assert len(result) == len(ohlcv)
