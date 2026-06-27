# Firecrawl Web Scraper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `firecrawl_search` and `firecrawl_crawl` tools to ClaudIA via a new `ibkr_core_mcp/web_scraper.py` module that integrates with the existing `ClaudeToolkit` and Google Drive credential chain.

**Architecture:** New `web_scraper.py` provides `FirecrawlClient` (Firecrawl REST v1 wrapper) and `WebDocsStore` (Drive persistence under `web_docs/` subfolder). Two Config fields (`firecrawl_api_key`, `gdrive_web_docs_folder_id`) read from env. Tool definitions appended to `TOOL_DEFINITIONS` in `claude_tools.py`; handlers on `ClaudeToolkit` dispatched via the existing `execute()` method.

**Tech Stack:** Python 3.11, `requests` (already a dep), `google-api-python-client` (already a dep), Firecrawl REST API v1, pytest + `unittest.mock`.

**Spec:** `docs/superpowers/specs/2026-06-26-firecrawl-web-scraper-design.md`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `ibkr_core_mcp/web_scraper.py` | **Create** | `FirecrawlError`, `WebDocsStoreError`, `_slugify`, `FirecrawlClient`, `WebDocsStore` |
| `ibkr_core_mcp/config.py` | **Modify** (lines 30, 62) | Add `firecrawl_api_key`, `gdrive_web_docs_folder_id` fields + env reads |
| `ibkr_core_mcp/claude_tools.py` | **Modify** (lines 628, 724, 789) | Append tool definitions, add lazy init attrs, wire handlers |
| `tests/test_web_scraper.py` | **Create** | Unit tests for all classes and handlers (mocked Drive + Firecrawl) |
| `tests/test_config.py` | **Modify** | Two new tests for the new config fields |
| `../claudia_ui/.env.example` | **Modify** | Add `FIRECRAWL_API_KEY` and `GDRIVE_WEB_DOCS_FOLDER_ID` entries |

---

## Task 1: Extend Config with Firecrawl fields

**Files:**
- Modify: `ibkr_core_mcp/config.py:30` (field) and `:62` (from_env)
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_config.py`:

```python
def test_firecrawl_api_key_reads_from_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-abc123")
    monkeypatch.setenv("GDRIVE_WEB_DOCS_FOLDER_ID", "webdocs-folder-id")
    from ibkr_core_mcp.config import Config
    cfg = Config.from_env()
    assert cfg.firecrawl_api_key == "fc-abc123"
    assert cfg.gdrive_web_docs_folder_id == "webdocs-folder-id"


def test_firecrawl_config_defaults_to_empty(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    monkeypatch.delenv("GDRIVE_WEB_DOCS_FOLDER_ID", raising=False)
    from ibkr_core_mcp.config import Config
    cfg = Config.from_env()
    assert cfg.firecrawl_api_key == ""
    assert cfg.gdrive_web_docs_folder_id == ""
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
pytest tests/test_config.py::test_firecrawl_api_key_reads_from_env tests/test_config.py::test_firecrawl_config_defaults_to_empty -v
```

Expected: FAIL — `Config` has no attribute `firecrawl_api_key`.

- [ ] **Step 3: Add the two fields to Config**

In `ibkr_core_mcp/config.py`, after line 30 (`gdrive_account_folder_id: str = ""`), add:

```python
    # Firecrawl REST API key (fc-...). If empty, firecrawl_search and firecrawl_crawl
    # return a "not available" error string to the LLM rather than raising.
    firecrawl_api_key: str = field(default="", repr=False)
    # Drive folder ID to use as the web_docs/ root. Auto-creates 'web_docs/' under
    # gdrive_folder_id if empty.
    gdrive_web_docs_folder_id: str = ""
```

In `from_env()`, after line 62 (`gdrive_account_folder_id=os.environ.get("GDRIVE_ACCOUNT_FOLDER_ID", ""),`), add:

```python
            firecrawl_api_key=os.environ.get("FIRECRAWL_API_KEY", ""),
            gdrive_web_docs_folder_id=os.environ.get("GDRIVE_WEB_DOCS_FOLDER_ID", ""),
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_config.py -v
```

Expected: All config tests PASS.

- [ ] **Step 5: Commit**

```bash
git add ibkr_core_mcp/config.py tests/test_config.py
git commit -m "feat: add firecrawl_api_key and gdrive_web_docs_folder_id to Config"
```

---

## Task 2: Create web_scraper.py — exceptions, _slugify, and FirecrawlClient scaffold

**Files:**
- Create: `ibkr_core_mcp/web_scraper.py`
- Create: `tests/test_web_scraper.py`

- [ ] **Step 1: Write the failing tests for _slugify and exceptions**

Create `tests/test_web_scraper.py`:

```python
import pytest


# ── _slugify ──────────────────────────────────────────────────────────────────

def test_slugify_strips_scheme_and_lowercases():
    from ibkr_core_mcp.web_scraper import _slugify
    result = _slugify("https://DOCS.EXAMPLE.COM/Foo/Bar")
    assert result == "docs-example-com-foo-bar"


def test_slugify_ibkr_campus_url():
    from ibkr_core_mcp.web_scraper import _slugify
    result = _slugify(
        "https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/"
    )
    assert result == "www-interactivebrokers-com-campus-ibkr-api-page-cpapi-v1"


def test_slugify_truncates_to_100_chars():
    from ibkr_core_mcp.web_scraper import _slugify
    long_url = "https://example.com/" + "a" * 200
    assert len(_slugify(long_url)) <= 100


def test_slugify_no_path_traversal():
    from ibkr_core_mcp.web_scraper import _slugify
    result = _slugify("https://example.com/../../../etc/passwd")
    assert ".." not in result
    assert "/" not in result
    assert "\\" not in result


def test_slugify_no_leading_trailing_hyphens():
    from ibkr_core_mcp.web_scraper import _slugify
    result = _slugify("https://example.com/")
    assert not result.startswith("-")
    assert not result.endswith("-")


# ── Exceptions ────────────────────────────────────────────────────────────────

def test_firecrawl_error_stores_status_code():
    from ibkr_core_mcp.web_scraper import FirecrawlError
    err = FirecrawlError("bad key", 401)
    assert err.status_code == 401
    assert str(err) == "bad key"


def test_firecrawl_error_status_code_optional():
    from ibkr_core_mcp.web_scraper import FirecrawlError
    err = FirecrawlError("network failure")
    assert err.status_code is None


def test_web_docs_store_error_chains_cause():
    from ibkr_core_mcp.web_scraper import WebDocsStoreError
    cause = RuntimeError("drive down")
    try:
        raise WebDocsStoreError("save failed") from cause
    except WebDocsStoreError as e:
        assert e.__cause__ is cause
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_web_scraper.py -v
```

Expected: FAIL — `ibkr_core_mcp.web_scraper` does not exist.

- [ ] **Step 3: Create web_scraper.py with scaffold**

Create `ibkr_core_mcp/web_scraper.py`:

```python
"""
Web scraping tools for ClaudIA, backed by the Firecrawl REST API v1.

Provides:
  FirecrawlClient  — search and crawl via https://api.firecrawl.dev/v1
  WebDocsStore     — persist crawl/search results to Google Drive under web_docs/
  _slugify         — convert a URL to a safe Drive filename stem
  FirecrawlError   — raised on Firecrawl API errors
  WebDocsStoreError — raised on Drive persistence errors
"""
from __future__ import annotations

import io
import json
import logging
import re
import time
from datetime import UTC, datetime

import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

from ibkr_core_mcp.config import Config

log = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/drive"]
_SLUG_RE = re.compile(r"[^a-z0-9]+")


class FirecrawlError(Exception):
    """
    Raised when the Firecrawl REST API returns an error response or a crawl job fails.

    Attributes:
        message: Human-readable description of the failure.
        status_code: HTTP status code from the API response, or None if the error
                     occurred before an HTTP response was received (e.g. network timeout).
    """

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class WebDocsStoreError(Exception):
    """
    Raised when a Drive write operation in WebDocsStore fails.

    The original Google API exception is always chained as __cause__ so callers
    can inspect it if needed. ClaudeToolkit handlers catch this and return an error
    string to the LLM rather than propagating.
    """


def _slugify(url: str) -> str:
    """
    Convert a URL into a safe Drive filename stem (no extension).

    Transformation steps:
      1. Strip scheme (http://, https://)
      2. Lowercase the result
      3. Replace any run of characters outside [a-z0-9] with a single hyphen
      4. Strip leading and trailing hyphens
      5. Truncate to 100 characters

    The result contains only [a-z0-9-] and is at most 100 characters long.
    No path separators, dots, or traversal sequences (e.g. '..') are possible
    in the output, making it safe to use as a Drive file name without further
    sanitisation.

    Examples:
        "https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/"
        → "www-interactivebrokers-com-campus-ibkr-api-page-cpapi-v1"

        "https://docs.firecrawl.dev/features/search"
        → "docs-firecrawl-dev-features-search"
    """
    # Strip scheme
    url = re.sub(r"^https?://", "", url, flags=re.IGNORECASE)
    url = url.lower()
    slug = _SLUG_RE.sub("-", url).strip("-")
    return slug[:100]
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_web_scraper.py -v
```

Expected: All 9 scaffold tests PASS.

- [ ] **Step 5: Commit**

```bash
git add ibkr_core_mcp/web_scraper.py tests/test_web_scraper.py
git commit -m "feat: add web_scraper.py scaffold — exceptions, _slugify, FirecrawlError"
```

---

## Task 3: FirecrawlClient.search

**Files:**
- Modify: `ibkr_core_mcp/web_scraper.py` (append after `_slugify`)
- Test: `tests/test_web_scraper.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_web_scraper.py`:

```python
# ── FirecrawlClient.search ────────────────────────────────────────────────────

from unittest.mock import MagicMock, patch


def test_firecrawl_client_rejects_empty_api_key():
    from ibkr_core_mcp.web_scraper import FirecrawlClient
    with pytest.raises(ValueError, match="api_key"):
        FirecrawlClient("")


@patch("ibkr_core_mcp.web_scraper.requests")
def test_search_returns_formatted_results(mock_requests):
    from ibkr_core_mcp.web_scraper import FirecrawlClient
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": [
            {"url": "https://example.com", "title": "Example", "markdown": "# Hello"}
        ]
    }
    mock_requests.post.return_value = mock_resp
    client = FirecrawlClient("fc-test")
    results = client.search("test query", limit=1)
    assert len(results) == 1
    assert results[0]["url"] == "https://example.com"
    assert results[0]["title"] == "Example"
    assert results[0]["markdown"] == "# Hello"
    # Verify correct endpoint and payload
    mock_requests.post.assert_called_once()
    call_kwargs = mock_requests.post.call_args
    assert "/search" in call_kwargs[0][0]
    assert call_kwargs[1]["json"]["scrapeOptions"] == {"formats": ["markdown"]}


@patch("ibkr_core_mcp.web_scraper.requests")
def test_search_401_raises_firecrawl_error(mock_requests):
    from ibkr_core_mcp.web_scraper import FirecrawlClient, FirecrawlError
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_requests.post.return_value = mock_resp
    client = FirecrawlClient("fc-bad")
    with pytest.raises(FirecrawlError) as exc_info:
        client.search("query")
    assert exc_info.value.status_code == 401
    assert "FIRECRAWL_API_KEY" in str(exc_info.value)


@patch("ibkr_core_mcp.web_scraper.requests")
def test_search_429_raises_rate_limit(mock_requests):
    from ibkr_core_mcp.web_scraper import FirecrawlClient, FirecrawlError
    mock_resp = MagicMock()
    mock_resp.status_code = 429
    mock_requests.post.return_value = mock_resp
    client = FirecrawlClient("fc-test")
    with pytest.raises(FirecrawlError) as exc_info:
        client.search("query")
    assert exc_info.value.status_code == 429


@patch("ibkr_core_mcp.web_scraper.requests")
def test_search_5xx_raises_service_error(mock_requests):
    from ibkr_core_mcp.web_scraper import FirecrawlClient, FirecrawlError
    mock_resp = MagicMock()
    mock_resp.status_code = 503
    mock_requests.post.return_value = mock_resp
    client = FirecrawlClient("fc-test")
    with pytest.raises(FirecrawlError) as exc_info:
        client.search("query")
    assert exc_info.value.status_code == 503


def test_search_empty_query_raises():
    from ibkr_core_mcp.web_scraper import FirecrawlClient
    client = FirecrawlClient("fc-test")
    with pytest.raises(ValueError, match="query"):
        client.search("")


@patch("ibkr_core_mcp.web_scraper.requests")
def test_search_limit_clamped_to_10(mock_requests):
    from ibkr_core_mcp.web_scraper import FirecrawlClient
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": []}
    mock_requests.post.return_value = mock_resp
    client = FirecrawlClient("fc-test")
    client.search("query", limit=999)
    payload = mock_requests.post.call_args[1]["json"]
    assert payload["limit"] == 10
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_web_scraper.py -k "search" -v
```

Expected: FAIL — `FirecrawlClient` not defined.

- [ ] **Step 3: Implement FirecrawlClient with search method**

Append to `ibkr_core_mcp/web_scraper.py` (after `_slugify`):

```python
class FirecrawlClient:
    """
    Thin wrapper around the Firecrawl REST API v1 (https://api.firecrawl.dev/v1).

    Authentication is via Bearer token in the Authorization header. All requests
    use a 30-second timeout via the `requests` library (already a dependency of
    ibkr_core_mcp). No retries are performed internally — callers handle retry
    logic at the ClaudeToolkit layer.

    Only the two endpoints required by ClaudIA are implemented:
      - POST /v1/search  (firecrawl_search tool)
      - POST /v1/crawl + GET /v1/crawl/{id}  (firecrawl_crawl tool)

    Args:
        api_key: Firecrawl API key (fc-...). Must be non-empty; validated at
                 construction time with a ValueError if blank.
    """

    BASE_URL = "https://api.firecrawl.dev/v1"

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("api_key must be non-empty")
        self._api_key = api_key
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def _raise_for_status(self, resp: requests.Response) -> None:
        """Translate Firecrawl HTTP errors into FirecrawlError with a status code."""
        if resp.status_code == 401:
            raise FirecrawlError("Invalid FIRECRAWL_API_KEY", 401)
        if resp.status_code == 429:
            raise FirecrawlError("Rate limit exceeded — wait before retrying", 429)
        if resp.status_code >= 500:
            raise FirecrawlError(
                f"Firecrawl service error: {resp.status_code}", resp.status_code
            )
        resp.raise_for_status()

    def search(self, query: str, limit: int = 5) -> list[dict[str, str]]:
        """
        Search the web and return full page content as markdown for each result.

        Calls POST /v1/search with scrapeOptions.formats=["markdown"] so that
        each result includes extracted markdown rather than raw HTML.

        Args:
            query: Free-text search query. Must be non-empty.
            limit: Maximum number of results to return. Clamped to [1, 10].

        Returns:
            List of result dicts, each containing:
              - "url": str   — source URL
              - "title": str — page title (empty string if not present)
              - "markdown": str — extracted markdown content (empty string if not present)

        Raises:
            FirecrawlError: On HTTP 401 (bad key), 429 (rate limit), 5xx (service error),
                            or any non-200 response. status_code is set on the exception.
            ValueError: If query is empty or limit is outside [1, 10] before the call.
            requests.exceptions.Timeout: If the API does not respond within 30 seconds.
        """
        if not query:
            raise ValueError("query must be non-empty")
        limit = max(1, min(10, limit))
        resp = requests.post(
            f"{self.BASE_URL}/search",
            headers=self._headers,
            json={
                "query": query,
                "limit": limit,
                "scrapeOptions": {"formats": ["markdown"]},
            },
            timeout=30,
        )
        self._raise_for_status(resp)
        data = resp.json()
        raw = data.get("data") or data.get("results") or []
        return [
            {
                "url": r.get("url", ""),
                "title": r.get("title", ""),
                "markdown": r.get("markdown", "") or r.get("content", ""),
            }
            for r in raw
        ]
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_web_scraper.py -k "search or FirecrawlClient or firecrawl_client" -v
```

Expected: All search + exception + _slugify tests PASS.

- [ ] **Step 5: Commit**

```bash
git add ibkr_core_mcp/web_scraper.py tests/test_web_scraper.py
git commit -m "feat: implement FirecrawlClient.search with error handling"
```

---

## Task 4: FirecrawlClient.crawl

**Files:**
- Modify: `ibkr_core_mcp/web_scraper.py` (add `crawl` method to `FirecrawlClient`)
- Test: `tests/test_web_scraper.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_web_scraper.py`:

```python
# ── FirecrawlClient.crawl ─────────────────────────────────────────────────────

@patch("ibkr_core_mcp.web_scraper.time")
@patch("ibkr_core_mcp.web_scraper.requests")
def test_crawl_polls_until_completed(mock_requests, mock_time):
    from ibkr_core_mcp.web_scraper import FirecrawlClient
    # monotonic: deadline=0+120=120, first while check=1 (enter), second=2 (enter),
    # but status=completed exits immediately after second poll
    mock_time.monotonic.side_effect = [0.0, 1.0, 2.0]

    start_resp = MagicMock()
    start_resp.status_code = 200
    start_resp.json.return_value = {"id": "job-123"}

    poll1 = MagicMock()
    poll1.status_code = 200
    poll1.json.return_value = {"status": "scraping", "data": []}

    poll2 = MagicMock()
    poll2.status_code = 200
    poll2.json.return_value = {
        "status": "completed",
        "data": [
            {"metadata": {"sourceURL": "https://example.com/page"}, "markdown": "# Page"}
        ],
    }

    mock_requests.post.return_value = start_resp
    mock_requests.get.side_effect = [poll1, poll2]

    client = FirecrawlClient("fc-test")
    pages = client.crawl("https://example.com", timeout_s=120)
    assert len(pages) == 1
    assert pages[0]["url"] == "https://example.com/page"
    assert pages[0]["markdown"] == "# Page"


@patch("ibkr_core_mcp.web_scraper.time")
@patch("ibkr_core_mcp.web_scraper.requests")
def test_crawl_failed_status_raises(mock_requests, mock_time):
    from ibkr_core_mcp.web_scraper import FirecrawlClient, FirecrawlError
    mock_time.monotonic.side_effect = [0.0, 1.0]

    start_resp = MagicMock()
    start_resp.status_code = 200
    start_resp.json.return_value = {"id": "job-fail"}

    fail_poll = MagicMock()
    fail_poll.status_code = 200
    fail_poll.json.return_value = {"status": "failed", "error": "blocked by robots.txt"}

    mock_requests.post.return_value = start_resp
    mock_requests.get.return_value = fail_poll

    client = FirecrawlClient("fc-test")
    with pytest.raises(FirecrawlError, match="Crawl job failed"):
        client.crawl("https://example.com")


@patch("ibkr_core_mcp.web_scraper.time")
@patch("ibkr_core_mcp.web_scraper.requests")
def test_crawl_timeout_returns_partial_results(mock_requests, mock_time):
    from ibkr_core_mcp.web_scraper import FirecrawlClient
    # deadline = 0.0 + 10 = 10; first while check = 5.0 (enter loop); second = 200.0 (exit)
    mock_time.monotonic.side_effect = [0.0, 5.0, 200.0]

    start_resp = MagicMock()
    start_resp.status_code = 200
    start_resp.json.return_value = {"id": "job-slow"}

    partial_poll = MagicMock()
    partial_poll.status_code = 200
    partial_poll.json.return_value = {
        "status": "scraping",
        "data": [
            {"metadata": {"sourceURL": "https://example.com/p1"}, "markdown": "partial content"}
        ],
    }

    mock_requests.post.return_value = start_resp
    mock_requests.get.return_value = partial_poll

    client = FirecrawlClient("fc-test")
    pages = client.crawl("https://example.com", timeout_s=10)
    # Returns partial — does not raise
    assert len(pages) == 1
    assert pages[0]["markdown"] == "partial content"


@patch("ibkr_core_mcp.web_scraper.time")
@patch("ibkr_core_mcp.web_scraper.requests")
def test_crawl_skips_pages_with_empty_markdown(mock_requests, mock_time):
    from ibkr_core_mcp.web_scraper import FirecrawlClient
    mock_time.monotonic.side_effect = [0.0, 1.0]

    start_resp = MagicMock()
    start_resp.status_code = 200
    start_resp.json.return_value = {"id": "job-empty"}

    poll = MagicMock()
    poll.status_code = 200
    poll.json.return_value = {
        "status": "completed",
        "data": [
            {"metadata": {"sourceURL": "https://example.com/a"}, "markdown": "# Real"},
            {"metadata": {"sourceURL": "https://example.com/b"}, "markdown": ""},
            {"metadata": {"sourceURL": "https://example.com/c"}, "markdown": None},
        ],
    }

    mock_requests.post.return_value = start_resp
    mock_requests.get.return_value = poll

    client = FirecrawlClient("fc-test")
    pages = client.crawl("https://example.com")
    assert len(pages) == 1
    assert pages[0]["url"] == "https://example.com/a"


@patch("ibkr_core_mcp.web_scraper.time")
@patch("ibkr_core_mcp.web_scraper.requests")
def test_crawl_max_pages_clamped(mock_requests, mock_time):
    from ibkr_core_mcp.web_scraper import FirecrawlClient
    mock_time.monotonic.side_effect = [0.0, 1.0]
    start_resp = MagicMock()
    start_resp.status_code = 200
    start_resp.json.return_value = {"id": "job-clamp"}
    poll = MagicMock()
    poll.status_code = 200
    poll.json.return_value = {"status": "completed", "data": []}
    mock_requests.post.return_value = start_resp
    mock_requests.get.return_value = poll

    client = FirecrawlClient("fc-test")
    client.crawl("https://example.com", max_pages=9999)
    payload = mock_requests.post.call_args[1]["json"]
    assert payload["limit"] == 100
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_web_scraper.py -k "crawl" -v
```

Expected: FAIL — `FirecrawlClient` has no `crawl` method.

- [ ] **Step 3: Implement crawl method**

Add the following method to the `FirecrawlClient` class in `ibkr_core_mcp/web_scraper.py` (after the `search` method):

```python
    def crawl(
        self,
        url: str,
        max_pages: int = 50,
        timeout_s: int = 120,
    ) -> list[dict[str, str]]:
        """
        Crawl a site starting from url and return all pages as markdown.

        Firecrawl crawls are asynchronous. This method:
          1. Starts the job with POST /v1/crawl
          2. Polls GET /v1/crawl/{id} every 5 seconds until status == "completed"
             or timeout_s seconds have elapsed
          3. Returns all pages collected so far (partial results on timeout)

        On timeout, a warning is logged and whatever pages were collected are
        returned. The return value is never raised on timeout — callers receive
        whatever Firecrawl had completed.

        Args:
            url: Root URL to crawl from. Must be a public http/https URL. The
                 caller (ClaudeToolkit handler) is responsible for SSRF validation
                 before calling this method.
            max_pages: Upper bound on pages to crawl. Clamped to [1, 100].
            timeout_s: Maximum wall-clock seconds to wait for the crawl to complete.
                       Minimum 10s. If the job is still running at timeout, partial
                       results are returned rather than raising an error.

        Returns:
            List of page dicts, each containing:
              - "url": str      — source URL for the page
              - "markdown": str — full markdown content of the page

            Pages with empty or None markdown are excluded from the result.

        Raises:
            FirecrawlError: If the crawl job transitions to status "failed", or if
                            the API returns a non-200 response on job start or poll.
            requests.exceptions.Timeout: If a single API call exceeds 30 seconds
                                         (distinct from the overall timeout_s limit).
        """
        max_pages = max(1, min(100, max_pages))
        timeout_s = max(10, timeout_s)

        # Start crawl job
        resp = requests.post(
            f"{self.BASE_URL}/crawl",
            headers=self._headers,
            json={"url": url, "limit": max_pages, "scrapeOptions": {"formats": ["markdown"]}},
            timeout=30,
        )
        self._raise_for_status(resp)
        job_id = resp.json()["id"]

        # Poll for completion
        deadline = time.monotonic() + timeout_s
        pages: list[dict[str, str]] = []

        while time.monotonic() < deadline:
            time.sleep(5)
            poll = requests.get(
                f"{self.BASE_URL}/crawl/{job_id}",
                headers=self._headers,
                timeout=30,
            )
            poll.raise_for_status()
            data = poll.json()
            status = data.get("status", "")

            pages = [
                {
                    "url": p.get("metadata", {}).get("sourceURL", p.get("url", "")),
                    "markdown": p.get("markdown", ""),
                }
                for p in (data.get("data") or [])
                if p.get("markdown")
            ]

            if status == "completed":
                return pages
            if status == "failed":
                raise FirecrawlError(
                    f"Crawl job failed: {data.get('error', 'unknown error')}"
                )

        log.warning(
            "firecrawl crawl timed out after %ds — returning %d partial pages",
            timeout_s,
            len(pages),
        )
        return pages
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_web_scraper.py -k "crawl or search or slugify or exception or FirecrawlClient or firecrawl_client" -v
```

Expected: All crawl + prior tests PASS.

- [ ] **Step 5: Commit**

```bash
git add ibkr_core_mcp/web_scraper.py tests/test_web_scraper.py
git commit -m "feat: implement FirecrawlClient.crawl with async poll and timeout"
```

---

## Task 5: WebDocsStore — Drive service init and folder helpers

**Files:**
- Modify: `ibkr_core_mcp/web_scraper.py` (append `WebDocsStore` class)
- Test: `tests/test_web_scraper.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_web_scraper.py`:

```python
# ── WebDocsStore helpers ──────────────────────────────────────────────────────

@pytest.fixture
def mock_store(mock_config):
    """WebDocsStore with a mocked Drive service."""
    from ibkr_core_mcp.web_scraper import WebDocsStore
    store = WebDocsStore.__new__(WebDocsStore)
    store._config = mock_config
    store._service = MagicMock()
    store._web_docs_folder_id = ""
    return store


def test_find_or_create_folder_returns_existing(mock_store):
    mock_store._service.files().list().execute.return_value = {
        "files": [{"id": "existing-folder-id"}]
    }
    result = mock_store._find_or_create_folder("web_docs", "root-id")
    assert result == "existing-folder-id"
    mock_store._service.files().create.assert_not_called()


def test_find_or_create_folder_creates_when_missing(mock_store):
    mock_store._service.files().list().execute.return_value = {"files": []}
    mock_store._service.files().create().execute.return_value = {"id": "new-folder-id"}
    result = mock_store._find_or_create_folder("web_docs", "root-id")
    assert result == "new-folder-id"


def test_get_web_docs_folder_id_uses_config_override(mock_store, mock_config):
    mock_config.gdrive_web_docs_folder_id = "override-folder-id"
    mock_store._config = mock_config
    mock_store._web_docs_folder_id = "override-folder-id"
    result = mock_store._get_web_docs_folder_id()
    assert result == "override-folder-id"
    mock_store._service.files().list.assert_not_called()


def test_get_web_docs_folder_id_auto_creates(mock_store):
    mock_store._web_docs_folder_id = ""
    mock_store._config.gdrive_folder_id = "root-folder"
    mock_store._service.files().list().execute.return_value = {"files": []}
    mock_store._service.files().create().execute.return_value = {"id": "auto-created-id"}
    result = mock_store._get_web_docs_folder_id()
    assert result == "auto-created-id"
    # Cached on second call — no additional Drive calls
    mock_store._service.files().list.reset_mock()
    result2 = mock_store._get_web_docs_folder_id()
    assert result2 == "auto-created-id"
```

Note: the `mock_config` fixture is already defined in `tests/conftest.py`. Since `Config` now has `gdrive_web_docs_folder_id` (added in Task 1), `mock_config` will automatically have it with an empty-string default.

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_web_scraper.py -k "store or folder" -v
```

Expected: FAIL — `WebDocsStore` not defined.

- [ ] **Step 3: Implement WebDocsStore with Drive helpers**

Append to `ibkr_core_mcp/web_scraper.py` (after `FirecrawlClient`):

```python
class WebDocsStore:
    """
    Persists web content (crawl results and search snapshots) to Google Drive.

    Writes to a dedicated subfolder tree under the root ClaudIA Drive folder
    (GOOGLE_DRIVE_FOLDER_ID):

        web_docs/               — created on first use
          {folder_name}/        — one subfolder per crawl target
            index.json          — crawl manifest (see save_crawl)
            {slug}.md           — one file per crawled page
          searches/             — created on first save_search call
            {timestamp}-{slug}.md

    Drive authentication reuses the same token and credentials files as GDriveCache
    (Config.gdrive_token_file, Config.gdrive_credentials_file). No new OAuth flow
    or scopes are required — both classes use
    "https://www.googleapis.com/auth/drive".

    If Config.gdrive_web_docs_folder_id is set, that folder is used as the
    web_docs/ root directly (bypassing auto-creation). If unset, the folder is
    auto-created as a child of Config.gdrive_folder_id on first use.

    Args:
        config: ibkr_core_mcp Config instance. Must have gdrive_folder_id set;
                gdrive_web_docs_folder_id is optional.

    Raises:
        WebDocsStoreError: On any Drive API failure during folder creation or file
                           upload, with the original exception chained as __cause__.
    """

    def __init__(self, config: Config) -> None:
        self._config = config
        self._service = None
        # Cached folder ID for web_docs/ root — populated on first use
        self._web_docs_folder_id: str = config.gdrive_web_docs_folder_id

    def _get_service(self):
        """Return an authenticated Drive v3 service, refreshing credentials if needed."""
        if self._service is not None:
            return self._service
        creds = None
        token_file = self._config.gdrive_token_file
        if token_file.exists():
            creds = Credentials.from_authorized_user_file(str(token_file), _SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                token_file.write_text(creds.to_json())
            else:
                raise WebDocsStoreError(
                    "Drive credentials not available or expired. "
                    "Re-authenticate by running GDriveCache or GDriveSync first."
                )
        self._service = build("drive", "v3", credentials=creds)
        return self._service

    def _find_or_create_folder(self, name: str, parent_id: str) -> str:
        """
        Return the Drive folder ID for a folder named `name` under `parent_id`,
        creating the folder if it does not exist.

        Args:
            name: Folder name to find or create. Must not contain single quotes
                  (validated by callers via _slugify or folder_name validation).
            parent_id: Drive folder ID of the parent.

        Returns:
            Drive folder ID (string).
        """
        service = self._get_service()
        results = (
            service.files()
            .list(
                q=(
                    f"name='{name}' and '{parent_id}' in parents "
                    "and mimeType='application/vnd.google-apps.folder' "
                    "and trashed=false"
                ),
                fields="files(id)",
            )
            .execute()
        )
        files = results.get("files", [])
        if files:
            return files[0]["id"]
        folder = (
            service.files()
            .create(
                body={
                    "name": name,
                    "mimeType": "application/vnd.google-apps.folder",
                    "parents": [parent_id],
                },
                fields="id",
            )
            .execute()
        )
        return folder["id"]

    def _get_web_docs_folder_id(self) -> str:
        """
        Return the Drive folder ID for the web_docs/ root, auto-creating it
        under Config.gdrive_folder_id on first call if not already set.

        The result is cached on the instance so subsequent calls skip the Drive lookup.
        """
        if self._web_docs_folder_id:
            return self._web_docs_folder_id
        folder_id = self._find_or_create_folder(
            "web_docs", self._config.gdrive_folder_id
        )
        self._web_docs_folder_id = folder_id
        return folder_id
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_web_scraper.py -k "store or folder" -v
```

Expected: All WebDocsStore helper tests PASS.

- [ ] **Step 5: Commit**

```bash
git add ibkr_core_mcp/web_scraper.py tests/test_web_scraper.py
git commit -m "feat: add WebDocsStore with Drive service init and folder helpers"
```

---

## Task 6: WebDocsStore.save_crawl

**Files:**
- Modify: `ibkr_core_mcp/web_scraper.py` (add `save_crawl` to `WebDocsStore`)
- Test: `tests/test_web_scraper.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_web_scraper.py`:

```python
# ── WebDocsStore.save_crawl ───────────────────────────────────────────────────

def test_save_crawl_invalid_folder_name_raises(mock_store):
    from ibkr_core_mcp.web_scraper import WebDocsStore
    with pytest.raises(ValueError, match="folder_name"):
        mock_store.save_crawl("../evil", [])
    with pytest.raises(ValueError, match="folder_name"):
        mock_store.save_crawl("path/slash", [])


def test_save_crawl_skips_empty_markdown(mock_store):
    mock_store._web_docs_folder_id = "web-docs-id"
    mock_store._service.files().list().execute.return_value = {"files": []}
    mock_store._service.files().create().execute.return_value = {"id": "new-id"}
    pages = [
        {"url": "https://example.com/a", "markdown": "# Real"},
        {"url": "https://example.com/b", "markdown": ""},
    ]
    counts = mock_store.save_crawl("my-folder", pages)
    assert counts["saved"] == 1
    assert counts["skipped"] == 1


def test_save_crawl_skips_existing_when_overwrite_false(mock_store):
    mock_store._web_docs_folder_id = "web-docs-id"
    # Folder lookup: find subfolder
    mock_store._service.files().list().execute.side_effect = [
        {"files": [{"id": "sub-folder-id"}]},   # _find_or_create_folder for the crawl subfolder
        {"files": [{"id": "existing-file-id"}]}, # existence check for first page
    ]
    mock_store._service.files().create().execute.return_value = {"id": "index-id"}

    pages = [{"url": "https://example.com/a", "markdown": "# Content"}]
    counts = mock_store.save_crawl("my-folder", pages, overwrite=False)
    assert counts["skipped"] == 1
    assert counts["saved"] == 0


def test_save_crawl_overwrites_existing_when_overwrite_true(mock_store):
    mock_store._web_docs_folder_id = "web-docs-id"
    mock_store._service.files().list().execute.side_effect = [
        {"files": [{"id": "sub-folder-id"}]},   # subfolder lookup
        {"files": [{"id": "existing-file-id"}]}, # existence check
    ]
    mock_store._service.files().update().execute.return_value = {}
    mock_store._service.files().create().execute.return_value = {"id": "index-id"}

    pages = [{"url": "https://example.com/a", "markdown": "# New content"}]
    counts = mock_store.save_crawl("my-folder", pages, overwrite=True)
    assert counts["saved"] == 1
    mock_store._service.files().update.assert_called()


def test_save_crawl_writes_index_json(mock_store):
    import json
    mock_store._web_docs_folder_id = "web-docs-id"
    mock_store._service.files().list().execute.side_effect = [
        {"files": [{"id": "sub-folder-id"}]},
        {"files": []},  # no existing file
    ]
    captured_content = {}

    def capture_create(body=None, media_body=None, fields=None):
        if body and body.get("name") == "index.json":
            media_body._fd.seek(0)
            captured_content["index"] = json.loads(media_body._fd.read())
        mock_resp = MagicMock()
        mock_resp.execute.return_value = {"id": "some-id"}
        return mock_resp

    mock_store._service.files().create.side_effect = capture_create

    pages = [{"url": "https://example.com/page", "markdown": "# Hello"}]
    mock_store.save_crawl("my-folder", pages)

    assert "index" in captured_content
    idx = captured_content["index"]
    assert idx["source_url"] == "https://example.com/page"
    assert idx["page_count"] == 1
    assert len(idx["pages"]) == 1
    assert idx["pages"][0]["url"] == "https://example.com/page"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_web_scraper.py -k "save_crawl" -v
```

Expected: FAIL — `WebDocsStore` has no `save_crawl` method.

- [ ] **Step 3: Implement save_crawl**

Add the following method to the `WebDocsStore` class in `ibkr_core_mcp/web_scraper.py`:

```python
    def save_crawl(
        self,
        folder_name: str,
        pages: list[dict[str, str]],
        overwrite: bool = False,
    ) -> dict[str, int]:
        """
        Save crawl results to Drive under web_docs/{folder_name}/.

        Each page is written as a separate .md file named by _slugify(page["url"]).
        An index.json manifest is always written (or updated) in the same folder.

        index.json structure:
            {
              "crawled_at": "2026-06-26T14:30:22Z",   // ISO 8601 UTC
              "source_url": str,                        // URL of the first page
              "page_count": int,
              "pages": [
                {"url": str, "filename": str},          // filename excludes .md
                ...
              ]
            }

        Args:
            folder_name: Drive subfolder name within web_docs/. Must not contain
                         '/', '\\', or '..'. Validated with ValueError before any
                         Drive call.
            pages: List of page dicts from FirecrawlClient.crawl() — each must
                   have "url" and "markdown" keys. Pages with empty markdown are
                   skipped silently.
            overwrite: If False (default), pages whose slugified filename already
                       exists in Drive are skipped. If True, existing files are
                       replaced in-place. index.json is always overwritten.

        Returns:
            Dict with keys:
              - "saved": int    — number of pages written to Drive
              - "skipped": int  — number of pages skipped (empty markdown or
                                  already exists when overwrite=False)
              - "failed": int   — number of pages that raised a Drive error
                                  (partial failure; others still saved)

        Raises:
            ValueError: If folder_name contains path-traversal characters.
            WebDocsStoreError: If the web_docs/ or subfolder cannot be created,
                               or if index.json cannot be written.
        """
        if not folder_name or "/" in folder_name or "\\" in folder_name or ".." in folder_name:
            raise ValueError(
                f"Invalid folder_name {folder_name!r}: must not contain '/', '\\\\', or '..'"
            )

        web_docs_id = self._get_web_docs_folder_id()
        subfolder_id = self._find_or_create_folder(folder_name, web_docs_id)
        service = self._get_service()

        saved = skipped = failed = 0
        saved_pages: list[dict[str, str]] = []

        for page in pages:
            url = page.get("url", "")
            markdown = page.get("markdown", "")
            if not markdown:
                skipped += 1
                continue

            filename = _slugify(url) + ".md"
            content = f"# {url}\n\n{markdown}".encode("utf-8")
            media = MediaIoBaseUpload(io.BytesIO(content), mimetype="text/markdown")

            existing = (
                service.files()
                .list(
                    q=f"name='{filename}' and '{subfolder_id}' in parents and trashed=false",
                    fields="files(id)",
                )
                .execute()
                .get("files", [])
            )

            try:
                if existing:
                    if not overwrite:
                        skipped += 1
                        continue
                    service.files().update(
                        fileId=existing[0]["id"], media_body=media
                    ).execute()
                else:
                    service.files().create(
                        body={"name": filename, "parents": [subfolder_id]},
                        media_body=media,
                        fields="id",
                    ).execute()
                saved += 1
                saved_pages.append({"url": url, "filename": _slugify(url)})
            except Exception as exc:
                log.warning("WebDocsStore: failed to save %s: %s", url, exc)
                failed += 1

        # Always write index.json
        index = {
            "crawled_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source_url": pages[0]["url"] if pages else "",
            "page_count": saved,
            "pages": saved_pages,
        }
        index_content = json.dumps(index, indent=2).encode("utf-8")
        index_media = MediaIoBaseUpload(io.BytesIO(index_content), mimetype="application/json")
        try:
            service.files().create(
                body={"name": "index.json", "parents": [subfolder_id]},
                media_body=index_media,
                fields="id",
            ).execute()
        except Exception as exc:
            raise WebDocsStoreError("Failed to write index.json") from exc

        return {"saved": saved, "skipped": skipped, "failed": failed}
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_web_scraper.py -k "save_crawl or store or folder" -v
```

Expected: All save_crawl + WebDocsStore helper tests PASS.

- [ ] **Step 5: Commit**

```bash
git add ibkr_core_mcp/web_scraper.py tests/test_web_scraper.py
git commit -m "feat: implement WebDocsStore.save_crawl with overwrite and index.json"
```

---

## Task 7: WebDocsStore.save_search

**Files:**
- Modify: `ibkr_core_mcp/web_scraper.py` (add `save_search` to `WebDocsStore`)
- Test: `tests/test_web_scraper.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_web_scraper.py`:

```python
# ── WebDocsStore.save_search ──────────────────────────────────────────────────

def test_save_search_returns_filename(mock_store):
    mock_store._web_docs_folder_id = "web-docs-id"
    mock_store._service.files().list().execute.return_value = {"files": []}
    mock_store._service.files().create().execute.return_value = {"id": "search-file-id"}

    results = [{"url": "https://example.com", "title": "Example", "markdown": "# Hello"}]
    filename = mock_store.save_search("ibkr flex api", results)

    assert filename.endswith(".md")
    assert "ibkr" in filename
    assert "flex" in filename


def test_save_search_filename_format(mock_store):
    """Filename must match YYYYMMDDTHHMMSSZ-{query-slug}.md"""
    import re
    mock_store._web_docs_folder_id = "web-docs-id"
    mock_store._service.files().list().execute.return_value = {"files": []}
    mock_store._service.files().create().execute.return_value = {"id": "fid"}

    filename = mock_store.save_search("test query", [])
    # e.g. 20260626T143022Z-test-query.md
    assert re.match(r"^\d{8}T\d{6}Z-.+\.md$", filename), f"Unexpected filename: {filename}"


def test_save_search_empty_query_raises(mock_store):
    with pytest.raises(ValueError, match="query"):
        mock_store.save_search("", [])


def test_save_search_writes_to_searches_subfolder(mock_store):
    mock_store._web_docs_folder_id = "web-docs-id"
    # First list() call: searches/ folder lookup → not found → create
    mock_store._service.files().list().execute.return_value = {"files": []}
    mock_store._service.files().create().execute.side_effect = [
        {"id": "searches-folder-id"},   # create searches/
        {"id": "file-id"},              # create the .md file
    ]

    mock_store.save_search("query", [{"url": "https://x.com", "title": "X", "markdown": "# X"}])

    create_calls = mock_store._service.files().create.call_args_list
    # First create: searches/ folder
    first_body = create_calls[0][1]["body"]
    assert first_body["name"] == "searches"
    assert first_body["mimeType"] == "application/vnd.google-apps.folder"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_web_scraper.py -k "save_search" -v
```

Expected: FAIL — `WebDocsStore` has no `save_search` method.

- [ ] **Step 3: Implement save_search**

Add the following method to the `WebDocsStore` class in `ibkr_core_mcp/web_scraper.py`:

```python
    def save_search(self, query: str, results: list[dict[str, str]]) -> str:
        """
        Save a search result snapshot to Drive under web_docs/searches/.

        The file is named: {ISO8601_UTC_compact}-{query_slug}.md
        Example: 20260626T143022Z-ibkr-flex-api.md

        File content format:
            # Search: {original query}
            Saved: {ISO 8601 UTC timestamp}

            ---

            ## {title or url}
            Source: {url}

            {markdown content}

            ---
            (repeated for each result)

        Args:
            query: The original search query string. Used in the filename and
                   file header. Must be non-empty.
            results: List of result dicts from FirecrawlClient.search().

        Returns:
            The Drive file name (not full path) of the saved snapshot, e.g.
            "20260626T143022Z-ibkr-flex-api.md". Useful for confirming the save.

        Raises:
            ValueError: If query is empty.
            WebDocsStoreError: If the searches/ subfolder cannot be created or
                               the file cannot be written, with the original
                               exception chained as __cause__.
        """
        if not query:
            raise ValueError("query must be non-empty")

        now = datetime.now(UTC)
        timestamp = now.strftime("%Y%m%dT%H%M%SZ")
        filename = f"{timestamp}-{_slugify(query)[:50]}.md"

        lines = [
            f"# Search: {query}",
            f"Saved: {now.strftime('%Y-%m-%dT%H:%M:%SZ')}",
            "",
            "---",
            "",
        ]
        for r in results:
            lines.append(f"## {r.get('title') or r.get('url', '')}")
            lines.append(f"Source: {r.get('url', '')}")
            lines.append("")
            lines.append(r.get("markdown", ""))
            lines.append("")
            lines.append("---")
            lines.append("")
        content = "\n".join(lines).encode("utf-8")

        web_docs_id = self._get_web_docs_folder_id()
        searches_id = self._find_or_create_folder("searches", web_docs_id)

        media = MediaIoBaseUpload(io.BytesIO(content), mimetype="text/markdown")
        try:
            self._get_service().files().create(
                body={"name": filename, "parents": [searches_id]},
                media_body=media,
                fields="id",
            ).execute()
        except Exception as exc:
            raise WebDocsStoreError(f"Failed to save search snapshot: {exc}") from exc

        return filename
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_web_scraper.py -v
```

Expected: All tests in `test_web_scraper.py` PASS.

- [ ] **Step 5: Commit**

```bash
git add ibkr_core_mcp/web_scraper.py tests/test_web_scraper.py
git commit -m "feat: implement WebDocsStore.save_search with timestamped Drive snapshot"
```

---

## Task 8: Add tool definitions and wire dispatch in ClaudeToolkit

**Files:**
- Modify: `ibkr_core_mcp/claude_tools.py:628` (append to `TOOL_DEFINITIONS`)
- Modify: `ibkr_core_mcp/claude_tools.py:724` (`ClaudeToolkit.__init__` — add lazy attrs)
- Modify: `ibkr_core_mcp/claude_tools.py:789` (`execute()` handlers dict — add two entries)
- Test: `tests/test_claude_tools.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_claude_tools.py`:

```python
def test_firecrawl_tools_in_toolkit_definitions(mock_config):
    from unittest.mock import MagicMock
    from ibkr_core_mcp.claude_tools import ClaudeToolkit
    toolkit = ClaudeToolkit(
        client=MagicMock(),
        cache=MagicMock(),
        store=MagicMock(),
        config=mock_config,
    )
    names = {t["name"] for t in toolkit.tools}
    assert "firecrawl_search" in names
    assert "firecrawl_crawl" in names
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
pytest tests/test_claude_tools.py::test_firecrawl_tools_in_toolkit_definitions -v
```

Expected: FAIL — `firecrawl_search` not in tool definitions.

- [ ] **Step 3: Append tool definitions to TOOL_DEFINITIONS**

In `ibkr_core_mcp/claude_tools.py`, replace the closing `]` at line 628 with:

```python
    {
        "name": "firecrawl_search",
        "description": (
            "Search the web using Firecrawl and return full page content as markdown. "
            "Use for financial news, broker documentation, research, or any web query "
            "where you need the full content of results (not just titles and links). "
            "Handles JavaScript-rendered pages that fetch_web_page cannot access. "
            "Set save_to_drive=true to persist a snapshot of the results to Google Drive "
            "under web_docs/searches/ for future reference."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query, e.g. 'IBKR Flex Web Service error codes'.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of results to return. Range: 1–10. Default: 5.",
                },
                "save_to_drive": {
                    "type": "boolean",
                    "description": (
                        "If true, save a markdown snapshot of the results to Google Drive "
                        "under web_docs/searches/. Default: false."
                    ),
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "firecrawl_crawl",
        "description": (
            "Crawl a documentation site and save all pages as markdown files to Google Drive. "
            "Use for bulk documentation archiving — e.g. crawling the full IBKR Campus API "
            "reference so it is available offline. The crawl starts from the given URL and "
            "follows links within the same domain up to max_pages. "
            "Results are saved to Drive under web_docs/{folder_name}/. "
            "An index.json manifest lists all crawled pages and their filenames."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": (
                        "Root URL to crawl from, e.g. "
                        "'https://www.interactivebrokers.com/campus/ibkr-api-page/'. "
                        "Must be a public http/https URL."
                    ),
                },
                "folder_name": {
                    "type": "string",
                    "description": (
                        "Drive subfolder name within web_docs/. Auto-derived from the "
                        "URL hostname if omitted, e.g. 'interactivebrokers-com'."
                    ),
                },
                "max_pages": {
                    "type": "integer",
                    "description": "Maximum pages to crawl. Range: 1–100. Default: 50.",
                },
                "overwrite": {
                    "type": "boolean",
                    "description": (
                        "If true, replace existing Drive files for pages already crawled. "
                        "Default: false (skip pages already present, saving only new ones)."
                    ),
                },
            },
            "required": ["url"],
        },
    },
]
```

- [ ] **Step 4: Add lazy init attrs to `ClaudeToolkit.__init__`**

In `ibkr_core_mcp/claude_tools.py`, in `ClaudeToolkit.__init__` (around line 737, after `self._config = config`), add:

```python
        # Lazy-initialised on first firecrawl tool call
        self._firecrawl: Any = None
        self._web_docs: Any = None
```

- [ ] **Step 5: Wire handlers in execute()**

In `ibkr_core_mcp/claude_tools.py`, in the `execute()` handlers dict after `"delete_cache": self._delete_cache,` (line 789), add:

```python
            "firecrawl_search": self._handle_firecrawl_search,
            "firecrawl_crawl": self._handle_firecrawl_crawl,
```

- [ ] **Step 6: Run test to confirm it passes**

```bash
pytest tests/test_claude_tools.py::test_firecrawl_tools_in_toolkit_definitions -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add ibkr_core_mcp/claude_tools.py tests/test_claude_tools.py
git commit -m "feat: register firecrawl_search and firecrawl_crawl in ClaudeToolkit"
```

---

## Task 9: Implement _handle_firecrawl_search

**Files:**
- Modify: `ibkr_core_mcp/claude_tools.py` (append handler method to `ClaudeToolkit`)
- Test: `tests/test_claude_tools.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_claude_tools.py`:

```python
# ── _handle_firecrawl_search ──────────────────────────────────────────────────

@pytest.fixture
def toolkit_no_key(mock_config):
    """ClaudeToolkit with no Firecrawl API key set."""
    from unittest.mock import MagicMock
    from ibkr_core_mcp.claude_tools import ClaudeToolkit
    mock_config.firecrawl_api_key = ""
    return ClaudeToolkit(
        client=MagicMock(), cache=MagicMock(), store=MagicMock(), config=mock_config
    )


@pytest.fixture
def toolkit_with_key(mock_config):
    """ClaudeToolkit with a dummy Firecrawl API key."""
    from unittest.mock import MagicMock
    from ibkr_core_mcp.claude_tools import ClaudeToolkit
    mock_config.firecrawl_api_key = "fc-test-key"
    return ClaudeToolkit(
        client=MagicMock(), cache=MagicMock(), store=MagicMock(), config=mock_config
    )


def test_firecrawl_search_no_key_returns_error(toolkit_no_key):
    result, fig = toolkit_no_key.execute("firecrawl_search", {"query": "test"})
    assert "FIRECRAWL_API_KEY" in result
    assert fig is None


def test_firecrawl_search_empty_query_returns_error(toolkit_with_key):
    result, fig = toolkit_with_key.execute("firecrawl_search", {"query": ""})
    assert "empty" in result.lower()
    assert fig is None


@patch("ibkr_core_mcp.web_scraper.requests")
def test_firecrawl_search_formats_results(mock_requests, toolkit_with_key):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": [{"url": "https://example.com", "title": "Example", "markdown": "# Hello"}]
    }
    mock_requests.post.return_value = mock_resp

    result, fig = toolkit_with_key.execute("firecrawl_search", {"query": "IBKR flex api"})
    assert "IBKR flex api" in result
    assert "https://example.com" in result
    assert "# Hello" in result
    assert fig is None


@patch("ibkr_core_mcp.web_scraper.requests")
def test_firecrawl_search_401_returns_auth_error(mock_requests, toolkit_with_key):
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_requests.post.return_value = mock_resp

    result, _ = toolkit_with_key.execute("firecrawl_search", {"query": "test"})
    assert "authentication failed" in result.lower()


@patch("ibkr_core_mcp.web_scraper.requests")
def test_firecrawl_search_saves_to_drive_when_requested(mock_requests, toolkit_with_key):
    from unittest.mock import patch as mpatch
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": []}
    mock_requests.post.return_value = mock_resp

    with mpatch("ibkr_core_mcp.web_scraper.WebDocsStore") as mock_store_cls:
        mock_store_cls.return_value.save_search.return_value = "20260626T000000Z-test.md"
        result, _ = toolkit_with_key.execute(
            "firecrawl_search", {"query": "test", "save_to_drive": True}
        )
    assert "Drive" in result or "drive" in result.lower() or "20260626T000000Z" in result
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_claude_tools.py -k "firecrawl_search" -v
```

Expected: FAIL — `ClaudeToolkit` has no `_handle_firecrawl_search` method.

- [ ] **Step 3: Implement the handler**

Append the following method to the `ClaudeToolkit` class in `ibkr_core_mcp/claude_tools.py` (after `_delete_cache`):

```python
    def _handle_firecrawl_search(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        """
        Handle the firecrawl_search tool call.

        Calls FirecrawlClient.search and formats results as markdown. Optionally
        saves a snapshot to Drive via WebDocsStore.save_search. Returns a
        descriptive error string (never raises) so the LLM can report the issue.
        """
        import ipaddress
        import urllib.parse

        from ibkr_core_mcp.web_scraper import (
            FirecrawlClient,
            FirecrawlError,
            WebDocsStore,
            WebDocsStoreError,
        )

        if not self._config.firecrawl_api_key:
            return "firecrawl_search is unavailable: FIRECRAWL_API_KEY is not set.", None

        query = inputs.get("query", "").strip()
        if not query:
            return "Query must not be empty.", None

        limit = max(1, min(10, int(inputs.get("limit", 5))))
        save_to_drive = bool(inputs.get("save_to_drive", False))

        if self._firecrawl is None:
            self._firecrawl = FirecrawlClient(self._config.firecrawl_api_key)

        try:
            results = self._firecrawl.search(query, limit=limit)
        except FirecrawlError as exc:
            if exc.status_code == 401:
                return "Firecrawl authentication failed: check FIRECRAWL_API_KEY.", None
            if exc.status_code == 429:
                return "Firecrawl rate limit exceeded — wait before retrying.", None
            return f"Firecrawl service error ({exc.status_code}) — try again later.", None

        lines = [f'## Web Search: "{query}"', ""]
        for i, r in enumerate(results, 1):
            lines.append(f"### {i}. {r.get('title') or r['url']}")
            lines.append(f"**URL:** {r['url']}")
            lines.append("")
            lines.append(r.get("markdown", ""))
            lines.append("")
            lines.append("---")
            lines.append("")

        if save_to_drive:
            if self._web_docs is None:
                self._web_docs = WebDocsStore(self._config)
            try:
                filename = self._web_docs.save_search(query, results)
                lines.append(f"*Saved to Drive: web_docs/searches/{filename}*")
            except WebDocsStoreError as exc:
                lines.append(
                    f"*Search results retrieved but Drive save failed: {exc}. "
                    "Results displayed above.*"
                )

        return "\n".join(lines), None
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_claude_tools.py -k "firecrawl_search" -v
```

Expected: All search handler tests PASS.

- [ ] **Step 5: Commit**

```bash
git add ibkr_core_mcp/claude_tools.py tests/test_claude_tools.py
git commit -m "feat: implement ClaudeToolkit._handle_firecrawl_search"
```

---

## Task 10: Implement _handle_firecrawl_crawl

**Files:**
- Modify: `ibkr_core_mcp/claude_tools.py` (append handler method to `ClaudeToolkit`)
- Test: `tests/test_claude_tools.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_claude_tools.py`:

```python
# ── _handle_firecrawl_crawl ───────────────────────────────────────────────────

def test_firecrawl_crawl_no_key_returns_error(toolkit_no_key):
    result, _ = toolkit_no_key.execute("firecrawl_crawl", {"url": "https://example.com"})
    assert "FIRECRAWL_API_KEY" in result


def test_firecrawl_crawl_localhost_blocked(toolkit_with_key):
    result, _ = toolkit_with_key.execute(
        "firecrawl_crawl", {"url": "http://localhost:5055/v1/api"}
    )
    assert "Blocked" in result


def test_firecrawl_crawl_private_ip_blocked(toolkit_with_key):
    result, _ = toolkit_with_key.execute(
        "firecrawl_crawl", {"url": "http://192.168.1.1/admin"}
    )
    assert "Blocked" in result


def test_firecrawl_crawl_invalid_folder_name_returns_error(toolkit_with_key):
    result, _ = toolkit_with_key.execute(
        "firecrawl_crawl", {"url": "https://example.com", "folder_name": "../evil"}
    )
    assert "Invalid folder_name" in result


@patch("ibkr_core_mcp.web_scraper.time")
@patch("ibkr_core_mcp.web_scraper.requests")
def test_firecrawl_crawl_returns_summary(mock_requests, mock_time, toolkit_with_key):
    from unittest.mock import patch as mpatch

    mock_time.monotonic.side_effect = [0.0, 1.0]
    start_resp = MagicMock()
    start_resp.status_code = 200
    start_resp.json.return_value = {"id": "job-1"}
    poll_resp = MagicMock()
    poll_resp.status_code = 200
    poll_resp.json.return_value = {
        "status": "completed",
        "data": [{"metadata": {"sourceURL": "https://docs.example.com/page"}, "markdown": "# Doc"}],
    }
    mock_requests.post.return_value = start_resp
    mock_requests.get.return_value = poll_resp

    with mpatch("ibkr_core_mcp.web_scraper.WebDocsStore") as mock_store_cls:
        mock_store_cls.return_value.save_crawl.return_value = {
            "saved": 1, "skipped": 0, "failed": 0
        }
        result, _ = toolkit_with_key.execute(
            "firecrawl_crawl",
            {"url": "https://docs.example.com", "folder_name": "example-docs"},
        )

    assert "Pages saved: 1" in result
    assert "web_docs/example-docs/" in result
    assert "index.json" in result


@patch("ibkr_core_mcp.web_scraper.time")
@patch("ibkr_core_mcp.web_scraper.requests")
def test_firecrawl_crawl_drive_failure_returns_inline_fallback(
    mock_requests, mock_time, toolkit_with_key
):
    from unittest.mock import patch as mpatch
    from ibkr_core_mcp.web_scraper import WebDocsStoreError

    mock_time.monotonic.side_effect = [0.0, 1.0]
    start_resp = MagicMock()
    start_resp.status_code = 200
    start_resp.json.return_value = {"id": "job-2"}
    poll_resp = MagicMock()
    poll_resp.status_code = 200
    poll_resp.json.return_value = {
        "status": "completed",
        "data": [{"metadata": {"sourceURL": "https://docs.example.com"}, "markdown": "# Fallback"}],
    }
    mock_requests.post.return_value = start_resp
    mock_requests.get.return_value = poll_resp

    with mpatch("ibkr_core_mcp.web_scraper.WebDocsStore") as mock_store_cls:
        mock_store_cls.return_value.save_crawl.side_effect = WebDocsStoreError("Drive down")
        result, _ = toolkit_with_key.execute(
            "firecrawl_crawl", {"url": "https://docs.example.com"}
        )

    assert "Drive save failed" in result
    assert "# Fallback" in result
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_claude_tools.py -k "firecrawl_crawl" -v
```

Expected: FAIL — `ClaudeToolkit` has no `_handle_firecrawl_crawl` method.

- [ ] **Step 3: Implement the handler**

Append the following method to the `ClaudeToolkit` class in `ibkr_core_mcp/claude_tools.py` (after `_handle_firecrawl_search`):

```python
    def _handle_firecrawl_crawl(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        """
        Handle the firecrawl_crawl tool call.

        Validates the URL (SSRF guard), starts an async Firecrawl crawl job,
        waits for completion, and saves all pages to Drive via WebDocsStore.
        On Drive failure, returns the first three pages inline as a fallback.
        Returns a descriptive error string (never raises) so the LLM can
        report the issue clearly.
        """
        import ipaddress
        import urllib.parse

        from ibkr_core_mcp.web_scraper import (
            FirecrawlClient,
            FirecrawlError,
            WebDocsStore,
            WebDocsStoreError,
            _slugify,
        )

        if not self._config.firecrawl_api_key:
            return "firecrawl_crawl is unavailable: FIRECRAWL_API_KEY is not set.", None

        url = inputs.get("url", "").strip()
        if not url:
            return "url must not be empty.", None

        # SSRF guard — same validation as _fetch_web_page in claudia/agent.py
        try:
            parsed = urllib.parse.urlparse(url)
            if parsed.scheme not in ("http", "https"):
                return (
                    f"Blocked: only http/https URLs are supported (got {parsed.scheme!r}).",
                    None,
                )
            host = (parsed.hostname or "").lower()
            if not host:
                return "Blocked: URL has no hostname.", None
            if (
                host in ("localhost", "0.0.0.0")
                or host.startswith("127.")
                or host.startswith("169.254.")
            ):
                return "Blocked: cannot crawl private or localhost addresses.", None
            try:
                addr = ipaddress.ip_address(host)
                if (
                    addr.is_private
                    or addr.is_loopback
                    or addr.is_link_local
                    or addr.is_reserved
                ):
                    return "Blocked: cannot crawl private or reserved IP addresses.", None
            except ValueError:
                pass  # hostname — not a literal IP
        except Exception as exc:
            return f"Invalid URL: {exc}", None

        max_pages = max(1, min(100, int(inputs.get("max_pages", 50))))
        overwrite = bool(inputs.get("overwrite", False))

        folder_name = inputs.get("folder_name", "").strip()
        if not folder_name:
            folder_name = _slugify(parsed.hostname or url)[:50]

        if "/" in folder_name or "\\" in folder_name or ".." in folder_name:
            return "Invalid folder_name: must not contain '/', '\\\\', or '..'.", None

        if self._firecrawl is None:
            self._firecrawl = FirecrawlClient(self._config.firecrawl_api_key)

        try:
            pages = self._firecrawl.crawl(url, max_pages=max_pages)
        except FirecrawlError as exc:
            if exc.status_code == 401:
                return "Firecrawl authentication failed: check FIRECRAWL_API_KEY.", None
            if exc.status_code == 429:
                return "Firecrawl rate limit exceeded — wait before retrying.", None
            return f"Firecrawl crawl failed: {exc}", None

        if self._web_docs is None:
            self._web_docs = WebDocsStore(self._config)

        try:
            counts = self._web_docs.save_crawl(folder_name, pages, overwrite=overwrite)
        except WebDocsStoreError as exc:
            inline = "\n\n---\n\n".join(
                f"## {p['url']}\n\n{p['markdown'][:2000]}" for p in pages[:3]
            )
            return (
                f"Crawl completed ({len(pages)} pages fetched) but Drive save failed: {exc}.\n"
                f"Displaying first {min(3, len(pages))} pages inline:\n\n{inline}",
                None,
            )

        lines = [
            f"## Crawl Complete: {url}",
            "",
            f"- Pages saved: {counts['saved']}",
            f"- Pages skipped: {counts['skipped']}  "
            f"(already in Drive, overwrite={overwrite})",
            f"- Pages failed: {counts['failed']}",
            f"- Drive folder: web_docs/{folder_name}/",
            f"- Manifest: web_docs/{folder_name}/index.json",
        ]
        return "\n".join(lines), None
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_claude_tools.py -k "firecrawl" -v
```

Expected: All firecrawl handler tests PASS.

- [ ] **Step 5: Commit**

```bash
git add ibkr_core_mcp/claude_tools.py tests/test_claude_tools.py
git commit -m "feat: implement ClaudeToolkit._handle_firecrawl_crawl with SSRF guard and Drive fallback"
```

---

## Task 11: Update .env.example

**Files:**
- Modify: `../claudia_ui/.env.example`

- [ ] **Step 1: Add new env vars**

Open `/Users/steph/Claude_Projects/claudia_ui/.env.example` and append:

```bash
# Firecrawl web scraping (optional — enables firecrawl_search and firecrawl_crawl tools)
FIRECRAWL_API_KEY=
GDRIVE_WEB_DOCS_FOLDER_ID=   # optional — auto-creates web_docs/ in root Drive folder if unset
```

- [ ] **Step 2: Commit**

```bash
cd /Users/steph/Claude_Projects/claudia_ui
git add .env.example
git commit -m "docs: add FIRECRAWL_API_KEY and GDRIVE_WEB_DOCS_FOLDER_ID to .env.example"
cd /Users/steph/Claude_Projects/ibkr_core_mcp
```

---

## Task 12: Full test suite pass and final integration check

**Files:** None modified — verification only.

- [ ] **Step 1: Run the full test suite**

```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
pytest -v --tb=short 2>&1 | tail -40
```

Expected: All tests PASS. Zero regressions in existing tests.

- [ ] **Step 2: Verify the two new tools appear in the tool list**

```bash
python -c "
from ibkr_core_mcp.config import Config
from ibkr_core_mcp.claude_tools import TOOL_DEFINITIONS
names = [t['name'] for t in TOOL_DEFINITIONS]
assert 'firecrawl_search' in names, 'firecrawl_search missing'
assert 'firecrawl_crawl' in names, 'firecrawl_crawl missing'
print('OK — tools registered:', [n for n in names if 'firecrawl' in n])
"
```

Expected output:
```
OK — tools registered: ['firecrawl_search', 'firecrawl_crawl']
```

- [ ] **Step 3: Verify Config picks up FIRECRAWL_API_KEY**

```bash
python -c "
import os; os.environ['ANTHROPIC_API_KEY'] = 'sk-test'; os.environ['FIRECRAWL_API_KEY'] = 'fc-testkey'
from ibkr_core_mcp.config import Config
cfg = Config.from_env()
assert cfg.firecrawl_api_key == 'fc-testkey'
print('OK — firecrawl_api_key:', cfg.firecrawl_api_key[:8] + '...')
"
```

Expected output:
```
OK — firecrawl_api_key: fc-testke...
```

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat: Firecrawl web scraper — firecrawl_search + firecrawl_crawl tools complete

Adds FirecrawlClient, WebDocsStore, and two ClaudeToolkit tools:
- firecrawl_search: web search with optional Drive snapshot
- firecrawl_crawl: async site crawl saved to Drive web_docs/

SSRF guard on crawl URL, partial-result timeout handling,
Drive failure fallback to inline response."
```
