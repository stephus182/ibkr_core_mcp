"""Live integration tests for the web-scraper's Google Drive persistence path
— the exact save_to_drive / firecrawl_crawl flow claudia_ui exercises in
production conversations.

Runs on **this repo's own standalone-dev `.env`** — the four vars CLAUDE.md documents
(`FIRECRAWL_API_KEY`, `GDRIVE_WEB_DOCS_FOLDER_ID`, `GDRIVE_TOKEN_FILE`,
`GDRIVE_CREDENTIALS_FILE`). Nothing else is needed:

    set -a; source ./.env; set +a
    pytest tests/test_web_scraper_drive_live.py -v -m integration

Sourcing claudia_ui's `.env` instead also works, and writes to the production folder
via `GOOGLE_DRIVE_FOLDER_ID` — either root is accepted, because either is enough for
`WebDocsStore`.

**It did not always work that way, and the failure mode is worth remembering.** The
fixture used to require `GOOGLE_DRIVE_FOLDER_ID` specifically — the one var this repo's
documented dev setup deliberately omits — so both tests here skipped on every default
run. A skip is not a failure, so nothing complained, and on 2026-07-30 a test rewritten
to cover `crawl_site` sat unverified for hours while the suite looked green. The fixture
now demands only what the code demands.

All tests skip automatically if any required env var is missing, or if
GDRIVE_TOKEN_FILE doesn't exist yet (this suite reuses an existing OAuth
token rather than launching an interactive browser login).

## Writes real files to real Drive

This suite writes into whichever real Drive folder is configured — the production
`GOOGLE_DRIVE_FOLDER_ID` when sourcing claudia_ui's `.env`, or the dev
`GDRIVE_WEB_DOCS_FOLDER_ID` otherwise. Writing to a real folder rather than a
throwaway sandbox was confirmed with the repo owner 2026-07-07 as intentional: the
point is to validate the exact folder structure claudia_ui's own users end up with. Cleanup policy (also confirmed 2026-07-07): each
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
        "GDRIVE_TOKEN_FILE": os.environ.get("GDRIVE_TOKEN_FILE", ""),
        "GDRIVE_CREDENTIALS_FILE": os.environ.get("GDRIVE_CREDENTIALS_FILE", ""),
    }
    missing = [k for k, v in required.items() if not v]

    # Either root works, because either is enough for WebDocsStore itself: it returns
    # `gdrive_web_docs_folder_id` directly when set, and only falls back to locating
    # `web_docs/` under `gdrive_folder_id` when it is not.
    #
    # This used to demand GOOGLE_DRIVE_FOLDER_ID specifically, which this repo's
    # documented standalone-dev .env deliberately omits (CLAUDE.md § Environment
    # Variables lists four vars, and that is not one of them). The result: both tests in
    # this file skipped on every default run — silently, because a skip is not a failure.
    # That is how a rewritten test sat unverified for hours on 2026-07-30 while the suite
    # looked healthy. Requiring only what the code requires ends that.
    folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "")
    web_docs_override = os.environ.get("GDRIVE_WEB_DOCS_FOLDER_ID", "")
    if not folder_id and not web_docs_override:
        missing.append("GOOGLE_DRIVE_FOLDER_ID or GDRIVE_WEB_DOCS_FOLDER_ID")
    if missing:
        pytest.skip(f"Missing env vars for live Drive test: {', '.join(missing)}")

    token_path = Path(required["GDRIVE_TOKEN_FILE"]).expanduser()
    if not token_path.exists():
        pytest.skip(f"GDRIVE_TOKEN_FILE not found at {token_path} — run OAuth once first")

    tmp = tmp_path_factory.mktemp("web_scraper_drive_live_cfg")
    return Config(
        gateway_url="https://localhost:5055/v1/api",
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", "test-key"),
        gdrive_folder_id=folder_id,
        gdrive_web_docs_folder_id=web_docs_override,
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


@pytest.fixture(scope="module")
def web_docs_id(live_config):
    """The `web_docs/` folder id, resolved by WebDocsStore rather than by this test.

    The test used to re-implement the lookup — query for a folder named `web_docs` under
    `gdrive_folder_id` — which is both a duplicate of production logic and the reason it
    demanded a variable the store does not need. Asking the store means the test can never
    disagree with the code it is testing about where the archive lives.
    """
    from ibkr_core_mcp.web_scraper import WebDocsStore

    return WebDocsStore(live_config)._get_web_docs_folder_id()


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
def test_crawl_site_saves_pages_to_drive(toolkit, drive_service, web_docs_id):
    """Was `test_firecrawl_crawl_saves_pages_to_drive`. That tool was deleted on
    2026-07-30 and this test kept passing CI for free because it is integration-marked
    and therefore skipped by default — a test for a tool that no longer exists, invisible
    until someone ran the live suite.

    `example.com` is deliberately NOT the target any more: it yields ~166 B, which now
    correctly grades "fallback", so `crawl_site` refuses to archive it and the test would
    fail for the right reason. Uses a real documentation page instead.
    """
    from ibkr_core_mcp.web_scraper import _slugify

    url = "https://docs.crawl4ai.com/core/quickstart/"
    text, fig = toolkit.execute(
        "crawl_site",
        {"url": url, "max_pages": 1, "max_depth": 0, "force_refresh": True},
    )
    assert fig is None
    assert "Crawl complete" in text, text
    assert "no credits spent" in text, "crawl_site must report that it cost nothing"

    slug = _slugify(url)

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
