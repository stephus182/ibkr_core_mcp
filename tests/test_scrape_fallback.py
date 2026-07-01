import asyncio
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

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
    monkeypatch.setattr(socket, "gethostbyname", lambda h: "93.184.216.34")
    assert is_private_host("example.com") is False


def test_is_private_host_blocks_hostname_resolving_to_private_ip(monkeypatch):
    """The DNS-rebinding-relevant case: hostname resolves to a private IP."""
    import socket

    from ibkr_core_mcp.scrape_fallback import is_private_host
    monkeypatch.setattr(socket, "gethostbyname", lambda h: "127.0.0.1")
    assert is_private_host("evil-rebinding.example") is True


def test_is_private_host_unresolvable_hostname_not_blocked(monkeypatch):
    """Unresolvable hostnames aren't a private-IP bypass — let the fetch fail naturally."""
    import socket

    from ibkr_core_mcp.scrape_fallback import is_private_host
    def _raise(_h):
        raise socket.gaierror("unresolvable")
    monkeypatch.setattr(socket, "gethostbyname", _raise)
    assert is_private_host("nonexistent.invalid") is False


def _make_config(**overrides):
    from ibkr_core_mcp.config import Config
    defaults = dict(
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


@patch("ibkr_core_mcp.scrape_fallback.anthropic")
def test_judge_completeness_llm_true_when_complete(mock_anthropic):
    from ibkr_core_mcp.scrape_fallback import judge_completeness_llm
    mock_client = _mock_anthropic_reply("COMPLETE")
    mock_anthropic.Anthropic.return_value = mock_client

    cfg = _make_config()
    assert judge_completeness_llm(cfg, "https://example.com/article", "full article text") is True
    mock_anthropic.Anthropic.assert_called_once_with(api_key="sk-test")


@patch("ibkr_core_mcp.scrape_fallback.anthropic")
def test_judge_completeness_llm_false_when_incomplete(mock_anthropic):
    from ibkr_core_mcp.scrape_fallback import judge_completeness_llm
    mock_client = _mock_anthropic_reply("INCOMPLETE")
    mock_anthropic.Anthropic.return_value = mock_client

    cfg = _make_config()
    assert judge_completeness_llm(cfg, "https://example.com/article", "Subscribe now...") is False


@patch("ibkr_core_mcp.scrape_fallback.anthropic")
def test_judge_completeness_llm_includes_url_and_markdown_in_prompt(mock_anthropic):
    from ibkr_core_mcp.scrape_fallback import judge_completeness_llm
    mock_client = _mock_anthropic_reply("COMPLETE")
    mock_anthropic.Anthropic.return_value = mock_client

    cfg = _make_config()
    judge_completeness_llm(cfg, "https://example.com/paywalled", "some snippet text")

    call_kwargs = mock_client.messages.create.call_args[1]
    prompt_text = call_kwargs["messages"][0]["content"]
    assert "https://example.com/paywalled" in prompt_text
    assert "some snippet text" in prompt_text


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
    monkeypatch.setattr(socket, "gethostbyname", lambda h: "127.0.0.1")
    route = _FakeRoute()
    await _reject_private_requests(route, _FakeRequest("http://evil-rebinding.example/x"))
    assert route.aborted is True
    assert route.continued is False


@pytest.mark.asyncio
async def test_reject_private_requests_continues_public_host(monkeypatch):
    import socket

    from ibkr_core_mcp.scrape_fallback import _reject_private_requests
    monkeypatch.setattr(socket, "gethostbyname", lambda h: "93.184.216.34")
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


# ── Crawl4AIScraper ──────────────────────────────────────────────────────────

class _FakeCrawlResult:
    def __init__(self, raw_markdown: str) -> None:
        self.markdown = MagicMock(raw_markdown=raw_markdown)


def _install_fake_crawl4ai(monkeypatch, raw_markdown: str = "fetched via crawl4ai"):
    """Inject a fake `crawl4ai` module into sys.modules and return
    (captured_configs, installed_hooks) so tests can assert on both the
    BrowserConfig(**kwargs) calls and the crawler_strategy.set_hook(...) calls."""
    captured_configs: list[dict] = []
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
    fake_module.AsyncWebCrawler = FakeAsyncWebCrawler
    fake_module.BrowserConfig = FakeBrowserConfig
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
    fake_module.BrowserProfiler = FakeBrowserProfiler
    monkeypatch.setitem(sys.modules, "crawl4ai", fake_module)
    return created_at


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


# ── CLI dispatch ─────────────────────────────────────────────────────────────

def test_cli_create_profile_calls_create_profile_with_config_dir(monkeypatch):
    import ibkr_core_mcp.scrape_fallback as sf

    captured = {}

    def fake_create_profile(url_or_domain, profiles_dir):
        captured["url_or_domain"] = url_or_domain
        captured["profiles_dir"] = profiles_dir
        return profiles_dir / "example.com"

    monkeypatch.setattr(sf, "create_profile", fake_create_profile)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("CRAWL4AI_PROFILES_DIR", "/tmp/cli-profiles")

    sf._main(["create-profile", "https://example.com/login"])

    assert captured["url_or_domain"] == "https://example.com/login"
    assert str(captured["profiles_dir"]) == "/tmp/cli-profiles"
