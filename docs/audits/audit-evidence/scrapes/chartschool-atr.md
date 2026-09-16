<!-- source: https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/average-true-range-atr -->

For the complete documentation index, see [llms.txt](https://chartschool.stockcharts.com/llms.txt). This page is also available as [Markdown](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/average-true-range-atr.md).

## What Is the Average True Range (ATR)?[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/average-true-range-atr\#what_is_the_average_true_range_atr)

Developed by J. Welles Wilder, the Average True Range (ATR) is an indicator that measures [volatility](https://chartschool.stockcharts.com/table-of-contents/glossary/glossary-v#volatility). As with most of his indicators, Wilder designed ATR with commodities and daily prices in mind. Commodities are frequently more volatile than stocks. They are often subject to gaps and limit moves, which occur when a commodity opens up or down its maximum allowed move for the session. A volatility formula based only on the high-low range would fail to capture volatility from gap or limit moves. Wilder created the Average True Range to capture this “missing” volatility. It is important to remember that ATR doesn't indicate price direction, just volatility.

Wilder features ATR in his 1978 book, _New Concepts in Technical Trading Systems_. This book also includes the Parabolic SAR, RSI, and the Directional Movement Concept (ADX). Despite being developed before the computer age, Wilder's indicators have stood the test of time and remain extremely popular.

## True Range[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/average-true-range-atr\#true_range)

Wilder started with a concept called **True Range (TR)**, which is defined as the greatest of the following:

- Method 1. Current High less the current Low

- Method 2. Current High less the previous Close (absolute value)

- Method 3. Current Low less the previous Close (absolute value)


Absolute values are used to ensure positive numbers. After all, Wilder was interested in measuring the distance between two points, not the direction. If the current period's high is above the prior period's high and the low is below the prior period's low, then the current period's high-low range will be used as the True Range. This is an outside day that would use Method 1 to calculate the TR. This is pretty straightforward. Methods 2 and 3 are used when there is a gap or an inside day. A gap occurs when the previous close is greater than the current high (signaling a potential gap down or limit move) or the previous close is lower than the current low (signaling a potential gap up or limit move). The image below shows examples of when methods 2 and 3 are appropriate.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FPOAF56FPLJ2xmlvASeda%252Fatr-1-trexam.png%3Falt%3Dmedia%26token%3D664f498b-f669-4c9c-b10b-6065a492afed&width=768&dpr=3&quality=100&sign=6a94eef78bc021bf4c811ccd09016f69&sv=3)

ATR - True Range Image

**Example A.** A small high/low range formed after a gap up. The TR equals the absolute value of the difference between the current high and the previous close.

**Example B.** A small high/low range formed after a gap down. The TR equals the absolute value of the difference between the current low and the previous close.

**Example C.** Even though the current close is within the previous high/low range, the current high/low range is quite small. In fact, it is smaller than the absolute value of the difference between the current high and the previous close, which is used to value the TR.

## How To Calculate ATR[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/average-true-range-atr\#how_to_calculate_atr)

Typically, the Average True Range (ATR) is based on 14 periods and can be calculated on an intraday, daily, weekly or monthly basis. For this example, the ATR will be based on daily data. Because there must be a beginning, the first TR value is simply the High minus the Low, and the first 14-day ATR is the average of the daily TR values for the last 14 days. After that, Wilder sought to smooth the data by incorporating the previous period's ATR value.

Copy

```
Current ATR = [(Prior ATR x 13) + Current TR] / 14

  - Multiply the previous 14-day ATR by 13.
  - Add the most recent day's TR value.
  - Divide the total by 14
```

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FDjxIhfVxaxSygIrcX2qm%252Fatr-2-qqqqsh.png%3Falt%3Dmedia%26token%3D050fd1c5-d403-4556-8579-d7efb041e5bb&width=768&dpr=3&quality=100&sign=0e267b8bdcaccadbdd17c4dffe236fcd&sv=3)

Click below to download an Excel spreadsheet that shows the beginning of an ATR calculation.

[cs-atr (1).xls](https://436553459-files.gitbook.io/~/files/v0/b/gitbook-x-prod.appspot.com/o/spaces%2FERtrZrZOhufFzk6ZQO4B%2Fuploads%2Fl2dscfibmLDJyo1YVDpe%2Fcs-atr%20(1).xls?alt=media&token=5186005d-c6de-464a-acc9-f70ffa4d9c5d)

41KB

Download [Open](https://436553459-files.gitbook.io/~/files/v0/b/gitbook-x-prod.appspot.com/o/spaces%2FERtrZrZOhufFzk6ZQO4B%2Fuploads%2Fl2dscfibmLDJyo1YVDpe%2Fcs-atr%20(1).xls?alt=media&token=5186005d-c6de-464a-acc9-f70ffa4d9c5d)

In the spreadsheet example, the first True Range value (0.91) equals the High minus the Low (yellow cells). The first 14-day ATR value (0.56) was calculated by finding the average of the first 14 True Range values (blue cell). Subsequent ATR values were smoothed using the formula above. The spreadsheet values correspond with the yellow area on the chart below; notice how ATR surged as QQQ plunged in May with many long candlesticks.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252F9FhMfcqMa0Y76iCBDLcg%252Fatr-3-qqqqexam.png%3Falt%3Dmedia%26token%3De8387479-46d7-407c-89e7-b9a0856a3b13&width=768&dpr=3&quality=100&sign=88c1f72d431c7299d228e5160b92bb93&sv=3)

ATR plotted on chart using StockCharts.com - Chart 1

For those trying this at home, a few caveats apply. First, just like with [Exponential Moving Averages (EMAs)](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/moving-averages-simple-and-exponential), ATR values depend on how far back you begin your calculations. The first True Range value is the current high minus the current low, and the first ATR is an average of the first 14 True Range values. The real ATR formula kicks in on day 15. Even so, the remnants of these first two calculations “linger” to slightly affect subsequent ATR values. **Spreadsheet values for a small subset of data may not match exactly with what is seen on the price chart.** Decimal rounding can also slightly affect ATR values. On our charts, we calculate back at least 250 periods (typically much further) to ensure a much greater degree of accuracy for our ATR values.

## Absolute ATR[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/average-true-range-atr\#absolute_atr)

ATR is based on the True Range, which uses absolute price changes. As such, ATR reflects volatility at an absolute level. In other words, ATR is not shown as a percentage of the current close. This means low-priced stocks will have lower ATR values than high-price stocks. For example, a $20-30 security will have much lower ATR values than a $200-300 security. Because of this, ATR values are not comparable. Large price movements for a single security, such as a decline from 70 to 20, can make long-term ATR comparisons impractical. Chart 4 shows Google with double-digit ATR values, and chart 5 shows Microsoft with ATR values below 1. Despite different values, their ATR lines have similar shapes.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FzVYGCTVwQoAY7qhSynHT%252Fatr-4-googhigh.png%3Falt%3Dmedia%26token%3Dbecb7f10-0e59-4a94-8281-37cbbab30e14&width=768&dpr=3&quality=100&sign=1581f99563e307127841bf59e7fadbc1&sv=3)

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FOqengrGCg5RfNeJiLN4F%252Fatr-5-mfstlow.png%3Falt%3Dmedia%26token%3Da2598c1d-2bc6-4b49-9470-3d252de0822d&width=768&dpr=3&quality=100&sign=e637498ce7b27d6a2e510e98cf4e8be7&sv=3)

## The Bottom Line[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/average-true-range-atr\#the_bottom_line)

ATR is not directional indicators like MACD or RSI. Instead, it's a unique volatility indicator that reflect the degree of interest or disinterest in a move. Large ranges or True Ranges often accompany strong moves in either direction, which can be volatile. This is especially true at the beginning of a move. Relatively narrow ranges can accompany low-volatility moves. The ATR can validate the enthusiasm behind a move or breakout. A bullish reversal with increased ATR would show strong buying pressure and reinforce the reversal. A bearish support break with increased ATR would show strong selling pressure and reinforce the support break.

* * *

## Using ATR with SharpCharts[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/average-true-range-atr\#using_atr_with_sharpcharts)

Listed as “Average True Range,” ATR is on the Indicators drop-down menu. The “parameters” box to the right of the indicator contains the default value, 14, for the number of periods used to smooth the data. To adjust the period setting, highlight the default value and enter a new setting. In his work, Wilder often used an 8-period ATR. SharpCharts also allows users to position the indicator above, below or behind the price plot. A moving average can be added to identify upturns or downturns in ATR. Click “advanced options” to add a moving average as an indicator overlay. [Click here](https://stockcharts.com/sc3/ui/?s=$INDU&p=D&b=5&g=0&id=p51341747448&listNum=30&a=202613287) for a live example of ATR.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FRH8qAzQxYpBE7Q1vKtR7%252Fatr-6-shch.png%3Falt%3Dmedia%26token%3D05144af0-c142-4b29-b9c8-437c13b6cb62&width=768&dpr=3&quality=100&sign=f23329e5e91fdcd9eccaf703d13a4e56&sv=3)

ATR - SharpCharts

## Suggested Scans[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/average-true-range-atr\#suggested_scans)

### Weeding Out High Volatility[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/average-true-range-atr\#weeding_out_high_volatility)

The Average True Range indicator can be used in scans to weed out securities with extremely high volatility. This simple scan searches for S&P 600 stocks that are in an uptrend. The final scan clause excludes high volatility stocks from the results. Note that the ATR is converted to a percentage of sorts so that the ATR of different stocks can be compared on the same scale.

Copy

```
[group is SP600]
AND [Daily EMA(50,close) > Daily EMA(200,close)]

AND [ATR(250) / SMA(20,Close) * 100 < 4]
```

For more details on the syntax to use for ATR scans, please see our [Scanning Indicator Reference](https://support.stockcharts.com/doku.php?id=scans:indicators#average_true_range_atr) in the Support Center.

[PreviousAverage Directional Index (ADX)](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/average-directional-index-adx) [NextAverage True Range Percent (ATRP)](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/average-true-range-percent-atrp)

Last updated 3 months ago

Was this helpful?

This site uses cookies to deliver its service and to analyze traffic. By browsing this site, you accept the [privacy policy](https://help.stockcharts.com/learning-more/policies-and-limitations/privacy-statement).

AcceptReject