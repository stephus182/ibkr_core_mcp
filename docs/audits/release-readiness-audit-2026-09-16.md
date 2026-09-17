# Release-readiness audit — 2026-09-16

Whole-package assess / test / fix, run against `HEAD` before deciding whether the 215
commits since `v1.2.2` warrant a release tag. Plan:
`docs/plans/2026-09-16-release-readiness-audit.md` (gitignored).

**Status:** Phase 3 (fixes) — in progress across nine sessions. **Not ready to tag.**
The register below is the current state; everything after it is chronological record.

---

## Register — current state (rebuilt 2026-09-16, session 9)

Rebuilt by extracting every finding ID from this report and reconciling it against the
Phase 1 domain totals, because the previous statement of the register was a paragraph in
the middle of the document and no longer matched it. **120 findings**, and the domain
counts reconcile exactly (13 + 9 + 12 + 21 + 25 + 21 + 19).

| Domain | Total | Closed | Open, with a claim | No claim recorded | Written off |
|---|---:|---:|---:|---:|---:|
| `SEC` | 13 | 7 | 6 | — | — |
| `WEB` | 9 | 2 | 7 | — | — |
| `TOOL` | 12 | 7 | 5 | — | — |
| `API` | 21 | 13 | 7 (+1 partial) | — | — |
| `DATA` | 25 | 8 | — | — | **17** |
| `DOCA` | 21 | 6 | — | — | **15** |
| `DOCB` | 19 | 1 | — | — | **18** |
| `DOCB-R` | 6 | 6 | — | — | — |
| `DOCA-R` | 3 | 3 | — | — | — |
| `DATA-R` | 5 | 5 | — | — | — |
| `API-R` | 1 | 1 | — | — | — |
| **Total** | **135** | **59** | **25** (+1 partial) | **0** | **50** |

`59 + 25 + 1 + 0 + 50 = 135`. **There are no unrecorded findings left.** All three blocks
(`DOCB` 18, `DOCA` 15, `DATA-03…19` 17) were re-derived in session 9 and produced 15 fresh
findings — 5 High, 6 Medium, 4 Low — every one closed. Severity order finally has something to
range over. "Written off" is its own column and not folded into either
"closed" or "no claim recorded", because it is neither: those 18 slots were never readable and
never will be, and the six `DOCB-R` findings that replace them are a **fresh** audit of the
same documents, not a recovery of what they said.

**`DOCB`, `DOCA` and `DATA-03…19` re-derived, session 9.** The 18 unwritten `DOCB` slots are **written off, not
closed** — their claims are unrecoverable. In their place the same 19 documents were
re-audited from scratch and produced `DOCB-R1…R6`, all six raised and closed (one High, three
Medium, two Low), plus four untested public behaviours in `indicators.py` and `models.py` that
the check found on the way. See *Phase 3 — `DOCB` re-derived*. `DATA-03…19` and the 15 unnamed
`DOCA` slots are the remaining 32 and are owed the same treatment.

### The number that changed, and why

This report previously read **"120 findings, 51 closed, 69 open"**. That 51 counted *fixes
shipped* — session 1's table alone carries four rows whose ID column is `—` (three endpoints
returning `[]` for data that arrived; `place_order` discarding IBKR's rejection object; the
live suite's 38 type-only assertions; price alerts non-functional). The 44 above counts
*register IDs resolved*. Both are true and they measure different things; the second is the
one a tag decision needs, so it is the one stated here from now on.

### ~~50 findings have no claim recorded — this is the blocker~~ — RESOLVED, session 9

**Only 73 of the 120 IDs appear anywhere in this 1,700-line report. 47 never appear at all**,
and six more appear only as the endpoints of a range (`DATA-06 … DATA-10 | Medium |`) whose
claim cell is empty. Phase 1 ran through agents; the domain *totals* were carried into this
report and the per-finding text was not.

| Block | IDs | What exists | State |
|---|---|---|---|
| `DATA-03…05` | 3 (**High**) | the cell reads `(see full report)` — there is no full report | re-derived session 9 → `DATA-R1…R5` |
| `DATA-06…19` | 14 | table cells are empty | re-derived session 9 → `DATA-R1…R5` |
| `DOCA-03…09, 12…17, 20, 21` | 15 | never written | re-derived session 9 → `DOCA-R1…R3`, `API-R1` |
| `DOCB-02…19` | 18 (4 **High**) | never written | re-derived session 9 → `DOCB-R1…R6` |

**A finding with no claim cannot be closed, dismissed or ranked.** Under the owner's
fix-everything-then-tag bar it is not open, it is unreadable — so "Criticals first, then by
severity" cannot terminate while 50 entries have no severity that can be checked and no claim
that can be verified. The precedent for answering this is already in this report twice: when
`DATA-03/04/05` were found to be lost, the domain was **re-audited directly** rather than
guessed at, and that sweep produced `DATA-25` (a real High). The same is owed to the other
three blocks.

### Open findings that do have a claim (25, none Critical)

| ID | Sev | Claim, in brief |
|---|---|---|
| `TOOL-01` | **High** | Correct fix shipped; cannot be exercised while IBKR's gateway refuses every alert operator. Documented, deliberately not closed |
| `WEB-03` | Medium | `WebDocsStore._get_service` is a third OAuth reimplementation, without `gdrive_auth.py`'s `RefreshError` handling |
| `WEB-04` | Medium | `firecrawl_search` archives to Drive, verbatim, results it simultaneously marks "⚠ Not usable content" |
| `WEB-05` | Medium | `docs/web-scraper-reference.md:174` describes the deleted fallback layer as current |
| `WEB-09` | Low | `_handle_crawl_site` guards the Drive write but not the Drive read |
| `WEB-06` | Low | `pyproject.toml:63` and `:97` name the deleted fallback rung in the present tense |
| `WEB-07` | Low | A live-test docstring documents a deleted method and tells the reader to export `ANTHROPIC_API_KEY` |
| `WEB-08` | Nit | `docs/web-scraper-reference.md:353` cites `_MAX_CONCURRENT_FALLBACKS`, which exists nowhere — re-confirmed session 9 |
| `SEC-02` | Medium | Three documents claim a gated method contacts no network before its gates; every one calls `_ensure_accounts_initialized()` first |
| `SEC-06` | Low | `redact_error` claims to scrub `identifier: value` pairs; the JSON/quoted form is not scrubbed. No reachable leak shown |
| `SEC-07` | Low | `OrderWriteAuthorization` binds body and order id but not account id |
| `SEC-08` | Low | Two more structural probes miss an ordinary alternative spelling |
| `SEC-09` | Nit | "The default button is the abandon one" holds only on the `osascript` fallback |
| `SEC-10` | Nit | `collapse_home` claims every surface; the SSE bearer-token log line writes the absolute home path |
| `TOOL-03` | Medium | `sync_flex_archive` tells users to upload to `ibkr_flex_archive/`; the handler reads `account_data/` |
| `TOOL-04` | Medium | `firecrawl_search` promises "full page content as markdown"; the handler returns 400 characters |
| `TOOL-05` | Medium | `verify_flex_import` is described as "does not modify any data" while writing to `flex_import_log` |
| `TOOL-07` | Low | MCP server refuses to start without `ANTHROPIC_API_KEY`, which no module reads. **Investigate before touching** (owner) |
| `API-05` | Medium | Positions page size documented as 30; IBKR documents 100. Confirmed from docs, indeterminate live |
| `API-10` | Medium | `IBKR_AUTH_BROWSER` is honoured on one code path out of three |
| `API-17` | Medium | Raised by the API-05 investigation; no closure recorded |
| `API-08` | Low | Stale docstring chunk table |
| `API-12` | Low | Wrong model citation |
| `API-13` | Low | Contradictory inline comment |
| `API-15` | Nit | Unguarded response shape |
| `API-11` | *scope* | **Partial** — 6 of 74 client methods return a Pydantic model; the other 68 are open |

`API-08` and `API-12/13/15` have no ID-tagged row of their own; their claims are recovered by
position from the Phase 1 combined row (`API-08, 11–15`) and are recorded here so they stop
depending on that reading.

### What has to happen before a tag is even decidable

1. ~~Re-derive `DOCB`, `DOCA` and `DATA-03…19`~~ — **all three done, session 9**, yielding
   `DOCB-R1…R6`, `DOCA-R1…R3`, `DATA-R1…R5` and `API-R1`, all closed. The register now has a
   terminating condition.
2. Then the 25 readable open findings, in severity order — all Medium and below except
   `TOOL-01`, which is blocked upstream and cannot be closed here.
3. `API-11`'s remaining 68 methods (owner-approved scope addition).

Two things need the owner: a fresh Chrome login at `https://localhost:5055` for any live
work, and explicit permission for `API-20`'s live check, which writes to the owner's data and
has no unmark method.

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

The indicator sweep of Phase 3 session 2 added 5 findings to the Data layer & quant row
(DATA-20 … DATA-24: 2 High, 1 Medium, 1 Low, 1 Nit), taking the register to **107**. They
are listed there rather than here because they were raised by a fix, not by Phase 1.

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

## Phase 3 — Fixes completed (session 2): the indicator audit

DATA-01 was triaged as "fix to canonical Wilder, **and audit every other indicator the
same way** — re-derived against authoritative definitions with hand-computed references".
All 14 were re-derived. Four were wrong; three had never diverged and one was a variant
that was simply unnamed.

### Method

The point of the exercise was to assert against something outside this repository, so no
formula was judged by inspection. For each indicator:

1. The definition was retrieved from StockCharts ChartSchool via Firecrawl (full markdown,
   HTTP 200 recorded for every page), and cross-checked against the TradingView Pine Script
   v6 reference, which publishes *equivalent Pine source* for its built-ins.
2. Where ChartSchool publishes a downloadable worked example, the spreadsheet itself was
   downloaded and its columns read — `cs-rsi.xls`, `cs-atr.xls`, `cs-bbands.xls`, all three
   authored by StockCharts staff.
3. **A hand-written canonical implementation was run against the published columns first.**
   If it could not reproduce them, the misunderstanding was mine and not the code's. It
   reproduced all three to 5e-5 or better — within those spreadsheets' own rounding.
4. A deliberately-broken control was run in the same batch: canonical Wilder at `period=13`
   against the published `period=14` column diverges by 1.4241, versus 4.79e-05 for the
   correct one. The check can fail.
5. Only then was the shipped implementation measured.

### What the two authorities settled — including one finding I nearly got wrong

TradingView's prose describes `ta.ema` and `ta.rma` almost identically ("exponentially
weighted moving average with alpha = ..."), which reads as though both are plain
recursions and would have made our `ema` look wrong too. Its published equivalent source
says otherwise, and the contrast is the entire finding:

```
pine_ema: sum := na(sum[1]) ? src                 : alpha*src + (1-alpha)*sum[1]
pine_rma: sum := na(sum[1]) ? ta.sma(src, length) : alpha*src + (1-alpha)*sum[1]
```

`ema` matches `pine_ema` exactly and is correct; `rsi`/`atr` used that same seed where
Wilder's requires the SMA. Had I stopped at the prose I would have "fixed" EMA and MACD —
changing every MACD backtest in the project — for no reason. A test now pins the EMA seed
so that wrong fix cannot be applied later, and mutation testing confirms it catches it.

### Findings

| ID | Indicator | Severity | Divergence vs the authority's own worked example |
|---|---|---|---|
| DATA-01 | `rsi` | **High** | up to **19.78 points**. Bar 15: 50.75 (neutral) vs published 70.53 (overbought) — opposite signals |
| DATA-20 | `atr` | **High** | up to **22.2%** relative; also emitted a value on bar 1, where ATR is undefined |
| DATA-21 | `bollinger_bands` | **High** | band width **2.60%** too wide — exactly `sqrt(20/19)-1`, which identifies the cause as `ddof` and nothing else |
| DATA-22 | `vwap` | Medium | accumulated over the whole frame, never resetting per session |
| DATA-23 | `keltner_channels` | Low | ATR length tied to the EMA length; the documented (20, 2.0, 10) default was inexpressible |
| DATA-24 | `stochastic` | Nit | correct, but the variant (Fast) was unnamed — it will differ from packages defaulting to Slow |

`ema`, `macd`, `obv`, `williams_r`, `sma`, `volume_sma`, `volume_ratio`: verified
unchanged. `true_range` was extracted as a public function so `atr` cannot drift from it.

### The same systemic pattern, a third time

**Not one existing test failed** when RSI moved by 19.78 points, ATR by 22% and every
Bollinger band by 2.6%. `tests/test_indicators.py` asserted shapes and bounds only:
`test_atr_positive`, `test_vwap_positive`, `bb_upper >= bb_mid` (true for any non-negative
deviation, hence true for either `ddof`), and `test_macd_histogram_is_diff`, which asserts
the histogram equals its own definition and so cannot fail at all. Thirteen of the
seventeen indicator tests could not detect a wrong formula.

This is the third instance of the pattern already recorded in this audit — a control that
cannot fail — after the live suite's 38 type-only assertions and the order-write AST guard
that saw only f-strings.

The guard added here is a different kind, and deliberately so: a test that pins computed
values to an outside reference. `tests/test_indicators_worked_examples.py` holds the three
published columns verbatim with their provenance, and
`scripts/audit/indicator_reference_divergence.py` reproduces the before/after table on
demand. Eight mutants were run against the new tests — including both directions of the
VWAP branch and the plausible-but-wrong EMA "fix" — and all eight were caught.

### Scope note

Institutional VWAP variants (Bloomberg's calculation, close-excluded forms) were raised and
ruled out of scope by the owner. `vwap` implements the single-session definition with a
configurable `anchor`.

---

## Phase 3 — Fixes completed (session 3): rate limiting

Starting from API-03, a one-line claim that a cited limit was wrong. Verifying it pulled in
two neighbouring findings and produced a new one that is worse than all three.

### API-03 — confirmed, with a root cause

The docstring said `/iserver/marketdata/history GET 5 concurrent requests`. The page it cited
says `10 req/sec or 50 req/min`. Fetched with the `.md` variant and a deliberately-fabricated
control URL in the same batch (`…/pacing-limitations-xyzzy-not-real.md` → 355 B `# Page Not
Found` against 3,017 B of real content, so the check can fail), then **all 26 rows were diffed
programmatically**: 25 agreed, 1 did not. The 25 matches are what make the 1 mismatch
trustworthy.

Root cause, from this repo's own archived evidence: the **old** cpapi-v1 page
(`docs/audits/audit-evidence/scrapes/cpapi-v1.md:1035`) really did say "5 concurrent requests".
IBKR changed the value at the 2026-08 documentation move. The 2026-08-11 repointing pass
updated the citation URL without re-reading the page behind it — leaving a stale value with a
*correct-looking source beside it*, which is harder to catch than an uncited claim.

### The new finding — the reason this stopped being a documentation fix

The corrected limit introduced a rate we were already exceeding. Measured live, bounded to 4
requests so the measurement could not itself provoke a ban:

```
observed rate      : 284.3 requests/min
official limit     :  50 requests/min   -> EXCEEDS by 5.7x
min gap            : 0.113 s
120 chunks (the _MAX_CHUNKS guard) would complete in 25.3 s
```

IBKR's published consequence is HTTP 429 and a **fifteen-minute penalty box on the IP,
applying to every endpoint** — so one wide history request denies service to orders, positions
and tickle alike. The reactive retry budget against that is 1 + 2 + 4 = 7 seconds.
`rate_limiter.py` was named for pacing, and API-04 recorded that three documents described it
as doing token-bucket pacing. It did not. **Owner decision: implement the real per-endpoint
pacer** rather than pace only pagination or correct the documents.

### What implementing it exposed

Turning pacing on made two latent problems measurable immediately.

**The unit suite went from 33 s to 76 s, and the cause was diagnostic rather than noise.**
Every `test_get_live_orders_*` took exactly 5.00 s — `/iserver/account/orders` is 1 req/5 secs
and the process-wide pacer was correctly serialising them. That is API-14 ("deliberate
double-call on a 1-req/5-s endpoint", graded Low) showing its real cost for the first time.

**A bug in my own wiring.** The path handed to the pacer included the query string, so
`/iserver/account/orders?force=true` did not match the table entry and fell through to the
laxer global default — the warmup pair escaped the very limit the pacer existed to enforce.
Caught by writing the test before assuming the wiring was right, and now pinned.

### API-14, re-graded and fixed at the root

The warmup is real: a fresh brokerage session's first read returns an empty array. But it is a
**per-session** need that was being paid **per call**, and `get_trades` already handled the
identical warmup on `/iserver/account/trades` by reading first and retrying on empty —
`get_live_orders` was the outlier, not the pattern.

Settled by measurement, not by reading the code. On a warm session, three consecutive plain
reads with no `force=true` ahead of them each returned the open order (conid 265598, orderId
1986940574):

```
plain read #1: 0.10s  n=1  ids=[1986940574]
plain read #2: 4.97s  n=1  ids=[1986940574]   <- the 5 s is our own pacing
plain read #3: 5.02s  n=1  ids=[1986940574]
```

| `get_live_orders()` | before | after |
|---|---|---|
| first call | 5.17 s | **0.35 s** |
| called twice back to back | 10.07 s | **~5.0 s** |

The residual 5 s is the published limit itself and no implementation can go under it. What
changed is that we no longer spend two slots to answer one question.

### Findings

| ID | Sev | Outcome |
|---|---|---|
| API-03 | **High** | Confirmed and fixed; root cause traced to the 2026-08-11 repointing pass |
| API-04 | Medium | Closed — the pacing three documents described now exists |
| API-14 | Low → **re-graded High** | Fixed at the root; 15x faster first call and half the traffic on a rate-limited endpoint |
| API-16 | **High**, new | Pagination burst at 5.7x the published limit, risking a 15-minute IP-wide ban |

### Verification

Seven mutants run; **one survived and that was the valuable one**. "Window never expires"
passed the whole file, because with a 1-request limit `history[0] + window - now` is already
non-positive at the boundary — so a fixed window and a sliding one are indistinguishable there.
The real consequence appears only once a full budget is spent, the window passes, and a second
full budget is spent inside the new one: without expiry the limit silently stops applying and
the deque grows without bound. Two tests were added for exactly that and the mutant is now
caught. A first attempt at the leak test asserted the wrong bound and failed against correct
code — calls 2 s apart still sit inside history's 60-second window, where 30 of them
legitimately coexist.

Live: 58 passed / 14 skipped across `test_client_live.py` and `test_alerts_live.py`, matching
the pre-change baseline exactly. The `/pa/transactions` pacing warning fired during the run and
the test passed — the `_MAX_PACING_WAIT` escape hatch working under real conditions rather than
in theory.

---

### Release readiness — current view

> **Superseded by the Register at the top of this report (session 9).** The paragraph below
> was the register for five sessions and no longer matches the document: it omits `SEC-13`,
> `WEB-02`'s closure, and it states 51 closed, which counted fixes shipped rather than
> register IDs resolved. Kept because it is what was believed at the time.

**Not ready.** Two sweeps have raised 6 findings beyond the 102 of Phase 1 (DATA-20 …
DATA-24 from the indicator audit, API-16 from the rate-limit work), so the register stands at
**120 findings, 51 closed, 69 open** (TOOL-01 investigated and documented rather than closed — it cannot be exercised while the upstream operator block stands) (DATA-25 raised and closed by this sweep; the original DATA-03/04/05 detail was lost with the Phase 1 agent output and could not be recovered). API-18, API-19 and TOOL-10/11/12 were raised and closed by the API-11 work; API-20 and API-21 were raised by the SEC-03/04 investigation and are now **closed**, along with SEC-03, SEC-04 and SEC-12; SEC-11 is **closed** — `_REPLY_ID_RE` was checked against 24 reply IDs IBKR really sent, recovered from claudia_ui's decision store; TOOL-02, TOOL-08, API-07 and the new DOCA-19 are **closed** by the alert-body pass; **API-11 itself is partly done** — six of 74 methods return models, the other 68 remain open. The
sweep itself is complete: 14 indicators re-derived, 6 findings, all 6 fixed and pinned.

Of the 16 High findings in the Phase 1 totals, DATA-01 closes here and SEC-01 closed in
session 1, leaving 14; DATA-20 and DATA-21 were raised at High and closed in the same
session. The rest of the queue is Medium and below, plus one owner-approved scope addition
still open (Pydantic return types across 74 client methods) and TOOL-07, which is to be
investigated before anything is touched. No release should carry the alert tools without the honesty fix that
landed here, and the `get_watchlists` note pending since 2026-08-11 is now closed by a live
run.

## Phase 3 — API-02: a short answer announced only to a log file

`_MAX_CHUNKS = 120` is a runaway guard. Past it, `get_market_history_paginated` returned a
well-formed result covering less than was asked and said so only via `log.warning` — which
reaches no caller, no model and no cache.

### A correction to my own first estimate

The first pass modelled chunk demand at 1,440 bars per calendar day, i.e. a continuously
traded instrument, and produced a table saying `90d/1min` needs 130 chunks and `1y/5min`
returns 33%. **Measured live, `90d/1min` finished in 62 chunks at 100.2% coverage and
correctly raised no warning.** IBKR's step table caps `1min`/`5min` requests at a one-day
period, so for RTH equity data a chunk covers one *trading* day and the guard bites at
roughly 120 trading days (~5.5 calendar months), not 90 calendar days. The stub-derived
percentages were pessimistic for stocks; they remain right for a 24-hour instrument, where
a chunk covers one calendar day.

The finding survives the correction — it just bites later than first stated.

### Live evidence

Both runs on conid 265598 (AAPL), `outside_rth=False`, 2026-09-16:

| request | chunks | bars | covered | warning |
|---|---:|---:|---|---|
| `90d`/`1min` | 62 of 120 | 24,097 | 90.2 of 90 days = **100.2%** | none — correct |
| `1y`/`5min` | **120 of 120** | 9,344 | 174 of 365 days = **47.7%** | fires, naming 2026-03-26 |

The control matters as much as the finding: a guard that warned on both would be useless.

Both runs measured **29.3–29.9 requests/min** against the published 50/min ceiling, i.e.
network-bound rather than pacer-bound — proactive pacing costs nothing on this endpoint in
practice.

### The half that mattered

The silent short answer is bad; persisting it is worse. `fetch_market_data` saved the result
to the **Drive cache**, which is shared across machines and keyed by
(symbol, timeframe, period, end) — so 47.7% of a year stored under `1y` answers every later
request for a year, on every machine, reporting a confident "Cache HIT". This repo has
already paid for exactly that shape: the 2026-08-05 `startTime` incident needed a cache
purge because "a code fix is not sufficient".

So a flagged result is returned but **not cached**, with the reason stated to the model and
actionable guidance (shorter period, or larger bar). Two options were rejected: a cache-HIT
heuristic comparing stored span against requested period cannot distinguish truncation from
a recently-listed instrument, and recording coverage in the Drive manifest would change a
cross-machine schema out of proportion to the finding.

### Verification

Five mutants, all caught — including both "flag every response" and "never cache anything",
the two mutations that a one-sided test suite would miss. The first attempt at the
"never flag truncation" mutant produced a syntax error rather than a behaviour change and
was re-run cleanly before being counted.

---

## Phase 3 — the gateway-dependent sweep (before releasing the gateway)

Everything below needed a live, authenticated gateway. Run as one batch so the session
could be released afterwards.

### API-09 — the stream fix, verified against the real WebSocket

The fix landed against a *fake* WebSocket. Driven against the live gateway with one local
SQLite alert stored (AAPL 265598, an inert `below 1.00`), and then with the pre-fix
arrangement restored, in the same session:

| arrangement | subscriptions sent to the live gateway |
|---|---|
| **with the fix** | `smd+265598` |
| **pre-fix** | **NONE** — the deadlock reproduces live |

That is the strongest form of the check: the fix is verified and the verification is proven
able to fail, both against real IBKR infrastructure rather than a double.

### TOOL-06 — real, but it could never have shown here

`ibkr://positions/current` inlined `get_accounts()[0]["accountId"]`, the package's single
violation of CLAUDE.md's `_first_account_id()` rule. **Live: this account returns BOTH
`accountId` and `id`, with the same value** (`UXXXX699`), so nothing was broken on this
machine — which is exactly why it survived. A row carrying only `id` fell into the "no
account could be resolved" branch and read no positions, reporting a resolution failure for
an account that resolves fine everywhere else in the package. Now uses the helper, and
carries out the reason the helper gave rather than a generic string.

### API-05 — confirmed from documentation, indeterminate live

`get_positions`' docstring said "page 0 = first 30". IBKR's cited page says 100, twice.
Nothing in the package chunked by 30, so it was a docstring claim only.

Live could not settle it: this gateway build returns **no `pageSize` field at all** (every
row `None`, measured 2026-09-16) and the account holds 2 positions, so the boundary is not
observable. Recorded as documentation-confirmed rather than measured.

### API-17 — new, raised by the above

**Every caller reads page 0 and stops.** `ClaudeToolkit._get_positions` and the
`ibkr://positions/current` resource both take the default page, so an account with more than
100 positions is reported with its first 100 and no indication there are more — the same
silently-incomplete shape as API-02. Not reachable on a 2-position account, so it is recorded
rather than fixed blind; the docstring now says so.

### TOOL-09 — reviewed, declaration left unchanged

`get_pnl` declares `{READ_ONLY, LOCAL_IO}` while `_prime_pnl_subscription` opens a
WebSocket. Judged against what the vocabulary actually means rather than on the word
"WebSocket":

- `NETWORK` is reserved for **third-party** services — only `sync_flex_trades` and
  `firecrawl_search` hold it, while all 24 `READ_ONLY` tools already talk to the local
  gateway over HTTP. So this is not a `NETWORK` omission.
- The touch is **conditional** (only when a cold gateway returns an empty `upnl`),
  **net-zero** (connect → subscribe → unsubscribe → disconnect leaves the gateway as it
  was), and **best-effort** (failure logged, never raised).
- Removing it would restore a live-verified bug: empty P&L on a fresh session (2026-07-17).

Expanding a frozen security vocabulary for a transient no-op is disproportionate. The
reasoning is now recorded **at the declaration site** so the next audit does not re-raise it.

### Live suite after all of the above

`pytest -m integration`: **85 passed, 14 skipped, 0 failed** (99 collected). The web-scraper
flake did not recur.

---

## Phase 3 — TOOL-01: unblocked by a real alert, then fixed and live-tested

### A correction to my own claim, first

Mid-investigation I wrote that "it's not just `orderId`, the entire body is the wrong
shape". That was a lead stated as a fact, from eyeballing two documentation pages. I also
said the detail page's field descriptions "use camelCase" — that is **one** field out of 35
(`alertName`, where the example says `alert_name`), i.e. a typo in IBKR's page, and I
generalised from it. Counted properly:

| | count | cross-case |
|---|---:|---|
| detail response, documented example keys | 34 | **0** camelCase |
| detail page, field descriptions | 35 | 1 camelCase (`alertName`) — a doc typo |
| create/modify request fields | 19 | **0** snake_case |
| **names present in both** | **3** | `conditions`, `conidex`, `tif` |

The defensible statement is "3 of the 19 request field names appear in the detail
response", not the hand-wave.

### What is established

`_modify_price_alert` posts the GET-detail response back to the create/modify endpoint with
three camelCase keys written on top of it. Per IBKR's documentation the two endpoints do not
share a vocabulary, and `orderId` is not among the three shared names. `orderId` is what
decides the call's meaning — "omitted or 0 creates, an existing alert id modifies that
alert" — and the detail response supplies `order_id`. On the documented shapes this performs
a **create**, leaving the original alert in place and adding a second.

Sources, both fetched 2026-09-16 with a fabricated control in the same batch:
`…/v1/endpoints/alerts/get-details-of-a-specific-alert.md` and
`…/api-reference/trading/trading-alerts/create-alert.md`. (The `v1/endpoints/alerts/`
create page returns "# Page Not Found" — that is TOOL-08/API-07, already closed.)

### What is NOT established, and why it stays open

- **What the live gateway actually returns.** This container is the 2023-04-24 build; the
  documentation is current. Only the doc's example has been read, never a real response.
- **Whether IBKR rejects or tolerates the present body.** Untested either way.

It cannot be tested. The gateway 403s any alert write whose body contains `>=` or `<=` —
the only operators IBKR's alert engine accepts — and the account holds no alerts created
elsewhere, so `get_alert` itself cannot be observed. A translator written from documentation
alone, for a write path that cannot be run, would be an untested rewrite of exactly the kind
of code this audit keeps finding defects in. **Owner-visible decision: record, annotate the
handler, do not fix blind.** It should be fixed together with the upstream operator block and
verified against a real alert.

**UNBLOCKED 2026-09-16.** The owner created a real alert on IBKR Mobile (`AAPL <= 1.00`,
GTC, order_id 1331320792), which made the read path observable and changed the decision from
"do not fix blind" to "fix, then test".

### The live shape settles it

`get_alert` against this gateway build returns **26 top-level keys, none camelCase**, matching
IBKR's documented example key for key. So the documentation-based reasoning held, and the
counts are now measured rather than inferred:

| | count | cross-case |
|---|---:|---|
| live detail top-level keys | 26 | **0** camelCase |
| create/modify request fields | 19 | **0** snake_case |
| shared top-level names | **2** | `conditions`, `tif` |

`orderId` is absent from what was posted, so the call read as a create. 17 of 19 request
fields were missing by name. `_alert_detail_to_request` now translates, with the live
response as the test fixture rather than the doc example, and the caller's patch applies to
the translated body.

### The result that was worth the round trip

A **well-formed** body — documented shape, `orderId` present, every required field supplied —
still returns `HTTP 403 - Access Denied`.

That separates two hypotheses which had been confounded since the alert investigation began.
The 403 was attributed to the `>=`/`<=` operator block, but "our body was malformed" was an
equally live explanation and nothing distinguished them. Body shape is now eliminated. The
operator block stands on its own evidence.

The owner's alert was unchanged by the test (same id, name, operator, value, TIF, active,
untriggered) and no duplicate was created — both verified after the call.

### A control deliberately not run

The obvious next step is to resend the identical body with a non-blocked operator, holding
everything else constant. **Not run against a real alert**: the body carries `orderId`, so it
modifies in place, and restoring the original needs `<=` — which 403s. The alert could not be
put back. Recorded here so the idea is not revived without the trap attached.

The handler's docstring carries the finding, so the next person to open it sees it before the
code.

---

## Phase 3 — the documentation block

Seven findings, each verified against the code before being touched rather than taken from
the Phase 1 summary. One did not reproduce as stated and is recorded that way.

| ID | Sev | Outcome |
|---|---|---|
| DOCB-01 | Critical* | Confirmed. `docs/README.md` stated the gate policy as "re-run for every chained reply" — the pre-2026-09-11 wording, wrong about Gate 1 |
| DOCA-01 | **High** | Confirmed. SECURITY.md printed a **weaker mitigation than the code implements** |
| DOCA-02 | **High** | Confirmed. `tools-reference.md` documented `search_contract`'s pre-2026-08-05 menu behaviour |
| SEC-05 | Medium | Confirmed. README contradicted itself seven lines apart |
| DOCA-10 | Medium | Confirmed exactly: 44 tools defined, `get_pa_periods` the one missing |
| DOCA-11 | Medium | Confirmed, **but not for the stated reason** — see below |
| DOCA-18 | Low | Confirmed in exactly three documents |

### DOCA-01 — the documented mitigation was weaker than the implemented one

SECURITY.md's confused-deputy section printed `_ORDER_ID_RE = re.compile(r"^\d+$")` while
`client.py` compiles `r"^[0-9]+$"`. Not equivalent, and the difference is the vulnerability:

| input | documented `\d+` | actual `[0-9]+` | `int()` accepts? |
|---|---|---|---|
| `123` | MATCH | MATCH | 123 |
| Arabic-Indic `١٢٣` | **MATCH** | reject | **123** |
| Devanagari `१२३` | **MATCH** | reject | **123** |
| mixed `1٢2` | **MATCH** | reject | **122** |

The mixed case is the sharp one: it passes `\d+`, and `int()` silently yields a *different*
order id than the string reads as. The same file records the fix for exactly this gap in its
audit log (2026-07-11 H-2 follow-up), so the file contradicted itself — and anyone copying
the documented pattern would have reintroduced the gap.

All three regexes were compared programmatically, not by eye: one mismatch of three, and
`client.py` defines exactly those three. The edit was confined to the **control inventory**;
the historical audit log quotes old values deliberately and was not touched.

`tests/security/test_documented_controls.py` now fails if the two drift apart, in either
direction, and asserts the Unicode property rather than only comparing strings. Three
mutants, three caught. It is explicitly **not** a twelfth invariant — the eleven are
unchanged.

### DOCA-11 — confirmed, but the stated cause was wrong

The finding read "README's Backtesting example does not run as pasted". The attribute access
is fine (`result.sharpe` etc. all resolve on a `BacktestResult`). The example fails for a
different reason: `run_backtest` spawns its child with `multiprocessing.get_context("spawn")`,
so the child re-imports the caller's `__main__` and re-runs a module-level call. Pasted into
a script it dies with

```
BacktestRuntimeError: Strategy process exited unexpectedly (exit code 1)
```

which blames the strategy — the one thing not at fault. Both halves fixed: the example now
carries the `if __name__ == "__main__":` guard, and the exception names the guard as a
possible cause so a programmatic caller sees it (Python prints its own guidance to stderr,
but `_safe_error` renders only `str(exc)`, where that text does not appear).

**A vacuous test of my own, caught by mutation.** The first version asserted
`"__main__" in stderr`, which Python's multiprocessing bootstrap error satisfies on its own —
the mutant removing the hint survived. Tightened to assert on the `BacktestRuntimeError:`
line specifically; the mutant is now caught.

### DOCA-18 — three documents, and a fourth that was already right

`README.md`, `CLAUDE.md` and `SECURITY.md` all described the CI dependency audit as running
"over the full installed tree". It runs in **requirements mode** — `pip install --dry-run` in
a throwaway venv, installing nothing — which this audit verified by running CI's exact
command. `CHANGELOG.md` already said so correctly. The distinction is the one that produced
Phase 0's near-miss: a local installed-tree run showed 50 vulnerabilities and a fix version
that does not exist under OSV, none of which CI sees.

---

## Phase 3 — the data/quant layer, re-derived

**The Phase 1 detail for DATA-03/04/05 was never written into this report** — it lived in
the agent output and is gone. Rather than guess at three findings, the domain was
re-audited directly, the same way the indicator sweep was run.

`analytics.py` was the obvious target: every test for `sharpe`, `max_drawdown`, `cagr` and
`calmar` was a shape or sign assertion ("positive returns → greater than zero", "flat is
zero"), so none could detect a wrong formula. Only `sortino` had ever been pinned to an
outside worked example. That is the same pattern the indicator sweep found.

### DATA-25 — **High**: max drawdown ignored any fall beginning on the first bar

`(1 + returns).cumprod()` starts the equity curve at the first bar's value, so the starting
capital was never a peak:

| returns | reported | correct |
|---|---|---|
| `[-0.50, 0, 0, 0]` | **0.0000** | −0.5000 |
| `[-0.50, +1.0, 0, 0]` | **0.0000** | −0.5000 |
| `[-0.10] × 4` | −0.2710 | −0.3439 (understated 21%) |
| peak occurs mid-series | −0.5000 | −0.5000 ✓ |

The first case reported **zero drawdown beside a CAGR of −100%**, which cannot both be
true. `calmar` returns 0.0 when drawdown is zero, so that strategy scored the same Calmar
as one that never drew down; `max_drawdown_duration` reported 0 bars under water, not 4.

Drawdown is a risk measure and this understated it — the dangerous direction. The fix is
one line (`_equity_curve` prepends 1.0) and carries a useful invariant: prepending can only
**raise** an early peak, so a computed drawdown can only become more negative or stay equal.
**Every figure produced before the fix is therefore understated or exact, never
overstated.**

Persistence: `save_backtest` writes `max_drawdown` as a column, so the 7 stored backtests
carry the old figures and are not comparable with new ones on this metric. One of them
(#2, `AAPL RSI MeanReversion`) is doubly affected — `max_drawdown=0.0` **and** `sharpe=0.0`,
computed before today's RSI fix.

### The control that makes the finding trustworthy

Peak *selection* was already correct, and is now pinned to Investopedia's published worked
example — 500k → 750k → 400k → 600k → 350k → 800k ⇒ −53.33%, with the interim 600k peak
deliberately not used. **That test passes both before and after the fix**, which is exactly
why it is worth having: it proves the new tests discriminate between "the peak is chosen
wrongly" and "the starting capital is missing", rather than failing everything.
https://www.investopedia.com/terms/m/maximum-drawdown-mdd.asp

Four mutants run, four caught (equity origin, cummax→cummin, min→max, `<`→`<=`).

### Verified correct, unchanged

- **`sharpe`** — `E[Ra−Rb]/σ` annualised by √periods, sample standard deviation, risk-free
  de-annualised by `/periods`. Matches the ex-post definition.
- **`cagr`** — `total^(1/years) − 1` over the compounded product.
- **`calmar`** — the MAR-ratio (whole-series) form, an owner decision from 2026-07-07, kept.

### Recorded, not fixed

`profit_factor` and `avg_win_loss_ratio` return `float("inf")` when there are no losing
trades. `json.dumps` emits `Infinity`, which **RFC 8259 does not permit** and a strict
parser rejects (`allow_nan=False` raises). Not currently reachable as a break: neither
metric is persisted — `save_backtest` stores only `total_return`, `sharpe`, `sortino`,
`max_drawdown`, `num_trades`, `win_rate` as columns plus a `metadata` blob — and the
model-facing path renders text. Left as-is; graded Low.

---

## Phase 3 — API-09: a deadlock that made every `--stream` price alert dead

The one-line finding was "in `--stream` mode the server never subscribes to any alert's
conid". Reading the loop shows why it is stronger than that — it is a deadlock, not an
omission:

```python
async for item in ws.listen():
    if isinstance(item, LiveQuote):
        for cid in active_conids - subscribed:
            await ws.subscribe(cid)      # only reachable from inside a LiveQuote
```

A `LiveQuote` is produced only from `topic.startswith("smd+")`, and the gateway sends
`smd+` only after an `smd+{conid}` subscription. No subscription, no quote; no quote, no
subscription. The only subscriptions made before the loop are executions and P&L, neither
of which enters that branch.

**Not moot, unlike TOOL-01.** These alerts are local SQLite rows written by
`add_price_alert` and checked by `AlertManager`; they have nothing to do with IBKR's own
alert API, which this audit separately proved unusable through the gateway. So this was a
feature that worked end to end apart from one unreachable line.

**Why it survived.** `_stream_loop` had no test. `test_stream_loop_retry_on_error` and
`test_stream_loop_cancelled_propagates` both patch `_stream_loop` out and exercise only the
retry wrapper around it, so the entire loop body — including this deadlock — was untested.
The same shape as the other Criticals: a control that could not fail.

Worth noting that `docs/mcp-server-reference.md`'s own programmatic example subscribes
before it listens, i.e. the documentation was right and the server code was not.

Reconciliation now runs before the loop and again on every message regardless of type, and
still releases a subscription when its alert is triggered or deleted. Two tests, three
mutants, all caught — including "reconcile only inside the LiveQuote branch", which is the
original defect.

---

### CLOSED: the intermittent live failure, captured and traced to this audit's own fix

Session 1 recorded this as open and deliberately did not guess at it:

> One run of `pytest tests/test_web_tools_live.py -m integration` reported `1 failed, 11
> passed`; four further runs the same day were clean. The failing test's identity was not
> captured, so it is recorded as unknown rather than guessed at.

It reproduced on 2026-09-16 during a full 94-test integration sweep, and this time `-rf`
caught it:

```
FAILED tests/test_web_scraper_drive_live.py::test_crawl_site_saves_pages_to_drive
playwright._impl._errors.Error: Route.abort: Route is already handled!
crawl_site failed for https://docs.crawl4ai.com/core/quickstart/:
    Error: Browser.close: Route.abort: Route is already handled!
```

**It was introduced by WEB-01 — this audit's own first Critical fix.** When a page tears
down mid-request, Playwright resolves the outstanding route itself. `route.fetch` then
raises, the handler's `except` branch calls `route.abort()`, and abort raises *from inside
the except block*. Nothing catches a raise from within an except handler, so it escaped
`_reject_private_requests` entirely and Playwright re-raised it at teardown. A guard whose
failure path can itself throw is not a guard.

Every abort site is now best-effort via `_abort_quietly`, which logs at debug rather than
swallowing silently — a run of these would mean routes are being resolved out from under
the guard, which is worth seeing. The SSRF property is untouched: the host checks run
before anything is fetched or served, so a request that reaches an abort has never been
fulfilled.

Verification, in order of strength:

- **Deterministic**: two unit tests drive a `_TornDownRoute` whose every operation raises
  the way Playwright's does — teardown during `fetch` and during `fulfill` — plus one
  asserting a failing abort still never serves private content. 3 mutants run, 3 caught,
  including "private host no longer aborted".
- **Corroborating**: 6 consecutive clean runs of the test that failed, and 4 consecutive
  clean runs of the three web live files (17 passed each). For an intermittent fault this
  is corroboration, not proof; the unit tests are the proof.

The session-1 note guessed at a transient network fault as "the likely cause". It was not,
and the note said "likely" is not evidence — correctly. The lesson stands in the other
direction too: the flake was in code this audit had just written, and the first instinct
was to look outward.

### Live validation — full sweep 2026-09-16

Run as a single pytest process, so one `EndpointPacer` governs the whole sweep. **The pacer
is per-process**, so two concurrent processes against the gateway do not share a budget;
live runs and ad-hoc probes were kept strictly sequential for that reason.

| Suite | Result |
|---|---|
| `test_client_live.py` | 57 passed, 4 skipped |
| `test_alerts_live.py` | 1 passed, 10 skipped (alerts remain non-functional via the gateway — upstream) |
| `test_web_tools_live.py`, `test_crawl4ai_live.py`, `test_web_scraper_live.py` | 17 passed (x4 runs) |
| `test_web_scraper_drive_live.py` | 2 passed (x6 runs) |
| **Full `-m integration` sweep** | **94 collected — 1 failed before the fix (that failure), clean after** |

Gateway/orders totals match the pre-audit baseline of 58 passed / 14 skipped exactly.

---

## Phase 3 — API-11: the Nit that was hiding five defects

API-11 was filed Low/Nit: *"zero of 74 methods return a Pydantic model."* The owner put the
fix in scope — thread Pydantic return types through all 74 methods. Before writing any of
that, the six models `models.py` already published were measured against responses captured
from the live gateway. **None of them worked.**

| Model | Endpoint | Result before the fix |
|---|---|---|
| `Order` | `/iserver/account/orders` | **raised** — `orderId` arrives `int`, the field declared `str` |
| `Contract` | `/trsrv/secdef` | **raised** — those rows carry `ticker`, not `symbol` |
| `Notification` | `/fyi/notifications` | validated with **every field empty** — IBKR sends `D/ID/FC/MD/MS/R` |
| `Trade` | `/iserver/account/trades` | `time` always `""` — the key is `trade_time` |
| `Position` | `/portfolio/{id}/positions` | kept 7 of 51 keys |
| `AccountSummary` | `/portfolio/{id}/summary` | kept 4 of 108, and published P&L the endpoint does not |

All six passed `tests/test_models.py` throughout. That file builds each model's input by
hand, so every test asserted that the model agreed with itself — the same shape as API-01's
stub-verified Critical and TOOL-01's fabricated alert body. **A fixture whose shape you chose
cannot tell you whether the shape is right.** The models are exported from `__init__.py` and
were never used by `client.py`, `claude_tools.py` or `mcp_server.py`, which is why two of them
could raise on real data for the package's whole life without anyone noticing.

`Notification` is the clearest case. IBKR's page for `/fyi/notifications` documents
`D` date, `ID` identifier, `FC` FYI code, `MD` content, `MS` title, `R` read flag. The model
declared `id`, `date`, `headline`, `body`, `isRead` — **zero overlap** — and validated anyway,
because every field had a default. Each notification came back fully populated with nothing.

### Two findings raised by the measurement

**API-18 — Medium: `AccountSummary` asserted P&L the endpoint does not publish.**
`unrealized_pnl` and `realized_pnl` read `0.0` on every call. The 108-key capture contains no
key matching *pnl*, and `portfolio-summary.md` documents none — it describes an open key/value
structure of "45-135 unique values" and never mentions profit and loss. Zero is a number a
reader will act on; absence is not. The four amounts are now `float | None`, and a key that
was not sent reads `None`. Whether some other account or segment publishes one is **not
established**, so the model reports what it found rather than generalising from one account.
Realised and unrealised P&L come from `/iserver/account/pnl/partitioned` — `get_pnl()`,
`upnl.{account}.{upl,dpl}`.

**API-19 — Nit: every `_normalize` before-validator was dead code.** Each mapped a declared
alias onto its own field, which `populate_by_name` already did. Found by mutation, not by
reading: breaking `Trade`'s `trade_time` alias left the entire suite green, because the
validator silently covered for it. The genuinely multi-spelling cases (`ticker`/`symbol`,
`assetClass`/`secType`, `con_id`/`conid`, `listingExchange`/`exchange`, `name`/`companyName`)
are now `AliasChoices`, the validators are gone — 60 lines — and each spelling is individually
mutation-killed.

### The design constraint the evidence set

A typed return that narrows a 51-key position to seven fields would be a worse defect than
the missing types, and the same defect this audit already found three times: silently
truncated market history, the alert modify body missing 17 of 19 fields, three endpoints
returning `[]` for data that had arrived. So the models are **views over the payload, never a
replacement for it**. `IBKRResponse` snapshots the response before any normaliser runs and
serves it through the mapping protocol, so `position.mkt_value` is the typed view while
`position["mktValue"]`, `dict(position)` and `len(position)` are exactly what IBKR sent.
Live-verified lossless on all seven endpoints.

Two further rules came from real records rather than from design taste:

- **A `null` is "not applicable", not a malformed value.** Searching for AAPL returns four
  equity listings and a bond aggregate whose `symbol`, `companyName` and `description` are
  all `null` (`{"bondid": 4, "companyHeader": "Corporate Fixed Income", "conid": "2147483647"}`).
  A null now falls back to the field default and stays readable as `contract["symbol"]`.
- **A record that will not validate is passed through, never dropped.** Hence
  `list[Position | dict[str, Any]]` rather than `list[Position]`. Dropping the row would
  answer "what do I hold?" with a confident, incomplete list.

### Two more, found by feeding the handlers the real thing

Threading typed returns into `client.py` is only safe if the layers above survive them. The
suite could not answer that: `toolkit._client` is a `MagicMock`, so every existing test hands
its handler whatever the test itself wrote — always a dict. Driving the handlers with models
built from the captured response found two defects, one new and one old.

**TOOL-11 — Medium: `ibkr://positions/current` would have stopped carrying positions,
silently.** The resource `json.dumps` the client's return directly, and its handler catches
every exception and answers with an error object. A `Position` is not JSON-serialisable, so
the resource would have kept answering successfully with
`{"error": "Object of type Position is not JSON serializable"}` — the third time in this audit
that a failure would have worn a success's shape, and the second on this exact resource
(the 2026-09-16 `text = "[]"` finding was the first). `models.json_default` is now passed at
both serialising call sites, and each is mutation-killed.

**TOOL-10 — Medium: the `get_notifications` tool has never shown a notification.** Its
renderer reads `n.get("isRead")` and `n.get("headline") or n.get("title")`. IBKR sends
`R`, `MS`, `MD`, `D`, `ID`, `FC` and none of those three, so every notification rendered as
`- [UNREAD] ?` — correct count, no titles, read state always wrong. Live, against three real
notifications:

```
FYI Notifications (3 unread):
- [UNREAD] ?
- [UNREAD] ?
- [UNREAD] ?
```

This predates the model work entirely; the handler read raw dicts and guessed their keys, the
same guess `Notification` made. `tests/claude_tools/test_account.py` stubbed
`{"id", "title", "body", "isRead"}` — a payload invented to match the guess — and asserted the
title appeared, so the test passed on data that cannot occur. The stub is now IBKR's
documented shape and the renderer reads `MS`/`R`. It reads them through the mapping rather
than through the model's attributes, deliberately, so a record that failed validation and
arrived as a plain dict still renders.

**TOOL-12 — Low: a failing unread count discarded a notification list that had arrived.**
Found while verifying TOOL-10 live. `/fyi/unreadnumber` returned
`HTTP 423 {"status":"waiting for reply"}` on four consecutive attempts against a healthy,
authenticated gateway while `/fyi/notifications` answered normally throughout. The handler
called it unguarded, so the list — the actual answer — would have been thrown away for the
sake of a decoration. The count now degrades to "unread count unavailable".

**On `R`'s polarity, and the limit of the evidence.** IBKR documents `R` as "Return if the
notification was read or not. Value Format: 0: Disabled; 1: Enabled". Measured, three
notifications all carried `R: 0` while `/fyi/unreadnumber` reported 3 — consistent with 0
meaning unread. **`R: 1` was never observed**, so the read branch rests on the documentation
alone, and the code says so rather than implying the polarity was verified. The first live run
after the fix printed "(0 unread)" beside three `[UNREAD]` rows, which looked like a
contradiction in the flag; it was the count endpoint failing, and re-measuring rather than
reasoning from the inconsistency is what separated the two.

### Status

Six of 74 methods now return models — `search_contract`, `get_secdef` (`Contract`),
`get_positions`, `get_trades`, `get_live_orders`, `get_account_summary`, `get_notifications`.
`client.py`'s module docstring claimed typed returns from the day it was written; the claim is
now an enumerated list, so it can be checked. **The remaining 68 are still open under API-11**
— they need the same treatment endpoint by endpoint, each shape verified against a captured
response and its `.md` page, and several of them (`get_scanner_params`, `get_contract_rules`,
`get_secdef_info`) publish open structures where a model would assert more than IBKR does.

### Evidence

`tests/fixtures/ibkr_live_shapes.json` — 27 endpoints captured verbatim from an authenticated
gateway on 2026-09-16, account numbers rewritten in keys and values, nothing else altered.
Reproduce with `scripts/audit/capture_live_response_shapes.py`. Every documentation fetch ran
a fabricated control URL in the same batch (`portfolio-summary.md` 2,391 B against 411 B
`# Page Not Found`).

Every new test was mutation-tested. **Two mutants survived the first pass, and both were real
gaps rather than noise:** `Position`'s typed fields had no test at all — the losslessness
tests read the raw payload and nothing read the typed view — and the documented null-`amount`
branch was unexercised. Both now have one, and all sixteen mutations die.

Live verification (gateway authenticated, single process): all seven endpoints returned typed
records, **zero passthrough rows**, `dict(model) == model.raw` on every one.
`get_live_orders` returned `order_id='1986940574'` from a raw `int` — the exact value that
raised before the fix.

---

## Phase 3 — SEC-03/04 investigated; two new endpoint defects found on the way

**Investigated, not yet fixed.** Recorded here so the evidence survives the pause; no code
changed. Picked up after API-11 because the remaining SEC findings are the highest-severity
items left, and because SEC-03 and SEC-04 interlock: invariant 9 is **claimed, untested, and
false**.

### SEC-03 and SEC-04 — confirmed independently

Invariant 9 reads *"Every path-interpolated identifier passes its regex —
`_ACCOUNT_ID_RE`, `_ORDER_ID_RE`, `_REPLY_ID_RE` applied in every URL-building method"*
(`docs/security-architecture.md:193`). An AST enumeration of `client.py` found **36 path
interpolations, 12 with no validator called in the enclosing method**:

| Interpolation | Assessment |
|---|---|
| `_resolve_one_reply` ← `reply_id` (twice) | **Real gap.** `reply_order` validates the same value; this path does not |
| `mark_notification_read` ← `notification_id` | **Real gap.** Caller-supplied string, straight into the path |
| `update_delivery_option` ← `option` | **Real gap**, and worse than hygiene — see API-21 |
| `get_contract_info`, `get_contract_info_and_rules`, `get_contract_algos`, `get_positions_by_conid`, `get_position` ← `conid` | Annotated `int`, but annotations are not enforced and this is public library API. `/iserver/secdef/search` returns `conid` as a **string** (`"265598"`), so a string conid is an ordinary value here, not a hypothetical |
| `get_positions` ← `page` | Same: annotated `int`, unvalidated |
| `ping`, `tickle`, `delete_watchlist` ← `self._base` | Not an identifier — the base URL |
| `get_live_orders` ← `type(orders).__name__` | **Not a URL at all.** An error message that begins `/iserver/account/orders returned …`. The first version of the checker reported it, which is why the committed one requires the literal to contain no whitespace |

SEC-04 is confirmed by construction: there is no `security`-marked test for invariant 9, and
writing the enumeration above is what exposed the three real gaps. The fix is one test that
requires every interpolation to be either validated or in an explicit allowlist with a stated
reason, so the exceptions are visible rather than absent.

### API-20 — **High**: `mark_notification_read` uses the wrong verb and the wrong path

```
code: POST /fyi/notifications/{notification_id}/read
docs: PUT  /fyi/notifications/{notificationId}          (empty JSON body)
```

Both of IBKR's documentation families agree, and they are independent pages:
`v1/endpoints/fy-is-and-notifications/mark-notification-read.md` (1,100 B) and
`api-reference/trading/trading-fy-is-and-notifications/read-fyi-notification.md` (5,313 B),
each fetched with a fabricated control URL in the same batch (451 B / 502 B
`# Page Not Found`). The method's own docstring cites the first of them. The API-reference
page also documents the 400: *"Missing, empty, **non-numeric**, or out-of-range parameter"* —
so the identifier is numeric, which settles the regex SEC-03 needs.

**The live test could not have caught it.** `test_mark_notification_read_noop` accepts a
successful result, HTTP 400, HTTP 404 **and** HTTP 423 — every outcome the call can produce.
Its docstring says "Verify mark_notification_read is callable"; it passes whether or not the
endpoint exists. The fourth test-that-cannot-fail this audit has found.

### API-21 — **High**: `update_delivery_option` conflates two different endpoints

```
code: POST /fyi/deliveryoptions/{option}   body {"deviceId": …, "enabled": …}
```

IBKR documents two endpoints here, and they differ in verb *and* in how parameters are passed:

| `option` | Method | Path | Parameters |
|---|---|---|---|
| `device` | POST | `/fyi/deliveryoptions/device` | JSON body: `deviceName`, `deviceId`, `uiName`, `enabled` |
| `email` | **PUT** | `/fyi/deliveryoptions/email` | **query** `enabled=true\|false` |

So the `device` call sends 2 of the 4 documented fields — the same defect shape as TOOL-01's
alert body — and the `email` call is wrong in both verb and parameter style and cannot work.
Any other `option` value is not a documented path at all, which is why the unvalidated
interpolation is more than hygiene: the set of valid values is exactly two and the code
accepts anything.

The two families disagree on whether the `device` body fields are required (`v1/endpoints`
says all four Required; `api-reference` says optional). That disagreement is recorded rather
than resolved — sending all four satisfies both readings.

Neither method is exposed as a tool, so the blast radius is the library API and any consumer
calling it directly. Both are `ACCOUNT_STATE` writes in the capability registry, correctly.

**Not verified live.** Confirming API-20 means marking one of the owner's real notifications
read, and this package has no method to mark one unread again. Deferred to the owner.

---

## Phase 3 — SEC-03/04 closed, API-20/21 fixed, and what the new control found next

### Invariant 9 now holds as a property, not as a list of three names

`tests/security/test_path_identifier_validation.py` enumerates every value interpolated into
a URL path in `client.py` and requires that **that value** be passed to a validator, or listed
in `ALLOWED` with a reason. Three exemptions are recorded (`self._base` in `ping`, `tickle`
and `delete_watchlist` — the gateway base URL, pinned to loopback at construction), and a
fourth test fails if an exemption outlives the interpolation it excuses.

**The first version of the checker asked the wrong question.** It asked whether the enclosing
method called *any* validator, which `get_positions` satisfied by validating its account id
while interpolating an unchecked `page` into the same URL. Strengthening it from per-method to
per-value took the count of unguarded interpolations from 8 to 10 — `get_positions`' `page`
and `get_position`'s `conid` were invisible to the weaker form. A checker that asks a weaker
question than the invariant is the same defect as no checker, one step further from being
noticed.

Ten interpolations were closed: five `conid` sites and one `page` (`_validate_conid`,
`_validate_page`, on `_NUMERIC_PATH_SEGMENT_RE`), `_resolve_one_reply`'s reply id, the
notification id, and the delivery option.

### SEC-11 — **Medium, open**: `_REPLY_ID_RE` has never met a real reply id

Adding `_validate_reply_id` to `_resolve_one_reply` — the obvious fix, and what the invariant
literally asks for — broke 18 reply-chain tests, whose fixtures use ids like `"RPL1"`. That is
a test-fixture problem, but chasing it surfaced a real one: **`_REPLY_ID_RE` is inferred from a
single documented example** (`a12b34c5-d678-9e012f-3456-7a890b12cd3e`) and no reply id IBKR
actually sent exists anywhere in this repository, because exercising one means placing a real
order.

The asymmetry decided it. A strict check on the chain path buys protection against a malicious
localhost gateway — the trust anchor we authenticate *to* — on a value **no caller supplies**.
If the inference is wrong it rejects a legitimate id in the middle of a reply chain, leaving a
placed order unconfirmed at IBKR. So `_resolve_one_reply` validates the property that matters —
`_validate_path_segment`, "this stays one path segment" — while `reply_order`, whose reply id
*is* caller-supplied, keeps the strict regex it has had since 2026-07-11.

`reply_order`'s strict check carries the same unverified inference and has carried it since
2026-07-11. **Open**, because closing it means placing a real order and reading the reply id
IBKR returns.

### API-20 and API-21 — fixed against both documentation families

`mark_notification_read` now does `PUT /fyi/notifications/{notificationId}` with an empty
body. `update_delivery_option` dispatches: `device` → `POST /fyi/deliveryoptions/device` with
all four documented body fields, `email` → `PUT /fyi/deliveryoptions/email?enabled=…`. Both
needed a `_put` helper, which is named in `test_order_write_boundary.py` alongside `_post` and
`_session` so a new order-write call site cannot reach the network through it either.

**The live test that could not fail is gone.** `test_mark_notification_read_noop` accepted a
successful result, 400, 404 and 423 under the docstring "Verify mark_notification_read is
callable". It is replaced by a local-refusal assertion plus
`test_mark_notification_read_live_write`, which runs only when `IBKR_TEST_NOTIFICATION_ID`
names a real id and asserts IBKR's documented `{"V": 1}` acknowledgement. It is opt-in
because marking a notification read writes to the account holder's data and this package
exposes no way to mark one unread.

### SEC-12 — raised and closed: the suite inventory was missing a file

Reconciling SECURITY.md's suite table against the constitution's eleven properties turned up a
twelfth file on disk — `test_documented_controls.py`, **added by this audit's own earlier
session and never listed in the table it exists to police**. The table reads as the inventory
of the suite, so a file missing from it makes the inventory look complete while it is not:
SEC-04 one level up. Closed by listing it, and by a new assertion in that same file that the
table and the directory must agree in both directions.

### Verification

Nine mutations, each reverting one of the new controls; every one turns a test red, and the
control run is green. Gates: ruff, ruff format, mypy (117 files), pytest 1,399 passed,
`pytest -m security` 208 passed.

**Not live-verified.** The gateway session expired during the pause and API-20's live check is
the opt-in write above, awaiting the owner. The unit tests pin verb, path and body against the
documented shapes; nothing here claims a live round trip.

---

## Phase 3 — SEC-11 closed by evidence that existed all along

**I recorded SEC-11 as "no reply id IBKR actually sent exists anywhere in this repository,
because exercising one means placing a real order." The second half was wrong.** The owner
pointed out that real orders have been placed and executed, and that claudia_ui holds the
records. It does. I had searched one repository and written a conclusion about the world.

`docs/order-api-reference.md` § *IBKR's reply chain — what it has actually sent* says exactly
where: since 2026-09-10 (`ibkr_core_mcp 882231a` + `claudia_ui d732c44`),
`place_order_and_confirm` / `modify_order_and_confirm` take a `reply_log=`, and `order_flow`
persists it as `ibkr_replies` in the decision metadata. **24 distinct reply IDs** were
recovered from 25 such rows, spanning real orders placed 2026-09-10 and 2026-09-11.

### What the measurement says

| | Result |
|---|---|
| Reply IDs recovered | **24**, from real orders on 2026-09-10/11 |
| Matching `_REPLY_ID_RE` (`^[0-9a-fA-F-]{1,64}$`) | **24 of 24** |
| Shape | Standard lowercase UUID, 36 chars, **8-4-4-4-12**, every one |
| Characters ever seen | `-0123456789abcdef` — no uppercase |
| IBKR's *documented* example | `a12b34c5-d678-9e012f-3456-7a890b12cd3e` — **8-4-6-4-12, not a valid UUID** |

The last row is the interesting one. **The example IBKR publishes is malformed relative to
what IBKR sends.** A pattern written as a UUID would accept all 24 real IDs and reject the
only example the documentation gives; the charset-and-length pattern accepts both. The
original decision to "match on charset/length, not exact segment structure" was right, and
now has a reason behind it rather than a hunch.

### What changed

`_resolve_one_reply` now calls `_validate_reply_id`, the same strict check `reply_order` has
used since 2026-07-11. The reason for the weaker `_validate_path_segment` — that the regex was
an inference and a false rejection mid-chain would leave a placed order unconfirmed — is void,
so the weaker check and its regex are **deleted rather than left in place**: an unused control
is one nothing can exercise.

The 39 test fixtures spelling reply IDs `"RPL1"` now carry the shape IBKR actually sends. That
those fixtures were unrealistic is what made the strict check look like a regression when it
was first applied, and it is why the first attempt reached for the weaker guard.

Three tests pin the measurement: the regex accepts the observed UUID shape, still accepts
IBKR's non-UUID documented example, and rejects eight traversal and malformed forms. Tightening
it to a UUID fails the second; loosening it fails the third. **The 24 IDs are deliberately not
committed** — this repository is public and they are the account holder's, so the shape is
recorded and the values are not.

### The lesson, which is not the finding

The finding was closed in twenty minutes once the owner said where to look. The cost was
writing "no evidence exists" from a one-repository search — the same shape as every
control-that-cannot-fail in this audit, inverted: not a check that could not fail, but a
conclusion that could not be contradicted by the place I chose to look. **Absence of evidence
in one repository is not evidence of absence**, and this package's own consuming project is
the first place to look for live evidence about it.

---

## Phase 3 — TOOL-02, TOOL-08 and API-07: the alert create body, against the page that does exist

### The page was found by a previous session and I re-searched anyway

`create-or-modify-alert.md` is dead and absent from `llms.txt`, so I ran `firecrawl_search` —
which returned only general Web API pages, a third-party GitHub client and a YouTube video.
Then I checked this repository's own docs, where `docs/ibkr-api-behaviors-reference.md`
already recorded the answer: the live page is
`api-reference/trading/trading-alerts/create-alert.md` (28,399 B, re-fetched 2026-09-16 with
a fabricated control returning "# Page Not Found"), found by an earlier session of this same
audit. **Check the repository's own notes before searching the web** — the same lesson as
SEC-11, one step smaller.

Byte size was useless here and would have misled: the real `alerts/introduction.md` is
**313 B**, smaller than the 394 B "# Page Not Found" body. Content, not size, is what
discriminates, exactly as CLAUDE.md says.

### TOOL-02 — the condition carried four wrong fields of six

IBKR documents six Required condition fields. Measured against the live page and the
archived capture, which agree:

| IBKR documents | We sent |
|---|---|
| `conidex` — `"265598@SMART"` | `conid` and `exchange` as **two** separate keys |
| `logicBind` — `a`/`o`/`n` | **missing** |
| `triggerMethod` — `"0"` | **missing** |
| `type`, `operator`, `value` | correct |
| *(no such field)* | `conditionType: "Price"` — invented; `type: 1` already means Price |

Corroborated by the account holder's own alert, whose GET detail returns `conidex`,
`condition_logic_bind` and `condition_trigger_method`.

### Three more found in the same body, none of them in the original finding

- **`isSizeCondition`** — zero occurrences in the live page and zero in the archived
  capture. The same class of invention as `conditionType`.
- **`outsideRth` was a Python bool** where IBKR documents an enum of `0`/`1`. `alertRepeatable`
  beside it was already cast with `int()`; this one was not, so it serialised as
  `true`/`false`. The account holder's alert returns `condition_outside_rth: 0`.
- **The `tif` enum offered `GTC` and `DAY`.** IBKR documents `GTC` and `GTD` only; `DAY`
  appears in no alert page, and the schema described it as "expires at market close", a
  behaviour nothing states. Now `GTC`/`GTD`, with a new `expire_time` input — IBKR documents
  `expireTime` as "Used with a tif of GTD only", and GTD without one is not a request IBKR
  can act on, so it is refused with that explanation rather than sent.

### DOCA-19 — **Medium**: "usable through the gateway" was false, and self-contradicting

`client.py` and `docs/ibkr-api-behaviors-reference.md` both said that after the `>=`/`<=`
block, "only `>`, `<` and `==` are usable through the gateway". **Twelve lines below its own
sentence**, that same file's elimination table records what actually happens:

```
>  <  ==     reach IBKR and are refused by its own engine:
             {"error":"Condition #1:can't recognize fix [>]"}
>=  <=       never arrive (403 HTML)
```

So **none of the five documented operators can create an alert**. "Not blocked by the 403
filter" is not "usable", and the difference is the whole question — a reader or a model
following that sentence would try `>` and get a different, equally dead end. `docs/audits/
live-test-log.md` had it right all along; two files repeating the wrong gloss is what made it
look settled. Both corrected, with the old wording quoted so the correction is visible.

This does not change the standing conclusion: alert creation remains impossible through the
gateway. It changes *why* a reader thinks so.

### Status

TOOL-02, TOOL-08 and API-07 closed; DOCA-19 raised and closed. Five stale citations of the
dead page repointed (`docs/api-reference.md`, four in `tests/test_alerts_live.py`); the
remaining mentions are prose warnings that the page is gone, which is the point.

**None of this can be live-verified**, and not because the gateway session expired: the
gateway refuses every operator, so a correct body cannot be proven correct here. What the
fixes remove is a *second* reason the call would fail, exactly as the TOOL-01 round trip did
— the value is in eliminating confounds, not in a green result.

Six mutations, each reverting one fix; every one turns a test red.

---

## Phase 3 — SEC-13: the fixture this audit created published the account holder

Raised while re-deriving the `DOCB` findings, whose Phase 1 text was never written down. The
sweep began mechanically — every backticked token in the 19 non-high-risk documents that
names a file must resolve somewhere in the tree — and one of its hits was
`flex_UXXXX699_2026-07-02_2928480049.xml`, a filename in `docs/flex-query-reference.md`
carrying the account holder's real IBKR account number. Looking for the rest of that number
is what found the fixture.

### What was published

`tests/fixtures/ibkr_live_shapes.json`, added by **this audit** in `ffd6014` and pushed to
`github.com/stephus182/ibkr_core_mcp`, confirmed `"visibility":"PUBLIC"`:

| | |
|---|---|
| Legal name on the account | `accountTitle` and `displayName`, in `account_meta` and `accounts` |
| Net liquidation / cash / buying power | 52,054.15 / 21,985.98 / 176,643.44 |
| Open positions | both, with conids, quantities, market values and average costs |
| Executed trades | four real futures fills with prices, order IDs and IBKR execution IDs |
| Resting order | one, with its order id and the consuming app's order reference |
| Account summary | 68 populated fields of 108 |
| Watchlist names, FYI notification bodies and IDs | all |

Plus the account number itself in **eight** tracked files, 33 occurrences — two living
documents, two unit-test modules and four audit records.

### The control that existed, and what it covered

`capture_live_response_shapes.py` did redact. It rewrote account numbers, in keys as well as
values, and asserted afterwards that none survived. **That assertion passed.** Its scope was
one field class of ten, and the file's own README stated the scope plainly — "account numbers
are the only thing rewritten … every value is exactly what came off the wire" — which is why
nothing flagged it: the document and the code agreed, and both were describing a control that
was narrower than the risk.

This is the sixth instance of the pattern this audit has recorded, and the first one the audit
introduced itself, in the same session that wrote up the other five.

### What changed

`scripts/audit/redact_live_payload.py` inverts the rule. In an owner-scoped payload **every
scalar is replaced by default**; exemptions are a named list of eleven keys holding IBKR
vocabulary (`currency`, `secType`, `assetClass`, `type`, and the ledger/summary envelope
labels). A field IBKR adds tomorrow is redacted, not published. Eight endpoints returning
public contract and market reference data — identical bytes for every customer — keep their
values.

Two properties made it harder than a `.replace()`:

- **Shape is the point.** The fixture exists to prove what IBKR sends. Keys, nesting and
  scalar types are asserted identical before and after redaction, on every re-derivation.
- **Type is not enough — the domain matters too.** A first pass preserved types and broke
  twelve of the fixture's own tests: IBKR sends `price` and `commission` as numeric *strings*,
  so `"7658.5"` → `"REDACTED"` is a string for a string and still unparseable; and `R` is a
  0/1 int Pydantic coerces to bool, so `0` → `1111111` is an int for an int and no longer a
  boolean. *A fixture that no longer validates is not a redacted fixture, it is a deleted one.*

Measured after: **1,170 owner-scoped scalars, 0 that are not a placeholder, a flag, or an
exempted structural value.** All 32 model tests still pass against it.

### The two mutants that mattered

Eight mutations were run against the new guard. Six were caught immediately. The two that
were not are the findings:

**M4 — re-exempting `fullname` survived.** The test imported `STRUCTURAL` and
`PUBLIC_ENDPOINTS` from the redactor and exempted whatever they held, so widening the code
widened its own oracle in one edit. `fullname` is the exact key that leaked `GLD` and `IGV` as
holdings on the first run of the new redactor — exempted as reference data, published as a
position. The lists are now **frozen in the test**, duplicated deliberately, with a test that
fails if the two drift apart. Adding an exemption is a two-file change and the second file is
where the reason has to be written.

**My mutation harness reported a survivor that was never applied.** `ruff format` had exploded
the `frozenset` one entry per line between writing the mutation and running it, so the `sed`
matched nothing and the unmutated code passed — reported as "SURVIVED". A mutation run that
does not verify the mutation landed is a control that cannot fail, one level up from the
control it is testing. Re-run with the edit asserted and the diff checked, M4 is caught by two
tests.

### An eighth mutant, found by the pre-push hook refusing my own commit

The first commit of `test_published_identifiers.py` was **refused by the pre-push hook, by
this test, for carrying the very thing it forbids.** Two literals: the real account number
quoted in a comment explaining the regex gap, and the fictional control the fire tests need
in order to prove the pattern can match.

The mechanism is worth recording, because it only appears once. `_tracked_files()` reads
`git ls-files`, so while the test file was untracked it was invisible to its own scan; the
full suite ran green 1,438 times. The moment it was committed it entered the scanned set and
failed. A guard that exempts itself is the obvious thing to write here and it is wrong — the
file is published like every other.

The comment is masked. The control is now **assembled at runtime** from three string
fragments, so the seven digits never appear together in the source and the exemption list
stays tight;
adding it to `PLACEHOLDERS` would have exempted a real-shaped number everywhere in the tree to
solve a problem in one file. M8 — restoring the literal — is caught.

### Status and what is deliberately not done

SEC-13 **closed at HEAD**. `tests/security/test_published_identifiers.py` (20 tests) holds:
no tracked file carries a real account number; no owner-scoped fixture value survives; the
seven specific values that were published are named individually and asserted absent; the scan
is proven non-vacuous against placeholders it must find; and the fixture is still substantial
enough to feed the model tests.

**The history is not rewritten.** The values remain in the pushed commits and can be reached
by SHA. The owner was shown the inventory and adjudicated: the exposure is not materially
actionable, no history rewrite, mask in place. The account number is masked as `UXXXX699` in
documents and audit records — which keeps those records honest about having used a real
account — and as the repo-wide placeholder `U1234567` in test code, where the value must stay
a valid account-number shape.

Gates: ruff, ruff format, mypy (119 files), pytest **1,438 passed**, `pytest -m security`
**241 passed**.

### DOCB re-derivation — where it stood when this interrupted it

The mechanical path check swept 19 documents and 214 file-naming tokens, with three fabricated
controls all reported missing. Findings so far, to be written up properly next session:

| | |
|---|---|
| `docs/plans/INDEX.md` | Lists `2026-08-07-flex-audit-handoff.md` as live "while branch `audit/checks-that-cannot-fail` is unmerged" — that branch exists neither locally nor on the remote, so the stated archive trigger can never fire |
| `docs/plans/INDEX.md` | States "root holds only live documents" and omits `2026-09-16-release-readiness-audit.md`, which is live on disk |
| `docs/plans/INDEX.md` | Still records `get-watchlists-empty-bug` as "pending live verification"; this audit closed it with a live run |
| `docs/web-scraper-reference.md:353` | Cites `_MAX_CONCURRENT_FALLBACKS`, which exists nowhere in the tree — WEB-08, confirmed |
| `docs/audits/release-readiness-audit-2026-09-16.md` | Cited `docs/order-api-reference.md` unqualified; that file is in **claudia_ui**, not this repository |

**A correction to this report's own open list.** The close-out of the previous session listed
the open findings and omitted the entire `WEB` domain. WEB-03 through WEB-09 are open and four
were re-confirmed against the code. WEB-02 is **closed** — by `102fd9d`, which replaced the
fake that could not express a redirect and added a real-browser live guard whose assertion is
the canary server's own hit counter — and was never recorded as closed.

**And the register's real state.** Of the 69 open findings, **51 have no recorded claim text**:
`DATA-03…05` (3 High, marked "see full report"), `DATA-06…19` (14, empty table cells), 16
unnamed `DOCA` and 18 unnamed `DOCB` (4 of them High). The `DATA-03/04/05` gap is already
recorded above and was answered by re-auditing `analytics.py`; the other 48 were never
re-derived. A finding with no claim cannot be closed or dismissed — under the owner's
fix-everything-then-tag bar it is not open, it is unreadable, and re-deriving those three
blocks is the remaining work before severity order means anything.

---

## Phase 3 — `DOCB` re-derived (session 9)

**The original text is unrecoverable, so nothing here is a recovery.** The 18 unwritten
`DOCB` slots named a severity and nothing else; what follows is a fresh audit of the same 19
documents, and the findings are numbered `DOCB-R1…` to keep them distinguishable from the
Phase 1 slots they replace. Where a re-derived finding cannot be matched to a slot, it is not
matched — inventing a correspondence would be the same error as carrying 120 forward without
checking it.

### Method, and the two blind spots the method itself had

Three mechanical sweeps over the 19 documents, each with fabricated controls that had to be
reported missing or the run was discarded:

| Sweep | Checked | Controls |
|---|---:|---|
| Every backticked token that names a file resolves in the tree | 214 | 3/3 caught |
| Every backticked identifier exists in the source | 902 | 3/3 caught |
| Every `<n> tools/tests/endpoints/...` claim, verified by running it | 38 | measured, not read |

**The first run of the identifier sweep produced 62 hits and most were false.** Two classes:
the documents name tests without their `test_` prefix by house convention, and `CHANGELOG.md`
names deleted code *on purpose*, because that is what a changelog is. Both were found by
reading the hits rather than counting them — and the second one is the reason a raw grep count
is a lead, not a finding. Corrected, the sweep reports 45, of which the great majority are
external vendor and IBKR field names that correctly exist nowhere in *this* tree.

### Findings

| ID | Sev | Finding |
|---|---|---|
| `DOCB-R1` | **High** | `docs/test-coverage.md`'s headline was **30% wrong** and 12 of 28 per-module figures had drifted |
| `DOCB-R2` | Medium | `docs/windows-setup.md:146` claims "All 22 MCP server tools"; there are **46** |
| `DOCB-R3` | Medium | `docs/web-scraper-reference.md:705` and `CLAUDE.md:68` both say the live web suite is **11 tests**; it is **12** |
| `DOCB-R4` | Low | `docs/web-scraper-reference.md:461` cites `_try_crawl`, which exists nowhere — the same class as WEB-08 |
| `DOCB-R5` | Low | `docs/plans/INDEX.md` carries three stale entries, one of which can never be resolved |
| `DOCB-R6` | Medium | **Code, found by the doc check** — four public behaviours with no test, all added by this audit |

#### DOCB-R1 — the file said "re-run the commands", and nobody ran them

`docs/test-coverage.md` opens with its own measurements and its own instruction: *"Do not edit
these numbers by hand; re-run the commands below."* The commands are in the file. Running them:

| | file said | measured 2026-09-16 |
|---|---:|---:|
| unit tests | 1,008 | **1,459** |
| integration tests | 93 | **100** |
| total | 1,101 | **1,559** |
| line coverage | 85% | **87%** |

and **12 of 28 per-module figures were wrong**, in both directions (`client.py` 74 → 81,
`mcp_server.py` 67 → 77, `models.py` 99 → 95).

Two of those drifts are **this audit's own work**, which makes the finding sharper than a
stale-number finding usually is:

- `indicators.py` was still listed under **"100% Coverage (no gaps)"** and had fallen to 98%.
  The DATA-01 fix added two early returns to `_wilder_smooth` and neither had a test — in the
  fix whose entire subject was correct behaviour on short series.
- `models.py` fell 99% → 95% because `IBKRResponse.items()`, `.values()` and the public `.raw`
  property, all added by the API-11 work, had no test at all.

#### DOCB-R6 — and the mutant that made it worth doing

Four behaviours were pinned. All four were already correct; none was pinned:

| Behaviour | Why it matters |
|---|---|
| RSI is NaN below `period + 1` bars | `0.0` reads as maximally oversold — the far end of DATA-01 |
| ATR is NaN below `period` bars | ATR is a volatility **denominator**; zero reads as a riskless instrument |
| `_wilder_smooth` on an all-NaN column | must not raise |
| `.raw`, `.items()`, `.values()` | public mapping surface; `.raw` must be a copy, not a view |

**The first version of the short-series test asserted only through `rsi`, and the mutant
survived.** Replacing the NaN guard with zeros is *invisible* through RSI, because RSI divides
gains by losses and `0/0` is NaN either way. The branch is observable through `atr`, which
returns the smoothed series directly — so the test moved there and the mutant is caught. This
is the same shape as SEC-13's `fullname`: a control aimed one layer away from the thing it
claims to hold.

**And a boundary I asserted instead of measuring.** The corrected test first claimed ATR needs
`period + 1` bars, by analogy with RSI, and failed against correct code. Measured, ATR needs
exactly `period`: `true_range` is defined on bar 0 (`high - low`, Wilder's convention with no
previous close) while RSI comes from `diff()` and loses one. Recorded because the failure
looked exactly like a defect and was not one.

Four mutants, all caught after the correction. `indicators.py` is back to **100%** and
`models.py` to **98%**.

#### What was checked and found correct

Not everything drifted, and the sweeps say so specifically: `indicators.add_all` adds exactly
the **20** columns `docs/api-usage-examples.md` claims; the MCP server exposes exactly **4**
resources and **46** tools as `docs/mcp-server-reference.md` and `docs/README.md` state;
`TOOL_DEFINITIONS` is **44** as `TEST_INDEX.md` and `api-usage-examples.md` state;
`docs/plans/INDEX.md`'s arithmetic (43 → 5 + 34 + 4, and 12+6+5+4+3 = 34 archived) is exact.
The `_merge_pages` / `_scrape_with_fallback` family in `web-scraper-reference.md` § 1.1 and
`require_windows_hello()` in `windows-setup.md` are cited as **deleted** and **not yet built**
respectively, which is correct usage of a name that does not resolve.

### Status

`DOCB-R1…R6` raised and closed. The 18 Phase 1 `DOCB` slots are **written off, not closed** —
their claims cannot be recovered and this sweep is what stands in their place. The register at
the top of this report is updated accordingly.

Gates: ruff, ruff format, mypy, pytest **1,459 passed**, `pytest -m security` **241 passed**.

*(The write-up first stated 1,445 from memory rather than from the run — corrected to the
measured figure. The same slip, in the section about a file whose numbers were never
re-measured.)*

---

## Phase 3 — `DOCA` re-derived (session 9)

Same method as `DOCB`, applied to the five high-risk documents (`SECURITY.md`, `CLAUDE.md`,
`README.md`, `docs/security-architecture.md`, `docs/tools-reference.md`). The 15 unwritten
`DOCA` slots are **written off**; `DOCA-R1…R3` replace them, plus one API finding the sweep
turned up.

### The sweeps found far less here, and that is the result

`SECURITY.md` and `docs/security-architecture.md` produced **no findings**. Every name the
identifier sweep flagged in them is cited *as deleted or as absent*, which is correct usage:
the `_scrape_with_fallback` family sits under an explicit "Restructured 2026-07-30 … that
ladder and all three functions were deleted" note; `tickler.sh` is described as having left the
image on 2026-08-06 and the tree on 2026-08-07; `outputSchema` appears in the sentence "none
declares an `outputSchema`"; `dependabot.yml` is a recorded decision *not* to have one. The
`conf.yaml` keys `listenSsl`, `sslPwd` and `cors.allowCredentials` all exist — **my sweep read
`.yml` and not `.yaml`**, which is a blind spot in the checker and not a defect in the
document.

`CLAUDE.md`'s package-structure block was diffed against the tree in both directions: **nothing
listed that does not exist, nothing in the tree left out.**

### Findings

| ID | Sev | Finding |
|---|---|---|
| `DOCA-R1` | Medium | `docs/tools-reference.md:504` documents `get_trading_schedule`'s output with two field names IBKR does not return |
| `DOCA-R2` | Low | `README.md:361` says the live web suite is 11 tests — the **third** site of `DOCB-R3`, missed when the first two were fixed |
| `DOCA-R3` | Low | `CLAUDE.md:46` says `tests/test_mcp_server.py` is 17 tests; it collects **25** |
| `API-R1` | Medium | `client.get_trading_schedule` could not send `conid`, which IBKR documents as **Required** |

#### DOCA-R1 / API-R1 — one line of documentation, two defects behind it

`tools-reference.md` promised the tool returns "JSON with `regularTradingHours`, `liquidHours`,
`timezone`, and next/current session". The handler is a `json.dumps` passthrough, so that is a
claim about IBKR's shape, and it had never been checked against IBKR. Fetched with a fabricated
control in the same batch (real page 2,982 B and no `# Page Not Found`; control 433 B and
`# Page Not Found` present):

| Promised | In IBKR's documented response object |
|---|---|
| `regularTradingHours` | **0 occurrences** |
| `liquidHours` | **0 occurrences** |
| `timezone` | 1 — real |

The real shape is `id`, `tradeVenueId`, `timezone`, `schedules[]`, each carrying `sessions[]`
(`openingTime`, `closingTime`, `prop`) and `tradingtimes[]` (`openingTime`, `closingTime`,
`cancelDayOrders`). A model told to look for `regularTradingHours` finds nothing and has no way
to know why.

Reading that same page for the response shape showed the request was wrong too: **`conid` is
marked Required** and this client had no way to send it. The one live capture of this endpoint
in the fixture is `trading_schedule: []`.

**The cause of the empty response is deliberately not claimed.** IBKR's own curl example on
that page omits `conid` while its Python example includes it, and no gateway was reachable to
settle it. What is established is that a documented-Required parameter was unsendable; that is
what was fixed, with two tests (sent when supplied, absent when not — an empty `conid=` would
be worse than none) and two mutants, both caught. **Live confirmation is owed.**

#### DOCA-R2 — the same defect, a third time, missed by me in this session

`DOCB-R3` found the live web suite documented as 11 tests when it collects 12. I fixed
`docs/web-scraper-reference.md` and `CLAUDE.md` — and `README.md:361` carried it too. I found
it only because the numeric sweep was run again over a different document set.

Two fixes applied to two branches of a defect class and the third left, in the session whose
own write-up calls that the recurring pattern. It is recorded here rather than quietly
corrected because the failure is the interesting part: **"fix the class" is not satisfied by
fixing the instances you happened to have open** — it requires re-running the check that found
the first one.

### Status

`DOCA-R1…R3` and `API-R1` raised and closed, `API-R1` pending live confirmation. The 15
Phase 1 `DOCA` slots are written off.

---

## Phase 3 — `DATA-03…19` re-derived (session 9)

The last unrecorded block. Seventeen slots: three marked "(see full report)" and fourteen
with empty claim cells. Written off and replaced by `DATA-R1…R5`.

### Method: mutation, not reading

The two precedents in this domain both found their defects by **changing the code and seeing
whether anything failed**, never by reading it — the indicator sweep (six findings behind
thirteen tests that could not detect a wrong formula) and the analytics sweep (`DATA-25`).
So 21 plausible defects were introduced across `analytics.py`, `backtest.py`, `cache.py`,
`store.py`, `flex_import.py` and `pinescript.py`, each run against the **whole** unit suite.

### The harness lied, and a no-op control is what caught it

The first battery reported *every* mutation as caught. The harness took its test selection as
one shell string, `"tests/ -m 'not integration'"`, and word-splitting handed pytest a literal
`'not` as the marker — so **pytest errored out on every run, and a non-zero exit was read as
"the mutation was caught"**. Fifteen results were fabricated, including four that this report
would otherwise have recorded as evidence that `cagr` and `calmar` were well covered.

It was found by a deliberate **no-op mutation** — appending `# noqa` to a `def` line — which
cannot change behaviour and must therefore survive. It was reported caught. That is the only
reason the battery was re-run.

The harness now distinguishes three outcomes, not two: tests failed (caught), tests passed
(survived), and *pytest itself did not run* (discarded). It also refuses to report when the
mutation text was not found — the failure mode that produced a false survivor in the SEC-13
work earlier the same day, where `ruff format` had re-flowed a `frozenset` between writing a
`sed` and running it.

**Three instances of the same shape in one session**: a control that imported its oracle from
the code under test (SEC-13), a mutation that never applied (SEC-13), and a harness that
scored a crash as a pass (here). The audit's recurring finding is *a control that cannot
fail*; these are the auditor's own.

A second lesson, cheaper: the backgrounded battery was killed mid-mutation and **left a mutant
in the working tree**. `git diff` after every battery is now part of the procedure.

### Findings — all five are metrics with no value pinned

| ID | Sev | Finding | Measured |
|---|---|---|---|
| `DATA-R1` | **High** | `sharpe` does not de-annualise `risk_free` — untested because every test passes the default `0.0` | at 4%: correct −2.36, mutant **−70.93** |
| `DATA-R2` | Medium | `sharpe`'s `ddof` unpinned — population vs sample stdev | ratio exactly `sqrt(n/(n−1))`; **5.4%** at n=10 |
| `DATA-R3` | **High** | `cagr`'s years denominator and exponent both unpinned | 0.2493 → **0.5608** / **6.4149** |
| `DATA-R4` | **High** | `calmar` entirely unpinned — *multiplying* by drawdown instead of dividing survives | 0.6462 → **0.0258** |
| `DATA-R5` | **High** | `backtest.expectancy` and `profit_factor` unpinned; inverted profit factor survives | 4.0 → **0.25**, which reads as a losing system |

`DATA-R1` and `DATA-R3` are the **same defect class as DATA-02** — the Critical where
`run_backtest` annualised intraday Sharpe with `periods=252`. `DATA-R2` is the same class as
`DATA-21`, where the Bollinger band width was out by exactly `sqrt(20/19)`. Both classes were
fixed at one site and never swept.

`DATA-R4` is the sharpest: `cagr(returns, periods) * abs(mdd)` instead of `/` survived 1,469
tests. It stays positive and preserves the ordering between strategies, so nothing about it
looks wrong — it simply is not the Calmar ratio.

`DATA-R5`'s inverted profit factor is the same shape. 4.0 becomes 0.25, and **1.0 is the
threshold a reader uses to decide whether a system makes money**, so the error changes the
conclusion rather than the magnitude.

### What the 2026-09-16 analytics sweep had already said

That sweep wrote: *"every test for `sharpe`, `max_drawdown`, `cagr` and `calmar` was a shape or
sign assertion … Only `sortino` had ever been pinned to an outside worked example."* It named
four metrics, fixed the one that was **wrong** (`max_drawdown`, DATA-25), pinned that one to
Investopedia — and left the other three unpinned, because they were *correct*. Correct and
unpinned is exactly the state this audit keeps finding; the sweep diagnosed the class and
treated one instance.

All three are now pinned to published references: `sharpe` to Wikipedia's Example 2
(12% return, 10% σ, 5% risk-free ⇒ **0.7**), `cagr` to Investopedia's (10,000 → 19,500 over
three years ⇒ **24.93%**) plus the identity that a constant annual return of x gives a CAGR of
exactly x, and `calmar` to a hand-computed −20%/+50%/+20% path (CAGR 0.1292432, drawdown
−0.20, ⇒ **0.6462162**), which also re-exercises DATA-25's starting-capital peak.

### Verified correct and well covered

Not everything was unpinned, and the mutants say which: `cache.check`'s one-day staleness
window, `flex_import`'s row-uid occurrence counter and its refusal to accept a trade with
neither `ibExecID` nor `tradeID`, `pinescript._sanitize`'s length cap, `store`'s 45-day gap
threshold, and `backtest`'s `win_rate` and `total_return` all fail a mutation immediately.

### Status

`DATA-R1…R5` raised and closed. Eleven mutants caught after the fixes, zero survivors. The 17
Phase 1 `DATA` slots are written off.

Gates: ruff, ruff format, mypy, pytest **1,474 passed**, `pytest -m security` **241 passed**.
