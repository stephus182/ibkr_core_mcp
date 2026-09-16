<!-- source: https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/moving-averages-simple-and-exponential -->

For the complete documentation index, see [llms.txt](https://chartschool.stockcharts.com/llms.txt). This page is also available as [Markdown](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/moving-averages-simple-and-exponential.md).

## What Is a Moving Average?[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/moving-averages-simple-and-exponential\#what_is_a_moving_average)

A moving average is an average of data points (usually price) for a specific time period. Why is it called “moving”? That's because each data point is calculated using data from the previous X periods. Because it averages prior data, moving averages smooth the price data to form a trend-following indicator.

A moving average doesn't predict price direction. Instead, it defines the current direction. However, a moving average tends to lag because it's based on past prices. Despite this, investors use moving averages to help smooth price action and filter out the noise.

Moving averages can be used to identify trend direction or define potential support and resistance levels. They also form the building blocks for many other technical indicators and overlays, such as [Bollinger Bands](https://chartschool.stockcharts.com/table-of-contents/glossary/glossary-b#bollinger_bands), [MACD](https://chartschool.stockcharts.com/table-of-contents/glossary/glossary-m#macd_moving_average_convergence_divergence), and [the McClellan Oscillator](https://chartschool.stockcharts.com/table-of-contents/glossary/glossary-m#mcclellan_oscillator).

![Chart from StockCharts.com showing a simple moving average (SMA) and exponential moving average (EMA) overlaid on a price chart of INTC](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252F7X38Cb7oiAifq7ZizKtW%252Fmova-1-intcexam.png%3Falt%3Dmedia%26token%3D1083254f-4892-4b36-964a-c993c1e0ec99&width=768&dpr=3&quality=100&sign=9cf499c5832c40ef1d266577f58aaa97&sv=3)

Example of a Simple Moving Average (SMA) and Exponential Moving Average (EMA) overlaid on a chart of INTC.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FM8bHBTieqVGCRCmVMIYB%252Fscc-icon.png%3Falt%3Dmedia%26token%3D34ef3915-ca84-44cd-b0ba-a8c136fb9a8f&width=40&dpr=3&quality=100&sign=fd7f826b0b5b67d7a4d39a6f4af26f0b&sv=3)[Click here for a live version of the chart.](https://stockcharts.com/sc3/ui/?s=INTC&a=1187753835&id=p81873495608)

* * *

The two most popular moving averages are the **simple moving average (SMA)** and the **exponential moving average (EMA)**. Simple moving averages (SMAs) average prices over the specified timeframe, while exponential moving averages (EMAs) give more weight to recent prices. Other specialty moving averages available in our charting tools include DEMA, Hull Moving Average, KAMA, and TEMA.

**Learn More.** [DEMA](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/double-exponential-moving-average-dema) \| [Hull Moving Average](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/hull-moving-average-hma) \| [KAMA](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/kaufmans-adaptive-moving-average-kama) \| [TEMA](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/triple-exponential-moving-average-tema)

### The Lag Factor in Moving Averages[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/moving-averages-simple-and-exponential\#what_is_the_lag_factor_in_moving_averages)

Because moving averages are based on past data, they tend to lag behind price data. The longer the moving average, the more the lag. In addition, the type of moving average affects the lag: EMAs with the more recent data weighted more heavily will lag less than an SMA, which gives equal weight to data further in the past.

A 10-day moving average will hug prices quite closely and turn shortly after prices turn. Short-term moving averages are like speedboats—nimble and quick to change. In contrast, a 100-day moving average contains lots of past data that slows it down. Longer-term moving averages are like ocean tankers—lethargic and slow to change. It takes a larger and longer price movement for a 100-day moving average to change course vs. a 10-day moving average.

The chart below shows the SPDR S&P 500 ETF (SPY) with a 10-day EMA closely following prices and a 100-day SMA grinding higher. Even with the July-August decline, the 100-day SMA held the course and did not turn down. The 50-day SMA fits somewhere between the 10- and 100-day moving averages when it comes to the lag factor.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FT8hHcHTCHCp8li0jP4AQ%252Fmova-2-spylag.png%3Falt%3Dmedia%26token%3D416a77d5-1c6d-4fcd-be23-f27570a8b0b0&width=768&dpr=3&quality=100&sign=11e38e707f3cb821c37e954d9bf143d8&sv=3)

The 10-day EMA in the chart follows price more closely than the 100-day SMA.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FM8bHBTieqVGCRCmVMIYB%252Fscc-icon.png%3Falt%3Dmedia%26token%3D34ef3915-ca84-44cd-b0ba-a8c136fb9a8f&width=40&dpr=3&quality=100&sign=fd7f826b0b5b67d7a4d39a6f4af26f0b&sv=3)[Click here for a live version of the chart.](https://stockcharts.com/sc3/ui/?s=SPY&id=p18857343158)

* * *

Keep the lag factor in mind when choosing the right moving average for your chart. Your moving average preferences will depend on your objectives, analytical style, and time horizon. Try experimenting with both types of moving averages, different timeframes, and different securities to find the best fit.

* * *

## Moving Average Calculation[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/moving-averages-simple-and-exponential\#how_do_you_calculate_moving_averages)

All moving averages take the average of a specified number of prior data points, but each type of moving average weights those data points differently.

### Simple Moving Average Formulas[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/moving-averages-simple-and-exponential\#simple_moving_average_formulas)

**A simple moving average is formed by computing the average price of a security over a specific number of periods.** Most moving averages are based on closing prices; for example, a 5-day simple moving average is the five-day sum of closing prices divided by five. As its name implies, a moving average is an average that moves. Old data is dropped as new data becomes available, causing the average to move along the time scale. The example below shows a 5-day moving average evolving over three days.

Copy

```
Daily Closing Prices: 11,12,13,14,15,16,17

First day of 5-day SMA: (11 + 12 + 13 + 14 + 15) / 5 = 13

Second day of 5-day SMA: (12 + 13 + 14 + 15 + 16) / 5 = 14

Third day of 5-day SMA: (13 + 14 + 15 + 16 + 17) / 5 = 15
```

The first day of the moving average simply covers the last five days. The second day of the moving average drops the first data point (11) and adds the new data point (16). The third day of the moving average continues by dropping the first data point (12) and adding the new data point (17). In the example above, prices gradually increase from 11 to 17 over a total of seven days. Notice that the moving average also rises from 13 to 15 over a three-day calculation period. Also, notice that each moving average value is just below the last price. For example, the moving average for day one equals 13 and the last price is 15. Prices the prior four days were lower and this causes the moving average to lag.

### Exponential Moving Average Formulas[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/moving-averages-simple-and-exponential\#exponential_moving_average_formulas)

Exponential moving averages (EMAs) reduce the lag by applying more weight to recent prices. The weighting applied to the most recent price depends on the number of periods in the moving average. EMAs differ from simple moving averages in that a given day's EMA calculation depends on the EMA calculations for all the days prior to that day. You need far more than 10 days of data to calculate a reasonably accurate 10-day EMA.

There are three steps to calculating an exponential moving average (EMA). First, calculate the simple moving average for the initial EMA value. An exponential moving average (EMA) has to start somewhere, so a simple moving average is used as the previous period's EMA in the first calculation. Second, calculate the weighting multiplier. Third, calculate the exponential moving average for each day between the initial EMA value and today, using the price, the multiplier, and the previous period's EMA value. The formula below is for a 10-day EMA.

Copy

```
Initial SMA: 10-period sum / 10

Multiplier: (2 / (Time periods + 1) ) = (2 / (10 + 1) ) = 0.1818 (18.18%)

EMA: {Close - EMA(previous day)} x multiplier + EMA(previous day).
```

#### **EMA Weighting Multiplier**[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/moving-averages-simple-and-exponential\#ema-weighting-multiplier)

A 10-period exponential moving average applies an 18.18% weighting to the most recent price. A 10-period EMA can also be called an 18.18% EMA. A 20-period EMA applies a 9.52% weighting to the most recent price (2/(20+1) = .0952). Notice that the weighting for the shorter time period is more than the weighting for the longer time period. In fact, the weighting drops by half every time the moving average period doubles.

If you want to use a specific percentage for an EMA, you can use this formula to convert it to time periods and then enter that value as the EMA's parameter:

Copy

```
Time Period = (2 / Percentage) - 1

3% Example:  Time Period = (2 / 0.03) - 1 = 65.67 time periods
```

#### **EMA Accuracy**[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/moving-averages-simple-and-exponential\#ema-accuracy)

Below is a spreadsheet example of a 10-day simple moving average and a 10-day exponential moving average for Intel. The SMA calculation is straightforward and requires little explanation: the 10-day SMA simply moves as new prices become available and old prices drop off. The exponential moving average in the spreadsheet starts with the SMA value (22.22) for its first EMA value. After the first calculation, the normal EMA formula is used.

The formula for an EMA incorporates the previous period's EMA value, which in turn incorporates the value for the EMA value before that, and so on. Each previous EMA value accounts for a small portion of the current value. Therefore, the current EMA value will change depending on how much past data you use in your EMA calculation. Ideally, for a 100% accurate EMA, you should use every data point the stock has ever had in calculating the EMA, starting your calculations from the first day the stock existed. This is not always practical, but the more data points you use, the more accurate your EMA will be. The goal is to maximize accuracy while minimizing calculation time.

The spreadsheet example below goes back 30 periods. With only 30 data points incorporated in the EMA calculations, the 10-day EMA values in the spreadsheet are not very accurate. On our charts, we calculate back at least 250 periods (typically much further), resulting in EMA values that are accurate to within a fraction of a penny.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252F98aDF7coJF68qFQxwqA3%252Fmova-1-sprdsheet.png%3Falt%3Dmedia%26token%3D91db141c-73ea-420e-89ab-9fb06ef6a45d&width=768&dpr=3&quality=100&sign=0bfc47c0e66b2b748996a1d26d8d9d94&sv=3)

Click below to download this spreadsheet example.

[cs-movavg.xls](https://436553459-files.gitbook.io/~/files/v0/b/gitbook-x-prod.appspot.com/o/spaces%2FERtrZrZOhufFzk6ZQO4B%2Fuploads%2FGcimZKibMI6uQbVq7yPM%2Fcs-movavg.xls?alt=media&token=ca74c600-293d-41cd-963c-af3209453073)

30KB

Download [Open](https://436553459-files.gitbook.io/~/files/v0/b/gitbook-x-prod.appspot.com/o/spaces%2FERtrZrZOhufFzk6ZQO4B%2Fuploads%2FGcimZKibMI6uQbVq7yPM%2Fcs-movavg.xls?alt=media&token=ca74c600-293d-41cd-963c-af3209453073)

* * *

### Adjusting the Settings[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/moving-averages-simple-and-exponential\#adjusting_the_settings)

#### **Simple vs Exponential Moving Averages**[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/moving-averages-simple-and-exponential\#simple-vs-exponential-moving-averages)

When adding a moving average to your chart, deciding whether to use an exponential or a simple moving average is the first choice. Although clear differences exist between simple and exponential moving averages, one is not necessarily better. Choosing the right type of moving average depends on your trading objectives.

Exponential moving averages have less lag and are, therefore, more sensitive to recent prices and recent price changes. Exponential moving averages will turn before simple moving averages.

On the other hand, simple moving averages represent a true average of prices for the entire period. As such, simple moving averages may be better suited to identify [support](https://chartschool.stockcharts.com/table-of-contents/glossary/glossary-s#support) or [resistance](https://chartschool.stockcharts.com/table-of-contents/glossary/glossary-r#resistance) levels.

The chart below shows XLK with the 50-day SMA in red and the 50-day EMA in green. Both peaked in late February, but the decline in the EMA was sharper than the decline in the SMA. The EMA turned up in early April, but the SMA continued lower until the beginning of May. Notice that the SMA turned up over a month after the EMA.

![Chart from StockCharts.com shows the 50-day EMA declined more sharply than the 50-day SMA](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FzjBWjGIRLsULKHzSwE9i%252Fmova-3-xlksema.png%3Falt%3Dmedia%26token%3D4b1e6d64-5274-4d0e-ab87-db7d32cc8ecd&width=768&dpr=3&quality=100&sign=47b48ab0c9b88453227dc383949803e8&sv=3)

The decline in the 50-day EMA (green) was sharper than the 50-day SMA (red)

#### **Lengths and Timeframes**[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/moving-averages-simple-and-exponential\#lengths-and-timeframes)

The length of the moving average depends on the trader's time horizon and analytical objectives. Shorter moving averages (5-20 periods) are suitable for short-term trends and trading. Medium-term trends can be analyzed using longer moving averages (20-60 periods). Long-term investors often use moving averages with 100 or more periods.

Some moving average lengths are more popular than others. The 200-day moving average is perhaps the most popular. Because of its length, this is clearly a long-term moving average. Next, the 50-day moving average is quite popular for the medium-term trend. Many chartists use the 50-day and 200-day moving averages together. Short-term, a 10-day moving average was quite popular in the past because it was easy to calculate. One simply added the numbers and moved the decimal point.

#### **Base Data**[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/moving-averages-simple-and-exponential\#base-data)

Moving averages are typically based on price data, specifically closing price data. However, moving averages can be applied to other types of price data (open, high, or low), volume data, or even other indicators.

The example below shows a chart with a 50-day SMA applied to the volume bars and a 20-day EMA applied to the RSI indicator.

![Chart from StockCharts showing that moving averages can be applied to volume bars and indicators such as the RSI](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FLzHPH4gX60fR1CauumHN%252Fmova-indicatorma.png%3Falt%3Dmedia%26token%3D162f0408-d0d5-40e2-8193-33f2d679a4e9&width=768&dpr=3&quality=100&sign=4e12837fa0351314ada4997b8df4b965&sv=3)

Moving averages can be applied to volume bars and the RSI as shown here.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FM8bHBTieqVGCRCmVMIYB%252Fscc-icon.png%3Falt%3Dmedia%26token%3D34ef3915-ca84-44cd-b0ba-a8c136fb9a8f&width=40&dpr=3&quality=100&sign=fd7f826b0b5b67d7a4d39a6f4af26f0b&sv=3)[Click here for a live version of the chart.](https://stockcharts.com/sc3/ui/?s=XLY&p=D&b=5&g=0&id=p23744900229&a=1187769032)

* * *

## Interpreting Moving Averages[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/moving-averages-simple-and-exponential\#interpreting_moving_averages)

Moving averages can be used to identify the trend, as well as support and resistance levels. Crossovers with price or with another moving average can provide trading signals. Chartists may also create a Moving Average Ribbon with more than one moving average to analyze the interaction between multiple MAs at once.

### Identifying Trends[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/moving-averages-simple-and-exponential\#how_do_you_identify_a_trend_using_moving_averages)

The direction of the moving average conveys important information about prices, whether that average is simple or exponential. A rising moving average shows that prices are generally increasing. A falling moving average indicates that prices, on average, are falling. A rising long-term moving average reflects a long-term uptrend. A falling long-term moving average reflects a long-term downtrend.

The chart below shows 3M (MMM) with a 150-day exponential moving average. You can see that moving averages are very effective during strong trends.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FegTtfYSlKJwAcSuQ91cQ%252Fmova-4-mmmturn.png%3Falt%3Dmedia%26token%3Da76d88a2-7fc2-4ccd-95e0-6b336b4647c7&width=768&dpr=3&quality=100&sign=8d4b4dd8d612da8db4b068b27b04446c&sv=3)

The chart shows that moving averages are effective during strong trends.

The 150-day EMA turned lower in November 2007 and again in January 2008. Notice that it took a 15% decline to reverse the direction of this moving average. These lagging indicators identify trend reversals as they occur (at best) or after they occur (at worst). MMM continued lower into March 2009 and then surged 40-50%. Notice that the 150-day EMA did not turn up until after this surge. Once it did, however, MMM continued higher the next 12 months. Moving averages work brilliantly in strong trends.

### Generating Trading Signals[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/moving-averages-simple-and-exponential\#generating-trading-signals)

Moving averages can be used to generate trading signals. One of the most basic techniques is that of using crossovers. For example, a bullish crossover occurs when a shorter moving average crosses above a longer moving average, indicating a potential buying opportunity. A bearish crossover occurs when a shorter moving average crosses below a longer moving average, indicating a potential selling opportunity. Similarly, a crossover can occur when price crosses above or below a moving average.

#### Double Moving Average Crossovers[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/moving-averages-simple-and-exponential\#how_do_you_read_a_double_moving_average_crossover)

Two moving averages can be used together to generate crossover signals. In [_Technical Analysis of the Financial Markets_](https://store.stockcharts.com/products/technical-analysis-of-the-financial-markets-1), John Murphy calls this the “double crossover method”. Double crossovers involve one relatively short moving average and one relatively long moving average. As with all moving averages, the general length of the moving average defines the timeframe for the system. A system using a 5-day EMA and a 35-day EMA would be deemed short-term. A system using a 50-day SMA and 200-day SMA would be deemed medium-term, perhaps even long-term.

A bullish crossover occurs when the shorter moving average crosses above the longer moving average. This is also known as a golden cross. A bearish crossover occurs when the shorter moving average crosses below the longer moving average. This is known as a death cross (sometimes called a “dead cross”).

Moving average crossovers produce relatively late signals. After all, the system employs two lagging indicators. The longer the moving average periods, the greater the lag in the signals. These signals work great when a good trend takes hold. However, when there's no strong trend, a moving average crossover system will produce many whipsaws.

There is also a triple crossover method that involves three moving averages. Again, a signal is generated when the shortest moving average crosses the two longer moving averages. A simple triple crossover system might involve 5-day, 10-day, and 20-day moving averages.

The chart below shows Home Depot (HD) with a 10-day EMA (green dotted line) and 50-day EMA (red line). The black line is the daily close.

![Chart from StockCharts.com showing moving average crossovers of a 10-day EMA and 50-day EMA](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252F3LKpdRV5y7y0dvs5ouQa%252Fmova-5-hdcross.png%3Falt%3Dmedia%26token%3D8e161360-a0f8-4501-b043-c972d91548f5&width=768&dpr=3&quality=100&sign=a874dd3c28ecfbb1d009ed6e233454e7&sv=3)

Example of moving average crossovers.

A moving average crossover would have resulted in three whipsaws before catching a good trade. The 10-day EMA broke below the 50-day EMA in late October (1), but this did not last long as the 10-day moved back above in mid-November (2). This cross lasted longer, but the next bearish crossover in January (3) occurred near late November price levels, resulting in another whipsaw. This bearish cross did not last long, as the 10-day EMA moved back above the 50-day a few days later (4). After three bad signals, the fourth signal foreshadowed a strong move as the stock advanced over 20%.

There are two important takeaways from this example. First, crossovers are prone to whipsaw. A price or time filter can be applied to help prevent whipsaws. Traders might require the crossover to last three days before acting or require the 10-day EMA to move above/below the 50-day EMA by a certain amount before acting.

Second, MACD can be used to identify and quantify these crossovers. MACD (10,50,1) will show a line representing the difference between the two exponential moving averages. MACD turns positive during a golden cross and negative during a death cross. The Percentage Price Oscillator (PPO) can be used the same way to show percentage differences. Note that MACD and the PPO are based on exponential moving averages and will not match up with simple moving averages.

The chart below shows Oracle (ORCL) with the 50-day EMA, 200-day EMA, and MACD(50,200,1).

![Chart from StockCharts.com showing that adding a MACD indicator can help to quantify EMA crossovers](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FrOSXa4VrtEydszI6V8np%252Fmova-6-orclcross.png%3Falt%3Dmedia%26token%3D8d7146bf-d363-413d-b138-abcf5021bb86&width=768&dpr=3&quality=100&sign=f38aa185897ab99f73d74945726a39a5&sv=3)

Adding the MACD indicator to a chart can help to quantify EMA crossovers.

There were four moving average crossovers over a two-and-a-half-year period. The first three resulted in whipsaws or bad trades. A sustained trend began with the fourth crossover as ORCL advanced to the mid-20s. Once again, moving average crossovers work great when the trend is strong but when there's no strong trend, they can result in whipsaws.

#### Price Crossovers[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/moving-averages-simple-and-exponential\#how_do_you_interpret_price_crossing_a_moving_average)

Moving averages can also be used to generate signals with simple price crossovers. A bullish signal is generated when prices move above the moving average. A bearish signal is generated when prices move below the moving average. Price crossovers can be combined to trade within the bigger trend. The longer moving average sets the tone for the bigger trend, and the shorter moving average generates the signals. You would look for bullish price crosses only when prices are already above the longer moving average. This would be trading in harmony with the bigger trend. For example, if price is above the 200-day moving average, chartists would only focus on signals when price moves above the 50-day moving average. A move below the 50-day moving average would precede such a signal, but such bearish crosses would be ignored because the bigger trend is up. A bearish cross would simply suggest a pullback within a bigger uptrend. A cross back above the 50-day moving average would signal an upturn in prices and a continuation of the bigger uptrend.

The next chart shows Emerson Electric (EMR) with the 50-day EMA and 200-day EMA. The stock crossed and held above the 200-day moving average in August. There were dips below the 50-day EMA in early November and again in early February. Prices quickly moved back above the 50-day EMA to provide bullish signals (green arrows) in harmony with the bigger uptrend. MACD(1,50,1) is shown in the indicator window to confirm price crosses above or below the 50-day EMA. The 1-day EMA equals the closing price. MACD(1,50,1) is positive when the close is above the 50-day EMA and negative when the close is below the 50-day EMA.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FgjUGnvF8pJsxFR3RNl2W%252Fmova-7-emrpricex.png%3Falt%3Dmedia%26token%3Dbdc6d359-1ff8-48ce-8895-acf10650e6a9&width=768&dpr=3&quality=100&sign=faf43425c61f1a2f41adf69ee53b18bc&sv=3)

**Learn More:** [How To Trade Price-to-Moving Average Crossovers](https://chartschool.stockcharts.com/table-of-contents/trading-strategies-and-models/trading-strategies/moving-average-trading-strategies/how-to-trade-price-to-moving-average-crossovers)

* * *

### Identifying Support and Resistance[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/moving-averages-simple-and-exponential\#can_moving_averages_be_used_to_identify_support_and_resistance)

Moving averages can also act as support in an uptrend and resistance in a downtrend. A short-term uptrend might find support near the 20-day simple moving average, also used in Bollinger Bands. A long-term uptrend might find support near the 200-day simple moving average, the most popular long-term moving average. The 200-day moving average may offer support or resistance because it's widely used. It is almost like a self-fulfilling prophecy.

The chart below shows the NY Composite with the 200-day simple moving average from mid-2004 until the end of 2008. The 200-day provided support numerous times during the advance. Once the trend reversed with a double top support break, the 200-day moving average acted as resistance around 9500.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FowtwdZWWnvzKMnzlCIC8%252Fmova-8-nyasupp.png%3Falt%3Dmedia%26token%3D502bc5e1-ab20-493f-8879-54ba1b1de895&width=768&dpr=3&quality=100&sign=3d9a9c6e7381f946fb59d07d7adfca83&sv=3)

Do not expect exact support and resistance levels from moving averages, especially longer moving averages. Markets are driven by emotion, which makes them prone to overshoots. Instead of exact levels, moving averages can be used to identify support or resistance _**zones**_.

**Learn More:** [Support and Resistance](https://chartschool.stockcharts.com/table-of-contents/chart-analysis/support-and-resistance) \| [Finding Support and Resistance in Moving Averages](https://chartschool.stockcharts.com/table-of-contents/trading-strategies-and-models/trading-strategies/moving-average-trading-strategies/finding-support-and-resistance-in-moving-averages)

* * *

## The Bottom Line[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/moving-averages-simple-and-exponential\#the_bottom_line)

The advantages of using moving averages need to be weighed against the disadvantages. Moving averages are trend-following, or lagging, indicators that will always be a step behind. This isn't necessarily a bad thing, though. After all, the trend is your friend, and it's best to trade in the direction of the trend. Moving averages ensure that a trader is in line with the current trend. Even though the trend is your friend, securities spend much time in trading ranges, which renders moving averages ineffective. Once in a trend, moving averages will keep you in but also give late signals. Don't expect to sell at the top and buy at the bottom using moving averages.

As with most technical analysis tools, moving averages should not be used alone, but in conjunction with other complementary tools. For example, chartists can use moving averages to define the overall trend and then use RSI to define [overbought](https://chartschool.stockcharts.com/table-of-contents/glossary/glossary-o#overbought) or [oversold](https://chartschool.stockcharts.com/table-of-contents/glossary/glossary-o#oversold) levels.

* * *

## Charting with Moving Averages[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/moving-averages-simple-and-exponential\#charting_with_moving_averages)

The Moving Average overlays (Simple and Exponential) can be added to SharpCharts and ACP Charts. The Simple Moving Average overlay can also be added to P&F Charts.

### Using with SharpCharts[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/moving-averages-simple-and-exponential\#using_with_sharpcharts)

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FLFYiaS4qwec34vwB7usI%252Fmova-shch.png%3Falt%3Dmedia%26token%3D8aecf191-4e66-4ba1-a516-e4fae1d668b7&width=768&dpr=3&quality=100&sign=563bb55680202db6590b87aaa573fe36&sv=3)

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FM8bHBTieqVGCRCmVMIYB%252Fscc-icon.png%3Falt%3Dmedia%26token%3D34ef3915-ca84-44cd-b0ba-a8c136fb9a8f&width=40&dpr=3&quality=100&sign=fd7f826b0b5b67d7a4d39a6f4af26f0b&sv=3)[Click here for a live version of this chart.](https://stockcharts.com/sc3/ui/?s=%24COMPQ&p=D&b=5&g=0&id=p05000127365&a=1184644471)

* * *

Moving averages are available in SharpCharts as a price overlay. Users can choose either a simple moving average or an exponential moving average using the Overlays drop-down menu. There are several settings parameters allowed for moving averages, but only the first one is required:

- The first parameter sets the number of periods. By default, the Simple Moving Average overlay is set to 50 periods, and the Exponential Moving Average overlay is set to 20 periods. However, these settings can be changed to fit your trading needs.

- An optional parameter can be added to specify which price field should be used in the calculations—“O” for the Open, “H” for the High, “L” for the Low, and “C” for the Close. A comma separates parameters. If this parameter is unspecified, the Close is used by default.

- Another optional parameter can be added to shift the moving averages to the left (past) or right (future). A negative number (-10) would shift the moving average to the left ten periods. A positive number (10) would shift the moving average to the right 10 periods.


To overlay multiple moving averages on a price chart, add another overlay line in the Overlays section of SharpCharts. StockCharts members can change the colors and style to differentiate between multiple moving averages. Note: If the style and color settings are not visible, click the green triangle to expand Advanced Options.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FqwionK4vi1I8UlNfh6v4%252Fmova-10-shch.png%3Falt%3Dmedia%26token%3D2993e902-52fa-49f7-a110-7c0be404a2fc&width=768&dpr=3&quality=100&sign=7b00ae974dbefcde199761c25e12b3b7&sv=3)

SharpChart settings for moving averages.

Moving average overlays can also be added to other technical indicators, such as RSI, CCI, and Volume. To do this, select Simple Moving Avg or Exp. Moving Avg from the Overlay dropdown menu adjacent to the indicator.

**Learn More:** For more details on the parameters used to configure Moving Average overlays, please see our [SharpCharts Parameter Reference](https://help.stockcharts.com/charts-and-tools/sharpcharts/sharpcharts-workbench/editing-sharpcharts/sharpcharts-parameter-reference#simple_moving_average_sma-1) in the Support Center.

### Using with StockChartsACP[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/moving-averages-simple-and-exponential\#using_with_stockchartsacp)

Simple and Exponential Moving Average overlays can be added from the Chart Settings panel for your StockChartsACP chart. Moving Averages can be overlaid on the security's price plot or an indicator panel.

![Chart from StockChartsACP with moving averages overlaid on price chart](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252Fucfx1Q7HhWxYda0psUWa%252Fmova-acp.png%3Falt%3Dmedia%26token%3D6a678a31-1c57-4c31-be39-d181d0814184&width=768&dpr=3&quality=100&sign=053122c3624e60e715454469520498ee&sv=3)

Example of charting SMA and EMA with StockChartsACP.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FM8bHBTieqVGCRCmVMIYB%252Fscc-icon.png%3Falt%3Dmedia%26token%3D34ef3915-ca84-44cd-b0ba-a8c136fb9a8f&width=40&dpr=3&quality=100&sign=fd7f826b0b5b67d7a4d39a6f4af26f0b&sv=3)[Click here for a live version of this chart.](https://schrts.co/CQPZsTnI)

* * *

Both moving average overlays use 20 periods by default, but this parameter can be adjusted to meet your technical analysis needs. Use the offset field to shift the moving average the specified number of periods to the left (past) or right (future). To calculate the moving average using data other than the close, use the Calculated From field; this can be set to use the Open, High, Low, Volume, or other indicators on the chart.

### Using With P&F Charts[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/moving-averages-simple-and-exponential\#using_with_p_f_charts)

Simple Moving Averages can also be overlaid on P&F charts. This overlay is available in the Overlays section on the P&F Workbench.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FIa3ZSj9JAU1bcMhHjuOP%252Fmova-pnf.png%3Falt%3Dmedia%26token%3D4fcd1e7c-9c18-4d55-b5c6-98c0cf7b8527&width=768&dpr=3&quality=100&sign=5ddf2183d8e3ec511e30b44143267ea0&sv=3)

Overlaying a Simple Moving Average on a P&F chart.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FM8bHBTieqVGCRCmVMIYB%252Fscc-icon.png%3Falt%3Dmedia%26token%3D34ef3915-ca84-44cd-b0ba-a8c136fb9a8f&width=40&dpr=3&quality=100&sign=fd7f826b0b5b67d7a4d39a6f4af26f0b&sv=3)[Click here for a live version of this chart.](https://stockcharts.com/freecharts/pnf.php?c=CAT,PWTADANRNO[PB20][D][F1!3!!!2!20][J1187795594,Y]&listNum=8)

* * *

By default, 20 periods are used to calculate the Simple Moving Average. However, since P&F moving averages are double-smoothed, a shorter moving average may be preferred when placing this overlay on a P&F chart.

**Learn More:** [Moving Averages on P&F Charts](https://chartschool.stockcharts.com/table-of-contents/chart-analysis/point-and-figure-charts/point-and-figure-indicators#moving_averages)

* * *

## Scanning for Moving Averages[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/moving-averages-simple-and-exponential\#scanning_for_moving_averages)

StockCharts members can search for stocks based on Moving Average values. Below are some example scans that can be used for Moving Average-based signals. Simply copy the scan text and paste it into the Scan Criteria box in the [Advanced Scan Workbench](https://stockcharts.com/def/servlet/ScanUI).

Members can also set up alerts to notify them when a Moving Average-based signal is triggered for a stock. Alerts use the same syntax as scans, so the sample scans below can be used as a starting point for setting up alerts as well. Simply copy the scan text and paste it into the Alert Criteria box in the [Technical Alert Workbench](https://stockcharts.com/h-al/al).

### Bullish Moving Average Cross[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/moving-averages-simple-and-exponential\#bullish_moving_average_cross)

This scan looks for stocks with a rising 150-day simple moving average and a bullish cross of the 5-day EMA and 35-day EMA. The 150-day moving average is rising as long as it is trading above its level five days ago. A bullish cross occurs when the 5-day EMA moves above the 35-day EMA on above-average volume.

Copy

```
[type = stock] AND [country = US]
AND [SMA(20,Volume) > 40000]
AND [SMA(60,Close) > 20]

AND [SMA(150,Close) > 5 days ago SMA(150,Close)]
AND [EMA(5,Close) > EMA(35,Close)]
AND [Yesterday's EMA(5,Close) < Yesterday's EMA(35,Close)]
AND [Volume > SMA(200,Volume)]
```

### Bearish Moving Average Cross[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/moving-averages-simple-and-exponential\#bearish_moving_average_cross)

This scan looks for stocks with a falling 150-day simple moving average and a bearish cross of the 5-day EMA and 35-day EMA. The 150-day moving average is falling as long as it is trading below its level five days ago. A bearish cross occurs when the 5-day EMA moves below the 35-day EMA on above-average volume.

Copy

```
[type = stock] AND [country = US]
AND [SMA(20,Volume) > 40000]
AND [SMA(60,Close) > 20]

AND [SMA(150,Close) < 5 days ago SMA(150,Close)]
AND [EMA(5,Close) < EMA(35,Close)]
AND [Yesterday's EMA(5,Close) > Yesterday's EMA(35,Close)]
AND [Volume > SMA(200,Volume)]
```

**Learn More:** For more details on the syntax for Moving Average scans, please see our [Scanning Indicator Reference](https://help.stockcharts.com/scanning-and-alerts/scan-writing-resource-center/scan-syntax-reference/scan-syntax-technical-indicators#moving_average) in the Support Center.

* * *

## Additional Resources[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/moving-averages-simple-and-exponential\#additional_resources)

### ChartSchool Articles[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/moving-averages-simple-and-exponential\#chartschool_articles)

[**Arthur Hill on Moving Average Crossovers**](https://chartschool.stockcharts.com/table-of-contents/overview/arthur-hill-on-moving-average-crossovers)
Learn about the limitations of using trading systems based solely on moving average crossovers.

### Recommended Books[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/moving-averages-simple-and-exponential\#recommended_books)

John Murphy's [_Technical Analysis of the Financial Markets_](https://a.co/d/1HCN6rx) contains a chapter devoted to moving averages, their various uses and their pros and cons. In addition, Murphy shows how moving averages work with Bollinger Bands and channel-based trading systems.

[PreviousLowest Low Value](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/lowest-low-value) [NextMoving Average Ribbon](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/moving-average-ribbon)

Last updated 8 hours ago

Was this helpful?

This site uses cookies to deliver its service and to analyze traffic. By browsing this site, you accept the [privacy policy](https://help.stockcharts.com/learning-more/policies-and-limitations/privacy-statement).

AcceptReject