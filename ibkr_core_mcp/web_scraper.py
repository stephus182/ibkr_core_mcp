"""
Web scraping tools for ClaudIA, backed by the Firecrawl REST API v1.

Currently provides:
  _slugify          — convert a URL to a safe Drive filename stem
  FirecrawlError    — raised on Firecrawl API errors
  WebDocsStoreError — raised on Drive persistence errors

Added by subsequent tasks in this module:
  FirecrawlClient   — search and crawl via https://api.firecrawl.dev/v1
  WebDocsStore      — persist crawl/search results to Google Drive under web_docs/
"""
from __future__ import annotations

import io
import json
import logging
import re
import time
from datetime import UTC, datetime
from typing import Any

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
    url = re.sub(r"^https?://", "", url, flags=re.IGNORECASE)
    url = url.lower()
    slug = _SLUG_RE.sub("-", url).strip("-")
    return slug[:100]


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


class WebDocsStore:
    """
    Persist Firecrawl crawl and search results to Google Drive under a 'web_docs/'
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
        self._cfg = config
        self._svc: Any = None

    def _get_service(self) -> Any:
        """Return a cached Google Drive API v3 service, refreshing credentials if needed."""
        if self._svc is not None:
            return self._svc
        creds = Credentials.from_authorized_user_file(
            str(self._cfg.gdrive_token_file), self._SCOPES
        )
        if not creds.valid and creds.expired and creds.refresh_token:
            creds.refresh(Request())
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
            return files[0]["id"]
        meta = {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_id],
        }
        created = svc.files().create(body=meta, fields="id").execute()
        return created["id"]

    def _get_web_docs_folder_id(self) -> str:
        """Return the web_docs/ root folder ID, using config override or auto-creating it."""
        if self._cfg.gdrive_web_docs_folder_id:
            return self._cfg.gdrive_web_docs_folder_id
        return self._find_or_create_folder("web_docs", self._cfg.gdrive_folder_id)

    def save_crawl(self, url: str, pages: list[dict[str, str]]) -> dict:
        """
        Save crawl results to Drive under web_docs/{url-slug}/.

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

        for page in pages:
            md = page.get("markdown") or ""
            if not md:
                continue
            page_url = page.get("url", "")
            filename = f"{_slugify(page_url)}.md"
            content_bytes = md.encode("utf-8")
            media = MediaIoBaseUpload(
                io.BytesIO(content_bytes), mimetype="text/markdown", resumable=False
            )
            # Check if file already exists
            q = f"name='{filename}' and '{folder_id}' in parents and trashed=false"
            existing = svc.files().list(q=q, fields="files(id)").execute().get("files", [])
            try:
                if existing:
                    file_id = existing[0]["id"]
                    svc.files().update(
                        fileId=file_id, media_body=media
                    ).execute()
                else:
                    meta = {"name": filename, "parents": [folder_id]}
                    result = svc.files().create(
                        body=meta, media_body=media, fields="id"
                    ).execute()
                    file_id = result["id"]
            except Exception as exc:
                raise WebDocsStoreError(
                    f"Failed to upload {filename} to Drive"
                ) from exc
            manifest_pages.append({"url": page_url, "file_id": file_id})

        manifest = {
            "url": url,
            "crawled_at": datetime.now(UTC).isoformat(),
            "pages": manifest_pages,
        }
        manifest_content = json.dumps(manifest, indent=2).encode("utf-8")
        manifest_media = MediaIoBaseUpload(
            io.BytesIO(manifest_content), mimetype="application/json", resumable=False
        )
        index_q = f"name='index.json' and '{folder_id}' in parents and trashed=false"
        existing_index = (
            svc.files().list(q=index_q, fields="files(id)").execute().get("files", [])
        )
        try:
            if existing_index:
                svc.files().update(
                    fileId=existing_index[0]["id"], media_body=manifest_media
                ).execute()
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
        """
        Save a search result snapshot to Drive under web_docs/searches/.

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

        media = MediaIoBaseUpload(
            io.BytesIO(content), mimetype="text/markdown", resumable=False
        )
        meta = {"name": filename, "parents": [searches_id]}
        try:
            result = svc.files().create(body=meta, media_body=media, fields="id").execute()
        except Exception as exc:
            raise WebDocsStoreError(f"Failed to save search snapshot {filename}") from exc
        return result["id"]
