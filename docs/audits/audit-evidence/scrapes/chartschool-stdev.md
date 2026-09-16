<!-- source: https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/standard-deviation-volatility -->

For the complete documentation index, see [llms.txt](https://chartschool.stockcharts.com/llms.txt). This page is also available as [Markdown](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/standard-deviation-volatility.md).

## What Is Standard Deviation (Volatility)?[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/standard-deviation-volatility\#introduction)

Standard deviation is a statistical term that measures the amount of variability or dispersion around an average. Standard deviation is also a measure of volatility. Generally speaking, dispersion is the difference between the actual value and the average value. The larger this dispersion or variability is, the higher the standard deviation. The smaller this dispersion or variability is, the lower the standard deviation. Chartists can use the standard deviation to measure expected risk and determine the significance of certain price movements.

* * *

## Calculating Standard Deviation[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/standard-deviation-volatility\#calculation)

StockCharts.com calculates the standard deviation for a population, which assumes that the periods involved represent the whole data set, not a sample from a bigger data set. The calculation steps are as follows:

1. Calculate the average (mean) price for the number of periods or observations.

2. Determine each period's deviation (close less average price).

3. Square each period's deviation.

4. Sum the squared deviations.

5. Divide this sum by the number of observations.

6. The standard deviation is then equal to the square root of that number.


![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FG7x8z9nHOSk5GuJGTz3z%252Fstdv-1-qqqqexcel1.png%3Falt%3Dmedia%26token%3D6d8fd411-4a7a-4799-b00f-9e48070d151f&width=768&dpr=3&quality=100&sign=885614532985d95440f01c9ed947057f&sv=3)

Standard Deviation Excel Spreadsheet

The spreadsheet above shows an example for a 10-period standard deviation using QQQQ data. Notice that the 10-period average is calculated after the 10th period and this average is applied to all 10 periods. Building a running standard deviation with this formula would be quite intensive. Excel has an easier way with the STDEVP formula. The table below shows the 10-period standard deviation using this formula.

Click below to download an Excel spreadsheet that shows standard deviation calculations.

[cs-stddev.xls](https://436553459-files.gitbook.io/~/files/v0/b/gitbook-x-prod.appspot.com/o/spaces%2FERtrZrZOhufFzk6ZQO4B%2Fuploads%2FhBTgzmtEOdtBRmMMeKCK%2Fcs-stddev.xls?alt=media&token=5d65cbc5-9c5f-4a06-95bc-c4d21bcd739b)

23KB

Download [Open](https://436553459-files.gitbook.io/~/files/v0/b/gitbook-x-prod.appspot.com/o/spaces%2FERtrZrZOhufFzk6ZQO4B%2Fuploads%2FhBTgzmtEOdtBRmMMeKCK%2Fcs-stddev.xls?alt=media&token=5d65cbc5-9c5f-4a06-95bc-c4d21bcd739b)

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252F0m3G1emTCGKGwJfgghiZ%252Fstdv-2-qqqqexam.png%3Falt%3Dmedia%26token%3D1d166336-f9ae-4ece-b07a-797dcd2a380c&width=768&dpr=3&quality=100&sign=5d1afd31611270f4655ad9f38ff9463d&sv=3)

Standard Deviation Chart 1

* * *

## Standard Deviation Values[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/standard-deviation-volatility\#standard_deviation_values)

Standard deviation values are dependent on the price of the underlying security. Securities with high prices, such as Google (±550), will have higher standard deviation values than securities with low prices, such as Intel (±22). These higher values are not a reflection of higher volatility, but rather a reflection of the actual price. Standard deviation values are shown in terms that relate directly to the price of the underlying security. Historical standard deviation values will also be affected if a security experiences a large price change over a period of time. A security that moves from 10 to 50 will most likely have a higher standard deviation at 50 than at 10.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252Fo53DCucmo02dPW9t8BgQ%252Fstdv-3-googintc.png%3Falt%3Dmedia%26token%3D3d4da07f-c4d9-41fd-8d42-2c7f8bac528a&width=768&dpr=3&quality=100&sign=143192960b1b83bb8563679d9d9ccdcf&sv=3)

Standard Deviation Chart 2

On the chart above, the left scale relates to the standard deviation. Google's standard deviation scale extends from 2.5 to 35, while the Intel range runs from .10 to .75. Average price changes (deviations) in Google range from $2.5 to $35, while average price changes (deviations) in Intel range from 10 cents to 75 cents.

Despite the range differences, chartists can visually assess volatility changes for each security. Volatility in Intel picked up from April to June as the standard deviation moved above .70 numerous times. Google experienced a surge in volatility in October as the standard deviation shot above 30. One would have to divide the standard deviation by the closing price to directly compare volatility for the two securities.

* * *

## Measuring Expectations[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/standard-deviation-volatility\#measuring_expectations)

The current value of the standard deviation can be used to estimate the importance of a move or set expectations. This assumes that price changes are normally distributed with a classic bell curve. Even though price changes for securities are not always normally distributed, chartists can still use normal distribution guidelines to gauge the significance of a price movement. In a normal distribution, 68% of the observations fall within one standard deviation, while 95% fall within two and 99.7% fall within three. Using these guidelines, traders can estimate the significance of a price movement. A move greater than one standard deviation would show above average strength or weakness, depending on the direction of the move.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FuTq5gyMD0SSNaccj9hPx%252Fstdv-4-msft68.png%3Falt%3Dmedia%26token%3D207dd2b9-d0fb-48e9-89e7-a3f065325e46&width=768&dpr=3&quality=100&sign=edc6fe4cbde4929a67500cce27acab60&sv=3)

Standard Deviation Chart 3

The chart above shows Microsoft (MSFT) with a 21-day standard deviation in the indicator window. There are around 21 trading days in a month and the monthly standard deviation was .88 on the last day. In a normal distribution, 68% of the 21 observations should show a price change less than 88 cents. 95% of the 21 observations should show a price change of less than 1.76 cents (2 x .88 or two standard deviations). 99.7% of the observations should show a price change of less than 2.64 (3 x .88 or three standard deviations. Price movements that were 1,2 or 3 standard deviations would be deemed noteworthy.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252Fn7RPHAlWN2gvORf41Q57%252Fstdv-5-msft95.png%3Falt%3Dmedia%26token%3D76245fa7-6d8f-4d70-97d6-c48d3004cabd&width=768&dpr=3&quality=100&sign=9eaa7e036f386f8a298769a7b16db2ee&sv=3)

Standard Deviation Chart 5

The 21-day standard deviation is still quite variable as it fluctuated between .32 and .88 from mid-August until mid-December. A 250-day moving average can be applied to smooth the indicator and find an average, which is around 68 cents. Price moves larger than 68 cents were greater than the 250-day SMA of the 21-day standard deviation. These above-average price movements indicate heightened interest that could foreshadow a trend change or mark a breakout.

* * *

## Conclusion[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/standard-deviation-volatility\#conclusion)

The standard deviation is a statistical measure of volatility. These values provide chartists with an estimate for expected price movements. Price moves greater than the Standard deviation show above average strength or weakness. The standard deviation is also used with other indicators, such as [Bollinger Bands](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/bollinger-bands). These bands are set 2 standard deviations above and below a moving average. Moves that exceed the bands are deemed significant enough to warrant attention. As with all indicators, the standard deviation should be used in conjunction with other analysis tools, such as [momentum oscillators](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/introduction-to-technical-indicators-and-oscillators#momentum_oscillators) or [chart patterns](https://chartschool.stockcharts.com/table-of-contents/chart-analysis/chart-patterns).

* * *

## Using with SharpCharts[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/standard-deviation-volatility\#using_with_sharpcharts)

The standard deviation is available as an indicator in SharpCharts with a default parameter of 10. This parameter can be changed according to analysis needs. Roughly speaking, 21 days equals one month, 63 days equals one quarter and 250 days equals one year. The standard deviation can also be used on weekly or monthly charts. Indicators can be applied to the standard deviation by clicking advanced options and then adding an overlay. [Click here](https://stockcharts.com/sc3/ui/?s=QQQ&p=D&yr=0&mn=6&dy=0&id=p80789045093&listNum=30&a=217969334) for a live chart with the standard deviation.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FuCOqGLWJU7GmJUjjax5R%252Fstdv-6-qqqqlive.png%3Falt%3Dmedia%26token%3D9a0dcc4b-4d92-46e5-8971-8163ca62e3f5&width=768&dpr=3&quality=100&sign=f0f4c6dac1616d2d503f90f5a5e73b31&sv=3)

Standard Deviation Chart 6

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FU4Lz49rX5gLBFASezmlv%252Fstdv-7-shch.png%3Falt%3Dmedia%26token%3Daebb865f-f418-4c17-afab-c7c9ad8b55e0&width=768&dpr=3&quality=100&sign=4c733d2c6e0a8559f9bd139cb1291d22&sv=3)

Standard Deviation SharpCharts

## Suggested Scans[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/standard-deviation-volatility\#suggested_scans)

### Weeding Out High Volatility[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/standard-deviation-volatility\#weeding_out_high_volatility)

The Standard Deviation indicator is often used in scans to weed out securities with extremely high volatility. This simple scan searches for S&P 600 stocks that are in an uptrend. The final scan clause excludes high volatility stocks from the results. Note that the standard deviation is converted to a percentage of sorts so that the standard deviation of different stocks can be compared on the same scale.

Copy

```
[group is SP600]
AND [Daily EMA(50,close) > Daily EMA(200,close)]

AND [Std Deviation(250) / SMA(20,Close) * 100 < 20]
```

**Learn More.** For more details on the syntax to use for Standard Deviation scans, please see our [Scan Syntax Reference](https://help.stockcharts.com/scanning-and-alerts/scan-writing-resource-center/scan-syntax-reference/scan-syntax-technical-indicators#standard_deviation_std_deviation) in the Support Center.

[PreviousSlope](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/slope) [NextStochastic Oscillator (Fast, Slow, and Full)](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/stochastic-oscillator-fast-slow-and-full)

Last updated 8 months ago

Was this helpful?

This site uses cookies to deliver its service and to analyze traffic. By browsing this site, you accept the [privacy policy](https://help.stockcharts.com/learning-more/policies-and-limitations/privacy-statement).

AcceptReject