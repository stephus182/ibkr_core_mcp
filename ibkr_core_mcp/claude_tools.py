"""ClaudeToolkit — the Anthropic tool layer over the rest of the package (43 tools).

`TOOL_DEFINITIONS` holds the JSON schemas Claude sees; `ClaudeToolkit` holds the
matching handlers and `execute()` dispatches between them. The pair is deliberately
portable: `mcp_server.py` reuses both to expose the same capabilities over MCP
(adding two alert tools, for 45), so a tool added here is available to both hosts.

`execute()` returns `tuple[str, None]`. The second slot once carried a figure and
was tightened when `plotly` was removed — this package returns data, never figures;
rendering belongs to the consuming UI. See `docs/python-package-landscape.md`.

This is also the only layer meant to talk to the Anthropic API from a host app, so
that a host's token accounting sees every call. The single sanctioned exception is
`scrape_fallback.judge_completeness_llm`.

Adding a tool: see the checklist in `CLAUDE.md`. Use `_first_account_id()` /
`_all_account_ids()` rather than inlining `get_accounts()` — they centralise the
`"accountId"` / `"id"` key fallback.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from typing import Any, NamedTuple
from zoneinfo import ZoneInfo

import pandas as pd

from ibkr_core_mcp import analytics as _analytics
from ibkr_core_mcp import indicators as _indicators
from ibkr_core_mcp import pinescript as _pinescript
from ibkr_core_mcp.backtest import BacktestResult
from ibkr_core_mcp.backtest import run_backtest as _run_backtest
from ibkr_core_mcp.cache import GDriveCache
from ibkr_core_mcp.client import _ACCOUNT_ID_RE, IBKRClient
from ibkr_core_mcp.config import Config
from ibkr_core_mcp.exceptions import BacktestError, IBKRCoreError
from ibkr_core_mcp.models import bars_to_dataframe as _bars_to_dataframe
from ibkr_core_mcp.store import SQLiteStore

log = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")


class _Resolved(NamedTuple):
    """The outcome of resolving one symbol to one tradeable listing.

    A NamedTuple rather than the previous `(conid, error)` pair specifically so that
    `currency` cannot be dropped on the way to the user. Every caller now has it in hand
    at the moment it has the conid, which is what makes "always state the currency" a
    property of the code instead of a rule each handler has to remember.

    `currency` is None only when `/iserver/secdef/info` could not be read; that means
    *unknown*, and callers must say so rather than omit the unit. It is also None
    whenever `error` is set, since nothing was resolved.
    """

    conid: int
    currency: str | None
    error: str | None
    # True only when `error` is a QUESTION about which listing was meant, as opposed to
    # a plain failure. The two must not be conflated: a question is the answer and has
    # to reach the user verbatim, while a failure is a diagnostic that can be summarised
    # alongside other symbols'.
    ambiguous: bool = False


# Bounds worst-case simultaneous Crawl4AI browser launches in the search-result
# fallback loop. FirecrawlClient.search()'s own `limit` is already clamped to
# [1, 10] (see web_scraper.py), so this caps concurrent launches to half that.
_MAX_CONCURRENT_FALLBACKS = 5

# Maps first character of IBKR field 6509 (Market Data Availability) to human-readable status.
# Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#md-availability
_MD_AVAILABILITY: dict[str, str] = {
    "R": "Live (Real-Time)",
    "D": "Delayed (15–20 min)",
    "Z": "Frozen (last close, real-time)",
    "Y": "Frozen Delayed (last close, delayed)",
    # N = no data at all — neither real-time nor delayed. Per IBKR docs:
    # "User does not have the required market data subscription(s) to relay back
    #  either real time or delayed data."
    # Possible causes: exchange-specific subscription missing (NYSE and NYSE Arca
    # are separate from NASDAQ even within a US equities bundle), wrong conid resolved,
    # or the conid's primary exchange differs from the subscribed venue.
    "N": "Not Subscribed (no data — neither live nor delayed)",
    # O = Market Data API Agreement not completed (annual IBKR requirement).
    # Would affect all symbols, not just specific ones.
    "O": "Not Available (Market Data API Agreement not completed — see Account Management)",
}


def _TODAY() -> str:
    return str(date.today())


def _dupe_note(raw_count: int, unique_count: int, verbose: bool = False) -> str:
    """Format the within-file duplicate-tradeID warning shared by _verify_flex_import's
    three status branches (pre-validated / hash-verified / cross-checked).

    Returns "" when raw_count == unique_count (no duplicates). `verbose` appends
    "(within-file duplicate tradeIDs)" for the pre-validated branch, matching its
    original wording; the other two branches use the terser form.
    """
    if raw_count == unique_count:
        return ""
    suffix = " (within-file duplicate tradeIDs)" if verbose else ""
    return f" ⚠ raw={raw_count} unique={unique_count}{suffix}"


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
            lines.append(f"  {g['gap_start']} → {g['gap_end']} ({g['calendar_days']} calendar days with no trades)")
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
                "period": {"type": "string", "description": "History period, lowercase units, e.g. '6m', '1y', '30d'"},
                "bar": {"type": "string", "description": "Bar size, e.g. '1d', '1h'", "default": "1d"},
                "end": {"type": "string", "description": "End date YYYY-MM-DD, defaults to today"},
            },
            "required": ["symbol", "period"],
        },
    },
    {
        "name": "check_cache",
        "description": (
            "Check whether data for a symbol/timeframe/period/end combination is "
            "already cached in Google Drive. Diagnostic only — fetch_market_data "
            "checks the cache automatically, so you don't need to call this first."
        ),
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
        "description": (
            "Retrieve account net liquidation value, cash balance, gross position "
            "value, and buying power from IBKR — a single aggregate snapshot for "
            "the account. This endpoint does not carry P&L fields — for realized/"
            "unrealized P&L use get_ledger (per-currency) or get_pnl (per account "
            "partition, no realized figure); for per-position detail use get_positions."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_positions",
        "description": (
            "Get all open positions for the IBKR account — symbol, quantity, "
            "market value, and unrealized P&L per position. For account-wide "
            "daily/unrealized P&L (not per-position) use get_pnl; for account "
            "totals (net liq, cash, buying power) use get_account_summary."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_trades",
        "description": (
            "Get trade history. source='live' queries IBKR directly (last 7 days max — current day "
            "plus 6 previous). source='store' queries the local SQLite store — unlimited history, "
            "includes all data synced via sync_flex_trades. Use source='store' for any analysis beyond 7 days."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Filter by symbol (optional)"},
                "source": {
                    "type": "string",
                    "description": "'live' (IBKR API, last 7 days max) or 'store' (SQLite, unlimited history including Flex syncs)",
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
                "account_id": {
                    "type": "string",
                    "description": "IBKR account ID (optional — resolved automatically if omitted)",
                },
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
        "description": (
            "Get cash balance and ledger information broken out per currency for "
            "the IBKR account — differs from get_account_summary's single "
            "aggregate figure."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_allocation",
        "description": (
            "Get portfolio allocation breakdown by asset class, industry, and "
            "category (aggregated percentages, not per-position detail — for "
            "individual holdings use get_positions)."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_pa_periods",
        "description": "Get the list of valid period strings for get_pa_performance queries. Call this first if unsure which period to use.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_pa_performance",
        "description": (
            "Get portfolio NAV performance from IBKR Portfolio Analyst. Use "
            "get_pa_periods first to discover valid period strings. Returns your "
            "actual account's NAV performance — not a price-return backtest; for "
            "those use get_analytics or run_backtest."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "description": "Valid period string from get_pa_periods, e.g. '1D', '7D', 'MTD', '1M', 'YTD', '1Y'",
                },
            },
            "required": ["period"],
        },
    },
    {
        "name": "get_pa_transactions",
        "description": (
            "Get transaction history from IBKR Portfolio Analyst for one symbol "
            "(all origins: mobile, TWS, API — not session-scoped). IBKR only "
            "supports one instrument per call."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Ticker symbol to fetch transactions for"},
                "sec_type": {
                    "type": "string",
                    "description": "Security type for conid resolution: 'STK' (default), 'IND', 'BOND', 'FUT', or 'CASH'",
                },
                "currency": {"type": "string", "description": "Currency code for the request (default 'USD')"},
                "days": {
                    "type": "integer",
                    "description": "Optional lookback window in days; omit for IBKR's default range",
                },
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "get_contract_info",
        "description": (
            "Get full contract details for a symbol (conid, exchange, currency, "
            "trading hours, etc.) — resolves the conid internally, so you don't "
            "need search_contract first. Supports STK, IND, BOND, and FUT "
            "(front-month); does not support CASH (FX) or OPT."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Ticker symbol"},
                "sec_type": {
                    "type": "string",
                    "description": "Security type: STK, IND, BOND, or FUT (default STK)",
                    "default": "STK",
                },
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "get_option_chain",
        "description": (
            "Get the option chain for an underlying symbol: all available expiry months "
            "plus call and put strike prices for one month (default: nearest expiry). "
            "Uses IBKR's documented secdef/search → secdef/strikes flow. Returns strikes "
            "only — not per-contract conids or greeks."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Underlying ticker, e.g. AAPL"},
                "month": {
                    "type": "string",
                    "description": "Expiry month as 3-letter month + 2-digit year, e.g. 'JAN26' (default: nearest expiry; the response's 'months' field lists all)",
                },
                "exchange": {"type": "string", "default": "SMART"},
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "run_scanner",
        "description": (
            "Run an IBKR market scanner to find instruments matching criteria "
            "(stocks by default; set instrument + location_code together for "
            "other types, e.g. FUT). "
            "Common scan_code values: 'TOP_PERC_GAIN', 'TOP_PERC_LOSE', 'MOST_ACTIVE', "
            "'HIGH_VS_13W_HL', 'LOW_VS_13W_HL', 'NEAR_52W_HL'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "scan_code": {"type": "string", "description": "Scanner type, e.g. 'TOP_PERC_GAIN'"},
                "instrument": {"type": "string", "description": "e.g. 'STK', 'FUT'", "default": "STK"},
                "location_code": {
                    "type": "string",
                    "description": (
                        "Defaults to 'STK.US.MAJOR' — override this when instrument "
                        "isn't STK, or it silently scans US equities regardless of "
                        "the instrument setting (e.g. use 'FUT.US' for US futures)."
                    ),
                    "default": "STK.US.MAJOR",
                },
                "max_results": {"type": "integer", "default": 25},
            },
            "required": ["scan_code"],
        },
    },
    {
        "name": "get_notifications",
        "description": (
            "Retrieve IBKR system notifications (FYI messages — e.g. dividend, "
            "margin, or account notices) and their unread count. Not the same as "
            "price alerts — use get_alerts for those."
        ),
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
            "(RSI, MACD, Bollinger Bands, ATR, VWAP, Stochastic, Williams %R, and Volume Ratio). "
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
            "Generate a PineScript v5 script for TradingView. source='indicators' (default) "
            "emits an indicator study from a list of indicators; source='backtest' emits a "
            "strategy() script from the most recent stored run_backtest result for the symbol "
            "(real metrics in the header — always use this after run_backtest instead of "
            "writing PineScript by hand). Output pastes directly into the Pine Editor."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Ticker symbol"},
                "source": {
                    "type": "string",
                    "description": "'indicators' (indicator study) or 'backtest' (strategy script from the latest stored run_backtest result)",
                    "default": "indicators",
                },
                "indicators": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "For source='indicators': list of indicators: 'rsi', 'macd', 'bollinger_bands', 'ema', 'sma', 'atr'",
                },
                "strategy_name": {
                    "type": "string",
                    "description": "Script name; for source='backtest' also filters which stored run to use (default: most recent for the symbol)",
                    "default": "",
                },
                "timeframe": {
                    "type": "string",
                    "description": "For source='backtest': cache timeframe of the backtested bars (for chart-timeframe inference; optional)",
                },
                "period": {"type": "string", "description": "For source='backtest': cache period key (optional)"},
                "end": {"type": "string", "description": "For source='backtest': cache end-date key (optional)"},
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "get_analytics",
        "description": (
            "Compute full portfolio/strategy analytics on cached OHLCV data: "
            "Sharpe ratio, Sortino ratio, Calmar ratio, CAGR, max drawdown, and drawdown duration. "
            "Annualized metrics scale automatically with the bar timeframe (IBKR bar notation, "
            "e.g. '5min'/'1h'/'1d'; intraday assumes the US equity 6.5h session). "
            "NOTE: computed from cached price history (close-to-close returns) for one "
            "symbol — not your actual account trades or P&L. For real account "
            "performance use get_pa_performance; for a rule-based trading strategy's "
            "backtested metrics use run_backtest."
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
                    "description": "'MKT', 'LMT', 'STP' (stop-market), 'STOP_LIMIT', or 'MIDPRICE'. Trailing types (TRAIL/TRAILLMT) are not supported by this tool.",
                    "default": "MKT",
                },
                "limit_price": {
                    "type": "number",
                    "description": "Limit price (required for order_type='LMT' and 'STOP_LIMIT'; optional price cap for 'MIDPRICE')",
                },
                "stop_price": {
                    "type": "number",
                    "description": "Stop trigger price (required for order_type='STP' and 'STOP_LIMIT')",
                },
                "sec_type": {
                    "type": "string",
                    "description": "Security type of the symbol: STK (default), IND, BOND, FUT (resolves front month), or CASH (FX pair like 'EUR.USD')",
                    "default": "STK",
                },
            },
            "required": ["symbol", "action", "quantity"],
        },
    },
    {
        "name": "get_pnl",
        "description": (
            "Get real-time daily and unrealized P&L for the IBKR account, one summary "
            "row per account/model partition — NOT broken down by position or symbol "
            "(IBKR's endpoint doesn't offer that). For per-position P&L use "
            "get_positions; for account totals (net liq, cash, buying power) use "
            "get_account_summary."
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
                    "description": "Security type: STK, IND, or BOND (default: STK) — the only values /iserver/secdef/search supports. For futures use get_futures; for FX use get_market_snapshot; for option strikes use get_option_chain.",
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
            "Get market data snapshot for one or more symbols: last price, bid, ask, "
            "high, low, change, change%, and volume. Each quote includes _data_status "
            "('Live (Real-Time)' when subscribed, 'Delayed (15–20 min)' when not), "
            "_quote_time (timestamp in ET), and _currency (the ISO code this listing "
            "trades in, or 'UNKNOWN'). Always report all three to the user.\n\n"
            "Name the currency by its ISO code — 'USD 91.42' or '$91.42 USD' — never a "
            "bare '$91.42'. '$' is not a currency: USD, MXN, CAD, AUD, HKD and SGD all "
            "write prices with it, so a bare symbol is ambiguous rather than merely terse. "
            "This applies to USD exactly as much as to any other currency, and most of all "
            "there: the same ticker trades in different currencies on different venues "
            "(IGV is USD on BATS but MXN on MEXI), and a peso price reads as a perfectly "
            "plausible dollar one.\n\n"
            "Resolution by sec_type:\n"
            "- STK (default): equities and ETFs. For international listings, pass exchange "
            "  to select the right venue (e.g. exchange='AMS' for ASML on Euronext Amsterdam, "
            "  exchange='ETR' for SAP on Xetra, exchange='TSE' for Toyota on Tokyo SE, "
            "  exchange='HKEX' for HSBC on HK). Without exchange the US listing is selected. "
            "  When there is no US listing, or the requested exchange has none, the tool "
            "  returns the candidate listings with their company names and asks which is "
            "  meant. Put that question to the user; do NOT answer it yourself by re-calling "
            "  with an exchange of your own choosing. Listings under one ticker can be "
            "  different companies (IGV is the iShares ETF on BATS and I Grandi Viaggi SpA "
            "  on BVME), so choosing for the user can price the wrong issuer.\n"
            "- IND: indices (SPX, NDX, DAX, FTSE, N225). Use exchange for non-US indices.\n"
            "- FUT: futures by root symbol. Front-month contract is selected automatically "
            "  from /trsrv/futures (e.g. ES, NQ, CL, GC, ZC, ZN, 6E). Do NOT pass expiry "
            "  in the symbol — use root symbol only.\n"
            "- CASH: FX spot pairs. Pass the pair as 'EUR.USD', 'USD.JPY', 'GBP.USD', etc. "
            "  (base.quote format). IBKR routes FX via IDEALPRO.\n"
            "- BOND: bonds via IBKR bond search. Specify CUSIP or issuer symbol.\n"
            "- OPT: options require a prior search_contract + secdef/info flow to resolve "
            "  the option conid. Call search_contract first, then get_market_snapshot with "
            "  the resolved conid directly (not ticker)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbols": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Ticker symbols. For FX: 'EUR.USD' format. "
                        "For FUT: root symbol only ('ES', not 'ESH25'). "
                        "For international STK: ticker as listed on the exchange."
                    ),
                },
                "sec_type": {
                    "type": "string",
                    "description": "Security type: STK (default), IND, FUT, CASH, BOND",
                },
                "exchange": {
                    "type": "string",
                    "description": (
                        "Optional. Filter to a specific exchange listing for STK/IND. "
                        "IBKR exchange codes: AMS (Euronext Amsterdam), ETR (Xetra), "
                        "LSE (London), TSE (Tokyo), HKEX (Hong Kong), ASX (Sydney), "
                        "TSX (Toronto), BVSP (Brazil), NSE (India). "
                        "Omit for US equities (SMART routing used)."
                    ),
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
                "symbol": {"type": "string", "description": "Ticker symbol, e.g. AAPL, CL, or 'EUR.USD' for CASH"},
                "sec_type": {
                    "type": "string",
                    "description": (
                        "Security type: STK, IND, or BOND (default: STK) — resolved via "
                        "contract search; FUT — resolved to the front-month contract; "
                        "CASH — FX pair, symbol must be 'BASE.QUOTE' e.g. 'EUR.USD'. "
                        "OPT is not supported (options need a strike/expiry, not just a symbol)."
                    ),
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
                "wait_for_ms": {
                    "type": "integer",
                    "description": (
                        "Advanced: milliseconds to wait for JavaScript rendering before "
                        "extracting. Try 3000 on a site whose content arrives via JavaScript "
                        "and came back empty. Omitted from the request when unset."
                    ),
                },
                "proxy": {
                    "type": "string",
                    "enum": ["basic", "enhanced", "auto"],
                    "description": (
                        "Advanced: Firecrawl proxy mode. 'basic' costs 1 credit, 'enhanced' "
                        "up to 5, 'auto' retries with enhanced only if basic fails. Try 'auto' "
                        "on a site that blocks automated clients. Omitted when unset."
                    ),
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
                    "description": (
                        "Max seconds to wait for the crawl. Default scales with max_pages "
                        "(6s per page, clamped to 120-600s). Only one Firecrawl attempt is "
                        "made, so this is the whole budget."
                    ),
                },
                "force_refresh": {
                    "type": "boolean",
                    "description": (
                        "Re-crawl even if a Drive manifest for this URL already exists and "
                        "is fresh (default false — reuses the cached manifest and makes zero "
                        "Firecrawl requests if one is less than 48h old)"
                    ),
                    "default": False,
                },
                "wait_for_ms": {
                    "type": "integer",
                    "description": (
                        "Advanced: milliseconds to wait for JavaScript rendering before "
                        "extracting. Try 3000 on a site whose content arrives via JavaScript "
                        "and came back empty. Omitted from the request when unset."
                    ),
                },
                "proxy": {
                    "type": "string",
                    "enum": ["basic", "enhanced", "auto"],
                    "description": (
                        "Advanced: Firecrawl proxy mode. 'basic' costs 1 credit, 'enhanced' "
                        "up to 5, 'auto' retries with enhanced only if basic fails. Try 'auto' "
                        "on a site that blocks automated clients. Omitted when unset."
                    ),
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "fetch_page",
        "description": (
            "Fetch ONE web page with a real browser and return it as markdown. "
            "Use for JavaScript-heavy sites that come back empty or truncated, and for "
            "paywalled sites with a saved login profile (FT, WSJ, Bloomberg) — those "
            "return the full article instead of the subscription stub. "
            "For API or reference documentation prefer firecrawl_search / firecrawl_crawl: "
            "they are cheaper, cover many pages, and cache to Drive. "
            "Needs the local browser (the [scraper] extra); reports that if it is missing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Page URL to fetch (public http/https only)",
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
        HumanAuthError,
        IBKRAPIError,
        IBKRAuthError,
        IBKRRateLimitError,
        StoreError,
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
        return f"Tool '{tool}' failed: Flex Web Service error. Check IBKR_FLEX_TOKEN and IBKR_FLEX_QUERY_ID, or retry — transient generation failures resolve automatically."
    if isinstance(exc, ConfigError):
        return f"Tool '{tool}' failed: configuration error. Check .env settings."
    if isinstance(exc, StoreError):
        return f"Tool '{tool}' failed: local store error. Check SQLite path and permissions."
    if isinstance(exc, HumanAuthError):
        return f"Tool '{tool}' failed: human authentication required (Touch ID or dialog cancelled)."
    if isinstance(exc, KeyError):
        return f"Tool '{tool}' failed: missing required input field."
    return f"Tool '{tool}' encountered an unexpected error."


def _validate_account_id(account_id: str) -> str:
    """Raise ValueError if account_id is not a valid IBKR account ID format."""
    if not _ACCOUNT_ID_RE.match(account_id):
        raise ValueError(f"Invalid account ID format: {account_id!r}")
    return account_id


def _money(v: float) -> str:
    """'$' + comma-grouped magnitude, sign only shown when negative (e.g. -$8,107.13)."""
    sign = "-" if v < 0 else ""
    return f"{sign}${abs(v):,.2f}"


def _money_signed(v: float) -> str:
    """Like _money but always shows an explicit +/- sign — for P&L figures,
    where the sign is the point (e.g. +$461.56, -$8,107.13)."""
    sign = "+" if v >= 0 else "-"
    return f"{sign}${abs(v):,.2f}"


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

        parsed.append(
            {
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
            }
        )
    return parsed, skipped


class ClaudeToolkit:
    """Ready-made Anthropic tool-use layer for IBKR research. Portable across any Claude-powered app.

    Exposes TOOL_DEFINITIONS (list of Anthropic tool dicts) and execute() to handle tool calls.
    Wire it into any Anthropic SDK messages call:
        response = client.messages.create(model=..., tools=toolkit.tools, ...)
        result, fig = toolkit.execute(tool_name, tool_input)

    Tool routing: IBKR tools → IBKRClient; local tools (search_past_conversations, fetch_web_page)
    → handled in claudia_ui/agent.py; TradingView tools → TradingViewBridge sidecar.

    Source (Anthropic tool use): https://platform.claude.com/docs/en/docs/build-with-claude/tool-use
    Source (Anthropic Messages API): https://platform.claude.com/docs/en/api/messages
    """

    def __init__(
        self,
        client: IBKRClient,
        cache: GDriveCache,
        store: SQLiteStore,
        config: Config,
    ) -> None:
        """Wire the toolkit to its four collaborators.

        Args:
            client: IBKR Client Portal client. Order writes stay gated inside it.
            cache: Drive parquet cache, consulted before any market-data fetch.
            store: SQLite store for trades, signals, and backtest results.
            config: Environment-derived configuration. Optional integrations
                (Firecrawl, Crawl4AI) report "not configured" at call time when
                their variables are absent, rather than failing construction.
        """
        self._client = client
        self._cache = cache
        self._store = store
        self._config = config
        self._firecrawl: Any = None
        self._web_docs: Any = None
        # Lazy singletons, unguarded by a lock — safe under mcp_server.py's
        # single-event-loop stdio/SSE dispatch (calls are processed one at a time),
        # but not safe if ClaudeToolkit is ever driven by a genuinely multi-threaded
        # host app. Add a lock if that becomes a real usage pattern.
        self._crawl4ai: Any = None

    @property
    def client(self) -> IBKRClient:
        """The underlying IBKR client, for callers needing an ungated read."""
        return self._client

    @property
    def tools(self) -> list[dict[str, Any]]:
        """The tool schemas to hand to Claude, in `TOOL_DEFINITIONS` order."""
        return TOOL_DEFINITIONS

    def execute(self, name: str, inputs: dict[str, Any]) -> tuple[str, None]:
        """Execute a tool call by name. Returns (text_result, None).

        The second element is always None. It once carried a plotly figure; that
        dependency was removed as unused and the return type narrowed to match.
        This package returns data, and the consuming UI renders it — see
        `docs/python-package-landscape.md`.
        """
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
            "fetch_page": self._handle_fetch_page,
        }
        handler = handlers.get(name)
        if not handler:
            return f"Unknown tool: {name}", None
        try:
            return handler(inputs)
        except Exception as e:
            return _safe_error(name, e), None

    # ── Private helpers ───────────────────────────────────────────────────────

    def _get_accounts(self) -> tuple[list[dict[str, Any]], str | None]:
        """Fetch all IBKR accounts. Returns (accounts, None) or ([], error_message).

        Single source of truth for the accounts call — callers should use
        _first_account_id / _all_account_ids rather than calling this directly,
        so the empty-accounts error string stays consistent everywhere.
        """
        accounts = self._client.get_accounts()
        if not accounts:
            return [], "No accounts found."
        return accounts, None

    def _first_account_id(self) -> tuple[str, str | None]:
        """Return (account_id, None) for the primary account, or ("", error) if none exist.

        Applies the "accountId" -> "id" key fallback IBKR varies between endpoints.
        Use this instead of inlining get_accounts() when a handler needs one account.
        """
        accounts, err = self._get_accounts()
        if err:
            return "", err
        return accounts[0].get("accountId", accounts[0].get("id", "")), None

    def _all_account_ids(self) -> tuple[list[str], str | None]:
        """Return (account_ids, None) for every account, or ([], error) if none exist.

        Applies the "accountId" -> "id" key fallback. Use for Portfolio Analyst
        endpoints (/pa/*) which take a list of account IDs.
        """
        accounts, err = self._get_accounts()
        if err:
            return [], err
        return [a.get("accountId", a.get("id", "")) for a in accounts], None

    def _fetch_market_data(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        """Fetch OHLCV bars for a symbol, Drive-cache first, IBKR on miss.

        On a cache hit, loads and summarizes the parquet. On a miss, resolves the
        conid (STK only — no sec_type parameter on this tool), then calls
        get_market_history_paginated with up to 3 warmup retries (2s apart) because
        /iserver/marketdata/history may return 404/500/empty on the first request
        while IBKR initializes the subscription. Saves the result to the Drive
        cache. Returns a human-readable summary, not the raw bars.
        """
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

        resolved = self._resolve_snapshot_conid(symbol, "STK", None)
        if resolved.error:
            return f"{resolved.error} Is IBKR connected?", None
        conid = resolved.conid

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
        hit = self._cache.check(inputs["symbol"], inputs["timeframe"], inputs["period"], inputs["end"])
        label = "HIT" if hit else "MISS"
        return f"Cache {label} for {inputs['symbol']} {inputs['timeframe']} {inputs['period']}–{inputs['end']}", None

    def _list_cache(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        """List every dataset in the Drive market-data cache with row count and cache date.

        Returns "Drive cache is empty." when nothing is cached. Each line is
        "<key>: <rows> bars, cached <YYYY-MM-DD>", tolerating missing rows/cached_at.
        """
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
        rows = ["| Symbol | Qty | Mkt Val | Unrealized P&L |", "|---|---|---|---|"]
        for p in positions:
            symbol = p.get("contractDesc", p.get("ticker", p.get("symbol", "?")))
            pos = p.get("position", 0)
            # IBKR can send these keys present but null — float(x or 0) matches
            # the _get_pnl/_get_ledger convention for the same fields.
            mkt_val = float(p.get("mktValue") or 0)
            pnl = float(p.get("unrealizedPnl") or 0)
            rows.append(f"| {symbol} | {pos} | {_money(mkt_val)} | **{_money_signed(pnl)}** |")
        return f"Open positions ({len(positions)}):\n\n" + "\n".join(rows), None

    def _get_trades(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        """Query trade history from two complementary sources — choose based on recency and origin needs.

        ## source='store' — Flex (full history, all origins)
        Reads local SQLite populated by sync_flex_trades. Flex Activity Statements are
        account-level reports, not per-platform logs, so they cover trades regardless of
        which client placed them (CP API, mobile app, TWS, web portal) — the specific
        enumeration of origins is empirically confirmed for live CP-API trades by
        get_trades()'s "Origin coverage — verified live 2026-07-06" note in client.py, not
        by a single official page enumerating all four origins for Flex specifically. No
        date limit on queries — full account history from the first Flex sync.
        Availability: T+1 (today's trades are never present; yesterday's trades become
        available after IBKR's overnight processing). Also includes any executions captured
        live via the WebSocket `str` topic (`mcp_server.py --stream`), which land in the
        same `trades` table in real time.
        Source: https://www.interactivebrokers.com/campus/glossary-terms/activity-statements/

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
                + "\n".join(lines)
                + pnl_line
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
            + "\n".join(lines)
            + upsert_note
        ), None

    def _sync_flex_trades(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        """Pull the latest historical trades from IBKR Flex Web Service → upsert into local SQLite store.

        ## What Flex covers
        Flex Activity Statements are account-level reports, not per-platform logs, so they
        cover trades regardless of which client placed them (CP API, mobile app, TWS, web
        portal) — the specific enumeration of origins is empirically confirmed for live
        CP-API trades by get_trades()'s "Origin coverage — verified live 2026-07-06" note in
        client.py, not by a single official page enumerating all four origins for Flex
        specifically. This is the authoritative source for historical P&L and full trade
        history.
        Source: https://www.interactivebrokers.com/campus/glossary-terms/activity-statements/

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
        """Import trades from a local Flex XML file into the SQLite store (idempotent).

        SECURITY: the path must resolve to a location under ~/.ibkr_core; anything
        else is blocked. This exists because the path arrives from the LLM and would
        otherwise allow prompt-injected reads of arbitrary local files. Returns a
        summary plus refreshed coverage, or a "Blocked:"/"File not found:" message.
        """
        from pathlib import Path

        from ibkr_core_mcp.flex_query import FlexQueryClient

        path = inputs["path"]
        # Path allowlist: only files under ~/.ibkr_core are permitted.
        # Prevents LLM prompt-injection from reading arbitrary local files.
        # is_relative_to (not a string-prefix check) so a sibling directory whose
        # name is a superstring of ".ibkr_core" (e.g. ".ibkr_core_evil") can't
        # pass — see docs/audits/security-audit-2026-07-11.md M-2.
        allowed_root = Path.home() / ".ibkr_core"
        resolved = Path(path).expanduser().resolve()
        if resolved != allowed_root and not resolved.is_relative_to(allowed_root):
            return f"Blocked: import path must be under {allowed_root}.", None
        if not resolved.exists():
            return f"File not found: {path}", None
        flex = FlexQueryClient(self._config, self._store, self._cache)
        trades = flex.import_from_file(str(resolved))
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
                dupe_note = _dupe_note(raw_count, len(unique_ids), verbose=True)
                file_lines.append(f"  ✓ pre-validated  {filename}  ({len(unique_ids)} tradeIDs){dupe_note}")
                all_xml_ids |= unique_ids
                continue

            # Auto-synced file: check hash against manifest.
            if entry is not None and entry["sha256"] == sha256:
                # Hash matches what was recorded at sync time — import is confirmed complete.
                self._store.mark_flex_import_verified(filename, now)
                dupe_note = _dupe_note(raw_count, len(unique_ids))
                file_lines.append(f"  ✓ hash verified  {filename}  ({len(unique_ids)} tradeIDs){dupe_note}")
                all_xml_ids |= unique_ids
                continue

            # Hash mismatch or first encounter for an auto file: full cross-check.
            reason = "first check" if entry is None else "hash mismatch — file changed since sync"
            missing = unique_ids - db_ids
            dupe_note = _dupe_note(raw_count, len(unique_ids))
            if missing:
                file_lines.append(
                    f"  ✗ {len(missing)} missing  {filename}  ({len(unique_ids)} in XML, {reason}){dupe_note}"
                )
                file_lines.append(f"    Missing tradeIDs (first 5): {sorted(missing)[:5]}")
                issues.append(filename)
            else:
                file_lines.append(f"  ✓ cross-checked  {filename}  ({len(unique_ids)} tradeIDs, {reason}){dupe_note}")
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
            lines.append(f"  Action: re-import {len(issues)} file(s) using import_flex_file or sync_flex_archive.")
        else:
            lines.append("  Result: all source tradeIDs confirmed present in SQLite.")

        return "\n".join(lines), None

    def _get_live_orders(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        """Return working orders (all statuses except Filled/Cancelled/Expired) across all instrument types.

        Origin is determined from the order_ref prefix ('CLAUDIA-' = ClaudIA-staged) rather
        than clientId, which is unreliable — both CP API and mobile orders can show clientId=0.
        order_ref is IBKR's real Live Orders field (snake_case); orderRef/cOID/clientOrderId
        are kept as fallbacks only (see docs/project-status.md Known Gaps, found 2026-07-10).
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
            order_ref = (
                o.get("order_ref")  # IBKR's real Live Orders field (snake_case) — verified
                # against docs/audits/audit-evidence/scrapes/cpapi-v1.md
                or o.get("orderRef")  # kept in case IBKR ever adds a camelCase alias
                or o.get("cOID")
                or o.get("clientOrderId")
                or ""
            )
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
        raw = self._client.get_orders_raw()
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
            order_ref = o.get("order_ref") or o.get("orderRef") or o.get("cOID") or ""
            client_id = o.get("clientId", "absent")
            if order_ref.startswith("CLAUDIA-"):
                origin = "ClaudIA-staged"
            elif client_id not in (0, "0", "absent", None):
                origin = f"API (clientId={client_id})"
            else:
                origin = "EXTERNAL"
            lines.append(
                f"orderId={o.get('orderId')} ticker={o.get('ticker', o.get('symbol'))} "
                f"side={o.get('side')} qty={o.get('totalSize')} price={o.get('price')} "
                f"status={status} origin={origin} clientId={client_id} "
                f"ref={order_ref or 'none'}{filtered}"
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

            def _f(key: str, _data: dict[str, Any] = data) -> float:
                try:
                    return float(_data.get(key) or 0)
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
            lines.append(f"  Net Liquidation Value : **{_money(nlv)}**")
            lines.append(f"  Cash Balance          : {_money(cash)}")
            lines.append(f"  Stock Market Value    : {_money(stock)}")
            if fut_mv:
                lines.append(f"  Futures Market Value  : {_money(fut_mv)}")
            lines.append(f"  Unrealized P&L        : **{_money_signed(unrealized)}**")
            lines.append(f"  Realized P&L          : **{_money_signed(realized)}**")
            if fut_pnl:
                lines.append(f"  Futures P&L           : **{_money_signed(fut_pnl)}**")
            if interest:
                lines.append(f"  Interest Accrued      : {_money_signed(interest)}")
            if dividends:
                lines.append(f"  Dividends             : {_money_signed(dividends)}")

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
        Call this before get_pa_performance when unsure which period values IBKR accepts.
        get_pa_transactions does not take a period — it takes a symbol (resolved to a conid).
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
        periods = self._client.get_pa_periods(account_ids)
        if periods:
            return "Valid PA periods:\n" + "\n".join(f"  - {p}" for p in periods), None
        # Extraction failed — fetch raw response to help diagnose the unknown shape.
        raw = self._client.get_pa_periods_raw(account_ids)
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

        ## Instrument scope
        IBKR's /pa/transactions endpoint takes `conids`, not a period string — and only one
        conid per call is supported. `symbol` is resolved to a conid via
        `_resolve_snapshot_conid` (same dispatch used by get_market_snapshot/get_contract_info).
        `days` is an optional lookback window; omit it for IBKR's default range.

        ## vs Flex (sync_flex_trades)
        Both cover all origins. Flex is T+1 (yesterday at best) but provides multi-year
        authoritative history. PA is faster (likely same-day) but limited to recent periods.
        """
        symbol = inputs["symbol"].upper()
        sec_type = inputs.get("sec_type", "STK")
        currency = inputs.get("currency", "USD")
        days = inputs.get("days")
        resolved = self._resolve_snapshot_conid(symbol, sec_type, None)
        if resolved.error:
            return resolved.error, None
        conid = resolved.conid
        account_ids, err = self._all_account_ids()
        if err:
            return err, None
        txns = self._client.get_pa_transactions(account_ids, [conid], currency, days)
        if not txns:
            return f"No transactions found for {symbol}.", None

        lines = []
        total_amount = 0.0
        for t in txns:
            if not isinstance(t, dict):
                continue
            date = str(t.get("date") or t.get("settleDate") or "?")[:10]
            desc = t.get("desc") or t.get("description") or t.get("type") or "?"
            amount = t.get("amount") or t.get("netCash") or 0
            try:
                amount = float(amount)
            except (ValueError, TypeError):
                amount = 0.0
            total_amount += amount
            lines.append(f"- {date} {desc}: {amount:+.2f}")

        return (
            f"PA Transactions — {symbol} ({len(lines)} records, all origins):\n"
            + "\n".join(lines[:50])
            + (f"\n  (showing first 50 of {len(lines)})" if len(lines) > 50 else "")
            + f"\nNet total: {total_amount:+.2f}"
        ), None

    def _get_contract_info(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        """Return full contract details and trading rules for any instrument type."""
        symbol = inputs["symbol"].upper()
        sec_type = inputs.get("sec_type", "STK")
        resolved = self._resolve_snapshot_conid(symbol, sec_type, None)
        if resolved.error:
            return resolved.error, None
        conid = resolved.conid
        info = self._client.get_contract_info_and_rules(conid)
        return json.dumps(info, indent=2), None

    def _get_option_chain(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        """Return the option chain via the documented secdef/search → strikes flow.

        Reimplemented 2026-07-07 (audit register item 6). client.get_option_chain()
        now performs the two-step documented flow and returns all expiry months plus
        call/put strikes for the requested month (default: nearest expiry).
        """
        symbol = inputs["symbol"].upper()
        month = inputs.get("month")
        exchange = inputs.get("exchange", "SMART")
        chain = self._client.get_option_chain(symbol, month=month, exchange=exchange)
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
            f"{i + 1}. {r.get('symbol', r.get('contractDescription', {}).get('symbol', '?'))} "
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
        try:
            result = _run_backtest(code, df, strategy_name=strategy_name, symbol=symbol)
        except BacktestError as exc:
            # Sandbox errors are errors in code the LLM itself wrote — the detail
            # is required for self-correction and contains nothing internal, so it
            # is returned here rather than redacted by _safe_error (which stays as
            # the conservative fallback for anything else).
            cols = ", ".join(str(c) for c in df.columns)
            return (
                f"Backtest failed: {exc}\n"
                f"  Available df columns: {cols}\n"
                "  Contract: strategy code receives df (raw OHLCV — indicators are "
                "NOT pre-computed; derive them in the code) and must set "
                "df['signal'] with 1=long, 0=flat, -1=short. Allowed: pd/np safe "
                "subsets, DataFrame methods; no imports or I/O."
            ), None
        try:
            self._store.save_backtest(result.to_dict())
        except Exception as exc:
            log.warning("_run_backtest: failed to persist result to store: %s", exc)
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
        """Generate a PineScript v5 script — indicator study or backtest-derived strategy.

        source='indicators' (default) emits an indicator study; source='backtest'
        rebuilds the most recent stored run_backtest result (optionally filtered by
        strategy_name) and emits a strategy() script via pinescript.strategy_from_backtest,
        with the real stored metrics in the header. strategy_from_signals is not wired —
        the signal series is never persisted (Python-API-only, see pinescript.py).
        """
        symbol = inputs["symbol"].upper()
        source = inputs.get("source", "indicators")
        strategy_name = inputs.get("strategy_name", "")

        if source == "backtest":
            runs = self._store.get_backtests(symbol=symbol, strategy=strategy_name or None)
            if not runs:
                which = f" named {strategy_name!r}" if strategy_name else ""
                return (
                    f"No stored backtest{which} for {symbol}. "
                    "Run run_backtest first — its result is persisted and this tool "
                    "generates the strategy script from the most recent run."
                ), None
            row = runs[0]
            result = BacktestResult(
                symbol=row.get("symbol") or symbol,
                strategy_name=row.get("strategy_name") or f"{symbol} Strategy",
                total_return=row.get("total_return") or 0.0,
                sharpe=row.get("sharpe") or 0.0,
                sortino=row.get("sortino") or 0.0,
                max_drawdown=row.get("max_drawdown") or 0.0,
                num_trades=row.get("num_trades") or 0,
                win_rate=row.get("win_rate") or 0.0,
            )
            # df is only used for timeframe inference; fall back to an empty frame
            # (infers '1D') when the bars aren't in cache under the provided keys.
            df = pd.DataFrame()
            timeframe = inputs.get("timeframe")
            period = inputs.get("period")
            end = inputs.get("end")
            if timeframe and period and end and self._cache.check(symbol, timeframe, period, end):
                df = self._cache.load(symbol, timeframe, period, end)
            return _pinescript.strategy_from_backtest(result, df), None

        indicators_list = inputs.get("indicators", ["rsi", "macd"])
        script = _pinescript.indicator_script(strategy_name or f"{symbol} Indicators", indicators_list, {})
        return script, None

    def _preview_order(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        """Return a whatif order preview (commission, margin impact) without submitting.

        sec_type routes contract resolution (_resolve_snapshot_conid): STK (default),
        IND, BOND, FUT (front month), or CASH ('BASE.QUOTE'). OPT is not supported.
        Price mapping per order type follows the CP API place-order spec.
        """
        # Order type names match IBKR CP API place-order field spec. Only types this
        # tool can fully parameterize are admitted: TRAIL/TRAILLMT need trailingAmt/
        # trailingType (not exposed here); MOC/LOC are not in the documented type list.
        # Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#place-order
        _VALID_ACTIONS = frozenset({"BUY", "SELL"})
        _VALID_ORDER_TYPES = frozenset({"MKT", "LMT", "STP", "STOP_LIMIT", "MIDPRICE"})
        symbol = inputs["symbol"].upper()
        action = inputs["action"].upper()
        quantity = int(inputs["quantity"])
        order_type = inputs.get("order_type", "MKT").upper()
        limit_price = inputs.get("limit_price")
        stop_price = inputs.get("stop_price")
        sec_type = inputs.get("sec_type", "STK").upper()

        if action not in _VALID_ACTIONS:
            return f"Invalid action {action!r}. Must be BUY or SELL.", None
        if order_type not in _VALID_ORDER_TYPES:
            return f"Invalid order_type {order_type!r}. Must be one of: {', '.join(sorted(_VALID_ORDER_TYPES))}.", None
        if quantity <= 0:
            return f"Invalid quantity {quantity}. Must be a positive integer.", None
        if order_type == "LMT" and limit_price is None:
            return "order_type='LMT' requires limit_price.", None
        if order_type == "STP" and stop_price is None:
            return "order_type='STP' requires stop_price.", None
        if order_type == "STOP_LIMIT":
            if stop_price is None:
                return "order_type='STOP_LIMIT' requires stop_price (and limit_price).", None
            if limit_price is None:
                return "order_type='STOP_LIMIT' requires limit_price (and stop_price).", None

        resolved = self._resolve_snapshot_conid(symbol, sec_type, None)
        if resolved.error:
            return resolved.error, None
        conid = resolved.conid

        account_id, err = self._first_account_id()
        if err:
            return err, None

        order: dict[str, Any] = {
            "conid": conid,  # IBKR requires int
            "orderType": order_type,
            "side": action,
            "quantity": int(quantity),  # int matches place_order convention
            "tif": "DAY",
        }
        if sec_type in ("FUT", "FOP"):
            # Required for US Futures and Futures Options — CME Group Rule 536-B
            # Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#place-order
            order["manualIndicator"] = True
            order["extOperator"] = "ClaudIA"
        # Price-field mapping per the CP API place-order spec: `price` is the limit
        # for LMT/STOP_LIMIT, the stop for STP, the option price cap for MIDPRICE;
        # `auxPrice` is the stop for STOP_LIMIT.
        if order_type in ("LMT", "MIDPRICE") and limit_price is not None:
            order["price"] = float(limit_price)  # IBKR requires float
        elif order_type == "STP" and stop_price is not None:
            order["price"] = float(stop_price)
        elif order_type == "STOP_LIMIT" and limit_price is not None and stop_price is not None:
            order["price"] = float(limit_price)
            order["auxPrice"] = float(stop_price)

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
        """Return real-time account/model-partition P&L (daily + unrealized), not per-position.

        GET /iserver/account/pnl/partitioned returns ONE summary row per account/model
        partition (e.g. "U1675699.Core") — rowType, dpl (daily), nl (net liquidity),
        upl (unrealized), el (excess liquidity), mv (margin value). There is no
        per-position/conid breakdown in this endpoint at all, despite an earlier
        version of this docstring claiming one; for per-position detail use
        get_positions instead. Verified against
        https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#account-pnl
        (scraped 2026-07-02, re-verified 2026-07-07).

        Cold-gateway quirk (live-verified 2026-07-17, see
        docs/plans/2026-07-17-account-pnl-display-fixes.md in the sibling claudia_ui
        repo): on a fresh gateway session this endpoint returns an empty {"upnl": {}}
        even when the account has open positions and real P&L, until something has
        subscribed to the spl WebSocket topic at least once. If the first call comes
        back empty, this method self-primes via _prime_pnl_subscription() (a
        best-effort WS subscribe/unsubscribe touch) and retries the REST call once
        before giving up — callers never need to know about the warm-up quirk.
        """
        pnl = self._client.get_pnl()
        partitions = pnl.get("upnl") if isinstance(pnl, dict) else None
        if not partitions or not isinstance(partitions, dict):
            self._prime_pnl_subscription()
            # /iserver/account/pnl/partitioned is rate-limited to 1 req/5secs
            # (rate_limiter.py); the WS priming round-trip above is usually well
            # under that on localhost, so pace the retry explicitly rather than
            # relying on with_retry's reactive 429 backoff to absorb it.
            import time

            time.sleep(1)
            pnl = self._client.get_pnl()
            partitions = pnl.get("upnl") if isinstance(pnl, dict) else None
        if not partitions or not isinstance(partitions, dict):
            return "No P&L data returned. Ensure IBKR gateway is connected.", None
        lines = ["Real-time P&L:"]
        upnl_total = 0.0
        dpnl_total = 0.0
        for account, row in partitions.items():
            if not isinstance(row, dict):
                continue
            try:
                upl = float(row.get("upl") or 0)
                dpl = float(row.get("dpl") or 0)
            except (ValueError, TypeError):
                log.warning("Non-numeric P&L for %s, skipping partition", account)
                continue
            upnl_total += upl
            dpnl_total += dpl
            nl = row.get("nl")
            el = row.get("el")
            extra = f"  net_liq={float(nl):.2f}" if isinstance(nl, (int, float)) else ""
            extra += f"  excess_liq={float(el):.2f}" if isinstance(el, (int, float)) else ""
            lines.append(f"  {account}: unrealized={upl:+.2f}  daily={dpl:+.2f}{extra}")
        lines.append(f"\nTotal unrealized P&L: {upnl_total:+.2f}")
        lines.append(f"Total daily P&L:      {dpnl_total:+.2f}")
        return "\n".join(lines), None

    def _prime_pnl_subscription(self) -> None:
        """Best-effort warm-up touch for IBKR's spl (account P&L) WS topic.

        Live-verified 2026-07-17 (docs/plans/2026-07-17-account-pnl-display-fixes.md
        in the sibling claudia_ui repo): GET /iserver/account/pnl/partitioned returns
        an empty {"upnl": {}} on a cold gateway session — even with open positions and
        real P&L — until something has subscribed to the spl WebSocket topic at least
        once. Merely sending the "spl+{}" subscribe message is enough; no tick needs
        to actually arrive (a live 45s wait received none, yet the very next REST call
        returned real data). Same class of undocumented warm-up dependency as
        /iserver/marketdata/snapshot (see _get_market_snapshot's two-call retry below).

        Only called by _get_pnl when the first REST call comes back empty. Must never
        raise: any failure here (auth, connect, WS hiccup) is swallowed and logged as
        a warning, so it degrades to _get_pnl's pre-existing "No P&L data" message
        instead of crashing the tool call.

        Caveat: BrowserCookieAuth.apply() is a synchronous, unbounded call (no
        internal timeout) — a stuck OS keychain-access prompt could block this
        whole method. Same pre-existing risk as IBKRClient's own construction and
        mcp_server.py's _stream_loop; not new here, and in practice the keychain
        item is normally already unlocked by the time get_pnl is first called.
        """
        try:
            import os

            import requests

            from ibkr_core_mcp.auth import BrowserCookieAuth
            from ibkr_core_mcp.scrape_fallback import _run_async
            from ibkr_core_mcp.streaming import IBKRWebSocket

            async def _touch() -> None:
                session = requests.Session()
                # IBKR_AUTH_BROWSER read directly from os.environ (not via Config)
                # to mirror claudia_ui's own BrowserCookieAuth call sites exactly —
                # see docs/env-vars-reference.md in that repo.
                BrowserCookieAuth(os.environ.get("IBKR_AUTH_BROWSER", "chrome")).apply(session)
                cookie = session.headers.get("Cookie", "")
                ws = IBKRWebSocket(self._config.gateway_url, cookie)
                try:
                    await ws.connect()
                    await ws.subscribe_pnl()
                    await ws.unsubscribe_pnl()
                finally:
                    await ws.disconnect()

            _run_async(_touch())
        except Exception as exc:
            log.warning("_get_pnl: failed to prime spl WS subscription: %s", exc)

    def _get_analytics(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        """Return return, CAGR, Sharpe, Sortino, Calmar, and drawdown stats from cached bars.

        Annualised metrics scale with the bar timeframe via
        analytics.periods_for_timeframe(); an unrecognized timeframe falls back to
        daily (252 periods/yr) with an explicit caveat appended to the output.
        """
        symbol = inputs["symbol"].upper()
        timeframe = inputs["timeframe"]
        period = inputs["period"]
        end = inputs["end"]
        if not self._cache.check(symbol, timeframe, period, end):
            return f"No cached data for {symbol}. Fetch it first with fetch_market_data.", None
        df = self._cache.load(symbol, timeframe, period, end)
        returns = df["close"].pct_change().dropna()
        periods = _analytics.periods_for_timeframe(timeframe)
        caveat = None
        if periods is None:
            periods = 252
            caveat = (
                f"  NOTE: timeframe '{timeframe}' not recognized — annualised metrics "
                "computed with the daily default (252 periods/yr)."
            )
        report = _analytics.full_report(returns, periods=periods)
        lines = [
            f"Analytics for {symbol} {timeframe} ({period}–{end}, {periods} periods/yr):",
            f"  Total Return:       {report['total_return']:.1%}",
            f"  CAGR:               {report['cagr']:.1%}",
            f"  Sharpe Ratio:       {report['sharpe']:.2f}",
            f"  Sortino Ratio:      {report['sortino']:.2f}",
            f"  Calmar Ratio:       {report['calmar']:.2f}",
            f"  Max Drawdown:       {report['max_drawdown']:.1%}",
            f"  Max DD Duration:    {report['max_drawdown_duration']} bars",
            f"  Bars analyzed:      {report['num_bars']}",
        ]
        if caveat:
            lines.append(caveat)
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

    def _listing_currency(self, conid: int) -> str | None:
        """Return the currency a listing trades in, or None if it could not be read.

        Every price this toolkit reports is denominated in *some* currency, and which one
        is a property of the listing, not of the ticker: IGV is USD on BATS and MXN on
        MEXI. A number without its unit is not a smaller answer than a number with it —
        it is a different and possibly wrong one, and nothing about "IGV 18.60" looks
        wrong until you know it was pesos.

        Returns None rather than raising, and callers must then say *currency unknown*
        rather than omit it. Silence is the one outcome that is not allowed: it reads as
        "the usual currency", which is exactly the assumption this exists to remove.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#secdef-info-contract
                (GET /iserver/secdef/info; returns a LIST, live-verified 2026-07-28 —
                the wrapper's return annotation says dict, so both shapes are handled)
        """
        try:
            info: Any = self._client.get_secdef_info(conid)
        except IBKRCoreError:
            return None
        row = info[0] if isinstance(info, list) and info else info
        if isinstance(row, dict) and row.get("currency"):
            return str(row["currency"])
        return None

    def _resolve_snapshot_conid(self, sym: str, sec_type: str, exchange: str | None) -> _Resolved:
        """Resolve one symbol to a conid using the correct endpoint for its sec_type.

        The single conid-resolution implementation for the toolkit (register item 15,
        docs/audits/claude-tools-audit-2026-07.md) — every handler needing a conid
        (_fetch_market_data, _get_contract_info, _preview_order, _get_market_snapshot,
        _create_price_alert) calls this rather than a duplicated STK/IND/BOND-only path.

        /iserver/secdef/search (used by search_contract) only documents support for
        STK, IND, BOND — NOT FUT or CASH. Using it for those types silently returns
        wrong or empty results. This dispatches to the documented endpoint per type:

        - STK: /trsrv/stocks (see _resolve_stock_conid) — the endpoint IBKR designates
          for symbol→conid resolution, and the only one carrying `isUS`. Defaults to the
          US listing and returns a question when that is not unique. It does NOT take
          "the first match": for IGV that was the Mexican listing, priced in MXN.
        - IND/BOND: /iserver/secdef/search (search_contract). If exchange is given,
          filters on `description` (the exchange code — there is no `exchange` key on
          these results) and errors when nothing matches, rather than substituting.
        - FUT: /trsrv/futures (get_futures) — returns all non-expired contracts for the
          root symbol; picks the lowest expirationDate (front month).
        - CASH: /iserver/currency/pairs (get_currency_pairs) — symbol must be 'BASE.QUOTE'
          (e.g. 'EUR.USD'). Queries pairs for the base currency, then matches the
          'BASE.QUOTE' symbol exactly. NOT resolved via /iserver/secdef/search — CASH
          is not in that endpoint's documented secType list.

        Returns a `_Resolved`: the conid and the currency it trades in, or an error.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#sec-search
                https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/ (trsrv/futures)
                https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#get-currency-pairs
        """
        if sec_type == "FUT":
            futures = self._client.get_futures([sym])
            if not futures:
                return _Resolved(0, None, f"No futures contracts found for root symbol {sym}.")
            try:
                front = min(futures, key=lambda f: int(f.get("expirationDate") or 0))
            except (ValueError, TypeError):
                front = futures[0]
            conid = front.get("conid")
            try:
                conid_int = int(conid) if conid else 0
            except (ValueError, TypeError):
                conid_int = 0
            if conid_int <= 0:
                return _Resolved(0, None, f"Futures contract for {sym} found but conid missing.")
            return _Resolved(conid_int, self._listing_currency(conid_int), None)

        if sec_type == "CASH":
            if "." not in sym:
                return _Resolved(0, None, f"FX pair {sym} must be in 'BASE.QUOTE' format (e.g. 'EUR.USD').")
            base, _, quote = sym.partition(".")
            pairs = self._client.get_currency_pairs(base)
            if not pairs:
                return _Resolved(0, None, f"No FX pairs found for base currency {base}.")
            match = next((p for p in pairs if str(p.get("symbol", "")).upper() == sym), None)
            if not match:
                return _Resolved(0, None, f"FX pair {sym} not found among {base} pairs.")
            conid = match.get("conid")
            try:
                conid_int = int(conid) if conid else 0
            except (ValueError, TypeError):
                conid_int = 0
            if conid_int <= 0:
                return _Resolved(0, None, f"FX pair {sym} found but conid missing.")
            return _Resolved(conid_int, self._listing_currency(conid_int), None)

        if sec_type == "STK":
            return self._resolve_stock_conid(sym, exchange)

        contracts = self._client.search_contract(sym, sec_type)
        if not contracts:
            return _Resolved(0, None, f"Could not resolve conid for {sym} (as {sec_type}).")

        if exchange:
            # `description` carries the exchange code on /iserver/secdef/search results;
            # there is NO `exchange` key (live-probed 2026-07-28: the returned keys are
            # companyHeader, companyName, conid, description, restricted, sections,
            # symbol). Filtering on "exchange" therefore matched nothing in production
            # and fell through to the unfiltered list — a silently wrong listing, masked
            # by a unit-test mock that invented the field.
            matches = [c for c in contracts if str(c.get("description") or "").upper() == exchange.upper()]
            if not matches:
                available = ", ".join(sorted({str(c.get("description") or "?") for c in contracts}))
                return _Resolved(
                    0,
                    None,
                    (
                        f"{sym} ({sec_type}) has no listing on {exchange}. Available: "
                        f"{available}. Ask the user which one they mean — do not substitute "
                        f"another exchange."
                    ),
                    ambiguous=True,
                )
            contracts = matches

        conid = contracts[0].get("conid") or contracts[0].get("con_id")
        try:
            conid_int = int(conid) if conid else 0
        except (ValueError, TypeError):
            conid_int = 0
        if conid_int <= 0:
            return _Resolved(0, None, f"Contract found for {sym} but conid missing.")
        return _Resolved(conid_int, self._listing_currency(conid_int), None)

    def _resolve_stock_conid(self, sym: str, exchange: str | None) -> _Resolved:
        """Resolve a STK symbol to one conid, or return a question instead of a guess.

        A ticker is not a unique key. IBKR documents this outright: *"For a single
        product trading in multiple markets, IB will assign distinct `conids` for each
        combination of product and currency. For instance, AAPL stock trading in USD in
        the United States has a different `conid` than the same AAPL stock trading in
        MXN."* Worse, the same ticker can belong to **different companies** — live-probed
        2026-07-28: IGV is both ISHARES EXPANDED TECH-SOFTWA and I GRANDI VIAGGI SPA;
        VOD is both VODAFONE GROUP PLC and VODACOM GROUP LTD.

        This uses `/trsrv/stocks`, which IBKR calls *"designed specifically for resolving
        stock symbols into `conids`"* and which is the only endpoint that answers the
        US-listing question itself, via a documented `isUS` boolean per contract.
        `/iserver/secdef/search` — what this resolver used before — returns neither
        `isUS` nor a currency, and its result *order* is not documented as meaningful.
        It was being trusted anyway: `contracts[0]` for IGV is the **Mexican** listing
        (conid 325209548, MXN), which is how a US ETF was reported at an MXN price, while
        `contracts[0]` for AAPL happens to be NASDAQ. Right by luck, wrong by luck.

        The rule, and it is deliberately not instrument-specific:

        1. An explicit `exchange` wins. No listing on it is an error naming what exists —
           never a substitution.
        2. Otherwise prefer the US listing, since a bare ticker is a US ticker by
           convention. Exactly one `isUS` contract resolves.
        3. Zero or several US listings is a question, not a default. Return the
           candidates so the caller asks the user. **Asking beats assuming**: a wrong
           listing is a plausible number for the wrong instrument, which is worse than
           no number because nothing about it looks wrong.

        Args:
            sym: Ticker, already upper-cased by the caller.
            exchange: Optional exchange code (e.g. "BATS", "MEXI") that pins the listing.

        Returns:
            (conid, None) when exactly one listing is determined, else (0, question)
            where `question` names every candidate and tells the caller to ask.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/web-api-staging/
                (Contracts → Equities; `GET /trsrv/stocks`, scraped 2026-07-28)
        """
        records = self._client.get_stocks([sym])
        if not records:
            return _Resolved(0, None, f"Could not resolve conid for {sym} (as STK).")

        # One row per (issuer, listing). `name` is carried down so an ambiguous ticker
        # can show WHICH company each candidate belongs to — the difference between
        # "same ETF, other currency" and "entirely different company".
        listings = [
            {
                "conid": c.get("conid"),
                "exchange": str(c.get("exchange") or "?"),
                "is_us": bool(c.get("isUS")),
                "name": str(r.get("name") or "?"),
            }
            for r in records
            for c in (r.get("contracts") or [])
        ]
        if not listings:
            return _Resolved(0, None, f"Could not resolve conid for {sym} (as STK).")

        def _pick(rows: list[dict[str, Any]]) -> _Resolved:
            try:
                conid_int = int(rows[0]["conid"] or 0)
            except (ValueError, TypeError):
                conid_int = 0
            if conid_int <= 0:
                return _Resolved(0, None, f"Contract found for {sym} but conid missing.")
            return _Resolved(conid_int, self._listing_currency(conid_int), None)

        def _describe(rows: list[dict[str, Any]]) -> str:
            return "; ".join(
                f"{r['exchange']}{' (US)' if r['is_us'] else ''} — {r['name']} — conid {r['conid']}" for r in rows
            )

        if exchange:
            matches = [r for r in listings if r["exchange"].upper() == exchange.upper()]
            if not matches:
                return _Resolved(
                    0,
                    None,
                    (
                        f"{sym} has no listing on {exchange}. Available: "
                        f"{_describe(listings)}. Ask the user which one they mean — do not "
                        f"substitute another exchange."
                    ),
                    ambiguous=True,
                )
            return _pick(matches)

        us = [r for r in listings if r["is_us"]]
        if len(us) == 1:
            return _pick(us)

        if not us:
            return _Resolved(
                0,
                None,
                (
                    f"{sym} has no US listing. Candidates: {_describe(listings)}. Ask the "
                    f"user which listing they mean and re-call with that exchange — do not "
                    f"pick one, and do not report a price until they answer."
                ),
                ambiguous=True,
            )
        return _Resolved(
            0,
            None,
            (
                f"{sym} is ambiguous: {len(us)} US listings. Candidates: {_describe(us)}. "
                f"Ask the user which one they mean and re-call with that exchange — do not "
                f"pick one, and do not report a price until they answer."
            ),
            ambiguous=True,
        )

    def _get_market_snapshot(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        """Return live market data snapshot for one or more symbols.

        Each quote is enriched with:
          _symbol       — ticker resolved from conid
          _data_status  — 'Live (Real-Time)' when subscribed; 'Delayed (15–20 min)' or
                          'Not Subscribed (no data — neither live nor delayed)' otherwise.
                          Derived from field 6509 (Market Data Availability, first char).
          _quote_time   — timestamp of the quote in ET (from field _updated, ms epoch).
                          Always report this to the user alongside price data.

        Price fields: 31=last, 84=bid, 86=ask, 70=high, 71=low, 82=change, 83=change%, 87=volume.

          _currency     — the currency this listing trades in, or 'UNKNOWN'. Always
                          report it with the price, as an ISO code and never as a bare
                          '$': the same ticker is a different currency on a different
                          venue (IGV is USD on BATS, MXN on MEXI), and USD, MXN, CAD,
                          AUD, HKD and SGD all write prices with '$', so a bare symbol
                          is ambiguous, not merely terse.

                          The instruction that reaches the model is the one in this
                          tool's TOOL_DEFINITIONS "description" — this docstring does
                          not (`tools` returns TOOL_DEFINITIONS verbatim; nothing
                          appends __doc__). Live 2026-07-28: the description named
                          _data_status and _quote_time and said "always report both",
                          and ClaudIA reported both every time while rendering price as
                          a bare '$91.42'. Keep the two in step — a rule that lives only
                          here is a rule the model never sees.

        Contract resolution is dispatched per sec_type by _resolve_snapshot_conid() —
        STK via /trsrv/stocks (US listing by default, ambiguity returned as a question),
        IND/BOND via /iserver/secdef/search, FUT via /trsrv/futures (front month),
        CASH via /iserver/currency/pairs with 'BASE.QUOTE' symbol format.

        A symbol whose listing could not be determined is NOT silently dropped: its
        question is returned to the caller so the user can be asked which listing they
        meant. Reporting the other symbols while staying quiet about that one would be
        the same defect as picking a listing at random.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#md-snapshot
                https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#md-availability
        """
        symbols = [s.upper() for s in inputs["symbols"]]
        sec_type = inputs.get("sec_type", "STK")
        exchange = inputs.get("exchange")
        conids: list[int] = []
        conid_to_sym: dict[int, str] = {}
        conid_to_ccy: dict[int, str | None] = {}
        ambiguous: list[str] = []
        failed: list[str] = []
        for sym in symbols:
            resolved = self._resolve_snapshot_conid(sym, sec_type, exchange)
            if resolved.error:
                failed.append(sym)
                if resolved.ambiguous:
                    ambiguous.append(resolved.error)
            else:
                conids.append(resolved.conid)
                conid_to_sym[resolved.conid] = sym
                conid_to_ccy[resolved.conid] = resolved.currency
        if not conids:
            # The ambiguity questions ARE the answer when nothing resolved. Collapsing
            # them into "could not resolve" would throw away the one thing the user can
            # act on — which listing they meant.
            head = "\n".join(ambiguous) + "\n\n" if ambiguous else ""
            return f"{head}Could not resolve conids for: {', '.join(symbols)}.", None

        import time

        snapshot = self._client.get_market_snapshot(conids)

        # First call initializes the iServer subscription but returns no price fields.
        # Retry once after 1s — same two-call warmup pattern as /iserver/account/orders.
        # Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#md-snapshot
        def _has_prices(s: list[dict[str, Any]]) -> bool:
            return any(item.get("31") or item.get("84") or item.get("86") for item in s)

        if snapshot and not _has_prices(snapshot):
            time.sleep(1)
            snapshot = self._client.get_market_snapshot(conids)

        if not snapshot:
            return "No market snapshot data returned.", None

        # Enrich each item with _symbol, _data_status, and _quote_time.
        # Always surface all three to the user — live vs delayed and timestamp are mandatory.
        no_data: list[str] = []
        enriched: list[dict[str, Any]] = []
        for item in snapshot:
            cid = item.get("conid")
            sym = conid_to_sym.get(cid, str(cid)) if isinstance(cid, int) else str(cid)
            avail = str(item.get("6509", ""))
            first_char = avail[0] if avail else ""
            data_status = _MD_AVAILABILITY.get(first_char, f"Unknown ({avail})")

            updated_ms = item.get("_updated")
            if updated_ms:
                try:
                    dt = datetime.fromtimestamp(int(updated_ms) / 1000, tz=_ET)
                    quote_time = dt.strftime("%H:%M:%S ET")
                except Exception:
                    quote_time = str(updated_ms)
            else:
                quote_time = "unavailable"

            # N = no data (neither live nor delayed). Track for diagnostic note.
            if first_char == "N" or (not avail and not (item.get("31") or item.get("84") or item.get("86"))):
                no_data.append(f"{sym} (conid={cid})")

            # 'UNKNOWN' rather than an omitted key: a missing currency reads as "the
            # usual one", which is the assumption that let an MXN price be reported as
            # though it were USD. Absent is indistinguishable from USD; UNKNOWN is not.
            ccy = conid_to_ccy.get(cid) if isinstance(cid, int) else None
            enriched.append(
                {
                    "_symbol": sym,
                    "_currency": ccy or "UNKNOWN",
                    "_data_status": data_status,
                    "_quote_time": quote_time,
                    **item,
                }
            )

        result = json.dumps(enriched, indent=2)
        notes = []
        # Ambiguity first: it is a question for the user, not a diagnostic, and it must
        # not be buried under the symbols that did resolve.
        notes.extend(ambiguous)
        if failed:
            notes.append(f"Could not resolve conid for: {', '.join(failed)} (as {sec_type}).")
        if no_data:
            notes.append(
                f"IBKR returned 'Not Subscribed' (6509=N) for: {', '.join(no_data)}. "
                "No data — neither real-time nor delayed. "
                "NYSE and NYSE Arca require separate market data subscriptions from NASDAQ "
                "even within a US equities bundle. "
                "Check: Account Management → Settings → Market Data Subscriptions. "
                "If the ticker is incorrect, please provide the right one. "
                "Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#md-availability"
            )
        if notes:
            result = "\n".join(notes) + "\n\n" + result
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
        """Create an IBKR server-side price alert that fires via the mobile app
        regardless of session state.

        Conid resolution goes through _resolve_snapshot_conid (STK/IND/BOND via
        search_contract; FUT via get_futures front-month; CASH via
        get_currency_pairs) — NOT a raw search_contract call, which per client.py's
        documented endpoint scope only supports STK/IND/BOND and would silently
        mis-resolve or fail for FUT/CASH. See docs/audits/claude-tools-audit-2026-07.md.
        The alert condition's exchange is always "SMART" (IBKR's standard routing
        default, used throughout this codebase) since _resolve_snapshot_conid does
        not return a resolved listing exchange.
        """
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
        resolved = self._resolve_snapshot_conid(symbol, sec_type, None)
        if resolved.error:
            return resolved.error, None
        conid_int = resolved.conid
        exchange = "SMART"
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
                    "type": 1,  # 1 = Price per IBKR Client Portal API
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
        existing = self._client.get_alert(alert_id)
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
        """Permanently delete an IBKR price alert by ID for the primary account.

        Resolves the account via _first_account_id first; returns that error if no
        account is found. The deletion itself is not gated (alerts are not orders).
        """
        account_id, err = self._first_account_id()
        if err:
            return err, None
        result = self._client.delete_alert(account_id, inputs["alert_id"])
        return json.dumps(result, indent=2), None

    def _activate_alert(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        """Enable or disable an existing IBKR price alert without deleting it.

        The `activate` input defaults to True when omitted. Resolves the primary
        account via _first_account_id. Returns the raw IBKR response as JSON.
        """
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
            symbols = (
                [r.get("ST") or r.get("symbol") or r.get("conid") or str(r) for r in rows if isinstance(r, dict)]
                if rows
                else []
            )
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
        """Delete one dataset from the Drive market-data cache, keyed by symbol/timeframe/period/end.

        Checks existence first and returns a "No cached entry" message if absent,
        so a miss is reported rather than silently succeeding.
        """
        symbol = inputs["symbol"].upper()
        timeframe = inputs["timeframe"]
        period = inputs["period"]
        end = inputs["end"]
        if not self._cache.check(symbol, timeframe, period, end):
            return f"No cached entry for {symbol} {timeframe} ({period}, end={end}).", None
        self._cache.delete(symbol, timeframe, period, end)
        return f"Deleted cache entry for {symbol} {timeframe} ({period}, end={end}).", None

    def _validate_public_url(self, url: str) -> str | None:
        """SSRF guard: return None if `url` is safe to fetch directly (http/https,
        resolves to a public address), or a "Blocked: ..." message if not.

        Shared by every code path that can trigger a *local* fetch of an
        externally-sourced URL: the firecrawl_crawl root URL, and — critically —
        every per-page/per-result URL passed to _assess_fallback_need (called by
        both _scrape_with_fallback for the search path and
        _apply_crawl4ai_fallback_batch for the crawl path), since those
        can originate from Firecrawl's own crawl (redirects/internal links) or from
        search results (which are external, attacker-influenceable content) rather
        than from a URL the caller explicitly typed in.

        Handles standard hostnames, IPv4/IPv6 literals, and decimal/hex-encoded IPs
        (e.g. http://2130706433/ = 127.0.0.1) by resolving before checking.

        This is one of two independent SSRF layers — see is_private_host's
        docstring in scrape_fallback.py for why a Python-level pre-check alone
        (this method) cannot fully close a DNS-rebinding or redirect-based
        bypass, and how the second layer (a Playwright-level per-request guard
        installed in Crawl4AIScraper.scrape/scrape_batch) closes it.

        Args:
            url: Candidate URL to validate before any local fetch.

        Returns:
            None if safe to fetch. Otherwise a human-readable "Blocked: ..." or
            "Invalid URL: ..." string suitable for returning directly to the LLM.
        """
        import urllib.parse

        from ibkr_core_mcp.scrape_fallback import is_private_host

        try:
            parsed = urllib.parse.urlparse(url)
            if parsed.scheme not in ("http", "https"):
                return f"Blocked: only http/https URLs are supported (got {parsed.scheme!r})."
            host = (parsed.hostname or "").lower()
            if not host:
                return "Blocked: URL has no hostname."
            if is_private_host(host):
                return "Blocked: cannot fetch from localhost, link-local, or private/reserved addresses."
        except Exception as exc:
            return f"Invalid URL: {exc}"
        return None

    def _assess_fallback_need(self, url: str, markdown: str, metadata: dict[str, Any] | None) -> tuple[bool, str, str]:
        """Decide whether `url` needs a Crawl4AI fallback fetch, without
        performing it -- the "decide" half of _scrape_with_fallback, split out
        so the crawl-path batch loop (_apply_crawl4ai_fallback_batch) can
        classify every page up front before opening a single shared browser.

        assess_quality decides "ok" / "ambiguous" / "fallback" from Firecrawl's
        own signals plus cheap heuristics. "ambiguous" results get one extra
        Claude call (judge_completeness_llm) before deciding whether to fall
        back -- this keeps the common case (clean results) free of any extra
        API call. A transient judge failure fails safe (keeps Firecrawl's
        content) rather than escalating to the slower Crawl4AI path.

        Args:
            url: Source URL for this result/page. Validated against
                 _validate_public_url as the last check before returning
                 needs_fallback=True -- this can't be skipped even though
                 firecrawl_crawl already validates its own root URL, since
                 this url may be a Firecrawl-discovered sub-page or search
                 result rather than the one the caller explicitly validated.
            markdown: Firecrawl's markdown for this result/page (may be empty).
            metadata: Firecrawl's per-result/per-page "metadata" dict, or None.

        Returns:
            (needs_fallback, markdown_if_not_needed, note_if_not_needed). When
            needs_fallback is True, the other two fields are "" -- the caller
            is responsible for actually fetching (via Crawl4AIScraper) and
            turning the outcome into a final result via
            _finalize_fallback_result. When needs_fallback is False, the
            caller should use markdown_if_not_needed/note_if_not_needed
            directly and must not call Crawl4AI at all for this URL.
        """
        from ibkr_core_mcp.scrape_fallback import assess_quality, judge_completeness_llm

        quality = assess_quality(markdown, metadata, url)
        if quality == "ok":
            return False, markdown, ""

        if quality == "ambiguous":
            try:
                if judge_completeness_llm(self._config, url, markdown):
                    return False, markdown, ""
            except Exception as exc:
                log.warning("judge_completeness_llm failed for %s: %s", url, exc)
                return (
                    False,
                    markdown,
                    "(Note: completeness check failed — showing Firecrawl's result as-is)",
                )

        blocked = self._validate_public_url(url)
        if blocked:
            return False, markdown, f"(Crawl4AI fallback skipped: {blocked})"

        return True, "", ""

    def _finalize_fallback_result(
        self, url: str, original_markdown: str, outcome: dict[str, str] | Exception
    ) -> tuple[str, str, bool]:
        """Turn a Crawl4AI fetch outcome into (final_markdown, note, used_fallback)
        -- the "after the fetch" half of _scrape_with_fallback, split out so
        both the single-URL path (_scrape_with_fallback) and the batch path
        (_apply_crawl4ai_fallback_batch, via Crawl4AIScraper.scrape_batch) can
        share the exact same note wording and exception-type handling.

        Args:
            url: The URL that was fetched (used only to compute the
                 saved-profile note below).
            original_markdown: Firecrawl's original markdown for this URL,
                 used as the fallback value whenever Crawl4AI's outcome isn't
                 usable.
            outcome: Either the successful {"url": ..., "markdown": ...}
                 result dict Crawl4AIScraper.scrape()/scrape_batch() produce,
                 or the Exception that was raised/collected while fetching
                 this URL.

        Returns:
            (final_markdown, note, used_fallback) -- used_fallback is True
            only when Crawl4AI's content actually replaced Firecrawl's.
        """
        import urllib.parse

        from ibkr_core_mcp.scrape_fallback import Crawl4AIUnavailableError

        if isinstance(outcome, Crawl4AIUnavailableError):
            return original_markdown, f"(Crawl4AI fallback unavailable: {outcome})", False
        if isinstance(outcome, Exception):
            log.warning("Crawl4AI fallback failed for %s: %s", url, outcome)
            return (
                original_markdown,
                "(Crawl4AI fallback failed — showing Firecrawl's partial result)",
                False,
            )

        fallback_markdown = outcome.get("markdown", "")
        if not fallback_markdown:
            return (
                original_markdown,
                "(Crawl4AI fallback returned no content — showing Firecrawl's partial result)",
                False,
            )

        from ibkr_core_mcp.scrape_fallback import _resolve_profile_dir

        domain = urllib.parse.urlparse(url).hostname or ""
        if _resolve_profile_dir(self._config.crawl4ai_profiles_dir, url) is not None:
            note = "(fetched via Crawl4AI fallback using a saved login profile)"
        else:
            note = (
                f"(fetched via Crawl4AI fallback — no saved login profile for {domain}; "
                f"if this is a paywalled site you subscribe to, run "
                f"`python -m ibkr_core_mcp.scrape_fallback create-profile {domain}` once)"
            )
        return fallback_markdown, note, True

    def _scrape_with_fallback(self, url: str, markdown: str, metadata: dict[str, Any] | None) -> tuple[str, str, bool]:
        """Return (final_markdown, note, used_fallback) for a single Firecrawl
        result/page, falling back to Crawl4AI when Firecrawl's content looks
        incomplete (blocked, empty, or paywalled).

        Composes _assess_fallback_need (decide) and _finalize_fallback_result
        (turn a fetch outcome into the final tuple) around a single
        Crawl4AIScraper.scrape() call. Used directly by the search path
        (_handle_firecrawl_search), where each result is typically a
        different domain, so batching across results isn't valid -- see
        _apply_crawl4ai_fallback_batch for the crawl path's batched
        equivalent.

        Args:
            url: Source URL for this result/page.
            markdown: Firecrawl's markdown for this result/page (may be empty).
            metadata: Firecrawl's per-result/per-page "metadata" dict, or None.

        Returns:
            (final_markdown, note, used_fallback) -- see _finalize_fallback_result.
        """
        needs_fallback, md_if_not, note_if_not = self._assess_fallback_need(url, markdown, metadata)
        if not needs_fallback:
            return md_if_not, note_if_not, False

        try:
            result = self._get_crawl4ai().scrape(url)
        except Exception as exc:
            return self._finalize_fallback_result(url, markdown, exc)
        return self._finalize_fallback_result(url, markdown, result)

    def _apply_crawl4ai_fallback_batch(self, root_url: str, pages: list[dict[str, Any]]) -> int:
        """Apply Crawl4AI fallback to every page in `pages` that needs it,
        mutating each page's "markdown" key in place. Used only by
        _handle_firecrawl_crawl.

        Batches every fallback-needing page into ONE
        Crawl4AIScraper.scrape_batch() call (one shared browser) instead of
        one browser launch per page -- safe because Firecrawl's crawl() only
        returns pages within the same site as root_url, so every page here
        shares the same saved-profile decision.

        Args:
            root_url: The crawl's original root URL -- used only to determine
                the shared profile domain passed to scrape_batch().
            pages: Firecrawl's page list for this crawl (each a dict with at
                least "url", "markdown", "metadata" keys).

        Returns:
            Count of pages where Crawl4AI's content actually replaced
            Firecrawl's (mirrors _scrape_with_fallback's used_fallback,
            summed across pages).
        """
        import urllib.parse

        candidates: list[tuple[dict[str, Any], str]] = []
        for page in pages:
            url = page.get("url", "")
            needs_fallback, md_if_not, _note_if_not = self._assess_fallback_need(
                url, page.get("markdown", ""), page.get("metadata")
            )
            if needs_fallback:
                candidates.append((page, page.get("markdown", "")))
            else:
                page["markdown"] = md_if_not

        if not candidates:
            return 0

        urls = [p.get("url", "") for p, _ in candidates]
        root_domain = urllib.parse.urlparse(root_url).hostname or ""
        try:
            outcomes = self._get_crawl4ai().scrape_batch(urls, profile_domain=root_domain)
        except Exception as exc:
            # A whole-batch failure (e.g. Crawl4AIUnavailableError, raised
            # before any URL is attempted) must degrade the same way a
            # per-URL failure would -- not crash the entire crawl.
            outcomes = {u: exc for u in urls}

        fallback_count = 0
        for page, original_markdown in candidates:
            url = page.get("url", "")
            outcome = outcomes.get(url, RuntimeError(f"Crawl4AI batch returned no result for {url}"))
            final_markdown, _note, used_fallback = self._finalize_fallback_result(url, original_markdown, outcome)
            page["markdown"] = final_markdown
            if used_fallback:
                fallback_count += 1
        return fallback_count

    def _handle_firecrawl_search(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        """Handle the firecrawl_search tool.

        Lazily initializes FirecrawlClient on first call. Returns a no-key message
        if FIRECRAWL_API_KEY is not configured. Optionally saves a Drive snapshot.
        """
        from ibkr_core_mcp.web_scraper import FirecrawlClient, FirecrawlError, WebDocsStore

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
        wait_for_raw = inputs.get("wait_for_ms")
        wait_for_ms = int(wait_for_raw) if wait_for_raw is not None else None
        proxy = inputs.get("proxy") or None

        if not query:
            return "query must be non-empty.", None

        try:
            results = self._firecrawl.search(query, limit=limit, wait_for_ms=wait_for_ms, proxy=proxy)
        except FirecrawlError as exc:
            return f"Firecrawl search failed (HTTP {exc.status_code}): {exc}", None

        if not results:
            return f"No results found for: {query}", None

        # Search results are typically different domains each, so unlike the
        # crawl path's shared-browser batch, there's no valid single browser
        # config to reuse here -- instead fetch fallbacks concurrently
        # (bounded) so independent per-domain browser launches overlap
        # instead of queuing sequentially behind each other.
        #
        # Built here, on this thread, before the pool fans out. _get_crawl4ai's
        # `if is None` is unguarded by a lock (see the note in __init__), and this is
        # the one genuinely multi-threaded path in the class — without this line, N
        # workers race to construct N scrapers and the last write wins.
        self._get_crawl4ai()
        with ThreadPoolExecutor(max_workers=min(_MAX_CONCURRENT_FALLBACKS, len(results))) as executor:
            fallback_results = list(
                executor.map(
                    lambda r: self._scrape_with_fallback(r.get("url", ""), r.get("markdown", ""), r.get("metadata")),
                    results,
                )
            )

        lines = [f"## Search results for: {query}\n"]
        for i, (r, (md, note, _used)) in enumerate(zip(results, fallback_results, strict=True), 1):
            r["markdown"] = md
            lines.append(f"### {i}. {r.get('title', '(no title)')}")
            lines.append(f"**URL:** {r.get('url', '')}\n")
            if md:
                lines.append(md[:2000])  # truncate very long pages
            if note:
                lines.append(note)
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

    def _crawl4ai_root_scrape(self, url: str) -> list[dict[str, Any]]:
        """Fetch a crawl's root URL locally with Crawl4AI as the ladder's last rung.

        The per-page fallback (_apply_crawl4ai_fallback_batch) iterates over Firecrawl's
        page list, so it cannot recover a crawl that produced no pages at all — the exact
        failure this closes. Fetching the root at least yields the landing page, and does
        it locally and free, which is also the right move when Firecrawl is rate-limited
        or out of credits.

        Args:
            url: The crawl's root URL, already SSRF-validated by the caller.

        Returns:
            A single-page list shaped like Firecrawl's own output so it flows into
            save_crawl unchanged, or [] when Crawl4AI produced nothing or is unavailable.
        """
        outcome: dict[str, str] | Exception
        try:
            outcome = self._get_crawl4ai().scrape(url)
        except Exception as exc:
            outcome = exc

        markdown, _note, used_fallback = self._finalize_fallback_result(url, "", outcome)
        if not used_fallback or not markdown:
            return []
        return [{"url": url, "markdown": markdown, "metadata": {}}]

    def _get_crawl4ai(self) -> Any:
        """Return the lazily-built Crawl4AIScraper, constructing it on first use.

        Five call sites shared this two-line idiom verbatim (both fallback paths, the
        search-result path, the crawl root rescue, and fetch_page). Constructing it
        lazily matters: `Crawl4AIScraper.__init__` is cheap, but importing it is not
        free and the `[scraper]` extra is optional, so a host that never scrapes never
        pays for it. See the `_crawl4ai` note in `__init__` for the threading caveat.
        """
        from ibkr_core_mcp.scrape_fallback import Crawl4AIScraper

        if self._crawl4ai is None:
            self._crawl4ai = Crawl4AIScraper(self._config.crawl4ai_profiles_dir)
        return self._crawl4ai

    def _profile_hint(self, url: str) -> str:
        """Return one line on whether a saved login profile applies to `url`.

        Names the `create-profile` command for that exact domain when none does.
        Shared by every fetch_page outcome that has to explain a thin or missing
        result, because "no profile" is the single most likely cause on exactly the
        sites that tool exists for.
        """
        import urllib.parse

        from ibkr_core_mcp.scrape_fallback import _resolve_profile_dir

        if _resolve_profile_dir(self._config.crawl4ai_profiles_dir, url) is not None:
            return "Used a saved login profile for this domain."
        domain = urllib.parse.urlparse(url).hostname or url
        return (
            f"No saved login profile for {domain}. If this is a paywalled site you "
            f"subscribe to, run `python -m ibkr_core_mcp.scrape_fallback "
            f"create-profile {domain}` once — you log in by hand, and only the "
            f"resulting browser session is stored, locally."
        )

    def _handle_fetch_page(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        """Handle the fetch_page tool — one URL, straight to the local browser.

        The recovery ladder in _handle_firecrawl_crawl reaches Crawl4AI only
        *underneath* a Firecrawl attempt. That is right for archiving a site and
        wrong for reading a single paywalled article: Firecrawl cannot log in, so
        trying it first spends a credit to be handed a subscription stub. This
        handler skips it entirely.

        Deliberately does not persist to Drive. firecrawl_crawl is the archiving
        tool; this one answers "read me this page" and its result is the message.

        Args:
            inputs: {"url": <public http/https page URL>}.

        Returns:
            (text, None) — the page markdown plus a profile note, or an honest
            failure naming the cause. Never raises: an absent browser, a crashed
            browser and an empty page are three different messages, not tracebacks.
        """
        from ibkr_core_mcp.scrape_fallback import Crawl4AIUnavailableError, assess_quality

        url = str(inputs.get("url", "")).strip()
        if not url:
            return "url must be non-empty.", None

        # Before the browser is constructed, not after: this tool hands a
        # model-supplied URL to a real browser, so a late check has already made
        # the request it was meant to prevent.
        blocked = self._validate_public_url(url)
        if blocked:
            return blocked, None

        try:
            page = self._get_crawl4ai().scrape(url)
        except Crawl4AIUnavailableError as exc:
            return (
                f"Cannot fetch {url}: {exc}\n"
                f"fetch_page needs the local browser. Install it with "
                f'`pip install "ibkr_core_mcp[scraper]"` followed by `crawl4ai-setup`.',
                None,
            )
        except Exception as exc:
            # Broad by intent: a crashed browser, a navigation timeout or a dead network
            # must reach the model as a message it can act on, not a traceback.
            log.warning("fetch_page failed for %s: %s", url, exc)
            return f"Fetch of {url} failed: {exc}", None

        markdown = page.get("markdown", "")
        if not markdown:
            return (
                f"Fetch of {url} returned no content.\n"
                f"{self._profile_hint(url)}\n"
                f"Other likely causes: the page is rendered by JavaScript that did not "
                f"finish, or the site blocked an automated browser.",
                None,
            )

        # A byte count alone is not a warning. Live baseline 2026-07-28: wsj.com without a
        # login profile returns exactly 1 B, and "# Fetched: <url> (1 B)" followed by one
        # byte reads like a successful fetch of a short page. assess_quality is the same
        # signal the fallback ladder already branches on — word counts and paywall markers —
        # so this reuses the repo's existing judgment rather than inventing a second
        # threshold that could drift away from it.
        #
        # metadata is None, not omitted by oversight: Crawl4AIScraper.scrape() returns
        # {"url", "markdown"} and nothing else, so there is no HTTP status here for
        # assess_quality's status_code >= 400 branch to read. Only its word-count and
        # paywall-marker checks apply on this path.
        caution = ""
        if assess_quality(markdown, None, url) != "ok":
            caution = (
                "\n\nNOTE: this content may be incomplete — a paywall stub, a blocked "
                "request, JavaScript that never finished, or simply a genuinely short "
                "page. Check it against what was asked for before treating it as the "
                "whole article."
            )

        return (
            f"# Fetched: {url}\n({len(markdown.encode('utf-8'))} B)\n{self._profile_hint(url)}{caution}\n\n{markdown}",
            None,
        )

    def _handle_firecrawl_crawl(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        """Handle the firecrawl_crawl tool.

        Validates the URL with an SSRF guard before passing to Firecrawl. Lazily
        initializes FirecrawlClient and WebDocsStore on first call. Always saves
        results to Drive (crawl is a bulk operation — Drive storage is the point).

        Checks Drive for an existing, fresh (< 48h) manifest for this URL before
        calling Firecrawl at all — unless force_refresh is set. Without this, every
        call re-fetches from Firecrawl regardless of whether the same URL was just
        crawled, which cascades into Firecrawl's own per-minute rate limit on any
        multi-URL job that re-runs (e.g. periodically re-verifying a fixed list of
        reference doc URLs) — see WebDocsStore.get_cached_crawl's docstring for
        the 48h default's rationale.
        """
        from ibkr_core_mcp.web_scraper import FirecrawlClient, FirecrawlError, WebDocsStore

        if not self._config.firecrawl_api_key:
            return (
                "firecrawl_crawl is not available: FIRECRAWL_API_KEY is not configured. "
                "Set it in .env to enable web crawling.",
                None,
            )

        url = inputs.get("url", "").strip()
        if not url:
            return "url must be non-empty.", None

        blocked = self._validate_public_url(url)
        if blocked:
            return blocked, None

        max_pages = int(inputs.get("max_pages", 50))
        timeout_s_raw = inputs.get("timeout_s")
        timeout_s = int(timeout_s_raw) if timeout_s_raw is not None else None
        wait_for_raw = inputs.get("wait_for_ms")
        wait_for_ms = int(wait_for_raw) if wait_for_raw is not None else None
        proxy = inputs.get("proxy") or None
        force_refresh = bool(inputs.get("force_refresh", False))

        if self._firecrawl is None:
            self._firecrawl = FirecrawlClient(self._config.firecrawl_api_key)
        if self._web_docs is None:
            self._web_docs = WebDocsStore(self._config)

        if not force_refresh:
            cached = self._web_docs.get_cached_crawl(url)
            if cached is not None:
                saved = len(cached["pages"])
                return (
                    f"Using cached crawl of {url} from Drive — no Firecrawl request made.\n"
                    f"Crawled at: {cached['crawled_at']}\n"
                    f"Saved {saved} page(s). Pass force_refresh=true to re-crawl.\n"
                    f"Pages: " + ", ".join(p["url"] for p in cached["pages"][:10]) + ("..." if saved > 10 else ""),
                    None,
                )

        import requests

        from ibkr_core_mcp.web_scraper import _MIN_USEFUL_BYTES, content_bytes

        # An account-level Firecrawl failure is not the end of the call. 401/402/429 and a
        # dead network are precisely when the free, local Crawl4AI rung is worth the most —
        # returning here would skip the fallback exactly when Firecrawl cannot be used at
        # all. The error is kept so the final message can still name the real cause.
        firecrawl_failure: str | None = None
        try:
            pages = self._firecrawl.crawl(
                url,
                max_pages=max_pages,
                timeout_s=timeout_s,
                wait_for_ms=wait_for_ms,
                proxy=proxy,
            )
        except FirecrawlError as exc:
            pages, firecrawl_failure = [], f"HTTP {exc.status_code}: {exc}"
            log.warning("firecrawl crawl of %s failed (%s) — falling back to Crawl4AI", url, firecrawl_failure)
        except requests.RequestException as exc:
            pages, firecrawl_failure = [], f"network error: {exc}"
            log.warning("firecrawl crawl of %s failed (%s) — falling back to Crawl4AI", url, firecrawl_failure)

        firecrawl_bytes = content_bytes(pages)

        # Every fallback-needing page in this crawl shares one Crawl4AI browser session
        # instead of one launch per page -- see _apply_crawl4ai_fallback_batch's
        # docstring for why that is safe.
        fallback_count = self._apply_crawl4ai_fallback_batch(url, pages)

        # Measured after the batch pass, which mutates page["markdown"] in place: testing
        # a value captured before it ran would fire a redundant root scrape on a crawl
        # the per-page fallback just rescued.
        root_rescued = False
        if content_bytes(pages) < _MIN_USEFUL_BYTES:
            root_pages = self._crawl4ai_root_scrape(url)
            if content_bytes(root_pages) > content_bytes(pages):
                pages = root_pages
                root_rescued = True

        final_bytes = content_bytes(pages)
        if final_bytes == 0:
            firecrawl_line = (
                f"Firecrawl failed ({firecrawl_failure})"
                if firecrawl_failure
                else f"Firecrawl returned {firecrawl_bytes} B"
            )
            return (
                f"Crawl of {url} produced no content.\n"
                f"{firecrawl_line}, and the local Crawl4AI fallback also returned "
                f"nothing.\n"
                f"Likely causes: the site blocks automated clients, its content is "
                f"rendered by JavaScript the scraper did not wait for, or your Firecrawl "
                f"plan is rate-limited or out of credits.\n"
                f"Next: if this is a site you subscribe to, run "
                f"`python -m ibkr_core_mcp.scrape_fallback create-profile {url}` once. "
                f"To retry Firecrawl with anti-bot options, pass wait_for_ms=3000 and "
                f"proxy='auto'. For IBKR documentation, append `.md` to the page URL "
                f"instead of crawling it.",
                None,
            )

        try:
            manifest = self._web_docs.save_crawl(url, pages)
        except Exception as exc:
            return f"Crawl completed ({len(pages)} pages) but Drive save failed: {exc}", None

        saved = len(manifest["pages"])
        why_firecrawl = (
            f"Firecrawl failed — {firecrawl_failure}" if firecrawl_failure else "Firecrawl returned nothing usable"
        )
        source = f"Crawl4AI ({why_firecrawl})" if root_rescued else "Firecrawl"
        fallback_line = (
            f"\nCrawl4AI fallback used for {fallback_count} page(s) Firecrawl couldn't fully extract."
            if fallback_count
            else ""
        )
        return (
            f"Crawl complete: saved {saved} page(s) ({final_bytes} B) from {url} to Drive.\n"
            f"Source: {source}\n"
            f"Crawled at: {manifest['crawled_at']}\n"
            f"Pages: "
            + ", ".join(p["url"] for p in manifest["pages"][:10])
            + ("..." if saved > 10 else "")
            + fallback_line,
            None,
        )
