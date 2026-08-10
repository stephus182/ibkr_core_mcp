"""`fetch_flex_archive.py` promised "a fixed, verifiable set of bytes" and verified none.

For a file already on disk it took the `cached` branch, read the **local** bytes, hashed
those, and recorded the digest as truth. It never compared against the previous manifest,
never against Drive, and nothing in the repo ever read the manifest back. A statement
truncated by a disk-full write or edited by hand produced a manifest that agreed with
itself perfectly and exited 0.

The second guard here is not hypothetical either. A 226-byte `ErrorCode 1019` payload was
deleted from the local archive on 2026-08-10 and came straight back on the next fetch,
because Drive still holds it and this script is deliberately read-only against Drive.
Refusing the payload at write time is what makes the archive self-defending.
"""

from __future__ import annotations

import hashlib
import json
from unittest.mock import MagicMock

import fetch_flex_archive
import pytest

from tests.flex_fixtures import WARN_1019_XML, statement, trade

pytestmark = pytest.mark.scripts

GOOD_XML = statement(trade()).encode("utf-8")


def _drive(monkeypatch, files, payloads):
    """Stand in for GDriveCache + the Drive service, returning `payloads` by file id."""
    cache = MagicMock()
    cache.list_account_files.return_value = files

    def get_media(fileId):  # noqa: N803 - matches the googleapiclient signature
        request = MagicMock()
        request._payload = payloads[fileId]
        return request

    cache._get_service.return_value.files.return_value.get_media.side_effect = get_media
    monkeypatch.setattr(fetch_flex_archive, "_cache", lambda: cache)

    class FakeDownloader:
        def __init__(self, buffer, request):
            self._buffer = buffer
            self._request = request

        def next_chunk(self):
            self._buffer.write(self._request._payload)
            return None, True

    monkeypatch.setattr("googleapiclient.http.MediaIoBaseDownload", FakeDownloader, raising=False)
    return cache


def _meta(name, file_id, payload):
    return {
        "id": file_id,
        "name": name,
        "size": str(len(payload)),
        "modifiedTime": "2026-08-06T20:29:53.000Z",
        "md5Checksum": hashlib.md5(payload).hexdigest(),  # noqa: S324 - Drive's own algorithm
    }


# ── the manifest must verify against Drive, not against itself ──────────────────


#: A *valid* statement that simply is not the one Drive holds. Deliberately well-formed:
#: a truncated file is also caught by the root-element guard, so a malformed payload
#: could not show that the checksum comparison itself is doing anything.
EDITED_XML = statement(trade(tradePrice="999.99")).encode("utf-8")


def test_cached_file_is_verified_against_drive_md5(tmp_path, monkeypatch):
    """The `cached` branch is the whole point — it never re-downloads, so it must check."""
    _drive(monkeypatch, [_meta("a.xml", "id1", GOOD_XML)], {"id1": GOOD_XML})
    (tmp_path / "a.xml").write_bytes(EDITED_XML)  # hand-edited on disk, still valid XML

    rc = fetch_flex_archive.main(["--dest", str(tmp_path), "--env", str(tmp_path / "none.env")])

    assert rc == 2


def test_manifest_is_not_written_when_a_file_mismatches(tmp_path, monkeypatch):
    """A manifest recording corrupt bytes as the new truth is worse than none."""
    _drive(monkeypatch, [_meta("a.xml", "id1", GOOD_XML)], {"id1": GOOD_XML})
    (tmp_path / "a.xml").write_bytes(EDITED_XML)

    fetch_flex_archive.main(["--dest", str(tmp_path), "--env", str(tmp_path / "none.env")])

    assert not (tmp_path / "_manifest.json").exists()


def test_a_matching_cached_file_is_accepted(tmp_path, monkeypatch):
    _drive(monkeypatch, [_meta("a.xml", "id1", GOOD_XML)], {"id1": GOOD_XML})
    (tmp_path / "a.xml").write_bytes(GOOD_XML)

    rc = fetch_flex_archive.main(["--dest", str(tmp_path), "--env", str(tmp_path / "none.env")])

    assert rc == 0
    entry = json.loads((tmp_path / "_manifest.json").read_text())[0]
    assert entry["md5_verified"] is True


def test_a_download_is_verified_too(tmp_path, monkeypatch):
    """Drive metadata disagreeing with Drive's own bytes must not pass silently."""
    files = [_meta("a.xml", "id1", GOOD_XML)]
    files[0]["md5Checksum"] = "0" * 32
    _drive(monkeypatch, files, {"id1": GOOD_XML})

    rc = fetch_flex_archive.main(["--dest", str(tmp_path), "--env", str(tmp_path / "none.env")])

    assert rc == 2


def test_missing_drive_md5_is_reported_not_assumed_good(tmp_path, monkeypatch):
    """md5Checksum is absent for non-binary Drive types; that is unverified, not verified."""
    files = [_meta("a.xml", "id1", GOOD_XML)]
    del files[0]["md5Checksum"]
    _drive(monkeypatch, files, {"id1": GOOD_XML})

    rc = fetch_flex_archive.main(["--dest", str(tmp_path), "--env", str(tmp_path / "none.env")])

    assert rc == 0
    entry = json.loads((tmp_path / "_manifest.json").read_text())[0]
    assert entry["md5_verified"] is False


# ── error payloads must never enter the archive ─────────────────────────────────


def test_refuses_to_archive_a_non_flexqueryresponse_payload(tmp_path, monkeypatch):
    """Deleting the 1019 fossil locally is not durable while Drive still serves it."""
    payload = WARN_1019_XML.encode("utf-8")
    _drive(monkeypatch, [_meta("err.xml", "id1", payload)], {"id1": payload})

    rc = fetch_flex_archive.main(["--dest", str(tmp_path), "--env", str(tmp_path / "none.env")])

    assert rc == 1
    assert not (tmp_path / "err.xml").exists(), "the error payload was written to the archive"


def test_a_skipped_payload_still_lets_the_good_files_be_archived(tmp_path, monkeypatch):
    """A permanent error payload on Drive must not disable the tool forever.

    This script is read-only against Drive by design, so a payload the owner has not
    deleted there is a standing condition, not a transient one. Blocking the manifest for
    every other statement because of it would make the guard something to work around.
    The exit stays non-zero so it never reads as success.
    """
    bad = WARN_1019_XML.encode("utf-8")
    _drive(
        monkeypatch,
        [_meta("a.xml", "id1", GOOD_XML), _meta("err.xml", "id2", bad)],
        {"id1": GOOD_XML, "id2": bad},
    )

    rc = fetch_flex_archive.main(["--dest", str(tmp_path), "--env", str(tmp_path / "none.env")])

    assert rc == 1
    assert (tmp_path / "a.xml").exists()
    manifest = json.loads((tmp_path / "_manifest.json").read_text())
    assert [entry["name"] for entry in manifest] == ["a.xml"]


def test_a_checksum_mismatch_still_blocks_the_manifest_entirely(tmp_path, monkeypatch):
    """Corruption is different from a known-bad payload: it invalidates the whole set."""
    _drive(
        monkeypatch,
        [_meta("a.xml", "id1", GOOD_XML), _meta("b.xml", "id2", GOOD_XML)],
        {"id1": GOOD_XML, "id2": GOOD_XML},
    )
    (tmp_path / "a.xml").write_bytes(EDITED_XML)

    rc = fetch_flex_archive.main(["--dest", str(tmp_path), "--env", str(tmp_path / "none.env")])

    assert rc == 2
    assert not (tmp_path / "_manifest.json").exists()


def test_a_good_statement_still_downloads(tmp_path, monkeypatch):
    _drive(monkeypatch, [_meta("a.xml", "id1", GOOD_XML)], {"id1": GOOD_XML})

    rc = fetch_flex_archive.main(["--dest", str(tmp_path), "--env", str(tmp_path / "none.env")])

    assert rc == 0
    assert (tmp_path / "a.xml").read_bytes() == GOOD_XML
