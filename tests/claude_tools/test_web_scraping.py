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


def _make_toolkit():
    """Return a ClaudeToolkit with all dependencies mocked.

    `crawl4ai_profiles_dir` is pinned to a path that cannot exist. Config's default
    is the developer's real `~/.ibkr_core/crawl4ai_profiles`, so without this every
    profile-dependent assertion in this file would silently depend on whether the
    machine running the suite happens to have a saved login for the domain under
    test — and would start behaving differently the day someone creates one. Tests
    that need a profile to be found override this with `tmp_path`.
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
        crawl4ai_profiles_dir=Path("/nonexistent/crawl4ai-profiles-for-tests"),
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


# ============================================================================
# Crawl4AI fallback wiring (_scrape_with_fallback + handler integration)
# ============================================================================


def _long_markdown(word_count: int) -> str:
    return " ".join(["word"] * word_count)


def test_validate_public_url_blocks_localhost():
    toolkit = _make_toolkit()
    assert toolkit._validate_public_url("http://localhost:5055/api") is not None


def test_validate_public_url_blocks_link_local():
    toolkit = _make_toolkit()
    assert toolkit._validate_public_url("http://169.254.169.254/latest/meta-data/") is not None


def test_validate_public_url_allows_public_https():
    toolkit = _make_toolkit()
    assert toolkit._validate_public_url("https://example.com/article") is None


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


# ============================================================================
# Recovery ladder — the "never downgrade" invariant
#
# The ladder is Firecrawl -> local Crawl4AI, and it upgrades only on strictly
# more content. A third, paid rung (Crawl4AI Cloud) sat below these two between
# 2026-07-28 and its removal the same day: it bought nothing the local browser
# did not already do, and on the only real block ever observed (2026-07-02,
# IBKR/Akamai) the free local rung was the one that won.
#
# Both tests below reach _handle_firecrawl_crawl, which SSRF-validates the root
# URL before any rung runs — so each is named in conftest's _REAL_DNS_EXEMPT_TESTS.
# Without that, a blocked DNS lookup short-circuits the whole tool into
# "Invalid URL: ..." and the assertions pass or fail for reasons that have
# nothing to do with the ladder.
# ============================================================================

# ~3.5 KB — real prose (over assess_quality's 200-word confidence bar, so no per-page
# fallback fires) but under web_scraper._MIN_USEFUL_BYTES, so the root rescue still runs.
_SUB_THRESHOLD_MARKDOWN = _REALISTIC_PARAGRAPH * 2


def _ladder_toolkit():
    """Toolkit whose Firecrawl and local rungs are both wired to return nothing."""
    toolkit = _make_toolkit()
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


# ============================================================================
# fetch_page — the browser door
#
# The ladder above reaches Crawl4AI only underneath a Firecrawl call. That is the
# right shape for archiving a site, and the wrong one for reading a single
# paywalled article: Firecrawl cannot log in, so trying it first only spends a
# credit to be handed a subscription stub. fetch_page goes straight to the local
# browser for one URL.
#
# Every test here reaches _handle_fetch_page, which SSRF-validates the URL before
# constructing anything — so each is named in conftest's _REAL_DNS_EXEMPT_TESTS,
# except the one that *wants* the URL rejected.
# ============================================================================


def _fetch_toolkit(tmp_path=None):
    """Toolkit with the browser mocked. Pass `tmp_path` to control profile lookup;
    without it `_make_toolkit`'s nonexistent-path default means no profile is found.
    """
    toolkit = _make_toolkit()
    if tmp_path is not None:
        toolkit._config.crawl4ai_profiles_dir = tmp_path
    toolkit._crawl4ai = MagicMock()
    toolkit._crawl4ai.scrape.return_value = {
        "url": "https://example.com/article",
        "markdown": _REALISTIC_MARKDOWN,
    }
    return toolkit


def test_fetch_page_returns_the_pages_markdown():
    toolkit = _fetch_toolkit()

    text, payload = toolkit.execute("fetch_page", {"url": "https://example.com/article"})

    assert payload is None
    toolkit._crawl4ai.scrape.assert_called_once_with("https://example.com/article")
    assert _REALISTIC_MARKDOWN in text


def test_fetch_page_blocks_a_private_host_before_launching_a_browser():
    """The SSRF guard must run first. This tool hands a model-supplied URL to a
    real browser, so a late check would already have made the request.
    """
    toolkit = _fetch_toolkit()

    text, _payload = toolkit.execute("fetch_page", {"url": "http://127.0.0.1:5055/admin"})

    toolkit._crawl4ai.scrape.assert_not_called()
    assert "blocked" in text.lower()


def test_fetch_page_names_the_saved_login_profile_when_one_applies(tmp_path):
    (tmp_path / "example.com").mkdir()
    toolkit = _fetch_toolkit(tmp_path)

    text, _payload = toolkit.execute("fetch_page", {"url": "https://example.com/article"})

    assert "saved login profile" in text.lower()


def test_fetch_page_says_how_to_create_a_profile_when_none_applies(tmp_path):
    """A paywalled fetch without a profile returns a stub. The message has to say
    what to do about it, or the user sees a short article and no reason why.
    """
    toolkit = _fetch_toolkit(tmp_path)

    text, _payload = toolkit.execute("fetch_page", {"url": "https://www.wsj.com/articles/x"})

    # The whole command, not "create-profile" and "wsj.com" as two loose substrings:
    # the hint is only useful if it names the right domain in the right place, and a
    # bare `"wsj.com" in text` would also pass on a hint pointing somewhere else.
    # (It also reads as naive URL-substring sanitization to CodeQL, which flagged it.)
    assert "create-profile www.wsj.com" in text


def test_fetch_page_reports_crawl4ai_unavailable_without_raising():
    """The [scraper] extra is optional; its absence is a message, not a traceback."""
    from ibkr_core_mcp.scrape_fallback import Crawl4AIUnavailableError

    toolkit = _fetch_toolkit()
    toolkit._crawl4ai.scrape.side_effect = Crawl4AIUnavailableError("crawl4ai is not installed")

    text, _payload = toolkit.execute("fetch_page", {"url": "https://example.com/article"})

    assert "not installed" in text
    assert "scraper" in text.lower()


def test_fetch_page_reports_an_empty_fetch_instead_of_claiming_success():
    """No content must never read as a successful fetch of an empty page. There is
    no earlier rung here to fall back to, so the honest answer is "nothing, and why".
    """
    toolkit = _fetch_toolkit()
    toolkit._crawl4ai.scrape.return_value = {"url": "https://example.com/article", "markdown": ""}

    text, _payload = toolkit.execute("fetch_page", {"url": "https://example.com/article"})

    lowered = text.lower()
    assert "no content" in lowered
    assert "fetched" not in lowered.split("no content")[0]


def test_fetch_page_reports_a_browser_failure_instead_of_raising():
    toolkit = _fetch_toolkit()
    toolkit._crawl4ai.scrape.side_effect = OSError("browser crashed")

    text, _payload = toolkit.execute("fetch_page", {"url": "https://example.com/article"})

    assert "browser crashed" in text


def test_fetch_page_flags_a_thin_result_instead_of_presenting_it_as_the_page():
    """A 1-byte body must not read as a successful fetch with a small number beside it.

    Live baseline 2026-07-28: wsj.com without a login profile returns exactly 1 B.
    A model handed "# Fetched: <url>\\n(1 B)" plus one byte can narrate having read the
    article. The reply has to say the content looks incomplete, using the same
    assess_quality signal the fallback ladder already trusts rather than a new
    threshold invented here.
    """
    toolkit = _fetch_toolkit()
    toolkit._crawl4ai.scrape.return_value = {"url": "https://example.com/article", "markdown": "."}

    text, _payload = toolkit.execute("fetch_page", {"url": "https://example.com/article"})

    assert "incomplete" in text.lower()


def test_fetch_page_does_not_cry_wolf_on_a_full_page():
    """The caution above must not fire on real content, or it stops meaning anything."""
    toolkit = _fetch_toolkit()

    text, _payload = toolkit.execute("fetch_page", {"url": "https://example.com/article"})

    assert "incomplete" not in text.lower()


# ============================================================================
# search_site — find pages within one domain (Crawl4AI seeder, no Firecrawl)
# ============================================================================


def test_search_site_blocks_a_private_domain_before_any_lookup():
    """The seeder fetches the named host's sitemap over the network, so a
    model-supplied private host has to be refused here, not after the request."""
    toolkit = _make_toolkit()
    text, _ = toolkit.execute("search_site", {"domain": "localhost", "query": "secrets"})
    assert text.startswith("Blocked:")


def test_search_site_ranks_and_points_at_fetch_page():
    toolkit = _make_toolkit()
    with patch("ibkr_core_mcp.scrape_fallback.search_site") as mock_search:
        mock_search.return_value = [
            {"url": "https://docs.x.dev/deep", "title": "Deep Crawling", "score": 1.0},
            {"url": "https://docs.x.dev/multi", "title": "Multi URL", "score": 0.4},
        ]
        text, _ = toolkit.execute("search_site", {"domain": "docs.x.dev", "query": "deep crawling"})

    assert "Deep Crawling" in text
    assert "https://docs.x.dev/deep" in text
    assert "1.000" in text
    # search finds, fetch_page reads — the reply must say so, since that split is
    # what replaced the old two-engine ladder.
    assert "fetch_page" in text


def test_search_site_says_nothing_matched_rather_than_returning_an_empty_list():
    """Zero matches is a real answer ("the site has no such page"), not a failure,
    and must not read as a broken tool."""
    toolkit = _make_toolkit()
    with patch("ibkr_core_mcp.scrape_fallback.search_site") as mock_search:
        mock_search.return_value = []
        text, _ = toolkit.execute("search_site", {"domain": "docs.x.dev", "query": "nonexistent topic"})

    assert "No pages on docs.x.dev matched" in text
    assert "reachable" in text


def test_search_site_reports_a_missing_package_without_raising():
    from ibkr_core_mcp.scrape_fallback import Crawl4AIUnavailableError

    toolkit = _make_toolkit()
    with patch("ibkr_core_mcp.scrape_fallback.search_site") as mock_search:
        mock_search.side_effect = Crawl4AIUnavailableError("not installed")
        text, _ = toolkit.execute("search_site", {"domain": "docs.x.dev", "query": "q"})

    assert "ibkr_core_mcp[scraper]" in text


def test_search_site_needs_no_firecrawl_key():
    """It reads public sitemaps. A missing FIRECRAWL_API_KEY must not disable it —
    that would recreate the coupling this whole refactor removes."""
    toolkit = _make_toolkit()
    toolkit._config.firecrawl_api_key = ""
    with patch("ibkr_core_mcp.scrape_fallback.search_site") as mock_search:
        mock_search.return_value = [{"url": "https://docs.x.dev/a", "title": "A", "score": 1.0}]
        text, _ = toolkit.execute("search_site", {"domain": "docs.x.dev", "query": "q"})

    assert "FIRECRAWL_API_KEY" not in text
    assert "https://docs.x.dev/a" in text


# ============================================================================
# crawl_site — archive a site with the local browser (no Firecrawl, no credits)
# ============================================================================


def test_crawl_site_refuses_to_archive_an_error_page_as_content():
    """The defect the first LIVE crawl_site run produced, and no unit test predicted.

    Crawling `docs.crawl4ai.com/core/` returned exactly one 44-byte page — nginx's
    "403 Forbidden" — and the handler answered "Crawl complete: saved 1 page(s)" while
    filing that error page into the research archive. A page count is not evidence of
    content, and an error page is still a page.

    Third instance of this trap in this codebase: "saved 0 page(s)" reported as success,
    fetch_page's "(1 B)" reading like a short page, and now this.
    """
    toolkit = _make_toolkit()
    toolkit._web_docs = MagicMock()
    toolkit._web_docs.get_cached_crawl.return_value = None
    with patch("ibkr_core_mcp.scrape_fallback.crawl_site") as mock_crawl:
        mock_crawl.return_value = [
            {
                "url": "https://d.dev/core/",
                "markdown": "# 403 Forbidden\n* * *\nnginx/1.24.0 (Ubuntu)\n",
                "metadata": {},
            }
        ]
        text, _ = toolkit.execute("crawl_site", {"url": "https://d.dev/core/"})

    assert "Nothing was saved to Drive" in text
    assert "403 Forbidden" in text  # the reply shows WHY, not just that it refused
    toolkit._web_docs.save_crawl.assert_not_called()


def test_crawl_site_still_archives_a_genuinely_short_page():
    """Refusing on an all-"fallback" verdict must not also discard real but brief pages —
    assess_quality's "ambiguous" band exists precisely for those."""
    toolkit = _make_toolkit()
    toolkit._web_docs = MagicMock()
    toolkit._web_docs.get_cached_crawl.return_value = None
    toolkit._web_docs.save_crawl.return_value = {
        "url": "https://d.dev/",
        "crawled_at": "2026-07-30T00:00:00+00:00",
        "pages": [{"url": "https://d.dev/", "file_id": "f1"}],
    }
    with patch("ibkr_core_mcp.scrape_fallback.crawl_site") as mock_crawl:
        mock_crawl.return_value = [{"url": "https://d.dev/", "markdown": _REALISTIC_PARAGRAPH[:1600], "metadata": {}}]
        text, _ = toolkit.execute("crawl_site", {"url": "https://d.dev/"})

    assert "Crawl complete: saved 1 page(s)" in text
    toolkit._web_docs.save_crawl.assert_called_once()


def test_crawl_site_needs_no_firecrawl_key():
    """crawl_site replaces firecrawl_crawl precisely so archiving stops depending on a
    paid key. A missing one must not disable it."""
    toolkit = _make_toolkit()
    toolkit._config.firecrawl_api_key = ""
    toolkit._web_docs = MagicMock()
    toolkit._web_docs.get_cached_crawl.return_value = None
    toolkit._web_docs.save_crawl.return_value = {
        "url": "https://d.dev/",
        "crawled_at": "2026-07-30T00:00:00+00:00",
        "pages": [{"url": "https://d.dev/", "file_id": "f1"}],
    }
    with patch("ibkr_core_mcp.scrape_fallback.crawl_site") as mock_crawl:
        mock_crawl.return_value = [{"url": "https://d.dev/", "markdown": _REALISTIC_MARKDOWN, "metadata": {}}]
        text, _ = toolkit.execute("crawl_site", {"url": "https://d.dev/"})

    assert "FIRECRAWL_API_KEY" not in text
    assert "no credits spent" in text


def test_crawl_site_blocks_a_private_url_before_launching_a_browser():
    toolkit = _make_toolkit()
    text, _ = toolkit.execute("crawl_site", {"url": "http://127.0.0.1:5055/admin"})
    assert text.startswith("Blocked:")


def test_crawl_site_uses_the_48h_drive_cache():
    toolkit = _make_toolkit()
    toolkit._web_docs = MagicMock()
    toolkit._web_docs.get_cached_crawl.return_value = {
        "url": "https://d.dev/",
        "crawled_at": "2026-07-30T00:00:00+00:00",
        "pages": [{"url": "https://d.dev/", "file_id": "f1"}],
    }
    with patch("ibkr_core_mcp.scrape_fallback.crawl_site") as mock_crawl:
        text, _ = toolkit.execute("crawl_site", {"url": "https://d.dev/"})
        mock_crawl.assert_not_called()

    assert "cached crawl" in text
