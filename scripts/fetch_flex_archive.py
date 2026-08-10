#!/usr/bin/env python3
"""Download the Flex XML archive from Google Drive to a local working directory.

Drive holds the archive in two places, both read here:

    account_data/                 automated Flex syncs (flex_U*.xml)
    account_data/Flex_Archive/    historical statements pulled from the website

This script is strictly **read-only against Drive**. It never uploads, renames or
deletes. It writes a local working copy plus a manifest recording the SHA-256 of every
file, each one checked against Drive's own ``md5Checksum`` at fetch time.

That verification is the point, and it did not exist before 2026-08-10: the manifest
hashed whatever bytes were on disk and compared them to nothing, so a truncated or
hand-edited statement produced a manifest that agreed with itself and exited 0. Files
that fail the comparison, and payloads that are not statements at all, are refused —
and no manifest is written on a bad fetch, because rewriting it would record the
corruption as the new truth.

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


class ArchiveFetchError(Exception):
    """A file failed checksum verification, so no manifest was written."""


class ArchiveSkipped(Exception):  # noqa: N818 - a report, not an error condition
    """Some payloads were not statements and were excluded; the manifest was written."""


def _root_tag(payload: bytes) -> str:
    """Root element name of `payload`, or a marker if it is not parseable XML."""
    import defusedxml.ElementTree as ET

    try:
        return str(ET.fromstring(payload.decode("utf-8", errors="replace")).tag)
    except ET.ParseError:
        return "unparseable"


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
    problems: list[str] = []  # corruption — invalidates the whole set
    skipped: list[str] = []  # not statements — excluded, but the rest is still good
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
            action = "downloaded"

        # Refuse the payload before it reaches the archive. IBKR answers a not-yet-ready
        # report with <FlexStatementResponse><ErrorCode>1019</ErrorCode>, and one such
        # 226-byte file sat in the archive for five weeks. `flex_query` now retries that
        # at fetch time, but the old one is still on Drive — and this script is
        # deliberately read-only against Drive, so deleting the local copy is not
        # durable. Refusing it here is what keeps it out permanently.
        root = _root_tag(payload)
        if root != "FlexQueryResponse":
            skipped.append(f"{meta['name']}: root is <{root}>, not a statement — not archived")
            print(f"  {'SKIPPED':<11} {len(payload):>9,} B  {'-' * 12}  {meta['name']}  <{root}>")
            continue

        # Verify against Drive's own checksum rather than against ourselves. Hashing the
        # local bytes and recording the result proves only that the file hashes to its
        # own hash; a truncated or hand-edited statement passed that test every time.
        # md5Checksum is only populated for binary content, so its absence is recorded
        # as unverified rather than assumed good.
        # https://developers.google.com/drive/api/reference/rest/v3/files
        drive_md5 = meta.get("md5Checksum") or ""
        local_md5 = hashlib.md5(payload).hexdigest()  # noqa: S324 - Drive's algorithm, not ours
        verified = bool(drive_md5) and drive_md5 == local_md5
        if drive_md5 and not verified:
            problems.append(
                f"{meta['name']}: local bytes do not match Drive "
                f"(drive md5 {drive_md5[:12]}, local {local_md5[:12]}, {len(payload):,} B)"
            )
            print(f"  {'MISMATCH':<11} {len(payload):>9,} B  {local_md5[:12]}  {meta['name']}")
            continue

        if action == "downloaded":
            target.write_bytes(payload)

        digest = hashlib.sha256(payload).hexdigest()
        manifest.append(
            {
                "name": meta["name"],
                "drive_id": meta["id"],
                "bytes": len(payload),
                "sha256": digest,
                "md5": local_md5,
                "md5_verified": verified,
                "drive_modified": meta.get("modifiedTime", ""),
            }
        )
        flag = "" if verified else "  (unverified: Drive supplied no md5)"
        print(f"  {action:<11} {len(payload):>9,} B  {digest[:12]}  {meta['name']}{flag}")

    if problems:
        # No manifest on a *corrupt* fetch. Rewriting it would bless the corruption as
        # the new truth, which is exactly how the previous version behaved.
        raise ArchiveFetchError("\n".join(problems))

    (dest / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    if skipped:
        # Deliberately not fatal. This script is read-only against Drive, so a payload
        # the owner has not deleted there is a standing condition — refusing the whole
        # fetch over it would make the archive permanently un-refreshable, and a guard
        # people have to work around stops being a guard. It is excluded and reported,
        # and main() still exits non-zero so nothing reads the run as clean.
        raise ArchiveSkipped("\n".join(skipped))
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
    try:
        manifest = fetch(args.dest, force=args.force)
    except ArchiveFetchError as exc:
        print(f"\nREFUSED  the archive was not updated:\n{exc}\n  No manifest was written.")
        return 2
    except ArchiveSkipped as exc:
        print(
            f"\nSKIPPED  payloads that are not statements were excluded:\n{exc}\n"
            "  The remaining files were archived and the manifest was written.\n"
            "  Delete these on Drive to clear this warning — this script never writes there."
        )
        return 1
    total = sum(entry["bytes"] for entry in manifest)
    unverified = sum(1 for entry in manifest if not entry["md5_verified"])
    note = f", {unverified} unverified" if unverified else ", all verified against Drive"
    print(f"\n{len(manifest)} files, {total:,} bytes{note}. Manifest: {args.dest / MANIFEST_NAME}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
