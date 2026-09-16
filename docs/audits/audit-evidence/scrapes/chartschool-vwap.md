<!-- source: https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/volume-weighted-average-price-vwap -->

For the complete documentation index, see [llms.txt](https://chartschool.stockcharts.com/llms.txt). This page is also available as [Markdown](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/volume-weighted-average-price-vwap.md).

## What Is the Volume-Weighted Average Price?[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/volume-weighted-average-price-vwap\#introduction)

Volume-Weighted Average Price (VWAP) is exactly what it sounds like: **the average price weighted by volume.** VWAP equals the dollar value of all trading periods divided by the total trading volume for the current day. The VWAP overlay is calculated using intraday data from a single market day, starting when trading opens and ending when it closes.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252F7rN108x9nYdzkrVK6bTF%252Fvwapexample.png%3Falt%3Dmedia%26token%3Dadedbd1e-3b61-4771-bcad-0637bbd2606b&width=768&dpr=3&quality=100&sign=bc54a33b841567ea7e6b813f5b869639&sv=3)

Originally developed by institutional investors in order to place large orders without disrupting the market, VWAP can also be used by retail investors. The VWAP line functions almost like a single-day moving average. Chartists can assess the position of price relative to the VWAP line in order to determine the intraday trend, or to set favorable entry and exit points for trades.

## Calculating VWAP[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/volume-weighted-average-price-vwap\#vwap_calculation)

VWAP is calculated using intraday data for a single day, starting from the first trade of the day and ending when the market closes. The calculated values for each period produce a line that is overlaid on the chart.

**Cool Tip:** Sometimes you want to start the VWAP line at a specific date and time (e.g. at a significant high or low, earnings announcement, or some other indicator of a change in market psychology). This way, the VWAP line would be calculated using only price action since the significant event. You can use the [Anchored VWAP overlay](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/anchored-vwap) to set a specific start time.

### Tick vs. Minute Data[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/volume-weighted-average-price-vwap\#tick_versus_minute)

Traditional VWAP is based on tick data. As you can imagine, there are many ticks (trades) during each minute of the day. Active securities during active periods can have 20–30 ticks in one minute alone. With 390 minutes in a typical stock exchange trading day, many stocks end up with well over 5000 ticks per day. Over 5000 stocks are traded every day, and these ticks start adding up exponentially. Needless to say, tick data is very resource-intensive.

Instead of VWAP based on tick data, StockCharts.com offers intraday VWAP based on intraday periods (1, 5, 10, 15, 30, or 60 minutes). Note that VWAP is not defined for daily, weekly, or monthly periods due to the nature of the calculation (see below).

### VWAP Formulas[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/volume-weighted-average-price-vwap\#vwap-formulas)

The formula for VWAP is fairly simple:

Copy

```
Cumulative(Volume x Typical Price)/Cumulative(Volume)
```

There are five steps involved in this calculation:

1. Compute the typical price for the intraday period. This is the average of the high, low, and close: `(H+L+C)/3)`.

2. Multiply the typical price by the period's volume.

3. Create a running total of these values. This is also known as a cumulative total.

4. Create a running total of volume (cumulative volume).

5. Divide the running total of price-volume by the running total of volume.


The spreadsheet example below shows one-minute VWAP for the first 30 minutes of trading in IBM. Dividing cumulative price volume by cumulative volume produces a price level adjusted (weighted) by volume. The first VWAP value is always the typical price because volume is equal in the numerator and the denominator. They cancel each other out in the first calculation.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FwfuTK341Da5lVM490n9q%252Fvwapp-1-xlsheet.png%3Falt%3Dmedia%26token%3D5abfb88d-1db0-4c5d-8b53-1fecac1d5167&width=768&dpr=3&quality=100&sign=53b183116294e460a4b22dc3399e6ce2&sv=3)

VWAP calculation example for IBM

The chart below shows one-minute bars with VWAP for IBM covering the same time period as the spreadsheet. For the first 30 minutes of trading, prices ranged from $127.36 on the high to $126.67 on the low. It was a volatile first 30 minutes. VWAP ranged from 127.21 to 127.09 and spent its time in the middle of this range.

![Chart from StockCharts.com of one-minute bars with a VWAP overlay.](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FzRSh1neiqN11Dj76aA6b%252Fvwapp-2-ibmexam.png%3Falt%3Dmedia%26token%3D6110d3cb-cd4a-4544-b8a0-72d1bc0db2b7&width=768&dpr=3&quality=100&sign=7258bb07ca0805826163eb0f389568bb&sv=3)

One-minute bars with VWAP on the IBM chart

### VWAP vs. Moving Averages[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/volume-weighted-average-price-vwap\#characteristics)

The VWAP line behaves similarly to a moving average, but because VWAP only uses values from a single trading day, the VWAP values at the beginning of that day use very few data points, and the values at market close are calculated using far more data.

The one-minute VWAP value at the end of the day is often close to the ending value for a 390-minute moving average. Both moving averages are based on the one-minute bars for that day. At the close, both are based on 390 minutes of data (one full day).

You cannot compare the 390-minute moving average to VWAP during the day, however. A 390-minute moving average at 12:00 PM will include data from the previous day. VWAP will not. Remember, VWAP calculations start fresh at the open and end at the close. Since 150 minutes of trading have elapsed by 12:00 PM, VWAP at 12:00 PM would need to be compared with a 150-minute moving average instead.

![Chart from StockCharts.com comparing a one-minute VWAP and a 390-minute moving average](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252F2QBUbvXaeQbfZHiSosgt%252Fvwapp-3-wmtsma.png%3Falt%3Dmedia%26token%3Dff35c416-b11e-4b99-bd6f-8c64b897f18d&width=768&dpr=3&quality=100&sign=0a3f7bd33ce4f7523f281f8b6b3f3978&sv=3)

VWAP compared with a 150-minute SMA at noon and a 390-minute SMA at close.

## Interpreting VWAP[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/volume-weighted-average-price-vwap\#interpreting-vwap)

While VWAP was originally developed for institutional investors to use when making large trades, individual investors can also use this overlay to determine the intraday trend and to assess entry/exit points.

### Determining the Intraday Trend[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/volume-weighted-average-price-vwap\#determining-the-intraday-trend)

Like moving averages, VWAP lags price because it is an average based on past data. The more data there is, the greater the lag.

Despite this lag, you can compare VWAP with the current price to determine the general direction of intraday prices. It works like a moving average. In general, intraday prices fall when below VWAP and rise when above VWAP. VWAP will fall somewhere between the day's high-low range when prices are range-bound for the day.

The next three charts show examples of flat, rising, and falling VWAP lines.

In the first chart, Merck (MRK) was in a trading range all day, and the VWAP line was flat across most of the chart. Because the first VWAP data point uses only one bar of price data in its calculations, the VWAP line starts closer to the opening price, but it quickly drops into a flat line as more price bars are added to the calculation.

![Chart from StockCharts.com showing a flat VWAP](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252Fb7IbHq0zAANHKH8GYePM%252Fvwapp-6-mrkflat.png%3Falt%3Dmedia%26token%3D7e2ed9be-22a1-487d-bcc9-32784d0367e9&width=768&dpr=3&quality=100&sign=e4d445d7cf364b2d0b322a486065aec6&sv=3)

Example of flat VWAP line

In the second chart, the price of General Electric (GE) was rising throughout the day, and the VWAP line rose accordingly. Notice that the price bars are above the VWAP line throughout most of the day. Again, the early VWAP values are a little erratic because so few data points have been accumulated for the calculation.

![Chart from StockCharts.com showing a rising VWAP](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252F1YZ2CMXrv4qPjyn1Lcyd%252Fvwapp-5-geup.png%3Falt%3Dmedia%26token%3D4cea9fe9-739d-4e87-a523-e9144ef6bc75&width=768&dpr=3&quality=100&sign=e028782df7fbb6befbbcd7c46529ef99&sv=3)

Example of rising VWAP line

The third chart shows the price of Microsoft (MSFT) falling throughout the day, with the VWAP line falling accordingly. In this case, the price bars spend most of the day below the VWAP line.

![Chart from StockCharts.com showing a falling VWAP](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FsqPAJuu7KrbtyE3DggmH%252Fvwapp-4-mfstdown.png%3Falt%3Dmedia%26token%3Db70a22d0-3361-4f43-a1a4-8b1a7870159e&width=768&dpr=3&quality=100&sign=89c035a3189bd991ef775e982fe22e64&sv=3)

Example of falling VWAP line

In all three examples, the direction of the VWAP line and its position relative to the price bars give chartists clues as to the intraday trend.

### Assessing Entry and Exit Points[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/volume-weighted-average-price-vwap\#assessing-entry-and-exit-points)

VWAP is used to identify [liquidity](https://chartschool.stockcharts.com/table-of-contents/glossary/glossary-l#liquidity) points. As a volume-weighted price measure, VWAP reflects price levels weighted by volume. This can help institutions with large orders. The idea is not to disrupt the market when entering large buy or sell orders. VWAP helps these institutions determine the liquid and illiquid price points for a specific security over a very short time.

VWAP can also be used to measure trading efficiency. After buying or selling a security, institutions or individuals can compare its price to VWAP values. A buy order executed below the VWAP value would be considered a good fill because the security was bought at a below-average price. Conversely, a sell order executed above the VWAP would be deemed a good fill because it was sold at an above-average price.

* * *

## The Bottom Line[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/volume-weighted-average-price-vwap\#conclusion)

VWAP serves as a reference point for one day's prices. Because of this, it's best suited for **intraday analysis.** Chartists can compare current prices with the VWAP values to determine the intraday trend. VWAP can also be used to determine relative value. Prices below VWAP values are relatively low for that day or that specific time. By contrast, prices above VWAP values are relatively high for that day or that specific time. **Remember that VWAP is a cumulative indicator, which means the number of data points progressively increases throughout the day.** On a one-minute chart, IBM will have 90 data points (minutes) by 11:00 AM, 210 data points by 1:00 PM, and 390 data points by the close. The number dramatically increases as the day extends. This is why VWAP lags price, and this lag increases as the day extends.

* * *

## Charting with VWAP[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/volume-weighted-average-price-vwap\#using_with_sharpcharts)

The VWAP overlay can be added to intraday SharpCharts and ACP Charts.

### Using with SharpCharts[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/volume-weighted-average-price-vwap\#using_with_sharpcharts-1)

Volume-Weighted Average Price (VWAP) can be plotted as a price overlay on Sharpcharts. After entering the security symbol, choose an **intraday** period and a **range**. The Period determines the data used to calculate the overlay. The range can set be for one day or "fill the chart." If you want more detail, choose "fill the chart," and if you want general levels, choose one day.

VWAP can be plotted over more than one day, but the overlay will jump from its prior closing value to the typical price for the next open as a new calculation period begins. Also, note that VWAP values can sometimes fall off the price chart. VWAP at 45.50 will not show up on a chart with a price range from $45.80 to $47. You may sometimes need to extend the range to a full day to see VWAP on the chart. The VWAP value is always displayed in the legend at the top left of the chart.

[Click here for a live version of this chart.](https://stockcharts.com/sc3/ui/?s=INTU&a=2277810739&p=1&yr=0&mn=0&dy=1&id=p13211053241)

![Chart from StockCharts.com showing a VWAP overlay on a one-minute chart of INTC](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FwG6nvSgC388ZO2YS38Yu%252Fvwapinshch.png%3Falt%3Dmedia%26token%3Da09f0926-c667-4191-b7d8-2c1bacc96ae6&width=768&dpr=3&quality=100&sign=aa71da571ad9df7b8c2df6a286224b1a&sv=3)

![Screenshot of Chart Attributes settings in SharpCharts](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FQXsurk01HTvlCrZkSd3K%252Fvwapp-8-shch.png%3Falt%3Dmedia%26token%3D9a7f8f16-e799-4ad7-ac36-a71db164d607&width=768&dpr=3&quality=100&sign=98cabe365bcd0dc0138062c9deae17ed&sv=3)

SharpCharts settings for the VWAP overlay

**Learn More.** For more details on the parameters used to configure VWAP overlays, please see our [SharpCharts Parameter Reference](https://help.stockcharts.com/charts-and-tools/sharpcharts/sharpcharts-workbench/editing-sharpcharts/sharpcharts-parameter-reference#vwap) in the Support Center.

### Using with StockChartsACP[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/volume-weighted-average-price-vwap\#using-with-stockchartsacp)

This overlay can be added from the Chart Settings panel for your intraday StockChartsACP chart.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FCCOGeHgW06dSmkGdGiSF%252Fvwapinacp.png%3Falt%3Dmedia%26token%3D44e9a32f-f579-4007-abf2-81bdd30c7ed8&width=768&dpr=3&quality=100&sign=340a01f1f5fe52af164a5fcb34d1bc08&sv=3)

[Click here for a live version of this chart.](https://schrts.co/hHEsRsyE)

This overlay takes no parameters, but the color and style of the VWAP line can be customized for your chart.

[PreviousVolume-by-Price](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/volume-by-price) [NextZigZag](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/zigzag)

Last updated 3 months ago

Was this helpful?

This site uses cookies to deliver its service and to analyze traffic. By browsing this site, you accept the [privacy policy](https://help.stockcharts.com/learning-more/policies-and-limitations/privacy-statement).

AcceptReject