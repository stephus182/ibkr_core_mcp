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
)
from ibkr_core_mcp.auth import BrowserCookieAuth, TokenAuth, NoAuth
from ibkr_core_mcp.client import IBKRClient
from ibkr_core_mcp.cache import GDriveCache
from ibkr_core_mcp.store import SQLiteStore
from ibkr_core_mcp.claude_tools import ClaudeToolkit

__version__ = "0.1.0"
__all__ = [
    "Config",
    "IBKRClient",
    "GDriveCache",
    "SQLiteStore",
    "ClaudeToolkit",
    "BrowserCookieAuth",
    "TokenAuth",
    "NoAuth",
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
]
