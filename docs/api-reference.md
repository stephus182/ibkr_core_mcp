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
Uses a 5-second timeout; never raises — returns `False` on any error. This is the method
`ConnectivityChecker` polls every 60s in production.
**Endpoint:** `GET /iserver/auth/status` — official docs list this endpoint as `POST`
(see Note below); GET is production-verified, not changed without a live test.
Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#auth-status

### `get_auth_status() -> dict`
Full authentication status including `authenticated`, `competing`, `connected` fields.
No callers elsewhere in the codebase as of 2026-06-30.
**Endpoint:** `GET /iserver/auth/status` — same documented-vs-implemented HTTP method
discrepancy as `ping()` (docs say `POST`); see ping()'s entry above.
Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#auth-status

### `tickle() -> bool`
Keep the session alive. Call every few minutes during idle periods.
Returns `True` on HTTP 200. Never raises.
**Endpoint:** `POST /tickle`
Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#tickle

### `reauthenticate() -> dict`
Request a new authentication session. Use when `get_auth_status()` shows `authenticated=false`.
**Officially deprecated** — docs direct all reauthentication to `POST /iserver/auth/ssodh/init`
instead, which is not implemented here (it's invoked by the browser-based Gateway login flow,
not application code). Never call proactively — it terminates any active authenticated session, including fresh logins.
**Endpoint:** `POST /iserver/reauthenticate` (Deprecated)
Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#reauthenticate

### `validate_sso() -> dict`
Validate the SSO token. Used after initial login to confirm the session is active. No callers
elsewhere in the codebase as of 2026-06-30.
**Endpoint:** `GET /sso/validate`
Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#sso-validate

---

## Market Data

### `get_market_history(conid, period, bar, outside_rth) -> dict`
Single-page OHLCV bars. **Maximum 1000 data points per request** (verified from official docs).
For requests that may exceed this, use `get_market_history_paginated()`.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `conid` | int | — | Contract ID (use `search_contract()` to find) |
| `period` | str | `"1Y"` | Full range: `{1-1000}d`, `{1-792}w`, `{1-182}m`, `{1-15}y` |
| `bar` | str | `"1d"` | `"1min"`, `"2min"`, `"5min"`, `"15min"`, `"30min"`, `"1h"`, `"2h"`, `"4h"`, `"8h"`, `"1d"`, `"1w"`, `"1m"` |
| `outside_rth` | bool | `False` | Include pre/post-market bars |

**Returns:** `{"startTime": "...", "data": [{"o":..., "h":..., "l":..., "c":..., "v":..., "t":...}, ...]}` — `t` is UNIX milliseconds UTC.

**Rate limit:** 5 concurrent requests.
**Endpoint:** `GET /iserver/marketdata/history`
Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#hist-md

---

### `get_market_history_paginated(conid, period, bar, outside_rth) -> dict`
**This is the endpoint `ClaudeToolkit.fetch_market_data` uses.**

Same parameters and return shape as `get_market_history()`, but automatically paginates
requests that would exceed the 1000-point limit. Uses `startTime` to walk backwards from
today in chunks, then merges and deduplicates.

| Bar size | Chunk size | Bars per chunk (approx) |
|----------|------------|-------------------------|
| `1d` | 1000 calendar days | ~690 trading days |
| `1w` | 1000 calendar days | ~143 weeks |
| `1h` | 197 calendar days | ~128 days × 6.5h |

**Endpoint:** `GET /iserver/marketdata/history` (chunked via startTime)
Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#hist-md

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
Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#md-snapshot

---

### `get_regulatory_snapshot(conid) -> dict`
Regulatory (NBBO-grade) market snapshot for a **single** contract. Responds synchronously
(no subscription warm-up needed).

**WARNING: incurs a fee of $0.01 USD per call** unless the account already holds a
direct exchange market data subscription. Applies to live and paper accounts.
**Do NOT use as a fallback for `get_market_snapshot()`** — that endpoint is free.
Use this only when compliance-grade NBBO data is specifically required.
**Endpoint:** `GET /md/regsnapshot` — query param: `conid` (single int, as string)
Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#regulatory-snapshot

---

### `unsubscribe_market_data(conid) -> dict`
Cancel streaming market data for a single contract.
**Endpoint:** `POST /iserver/marketdata/unsubscribe`
Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#md-unsubscribe-single

### `unsubscribe_all_market_data() -> dict`
Cancel all active streaming market data subscriptions. No parameters.
**Endpoint:** `GET /iserver/marketdata/unsubscribeall`
Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#md-unsubscribe-all

---

## Contract / Security Definition

### `search_contract(symbol, sec_type) -> list[dict]`
Resolve a symbol to one or more contracts.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `symbol` | str | — | Ticker, e.g. `"AAPL"` |
| `sec_type` | str | `"STK"` | Officially documented valid values: `"STK"`, `"IND"`, `"BOND"` only |

**Returns:** List of `{"conid": ..., "symbol": ..., "companyName": ..., "exchange": ..., "currency": ...}`

**Endpoint:** `GET /iserver/secdef/search`

**Not supported here** — use the documented endpoint for these asset classes instead:
- FUT → `get_futures()` (`GET /trsrv/futures`)
- CASH (FX) → `get_currency_pairs()` (`GET /iserver/currency/pairs`)
- OPT → `search_contract()` for the underlying, then `get_secdef_info()` (`GET /iserver/secdef/info`) for the option conid

Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#sec-search

---

### `get_contract_info(conid) -> dict`
Full contract metadata: exchange, currency, primary exchange, trading class, multiplier, etc.
**Endpoint:** `GET /iserver/contract/{conid}/info`
Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#info-conid-contract

### `get_contract_info_and_rules(conid) -> dict`
Contract info plus trading rules (min tick, order types, etc.).
**Endpoint:** `GET /iserver/contract/{conid}/info-and-rules`
Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#info-rules-contract

### `get_contract_algos(conid) -> list[dict]`
Available algorithmic order types for a contract.
**Endpoint:** `GET /iserver/contract/{conid}/algos`
Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#algo-conid-contract

### `get_secdef_info(conid) -> dict`
Security definition info (type, symbol, currency, exchange, listing exchange).
**Endpoint:** `GET /iserver/secdef/info`
Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#secdef-info-contract

### `get_secdef(conids) -> list[dict]`
Batch security definitions for multiple conids.
**Endpoint:** `GET /trsrv/secdef`
Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#trsrv-conid-contract

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
**WARNING: `/trsrv/secdef/chains` does not exist in official IBKR docs (verified 2026-06-30).
This method currently raises `IBKRAPIError` (404) on every call.**

The documented multi-step flow for option chains:
1. `search_contract(symbol, "STK")` → get underlying conid (required before step 2)
2. `get_option_strikes(conid, "OPT", month, exchange)` → strikes per expiry month
Available expiry months are returned in the secdef/search response.

**Endpoint:** `GET /trsrv/secdef/chains` (DOES NOT EXIST)
Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#search-symbol-contract

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

### `get_trading_schedule(asset_class, symbol, exchange, exchange_filter) -> list[dict]`
Trading hours, sessions, and timezone for a symbol/exchange.
Returns a list of schedule objects (verified live 2026-06-30 — returns `list`, not `dict`).
**Endpoint:** `GET /trsrv/secdef/schedule`

### `get_currency_pairs(currency) -> list[dict]`
Available FX pairs for a target currency.

**Note:** IBKR returns `{"USD": [{"symbol": "USD.SGD", "conid": ..., "ccyPair": "SGD"}, ...]}` —
this method flattens to a list. Same dict-flattening behaviour as `get_futures()`/`get_stocks()`.

Corrected 2026-06-30: previously called the undocumented `/iserver/secdef/currency`, which
always returned `[]`. `/iserver/secdef/search` does not document `CASH`/FX as a valid `secType`
either — this is the only documented FX resolution path.

**Endpoint:** `GET /iserver/currency/pairs`

Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#get-currency-pairs

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
Recent trade executions (last ~6 days).

**Note:** `?days=7` is appended to extend the lookback window. Without it, IBKR returns today's
session only. The `days` parameter is not documented in the public IBKR CP API reference (requires
authentication to access) — this behavior was verified by testing, not official documentation.

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

---

## FYI / Notifications

### `get_notifications(max_results) -> list[dict]`
Account notifications — order fills, margin calls, system messages. Max 10 per request (official API limit).
Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
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
Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#get-alert-list

### `get_alert(alert_id) -> dict`
Full details for a specific alert by ID. **Not** account-scoped in the URL — unlike
every other alert endpoint below, this one takes only the alert ID and a required
`type=Q` query parameter; IBKR resolves the alert from the session's logged-in account.
**Endpoint:** `GET /iserver/account/alert/{order_id}?type=Q`
Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#get-alert

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
Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#create-alert

---

### `delete_alert(account_id, alert_id) -> dict`
Delete an alert permanently. If `alert_id` is `0`, deletes all alerts.
**Endpoint:** `DELETE /iserver/account/{accountId}/alert/{alertId}`
Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#delete-alert

### `activate_alert(account_id, alert_id, activate) -> dict`
Toggle alert on/off. `activate=True` enables; `activate=False` disables.
**Endpoint:** `POST /iserver/account/{accountId}/alert/activate`
Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#activate-alert

---

## Watchlists

### `get_watchlists() -> list[dict]`
All watchlists for the account.
**Endpoint:** `GET /iserver/watchlists` — query param `SC=USER_WATCHLIST`
Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#all-watchlists

### `get_watchlist(watchlist_id) -> dict`
Contents of a specific watchlist. `watchlist_id` is passed as query param `id`.
**Endpoint:** `GET /iserver/watchlist`
Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#watchlist-info

### `create_watchlist(name, rows) -> dict`
Create a new watchlist. `rows` is a list of `{"C": conid}` objects.
**Endpoint:** `POST /iserver/watchlist`
Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#create-watchlist

### `delete_watchlist(watchlist_id) -> dict`
Delete a watchlist. `watchlist_id` passed as query param `id`.
**Endpoint:** `DELETE /iserver/watchlist`
Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#delete-watchlist

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
Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#account-pnl

### `get_brokerage_accounts() -> dict`
List of accounts the user has trading access to, their aliases, the currently selected
account, and per-account capability flags (`supportsCashQty`, `supportsFractions`,
`allowCustomerTime`, etc). **Officially documented as required before modifying an order
or querying open orders.** `IBKRClient._ensure_accounts_initialized()` calls this once per
client instance (cached) and runs automatically at the top of every order read/write
method (`get_live_orders`, `get_order_status`, `place_order`, `modify_order`,
`cancel_order`, `reply_order`, `get_order_preview`) — callers do not need to call this
directly under normal use.

**Returns:** `dict` with keys: `accounts` (list of account ID strings), `acctProps`, `aliases`, `allowFeatures`, `chartPeriods`, `groups`, `profiles`, `selectedAccount`. Verified live 2026-06-30 — NOT a bare list.

**Endpoint:** `GET /iserver/accounts`
Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#get-brokerage-accounts

### `switch_account(account_id) -> dict`
Switch the active account (for advisors / family accounts).
**Endpoint:** `POST /iserver/account`
Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#switch-account

### `logout() -> dict`
End the current session.
**Endpoint:** `POST /logout`
Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#logout

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
