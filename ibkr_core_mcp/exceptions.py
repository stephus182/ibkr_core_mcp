class IBKRCoreError(Exception):
    """Base exception for all ibkr_core_mcp errors."""


class IBKRAuthError(IBKRCoreError):
    """Session not authenticated or cookie extraction failed."""


class IBKRRateLimitError(IBKRCoreError):
    """Gateway returned 429 and retries exhausted."""


class IBKRAPIError(IBKRCoreError):
    """Non-auth HTTP error from the IBKR gateway."""

    def __init__(self, message: str, status_code: int = 0) -> None:
        super().__init__(message)
        self.status_code = status_code


class CacheError(IBKRCoreError):
    """Base cache error."""


class CacheMissError(CacheError):
    """Requested data not in Drive cache."""


class CacheWriteError(CacheError):
    """Failed to write to Drive cache."""


class StoreError(IBKRCoreError):
    """SQLite store error."""


class BacktestError(IBKRCoreError):
    """Base backtest error."""


class BacktestSyntaxError(BacktestError):
    """Strategy code has a syntax error."""


class BacktestRuntimeError(BacktestError):
    """Strategy code raised an exception at runtime."""


class ConfigError(IBKRCoreError):
    """Missing or invalid configuration."""


class HumanAuthError(IBKRCoreError):
    """Raised when Touch ID is denied, times out, unavailable, or the user cancels the confirmation dialog."""


class FlexQueryError(IBKRCoreError):
    """Raised when a Flex Query request fails, times out, or returns unexpected XML."""
