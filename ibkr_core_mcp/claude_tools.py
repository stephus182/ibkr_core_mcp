from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Any

import pandas as pd

from ibkr_core_mcp import analytics as _analytics
from ibkr_core_mcp import indicators as _indicators
from ibkr_core_mcp import pinescript as _pinescript
from ibkr_core_mcp.backtest import run_backtest as _run_backtest
from ibkr_core_mcp.cache import GDriveCache
from ibkr_core_mcp.models import bars_to_dataframe as _bars_to_dataframe
from ibkr_core_mcp.client import IBKRClient
from ibkr_core_mcp.config import Config
from ibkr_core_mcp.store import SQLiteStore

log = logging.getLogger(__name__)


def _TODAY() -> str:
    return str(date.today())


def _format_coverage(cov: dict[str, Any]) -> list[str]:
    """Format trade date coverage into human-readable lines, with staleness and gap instructions."""
    days_old = cov.get("days_since_newest", 0)
    stale_note = f" ⚠ DATA STALE ({days_old}d old) — run sync_flex_trades to refresh" if cov.get("stale") else ""
    lines = [
        f"\nTrade history: {cov['oldest']} → {cov['newest']}  ({cov['total_trades']} trades total){stale_note}",
    ]
    gaps = cov.get("gaps", [])
    if not gaps:
        lines.append("Coverage integrity: OK — no significant gaps detected.")
    else:
        lines.append(f"Coverage integrity: {len(gaps)} gap(s) require attention:")
        for g in gaps:
            lines.append(
                f"  Gap {g['gap_start']} → {g['gap_end']} ({g['calendar_days']} days). "
                f"To fill: download Flex XML for {g['request_from']} to {g['request_to']} "
                f"from IBKR website → upload to account_data/ on Drive → run sync_flex_archive."
            )
    return lines

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
        "description": (
            "Get trade history. source='live' queries IBKR directly (last 6 days only). "
            "source='store' queries the local SQLite store — unlimited history, includes all data "
            "synced via sync_flex_trades. Use source='store' for any analysis beyond 6 days."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Filter by symbol (optional)"},
                "source": {
                    "type": "string",
                    "description": "'live' (IBKR API, last 6 days) or 'store' (SQLite, unlimited history including Flex syncs)",
                    "default": "store",
                },
                "start": {"type": "string", "description": "Start date YYYY-MM-DD (store source only, optional)"},
                "end": {"type": "string", "description": "End date YYYY-MM-DD (store source only, optional)"},
            },
            "required": [],
        },
    },
    {
        "name": "sync_flex_archive",
        "description": (
            "Download all Flex XML files from the 'ibkr_flex_archive' Google Drive subfolder "
            "and import them into the local SQLite trade store. Use for historical backfill: "
            "upload year-by-year XML files to Drive first, then run this once. "
            "Duplicates are handled automatically. Runs check_flex_coverage at the end."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "import_flex_file",
        "description": (
            "Import a locally downloaded IBKR Flex XML file into the SQLite trade store. "
            "Use for historical backfill: download year-by-year XMLs from the IBKR website "
            "(Performance & Reports → Flex Queries → Run with custom date range), save each "
            "file to ~/.ibkr_core/flex_archive/, then call this tool for each file. "
            "Duplicates are handled automatically (idempotent)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path to the Flex XML file"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "check_flex_coverage",
        "description": (
            "Check the date coverage of historical trade data in the local SQLite store. "
            "Reports oldest and newest trade dates, total trade count, and any gaps larger "
            "than 5 calendar days that may indicate missing historical imports."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "sync_flex_trades",
        "description": (
            "Fetch the full historical trade history from IBKR Flex Web Service and store it in "
            "the local SQLite database and Google Drive cache. Requires IBKR_FLEX_TOKEN and "
            "IBKR_FLEX_QUERY_ID to be configured. Run this once or daily to keep historical "
            "trade data current beyond the 6-day API limit."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "IBKR account ID (optional — resolved automatically if omitted)"},
            },
            "required": [],
        },
    },
    {
        "name": "get_live_orders",
        "description": (
            "Get ALL non-terminal orders for the account regardless of origin — "
            "includes orders placed via IBKR mobile, TWS, web portal, or ClaudIA staging. "
            "Uses the account-scoped endpoint which returns every working order on the account. "
            "IMPORTANT: orders placed via mobile or TWS CANNOT be modified or cancelled by the API. "
            "When reporting such orders, explicitly state: 'I can see this order but cannot modify "
            "or cancel it — use IBKR mobile or TWS to manage it.' Never skip or silently omit "
            "externally-placed orders. Always flag their origin when it differs from ClaudIA staging."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "diagnose_orders",
        "description": (
            "Return the raw unfiltered IBKR orders API response for debugging. "
            "Use when get_live_orders returns empty but the user believes they have open orders. "
            "Shows ALL orders regardless of status, plus the raw response shape, "
            "so you can identify whether orders are present but filtered, or genuinely absent."
        ),
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
    {
        "name": "add_indicators",
        "description": (
            "Load cached market data for a symbol and compute all technical indicators "
            "(RSI, MACD, Bollinger Bands, ATR, VWAP, OBV, Stochastic, Williams %R, Keltner Channels). "
            "Returns a summary of current indicator values."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Ticker symbol"},
                "timeframe": {"type": "string", "description": "e.g. '1D'"},
                "period": {"type": "string", "description": "e.g. '1Y'"},
                "end": {"type": "string", "description": "End date YYYY-MM-DD"},
            },
            "required": ["symbol", "timeframe", "period", "end"],
        },
    },
    {
        "name": "run_backtest",
        "description": (
            "Execute a Python strategy in a sandboxed environment against cached market data. "
            "Strategy code receives a pandas DataFrame `df` with OHLCV columns and must set "
            "df['signal'] = 1 (long), 0 (flat), or -1 (short). "
            "Returns Sharpe ratio, total return, max drawdown, trade count, and win rate."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python strategy code string"},
                "symbol": {"type": "string", "description": "Ticker symbol"},
                "timeframe": {"type": "string", "description": "e.g. '1D'"},
                "period": {"type": "string", "description": "e.g. '1Y'"},
                "end": {"type": "string", "description": "End date YYYY-MM-DD"},
                "strategy_name": {"type": "string", "description": "Human-readable name", "default": ""},
            },
            "required": ["code", "symbol", "timeframe", "period", "end"],
        },
    },
    {
        "name": "generate_pinescript",
        "description": (
            "Generate a PineScript v5 script for TradingView from a list of indicators "
            "or from a previously run backtest strategy. "
            "Output can be pasted directly into the TradingView Pine Editor."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Ticker symbol"},
                "indicators": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of indicators: 'rsi', 'macd', 'bollinger_bands', 'ema', 'sma', 'atr'",
                },
                "strategy_name": {"type": "string", "description": "Optional name for the script", "default": ""},
            },
            "required": ["symbol", "indicators"],
        },
    },
    {
        "name": "get_analytics",
        "description": (
            "Compute full portfolio/strategy analytics on cached OHLCV data: "
            "Sharpe ratio, Sortino ratio, Calmar ratio, CAGR, max drawdown, and drawdown duration."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Ticker symbol"},
                "timeframe": {"type": "string", "description": "e.g. '1D'"},
                "period": {"type": "string", "description": "e.g. '1Y'"},
                "end": {"type": "string", "description": "End date YYYY-MM-DD"},
            },
            "required": ["symbol", "timeframe", "period", "end"],
        },
    },
    {
        "name": "preview_order",
        "description": (
            "Preview an order using IBKR's whatif endpoint — returns estimated cost, "
            "commission, margin impact, and buying power effect WITHOUT placing the order. "
            "Use this before proposing a trade to verify feasibility and cost."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Ticker symbol, e.g. AAPL"},
                "action": {"type": "string", "description": "'BUY' or 'SELL'"},
                "quantity": {"type": "integer", "description": "Number of shares"},
                "order_type": {
                    "type": "string",
                    "description": "'MKT', 'LMT', or 'STP'",
                    "default": "MKT",
                },
                "limit_price": {
                    "type": "number",
                    "description": "Limit price (required if order_type='LMT')",
                },
            },
            "required": ["symbol", "action", "quantity"],
        },
    },
    {
        "name": "get_pnl",
        "description": (
            "Get real-time partitioned P&L for the IBKR account: "
            "daily P&L, unrealized P&L, and realized P&L broken down by position."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "search_contract",
        "description": (
            "Search for IBKR contracts by symbol and security type. "
            "Returns conid, exchange, currency, and description. "
            "Use this to discover conids before calling tools that require one."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Ticker symbol, e.g. CL, AAPL, SPY"},
                "sec_type": {
                    "type": "string",
                    "description": "Security type: STK, FUT, OPT, FX, IND, CFD, BOND (default: STK)",
                },
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "get_futures",
        "description": (
            "Look up futures contracts for one or more symbols. "
            "Returns available expiry months, conids, and exchange info. "
            "Useful for CL, ES, NQ, GC, and other futures."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbols": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of root symbols, e.g. ['CL', 'ES']",
                },
            },
            "required": ["symbols"],
        },
    },
    {
        "name": "get_market_snapshot",
        "description": (
            "Get live real-time market data snapshot for one or more symbols: "
            "last price, bid, ask, volume, high, low, and change%. "
            "Resolves symbols to conids automatically."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbols": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of symbols, e.g. ['CL', 'GLD', 'SPY']",
                },
                "sec_type": {
                    "type": "string",
                    "description": "Security type for contract lookup: STK, FUT, etc. (default: STK)",
                },
            },
            "required": ["symbols"],
        },
    },
    {
        "name": "get_trading_schedule",
        "description": (
            "Get the trading schedule and session hours for a symbol: "
            "regular trading hours, pre/post-market sessions, and next trading date. "
            "Useful for futures (e.g. CL on NYMEX) and equities."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Ticker symbol, e.g. CL, AAPL"},
                "asset_class": {
                    "type": "string",
                    "description": "Asset class: STK, FUT, OPT, FX (default: STK)",
                },
                "exchange": {
                    "type": "string",
                    "description": "Exchange, e.g. NYMEX, NYSE, NASDAQ (default: SMART)",
                },
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "get_alerts",
        "description": "List all IBKR price alerts configured on the account.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "create_price_alert",
        "description": (
            "Create a native IBKR price alert for a symbol. "
            "The alert fires server-side (even when the app is closed) when the price "
            "crosses the threshold. Use '>=' for above and '<=' for below."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Ticker symbol, e.g. AAPL, CL"},
                "sec_type": {
                    "type": "string",
                    "description": "Security type: STK, FUT, OPT, FX (default: STK)",
                },
                "operator": {
                    "type": "string",
                    "enum": [">=", "<="],
                    "description": "'>=' triggers when price reaches or exceeds threshold; '<=' when it falls to or below",
                },
                "price": {"type": "number", "description": "Price threshold"},
                "tif": {
                    "type": "string",
                    "enum": ["GTC", "DAY"],
                    "description": "Time in force: 'GTC' (good till cancelled, default) or 'DAY' (expires at market close)",
                },
                "outside_rth": {
                    "type": "boolean",
                    "description": "If true, alert also monitors extended hours (pre-market and after-hours). Default false (regular hours only). Useful for earnings.",
                },
                "name": {
                    "type": "string",
                    "description": "Human-readable alert name (default: auto-generated from symbol and price)",
                },
                "repeat": {
                    "type": "boolean",
                    "description": "Whether to repeat the alert after it fires (default: false)",
                },
            },
            "required": ["symbol", "operator", "price"],
        },
    },
    {
        "name": "delete_alert",
        "description": "Delete an IBKR price alert by its alert ID. Use get_alerts first to find the ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "alert_id": {"type": "string", "description": "Alert ID from get_alerts"},
            },
            "required": ["alert_id"],
        },
    },
    {
        "name": "activate_alert",
        "description": "Activate or deactivate an existing IBKR price alert without deleting it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "alert_id": {"type": "string", "description": "Alert ID from get_alerts"},
                "activate": {
                    "type": "boolean",
                    "description": "true to activate, false to deactivate (default: true)",
                },
            },
            "required": ["alert_id"],
        },
    },
    {
        "name": "modify_price_alert",
        "description": (
            "Modify an existing IBKR price alert. Fetches the current alert by ID and "
            "applies only the fields you provide, leaving others unchanged. "
            "Use get_alerts first to find the alert ID."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "alert_id": {"type": "string", "description": "Alert ID from get_alerts"},
                "price": {"type": "number", "description": "New price threshold"},
                "operator": {
                    "type": "string",
                    "enum": [">=", "<="],
                    "description": "New operator: '>=' (above) or '<=' (below)",
                },
                "tif": {
                    "type": "string",
                    "enum": ["GTC", "DAY"],
                    "description": "New time in force: GTC or DAY",
                },
                "outside_rth": {
                    "type": "boolean",
                    "description": "New session scope: true = extended hours, false = regular hours only",
                },
                "name": {"type": "string", "description": "New alert name"},
            },
            "required": ["alert_id"],
        },
    },
    {
        "name": "get_watchlists",
        "description": "List all IBKR watchlists and their contents.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_order_status",
        "description": "Get the status and details of a specific order by its order ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "IBKR order ID"},
            },
            "required": ["order_id"],
        },
    },
    {
        "name": "delete_cache",
        "description": (
            "Delete a specific dataset from the Google Drive cache. "
            "Use when cached data is stale and needs to be re-fetched."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Ticker symbol"},
                "timeframe": {"type": "string", "description": "Bar size, e.g. 1D, 1H"},
                "period": {"type": "string", "description": "Lookback period, e.g. 1Y, 6M"},
                "end": {"type": "string", "description": "End date YYYY-MM-DD"},
            },
            "required": ["symbol", "timeframe", "period", "end"],
        },
    },
]


_ACCOUNT_ID_RE = re.compile(r"^[A-Z0-9]{4,12}$")


def _safe_error(tool: str, exc: Exception) -> str:
    """Return a controlled error string that doesn't leak internal details to the LLM."""
    from ibkr_core_mcp.exceptions import (
        BacktestError,
        BacktestRuntimeError,
        BacktestSyntaxError,
        CacheError,
        ConfigError,
        FlexQueryError,
        IBKRAPIError,
        IBKRAuthError,
        IBKRRateLimitError,
    )
    if isinstance(exc, IBKRAuthError):
        return f"Tool '{tool}' failed: IBKR session not authenticated. Re-open the gateway and log in."
    if isinstance(exc, IBKRRateLimitError):
        return f"Tool '{tool}' failed: IBKR rate limit hit. Retry in a few seconds."
    if isinstance(exc, IBKRAPIError):
        return f"Tool '{tool}' failed: IBKR gateway returned an error (HTTP {exc.status_code})."
    if isinstance(exc, CacheError):
        return f"Tool '{tool}' failed: Google Drive cache error. Check Drive credentials."
    if isinstance(exc, BacktestSyntaxError):
        return f"Tool '{tool}' failed: strategy has a syntax error."
    if isinstance(exc, BacktestRuntimeError):
        return f"Tool '{tool}' failed: strategy raised a runtime error."
    if isinstance(exc, BacktestError):
        return f"Tool '{tool}' failed: backtest error."
    if isinstance(exc, FlexQueryError):
        return f"Tool '{tool}' failed: {exc}"
    if isinstance(exc, ConfigError):
        return f"Tool '{tool}' failed: configuration error. Check .env settings."
    if isinstance(exc, KeyError):
        return f"Tool '{tool}' failed: missing required input field."
    return f"Tool '{tool}' encountered an unexpected error."


def _validate_account_id(account_id: str) -> str:
    """Raise ValueError if account_id is not a valid IBKR account ID format."""
    if not _ACCOUNT_ID_RE.match(account_id):
        raise ValueError(f"Invalid account ID format: {account_id!r}")
    return account_id


_SIDE_MAP = {"B": "BUY", "S": "SELL", "BUY": "BUY", "SELL": "SELL"}


def _parse_live_trades(raw: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Validate and normalise raw IBKR live trade records into store schema.

    Mirrors the integrity guarantees of FlexQueryClient._parse_trades:
    - Skips records missing execution_id, symbol, side, or time.
    - Never falls back to a loop index for execution_id (would cause cross-call collisions).
    - Normalises side: B→BUY, S→SELL.
    - Applies abs() to commission (IBKR reports negative values).

    Returns (parsed_records, skipped_count).
    """
    parsed: list[dict[str, Any]] = []
    skipped = 0
    for t in raw:
        execution_id = (t.get("execution_id") or t.get("execId") or "").strip()
        symbol = (t.get("symbol") or t.get("ticker") or "").upper().strip()
        raw_side = (t.get("side") or "").strip()
        side = _SIDE_MAP.get(raw_side.upper())
        time_val = str(t.get("trade_time") or t.get("time") or "").strip()

        if not execution_id or not symbol or not side or not time_val:
            skipped += 1
            continue

        try:
            size = float(t.get("size") or t.get("filledQuantity") or 0)
            price = float(t.get("price") or t.get("avgPrice") or 0)
            commission = abs(float(t.get("commission") or 0))
        except (ValueError, TypeError):
            skipped += 1
            continue

        parsed.append({
            "execution_id": execution_id,
            "symbol": symbol,
            "side": side,
            "size": size,
            "price": price,
            "time": time_val,
            "commission": commission,
            "account": str(t.get("account") or t.get("acctID") or ""),
        })
    return parsed, skipped


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
    def client(self) -> IBKRClient:
        return self._client

    @property
    def tools(self) -> list[dict[str, Any]]:
        return TOOL_DEFINITIONS

    def execute(self, name: str, inputs: dict[str, Any]) -> tuple[str, Any]:
        """Execute a tool call. Returns (text_result, optional_plotly_fig)."""
        handlers = {
            "fetch_market_data": self._fetch_market_data,
            "check_cache": self._check_cache,
            "list_cache": self._list_cache,
            "get_account_summary": self._get_account_summary,
            "get_positions": self._get_positions,
            "get_trades": self._get_trades,
            "sync_flex_archive": self._sync_flex_archive,
            "import_flex_file": self._import_flex_file,
            "check_flex_coverage": self._check_flex_coverage,
            "sync_flex_trades": self._sync_flex_trades,
            "get_live_orders": self._get_live_orders,
            "diagnose_orders": self._diagnose_orders,
            "get_ledger": self._get_ledger,
            "get_allocation": self._get_allocation,
            "get_pa_performance": self._get_pa_performance,
            "get_pa_transactions": self._get_pa_transactions,
            "get_contract_info": self._get_contract_info,
            "get_option_chain": self._get_option_chain,
            "run_scanner": self._run_scanner,
            "get_notifications": self._get_notifications,
            "add_indicators": self._add_indicators,
            "run_backtest": self._run_backtest,
            "generate_pinescript": self._generate_pinescript,
            "get_analytics": self._get_analytics,
            "preview_order": self._preview_order,
            "get_pnl": self._get_pnl,
            "search_contract": self._search_contract,
            "get_futures": self._get_futures,
            "get_market_snapshot": self._get_market_snapshot,
            "get_trading_schedule": self._get_trading_schedule,
            "get_alerts": self._get_alerts,
            "create_price_alert": self._create_price_alert,
            "modify_price_alert": self._modify_price_alert,
            "delete_alert": self._delete_alert,
            "activate_alert": self._activate_alert,
            "get_watchlists": self._get_watchlists,
            "get_order_status": self._get_order_status,
            "delete_cache": self._delete_cache,
        }
        handler = handlers.get(name)
        if not handler:
            return f"Unknown tool: {name}", None
        try:
            return handler(inputs)
        except Exception as e:
            return _safe_error(name, e), None

    # ── Private helpers ───────────────────────────────────────────────────────

    def _get_accounts(self) -> tuple[list[dict], str | None]:
        accounts = self._client.get_accounts()
        if not accounts:
            return [], "No accounts found."
        return accounts, None

    def _first_account_id(self) -> tuple[str, str | None]:
        accounts, err = self._get_accounts()
        if err:
            return "", err
        return accounts[0].get("accountId", accounts[0].get("id", "")), None

    def _all_account_ids(self) -> tuple[list[str], str | None]:
        accounts, err = self._get_accounts()
        if err:
            return [], err
        return [a.get("accountId", a.get("id", "")) for a in accounts], None

    def _resolve_conid(self, symbol: str, sec_type: str = "STK") -> tuple[str, str | None]:
        contracts = self._client.search_contract(symbol, sec_type)
        if not contracts:
            return "", f"No contract found for {symbol}."
        conid = contracts[0].get("conid") or contracts[0].get("con_id")
        if not conid:
            return "", f"Contract found for {symbol} but conid missing: {contracts[0]}"
        return str(conid), None

    def _fetch_market_data(self, inputs: dict[str, Any]) -> tuple[str, Any]:
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

        conid, err = self._resolve_conid(symbol)
        if err:
            return f"{err} Is IBKR connected?", None

        # HMDS first-call behavior: IBKR initializes a data subscription on the first
        # request for a symbol, which typically returns 404 or 500 while warming up.
        # Retry up to 3 times with a short delay before giving up.
        import time
        from ibkr_core_mcp.exceptions import IBKRAPIError
        raw = None
        for attempt in range(3):
            try:
                raw = self._client.get_hmds_history(conid, period=period, bar=bar)
                break
            except IBKRAPIError:
                if attempt < 2:
                    time.sleep(2)
        if raw is None or not raw.get("data"):
            return f"IBKR returned no data for {symbol} (period={period}, bar={bar})", None

        df = _bars_to_dataframe(raw)

        self._cache.save(df, symbol, timeframe, period, end)
        return (
            f"Fetched {symbol} {timeframe} ({period}) from IBKR: "
            f"{len(df)} bars from {df.index[0].date()} to {df.index[-1].date()}. "
            f"Saved to Drive cache.",
            None,
        )

    def _check_cache(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        hit = self._cache.check(
            inputs["symbol"], inputs["timeframe"], inputs["period"], inputs["end"]
        )
        label = "HIT" if hit else "MISS"
        return f"Cache {label} for {inputs['symbol']} {inputs['timeframe']} {inputs['period']}–{inputs['end']}", None

    def _list_cache(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        entries = self._cache.list_cached()
        if not entries:
            return "Drive cache is empty.", None
        lines = [f"- {e['key']}: {e.get('rows', '?')} bars, cached {e.get('cached_at', '?')[:10]}" for e in entries]
        return f"Cached datasets ({len(entries)}):\n" + "\n".join(lines), None

    def _get_account_summary(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        account_id, err = self._first_account_id()
        if err:
            return err, None
        summary = self._client.get_account_summary(account_id)
        return json.dumps(summary, indent=2), None

    def _get_positions(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        account_id, err = self._first_account_id()
        if err:
            return err, None
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

    def _get_trades(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        source = inputs.get("source", "store")
        symbol = inputs.get("symbol")
        if source == "store":
            trades = self._store.get_trades(
                symbol=symbol,
                start=inputs.get("start"),
                end=inputs.get("end"),
            )
            if not trades:
                return "No trades found in local store.", None
            lines = [f"- {t['time'][:10]} {t['symbol']} {t['side']} {t['size']} @ {t['price']}" for t in trades[:20]]
            suffix = f"  (showing first 20 of {len(trades)})" if len(trades) > 20 else ""
            return f"Trade history (SQLite, {len(trades)} total){suffix}:\n" + "\n".join(lines), None
        # source == 'live'
        trades = self._client.get_trades()
        if symbol:
            trades = [t for t in trades if t.get("symbol", "").upper() == symbol.upper()]

        parsed, skipped = _parse_live_trades(trades)
        upsert_note = ""
        if parsed:
            try:
                self._store.upsert_trades(parsed)
            except Exception as exc:
                upsert_note = f"\n⚠ Store upsert failed: {exc}"
        skip_note = f" ({skipped} record(s) skipped — missing required fields)" if skipped else ""

        if not trades:
            return "No trades in last 6 days.", None
        lines = [
            f"- {t['time'][:19]} {t['symbol']} {t['side']} {t['size']} @ {t['price']}"
            for t in parsed[:20]
        ]
        suffix = f"  (showing first 20 of {len(parsed)})" if len(parsed) > 20 else ""
        return (
            f"Recent trades (last 6 days, {len(parsed)} total){skip_note}{suffix}:\n"
            + "\n".join(lines) + upsert_note
        ), None

    def _sync_flex_trades(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        from ibkr_core_mcp.flex_query import FlexQueryClient
        if not self._config.flex_token or not self._config.flex_query_id:
            return (
                "Flex Query not configured. Set IBKR_FLEX_TOKEN and IBKR_FLEX_QUERY_ID in .env. "
                "Token and Query ID must be created manually on the IBKR website under Reports → Flex Queries.",
                None,
            )
        account_id = inputs.get("account_id", "")
        if not account_id:
            account_id, _ = self._first_account_id()
        if not account_id:
            return "Could not resolve account ID. Pass account_id explicitly.", None
        _validate_account_id(account_id)
        flex = FlexQueryClient(self._config, self._store, self._cache)
        trades = flex.fetch_trades(account_id)
        cov = self._store.get_trade_date_coverage()
        self._store.log_entry(
            "flex_sync",
            account=account_id,
            trades_fetched=len(trades),
            newest=cov.get("newest"),
            total=cov.get("total_trades"),
        )
        lines = [f"Flex sync complete: {len(trades)} trades fetched for account {account_id}."]
        lines.extend(_format_coverage(cov))
        return "\n".join(lines), None

    def _sync_flex_archive(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        from ibkr_core_mcp.flex_query import FlexQueryClient
        flex = FlexQueryClient(self._config, self._store, self._cache)
        try:
            result = flex.sync_archive_from_drive()
        except FileNotFoundError as e:
            return str(e), None
        if result["files"] == 0:
            return "No XML files found in account_data/ on Drive.", None
        lines = [f"Imported {result['trades']} trades from {result['files']} file(s):"]
        for p in result.get("processed", []):
            lines.append(f"  {p['file']}: {p['trades']} trades ({p['range']})")
        lines.extend(_format_coverage(self._store.get_trade_date_coverage()))
        return "\n".join(lines), None

    def _import_flex_file(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        from ibkr_core_mcp.flex_query import FlexQueryClient
        from pathlib import Path
        path = inputs["path"]
        if not Path(path).exists():
            return f"File not found: {path}", None
        flex = FlexQueryClient(self._config, self._store, self._cache)
        trades = flex.import_from_file(path)
        if not trades:
            return f"No trades found in {path}.", None
        dates = sorted(t["time"][:10] for t in trades)
        lines = [
            f"Imported {len(trades)} trades from {Path(path).name}: {dates[0]} → {dates[-1]}.",
        ]
        lines.extend(_format_coverage(self._store.get_trade_date_coverage()))
        return "\n".join(lines), None

    def _check_flex_coverage(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        cov = self._store.get_trade_date_coverage()
        if not cov["oldest"]:
            return "No trade history in store. Run sync_flex_archive or sync_flex_trades first.", None
        return "\n".join(_format_coverage(cov)), None

    def _get_live_orders(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        orders = self._client.get_live_orders()
        if not orders:
            return "No open orders.", None
        lines = []
        for o in orders:
            ticker = o.get("ticker") or o.get("symbol") or "?"
            side = o.get("side", "?")
            qty = o.get("totalSize", "?")
            price = o.get("price", "MKT")
            status = o.get("status", "?")
            tif = o.get("timeInForce") or o.get("tif") or ""
            order_ref = o.get("orderRef") or o.get("cOID") or o.get("clientOrderId") or ""
            client_id = o.get("clientId")
            # Determine origin: CLAUDIA-prefixed cOID is definitive; clientId is unreliable
            # because both ClaudIA (Client Portal API) and mobile orders may show clientId=0
            if order_ref.startswith("CLAUDIA-"):
                origin = "ClaudIA-staged"
            elif client_id and client_id != 0:
                origin = f"API (clientId={client_id})"
            else:
                origin = "EXTERNAL (mobile/TWS/web portal) — read-only via API"
            line = (
                f"- orderId={o.get('orderId', '?')} {ticker} {side} {qty} @ {price} "
                f"[{status}] TIF={tif} origin={origin}"
            )
            if order_ref and not order_ref.startswith("CLAUDIA-"):
                line += f" ref={order_ref}"
            lines.append(line)
        return f"Live orders ({len(orders)}):\n" + "\n".join(lines), None

    def _diagnose_orders(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        """Return the raw unfiltered orders response to diagnose empty results."""
        accounts = self._client.get_accounts()
        account_id = accounts[0].get("id") or accounts[0].get("accountId") if accounts else None
        if account_id:
            path = f"/iserver/account/{account_id}/orders?force=true"
        else:
            path = "/iserver/account/orders?force=true"
        raw = self._client._get(path)
        if isinstance(raw, dict):
            orders = raw.get("orders", raw)
        else:
            orders = raw
        if not isinstance(orders, list):
            return (
                f"Unexpected response shape — not a list.\n"
                f"Response type: {type(raw).__name__}\n"
                f"Raw response:\n{json.dumps(raw, indent=2)}"
            ), None
        if not orders:
            return (
                "Orders list is genuinely empty in the raw IBKR response.\n"
                "No orders exist at the server level — not a filtering issue.\n"
                f"Full raw response:\n{json.dumps(raw, indent=2)}"
            ), None
        # Show every order with all fields + note which would be filtered
        terminal = {"Filled", "Cancelled", "ApiCancelled", "Expired"}
        lines = []
        for o in orders:
            status = o.get("status", "MISSING")
            filtered = " [FILTERED by get_live_orders]" if status in terminal or not status else ""
            order_ref = o.get("orderRef") or o.get("cOID") or ""
            client_id = o.get("clientId", "absent")
            lines.append(
                f"orderId={o.get('orderId')} ticker={o.get('ticker', o.get('symbol'))} "
                f"side={o.get('side')} qty={o.get('totalSize')} price={o.get('price')} "
                f"status={status} clientId={client_id} ref={order_ref or 'none'}{filtered}"
            )
        return (
            f"Endpoint used: {path}\nRaw IBKR orders ({len(orders)} total):\n" + "\n".join(lines)
        ), None

    def _get_ledger(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        account_id, err = self._first_account_id()
        if err:
            return err, None
        ledger = self._client.get_account_ledger(account_id)
        return json.dumps(ledger, indent=2), None

    def _get_allocation(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        account_id, err = self._first_account_id()
        if err:
            return err, None
        allocation = self._client.get_account_allocation(account_id)
        return json.dumps(allocation, indent=2), None

    def _get_pa_performance(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        account_ids, err = self._all_account_ids()
        if err:
            return err, None
        perf = self._client.get_pa_performance(account_ids, inputs["period"])
        return json.dumps(perf, indent=2), None

    def _get_pa_transactions(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        account_ids, err = self._all_account_ids()
        if err:
            return err, None
        txns = self._client.get_pa_transactions(account_ids, inputs["period"])
        return json.dumps(txns, indent=2), None

    def _get_contract_info(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        symbol = inputs["symbol"].upper()
        sec_type = inputs.get("sec_type", "STK")
        conid, err = self._resolve_conid(symbol, sec_type)
        if err:
            return err, None
        info = self._client.get_contract_info_and_rules(conid)
        return json.dumps(info, indent=2), None

    def _get_option_chain(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        symbol = inputs["symbol"].upper()
        exchange = inputs.get("exchange", "SMART")
        chain = self._client.get_option_chain(symbol, exchange=exchange)
        return json.dumps(chain, indent=2), None

    def _run_scanner(self, inputs: dict[str, Any]) -> tuple[str, Any]:
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

    def _get_notifications(self, inputs: dict[str, Any]) -> tuple[str, Any]:
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

    def _add_indicators(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        symbol = inputs["symbol"].upper()
        timeframe = inputs["timeframe"]
        period = inputs["period"]
        end = inputs["end"]
        if not self._cache.check(symbol, timeframe, period, end):
            return f"No cached data for {symbol} {timeframe} {period}. Fetch it first with fetch_market_data.", None
        df = self._cache.load(symbol, timeframe, period, end)
        df = _indicators.add_all(df)
        last = df.iloc[-1]
        lines = [
            f"Indicators for {symbol} (last bar: {df.index[-1].date()}):",
            f"  RSI(14):          {last.get('rsi', float('nan')):.1f}",
            f"  MACD:             {last.get('macd', float('nan')):.4f}  Signal: {last.get('macd_signal', float('nan')):.4f}",
            f"  BB Upper/Mid/Low: {last.get('bb_upper', float('nan')):.2f} / {last.get('bb_mid', float('nan')):.2f} / {last.get('bb_lower', float('nan')):.2f}",
            f"  ATR(14):          {last.get('atr', float('nan')):.4f}",
            f"  VWAP:             {last.get('vwap', float('nan')):.2f}",
            f"  Stoch %K/%D:      {last.get('stoch_k', float('nan')):.1f} / {last.get('stoch_d', float('nan')):.1f}",
            f"  Williams %R:      {last.get('williams_r', float('nan')):.1f}",
            f"  Volume Ratio:     {last.get('volume_ratio', float('nan')):.2f}x avg",
        ]
        return "\n".join(lines), None

    def _run_backtest(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        symbol = inputs["symbol"].upper()
        timeframe = inputs["timeframe"]
        period = inputs["period"]
        end = inputs["end"]
        code = inputs["code"]
        strategy_name = inputs.get("strategy_name", "")
        if not self._cache.check(symbol, timeframe, period, end):
            return f"No cached data for {symbol}. Fetch it first with fetch_market_data.", None
        df = self._cache.load(symbol, timeframe, period, end)
        result = _run_backtest(code, df, strategy_name=strategy_name, symbol=symbol)
        try:
            self._store.save_backtest(result.to_dict())
        except Exception:
            pass
        lines = [
            f"Backtest: {strategy_name or 'Unnamed'} on {symbol} {timeframe} ({period})",
            f"  Total Return:  {result.total_return:.1%}",
            f"  Sharpe Ratio:  {result.sharpe:.2f}",
            f"  Sortino Ratio: {result.sortino:.2f}",
            f"  Max Drawdown:  {result.max_drawdown:.1%}",
            f"  Num Trades:    {result.num_trades}",
            f"  Win Rate:      {result.win_rate:.1%}",
        ]
        return "\n".join(lines), None

    def _generate_pinescript(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        symbol = inputs["symbol"].upper()
        indicators_list = inputs.get("indicators", ["rsi", "macd"])
        strategy_name = inputs.get("strategy_name", f"{symbol} Indicators")
        script = _pinescript.indicator_script(strategy_name, indicators_list, {})
        return script, None

    def _preview_order(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        symbol = inputs["symbol"].upper()
        action = inputs["action"].upper()
        quantity = int(inputs["quantity"])
        order_type = inputs.get("order_type", "MKT").upper()
        limit_price = inputs.get("limit_price")

        conid, err = self._resolve_conid(symbol)
        if err:
            return err, None

        account_id, err = self._first_account_id()
        if err:
            return err, None

        order: dict[str, Any] = {
            "conid": conid,
            "orderType": order_type,
            "side": action,
            "quantity": quantity,
            "tif": "DAY",
        }
        if order_type == "LMT" and limit_price is not None:
            order["price"] = limit_price

        result = self._client.get_order_preview(account_id, order)
        lines = [
            f"Order Preview: {action} {quantity} {symbol} ({order_type})",
            f"  Commission est.:      {result.get('commission', 'N/A')}",
            f"  Equity with loan:     {result.get('equity', {}).get('amount', 'N/A')}",
            f"  Initial margin:       {result.get('initMarginChange', 'N/A')}",
            f"  Maintenance margin:   {result.get('maintMarginChange', 'N/A')}",
            f"  Buying power effect:  {result.get('equity', {}).get('change', 'N/A')}",
        ]
        return "\n".join(lines), None

    def _get_pnl(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        pnl = self._client.get_pnl()
        if not pnl:
            return "No P&L data returned. Ensure IBKR gateway is connected.", None
        lines = ["Real-time P&L:"]
        upnl_total = 0.0
        dpnl_total = 0.0
        for _acct, data in pnl.items():
            if not isinstance(data, dict):
                continue
            for conid, pos_pnl in data.items():
                if not isinstance(pos_pnl, dict):
                    continue
                symbol = pos_pnl.get("ticker", str(conid))
                try:
                    upnl = float(pos_pnl.get("uPnl") or 0)
                    dpnl = float(pos_pnl.get("dPnl") or 0)
                except (ValueError, TypeError):
                    log.warning("Non-numeric P&L for %s, skipping position", symbol)
                    continue
                upnl_total += upnl
                dpnl_total += dpnl
                lines.append(f"  {symbol}: unrealized={upnl:+.2f}  daily={dpnl:+.2f}")
        lines.append(f"\nTotal unrealized P&L: {upnl_total:+.2f}")
        lines.append(f"Total daily P&L:      {dpnl_total:+.2f}")
        return "\n".join(lines), None

    def _get_analytics(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        symbol = inputs["symbol"].upper()
        timeframe = inputs["timeframe"]
        period = inputs["period"]
        end = inputs["end"]
        if not self._cache.check(symbol, timeframe, period, end):
            return f"No cached data for {symbol}. Fetch it first with fetch_market_data.", None
        df = self._cache.load(symbol, timeframe, period, end)
        returns = df["close"].pct_change().dropna()
        report = _analytics.full_report(returns)
        lines = [
            f"Analytics for {symbol} {timeframe} ({period}–{end}):",
            f"  Total Return:       {report['total_return']:.1%}",
            f"  CAGR:               {report['cagr']:.1%}",
            f"  Sharpe Ratio:       {report['sharpe']:.2f}",
            f"  Sortino Ratio:      {report['sortino']:.2f}",
            f"  Calmar Ratio:       {report['calmar']:.2f}",
            f"  Max Drawdown:       {report['max_drawdown']:.1%}",
            f"  Max DD Duration:    {report['max_drawdown_duration']} bars",
            f"  Bars analyzed:      {report['num_bars']}",
        ]
        return "\n".join(lines), None

    def _search_contract(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        symbol = inputs["symbol"].upper()
        sec_type = inputs.get("sec_type", "STK")
        contracts = self._client.search_contract(symbol, sec_type)
        if not contracts:
            return f"No contracts found for {symbol} ({sec_type}).", None
        return json.dumps(contracts, indent=2), None

    def _get_futures(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        symbols = [s.upper() for s in inputs["symbols"]]
        futures = self._client.get_futures(symbols)
        if not futures:
            return f"No futures found for {', '.join(symbols)}.", None
        return json.dumps(futures, indent=2), None

    def _get_market_snapshot(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        symbols = [s.upper() for s in inputs["symbols"]]
        sec_type = inputs.get("sec_type", "STK")
        conids = []
        failed = []
        for sym in symbols:
            contracts = self._client.search_contract(sym, sec_type)
            if contracts:
                conid = contracts[0].get("conid")
                try:
                    conid_int = int(conid) if conid else 0
                except (ValueError, TypeError):
                    conid_int = 0
                if conid_int > 0:
                    conids.append(conid_int)
                else:
                    failed.append(sym)
            else:
                failed.append(sym)
        if not conids:
            return f"Could not resolve conids for: {', '.join(symbols)}.", None
        snapshot = self._client.get_market_snapshot(conids)
        if not snapshot:
            return "No market snapshot data returned.", None
        result = json.dumps(snapshot, indent=2)
        if failed:
            result = f"Note: could not resolve {', '.join(failed)} as {sec_type} — omitted.\n\n" + result
        return result, None

    def _get_trading_schedule(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        symbol = inputs["symbol"].upper()
        asset_class = inputs.get("asset_class", "STK")
        exchange = inputs.get("exchange", "SMART")
        schedule = self._client.get_trading_schedule(asset_class, symbol, exchange)
        return json.dumps(schedule, indent=2), None

    def _get_alerts(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        account_id, err = self._first_account_id()
        if err:
            return err, None
        alerts = self._client.get_alerts(account_id)
        if not alerts:
            return "No price alerts configured.", None
        return json.dumps(alerts, indent=2), None

    def _create_price_alert(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        account_id, err = self._first_account_id()
        if err:
            return err, None
        symbol = inputs["symbol"].upper()
        sec_type = inputs.get("sec_type", "STK")
        operator = inputs["operator"]
        price = inputs["price"]
        tif = inputs.get("tif", "GTC")
        outside_rth = inputs.get("outside_rth", False)
        repeat = inputs.get("repeat", False)
        contracts = self._client.search_contract(symbol, sec_type)
        if not contracts:
            return f"No contract found for {symbol} ({sec_type}).", None
        conid = contracts[0].get("conid")
        if not conid:
            return f"Contract found for {symbol} but conid missing.", None
        try:
            conid_int = int(conid)
        except (ValueError, TypeError):
            return f"Invalid conid '{conid}' returned for {symbol}.", None
        exchange = contracts[0].get("exchange", "SMART")
        name = inputs.get("name") or f"{symbol} {operator} {price}"
        alert = {
            "orderId": 0,
            "alertName": name,
            "alertMessage": "",
            "alertRepeatable": int(repeat),
            "expireTime": "",
            "tif": tif,
            "outsideRth": outside_rth,
            "isSizeCondition": False,
            "conditions": [
                {
                    "type": 1,          # 1 = Price per IBKR Client Portal API
                    "conid": conid_int,
                    "exchange": exchange,
                    "conditionType": "Price",
                    "operator": operator,
                    "value": str(price),
                }
            ],
        }
        result = self._client.create_alert(account_id, alert)
        return json.dumps(result, indent=2), None

    def _modify_price_alert(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        account_id, err = self._first_account_id()
        if err:
            return err, None
        alert_id = inputs["alert_id"]
        existing = self._client.get_alert(account_id, alert_id)
        if not existing:
            return f"Alert {alert_id} not found.", None
        # Apply only the fields provided — leave everything else unchanged
        if "name" in inputs:
            existing["alertName"] = inputs["name"]
        if "tif" in inputs:
            existing["tif"] = inputs["tif"]
        if "outside_rth" in inputs:
            existing["outsideRth"] = inputs["outside_rth"]
        if "price" in inputs or "operator" in inputs:
            conditions = existing.get("conditions", [])
            if conditions:
                if "price" in inputs:
                    conditions[0]["value"] = str(inputs["price"])
                if "operator" in inputs:
                    conditions[0]["operator"] = inputs["operator"]
        result = self._client.create_alert(account_id, existing)
        return json.dumps(result, indent=2), None

    def _delete_alert(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        account_id, err = self._first_account_id()
        if err:
            return err, None
        result = self._client.delete_alert(account_id, inputs["alert_id"])
        return json.dumps(result, indent=2), None

    def _activate_alert(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        account_id, err = self._first_account_id()
        if err:
            return err, None
        activate = inputs.get("activate", True)
        result = self._client.activate_alert(account_id, inputs["alert_id"], activate)
        return json.dumps(result, indent=2), None

    def _get_watchlists(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        watchlists = self._client.get_watchlists()
        if not watchlists:
            return "No watchlists found.", None
        return json.dumps(watchlists, indent=2), None

    def _get_order_status(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        order_id = inputs["order_id"]
        status = self._client.get_order_status(order_id)
        return json.dumps(status, indent=2), None

    def _delete_cache(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        symbol = inputs["symbol"].upper()
        timeframe = inputs["timeframe"]
        period = inputs["period"]
        end = inputs["end"]
        if not self._cache.check(symbol, timeframe, period, end):
            return f"No cached entry for {symbol} {timeframe} ({period}, end={end}).", None
        self._cache.delete(symbol, timeframe, period, end)
        return f"Deleted cache entry for {symbol} {timeframe} ({period}, end={end}).", None
