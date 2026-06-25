"""ibkr_core_mcp MCP server.

Run:
    python -m ibkr_core_mcp.mcp_server                   # stdio (Claude Desktop)
    python -m ibkr_core_mcp.mcp_server --transport sse   # HTTP/SSE on localhost:5174
    python -m ibkr_core_mcp.mcp_server --transport sse --stream  # + WebSocket streaming
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.types import Resource, TextContent, Tool
from pydantic import AnyUrl

from ibkr_core_mcp import __version__
from ibkr_core_mcp.claude_tools import TOOL_DEFINITIONS, ClaudeToolkit, _safe_error

if TYPE_CHECKING:
    from ibkr_core_mcp.store import SQLiteStore

logger = logging.getLogger(__name__)

_ADD_ALERT_DEF: dict[str, Any] = {
    "name": "add_price_alert",
    "description": (
        "Create a price alert that fires when a symbol crosses a threshold. "
        "direction must be 'above' or 'below'."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "conid":     {"type": "integer", "description": "IBKR contract ID"},
            "symbol":    {"type": "string",  "description": "Ticker symbol, e.g. 'AAPL'"},
            "threshold": {"type": "number",  "description": "Price threshold"},
            "direction": {"type": "string",  "enum": ["above", "below"]},
        },
        "required": ["conid", "symbol", "threshold", "direction"],
    },
}

_GET_ALERTS_DEF: dict[str, Any] = {
    "name": "get_price_alerts",
    "description": "List price alerts. active_only=true returns only untriggered alerts.",
    "input_schema": {
        "type": "object",
        "properties": {
            "active_only": {"type": "boolean", "default": True},
        },
    },
}

_ALL_TOOL_DEFS: list[dict[str, Any]] = list(TOOL_DEFINITIONS) + [_ADD_ALERT_DEF, _GET_ALERTS_DEF]
_EXISTING_TOOL_NAMES: frozenset[str] = frozenset(str(t["name"]) for t in TOOL_DEFINITIONS)


def _dispatch(name: str, args: dict[str, Any], toolkit: ClaudeToolkit, store: SQLiteStore) -> str:
    """Route a tool call to the right handler. Never raises — always returns str."""
    try:
        if name in _EXISTING_TOOL_NAMES:
            text, _ = toolkit.execute(name, args)
            return text
        if name == "add_price_alert":
            aid = store.add_alert(
                int(args["conid"]), str(args["symbol"]),
                float(args["threshold"]), str(args["direction"]),
            )
            sym = str(args["symbol"]).upper()
            return f"Alert #{aid} created: {sym} {args['direction']} {args['threshold']}."
        if name == "get_price_alerts":
            alerts = store.get_alerts(active_only=bool(args.get("active_only", True)))
            if not alerts:
                return "No price alerts."
            return "\n".join(
                f"#{a['id']} {a['symbol']} {a['direction']} {a['threshold']} "
                f"{'[triggered]' if a['triggered_at'] else '[active]'}"
                for a in alerts
            )
        return f"Unknown tool: {name!r}"
    except Exception as exc:
        return _safe_error(name, exc)


def build_server(toolkit: ClaudeToolkit, store: SQLiteStore) -> Server:
    """Build and return a configured MCP Server instance."""
    server = Server("ibkr-core-mcp")

    @server.list_tools()
    async def handle_list_tools() -> list[Tool]:
        return [
            Tool(
                name=t["name"],
                description=t["description"],
                inputSchema=t["input_schema"],
            )
            for t in _ALL_TOOL_DEFS
        ]

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
        text = _dispatch(name, arguments or {}, toolkit, store)
        return [TextContent(type="text", text=text)]

    @server.list_resources()
    async def handle_list_resources() -> list[Resource]:
        return [
            Resource(uri=AnyUrl("ibkr://accounts"),          name="IBKR Accounts",          mimeType="application/json"),
            Resource(uri=AnyUrl("ibkr://positions/current"), name="Current Positions",       mimeType="application/json"),
            Resource(uri=AnyUrl("ibkr://trades/recent"),     name="Recent Trades (SQLite)",  mimeType="application/json"),
        ]

    @server.read_resource()
    async def handle_read_resource(uri: AnyUrl) -> list[ReadResourceContents]:
        path = str(uri)
        text = "[]"
        try:
            if path == "ibkr://accounts":
                text = json.dumps(toolkit._client.get_accounts(), indent=2)
            elif path == "ibkr://positions/current":
                accounts = toolkit._client.get_accounts()
                account_id = accounts[0].get("accountId", "") if accounts else ""
                if account_id:
                    text = json.dumps(toolkit._client.get_positions(account_id), indent=2)
            elif path == "ibkr://trades/recent":
                text = json.dumps(store.get_trades()[:100], indent=2)
        except Exception as exc:
            logger.warning("read_resource %s failed: %s", path, type(exc).__name__)
        return [ReadResourceContents(content=text, mime_type="application/json")]

    return server


async def _run_stdio(server: Server) -> None:
    from mcp.server.stdio import stdio_server

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, write_stream,
            InitializationOptions(
                server_name="ibkr-core-mcp",
                server_version=__version__,
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


async def _run_sse(server: Server, port: int, streaming: bool, toolkit: ClaudeToolkit, store: SQLiteStore) -> None:
    import uvicorn
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.responses import Response
    from starlette.routing import Mount, Route

    init_opts = InitializationOptions(
        server_name="ibkr-core-mcp",
        server_version=__version__,
        capabilities=server.get_capabilities(
            notification_options=NotificationOptions(),
            experimental_capabilities={},
        ),
    )

    sse_transport = SseServerTransport("/messages/")

    async def handle_sse(request: Any) -> Response:
        async with sse_transport.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await server.run(streams[0], streams[1], init_opts)
        return Response()

    app = Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse_transport.handle_post_message),
        ]
    )

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    uv_server = uvicorn.Server(config)

    uv_task = asyncio.create_task(uv_server.serve())
    if streaming:
        # Run the stream loop as an independent background task so that a
        # WebSocket error does not propagate to gather() and cancel the HTTP
        # server.  The loop retries internally; we only cancel it on clean exit.
        stream_task = asyncio.create_task(_stream_loop_with_retry(toolkit, store))
        try:
            await uv_task
        finally:
            stream_task.cancel()
            try:
                await stream_task
            except asyncio.CancelledError:
                pass
    else:
        await uv_task


async def _stream_loop_with_retry(toolkit: ClaudeToolkit, store: SQLiteStore) -> None:
    """Background task wrapper: reconnect on transient errors with exponential backoff."""
    _RETRY_DELAYS = [5, 10, 30, 60]  # seconds between reconnect attempts
    attempt = 0
    while True:
        try:
            await _stream_loop(toolkit, store)
            # _stream_loop only returns without exception if the WebSocket closed
            # cleanly (e.g. gateway shutdown).  Retry after a short delay.
            logger.info("ibkr-core-mcp: WebSocket closed cleanly; reconnecting in 5s")
            await asyncio.sleep(5)
            attempt = 0
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            delay = _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]
            logger.error(
                "WebSocket stream error (attempt %d), retrying in %ds: %s",
                attempt + 1, delay, type(exc).__name__,
            )
            await asyncio.sleep(delay)
            attempt += 1


async def _stream_loop(toolkit: ClaudeToolkit, store: SQLiteStore) -> None:
    """Single-attempt WebSocket loop: connect, stream quotes, fire alerts."""
    import requests as _requests

    from ibkr_core_mcp.auth import BrowserCookieAuth
    from ibkr_core_mcp.streaming import AlertManager, IBKRWebSocket

    session = _requests.Session()
    BrowserCookieAuth().apply(session)
    cookie = session.headers.get("Cookie", "")

    ws = IBKRWebSocket(toolkit._config.gateway_url, cookie)
    manager = AlertManager(store)

    try:
        await ws.connect()
        logger.info("ibkr-core-mcp: WebSocket connected")
        subscribed: set[int] = set()
        async for quote in ws.listen():
            active_conids = {a["conid"] for a in store.get_alerts(active_only=True)}
            # Subscribe to newly-added alert conids.
            for cid in active_conids - subscribed:
                await ws.subscribe(cid)
                subscribed.add(cid)
            # Unsubscribe from conids that no longer have active alerts to avoid
            # accumulating stale subscriptions after alerts are triggered/removed.
            for cid in subscribed - active_conids:
                await ws.unsubscribe(cid)
                subscribed.discard(cid)
            triggered = manager.check_quote(quote)
            for alert in triggered:
                logger.warning(
                    "PRICE ALERT #%d: %s %s %.4f (last=%.4f)",
                    alert["id"], alert["symbol"], alert["direction"],
                    alert["threshold"], quote.last or 0,
                )
    finally:
        await ws.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(description="ibkr-core-mcp MCP server")
    parser.add_argument("--transport", choices=["stdio", "sse"], default="stdio")
    parser.add_argument("--port", type=int, default=5174, help="Port for SSE transport")
    parser.add_argument("--stream", action="store_true", help="Enable WebSocket live streaming")
    args = parser.parse_args()

    from ibkr_core_mcp import ClaudeToolkit, Config, GDriveCache, IBKRClient, SQLiteStore

    cfg = Config.from_env()
    store = SQLiteStore(cfg)
    toolkit = ClaudeToolkit(IBKRClient(cfg), GDriveCache(cfg), store, cfg)
    server = build_server(toolkit, store)

    if args.transport == "stdio":
        asyncio.run(_run_stdio(server))
    else:
        asyncio.run(_run_sse(server, args.port, args.stream, toolkit, store))


if __name__ == "__main__":
    main()
