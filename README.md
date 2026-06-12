# ibkr_core_mcp

Python library for Interactive Brokers clients. Wraps the IBKR Client Portal API and ships batteries-included tooling for algorithmic trading, backtesting, real-time streaming, and Claude AI integration.

> **Who is this for?** IBKR account holders who want to automate market data retrieval, portfolio monitoring, and order staging from Python — or who want to connect an AI assistant to their brokerage.

---

## Feature overview

| Module | What it does |
|---|---|
| `GatewayManager` | Builds and runs the official IBKR Client Portal Gateway as a Docker container, guides browser login + 2FA |
| `IBKRClient` | Full REST client for the Client Portal API — market data, positions, orders, scanners |
| `ClaudeToolkit` | 33 ready-made Claude AI tools (`tools=` parameter) for Anthropic SDK integration |
| `SQLiteStore` | Local SQLite store — trade history, price alerts, session log |
| `GDriveCache` | Google Drive Parquet cache for OHLCV data |
| `streaming` | IBKR WebSocket live quotes + price alert engine |
| `backtest` | Safe sandboxed strategy backtester |
| `indicators` | Technical indicators (RSI, MACD, Bollinger, ATR, VWAP, …) |
| `analytics` | Portfolio analytics — drawdown, Sharpe, Beta, return attribution |
| `pinescript` | PineScript v5 generator |
| `mcp_server` | MCP server (stdio + SSE) exposing all 33 tools to any MCP client |

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

## Installation

```bash
pip install ibkr_core_mcp
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
    model="claude-opus-4-8",
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
| `get_live_orders` | Working orders (Submitted, PreSubmitted, Inactive, …) |
| `get_order_status` | Status of a specific order by ID |
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
| `delete_alert` | Delete an IBKR price alert |
| `activate_alert` | Enable or disable an IBKR price alert |
| `get_watchlists` | List IBKR watchlists and their contents |
| `add_indicators` | Compute RSI, MACD, Bollinger, ATR, VWAP, … |
| `run_backtest` | Sandboxed RestrictedPython strategy backtester |
| `generate_pinescript` | Generate PineScript v5 strategy/indicator |
| `get_analytics` | Sharpe, Sortino, Calmar, CAGR, max drawdown |

---

## MCP server

Expose all 33 tools to any MCP-compatible client (Claude Desktop, Cursor, etc.):

```bash
# stdio transport (Claude Desktop / Cursor)
python -m ibkr_core_mcp.mcp_server

# SSE transport with live streaming
python -m ibkr_core_mcp.mcp_server --transport sse --port 8765 --streaming
```

---

## Streaming (live quotes)

```python
import asyncio
from ibkr_core_mcp.streaming import IBKRWebSocket

# IBKRWebSocket takes the gateway URL and a session cookie string
ws = IBKRWebSocket(gateway_url="wss://localhost:5055", session_cookie="")

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
| `IBKR_SQLITE_PATH` | ✅ | SQLite store path (e.g. `~/.ibkr_core/store.db`) |
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
