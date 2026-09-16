<!-- source: https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/stochastic-oscillator-fast-slow-and-full -->

For the complete documentation index, see [llms.txt](https://chartschool.stockcharts.com/llms.txt). This page is also available as [Markdown](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/stochastic-oscillator-fast-slow-and-full.md).

## What Is the Stochastic Oscillator?[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/stochastic-oscillator-fast-slow-and-full\#what_is_the_stochastic_oscillator)

The Stochastic Oscillator is a momentum indicator that shows the speed and momentum of price movement. George C. Lane developed the indicator in the late 1950s. According to an interview with Lane, the Stochastic Oscillator “doesn't follow price, it doesn't follow volume or anything like that. It follows the speed or the momentum of price. As a rule, the momentum changes direction before price.” As such, bullish and bearish divergences in the Stochastic Oscillator can be used to foreshadow reversals. This was the first and most important signal that Lane identified. Lane also used this oscillator to identify bull and bear set-ups to anticipate a future reversal. As the Stochastic Oscillator is range-bound, it is also helpful in identifying overbought and oversold levels.

## How Do You Calculate the Stochastic Oscillator?[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/stochastic-oscillator-fast-slow-and-full\#how_do_you_calculate_the_stochastic_oscillator)

Copy

```
%K = (Current Close - Lowest Low)/(Highest High - Lowest Low) * 100
%D = 3-day SMA of %K

Lowest Low = lowest low for the look-back period
Highest High = highest high for the look-back period
%K is multiplied by 100 to move the decimal point two places
```

The default setting for the Stochastic Oscillator is 14 periods, which can be days, weeks, months or an intraday timeframe. A 14-period %K would use the most recent close, the highest high over the last 14 periods and the lowest low over the last 14 periods. %D is a 3-day simple [moving average](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/moving-averages-simple-and-exponential) of %K. This line is plotted alongside %K to act as a signal or trigger line.

Click below to download a spreadsheet example that shows the Stochastic Oscillator calculations.

[cs-soo.xls](https://436553459-files.gitbook.io/~/files/v0/b/gitbook-x-prod.appspot.com/o/spaces%2FERtrZrZOhufFzk6ZQO4B%2Fuploads%2F39NrAUay7CXm7lwemxFD%2Fcs-soo.xls?alt=media&token=ad8fd04f-0323-42ea-b6ff-dfce2abd22f7)

19KB

Download [Open](https://436553459-files.gitbook.io/~/files/v0/b/gitbook-x-prod.appspot.com/o/spaces%2FERtrZrZOhufFzk6ZQO4B%2Fuploads%2F39NrAUay7CXm7lwemxFD%2Fcs-soo.xls?alt=media&token=ad8fd04f-0323-42ea-b6ff-dfce2abd22f7)

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FoddXmPXlfqku3ZjdLDYZ%252Fsoo-1-ibmexam.png%3Falt%3Dmedia%26token%3Df424e467-3d11-4963-b995-aa194e8327b2&width=768&dpr=3&quality=100&sign=00218f8a060a1e8391ce1e0c34961961&sv=3)

Stochastics - Chart 1

## Interpreting the Stochastic Oscillator[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/stochastic-oscillator-fast-slow-and-full\#interpreting_the_stochastic_oscillator)

The Stochastic Oscillator measures the level of the close relative to the high-low range over a given period. Assume that the highest high equals 110, the lowest low equals 100, and the close equals 108. The high-low range is 10, the denominator in the %K formula. The close less the lowest low equals 8, which is the numerator. When you divide 8 by 10 you get 0.80 or 80%. Multiply this number by 100 to find %K. %K would equal 30 if the close were at 103 (0.30 x 100). The Stochastic Oscillator is above 50 when the close is in the upper half of the range and below 50 when the close is in the lower half. Low readings (below 20) indicate that price is near its low for the given time period. High readings (above 80) indicate that price is near its high for the given time period. The IBM example above shows three 14-day ranges (yellow areas) with the closing price at the end of the period (red dotted) line. The Stochastic Oscillator equals 91 when the close was at the top of the range, 15 when it was near the bottom, and 57 when it was in the middle of the range.

## Three Stochastic Versions: Fast, Slow, and Full[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/stochastic-oscillator-fast-slow-and-full\#three_stochastic_versionsfast_slow_and_full)

There are three versions of the Stochastic Oscillator available on SharpCharts. The Fast Stochastic Oscillator is based on George Lane's original formulas for %K and %D. In this fast version, %K can appear rather choppy. %D is the 3-day SMA of %K. In fact, Lane used %D to generate buy or sell signals based on bullish and bearish divergences. Lane asserts that a %D divergence is the “only signal which will cause you to buy or sell.” Because %D in the Fast Stochastic Oscillator is used for signals, the Slow Stochastic Oscillator was introduced to reflect this emphasis. The Slow Stochastic Oscillator smooths %K with a 3-day SMA, which is exactly what %D is in the Fast Stochastic Oscillator. Notice that %K in the Slow Stochastic Oscillator equals %D in the Fast Stochastic Oscillator (chart 2).

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FLPDTg7HcJsn2QXGFk6Od%252Fsoo-2-qqqqfull.png%3Falt%3Dmedia%26token%3Db6c7181f-cc8a-49c9-88e8-8ea11f4335e6&width=768&dpr=3&quality=100&sign=0e7b4235cd19af6bdd8644045a215a52&sv=3)

Stochastics - Chart 2

### Fast Stochastic Oscillator:[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/stochastic-oscillator-fast-slow-and-full\#fast-stochastic-oscillator)

- Fast %K = %K basic calculation

- Fast %D = 3-period SMA of Fast %K


### Slow Stochastic Oscillator:[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/stochastic-oscillator-fast-slow-and-full\#slow-stochastic-oscillator)

- Slow %K = Fast %K smoothed with 3-period SMA

- Slow %D = 3-period SMA of Slow %K


The Full Stochastic Oscillator is a fully customizable version of the Slow Stochastic Oscillator. Users can set the look-back period, the number of periods for slow %K and the number of periods for the %D moving average. The default parameters were used in these examples: Fast Stochastic Oscillator (14,3), Slow Stochastic Oscillator (14,3) and Full Stochastic Oscillator (14,3,3).

### Full Stochastic Oscillator:[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/stochastic-oscillator-fast-slow-and-full\#full-stochastic-oscillator)

- Full %K = Fast %K smoothed with X-period SMA

- Full %D = X-period SMA of Full %K


## Overbought/Oversold[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/stochastic-oscillator-fast-slow-and-full\#overbought_oversold)

As a [bound oscillator](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/introduction-to-technical-indicators-and-oscillators#banded_oscillators), the Stochastic Oscillator makes it easy to identify overbought and oversold levels. The oscillator ranges from zero to 100. No matter how fast a security advances or declines, the Stochastic Oscillator will always fluctuate within this range. Traditional settings use 80 as the overbought threshold and 20 as the oversold threshold. These levels can be adjusted to suit analytical needs and security characteristics.

For example, if the 20-day Stochastic Oscillator is above 80 it indicates the underlying security is trading near the top of its 20-day high-low range. A reading below 20 indicates the security is trading at the low end of its high-low range.

Overbought readings aren't necessarily bearish. Securities can become overbought and remain overbought during a strong uptrend. Closing levels that are consistently near the top of the range indicate sustained buying pressure.

In a similar vein, oversold readings aren't necessarily bullish. Securities can also become oversold and remain oversold during a strong downtrend. Closing levels consistently near the bottom of the range indicate sustained selling pressure. This is why it's important to identify the bigger trend and trade in the direction of this trend. Look for occasional oversold readings in an uptrend and ignore frequent overbought readings. Similarly, look for occasional overbought readings in a strong downtrend and ignore frequent oversold readings.

The chart below displays the Full Stochastic Oscillator (20,5,5) in the panel below a price chart. A longer look-back period (20 days versus 14) and longer moving averages for smoothing (5 versus 3) produce a less sensitive oscillator with fewer signals. The stock was trading between $14 and $18 from July 2009 until April 2010. Such trading ranges are well suited for the Stochastic Oscillator. Dips below 20 warn of oversold conditions that could foreshadow a bounce. Moves above 80 warn of overbought conditions that could foreshadow a decline.

![Full Stochastic Oscillator applied to a chart from StockCharts.com showing how a stock can remain overbought for an extended period](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FT5DtscSRBfkbtMPxN4z2%252Fsoo-3-yhooobos.png%3Falt%3Dmedia%26token%3Dc7b68055-19af-4abe-925f-0c5167b1d8e2&width=768&dpr=3&quality=100&sign=ccf20a7925c0b34fe8844dd03346e25f&sv=3)

FULL STOCHASTIC OSCILLATOR. Note how the oscillator moved above 80 and remained there.

Notice how the oscillator can move above 80 and remain above 80 (orange highlights). Similarly, the oscillator moved below 20 and sometimes remained below 20. The indicator is overbought _and_ strong when above 80. A subsequent move below 80 is needed to signal a reversal or failure at resistance (red dotted lines). Conversely, the oscillator is oversold and weak when below 20. A move above 20 is needed to show an upturn and successful support test (green dotted lines).

Chart 4 shows Crown Castle (CCI) with a breakout in July to start an uptrend. The Full Stochastic Oscillator (20,5,5) was used to identify oversold readings. Overbought readings were ignored because the bigger trend was up. Trading in the direction of the bigger trend improves the odds. The Full Stochastic Oscillator moved below 20 in early September and early November. Subsequent moves back above 20 signaled an upturn in prices (green dotted line) and continuation of the bigger uptrend.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FytAsceNywkWiEHsQm9mm%252Fsoo-4-cciosup.png%3Falt%3Dmedia%26token%3Dca7df0bd-9147-487e-a2e6-2a79da490a80&width=768&dpr=3&quality=100&sign=544980ad66339d6ec1eb81b9fa35d4c3&sv=3)

Stochastics - Chart 4

Chart 5 shows Autozone (AZO) with a support break in May 2009 that started a downtrend. With a downtrend in force, the Full Stochastic Oscillator (10,3,3) was used to identify overbought readings to foreshadow a potential reversal. Oversold readings were ignored because of the bigger downtrend. The shorter look-back period (10 versus 14) increases the sensitivity of the oscillator for more overbought readings. For reference, the Full Stochastic Oscillator (20,5,5) is also shown. Notice that this less sensitive version did not become overbought in August, September, and October. It is sometimes necessary to increase sensitivity to generate signals.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FIni3HlsNddtLPepvtlaZ%252Fsoo-5-azoobdn.png%3Falt%3Dmedia%26token%3Dba554c6b-f6dd-4147-b7f8-ccbaa1d8efd2&width=768&dpr=3&quality=100&sign=c58ccf40427d62c28390bead84be58d5&sv=3)

Stochastics - Chart 5

## Bull/Bear Divergences[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/stochastic-oscillator-fast-slow-and-full\#bull_bear_divergences)

[Divergences](https://chartschool.stockcharts.com/table-of-contents/glossary/glossary-d#divergence) form when a new high or low in price is not confirmed by the Stochastic Oscillator. A bullish divergence forms when price records a lower low, but the Stochastic Oscillator forms a higher low. This shows less downside momentum that could foreshadow a bullish reversal. A bearish divergence forms when price records a higher high, but the Stochastic Oscillator forms a lower high. This shows less upside momentum that could foreshadow a bearish reversal.

When a divergence takes hold, look for a confirmation to signal a reversal. A bearish divergence can be confirmed with a support break on the price chart or a Stochastic Oscillator break below 50, which is the centerline. A bullish divergence can be confirmed with a resistance break on the price chart or a Stochastic Oscillator break above 50.

The 50 level is important to watch. The Stochastic Oscillator moves between zero and 100, which makes 50 the centerline. Think of it as the 50-yard line in football. The offense has a higher chance of scoring when it crosses the 50-yard line. The defense has an edge as long as it prevents the offense from crossing the 50-yard line.

A Stochastic Oscillator cross above 50 signals that prices are trading in the upper half of their high-low range for the given look-back period. This suggests that the cup is half full. Conversely, a cross below 50 means that prices are trading in the bottom half of the given look-back period. This suggests that the cup is half empty.

Chart 6 shows International Gaming Tech (IGT) with a bullish divergence in February-March 2010. Notice how the stock moved to a new low, but the Stochastic Oscillator formed a higher low. There are three steps to confirming this higher low. The first is a signal line cross and/or move back above 20. A signal line cross occurs when %K (black) crosses %D (red). This provides the earliest entry possible. The second is a move above 50, which puts prices in the upper half of the Stochastic range. The third is a resistance breakout on the price chart. Notice how the Stochastic Oscillator moved above 50 in late March and remained above 50 until late May.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FfghwMbpwdY8Mo01fC3S2%252Fsoo-6-igtbudd.png%3Falt%3Dmedia%26token%3D8a64373a-4837-42a7-b626-b769e508e6e6&width=768&dpr=3&quality=100&sign=272a6d65f564210b7ec921687dffd7ef&sv=3)

Stochastics - Chart 6

Chart 7 shows Kohls (KSS) with a bearish divergence in April 2010. The stock moved to higher highs in early and late April, but the Stochastic Oscillator peaked in late March and formed lower highs. The signal line crosses and moves below 80 did not provide good early signals in this case because KSS kept moving higher. The Stochastic Oscillator moved below 50 for the second signal and the stock broke support for the third signal. As KSS shows, early signals are not always clean and simple. Signal line crosses, moves below 80, and moves above 20 are frequent and prone to whipsaw. Even after KSS broke support and the Stochastic Oscillator moved below 50, the stock bounced back above 57 and the Stochastic Oscillator bounced back above 50 before the stock continued sharply lower.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252Fw5p3DLOP06sMbgHomcx0%252Fsoo-7-kssbedd.png%3Falt%3Dmedia%26token%3Dd1b12b58-c673-4f15-8680-97d1f085fd82&width=768&dpr=3&quality=100&sign=0d9e38f23dac305351d1a72375931319&sv=3)

Stochastics - Chart 7

## Bull/Bear Set-Ups[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/stochastic-oscillator-fast-slow-and-full\#bull_bear_set-ups)

George Lane identified another form of divergence to predict bottoms or tops, dubbed “set-ups.” A bull set-up is basically the inverse of a bullish divergence. The underlying security forms a lower high, but the Stochastic Oscillator forms a higher high. Even though the stock could not exceed its prior high, the higher high in the Stochastic Oscillator shows strengthening upside momentum. The next decline is then expected to result in a tradable bottom.

Chart 8 shows Network Appliance (NTAP) with a bull set-up in June 2009. The stock formed a lower high as the Stochastic Oscillator forged a higher high. This higher high shows strength in upside momentum. Remember that this is a set-up, not a signal. The set-up foreshadows a tradable low in the near future. NTAP declined below its June low and the Stochastic Oscillator moved below 20 to become oversold. Traders could have acted when the Stochastic Oscillator moved above its signal line, above 20 or above 50, or after NTAP broke resistance with a strong move.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FpQrsb8z9VNRbwtTwKAh5%252Fsoo-8-ntapbuset.png%3Falt%3Dmedia%26token%3Dce4323cc-7219-42da-be93-7d31a856b357&width=768&dpr=3&quality=100&sign=6fa76dcb3d284aaf9742f470f64ef197&sv=3)

Stochastics - Chart 8

A bear set-up occurs when the security forms a higher low, but the Stochastic Oscillator forms a lower low. Even though the stock held above its prior low, the lower low in the Stochastic Oscillator shows increasing downside momentum. The next advance is expected to result in an important peak. Chart 9 shows Motorola (MOT) with a bear set-up in November 2009. The stock formed a higher low in late-November and early December, but the Stochastic Oscillator formed a lower low with a move below 20. This showed strong downside momentum. The subsequent bounce did not last long as the stock quickly peaked. Notice that the Stochastic Oscillator did not make it back above 80 and turned down below its signal line in mid-December.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FyaxfYlWP85muABrN5AuJ%252Fsoo-9-motbeset.png%3Falt%3Dmedia%26token%3Dad01a8f7-2021-4729-a69e-7311e9b4eced&width=768&dpr=3&quality=100&sign=b025800c18ef5610fe0936ca8052a76f&sv=3)

Stochastics - Chart 9

## The Bottom Line[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/stochastic-oscillator-fast-slow-and-full\#the_bottom_line)

While momentum oscillators are best suited for trading ranges, they can also be used with securities that trend, provided the trend takes on a zigzag format. Pullbacks are part of uptrends that zigzag higher. Bounces are part of downtrends that zigzag lower. In this regard, the Stochastic Oscillator can be used to identify opportunities in harmony with the bigger trend.

The indicator can also be used to identify turns near support or resistance. Should a security trade near support with an oversold Stochastic Oscillator, look for a break above 20 to signal an upturn and successful support test. Conversely, should a security trade near resistance with an overbought Stochastic Oscillator, look for a break below 80 to signal a downturn and resistance failure.

The settings on the Stochastic Oscillator depend on personal preferences, trading style and timeframe. A shorter look-back period will produce a choppy oscillator with many overbought and oversold readings. A longer look-back period will provide a smoother oscillator with fewer overbought and oversold readings.

Like all technical indicators, it is important to use the Stochastic Oscillator in conjunction with other technical analysis tools. Volume, support/resistance and breakouts can be used to confirm or refute signals produced by the Stochastic Oscillator.

* * *

## Using with SharpCharts[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/stochastic-oscillator-fast-slow-and-full\#using_with_sharpcharts)

As noted above, there are three versions of the Stochastic Oscillator available as an indicator on SharpCharts. The default settings are as follows: Fast Stochastic Oscillator (14,3), Slow Stochastic Oscillator (14,3) and Full Stochastic Oscillator (14,3,3). The look-back period (14) is used for the basic %K calculation. Remember, %K in the Fast Stochastic Oscillator is unsmoothed and %K in the Slow Stochastic Oscillator is smoothed with a 3-day SMA. The “3” in the Fast and Slow Stochastic Oscillator settings (14,3) sets the moving average period for %D. Chartists looking for maximum flexibility can simply choose the Full Stochastic Oscillator to set the look-back period, the smoothing factor for %K and the moving average for %D. The indicator can be placed above, below or behind the actual price plot. Placing the Stochastic Oscillator behind the price allows users to easily match indicator swings with price swings. [Click here for a live example](https://stockcharts.com/sc3/ui/?s=$COMPQ&p=D&yr=0&mn=6&dy=0&id=p82180859243&listNum=30&a=201659153).

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FR2x8dMMYhWGqADtsamEL%252Fsoo-10-compqlive.png%3Falt%3Dmedia%26token%3D289726d1-389a-41d7-9b8a-fde694e5ef5a&width=768&dpr=3&quality=100&sign=4f456ec73f5cb67d6e6ccb837e99d30d&sv=3)

Stochastics - Chart 10

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FkSbRBZ3CnfGgxY0wZapT%252Fsoo-11-shch.png%3Falt%3Dmedia%26token%3D7f90fb49-e7fa-4827-85f8-286e46e43703&width=768&dpr=3&quality=100&sign=ac2de07b72e5d16f38b641d05f98e857&sv=3)

Stochastics - SharpCharts

## Suggested Scans[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/stochastic-oscillator-fast-slow-and-full\#suggested_scans)

### Stochastic Oscillator Oversold Upturn[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/stochastic-oscillator-fast-slow-and-full\#stochastic_oscillator_oversold_upturn)

This scan starts with stocks that are trading above their 200-day moving average to focus on those that are in a bigger uptrend. Of these, the scan then looks for stocks with a Stochastic Oscillator that turned up from an oversold level (below 20).

Copy

```
[type = stock] AND [country = US]
AND [Daily SMA(20,Daily Volume) > 40000]
AND [Daily SMA(60,Daily Close) > 20]

AND [Daily Close > Daily SMA(200,Daily Close)]
AND [Yesterday's Daily Slow Stoch %K(14,3) < 20]
AND [Daily Slow Stoch %K(14,3) > 20]
```

### Stochastic Oscillator Overbought Downturn[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/stochastic-oscillator-fast-slow-and-full\#stochastic_oscillator_overbought_downturn)

This scan starts with stocks that are trading below their 200-day moving average to focus on those that are in a bigger downtrend. Of these, the scan then looks for stocks with a Stochastic Oscillator that turned down after an overbought reading (above 80).

Copy

```
[type = stock] AND [country = US]
AND [Daily SMA(20,Daily Volume) > 40000]
AND [Daily SMA(60,Daily Close) > 20]

AND [Daily Close < Daily SMA(200,Daily Close)]
AND [Yesterday's Daily Slow Stoch %K(14,3) > 80]
AND [Daily Slow Stoch %K(14,3) < 80]
```

**Learn More.** For more details on the syntax to use for Stochastic Oscillator scans, please see our [Scanning Indicator Reference](https://help.stockcharts.com/scanning-and-alerts/scan-writing-resource-center/scan-syntax-reference/scan-syntax-technical-indicators#stochastic_oscillators) in the Support Center.

## Stochastic Oscillator FAQs[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/stochastic-oscillator-fast-slow-and-full\#stochastic_oscillator_faqs)

What are the different versions of the Stochastic Oscillator? [Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/stochastic-oscillator-fast-slow-and-full#what-are-the-different-versions-of-the-stochastic-oscillator)

There are three versions of the Stochastic Oscillator: Fast, Slow, and Full.

- The Fast version uses original formulas for %K and %D.

- The Slow version smooths %K with a 3-day SMA.

- The Full version is customizable, allowing users to set the look-back period, the number of periods for slow %K, and the number of periods for the %D moving average.


What is a bullish divergence in the Stochastic Oscillator? [Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/stochastic-oscillator-fast-slow-and-full#what-is-a-bullish-divergence-in-the-stochastic-oscillator)

A bullish divergence occurs when the price records a lower low, but the Stochastic Oscillator forms a higher low. This indicates less downside momentum, potentially foreshadowing a bullish reversal.

What is a bearish divergence in the Stochastic Oscillator? [Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/stochastic-oscillator-fast-slow-and-full#what-is-a-bearish-divergence-in-the-stochastic-oscillator)

A bearish divergence occurs when the price records a higher high, but the Stochastic Oscillator forms a lower high. This signals less upside momentum, potentially indicating a bearish reversal.

What are Bull/Bear Set-Ups in the context of the Stochastic Oscillator? [Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/stochastic-oscillator-fast-slow-and-full#what-are-bull-bear-set-ups-in-the-context-of-the-stochastic-oscillator)

Bull and Bear Set-Ups, identified by George Lane, are another form of divergence used to predict market tops or bottoms. A bull set-up forms when the security creates a lower high, but the Stochastic Oscillator forms a higher high. In contrast, a bear set-up happens when the security forms a higher low, but the Stochastic Oscillator forms a lower low.

Can the Stochastic Oscillator be used for trending securities? [Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/stochastic-oscillator-fast-slow-and-full#can-the-stochastic-oscillator-be-used-for-trending-securities)

While the Stochastic Oscillator is best suited for trading ranges, it can also be used with securities that trend, as long as the trend has a zigzag format. In an uptrend, pullbacks are parts of the zigzag that move higher. In a downtrend, bounces are parts of the zigzag that move lower. A suitable adjustment of the oscillator's sensitivity may be needed for these scenarios.

* * *

## Further Study[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/stochastic-oscillator-fast-slow-and-full\#further_study)

John Murphy's [_Technical Analysis of the Financial Markets_](https://a.co/d/598OGRx) has a chapter devoted to momentum oscillators and their various uses, covering the pros and cons as well as some examples specific to the Stochastic Oscillator.

Martin Pring's [_Technical Analysis Explained_](https://a.co/d/7N8AqJF) explains the basics of momentum indicators by covering divergences, crossovers, and other signals. There are two more chapters covering specific momentum indicators, each containing a number of examples.

[**Technical Analysis of the Financial Markets**](https://a.co/d/598OGRx)
John J. Murphy

[**Technical Analysis Explained**](https://a.co/d/7N8AqJF)
Martin Pring

[PreviousStandard Deviation (Volatility)](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/standard-deviation-volatility) [NextStochRSI](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/stochrsi)

Last updated 24 minutes ago

Was this helpful?

This site uses cookies to deliver its service and to analyze traffic. By browsing this site, you accept the [privacy policy](https://help.stockcharts.com/learning-more/policies-and-limitations/privacy-statement).

AcceptReject