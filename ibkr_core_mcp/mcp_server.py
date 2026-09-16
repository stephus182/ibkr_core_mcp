"""ibkr_core_mcp MCP server.

Run:
    python -m ibkr_core_mcp.mcp_server                   # stdio (Claude Desktop)
    python -m ibkr_core_mcp.mcp_server --transport sse   # HTTP/SSE on localhost:5174
    python -m ibkr_core_mcp.mcp_server --transport sse --stream  # + WebSocket streaming
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hmac
import json
import logging
import os
import secrets
from typing import TYPE_CHECKING, Any

from mcp.server import NotificationOptions, Server
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.models import InitializationOptions
from mcp.types import Resource, TextContent, Tool, ToolAnnotations
from pydantic import AnyUrl

from ibkr_core_mcp import __version__
from ibkr_core_mcp.claude_tools import READ_LIKE_CAPABILITIES, TOOL_DEFINITIONS, ClaudeToolkit, _safe_error
from ibkr_core_mcp.models import json_default
from ibkr_core_mcp.redaction import redact_error

if TYPE_CHECKING:
    from ibkr_core_mcp.config import Config
    from ibkr_core_mcp.store import SQLiteStore

logger = logging.getLogger(__name__)

_ADD_ALERT_DEF: dict[str, Any] = {
    "name": "add_price_alert",
    "capabilities": frozenset({"DATABASE"}),
    "description": (
        "Create a price alert that fires when a symbol crosses a threshold. direction must be 'above' or 'below'."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "conid": {"type": "integer", "description": "IBKR contract ID"},
            "symbol": {"type": "string", "description": "Ticker symbol, e.g. 'AAPL'"},
            "threshold": {"type": "number", "description": "Price threshold"},
            "direction": {"type": "string", "enum": ["above", "below"]},
        },
        "required": ["conid", "symbol", "threshold", "direction"],
    },
}

_GET_ALERTS_DEF: dict[str, Any] = {
    "name": "get_price_alerts",
    "capabilities": frozenset({"READ_ONLY"}),
    "description": "List price alerts. active_only=true returns only untriggered alerts.",
    "input_schema": {
        "type": "object",
        "properties": {
            "active_only": {"type": "boolean", "default": True},
        },
    },
}

_ALL_TOOL_DEFS: list[dict[str, Any]] = [*TOOL_DEFINITIONS, _ADD_ALERT_DEF, _GET_ALERTS_DEF]
_EXISTING_TOOL_NAMES: frozenset[str] = frozenset(str(t["name"]) for t in TOOL_DEFINITIONS)

_DESTRUCTIVE_CAPABILITIES = frozenset({"GOOGLE_DRIVE", "ACCOUNT_STATE"})
_OPEN_WORLD_CAPABILITIES = frozenset({"NETWORK", "WEB_FETCH"})


def tool_annotations(capabilities: frozenset[str]) -> ToolAnnotations:
    """The MCP-native hints derived from a tool's declared capabilities.

    MCP clients gate their own confirmation prompts on `readOnlyHint` / `destructiveHint`;
    until 2026-09-13 the declaration existed only for this package's test suite and the
    protocol field stayed empty (review). Deriving both from one set keeps the internal
    vocabulary and the protocol-native one from drifting.
    """
    return ToolAnnotations(
        readOnlyHint=capabilities <= READ_LIKE_CAPABILITIES,
        destructiveHint=bool(capabilities & _DESTRUCTIVE_CAPABILITIES),
        openWorldHint=bool(capabilities & _OPEN_WORLD_CAPABILITIES),
    )


def _dispatch(name: str, args: dict[str, Any], toolkit: ClaudeToolkit, store: SQLiteStore) -> str:
    """Route a tool call to the right handler. Never raises — always returns str."""
    try:
        if name in _EXISTING_TOOL_NAMES:
            text, _ = toolkit.execute(name, args)
            return text
        if name == "add_price_alert":
            aid = store.add_alert(
                int(args["conid"]),
                str(args["symbol"]),
                float(args["threshold"]),
                str(args["direction"]),
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
                annotations=tool_annotations(frozenset(t["capabilities"])),
            )
            for t in _ALL_TOOL_DEFS
        ]

    # `validate_input=True` is the SDK's default; it is written out so the property is this
    # package's own statement rather than an inherited one, and so a reader of `build_server`
    # sees that arguments are schema-checked before `_dispatch` runs (invariant 11,
    # tests/security/test_tool_input_validation.py).
    @server.call_tool(validate_input=True)
    async def handle_call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
        text = _dispatch(name, arguments or {}, toolkit, store)
        return [TextContent(type="text", text=text)]

    @server.list_resources()
    async def handle_list_resources() -> list[Resource]:
        return [
            Resource(uri=AnyUrl("ibkr://accounts"), name="IBKR Accounts", mimeType="application/json"),
            Resource(uri=AnyUrl("ibkr://positions/current"), name="Current Positions", mimeType="application/json"),
            Resource(uri=AnyUrl("ibkr://trades/recent"), name="Recent Trades (SQLite)", mimeType="application/json"),
            Resource(
                uri=AnyUrl("ibkr://pnl/live"), name="Live P&L (WebSocket, --stream only)", mimeType="application/json"
            ),
        ]

    @server.read_resource()
    async def handle_read_resource(uri: AnyUrl) -> list[ReadResourceContents]:
        path = str(uri)
        # An error OBJECT, not "[]". `text` used to be initialised to an empty array
        # before the try, so a down gateway or an expired session produced a perfectly
        # successful resource response whose body said "you have no positions" — and
        # only type(exc).__name__ was logged, so even the reason was thrown away. The
        # mimeType contract is preserved; the model can read this and say what broke.
        text = json.dumps({"error": "resource handler did not run", "resource": path})
        try:
            if path == "ibkr://accounts":
                text = json.dumps(toolkit._client.get_accounts(), indent=2)
            elif path == "ibkr://positions/current":
                # `_first_account_id`, not an inlined `get_accounts()[0]["accountId"]`.
                # IBKR varies that key by endpoint — the helper applies the documented
                # "accountId" -> "id" fallback, and CLAUDE.md requires using it for exactly
                # this reason. Reading only "accountId" was the package's single violation
                # of that rule: a row carrying just "id" fell into the branch below and
                # reported a resolution failure for an account that resolved fine
                # everywhere else (audit finding TOOL-06, 2026-09-16).
                account_id, account_err = toolkit._first_account_id()
                if account_id:
                    # default=json_default: get_positions returns Position models, and this
                    # handler catches every exception — a serialisation failure would answer
                    # with an error object rather than crash, so the resource would look
                    # healthy while carrying nothing.
                    text = json.dumps(toolkit._client.get_positions(account_id), indent=2, default=json_default)
                else:
                    # Not silent: no exception, but nothing was read either, and the
                    # reason the helper gave is carried out rather than discarded.
                    text = json.dumps(
                        {
                            "error": account_err or "no account could be resolved, so positions were never read",
                            "resource": path,
                        }
                    )
            elif path == "ibkr://trades/recent":
                text = json.dumps(store.get_trades()[:100], indent=2)
            elif path == "ibkr://pnl/live":
                # Only populated if the server was started with --stream; otherwise
                # pnl_snapshots stays empty and this always returns {}.
                latest = store.get_latest_pnl()
                text = json.dumps(latest if latest is not None else {}, indent=2)
            else:
                text = json.dumps({"error": f"unknown resource: {path}", "resource": path})
        except Exception as exc:
            logger.warning("read_resource %s failed: %s", path, redact_error(exc))
            text = json.dumps({"error": redact_error(exc), "resource": path}, indent=2)
        return [ReadResourceContents(content=text, mime_type="application/json")]

    return server


async def _run_stdio(server: Server) -> None:
    from mcp.server.stdio import stdio_server

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="ibkr-core-mcp",
                server_version=__version__,
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


class _BearerTokenGate:
    """ASGI middleware requiring `Authorization: Bearer <token>` on every HTTP request.

    Wraps the whole SSE app — `/sse`, where a client reads its session id, and `/messages/`,
    where it posts JSON-RPC — so an unauthenticated caller is refused before any MCP
    machinery runs, the SDK's own Host/Origin check included. Gating only `/messages/` would
    leave the more interesting half open.

    Pure ASGI on purpose: a Starlette `BaseHTTPMiddleware` buffers the response, which breaks
    the `/sse` event stream. This reads `scope["headers"]` directly (ASGI guarantees
    lowercased byte names) and either passes the call through untouched or writes the 401
    itself. Non-HTTP scopes — lifespan — pass through.

    The comparison is `hmac.compare_digest` over the entire header value, scheme included, so
    a prefix of the token is not distinguishable from a wrong one by response timing.
    """

    def __init__(self, app: Any, token: str) -> None:
        """Wrap `app`, admitting only requests that present `token` as a bearer credential."""
        self._app = app
        self._expected = f"Bearer {token}".encode()

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        """Answer 401, or hand the call to the wrapped app unchanged."""
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return
        presented = b""
        for name, value in scope.get("headers", ()):
            if name == b"authorization":
                presented = bytes(value)
                break
        if not hmac.compare_digest(presented, self._expected):
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [(b"content-type", b"text/plain; charset=utf-8"), (b"www-authenticate", b"Bearer")],
                }
            )
            await send({"type": "http.response.body", "body": b"Unauthorized"})
            return
        await self._app(scope, receive, send)


def _issue_sse_token(config: Config) -> str:
    """Mint this launch's SSE bearer token and write it to a 0600 file for local clients.

    A fresh `secrets.token_urlsafe(32)` every launch: nothing to configure, nothing to
    rotate, and a credential that stops working when the server does. It is written under
    `~/.ibkr_core/` — the directory `SQLiteStore` already holds at 0700 — rather than printed,
    because a terminal is scrolled, screen-shared and often captured; only the path is logged,
    never the value.

    Why it exists: the loopback bind and the Host/Origin check stop the LAN and the browser,
    not another process on this machine, which needs no DNS trick — it can simply open the
    port. OWASP §1 ("if you must use local HTTP … still utilize explicit
    authorization/authentication"), the MCP best-practices page ("require an authorization
    token") and the transports specification ("SHOULD implement proper authentication") all
    name the step. See SECURITY.md § MCP Transports.

    Args:
        config: Supplies `sqlite_path`, whose parent is the `~/.ibkr_core/` directory.

    Returns:
        The token to hand to `build_sse_app`.
    """
    token = secrets.token_urlsafe(32)
    path = config.sqlite_path.parent / "mcp_sse_token"
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # O_CREAT's mode applies only when the file is created, so a token file left by an
    # earlier launch would keep its old mode — hence the explicit chmod, as in gdrive_auth.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(token + "\n")
    os.chmod(path, 0o600)
    logger.warning(
        "ibkr-core-mcp: SSE bearer token for this launch written to %s — clients must send "
        "'Authorization: Bearer <token>'. It is replaced on every launch.",
        path,
    )
    return token


def build_sse_app(server: Server, token: str) -> Any:
    """The Starlette app behind `--transport sse`: `/sse` for the stream, `/messages/` for posts.

    `token` is this launch's bearer credential (`_issue_sse_token`). It is a required
    argument rather than an optional one so that an unauthenticated server cannot be built by
    forgetting to pass it — the same reasoning that removed `ORDER_EXECUTION` from the
    capability vocabulary instead of asserting that nobody declares it.

    Factored out of `_run_sse` so the transport's construction is a testable value
    (tests/security/test_transport_security.py) rather than a line inside a coroutine that
    only runs under uvicorn.

    Args:
        server: The configured MCP server to serve.
        token: The bearer token every request must present.

    Returns:
        An ASGI application: the bearer gate wrapping the Starlette routes.
    """
    from mcp.server.sse import SseServerTransport
    from mcp.server.transport_security import TransportSecuritySettings
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

    # DNS-rebinding protection (2026-09-13, audit A3) — the browser half of the transport's
    # defence; `_BearerTokenGate` above is the local-process half (2026-09-14). Without
    # `security_settings` the SDK
    # substitutes `enable_dns_rebinding_protection=False` "for backwards compatibility",
    # so Host and Origin were never checked. uvicorn's 127.0.0.1 bind stops the LAN, not
    # the operator's own browser: a page whose DNS answer flips to 127.0.0.1 becomes
    # same-origin with this server and can drive every tool from an unattended tab. The
    # allowed values are the only ones a real local client ever sends; any port, because
    # `--port` is a flag.
    sse_transport = SseServerTransport(
        "/messages/",
        security_settings=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            # Bare entries as well as `:*` wildcards: the SDK matches a wildcard with
            # `startswith(base + ":")`, so a port-less Host or Origin (`--port 80`) needs
            # its own entry (review 2026-09-13).
            allowed_hosts=["127.0.0.1", "127.0.0.1:*", "localhost", "localhost:*", "[::1]", "[::1]:*"],
            allowed_origins=[
                "http://127.0.0.1",
                "http://127.0.0.1:*",
                "http://localhost",
                "http://localhost:*",
                "http://[::1]",
                "http://[::1]:*",
            ],
        ),
    )

    async def handle_sse(request: Any) -> Response:
        async with sse_transport.connect_sse(request.scope, request.receive, request._send) as streams:
            await server.run(streams[0], streams[1], init_opts)
        return Response()

    return _BearerTokenGate(
        Starlette(
            routes=[
                Route("/sse", endpoint=handle_sse),
                Mount("/messages/", app=sse_transport.handle_post_message),
            ]
        ),
        token,
    )


async def _run_sse(server: Server, port: int, streaming: bool, toolkit: ClaudeToolkit, store: SQLiteStore) -> None:
    import uvicorn

    app = build_sse_app(server, _issue_sse_token(toolkit._config))
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
            with contextlib.suppress(asyncio.CancelledError):
                await stream_task
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
                attempt + 1,
                delay,
                type(exc).__name__,
            )
            await asyncio.sleep(delay)
            attempt += 1


async def _reconcile_alert_subscriptions(ws: Any, store: SQLiteStore, subscribed: set[int]) -> None:
    """Make the live market-data subscriptions match the active price alerts.

    Subscribes to conids that gained an alert and unsubscribes from those that lost one,
    mutating `subscribed` in place. Unsubscribing matters on a long-lived server: a
    triggered or deleted alert would otherwise leave its subscription behind for the life
    of the process.

    Args:
        ws: Connected `IBKRWebSocket`.
        store: SQLite store holding the alert rows written by `add_price_alert`.
        subscribed: Conids currently subscribed; updated in place.
    """
    active = {int(a["conid"]) for a in store.get_alerts(active_only=True)}
    for conid in active - subscribed:
        await ws.subscribe(conid)
        subscribed.add(conid)
    for conid in subscribed - active:
        await ws.unsubscribe(conid)
        subscribed.discard(conid)


async def _stream_loop(toolkit: ClaudeToolkit, store: SQLiteStore) -> None:
    """Single-attempt WebSocket loop: connect, stream quotes/executions/P&L, fire alerts."""
    import requests as _requests

    from ibkr_core_mcp.auth import BrowserCookieAuth
    from ibkr_core_mcp.streaming import (
        AlertManager,
        IBKRWebSocket,
        LiveQuote,
        PnLUpdate,
        TradeExecution,
        _parse_stream_execution,
    )

    session = _requests.Session()
    BrowserCookieAuth().apply(session)
    cookie = session.headers.get("Cookie", "")

    ws = IBKRWebSocket(toolkit._config.gateway_url, cookie)
    manager = AlertManager(store)

    try:
        await ws.connect()
        logger.info("ibkr-core-mcp: WebSocket connected")
        await ws.subscribe_executions()
        await ws.subscribe_pnl()
        subscribed: set[int] = set()
        # Before the loop, not inside it. Reconciling only on a LiveQuote was a deadlock:
        # a LiveQuote is parsed only from an `smd+` frame, and the gateway sends `smd+`
        # only after an `smd+{conid}` subscription — so no subscription meant no quote,
        # and no quote meant no subscription. The two subscriptions made above are
        # executions and P&L, neither of which is a LiveQuote. Every price alert was
        # therefore silently dead under `--stream` (audit finding API-09, 2026-09-16).
        await _reconcile_alert_subscriptions(ws, store, subscribed)
        async for item in ws.listen():
            # On every message, whatever its type, so an alert added while the server is
            # running is picked up by the next tick rather than only by a quote for a
            # contract we are not yet watching. P&L ticks alone are enough to drive this.
            await _reconcile_alert_subscriptions(ws, store, subscribed)
            if isinstance(item, LiveQuote):
                triggered = manager.check_quote(item)
                for alert in triggered:
                    logger.warning(
                        "PRICE ALERT #%d: %s %s %.4f (last=%.4f)",
                        alert["id"],
                        alert["symbol"],
                        alert["direction"],
                        alert["threshold"],
                        item.last or 0,
                    )
            elif isinstance(item, TradeExecution):
                store.upsert_trades([_parse_stream_execution(item)])
            elif isinstance(item, PnLUpdate):
                store.record_pnl_snapshot(
                    account=item.account,
                    row_type=item.row_type,
                    dpl=item.dpl,
                    nl=item.nl,
                    upl=item.upl,
                    uel=item.uel,
                    mv=item.mv,
                )
    finally:
        await ws.disconnect()


def main() -> None:
    """Console-script entry point for the MCP server.

    Parses `--transport` (stdio or sse), `--port`, and `--stream`, builds the
    toolkit from environment configuration, and serves until interrupted.
    """
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
