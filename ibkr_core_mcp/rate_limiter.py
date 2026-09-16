"""Proactive per-endpoint pacing and exponential backoff for IBKR Client Portal requests.

Two halves, and until 2026-09-16 only the second existed: `EndpointPacer` spaces requests
so a published limit is not broken, and `with_retry` survives the 429 when one is anyway.
Described as a "token bucket" in three documents for months; it is a sliding window, which
is what IBKR's limits are actually written as (N requests per fixed period).
"""

from __future__ import annotations

import re
import threading
import time
import warnings
from collections import deque
from collections.abc import Callable

import requests

from ibkr_core_mcp.exceptions import IBKRAPIError, IBKRAuthError, IBKRRateLimitError

_DEFAULT_MAX_RETRIES = 3
_BASE_BACKOFF = 1.0  # seconds

# Requests per window, in seconds, per endpoint — IBKR's published pacing table, verbatim
# and executable. Re-read from the source page 2026-09-16 and diffed row by row against
# the copy that used to live in `with_retry`'s docstring: 25 of 26 rows agreed and
# `/iserver/marketdata/history` did not, because IBKR changed it. There is deliberately
# no second, prose copy of this table anywhere in the package — a stale duplicate is
# what API-03 was.
#
# `{placeholder}` segments are matched positionally, the way the source page writes them.
# A tuple of tuples because an endpoint may carry more than one limit at once, and
# history does: both bind.
#
# Source: https://www.interactivebrokers.com/docs/web-api/v1/pacing-limitations
_PER_SECOND = ((1, 1.0),)
_PER_FIVE_SECONDS = ((1, 5.0),)
_PER_FIFTEEN_MINUTES = ((1, 900.0),)

ENDPOINT_LIMITS: dict[tuple[str, str], tuple[tuple[int, float], ...]] = {
    ("/fyi/unreadnumber", "GET"): _PER_SECOND,
    ("/fyi/settings", "GET"): _PER_SECOND,
    ("/fyi/settings/{typecode}", "POST"): _PER_SECOND,
    ("/fyi/disclaimer/{typecode}", "GET"): _PER_SECOND,
    ("/fyi/disclaimer/{typecode}", "PUT"): _PER_SECOND,
    ("/fyi/deliveryoptions", "GET"): _PER_SECOND,
    ("/fyi/deliveryoptions/email", "PUT"): _PER_SECOND,
    ("/fyi/deliveryoptions/device", "POST"): _PER_SECOND,
    ("/fyi/deliveryoptions/{deviceId}", "DELETE"): _PER_SECOND,
    ("/fyi/notifications", "GET"): _PER_SECOND,
    ("/fyi/notifications/more", "GET"): _PER_SECOND,
    ("/fyi/notifications/{notificationId}", "PUT"): _PER_SECOND,
    ("/iserver/account/orders", "GET"): _PER_FIVE_SECONDS,
    ("/iserver/account/pnl/partitioned", "GET"): _PER_FIVE_SECONDS,
    ("/iserver/account/trades", "GET"): _PER_FIVE_SECONDS,
    ("/iserver/marketdata/history", "GET"): ((10, 1.0), (50, 60.0)),
    ("/iserver/marketdata/snapshot", "GET"): ((10, 1.0),),
    ("/iserver/scanner/params", "GET"): _PER_FIFTEEN_MINUTES,
    ("/iserver/scanner/run", "POST"): _PER_SECOND,
    ("/pa/performance", "POST"): _PER_FIFTEEN_MINUTES,
    ("/pa/summary", "POST"): _PER_FIFTEEN_MINUTES,
    ("/pa/transactions", "POST"): _PER_FIFTEEN_MINUTES,
    ("/portfolio/accounts", "GET"): _PER_FIVE_SECONDS,
    ("/portfolio/subaccounts", "GET"): _PER_FIVE_SECONDS,
    ("/sso/validate", "GET"): _PER_SECOND,
    ("/tickle", "GET"): _PER_SECOND,
}

# "Any endpoint not listed in the table below follows the global restriction of 10
# requests per second." — same page.
GLOBAL_LIMIT: tuple[tuple[int, float], ...] = ((10, 1.0),)

# Longest pace this will impose before giving up and letting the request through. The
# fifteen-minute endpoints are why it exists: blocking a tool call for 900 s would be a
# worse outcome than the 429 being avoided, and raising would fail a call that succeeds
# today. 65 s is chosen so history's 50-per-minute rule — the one a real workload
# actually hits — is always honoured in full.
_MAX_PACING_WAIT = 65.0


def _pattern_to_regex(pattern: str) -> re.Pattern[str]:
    """Compile a table key, whose `{placeholder}` segments match any single segment."""
    parts = [r"[^/]+" if seg.startswith("{") else re.escape(seg) for seg in pattern.split("/")]
    return re.compile("^" + "/".join(parts) + "$")


class EndpointPacer:
    """Proactively spaces requests so IBKR's published per-endpoint limits are not broken.

    `with_retry` reacts to a 429; nothing prevented one. Measured live on 2026-09-16,
    `get_market_history_paginated` issued chunks at **284 requests/minute** against a
    published ceiling of 50, and its 120-chunk runaway guard would have finished in ~25
    seconds — 2.4x the minute's allowance inside half a minute. IBKR answers that with a
    429 and a fifteen-minute penalty box on the IP, across every endpoint, against a
    reactive retry budget of seven seconds. Three documents already described this class
    as doing proactive token-bucket pacing (audit finding API-04); it did not, and now it
    does.

    The window is sliding, not fixed: a request that falls outside the window costs
    nothing, so ordinary spaced-out usage never pays for pacing at all.

    **KNOWN LIMITATION — the budget is per PROCESS, and IBKR's is per IP.** Nothing here
    is shared between interpreters, so N concurrent or rapidly-repeated processes can each
    stay inside the limit while together breaking it. This is not theoretical: on
    2026-09-16, a sequence of short-lived probe scripts against the live gateway — each
    starting with an empty budget — earned HTTP 429 and the documented fifteen-minute
    penalty box, while no single process had exceeded 50 requests in a minute.

    It matters because that is how this package is actually used: a pytest run, a script,
    and an MCP server are three processes sharing one IP. Closing it needs cross-process
    state (a lock file or a small broker), which is a larger change than the in-process
    pacer and has not been made. Until then: do not run live suites concurrently, and
    treat back-to-back script invocations as sharing one budget.

    Thread-safe. The lock is deliberately held across the sleep — two threads sharing a
    budget must queue, or the pacing is decorative.

    Args:
        clock: Monotonic time source. Injected so tests need not sleep.
        sleep: Blocking sleep. Injected for the same reason.
        max_wait: Longest pace to impose before warning and letting the request proceed.
    """

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        max_wait: float = _MAX_PACING_WAIT,
    ) -> None:
        """Build a pacer with empty history. See the class docstring for the arguments."""
        self._clock = clock
        self._sleep = sleep
        self._max_wait = max_wait
        self._lock = threading.Lock()
        self._calls: dict[tuple[str, int, float], deque[float]] = {}
        # Most specific first: a literal segment must win over a `{placeholder}` one, so
        # /fyi/notifications/more is never charged to /fyi/notifications/{notificationId}.
        self._matchers = sorted(
            ((_pattern_to_regex(pattern), pattern, limits) for (pattern, _m), limits in ENDPOINT_LIMITS.items()),
            key=lambda item: -sum(1 for seg in item[1].split("/") if not seg.startswith("{")),
        )

    @staticmethod
    def _endpoint(path: str) -> str:
        """Strip the query string — it is an argument, not a different endpoint.

        `get_live_orders` sends `/iserver/account/orders?force=true` and then
        `/iserver/account/orders`, IBKR's documented subscription warmup. Matching the
        raw string would put those in two different buckets and let the pair through at
        exactly the rate the 1-req/5-secs limit exists to prevent.
        """
        return path.split("?", 1)[0]

    def limits_for(self, path: str) -> tuple[tuple[int, float], ...]:
        """Published limits for a concrete request path, or the global 10/second default.

        Args:
            path: Request path as sent, with or without a query string, e.g.
                `/fyi/notifications/12345` or `/iserver/account/orders?force=true`.

        Returns:
            One `(requests, window_seconds)` pair per limit that applies.
        """
        endpoint = self._endpoint(path)
        for regex, _pattern, limits in self._matchers:
            if regex.match(endpoint):
                return limits
        return GLOBAL_LIMIT

    def acquire(self, path: str) -> float:
        """Block until this path may be requested, then record the request.

        Args:
            path: Request path as sent.

        Returns:
            Seconds actually waited — 0.0 when the request was free.

        Warns:
            UserWarning: When the required wait exceeds `max_wait`. The request is let
                through rather than blocked for a quarter of an hour, so the caller keeps
                the call and learns it is over the limit.
        """
        limits = self.limits_for(path)
        key = self._bucket_key(path)
        with self._lock:
            now = self._clock()
            wait, blocking = self._required_wait(key, limits, now)
            if wait > 0.0 and blocking is not None:
                if wait > self._max_wait:
                    count, window = blocking
                    warnings.warn(
                        f"IBKR limits {path} to {count} request per {window:.0f} s and this "
                        f"call is {wait:.0f} s early; sending it anyway rather than blocking. "
                        "Expect HTTP 429 and a 15-minute penalty box on this IP.",
                        UserWarning,
                        stacklevel=2,
                    )
                    wait = 0.0
                else:
                    self._sleep(wait)
                    now = self._clock()
            for count, window in limits:
                self._expire(self._history(key, count, window), now, window)
                self._history(key, count, window).append(now)
            return wait

    def _bucket_key(self, path: str) -> str:
        """The table pattern a path is charged to, so every id shares one budget."""
        endpoint = self._endpoint(path)
        for regex, pattern, _limits in self._matchers:
            if regex.match(endpoint):
                return pattern
        return "*"

    def _history(self, key: str, count: int, window: float) -> deque[float]:
        return self._calls.setdefault((key, count, window), deque())

    @staticmethod
    def _expire(history: deque[float], now: float, window: float) -> None:
        while history and history[0] <= now - window:
            history.popleft()

    def _required_wait(
        self, key: str, limits: tuple[tuple[int, float], ...], now: float
    ) -> tuple[float, tuple[int, float] | None]:
        """Longest wait any applicable limit demands, and which limit demanded it."""
        wait = 0.0
        blocking: tuple[int, float] | None = None
        for count, window in limits:
            history = self._history(key, count, window)
            self._expire(history, now, window)
            if len(history) >= count:
                needed = history[0] + window - now
                if needed > wait:
                    wait, blocking = needed, (count, window)
        return wait, blocking


_pacer = EndpointPacer()


def pace(path: str) -> float:
    """Pace a request against the process-wide pacer. See `EndpointPacer.acquire`.

    Args:
        path: Request path as sent, e.g. `/iserver/marketdata/history`.

    Returns:
        Seconds waited.
    """
    return _pacer.acquire(path)


def with_retry(
    fn: Callable[[], requests.Response],
    max_retries: int = _DEFAULT_MAX_RETRIES,
    path: str | None = None,
) -> requests.Response:
    """Pace the request for its endpoint, then call fn(), retrying on 429/503.

    Args:
        fn: Thunk performing the HTTP call.
        max_retries: Attempts after the first before raising.
        path: Request path, e.g. `/iserver/marketdata/history`. When given, the request
            is paced against IBKR's published limit for that endpoint before it is sent.
            Optional only so that a caller with no path still works; every call site in
            `client.py` passes one.

    Retry strategy: base 1s, 2× factor, 3 retries (delays: 1s, 2s, 4s).
    No Retry-After header parsing — IBKR Client Portal API does not document
    a Retry-After header in its public reference. Fixed exponential backoff
    is used as a safe default.

    Rate limits and the pacing that enforces them now live in `ENDPOINT_LIMITS` and
    `EndpointPacer` below — one executable table instead of a prose copy. This docstring
    used to restate all 26 rows, and the copy went stale: IBKR changed
    `/iserver/marketdata/history` from "5 concurrent" to 10/sec-or-50/min at the 2026-08
    docs move, and the link-repointing pass updated the citation URL without re-reading
    the page it pointed at (audit finding API-03, 2026-09-16).

    `with_retry` remains the reactive half: it cannot prevent a 429, only survive one.
    Violators receive HTTP 429 and the IP is placed in a fifteen-minute penalty box that
    applies to every endpoint; the backoff below totals seven seconds, so prevention is
    the only thing that actually helps. That is `EndpointPacer`'s job.


    Historical data pacing rules (from TWS API docs, verified 2026-06-26):
    - No identical requests within 15 seconds
    - No 6+ requests for the same contract/exchange/tick type within 2 seconds
    - No more than 60 requests in any 10-minute rolling window
    - Max 50 concurrent open historical data requests
    - BID_ASK tick type counts as 2 requests against all of the above limits
    - Bars >=1 minute: historical data limitations have been lifted (per official docs;
      bars <1 minute remain subject to the limitations above, and bars <=30 seconds
      become unavailable once older than six months)
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
    if path is not None:
        pace(path)
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
                raise IBKRRateLimitError(f"Rate limit exceeded after {max_retries} retries (HTTP {status})")
            backoff = _BASE_BACKOFF * (2**attempt)
            time.sleep(backoff)
            attempt += 1
            continue
        # Any other error status — include response body so callers can see IBKR's rejection reason
        try:
            body_preview = resp.text[:400]
        except Exception:
            body_preview = ""
        raise IBKRAPIError(f"IBKR gateway returned HTTP {status}: {body_preview}", status_code=status)
