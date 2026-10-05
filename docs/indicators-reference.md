# Indicators reference — every setting, its default, and where its definition comes from

What `add_indicators` and `ibkr_core_mcp.indicators` compute, setting by setting. The aim is
narrow and stated: **an indicator here takes the settings TradingView offers for it, under
TradingView's names, and prints them on every line** — so a figure can be held against the
same line on a chart, and so no figure is ever read as being on a source, a type or a length
it was not computed on. It is not an attempt to reproduce TradingView.

Each row is either a sentence from the source's own page (linked, read 2026-10-05) or a
measurement (dated). Where neither exists the row says *not established*. Research index:
`claudia_ui/.firecrawl/indicators/SOURCES.md` (scrapes of 2026-09-23 and 2026-10-05,
git-ignored). Decisions: the operator's, 2026-10-05, recorded in claudia_ui's
`docs/project-status.md`.

Bars themselves — stamps, hours, volume — are `docs/market-data-conventions.md`.

---

## 1. The settings of `add_indicators`

Every one is optional. One left out is computed at its default **and printed as
`(by default)`**; one given is printed as `(as given)`. One call is one configuration: the
source, type and offset apply to every average and band in it, and a different mix is a second
call.

| Input | TradingView's name | Values | Default | Whose default |
|---|---|---|---|---|
| `source` | Source (moving averages, Bollinger bands) | `open` `high` `low` `close` `hl2` `hlc3` `ohlc4` `hlcc4` (§2) | **`hl2`** | The operator's. TradingView's is `close` ("Close is the default") |
| `oscillator_source` | Source (RSI, MACD) | the same eight | **`close`** | The indicators' own definition, and TradingView's default (§6) |
| `ma_type` | the indicator itself for an average (SMA, EMA, …); **Basis MA Type** on the bands | `SMA` `EMA` `SMMA (RMA)` `WMA` `VWMA` (§3) | **`SMA`** | TradingView's |
| `ma_periods` | Length, one per average | a list of whole numbers ≥ 1, e.g. `[25, 50, 100, 200]` | none — no average is reported | — (TradingView's SMA opens at 9: "9 days is the default") |
| `band_period` | Length (Bollinger bands) | a whole number ≥ 1 | **`20`** | TradingView's and Bollinger's ("20 days is the default") |
| `band_stds` | StdDev (Bollinger bands) | a list of numbers > 0, one band pair each, e.g. `[1, 2, 2.5]` | **`[2]`** | TradingView's and Bollinger's ("2 is the default") |
| `offset` | Offset (moving averages, Bollinger bands) | a whole number of bars, either sign (§5) | **`0`** | TradingView's ("0 is the default") |

Sources for the names and defaults: TradingView's help pages for
[Bollinger Bands](https://www.tradingview.com/support/solutions/43000501840-bollinger-bands-bb/)
(Length, Basis MA Type, Source, StdDev, Offset),
the [Simple Moving Average](https://www.tradingview.com/support/solutions/43000696841-simple-moving-average/)
(Length, Source, Offset),
[RSI](https://www.tradingview.com/support/solutions/43000502338-relative-strength-index-rsi/)
(RSI Length, Source) and
[MACD](https://www.tradingview.com/support/solutions/43000502344-moving-average-convergence-divergence-macd-indicator/)
(Source, Fast length, Slow length, Signal length, Oscillator MA type, Signal MA type).

**A value outside a list is refused, with the list** — `add_indicators: source 'typical' is not
one of TradingView's price sources (open, high, low, close, hl2, hlc3, ohlc4, hlcc4). Nothing
computed.` The schema's `enum` is not enforced server-side; computing on `close` under the name
that was asked for is the silent substitution this tool exists to remove.

**The `hl2` default is the tool's, not the functions'.** `indicators.sma(df, 200)` in Python is
still an average of `close`, as it always was (§10); the tool always passes a source.

---

## 2. Price sources

TradingView's own list, in its order — Pine's `input.source()` documents the dropdown as
"open/high/low/close/hl2/hlc3/ohlc4/hlcc4"
([Pine v6 reference](https://www.tradingview.com/pine-script-reference/v6/#fun_input.source)).

| Name | Definition | Pine's words |
|---|---|---|
| `open` `high` `low` `close` | the bar's own value | — |
| `hl2` | (high + low) / 2 | "Is a shortcut for (high + low)/2" |
| `hlc3` | (high + low + close) / 3 | "Is a shortcut for (high + low + close)/3" |
| `ohlc4` | (open + high + low + close) / 4 | "Is a shortcut for (open + high + low + close)/4" |
| `hlcc4` | (high + low + close + close) / 4 | "Is a shortcut for (high + low + close + close)/4" |

TradingView shows the same eight in two spellings: the settings dialog writes the formula
(`hl2` reads **(H + L)/2** there) and the chart legend writes the short name (`SMA 200 hl2`).
The short names are the vocabulary here, and the result prints the formula beside the name
where the setting is stated: `source: hl2 = (high + low)/2 (by default)`.

Averaging something other than the close is ordinary practice, not a departure: "Most moving
averages are based on closing prices… However, moving averages can be applied to other types
of price data"
([ChartSchool](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/moving-averages-simple-and-exponential)),
and TradingView's Awesome Oscillator is defined on the bar's midpoint — "not calculated using
closing price but rather each bar's midpoints", `sma((high+low)/2, …)`
([Awesome Oscillator](https://www.tradingview.com/support/solutions/43000501826-awesome-oscillator-ao/)).

---

## 3. Moving-average types

"The types of moving averages available for built-in indicators are: "SMA", "SMA + Bollinger
Bands", "EMA", "SMMA (RMA)", "WMA", and "VWMA"."
([TradingView](https://www.tradingview.com/support/solutions/43000742042/)). The five averages
are offered under those names; "SMA + Bollinger Bands" is an SMA with bands drawn round it, which
here is `ma_periods` plus the band settings.

| `ma_type` | Pine function | Definition, in Pine's words | First value |
|---|---|---|---|
| `SMA` | `ta.sma` | "the sum of last y values of x, divided by y" | after `length` bars |
| `EMA` | `ta.ema` | "`EMA = alpha * source + (1 - alpha) * EMA[1]`, where `alpha = 2 / (length + 1)`", seeded with the first value | first bar (but see §8) |
| `SMMA (RMA)` | `ta.rma` | "the exponentially weighted moving average with alpha = 1 / length", seeded with the SMA of the first `length` values — Wilder's smoothing, the average inside RSI and ATR | after `length` bars |
| `WMA` | `ta.wma` | "weighting factors decrease in arithmetical progression" — the newest bar weighs `length`, the oldest 1 | after `length` bars |
| `VWMA` | `ta.vwma` | "the same as: sma(source \* volume, length) / sma(volume, length)" | after `length` bars |

All five: [Pine v6 reference](https://www.tradingview.com/pine-script-reference/v6/), `ta.sma`,
`ta.ema`, `ta.rma`, `ta.wma`, `ta.vwma`, each with its "same on pine" source.

**VWMA weighs by the bars' own volume, which on IBKR bars is IBKR's filtered historical
volume** — block trades, combos and derivative-priced trades excluded
(`docs/market-data-conventions.md`). Where an exchange's reported volume differs, as on crude
futures, a VWMA differs from a chart built on that volume, for that reason and not through an
error in either.

---

## 4. Bollinger bands

**One source for the basis and the deviation.** Pine publishes `ta.bb` as
`basis = ta.sma(src, length)` and `dev = mult * ta.stdev(src, length)`
([`ta.bb`](https://www.tradingview.com/pine-script-reference/v6/#fun_ta.bb)): bands on `hl2`
are an average of `hl2` plus and minus a deviation of `hl2`.

**The deviation is the population standard deviation** (divide by `length`, not `length − 1`).
`ta.stdev`'s `biased` argument defaults to true — "a biased estimate of the entire population"
([`ta.stdev`](https://www.tradingview.com/pine-script-reference/v6/#fun_ta.stdev)) — and
ChartSchool states the same
([Standard Deviation](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/standard-deviation-volatility)).
`tests/test_indicators_worked_examples.py` pins it to ChartSchool's published spreadsheet.

**`ma_type` is TradingView's "Basis MA Type", and it moves the middle line only.** TradingView:
"Determines the type of Moving Average that is applied to the basis plot line". The deviation
stays `ta.stdev`, which Pine computes around the *simple* mean whatever the basis is. John
Bollinger's own rules say why the default is an SMA, and disagree with mixing:

> 12\. Traditional Bollinger Bands are based upon a simple moving average. This is because a
> simple average is used in the standard deviation calculation and we wish to be logically
> consistent.
>
> 13\. Exponential Bollinger Bands eliminate sudden changes in the width of the bands caused by
> large price changes exiting the back of the calculation window. Exponential averages must be
> used for BOTH the middle band and in the calculation of standard deviation.
>
> — [bollingerbands.com, Bollinger Band Rules](https://www.bollingerbands.com/bollinger-band-rules)

TradingView's parameter is what is reproduced, because matching its settings is the purpose:
with a non-SMA basis these are TradingView's bands, not Bollinger's exponential ones. The
result says what the deviation is on every call — `1 StdDev = 29.12: population standard
deviation of hl2 over 200 bars`. Bollinger's rule 9 covers the rest: the 20 and the 2 "are just
that, defaults".

---

## 5. Offset

TradingView: "Changing this number will move the [Simple Moving Average / Bollinger Bands]
either Forwards or Backwards relative to the current market. 0 is the default." Pine's `plot`:
"Shifts the plot to the left or to the right on the given number of bars"
([`plot`](https://www.tradingview.com/pine-script-reference/v6/#fun_plot)).

**The values do not change; where they are drawn does.** This tool reports the last bar, so:

| `offset` | What TradingView draws | What the line reports |
|---|---|---|
| `0` | each value on its own bar | the value computed on the last bar |
| `+k` | the line moved `k` bars to the right | the value computed `k` bars before the last bar — the one sitting on the last bar. Needs `length + k` bars |
| `−k` | the line moved `k` bars to the left | `nothing is drawn on the last bar — the line ends k bar(s) earlier` |

A non-zero offset is part of the label: `SMA 200 hl2 offset 5`. It applies to the averages and
the bands, as in TradingView; RSI and MACD have no Offset input there and none here.

---

## 6. RSI and MACD

Both are defined by their authors on closing prices, and `close` is their default here for
that reason — independently of the averages' source:

- **RSI** — TradingView's own long form opens `change = change(close)` and ends "exactly equal
  to rsi(close, 14)"; "Source … Close is the default". Wilder's smoothing, seeded with the
  simple average of the first 14 changes
  ([ChartSchool](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/relative-strength-index-rsi)).
- **MACD** — "Closing prices are used for these moving averages"
  ([ChartSchool](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/macd-moving-average-convergence-divergence-oscillator));
  12- and 26-bar EMAs, a 9-bar EMA of their difference.

Pine gives each a source — `ta.rsi(source, length)`, `ta.macd(source, fastlen, slowlen,
siglen)` — and `oscillator_source` is that setting, for both. Averages on `hl2` beside an RSI on
`close` is the ordinary arrangement and not a mix of sources: they are separate instruments,
each on the price it is defined on, and each line names its own (`RSI(14) close`,
`MACD(12,26,9) hl2`). The lengths are fixed at 14 and 12/26/9.

---

## 7. The lines that take no source

| Line | Definition | Length |
|---|---|---|
| `ATR(14)` | Wilder's smoothing of True Range — "max(high - low, abs(high - close[1]), abs(low - close[1]))" | 14 |
| `VWAP` | (high + low + close)/3 weighted by volume, restarted each session. **Regular-hours intraday bars only** | — |
| `Stoch %K/%D (14,3)` | The **Fast** Stochastic: %K unsmoothed, %D its 3-bar SMA. Charting packages often open on the Slow one | 14, 3 |
| `Williams %R (14)` | (highest high − close) / (highest high − lowest low) × −100 | 14 |
| `Volume Ratio (20)` | The bar's volume over its 20-bar average (IBKR's filtered volume) | 20 |

**VWAP has two cases where it prints the reason instead of a figure.** On daily or coarser bars:
"VWAP is not defined for daily, weekly, or monthly periods due to the nature of the calculation"
([ChartSchool](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/volume-weighted-average-price-vwap)).
And on an **all-hours** series (`outside_rth=true`): the VWAP here restarts on the UTC day,
which a regular US or European session sits inside and an all-hours one does not — a CME
session opens at 18:00 New York and crosses midnight UTC (measured 2026-09-17 on ES minute bars:
the figure restarted mid-session), and a US stock's post-market runs past midnight UTC while New
York is on standard time. The tool does not guess a session; `indicators.vwap(df, tz=…,
session_open=…)` takes one from a caller who knows it.

---

## 8. When a line has no value — never `nan`

| Cause | The line reads | The cure |
|---|---|---|
| Fewer bars in the window than the line needs | `n/a — 126 bars in the window, 200 needed; fetch a longer period` | Fetch a longer period. There is no other: nothing is fetched behind the scenes |
| Enough bars, and the definition divides by zero — a flat window under RSI or the Stochastic, a zero deviation under the bands | `n/a — undefined on the last bar` | None; the indicator has no value there, and no neutral one is invented |
| A negative offset | `nothing is drawn on the last bar — the line ends k bar(s) earlier` | — |

"The window" is the bars that were fetched: TradingView has years of history behind a chart,
and this tool has what `fetch_market_data` cached.

| Line | Bars needed |
|---|---|
| An average or bands of length `n` (offset `+k`) | `n + k` |
| `RSI(14)` | 15 — fourteen changes |
| `MACD(12,26,9)` | 34 — a 26-bar average and nine values of it |
| `ATR(14)`, `Williams %R (14)` | 14 |
| `Stoch %K/%D (14,3)` | 16 |
| `Volume Ratio (20)` | 20 |

**The count applies to EMA and MACD too, and that is this tool's rule, not TradingView's.** Pine
defines an EMA from the first bar, so a 200-bar EMA on 126 bars is a number — one still
dominated by where the data happened to start, and not one to act on. It reads `n/a` here.

**Recursive averages near the start of the data.** EMA, RSI and MACD carry their starting point
forward and settle as bars accumulate (ChartSchool calculates "back at least 250 periods" for
this reason). The rule, stated in the tool's description rather than hidden in a second fetch:
*ask for a period longer than your longest length*. After a six-month daily window the starting
value's remaining weight on the last bar is of the order of 10⁻⁴ or less for the default lengths.

---

## 9. The result, line by line

The five-bar frame of the tests, worked by hand — `hl2` = 6, 8, 10, 12, 14, each close one
above. `ma_periods=[3, 200]`, `band_period=3`, `band_stds=[1, 2.5]`:

```text
Indicators for AAPL 1D, regular trading hours (by default) (last bar: 2026-05-22):
  Averages and bands — source: hl2 = (high + low)/2 (by default); type: SMA (by default); offset: 0 (by default)
  Bands — length: 3 (as given); StdDev: 1, 2.5 (as given)
  RSI and MACD — source: close (by default)
  SMA 3 hl2: 12.00
  SMA 200 hl2: n/a — 5 bars in the window, 200 needed; fetch a longer period
  BB 3 SMA hl2 1: 12.00 / 13.63 / 10.37 (basis / upper / lower)
  BB 3 SMA hl2 2.5: 12.00 / 16.08 / 7.92 (basis / upper / lower)
  last close 15.00 = SMA 3 hl2 + 1.84 StdDev (1 StdDev = 1.63: population standard deviation of hl2 over 3 bars)
  RSI(14) close: n/a — 5 bars in the window, 15 needed; fetch a longer period
  …
```

- **The first three lines are the configuration**, every setting with `(by default)` or
  `(as given)`.
- **Averages and bands carry TradingView's legend labels** — `SMA 200 hl2` is type, length,
  source; `BB 200 SMA hl2 2.5` is length, basis type, source, StdDev — so a line here is held
  against the line of the same name on the chart. A band line gives basis, upper, lower.
- **`last close … = … ± n StdDev`** is the one sentence TradingView has no need of, since it
  draws the picture: where the last bar's **close** sits against the bands' basis, in the bands'
  own deviations. The close is the price; the average and the deviation are the source's. Above:
  (15 − 12) / 1.633 = +1.84.
- The remaining lines are RSI, MACD, ATR, VWAP, the Stochastic, Williams %R and Volume Ratio.

---

## 10. The Python API

`ibkr_core_mcp.indicators` — pure functions on an OHLCV DataFrame. **Every `source` defaults to
`close`**, the textbook definition and the behaviour before 2.2.0; the `hl2` default belongs to
the tool.

| Name | Signature | Returns |
|---|---|---|
| `SOURCES` | tuple of the eight names (§2) | — |
| `MA_TYPES` | dict, TradingView's type name → Pine function name (§3) | — |
| `price_source` | `(df, source="close")` | the Series; `ValueError` on a name outside `SOURCES` |
| `moving_average` | `(df, period=20, ma_type="SMA", source="close")` | Series named `{sma\|ema\|rma\|wma\|vwma}_{period}_{source}` — `sma_200_hl2` |
| `sma`, `ema` | `(df, period=20, source="close")` | `moving_average` at that type |
| `bollinger_bands` | `(df, period=20, std=2.0, source="close", ma_type="SMA")` | `bb_upper`, `bb_mid`, `bb_lower` |
| `rsi` | `(df, period=14, source="close")` | Series, 0–100 |
| `macd` | `(df, fast=12, slow=26, signal=9, source="close")` | `macd`, `macd_signal`, `histogram` |

`atr`, `true_range`, `stochastic`, `williams_r`, `keltner_channels`, `vwap`, `obv`,
`volume_sma`, `volume_ratio` and `add_all` are unchanged; `add_all` computes everything at its
fixed defaults on `close`. Variants and seeds: `docs/api-usage-examples.md` § Conventions.

```python
from ibkr_core_mcp import indicators

sma_200 = indicators.sma(df, 200, source="hl2")                      # Series "sma_200_hl2"
bands = indicators.bollinger_bands(df, 200, 2.5, source="hl2")       # basis and deviation both on hl2
wma_50 = indicators.moving_average(df, 50, "WMA", "hlc3")            # Series "wma_50_hlc3"
```

---

## 11. What is not offered

| TradingView setting | Status here |
|---|---|
| MACD "Oscillator MA type", "Signal MA type" (EMA or SMA) | Not offered — all three averages are EMAs, the definition in §6 |
| RSI "Smoothing" section (a moving average of the RSI, with optional bands) and "Calculate Divergence" | Not offered |
| "Timeframe" (compute on another timeframe than the chart's) and "Wait for timeframe closes" | Not offered — an indicator is computed on the cached bars' own size |
| Lengths of RSI, MACD, ATR, Stochastic, Williams %R, Volume Ratio | Fixed at the standard settings in §6–§7 |
| Any indicator not listed in this page | Not computed |
| Exponential Bollinger bands in Bollinger's sense (rule 13: exponential deviation too) | Not offered; `ma_type="EMA"` is TradingView's Basis MA Type (§4) |

---

## 12. Proofs, and what is not established

| Claim | Proof |
|---|---|
| Each of the eight sources is Pine's definition | `test_price_sources_follow_pines_definitions` — one bar whose eight sources are eight different numbers |
| Each of the five types is Pine's definition, and the Series is named for type, length and source | `test_moving_average_types_follow_pines_definitions` — worked by hand on four bars; five different answers, none of them the answer on `close` |
| Basis and deviation share the source; the basis type moves the middle line only | `test_bollinger_bands_take_the_source_for_the_basis_and_the_deviation` |
| RSI and MACD read the source given, and `close` when given none | `test_rsi_and_macd_read_the_source_they_are_given_and_close_when_given_none` |
| The tool computes on the source it names, in TradingView's labels, with every setting stated | `tests/claude_tools/test_market_data.py`, the `add_indicators` tests — figures worked by hand |
| A line never prints `nan`; an out-of-list setting is refused | same file |
| TradingView's three band pairs share one basis and one deviation | Read off the operator's chart legend, 2026-10-05 (ES1! 1h, `BB 200 SMA hl2` at 1, 2 and 2.5): the three pairs are each centred on the `SMA 200 hl2` line's own value, and their half-widths are 1, 2 and 2.5 times one figure |

Each of those tests was held against mutants of the code — a source read as another, a
reversed weighting, a deviation taken on `close`, a default relabelled "as given" — and each
mutant failed one.

**Not established**, as of 2026-10-05:

- **This package's figures against a TradingView chart, on the same bars.** The definitions are
  TradingView's and the arithmetic is tested against them by hand; a line-for-line comparison on
  live bars has not been run.
- **`ma_type` other than SMA on the bands, against a TradingView chart.** The reading in §4 is
  TradingView's help text and Pine's `ta.stdev`; it has not been held against a chart with a
  non-SMA basis.
- **Whether the last bar IBKR returns is one still in progress.** If it is, "last close" is the
  latest price at the time of the fetch, not a completed bar's close.

---

## 13. Every official page

**TradingView** —
[Pine Script v6 reference](https://www.tradingview.com/pine-script-reference/v6/) (`input.source`,
`hl2` `hlc3` `ohlc4` `hlcc4`, `ta.sma` `ta.ema` `ta.rma` `ta.wma` `ta.vwma`, `ta.bb`, `ta.stdev`,
`ta.rsi`, `ta.macd`, `ta.atr`, `plot`) ·
[Bollinger Bands](https://www.tradingview.com/support/solutions/43000501840-bollinger-bands-bb/) ·
[Simple Moving Average](https://www.tradingview.com/support/solutions/43000696841-simple-moving-average/) ·
[Moving-average types (the "Smoothing" section)](https://www.tradingview.com/support/solutions/43000742042/) ·
[RSI](https://www.tradingview.com/support/solutions/43000502338-relative-strength-index-rsi/) ·
[MACD](https://www.tradingview.com/support/solutions/43000502344-moving-average-convergence-divergence-macd-indicator/) ·
[Awesome Oscillator](https://www.tradingview.com/support/solutions/43000501826-awesome-oscillator-ao/)

**John Bollinger** — [Bollinger Band Rules](https://www.bollingerbands.com/bollinger-band-rules)

**StockCharts ChartSchool** —
[Moving Averages](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/moving-averages-simple-and-exponential) ·
[Bollinger Bands](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/bollinger-bands) ·
[Standard Deviation](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/standard-deviation-volatility) ·
[RSI](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/relative-strength-index-rsi) ·
[MACD](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/macd-moving-average-convergence-divergence-oscillator) ·
[ATR](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/average-true-range-atr) ·
[VWAP](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/volume-weighted-average-price-vwap) ·
[Stochastic Oscillator](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/stochastic-oscillator-fast-slow-and-full)
