"""Indicator values pinned to the source authorities' own published worked examples.

Every number in this file was read out of a spreadsheet published by StockCharts
ChartSchool alongside the prose definition of the indicator — not computed by us,
not copied from another library, and not asserted from memory. The spreadsheets
were downloaded 2026-09-16; each `_SOURCE` constant records the page they came from.

Why this file exists. Before it, `tests/test_indicators.py` checked shapes and
bounds only: that ATR is positive, that a Bollinger upper band is above its middle,
that MACD's histogram equals its own definition. Not one of those can fail for a
wrong formula — `bb_upper >= bb_mid` holds for any non-negative deviation, so it
holds whichever `ddof` you pass. Three real divergences (RSI off by up to 19.8
points, ATR by 22%, Bollinger band width by 2.6%) sat behind a fully green suite.
A test that pins a computed value to an outside reference is the only kind that
could have caught them.

Tolerances are loose enough for the spreadsheets' own rounding (they publish 4–6
decimals) and far tighter than any of the divergences above, so a regression to
the previous behaviour fails these tests by three to five orders of magnitude.
"""

import numpy as np
import pandas as pd
import pytest

_RSI_SOURCE = (
    "https://chartschool.stockcharts.com/table-of-contents/technical-indicators"
    "-and-overlays/technical-indicators/relative-strength-index-rsi"
)
"""QQQQ daily closes and the 14-day RSI column from ChartSchool's cs-rsi.xls."""

RSI_CLOSE = [
    44.3389,
    44.0902,
    44.1497,
    43.6124,
    44.3278,
    44.8264,
    45.0955,
    45.4245,
    45.8433,
    46.0826,
    45.8931,
    46.0328,
    45.614,
    46.282,
    46.282,
    46.0028,
    46.0328,
    46.4116,
    46.2222,
    45.6439,
    46.2122,
    46.2521,
    45.7137,
    46.4515,
    45.7835,
    45.3548,
    44.0288,
    44.1783,
    44.2181,
    44.5672,
    43.4205,
    42.6628,
    43.1314,
]
RSI_EXPECTED = [
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    70.5328,
    66.3186,
    66.5498,
    69.4063,
    66.3552,
    57.9749,
    62.9296,
    63.2571,
    56.0593,
    62.3771,
    54.7076,
    50.4228,
    39.9898,
    41.4605,
    41.8689,
    45.4632,
    37.304,
    33.0795,
    37.773,
]

_ATR_SOURCE = (
    "https://chartschool.stockcharts.com/table-of-contents/technical-indicators"
    "-and-overlays/technical-indicators/average-true-range-atr"
)
"""QQQQ daily bars with the True Range and 14-day ATR columns from cs-atr.xls."""

ATR_HIGH = [
    48.7,
    48.72,
    48.9,
    48.87,
    48.82,
    49.05,
    49.2,
    49.35,
    49.92,
    50.19,
    50.12,
    49.66,
    49.88,
    50.19,
    50.36,
    50.57,
    50.65,
    50.43,
    49.63,
    50.33,
    50.29,
    50.17,
    49.32,
    48.5,
    48.3201,
    46.8,
    47.8,
    48.39,
    48.66,
    48.79,
]
ATR_LOW = [
    47.79,
    48.14,
    48.39,
    48.37,
    48.24,
    48.635,
    48.94,
    48.86,
    49.5,
    49.87,
    49.2,
    48.9,
    49.43,
    49.725,
    49.26,
    50.09,
    50.3,
    49.21,
    48.98,
    49.61,
    49.2,
    49.43,
    48.08,
    47.64,
    41.55,
    44.2833,
    47.31,
    47.2,
    47.9,
    47.7301,
]
ATR_CLOSE = [
    48.16,
    48.61,
    48.75,
    48.63,
    48.74,
    49.03,
    49.07,
    49.32,
    49.91,
    50.13,
    49.53,
    49.5,
    49.75,
    50.03,
    50.31,
    50.52,
    50.41,
    49.34,
    49.37,
    50.23,
    49.2375,
    49.93,
    48.43,
    48.18,
    46.57,
    45.41,
    47.77,
    47.72,
    48.62,
    47.85,
]
ATR_TR = [
    0.91,
    0.58,
    0.51,
    0.5,
    0.58,
    0.415,
    0.26,
    0.49,
    0.6,
    0.32,
    0.93,
    0.76,
    0.45,
    0.465,
    1.1,
    0.48,
    0.35,
    1.22,
    0.65,
    0.96,
    1.09,
    0.9325,
    1.85,
    0.86,
    6.7701,
    2.5167,
    2.39,
    1.19,
    0.94,
    1.0599,
]
ATR_EXPECTED = [
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    0.555,
    0.593929,
    0.585791,
    0.568949,
    0.615452,
    0.61792,
    0.642354,
    0.674329,
    0.69277,
    0.775429,
    0.78147,
    1.209229,
    1.30262,
    1.38029,
    1.366698,
    1.336219,
    1.316482,
]

_BB_SOURCE = (
    "https://chartschool.stockcharts.com/table-of-contents/technical-indicators"
    "-and-overlays/technical-overlays/bollinger-bands"
)
"""SPY daily closes with the Bollinger Bands (20,2) columns from cs-bbands.xls."""

BB_PRICE = [
    86.1557,
    89.0867,
    88.7829,
    90.3228,
    89.0671,
    91.1453,
    89.4397,
    89.175,
    86.9302,
    87.6752,
    86.9596,
    89.4299,
    89.3221,
    88.7241,
    87.4497,
    87.2634,
    89.4985,
    87.9006,
    89.126,
    90.7043,
    92.9001,
    92.9784,
    91.8021,
    92.6647,
    92.6843,
    92.3021,
    92.7725,
    92.5373,
    92.949,
    93.2039,
    91.0669,
    89.8318,
    89.7435,
    90.3994,
    90.7387,
    88.0177,
    88.0867,
    88.8439,
    90.7781,
    90.5416,
    91.3894,
    90.65,
]
BB_MID = [
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    88.70794,
    89.04516,
    89.239745,
    89.390705,
    89.5078,
    89.68866,
    89.7465,
    89.91314,
    90.081255,
    90.382195,
    90.65863,
    90.863995,
    90.88409,
    90.90516,
    90.988925,
    91.153375,
    91.19109,
    91.1205,
    91.167665,
    91.25027,
    91.242135,
    91.1666,
    91.05018,
]
BB_STD = [
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    1.291961,
    1.452054,
    1.686425,
    1.771747,
    1.902075,
    2.019895,
    2.076546,
    2.176557,
    2.241921,
    2.202359,
    2.192185,
    2.021805,
    2.009411,
    1.99508,
    1.936044,
    1.760127,
    1.682751,
    1.779126,
    1.70406,
    1.642001,
    1.645086,
    1.601325,
    1.549162,
]
BB_UPPER = [
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    91.291862,
    91.949268,
    92.612595,
    92.9342,
    93.31195,
    93.72845,
    93.899592,
    94.266255,
    94.565096,
    94.786912,
    95.043001,
    94.907605,
    94.902912,
    94.89532,
    94.861013,
    94.673629,
    94.556593,
    94.678752,
    94.575786,
    94.534271,
    94.532306,
    94.369251,
    94.148503,
]
BB_LOWER = [
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    86.124018,
    86.141052,
    85.866895,
    85.84721,
    85.70365,
    85.64887,
    85.593408,
    85.560025,
    85.597414,
    85.977478,
    86.274259,
    86.820385,
    86.865268,
    86.915,
    87.116837,
    87.633121,
    87.825587,
    87.562248,
    87.759544,
    87.966269,
    87.951964,
    87.963949,
    87.951857,
]


def _frame(high, low, close, volume=None):
    """OHLCV frame from parallel lists; `open` is unused by every indicator here."""
    n = len(close)
    return pd.DataFrame(
        {
            "open": close,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.ones(n) if volume is None else volume,
        },
        index=pd.RangeIndex(n),
    )


def _published(values):
    """Published column as a float Series; blank spreadsheet cells become NaN."""
    return pd.Series([np.nan if v is None else v for v in values], dtype=float)


def _assert_matches_published(got, expected, tol, label):
    """Compare against a published column on the bars the source actually publishes.

    Also asserts the NaN pattern, which is half the finding: the source leaves the
    warm-up bars blank because the indicator is undefined there, and an
    implementation that prints a number for bar 1 is wrong even where the
    converged values agree.
    """
    got = pd.Series(got).reset_index(drop=True)
    published = expected.notna()
    assert published.any(), "reference column is empty — the test would be vacuous"
    worst = (got[published] - expected[published]).abs().max()
    assert worst < tol, f"{label}: worst divergence {worst:.6g} exceeds {tol:g}"
    assert (got.isna() == expected.isna()).all(), (
        f"{label}: warm-up differs — source publishes "
        f"{int(expected.notna().sum())} values, we produce {int(got.notna().sum())}"
    )


def test_rsi_reproduces_the_stockcharts_worked_example():
    """Wilder seeds the averages with a simple mean of the first `period` changes.

    ChartSchool, and the Note in cs-rsi.xls itself: "First Average Gain = Sum of
    Gains over the past 14 periods / 14", and only then the recursion
    "[(previous Average Gain) x 13 + current Gain] / 14".

    Seeding with the first observation instead — which is what
    `ewm(alpha=1/period, adjust=False)` does — put bar 15 at 50.75 against the
    published 70.53. Those are opposite readings: neutral versus overbought.
    """
    from ibkr_core_mcp.indicators import rsi

    result = rsi(_frame(RSI_CLOSE, RSI_CLOSE, RSI_CLOSE), period=14)

    _assert_matches_published(result, _published(RSI_EXPECTED), 1e-3, "RSI")


def test_atr_reproduces_the_stockcharts_worked_example():
    """Same Wilder seeding, and the same defect, in the other Wilder indicator.

    ChartSchool: "The first True Range value is the current high minus the current
    low, and the first ATR is an average of the first 14 True Range values. The
    real ATR formula kicks in on day 15."

    The published first ATR is 0.555 — the mean of the 14 True Ranges above it —
    where this returned 0.678, and it printed a value on bar 1 where ATR has no
    definition at all.
    """
    from ibkr_core_mcp.indicators import atr

    result = atr(_frame(ATR_HIGH, ATR_LOW, ATR_CLOSE), period=14)

    _assert_matches_published(result, _published(ATR_EXPECTED), 1e-5, "ATR")


def test_bollinger_bands_reproduce_the_stockcharts_worked_example():
    """The deviation is the POPULATION standard deviation, not the sample one.

    ChartSchool's Standard Deviation page: "StockCharts.com calculates the standard
    deviation for a population, which assumes that the periods involved represent
    the whole data set, not a sample from a bigger data set." TradingView agrees
    independently — `ta.stdev(source, length, biased)` defaults `biased` to true.

    pandas' `Series.rolling(n).std()` defaults to ddof=1, so every band sat
    sqrt(20/19) = 2.60% too far from the middle.
    """
    from ibkr_core_mcp.indicators import bollinger_bands

    result = bollinger_bands(_frame(BB_PRICE, BB_PRICE, BB_PRICE), period=20, std=2.0)

    _assert_matches_published(result["bb_mid"], _published(BB_MID), 1e-5, "bb_mid")
    _assert_matches_published(result["bb_upper"], _published(BB_UPPER), 1e-5, "bb_upper")
    _assert_matches_published(result["bb_lower"], _published(BB_LOWER), 1e-5, "bb_lower")


def test_true_range_of_the_first_bar_is_the_high_low_range():
    """Two of the three True Range candidates need a previous close, so on bar 1
    only `high - low` is defined. The published column starts at 0.91 = 48.70 -
    47.79 rather than blank, and `max` over the candidates must not propagate the
    NaNs from the other two."""
    from ibkr_core_mcp.indicators import true_range

    result = true_range(_frame(ATR_HIGH, ATR_LOW, ATR_CLOSE))

    _assert_matches_published(result, _published(ATR_TR), 1e-9, "true_range")


def test_ema_seeds_with_the_first_value_not_a_simple_moving_average():
    """A guard against "fixing" EMA the way RSI and ATR genuinely needed fixing.

    TradingView publishes equivalent Pine source for both, and they differ on
    purpose (Pine Script v6 reference, ta.ema and ta.rma):

        pine_ema: sum := na(sum[1]) ? src                   : alpha*src + (1-alpha)*sum[1]
        pine_rma: sum := na(sum[1]) ? ta.sma(src, length)   : alpha*src + (1-alpha)*sum[1]

    Wilder's smoothing (rma) seeds with an SMA; a plain EMA seeds with the first
    value. Our `ema` matches pine_ema, so `macd` — built from two of them — matches
    TradingView too, which is what `pinescript.py` emits for these strategies.
    StockCharts documents an SMA seed for EMA instead; that disagreement is real
    and is resolved in favour of TradingView here, deliberately, because our
    generated scripts run there.
    """
    from ibkr_core_mcp.indicators import ema

    prices = [10.0, 11.0, 12.0, 13.0, 14.0]
    result = ema(_frame(prices, prices, prices), period=4)

    alpha = 2 / (4 + 1)
    expected = prices[0]
    for price in prices[1:]:
        expected = alpha * price + (1 - alpha) * expected

    assert result.iloc[0] == pytest.approx(prices[0]), "EMA must seed with the first value"
    assert result.iloc[-1] == pytest.approx(expected)


def test_vwap_restarts_each_session():
    """VWAP is a single-session measure, and ours ran cumulatively forever.

    "VWAP equals the dollar value of all trading periods divided by the total
    trading volume for the current day. The VWAP overlay is calculated using
    intraday data from a single market day, starting when trading opens and ending
    when it closes." — and, on the same page, "VWAP is not defined for daily,
    weekly, or monthly periods due to the nature of the calculation."
    https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/volume-weighted-average-price-vwap

    Two sessions, deliberately far apart in price. Carrying day one's volume into
    day two drags day two's first value toward 100; a correct session VWAP puts it
    exactly at day two's own typical price.
    """
    from ibkr_core_mcp.indicators import vwap

    index = pd.to_datetime(
        [
            "2025-01-02 09:30",
            "2025-01-02 09:31",
            "2025-01-03 09:30",
            "2025-01-03 09:31",
        ]
    )
    df = pd.DataFrame(
        {
            "open": [100.0, 100.0, 200.0, 200.0],
            "high": [100.0, 100.0, 200.0, 200.0],
            "low": [100.0, 100.0, 200.0, 200.0],
            "close": [100.0, 100.0, 200.0, 200.0],
            "volume": [1_000.0, 1_000.0, 1_000.0, 1_000.0],
        },
        index=index,
    )

    result = vwap(df)

    assert result.iloc[1] == pytest.approx(100.0)
    assert result.iloc[2] == pytest.approx(200.0), "session two must not inherit session one"
    assert result.iloc[3] == pytest.approx(200.0)


def test_vwap_can_still_run_over_the_whole_frame_when_asked_explicitly():
    """`anchor=None` keeps the old whole-series behaviour, but you have to ask."""
    from ibkr_core_mcp.indicators import vwap

    index = pd.to_datetime(["2025-01-02 09:30", "2025-01-03 09:30"])
    df = pd.DataFrame(
        {
            "open": [100.0, 200.0],
            "high": [100.0, 200.0],
            "low": [100.0, 200.0],
            "close": [100.0, 200.0],
            "volume": [1_000.0, 1_000.0],
        },
        index=index,
    )

    assert vwap(df, anchor=None).iloc[-1] == pytest.approx(150.0)


def test_vwap_refuses_a_frame_it_cannot_split_into_sessions():
    """A positional index carries no session boundaries. Silently falling back to a
    running total is how the whole-frame VWAP survived unnoticed, so this raises."""
    from ibkr_core_mcp.indicators import vwap

    df = _frame([1.0, 2.0], [1.0, 2.0], [1.0, 2.0], volume=[1.0, 1.0])

    with pytest.raises(ValueError, match="DatetimeIndex"):
        vwap(df)


def test_keltner_channels_use_a_ten_period_atr_by_default():
    """ChartSchool's default parameter triple is (20, 2.0, 10) — "The first number
    (20) sets the periods for the exponential moving average. The second number
    (2.0) is the ATR multiplier. The third number (10) is the number of periods for
    Average True Range (ATR)."
    https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/keltner-channels

    The ATR length was tied to the EMA length, so there was no way to express the
    documented default at all.
    """
    from ibkr_core_mcp.indicators import atr, ema, keltner_channels

    # Ranges must vary, or every True Range is identical and the two ATR lengths
    # agree by construction — the vacuity guard at the end of this test caught
    # exactly that on a first attempt with a constant-range ramp.
    rng = np.random.default_rng(7)
    prices = list(100.0 + np.cumsum(rng.normal(0, 0.8, 60)))
    highs = [p + abs(r) for p, r in zip(prices, rng.uniform(0.2, 3.0, 60), strict=True)]
    lows = [p - abs(r) for p, r in zip(prices, rng.uniform(0.2, 3.0, 60), strict=True)]
    df = _frame(highs, lows, prices)

    result = keltner_channels(df, period=20, atr_mult=2.0)

    expected_mid = ema(df, 20)
    expected_band = 2.0 * atr(df, 10)
    assert result["kc_mid"].iloc[-1] == pytest.approx(expected_mid.iloc[-1])
    assert result["kc_upper"].iloc[-1] == pytest.approx((expected_mid + expected_band).iloc[-1])
    assert result["kc_upper"].iloc[-1] != pytest.approx((expected_mid + 2.0 * atr(df, 20)).iloc[-1]), (
        "ATR(10) and ATR(20) must actually differ on this data, or the test is vacuous"
    )
