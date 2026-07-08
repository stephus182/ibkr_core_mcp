from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.web_scraping

_REALISTIC_MARKDOWN = (
    "# IBKR API Documentation Overview\n\n"
    "The Interactive Brokers Client Portal API provides programmatic access to "
    "account information, market data, and order management functionality for "
    "developers building automated trading applications. This reference covers "
    "authentication flows, the two-call warmup pattern required by several "
    "endpoints, and the rate limits enforced per endpoint group. Developers "
    "should note that market data snapshots may be delayed by fifteen minutes "
    "unless a real-time data subscription is active on the account. Historical "
    "data requests are paginated in batches of up to one thousand data points "
    "and support both daily and intraday bar sizes. Order placement endpoints "
    "require an active brokerage session established through the gateway browser-based "
    "login flow, since the Client Portal Gateway must run on the "
    "same machine as the browser used for authentication. Session cookies "
    "expire after a period of inactivity, so client applications are expected "
    "to call the tickle endpoint at regular intervals to keep the session "
    "alive. This documentation also describes the Flex Web Service, a separate "
    "reporting mechanism that provides back-office trade data with a one-day "
    "settlement delay, in contrast to the near-real-time data available "
    "through the standard Client Portal endpoints described above in detail. "
    "Readers who need a deeper technical walkthrough should consult the full "
    "endpoint reference table later in this guide, which lists every supported "
    "operation alongside its required parameters and expected response shape."
)

# ============================================================================
# Firecrawl handler tests
# ============================================================================


def _make_toolkit():
    """Return a ClaudeToolkit with all dependencies mocked."""
    from pathlib import Path

    from ibkr_core_mcp.claude_tools import ClaudeToolkit
    from ibkr_core_mcp.config import Config
    cfg = Config(
        gateway_url="http://localhost",
        anthropic_api_key="sk-test",
        gdrive_folder_id="root-id",
        sqlite_path=Path("/tmp/store.db"),
        gdrive_token_file=Path("/tmp/token.json"),
        gdrive_credentials_file=Path("/tmp/creds.json"),
        firecrawl_api_key="fc-test",
    )
    toolkit = ClaudeToolkit(
        client=MagicMock(),
        cache=MagicMock(),
        store=MagicMock(),
        config=cfg,
    )
    return toolkit


def test_firecrawl_search_returns_no_key_message_when_key_missing():
    from pathlib import Path

    from ibkr_core_mcp.claude_tools import ClaudeToolkit
    from ibkr_core_mcp.config import Config
    cfg = Config(
        gateway_url="http://localhost",
        anthropic_api_key="sk-test",
        gdrive_folder_id="root-id",
        sqlite_path=Path("/tmp/store.db"),
        gdrive_token_file=Path("/tmp/token.json"),
        gdrive_credentials_file=Path("/tmp/creds.json"),
        firecrawl_api_key="",
    )
    toolkit = ClaudeToolkit(client=MagicMock(), cache=MagicMock(), store=MagicMock(), config=cfg)
    result, fig = toolkit.execute("firecrawl_search", {"query": "test"})
    assert "FIRECRAWL_API_KEY" in result
    assert fig is None


@patch("ibkr_core_mcp.web_scraper.FirecrawlClient")
def test_firecrawl_search_returns_formatted_results(mock_fc_cls):
    toolkit = _make_toolkit()
    mock_fc = MagicMock()
    mock_fc.search.return_value = [
        {"url": "https://example.com", "title": "Example", "markdown": _REALISTIC_MARKDOWN}
    ]
    mock_fc_cls.return_value = mock_fc

    result, fig = toolkit.execute("firecrawl_search", {"query": "IBKR API", "limit": 3})
    assert "## Search results for: IBKR API" in result
    assert fig is None
    mock_fc.search.assert_called_once_with("IBKR API", limit=3)


@patch("ibkr_core_mcp.web_scraper.FirecrawlClient")
@patch("ibkr_core_mcp.web_scraper.WebDocsStore")
def test_firecrawl_search_saves_to_drive_when_requested(mock_wds_cls, mock_fc_cls):
    toolkit = _make_toolkit()
    mock_fc = MagicMock()
    mock_fc.search.return_value = [{"url": "u", "title": "t", "markdown": "m"}]
    mock_fc_cls.return_value = mock_fc
    mock_wds = MagicMock()
    mock_wds.save_search.return_value = "file-id-123"
    mock_wds_cls.return_value = mock_wds

    result, _ = toolkit.execute("firecrawl_search", {"query": "test", "save_to_drive": True})
    mock_wds.save_search.assert_called_once()
    assert "file-id-123" in result or "Drive" in result


def test_firecrawl_crawl_blocks_private_url():
    toolkit = _make_toolkit()
    result, fig = toolkit.execute("firecrawl_crawl", {"url": "http://localhost:5055/api"})
    assert "Blocked" in result
    assert fig is None


def test_firecrawl_crawl_returns_no_key_message_when_key_missing():
    from pathlib import Path

    from ibkr_core_mcp.claude_tools import ClaudeToolkit
    from ibkr_core_mcp.config import Config
    cfg = Config(
        gateway_url="http://localhost",
        anthropic_api_key="sk-test",
        gdrive_folder_id="root-id",
        sqlite_path=Path("/tmp/store.db"),
        gdrive_token_file=Path("/tmp/token.json"),
        gdrive_credentials_file=Path("/tmp/creds.json"),
        firecrawl_api_key="",
    )
    toolkit = ClaudeToolkit(client=MagicMock(), cache=MagicMock(), store=MagicMock(), config=cfg)
    result, fig = toolkit.execute("firecrawl_crawl", {"url": "https://example.com"})
    assert "FIRECRAWL_API_KEY" in result
    assert fig is None


@patch("ibkr_core_mcp.web_scraper.FirecrawlClient")
@patch("ibkr_core_mcp.web_scraper.WebDocsStore")
def test_firecrawl_crawl_saves_pages_to_drive(mock_wds_cls, mock_fc_cls):
    toolkit = _make_toolkit()
    mock_fc = MagicMock()
    mock_fc.crawl.return_value = [
        {"url": "https://example.com/page", "markdown": _REALISTIC_MARKDOWN}
    ]
    mock_fc_cls.return_value = mock_fc
    mock_wds = MagicMock()
    mock_wds.save_crawl.return_value = {
        "url": "https://example.com",
        "crawled_at": "2026-01-01T00:00:00+00:00",
        "pages": [{"url": "https://example.com/page", "file_id": "fid"}],
    }
    mock_wds_cls.return_value = mock_wds

    result, fig = toolkit.execute("firecrawl_crawl", {"url": "https://example.com"})
    assert "Crawl complete: saved 1 page(s)" in result
    assert fig is None
    mock_wds.save_crawl.assert_called_once()


# ============================================================================
# Crawl4AI fallback wiring (_scrape_with_fallback + handler integration)
# ============================================================================


def _long_markdown(word_count: int) -> str:
    return " ".join(["word"] * word_count)


def test_scrape_with_fallback_returns_original_when_quality_ok():
    toolkit = _make_toolkit()
    markdown = _long_markdown(500)
    result, note = toolkit._scrape_with_fallback(
        "https://example.com/article", markdown, {"statusCode": 200}
    )
    assert result == markdown
    assert note == ""


@patch("ibkr_core_mcp.scrape_fallback.Crawl4AIScraper")
def test_scrape_with_fallback_uses_crawl4ai_when_quality_is_fallback(mock_cls):
    toolkit = _make_toolkit()
    mock_scraper = MagicMock()
    mock_scraper.scrape.return_value = {
        "url": "https://example.com/article",
        "markdown": "the full recovered article text",
    }
    mock_cls.return_value = mock_scraper

    result, note = toolkit._scrape_with_fallback(
        "https://example.com/article", "", None
    )
    assert result == "the full recovered article text"
    assert "Crawl4AI" in note
    mock_scraper.scrape.assert_called_once_with("https://example.com/article")


@patch("ibkr_core_mcp.scrape_fallback.Crawl4AIScraper")
@patch("ibkr_core_mcp.scrape_fallback.judge_completeness_llm")
def test_scrape_with_fallback_ambiguous_and_llm_says_complete_keeps_original(
    mock_judge, mock_cls
):
    toolkit = _make_toolkit()
    mock_judge.return_value = True
    markdown = _long_markdown(100)  # borderline band → ambiguous

    result, note = toolkit._scrape_with_fallback(
        "https://example.com/article", markdown, None
    )
    assert result == markdown
    assert note == ""
    mock_cls.return_value.scrape.assert_not_called()


@patch("ibkr_core_mcp.scrape_fallback.Crawl4AIScraper")
@patch("ibkr_core_mcp.scrape_fallback.judge_completeness_llm")
def test_scrape_with_fallback_ambiguous_and_llm_says_incomplete_falls_back(
    mock_judge, mock_cls
):
    toolkit = _make_toolkit()
    mock_judge.return_value = False
    mock_scraper = MagicMock()
    mock_scraper.scrape.return_value = {
        "url": "https://example.com/article",
        "markdown": "recovered full content",
    }
    mock_cls.return_value = mock_scraper
    markdown = _long_markdown(100)

    result, note = toolkit._scrape_with_fallback(
        "https://example.com/article", markdown, None
    )
    assert result == "recovered full content"
    assert "Crawl4AI" in note


@patch("ibkr_core_mcp.scrape_fallback.Crawl4AIScraper")
def test_scrape_with_fallback_crawl4ai_unavailable_returns_original_with_note(mock_cls):
    from ibkr_core_mcp.scrape_fallback import Crawl4AIUnavailableError
    toolkit = _make_toolkit()
    mock_cls.return_value.scrape.side_effect = Crawl4AIUnavailableError(
        "Crawl4AI is not installed. Install with `pip install ibkr_core_mcp[scraper]`."
    )

    result, note = toolkit._scrape_with_fallback(
        "https://example.com/article", "", None
    )
    assert result == ""
    assert "ibkr_core_mcp[scraper]" in note


@patch("ibkr_core_mcp.scrape_fallback.Crawl4AIScraper")
def test_scrape_with_fallback_notes_missing_login_profile(mock_cls, tmp_path):
    toolkit = _make_toolkit()
    toolkit._config.crawl4ai_profiles_dir = tmp_path  # no example.com/ subfolder
    mock_cls.return_value.scrape.return_value = {
        "url": "https://example.com/article",
        "markdown": "partial anonymous content",
    }

    _, note = toolkit._scrape_with_fallback("https://example.com/article", "", None)
    assert "no saved login profile" in note
    assert "create-profile" in note


@patch("ibkr_core_mcp.scrape_fallback.Crawl4AIScraper")
def test_scrape_with_fallback_notes_saved_login_profile_used(mock_cls, tmp_path):
    toolkit = _make_toolkit()
    (tmp_path / "example.com").mkdir()
    toolkit._config.crawl4ai_profiles_dir = tmp_path
    mock_cls.return_value.scrape.return_value = {
        "url": "https://example.com/article",
        "markdown": "full subscriber content",
    }

    _, note = toolkit._scrape_with_fallback("https://example.com/article", "", None)
    assert "saved login profile" in note
    assert "no saved login profile" not in note


@patch("ibkr_core_mcp.web_scraper.FirecrawlClient")
@patch("ibkr_core_mcp.scrape_fallback.Crawl4AIScraper")
def test_firecrawl_search_applies_fallback_when_result_incomplete(mock_c4a_cls, mock_fc_cls):
    toolkit = _make_toolkit()
    mock_fc = MagicMock()
    mock_fc.search.return_value = [
        {
            "url": "https://wsj.com/article",
            "title": "Paywalled Article",
            "markdown": "Subscribe now to keep reading.",
            "metadata": {},
        }
    ]
    mock_fc_cls.return_value = mock_fc
    mock_c4a_cls.return_value.scrape.return_value = {
        "url": "https://wsj.com/article",
        "markdown": "the full recovered article body",
    }

    result, fig = toolkit.execute("firecrawl_search", {"query": "wsj article"})
    assert "the full recovered article body" in result
    assert "Crawl4AI" in result
    assert fig is None


def test_validate_public_url_blocks_localhost():
    toolkit = _make_toolkit()
    assert toolkit._validate_public_url("http://localhost:5055/api") is not None


def test_validate_public_url_blocks_link_local():
    toolkit = _make_toolkit()
    assert toolkit._validate_public_url("http://169.254.169.254/latest/meta-data/") is not None


def test_validate_public_url_allows_public_https():
    toolkit = _make_toolkit()
    assert toolkit._validate_public_url("https://example.com/article") is None


@patch("ibkr_core_mcp.scrape_fallback.Crawl4AIScraper")
@patch("ibkr_core_mcp.scrape_fallback.judge_completeness_llm")
def test_scrape_with_fallback_judge_failure_keeps_original_content(mock_judge, mock_cls):
    """A transient Anthropic API failure during the completeness judgment must fail
    safe (keep Firecrawl's original content) rather than silently escalating to the
    slower, heavier Crawl4AI path on a result that might have been genuinely fine."""
    toolkit = _make_toolkit()
    mock_judge.side_effect = RuntimeError("anthropic API unavailable")
    markdown = _long_markdown(100)  # borderline band → ambiguous

    result, note = toolkit._scrape_with_fallback(
        "https://example.com/article", markdown, None
    )
    assert result == markdown
    assert "completeness check failed" in note.lower()
    mock_cls.return_value.scrape.assert_not_called()


@patch("ibkr_core_mcp.scrape_fallback.Crawl4AIScraper")
def test_scrape_with_fallback_never_calls_crawl4ai_for_blocked_url(mock_cls):
    """SSRF regression guard: a URL that resolves to a private/link-local address
    must never reach Crawl4AIScraper.scrape, regardless of how it entered
    _scrape_with_fallback (crawl sub-page, search result, etc.)."""
    toolkit = _make_toolkit()
    result, note = toolkit._scrape_with_fallback(
        "http://169.254.169.254/latest/meta-data/", "", None
    )
    mock_cls.return_value.scrape.assert_not_called()
    assert "Blocked" in note


@patch("ibkr_core_mcp.web_scraper.FirecrawlClient")
@patch("ibkr_core_mcp.scrape_fallback.Crawl4AIScraper")
def test_firecrawl_search_never_fetches_blocked_result_url_via_crawl4ai(
    mock_c4a_cls, mock_fc_cls
):
    """A search result pointing at a private/internal address (e.g. a manipulated
    or attacker-influenced search result) must not trigger a local Crawl4AI fetch
    just because Firecrawl's own markdown for it looks incomplete."""
    toolkit = _make_toolkit()
    mock_fc = MagicMock()
    mock_fc.search.return_value = [
        {
            "url": "http://169.254.169.254/latest/meta-data/",
            "title": "Suspicious result",
            "markdown": "",
            "metadata": {},
        }
    ]
    mock_fc_cls.return_value = mock_fc

    result, fig = toolkit.execute("firecrawl_search", {"query": "test"})
    mock_c4a_cls.return_value.scrape.assert_not_called()


@patch("ibkr_core_mcp.web_scraper.FirecrawlClient")
@patch("ibkr_core_mcp.web_scraper.WebDocsStore")
@patch("ibkr_core_mcp.scrape_fallback.Crawl4AIScraper")
def test_firecrawl_crawl_never_fetches_blocked_subpage_url_via_crawl4ai(
    mock_c4a_cls, mock_wds_cls, mock_fc_cls
):
    """A crawled sub-page URL that resolves to a private address (e.g. Firecrawl
    followed a redirect/internal link off the validated root) must not reach
    Crawl4AIScraper.scrape even though the top-level crawl root passed the guard."""
    toolkit = _make_toolkit()
    mock_fc = MagicMock()
    mock_fc.crawl.return_value = [
        {"url": "http://127.0.0.1:8080/internal", "markdown": "", "metadata": {"statusCode": 403}}
    ]
    mock_fc_cls.return_value = mock_fc
    mock_wds = MagicMock()
    mock_wds.save_crawl.return_value = {
        "url": "https://example.com",
        "crawled_at": "2026-01-01T00:00:00+00:00",
        "pages": [{"url": "http://127.0.0.1:8080/internal", "file_id": "fid"}],
    }
    mock_wds_cls.return_value = mock_wds

    toolkit.execute("firecrawl_crawl", {"url": "https://example.com"})
    mock_c4a_cls.return_value.scrape.assert_not_called()


@patch("ibkr_core_mcp.web_scraper.FirecrawlClient")
@patch("ibkr_core_mcp.web_scraper.WebDocsStore")
@patch("ibkr_core_mcp.scrape_fallback.Crawl4AIScraper")
def test_firecrawl_crawl_applies_fallback_per_page(mock_c4a_cls, mock_wds_cls, mock_fc_cls):
    toolkit = _make_toolkit()
    mock_fc = MagicMock()
    mock_fc.crawl.return_value = [
        {"url": "https://example.com/blocked", "markdown": "", "metadata": {"statusCode": 403}}
    ]
    mock_fc_cls.return_value = mock_fc
    mock_c4a_cls.return_value.scrape.return_value = {
        "url": "https://example.com/blocked",
        "markdown": "recovered page content",
    }
    mock_wds = MagicMock()
    mock_wds.save_crawl.return_value = {
        "url": "https://example.com",
        "crawled_at": "2026-01-01T00:00:00+00:00",
        "pages": [{"url": "https://example.com/blocked", "file_id": "fid"}],
    }
    mock_wds_cls.return_value = mock_wds

    result, fig = toolkit.execute("firecrawl_crawl", {"url": "https://example.com"})
    assert fig is None
    # The recovered content (not the empty Firecrawl stub) must be what gets saved to Drive.
    saved_pages = mock_wds.save_crawl.call_args[0][1]
    assert saved_pages[0]["markdown"] == "recovered page content"


# ============================================================================
# _diagnose_orders
# ============================================================================


