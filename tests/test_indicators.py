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


def _ohlc(n):
    """Minimal OHLC frame with a real high-low range on every bar, for ATR."""
    close = np.linspace(100.0, 110.0, n)
    return pd.DataFrame(
        {"open": close, "high": close + 1.0, "low": close - 1.0, "close": close, "volume": np.ones(n)},
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
    """ "Similarly, RSI equals 0 when Average Gain equals zero." — same source."""
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
    assert {"open", "high", "low", "close", "volume"}.issubset(set(result.columns))
    assert len(result) == len(ohlcv)


# ── Series shorter than the lookback ───────────────────────────────────────────
#
# `_wilder_smooth`'s two early returns (`indicators.py:51` and `:55`) had no test. They
# were introduced by this audit's own DATA-01 fix — whose entire subject was correct
# behaviour on SHORT series — and the shortest-series branch was the one left unpinned.
# Found by re-measuring `docs/test-coverage.md`, which still listed `indicators.py` under
# "100% Coverage (no gaps)" while it had drifted to 98%.


@pytest.mark.parametrize("bars", [1, 5, 13, 14])
def test_rsi_is_undefined_when_there_are_fewer_bars_than_the_period(bars):
    """Wilder seeds on the SMA of the first `period` changes, so `period` changes need
    `period + 1` bars. Below that the indicator is undefined and must say so with NaN —
    not with 0.0, which reads as maximally oversold and is the exact defect DATA-01 fixed
    at the other end of the series."""
    from ibkr_core_mcp.indicators import rsi

    out = rsi(_closes(np.linspace(100.0, 110.0, bars)), period=14)
    assert len(out) == bars
    assert out.isna().all(), f"{bars} bars produced a value where RSI is undefined"


def test_rsi_becomes_defined_at_exactly_one_bar_past_the_period():
    """The counter-case. A guard that returned all-NaN for every length would pass the
    test above; this pins the first bar where a value is legitimate."""
    from ibkr_core_mcp.indicators import rsi

    out = rsi(_closes(np.linspace(100.0, 110.0, 15)), period=14)
    assert out.iloc[:14].isna().all()
    assert out.notna().iloc[14], "no value at the first bar where Wilder is defined"


def test_rsi_of_an_all_nan_close_column_is_all_nan_and_does_not_raise():
    """`present.size == 0` — the other early return. A recursive average over no
    observations has no seed, and the honest answer is NaN rather than an IndexError."""
    from ibkr_core_mcp.indicators import rsi

    out = rsi(_closes(np.full(20, np.nan)), period=14)
    assert out.isna().all()


def test_atr_is_undefined_when_there_are_fewer_bars_than_the_period():
    """`atr` returns `_wilder_smooth`'s output directly, so it is where the short-series
    branch is observable. `rsi` is not: it divides gains by losses, and `0/0` is NaN, so a
    guard returning zeros instead of NaN looks identical through RSI. The first version of
    this test asserted only through `rsi` and the mutant survived.

    Zero is the dangerous value here rather than merely a wrong one — ATR is a volatility
    denominator in position sizing and in `keltner_channels`, and a zero band width reads
    as a riskless instrument.

    The boundary differs from RSI's by one bar, and it was measured rather than assumed:
    `true_range` is defined on bar 0 (`high - low`, Wilder's convention when there is no
    previous close), so ATR needs `period` bars, while RSI comes from `diff()` and needs
    `period + 1`. The first version of this test asserted RSI's boundary for ATR and
    failed against correct code.
    """
    from ibkr_core_mcp.indicators import atr

    for bars in (2, 5, 13):
        out = atr(_ohlc(bars), period=14)
        assert out.isna().all(), f"{bars} bars produced an ATR where it is undefined"

    defined = atr(_ohlc(14), period=14)
    assert defined.iloc[:13].isna().all()
    assert defined.notna().iloc[13], "no ATR at the first bar where Wilder is defined"
    assert (defined.dropna() > 0).all(), "ATR collapsed to zero on a series with real range"
