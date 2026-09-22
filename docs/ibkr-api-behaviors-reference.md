# Known IBKR API Behaviors (Documented, Not Assumed)

These are verified against official sources — not guesses:

- **`/iserver/account/orders`** — subscription warmup, but **once per session, not once per call**. A fresh brokerage session's first read returns an empty array; `force=true` clears cached state to instantiate the subscription ("Force the system to clear saved information and make a fresh request for orders. Submission will appear as a blank array"). Until 2026-09-16 `get_live_orders` and `get_orders_raw` sent that pair before **every** read, spending two slots of a 1-req/5-secs endpoint to answer one question. **Measured live 2026-09-16 on a warm session: three consecutive plain reads, with no `force=true` ahead of them, each returned the open order** (conid 265598). Both methods now read first and prime only when the read comes back empty — the same shape `get_trades` already used for the identical warmup on `/iserver/account/trades`. Effect with pacing enforced: `get_live_orders()` went from 5.17 s to 0.35 s, and from 10.07 s to ~5.0 s when called twice back to back (the remaining 5 s is the published limit itself). Sources: [live-orders](https://www.interactivebrokers.com/docs/web-api/v1/endpoints/order-monitoring/live-orders), [IBKR Campus — Orders](https://www.interactivebrokers.com/campus/trading-lessons/request-modify-orders/)
- **`/iserver/marketdata/history`** — primary fetch endpoint, max 1000 data points per request. First-call warmup (404/500) auto-retried 3× with 2s delay in `claude_tools.py`. Pagination for large requests handled by `get_market_history_paginated()`. **`startTime` is the END of the returned window, not the start** — the spec calls it "a fixed UTC date-time reference point ... from which the specified period extends", and measurement settles the direction (conid 756733, anchor `20231109-00:00:00`, `period=100d`, 2026-08-05): `direction` omitted → 2023-06-20 → 2023-11-07; `direction=-1` → **identical**; `direction=1` → `{"error": "Chart data unavailable"}` on that conid, despite the spec documenting it as supported whenever `startTime` is included. So the default is backwards. **The claim that the forward direction "does not work" was generalised from one instrument and is wrong** — re-measured 2026-09-16 with `startTime=20260601-00:00:00`, `period=10d`, `bar=1d`: AAPL (265598), MSFT (272093), NVDA (4815747) and IWM (9579970) all returned proper forward windows (2026-06-03 → 2026-06-15), while **SPY (756733) and QQQ (320227571) returned HTTP 500 `Chart data unavailable`** in all four anchor/period combinations tried. It is neither security type nor exchange: IWM is an ARCA ETF that works and SPY is an ARCA ETF that does not. The original conid-756733 result reproduced exactly, so IBKR did not change anything — the rule was over-stated. **`direction=-1`, which `get_market_history_paginated` sends, worked on all six**, and end-to-end pagination returned identical results for all six (5d/5min: 299 bars, 5.2d span, 0 duplicates), so no code path is affected. **The newest chunk must send no `startTime` at all** ("if omitted, the current time is used"): on SPY `30d`/`1d`, omitted reached 2026-08-05, an explicit timestamp of that same moment reached 08-04, midnight-today reached 08-03. Reading `startTime` as the start cost a **silent 1,010-day-stale result** — SPY `5y`/`1w` returned 291 well-formed bars ending 2023-10-30 with no error — for every request wider than one chunk (`3y`/`5y` on most bars, `1y`/`2y` on `1h`). Fixed 2026-08-05. **A code fix is not sufficient: `_fetch_market_data` returns "Cache HIT" and serves the stored parquet without re-fetching**, so poisoned windows persist until purged with `GDriveCache.delete()`. Source (the reference that resolves — the old campus URL 404s): https://api.ibkr.com/gw/api/v3/api-docs
- **An empty WINDOW is not the end of the data, and reading it as one silently lost 5 days down to 11 hours.** IBKR answers a window it has nothing for with `points: 0` and a single **placeholder bar carrying no `t`** — `{"o": 0.0, "c": 0.0}` — so `data` is non-empty and a `if not bars` guard does not fire. `get_market_history_paginated` broke on the resulting empty timestamp list and returned what it had, with **no** truncation warning (the warning fires only on chunk-guard exhaustion). `points: 0` is IBKR's own documented shape, not an anomaly: `points` is defined as "the total number of data points in the bar", and the published example response on the endpoint page itself carries `"points": 0` alongside `outsideRth: true` and `timePeriod: "1d"`. **The failure is ONE cell of four, and mixing the cases hides it.** Measured live 2026-09-22, `5d`/`1min`, comparing pagination against a single capped call: AAPL `outside_rth=False` → 1501 bars, 0 lost; **AAPL `outside_rth=True` → 653 bars covering 10.9 h of a requested 5 days, 343 lost**; CL (future) `outside_rth=False` → 1681, 0 lost; CL `outside_rth=True` → 5018, 0 lost. The mechanism is the session boundary, which is why security type alone does not predict it: the first chunk sends no `startTime` and returns today's partial session, so the cursor anchors on its oldest bar — 08:04 UTC, the 04:00 ET **pre-market open** — and an equity "1 trading day" window *ending* at pre-market open contains nothing. A future trades nearly round the clock, so its cursor lands mid-session and every window is full. The data was never missing: the SAME anchor with `period=2d` returned 960 bars of the previous session, and an anchor of `20260921-23:59:00` returned 958. **Fixed by widening the window and retrying** (bounded, `_MAX_WIDENINGS = 4`), which was chosen by measurement over the obvious alternative: stepping the cursor back a chunk instead still lost all 343 bars on the broken cell **and lost one on futures**, while widening took the broken cell to 3,537 bars / 131 h and left the three already-correct cells byte-identical — same bars, same request count. Re-verified live after the fix: all four cells 0 lost. Caught by `test_paginated_history_recovers_what_the_point_cap_drops`, which had never run this combination. Source: https://www.interactivebrokers.com/docs/web-api/v1/endpoints/market-data/historical-market-data.md (4,975 B; a fabricated control URL in the same batch returned 429 B)
- **A wide intraday request can exhaust the pagination guard and come back short.** IBKR's step table caps `1min` and `5min` requests at a 1-day period, so `get_market_history_paginated` needs roughly one chunk per *trading* day and `_MAX_CHUNKS = 120` is reached at about 120 trading days (~5.5 calendar months) for RTH equity data — sooner for a continuously-traded instrument, where a chunk covers one calendar day. Until 2026-09-16 the result was a well-formed short answer with only a `log.warning`, which reaches no caller, no model and no cache. **Verified live 2026-09-16** (conid 265598, AAPL, `outside_rth=False`): `1y`/`5min` hit the guard at exactly 120 chunks and returned **9,344 bars covering 174 of 365 days — 47.7%**, back to 2026-03-26. The same run measured 29.3 requests/min against the published 50/min ceiling, i.e. network-bound rather than pacer-bound, so proactive pacing costs nothing here. A control in the same session, `90d`/`1min`, finished in 62 chunks at 100.2% coverage and correctly carried no warning. The response now carries `ibkr_core_warning` naming the period asked for, the guard, and the date actually reached, and `fetch_market_data` **refuses to cache** a flagged result — a partial window stored under the requested period would answer every later request for that period, on every machine, exactly as the 2026-08-05 `startTime` poisoning did.
- **`trades.time` has two formats, written by two paths** — `flex_query` writes ISO (`2026-08-04T14:21:42`); the live CP API path and the WebSocket `str` path write IBKR's compact `20260804-14:21:42`. `upsert_trades`' `ON CONFLICT` deliberately does not update `time` (first observation of a fill is authoritative), so a live-captured row keeps the compact form permanently. Until 2026-08-05 `get_trade_date_coverage` matched the ISO shape only and could not see them: **38 of 1,206 rows (3%) on the live account**, with the newest reportable date 2026-08-04 while the table already held 2026-08-05. The sharp consequence was not the missing day but that a window holding *only* live-captured trades would read as a 45+ day gap — reported to the user as inactivity. Now: `time` is normalised to ISO on write, the **activity report** reads every row via `_TRADE_DATE_SQL` (both formats), and the **staleness flag** deliberately still reads settled `flex_trade` rows (`source='flex'`) only — Flex is T+1, so today's live fill is exactly the trade whose settled record has not arrived, and counting it would suppress the pull that brings it.
- **`/iserver/account/trades`** — **the direct access point for today's + recent fills**: `get_trades(source='live')` → `client.get_trades()` → `GET /iserver/account/trades?days=7`. It is the only REST source that can contain same-day executions (Flex is T+1). Official reference documents: "a list of trades for the currently selected account for current day and six previous days" (`?days=7` max), "advised to call this endpoint once per session." Origin coverage is not documented officially but **verified live 2026-07-06: all origins appear (mobile included) once the subscription is primed** — the endpoint has the same two-call warmup as `/iserver/account/orders` (fresh session's first call returns empty; `client.get_trades()` auto-retries once, 1 s apart). The 2026-07-02 empty observation was this warmup, not an origin filter. For real-time execution push, the WebSocket **`str` (trades) topic** is implemented in `streaming.py` (`IBKRWebSocket.subscribe_executions()`/`unsubscribe_executions()`, args: `realtimeUpdatesOnly`, `days`) and persists executions into the same `trades` table used by REST/Flex via `_parse_stream_execution()` — so `get_trades(source='store')` and `ibkr://trades/recent` pick them up automatically once a `--stream` server has captured them. Beyond 7 days or for origin-complete history: the Flex store. Source: CP API reference "Trades" + WebSocket sections, scraped 2026-07-02, `str`/`spl` topics re-confirmed 2026-07-06.
- **Flex Web Service** — T+1 delay, back-office data. Captures all trades from all interfaces (mobile, TWS, API). Requires separate token + query ID, not CP API credentials.
- **Flex endpoint** — the initial `SendRequest` call goes to `ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/SendRequest`, matching official docs. The follow-up `GetStatement` URL that IBKR returns in the `SendRequest` response, however, is observed live pointing at **`gdcdyn`**, not `ndcdyn` — both are legitimate IBKR Flex subdomains and both are allowlisted by the SSRF guard in `flex_query.py` (`_ALLOWED_URL_PREFIXES`). Treating `gdcdyn` as categorically wrong was itself a past incident (see CLAUDE.md's Flex endpoint URL row) — the earlier bug was assuming the *wrong path* (`gdcdyn.../Universal/servlet/...`) for the *first* call, not that `gdcdyn` never legitimately appears. Requires a `User-Agent` header for programmatic access. Observed live 2026-06-26.
- **`/md/regsnapshot` (Regulatory Snapshot) — permanently removed by IBKR.** Announced via the official [Web API Changelog](https://www.interactivebrokers.com/docs/web-api/changelog), dated **2026-02-11**, tagged `warning`: *"The /md/regsnapshot endpoint is no longer supported for users to query a regulatory snapshot via API."* Enforcement was not immediate — the endpoint still returned real live NBBO data (with the documented $0.01 charge) as recently as the 2026-07-08 integration baseline, and only started returning `HTTP 404: Resource not found` sometime between 2026-07-08 and 2026-07-22 (no separate changelog entry marks the exact cutover date). `get_regulatory_snapshot()` was removed from `client.py` accordingly (dead API surface, not an entitlement gap on the calling account) — see `docs/audits/live-test-log.md` run `2026-07-22-1` for the full investigation.
- **`/trsrv/secdef/schedule` — IBKR publishes three disagreeing "trading schedule" pages, and `exchange=SMART` returns an empty list.** Measured live 2026-09-16 on an authenticated gateway. **(1) The parameters.** The gateway enforces `{"error":"Bad Request: assetClass and exactly one of symbol/conid are required"}` — both together is a 400, neither is a 400. The **API Reference** ([get-trading-schedule](https://www.interactivebrokers.com/docs/web-api/api-reference/trading/trading-contracts/get-trading-schedule)) documents `assetClass` + `symbol` required and **no `conid` parameter at all**, which matches the gateway; the older narrative page (`v1/endpoints/contract/trading-schedule-by-symbol`) lists **both** `conid` *and* `symbol` as *Required* — a combination that cannot succeed. A fix written from that page shipped a guaranteed 400 and was caught only by running it. `conid` does work as an undocumented **alternative** to `symbol` (265598 and `AAPL` returned the same 125 rows). **(2) A third page is a different endpoint**: `v1/endpoints/contract/trading-schedule-new` documents `GET /contract/trading-schedule`, keyed by `conid`, returning `exchange_time_zone` and a date-keyed `schedules` object — not implemented here. **(3) `exchange` decides whether you get anything, and omitting it returns the most.** Measured on AAPL: no exchange **141 rows**, `ISLAND` 125, `SMART` **0**. SMART is IBKR's smart-routing destination and the correct default nearly everywhere — `get_option_chain`, secdef strikes and the alert condition all pass it and all work, verified live the same day. This endpoint is the exception: its `exchange` means *a venue with published trading hours*, not a route, and SMART has none, so it returns an empty list rather than an error. The fixture's `trading_schedule` was that empty list until the 2026-09-17 re-capture, which dropped the `exchange` argument and recorded the 141 rows the endpoint really returns (this sentence described the empty fixture for a day after it stopped existing) — and the `get_trading_schedule` **tool** defaulted its `exchange` to SMART until 2026-09-16, so its minimal call (`symbol` is the only required input) answered `[]` for every equity (TOOL-R1). **(4) The response object.** The wire returns `id`, `tradeVenueId`, `exchange`, `description`, `timezone`, `schedules[]` — six keys, matching the API Reference exactly. The narrative page omits `exchange` and `description`. Neither page nor wire has `regularTradingHours` or `liquidHours`, which `docs/tools-reference.md` promised until 2026-09-16.
- **`PUT /fyi/notifications/{id}` marks ONE notification read, and `R: 1` is now observed.** Measured 2026-09-16 with the account holder's explicit permission — this is a write with no unmark in this package, so it had never been exercised. Three notifications all carried `R: 0`; marking one returned IBKR's documented acknowledgement `{"V": 1, "T": <ms>}`, and a re-read showed **that one at `R: 1` and the other two still at `R: 0`**. Both halves matter: `1` is the read flag (confirming IBKR's "0: Disabled; 1: Enabled"), and the write is **targeted, not global**. Until then `R: 1` had never been seen and the read branch in `claude_tools._get_notifications` rested on documentation alone (audit finding API-20). The verb and path were corrected from `POST /fyi/notifications` to `PUT /fyi/notifications/{id}` on the same audit; this run is the first confirmation that the corrected call works.

## Alerts: the detail response and the write body are different vocabularies

Measured against a live gateway (build 2023-04-24) on 2026-09-16, using a real alert created
on IBKR Mobile (`AAPL <= 1.00`, GTC; its order_id is deliberately not reproduced —
this repository is public and an order id is account data):

- `GET /iserver/account/alert/{order_id}` returns **26 top-level keys, none camelCase** —
  `order_id`, `alert_name`, `alert_message`, `condition_outside_rth`, and
  `conditions[].condition_operator` / `condition_value` / `condition_logic_bind` /
  `condition_trigger_method`. The live shape matches IBKR's documented example key for key.
- `POST /iserver/account/{accountId}/alert` documents **19 fields, none snake_case** —
  `orderId`, `alertName`, `alertMessage`, `outsideRth`, and `conditions[].operator` /
  `value` / `logicBind` / `triggerMethod`.
- **Exactly two top-level names appear in both: `conditions` and `tif`.**

`orderId` decides what the call means — "omitted or 0 creates, an existing alert id modifies
that alert" — and the detail response supplies `order_id`. Posting the detail response back
therefore reads as a *create*. `claude_tools._alert_detail_to_request` translates between the
two shapes; before it existed, `modify_price_alert` set three camelCase keys on the raw
detail response and sent the rest through untouched (audit finding TOOL-01).

### The 403 is the operator, not the body shape

This had been confounded. Alert writes were known to 403, and the explanation on record was
the `>=`/`<=` operator block — but "our body was malformed" was an equally live explanation
and nothing distinguished them.

Settled 2026-09-16: a **well-formed** body — documented shape, `orderId` present, every
required field supplied, verified against the live detail response — still returns
`HTTP 403 - Access Denied`. Body shape is eliminated as the cause. The operator block stands.

Note for anyone tempted by the obvious control (resend the same body with a non-blocked
operator, holding everything else constant): **do not run it against an alert you want to
keep.** The body carries `orderId`, so it modifies in place, and restoring the original
requires `<=` — which 403s. The alert cannot be put back.

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

## Price alerts: the gateway rejects the two operators the API documents most

**Alerts had never been exercised end to end.** Reviewed and measured 2026-09-16 against a
live authenticated gateway.

**A body containing `>=`, `<=` or `!=` never reaches IBKR.** It comes back as an opaque
HTML `403 Error 403 - Access Denied`, with nothing in the gateway log. Measured, isolating
one field at a time:

| Body contains | Result |
|---|---|
| `>=`, `<=`, `!=` — in `operator` **or** in `alertName` | **403 HTML**, request never reaches the alert API |
| `>`, `<`, `=`, `==`, `=>`, `=<`, plain text | `500` + a real IBKR JSON validation error |

So the filter is **body-wide, not field-specific**, and it is not a permissions problem:
`DELETE /iserver/account/{acctId}/alert/{id}` — also a write — reaches IBKR and answers
`{"error":"failed to delete alert: Alert 999999999 doesn't exist"}`. Calling the documented
prerequisite `GET /iserver/accounts` first, or `tickle`, changes nothing.

**Whether the filter is the local gateway or IBKR's edge is undetermined.** `conf.yaml` sets
`proxyRemoteHost: https://api.ibkr.com`, and the gateway logs nothing for these requests.
Recorded as unknown rather than guessed.

**The consequence.** IBKR documents `operator` as an enum of `>=`, `<=`, `>`, `<`, `==`, and
its own sample body uses `"<="`. **None of the five can create an alert.** `>=` and `<=`
never arrive; `>`, `<` and `==` arrive and are refused by IBKR's own engine
(`can't recognize fix [>]`, the table below). This paragraph read "Three of the five are
usable through the gateway" until 2026-09-16 — contradicting that table twelve lines down,
and reading as though an alert could be created with `>`. It cannot. "Not blocked by the
403 filter" is not "usable".

**This is why alert writes have always "skipped".** `tests/test_client_live.py` and
`tests/test_alerts_live.py` recorded the 403 as "alert write requires trading session
permissions (CP API restriction)" and `docs/audits/live-test-log.md` carries "All 10 write
tests | SKIP (403)" on that basis. A write verb works, and the failure is payload-dependent,
so that attribution is wrong.

**The create/modify page is not where the other alert pages are.**
`v1/endpoints/alerts/create-or-modify-alert.md` returns "# Page Not Found", and no page under
`v1/endpoints/` declares `POST /iserver/account/{accountId}/alert`. The real page is
`api-reference/trading/trading-alerts/create-alert.md` (28,219 B) and is **absent from
`llms.txt`** — the case CLAUDE.md names, where the index's silence proves nothing and
`firecrawl_search` settles it. It also answers a question the archived capture could not:
`orderId` is "optional; used in case of modification and represent Alert Id", so it is the
create-vs-modify discriminator.

### Why this cannot be worked around

Measured 2026-09-16, in this order, each step ruling out the next-most-likely cause:

| Attempt | Result |
|---|---|
| Every value in IBKR's documented `operator` enum | `>` `<` `==` reach IBKR and are refused by its own engine: `{"error":"Condition #1:can't recognize fix [>]"}`. `>=` `<=` never arrive (403) |
| Other spellings — `&gt;=`, `gte`, `GE`, `5`, `A` | all "can't recognize fix" |
| JSON unicode escapes — `"\u003e="`, `"\u003e\u003d"` (no literal `>` or `=` in the raw bytes) | still 403, so the filter is not a naive byte scan of the body |
| `GET /iserver/accounts` prerequisite, then POST | 403 |
| `tickle`, then POST | 403 |
| Rebuilding the gateway image for a newer build | **pointless** — `HEAD` on `download2.interactivebrokers.com/portal/clientportal.gw.zip` returns `Last-Modified: Mon, 24 Apr 2023`. The running container reports that same build, so it is not stale: that IS IBKR's currently published gateway |

**Conclusion: the only two operators IBKR's alert engine accepts are the only two that
cannot reach it.** Price alert creation and modification are not possible through the Client Portal Gateway as published. This is an upstream defect, not a configuration
mistake, and no code change in this package can resolve it.

What this package should do about it is be honest: a `403` here means this, not "your
account lacks permission", and the alert write tools should say so rather than surfacing
an opaque gateway error.


## Order status carries prices IBKR does not document

`GET /iserver/account/order/status/{orderId}` returns `limit_price` on a limit order and
`stop_price` on a stop. **Neither appears in IBKR's documentation** — not in the field list,
not in the example response object, which for prices carries only `average_price` ("the
average price of execution") and `exit_strategy_display_price`.

They are real. Measured live 2026-09-04 on three resting orders: `limit_price` `'150.00'`
and `'7660.00'` on limit orders, `stop_price` `'7732.00'` on a stop with `limit_price` set
to the empty string. A STOP_LIMIT sets both. The measurement and the readback logic built on
it live in claudia_ui's `order_flow._price_readback_fields`; this entry exists because a
contributor reading only IBKR's page would find nothing and conclude the read was a mistake.

Two consumers in this package depend on it:

- `_cancel_dialog_details` reads `limit_price or stop_price` into the Gate 2 cancel dialog's
  `price` row. The empty string on a stop is why `or` is correct rather than a `None` check.
- `tests/test_readers_against_live_shapes.py` pins the endpoint's shape from IBKR's published
  example and allow-lists exactly these two keys, each entry carrying its measurement. A key
  added to that allow-list without one fails `test_every_allow_listed_key_carries_its_evidence`.

Verified 2026-09-21: the page was re-fetched (5,977 B, with a fabricated control URL in the
same batch returning 440 B `# Page Not Found`) and still documents neither field.

Source: https://www.interactivebrokers.com/docs/web-api/v1/endpoints/order-monitoring/order-status.md


## A bracket's children are auto-OCA'd onto the parent's own order id

`GET /iserver/account/order/status/{orderId}` on a bracket **child** returns **both**
`parent_order_id` and `oca_group_id`, holding the **same** value — and that value is the
**parent's own `order_id`**. `oca_group_type` reads `ReduceOnFillNonBlock`. The **parent**
carries neither field; it carries `children_order_ids` (a string).

**Measured live 2026-09-22** against the account holder's gateway: a read-only probe of
resting orders, no write of any kind, on **two independent brackets**, both CL futures.
Order ids, quantities and the account are deliberately not reproduced — this repository is
public, and an order id is account data.

So IBKR groups the legs for us, under an identifier this package never sends and cannot
choose. Nothing here asks for an OCA group: `_bracket_tickets` sends `cOID` on the parent and
`parentId` on each child, exactly as IBKR's bracket page documents, and `isSingleGroup` is
never set. The grouping is IBKR's own behaviour for a `parentId`-linked bracket.

### Why this entry exists: H1 is per child, not a sum

*A bracket child is never larger than the parent* (H1) is enforced **per child** —
`client._bracket_tickets` compares each child with the parent and never sums them, and
`order_confirm.confirm_bracket_dialog` repeats the rule the same way. A parent of 1 with two
children of 1 therefore passes, aggregate 2 against a parent of 1. **That is deliberate. Do
not add an aggregate check.** Two independent reasons, of different standing:

- **DOCUMENTED.** IBKR's own published bracket sizes **both** children at the full parent
  quantity — 50 / 50 / 50, with no `isSingleGroup` — because that is what the shape is for: a
  full-size profit taker **and** a full-size stop on one position. `sum(children) <= parent`
  refuses IBKR's standard bracket.
- **MEASURED**, as above. The legs are mutually exclusive at the exchange, so the aggregate
  can never be working at once. That is *why* per child is the right granularity, rather than
  a convenience the code settled for.

### The standing of each field name

A contributor will check these against IBKR's documentation and find nothing, so it is
written down rather than left to be rediscovered:

| Field | Where it appears |
|---|---|
| `parent_order_id`, `oca_group_id`, `oca_group_type`, `all_or_none` | **No IBKR page.** Real but undocumented — the same class as `limit_price` / `stop_price` above |
| `allOrNone`, `isSingleGroup` | Documented, on the submit-new-order page, as **request body** fields |
| `ocaType` | Not in IBKR's Web API body spec at all |
| `minQty` | Does not exist anywhere in it |

`all_or_none` on order status is **UNVERIFIED, not disproved**: it was absent from every
response in this probe, every resting order was a CL future, and AON is not supported on
futures — so the stock case is untested. A whatif control the same day showed `allOrNone:
true` is *accepted* on a stock ticket, and the control without it was accepted too; that
proves the field is legal in the body and says nothing about whether it is retained or read
back.

### Fill quantities on order status

`cum_fill` and `total_size` are both present and both arrive as **strings**. `size` is present
too, and IBKR documents it as the **remaining unfilled** quantity — so `size` must never be
used for a fill comparison. `cum_fill` against `total_size` is the comparison that means what
it looks like. All three are in IBKR's own documented example for the endpoint, unlike the
four fields in the table above.

### What this measurement did NOT establish

Stated so neither is later cited as proven here:

- That a **full** fill of one leg cancels its sibling. The account holder reports this from
  their own trading; this probe did not reproduce it.
- What IBKR does to a sibling on a **partial** fill. Untested. `ReduceOnFillNonBlock` is
  suggestive, but reading a type name is not measuring a behaviour.

`parent_order_id` is already load-bearing in this package: `pair_bracket_response` matches a
returned child to its parent by it, because IBKR's response array is **not** index-aligned
with the submission. If that reader is ever added to `DOC_SHAPE_READERS` in
`tests/test_readers_against_live_shapes.py`, `parent_order_id` will need an entry in that
file's `_MEASURED_BUT_UNDOCUMENTED` map — this measurement is its evidence.

Sources: https://www.interactivebrokers.com/docs/web-api/v1/endpoints/order-monitoring/order-status.md,
https://www.interactivebrokers.com/docs/web-api/v1/endpoints/orders/bracket-orders-oca-groups.md,
https://www.interactivebrokers.com/docs/web-api/api-reference/trading/trading-orders/submit-new-order.md
