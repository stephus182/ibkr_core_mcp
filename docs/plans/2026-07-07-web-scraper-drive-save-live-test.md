# Web Scraper → Google Drive Save Live Test — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove that `WebDocsStore`'s Google Drive persistence — the exact path a consuming project exercises when a conversation calls `firecrawl_search(save_to_drive=True)` or `firecrawl_crawl(...)` — actually creates the documented `web_docs/` folder structure in a real production Drive folder, not just in mocked unit tests.

**Architecture:** New live-test file `tests/test_web_scraper_drive_live.py`, gated on real credentials for **both** Firecrawl and Google Drive being present in the environment (sourced from the consuming project's `.env`, never committed). Tests call `ClaudeToolkit.execute()` exactly as a consuming project's agent does, then independently verify the resulting Drive structure via a raw `googleapiclient` Drive service (reusing `WebDocsStore._get_service()`), and clean up the individual files they created — leaving the `web_docs/searches/` and `web_docs/<slug>/` folders themselves in place, per the owner's explicit cleanup decision (2026-07-07): **delete files once their existence is proven; leave the sub-folders**.

**Tech Stack:** real Firecrawl API, real Google Drive API v3 (`googleapiclient`), the already-existing OAuth token at `~/.ibkr_core/token.json` (no new OAuth flow needed — this plan skips if that token is missing rather than launching an interactive browser login from inside a test).

**Risk note:** this plan writes real files into the real, production `GOOGLE_DRIVE_FOLDER_ID` (a consuming project's actual Drive folder) — confirmed with the owner 2026-07-07 as the intended target, specifically *because* it validates the exact path a consuming project's users hit, not a throwaway folder. Every test must verify-then-delete its own file(s) before completing; a failed assertion mid-test should not be allowed to leave orphaned Drive files uncleaned (see Task 2's `try/finally` note).

---

## File Structure

- Create: `tests/test_web_scraper_drive_live.py` — fixtures + 2 tests (search-snapshot save, crawl mandatory-save)
- No production code changes — `WebDocsStore` and the `firecrawl_search`/`firecrawl_crawl` handlers are already implemented and unit-tested (`tests/test_web_scraper.py`, `tests/test_claude_tools.py`).

---

### Task 1: Write the credential-gated fixtures

**Files:**
- Create: `tests/test_web_scraper_drive_live.py`

- [ ] **Step 1: Write the test file's fixtures**

```python
"""Live integration tests for the web-scraper's Google Drive persistence path
— the exact save_to_drive / firecrawl_crawl flow a consuming project exercises in
production conversations.

Requires real credentials for BOTH Firecrawl and Google Drive, pointed at the
SAME account/folder a consuming project itself uses. Source them from the consuming project's own
.env (never committed to this repo):

    set -a; source /path/to/<consuming-project>/.env; set +a
    pytest tests/test_web_scraper_drive_live.py -v -m integration

All tests skip automatically if any required env var is missing, or if
GDRIVE_TOKEN_FILE doesn't exist yet (this suite reuses an existing OAuth
token rather than launching an interactive browser login).

## Writes real files to real Drive

This suite writes into the ACTUAL production GOOGLE_DRIVE_FOLDER_ID —
confirmed with the repo owner 2026-07-07 as intentional, since the point is
to validate the exact folder structure a consuming project's own users end up with,
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
```

- [ ] **Step 2: Run it to confirm it SKIPS cleanly with no env vars set**

Run: `pytest tests/test_web_scraper_drive_live.py -v -m integration`
Expected: `0 collected` initially (no tests yet, only fixtures) — this step just confirms the file imports without error: `python -c "import tests.test_web_scraper_drive_live"` run from the repo root with the venv active, expect no output/error.

- [ ] **Step 3: Commit**

```bash
git add tests/test_web_scraper_drive_live.py
git commit -m "test: add Drive-save live-test fixtures (skips until real Drive+Firecrawl creds present)"
```

---

### Task 2: firecrawl_search + save_to_drive — verify the searches/ snapshot

**Files:**
- Modify: `tests/test_web_scraper_drive_live.py`

- [ ] **Step 1: Write the test**

Append to `tests/test_web_scraper_drive_live.py`:

```python
import re


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
```

- [ ] **Step 2: Run it live**

Run: `set -a; source /path/to/<consuming-project>/.env; set +a; pytest tests/test_web_scraper_drive_live.py -v -m integration -k saves_snapshot`
Expected: PASS. This makes one real Firecrawl search call and one real Drive write + read + delete.

- [ ] **Step 3: Manually spot-check in Drive (one-time, not automated)**

Open Google Drive in a browser, navigate to the consuming project's Drive folder → `web_docs/searches/`. Confirm the folder exists and is empty of leftover test files (the test's `finally` block should have deleted the one it created).

- [ ] **Step 4: Commit**

```bash
git add tests/test_web_scraper_drive_live.py
git commit -m "test: verify firecrawl_search save_to_drive writes a real snapshot to Drive"
```

---

### Task 3: firecrawl_crawl (mandatory Drive save) — verify the `<slug>/` folder structure

**Files:**
- Modify: `tests/test_web_scraper_drive_live.py`

- [ ] **Step 1: Write the test**

Note: `example.com`'s page content is ~2 words ("Example Domain"), so
`assess_quality()` will classify it as `"fallback"` regardless of Firecrawl's
actual quality — this is expected and harmless here. If the Crawl4AI plan
(`2026-07-07-crawl4ai-live-test.md`) hasn't been run in this environment yet,
`_scrape_with_fallback` will catch `Crawl4AIUnavailableError` and keep
Firecrawl's original (short but real) markdown, adding a
"Crawl4AI fallback unavailable" note to the crawl summary text — it does NOT
fail this test or leave `index.json`/the page `.md` file empty, since
`WebDocsStore.save_crawl` only skips pages with genuinely empty markdown.

Append to `tests/test_web_scraper_drive_live.py`:

```python
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
```

- [ ] **Step 2: Run it live**

Run: `set -a; source /path/to/<consuming-project>/.env; set +a; pytest tests/test_web_scraper_drive_live.py -v -m integration -k saves_pages`
Expected: PASS. Makes one real Firecrawl crawl call (1 page, `example.com`) and real Drive writes (`index.json` + one `.md` file) + reads + deletes.

- [ ] **Step 3: Manually spot-check in Drive (one-time, not automated)**

Open Drive → `web_docs/`. Confirm a folder named after the example.com slug (`example-com` or similar, from `_slugify`) exists and is empty of leftover files.

- [ ] **Step 4: Commit**

```bash
git add tests/test_web_scraper_drive_live.py
git commit -m "test: verify firecrawl_crawl's mandatory Drive save writes the documented folder structure"
```

---

### Task 4: Full-suite sanity check

**Files:** none

- [ ] **Step 1: Run the new file standalone with real creds sourced**

Run: `set -a; source /path/to/<consuming-project>/.env; set +a; pytest tests/test_web_scraper_drive_live.py -v -m integration`
Expected: `2 passed`

- [ ] **Step 2: Run it again with NO creds sourced, confirm clean skip**

Run: `pytest tests/test_web_scraper_drive_live.py -v -m integration`
Expected: `2 skipped` (reason: missing env vars) — proves this suite never accidentally runs (and never accidentally writes to Drive) in a normal CI/dev run without explicit credential sourcing.

- [ ] **Step 3: Run the full non-integration suite to confirm nothing else broke**

Run: `pytest -q -m "not integration"`
Expected: same pass count as before this plan — no regressions (these are all `@pytest.mark.integration`, excluded here).

- [ ] **Step 4: ruff**

Run: `ruff check tests/test_web_scraper_drive_live.py`
Expected: `All checks passed!`

---

## Self-Review Notes

- **Spec coverage:** "Test claudia's use of web_scraper for saving in a Drive subfolder" → Task 2 (search snapshot → `web_docs/searches/`) and Task 3 (crawl → `web_docs/<slug>/`), both driven through `ClaudeToolkit.execute()` — the identical call path a consuming project's agent uses, not a hand-rolled call to `WebDocsStore` directly. "Consult" → addressed before this plan was written: Drive target (a real consuming-project folder, not a throwaway) and cleanup policy (delete files, keep folders) were both confirmed with the owner 2026-07-07 rather than assumed.
- **No placeholders:** every step has real, complete code or an exact command with expected output.
- **Type consistency:** `WebDocsStore(config)._get_service()`, `ClaudeToolkit.execute(name, inputs)`, and `_slugify(url)` signatures match `ibkr_core_mcp/web_scraper.py` and `ibkr_core_mcp/claude_tools.py` as they exist today (verified 2026-07-07).
- **Safety:** every Drive-verification test wraps its assertions in `try`/`finally` so a failed assertion still triggers cleanup rather than leaving an orphaned file if the test is re-run.
