from unittest.mock import MagicMock, patch

import pytest
import requests


def _resp(status=200, body=None, headers=None):
    """Build a mock requests.Response."""
    resp = MagicMock()
    resp.status_code = status
    resp.headers = headers or {}
    resp.json.return_value = body if body is not None else {}
    return resp


def _client(api_key="sk_live_test", base_url="https://api.crawl4ai.com"):
    from ibkr_core_mcp.crawl4ai_cloud import Crawl4AICloudClient

    return Crawl4AICloudClient(api_key, base_url=base_url)


# ============================================================================
# Construction
# ============================================================================


def test_empty_api_key_raises_at_construction():
    from ibkr_core_mcp.crawl4ai_cloud import Crawl4AICloudClient

    with pytest.raises(ValueError, match="api_key"):
        Crawl4AICloudClient("")


# ============================================================================
# Request shape
# ============================================================================


@patch("ibkr_core_mcp.crawl4ai_cloud.requests")
def test_scrape_authenticates_with_x_api_key_header_not_bearer(mock_requests):
    """Crawl4AI Cloud uses X-API-Key; a Bearer header (Firecrawl's scheme) is a 401."""
    mock_requests.post.return_value = _resp(body={"success": True, "markdown": "# hi"})

    _client().scrape("https://example.com/docs")

    headers = mock_requests.post.call_args.kwargs["headers"]
    assert headers["X-API-Key"] == "sk_live_test"
    assert "Authorization" not in headers


@patch("ibkr_core_mcp.crawl4ai_cloud.requests")
def test_scrape_posts_to_v1_scrape_with_url_and_fit(mock_requests):
    mock_requests.post.return_value = _resp(body={"success": True, "markdown": "# hi"})

    _client().scrape("https://example.com/docs")

    assert mock_requests.post.call_args.args[0] == "https://api.crawl4ai.com/v1/scrape"
    body = mock_requests.post.call_args.kwargs["json"]
    assert body["url"] == "https://example.com/docs"
    assert body["fit"] is True


@patch("ibkr_core_mcp.crawl4ai_cloud.requests")
def test_scrape_honors_a_custom_base_url(mock_requests):
    mock_requests.post.return_value = _resp(body={"success": True, "markdown": "# hi"})

    _client(base_url="https://staging.example/").scrape("https://example.com/docs")

    assert mock_requests.post.call_args.args[0] == "https://staging.example/v1/scrape"


@patch("ibkr_core_mcp.crawl4ai_cloud.requests")
def test_scrape_omits_proxy_entirely_when_unset(mock_requests):
    """Passing proxy:"direct" is a 422 — the no-proxy request must omit the key."""
    mock_requests.post.return_value = _resp(body={"success": True, "markdown": "# hi"})

    _client().scrape("https://example.com/docs")

    assert "proxy" not in mock_requests.post.call_args.kwargs["json"]


@patch("ibkr_core_mcp.crawl4ai_cloud.requests")
def test_scrape_sends_proxy_as_an_object_when_set(mock_requests):
    """proxy is an object here, unlike Firecrawl where it is a string."""
    mock_requests.post.return_value = _resp(body={"success": True, "markdown": "# hi"})

    _client().scrape("https://example.com/docs", proxy_mode="residential", proxy_country="US")

    assert mock_requests.post.call_args.kwargs["json"]["proxy"] == {"mode": "residential", "country": "US"}


@patch("ibkr_core_mcp.crawl4ai_cloud.requests")
def test_scrape_omits_proxy_country_when_not_given(mock_requests):
    mock_requests.post.return_value = _resp(body={"success": True, "markdown": "# hi"})

    _client().scrape("https://example.com/docs", proxy_mode="datacenter")

    assert mock_requests.post.call_args.kwargs["json"]["proxy"] == {"mode": "datacenter"}


# A real dry-run response, captured live 2026-07-28. Note what it does NOT have: a
# `success` key, or a `markdown` key. It is a pricing quote, not a page — which is why
# estimate() is a separate method rather than a mode flag on scrape().
_DRY_RUN_BODY = {
    "service": "scrape",
    "credits": "1.0000",
    "credits_exact": True,
    "breakdown": [{"service": "scrape", "action": "url_fetch", "credits": "1.0000"}],
    "dry_run": True,
    "covered_by_balance": True,
}


@patch("ibkr_core_mcp.crawl4ai_cloud.requests")
def test_estimate_sends_dry_run_and_returns_the_quote(mock_requests):
    mock_requests.post.return_value = _resp(body=_DRY_RUN_BODY)

    quote = _client().estimate("https://example.com/docs")

    assert mock_requests.post.call_args.kwargs["json"]["dry_run"] is True
    assert quote["credits"] == "1.0000"


@patch("ibkr_core_mcp.crawl4ai_cloud.requests")
def test_estimate_does_not_demand_a_success_key(mock_requests):
    """The live dry-run body has no `success` field — treating its absence as failure
    made estimate() raise on every real call. Caught by the live suite, not this one."""
    mock_requests.post.return_value = _resp(body=_DRY_RUN_BODY)

    _client().estimate("https://example.com/docs")  # must not raise


@patch("ibkr_core_mcp.crawl4ai_cloud.requests")
def test_estimate_carries_the_proxy_object_through(mock_requests):
    mock_requests.post.return_value = _resp(body=_DRY_RUN_BODY)

    _client().estimate("https://example.com/docs", proxy_mode="residential", proxy_country="US")

    assert mock_requests.post.call_args.kwargs["json"]["proxy"] == {"mode": "residential", "country": "US"}


@patch("ibkr_core_mcp.crawl4ai_cloud.requests")
def test_scrape_never_sends_dry_run(mock_requests):
    """A scrape that quietly priced itself instead of fetching would return an empty page."""
    mock_requests.post.return_value = _resp(body={"success": True, "markdown": "# hi"})

    _client().scrape("https://example.com/docs")

    assert "dry_run" not in mock_requests.post.call_args.kwargs["json"]


# ============================================================================
# Response mapping
# ============================================================================


@patch("ibkr_core_mcp.crawl4ai_cloud.requests")
def test_scrape_returns_the_shared_page_dict_shape(mock_requests):
    """The ladder and WebDocsStore.save_crawl both consume {"url","markdown","metadata"}."""
    mock_requests.post.return_value = _resp(
        body={"success": True, "url": "https://example.com/docs", "markdown": "# Real content"}
    )

    page = _client().scrape("https://example.com/docs")

    assert page == {"url": "https://example.com/docs", "markdown": "# Real content", "metadata": {}}


@patch("ibkr_core_mcp.crawl4ai_cloud.requests")
def test_scrape_falls_back_to_fit_markdown_when_markdown_is_empty(mock_requests):
    mock_requests.post.return_value = _resp(
        body={"success": True, "url": "https://example.com/docs", "markdown": "", "fit_markdown": "# Pruned"}
    )

    assert _client().scrape("https://example.com/docs")["markdown"] == "# Pruned"


@patch("ibkr_core_mcp.crawl4ai_cloud.requests")
def test_scrape_uses_the_requested_url_when_the_response_omits_one(mock_requests):
    mock_requests.post.return_value = _resp(body={"success": True, "markdown": "# hi"})

    assert _client().scrape("https://example.com/docs")["url"] == "https://example.com/docs"


@patch("ibkr_core_mcp.crawl4ai_cloud.requests")
def test_scrape_raises_when_the_body_reports_failure(mock_requests):
    """HTTP 200 with success:false is a real failure mode and must not look like an empty page."""
    from ibkr_core_mcp.crawl4ai_cloud import Crawl4AICloudError

    mock_requests.post.return_value = _resp(body={"success": False, "error_message": "page returned no HTML"})

    with pytest.raises(Crawl4AICloudError, match="page returned no HTML"):
        _client().scrape("https://example.com/docs")


# ============================================================================
# Error mapping — the 429 trap
# ============================================================================


@pytest.mark.parametrize(
    ("status", "expected"),
    [(401, "API key"), (402, "credit"), (429, "quota"), (422, "422"), (500, "500")],
)
@patch("ibkr_core_mcp.crawl4ai_cloud.requests")
def test_scrape_maps_http_errors_to_typed_error_with_status_code(mock_requests, status, expected):
    from ibkr_core_mcp.crawl4ai_cloud import Crawl4AICloudError

    mock_requests.post.return_value = _resp(status=status)

    with pytest.raises(Crawl4AICloudError, match=expected) as excinfo:
        _client().scrape("https://example.com/docs")
    assert excinfo.value.status_code == status


@patch("ibkr_core_mcp.crawl4ai_cloud.requests")
def test_scrape_does_not_retry_a_429(mock_requests):
    """429 is quota exhaustion here, not backpressure — retrying burns the daily budget to fail."""
    from ibkr_core_mcp.crawl4ai_cloud import Crawl4AICloudError

    mock_requests.post.return_value = _resp(status=429)

    with pytest.raises(Crawl4AICloudError):
        _client().scrape("https://example.com/docs")

    assert mock_requests.post.call_count == 1


@patch("ibkr_core_mcp.crawl4ai_cloud.requests")
def test_scrape_does_not_retry_a_server_error_either(mock_requests):
    """No retry path exists at all in this client — one call in, one result out."""
    from ibkr_core_mcp.crawl4ai_cloud import Crawl4AICloudError

    mock_requests.post.return_value = _resp(status=503)

    with pytest.raises(Crawl4AICloudError):
        _client().scrape("https://example.com/docs")

    assert mock_requests.post.call_count == 1


@patch("ibkr_core_mcp.crawl4ai_cloud.requests")
def test_scrape_never_puts_the_api_key_in_an_error_message(mock_requests):
    from ibkr_core_mcp.crawl4ai_cloud import Crawl4AICloudError

    mock_requests.post.return_value = _resp(status=401)

    with pytest.raises(Crawl4AICloudError) as excinfo:
        _client(api_key="sk_live_supersecret").scrape("https://example.com/docs")
    assert "sk_live_supersecret" not in str(excinfo.value)


# ============================================================================
# Quota surfacing
# ============================================================================

# Live /v1/usage shape, verified 2026-07-28. Note this is NOT the shape in the vendor's
# own llms-full.txt, which documents crawl.credits_daily_limit / crawl.credits_remaining_today
# — those keys do not exist on the live response.
_USAGE_BODY = {
    "plan": {"name": "free", "daily_credits": 50, "rate_per_minute": 10, "concurrent": 1},
    "credits": {"used_today": 0, "remaining_today": 50, "daily_limit": 50},
}


@patch("ibkr_core_mcp.crawl4ai_cloud.requests")
def test_scrape_records_credits_remaining_from_the_response_body(mock_requests):
    """The scrape response already carries the balance — no extra call needed to read it."""
    mock_requests.post.return_value = _resp(
        body={"success": True, "markdown": "# hi", "usage": {"credits_used": 1.0, "credits_remaining": 47.0}}
    )

    client = _client()
    assert client.last_credits_remaining is None
    client.scrape("https://example.com/docs")
    assert client.last_credits_remaining == 47.0


@patch("ibkr_core_mcp.crawl4ai_cloud.requests")
def test_scrape_never_logs_the_bodys_credits_used_field(mock_requests, caplog):
    """usage.credits_used is not what the call actually cost.

    Measured live 2026-07-28: a no-proxy scrape reported credits_used: 5.0 while the
    /v1/usage ledger moved by exactly 1. credits_remaining agreed with the ledger; this
    field did not. Both planning documents' "some operations cost 5 credits" budget came
    from reading it. Log only what is true.
    """
    mock_requests.post.return_value = _resp(
        body={"success": True, "markdown": "# hi", "usage": {"credits_used": 5.0, "credits_remaining": 46.0}}
    )

    with caplog.at_level("INFO"):
        _client().scrape("https://example.com/docs")

    logged = " | ".join(r.getMessage() for r in caplog.records)
    assert "46.0" in logged, "the trustworthy field must still be reported"
    assert "5.0" not in logged, f"credits_used leaked into a log line: {logged}"


@patch("ibkr_core_mcp.crawl4ai_cloud.requests")
def test_scrape_leaves_credits_remaining_none_when_the_body_omits_usage(mock_requests):
    mock_requests.post.return_value = _resp(body={"success": True, "markdown": "# hi"})

    client = _client()
    client.scrape("https://example.com/docs")
    assert client.last_credits_remaining is None


@patch("ibkr_core_mcp.crawl4ai_cloud.requests")
def test_low_balance_warning_is_relative_to_the_reported_allowance(mock_requests, caplog):
    """9 of 50 is under a fifth and warns; the threshold is read from the API, never hardcoded."""
    mock_requests.get.return_value = _resp(body=_USAGE_BODY)
    mock_requests.post.return_value = _resp(
        body={"success": True, "markdown": "# hi", "usage": {"credits_remaining": 9.0}}
    )

    with caplog.at_level("WARNING"):
        _client().scrape("https://example.com/docs")

    assert any("credit" in r.message.lower() for r in caplog.records if r.levelname == "WARNING")


@patch("ibkr_core_mcp.crawl4ai_cloud.requests")
def test_no_low_balance_warning_when_comfortably_above_the_threshold(mock_requests, caplog):
    mock_requests.get.return_value = _resp(body=_USAGE_BODY)
    mock_requests.post.return_value = _resp(
        body={"success": True, "markdown": "# hi", "usage": {"credits_remaining": 40.0}}
    )

    with caplog.at_level("WARNING"):
        _client().scrape("https://example.com/docs")

    assert [r for r in caplog.records if r.levelname == "WARNING"] == []


@patch("ibkr_core_mcp.crawl4ai_cloud.requests")
def test_a_large_plan_warns_at_a_balance_an_absolute_threshold_would_ignore(mock_requests, caplog):
    """500 of 5000/day is under a fifth and must warn.

    This is the test that fails if anyone reintroduces a hardcoded "warn under 10":
    500 sails past any small absolute floor while being genuinely low for this plan.
    It is the *upgrade* direction — the one §2b of the plan exists to protect.
    """
    mock_requests.get.return_value = _resp(
        body={"plan": {"name": "pro", "daily_credits": 5000}, "credits": {"daily_limit": 5000}}
    )
    mock_requests.post.return_value = _resp(
        body={"success": True, "markdown": "# hi", "usage": {"credits_remaining": 500.0}}
    )

    with caplog.at_level("WARNING"):
        _client().scrape("https://example.com/docs")

    assert any("credit" in r.message.lower() for r in caplog.records if r.levelname == "WARNING")


@patch("ibkr_core_mcp.crawl4ai_cloud.requests")
def test_allowance_is_fetched_once_and_reused_across_scrapes(mock_requests):
    """/v1/usage costs a request against a per-minute limit — poll it once per client, not per scrape."""
    mock_requests.get.return_value = _resp(body=_USAGE_BODY)
    mock_requests.post.return_value = _resp(
        body={"success": True, "markdown": "# hi", "usage": {"credits_remaining": 9.0}}
    )

    client = _client()
    client.scrape("https://example.com/a")
    client.scrape("https://example.com/b")
    client.scrape("https://example.com/c")

    assert mock_requests.get.call_count == 1


@patch("ibkr_core_mcp.crawl4ai_cloud.requests")
def test_a_failing_usage_lookup_never_breaks_a_successful_scrape(mock_requests):
    """Quota reporting is a nicety; losing it must not lose the page the ladder just rescued."""
    mock_requests.get.side_effect = requests.RequestException("usage endpoint down")
    mock_requests.post.return_value = _resp(
        body={"success": True, "markdown": "# Real content", "usage": {"credits_remaining": 1.0}}
    )

    page = _client().scrape("https://example.com/docs")

    assert page["markdown"] == "# Real content"


@patch("ibkr_core_mcp.crawl4ai_cloud.requests")
def test_usage_returns_the_parsed_plan_and_credit_blocks(mock_requests):
    mock_requests.get.return_value = _resp(body=_USAGE_BODY)

    usage = _client().usage()

    assert mock_requests.get.call_args.args[0] == "https://api.crawl4ai.com/v1/usage"
    assert usage["plan"]["daily_credits"] == 50
    assert usage["credits"]["remaining_today"] == 50
