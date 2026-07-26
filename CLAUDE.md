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
```

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

**Standalone dev exception:** with no `.env` here, `firecrawl_search`/`firecrawl_crawl`
correctly report "not configured" and never touch Drive — by design, not a bug, since
`Config.from_env()` reads empty strings. To exercise Drive caching while developing
ibkr_core_mcp in isolation (not inside a consuming project), a local `.env` **in this
repo** is fine — it's gitignored and never committed. Only 4 vars are needed (no
`GOOGLE_DRIVE_FOLDER_ID` required): `FIRECRAWL_API_KEY`, `GDRIVE_WEB_DOCS_FOLDER_ID`
(an existing `web_docs/` folder ID), `GDRIVE_TOKEN_FILE`, `GDRIVE_CREDENTIALS_FILE`
(reuse an already-authenticated token to skip interactive OAuth). Verify with
`pytest tests/test_web_scraper_dev_cache_live.py -v -m integration`.

Never commit `.env` or any GDrive OAuth credential/token file (e.g. `credentials_ibkr_core_mcp.json`, `token_ibkr_core_mcp.json`).

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
├── claude_tools.py       # Claude tool definitions + handlers (42 tools, portable)
├── mcp_server.py         # MCP server (stdio + SSE transports) — 44 tools, 4 resources
├── human_auth.py         # Gate 1: Touch ID / Face ID biometric authentication
├── order_confirm.py      # Gate 2: visual order confirmation dialog (tkinter/AppKit)
├── streaming.py          # IBKRWebSocket — live quotes, execution/P&L push; AlertManager
├── web_scraper.py        # FirecrawlClient + WebDocsStore — search/crawl, Drive snapshots
├── scrape_fallback.py    # Crawl4AI fallback + SSRF guard for web scraping
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
  **`interactivebrokers.com/docs/web-api/`**. All 81 deep links in this repo were repointed.
  Two things to know before citing a source URL again:

  - The old URLs **still return HTTP 200** — they redirect to the new site's Introduction page
    and *silently drop the `#anchor`*. A link checker reports success while the reader lands
    on the wrong page. Never re-add a `cpapi-v1/#…` link; a 200 is not evidence it works.
  - The new site is AI-friendly, which makes verification cheap: append **`.md`** to any page
    URL for clean markdown, and **`https://www.interactivebrokers.com/docs/web-api/llms.txt`**
    is a complete 517-page index. There is also an MCP server at
    `https://ibkrcampus.com/docs/web-api/_mcp/server`. Prefer these over scraping the HTML — they
    cost no Firecrawl credits and cannot be edge-blocked. If you do scrape,
    `FirecrawlClient.crawl()` makes one attempt and, whenever it yields under 5 KB of markdown
    (including on 401/402/429 or a network error), falls back to a free local Crawl4AI scrape of
    the root URL, reporting an explicit diagnosis instead of the old silent "saved 0 page(s)".
    `waitFor`/`proxy` are exposed on both `crawl()` and `search()` as opt-in overrides.

- **ClaudeToolkit is the only layer meant to talk to the Anthropic API** in host apps — one
  deliberate, scoped exception exists (`scrape_fallback.judge_completeness_llm`, a single
  cheap Haiku completeness check). Don't treat it as precedent for adding another direct API
  call without the same scrutiny; a host app's own token-usage tracking won't see it. Detail:
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
- MCP Server (install, stdio/SSE transports, 44 tools, 4 resources, price alerts, TradingView integration): `docs/mcp-server-reference.md`
- Known IBKR API behaviors, verified not assumed: `docs/ibkr-api-behaviors-reference.md`
- Official documentation URLs, all external APIs: `docs/external-docs-reference.md`
- Web scraper (Firecrawl + Crawl4AI, recovery ladder, paywalled-site login profiles,
  per-host quirks, troubleshooting): `docs/web-scraper-reference.md`
- Consuming projects: `docs/consumers.md`
- Charting/quant/stats package landscape (what we have vs. gaps vs. duplicative-of-existing-code): `docs/python-package-landscape.md`
