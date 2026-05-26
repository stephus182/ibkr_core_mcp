from __future__ import annotations
import json
import ssl
from dataclasses import dataclass
from typing import AsyncGenerator, TYPE_CHECKING
from urllib.parse import urlparse

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
    """Async WebSocket client for IBKR real-time market data.

    Usage::
        ws = IBKRWebSocket("https://localhost:5055", session_cookie)
        await ws.connect()
        await ws.subscribe(265598)
        async for quote in ws.listen():
            print(quote.last)
        await ws.disconnect()
    """

    def __init__(self, gateway_url: str, session_cookie: str) -> None:
        base = gateway_url.rstrip("/")
        self._ws_url = base.replace("https://", "wss://").replace("http://", "ws://") + "/v1/api/ws"
        self._cookie = session_cookie   # not logged anywhere
        self._ws = None

    async def connect(self) -> None:
        import websockets  # optional dep — only imported when streaming is used

        parsed = urlparse(self._ws_url)
        if parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
            from ibkr_core_mcp.exceptions import StreamingError
            raise StreamingError(
                f"IBKRWebSocket only connects to localhost; got {parsed.hostname!r}"
            )

        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_ctx.check_hostname = False      # self-signed cert on localhost
        ssl_ctx.verify_mode = ssl.CERT_NONE

        self._ws = await websockets.connect(
            self._ws_url,
            ssl=ssl_ctx,
            additional_headers={"Cookie": self._cookie},
            ping_interval=20,
            ping_timeout=10,
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
