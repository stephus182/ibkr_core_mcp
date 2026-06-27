import pytest


# ── _slugify ──────────────────────────────────────────────────────────────────

def test_slugify_strips_scheme_and_lowercases():
    from ibkr_core_mcp.web_scraper import _slugify
    result = _slugify("https://DOCS.EXAMPLE.COM/Foo/Bar")
    assert result == "docs-example-com-foo-bar"


def test_slugify_ibkr_campus_url():
    from ibkr_core_mcp.web_scraper import _slugify
    result = _slugify(
        "https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/"
    )
    assert result == "www-interactivebrokers-com-campus-ibkr-api-page-cpapi-v1"


def test_slugify_truncates_to_100_chars():
    from ibkr_core_mcp.web_scraper import _slugify
    long_url = "https://example.com/" + "a" * 200
    assert len(_slugify(long_url)) <= 100


def test_slugify_no_path_traversal():
    from ibkr_core_mcp.web_scraper import _slugify
    result = _slugify("https://example.com/../../../etc/passwd")
    assert ".." not in result
    assert "/" not in result
    assert "\\" not in result


def test_slugify_no_leading_trailing_hyphens():
    from ibkr_core_mcp.web_scraper import _slugify
    result = _slugify("https://example.com/")
    assert not result.startswith("-")
    assert not result.endswith("-")


# ── Exceptions ────────────────────────────────────────────────────────────────

def test_firecrawl_error_stores_status_code():
    from ibkr_core_mcp.web_scraper import FirecrawlError
    err = FirecrawlError("bad key", 401)
    assert err.status_code == 401
    assert str(err) == "bad key"


def test_firecrawl_error_status_code_optional():
    from ibkr_core_mcp.web_scraper import FirecrawlError
    err = FirecrawlError("network failure")
    assert err.status_code is None


def test_web_docs_store_error_chains_cause():
    from ibkr_core_mcp.web_scraper import WebDocsStoreError
    cause = RuntimeError("drive down")
    try:
        raise WebDocsStoreError("save failed") from cause
    except WebDocsStoreError as e:
        assert e.__cause__ is cause


# ── FirecrawlClient.search ────────────────────────────────────────────────────

from unittest.mock import MagicMock, patch


def test_firecrawl_client_rejects_empty_api_key():
    from ibkr_core_mcp.web_scraper import FirecrawlClient
    with pytest.raises(ValueError, match="api_key"):
        FirecrawlClient("")


@patch("ibkr_core_mcp.web_scraper.requests")
def test_search_returns_formatted_results(mock_requests):
    from ibkr_core_mcp.web_scraper import FirecrawlClient
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": [
            {"url": "https://example.com", "title": "Example", "markdown": "# Hello"}
        ]
    }
    mock_requests.post.return_value = mock_resp
    client = FirecrawlClient("fc-test")
    results = client.search("test query", limit=1)
    assert len(results) == 1
    assert results[0]["url"] == "https://example.com"
    assert results[0]["title"] == "Example"
    assert results[0]["markdown"] == "# Hello"
    mock_requests.post.assert_called_once()
    call_kwargs = mock_requests.post.call_args
    assert "/search" in call_kwargs[0][0]
    assert call_kwargs[1]["json"]["scrapeOptions"] == {"formats": ["markdown"]}


@patch("ibkr_core_mcp.web_scraper.requests")
def test_search_401_raises_firecrawl_error(mock_requests):
    from ibkr_core_mcp.web_scraper import FirecrawlClient, FirecrawlError
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_requests.post.return_value = mock_resp
    client = FirecrawlClient("fc-bad")
    with pytest.raises(FirecrawlError) as exc_info:
        client.search("query")
    assert exc_info.value.status_code == 401
    assert "FIRECRAWL_API_KEY" in str(exc_info.value)


@patch("ibkr_core_mcp.web_scraper.requests")
def test_search_429_raises_rate_limit(mock_requests):
    from ibkr_core_mcp.web_scraper import FirecrawlClient, FirecrawlError
    mock_resp = MagicMock()
    mock_resp.status_code = 429
    mock_requests.post.return_value = mock_resp
    client = FirecrawlClient("fc-test")
    with pytest.raises(FirecrawlError) as exc_info:
        client.search("query")
    assert exc_info.value.status_code == 429


@patch("ibkr_core_mcp.web_scraper.requests")
def test_search_5xx_raises_service_error(mock_requests):
    from ibkr_core_mcp.web_scraper import FirecrawlClient, FirecrawlError
    mock_resp = MagicMock()
    mock_resp.status_code = 503
    mock_requests.post.return_value = mock_resp
    client = FirecrawlClient("fc-test")
    with pytest.raises(FirecrawlError) as exc_info:
        client.search("query")
    assert exc_info.value.status_code == 503


def test_search_empty_query_raises():
    from ibkr_core_mcp.web_scraper import FirecrawlClient
    client = FirecrawlClient("fc-test")
    with pytest.raises(ValueError, match="query"):
        client.search("")


@patch("ibkr_core_mcp.web_scraper.requests")
def test_search_limit_clamped_to_10(mock_requests):
    from ibkr_core_mcp.web_scraper import FirecrawlClient
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": []}
    mock_requests.post.return_value = mock_resp
    client = FirecrawlClient("fc-test")
    client.search("query", limit=999)
    payload = mock_requests.post.call_args[1]["json"]
    assert payload["limit"] == 10
