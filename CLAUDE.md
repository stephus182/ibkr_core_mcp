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
```

**Python:** 3.11+ required. Use Homebrew Python on macOS (`brew install python`) — invoke the
versioned binary (`python3.11 -m venv`), not bare `python3`, since Homebrew may resolve that
to a newer, unsupported interpreter.
**Package manager:** `brew install` for macOS tooling, `pip install -e ".[dev,server]"` for
Python deps. The `server` extra (`mcp`, `starlette`, `uvicorn`) is not optional for a full
local test run — `tests/test_mcp_server.py`'s 17 tests fail to collect without it, even
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

# Web tools — a LIVE run is mandatory before calling any scraper change done.
# 11 tests, ~28s. Skips cleanly without the [scraper] extra or a Firecrawl key.
pytest tests/test_web_tools_live.py -v -m integration
```

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
mypy                      # type check — must be clean (files= covers both ibkr_core_mcp/ and tests/)
```

`[tool.mypy]` runs `strict = true` against `ibkr_core_mcp/` itself. `tests/` is also checked
(`files = ["ibkr_core_mcp", "tests"]`) but under a narrower `tests.*` override that relaxes
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

---

## Environment Variables

Create `.env` in any consuming project (not in this repo):

```
IBKR_GATEWAY_URL=https://localhost:5055/v1/api
ANTHROPIC_API_KEY=sk-ant-...
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
├── client.py             # All 74 IBKR Client Portal API endpoints
├── models.py             # Pydantic v2 schemas for all response types
├── exceptions.py         # Custom exception hierarchy (IBKRCoreError → subclasses)
├── cache.py              # Google Drive parquet cache (market data, shared cross-machine)
├── store.py              # SQLite store (trades, signals, backtest results, positions)
├── flex_query.py         # FlexQueryClient — Flex Web Service historical trade sync (T+1, unlimited history)
├── backtest.py           # RestrictedPython sandbox executor
├── indicators.py         # Technical indicators (RSI, MACD, BB, ATR, VWAP, OBV, ...)
├── analytics.py          # Performance metrics (Sharpe, Sortino, Calmar, drawdown, ...)
├── claude_tools.py       # Claude tool definitions + handlers (44 tools, portable)
├── mcp_server.py         # MCP server (stdio + SSE transports) — 46 tools, 4 resources
├── human_auth.py         # Gate 1: Touch ID / Face ID biometric authentication
├── order_confirm.py      # Gate 2: visual order confirmation dialog (tkinter/AppKit)
├── streaming.py          # IBKRWebSocket — live quotes, execution/P&L push; AlertManager
├── web_scraper.py        # FirecrawlClient + WebDocsStore — search/crawl, Drive snapshots (ladder rung 1)
├── local_browser.py    # Crawl4AI local browser (Playwright) + SSRF guard (ladder rung 2)
├── pinescript.py         # PineScript v5 generation from strategies and indicators
├── rate_limiter.py       # Token-bucket rate limiter + exponential backoff on 429
├── config.py             # Config dataclass loaded from environment variables
└── gateway/
    ├── manager.py        # GatewayManager — Docker lifecycle, auth polling
    ├── Dockerfile        # eclipse-temurin:21 + IBKR Client Portal zip
    ├── conf.yaml         # Gateway config (port, SSL, CORS, IP allowlist)
    ├── run_gateway.sh    # Entrypoint: start Java process + tickler
    ├── tickler.sh        # Periodic POST /tickle to keep session alive
    └── healthcheck.sh    # curl-based readiness probe used by run_gateway.sh
```

Basic object setup used throughout the codebase (`Config`, `IBKRClient`, `GDriveCache`,
`SQLiteStore`) and all per-module usage examples: `docs/api-usage-examples.md`

---

## Security & Fingerprint Authentication

**ALL order write operations require two sequential human validations. There is no bypass.**

Every call to `place_order`, `modify_order`, `cancel_order`, or `reply_order` must pass both gates — in order — before any network call reaches IBKR. `place_order_and_confirm` / `modify_order_and_confirm` run the same two gates again for every chained reply IBKR asks for, not just once. Full usage examples: `docs/order-management-examples.md`

| Gate | Mechanism | Behaviour |
|---|---|---|
| **Gate 1 — Touch ID** | Apple `LocalAuthentication` (`LAPolicyDeviceOwnerAuthentication`) | Touch ID/Face ID first, falls back to the device's system password on a failed/cancelled biometric scan. 60-second timeout. |
| **Gate 2 — Visual confirmation** | tkinter modal dialog with full order details + live-order disclaimer | Explicit mouse click required. Enter key does not confirm. |

If either gate fails (denied, timeout, cancelled), `HumanAuthError` is raised immediately and the IBKR endpoint is never contacted.

**Gated endpoints:**

| Method | Gates |
|---|---|
| `place_order` | Touch ID → confirm dialog |
| `place_order_and_confirm` | `place_order`'s gates, then Touch ID → reply dialog (showing the real IBKR message) per chained reply, until a terminal response |
| `modify_order` | Touch ID → modify dialog |
| `modify_order_and_confirm` | `modify_order`'s gates, then Touch ID → reply dialog per chained reply, until a terminal response |
| `cancel_order` | Touch ID → cancel dialog |
| `reply_order` | Touch ID → reply dialog |

`place_order_and_confirm` / `modify_order_and_confirm` are the recommended entry points — a single IBKR order can require multiple chained replies before reaching a terminal state, and these methods resolve the whole chain safely. `place_order` / `modify_order` / `reply_order` stay available for callers who want manual control over each step.

**Explicitly ungated (read-only, no execution risk):**

| Method | Reason |
|---|---|
| `get_order_preview` | IBKR `whatif` — simulates, never executes |
| `get_live_orders` / `get_order_status` / `get_orders_raw` | Read-only |
| `create_alert` / `delete_alert` / `activate_alert` | Price notifications, not order execution |

**Rules for contributors:**

- Never add a bypass flag, session cache, or library-side fallback to `require_touch_id` or any dialog function — no code path may skip or cache a prior Touch ID / dialog success.
- Never move the gates out of `IBKRClient` — enforcement must be at the innermost call site.
- The required policy is `LAPolicyDeviceOwnerAuthentication` (Touch ID/Face ID, falling back to the device's system password on a failed/cancelled biometric scan) — Apple's own recovery path for a genuinely-failed biometric read, not a bypass this library adds. The stricter biometrics-only policy was evaluated and rejected: a failed scan under it has no recovery path at all. Don't change this policy without updating both this file and `README.md`'s Security section in the same PR.
- Any PR that weakens these gates *beyond* the documented policy above — e.g. skipping `require_touch_id`/`confirm_order_dialog` entirely, caching a prior success, or adding a fallback beyond the OS's own password prompt — will be rejected.

---

## Gateway Authentication & Session

The IBKR Client Portal Gateway must run on the **same machine** as the browser used to authenticate — no cloud deployment possible. `BrowserCookieAuth` (default) reads Chrome's cookie store for `localhost`; start it via the built-in `GatewayManager`. Session expires without activity — call `client.tickle()` every 60s to keep it alive. Rate limit 10 requests/second globally (lower per-endpoint limits apply to some endpoints — see `docs/gateway-auth-reference.md`), handled transparently by `rate_limiter.py`. Full login walkthrough, `GatewayManager` code, and headless `TokenAuth` usage for batch jobs: `docs/gateway-auth-reference.md`

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
  claim of completeness was wrong. The only surviving `cpapi-v1` text is
  `docs/audits/audit-evidence/scrapes/cpapi-v1.md`, a dated capture of the retired page which
  carries a header saying so; its in-body URLs are evidence, not citations, and rewriting them
  would falsify what was retrieved. Three things to know before citing a source URL again:

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
    is a complete 517-page index. There is also an MCP server at
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

1. **`client.py`** — add method, return typed model
2. **`models.py`** — add Pydantic model for response if new shape
3. **`claude_tools.py`** — add tool definition to `TOOL_DEFINITIONS` + handler method to `ClaudeToolkit`
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
- Web scraper (Firecrawl + Crawl4AI, recovery ladder, paywalled-site login profiles,
  per-host quirks, troubleshooting): `docs/web-scraper-reference.md`
- Scraping *method* — approaching an unfamiliar host, the four-way matrix, reading a blocked
  page, and where we stop on the anti-bot ladder: `docs/web-scraping-methodology.md`
- Consuming projects: `docs/consumers.md`
- Charting/quant/stats package landscape (what we have vs. gaps vs. duplicative-of-existing-code): `docs/python-package-landscape.md`
