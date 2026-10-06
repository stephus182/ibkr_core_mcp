# Market-data conventions — what a bar is, by asset class and source

What `fetch_market_data` returns, what the exchange defines, and what TradingView draws — stated
per asset class and per source, each convention with its proof. **Nothing here is assumed**: a
row is either a measurement (dated, reproducible from the files named) or a sentence from the
source's own page (linked). Where neither exists, the row says *not established*.

Vocabulary, fixed by the operator on 2026-10-03: market data has **sessions**; a bar is
**stamped**; the stamp is the source's fact and is **kept as received**, never shifted,
re-dated or re-bucketed — what this package adds is the rule for reading it, stated beside the
stamp. **A session date is not a trade date**: trade dates belong to Flex statements and fills,
and the two words do not mix.

Research index: `claudia_ui/.firecrawl/market-data/SOURCES.md` (scrapes of 2026-09-23 and
2026-10-03, git-ignored); measurements:
`claudia_ui/docs/plans/2026-10-03-outside-rth-probe/` (probe, live check, witness) and
`claudia_ui/docs/plans/2026-09-25-subminute-probe/`. Operator decisions: claudia_ui's
`docs/project-status.md`, 2026-10-02/03.

---

## 1. Our own conventions (the toolkit)

| Convention | Rule | Proof / decision |
|---|---|---|
| Security type | IB's own `secType` codes. `fetch_market_data` offers `STK` (default, stated as `STK (by default)`) and `FUT`; the enum lists only what the tool serves and the handler refuses the rest, naming the offer. `IND`, `CASH`, `OPT`, `FOP`, `BOND` are not served yet | Operator 2026-10-03 (point 3); IBKR uses these codes as the `sectype` parameter and `secType` field across the Web API ([contracts reference](https://www.interactivebrokers.com/campus/ibkr-api-page/web-api-staging/#contracts), [secdef/search](https://www.interactivebrokers.com/docs/web-api/v1/endpoints/contract/search-contract-by-symbol)); resolvers are split by type: [`/trsrv/stocks`](https://www.interactivebrokers.com/campus/ibkr-api-page/web-api-staging/), [`/trsrv/futures`](https://www.interactivebrokers.com/docs/web-api/v1/endpoints/contract/security-future-by-symbol) |
| A futures root | Means the **front-month contract's own bars** — the earliest contract still tradeable (gaps #58/#71), decided at the time of the request. Before it became the front month the bars are its prints as a back month, thinner. `conid` pins one contract, expired ones included | Operator 2026-10-03 (point 1). Thin back-month prints: ESZ6 4,719 contracts on 2026-09-02 vs 1.4 million a month later (probe). No continuous series: IBKR, "Continuous Futures … can not be used … In the Web API" ([continuous futures](https://www.interactivebrokers.com/docs/general/contracts/futures/continuous-futures)) |
| Cache key | `SYMBOL_BAR_PERIOD_END_RTH|ALL` — the hours written both ways. A future is cached under **its own symbol** (`ESZ6`), never the root, so ESU6 and ESZ6 never share an entry and a roll produces a new key by itself. The manifest row records the listing (name, exchange, currency, conid, `root` for a future) and the hours | Operator 2026-10-03 (points 2 and 4); pre-2.2.0 cache flushed by the operator the same day |
| Hours | `outside_rth` explicit on every tool that reads the cache. Fetch default by type — `STK` false, `FUT` true; readers default false. Every result states the hours and why (`regular trading hours (by default for STK)`, `all trading hours (as given)`) | Operator 2026-10-03 (point 4): "always be explicit about everything"; defaults as given |
| Stamps | Kept as IBKR's. An all-hours futures series prints its stamps **as session opens, in ET**, with the reading rule; `add_indicators` says `last bar stamped … (its session open)`. Nothing computes a session date | Operator 2026-10-03: "keep IB stamp … should not be modified, only understood correctly by evidence and rules"; §3 for why a calendar cannot do it |
| Default end date | Today, stated (`ending 2026-10-03 (today, by default)`) | Operator 2026-10-02 ("a default must be stated") |
| The newest bar — no half candle | A bar is kept only once its period has ended **for a minute before the read** (`_SETTLE_SECONDS`, at the fetch; the readers inherit it). The result states the read time and names the bar not kept; a hit states when its bars were read. A daily bar is kept from the next morning. The live price is `get_market_snapshot`'s | Measured 2026-10-05: IBKR's newest bar is the one in progress, and a bar's last trades arrive 1–4 s after its end (`claudia_ui/docs/plans/2026-10-05-history-seams-probe/`); operator: "Do NOT attempt to make half candles", a hard-coded delay, "accuracy and precision is number one priority, speed is not" |
| Indicators on these bars | Computed with TradingView's settings, each printed on its line; the averages and bands read `hl2` by default, RSI and MACD `close`. A VWMA and the Volume Ratio weigh by IBKR's filtered volume; VWAP is printed for regular-hours intraday bars only | [`indicators-reference.md`](indicators-reference.md); operator 2026-10-05 |

---

## 2. US stocks and ETFs (`STK`)

### 2a. IBKR — what `/iserver/marketdata/history` returns

| Convention | Measured / stated | Proof |
|---|---|---|
| Regular-hours daily bar (`outsideRth=false`, our default) | Stamped **09:30 ET on the session's own date**; the regular-session OHLC | Probe 2026-10-03, AAPL `1m/1d` |
| All-hours daily bar (`outsideRth=true`) | Stamped **04:00 ET, same date**; **different OHLC on 20 of 20 days** — open, close, often high/low, always volume (2026-10-02: `333.26/334.54/330.61/333.69` regular vs `331.05/334.54/330.16/333.60` all hours). A regular-session daily bar **cannot be cut from an all-hours one** | Probe 2026-10-03 (`outside_rth_probe.out`) |
| Hourly, regular | Starts 09:30, 10:00 … 15:00 ET — 7 bars a day | Probe 2026-10-03, AAPL `5d/1h` |
| Hourly, all hours | 04:00 … 19:00 ET — 16 bars a day; "all" adds 04:00–09:00 and 16:00–19:00 | Same |
| What the flag means on IBKR's page | Documented only as a response field: "Defines if the market data returned was inside regular trading hours or not" — nothing on daily bars; the daily effect above is measured, not documented | [historical-market-data](https://www.interactivebrokers.com/docs/web-api/v1/endpoints/market-data/historical-market-data) (scraped 2026-10-03); parameter definitions with `outsideRth` default false: [OpenAPI v3](https://api.ibkr.com/gw/api/v3/api-docs) |
| Which venues | IBKR's US equity Level 1 subscriptions **are the SIP networks** — "NYSE (Network A/CTA)", "…ARCA, BATS, IEX… (Network B)", "NASDAQ (Network C/UTP)"; a smart-routed historical request needs subscriptions to all exchanges | [popular subscriptions](https://www.interactivebrokers.com/docs/general/market-data-subscriptions/popular-market-data-subscriptions/introduction), [subscriptions intro](https://www.interactivebrokers.com/docs/general/market-data-subscriptions/introduction), [TWS API historical data](https://interactivebrokers.github.io/tws-api/historical_data.html) |
| Volume is **filtered** | "Combo legs, block trades and derivative trades" are excluded; historical volume "will be lower than an unfiltered historical data feed" and generally lower than real-time daily volume. So it is **not** the consolidated figure | [historical data filtering](https://www.interactivebrokers.com/docs/tws-api/doc/market-data-historical/historical-data-limitations/historical-data-filtering), [historical bars](https://interactivebrokers.github.io/tws-api/historical_bars.html); the current synchronous-API page does not repeat it ([sync historical](https://www.interactivebrokers.com/docs/tws-api/doc/synchronous-api/historical-market-data)) |
| Native vs calculated volume | A **TWS display preference**, not a Web API one: "Prefer native volume — … will include delayed transactions, busts, late-reported trades and combos" / "Prefer calculated volume — updates with every tick, but may not include …"; vendors differ "primarily concerning block trades, combos and odd-lots" | [TWS display configuration](https://www.ibkrguides.com/traderworkstation/display-configuration.htm), [archived ticker row settings](https://www.interactivebrokers.co.uk/en/software/tws.bak/usersguidebook/configuretws/ticker_row_settings.htm), [IBKR FAQ 102546341](https://www.interactivebrokers.com/lib/cstools/faq/#/content/102546341) |
| Units | IBKR's page: `%v` is "actual volume/100". The core does not convert it. **Not witnessed** against the SIP figure | [history endpoint (campus mirror)](https://www.interactivebrokers.com/docs/web-api/v1/endpoints/market-data/historical-market-data); IBKR scaling volume by 100 elsewhere: [archived High/Low/Volume columns](https://www.interactivebrokers.co.uk/en/software/tws.bak/usersguidebook/thetradingwindow/high_low_volume.htm), [TWS API market data](https://interactivebrokers.github.io/tws-api/market_data.html) |
| Consolidation flag on quotes | Snapshot field 6509, second character `p` = "Consolidated — Market data is aggregated across multiple exchanges or venues". The core decodes the first character only (open item) | [get-md-snapshot](https://www.interactivebrokers.com/docs/web-api/api-reference/trading/trading-market-data/get-md-snapshot), [market data fields](https://www.interactivebrokers.com/docs/web-api/v1/endpoints/market-data/market-data-fields) |
| Changelog | No entry on volume units or a default exchange | [Web API changelog](https://www.interactivebrokers.com/docs/web-api/changelog) |

### 2b. The exchange side — the consolidated tape

| Convention | Stated | Proof |
|---|---|---|
| Who produces consolidated volume | The **SIPs**: CTA (Tapes A/B) and UTP (Tape C). Aggregating vendors redistribute it. A single exchange's site is **not** consolidated (operator rule, 2026-09-23) | [CTA plan](https://www.ctaplan.com/publicdocs/ctaplan/CTS_Pillar_Output_Specification.pdf), [UTP plan](https://www.utpplan.com/DOC/UtpBinaryOutputSpec.pdf) |
| What updates consolidated volume | CTA sale-condition matrix: odd lot `I`, average price `B`, extended hours `T`/`U`, contingent `V`, QCT `7`, derivatively priced `4` all **update volume**; only `M`/`Q` (official close/open) and `9` (corrected close) do not. UTP: the same principle (§3.14.2) and its own `totalConsVolume` message, "as reported by all UTP participants" | [CTS Pillar output spec](https://www.ctaplan.com/publicdocs/ctaplan/CTS_Pillar_Output_Specification.pdf) (≈ line 2380 of the scrape), [UTP binary output spec](https://www.utpplan.com/DOC/UtpBinaryOutputSpec.pdf) (≈ lines 1380, 1889) |
| Odd lots | CTA: odd lots in consolidated volume | [CTA odd-lots FAQ](https://www.ctaplan.com/publicdocs/ctaplan/CTA_Odd_Lots_Changes_FAQ.pdf); UTP data policies: [datapolicies.pdf](https://www.utpplan.com/DOC/datapolicies.pdf); trader notices [UTP2025-10](https://www.nasdaqtrader.com/TraderNews.aspx?id=UTP2025-10), [dtn2013-34](https://nasdaqtrader.com/TraderNews.aspx?id=dtn2013-34) (body not captured) |
| The partial-coverage trap | Nasdaq Last Sale = "all securities traded in Nasdaq systems and the FINRA/Nasdaq TRF" — Nasdaq venues plus one off-exchange facility, not NYSE/Arca/Cboe/IEX or the other TRFs. Nasdaq.com's historical page is one exchange group's. Yahoo: dropped entirely (not professional) | [Nasdaq Last Sale](https://www.nasdaq.com/products/data/equities/nasdaq-last-sale), [Nasdaq historical](https://www.nasdaq.com/market-activity/quotes/historical); not scraped: [SEC 34-105779](https://www.sec.gov/files/rules/sro/nms/2026/34-105779.pdf) |
| Vendor survey | IBKR's quant-news article is a generic vendor survey, nothing on IBKR's own volume source | [historical market data sources](https://www.interactivebrokers.com/campus/ibkr-quant-news/historical-market-data-sources/) |

### 2c. TradingView

Not witnessed for stocks. Nothing is claimed.

---

## 3. Futures (`FUT`) — CME Group (CME and NYMEX measured)

### 3a. IBKR — what `/iserver/marketdata/history` returns

| Convention | Measured / stated | Proof |
|---|---|---|
| All-hours daily bar (`outsideRth=true`, our default for FUT) | The full electronic session, **stamped at the session open — 18:00 ET the evening before**. The bar stamped Thursday 18:00 is **Friday's session**; Sunday's stamp is Monday's session. 21 bars for `1m` where the day session gives 20 (one more session at the start of the window) | Probe 2026-10-03, ESZ6 `1m/1d`; live check CLX6 `3m/1d` (64 bars, 2026-07-02 18:00 → 10-01 18:00) |
| Regular-hours daily bar (`outsideRth=false`) | The day session, **stamped 09:30 ET on the session's own date**. Its **close is the same print as the all-hours close** (ES 19 of 19 sessions; CL 3 of 3) — IBKR's "regular hours" for both run to the 17:00 close; open, high/low and volume differ | Probe 2026-10-03 (ESZ6); live check 2026-10-03 (CLX6: 63 bars, 2026-07-07 → 10-02) |
| A CME holiday session | **One bar**: Sunday 2026-09-06 18:00's stamp covers through Tuesday 09-08 17:00 (Labor Day); **no Monday bar in either series**; the day-session series has no 09-07 bar and its 09-08 bar matches the Sunday-stamped all-hours bar's close and low | Probe 2026-10-03 |
| Hourly, all hours | Starts 00:00 … 23:00 ET, **no 17:00 bar** (the maintenance break) — 23 start times, 115 bars over 6 ET days for `5d` | Probe 2026-10-03, ESZ6 `5d/1h` |
| Hourly, regular | Starts 09:30, 10:00 … 16:00 ET — 8 bars a day | Same |
| Why no session date is computed | IBKR puts **no session date on a bar**. A calendar library dates the holiday bar wrong: `exchange_calendars` ("CMES") lists 2026-09-07 as a session, so "the next session after the stamp" gives 09-07 where IBKR's own series says 09-08. A fixed duration fails the same way (that session ran 47 hours). The stamp is kept and the rule stated | Probe 2026-10-03 (second script in the session record) |
| Contract identity | `/iserver/contract/{conid}/info` gives `local_symbol` (ESZ6), `contract_month`, `maturity_date`, `company_name`, `exchange`, `multiplier`; `/trsrv/futures` lists a root's contracts with `expirationDate` and `ltd`, **including ones past their last trade date** (gap #58). ES: `ltd` is the earlier date; NYMEX energy (CL, NG): `ltd` is the first day of the contract month, after trading stopped (gap #71) — hence "earliest of the two" | [get-instrument-info](https://www.interactivebrokers.com/docs/web-api/api-reference/trading/trading-contracts/get-instrument-info), [security-future-by-symbol](https://www.interactivebrokers.com/docs/web-api/v1/endpoints/contract/security-future-by-symbol); measurements 2026-09-20, 09-24, 09-29 in claudia_ui's status file |
| Expired contracts | IBKR's page (TWS API `IncludeExpired`): historical data "for contracts that have expired within the last 2 years". **Measured through the Web API 2026-09-25:** ESU5 served 12 months after expiry, ESM5 **refused** at 15 ("Contract details are not available") — the practical window is about a year; the boundary between 12 and 15 months is not established. 2026-10-03: ESU6 (expired 09-18) served 63 bars to 09-17 18:00 | [expired futures](https://www.interactivebrokers.com/docs/general/contracts/futures/expired-futures); `claudia_ui/docs/plans/2026-09-25-subminute-probe/`; live check 2026-10-03 |
| Volume | **Filtered**, as for stocks (no block trades, combos, derivative-priced trades). In **contracts**, 1:1 with TradingView's ES figure (1,762,000 vs 1.76M). The gap on CL (§3c) is the off-screen share, **not an error**, and the tool description says so | [historical data filtering](https://www.interactivebrokers.com/docs/tws-api/doc/market-data-historical/historical-data-limitations/historical-data-filtering); witness 2026-10-03 |
| Sub-minute bars | `bar=1S` (uppercase) returns genuine 1-second bars (re-measured 2026-10-05: 300 for five minutes, `barLength: 1`); `t` on them is 60 s apart (the last reads 18:53:59 ET for a true 13:59:58); lowercase `1s` → HTTP 500. **Refused by this package with that reason**, at the client and the tool, before any request: no stamp is changed (operator, 2026-10-05) — register F22; a study-database question for later | `claudia_ui/docs/plans/2026-09-25-subminute-probe/`; [OpenAPI v3](https://api.ibkr.com/gw/api/v3/api-docs) lists `S` |
| Not measured | Weekly and monthly stamps; other roots' session open hours; a holiday that falls on a Friday | — |

### 3b. The exchange side — CME Group

| Convention | Stated | Proof |
|---|---|---|
| ES trading hours (CME's own words) | "CME Globex: Sunday 6:00 p.m. – Friday 5:00 p.m. ET … with a daily maintenance period from 5:00 p.m. – 6:00 p.m. ET"; CME ClearPort Sunday 6:00 p.m. – Friday 6:45 p.m. ET. Trading terminates 9:30 a.m. ET on the 3rd Friday of the contract month | [ES contract specs](https://www.cmegroup.com/markets/equities/sp/e-mini-sandp500.contractSpecs.html) (scraped 2026-09-10) |
| CL trading hours | "CME Globex: Sunday – Friday 5:00 p.m. – 4:00 p.m. CT with a 60-minute break each day beginning at 4:00 p.m. CT" (= 18:00 – 17:00 ET); TAS Sunday – Friday 5:00 p.m. – 1:30 p.m. CT; ClearPort Sunday 5:00 p.m. – Friday 4:00 p.m. CT. Trading terminates 3 business days before the 25th of the month before the contract month | [CL contract specs](https://www.cmegroup.com/markets/energy/crude-oil/light-sweet-crude.contractSpecs.html) (scraped 2026-09-10) |
| What IBKR's stamps show of those hours | The all-hours hourly series has every start time but 17:00 — CME's maintenance hour; the all-hours daily stamp of 18:00 ET is the Globex open. IBKR's "regular hours" (09:30 → 17:00 close) are IBKR's definition, not CME's; CME defines no "regular" session for Globex products | Probe 2026-10-03 against the specs above |
| No consolidated tape | Futures trade on one exchange; **the exchange is the source**. CME's daily volume = **Globex + Open Outcry + ClearPort/PNT**, reported per division (CME, CBOT, NYMEX, COMEX) | [exchange volume](https://www.cmegroup.com/market-data/browse-data/exchange-volume.html) |
| Block trades | Submitted via CME Direct or CME ClearPort; "Block trade prices are published separately from transactions in the regular market. Block trade volume is also identified in the daily volume reports published by the Exchange" (Rule 526 §A0) | [block trades](https://www.cmegroup.com/clearing/trading-practices/block-trades.html), [Rule 526](https://www.cmegroup.com/rulebook/files/cme-group-Rule-526.pdf) |
| EFRPs | "The futures leg of the EFRP is reported to the Exchange and is cleared by CME Clearing"; the cash leg is not reported | [understanding EFRP transactions](https://www.cmegroup.com/education/articles-and-reports/understanding-efrp-transactions) |
| Holiday sessions | The Labor Day 2026 Globex session was one bar in IBKR's series, Sunday open through Tuesday close (§3a). CME's product-group holiday hours: [holiday calendar](https://www.cmegroup.com/tools-information/holiday-calendar.html) (the core's `futures["holiday_schedule_today"]` points there; measured on CME's own page 2026-10-02 for the calendar work, register F18) | Probe 2026-10-03; F18 |

### 3c. TradingView (the operator's chart, the out-of-band witness)

| Convention | Witnessed | Proof |
|---|---|---|
| Session | Charts set to **ETH** (electronic trading hours) — the comparison for our all-hours series | Operator's screenshots 2026-10-03 (footer `ETH`); figures in `WITNESS.md`, screenshots not kept |
| Daily bar date | TradingView dates the bar **by the session**: its bar dated **Fri 02 Oct '26** is IBKR's bar **stamped Thu 2026-10-01 18:00 ET** | Same |
| ES prices | `ES1!`/CME Fri 02 Oct: O 7,724.00 H 7,810.25 L 7,723.25 C 7,777.25 — IBKR's Thursday-stamped bar 7724.0 / 7810.25 / 7723.25 / 7777.25: **4 of 4 to the tick** | Same |
| CL prices | `CL1!`/NYMEX Fri 02 Oct: O 93.46 H 93.51 L 88.06 C 91.11 — IBKR 93.46 / 93.51 / 88.06 / 91.11: **4 of 4 to the cent** | Same |
| ES volume | TradingView 1.76M; IBKR 1,762,000 — agree (ES has almost no off-screen share) | Same |
| CL volume | TradingView **327.9K**; IBKR **242,152** (−26%) with identical prices — **expected**: IBKR's history is filtered (§3a), CME's reported volume includes ClearPort, blocks and EFRP legs (§3b), and crude carries a large off-screen share (blocks, EFRPs, TAS). Not established: TradingView's own statement of what its NYMEX volume includes (not scraped) | Operator 2026-10-03 |
| `1!` vs the contract | The charts were the continuous fronts (`ES1!`, `CL1!`), not `ESZ2026`/`CLX2026` by name; on this bar the front **is** ESZ6 / CLX6, and a tick-exact match on four prices cannot come from another month | Same |
| Continuous charts | TradingView draws a continuous series across rolls; this package does not and will not — "TV does continuous for charts extremely well … trying to replicate TV is not the scope" | Operator 2026-10-03 |

---

## 4. Not served yet — conventions to establish before adding a type

| Type | What exists | What is missing before `fetch_market_data` offers it |
|---|---|---|
| `IND` | Resolution through `/iserver/secdef/search` (`_resolve_snapshot_conid`) | A key rule (an index symbol can collide with a stock ticker under a ticker key), the hours default, one live read |
| `CASH` | Resolution through `/iserver/currency/pairs` | Which hours a daily FX bar covers at IBKR (24-hour market), a key rule, one live read |
| `OPT` / `FOP` | By conid only, through `get_option_chain` / `/iserver/secdef/strikes` ([contracts reference](https://www.interactivebrokers.com/campus/ibkr-api-page/web-api-staging/#contracts)) | A separate piece of work: the contract pinned by conid and cached under its own symbol, as a future is. "What is important is leaving the door opened to do so" (operator 2026-10-03) |
| `BOND` | Resolution exists | Not added without a use |

---

## 5. Sources — every official page used, by owner

**Interactive Brokers**
- Web API history endpoint: https://www.interactivebrokers.com/docs/web-api/v1/endpoints/market-data/historical-market-data (2026-10-03) and the campus mirror https://www.interactivebrokers.com/docs/web-api/v1/endpoints/market-data/historical-market-data (2026-09-23; `%v` = "actual volume/100")
- OpenAPI v3 (parameter definitions, `outsideRth` default false, `source`, bar unit `S`): https://api.ibkr.com/gw/api/v3/api-docs
- Market-data fields (87, 7762, 7282, 6509): https://www.interactivebrokers.com/docs/web-api/v1/endpoints/market-data/market-data-fields
- Snapshot endpoint (field 6509 second character `p` = Consolidated): https://www.interactivebrokers.com/docs/web-api/api-reference/trading/trading-market-data/get-md-snapshot
- Web API changelog: https://www.interactivebrokers.com/docs/web-api/changelog
- Contracts reference (secType codes, derivative workflow): https://www.interactivebrokers.com/campus/ibkr-api-page/web-api-staging/#contracts (2026-10-03)
- `/iserver/secdef/search`: https://www.interactivebrokers.com/docs/web-api/v1/endpoints/contract/search-contract-by-symbol (2026-10-03 — documents `symbol` and `name` only)
- `/trsrv/futures`: https://www.interactivebrokers.com/docs/web-api/v1/endpoints/contract/security-future-by-symbol
- `/iserver/contract/{conid}/info`: https://www.interactivebrokers.com/docs/web-api/api-reference/trading/trading-contracts/get-instrument-info
- Continuous futures ("can not be used … In the Web API"): https://www.interactivebrokers.com/docs/general/contracts/futures/continuous-futures (2026-09-10)
- Expired futures (historical data within the last 2 years, TWS API): https://www.interactivebrokers.com/docs/general/contracts/futures/expired-futures (2026-09-10)
- Historical data filtering (blocks, combos, derivative trades excluded): https://www.interactivebrokers.com/docs/tws-api/doc/market-data-historical/historical-data-limitations/historical-data-filtering
- Historical bars ("lower than an unfiltered historical data feed"): https://interactivebrokers.github.io/tws-api/historical_bars.html
- Historical data (subscriptions, smart-routed requests): https://interactivebrokers.github.io/tws-api/historical_data.html
- Synchronous API historical market data (current page, no filtering note): https://www.interactivebrokers.com/docs/tws-api/doc/synchronous-api/historical-market-data
- TWS API market data (sizes in shares since TWS 985): https://interactivebrokers.github.io/tws-api/market_data.html
- Market-data subscriptions, introduction: https://www.interactivebrokers.com/docs/general/market-data-subscriptions/introduction
- Popular subscriptions (US L1 = the SIP networks A/B/C): https://www.interactivebrokers.com/docs/general/market-data-subscriptions/popular-market-data-subscriptions/introduction
- TWS display configuration (native vs calculated volume): https://www.ibkrguides.com/traderworkstation/display-configuration.htm
- Archived TWS guides: https://www.interactivebrokers.co.uk/en/software/tws.bak/usersguidebook/configuretws/ticker_row_settings.htm , https://www.interactivebrokers.co.uk/en/software/tws.bak/usersguidebook/thetradingwindow/high_low_volume.htm
- FAQ 102546341 (native vs calculated, vendors differ on blocks/combos/odd lots): https://www.interactivebrokers.com/lib/cstools/faq/#/content/102546341
- Quant-news vendor survey (no IBKR-specific content): https://www.interactivebrokers.com/campus/ibkr-quant-news/historical-market-data-sources/

**CME Group**
- Exchange volume (Globex + Open Outcry + ClearPort/PNT): https://www.cmegroup.com/market-data/browse-data/exchange-volume.html
- Block trades: https://www.cmegroup.com/clearing/trading-practices/block-trades.html
- Rule 526 (block trade volume in the daily volume reports): https://www.cmegroup.com/rulebook/files/cme-group-Rule-526.pdf
- EFRP transactions: https://www.cmegroup.com/education/articles-and-reports/understanding-efrp-transactions
- ES contract specs (hours, termination): https://www.cmegroup.com/markets/equities/sp/e-mini-sandp500.contractSpecs.html
- CL contract specs (hours, termination): https://www.cmegroup.com/markets/energy/crude-oil/light-sweet-crude.contractSpecs.html
- Holiday calendar: https://www.cmegroup.com/tools-information/holiday-calendar.html

**The consolidated tape (US equities)**
- CTA plan, CTS Pillar output specification (sale-condition matrix): https://www.ctaplan.com/publicdocs/ctaplan/CTS_Pillar_Output_Specification.pdf
- CTA odd-lots FAQ: https://www.ctaplan.com/publicdocs/ctaplan/CTA_Odd_Lots_Changes_FAQ.pdf
- UTP plan, binary output specification: https://www.utpplan.com/DOC/UtpBinaryOutputSpec.pdf
- UTP data policies: https://www.utpplan.com/DOC/datapolicies.pdf
- Nasdaq trader notices: https://www.nasdaqtrader.com/TraderNews.aspx?id=UTP2025-10 , https://nasdaqtrader.com/TraderNews.aspx?id=dtn2013-34
- SEC (not scraped): https://www.sec.gov/files/rules/sro/nms/2026/34-105779.pdf

**Single-venue sites — documented as the trap, not as sources**
- Nasdaq Last Sale: https://www.nasdaq.com/products/data/equities/nasdaq-last-sale
- Nasdaq.com historical quotes: https://www.nasdaq.com/market-activity/quotes/historical

**TradingView** — no page scraped; the witness is the operator's own chart (session ETH), figures recorded in `claudia_ui/docs/plans/2026-10-03-outside-rth-probe/WITNESS.md`.
