"""ibkr_core_mcp — IBKR Client Portal API package."""

import logging
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

from ibkr_core_mcp import analytics, indicators, pinescript
from ibkr_core_mcp.auth import AuthStrategy, BrowserCookieAuth, NoAuth, TokenAuth
from ibkr_core_mcp.backtest import BacktestResult, run_backtest
from ibkr_core_mcp.cache import GDriveCache
from ibkr_core_mcp.claude_tools import ClaudeToolkit
from ibkr_core_mcp.client import BracketPairing, IBKRClient, pair_bracket_response
from ibkr_core_mcp.config import Config
from ibkr_core_mcp.exceptions import (
    BacktestError,
    BacktestRuntimeError,
    BacktestSyntaxError,
    CacheError,
    CacheMissError,
    CacheWriteError,
    ConfigError,
    FlexQueryError,
    GatewayError,
    HumanAuthError,
    IBKRAPIError,
    IBKRAuthError,
    IBKRCoreError,
    IBKRRateLimitError,
    OrderValidationError,
    StoreError,
    StreamingError,
)
from ibkr_core_mcp.flex_query import FlexQueryClient
from ibkr_core_mcp.gateway import GatewayManager
from ibkr_core_mcp.human_auth import require_touch_id
from ibkr_core_mcp.models import (
    Account,
    AccountSummary,
    Alert,
    Algo,
    AuthStatus,
    BrokerageSession,
    Contract,
    ContractDetails,
    ContractRules,
    CurrencyPair,
    FutureContract,
    IBKRResponse,
    MarketHistory,
    MTAAlert,
    Notification,
    OptionChain,
    Order,
    Position,
    SecDefInfo,
    StockSearchResult,
    Trade,
    TradingSchedule,
    Watchlist,
    WatchlistDetail,
    bars_to_dataframe,
    json_default,
)
from ibkr_core_mcp.store import SQLiteStore
from ibkr_core_mcp.streaming import (
    AlertManager,
    IBKRWebSocket,
    LiveQuote,
    PnLUpdate,
    TradeExecution,
)
from ibkr_core_mcp.web_scraper import FirecrawlError, WebDocsStoreError

logging.getLogger(__name__).addHandler(logging.NullHandler())

try:
    __version__ = _pkg_version("ibkr_core_mcp")
except PackageNotFoundError:
    __version__ = "0.0.0"
__all__ = [
    # Core
    "Config",
    "IBKRClient",
    "GDriveCache",
    "SQLiteStore",
    "ClaudeToolkit",
    "FlexQueryClient",
    # Brackets — module-level, unlike the two bracket methods on IBKRClient. `client` is
    # not exported as a namespace, so these are reachable only from here.
    "pair_bracket_response",
    "BracketPairing",
    # Auth
    "AuthStrategy",
    "BrowserCookieAuth",
    "TokenAuth",
    "NoAuth",
    # Models
    "Contract",
    "IBKRResponse",
    "Position",
    "Trade",
    "Order",
    "AccountSummary",
    "Notification",
    "Account",
    "AuthStatus",
    "Alert",
    "Watchlist",
    "CurrencyPair",
    "SecDefInfo",
    "ContractDetails",
    "ContractRules",
    "FutureContract",
    "StockSearchResult",
    "Algo",
    "TradingSchedule",
    "MarketHistory",
    "OptionChain",
    "BrokerageSession",
    "WatchlistDetail",
    "MTAAlert",
    "bars_to_dataframe",
    "json_default",
    # Backtest
    "run_backtest",
    "BacktestResult",
    # Streaming
    "IBKRWebSocket",
    "LiveQuote",
    "TradeExecution",
    "PnLUpdate",
    "AlertManager",
    # Functional modules
    "indicators",
    "analytics",
    "pinescript",
    # Exceptions
    "IBKRCoreError",
    "IBKRAuthError",
    "IBKRRateLimitError",
    "IBKRAPIError",
    "CacheError",
    "CacheMissError",
    "CacheWriteError",
    "StoreError",
    "BacktestError",
    "BacktestSyntaxError",
    "BacktestRuntimeError",
    "ConfigError",
    "HumanAuthError",
    "OrderValidationError",
    "FlexQueryError",
    "StreamingError",
    "require_touch_id",
    # Gateway
    "GatewayManager",
    # Exceptions (continued)
    "GatewayError",
    "FirecrawlError",
    "WebDocsStoreError",
]
