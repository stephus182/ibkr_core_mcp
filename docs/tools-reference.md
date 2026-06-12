# ClaudeToolkit — Tools Reference

All 33 tools exposed by `ClaudeToolkit.tools` and `ClaudeToolkit.execute()`. Each tool returns
`(text: str, fig: plotly.Figure | None)`. `fig` is only non-`None` for chart tools (currently none
— reserved for a future equity-curve chart tool).

Pass `toolkit.tools` directly to the Anthropic SDK `tools=` parameter. Route responses through
`toolkit.execute(block.name, block.input)`.

---

## Portfolio & Account

### `get_account_summary`
Retrieve net liquidation value, total cash, unrealized P&L, and realized P&L.

**Inputs:** none

**Output:** JSON with `netliquidation`, `totalcashvalue`, `unrealizedpnl`, `realizedpnl` amounts.

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

**Output:** JSON allocation object with `assetClass`, `group`, `sector`, `industry` sub-objects.

**IBKR endpoint:** `GET /portfolio/{accountId}/allocation`

---

### `get_pa_performance`
Portfolio NAV performance from IBKR Portfolio Analyst.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `period` | string | ✅ | `"last7days"`, `"last30days"`, `"ytd"`, `"last365days"`, `"alltime"` |

**Output:** NAV performance data for the requested period.

**IBKR endpoint:** `POST /pa/performance`

---

### `get_pa_transactions`
Transaction history from IBKR Portfolio Analyst.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `period` | string | ✅ | Same period values as `get_pa_performance` |

**Output:** Transaction list for the requested period.

**IBKR endpoint:** `POST /pa/transactions`

---

## Orders

### `get_live_orders`
Working orders — Submitted, PreSubmitted, PendingSubmit, ApiPending, PendingCancel.
Also returns `Inactive` orders (exist on IBKR but stalled, e.g. failed risk check).
Filled and Cancelled orders are excluded; use `get_trades` for executions.

**Inputs:** none

**Output:** JSON array of working orders. Each entry includes `orderId`, `ticker`, `side`,
`totalSize`, `price`, `orderType`, `status`.

**IBKR endpoint:** `GET /iserver/account/orders` (filtered by `_WORKING_STATUSES`)

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
Whatif preview — returns estimated cost, commission, margin impact, and buying power effect
**without placing the order**. Use this before proposing a trade to verify feasibility.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `symbol` | string | ✅ | Ticker, e.g. `"AAPL"` |
| `action` | string | ✅ | `"BUY"` or `"SELL"` |
| `quantity` | integer | ✅ | Number of shares/contracts |
| `order_type` | string | — | `"MKT"` (default), `"LMT"`, or `"STP"` |
| `limit_price` | number | — | Required when `order_type="LMT"` |

**Output:** JSON from IBKR `/whatif` endpoint with `equity`, `commission`, `marginImpact`,
`buyingPowerEffect`.

**IBKR endpoint:** `POST /iserver/account/{accountId}/orders/whatif`

---

## Trades

### `get_trades`
Trade history from IBKR or local SQLite store.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `symbol` | string | — | Filter by symbol |
| `source` | string | — | `"live"` (IBKR API, last 6 days) or `"store"` (SQLite, unlimited) — default `"store"` |
| `start` | string | — | Start date `YYYY-MM-DD` (store only) |
| `end` | string | — | End date `YYYY-MM-DD` (store only) |

**Output:** JSON array of trade executions.

**IBKR endpoint (live):** `GET /iserver/account/trades`
**Store:** `SQLiteStore.get_trades()`

---

### `sync_flex_trades`
Fetch full historical trade history from IBKR Flex Web Service and upsert into SQLite.
Requires `IBKR_FLEX_TOKEN` and `IBKR_FLEX_QUERY_ID` env vars.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `account_id` | string | — | IBKR account ID (resolved automatically if omitted) |

**Output:** Count of trades fetched and stored.

**IBKR endpoint:** Flex Web Service (`gdcdyn.interactivebrokers.com`)

---

## Market Data

### `fetch_market_data`
Fetch OHLCV historical bars. Checks Google Drive Parquet cache first; calls IBKR only on a miss.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `symbol` | string | ✅ | Ticker, e.g. `"AAPL"` |
| `period` | string | ✅ | History period: `"1Y"`, `"6M"`, `"3M"`, `"1M"`, `"1W"`, `"1D"` |
| `bar` | string | — | Bar size: `"1d"` (default), `"1h"`, `"30min"`, `"5min"`, `"1min"` |
| `end` | string | — | End date `YYYY-MM-DD` (defaults to today) |

**Output:** Summary with row count, date range, and last close.

**IBKR endpoint:** `GET /iserver/marketdata/history`

---

### `get_market_snapshot`
Live real-time snapshot for one or more symbols: last price, bid, ask, volume, high, low, change%.
Resolves symbols to conids automatically.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `symbols` | array[string] | ✅ | e.g. `["AAPL", "MSFT", "SPY"]` |
| `sec_type` | string | — | `"STK"` (default), `"FUT"`, `"OPT"`, `"FX"` |

**Output:** JSON array with live quote fields. Field codes: `"31"` = last price, `"84"` = bid,
`"86"` = ask, `"87"` = volume. IBKR may return field codes rather than friendly names for some data.

**Note:** IBKR snapshot subscriptions require a brief warm-up (≈1s). If the first call returns
empty data, retry once.

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
Trading hours and session information for a symbol.

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

**Output:** Formatted summary of current indicator values: RSI(14), MACD, MACD signal, BB upper/mid/lower,
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

**Sandbox:** `RestrictedPython` — no file I/O, no network, no `import`. `df`, `pd`, `np` are available.
Code is limited to 4096 characters and 10-second execution timeout.

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

**Output:** PineScript v5 code starting with `//@version=5`. Can be pasted directly into TradingView
Pine Editor.

**Note:** The generated code is a functional template. Entry/exit conditions use placeholder logic
that should be customized for your specific strategy.

---

## Alerts

### `get_alerts`
List all IBKR price alerts configured on the account.

**Inputs:** none

**Output:** JSON array of alerts. Each entry has `orderId` (the alert ID), `alertName`,
`alertActive` (1/0), `conditions` array.

**IBKR endpoint:** `GET /iserver/account/{accountId}/alerts`

---

### `create_price_alert`
Create a native IBKR server-side price alert. Alerts fire even when the app is closed and are
delivered to the IBKR mobile app.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `symbol` | string | ✅ | Ticker, e.g. `"AAPL"`, `"CL"` |
| `operator` | string | ✅ | `">="` (at or above) or `"<="` (at or below) |
| `price` | number | ✅ | Price threshold |
| `sec_type` | string | — | `"STK"` (default), `"FUT"`, `"OPT"`, `"FX"` |
| `name` | string | — | Human-readable label (auto-generated if omitted) |
| `repeat` | boolean | — | Repeat after firing (default `false`) |

**Output:** JSON confirmation from IBKR with the new alert's `orderId`.

**IBKR endpoint:** `POST /iserver/account/{accountId}/alert`

**Note:** Exchange is resolved from the contract — futures use their native exchange (NYMEX, CME),
not SMART.

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
| `max_results` | integer | — | Maximum to return (default 10, max 100) |

**Output:** JSON array of notifications. Each entry has `id`, `date`, `headline`, `body`, `isRead`.
Also includes total unread count.

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

**IBKR endpoint:** `POST /iserver/scanner/run`
