"""Whole-web search, and the Drive archive every web tool writes to.

Two independent halves that have never shared a line of code:

  * **`FirecrawlClient`** — one endpoint, POST /v1/search. Firecrawl's sole
    remaining job here, and the only thing the local browser genuinely cannot do:
    find pages when you have no URL. `AsyncUrlSeeder` (`local_browser.py`) is
    domain-scoped by construction, so it can search *a* site but never *the web*.
  * **`WebDocsStore`** — the `web_docs/` Google Drive archive. Engine-agnostic:
    it takes a list of `{"url", "markdown"}` dicts and never knew who produced
    them, which is exactly why `crawl_site` could replace `firecrawl_crawl`
    underneath it as a drop-in rather than a migration.

**The crawl half of this client was deleted on 2026-07-30** — job start, the 5s
polling loop, `next` pagination, deadline handling, ~330 lines. Not because it
was broken but because it lost: measured on the same URLs minutes apart, the free
local browser returned more content in a tenth of the time
(`docs/web-scraper-reference.md` §5.2). `crawl_site` does that job now.

Provides:
  _slugify          — convert a URL to a safe Drive filename stem
  content_bytes     — total UTF-8 markdown bytes across a page list
  FirecrawlError    — raised on Firecrawl API errors
  WebDocsStoreError — raised on Drive persistence errors
  FirecrawlClient   — whole-web search via https://api.firecrawl.dev/v1
  WebDocsStore      — persist crawl/search results to Google Drive under web_docs/
"""

from __future__ import annotations

import io
import json
import logging
import random
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

from ibkr_core_mcp.config import Config

log = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/drive"]
_SLUG_RE = re.compile(r"[^a-z0-9]+")

# Firecrawl's own documented retry guidance (https://docs.firecrawl.dev/api-reference/errors,
# verified 2026-07-14): retryable statuses are 408/429/500/502/503/504; honor the Retry-After
# header (seconds) when present, else exponential backoff capped at 30s plus jitter:
# min(2 ** attempt, 30) + random(). Per-plan rate limits (https://docs.firecrawl.dev/rate-limits,
# same date) are as low as 1 req/min for /crawl on the Free tier, so a caller issuing several
# requests back-to-back with no retry at all (the prior behavior here) reliably cascades into
# a 429 on every subsequent call within that window.
_FIRECRAWL_RETRYABLE_STATUSES = frozenset({408, 429, 500, 502, 503, 504})
_FIRECRAWL_MAX_RETRIES = 3
_FIRECRAWL_MAX_BACKOFF = 30.0


def _request_with_backoff(fn: Callable[[], requests.Response]) -> requests.Response:
    """Call fn() (a zero-arg thunk wrapping a single requests.post/get call), retrying
    on Firecrawl's documented retryable statuses with exponential backoff + jitter,
    honoring the Retry-After header when present. See the module-level comment above
    _FIRECRAWL_RETRYABLE_STATUSES for the source citation.

    fn is a thunk (not method/url/kwargs passed separately) so callers keep using
    requests.post(...)/requests.get(...) directly — preserving the existing
    `@patch("ibkr_core_mcp.web_scraper.requests")` / `mock_requests.post` test mocking
    convention used throughout this module's test suite.

    Returns the final response (whether it succeeded or retries were exhausted) —
    callers still run their own status-code handling (_raise_for_status) on it.
    """
    attempt = 0
    while True:
        resp = fn()
        if resp.status_code not in _FIRECRAWL_RETRYABLE_STATUSES or attempt >= _FIRECRAWL_MAX_RETRIES:
            return resp
        retry_after = resp.headers.get("Retry-After")
        try:
            delay = float(retry_after) if retry_after is not None else min(2**attempt, _FIRECRAWL_MAX_BACKOFF)
        except (TypeError, ValueError):
            delay = min(2**attempt, _FIRECRAWL_MAX_BACKOFF)
        time.sleep(delay + random.random())
        attempt += 1


class FirecrawlError(Exception):
    """Raised when the Firecrawl REST API returns an error response or a crawl job fails.

    Attributes:
        message: Human-readable description of the failure.
        status_code: HTTP status code from the API response, or None if the error
                     occurred before an HTTP response was received (e.g. network timeout).
    """

    def __init__(self, message: str, status_code: int | None = None) -> None:
        """Record the message and, when one was received, the HTTP status.

        Args:
            message: Human-readable description of the failure.
            status_code: HTTP status from Firecrawl, or None when the request
                failed before any response arrived (e.g. a network timeout) —
                which is why this is None rather than 0.
        """
        super().__init__(message)
        self.status_code = status_code


class WebDocsStoreError(Exception):
    """Raised when a Drive write operation in WebDocsStore fails.

    The original Google API exception is always chained as __cause__ so callers
    can inspect it if needed. ClaudeToolkit handlers catch this and return an error
    string to the LLM rather than propagating.
    """


def _slugify(url: str) -> str:
    """Convert a URL into a safe Drive filename stem (no extension).

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
        "https://ibkrcampus.com/docs/web-api/v1/endpoints/introduction.md"
        → "ibkrcampus-com-docs-web-api-v1-endpoints-introduction-md"

        "https://docs.firecrawl.dev/features/search"
        → "docs-firecrawl-dev-features-search"
    """
    url = re.sub(r"^https?://", "", url, flags=re.IGNORECASE)
    url = url.lower()
    slug = _SLUG_RE.sub("-", url).strip("-")
    return slug[:100]


def content_bytes(pages: list[dict[str, Any]]) -> int:
    """Return the total bytes of extracted markdown across a list of crawl pages.

    How `crawl_site` reports the size of what it archived. It was once the signal the
    two-engine ladder branched on; with one engine there is nothing to branch between,
    and it is simply a measurement.

    Counts UTF-8 **bytes**, not characters, so a page of accented or CJK text is not
    undercounted.

    Args:
        pages: Page dicts as produced by `local_browser.crawl_site()`. A missing or
            None "markdown" key contributes zero rather than raising.

    Returns:
        Total markdown size in bytes; 0 for an empty list.
    """
    return sum(len((page.get("markdown") or "").encode("utf-8")) for page in pages)


class FirecrawlClient:
    """Thin wrapper around the Firecrawl REST API v1 (https://api.firecrawl.dev/v1).

    Authentication is via Bearer token in the Authorization header. All requests
    use a 30-second timeout via the `requests` library (already a dependency of
    ibkr_core_mcp). No retries are performed internally — callers handle retry
    logic at the ClaudeToolkit layer.

    One endpoint is implemented, because one is all that is still needed:
      - POST /v1/search  (firecrawl_search tool)

    The crawl endpoints were removed on 2026-07-30 — `crawl_site` does that job with
    the local browser, faster and free.

    Args:
        api_key: Firecrawl API key (fc-...). Must be non-empty; validated at
                 construction time with a ValueError if blank.
    """

    BASE_URL = "https://api.firecrawl.dev/v1"

    def __init__(self, api_key: str) -> None:
        """Store the API key and build the Bearer auth headers.

        Args:
            api_key: Firecrawl API key (`fc-…`).

        Raises:
            ValueError: If `api_key` is empty. Checked here so a missing key
                surfaces at construction rather than as a confusing 401 later.
        """
        if not api_key:
            raise ValueError("api_key must be non-empty")
        self._api_key = api_key
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def _raise_for_status(self, resp: requests.Response) -> None:
        """Translate Firecrawl HTTP errors into FirecrawlError with a status code.

        Every HTTP failure leaves this client as a FirecrawlError, never as a raw
        requests.HTTPError — callers (and ClaudeToolkit's handler) catch one exception
        type, and crawl()'s escalation logic can read `status_code` to decide whether a
        retry could possibly help.
        """
        if resp.status_code == 401:
            raise FirecrawlError("Invalid FIRECRAWL_API_KEY", 401)
        if resp.status_code == 402:
            raise FirecrawlError("Firecrawl account is out of credits", 402)
        if resp.status_code == 429:
            raise FirecrawlError("Rate limit exceeded — wait before retrying", 429)
        if resp.status_code >= 500:
            raise FirecrawlError(f"Firecrawl service error: {resp.status_code}", resp.status_code)
        if resp.status_code >= 400:
            raise FirecrawlError(f"Firecrawl request failed: HTTP {resp.status_code}", resp.status_code)

    def _scrape_options(
        self,
        *,
        wait_for_ms: int | None = None,
        proxy: str | None = None,
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        """Build the Firecrawl `scrapeOptions` payload shared by search() and crawl().

        One builder for both endpoints so their request bodies cannot drift apart, and
        so a future v2 migration has exactly one seam to change.

        Every option is omitted when None rather than sent as null, which keeps an
        options-free call byte-for-byte identical to the request this client sent before
        these parameters existed.

        Field reference (all confirmed present in v1 scrapeOptions):
        https://docs.firecrawl.dev/v1/api-reference/endpoint/crawl-post (verified 2026-07-25)

        Args:
            wait_for_ms: Milliseconds to wait for JavaScript rendering before extracting.
                0 is meaningful ("don't wait") and is passed through; only None omits it.
            proxy: One of "basic" (1 credit), "enhanced" (up to 5 credits), or "auto"
                (basic, retried through enhanced on failure).
            timeout_ms: Per-page scrape timeout in milliseconds, distinct from this
                client's own polling budget.

        Returns:
            The scrapeOptions dict to embed in a /search or /crawl request body.
        """
        options: dict[str, Any] = {"formats": ["markdown"]}
        if wait_for_ms is not None:
            options["waitFor"] = wait_for_ms
        if proxy is not None:
            options["proxy"] = proxy
        if timeout_ms is not None:
            options["timeout"] = timeout_ms
        return options

    def search(
        self,
        query: str,
        limit: int = 5,
        *,
        wait_for_ms: int | None = None,
        proxy: str | None = None,
        timeout_ms: int | None = None,
    ) -> list[dict[str, Any]]:
        """Search the web and return full page content as markdown for each result.

        Calls POST /v1/search with scrapeOptions.formats=["markdown"] so that
        each result includes extracted markdown rather than raw HTML.

        Args:
            query: Free-text search query. Must be non-empty.
            limit: Maximum number of results to return. Clamped to [1, 10].
            wait_for_ms: Advanced override — milliseconds to wait for JavaScript
                rendering before extraction. See _scrape_options.
            proxy: Advanced override — "basic", "enhanced", or "auto". See
                _scrape_options. Note "enhanced"/"auto" can cost up to 5 credits.
            timeout_ms: Advanced override — per-page scrape timeout in milliseconds.

        Returns:
            List of result dicts, each containing:
              - "url": str   — source URL
              - "title": str — page title (empty string if not present)
              - "markdown": str — extracted markdown content (empty string if not present)
              - "metadata": dict — Firecrawl's raw per-result metadata (statusCode:
                int, error: str|null, etc., empty dict if not present). Passed to
                `assess_quality` by `_handle_firecrawl_search`, which is the only
                caller with a real HTTP status to judge by, so it is the only one
                where that function's status branch can fire.
                Schema: https://docs.firecrawl.dev/api-reference/endpoint/search

        Raises:
            FirecrawlError: On HTTP 401 (bad key), 429 (rate limit), 5xx (service error),
                            or any non-200 response. status_code is set on the exception.
            ValueError: If query is empty or limit is outside [1, 10] before the call.
            requests.exceptions.Timeout: If the API does not respond within 30 seconds.
        """
        if not query:
            raise ValueError("query must be non-empty")
        limit = max(1, min(10, limit))
        resp = _request_with_backoff(
            lambda: requests.post(
                f"{self.BASE_URL}/search",
                headers=self._headers,
                json={
                    "query": query,
                    "limit": limit,
                    "scrapeOptions": self._scrape_options(wait_for_ms=wait_for_ms, proxy=proxy, timeout_ms=timeout_ms),
                },
                timeout=30,
            )
        )
        self._raise_for_status(resp)
        data = resp.json()
        raw = data.get("data") or data.get("results") or []
        return [
            {
                "url": r.get("url", ""),
                "title": r.get("title", ""),
                "markdown": r.get("markdown", "") or r.get("content", ""),
                "metadata": r.get("metadata", {}),
            }
            for r in raw
        ]


class WebDocsStore:
    """Persist Firecrawl crawl and search results to Google Drive under a 'web_docs/'
    subfolder, using the same Drive credentials already in use by GDriveCache.

    Drive folder layout (auto-created on first use):
      <gdrive_folder_id>/
        web_docs/               ← created by _get_web_docs_folder_id if not overridden
          <url-slug>/           ← one subfolder per crawled domain
            index.json          ← manifest: {url, crawled_at, pages: [{url, file_id}]}
            <page-slug>.md      ← one file per crawled page
          searches/             ← flat folder for search snapshots
            <YYYYMMDDTHHMMSSz>-<query-slug>.md

    Override the web_docs/ root by setting gdrive_web_docs_folder_id in Config.

    Args:
        config: ibkr_core_mcp Config instance. Uses gdrive_token_file,
                gdrive_credentials_file, gdrive_folder_id, and
                gdrive_web_docs_folder_id.
    """

    _SCOPES = ["https://www.googleapis.com/auth/drive"]

    def __init__(self, config: Config) -> None:
        """Prepare the store without contacting Drive.

        The Drive service is built lazily on first use, so construction performs
        no OAuth and no network I/O.

        Args:
            config: Supplies `gdrive_web_docs_folder_id` and the credential/token
                paths used by the OAuth flow.
        """
        self._cfg = config
        self._svc: Any = None

    def _get_service(self) -> Any:
        """Return a cached Google Drive API v3 service, running the OAuth flow if needed.

        Mirrors GDriveCache._get_service(): checks for an existing token file, refreshes
        expired credentials, or falls back to InstalledAppFlow (opens local browser on port 0).
        Token is written with mode 0o600 (user-only read/write).

        Source: https://developers.google.com/drive/api/quickstart/python
        """
        if self._svc is not None:
            return self._svc
        creds = None
        if self._cfg.gdrive_token_file.exists():
            creds = Credentials.from_authorized_user_file(  # type: ignore[no-untyped-call]
                str(self._cfg.gdrive_token_file), self._SCOPES
            )
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(str(self._cfg.gdrive_credentials_file), self._SCOPES)
                creds = flow.run_local_server(port=0)
            import os

            self._cfg.gdrive_token_file.parent.mkdir(parents=True, exist_ok=True)
            token_path = str(self._cfg.gdrive_token_file)
            fd = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as fh:
                fh.write(creds.to_json())
            os.chmod(token_path, 0o600)
        self._svc = build("drive", "v3", credentials=creds)
        return self._svc

    def _find_or_create_folder(self, name: str, parent_id: str) -> str:
        """Return the Drive ID of a folder by name under parent_id, creating it if absent."""
        svc = self._get_service()
        q = (
            f"name='{name}' and mimeType='application/vnd.google-apps.folder'"
            f" and '{parent_id}' in parents and trashed=false"
        )
        result = svc.files().list(q=q, fields="files(id)").execute()
        files = result.get("files", [])
        if files:
            return str(files[0]["id"])
        meta = {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_id],
        }
        created = svc.files().create(body=meta, fields="id").execute()
        return str(created["id"])

    def _get_web_docs_folder_id(self) -> str:
        """Return the web_docs/ root folder ID, using config override or auto-creating it."""
        if self._cfg.gdrive_web_docs_folder_id:
            return self._cfg.gdrive_web_docs_folder_id
        return self._find_or_create_folder("web_docs", self._cfg.gdrive_folder_id)

    def get_cached_crawl(self, url: str, max_age_hours: float = 48.0) -> dict[str, Any] | None:
        """Return the existing Drive manifest for `url` (from a prior save_crawl call)
        if one exists and is younger than max_age_hours, else None.

        Lets callers skip an entire Firecrawl API call when a recent crawl is
        already archived — the missing piece that let repeated runs (e.g. a docs
        verification pass re-checking the same reference URLs) re-fetch every URL
        every time and cascade into Firecrawl's own rate limit.

        max_age_hours default (48h) is informed by Firecrawl's own `scrapeOptions.maxAge`
        cache parameter on the **v2** `/crawl` endpoint (172800000ms = 48h default) — but
        this repo's `BASE_URL` targets Firecrawl's **v1** API
        (https://api.firecrawl.dev/v1), where the same parameter's documented default is
        actually `0` (caching disabled) per
        https://docs.firecrawl.dev/v1/api-reference/endpoint/crawl-post (verified
        2026-07-14). So 48h is NOT "the same default Firecrawl already uses" for what we
        actually call — it's this repo's own deliberate choice, using Firecrawl's v2
        default as a reasonable, externally-validated reference point for "how fresh is
        fresh enough" for reference documentation content (which doesn't change multiple
        times a day), rather than an arbitrary number invented from nothing. Pass a
        smaller max_age_hours (or skip this check) for a job that needs a shorter window,
        e.g. a future scheduled refresh job.

        Never creates or writes anything — a pure read. (One minor exception: if no
        `gdrive_web_docs_folder_id` override is configured, the underlying
        `_get_web_docs_folder_id()` lookup will auto-create the empty `web_docs/`
        root folder if it doesn't exist yet, same as every other method on this
        class — harmless, and it would be created on the next save_crawl anyway.)

        Args:
            url: The root URL that was crawled (same value passed to save_crawl).
            max_age_hours: Maximum manifest age to treat as still fresh.

        Returns:
            The manifest dict ({url, crawled_at, pages}) if a fresh cached entry
            exists, else None (no entry at all, or it's older than max_age_hours).
        """
        svc = self._get_service()
        web_docs_id = self._get_web_docs_folder_id()
        slug = _slugify(url)

        slug_q = (
            f"name='{slug}' and mimeType='application/vnd.google-apps.folder'"
            f" and '{web_docs_id}' in parents and trashed=false"
        )
        slug_folders = svc.files().list(q=slug_q, fields="files(id)").execute().get("files", [])
        if not slug_folders:
            return None
        slug_folder_id = slug_folders[0]["id"]

        index_q = f"name='index.json' and '{slug_folder_id}' in parents and trashed=false"
        index_files = svc.files().list(q=index_q, fields="files(id)").execute().get("files", [])
        if not index_files:
            return None

        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, svc.files().get_media(fileId=index_files[0]["id"]))
        done = False
        while not done:
            _, done = downloader.next_chunk()
        manifest: dict[str, Any] = json.loads(buf.getvalue())

        crawled_at = datetime.fromisoformat(manifest["crawled_at"])
        age_hours = (datetime.now(UTC) - crawled_at).total_seconds() / 3600
        if age_hours > max_age_hours:
            return None
        return manifest

    def save_crawl(self, url: str, pages: list[dict[str, str]]) -> dict[str, Any]:
        """Save crawl results to Drive under web_docs/{url-slug}/.

        Each page is uploaded as a .md file. If a file with the same name already
        exists, it is overwritten via Drive's Files.update method. Pages with empty
        or None markdown are skipped. An index.json manifest is always written (even
        for an empty crawl) so callers can detect previously-crawled URLs.

        Drive layout created by this method:
          web_docs/
            {slug}/
              {page-slug}.md    ← one per page
              index.json        ← {url, crawled_at, pages: [{url, file_id}]}

        Args:
            url: Root URL that was crawled (used to derive the subfolder slug).
            pages: List of page dicts from FirecrawlClient.crawl(), each with
                   "url" and "markdown" keys.

        Returns:
            Manifest dict: {url, crawled_at (ISO-8601 UTC), pages: [{url, file_id}]}

        Raises:
            WebDocsStoreError: If a Drive API call fails. Original exception is
                               chained via `raise ... from exc`.
        """
        svc = self._get_service()
        web_docs_id = self._get_web_docs_folder_id()
        slug = _slugify(url)
        folder_id = self._find_or_create_folder(slug, web_docs_id)

        manifest_pages: list[dict[str, str]] = []
        # filename -> the page_url that claimed it, this call only. Two distinct
        # URLs can _slugify to the same string (e.g. "/a-b" and "/a_b" both
        # collapse to "a-b"); without this, the second page's existence-check
        # would find the first page's just-created file and overwrite it.
        claimed_filenames: dict[str, str] = {}

        for page in pages:
            md = page.get("markdown") or ""
            if not md:
                continue
            page_url = page.get("url", "")
            base_slug = _slugify(page_url)
            filename = f"{base_slug}.md"
            suffix = 2
            while filename in claimed_filenames and claimed_filenames[filename] != page_url:
                filename = f"{base_slug}-{suffix}.md"
                suffix += 1
            claimed_filenames[filename] = page_url
            # Not named content_bytes: that is a module-level function in this file
            # (the ladder's sizing signal), and shadowing it here reads as a call site.
            md_bytes = md.encode("utf-8")
            media = MediaIoBaseUpload(io.BytesIO(md_bytes), mimetype="text/markdown", resumable=False)
            # Check if file already exists
            q = f"name='{filename}' and '{folder_id}' in parents and trashed=false"
            existing = svc.files().list(q=q, fields="files(id)").execute().get("files", [])
            try:
                if existing:
                    file_id = existing[0]["id"]
                    svc.files().update(fileId=file_id, media_body=media).execute()
                else:
                    meta = {"name": filename, "parents": [folder_id]}
                    result = svc.files().create(body=meta, media_body=media, fields="id").execute()
                    file_id = result["id"]
            except Exception as exc:
                raise WebDocsStoreError(f"Failed to upload {filename} to Drive") from exc
            manifest_pages.append({"url": page_url, "file_id": file_id})

        manifest = {
            "url": url,
            "crawled_at": datetime.now(UTC).isoformat(),
            "pages": manifest_pages,
        }
        manifest_content = json.dumps(manifest, indent=2).encode("utf-8")
        manifest_media = MediaIoBaseUpload(io.BytesIO(manifest_content), mimetype="application/json", resumable=False)
        index_q = f"name='index.json' and '{folder_id}' in parents and trashed=false"
        existing_index = svc.files().list(q=index_q, fields="files(id)").execute().get("files", [])
        try:
            if existing_index:
                svc.files().update(fileId=existing_index[0]["id"], media_body=manifest_media).execute()
            else:
                svc.files().create(
                    body={"name": "index.json", "parents": [folder_id]},
                    media_body=manifest_media,
                    fields="id",
                ).execute()
        except Exception as exc:
            raise WebDocsStoreError("Failed to write index.json to Drive") from exc

        return manifest

    def save_search(self, query: str, results: list[dict[str, str]]) -> str:
        """Save a search result snapshot to Drive under web_docs/searches/.

        Produces a single markdown file named {YYYYMMDDTHHMMSSz}-{query-slug}.md,
        containing the query and all result titles, URLs, and markdown bodies.

        The file is always created fresh (no overwrite check — each search is a
        new timestamped snapshot). Duplicate queries result in multiple files.

        Drive layout:
          web_docs/
            searches/
              {YYYYMMDDTHHMMSSz}-{query-slug}.md

        Args:
            query: The search query string, used in the filename and document header.
            results: List of result dicts from FirecrawlClient.search(), each with
                     "url", "title", and "markdown" keys.

        Returns:
            Drive file ID of the created snapshot file.

        Raises:
            WebDocsStoreError: If the Drive upload fails. Original exception chained.
        """
        svc = self._get_service()
        web_docs_id = self._get_web_docs_folder_id()
        searches_id = self._find_or_create_folder("searches", web_docs_id)

        now = datetime.now(UTC)
        ts = now.strftime("%Y%m%dT%H%M%SZ")
        filename = f"{ts}-{_slugify(query)}.md"

        lines = [f"# Search: {query}", f"*Saved: {now.isoformat()}*", ""]
        for i, r in enumerate(results, 1):
            lines.append(f"## {i}. {r.get('title', '(no title)')}")
            lines.append(f"**URL:** {r.get('url', '')}")
            lines.append("")
            lines.append(r.get("markdown", ""))
            lines.append("")
        content = "\n".join(lines).encode("utf-8")

        media = MediaIoBaseUpload(io.BytesIO(content), mimetype="text/markdown", resumable=False)
        meta = {"name": filename, "parents": [searches_id]}
        try:
            result = svc.files().create(body=meta, media_body=media, fields="id").execute()
        except Exception as exc:
            raise WebDocsStoreError(f"Failed to save search snapshot {filename}") from exc
        return str(result["id"])
