"""
Web scraping tools for ClaudIA, backed by the Firecrawl REST API v1.

Provides:
  FirecrawlClient   — search and crawl via https://api.firecrawl.dev/v1
  WebDocsStore      — persist crawl/search results to Google Drive under web_docs/
  _slugify          — convert a URL to a safe Drive filename stem
  FirecrawlError    — raised on Firecrawl API errors
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
    url = re.sub(r"^https?://", "", url, flags=re.IGNORECASE)
    url = url.lower()
    slug = _SLUG_RE.sub("-", url).strip("-")
    return slug[:100]
