# IBKRClient — API Reference

Full reference for all 74 public `IBKRClient` methods. All methods return raw dicts/lists from
the IBKR Client Portal API unless noted. HTTP errors raise exceptions from
`ibkr_core_mcp.exceptions`. Every endpoint below is sourced from the official Client Portal Web
API reference at https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/introduction (anchored
per-endpoint below) unless explicitly marked unverified.

The client is initialized with a `Config` and an optional `AuthStrategy`:

```python
from ibkr_core_mcp import IBKRClient, Config
from ibkr_core_mcp.auth import BrowserCookieAuth  # default

config = Config.from_env()
client = IBKRClient(config)  # BrowserCookieAuth by default
```

**Security note:** `IBKRClient` only connects to localhost (`localhost`, `127.0.0.1`, `::1`).
Any other `IBKR_GATEWAY_URL` raises `ConfigError` at construction time.

**Account/order ID initialization:** Every order read/write method (`get_live_orders`,
`get_orders_raw`, `get_order_status`, `place_order`, `modify_order`, `cancel_order`,
`reply_order`, `get_order_preview`) calls `get_brokerage_accounts()` once per client instance
before its own request — the official docs require `GET /iserver/accounts` to run before
order operations. The call is cached on `_accounts_initialized`; callers never need to invoke
`get_brokerage_accounts()` directly under normal use.

---

## Session

### `ping() -> bool`
Quick connectivity check. Returns `True` if the gateway is reachable and authenticated.
Uses a 5-second timeout; never raises — returns `False` on any error. This is the method
`ConnectivityChecker` polls every 60s in production. Retries once after `tickle()` to work
around an IBKR gateway quirk where the first `/iserver/auth/status` call of a new session
returns `authenticated=false` even when fully logged in.
**Endpoint:** `GET /iserver/auth/status` — official docs list this endpoint as `POST`
(see Note below); GET is production-verified, not changed without a live test.
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/session/authentication-status

### `get_auth_status() -> dict`
Full authentication status including `authenticated`, `competing`, `connected` fields.
No callers elsewhere in the codebase as of 2026-06-30.
**Endpoint:** `GET /iserver/auth/status` — same documented-vs-implemented HTTP method
discrepancy as `ping()` (docs say `POST` with an empty JSON body); see `ping()`'s entry above.
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/session/authentication-status

### `tickle() -> bool`
Keep the session alive. Call every few minutes during idle periods. `ConnectivityChecker`
calls this every 60s as a side effect of its `/tickle` poll, preventing IBKR auto-logout.
Returns `True` on HTTP 200. Never raises.
**Endpoint:** `POST /tickle`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/session/ping-the-server

### `reauthenticate() -> dict`
Request a new authentication session. Use only when `get_auth_status()` shows
`authenticated=false` and the user has not recently logged in.
**Officially deprecated** — docs direct all reauthentication to `POST /iserver/auth/ssodh/init`
instead, described as "essential for using all endpoints besides `/portfolio`." That endpoint is
not implemented here — it's invoked by the browser-based Gateway login flow
(`https://localhost:5055`) itself, not application code; `GatewayManager` relies on that browser
flow rather than calling it directly.
**Never call proactively** — it terminates any active authenticated session, including fresh
logins.
**Endpoint:** `POST /iserver/reauthenticate` (Deprecated)
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/session/re-authenticate-the-brokerage-session-deprecated

### `validate_sso() -> dict`
Validate the SSO token. Used after initial login to confirm the session is active. No callers
elsewhere in the codebase as of 2026-06-30.
**Endpoint:** `GET /sso/validate`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/session/validate-sso

---

## Market Data

### `get_market_history(conid, period, bar, outside_rth) -> dict`
Single-page OHLCV bars. **Maximum 1000 data points per request; max 5 concurrent requests**
(both officially documented — exceeding either returns HTTP 429). For requests that may exceed
the point limit, use `get_market_history_paginated()`.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `conid` | int | — | Contract ID (use `search_contract()` to find) |
| `period` | str | `"1y"` | `{1-30}min`, `{1-8}h`, `{1-1000}d`, `{1-792}w`, `{1-182}m`, `{1-15}y` |
| `bar` | str | `"1d"` | `1min`, `2min`, `3min`, `5min`, `10min`, `15min`, `30min`, `1h`, `2h`, `3h`, `4h`, `8h`, `1d`, `1w`, `1m` |
| `outside_rth` | bool | `False` | Include pre/post-market bars |

**Case sensitivity (verified live 2026-07-06):** IBKR period/bar units are lowercase.
Uppercase inputs are **not rejected** — the API silently substitutes a ~84-bar default
(`period="6M"` returned 4 months of dailies; `"6m"` returned the true 6 months). This method
lowercases both inputs before the request to avoid the trap.

**Step size** — valid `bar` range and default per `period` (from official docs):

| `period` | valid `bar` range | default `bar` |
|---|---|---|
| `1min` | `1min` | `1min` |
| `1h` | `1min`–`8h` | `1min` |
| `1d` | `1min`–`8h` | `1min` |
| `1w` | `10min`–`1w` | `15min` |
| `1m` | `1h`–`1m` | `30min` |
| `3m` | `2h`–`1m` | `1d` |
| `6m` | `4h`–`1m` | `1d` |
| `1y` | `8h`–`1m` | `1d` |
| `2y` | `1d`–`1m` | `1d` |
| `3y` | `1d`–`1m` | `1w` |
| `15y` | `1w`–`1m` | `1w` |

**Returns:** `{"startTime": "...", "data": [{"o":..., "h":..., "l":..., "c":..., "v":..., "t":...}, ...]}` — `t` is UNIX milliseconds UTC.

**Endpoint:** `GET /iserver/marketdata/history`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/market-data/historical-market-data

---

### `get_market_history_paginated(conid, period, bar, outside_rth) -> dict`
**This is the endpoint `ClaudeToolkit.fetch_market_data` uses.**

Same parameters and return shape as `get_market_history()`, but automatically paginates
requests that would exceed the 1000-point limit. Walks backwards from today in calendar-day
chunks sized to stay under 80% of the limit (`_CHUNK_SAFETY = 0.80`), using the `startTime`
parameter, then merges, sorts by timestamp, and deduplicates.

**Chunk sizes by bar** (targeting 80% of the 1000-point limit):

| Bar size | Chunk size | Bars per chunk (approx) |
|----------|------------|-------------------------|
| `1d` | 1000 calendar days | ~690 trading days |
| `1w` | 1000 calendar days | ~142 trading weeks |
| `1h` | 246 calendar days | ~160 trading days × 6.5h |
| `1m` | 1000 calendar days | ~33 months |

**Endpoint:** `GET /iserver/marketdata/history` (chunked via `startTime`)
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/market-data/historical-market-data

---

### `get_market_snapshot(conids, fields) -> list[dict]`
Live quotes for one or more contracts. Returns `[]` if the response is not a list.
**Limits:** max 100 conids and max 50 fields per request (officially documented).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `conids` | list[int] | — | Contract IDs |
| `fields` | list[str] | `["31","55","70","71","82","83","84","86","87","6509"]` | Field codes to request |

**Default field codes:**

| Code | Meaning |
|---|---|
| `31` | Last Price — may be prefixed `C` (prev close) or `H` (halted) |
| `55` | Symbol |
| `70` | High — current day |
| `71` | Low — current day |
| `82` | Change — price change vs. prior close |
| `83` | Change % |
| `84` | Bid Price — highest bid |
| `86` | Ask Price — lowest ask |
| `87` | Volume — day volume (`K`/`M` suffix for thousands/millions) |
| `6509` | Availability — first char: `R`=RealTime, `D`=Delayed, `N`=NotSubscribed, `Z`=Frozen, `Y`=FrozenDelayed, `O`=API agreement incomplete |

**Subscription note:** field `6509` starting with `N` means no market data subscription for
that exchange. NYSE, NASDAQ, and NYSE Arca (ETFs) each require separate IBKR subscriptions —
without one, price fields are absent and `6509` returns `N`. Check Account Management →
Settings → Market Data Subscriptions.

**Warm-up note:** the first snapshot call for a new conid initializes the subscription but
returns no price fields — empty results on first call are normal, retry after ≈1s.

Note: `/iserver/accounts` is officially documented as required only before order writes/reads
(see `get_brokerage_accounts()`), not before market data snapshots — this method does not call it.

**Endpoint:** `GET /iserver/marketdata/snapshot`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/market-data/live-market-data-snapshot
Changelog: https://www.interactivebrokers.com/docs/web-api/changelog

---

### `unsubscribe_market_data(conid) -> dict`
Cancel streaming market data for a single contract.
**Endpoint:** `POST /iserver/marketdata/unsubscribe`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/market-data/unsubscribe-single

### `unsubscribe_all_market_data() -> dict`
Cancel all active streaming market data subscriptions. No parameters.
**Endpoint:** `GET /iserver/marketdata/unsubscribeall`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/market-data/unsubscribe-all

---

## Contract / Security Definition

### `search_contract(symbol, sec_type) -> list[dict]`
Resolve a symbol to one or more contracts. Returns `[]` if no match.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `symbol` | str | — | Ticker, e.g. `"AAPL"` |
| `sec_type` | str | `"STK"` | Officially documented valid values: `"STK"`, `"IND"`, `"BOND"` only |

**Returns:** `[{"conid": ..., "symbol": ..., "companyName": ..., "exchange": ..., "currency": ...}, ...]`

**Not supported here** — use the documented endpoint for these asset classes instead:
- `FUT` → `get_futures()` (`GET /trsrv/futures`)
- `CASH` (FX) → `get_currency_pairs()` (`GET /iserver/currency/pairs`)
- `OPT` → `get_option_chain()` (wraps `search_contract()` for the underlying + `get_option_strikes()`), or manually via `search_contract()` then `get_secdef_info()` (`GET /iserver/secdef/info`) for a specific option conid

**Endpoint:** `GET /iserver/secdef/search`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/contract/search-contract-by-symbol

---

### `get_contract_info(conid) -> dict`
Full contract metadata: exchange, currency, primary exchange, trading class, multiplier, etc.
**Endpoint:** `GET /iserver/contract/{conid}/info`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/contract/contract-information-by-contract-id

### `get_contract_info_and_rules(conid) -> dict`
Contract info plus trading rules (min tick, order types, etc.).
**Endpoint:** `GET /iserver/contract/{conid}/info-and-rules`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/contract/find-all-info-and-rules-for-a-given-contract

### `get_contract_algos(conid) -> list[dict]`
Available algorithmic order types for a contract. Returns `[]` if none.
**Endpoint:** `GET /iserver/contract/{conid}/algos`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/contract/search-algo-params-by-contract-id

### `get_secdef_info(conid) -> dict`
Security definition info (type, symbol, currency, exchange, listing exchange).
**Endpoint:** `GET /iserver/secdef/info`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/contract/search-sec-def-information-by-conid

### `get_secdef(conids) -> list[dict]`
Batch security definitions for multiple conids. Returns `[]` if response is not a list.
**Endpoint:** `GET /trsrv/secdef`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/contract/search-the-security-definition-by-contract-id

---

### `get_option_strikes(conid, sec_type, month, exchange) -> dict[str, list[float]]`
Available strikes for one expiry month, split into call/put arrays.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `conid` | int | — | Underlying's conid |
| `sec_type` | str | — | `"OPT"` |
| `month` | str | — | `{3-char month}{2-char year}`, e.g. `"JAN26"` (**not** `"JAN2026"`) |
| `exchange` | str | `"SMART"` | |

**Returns:** `{"call": [...], "put": [...]}` — the documented response shape (there is no
`"strike"` key).

**Gotcha (officially documented):** this endpoint **always returns empty arrays** unless
`GET /iserver/secdef/search` was called for the same underlying beforehand, in the same
session, **without** the `name` query field — including `name=true` on that prior search call
also suppresses strikes data. `get_option_chain()` below handles this automatically; if you
call `get_option_strikes()` directly, call `search_contract()` for the underlying first.

**Endpoint:** `GET /iserver/secdef/strikes`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/contract/search-strikes-by-underlying-contract-id

---

### `get_option_chain(symbol, month, exchange) -> dict`
Option chain for an underlying, via the documented two-step discovery flow.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `symbol` | str | — | Underlying ticker |
| `month` | str \| None | `None` | `{3-char month}{2-char year}`, e.g. `"JAN26"`; defaults to the nearest available expiry |
| `exchange` | str | `"SMART"` | |

1. `GET /iserver/secdef/search?symbol=<symbol>` — required first call; primes the session
   (see `get_option_strikes()`'s gotcha above) and is the source of the `OPT` section's
   available expiry months (a `;`-delimited string, e.g. `"JAN26;FEB26;..."`).
2. `GET /iserver/secdef/strikes` for the resolved month.

**Returns:** `{"symbol": ..., "conid": ..., "months": [all expiries], "month": <resolved>,
"call": [strikes], "put": [strikes]}`. Raises `IBKRAPIError` if the underlying has no `OPT`
section in its `secdef/search` response, or that section lists no expiry months.

Reimplemented 2026-07-07 (audit register item 6) — replaces a previous call to
`/trsrv/secdef/chains`, an endpoint absent from the documented CP API that 404'd on every call.
This method **no longer 404s**; it composes the two documented endpoints above internally, and
no longer takes a `currency` parameter.

**Endpoints:** `GET /iserver/secdef/search` + `GET /iserver/secdef/strikes`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/contract/search-contract-by-symbol

---

### `get_bond_filters(symbol, issue_id) -> dict`
Available filter criteria for bond search. `issue_id` comes from a prior
`/iserver/secdef/search` call and can in turn be passed to `/iserver/secdef/info?issuerId=...`.
**Endpoint:** `GET /iserver/secdef/bond-filters`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/contract/search-bond-filter-information

---

### `get_futures(symbols) -> list[dict]`
Futures contracts for root symbols.

**Note:** IBKR returns `{"CL": [...], "ES": [...]}` — this method flattens to a list.
Returns `[]` if the response shape is unexpected.

**Endpoint:** `GET /trsrv/futures`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/contract/security-future-by-symbol

---

### `get_stocks(symbols) -> list[dict]`
Stock contracts for symbols. Same dict-flattening behaviour as `get_futures()`.
Each record is one issuer — `{name, assetClass, contracts: [{conid, exchange, isUS}]}` —
and `isUS` is the **only** US-listing signal any contract endpoint returns. This is the
endpoint IBKR designates for resolving stock symbols into conids, and conid is assigned
per *(product, currency)*, so a ticker alone does not identify a contract.
See `docs/symbology-reference.md` for the resolution rule and the IGV defect it fixed.
**Endpoint:** `GET /trsrv/stocks`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/contract/security-stocks-by-symbol

---

### `get_trading_schedule(asset_class, symbol, exchange, exchange_filter) -> list[dict]`
Trading hours, sessions, and timezone for a symbol/exchange.
Returns a list of schedule objects (verified live 2026-06-30 — returns `list`, not `dict`).
**Endpoint:** `GET /trsrv/secdef/schedule`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/contract/trading-schedule-by-symbol

### `get_currency_pairs(currency) -> list[dict]`
Available FX pairs for a target currency.

**Note:** IBKR returns `{"USD": [{"symbol": "USD.SGD", "conid": ..., "ccyPair": "SGD"}, ...]}` —
this method flattens to a list. Same dict-flattening behaviour as `get_futures()`/`get_stocks()`.

Corrected 2026-06-30: previously called the undocumented `/iserver/secdef/currency`, which
always returned `[]` (the response is a dict, not a list, so the old `isinstance(list)` check
silently discarded every result). `/iserver/secdef/search` also does not document `CASH` as a
valid `secType` (only `STK`, `IND`, `BOND`) — this is the only documented FX resolution path.

**Endpoint:** `GET /iserver/currency/pairs`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/contract/currency-pairs

### `get_contract_rules(conid, is_buy) -> dict`
Order rules for a contract (min tick, valid order types, size constraints).
**Endpoint:** `POST /iserver/contract/rules`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/contract/search-contract-rules

---

## Portfolio

### `get_accounts() -> list[dict]`
All accounts associated with the authenticated session. Returns `[]` if response is not a list.
**Returns:** `[{"accountId": "U1234567", ...}, ...]`
**Endpoint:** `GET /portfolio/accounts`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/portfolio/portfolio-accounts

### `get_subaccounts() -> list[dict]`
Sub-accounts (for IB Family accounts / advisors). Returns `[]` if response is not a list.
**Endpoint:** `GET /portfolio/subaccounts`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/portfolio/portfolio-subaccounts

### `get_account_meta(account_id) -> dict`
Account metadata (display name, status, type).
**Endpoint:** `GET /portfolio/{accountId}/meta`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/portfolio/specific-accounts-portfolio-information

### `get_account_summary(account_id) -> dict`
Net liquidation, cash, P&L. The response uses nested `{"amount": value}` objects.
**Endpoint:** `GET /portfolio/{accountId}/summary`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/portfolio/portfolio-summary

### `get_account_ledger(account_id) -> dict`
Cash balances by currency with detailed ledger fields.
**Endpoint:** `GET /portfolio/{accountId}/ledger`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/portfolio/portfolio-ledger

### `get_account_allocation(account_id) -> dict`
Portfolio breakdown by asset class, sector, industry.
**Endpoint:** `GET /portfolio/{accountId}/allocation`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/portfolio/portfolio-allocation-single

---

### `get_positions(account_id, page) -> list[dict]`
Open positions, paginated (page 0 = first 30). Returns `[]` if response is not a list.

**Returns:** `[{"conid": ..., "contractDesc": ..., "position": ..., "mktPrice": ...,
"mktValue": ..., "unrealizedPnl": ..., "realizedPnl": ...}, ...]`

**Endpoint:** `GET /portfolio/{accountId}/positions/{page}`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/portfolio/positions

---

### `get_positions_by_conid(conid) -> list[dict]`
Position data for a specific contract across all accounts. Returns `[]` if response is not a list.
**Endpoint:** `GET /portfolio/positions/{conid}`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/portfolio/position-contract-info

### `get_position(account_id, conid) -> dict`
Position for a specific account + contract pair.
**Endpoint:** `GET /portfolio/{accountId}/position/{conid}`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/portfolio/positions-by-conid

### `get_combo_positions(account_id) -> list[dict]`
Combo/spread positions. Returns `[]` if response is not a list.
**Endpoint:** `GET /portfolio/{accountId}/combo/positions`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/portfolio/combination-positions

### `get_portfolio_allocation(account_ids) -> dict`
Aggregated allocation across multiple accounts.
**Endpoint:** `POST /portfolio/allocation`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/portfolio/portfolio-allocation-all

### `invalidate_positions_cache(account_id) -> dict`
Force-refresh the IBKR position cache. Call before `get_positions()` if data looks stale.
**Endpoint:** `POST /portfolio/{accountId}/positions/invalidate`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/portfolio/invalidate-backend-portfolio-cache

---

## Orders (Read-Only)

### `get_live_orders() -> list[dict]`
Working orders — every order **except** those in `_TERMINAL_STATUSES`:
`{"Filled", "Cancelled", "ApiCancelled", "Expired"}`. In practice this surfaces orders in
`PreSubmitted`, `Submitted`, `ApiPending`, `PendingSubmit`, `PendingCancel`, or `Inactive`.

`Inactive` = order exists on IBKR but is stalled (e.g. failed risk check). These require
user action to resolve.

**Two-call warmup (officially documented):** the first call with `?force=true` instantiates
the order subscription; a second call (after a 1s pause) returns the actual live order list.
This method performs both calls internally.

**Endpoint:** `GET /iserver/account/orders`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/order-monitoring/live-orders
         https://www.interactivebrokers.com/campus/trading-lessons/request-modify-orders/

---

### `get_orders_raw() -> Any`
Raw, unfiltered `/iserver/account/orders` response, for diagnostics. Same two-call warmup as
`get_live_orders()`, but returns the response exactly as IBKR sent it — no status filtering, no
shape normalization. Used by `ClaudeToolkit`'s `diagnose_orders` to show what the server
actually returned when `get_live_orders()`'s filtered/normalized view isn't enough to debug a
missing or unexpected order.
**Endpoint:** `GET /iserver/account/orders`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/order-monitoring/live-orders

---

### `get_order_status(order_id) -> dict`
Full order details for a specific order ID.
**Endpoint:** `GET /iserver/account/order/status/{orderId}`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/order-monitoring/order-status

### `get_trades() -> list[dict]`
Trade executions for the current day plus up to 6 previous days (7-day window). **This is the
package's direct access point for TODAY's and recent fills** — the only REST source that can
contain same-day executions (Flex is T+1 and never contains today). Exposed to the LLM as
`get_trades(source='live')`.

**`?days=7` parameter (officially documented, re-verified 2026-07-02):** specifies the number
of days to receive executions for, up to a maximum of 7. Without it, IBKR returns only the
current day. This method always passes `days=7` for maximum lookback. The docs also advise
calling this endpoint once per session.

**Origin coverage (verified live 2026-07-06):** the official reference documents only "trades
for the currently selected account"; origin scope (API vs. mobile vs. TWS) is not stated.
Verified live: once the subscription is primed (see warmup below), mobile-placed fills DO
appear — origin coverage is complete.

**Two-call warmup (verified live 2026-07-06):** a fresh brokerage session returns an **empty**
list on the first call and the actual fills on a follow-up call — the same
subscription-instantiation behavior as `/iserver/account/orders`. This method retries once
after a 1s pause if the first response is empty; two empty responses mean genuinely no trades.

**When this is NOT the right tool:**
- Full history beyond 7 days → `FlexQueryClient.fetch_trades` (T+1, all origins) — see
  `docs/flex-query-reference.md`
- Real-time execution push → use the WebSocket `str` (trades) topic instead:
  `IBKRWebSocket.subscribe_executions(realtime_updates_only, days)` in `streaming.py`, which
  normalizes each push via `_parse_stream_execution` into this same trades table shape

**Endpoint:** `GET /iserver/account/trades`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/order-monitoring/trades

---

## Portfolio Analyst

### `get_pa_periods(account_ids) -> list[str]`
Available period strings for Portfolio Analyst queries. Verified live 2026-06-30: returns
`["1D", "7D", "MTD", "1M", "YTD", "1Y"]`.

**Response shape (live-verified) — the `"periods"` list is nested inside each account's
sub-dict, NOT at the top level:**

```python
{
  "pm": "TWR", "nd": 366, ...,
  "<accountId>": {
    "1D": {"nav": [...], "cps": [...], ...},
    ...
    "periods": ["1D", "7D", "MTD", "1M", "YTD", "1Y"],
    "baseCurrency": "USD", ...
  }
}
```

This method extracts `periods` from that nesting (falling back to top-level `periods` /
`Period` / `allPeriods` / `period` keys if present); returns `[]` if none of those shapes match.

**Endpoint:** `POST /pa/allperiods`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/portfolio-analyst/all-periods

### `get_pa_periods_raw(account_ids) -> Any`
Raw `/pa/allperiods` response, untouched — for diagnosing response shapes `get_pa_periods()`
doesn't recognize. `get_pa_periods()` returns `[]` when its documented-nesting extraction
finds nothing; this method exposes the raw payload so the caller can identify the actual
shape (used by `ClaudeToolkit`'s `get_pa_periods` fallback).
**Endpoint:** `POST /pa/allperiods`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/portfolio-analyst/all-periods

### `get_pa_performance(account_ids, period) -> dict`
NAV cumulative performance series for the given period.

**Valid periods (live-verified 2026-06-30 against `/pa/performance`):** `"1D"`, `"7D"`, `"MTD"`,
`"1M"`, `"YTD"`, `"1Y"` — all return HTTP 200. Strings like `"last7days"` / `"last30days"` /
`"ytd"` return **HTTP 400** — they are not valid for this endpoint even though they resemble
other IBKR APIs' period conventions. Use `get_pa_periods()` to retrieve the authoritative list
for the account rather than hardcoding these.
**Endpoint:** `POST /pa/performance`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/portfolio-analyst/account-performance

### `get_pa_transactions(account_ids, conids, currency, days) -> list[dict]`
Transaction history from Portfolio Analyst — dividends, buys, sells, transfers. Covers all
trade origins (CP API, mobile, TWS, web portal) — not session-scoped. Only **one conid per
call** is supported (IBKR limitation per official docs).

| Parameter | Type | Default |
|---|---|---|
| `account_ids` | list[str] | — |
| `conids` | list[int] | — |
| `currency` | str | `"USD"` |
| `days` | int \| None | `None` |

Bug fixed 2026-06-30: the previous signature took `period: str` and sent it as the request body
field `"period"` — both wrong. Required fields are `conids` (array of ints) and `currency`
(string); `days` is optional. Old calls returned HTTP 400 because `conids` and `currency` were
missing from the request body.

**Endpoint:** `POST /pa/transactions`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/portfolio-analyst/transaction-history

---

## Scanner

### `get_scanner_params() -> dict`
Available scanner types and filter parameters.
**Endpoint:** `GET /iserver/scanner/params`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/scanner/iserver-scanner-parameters

### `run_iserver_scanner(params) -> list[dict]`
Run a scanner with full parameter control. Returns `[]` if no contracts matched.
**Endpoint:** `POST /iserver/scanner/run`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/scanner/iserver-market-scanner

---

## FYI / Notifications

### `get_notifications(max_results) -> list[dict]`
Account notifications — order fills, margin calls, system messages. `max_results` is clamped
to `[1, 10]` — IBKR enforces a hard cap of 10 notifications per request.
**Endpoint:** `GET /fyi/notifications`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/fy-is-and-notifications/get-a-list-of-notifications

### `get_unread_count() -> int`
Number of unread FYI notifications.
**Endpoint:** `GET /fyi/unreadnumber`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/fy-is-and-notifications/unread-bulletins

### `get_delivery_options() -> dict`
Notification delivery channel configuration.
**Endpoint:** `GET /fyi/deliveryoptions`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/fy-is-and-notifications/get-delivery-options

### `get_mta_alert() -> dict`
Mobile Trading Alerts — account-level watchdog alerts.
**Endpoint:** `GET /iserver/account/mta`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/alerts/get-mta-alert

### `mark_notification_read(notification_id) -> dict`
Mark a FYI notification as read.
**Endpoint:** `POST /fyi/notifications/{notificationId}/read`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/fy-is-and-notifications/mark-notification-read

### `update_delivery_option(device_id, option, enabled) -> dict`
Enable/disable a notification delivery channel.
**Endpoint:** `POST /fyi/deliveryoptions/{option}`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/fy-is-and-notifications/enable-disable-device-option

---

## Alerts (IBKR Native)

### `get_alerts(account_id) -> list[dict]`
All price alerts configured on the account. The `orderId` field is the alert ID. Returns `[]`
if response is not a list.
**Endpoint:** `GET /iserver/account/{accountId}/alerts`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/alerts/get-a-list-of-available-alerts

### `get_alert(alert_id) -> dict`
Full details for a specific alert by ID. **Not** account-scoped in the URL — unlike
every other alert endpoint below, this one takes only the alert ID and a required
`type=Q` query parameter (same pattern as `get_order_status`); IBKR resolves the alert from the
session's logged-in account.
**Endpoint:** `GET /iserver/account/alert/{order_id}?type=Q`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/alerts/get-details-of-a-specific-alert

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
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/alerts/create-or-modify-alert

---

### `delete_alert(account_id, alert_id) -> dict`
Delete an alert permanently. If `alert_id` is `0`, deletes all alerts.
**Endpoint:** `DELETE /iserver/account/{accountId}/alert/{alertId}`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/alerts/delete-an-alert

### `activate_alert(account_id, alert_id, activate) -> dict`
Toggle alert on/off without deleting it. `activate=True` enables; `activate=False` disables.
**Endpoint:** `POST /iserver/account/{accountId}/alert/activate`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/alerts/activate-or-deactivate-an-alert

---

## Watchlists

### `get_watchlists() -> list[dict]`
All watchlists for the account. Returns `[]` if response is not a list.
**Endpoint:** `GET /iserver/watchlists` — query param `SC=USER_WATCHLIST`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/watchlists/get-all-watchlists

### `get_watchlist(watchlist_id) -> dict`
Contents of a specific watchlist. `watchlist_id` is passed as query param `id`.
**Endpoint:** `GET /iserver/watchlist`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/watchlists/get-watchlist-information

### `create_watchlist(name, rows) -> dict`
Create a new watchlist. `rows` is a list of `{"C": conid}` objects.
**Endpoint:** `POST /iserver/watchlist`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/watchlists/create-a-watchlist

### `delete_watchlist(watchlist_id) -> dict`
Delete a watchlist. `watchlist_id` passed as query param `id`.
**Endpoint:** `DELETE /iserver/watchlist`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/watchlists/delete-a-watchlist

---

## Events Contracts

**Status: unverified, currently non-functional.** Both methods below call bare `/events/...`
paths that **do not appear anywhere** in the official Client Portal Web API reference (verified
2026-06-30, full page scan; re-confirmed via the current documentation scrape). They raise
`IBKRAPIError` (404) on every call.

IBKR *does* document an Event Contracts product (ForecastEx and CME Group event/forecast
contracts, modeled on options) — but under a **different, undocumented-by-this-client**
namespace: `GET /forecast/category/tree`, `GET /forecast/contract/market`,
`GET /forecast/contract/rules`, `GET /forecast/contract/schedules`, and
`GET /forecast/contract/details`. Neither `get_event_contracts()` nor `get_event_contract()`
calls any of these — reimplementing this pair against the `/forecast/*` endpoints is a known
gap, not yet scheduled.
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/event-contracts/introduction

### `get_event_contracts(conids) -> list[dict]`
**Endpoint:** `GET /events/contracts` (does not exist — see Status above)

### `get_event_contract(conid) -> dict`
**Endpoint:** `GET /events/show` (does not exist — see Status above)

---

## Order Management (Write — Human Auth Required)

Every method in this section enforces two sequential security gates before any API call is made:
1. **Gate 1:** macOS Touch ID / Face ID (`LAPolicyDeviceOwnerAuthentication`, falls back to the
   device's system password on a failed/cancelled biometric scan, 60s timeout).
2. **Gate 2:** tkinter modal dialog with full order details (Enter key does not confirm).

If either gate fails or times out, `HumanAuthError` is raised and no HTTP call is made. See
CLAUDE.md's Security & Fingerprint Authentication section for the full policy rationale — the
gate uses `LAPolicyDeviceOwnerAuthentication`, **not** the biometrics-only
`LAPolicyDeviceOwnerAuthenticationWithBiometrics` (that stricter policy was evaluated and
rejected: a failed scan under it has no recovery path).

> **ClaudIA constraint:** `ClaudeToolkit` deliberately exposes no tools that call any method in
> this section. Order execution is a UI-layer action triggered by a physical button click, not
> an LLM tool call.

**GTC orders are not indefinite (verified live 2026-07-06, IBKR convention):** a GTC order
auto-cancels at the end of the calendar quarter *following* the current one, not simply
"year-end." Placed in Q3 → cancels end of Q4; placed in Q1 → cancels end of Q2. Confirmed live:
an order placed 2026-07-06 (Q3) returned a final reply message "will be automatically canceled
at 20261231 16:00:00 EST" (end of Q4), matching the rule exactly — the reply chain (below)
surfaces the exact cancellation timestamp for each GTC order placed.
Source: https://www.interactivebrokers.com/campus/trading-lessons/mosaic-good-till-cancelled-gtc-order-type/

**Order confirmation may require multiple chained replies (verified live 2026-07-06):**
`place_order()`'s response can include an `{"id", "message", "messageIds", ...}` entry requiring
`reply_order(id)`. Critically, `reply_order()`'s own response can *also* return another such
entry — confirmed live: a single AAPL limit order required **three** sequential replies
(price-band %, no-market-data, mandatory-cap-price) before returning a terminal
`{"order_status": "Submitted", ...}`. Callers must loop `reply_order()` until a response with no
`"id"`/`"message"` is returned — use `place_order_and_confirm()` / `modify_order_and_confirm()`
below rather than doing this manually. Official docs warn the reply must be answered
immediately — other requests interleaved in between risk invalidating it (HTTP 503 on the next
reply attempt).

**US Futures and Futures Options (FUT/FOP):** the order dict must include both
`manualIndicator=True` and `extOperator="<user>"`. Required since May 1, 2025 for CME Group
Rule 536-B compliance — IBKR returns HTTP 400 without them for FUT/FOP orders. `order_flow.py`
adds these automatically when `sec_type` is `"FUT"` or `"FOP"`.
Source: https://www.interactivebrokers.com/docs/web-api/changelog

### `place_order(account_id, order) -> list[dict]`
Place a new order after both security gates pass. Strips display-only underscore-prefixed
fields (e.g. `_companyName`) from the order dict before sending — those carry Gate 2 dialog
metadata, not valid IBKR request fields (`ticker` *is* a valid, optional IBKR field and is not
stripped).
**Endpoint:** `POST /iserver/account/{accountId}/orders`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/orders/place-order
         https://www.interactivebrokers.com/campus/trading-lessons/request-modify-orders/

### `modify_order(account_id, order_id, order) -> dict`
Modify an existing order after both security gates pass.
**Endpoint:** `POST /iserver/account/{accountId}/order/{orderId}`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/orders/modify-order
         https://www.interactivebrokers.com/campus/trading-lessons/request-modify-orders/

### `cancel_order(account_id, order_id, order_details) -> dict`
Cancel an order after both security gates pass. `order_details` is optional display-only info
(symbol/side/qty/price/TIF/etc.) shown in the Gate 2 dialog so the human can verify the correct
order before cancelling — mirrors `modify_order()`'s dialog, which already receives the full
order dict.
**Endpoint:** `DELETE /iserver/account/{accountId}/order/{orderId}`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/orders/cancel-order
         https://www.interactivebrokers.com/campus/trading-lessons/request-modify-orders/

### `reply_order(reply_id, ibkr_confirmed) -> list[dict]`
Confirm an order that requires an explicit IBKR reply (e.g. after a warning). Both gates
required. See "Order confirmation may require multiple chained replies" above — a single call
may not resolve the whole chain; prefer `place_order_and_confirm()` / `modify_order_and_confirm()`.
**Endpoint:** `POST /iserver/reply/{replyId}`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/orders/place-order-reply-confirmation

---

### `place_order_and_confirm(account_id, order) -> list[dict]` — recommended entry point
Places an order and resolves its **full reply chain**, looping Gate 1 + Gate 2 + the confirm
POST for each reply until a terminal response, showing the human the actual IBKR warning text
at every step (not just a bare `reply_id`). Calls `place_order()` for the initial submission —
Gate 1 + Gate 2 already run correctly there.

Runs the loop back-to-back with no unrelated requests interleaved, per IBKR's reply-immediacy
warning (see above). If the human declines any reply in the chain, `HumanAuthError` is raised
— but the decline is POSTed to IBKR (`{"confirmed": False}`) first, unlike the standalone
`reply_order()`, which raises without ever contacting IBKR and leaves the order ambiguous on
IBKR's side. This is a deliberate behavior difference, not a bug.

**Endpoint:** `POST /iserver/account/{accountId}/orders`, then `POST /iserver/reply/{replyId}` per chained reply
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/orders/place-order
         https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/orders/place-order-reply-confirmation

### `modify_order_and_confirm(account_id, order_id, order) -> dict` — recommended entry point
Same loop/display/decline semantics as `place_order_and_confirm()`, applied to `modify_order()`
instead. Note: `modify_order()`'s own return type is a single dict (not a list), so this method
checks for `"id"`/`"message"` directly on that dict rather than on a list's first element.

This method was added proactively to close the same never-loops-replies gap that `place_order()`
had before `place_order_and_confirm()` was added, but the gap has **not been live-verified for
`modify_order` specifically** as of 2026-07-06 — only the `place_order` 3-reply chain has been
confirmed live.

**Endpoint:** `POST /iserver/account/{accountId}/order/{orderId}`, then `POST /iserver/reply/{replyId}` per chained reply
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/orders/modify-order
         https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/orders/place-order-reply-confirmation

---

### `get_order_preview(account_id, order) -> dict`
Whatif preview — cost, commission, margin impact. No order placed, no security gates. Same
underscore-field-stripping as `place_order()`.
**Endpoint:** `POST /iserver/account/{accountId}/orders/whatif`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/orders/preview-order-what-if-order

---

## Account / Admin

### `get_pnl() -> dict`
Real-time partitioned P&L — daily, unrealized, realized — across all positions.
**Endpoint:** `GET /iserver/account/pnl/partitioned`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/accounts/account-profit-and-loss

### `get_brokerage_accounts() -> dict`
List of accounts the user has trading access to, their aliases, the currently selected
account, and per-account capability flags (`supportsCashQty`, `supportsFractions`,
`allowCustomerTime`, etc). **Officially documented as required before modifying an order
or querying open orders.** `IBKRClient._ensure_accounts_initialized()` calls this once per
client instance (cached) and runs automatically at the top of every order read/write
method (`get_live_orders`, `get_orders_raw`, `get_order_status`, `place_order`, `modify_order`,
`cancel_order`, `reply_order`, `get_order_preview`) — callers do not need to call this
directly under normal use.

**Returns:** `dict` with keys: `accounts` (list of account ID strings), `acctProps`, `aliases`, `allowFeatures`, `chartPeriods`, `groups`, `profiles`, `selectedAccount`. Verified live 2026-06-30 — NOT a bare list.

**Endpoint:** `GET /iserver/accounts`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/accounts/receive-brokerage-accounts

### `switch_account(account_id) -> dict`
Switch the active account (for advisors / family accounts).
**Endpoint:** `POST /iserver/account`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/accounts/switch-account

### `logout() -> dict`
End the current session.
**Endpoint:** `POST /logout`
Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/session/logout-of-the-current-session

---

## Error Handling

| Exception | When raised |
|-----------|-------------|
| `IBKRAuthError` | HTTP 401 — session expired or not authenticated |
| `IBKRRateLimitError` | HTTP 429 after 3 retries with exponential backoff |
| `IBKRAPIError` | Other HTTP 4xx/5xx errors (has `.status_code` attribute) |
| `ConfigError` | Invalid `gateway_url` (not localhost), or invalid `account_id`/`order_id`/`alert_id`/`reply_id` format caught by input validation before any request is sent |
| `HumanAuthError` | Touch ID denied, timed out, or unavailable; or the user declined/cancelled the Gate 2 confirmation dialog |

`ConfigError` here is a client-side guard, not an IBKR response — `_validate_account_id`,
`_validate_order_id`, and `_validate_reply_id` reject malformed IDs before they're interpolated
into a URL, preventing path traversal via f-string-built request paths.

All methods except `ping()` and `tickle()` use `with_retry()` internally (3 retries, 1s base
backoff, handles 429 and 503). 401 responses are not retried — they raise `IBKRAuthError`
immediately. `ping()` and `tickle()` bypass `with_retry()` entirely — they call the session
directly with a 5s timeout, catch any exception, and return a `bool`; see their own docstrings.
