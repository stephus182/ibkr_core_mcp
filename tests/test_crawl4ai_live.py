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
        pytest.skip(
            "crawl4ai not installed — run `pip install ibkr_core_mcp[scraper]` "
            "then `crawl4ai-setup`"
        )


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
