"""Web scraping tools for ClaudIA — Firecrawl primary + Crawl4AI fallback.

Primary layer: Firecrawl REST API v1 (https://api.firecrawl.dev/v1).
Fallback layer: Crawl4AI (Playwright-based, open-source) — defined in
  `scrape_fallback.py`. Activated by ClaudeToolkit._scrape_with_fallback()
  when assess_quality() classifies a Firecrawl result as "fallback" (empty,
  HTTP error, or <40 words) or "ambiguous" (paywall markers, 40–200 words)
  and judge_completeness_llm() confirms incompleteness.

This module provides the Firecrawl client and Drive persistence only.
The fallback decision logic, Crawl4AI scraper, and SSRF Playwright guard
live in scrape_fallback.py. Orchestration lives in claude_tools.py.

Provides:
  _slugify          — convert a URL to a safe Drive filename stem
  FirecrawlError    — raised on Firecrawl API errors
  WebDocsStoreError — raised on Drive persistence errors
  FirecrawlClient   — search and crawl via https://api.firecrawl.dev/v1
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

# Hard cap on how many "next" pagination chunks crawl() will follow after a
# completed job (see GET /v1/crawl/{id} docs: "next" pages the >10MB result).
# Guards against a misbehaving/looping cursor (e.g. an API bug that returns
# the same "next" URL forever) in addition to the seen-URL and deadline
# checks in crawl() itself.
_FIRECRAWL_MAX_NEXT_CHUNKS = 50

# Minimum total markdown a crawl must yield before it is treated as a success.
# Calibrated against this repo's own scrape cache (docs/audits/audit-evidence/scrapes/):
# the largest observed failure is a 152-byte Akamai edge-block page, and the smallest
# observed real documentation page is 12,933 bytes. 5 KB sits ~34x above the former
# and ~2.5x below the latter, and is set high enough to also catch partial extractions
# that returned something but plainly not a page. See
# docs/plans/2026-07-25-web-scraper-robustness-design.md section 3.1.
_MIN_USEFUL_BYTES = 5 * 1024

# Escalation options for a crawl that came back under _MIN_USEFUL_BYTES. Proven against
# interactivebrokers.com in docs/audits/audit-evidence/scrapes/manifest.json (2026-07-02):
# "retry with --wait-for 3000 --proxy auto succeeded after prior firecrawl-default and
# webfetch failures". Both are documented v1 scrapeOptions fields:
# https://docs.firecrawl.dev/v1/api-reference/endpoint/crawl-post (verified 2026-07-25).
_ESCALATION_WAIT_FOR_MS = 3000
_ESCALATION_PROXY = "auto"

# Floor for the escalated attempt's polling budget. Stealth is slower by construction —
# waitFor adds 3s per page and proxy="auto" retries a failed basic fetch through the
# enhanced proxy — so reusing a budget that just timed out would reproduce the timeout.
_ESCALATION_MIN_TIMEOUT_S = 180

# Firecrawl statuses where a stealth retry cannot help: a bad key, an empty credit
# balance, and an active rate limit are account-level, not page-level. Retrying burns
# time and money to fail identically, and in the 429 case worsens the throttling.
_NON_ESCALATING_STATUSES = frozenset({401, 402, 429})


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
        "https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/"
        → "www-interactivebrokers-com-campus-ibkr-api-page-cpapi-v1"

        "https://docs.firecrawl.dev/features/search"
        → "docs-firecrawl-dev-features-search"
    """
    url = re.sub(r"^https?://", "", url, flags=re.IGNORECASE)
    url = url.lower()
    slug = _SLUG_RE.sub("-", url).strip("-")
    return slug[:100]


def content_bytes(pages: list[dict[str, Any]]) -> int:
    """Return the total bytes of extracted markdown across a list of crawl pages.

    This is the single signal the recovery ladder branches on. The decision a caller
    actually needs is "did I get content?", which is a property of the output — not of
    how the attempt ended. Blocked, timed out, job-failed and completed-empty all
    produce the same next move, so they need no separate representation.

    Counts UTF-8 **bytes**, not characters, so a page of accented or CJK text is not
    undercounted into a false "blocked" verdict.

    Args:
        pages: Page dicts as returned by `FirecrawlClient.crawl()`. A missing or None
            "markdown" key contributes zero rather than raising, since Firecrawl returns
            both shapes for pages it failed to extract.

    Returns:
        Total markdown size in bytes; 0 for an empty list.
    """
    return sum(len((page.get("markdown") or "").encode("utf-8")) for page in pages)


def _resolve_timeout(max_pages: int, timeout_s: int | None) -> int:
    """Return the per-attempt polling budget in seconds for a crawl.

    `timeout_s` is this client's own polling patience, not Firecrawl's timeout — see
    FirecrawlClient.crawl(). The old fixed 120s default was under-budgeted for its own
    50-page default: a slow, JS-heavy site routinely exceeds it, manufacturing a
    "timed out with nothing" result that is not a block at all. Scaling with page count
    keeps small crawls fast while giving large ones room to finish.

    Args:
        max_pages: Page cap for this crawl, already clamped to [1, 100] by the caller.
        timeout_s: An explicit caller-supplied budget, or None to derive one.

    Returns:
        The explicit value (floored at 10s, matching the previous behavior), or
        `min(600, max(120, 6 * max_pages))` when none was supplied.
    """
    if timeout_s is not None:
        return max(10, timeout_s)
    return min(600, max(120, 6 * max_pages))


class FirecrawlClient:
    """Thin wrapper around the Firecrawl REST API v1 (https://api.firecrawl.dev/v1).

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
              - "metadata": dict — Firecrawl's raw per-result metadata (statusCode,
                error, etc., empty dict if not present), used by ClaudeToolkit's
                Crawl4AI fallback (assess_quality) to judge extraction quality

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

    def _attempt(
        self,
        url: str,
        max_pages: int,
        timeout_s: int,
        scrape_options: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Run one crawl attempt, converting every recoverable failure into an empty
        page list so the caller has something to measure.

        This is the piece that makes the recovery ladder possible. Previously a crawl
        could end three different ways — a raised FirecrawlError on a failed job, a raw
        requests.HTTPError mid-poll, or a silent empty return on deadline — so there was
        no single point at which "we got nothing" was decided, and therefore nowhere to
        attach recovery. Every route now ends in a list.

        Args:
            url: Root URL to crawl.
            max_pages: Page cap, already clamped.
            timeout_s: Polling budget, already resolved.
            scrape_options: The scrapeOptions payload for this attempt.

        Returns:
            The attempt's pages, or [] if it failed recoverably.

        Raises:
            FirecrawlError: For account-level failures only (401 bad key, 402 out of
                credits, 429 rate limited). A slower, more expensive retry cannot fix
                any of them, and in the 429 case would worsen the throttling — so these
                propagate rather than consuming an escalation.
        """
        try:
            return self._try_crawl(url, max_pages, timeout_s, scrape_options)
        except FirecrawlError as exc:
            if exc.status_code in _NON_ESCALATING_STATUSES:
                raise
            log.warning("firecrawl crawl attempt for %s failed: %s", url, exc)
            return []
        except requests.RequestException as exc:
            log.warning("firecrawl crawl attempt for %s failed: %s", url, exc)
            return []

    def _try_crawl(
        self,
        url: str,
        max_pages: int,
        timeout_s: int,
        scrape_options: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Run exactly one Firecrawl crawl attempt: start the job, poll it, follow
        pagination, and return whatever pages it produced.

        Callers pass an already-clamped `max_pages` and an already-resolved `timeout_s`
        (see _resolve_timeout), plus a prepared scrapeOptions dict (see _scrape_options).
        The retry/escalation decision belongs to crawl(), not here — this method's only
        job is to execute one attempt faithfully.

        Firecrawl crawls are asynchronous. This method:
          1. Starts the job with POST /v1/crawl
          2. Polls GET /v1/crawl/{id} every 5 seconds until status == "completed"
             or timeout_s seconds have elapsed
          3. Once status == "completed", follows the response's "next" pagination
             cursor (present when the crawl's result exceeds 10MB — see
             https://docs.firecrawl.dev/api-reference/endpoint/crawl-get) until it
             is absent, accumulating every chunk's pages before returning. This
             is bounded by the same timeout_s deadline as step 2, plus a hard
             cap on chunk count and a repeated-cursor guard, so pagination
             itself can never hang or exceed the requested wall-clock budget
          4. Returns all pages collected so far (partial results on timeout)

        On timeout, a warning is logged and whatever pages were collected are
        returned. The return value is never raised on timeout — callers receive
        whatever Firecrawl had completed.

        Args:
            url: Root URL to crawl from. Must be a public http/https URL. The
                 caller (ClaudeToolkit handler) is responsible for SSRF validation
                 before calling this method. Note this only validates the root —
                 the individual page URLs in the returned list (which Firecrawl
                 itself discovered via internal links/redirects) are NOT
                 pre-validated here and are re-checked independently by
                 ClaudeToolkit._validate_public_url before any local fetch of
                 them (e.g. the Crawl4AI fallback).
            max_pages: Page cap, already clamped to [1, 100].
            timeout_s: Polling budget in seconds, already resolved. If the job is
                       still running at timeout, partial results are returned rather
                       than raising an error.
            scrape_options: The scrapeOptions payload to send.

        Returns:
            List of page dicts, each containing:
              - "url": str      — source URL for the page
              - "markdown": str — full markdown content of the page, or "" if empty/None
              - "metadata": dict — Firecrawl's raw per-page metadata (statusCode,
                error, etc.), used by callers to assess extraction quality

            No pages are filtered out — empty-markdown and error pages are included
            so callers (e.g. the Crawl4AI fallback) can see and recover from them
            instead of having them silently dropped.

        Raises:
            FirecrawlError: If the crawl job transitions to status "failed", or if
                            the API returns a non-200 response on job start or poll.
            requests.exceptions.Timeout: If a single API call exceeds 30 seconds
                                         (distinct from the overall timeout_s limit).
        """
        # Start crawl job
        resp = _request_with_backoff(
            lambda: requests.post(
                f"{self.BASE_URL}/crawl",
                headers=self._headers,
                json={"url": url, "limit": max_pages, "scrapeOptions": scrape_options},
                timeout=30,
            )
        )
        self._raise_for_status(resp)
        job_id = resp.json()["id"]

        def _pages_from(data: dict[str, Any]) -> list[dict[str, Any]]:
            return [
                {
                    "url": p.get("metadata", {}).get("sourceURL", p.get("url", "")),
                    "markdown": p.get("markdown") or "",
                    "metadata": p.get("metadata", {}),
                }
                for p in (data.get("data") or [])
            ]

        def _fetch_next(next_page_url: str) -> requests.Response:
            # A plain nested function (not a loop-body lambda) so next_page_url
            # is this call's own parameter, not a mutating loop variable.
            return _request_with_backoff(
                lambda: requests.get(
                    next_page_url,
                    headers=self._headers,
                    timeout=30,
                )
            )

        # Poll for completion
        deadline = time.monotonic() + timeout_s
        pages: list[dict[str, Any]] = []

        while time.monotonic() < deadline:
            time.sleep(5)
            poll = _request_with_backoff(
                lambda: requests.get(
                    f"{self.BASE_URL}/crawl/{job_id}",
                    headers=self._headers,
                    timeout=30,
                )
            )
            self._raise_for_status(poll)
            data = poll.json()
            status = data.get("status", "")

            pages = _pages_from(data)

            if status == "completed":
                # Result exceeded 10MB — Firecrawl paginates via "next", a
                # fully-formed URL to the next chunk of `data` (not a delta;
                # append, don't replace). Absent/null "next" means done.
                #
                # Bounded three ways so a misbehaving/looping cursor or a very
                # large paginated result can't hang or blow past the caller's
                # requested timeout_s: a hard chunk-count cap, a seen-URL guard
                # against a cursor that fails to advance, and the same
                # wall-clock deadline the outer poll loop honors.
                next_url = data.get("next")
                seen_next_urls: set[str] = set()
                chunks_fetched = 0
                while next_url:
                    if next_url in seen_next_urls:
                        log.warning(
                            "firecrawl crawl next-cursor repeated — stopping pagination early with %d pages",
                            len(pages),
                        )
                        break
                    if chunks_fetched >= _FIRECRAWL_MAX_NEXT_CHUNKS:
                        log.warning(
                            "firecrawl crawl hit the %d-chunk pagination cap — stopping early with %d pages",
                            _FIRECRAWL_MAX_NEXT_CHUNKS,
                            len(pages),
                        )
                        break
                    if time.monotonic() >= deadline:
                        log.warning(
                            "firecrawl crawl pagination exceeded timeout_s=%ds — returning %d partial pages",
                            timeout_s,
                            len(pages),
                        )
                        break
                    seen_next_urls.add(next_url)
                    next_resp = _fetch_next(next_url)
                    self._raise_for_status(next_resp)
                    next_data = next_resp.json()
                    pages.extend(_pages_from(next_data))
                    next_url = next_data.get("next")
                    chunks_fetched += 1
                return pages
            if status == "failed":
                raise FirecrawlError(f"Crawl job failed: {data.get('error', 'unknown error')}")

        log.warning(
            "firecrawl crawl timed out after %ds — returning %d partial pages",
            timeout_s,
            len(pages),
        )
        return pages

    def crawl(
        self,
        url: str,
        max_pages: int = 50,
        timeout_s: int | None = None,
        *,
        wait_for_ms: int | None = None,
        proxy: str | None = None,
    ) -> list[dict[str, Any]]:
        """Crawl a site starting from url and return all pages as markdown.

        Runs up to two Firecrawl attempts. The first uses cheap defaults. If it yields
        less than _MIN_USEFUL_BYTES of markdown — whether because the site blocked us,
        the job failed, the budget ran out, or the pages came back empty — a second
        attempt runs with waitFor and an anti-bot proxy, options proven against
        interactivebrokers.com (see _ESCALATION_WAIT_FOR_MS).

        The better of the two results is returned, so the ladder is monotonic: it can
        never hand back less than the first attempt already produced, and a thin
        escalated result can never silently replace a good cheap one. That is what makes
        a threshold this aggressive safe — a legitimately short page costs a wasted
        retry, never a wrong answer.

        A caller that still gets nothing should fall back to a local scrape;
        ClaudeToolkit._handle_firecrawl_crawl does exactly that with Crawl4AI.

        Args:
            url: Root URL to crawl from. Must be a public http/https URL. The caller is
                responsible for SSRF validation. Note this only validates the root — the
                individual page URLs in the returned list were discovered by Firecrawl
                and are re-checked independently by ClaudeToolkit._validate_public_url
                before any local fetch of them.
            max_pages: Upper bound on pages to crawl. Clamped to [1, 100].
            timeout_s: Polling budget **per attempt**, in seconds. None derives one from
                max_pages (see _resolve_timeout). Worst-case wall clock is therefore
                roughly twice this value when both attempts run.
            wait_for_ms: Advanced override for the first attempt's JS render wait. The
                escalated attempt uses _ESCALATION_WAIT_FOR_MS unless this is set, in
                which case the caller's value is respected on both attempts.
            proxy: Advanced override for the first attempt's proxy mode, same handling
                as wait_for_ms. "enhanced"/"auto" can cost up to 5 credits per page.

        Returns:
            Page dicts with "url", "markdown" and "metadata" keys. Empty-markdown and
            error pages are included, not filtered, so callers can see and recover from
            them. Returns [] when both attempts came back with nothing.

        Raises:
            FirecrawlError: Only for account-level failures — 401 (invalid key), 402
                (out of credits), 429 (rate limited). Note this method no longer raises
                when the crawl job itself reports "failed"; that case escalates and then
                returns whatever the ladder produced, which is the point of the ladder.
        """
        max_pages = max(1, min(100, max_pages))
        resolved_timeout = _resolve_timeout(max_pages, timeout_s)

        first = self._attempt(
            url,
            max_pages,
            resolved_timeout,
            self._scrape_options(wait_for_ms=wait_for_ms, proxy=proxy),
        )
        if content_bytes(first) >= _MIN_USEFUL_BYTES:
            return first

        log.warning(
            "firecrawl crawl of %s returned %d B (under the %d B threshold) — retrying with waitFor and an anti-bot proxy",
            url,
            content_bytes(first),
            _MIN_USEFUL_BYTES,
        )
        second = self._attempt(
            url,
            max_pages,
            max(resolved_timeout, _ESCALATION_MIN_TIMEOUT_S),
            self._scrape_options(
                wait_for_ms=_ESCALATION_WAIT_FOR_MS if wait_for_ms is None else wait_for_ms,
                proxy=_ESCALATION_PROXY if proxy is None else proxy,
            ),
        )
        # max() returns the first maximal element, so a tie keeps the cheaper rung.
        return max(first, second, key=content_bytes)


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
            content_bytes = md.encode("utf-8")
            media = MediaIoBaseUpload(io.BytesIO(content_bytes), mimetype="text/markdown", resumable=False)
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
