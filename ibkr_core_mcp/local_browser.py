"""The local Crawl4AI browser — every ibkr_core_mcp web tool that takes a URL.

Crawl4AI is an open-source, Playwright-based crawler that can reuse a locally
saved browser login profile, so a paywalled site the user subscribes to returns
the full article instead of the subscription stub. `crawl4ai` is an optional
dependency (`pip install ibkr_core_mcp[scraper]`) and is only imported when a
scrape actually runs.

**Two rules govern every profiled fetch, and both are load-bearing** (see
`_browser_config` and `_profile_in_use` for the measurements behind them):

  1. It runs in a **visible** browser. A profile's bot-management cookies are
     minted by the visible browser `create_profile()` opens, and replaying them
     headless is a fingerprint mismatch the site challenges — so a profiled
     headless fetch is strictly *worse* than no profile at all.
  2. It is **serialised per profile**. A profile is a real Chrome `user_data_dir`
     and only one browser may hold it; two concurrent fetches of one domain
     otherwise both return 0 B without raising.

Anonymous fetches are subject to neither: they stay headless and run in parallel.

**This module is no longer a fallback.** Until 2026-07-30 it sat underneath
Firecrawl, reachable only when a paid attempt came back thin, and a two-engine
ladder decided between them. Live measurement retired that arrangement: on the
same URLs minutes apart the local browser returned *more* content in a *tenth*
of the time, for free (`docs/web-scraper-reference.md` §5.2). So the split is now
by capability rather than by cost:

  * **Anything with a URL comes here** — `fetch_page` (one page), `crawl_site`
    (archive a site), `search_site` (find pages within one site).
  * **Firecrawl keeps only whole-web search**, the one thing this module cannot
    do: `AsyncUrlSeeder` is domain-scoped by construction.

Nothing falls back to anything, so there is no merge, no arbitration, and no LLM
judge. The file name is kept for import stability; "fallback" is history.

Provides:
  Quality                  — "ok" / "ambiguous" / "fallback" classification type
  Crawl4AIUnavailableError — raised when the optional `crawl4ai` dependency is missing
  assess_quality           — is this markdown real content, or a stub/error page?
  Crawl4AIScraper          — fetches a single URL, reusing a saved login profile
                              for the URL's domain if one exists
  crawl_site               — breadth-first same-host crawl, for archiving to Drive
  search_site              — BM25-ranked page discovery within one domain
  create_profile           — one-time interactive login; saves a browser profile
  list_profiles            — the saved profiles, with each one's age in days

Source: https://docs.crawl4ai.com/ (Crawl4AI, verified against the published
PyPI wheel for crawl4ai==0.5.0 and crawl4ai==0.9.0 on 2026-06-30 — see the
`crawl4ai>=0.5.0` floor note in CLAUDE.md's "Web Scraping" reference table).
"""

from __future__ import annotations

import asyncio
import shutil
import sys
import threading
import time
from collections.abc import Coroutine, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

Quality = Literal["ok", "ambiguous", "fallback"]

# assess_quality() thresholds — see its docstring for the classification rules
# these feed into. Real short pages exist, so length alone is never a hard
# "fallback" verdict once markdown is non-trivially present.
_MIN_WORDS_FALLBACK = 40
_MIN_WORDS_CONFIDENT = 200

# How many URLs search_site() asks the seeder to discover before ranking. The caller's
# own `limit` applies to *matches* after BM25 scoring, so this has to be much larger:
# scoring is sparse (4 of 87 above zero on the live 2026-07-30 run), and a cap applied
# before ranking would silently truncate the candidate pool rather than the answer.
_SEED_MAX_URLS = 1000

# The score BM25 assigns to every page when the query shares no terms with any of them.
# Not a tuning knob — it is the observed neutral value, and the flat distribution at it
# is how "nothing matched" is detected. See _is_no_information_plateau.
_NEUTRAL_BM25_SCORE = 0.5

# Common phrasing on metered/hard paywalls (WSJ, Bloomberg, FT, Barron's, etc.)
# that signals a page is showing a subscription stub rather than full content.
_PAYWALL_MARKERS = (
    "subscribe to continue",
    "sign in to continue reading",
    "already a subscriber",
    "unlock this article",
    "create a free account to continue",
    "this content is reserved for subscribers",
)


def is_private_host(host: str) -> bool:
    """True if `host` (a hostname or IP literal, already lowercased by the caller)
    is localhost, link-local, or resolves — as a literal or via DNS — to a
    private/loopback/reserved IP address.

    Shared by two independent SSRF layers so they can't silently drift apart:
      1. ClaudeToolkit._validate_public_url — the Python-level pre-check run
         before any URL reaches Crawl4AI at all.
      2. The Playwright-level per-request guard installed on every browser this
         module opens — `Crawl4AIScraper.scrape()` and `crawl_site()` both register
         it (see _reject_private_requests below) — which
         re-checks every request Chromium actually makes (initial navigation,
         redirects, and subresources) at the moment it's about to be sent —
         closing the DNS-rebinding and redirect-based gaps that layer 1 alone
         cannot close, since layer 1's DNS resolution happens in a different
         process, moments before Chromium performs its own independent lookup.

    Args:
        host: Hostname or IP literal to check. Callers are responsible for
              extracting this from a URL (e.g. via urlparse(url).hostname).

    Returns:
        True if the host should be blocked. False if it resolves to a public
        address, or if it's unresolvable (an unresolvable hostname isn't a
        private-IP bypass — the fetch will simply fail on its own).
    """
    import ipaddress
    import socket

    # S104 false positive: "0.0.0.0" here is a *blocklist entry* in the SSRF
    # guard (rejecting requests to the all-interfaces address), not a bind.
    if host in ("localhost", "0.0.0.0") or host.startswith("127.") or host.startswith("169.254."):  # noqa: S104
        return True
    try:
        addr = ipaddress.ip_address(host)
        return addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved
    except ValueError:
        # Not a literal IP — resolve via DNS and re-check. Catches decimal
        # (2130706433) and hex (0x7f000001) encoded IPs as well as ordinary
        # hostnames that happen to resolve to a private address.
        #
        # getaddrinfo (not gethostbyname) so AAAA-only hosts can't bypass this
        # by having no A record — gethostbyname is IPv4-only and used to treat
        # "unresolvable via IPv4" as "safe," which is wrong for a host that
        # resolves fine via IPv6. See docs/audits/security-audit-2026-07-11.md H-4.
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror:
            return False
        for info in infos:
            sockaddr = info[4]
            ip_str = sockaddr[0]
            try:
                addr = ipaddress.ip_address(ip_str)
            except ValueError:
                continue
            if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
                return True
        return False


class Crawl4AIUnavailableError(Exception):
    """Raised when the optional `crawl4ai` dependency is not installed.

    ClaudeToolkit catches this and returns a message to the LLM pointing at the
    install command, rather than letting the ImportError propagate.

    Note on versions: pyproject.toml pins `crawl4ai>=0.5.0` because
    `BrowserProfiler` (required by create_profile()) does not exist before
    0.5.0 — confirmed by inspecting the published wheels for 0.4.248 and 0.5.0
    on 2026-06-30. An install pinned below that floor would import successfully
    but raise this exact error, with a misleading "not installed" message, the
    moment create_profile() is actually called.
    """


def _run_async(coro: Coroutine[Any, Any, Any]) -> Any:
    """Run an async coroutine from sync code, regardless of whether the calling
    thread already has a running event loop.

    ClaudeToolkit.execute() is invoked synchronously from inside mcp_server.py's
    async `handle_call_tool`, which itself runs under `asyncio.run()`. A plain
    `asyncio.run(coro)` here would raise "cannot be called from a running event
    loop" in that case. Spawning a dedicated thread with its own fresh event loop
    sidesteps the conflict entirely, at the cost of one thread per fallback call.

    Args:
        coro: Any awaitable coroutine (e.g. Crawl4AI's async `arun`/`create_profile`).

    Returns:
        Whatever the coroutine returns.

    Raises:
        Whatever the coroutine raises — the original exception (and traceback
        context) is re-raised on the calling thread, not wrapped.
    """
    result: dict[str, Any] = {}

    def runner() -> None:
        loop = asyncio.new_event_loop()
        try:
            result["value"] = loop.run_until_complete(coro)
        except BaseException as exc:  # propagated to caller below
            result["error"] = exc
        finally:
            loop.close()

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()

    if "error" in result:
        raise result["error"]
    return result["value"]


def assess_quality(markdown: str, metadata: dict[str, Any] | None, url: str) -> Quality:
    """Is this markdown real content, a stub, or too close to call?

    The repo's single answer to "did I actually get the page?", and the reason no
    scraper tool can report the *shape* of success while holding nothing.

    | Verdict | Meaning | Trigger |
    |---|---|---|
    | `"fallback"` | Not content | HTTP status >= 400 or an `error` in metadata, **or** under ~40 words |
    | `"ambiguous"` | Might be a stub | A known paywall phrase, **or** ~40-200 words |
    | `"ok"` | Content | everything else |

    **The verdict name `"fallback"` is historical.** It once meant "escalate to the
    Crawl4AI rung", and the value is kept because it is persisted in nothing and
    renaming it would churn every caller for no behavioural gain — but read it as
    "unusable". There is no rung to escalate to: this now decides whether a tool
    should *say so*, not which engine to try next.

    Three callers, supplying different amounts of evidence:

      * `crawl_site` — refuses to archive when **every** page grades `"fallback"`.
        `"ambiguous"` is deliberately not enough: real short pages exist, and
        discarding them would be its own kind of wrong.
      * `fetch_page` — flags anything not `"ok"` as possibly incomplete.
      * `firecrawl_search` — annotates any result grading `"fallback"` and excludes it
        from the "read these" invitation. It passes Firecrawl's own per-result metadata,
        so the HTTP-status branch is live there and only there.

    `fetch_page` and `crawl_site` pass `metadata=None` because the local browser
    returns `{"url", "markdown"}` and carries no HTTP status. That is working from
    less, not working wrongly — the word-count and paywall-marker checks still apply,
    and they are what catch a 44-byte 403 or a 1-byte anti-bot stub.

    **This docstring described the `firecrawl_search` caller for nine days before it
    existed** (2026-07-30 to 2026-08-07). Only two call sites were real, both passing
    `metadata=None`, so the status branch was unreachable in production while unit tests
    covered it directly and stayed green — documentation asserting that a check runs,
    which is the same defect class the check itself exists to catch.

    Args:
        markdown: The markdown content scraped for this page/result.
        metadata: The scraper's "metadata" dict, or None when it reports none.
        url: Source URL, accepted for logging/telemetry — not used in the
             classification itself.

    Returns:
        One of `"ok"`, `"ambiguous"`, `"fallback"`.
    """
    metadata = metadata or {}
    status_code = metadata.get("statusCode")
    if metadata.get("error") or (isinstance(status_code, int) and status_code >= 400):
        return "fallback"

    word_count = len(markdown.split())
    if word_count < _MIN_WORDS_FALLBACK:
        return "fallback"

    lowered = markdown.lower()
    if any(marker in lowered for marker in _PAYWALL_MARKERS):
        return "ambiguous"

    if word_count < _MIN_WORDS_CONFIDENT:
        return "ambiguous"

    return "ok"


def _safe_domain(url_or_domain: str) -> str:
    """Extract a filesystem-safe domain string from a URL or bare domain, for use
    as a `profiles_dir` subdirectory name (`profiles_dir / domain`).

    Deliberate defense-in-depth, not incidental: a hostname of ".." would make
    `profiles_dir / domain` resolve to profiles_dir's *parent* directory (e.g.
    `~/.ibkr_core`), which `Crawl4AIScraper.scrape()` would then read from
    (picking up an unrelated file as if it were a browser profile) and
    `create_profile()` would `shutil.rmtree()`/write into. Today this is also
    incidentally blocked upstream by ClaudeToolkit._validate_public_url, whose
    DNS resolution raises on malformed hostnames like "..", but that's a side
    effect of IDNA encoding rules, not an intentional path-traversal check — a
    future change to that validation could silently reopen it. This function
    makes the check explicit and independent of any caller's URL validation.

    Args:
        url_or_domain: A URL (its hostname is used) or a bare domain string.

    Returns:
        The lowercased domain.

    Raises:
        ValueError: If the resulting domain is empty, or contains "..", "/",
            or "\\" — anything that could escape `profiles_dir` via the
            `profiles_dir / domain` join.
    """
    domain = (urlparse(url_or_domain).hostname or url_or_domain or "").lower()
    if not domain or ".." in domain or "/" in domain or "\\" in domain:
        raise ValueError(f"Invalid domain for profile storage: {url_or_domain!r}")
    return domain


def _resolve_profile_dir(profiles_dir: Path, url_or_domain: str) -> Path | None:
    """Find the saved browser profile that applies to a URL, or None if there is none.

    Lookup used to be exact-hostname only, which silently defeated the feature it was
    built for: a profile created for "www.ft.com" was not found for a "ft.com" or
    "markets.ft.com" article, so the scrape fell back to anonymous and returned the
    paywall stub with nothing indicating the profile existed.

    Candidates are tried most-specific first: the exact host, the host without a leading
    "www.", then progressively broader parents while at least two labels remain. Matching
    therefore only ever broadens *toward* the registrable domain, never toward a sibling
    host — a profile for "ft.com" can serve "markets.ft.com", which is intended, and
    cookie scoping still applies on top. Stopping at two labels means a directory named
    after a bare TLD can never be matched.

    Multi-part suffixes ("ft.co.uk") stop at "co.uk", which will simply never match a
    saved profile. No public-suffix list is worth adding for that.

    Args:
        profiles_dir: Root holding one profile directory per domain
            (Config.crawl4ai_profiles_dir).
        url_or_domain: A URL or bare domain; only its hostname is used.

    Returns:
        The first matching profile directory, or None to scrape anonymously.
    """
    host = _safe_domain(url_or_domain)
    candidates = [host]
    if host.startswith("www."):
        candidates.append(host[len("www.") :])
    labels = host.split(".")
    while len(labels) > 2:
        labels = labels[1:]
        candidate = ".".join(labels)
        if candidate not in candidates:
            candidates.append(candidate)
    for candidate in candidates:
        path = profiles_dir / candidate
        if path.is_dir():
            return path
    return None


async def _reject_private_requests(route: Any, request: Any) -> None:
    """Playwright route handler: abort any request whose host is private/loopback/
    link-local/reserved; otherwise let it continue.

    Installed (via _install_ssrf_guard below) on every request Chromium makes
    during a Crawl4AI page load — the initial navigation, every HTTP redirect
    hop, and every subresource — not just the URL Crawl4AIScraper.scrape() was
    originally called with. This is the second of two SSRF layers (see
    is_private_host's docstring): it closes what a single pre-fetch URL check
    at the Python level cannot, because it re-checks at the moment each request
    is actually about to be sent, inside the same browser navigation, rather
    than relying on a DNS resolution done earlier in a different process.

    Args:
        route: Playwright `Route` object for the intercepted request.
        request: Playwright `Request` object; `request.url` is the URL about
                 to be fetched (which may differ from the original scrape URL
                 if this is a redirect or subresource).
    """
    import urllib.parse

    host = (urllib.parse.urlparse(request.url).hostname or "").lower()
    if host and is_private_host(host):
        await route.abort()
    else:
        await route.continue_()


async def _install_ssrf_guard(page: Any, **_kwargs: Any) -> None:
    """Crawl4AI `on_page_context_created` hook: register _reject_private_requests
    as the route handler for every request the page makes."""
    await page.route("**/*", _reject_private_requests)


_PROFILE_LOCKS: dict[str, threading.Lock] = {}
_PROFILE_LOCKS_GUARD = threading.Lock()

# How long a profiled fetch waits for another one on the same profile to finish. Generous
# because the thing being waited on is a whole browser session — a profiled `crawl_site`
# of 25 pages runs ~30 s — and because timing out is the worse outcome: the caller gets an
# error where waiting would have produced the article.
_PROFILE_LOCK_TIMEOUT_S = 180.0


@contextmanager
def _profile_in_use(profile_dir: Path | None) -> Iterator[None]:
    """Hold an exclusive claim on a login profile for the duration of one browser session.

    **Chrome already enforces this; the lock only changes how it fails.** A profile is a real
    Chrome `user_data_dir`, guarded by a `SingletonLock` file, so two browsers cannot share
    one. Without this, a second concurrent fetch of the same domain loses the race and
    returns **0 B** — measured 2026-07-30: two simultaneous profiled fetches of the same
    ft.com article returned 0 B and 0 B, while the same pair run anonymously returned
    25,242 B and 25,293 B. Neither raised. `assess_quality("")` grades `fallback`, so
    `fetch_page` does append its incompleteness NOTE — the caller is told *something* is
    wrong, but the stated causes (paywall stub, blocked request, unfinished JS) are all
    wrong, and a plain retry would have worked.

    Serialising turns that into a wait. Anonymous fetches take no lock: they get a throwaway
    profile directory each, share nothing, and genuinely run in parallel — verified above.

    The bug predates the visible-browser fix; the lock is on `user_data_dir` and has nothing
    to do with `headless`. It was simply unreachable while profiled fetches were being
    challenged anyway, which is what made the whole profiled path look broken instead of
    contended.

    Args:
        profile_dir: The saved profile this session will open, or None for an anonymous
            fetch, in which case this is a no-op and nothing is serialised.

    Yields:
        Nothing — the claim is held for the body of the `with` block.

    Raises:
        TimeoutError: If another session holds the same profile for longer than
            `_PROFILE_LOCK_TIMEOUT_S`. Failing loudly beats returning the 0 B this exists
            to prevent.
    """
    if profile_dir is None:
        yield
        return

    key = str(profile_dir)
    with _PROFILE_LOCKS_GUARD:
        lock = _PROFILE_LOCKS.setdefault(key, threading.Lock())

    if not lock.acquire(timeout=_PROFILE_LOCK_TIMEOUT_S):
        raise TimeoutError(
            f"Another browser session has been using the login profile {key} for over "
            f"{_PROFILE_LOCK_TIMEOUT_S:.0f}s. Only one browser can open a Chrome profile at a "
            "time, so this fetch cannot start. Retry once the other one finishes."
        )
    try:
        yield
    finally:
        lock.release()


def _browser_config(browser_config_cls: Any, profile_dir: Path | None) -> Any:
    """Build the Crawl4AI `BrowserConfig` for a fetch: headless when anonymous, **visible
    when a saved login profile is in play**.

    That asymmetry is not a preference, it is what makes a profile work at all. A saved
    profile carries short-lived bot-management cookies minted by the visible browser
    `create_profile()` opened — FT's jar holds 15 `__cf_bm` (Cloudflare Bot Management)
    entries alongside `FTSession_s`. Replaying those from `--headless=new` presents a
    browser fingerprint that does not match the one they were issued to, and the site
    treats the mismatch as exactly what it looks like.

    Live-proven on ft.com 2026-07-30, same article, one variable changed at a time:

    | headless | profile | result                                          |
    |----------|---------|-------------------------------------------------|
    | True     | no      | 25,238 B — FT paywall barrier page, no article   |
    | True     | yes     |  1,213 B — FT "Security Verification" challenge  |
    | False    | yes     | 35,394 B — **the full article**                  |

    So a profiled headless fetch is strictly worse than no profile at all: it trades the
    barrier page for a bot challenge. There is no configuration in which it is the right
    choice, which is why this is unconditional rather than a caller option.

    Anonymous fetches stay headless. They have no cookies to be inconsistent with, and
    headless is faster and needs no display.

    **Requires a display for profiled fetches.** `headless=False` launches a real window,
    so a profiled scrape cannot run over a bare SSH session or on a headless host. That is
    an accepted cost: ClaudIA runs on the user's desktop, and the alternative is a profile
    feature that silently never works. Anonymous scrapes are unaffected.

    This does nothing for a site that blocks the automated browser *before* authentication
    — wsj.com still answers DataDome's HTTP 401 and 1 B here, visible and profiled
    (re-verified 2026-07-30). The fix addresses a cookie/fingerprint mismatch, not edge
    bot-blocking. See `docs/web-scraper-reference.md` § Live Test Log.

    Args:
        browser_config_cls: Crawl4AI's `BrowserConfig`, passed in rather than imported
            here so the callers keep their lazy import and their single
            `Crawl4AIUnavailableError` path.
        profile_dir: The saved profile for this URL's domain (`_resolve_profile_dir`),
            or None to browse anonymously.

    Returns:
        A configured `BrowserConfig`.
    """
    if profile_dir is not None:
        return browser_config_cls(headless=False, use_managed_browser=True, user_data_dir=str(profile_dir))
    return browser_config_cls(headless=True)


class Crawl4AIScraper:
    """Single-page scraper on Crawl4AI (https://docs.crawl4ai.com/) — a Playwright-based,
    open-source crawler needing no API key. Backs the `fetch_page` tool.

    Not a fallback: it is the primary and only route for reading one page. It was
    reachable only underneath a Firecrawl attempt until 2026-07-30, which is precisely
    why no paywalled article could ever be opened.

    If a browser profile exists for the target URL's domain under `profiles_dir`
    (created via `python -m ibkr_core_mcp.local_browser create-profile <url>`,
    which runs Crawl4AI's BrowserProfiler for a one-time interactive login), the
    scrape reuses that saved login session. Otherwise it scrapes anonymously —
    which will still be incomplete for hard paywalls, and that's expected.

    `crawl4ai` is imported lazily inside scrape() so the base ibkr_core_mcp package never
    requires the optional `[scraper]` extra.

    Source (BrowserConfig / managed-browser profile reuse, and the
    on_page_context_created hook used for the SSRF request guard):
      https://docs.crawl4ai.com/advanced/identity-based-crawling/
      (hook signature verified against the installed crawl4ai==0.9.0 source,
      crawl4ai/async_crawler_strategy.py, on 2026-07-01 — AsyncCrawlerStrategy
      exposes hooks including "on_page_context_created", called with the
      Playwright `page` as its first argument.)

    Args:
        profiles_dir: Root directory for saved login profiles — one subfolder
                       per domain, matching Config.crawl4ai_profiles_dir. The
                       caller does not need to create this directory; scrape()
                       only reads from it and never writes to it (create_profile
                       is what populates it).
    """

    def __init__(self, profiles_dir: Path) -> None:
        """Record where saved browser profiles live.

        Args:
            profiles_dir: Root holding one saved-session profile per domain,
                matching `Config.crawl4ai_profiles_dir`. It is not created here:
                `scrape()` only ever reads from it, and `create_profile` is what
                populates it.
        """
        self._profiles_dir = profiles_dir

    def scrape(self, url: str) -> dict[str, str]:
        """Fetch one URL in a local browser and return its markdown.

        Uses the saved login profile for the URL's domain when one exists (see
        `_resolve_profile_dir`), otherwise browses anonymously — which still returns the
        stub on a hard paywall, as expected.

        **A profiled fetch opens a visible browser window; an anonymous one stays
        headless.** That is required for the profile to work at all, not a preference —
        `_browser_config` carries the live evidence and the display requirement.

        Installs the Playwright-level SSRF guard on the browser context, so every request
        Chromium actually makes — the navigation, each redirect hop, and every subresource
        — is re-checked at the moment it is sent. That is the second of two independent
        layers; see `is_private_host`.

        This was a one-URL wrapper around a `scrape_batch()` that shared a single browser
        across many URLs. That batching existed solely for the deleted per-page fallback
        loop, which re-fetched every thin page of a Firecrawl crawl; multi-page crawling is
        `crawl_site`'s job now and it does its own session management. Nothing called
        `scrape_batch` with more than one URL, so it was folded back in here on 2026-07-30.

        Args:
            url: The URL to fetch. The caller is responsible for SSRF-validating it first
                (`ClaudeToolkit._validate_public_url`); the guard installed here covers
                what that pre-check cannot see.

        Returns:
            {"url": url, "markdown": <raw markdown, or "" if the page had none>}

        Raises:
            Crawl4AIUnavailableError: If `crawl4ai` is not installed.
            Exception: Whatever Playwright raised for this URL (e.g. a navigation
                timeout) propagates — a single-URL caller expects a return or a raise.
        """
        try:
            from crawl4ai import AsyncWebCrawler, BrowserConfig
        except ImportError as exc:
            raise Crawl4AIUnavailableError(
                "Crawl4AI is not installed. Install with "
                "`pip install ibkr_core_mcp[scraper]` and then run `crawl4ai-setup`."
            ) from exc

        profile_dir = _resolve_profile_dir(self._profiles_dir, url)
        browser_config = _browser_config(BrowserConfig, profile_dir)

        async def _scrape_one() -> dict[str, str]:
            async with AsyncWebCrawler(config=browser_config) as crawler:
                crawler.crawler_strategy.set_hook("on_page_context_created", _install_ssrf_guard)
                result = await crawler.arun(url=url)
                markdown = result.markdown.raw_markdown if result.markdown else ""
                return {"url": url, "markdown": markdown}

        with _profile_in_use(profile_dir):
            return _run_async(_scrape_one())  # type: ignore[no-any-return]


def crawl_site(
    url: str,
    profiles_dir: Path,
    max_pages: int = 25,
    max_depth: int = 2,
) -> list[dict[str, Any]]:
    """Crawl a site from `url` with the local browser and return its pages.

    The free replacement for the Firecrawl crawl rung. Breadth-first from the root,
    following only same-host links, using a saved login profile when one matches the
    domain — so a subscription site can be archived, which the paid rung could never do.

    Output is shaped exactly like Firecrawl's page list ({"url", "markdown", "metadata"})
    so it flows into `WebDocsStore.save_crawl` unchanged. That store never knew which
    engine produced its input, which is what makes this substitution a drop-in.

    **The root URL is returned twice by the strategy** — once at depth 0 and again at
    depth 1, byte-identical (observed live 2026-07-30: `docs.crawl4ai.com/` twice at
    14,030 B in a 6-page crawl). Deduplicated here, largest markdown per URL winning.
    Without it `save_crawl` writes one file but appends two manifest entries, and the
    reply claims a page count the archive does not contain.

    Args:
        url: Root URL. The caller is responsible for SSRF validation before calling;
            a second, independent Playwright-level guard is installed here for the
            links the crawl discovers on its own, which no pre-check can see.
        profiles_dir: Root holding one saved login profile per domain.
        max_pages: Upper bound on pages fetched. Clamped to [1, 100]. Measured ~1.2 s
            per page, so 25 is roughly 30 s.
        max_depth: How many link-hops from the root. Clamped to [0, 5]. 0 fetches only
            the root.

    Returns:
        Page dicts with "url", "markdown" and "metadata" (carrying the crawl `depth`),
        deduplicated by URL and with empty pages dropped, so a reported count always
        equals what was archived.

    Raises:
        Crawl4AIUnavailableError: If `crawl4ai` is not installed.
        ValueError: If `url` is blank.
    """
    url = (url or "").strip()
    if not url:
        raise ValueError("url must be non-empty")
    max_pages = max(1, min(100, max_pages))
    max_depth = max(0, min(5, max_depth))

    try:
        from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
        from crawl4ai.deep_crawling import BFSDeepCrawlStrategy
    except ImportError as exc:
        raise Crawl4AIUnavailableError(
            "Crawl4AI is not installed. Install with "
            "`pip install ibkr_core_mcp[scraper]` and then run `crawl4ai-setup`."
        ) from exc

    profile_dir = _resolve_profile_dir(profiles_dir, url)
    browser_config = _browser_config(BrowserConfig, profile_dir)

    async def _crawl() -> list[Any]:
        # include_external=False keeps every hop on the root's host. Verified live: a
        # 6-page crawl of docs.crawl4ai.com touched exactly one hostname. It is also a
        # safety property, not just a scoping one — it is what stops a hostile page from
        # walking the crawler onto another host entirely.
        strategy = BFSDeepCrawlStrategy(max_depth=max_depth, max_pages=max_pages, include_external=False)
        run_config = CrawlerRunConfig(deep_crawl_strategy=strategy, stream=False, verbose=False)
        async with AsyncWebCrawler(config=browser_config) as crawler:
            crawler.crawler_strategy.set_hook("on_page_context_created", _install_ssrf_guard)
            results: list[Any] = await crawler.arun(url, config=run_config)
            return results

    with _profile_in_use(profile_dir):
        results = _run_async(_crawl())

    by_url: dict[str, dict[str, Any]] = {}
    for result in results:
        markdown = result.markdown.raw_markdown if getattr(result, "markdown", None) else ""
        if not markdown:
            continue
        page_url = getattr(result, "url", "") or ""
        metadata = getattr(result, "metadata", None) or {}
        existing = by_url.get(page_url)
        if existing is not None and len(existing["markdown"].encode("utf-8")) >= len(markdown.encode("utf-8")):
            continue
        by_url[page_url] = {
            "url": page_url,
            "markdown": markdown,
            "metadata": {"depth": metadata.get("depth")},
        }
    return list(by_url.values())


def _is_no_information_plateau(scores: list[float]) -> bool:
    """True when BM25's scores carry no ranking information and must not be presented
    as matches.

    **Found by running the tool, not by testing it.** The first live invocation of
    `search_site` answered the deliberate nonsense query "zzzq nonexistent topic xyzzy"
    with ten confidently-ranked pages — the Privacy Policy, the Contributing Guide, the
    home page — every one at exactly 0.500. The unit tests missed it because they mocked
    a non-match as 0.0, which is what a reasonable person assumes BM25 returns. The real
    scorer does something else, and the mock was weaker than the dependency yet again.

    Measured on docs.crawl4ai.com, 2026-07-30, 87 URLs per run:

    | query | max | distinct scores |
    |---|---|---|
    | "deep crawling strategy" | 1.000 | 4 (peak, three 0.4s, 82 zeros) |
    | "save a browser login profile for a paywalled site" | 1.000 | 5 |
    | "zzzq nonexistent topic xyzzy" | 0.500 | **1** — all 87 identical |
    | "qqqqq wwwww eeeee rrrrr" | 0.500 | **1** — all 87 identical |

    With any term overlap the best page normalises to 1.0 and non-matches fall to 0.0.
    With none, every page gets the same neutral 0.5. So the signature of "nothing
    matched" is a completely flat distribution at or below neutral — not a low score.

    The vendor's own `SeedingConfig(score_threshold=...)` cannot express this: 0.51
    correctly empties the nonsense query but also discards the genuine 0.400 and 0.389
    hits from "deep crawling strategy". A threshold answers "how good is this page?";
    the question here is "did the ranking learn anything at all?"

    Args:
        scores: Every numeric relevance score in the result set.

    Returns:
        True if the caller should treat the whole set as "nothing matched". False for an
        empty list (there is nothing to present either way) and for any set showing real
        differentiation. A lone page scoring above neutral is a genuine hit and survives.
    """
    if not scores:
        return False
    distinct = {round(s, 6) for s in scores}
    return len(distinct) == 1 and distinct.pop() <= _NEUTRAL_BM25_SCORE


def search_site(domain: str, query: str, limit: int = 10, source: str = "sitemap+cc") -> list[dict[str, Any]]:
    """Find the pages on one site that match `query`, ranked by BM25 relevance.

    This is *site* search, not web search: `AsyncUrlSeeder` discovers URLs from the
    domain's sitemap and/or the Common Crawl index and scores them against the query.
    It cannot find pages on any other host — passing a query with no domain has no
    meaning here. Whole-web search is `firecrawl_search`, and remains the one job only
    Firecrawl can do.

    Costs nothing and touches no API key: sitemaps and the CC index are public.

    **A saved login profile never applies here, by design.** Unlike `Crawl4AIScraper.scrape`
    and `crawl_site`, this builds no `BrowserConfig` at all — `AsyncUrlSeeder` does its own
    fetching, so `extract_head` reads every page's `<head>` anonymously even on a domain with
    a profile saved. That is the right trade: titles and meta descriptions sit outside the
    paywall on every site tested, so a login buys nothing for *ranking*, and taking the
    profile lock here would serialise discovery behind whatever fetch is running. The login
    matters when you read the page, which is `fetch_page`'s job — so on a subscription site
    the flow is `search_site` to rank anonymously, then `fetch_page` to read with the profile.

    **`extract_head=True` is forced, not a default.** Verified live 2026-07-30 against
    `docs.crawl4ai.com`: with it, 87 of 87 URLs carry a `relevance_score` and
    `"save a browser login profile for a paywalled site"` ranks
    `/advanced/undetected-browser/` first at 1.000. Without it, **zero** URLs are scored
    and the list comes back in arbitrary sitemap order. The vendor's own documented
    example omits the flag (https://docs.crawl4ai.com/assets/llm.txt/txt/url_seeder.txt),
    so copying that example produces something that looks like ranked search and is not.
    Head extraction is what BM25 scores against; without it there is no text to score.

    Args:
        domain: Bare hostname, e.g. "docs.crawl4ai.com". The caller is responsible for
            SSRF validation (ClaudeToolkit._validate_public_url) before calling.
        query: Free-text query. Must be non-empty — an empty query would return the
            sitemap in arbitrary order while presenting itself as a search result.
        limit: Maximum matches to return. Clamped to [1, 50].
        source: "sitemap" (fast, official), "cc" (Common Crawl), or "sitemap+cc".
            Measured on docs.crawl4ai.com: sitemap 87 URLs/5.0 s, sitemap+cc 90/5.9 s.

    Returns:
        Up to `limit` dicts of {"url", "title", "score"}, highest score first.
        **Only pages that actually matched** (score > 0) are returned: BM25 is sparse —
        the same run scored just 4 of 87 URLs above zero — so returning the tail would
        pad a real answer with pages the query did not match.

        An empty list is **ambiguous** in this form: it means "discovered nothing",
        "discovered pages but scored none of them", or "scored them and none matched".
        Only the last is an answer. Use `search_site_detailed` when the difference
        matters — it is what `_handle_search_site` calls, because telling a model
        "none of them is about that, do not retry" after a sitemap 404 is a
        confidently wrong answer that also suppresses recovery.

    Raises:
        Crawl4AIUnavailableError: If `crawl4ai` is not installed.
        ValueError: If `domain` or `query` is blank.
    """
    matches, _stats = search_site_detailed(domain, query, limit=limit, source=source)
    return matches


def search_site_detailed(
    domain: str, query: str, limit: int = 10, source: str = "sitemap+cc"
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """`search_site`, plus what actually happened — so an empty result can be explained.

    Three different situations produced an identical empty list, and the caller could
    not tell them apart:

    | discovered | scored | what it means |
    |---|---|---|
    | 0 | 0 | The sitemap was empty, 404'd, or robots blocked the seeder. **A failure.** |
    | N | 0 | URLs found, but no page yielded a `relevance_score`. **Nothing was ranked.** |
    | N | M>0 | Pages really were read and scored, and none matched. **A real answer.** |

    `_is_no_information_plateau([])` returns `False` — correct for its own contract,
    since an empty score list shows no flat distribution — so the first two rows fell
    through to the same `return []` as the third. `_handle_search_site` then told the
    model the site "was reachable and its pages were read and scored", and instructed it
    not to retry. That is true only of the third row.

    Args:
        domain: Bare hostname. Caller SSRF-validates first, as for `search_site`.
        query: Free-text query; must be non-empty.
        limit: Maximum matches to return. Clamped to [1, 50].
        source: "sitemap", "cc", or "sitemap+cc".

    Returns:
        `(matches, stats)`. `matches` is exactly what `search_site` returns. `stats` is
        `{"discovered": int, "scored": int, "searched": bool}`, where `searched` is True
        only when at least one page was actually ranked against the query — i.e. only
        when an empty `matches` is a real answer rather than a failed lookup.

    Raises:
        Crawl4AIUnavailableError: If `crawl4ai` is not installed.
        ValueError: If `domain` or `query` is blank.
    """
    domain = (domain or "").strip()
    query = (query or "").strip()
    if not domain:
        raise ValueError("domain must be non-empty")
    if not query:
        raise ValueError("query must be non-empty")
    limit = max(1, min(50, limit))

    try:
        from crawl4ai import AsyncUrlSeeder, SeedingConfig
    except ImportError as exc:
        raise Crawl4AIUnavailableError(
            "Crawl4AI is not installed. Install with "
            "`pip install ibkr_core_mcp[scraper]` and then run `crawl4ai-setup`."
        ) from exc

    async def _seed() -> list[dict[str, Any]]:
        config = SeedingConfig(
            source=source,
            query=query,
            scoring_method="bm25",
            extract_head=True,  # mandatory — see docstring
            max_urls=_SEED_MAX_URLS,
        )
        async with AsyncUrlSeeder() as seeder:
            # The vendor ships no type information, so this is Any at the boundary;
            # naming the shape here is the one place it gets asserted.
            seeded: list[dict[str, Any]] = await seeder.urls(domain, config)
            return seeded

    raw: list[dict[str, Any]] = _run_async(_seed())

    scores = [e["relevance_score"] for e in raw if isinstance(e.get("relevance_score"), (int, float))]
    # `searched` is the whole point of this function: it is False when the ranking never
    # ran, so the caller cannot report "we read them and none matched" about pages that
    # were never discovered or never scored.
    stats: dict[str, Any] = {"discovered": len(raw), "scored": len(scores), "searched": bool(scores)}

    if _is_no_information_plateau(scores):
        return [], stats

    matches: list[dict[str, Any]] = []
    for entry in raw:
        score = entry.get("relevance_score")
        if not isinstance(score, (int, float)) or score <= 0:
            continue
        head = entry.get("head_data") or {}
        matches.append(
            {
                "url": entry.get("url", ""),
                "title": (head.get("title") or "").strip(),
                "score": float(score),
            }
        )
    matches.sort(key=lambda m: m["score"], reverse=True)
    return matches[:limit], stats


def create_profile(url_or_domain: str, profiles_dir: Path) -> Path:
    """Interactively log into a site once; save the session for Crawl4AIScraper
    to reuse on future scrapes of that domain.

    Opens a real (non-headless) browser via Crawl4AI's BrowserProfiler — the
    user logs in by hand, then confirms in the terminal to save the profile.
    No password is ever seen or stored by ibkr_core_mcp; only the resulting
    browser profile (cookies/local storage) is copied into `profiles_dir`.

    BrowserProfiler.create_profile() itself saves to crawl4ai's own default
    location (~/.crawl4ai/profiles/<profile_name>); this function copies that
    result into ibkr_core_mcp's own `profiles_dir` so Config.crawl4ai_profiles_dir
    stays the single source of truth Crawl4AIScraper reads from.

    Source: https://docs.crawl4ai.com/advanced/identity-based-crawling/

    **Must be called from the main thread**, and deliberately does NOT use
    `_run_async()`. BrowserProfiler.create_profile() installs a SIGINT handler so
    Ctrl-C closes the browser cleanly, and `signal.signal()` raises
    "signal only works in main thread of the main interpreter" anywhere else.
    `_run_async` exists to survive being called from inside a running event loop
    (mcp_server.py's async dispatch), which it does by handing the coroutine to a
    worker thread — correct for scraping, fatal here. This is an interactive CLI
    operation with exactly one caller (`_main`), so a plain `asyncio.run()` on the
    calling thread is both sufficient and the only thing that works.

    Args:
        url_or_domain: A URL (e.g. "https://www.wsj.com/login") or bare domain
                        (e.g. "www.wsj.com"). Only the hostname is used.
        profiles_dir: Root directory for saved profiles (Config.crawl4ai_profiles_dir).
                       The profile is stored at profiles_dir/<domain>/.

    Returns:
        The path the profile was saved to: profiles_dir/<domain>/.

    Raises:
        Crawl4AIUnavailableError: If `crawl4ai` is not installed.
        RuntimeError: If called off the main thread, or from inside a running event
            loop — both are unsupported for the signal-handler reason above, and
            failing with an explanation beats failing inside the vendor's traceback.
    """
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError(
            "create_profile() must run on the main thread: Crawl4AI's BrowserProfiler "
            "installs a SIGINT handler, and signal handlers cannot be installed from a "
            "worker thread. Run it from the CLI: "
            "`python -m ibkr_core_mcp.local_browser create-profile <url>`."
        )

    try:
        from crawl4ai import BrowserProfiler
    except ImportError as exc:
        raise Crawl4AIUnavailableError(
            "Crawl4AI is not installed. Install with "
            "`pip install ibkr_core_mcp[scraper]` and then run `crawl4ai-setup`."
        ) from exc

    domain = _safe_domain(url_or_domain)
    profiler = BrowserProfiler()
    created_path = Path(asyncio.run(profiler.create_profile(profile_name=domain)))

    profiles_dir.mkdir(parents=True, exist_ok=True)
    dest = profiles_dir / domain
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(created_path, dest)
    return dest


def list_profiles(profiles_dir: Path) -> list[tuple[str, Path, float]]:
    """Return every saved browser profile with its path and age in days.

    Saved sessions expire, and until now expiry presented as a mysteriously truncated
    article with no way to check what was saved or how old it was. Age is taken from the
    directory's mtime, which create_profile sets when it copies the profile in.

    Args:
        profiles_dir: Root holding one profile directory per domain
            (Config.crawl4ai_profiles_dir). A missing directory is not an error.

    Returns:
        (domain, path, age_days) tuples sorted by domain. Non-directory entries are
        skipped. Empty list when nothing is saved.
    """
    if not profiles_dir.is_dir():
        return []
    now = time.time()
    entries: list[tuple[str, Path, float]] = []
    for child in sorted(profiles_dir.iterdir()):
        if not child.is_dir():
            continue
        entries.append((child.name, child, (now - child.stat().st_mtime) / 86400))
    return entries


def _main(argv: list[str] | None = None) -> None:
    """CLI entry point: `python -m ibkr_core_mcp.local_browser create-profile <url-or-domain>`.

    Resolves the profiles root with `config.crawl4ai_profiles_dir_from_env()` rather
    than `Config.from_env()`: both subcommands are browser-only and need nothing
    from Anthropic, and `from_env()` would fail them with "ANTHROPIC_API_KEY is
    required but not set" — an error naming a key neither operation uses.

    `create-profile` additionally requires an interactive terminal, and refuses
    without one. Crawl4AI's keyboard listener falls back to `input()` when there is
    no TTY, `input()` raises EOFError immediately, and EOF is treated as the user
    pressing 'q' — which saves a profile containing no login at all. That profile
    then looks valid to `_resolve_profile_dir`, so `fetch_page` reports "Used a
    saved login profile" while returning the paywall stub. Failing loudly is the
    only safe option.

    Two subcommands exist: `create-profile` and `list-profiles`. The argparse
    subparser structure is kept so a further subcommand (e.g. deleting saved
    profiles) can be added without a breaking CLI change.

    Args:
        argv: Command-line arguments excluding the program name, e.g.
              ["create-profile", "https://www.wsj.com"]. Defaults to
              `sys.argv[1:]` (argparse's normal behavior) when None.
    """
    import argparse

    from ibkr_core_mcp.config import crawl4ai_profiles_dir_from_env

    parser = argparse.ArgumentParser(prog="python -m ibkr_core_mcp.local_browser")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create_parser = subparsers.add_parser(
        "create-profile",
        help="Interactively log into a paywalled site once; save the session for reuse.",
    )
    create_parser.add_argument("url_or_domain")
    subparsers.add_parser(
        "list-profiles",
        help="List saved login profiles and how old each session is.",
    )
    args = parser.parse_args(argv)

    profiles_dir = crawl4ai_profiles_dir_from_env()

    if args.command == "create-profile":
        if not sys.stdin.isatty():
            parser.error(
                "create-profile needs an interactive terminal — you log in by hand, then "
                "press 'q'. Without a TTY, Crawl4AI's input fallback reads EOF, treats it "
                "as 'q' immediately, and saves a profile with no login in it. Run this "
                "command directly in a terminal, not through a pipe, script or task runner."
            )
        dest = create_profile(args.url_or_domain, profiles_dir)
        print(f"Profile saved to {dest}")
    elif args.command == "list-profiles":
        entries = list_profiles(profiles_dir)
        if not entries:
            print(f"No saved profiles in {profiles_dir}")
            return
        for domain, path, age_days in entries:
            print(f"{domain:<30} {age_days:>6.1f} days  {path}")


if __name__ == "__main__":
    _main()
