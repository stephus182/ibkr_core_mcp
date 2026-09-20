import pytest

from ibkr_core_mcp.exceptions import (
    BacktestError,
    BacktestSyntaxError,
    CacheError,
    CacheMissError,
    CacheWriteError,
    ConfigError,
    IBKRAPIError,
    IBKRAuthError,
    IBKRCoreError,
    IBKRRateLimitError,
    StoreError,
)


def test_hierarchy_ibkr_auth_is_core():
    assert issubclass(IBKRAuthError, IBKRCoreError)


def test_hierarchy_rate_limit_is_core():
    assert issubclass(IBKRRateLimitError, IBKRCoreError)


def test_hierarchy_api_error_is_core():
    assert issubclass(IBKRAPIError, IBKRCoreError)


def test_hierarchy_cache_miss_is_cache():
    assert issubclass(CacheMissError, CacheError)
    assert issubclass(CacheError, IBKRCoreError)


def test_hierarchy_cache_write_is_cache():
    assert issubclass(CacheWriteError, CacheError)


def test_hierarchy_store_is_core():
    assert issubclass(StoreError, IBKRCoreError)


def test_hierarchy_backtest_syntax_is_backtest():
    assert issubclass(BacktestSyntaxError, BacktestError)
    assert issubclass(BacktestError, IBKRCoreError)


def test_hierarchy_config_is_core():
    assert issubclass(ConfigError, IBKRCoreError)


def test_api_error_carries_status_code():
    err = IBKRAPIError("bad request", status_code=400)
    assert err.status_code == 400
    assert "bad request" in str(err)


def test_rate_limit_error_carries_status_code_like_api_error():
    """`with_retry` raises one class for 429 and 503; the tool layer needs to tell them apart
    (a 429 is a fifteen-minute penalty box, a 503 is the gateway being down). 0 when unknown,
    so callers can branch without it ever being None — the same contract as `IBKRAPIError`."""
    assert IBKRRateLimitError("x", status_code=429).status_code == 429
    assert IBKRRateLimitError("x").status_code == 0
    assert "x" in str(IBKRRateLimitError("x", status_code=503))


def test_catch_all_via_base():
    with pytest.raises(IBKRCoreError):
        raise IBKRAuthError("session expired")
