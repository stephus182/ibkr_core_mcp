"""Tests for gdrive_auth — shared Drive OAuth credential load/refresh/persist logic.

Shared by ibkr_core_mcp's GDriveCache and claudia_ui's GDriveSync. See
docs/plans/2026-07-10-gdrive-auth-dedup-design.md (claudia_ui repo) for why
this module exists.
"""

import os
import stat
from pathlib import Path
from unittest.mock import MagicMock, patch

from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials

from ibkr_core_mcp.gdrive_auth import load_or_refresh_credentials, persist_credentials

_SCOPES = ["https://www.googleapis.com/auth/drive"]


def test_load_or_refresh_returns_none_when_file_missing(tmp_path):
    token_file = tmp_path / "token.json"
    result = load_or_refresh_credentials(token_file, _SCOPES)
    assert result is None


def test_load_or_refresh_returns_valid_credentials_unchanged(tmp_path):
    token_file = tmp_path / "token.json"
    token_file.write_text('{"existing": "token"}')

    mock_creds = MagicMock()
    mock_creds.valid = True

    with (
        patch(
            "ibkr_core_mcp.gdrive_auth.Credentials.from_authorized_user_file",
            return_value=mock_creds,
        ),
        patch("ibkr_core_mcp.gdrive_auth.Request") as mock_request,
    ):
        result = load_or_refresh_credentials(token_file, _SCOPES)

    assert result is mock_creds
    mock_request.assert_not_called()
    mock_creds.refresh.assert_not_called()
    # File is untouched — valid credentials are never rewritten.
    assert token_file.read_text() == '{"existing": "token"}'


def test_load_or_refresh_refreshes_and_persists_expired_credentials(tmp_path):
    token_file = tmp_path / "token.json"
    token_file.write_text('{"existing": "token"}')

    mock_creds = MagicMock()
    mock_creds.valid = False
    mock_creds.expired = True
    mock_creds.refresh_token = "rt"
    mock_creds.to_json.return_value = '{"refreshed": true}'

    with (
        patch(
            "ibkr_core_mcp.gdrive_auth.Credentials.from_authorized_user_file",
            return_value=mock_creds,
        ),
        patch("ibkr_core_mcp.gdrive_auth.Request"),
    ):
        result = load_or_refresh_credentials(token_file, _SCOPES)

    assert result is mock_creds
    mock_creds.refresh.assert_called_once()
    assert token_file.read_text() == '{"refreshed": true}'


def test_load_or_refresh_returns_none_when_expired_and_unrefreshable(tmp_path):
    token_file = tmp_path / "token.json"
    token_file.write_text('{"existing": "token"}')

    mock_creds = MagicMock()
    mock_creds.valid = False
    mock_creds.expired = True
    mock_creds.refresh_token = None

    with patch(
        "ibkr_core_mcp.gdrive_auth.Credentials.from_authorized_user_file",
        return_value=mock_creds,
    ):
        result = load_or_refresh_credentials(token_file, _SCOPES)

    assert result is None
    # No refresh attempted, nothing persisted — file untouched.
    assert token_file.read_text() == '{"existing": "token"}'


def test_load_or_refresh_returns_none_when_refresh_fails(tmp_path):
    token_file = tmp_path / "token.json"
    token_file.write_text('{"existing": "token"}')

    mock_creds = MagicMock()
    mock_creds.valid = False
    mock_creds.expired = True
    mock_creds.refresh_token = "rt"
    mock_creds.refresh.side_effect = RefreshError("invalid_grant: token revoked")

    with (
        patch(
            "ibkr_core_mcp.gdrive_auth.Credentials.from_authorized_user_file",
            return_value=mock_creds,
        ),
        patch("ibkr_core_mcp.gdrive_auth.Request"),
    ):
        result = load_or_refresh_credentials(token_file, _SCOPES)

    assert result is None
    # A failed refresh must not be persisted — the stale token file is left untouched.
    assert token_file.read_text() == '{"existing": "token"}'


def test_persist_credentials_writes_json_with_restricted_permissions(tmp_path):
    token_file = tmp_path / "token.json"
    mock_creds = MagicMock()
    mock_creds.to_json.return_value = '{"token": "value"}'

    persist_credentials(token_file, mock_creds)

    assert token_file.read_text() == '{"token": "value"}'
    mode = stat.S_IMODE(os.stat(token_file).st_mode)
    assert mode == 0o600


def test_persist_credentials_enforces_permissions_on_preexisting_file(tmp_path):
    token_file = tmp_path / "token.json"
    token_file.write_text("{}")
    os.chmod(token_file, 0o644)  # simulate a pre-existing file with loose permissions

    mock_creds = MagicMock()
    mock_creds.to_json.return_value = '{"token": "value"}'

    persist_credentials(token_file, mock_creds)

    mode = stat.S_IMODE(os.stat(token_file).st_mode)
    assert mode == 0o600


def test_persist_credentials_creates_parent_directory(tmp_path):
    token_file = tmp_path / "nested" / "dir" / "token.json"
    mock_creds = MagicMock()
    mock_creds.to_json.return_value = '{"token": "value"}'

    persist_credentials(token_file, mock_creds)

    assert token_file.read_text() == '{"token": "value"}'


# ── One connection per request (register F17) ────────────────────────────────


def test_every_drive_request_gets_its_own_connection():
    """httplib2 is not thread-safe, and Google's rule is one `httplib2.Http` per thread
    (https://googleapis.github.io/google-api-python-client/docs/thread_safety.html). One shared
    connection aborted a host's process on 2026-09-23 (claudia_ui gap #61). The real `build()`,
    offline: this is Google's request path, not a mock."""
    import httplib2

    from ibkr_core_mcp.gdrive_auth import build_drive_service

    creds = Credentials(token="test-token")
    service = build_drive_service(creds)
    first = service.files().list(pageSize=1, fields="files(id)")
    second = service.files().list(pageSize=1, fields="files(id)")

    assert isinstance(first.http.http, httplib2.Http)
    assert first.http.http is not second.http.http
    assert first.http.credentials is creds


def test_the_drive_service_is_built_in_one_place():
    """Every Drive client in the package goes through `build_drive_service`: a module that
    calls Google's `build` itself would share one connection again."""
    package = Path(__file__).resolve().parents[1] / "ibkr_core_mcp"
    builders = sorted(p.name for p in package.glob("*.py") if "googleapiclient.discovery" in p.read_text())
    assert builders == ["gdrive_auth.py"]
