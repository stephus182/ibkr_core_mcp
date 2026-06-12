# IBKRClient — API Reference

Full reference for all `IBKRClient` methods. All methods return raw dicts/lists from the IBKR
Client Portal API unless noted. HTTP errors raise exceptions from `ibkr_core_mcp.exceptions`.

The client is initialized with a `Config` and an optional `AuthStrategy`:

```python
from ibkr_core_mcp import IBKRClient, Config
from ibkr_core_mcp.auth import BrowserCookieAuth  # default

config = Config.from_env()
client = IBKRClient(config)  # BrowserCookieAuth by default
```

**Security note:** `IBKRClient` only connects to localhost (`localhost`, `127.0.0.1`, `::1`).
Any other `IBKR_GATEWAY_URL` raises `ConfigError` at construction time.

---

## Session

### `ping() -> bool`
Quick connectivity check. Returns `True` if the gateway is reachable and authenticated.
Uses a 5-second timeout; never raises — returns `False` on any error.

### `get_auth_status() -> dict`
Full authentication status including `authenticated`, `competing`, `connected` fields.
**Endpoint:** `GET /iserver/auth/status`

### `tickle() -> bool`
Keep the session alive. Call every few minutes during idle periods.
Returns `True` on HTTP 200. Never raises.
**Endpoint:** `POST /tickle`

### `reauthenticate() -> dict`
Request a new authentication session. Use when `get_auth_status()` shows `authenticated=false`.
**Endpoint:** `POST /iserver/reauthenticate`

### `validate_sso() -> dict`
Validate the SSO token. Used after initial login to confirm the session is active.
**Endpoint:** `POST /sso/validate`

---

## Market Data

### `get_market_history(conid, period, bar, outside_rth) -> dict`
OHLCV bars for a contract.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `conid` | int | — | Contract ID (use `search_contract()` to find) |
| `period` | str | `"1Y"` | `"1D"`, `"1W"`, `"1M"`, `"3M"`, `"6M"`, `"1Y"`, `"2Y"`, `"5Y"` |
| `bar` | str | `"1d"` | `"1min"`, `"2min"`, `"5min"`, `"15min"`, `"30min"`, `"1h"`, `"2h"`, `"4h"`, `"1d"`, `"1w"`, `"1m"` |
| `outside_rth` | bool | `False` | Include pre/post-market bars |

**Returns:** `{"startTime": "...", "data": [{"o":..., "h":..., "l":..., "c":..., "v":..., "t":...}, ...]}`

**Endpoint:** `GET /iserver/marketdata/history`

**⚠ Hard cap:** This endpoint caps at ~84 daily bars regardless of the `period` parameter. Use `get_hmds_history()` for any request longer than ~4 months.

---

### `get_market_snapshot(conids, fields) -> list[dict]`
Live quotes for one or more contracts. Returns `[]` if the response is not a list.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `conids` | list[int] | — | Contract IDs |
| `fields` | list[str] | `["31","55","70","71","84","86"]` | Field codes to request |

**Common field codes:** `"31"` = last price, `"55"` = symbol, `"70"` = high, `"71"` = low,
`"84"` = bid, `"86"` = ask, `"87"` = volume.

**Note:** IBKR snapshot subscriptions require a warm-up period. Empty results on first call
are normal — retry after ≈1s.

**Endpoint:** `GET /iserver/marketdata/snapshot`

---

### `get_hmds_history(conid, period, bar, outside_rth) -> dict`
Historical Market Data Service — same parameters and return shape as `get_market_history()`.
Use this for all requests beyond ~4 months; supports up to 7Y of daily data for equities.
**This is the endpoint `ClaudeToolkit.fetch_market_data` uses.**

**Endpoint:** `GET /hmds/history`

---

### `get_md_snapshot(conids, fields) -> list[dict]`
Alternative snapshot endpoint (`/md/snapshot`). Same semantics as `get_market_snapshot()`.
Use when `/iserver/marketdata/snapshot` returns empty.

**Endpoint:** `GET /md/snapshot`

---

### `get_market_data_fields() -> dict`
Available field codes and their human-readable names.
**Endpoint:** `GET /iserver/marketdata/fields`

### `get_market_data_periods() -> dict`
Valid period strings for history requests.
**Endpoint:** `GET /iserver/marketdata/periods`

### `get_market_data_bars() -> dict`
Valid bar size strings for history requests.
**Endpoint:** `GET /iserver/marketdata/bars`

### `get_market_data_availability() -> dict`
Market data subscription availability for the account.
**Endpoint:** `GET /iserver/marketdata/availability`

### `unsubscribe_market_data(conid) -> dict`
Unsubscribe a specific contract from streaming market data.
**Endpoint:** `POST /iserver/marketdata/unsubscribe`

### `unsubscribe_all_market_data() -> dict`
Unsubscribe all active streaming market data subscriptions.
**Endpoint:** `POST /iserver/marketdata/unsubscribeall`

---

## Contract / Security Definition

### `search_contract(symbol, sec_type) -> list[dict]`
Resolve a symbol to one or more contracts.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `symbol` | str | — | Ticker, e.g. `"AAPL"`, `"CL"` |
| `sec_type` | str | `"STK"` | `"STK"`, `"FUT"`, `"OPT"`, `"FX"`, `"IND"`, `"CFD"`, `"BOND"` |

**Returns:** List of `{"conid": ..., "symbol": ..., "companyName": ..., "exchange": ..., "currency": ...}`

**Endpoint:** `GET /iserver/secdef/search`

---

### `get_contract_info(conid) -> dict`
Full contract metadata: exchange, currency, primary exchange, trading class, multiplier, etc.
**Endpoint:** `GET /iserver/contract/{conid}/info`

### `get_contract_info_and_rules(conid) -> dict`
Contract info plus trading rules (min tick, order types, etc.).
**Endpoint:** `GET /iserver/contract/{conid}/info-and-rules`

### `get_contract_algos(conid) -> list[dict]`
Available algorithmic order types for a contract.
**Endpoint:** `GET /iserver/contract/{conid}/algos`

### `get_secdef_info(conid) -> dict`
Security definition info (type, symbol, currency, exchange, listing exchange).
**Endpoint:** `GET /iserver/secdef/info`

### `get_secdef(conids) -> list[dict]`
Batch security definitions for multiple conids.
**Endpoint:** `GET /trsrv/secdef`

---

### `get_option_strikes(conid, sec_type, month, exchange) -> list[float]`
Available strike prices for an option chain.

| Parameter | Type | Default |
|-----------|------|---------|
| `conid` | int | — |
| `sec_type` | str | — |
| `month` | str | — | Format: `"JAN2026"` |
| `exchange` | str | `"SMART"` |

**Endpoint:** `GET /iserver/secdef/strikes`

---

### `get_option_chain(symbol, exchange, currency) -> dict`
Full options chain — all expirations, strikes, conids.
**Endpoint:** `GET /trsrv/secdef/chains`

### `get_bond_filters(symbol, issue_id) -> dict`
Available filter criteria for bond search.
**Endpoint:** `GET /iserver/secdef/bond-filters`

---

### `get_futures(symbols) -> list[dict]`
Futures contracts for root symbols.

**Note:** IBKR returns `{"CL": [...], "ES": [...]}` — this method flattens to a list.
Returns `[]` if the response shape is unexpected.

**Endpoint:** `GET /trsrv/futures`

---

### `get_stocks(symbols) -> list[dict]`
Stock contracts for symbols. Same dict-flattening behaviour as `get_futures()`.
**Endpoint:** `GET /trsrv/stocks`

---

### `get_trading_schedule(asset_class, symbol, exchange, exchange_filter) -> dict`
Trading hours, sessions, and timezone for a symbol/exchange.
**Endpoint:** `GET /trsrv/secdef/schedule`

### `get_currency_pairs(currency) -> list[dict]`
Available FX pairs for a base currency.
**Endpoint:** `GET /iserver/secdef/currency`

### `get_contract_rules(conid, is_buy) -> dict`
Order rules for a contract (min tick, valid order types, etc.).
**Endpoint:** `POST /iserver/contract/rules`

---

## Portfolio

### `get_accounts() -> list[dict]`
All accounts associated with the authenticated session.
**Returns:** `[{"accountId": "U1234567", ...}, ...]`
**Endpoint:** `GET /portfolio/accounts`

### `get_subaccounts() -> list[dict]`
Sub-accounts (for IB Family accounts / advisors).
**Endpoint:** `GET /portfolio/subaccounts`

### `get_account_meta(account_id) -> dict`
Account metadata (display name, status, type).
**Endpoint:** `GET /portfolio/{accountId}/meta`

### `get_account_summary(account_id) -> dict`
Net liquidation, cash, P&L. The response uses nested `{"amount": value}` objects.
**Endpoint:** `GET /portfolio/{accountId}/summary`

### `get_account_ledger(account_id) -> dict`
Cash balances by currency with detailed ledger fields.
**Endpoint:** `GET /portfolio/{accountId}/ledger`

### `get_account_allocation(account_id) -> dict`
Portfolio breakdown by asset class, sector, industry.
**Endpoint:** `GET /portfolio/{accountId}/allocation`

---

### `get_positions(account_id, page) -> list[dict]`
Open positions, paginated (page 0 = first 30).

**Returns:** `[{"conid": ..., "contractDesc": ..., "position": ..., "mktPrice": ...,
"mktValue": ..., "unrealizedPnl": ..., "realizedPnl": ...}, ...]`

**Endpoint:** `GET /portfolio/{accountId}/positions/{page}`

---

### `get_positions_by_conid(conid) -> list[dict]`
Position data for a specific contract across all accounts.
**Endpoint:** `GET /portfolio/positions/{conid}`

### `get_position(account_id, conid) -> dict`
Position for a specific account + contract pair.
**Endpoint:** `GET /portfolio/{accountId}/position/{conid}`

### `get_combo_positions(account_id) -> list[dict]`
Combo/spread positions.
**Endpoint:** `GET /portfolio/{accountId}/combo/positions`

### `get_portfolio_allocation(account_ids) -> dict`
Aggregated allocation across multiple accounts.
**Endpoint:** `POST /portfolio/allocation`

### `invalidate_positions_cache(account_id) -> dict`
Force-refresh the IBKR position cache. Call before `get_positions()` if data looks stale.
**Endpoint:** `POST /portfolio/{accountId}/positions/invalidate`

---

## Orders (Read-Only)

### `get_live_orders() -> list[dict]`
Working orders only — filtered to `_WORKING_STATUSES`:
`{"PreSubmitted", "Submitted", "ApiPending", "PendingSubmit", "PendingCancel", "Inactive"}`.

`Inactive` = order exists on IBKR but is stalled (e.g. failed risk check). These require
user action to resolve.

**Endpoint:** `GET /iserver/account/orders`

---

### `get_order_status(order_id) -> dict`
Full order details for a specific order ID.
**Endpoint:** `GET /iserver/account/order/status/{orderId}`

### `get_trades() -> list[dict]`
Recent trade executions (last 6 days).
**Endpoint:** `GET /iserver/account/trades`

---

## Portfolio Analyst

### `get_pa_periods(account_ids) -> list[str]`
Available period strings for Portfolio Analyst queries.
**Endpoint:** `POST /pa/allperiods`

### `get_pa_performance(account_ids, period) -> dict`
NAV performance for the given period.
**Valid periods:** `"last7days"`, `"last30days"`, `"ytd"`, `"last365days"`, `"alltime"`
**Endpoint:** `POST /pa/performance`

### `get_pa_transactions(account_ids, period) -> list[dict]`
Transaction history from Portfolio Analyst.
**Endpoint:** `POST /pa/transactions`

---

## Scanner

### `get_scanner_params() -> dict`
Available scanner types and filter parameters.
**Endpoint:** `GET /iserver/scanner/params`

### `run_iserver_scanner(params) -> list[dict]`
Run a scanner with full parameter control.
**Endpoint:** `POST /iserver/scanner/run`

### `run_hmds_scanner(params) -> list[dict]`
Run an HMDS-based historical scanner.
**Endpoint:** `POST /hmds/scanner`

---

## FYI / Notifications

### `get_notifications(max_results) -> list[dict]`
Account notifications — order fills, margin calls, system messages. Max 100.
**Endpoint:** `GET /fyi/notifications`

### `get_unread_count() -> int`
Number of unread FYI notifications.
**Endpoint:** `GET /fyi/unreadnumber`

### `get_delivery_options() -> dict`
Notification delivery channel configuration.
**Endpoint:** `GET /fyi/deliveryoptions`

### `get_mta_alert() -> dict`
Mobile Trading Alerts — account-level watchdog alerts.
**Endpoint:** `GET /iserver/account/mta`

### `mark_notification_read(notification_id) -> dict`
Mark a FYI notification as read.
**Endpoint:** `POST /fyi/notifications/{notificationId}/read`

### `update_delivery_option(device_id, option, enabled) -> dict`
Enable/disable a notification delivery channel.
**Endpoint:** `POST /fyi/deliveryoptions/{option}`

---

## Alerts (IBKR Native)

### `get_alerts(account_id) -> list[dict]`
All price alerts configured on the account. The `orderId` field is the alert ID.
**Endpoint:** `GET /iserver/account/{accountId}/alerts`

### `create_alert(account_id, alert) -> dict`
Create a price alert. The `alert` dict must match the IBKR alert payload schema:

```python
alert = {
    "orderId": 0,
    "alertName": "AAPL >= 200",
    "alertMessage": "",
    "alertRepeatable": 0,        # 1 = repeat
    "expireTime": "",
    "tif": "GTC",
    "outsideRth": False,
    "isSizeCondition": False,
    "conditions": [{
        "type": 1,               # 1 = Price condition
        "conid": 265598,
        "exchange": "NASDAQ",    # use contract's actual exchange, not SMART for futures
        "conditionType": "Price", # camelCase required
        "operator": ">=",
        "value": "200.0",        # string, not number
    }],
}
```

Use `ClaudeToolkit.execute("create_price_alert", ...)` instead — it resolves conid and
exchange automatically.

**Endpoint:** `POST /iserver/account/{accountId}/alert`

---

### `delete_alert(account_id, alert_id) -> dict`
Delete an alert permanently.
**Endpoint:** `DELETE /iserver/account/{accountId}/alert/{alertId}`

### `activate_alert(account_id, alert_id, activate) -> dict`
Toggle alert on/off. `activate=True` enables; `activate=False` disables.
**Endpoint:** `POST /iserver/account/{accountId}/alert/activate`

---

## Watchlists

### `get_watchlists() -> list[dict]`
All watchlists for the account.
**Endpoint:** `GET /iserver/account/watchlists`

### `get_watchlist(watchlist_id) -> dict`
Contents of a specific watchlist.
**Endpoint:** `GET /iserver/account/watchlist/{watchlistId}`

### `create_watchlist(name, rows) -> dict`
Create a new watchlist. `rows` is a list of `{"C": conid}` objects.
**Endpoint:** `POST /iserver/account/watchlist`

### `delete_watchlist(watchlist_id) -> dict`
Delete a watchlist.
**Endpoint:** `DELETE /iserver/account/watchlist/{watchlistId}`

---

## Events Contracts

### `get_event_contracts(conids) -> list[dict]`
Event-based contracts (e.g. political outcome contracts).
**Endpoint:** `GET /events/contracts`

### `get_event_contract(conid) -> dict`
Details for a specific event contract.
**Endpoint:** `GET /events/show`

---

## Order Management (Write — Human Auth Required)

These four methods enforce two sequential security gates before any API call is made:
1. **Gate 1:** macOS Touch ID (`LAPolicyDeviceOwnerAuthenticationWithBiometrics`, 60s timeout)
2. **Gate 2:** tkinter modal dialog with full order details + 60s countdown (Enter key disabled)

If either gate fails or times out, `HumanAuthError` is raised and no HTTP call is made.

> **ClaudIA constraint:** `ClaudeToolkit` deliberately exposes no tools that call these methods.
> Order execution is a UI-layer action triggered by a physical button click, not an LLM tool call.

### `place_order(account_id, order) -> list[dict]`
Place a new order after both security gates pass.
**Endpoint:** `POST /iserver/account/{accountId}/orders`

### `modify_order(account_id, order_id, order) -> dict`
Modify an existing order after both security gates pass.
**Endpoint:** `POST /iserver/account/{accountId}/order/{orderId}`

### `cancel_order(account_id, order_id) -> dict`
Cancel an order after both security gates pass.
**Endpoint:** `DELETE /iserver/account/{accountId}/order/{orderId}`

### `reply_order(reply_id, ibkr_confirmed) -> list[dict]`
Confirm an order that requires an explicit IBKR reply (e.g. after a warning). Both gates required.
**Endpoint:** `POST /iserver/reply/{replyId}`

---

### `get_order_preview(account_id, order) -> dict`
Whatif preview — cost, commission, margin impact. No order placed, no security gates.
**Endpoint:** `POST /iserver/account/{accountId}/orders/whatif`

---

## Account / Admin

### `get_pnl() -> dict`
Real-time partitioned P&L — daily, unrealized, realized — across all positions.
**Endpoint:** `GET /iserver/account/pnl/partitioned`

### `get_brokerage_accounts() -> dict`
All brokerage accounts (alias for `GET /portfolio/accounts` — same data as `get_accounts()`).
**Endpoint:** `GET /portfolio/accounts`

### `switch_account(account_id) -> dict`
Switch the active account (for advisors / family accounts).
**Endpoint:** `POST /iserver/account`

### `logout() -> dict`
End the current session.
**Endpoint:** `POST /logout`

---

## Error Handling

| Exception | When raised |
|-----------|-------------|
| `IBKRAuthError` | HTTP 401 — session expired or not authenticated |
| `IBKRRateLimitError` | HTTP 429 after 3 retries with exponential backoff |
| `IBKRAPIError` | Other HTTP 4xx/5xx errors (has `.status_code` attribute) |
| `ConfigError` | Invalid `gateway_url` (not localhost) or invalid `account_id` format |
| `HumanAuthError` | Touch ID denied, timed out, or biometrics unavailable |

All methods use `with_retry()` internally (3 retries, 1s base backoff, handles 429 and 503).
401 responses are not retried — they raise `IBKRAuthError` immediately.
