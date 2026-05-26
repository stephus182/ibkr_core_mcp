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
from typing import TYPE_CHECKING

from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.types import TextContent, Tool, Resource
from pydantic import AnyUrl

from ibkr_core_mcp.claude_tools import TOOL_DEFINITIONS, ClaudeToolkit, _safe_error
from ibkr_core_mcp.exceptions import IBKRCoreError

if TYPE_CHECKING:
    from ibkr_core_mcp.store import SQLiteStore

logger = logging.getLogger(__name__)

_ADD_ALERT_DEF: dict = {
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

_GET_ALERTS_DEF: dict = {
    "name": "get_price_alerts",
    "description": "List price alerts. active_only=true returns only untriggered alerts.",
    "input_schema": {
        "type": "object",
        "properties": {
            "active_only": {"type": "boolean", "default": True},
        },
    },
}

_ALL_TOOL_DEFS: list[dict] = list(TOOL_DEFINITIONS) + [_ADD_ALERT_DEF, _GET_ALERTS_DEF]
_EXISTING_TOOL_NAMES: frozenset[str] = frozenset(t["name"] for t in TOOL_DEFINITIONS)


def _dispatch(name: str, args: dict, toolkit: ClaudeToolkit, store: "SQLiteStore") -> str:
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


def build_server(toolkit: ClaudeToolkit, store: "SQLiteStore") -> Server:
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
    async def handle_call_tool(name: str, arguments: dict | None) -> list[TextContent]:
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
    async def handle_read_resource(uri: AnyUrl) -> str:
        path = str(uri)
        try:
            if path == "ibkr://accounts":
                return json.dumps(toolkit._client.get_accounts(), indent=2)
            if path == "ibkr://positions/current":
                accounts = toolkit._client.get_accounts()
                account_id = accounts[0].get("accountId", "") if accounts else ""
                if not account_id:
                    return "[]"
                return json.dumps(toolkit._client.get_positions(account_id), indent=2)
            if path == "ibkr://trades/recent":
                return json.dumps(store.get_trades()[:100], indent=2)
        except IBKRCoreError:
            pass
        return "[]"

    return server


async def _run_stdio(server: Server) -> None:
    from mcp.server.stdio import stdio_server

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, write_stream,
            InitializationOptions(
                server_name="ibkr-core-mcp",
                server_version="0.4.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


async def _run_sse(server: Server, port: int, streaming: bool, toolkit: ClaudeToolkit, store: "SQLiteStore") -> None:
    import uvicorn
    from starlette.applications import Starlette
    from starlette.routing import Mount, Route
    from starlette.responses import Response
    from mcp.server.sse import SseServerTransport

    init_opts = InitializationOptions(
        server_name="ibkr-core-mcp",
        server_version="0.4.0",
        capabilities=server.get_capabilities(
            notification_options=NotificationOptions(),
            experimental_capabilities={},
        ),
    )

    sse_transport = SseServerTransport("/messages/")

    async def handle_sse(request):
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

    tasks: list[asyncio.Task] = [asyncio.create_task(uv_server.serve())]
    if streaming:
        tasks.append(asyncio.create_task(_stream_loop(toolkit, store)))
    await asyncio.gather(*tasks)


async def _stream_loop(toolkit: ClaudeToolkit, store: "SQLiteStore") -> None:
    """Background task: connect WebSocket, stream quotes, fire alerts."""
    import requests as _requests
    from ibkr_core_mcp.auth import BrowserCookieAuth
    from ibkr_core_mcp.streaming import IBKRWebSocket, AlertManager

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
            for cid in active_conids - subscribed:
                await ws.subscribe(cid)
                subscribed.add(cid)
            triggered = manager.check_quote(quote)
            for alert in triggered:
                logger.warning(
                    "PRICE ALERT #%d: %s %s %.4f (last=%.4f)",
                    alert["id"], alert["symbol"], alert["direction"],
                    alert["threshold"], quote.last or 0,
                )
    except Exception as exc:
        logger.error("WebSocket stream error: %s", exc)
    finally:
        await ws.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(description="ibkr-core-mcp MCP server")
    parser.add_argument("--transport", choices=["stdio", "sse"], default="stdio")
    parser.add_argument("--port", type=int, default=5174, help="Port for SSE transport")
    parser.add_argument("--stream", action="store_true", help="Enable WebSocket live streaming")
    args = parser.parse_args()

    from ibkr_core_mcp import Config, IBKRClient, GDriveCache, SQLiteStore, ClaudeToolkit

    cfg = Config.from_env()
    toolkit = ClaudeToolkit(IBKRClient(cfg), GDriveCache(cfg), SQLiteStore(cfg), cfg)
    store = SQLiteStore(cfg)
    server = build_server(toolkit, store)

    if args.transport == "stdio":
        asyncio.run(_run_stdio(server))
    else:
        asyncio.run(_run_sse(server, args.port, args.stream, toolkit, store))


if __name__ == "__main__":
    main()
