"""Crawl4AI Cloud client — the web scraper's third and last recovery rung.

Peer to `web_scraper.FirecrawlClient`, deliberately in its own module: `web_scraper.py`
is Firecrawl-protocol-and-Drive-persistence only, and `scrape_fallback.py` is about the
*local* Playwright scraper and its SSRF guard. A remote HTTP client belongs in neither.

Do not confuse `Crawl4AICloudClient` (here, hosted, costs credits) with
`scrape_fallback.Crawl4AIScraper` (local, free, runs a browser on this machine). They
share a vendor name and nothing else, and neither module imports the other.

**This wraps the vendor's own SDK (`crawl4ai-cloud-sdk`), not hand-rolled HTTP.** The
first cut of this module built `POST /v1/scrape` by hand on `requests`; the SDK is the
better base and, on inspection of its source, gives up none of the invariants this ladder
depends on — see `docs/web-scraper-reference.md` §5.2 for the evaluation. In particular
the SDK raises on 429 **without retrying** (its retry branches cover only 5xx, timeouts
and network errors), and it splits `RateLimitError` from `QuotaExceededError`, a
distinction the hand-rolled version could not make.

Only single-page scraping is used — exact parity with what the local rung does: fetch one
URL, return one page. The SDK exposes far more (`/v1/site`, extraction, enrichment); none
of it is needed to close the gap this rung exists for.

Source of truth for the API: https://api.crawl4ai.com/llms-full.txt. Facts here were
verified by live call on 2026-07-28, and where the vendor reference and the live API
disagreed, the live API won and the disagreement is noted at the point of use.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Coroutine
from typing import Any

import requests

log = logging.getLogger(__name__)

# Per-request timeout. Not a plan/tier value — it bounds how long a single scrape may block
# the recovery ladder, and is generous because this rung only ever runs after both Firecrawl
# and the local scraper have already failed, on pages that are hard to fetch.
_TIMEOUT_S = 90.0

# Retries are disabled outright. The SDK already exempts 429 (a quota signal, not
# backpressure), but its remaining retry branches cover timeouts and network errors — and a
# retried timeout can re-issue a scrape the server already executed, billing the same page
# twice. One attempt in, one result out, for the same budget reason the 429 rule exists.
# The SDK treats max_retries as an attempt count, so 1 means "try once, never again".
_MAX_ATTEMPTS = 1

# Warn when the remaining daily balance falls below this fraction of the plan's own reported
# allowance. A *fraction*, deliberately, not a credit count: "warn under 10" is right for a
# 50/day plan and silently useless the day the account moves to 5000/day. Nothing in this
# module may hard-code a tier's numbers — they are read from the API.
_LOW_CREDIT_FRACTION = 0.2

# Sent explicitly because the SDK's own default is invalid. crawl4ai-cloud-sdk 1.2.0
# declares `scrape(strategy: str = "auto")`, but the live endpoint accepts only "browser"
# or "http" and rejects "auto" with a 422 (pydantic literal_error, observed 2026-07-28) —
# so every call left on the SDK default fails. "browser" is what llms-full.txt documents as
# the default and is the JS-capable path this rung needs, since it runs on pages that
# defeated two simpler scrapers already. Drop this only once the SDK is fixed AND a live
# run proves it; unit tests cannot catch it, because the mock accepts anything.
_STRATEGY = "browser"


class Crawl4AICloudError(Exception):
    """Raised when a Crawl4AI Cloud call fails, or its dependency is missing.

    A distinct type from `FirecrawlError` on purpose: a Firecrawl exception raised by a
    Crawl4AI call would send the next reader to the wrong module. It is also this module's
    boundary type — the vendor SDK's exception hierarchy is translated into it, so
    `claude_tools.py` catches one thing and a future SDK change cannot ripple outward.

    Attributes:
        message: Human-readable description of the failure.
        status_code: HTTP status from the API, or None when the failure happened before any
            response arrived (network error, missing dependency).
    """

    def __init__(self, message: str, status_code: int | None = None) -> None:
        """Record the message and, when one was received, the HTTP status.

        Args:
            message: Human-readable description of the failure.
            status_code: HTTP status from Crawl4AI Cloud, or None when no response arrived.
        """
        super().__init__(message)
        self.status_code = status_code


def _run_async(coro: Coroutine[Any, Any, Any]) -> Any:
    """Run a coroutine from sync code, even when the calling thread has a running loop.

    The vendor SDK is async-only (`AsyncWebCrawler`; there is no sync client), while
    `ClaudeToolkit.execute()` is synchronous and, under `mcp_server.py`, already runs inside
    `asyncio.run()`. A plain `asyncio.run()` here would raise "cannot be called from a
    running event loop", so a dedicated thread with its own fresh loop sidesteps it.

    `scrape_fallback._run_async` is the same helper for the same reason. It is duplicated
    rather than imported because these two modules must not depend on each other — one is
    the local Playwright rung, the other a hosted HTTP rung, and the only thing they share
    is a vendor name. Fifteen lines is a cheaper price than that coupling.

    Args:
        coro: Any coroutine.

    Returns:
        Whatever the coroutine returns.

    Raises:
        Whatever the coroutine raises, re-raised on the calling thread unwrapped.
    """
    result: dict[str, Any] = {}

    def runner() -> None:
        loop = asyncio.new_event_loop()
        try:
            result["value"] = loop.run_until_complete(coro)
        except BaseException as exc:  # propagated to the caller below
            result["error"] = exc
        finally:
            loop.close()

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()

    if "error" in result:
        raise result["error"]
    return result["value"]


class Crawl4AICloudClient:
    """Thin adapter over the vendor's `crawl4ai-cloud-sdk` for the recovery ladder's rung 3.

    Exposes only what the ladder needs — one page in, one page dict out — and translates the
    SDK's exceptions into `Crawl4AICloudError` so `claude_tools.py` has a single type to
    catch.

    **Callers must serialise scrapes.** The free plan allows 1 concurrent request (as of
    2026-07-28), so parallel calls 429 against each other. The ladder calls this once per
    crawl and is safe; anything that fans out — `_MAX_CONCURRENT_FALLBACKS` in
    `claude_tools.py` launches up to 5 local scrapes at once — must not reuse this client
    without serialising first. Serialising costs nothing on a paid plan.

    Args:
        api_key: Crawl4AI Cloud API key (`sk_live_…`). Must be non-empty.
        base_url: API root, overridable for staging.
    """

    def __init__(self, api_key: str, *, base_url: str = "https://api.crawl4ai.com") -> None:
        """Store credentials for the per-call SDK crawler.

        Args:
            api_key: Crawl4AI Cloud API key (`sk_live_…`).
            base_url: API root, overridable for staging.

        Raises:
            ValueError: If `api_key` is empty. Checked here so a missing key surfaces at
                construction rather than as a confusing 401 later.
        """
        if not api_key:
            raise ValueError("api_key must be non-empty")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        # Credits left after the most recent successful scrape, read from that response.
        # None until one has run. The ladder reports it, but only when this rung fired.
        self.last_credits_remaining: float | None = None
        self._daily_allowance: float | None = None
        self._allowance_looked_up = False

    def _crawler(self) -> Any:
        """Build a vendor `AsyncWebCrawler`, with retries disabled.

        Raises:
            Crawl4AICloudError: If `crawl4ai-cloud-sdk` is not installed. Imported lazily,
                and reported as a normal rung failure, because the cloud rung is optional —
                the ladder must keep working for anyone who installed neither scraper extra.
        """
        try:
            from crawl4ai_cloud import AsyncWebCrawler
        except ImportError as exc:
            raise Crawl4AICloudError(
                "crawl4ai-cloud-sdk is not installed — install ibkr_core_mcp[scraper] to enable the Crawl4AI Cloud rung"
            ) from exc

        return AsyncWebCrawler(
            api_key=self._api_key,
            base_url=self._base_url,
            timeout=_TIMEOUT_S,
            max_retries=_MAX_ATTEMPTS,
        )

    def _translate(self, exc: Exception) -> Crawl4AICloudError:
        """Map a vendor SDK exception onto this module's boundary type.

        The SDK distinguishes `RateLimitError` (too fast — retryable in principle) from
        `QuotaExceededError` (daily budget gone — not retryable at all), which the
        hand-rolled predecessor could not. Both are HTTP 429; the message says which, so the
        ladder's diagnosis names the real cause and nobody reads "429" and assumes a retry
        would help.

        The API key is never interpolated into the message.
        """
        from crawl4ai_cloud import errors as sdk_errors

        status = getattr(exc, "status_code", None)
        if isinstance(exc, sdk_errors.QuotaExceededError):
            quota = getattr(exc, "quota_type", None) or "daily"
            return Crawl4AICloudError(f"Crawl4AI {quota} quota exhausted — not retryable (HTTP 429)", 429)
        if isinstance(exc, sdk_errors.RateLimitError):
            return Crawl4AICloudError(f"Crawl4AI rate limit hit — too many requests per minute (HTTP 429): {exc}", 429)
        if isinstance(exc, sdk_errors.AuthenticationError):
            return Crawl4AICloudError("invalid or missing Crawl4AI API key (HTTP 401)", 401)
        if isinstance(exc, sdk_errors.CloudError):
            return Crawl4AICloudError(f"Crawl4AI request failed: {exc}", status if isinstance(status, int) else None)
        return Crawl4AICloudError(f"Crawl4AI request failed: {exc}")

    def _call(self, method_name: str, /, **kwargs: Any) -> Any:
        """Run one SDK crawler method to completion and always close the client.

        Every network path in this module goes through here, so the exception translation
        and the connection teardown exist in exactly one place.
        """
        crawler = self._crawler()

        async def _go() -> Any:
            try:
                return await getattr(crawler, method_name)(**kwargs)
            finally:
                await crawler.close()

        try:
            return _run_async(_go())
        except Crawl4AICloudError:
            raise
        except Exception as exc:
            raise self._translate(exc) from exc

    def usage(self) -> dict[str, Any]:
        """Return the account's current plan, credit, storage and LLM-token usage.

        Calls `GET /v1/usage` directly rather than through the SDK, which wraps
        `/v1/crawl/storage` but has no usage endpoint at all. That gap matters: the
        low-balance warning below is expressed as a fraction of `plan.daily_credits`, and
        this is the only endpoint that reports it.

        Costs a request against the per-minute rate limit but **no credits** (verified live
        2026-07-28: four dry runs and three usage calls left `credits.used_today` at 0).

        Returns:
            The parsed body. Live shape is
            `{"plan": {"name", "daily_credits", "rate_per_minute", "concurrent", ...},
              "credits": {"used_today", "remaining_today", "daily_limit"},
              "storage": {...}, "llm": {...}}`.

            This is **not** the shape in the vendor's own llms-full.txt, which documents
            `crawl.credits_daily_limit` / `crawl.credits_remaining_today`. Those keys are
            absent from the live response; the published reference is stale. Live wins.

        Raises:
            Crawl4AICloudError: On any HTTP error status.
        """
        resp = requests.get(
            f"{self._base_url}/v1/usage",
            headers={"X-API-Key": self._api_key},
            timeout=_TIMEOUT_S,
        )
        if resp.status_code >= 400:
            raise Crawl4AICloudError(f"Crawl4AI usage lookup failed: HTTP {resp.status_code}", resp.status_code)
        body: dict[str, Any] = resp.json()
        return body

    def _daily_credit_allowance(self) -> float | None:
        """Return the plan's daily credit allowance, looked up at most once per client.

        The scrape response carries the remaining balance but not the allowance to judge it
        against, so one `/v1/usage` call is unavoidable to keep the threshold relative. It is
        cached rather than polled per scrape: repeating it would spend a request against a
        per-minute limit to learn something that does not change during a session.

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

    def _record_usage(self, usage: Any) -> None:
        """Log the remaining balance and warn when it is proportionally low.

        Reads the balance off the scrape response the SDK already parsed, which is free — a
        `GET /v1/usage` per scrape would spend a request against the per-minute limit to
        learn what the response has already said.

        **`credits_used` on that same object is deliberately ignored: it is wrong.** Measured
        2026-07-28, a no-proxy scrape reported `credits_used: 5.0` while `/v1/usage` moved
        from 3 to 4 — a true cost of 1, which the `dry_run` quote had also priced at exactly
        1.0. `credits_remaining` agreed with the ledger; `credits_used` did not, and reading
        it is very likely where this project's earlier "some operations cost 5 credits"
        budget came from.
        """
        remaining = getattr(usage, "credits_remaining", None) if usage is not None else None
        if remaining is None:
            return
        self.last_credits_remaining = float(remaining)
        log.info("crawl4ai cloud: %s credit(s) remaining today", self.last_credits_remaining)
        allowance = self._daily_credit_allowance()
        if allowance and self.last_credits_remaining < allowance * _LOW_CREDIT_FRACTION:
            log.warning(
                "crawl4ai cloud: only %s of %s daily credits remain (under %.0f%% of the plan allowance)",
                self.last_credits_remaining,
                allowance,
                _LOW_CREDIT_FRACTION * 100,
            )

    @staticmethod
    def _proxy(proxy_mode: str | None, proxy_country: str | None) -> Any:
        """Build the SDK's ProxyConfig, or None to omit the field entirely.

        Omission is not the same as a "no proxy" value here: the string `"direct"` is a hard
        422 (verified live 2026-07-28, pydantic `model_attributes_type`), which is the trap
        that makes copying Firecrawl's string-valued `proxy` wrong. Returning None leaves the
        SDK to omit the field.
        """
        if proxy_mode is None:
            return None
        from crawl4ai_cloud import ProxyConfig

        if proxy_country is not None:
            return ProxyConfig(mode=proxy_mode, country=proxy_country)
        return ProxyConfig(mode=proxy_mode)

    def estimate(
        self,
        url: str,
        *,
        proxy_mode: str | None = None,
        proxy_country: str | None = None,
    ) -> dict[str, Any]:
        """Price a scrape without executing it, using the API's dry-run mode.

        A separate method from `scrape()` because the response is a different kind of thing:
        a quote, with no `success` field and no `markdown`. An early hand-rolled version made
        `dry_run` a `scrape()` flag and checked `success` unconditionally, so every real dry
        run raised — a mistake the unit tests could not catch, because they asserted against
        a fabricated body carrying a `success` key the live API never sends. The vendor SDK
        makes the same split, via its own `_dry_run_estimate`.

        Free: four dry runs on 2026-07-28 left `credits.used_today` at 0.

        Args:
            url: The page that would be fetched.
            proxy_mode: See `scrape()`. Included because it changes the price — as of
                2026-07-28, 1 credit with no proxy, 2 datacenter, 5 residential.
            proxy_country: See `scrape()`.

        Returns:
            The raw quote, including `credits`, `credits_exact` and a per-action `breakdown`.

        Raises:
            Crawl4AICloudError: On any error, including the 422 a malformed request earns —
                which is the point of calling this.
        """
        quote = self._call(
            "scrape",
            url=url,
            fit=True,
            strategy=_STRATEGY,
            proxy=self._proxy(proxy_mode, proxy_country),
            dry_run=True,
        )
        return quote if isinstance(quote, dict) else dict(quote)

    def scrape(
        self,
        url: str,
        *,
        proxy_mode: str | None = None,
        proxy_country: str | None = None,
    ) -> dict[str, Any]:
        """Fetch one URL and return it as a ladder page dict.

        Args:
            url: The page to fetch. SSRF validation is the caller's job — the recovery ladder
                validates the crawl root before any rung runs.
            proxy_mode: One of "datacenter", "residential" or "auto". **Omitted from the
                request entirely when None** — see `_proxy`. Costs rise with the mode: as of
                2026-07-28, 1 credit with no proxy, 2 datacenter, 5 residential.
            proxy_country: ISO 2-letter code for geo-targeting, e.g. "US". Only sent
                alongside `proxy_mode`.

        Returns:
            A page dict shaped `{"url", "markdown", "metadata"}` — the same shape Firecrawl's
            `crawl()` and the local rung produce, so it flows into `WebDocsStore.save_crawl`
            unchanged.

        Raises:
            Crawl4AICloudError: On any HTTP or transport error, or when the response reports
                a failed scrape. Never retried — see `_MAX_ATTEMPTS`.
        """
        result = self._call(
            "scrape",
            url=url,
            fit=True,
            strategy=_STRATEGY,
            proxy=self._proxy(proxy_mode, proxy_country),
        )

        error = getattr(result, "error_message", None)
        if error:
            raise Crawl4AICloudError(str(error))

        self._record_usage(getattr(result, "usage", None))

        # `markdown` is the full extraction; `fit_markdown` is the PruningContentFilter output
        # requested by `fit=True`. Prefer the full one — the ladder's only decision is "is
        # there enough content?", and pruning a page down to a nav shell is the very failure
        # that sent the crawl to this rung. Measured 2026-07-28 on the same response:
        # markdown 17,834 B vs fit_markdown 12,186 B.
        markdown = getattr(result, "markdown", None) or getattr(result, "fit_markdown", None) or ""
        return {"url": url, "markdown": str(markdown), "metadata": {}}
