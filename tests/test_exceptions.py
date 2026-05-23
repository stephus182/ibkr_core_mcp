import pytest

from ibkr_core_mcp.exceptions import (
    IBKRCoreError, IBKRAuthError, IBKRRateLimitError, IBKRAPIError,
    CacheError, CacheMissError, CacheWriteError,
    StoreError, BacktestError, BacktestSyntaxError, BacktestRuntimeError,
    ConfigError,
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


def test_catch_all_via_base():
    with pytest.raises(IBKRCoreError):
        raise IBKRAuthError("session expired")
