# Known IBKR API Behaviors (Documented, Not Assumed)

These are verified against official sources — not guesses:

- **`/iserver/account/orders`** — subscription warmup, but **once per session, not once per call**. A fresh brokerage session's first read returns an empty array; `force=true` clears cached state to instantiate the subscription ("Force the system to clear saved information and make a fresh request for orders. Submission will appear as a blank array"). Until 2026-09-16 `get_live_orders` and `get_orders_raw` sent that pair before **every** read, spending two slots of a 1-req/5-secs endpoint to answer one question. **Measured live 2026-09-16 on a warm session: three consecutive plain reads, with no `force=true` ahead of them, each returned the open order** (conid 265598, orderId 1986940574). Both methods now read first and prime only when the read comes back empty — the same shape `get_trades` already used for the identical warmup on `/iserver/account/trades`. Effect with pacing enforced: `get_live_orders()` went from 5.17 s to 0.35 s, and from 10.07 s to ~5.0 s when called twice back to back (the remaining 5 s is the published limit itself). Sources: [live-orders](https://www.interactivebrokers.com/docs/web-api/v1/endpoints/order-monitoring/live-orders), [IBKR Campus — Orders](https://www.interactivebrokers.com/campus/trading-lessons/request-modify-orders/)
- **`/iserver/marketdata/history`** — primary fetch endpoint, max 1000 data points per request. First-call warmup (404/500) auto-retried 3× with 2s delay in `claude_tools.py`. Pagination for large requests handled by `get_market_history_paginated()`. **`startTime` is the END of the returned window, not the start** — the spec calls it "a fixed UTC date-time reference point ... from which the specified period extends", and measurement settles the direction (conid 756733, anchor `20231109-00:00:00`, `period=100d`, 2026-08-05): `direction` omitted → 2023-06-20 → 2023-11-07; `direction=-1` → **identical**; `direction=1` → `{"error": "Chart data unavailable"}` on that conid, despite the spec documenting it as supported whenever `startTime` is included. So the default is backwards. **The claim that the forward direction "does not work" was generalised from one instrument and is wrong** — re-measured 2026-09-16 with `startTime=20260601-00:00:00`, `period=10d`, `bar=1d`: AAPL (265598), MSFT (272093), NVDA (4815747) and IWM (9579970) all returned proper forward windows (2026-06-03 → 2026-06-15), while **SPY (756733) and QQQ (320227571) returned HTTP 500 `Chart data unavailable`** in all four anchor/period combinations tried. It is neither security type nor exchange: IWM is an ARCA ETF that works and SPY is an ARCA ETF that does not. The original conid-756733 result reproduced exactly, so IBKR did not change anything — the rule was over-stated. **`direction=-1`, which `get_market_history_paginated` sends, worked on all six**, and end-to-end pagination returned identical results for all six (5d/5min: 299 bars, 5.2d span, 0 duplicates), so no code path is affected. **The newest chunk must send no `startTime` at all** ("if omitted, the current time is used"): on SPY `30d`/`1d`, omitted reached 2026-08-05, an explicit timestamp of that same moment reached 08-04, midnight-today reached 08-03. Reading `startTime` as the start cost a **silent 1,010-day-stale result** — SPY `5y`/`1w` returned 291 well-formed bars ending 2023-10-30 with no error — for every request wider than one chunk (`3y`/`5y` on most bars, `1y`/`2y` on `1h`). Fixed 2026-08-05. **A code fix is not sufficient: `_fetch_market_data` returns "Cache HIT" and serves the stored parquet without re-fetching**, so poisoned windows persist until purged with `GDriveCache.delete()`. Source (the reference that resolves — the old campus URL 404s): https://api.ibkr.com/gw/api/v3/api-docs
- **A wide intraday request can exhaust the pagination guard and come back short.** IBKR's step table caps `1min` and `5min` requests at a 1-day period, so `get_market_history_paginated` needs roughly one chunk per *trading* day and `_MAX_CHUNKS = 120` is reached at about 120 trading days (~5.5 calendar months) for RTH equity data — sooner for a continuously-traded instrument, where a chunk covers one calendar day. Until 2026-09-16 the result was a well-formed short answer with only a `log.warning`, which reaches no caller, no model and no cache. **Verified live 2026-09-16** (conid 265598, AAPL, `outside_rth=False`): `1y`/`5min` hit the guard at exactly 120 chunks and returned **9,344 bars covering 174 of 365 days — 47.7%**, back to 2026-03-26. The same run measured 29.3 requests/min against the published 50/min ceiling, i.e. network-bound rather than pacer-bound, so proactive pacing costs nothing here. A control in the same session, `90d`/`1min`, finished in 62 chunks at 100.2% coverage and correctly carried no warning. The response now carries `ibkr_core_warning` naming the period asked for, the guard, and the date actually reached, and `fetch_market_data` **refuses to cache** a flagged result — a partial window stored under the requested period would answer every later request for that period, on every machine, exactly as the 2026-08-05 `startTime` poisoning did.
- **`trades.time` has two formats, written by two paths** — `flex_query` writes ISO (`2026-08-04T14:21:42`); the live CP API path and the WebSocket `str` path write IBKR's compact `20260804-14:21:42`. `upsert_trades`' `ON CONFLICT` deliberately does not update `time` (first observation of a fill is authoritative), so a live-captured row keeps the compact form permanently. Until 2026-08-05 `get_trade_date_coverage` matched the ISO shape only and could not see them: **38 of 1,206 rows (3%) on the live account**, with the newest reportable date 2026-08-04 while the table already held 2026-08-05. The sharp consequence was not the missing day but that a window holding *only* live-captured trades would read as a 45+ day gap — reported to the user as inactivity. Now: `time` is normalised to ISO on write, the **activity report** reads every row via `_TRADE_DATE_SQL` (both formats), and the **staleness flag** deliberately still reads settled `flex_trade` rows (`source='flex'`) only — Flex is T+1, so today's live fill is exactly the trade whose settled record has not arrived, and counting it would suppress the pull that brings it.
- **`/iserver/account/trades`** — **the direct access point for today's + recent fills**: `get_trades(source='live')` → `client.get_trades()` → `GET /iserver/account/trades?days=7`. It is the only REST source that can contain same-day executions (Flex is T+1). Official reference documents: "a list of trades for the currently selected account for current day and six previous days" (`?days=7` max), "advised to call this endpoint once per session." Origin coverage is not documented officially but **verified live 2026-07-06: all origins appear (mobile included) once the subscription is primed** — the endpoint has the same two-call warmup as `/iserver/account/orders` (fresh session's first call returns empty; `client.get_trades()` auto-retries once, 1 s apart). The 2026-07-02 empty observation was this warmup, not an origin filter. For real-time execution push, the WebSocket **`str` (trades) topic** is implemented in `streaming.py` (`IBKRWebSocket.subscribe_executions()`/`unsubscribe_executions()`, args: `realtimeUpdatesOnly`, `days`) and persists executions into the same `trades` table used by REST/Flex via `_parse_stream_execution()` — so `get_trades(source='store')` and `ibkr://trades/recent` pick them up automatically once a `--stream` server has captured them. Beyond 7 days or for origin-complete history: the Flex store. Source: CP API reference "Trades" + WebSocket sections, scraped 2026-07-02, `str`/`spl` topics re-confirmed 2026-07-06.
- **Flex Web Service** — T+1 delay, back-office data. Captures all trades from all interfaces (mobile, TWS, API). Requires separate token + query ID, not CP API credentials.
- **Flex endpoint** — the initial `SendRequest` call goes to `ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/SendRequest`, matching official docs. The follow-up `GetStatement` URL that IBKR returns in the `SendRequest` response, however, is observed live pointing at **`gdcdyn`**, not `ndcdyn` — both are legitimate IBKR Flex subdomains and both are allowlisted by the SSRF guard in `flex_query.py` (`_ALLOWED_URL_PREFIXES`). Treating `gdcdyn` as categorically wrong was itself a past incident (see CLAUDE.md's Flex endpoint URL row) — the earlier bug was assuming the *wrong path* (`gdcdyn.../Universal/servlet/...`) for the *first* call, not that `gdcdyn` never legitimately appears. Requires a `User-Agent` header for programmatic access. Observed live 2026-06-26.
- **`/md/regsnapshot` (Regulatory Snapshot) — permanently removed by IBKR.** Announced via the official [Web API Changelog](https://www.interactivebrokers.com/docs/web-api/changelog), dated **2026-02-11**, tagged `warning`: *"The /md/regsnapshot endpoint is no longer supported for users to query a regulatory snapshot via API."* Enforcement was not immediate — the endpoint still returned real live NBBO data (with the documented $0.01 charge) as recently as the 2026-07-08 integration baseline, and only started returning `HTTP 404: Resource not found` sometime between 2026-07-08 and 2026-07-22 (no separate changelog entry marks the exact cutover date). `get_regulatory_snapshot()` was removed from `client.py` accordingly (dead API surface, not an entitlement gap on the calling account) — see `docs/audits/live-test-log.md` run `2026-07-22-1` for the full investigation.
- **`/trsrv/secdef/schedule` — IBKR publishes three disagreeing "trading schedule" pages, and `exchange=SMART` returns an empty list.** Measured live 2026-09-16 on an authenticated gateway. **(1) The parameters.** The gateway enforces `{"error":"Bad Request: assetClass and exactly one of symbol/conid are required"}` — both together is a 400, neither is a 400. The **API Reference** ([get-trading-schedule](https://www.interactivebrokers.com/docs/web-api/api-reference/trading/trading-contracts/get-trading-schedule)) documents `assetClass` + `symbol` required and **no `conid` parameter at all**, which matches the gateway; the older narrative page (`v1/endpoints/contract/trading-schedule-by-symbol`) lists **both** `conid` *and* `symbol` as *Required* — a combination that cannot succeed. A fix written from that page shipped a guaranteed 400 and was caught only by running it. `conid` does work as an undocumented **alternative** to `symbol` (265598 and `AAPL` returned the same 125 rows). **(2) A third page is a different endpoint**: `v1/endpoints/contract/trading-schedule-new` documents `GET /contract/trading-schedule`, keyed by `conid`, returning `exchange_time_zone` and a date-keyed `schedules` object — not implemented here. **(3) `exchange` decides whether you get anything, and omitting it returns the most.** Measured on AAPL: no exchange **141 rows**, `ISLAND` 125, `SMART` **0**. SMART is IBKR's smart-routing destination and the correct default nearly everywhere — `get_option_chain`, secdef strikes and the alert condition all pass it and all work, verified live the same day. This endpoint is the exception: its `exchange` means *a venue with published trading hours*, not a route, and SMART has none, so it returns an empty list rather than an error. The empty `trading_schedule` in `tests/fixtures/ibkr_live_shapes.json` is that, not a defect and not a missing parameter — and the `get_trading_schedule` **tool** defaulted its `exchange` to SMART until 2026-09-16, so its minimal call (`symbol` is the only required input) answered `[]` for every equity (TOOL-R1). **(4) The response object.** The wire returns `id`, `tradeVenueId`, `exchange`, `description`, `timezone`, `schedules[]` — six keys, matching the API Reference exactly. The narrative page omits `exchange` and `description`. Neither page nor wire has `regularTradingHours` or `liquidHours`, which `docs/tools-reference.md` promised until 2026-09-16.

## Alerts: the detail response and the write body are different vocabularies

Measured against a live gateway (build 2023-04-24) on 2026-09-16, using a real alert created
on IBKR Mobile (`AAPL <= 1.00`, GTC, order_id 1331320792):

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
cannot reach it.** Price alert creation and modification are not possible through the
Client Portal Gateway as published. This is an upstream defect, not a configuration
mistake, and no code change in this package can resolve it.

What this package should do about it is be honest: a `403` here means this, not "your
account lacks permission", and the alert write tools should say so rather than surfacing
an opaque gateway error.

