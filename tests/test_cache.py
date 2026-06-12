from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest


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


# ── CA-02: token file permissions ─────────────────────────────────────────────

def test_token_file_created_with_restricted_permissions(tmp_path):
    import os
    import stat
    from unittest.mock import MagicMock

    from ibkr_core_mcp.cache import GDriveCache

    token_file = tmp_path / "token.json"
    token_file.write_text('{"existing": "token"}')

    cfg = MagicMock()
    cfg.gdrive_folder_id = "folder123"
    cfg.gdrive_token_file = token_file
    cfg.gdrive_credentials_file = tmp_path / "creds.json"

    fake_creds = MagicMock()
    fake_creds.valid = False
    fake_creds.expired = True
    fake_creds.refresh_token = "refresh_token_value"
    fake_creds.to_json.return_value = '{"token": "refreshed"}'

    cache = GDriveCache.__new__(GDriveCache)
    cache._config = cfg
    cache._service = None
    cache._manifest = {}
    cache._manifest_loaded_at = 0.0

    with patch("ibkr_core_mcp.cache.Credentials.from_authorized_user_file", return_value=fake_creds), \
         patch("ibkr_core_mcp.cache.Request"), \
         patch("ibkr_core_mcp.cache.build") as mock_build:
        mock_build.return_value = MagicMock()
        cache._get_service()

    mode = stat.S_IMODE(os.stat(token_file).st_mode)
    assert mode == 0o600, f"Expected 0o600, got {oct(mode)}"


# ── CA-06: cache key input validation ─────────────────────────────────────────

def test_cache_key_rejects_underscore_in_symbol(cache):
    from ibkr_core_mcp.exceptions import CacheError
    with pytest.raises(CacheError, match="symbol"):
        cache.check("AAPL_1D", "1D", "1Y", "2026-01-01")


def test_cache_key_rejects_empty_symbol(cache):
    from ibkr_core_mcp.exceptions import CacheError
    with pytest.raises(CacheError, match="symbol"):
        cache.check("", "1D", "1Y", "2026-01-01")


def test_cache_key_accepts_valid_inputs(cache):
    cache._manifest_loaded_at = float("inf")
    result = cache.check("AAPL", "1D", "1Y", "2026-01-01")
    assert result is False  # cache miss is fine, no error


# ── C-02: folder_id validation ────────────────────────────────────────────────

def test_get_service_raises_on_empty_folder_id(tmp_path):
    from unittest.mock import MagicMock

    from ibkr_core_mcp.cache import GDriveCache
    from ibkr_core_mcp.exceptions import CacheError

    token_file = tmp_path / "token.json"
    token_file.write_text('{}')

    cfg = MagicMock()
    cfg.gdrive_folder_id = ""
    cfg.gdrive_cache_folder_id = ""
    cfg.gdrive_token_file = token_file
    cfg.gdrive_credentials_file = tmp_path / "creds.json"

    fake_creds = MagicMock()
    fake_creds.valid = True

    cache = GDriveCache.__new__(GDriveCache)
    cache._config = cfg
    cache._service = None
    cache._manifest = {}
    cache._manifest_loaded_at = 0.0
    cache._resolved_cache_folder = ""

    with patch("ibkr_core_mcp.cache.Credentials.from_authorized_user_file", return_value=fake_creds), \
         patch("ibkr_core_mcp.cache.build") as mock_build:
        mock_build.return_value = MagicMock()
        with pytest.raises(CacheError, match="GOOGLE_DRIVE_FOLDER_ID"):
            cache._get_service()
