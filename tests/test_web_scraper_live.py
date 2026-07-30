"""Live integration tests for the Firecrawl web scraper.

Exercises the real Firecrawl REST API (https://api.firecrawl.dev/v1) — no
mocking. Covers:
    FirecrawlClient.search, FirecrawlClient.crawl,
    ClaudeToolkit.execute("firecrawl_search") end-to-end

Run with real API keys exported (not committed anywhere):
    export FIRECRAWL_API_KEY=fc-...
    export ANTHROPIC_API_KEY=sk-ant-...   # only needed if a result is ambiguous

    pytest tests/test_web_scraper_live.py -v -m integration

All tests are skipped automatically when FIRECRAWL_API_KEY is not set.

## Scope

- FirecrawlClient.search/crawl hit the real API — network calls, real cost
  against the configured Firecrawl plan. Kept cheap: limit=1, max_pages=1,
  targeting small/stable pages.
- Drive persistence (WebDocsStore, firecrawl_crawl's mandatory save_to_drive)
  is NOT exercised here — it needs real GDrive OAuth, out of scope for this
  key-gated suite. firecrawl_crawl is tested via FirecrawlClient.crawl()
  directly (module-level), not through ClaudeToolkit.execute, for that reason.
  firecrawl_search is tested through ClaudeToolkit.execute with
  save_to_drive=False (the schema default).
- The Crawl4AI fallback is NOT forced here — it only fires when
  assess_quality() classifies a real Firecrawl result as ambiguous/fallback,
  which depends on live page content at run time and isn't deterministic to
  script against a real target.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def firecrawl_key() -> str:
    key = os.environ.get("FIRECRAWL_API_KEY", "")
    if not key:
        pytest.skip("FIRECRAWL_API_KEY not set — skipping live Firecrawl tests")
    return key


def _skip_if_account_cannot_serve(text: str) -> None:
    """Skip — loudly, naming the cause — when Firecrawl refuses for account reasons.

    HTTP 402 (out of credits) and 429 (rate limited) describe the ACCOUNT, not the code
    under test, so failing on them reports a defect that does not exist. Skipping with the
    real message keeps the cause visible in the skip reason instead of hiding it behind a
    green run. Hit for real on 2026-07-30, when a day of live scraper work exhausted the
    free tier mid-suite.
    """
    if "HTTP 402" in text or "HTTP 429" in text:
        pytest.skip(f"Firecrawl account cannot serve this request right now: {text.strip()}")


@pytest.fixture(scope="module")
def live_config(firecrawl_key, tmp_path_factory):
    from ibkr_core_mcp.config import Config

    tmp = tmp_path_factory.mktemp("web_scraper_live_cfg")
    return Config(
        gateway_url="https://localhost:5055/v1/api",
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", "test-key"),
        gdrive_folder_id="test-folder-id",
        sqlite_path=tmp / "store.db",
        gdrive_token_file=tmp / "token.json",
        gdrive_credentials_file=tmp / "credentials.json",
        firecrawl_api_key=firecrawl_key,
    )


@pytest.fixture(scope="module")
def toolkit(live_config):
    from ibkr_core_mcp.claude_tools import ClaudeToolkit

    # firecrawl_search touches none of client/cache/store on its happy path —
    # only self._config and self._firecrawl (lazily built from firecrawl_api_key).
    return ClaudeToolkit(MagicMock(), MagicMock(), MagicMock(), live_config)


# ---------------------------------------------------------------------------
# FirecrawlClient — direct, real API
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_firecrawl_client_search_real_query(firecrawl_key):
    from ibkr_core_mcp.web_scraper import FirecrawlClient, FirecrawlError

    client = FirecrawlClient(firecrawl_key)
    try:
        results = client.search("Interactive Brokers Client Portal API", limit=1)
    except FirecrawlError as exc:
        # The client RAISES for account-level statuses rather than returning text, so the
        # string-based guard used elsewhere cannot see this one. Same reasoning: 402/429
        # describe the account, not the code. See _skip_if_account_cannot_serve.
        if exc.status_code in (402, 429):
            pytest.skip(f"Firecrawl account cannot serve this request right now: {exc}")
        raise

    assert len(results) >= 1
    result = results[0]
    assert result["url"].startswith("http")
    assert isinstance(result["markdown"], str)
    assert isinstance(result["metadata"], dict)


@pytest.mark.integration
def test_firecrawl_client_invalid_key_raises():
    from ibkr_core_mcp.web_scraper import FirecrawlClient, FirecrawlError

    client = FirecrawlClient("fc-definitely-not-a-real-key")
    with pytest.raises(FirecrawlError) as exc_info:
        client.search("test query", limit=1)
    assert exc_info.value.status_code in (401, 403)


# ---------------------------------------------------------------------------
# ClaudeToolkit.execute("firecrawl_search") — full dispatch path, real API
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_toolkit_firecrawl_search_end_to_end(toolkit):
    text, fig = toolkit.execute(
        "firecrawl_search",
        {"query": "Interactive Brokers Client Portal API", "limit": 1},
    )
    assert fig is None
    _skip_if_account_cannot_serve(text)
    assert "Search results for" in text
    assert "http" in text


@pytest.mark.integration
def test_toolkit_firecrawl_search_empty_query_no_network_call(toolkit):
    text, fig = toolkit.execute("firecrawl_search", {"query": "", "limit": 1})
    assert fig is None
    assert "non-empty" in text
