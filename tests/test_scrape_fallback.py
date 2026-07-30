import asyncio
import io
import sys
import types
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

# ── is_private_host ──────────────────────────────────────────────────────────


def test_is_private_host_blocks_localhost():
    from ibkr_core_mcp.scrape_fallback import is_private_host

    assert is_private_host("localhost") is True


def test_is_private_host_blocks_loopback_ip():
    from ibkr_core_mcp.scrape_fallback import is_private_host

    assert is_private_host("127.0.0.1") is True


def test_is_private_host_blocks_link_local():
    from ibkr_core_mcp.scrape_fallback import is_private_host

    assert is_private_host("169.254.169.254") is True


def test_is_private_host_blocks_private_ip_literal():
    from ibkr_core_mcp.scrape_fallback import is_private_host

    assert is_private_host("192.168.1.1") is True


def test_is_private_host_allows_public_hostname(monkeypatch):
    import socket

    from ibkr_core_mcp.scrape_fallback import is_private_host

    def _fake_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo)
    assert is_private_host("example.com") is False


def test_is_private_host_blocks_hostname_resolving_to_private_ip(monkeypatch):
    """The DNS-rebinding-relevant case: hostname resolves to a private IP."""
    import socket

    from ibkr_core_mcp.scrape_fallback import is_private_host

    def _fake_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo)
    assert is_private_host("evil-rebinding.example") is True


def test_is_private_host_unresolvable_hostname_not_blocked(monkeypatch):
    """Unresolvable hostnames aren't a private-IP bypass — let the fetch fail naturally."""
    import socket

    from ibkr_core_mcp.scrape_fallback import is_private_host

    def _raise(_h, *args, **kwargs):
        raise socket.gaierror("unresolvable")

    monkeypatch.setattr(socket, "getaddrinfo", _raise)
    assert is_private_host("nonexistent.invalid") is False


def test_is_private_host_blocks_aaaa_only_hostname_resolving_to_loopback(monkeypatch):
    """A hostname with no A record but an AAAA record pointing at ::1 must be
    blocked — socket.gethostbyname alone can't see AAAA records and used to
    fail open here. See docs/audits/security-audit-2026-07-11.md H-4."""
    import socket

    from ibkr_core_mcp.scrape_fallback import is_private_host

    def _fake_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::1", 0, 0, 0))]

    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo)
    assert is_private_host("aaaa-only-evil.example") is True


def test_is_private_host_allows_aaaa_only_hostname_resolving_to_public_ipv6(monkeypatch):
    """A genuinely public IPv6-only hostname must still be allowed through."""
    import socket

    from ibkr_core_mcp.scrape_fallback import is_private_host

    def _fake_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2606:2800:220:1:248:1893:25c8:1946", 0, 0, 0))]

    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo)
    assert is_private_host("public-ipv6-only.example") is False


def _make_config(**overrides: Any):
    from ibkr_core_mcp.config import Config

    defaults: dict[str, Any] = dict(
        gateway_url="http://localhost",
        anthropic_api_key="sk-test",
        gdrive_folder_id="root-id",
        sqlite_path=Path("/tmp/store.db"),
        gdrive_token_file=Path("/tmp/token.json"),
        gdrive_credentials_file=Path("/tmp/creds.json"),
    )
    defaults.update(overrides)
    return Config(**defaults)


# ── judge_completeness_llm ───────────────────────────────────────────────────


def _mock_anthropic_reply(text: str) -> MagicMock:
    client = MagicMock()
    block = MagicMock()
    block.text = text
    response = MagicMock()
    response.content = [block]
    client.messages.create.return_value = response
    return client








# ── _run_async ───────────────────────────────────────────────────────────────


def test_run_async_returns_coroutine_result_from_plain_sync_context():
    from ibkr_core_mcp.scrape_fallback import _run_async

    async def coro():
        return "done"

    assert _run_async(coro()) == "done"


def test_run_async_works_when_called_from_a_running_event_loop():
    """This is the actual bug _run_async exists to avoid: ClaudeToolkit.execute()
    is called synchronously from inside mcp_server.py's async handle_call_tool,
    which runs inside asyncio.run(). A plain asyncio.run() inside _run_async would
    raise 'cannot be called from a running event loop' in that case."""
    from ibkr_core_mcp.scrape_fallback import _run_async

    async def inner_coro():
        return "inner-done"

    async def outer():
        # Sync call from within a running loop — mirrors claude_tools.py's usage.
        return _run_async(inner_coro())

    assert asyncio.run(outer()) == "inner-done"


def test_run_async_propagates_exceptions():
    from ibkr_core_mcp.scrape_fallback import _run_async

    async def failing_coro():
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        _run_async(failing_coro())


# ── assess_quality ──────────────────────────────────────────────────────────


def _long_markdown(word_count: int) -> str:
    return " ".join(["word"] * word_count)


def test_assess_quality_empty_markdown_is_fallback():
    from ibkr_core_mcp.scrape_fallback import assess_quality

    assert assess_quality("", None, "https://example.com") == "fallback"


def test_assess_quality_very_short_markdown_is_fallback():
    from ibkr_core_mcp.scrape_fallback import assess_quality

    assert assess_quality(_long_markdown(10), None, "https://example.com") == "fallback"


def test_assess_quality_metadata_error_status_is_fallback():
    from ibkr_core_mcp.scrape_fallback import assess_quality

    markdown = _long_markdown(500)
    metadata = {"statusCode": 403}
    assert assess_quality(markdown, metadata, "https://example.com") == "fallback"


def test_assess_quality_metadata_error_field_is_fallback():
    from ibkr_core_mcp.scrape_fallback import assess_quality

    markdown = _long_markdown(500)
    metadata = {"statusCode": 200, "error": "blocked by Cloudflare"}
    assert assess_quality(markdown, metadata, "https://example.com") == "fallback"


def test_assess_quality_paywall_keyword_is_ambiguous():
    from ibkr_core_mcp.scrape_fallback import assess_quality

    markdown = _long_markdown(500) + "\n\nSubscribe to continue reading this article."
    assert assess_quality(markdown, None, "https://example.com") == "ambiguous"


def test_assess_quality_borderline_length_is_ambiguous():
    from ibkr_core_mcp.scrape_fallback import assess_quality

    # Between the hard-fallback floor and the confident-ok ceiling.
    assert assess_quality(_long_markdown(100), None, "https://example.com") == "ambiguous"


def test_assess_quality_long_clean_markdown_is_ok():
    from ibkr_core_mcp.scrape_fallback import assess_quality

    markdown = _long_markdown(500)
    metadata = {"statusCode": 200}
    assert assess_quality(markdown, metadata, "https://example.com") == "ok"


def test_assess_quality_handles_none_metadata():
    from ibkr_core_mcp.scrape_fallback import assess_quality

    markdown = _long_markdown(500)
    assert assess_quality(markdown, None, "https://example.com") == "ok"


# ── _reject_private_requests (Playwright per-request SSRF guard) ─────────────


class _FakeRoute:
    def __init__(self):
        self.aborted = False
        self.continued = False

    async def abort(self):
        self.aborted = True

    async def continue_(self):
        self.continued = True


class _FakeRequest:
    def __init__(self, url):
        self.url = url


@pytest.mark.asyncio
async def test_reject_private_requests_aborts_private_host():
    from ibkr_core_mcp.scrape_fallback import _reject_private_requests

    route = _FakeRoute()
    await _reject_private_requests(route, _FakeRequest("http://127.0.0.1:5055/v1/api/x"))
    assert route.aborted is True
    assert route.continued is False


@pytest.mark.asyncio
async def test_reject_private_requests_aborts_dns_rebound_host(monkeypatch):
    """The exact DNS-rebinding case: a hostname (not a literal private IP) that
    resolves to a private address at request-interception time — i.e. Chromium's
    own resolution, not the earlier Python-level pre-check's resolution."""
    import socket

    from ibkr_core_mcp.scrape_fallback import _reject_private_requests

    def _fake_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo)
    route = _FakeRoute()
    await _reject_private_requests(route, _FakeRequest("http://evil-rebinding.example/x"))
    assert route.aborted is True
    assert route.continued is False


@pytest.mark.asyncio
async def test_reject_private_requests_continues_public_host(monkeypatch):
    import socket

    from ibkr_core_mcp.scrape_fallback import _reject_private_requests

    def _fake_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo)
    route = _FakeRoute()
    await _reject_private_requests(route, _FakeRequest("https://example.com/article"))
    assert route.continued is True
    assert route.aborted is False


# ── _safe_domain (path-traversal hardening for profiles_dir / domain) ────────


def test_safe_domain_extracts_hostname_from_url():
    from ibkr_core_mcp.scrape_fallback import _safe_domain

    assert _safe_domain("https://www.wsj.com/login") == "www.wsj.com"


def test_safe_domain_accepts_bare_domain():
    from ibkr_core_mcp.scrape_fallback import _safe_domain

    assert _safe_domain("www.wsj.com") == "www.wsj.com"


def test_safe_domain_rejects_dotdot_traversal():
    """A deliberate check, not incidental: profiles_dir / '..' would resolve to
    profiles_dir's parent directory (e.g. ~/.ibkr_core), so a hostname of '..'
    must never reach the path-join, regardless of whether upstream URL
    validation happens to also reject it as an invalid hostname today."""
    from ibkr_core_mcp.scrape_fallback import _safe_domain

    with pytest.raises(ValueError, match="Invalid domain"):
        _safe_domain("https://../evil/")


def test_safe_domain_rejects_path_separator():
    from ibkr_core_mcp.scrape_fallback import _safe_domain

    with pytest.raises(ValueError, match="Invalid domain"):
        _safe_domain("evil/../../etc")


def test_safe_domain_rejects_empty():
    from ibkr_core_mcp.scrape_fallback import _safe_domain

    with pytest.raises(ValueError, match="Invalid domain"):
        _safe_domain("")


# ── _resolve_profile_dir ─────────────────────────────────────────────────────


def test_resolve_profile_dir_prefers_exact_host(tmp_path):
    from ibkr_core_mcp.scrape_fallback import _resolve_profile_dir

    (tmp_path / "markets.ft.com").mkdir()
    (tmp_path / "ft.com").mkdir()

    assert _resolve_profile_dir(tmp_path, "https://markets.ft.com/x") == tmp_path / "markets.ft.com"


def test_resolve_profile_dir_strips_www(tmp_path):
    from ibkr_core_mcp.scrape_fallback import _resolve_profile_dir

    (tmp_path / "ft.com").mkdir()

    assert _resolve_profile_dir(tmp_path, "https://www.ft.com/x") == tmp_path / "ft.com"


def test_resolve_profile_dir_finds_parent_domain_for_subdomain(tmp_path):
    from ibkr_core_mcp.scrape_fallback import _resolve_profile_dir

    (tmp_path / "wsj.com").mkdir()

    assert _resolve_profile_dir(tmp_path, "https://www.wsj.com/articles/x") == tmp_path / "wsj.com"


def test_resolve_profile_dir_stops_at_two_labels(tmp_path):
    from ibkr_core_mcp.scrape_fallback import _resolve_profile_dir

    # A bare-TLD directory must never be matched — stripping stops while two labels remain.
    (tmp_path / "com").mkdir()

    assert _resolve_profile_dir(tmp_path, "https://deep.sub.example.com/x") is None


def test_resolve_profile_dir_returns_none_when_nothing_matches(tmp_path):
    from ibkr_core_mcp.scrape_fallback import _resolve_profile_dir

    assert _resolve_profile_dir(tmp_path, "https://www.ft.com/x") is None


# ── Crawl4AIScraper ──────────────────────────────────────────────────────────


class _FakeCrawlResult:
    def __init__(self, raw_markdown: str) -> None:
        self.markdown = MagicMock(raw_markdown=raw_markdown)


def _install_fake_crawl4ai(monkeypatch, raw_markdown: str = "fetched via crawl4ai"):
    """Inject a fake `crawl4ai` module into sys.modules and return
    (captured_configs, installed_hooks) so tests can assert on both the
    BrowserConfig(**kwargs) calls and the crawler_strategy.set_hook(...) calls."""
    captured_configs: list[dict[str, object]] = []
    installed_hooks: dict[str, object] = {}

    class FakeBrowserConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            captured_configs.append(kwargs)

    class FakeCrawlerStrategy:
        def set_hook(self, hook_type, hook):
            installed_hooks[hook_type] = hook

    class FakeAsyncWebCrawler:
        def __init__(self, config=None):
            self.config = config
            self.crawler_strategy = FakeCrawlerStrategy()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def arun(self, url):
            return _FakeCrawlResult(raw_markdown)

    fake_module = types.ModuleType("crawl4ai")
    setattr(fake_module, "AsyncWebCrawler", FakeAsyncWebCrawler)  # noqa: B010 -- ModuleType has no static attrs; setattr keeps mypy happy too
    setattr(fake_module, "BrowserConfig", FakeBrowserConfig)  # noqa: B010
    monkeypatch.setitem(sys.modules, "crawl4ai", fake_module)
    return captured_configs, installed_hooks


def test_crawl4ai_scraper_raises_when_not_installed(monkeypatch, tmp_path):
    from ibkr_core_mcp.scrape_fallback import Crawl4AIScraper, Crawl4AIUnavailableError

    monkeypatch.setitem(sys.modules, "crawl4ai", None)  # simulates "not installed"

    scraper = Crawl4AIScraper(tmp_path)
    with pytest.raises(Crawl4AIUnavailableError, match="ibkr_core_mcp\\[scraper\\]"):
        scraper.scrape("https://example.com/article")


def test_crawl4ai_scraper_returns_markdown_and_url(monkeypatch, tmp_path):
    from ibkr_core_mcp.scrape_fallback import Crawl4AIScraper

    _install_fake_crawl4ai(monkeypatch, raw_markdown="the full article text")

    scraper = Crawl4AIScraper(tmp_path)
    result = scraper.scrape("https://example.com/article")
    assert result == {"url": "https://example.com/article", "markdown": "the full article text"}


def test_crawl4ai_scraper_uses_saved_profile_when_present(monkeypatch, tmp_path):
    from ibkr_core_mcp.scrape_fallback import Crawl4AIScraper

    captured, _hooks = _install_fake_crawl4ai(monkeypatch)

    profile_dir = tmp_path / "example.com"
    profile_dir.mkdir()

    scraper = Crawl4AIScraper(tmp_path)
    scraper.scrape("https://example.com/paywalled")

    assert captured[0]["use_managed_browser"] is True
    assert captured[0]["user_data_dir"] == str(profile_dir)


def test_crawl4ai_scraper_no_profile_when_absent(monkeypatch, tmp_path):
    from ibkr_core_mcp.scrape_fallback import Crawl4AIScraper

    captured, _hooks = _install_fake_crawl4ai(monkeypatch)

    scraper = Crawl4AIScraper(tmp_path)  # tmp_path/example.com does not exist
    scraper.scrape("https://example.com/anonymous")

    assert not captured[0].get("use_managed_browser")
    assert "user_data_dir" not in captured[0]


def test_crawl4ai_scraper_installs_ssrf_request_guard_hook(monkeypatch, tmp_path):
    """Regression guard for the DNS-rebinding / redirect SSRF gaps: every scrape
    must install a per-request guard on the Playwright page, not just rely on
    the earlier Python-level URL pre-check."""
    from ibkr_core_mcp.scrape_fallback import Crawl4AIScraper

    _captured, hooks = _install_fake_crawl4ai(monkeypatch)

    scraper = Crawl4AIScraper(tmp_path)
    scraper.scrape("https://example.com/article")

    assert "on_page_context_created" in hooks


@pytest.mark.asyncio
async def test_installed_ssrf_hook_registers_reject_private_requests_route(monkeypatch, tmp_path):
    """The installed hook must, when given a page, register
    _reject_private_requests (or equivalent) as the route handler for every
    request the page makes, not just the initial navigation URL."""
    from ibkr_core_mcp.scrape_fallback import Crawl4AIScraper, _reject_private_requests

    _captured, hooks = _install_fake_crawl4ai(monkeypatch)

    scraper = Crawl4AIScraper(tmp_path)
    scraper.scrape("https://example.com/article")
    installed_hook = hooks["on_page_context_created"]

    class _FakePage:
        def __init__(self):
            self.routed = []

        async def route(self, pattern, handler):
            self.routed.append((pattern, handler))

    page = _FakePage()
    await installed_hook(page)
    assert len(page.routed) == 1
    pattern, handler = page.routed[0]
    assert pattern == "**/*"
    assert handler is _reject_private_requests


def _install_fake_crawl4ai_tracking(monkeypatch, markdown_by_url=None, fail_urls=frozenset()):
    """Separate fake-crawl4ai installer used only by scrape_batch tests below:
    tracks how many AsyncWebCrawler instances get constructed (proving reuse
    across multiple arun() calls within one scrape_batch() call) and which
    URLs were actually passed to arun(), in call order. Kept independent from
    _install_fake_crawl4ai above rather than changing that helper's return
    shape, since 5 existing tests depend on its exact 2-tuple return.
    """
    construction_count = {"value": 0}
    arun_urls: list[str] = []

    class FakeCrawlerStrategy:
        def set_hook(self, hook_type, hook):
            pass

    class FakeAsyncWebCrawler:
        def __init__(self, config=None):
            self.config = config
            self.crawler_strategy = FakeCrawlerStrategy()
            construction_count["value"] += 1

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def arun(self, url):
            arun_urls.append(url)
            if url in fail_urls:
                raise RuntimeError("fake crawl4ai failure")
            content = (markdown_by_url or {}).get(url, f"content for {url}")
            return _FakeCrawlResult(content)

    class FakeBrowserConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    fake_module = types.ModuleType("crawl4ai")
    setattr(fake_module, "AsyncWebCrawler", FakeAsyncWebCrawler)  # noqa: B010 -- ModuleType has no static attrs; setattr keeps mypy happy too
    setattr(fake_module, "BrowserConfig", FakeBrowserConfig)  # noqa: B010
    monkeypatch.setitem(sys.modules, "crawl4ai", fake_module)
    return construction_count, arun_urls


def test_scrape_batch_reuses_one_browser_across_all_urls(monkeypatch, tmp_path):
    from ibkr_core_mcp.scrape_fallback import Crawl4AIScraper

    construction_count, arun_urls = _install_fake_crawl4ai_tracking(monkeypatch)

    scraper = Crawl4AIScraper(tmp_path)
    urls = ["https://example.com/a", "https://example.com/b", "https://example.com/c"]
    outcomes = scraper.scrape_batch(urls, profile_domain="https://example.com")

    assert construction_count["value"] == 1
    assert arun_urls == urls
    for url in urls:
        assert outcomes[url] == {"url": url, "markdown": f"content for {url}"}


def test_scrape_batch_isolates_one_url_failure_from_the_rest(monkeypatch, tmp_path):
    from ibkr_core_mcp.scrape_fallback import Crawl4AIScraper

    construction_count, _arun_urls = _install_fake_crawl4ai_tracking(
        monkeypatch, fail_urls=frozenset({"https://example.com/b"})
    )

    scraper = Crawl4AIScraper(tmp_path)
    urls = ["https://example.com/a", "https://example.com/b", "https://example.com/c"]
    outcomes = scraper.scrape_batch(urls, profile_domain="https://example.com")

    assert construction_count["value"] == 1  # browser stayed open despite the failure
    assert outcomes["https://example.com/a"] == {
        "url": "https://example.com/a",
        "markdown": "content for https://example.com/a",
    }
    assert isinstance(outcomes["https://example.com/b"], RuntimeError)
    assert outcomes["https://example.com/c"] == {
        "url": "https://example.com/c",
        "markdown": "content for https://example.com/c",
    }


def test_scrape_batch_empty_urls_returns_empty_dict_without_importing_crawl4ai(tmp_path):
    from ibkr_core_mcp.scrape_fallback import Crawl4AIScraper

    scraper = Crawl4AIScraper(tmp_path)
    assert scraper.scrape_batch([], profile_domain="https://example.com") == {}


# ── create_profile (interactive login → saved profile) ────────────────────────


def _install_fake_browser_profiler(monkeypatch, tmp_path, domain: str = "example.com"):
    """Fake crawl4ai.BrowserProfiler.create_profile: simulates a completed
    interactive login by creating a directory with a marker file, at crawl4ai's
    own default location convention (~/.crawl4ai/profiles/<name>)."""
    created_at = tmp_path / "crawl4ai-default-profiles" / domain
    created_at.mkdir(parents=True)
    (created_at / "cookies.json").write_text("{}")

    class FakeBrowserProfiler:
        async def create_profile(self, profile_name):
            assert profile_name == domain
            return str(created_at)

    fake_module = types.ModuleType("crawl4ai")
    setattr(fake_module, "BrowserProfiler", FakeBrowserProfiler)  # noqa: B010 -- ModuleType has no static attrs; setattr keeps mypy happy too
    monkeypatch.setitem(sys.modules, "crawl4ai", fake_module)
    return created_at


def test_create_profile_runs_the_coroutine_on_the_main_thread(monkeypatch, tmp_path):
    """crawl4ai's BrowserProfiler installs a SIGINT handler so Ctrl-C can close the
    browser cleanly, and signal.signal() raises anywhere but the main thread.

    create_profile() originally routed through _run_async(), which runs the coroutine
    in a worker thread — correct for scraping (it can be called from inside a running
    event loop) and fatal here. The create-profile CLI therefore failed on every
    invocation while the three mocked tests below stayed green, because
    _install_fake_browser_profiler's fake installs no handler. Live failure, first
    real run 2026-07-28:

        ValueError: signal only works in main thread of the main interpreter

    This fake does what the vendor does, so the test fails for the real reason.
    """
    import signal
    import threading

    created_at = tmp_path / "crawl4ai-default-profiles" / "example.com"
    created_at.mkdir(parents=True)
    (created_at / "cookies.json").write_text("{}")

    class SignalInstallingProfiler:
        async def create_profile(self, profile_name):
            previous = signal.getsignal(signal.SIGINT)
            signal.signal(signal.SIGINT, signal.SIG_DFL)  # ValueError off the main thread
            signal.signal(signal.SIGINT, previous if previous is not None else signal.SIG_DFL)
            assert threading.current_thread() is threading.main_thread()
            return str(created_at)

    fake_module = types.ModuleType("crawl4ai")
    setattr(fake_module, "BrowserProfiler", SignalInstallingProfiler)  # noqa: B010
    monkeypatch.setitem(sys.modules, "crawl4ai", fake_module)

    from ibkr_core_mcp.scrape_fallback import create_profile

    dest = create_profile("https://example.com/login", tmp_path / "profiles")

    assert (dest / "cookies.json").exists()


def test_create_profile_raises_when_not_installed(monkeypatch, tmp_path):
    from ibkr_core_mcp.scrape_fallback import Crawl4AIUnavailableError, create_profile

    monkeypatch.setitem(sys.modules, "crawl4ai", None)

    with pytest.raises(Crawl4AIUnavailableError):
        create_profile("https://example.com/login", tmp_path / "profiles")


def test_create_profile_copies_into_profiles_dir_by_domain(monkeypatch, tmp_path):
    from ibkr_core_mcp.scrape_fallback import create_profile

    _install_fake_browser_profiler(monkeypatch, tmp_path, domain="example.com")

    profiles_dir = tmp_path / "profiles"
    dest = create_profile("https://example.com/login", profiles_dir)

    assert dest == profiles_dir / "example.com"
    assert (dest / "cookies.json").exists()


def test_create_profile_accepts_bare_domain(monkeypatch, tmp_path):
    from ibkr_core_mcp.scrape_fallback import create_profile

    _install_fake_browser_profiler(monkeypatch, tmp_path, domain="example.com")

    profiles_dir = tmp_path / "profiles"
    dest = create_profile("example.com", profiles_dir)

    assert dest == profiles_dir / "example.com"


def test_create_profile_overwrites_existing_profile(monkeypatch, tmp_path):
    from ibkr_core_mcp.scrape_fallback import create_profile

    _install_fake_browser_profiler(monkeypatch, tmp_path, domain="example.com")

    profiles_dir = tmp_path / "profiles"
    stale = profiles_dir / "example.com"
    stale.mkdir(parents=True)
    (stale / "stale-marker.txt").write_text("old session")

    dest = create_profile("https://example.com/login", profiles_dir)

    assert not (dest / "stale-marker.txt").exists()
    assert (dest / "cookies.json").exists()


# ── list_profiles ────────────────────────────────────────────────────────────


def test_list_profiles_returns_empty_for_missing_dir(tmp_path):
    from ibkr_core_mcp.scrape_fallback import list_profiles

    assert list_profiles(tmp_path / "nope") == []


def test_list_profiles_reports_each_saved_domain(tmp_path):
    from ibkr_core_mcp.scrape_fallback import list_profiles

    (tmp_path / "www.ft.com").mkdir()
    (tmp_path / "wsj.com").mkdir()
    (tmp_path / "stray-file.txt").write_text("not a profile")

    entries = list_profiles(tmp_path)

    # Alphabetical: "wsj.com" < "www.ft.com" because 's' < 'w' at index 1.
    assert [name for name, _path, _age in entries] == ["wsj.com", "www.ft.com"]
    assert all(age >= 0 for _name, _path, age in entries)


# ── CLI dispatch ─────────────────────────────────────────────────────────────


class _FakeTTY:
    """stdin stand-in that reports itself as a terminal. Under pytest the real
    stdin is captured and `isatty()` is False, which is the condition the CLI now
    refuses on — so every create-profile CLI test has to say which it is."""

    def isatty(self):
        return True


def test_cli_create_profile_does_not_require_an_anthropic_key(monkeypatch, tmp_path):
    """Saving a browser login has nothing to do with Anthropic.

    `_main` resolved its profiles directory via `Config.from_env()`, which raises
    ConfigError("ANTHROPIC_API_KEY is required but not set"). So the documented
    create-profile command failed outright for anyone without an unrelated LLM key
    exported — with an error naming a key the operation never uses.

    test_cli_create_profile_calls_create_profile_with_config_dir below hid this for
    as long as it existed, by setting ANTHROPIC_API_KEY rather than asking why a
    browser-login command needed one.
    """
    import ibkr_core_mcp.scrape_fallback as sf

    captured = {}

    def fake_create_profile(url_or_domain, profiles_dir):
        captured["profiles_dir"] = profiles_dir
        return profiles_dir / "example.com"

    monkeypatch.setattr(sf, "create_profile", fake_create_profile)
    monkeypatch.setattr(sys, "stdin", _FakeTTY())
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("CRAWL4AI_PROFILES_DIR", str(tmp_path / "profiles"))

    sf._main(["create-profile", "https://example.com/login"])

    assert captured["profiles_dir"] == tmp_path / "profiles"


def test_cli_create_profile_refuses_without_a_terminal(monkeypatch, tmp_path):
    """Refusing beats silently saving a profile with no login in it.

    Crawl4AI's keyboard listener needs a TTY. Without one, `_listen_unix` fails on
    termios, the fallback listener's `input()` raises EOFError, and EOF is treated
    as the user pressing 'q' — so the profile saves *immediately*, before any login
    happens. The result is a directory that looks like a valid profile, makes
    fetch_page report "Used a saved login profile", and still returns the paywall
    stub. A loud refusal is the only safe behaviour.
    """
    import ibkr_core_mcp.scrape_fallback as sf

    called = []
    monkeypatch.setattr(sf, "create_profile", lambda u, d: called.append(u))
    monkeypatch.setattr(sys, "stdin", io.StringIO())  # isatty() -> False
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("CRAWL4AI_PROFILES_DIR", str(tmp_path / "profiles"))

    with pytest.raises(SystemExit):
        sf._main(["create-profile", "https://example.com/login"])

    assert called == [], "create_profile must not run without an interactive terminal"


def test_cli_create_profile_calls_create_profile_with_config_dir(monkeypatch):
    import ibkr_core_mcp.scrape_fallback as sf

    captured = {}

    def fake_create_profile(url_or_domain, profiles_dir):
        captured["url_or_domain"] = url_or_domain
        captured["profiles_dir"] = profiles_dir
        return profiles_dir / "example.com"

    monkeypatch.setattr(sf, "create_profile", fake_create_profile)
    monkeypatch.setattr(sys, "stdin", _FakeTTY())
    monkeypatch.setenv("CRAWL4AI_PROFILES_DIR", "/tmp/cli-profiles")

    sf._main(["create-profile", "https://example.com/login"])

    assert captured["url_or_domain"] == "https://example.com/login"
    assert str(captured["profiles_dir"]) == "/tmp/cli-profiles"


# ── search_site (Crawl4AI URL seeder + BM25) ─────────────────────────────────


def _install_fake_seeder(monkeypatch, entries: list[dict[str, Any]]):
    """Inject a fake `crawl4ai` exposing AsyncUrlSeeder/SeedingConfig.

    Returns the list that captures every SeedingConfig(**kwargs) call, so a test can
    assert on what was actually asked of the seeder — `extract_head=True` above all,
    since without it the live API scores nothing and returns sitemap order (verified
    2026-07-30).
    """
    captured: list[dict[str, Any]] = []

    class FakeSeedingConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            captured.append(kwargs)

    class FakeAsyncUrlSeeder:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def urls(self, domain, config):
            captured[-1]["_domain"] = domain
            return entries

    fake_module = types.ModuleType("crawl4ai")
    setattr(fake_module, "AsyncUrlSeeder", FakeAsyncUrlSeeder)  # noqa: B010
    setattr(fake_module, "SeedingConfig", FakeSeedingConfig)  # noqa: B010
    monkeypatch.setitem(sys.modules, "crawl4ai", fake_module)
    return captured


def _entry(url, score, title=None):
    return {
        "url": url,
        "relevance_score": score,
        "head_data": {"title": title} if title else {},
    }


def test_search_site_forces_extract_head(monkeypatch):
    """The single most important assertion in this file's newest section.

    Measured live 2026-07-30 against docs.crawl4ai.com: with extract_head=True, 87 of 87
    URLs carry a relevance_score; with it False, **zero** do and the list is sitemap
    order. The vendor's own documented example omits the flag, so a future "simplify the
    config" edit that drops it would produce something that still returns URLs, still
    looks ranked, and silently is not.
    """
    from ibkr_core_mcp.scrape_fallback import search_site

    captured = _install_fake_seeder(monkeypatch, [_entry("https://x.dev/a", 1.0)])
    search_site("x.dev", "some query")

    assert captured[0]["extract_head"] is True
    assert captured[0]["scoring_method"] == "bm25"
    assert captured[0]["query"] == "some query"
    assert captured[0]["_domain"] == "x.dev"


def test_search_site_drops_zero_scored_pages(monkeypatch):
    """BM25 is sparse — 4 of 87 URLs scored above zero on the live run. Returning the
    tail would pad a real answer with pages the query never matched."""
    from ibkr_core_mcp.scrape_fallback import search_site

    _install_fake_seeder(
        monkeypatch,
        [
            _entry("https://x.dev/hit", 0.9),
            _entry("https://x.dev/miss", 0.0),
            _entry("https://x.dev/unscored", None),
        ],
    )
    results = search_site("x.dev", "q")

    assert [r["url"] for r in results] == ["https://x.dev/hit"]


def test_search_site_returns_nothing_when_every_page_scores_the_same(monkeypatch):
    """The defect the first LIVE run found, and that no mock had caught.

    A nonsense query does not score 0.0 — BM25 hands every page an identical neutral
    0.5, and the tool presented ten confidently-ranked irrelevant pages (Privacy Policy,
    Contributing Guide, home page) as matches. Measured on docs.crawl4ai.com: two
    nonsense queries each produced 87 URLs at exactly 0.5 with ONE distinct score, while
    two real queries peaked at 1.0 with 4-5 distinct scores.

    The old test mocked a miss as 0.0, which is what one assumes and not what happens.
    These fixtures use the values the real scorer returns.
    """
    from ibkr_core_mcp.scrape_fallback import search_site

    _install_fake_seeder(monkeypatch, [_entry(f"https://x.dev/{i}", 0.5) for i in range(87)])

    assert search_site("x.dev", "zzzq nonexistent topic xyzzy") == []


def test_search_site_keeps_a_lone_page_that_scored_above_neutral(monkeypatch):
    """A flat distribution only means "no information" when it sits at or below the
    neutral score. One page scoring 1.0 is a genuine hit, not a plateau — the
    no-information guard must not swallow it."""
    from ibkr_core_mcp.scrape_fallback import search_site

    _install_fake_seeder(monkeypatch, [_entry("https://x.dev/only", 1.0, title="The One Page")])
    results = search_site("x.dev", "q")

    assert [r["url"] for r in results] == ["https://x.dev/only"]


def test_search_site_keeps_real_hits_a_blunt_threshold_would_discard(monkeypatch):
    """Live "deep crawling strategy" scored 1.0 then three pages at 0.400 and one at
    0.389 — all genuine. The vendor's own score_threshold=0.51 empties the nonsense
    query but also throws these away, which is why the plateau check is used instead."""
    from ibkr_core_mcp.scrape_fallback import search_site

    _install_fake_seeder(
        monkeypatch,
        [
            _entry("https://x.dev/deep", 1.0),
            _entry("https://x.dev/multi", 0.4),
            _entry("https://x.dev/adaptive", 0.4),
            _entry("https://x.dev/identity", 0.389),
            *[_entry(f"https://x.dev/miss{i}", 0.0) for i in range(82)],
        ],
    )
    results = search_site("x.dev", "deep crawling strategy")

    assert len(results) == 4
    assert results[0]["url"] == "https://x.dev/deep"
    assert results[-1]["score"] == pytest.approx(0.389)


def test_search_site_ranks_highest_score_first(monkeypatch):
    from ibkr_core_mcp.scrape_fallback import search_site

    _install_fake_seeder(
        monkeypatch,
        [_entry("https://x.dev/low", 0.2), _entry("https://x.dev/top", 1.0), _entry("https://x.dev/mid", 0.5)],
    )
    results = search_site("x.dev", "q")

    assert [r["url"] for r in results] == ["https://x.dev/top", "https://x.dev/mid", "https://x.dev/low"]


def test_search_site_extracts_the_title_from_head_data(monkeypatch):
    """head_data is a dict (verified live), not a JSON string — reading it as text
    would put a repr in front of the user."""
    from ibkr_core_mcp.scrape_fallback import search_site

    _install_fake_seeder(monkeypatch, [_entry("https://x.dev/a", 1.0, title="Deep Crawling - Docs")])
    assert search_site("x.dev", "q")[0]["title"] == "Deep Crawling - Docs"


def test_search_site_clamps_limit_and_applies_it_after_ranking(monkeypatch):
    """The limit bounds the ANSWER, not the candidate pool: _SEED_MAX_URLS is what the
    seeder is asked for, so a small limit cannot truncate the pool before scoring."""
    from ibkr_core_mcp.scrape_fallback import _SEED_MAX_URLS, search_site

    captured = _install_fake_seeder(
        monkeypatch, [_entry(f"https://x.dev/{i}", 1.0 - i / 100) for i in range(30)]
    )
    results = search_site("x.dev", "q", limit=3)

    assert len(results) == 3
    assert results[0]["url"] == "https://x.dev/0"
    assert captured[0]["max_urls"] == _SEED_MAX_URLS


def test_search_site_rejects_a_blank_query(monkeypatch):
    """An empty query would return the sitemap in arbitrary order while presenting
    itself as a search result — the exact shape of a silent wrong answer."""
    from ibkr_core_mcp.scrape_fallback import search_site

    _install_fake_seeder(monkeypatch, [])
    with pytest.raises(ValueError, match="query must be non-empty"):
        search_site("x.dev", "   ")
    with pytest.raises(ValueError, match="domain must be non-empty"):
        search_site("  ", "q")


def test_search_site_raises_when_crawl4ai_is_not_installed(monkeypatch):
    from ibkr_core_mcp.scrape_fallback import Crawl4AIUnavailableError, search_site

    monkeypatch.setitem(sys.modules, "crawl4ai", None)
    with pytest.raises(Crawl4AIUnavailableError, match="ibkr_core_mcp\\[scraper\\]"):
        search_site("x.dev", "q")


# ── crawl_site (Crawl4AI deep crawl, the free replacement for firecrawl_crawl) ──


class _FakeDeepResult:
    def __init__(self, url, raw_markdown, depth=0):
        self.url = url
        self.markdown = MagicMock(raw_markdown=raw_markdown) if raw_markdown is not None else None
        self.metadata = {"depth": depth}


def _install_fake_deep_crawler(monkeypatch, results: list[Any]):
    """Fake `crawl4ai` exposing the deep-crawl surface. Returns (captured_browser_kwargs,
    captured_strategy_kwargs, installed_hooks) so tests can assert on domain confinement,
    the page cap, and that the SSRF guard was installed."""
    browser_kwargs: list[dict[str, Any]] = []
    strategy_kwargs: list[dict[str, Any]] = []
    installed_hooks: dict[str, object] = {}

    class FakeBrowserConfig:
        def __init__(self, **kwargs):
            browser_kwargs.append(kwargs)

    class FakeCrawlerRunConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeBFS:
        def __init__(self, **kwargs):
            strategy_kwargs.append(kwargs)

    class FakeStrategy:
        def set_hook(self, hook_type, hook):
            installed_hooks[hook_type] = hook

    class FakeAsyncWebCrawler:
        def __init__(self, config=None):
            self.crawler_strategy = FakeStrategy()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def arun(self, url, config=None):
            return results

    fake = types.ModuleType("crawl4ai")
    setattr(fake, "AsyncWebCrawler", FakeAsyncWebCrawler)  # noqa: B010
    setattr(fake, "BrowserConfig", FakeBrowserConfig)  # noqa: B010
    setattr(fake, "CrawlerRunConfig", FakeCrawlerRunConfig)  # noqa: B010
    fake_deep = types.ModuleType("crawl4ai.deep_crawling")
    setattr(fake_deep, "BFSDeepCrawlStrategy", FakeBFS)  # noqa: B010
    monkeypatch.setitem(sys.modules, "crawl4ai", fake)
    monkeypatch.setitem(sys.modules, "crawl4ai.deep_crawling", fake_deep)
    return browser_kwargs, strategy_kwargs, installed_hooks


def test_crawl_site_deduplicates_the_root_url(monkeypatch, tmp_path):
    """The strategy returns the root TWICE — depth 0 and depth 1, byte-identical
    (observed live: docs.crawl4ai.com/ twice at 14,030 B in a 6-page crawl).

    Left in, save_crawl writes one file but appends two manifest entries, so the reply
    claims a page count the archive does not contain. Found by probing the real API
    before writing the function, not by a test failing afterwards.
    """
    from ibkr_core_mcp.scrape_fallback import crawl_site

    _install_fake_deep_crawler(
        monkeypatch,
        [
            _FakeDeepResult("https://d.dev/", "root content", depth=0),
            _FakeDeepResult("https://d.dev/", "root content", depth=1),
            _FakeDeepResult("https://d.dev/a", "page a", depth=1),
        ],
    )
    pages = crawl_site("https://d.dev/", tmp_path)

    assert [p["url"] for p in pages] == ["https://d.dev/", "https://d.dev/a"]


def test_crawl_site_keeps_the_larger_copy_of_a_duplicated_url(monkeypatch, tmp_path):
    from ibkr_core_mcp.scrape_fallback import crawl_site

    _install_fake_deep_crawler(
        monkeypatch,
        [
            _FakeDeepResult("https://d.dev/x", "short", depth=0),
            _FakeDeepResult("https://d.dev/x", "much longer content here", depth=1),
        ],
    )
    pages = crawl_site("https://d.dev/", tmp_path)

    assert len(pages) == 1
    assert pages[0]["markdown"] == "much longer content here"


def test_crawl_site_confines_the_crawl_to_one_host_and_caps_pages(monkeypatch, tmp_path):
    """include_external=False is a safety property, not just scoping: it is what stops a
    hostile page walking the crawler onto another host."""
    from ibkr_core_mcp.scrape_fallback import crawl_site

    _, strategy_kwargs, hooks = _install_fake_deep_crawler(
        monkeypatch, [_FakeDeepResult("https://d.dev/", "c")]
    )
    crawl_site("https://d.dev/", tmp_path, max_pages=7, max_depth=3)

    assert strategy_kwargs[0]["include_external"] is False
    assert strategy_kwargs[0]["max_pages"] == 7
    assert strategy_kwargs[0]["max_depth"] == 3
    # The per-request SSRF guard matters most here: a deep crawl follows links nobody
    # pre-validated, because nobody knew they existed.
    assert "on_page_context_created" in hooks


def test_crawl_site_clamps_absurd_bounds(monkeypatch, tmp_path):
    from ibkr_core_mcp.scrape_fallback import crawl_site

    _, strategy_kwargs, _ = _install_fake_deep_crawler(monkeypatch, [_FakeDeepResult("https://d.dev/", "c")])
    crawl_site("https://d.dev/", tmp_path, max_pages=99999, max_depth=99)

    assert strategy_kwargs[0]["max_pages"] == 100
    assert strategy_kwargs[0]["max_depth"] == 5


def test_crawl_site_drops_empty_pages_so_the_count_is_honest(monkeypatch, tmp_path):
    from ibkr_core_mcp.scrape_fallback import crawl_site

    _install_fake_deep_crawler(
        monkeypatch,
        [
            _FakeDeepResult("https://d.dev/good", "real content"),
            _FakeDeepResult("https://d.dev/empty", ""),
            _FakeDeepResult("https://d.dev/none", None),
        ],
    )
    pages = crawl_site("https://d.dev/", tmp_path)

    assert [p["url"] for p in pages] == ["https://d.dev/good"]


def test_crawl_site_uses_a_saved_login_profile_when_one_matches(monkeypatch, tmp_path):
    """Archiving a subscription site is something the paid rung could never do."""
    from ibkr_core_mcp.scrape_fallback import crawl_site

    (tmp_path / "d.dev").mkdir()
    browser_kwargs, _, _ = _install_fake_deep_crawler(monkeypatch, [_FakeDeepResult("https://d.dev/", "c")])
    crawl_site("https://d.dev/", tmp_path)

    assert browser_kwargs[0]["use_managed_browser"] is True
    assert browser_kwargs[0]["user_data_dir"].endswith("d.dev")


def test_crawl_site_raises_when_crawl4ai_is_not_installed(monkeypatch, tmp_path):
    from ibkr_core_mcp.scrape_fallback import Crawl4AIUnavailableError, crawl_site

    monkeypatch.setitem(sys.modules, "crawl4ai", None)
    with pytest.raises(Crawl4AIUnavailableError, match="ibkr_core_mcp\\[scraper\\]"):
        crawl_site("https://d.dev/", tmp_path)
