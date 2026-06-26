from __future__ import annotations

import time
from collections.abc import Callable

import requests

from ibkr_core_mcp.exceptions import IBKRAPIError, IBKRAuthError, IBKRRateLimitError

_DEFAULT_MAX_RETRIES = 3
_BASE_BACKOFF = 1.0  # seconds


def with_retry(
    fn: Callable[[], requests.Response],
    max_retries: int = _DEFAULT_MAX_RETRIES,
) -> requests.Response:
    """Call fn(), retrying on 429/503 with exponential backoff.

    Retry strategy: base 1s, 2× factor, 3 retries (delays: 1s, 2s, 4s).
    No Retry-After header parsing — IBKR Client Portal API does not document
    a Retry-After header in its public reference. Fixed exponential backoff
    is used as a safe default.

    IBKR Client Portal does not publish per-endpoint rate limits in public docs.
    The CP API reference requires authentication:
    https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/

    Historical data rate limits (from TWS API docs — likely shared infrastructure):
    - No identical requests within 15 seconds
    - No 6+ requests for the same contract within 2 seconds
    - No 60+ requests in any 10-minute window
    - Max 50 concurrent open historical data requests
    Source: https://interactivebrokers.github.io/tws-api/historical_limitations.html
    Note: TWS API pacing rules — not confirmed to apply to CP API REST endpoints.

    Note: Flex Web Service has documented rate limits (error 1018: max 1 req/s,
    10 req/min per token). Those are enforced separately in flex_query.py.
    Source: https://www.ibkrguides.com/clientportal/performanceandstatements/flex3error.htm

    Raises:
        IBKRAuthError: on 401 (no retry — session must be re-established)
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
