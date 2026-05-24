from __future__ import annotations
import json
from datetime import date
from typing import Any

import pandas as pd

from ibkr_core_mcp.cache import GDriveCache
from ibkr_core_mcp.client import IBKRClient
from ibkr_core_mcp.config import Config
from ibkr_core_mcp.exceptions import CacheMissError
from ibkr_core_mcp.store import SQLiteStore

_TODAY = lambda: str(date.today())

TOOL_DEFINITIONS = [
    {
        "name": "fetch_market_data",
        "description": (
            "Fetch OHLCV historical data for a symbol from IBKR. "
            "Checks Google Drive cache first; only calls IBKR on a cache miss. "
            "Returns a summary of the data retrieved."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Ticker, e.g. AAPL"},
                "period": {"type": "string", "description": "History period, e.g. '1Y', '6M'"},
                "bar": {"type": "string", "description": "Bar size, e.g. '1d', '1h'", "default": "1d"},
                "end": {"type": "string", "description": "End date YYYY-MM-DD, defaults to today"},
            },
            "required": ["symbol", "period"],
        },
    },
    {
        "name": "check_cache",
        "description": "Check whether data for a symbol/timeframe is cached in Google Drive.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "timeframe": {"type": "string", "description": "e.g. '1D'"},
                "period": {"type": "string", "description": "e.g. '1Y'"},
                "end": {"type": "string", "description": "End date YYYY-MM-DD"},
            },
            "required": ["symbol", "timeframe", "period", "end"],
        },
    },
    {
        "name": "list_cache",
        "description": "List all datasets currently cached in Google Drive.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_account_summary",
        "description": "Retrieve account net liquidation value, cash balance, and P&L from IBKR.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_positions",
        "description": "Get all open positions for the IBKR account.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_trades",
        "description": "Get recent trade history (last 6 days from IBKR, all-time from SQLite store).",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Filter by symbol (optional)"},
                "source": {"type": "string", "description": "'live' (IBKR, last 6 days) or 'store' (SQLite, all-time)", "default": "live"},
            },
            "required": [],
        },
    },
    {
        "name": "get_live_orders",
        "description": "Get currently open/pending orders from IBKR.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_ledger",
        "description": "Get cash balance and ledger information by currency for the IBKR account.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_allocation",
        "description": "Get portfolio allocation breakdown by asset class, industry, and category.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_pa_performance",
        "description": "Get portfolio NAV performance from IBKR Portfolio Analyst.",
        "input_schema": {
            "type": "object",
            "properties": {
                "period": {"type": "string", "description": "e.g. 'last7days', 'last30days', 'ytd', 'last365days'"},
            },
            "required": ["period"],
        },
    },
    {
        "name": "get_pa_transactions",
        "description": "Get transaction history from IBKR Portfolio Analyst.",
        "input_schema": {
            "type": "object",
            "properties": {
                "period": {"type": "string", "description": "e.g. 'last7days', 'ytd'"},
            },
            "required": ["period"],
        },
    },
    {
        "name": "get_contract_info",
        "description": "Get full contract details for a symbol (conid, exchange, currency, trading hours, etc.).",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Ticker symbol"},
                "sec_type": {"type": "string", "description": "Security type, default STK", "default": "STK"},
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "get_option_chain",
        "description": "Get the options chain for a symbol — expirations, strikes, and contract IDs.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "exchange": {"type": "string", "default": "SMART"},
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "run_scanner",
        "description": (
            "Run an IBKR market scanner to find stocks matching criteria. "
            "Common scan_code values: 'TOP_PERC_GAIN', 'TOP_PERC_LOSE', 'MOST_ACTIVE', "
            "'HIGH_VS_13W_HL', 'LOW_VS_13W_HL', 'NEAR_52W_HL'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "scan_code": {"type": "string", "description": "Scanner type, e.g. 'TOP_PERC_GAIN'"},
                "instrument": {"type": "string", "description": "e.g. 'STK'", "default": "STK"},
                "location_code": {"type": "string", "description": "e.g. 'STK.US.MAJOR'", "default": "STK.US.MAJOR"},
                "max_results": {"type": "integer", "default": 25},
            },
            "required": ["scan_code"],
        },
    },
    {
        "name": "get_notifications",
        "description": "Retrieve IBKR FYI notifications and unread alerts.",
        "input_schema": {
            "type": "object",
            "properties": {
                "max_results": {"type": "integer", "default": 10},
            },
            "required": [],
        },
    },
]


class ClaudeToolkit:
    """Ready-made Claude tool layer for IBKR research. Portable across any Claude-powered app."""

    def __init__(
        self,
        client: IBKRClient,
        cache: GDriveCache,
        store: SQLiteStore,
        config: Config,
    ) -> None:
        self._client = client
        self._cache = cache
        self._store = store
        self._config = config

    @property
    def tools(self) -> list[dict]:
        return TOOL_DEFINITIONS

    def execute(self, name: str, inputs: dict) -> tuple[str, Any]:
        """Execute a tool call. Returns (text_result, optional_plotly_fig)."""
        handlers = {
            "fetch_market_data": self._fetch_market_data,
            "check_cache": self._check_cache,
            "list_cache": self._list_cache,
            "get_account_summary": self._get_account_summary,
            "get_positions": self._get_positions,
            "get_trades": self._get_trades,
            "get_live_orders": self._get_live_orders,
            "get_ledger": self._get_ledger,
            "get_allocation": self._get_allocation,
            "get_pa_performance": self._get_pa_performance,
            "get_pa_transactions": self._get_pa_transactions,
            "get_contract_info": self._get_contract_info,
            "get_option_chain": self._get_option_chain,
            "run_scanner": self._run_scanner,
            "get_notifications": self._get_notifications,
        }
        handler = handlers.get(name)
        if not handler:
            return f"Unknown tool: {name}", None
        try:
            return handler(inputs)
        except Exception as e:
            return f"Tool '{name}' error: {e}", None

    def _fetch_market_data(self, inputs: dict) -> tuple[str, Any]:
        symbol = inputs["symbol"].upper()
        period = inputs["period"]
        bar = inputs.get("bar", "1d")
        end = inputs.get("end", _TODAY())
        timeframe = bar.upper()

        if self._cache.check(symbol, timeframe, period, end):
            df = self._cache.load(symbol, timeframe, period, end)
            return (
                f"Cache HIT — loaded {symbol} {timeframe} ({period}) from Drive. "
                f"{len(df)} bars from {df.index[0].date()} to {df.index[-1].date()}.",
                None,
            )

        contracts = self._client.search_contract(symbol)
        if not contracts:
            return f"No contract found for {symbol}. Is IBKR connected?", None
        conid = contracts[0].get("conid") or contracts[0].get("con_id")
        if not conid:
            return f"Contract found for {symbol} but conid missing: {contracts[0]}", None

        raw = self._client.get_market_history(conid, period=period, bar=bar)
        data = raw.get("data", [])
        if not data:
            return f"IBKR returned no data for {symbol} (period={period}, bar={bar})", None

        df = pd.DataFrame(data)
        df["t"] = pd.to_datetime(df["t"], unit="ms")
        df = df.rename(columns={"t": "date", "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
        df = df.set_index("date").sort_index()

        self._cache.save(df, symbol, timeframe, period, end)
        return (
            f"Fetched {symbol} {timeframe} ({period}) from IBKR: "
            f"{len(df)} bars from {df.index[0].date()} to {df.index[-1].date()}. "
            f"Saved to Drive cache.",
            None,
        )

    def _check_cache(self, inputs: dict) -> tuple[str, Any]:
        hit = self._cache.check(
            inputs["symbol"], inputs["timeframe"], inputs["period"], inputs["end"]
        )
        label = "HIT" if hit else "MISS"
        return f"Cache {label} for {inputs['symbol']} {inputs['timeframe']} {inputs['period']}–{inputs['end']}", None

    def _list_cache(self, inputs: dict) -> tuple[str, Any]:
        entries = self._cache.list_cached()
        if not entries:
            return "Drive cache is empty.", None
        lines = [f"- {e['key']}: {e.get('rows', '?')} bars, cached {e.get('cached_at', '?')[:10]}" for e in entries]
        return f"Cached datasets ({len(entries)}):\n" + "\n".join(lines), None

    def _get_account_summary(self, inputs: dict) -> tuple[str, Any]:
        accounts = self._client.get_accounts()
        if not accounts:
            return "No accounts found.", None
        account_id = accounts[0].get("accountId", accounts[0].get("id", ""))
        summary = self._client.get_account_summary(account_id)
        return json.dumps(summary, indent=2), None

    def _get_positions(self, inputs: dict) -> tuple[str, Any]:
        accounts = self._client.get_accounts()
        if not accounts:
            return "No accounts found.", None
        account_id = accounts[0].get("accountId", accounts[0].get("id", ""))
        positions = self._client.get_positions(account_id)
        if not positions:
            return "No open positions.", None
        lines = []
        for p in positions:
            symbol = p.get("contractDesc", p.get("ticker", p.get("symbol", "?")))
            pos = p.get("position", 0)
            mkt_val = p.get("mktValue", 0)
            pnl = p.get("unrealizedPnl", 0)
            lines.append(f"- {symbol}: {pos} shares, mktVal={mkt_val:.2f}, unrealPnL={pnl:.2f}")
        return f"Open positions ({len(positions)}):\n" + "\n".join(lines), None

    def _get_trades(self, inputs: dict) -> tuple[str, Any]:
        source = inputs.get("source", "live")
        symbol = inputs.get("symbol")
        if source == "store":
            trades = self._store.get_trades(symbol=symbol)
            if not trades:
                return "No trades found in local store.", None
            lines = [f"- {t['time'][:10]} {t['symbol']} {t['side']} {t['size']} @ {t['price']}" for t in trades[:20]]
            return f"Trade history (SQLite, {len(trades)} total):\n" + "\n".join(lines), None
        trades = self._client.get_trades()
        if symbol:
            trades = [t for t in trades if t.get("symbol", "").upper() == symbol.upper()]
        try:
            self._store.upsert_trades([
                {
                    "execution_id": t.get("execution_id", t.get("orderId", str(i))),
                    "symbol": t.get("symbol", ""),
                    "side": t.get("side", ""),
                    "size": float(t.get("size", t.get("filledQuantity", 0))),
                    "price": float(t.get("price", t.get("avgPrice", 0))),
                    "time": str(t.get("trade_time", t.get("time", ""))),
                    "commission": float(t.get("commission", 0)),
                    "account": str(t.get("account", "")),
                }
                for i, t in enumerate(trades)
                if t.get("symbol")
            ])
        except Exception:
            pass
        if not trades:
            return "No trades in last 6 days.", None
        lines = [
            f"- {t.get('trade_time', t.get('time', '?'))[:19]} "
            f"{t.get('symbol', '?')} {t.get('side', '?')} "
            f"{t.get('size', t.get('filledQuantity', '?'))} @ {t.get('price', t.get('avgPrice', '?'))}"
            for t in trades[:20]
        ]
        return f"Recent trades (last 6 days, {len(trades)} total):\n" + "\n".join(lines), None

    def _get_live_orders(self, inputs: dict) -> tuple[str, Any]:
        orders = self._client.get_live_orders()
        if not orders:
            return "No open orders.", None
        lines = [
            f"- {o.get('orderId', '?')} {o.get('ticker', o.get('symbol', '?'))} "
            f"{o.get('side', '?')} {o.get('totalSize', '?')} @ {o.get('price', 'MKT')} "
            f"[{o.get('status', '?')}]"
            for o in orders
        ]
        return f"Live orders ({len(orders)}):\n" + "\n".join(lines), None

    def _get_ledger(self, inputs: dict) -> tuple[str, Any]:
        accounts = self._client.get_accounts()
        if not accounts:
            return "No accounts found.", None
        account_id = accounts[0].get("accountId", accounts[0].get("id", ""))
        ledger = self._client.get_account_ledger(account_id)
        return json.dumps(ledger, indent=2), None

    def _get_allocation(self, inputs: dict) -> tuple[str, Any]:
        accounts = self._client.get_accounts()
        if not accounts:
            return "No accounts found.", None
        account_id = accounts[0].get("accountId", accounts[0].get("id", ""))
        allocation = self._client.get_account_allocation(account_id)
        return json.dumps(allocation, indent=2), None

    def _get_pa_performance(self, inputs: dict) -> tuple[str, Any]:
        accounts = self._client.get_accounts()
        if not accounts:
            return "No accounts found.", None
        account_ids = [a.get("accountId", a.get("id", "")) for a in accounts]
        perf = self._client.get_pa_performance(account_ids, inputs["period"])
        return json.dumps(perf, indent=2), None

    def _get_pa_transactions(self, inputs: dict) -> tuple[str, Any]:
        accounts = self._client.get_accounts()
        if not accounts:
            return "No accounts found.", None
        account_ids = [a.get("accountId", a.get("id", "")) for a in accounts]
        txns = self._client.get_pa_transactions(account_ids, inputs["period"])
        return json.dumps(txns, indent=2), None

    def _get_contract_info(self, inputs: dict) -> tuple[str, Any]:
        symbol = inputs["symbol"].upper()
        sec_type = inputs.get("sec_type", "STK")
        contracts = self._client.search_contract(symbol, sec_type)
        if not contracts:
            return f"No contract found for {symbol}.", None
        conid = contracts[0].get("conid")
        if not conid:
            return f"Contract found but conid missing: {contracts[0]}", None
        info = self._client.get_contract_info_and_rules(conid)
        return json.dumps(info, indent=2), None

    def _get_option_chain(self, inputs: dict) -> tuple[str, Any]:
        symbol = inputs["symbol"].upper()
        exchange = inputs.get("exchange", "SMART")
        chain = self._client.get_option_chain(symbol, exchange=exchange)
        return json.dumps(chain, indent=2), None

    def _run_scanner(self, inputs: dict) -> tuple[str, Any]:
        params = {
            "instrument": inputs.get("instrument", "STK"),
            "location": inputs.get("location_code", "STK.US.MAJOR"),
            "scanCode": inputs["scan_code"],
            "secType": "STK",
            "filter": [],
        }
        results = self._client.run_iserver_scanner(params)
        if not results:
            return f"Scanner returned no results for {inputs['scan_code']}.", None
        max_r = inputs.get("max_results", 25)
        lines = [
            f"{i+1}. {r.get('symbol', r.get('contractDescription', {}).get('symbol', '?'))} "
            f"({r.get('contractDescription', {}).get('exchange', '?')})"
            for i, r in enumerate(results[:max_r])
        ]
        return f"Scanner: {inputs['scan_code']} — {len(results)} results:\n" + "\n".join(lines), None

    def _get_notifications(self, inputs: dict) -> tuple[str, Any]:
        max_r = inputs.get("max_results", 10)
        notifications = self._client.get_notifications(max_r)
        unread = self._client.get_unread_count()
        if not notifications:
            return f"No FYI notifications. Unread count: {unread}", None
        lines = [
            f"- [{('UNREAD' if not n.get('isRead') else 'read')}] {n.get('headline', n.get('title', '?'))}"
            for n in notifications
        ]
        return f"FYI Notifications ({unread} unread):\n" + "\n".join(lines), None
