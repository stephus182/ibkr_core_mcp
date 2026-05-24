import pytest
import pandas as pd
import numpy as np
from unittest.mock import patch, MagicMock
from datetime import date, timedelta


@pytest.fixture
def cache(mock_config):
    from ibkr_core_mcp.cache import GDriveCache
    c = GDriveCache.__new__(GDriveCache)
    c._config = mock_config
    c._service = MagicMock()
    c._manifest = {}
    c._manifest_loaded_at = 0.0
    return c


def test_cache_key_format(cache):
    key = cache._cache_key("aapl", "1d", "1Y", "2026-05-22")
    assert key == "AAPL_1D_1Y_2026-05-22"


def test_check_returns_false_on_miss(cache):
    cache._manifest = {}
    cache._manifest_loaded_at = float("inf")  # bypass TTL
    assert cache.check("AAPL", "1D", "1Y", "2026-05-22") is False


def test_check_returns_true_on_hit(cache):
    cache._manifest = {
        "AAPL_1D_1Y_2026-05-22": {
            "end": "2026-05-22",
            "rows": 252,
        }
    }
    cache._manifest_loaded_at = float("inf")
    assert cache.check("AAPL", "1D", "1Y", "2026-05-22") is True


def test_check_stale_today_end(cache):
    two_days_ago = str(date.today() - timedelta(days=2))
    cache._manifest = {
        f"AAPL_1D_1Y_{date.today()}": {
            "end": two_days_ago,
            "rows": 252,
        }
    }
    cache._manifest_loaded_at = float("inf")
    result = cache.check("AAPL", "1D", "1Y", str(date.today()))
    assert result is False  # stale — cached_end < today - 1


def test_list_cached_returns_keys(cache):
    cache._manifest = {
        "AAPL_1D_1Y_2026-05-22": {"symbol": "AAPL", "rows": 252},
        "TSLA_1D_6M_2026-05-22": {"symbol": "TSLA", "rows": 126},
    }
    cache._manifest_loaded_at = float("inf")
    entries = cache.list_cached()
    assert len(entries) == 2
