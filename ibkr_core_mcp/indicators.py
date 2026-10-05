"""Technical indicator functions for OHLCV DataFrames (pure functions, no side effects)."""

from __future__ import annotations

import numpy as np
import pandas as pd

SOURCES: tuple[str, ...] = ("open", "high", "low", "close", "hl2", "hlc3", "ohlc4", "hlcc4")
"""The price sources an indicator can be computed on — TradingView's own list, in its order.

Pine's `input.source()` documents the dropdown as "open/high/low/close/hl2/hlc3/ohlc4/hlcc4"
(https://www.tradingview.com/pine-script-reference/v6/#fun_input.source, read 2026-10-05).
TradingView's settings dialog shows the same eight as formulas — `hl2` reads "(H + L)/2"
there — and its chart legend prints the short name (`SMA 200 hl2`); the short names are the
vocabulary here. `price_source` holds each definition."""

MA_TYPES: dict[str, str] = {"SMA": "sma", "EMA": "ema", "SMMA (RMA)": "rma", "WMA": "wma", "VWMA": "vwma"}
"""TradingView's moving-average types, each mapped to the Pine function that defines it.

"The types of moving averages available for built-in indicators are: "SMA", "SMA + Bollinger
Bands", "EMA", "SMMA (RMA)", "WMA", and "VWMA"."
https://www.tradingview.com/support/solutions/43000742042/ (read 2026-10-05). The keys are
that list as written, less "SMA + Bollinger Bands", which is an SMA with `bollinger_bands`
drawn round it rather than a sixth average. The values (`ta.sma` … `ta.vwma`) name the
Series `moving_average` returns."""


def price_source(df: pd.DataFrame, source: str = "close") -> pd.Series:
    """The price series an indicator is computed on, by TradingView's name for it.

    Pine v6 defines the four built-in combinations in as many words
    (https://www.tradingview.com/pine-script-reference/v6/, `hl2`, `hlc3`, `ohlc4`, `hlcc4`):

        hl2    "Is a shortcut for (high + low)/2"
        hlc3   "Is a shortcut for (high + low + close)/3"
        ohlc4  "Is a shortcut for (open + high + low + close)/4"
        hlcc4  "Is a shortcut for (high + low + close + close)/4"

    `open`, `high`, `low` and `close` are the bar's own columns. A name outside `SOURCES` is
    refused: falling back to `close` would hand back a number computed on something the
    caller did not ask for, under the name they did ask for.

    Args:
        df: OHLCV frame.
        source: One of `SOURCES`. Default `close`, as in every Pine example.

    Returns:
        Series aligned to `df.index`.

    Raises:
        ValueError: If `source` is not one of `SOURCES`.
    """
    if source in ("open", "high", "low", "close"):
        return df[source]
    if source == "hl2":
        return (df["high"] + df["low"]) / 2
    if source == "hlc3":
        return (df["high"] + df["low"] + df["close"]) / 3
    if source == "ohlc4":
        return (df["open"] + df["high"] + df["low"] + df["close"]) / 4
    if source == "hlcc4":
        return (df["high"] + df["low"] + df["close"] + df["close"]) / 4
    raise ValueError(f"source must be one of {', '.join(SOURCES)}; got {source!r}")


def _wilder_smooth(values: pd.Series, period: int) -> pd.Series:
    """Wilder's smoothing: seed with the mean of the first `period` values, then recur.

    Wilder's RSI and ATR are both built on this one average, and both are wrong if
    it is seeded wrong. StockCharts states the seeding explicitly for each:

        "First Average Gain = Sum of Gains over the past 14 periods / 14"
        https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/relative-strength-index-rsi

        "the first ATR is an average of the first 14 True Range values. The real
         ATR formula kicks in on day 15."
        https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/average-true-range-atr

    TradingView agrees, and publishes equivalent Pine source that makes the contrast
    with a plain EMA explicit (Pine Script v6 reference, `ta.rma` and `ta.ema`):

        pine_rma: sum := na(sum[1]) ? ta.sma(src, length) : alpha*src + (1-alpha)*sum[1]
        pine_ema: sum := na(sum[1]) ? src                 : alpha*src + (1-alpha)*sum[1]

    `ewm(alpha=1/period, adjust=False)` is the second of those, not the first — it
    seeds with the first observation. That is the correct spelling of `ema()` and the
    wrong one for Wilder, and using it here put RSI up to 19.8 points and ATR up to
    22% away from the published references. `tests/test_indicators_worked_examples.py`
    pins both to those references.

    Leading NaNs are skipped rather than counted, so a gain series (which starts NaN,
    because it comes from `diff()`) seeds from its first *real* change. The result is
    NaN until the seed bar, because the average genuinely does not exist before it.

    Args:
        values: Series to smooth. Leading NaNs are ignored; an interior NaN is not
            special-cased and will propagate, which is the honest behaviour for a
            recursive average.
        period: Wilder's lookback, `n` in "previous x (n-1), plus current, over n".

    Returns:
        Series aligned to `values.index`, NaN before the seed bar.
    """
    raw = values.to_numpy(dtype=float)
    out = np.full(raw.shape, np.nan)
    present = np.flatnonzero(~np.isnan(raw))
    if present.size == 0:
        return pd.Series(out, index=values.index)
    start = int(present[0])
    seed_end = start + period
    if seed_end > raw.size:
        return pd.Series(out, index=values.index)
    out[seed_end - 1] = raw[start:seed_end].mean()
    for i in range(seed_end, raw.size):
        out[i] = (out[i - 1] * (period - 1) + raw[i]) / period
    return pd.Series(out, index=values.index)


def true_range(df: pd.DataFrame) -> pd.Series:
    """True Range: the greatest of the high-low range and the two gaps from the prior close.

    "True range is max(high - low, abs(high - close[1]), abs(low - close[1]))"
    https://www.tradingview.com/pine-script-reference/v6/#fun_ta.atr

    On the first bar there is no prior close, so two of the three candidates are NaN
    and only the high-low range is defined. `max(axis=1)` skips NaN, which is what
    makes that come out right — StockCharts' worked example likewise opens at
    48.70 - 47.79 = 0.91 rather than blank.

    Exposed publicly because ATR is not the only thing that wants it, and because a
    shared helper is the only way `atr` and any future range-based indicator cannot
    drift apart.

    Args:
        df: OHLCV frame; `high`, `low` and `close` are read.

    Returns:
        Series aligned to `df.index`, defined from the first bar.
    """
    prev_close = df["close"].shift(1)
    return pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)


def moving_average(df: pd.DataFrame, period: int = 20, ma_type: str = "SMA", source: str = "close") -> pd.Series:
    """A moving average of `source`, of one of TradingView's five types, to Pine's definition.

    Each type is the Pine function TradingView names for it, and each of those publishes
    its own arithmetic (https://www.tradingview.com/pine-script-reference/v6/, `ta.sma`,
    `ta.ema`, `ta.rma`, `ta.wma`, `ta.vwma`):

        SMA         "the sum of last y values of x, divided by y"
        EMA         "alpha * source + (1 - alpha) * EMA[1], where alpha = 2 / (length + 1)",
                    seeded with the first value (`na(sum[1]) ? src`)
        SMMA (RMA)  "the exponentially weighted moving average with alpha = 1 / length",
                    seeded with the SMA of the first `length` values — Wilder's smoothing,
                    the average inside RSI and ATR (`_wilder_smooth`)
        WMA         "weighting factors decrease in arithmetical progression": the newest bar
                    weighs `length`, the oldest 1 (`weight = (y - i) * y`, normalised)
        VWMA        "the same as: sma(source * volume, length) / sma(volume, length)"

    VWMA weighs by the frame's own volume. On IBKR bars that is IBKR's filtered historical
    volume (docs/market-data-conventions.md), so where an exchange's reported volume differs
    — crude futures — a VWMA differs from a chart built on that volume, for that reason.

    Args:
        df: OHLCV frame; `volume` is read for VWMA only.
        period: Number of bars — TradingView's "Length".
        ma_type: One of `MA_TYPES`.
        source: One of `SOURCES`.

    Returns:
        Series aligned to `df.index`, named `{sma|ema|rma|wma|vwma}_{period}_{source}`.
        NaN until `period` bars exist, except EMA, which Pine defines from the first bar.

    Raises:
        ValueError: If `ma_type` is not one of `MA_TYPES` or `source` not one of `SOURCES`.
    """
    src = price_source(df, source)
    if ma_type == "SMA":
        out = src.rolling(period).mean()
    elif ma_type == "EMA":
        out = src.ewm(span=period, adjust=False).mean()
    elif ma_type == "SMMA (RMA)":
        out = _wilder_smooth(src, period)
    elif ma_type == "WMA":
        # A window longer than the frame is never applied, so its weights are never used; the
        # cap keeps a wild `period` from allocating them.
        weights = np.arange(1, min(period, len(src)) + 1, dtype=float)
        out = src.rolling(period).apply(lambda window: float(window @ weights) / weights.sum(), raw=True)
    elif ma_type == "VWMA":
        volume = df["volume"]
        out = (src * volume).rolling(period).sum() / volume.rolling(period).sum().replace(0, float("nan"))
    else:
        raise ValueError(f"ma_type must be one of {', '.join(MA_TYPES)}; got {ma_type!r}")
    return out.rename(f"{MA_TYPES[ma_type]}_{period}_{source}")


def sma(df: pd.DataFrame, period: int = 20, source: str = "close") -> pd.Series:
    """Simple moving average of `source`. Returns a Series named `sma_{period}_{source}`.

    `moving_average(df, period, "SMA", source)` — see there for the definition and the
    sources. The Series is named for what it is: `sma_200_hl2` is not `sma_200_close`.
    """
    return moving_average(df, period, "SMA", source)


def ema(df: pd.DataFrame, period: int = 20, source: str = "close") -> pd.Series:
    """Exponential moving average of `source`, seeded with its first value.

    Deliberately NOT Wilder's smoothing, and deliberately not SMA-seeded. TradingView
    publishes equivalent Pine source for both averages, and the seeds differ on purpose
    (Pine Script v6 reference, `ta.ema` and `ta.rma`):

        pine_ema: sum := na(sum[1]) ? src                 : alpha*src + (1-alpha)*sum[1]
        pine_rma: sum := na(sum[1]) ? ta.sma(src, length) : alpha*src + (1-alpha)*sum[1]

    `ewm(span=period, adjust=False)` is exactly `pine_ema`, so this — and `macd`, built
    from two of these — agrees with what `pinescript.py` emits for TradingView.
    StockCharts documents an SMA seed for EMA instead
    (https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/moving-averages-simple-and-exponential);
    that disagreement is real, and is resolved in TradingView's favour here because our
    generated scripts run there. `_wilder_smooth` is the other seed, for the two
    indicators Wilder actually defined.

    Args:
        df: OHLCV frame.
        period: EMA span; alpha = 2 / (period + 1).
        source: One of `SOURCES`. Default `close`.

    Returns:
        Series aligned to `df.index`, named `ema_{period}_{source}`, defined from the
        first bar.
    """
    return moving_average(df, period, "EMA", source)


def rsi(df: pd.DataFrame, period: int = 14, source: str = "close") -> pd.Series:
    """Relative Strength Index (0–100). Returns a Series. Values >70 overbought, <30 oversold.

    Zero average loss is a divide-by-zero for RS, and Wilder's convention resolves it by
    definition rather than by propagating NaN:

        "If the Average Loss equals zero, a 'divide by zero' situation occurs for RS, and
         RSI is set to 100 by definition. Similarly, RSI equals 0 when Average Gain
         equals zero."
        https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/relative-strength-index-rsi

    This previously did `gain / loss.replace(0, nan)`, which made the whole series NaN
    for any uninterrupted uptrend — `add_indicators` rendered "RSI(14): nan" — and for a
    flat series. `test_rsi_bounds` could not catch it: it filtered with `dropna()` and
    then asserted `.all()`, which pandas evaluates as True on an empty Series.

    A perfectly flat series leaves both averages at zero. RS is then 0/0, no source
    defines it, and NaN is returned rather than inventing a neutral 50.

    RSI is defined on closing prices — TradingView's own long form opens `change =
    change(close)` and ends "exactly equal to rsi(close, 14)"
    (https://www.tradingview.com/support/solutions/43000502338-relative-strength-index-rsi/)
    — and `close` is the default here for that reason. `ta.rsi(source, length)` takes any
    source, and so does this; a caller who moves it off `close` is asking for a different
    oscillator and should say so wherever the number is shown.

    Args:
        df: OHLCV frame.
        period: Wilder smoothing period.
        source: One of `SOURCES`. Default `close`.

    Returns:
        Series aligned to `df.index`, 0–100, NaN only where genuinely undefined.
    """
    delta = price_source(df, source).diff()
    gain = _wilder_smooth(delta.clip(lower=0), period)
    loss = _wilder_smooth(-delta.clip(upper=0), period)
    rs = gain / loss.replace(0, float("nan"))
    result = 100 - (100 / (1 + rs))
    # Wilder's by-definition cases, applied only where the division actually failed.
    result = result.mask((loss == 0) & (gain > 0), 100.0)
    return result.mask((gain == 0) & (loss > 0), 0.0)


def macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9, source: str = "close") -> pd.DataFrame:
    """MACD. Columns: 'macd', 'macd_signal', 'histogram'.

        "MACD Line: (12-day EMA - 26-day EMA)
         Signal Line: 9-day EMA of MACD Line
         MACD Histogram: MACD Line - Signal Line"
        https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/macd-moving-average-convergence-divergence-oscillator

    Built from plain EMAs, seeded with the first observation — see `ema` for why that
    seed is right here and wrong for `rsi`/`atr`. Verified unchanged by the 2026-09-16
    indicator audit; it is the Wilder-smoothed pair that was wrong, not this.

    "Closing prices are used for these moving averages" (same page), so `close` is the
    default. `ta.macd(source, fastlen, slowlen, siglen)` takes any source, and so does
    this. TradingView's indicator also offers an "Oscillator MA type" and a "Signal MA
    type" (EMA or SMA, https://www.tradingview.com/support/solutions/43000502344-moving-average-convergence-divergence-macd-indicator/);
    those are not offered here — all three averages are EMAs, the definition quoted above.

    Args:
        df: OHLCV frame.
        fast: Span of the faster EMA.
        slow: Span of the slower EMA.
        signal: Span of the EMA taken over the MACD line.
        source: One of `SOURCES`. Default `close`.

    Returns:
        DataFrame indexed like `df`, defined from the first bar.
    """
    src = price_source(df, source)
    ema_fast = src.ewm(span=fast, adjust=False).mean()
    ema_slow = src.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return pd.DataFrame(
        {"macd": macd_line, "macd_signal": signal_line, "histogram": macd_line - signal_line},
        index=df.index,
    )


def vwap(
    df: pd.DataFrame,
    anchor: str | None = "D",
    *,
    tz: str | None = None,
    session_open: str | None = None,
) -> pd.Series:
    """Volume-Weighted Average Price, accumulated within each `anchor` session.

    VWAP measures one session. It is not a running average over whatever range of
    bars you happen to hold:

        "VWAP equals the dollar value of all trading periods divided by the total
         trading volume for the current day. The VWAP overlay is calculated using
         intraday data from a single market day, starting when trading opens and
         ending when it closes."

        "VWAP is not defined for daily, weekly, or monthly periods due to the
         nature of the calculation."
        https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/volume-weighted-average-price-vwap

    This accumulated from the first bar of the frame to the last and never reset, so
    on a multi-day intraday frame every session after the first carried the whole
    history of the ones before it — a number that answers no question anyone asks.

    On daily or coarser bars each session holds a single bar and VWAP degenerates to
    that bar's typical price. That is the arithmetic consequence of the definition
    above, not a useful indicator; `ClaudeToolkit._add_indicators` reports VWAP only
    for intraday timeframes for that reason.

    Args:
        df: OHLCV frame; `high`, `low`, `close` and `volume` are read.
        anchor: pandas offset alias naming the session boundary — "D" (default) for
            a calendar day, "W" for a week, and so on, on the clock `tz` selects.
            `None` accumulates across the whole frame, which is the pre-2026-09-16
            behaviour and now has to be asked for by name.
        tz: IANA zone the session is defined in, e.g. "America/New_York". A naive
            index is read as UTC — that is what `bars_to_dataframe` builds — and an
            aware one is converted. **With no `tz` a session is the calendar day of the
            index as given**: the UTC day for IBKR bars, which is the exchange day for
            regular-hours bars of a US or European listing and is not for a CME
            session, which opens at 18:00 New York and crosses midnight UTC an hour
            later. Measured 2026-09-17 on ES minute bars: 4800.00 at 23:59 UTC,
            5000.00 at 00:00 UTC, the session's earlier prints discarded (DATA-R6).
            This docstring said "calendar day" without saying whose until then.
        session_open: "HH:MM" on that clock at which a session begins; bars before it
            belong to the previous session. `tz="America/New_York",
            session_open="18:00"` is the CME session. Default midnight.

    Returns:
        Series aligned to `df.index`.

    Raises:
        ValueError: If `anchor` is set and `df.index` is not a DatetimeIndex, since
            there is then no way to tell where one session ends. Falling back to a
            running total is what hid this defect, so it is refused rather than
            guessed. Also if `session_open` is not "HH:MM".
    """
    typical = (df["high"] + df["low"] + df["close"]) / 3
    weighted = typical * df["volume"]
    if anchor is None:
        return weighted.cumsum() / df["volume"].cumsum()
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError(
            f"vwap(anchor={anchor!r}) needs a DatetimeIndex to find session boundaries; "
            f"got {type(df.index).__name__}. Pass anchor=None for a whole-frame "
            "cumulative VWAP, or index the frame by timestamp."
        )
    session = _session_labels(df.index, anchor, tz, session_open)
    return weighted.groupby(session).cumsum() / df["volume"].groupby(session).cumsum()


def _session_labels(index: pd.DatetimeIndex, anchor: str, tz: str | None, session_open: str | None) -> pd.PeriodIndex:
    """One label per bar naming its session, on the exchange's clock when one is given.

    The index is moved onto `tz`'s wall clock (a naive index read as UTC), shifted back by
    `session_open` so a session that opens at 18:00 falls inside one calendar day, and
    then cut into `anchor` periods. Without `tz` the wall clock is the index's own; an
    aware index is read on its own clock rather than converted (DATA-R6).
    """
    clock = index
    if tz is not None:
        aware = clock.tz_localize("UTC") if clock.tz is None else clock
        clock = aware.tz_convert(tz).tz_localize(None)
    elif clock.tz is not None:
        clock = clock.tz_localize(None)
    if session_open is not None:
        try:
            hours, minutes = (int(part) for part in session_open.split(":"))
        except ValueError:
            raise ValueError(f"session_open must be 'HH:MM', e.g. '18:00'; got {session_open!r}") from None
        clock = clock - pd.Timedelta(hours=hours, minutes=minutes)
    return clock.to_period(anchor)


def bollinger_bands(
    df: pd.DataFrame, period: int = 20, std: float = 2.0, source: str = "close", ma_type: str = "SMA"
) -> pd.DataFrame:
    """Bollinger Bands. Columns: 'bb_upper', 'bb_mid', 'bb_lower'.

    The deviation is the POPULATION standard deviation (ddof=0), which is the whole
    reason `ddof` is written out below rather than left to the pandas default:

        "StockCharts.com calculates the standard deviation for a population, which
         assumes that the periods involved represent the whole data set, not a sample
         from a bigger data set."
        https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/standard-deviation-volatility

    TradingView agrees independently, and says so in as many words — `ta.stdev(source,
    length, biased)` defaults `biased` to true, and "If `biased` is true, function will
    calculate using a biased estimate of the entire population, if false - unbiased
    estimate of a sample."
    https://www.tradingview.com/pine-script-reference/v6/#fun_ta.stdev

    `Series.rolling(n).std()` defaults to ddof=1, so every band previously sat
    sqrt(20/19) = 2.60% too far from the middle at the default period. Band touches are
    the signal, so a systematically too-wide band under-reports every one of them.

    **One source for the basis and the deviation.** Pine publishes `ta.bb` as
    `basis = ta.sma(src, length)` and `dev = mult * ta.stdev(src, length)`
    (https://www.tradingview.com/pine-script-reference/v6/#fun_ta.bb): bands on `hl2` are an
    average of `hl2` plus and minus a deviation of `hl2`, never an average of one series
    inside a deviation of another.

    **`ma_type` is TradingView's "Basis MA Type", and it moves the middle line only.**
    TradingView: "Determines the type of Moving Average that is applied to the basis plot
    line" (https://www.tradingview.com/support/solutions/43000501840-bollinger-bands-bb/).
    The deviation stays `ta.stdev`, which Pine computes around the *simple* mean whatever
    the basis is. John Bollinger's own rules disagree with that combination, and say why the
    default is an SMA:

        "12. Traditional Bollinger Bands are based upon a simple moving average. This is
         because a simple average is used in the standard deviation calculation and we wish
         to be logically consistent."
        "13. … Exponential averages must be used for BOTH the middle band and in the
         calculation of standard deviation."
        https://www.bollingerbands.com/bollinger-band-rules

    TradingView's parameter is what is reproduced here, because matching its settings is the
    purpose; with a non-SMA basis these are TradingView's bands, not Bollinger's exponential
    ones. That reading of the help text had not been checked against a TradingView chart with
    a non-SMA basis when this was written (2026-10-05).

    Args:
        df: OHLCV frame.
        period: Lookback for both the basis and the deviation — TradingView's "Length".
        std: Deviation multiplier for the outer bands — TradingView's "StdDev".
        source: One of `SOURCES`. Default `close`.
        ma_type: One of `MA_TYPES`, for the basis. Default `SMA`.

    Returns:
        DataFrame indexed like `df`, NaN for the first `period - 1` bars.
    """
    mid = moving_average(df, period, ma_type, source)
    dev = price_source(df, source).rolling(period).std(ddof=0)
    return pd.DataFrame(
        {"bb_upper": mid + std * dev, "bb_mid": mid, "bb_lower": mid - std * dev},
        index=df.index,
    )


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range — Wilder's smoothing of True Range. Returns a Series.

    "The first True Range value is the current high minus the current low, and the
     first ATR is an average of the first 14 True Range values. The real ATR formula
     kicks in on day 15."
    https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/average-true-range-atr

    This used `ewm(alpha=1/period, adjust=False)`, which seeds with the first True
    Range rather than the mean of the first `period` of them. Against ChartSchool's
    own published worked example that was up to 22% high, and it printed a value on
    bar 1 where ATR has no definition. See `_wilder_smooth`.

    Args:
        df: OHLCV frame; `high`, `low` and `close` are read.
        period: Wilder lookback.

    Returns:
        Series aligned to `df.index`, NaN for the first `period - 1` bars.
    """
    return _wilder_smooth(true_range(df), period)


def stochastic(df: pd.DataFrame, k: int = 14, d: int = 3) -> pd.DataFrame:
    """FAST Stochastic oscillator (14, 3). Columns: 'stoch_k', 'stoch_d'.

    Which of the three variants this is was left unstated, and they do not agree:

        "Fast %K = %K basic calculation; Fast %D = 3-period SMA of Fast %K"
        "Slow %K = Fast %K smoothed with 3-period SMA; Slow %D = 3-period SMA of Slow %K"
        https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/stochastic-oscillator-fast-slow-and-full

    %K here is unsmoothed, so this is the Fast form — verified correct against that
    definition, and named now so a caller comparing against a charting package's
    default (commonly Slow) knows why the lines differ rather than assuming a bug.

    Args:
        df: OHLCV frame; `high`, `low` and `close` are read.
        k: Look-back for the %K high/low range.
        d: SMA length for the %D signal line.

    Returns:
        DataFrame indexed like `df`. A flat window makes the range zero and %K
        undefined; NaN is returned there rather than a neutral 50.
    """
    lo = df["low"].rolling(k).min()
    hi = df["high"].rolling(k).max()
    pct_k = 100 * (df["close"] - lo) / (hi - lo).replace(0, float("nan"))
    return pd.DataFrame({"stoch_k": pct_k, "stoch_d": pct_k.rolling(d).mean()}, index=df.index)


def williams_r(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Williams %R oscillator (-100 to 0). Returns a Series. Values > -20 overbought, < -80 oversold."""
    hi = df["high"].rolling(period).max()
    lo = df["low"].rolling(period).min()
    return -100 * (hi - df["close"]) / (hi - lo).replace(0, float("nan"))


def keltner_channels(
    df: pd.DataFrame,
    period: int = 20,
    atr_mult: float = 2.0,
    atr_period: int = 10,
) -> pd.DataFrame:
    """Keltner Channels (EMA ± an ATR multiple). Columns: 'kc_upper', 'kc_mid', 'kc_lower'.

    ChartSchool's documented defaults are the parameter triple (20, 2.0, 10):

        "Middle Line: 20-day exponential moving average
         Upper Channel Line: 20-day EMA + (2 x ATR(10))"

        "The first number (20) sets the periods for the exponential moving average.
         The second number (2.0) is the ATR multiplier. The third number (10) is the
         number of periods for Average True Range (ATR)."
        https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/keltner-channels

    The ATR length was previously tied to the EMA length, so the documented default
    could not be expressed at all — `keltner_channels(df)` gave EMA(20) ± 2·ATR(20).

    The two authorities genuinely differ here, so this one is a choice rather than a
    correction. TradingView's `ta.kc` uses an *EMA* of true range at the same length
    as the basis, not Wilder's ATR at a separate one
    (https://www.tradingview.com/pine-script-reference/v6/#fun_ta.kc). ChartSchool's
    form is followed because its (20, 2.0, 10) triple is the charting default users
    will compare against, and `atr_period` makes the difference addressable either
    way.

    Args:
        df: OHLCV frame.
        period: Lookback for the EMA that forms the middle line.
        atr_mult: How many ATRs the channels sit from the middle line.
        atr_period: Lookback for the ATR that sets channel width. Defaults to 10,
            independent of `period`.

    Returns:
        DataFrame indexed like `df` with 'kc_upper', 'kc_mid' and 'kc_lower'.
    """
    mid = ema(df, period)
    band = atr_mult * atr(df, atr_period)
    return pd.DataFrame(
        {"kc_upper": mid + band, "kc_mid": mid, "kc_lower": mid - band},
        index=df.index,
    )


def obv(df: pd.DataFrame) -> pd.Series:
    """On-Balance Volume (cumulative). Returns a Series. Rising OBV confirms uptrend."""
    direction = np.sign(df["close"].diff()).fillna(0)
    return (direction * df["volume"]).cumsum()


def volume_sma(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Simple moving average of volume. Returns a Series."""
    return df["volume"].rolling(period).mean()


def volume_ratio(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Current volume divided by its SMA. Returns a Series. Values >1 indicate above-average volume."""
    avg = volume_sma(df, period)
    return df["volume"] / avg.replace(0, float("nan"))


def add_all(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of df with all indicator columns appended."""
    out = df.copy()
    out["sma_20"] = sma(df, 20)
    out["ema_20"] = ema(df, 20)
    out["rsi"] = rsi(df, 14)
    _macd = macd(df)
    out["macd"] = _macd["macd"]
    out["macd_signal"] = _macd["macd_signal"]
    out["macd_hist"] = _macd["histogram"]
    out["vwap"] = vwap(df)
    _bb = bollinger_bands(df)
    out["bb_upper"] = _bb["bb_upper"]
    out["bb_mid"] = _bb["bb_mid"]
    out["bb_lower"] = _bb["bb_lower"]
    out["atr"] = atr(df, 14)
    _stoch = stochastic(df)
    out["stoch_k"] = _stoch["stoch_k"]
    out["stoch_d"] = _stoch["stoch_d"]
    out["williams_r"] = williams_r(df)
    _kc = keltner_channels(df)
    out["kc_upper"] = _kc["kc_upper"]
    out["kc_mid"] = _kc["kc_mid"]
    out["kc_lower"] = _kc["kc_lower"]
    out["obv"] = obv(df)
    out["volume_sma"] = volume_sma(df)
    out["volume_ratio"] = volume_ratio(df)
    return out
