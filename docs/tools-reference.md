# ClaudeToolkit — Tools Reference

**42 tools total** (40 core + 2 web scraper) exposed by `ClaudeToolkit.tools` and
`ClaudeToolkit.execute()`. `ClaudeToolkit.tools` always advertises all 42 regardless of
environment — the 2 scraper tools (`firecrawl_search`, `firecrawl_crawl`) are not conditionally
omitted from the schema. `FIRECRAWL_API_KEY` is instead checked at call time, inside
`execute()`: calling either scraper tool without the key set returns an error string rather
than the tool being absent from what's offered to the model.

Each tool returns `(text: str, fig: plotly.Figure | None)`. `fig` is only non-`None` for chart tools (currently none — reserved for a future equity-curve chart tool).

Pass `toolkit.tools` directly to the Anthropic SDK `tools=` parameter. Route responses through `toolkit.execute(block.name, block.input)`.

**IBKR API source:** https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/introduction

---

## Portfolio & Account

### `get_account_summary`
Net liquidation value, total cash, gross position value, and buying power — a single
aggregate snapshot for the account. This endpoint does not carry P&L fields — for
realized/unrealized P&L use `get_ledger` (per-currency) or `get_pnl` (per account
partition, no realized figure); for per-position detail use `get_positions`.

**Inputs:** none

**Output:** Text summary with `Account`, `Net Liquidation`, `Cash`, `Gross Position Val`,
`Buying Power`.

**IBKR endpoint:** `GET /portfolio/{accountId}/summary`

---

### `get_positions`
All open positions for the primary account. Flat entries (`position=0`) are filtered out.

**Inputs:** none

**Output:** Text list of open positions — one line per position with symbol, `qty`, `mktVal`,
`unrealPnL`.

**IBKR endpoint:** `GET /portfolio/{accountId}/positions/0`

---

### `get_pnl`
Real-time account-level P&L — daily and unrealized. **Not** broken down by position (IBKR's
`/iserver/account/pnl/partitioned` returns one summary row per account/model partition, no
per-conid detail); use `get_positions` for per-position unrealized P&L. No realized figure is
returned by this endpoint.

**Inputs:** none

**Output:** Text summary — per-partition unrealized/daily P&L (plus net/excess liquidity where
present), and totals across partitions.

**Note:** On a cold gateway session this endpoint can return an empty result (`{"upnl": {}}`)
even with open positions — live-verified 2026-07-17, same class of warm-up quirk as
`get_market_snapshot` below. The tool self-primes: if the first call comes back empty, it
briefly subscribes/unsubscribes to the `spl` WebSocket topic and retries once before falling
back to "No P&L data returned" — callers don't need to retry or know about the quirk.

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
Return the exact period strings accepted by `get_pa_performance` for this account.

**Always call this before `get_pa_performance`** — IBKR returns HTTP 400 for invalid period strings, and the valid set comes from this endpoint. `get_pa_transactions` does not take a period (see below).

**Inputs:** none

**Output:** Text list of valid period strings (documented values: `"1D"`, `"7D"`, `"MTD"`, `"1M"`, `"YTD"`, `"1Y"` — the exact set returned may vary by account age/type).

**IBKR endpoint:** `POST /pa/allperiods`

---

### `get_pa_performance`
Portfolio NAV performance from IBKR Portfolio Analyst.

**Call `get_pa_periods` first** to get the exact period strings IBKR accepts. Passing an invalid string returns HTTP 400 with no useful error message.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `period` | string | ✅ | Period string from `get_pa_periods`, e.g. `"1D"`, `"7D"`, `"MTD"`, `"1M"`, `"YTD"`, `"1Y"` |

**Output:** Text summary of NAV performance data for the requested period.

**Rate limit:** 1 req/15 mins (official).

**IBKR endpoint:** `POST /pa/performance`

---

### `get_pa_transactions`
Transaction history from IBKR Portfolio Analyst for **one symbol**. Covers all order origins (mobile, TWS, API) — not session-scoped.

IBKR's `/pa/transactions` endpoint takes a resolved conid, not a period — `symbol` is resolved to a conid internally (same dispatch used by `get_market_snapshot`/`get_contract_info`), so `search_contract` doesn't need to be called first. Only one instrument is supported per call.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `symbol` | string | ✅ | Ticker symbol to fetch transactions for |
| `sec_type` | string | — | `"STK"` (default), `"IND"`, `"BOND"`, `"FUT"`, or `"CASH"` — used for conid resolution |
| `currency` | string | — | Currency code for the request (default `"USD"`) |
| `days` | integer | — | Optional lookback window in days; omit for IBKR's default range |

**Output:** Text list of transactions (date, description, amount) plus a net total.

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

**Output:** Text list of working orders — one line per order with `orderId`, `ticker`, `side`,
quantity, price, `status`, time-in-force, and origin (`ClaudIA-staged`, `API (clientId=...)`,
or `EXTERNAL`).

**Rate limit:** 1 req/5 secs (official).

**IBKR endpoint:** `GET /iserver/account/orders` (filtered by working statuses)

---

### `diagnose_orders`
Raw unfiltered IBKR orders API response for debugging. Use when `get_live_orders` returns
empty but orders are expected. Shows ALL orders regardless of status and the full response
shape, so you can see whether orders are present but filtered, or genuinely absent.

**Inputs:** none

**Output:** Text list of every order with all fields plus a `[FILTERED by get_live_orders]`
marker on terminal-status orders — or the raw JSON response verbatim for the edge cases where
the response isn't a populated list (empty list, or an unexpected non-list shape).

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
| `order_type` | string | — | `"MKT"` (default), `"LMT"`, `"STP"`, `"STOP_LIMIT"`, or `"MIDPRICE"`. Trailing types (`TRAIL`/`TRAILLMT`) are not supported by this tool. |
| `limit_price` | number | — | Required for `order_type="LMT"`/`"STOP_LIMIT"`; optional price cap for `"MIDPRICE"` |
| `stop_price` | number | — | Required for `order_type="STP"`/`"STOP_LIMIT"` |
| `sec_type` | string | — | `"STK"` (default), `"IND"`, `"BOND"`, `"FUT"` (resolves front month), or `"CASH"` (FX pair, e.g. `"EUR.USD"`) |

**Output:** Text summary — `Commission est.`, `Equity with loan`, `Initial margin`,
`Maintenance margin`, `Buying power effect` (equity change).

**IBKR endpoint:** `POST /iserver/account/{accountId}/orders/whatif`

---

## Trades

### `get_trades`
Trade history from IBKR or local SQLite store.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `symbol` | string | — | Filter by symbol |
| `source` | string | — | `"live"` (IBKR API, last 7 days, all origins) or `"store"` (SQLite, full history) — default `"store"` |
| `start` | string | — | Start date `YYYY-MM-DD` (store only) |
| `end` | string | — | End date `YYYY-MM-DD` (store only) |

**Output:** Text list of trade executions — one line per trade with time, symbol, asset class,
side, size, price (plus commission and realized P&L for `source="store"`).

**Note (live):** Returns all trades on the account regardless of order origin (mobile, TWS, API).
Calls IBKR with `?days=7`, the documented maximum for this endpoint.
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/introduction

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
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/introduction

**Rate limit:** 5 concurrent requests (official).

**IBKR endpoint:** `GET /iserver/marketdata/history` (paginated via `startTime`)

---

### `get_market_snapshot`
Live real-time snapshot for one or more symbols: last price, bid, ask, volume, high, low, change%.
Resolves symbols to conids automatically.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `symbols` | array[string] | ✅ | For FX: `"EUR.USD"` format. For FUT: root symbol only (`"ES"`, not `"ESH25"`). For international STK: ticker as listed on the exchange. |
| `sec_type` | string | — | `"STK"` (default), `"IND"`, `"FUT"`, `"CASH"`, `"BOND"`. **`OPT` is not supported** — resolve the option conid first via `search_contract` + `get_option_chain`, then pass that conid directly rather than a ticker. |
| `exchange` | string | — | Optional, for STK/IND only — filters to a specific listing (e.g. `"AMS"` Euronext Amsterdam, `"ETR"` Xetra, `"LSE"` London, `"TSE"` Tokyo, `"HKEX"` Hong Kong, `"ASX"` Sydney, `"TSX"` Toronto, `"BVSP"` Brazil, `"NSE"` India). Omit for US equities (SMART routing). Without it, the first search result is used. |

**Output:** JSON array with live quote fields. Field codes: `"31"` = last price, `"84"` = bid,
`"86"` = ask, `"87"` = volume. Each quote also includes `_data_status` (`"Live (Real-Time)"` when
subscribed, `"Delayed (15–20 min)"` when not) and `_quote_time` (ET timestamp) — always report
both to the user.

**Note:** Max 100 conids per request, max 50 fields per request. Snapshot subscriptions require
a brief warm-up (≈1s); empty result on first call — retry once.
Source: https://www.interactivebrokers.com/docs/web-api/changelog (Dec 10, 2025)

**IBKR endpoint:** `GET /iserver/marketdata/snapshot`

---

## Contracts

### `search_contract`
Look up IBKR contract details for a symbol.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `symbol` | string | ✅ | Ticker, e.g. `"AAPL"`, `"IBM"` |
| `sec_type` | string | — | `"STK"`, `"IND"`, or `"BOND"` (default `"STK"`) — **the only values `/iserver/secdef/search` supports.** For futures use `get_futures`; for FX use `get_market_snapshot`; for option strikes use `get_option_chain`. |

**Output:** JSON array of matching contracts. Each entry has `conid`, `symbol`, `companyName`,
`exchange`, `currency`.

**IBKR endpoint:** `GET /iserver/secdef/search`

---

### `get_contract_info`
Full contract details: conid, exchange, currency, trading hours, margin class. Resolves the
conid internally, so `search_contract` doesn't need to be called first.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `symbol` | string | ✅ | Ticker symbol |
| `sec_type` | string | — | `"STK"`, `"IND"`, `"BOND"`, or `"FUT"` (front-month) — default `"STK"`. **Does not support `CASH` (FX) or `OPT`.** |

**Output:** Full contract JSON from IBKR.

**IBKR endpoint:** `GET /iserver/contract/{conid}/info-and-rules`

---

### `get_option_chain`
Option chain for an underlying symbol: all available expiry months, plus call and put strike
prices for **one** month (default: nearest expiry). Uses IBKR's documented
`secdef/search` → `secdef/strikes` flow internally. Returns strikes only — not per-contract
conids or greeks.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `symbol` | string | ✅ | Underlying ticker, e.g. `"AAPL"` |
| `month` | string | — | Expiry month as 3-letter month + 2-digit year, e.g. `"JAN26"` (default: nearest expiry; the response's `months` field lists all available ones) |
| `exchange` | string | — | Default `"SMART"` |

**Output:** JSON object: `{"symbol", "conid", "months": [all expiries], "month": <resolved>, "call": [strikes], "put": [strikes]}`.

Reimplemented 2026-07-07 — a previous version called the undocumented `/trsrv/secdef/chains`,
which 404'd on every call. It no longer does.

**IBKR endpoint:** `GET /iserver/secdef/search` (resolve underlying) + `GET /iserver/secdef/strikes` (strikes for the resolved month)

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

**Output:** `"Drive cache is empty."`, or a text list — one line per dataset,
`<key>: <rows> bars, cached <YYYY-MM-DD>`.

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
ATR(14), VWAP, Stochastic %K/%D, Williams %R, Volume Ratio.

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

**Output:** Total return, CAGR, Sharpe, Sortino, Calmar, max drawdown, max drawdown duration
(bars), bars analyzed.

---

### `generate_pinescript`
Generate a PineScript v5 script for TradingView. Two modes, selected by `source`:

- `source="indicators"` (default) — emits an indicator study from a list of indicators.
- `source="backtest"` — emits a `strategy()` script from the most recent stored
  `run_backtest` result for the symbol, with real metrics in the header. Always use this
  mode after `run_backtest` instead of writing PineScript by hand.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `symbol` | string | ✅ | Ticker (used in comments/title) |
| `source` | string | — | `"indicators"` (default) or `"backtest"` |
| `indicators` | array[string] | — | For `source="indicators"`: one or more of `"rsi"`, `"macd"`, `"bollinger_bands"`, `"ema"`, `"sma"`, `"atr"` |
| `strategy_name` | string | — | Script title; for `source="backtest"` also filters which stored run to use (default: most recent for the symbol) |
| `timeframe` | string | — | For `source="backtest"`: cache timeframe of the backtested bars, for chart-timeframe inference (optional) |
| `period` | string | — | For `source="backtest"`: cache period key (optional) |
| `end` | string | — | For `source="backtest"`: cache end-date key (optional) |

Only `symbol` is required — `indicators` is optional (used only in `source="indicators"` mode).

**Output:** PineScript v5 code starting with `//@version=5`. Can be pasted directly into
TradingView Pine Editor.

**Note:** In `source="indicators"` mode, generated code is a functional template — entry/exit
conditions use placeholder logic that should be customized for your specific strategy. In
`source="backtest"` mode, the script reflects the actual stored backtest's signal logic and
metrics.

---

## Alerts

IBKR alerts are server-side — they fire even when ClaudIA is not running and are delivered
to the IBKR mobile app.

Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/alerts/introduction

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
| `symbol` | string | ✅ | Ticker, e.g. `"AAPL"`, `"CL"`, or `"EUR.USD"` for CASH |
| `operator` | string | ✅ | `">="` (at or above) or `"<="` (at or below) |
| `price` | number | ✅ | Price threshold |
| `sec_type` | string | — | `"STK"`, `"IND"`, or `"BOND"` (default `"STK"`) — resolved via contract search; `"FUT"` — resolved to the front-month contract; `"CASH"` — FX pair, `symbol` must be `"BASE.QUOTE"` e.g. `"EUR.USD"`. **`OPT` is not supported** (options need a strike/expiry, not just a symbol). |
| `tif` | string | — | `"GTC"` (default) or `"DAY"` (expires at market close) |
| `outside_rth` | boolean | — | `true` = also monitor extended hours (pre/after-market); default `false` |
| `name` | string | — | Human-readable label (auto-generated if omitted) |
| `repeat` | boolean | — | Repeat after firing (default `false`) |

**Output:** JSON confirmation with the new alert's `orderId`.

**Note:** the alert condition's exchange is always `"SMART"` — including for futures — because
`create_price_alert`'s conid-resolution path (shared with `get_market_snapshot`) does not
return a resolved listing exchange to build the condition from.

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

**IBKR endpoint:** `GET /iserver/watchlists`

---

## Notifications

### `get_notifications`
IBKR FYI notifications — account alerts, order fills, margin calls, news.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `max_results` | integer | — | Maximum to return (default 10, max 10 per request) |

**Output:** JSON array of notifications. Each entry has `id`, `date`, `headline`, `body`, `isRead`.
Also includes total unread count.

**Note:** IBKR enforces a hard cap of 10 notifications per request.
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/introduction

**IBKR endpoint:** `GET /fyi/notifications`

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
| `wait_for_ms` | integer | — | Advanced. Milliseconds to wait for JavaScript rendering before extraction. Omitted from the request entirely when unset |
| `proxy` | string | — | Advanced. `basic` (1 credit), `enhanced` (up to 5), or `auto` (basic, retried through enhanced on failure). Omitted when unset |

**Output:** Search results with URL, title, and full markdown content.

---

### `firecrawl_crawl`
Crawl an entire website starting from a URL and save all pages to Drive under
`web_docs/{url-slug}/`. Crawls are asynchronous — polls until done or timeout.
Use for archiving IBKR documentation or other reference sites.

**Caches reads:** if a Drive manifest for this exact URL already exists and is
less than 48h old, the cached manifest is returned directly and Firecrawl is
never called (0 requests, 0 credits). 48h is informed by Firecrawl's own
`scrapeOptions.maxAge` cache default on its **v2** API (172800000ms) — the
**v1** API this package actually calls (`BASE_URL = .../v1`) defaults that
same parameter to `0`/disabled, so this isn't literally Firecrawl's own
default for what we call, just a deliberate choice using their v2 number as
a reference point for reference-doc content, not an arbitrary one. Pass
`force_refresh: true` to always re-crawl.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `url` | string | ✅ | Root URL to crawl from (public http/https only) |
| `max_pages` | integer | — | Maximum pages to crawl (1–100, default 50) |
| `timeout_s` | integer | — | Max seconds to wait. Default is derived from `max_pages` as `min(600, max(120, 6 × max_pages))` — 120s up to 20 pages, 300s at 50, 600s at 100. Only one Firecrawl attempt is made, so this is the whole budget |
| `force_refresh` | boolean | — | Re-crawl even if a fresh (<48h) cached manifest exists (default `false`) |
| `wait_for_ms` | integer | — | Advanced, opt-in. Milliseconds to wait for JavaScript rendering. Try `3000` on a JS-rendered site that came back empty. Omitted from the request when unset |
| `proxy` | string | — | Advanced, opt-in. `basic` / `enhanced` / `auto`. Try `auto` on a site that blocks automated clients. Omitted when unset |

**Output:** Summary of pages saved to Drive with byte count, source (Firecrawl,
Crawl4AI, or Crawl4AI Cloud), paths and page count; or a "Using cached crawl..."
message with zero Firecrawl requests if a fresh manifest was already on Drive.
When the Cloud rung fired, a final line reports credits remaining today.

**Recovery — a three-rung ladder.** Exactly one Firecrawl attempt is made. If it
yields under 5 KB of markdown — for any reason, including a blocked site, a failed
job, an exhausted budget, empty pages, or an account-level failure (401/402/429)
or network error — the handler scrapes the root URL **locally** with Crawl4AI,
free, and keeps whichever result is larger. If that still comes up short, it
scrapes the root URL through **Crawl4AI Cloud** (1 credit, no proxy) and again
keeps the larger result.

The paid cloud rung deliberately runs *after* the free local one: on the only real
failure observed to date, local was the rung that worked, and a paid rung ahead of
it would have spent credits to be overtaken by something free. Cloud exists for the
case local cannot solve — an IP-level block aimed at this machine's own address.

The cloud rung is **skipped silently when `CRAWL4AI_API_KEY` is unset**, and the
failure message says nothing about it, so the tool behaves exactly as it did with
two rungs for anyone without a Crawl4AI account.

Firecrawl is not retried: the Free tier allows only 2 `/crawl` requests per minute,
so a second attempt would rate-limit the next call. Crawl4AI Cloud is never retried
either — a 429 there means the daily quota is gone, not that it wants to be asked
again. Pass `wait_for_ms` / `proxy` explicitly when a host is known to need them. A
crawl that ends with no content returns a diagnosis naming **each** rung's failure,
never "saved 0 page(s)". Full detail: `docs/web-scraper-reference.md`.

**Retry behavior:** all Firecrawl HTTP requests (job start + status polling)
retry automatically on 429/408/500/502/503/504, honoring the `Retry-After`
header when present, else exponential backoff capped at 30s + jitter — per
Firecrawl's own documented error-handling guidance
(https://docs.firecrawl.dev/api-reference/errors).
