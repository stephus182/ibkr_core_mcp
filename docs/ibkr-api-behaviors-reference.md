# Known IBKR API Behaviors (Documented, Not Assumed)

These are verified against official sources — not guesses:

- **`/iserver/account/orders`** — two-call pattern: first call instantiates the subscription, second call retrieves data. Source: [IBKR Campus — Orders](https://www.interactivebrokers.com/campus/trading-lessons/request-modify-orders/)
- **`/iserver/marketdata/history`** — primary fetch endpoint, max 1000 data points per request. First-call warmup (404/500) auto-retried 3× with 2s delay in `claude_tools.py`. Pagination for large requests handled by `get_market_history_paginated()`. **`startTime` is the END of the returned window, not the start** — the spec calls it "a fixed UTC date-time reference point ... from which the specified period extends", and measurement settles the direction (conid 756733, anchor `20231109-00:00:00`, `period=100d`, 2026-08-05): `direction` omitted → 2023-06-20 → 2023-11-07; `direction=-1` → **identical**; `direction=1` → `{"error": "Chart data unavailable"}`, despite the spec documenting it as supported whenever `startTime` is included. So the default is backwards and the documented forward direction does not work. **The newest chunk must send no `startTime` at all** ("if omitted, the current time is used"): on SPY `30d`/`1d`, omitted reached 2026-08-05, an explicit timestamp of that same moment reached 08-04, midnight-today reached 08-03. Reading `startTime` as the start cost a **silent 1,010-day-stale result** — SPY `5y`/`1w` returned 291 well-formed bars ending 2023-10-30 with no error — for every request wider than one chunk (`3y`/`5y` on most bars, `1y`/`2y` on `1h`). Fixed 2026-08-05. **A code fix is not sufficient: `_fetch_market_data` returns "Cache HIT" and serves the stored parquet without re-fetching**, so poisoned windows persist until purged with `GDriveCache.delete()`. Source (the reference that resolves — the old campus URL 404s): https://api.ibkr.com/gw/api/v3/api-docs
- **`trades.time` has two formats, written by two paths** — `flex_query` writes ISO (`2026-08-04T14:21:42`); the live CP API path and the WebSocket `str` path write IBKR's compact `20260804-14:21:42`. `upsert_trades`' `ON CONFLICT` deliberately does not update `time` (first observation of a fill is authoritative), so a live-captured row keeps the compact form permanently. Until 2026-08-05 `get_trade_date_coverage` matched the ISO shape only and could not see them: **38 of 1,206 rows (3%) on the live account**, with the newest reportable date 2026-08-04 while the table already held 2026-08-05. The sharp consequence was not the missing day but that a window holding *only* live-captured trades would read as a 45+ day gap — reported to the user as inactivity. Now: `time` is normalised to ISO on write, the **activity report** reads every row via `_TRADE_DATE_SQL` (both formats), and the **staleness flag** deliberately still reads settled `flex_trade` rows (`source='flex'`) only — Flex is T+1, so today's live fill is exactly the trade whose settled record has not arrived, and counting it would suppress the pull that brings it.
- **`/iserver/account/trades`** — **the direct access point for today's + recent fills**: `get_trades(source='live')` → `client.get_trades()` → `GET /iserver/account/trades?days=7`. It is the only REST source that can contain same-day executions (Flex is T+1). Official reference documents: "a list of trades for the currently selected account for current day and six previous days" (`?days=7` max), "advised to call this endpoint once per session." Origin coverage is not documented officially but **verified live 2026-07-06: all origins appear (mobile included) once the subscription is primed** — the endpoint has the same two-call warmup as `/iserver/account/orders` (fresh session's first call returns empty; `client.get_trades()` auto-retries once, 1 s apart). The 2026-07-02 empty observation was this warmup, not an origin filter. For real-time execution push, the WebSocket **`str` (trades) topic** is implemented in `streaming.py` (`IBKRWebSocket.subscribe_executions()`/`unsubscribe_executions()`, args: `realtimeUpdatesOnly`, `days`) and persists executions into the same `trades` table used by REST/Flex via `_parse_stream_execution()` — so `get_trades(source='store')` and `ibkr://trades/recent` pick them up automatically once a `--stream` server has captured them. Beyond 7 days or for origin-complete history: the Flex store. Source: CP API reference "Trades" + WebSocket sections, scraped 2026-07-02, `str`/`spl` topics re-confirmed 2026-07-06.
- **Flex Web Service** — T+1 delay, back-office data. Captures all trades from all interfaces (mobile, TWS, API). Requires separate token + query ID, not CP API credentials.
- **Flex endpoint** — the initial `SendRequest` call goes to `ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/SendRequest`, matching official docs. The follow-up `GetStatement` URL that IBKR returns in the `SendRequest` response, however, is observed live pointing at **`gdcdyn`**, not `ndcdyn` — both are legitimate IBKR Flex subdomains and both are allowlisted by the SSRF guard in `flex_query.py` (`_ALLOWED_URL_PREFIXES`). Treating `gdcdyn` as categorically wrong was itself a past incident (see CLAUDE.md's Flex endpoint URL row) — the earlier bug was assuming the *wrong path* (`gdcdyn.../Universal/servlet/...`) for the *first* call, not that `gdcdyn` never legitimately appears. Requires a `User-Agent` header for programmatic access. Observed live 2026-06-26.
- **`/md/regsnapshot` (Regulatory Snapshot) — permanently removed by IBKR.** Announced via the official [Web API Changelog](https://www.interactivebrokers.com/docs/web-api/changelog), dated **2026-02-11**, tagged `warning`: *"The /md/regsnapshot endpoint is no longer supported for users to query a regulatory snapshot via API."* Enforcement was not immediate — the endpoint still returned real live NBBO data (with the documented $0.01 charge) as recently as the 2026-07-08 integration baseline, and only started returning `HTTP 404: Resource not found` sometime between 2026-07-08 and 2026-07-22 (no separate changelog entry marks the exact cutover date). `get_regulatory_snapshot()` was removed from `client.py` accordingly (dead API surface, not an entitlement gap on the calling account) — see `docs/audits/live-test-log.md` run `2026-07-22-1` for the full investigation.

## Response shape: several endpoints wrap the array in an object

Reading these as a bare list reports **"no data" for data that arrived** — silently, with no
error and no log. All verified 2026-09-16 against an authenticated gateway *and* against the
doc page that declares the endpoint.

**How the pages were identified.** Not by name. Every page under `v1/endpoints/` in
`llms.txt` (123) was fetched, each page's own endpoint declaration extracted, and the method
matched to the page declaring its endpoint. Matching by *name* is unsound and was caught doing
harm here: `positions-by-conid.md` and `position-contract-info.md` are both plausible names for
`get_positions_by_conid`, and the first documents `GET /portfolio/{acctId}/position/{conid}` —
a different endpoint. A fabricated control URL in the same batch returned `# Page Not Found`,
so the check could fail. Matched properly, **all 14 `Source:` URLs already in `client.py` are
correct**.

| Endpoint | Documented | Live | Effect before the fix |
|---|---|---|---|
| `GET /iserver/contract/{conid}/algos` | object, `algos: Array of objects` | `{"algos": [...]}` | 10 algos for GLD reported as none |
| `POST /pa/transactions` | object; **never a bare array** | `{"transactions": [...], "rpnl", "currency", "from", "to", "id", "nd"}` | `[]` for every account since the method was written, while IBKR returned 11 transactions |
| `GET /portfolio/positions/{conid}` | **array** (`position-contract-info.md`) | **account-keyed object**, `{"U1234567": [...], "U1234567C": [...]}` | open positions reported as none |

**The `/portfolio/positions/{conid}` divergence is real** — documented as an array, observed as
an object keyed by account id, one bucket per account holding the contract. The keys are
account ids, so no fixed key name finds them. Both shapes are accepted. *(This entry first
claimed the divergence on 2026-09-16 having checked `positions-by-conid.md` — the wrong page.
Re-checked against the page that declares the endpoint: the claim holds, the evidence did not.)*

**`POST /iserver/account/{accountId}/orders` publishes a third shape, and it is an object.**
Beside the normal array and the Alternate reply-required array, `place-order.md` documents a
bare `{"error": "We cannot accept an order at the limit price you selected…"}`. Read as a list
it became `[]`, so an order IBKR **refused for a stated reason** reached the caller as an empty
response — indistinguishable from "nothing happened", with IBKR's own words discarded, on the
one path where that matters most. `place_order` now returns it via `_as_reply_list`, the
one-element-list wrapper that already existed and was only ever applied a layer further out.
`reply_order` publishes only the array shape; `cancel_order` publishes two objects and already
returns them intact.

**Prior instances of the same class:** `get_currency_pairs` (2026-06-30, `{"currencyPairs": …}`),
`get_secdef` (2026-07-28, `{"secdef": …}`), `get_watchlists` (found live 2026-07-23, fixed
2026-08-11, `{"data": {"user_lists": …}}`). Three point-fixes and no sweep is what allowed the
next three. `tests/test_client.py::test_no_new_endpoint_silently_discards_an_object_response`
now requires any method using the bare-list fallback to name its endpoint and the evidence that
it really returns an array.

**Open:** `GET /events/contracts` returned HTTP 404 live and no page under `v1/endpoints/`
declares it. Absence from the index proves nothing on its own, so this is unverified rather
than dead; settling it needs `firecrawl_search`.
