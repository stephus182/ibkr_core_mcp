from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.web_scraping

_REALISTIC_PARAGRAPH = (
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

# Repeated to ~7 KB so it clears web_scraper._MIN_USEFUL_BYTES, matching the size of a
# real documentation page (12.9-91.9 KB in docs/audits/audit-evidence/scrapes/).
_REALISTIC_MARKDOWN = _REALISTIC_PARAGRAPH * 4

# ============================================================================
# Firecrawl handler tests
# ============================================================================


def _make_toolkit(crawl4ai_api_key=""):
    """Return a ClaudeToolkit with all dependencies mocked.

    crawl4ai_api_key defaults to "" — the cloud rung unconfigured — so every test
    written before that rung existed still exercises the two-rung ladder unchanged.
    """
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
        crawl4ai_api_key=crawl4ai_api_key,
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
    mock_fc.search.return_value = [{"url": "https://example.com", "title": "Example", "markdown": _REALISTIC_MARKDOWN}]
    mock_fc_cls.return_value = mock_fc

    result, fig = toolkit.execute("firecrawl_search", {"query": "IBKR API", "limit": 3})
    assert "## Search results for: IBKR API" in result
    assert fig is None
    # Overrides default to None, which _scrape_options omits — so the request body
    # Firecrawl actually receives is unchanged from before they existed.
    mock_fc.search.assert_called_once_with("IBKR API", limit=3, wait_for_ms=None, proxy=None)


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
    mock_fc.crawl.return_value = [{"url": "https://example.com/page", "markdown": _REALISTIC_MARKDOWN}]
    mock_fc_cls.return_value = mock_fc
    mock_wds = MagicMock()
    mock_wds.get_cached_crawl.return_value = None  # force cache-miss -> fetch-fresh path
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


@patch("ibkr_core_mcp.web_scraper.FirecrawlClient")
@patch("ibkr_core_mcp.web_scraper.WebDocsStore")
def test_firecrawl_crawl_uses_cached_manifest_and_skips_firecrawl(mock_wds_cls, mock_fc_cls):
    """A fresh Drive manifest must short-circuit the whole call — zero Firecrawl
    requests — this is the fix for repeated runs (e.g. re-verifying a fixed list
    of doc URLs) cascading into Firecrawl's own rate limit."""
    toolkit = _make_toolkit()
    mock_fc = MagicMock()
    mock_fc_cls.return_value = mock_fc
    mock_wds = MagicMock()
    mock_wds.get_cached_crawl.return_value = {
        "url": "https://example.com",
        "crawled_at": "2026-07-14T00:00:00+00:00",
        "pages": [{"url": "https://example.com/page", "file_id": "fid"}],
    }
    mock_wds_cls.return_value = mock_wds

    result, fig = toolkit.execute("firecrawl_crawl", {"url": "https://example.com"})

    assert fig is None
    assert "cached" in result.lower()
    mock_fc.crawl.assert_not_called()
    mock_wds.save_crawl.assert_not_called()


@patch("ibkr_core_mcp.web_scraper.FirecrawlClient")
@patch("ibkr_core_mcp.web_scraper.WebDocsStore")
def test_firecrawl_crawl_force_refresh_bypasses_cache(mock_wds_cls, mock_fc_cls):
    toolkit = _make_toolkit()
    mock_fc = MagicMock()
    mock_fc.crawl.return_value = [{"url": "https://example.com/page", "markdown": _REALISTIC_MARKDOWN}]
    mock_fc_cls.return_value = mock_fc
    mock_wds = MagicMock()
    mock_wds.get_cached_crawl.return_value = {
        "url": "https://example.com",
        "crawled_at": "2026-07-14T00:00:00+00:00",
        "pages": [{"url": "https://example.com/page", "file_id": "fid"}],
    }
    mock_wds.save_crawl.return_value = {
        "url": "https://example.com",
        "crawled_at": "2026-07-14T01:00:00+00:00",
        "pages": [{"url": "https://example.com/page", "file_id": "fid2"}],
    }
    mock_wds_cls.return_value = mock_wds

    result, fig = toolkit.execute("firecrawl_crawl", {"url": "https://example.com", "force_refresh": True})

    assert fig is None
    mock_fc.crawl.assert_called_once()
    mock_wds.save_crawl.assert_called_once()


def test_crawl_falls_back_to_crawl4ai_root_when_firecrawl_returns_nothing():
    from ibkr_core_mcp.claude_tools import ClaudeToolkit  # noqa: F401

    toolkit = _make_toolkit()
    toolkit._firecrawl = MagicMock()
    toolkit._firecrawl.crawl.return_value = []
    toolkit._web_docs = MagicMock()
    toolkit._web_docs.get_cached_crawl.return_value = None
    toolkit._web_docs.save_crawl.return_value = {
        "url": "https://www.interactivebrokers.com/docs/",
        "crawled_at": "2026-07-25T00:00:00+00:00",
        "pages": [{"url": "https://www.interactivebrokers.com/docs/", "file_id": "f1"}],
    }
    toolkit._crawl4ai = MagicMock()
    toolkit._crawl4ai.scrape.return_value = {
        "url": "https://www.interactivebrokers.com/docs/",
        "markdown": _REALISTIC_MARKDOWN,
    }

    text, _payload = toolkit.execute("firecrawl_crawl", {"url": "https://www.interactivebrokers.com/docs/"})

    toolkit._crawl4ai.scrape.assert_called_once_with("https://www.interactivebrokers.com/docs/")
    saved_pages = toolkit._web_docs.save_crawl.call_args[0][1]
    assert saved_pages[0]["markdown"] == _REALISTIC_MARKDOWN
    assert "Crawl4AI" in text


def test_crawl_does_not_root_scrape_when_firecrawl_returned_content():
    toolkit = _make_toolkit()
    toolkit._firecrawl = MagicMock()
    toolkit._firecrawl.crawl.return_value = [
        {"url": "https://example.com/a", "markdown": _REALISTIC_MARKDOWN, "metadata": {}}
    ]
    toolkit._web_docs = MagicMock()
    toolkit._web_docs.get_cached_crawl.return_value = None
    toolkit._web_docs.save_crawl.return_value = {
        "url": "https://example.com",
        "crawled_at": "2026-07-25T00:00:00+00:00",
        "pages": [{"url": "https://example.com/a", "file_id": "f1"}],
    }
    toolkit._crawl4ai = MagicMock()

    toolkit.execute("firecrawl_crawl", {"url": "https://example.com"})

    toolkit._crawl4ai.scrape.assert_not_called()


def test_crawl_never_reports_zero_pages_as_success():
    toolkit = _make_toolkit()
    toolkit._firecrawl = MagicMock()
    toolkit._firecrawl.crawl.return_value = []
    toolkit._web_docs = MagicMock()
    toolkit._web_docs.get_cached_crawl.return_value = None
    toolkit._crawl4ai = MagicMock()
    toolkit._crawl4ai.scrape.return_value = {"url": "https://example.com", "markdown": ""}

    text, _payload = toolkit.execute("firecrawl_crawl", {"url": "https://example.com"})

    assert "saved 0 page(s)" not in text
    assert "no content" in text.lower()
    toolkit._web_docs.save_crawl.assert_not_called()


def test_crawl_degrades_when_crawl4ai_is_not_installed():
    from ibkr_core_mcp.scrape_fallback import Crawl4AIUnavailableError

    toolkit = _make_toolkit()
    toolkit._firecrawl = MagicMock()
    toolkit._firecrawl.crawl.return_value = []
    toolkit._web_docs = MagicMock()
    toolkit._web_docs.get_cached_crawl.return_value = None
    toolkit._crawl4ai = MagicMock()
    toolkit._crawl4ai.scrape.side_effect = Crawl4AIUnavailableError("not installed")

    text, _payload = toolkit.execute("firecrawl_crawl", {"url": "https://example.com"})

    assert "no content" in text.lower()


def test_crawl_reports_network_failure_instead_of_raising():
    import requests

    toolkit = _make_toolkit()
    toolkit._firecrawl = MagicMock()
    toolkit._firecrawl.crawl.side_effect = requests.ConnectionError("dns failure")
    toolkit._web_docs = MagicMock()
    toolkit._web_docs.get_cached_crawl.return_value = None

    text, _payload = toolkit.execute("firecrawl_crawl", {"url": "https://example.com"})

    assert "network" in text.lower()


# ============================================================================
# Crawl4AI fallback wiring (_scrape_with_fallback + handler integration)
# ============================================================================


def _long_markdown(word_count: int) -> str:
    return " ".join(["word"] * word_count)


def test_scrape_with_fallback_returns_original_when_quality_ok():
    toolkit = _make_toolkit()
    markdown = _long_markdown(500)
    result, note, used_fallback = toolkit._scrape_with_fallback(
        "https://example.com/article", markdown, {"statusCode": 200}
    )
    assert result == markdown
    assert note == ""
    assert used_fallback is False


@patch("ibkr_core_mcp.scrape_fallback.Crawl4AIScraper")
def test_scrape_with_fallback_uses_crawl4ai_when_quality_is_fallback(mock_cls):
    toolkit = _make_toolkit()
    mock_scraper = MagicMock()
    mock_scraper.scrape.return_value = {
        "url": "https://example.com/article",
        "markdown": "the full recovered article text",
    }
    mock_cls.return_value = mock_scraper

    result, note, used_fallback = toolkit._scrape_with_fallback("https://example.com/article", "", None)
    assert result == "the full recovered article text"
    assert "Crawl4AI" in note
    assert used_fallback is True
    mock_scraper.scrape.assert_called_once_with("https://example.com/article")


@patch("ibkr_core_mcp.scrape_fallback.Crawl4AIScraper")
@patch("ibkr_core_mcp.scrape_fallback.judge_completeness_llm")
def test_scrape_with_fallback_ambiguous_and_llm_says_complete_keeps_original(mock_judge, mock_cls):
    toolkit = _make_toolkit()
    mock_judge.return_value = True
    markdown = _long_markdown(100)  # borderline band → ambiguous

    result, note, used_fallback = toolkit._scrape_with_fallback("https://example.com/article", markdown, None)
    assert result == markdown
    assert note == ""
    assert used_fallback is False
    mock_cls.return_value.scrape.assert_not_called()


@patch("ibkr_core_mcp.scrape_fallback.Crawl4AIScraper")
@patch("ibkr_core_mcp.scrape_fallback.judge_completeness_llm")
def test_scrape_with_fallback_ambiguous_and_llm_says_incomplete_falls_back(mock_judge, mock_cls):
    toolkit = _make_toolkit()
    mock_judge.return_value = False
    mock_scraper = MagicMock()
    mock_scraper.scrape.return_value = {
        "url": "https://example.com/article",
        "markdown": "recovered full content",
    }
    mock_cls.return_value = mock_scraper
    markdown = _long_markdown(100)

    result, note, used_fallback = toolkit._scrape_with_fallback("https://example.com/article", markdown, None)
    assert result == "recovered full content"
    assert "Crawl4AI" in note
    assert used_fallback is True


@patch("ibkr_core_mcp.scrape_fallback.Crawl4AIScraper")
def test_scrape_with_fallback_crawl4ai_unavailable_returns_original_with_note(mock_cls):
    from ibkr_core_mcp.scrape_fallback import Crawl4AIUnavailableError

    toolkit = _make_toolkit()
    mock_cls.return_value.scrape.side_effect = Crawl4AIUnavailableError(
        "Crawl4AI is not installed. Install with `pip install ibkr_core_mcp[scraper]`."
    )

    result, note, used_fallback = toolkit._scrape_with_fallback("https://example.com/article", "", None)
    assert result == ""
    assert "ibkr_core_mcp[scraper]" in note
    assert used_fallback is False


@patch("ibkr_core_mcp.scrape_fallback.Crawl4AIScraper")
def test_scrape_with_fallback_notes_missing_login_profile(mock_cls, tmp_path):
    toolkit = _make_toolkit()
    toolkit._config.crawl4ai_profiles_dir = tmp_path  # no example.com/ subfolder
    mock_cls.return_value.scrape.return_value = {
        "url": "https://example.com/article",
        "markdown": "partial anonymous content",
    }

    _, note, used_fallback = toolkit._scrape_with_fallback("https://example.com/article", "", None)
    assert "no saved login profile" in note
    assert "create-profile" in note
    assert used_fallback is True


@patch("ibkr_core_mcp.scrape_fallback.Crawl4AIScraper")
def test_scrape_with_fallback_notes_saved_login_profile_used(mock_cls, tmp_path):
    toolkit = _make_toolkit()
    (tmp_path / "example.com").mkdir()
    toolkit._config.crawl4ai_profiles_dir = tmp_path
    mock_cls.return_value.scrape.return_value = {
        "url": "https://example.com/article",
        "markdown": "full subscriber content",
    }

    _, note, used_fallback = toolkit._scrape_with_fallback("https://example.com/article", "", None)
    assert "saved login profile" in note
    assert "no saved login profile" not in note
    assert used_fallback is True


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

    result, note, used_fallback = toolkit._scrape_with_fallback("https://example.com/article", markdown, None)
    assert result == markdown
    assert "completeness check failed" in note.lower()
    assert used_fallback is False
    mock_cls.return_value.scrape.assert_not_called()


@patch("ibkr_core_mcp.scrape_fallback.Crawl4AIScraper")
def test_scrape_with_fallback_never_calls_crawl4ai_for_blocked_url(mock_cls):
    """SSRF regression guard: a URL that resolves to a private/link-local address
    must never reach Crawl4AIScraper.scrape, regardless of how it entered
    _scrape_with_fallback (crawl sub-page, search result, etc.)."""
    toolkit = _make_toolkit()
    result, note, used_fallback = toolkit._scrape_with_fallback("http://169.254.169.254/latest/meta-data/", "", None)
    mock_cls.return_value.scrape.assert_not_called()
    assert "Blocked" in note
    assert used_fallback is False


@patch("ibkr_core_mcp.web_scraper.FirecrawlClient")
@patch("ibkr_core_mcp.scrape_fallback.Crawl4AIScraper")
def test_firecrawl_search_never_fetches_blocked_result_url_via_crawl4ai(mock_c4a_cls, mock_fc_cls):
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
def test_firecrawl_crawl_never_fetches_blocked_subpage_url_via_crawl4ai(mock_c4a_cls, mock_wds_cls, mock_fc_cls):
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
    mock_wds.get_cached_crawl.return_value = None  # force cache-miss -> fetch-fresh path
    mock_wds.save_crawl.return_value = {
        "url": "https://example.com",
        "crawled_at": "2026-01-01T00:00:00+00:00",
        "pages": [{"url": "http://127.0.0.1:8080/internal", "file_id": "fid"}],
    }
    mock_wds_cls.return_value = mock_wds

    toolkit.execute("firecrawl_crawl", {"url": "https://example.com"})
    mock_c4a_cls.return_value.scrape_batch.assert_not_called()


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
    mock_c4a_cls.return_value.scrape_batch.return_value = {
        "https://example.com/blocked": {
            "url": "https://example.com/blocked",
            "markdown": "recovered page content",
        },
    }
    mock_wds = MagicMock()
    mock_wds.get_cached_crawl.return_value = None  # force cache-miss -> fetch-fresh path
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
    assert "Crawl4AI fallback used for 1 page(s)" in result


@patch("ibkr_core_mcp.web_scraper.FirecrawlClient")
@patch("ibkr_core_mcp.web_scraper.WebDocsStore")
@patch("ibkr_core_mcp.scrape_fallback.Crawl4AIScraper")
def test_firecrawl_crawl_does_not_claim_fallback_used_when_unavailable(mock_c4a_cls, mock_wds_cls, mock_fc_cls):
    """A page whose fallback attempt fails/is skipped/is unavailable must not be
    counted in the 'Crawl4AI fallback used for N page(s)' summary — that count
    must reflect only pages where Crawl4AI actually replaced the content."""
    from ibkr_core_mcp.scrape_fallback import Crawl4AIUnavailableError

    toolkit = _make_toolkit()
    mock_fc = MagicMock()
    mock_fc.crawl.return_value = [
        {"url": "https://example.com/blocked", "markdown": "", "metadata": {"statusCode": 403}}
    ]
    mock_fc_cls.return_value = mock_fc
    mock_c4a_cls.return_value.scrape_batch.side_effect = Crawl4AIUnavailableError(
        "Crawl4AI is not installed. Install with `pip install ibkr_core_mcp[scraper]`."
    )
    mock_wds = MagicMock()
    mock_wds.get_cached_crawl.return_value = None  # force cache-miss -> fetch-fresh path
    mock_wds.save_crawl.return_value = {
        "url": "https://example.com",
        "crawled_at": "2026-01-01T00:00:00+00:00",
        "pages": [],
    }
    mock_wds_cls.return_value = mock_wds

    result, fig = toolkit.execute("firecrawl_crawl", {"url": "https://example.com"})
    assert fig is None
    assert "Crawl4AI fallback used" not in result


@patch("ibkr_core_mcp.web_scraper.FirecrawlClient")
@patch("ibkr_core_mcp.web_scraper.WebDocsStore")
@patch("ibkr_core_mcp.scrape_fallback.Crawl4AIScraper")
def test_firecrawl_crawl_batch_maps_outcomes_to_correct_pages(mock_c4a_cls, mock_wds_cls, mock_fc_cls):
    """A crawl with a mix of clean and fallback-needing pages must batch only the
    fallback-needing URLs into scrape_batch, and must re-attach each candidate's own
    outcome to its own page -- proving there's no cross-contamination between pages
    when the batch loop pairs candidates back up with their outcomes."""
    toolkit = _make_toolkit()
    mock_fc = MagicMock()
    mock_fc.crawl.return_value = [
        {"url": "https://example.com/clean", "markdown": _REALISTIC_MARKDOWN, "metadata": {"statusCode": 200}},
        {"url": "https://example.com/blocked-a", "markdown": "", "metadata": {"statusCode": 403}},
        {"url": "https://example.com/blocked-b", "markdown": "", "metadata": {"statusCode": 500}},
    ]
    mock_fc_cls.return_value = mock_fc
    mock_c4a_cls.return_value.scrape_batch.return_value = {
        "https://example.com/blocked-a": {
            "url": "https://example.com/blocked-a",
            "markdown": "recovered content for page A",
        },
        "https://example.com/blocked-b": RuntimeError("network error fetching page B"),
    }
    mock_wds = MagicMock()
    mock_wds.get_cached_crawl.return_value = None  # force cache-miss -> fetch-fresh path
    mock_wds.save_crawl.return_value = {
        "url": "https://example.com",
        "crawled_at": "2026-01-01T00:00:00+00:00",
        "pages": [
            {"url": "https://example.com/clean", "file_id": "fid1"},
            {"url": "https://example.com/blocked-a", "file_id": "fid2"},
            {"url": "https://example.com/blocked-b", "file_id": "fid3"},
        ],
    }
    mock_wds_cls.return_value = mock_wds

    result, fig = toolkit.execute("firecrawl_crawl", {"url": "https://example.com"})
    assert fig is None

    # The clean page never needed a fallback fetch at all -- only the two
    # fallback-needing URLs reach scrape_batch, in page order.
    mock_c4a_cls.return_value.scrape_batch.assert_called_once_with(
        ["https://example.com/blocked-a", "https://example.com/blocked-b"],
        profile_domain="example.com",
    )

    saved_pages = {p["url"]: p["markdown"] for p in mock_wds.save_crawl.call_args[0][1]}
    assert saved_pages["https://example.com/clean"] == _REALISTIC_MARKDOWN
    assert saved_pages["https://example.com/blocked-a"] == "recovered content for page A"
    # Page B's own fallback attempt failed -- it must fall back to its own (empty)
    # original markdown, never page A's recovered content or vice versa.
    assert saved_pages["https://example.com/blocked-b"] == ""

    # Only page A's outcome actually replaced Firecrawl's content.
    assert "Crawl4AI fallback used for 1 page(s)" in result


@patch("ibkr_core_mcp.web_scraper.FirecrawlClient")
def test_firecrawl_search_preserves_result_order_under_concurrent_fallback(mock_fc_cls):
    """Concurrent fallback execution (ThreadPoolExecutor.map) must not reorder
    results in the final output, even when different results' fallback
    fetches take different amounts of time -- the first result is given the
    LONGEST artificial delay specifically to prove ordering survives even
    when completion order differs from input order."""
    import time

    toolkit = _make_toolkit()
    mock_fc = MagicMock()
    mock_fc.search.return_value = [
        {"url": "https://a.example.com", "title": "A", "markdown": "", "metadata": {"statusCode": 403}},
        {"url": "https://b.example.com", "title": "B", "markdown": "", "metadata": {"statusCode": 403}},
        {"url": "https://c.example.com", "title": "C", "markdown": "", "metadata": {"statusCode": 403}},
    ]
    mock_fc_cls.return_value = mock_fc

    delays = {"https://a.example.com": 0.15, "https://b.example.com": 0.05, "https://c.example.com": 0.0}

    def fake_scrape_with_fallback(url, markdown, metadata):
        time.sleep(delays[url])
        label = url.split("//")[1].split(".")[0].upper()
        return f"recovered {label} content", "", True

    toolkit._scrape_with_fallback = fake_scrape_with_fallback
    result, fig = toolkit.execute("firecrawl_search", {"query": "test"})

    a_pos = result.index("recovered A content")
    b_pos = result.index("recovered B content")
    c_pos = result.index("recovered C content")
    assert a_pos < b_pos < c_pos


# ============================================================================
# _diagnose_orders
# ============================================================================


def test_firecrawl_search_forwards_wait_for_and_proxy_to_the_client():
    toolkit = _make_toolkit()
    toolkit._firecrawl = MagicMock()
    toolkit._firecrawl.search.return_value = []

    toolkit.execute(
        "firecrawl_search",
        {"query": "ibkr api", "wait_for_ms": 3000, "proxy": "auto"},
    )

    kwargs = toolkit._firecrawl.search.call_args[1]
    assert kwargs["wait_for_ms"] == 3000
    assert kwargs["proxy"] == "auto"


def _blocked_firecrawl_toolkit(exc):
    """Toolkit whose Firecrawl crawl raises `exc`, with Crawl4AI ready to rescue it."""
    toolkit = _make_toolkit()
    toolkit._firecrawl = MagicMock()
    toolkit._firecrawl.crawl.side_effect = exc
    toolkit._web_docs = MagicMock()
    toolkit._web_docs.get_cached_crawl.return_value = None
    toolkit._web_docs.save_crawl.return_value = {
        "url": "https://example.com",
        "crawled_at": "2026-07-26T00:00:00+00:00",
        "pages": [{"url": "https://example.com", "file_id": "f1"}],
    }
    toolkit._crawl4ai = MagicMock()
    toolkit._crawl4ai.scrape.return_value = {"url": "https://example.com", "markdown": _REALISTIC_MARKDOWN}
    return toolkit


def test_crawl_falls_back_to_crawl4ai_when_firecrawl_is_rate_limited():
    from ibkr_core_mcp.web_scraper import FirecrawlError

    # 429 is exactly when the free local scraper matters most: Firecrawl's Free tier
    # allows 2 /crawl per minute, so a rate limit means no more paid attempts this minute.
    toolkit = _blocked_firecrawl_toolkit(FirecrawlError("Rate limit exceeded", 429))

    text, _payload = toolkit.execute("firecrawl_crawl", {"url": "https://example.com"})

    toolkit._crawl4ai.scrape.assert_called_once_with("https://example.com")
    assert "Crawl4AI" in text
    assert "Crawl complete" in text


def test_crawl_falls_back_to_crawl4ai_when_out_of_credits():
    from ibkr_core_mcp.web_scraper import FirecrawlError

    toolkit = _blocked_firecrawl_toolkit(FirecrawlError("out of credits", 402))

    text, _payload = toolkit.execute("firecrawl_crawl", {"url": "https://example.com"})

    toolkit._crawl4ai.scrape.assert_called_once_with("https://example.com")
    assert "Crawl complete" in text


def test_crawl_falls_back_to_crawl4ai_on_network_error():
    import requests

    toolkit = _blocked_firecrawl_toolkit(requests.ConnectionError("dns failure"))

    text, _payload = toolkit.execute("firecrawl_crawl", {"url": "https://example.com"})

    toolkit._crawl4ai.scrape.assert_called_once_with("https://example.com")
    assert "Crawl complete" in text


def test_crawl_no_content_message_names_the_firecrawl_failure():
    from ibkr_core_mcp.web_scraper import FirecrawlError

    toolkit = _blocked_firecrawl_toolkit(FirecrawlError("Rate limit exceeded", 429))
    toolkit._crawl4ai.scrape.return_value = {"url": "https://example.com", "markdown": ""}

    text, _payload = toolkit.execute("firecrawl_crawl", {"url": "https://example.com"})

    # When everything fails, the message must still say why Firecrawl produced nothing —
    # "no content" alone would hide an expired key or an empty credit balance.
    assert "no content" in text.lower()
    assert "429" in text
    toolkit._web_docs.save_crawl.assert_not_called()


# ============================================================================
# Recovery ladder rung 3 — Crawl4AI Cloud
#
# Order is Firecrawl -> LOCAL Crawl4AI -> Crawl4AI CLOUD, deliberately. The cloud
# rung costs credits and the local one is free, and on the only real failure
# observed to date (2026-07-28, the IBKR campus reference) local was the rung that
# worked. A paid rung ahead of it would have spent credits to be overtaken by
# something free.
#
# Every test here reaches _handle_firecrawl_crawl, which SSRF-validates the root
# URL before any rung runs — so each one is named in conftest's
# _REAL_DNS_EXEMPT_TESTS. Without that, a blocked DNS lookup short-circuits the
# whole tool into "Invalid URL: ..." and the assertions below pass or fail for
# reasons that have nothing to do with the ladder.
# ============================================================================

_CLOUD_MARKDOWN = _REALISTIC_PARAGRAPH * 5  # distinguishable from _REALISTIC_MARKDOWN


def _ladder_toolkit(cloud_key="sk_live_test"):
    """Toolkit whose Firecrawl and local rungs are wired to return nothing."""
    toolkit = _make_toolkit(crawl4ai_api_key=cloud_key)
    toolkit._firecrawl = MagicMock()
    toolkit._firecrawl.crawl.return_value = []
    toolkit._web_docs = MagicMock()
    toolkit._web_docs.get_cached_crawl.return_value = None
    toolkit._web_docs.save_crawl.return_value = {
        "url": "https://example.com",
        "crawled_at": "2026-07-28T00:00:00+00:00",
        "pages": [{"url": "https://example.com", "file_id": "f1"}],
    }
    toolkit._crawl4ai = MagicMock()
    toolkit._crawl4ai.scrape.return_value = {"url": "https://example.com", "markdown": ""}
    return toolkit


def test_crawl_falls_back_to_cloud_when_firecrawl_and_local_both_fail():
    toolkit = _ladder_toolkit()
    toolkit._crawl4ai_cloud = MagicMock()
    toolkit._crawl4ai_cloud.scrape.return_value = {
        "url": "https://example.com",
        "markdown": _CLOUD_MARKDOWN,
        "metadata": {},
    }

    text, _payload = toolkit.execute("firecrawl_crawl", {"url": "https://example.com"})

    toolkit._crawl4ai_cloud.scrape.assert_called_once_with("https://example.com")
    saved_pages = toolkit._web_docs.save_crawl.call_args[0][1]
    assert saved_pages[0]["markdown"] == _CLOUD_MARKDOWN
    assert "Crawl4AI Cloud" in text


def test_crawl_does_not_reach_cloud_when_the_free_local_rung_rescued_it():
    """The paid rung must never run on a page the free one already served."""
    toolkit = _ladder_toolkit()
    toolkit._crawl4ai.scrape.return_value = {"url": "https://example.com", "markdown": _REALISTIC_MARKDOWN}
    toolkit._crawl4ai_cloud = MagicMock()

    text, _payload = toolkit.execute("firecrawl_crawl", {"url": "https://example.com"})

    toolkit._crawl4ai_cloud.scrape.assert_not_called()
    assert "Crawl4AI Cloud" not in text


def test_crawl_skips_the_cloud_rung_silently_when_no_key_is_configured():
    """With no key the ladder must behave exactly as it did before this rung existed."""
    toolkit = _ladder_toolkit(cloud_key="")
    toolkit._crawl4ai_cloud = MagicMock()

    text, _payload = toolkit.execute("firecrawl_crawl", {"url": "https://example.com"})

    toolkit._crawl4ai_cloud.scrape.assert_not_called()
    assert "Crawl4AI Cloud" not in text
    assert "not configured" not in text.lower()
    assert "no content" in text.lower()


def test_crawl_no_content_message_names_every_rung_that_failed():
    toolkit = _ladder_toolkit()
    toolkit._crawl4ai_cloud = MagicMock()
    toolkit._crawl4ai_cloud.scrape.return_value = {"url": "https://example.com", "markdown": ""}

    text, _payload = toolkit.execute("firecrawl_crawl", {"url": "https://example.com"})

    assert "saved 0 page(s)" not in text
    lowered = text.lower()
    assert "firecrawl" in lowered
    assert "local crawl4ai" in lowered
    assert "cloud" in lowered


def test_crawl_names_the_cloud_failure_rather_than_swallowing_it():
    from ibkr_core_mcp.crawl4ai_cloud import Crawl4AICloudError

    toolkit = _ladder_toolkit()
    toolkit._crawl4ai_cloud = MagicMock()
    toolkit._crawl4ai_cloud.scrape.side_effect = Crawl4AICloudError(
        "Crawl4AI rate or daily quota limit exceeded (HTTP 429)", 429
    )

    text, _payload = toolkit.execute("firecrawl_crawl", {"url": "https://example.com"})

    assert "429" in text


def test_crawl_reports_remaining_credits_only_when_the_cloud_rung_fired():
    toolkit = _ladder_toolkit()
    toolkit._crawl4ai_cloud = MagicMock()
    toolkit._crawl4ai_cloud.scrape.return_value = {
        "url": "https://example.com",
        "markdown": _CLOUD_MARKDOWN,
        "metadata": {},
    }
    toolkit._crawl4ai_cloud.last_credits_remaining = 46.0

    text, _payload = toolkit.execute("firecrawl_crawl", {"url": "https://example.com"})

    assert "46" in text and "credit" in text.lower()


def test_crawl_does_not_mention_credits_when_firecrawl_served_the_page():
    toolkit = _ladder_toolkit()
    toolkit._firecrawl.crawl.return_value = [
        {"url": "https://example.com/a", "markdown": _REALISTIC_MARKDOWN, "metadata": {}}
    ]
    toolkit._crawl4ai_cloud = MagicMock()
    toolkit._crawl4ai_cloud.last_credits_remaining = 46.0

    text, _payload = toolkit.execute("firecrawl_crawl", {"url": "https://example.com"})

    assert "credit" not in text.lower()
