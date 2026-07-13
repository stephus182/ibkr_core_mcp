# Web Docs Cache: Check-Before-Scrape + search_web_docs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the one confirmed gap from the 2026-07-07 web_scraper audit — there is no way for the LLM to read back what's already archived in Drive's `web_docs/` tree. Add (1) check-before-scrape so `firecrawl_crawl` reuses an already-archived crawl instead of re-scraping, and (2) a `search_web_docs` tool so the LLM can browse/search the archive directly.

**Architecture:** Two new `WebDocsStore` read methods (`load_crawl`, `list_web_docs`) in `web_scraper.py`, reusing the exact Drive-download pattern already proven in `GDriveCache._load_manifest` (`cache.py:236`, `MediaIoBaseDownload`). `_handle_firecrawl_crawl` in `claude_tools.py` calls `load_crawl` before ever touching Firecrawl, unless `force_refresh=true`. A new `search_web_docs` tool exposes `list_web_docs` to the LLM. No new Drive folders, no new credentials, no staleness/TTL bookkeeping — the existing `web_docs/{slug}/index.json` archive layout written by `save_crawl` IS the cache; these methods only ever read it.

**Tech Stack:** Google Drive API v3 (`googleapiclient`, already a dependency), same OAuth token/credentials `WebDocsStore` already uses. No new external dependencies.

**Design note (verified, not assumed):** Drive's `fullText contains` query operator's support for `text/markdown` mimetype content indexing is not documented in Google's own search-files guide (checked 2026-07-07 — see CLAUDE.md's "Docs First" rule, which exists precisely because this codebase has been burned twice by assuming undocumented API behavior). `list_web_docs` therefore never relies on Drive full-text search: it matches `query` against metadata this codebase already controls and guarantees — the crawl's source URL / folder slug, and the search snapshot's filename slug — which is reliable regardless of Drive's content-indexing behavior for any given mimetype.

---

## File Structure

- Modify: `ibkr_core_mcp/web_scraper.py` — add `_download_bytes`, `load_crawl`, `_list_children`, `list_web_docs` to `WebDocsStore`; import `MediaIoBaseDownload`; add module-level `_SEARCH_FILENAME_RE`
- Modify: `ibkr_core_mcp/claude_tools.py` — add `force_refresh` to `firecrawl_crawl`'s schema + check-before-scrape in `_handle_firecrawl_crawl`; add `search_web_docs` tool definition, `_handle_search_web_docs`, and dispatch registration
- Modify: `tests/test_web_scraper.py` — tests for the four new `WebDocsStore` methods
- Modify: `tests/test_claude_tools.py` — fix 3 existing tests broken by the new `load_crawl` call, add tests for check-before-scrape and `search_web_docs`
- Modify: `tests/test_web_scraper_drive_live.py` — two live proofs (cache hit on second crawl; `search_web_docs` finds a saved snapshot)
- Modify: `CLAUDE.md`, `README.md` — tool counts 42→43 (ClaudeToolkit) / 44→45 (MCP server)

---

### Task 1: `WebDocsStore._download_bytes` + `load_crawl` (check-before-scrape read path)

**Files:**
- Modify: `ibkr_core_mcp/web_scraper.py`
- Modify: `tests/test_web_scraper.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_web_scraper.py` (after the `save_search` tests at the end of the file):

```python
# ── WebDocsStore.load_crawl (check-before-scrape) ─────────────────────────────


def test_download_bytes_returns_file_content(tmp_path):
    store = _make_store_with_mock_service(tmp_path)

    def fake_download(buf, request):
        buf.write(b'{"hello": "world"}')
        buf.seek(0)
        m = MagicMock()
        m.next_chunk.return_value = (None, True)
        return m

    with patch("ibkr_core_mcp.web_scraper.MediaIoBaseDownload", side_effect=fake_download):
        content = store._download_bytes("some-file-id")
    assert content == b'{"hello": "world"}'


def test_load_crawl_returns_none_when_folder_missing(tmp_path):
    store = _make_store_with_mock_service(tmp_path)
    svc = store._svc
    svc.files().list().execute.return_value = {"files": []}

    assert store.load_crawl("https://example.com") is None


def test_load_crawl_returns_none_when_index_json_missing(tmp_path):
    store = _make_store_with_mock_service(tmp_path)
    svc = store._svc
    svc.files().list().execute.side_effect = [
        {"files": [{"id": "folder-id"}]},  # folder lookup
        {"files": []},                     # index.json lookup
    ]

    assert store.load_crawl("https://example.com") is None


def test_load_crawl_returns_manifest_and_downloaded_pages(tmp_path):
    import json

    store = _make_store_with_mock_service(tmp_path)
    svc = store._svc
    manifest = {
        "url": "https://example.com",
        "crawled_at": "2026-01-01T00:00:00+00:00",
        "pages": [{"url": "https://example.com/page", "file_id": "page-fid"}],
    }
    svc.files().list().execute.side_effect = [
        {"files": [{"id": "folder-id"}]},   # folder lookup
        {"files": [{"id": "index-fid"}]},   # index.json lookup
    ]

    downloads = {
        "index-fid": json.dumps(manifest).encode("utf-8"),
        "page-fid": b"# Cached page content",
    }

    def fake_get_media(fileId):
        req = MagicMock()
        req.file_id = fileId
        return req

    svc.files().get_media.side_effect = fake_get_media

    def fake_downloader(buf, request):
        buf.write(downloads[request.file_id])
        buf.seek(0)
        m = MagicMock()
        m.next_chunk.return_value = (None, True)
        return m

    with patch("ibkr_core_mcp.web_scraper.MediaIoBaseDownload", side_effect=fake_downloader):
        result = store.load_crawl("https://example.com")

    assert result["url"] == "https://example.com"
    assert result["crawled_at"] == "2026-01-01T00:00:00+00:00"
    assert result["pages"] == [
        {"url": "https://example.com/page", "markdown": "# Cached page content"}
    ]


def test_load_crawl_skips_page_that_fails_to_download(tmp_path):
    import json

    store = _make_store_with_mock_service(tmp_path)
    svc = store._svc
    manifest = {
        "url": "https://example.com",
        "crawled_at": "2026-01-01T00:00:00+00:00",
        "pages": [
            {"url": "https://example.com/good", "file_id": "good-fid"},
            {"url": "https://example.com/deleted", "file_id": "deleted-fid"},
        ],
    }
    svc.files().list().execute.side_effect = [
        {"files": [{"id": "folder-id"}]},
        {"files": [{"id": "index-fid"}]},
    ]

    def fake_get_media(fileId):
        req = MagicMock()
        req.file_id = fileId
        return req

    svc.files().get_media.side_effect = fake_get_media

    def fake_downloader(buf, request):
        if request.file_id == "index-fid":
            buf.write(json.dumps(manifest).encode("utf-8"))
        elif request.file_id == "good-fid":
            buf.write(b"# Good page")
        else:
            raise Exception("file not found in Drive")
        buf.seek(0)
        m = MagicMock()
        m.next_chunk.return_value = (None, True)
        return m

    with patch("ibkr_core_mcp.web_scraper.MediaIoBaseDownload", side_effect=fake_downloader):
        result = store.load_crawl("https://example.com")

    assert result["pages"] == [{"url": "https://example.com/good", "markdown": "# Good page"}]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_web_scraper.py -k "download_bytes or load_crawl" -v`
Expected: FAIL with `AttributeError: 'WebDocsStore' object has no attribute '_download_bytes'` (or `load_crawl`)

- [ ] **Step 3: Add the import and implement both methods**

In `ibkr_core_mcp/web_scraper.py`, update the import line:

```python
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
```

Add these two methods to `WebDocsStore`, directly after `save_search` (end of the class):

```python
    def _download_bytes(self, file_id: str) -> bytes:
        """Download a Drive file's raw content, mirroring GDriveCache._load_manifest's
        MediaIoBaseDownload pattern (cache.py:236)."""
        svc = self._get_service()
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, svc.files().get_media(fileId=file_id))
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buf.getvalue()

    def load_crawl(self, url: str) -> dict[str, Any] | None:
        """
        Return a previously saved crawl for `url`, or None if none exists.

        Reads web_docs/{slug}/index.json, then downloads each page's .md content
        by the file_id recorded in the manifest. Used by
        ClaudeToolkit._handle_firecrawl_crawl to serve an already-archived crawl
        instead of re-scraping (check-before-scrape) unless force_refresh=True.

        Args:
            url: The root URL that would be crawled — matched against the saved
                 crawl's folder via the same _slugify(url) used by save_crawl.

        Returns:
            {"url": str, "crawled_at": str, "pages": [{"url": str, "markdown": str}, ...]}
            or None if web_docs/{slug}/ or its index.json does not exist.

        Note: a page whose file_id fails to download (e.g. manually deleted from
        Drive after the manifest was written) is silently skipped rather than
        failing the whole load — a partial cache hit is still useful, and
        force_refresh=True remains available for a clean re-crawl.
        """
        svc = self._get_service()
        web_docs_id = self._get_web_docs_folder_id()
        slug = _slugify(url)
        folder_q = (
            f"name='{slug}' and mimeType='application/vnd.google-apps.folder'"
            f" and '{web_docs_id}' in parents and trashed=false"
        )
        folders = svc.files().list(q=folder_q, fields="files(id)").execute().get("files", [])
        if not folders:
            return None
        folder_id = folders[0]["id"]

        index_q = f"name='index.json' and '{folder_id}' in parents and trashed=false"
        index_files = svc.files().list(q=index_q, fields="files(id)").execute().get("files", [])
        if not index_files:
            return None

        manifest = json.loads(self._download_bytes(index_files[0]["id"]))
        pages: list[dict[str, str]] = []
        for p in manifest.get("pages", []):
            try:
                markdown = self._download_bytes(p["file_id"]).decode("utf-8")
            except Exception as exc:
                log.warning("load_crawl: failed to download page %s: %s", p.get("url"), exc)
                continue
            pages.append({"url": p["url"], "markdown": markdown})

        return {
            "url": manifest.get("url", url),
            "crawled_at": manifest.get("crawled_at", ""),
            "pages": pages,
        }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_web_scraper.py -k "download_bytes or load_crawl" -v`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add ibkr_core_mcp/web_scraper.py tests/test_web_scraper.py
git commit -m "feat: add WebDocsStore.load_crawl for check-before-scrape reads"
```

---

### Task 2: `WebDocsStore.list_web_docs` (browse/search the archive)

**Files:**
- Modify: `ibkr_core_mcp/web_scraper.py`
- Modify: `tests/test_web_scraper.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_web_scraper.py`:

```python
# ── WebDocsStore.list_web_docs ─────────────────────────────────────────────────


def test_list_web_docs_returns_crawl_and_search_entries_sorted_newest_first(tmp_path):
    import json

    store = _make_store_with_mock_service(tmp_path)
    svc = store._svc

    svc.files().list().execute.side_effect = [
        {"files": [{"id": "crawl-folder-id", "name": "example-com"}]},   # crawl folders
        {"files": [{"id": "index-fid"}]},                                # index.json lookup
        {"files": [{"id": "searches-folder-id"}]},                       # searches/ folder lookup
        {"files": [{"id": "search-file-id", "name": "20260101T120000Z-ibkr-docs.md"}]},  # searches contents
    ]
    store._download_bytes = MagicMock(
        return_value=json.dumps(
            {
                "url": "https://example.com",
                "crawled_at": "2026-06-01T00:00:00+00:00",
                "pages": [{"url": "https://example.com/a", "file_id": "x"}],
            }
        ).encode("utf-8")
    )

    entries = store.list_web_docs()

    assert len(entries) == 2
    # Crawl (2026-06-01) is newer than the search snapshot (2026-01-01) -> crawl first
    assert entries[0]["kind"] == "crawl"
    assert entries[0]["url"] == "https://example.com"
    assert entries[0]["page_count"] == 1
    assert entries[1]["kind"] == "search"
    assert entries[1]["query_slug"] == "ibkr-docs"
    assert entries[1]["file_id"] == "search-file-id"


def test_list_web_docs_filters_by_query_substring(tmp_path):
    import json

    store = _make_store_with_mock_service(tmp_path)
    svc = store._svc

    svc.files().list().execute.side_effect = [
        {"files": [
            {"id": "f1", "name": "example-com"},
            {"id": "f2", "name": "docs-firecrawl-dev"},
        ]},                                 # crawl folders
        {"files": [{"id": "idx1"}]},         # index.json for f1
        {"files": [{"id": "idx2"}]},         # index.json for f2
        {"files": []},                       # no searches/ folder
    ]
    manifests = {
        "idx1": {"url": "https://example.com", "crawled_at": "2026-06-01T00:00:00+00:00", "pages": []},
        "idx2": {"url": "https://docs.firecrawl.dev", "crawled_at": "2026-06-02T00:00:00+00:00", "pages": []},
    }
    store._download_bytes = MagicMock(
        side_effect=lambda fid: json.dumps(manifests[fid]).encode("utf-8")
    )

    entries = store.list_web_docs(query="firecrawl")

    assert len(entries) == 1
    assert entries[0]["url"] == "https://docs.firecrawl.dev"


def test_list_web_docs_respects_limit(tmp_path):
    import json

    store = _make_store_with_mock_service(tmp_path)
    svc = store._svc

    svc.files().list().execute.side_effect = [
        {"files": [
            {"id": "f1", "name": "site-a"},
            {"id": "f2", "name": "site-b"},
            {"id": "f3", "name": "site-c"},
        ]},
        {"files": [{"id": "idx1"}]},
        {"files": [{"id": "idx2"}]},
        {"files": [{"id": "idx3"}]},
        {"files": []},  # no searches/ folder
    ]
    manifests = {
        "idx1": {"url": "https://a.com", "crawled_at": "2026-01-01T00:00:00+00:00", "pages": []},
        "idx2": {"url": "https://b.com", "crawled_at": "2026-02-01T00:00:00+00:00", "pages": []},
        "idx3": {"url": "https://c.com", "crawled_at": "2026-03-01T00:00:00+00:00", "pages": []},
    }
    store._download_bytes = MagicMock(
        side_effect=lambda fid: json.dumps(manifests[fid]).encode("utf-8")
    )

    entries = store.list_web_docs(limit=2)

    assert len(entries) == 2
    assert entries[0]["url"] == "https://c.com"  # newest first
    assert entries[1]["url"] == "https://b.com"


def test_list_web_docs_excludes_searches_folder_from_crawl_entries(tmp_path):
    """The 'searches' subfolder itself must never be treated as a crawled site."""
    store = _make_store_with_mock_service(tmp_path)
    svc = store._svc

    svc.files().list().execute.side_effect = [
        {"files": [{"id": "searches-id", "name": "searches"}]},  # folders_only listing
        {"files": [{"id": "searches-id"}]},                      # searches/ folder lookup (by name)
        {"files": []},                                           # searches/ contents (empty)
    ]
    store._download_bytes = MagicMock()

    entries = store.list_web_docs()

    assert entries == []
    store._download_bytes.assert_not_called()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_web_scraper.py -k list_web_docs -v`
Expected: FAIL with `AttributeError: 'WebDocsStore' object has no attribute 'list_web_docs'`

- [ ] **Step 3: Implement `_list_children` and `list_web_docs`**

Add this module-level constant in `ibkr_core_mcp/web_scraper.py`, next to `_SLUG_RE`:

```python
_SEARCH_FILENAME_RE = re.compile(r"^(\d{8}T\d{6}Z)-(.+)\.md$")
```

Add these two methods to `WebDocsStore`, after `load_crawl`:

```python
    def _list_children(self, parent_id: str, folders_only: bool = False) -> list[dict[str, str]]:
        """List immediate children of a Drive folder.

        Returns [{"id": str, "name": str}, ...]. Used by list_web_docs to
        enumerate crawl subfolders (folders_only=True) and files inside
        web_docs/searches/ (folders_only=False).
        """
        svc = self._get_service()
        q = f"'{parent_id}' in parents and trashed=false"
        if folders_only:
            q += " and mimeType='application/vnd.google-apps.folder'"
        result = svc.files().list(q=q, fields="files(id,name)", pageSize=1000).execute()
        return result.get("files", [])

    def list_web_docs(self, query: str = "", limit: int = 20) -> list[dict[str, Any]]:
        """
        Browse or search the web_docs/ archive: previously crawled sites and saved
        search snapshots.

        Matches `query` (case-insensitive substring) against a crawl's source URL
        and folder name, or a search snapshot's filename slug — NOT full document
        content. Drive's `fullText contains` query operator's support for
        text/markdown mimetype content is not documented (see this module's
        docstring / CLAUDE.md's Docs First rule), so this method never relies on
        it; matching stays on metadata this codebase already controls (URLs,
        filenames), which is reliable regardless of Drive's content-indexing
        behavior for a given mimetype.

        Args:
            query: Case-insensitive substring to filter by. Empty string returns
                   everything (browse mode).
            limit: Maximum number of entries to return, newest first.

        Returns:
            List of entries, newest first, each one of:
              {"kind": "crawl", "url": str, "crawled_at": str, "page_count": int}
              {"kind": "search", "query_slug": str, "saved_at": str,
               "file_id": str, "filename": str}
        """
        svc = self._get_service()
        web_docs_id = self._get_web_docs_folder_id()
        q = query.lower().strip()

        entries: list[dict[str, Any]] = []

        for folder in self._list_children(web_docs_id, folders_only=True):
            if folder["name"] == "searches":
                continue
            index_q = f"name='index.json' and '{folder['id']}' in parents and trashed=false"
            index_files = svc.files().list(q=index_q, fields="files(id)").execute().get("files", [])
            if not index_files:
                continue
            try:
                manifest = json.loads(self._download_bytes(index_files[0]["id"]))
            except Exception:
                continue
            url = manifest.get("url", "")
            if q and q not in url.lower() and q not in folder["name"]:
                continue
            entries.append(
                {
                    "kind": "crawl",
                    "url": url,
                    "crawled_at": manifest.get("crawled_at", ""),
                    "page_count": len(manifest.get("pages", [])),
                }
            )

        searches_q = (
            "name='searches' and mimeType='application/vnd.google-apps.folder'"
            f" and '{web_docs_id}' in parents and trashed=false"
        )
        searches_folders = svc.files().list(q=searches_q, fields="files(id)").execute().get("files", [])
        if searches_folders:
            for f in self._list_children(searches_folders[0]["id"], folders_only=False):
                m = _SEARCH_FILENAME_RE.match(f["name"])
                if not m:
                    continue
                ts, slug = m.group(1), m.group(2)
                if q and q not in slug:
                    continue
                saved_at = datetime.strptime(ts, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC).isoformat()
                entries.append(
                    {
                        "kind": "search",
                        "query_slug": slug,
                        "saved_at": saved_at,
                        "file_id": f["id"],
                        "filename": f["name"],
                    }
                )

        entries.sort(key=lambda e: e.get("crawled_at") or e.get("saved_at") or "", reverse=True)
        return entries[:limit]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_web_scraper.py -k list_web_docs -v`
Expected: `4 passed`

- [ ] **Step 5: Run the whole file to confirm no regressions**

Run: `pytest tests/test_web_scraper.py -v`
Expected: all tests pass (previous count + 8 new tests from Tasks 1–2)

- [ ] **Step 6: Commit**

```bash
git add ibkr_core_mcp/web_scraper.py tests/test_web_scraper.py
git commit -m "feat: add WebDocsStore.list_web_docs for browsing/searching the Drive archive"
```

---

### Task 3: Wire check-before-scrape into `firecrawl_crawl`

**Files:**
- Modify: `ibkr_core_mcp/claude_tools.py`
- Modify: `tests/test_claude_tools.py`

- [ ] **Step 1: Fix the 3 existing tests that will break**

`_handle_firecrawl_crawl` is about to call `self._web_docs.load_crawl(url)`. Three existing tests mock `WebDocsStore` without setting `load_crawl`, so the mock's auto-generated attribute would return a truthy `MagicMock` — a false cache hit — breaking them. Add `mock_wds.load_crawl.return_value = None` to each, immediately after `mock_wds = MagicMock()`:

In `tests/test_claude_tools.py`, find and update these three tests:

1. `test_firecrawl_crawl_saves_pages_to_drive` (around line 1338):
```python
    mock_wds = MagicMock()
    mock_wds.load_crawl.return_value = None
    mock_wds.save_crawl.return_value = {
```

2. `test_firecrawl_crawl_never_fetches_blocked_subpage_url_via_crawl4ai` (around line 1582):
```python
    mock_wds = MagicMock()
    mock_wds.load_crawl.return_value = None
    mock_wds.save_crawl.return_value = {
```

3. `test_firecrawl_crawl_applies_fallback_per_page` (around line 1608):
```python
    mock_wds = MagicMock()
    mock_wds.load_crawl.return_value = None
    mock_wds.save_crawl.return_value = {
```

- [ ] **Step 2: Run the full claude_tools crawl tests to confirm they're still green before adding new behavior**

Run: `pytest tests/test_claude_tools.py -k firecrawl_crawl -v`
Expected: all pass (no behavior change yet — `_handle_firecrawl_crawl` hasn't been touched)

- [ ] **Step 3: Write the new failing tests**

Append to `tests/test_claude_tools.py`, after `test_firecrawl_crawl_saves_pages_to_drive`:

```python
@patch("ibkr_core_mcp.web_scraper.FirecrawlClient")
@patch("ibkr_core_mcp.web_scraper.WebDocsStore")
def test_firecrawl_crawl_serves_cached_result_without_calling_firecrawl(mock_wds_cls, mock_fc_cls):
    toolkit = _make_toolkit()
    mock_wds = MagicMock()
    mock_wds.load_crawl.return_value = {
        "url": "https://example.com",
        "crawled_at": "2026-01-01T00:00:00+00:00",
        "pages": [{"url": "https://example.com/page", "markdown": "# Cached"}],
    }
    mock_wds_cls.return_value = mock_wds

    result, fig = toolkit.execute("firecrawl_crawl", {"url": "https://example.com"})

    assert "Already archived" in result
    assert fig is None
    mock_fc_cls.return_value.crawl.assert_not_called()
    mock_wds.save_crawl.assert_not_called()


@patch("ibkr_core_mcp.web_scraper.FirecrawlClient")
@patch("ibkr_core_mcp.web_scraper.WebDocsStore")
def test_firecrawl_crawl_force_refresh_bypasses_cache(mock_wds_cls, mock_fc_cls):
    toolkit = _make_toolkit()
    mock_wds = MagicMock()
    mock_wds.load_crawl.return_value = {
        "url": "https://example.com",
        "crawled_at": "2026-01-01T00:00:00+00:00",
        "pages": [{"url": "https://example.com/page", "markdown": "# Cached"}],
    }
    mock_wds.save_crawl.return_value = {
        "url": "https://example.com",
        "crawled_at": "2026-02-01T00:00:00+00:00",
        "pages": [{"url": "https://example.com/page", "file_id": "fid"}],
    }
    mock_wds_cls.return_value = mock_wds
    mock_fc = MagicMock()
    mock_fc.crawl.return_value = [{"url": "https://example.com/page", "markdown": "# Fresh"}]
    mock_fc_cls.return_value = mock_fc

    result, fig = toolkit.execute(
        "firecrawl_crawl", {"url": "https://example.com", "force_refresh": True}
    )

    assert "Crawl complete" in result
    assert fig is None
    mock_fc.crawl.assert_called_once()
    mock_wds.load_crawl.assert_not_called()  # force_refresh skips the cache check entirely
```

- [ ] **Step 4: Run the new tests to verify they fail**

Run: `pytest tests/test_claude_tools.py -k "serves_cached_result or force_refresh_bypasses_cache" -v`
Expected: FAIL — `"Already archived"` not in result (current handler always calls Firecrawl)

- [ ] **Step 5: Add `force_refresh` to the tool schema**

In `ibkr_core_mcp/claude_tools.py`, in the `firecrawl_crawl` entry of `TOOL_DEFINITIONS` (around line 826-845), add a new property after `timeout_s`:

```python
                "timeout_s": {
                    "type": "integer",
                    "description": "Max seconds to wait for crawl to complete (default 120)",
                    "default": 120,
                },
                "force_refresh": {
                    "type": "boolean",
                    "description": (
                        "If true, re-crawl even if this URL was already archived to Drive. "
                        "Default: false (reuse the cached crawl if one exists, skipping "
                        "Firecrawl entirely)."
                    ),
                    "default": False,
                },
```

- [ ] **Step 6: Implement check-before-scrape in `_handle_firecrawl_crawl`**

Replace the full body of `_handle_firecrawl_crawl` in `ibkr_core_mcp/claude_tools.py` (currently lines 2686–2758) with:

```python
    def _handle_firecrawl_crawl(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        """
        Handle the firecrawl_crawl tool.

        Validates the URL with an SSRF guard before passing to Firecrawl. Lazily
        initializes FirecrawlClient and WebDocsStore on first call. Always saves
        results to Drive (crawl is a bulk operation — Drive storage is the point).

        Check-before-scrape: unless force_refresh=True, checks Drive for an
        existing archived crawl of this URL (WebDocsStore.load_crawl) and serves
        it directly, skipping Firecrawl entirely. The web_docs/{slug}/ layout
        save_crawl already writes IS the cache — no separate staleness
        bookkeeping is needed.
        """
        from ibkr_core_mcp.web_scraper import FirecrawlClient, FirecrawlError, WebDocsStore

        if not self._config.firecrawl_api_key:
            return (
                "firecrawl_crawl is not available: FIRECRAWL_API_KEY is not configured. "
                "Set it in .env to enable web crawling.",
                None,
            )

        url = inputs.get("url", "").strip()
        if not url:
            return "url must be non-empty.", None

        blocked = self._validate_public_url(url)
        if blocked:
            return blocked, None

        max_pages = int(inputs.get("max_pages", 50))
        timeout_s = int(inputs.get("timeout_s", 120))
        force_refresh = bool(inputs.get("force_refresh", False))

        if self._web_docs is None:
            self._web_docs = WebDocsStore(self._config)

        if not force_refresh:
            cached = self._web_docs.load_crawl(url)
            if cached is not None:
                pages = cached["pages"]
                preview = ", ".join(p["url"] for p in pages[:10])
                more = "..." if len(pages) > 10 else ""
                return (
                    "Already archived (served from Drive cache — pass force_refresh=true "
                    "to re-crawl):\n"
                    f"- Source: {cached['url']}\n"
                    f"- Archived at: {cached['crawled_at']}\n"
                    f"- Pages: {len(pages)}\n"
                    f"Pages: {preview}{more}",
                    None,
                )

        if self._firecrawl is None:
            self._firecrawl = FirecrawlClient(self._config.firecrawl_api_key)

        try:
            pages = self._firecrawl.crawl(url, max_pages=max_pages, timeout_s=timeout_s)
        except FirecrawlError as exc:
            return f"Firecrawl crawl failed (HTTP {exc.status_code}): {exc}", None

        # NOTE: each fallback call here launches its own Crawl4AI browser process
        # (Crawl4AIScraper.scrape has no connection/browser reuse across calls) and
        # runs sequentially. A crawl with many blocked/paywalled pages will pay
        # Chromium startup cost per page and can push total tool latency well past
        # Firecrawl's own timeout_s budget. Acceptable for now (fallback only fires
        # on already-incomplete pages, typically a minority) — worth revisiting with
        # a shared crawler instance or a fallback page cap if that stops holding.
        fallback_count = 0
        for page in pages:
            md, note = self._scrape_with_fallback(
                page.get("url", ""), page.get("markdown", ""), page.get("metadata")
            )
            page["markdown"] = md
            if note:
                fallback_count += 1

        try:
            manifest = self._web_docs.save_crawl(url, pages)
        except Exception as exc:
            return f"Crawl completed ({len(pages)} pages) but Drive save failed: {exc}", None

        saved = len(manifest["pages"])
        fallback_line = (
            f"\nCrawl4AI fallback used for {fallback_count} page(s) Firecrawl couldn't fully extract."
            if fallback_count
            else ""
        )
        return (
            f"Crawl complete: saved {saved} page(s) from {url} to Drive.\n"
            f"Crawled at: {manifest['crawled_at']}\n"
            f"Pages: " + ", ".join(p['url'] for p in manifest['pages'][:10])
            + ("..." if saved > 10 else "")
            + fallback_line,
            None,
        )
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `pytest tests/test_claude_tools.py -k firecrawl_crawl -v`
Expected: all pass, including the 2 new tests

- [ ] **Step 8: Run the full unit suite to confirm no regressions**

Run: `pytest -q -m "not integration"`
Expected: same pass count as before this task, plus the new tests — no failures

- [ ] **Step 9: Commit**

```bash
git add ibkr_core_mcp/claude_tools.py tests/test_claude_tools.py
git commit -m "feat: firecrawl_crawl serves an already-archived crawl from Drive instead of re-scraping"
```

---

### Task 4: `search_web_docs` tool

**Files:**
- Modify: `ibkr_core_mcp/claude_tools.py`
- Modify: `tests/test_claude_tools.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_claude_tools.py`:

```python
# ============================================================================
# search_web_docs
# ============================================================================


@patch("ibkr_core_mcp.web_scraper.WebDocsStore")
def test_search_web_docs_lists_entries(mock_wds_cls):
    toolkit = _make_toolkit()
    mock_wds = MagicMock()
    mock_wds.list_web_docs.return_value = [
        {
            "kind": "crawl",
            "url": "https://example.com",
            "crawled_at": "2026-01-01T00:00:00+00:00",
            "page_count": 3,
        },
        {
            "kind": "search",
            "query_slug": "ibkr-flex-api",
            "saved_at": "2026-01-02T00:00:00+00:00",
            "file_id": "fid",
            "filename": "20260102T000000Z-ibkr-flex-api.md",
        },
    ]
    mock_wds_cls.return_value = mock_wds

    result, fig = toolkit.execute("search_web_docs", {})

    assert "example.com" in result
    assert "ibkr-flex-api" in result
    assert fig is None
    mock_wds.list_web_docs.assert_called_once_with("", 10)


@patch("ibkr_core_mcp.web_scraper.WebDocsStore")
def test_search_web_docs_filters_by_query(mock_wds_cls):
    toolkit = _make_toolkit()
    mock_wds = MagicMock()
    mock_wds.list_web_docs.return_value = []
    mock_wds_cls.return_value = mock_wds

    result, fig = toolkit.execute("search_web_docs", {"query": "nonexistent", "limit": 5})

    assert "No archived web docs found" in result
    assert fig is None
    mock_wds.list_web_docs.assert_called_once_with("nonexistent", 5)


@patch("ibkr_core_mcp.web_scraper.WebDocsStore")
def test_search_web_docs_empty_archive_message(mock_wds_cls):
    toolkit = _make_toolkit()
    mock_wds = MagicMock()
    mock_wds.list_web_docs.return_value = []
    mock_wds_cls.return_value = mock_wds

    result, fig = toolkit.execute("search_web_docs", {})

    assert "archive is empty" in result
    assert fig is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_claude_tools.py -k search_web_docs -v`
Expected: FAIL — `"Unknown tool: search_web_docs"` (tool not registered yet)

- [ ] **Step 3: Add the tool definition**

In `ibkr_core_mcp/claude_tools.py`, insert this entry into `TOOL_DEFINITIONS` immediately after the `firecrawl_crawl` entry (before the closing `]`):

```python
    {
        "name": "search_web_docs",
        "description": (
            "Browse or search content already archived in the web_docs/ Google Drive "
            "cache from previous firecrawl_crawl and firecrawl_search(save_to_drive=true) "
            "calls. Use this BEFORE firecrawl_crawl/firecrawl_search to check whether a "
            "site or query has already been archived, avoiding a redundant scrape. "
            "Matches query against archived URLs/slugs and saved search queries, not full "
            "document content. Omit query to list everything, newest first."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Case-insensitive substring to filter by (URL, domain, or search "
                        "query). Omit to list all archived docs."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum entries to return. Default 10.",
                    "default": 10,
                },
            },
            "required": [],
        },
    },
```

- [ ] **Step 4: Add the handler**

Add this method to `ClaudeToolkit` in `ibkr_core_mcp/claude_tools.py`, immediately after `_handle_firecrawl_crawl`:

```python
    def _handle_search_web_docs(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        """
        Handle the search_web_docs tool: browse or search the Drive web_docs/
        archive built by firecrawl_crawl and firecrawl_search(save_to_drive=true).

        Read-only — never touches Firecrawl or Crawl4AI. Matches `query` against
        archived URLs/folder slugs and saved-search filename slugs (see
        WebDocsStore.list_web_docs's docstring for why this doesn't attempt full
        document-content search).
        """
        from ibkr_core_mcp.web_scraper import WebDocsStore, WebDocsStoreError

        if self._web_docs is None:
            self._web_docs = WebDocsStore(self._config)

        query = inputs.get("query", "").strip()
        limit = int(inputs.get("limit", 10))

        try:
            entries = self._web_docs.list_web_docs(query, limit)
        except WebDocsStoreError as exc:
            return f"search_web_docs failed: {exc}", None

        if not entries:
            empty = (
                f"No archived web docs found matching {query!r}."
                if query
                else "web_docs/ archive is empty."
            )
            return empty, None

        header = (
            f'## Archived web docs matching "{query}" ({len(entries)}):\n'
            if query
            else f"## All archived web docs ({len(entries)}):\n"
        )
        lines = [header]
        for e in entries:
            if e["kind"] == "crawl":
                lines.append(
                    f"- **Crawl:** {e['url']} — {e['page_count']} page(s), "
                    f"archived {e['crawled_at']}"
                )
            else:
                lines.append(
                    f"- **Search:** \"{e['query_slug']}\" — saved {e['saved_at']} "
                    f"(web_docs/searches/{e['filename']})"
                )
        lines.append(
            "\nTo reuse an archived crawl instead of re-scraping, call firecrawl_crawl "
            "with the same url — it is served from this cache automatically unless "
            "force_refresh=true."
        )
        return "\n".join(lines), None
```

- [ ] **Step 5: Register the handler in the dispatch dict**

In `ibkr_core_mcp/claude_tools.py`, in `execute()`'s `handlers` dict, add a line immediately after `"firecrawl_crawl": self._handle_firecrawl_crawl,`:

```python
            "firecrawl_crawl": self._handle_firecrawl_crawl,
            "search_web_docs": self._handle_search_web_docs,
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `pytest tests/test_claude_tools.py -k search_web_docs -v`
Expected: `3 passed`

- [ ] **Step 7: Run the full unit suite to confirm no regressions**

Run: `pytest -q -m "not integration"`
Expected: same pass count as Task 3's Step 8, plus 3 new tests — no failures

- [ ] **Step 8: ruff + mypy**

Run: `ruff check ibkr_core_mcp/web_scraper.py ibkr_core_mcp/claude_tools.py tests/test_web_scraper.py tests/test_claude_tools.py`
Expected: `All checks passed!`

Run: `mypy ibkr_core_mcp/web_scraper.py ibkr_core_mcp/claude_tools.py`
Expected: `Success: no issues found in 2 source files`

- [ ] **Step 9: Commit**

```bash
git add ibkr_core_mcp/claude_tools.py tests/test_claude_tools.py
git commit -m "feat: add search_web_docs tool to browse/search the Drive web_docs archive"
```

---

### Task 5: Update tool-count documentation

**Files:**
- Modify: `CLAUDE.md`
- Modify: `README.md`

Adding `search_web_docs` brings `ClaudeToolkit` from 42 to 43 tools, and the MCP server (which adds 2 alert-only tools) from 44 to 45.

- [ ] **Step 1: Update `CLAUDE.md`**

Line 69, in the package structure tree:
```
├── claude_tools.py    # Claude tool definitions + handlers (43 tools, portable)
```

Line 430, in the Claude AI Tool Layer example:
```python
    tools=toolkit.tools,          # 43 tools, ready to use
```

Line 472, in the MCP Server section:
```
`ibkr_core_mcp` ships a built-in MCP server exposing 45 tools and 4 resources.
```

- [ ] **Step 2: Update `README.md`**

Line 24:
```
| `mcp_server` | MCP server (stdio + SSE) exposing all 45 tools to any MCP client |
```

Line 228:
```
Expose all 43 tools (+ 2 MCP-only alert tools = 45 total) to any MCP-compatible client (Claude Desktop, Cursor, etc.):
```

- [ ] **Step 3: Verify no other stale counts remain**

Run: `grep -n "42 tools\|44 tools" CLAUDE.md README.md`
Expected: no output (both files updated)

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "docs: update tool counts for search_web_docs (42->43, 44->45)"
```

---

### Task 6: Live verification against real Drive

**Files:**
- Modify: `tests/test_web_scraper_drive_live.py`

These tests extend the live-test file from the 2026-07-07 Drive-save plan (already in the repo, gated the same way — real Firecrawl + Drive creds sourced from the consuming project's `.env`). They prove check-before-scrape and `search_web_docs` work against a real production Drive folder, not just mocks.

- [ ] **Step 1: Write the live tests**

Append to `tests/test_web_scraper_drive_live.py`:

```python
@pytest.mark.integration
def test_firecrawl_crawl_second_call_is_served_from_cache(toolkit, drive_service, live_config):
    from ibkr_core_mcp.web_scraper import _slugify

    url = "https://example.com"
    slug = _slugify(url)

    first_text, first_fig = toolkit.execute(
        "firecrawl_crawl", {"url": url, "max_pages": 1, "timeout_s": 60}
    )
    assert first_fig is None
    assert "Crawl complete" in first_text

    second_text, second_fig = toolkit.execute(
        "firecrawl_crawl", {"url": url, "max_pages": 1, "timeout_s": 60}
    )
    assert second_fig is None
    assert "Already archived" in second_text

    web_docs_q = (
        "name='web_docs' and mimeType='application/vnd.google-apps.folder'"
        f" and '{live_config.gdrive_folder_id}' in parents and trashed=false"
    )
    web_docs = drive_service.files().list(q=web_docs_q, fields="files(id)").execute()["files"]
    web_docs_id = web_docs[0]["id"]

    slug_q = (
        f"name='{slug}' and mimeType='application/vnd.google-apps.folder'"
        f" and '{web_docs_id}' in parents and trashed=false"
    )
    slug_folder_id = (
        drive_service.files().list(q=slug_q, fields="files(id)").execute()["files"][0]["id"]
    )
    contents_q = f"'{slug_folder_id}' in parents and trashed=false"
    contents = drive_service.files().list(q=contents_q, fields="files(id,name)").execute()["files"]

    try:
        assert any(f["name"] == "index.json" for f in contents)
    finally:
        # Cleanup policy: delete the files created by this run; leave the
        # web_docs/<slug>/ folder itself in place, matching the Drive-save
        # live test's convention.
        for f in contents:
            drive_service.files().delete(fileId=f["id"]).execute()


@pytest.mark.integration
def test_search_web_docs_finds_saved_search_snapshot(toolkit, drive_service):
    search_text, search_fig = toolkit.execute(
        "firecrawl_search",
        {
            "query": "Interactive Brokers Client Portal API check-before-scrape test",
            "limit": 1,
            "save_to_drive": True,
        },
    )
    assert search_fig is None
    import re

    match = re.search(r"file ID: ([^)]+)\)", search_text)
    assert match, f"No Drive file ID found in response: {search_text}"
    file_id = match.group(1)

    try:
        result_text, result_fig = toolkit.execute(
            "search_web_docs", {"query": "check-before-scrape test"}
        )
        assert result_fig is None
        assert "check-before-scrape-test" in result_text or "Search:" in result_text
    finally:
        drive_service.files().delete(fileId=file_id).execute()
```

- [ ] **Step 2: Run the live tests**

Run: `set -a; source /path/to/<consuming-project>/.env; set +a; pytest tests/test_web_scraper_drive_live.py -v -m integration -k "cache or search_web_docs"`
Expected: `2 passed`

- [ ] **Step 3: Confirm clean skip with no creds sourced**

Run: `pytest tests/test_web_scraper_drive_live.py -v -m integration`
Expected: `4 skipped` (2 tests from the earlier Drive-save plan + these 2 new ones)

- [ ] **Step 4: Full non-integration suite, ruff, mypy**

Run: `pytest -q -m "not integration"`
Expected: same pass count as Task 4's Step 7 (these are `@pytest.mark.integration`, excluded here)

Run: `ruff check tests/test_web_scraper_drive_live.py`
Expected: `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add tests/test_web_scraper_drive_live.py
git commit -m "test: live-verify check-before-scrape and search_web_docs against real Drive"
```

---

## Self-Review Notes

- **Spec coverage:** "check before scrape" → Task 3 (`load_crawl` wired into `_handle_firecrawl_crawl`, `force_refresh` escape hatch) + Task 6 (live proof). "ability to search web docs" → Task 2 (`list_web_docs`) + Task 4 (`search_web_docs` tool) + Task 6 (live proof). "best most logical approach, clean and efficient" → no new Drive folders/files/staleness bookkeeping: the archive `save_crawl` already writes IS the cache; matching stays on cheap metadata (URLs/filenames) rather than an unverified `fullText` content-search assumption, per CLAUDE.md's Docs First rule.
- **No placeholders:** every step has complete code or an exact command with expected output.
- **Type consistency:** `WebDocsStore.load_crawl(url) -> dict[str, Any] | None`, `list_web_docs(query="", limit=20) -> list[dict[str, Any]]`, and `_download_bytes(file_id) -> bytes` signatures are used identically across Tasks 1, 2, 3, and 4 — Task 3's handler calls `self._web_docs.load_crawl(url)` and checks `is not None`; Task 4's handler calls `self._web_docs.list_web_docs(query, limit)` matching Task 2's signature exactly.
- **Regression risk called out explicitly:** Task 3 Step 1 fixes the 3 existing tests that would otherwise silently break (a MagicMock's auto-generated `load_crawl` attribute is truthy, which would turn every mocked `firecrawl_crawl` test into a false cache hit) — found by reading current test mocks before writing the handler change, not discovered after the fact.
- **Safety:** the Task 6 live tests wrap Drive-verification assertions in `try`/`finally` (test 1) or a bare `finally` around the one file they create (test 2), matching the cleanup discipline already established in `tests/test_web_scraper_drive_live.py`.
