# ClaudeToolkit — Tools Reference

**40 core tools** exposed by `ClaudeToolkit.tools` and `ClaudeToolkit.execute()`, plus **2 optional web scraper tools** when `FIRECRAWL_API_KEY` is set (42 total).

Each tool returns `(text: str, fig: plotly.Figure | None)`. `fig` is only non-`None` for chart tools (currently none — reserved for a future equity-curve chart tool).

Pass `toolkit.tools` directly to the Anthropic SDK `tools=` parameter. Route responses through `toolkit.execute(block.name, block.input)`.

**IBKR API source:** https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/

---

## Portfolio & Account

### `get_account_summary`
Net liquidation value, total cash, unrealized P&L, and realized P&L.

**Inputs:** none

**Output:** JSON with `netliquidation`, `totalcashvalue`, `unrealizedpnl`, `realizedpnl`.

**IBKR endpoint:** `GET /portfolio/{accountId}/summary`

---

### `get_positions`
All open positions for the primary account.

**Inputs:** none

**Output:** JSON array of positions. Each entry includes `conid`, `contractDesc` (symbol),
`position` (size), `mktPrice`, `mktValue`, `unrealizedPnl`, `realizedPnl`.

**IBKR endpoint:** `GET /portfolio/{accountId}/positions/0`

---

### `get_pnl`
Real-time partitioned P&L — daily, unrealized, and realized — broken down by position.

**Inputs:** none

**Output:** Raw JSON from `/iserver/account/pnl/partitioned`.

**Rate limit:** 1 req/5 secs (official).

**IBKR endpoint:** `GET /iserver/account/pnl/partitioned`

---

### `get_ledger`
Cash balance and ledger information by currency.

**Inputs:** none

**Output:** JSON ledger keyed by currency code (e.g. `"BASE"`, `"USD"`, `"CAD"`).
Each entry has `cashbalance`, `netliquidation`, `unrealizedpnl`, `realizedpnl`.

**IBKR endpoint:** `GET /portfolio/{accountId}/ledger`

---

### `get_allocation`
Portfolio breakdown by asset class, industry, sector, and group.

**Inputs:** none

**Output:** JSON object with `assetClass`, `group`, `sector`, `industry` sub-objects.

**IBKR endpoint:** `GET /portfolio/{accountId}/allocation`

---

### `get_pa_periods`
Return the exact period strings accepted by Portfolio Analyst for this account.

**Always call this before `get_pa_performance` or `get_pa_transactions`** — IBKR returns HTTP 400 for invalid period strings, and the valid set comes from this endpoint.

**Inputs:** none

**Output:** JSON array of valid period strings (e.g. `["last7days", "last30days", "ytd", "last365days", "alltime"]`).

**IBKR endpoint:** `POST /pa/allperiods`

---

### `get_pa_performance`
Portfolio NAV performance from IBKR Portfolio Analyst.

**Call `get_pa_periods` first** to get the exact period strings IBKR accepts. Passing an invalid string returns HTTP 400 with no useful error message.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `period` | string | ✅ | Period string from `get_pa_periods` (e.g. `"last7days"`, `"ytd"`, `"last365days"`) |

**Output:** NAV performance data for the requested period.

**Rate limit:** 1 req/15 mins (official).

**IBKR endpoint:** `POST /pa/performance`

---

### `get_pa_transactions`
Transaction history from IBKR Portfolio Analyst. Covers all order origins (mobile, TWS, API) — not session-scoped.

**Call `get_pa_periods` first** to get the exact period strings IBKR accepts.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `period` | string | ✅ | Period string from `get_pa_periods` (e.g. `"last7days"`, `"ytd"`) |

**Output:** Transaction list for the requested period.

**Rate limit:** 1 req/15 mins (official).

**IBKR endpoint:** `POST /pa/transactions`

---

## Orders

### `get_live_orders`
Working orders — Submitted, PreSubmitted, PendingSubmit, ApiPending, PendingCancel.
Also returns `Inactive` orders (exist on IBKR but stalled, e.g. failed risk check).
Filled and Cancelled orders are excluded; use `get_trades` for executions.

Uses the IBKR two-call pattern internally: first call instantiates the subscription, second retrieves data.
Source: https://www.interactivebrokers.com/campus/trading-lessons/request-modify-orders/

**Inputs:** none

**Output:** JSON array of working orders. Each entry includes `orderId`, `ticker`, `side`,
`totalSize`, `price`, `orderType`, `status`.

**Rate limit:** 1 req/5 secs (official).

**IBKR endpoint:** `GET /iserver/account/orders` (filtered by working statuses)

---

### `diagnose_orders`
Raw unfiltered IBKR orders API response for debugging. Use when `get_live_orders` returns
empty but orders are expected. Shows ALL orders regardless of status and the full response
shape, so you can see whether orders are present but filtered, or genuinely absent.

**Inputs:** none

**Output:** Raw JSON from IBKR orders endpoint, unfiltered.

**IBKR endpoint:** `GET /iserver/account/orders`

---

### `get_order_status`
Status and details for a specific order.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `order_id` | string | ✅ | IBKR order ID (from `get_live_orders`) |

**Output:** Raw JSON order status from IBKR.

**IBKR endpoint:** `GET /iserver/account/order/status/{orderId}`

---

### `preview_order`
Whatif preview — estimated cost, commission, margin impact, and buying power effect,
**without placing the order**. Use before proposing a trade to verify feasibility.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `symbol` | string | ✅ | Ticker, e.g. `"AAPL"` |
| `action` | string | ✅ | `"BUY"` or `"SELL"` |
| `quantity` | integer | ✅ | Number of shares/contracts |
| `order_type` | string | — | `"MKT"` (default), `"LMT"`, or `"STP"` |
| `limit_price` | number | — | Required when `order_type="LMT"` |

**Output:** JSON with `equity`, `commission`, `marginImpact`, `buyingPowerEffect`.

**IBKR endpoint:** `POST /iserver/account/{accountId}/orders/whatif`

---

## Trades

### `get_trades`
Trade history from IBKR or local SQLite store.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `symbol` | string | — | Filter by symbol |
| `source` | string | — | `"live"` (IBKR API, last 6 days, all origins) or `"store"` (SQLite, full history) — default `"store"` |
| `start` | string | — | Start date `YYYY-MM-DD` (store only) |
| `end` | string | — | End date `YYYY-MM-DD` (store only) |

**Output:** JSON array of trade executions.

**Note (live):** Returns all trades on the account regardless of order origin (mobile, TWS, API).
`?days` supports up to a maximum of 7 days; if unspecified, only the current day is returned.
Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/

**Rate limit:** 1 req/5 secs (official).

**IBKR endpoint (live):** `GET /iserver/account/trades`
**Store:** `SQLiteStore.get_trades()`

---

### `sync_flex_trades`
Fetch full historical trade history from the IBKR Flex Web Service and upsert into SQLite.
Requires `IBKR_FLEX_TOKEN` and `IBKR_FLEX_QUERY_ID` env vars. T+1 latency — yesterday is the newest possible.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `account_id` | string | — | IBKR account ID (resolved automatically if omitted) |

**Output:** Count of trades fetched and stored, plus coverage summary.

**Flex endpoint:** `https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/`
Source: https://www.ibkrguides.com/clientportal/performanceandstatements/flex3.htm

---

### `sync_flex_archive`
Download all Flex XML files from the `ibkr_flex_archive` Google Drive subfolder and import
them into the local SQLite trade store. Use for historical backfill: upload year-by-year
XML files to Drive first, then run this once. Duplicates are handled automatically.
Runs `check_flex_coverage` at the end.

**Inputs:** none

**Output:** Per-file import counts and coverage summary.

---

### `import_flex_file`
Import a single locally-downloaded IBKR Flex XML file into the SQLite trade store.
Use for historical backfill with files saved to `~/.ibkr_core/flex_archive/`.
Duplicates are handled automatically (idempotent).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | ✅ | Absolute path to the Flex XML file |

**Output:** Import count and confirmation.

---

### `check_flex_coverage`
Report the trade activity date range from the local SQLite store: oldest trade, newest trade,
total record count, and periods of 45+ calendar days with no recorded executions.
Gaps reflect genuine inactivity (30-day min hold periods produce 50–68 day gaps), not
necessarily missing imports — use `verify_flex_import` to distinguish.

**Inputs:** none

**Output:** Coverage summary with date range, trade count, and any gap periods.

---

### `verify_flex_import`
Read-only integrity check — compares source XML archives in Google Drive `account_data/`
against the local SQLite trades table. For each XML file, extracts all tradeIDs and checks
whether they are present in SQLite. Reports per-file counts (XML records vs SQLite matches)
and an aggregate summary. A missing tradeID means that execution was not imported.

**Inputs:** none

**Output:** Per-file verification report and aggregate match summary.

---

## Market Data

### `fetch_market_data`
Fetch OHLCV historical bars. Checks Google Drive Parquet cache first; calls IBKR only on a miss.
Automatically paginates requests exceeding the 1000 data-point limit using `startTime` chunks.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `symbol` | string | ✅ | Ticker, e.g. `"AAPL"` |
| `period` | string | ✅ | e.g. `"1Y"`, `"6M"`, `"3M"`, `"1M"`, `"1W"`, `"1D"`. Full range: `{1-1000}d`, `{1-792}w`, `{1-182}m`, `{1-15}y` |
| `bar` | string | — | `"1d"` (default), `"1h"`, `"30min"`, `"5min"`, `"1min"` |
| `end` | string | — | End date `YYYY-MM-DD` (defaults to today) |

**Output:** Summary with row count, date range, and last close.

**Note:** Max 1000 data points per request — handled automatically by pagination.
`/hmds/history` was deprecated November 18, 2025; this tool uses `/iserver/marketdata/history`.
Source: https://www.interactivebrokers.com/campus/ibkr-api-page/web-api-changelog/

**Rate limit:** 5 concurrent requests (official).

**IBKR endpoint:** `GET /iserver/marketdata/history` (paginated via `startTime`)

---

### `get_market_snapshot`
Live real-time snapshot for one or more symbols: last price, bid, ask, volume, high, low, change%.
Resolves symbols to conids automatically.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `symbols` | array[string] | ✅ | e.g. `["AAPL", "MSFT", "SPY"]` |
| `sec_type` | string | — | `"STK"` (default), `"FUT"`, `"OPT"`, `"FX"` |

**Output:** JSON array with live quote fields. Field codes: `"31"` = last price, `"84"` = bid,
`"86"` = ask, `"87"` = volume.

**Note:** Max 100 conids per request, max 50 fields per request. Snapshot subscriptions require
a brief warm-up (≈1s); empty result on first call — retry once.
Source: https://www.interactivebrokers.com/campus/ibkr-api-page/web-api-changelog/ (Dec 10, 2025)

**IBKR endpoint:** `GET /iserver/marketdata/snapshot`

---

## Contracts

### `search_contract`
Look up IBKR contract details for a symbol.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `symbol` | string | ✅ | Ticker, e.g. `"AAPL"`, `"CL"`, `"SPY"` |
| `sec_type` | string | — | `"STK"` (default), `"FUT"`, `"OPT"`, `"FX"`, `"IND"`, `"CFD"`, `"BOND"` |

**Output:** JSON array of matching contracts. Each entry has `conid`, `symbol`, `companyName`,
`exchange`, `currency`.

**IBKR endpoint:** `GET /iserver/secdef/search`

---

### `get_contract_info`
Full contract details: conid, exchange, currency, trading hours, margin class.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `symbol` | string | ✅ | Ticker symbol |
| `sec_type` | string | — | Default `"STK"` |

**Output:** Full contract JSON from IBKR.

**IBKR endpoint:** `GET /iserver/contract/{conid}/info`

---

### `get_option_chain`
Options chain for a symbol — all expirations, strikes, and contract IDs.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `symbol` | string | ✅ | Underlying symbol |
| `exchange` | string | — | Default `"SMART"` |

**Output:** JSON object keyed by expiration date, each containing a list of strike/conid pairs.

**IBKR endpoint:** `GET /trsrv/secdef/chains`

---

### `get_futures`
Futures contracts for one or more root symbols — expiry months, conids, exchanges.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `symbols` | array[string] | ✅ | Root symbols, e.g. `["CL", "ES", "GC"]` |

**Output:** JSON array of futures contracts with `conid`, `symbol`, `exchange`, `expirationDate`.

**IBKR endpoint:** `GET /trsrv/futures`

---

### `get_trading_schedule`
Trading hours and session information for a symbol. Resolves symbol to conid internally.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `symbol` | string | ✅ | Ticker, e.g. `"CL"`, `"AAPL"` |
| `asset_class` | string | — | `"STK"` (default), `"FUT"`, `"OPT"`, `"FX"` |
| `exchange` | string | — | e.g. `"NYMEX"`, `"NYSE"` (default `"SMART"`) |

**Output:** JSON with `regularTradingHours`, `liquidHours`, `timezone`, and next/current session.

**IBKR endpoint:** `GET /trsrv/secdef/schedule`

---

## Cache

### `check_cache`
Check whether a specific dataset is cached in Google Drive.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `symbol` | string | ✅ | Ticker |
| `timeframe` | string | ✅ | e.g. `"1D"` |
| `period` | string | ✅ | e.g. `"1Y"` |
| `end` | string | ✅ | End date `YYYY-MM-DD` |

**Output:** `"HIT"` or `"MISS"`.

---

### `list_cache`
List all datasets cached in Google Drive.

**Inputs:** none

**Output:** JSON array of cache manifest entries with `symbol`, `timeframe`, `period`,
`cached_at`, `row_count`.

---

### `delete_cache`
Delete a specific dataset from the Google Drive cache. Use when stale data needs re-fetching.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `symbol` | string | ✅ | Ticker |
| `timeframe` | string | ✅ | e.g. `"1D"` |
| `period` | string | ✅ | e.g. `"1Y"` |
| `end` | string | ✅ | End date `YYYY-MM-DD` |

**Output:** Confirmation message.

---

## Analysis

### `add_indicators`
Load cached market data and compute all technical indicators.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `symbol` | string | ✅ | Ticker |
| `timeframe` | string | ✅ | e.g. `"1D"` |
| `period` | string | ✅ | e.g. `"1Y"` |
| `end` | string | ✅ | End date `YYYY-MM-DD` |

**Output:** Current values for: RSI(14), MACD, MACD signal, Bollinger Bands (upper/mid/lower),
ATR(14), VWAP, OBV, Stochastic %K/%D, Williams %R, Keltner Channels.

**Prerequisite:** Data must be cached. Call `fetch_market_data` first if needed.

---

### `run_backtest`
Execute a Python strategy in a sandboxed `RestrictedPython` environment.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `code` | string | ✅ | Python code. Must set `df['signal'] = 1` (long), `0` (flat), or `-1` (short) |
| `symbol` | string | ✅ | Ticker |
| `timeframe` | string | ✅ | e.g. `"1D"` |
| `period` | string | ✅ | e.g. `"1Y"` |
| `end` | string | ✅ | End date `YYYY-MM-DD` |
| `strategy_name` | string | — | Human-readable label |

**Output:** Sharpe ratio, Sortino ratio, total return, max drawdown, trade count, win rate.
Result is persisted to `SQLiteStore.backtest_results`.

**Sandbox:** `RestrictedPython` — no file I/O, no network, no `import`. `df`, `pd`, `np`
are pre-injected. Code is limited to 4096 characters and 10-second execution timeout.

**Prerequisite:** Data must be cached.

---

### `get_analytics`
Full analytics report on a cached dataset.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `symbol` | string | ✅ | Ticker |
| `timeframe` | string | ✅ | e.g. `"1D"` |
| `period` | string | ✅ | e.g. `"1Y"` |
| `end` | string | ✅ | End date `YYYY-MM-DD` |

**Output:** Sharpe, Sortino, Calmar, CAGR, max drawdown, max drawdown duration (bars).

---

### `generate_pinescript`
Generate a PineScript v5 indicator or strategy script.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `symbol` | string | ✅ | Ticker (used in comments/title) |
| `indicators` | array[string] | ✅ | One or more of: `"rsi"`, `"macd"`, `"bollinger_bands"`, `"ema"`, `"sma"`, `"atr"` |
| `strategy_name` | string | — | Script title |

**Output:** PineScript v5 code starting with `//@version=5`. Can be pasted directly into
TradingView Pine Editor.

**Note:** Generated code is a functional template. Entry/exit conditions use placeholder
logic that should be customized for your specific strategy.

---

## Alerts

IBKR alerts are server-side — they fire even when ClaudIA is not running and are delivered
to the IBKR mobile app.

Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#alerts

### `get_alerts`
List all IBKR price alerts configured on the account.

**Inputs:** none

**Output:** JSON array of alerts. Each entry has `orderId` (the alert ID), `alertName`,
`alertActive` (1/0), `conditions` array.

**IBKR endpoint:** `GET /iserver/account/{accountId}/alerts`

---

### `create_price_alert`
Create a native IBKR server-side price alert.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `symbol` | string | ✅ | Ticker, e.g. `"AAPL"`, `"CL"` |
| `operator` | string | ✅ | `">="` (at or above) or `"<="` (at or below) |
| `price` | number | ✅ | Price threshold |
| `sec_type` | string | — | `"STK"` (default), `"FUT"`, `"OPT"`, `"FX"` |
| `name` | string | — | Human-readable label (auto-generated if omitted) |
| `repeat` | boolean | — | Repeat after firing (default `false`) |

**Output:** JSON confirmation with the new alert's `orderId`.

**Note:** Exchange is resolved from the contract — futures use their native exchange
(NYMEX, CME), not SMART.

**IBKR endpoint:** `POST /iserver/account/{accountId}/alert`

---

### `modify_price_alert`
Modify an existing IBKR price alert. Fetches the current alert by ID and applies only the
fields you provide, leaving others unchanged. Use `get_alerts` first to find the alert ID.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `alert_id` | string | ✅ | Alert ID from `get_alerts` (`orderId` field) |
| `price` | number | — | New price threshold |
| `operator` | string | — | `">="` or `"<="` |
| `tif` | string | — | `"GTC"` or `"DAY"` |
| `outside_rth` | boolean | — | `true` = extended hours, `false` = regular hours only |
| `name` | string | — | New alert name |

**Output:** JSON confirmation.

**IBKR endpoint:** `POST /iserver/account/{accountId}/alert` (update via same create endpoint)

---

### `delete_alert`
Delete an IBKR alert permanently.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `alert_id` | string | ✅ | Alert ID from `get_alerts` (`orderId` field) |

**Output:** JSON confirmation.

**IBKR endpoint:** `DELETE /iserver/account/{accountId}/alert/{alertId}`

---

### `activate_alert`
Activate or deactivate an alert without deleting it.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `alert_id` | string | ✅ | Alert ID from `get_alerts` |
| `activate` | boolean | — | `true` to activate (default), `false` to deactivate |

**Output:** JSON confirmation.

**IBKR endpoint:** `POST /iserver/account/{accountId}/alert/activate`

---

## Watchlists

### `get_watchlists`
List all IBKR watchlists and their contents.

**Inputs:** none

**Output:** JSON array of watchlists. Each entry has `id`, `name`, `rows` (array of instruments).

**IBKR endpoint:** `GET /iserver/account/watchlists`

---

## Notifications

### `get_notifications`
IBKR FYI notifications — account alerts, order fills, margin calls, news.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `max_results` | integer | — | Maximum to return (default 10, **max 10** — official API limit) |

**Output:** JSON array of notifications. Each entry has `id`, `date`, `headline`, `body`, `isRead`.
Also includes total unread count.

**IBKR endpoint:** `GET /fyi/notifications`
Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/

---

## Scanner

### `run_scanner`
Run an IBKR market scanner.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `scan_code` | string | ✅ | Scanner type (see below) |
| `instrument` | string | — | `"STK"` (default) |
| `location_code` | string | — | `"STK.US.MAJOR"` (default) |
| `max_results` | integer | — | Default 25 |

**Common `scan_code` values:**

| Code | Description |
|------|-------------|
| `TOP_PERC_GAIN` | Top % gainers today |
| `TOP_PERC_LOSE` | Top % losers today |
| `MOST_ACTIVE` | Most active by volume |
| `HIGH_VS_13W_HL` | Near 13-week highs |
| `LOW_VS_13W_HL` | Near 13-week lows |
| `NEAR_52W_HL` | Near 52-week high |

**Output:** JSON array of matching contracts with `conid`, `symbol`, `company`, and scan-specific fields.

**Rate limit:** 1 req/sec (official).

**IBKR endpoint:** `POST /iserver/scanner/run`

---

## Web Scraper (optional)

These two tools are available only when `FIRECRAWL_API_KEY` is set. They use the
Firecrawl API to search the web and crawl documentation sites, saving results to
Google Drive `web_docs/`.

### `firecrawl_search`
Search the web and return full page content as markdown. Use for research, news, or
fetching technical documentation. Optionally saves a snapshot to Drive.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | ✅ | Search query |
| `limit` | integer | — | Max results (1–10, default 5) |
| `save_to_drive` | boolean | — | Save markdown snapshot to Drive `web_docs/searches/` (default `false`) |

**Output:** Search results with URL, title, and full markdown content.

---

### `firecrawl_crawl`
Crawl an entire website starting from a URL and save all pages to Drive under
`web_docs/{url-slug}/`. Crawls are asynchronous — polls until done or timeout.
Use for archiving IBKR documentation or other reference sites.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `url` | string | ✅ | Root URL to crawl from (public http/https only) |
| `max_pages` | integer | — | Maximum pages to crawl (1–100, default 50) |
| `timeout_s` | integer | — | Max seconds to wait (default 120) |

**Output:** Summary of pages saved to Drive with paths and page count.
