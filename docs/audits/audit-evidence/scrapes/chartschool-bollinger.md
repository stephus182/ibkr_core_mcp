<!-- source: https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/bollinger-bands -->

For the complete documentation index, see [llms.txt](https://chartschool.stockcharts.com/llms.txt). This page is also available as [Markdown](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/bollinger-bands.md).

## What Are Bollinger Bands?[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/bollinger-bands\#what_are_bollinger_bands)

Developed by John Bollinger, Bollinger Bands® are volatility bands placed above and below a moving average. Volatility is based on the standard deviation, which changes as volatility increases and decreases. The bands automatically widen when volatility increases and contract when volatility decreases. Their dynamic nature allows them to be used on different securities with the standard settings.

[Click here for a live version of this chart.](https://stockcharts.com/sc3/ui/?s=MSFT&p=D&b=5&g=0&id=p81912915738&a=952666096)

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FBZnCeZSQBBU7K7XPvfRc%252Fbb-intro.png%3Falt%3Dmedia%26token%3Def86842a-cbc4-408c-a558-6764160afec3&width=768&dpr=3&quality=100&sign=ef342037daf4249d8fbed7eedd3908e5&sv=3)

So, how do you use Bollinger Bands effectively? They can be used to confirm M-Tops and W-Bottoms or to determine the trend's strength. Signals based on the distance between the upper and lower band, including the popular Bollinger Band Squeeze, are identified using the related Bollinger BandWidth indicator.

**Learn More:** [Bollinger Band Squeeze](https://chartschool.stockcharts.com/table-of-contents/trading-strategies-and-models/trading-strategies/bollinger-band-squeeze) \| [Bollinger BandWidth](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/bollinger-bandwidth)

**Note:** Bollinger Bands® is a registered trademark of John Bollinger.

* * *

## Bollinger Bands Calculation[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/bollinger-bands\#how_to_calculate_bollinger_bands)

### Formulas[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/bollinger-bands\#formulas)

Copy

```
  * Middle Band = 20-day simple moving average (SMA)
  * Upper Band = 20-day SMA + (20-day standard deviation of price x 2)
  * Lower Band = 20-day SMA - (20-day standard deviation of price x 2)
```

**Bollinger Bands consist of a middle band with two outer bands.** The middle band is a simple moving average that is usually set at 20 periods. A simple moving average is used because the standard deviation formula also uses a simple moving average. The look-back period for the standard deviation is the same as for the simple moving average. The outer bands are usually set 2 standard deviations above and below the middle band.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FUiTE2mNKIDdItNZvAW7k%252Fbbs-1-spyexam.png%3Falt%3Dmedia%26token%3Df2c238cb-a278-4595-bf04-53ab5f332723&width=768&dpr=3&quality=100&sign=248acfe62583c8e5375f62161b447407&sv=3)

Chart 1

This spreadsheet below shows the calculations for the Bollinger Bands in the SPY chart above.

Click below to download this spreadsheet example.

[cs-bbands.xls](https://436553459-files.gitbook.io/~/files/v0/b/gitbook-x-prod.appspot.com/o/spaces%2FERtrZrZOhufFzk6ZQO4B%2Fuploads%2FanKvdQj5hf23LTtoC3Ws%2Fcs-bbands.xls?alt=media&token=bbeff0b1-b5f7-4013-adb6-6f0770d77ab6)

33KB

Download [Open](https://436553459-files.gitbook.io/~/files/v0/b/gitbook-x-prod.appspot.com/o/spaces%2FERtrZrZOhufFzk6ZQO4B%2Fuploads%2FanKvdQj5hf23LTtoC3Ws%2Fcs-bbands.xls?alt=media&token=bbeff0b1-b5f7-4013-adb6-6f0770d77ab6)

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252Fc9Qjg6fJ1CMHXZHCnk0F%252Fbbs-1-sprdsheet.png%3Falt%3Dmedia%26token%3Dc428e549-b840-4e6b-b0dc-e96161921e81&width=768&dpr=3&quality=100&sign=59e5087c202539921379a10c68e4e014&sv=3)

**Learn More:** [Moving Averages](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/moving-averages-simple-and-exponential) \| [Standard Deviation](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/standard-deviation-volatility)

### Adjusting Bollinger Band Settings[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/bollinger-bands\#adjusting_bollinger_band_settings)

Settings can be adjusted to suit the characteristics of particular securities or trading styles. Bollinger recommends making small incremental adjustments to the standard deviation multiplier. Changing the number of periods for the moving average also affects the number of periods used to calculate the standard deviation. Therefore, only small adjustments are required for the standard deviation **multiplier**. An increase in the moving average period would automatically increase the number of periods used to calculate the standard deviation and would also warrant an increase in the standard deviation **multiplier**. With a 20-day SMA and 20-day standard deviation, the standard deviation multiplier is set at 2. Bollinger suggests increasing the standard deviation multiplier to 2.1 for a 50-period SMA and decreasing the standard deviation multiplier to 1.9 for a 10-period SMA.

## Interpreting Bollinger Bands[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/bollinger-bands\#what_do_bollinger_bands_tell_us)

Bollinger Bands are often used to help confirm trend reversals. M-Tops and W-Bottoms are chart patterns that can indicate a trend reversal; the chart pattern's position relative to the Bollinger Bands helps confirm the chart pattern.

The strength of the trend can also be determined by how closely prices follow the upper Bollinger Band in a strong uptrend, or the lower Bollinger Band in a strong downtrend. This is often referred to as "walking the bands".

### Confirming W-Bottom Chart Patterns[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/bollinger-bands\#signalw-bottoms)

W-Bottoms were part of Arthur Merrill's work that identified 16 patterns with a basic W shape. Bollinger uses these various W patterns with Bollinger Bands to identify W-Bottoms, which form in a downtrends and contain two reaction lows. In particular, Bollinger looks for W-Bottoms where the second low is lower than the first but holds above the lower band. There are four steps to confirm a W-Bottom with Bollinger Bands. First, a reaction low forms. This low is usually, but not always, below the lower band. Second, there is a bounce towards the middle band. Third, there is a new price low in the security. This low holds **above** the lower band. The ability to hold above the lower band on the test shows less weakness on the last decline. Fourth, the pattern is confirmed with a strong move off the second low and a resistance break.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FJPCjD7v1YEXarURufxNY%252Fbbs-2-jwnwbot.png%3Falt%3Dmedia%26token%3D9cc1eef8-5136-4c97-b717-3a6ad2e545b3&width=768&dpr=3&quality=100&sign=1f81f1587b866ae1900e5aaa6666ff0c&sv=3)

Chart 2

Chart 2 shows Nordstrom (JWN) with a W-Bottom in January-February 2010. First, the stock formed a reaction low in January (black arrow) and broke below the lower band. Second, there was a bounce back above the middle band. Third, the stock moved below its January low and held above the lower band. Even though the 5-Feb spike low broke the lower band, the signal is not affected since, like Bollinger Bands, it is calculated using closing prices. Fourth, the stock surged with expanding volume in late February and broke above the early February high.

Chart 3 shows Sandisk with a smaller W-Bottom in July-August 2009.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FdnSeQseJstPlj65zVFZe%252Fbbs-3-sndkwbot.png%3Falt%3Dmedia%26token%3Db56d6325-8bd5-4df6-a1b1-7ce6f5b37db0&width=768&dpr=3&quality=100&sign=e339f6114cc6b39bec3b2a4735b6f4bc&sv=3)

Chart 3

### Confirming M-Top Chart Patterns[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/bollinger-bands\#signalm-tops)

M-Tops were also part of Arthur Merrill's work that identified 16 patterns with a basic M shape. Bollinger uses these various M patterns with Bollinger Bands to identify M-Tops, which are essentially the opposite of W-Bottoms. According to Bollinger, tops are usually more complicated and drawn out than bottoms. Double tops, head-and-shoulders patterns, and diamonds represent evolving tops.

In its most basic form, an M-Top is similar to a double top. However, the reaction highs are not always equal; the first high can be higher or lower than the second high. Bollinger suggests looking for signs of non-confirmation when a security is making new highs. A non-confirmation occurs with three steps. First, a security creates a reaction high above the upper band. Second, there is a pullback towards the middle band. Third, prices move above the prior high but fail to reach the upper band. This is a warning sign. The inability of the second reaction high to reach the upper band shows waning momentum, which can foreshadow a trend reversal. Final confirmation comes with a support break or bearish indicator signal.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252Fn8ahD7Ar613AetIru1U0%252Fbbs-4-xommtop.png%3Falt%3Dmedia%26token%3D45505439-ead9-41a6-a4c4-6fa6dfd0a3b6&width=768&dpr=3&quality=100&sign=8a3ed897cbd0eab914d4e215b1d8ae17&sv=3)

Chart 4

Chart 4 shows Exxon Mobil (XOM) with an M-Top in April-May 2008. The stock moved above the upper band in April, followed by a pullback in May and another push above 90. Even though the stock moved above the upper band on an intraday basis, it did not CLOSE above the upper band. The M-Top was confirmed with a support break two weeks later. Additionally, the MACD formed a bearish divergence and moved below its signal line for confirmation.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FN5uWNvDsFS4DB5H7wNEY%252Fbbs-5-phmmtop-1.png%3Falt%3Dmedia%26token%3D509c1973-3359-464e-adb1-947f053ab1df&width=768&dpr=3&quality=100&sign=4882d6dd8a84b3d14f64237e7ec30421&sv=3)

Chart 5

Chart 5 shows Pulte Homes (PHM) within an uptrend in July-August 2008. Price exceeded the upper band in early September to affirm the uptrend. After a pullback below the 20-day SMA (middle Bollinger Band), the stock moved to a higher high above 17. Despite this new high for the move, price did not exceed the upper band, which was a warning sign. The stock broke support a week later and MACD moved below its signal line. Notice that this M-top is more complex because there are lower reaction highs on either side of the peak (blue arrow). This evolving top formed a small head-and-shoulders pattern.

### Measuring Trend Strength: Walking the Bands[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/bollinger-bands\#signalwalking_the_bands)

Moves above or below the bands are not signals per se. As Bollinger puts it, moves that touch or exceed the bands are not signals, but rather “tags”. On the face of it, a move to the upper band shows strength, while a sharp move to the lower band shows weakness. Momentum oscillators work much the same way. Overbought is not necessarily bullish. It takes strength to reach overbought levels and overbought conditions can extend in a strong uptrend. Similarly, prices can “walk the band” with numerous touches during a strong uptrend. Think about it for a moment. The upper band is 2 standard deviations above the 20-period simple moving average. It takes a pretty strong price move to exceed this upper band. An upper band touch that occurs after a Bollinger Band confirmed W-Bottom would signal the start of an uptrend. Just as a strong uptrend produces numerous upper band tags, it is also common for prices to never reach the lower band during an uptrend. The 20-day SMA sometimes acts as support. In fact, dips below the 20-day SMA sometimes provide buying opportunities before the next tag of the upper band.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FZXO5iTpnlSIS9X9Yo3kY%252Fbbs-6-apdwalk.png%3Falt%3Dmedia%26token%3Ddbb41393-b7d0-4df1-93e9-199e116f978b&width=768&dpr=3&quality=100&sign=222372f429e872cf5999ee76ee3c1fb8&sv=3)

Chart 6

Chart 6 shows Air Products (APD) with a surge and close above the upper band in mid-July. First, notice that this is a strong surge that broke above two resistance levels. A strong upward thrust is a sign of strength, not weakness. Trading turned flat in August and the 20-day SMA moved sideways. The Bollinger Bands narrowed, but APD did not close below the lower band. Prices and the 20-day SMA turned up in September. Overall, APD closed above the upper band at least five times over a four-month period. The indicator window shows the 10-period Commodity Channel Index (CCI). Dips below -100 are deemed oversold and moves back above -100 signal the start of an oversold bounce (green dotted line). The upper band tag and breakout started the uptrend. CCI then identified tradable pullbacks with dips below -100. This is an example of combining Bollinger Bands with a momentum oscillator for trading signals.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FtKRKHSMfKpQepYQ9nFrH%252Fbbs-7-monwalk.png%3Falt%3Dmedia%26token%3De138b498-f53a-4bbb-837b-a58c40cbd34a&width=768&dpr=3&quality=100&sign=f639dc60280e3ef89b1e098354b8be26&sv=3)

Chart 7

Chart 7 shows Monsanto (MON) with a walk down the lower band. The stock broke down in January with a support break and closed below the lower band. From mid-January until early May, Monsanto closed below the lower band at least five times. Notice that the stock did not close above the upper band once during this period. The support break and initial close below the lower band signaled a downtrend. As such, the 10-period Commodity Channel Index (CCI) was used to identify short-term overbought situations. A move above +100 is overbought. A move back below +100 signals a resumption of the downtrend (red arrows). This system triggered two good signals in early 2010.

## The Bottom Line[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/bollinger-bands\#final_thoughts)

Bollinger Bands reflect direction with the 20-period SMA and volatility with the upper/lower bands. As such, they can determine if prices are relatively high or low. **According to Bollinger, the bands should contain 88-89% of price action, which makes a move outside the bands significant.** Technically, prices are relatively high when they're above the upper band and relatively low when below the lower band. However, “relatively high” should not be regarded as bearish or a sell signal. Likewise, “relatively low” should not be considered bullish or a buy signal. Prices are high or low for a reason. As with other indicators, Bollinger Bands are not meant to be used as a stand-alone tool. Chartists should combine Bollinger Bands with basic trend analysis and other indicators for confirmation.

* * *

## Charting with Bollinger Bands[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/bollinger-bands\#charting_with_bollinger_bands)

The Bollinger Bands overlay can be added to SharpCharts, ACP Charts, and P&F Charts.

### Using with SharpCharts[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/bollinger-bands\#using_with_sharpcharts)

[Click here for a live version of this chart.](https://stockcharts.com/sc3/ui/?s=F&p=D&b=5&g=0&id=p49007926451&a=952729897)

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FMWDs85OxWuhHhAZrE63N%252Fbb-shch.png%3Falt%3Dmedia%26token%3D0210528a-ce67-458e-97db-2e9111a84e28&width=768&dpr=3&quality=100&sign=8b5bf41c390dd0e159292a2a6ac4afaa&sv=3)

Chart 8

Bollinger Bands can be found in SharpCharts as a price overlay. As with a simple moving average, Bollinger Bands should be shown on top of a price plot. Upon selecting Bollinger Bands, the default setting will appear in the parameters window (20,2). The first number (20) sets the periods for the simple moving average and the standard deviation. The second number (2) sets the standard deviation multiplier for the upper and lower bands. These default parameters set the bands 2 standard deviations above/below the simple moving average. Users can change the parameters to suit their charting needs. A Bollinger Band overlay can be set at (50,2.1) for a longer timeframe or at (10,1.9) for a shorter timeframe.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FVSULucWjk01IdWHxmSWy%252Fbbs-9-shch.png%3Falt%3Dmedia%26token%3D986aec63-e861-4767-8c12-5ffb8056e702&width=768&dpr=3&quality=100&sign=b3089da34adc758fc66c87126119e542&sv=3)

**Learn More:** For more details on the parameters used to configure Bollinger Bands overlays, please see our [SharpCharts Parameter Reference](https://help.stockcharts.com/charts-and-tools/sharpcharts/sharpcharts-workbench/editing-sharpcharts/sharpcharts-parameter-reference#bollinger_bands-1) in the Support Center.

### Using With StockChartsACP[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/bollinger-bands\#using_with_stockchartsacp)

This overlay can be added from the Chart Settings panel for your StockChartsACP chart. Bollinger Bands can be overlaid on the security's price plot or on an indicator panel.
[Click here for a live version of this chart.](https://schrts.co/AXNcfZkD)

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FOIVBY9hgAI3rA5x4jSL2%252Fbb-acp.png%3Falt%3Dmedia%26token%3D0a01cd16-027b-4b1e-85ec-e49dd7e3feb6&width=768&dpr=3&quality=100&sign=c8687dd99bfd255a4c1bbfeab28e7f2d&sv=3)

Chart 9

By default, the overlay uses a 20-period SMA and sets the bands 2.0 standard deviations above or below the SMA. These parameters can be adjusted to meet your technical analysis needs.

### Using With P&F Charts[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/bollinger-bands\#using_with_p_f_charts)

Bollinger Bands can also be overlaid on P&F charts. This overlay can be found in the Overlays section on the P&F Workbench.

[Click here for a live version of this chart.](https://stockcharts.com/freecharts/pnf.php?c=IBM,PWTADANRNO[PE20,2][D][F1!3!!!2!20]&dt=202105122038)

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FPieeJdR7kAZ9KQZR4ZBI%252Fbb-pnf.png%3Falt%3Dmedia%26token%3D96eb9077-c142-4f36-ad01-003986e814de&width=768&dpr=3&quality=100&sign=63a62aae56619f62bd59bc94ac208bf6&sv=3)

Chart 10

By default, a 20-period SMA and 2 standard deviations are used to calculate the Bollinger Bands. However, since P&F moving averages are double smoothed, it may be necessary to shorten the moving average period when placing this overlay on a P&F chart.

**Learn More:** [Bollinger Bands on P&F Charts](https://chartschool.stockcharts.com/table-of-contents/chart-analysis/point-and-figure-charts/point-and-figure-indicators#bollinger_bands)

* * *

## Scanning for Bollinger Bands[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/bollinger-bands\#scanning_for_bollinger_bands)

StockCharts members can search for stocks based on Bollinger Band values. Below are some example scans that can be used for Bollinger Bands-based signals. Simply copy the scan text and paste it into the Scan Criteria box in the [Advanced Scan Workbench](https://help.stockcharts.com/scanning-and-alerts/technical-scans/advanced-scan-workbench).

Members can also set up alerts to notify them when a Bollinger Bands-based signal is triggered for a stock. Alerts use the same syntax as scans, so the sample scans below can be used as a starting point for setting up alerts as well. Simply copy the scan text and paste it into the Alert Criteria box in the [Technical Alert Workbench](https://help.stockcharts.com/scanning-and-alerts/technical-alerts/technical-alert-workbench).

### Bullish Bollinger Band Crossover[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/bollinger-bands\#bullish_bollinger_band_crossover)

This scan finds stocks that have just moved above their upper Bollinger Band line. This scan is just a starting point. Further refinement and analysis are required.

Copy

```
[type = stock] AND [country = US]
AND [Daily SMA(20,Daily Volume) > 40000]
AND [Daily SMA(60,Daily Close) > 5]

AND [Daily Close x Daily Upper BB(20,2.0)]
```

### Bearish Bollinger Band Crossover[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/bollinger-bands\#bearish_bollinger_band_crossover)

This scan finds stocks that have just moved below their lower Bollinger Band line. This scan is just a starting point. Further refinement and analysis are required.

Copy

```
[type = stock] AND [country = US]
AND [Daily SMA(20,Daily Volume) > 40000]
AND [Daily SMA(60,Daily Close) > 5]

AND [Daily Lower BB(20,2.0) x Daily Close]
```

**Learn More:** For more details on the syntax to use for Bollinger Band scans, please see our [Scanning Indicator Reference](https://help.stockcharts.com/scanning-and-alerts/scan-writing-resource-center/scan-syntax-reference/scan-syntax-technical-indicators#bollinger_bands) in the Support Center.

* * *

[PreviousAnchored VWAP](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/anchored-vwap) [NextChandelier Exit](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/chandelier-exit)

Last updated 21 minutes ago

Was this helpful?

This site uses cookies to deliver its service and to analyze traffic. By browsing this site, you accept the [privacy policy](https://help.stockcharts.com/learning-more/policies-and-limitations/privacy-statement).

AcceptReject