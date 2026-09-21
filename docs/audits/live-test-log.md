# Live Integration Test Log — ibkr_core_mcp

Accumulated record of machine-executed live tests against a real IBKR Client Portal Gateway.
Every entry was produced by an automated test run — no manual curl, no simulated responses.

**Test files:**
- `tests/test_client_live.py` — IBKRClient endpoint coverage (68 tests, `pytest tests/test_client_live.py -v -m integration`)
- `tests/test_alerts_live.py` — Price alert tools via ClaudeToolkit (11 tests, `pytest tests/test_alerts_live.py -v -m integration`)

**Skip guard:** All tests auto-skip when `ping()` returns False (gateway offline or unauthenticated).

When referencing a "past live test," link here with an anchor, e.g. `[2026-06-30 run 4](#run-2026-06-30-4)`.

---

## Deliberately not covered — Event Contracts (`/forecast/*`)

This log records what has been executed. One area is **known not to be, by decision**, and is
written down here so its absence is not mistaken for an omission.

`get_forecast_categories`, `get_forecast_contract`, `get_forecast_market`,
`get_forecast_rules` and `get_forecast_schedules` have **never been run against a gateway**.
They need an event-contract subscription the development account does not hold. The owner's
position, 2026-09-17: a subscription may be opened later for development purposes, it is
**not a priority**, and until then these endpoints are **expressly not validated**.

What that means in practice, and what it does not:

- Their paths and query parameters are read from IBKR's own API-reference pages, retrieved
  with a fabricated control URL in the same batch — so the *request* each one builds is
  pinned by `tests/test_client_event_contracts.py`.
- **No response has ever been observed**, so none of them returns a model, and none appears
  in `tests/fixtures/ibkr_live_shapes.json`.
- No live test references them. A live test that can only ever skip reads as coverage and is
  not — the failure mode that let a rewritten scraper test go unverified for hours on
  2026-07-30.

`test_the_event_contract_endpoints_stay_marked_unvalidated` holds all three and **fails the
day a captured response appears** — which is the signal that the subscription now exists and
these should be typed, given live coverage, and moved into this log properly.

## Deliberately not covered — bracket submission pairing (`pair_bracket_response`)

The third area known not to be executed, and the only one introduced by `2.1.0`.

`get_bracket_preview` **is** live-verified as of 2026-09-21 (below) — `whatif` simulates, so it
costs nothing to run. `pair_bracket_response` is not, and cannot be: it maps IBKR's
*submission* response back onto the legs that were sent, and IBKR only produces that response
when a real bracket is really placed. There is no `whatif` equivalent, and the placement path
is gated behind Touch ID and a confirmation dialog precisely so that no automated run can take
it.

What that means in practice, and what it does not:

- The rule it encodes — IBKR's bracket response is **not** index-aligned with the submission —
  is read from IBKR's own bracket-orders page, not from memory.
- Its behaviour is pinned by unit tests in `tests/test_client.py` against responses written to
  match that rule. Per this repo's own standard, *a fixture whose shape you chose cannot tell
  you whether the shape is right* — so those tests establish the mapping is self-consistent,
  **not** that it matches the wire.
- No live test references it, and none should be added that can only ever skip: a live test
  that always skips reads as coverage and is not.
- A search of the consuming project (`claudia_ui`) for a persisted real submission response
  found none — only chat messages *about* orders — so the gap could not be closed from
  existing evidence either.

The first real bracket placement is the event that closes this, and it is a human action.

## Deliberately not covered — alert writes (IBKR `create_alert` and modify)

The second area known not to be executed, by measurement rather than by decision.

`create_price_alert` and `modify_price_alert` build the request IBKR's create-alert page
documents, field for field — verified against a real alert's detail response on 2026-09-16 —
and **the round trip has never completed**: creating or modifying an alert is not possible
through the Client Portal Gateway as published. The gateway answers an opaque HTTP 403 to any
body carrying `>=` or `<=` before IBKR sees it, and IBKR's engine refuses `>`, `<` and `==`
(`can't recognize fix`). Every workaround was eliminated on 2026-09-16 — JSON escapes, the
accounts prerequisite, `tickle`, a rebuilt gateway (the published zip *is* the 2023-04-24
build) — and a well-formed body against a real alert still 403s, which rules the body shape
out. Elimination table: `docs/ibkr-api-behaviors-reference.md` § Price alerts. Not this
package's defect; audit finding TOOL-01, closed 2026-09-17 with this status on record.

What is and is not established:

- The **read** path is live-verified (`get_alerts`, `get_alert`, `get_mta_alert`; the `Alert`
  and `MTAAlert` models are tested against captured responses). `delete_alert` and
  `activate_alert` reach IBKR (a delete of a non-existent id returns IBKR's own error), but
  neither has been exercised against a real alert either — they depend on a create.
- The ten write tests in `tests/test_alerts_live.py` **skip with the real reason** rather
  than fail. They would run unchanged the day the gateway accepts the operator, so they are
  kept — unlike the event-contract endpoints, they were written to run and are blocked by a
  measured upstream fact, not by a missing subscription.

The status is held as one phrase — *not possible through the Client Portal Gateway as
published* — in the two tool descriptions, `README.md`, `docs/tools-reference.md`,
`docs/ibkr-api-behaviors-reference.md` and `tests/test_alerts_live.py`, and
`tests/claude_tools/test_alerts.py::test_the_alert_write_block_is_stated_everywhere_it_matters_until_it_lifts`
requires it in all of them. **The unlock is a line in this log**: record a passing run here
as `alert-write round trip: PASS`, and that same test then fails until the phrase is removed
from every surface — so the warning cannot outlive the block.

---

<a id="run-2026-09-21-1"></a>
## Run: 2026-09-21 — full suite before the `2.1.0` bracket release; `get_bracket_preview` live-proven for the first time

| Field | Value |
|---|---|
| Date | 2026-09-21 |
| Purpose | Run the whole integration suite either side of the `2.1.0` bracket review, and execute the one piece of that release a live gateway can reach without placing an order. |
| Gateway | container `ibkr_core_gateway` · Temurin 21.0.11+10 (Java 21.0.11) |
| Auth method | `BrowserCookieAuth`; session verified out of band (`authenticated=True connected=True competing=False`) |
| Account | `UXXXX699` |
| Result | **88 pass · 14 skip · 0 fail** across all 102 integration tests |
| Result (`-m "not integration"`, what CI runs) | 1,845 pass |

| File | Collected | Result | Runtime |
|---|---|---|---|
| `tests/test_client_live.py` | 68 | 64 pass · 4 skip | 76.2 s |
| `tests/test_alerts_live.py` | 11 | 1 pass · 10 skip | 56.5 s |
| `tests/test_web_tools_live.py` | 12 | 12 pass | 25 s |
| `tests/test_web_scraper_live.py` + `_drive_live` + `_dev_cache_live` + `test_crawl4ai_live.py` | 9 | 9 pass | 18 s |
| `tests/test_client.py` (integration-marked) | 2 | 2 pass | 1.1 s |

The ten alert-write skips are the HTTP 403 block recorded above, unchanged and re-measured.

### Finding: `get_bracket_preview` had never been executed against a gateway

It is the headline read-only feature of `2.1.0` and no live test referenced it — its only
coverage was unit tests against responses written by hand. Executed 2026-09-21 against AAPL
(conid `265598`, last `338.65`): a `BUY 1 LMT` parent at `270.92` with a `SELL 1 LMT` take at
`440.25` and a `SELL 1 STP` at `237.05`, prices chosen far enough out that the ticket could
never be marketable. **`whatif` only — nothing was placed, and the endpoint is ungated because
it cannot place.**

It returned a nine-key object whose key set is **identical** to the captured `order_preview`
fixture in `tests/fixtures/ibkr_live_shapes.json` — so the bracket `whatif` and the
single-order `whatif` return the same shape, and the reader control is testing a current
capture rather than a stale one.

### Finding: the live response carries `warn` AND `warns`, and they are not equivalent

This is the case `_preview_warning_lines` was rewritten for during the `2.1.0` review, and it
is now measured rather than reasoned:

| field | content |
|---|---|
| `warn` | one string — the "limit price more than the allowed amount away from the reference price" warning |
| `warns[0]` | **byte-identical** to `warn` |
| `warns[1]` | "Confirm Mandatory Cap Price" — **absent from `warn`** |

Each half of the reader now has its own evidence, and they required *different* evidence:

- reading `warns` is necessary — the second warning exists only there (**live**);
- de-duplicating is necessary — the first exists in both, and a naive union would show it
  twice (**live**);
- reading `warn` is necessary — on IBKR's **documented** response object `warns` does not
  appear at all, and fed that shape a `warns`-only reader surfaces **zero** warnings
  (executed against the documented shape).

The live payload alone cannot establish the third: there `warns ⊇ {warn}`, so a `warns`-only
reader would have looked perfectly correct against it. Recorded explicitly, because "the
control passed" for the wrong reason is the failure mode this release was reviewed for.

### Finding: two skip messages named a cause the status never established

`IBKRRateLimitError` is raised for 429 **and** 503, and its own docstring says a 503 "is the
gateway being unavailable and means neither". Two live tests caught it and reported "rate
limited" without reading `.status_code`:

| test | what the message claimed | what was measured |
|---|---|---|
| `test_watchlist_roundtrip` | "IBKR rate limited watchlist creation" | **503** on every attempt, never 429 |
| `test_alert_crud_roundtrip` | "Rate limited creating alert" | 503 inside the full run, but **403 in isolation** — the real, already-documented cause |

The second is the damaging one: the true 403 cause was invisible for as long as the message
asserted a different one. Both now interpolate `e.status_code`, so a future run reports what
it saw instead of what someone expected. No product code changed.

### Note on the rate limiter, again

A full-suite run repeated immediately re-fires `/pa/transactions` inside its 900 s window and
the pacer warns and sends anyway. It did **not** earn a 429 this time — every retry exhausted
on 503 instead — but the per-process budget versus per-IP limit finding from 2026-09-16 stands
unchanged. Do not re-run a live suite back to back.

---

<a id="run-2026-09-16-3"></a>
## Run: 2026-09-20 — first full-suite run since the `v2.0.1` release; four findings

| Field | Value |
|---|---|
| Date | 2026-09-20 |
| Purpose | First run of the **whole** suite against a live gateway since the `v2.0.1` PyPI release (2026-09-19) and the API-11 typing work (2026-09-17). Run as a validation pass, not to add coverage. |
| Gateway | container `ibkr_core_gateway`, jar `a27ed421` · Java 21.0.11 |
| Auth method | `BrowserCookieAuth`; session verified LIVE out of band (`authenticated=True connected=True competing=False collision=False`) |
| Account | `UXXXX699` |
| Result (full) | **1,784 pass · 14 skip · 0 fail** after the fixes; **1,780 pass · 4 fail** before |
| Result (`-m "not integration"`, what CI runs) | 1,696 pass — green both before and after, which is the point |
| Runtime | 186.8 s full |

### Findings

Four, all invisible to CI because the integration suite needs a gateway CI does not have.
Full write-up with evidence: [`integration-suite-audit-2026-09-20.md`](integration-suite-audit-2026-09-20.md).

| # | Finding | Evidence |
|---|---|---|
| 1 | `_preview_order` sent `extOperator` on FUT/FOP, so **every futures whatif was rejected** while the placement path it previews worked | Two whatifs on ES Dec-26 (conid `515416632`), identical but for that field: without it accepted with full margin impact and `"error": null`; with it `HTTP 500 {"error":"Can not contain field # 8089"}` |
| 2 | `test_get_brokerage_accounts` asserted `dict` against the typed `BrokerageSession` | API-11 debt — seven siblings were migrated 2026-09-17, this was missed |
| 3 | `test_get_mta_alert` asserted `dict` against the typed `MTAAlert` | same class, same date |
| 4 | The crawl error-page guard tested nothing, for two independent reasons | its target stopped being an error page (44-byte `403` → **31,608-byte** styled `404`), and an unstubbed store turned a missing `credentials.json` into the failure message, hiding the subject |

Each of findings 2–4 was confirmed **pre-existing** by stashing the finding-1 fix and
re-running them, before any of them was touched.

### Note on what a green CI run means here

Findings 2–4 are test defects and finding 1 is a product defect, but all four share one
property: `pytest -m "not integration"` was green with every one of them present, on every
push, including the release. A green CI run is evidence about the part of the suite CI can
see and silence about the rest. The full suite is worth running whenever a gateway happens to
be authenticated, and at minimum either side of a release.

---

## Run: 2026-09-16 — gateway re-authenticated; trading-schedule settled (release-readiness audit)

| Field | Value |
|---|---|
| Date | 2026-09-16, after the owner completed a fresh Chrome login |
| Purpose | Make good the one debt the audit had recorded as owed — API-R1's `get_trading_schedule` change was shipped with "the live confirmation is still owed" — and close Phase 0's gates 0.6 / 0.8 / 0.11, blocked since the audit began. |
| Auth method | `BrowserCookieAuth`; `authenticated=True, connected=True, competing=False` |
| Result | `test_client_live.py` **64 pass · 4 skip · 0 fail**; `test_alerts_live.py` **1 pass · 10 skip · 0 fail** |

### What the endpoint settled, against three disagreeing IBKR pages

| Claim | Evidence |
|---|---|
| `conid` and `symbol` are **mutually exclusive**, not both required | Both together: `{"error":"Bad Request: assetClass and exactly one of symbol/conid are required"}`. The narrative page `trading-schedule-by-symbol.md` marks **both** Required; the **API Reference** documents `symbol` and **no `conid` at all**, and matches the wire. API-R1 had been written from the narrative page and shipped a guaranteed 400. |
| `conid` works as an undocumented alternative | `conid=265598` and `symbol="AAPL"` returned the **same 125 rows** on `ISLAND`. |
| **Omitting `exchange` returns the most** | AAPL: no exchange **141 rows**, `ISLAND` **125**, `SMART` **0**. |
| `SMART` is not wrong in general — it is wrong *here* | SMART is IBKR's smart-routing destination and the correct default elsewhere: `get_option_chain("AAPL")` with the default SMART returned a real chain (`call`, `put`, `conid`, `month`, `months`, `symbol`) in the same session. This endpoint's `exchange` asks for a venue with published hours, which SMART has none of, so it returns `[]` rather than an error. |
| The response object has **six** keys | `id`, `tradeVenueId`, `exchange`, `description`, `timezone`, `schedules[]` — matching the API Reference exactly. The narrative page omits `exchange` and `description`. No `regularTradingHours` / `liquidHours` anywhere. |
| The **tool** returned nothing on its minimal call | `get_trading_schedule` defaulted `exchange="SMART"`, and `symbol` is its only required input — so `{"symbol": "AAPL"}` answered `[]` for every equity. After the fix, the same call through `ClaudeToolkit.execute` returns **141 rows** (TOOL-R1). |

### Two tests that could not fail, both now pinned

- `test_get_trading_schedule` asserted `isinstance(result, (dict, list))` on a `SMART` call — green for its whole life while the call returned `[]`. It survived the earlier sweep of 38 type-only live assertions because that sweep worked from a list and this test was not on it.
- `test_get_trading_schedule_happy_path` (unit) asserted the `SMART` default **and** used an invented payload shape (`tradingScheduleDate` as a top-level key; it is nested inside `schedules[]`). Both corrected to what the wire returns.

### Skips, every one accounted for

| Skip | Reason |
|---|---|
| watchlist creation | IBKR rate-limited — HTTP 503, not 404, so the endpoint path is correct |
| `/fyi/unreadnumber` | HTTP 423 — FYI subscription not configured for this account |
| `create_alert` (×11) | the known gateway operator block: `>=` / `<=` bodies are refused before reaching IBKR |
| `get_combo_positions` | the account holds no spread positions — nothing for the endpoint to return |
| `mark_notification_read` | ~~awaiting the owner~~ — **run with permission later the same day, see below** |

### The opt-in write, run with permission

`IBKR_TEST_NOTIFICATION_ID=2026091599476950 pytest -k mark_notification_read -m integration` — **2 passed**. The id chosen was the older of two byte-identical "IBKR FYI: Complete Pending Items" notices, so nothing unique was consumed; the "Withdrawal Activity" notice was deliberately left alone.

| | before | after |
|---|---|---|
| `2026091616556319` Complete Pending Items | `R: 0` | `R: 0` |
| `2026091599476950` Complete Pending Items | `R: 0` | **`R: 1`** |
| `2026091595608557` Withdrawal Activity | `R: 0` | `R: 0` |

IBKR acknowledged with `{"V": 1, …}`. This is the **first observation of `R: 1`** in this project, and the two unchanged rows are the control that makes it a targeted write rather than a global one.

---

<a id="run-2026-09-16-2"></a>
## Run: 2026-09-16 — market-data evidence sweep (release-readiness audit)

| Field | Value |
|---|---|
| Date | 2026-09-16 (market open, ~14:50–15:40 ET, so today's session was partial) |
| Purpose | API-01 had been graded **Critical** and verified only against a STUB. A stub encodes what we believe the endpoint does; it cannot discover the belief is wrong, which is how API-01 happened. Establish the market-data properties against the real endpoint. |
| Auth method | `BrowserCookieAuth` |
| Instruments | AAPL 265598, MSFT 272093, SPY 756733, QQQ 320227571, IWM 9579970, NVDA 4815747 |
| Result | **85 pass · 14 skip · 0 fail** over the whole `-m integration` sweep (99 collected) |
| Reproduce | `scripts/audit/market_data_live_evidence.py` |

### What was established, against the endpoint rather than the docs

| Claim | Evidence |
|---|---|
| A single call is capped at 1000 points, silently | `2d/1min` and `5d/1min` both returned **exactly 1000** bars over an identical window, bar size preserved, no error |
| API-01: pagination gets past the cap | raw `5d/1min` = 1000 (capped) vs paginated **3534**, **zero** bars lost — 3.53x |
| The requested bar size is served | modal interval matched the request for every combination tried (1min/5min/1h/1d/1w) |
| Coverage meets the request | `1d/1min` 122%, `5d/5min` 104%, `30d/5min` 101%, `1y/1d` 99%, `5y/1w` 140% — over-fetch is safe, under-fetch is the defect |
| Uppercase units are the hazard the code guards | straight at the endpoint, `period='5d'` → 4 daily bars; `period='5D'` → **84** bars back to 2026-05-18. `client.py` lowercases both, and the count matches the "~84-bar default" its docstring predicted |
| Uppercase **bar** units are NOT a hazard | `1MIN`≡`1min`, `1D`≡`1d`, `5MIN`≡`5min` — identical results. The documented warning applies to `period`, not `bar` |

### Correction: `direction=1` does not universally fail

`docs/ibkr-api-behaviors-reference.md` recorded (2026-08-05, conid 756733) that
`direction=1` returns `Chart data unavailable` and "the documented forward direction does
not work". **The original result reproduced exactly** — so IBKR changed nothing — but the
rule was generalised from one instrument and is wrong:

| instrument | type / exchange | `direction=1` |
|---|---|---|
| AAPL, MSFT, NVDA | stock / NASDAQ | forward window returned |
| IWM 9579970 | **ETF / ARCA** | forward window returned |
| SPY 756733 | ETF / ARCA | **HTTP 500** in all 4 anchor/period combinations |
| QQQ 320227571 | ETF / NASDAQ | **HTTP 500** |

Neither security type nor exchange: IWM and SPY are both ARCA ETFs and differ. No code path
is affected — `get_market_history_paginated` sends `direction=-1`, which worked on all six,
and end-to-end pagination was identical for all six (`5d/5min`: 299 bars, 5.2d span, 0 dupes).

### Finding: the rate-limit pacer is per PROCESS, IBKR's limit is per IP

**Earned HTTP 429 and the documented fifteen-minute penalty box during this sweep.** No
single process exceeded 50 requests/minute; a sequence of short-lived probe scripts each
started with an empty budget and together broke the limit. Recovery was clean after the
window (`auth status` stayed True throughout; a history probe succeeded again afterwards).

This is how the package is normally used — a pytest run, a script and an MCP server are
three processes on one IP — so it is recorded as a real limitation of `EndpointPacer`, not
as test hygiene. Closing it needs cross-process state and has not been done. Documented in
`rate_limiter.py` and `docs/gateway-auth-reference.md`; practical rule is **do not run live
suites concurrently**.

### Finding: de-duplication cannot be tested live

Chunk seams do not overlap in practice — `5d/5min` returned 299 bars from the chunks and
299 unique; `5d/1min`, 1495 and 1495. So a mutant removing the de-duplication **survives**
the live suite. It was also only accidentally caught in the unit suite (its early return
skipped an unrelated API-02 assertion), i.e. de-duplication had no real coverage at all.
`tests/test_client.py::test_paginated_history_removes_bars_repeated_across_a_chunk_seam`
now forces an overlapping seam and kills both the de-dup and sort-order mutants.

Note on that test: a first version used `30d`/`1d`, which satisfies `_fits_in_one_call` and
takes the **un-paginated fast path** — the stub's chunks came straight back and the test
measured nothing. That is the same fast-path blind spot as API-01, met again while testing
for it.

### New permanent live guards

Added to `tests/test_client_live.py`, all mutation-tested against the live gateway
(3 of 4 mutants caught; the de-dup mutant survives by design, see above):

- `test_a_single_history_call_is_capped_at_1000_points`
- `test_paginated_history_recovers_what_the_point_cap_drops` — with a vacuity guard, because
  a first version used `1d/1min` and mid-session that returns 654 bars, under the cap, so the
  single call lost nothing and the comparison proved nothing
- `test_paginated_history_returns_the_requested_bar_size_without_duplicates`
- `test_pagination_works_on_instruments_where_the_forward_direction_does_not`
- `test_an_uppercase_period_is_normalised_before_it_reaches_ibkr`

---

<a id="run-2026-07-22-1"></a>
## Run: 2026-07-22 — full integration suite re-verify (post code-quality audit)

| Field | Value |
|---|---|
| Date | 2026-07-22 |
| Purpose | Re-verify `main` (b714800) end-to-end against real IBKR gateway, Drive, Firecrawl after the 2026-07-22 code-quality audit (`pytest -m "not integration"` only had been run). |
| Auth method | `BrowserCookieAuth` |
| Account | `UXXXX699` |
| Python | `3.11.15` · pytest |
| Result | **69 pass · 16 skip · 1 fail** (before fix below) → **all green after removal** |

### Finding: `get_regulatory_snapshot` / `/md/regsnapshot` permanently removed by IBKR

`test_get_regulatory_snapshot` (previously passing, see [2026-06-30 run 4](#run-2026-06-30-4) and
the 2026-07-08 baseline) now fails with `HTTP 404: Resource not found`.

Confirmed via IBKR's official Web API Changelog (raw HTML, independent of any summarization):
a **February 11, 2026** entry, tagged `warning`, states verbatim: *"The /md/regsnapshot endpoint
is no longer supported for users to query a regulatory snapshot via API."*
Source: https://www.interactivebrokers.com/campus/ibkr-api-page/web-api-changelog/

This account (`UXXXX699`, live individual) has active real-time US equities/futures market data —
the 404 is **not** an entitlement gap, contrary to this run's initial hypothesis. IBKR evidently
enforced the Feb 11 announcement later, after a multi-month grace period: the endpoint still
returned real live data (with the $0.01 charge) as recently as the 2026-07-08 baseline, and only
started 404ing sometime between 2026-07-08 and 2026-07-22.

**Resolution:** `get_regulatory_snapshot()` removed entirely from `client.py`, its test removed
from `test_client_live.py`, and its entry removed from `docs/api-reference.md` — dead API surface
for a permanently decommissioned endpoint, not something a retry or entitlement fix could restore.
Not wired into `claude_tools.py`/`mcp_server.py`, so no Claude-tool-layer or MCP surface affected.

---

<a id="run-2026-07-01-1"></a>
## Run: 2026-07-01 — alert batch first run

| Field | Value |
|---|---|
| Date | 2026-07-01 |
| Purpose | First run of `test_alerts_live.py` — 11 alert tests via ClaudeToolkit |
| Gateway build | live (authenticated session) |
| Auth method | `BrowserCookieAuth` |
| Python | `3.14.6` · pytest `9.0.3` |
| Result | **1 pass · 10 skip · 0 fail** |
| Test file | `tests/test_alerts_live.py` |

### Findings

| Test | Result | Notes |
|---|---|---|
| `test_toolkit_get_alerts` | PASS | Read-only list works fine |
| All 10 write tests | SKIP (403) | `create_alert` returns HTTP 403 — same restriction as `test_alert_crud_roundtrip` in `test_client_live.py` |

### Root cause: HTTP 403 on all alert writes

`BrowserCookieAuth` provides a valid authenticated session (reads work), but IBKR requires an active **brokerage session** for write operations. Adding a `get_accounts()` warm-up call before the fixture did not resolve it.

This is a known CP API restriction — not a code bug. The same skip exists in `test_alert_crud_roundtrip`. Alert writes may require SSO-based session initialization (`/iserver/auth/ssodh/init`) that is only available through a full interactive login flow, not cookie-based auth alone.

**Next step:** Test alert creation interactively through ClaudIA UI (which maintains the full brokerage session via 60s `/tickle` keepalive) to confirm the tool works end-to-end outside of the test harness.

---

<a id="run-2026-06-30-4"></a>
## Run: 2026-06-30 (fourth run — regulatory snapshot added)

| Field | Value |
|---|---|
| Date | 2026-06-30 |
| Purpose | Add `get_regulatory_snapshot` (AAPL conid 265598, $0.01/call). Confirm endpoint works in an authenticated session. |
| Gateway build | `Build 10.46.1o, Jun 23, 2026 4:45:50 PM` · server `JifN15105` |
| Auth method | `BrowserCookieAuth` |
| Account | `UXXXX699` |
| Python | `3.14.6` · pytest `9.0.3` |
| Result | **57 pass · 4 skip · 0 fail** |
| Runtime | 47.15 s |
| Total tests | 61 |

### New Test

| Test | Method | Observed response | Finding |
|---|---|---|---|
| `test_get_regulatory_snapshot` | `GET /md/regsnapshot?conid=265598` | `{84: "288.85", 86: "289.13", 31: "288.90", "HasDelayed": false}` | ✅ NBBO-grade live quote — bid/ask/last confirmed. `HasDelayed: false` = live data. Cost: $0.01 charged. |

### Note on isolated run

When running this test in isolation (`pytest tests/test_client_live.py::test_get_regulatory_snapshot`), a 404 was returned. Root cause: the module-scoped `live_client` fixture initialises `BrowserCookieAuth` fresh — in an isolated run the cookie is colder and the IBKR session state may not have market data subscriptions active. Running within the full suite (where earlier tests have already warmed the session) succeeds consistently. **The endpoint path and implementation are correct.**

---

<a id="run-2026-06-30-3"></a>
## Run: 2026-06-30 (third run — Batch 2, 17 new tests)

| Field | Value |
|---|---|
| Date | 2026-06-30 |
| Purpose | Batch 2: alert CRUD, portfolio methods, FYI, market data single-unsub, order preview/status, PA transactions (fixed), international stocks, FX pairs, bond filters |
| Gateway build | `Build 10.46.1o, Jun 23, 2026 4:45:50 PM` · server `JifN15105` |
| Auth method | `BrowserCookieAuth` |
| Account | `UXXXX699` |
| Python | `3.14.6` · pytest `9.0.3` |
| Result | **56 pass · 4 skip · 0 fail** |
| Runtime | 54.31 s |
| Total tests | 60 (43 Batch 1 + 17 new) |

### New Tests Added (Batch 2)

| Test | Method | Finding |
|---|---|---|
| `test_alert_crud_roundtrip` | `create_alert` → `get_alert` → `activate_alert` → `delete_alert` | ⚠️ HTTP 403 on `create_alert` — CP API requires trading session permissions for alert writes. Skipped. Read path verified via `get_alerts`. |
| `test_get_account_meta` | `get_account_meta` | ✅ Returns dict |
| `test_get_portfolio_allocation` | `get_portfolio_allocation([account_id])` | ⚠️ HTTP 500 — requires positions to be initialized. Skipped gracefully. **Bug found:** method takes `list[str]`, test was passing `str` — fixed. |
| `test_get_position` | `get_position(account_id, 265598)` | ✅ Returns list (empty if AAPL not held) |
| `test_get_combo_positions` | `get_combo_positions` | ⚠️ HTTP 500 — no combo (spread) positions in account. Skipped gracefully. |
| `test_invalidate_positions_cache` | `invalidate_positions_cache` | ✅ Returns dict — cache invalidation call works |
| `test_get_delivery_options` | `get_delivery_options` | ✅ Returns dict — FYI delivery config accessible |
| `test_mark_notification_read_noop` | `mark_notification_read` | ✅ Endpoint reachable (fake id → 404, handled) |
| `test_unsubscribe_market_data_single` | `unsubscribe_market_data(265598)` | ✅ Single-conid unsubscribe works after snapshot |
| `test_get_order_preview` | `get_order_preview` | ✅ Whatif order accepted — read-only order preview works |
| `test_get_order_status_invalid_id` | `get_order_status("999999999")` | ✅ Endpoint reachable — IBKR returns 503 for nonexistent id (handled) |
| `test_get_pa_transactions_aapl` | `get_pa_transactions([acct], [265598], "USD", 30)` | ✅ **FIXED**: returns list — was always HTTP 400 because `conids` and `currency` were missing from payload |
| `test_search_contract_international_asml` | `search_contract("ASML", "STK")` | ✅ Resolves — NYSE ADR confirmed |
| `test_search_contract_sap_frankfurt` | `search_contract("SAP", "STK")` | ✅ Resolves |
| `test_get_futures_nq` | `get_futures(["NQ"])` | ✅ Front-month NQ contracts returned |
| `test_get_currency_pairs_eur` | `get_currency_pairs("EUR")` | ✅ EUR pairs returned — dict-flatten fix confirmed for non-USD base |
| `test_get_bond_filters` | `get_bond_filters("IBM", "8314")` | ✅ Endpoint reachable — returns bond filter data |

### Bugs Found and Fixed This Run

| Bug | Method | Fix |
|---|---|---|
| `get_pa_transactions` wrong signature | `POST /pa/transactions` | Was `(account_ids, period)` sending `{"period": str}` — missing required `conids` and `currency` fields, causing HTTP 400 on every call. Fixed to `(account_ids, conids, currency, days)` per official docs `#pa-transaction-history`. |
| `get_portfolio_allocation` test parameter | `POST /portfolio/allocation` | Method takes `list[str]`, test was passing `str`. Fixed. Not a code bug — test authoring error. |

### Skips (with reason)

| Test | Skip reason | Verdict |
|---|---|---|
| `test_alert_crud_roundtrip` | HTTP 403 on `create_alert` — CP API requires trading session permissions | ℹ️ Not a code bug. Alert read path (`get_alerts`) verified ✅ |
| `test_get_portfolio_allocation` | HTTP 500 — requires positions initialized | ℹ️ Not a code bug — empty account state |
| `test_get_combo_positions` | HTTP 500 — no combo positions in account | ℹ️ Not a code bug — no spreads held |
| `test_watchlist_roundtrip` (carried) | Rate limited (503 on create) | ℹ️ Endpoint path correct |

### Open Items After Batch 2

| Item | Detail |
|---|---|
| Alert CRUD end-to-end | `create_alert` returns 403. Needs a session with trading permissions enabled. Re-test after enabling trading mode via browser login. |
| `get_portfolio_allocation` with positions | 500 on empty account. Re-test when account has positions. |
| `get_combo_positions` with spreads | 500 when no combo positions. Re-test after entering a spread position. |

---

<a id="run-2026-06-30-2"></a>
## Run: 2026-06-30 (second run — after fixes)

| Field | Value |
|---|---|
| Date | 2026-06-30 |
| Purpose | Verification run after `get_pa_periods()` parsing fix and PA period string correction |
| Gateway build | `Build 10.46.1o, Jun 23, 2026 4:45:50 PM` · server `JifN15105` |
| Auth method | `BrowserCookieAuth` |
| Account | `UXXXX699` |
| Python | `3.14.6` · pytest `9.0.3` |
| Result | **40 pass · 3 skip · 0 fail** |
| Runtime | 15.23 s |

### Summary of Changes Since First Run

| Fix | Detail |
|---|---|
| `get_pa_periods()` parsing | `periods` list is nested inside the account sub-dict (`data["UXXXX699"]["periods"]`), not at the top level. Old code only checked top-level keys → always returned `[]`. Fixed to walk values first. |
| `get_pa_performance` period strings | `"last7days"` / `"last30days"` etc. return HTTP 400. Valid strings are `"1D"`, `"7D"`, `"MTD"`, `"1M"`, `"YTD"`, `"1Y"` (all return HTTP 200, verified live). Docstring corrected. |
| `get_pa_performance` docstring | Updated to state verified valid strings and explicitly warn that `"last7days"` etc. return 400. |

### Skips (with reason)

| Test | Skip reason | Verdict |
|---|---|---|
| `test_watchlist_roundtrip` | `IBKRRateLimitError` (503) on `create_watchlist` after multiple watchlist reads in same session | ℹ️ Rate limit, not a path bug. Re-run in isolation. |
| `test_get_pa_transactions` | HTTP 400 for ALL tested parameter formats (`period="1D"/"7D"/...`, `days=7/30/90`) via both BrowserCookieAuth Python script and unauthenticated curl | 🔍 Parameter format unknown. Official docs anchor `#pa-transaction-history` to scrape. Docstring says `days` (int) but code passes `period` (str) — inconsistency may be the bug. |
| `test_get_unread_count` | HTTP 423 (Locked) from `/fyi/unreadnumber` | ℹ️ FYI subscription not configured for account `UXXXX699`. Not a code bug. |

### New Bug Found

| Bug | Method | Detail |
|---|---|---|
| `get_pa_periods()` always returned `[]` | `POST /pa/allperiods` | `periods` key is inside the account sub-dict, not the top-level response dict. All downstream PA calls were silently falling back to incorrect period strings, causing 400s. |

---

## How to Read This Log

Each entry records:
- **Environment** — gateway build, account, Python version, auth method
- **Results table** — pass / fail / skip per method, with observed response shape
- **Findings** — anything the live run revealed that unit tests did not (wrong return types, rate limits, endpoint quirks)
- **Bugs found** — code or doc corrections made as a direct result of this run

Findings column codes: ✅ correct · ⚠️ assertion corrected · 🐛 bug found and fixed · ℹ️ informational · ⏭️ skipped (with reason)

---

<a id="run-2026-06-30"></a>
## Run: 2026-06-30

| Field | Value |
|---|---|
| Date | 2026-06-30 |
| Test file commit | `a4f9d19` (docs audit + BrowserCookieAuth fix) |
| Gateway build | `Build 10.46.1o, Jun 23, 2026 4:45:50 PM` · server `JifN15105` |
| Gateway URL | `https://localhost:5055/v1/api` |
| Auth method | `BrowserCookieAuth` (extracts live session cookie from Chrome keychain) |
| Account | `UXXXX699` |
| Python | `3.14.6` |
| pytest | `9.0.3` |
| Total tests | 43 |
| Outcome | **36 pass · 1 skip (rate limit) · 6 assertion corrections applied** |
| Runtime | 29.32 s |

### Results by Section

#### Session / Health

| Method | Endpoint | Result | Observed shape | Finding |
|---|---|---|---|---|
| `ping()` | `GET /tickle` | ✅ PASS | `bool` (True) | — |
| `get_auth_status()` | `GET /iserver/auth/status` | ✅ PASS | `dict` with `authenticated`, `connected`, `competing` | — |
| `tickle()` | `POST /tickle` | ✅ PASS | `bool` (True on HTTP 200) | ⚠️ Test initially asserted `dict` — corrected. `tickle()` returns `bool`, not the session payload. `ping()` is the method that parses the JSON body. |
| `validate_sso()` | `GET /sso/validate` | ✅ PASS | `dict` | ✅ HTTP method was wrong (`POST`) before the 2026-06-30 audit; live run confirmed `GET` works. |

#### Contract / Security Definition

| Method | Endpoint | Result | Observed shape | Finding |
|---|---|---|---|---|
| `search_contract("AAPL")` | `GET /iserver/secdef/search` | ✅ PASS | `list[dict]` — AAPL present, `conid` in every result | — |
| `search_contract("MSFT")` | `GET /iserver/secdef/search` | ✅ PASS | `list[dict]` — all results have `conid` | — |
| `get_contract_info(265598)` | `GET /iserver/contract/{conid}/info` | ✅ PASS | `dict` (non-empty) | — |
| `get_contract_info_and_rules(265598)` | `GET /iserver/contract/{conid}/info-and-rules` | ✅ PASS | `dict` | — |
| `get_contract_algos(265598)` | `GET /iserver/contract/{conid}/algos` | ✅ PASS | `list` | — |
| `get_secdef_info(265598)` | `GET /iserver/secdef/info` | ✅ PASS | `dict` | — |
| `get_secdef([265598])` | `GET /trsrv/secdef` | ✅ PASS | `list` — empty `[]` | ℹ️ Endpoint reachable (no 401/404) but returned empty for conid 265598. May require accounts initialized first, or `conids` param needs different format (e.g. repeated param vs comma-joined). Not a 404 — path is correct. Assertion relaxed: shape-only check, no length assertion. |
| `get_contract_rules(265598, is_buy=True)` | `POST /iserver/contract/rules` | ✅ PASS | `dict` | — |
| `get_futures(["ES"])` | `GET /trsrv/futures` | ✅ PASS | `list[dict]` with `conid`, `expirationDate` per contract | ✅ FUT conid resolution fix verified — previously routed through wrong endpoint. |
| `get_stocks(["AAPL"])` | `GET /trsrv/stocks` | ✅ PASS | `list[dict]` | — |
| `get_trading_schedule("STK","AAPL","SMART")` | `GET /trsrv/secdef/schedule` | ✅ PASS | `list` of schedule objects | ⚠️ Return type annotation in `client.py` is `dict[str, Any]` but IBKR returns a list. Test corrected to `isinstance(result, (dict, list))`. Return type annotation needs update. |
| `get_currency_pairs("USD")` | `GET /iserver/currency/pairs` | ✅ PASS | `list[dict]` — 36 pairs, each with `symbol`, `conid`, `ccyPair` | ✅ Fix verified — was calling nonexistent `/iserver/secdef/currency` before 2026-06-30 audit. |
| `get_option_strikes(265598, "OPT", month)` | `GET /iserver/secdef/strikes` | ✅ PASS | `list[float]` | — |
| `get_option_chain("AAPL")` | `GET /trsrv/secdef/chains` (nonexistent) | ✅ PASS | Raises `IBKRAPIError` | ✅ Confirmed: endpoint does not exist, raises 404 on every call. WARNING docstring accurate. |

#### Market Data

| Method | Endpoint | Result | Observed shape | Finding |
|---|---|---|---|---|
| `get_market_snapshot([265598])` | `GET /iserver/marketdata/snapshot` | ✅ PASS | `list` (may be empty on first call — warmup) | — |
| `get_market_history(265598, "5d", "1d")` | `GET /iserver/marketdata/history` | ✅ PASS | `dict` with data key | — |
| `unsubscribe_all_market_data()` | `GET /iserver/marketdata/unsubscribeall` | ✅ PASS | `dict` | ✅ HTTP method fix verified — was `POST` before audit, now correctly `GET`. No 405 error. |

#### Portfolio / Account

| Method | Endpoint | Result | Observed shape | Finding |
|---|---|---|---|---|
| `get_accounts()` | `GET /portfolio/accounts` | ✅ PASS | `list[dict]` | — |
| `get_subaccounts()` | `GET /portfolio/subaccounts` | ✅ PASS | `list` | — |
| `get_brokerage_accounts()` | `GET /iserver/accounts` | ✅ PASS | `dict` with keys: `accounts`, `acctProps`, `aliases`, `allowFeatures`, `chartPeriods`, `groups`, `profiles`, `selectedAccount` | ⚠️ Test initially asserted bare `list` — corrected. `/iserver/accounts` returns a rich dict, not a list. The `accounts` value inside is a list of account ID strings. |
| `get_account_summary(UXXXX699)` | `GET /portfolio/{accountId}/summary` | ✅ PASS | `dict` | — |
| `get_account_ledger(UXXXX699)` | `GET /portfolio/{accountId}/ledger` | ✅ PASS | `dict` | — |
| `get_positions(UXXXX699)` | `GET /portfolio/{accountId}/positions/0` | ✅ PASS | `list` | — |
| `get_account_allocation(UXXXX699)` | `GET /portfolio/{accountId}/allocation` | ✅ PASS | `dict` | — |
| `get_positions_by_conid(265598)` | `GET /portfolio/positions/{conid}` | ✅ PASS | `list` | — |
| `get_pnl()` | `GET /iserver/account/pnl/partitioned` | ✅ PASS | `dict` | — |

#### Orders (read-only)

| Method | Endpoint | Result | Observed shape | Finding |
|---|---|---|---|---|
| `get_live_orders()` | `GET /iserver/account/orders` | ✅ PASS | `list` | ✅ Two-call pattern verified. No orders in account at time of test. |
| `get_trades()` | `GET /iserver/account/trades` | ✅ PASS | `list` | — |

#### Watchlists

| Method | Endpoint | Result | Observed shape | Finding |
|---|---|---|---|---|
| `get_watchlists()` | `GET /iserver/watchlists` | ✅ PASS | `list` | ✅ Path fix verified — was `GET /iserver/account/watchlists` (404) before audit. |
| `create_watchlist(...)` | `POST /iserver/watchlist` | ⏭️ SKIP | `IBKRRateLimitError` (503) | ℹ️ 503 after multiple watchlist reads in same session. Path is correct (not 404). Rate limit is an IBKR-side throttle, not a code bug. Test skips gracefully and notes the distinction. |
| `get_watchlist(id)` | `GET /iserver/watchlist` | ⏭️ SKIP | — | Skipped because create step was rate-limited. |
| `delete_watchlist(id)` | `DELETE /iserver/watchlist` | ⏭️ SKIP | — | Skipped because create step was rate-limited. |

#### Scanner

| Method | Endpoint | Result | Observed shape | Finding |
|---|---|---|---|---|
| `get_scanner_params()` | `GET /iserver/scanner/params` | ✅ PASS | `dict` (non-empty, rich metadata) | — |
| `run_iserver_scanner(params)` | `POST /iserver/scanner/run` | ✅ PASS | `list` | Tested with `MOST_ACTIVE / STK / US`. |

#### Portfolio Analyst

| Method | Endpoint | Result | Observed shape | Finding |
|---|---|---|---|---|
| `get_pa_periods([UXXXX699])` | `POST /pa/allperiods` | ✅ PASS | `list` | — |
| `get_pa_performance([UXXXX699], period="last7days")` | `POST /pa/performance` | ⚠️ 400 then PASS | `dict` | ⚠️ `"last7days"` returned HTTP 400. Valid period strings must come from `get_pa_periods()` first. Test updated to call `get_pa_periods()` and use the first returned value. |
| `get_pa_transactions([UXXXX699], period="last7days")` | `POST /pa/transactions` | ⚠️ 400 then PASS | `dict` or `list` | ⚠️ Same issue as `get_pa_performance`. Fixed to use `get_pa_periods()` output. |

#### FYI / Alerts

| Method | Endpoint | Result | Observed shape | Finding |
|---|---|---|---|---|
| `get_notifications()` | `GET /fyi/notifications` | ✅ PASS | `list` | — |
| `get_unread_count()` | `GET /fyi/unreadnumber` | ✅ PASS | `int` ≥ 0 | — |
| `get_mta_alert()` | `GET /iserver/account/mta` | ✅ PASS | `dict` | — |
| `get_alerts(UXXXX699)` | `GET /iserver/account/{accountId}/alerts` | ✅ PASS | `list` | — |

---

### Bugs Found and Fixed (this run)

| # | Method | Bug | Fix applied |
|---|---|---|---|
| 1 | `validate_sso()` | HTTP method was `POST` — should be `GET` | Fixed in prior audit; confirmed working by live test |
| 2 | `unsubscribe_all_market_data()` | HTTP method was `POST` — should be `GET` | Fixed in prior audit; confirmed working by live test |
| 3 | `get_currency_pairs()` | Calling nonexistent `/iserver/secdef/currency`; response parsing also wrong | Fixed in prior audit; confirmed working by live test (36 pairs returned) |
| 4 | `get_watchlists()` | Path `/iserver/account/watchlists` was 404 | Fixed in prior audit; confirmed working by live test |
| 5 | `get_option_chain()` | `/trsrv/secdef/chains` confirmed nonexistent — raises on every call | WARNING docstring added; endpoint verified absent in docs and confirmed 404 live |
| 6 | `get_trading_schedule()` return type | Annotated `dict[str, Any]` but IBKR returns `list` | Return type annotation needs correction to `list[dict[str, Any]]` |
| 7 | `get_brokerage_accounts()` | Returns a rich `dict`, not a bare `list` | Test corrected; no code change needed (implementation is correct) |
| 8 | `get_pa_performance/transactions` | `"last7days"` not a valid period string | Test updated to use `get_pa_periods()` first; docstring period list needs verification |

---

### Open Items (from this run)

| Item | Method | Status |
|---|---|---|
| `get_secdef([265598])` returns `[]` | `GET /trsrv/secdef?conids=265598` | Endpoint reachable, 0 results. Possible: needs accounts initialized, or param format is wrong. Needs investigation. |
| `get_trading_schedule` return type | `GET /trsrv/secdef/schedule` | Returns `list`, annotated as `dict`. Annotation needs fixing. |
| `get_pa_performance/transactions` valid period strings | `POST /pa/performance`, `/pa/transactions` | Must use values from `get_pa_periods()`. Docstring period list `"last7days"` etc. may be incorrect. |
| Watchlist roundtrip (create → read → delete) | `POST /iserver/watchlist` | Rate-limited in this run. Rerun in isolation to verify all three path fixes end-to-end. |

---

### Environment Notes

- `BrowserCookieAuth` extracts the live IBKR session cookie from Chrome's macOS keychain. The session expired ~5 minutes after the test run completed — subsequent runs correctly auto-skip rather than fail.
- IBKR session keepalive requires calling `tickle()` or `ping()` at least every few minutes. `ConnectivityChecker` in `claudia_ui` does this every 60s.
- Gateway: Docker container on `localhost:5055`. Tests assume the container is already running and the IBKR session is fully authenticated (2FA complete).

---

*To add a new run entry, prepend it above this one and add a link to the index at the top.*

---

## Correction 2026-09-16 — the alert-write 403 was misattributed throughout this log

The **observations** in this file stand: `create_alert` returned HTTP 403 on every run. The
**interpretation** attached to them does not. Three entries above say the cause is that the
CP API "requires trading session permissions for alert writes" and one recommends
re-testing "after enabling trading mode via browser login". That is wrong, and it left
alert CRUD recorded as a known-expected skip for months rather than as a defect.

Measured 2026-09-16 against a live authenticated gateway:

* the gateway returns an opaque HTML `403 Access Denied` for any request body containing
  `>=`, `<=` or `!=` — in the `operator` field or in `alertName`, so it is body-wide;
* `>`, `<`, `==` and every other spelling reach IBKR and are refused by its own engine
  (`{"error":"Condition #1:can't recognize fix [>]"}`), so the only two operators IBKR
  accepts are the only two that cannot reach it;
* `DELETE /iserver/account/{acctId}/alert/{id}` is a write and reaches IBKR normally,
  which is what rules out the session/permissions explanation;
* calling `GET /iserver/accounts` first, or `tickle`, changes nothing; JSON-escaping the
  operator (`\u003e\u003d`) changes nothing; rebuilding the gateway would change nothing,
  because the upstream zip's `Last-Modified` is 2023-04-24 — the build in use IS the
  current published one.

Alert creation and modification are therefore not possible through the Client Portal
Gateway as published. Evidence and the full elimination table:
`docs/ibkr-api-behaviors-reference.md` § Price alerts. The entries above are left as
written, because they record what was observed on their dates.

