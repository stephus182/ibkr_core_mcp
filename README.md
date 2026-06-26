# ibkr_core_mcp

Python library for Interactive Brokers clients. Wraps the IBKR Client Portal API and ships batteries-included tooling for algorithmic trading, backtesting, real-time streaming, and Claude AI integration.

> **Who is this for?** IBKR account holders who want to automate market data retrieval, portfolio monitoring, and order staging from Python — or who want to connect an AI assistant to their brokerage.

---

## Feature overview

| Module | What it does |
|---|---|
| `GatewayManager` | Builds and runs the official IBKR Client Portal Gateway as a Docker container, guides browser login + 2FA |
| `IBKRClient` | Full REST client for the Client Portal API — market data, positions, orders, scanners |
| `ClaudeToolkit` | 38 ready-made Claude AI tools (`tools=` parameter) for Anthropic SDK integration |
| `SQLiteStore` | Local SQLite store — trade history, price alerts, session log |
| `GDriveCache` | Google Drive Parquet cache for OHLCV data |
| `streaming` | IBKR WebSocket live quotes + price alert engine |
| `backtest` | Safe sandboxed strategy backtester |
| `indicators` | Technical indicators (RSI, MACD, Bollinger, ATR, VWAP, …) |
| `analytics` | Portfolio analytics — drawdown, Sharpe, Sortino, Calmar, CAGR, win rate, profit factor |
| `pinescript` | PineScript v5 generator |
| `mcp_server` | MCP server (stdio + SSE) exposing all 40 tools to any MCP client |

---

## Requirements

- Python 3.11+
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (for `GatewayManager`)
- An **Interactive Brokers** account (live or paper)
- Anthropic API key (for Claude AI tools / MCP server)

### macOS — required for order execution

Order write methods (`place_order`, `modify_order`, `cancel_order`, `reply_order`) are gated by Touch ID. This gate is enforced inside the library and **cannot be bypassed**. It requires:

| Requirement | Minimum |
|---|---|
| Operating system | macOS 10.12.1 (Sierra) |
| Hardware | Any Mac with a built-in Touch ID sensor or a [Touch ID keyboard](https://www.apple.com/shop/product/MK293LL/A/) |
| Python package | `pyobjc-framework-LocalAuthentication` (installed automatically with `ibkr_core_mcp`) |
| Policy | `LAPolicyDeviceOwnerAuthenticationWithBiometrics` — biometric only, **no password fallback** |

Touch ID is available on: MacBook Pro (late 2016+), MacBook Air (2018+), Mac mini (2020+), iMac (2021+), Mac Studio, Mac Pro (2023+).

**Linux / Windows:** All read-only tools (market data, portfolio queries, backtesting, analytics, MCP server) work on any platform. Order execution is macOS-only by design.

---

## API Documentation

This library is built on official documented APIs. Any contribution touching API behavior, error codes, endpoint paths, or field names **must reference the official source** — never assume from memory or training data.

| API | Official reference |
|---|---|
| IBKR Client Portal API | https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/ |
| IBKR Flex Web Service | https://www.ibkrguides.com/clientportal/performanceandstatements/flex3.htm |
| Flex error codes | https://www.ibkrguides.com/clientportal/performanceandstatements/flex3error.htm |
| IBKR WebSocket streaming | https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#websockets |
| Google Drive API v3 | https://developers.google.com/drive/api/reference/rest/v3 |
| macOS LocalAuthentication | https://developer.apple.com/documentation/localauthentication |

Full details and per-file API ownership are in [`CLAUDE.md`](CLAUDE.md#ibkr-api-reference--docs-first).

---

## Installation

```bash
pip install git+https://github.com/stephus182/ibkr_core_mcp.git
```

Or pin to a specific version:

```bash
pip install git+https://github.com/stephus182/ibkr_core_mcp.git@v0.4.0
```

Or for local development:

```bash
git clone https://github.com/stephus182/ibkr_core_mcp.git
cd ibkr_core_mcp
pip install -e ".[dev]"
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

Or use the programmatic API (for non-interactive environments like Chainlit):

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
        text, fig = toolkit.execute(block.name, block.input)
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
| `search_contract` | Resolve symbol → conid, exchange, currency |
| `get_contract_info` | Full contract details (exchange, trading hours, etc.) |
| `get_option_chain` | Options chain — expirations, strikes, conids |
| `get_futures` | Futures contracts — expiry months, conids |
| `get_market_snapshot` | Live bid/ask/last/volume for one or more symbols |
| `get_trading_schedule` | Trading hours and next session for a symbol |
| `run_scanner` | Market scanner (top gainers, losers, most active, …) |
| `get_notifications` | IBKR FYI account notifications |
| `get_alerts` | List IBKR native price alerts |
| `create_price_alert` | Create a server-side IBKR price alert |
| `modify_price_alert` | Update threshold or direction on an existing IBKR alert |
| `delete_alert` | Delete an IBKR price alert |
| `activate_alert` | Enable or disable an IBKR price alert |
| `get_watchlists` | List IBKR watchlists and their contents |
| `add_indicators` | Compute RSI, MACD, Bollinger, ATR, VWAP, … |
| `run_backtest` | Sandboxed RestrictedPython strategy backtester |
| `generate_pinescript` | Generate PineScript v5 strategy/indicator |
| `get_analytics` | Sharpe, Sortino, Calmar, CAGR, max drawdown |

---

## MCP server

Expose all 38 tools (+ 2 MCP-only alert tools = 40 total) to any MCP-compatible client (Claude Desktop, Cursor, etc.):

```bash
# stdio transport (Claude Desktop / Cursor)
python -m ibkr_core_mcp.mcp_server

# SSE transport with live streaming
python -m ibkr_core_mcp.mcp_server --transport sse --port 5174 --stream
```

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

For price alerts, use the native IBKR alert system via `ClaudeToolkit.execute("create_price_alert", ...)`
— alerts fire server-side and deliver to the IBKR mobile app even when the app is closed.

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

result = run_backtest(code=code, df=bars_dataframe, strategy_name="EMA crossover", symbol="AAPL")
print(result.sharpe, result.max_drawdown, result.total_return)
```

Strategy code runs in a `RestrictedPython` sandbox — no file system or network access.
4096-character limit; 10-second timeout. Available: `df`, `pd`, `np`.

---

## Environment variables

Copy `.env.example` to `.env` and fill in:

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | ✅ for `Config.from_env()` | Anthropic API key (required by `ClaudeToolkit`; `Config.from_env()` raises if absent) |
| `IBKR_GATEWAY_URL` | ✅ | Client Portal URL (default: `https://localhost:5055`) |
| `IBKR_SQLITE_PATH` | optional | SQLite store path (default: `~/.ibkr_core/store.db`) |
| `GOOGLE_DRIVE_FOLDER_ID` | for GDrive | Root Drive folder — parent of `db/` and `market_data/` subfolders |
| `GDRIVE_DB_FOLDER_ID` | optional | Explicit folder for claudia.db. If unset, auto-created as `db/` inside `GOOGLE_DRIVE_FOLDER_ID` |
| `GDRIVE_CACHE_FOLDER_ID` | optional | Explicit Drive folder for Parquet cache. If unset, auto-created as `market_data/` inside `GOOGLE_DRIVE_FOLDER_ID` |
| `GDRIVE_TOKEN_FILE` | for GDrive | OAuth2 token path |
| `GDRIVE_CREDENTIALS_FILE` | for GDrive | OAuth2 credentials path |
| `IBKR_FLEX_TOKEN` | for Flex sync | Flex Web Service token |
| `IBKR_FLEX_QUERY_ID` | for Flex sync | Flex query ID |

---

## Security

**ibkr_core_mcp does not place orders autonomously.** Order write methods (`place_order`, `modify_order`, `cancel_order`, `reply_order`) on `IBKRClient` are gated by two sequential controls enforced at the innermost call site inside the library:

### Gate 1 — Touch ID (macOS LocalAuthentication)

Implemented in `human_auth.py` using the macOS `LocalAuthentication` framework via `pyobjc-framework-LocalAuthentication`.

- **Policy:** `LAPolicyDeviceOwnerAuthenticationWithBiometrics` — fingerprint or Face ID only
- **No fallback:** Password / PIN entry is explicitly excluded. If biometrics are unavailable the call raises `HumanAuthError` immediately.
- **Timeout:** 60 seconds. An unanswered prompt raises `HumanAuthError` and the order is not submitted.
- **Prompt text:** The caller-supplied `reason` string appears in the macOS Touch ID dialog (e.g. *"Confirm order: BUY 100 AAPL"*).
- **Thread-safe:** Uses a `threading.Event` to wait for the async `LAContext` reply callback without blocking the main run loop.

If `pyobjc-framework-LocalAuthentication` is not installed, or if the Mac hardware does not support biometrics (e.g. a Mac mini without a Touch ID keyboard attached), the gate raises `HumanAuthError` and the order is never submitted.

### Gate 2 — Visual confirmation dialog (tkinter)

Implemented in `order_confirm.py`.

- Full order details displayed in a modal window
- 60-second countdown timer — dialog auto-cancels on timeout
- **Enter key disabled** — confirmation requires a deliberate mouse click on the "Confirm" button
- Runs on the main thread; the tkinter event loop is driven internally

Both gates are part of `ibkr_core_mcp` itself. Downstream consumers such as [ClaudIA](https://github.com/stephus182/claudia_ui) can add further gates (e.g. a Chainlit "Stage this order" button click) before `place_order` is ever invoked.

`GatewayManager` runs the IBKR Client Portal Gateway as a Docker container bound to `localhost:5055` only. The container has no privileged access and exposes no host filesystem mounts. See [SECURITY.md](SECURITY.md) for the full security model.

---

## Market Calendar

`SQLiteStore.get_market_calendar_context()` uses [`exchange_calendars`](https://github.com/rsheftel/pandas_market_calendars) to provide trading-day-aware context without any API calls:

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

**100+ supported markets** including XNAS (NASDAQ), XPAR (Euronext Paris), XKRX (Korea), XBOM (Bombay), SSE (Shanghai), BVMF (Brazil), and more — [full list](https://github.com/rsheftel/exchange_calendars#calendars).

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

[ClaudIA](https://github.com/stephus182/claudia_ui) is a Chainlit-based trading assistant that imports `ibkr_core_mcp` directly as a Python package and drives it via `ClaudeToolkit`. If you want a ready-made conversational UI on top of this library, start there.

---

## Development

```bash
# Unit tests (no IBKR connection needed)
pytest -m "not integration"

# All tests (requires running IBKR gateway + credentials)
pytest

# Lint + type check
ruff check .
mypy ibkr_core_mcp
```

---

## License

MIT
