"""Live integration tests for the web-scraper's Google Drive persistence path
— the exact save_to_drive / firecrawl_crawl flow claudia_ui exercises in
production conversations.

Requires real credentials for BOTH Firecrawl and Google Drive, pointed at the
SAME account/folder claudia_ui itself uses. Source them from claudia_ui's own
.env (never committed to this repo):

    set -a; source /Users/steph/Claude_Projects/claudia_ui/.env; set +a
    pytest tests/test_web_scraper_drive_live.py -v -m integration

All tests skip automatically if any required env var is missing, or if
GDRIVE_TOKEN_FILE doesn't exist yet (this suite reuses an existing OAuth
token rather than launching an interactive browser login).

## Writes real files to real Drive

This suite writes into the ACTUAL production GOOGLE_DRIVE_FOLDER_ID —
confirmed with the repo owner 2026-07-07 as intentional, since the point is
to validate the exact folder structure claudia_ui's own users end up with,
not a throwaway sandbox. Cleanup policy (also confirmed 2026-07-07): each
test verifies its file(s) exist via a direct Drive API read, THEN deletes
just those file(s) in a `finally` block — the `web_docs/searches/` and
`web_docs/<slug>/` folders themselves are left in place, so repeated runs
don't accumulate files but the folder layout stays inspectable.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture(scope="module")
def live_config(tmp_path_factory):
    from ibkr_core_mcp.config import Config

    required = {
        "FIRECRAWL_API_KEY": os.environ.get("FIRECRAWL_API_KEY", ""),
        "GOOGLE_DRIVE_FOLDER_ID": os.environ.get("GOOGLE_DRIVE_FOLDER_ID", ""),
        "GDRIVE_TOKEN_FILE": os.environ.get("GDRIVE_TOKEN_FILE", ""),
        "GDRIVE_CREDENTIALS_FILE": os.environ.get("GDRIVE_CREDENTIALS_FILE", ""),
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        pytest.skip(f"Missing env vars for live Drive test: {', '.join(missing)}")

    token_path = Path(required["GDRIVE_TOKEN_FILE"]).expanduser()
    if not token_path.exists():
        pytest.skip(f"GDRIVE_TOKEN_FILE not found at {token_path} — run OAuth once first")

    tmp = tmp_path_factory.mktemp("web_scraper_drive_live_cfg")
    return Config(
        gateway_url="https://localhost:5055/v1/api",
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", "test-key"),
        gdrive_folder_id=required["GOOGLE_DRIVE_FOLDER_ID"],
        sqlite_path=tmp / "store.db",
        gdrive_token_file=token_path,
        gdrive_credentials_file=Path(required["GDRIVE_CREDENTIALS_FILE"]).expanduser(),
        firecrawl_api_key=required["FIRECRAWL_API_KEY"],
    )


@pytest.fixture(scope="module")
def toolkit(live_config):
    from ibkr_core_mcp.claude_tools import ClaudeToolkit

    return ClaudeToolkit(MagicMock(), MagicMock(), MagicMock(), live_config)


@pytest.fixture(scope="module")
def drive_service(live_config):
    from ibkr_core_mcp.web_scraper import WebDocsStore

    return WebDocsStore(live_config)._get_service()


@pytest.mark.integration
def test_firecrawl_search_saves_snapshot_to_drive(toolkit, drive_service):
    text, fig = toolkit.execute(
        "firecrawl_search",
        {
            "query": "Interactive Brokers Client Portal API",
            "limit": 1,
            "save_to_drive": True,
        },
    )
    assert fig is None
    match = re.search(r"file ID: ([^)]+)\)", text)
    assert match, f"No Drive file ID found in response: {text}"
    file_id = match.group(1)

    try:
        # Verify the file really exists in Drive (real read, not just trusting
        # the tool's return text) before deleting it.
        meta = drive_service.files().get(fileId=file_id, fields="id,name,parents").execute()
        assert meta["name"].endswith(".md")
    finally:
        # Cleanup policy: delete the file once its existence is proven; the
        # web_docs/searches/ folder itself is left in place.
        drive_service.files().delete(fileId=file_id).execute()


@pytest.mark.integration
def test_firecrawl_crawl_saves_pages_to_drive(toolkit, drive_service, live_config):
    from ibkr_core_mcp.web_scraper import _slugify

    text, fig = toolkit.execute(
        "firecrawl_crawl",
        {"url": "https://example.com", "max_pages": 1, "timeout_s": 60},
    )
    assert fig is None
    assert "Crawl complete" in text

    slug = _slugify("https://example.com")

    web_docs_q = (
        "name='web_docs' and mimeType='application/vnd.google-apps.folder'"
        f" and '{live_config.gdrive_folder_id}' in parents and trashed=false"
    )
    web_docs = drive_service.files().list(q=web_docs_q, fields="files(id)").execute()["files"]
    assert web_docs, "web_docs/ folder not found in Drive"
    web_docs_id = web_docs[0]["id"]

    slug_q = (
        f"name='{slug}' and mimeType='application/vnd.google-apps.folder'"
        f" and '{web_docs_id}' in parents and trashed=false"
    )
    slug_folders = drive_service.files().list(q=slug_q, fields="files(id)").execute()["files"]
    assert slug_folders, f"web_docs/{slug}/ folder not found in Drive"
    slug_folder_id = slug_folders[0]["id"]

    contents_q = f"'{slug_folder_id}' in parents and trashed=false"
    contents = drive_service.files().list(q=contents_q, fields="files(id,name)").execute()["files"]
    names = {f["name"] for f in contents}

    try:
        assert "index.json" in names, f"index.json missing from web_docs/{slug}/: {names}"
        assert any(n.endswith(".md") for n in names), f"No page .md file in web_docs/{slug}/: {names}"
    finally:
        # Cleanup policy: delete the files we just verified; leave the
        # web_docs/<slug>/ folder itself in place.
        for f in contents:
            drive_service.files().delete(fileId=f["id"]).execute()
