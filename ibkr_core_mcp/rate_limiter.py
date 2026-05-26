from __future__ import annotations
import time
from typing import Callable
import requests

from ibkr_core_mcp.exceptions import IBKRAuthError, IBKRRateLimitError, IBKRAPIError

_DEFAULT_MAX_RETRIES = 3
_BASE_BACKOFF = 1.0  # seconds


def with_retry(
    fn: Callable[[], requests.Response],
    max_retries: int = _DEFAULT_MAX_RETRIES,
) -> requests.Response:
    """Call fn(), retrying on 429/503 with exponential backoff.

    Raises:
        IBKRAuthError: on 401 (no retry)
        IBKRRateLimitError: on 429 after retries exhausted
        IBKRAPIError: on other 4xx/5xx
    """
    attempt = 0
    while True:
        resp = fn()
        status = resp.status_code

        if 200 <= status < 300:
            return resp
        if status == 401:
            raise IBKRAuthError("IBKR session not authenticated (401)")
        if status in (429, 503):
            if attempt >= max_retries:
                raise IBKRRateLimitError(
                    f"Rate limit exceeded after {max_retries} retries (HTTP {status})"
                )
            backoff = _BASE_BACKOFF * (2 ** attempt)
            time.sleep(backoff)
            attempt += 1
            continue
        # Any other error status
        raise IBKRAPIError(
            f"IBKR gateway returned HTTP {status}", status_code=status
        )
