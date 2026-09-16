<!-- source: https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/on-balance-volume-obv -->

For the complete documentation index, see [llms.txt](https://chartschool.stockcharts.com/llms.txt). This page is also available as [Markdown](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/on-balance-volume-obv.md).

## What Is On Balance Volume (OBV)?[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/on-balance-volume-obv\#what_is_on_balance_volume_obv)

The On Balance Volume (OBV) is an indicator that assesses a security's buying and selling pressure by analyzing cumulative volume. It adds volume on days when the price rises and subtracts it on days when the price declines.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FGovFGEjSdpSMo6r8Y7dl%252Fobvexample.png%3Falt%3Dmedia%26token%3D6c3e9f7c-ede6-422c-a752-2df40d0f3cd9&width=768&dpr=3&quality=100&sign=a2c5e29a386dff7197de5e3cf9805787&sv=3)

On Balance Volume smoothed with a 20-day EMA

OBV was originally developed by Joe Granville, and he first explained it in his 1963 book _Granville's New Key to Stock Market Profits_. The OBV is noteworthy because it was among the earliest metrics to track the inflow and outflow of volume. By comparing the OBV with price action, analysts can detect divergences that may forecast future price shifts, or they can use the OBV to confirm existing price trends.

## Calculating OBV[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/on-balance-volume-obv\#how_is_obv_calculated)

The On Balance Volume (OBV) line is simply a running total of positive and negative volume. A period's volume is positive when the close is above the prior close and is negative when the close is below the prior close.

Copy

```

If the closing price is above the prior close price then:
Current OBV = Previous OBV + Current Volume

If the closing price is below the prior close price then:
Current OBV = Previous OBV  -  Current Volume

If the closing prices equals the prior close price then:
Current OBV = Previous OBV (no change)
```

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FvCzz2ER90GyBprZOqwjr%252Fobv-2-wmtxls.png%3Falt%3Dmedia%26token%3D118d777e-bd7c-4311-a415-50b4c9507c05&width=768&dpr=3&quality=100&sign=7951c0334f2aeb9eb928bb8a1cdd086d&sv=3)

On Balance Volume calculation example

In the table above, volume figures were rounded off and are shown in 1000's. In other words, 8,200 really equals 8,200,000 or 8.2 million shares. First, we must determine if the stock closed up (+1) or down (-1). This number is now used as the volume multiplier to compute positive or negative volume. The last column (OBV) forms the running total for positive/negative volume. Because OBV has to start somewhere, the first value (8200) is simply equal to the first period's positive/negative volume. The chart below shows the stock price with volume and OBV.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FpODzEuUP4zb6gKgoD1vD%252Fobv-1-wmtexam.png%3Falt%3Dmedia%26token%3Dc2a6adda-097d-4386-ba49-f8c352fd48ae&width=768&dpr=3&quality=100&sign=e0e519ab9a6861ba05d49bb894a67476&sv=3)

On Balance Volume rises on up days and drops on down days

**Note:** The scale of OBV is not relevant, and is not even shown on SharpCharts. Instead, chartists look at whether the OBV line is up or down compared to previous trading periods.

## Interpreting OBV[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/on-balance-volume-obv\#how_do_you_interpret_obv)

Granville theorized that volume precedes price. OBV rises when volume on up days outpaces volume on down days. OBV falls when volume on down days is stronger. A rising OBV reflects positive volume pressure that can lead to higher prices. Conversely, falling OBV reflects negative volume pressure that can foreshadow lower prices. Granville noted in his research that OBV would often move before price. Expect prices to move higher if OBV is rising while prices are either flat or moving down. Expect prices to move lower if OBV is falling while prices are either flat or moving up.

The absolute value of OBV is not important. Chartists should instead focus on the characteristics of the OBV line. First, define the trend for OBV. Second, determine if the current trend matches the trend for the underlying security. Third, look for potential support or resistance levels. Once broken, the trend for OBV will change and these breaks can be used to generate signals. Also, notice that OBV is based on closing prices. Therefore, closing prices should be considered when looking for divergences or support/resistance breaks. Finally, volume spikes can sometimes throw off the indicator by causing a sharp move that will require a settling period.

### Divergences[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/on-balance-volume-obv\#how_do_you_read_obv_divergences)

Bullish and [bearish divergence](https://chartschool.stockcharts.com/table-of-contents/glossary/glossary-b#bearish_divergence) signals can be used to anticipate a trend reversal. These signals are truly based on the theory that volume precedes prices. A bullish divergence forms when OBV moves higher or forms a higher low even as prices move lower or forge a lower low. A bearish divergence forms when OBV moves lower or forms a lower low even as prices move higher or forge a higher high. The divergence between OBV and price should alert chartists that a price reversal could be in the making.

The chart for Starbucks (SBUX) shows a [bullish divergence](https://chartschool.stockcharts.com/table-of-contents/glossary/glossary-b#bullish_divergence) forming in July. On the price chart, SBUX moved below its June low with a lower low in early July. OBV, on the other hand, held above its June low to form a bullish divergence. OBV went on to break resistance before SBUX broke resistance. This was a classic case of volume leading price. SBUX broke resistance a week later and continued above 20 for a 30+ percent gain. The second chart shows OBV moving higher as Texas Instruments (TXN) trades within a range. Rising OBV during a trading range indicates accumulation, which is bullish.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252Fococ0PB0Gt9LBBbNsong%252Fobv-4-sbuxbudd.png%3Falt%3Dmedia%26token%3D1dbf784b-32ca-458d-bb7c-627420c059df&width=768&dpr=3&quality=100&sign=f7a1d8c72e6b143281c2d91f996e833a&sv=3)

Bullish divergence with OBV

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FBWJRElgYgM21DdQsjr4Y%252Fobv-5-txnbudd.png%3Falt%3Dmedia%26token%3D11c471ac-711c-4d5b-9e1e-334dc2fead50&width=768&dpr=3&quality=100&sign=73e332289c12b3da70e5a03ae870a92d&sv=3)

Rising OBV during a trading range

The chart for Medtronic (MDT) shows a bearish divergence with volume leading price lower. The blue dotted lines identify the divergence period. MDT moved higher (43 to 45) as OBV moved lower. Also, notice that OBV broke support during this divergence period. The uptrend in OBV reversed with the break below the February low. MDT, on the other hand, was still moving higher. Volume ultimately won the day as MDT followed volume lower with a decline into the low 30s. The second chart shows Valero Energy (VLO) with OBV forming a bearish divergence in April and a confirming support break in May.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252F7a3jag3xj5lQJhUUCBpr%252Fobv-6-mdtbedd.png%3Falt%3Dmedia%26token%3D5cf0f223-8b61-4cff-9bb2-e83b01372e77&width=768&dpr=3&quality=100&sign=9c4375a231b49ffa66544c1926c297e8&sv=3)

Bearish divergence with OBV

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252F7jNG0a9upv5fzYc1oA4p%252Fobv-7-vlobedd.png%3Falt%3Dmedia%26token%3Df27e9cea-52b2-4074-be18-e3d96468e377&width=768&dpr=3&quality=100&sign=a74a47f8520c2929051392a913542cf8&sv=3)

Bearish divergence with OBV

### Trend Confirmation[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/on-balance-volume-obv\#how_do_you_use_obv_for_trend_confirmation)

OBV can be used to confirm a price trend, upside breakout or downside break. The chart for Best Buy (BBY) shows three confirming signals as well as confirmation of the price trend. OBV and BBY moved lower in December-January, higher from March to April, lower from May to August and higher from September to October. The trends in OBV matched the trend in BBY.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252Fp1QXmuBdZUKc2H4wg393%252Fobv-3-bbyconfirm.png%3Falt%3Dmedia%26token%3Dd8856620-5e35-410d-af97-ce3458f5093a&width=768&dpr=3&quality=100&sign=d4c976580c3edae179888908effcfab1&sv=3)

OBV confirming price trends

OBV also confirmed trend reversals in BBY. Notice how BBY broke its downtrend line in late February and OBV confirmed with a resistance breakout in March. BBY broke its uptrend line in late April and OBV confirmed with a support break in early May. BBY broke its downtrend line in early September and OBV confirmed with a trend line break a week later. These coincident signals indicated that positive and negative volume were in harmony with price.

Sometimes OBV moves step-for-step with the underlying security. In this case, OBV is confirming the strength of the underlying trend, be it down or up. The chart for Autozone (AZO) shows prices as a black line and OBV as a pink line. Both moved steadily higher from November 2009 until October 2010. Positive volume remained strong throughout the advance.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FA4RXKQEqahtPK2KqGs7W%252Fobv-8-azosteps.png%3Falt%3Dmedia%26token%3D2d127451-c113-4cbf-aeb2-f55c04a1b194&width=768&dpr=3&quality=100&sign=31af9e7742370446c98cad93e121922b&sv=3)

OBV overlaid on price helps confirm price trend

## The Bottom Line[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/on-balance-volume-obv\#the_bottom_line)

On Balance Volume (OBV) uses volume and price to measure buying and selling pressure. Buying pressure is evident when positive volume exceeds negative volume, and the OBV line rises. Selling pressure occurs when negative volume exceeds positive volume, and the OBV line falls. Analysts can use OBV to confirm the underlying trend or look for divergences that may foreshadow a price change. As with all indicators, it's important to use OBV in conjunction with other aspects of technical analysis. It's not a standalone indicator. OBV can be combined with basic [pattern analysis](https://chartschool.stockcharts.com/table-of-contents/chart-analysis/chart-patterns) or to confirm signals from [momentum oscillators](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/introduction-to-technical-indicators-and-oscillators#momentum_oscillators).

* * *

## Charting with OBV[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/on-balance-volume-obv\#using_with_sharpcharts)

### Using with SharpCharts[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/on-balance-volume-obv\#using_with_sharpcharts-1)

On Balance Volume (OBV) is available in SharpCharts as an indicator. After selecting, OBV can be positioned above, below or behind the price plot of the underlying security. Positioning it behind the plot makes it easy to compare OBV with the underlying security. Chartists can also add a [moving average](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/moving-averages-simple-and-exponential) or another overlay to OBV using the Overlay setting for the OBV indicator.

[Click here for a live version of this chart.](https://stockcharts.com/sc3/ui/?s=IBM&a=2266088106&p=D&b=5&g=0&id=p73480075647)

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FRq3XlqcnAllH7po1YJMx%252Fobv-9-ibmshch.png%3Falt%3Dmedia%26token%3D264f1e9f-0413-416f-8ce3-2add7613cf35&width=768&dpr=3&quality=100&sign=e1144f25b688033255da93d91df6ece3&sv=3)

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FPhxStEwChCyRDE1m17qg%252Fobv-10-shch.png%3Falt%3Dmedia%26token%3D5fdf89fe-83a1-4de2-a9c3-04f1978f07d6&width=768&dpr=3&quality=100&sign=cc84becbe5e3b6235d8001fdaf46baa7&sv=3)

SharpCharts Settings for On Balance Volume

**Learn More:** For more details on the parameters used to configure Mass Index indicators, please see our [SharpCharts Parameter Reference](https://help.stockcharts.com/charts-and-tools/sharpcharts/sharpcharts-workbench/editing-sharpcharts/sharpcharts-parameter-reference#on_balance_volume_obv) in the Support Center.

### Using with StockChartsACP[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/on-balance-volume-obv\#using-with-stockchartsacp)

This indicator can be added from the Chart Settings panel for your StockChartsACP chart. The indicator can be positioned above, below, or behind the security's price plot.

![](https://chartschool.stockcharts.com/~gitbook/image?url=https%3A%2F%2F436553459-files.gitbook.io%2F%7E%2Ffiles%2Fv0%2Fb%2Fgitbook-x-prod.appspot.com%2Fo%2Fspaces%252FERtrZrZOhufFzk6ZQO4B%252Fuploads%252FaKVF2UmUzzJqXYj5xB0D%252Fobvinacp.png%3Falt%3Dmedia%26token%3Da2a5b66f-8449-406c-ab4b-df9666550289&width=768&dpr=3&quality=100&sign=a6c183bb664f64836521ad1aece1b792&sv=3)

[Click here for a live version of the chart.](https://schrts.co/WkuWWNyB)

The indicator does not have any parameters, but the settings panel can be used to change the line style or to add an overlay to the indicator.

## Scanning for OBV[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/on-balance-volume-obv\#suggested_scans)

StockCharts members can search for stocks based on OBV values. Below are some example scans that can be used for OBV-based signals. Simply copy the scan text and paste it into the Scan Criteria box in the [Advanced Scan Workbench](https://stockcharts.com/def/servlet/ScanUI).

Members can also set up alerts to notify them when an OBV-based signal is triggered for a stock. Alerts use the same syntax as scans, so the sample scans below can be used as a starting point for setting up alerts as well. Simply copy the scan text and paste it into the Alert Criteria box in the [Technical Alert Workbench](https://stockcharts.com/h-al/al).

### Bullish Divergence in OBV and ADL[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/on-balance-volume-obv\#bullish_divergence_in_obv_and_adl)

This scan starts with a base of stocks that are averaging at least $10 in price and 100,000 daily volume over the last 60 days. Potential bullish divergences are found by looking for stocks where price is BELOW the 65-day SMA and 20-day SMA, but OBV and the Accumulation Distribution Line are ABOVE the 65-day SMA and 20-day SMA.

Copy

```
[type = stock] AND [country = US]
AND [Daily SMA(60,Daily Volume) > 100000]
AND [Daily SMA(60,Daily Close) > 10]

AND [Daily Close < Daily SMA(65,Daily Close)]
AND [Daily AccDist > Daily AccDist Signal (65)]
AND [Daily OBV > Daily OBV Signal(65)]
AND [Daily Close < Daily SMA(20,Daily Close)]
AND [Daily AccDist > Daily AccDist Signal (20)]
AND [Daily OBV > Daily OBV Signal(20)]
```

### Bearish divergence in OBV and ADL[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/on-balance-volume-obv\#bearish_divergence_in_obv_and_adl)

This scan starts with a base of stocks that are averaging at least $10 in price and 100,000 daily volume over the last 60 days. Potential bearish divergences are found by looking for stocks where price is ABOVE the 65-day SMA and 20-day SMA, but OBV and the Accumulation Distribution Line are BELOW the 65-day SMA and 20-day SMA.

Copy

```
[type = stock] AND [country = US]
AND [Daily SMA(60,Daily Volume) > 100000]
AND [Daily SMA(60,Daily Close) > 10]

AND [Daily Close > Daily SMA(65,Daily Close)]
AND [Daily AccDist < Daily AccDist Signal (65)]
AND [Daily OBV < Daily OBV Signal(65)]
AND [Daily Close > Daily SMA(20,Daily Close)]
AND [Daily AccDist < Daily AccDist Signal (20)]
AND [Daily OBV < Daily OBV Signal(20)]
```

**Learn More.** For more details on the syntax for OBV scans, please see our [Scanning Indicator Reference](https://help.stockcharts.com/scanning-and-alerts/scan-writing-resource-center/scan-syntax-reference/scan-syntax-technical-indicators#on_balance_volume_obv) in the Support Center.

**Note**: For scanning purposes, daily volume data is incomplete during the trading day. When running scans with volume-based indicators like OBV, base the scan on the “Last Market Close.” Examples of other volume-based indicators include Accumulation/Distribution, Chaikin Money Flow, and the PVO.

## Additional Resources[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/on-balance-volume-obv\#further_study)

### Recommended Books[Direct link to heading](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/on-balance-volume-obv\#recommended-books)

John Murphy's [_Technical Analysis of the Financial Markets_](https://a.co/d/1eLUbD7) covers it all with explanations that are simple and clear. Murphy covers all the major charts patterns and indicators, including OBV. A complete chapter is devoted to understanding volume and open interest.

[PreviousNegative Volume Index (NVI)](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/negative-volume-index-nvi) [NextPercentage Price Oscillator (PPO)](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/percentage-price-oscillator-ppo)

Last updated 1 day ago

Was this helpful?

This site uses cookies to deliver its service and to analyze traffic. By browsing this site, you accept the [privacy policy](https://help.stockcharts.com/learning-more/policies-and-limitations/privacy-statement).

AcceptReject