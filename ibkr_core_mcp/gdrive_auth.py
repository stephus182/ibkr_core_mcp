"""Shared Google Drive OAuth credential loading, refresh, and persistence.

Used by both ibkr_core_mcp.cache.GDriveCache and claudia_ui's claudia.gdrive_sync.GDriveSync
so there is exactly one implementation of "how do we load/refresh a Drive token." Before
this module existed, both classes independently reimplemented the same ~15 lines of
Credentials-loading/refresh/persist logic — see
docs/superpowers/specs/2026-07-10-gdrive-auth-dedup-design.md (claudia_ui repo) for why
that was extracted.

Source (google-auth credentials): https://google-auth.readthedocs.io/en/stable/reference/google.oauth2.credentials.html
"""
from __future__ import annotations

import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials


def load_or_refresh_credentials(token_file: Path, scopes: list[str]) -> Credentials | None:
    """Load credentials from token_file, refreshing in place if expired but refreshable.

    Returns the credentials unchanged if still valid. If expired but refreshable (has a
    refresh_token), refreshes via google.auth.transport.requests.Request, persists the
    refreshed token via persist_credentials, and returns it. Returns None if the file
    doesn't exist, or if the credentials are expired with no refresh_token — never raises;
    callers decide what "no usable credentials" means for them (interactive bootstrap, or
    a hard error).
    """
    if not token_file.exists():
        return None
    creds = Credentials.from_authorized_user_file(str(token_file), scopes)
    if creds.valid:
        return creds
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        persist_credentials(token_file, creds)
        return creds
    return None


def persist_credentials(token_file: Path, creds: Credentials) -> None:
    """Write creds.to_json() to token_file with mode 0o600.

    Two-step chmod: os.open's O_CREAT mode only applies the permission on file creation,
    not on an existing file, so os.chmod is called unconditionally afterward to enforce
    0o600 regardless of whether the file was created or truncated.
    """
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_path = str(token_file)
    fd = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(creds.to_json())
    os.chmod(token_path, 0o600)
