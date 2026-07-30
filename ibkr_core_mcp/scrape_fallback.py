"""The local Crawl4AI browser for ibkr_core_mcp's web scraping tools.

Crawl4AI is an open-source, Playwright-based crawler that can reuse a locally
saved browser login profile, so a paywalled site the user subscribes to returns
the full article instead of the subscription stub. `crawl4ai` is an optional
dependency (`pip install ibkr_core_mcp[scraper]`) and is only imported when a
scrape actually runs.

`claude_tools.py` reaches this module two ways, and the distinction matters:

  * **As a fallback** — Firecrawl (`web_scraper.py`) runs first for `firecrawl_search`
    and `firecrawl_crawl`; `assess_quality` decides when its result looks incomplete
    (blocked, empty, or paywalled) and the browser recovers what it can.
  * **As the direct route** — the `fetch_page` tool calls `Crawl4AIScraper.scrape()`
    for a single URL with no Firecrawl attempt at all. That is the only route that
    works for a paywalled article, since Firecrawl cannot log in.

Provides:
  Quality                  — "ok" / "ambiguous" / "fallback" classification type
  Crawl4AIUnavailableError — raised when the optional `crawl4ai` dependency is missing
  assess_quality           — classify a scrape result as ok/ambiguous/fallback
  judge_completeness_llm   — one cheap Claude call to resolve "ambiguous" cases
  Crawl4AIScraper          — fetches a single URL via Crawl4AI, reusing a saved
                              login profile for the URL's domain if one exists
  create_profile           — one-time interactive login; saves a browser profile
                              for Crawl4AIScraper to reuse later
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
from collections.abc import Coroutine
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlparse

import anthropic

if TYPE_CHECKING:
    from ibkr_core_mcp.config import Config

Quality = Literal["ok", "ambiguous", "fallback"]

# Cheap, fast model for the binary completeness check — not the main conversation model.
# Model catalogue: see the claude-api skill / https://platform.claude.com/docs/en/docs/about-claude/models
_JUDGE_MODEL = "claude-haiku-4-5-20251001"
_JUDGE_MAX_MARKDOWN_CHARS = 3000

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
      2. The Playwright-level per-request guard installed in
         Crawl4AIScraper.scrape_batch() (see _reject_private_requests below;
         scrape() delegates to scrape_batch() for a single URL), which
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
    """Classify a scraped markdown result as "ok", "ambiguous", or "fallback".

    "fallback" (skip the LLM judge, go straight to Crawl4AI):
      - metadata reports an HTTP error status (>= 400) or an "error" value
      - markdown has fewer than ~40 words (effectively empty)

    "ambiguous" (send to judge_completeness_llm before deciding):
      - a known paywall keyword phrase is present in the markdown
      - word count is in the borderline band (~40-200 words) — real short pages
        exist, so length alone isn't a confident signal either way

    "ok" otherwise.

    Two callers, and they supply different amounts of evidence. The fallback paths
    pass Firecrawl's own page dict, so the HTTP-status branch above is live. The
    `fetch_page` tool passes None, because `Crawl4AIScraper.scrape()` returns
    {"url", "markdown"} and carries no status — there, only the word-count and
    paywall-marker checks apply. Both are honest uses; the second is simply
    working from less.

    Args:
        markdown: The markdown content scraped for this page/result.
        metadata: The scraper's "metadata" dict for this page/result, or None when
             the scraper does not report one (see above).
        url: Source URL, included for future logging/telemetry — not currently
             used in the classification itself.
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


def judge_completeness_llm(config: Config, url: str, markdown: str) -> bool:
    """Ask Claude whether a scraped page looks complete or truncated/paywalled/blocked.

    Only called for assess_quality's "ambiguous" verdict — the confident "ok" and
    "fallback" cases never reach here, so this cheap Haiku call only fires on the
    minority of borderline results.

    Args:
        config: Provides anthropic_api_key (already required by Config).
        url: Source URL, included in the prompt for context.
        markdown: The scraped markdown to judge. Truncated to the first
                  _JUDGE_MAX_MARKDOWN_CHARS characters to keep the call cheap.

    Returns:
        True if Claude's reply contains "COMPLETE" (and not "INCOMPLETE"),
        False otherwise.
    """
    client = anthropic.Anthropic(api_key=config.anthropic_api_key)
    snippet = markdown[:_JUDGE_MAX_MARKDOWN_CHARS]
    prompt = (
        f"Below is scraped content from {url}.\n\n"
        f"---\n{snippet}\n---\n\n"
        "Does this look like the complete page content, or does it look "
        "truncated, paywalled, or blocked (e.g. a login wall, a subscription "
        "prompt, or a Cloudflare/error page)? "
        "Reply with exactly one word: COMPLETE or INCOMPLETE."
    )
    response = client.messages.create(
        model=_JUDGE_MODEL,
        max_tokens=10,
        messages=[{"role": "user", "content": prompt}],
    )
    reply = getattr(response.content[0], "text", "").strip().upper()
    return "INCOMPLETE" not in reply


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


class Crawl4AIScraper:
    """Fallback scraper using Crawl4AI (https://docs.crawl4ai.com/) — a Playwright-based,
    open-source crawler with no API key. Used only when Firecrawl's result looks
    incomplete (see assess_quality / judge_completeness_llm).

    If a browser profile exists for the target URL's domain under `profiles_dir`
    (created via `python -m ibkr_core_mcp.scrape_fallback create-profile <url>`,
    which runs Crawl4AI's BrowserProfiler for a one-time interactive login), the
    scrape reuses that saved login session. Otherwise it scrapes anonymously —
    which will still be incomplete for hard paywalls, and that's expected.

    `crawl4ai` is imported lazily inside scrape() so the base ibkr_core_mcp
    package never requires it.

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

    def scrape_batch(self, urls: list[str], profile_domain: str) -> dict[str, dict[str, str] | Exception]:
        """Scrape multiple URLs using ONE shared Crawl4AI browser session instead
        of launching a fresh Chromium per URL.

        Safe only when every URL in `urls` shares the same saved-profile
        decision -- true for pages within a single Firecrawl crawl() call,
        since Firecrawl's crawl() only returns pages within the same site as
        its root URL. Callers pass that root's domain as `profile_domain`,
        not each individual page's own domain.

        Installs the same Playwright-level SSRF guard (_reject_private_requests)
        as scrape() used to, once per session rather than once per URL -- it
        re-checks every request (navigation, redirects, subresources) the
        shared browser makes across the whole batch.

        Args:
            urls: URLs to fetch. Empty list returns {} without importing
                crawl4ai or launching a browser.
            profile_domain: Domain used to decide whether a saved login
                profile applies (profiles_dir/profile_domain). Pass the
                crawl's root domain -- all pages in one crawl share this
                decision by construction (see above).

        Returns:
            Dict keyed by each input URL. Each value is either a
            {"url": ..., "markdown": ...} result dict (same shape scrape()
            returns) or the Exception raised while fetching that specific
            URL -- one URL failing does not abort the rest of the batch or
            close the shared browser early.

        Raises:
            Crawl4AIUnavailableError: If `crawl4ai` is not installed. Raised
                before the browser is launched, before any URL is attempted --
                an install-time problem, not a per-URL one. Callers that want
                per-page graceful degradation (rather than the whole batch
                failing) must catch this around the scrape_batch() call
                itself, not expect it inside the returned dict.
        """
        if not urls:
            return {}

        try:
            from crawl4ai import AsyncWebCrawler, BrowserConfig
        except ImportError as exc:
            raise Crawl4AIUnavailableError(
                "Crawl4AI is not installed. Install with "
                "`pip install ibkr_core_mcp[scraper]` and then run `crawl4ai-setup`."
            ) from exc

        profile_dir = _resolve_profile_dir(self._profiles_dir, profile_domain)
        if profile_dir is not None:
            browser_config = BrowserConfig(
                headless=True,
                use_managed_browser=True,
                user_data_dir=str(profile_dir),
            )
        else:
            browser_config = BrowserConfig(headless=True)

        async def _scrape_all() -> dict[str, dict[str, str] | Exception]:
            outcomes: dict[str, dict[str, str] | Exception] = {}
            async with AsyncWebCrawler(config=browser_config) as crawler:
                crawler.crawler_strategy.set_hook("on_page_context_created", _install_ssrf_guard)
                for u in urls:
                    try:
                        result = await crawler.arun(url=u)
                        markdown = result.markdown.raw_markdown if result.markdown else ""
                        outcomes[u] = {"url": u, "markdown": markdown}
                    except Exception as exc:
                        # Isolate one URL's failure from the rest of the batch --
                        # the caller inspects each outcome's type to decide how
                        # to degrade, matching scrape()'s single-URL contract.
                        outcomes[u] = exc
            return outcomes

        return _run_async(_scrape_all())  # type: ignore[no-any-return]

    def scrape(self, url: str) -> dict[str, str]:
        """Scrape a single URL with Crawl4AI.

        A 1-URL call to scrape_batch() -- see that method's docstring for the
        full behavior (browser lifecycle, SSRF guard, profile resolution).
        This method exists for callers that only ever need one URL at a time
        (e.g. the search-result fallback path, where each result is typically
        a different domain and batching wouldn't be valid anyway).

        Args:
            url: The URL to fetch.

        Returns:
            {"url": url, "markdown": <raw_markdown or "" if the page had none>}

        Raises:
            Crawl4AIUnavailableError: If `crawl4ai` is not installed.
            Exception: Whatever scrape_batch() caught for this URL specifically
                (e.g. a Playwright navigation error) is re-raised here, since a
                single-URL caller expects scrape() to either return or raise,
                not receive an outcome dict.
        """
        outcome = self.scrape_batch([url], profile_domain=url)[url]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


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
    if profile_dir is not None:
        browser_config = BrowserConfig(headless=True, use_managed_browser=True, user_data_dir=str(profile_dir))
    else:
        browser_config = BrowserConfig(headless=True)

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
        pad a real answer with pages the query did not match. An empty list means
        nothing on that site matched, which is a usable answer.

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
    if _is_no_information_plateau(scores):
        return []

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
    return matches[:limit]


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
            "`python -m ibkr_core_mcp.scrape_fallback create-profile <url>`."
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
    """CLI entry point: `python -m ibkr_core_mcp.scrape_fallback create-profile <url-or-domain>`.

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

    parser = argparse.ArgumentParser(prog="python -m ibkr_core_mcp.scrape_fallback")
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
