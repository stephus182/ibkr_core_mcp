# MCP Server — Full Reference

`ibkr_core_mcp` ships a built-in MCP server exposing 44 tools and 4 resources.
Any MCP-compatible client — Claude Desktop, a custom chatbot, a dashboard, or an
ML pipeline — connects without requiring the `anthropic` SDK.

## Install

```bash
pip install "ibkr_core_mcp[server]"
```

## stdio — Claude Desktop

```bash
python -m ibkr_core_mcp.mcp_server
```

Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "ibkr": {
      "command": "/path/to/.venv/bin/python",
      "args": ["-m", "ibkr_core_mcp.mcp_server"],
      "env": {
        "IBKR_GATEWAY_URL": "https://localhost:5055/v1/api",
        "ANTHROPIC_API_KEY": "sk-ant-...",
        "GOOGLE_DRIVE_FOLDER_ID": "...",
        "IBKR_SQLITE_PATH": "~/.ibkr_core/store.db",
        "GDRIVE_TOKEN_FILE": "~/.ibkr_core/token_ibkr_core_mcp.json",
        "GDRIVE_CREDENTIALS_FILE": "~/.ibkr_core/credentials_ibkr_core_mcp.json"
      }
    }
  }
}
```

## HTTP/SSE — dashboard and chatbots

```bash
# Read-only (no streaming)
python -m ibkr_core_mcp.mcp_server --transport sse --port 5174

# With WebSocket live quotes and price alerts
python -m ibkr_core_mcp.mcp_server --transport sse --port 5174 --stream
```

The server binds to `127.0.0.1` only — never exposed to external networks.
Connect MCP clients to `http://localhost:5174/sse`.

## Tools (44)

All 42 `ClaudeToolkit` tools plus:
- `add_price_alert` — register a threshold alert (persisted to SQLite)
- `get_price_alerts` — list active or all alerts

## Resources

| URI | Content |
|---|---|
| `ibkr://accounts` | All IBKR accounts |
| `ibkr://positions/current` | Current positions for primary account |
| `ibkr://trades/recent` | Last 100 trades from SQLite |
| `ibkr://pnl/live` | Latest account P&L snapshot (WebSocket `spl` topic, `--stream` only) |

## Price alerts (programmatic)

```python
import asyncio
from ibkr_core_mcp import Config, IBKRWebSocket, AlertManager, SQLiteStore
from ibkr_core_mcp.auth import BrowserCookieAuth
import requests

async def main():
    cfg = Config.from_env()
    store = SQLiteStore(cfg)

    session = requests.Session()
    BrowserCookieAuth().apply(session)
    cookie = session.headers.get("Cookie", "")

    ws = IBKRWebSocket(cfg.gateway_url, cookie)
    await ws.connect()
    await ws.subscribe(265598)  # AAPL conid

    store.add_alert(265598, "AAPL", 185.0, "above")
    manager = AlertManager(store)

    async for quote in ws.listen():
        for alert in manager.check_quote(quote):
            print(f"ALERT: {alert['symbol']} hit {alert['threshold']}")

asyncio.run(main())
```

## TradingView integration

`tradingview-mcp` (MIT, Node.js) connects to TradingView Desktop via Chrome
DevTools Protocol and exposes 78 tools: chart reading, PineScript injection,
drawings, and replay. Run it alongside ibkr-core-mcp so Claude can read live
charts and query your IBKR account in the same conversation:

```json
{
  "mcpServers": {
    "ibkr":        { "command": "python", "args": ["-m", "ibkr_core_mcp.mcp_server"], "env": { "..." : "..." } },
    "tradingview": { "command": "npx",    "args": ["-y", "tradingview-mcp"] }
  }
}
```

See: https://github.com/tradesdontlie/tradingview-mcp
