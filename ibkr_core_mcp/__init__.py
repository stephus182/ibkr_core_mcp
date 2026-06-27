"""ibkr_core_mcp — IBKR Client Portal API package."""
import logging

from ibkr_core_mcp import analytics, indicators, pinescript
from ibkr_core_mcp.auth import AuthStrategy, BrowserCookieAuth, NoAuth, TokenAuth
from ibkr_core_mcp.backtest import BacktestResult, run_backtest
from ibkr_core_mcp.cache import GDriveCache
from ibkr_core_mcp.claude_tools import ClaudeToolkit
from ibkr_core_mcp.client import IBKRClient
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
    StoreError,
    StreamingError,
)
from ibkr_core_mcp.flex_query import FlexQueryClient
from ibkr_core_mcp.gateway import GatewayManager
from ibkr_core_mcp.human_auth import require_touch_id
from ibkr_core_mcp.models import (
    AccountSummary,
    Contract,
    Notification,
    Order,
    Position,
    Trade,
    bars_to_dataframe,
)
from ibkr_core_mcp.store import SQLiteStore
from ibkr_core_mcp.streaming import AlertManager, IBKRWebSocket, LiveQuote
from ibkr_core_mcp.web_scraper import FirecrawlError, WebDocsStoreError

logging.getLogger(__name__).addHandler(logging.NullHandler())

__version__ = "0.4.0"
__all__ = [
    # Core
    "Config",
    "IBKRClient",
    "GDriveCache",
    "SQLiteStore",
    "ClaudeToolkit",
    "FlexQueryClient",
    # Auth
    "AuthStrategy",
    "BrowserCookieAuth",
    "TokenAuth",
    "NoAuth",
    # Models
    "Contract",
    "Position",
    "Trade",
    "Order",
    "AccountSummary",
    "Notification",
    "bars_to_dataframe",
    # Backtest
    "run_backtest",
    "BacktestResult",
    # Streaming
    "IBKRWebSocket",
    "LiveQuote",
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
