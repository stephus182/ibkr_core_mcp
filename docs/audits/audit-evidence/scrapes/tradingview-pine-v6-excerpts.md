<!-- source: https://www.tradingview.com/pine-script-reference/v6/ -->
<!-- retrieved 2026-09-16 via firecrawl; full page 1,323,889 B, excerpted here -->

# TradingView Pine Script v6 reference — indicator excerpts

The entries consulted by the 2026-09-16 indicator audit. The full reference is 1.3 MB,
so only the functions that settled a question are kept. The decisive pair is `ta.ema`
and `ta.rma`: their prose descriptions read almost identically, and only the equivalent
Pine source TradingView publishes with them shows that the seeds differ.

### ta.tr

True range, equivalent to `ta.tr(handle_na = false)`. It is calculated as `math.max(high - low, math.abs(high - close[1]), math.abs(low - close[1]))`.

Type

series float

### ta.atr()

Function atr (average true range) returns the RMA of true range. True range is max(high - low, abs(high - close\[1\]), abs(low - close\[1\])).

Syntax

```
ta.atr(length) → series float
```

Arguments

length (simple int) Length (number of bars back).

Example

```
//@version=6
indicator("ta.atr")
plot(ta.atr(14))

//the same on pine
pine_atr(length) =>
    trueRange = na(high[1])? high-low : math.max(math.max(high - low, math.abs(high - close[1])), math.abs(low - close[1]))
    //true range can be also calculated with ta.tr(true)
    ta.rma(trueRange, length)

plot(pine_atr(14))
```

Returns

Average true range.

Remarks

`na` values in the `source` series are ignored; the function calculates on the `length` quantity of non-`na` values.

### ta.bb()

Bollinger Bands. A Bollinger Band is a technical analysis tool defined by a set of lines plotted two standard deviations (positively and negatively) away from a simple moving average (SMA) of the security's price, but can be adjusted to user preferences.

Syntax

```
ta.bb(series, length, mult) → [series float, series float, series float]
```

Arguments

series (series int/float) Series of values to process.

length (series int) Number of bars (length).

mult (simple int/float) Standard deviation factor.

Example

```
//@version=6
indicator("ta.bb")

[middle, upper, lower] = ta.bb(close, 5, 4)
plot(middle, color=color.yellow)
plot(upper, color=color.yellow)
plot(lower, color=color.yellow)

// the same on pine
f_bb(src, length, mult) =>
    float basis = ta.sma(src, length)
    float dev = mult * ta.stdev(src, length)
    [basis, basis + dev, basis - dev]

[pineMiddle, pineUpper, pineLower] = f_bb(close, 5, 4)

plot(pineMiddle)
plot(pineUpper)
plot(pineLower)
```

Returns

Bollinger Bands.

Remarks

`na` values in the `source` series are ignored; the function calculates on the `length` quantity of non-`na` values.

### ta.ema()

The ema function returns the exponentially weighted moving average. In ema weighting factors decrease exponentially. It calculates by using a formula: `EMA = alpha * source + (1 - alpha) * EMA[1]`, where `alpha = 2 / (length + 1)`.

Syntax

```
ta.ema(source, length) → series float
```

Arguments

source (series int/float) Series of values to process.

length (simple int) Number of bars (length).

Example

```
//@version=6
indicator("ta.ema")
plot(ta.ema(close, 15))

//the same on pine
pine_ema(src, length) =>
    alpha = 2 / (length + 1)
    sum = 0.0
    sum := na(sum[1]) ? src : alpha * src + (1 - alpha) * nz(sum[1])
plot(pine_ema(close,15))
```

Returns

Exponential moving average of `source` with alpha = 2 / (length + 1).

Remarks

Please note that using this variable/function can cause [indicator repainting](https://www.tradingview.com/pine-script-docs/concepts/repainting/).

`na` values in the `source` series are ignored; the function calculates on the `length` quantity of non-`na` values.

### ta.kc()

Keltner Channels. Keltner channel is a technical analysis indicator showing a central moving average line plus channel lines at a distance above and below.

Syntax

```
ta.kc(series, length, mult, useTrueRange) → [series float, series float, series float]
```

Arguments

series (series int/float) Series of values to process.

length (simple int) Number of bars (length).

mult (simple int/float) Standard deviation factor.

useTrueRange (simple bool) An optional parameter. Specifies if True Range is used; default is true. If the value is false, the range will be calculated with the expression (high - low).

Example

```
//@version=6
indicator("ta.kc")

[middle, upper, lower] = ta.kc(close, 5, 4)
plot(middle, color=color.yellow)
plot(upper, color=color.yellow)
plot(lower, color=color.yellow)

// the same on pine
f_kc(src, length, mult, useTrueRange) =>
    float basis = ta.ema(src, length)
    float span = (useTrueRange) ? ta.tr : (high - low)
    float rangeEma = ta.ema(span, length)
    [basis, basis + rangeEma * mult, basis - rangeEma * mult]

[pineMiddle, pineUpper, pineLower] = f_kc(close, 5, 4, true)

plot(pineMiddle)
plot(pineUpper)
plot(pineLower)
```

Returns

Keltner Channels.

Remarks

`na` values in the `source` series are ignored; the function calculates on the `length` quantity of non-`na` values.

### ta.rma()

Moving average used in RSI. It is the exponentially weighted moving average with alpha = 1 / length.

Syntax

```
ta.rma(source, length) → series float
```

Arguments

source (series int/float) Series of values to process.

length (simple int) Number of bars (length).

Example

```
//@version=6
indicator("ta.rma")
plot(ta.rma(close, 15))

//the same on pine
pine_rma(src, length) =>
    alpha = 1/length
    sum = 0.0
    sum := na(sum[1]) ? ta.sma(src, length) : alpha * src + (1 - alpha) * nz(sum[1])
plot(pine_rma(close, 15))
```

Returns

Exponential moving average of `source` with alpha = 1 / `length`.

Remarks

`na` values in the `source` series are ignored; the function calculates on the `length` quantity of non-`na` values.

### ta.rsi()

Relative strength index. It is calculated using the `ta.rma()` of upward and downward changes of `source` over the last `length` bars.

Syntax

```
ta.rsi(source, length) → series float
```

Arguments

source (series int/float) Series of values to process.

length (simple int) Number of bars (length).

Example

```
//@version=6
indicator("ta.rsi")
plot(ta.rsi(close, 7))

// same on pine, but less efficient
pine_rsi(x, y) =>
    u = math.max(x - x[1], 0) // upward ta.change
    d = math.max(x[1] - x, 0) // downward ta.change
    rs = ta.rma(u, y) / ta.rma(d, y)
    res = 100 - 100 / (1 + rs)
    res

plot(pine_rsi(close, 7))
```

Returns

Relative strength index.

Remarks

`na` values in the `source` series are ignored; the function calculates on the `length` quantity of non-`na` values.

### ta.sma()

The sma function returns the moving average, that is the sum of last y values of x, divided by y.

Syntax

```
ta.sma(source, length) → series float
```

Arguments

source (series int/float) Series of values to process.

length (series int) Number of bars (length).

Example

```
//@version=6
indicator("ta.sma")
plot(ta.sma(close, 15))

// same on pine, but much less efficient
pine_sma(x, y) =>
    sum = 0.0
    for i = 0 to y - 1
        sum := sum + x[i] / y
    sum
plot(pine_sma(close, 15))
```

Returns

Simple moving average of `source` for `length` bars back.

Remarks

`na` values in the `source` series are ignored.

### ta.stdev()

Syntax

```
ta.stdev(source, length, biased) → series float
```

Arguments

source (series int/float) Series of values to process.

length (series int) Number of bars (length).

biased (series bool) Determines which estimate should be used. Optional. The default is true.

Example

```
//@version=6
indicator("ta.stdev")
plot(ta.stdev(close, 5))

//the same on pine
isZero(val, eps) => math.abs(val) <= eps

SUM(fst, snd) =>
    EPS = 1e-10
    res = fst + snd
    if isZero(res, EPS)
        res := 0
    else
        if not isZero(res, 1e-4)
            res := res
        else
            15

pine_stdev(src, length) =>
    avg = ta.sma(src, length)
    sumOfSquareDeviations = 0.0
    for i = 0 to length - 1
        sum = SUM(src[i], -avg)
        sumOfSquareDeviations := sumOfSquareDeviations + sum * sum

    stdev = math.sqrt(sumOfSquareDeviations / length)
plot(pine_stdev(close, 5))
```

Returns

Standard deviation.

Remarks

If `biased` is true, function will calculate using a biased estimate of the entire population, if false - unbiased estimate of a sample.

`na` values in the `source` series are ignored; the function calculates on the `length` quantity of non-`na` values.

### ta.stoch()

Stochastic. It is calculated by a formula: 100 \* (close - lowest(low, length)) / (highest(high, length) - lowest(low, length)).

Syntax

```
ta.stoch(source, high, low, length) → series float
```

Arguments

source (series int/float) Source series.

high (series int/float) Series of high.

low (series int/float) Series of low.

length (series int) Length (number of bars back).

Returns

Stochastic.

Remarks

`na` values in the `source` series are ignored.

### ta.tr()

Calculates the current bar's true range. Unlike a bar's actual range (`high - low`), true range accounts for potential gaps by taking the maximum of the current bar's actual range and the absolute distances from the previous bar's [close](https://www.tradingview.com/pine-script-reference/v6/#var_close) to the current bar's [high](https://www.tradingview.com/pine-script-reference/v6/#var_high) and [low](https://www.tradingview.com/pine-script-reference/v6/#var_low). The formula is: `math.max(high - low, math.abs(high - close[1]), math.abs(low - close[1]))`.

Syntax

```
ta.tr(handle_na) → series float
```

Arguments

handle\_na (simple bool) Defines how the function calculates the result when the previous bar's [close](https://www.tradingview.com/pine-script-reference/v6/#var_close) is [na](https://www.tradingview.com/pine-script-reference/v6/#var_na). If [true](https://www.tradingview.com/pine-script-reference/v6/#const_true), the function returns the bar's `high - low` value. If [false](https://www.tradingview.com/pine-script-reference/v6/#const_false), it returns [na](https://www.tradingview.com/pine-script-reference/v6/#var_na).

Returns

True range. It is math.max(high - low, math.abs(high - close\[1\]), math.abs(low - close\[1\])).

Remarks

ta.tr(false) is exactly the same as [ta.tr](https://www.tradingview.com/pine-script-reference/v6/#var_ta.tr).

### ta.wpr()

Williams %R. The oscillator shows the current closing price in relation to the high and low of the past 'length' bars.

Syntax

```
ta.wpr(length) → series float
```

Arguments

length (series int) Number of bars.

Example

```
//@version=6
indicator("Williams %R", shorttitle="%R", format=format.price, precision=2)
plot(ta.wpr(14), title="%R", color=color.new(#ff6d00, 0))
```

Returns

Williams %R.

Remarks

`na` values in the `source` series are ignored.

