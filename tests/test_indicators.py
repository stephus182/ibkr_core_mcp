import numpy as np
import pandas as pd
import pytest


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


def _closes(values):
    """Minimal OHLCV frame from a close series — rsi only reads df['close']."""
    n = len(values)
    return pd.DataFrame(
        {"open": values, "high": values, "low": values, "close": values, "volume": np.ones(n)},
        index=pd.date_range("2025-01-01", periods=n, freq="B"),
    )


def test_rsi_bounds(ohlcv):
    """Was `assert (valid >= 0).all() and (valid <= 100).all()` after a dropna().

    pandas' `.all()` on an EMPTY Series is True, so an rsi() returning all-NaN — the
    single most likely breakage — satisfied it. It did exactly that for any
    uninterrupted uptrend, and this test passed for all four inputs below including
    the two that were broken. The emptiness guard is the whole point; without it,
    adding the parametrisation alone would just be a second vacuous test.
    """
    from ibkr_core_mcp.indicators import rsi

    result = rsi(ohlcv, period=14)
    valid = result.dropna()
    assert not valid.empty, "all-NaN passes the bounds check vacuously"
    assert (valid >= 0).all() and (valid <= 100).all()


def test_rsi_is_100_when_there_are_no_losses():
    """Wilder's convention, verified against a real source rather than assumed:

    "If the Average Loss equals zero, a 'divide by zero' situation occurs for RS, and
    RSI is set to 100 by definition."
    https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/relative-strength-index-rsi

    `gain / loss.replace(0, nan)` made every value NaN instead, so add_indicators
    rendered "RSI(14): nan" for any uninterrupted uptrend.
    """
    from ibkr_core_mcp.indicators import rsi

    result = rsi(_closes(np.arange(1, 80, dtype=float)), period=14)

    assert not result.dropna().empty
    assert result.iloc[-1] == 100.0


def test_rsi_is_0_when_there_are_no_gains():
    """"Similarly, RSI equals 0 when Average Gain equals zero." — same source."""
    from ibkr_core_mcp.indicators import rsi

    result = rsi(_closes(np.arange(80, 1, -1, dtype=float)), period=14)

    assert result.iloc[-1] == 0.0


def test_rsi_is_undefined_for_a_perfectly_flat_series():
    """Both averages zero: RS is 0/0 and no source defines it. NaN is the honest
    answer — asserted explicitly so "it happens to be NaN" cannot drift unnoticed."""
    from ibkr_core_mcp.indicators import rsi

    result = rsi(_closes(np.full(80, 100.0)), period=14)

    assert result.iloc[-1] != result.iloc[-1], "expected NaN for an undefined RSI"


def test_macd_columns(ohlcv):
    from ibkr_core_mcp.indicators import macd

    result = macd(ohlcv)
    assert isinstance(result, pd.DataFrame)
    assert set(result.columns) == {"macd", "macd_signal", "histogram"}
    assert len(result) == len(ohlcv)


def test_macd_histogram_is_diff(ohlcv):
    from ibkr_core_mcp.indicators import macd

    result = macd(ohlcv)
    diff = (result["macd"] - result["macd_signal"]).round(10)
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
        "sma_20",
        "ema_20",
        "rsi",
        "macd",
        "macd_signal",
        "macd_hist",
        "vwap",
        "bb_upper",
        "bb_mid",
        "bb_lower",
        "atr",
        "stoch_k",
        "stoch_d",
        "williams_r",
        "kc_upper",
        "kc_mid",
        "kc_lower",
        "obv",
        "volume_sma",
        "volume_ratio",
    }
    assert expected_cols.issubset(set(result.columns))


def test_add_all_preserves_ohlcv(ohlcv):
    from ibkr_core_mcp import indicators

    result = indicators.add_all(ohlcv)
    assert set(["open", "high", "low", "close", "volume"]).issubset(set(result.columns))
    assert len(result) == len(ohlcv)
