"""Live integration test: web_docs Drive caching when developing ibkr_core_mcp
standalone (no consuming project like claudia_ui around it).

Distinct from `test_web_scraper_drive_live.py`, which requires
`GOOGLE_DRIVE_FOLDER_ID` (claudia_ui's production root folder) and validates
the auto-create-under-root path. This file validates the override path
instead — `GDRIVE_WEB_DOCS_FOLDER_ID` pointed directly at an existing
`web_docs/` folder, with no root folder configured at all. That's the
realistic shape of a *standalone dev* `.env` for this repo: per CLAUDE.md,
`.env` normally belongs only in consuming projects, but a local (gitignored)
one here — with just the Firecrawl key, the web_docs folder override, and
paths to an already-authenticated OAuth token — is enough to test caching
without needing the full claudia_ui env.

Root cause this test guards against: `firecrawl_search`/`firecrawl_crawl`
silently look like they cache nothing while developing ibkr_core_mcp in
isolation, simply because no env vars are set (by design — see CLAUDE.md's
Environment Variables section). That's not a bug, but it's easy to
mistake for one; this test is the reusable proof that caching works once
the four vars below are set.

Setup (one-time, local only — never commit `.env`):
    cp .env.example .env   # if not already present
    # then add/edit these four lines:
    FIRECRAWL_API_KEY=fc-...
    GDRIVE_WEB_DOCS_FOLDER_ID=<existing web_docs/ folder ID in Drive>
    GDRIVE_TOKEN_FILE=~/.ibkr_core/token_ibkr_core_mcp.json
    GDRIVE_CREDENTIALS_FILE=~/.ibkr_core/credentials_ibkr_core_mcp.json

Run:
    pytest tests/test_web_scraper_dev_cache_live.py -v -m integration

All tests skip automatically if any required env var is missing, or if
GDRIVE_TOKEN_FILE doesn't exist yet (reuses an existing OAuth token rather
than launching an interactive browser login).

## Writes real files to real Drive

Writes into whatever `GDRIVE_WEB_DOCS_FOLDER_ID` points at. Cleanup policy
(same as `test_web_scraper_drive_live.py`): verify the file exists via a
direct Drive API read, THEN delete just that file in a `finally` block —
the `web_docs/searches/` folder itself is left in place.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env", override=False)


@pytest.fixture(scope="module")
def dev_config(tmp_path_factory):
    from ibkr_core_mcp.config import Config

    required = {
        "FIRECRAWL_API_KEY": os.environ.get("FIRECRAWL_API_KEY", ""),
        "GDRIVE_WEB_DOCS_FOLDER_ID": os.environ.get("GDRIVE_WEB_DOCS_FOLDER_ID", ""),
        "GDRIVE_TOKEN_FILE": os.environ.get("GDRIVE_TOKEN_FILE", ""),
        "GDRIVE_CREDENTIALS_FILE": os.environ.get("GDRIVE_CREDENTIALS_FILE", ""),
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        pytest.skip(
            f"Missing env vars for dev web_docs cache test: {', '.join(missing)} "
            "(see this file's module docstring for local .env setup)"
        )

    token_path = Path(required["GDRIVE_TOKEN_FILE"]).expanduser()
    if not token_path.exists():
        pytest.skip(f"GDRIVE_TOKEN_FILE not found at {token_path} — run OAuth once first")

    tmp = tmp_path_factory.mktemp("web_scraper_dev_cache_cfg")
    return Config(
        gateway_url="https://localhost:5055/v1/api",
        anthropic_api_key="test-key",
        gdrive_folder_id="",
        sqlite_path=tmp / "store.db",
        gdrive_token_file=token_path,
        gdrive_credentials_file=Path(required["GDRIVE_CREDENTIALS_FILE"]).expanduser(),
        firecrawl_api_key=required["FIRECRAWL_API_KEY"],
        gdrive_web_docs_folder_id=required["GDRIVE_WEB_DOCS_FOLDER_ID"],
    )


@pytest.fixture(scope="module")
def toolkit(dev_config):
    from ibkr_core_mcp.claude_tools import ClaudeToolkit

    return ClaudeToolkit(MagicMock(), MagicMock(), MagicMock(), dev_config)


@pytest.fixture(scope="module")
def drive_service(dev_config):
    from ibkr_core_mcp.web_scraper import WebDocsStore

    return WebDocsStore(dev_config)._get_service()


@pytest.mark.integration
def test_firecrawl_search_saves_to_drive_from_dev_env(toolkit, drive_service):
    """Proves the standalone-dev .env (no GOOGLE_DRIVE_FOLDER_ID, only the
    web_docs override) is sufficient for firecrawl_search's save_to_drive
    path to actually reach Drive — not just return a "not configured" string.
    """
    text, fig = toolkit.execute(
        "firecrawl_search",
        {
            "query": "Interactive Brokers Client Portal API",
            "limit": 1,
            "save_to_drive": True,
        },
    )
    assert fig is None
    assert "not configured" not in text
    match = re.search(r"file ID: ([^)]+)\)", text)
    assert match, f"No Drive file ID found in response: {text}"
    file_id = match.group(1)

    try:
        meta = drive_service.files().get(fileId=file_id, fields="id,name,parents").execute()
        assert meta["name"].endswith(".md")
    finally:
        drive_service.files().delete(fileId=file_id).execute()
