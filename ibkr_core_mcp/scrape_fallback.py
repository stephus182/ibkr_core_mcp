"""
Firecrawl → Crawl4AI fallback for ibkr_core_mcp's web scraping tools.

Firecrawl (web_scraper.py) is the default scraper. This module decides when its
result looks incomplete (blocked, empty, or paywalled) and, when so, falls back
to Crawl4AI — an open-source, Playwright-based crawler that supports reusing a
locally saved browser login profile for paywalled sites the user already
subscribes to. `crawl4ai` is an optional dependency (`pip install
ibkr_core_mcp[scraper]`) and is only imported when the fallback actually runs.

Provides:
  Quality                  — "ok" / "ambiguous" / "fallback" classification type
  Crawl4AIUnavailableError — raised when the optional `crawl4ai` dependency is missing
  assess_quality           — classify a Firecrawl result as ok/ambiguous/fallback
  judge_completeness_llm   — one cheap Claude call to resolve "ambiguous" cases
  Crawl4AIScraper          — fetches a single URL via Crawl4AI, reusing a saved
                              login profile for the URL's domain if one exists
  create_profile           — one-time interactive login; saves a browser profile
                              for Crawl4AIScraper to reuse later

Source: https://docs.crawl4ai.com/ (Crawl4AI, verified against the published
PyPI wheel for crawl4ai==0.5.0 and crawl4ai==0.9.0 on 2026-06-30 — see the
`crawl4ai>=0.5.0` floor note in CLAUDE.md's "Web Scraping" reference table).
"""
from __future__ import annotations

import asyncio
import shutil
import threading
from collections.abc import Coroutine
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlparse

import anthropic

if TYPE_CHECKING:
    from ibkr_core_mcp.config import Config

Quality = Literal["ok", "ambiguous", "fallback"]

# Cheap, fast model for the binary completeness check — not the main conversation model.
# Model catalogue: see the claude-api skill / https://docs.anthropic.com/en/docs/about-claude/models
_JUDGE_MODEL = "claude-haiku-4-5-20251001"
_JUDGE_MAX_MARKDOWN_CHARS = 3000

# assess_quality() thresholds — see its docstring for the classification rules
# these feed into. Real short pages exist, so length alone is never a hard
# "fallback" verdict once markdown is non-trivially present.
_MIN_WORDS_FALLBACK = 40
_MIN_WORDS_CONFIDENT = 200

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


class Crawl4AIUnavailableError(Exception):
    """
    Raised when the optional `crawl4ai` dependency is not installed.

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
    """
    Run an async coroutine from sync code, regardless of whether the calling
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
    """
    Classify a Firecrawl markdown result as "ok", "ambiguous", or "fallback".

    "fallback" (skip the LLM judge, go straight to Crawl4AI):
      - metadata reports an HTTP error status (>= 400) or an "error" value
      - markdown has fewer than ~40 words (effectively empty)

    "ambiguous" (send to judge_completeness_llm before deciding):
      - a known paywall keyword phrase is present in the markdown
      - word count is in the borderline band (~40-200 words) — real short pages
        exist, so length alone isn't a confident signal either way

    "ok" otherwise.

    Args:
        markdown: The markdown content returned by Firecrawl for this page/result.
        metadata: The Firecrawl "metadata" dict for this page/result, or None.
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
    """
    Ask Claude whether a scraped page looks complete or truncated/paywalled/blocked.

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


class Crawl4AIScraper:
    """
    Fallback scraper using Crawl4AI (https://docs.crawl4ai.com/) — a Playwright-based,
    open-source crawler with no API key. Used only when Firecrawl's result looks
    incomplete (see assess_quality / judge_completeness_llm).

    If a browser profile exists for the target URL's domain under `profiles_dir`
    (created via `python -m ibkr_core_mcp.scrape_fallback create-profile <url>`,
    which runs Crawl4AI's BrowserProfiler for a one-time interactive login), the
    scrape reuses that saved login session. Otherwise it scrapes anonymously —
    which will still be incomplete for hard paywalls, and that's expected.

    `crawl4ai` is imported lazily inside scrape() so the base ibkr_core_mcp
    package never requires it.

    Source (BrowserConfig / managed-browser profile reuse):
      https://docs.crawl4ai.com/advanced/identity-based-crawling/

    Args:
        profiles_dir: Root directory for saved login profiles — one subfolder
                       per domain, matching Config.crawl4ai_profiles_dir. The
                       caller does not need to create this directory; scrape()
                       only reads from it and never writes to it (create_profile
                       is what populates it).
    """

    def __init__(self, profiles_dir: Path) -> None:
        self._profiles_dir = profiles_dir

    def scrape(self, url: str) -> dict[str, str]:
        """
        Scrape a single URL with Crawl4AI.

        Launches a fresh headless Chromium instance per call (no connection or
        browser reuse across calls — see the caller-side note in
        ClaudeToolkit._handle_firecrawl_crawl's per-page fallback loop for the
        latency/resource tradeoff this implies for bulk crawls).

        Args:
            url: The URL to fetch. Callers MUST validate this is not a private/
                 loopback/link-local address before calling — this method has
                 no SSRF guard of its own; it trusts the caller (see
                 ClaudeToolkit._validate_public_url / _scrape_with_fallback).

        Returns:
            {"url": url, "markdown": <raw_markdown or "" if the page had none>}

        Raises:
            Crawl4AIUnavailableError: If `crawl4ai` is not installed. Unlike
                create_profile(), this method only imports `AsyncWebCrawler` and
                `BrowserConfig`, both present since crawl4ai 0.4.x — so an old
                crawl4ai install won't hit this error here even though the
                package-wide floor is 0.5.0 (see Crawl4AIUnavailableError).
        """
        try:
            from crawl4ai import AsyncWebCrawler, BrowserConfig
        except ImportError as exc:
            raise Crawl4AIUnavailableError(
                "Crawl4AI is not installed. Install with "
                "`pip install ibkr_core_mcp[scraper]` and then run `crawl4ai-setup`."
            ) from exc

        domain = urlparse(url).hostname or ""
        profile_dir = self._profiles_dir / domain
        if profile_dir.is_dir():
            browser_config = BrowserConfig(
                headless=True,
                use_managed_browser=True,
                user_data_dir=str(profile_dir),
            )
        else:
            browser_config = BrowserConfig(headless=True)

        async def _scrape() -> dict[str, str]:
            async with AsyncWebCrawler(config=browser_config) as crawler:
                result = await crawler.arun(url=url)
                markdown = result.markdown.raw_markdown if result.markdown else ""
                return {"url": url, "markdown": markdown}

        return _run_async(_scrape())  # type: ignore[no-any-return]


def create_profile(url_or_domain: str, profiles_dir: Path) -> Path:
    """
    Interactively log into a site once; save the session for Crawl4AIScraper
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

    Args:
        url_or_domain: A URL (e.g. "https://www.wsj.com/login") or bare domain
                        (e.g. "www.wsj.com"). Only the hostname is used.
        profiles_dir: Root directory for saved profiles (Config.crawl4ai_profiles_dir).
                       The profile is stored at profiles_dir/<domain>/.

    Returns:
        The path the profile was saved to: profiles_dir/<domain>/.

    Raises:
        Crawl4AIUnavailableError: If `crawl4ai` is not installed.
    """
    try:
        from crawl4ai import BrowserProfiler
    except ImportError as exc:
        raise Crawl4AIUnavailableError(
            "Crawl4AI is not installed. Install with "
            "`pip install ibkr_core_mcp[scraper]` and then run `crawl4ai-setup`."
        ) from exc

    domain = urlparse(url_or_domain).hostname or url_or_domain
    profiler = BrowserProfiler()
    created_path = Path(_run_async(profiler.create_profile(profile_name=domain)))

    profiles_dir.mkdir(parents=True, exist_ok=True)
    dest = profiles_dir / domain
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(created_path, dest)
    return dest


def _main(argv: list[str] | None = None) -> None:
    """
    CLI entry point: `python -m ibkr_core_mcp.scrape_fallback create-profile <url-or-domain>`.

    Reads Config.crawl4ai_profiles_dir from the environment (same .env-driven
    Config.from_env() used everywhere else in this package) and delegates to
    create_profile(). Only one subcommand exists today (`create-profile`);
    the argparse subparser structure is kept so a second subcommand (e.g.
    listing or deleting saved profiles) can be added without a breaking CLI
    change.

    Args:
        argv: Command-line arguments excluding the program name, e.g.
              ["create-profile", "https://www.wsj.com"]. Defaults to
              `sys.argv[1:]` (argparse's normal behavior) when None.
    """
    import argparse

    from ibkr_core_mcp.config import Config

    parser = argparse.ArgumentParser(prog="python -m ibkr_core_mcp.scrape_fallback")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create_parser = subparsers.add_parser(
        "create-profile",
        help="Interactively log into a paywalled site once; save the session for reuse.",
    )
    create_parser.add_argument("url_or_domain")
    args = parser.parse_args(argv)

    if args.command == "create-profile":
        config = Config.from_env()
        dest = create_profile(args.url_or_domain, config.crawl4ai_profiles_dir)
        print(f"Profile saved to {dest}")


if __name__ == "__main__":
    _main()
