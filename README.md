# ibkr_core_mcp

[![CI](https://github.com/stephus182/ibkr_core_mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/stephus182/ibkr_core_mcp/actions/workflows/ci.yml)

Python library for Interactive Brokers clients. Wraps the IBKR Client Portal API and ships batteries-included tooling for algorithmic trading, backtesting, real-time streaming, and Claude AI integration.

> **Who is this for?** IBKR account holders who want to automate market data retrieval, portfolio monitoring, and order staging from Python — or who want to connect an AI assistant to their brokerage.

---

📚 Full documentation catalog: [`docs/README.md`](docs/README.md)

## Feature overview

| Module | What it does |
|---|---|
| `GatewayManager` | Builds and runs the official IBKR Client Portal Gateway as a Docker container, guides browser login + 2FA |
| `IBKRClient` | Full REST client for the Client Portal API — market data, positions, orders, scanners |
| `ClaudeToolkit` | 44 ready-made Claude AI tools (`tools=` parameter) for Anthropic SDK integration |
| `SQLiteStore` | Local SQLite store — trade history, price alerts, session log |
| `GDriveCache` | Google Drive Parquet cache for OHLCV data |
| `streaming` | IBKR WebSocket live quotes + price alert engine |
| `backtest` | Strategy backtester in a RestrictedPython sandbox — attribute allowlist, child process, 10 s watchdog |
| `indicators` | Technical indicators (RSI, MACD, Bollinger, ATR, VWAP, …) |
| `analytics` | Portfolio analytics — drawdown, Sharpe, Sortino, Calmar, CAGR, win rate, profit factor |
| `pinescript` | PineScript v5 generator |
| `web_scraper` / `local_browser` | Whole-web search (Firecrawl) + the local Crawl4AI browser for anything with a URL, and the `web_docs/` Drive archive |
| `mcp_server` | MCP server (stdio + SSE with Host/Origin validation) exposing all 46 tools to any MCP client |

---

## Requirements

- Python 3.11 – 3.13 (3.14 not yet supported — enforced by `requires-python`)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (for `GatewayManager`)
- An **Interactive Brokers** account (live or paper)
- An Anthropic API key if *your* application drives Claude — this package never calls a
  model, so it neither needs nor accepts one (see `ClaudeToolkit` below)

### macOS — required for order execution

Order write methods (`place_order`, `place_order_and_confirm`, `modify_order`, `modify_order_and_confirm`, `cancel_order`, `reply_order`) are gated by Touch ID. This gate is enforced inside the library and **cannot be bypassed**. It requires:

| Requirement | Minimum |
|---|---|
| Operating system | macOS 10.12.1 (Sierra) |
| Hardware | Any Mac with a built-in Touch ID sensor or a [Touch ID keyboard](https://www.apple.com/shop/product/MK293LL/A/) |
| Python package | `pyobjc-framework-LocalAuthentication` (installed automatically with `ibkr_core_mcp`) |
| Policy | `LAPolicyDeviceOwnerAuthentication` — Touch ID/Face ID first, falls back to the device's system password if the biometric scan fails or is cancelled |

Touch ID is available on: MacBook Pro (late 2016+), MacBook Air (2018+), Mac mini (2020+), iMac (2021+), Mac Studio, Mac Pro (2023+).

**Linux / Windows:** All read-only tools (market data, portfolio queries, backtesting, analytics, MCP server) work on any platform. Order execution is macOS-only by design.

---

## API Documentation

This library is built on official documented APIs. Any contribution touching API behavior, error codes, endpoint paths, or field names **must reference the official source** — never assume from memory or training data.

| API | Official reference |
|---|---|
| IBKR Client Portal API | https://www.interactivebrokers.com/docs/web-api/v1/introduction |
| IBKR Flex Web Service | https://www.ibkrguides.com/clientportal/performanceandstatements/flex3.htm |
| Flex error codes | https://www.ibkrguides.com/clientportal/performanceandstatements/flex3error.htm |
| IBKR WebSocket streaming | https://www.interactivebrokers.com/docs/web-api/v1/ws/introduction |
| Google Drive API v3 | https://developers.google.com/drive/api/reference/rest/v3 |
| macOS LocalAuthentication | https://developer.apple.com/documentation/localauthentication |
| Firecrawl API | https://docs.firecrawl.dev/api-reference/endpoint/scrape |
| Crawl4AI (local browser) | https://docs.crawl4ai.com/ |

Full details and per-file API ownership are in [`CLAUDE.md`](CLAUDE.md#conventions).

---

## Installation

```bash
pip install git+https://github.com/stephus182/ibkr_core_mcp.git
```

Or pin to a specific version:

```bash
pip install git+https://github.com/stephus182/ibkr_core_mcp.git@v1.2.2
```

Or for local development:

```bash
git clone https://github.com/stephus182/ibkr_core_mcp.git
cd ibkr_core_mcp
pip install -e ".[dev,server]"
```

---

## Quick start

### 1. Start the IBKR gateway

`GatewayManager` handles the entire Docker lifecycle — building the image, starting the container, and guiding you through browser login and 2FA.

```python
from ibkr_core_mcp.gateway import GatewayManager

gm = GatewayManager()
gm.startup()   # interactive: starts container → opens browser → waits for auth
```

Or use the programmatic API (for non-interactive environments, e.g. a web UI or a batch job):

```python
gm = GatewayManager()
gm.start()                   # build image (first run) + docker run
gm.wait_for_gateway()        # wait up to 120 s for Java process
gm.open_login_page()         # open https://localhost:5055 in browser
# … user logs in …
gm.wait_for_auth(timeout=300)  # poll until authenticated
```

`startup()` steps on first run:
1. Launch Docker Desktop (macOS) if not running
2. Build the gateway image (~60 MB IBKR zip, cached afterwards)
3. Start the container on port 5055
4. Open `https://localhost:5055` in your browser
5. You log in with your IBKR credentials + 2FA
6. Verify the session is active

### 2. Query IBKR

```python
from ibkr_core_mcp import IBKRClient, SQLiteStore, Config

config = Config.from_env()             # reads env vars / .env
store  = SQLiteStore(config)
client = IBKRClient(config)            # BrowserCookieAuth used by default

# Most endpoints need an account ID first
accounts   = client.get_accounts()
account_id = accounts[0]["accountId"]

summary   = client.get_account_summary(account_id)
positions = client.get_positions(account_id)

# Market data requires a contract ID (conid), not a symbol string
contracts = client.search_contract("AAPL")
conid     = contracts[0]["conid"]
bars      = client.get_market_history(conid, period="1Y", bar="1d")
```

### 3. Use Claude AI tools

```python
import anthropic
from ibkr_core_mcp import ClaudeToolkit, IBKRClient, SQLiteStore, GDriveCache, Config

config  = Config.from_env()
store   = SQLiteStore(config)
cache   = GDriveCache(config)
client  = IBKRClient(config)
toolkit = ClaudeToolkit(client=client, cache=cache, store=store, config=config)

ai = anthropic.Anthropic()

response = ai.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=4096,
    tools=toolkit.tools,               # drop-in for Anthropic SDK
    messages=[{"role": "user", "content": "What are my current positions?"}],
)

# Route tool calls back through the toolkit
for block in response.content:
    if block.type == "tool_use":
        text, _fig = toolkit.execute(block.name, block.input)  # _fig is always None in v1.0
```

---

## Available tools (Claude AI / MCP)

See [docs/tools-reference.md](docs/tools-reference.md) for full parameter docs and output shapes.

| Tool | Description |
|---|---|
| `fetch_market_data` | OHLCV history with Google Drive cache |
| `check_cache` | Check whether data is cached |
| `list_cache` | List all cached datasets |
| `delete_cache` | Delete a cached dataset |
| `get_account_summary` | Net liquidation, cash, P&L |
| `get_positions` | All open positions |
| `get_pnl` | Real-time P&L partitioned by position |
| `get_ledger` | Cash balances by currency |
| `get_allocation` | Portfolio breakdown by asset class |
| `get_trades` | Trade history (live: last 6 days; store: unlimited) |
| `sync_flex_trades` | Sync full history via IBKR Flex Web Service |
| `sync_flex_archive` | Re-sync full Flex archive from GDrive parquet |
| `check_flex_coverage` | Activity distribution report — trade-date coverage across stored history (not an integrity check) |
| `import_flex_file` | Import a locally downloaded Flex XML file into SQLite |
| `verify_flex_import` | Import integrity check — cross-checks XML tradeIDs on Drive against SQLite; uses manifest to skip re-verifying unchanged files |
| `get_live_orders` | Working orders (Submitted, PreSubmitted, Inactive, …) |
| `get_order_status` | Status of a specific order by ID |
| `diagnose_orders` | Diagnose order issues — checks session, permissions, account |
| `preview_order` | Whatif order preview — no order placed |
| `get_pa_performance` | Portfolio Analyst NAV performance |
| `get_pa_transactions` | Portfolio Analyst transactions |
| `get_pa_periods` | Valid period strings for `get_pa_performance` |
| `search_contract` | Resolve symbol → conid, exchange, currency |
| `get_contract_info` | Full contract details (exchange, trading hours, etc.) |
| `get_option_chain` | Option chain — expiry months + call/put strikes |
| `get_futures` | Futures contracts — expiry months, conids |
| `get_market_snapshot` | Live bid/ask/last/volume for one or more symbols |
| `get_trading_schedule` | Per-venue trading sessions and hours for a symbol (omit `exchange`; SMART returns nothing) |
| `run_scanner` | Market scanner (top gainers, losers, most active, …) |
| `get_notifications` | IBKR FYI account notifications |
| `get_alerts` | List IBKR native price alerts |
| `create_price_alert` | Create a server-side IBKR price alert — **blocked upstream**, see [Streaming](#streaming-live-quotes) |
| `modify_price_alert` | Update threshold or direction on an existing IBKR alert — **blocked upstream**, same note |
| `delete_alert` | Delete an IBKR price alert |
| `activate_alert` | Enable or disable an IBKR price alert |
| `get_watchlists` | List IBKR watchlists and their contents |
| `add_indicators` | Compute RSI, MACD, Bollinger, ATR, VWAP, … |
| `run_backtest` | Sandboxed RestrictedPython strategy backtester |
| `generate_pinescript` | Generate PineScript v5 strategy/indicator |
| `get_analytics` | Sharpe, Sortino, Calmar, CAGR, max drawdown |
| `firecrawl_search` | Search the **whole web** — a query with no site in mind. Returns ranked URLs + snippets |
| `search_site` | Search **one site** — domain + query, BM25-ranked. Free (local browser + public sitemaps) |
| `crawl_site` | Archive a site to Google Drive under `web_docs/`; reuses a cached crawl <48h old. Free |
| `fetch_page` | Read **one page** as markdown, incl. paywalled sites with a saved login. Free |

---

## MCP server

Expose all 44 tools (+ 2 MCP-only alert tools = 46 total) to any MCP-compatible client (Claude Desktop, Cursor, etc.):

```bash
# stdio transport (Claude Desktop / Cursor)
python -m ibkr_core_mcp.mcp_server

# SSE transport with live streaming — binds 127.0.0.1 and accepts loopback Host/Origin only
python -m ibkr_core_mcp.mcp_server --transport sse --port 5174 --stream
```

Every tool carries a declared `capabilities` set (read-only, compute, Drive, SQLite, IBKR
account state, sandbox, web fetch, …); no tool declares order execution, and the test suite
asserts it. See [`docs/security-architecture.md`](docs/security-architecture.md) § 2 and § 6.8.

---

## Streaming (live quotes)

```python
import asyncio
from ibkr_core_mcp.streaming import IBKRWebSocket

# IBKRWebSocket takes the HTTPS gateway URL — it converts to wss:// internally
ws = IBKRWebSocket(gateway_url="https://localhost:5055", session_cookie="")

async def main():
    await ws.connect()
    conid = 265598  # AAPL — use search_contract() to find conids
    await ws.subscribe(conid)
    async for quote in ws.listen():
        print(quote.symbol, quote.last, quote.bid, quote.ask)

asyncio.run(main())
```

**Price alerts: the local engine works; creating IBKR's native alerts does not, and it is not this
package's defect.** `SQLiteStore.add_alert` + `AlertManager` (and the MCP server's `add_price_alert`
under `--stream`) evaluate thresholds against live quotes on this machine. IBKR's own server-side
alerts can be *listed, deleted and toggled* through `get_alerts` / `delete_alert` / `activate_alert`,
but **creating or modifying one is not possible through the Client Portal Gateway as published**:
the gateway refuses any request body carrying `>=` or `<=` before IBKR sees it, and IBKR's alert
engine refuses the three operators the gateway lets through — measured 2026-09-16, elimination
table in [`docs/ibkr-api-behaviors-reference.md`](docs/ibkr-api-behaviors-reference.md) § Price
alerts. `create_price_alert` and `modify_price_alert` are kept, say so in their descriptions, and
return that explanation instead of an alert; the day the gateway changes, they work unchanged.

---

## Backtesting

```python
from ibkr_core_mcp.backtest import run_backtest

# Strategy code receives a DataFrame `df` and must set df['signal']
# 1 = long, 0 = flat, -1 = short
code = """
fast = df['close'].ewm(span=12).mean()
slow = df['close'].ewm(span=26).mean()
df['signal'] = (fast > slow).astype(int)
"""

# The sandbox runs in a SPAWNED child process, which re-imports your __main__ — so a
# script must guard the call, or the child re-runs it and dies before the strategy runs.
if __name__ == "__main__":
    result = run_backtest(code=code, df=bars_dataframe, strategy_name="EMA crossover", symbol="AAPL")
    print(result.sharpe, result.max_drawdown, result.total_return)
```

Strategy code runs in a `RestrictedPython` sandbox inside a child process — no imports, no
file system, no network, no subprocess. `df`, `pd` and `np` expose an **allowlist** of the
vectorised-strategy vocabulary (arithmetic, rolling/ewm/expanding/groupby, indexing, `.str`/`.dt`,
in-memory converters); every `to_*` writer, `style`, `plot` and pandas' expression engine are
unreachable, and the string form of `apply`/`agg`/`transform` faces the same list. 4,096-character
limit; 10-second watchdog. Rationale and the audit that motivated the allowlist:
[SECURITY.md](SECURITY.md#code-execution-security--backtest-sandbox).

---

## Web Scraping

**Four tools, one job each, and no fallback between them.** Anything that takes a URL goes to a
free local browser ([Crawl4AI](https://docs.crawl4ai.com/), Playwright-based, no API key).
[Firecrawl](https://firecrawl.dev) is kept for the one thing the browser cannot do: search the
web when you have no URL yet.

| Tool | Engine | Cost | Job |
|---|---|---|---|
| `firecrawl_search` | Firecrawl | ~1 credit | Find pages **anywhere** |
| `search_site` | Crawl4AI | free | Find pages **on one site**, BM25-ranked |
| `crawl_site` | Crawl4AI | free | **Archive a site** to Drive `web_docs/{url-slug}/` |
| `fetch_page` | Crawl4AI | free | **Read one page** as markdown |

The first two *find* and return URLs; the last two *read*. Neither finder returns page text —
follow one with `fetch_page`.

**Why the local browser is the default and not the fallback.** Until 2026-07-30 this was a
two-rung ladder: Firecrawl first, Crawl4AI only as a rescue. Measured on the same URLs minutes
apart, that was backwards — local returned **17,364 B in 1.2 s** where Firecrawl returned
**14,341 B in 16.8 s**, and **8,786 B in 1.3 s** against **5,515 B in 13.2 s**. Bigger, ~10×
faster, free. The ladder and ~900 lines of arbitration went with it. Counter-case worth knowing:
hosts with real anti-bot protection refuse the local browser outright (`wsj.com` → HTTP 401 and
1 byte, and no saved login changes that).

`crawl_site` checks Drive for an existing manifest before opening a browser — if one under 48h
old exists for that URL it is returned directly, fetching nothing (`force_refresh: true`
bypasses). The 48h window is this package's own choice for reference-doc content, informed by
Firecrawl's v2 `scrapeOptions.maxAge` default (172,800,000 ms) as an externally-validated
reference point; the v1 API this package calls defaults that same parameter to `0`.

```bash
# The three browser tools need this extra (base install works without it)
pip install "ibkr_core_mcp[scraper]"
crawl4ai-setup   # installs Playwright/Chromium, one-time
```

For paywalled sites you already subscribe to, Crawl4AI can reuse a saved browser login — no
credentials are ever stored by `ibkr_core_mcp`, only the resulting browser session:

```bash
# One-time interactive login; opens a real browser window. Needs a TTY.
python -m ibkr_core_mcp.local_browser create-profile https://www.ft.com
```

The session lives under `CRAWL4AI_PROFILES_DIR` (default
`~/.ibkr_core/crawl4ai_profiles/<domain>/`) and is reused automatically on later scrapes of that
domain. Every URL reaching the local browser is SSRF-validated first, and a second
Playwright-level guard re-checks every navigation, redirect and subresource — see
[SECURITY.md](SECURITY.md#ssrf-prevention-web-scraping--the-local-browser).

**Live tests are mandatory for this subsystem**, because every defect in it was found by running
a tool rather than by a test failing:

```bash
set -a; source ./.env; set +a
pytest tests/test_web_tools_live.py -v -m integration     # 12 tests, ~30s
```

Full detail, including the credit model and per-host notes:
[`docs/web-scraper-reference.md`](docs/web-scraper-reference.md).


---

## Environment variables

Copy `.env.example` to `.env` and fill in:

| Variable | Required | Description |
|---|---|---|
| `IBKR_GATEWAY_URL` | ✅ | Client Portal URL (default: `https://localhost:5055/v1/api`) — the `/v1/api` suffix is required; paths are appended verbatim |
| `IBKR_SQLITE_PATH` | optional | SQLite store path (default: `~/.ibkr_core/store.db`) |
| `GOOGLE_DRIVE_FOLDER_ID` | for GDrive | Root Drive folder — parent of `db/` and `market_data/` subfolders |
| `GDRIVE_DB_FOLDER_ID` | optional | Explicit folder for claudia.db. If unset, auto-created as `db/` inside `GOOGLE_DRIVE_FOLDER_ID` |
| `GDRIVE_CACHE_FOLDER_ID` | optional | Explicit Drive folder for Parquet cache. If unset, auto-created as `market_data/` inside `GOOGLE_DRIVE_FOLDER_ID` |
| `GDRIVE_TOKEN_FILE` | for GDrive | OAuth2 token path |
| `GDRIVE_CREDENTIALS_FILE` | for GDrive | OAuth2 credentials path |
| `IBKR_FLEX_TOKEN` | for Flex sync | Flex Web Service token |
| `IBKR_FLEX_QUERY_ID` | for Flex sync | Flex query ID |
| `FIRECRAWL_API_KEY` | for whole-web search only | Firecrawl API key. If unset, only `firecrawl_search` returns a "not available" message rather than raising |
| `GDRIVE_WEB_DOCS_FOLDER_ID` | optional | Explicit Drive folder for scraped docs/search snapshots. If unset, auto-created as `web_docs/` inside `GOOGLE_DRIVE_FOLDER_ID` |
| `CRAWL4AI_PROFILES_DIR` | optional | Saved Crawl4AI login profiles for paywalled sites (default: `~/.ibkr_core/crawl4ai_profiles`) |

---

## Security

**ibkr_core_mcp does not place orders autonomously.** Order write methods (`place_order`, `place_order_and_confirm`, `modify_order`, `modify_order_and_confirm`, `cancel_order`, `reply_order`) on `IBKRClient` are gated by two sequential controls enforced at the innermost call site inside the library. A single IBKR order can require several chained confirmation replies before reaching a terminal state — `place_order_and_confirm`/`modify_order_and_confirm` are the recommended entry points, since they take one Touch ID for the whole chain and show a confirmation dialog for every reply in it (see [CLAUDE.md — Security & Fingerprint Authentication](CLAUDE.md#security--fingerprint-authentication)):

### Gate 1 — Touch ID (macOS LocalAuthentication)

Implemented in `human_auth.py` using the macOS `LocalAuthentication` framework via `pyobjc-framework-LocalAuthentication`.

- **Policy:** `LAPolicyDeviceOwnerAuthentication` — tries Touch ID/Face ID first, then falls back to the device's system password if the biometric scan fails or is cancelled. The fallback exists because a fingerprint scan can genuinely fail to read (wet/dry skin, worn ridge detail, sensor angle) even for the real account owner — the stricter biometrics-only policy has no recovery path on a failed scan.
- **No bypass inside the library:** `ibkr_core_mcp` itself never intercepts or skips this call. A standalone write prompts. A chain started by `place_order_and_confirm` / `modify_order_and_confirm` takes **one** Touch ID up front, which mints an `OrderWriteAuthorization` bound to the SHA-256 of that write's own account and body (300 s, frame-local, expiring closed); the write and each chained reply re-check *that value* instead of prompting again, and Gate 2 runs unskipped at every step. Anything the authorization does not cover — a direct call, an expired window, a body that no longer matches — prompts. This bullet said "every order-write attempt calls `require_touch_id()` fresh" until 2026-09-16, contradicting the paragraph above it and the 2026-09-11 rule. If both the biometric scan and the system password fail, `HumanAuthError` is raised immediately and the order is never submitted.
- **Timeout:** 60 seconds. An unanswered prompt raises `HumanAuthError` and the order is not submitted.
- **Prompt text:** The caller-supplied `reason` string appears in the macOS Touch ID dialog (e.g. *"Confirm order: BUY 100 AAPL"*).
- **Thread-safe:** Uses a `threading.Event` to wait for the async `LAContext` reply callback without blocking the main run loop.

If `pyobjc-framework-LocalAuthentication` is not installed, or if the Mac hardware does not support biometrics (e.g. a Mac mini without a Touch ID keyboard attached), the gate raises `HumanAuthError` and the order is never submitted.

### Gate 2 — Visual confirmation dialog

Implemented in `order_confirm.py`.

- Full order details displayed in a modal: on macOS an AppKit dialog run in a subprocess (banner colour-coded by side — green BUY, red SELL, dark red CANCEL, amber when the side is unknown), with an `osascript` fallback; `tkinter` on other platforms
- 60-second timeout — the dialog auto-cancels unattended
- **Enter key disabled** — confirmation requires a deliberate mouse click on the button named for the action (SEND TO IBKR, MODIFY ORDER, CANCEL ORDER, CONFIRM REPLY). Return confirms on none of the three renderers, but each refuses it by a different mechanism, and `SECURITY.md` § Gate 2 names them. This bullet ended "the default button is the abandon one" until 2026-09-17, which was the `osascript` fallback's mechanism alone (audit finding SEC-09)
- The body the dialog shows is the body sent: the order dict is copied before the gates

Both gates are part of `ibkr_core_mcp` itself. Downstream consumers such as [ClaudIA](https://github.com/stephus182/claudia_ui) can add further gates (e.g. a "Stage this order" button click in its Panel UI) before `place_order`/`place_order_and_confirm` is ever invoked.

`GatewayManager` runs the IBKR Client Portal Gateway as a Docker container bound to `localhost:5055` only. The container has no privileged access and exposes no host filesystem mounts.

**Web scraping (`search_site`, `crawl_site`, `fetch_page`) is SSRF-guarded at two independent layers** — a pre-fetch URL check, plus a Playwright-level per-request check on every Crawl4AI fetch (initial navigation, redirects, and subresources) that closes DNS-rebinding and redirect-based bypasses the pre-fetch check alone can't. See [SECURITY.md](SECURITY.md#ssrf-prevention-web-scraping--the-local-browser).

### Machine-checked, not just documented

Since the 2026-09-13 security architecture audit, the properties above are enforced by tests
that read the source, not only by convention (`pytest -m security`, ~10 s, part of every unit
run and of CI):

- the three order-write endpoints are built only inside the four gated methods, each runs a gate before its first network call, and the tool layer never references an order write;
- the whatif preview is the only ungated order path;
- every tool declares its `capabilities`, none declares `ORDER_EXECUTION`, and a handler that touches an undeclared sink fails;
- strategy code cannot read or write a file, spawn a process or reach the network (canary tests), and what it may touch is a frozen allowlist;
- every model-supplied URL is checked before the fetch and on every browser request, against a tested table of local and reserved address forms;
- every exception the tool layer shows or logs passes one redaction function;
- unit tests cannot open sockets, resolve names or see the operator's credentials;
- processes are spawned only from three named modules, never through a shell;
- the SSE transport rejects foreign `Host`/`Origin` values.

CI adds `pip-audit` over a **fresh resolve** of `.[dev,server,scraper]` — requirements mode, installing nothing, so it audits what a user would get rather than what this machine happens to have — and `gitleaks` over every pushed range. The
design — principals, privilege tiers, the trust-boundary map, each invariant with its enforcing
test, the decision log, change recipes — is [`docs/security-architecture.md`](docs/security-architecture.md);
the control inventory is [SECURITY.md](SECURITY.md); the audit with its probe evidence is
[`docs/audits/security-architecture-audit-2026-09-13.md`](docs/audits/security-architecture-audit-2026-09-13.md).

---

## Market Calendar

`SQLiteStore.get_market_calendar_context()` uses [`exchange_calendars`](https://github.com/gerrymanoim/exchange_calendars) to provide trading-day-aware context without any API calls:

```python
from ibkr_core_mcp.store import SQLiteStore

# Default: 20 exchanges (full G20 + Eurex) — no Config needed for this call
cal = SQLiteStore.get_market_calendar_context()

# {
#   "today": "2026-06-24",
#   "is_trading_day": True,
#   "last_trading_day": "2026-06-23",
#   "next_trading_day": "2026-06-25",
#   "primary_exchange": "XNYS",
#   "holidays_by_exchange": {
#     "XNYS":  ["2026-01-01", "2026-01-19", "2026-02-16", ...],   # NYSE
#     "CME":   ["2026-01-01", "2026-07-04", ...],                  # CME Futures
#     "XLON":  ["2026-01-01", "2026-04-03", "2026-04-06", ...],   # LSE London
#     "XETR":  ["2026-01-01", "2026-04-03", ...],                  # Xetra Frankfurt
#     "XTKS":  ["2026-01-01", "2026-01-02", ...],                  # TSE Tokyo
#     "XHKG":  ["2026-01-01", "2026-01-28", ...],                  # HKEX Hong Kong
#     "XASX":  ["2026-01-01", "2026-01-26", ...],                  # ASX Sydney
#     "XTSE":  ["2026-01-01", "2026-02-16", ...]                   # TSX Toronto
#   }
# }

# Custom exchange list
cal = SQLiteStore.get_market_calendar_context(exchanges=["XNYS", "XKRX", "XBOM"])
```

**Coverage:** full current year + next year (past and future holidays) — ~10–28 per exchange, negligible payload.

**Default 20 exchanges (full G20 + Eurex):** NYSE (XNYS), CME Futures (CME), LSE London (XLON), Xetra Frankfurt (XETR), Eurex (XEUR), Euronext Paris (XPAR), Borsa Italiana (XMIL), TSE Tokyo (XTKS), HKEX Hong Kong (XHKG), SSE Shanghai (XSHG), BSE Mumbai (XBOM), KRX Seoul (XKRX), ASX Sydney (XASX), TSX Toronto (XTSE), B3 São Paulo (BVMF), BMV Mexico City (XMEX), JSE Johannesburg (XJSE), Tadawul Saudi Arabia (XSAU), IDX Jakarta (XIDX), Borsa Istanbul (XIST). Excludes Russia (XMOS — IBKR suspended most Russian securities since 2022) and Argentina (XBUE — capital controls, very limited IBKR access).

**100+ supported markets** including XNAS (NASDAQ), XPAR (Euronext Paris), XKRX (Korea), XBOM (Bombay), SSE (Shanghai), BVMF (Brazil), and more — [full list](https://github.com/gerrymanoim/exchange_calendars).

**Used for:**
- **Staleness check** — `get_trade_date_coverage()` uses the NYSE calendar to determine if Flex data is current. `newest == last_trading_day` means fully up to date, regardless of whether today is a weekend or holiday.
- **System prompt injection** — ClaudIA receives today's trading status, last/next trading day, and full-year holidays for all 20 exchanges at session start. This lets it reason about order timing, settlement windows, cross-regional volume effects, and upcoming closures proactively — without any API calls or gateway dependency.

**Why not the IBKR API?** The Client Portal API has a per-contract trading schedule endpoint but no standalone market holiday calendar. `exchange_calendars` is lighter, faster, and works offline.

**Performance:** Designed for zero marginal cost at scale.

| Call | Time |
|---|---|
| First call per process (cold) | ~3.4s — `exchange_calendars` loads numpy arrays for 20 exchanges once |
| Subsequent calls same day | 0.01ms — process-level date-keyed cache hit |
| Next day / process restart | Recomputes fresh automatically |

The cache key is `(date_str, tuple(exchange_codes))` — stored in a module-level dict (`_market_calendar_cache`). It auto-invalidates when the date changes; no manual expiry, no TTL logic needed. Correct by construction.

---

## Flex Import Integrity

`verify_flex_import` is a manifest-based integrity check that proves every tradeID in the source XML archives is present in SQLite. It does **not** analyse activity patterns — use `check_flex_coverage` for that.

### How it works

```
Drive account_data/
  ClaudIA_Full_Activity_2024.xml  ← manual (pre-validated by user)
  flex_U123_2024-06-15_REF.xml   ← auto (archived by sync_flex_trades)
  flex_U123_2024-06-20_REF2.xml  ← auto
```

1. **Manual archives** (`ClaudIA_Full_Activity_*.xml`) — registered in the manifest on first encounter with `source='manual'` and `verified_at` already set. Never re-verified — user confirmed integrity at import time.
2. **Auto-synced archives** (`flex_U*.xml`) — manifest row written at sync time with SHA-256 and `verified_at=now` (tradeIDs were just upserted, import is verified by definition). On re-check: SHA-256 compared to manifest. If hash matches, the full tradeID scan is skipped — file unchanged since sync. Hash mismatch (or first encounter) triggers a full cross-check.

### Import manifest — `flex_import_log` table

| Column | Description |
|---|---|
| `filename` | Drive filename (unique per file) |
| `sha256` | SHA-256 of XML bytes at log time |
| `trade_id_count` | Unique tradeIDs in the XML |
| `raw_trade_count` | Total `<Trade>` elements — if `raw != unique`, within-file duplicate tradeIDs detected |
| `source` | `'manual'` or `'auto'` |
| `imported_at` | UTC timestamp of first log |
| `verified_at` | UTC timestamp of last successful integrity check (`NULL` until first check) |

### What it catches

| Condition | Result |
|---|---|
| tradeID in XML but missing from SQLite | `✗ N missing` — re-import required |
| `raw_count != unique_count` | `⚠ within-file duplicate tradeIDs` — flagged transparently (should never occur from IBKR) |
| Drive file modified after sync | Hash mismatch → full cross-check triggered automatically |

### What it does NOT do

- Never modifies trade data — IBKR XML is the authority; SQLite is never "corrected" against anything other than a fresh pull
- Gaps in trade-date coverage are not flagged — inactivity (holding a position) appears as a gap; that is correct data, not a coverage hole

---

## ClaudIA integration

[ClaudIA](https://github.com/stephus182/claudia_ui) is a Panel-based trading assistant that imports `ibkr_core_mcp` directly as a Python package and drives it via `ClaudeToolkit`. If you want a ready-made conversational UI on top of this library, start there.

---

## Development

```bash
# Unit tests (no IBKR connection needed)
pytest -m "not integration"

# All tests (requires running IBKR gateway + credentials)
pytest

# Security invariants only (~10 s)
pytest -m security

# Lint + type check
ruff check .            # includes pydocstyle D — every public definition needs a docstring
ruff format --check .
mypy

# Dependency audit (network). CI audits a FRESH RESOLVE of the extras in requirements mode —
# `pip install --dry-run` in a throwaway venv, installing nothing — not this machine's installed
# tree, which reports what happens to be here and produced a near-miss on 2026-09-16. Same
# command as .github/workflows/ci.yml, minus the ignore-file flags:
printf '.[dev,server,scraper]\n' > /tmp/audit-requirements.txt
pip-audit --strict --desc --vulnerability-service osv -r /tmp/audit-requirements.txt
```

Docstring coverage is enforced in CI: `ruff`'s `pydocstyle` (`D`) rules are enabled, so a new
public module, class, method, function, or `__init__` without a docstring fails the lint.
Formatting-opinion codes (imperative mood, trailing periods, and similar) are deliberately
disabled — see the annotated `ignore` list in `pyproject.toml` for what is off and why.

---

## License

MIT
