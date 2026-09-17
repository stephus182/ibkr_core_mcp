# ibkr_core_mcp — Developer Guide

Standalone pip-installable Python package providing a complete IBKR Client Portal API client, Google Drive parquet cache, SQLite store, backtest sandbox, technical indicators, portfolio analytics, Claude AI tool layer, and PineScript generation utilities.

**Design spec:** `docs/plans/2026-05-22-ibkr-core-mcp-design.md`

---

## Install

```bash
# From GitHub (any consuming project)
pip install git+https://github.com/stephus182/ibkr_core_mcp.git

# Pinned version
pip install git+https://github.com/stephus182/ibkr_core_mcp.git@v1.0.0

# Local editable dev
pip install -e /path/to/ibkr_core_mcp
```

## Dev Setup

```bash
cd /path/to/ibkr_core_mcp
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,server]"
git config core.hooksPath .githooks   # the four CI gates as a pre-push hook (see Linting & Type Checking)
```

**Editable-install mode matters.** `pip install -e .` installs setuptools' *lenient* mode: the
`.pth` finder maps `ibkr_core_mcp` to the source directory and new modules are visible at once.
A *strict*-mode install (`--config-settings editable_mode=strict`) instead builds a tree of
per-file symlinks under `build/__editable__…/` and a module added afterwards is invisible to any
interpreter not started from the repo root — on 2026-09-13 that hid a new module from a probe
script until the package was reinstalled. If a script outside the repo cannot import something
that exists, check `site-packages/__editable___*_finder.py`'s `MAPPING`, reinstall, and delete
the stale `build/` tree.

**Python:** 3.11+ required. Use Homebrew Python on macOS (`brew install python`) — invoke the
versioned binary (`python3.11 -m venv`), not bare `python3`, since Homebrew may resolve that
to a newer, unsupported interpreter.
**Package manager:** `brew install` for macOS tooling, `pip install -e ".[dev,server]"` for
Python deps. The `server` extra (`mcp`, `starlette`, `uvicorn`) is not optional for a full
local test run — `tests/test_mcp_server.py`'s 25 tests fail to collect without it, even
though `mcp_server.py` itself is a separate entry point from the rest of the package.

## Running Tests

```bash
pytest -m "not integration"                            # unit tests only, no gateway/Drive/IBKR needed
pytest                                                  # all tests, requires live IBKR gateway + .env
pytest tests/test_indicators.py -v                      # specific module

# Targeted claude_tools subsets — see tests/claude_tools/TEST_INDEX.md
pytest tests/claude_tools/                              # all claude_tools unit tests
pytest tests/claude_tools/ -m "not integration"          # same, explicit
pytest tests/claude_tools/test_flex.py                   # one domain file
pytest -m orders                                         # one domain, repo-wide
pytest tests/claude_tools/test_tool_descriptions.py      # schema/description honesty only

# Security regression suite — the eleven properties of SECURITY.md § Security Regression Suite,
# each read from the source or driven with canaries; ~10 s. Part of the unit run and of CI.
pytest -m security

# Web tools — a LIVE run is mandatory before calling any scraper change done.
# 12 tests, ~28s. Skips cleanly without the [scraper] extra or a Firecrawl key.
pytest tests/test_web_tools_live.py -v -m integration
```

**A new guard is not a guard until you have watched it fail.** This audit repeatedly found
tests that could not fail — one read its own oracle from the code under test, another asserted
a handler had been *registered* rather than that it worked. `scripts/audit/mutation_battery.py`
breaks the thing a test watches and requires the test to catch it; it refuses to report a
result when the mutation did not apply, when pytest never ran, or when the unmutated control
is not green, because each of those has already produced a wrong answer here — an earlier
ad-hoc version **fabricated 15 results**, hiding two genuinely unpinned functions. Drive it
from a throwaway script (usage is in its docstring); `tests/scripts/test_mutation_battery.py`
proves the harness itself before you trust it.

**The web scraper does not get to be "done" on a green unit suite.** Every defect in the
2026-07-30 rewrite was found by running a tool, never by a test failing — four in one
session, each behind a passing suite; and before that `create_profile` shipped with three
green tests having never been executed, then broke on its first real run for three separate
reasons. The mocks were weaker than the dependency each time (a fake seeder scores a miss
0.0; the real one scores it 0.5). Run the live suite and record the result in
`docs/web-scraper-reference.md` §11. Full procedure: §10 of that file.

## Linting & Type Checking

```bash
ruff check .              # lint — must be clean
ruff format --check .     # formatting — must be clean
# The ruff rule set (`[tool.ruff.lint]` in pyproject.toml) is identical to claudia_ui's,
# aligned 2026-09-08 — change it in both repos or in neither.
mypy                      # type check — must be clean (files= covers ibkr_core_mcp/, tests/ and scripts/)
```

**Run the whole line before pushing, in this order — CI's test job runs these four steps and
stops at the first red one; two further jobs (`dependency-audit`, `secret-scan`) run in parallel
and need the network, so they are CI-only.** Run 34082479743 (2026-09-07) failed at `ruff format --check` on four
files, and that red step hid two real mypy errors CI never reached; they surfaced only when
the formatting was fixed. A green `ruff check` says nothing about `ruff format`, and a red
`ruff format` says nothing about mypy or pytest. The same four steps, in the same order, are
claudia_ui's CI (`.github/workflows/ci.yml` in both repos, aligned 2026-09-08; the two
2026-09-13 jobs exist here only — claudia_ui's file still mirrors the four-step test job), and
they are `.githooks/pre-push` in both repos, which refuses a push that would go red — enabled once per
clone by `git config core.hooksPath .githooks` (Dev Setup); `git push --no-verify` bypasses it
on purpose. Branch protection cannot do this for a direct-push workflow: a required status
check rejects every push whose commit has not already passed CI, which a direct push never has.

**No gate command may be piped.** `$?` is the exit status of the *last* command in a pipeline
and `pipefail` is off by default, so `pytest … | tail -1` exits **0 on a red suite** — measured
here in both `zsh` and `sh`. On 2026-09-16 that exact line, joined by `&&`, carried the rest of
a commit chain through a red suite; `.githooks/pre-push` is what stopped it leaving the machine,
and the commit was amended (`0ea4a09`). The same trap reported a failed CI run as green on
2026-09-13 — see *Reading a CI run* below, which is the same rule applied to `gh run watch`.
Run each gate bare and read its status, or redirect first and read the file:
`pytest -m "not integration" -q > out.txt; ec=$?; tail -3 out.txt`. Never `gate | filter`, and
note that `&&` between gates hides this rather than catching it: a masked 0 lets the chain
continue.

**Run the four as four separate commands, each status read on its own — not an `&&` chain.**
`&&` stops at the first red, so three real errors cost three round trips to find instead of
one. Measured 2026-09-17: a single bare pass surfaced `ruff check`, `ruff format` and `mypy`
failures *together*, in code written minutes earlier; chained, it would have reported one,
then one, then one. `.githooks/pre-push` deliberately stops at the first failure (its `run()`
helper exits) — that is correct for a gate whose job is to refuse, and it is why the hook is
not a substitute for running the line yourself while you still have work to fix. The same
shape is already recorded above for CI: run 34082479743 failed at `ruff format --check` and
that red step hid two real `mypy` errors CI never reached.

**Two more gates run in CI only** (they need the network): `pip-audit` over a **fresh resolve**
of `.[dev,server,scraper]` — requirements mode, `pip install --dry-run` in a throwaway venv,
installing nothing — weekly as well as per push, with ignores only from
`security/pip-audit-ignores.txt`. Auditing the *installed* tree instead reports what this
machine happens to have and is not what CI checks; that difference produced a near-miss on
2026-09-16. Reproduce CI exactly with the command in `.github/workflows/ci.yml`. And
`gitleaks` over the pushed range, configured by `.gitleaks.toml`. Neither is in the pre-push
hook. Added 2026-09-13; the reasoning is in
`docs/audits/security-architecture-audit-2026-09-13.md` § Phase 3.

`[tool.mypy]` runs `strict = true` against `ibkr_core_mcp/` and `scripts/`. `tests/` is also checked
(`files = ["ibkr_core_mcp", "tests", "scripts"]`) but under a narrower `tests.*` override that relaxes
only `disallow_untyped_defs`/`disallow_incomplete_defs`/`disallow_untyped_calls` — this
codebase's tests carry zero signature annotations by established convention, and demanding
them would be a large, low-value diff. Every other strict check, including body-level
`check_untyped_defs`, still runs against test code. See
`docs/audits/2026-07-22-code-quality-audit.md` for the full rationale and a worked example of
the override in practice (981 boilerplate findings configured away, 183 real ones fixed).

**Docstring coverage is enforced.** `ruff`'s `pydocstyle` rules (`D`) are enabled, so every
public module, class, method, function, and `__init__` in `ibkr_core_mcp/` must carry a
docstring or the lint fails. Enabled 2026-07-25 after a pass found 39 undocumented public
definitions — including `IBKRClient.__init__`, which is what pins the TLS-verify-off exemption
to localhost. `claudia_ui` adopted the same configuration on the same date, so both repos
enforce one rule.

Only the *coverage* (`D1xx`) rules are enforced. The formatting-opinion codes are disabled
because they conflict with this codebase's house style — multi-paragraph docstrings that
explain *why* and cite source URLs. `pyproject.toml`'s `ignore` list annotates each one; the
notable pair is `D212`/`D213`, which are mutually exclusive: this codebase opens the summary
on the **first** line (346 docstrings do, versus 36 that did not and were normalised), so
`D213` is ignored. Write new docstrings that way. `tests/*` and `scripts/audit/*` are exempt
from `D` only — test names are the documentation, and the audit scripts are evidence
artifacts committed as run, not maintained code.

## Publishing a New Version

```bash
git tag -l --sort=-v:refname | head -1    # check current latest tag first — don't reuse one
git tag vX.Y.Z                             # semver — bump patch/minor/major as appropriate
git push origin vX.Y.Z
```
Consumers pin to: `pip install git+https://github.com/stephus182/ibkr_core_mcp.git@vX.Y.Z`

**Reading a CI run.** `gh run view <id> --json conclusion,jobs`, or `gh run watch <id>
--exit-status` with **no pipe** — `… | tail` returns `tail`'s exit status and reported a failed
run as green on 2026-09-13. The two GitHub-side scanners (CodeQL default setup, Dependabot
alerts) run outside `ci.yml` and are not merge gates; what each can and cannot see is in
`docs/security-architecture.md` § 7.

---

## Environment Variables

Create `.env` in any consuming project (not in this repo):

```
IBKR_GATEWAY_URL=https://localhost:5055/v1/api
GOOGLE_DRIVE_FOLDER_ID=1abc...xyz
IBKR_SQLITE_PATH=~/.ibkr_core/store.db
GDRIVE_TOKEN_FILE=~/.ibkr_core/token_ibkr_core_mcp.json
GDRIVE_CREDENTIALS_FILE=~/.ibkr_core/credentials_ibkr_core_mcp.json
```

**Standalone dev exception:** with no `.env` here, `firecrawl_search` correctly reports
"not configured" and never touches Drive — by design, not a bug, since
`Config.from_env()` reads empty strings. To exercise Drive caching while developing
ibkr_core_mcp in isolation (not inside a consuming project), a local `.env` **in this
repo** is fine — it's gitignored and never committed. Only 4 vars are needed (no
`GOOGLE_DRIVE_FOLDER_ID` required): `FIRECRAWL_API_KEY`, `GDRIVE_WEB_DOCS_FOLDER_ID`
(an existing `web_docs/` folder ID), `GDRIVE_TOKEN_FILE`, `GDRIVE_CREDENTIALS_FILE`
(reuse an already-authenticated token to skip interactive OAuth). Verify with:

```bash
set -a; source ./.env; set +a
pytest tests/test_web_scraper_dev_cache_live.py tests/test_web_scraper_drive_live.py -v -m integration
```

Those four vars are enough for **every** live scraper test, `GOOGLE_DRIVE_FOLDER_ID`
included-by-omission: `WebDocsStore` accepts either root. It did not used to be — the
Drive live fixture demanded `GOOGLE_DRIVE_FOLDER_ID` specifically, so both of its tests
skipped on every default run here, silently, and a rewritten test went unverified for
hours (2026-07-30). If you add a live test, require only what the code requires.

**Web scraper env vars** (all optional; each disables a feature rather than raising):

| Var | Effect if unset |
|---|---|
| `FIRECRAWL_API_KEY` | `firecrawl_search` reports "not configured". The other three web tools are unaffected — they need no key. |
| `CRAWL4AI_PROFILES_DIR` | Defaults to `~/.ibkr_core/crawl4ai_profiles` (paywalled-site logins) |

**`IBKR_AUTH_BROWSER`** (optional, default `chrome`) selects which browser's cookie store
`BrowserCookieAuth` reads the localhost session from. It is read from `os.environ` inside
`BrowserCookieAuth.__init__` — the single point of construction — so all three paths honour
it: `IBKRClient`'s default auth, `mcp_server`'s stream path, and `claude_tools`' P&L
WebSocket. **Until 2026-09-17 only the last of the three did** (audit finding API-10): the
other two constructed the class bare and got Chrome, so an operator on Firefox had a working
P&L subscription and an unauthenticated session everywhere else, reported as "no localhost
cookies found in chrome" — a browser they had not chosen. `Config` deliberately does not
carry it, so there is nothing to thread through.

It accepts exactly five names — `chrome`, `chromium`, `firefox`, `safari`, `edge` — and
raises `ValueError` naming the offending source on anything else. **This paragraph said
"any `browser_cookie3` backend name" until 2026-09-17, and that was wrong** (API-R2):
measured, the library ships 14 backends and this allow-list admits 5, so `brave`, `arc`,
`opera`, `opera_gx`, `vivaldi`, `librewolf`, `lynx` and `w3m` are all refused. The list is
closed on purpose — the name reaches `getattr(browser_cookie3, …)`, so it is validated
before it can get there. Widening it is a deliberate decision about auth surface, not a
typo fix.

`CRAWL4AI_PROFILES_DIR` is the **only** Crawl4AI setting. A `CRAWL4AI_API_KEY` /
`CRAWL4AI_API_URL` pair configured a hosted rung that was removed on 2026-07-28 (§5.1 of
`docs/web-scraper-reference.md`); either variable is now simply ignored.

Never commit `.env` or any GDrive OAuth credential/token file (e.g. `credentials_ibkr_core_mcp.json`, `token_ibkr_core_mcp.json`). Never print an API key in logs, errors or test output.

---

## Package Structure

```
ibkr_core_mcp/
├── __init__.py           # Public API — import everything from here
├── auth.py               # Auth strategies: BrowserCookieAuth, TokenAuth, NoAuth
├── client.py             # The IBKR Client Portal API surface (see its module docstring for the count)
├── models.py             # Pydantic v2 schemas for all response types
├── exceptions.py         # Custom exception hierarchy (IBKRCoreError → subclasses)
├── cache.py              # Google Drive parquet cache (market data, shared cross-machine)
├── store.py              # SQLite store (trades, signals, backtest results, positions)
├── flex_query.py         # FlexQueryClient — Flex Web Service historical trade sync (T+1, unlimited history)
├── flex_schema.py        # GENERATED by scripts/audit_flex_xml.py — every attribute IBKR emits, as columns
├── flex_import.py        # Parse a Flex statement into the flex_* tables; refuses on unknown attributes
├── flex_store.py         # SQLite writer for the generated flex_* schema
├── backtest.py           # RestrictedPython sandbox executor
├── indicators.py         # Technical indicators (RSI, MACD, BB, ATR, VWAP, OBV, ...)
├── analytics.py          # Performance metrics (Sharpe, Sortino, Calmar, drawdown, ...)
├── claude_tools.py       # Claude tool definitions + handlers (44 tools, portable; each declares `capabilities`)
├── redaction.py          # redact_error — the one path for exception text the model layer shows or logs
├── mcp_server.py         # MCP server (stdio + SSE transports) — 46 tools, 4 resources
├── human_auth.py         # Gate 1: Touch ID / Face ID biometric authentication
├── order_confirm.py      # Gate 2: builds the confirmation dialog + side extraction
├── _order_dialog.py      # Gate 2's display subprocess — AppKit modal, colour-coded banner
├── streaming.py          # IBKRWebSocket — live quotes, execution/P&L push; AlertManager
├── web_scraper.py        # FirecrawlClient (whole-web search) + WebDocsStore — Drive snapshots
├── local_browser.py      # Crawl4AI local browser (Playwright) + SSRF guard — fetch/crawl/search a site
├── pinescript.py         # PineScript v5 generation from strategies and indicators
├── rate_limiter.py       # Proactive per-endpoint pacing (sliding window) + backoff on 429
├── config.py             # Config dataclass loaded from environment variables
├── gdrive_auth.py        # Shared Google OAuth token/refresh helper (used by cache + web_scraper)
└── gateway/
    ├── __init__.py
    ├── manager.py        # GatewayManager — Docker lifecycle, auth polling
    ├── Dockerfile        # eclipse-temurin:21 + IBKR Client Portal zip
    ├── conf.yaml         # Gateway config (port, SSL, CORS, IP allowlist)
    ├── run_gateway.sh    # Entrypoint: start the Java process and wait — nothing else
    └── healthcheck.sh    # curl GET readiness probe used by run_gateway.sh's wait loop
```

Basic object setup used throughout the codebase (`Config`, `IBKRClient`, `GDriveCache`,
`SQLiteStore`) and all per-module usage examples: `docs/api-usage-examples.md`

---

## Security & Fingerprint Authentication

**ALL order write operations require two sequential human validations. There is no bypass.**

Every call to `place_order`, `modify_order`, `cancel_order`, or `reply_order` must pass
both gates — in order — before **any order-write request** reaches IBKR.

This read "before any network call reaches IBKR" until 2026-09-16 and that was wrong: on a
fresh session each of the four opens with `_ensure_accounts_initialized()`, which issues
`GET /iserver/accounts` — IBKR's documented prerequisite for order operations — before
Gate 1. The ordering is deliberate (`test_place_order_initializes_accounts_before_touch_id`
requires it by name) so a dead session fails fast rather than after two human gates.
Measured with Gate 1 denying: one GET on a fresh session, zero once initialised, and
**zero order writes either way** (audit finding SEC-02).

`place_order_and_confirm` / `modify_order_and_confirm` take **one Touch ID for the whole chain** and show **a dialog for every chained reply**. The fingerprint is taken once, up front, and mints an `OrderWriteAuthorization` bound to the SHA-256 of that write's own account and body (300 s, frame-local, expiring closed; the account joined the scope on 2026-09-17, audit finding SEC-07); the write and every chained reply re-check *that* value instead of prompting again, and Gate 2 runs unskipped at each step. This is the 2026-09-11 rule — IBKR Mobile and TWS also ask once per placement — and it is stated correctly in `SECURITY.md` § Two-Gate System and `docs/security-architecture.md` § 6.1. **This file said "the same two gates again for every chained reply" until 2026-09-14**, which was wrong about Gate 1 and right about Gate 2. Full usage examples: `docs/order-management-examples.md`

| Gate | Mechanism | Behaviour |
|---|---|---|
| **Gate 1 — Touch ID** | Apple `LocalAuthentication` (`LAPolicyDeviceOwnerAuthentication`) | Touch ID/Face ID first, falls back to the device's system password on a failed/cancelled biometric scan. 60-second timeout. |
| **Gate 2 — Visual confirmation** | On macOS an AppKit `NSAlert` in a subprocess (`osascript` if that fails); a `tkinter` modal elsewhere. Full order details + live-order disclaimer | Explicit mouse click required. Enter key does not confirm. |

If either gate fails (denied, timeout, cancelled), `HumanAuthError` is raised immediately and no order is placed, modified or cancelled.

One deliberate exception, and it is not an execution path: a reply declined inside
`place_order_and_confirm` / `modify_order_and_confirm` POSTs `{"confirmed": false}` to tell IBKR
the human said no, and only then raises (`_resolve_one_reply`). The standalone `reply_order`
contacts nothing on a decline.

**Gated endpoints:**

| Method | Gates |
|---|---|
| `place_order` | Touch ID → confirm dialog |
| `place_order_and_confirm` | One Touch ID for the whole chain, taken here — so `place_order` does not prompt a second time — then its confirm dialog, then a reply dialog per chained reply (showing the real IBKR message), until a terminal response |
| `modify_order` | Touch ID → modify dialog |
| `modify_order_and_confirm` | The same, for modify: one Touch ID for the chain, then the modify dialog, then a reply dialog per chained reply, until a terminal response |
| `cancel_order` | Touch ID → cancel dialog |
| `reply_order` | Touch ID → reply dialog |

`place_order_and_confirm` / `modify_order_and_confirm` are the recommended entry points — a single IBKR order can require multiple chained replies before reaching a terminal state, and these methods resolve the whole chain safely. `place_order` / `modify_order` / `reply_order` stay available for callers who want manual control over each step.

**Explicitly ungated.** What these share is not that they read — it is that none can place,
modify, cancel or confirm an order. They are *not* all read-only.

*Read-only and simulation:*

| Method | Reason |
|---|---|
| `get_order_preview` | IBKR `whatif` — simulates, never executes |
| `get_live_orders` / `get_order_status` / `get_orders_raw` | Read-only |

*Ungated non-order `ACCOUNT_STATE` mutations* — real writes to IBKR's servers, ungated
deliberately because a price notification is not an execution path:

| Method | What it changes |
|---|---|
| `create_alert` | `POST` — creates a price alert (given an existing alert id, modifies it) |
| `delete_alert` | `DELETE` — removes a price alert permanently |
| `activate_alert` | `POST` — enables or disables an existing alert |

The three alert writes were listed as "read-only, no execution risk" until 2026-09-14, while the
capability registry had them correctly as `ACCOUNT_STATE` all along (`SECURITY.md` § Capability
declarations). Documentation only — no gate or classification changed.

**Rules for contributors:**

- Never add a bypass flag, session cache, or library-side fallback to `require_touch_id` or any dialog function — no code path may skip or cache a prior Touch ID / dialog success.
- Never move the gates out of `IBKRClient` — enforcement must be at the innermost call site.
- The required policy is `LAPolicyDeviceOwnerAuthentication` (Touch ID/Face ID, falling back to the device's system password on a failed/cancelled biometric scan) — Apple's own recovery path for a genuinely-failed biometric read, not a bypass this library adds. The stricter biometrics-only policy was evaluated and rejected: a failed scan under it has no recovery path at all. Don't change this policy without updating both this file and `README.md`'s Security section in the same PR.
- Any PR that weakens these gates *beyond* the documented policy above — e.g. skipping `require_touch_id`/`confirm_order_dialog` entirely, caching a prior success, or adding a fallback beyond the OS's own password prompt — will be rejected.
- **The boundary is machine-checked** (2026-09-13): `tests/security/test_order_write_boundary.py` reads `client.py` and fails if an order-write endpoint is built anywhere but the gated methods, if a gated method reaches the network before a gate — directly or through a helper, with
  `_ensure_accounts_initialized` the one exemption, named and reasoned in the test — or if `claude_tools.py`/`mcp_server.py` name an order-write method, `_post`, `_session` or `OrderWriteAuthorization`. A new tool with side effects must declare them in its `capabilities` set, and no tool may declare `ORDER_EXECUTION` (`tests/security/test_tool_capabilities.py`). The full list of held properties: `SECURITY.md` § Security Regression Suite; the audits that produced them: `docs/audits/security-architecture-audit-2026-09-13.md` (invariants 1–10) and `docs/audits/owasp-mcp-guide-applicability-2026-09-14.md` (invariant 11, and the SSE bearer token in 10).

---

## Gateway Authentication & Session

The IBKR Client Portal Gateway must run on the **same machine** as the browser used to authenticate — no cloud deployment possible. `BrowserCookieAuth` (default) reads Chrome's cookie store for `localhost`; start it via the built-in `GatewayManager`. Session expires without activity — call `client.tickle()` every 60s to keep it alive. Rate limit 10 requests/second globally, with much stricter per-endpoint limits — see `docs/gateway-auth-reference.md`. Handled transparently by `rate_limiter.py`, which since 2026-09-16 **paces proactively** (`EndpointPacer`, sliding window, limits in `ENDPOINT_LIMITS`) as well as retrying 429s. Exceeding a limit costs a fifteen-minute penalty box on the IP across every endpoint, so prevention is the part that matters. Full login walkthrough, `GatewayManager` code, and headless `TokenAuth` usage for batch jobs: `docs/gateway-auth-reference.md`

---

## Conventions

- **API Docs First**: never assume IBKR endpoint behavior, error codes, field names, or URL
  paths from memory or training data. Always verify against official documentation before
  writing any code, error message, or diagnosis. This rule exists because assumption-based
  development caused two confirmed incidents in this codebase:

  | Incident | Assumed | Actual | Cost |
  |---|---|---|---|
  | Flex error 1001 | "rate limit — wait 5 min" | Transient generation failure — retry | Multiple failed sync attempts, misdiagnosed |
  | Flex endpoint URL | `gdcdyn.interactivebrokers.com/Universal/servlet/...` | `ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/` | Flex API never worked from day one |

  **Protocol:** Use `WebFetch` to load the relevant doc page before writing any fix, error
  message, or new endpoint. Cite the source URL in the commit message. Full official-doc
  URL tables (Client Portal, Flex, WebSocket, Drive, LocalAuthentication, web scraping):
  `docs/external-docs-reference.md`. Verified (not assumed) IBKR API behaviors already documented:
  `docs/ibkr-api-behaviors-reference.md`

  **IBKR moved their Web API docs (discovered 2026-07-25).** The old single-page reference at
  `interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/` is now a Fern-hosted site at
  **`ibkrcampus.com/docs/web-api/`**. The 2026-07-25 pass repointed 81 links but **missed 118
  more**, `client.py` alone holding 75; those were repointed 2026-08-05 against the site's own
  `llms.txt` index, and the count here is deliberately not restated as "all of them" — the last
  claim of completeness was wrong. Surviving `cpapi-v1` URLs live **only in dated audit
  artifacts** — `docs/audits/audit-evidence/scrapes/` (the captures themselves, plus their
  manifest), `docs/audits/2026-06-30-quote-access-matrix.md` and
  `docs/audits/claude-tools-audit-2026-07.md`. Those are evidence of what was retrieved on a
  given day, not citations, and rewriting them would falsify the record. No file under
  `ibkr_core_mcp/`, `tests/`, or the living docs cites one. (This paragraph previously named
  a single evidence file as "the only surviving cpapi-v1 text"; eight files contained it —
  a completeness claim that was itself wrong, in the paragraph warning about completeness
  claims.) **IBKR moved a second time, and this one changed the path, not the host (found
  2026-08-11).** The endpoint prefix `docs/web-api/web-api-v-1-0-documentation/…` is superseded
  by `docs/web-api/v1/…`, and the WebSocket segment `websockets/` is now `ws/`. 93 links were
  repointed across the living docs, `client.py`, `streaming.py`, `test_client.py` and
  `README.md`; each target was confirmed present in `llms.txt` before rewriting and then
  live-fetched (72/72 real). Surviving old-prefix strings are prose warnings and `docs/plans/`
  records, not links. **Cite the `v1/` form.**

  Four things to know before citing a source URL again:

  - **The HTML page cannot tell you whether a page exists — only the `.md` variant can.** The
    site is JavaScript-rendered, so fetching the HTML of a real page and of a URL invented on
    the spot returns **byte-identical empty output**. Appending `.md` discriminates cleanly
    (~6,400 B for a real page vs ~1,000 B `# Page Not Found`), but *only on the `v1/` prefix* —
    `.md` on the old prefix fails even for a page that genuinely exists. Always run a
    deliberately-fabricated control URL in the same batch: it is the only proof your check can
    still fail, and a check that cannot fail found "73 of 74 links broken" here on a parser bug.
  - **`llms.txt` membership proves existence but its absence proves nothing.**
    `docs/web-api/changelog` is real (11,686 B, confirmed live) yet is not in the index. When
    the index is silent, `firecrawl_search` settles it — whole-web search is the one job the
    local browser structurally cannot do.
  - The old URLs **still return HTTP 200** — they redirect to the new site's Introduction page
    and *silently drop the `#anchor`*. A link checker reports success while the reader lands
    on the wrong page. Never re-add a `cpapi-v1/#…` link; a 200 is not evidence it works.
  - **The new site also answers 200 for pages that do not exist.** A made-up path returns a
    ~290-byte body reading `# Page Not Found`, so a status check cannot tell a real page from a
    typo — a first verification pass here graded 74 URLs "resolving" on status alone and was
    worthless. Check that the URL appears in `llms.txt`, or that the body lacks
    `# Page Not Found`. Byte-size is a weak proxy: real pages can be short (`unread-bulletins`
    is 576 B).
  - The new site is AI-friendly, which makes verification cheap: append **`.md`** to any page
    URL for clean markdown, and **`https://www.interactivebrokers.com/docs/web-api/llms.txt`**
    is the complete page index (469 unique .md URLs measured 2026-08-07, **re-measured 2026-08-11: still 469**; it said "517-page" from an earlier, unverified count). Note the index lists its URLs on the `ibkrcampus.com` host while the docs cite `www.interactivebrokers.com` — both serve the same pages, so compare by *path*, not by full URL. There is also an MCP server at
    `https://ibkrcampus.com/docs/web-api/_mcp/server`. Prefer these over scraping the HTML — they
    cost no Firecrawl credits and cannot be edge-blocked. If you do scrape, the recovery ladder
    is gone: as of 2026-07-30 there are **four web tools, one job each, and no fallback
    between them**. Anything with a URL goes to the free local browser — `fetch_page` (one
    page), `crawl_site` (archive a site to Drive), `search_site` (find pages on one site,
    BM25-ranked). Firecrawl keeps exactly one job, `firecrawl_search`, because whole-web
    search is the only thing the browser cannot do (`AsyncUrlSeeder` is domain-scoped by
    construction). Full detail: `docs/web-scraper-reference.md`.

    **Why the ladder went.** It ran the paid engine first and fell back to the free one.
    Measured on the same URLs minutes apart, that was backwards: local returned 17,364 B in
    1.2 s where Firecrawl returned 14,341 B in 16.8 s, and 8,786 B in 1.3 s against 5,515 B
    in 13.2 s — bigger, ~10x faster, free. ~900 lines of arbitration went with it. Counter-case
    worth keeping: hosts with real anti-bot protection refuse the local browser outright
    (`wsj.com` -> HTTP 401 / 1 B via DataDome, and **no saved login profile changes that**).

    **With no fallback to catch a bad result, each tool must be honest about its own output**
    — and three separate live runs proved that is not automatic. A crawl reported "saved 1
    page(s)" for a 44-byte nginx 403; a site search returned ten confidently-ranked pages for
    a nonsense query because BM25 scores a non-match 0.5, not 0.0; a byte count read like a
    short page when it was an anti-bot stub. All three now refuse or flag, via the shared
    `assess_quality` signal. Each was found by running the tool, never by a passing test.

- **ClaudeToolkit is the only layer that talks to the Anthropic API** in host apps — with no
  exceptions as of 2026-07-30. There was one (`local_browser.judge_completeness_llm`, a
  cheap Haiku call arbitrating between two scraper engines) and it is deleted, not merely
  better-guarded: with one engine per job there is nothing for a model to arbitrate. A host
  app's own token accounting cannot see a call made here, which is why the bar for adding
  another is "no other design works", not "it is cheap". Detail:
  `docs/api-usage-examples.md`

---

## Adding a New IBKR Endpoint

1. **`client.py`** — add method. Return a model from `models.py` when the response has a
   shape worth naming; otherwise return the decoded response and annotate it as such. This
   step said "return typed model" while **zero of 74 methods did** (audit finding API-11,
   2026-09-16); **29 do now** (2026-09-17), and `client.py`'s module docstring lists
   them by name so the claim can be checked rather than believed — by a guard whose model
   set is derived from `models.py`, because the first version froze six hand-typed names
   and stopped noticing the day a seventh model appeared. The "otherwise" branch is a
   decision, not an omission: every endpoint in `tests/fixtures/ibkr_live_shapes.json`
   either returns a model or is listed in `_NO_MODEL_BY_DESIGN` with the reason, and
   `test_every_captured_endpoint_is_typed_or_reasoned` fails when a new capture belongs to
   neither set.

   **A typed return is not a `dict`, and every caller has to survive that.** An
   `IBKRResponse` serves the mapping protocol — `.get`, `[]`, `in`, `len`, iteration — but
   it is not a `dict` and `json.dumps` does not know it. Typing a method therefore breaks
   two things silently, and both happened here on 2026-09-17: `isinstance(row, dict)`
   filters turned 21 futures rows into 0 and made `_listing_currency` answer "unknown" for
   every price, and a bare `json.dumps` turned the `get_alerts` tool and the
   `ibkr://accounts` resource into error bodies — the unit suite green throughout, because
   its mocks hand the handlers dicts. So when you type a method: grep its callers for
   `isinstance(..., dict)` and widen them to `dict | IBKRResponse`, and serialise only
   through `default=json_default`. Two guards hold the second one and part of the first:
   `test_every_json_dumps_in_the_tool_layer_can_serialise_a_model` reads the source of
   `claude_tools.py` and `mcp_server.py`, and `tests/claude_tools/test_typed_returns.py`
   drives the handlers with models built from the capture instead of hand-written dicts. Decode the response with `_decode(resp, path)`,
   never a bare `resp.json()`: `with_retry` has already raised on any non-2xx, but a 2xx is
   not a promise of JSON — the gateway serves an HTML page once its session lapses, and that
   left `IBKRClient` as `requests.exceptions.JSONDecodeError`, straight past the
   `except IBKRCoreError` that `exceptions.py` tells callers to write (API-15, 2026-09-17).
   `ping` is the one exemption and
   `test_every_client_request_helper_decodes_through_the_same_guard` fails if a second
   appears.
2. **`models.py`** — add a Pydantic model for the response if it is a new shape. Derive from
   `IBKRResponse`, never from `BaseModel` directly: that base keeps the payload IBKR sent and
   serves it through the mapping protocol, so a typed return can never narrow a 51-key
   position to seven fields. Return it via `parse_one`/`parse_many`, which pass an
   unparseable record through as the dict it arrived as instead of dropping it.
   **Then add the endpoint to `tests/fixtures/ibkr_live_shapes.json`** — re-capture with
   `scripts/audit/capture_live_response_shapes.py` against a live gateway — and test the model
   against that. Every model in this package was once tested against a dict written by hand
   to match it; two of the six raised on real data and two returned empty objects, for the
   package's whole life, behind a green suite. A fixture whose shape you chose cannot tell
   you whether the shape is right.
3. **`claude_tools.py`** — add tool definition to `TOOL_DEFINITIONS` + handler method to `ClaudeToolkit`
   - Declare `"capabilities": frozenset({...})` from `CAPABILITIES` on the definition — every sink the
     handler touches (IBKR write → `ACCOUNT_STATE`, store write → `DATABASE`, Drive write →
     `GOOGLE_DRIVE`, browser/seeder → `WEB_FETCH`, remote service → `NETWORK`) must be declared or
     `tests/security/test_tool_capabilities.py` fails; `ORDER_EXECUTION` cannot be declared at all.
     If the tool mutates state, add it to that test's frozen mutating-tool list and to `SECURITY.md`'s
     capability table.
   - If the handler needs an account ID, use `self._first_account_id()` (single) or `self._all_account_ids()` (all). Do **not** inline `get_accounts()` — the helpers centralise the `"accountId"` / `"id"` key fallback.
   - If the handler needs a `conid`, use `contracts[0].get("conid") or contracts[0].get("con_id")` to match `_fetch_market_data`.
   - Register the handler in the `execute()` dispatch dict.
4. **`tests/test_client.py`** — add integration test marked `@pytest.mark.integration`
5. Update `__init__.py` if new model needs to be exported

---

## Pointers

Read these on demand when working in the relevant area — they are plain file references,
not `@import`s, so they don't load into every session's context automatically.

- Per-module usage examples (Setup, Market Data, Technical Indicators, Backtesting,
  Portfolio Analytics, Claude AI Tool Layer, PineScript Generation): `docs/api-usage-examples.md`
- Order Management full code examples (read-only, place/confirm, manual reply-chain
  control, modify/cancel, GTC quarter-end auto-cancel behavior): `docs/order-management-examples.md`
- Gateway login walkthrough, `GatewayManager`, headless `TokenAuth`: `docs/gateway-auth-reference.md`
- Historical Trade Data / Flex Queries (one-time setup, usage, constraints): `docs/flex-query-reference.md`
- MCP Server (install, stdio/SSE transports, 46 tools, 4 resources, price alerts, TradingView integration): `docs/mcp-server-reference.md`
- Known IBKR API behaviors, verified not assumed: `docs/ibkr-api-behaviors-reference.md`
- Official documentation URLs, all external APIs: `docs/external-docs-reference.md`
- Web scraper (Firecrawl + Crawl4AI, four tools with no fallback between them, paywalled-site login profiles,
  per-host quirks, troubleshooting): `docs/web-scraper-reference.md`
- Scraping *method* — approaching an unfamiliar host, the four-way matrix, reading a blocked
  page, and where we stop on the anti-bot ladder: `docs/web-scraping-methodology.md`
- Security architecture — principals, privilege tiers, the trust-boundary map, the eleven
  invariants with their tests, subsystem designs, CI gates, the decision log, change recipes:
  `docs/security-architecture.md`; the OWASP MCP-guide applicability decision (2026-09-14, the
  principal external baseline, section by section): `docs/audits/owasp-mcp-guide-applicability-2026-09-14.md`,
  whose retrieved sources are archived under `docs/audits/audit-evidence/scrapes/`
- Consuming projects: `docs/consumers.md`
- Charting/quant/stats package landscape (what we have vs. gaps vs. duplicative-of-existing-code): `docs/python-package-landscape.md`
