"""Unit tests for the Crawl4AI Cloud adapter.

The vendor SDK builds the HTTP request, so nothing here asserts on headers, URLs or body
shape — that is the SDK's job, verified once against the live API in
tests/test_crawl4ai_cloud_live.py. What is tested here is *our* behaviour: what we pass the
SDK, how we translate its exceptions, how we map its result onto the ladder's page dict, and
the credit accounting.

`crawl4ai_cloud` is the SDK package; `ibkr_core_mcp.crawl4ai_cloud` is our adapter. Patch
targets below are fully qualified because the two names collide.
"""

import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _client(api_key="crawl4ai-fake-key-for-tests", base_url="https://api.crawl4ai.com"):
    from ibkr_core_mcp.crawl4ai_cloud import Crawl4AICloudClient

    return Crawl4AICloudClient(api_key, base_url=base_url)


# The SDK lives in the optional [scraper] extra, which CI does not install (it runs
# `pip install -e ".[dev,server]"`). So these tests inject a fake `crawl4ai_cloud` module
# rather than importing the real one — the same approach tests/test_scrape_fallback.py takes
# for the optional local `crawl4ai` package. It also keeps the suite independent of the SDK's
# version, which matters because our adapter deliberately pins around one of its defaults.


class _FakeCloudError(Exception):
    def __init__(self, message="", status_code=None, *_args):
        super().__init__(message)
        self.status_code = status_code


class _FakeAuthenticationError(_FakeCloudError):
    pass


class _FakeRateLimitError(_FakeCloudError):
    pass


class _FakeQuotaExceededError(_FakeCloudError):
    quota_type = "daily"


class _FakeProxyConfig:
    def __init__(self, mode=None, country=None):
        self.mode = mode
        self.country = country


def _fake_sdk_module(crawler):
    # setattr rather than attribute assignment, matching _install_fake_crawl4ai in
    # tests/test_scrape_fallback.py: ModuleType has no static attributes, so plain
    # assignment is a mypy attr-defined error.
    errors = types.ModuleType("crawl4ai_cloud.errors")
    setattr(errors, "CloudError", _FakeCloudError)  # noqa: B010
    setattr(errors, "AuthenticationError", _FakeAuthenticationError)  # noqa: B010
    setattr(errors, "RateLimitError", _FakeRateLimitError)  # noqa: B010
    setattr(errors, "QuotaExceededError", _FakeQuotaExceededError)  # noqa: B010

    module = types.ModuleType("crawl4ai_cloud")
    crawler_cls = MagicMock(return_value=crawler)
    setattr(module, "AsyncWebCrawler", crawler_cls)  # noqa: B010
    setattr(module, "ProxyConfig", _FakeProxyConfig)  # noqa: B010
    setattr(module, "errors", errors)  # noqa: B010
    return module, errors, crawler_cls


def _sdk(scrape_result=None, scrape_error=None):
    """Install a fake SDK; return (context_manager, crawler_mock, AsyncWebCrawler_mock)."""
    crawler = MagicMock()
    crawler.scrape = AsyncMock(return_value=scrape_result, side_effect=scrape_error)
    crawler.close = AsyncMock()
    module, errors, crawler_cls = _fake_sdk_module(crawler)
    cm = patch.dict(sys.modules, {"crawl4ai_cloud": module, "crawl4ai_cloud.errors": errors})
    return cm, crawler, crawler_cls


def _page(markdown="# Real content", fit_markdown=None, usage=None, error_message=None):
    """A stand-in for the SDK's MarkdownResponse."""
    r = MagicMock()
    r.markdown = markdown
    r.fit_markdown = fit_markdown
    r.usage = usage
    r.error_message = error_message
    return r


def _usage(credits_remaining=None, credits_used=None):
    u = MagicMock()
    u.credits_remaining = credits_remaining
    u.credits_used = credits_used
    return u


# ============================================================================
# Construction
# ============================================================================


def test_empty_api_key_raises_at_construction():
    from ibkr_core_mcp.crawl4ai_cloud import Crawl4AICloudClient

    with pytest.raises(ValueError, match="api_key"):
        Crawl4AICloudClient("")


def test_missing_sdk_is_a_rung_failure_not_an_import_crash():
    """The cloud rung is optional — an uninstalled SDK must degrade, not break the tool."""
    from ibkr_core_mcp.crawl4ai_cloud import Crawl4AICloudError

    with patch.dict("sys.modules", {"crawl4ai_cloud": None}):
        with pytest.raises(Crawl4AICloudError, match="not installed"):
            _client().scrape("https://example.com/docs")


# ============================================================================
# What we pass the SDK
# ============================================================================


def test_retries_are_disabled_so_a_timeout_cannot_double_bill_a_page():
    """The SDK exempts 429, but a retried *timeout* can re-issue a scrape that already ran."""
    patcher, _crawler, cls = _sdk(scrape_result=_page())
    with patcher:
        _client().scrape("https://example.com/docs")

    assert cls.call_args.kwargs["max_retries"] == 1


def test_strategy_is_pinned_because_the_sdks_own_default_is_invalid():
    """The SDK defaults strategy="auto"; the API rejects it with 422.

    `scrape(strategy: str = "auto")` in crawl4ai-cloud-sdk 1.2.0 is a vendor bug — the live
    endpoint accepts only 'browser' or 'http' (pydantic literal_error, observed 2026-07-28),
    so every call using the SDK default 422s. We pass 'browser' explicitly, which is what
    llms-full.txt documents as the default. Remove this only after the SDK is fixed AND a
    live run proves it.
    """
    patcher, crawler, _cls = _sdk(scrape_result=_page())
    with patcher:
        _client().scrape("https://example.com/docs")

    assert crawler.scrape.call_args.kwargs["strategy"] == "browser"


def test_estimate_pins_the_same_strategy_as_scrape():
    """An estimate for a strategy the real call would not send is a worthless quote."""
    patcher, crawler, _cls = _sdk(scrape_result={"credits": "1.0000"})
    with patcher:
        _client().estimate("https://example.com/docs")

    assert crawler.scrape.call_args.kwargs["strategy"] == "browser"


def test_credentials_and_base_url_are_handed_to_the_sdk():
    patcher, _crawler, cls = _sdk(scrape_result=_page())
    with patcher:
        _client(api_key="secret-key", base_url="https://staging.example/").scrape("https://example.com/docs")

    assert cls.call_args.kwargs["api_key"] == "secret-key"
    assert cls.call_args.kwargs["base_url"] == "https://staging.example"


def test_scrape_omits_proxy_entirely_when_unset():
    """proxy="direct" is a 422 — omission is the only way to ask for no proxy."""
    patcher, crawler, _cls = _sdk(scrape_result=_page())
    with patcher:
        _client().scrape("https://example.com/docs")

    assert crawler.scrape.call_args.kwargs["proxy"] is None


def test_scrape_sends_a_proxy_config_object_when_set():
    patcher, crawler, _cls = _sdk(scrape_result=_page())
    with patcher:
        _client().scrape("https://example.com/docs", proxy_mode="residential", proxy_country="US")

    proxy = crawler.scrape.call_args.kwargs["proxy"]
    assert proxy.mode == "residential"
    assert proxy.country == "US"


def test_scrape_never_asks_for_a_dry_run():
    """A scrape that quietly priced itself instead of fetching would return an empty page."""
    patcher, crawler, _cls = _sdk(scrape_result=_page())
    with patcher:
        _client().scrape("https://example.com/docs")

    assert crawler.scrape.call_args.kwargs.get("dry_run") is not True


def test_estimate_asks_for_a_dry_run_and_returns_the_quote():
    quote = {"credits": "1.0000", "credits_exact": True, "dry_run": True}
    patcher, crawler, _cls = _sdk(scrape_result=quote)
    with patcher:
        result = _client().estimate("https://example.com/docs")

    assert crawler.scrape.call_args.kwargs["dry_run"] is True
    assert result["credits"] == "1.0000"


def test_the_sdk_client_is_always_closed():
    patcher, crawler, _cls = _sdk(scrape_result=_page())
    with patcher:
        _client().scrape("https://example.com/docs")

    crawler.close.assert_awaited_once()


def test_the_sdk_client_is_closed_even_when_the_call_fails():
    patcher, crawler, _cls = _sdk(scrape_error=RuntimeError("boom"))
    from ibkr_core_mcp.crawl4ai_cloud import Crawl4AICloudError

    with patcher, pytest.raises(Crawl4AICloudError):
        _client().scrape("https://example.com/docs")

    crawler.close.assert_awaited_once()


# ============================================================================
# Result mapping
# ============================================================================


def test_scrape_returns_the_shared_page_dict_shape():
    """The ladder and WebDocsStore.save_crawl both consume {"url","markdown","metadata"}."""
    patcher, _crawler, _cls = _sdk(scrape_result=_page(markdown="# Real content"))
    with patcher:
        page = _client().scrape("https://example.com/docs")

    assert page == {"url": "https://example.com/docs", "markdown": "# Real content", "metadata": {}}


def test_scrape_falls_back_to_fit_markdown_when_markdown_is_empty():
    patcher, _crawler, _cls = _sdk(scrape_result=_page(markdown="", fit_markdown="# Pruned"))
    with patcher:
        assert _client().scrape("https://example.com/docs")["markdown"] == "# Pruned"


def test_scrape_raises_when_the_response_reports_an_error():
    """A failed scrape must not look like a successful empty page."""
    from ibkr_core_mcp.crawl4ai_cloud import Crawl4AICloudError

    patcher, _crawler, _cls = _sdk(scrape_result=_page(markdown="", error_message="page returned no HTML"))
    with patcher, pytest.raises(Crawl4AICloudError, match="page returned no HTML"):
        _client().scrape("https://example.com/docs")


# ============================================================================
# Exception translation — the 429 distinction
# ============================================================================


def test_quota_exhaustion_is_named_as_not_retryable():
    """QuotaExceededError and RateLimitError are both 429 and mean opposite things."""
    from ibkr_core_mcp.crawl4ai_cloud import Crawl4AICloudError

    patcher, _crawler, _cls = _sdk(scrape_error=_FakeQuotaExceededError("daily cap", 429, {}, {}))
    with patcher, pytest.raises(Crawl4AICloudError) as excinfo:
        _client().scrape("https://example.com/docs")

    assert excinfo.value.status_code == 429
    assert "not retryable" in str(excinfo.value)


def test_a_rate_limit_is_distinguished_from_quota_exhaustion():
    from ibkr_core_mcp.crawl4ai_cloud import Crawl4AICloudError

    patcher, _crawler, _cls = _sdk(scrape_error=_FakeRateLimitError("rate limit", 429, {}, {}))
    with patcher, pytest.raises(Crawl4AICloudError) as excinfo:
        _client().scrape("https://example.com/docs")

    assert excinfo.value.status_code == 429
    assert "rate limit" in str(excinfo.value).lower()
    assert "not retryable" not in str(excinfo.value)


def test_a_bad_key_maps_to_401():
    from ibkr_core_mcp.crawl4ai_cloud import Crawl4AICloudError

    patcher, _crawler, _cls = _sdk(scrape_error=_FakeAuthenticationError("bad key", 401, {}, {}))
    with patcher, pytest.raises(Crawl4AICloudError) as excinfo:
        _client().scrape("https://example.com/docs")

    assert excinfo.value.status_code == 401


def test_a_transport_error_becomes_a_typed_error_not_a_raw_exception():
    from ibkr_core_mcp.crawl4ai_cloud import Crawl4AICloudError

    patcher, _crawler, _cls = _sdk(scrape_error=OSError("connection reset"))
    with patcher, pytest.raises(Crawl4AICloudError, match="connection reset"):
        _client().scrape("https://example.com/docs")


def test_an_error_never_leaks_the_api_key():
    from ibkr_core_mcp.crawl4ai_cloud import Crawl4AICloudError

    patcher, _crawler, _cls = _sdk(scrape_error=_FakeAuthenticationError("bad key", 401, {}, {}))
    with patcher, pytest.raises(Crawl4AICloudError) as excinfo:
        _client(api_key="super-secret-value").scrape("https://example.com/docs")

    assert "super-secret-value" not in str(excinfo.value)


# ============================================================================
# Credit accounting
# ============================================================================

# Live /v1/usage shape, verified 2026-07-28. NOT the shape in the vendor's own
# llms-full.txt, which documents crawl.credits_daily_limit / crawl.credits_remaining_today —
# those keys do not exist on the live response.
_USAGE_BODY = {
    "plan": {"name": "free", "daily_credits": 50, "rate_per_minute": 10, "concurrent": 1},
    "credits": {"used_today": 0, "remaining_today": 50, "daily_limit": 50},
}


def _usage_response(body=None, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = body if body is not None else _USAGE_BODY
    return resp


@patch("ibkr_core_mcp.crawl4ai_cloud.requests")
def test_scrape_records_credits_remaining(mock_requests):
    mock_requests.get.return_value = _usage_response()
    patcher, _crawler, _cls = _sdk(scrape_result=_page(usage=_usage(credits_remaining=47.0)))
    with patcher:
        client = _client()
        assert client.last_credits_remaining is None
        client.scrape("https://example.com/docs")

    assert client.last_credits_remaining == 47.0


@patch("ibkr_core_mcp.crawl4ai_cloud.requests")
def test_scrape_never_logs_the_responses_credits_used_field(mock_requests, caplog):
    """usage.credits_used is not what the call actually cost.

    Measured live 2026-07-28: a no-proxy scrape reported credits_used 5.0 while the
    /v1/usage ledger moved by exactly 1. credits_remaining agreed with the ledger; this
    field did not, and reading it is where the earlier "5 credits a scrape" budget came from.
    """
    mock_requests.get.return_value = _usage_response()
    patcher, _crawler, _cls = _sdk(scrape_result=_page(usage=_usage(credits_remaining=46.0, credits_used=5.0)))
    with patcher, caplog.at_level("INFO"):
        _client().scrape("https://example.com/docs")

    logged = " | ".join(r.getMessage() for r in caplog.records)
    assert "46.0" in logged, "the trustworthy field must still be reported"
    assert "5.0" not in logged, f"credits_used leaked into a log line: {logged}"


@patch("ibkr_core_mcp.crawl4ai_cloud.requests")
def test_scrape_survives_a_response_carrying_no_usage(mock_requests):
    mock_requests.get.return_value = _usage_response()
    patcher, _crawler, _cls = _sdk(scrape_result=_page(usage=None))
    with patcher:
        client = _client()
        client.scrape("https://example.com/docs")

    assert client.last_credits_remaining is None


@patch("ibkr_core_mcp.crawl4ai_cloud.requests")
def test_low_balance_warning_is_relative_to_the_reported_allowance(mock_requests, caplog):
    """9 of 50 is under a fifth and warns; the threshold is read from the API, never hardcoded."""
    mock_requests.get.return_value = _usage_response()
    patcher, _crawler, _cls = _sdk(scrape_result=_page(usage=_usage(credits_remaining=9.0)))
    with patcher, caplog.at_level("WARNING"):
        _client().scrape("https://example.com/docs")

    assert any("credit" in r.getMessage().lower() for r in caplog.records if r.levelname == "WARNING")


@patch("ibkr_core_mcp.crawl4ai_cloud.requests")
def test_no_low_balance_warning_when_comfortably_above_the_threshold(mock_requests, caplog):
    mock_requests.get.return_value = _usage_response()
    patcher, _crawler, _cls = _sdk(scrape_result=_page(usage=_usage(credits_remaining=40.0)))
    with patcher, caplog.at_level("WARNING"):
        _client().scrape("https://example.com/docs")

    assert [r for r in caplog.records if r.levelname == "WARNING"] == []


@patch("ibkr_core_mcp.crawl4ai_cloud.requests")
def test_a_large_plan_warns_at_a_balance_an_absolute_threshold_would_ignore(mock_requests, caplog):
    """500 of 5000/day is under a fifth and must warn.

    This is the test that fails if anyone reintroduces a hardcoded "warn under 10": 500 sails
    past any small absolute floor while being genuinely low for this plan. It is the upgrade
    direction, which the no-hardcoded-tier rule exists to protect.
    """
    mock_requests.get.return_value = _usage_response(
        {"plan": {"name": "pro", "daily_credits": 5000}, "credits": {"daily_limit": 5000}}
    )
    patcher, _crawler, _cls = _sdk(scrape_result=_page(usage=_usage(credits_remaining=500.0)))
    with patcher, caplog.at_level("WARNING"):
        _client().scrape("https://example.com/docs")

    assert any("credit" in r.getMessage().lower() for r in caplog.records if r.levelname == "WARNING")


@patch("ibkr_core_mcp.crawl4ai_cloud.requests")
def test_the_allowance_is_looked_up_once_and_reused(mock_requests):
    """/v1/usage costs a request against a per-minute limit — poll it once, not per scrape."""
    mock_requests.get.return_value = _usage_response()
    patcher, _crawler, _cls = _sdk(scrape_result=_page(usage=_usage(credits_remaining=9.0)))
    with patcher:
        client = _client()
        client.scrape("https://example.com/a")
        client.scrape("https://example.com/b")
        client.scrape("https://example.com/c")

    assert mock_requests.get.call_count == 1


@patch("ibkr_core_mcp.crawl4ai_cloud.requests")
def test_a_failing_usage_lookup_never_breaks_a_successful_scrape(mock_requests):
    """Quota reporting is a nicety; losing it must not lose the page the ladder just rescued."""
    mock_requests.get.side_effect = OSError("usage endpoint down")
    patcher, _crawler, _cls = _sdk(scrape_result=_page(markdown="# Real", usage=_usage(credits_remaining=1.0)))
    with patcher:
        page = _client().scrape("https://example.com/docs")

    assert page["markdown"] == "# Real"


@patch("ibkr_core_mcp.crawl4ai_cloud.requests")
def test_usage_reads_the_v1_usage_endpoint_the_sdk_does_not_wrap(mock_requests):
    """The SDK covers /v1/crawl/storage but no usage endpoint, so this stays a direct call."""
    mock_requests.get.return_value = _usage_response()

    usage = _client().usage()

    assert mock_requests.get.call_args.args[0] == "https://api.crawl4ai.com/v1/usage"
    assert usage["plan"]["daily_credits"] == 50
    assert usage["credits"]["remaining_today"] == 50


@patch("ibkr_core_mcp.crawl4ai_cloud.requests")
def test_usage_raises_a_typed_error_on_an_http_failure(mock_requests):
    from ibkr_core_mcp.crawl4ai_cloud import Crawl4AICloudError

    mock_requests.get.return_value = _usage_response(status=401)

    with pytest.raises(Crawl4AICloudError) as excinfo:
        _client().usage()
    assert excinfo.value.status_code == 401
