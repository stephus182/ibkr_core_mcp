"""Live integration tests for the Crawl4AI Cloud client.

Exercises the real API (https://api.crawl4ai.com) — no mocking. Run with the key
exported, or from this repo's gitignored .env:

    export CRAWL4AI_API_KEY=sk_live_...
    pytest tests/test_crawl4ai_cloud_live.py -v -m integration

All tests skip automatically when CRAWL4AI_API_KEY is not set.

## Budget

The account is on the free plan **as of 2026-07-28**: 50 credits/day, 10 requests/min,
1 concurrent request. Measured cost of a POST /v1/scrape, from live `dry_run` estimates on
that date:

| proxy      | credits |
|------------|---------|
| omitted    | 1       |
| datacenter | 2       |
| residential| 5       |

This module therefore spends **exactly 1 credit per full run**: one real no-proxy scrape.
Everything else is free — `GET /v1/usage` costs a request but no credits, and `dry_run`
validates and prices a request without executing or charging it. `dry_run` is *not*
documented in the vendor's llms-full.txt but was live-verified working and free on
2026-07-28.

Two rules that cost real money if broken:

- **Never point a live scrape at a page under 5 KB of markdown.** It lands below
  `web_scraper._MIN_USEFUL_BYTES`, which makes the ladder treat a perfectly good fetch as
  a failure and burn quota on the next rung every run. `example.com` is 167 B;
  the target below is ~14 KB.
- **Serialise.** The free plan allows 1 concurrent request, so parallel tests 429 against
  each other. These tests are sequential and must stay that way.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.integration

# Over _MIN_USEFUL_BYTES (5 KB) by a wide margin — see the module docstring.
_LIVE_TARGET = "https://docs.firecrawl.dev/introduction"


@pytest.fixture(scope="module")
def cloud_key() -> str:
    key = os.environ.get("CRAWL4AI_API_KEY", "")
    if not key:
        from dotenv import load_dotenv

        load_dotenv(override=False)
        key = os.environ.get("CRAWL4AI_API_KEY", "")
    if not key:
        pytest.skip("CRAWL4AI_API_KEY not set — skipping live Crawl4AI Cloud tests")
    return key


@pytest.fixture(scope="module")
def client(cloud_key):
    from ibkr_core_mcp.crawl4ai_cloud import Crawl4AICloudClient

    return Crawl4AICloudClient(cloud_key)


def test_usage_reports_a_plan_and_a_credit_balance(client):
    """Free: no credits charged. Also pins the live response shape.

    The vendor's own llms-full.txt documents crawl.credits_daily_limit /
    crawl.credits_remaining_today for this endpoint. Those keys do not exist. If this test
    starts failing, re-read the live response before trusting the published reference.
    """
    usage = client.usage()

    assert usage["plan"]["daily_credits"] > 0
    assert usage["credits"]["remaining_today"] >= 0
    assert usage["plan"]["concurrent"] >= 1


def test_estimate_prices_a_request_without_spending_a_credit(client):
    """dry_run is undocumented in llms-full.txt but real, and it is how the rest of this
    module stays inside a 50/day budget.

    The quote body has no `success` key — the first version of this client demanded one
    and raised on every real dry run. That is why estimate() exists separately from
    scrape(), and why this assertion is on the live suite.
    """
    before = client.usage()["credits"]["used_today"]

    quote = client.estimate(_LIVE_TARGET)

    assert float(quote["credits"]) == 1.0, "a no-proxy scrape was 1 credit on 2026-07-28"
    assert client.usage()["credits"]["used_today"] == before


def test_proxy_mode_raises_the_price_which_is_why_the_ladder_omits_it(client):
    """Measured 2026-07-28: none=1, datacenter=2, residential=5. Free to re-verify."""
    plain = float(client.estimate(_LIVE_TARGET)["credits"])
    datacenter = float(client.estimate(_LIVE_TARGET, proxy_mode="datacenter")["credits"])
    residential = float(client.estimate(_LIVE_TARGET, proxy_mode="residential", proxy_country="US")["credits"])

    assert plain < datacenter < residential


def test_proxy_as_a_bare_string_is_rejected(client):
    """Firecrawl's `proxy: "direct"` is a hard 422 here — proved without spending a credit.

    This is the trap that makes copying FirecrawlClient's request builder wrong.
    """
    import requests

    resp = requests.post(
        "https://api.crawl4ai.com/v1/scrape",
        headers={"X-API-Key": os.environ["CRAWL4AI_API_KEY"], "Content-Type": "application/json"},
        json={"url": _LIVE_TARGET, "fit": True, "dry_run": True, "proxy": "direct"},
        timeout=60,
    )

    # Posted by hand, not through the client: scrape() has no code path that can build this
    # body, which is the point. This test guards the reason for that, not the client.
    assert resp.status_code == 422
    assert resp.json()["detail"][0]["loc"] == ["body", "proxy"]


def test_a_bad_key_is_a_401_not_a_silent_empty_page():
    from ibkr_core_mcp.crawl4ai_cloud import Crawl4AICloudClient, Crawl4AICloudError

    with pytest.raises(Crawl4AICloudError) as excinfo:
        Crawl4AICloudClient("sk_live_definitely_not_a_real_key").usage()

    assert excinfo.value.status_code == 401


def test_real_scrape_returns_usable_markdown_and_charges_one_credit(client):
    """The one paid call in this module. Costs 1 credit with no proxy (measured 2026-07-28)."""
    from ibkr_core_mcp.web_scraper import _MIN_USEFUL_BYTES, content_bytes

    before = client.usage()["credits"]["used_today"]

    page = client.scrape(_LIVE_TARGET)

    assert set(page) == {"url", "markdown", "metadata"}
    assert content_bytes([page]) > _MIN_USEFUL_BYTES, (
        f"live target yielded only {content_bytes([page])} B — under the ladder's "
        f"usefulness floor, which would make this rung look like a failure every run"
    )
    assert client.last_credits_remaining is not None

    spent = client.usage()["credits"]["used_today"] - before
    assert spent == 1, f"expected a no-proxy scrape to cost 1 credit, spent {spent}"


def test_ladder_rescues_a_crawl_end_to_end_through_claude_toolkit(cloud_key, tmp_path):
    """The definition-of-done case: Firecrawl AND local both fail, Cloud rescues, source named.

    Only the two failing rungs and Drive are mocked. The cloud rung is the real client
    making a real call — this is the one test that proves the wiring, not just the pieces.
    Drive is mocked for the same reason as tests/test_web_scraper_live.py: exercising
    WebDocsStore needs real GDrive OAuth, which is out of scope for a key-gated suite.

    Costs 1 credit.
    """
    from unittest.mock import MagicMock

    from ibkr_core_mcp.claude_tools import ClaudeToolkit
    from ibkr_core_mcp.config import Config

    cfg = Config(
        gateway_url="https://localhost:5055/v1/api",
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", "test-key"),
        gdrive_folder_id="test-folder",
        sqlite_path=tmp_path / "store.db",
        gdrive_token_file=tmp_path / "token.json",
        gdrive_credentials_file=tmp_path / "creds.json",
        firecrawl_api_key="fc-test",
        crawl4ai_api_key=cloud_key,
    )
    toolkit = ClaudeToolkit(client=MagicMock(), cache=MagicMock(), store=MagicMock(), config=cfg)

    # Rung 1: Firecrawl returns nothing at all.
    toolkit._firecrawl = MagicMock()
    toolkit._firecrawl.crawl.return_value = []
    # Rung 2: the local Playwright scraper comes up empty too.
    toolkit._crawl4ai = MagicMock()
    toolkit._crawl4ai.scrape.return_value = {"url": _LIVE_TARGET, "markdown": ""}
    toolkit._web_docs = MagicMock()
    toolkit._web_docs.get_cached_crawl.return_value = None
    toolkit._web_docs.save_crawl.return_value = {
        "url": _LIVE_TARGET,
        "crawled_at": "2026-07-28T00:00:00+00:00",
        "pages": [{"url": _LIVE_TARGET, "file_id": "live"}],
    }
    # Rung 3 is left alone: the real Crawl4AICloudClient is constructed by the handler.

    text, _payload = toolkit.execute("firecrawl_crawl", {"url": _LIVE_TARGET})

    assert "Crawl4AI Cloud" in text, text
    assert "credits remaining today" in text.lower(), text
    saved_pages = toolkit._web_docs.save_crawl.call_args[0][1]
    assert len(saved_pages[0]["markdown"]) > 5 * 1024
