# Release-readiness audit — 2026-09-16

Whole-package assess / test / fix, run against `HEAD` before deciding whether the 215
commits since `v1.2.2` warrant a release tag. Plan:
`docs/plans/2026-09-16-release-readiness-audit.md` (gitignored).

**Status:** Phase 0 in progress.

---

## Phase 0 — Baseline

Measured against `2a228d7` on 2026-09-16. Nothing was fixed in this phase; the purpose is
ground truth before anyone forms an opinion. Environment: Python 3.11.16, lenient editable
install resolving to the source tree.

| # | Gate | Command | Result |
|---|---|---|---|
| 0.1 | Lint | `ruff check .` | **PASS** — All checks passed! |
| 0.2 | Format | `ruff format --check .` | **PASS** — 106 files already formatted |
| 0.3 | Types | `mypy` | **PASS** — no issues found in 106 source files |
| 0.4 | Unit | `pytest -m "not integration"` | **PASS** — 1257 passed, 93 deselected, 25.87 s |
| 0.5 | Security | `pytest -m security` | **PASS** — 194 passed, 1156 deselected, 4.10 s |
| 0.6 | Live gateway | `pytest tests/test_client_live.py -m integration` | **BLOCKED** — 61 skipped, gateway unauthenticated |
| 0.7 | Live web tools | `pytest tests/test_web_tools_live.py -m integration` | **PASS** — 11 passed, 25.81 s |
| 0.7b | Live scraper (Drive, dev-cache, crawl4ai, web_scraper) | `pytest tests/test_web_scraper_*_live.py tests/test_crawl4ai_live.py -m integration` | **PASS** — 8 passed |
| 0.8 | Live watchlist | `pytest tests/test_client_live.py -k watchlist -m integration` | **BLOCKED** — same cause |
| 0.9 | Order gates (manual) | Gate 1 + Gate 2 end to end | not yet run |
| 0.10 | Supply chain | `pip-audit` (CI-equivalent) | **PASS** — no known vulnerabilities, 1 correctly ignored |
| 0.11 | Live alerts | `pytest tests/test_alerts_live.py -m integration` | **BLOCKED** — 11 skipped, gateway unauthenticated |

Gates 0.1–0.4 were run in CI's order, because a red step hides every step after it
(run 34082479743).

### 0.6 / 0.8 / 0.11 — why they are blocked

The gateway **container** is healthy: `ibkr_core_gateway` up 40 hours, `127.0.0.1:5055`
bound, HTTP reachable. The **session** is not authenticated:

```
ping():        False
get_auth_status(): IBKRAuthError — IBKR session not authenticated (401)
```

`BrowserCookieAuth` found cookies (no "no localhost cookies found" warning was emitted), so
this is an expired session rather than a missing one — consistent with a 40-hour-old
container and no `tickle()` keepalive. Clearing it needs a fresh browser login at
`https://localhost:5055`; it is not a code defect and not a finding.

72 live assertions are gated behind this (61 client + 11 alerts), including the pending
`get_watchlists` verification (`docs/plans/2026-07-23-get-watchlists-empty-bug.md`) and any
live confirmation of `2a228d7`'s paginated-history fix.

### 0.10 — a near-miss worth recording

The first local `pip-audit` run reported **50 vulnerabilities across 6 packages**
(aiohttp, cryptography, h2, nltk, pip, tornado), and showed `PYSEC-2026-3740` — the one
entry in `security/pip-audit-ignores.txt` — with a fix version of `3.10.3`. That would have
made the ignore stale under the file's own rule ("a finding WITH a fixed release is never
ignored — bump the floor"), and its re-check date of 2026-10-13 meant nothing would have
caught it until then.

Both readings were wrong, and the checks that showed them were the wrong checks:

1. **The 50 findings are local venv staleness, not a repo defect.** CI audits a *fresh
   resolve* of `.[dev,server,scraper]` via `pip install --dry-run --report`, not an installed
   tree. Replicating CI exactly returns `No known vulnerabilities found, 1 ignored`.
2. **`PYSEC-2026-3740` still has no fixed release.** The `3.10.3` column came from the PyPI
   vulnerability service conflating it with the *other* nltk advisories. Under **OSV** — the
   service CI actually specifies — a fresh resolve picks nltk `3.10.3` and 3740 reports
   `fix_versions: []` on that very version. The ignore entry is accurate and correctly applied.

Control that made this decidable: re-running the identical command with the `--ignore-vuln`
removed, which surfaced exactly one finding (`nltk 3.10.3 / PYSEC-2026-3740`, no fix) and
proved the check was capable of failing.

**Not a finding.** Recorded because it is the plan's R1/R4 failure mode caught in the act,
on the first gate.

### Corrections made during Phase 0

- `firecrawl` is absent from the venv. Not a gap: the SDK is never imported — `FirecrawlClient`
  calls `https://api.firecrawl.dev/v1` over httpx directly. The import probe tested for
  something the package deliberately does not use.
- `test_toolkit_get_alerts` appeared to pass against an unauthenticated gateway. It did not —
  line 139 is in the skip list; the `InsecureRequestWarning` attributed to it came from the
  `live_toolkit` fixture's probe firing before the skip.

### Leads parked for Phase 1

Not findings. Each needs verification against the docs before it is called anything.

| Lead | For |
|---|---|
| `pyproject.toml` describes the `scraper` extra as "the scraper's **fallback rung**" — the fallback ladder was deleted 2026-07-28 | § 4.4 / § 4.6 |
| `.env` files still set `CRAWL4AI_API_KEY`; CLAUDE.md says the variable is now simply ignored | § 4.6 |
| `grep` finds 48 `"name":` and 46 `"capabilities"` in `claude_tools.py`; CLAUDE.md says 44 tools. Raw grep also counts nested schema properties — count properly | § 4.3 |
| `tests/security/` holds **10** test files and 194 collected tests; prior records describe "9 files, 138 tests" and "~10 s" (actual 4.10 s) | § 4.1 / § 4.6 |
| `docs/ibkr-api-behaviors-reference.md` is 11 lines, but CLAUDE.md cites it as the store of verified-not-assumed IBKR behaviours | § 4.6 |
| `docs/plans/INDEX.md` lists `2026-08-07-flex-audit-handoff.md` as live pending branch `audit/checks-that-cannot-fail`; that branch no longer exists | § 4.6 |
| 1,152 `def test_` but 1257 collected (parametrisation) — check what `docs/test-coverage.md` claims | § 4.6 |

---

## Phase 1 — Findings

### Domain: security and order-write gates (`SEC`)

10 findings. Every claim below was **re-verified by me independently** of the agent that
raised it; the agent's evidence is not taken on trust.

| ID | Sev | Claim |
|---|---|---|
| SEC-01 | **High** | The AST guard holding "only the five gated methods may build an order-write URL" sees only f-strings and literal `{}` templates, in function bodies. Concatenation, `%`-format, `str.join`, and module-level constants are invisible to it |
| SEC-02 | Medium | Three documents claim a gated method contacts no network before its gates; every one calls `_ensure_accounts_initialized()` → `GET /iserver/accounts` first, and that request goes out even when Gate 1 then denies |
| SEC-03 | Medium | Invariant 9 claims every path-interpolated identifier is validated; `_resolve_one_reply`, `mark_notification_read` and `update_delivery_option` interpolate without validation |
| SEC-04 | Medium | `pytest -m security` is documented as running all eleven invariants; it runs ten — invariant 9 has no `security`-marked test |
| SEC-05 | Medium | `README.md:397` states the pre-2026-09-11 Gate 1 rule ("every order-write attempt calls `require_touch_id()` fresh"), contradicting `README.md:390` seven lines above |
| SEC-06 | Low | `redact_error` claims to scrub `identifier: value` credential pairs; the JSON/quoted form (`"refresh_token": "…"`) is not scrubbed. No reachable leak demonstrated |
| SEC-07 | Low | `OrderWriteAuthorization` binds the body and order id but not the account id — an authorization for account A covers a byte-identical body sent to account B |
| SEC-08 | Low | Two more structural probes miss an ordinary alternative spelling (`from os import system`; a handler binding `c = self._client` first) |
| SEC-09 | Nit | "The default button is the abandon one" is true only on the `osascript` fallback; on the primary AppKit path no button is default |
| SEC-10 | Nit | `collapse_home` claims to cover every surface that shows a path "or a log"; the SSE bearer-token log line writes the absolute home path |

#### SEC-01 — independent verification

The guard's own reconstruction handles two AST node kinds only
(`tests/security/structural.py:45-57`), and walks function bodies only (`:73-85`). Driven
against the real checker with the real pattern:

```
DETECTED  f-string (the form used today)
MISSED    concatenation
MISSED    percent-format
MISSED    str.join
MISSED    module-level constant
```

The f-string row is the control: it proves the probe was wired up and capable of firing, so
the four misses are genuine blind spots rather than a broken harness. The consequence is that
a new gate-free order-write call site written in any of those four styles would pass
`pytest -m security` silently — which is the single thing this test exists to prevent.

Nothing in `SECURITY.md`, `docs/security-architecture.md`, or the 2026-09-13 audit records the
f-string-only limit, so this is drift, not a documented decision.

#### Counts resolved

`len(TOOL_DEFINITIONS) == 44`, `len(_ALL_TOOL_DEFS) == 46`, `ORDER_EXECUTION not in CAPABILITIES`.
CLAUDE.md's "44 tools" and `docs/mcp-server-reference.md`'s "46 tools" are both correct. The
Phase 0 lead of 48/46 from grep was a false lead exactly as R4 predicted — the grep counted
nested `inputSchema` properties.

#### Verified clean in this domain

Gate 1/Gate 2 have no bypass flag, cache or env-var read anywhere; every failure mode fails
closed; gates sit at the innermost call site (driven: with either gate raising, all four write
methods made 0 POSTs and 0 DELETEs). `OrderWriteAuthorization` is frozen, frame-local, minted in
exactly one place, and expires closed at 301 s; a changed quantity or a `place`→`modify` switch
is correctly not covered. One Touch ID per chain with Gate 2 unskipped was measured on a
three-reply chain (1 / 1 / 3). The declined-reply exception is the only contact-on-decline path.
AppleScript escaping holds against an injection canary that executed when unescaped. Credential
fields carry `repr=False` and a live `repr(Config(...))` leaked no canary.

R5 compliance: `git status --porcelain` unchanged across the agent's run.

---

### Domain: web scraper (`WEB`) — 9 findings

#### WEB-01 — **Critical**, reproduced independently

`ibkr_core_mcp/local_browser.py:388-413`. The Playwright layer-2 SSRF guard does not see HTTP
redirect hops. A public URL that 302s to a private address is fetched and its content returned
to the model. `fetch_page` and `crawl_site` are both affected; `search_site` (httpx) is not.

My own reproduction, with the direct-loopback control that must be refused:

```
=== CONTROL: direct loopback must be REFUSED ===
reply: Blocked: cannot fetch from localhost, link-local, or private/reserved addresses.
canary leaked: False

=== TEST: public URL that 302s to loopback ===
reply: # Fetched: https://httpbin.org/redirect-to?url=http://127.0.0.1:8901/ (25 B)
CANARY LEAKED: True

=== canary server access log ===
127.0.0.1 - - [16/Sep/2026 08:57:53] "GET / HTTP/1.1" 200 -
```

The access log is the decisive evidence: the private server itself recorded Chromium's
connection. The control proves layer 1 works and that the harness can show a refusal, so the
leak is the redirect specifically.

The claim it falsifies is `SECURITY.md:754` — "verified … against the Chromium/Playwright
network stack, which routes redirects and subresources through the same request-interception
path as the initial navigation". Subresources do (45 route events measured on an asset-heavy
page); redirects do not, because Playwright follows a 3xx internally after `route.continue_()`
and emits no second route event. Asserted as closed in six places including
`CHANGELOG.md:234` and the 2026-09-13 audit.

Root-cause fix, proven live by the auditing agent without editing the repo: follow the chain
explicitly inside `_reject_private_requests` via `route.fetch(url=url, max_redirects=0)`,
check `Location`'s host, abort if private, else loop bounded. Under that handler the canary
server's access log stayed **completely empty** and a public redirect still resolved. Two
things need live re-measurement before it ships: `route.fulfill()` leaves `page.url` at the
redirector, and every subresource then round-trips through `route.fetch`.

#### WEB-02 — **High**

`tests/test_local_browser.py:571-595` is the test that exists to pin WEB-01's property. Its
docstring promises "every request the page makes, not just the initial navigation URL"; it
asserts only that a handler was *registered* with a `**/*` glob, against a `_FakePage`. The
glob is registered and the redirect is still missed. 188 tests green while the property did
not hold — the mock was weaker than the dependency, exactly as `docs/web-scraper-reference.md`
§10 warns.

| ID | Sev | Claim |
|---|---|---|
| WEB-03 | Medium | `WebDocsStore._get_service` is a third reimplementation of the Drive OAuth helper and omits the `RefreshError` handling added to `gdrive_auth.py` on 2026-07-13 |
| WEB-04 | Medium | `firecrawl_search` archives to Drive, verbatim and unannotated, results it simultaneously marks "⚠ Not usable content" to the model |
| WEB-05 | Medium | `docs/web-scraper-reference.md:174` describes the deleted fallback layer as current |
| WEB-06 | Low | `pyproject.toml:63` and `:97` name the deleted fallback rung in the present tense |
| WEB-07 | Low | `tests/test_web_scraper_live.py`'s docstring documents a deleted method and tells the reader to export `ANTHROPIC_API_KEY` for the scraper |
| WEB-08 | Nit | `docs/web-scraper-reference.md:353` cites `_MAX_CONCURRENT_FALLBACKS`, which exists nowhere in the tree |
| WEB-09 | Low | `_handle_crawl_site` guards the Drive write but not the Drive read, so an OAuth failure surfaces as "unexpected error" |

### Domain: tool layer and MCP (`TOOL`) — 9 findings

| ID | Sev | Claim |
|---|---|---|
| TOOL-01 | **High** | `_modify_price_alert` reads IBKR's snake_case alert-detail response and writes camelCase keys beside the stale ones, never carrying `orderId` — a malformed create, not a modify |
| TOOL-02 | Low | The alert condition payload uses `conid`+`exchange`+`conditionType`; IBKR documents `conidex`, `logicBind`, `triggerMethod`. `conidex` appears nowhere in the codebase |
| TOOL-03 | Medium | `sync_flex_archive`'s description tells users to upload to `ibkr_flex_archive/`; the handler reads `account_data/`. No code path reads the named folder |
| TOOL-04 | Medium | `firecrawl_search`'s description promises "full page content as markdown"; the handler returns a 400-character snippet |
| TOOL-05 | Medium | `verify_flex_import` is described as "does not modify any data" while correctly declaring `DATABASE` and writing to `flex_import_log` |
| TOOL-06 | Medium | `mcp_server.py:167` inlines `get_accounts()` and reads only `"accountId"` — the package's single violation of CLAUDE.md's `_first_account_id()` rule |
| TOOL-07 | Low | The MCP server refuses to start without `ANTHROPIC_API_KEY`, which no module in the package reads; README's stated reason for the requirement is false |
| TOOL-08 | Low | Five files cite `…/alerts/create-or-modify-alert.md`, which returns `# Page Not Found` and is absent from `llms.txt` |
| TOOL-09 | Low | `get_pnl` declares `READ_ONLY` but opens a WebSocket and sends a subscribe/unsubscribe pair on a cold gateway |

### Domain: IBKR API surface (`API`) — 15 findings

#### API-01 — **Critical** (agent graded High; I raise it), verified independently

`ibkr_core_mcp/client.py:559-560`. Yesterday's pagination fix (`2a228d7`) repaired the loop
but not the **fast path**. `_chunk_days_for_bar` ends in `max(1, …)`, and for `1min`:

```
  bar    chunk_days x bars/day  = points   vs _MAX_POINTS=1000
  1min       1     x  1440.0    = 1440.0   OVERFLOW
  5min       1     x   288.0    =  288.0   ok
  1h        30     x    24.0    =  720.0   ok
  1d      1000     x     0.69   =  690.0   ok
```

`1min` is the only overflowing bar size — and the most-used intraday one. When
`total_days <= chunk_days` the method short-circuits to a single un-paginated
`get_market_history` call. Driven against a stub that truncates the way `2a228d7` measured
IBKR truncating (newest 1000, silently):

```
  period=1d  bar=1min  requests= 1  bars= 1000 /  1440 expected  =  69.4%
```

Nearly a third of a trading day's bars, missing, with no error and no warning. The commit's
own reasoning — "correctness no longer depends on the estimate at all" — is true *inside the
loop*; the fast path bypasses the loop, so on that branch correctness still depends on an
estimate that exceeds the cap. Its live verification used `5d/1min` and `30d/5min`, both of
which take the loop. `1d/1min` was never exercised.

Raised to Critical under this audit's own rubric: silently wrong financial data that a human
or model will compute indicators on.

| ID | Sev | Claim |
|---|---|---|
| API-02 | High | `_MAX_CHUNKS=120` returns a well-formed result covering less than asked, logging rather than failing |
| API-03 | High | The cited rate limit for `/iserver/marketdata/history` is wrong against the page it cites |
| API-09 | High | In `--stream` mode the server never subscribes to any alert's conid |
| API-04 | Medium | Three documents claim proactive token-bucket pacing |
| API-05 | Medium | Positions page size documented as 30; IBKR documents 100 |
| API-06 | Medium | The regression tests guarding `2a228d7` are timezone-dependent |
| API-07 | Medium | `create_alert`'s cited source URL is dead (same page as TOOL-08) |
| API-10 | Medium | `IBKR_AUTH_BROWSER` is honoured on one code path out of three |
| API-08, 11–15 | Low/Nit | Stale docstring chunk table; zero of 74 methods return a Pydantic model; wrong model citation; contradictory inline comment; deliberate double-call on a 1-req/5-s endpoint; unguarded response shape |

### Domain: documentation (`DOCA` 21, `DOCB` 19)

Headline items:

| ID | Sev | Claim |
|---|---|---|
| DOCB-01 | Critical* | `docs/README.md:45-47` still states both gates re-run for every chained reply — the exact wording CLAUDE.md corrected on 2026-09-14 |
| DOCA-01 | High | `SECURITY.md:261-264` prints the **pre-fix**, Unicode-permissive `_ORDER_ID_RE = r"^\d+$"` as the mitigation; the code has `[0-9]`, and this same file records the fix at line 912 |
| DOCA-02 | High | `docs/tools-reference.md` documents `search_contract`'s pre-2026-08-05 behaviour |
| DOCA-10 | Medium | README's tool table lists 43 of the 44 tools — `get_pa_periods` is missing |
| DOCA-11 | Medium | README's Backtesting example does not run as pasted |
| DOCA-18 | Low | Three documents say CI runs `pip-audit` over the "installed tree"; it audits a fresh resolve — the same distinction that produced Phase 0's near-miss |

*severity to be re-graded at triage.


### Domain: data layer, sandbox, quant (`DATA`) — 19 findings

#### DATA-02 — **Critical**, verified independently

`ibkr_core_mcp/backtest.py:634-635`. `run_backtest` annualises Sharpe and Sortino with
`periods=252` regardless of bar size, while `get_analytics` — on the same bars — uses
`periods_for_timeframe`. Measured:

```
periods_for_timeframe('5min') = 19656   ('1d') = 252
Sharpe periods=252   (run_backtest reports)  = 0.162
Sharpe periods=19656 (get_analytics reports) = 1.430
ratio 8.832   sqrt(19656/252) = 8.832
CONTROL daily: 0.161929 vs 0.161929 -> identical: True
```

The daily control agreeing to 1e-12 proves the 5-minute disagreement is a real divergence and
not a harness artefact. The wrong figure is then persisted via `save_backtest` and re-emitted
in the generated PineScript header, so it propagates beyond the call that produced it.

`docs/plans/2026-06-27-architecture-notes.md:122` records this exact defect class and its fix —
which landed for `full_report`/`get_analytics` and never for the backtest path. A half-applied
fix, which is the same shape as API-01.

#### DATA-01 — High, verified independently

`indicators.py:45-47` seeds Wilder smoothing with the first observation
(`ewm(adjust=False)`) rather than the SMA of the first 14 gains/losses. Measured against a
hand-written Wilder reference on a 250-bar series:

```
 bar      impl    Wilder     diff
   1    0.0000       n/a            <- a value where the indicator is undefined
  14   12.6173   29.9776   -17.36   <- oversold vs neutral: a different signal
  40   37.4124   42.4654    -5.05
 150   55.7967   55.7989    -0.00   <- converged
```

The divergence converges to zero by ~bar 150, so a long series is fine; a short one is not,
and 17 RSI points is the difference between two opposite trading signals. The docstring
promises "NaN only where genuinely undefined" and cites StockCharts' Wilder definition;
the function returns `0.0` at bar 1.

| ID | Sev | Claim |
|---|---|---|
| DATA-03/04/05 | High | (see full report) |
| DATA-06 … DATA-10 | Medium | |
| DATA-11 … DATA-18 | Low | |
| DATA-19 | Nit | |

---

## Phase 1 — totals

| Domain | Findings | Critical | High | Medium | Low | Nit |
|---|---:|---:|---:|---:|---:|---:|
| Security & orders | 10 | 0 | 1 | 4 | 3 | 2 |
| IBKR API surface | 15 | 1* | 3 | 5 | 5 | 1 |
| Tool layer & MCP | 9 | 0 | 1 | 4 | 4 | 0 |
| Web scraper | 9 | 1 | 1 | 3 | 3 | 1 |
| Data layer & quant | 19 | 1 | 4 | 5 | 8 | 1 |
| Docs — high-risk 5 | 21 | 0 | 2 | 10 | 7 | 2 |
| Docs — remaining 19 | 19 | 1* | 4 | 8 | 3 | 3 |
| **Total** | **102** | **4** | **16** | **39** | **33** | **10** |

*API-01 raised from High to Critical by me. DOCB-01's Critical is a documentation claim and is
re-graded at triage.

**Three Criticals are code defects and all three were reproduced by me, not taken on an
agent's word:** WEB-01 (live SSRF, canary in the private server's own access log), API-01
(69.4% of a trading day's 1-minute bars, silently), DATA-02 (Sharpe off by 8.8x on intraday
backtests).

All three were invisible to a fully green run of 1,257 unit tests, four CI gates, the security
suite, and the live scraper suite.

### The pattern

Across every domain, the code is stronger than the claims made about it are accurate. WEB-01,
API-01, SEC-01, DATA-02 and DOCA-01 are all the same shape: **a guarantee that is narrower in
reality than in writing**, with a test that cannot fail in the gap. Two of them (API-01,
DATA-02) are fixes that were applied to one branch of a defect class and not the other.

---

## Phase 2 — Triage, adjudicated by the owner 2026-09-16

| Question | Decision |
|---|---|
| DATA-01 RSI seeding | **Fix to canonical Wilder, and audit every other indicator the same way** — MACD, Bollinger, ATR, VWAP, OBV re-derived against authoritative definitions with hand-computed references. Precedent: the sortino migration, where pre-migration figures were accepted as not comparable |
| API-11 response typing | **In scope.** Thread Pydantic return types through all 74 client methods |
| TOOL-07 Anthropic key | **Investigate before touching.** Establish why the requirement exists, how it is used across this repo and consuming projects, and what the original logic was. No change until that is understood |
| Fix sequence | **Criticals first, then by severity** |

Nothing was placed out of scope. The two scope-growing decisions (a full indicator audit, and
typed returns across 74 methods) are recorded here because they, not the 102 findings, now set
the timeline.

---

## Phase 3 — Fixes

Sequence: WEB-01, API-01, DATA-02 (Criticals), then High, Medium, Low, Nit.
Each fix: failing test first → root-cause fix → four CI gates in CI's order → commit.

---

## Phase 3 — Fixes completed (session 1)

Branch `audit/release-readiness-2026-09-16`. Every claim below was verified by me
independently of the agent that raised it, and every fix was mutation-tested.

| # | Finding | Severity | Verification |
|---|---|---|---|
| WEB-01 | Playwright SSRF guard did not see redirect hops | **Critical** | Canary server's own access log recorded Chromium connecting to loopback; fixed guard leaves it empty |
| API-01 | `1d/1min` returned 69.4% of a trading day's bars | **Critical** | Driven against an IBKR-accurate truncating stub; all 20 period/bar combinations now ≥100% span, 0 gaps |
| DATA-02 | `run_backtest` annualised intraday Sharpe 8.8x wrong | **Critical** | Daily control agrees to 1e-12, proving the divergence real |
| — | Three endpoints returned `[]` for data that arrived | **Critical** | Live: 10 algos, 2 positions, **11 transactions** recovered |
| — | `place_order` discarded IBKR's documented rejection object | High | `place-order.md` publishes a third, object-shaped response |
| SEC-01 | Order-write AST guard saw only f-strings | High | 5 of 6 URL idioms measured invisible; owner set unchanged after widening |
| — | Live suite asserted types, not data (38 tests) | **Systemic** | Reverting fixes now fails the live tests; previously passed |
| API-06 | Pagination stub timezone-skewed | Medium | 4.0h skew reproduced; zero on a UTC runner, so CI could never see it |
| — | Price alerts non-functional; cause misattributed for months | High | See below |

### Price alerts — reviewed and measured end to end

Alerts had never been exercised. Documentation reviewed first, then tested methodically
against the live gateway at the owner's direction.

**Finding: alert creation and modification are impossible through the Client Portal
Gateway as published.** The gateway rejects any body containing `>=` or `<=` with an opaque
HTML 403 before it reaches IBKR; those are the only two operators IBKR's alert engine
accepts (`>`, `<`, `==` arrive and return `can't recognize fix`). Both alert tools exposed
an enum of exactly the two blocked operators.

Ruled out, each by measurement: account permissions and brokerage session (`DELETE` is a
write and works); the documented `GET /iserver/accounts` prerequisite; `tickle`; JSON
unicode escaping of the operator; and a stale gateway image — the upstream zip's
`Last-Modified` is 2023-04-24, so the build in use IS the current published one.

**Documentation corrected:** `create_alert` cited a dead page. The real one sits under
`api-reference/trading/trading-alerts/` and is **absent from `llms.txt`** — the case
CLAUDE.md names, where the index's silence proves nothing and `firecrawl_search` settles
it. It also confirmed `orderId` as the create-vs-modify discriminator, which the archived
capture could not.

**Honesty fix, verified live against a real 403:** the tools now name the real cause,
explicitly rule out the wrong one, and cite the evidence — instead of
"IBKR gateway returned an error (HTTP 403)". The misattribution in
`tests/test_client_live.py`, `tests/test_alerts_live.py` and `docs/audits/live-test-log.md`
is corrected; the dated log's observations are left as written, with a correction appended,
because they record what was seen on their dates.

### The systemic pattern

Every Critical in this audit was one of two shapes:

1. **A control that could not fail.** The SSRF test asserted a handler was *registered*;
   the order-write probe's guard-on-guard used only f-strings; 38 live tests asserted
   `isinstance(x, list)` where `[]` is a list.
2. **A fix applied to one branch of a defect class, never swept.** Pagination (loop fixed,
   fast path not); annualisation (`full_report` fixed, backtest not); the object-wrapper
   silent empty (fixed three times, three more live).

Both now have permanent guards: `tests/test_assertion_strength.py` and
`test_no_new_endpoint_silently_discards_an_object_response`. Both guards are heuristics
over the shapes that have actually cost this project, not proofs.

### Release readiness — current view

**Not ready.** 11 of 102 findings closed. The remaining queue is 16 High and below, plus
two owner-approved scope additions (a full indicator audit; Pydantic return types across
74 client methods). No release should carry the alert tools without the honesty fix that
landed here, and the `get_watchlists` note pending since 2026-08-11 is now closed by a live
run.

### Open: an uncaptured intermittent failure in the live web-tools suite

One run of `pytest tests/test_web_tools_live.py -m integration` reported `1 failed, 11
passed`; four further runs the same day were clean (12 passed each). The failing test's
identity was not captured, so it is recorded as unknown rather than guessed at.

The suite reaches third-party hosts (httpbin.org, docs.crawl4ai.com, Firecrawl), so a
transient network or rate-limit fault is the likely cause — but "likely" is not evidence.
Note the new redirect guard cannot fail this way: if the redirector is slow or unreachable
the canary server is simply never contacted, `hits` stays empty and the test passes, and if
the redirector stops issuing its 302 the test skips loudly. Watch for a recurrence and
capture `-rf` output when it happens.
