# ibkr_core_mcp Phase 3 — MCP Server + Live Data Streaming

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose all ibkr_core_mcp capabilities as a proper MCP server so multiple client apps (dashboard, trading chatbot, ML/analysis chatbot, Claude Desktop) can connect simultaneously; add real-time quote streaming via IBKR WebSocket with SQLite-persisted price alerts and MCP log notifications.

**Architecture:** Two new modules — `streaming.py` (async WebSocket client + AlertManager) and `mcp_server.py` (low-level `mcp.Server` wrapping all 22 tools + 3 MCP resources). The MCP server supports both **stdio** (Claude Desktop) and **HTTP/SSE on localhost only** (dashboard, chatbots). Existing sync codebase is unchanged.

**Design principles applied:**
- Low-level `mcp.Server` API for clean dynamic tool registration — no FastMCP hacks, no `__mcp_input_schema__` injection
- Single dispatcher (`_dispatch`) routes all tool calls — no loops, no redundancy
- WebSocket streaming is optional (`--stream` flag); server works fully without it
- SSE transport binds to `127.0.0.1` only — never `0.0.0.0`
- All tool errors go through `_safe_error` — no raw exceptions reach MCP clients
- No order-write tools exposed (same guarantee as `ClaudeToolkit`)

**Version target:** 0.4.0  
**Status:** ✅ Complete — tagged `v0.4.0`, pushed to GitHub  
**Commits:** `6e571c2`, `3fc2790`, `faaccec`, `76428dc`, `237a8e6`

---

## Context

`ClaudeToolkit` already wraps IBKR in 20 tools but requires the `anthropic` SDK in every consuming app. Phase 3 lifts those tools onto MCP so any host can use them without brokerage-specific glue code.

**Client ecosystem:**

| Client | Transport | What it uses |
|---|---|---|
| Claude Desktop | stdio | All 22 tools + resources |
| Trading chatbot UI | HTTP/SSE :5174 | Account, orders, alerts, live quotes |
| ML/analysis chatbot | HTTP/SSE :5174 | Market data, indicators, backtest, PineScript |
| Personal dashboard | HTTP/SSE :5174 | Positions, trades (resources) |

**TradingView complement:** `tradingview-mcp` (MIT, Node.js, runs separately) connects to TradingView Desktop via Chrome DevTools Protocol on `localhost:9222` and exposes 78 tools. Configure Claude Desktop with both servers — no code coupling needed. See: https://github.com/tradesdontlie/tradingview-mcp

---

## Architecture

```
IBKR Gateway (localhost:5055)
  │  REST (existing)          │  wss://localhost:5055/v1/api/ws (new, optional)
  ▼                           ▼
IBKRClient               IBKRWebSocket ──► LiveQuote stream
     │                                           │
     └─── ClaudeToolkit (20 tools) ──────── AlertManager ──► SQLite + log notification
                    │
              mcp_server.py
              ├── list_tools()  → 22 Tool definitions
              ├── call_tool()   → _dispatch(name, args)
              ├── list_resources() / read_resource()
              └── (streaming) background asyncio task when --stream
                    │
          ┌─────────┴──────────┐
     stdio transport      SSE :5174 (127.0.0.1 only)
          │                    │
    Claude Desktop      Dashboard / Chatbots
```

---

## File Map

| File | Action |
|---|---|
| `ibkr_core_mcp/streaming.py` | **Create** — `IBKRWebSocket`, `LiveQuote`, `AlertManager` |
| `ibkr_core_mcp/store.py` | **Modify** — add `price_alerts` table + 3 methods |
| `ibkr_core_mcp/exceptions.py` | **Modify** — add `StreamingError` |
| `ibkr_core_mcp/mcp_server.py` | **Create** — MCP server, 22 tools, 3 resources, stdio+SSE |
| `ibkr_core_mcp/__init__.py` | **Modify** — export new symbols, bump to 0.4.0 |
| `pyproject.toml` | **Modify** — `[server]` optional extras, `pytest-asyncio` in dev |
| `tests/test_streaming.py` | **Create** |
| `tests/test_mcp_server.py` | **Create** |
| `CLAUDE.md` | **Modify** — MCP server setup, streaming, TradingView note |

**Existing code reused (no modification):**
- `claude_tools.py` — `ClaudeToolkit`, `TOOL_DEFINITIONS`, `_safe_error`, `_validate_account_id`
- `config.py` — `Config.from_env()`, `Config.gateway_url`
- `auth.py` — `BrowserCookieAuth` to extract session cookie for WebSocket auth
- `store.py` — `SQLiteStore` (extended with alerts)

---

## Task 1: `streaming.py` + `store.py` price_alerts + `StreamingError`

**Files:**
- `ibkr_core_mcp/exceptions.py` — add `StreamingError`
- `ibkr_core_mcp/store.py` — add `price_alerts` table + 3 methods
- `ibkr_core_mcp/streaming.py` — create
- `tests/test_streaming.py` — create

- [x] **Step 1: Add `StreamingError` to `exceptions.py`**

Append after `FlexQueryError`:
```python
class StreamingError(IBKRCoreError):
    """Raised when the IBKR WebSocket connection fails or returns an unexpected message."""
```

- [x] **Step 2: Add `price_alerts` table + methods to `store.py`**

In `initialize()`, inside the `executescript` block, add:
```sql
CREATE TABLE IF NOT EXISTS price_alerts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    conid        INTEGER NOT NULL,
    symbol       TEXT    NOT NULL,
    threshold    REAL    NOT NULL,
    direction    TEXT    NOT NULL CHECK (direction IN ('above', 'below')),
    created_at   TEXT    NOT NULL,
    triggered_at TEXT
);
```

Add three methods to `SQLiteStore` (after `save_backtest`):
```python
def add_alert(self, conid: int, symbol: str, threshold: float, direction: str) -> int:
    """Insert a price alert. direction must be 'above' or 'below'. Returns new id."""
    if direction not in ("above", "below"):
        raise ValueError(f"direction must be 'above' or 'below', got {direction!r}")
    self.initialize()
    now = datetime.now(tz=timezone.utc).isoformat()
    with self._connect() as conn:
        cur = conn.execute(
            "INSERT INTO price_alerts (conid, symbol, threshold, direction, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (conid, symbol.upper(), threshold, direction, now),
        )
        return cur.lastrowid or 0

def get_alerts(self, active_only: bool = True) -> list[dict]:
    """Return alerts; active_only=True excludes already-triggered alerts."""
    self.initialize()
    query = "SELECT * FROM price_alerts"
    if active_only:
        query += " WHERE triggered_at IS NULL"
    query += " ORDER BY created_at DESC"
    with self._connect() as conn:
        return [dict(r) for r in conn.execute(query).fetchall()]

def mark_alert_triggered(self, alert_id: int) -> None:
    """Record that an alert fired by setting triggered_at to now."""
    self.initialize()
    now = datetime.now(tz=timezone.utc).isoformat()
    with self._connect() as conn:
        conn.execute(
            "UPDATE price_alerts SET triggered_at = ? WHERE id = ?",
            (now, alert_id),
        )
```

- [x] **Step 3: Write failing tests** (`tests/test_streaming.py` — 12 tests)

- [x] **Step 4: Run tests to verify they fail** — `ImportError` on streaming module confirmed

- [x] **Step 5: Create `ibkr_core_mcp/streaming.py`**

```python
from __future__ import annotations
import json
import ssl
from dataclasses import dataclass
from typing import AsyncGenerator, TYPE_CHECKING

if TYPE_CHECKING:
    from ibkr_core_mcp.store import SQLiteStore

_FIELD_MAP = {"31": "last", "84": "bid", "86": "ask", "87": "volume",
              "55": "symbol", "70": "high", "71": "low"}
_DEFAULT_FIELDS = ["31", "55", "84", "86", "87"]


@dataclass
class LiveQuote:
    conid: int
    symbol: str = ""
    last: float | None = None
    bid: float | None = None
    ask: float | None = None
    volume: float | None = None
    high: float | None = None
    low: float | None = None


class IBKRWebSocket:
    """Async WebSocket client for IBKR real-time market data."""

    def __init__(self, gateway_url: str, session_cookie: str) -> None:
        base = gateway_url.rstrip("/")
        self._ws_url = base.replace("https://", "wss://").replace("http://", "ws://") + "/v1/api/ws"
        self._cookie = session_cookie   # not logged anywhere
        self._ws = None

    async def connect(self) -> None:
        import websockets  # optional dep — only imported when streaming is used
        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        self._ws = await websockets.connect(
            self._ws_url, ssl=ssl_ctx,
            additional_headers={"Cookie": self._cookie},
            ping_interval=20, ping_timeout=10,
        )

    async def subscribe(self, conid: int, fields: list[str] | None = None) -> None:
        if self._ws is None:
            raise RuntimeError("Call connect() first")
        await self._ws.send(f'smd+{conid}+{json.dumps({"fields": fields or _DEFAULT_FIELDS})}')

    async def unsubscribe(self, conid: int) -> None:
        if self._ws is not None:
            await self._ws.send(f"umd+{conid}+{{}}")

    async def listen(self) -> AsyncGenerator[LiveQuote, None]:
        if self._ws is None:
            raise RuntimeError("Call connect() first")
        async for raw in self._ws:
            quote = self._parse_message(raw)
            if quote is not None:
                yield quote

    async def disconnect(self) -> None:
        if self._ws is not None:
            await self._ws.close()
            self._ws = None

    def _parse_message(self, raw: str) -> LiveQuote | None:
        try:
            msg = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
        topic = msg.get("topic", "")
        if not topic.startswith("smd+"):
            return None
        data_list = msg.get("data", [])
        if not data_list:
            return None
        data = data_list[0]
        try:
            conid = int(data.get("conid", topic.split("+")[1]))
        except (ValueError, IndexError):
            return None
        kwargs: dict = {"conid": conid}
        for code, attr in _FIELD_MAP.items():
            if code not in data:
                continue
            val = data[code]
            if attr == "symbol":
                kwargs[attr] = str(val)
            else:
                try:
                    kwargs[attr] = float(val)
                except (TypeError, ValueError):
                    pass
        return LiveQuote(**kwargs)


class AlertManager:
    """Check live quotes against active price alerts; mark triggered ones in SQLite."""

    def __init__(self, store: "SQLiteStore") -> None:
        self._store = store

    def check_quote(self, quote: LiveQuote) -> list[dict]:
        """Return newly-triggered alerts and mark them triggered. Returns [] if last is None."""
        if quote.last is None:
            return []
        active = [a for a in self._store.get_alerts(active_only=True) if a["conid"] == quote.conid]
        triggered = []
        for alert in active:
            hit = (
                (alert["direction"] == "above" and quote.last >= alert["threshold"])
                or (alert["direction"] == "below" and quote.last <= alert["threshold"])
            )
            if hit:
                self._store.mark_alert_triggered(alert["id"])
                triggered.append(alert)
        return triggered
```

- [x] **Step 6: Run tests** — 12/12 pass

- [x] **Step 7: Run full suite** — 164/164 pass

- [x] **Step 8: Commit** — `6e571c2`

> **Implementation note:** Also added `price_alerts` to `test_initialize_creates_tables` in `tests/test_store.py` (commit `3fc2790`), caught during code quality review.

---

## Task 2: MCP Server (`mcp_server.py`)

**Design notes:**
- Uses low-level `mcp.server.Server` (not FastMCP) — mcp 1.27.1 installed
- Single `_dispatch()` function handles all tool calls
- SSE transport binds to `127.0.0.1` only
- `_safe_error` wraps every tool call
- No order-write tools
- Streaming runs as an asyncio background task; server works without it
- `server_version` reads from `__version__` (not hardcoded) to stay in sync
- `main()` creates one `SQLiteStore` shared by both `ClaudeToolkit` and `build_server`

**Tools exposed (22):** 20 existing ClaudeToolkit tools + `add_price_alert` + `get_price_alerts`

**Resources (3):** `ibkr://accounts`, `ibkr://positions/current`, `ibkr://trades/recent`

- [x] **Step 1: Install MCP extras**

```bash
pip install "mcp>=1.0" "starlette>=0.40" "uvicorn>=0.30" "pytest-asyncio>=0.23"
```

- [x] **Step 2: Write failing tests** (`tests/test_mcp_server.py` — 6 tests)

> **Note:** `test_server_has_22_tools` uses `server.request_handlers[ListToolsRequest]` — not `_tool_handlers` (doesn't exist in mcp 1.27). `asyncio_mode = "auto"` makes `@pytest.mark.asyncio` unnecessary on async tests.

- [x] **Step 3: Run tests to verify they fail** — `ImportError` confirmed

- [x] **Step 4: Create `ibkr_core_mcp/mcp_server.py`**

Key implementation:

```python
from ibkr_core_mcp import __version__
from ibkr_core_mcp.claude_tools import TOOL_DEFINITIONS, ClaudeToolkit, _safe_error

_ALL_TOOL_DEFS = list(TOOL_DEFINITIONS) + [_ADD_ALERT_DEF, _GET_ALERTS_DEF]  # 22 total
_EXISTING_TOOL_NAMES = frozenset(t["name"] for t in TOOL_DEFINITIONS)

def _dispatch(name, args, toolkit, store) -> str:
    try:
        if name in _EXISTING_TOOL_NAMES:
            text, _ = toolkit.execute(name, args)
            return text
        if name == "add_price_alert":
            aid = store.add_alert(int(args["conid"]), str(args["symbol"]),
                                  float(args["threshold"]), str(args["direction"]))
            return f"Alert #{aid} created: ..."
        if name == "get_price_alerts":
            alerts = store.get_alerts(active_only=bool(args.get("active_only", True)))
            return "No price alerts." if not alerts else "\n".join(...)
        return f"Unknown tool: {name!r}"
    except Exception as exc:
        return _safe_error(name, exc)

def build_server(toolkit, store) -> Server:
    server = Server("ibkr-core-mcp")
    # list_tools, call_tool, list_resources, read_resource registered here
    # read_resource catches Exception broadly and logs warning before returning "[]"
    return server

# _run_sse: host="127.0.0.1", never 0.0.0.0
# main(): store = SQLiteStore(cfg); toolkit = ClaudeToolkit(..., store, ...); shared instance
```

- [x] **Step 5: Add `asyncio_mode = "auto"` to `pyproject.toml`**

- [x] **Step 6: Run tests** — 6/6 pass

- [x] **Step 7: Run full suite** — 170/170 pass

- [x] **Step 8: Commit** — `faaccec`, then quality fixes in `76428dc`

---

## Task 3: Wiring — exports, deps, CLAUDE.md, version 0.4.0

- [x] **Step 1: Update `__init__.py`**

```python
from ibkr_core_mcp.streaming import IBKRWebSocket, LiveQuote, AlertManager
# StreamingError added to exceptions import block
# __version__ = "0.4.0"
# __all__ updated with IBKRWebSocket, LiveQuote, AlertManager, StreamingError
```

- [x] **Step 2: Update `pyproject.toml`**

```toml
version = "0.4.0"

[project.optional-dependencies]
server = [
    "mcp>=1.0",
    "starlette>=0.40",
    "uvicorn>=0.30",
    "websockets>=12.0",
]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23", "pytest-mock>=3.12", "mypy>=1.8", "ruff>=0.3"]
```

- [x] **Step 3: Add `## MCP Server` section to `CLAUDE.md`** — inserted before `## Adding a New IBKR Endpoint`

- [x] **Step 4: Run full suite** — 170 pass, imports OK, 22 tools confirmed

- [x] **Step 5: Commit, tag, push** — commit `237a8e6`, tag `v0.4.0` pushed

---

## Security checklist

- [x] SSE transport binds to `127.0.0.1`, not `0.0.0.0`
- [x] All tool dispatch goes through `_dispatch()` which calls `_safe_error` on any exception
- [x] No order-write tools present
- [x] Session cookie passed to `IBKRWebSocket` is not logged at any level
- [x] `direction` field validated (SQLite `CHECK` constraint + `ValueError` in `store.add_alert`)
- [x] `conid` cast to `int` in `_dispatch` before use
- [x] Resources return `"[]"` on any exception (broad catch + `logger.warning`)
- [x] `websockets` import is deferred inside `connect()`

---

## Verification

```bash
# All unit tests
pytest -m "not integration" -q
# → 170 passed

# Confirm imports
python -c "from ibkr_core_mcp import IBKRWebSocket, LiveQuote, AlertManager, StreamingError; print('OK')"

# Confirm 22 tools registered
python -c "
from ibkr_core_mcp.mcp_server import _ALL_TOOL_DEFS
assert len(_ALL_TOOL_DEFS) == 22
print('22 tools OK')
"

# Start server (stdio)
echo '{}' | python -m ibkr_core_mcp.mcp_server --transport stdio || true
```
