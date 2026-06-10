# ibkr_core_mcp

Python library for Interactive Brokers clients. Wraps the IBKR Client Portal API and ships batteries-included tooling for algorithmic trading, backtesting, real-time streaming, and Claude AI integration.

> **Who is this for?** IBKR account holders who want to automate market data retrieval, portfolio monitoring, and order staging from Python — or who want to connect an AI assistant to their brokerage.

---

## Feature overview

| Module | What it does |
|---|---|
| `GatewayManager` | Builds and runs the official IBKR Client Portal Gateway as a Docker container, guides browser login + 2FA |
| `IBKRClient` | Full REST client for the Client Portal API — market data, positions, orders, scanners |
| `ClaudeToolkit` | 22 ready-made Claude AI tools (`tools=` parameter) for Anthropic SDK integration |
| `SQLiteStore` | Local SQLite store — trade history, price alerts, session log |
| `GDriveCache` | Google Drive Parquet cache for OHLCV data |
| `streaming` | IBKR WebSocket live quotes + price alert engine |
| `backtest` | Safe sandboxed strategy backtester |
| `indicators` | Technical indicators (RSI, MACD, Bollinger, ATR, VWAP, …) |
| `analytics` | Portfolio analytics — drawdown, Sharpe, Beta, return attribution |
| `pinescript` | PineScript v5 generator |
| `mcp_server` | MCP server (stdio + SSE) exposing all 22 tools to any MCP client |

---

## Requirements

- Python 3.11+
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (for `GatewayManager`)
- An **Interactive Brokers** account (live or paper)
- Anthropic API key (for Claude AI tools / MCP server)

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
from ibkr_core_mcp import IBKRClient, BrowserCookieAuth, SQLiteStore, Config

config = Config()                      # reads env vars / .env
store  = SQLiteStore(config.sqlite_path)
client = IBKRClient(auth=BrowserCookieAuth(), store=store, config=config)

summary   = client.get_account_summary()
positions = client.get_positions()
bars      = client.get_market_data("AAPL", period="1Y", bar="1d")
```

### 3. Use Claude AI tools

```python
import anthropic
from ibkr_core_mcp import ClaudeToolkit, IBKRClient, SQLiteStore, GDriveCache, Config

config  = Config()
store   = SQLiteStore(config.sqlite_path)
cache   = GDriveCache(config)
client  = IBKRClient(auth=BrowserCookieAuth(), store=store, config=config)
toolkit = ClaudeToolkit(client=client, store=store, cache=cache, config=config)

ai = anthropic.Anthropic()

response = ai.messages.create(
    model="claude-opus-4-8",
    max_tokens=4096,
    tools=toolkit.tool_definitions(),       # drop-in for Anthropic SDK
    messages=[{"role": "user", "content": "What are my current positions?"}],
)

# Route tool calls back through the toolkit
for block in response.content:
    if block.type == "tool_use":
        result = toolkit.call_tool(block.name, block.input)
```

---

## Available tools (Claude AI / MCP)

| Tool | Description |
|---|---|
| `fetch_market_data` | OHLCV history with Google Drive cache |
| `check_cache` | Check whether data is cached |
| `list_cache` | List all cached datasets |
| `get_account_summary` | Net liquidation, cash, P&L |
| `get_positions` | All open positions |
| `get_trades` | Trade history (live: last 6 days; store: unlimited) |
| `sync_flex_trades` | Sync full history via IBKR Flex Web Service |
| `get_live_orders` | Open / pending orders |
| `get_ledger` | Cash balances by currency |
| `get_allocation` | Portfolio breakdown by asset class |
| `get_pa_performance` | Portfolio Analyst NAV performance |
| `get_pa_transactions` | Portfolio Analyst transactions |
| `get_contract_info` | Contract details (conid, exchange, trading hours) |
| `get_option_chain` | Options chain — expirations, strikes, conids |
| `run_scanner` | Market scanner (top gainers, losers, most active, …) |
| `get_notifications` | IBKR account notifications |
| `add_indicators` | Compute RSI, MACD, Bollinger, ATR, VWAP, … |
| `run_backtest` | Sandboxed strategy backtester |
| `generate_pinescript` | Generate PineScript v5 strategy/indicator |
| `get_analytics` | Drawdown, Sharpe, Beta, return attribution |
| `preview_order` | Whatif order preview — no order placed |
| `get_pnl` | Real-time P&L partitioned by account/position |

---

## MCP server

Expose all 22 tools to any MCP-compatible client (Claude Desktop, Cursor, etc.):

```bash
# stdio transport (Claude Desktop / Cursor)
python -m ibkr_core_mcp.mcp_server

# SSE transport with live streaming
python -m ibkr_core_mcp.mcp_server --transport sse --port 8765 --streaming
```

---

## Streaming (live quotes + price alerts)

```python
from ibkr_core_mcp.streaming import IBKRWebSocket, AlertManager, SQLiteStore, Config

config = Config()
store  = SQLiteStore(config.sqlite_path)

# Live quotes
ws = IBKRWebSocket(config=config)
await ws.subscribe(["AAPL", "TSLA"])

# Price alerts
manager = AlertManager(store=store, client=client, config=config)
await manager.add_alert("AAPL", target_price=200.0, direction="above")
```

---

## Backtesting

```python
from ibkr_core_mcp.backtest import run_backtest

result = run_backtest(
    bars=bars_dataframe,       # pandas DataFrame with OHLCV columns
    strategy_code="""
def strategy(bars):
    return bars['close'].pct_change().fillna(0)
""",
)
print(result.sharpe, result.max_drawdown)
```

Strategy code runs in a `RestrictedPython` sandbox — no file system or network access.

---

## Environment variables

Copy `.env.example` to `.env` and fill in:

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | if using Claude tools | Anthropic API key |
| `IBKR_GATEWAY_URL` | ✅ | Client Portal URL (default: `https://localhost:5055`) |
| `IBKR_SQLITE_PATH` | ✅ | SQLite store path (e.g. `~/.ibkr_core/store.db`) |
| `GOOGLE_DRIVE_FOLDER_ID` | for GDrive cache | Drive folder for Parquet cache |
| `GDRIVE_TOKEN_FILE` | for GDrive cache | OAuth2 token path |
| `GDRIVE_CREDENTIALS_FILE` | for GDrive cache | OAuth2 credentials path |
| `IBKR_FLEX_TOKEN` | for Flex sync | Flex Web Service token |
| `IBKR_FLEX_QUERY_ID` | for Flex sync | Flex query ID |

---

## Security

**ibkr_core_mcp does not place orders autonomously.** The `place_order` and `reply_order` methods on `IBKRClient` exist but are gated behind `require_touch_id()` — a macOS biometric authentication check (Apple Touch ID / LocalAuthentication framework) that must pass before the HTTP call is made.

A second gate (tkinter modal with a 60-second countdown, Enter key disabled) is provided in downstream consumers such as [ClaudIA](https://github.com/stephus182/claudia_ui).

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
