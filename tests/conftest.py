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
# bugs that fixture was built to catch (see
# docs/plans/archive/testing-audits/2026-07-08-claude-tools-test-reorg-design.md), and pre-dates this
# reorg. Mocking DNS resolution here would weaken coverage of security-critical
# SSRF logic (see SECURITY.md § SSRF Prevention (Web Scraping)), so these are
# exempted by name instead of having DNS mocked away.
#
# THIS SET IS A SECURITY EXEMPTION LIST. An entry grants a test the right to make
# real DNS calls, so a name that no longer matches any test is not harmless — it is
# an exemption nothing uses, and it makes the set look better-audited than it is.
# Three such names survived here from tools deleted on 2026-07-30 and were removed
# on 2026-08-07; prune in the same commit as any test deletion.
#
# Every entry is here for one reason: the handler SSRF-validates before doing its
# real work, so blocked DNS short-circuits the tool into "Blocked: ..." / "Invalid
# URL: ..." and the test's assertions stop meaning anything — they would pass for
# the wrong reason. The matching "...blocks_a_private_..." tests are deliberately
# NOT listed: they want the rejection, and localhost/127.0.0.1 need no DNS to be
# recognised.
_REAL_DNS_EXEMPT_TESTS = {
    "test_validate_public_url_allows_public_https",
    # fetch_page handler tests — _handle_fetch_page validates the URL before
    # constructing the browser.
    "test_fetch_page_returns_the_pages_markdown",
    "test_fetch_page_names_the_saved_login_profile_when_one_applies",
    "test_fetch_page_says_how_to_create_a_profile_when_none_applies",
    "test_fetch_page_reports_crawl4ai_unavailable_without_raising",
    "test_fetch_page_reports_an_empty_fetch_instead_of_claiming_success",
    "test_fetch_page_reports_a_browser_failure_instead_of_raising",
    "test_fetch_page_flags_a_thin_result_instead_of_presenting_it_as_the_page",
    "test_fetch_page_does_not_cry_wolf_on_a_full_page",
    # search_site handler tests — _handle_search_site validates the domain before the
    # seeder runs.
    "test_search_site_ranks_and_points_at_fetch_page",
    "test_search_site_says_nothing_matched_rather_than_returning_an_empty_list",
    "test_search_site_does_not_claim_pages_were_read_when_none_were_discovered",
    "test_search_site_does_not_claim_pages_were_scored_when_none_were",
    "test_search_site_reports_a_missing_package_without_raising",
    "test_search_site_needs_no_firecrawl_key",
    # crawl_site handler tests — the root URL is validated before the browser runs.
    "test_crawl_site_refuses_to_archive_an_error_page_as_content",
    "test_crawl_site_still_archives_a_genuinely_short_page",
    "test_crawl_site_needs_no_firecrawl_key",
    "test_crawl_site_uses_the_48h_drive_cache",
}


def pytest_configure(config):
    """Block sockets from the moment the session starts, not from each test's setup.

    `_no_real_io` below arms pytest-socket per test, which leaves module import and
    collection uncovered: a module that resolved a name at import time would have done so
    before any fixture ran (docs/audits/security-architecture-audit-2026-09-13.md, C).
    Blocking here closes that; the fixture then *enables* sockets only for the tests that
    are entitled to them.
    """
    from pytest_socket import disable_socket

    disable_socket(allow_unix_socket=True)


def pytest_unconfigure(config):
    from pytest_socket import enable_socket

    enable_socket()


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

    Since 2026-09-13 the session-wide block from `pytest_configure` is the default
    state; this fixture opens a window for the exempt tests and re-closes it after.
    """
    from pytest_socket import disable_socket, enable_socket

    if request.node.get_closest_marker("integration") or request.node.name in _REAL_DNS_EXEMPT_TESTS:
        enable_socket()
        yield
        disable_socket(allow_unix_socket=True)
        return
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    disable_socket(allow_unix_socket=True)
    yield


# Secret-named variables that must never be visible to a unit test. A test that needs one
# sets a fake with monkeypatch.setenv; nothing here may read the operator's.
_SECRET_ENV_VARS = (
    "ANTHROPIC_API_KEY",
    "FIRECRAWL_API_KEY",
    "IBKR_FLEX_TOKEN",
    "IBKR_FLEX_QUERY_ID",
    "GDRIVE_TOKEN_FILE",
    "GDRIVE_CREDENTIALS_FILE",
    "GOOGLE_DRIVE_FOLDER_ID",
    "GDRIVE_WEB_DOCS_FOLDER_ID",
    "GDRIVE_CACHE_FOLDER_ID",
    "GDRIVE_DB_FOLDER_ID",
    "GDRIVE_ACCOUNT_FOLDER_ID",
    "IBKR_GATEWAY_URL",
    "IBKR_SQLITE_PATH",
    "CRAWL4AI_PROFILES_DIR",
)


@pytest.fixture(autouse=True)
def _no_real_secrets(request, monkeypatch):
    """Keep the operator's `.env` and environment out of every non-integration test.

    Constructing `Config(...)` runs `load_dotenv()` through the `crawl4ai_profiles_dir`
    default factory, which walks up from `config.py` and loads the repository's real
    `.env` into `os.environ` — probed 2026-09-13: FIRECRAWL_API_KEY and GDRIVE_* appeared
    in a unit test's environment (docs/audits/security-architecture-audit-2026-09-13.md,
    B6). pytest-socket stops that key from reaching the network, but a test asserting on
    `os.environ` or calling `Config.from_env()` would silently use real values and pass
    for the wrong reason. `load_dotenv` becomes a no-op and the secret names are removed;
    tests/security/test_no_live_io.py holds this.
    """
    if request.node.get_closest_marker("integration"):
        yield
        return
    monkeypatch.setattr("ibkr_core_mcp.config.load_dotenv", lambda *args, **kwargs: False)
    for name in _SECRET_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    yield
