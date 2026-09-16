<!-- source: https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/relative-strength-index-rsi -->

For the complete documentation index, see [llms.txt](https://chartschool.stockcharts.com/llms.txt). This page is also available as [Markdown](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/relative-strength-index-rsi.md).

## What Is the Relative Strength Index (RSI)?[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/relative-strength-index-rsi\#what_is_the_relative_strength_index_rsi)

The RSI, a momentum oscillator developed by J. Welles Wilder, measures the speed and change of price movements. The RSI moves up and down (oscillates) between zero and 100. When the RSI is above 70, it generally indicates overbought conditions; when the RSI is below 30, it indicates oversold conditions. The RSI also generates trading signals via divergences, failure swings, and centerline crossovers. You could also use the RSI to identify the general trend.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252Fuo9uuB0iU2QpKIy60TEg%252Frsiexample.png%3Falt%3Dmedia%26token%3D88f53766-7f54-479f-9aff-7565bb7ac89c&width=768&dpr=3&quality=100&sign=b7e9437953da638bb9360feb30462ad0&sv=3)

RSI is a popular [momentum indicator](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/introduction-to-technical-indicators-and-oscillators#momentum_oscillators) that has been featured in a number of articles, interviews, and books over the years. In particular, Constance Brown's book, _Technical Analysis for the Trading Professional_, features the concept of bull and bear market ranges for RSI. Andrew Cardwell, Brown's RSI mentor, introduced positive and negative reversals for RSI and turned the notion of divergence, literally and figuratively, on its head.

Wilder features RSI in his 1978 book, _New Concepts in Technical Trading Systems_. This book also includes the Parabolic SAR, Average True Range, and the Directional Movement Concept (ADX). Despite being developed before the computer age, Wilder's indicators have stood the test of time and continue to be applied by chart analysts.

* * *

## RSI Calculation[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/relative-strength-index-rsi\#calculating_the_rsi)

There are three basic components in the RSI— **RS**, **Average Gain**, and **Average Loss**. This RSI calculation is based on 14 periods, the default Wilder suggested in his book. Losses are expressed as positive values, not negative values.

Copy

```
                  100
    RSI = 100 - --------
                 1 + RS

    RS = Average Gain / Average Loss
```

The first calculations for average gain and average loss are simple 14-period averages:

- First Average Gain = Sum of Gains over the past 14 periods / 14.

- First Average Loss = Sum of Losses over the past 14 periods / 14.


The second and subsequent, calculations are based on the prior averages and the current gain loss:

- Average Gain = \[(previous Average Gain) x 13 + current Gain\] / 14.

- Average Loss = \[(previous Average Loss) x 13 + current Loss\] / 14.


Taking the prior value plus the current value is a smoothing technique similar to calculating an exponential moving average. This also means RSI values become more accurate as the calculation period extends. SharpCharts uses at least 250 data points before the starting date of any chart (assuming that much data exists) when calculating its RSI values. A formula will need at least 250 data points to replicate our RSI numbers.

Wilder's formula normalizes RS and turns it into an oscillator that fluctuates between zero and 100. The normalization step makes it easier to identify extremes because RSI is range-bound. When the Average Gain equals zero, RSI is zero. So, if you're using a 14-period RSI, a zero RSI value means prices moved lower in all 14 periods. There were no gains to measure. RSI is 100 when the Average Loss equals zero. This means prices moved higher in all 14 periods, and there were no losses to measure.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FhJHOoktXiwlYvmWsCFas%252Frsi-2-rsplot.png%3Falt%3Dmedia%26token%3Dd05cbab0-9d89-4b50-a0f5-76ab8e4e7141&width=768&dpr=3&quality=100&sign=5117ccd2a59b9b531487741904ed5773&sv=3)

RS vs. RSI Plots

Below is an Excel spreadsheet that shows the start of an RSI calculation.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252Fl2hpHn0cEC6JejEAv7JF%252Frsi-1-rsiexcel.png%3Falt%3Dmedia%26token%3Ded4bd561-15f3-4699-9b02-0c2e012d9fac&width=768&dpr=3&quality=100&sign=0f11b1605ee7c6d37c6bde4999636d30&sv=3)

RSI Calculation Example

Click below to download the spreadsheet.

[cs-rsi.xls](https://436553459-files.gitbook.io/~/files/v0/b/gitbook-x-prod.appspot.com/o/spaces%2FERtrZrZOhufFzk6ZQO4B%2Fuploads%2FcFVjzTtdAgH6y4RZl8kQ%2Fcs-rsi.xls?alt=media&token=42de84ef-276f-4f67-9cb0-47f0c935910d)

28KB

Download [Open](https://436553459-files.gitbook.io/~/files/v0/b/gitbook-x-prod.appspot.com/o/spaces%2FERtrZrZOhufFzk6ZQO4B%2Fuploads%2FcFVjzTtdAgH6y4RZl8kQ%2Fcs-rsi.xls?alt=media&token=42de84ef-276f-4f67-9cb0-47f0c935910d)

**Note:** The smoothing process affects RSI values. RS values are smoothed after the first calculation. Average Loss equals the sum of the losses divided by 14 for the first calculation. Subsequent calculations multiply the prior value by 13, add the most recent value, and divide the total by 14. This creates a smoothing effect. The same applies to Average Gain. Because of this smoothing, RSI values may differ based on the total calculation period. 250 periods will allow for more smoothing than 30 periods, which will slightly affect RSI values. StockCharts.com goes back 250 days whenever possible. If the Average Loss equals zero, a “divide by zero” situation occurs for RS, and RSI is set to 100 by definition. Similarly, RSI equals 0 when Average Gain equals zero.

### Adjusting RSI Parameters[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/relative-strength-index-rsi\#what_are_the_best_rsi_parameters)

The default look-back period for RSI is 14, but you can lower it to increase sensitivity or raise it to decrease sensitivity. A 10-day RSI is more likely to reach overbought or oversold levels than a 20-day RSI. The look-back parameters also depend on a security's volatility. The 14-day RSI for a volatile stock such as Amazon (AMZN) is more likely to become overbought or oversold than a 14-day RSI for a utility company such as Duke Energy (DUK).

The traditional overbought and oversold levels can be adjusted to better fit the security or analytical requirements. Raising the overbought threshold to 80 or lowering the oversold threshold to 20 could reduce the number of overbought/oversold readings. Short-term traders sometimes use 2-period RSI to look for overbought readings above 80 and oversold readings below 20.

**Cool Tip:** While many of the examples in this article use daily charts, the RSI can be added to many timeframes - daily, weekly, hourly, and minute charts. The best timeframe to use depends on your trading strategy and goals.

* * *

## Interpreting RSI[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/relative-strength-index-rsi\#overbought_and_oversold_rsi_levels)

### Overbought and Oversold RSI Levels[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/relative-strength-index-rsi\#overbought_and_oversold_rsi_levels-1)

Wilder considered RSI [overbought](https://chartschool.stockcharts.com/table-of-contents/glossary/glossary-o#overbought) above 70 and [oversold](https://chartschool.stockcharts.com/table-of-contents/glossary/glossary-o#oversold) below 30. The chart below shows McDonalds with a 14-day RSI. This chart features daily bars in gray with a one-day SMA in pink to highlight closing prices (as RSI is based on closing prices). Working from left to right, the stock became oversold in late July and found support around 44 (1).

Notice that the bottom **evolved** after the oversold reading. Bottoming can be a process—this stock did not bottom as soon as the oversold reading appeared. From oversold levels, RSI moved above 70 in mid-September to become overbought. Despite this overbought reading, the stock did not decline; instead, it stalled for a couple weeks and then continued higher.

Three more overbought readings occurred before the stock finally peaked in December (2). Momentum oscillators can become overbought (oversold) and remain so in a strong up (down) trend. The first three overbought readings foreshadowed consolidations. The fourth coincided with a significant peak. RSI then moved from overbought to oversold in January. The stock ultimately bottomed around 46 a few weeks later (3); the final bottom did not coincide with the initial oversold reading.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252Fn5x98LPiBZZJxadGh0Pg%252Frsi-3-mcdobos.png%3Falt%3Dmedia%26token%3Dd02be850-704c-4e67-b9c3-573d06f8558b&width=768&dpr=3&quality=100&sign=c5632cfe251c0d6e49f44ff4550cd289&sv=3)

Overbought and Oversold RSI

Like many momentum oscillators, **overbought and oversold readings for RSI work best when prices move sideways within a range**. The chart below shows MEMC Electronics (WFR) trading between 13.5 and 21 from April to September 2009. The stock peaked soon after RSI reached 70 and bottomed soon after the stock reached 30.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FSe9oWonkc2XNkkQsSKRs%252Frsi-4-wfrobos.png%3Falt%3Dmedia%26token%3D9db98ccc-8072-4b4c-a947-f343af6ef332&width=768&dpr=3&quality=100&sign=2004217d1b8c232564cab5f7be45736a&sv=3)

Overbought/Oversold RSI in a Trading Range

* * *

### Bullish and Bearish Divergences in RSI[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/relative-strength-index-rsi\#bullish_and_bearish_divergences_in_rsi)

According to Wilder, divergences signal a potential reversal point because directional momentum does not confirm price. A bullish divergence occurs when the underlying security makes a lower low, and RSI forms a higher low. RSI does not confirm the lower low, and this shows strengthening momentum. A bearish divergence forms when the security records a higher high and RSI forms a lower high. RSI does not confirm the new high and this shows weakening momentum.

The chart below shows Ebay (EBAY) with a bearish divergence in August–October. The stock moved to new highs in September–October, but RSI formed lower highs for the bearish divergence. The subsequent breakdown in mid-October confirmed weakening momentum.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FcQFIpdwswJcxqt354GHZ%252Frsi-5-ebaydiverg.png%3Falt%3Dmedia%26token%3De09b1a38-f399-4787-93bb-1397a82d0299&width=768&dpr=3&quality=100&sign=04bd165b862d77e98dc5e4c0873d5a94&sv=3)

RSI Divergences

A bullish divergence formed in January–March. The bullish divergence formed with eBay moving to new lows in March and RSI holding above its prior low. RSI reflected less downside momentum during the February-March decline. The mid-March breakout confirmed improving momentum. Divergences tend to be more robust when they form after an overbought or oversold reading.

Before getting too excited about divergences as great trading signals, it must be noted that divergences are misleading in a strong trend. A strong uptrend can show numerous bearish divergences before a top materializes.

Conversely, bullish divergences can appear in a strong downtrend, yet the downtrend continues. The chart below shows the SPDR S&P 500 ETF (SPY) with three bearish divergences and a continuing uptrend. These bearish divergences may have warned of a short-term pullback, but there was clearly no major trend reversal.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252Fzg3Dldc2OKW2vD2JWRjK%252Frsi-6-spydiverg.png%3Falt%3Dmedia%26token%3D072bb1b3-387b-4cfd-864a-2c589a3baf8a&width=768&dpr=3&quality=100&sign=abe57e7cf3f8eb5d49169394fcc0691e&sv=3)

RSI Divergences in a strong trend

* * *

### RSI Failure Swings[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/relative-strength-index-rsi\#rsi_failure_swings)

Wilder also considered failure swings as strong indications of an impending reversal. Failure swings are independent of price action, focusing solely on RSI for signals and ignoring the concept of divergences. A bullish failure swing forms when RSI moves below 30 (oversold), bounces above 30, pulls back, holds above 30 and then breaks its prior high. It is basically a move to oversold levels and then a higher low above oversold levels. The chart below shows Research in Motion (RIMM) with 10-day RSI forming a bullish failure swing.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FKHxCmg80baJH1MeENKt7%252Frsi-7-rimmbfs.png%3Falt%3Dmedia%26token%3D52581013-4598-4a86-bf48-2f05dbca696f&width=768&dpr=3&quality=100&sign=6325cf1bb45b926663a51b7e12204bb0&sv=3)

Bullish RSI Failure Swing

A bearish failure swing forms when RSI moves above 70, pulls back, bounces, fails to exceed 70, and then breaks its prior low. It is a move to overbought levels, followed by a lower high beneath those levels. The chart below shows Texas Instruments (TXN) with a bearish failure swing in May–June 2008.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FESpwSOcfNV79fqUofZdj%252Frsi-8-txnbfs.png%3Falt%3Dmedia%26token%3Dcfa1803b-02d9-414f-8def-9818dd51ce44&width=768&dpr=3&quality=100&sign=a00242d178948b6e9c9f4f1b4fa26b29&sv=3)

Bearish RSI Failure Swing

* * *

### Using RSI To Identify Trends[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/relative-strength-index-rsi\#how_to_use_rsi_to_identify_trends)

In _Technical Analysis for the Trading Professional_, Constance Brown suggests that oscillators do not travel between 0 and 100. This also happens to be the name of the first chapter. Brown identifies a bull market range and a bear market for RSI. RSI tends to fluctuate between 40 and 90 in a bull market (uptrend) with the 40–50 zones acting as support. These ranges may vary depending on RSI parameters, strength of trend and volatility of the underlying security.

The chart below shows 14-week RSI for SPY during the bull market from 2003 until 2007. RSI surged above 70 in late 2003 and then moved into its bull market range (40–90). There was one overshoot below 40 in July 2004, but RSI held the 40–50 zone at least five times from January 2005 until October 2007 (green arrows). In fact, notice that pullbacks to this zone provided low risk entry points to participate in the uptrend.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FvQjhRBl2i4uc0vHQDnLU%252Frsi-9-spybull.png%3Falt%3Dmedia%26token%3Dcb646c58-aeca-49ca-a4a7-5dc9bcf3f194&width=768&dpr=3&quality=100&sign=27ed86f8c1c7e40f91ba2630c4e4100f&sv=3)

Using RSI to identify an uptrend

On the flip side, RSI tends to fluctuate between 10 and 60 in a bear market (downtrend) with the 50-60 zone acting as resistance. The chart below shows 14-day RSI for the US Dollar Index ($USD) during its 2009 downtrend. RSI moved to 30 in March to signal the start of a bear range. The 50–60 zone subsequently marked resistance until a breakout in December.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252Fdh5ckOLfDv6tVIpCqgrP%252Frsi-10-usdbear.png%3Falt%3Dmedia%26token%3D8ae27891-e53f-4e2d-b9ee-e3a4f014b608&width=768&dpr=3&quality=100&sign=bd9bf9d737a705ec9ce3ed82a2066df1&sv=3)

Using RSI to identify a downtrend

* * *

### Identifying Positive and Negative Reversals With RSI[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/relative-strength-index-rsi\#identifying_positive_and_negative_reversals_with_rsi)

Andrew Cardwell developed positive and negative reversals for RSI, which are the opposite of bearish and bullish divergences. Cardwell's books are out of print, but he offers seminars detailing these methods. Cardwell's interpretation of divergences differs from Wilder's. Cardwell considered bearish divergences to be bull market phenomena. In other words, bearish divergences are more likely to form in uptrends. Similarly, bullish divergences are considered bear market phenomena and are indicative of a downtrend.

A positive reversal forms when RSI forges a lower low, and the security forms a higher low. This lower low is not at oversold levels but is usually between 30 and 50. The chart below shows MMM with a positive reversal forming in June 2009. MMM broke resistance a few weeks later, and RSI moved above 70. Despite weaker momentum with a lower low in RSI, MMM held above its prior low and showed underlying strength. In essence, price action overruled momentum.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252Fbo6BF9RSiPenPmzq5x7E%252Frsi-11-mmmprvsl.png%3Falt%3Dmedia%26token%3D331ddf34-c3ad-4a8b-8951-827ed40f6ea6&width=768&dpr=3&quality=100&sign=74ebd8d53e06a11ad93e9588090d20e2&sv=3)

Identifying a positive reversal with RSI

A negative reversal is the opposite of a positive reversal. RSI forms a higher high, but the security forms a lower high. Again, the higher high is usually just below overbought levels in the 50-70 area. The chart below shows Starbucks (SBUX) forming a lower high as RSI forms a higher high. Even though RSI forged a new high and momentum was strong, the price action failed to confirm as lower high formed. This negative reversal foreshadowed the big support break in late June and sharp decline.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FMkqWlsMFXpj3xN6tZ0ex%252Frsi-12-sbuxprvsl.png%3Falt%3Dmedia%26token%3D6822459e-3c1d-47a4-b61f-8321fd704cc5&width=768&dpr=3&quality=100&sign=6de478debd234400dbc045a21834888f&sv=3)

Identifying a negative reversal with RSI

* * *

## The Bottom Line[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/relative-strength-index-rsi\#final_thoughts)

RSI is a versatile momentum oscillator that has stood the test of time. Despite changes in [volatility](https://chartschool.stockcharts.com/table-of-contents/glossary/glossary-v#volatility) and the markets, RSI remains as relevant now as it was in Wilder's days. While Wilder's original interpretations help understand the indicator, the work of Brown and Cardwell takes RSI interpretation to a new level. But adjusting to this level takes some rethinking.

Wilder considers overbought conditions ripe for a reversal, but overbought can also be a sign of strength. Bearish divergences still produce some good sell signals, but you must be careful in strong trends when bearish divergences are normal. Even though the concept of positive and negative reversals may seem to undermine Wilder's interpretation, the logic makes sense. Wilder would hardly dismiss the value of putting more emphasis on price action. Positive and negative reversals put price action of the underlying security first and the indicator second, which is how it should be. Bearish and bullish divergences place the indicator first and price action second. By emphasizing price action, the concept of positive and negative reversals challenges our thinking toward momentum oscillators.

Like all technical indicators, RSI should be used in conjunction with other tools and indicators to confirm signals and avoid potential false alarms.

* * *

## Charting with RSI[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/relative-strength-index-rsi\#using_rsi_in_sharpcharts)

### Using with SharpCharts[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/relative-strength-index-rsi\#using_rsi_in_sharpcharts-1)

RSI is available as an indicator for SharpCharts. Select RSI from the **Indicator** dropdown, select the **Parameter** and the position (above, below, or behind the underlying price plot). Placing RSI directly on top of the price plot accentuates the movements relative to price action of the underlying security. You can apply “advanced options” to smooth the indicator with a moving average or add a horizontal line to mark overbought or oversold levels.

[Click here for a live version of this chart.](https://stockcharts.com/sc3/ui/?s=QQQ&id=p98665714007)

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FccBhiAlu8vZoUHlPhjMf%252Frsi-13-qqqqshch.png%3Falt%3Dmedia%26token%3Dc37f8cda-7666-4262-b6e6-719725f7e272&width=768&dpr=3&quality=100&sign=677aff99870f87c0da30767564e952c7&sv=3)

Using RSI on a SharpChart

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FUA6YWme30vFampOZO5xG%252Frsi-14-shch.png%3Falt%3Dmedia%26token%3D84de9733-cceb-4724-8b15-8e4f7a848093&width=768&dpr=3&quality=100&sign=c4b78c8507902049781faf7f0c35980e&sv=3)

RSI Settings on the SharpCharts Workbench

**Learn More:** For more details on the parameters used to configure RSI indicators, please see our [SharpCharts Parameter Reference](https://help.stockcharts.com/charts-and-tools/sharpcharts/sharpcharts-workbench/editing-sharpcharts/sharpcharts-parameter-reference#rsi) in the Support Center.

### Using with StockChartsACP[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/relative-strength-index-rsi\#using-with-stockchartsacp)

This indicator can be added from the Chart Settings panel for your StockChartsACP chart. The indicator can be positioned above, below, or behind the security's price plot.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252Fyj7WjJUOUhCSmwpZMVAo%252Frsiinacp.png%3Falt%3Dmedia%26token%3Dcc6f1ec9-fb06-45b9-9f83-160a3cc31359&width=768&dpr=3&quality=100&sign=b5a59c4b713ae93280db2620e717ac0f&sv=3)

Using RSI on an ACP chart

[Click here for a live version of this chart.](https://schrts.co/ditCCjbJ)

By default, this indicator is calculated using 14 periods. This parameter can be adjusted to meet your technical analysis needs.

* * *

## Scanning for RSI[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/relative-strength-index-rsi\#recommended_rsi_scans)

StockCharts members can search for stocks based on RSI values. Below are some example scans that can be used for RSI-based signals. Simply copy the scan text and paste it into the Scan Criteria box in the [Advanced Scan Workbench](https://stockcharts.com/def/servlet/ScanUI).

Members can also set up alerts to notify them when an RSI-based signal is triggered for a stock. Alerts use the same syntax as scans, so the sample scans below can be used as a starting point for setting up alerts as well. Simply copy the scan text and paste it into the Alert Criteria box in the [Technical Alert Workbench](https://stockcharts.com/h-al/al).

### RSI Oversold in Uptrend[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/relative-strength-index-rsi\#rsi_oversold_in_uptrend)

This scan reveals stocks that are in an uptrend with oversold RSI. First, stocks must be above their 200-day moving average to be in an overall uptrend. Second, RSI must cross below 30 to become oversold.

Copy

```
[type = stock] AND [country = US]
AND [Daily SMA(20,Daily Volume) > 40000]
AND [Daily SMA(60,Daily Close) > 20]

AND [Daily Close > Daily SMA(200,Daily Close)]
AND [Daily RSI(5,Daily Close) <= 30]
```

### RSI Overbought in Downtrend[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/relative-strength-index-rsi\#rsi_overbought_in_downtrend)

This scan reveals stocks that are in a downtrend with overbought RSI turning down. First, stocks must be below their 200-day moving average to be in an overall downtrend. Second, RSI must cross above 70 to become overbought.

Copy

```
[type = stock] AND [country = US]
AND [Daily SMA(20,Daily Volume) > 40000]
AND [Daily SMA(60,Daily Close) > 20]

AND [Daily Close < Daily SMA(200,Daily Close)]
AND [Daily RSI(5,Daily Close) >= 70]
```

**Learn More:** For more details on the syntax to use for RSI scans, please see our [Scanning Indicator Reference](https://help.stockcharts.com/scanning-and-alerts/scan-writing-resource-center/scan-syntax-reference/scan-syntax-technical-indicators#relative_strength_index_rsi) in the Support Center.

## Additional Resources[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/relative-strength-index-rsi\#further_study)

### Recommended Books[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/relative-strength-index-rsi\#recommended-books)

Constance Brown's [_Technical Analysis for the Trading Professional_](https://a.co/d/ehJRi4x) takes RSI to a new level with bull market and bear market ranges, positive and negative reversals, and projections based on RSI. Some methods of Andrew Cardwell, her RSI mentor, are also explained and refined in the book.

[PreviousRate of Change (ROC)](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/rate-of-change-roc) [NextRelative Volume (RVOL)](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/relative-volume-rvol)

Last updated 8 hours ago

Was this helpful?

This site uses cookies to deliver its service and to analyze traffic. By browsing this site, you accept the [privacy policy](https://help.stockcharts.com/learning-more/policies-and-limitations/privacy-statement).

AcceptReject