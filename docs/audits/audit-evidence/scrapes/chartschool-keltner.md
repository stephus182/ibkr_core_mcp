<!-- source: https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/keltner-channels -->

For the complete documentation index, see [llms.txt](https://chartschool.stockcharts.com/llms.txt). This page is also available as [Markdown](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/keltner-channels.md).

## What Are Keltner Channels?[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/keltner-channels\#introduction)

Keltner Channels are volatility-based envelopes set above and below an exponential moving average. This indicator is similar to Bollinger Bands, which use the standard deviation to set the bands. Instead of using the standard deviation, Keltner Channels use the Average True Range (ATR) to set channel distance. The channels are typically set two Average True Range values above and below the 20-day EMA. The exponential moving average dictates direction and the Average True Range sets channel width. **Keltner Channels are a trend following indicator used to identify reversals with channel breakouts and channel direction.** Channels can also be used to identify overbought and oversold levels when the trend is flat.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FtPWtaA03ydumlRDcvspz%252Fkelt-0-intro.png%3Falt%3Dmedia%26token%3Dd39cd751-40e9-49b6-8e64-f900a5f66c18&width=768&dpr=3&quality=100&sign=bdea81ef17c49a5bd87433e43c8c8316&sv=3)

[Click here for a live version of this chart.](https://stockcharts.com/sc3/ui/?s=XLP&p=D&b=5&g=0&id=p95754873344)

In his 1960 book, How to Make Money in Commodities, Chester Keltner introduced the “Ten-Day Moving Average Trading Rule,” which is credited as the original version of Keltner Channels. This original version started with a 10-day SMA of the typical price {(H+L+C)/3)} as the centerline. The 10-day SMA of the High-Low range was added and subtracted to set the upper and lower channel lines. Linda Bradford Raschke introduced the newer version of Keltner Channels in the 1980s. Like Bollinger Bands, this new version used a volatility based indicator, Average True Range (ATR), to set channel width. StockCharts.com uses this newer version of Keltner Channels.

**Learn More:** [Average True Range (ATR)](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/average-true-range-atr)

## Keltner Channels Calculation[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/keltner-channels\#keltner_channels_calculation)

There are three steps to calculating Keltner Channels. First, select the length for the exponential moving average. Second, choose the time periods for the Average True Range (ATR). Third, choose the multiplier for the Average True Range.

Copy

```
Middle Line: 20-day exponential moving average
Upper Channel Line: 20-day EMA + (2 x ATR(10))
Lower Channel Line: 20-day EMA - (2 x ATR(10))
```

The example above is based on the default settings for SharpCharts. Because moving averages lag price, a longer moving average will have more lag and a shorter moving average will have less lag. ATR is the basic volatility setting. Short timeframes, such as 10, produce a more volatile ATR that fluctuates as 10-period volatility ebbs and flows. Longer timeframes, such as 100, smooth these fluctuations to produce a more constant ATR reading. The multiplier has the most effect on the channel width. Simply changing from 2 to 1 will cut channel width in half. Increasing from 2 to 3 will increase channel width by 50%.

Here's a chart showing three Keltner Channels set at 1, 2, and 3 ATRs away from the central moving average. This particular technique has been advocated by Kerry Lovvorn of [SpikeTrade.com](http://spiketrade.com/) for years.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252F2G8rscSMM4fa7wU3iiAQ%252Fkelt-1-axpexam.png%3Falt%3Dmedia%26token%3D4e5b5b81-2177-49cc-81d3-3b379b34e04f&width=768&dpr=3&quality=100&sign=ca35e6fa20586ee464d4042ab2c43d1c&sv=3)

Keltner Channels - Calculation Example

The chart above shows the default Keltner Channels in red, a wider channel in blue and a narrower channel in green. The blue channels were set three Average True Range values above and below (3 x ATR). The green channels used one ATR value. All three share the 20-day EMA, which is the dotted line in the middle. The indicator windows show differences in the Average True Range (ATR) for 10 periods, 50 periods and 100 periods. Notice how the short ATR (10) is more volatile and has the widest range. In contrast, 100-period ATR is much smoother with a less volatile range.

## Interpreting Keltner Channels[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/keltner-channels\#interpreting_keltner_channels)

Indicators based on channels, bands and envelopes are designed to encompass most price action. Therefore, moves above or below the channel lines warrant attention because they are relatively rare. Trends often start with strong moves in one direction or another. A surge above the upper channel line shows extraordinary strength, while a plunge below the lower channel line shows extraordinary weakness. Such strong moves can signal the end of one trend and the beginning of another.

With an exponential moving average as its foundation, Keltner Channels are a trend following indicator. As with moving averages and other trend-following indicators, Keltner Channels lag price action. The direction of the moving average dictates the direction of the channel. In general, a downtrend is present when the channel moves lower, while an uptrend exists when the channel moves higher. The trend is flat when the channel moves sideways.

A channel upturn and break above the upper trend line can signal the start of an uptrend. A channel downturn and break below the lower trend line can signal the start a downtrend. Sometimes a strong trend does not take hold after a channel breakout and prices oscillate between the channel lines. Such trading ranges are marked by a relatively flat moving average. The channel boundaries can then be used to identify overbought and oversold levels for trading purposes.

**Learn More:** [Moving Averages](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/moving-averages-simple-and-exponential)

### Identifying the Start of an Uptrend[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/keltner-channels\#uptrend)

The chart below shows Archer Daniels Midland (ADM) starting an uptrend as the Keltner Channels turn up and the stock surges above the upper channel line. ADM was in a clear downtrend in April-May as prices continued to pierce the lower channel. With a strong thrust up in June, prices exceeded the upper channel and the channel turned up to start a new uptrend. Notice that prices held above the lower channel on dips in early and late July.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FzWNylOpsj37oHRMjLbTk%252Fkelt-2-admup.png%3Falt%3Dmedia%26token%3Da8e4c4ea-fea8-4270-a9c6-0d2d2f8df7b7&width=768&dpr=3&quality=100&sign=61cef81ec764e7bf274a8c5aeedec6a6&sv=3)

Keltner Channels - Uptrend Example

Even with a new uptrend established, it is often prudent to wait for a pullback or better entry point to improve the reward-to-risk ratio. Momentum oscillators or other indicators can then be employed to define oversold readings. This chart shows [StochRSI](https://chartschool.stockcharts.com/table-of-contents/glossary/glossary-s#stochrsi), one of the more sensitive momentum oscillators, dipping below .20 to become oversold at least three times during the uptrend. The subsequent crosses back above .20 signaled a resumption of the uptrend.

### Identifying the Start of a Downtrend[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/keltner-channels\#downtrend)

The chart below shows Nvidia (NVDA) starting a downtrend with a sharp decline below the lower channel line. After this initial break, the stock met resistance near the 20-day EMA (middle line) from mid-May until early August. The inability to even come close to the upper channel line showed strong downside pressure.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FlcPiGMeLDoeOx3Hp6J0b%252Fkelt-3-nvdadown.png%3Falt%3Dmedia%26token%3De93f983b-1624-4a70-a0f3-0629f6664a39&width=768&dpr=3&quality=100&sign=b47ead601ac931829debee98fd737edb&sv=3)

Keltner Channels - Downtrend Example

A 10-period [Commodity Channel Index (CCI)](https://chartschool.stockcharts.com/table-of-contents/glossary/glossary-c#commodity_channel_index_cci) is shown as the momentum oscillator to identify short-term overbought conditions. A move above 100 is considered overbought. A subsequent move back below 100 signals a resumption of the downtrend. This signal worked well until September. These failed signals indicated a possible trend change that was subsequently confirmed with a break above the upper channel line.

### Identifying Breakouts from a Trading Range[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/keltner-channels\#flat_trend)

Once a trading range or flat trading environment has been identified, traders can use the Keltner Channels to identify overbought and oversold levels. A trading range can be identified with a flat moving average and the Average Directional Index (ADX). The chart below shows IBM fluctuating between support in the 120-122 area and resistance in the 130-132 area from February to late September. The 20-day EMA (middle line) lagged price action, but flattened out from April to September.

The indicator window shows ADX (black line) confirming a weak trend. Low and falling ADX shows a weak trend. High and rising ADX shows a strong trend. ADX was below 40 the entire time and below 30 most of the time. This reflects the absence of a trend. Also, notice that ADX peaked in early June and fell until late August.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FAblhOBl9ZjejHPZOSMph%252Fkelt-4-ibmflat.png%3Falt%3Dmedia%26token%3D61938774-3182-4652-b83f-1615c62f4bb1&width=768&dpr=3&quality=100&sign=11b064f14fb7fafda0127adcef3ac67d&sv=3)

Keltner Channels - Breakout from a Trading Range

Armed with the prospects of a weak trend and trading range, traders can use Keltner Channels to anticipate reversals. In addition, notice that the channel lines often coincide with chart support and resistance. IBM dipped below the lower channel line three times from late May until late August. These dips provided low-risk entry points. The stock did not manage to reach the upper channel line, but did get close as it reversed in the resistance zone. The Disney chart shows a similar situation.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FEBiJ0JOrcSrWtF0eXxux%252Fkelt-5-disflat.png%3Falt%3Dmedia%26token%3Da921c85c-d503-42de-82ba-99fe3c0318b1&width=768&dpr=3&quality=100&sign=4c7eed1e8fac5c4562ce13ce54dbd878&sv=3)

Keltner Channels - Trading Range Example

### Keltner Channels vs Bollinger Bands[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/keltner-channels\#versus_bollinger_bands)

There are two differences between Keltner Channels and Bollinger Bands. First, Keltner Channels are smoother than Bollinger Bands because the width of the Bollinger Bands is based on the standard deviation, which is more volatile than the Average True Range (ATR). Many consider this a plus because it creates a more constant width. This makes Keltner Channels well suited for trend following and trend identification. Second, Keltner Channels also use an exponential moving average, which is more sensitive than the simple moving average used in Bollinger Bands. The chart below shows Keltner Channels (blue), Bollinger Bands (pink), Average True Range (10), Standard Deviation (10) and Standard Deviation (20) for comparison. Notice how the Keltner Channels are smoother than the Bollinger Bands. Also, notice how the Standard Deviation covers a larger range than the Average True Range (ATR).

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252F48RvOTwBZtFMz6lnPScu%252Fkelt-7-spybbs.png%3Falt%3Dmedia%26token%3D93efa153-de28-4263-be99-947c4c7921ff&width=768&dpr=3&quality=100&sign=d9e2534324959398d66cb4cedd02c10a&sv=3)

Keltner Channels vs Bollinger Bands

**Learn More:** [Bollinger Bands](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/bollinger-bands)

## The Bottom Line[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/keltner-channels\#conclusion)

**Keltner Channels are a trend following indicator designed to identify the underlying trend.** Trend identification is more than half the battle. The trend can be up, down or flat. Using the methods described above, traders and investors can identify the trend to establish a trading preference. Bullish trades are favored in an uptrend and bearish trades are favored in a downtrend. A flat trend requires a more nimble approach because prices often peak at the upper channel line and trough at the lower channel line. As with all analysis techniques, Keltner Channels should be used in conjunction with other indicators and analysis. Momentum indicators offer a good complement to the trend-following Keltner Channels.

**Learn More:** [Momentum Indicators](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/introduction-to-technical-indicators-and-oscillators#momentum_oscillators)

* * *

## Charting with Keltner Channels[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/keltner-channels\#charting_with_keltner_channels)

The Keltner Channels overlay can be added to SharpCharts and ACP Charts.

### Using with SharpCharts[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/keltner-channels\#using_with_sharpcharts)

Keltner Channels can be found in SharpCharts as a price overlay. As with a moving average, Keltner Channels should be shown on top of a price plot. Upon selecting the indicator from the dropdown box, the default setting will appear in the parameters window (20,2.0,10). The first number (20) sets the periods for the exponential moving average. The second number (2.0) is the ATR multiplier. The third number (10) is the number of periods for Average True Range (ATR). These default parameters set the channels 2 ATR values above/below the 20-day EMA. Users can change the parameters to suit their charting needs.

[Click here for a live version of the chart.](https://stockcharts.com/sc3/ui/?s=SPY&p=D&b=5&g=0&id=p14639241588&a=211776022)

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FjwnWCQ1o2q01dEXA9cth%252Fkelt-9-shchlive.png%3Falt%3Dmedia%26token%3Dc7a91ada-bee1-4f6f-81be-5b3791880121&width=768&dpr=3&quality=100&sign=444d423ea03a9464f1c4a9abf58b7849&sv=3)

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252F7Y6o9qGoL11Zii0A2DAF%252Fkelt-8-shch.png%3Falt%3Dmedia%26token%3D0a7d157f-b243-4774-9391-0d95f210464e&width=768&dpr=3&quality=100&sign=a76aa0561efa0c9f434fb3f35b1d85cd&sv=3)

SharpCharts settings for the Keltner Channels overlay

**Learn More:** For more details on the parameters used to configure Keltner Channel overlays, please see our [SharpCharts Parameter Reference](https://help.stockcharts.com/charts-and-tools/sharpcharts/sharpcharts-workbench/editing-sharpcharts/sharpcharts-parameter-reference#keltner_channels) in the Support Center.

### Using with StockChartsACP[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/keltner-channels\#using_with_stockchartsacp)

This overlay can be added from the Chart Settings panel for your StockChartsACP chart. Keltner Channels can be overlaid on the security's price plot or on an indicator panel.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252Fn7TLGPn1ihIjisdLQjDE%252Fkelt-acp.png%3Falt%3Dmedia%26token%3D779c21a7-5c47-4883-bc54-f4e630ee8d8b&width=768&dpr=3&quality=100&sign=680c51cb70465605074ad6d0d869e4c0&sv=3)

[Click here for a live version of this chart.](https://schrts.co/iMUpRAaf)

By default, the overlay uses a 20-period EMA, 10 periods for the ATR, and an ATR multiplier of 2.0. These parameters can be adjusted to meet your technical analysis needs.

## Scanning for Keltner Channels[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/keltner-channels\#scanning_for_keltner_channels)

StockCharts members can screen for stocks based on Keltner Channel values. Below are some example scans that can be used for Keltner Channel-based signals. Simply copy the scan text and paste it into the Scan Criteria box in the [Advanced Scan Workbench](https://stockcharts.com/def/servlet/ScanUI).

Members can also set up alerts to notify them when a Keltner Channel-based signal is triggered for a stock. Alerts use the same syntax as scans, so the sample scans below can be used as a starting point for setting up alerts as well. Simply copy the scan text and paste it into the Alert Criteria box in the [Technical Alert Workbench](https://stockcharts.com/h-al/al).

### Oversold after Bullish Keltner Channel Breakout[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/keltner-channels\#oversold_after_bullish_keltner_channel_breakout)

This scan looks for stocks that broke above their upper Keltner Channel 20 days ago to affirm or establish an uptrend. The current 10-period CCI is below -100 to indicate a short-term oversold condition.

Copy

```
[type = stock] AND [country = US]
AND [Daily SMA(20,Daily Volume) > 40000]

AND [20 days ago Daily High > 20 days ago Daily Upper Kelt Chan(20,2.0,10)]
AND [Daily CCI(10) < -100]
```

### Overbought after Bearish Keltner Channel Breakout[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/keltner-channels\#overbought_after_bearish_keltner_channel_breakout)

This scan looks for stocks that broke below their lower Keltner Channel 20 days ago to affirm or establish a downtrend. The current 10-period CCI is above +100 to indicate a short-term overbought condition.

Copy

```
[type = stock] AND [country = US]
AND [Daily SMA(20,Daily Volume) > 40000]

AND [20 days ago Daily Low < 20 days ago Daily Lower Kelt Chan(20,2.0,10)]
AND [Daily CCI(10) > 100]
```

**Learn More:** For more details on the scan syntax to use for Keltner Channel scans, please see our [Scanning Indicator Reference](https://help.stockcharts.com/scanning-and-alerts/scan-writing-resource-center/scan-syntax-reference/scan-syntax-technical-indicators#keltner_channels) in the Support Center.

## Additional Resources[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/keltner-channels\#recommended_books)

### Recommended Books[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/keltner-channels\#recommended_books-1)

Even though Keltner Channels are not used specifically in Thomas Carr's [_Trend Trading for a Living_](https://a.co/d/6qP0b1P), the book shows traders how to trade in the direction of the underlying trend. Carr also shows readers how to configure a bullish and bearish watch list from which to set your entry and exit prices.

Michael Covel's [_Trend Following_](https://a.co/d/a9zSIWz) introduces the fundamental concepts and techniques for a variety of trend following systems. Covel shows why market prices contain all available information, and readers will learn how to interpret price movements and profit from trend following.

[PreviousKaufman's Adaptive Moving Average (KAMA)](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/kaufmans-adaptive-moving-average-kama) [NextLinear Regression Forecast](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/linear-regression-forecast)

Last updated 5 months ago

Was this helpful?

This site uses cookies to deliver its service and to analyze traffic. By browsing this site, you accept the [privacy policy](https://help.stockcharts.com/learning-more/policies-and-limitations/privacy-statement).

AcceptReject