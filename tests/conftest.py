import os

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
    """Block sockets from the moment the session starts, so module import and collection
    are covered too. From the first test on, pytest-socket's own per-test hooks take over
    (see `pytest_collection_modifyitems`); its teardown re-enables sockets after every
    test, which is why this call alone is not the per-test guarantee."""
    from pytest_socket import disable_socket

    disable_socket(allow_unix_socket=True)


def pytest_unconfigure(config):
    from pytest_socket import enable_socket

    enable_socket()


def pytest_collection_modifyitems(config, items):
    """Give every test pytest-socket's own marker, so the block is applied by the plugin's
    `pytest_runtest_setup` — which runs BEFORE any fixture, module-scoped ones included.

    Review 2026-09-13: a session-wide `disable_socket()` plus a function-scoped fixture that
    re-enabled sockets for integration tests left the first live module's module-scoped
    `live_client` fixture blocked; `ping()` swallowed the `SocketBlockedError` and the whole
    module skipped as "gateway not reachable" with a green summary. The plugin's marker path
    enables or disables at the right moment for every scope. Integration tests and the
    DNS-exempt tests get `enable_socket`; everything else gets `disable_socket`
    (`--allow-unix-socket` in `addopts` keeps asyncio's self-pipe working).
    """
    for item in items:
        if item.get_closest_marker("integration") or item.name in _REAL_DNS_EXEMPT_TESTS:
            item.add_marker(pytest.mark.enable_socket)
        else:
            item.add_marker(pytest.mark.disable_socket)


@pytest.fixture(autouse=True)
def _no_real_io(request, monkeypatch):
    """Block real sleeps in every non-integration test.

    Added after discovering 3 claude_tools tests and 6 client.py tests were silently paying
    real wall-clock time (unmocked time.sleep) or making a real network call (unmocked
    Crawl4AI construction) despite being "unit" tests. The network half now lives in
    `pytest_collection_modifyitems` above (pytest-socket markers); this fixture keeps only
    the sleep stub, and exempts the same tests.
    """
    if request.node.get_closest_marker("integration") or request.node.name in _REAL_DNS_EXEMPT_TESTS:
        yield
        return
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    yield


@pytest.fixture
def client(mock_config):
    """An `IBKRClient` with no auth and the accounts pre-initialised — shared by
    `tests/test_client.py` and `tests/security/` (was copied in three places)."""
    from ibkr_core_mcp.auth import NoAuth
    from ibkr_core_mcp.client import IBKRClient

    c = IBKRClient(mock_config, auth=NoAuth())
    # Pre-mark accounts as initialized so order/auth tests don't need to also mock the
    # /iserver/accounts prerequisite call. Tests for _ensure_accounts_initialized() itself
    # reset this flag explicitly.
    c._accounts_initialized = True
    return c


# Every variable this package reads carries one of these prefixes (`Config.from_env`,
# `IBKR_AUTH_BROWSER` in claude_tools, `CRAWL4AI_PROFILES_DIR`). Scrubbing by prefix, not by
# a hand-kept list: the first version listed 14 names, the test that checked them listed 7,
# and neither had `IBKR_AUTH_BROWSER` (review 2026-09-13).
_SECRET_ENV_PREFIXES = ("IBKR_", "GDRIVE_", "GOOGLE_", "FIRECRAWL_", "ANTHROPIC_", "CRAWL4AI_")


@pytest.fixture(autouse=True)
def _no_real_secrets(request, monkeypatch):
    """Keep the operator's `.env` and environment out of every non-integration test.

    Constructing `Config(...)` runs `load_dotenv()` through the `crawl4ai_profiles_dir`
    default factory, which walks up from `config.py` and loads the repository's real
    `.env` into `os.environ` — probed 2026-09-13: FIRECRAWL_API_KEY and GDRIVE_* appeared
    in a unit test's environment (docs/audits/security-architecture-audit-2026-09-13.md,
    B6). pytest-socket stops that key from reaching the network, but a test asserting on
    `os.environ` or calling `Config.from_env()` would silently use real values and pass
    for the wrong reason. `load_dotenv` becomes a no-op at every import site and every
    variable with a package prefix is removed; tests/security/test_no_live_io.py holds this.
    """
    if request.node.get_closest_marker("integration"):
        yield
        return
    noop = lambda *args, **kwargs: False  # noqa: E731
    monkeypatch.setattr("ibkr_core_mcp.config.load_dotenv", noop)
    monkeypatch.setattr("dotenv.load_dotenv", noop)
    monkeypatch.setattr("dotenv.main.load_dotenv", noop)
    for name in [k for k in os.environ if k.startswith(_SECRET_ENV_PREFIXES)]:
        monkeypatch.delenv(name, raising=False)
    yield
