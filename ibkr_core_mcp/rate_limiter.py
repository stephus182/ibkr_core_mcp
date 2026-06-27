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

    CP API rate limits (verified 2026-06-26 from official docs):
    Global limit: 10 requests/second for any endpoint not in the table below.
    Violators receive HTTP 429; IP is put in a penalty box for 15 minutes.
    Repeat violators may be permanently blocked.

    Per-endpoint limits (official table):
      /iserver/account/orders        GET   1 req/5 secs
      /iserver/account/pnl/partitioned GET 1 req/5 secs
      /iserver/account/trades        GET   1 req/5 secs
      /iserver/marketdata/history    GET   5 concurrent requests
      /iserver/marketdata/snapshot   GET   10 req/s
      /iserver/scanner/params        GET   1 req/15 mins
      /iserver/scanner/run           POST  1 req/sec
      /pa/performance                POST  1 req/15 mins
      /pa/summary                    POST  1 req/15 mins
      /pa/transactions               POST  1 req/15 mins
      /portfolio/accounts            GET   1 req/5 secs
      /portfolio/subaccounts         GET   1 req/5 secs
      /sso/validate                  GET   1 req/min
      /tickle                        GET   1 req/sec
    Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#rate-limiting

    Historical data pacing rules (from TWS API docs, verified 2026-06-26):
    - No identical requests within 15 seconds
    - No 6+ requests for the same contract/exchange/tick type within 2 seconds
    - No more than 60 requests in any 10-minute rolling window
    - Max 50 concurrent open historical data requests
    - BID_ASK tick type counts as 2 requests against all of the above limits
    - Bars >30 seconds: historical data limitations have been lifted (per official docs)
    Source: https://interactivebrokers.github.io/tws-api/historical_limitations.html
    Note: these are TWS API pacing rules — not confirmed to apply identically to
    CP API REST (/iserver/marketdata/history) endpoints. Applied here as a
    conservative default given the shared IBKR infrastructure.

    Flex Web Service rate limits (error 1018, verified against official error code table):
    max 1 request/second, 10 requests/minute per token. Enforced separately in flex_query.py.
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
