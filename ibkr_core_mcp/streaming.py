from __future__ import annotations

import json
import ssl
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

if TYPE_CHECKING:
    from ibkr_core_mcp.store import SQLiteStore

_FIELD_MAP = {"31": "last", "84": "bid", "86": "ask", "87": "volume",
              "55": "symbol", "70": "high", "71": "low"}
_DEFAULT_FIELDS = ["31", "55", "84", "86", "87"]


@dataclass
class LiveQuote:
    """A single parsed IBKR WebSocket market data tick for one contract."""

    conid: int
    symbol: str = ""
    last: float | None = None
    bid: float | None = None
    ask: float | None = None
    volume: float | None = None
    high: float | None = None
    low: float | None = None


@dataclass
class TradeExecution:
    """A single parsed IBKR WebSocket trade execution (str topic).
    Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#ws-trades-sub
    """

    execution_id: str
    conid: int | None = None
    symbol: str = ""
    side: str = ""
    size: float | None = None
    price: float | None = None
    trade_time: str = ""                  # raw "YYYYMMDD-HH:mm:ss" UTC, as IBKR sends it
    trade_time_epoch: int | None = None   # IBKR's trade_time_r
    order_ref: str = ""
    exchange: str = ""
    net_amount: float | None = None
    account: str = ""
    account_code: str = ""                # IBKR's accountCode
    company_name: str = ""
    contract_description_1: str = ""
    contract_description_2: str = ""
    sec_type: str = ""
    conid_ex: str = ""                    # IBKR's conidEx
    open_close: str = ""                  # "???" if opening trade
    liquidation_trade: str = ""
    is_event_trading: str = ""
    supports_tax_opt: str = ""
    order_description: str = ""


@dataclass
class PnLUpdate:
    """A single parsed IBKR WebSocket account P&L tick (spl topic).
    Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#ws-pnl-sub
    NOTE: IBKR's docs page mislabels this response section "Order Updates Response"
    (duplicate of the real order-updates heading earlier on the page) — the field
    content here is unambiguously P&L. Confirmed via a fresh targeted re-scrape, 2026-07-06.
    Only the first account key in a message is parsed (confirmed doc example shows
    exactly one); extend to list[PnLUpdate] if multi-account traffic is ever observed.
    """

    account: str                          # raw key as sent, e.g. "DU1234567.Core"
    row_type: int | None = None
    dpl: float | None = None
    nl: float | None = None
    upl: float | None = None
    uel: float | None = None
    mv: float | None = None


_SIDE_MAP = {"B": "BUY", "S": "SELL", "BUY": "BUY", "SELL": "SELL"}


def _parse_stream_execution(execution: TradeExecution) -> dict[str, Any]:
    """Normalise a WS str-topic TradeExecution into the SQLiteStore.trades schema."""
    raw_side = (execution.side or "").upper()
    return {
        "execution_id": execution.execution_id,
        "symbol": execution.symbol,
        "side": _SIDE_MAP.get(raw_side, raw_side),
        "size": execution.size or 0.0,
        "price": execution.price or 0.0,
        "time": execution.trade_time,
        "commission": 0.0,       # str payload has no commission field
        "account": execution.account,
        "asset_class": (execution.sec_type or "").upper(),
        "realized_pnl": None,    # str payload has no realized P&L field (same gap
                                 # claude_tools._parse_live_trades already documents
                                 # for the REST trades endpoint)
    }


class IBKRWebSocket:
    """Async WebSocket client for IBKR real-time market data.

    Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#websockets
    Endpoint: wss://localhost:{port}/v1/api/ws

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
        if base.endswith("/v1/api"):
            # Callers commonly pass config.gateway_url, which already carries
            # the /v1/api REST prefix — strip it so it isn't doubled below.
            base = base[: -len("/v1/api")]
        self._ws_url = base.replace("https://", "wss://").replace("http://", "ws://") + "/v1/api/ws"
        self._cookie = session_cookie   # not logged anywhere
        self._ws: Any = None

    async def connect(self) -> None:
        try:
            import websockets  # optional dep — only imported when streaming is used
        except ModuleNotFoundError as exc:
            raise ModuleNotFoundError(
                "websockets is required for IBKRWebSocket. "
                "Install it with: pip install 'ibkr_core_mcp[server]'"
            ) from exc

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
        """Subscribe to real-time market data for a contract.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#websockets
        Message format: smd+{conid}+{"fields": [...]}
        """
        if self._ws is None:
            raise RuntimeError("Call connect() first")
        await self._ws.send(f'smd+{conid}+{json.dumps({"fields": fields or _DEFAULT_FIELDS})}')

    async def unsubscribe(self, conid: int) -> None:
        """Unsubscribe from real-time market data for a contract.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#websockets
        Message format: umd+{conid}+{}
        """
        if self._ws is not None:
            await self._ws.send(f"umd+{conid}+{{}}")

    async def subscribe_executions(self, realtime_updates_only: bool = False, days: int = 1) -> None:
        """Subscribe to live trade executions.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#ws-trades-sub
        Message format: str+{"realtimeUpdatesOnly": bool, "days": int}
        """
        if self._ws is None:
            raise RuntimeError("Call connect() first")
        await self._ws.send(f"str+{json.dumps({'realtimeUpdatesOnly': realtime_updates_only, 'days': days})}")

    async def unsubscribe_executions(self) -> None:
        """Unsubscribe from live trade executions. Message format: utr"""
        if self._ws is not None:
            await self._ws.send("utr")

    async def subscribe_pnl(self) -> None:
        """Subscribe to live account P&L ticks.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#ws-pnl-sub
        Message format: spl+{}
        """
        if self._ws is None:
            raise RuntimeError("Call connect() first")
        await self._ws.send("spl+{}")

    async def unsubscribe_pnl(self) -> None:
        """Unsubscribe from live account P&L ticks. Message format: upl"""
        if self._ws is not None:
            await self._ws.send("upl")

    async def listen(self) -> AsyncGenerator[LiveQuote | TradeExecution | PnLUpdate, None]:
        if self._ws is None:
            raise RuntimeError("Call connect() first")
        async for raw in self._ws:
            parsed = self._parse_message(raw)
            if parsed is None:
                continue
            if isinstance(parsed, list):
                for item in parsed:
                    yield item
            else:
                yield parsed

    async def disconnect(self) -> None:
        if self._ws is not None:
            await self._ws.close()
            self._ws = None

    def _parse_message(
        self, raw: str
    ) -> LiveQuote | list[TradeExecution] | PnLUpdate | None:
        try:
            msg = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(msg, dict):
            return None
        topic = msg.get("topic", "")
        if topic.startswith("smd+"):
            return self._parse_market_data(topic, msg)
        if topic == "str":
            return self._parse_trade_executions(msg)
        if topic == "spl":
            return self._parse_pnl(msg)
        return None

    def _parse_market_data(self, topic: str, msg: dict[str, Any]) -> LiveQuote | None:
        data_list = msg.get("data", [])
        # IBKR may send data as a list or as a bare dict; normalise to a dict.
        if isinstance(data_list, list):
            if not data_list:
                return None
            data = data_list[0]
        elif isinstance(data_list, dict):
            data = data_list
        else:
            return None
        if not isinstance(data, dict):
            return None
        try:
            conid = int(data.get("conid", topic.split("+")[1]))
        except (ValueError, IndexError):
            return None
        kwargs: dict[str, Any] = {"conid": conid}
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

    def _parse_trade_executions(self, msg: dict[str, Any]) -> list[TradeExecution] | None:
        args = msg.get("args", [])
        if isinstance(args, dict):
            args = [args]
        if not isinstance(args, list) or not args:
            return None
        executions = []
        for record in args:
            if not isinstance(record, dict):
                continue
            execution_id = record.get("execution_id")
            if not execution_id:
                continue
            kwargs: dict[str, Any] = {
                "execution_id": str(execution_id),
                "symbol": str(record.get("symbol", "")),
                "side": str(record.get("side", "")),
                "trade_time": str(record.get("trade_time", "")),
                "order_ref": str(record.get("order_ref", "")),
                "exchange": str(record.get("exchange", "")),
                "account": str(record.get("account", "")),
                "account_code": str(record.get("accountCode", "")),
                "company_name": str(record.get("company_name", "")),
                "contract_description_1": str(record.get("contract_description_1", "")),
                "contract_description_2": str(record.get("contract_description_2", "")),
                "sec_type": str(record.get("sec_type", "")),
                "conid_ex": str(record.get("conidEx", "")),
                "open_close": str(record.get("open_close", "")),
                "liquidation_trade": str(record.get("liquidation_trade", "")),
                "is_event_trading": str(record.get("is_event_trading", "")),
                "supports_tax_opt": str(record.get("supports_tax_opt", "")),
                "order_description": str(record.get("order_description", "")),
            }
            for field, attr in (
                ("size", "size"), ("price", "price"), ("net_amount", "net_amount"),
                ("conid", "conid"),
            ):
                if field not in record:
                    continue
                try:
                    kwargs[attr] = float(record[field]) if field != "conid" else int(record[field])
                except (TypeError, ValueError):
                    pass
            if "trade_time_r" in record:
                try:
                    kwargs["trade_time_epoch"] = int(record["trade_time_r"])
                except (TypeError, ValueError):
                    pass
            executions.append(TradeExecution(**kwargs))
        return executions or None

    def _parse_pnl(self, msg: dict[str, Any]) -> PnLUpdate | None:
        args = msg.get("args", {})
        if not isinstance(args, dict) or not args:
            return None
        account, data = next(iter(args.items()))
        if not isinstance(data, dict):
            return None
        kwargs: dict[str, Any] = {"account": str(account)}
        if "rowType" in data:
            try:
                kwargs["row_type"] = int(data["rowType"])
            except (TypeError, ValueError):
                pass
        for field in ("dpl", "nl", "upl", "uel", "mv"):
            if field not in data:
                continue
            try:
                kwargs[field] = float(data[field])
            except (TypeError, ValueError):
                pass
        return PnLUpdate(**kwargs)


class AlertManager:
    """Check live quotes against active price alerts; mark triggered ones in SQLite."""

    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    def check_quote(self, quote: LiveQuote) -> list[dict[str, Any]]:
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
