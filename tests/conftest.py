import pytest


@pytest.fixture
def tmp_db(tmp_path):
    """Temporary SQLite database path."""
    return tmp_path / "test_store.db"


@pytest.fixture
def mock_config(tmp_path, tmp_db):
    """Config with safe defaults for unit tests."""
    from ibkr_core_mcp.config import Config

    return Config(
        gateway_url="https://localhost:5055/v1/api",
        anthropic_api_key="test-key",
        gdrive_folder_id="test-folder-id",
        sqlite_path=tmp_db,
        gdrive_token_file=tmp_path / "token.json",
        gdrive_credentials_file=tmp_path / "credentials.json",
    )


# These tests' entire purpose is exercising the real SSRF/DNS validation path
# (ClaudeToolkit._validate_public_url -> scrape_fallback.is_private_host ->
# socket.gethostbyname) against a real public hostname (example.com/wsj.com).
# Discovered while adding _no_real_io below: unrelated to the 3 sleep/network
# bugs that fixture was built to catch (see docs/2026-07-08-claude-tools-test-reorg-design.md),
# and pre-dates this reorg. Mocking DNS resolution here would weaken coverage
# of security-critical SSRF logic (see CLAUDE.md's Firecrawl SSRF hardening
# notes), so these are exempted by name instead of having DNS mocked away.
# test_firecrawl_crawl_saves_pages_to_drive needs this permanently, not just
# until the per-page markdown-length fix lands: _handle_firecrawl_crawl
# validates the *root* URL unconditionally (claude_tools.py, before Firecrawl's
# crawl() is even called), independent of any per-page assess_quality result —
# so blocking DNS here fails the whole tool call outright ("Invalid URL: ...")
# rather than gracefully degrading. The markdown-length fix (Task 14) still
# matters for this test: it prevents the separate, expensive per-page
# Crawl4AI browser fetch once the root check passes.
# test_firecrawl_crawl_never_fetches_blocked_subpage_url_via_crawl4ai needs
# this for a subtler reason: its root URL (example.com) must resolve and pass
# the guard for the test to mean what its docstring claims ("must not reach
# Crawl4AIScraper.scrape even though the top-level crawl root passed the
# guard") — a blocked-by-DNS root would make scrape.assert_not_called() pass
# for the wrong reason (root rejected, not "root ok, sub-page correctly
# rejected"), silently defeating the point of the test.
_REAL_DNS_EXEMPT_TESTS = {
    "test_firecrawl_crawl_saves_pages_to_drive",
    "test_firecrawl_crawl_never_fetches_blocked_subpage_url_via_crawl4ai",
    "test_scrape_with_fallback_uses_crawl4ai_when_quality_is_fallback",
    "test_scrape_with_fallback_ambiguous_and_llm_says_incomplete_falls_back",
    "test_scrape_with_fallback_crawl4ai_unavailable_returns_original_with_note",
    "test_scrape_with_fallback_notes_missing_login_profile",
    "test_scrape_with_fallback_notes_saved_login_profile_used",
    "test_firecrawl_search_applies_fallback_when_result_incomplete",
    "test_validate_public_url_allows_public_https",
    "test_firecrawl_crawl_applies_fallback_per_page",
    "test_firecrawl_crawl_does_not_claim_fallback_used_when_unavailable",
    "test_firecrawl_crawl_batch_maps_outcomes_to_correct_pages",
    "test_firecrawl_crawl_uses_cached_manifest_and_skips_firecrawl",
    "test_firecrawl_crawl_force_refresh_bypasses_cache",
    # The recovery-ladder handler tests, for the same reason as
    # test_firecrawl_crawl_saves_pages_to_drive above: _handle_firecrawl_crawl
    # validates the root URL before anything else, so a DNS block short-circuits
    # the tool into "Invalid URL: ..." and none of the ladder ever runs.
    # test_crawl_does_not_root_scrape_when_firecrawl_returned_content needs it for
    # the subtler reason documented above for the blocked-subpage test: with DNS
    # blocked its scrape.assert_not_called() passes because the root was rejected,
    # not because Firecrawl's content made the root scrape unnecessary.
    "test_crawl_falls_back_to_crawl4ai_root_when_firecrawl_returns_nothing",
    "test_crawl_does_not_root_scrape_when_firecrawl_returned_content",
    "test_crawl_never_reports_zero_pages_as_success",
    "test_crawl_degrades_when_crawl4ai_is_not_installed",
    "test_crawl_reports_network_failure_instead_of_raising",
}


@pytest.fixture(autouse=True)
def _no_real_io(request, monkeypatch):
    """Block real sleeps and real network I/O in every non-integration test.

    Added after discovering 3 claude_tools tests and 6 client.py tests were
    silently paying real wall-clock time (unmocked time.sleep) or making a
    real network call (unmocked Crawl4AI construction) despite being "unit"
    tests. Exempts anything marked `integration`, which intentionally hits
    a real gateway/network, plus the pre-existing SSRF/DNS tests in
    _REAL_DNS_EXEMPT_TESTS above. allow_unix_socket=True is required so
    asyncio's internal self-pipe (socket.socketpair, AF_UNIX) keeps working —
    per pytest-socket's own docs, this is the documented pattern for async
    test suites, not a network hole (AF_INET/DNS stays blocked).
    """
    if request.node.get_closest_marker("integration") or request.node.name in _REAL_DNS_EXEMPT_TESTS:
        yield
        return
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    from pytest_socket import disable_socket, enable_socket

    disable_socket(allow_unix_socket=True)
    yield
    enable_socket()
