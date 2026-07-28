"""Crawl4AI Cloud REST client — the web scraper's third and last recovery rung.

Peer to `web_scraper.FirecrawlClient`, deliberately in its own module: `web_scraper.py`
is Firecrawl-protocol-and-Drive-persistence only, and `scrape_fallback.py` is about the
*local* Playwright scraper and its SSRF guard. A remote HTTP client belongs in neither.

Do not confuse `Crawl4AICloudClient` (here, hosted, costs credits) with
`scrape_fallback.Crawl4AIScraper` (local, free, runs a browser on this machine). They
share a vendor name and nothing else.

Only `POST /v1/scrape` is implemented — exact parity with what the local rung does today:
fetch one URL, return one page. `/v1/site` recursive crawling would add async job
submission, polling and per-URL result fetching, and the ladder does not need it.

Source of truth: https://api.crawl4ai.com/llms-full.txt (the human docs at /docs/... are a
JavaScript SPA and return an HTML shell to curl). Every fact below was verified by live
call on 2026-07-28; where the vendor reference and the live API disagreed, the live API
won and the disagreement is noted at the point of use.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

log = logging.getLogger(__name__)

# Per-request HTTP timeout. Not a plan/tier value — it bounds how long a single scrape may
# block the recovery ladder, and is generous because this rung only ever runs after both
# Firecrawl and the local scraper have already failed, on pages that are hard to fetch.
_TIMEOUT_S = 90

# Warn when the remaining daily balance falls below this fraction of the plan's own
# reported allowance. A *fraction*, deliberately, not a credit count: "warn under 10" is
# right for a 50/day plan and silently useless the day the account moves to 5000/day.
# Nothing in this module may hard-code a tier's numbers — they are read from the API.
_LOW_CREDIT_FRACTION = 0.2

# Crawl4AI Cloud's documented error codes (https://api.crawl4ai.com/llms-full.txt § Error
# Codes, verified 2026-07-28), mapped to messages that name the cause rather than echoing a
# bare number. 402 is absent from the vendor's table — this API signals an exhausted budget
# with 429, not 402 — but is mapped anyway so a future billing change cannot surface as an
# unexplained generic error.
_ERROR_MESSAGES = {
    400: "invalid request parameters",
    401: "invalid or missing Crawl4AI API key",
    402: "Crawl4AI account is out of credits",
    403: "Crawl4AI plan does not allow this operation",
    422: "Crawl4AI could not process the page (it may have returned no HTML)",
    429: "Crawl4AI rate or daily quota limit exceeded",
    503: "no Crawl4AI workers available",
    504: "Crawl4AI request timed out",
}


class Crawl4AICloudError(Exception):
    """Raised when the Crawl4AI Cloud API returns an error response or a failed body.

    Mirrors `FirecrawlError`'s shape but is deliberately a distinct type: a Firecrawl
    exception raised by a Crawl4AI call would send the next reader to the wrong module.

    Attributes:
        message: Human-readable description of the failure.
        status_code: HTTP status from the API, or None when the request failed before
            any response arrived (e.g. a network timeout) or the body itself reported
            failure under an HTTP 200.
    """

    def __init__(self, message: str, status_code: int | None = None) -> None:
        """Record the message and, when one was received, the HTTP status.

        Args:
            message: Human-readable description of the failure.
            status_code: HTTP status from Crawl4AI Cloud, or None when no response
                arrived or the failure was reported in the body of a 200.
        """
        super().__init__(message)
        self.status_code = status_code


class Crawl4AICloudClient:
    """Thin wrapper around the Crawl4AI Cloud REST API (https://api.crawl4ai.com).

    Authentication is the `X-API-Key` header — **not** `Authorization: Bearer`, which is
    Firecrawl's scheme and returns 401 here. Key format is `sk_live_…`.

    **This client never retries.** Crawl4AI returns 429 for daily-quota exhaustion, so the
    retry-on-429 policy in `web_scraper._request_with_backoff` — correct for Firecrawl,
    which documents 429 as retryable backpressure — would spend the entire daily budget
    to fail three times as slowly. One call in, one result out. That helper is deliberately
    left untouched rather than parameterised: it serves the rung that runs most, and a
    change there risks a live regression in Firecrawl for the benefit of this one.

    **Callers must serialise scrapes.** The free plan allows 1 concurrent request (as of
    2026-07-28), so parallel calls 429 against each other. The recovery ladder calls this
    once per crawl and is safe; anything that fans out — `_MAX_CONCURRENT_FALLBACKS` in
    `claude_tools.py` launches up to 5 local scrapes at once — must not reuse this client
    without serialising first. Serialising costs nothing on a paid plan.

    Args:
        api_key: Crawl4AI Cloud API key (`sk_live_…`). Must be non-empty.
        base_url: API root, overridable for staging. Trailing slashes are stripped.
    """

    def __init__(self, api_key: str, *, base_url: str = "https://api.crawl4ai.com") -> None:
        """Store the API key and build the X-API-Key auth headers.

        Args:
            api_key: Crawl4AI Cloud API key (`sk_live_…`).
            base_url: API root, overridable for staging.

        Raises:
            ValueError: If `api_key` is empty. Checked here so a missing key surfaces at
                construction rather than as a confusing 401 later.
        """
        if not api_key:
            raise ValueError("api_key must be non-empty")
        self._base_url = base_url.rstrip("/")
        self._headers = {
            "X-API-Key": api_key,
            "Content-Type": "application/json",
        }
        # Credits left after this client's most recent successful scrape, read straight
        # out of that response body. None until one has run. The ladder reports it in the
        # tool output, but only when this rung actually fired.
        self.last_credits_remaining: float | None = None
        self._daily_allowance: float | None = None
        self._allowance_looked_up = False

    def usage(self) -> dict[str, Any]:
        """Return the account's current plan, credit, storage and LLM-token usage.

        Calls GET /v1/usage, which costs a request against the per-minute rate limit but
        **no credits** (verified live 2026-07-28: four dry runs and three usage calls left
        `credits.used_today` at 0).

        Returns:
            The parsed response body. The live shape is
            `{"plan": {"name", "daily_credits", "rate_per_minute", "concurrent", ...},
              "credits": {"used_today", "remaining_today", "daily_limit"},
              "storage": {...}, "llm": {...}}`.

            This is **not** the shape in the vendor's own llms-full.txt, which documents
            `crawl.credits_daily_limit` / `crawl.credits_remaining_today`. Those keys are
            absent from the live response; the reference is stale. Live wins.

        Raises:
            Crawl4AICloudError: On any HTTP error status.
        """
        resp = requests.get(f"{self._base_url}/v1/usage", headers=self._headers, timeout=_TIMEOUT_S)
        self._raise_for_status(resp)
        body: dict[str, Any] = resp.json()
        return body

    def _daily_credit_allowance(self) -> float | None:
        """Return the plan's daily credit allowance, looked up at most once per client.

        The scrape response carries the remaining balance but not the allowance it should
        be judged against, so one GET /v1/usage is unavoidable to make the low-balance
        threshold relative. It is cached rather than polled per scrape: repeating it would
        spend a request against a per-minute limit to learn what does not change during a
        session.

        Returns None when the lookup fails or reports no allowance, which suppresses the
        low-balance warning rather than guessing a number.
        """
        if self._allowance_looked_up:
            return self._daily_allowance
        self._allowance_looked_up = True
        try:
            body = self.usage()
        except Exception as exc:  # noqa: BLE001 - a best-effort nicety, never fatal
            log.debug("crawl4ai cloud: usage lookup failed (%s) — low-balance warnings disabled", exc)
            return None
        allowance = body.get("plan", {}).get("daily_credits") or body.get("credits", {}).get("daily_limit")
        self._daily_allowance = float(allowance) if allowance else None
        return self._daily_allowance

    def _record_usage(self, payload: dict[str, Any]) -> None:
        """Log this scrape's credit cost and warn when the balance is proportionally low.

        Reads `usage.credits_remaining` out of the scrape response, which is free — the
        alternative, a GET /v1/usage per scrape, would spend a request against the
        per-minute limit to learn what the response already said.
        """
        usage = payload.get("usage") or {}
        remaining = usage.get("credits_remaining")
        if remaining is None:
            return
        self.last_credits_remaining = float(remaining)
        log.info(
            "crawl4ai cloud: %s credit(s) used, %s remaining today",
            usage.get("credits_used", "?"),
            self.last_credits_remaining,
        )
        allowance = self._daily_credit_allowance()
        if allowance and self.last_credits_remaining < allowance * _LOW_CREDIT_FRACTION:
            log.warning(
                "crawl4ai cloud: only %s of %s daily credits remain (under %.0f%% of the plan allowance)",
                self.last_credits_remaining,
                allowance,
                _LOW_CREDIT_FRACTION * 100,
            )

    def _raise_for_status(self, resp: requests.Response) -> None:
        """Translate a Crawl4AI HTTP error into Crawl4AICloudError with its status code.

        Every HTTP failure leaves this client as a Crawl4AICloudError, never as a raw
        requests.HTTPError, so the ladder catches one exception type and can read
        `status_code` to name the cause in its diagnosis.

        The API key is never interpolated into the message.
        """
        if resp.status_code < 400:
            return
        detail = _ERROR_MESSAGES.get(resp.status_code, f"Crawl4AI request failed: HTTP {resp.status_code}")
        raise Crawl4AICloudError(f"{detail} (HTTP {resp.status_code})", resp.status_code)

    def _scrape_body(self, url: str, proxy_mode: str | None, proxy_country: str | None) -> dict[str, Any]:
        """Build the POST /v1/scrape request body shared by scrape() and estimate().

        One builder for both so a priced request and an executed one cannot drift apart —
        an estimate for a body the real call would not send is worthless.

        `proxy` is omitted entirely when proxy_mode is None. It is an *object* here, unlike
        Firecrawl where it is a string, and the string "direct" is a hard 422 rather than a
        no-op (verified live 2026-07-28).
        """
        body: dict[str, Any] = {"url": url, "fit": True}
        if proxy_mode is not None:
            proxy: dict[str, Any] = {"mode": proxy_mode}
            if proxy_country is not None:
                proxy["country"] = proxy_country
            body["proxy"] = proxy
        return body

    def estimate(
        self,
        url: str,
        *,
        proxy_mode: str | None = None,
        proxy_country: str | None = None,
    ) -> dict[str, Any]:
        """Price a scrape without executing it, using the API's dry-run mode.

        A separate method rather than a flag on scrape(), because the response is a
        different kind of thing: a quote, with no `success` field and no `markdown`. The
        first draft of this client made dry_run a scrape() parameter and checked
        `success` unconditionally, so every real dry run raised — a mistake the unit tests
        could not catch, because they asserted against a fabricated body that had a
        `success` key the live API never sends.

        `dry_run` is absent from the vendor's llms-full.txt but live-verified working, and
        free: four dry runs on 2026-07-28 left `credits.used_today` at 0.

        Args:
            url: The page that would be fetched.
            proxy_mode: See scrape(). Included because it changes the price — as of
                2026-07-28 a scrape costs 1 credit with no proxy, 2 with datacenter and 5
                with residential.
            proxy_country: See scrape().

        Returns:
            The raw quote body, including `credits` (a decimal string), `credits_exact`
            and a per-action `breakdown`.

        Raises:
            Crawl4AICloudError: On any HTTP error status — including the 422 a malformed
                request earns, which is the point of calling this.
        """
        resp = requests.post(
            f"{self._base_url}/v1/scrape",
            headers=self._headers,
            json={**self._scrape_body(url, proxy_mode, proxy_country), "dry_run": True},
            timeout=_TIMEOUT_S,
        )
        self._raise_for_status(resp)
        quote: dict[str, Any] = resp.json()
        return quote

    def scrape(
        self,
        url: str,
        *,
        proxy_mode: str | None = None,
        proxy_country: str | None = None,
    ) -> dict[str, Any]:
        """Fetch one URL via POST /v1/scrape and return it as a ladder page dict.

        Args:
            url: The page to fetch. SSRF validation is the caller's job — the recovery
                ladder validates the crawl root before any rung runs.
            proxy_mode: One of "datacenter", "residential" or "auto". **Omitted from the
                request entirely when None.** Unlike Firecrawl, `proxy` here is an object,
                and sending the string "direct" is a hard 422 (verified live 2026-07-28:
                pydantic `model_attributes_type`). Costs rise with the mode — as of
                2026-07-28 a scrape is 1 credit with no proxy, 2 with datacenter and 5
                with residential.
            proxy_country: ISO 2-letter code for geo-targeting, e.g. "US". Only sent
                alongside proxy_mode.

        Returns:
            A page dict shaped `{"url", "markdown", "metadata"}` — the same shape
            Firecrawl's crawl() and the local rung produce, so it flows into
            `WebDocsStore.save_crawl` unchanged.

        Raises:
            Crawl4AICloudError: On any HTTP error status, or on an HTTP 200 whose body
                reports `success: false`.
            requests.RequestException: On a network-level failure, left to the caller to
                catch — the ladder already treats a dead network the same as a failed rung.
        """
        resp = requests.post(
            f"{self._base_url}/v1/scrape",
            headers=self._headers,
            json=self._scrape_body(url, proxy_mode, proxy_country),
            timeout=_TIMEOUT_S,
        )
        self._raise_for_status(resp)

        payload = resp.json()
        if not payload.get("success", False):
            reason = payload.get("error_message") or "Crawl4AI reported an unsuccessful scrape"
            raise Crawl4AICloudError(reason)

        self._record_usage(payload)

        # `markdown` is the full extraction; `fit_markdown` is the PruningContentFilter
        # output requested by `fit: true`. Prefer the full one — the ladder's only decision
        # is "is there enough content?", and pruning a page down to a nav shell is the very
        # failure that sent the crawl to this rung. fit_markdown is the fallback for the
        # case where the filter kept something the raw extraction did not.
        markdown = payload.get("markdown") or payload.get("fit_markdown") or ""
        return {"url": payload.get("url") or url, "markdown": markdown, "metadata": {}}
