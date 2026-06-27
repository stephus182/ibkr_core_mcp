from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

import pandas as pd

from ibkr_core_mcp import analytics as _analytics
from ibkr_core_mcp import indicators as _indicators
from ibkr_core_mcp import pinescript as _pinescript
from ibkr_core_mcp.backtest import run_backtest as _run_backtest
from ibkr_core_mcp.cache import GDriveCache
from ibkr_core_mcp.models import bars_to_dataframe as _bars_to_dataframe
from ibkr_core_mcp.client import IBKRClient, _ACCOUNT_ID_RE
from ibkr_core_mcp.config import Config
from ibkr_core_mcp.store import SQLiteStore

log = logging.getLogger(__name__)


def _TODAY() -> str:
    return str(date.today())


def _format_coverage(cov: dict[str, Any]) -> list[str]:
    """Format trade date coverage into human-readable lines with staleness and gap notes."""
    days_old = cov.get("days_since_newest", 0)
    stale_note = f" ⚠ DATA STALE ({days_old}d old) — run sync_flex_trades to refresh" if cov.get("stale") else ""
    lines = [
        f"\nTrade history: {cov['oldest']} → {cov['newest']}  ({cov['total_trades']} trades total){stale_note}",
    ]
    gaps = cov.get("gaps", [])
    if not gaps:
        lines.append("Coverage: no periods longer than 45 days without a recorded trade.")
    else:
        lines.append(
            f"Coverage: {len(gaps)} period(s) of 45+ days with no recorded trades "
            f"(may be inactivity or missing data — only you can tell):"
        )
        for g in gaps:
            lines.append(
                f"  {g['gap_start']} → {g['gap_end']} ({g['calendar_days']} calendar days with no trades)"
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
            "Report the trade activity date range from the local SQLite store: "
            "oldest trade, newest trade, total record count, and periods of 45+ calendar days "
            "with no recorded executions (which may reflect genuine inactivity or missing imports — "
            "use verify_flex_import to distinguish). Does not verify completeness against source."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "verify_flex_import",
        "description": (
            "Verify Flex import completeness by comparing source XML archives in Google Drive "
            "account_data/ against the local SQLite trades table. For each XML file, extracts "
            "all tradeIDs and checks whether they are present in SQLite. Reports per-file "
            "counts (XML records vs SQLite matches) and an aggregate summary. "
            "A missing tradeID means that execution was not imported. "
            "Does not modify any data — read-only integrity check against the source files."
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
        "name": "get_pa_periods",
        "description": "Get the list of valid period strings for Portfolio Analyst queries (performance and transactions). Call this first if unsure which period to use.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_pa_performance",
        "description": "Get portfolio NAV performance from IBKR Portfolio Analyst. Use get_pa_periods first to discover valid period strings.",
        "input_schema": {
            "type": "object",
            "properties": {
                "period": {"type": "string", "description": "Valid period string from get_pa_periods, e.g. 'last7days', 'last30days', 'ytd', 'last365days'"},
            },
            "required": ["period"],
        },
    },
    {
        "name": "get_pa_transactions",
        "description": "Get transaction history from IBKR Portfolio Analyst (all origins: mobile, TWS, API). Use get_pa_periods first to discover valid period strings.",
        "input_schema": {
            "type": "object",
            "properties": {
                "period": {"type": "string", "description": "Valid period string from get_pa_periods, e.g. 'last7days', 'ytd'"},
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
    {
        "name": "firecrawl_search",
        "description": (
            "Search the web using Firecrawl and return full page content as markdown. "
            "Use for research, news, or fetching technical documentation. "
            "Optionally saves a Drive snapshot under web_docs/searches/ for later reference. "
            "Requires FIRECRAWL_API_KEY to be set."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (1-10, default 5)",
                    "default": 5,
                },
                "save_to_drive": {
                    "type": "boolean",
                    "description": "If true, save a markdown snapshot to Drive (default false)",
                    "default": False,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "firecrawl_crawl",
        "description": (
            "Crawl an entire website starting from a URL and save all pages to Drive "
            "under web_docs/{url-slug}/. Returns a summary of pages saved. "
            "Crawls are asynchronous — Firecrawl polls until done or timeout. "
            "Use for archiving IBKR documentation or other reference sites. "
            "Requires FIRECRAWL_API_KEY to be set."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Root URL to crawl from (public http/https only)",
                },
                "max_pages": {
                    "type": "integer",
                    "description": "Maximum pages to crawl (1-100, default 50)",
                    "default": 50,
                },
                "timeout_s": {
                    "type": "integer",
                    "description": "Max seconds to wait for crawl to complete (default 120)",
                    "default": 120,
                },
            },
            "required": ["url"],
        },
    },
]


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
            "asset_class": (t.get("assetClass") or t.get("secType") or "").strip().upper(),
            "realized_pnl": None,  # CP API trades endpoint does not include realized P&L
        })
    return parsed, skipped


class ClaudeToolkit:
    """Ready-made Anthropic tool-use layer for IBKR research. Portable across any Claude-powered app.

    Exposes TOOL_DEFINITIONS (list of Anthropic tool dicts) and execute() to handle tool calls.
    Wire it into any Anthropic SDK messages call:
        response = client.messages.create(model=..., tools=toolkit.tools, ...)
        result, fig = toolkit.execute(tool_name, tool_input)

    Tool routing: IBKR tools → IBKRClient; local tools (search_past_conversations, fetch_web_page)
    → handled in claudia_ui/agent.py; TradingView tools → TradingViewBridge sidecar.

    Source (Anthropic tool use): https://docs.anthropic.com/en/docs/build-with-claude/tool-use
    Source (Anthropic Messages API): https://docs.anthropic.com/en/api/messages
    """

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
        self._firecrawl: Any = None
        self._web_docs: Any = None

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
            "verify_flex_import": self._verify_flex_import,
            "sync_flex_trades": self._sync_flex_trades,
            "get_live_orders": self._get_live_orders,
            "diagnose_orders": self._diagnose_orders,
            "get_ledger": self._get_ledger,
            "get_allocation": self._get_allocation,
            "get_pa_periods": self._get_pa_periods,
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
            "firecrawl_search": self._handle_firecrawl_search,
            "firecrawl_crawl": self._handle_firecrawl_crawl,
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

        # iserver/marketdata/history first-call behavior: IBKR may return 404 or 500
        # on the first request for a symbol while initializing the data subscription,
        # or return a null/empty body. Retry up to 3 times with 2s delays.
        import time
        from ibkr_core_mcp.exceptions import IBKRAPIError
        raw = None
        for attempt in range(3):
            try:
                raw = self._client.get_market_history_paginated(conid, period=period, bar=bar)
                if raw and raw.get("data"):
                    break
            except IBKRAPIError:
                pass
            if attempt < 2:
                time.sleep(2)
        if not raw or not raw.get("data"):
            return (
                f"IBKR returned no data for {symbol} (period={period}, bar={bar}) "
                f"after 3 attempts. Check that the IBKR gateway is authenticated and "
                f"that the period/bar combination is valid for this instrument."
            ), None

        df = _bars_to_dataframe(raw)

        self._cache.save(df, symbol, timeframe, period, end)
        return (
            f"Fetched {symbol} {timeframe} ({period}) from IBKR: "
            f"{len(df)} bars from {df.index[0].date()} to {df.index[-1].date()}. "
            f"Saved to Drive cache.",
            None,
        )

    def _check_cache(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        """Return HIT/MISS for a specific symbol/timeframe/period/end combination."""
        hit = self._cache.check(
            inputs["symbol"], inputs["timeframe"], inputs["period"], inputs["end"]
        )
        label = "HIT" if hit else "MISS"
        return f"Cache {label} for {inputs['symbol']} {inputs['timeframe']} {inputs['period']}–{inputs['end']}", None

    def _list_cache(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        """List all datasets currently in the Drive market-data cache."""
        entries = self._cache.list_cached()
        if not entries:
            return "Drive cache is empty.", None
        lines = [f"- {e['key']}: {e.get('rows', '?')} bars, cached {e.get('cached_at', '?')[:10]}" for e in entries]
        return f"Cached datasets ({len(entries)}):\n" + "\n".join(lines), None

    def _get_account_summary(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        """Return high-level account balances: NLV, cash, gross position value, P&L, buying power."""
        account_id, err = self._first_account_id()
        if err:
            return err, None
        summary = self._client.get_account_summary(account_id)

        def _fmt(key: str) -> str:
            item = summary.get(key, {})
            amt = item.get("amount")
            cur = item.get("currency") or "USD"
            val = item.get("value")
            if amt is not None:
                return f"${amt:,.2f} {cur}"
            return str(val) if val else "—"

        lines = [
            f"Account:             {summary.get('accountcode', {}).get('value', account_id)}",
            f"Net Liquidation:     {_fmt('netliquidation')}",
            f"Cash:                {_fmt('totalcashvalue')}",
            f"Gross Position Val:  {_fmt('grosspositionvalue')}",
            f"Unrealized P&L:      {_fmt('unrealizedpnl')}",
            f"Realized P&L:        {_fmt('realizedpnl')}",
            f"Buying Power:        {_fmt('buyingpower')}",
        ]
        return "\n".join(lines), None

    def _get_positions(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        """Return all open positions across all instrument types (equities, futures, options, etc.).

        IBKR includes flat entries (position=0) in the positions list. These are filtered
        out unconditionally — position=0 means flat regardless of instrument type.
        The quantity label is 'qty' (not 'shares') because the field is generic across
        all IBKR instrument classes.
        """
        account_id, err = self._first_account_id()
        if err:
            return err, None
        positions = self._client.get_positions(account_id)
        # position=0 means flat — not an open position regardless of instrument type.
        positions = [p for p in positions if p.get("position", 0) != 0]
        if not positions:
            return "No open positions.", None
        lines = []
        for p in positions:
            symbol = p.get("contractDesc", p.get("ticker", p.get("symbol", "?")))
            pos = p.get("position", 0)
            mkt_val = p.get("mktValue", 0)
            pnl = p.get("unrealizedPnl", 0)
            lines.append(f"- {symbol}: {pos} qty, mktVal={mkt_val:.2f}, unrealPnL={pnl:.2f}")
        return f"Open positions ({len(positions)}):\n" + "\n".join(lines), None

    def _get_trades(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        """Query trade history from two complementary sources — choose based on recency and origin needs.

        ## source='store' — Flex (full history, all origins)
        Reads local SQLite populated by sync_flex_trades. Covers all trade origins: CP API,
        mobile app, TWS, and web portal. No date limit on queries — full account history from
        the first Flex sync. Availability: T+1 (today's trades are never present; yesterday's
        trades become available after IBKR's overnight processing).
        Source: https://www.ibkrguides.com/orgportal/performanceandstatements/flex.htm

        ## source='live' — CP API /iserver/account/trades (last 7 days max)
        Calls the CP API endpoint with ?days=7 for up to 7 days of recent history (official
        max per IBKR docs). Returns all trades on the account regardless of origin (CP API,
        mobile, TWS). "Currently selected account" in IBKR docs is a multi-account concept
        only — single-account users receive all trades.

        ## Choosing the right source
        - Today's fills (any origin) → source='live' (?days=7 covers current day)
        - Yesterday and earlier, full history → source='store' after sync_flex_trades
        - All origins same-day with P&L breakdown → get_pa_transactions
        """
        source = inputs.get("source", "store")
        symbol = inputs.get("symbol")
        if source == "store":
            trades = self._store.get_trades(
                symbol=symbol,
                start=inputs.get("start"),
                end=inputs.get("end"),
            )
            if not trades:
                return (
                    "No trades found in Flex store for the requested period. "
                    "Run sync_flex_trades to pull the latest data from IBKR (T+1 — yesterday's trades available today)."
                ), None
            total_pnl = sum(t.get("realized_pnl") or 0.0 for t in trades)
            has_pnl = any(t.get("realized_pnl") is not None for t in trades)
            lines = [
                f"- {t['time'][:10]} {t['symbol']} [{t.get('asset_class') or '?'}] "
                f"{t['side']} {t['size']} @ {t['price']} "
                f"comm={t.get('commission', 0):.2f}"
                + (f" pnl={t['realized_pnl']:+.2f}" if t.get("realized_pnl") is not None else "")
                for t in trades[:50]
            ]
            suffix = f"  (showing first 50 of {len(trades)})" if len(trades) > 50 else ""
            pnl_line = f"\nTotal realized P&L: {total_pnl:+.2f}" if has_pnl else ""
            return (
                f"Trade history — Flex store ({len(trades)} total, all origins incl. mobile/TWS){suffix}:\n"
                + "\n".join(lines) + pnl_line
            ), None
        # source == 'live'
        # Note: CP API /iserver/account/trades is session-scoped — mobile/TWS-placed
        # trades from the same account may NOT appear. Use source='store' (Flex) for
        # authoritative multi-day P&L including all origins.
        trades = self._client.get_trades()
        if symbol:
            trades = [t for t in trades if t.get("symbol", "").upper() == symbol.upper()]

        parsed, skipped = _parse_live_trades(trades)
        upsert_note = ""
        if parsed:
            try:
                self._store.upsert_trades(parsed)
            except Exception as exc:
                log.warning("_get_trades: store upsert failed: %s", exc)
                upsert_note = "\n⚠ Trade history could not be saved to local store."
        skip_note = f" ({skipped} record(s) skipped — missing required fields)" if skipped else ""

        if not trades:
            return (
                "No trades visible in CP API session (last 7 days). "
                "Mobile/TWS-placed trades are not included in the session scope. "
                "For today's mobile/TWS fills use get_pa_transactions (all origins, not session-scoped). "
                "For multi-day history use source='store' after syncing with sync_flex_trades (T+1)."
            ), None
        lines = [
            f"- {t['time'][:19]} {t['symbol']} {t['asset_class'] or '?'} {t['side']} {t['size']} @ {t['price']}"
            for t in parsed[:20]
        ]
        suffix = f"  (showing first 20 of {len(parsed)})" if len(parsed) > 20 else ""
        return (
            f"Recent trades — CP API session (last 7 days, {len(parsed)} total){skip_note}{suffix}:\n"
            + "\n".join(lines) + upsert_note
        ), None

    def _sync_flex_trades(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        """Pull the latest historical trades from IBKR Flex Web Service → upsert into local SQLite store.

        ## What Flex covers
        Flex Activity Statements contain the complete execution record for the account across ALL
        trade origins: CP API, mobile app, TWS, and web portal. This is the authoritative source
        for historical P&L and full trade history.
        Source: https://www.ibkrguides.com/orgportal/performanceandstatements/flex.htm

        ## Availability timing (T+1)
        Flex data is generated by IBKR's overnight batch processing. Today's trades are NEVER
        present in Flex on the same calendar day they execute. The Flex file for a given
        trade date becomes available the following calendar day. This T+1 behavior is observed;
        IBKR does not publish a specific daily cutoff time.

        ## For today's trades
        Use get_pa_transactions (Portfolio Analyst back-office data — all origins, faster
        availability than Flex, not session-scoped).
        """
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
        """Import all Flex XML files from Drive account_data/ into the local store."""
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
        """Import trades from a local Flex XML file into the store."""
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
        """Report trade activity date range and total count from the local Flex store.

        Activity report only — does not verify completeness against source XMLs.
        Use verify_flex_import for a true source-vs-SQLite integrity check.
        """
        cov = self._store.get_trade_date_coverage()
        if not cov["oldest"]:
            return "No trade history in store. Run sync_flex_archive or sync_flex_trades first.", None
        return "\n".join(_format_coverage(cov)), None

    def _verify_flex_import(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        """Verify Flex import completeness against source XML archives on Drive.

        For each XML in account_data/:
          - Manual archives (ClaudIA_Full_Activity_*.xml): registered in the manifest
            as pre-validated on first encounter; never re-verified (user confirmed integrity).
          - Auto-synced archives (flex_U*.xml): manifest entry written at sync time with
            SHA-256 and verified_at already set. On re-check: download, compare SHA-256
            to manifest — if hash matches, import is confirmed complete without a full
            tradeID scan. If hash differs (file modified after sync), full cross-check runs.

        Flags within-file duplicate tradeIDs (raw_count != unique_count) — should never
        occur from IBKR but is surfaced transparently if it does.

        Read-only. Never modifies trade data. IBKR XML is the authoritative source.
        Updates verified_at in the manifest after each successful check.
        """
        import hashlib
        from datetime import UTC, datetime
        from ibkr_core_mcp.flex_query import FlexQueryClient

        if self._cache is None:
            return (
                "verify_flex_import requires Google Drive (GOOGLE_DRIVE_FOLDER_ID not set). "
                "Source XML archives are stored in account_data/ on Drive.",
                None,
            )

        xml_files = self._cache.download_account_files(extension=".xml")
        if not xml_files:
            return (
                "No .xml files found in account_data/ on Drive. "
                "Flex XML archives are uploaded automatically after each sync.",
                None,
            )

        db_ids = self._store.get_all_execution_ids()
        now = datetime.now(UTC).isoformat()
        all_xml_ids: set[str] = set()
        file_lines: list[str] = []
        issues: list[str] = []

        for filename, content in xml_files:
            xml_text = content.decode("utf-8")
            sha256 = hashlib.sha256(content).hexdigest()

            # Determine source type from filename convention:
            #   ClaudIA_Full_Activity_*.xml → manual (user-validated historical archive)
            #   flex_U*.xml                 → auto (ClaudIA Flex Web Service sync)
            is_manual = filename.startswith("ClaudIA_Full_Activity_")
            source = "manual" if is_manual else "auto"

            try:
                unique_ids, raw_count = FlexQueryClient.extract_execution_ids(xml_text)
            except Exception as exc:
                file_lines.append(f"  ✗ PARSE ERROR  {filename}: {exc}")
                issues.append(filename)
                continue

            entry = self._store.get_flex_import_entry(filename)

            if is_manual:
                # Manual archives are pre-validated. Register in manifest on first encounter;
                # mark verified_at = imported_at (integrity confirmed by user, not re-checked).
                if entry is None:
                    self._store.log_flex_import(
                        filename=filename,
                        sha256=sha256,
                        trade_id_count=len(unique_ids),
                        raw_trade_count=raw_count,
                        source="manual",
                        imported_at=now,
                        verified_at=now,
                    )
                dupe_note = (
                    f" ⚠ raw={raw_count} unique={len(unique_ids)} (within-file duplicate tradeIDs)"
                    if raw_count != len(unique_ids) else ""
                )
                file_lines.append(
                    f"  ✓ pre-validated  {filename}  ({len(unique_ids)} tradeIDs){dupe_note}"
                )
                all_xml_ids |= unique_ids
                continue

            # Auto-synced file: check hash against manifest.
            if entry is not None and entry["sha256"] == sha256:
                # Hash matches what was recorded at sync time — import is confirmed complete.
                self._store.mark_flex_import_verified(filename, now)
                dupe_note = (
                    f" ⚠ raw={raw_count} unique={len(unique_ids)}"
                    if raw_count != len(unique_ids) else ""
                )
                file_lines.append(
                    f"  ✓ hash verified  {filename}  ({len(unique_ids)} tradeIDs){dupe_note}"
                )
                all_xml_ids |= unique_ids
                continue

            # Hash mismatch or first encounter for an auto file: full cross-check.
            reason = "first check" if entry is None else "hash mismatch — file changed since sync"
            missing = unique_ids - db_ids
            dupe_note = (
                f" ⚠ raw={raw_count} unique={len(unique_ids)}"
                if raw_count != len(unique_ids) else ""
            )
            if missing:
                file_lines.append(
                    f"  ✗ {len(missing)} missing  {filename}  "
                    f"({len(unique_ids)} in XML, {reason}){dupe_note}"
                )
                file_lines.append(
                    f"    Missing tradeIDs (first 5): {sorted(missing)[:5]}"
                )
                issues.append(filename)
            else:
                file_lines.append(
                    f"  ✓ cross-checked  {filename}  "
                    f"({len(unique_ids)} tradeIDs, {reason}){dupe_note}"
                )
                self._store.log_flex_import(
                    filename=filename,
                    sha256=sha256,
                    trade_id_count=len(unique_ids),
                    raw_trade_count=raw_count,
                    source=source,
                    imported_at=entry["imported_at"] if entry else now,
                    verified_at=now,
                )
            all_xml_ids |= unique_ids

        total_missing = all_xml_ids - db_ids
        lines = [
            "Flex Import Integrity Check",
            f"  {len(xml_files)} XML file(s) in Drive account_data/",
            f"  {len(db_ids)} execution_ids in SQLite trades table",
            "",
            *file_lines,
            "",
            "Aggregate (union of all source files):",
            f"  Unique tradeIDs across all XMLs : {len(all_xml_ids)}",
            f"  Present in SQLite               : {len(all_xml_ids & db_ids)}",
            f"  Missing from SQLite             : {len(total_missing)}",
        ]
        if issues:
            lines.append(
                f"  Action: re-import {len(issues)} file(s) using import_flex_file or sync_flex_archive."
            )
        else:
            lines.append("  Result: all source tradeIDs confirmed present in SQLite.")

        return "\n".join(lines), None

    def _get_live_orders(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        """Return working orders (all statuses except Filled/Cancelled/Expired) across all instrument types.

        Origin is determined from orderRef prefix ('CLAUDIA-' = ClaudIA-staged) rather than
        clientId, which is unreliable — both CP API and mobile orders can show clientId=0.
        """
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
        import time
        self._client._get("/iserver/account/orders?force=true")  # instantiate
        time.sleep(1)
        raw = self._client._get("/iserver/account/orders")  # retrieve
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
            f"Endpoint used: /iserver/account/orders\nRaw IBKR orders ({len(orders)} total):\n" + "\n".join(lines)
        ), None

    def _get_ledger(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        """Return per-currency cash ledger: NLV, cash, market values, P&L, interest, dividends.

        IBKR returns the ledger keyed by currency code plus a synthetic 'BASE' aggregate.
        BASE is excluded — per-currency keys are the authoritative values.
        Futures and interest rows are suppressed when zero to keep output clean.
        """
        account_id, err = self._first_account_id()
        if err:
            return err, None
        ledger = self._client.get_account_ledger(account_id)
        if not ledger:
            return "No ledger data returned.", None

        # IBKR ledger is keyed by currency (e.g. {"USD": {...}, "BASE": {...}}).
        # BASE is a synthetic aggregate; prefer currency-specific keys first.
        currencies = [k for k in ledger if k != "BASE"] or list(ledger.keys())
        lines: list[str] = []
        for currency in currencies:
            data = ledger.get(currency, {})
            if not isinstance(data, dict):
                continue

            def _f(key: str) -> float:
                try:
                    return float(data.get(key) or 0)
                except (ValueError, TypeError):
                    return 0.0

            nlv = _f("netliquidationvalue")
            cash = _f("cashbalance")
            stock = _f("stockmarketvalue")
            fut_mv = _f("futuresonlymv")
            unrealized = _f("unrealizedpnl")
            realized = _f("realizedpnl")
            fut_pnl = _f("futuresonlypnl")
            interest = _f("accruals")
            dividends = _f("dividends")

            lines.append(f"Account Ledger ({currency}):")
            lines.append(f"  Net Liquidation Value : {nlv:>14,.2f}")
            lines.append(f"  Cash Balance          : {cash:>14,.2f}")
            lines.append(f"  Stock Market Value    : {stock:>14,.2f}")
            if fut_mv:
                lines.append(f"  Futures Market Value  : {fut_mv:>14,.2f}")
            lines.append(f"  Unrealized P&L        : {unrealized:>+14,.2f}")
            lines.append(f"  Realized P&L          : {realized:>+14,.2f}")
            if fut_pnl:
                lines.append(f"  Futures P&L           : {fut_pnl:>+14,.2f}")
            if interest:
                lines.append(f"  Interest Accrued      : {interest:>+14,.2f}")
            if dividends:
                lines.append(f"  Dividends             : {dividends:>+14,.2f}")

        return "\n".join(lines) if lines else json.dumps(ledger, indent=2), None

    def _get_allocation(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        """Return portfolio allocation breakdown by asset class, sector, and industry."""
        account_id, err = self._first_account_id()
        if err:
            return err, None
        allocation = self._client.get_account_allocation(account_id)
        return json.dumps(allocation, indent=2), None

    def _get_pa_periods(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        """Return valid period strings for Portfolio Analyst queries from IBKR's /pa/allperiods endpoint.

        ## Purpose
        Call this before get_pa_transactions when unsure which period values IBKR accepts.
        Documented period values (verified 2026-06-26): "1D", "7D", "MTD", "1M", "YTD", "1Y".
        Always fetch from this endpoint rather than hardcoding — IBKR may return a subset
        based on account age/type.

        ## Raw response fallback
        When the extraction logic cannot recognize IBKR's response shape, the raw IBKR
        response is returned so the caller can identify the correct key and update
        client.get_pa_periods() accordingly.
        """
        account_ids, err = self._all_account_ids()
        if err:
            return err, None
        # Call the raw endpoint directly so we can show what IBKR actually returned
        # if get_pa_periods() fails to extract the list.
        raw = self._client._post("/pa/allperiods", {"acctIds": account_ids})
        periods = self._client.get_pa_periods(account_ids)
        if periods:
            return "Valid PA periods:\n" + "\n".join(f"  - {p}" for p in periods), None
        return (
            f"get_pa_periods returned no periods. "
            f"Raw IBKR response (use this to identify the correct response key):\n"
            f"{json.dumps(raw, indent=2)}"
        ), None

    def _get_pa_performance(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        """Return Portfolio Analyst performance metrics for the requested period."""
        account_ids, err = self._all_account_ids()
        if err:
            return err, None
        perf = self._client.get_pa_performance(account_ids, inputs["period"])
        return json.dumps(perf, indent=2), None

    def _get_pa_transactions(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        """Transaction history from IBKR Portfolio Analyst — all origins, not session-scoped.

        ## When to use this tool
        This is the correct tool for finding today's trades from any origin (mobile app, TWS,
        CP API, web portal). Unlike get_trades source='live' (CP API session-scoped), PA
        uses IBKR's back-office data which is not tied to the current session.
        Use this when: a trade was placed via mobile or TWS and does not appear in get_trades.

        ## Availability timing
        PA uses IBKR back-office data. Timing relative to same-day execution is not
        stated in the official docs. Observed: same-day fills appear accessible, but this
        has not been confirmed across all trade origins and time zones.

        ## Period values
        Documented values: "1D", "7D", "MTD", "1M", "YTD", "1Y". Must come from
        get_pa_periods — IBKR returns HTTP 400 for invalid period strings, and the
        exact set returned may vary by account age/type.
        On HTTP 400: this handler automatically fetches valid periods and returns them in the
        error so the caller can retry with the correct value.

        ## vs Flex (sync_flex_trades)
        Both cover all origins. Flex is T+1 (yesterday at best) but provides multi-year
        authoritative history. PA is faster (likely same-day) but limited to recent periods.
        """
        from ibkr_core_mcp.exceptions import IBKRAPIError
        account_ids, err = self._all_account_ids()
        if err:
            return err, None
        period = inputs["period"]
        try:
            txns = self._client.get_pa_transactions(account_ids, period)
        except IBKRAPIError as exc:
            if exc.status_code == 400:
                valid = self._client.get_pa_periods(account_ids)
                hint = (
                    f"Valid periods from IBKR: {', '.join(valid)}"
                    if valid else "Could not retrieve valid periods from IBKR."
                )
                return (
                    f"get_pa_transactions failed: IBKR rejected period '{period}' (HTTP 400). "
                    f"{hint}"
                ), None
            raise
        if not txns:
            return f"No transactions found for period '{period}'.", None

        lines = []
        total_amount = 0.0
        for t in txns:
            if not isinstance(t, dict):
                continue
            date = str(t.get("date") or t.get("settleDate") or "?")[:10]
            desc = t.get("desc") or t.get("description") or t.get("type") or "?"
            symbol = t.get("symbol") or t.get("conid") or ""
            amount = t.get("amount") or t.get("netCash") or 0
            try:
                amount = float(amount)
            except (ValueError, TypeError):
                amount = 0.0
            total_amount += amount
            symbol_part = f" [{symbol}]" if symbol else ""
            lines.append(f"- {date}{symbol_part} {desc}: {amount:+.2f}")

        return (
            f"PA Transactions — {inputs['period']} ({len(lines)} records, all origins):\n"
            + "\n".join(lines[:50])
            + (f"\n  (showing first 50 of {len(lines)})" if len(lines) > 50 else "")
            + f"\nNet total: {total_amount:+.2f}"
        ), None

    def _get_contract_info(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        """Return full contract details and trading rules for any instrument type."""
        symbol = inputs["symbol"].upper()
        sec_type = inputs.get("sec_type", "STK")
        conid, err = self._resolve_conid(symbol, sec_type)
        if err:
            return err, None
        info = self._client.get_contract_info_and_rules(conid)
        return json.dumps(info, indent=2), None

    def _get_option_chain(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        """Return the option chain (strikes, expirations) for the given underlying symbol."""
        symbol = inputs["symbol"].upper()
        exchange = inputs.get("exchange", "SMART")
        chain = self._client.get_option_chain(symbol, exchange=exchange)
        return json.dumps(chain, indent=2), None

    def _run_scanner(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        """Run an IBKR market scanner for any instrument type (STK, FUT, ETF, etc.)."""
        instrument = inputs.get("instrument", "STK")
        params = {
            "instrument": instrument,
            "location": inputs.get("location_code", "STK.US.MAJOR"),
            "scanCode": inputs["scan_code"],
            "secType": instrument,  # pass through — not hardcoded to STK
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
        """Return FYI notifications and unread count from the IBKR notification centre."""
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
        """Compute RSI, MACD, Bollinger Bands, ATR, VWAP, Stochastic, and Williams %R from cached bars."""
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
        """Execute a vectorised backtest strategy on cached OHLCV bars and return performance metrics."""
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
        """Generate a PineScript v5 indicator script for the requested symbol and indicators."""
        symbol = inputs["symbol"].upper()
        indicators_list = inputs.get("indicators", ["rsi", "macd"])
        strategy_name = inputs.get("strategy_name", f"{symbol} Indicators")
        script = _pinescript.indicator_script(strategy_name, indicators_list, {})
        return script, None

    def _preview_order(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        """Return a whatif order preview (commission, margin impact) without submitting.

        sec_type is passed through to contract resolution — defaults to STK but must
        be set to 'FUT', 'OPT', etc. for non-equity instruments.
        """
        symbol = inputs["symbol"].upper()
        action = inputs["action"].upper()
        quantity = int(inputs["quantity"])
        order_type = inputs.get("order_type", "MKT").upper()
        limit_price = inputs.get("limit_price")
        sec_type = inputs.get("sec_type", "STK")

        conid, err = self._resolve_conid(symbol, sec_type)
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
        """Return real-time unrealized and daily P&L broken down by position across all instrument types."""
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
        """Return return, CAGR, Sharpe, Sortino, Calmar, and drawdown stats from cached bars."""
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
        """Search for contracts by symbol and security type; returns conid and exchange info."""
        symbol = inputs["symbol"].upper()
        sec_type = inputs.get("sec_type", "STK")
        contracts = self._client.search_contract(symbol, sec_type)
        if not contracts:
            return f"No contracts found for {symbol} ({sec_type}).", None
        return json.dumps(contracts, indent=2), None

    def _get_futures(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        """Return available futures contracts and expiration dates for the given root symbols."""
        symbols = [s.upper() for s in inputs["symbols"]]
        futures = self._client.get_futures(symbols)
        if not futures:
            return f"No futures found for {', '.join(symbols)}.", None
        return json.dumps(futures, indent=2), None

    def _get_market_snapshot(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        """Return live market data snapshot (bid, ask, last, volume) for one or more symbols.

        sec_type defaults to STK but must be passed as 'FUT', 'OPT', etc. for
        non-equity instruments to resolve the correct conid.
        """
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

        import time
        snapshot = self._client.get_market_snapshot(conids)
        # First call initializes the iServer subscription but returns no price fields.
        # If no price data came back, wait 1s and retry once — same warmup pattern as
        # /iserver/account/orders (two-call). Fields 31=last, 84=bid, 86=ask.
        _has_prices = lambda s: any(item.get("31") or item.get("84") or item.get("86") for item in s)
        if snapshot and not _has_prices(snapshot):
            time.sleep(1)
            snapshot = self._client.get_market_snapshot(conids)

        if not snapshot:
            return "No market snapshot data returned.", None
        result = json.dumps(snapshot, indent=2)
        if failed:
            result = f"Note: could not resolve {', '.join(failed)} as {sec_type} — omitted.\n\n" + result
        return result, None

    def _get_trading_schedule(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        """Return the trading schedule (hours, holidays) for a symbol on its exchange."""
        symbol = inputs["symbol"].upper()
        asset_class = inputs.get("asset_class", "STK")
        exchange = inputs.get("exchange", "SMART")
        schedule = self._client.get_trading_schedule(asset_class, symbol, exchange)
        return json.dumps(schedule, indent=2), None

    def _get_alerts(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        """List all price alerts configured on the IBKR server for this account."""
        account_id, err = self._first_account_id()
        if err:
            return err, None
        alerts = self._client.get_alerts(account_id)
        if not alerts:
            return "No price alerts configured.", None
        return json.dumps(alerts, indent=2), None

    def _create_price_alert(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        """Create an IBKR server-side price alert that fires via the mobile app regardless of session state."""
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
        """Update price, operator, name, or TIF on an existing alert (patch — unset fields unchanged)."""
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
        """Permanently delete a price alert by ID."""
        account_id, err = self._first_account_id()
        if err:
            return err, None
        result = self._client.delete_alert(account_id, inputs["alert_id"])
        return json.dumps(result, indent=2), None

    def _activate_alert(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        """Toggle an alert on or off without deleting it."""
        account_id, err = self._first_account_id()
        if err:
            return err, None
        activate = inputs.get("activate", True)
        result = self._client.activate_alert(account_id, inputs["alert_id"], activate)
        return json.dumps(result, indent=2), None

    def _get_watchlists(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        """Return all watchlists and their constituent symbols from the IBKR account.

        IMPORTANT: Watchlists in TradingView are NOT the same as IBKR watchlists.
        This endpoint returns only watchlists created inside IBKR (TWS, mobile app,
        or Client Portal). TradingView has its own separate watchlist storage.
        """
        watchlists = self._client.get_watchlists()
        if not watchlists:
            return "No watchlists found in IBKR account.", None
        # Emit raw IBKR response first so the structure is transparent, then a
        # plain-text summary. This prevents misreading ambiguous field names.
        lines = [f"IBKR watchlists ({len(watchlists)} found) — raw response below:\n"]
        for wl in watchlists:
            wl_id = wl.get("id") or wl.get("watchlistId") or "?"
            wl_name = wl.get("name") or wl.get("watchlistName") or "?"
            rows = wl.get("rows") or wl.get("instruments") or wl.get("symbols") or []
            symbols = [
                r.get("ST") or r.get("symbol") or r.get("conid") or str(r)
                for r in rows if isinstance(r, dict)
            ] if rows else []
            lines.append(f"  [{wl_id}] {wl_name}: {', '.join(str(s) for s in symbols) or '(no symbols)'}")
        lines.append("\nRaw IBKR response:")
        lines.append(json.dumps(watchlists, indent=2))
        return "\n".join(lines), None

    def _get_order_status(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        """Return current status and fill details for a specific order ID."""
        order_id = inputs["order_id"]
        status = self._client.get_order_status(order_id)
        return json.dumps(status, indent=2), None

    def _delete_cache(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        """Remove a specific dataset from the Drive market-data cache."""
        symbol = inputs["symbol"].upper()
        timeframe = inputs["timeframe"]
        period = inputs["period"]
        end = inputs["end"]
        if not self._cache.check(symbol, timeframe, period, end):
            return f"No cached entry for {symbol} {timeframe} ({period}, end={end}).", None
        self._cache.delete(symbol, timeframe, period, end)
        return f"Deleted cache entry for {symbol} {timeframe} ({period}, end={end}).", None

    def _handle_firecrawl_search(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        """
        Handle the firecrawl_search tool.

        Lazily initializes FirecrawlClient on first call. Returns a no-key message
        if FIRECRAWL_API_KEY is not configured. Optionally saves a Drive snapshot.
        """
        from ibkr_core_mcp.web_scraper import FirecrawlClient, WebDocsStore, FirecrawlError

        if not self._config.firecrawl_api_key:
            return (
                "firecrawl_search is not available: FIRECRAWL_API_KEY is not configured. "
                "Set it in .env to enable web search.",
                None,
            )
        if self._firecrawl is None:
            self._firecrawl = FirecrawlClient(self._config.firecrawl_api_key)

        query = inputs.get("query", "").strip()
        limit = int(inputs.get("limit", 5))
        save_to_drive = bool(inputs.get("save_to_drive", False))

        if not query:
            return "query must be non-empty.", None

        try:
            results = self._firecrawl.search(query, limit=limit)
        except FirecrawlError as exc:
            return f"Firecrawl search failed (HTTP {exc.status_code}): {exc}", None

        if not results:
            return f"No results found for: {query}", None

        lines = [f"## Search results for: {query}\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"### {i}. {r.get('title', '(no title)')}")
            lines.append(f"**URL:** {r.get('url', '')}\n")
            md = r.get("markdown", "")
            if md:
                lines.append(md[:2000])  # truncate very long pages
            lines.append("")

        drive_note = ""
        if save_to_drive:
            if self._web_docs is None:
                self._web_docs = WebDocsStore(self._config)
            try:
                file_id = self._web_docs.save_search(query, results)
                drive_note = f"\n\n*Snapshot saved to Drive (file ID: {file_id})*"
            except Exception as exc:
                log.warning("firecrawl_search: Drive save failed: %s", exc)
                drive_note = "\n\n*Note: Drive snapshot failed — results shown above.*"

        return "\n".join(lines) + drive_note, None

    def _handle_firecrawl_crawl(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        """
        Handle the firecrawl_crawl tool.

        Validates the URL with an SSRF guard before passing to Firecrawl. Lazily
        initializes FirecrawlClient and WebDocsStore on first call. Always saves
        results to Drive (crawl is a bulk operation — Drive storage is the point).
        """
        import ipaddress
        import urllib.parse
        from ibkr_core_mcp.web_scraper import FirecrawlClient, WebDocsStore, FirecrawlError

        if not self._config.firecrawl_api_key:
            return (
                "firecrawl_crawl is not available: FIRECRAWL_API_KEY is not configured. "
                "Set it in .env to enable web crawling.",
                None,
            )

        url = inputs.get("url", "").strip()
        if not url:
            return "url must be non-empty.", None

        # SSRF guard
        try:
            parsed = urllib.parse.urlparse(url)
            if parsed.scheme not in ("http", "https"):
                return f"Blocked: only http/https URLs are supported (got {parsed.scheme!r}).", None
            host = (parsed.hostname or "").lower()
            if not host:
                return "Blocked: URL has no hostname.", None
            if host in ("localhost", "0.0.0.0") or host.startswith("127.") or host.startswith("169.254."):
                return "Blocked: cannot fetch from localhost or link-local addresses.", None
            try:
                addr = ipaddress.ip_address(host)
                if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
                    return "Blocked: cannot fetch from private or reserved IP addresses.", None
            except ValueError:
                pass  # hostname — allow DNS resolution
        except Exception as exc:
            return f"Invalid URL: {exc}", None

        max_pages = int(inputs.get("max_pages", 50))
        timeout_s = int(inputs.get("timeout_s", 120))

        if self._firecrawl is None:
            self._firecrawl = FirecrawlClient(self._config.firecrawl_api_key)
        if self._web_docs is None:
            self._web_docs = WebDocsStore(self._config)

        try:
            pages = self._firecrawl.crawl(url, max_pages=max_pages, timeout_s=timeout_s)
        except FirecrawlError as exc:
            return f"Firecrawl crawl failed (HTTP {exc.status_code}): {exc}", None

        try:
            manifest = self._web_docs.save_crawl(url, pages)
        except Exception as exc:
            return f"Crawl completed ({len(pages)} pages) but Drive save failed: {exc}", None

        saved = len(manifest["pages"])
        return (
            f"Crawl complete: saved {saved} page(s) from {url} to Drive.\n"
            f"Crawled at: {manifest['crawled_at']}\n"
            f"Pages: " + ", ".join(p['url'] for p in manifest['pages'][:10])
            + ("..." if saved > 10 else ""),
            None,
        )
