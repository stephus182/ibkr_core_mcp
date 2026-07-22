"""Live integration tests for the real Crawl4AI fallback (Playwright-driven).

Unlike tests/test_web_scraper_live.py (Firecrawl only, no crawl4ai) and
tests/test_scrape_fallback.py (crawl4ai fully mocked), these tests require
the optional `crawl4ai` dependency actually installed with its browser
downloaded:
    pip install "ibkr_core_mcp[scraper]"
    crawl4ai-setup

All tests requiring a real browser skip automatically if `crawl4ai` isn't
importable. The SSRF pre-check test does NOT require crawl4ai — it must
hold regardless of whether the optional dependency is installed.

Run:
    pytest tests/test_crawl4ai_live.py -v -m integration
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture(scope="module")
def crawl4ai_available():
    try:
        import crawl4ai  # noqa: F401
    except ImportError:
        pytest.skip("crawl4ai not installed — run `pip install ibkr_core_mcp[scraper]` then `crawl4ai-setup`")


@pytest.fixture()
def toolkit(tmp_path):
    from ibkr_core_mcp.claude_tools import ClaudeToolkit
    from ibkr_core_mcp.config import Config

    config = Config(
        gateway_url="https://localhost:5055/v1/api",
        anthropic_api_key="test-key",
        gdrive_folder_id="",
        sqlite_path=tmp_path / "store.db",
        gdrive_token_file=tmp_path / "token.json",
        gdrive_credentials_file=tmp_path / "credentials.json",
        crawl4ai_profiles_dir=tmp_path / "crawl4ai_profiles",
    )
    return ClaudeToolkit(MagicMock(), MagicMock(), MagicMock(), config)


@pytest.mark.integration
def test_crawl4ai_scraper_real_browser_scrape(crawl4ai_available, tmp_path):
    """Direct Crawl4AIScraper.scrape() against a real, stable, static page —
    proves the real Playwright/Chromium round-trip works end to end."""
    from ibkr_core_mcp.scrape_fallback import Crawl4AIScraper

    scraper = Crawl4AIScraper(tmp_path / "profiles")
    result = scraper.scrape("https://example.com")

    assert result["url"] == "https://example.com"
    assert "Example Domain" in result["markdown"]


@pytest.mark.integration
def test_scrape_with_fallback_triggers_real_crawl4ai_on_empty_firecrawl_result(crawl4ai_available, toolkit):
    """Empty Firecrawl markdown makes assess_quality() return "fallback",
    which skips the LLM judge entirely and routes straight to the real
    Crawl4AIScraper — proving the full wiring, not just the isolated unit."""
    markdown, note, used_fallback = toolkit._scrape_with_fallback("https://example.com", "", {})

    assert "Example Domain" in markdown
    assert "Crawl4AI fallback" in note
    assert used_fallback is True


@pytest.mark.integration
def test_scrape_batch_reuses_one_real_browser_across_two_real_urls(crawl4ai_available, tmp_path):
    """Crawl4AIScraper.scrape_batch() against two real, stable, static pages --
    proves actual browser reuse (not just the fully-mocked unit test in
    tests/test_scrape_fallback.py) by wrapping the real AsyncWebCrawler class
    with a construction counter, while still exercising the genuine
    Playwright/Chromium round-trip for every arun() call."""
    import crawl4ai

    from ibkr_core_mcp.scrape_fallback import Crawl4AIScraper

    construction_count = {"value": 0}
    RealAsyncWebCrawler = crawl4ai.AsyncWebCrawler

    class CountingAsyncWebCrawler(RealAsyncWebCrawler):  # type: ignore[misc,valid-type]
        def __init__(self, *args, **kwargs):
            construction_count["value"] += 1
            super().__init__(*args, **kwargs)

    original = crawl4ai.AsyncWebCrawler
    crawl4ai.AsyncWebCrawler = CountingAsyncWebCrawler
    try:
        scraper = Crawl4AIScraper(tmp_path / "profiles")
        urls = ["https://example.com", "https://example.org"]
        outcomes = scraper.scrape_batch(urls, profile_domain="https://example.com")
    finally:
        crawl4ai.AsyncWebCrawler = original

    assert construction_count["value"] == 1  # one real Chromium session for both URLs
    for url in urls:
        outcome = outcomes[url]
        assert not isinstance(outcome, Exception), f"{url} failed: {outcome}"
        assert outcome["url"] == url
        assert "Example Domain" in outcome["markdown"]


@pytest.mark.integration
def test_scrape_with_fallback_blocks_private_host_before_any_browser_launch(toolkit):
    """The Python-level SSRF guard (_validate_public_url) must reject a
    private-host URL before Crawl4AI is even imported — this must hold
    whether or not the optional `crawl4ai` dependency is installed, so this
    test intentionally does not depend on the crawl4ai_available fixture."""
    markdown, note, used_fallback = toolkit._scrape_with_fallback("http://127.0.0.1:9/", "", {})

    assert markdown == ""
    assert "Blocked" in note
    assert used_fallback is False
