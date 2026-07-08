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
