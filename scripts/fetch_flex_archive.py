#!/usr/bin/env python3
"""Download the Flex XML archive from Google Drive to a local working directory.

Drive holds the archive in two places, both read here:

    account_data/                 automated Flex syncs (flex_U*.xml)
    account_data/Flex_Archive/    historical statements pulled from the website

This script is strictly **read-only against Drive**. It never uploads, renames or
deletes. It writes a local working copy plus a SHA-256 manifest so the audit and
rebuild steps run against a fixed, verifiable set of bytes.

On IBKR retention: the Flex Queries page says saved queries are "available for the
four previous calendar years and from the start of the current calendar year"
(https://www.ibkrguides.com/clientportal/performanceandstatements/flex.htm). That
sentence describes saved *query template* retention, not data retention — 2020 and
2021 statements were successfully re-pulled on 2026-08-04 and parsed byte-equivalent
to the archived copies. So the archive is prudent redundancy, not the only copy.

Usage:
    python scripts/fetch_flex_archive.py [--dest ~/.ibkr_core/flex_archive] [--force]
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
from pathlib import Path
from typing import Any

DEFAULT_DEST = Path.home() / ".ibkr_core" / "flex_archive"
MANIFEST_NAME = "_manifest.json"


def _load_dotenv(path: Path) -> None:
    """Populate os.environ from a .env file without overriding existing values."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _cache() -> Any:
    """Return a GDriveCache using ibkr_core_mcp's own auth."""
    from ibkr_core_mcp import Config
    from ibkr_core_mcp.cache import GDriveCache

    return GDriveCache(Config.from_env())


def fetch(dest: Path, *, force: bool = False) -> list[dict[str, Any]]:
    """Download every .xml under Drive account_data/ to dest. Returns manifest entries.

    Uses GDriveCache.list_account_files, which walks subfolders. A single-level listing
    here would quietly skip account_data/Flex_Archive/ and produce a manifest covering
    only the automated syncs — which is precisely what happened once.
    """
    from googleapiclient.http import MediaIoBaseDownload

    cache = _cache()
    service = cache._get_service()
    dest.mkdir(parents=True, exist_ok=True)

    remote_files = cache.list_account_files(".xml")
    if not remote_files:
        raise SystemExit("No .xml files found under account_data/ on Drive")

    manifest: list[dict[str, Any]] = []
    for meta in remote_files:
        target = dest / meta["name"]
        if target.exists() and not force:
            payload = target.read_bytes()
            action = "cached"
        else:
            buffer = io.BytesIO()
            downloader = MediaIoBaseDownload(buffer, service.files().get_media(fileId=meta["id"]))
            done = False
            while not done:
                _, done = downloader.next_chunk()
            payload = buffer.getvalue()
            target.write_bytes(payload)
            action = "downloaded"

        digest = hashlib.sha256(payload).hexdigest()
        manifest.append(
            {
                "name": meta["name"],
                "drive_id": meta["id"],
                "bytes": len(payload),
                "sha256": digest,
                "drive_modified": meta.get("modifiedTime", ""),
            }
        )
        print(f"  {action:<11} {len(payload):>9,} B  {digest[:12]}  {meta['name']}")

    (dest / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    parser.add_argument("--force", action="store_true", help="re-download even if present")
    parser.add_argument("--env", type=Path, default=Path.cwd() / ".env")
    args = parser.parse_args(argv)

    _load_dotenv(args.env)
    print(f"Fetching Flex archive → {args.dest}")
    manifest = fetch(args.dest, force=args.force)
    total = sum(entry["bytes"] for entry in manifest)
    print(f"\n{len(manifest)} files, {total:,} bytes. Manifest: {args.dest / MANIFEST_NAME}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
