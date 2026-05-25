"""ibkr_core_mcp — IBKR Client Portal API package."""

from ibkr_core_mcp.config import Config
from ibkr_core_mcp.exceptions import (
    IBKRCoreError,
    IBKRAuthError,
    IBKRRateLimitError,
    IBKRAPIError,
    CacheError,
    CacheMissError,
    CacheWriteError,
    StoreError,
    BacktestError,
    BacktestSyntaxError,
    BacktestRuntimeError,
    ConfigError,
    HumanAuthError,
)
from ibkr_core_mcp.auth import BrowserCookieAuth, TokenAuth, NoAuth
from ibkr_core_mcp.client import IBKRClient
from ibkr_core_mcp.cache import GDriveCache
from ibkr_core_mcp.store import SQLiteStore
from ibkr_core_mcp.claude_tools import ClaudeToolkit
from ibkr_core_mcp.models import (
    Contract,
    Position,
    Trade,
    Order,
    AccountSummary,
    Notification,
    bars_to_dataframe,
)
from ibkr_core_mcp.backtest import run_backtest, BacktestResult
from ibkr_core_mcp import indicators
from ibkr_core_mcp import analytics
from ibkr_core_mcp import pinescript

__version__ = "0.2.0"
__all__ = [
    # Core
    "Config",
    "IBKRClient",
    "GDriveCache",
    "SQLiteStore",
    "ClaudeToolkit",
    # Auth
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
]
