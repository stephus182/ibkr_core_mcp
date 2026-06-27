# Firecrawl Web Scraper — Design Spec

**Date:** 2026-06-26  
**Status:** Approved  
**Scope:** `ibkr_core_mcp` — new module `web_scraper.py` + Config extension + ClaudeToolkit integration

---

## Overview

Add two LLM-accessible tools to ClaudIA via `ibkr_core_mcp`:

- `firecrawl_search` — web search returning full markdown content per result; optional Drive snapshot
- `firecrawl_crawl` — async bulk crawl of a documentation site; saves all pages to Google Drive

Primary use cases:
1. Fetching and archiving IBKR API documentation for offline reference
2. Searching financial news, broker pages, and research content during a session

These tools augment the existing `fetch_web_page` local tool in `claudia/agent.py` (which handles simple single-URL fetches via `requests`). Firecrawl's value over plain requests: handles JS-rendered pages and structured extraction at scale.

Approach chosen: **Approach A** — new module in `ibkr_core_mcp`, folded into `ClaudeToolkit`. Follows every existing pattern (Config, Drive credentials, tool dispatch) with no changes required in `claudia/`.

---

## Architecture

```
claudia/agent.py
  └─ ClaudeToolkit.handle_tool("firecrawl_search" | "firecrawl_crawl")
       └─ ibkr_core_mcp/web_scraper.py
            ├─ FirecrawlClient          — Firecrawl REST v1 wrapper
            └─ WebDocsStore             — Drive persistence for crawled/searched content
                 └─ uses Config.gdrive_token_file + Config.gdrive_credentials_file
                      (same credential chain as GDriveCache — no new auth)
```

No changes to `claudia/agent.py` are required. Tools appear in `ClaudeToolkit.get_tool_definitions()` automatically once `web_scraper.py` is imported and `TOOL_DEFINITIONS` is extended.

---

## New File: `ibkr_core_mcp/web_scraper.py`

### Exceptions

```python
class FirecrawlError(Exception):
    """
    Raised when the Firecrawl REST API returns an error response or a crawl job fails.

    Attributes:
        message: Human-readable description of the failure.
        status_code: HTTP status code from the API response, or None if the error
                     occurred before an HTTP response was received (e.g. network timeout).
    """
    def __init__(self, message: str, status_code: int | None = None): ...


class WebDocsStoreError(Exception):
    """
    Raised when a Drive write operation in WebDocsStore fails.

    The original Google API exception is always chained as __cause__ so callers
    can inspect it if needed. ClaudeToolkit handlers catch this and return an error
    string to the LLM rather than propagating.
    """
```

### Module-level helper

```python
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
```

### `FirecrawlClient`

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

    def search(
        self,
        query: str,
        limit: int = 5,
    ) -> list[dict[str, str]]:
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
        returned. The return value is never empty on timeout — callers receive
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

            Pages with empty markdown are excluded from the result.

        Raises:
            FirecrawlError: If the crawl job transitions to status "failed", or if
                            the API returns a non-200 response on job start or poll.
            requests.exceptions.Timeout: If a single API call exceeds 30 seconds
                                         (distinct from the overall timeout_s limit).
        """
```

### `WebDocsStore`

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
                       replaced. index.json is always overwritten.

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

    def save_search(
        self,
        query: str,
        results: list[dict[str, str]],
    ) -> str:
        """
        Save a search result snapshot to Drive under web_docs/searches/.

        The file is named: {ISO8601_UTC_compact}-{query_slug}.md
        Example: 20260626T143022Z-ibkr-flex-api.md

        File content format:
            # Search: {original query}
            Saved: {ISO 8601 UTC timestamp}

            ---

            ## {title}
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
            "20260626T143022Z-ibkr-flex-api.md". Useful for logging or
            confirming the save to the user.

        Raises:
            WebDocsStoreError: If the searches/ subfolder cannot be created or
                               the file cannot be written.
        """
```

---

## Config Changes (`ibkr_core_mcp/config.py`)

Two new fields added to the `Config` dataclass:

```python
firecrawl_api_key: str = field(default="", repr=False)
# Firecrawl REST API key (fc-...). If empty, firecrawl_search and firecrawl_crawl
# return a "not available" error to the LLM. Tools remain registered so ClaudIA
# can explain why they are unavailable rather than claiming they don't exist.

gdrive_web_docs_folder_id: str = ""
# Optional: Drive folder ID to use as the web_docs/ root. If empty, WebDocsStore
# auto-creates a 'web_docs/' subfolder inside GOOGLE_DRIVE_FOLDER_ID on first use.
# Set explicitly to point at a pre-existing folder.
```

New env vars read in `Config.from_env()`:
- `FIRECRAWL_API_KEY` → `firecrawl_api_key`
- `GDRIVE_WEB_DOCS_FOLDER_ID` → `gdrive_web_docs_folder_id` (optional)

---

## Tool Definitions (added to `TOOL_DEFINITIONS` in `claude_tools.py`)

### `firecrawl_search`

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
}
```

### `firecrawl_crawl`

```python
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
}
```

---

## ClaudeToolkit Handler Behaviour

### Lazy initialisation

```python
# In ClaudeToolkit.__init__:
self._firecrawl: FirecrawlClient | None = None
self._web_docs: WebDocsStore | None = None
```

Both are initialised on the first call to their respective handler. If `config.firecrawl_api_key` is empty, `_firecrawl` is never initialised and the handler returns an error string immediately.

### SSRF guard (crawl only)

Before calling `FirecrawlClient.crawl`, the handler performs the same URL validation as `_fetch_web_page` in `claudia/agent.py`:
- Scheme must be `http` or `https`
- Hostname must not be `localhost`, `0.0.0.0`, or start with `127.` / `169.254.`
- Literal IP addresses must not be private, loopback, link-local, or reserved

Returns `"Blocked: cannot crawl private or localhost addresses."` on violation.

### `_handle_firecrawl_search` response format

```
## Web Search: "{query}"

### 1. {title}
**URL:** {url}

{markdown content}

---

### 2. ...

(Saved to Drive: web_docs/searches/20260626T143022Z-ibkr-flex-api.md)  ← if save_to_drive=true
```

### `_handle_firecrawl_crawl` response format

```
## Crawl Complete: {url}

- Pages saved: {n}
- Pages skipped: {n}  (already in Drive, overwrite=false)
- Pages failed: {n}
- Drive folder: web_docs/{folder_name}/
- Manifest: web_docs/{folder_name}/index.json
```

---

## Error Surface Summary

| Condition | Handler response to LLM |
|---|---|
| `FIRECRAWL_API_KEY` not set | `"firecrawl_search is unavailable: FIRECRAWL_API_KEY is not set."` |
| 401 from Firecrawl | `"Firecrawl authentication failed: check FIRECRAWL_API_KEY."` |
| 429 from Firecrawl | `"Firecrawl rate limit exceeded — wait before retrying."` |
| 5xx from Firecrawl | `"Firecrawl service error ({status_code}) — try again later."` |
| Crawl job failed | `"Crawl job failed: {error detail from API response}."` |
| Crawl timeout (partial) | Returns partial results with note: `"Warning: crawl timed out after {n}s — {k} of {total} pages collected."` |
| Drive unavailable (save_search) | `"Search results retrieved but Drive save failed: {reason}. Results displayed above."` |
| Drive unavailable (crawl) | `"Crawl completed ({n} pages) but Drive save failed: {reason}. Displaying first 3 pages inline."` |
| SSRF violation (crawl) | `"Blocked: cannot crawl private or localhost addresses."` |
| Invalid folder_name | `"Invalid folder_name: must not contain '/', '\\\\', or '..'."` |
| Empty query | `"Query must not be empty."` |

---

## Drive Folder Layout

```
GOOGLE_DRIVE_FOLDER_ID/          ← existing root folder
  db/                            ← existing (claudia.db)
  market_data/                   ← existing (OHLCV Parquet cache)
  account_data/                  ← existing (Flex XMLs, store.db backup)
  web_docs/                      ← NEW — auto-created by WebDocsStore on first use
    ibkr-campus/                 ← example: crawl of IBKR Campus API docs
      index.json
      ibkr-api-page-cpapi-v1.md
      trading-lessons-request-modify-orders.md
    searches/                    ← saved firecrawl_search snapshots
      20260626T143022Z-ibkr-flex-error-codes.md
```

---

## Explicitly Out of Scope

- `firecrawl_scrape` (single URL): existing `fetch_web_page` in `claudia/agent.py` covers this
- `firecrawl_interact` (browser automation): not selected; no use case identified
- Crawl result retrieval tool: ClaudIA can surface Drive content via search if needed in a future iteration
- Rate-limit retry loop inside `FirecrawlClient`: single attempt; clear error returned; LLM can retry
- Shared Drive service object between `WebDocsStore` and `GDriveCache`: each creates its own; same credential files; no new auth

---

## Files Modified / Created

| File | Change |
|---|---|
| `ibkr_core_mcp/web_scraper.py` | **New** — `FirecrawlError`, `WebDocsStoreError`, `_slugify`, `FirecrawlClient`, `WebDocsStore` |
| `ibkr_core_mcp/config.py` | Add `firecrawl_api_key`, `gdrive_web_docs_folder_id`, read from env |
| `ibkr_core_mcp/claude_tools.py` | Add `firecrawl_search` + `firecrawl_crawl` to `TOOL_DEFINITIONS`; add lazy init + handlers to `ClaudeToolkit` |
| `ibkr_core_mcp/pyproject.toml` | No changes — `requests` already a dependency |
| `../claudia_ui/.env.example` | Add `FIRECRAWL_API_KEY=` and `GDRIVE_WEB_DOCS_FOLDER_ID=` entries |
| `tests/test_web_scraper.py` | **New** — unit tests for `_slugify`, `FirecrawlClient` (mocked), `WebDocsStore` (mocked Drive) |
