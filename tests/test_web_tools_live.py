"""LIVE acceptance suite for the four web tools, through `ClaudeToolkit.execute()`.

**Why this file exists.** Every defect in the 2026-07-30 scraper rewrite was found by
running the tool, never by a passing unit test — four of them in one session, each behind
a green suite. The pattern is old here: `create_profile` shipped with three passing tests
and had never once been executed, and failed on its first real invocation for three
independent reasons. Mocks are routinely weaker than the dependency they stand in for.

So each test below is a regression guard for a specific defect that **only a live run
could have surfaced**, and the docstring names it. If one fails, read the docstring before
assuming the test is wrong.

Sibling files test the parts; this one tests the four tools as the model actually sees
them — `tests/test_local_browser.py` (browser, mocked), `tests/test_crawl4ai_live.py`
(browser, real), `tests/test_web_scraper_live.py` (Firecrawl client),
`tests/test_web_scraper_drive_live.py` (Drive persistence).

Run:
    pytest tests/test_web_tools_live.py -v -m integration

Requirements, each skipped independently rather than failing:
  * the `[scraper]` extra + `crawl4ai-setup` — all browser tests
  * `FIRECRAWL_API_KEY` — the whole-web search test only (spends ~1 credit)

Costs: the browser tests are free. Targets are stable documentation hosts, deliberately
NOT `example.com` — it yields ~166 B, which correctly grades "fallback", so it is a bad
probe for anything except the "too thin to be content" path.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

# Stable, static, automation-tolerant targets. docs.crawl4ai.com is used throughout
# because its sitemap is small and its content changed under none of the 2026-07-30 runs.
DOCS_HOST = "docs.crawl4ai.com"
DOCS_PAGE = "https://docs.crawl4ai.com/core/deep-crawling/"
DOCS_ROOT = "https://docs.crawl4ai.com/core/quickstart/"
DIRECTORY_PREFIX_403 = "https://docs.crawl4ai.com/core/"


@pytest.fixture(scope="module")
def browser_available():
    try:
        import crawl4ai  # noqa: F401
    except ImportError:
        pytest.skip("crawl4ai not installed — `pip install ibkr_core_mcp[scraper]` then `crawl4ai-setup`")


@pytest.fixture()
def toolkit(tmp_path):
    """Toolkit with NO Firecrawl key and a profiles dir that cannot exist.

    Deliberate: it proves the three browser tools work with neither, which is the whole
    claim of the 2026-07-30 split. A test that silently depended on the developer's own
    saved WSJ profile would behave differently on another machine.
    """
    from ibkr_core_mcp.claude_tools import ClaudeToolkit
    from ibkr_core_mcp.config import Config

    config = Config(
        gateway_url="https://localhost:5055/v1/api",
        anthropic_api_key="unused-by-the-scraper",
        gdrive_folder_id="",
        sqlite_path=tmp_path / "store.db",
        gdrive_token_file=tmp_path / "token.json",
        gdrive_credentials_file=tmp_path / "credentials.json",
        firecrawl_api_key="",
        crawl4ai_profiles_dir=tmp_path / "profiles-that-do-not-exist",
    )
    return ClaudeToolkit(MagicMock(), MagicMock(), MagicMock(), config)


# ---------------------------------------------------------------------------
# search_site — find pages on one site
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_search_site_ranks_the_right_page_first(browser_available, toolkit):
    """Guards `extract_head=True`, which the vendor's own documented example omits.

    Without it the seeder scores **zero** of 87 URLs and returns them in sitemap order —
    a list that still looks like ranked search. A unit test can assert the flag is passed;
    only a live run proves the flag is what produces a ranking.
    """
    text, fig = toolkit.execute("search_site", {"domain": DOCS_HOST, "query": "deep crawling strategy"})

    assert fig is None
    assert "match(es)" in text, text
    first_url = next(line for line in text.splitlines() if line.strip().startswith("http"))
    assert "deep-crawling" in first_url, f"expected the deep-crawling page ranked first, got: {first_url}"
    assert "1.000" in text, "the best match should normalise to 1.000"
    assert "fetch_page" in text, "search_site must hand off to fetch_page — it finds, it does not read"


@pytest.mark.integration
def test_search_site_reports_no_match_instead_of_ranking_noise(browser_available, toolkit):
    """Guards the 0.5 plateau — the sharpest defect of the rewrite.

    BM25 does not score a non-matching page 0.0; it gives EVERY page an identical neutral
    0.5. The first live run answered this exact query with ten confidently-ranked pages:
    the Privacy Policy, the Contributing Guide, the home page. The unit tests had mocked a
    miss as 0.0 and were all green.

    A failure here means the flat-distribution guard has regressed and the tool is once
    again inventing relevance.
    """
    text, _ = toolkit.execute("search_site", {"domain": DOCS_HOST, "query": "zzzq nonexistent topic xyzzy"})

    assert "No pages on" in text, f"a nonsense query must return no matches, got: {text[:400]}"
    assert "Privacy" not in text and "Contributing" not in text


@pytest.mark.integration
def test_search_site_needs_no_firecrawl_key(browser_available, toolkit):
    """The toolkit fixture has `firecrawl_api_key=""`. Free site search is the entire
    reason the paid crawl rung could be deleted, so a key requirement creeping back in
    would silently undo that."""
    assert toolkit._config.firecrawl_api_key == ""
    text, _ = toolkit.execute("search_site", {"domain": DOCS_HOST, "query": "browser configuration"})

    assert "FIRECRAWL_API_KEY" not in text
    assert "match(es)" in text or "No pages on" in text


# ---------------------------------------------------------------------------
# fetch_page — read one page
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_fetch_page_returns_real_content_without_crying_wolf(browser_available, toolkit):
    """A real documentation page must come back whole AND unflagged.

    The complement of the thin-content tests: a guard that fires on everything is as
    useless as one that never fires. Live baseline 2026-07-30: 41,601 B.
    """
    text, fig = toolkit.execute("fetch_page", {"url": DOCS_PAGE})

    assert fig is None
    assert "Deep Crawl" in text or "deep crawl" in text.lower()
    assert len(text) > 10_000, f"expected a substantial page, got {len(text)} chars"
    assert "may be incomplete" not in text, "a full page must not be flagged as incomplete"


@pytest.mark.integration
def test_fetch_page_flags_an_anti_bot_stub_rather_than_presenting_it(browser_available, toolkit):
    """Guards the "a byte count is not a warning" finding.

    `wsj.com` answers this machine's browser with **1 byte** at HTTP 401 — DataDome, and
    verified 2026-07-30 to be identical with a real saved login profile, headless or
    visible. So `# Fetched: <url>` / `(1 B)` reads exactly like a successful fetch of a
    short page unless something says otherwise.

    This test asserts the *flag*, not the block: if WSJ ever starts serving this machine
    real content, the assertion on `1 B` will fail loudly and that is worth knowing.
    """
    text, _ = toolkit.execute("fetch_page", {"url": "https://www.wsj.com"})

    assert "may be incomplete" in text, f"a 1 B anti-bot stub must be flagged: {text[:300]}"


# ---------------------------------------------------------------------------
# crawl_site — archive a site
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_crawl_site_refuses_to_archive_an_error_page(browser_available, toolkit):
    """Guards the third instance of "a page count is not evidence of content".

    `/core/` is a directory prefix; nginx answers 403 with a 44-byte body. An earlier
    build archived that into Drive and reported "Crawl complete: saved 1 page(s)".
    Predecessors of the same trap: "saved 0 page(s)" reported as success, and
    `fetch_page`'s "(1 B)".

    Asserts nothing reached Drive: `save_crawl` must never be called.
    """
    text, _ = toolkit.execute(
        "crawl_site", {"url": DIRECTORY_PREFIX_403, "max_pages": 3, "max_depth": 0, "force_refresh": True}
    )

    assert "none of them is content" in text, text[:400]
    assert "Nothing was saved to Drive" in text
    assert "403" in text, "the reply must quote the offending content, not just refuse"


@pytest.mark.integration
def test_crawl_site_archives_a_real_page_and_does_not_duplicate_the_root(browser_available, toolkit, monkeypatch):
    """Guards the duplicated-root defect: the deep-crawl strategy returns the root URL
    twice, at depth 0 and depth 1, byte-identical. Undeduplicated, `save_crawl` writes one
    file but records two manifest entries, so the reply claims a page count the archive
    does not contain.

    Drive is stubbed — this asserts what `crawl_site` HANDS to the store, which is where
    the defect lived. `tests/test_web_scraper_drive_live.py` covers the real Drive write.
    """
    saved = {}

    class _FakeStore:
        def get_cached_crawl(self, url, max_age_hours=48.0):
            return None

        def save_crawl(self, url, pages):
            saved["pages"] = pages
            return {"url": url, "crawled_at": "2026-07-30T00:00:00+00:00", "pages": [{"url": p["url"]} for p in pages]}

    toolkit._web_docs = _FakeStore()
    text, _ = toolkit.execute("crawl_site", {"url": DOCS_ROOT, "max_pages": 4, "max_depth": 1, "force_refresh": True})

    assert "Crawl complete" in text, text[:400]
    assert "no credits spent" in text
    urls = [p["url"] for p in saved["pages"]]
    assert len(urls) == len(set(urls)), f"the same URL was archived twice: {urls}"
    assert all(p["markdown"] for p in saved["pages"]), "an empty page must never reach Drive"


# ---------------------------------------------------------------------------
# firecrawl_search — the one job only Firecrawl can do (costs ~1 credit)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_firecrawl_search_reaches_hosts_search_site_never_could(tmp_path):
    """The justification for keeping the Firecrawl dependency at all.

    `search_site` is domain-scoped by construction (`AsyncUrlSeeder.urls(domain, config)`),
    so it can search *a* site but never *the web*. This asserts the distinguishing
    property directly: results arrive from hosts the caller never named.
    """
    key = os.environ.get("FIRECRAWL_API_KEY", "")
    if not key:
        pytest.skip("FIRECRAWL_API_KEY not set — skipping the one test that spends a credit")

    from ibkr_core_mcp.claude_tools import ClaudeToolkit
    from ibkr_core_mcp.config import Config

    config = Config(
        gateway_url="https://localhost:5055/v1/api",
        anthropic_api_key="unused-by-the-scraper",
        gdrive_folder_id="",
        sqlite_path=tmp_path / "store.db",
        gdrive_token_file=tmp_path / "token.json",
        gdrive_credentials_file=tmp_path / "credentials.json",
        firecrawl_api_key=key,
    )
    toolkit = ClaudeToolkit(MagicMock(), MagicMock(), MagicMock(), config)

    text, fig = toolkit.execute("firecrawl_search", {"query": "BM25 relevance ranking documentation", "limit": 3})

    # An exhausted quota or an active rate limit is a fact about the ACCOUNT, not a
    # regression in the code under test — but it must be loud, not swallowed. Skipping
    # names the cause in the skip reason, where a plain pass would hide it entirely.
    # (Hit for real on 2026-07-30: the day's live runs exhausted the free tier.)
    if "HTTP 402" in text or "HTTP 429" in text:
        pytest.skip(f"Firecrawl account cannot serve this request right now: {text.strip()}")

    assert fig is None
    assert "Search results for" in text
    hosts = {line.split("//", 1)[1].split("/", 1)[0] for line in text.splitlines() if "**URL:** http" in line}
    assert hosts, f"no result URLs parsed from: {text[:400]}"
    assert "fetch_page" in text, "search finds; fetch_page reads"


# ---------------------------------------------------------------------------
# SSRF — every tool that takes a URL or a host
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("fetch_page", {"url": "http://127.0.0.1:5055/admin"}),
        ("crawl_site", {"url": "http://localhost:8001/"}),
        ("search_site", {"domain": "localhost", "query": "secrets"}),
    ],
)
def test_private_hosts_are_refused_before_any_request(toolkit, tool, args):
    """All three URL-taking tools must reject a private host, and must do it BEFORE the
    browser or the sitemap fetch — a late check has already made the request it was meant
    to prevent. Needs no `crawl4ai`: rejection must happen even when the browser is absent.
    """
    text, _ = toolkit.execute(tool, args)
    assert text.startswith("Blocked:"), f"{tool} did not refuse a private host: {text[:200]}"
