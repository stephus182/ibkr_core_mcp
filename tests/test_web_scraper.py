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


# ── FirecrawlClient.crawl ─────────────────────────────────────────────────────

@patch("ibkr_core_mcp.web_scraper.time")
@patch("ibkr_core_mcp.web_scraper.requests")
def test_crawl_polls_until_completed(mock_requests, mock_time):
    from ibkr_core_mcp.web_scraper import FirecrawlClient
    # monotonic: deadline=0+120=120; first while check=1 (enter); after poll status=completed → exit
    mock_time.monotonic.side_effect = [0.0, 1.0, 2.0]

    start_resp = MagicMock()
    start_resp.status_code = 200
    start_resp.json.return_value = {"id": "job-123"}

    poll1 = MagicMock()
    poll1.status_code = 200
    poll1.json.return_value = {"status": "scraping", "data": []}

    poll2 = MagicMock()
    poll2.status_code = 200
    poll2.json.return_value = {
        "status": "completed",
        "data": [
            {"metadata": {"sourceURL": "https://example.com/page"}, "markdown": "# Page"}
        ],
    }

    mock_requests.post.return_value = start_resp
    mock_requests.get.side_effect = [poll1, poll2]

    client = FirecrawlClient("fc-test")
    pages = client.crawl("https://example.com", timeout_s=120)
    assert len(pages) == 1
    assert pages[0]["url"] == "https://example.com/page"
    assert pages[0]["markdown"] == "# Page"


@patch("ibkr_core_mcp.web_scraper.time")
@patch("ibkr_core_mcp.web_scraper.requests")
def test_crawl_failed_status_raises(mock_requests, mock_time):
    from ibkr_core_mcp.web_scraper import FirecrawlClient, FirecrawlError
    mock_time.monotonic.side_effect = [0.0, 1.0]

    start_resp = MagicMock()
    start_resp.status_code = 200
    start_resp.json.return_value = {"id": "job-fail"}

    fail_poll = MagicMock()
    fail_poll.status_code = 200
    fail_poll.json.return_value = {"status": "failed", "error": "blocked by robots.txt"}

    mock_requests.post.return_value = start_resp
    mock_requests.get.return_value = fail_poll

    client = FirecrawlClient("fc-test")
    with pytest.raises(FirecrawlError, match="Crawl job failed"):
        client.crawl("https://example.com")


@patch("ibkr_core_mcp.web_scraper.time")
@patch("ibkr_core_mcp.web_scraper.requests")
def test_crawl_timeout_returns_partial_results(mock_requests, mock_time):
    from ibkr_core_mcp.web_scraper import FirecrawlClient
    # deadline = 0.0 + 10 = 10; first while check = 5.0 (enter loop); second = 200.0 (exit)
    mock_time.monotonic.side_effect = [0.0, 5.0, 200.0]

    start_resp = MagicMock()
    start_resp.status_code = 200
    start_resp.json.return_value = {"id": "job-slow"}

    partial_poll = MagicMock()
    partial_poll.status_code = 200
    partial_poll.json.return_value = {
        "status": "scraping",
        "data": [
            {"metadata": {"sourceURL": "https://example.com/p1"}, "markdown": "partial content"}
        ],
    }

    mock_requests.post.return_value = start_resp
    mock_requests.get.return_value = partial_poll

    client = FirecrawlClient("fc-test")
    pages = client.crawl("https://example.com", timeout_s=10)
    # Returns partial — does not raise
    assert len(pages) == 1
    assert pages[0]["markdown"] == "partial content"


@patch("ibkr_core_mcp.web_scraper.time")
@patch("ibkr_core_mcp.web_scraper.requests")
def test_crawl_skips_pages_with_empty_markdown(mock_requests, mock_time):
    from ibkr_core_mcp.web_scraper import FirecrawlClient
    mock_time.monotonic.side_effect = [0.0, 1.0]

    start_resp = MagicMock()
    start_resp.status_code = 200
    start_resp.json.return_value = {"id": "job-empty"}

    poll = MagicMock()
    poll.status_code = 200
    poll.json.return_value = {
        "status": "completed",
        "data": [
            {"metadata": {"sourceURL": "https://example.com/a"}, "markdown": "# Real"},
            {"metadata": {"sourceURL": "https://example.com/b"}, "markdown": ""},
            {"metadata": {"sourceURL": "https://example.com/c"}, "markdown": None},
        ],
    }

    mock_requests.post.return_value = start_resp
    mock_requests.get.return_value = poll

    client = FirecrawlClient("fc-test")
    pages = client.crawl("https://example.com")
    assert len(pages) == 1
    assert pages[0]["url"] == "https://example.com/a"


@patch("ibkr_core_mcp.web_scraper.time")
@patch("ibkr_core_mcp.web_scraper.requests")
def test_crawl_max_pages_clamped(mock_requests, mock_time):
    from ibkr_core_mcp.web_scraper import FirecrawlClient
    mock_time.monotonic.side_effect = [0.0, 1.0]
    start_resp = MagicMock()
    start_resp.status_code = 200
    start_resp.json.return_value = {"id": "job-clamp"}
    poll = MagicMock()
    poll.status_code = 200
    poll.json.return_value = {"status": "completed", "data": []}
    mock_requests.post.return_value = start_resp
    mock_requests.get.return_value = poll

    client = FirecrawlClient("fc-test")
    client.crawl("https://example.com", max_pages=9999)
    payload = mock_requests.post.call_args[1]["json"]
    assert payload["limit"] == 100


# ── WebDocsStore — Drive service and folder helpers ───────────────────────────

def _make_cfg_with_drive(tmp_path):
    """Helper: Config with dummy Drive creds pointing to tmp files."""
    from ibkr_core_mcp.config import Config
    token = tmp_path / "token.json"
    creds_file = tmp_path / "credentials.json"
    token.write_text('{"token": "tok", "refresh_token": "r", "token_uri": "u", "client_id": "c", "client_secret": "s", "scopes": ["https://www.googleapis.com/auth/drive"]}')
    creds_file.write_text('{}')
    return Config(
        gateway_url="http://localhost",
        anthropic_api_key="sk-test",
        gdrive_folder_id="root-folder-id",
        sqlite_path=tmp_path / "store.db",
        gdrive_token_file=token,
        gdrive_credentials_file=creds_file,
        gdrive_web_docs_folder_id="",
    )


@patch("ibkr_core_mcp.web_scraper.Credentials")
@patch("ibkr_core_mcp.web_scraper.build")
def test_get_service_returns_drive_service(mock_build, mock_creds_cls, tmp_path):
    from ibkr_core_mcp.web_scraper import WebDocsStore
    cfg = _make_cfg_with_drive(tmp_path)
    mock_creds = MagicMock()
    mock_creds.valid = True
    mock_creds_cls.from_authorized_user_file.return_value = mock_creds
    mock_svc = MagicMock()
    mock_build.return_value = mock_svc

    store = WebDocsStore(cfg)
    svc = store._get_service()
    assert svc is mock_svc
    mock_build.assert_called_once_with("drive", "v3", credentials=mock_creds)


@patch("ibkr_core_mcp.web_scraper.Credentials")
@patch("ibkr_core_mcp.web_scraper.build")
def test_get_service_cached(mock_build, mock_creds_cls, tmp_path):
    from ibkr_core_mcp.web_scraper import WebDocsStore
    cfg = _make_cfg_with_drive(tmp_path)
    mock_creds = MagicMock()
    mock_creds.valid = True
    mock_creds_cls.from_authorized_user_file.return_value = mock_creds
    mock_build.return_value = MagicMock()

    store = WebDocsStore(cfg)
    svc1 = store._get_service()
    svc2 = store._get_service()
    assert svc1 is svc2
    mock_build.assert_called_once()  # cached after first call


@patch("ibkr_core_mcp.web_scraper.Credentials")
@patch("ibkr_core_mcp.web_scraper.build")
def test_find_or_create_folder_finds_existing(mock_build, mock_creds_cls, tmp_path):
    from ibkr_core_mcp.web_scraper import WebDocsStore
    cfg = _make_cfg_with_drive(tmp_path)
    mock_creds = MagicMock()
    mock_creds.valid = True
    mock_creds_cls.from_authorized_user_file.return_value = mock_creds

    mock_svc = MagicMock()
    mock_build.return_value = mock_svc
    mock_svc.files().list().execute.return_value = {
        "files": [{"id": "existing-folder-id"}]
    }

    store = WebDocsStore(cfg)
    fid = store._find_or_create_folder("web_docs", "root-folder-id")
    assert fid == "existing-folder-id"
    mock_svc.files().create.assert_not_called()


@patch("ibkr_core_mcp.web_scraper.Credentials")
@patch("ibkr_core_mcp.web_scraper.build")
def test_find_or_create_folder_creates_when_missing(mock_build, mock_creds_cls, tmp_path):
    from ibkr_core_mcp.web_scraper import WebDocsStore
    cfg = _make_cfg_with_drive(tmp_path)
    mock_creds = MagicMock()
    mock_creds.valid = True
    mock_creds_cls.from_authorized_user_file.return_value = mock_creds

    mock_svc = MagicMock()
    mock_build.return_value = mock_svc
    mock_svc.files().list().execute.return_value = {"files": []}
    mock_svc.files().create().execute.return_value = {"id": "new-folder-id"}

    store = WebDocsStore(cfg)
    fid = store._find_or_create_folder("web_docs", "root-folder-id")
    assert fid == "new-folder-id"
    mock_svc.files().create.assert_called()


@patch("ibkr_core_mcp.web_scraper.Credentials")
@patch("ibkr_core_mcp.web_scraper.build")
def test_get_web_docs_folder_uses_config_override(mock_build, mock_creds_cls, tmp_path):
    from ibkr_core_mcp.web_scraper import WebDocsStore
    from ibkr_core_mcp.config import Config
    token = tmp_path / "token.json"
    creds_file = tmp_path / "credentials.json"
    token.write_text('{"token": "tok", "refresh_token": "r", "token_uri": "u", "client_id": "c", "client_secret": "s", "scopes": ["https://www.googleapis.com/auth/drive"]}')
    creds_file.write_text('{}')
    cfg = Config(
        gateway_url="http://localhost",
        anthropic_api_key="sk-test",
        gdrive_folder_id="root-folder-id",
        sqlite_path=tmp_path / "store.db",
        gdrive_token_file=token,
        gdrive_credentials_file=creds_file,
        gdrive_web_docs_folder_id="override-folder-id",
    )
    mock_creds = MagicMock()
    mock_creds.valid = True
    mock_creds_cls.from_authorized_user_file.return_value = mock_creds
    mock_build.return_value = MagicMock()

    store = WebDocsStore(cfg)
    fid = store._get_web_docs_folder_id()
    assert fid == "override-folder-id"
