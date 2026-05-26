from __future__ import annotations
import io
import json
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

from ibkr_core_mcp.config import Config
from ibkr_core_mcp.exceptions import CacheMissError, CacheWriteError

_SCOPES = ["https://www.googleapis.com/auth/drive.file"]
_MANIFEST_NAME = "manifest.json"
_MANIFEST_TTL = 60.0


class GDriveCache:
    """Google Drive parquet cache for OHLCV market data."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._service: Any = None
        self._manifest: dict = {}
        self._manifest_loaded_at: float = 0.0

    def _get_service(self) -> Any:
        if self._service:
            return self._service
        creds = None
        if self._config.gdrive_token_file.exists():
            creds = Credentials.from_authorized_user_file(
                str(self._config.gdrive_token_file), _SCOPES
            )
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self._config.gdrive_credentials_file), _SCOPES
                )
                creds = flow.run_local_server(port=0)
            self._config.gdrive_token_file.parent.mkdir(parents=True, exist_ok=True)
            self._config.gdrive_token_file.write_text(creds.to_json())
            os.chmod(self._config.gdrive_token_file, 0o600)
        self._service = build("drive", "v3", credentials=creds)
        return self._service

    def _cache_key(self, symbol: str, timeframe: str, period: str, end: str) -> str:
        return f"{symbol.upper()}_{timeframe.upper()}_{period}_{end}"

    def _filename(self, key: str) -> str:
        return f"{key}.parquet"

    def _load_manifest(self) -> dict:
        now = time.monotonic()
        if self._manifest_loaded_at > 0 and (now - self._manifest_loaded_at) < _MANIFEST_TTL:
            return self._manifest
        svc = self._get_service()
        folder_id = self._config.gdrive_folder_id
        results = (
            svc.files()
            .list(
                q=f"name='{_MANIFEST_NAME}' and '{folder_id}' in parents and trashed=false",
                fields="files(id)",
            )
            .execute()
        )
        files = results.get("files", [])
        if not files:
            self._manifest = {}
            self._manifest_loaded_at = time.monotonic()
            return self._manifest
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, svc.files().get_media(fileId=files[0]["id"]))
        done = False
        while not done:
            _, done = downloader.next_chunk()
        self._manifest = json.loads(buf.getvalue())
        self._manifest_loaded_at = time.monotonic()
        return self._manifest

    def _save_manifest(self) -> None:
        svc = self._get_service()
        folder_id = self._config.gdrive_folder_id
        data = json.dumps(self._manifest, indent=2).encode()
        buf = io.BytesIO(data)
        media = MediaIoBaseUpload(buf, mimetype="application/json")
        results = (
            svc.files()
            .list(
                q=f"name='{_MANIFEST_NAME}' and '{folder_id}' in parents and trashed=false",
                fields="files(id)",
            )
            .execute()
        )
        files = results.get("files", [])
        if files:
            svc.files().update(fileId=files[0]["id"], media_body=media).execute()
        else:
            metadata = {"name": _MANIFEST_NAME, "parents": [folder_id]}
            svc.files().create(body=metadata, media_body=media, fields="id").execute()

    def check(self, symbol: str, timeframe: str, period: str, end: str) -> bool:
        """Return True if a fresh cached file exists for this key."""
        manifest = self._load_manifest()
        key = self._cache_key(symbol, timeframe, period, end)
        entry = manifest.get(key)
        if not entry:
            return False
        cached_end = datetime.strptime(entry["end"], "%Y-%m-%d").date()
        today = date.today()
        if end in ("today", str(today)):
            return cached_end >= today - timedelta(days=1)
        return True

    def load(self, symbol: str, timeframe: str, period: str, end: str) -> pd.DataFrame:
        """Download and return cached parquet as DataFrame."""
        key = self._cache_key(symbol, timeframe, period, end)
        fname = self._filename(key)
        svc = self._get_service()
        folder_id = self._config.gdrive_folder_id
        results = (
            svc.files()
            .list(
                q=f"name='{fname}' and '{folder_id}' in parents and trashed=false",
                fields="files(id)",
            )
            .execute()
        )
        files = results.get("files", [])
        if not files:
            raise CacheMissError(f"No cached file for {key}")
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, svc.files().get_media(fileId=files[0]["id"]))
        done = False
        while not done:
            _, done = downloader.next_chunk()
        buf.seek(0)
        return pd.read_parquet(buf)

    def save(
        self, df: pd.DataFrame, symbol: str, timeframe: str, period: str, end: str
    ) -> None:
        """Upload DataFrame as parquet to Drive and update manifest."""
        key = self._cache_key(symbol, timeframe, period, end)
        fname = self._filename(key)
        svc = self._get_service()
        folder_id = self._config.gdrive_folder_id
        buf = io.BytesIO()
        df.to_parquet(buf, index=True)
        buf.seek(0)
        media = MediaIoBaseUpload(buf, mimetype="application/octet-stream")
        results = (
            svc.files()
            .list(
                q=f"name='{fname}' and '{folder_id}' in parents and trashed=false",
                fields="files(id)",
            )
            .execute()
        )
        existing = results.get("files", [])
        try:
            if existing:
                svc.files().update(fileId=existing[0]["id"], media_body=media).execute()
            else:
                metadata = {"name": fname, "parents": [folder_id]}
                svc.files().create(body=metadata, media_body=media, fields="id").execute()
        except Exception as e:
            raise CacheWriteError(f"Failed to write {fname} to Drive: {e}") from e

        self._load_manifest()
        self._manifest[key] = {
            "symbol": symbol.upper(),
            "timeframe": timeframe.upper(),
            "period": period,
            "end": end if end != "today" else str(date.today()),
            "rows": len(df),
            "cached_at": datetime.now(tz=timezone.utc).isoformat(),
        }
        self._save_manifest()

    def list_cached(self) -> list[dict]:
        """Return list of all manifest entries."""
        manifest = self._load_manifest()
        return [{"key": k, **v} for k, v in manifest.items()]

    def delete(self, symbol: str, timeframe: str, period: str, end: str) -> None:
        """Remove a cached file and its manifest entry."""
        key = self._cache_key(symbol, timeframe, period, end)
        fname = self._filename(key)
        svc = self._get_service()
        folder_id = self._config.gdrive_folder_id
        results = (
            svc.files()
            .list(
                q=f"name='{fname}' and '{folder_id}' in parents and trashed=false",
                fields="files(id)",
            )
            .execute()
        )
        for f in results.get("files", []):
            svc.files().delete(fileId=f["id"]).execute()
        self._load_manifest()
        self._manifest.pop(key, None)
        self._save_manifest()
