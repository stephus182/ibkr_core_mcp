import io
from datetime import date, timedelta
from unittest.mock import MagicMock, call, patch

import pandas as pd
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


# ── Drive-path fixture helpers ────────────────────────────────────────────────

def _make_parquet_bytes(df: pd.DataFrame) -> bytes:
    """Serialize a DataFrame to parquet bytes (used to fake Drive downloads)."""
    buf = io.BytesIO()
    df.to_parquet(buf, index=True)
    return buf.getvalue()


@pytest.fixture
def drive_cache(cache):
    """GDriveCache with a pre-resolved cache folder so _resolve_cache_folder()
    returns immediately without hitting Drive."""
    cache._config.gdrive_cache_folder_id = "cache-folder-id"
    cache._resolved_cache_folder = "cache-folder-id"
    # Freeze manifest so load/save/delete won't try to re-load it from Drive.
    cache._manifest_loaded_at = float("inf")
    return cache


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


# ── Drive API call paths: load() ──────────────────────────────────────────────

def test_load_happy_path_returns_dataframe(drive_cache):
    """load() downloads parquet bytes via MediaIoBaseDownload and returns a DataFrame."""
    from ibkr_core_mcp.exceptions import CacheMissError

    expected_df = pd.DataFrame({"close": [100.0, 101.0, 102.0]})
    parquet_bytes = _make_parquet_bytes(expected_df)

    svc = drive_cache._service
    # files().list().execute() returns one matching file
    svc.files().list().execute.return_value = {"files": [{"id": "file-abc123"}]}

    def fake_download(buf, request):
        buf.write(parquet_bytes)
        buf.seek(0)
        m = MagicMock()
        m.next_chunk.return_value = (None, True)
        return m

    with patch("ibkr_core_mcp.cache.MediaIoBaseDownload", side_effect=fake_download):
        result = drive_cache.load("AAPL", "1D", "1Y", "2026-05-22")

    assert isinstance(result, pd.DataFrame)
    assert result.shape == expected_df.shape
    assert list(result.columns) == ["close"]


def test_load_miss_raises_cache_miss_error(drive_cache):
    """load() raises CacheMissError when files().list() returns no files."""
    from ibkr_core_mcp.exceptions import CacheMissError

    drive_cache._service.files().list().execute.return_value = {"files": []}

    with pytest.raises(CacheMissError, match="No cached file for AAPL_1D_1Y_2026-05-22"):
        drive_cache.load("AAPL", "1D", "1Y", "2026-05-22")


def test_load_drive_error_raises_cache_miss_error(drive_cache):
    """load() raises CacheMissError when Drive raises an exception (folder unavailable)."""
    from ibkr_core_mcp.exceptions import CacheMissError

    drive_cache._service.files().list().execute.side_effect = Exception("Drive unavailable")

    with pytest.raises(CacheMissError, match="Drive folder unavailable"):
        drive_cache.load("AAPL", "1D", "1Y", "2026-05-22")


def test_load_drive_error_resets_cache_folder(drive_cache):
    """load() resets _resolved_cache_folder when a Drive exception occurs."""
    drive_cache._service.files().list().execute.side_effect = Exception("Drive gone")
    drive_cache._resolved_cache_folder = "old-folder-id"

    import contextlib
    with contextlib.suppress(Exception):
        drive_cache.load("AAPL", "1D", "1Y", "2026-05-22")

    assert drive_cache._resolved_cache_folder == ""


# ── Drive API call paths: save() ──────────────────────────────────────────────

def test_save_creates_new_file_when_none_exists(drive_cache):
    """save() calls files().create() when no existing parquet file is found."""
    svc = drive_cache._service
    # First list call: no existing parquet file
    # Second list call (inside _save_manifest): no existing manifest
    svc.files().list().execute.return_value = {"files": []}
    svc.files().create().execute.return_value = {"id": "new-file-id"}

    df = pd.DataFrame({"close": [100.0, 101.0]})
    drive_cache.save(df, "AAPL", "1D", "1Y", "2026-05-22")

    # create() must have been called (for the parquet file and/or manifest)
    svc.files().create.assert_called()
    # update() must NOT have been called for the data file
    # (MagicMock records calls; we check update was not used for data)
    update_calls = svc.files().update.call_args_list
    # The update call has fileId kwarg — if it was called for an existing parquet,
    # it would include the old file id. Since list returned empty, no update expected.
    data_updates = [c for c in update_calls if c.kwargs.get("fileId") == "existing-file-id"]
    assert not data_updates


def test_save_updates_existing_file_when_found(drive_cache):
    """save() calls files().update() when a parquet file already exists in Drive."""
    svc = drive_cache._service
    # First list call: existing parquet file found
    # Second list call (_save_manifest): no existing manifest → create manifest
    svc.files().list().execute.side_effect = [
        {"files": [{"id": "existing-parquet-id"}]},  # parquet search
        {"files": []},                                 # manifest search
    ]
    svc.files().update().execute.return_value = {}
    svc.files().create().execute.return_value = {"id": "manifest-id"}

    df = pd.DataFrame({"close": [100.0, 101.0]})
    drive_cache.save(df, "AAPL", "1D", "1Y", "2026-05-22")

    # update() must have been called with the existing file id
    update_call_kwargs = [c.kwargs for c in svc.files().update.call_args_list]
    file_ids_updated = [kw.get("fileId") for kw in update_call_kwargs]
    assert "existing-parquet-id" in file_ids_updated


def test_save_raises_cache_write_error_on_drive_failure(drive_cache):
    """save() raises CacheWriteError when the Drive upload fails."""
    from ibkr_core_mcp.exceptions import CacheWriteError

    svc = drive_cache._service
    # No existing file — will try create
    svc.files().list().execute.return_value = {"files": []}
    svc.files().create().execute.side_effect = Exception("Network error")

    df = pd.DataFrame({"close": [100.0]})
    with pytest.raises(CacheWriteError, match="Failed to write"):
        drive_cache.save(df, "AAPL", "1D", "1Y", "2026-05-22")


def test_save_updates_manifest_entry(drive_cache):
    """save() writes symbol/timeframe/period/end/rows into the in-memory manifest."""
    svc = drive_cache._service
    svc.files().list().execute.return_value = {"files": []}
    svc.files().create().execute.return_value = {"id": "new-id"}

    df = pd.DataFrame({"close": [1.0, 2.0, 3.0]})
    drive_cache.save(df, "AAPL", "1D", "1Y", "2026-05-22")

    entry = drive_cache._manifest.get("AAPL_1D_1Y_2026-05-22")
    assert entry is not None
    assert entry["symbol"] == "AAPL"
    assert entry["rows"] == 3
    assert entry["end"] == "2026-05-22"


# ── Drive API call paths: delete() ───────────────────────────────────────────

def test_delete_calls_files_delete_when_file_found(drive_cache):
    """delete() calls files().delete() when the parquet file exists in Drive."""
    svc = drive_cache._service
    # First list: parquet file found
    # Second list (_save_manifest): no manifest
    svc.files().list().execute.side_effect = [
        {"files": [{"id": "parquet-to-delete"}]},
        {"files": []},
    ]
    svc.files().create().execute.return_value = {"id": "manifest-id"}

    drive_cache.delete("AAPL", "1D", "1Y", "2026-05-22")

    delete_call_kwargs = [c.kwargs for c in svc.files().delete.call_args_list]
    deleted_ids = [kw.get("fileId") for kw in delete_call_kwargs]
    assert "parquet-to-delete" in deleted_ids


def test_delete_no_drive_call_when_file_not_found(drive_cache):
    """delete() does not call files().delete() when no parquet file exists."""
    svc = drive_cache._service
    # First list: no parquet file
    # Second list (_save_manifest): no manifest
    svc.files().list().execute.side_effect = [
        {"files": []},
        {"files": []},
    ]
    svc.files().create().execute.return_value = {"id": "manifest-id"}

    drive_cache.delete("AAPL", "1D", "1Y", "2026-05-22")

    svc.files().delete.assert_not_called()


def test_delete_removes_manifest_entry(drive_cache):
    """delete() removes the key from the in-memory manifest."""
    svc = drive_cache._service
    drive_cache._manifest["AAPL_1D_1Y_2026-05-22"] = {
        "symbol": "AAPL", "rows": 252, "end": "2026-05-22"
    }
    svc.files().list().execute.side_effect = [
        {"files": [{"id": "parquet-id"}]},
        {"files": []},
    ]
    svc.files().create().execute.return_value = {"id": "manifest-id"}

    drive_cache.delete("AAPL", "1D", "1Y", "2026-05-22")

    assert "AAPL_1D_1Y_2026-05-22" not in drive_cache._manifest


def test_delete_no_error_when_file_not_found(drive_cache):
    """delete() does not raise when the parquet file does not exist in Drive."""
    svc = drive_cache._service
    svc.files().list().execute.side_effect = [
        {"files": []},
        {"files": []},
    ]
    svc.files().create().execute.return_value = {"id": "manifest-id"}

    # Must not raise
    drive_cache.delete("TSLA", "1H", "3M", "2026-01-15")
