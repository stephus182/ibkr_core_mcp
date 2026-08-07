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
# (ClaudeToolkit._validate_public_url -> local_browser.is_private_host ->
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
    "test_firecrawl_crawl_never_fetches_blocked_subpage_url_via_crawl4ai",
    "test_validate_public_url_allows_public_https",
    "test_firecrawl_crawl_does_not_claim_fallback_used_when_unavailable",
    # The recovery-ladder handler tests, for the same reason as
    # test_firecrawl_crawl_saves_pages_to_drive above: _handle_firecrawl_crawl
    # validates the root URL before anything else, so a DNS block short-circuits
    # the tool into "Invalid URL: ..." and none of the ladder ever runs.
    # test_crawl_does_not_root_scrape_when_firecrawl_returned_content needs it for
    # the subtler reason documented above for the blocked-subpage test: with DNS
    # blocked its scrape.assert_not_called() passes because the root was rejected,
    # not because Firecrawl's content made the root scrape unnecessary.
    "test_crawl_does_not_root_scrape_when_firecrawl_returned_content",
    # The "never downgrade" ladder tests, for the same reason as every other
    # _handle_firecrawl_crawl test above: the root URL is SSRF-validated before any
    # rung runs, so blocked DNS returns "Invalid URL: ..." and no ladder executes.
    # test_local_rung_does_not_replace_a_larger_firecrawl_result needs it for the
    # subtler reason documented above: its scrape.assert_called_once() would fail,
    # and its content assertion would pass vacuously, if the root were rejected
    # before the ladder was ever consulted.
    # Same again: both assert on what save_crawl received, which is reached only if
    # the root URL survives validation and the whole ladder actually runs.
    # fetch_page handler tests. Same reason again: _handle_fetch_page SSRF-validates
    # the URL before constructing the browser, so a blocked DNS lookup turns every
    # one of these into "Blocked: ..." and the assertions stop meaning anything.
    # test_fetch_page_blocks_a_private_host_before_launching_a_browser is NOT listed
    # -- it wants the rejection, and 127.0.0.1 needs no DNS to be recognised.
    "test_fetch_page_returns_the_pages_markdown",
    "test_fetch_page_names_the_saved_login_profile_when_one_applies",
    "test_fetch_page_says_how_to_create_a_profile_when_none_applies",
    "test_fetch_page_reports_crawl4ai_unavailable_without_raising",
    "test_fetch_page_reports_an_empty_fetch_instead_of_claiming_success",
    "test_fetch_page_reports_a_browser_failure_instead_of_raising",
    "test_fetch_page_flags_a_thin_result_instead_of_presenting_it_as_the_page",
    "test_fetch_page_does_not_cry_wolf_on_a_full_page",
    # search_site handler tests: _handle_search_site SSRF-validates the domain before
    # the seeder runs, so blocked DNS turns each of these into "Blocked: ..." and the
    # assertions stop meaning anything. test_search_site_blocks_a_private_domain... is
    # NOT listed -- it wants the rejection, and localhost needs no DNS to be caught.
    "test_search_site_ranks_and_points_at_fetch_page",
    "test_search_site_says_nothing_matched_rather_than_returning_an_empty_list",
    "test_search_site_does_not_claim_pages_were_read_when_none_were_discovered",
    "test_search_site_does_not_claim_pages_were_scored_when_none_were",
    "test_search_site_reports_a_missing_package_without_raising",
    "test_search_site_needs_no_firecrawl_key",
    # crawl_site handler tests: the root URL is SSRF-validated before the browser runs,
    # so blocked DNS turns each into "Blocked: ..." and the assertions stop meaning
    # anything. test_crawl_site_blocks_a_private_url... is NOT listed: it wants the
    # rejection, and 127.0.0.1 needs no DNS to be recognised.
    "test_crawl_site_refuses_to_archive_an_error_page_as_content",
    "test_crawl_site_still_archives_a_genuinely_short_page",
    "test_crawl_site_needs_no_firecrawl_key",
    "test_crawl_site_uses_the_48h_drive_cache",
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
