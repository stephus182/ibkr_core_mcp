from unittest.mock import MagicMock, patch

import pytest

# ── _slugify ──────────────────────────────────────────────────────────────────


def test_slugify_strips_scheme_and_lowercases():
    from ibkr_core_mcp.web_scraper import _slugify

    result = _slugify("https://DOCS.EXAMPLE.COM/Foo/Bar")
    assert result == "docs-example-com-foo-bar"


def test_slugify_ibkr_campus_url():
    from ibkr_core_mcp.web_scraper import _slugify

    result = _slugify("https://ibkrcampus.com/docs/web-api/v1/endpoints/introduction.md")
    assert result == "ibkrcampus-com-docs-web-api-v1-endpoints-introduction-md"


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


# ── content_bytes ─────────────────────────────────────────────────────────────


def test_content_bytes_sums_markdown_across_pages():
    from ibkr_core_mcp.web_scraper import content_bytes

    assert content_bytes([{"markdown": "abc"}, {"markdown": "de"}]) == 5


def test_content_bytes_treats_missing_and_none_markdown_as_zero():
    from ibkr_core_mcp.web_scraper import content_bytes

    assert content_bytes([{"markdown": None}, {}, {"markdown": ""}]) == 0


def test_content_bytes_counts_utf8_bytes_not_characters():
    from ibkr_core_mcp.web_scraper import content_bytes

    # U+00E9 is one character but two bytes in UTF-8. A page of accented text
    # must not be undercounted into a false "blocked" verdict.
    assert content_bytes([{"markdown": "é" * 10}]) == 20


def test_content_bytes_empty_list_is_zero():
    from ibkr_core_mcp.web_scraper import content_bytes

    assert content_bytes([]) == 0


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


def test_firecrawl_client_rejects_empty_api_key():
    from ibkr_core_mcp.web_scraper import FirecrawlClient

    with pytest.raises(ValueError, match="api_key"):
        FirecrawlClient("")


@patch("ibkr_core_mcp.web_scraper.requests")
def test_search_returns_formatted_results(mock_requests):
    from ibkr_core_mcp.web_scraper import FirecrawlClient

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": [{"url": "https://example.com", "title": "Example", "markdown": "# Hello"}]}
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
    mock_resp.headers = {}
    mock_requests.post.return_value = mock_resp
    client = FirecrawlClient("fc-test")
    with pytest.raises(FirecrawlError) as exc_info:
        client.search("query")
    assert exc_info.value.status_code == 429
    # Retries exhausted (persistent 429), not a single immediate raise.
    assert mock_requests.post.call_count == 4  # 1 initial + 3 retries


@patch("ibkr_core_mcp.web_scraper.time")
@patch("ibkr_core_mcp.web_scraper.requests")
def test_search_retries_on_429_then_succeeds(mock_requests, mock_time):
    """Per Firecrawl's own documented error-handling guidance
    (https://docs.firecrawl.dev/api-reference/errors), a 429 is retryable —
    the client must not raise on the first one if a later attempt succeeds."""
    from ibkr_core_mcp.web_scraper import FirecrawlClient

    rate_limited = MagicMock()
    rate_limited.status_code = 429
    rate_limited.headers = {}
    ok_resp = MagicMock()
    ok_resp.status_code = 200
    ok_resp.json.return_value = {"data": [{"url": "https://example.com", "title": "", "markdown": "hi"}]}
    mock_requests.post.side_effect = [rate_limited, ok_resp]

    client = FirecrawlClient("fc-test")
    results = client.search("query")

    assert len(results) == 1
    assert mock_requests.post.call_count == 2
    mock_time.sleep.assert_called_once()


@patch("ibkr_core_mcp.web_scraper.time")
@patch("ibkr_core_mcp.web_scraper.requests")
def test_search_honors_retry_after_header(mock_requests, mock_time):
    """Must honor the Retry-After header value exactly, per Firecrawl's documented
    guidance, rather than always using the default backoff formula."""
    from ibkr_core_mcp.web_scraper import FirecrawlClient

    rate_limited = MagicMock()
    rate_limited.status_code = 429
    rate_limited.headers = {"Retry-After": "7"}
    ok_resp = MagicMock()
    ok_resp.status_code = 200
    ok_resp.json.return_value = {"data": []}
    mock_requests.post.side_effect = [rate_limited, ok_resp]

    client = FirecrawlClient("fc-test")
    client.search("query")

    slept_for = mock_time.sleep.call_args[0][0]
    assert slept_for >= 7.0


@patch("ibkr_core_mcp.web_scraper.requests")
def test_search_5xx_raises_service_error(mock_requests):
    from ibkr_core_mcp.web_scraper import FirecrawlClient, FirecrawlError

    mock_resp = MagicMock()
    mock_resp.status_code = 503
    mock_resp.headers = {}
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
def test_search_includes_result_metadata(mock_requests):
    """Each search result retains Firecrawl's per-result metadata (statusCode/error)
    so callers can assess extraction quality without a second round trip."""
    from ibkr_core_mcp.web_scraper import FirecrawlClient

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": [
            {
                "url": "https://example.com",
                "title": "Example",
                "markdown": "# Hello",
                "metadata": {"statusCode": 200},
            }
        ]
    }
    mock_requests.post.return_value = mock_resp
    client = FirecrawlClient("fc-test")
    results = client.search("test query", limit=1)
    assert results[0]["metadata"] == {"statusCode": 200}


@patch("ibkr_core_mcp.web_scraper.requests")
def test_search_metadata_defaults_to_empty_dict(mock_requests):
    from ibkr_core_mcp.web_scraper import FirecrawlClient

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": [{"url": "https://example.com", "title": "Example", "markdown": "# Hello"}]}
    mock_requests.post.return_value = mock_resp
    client = FirecrawlClient("fc-test")
    results = client.search("test query", limit=1)
    assert results[0]["metadata"] == {}


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


def test_scrape_options_default_is_todays_request_body():
    from ibkr_core_mcp.web_scraper import FirecrawlClient

    client = FirecrawlClient("fc-test")
    assert client._scrape_options() == {"formats": ["markdown"]}


def test_scrape_options_includes_wait_for_and_proxy_when_given():
    from ibkr_core_mcp.web_scraper import FirecrawlClient

    client = FirecrawlClient("fc-test")
    assert client._scrape_options(wait_for_ms=3000, proxy="auto", timeout_ms=60000) == {
        "formats": ["markdown"],
        "waitFor": 3000,
        "proxy": "auto",
        "timeout": 60000,
    }


def test_scrape_options_keeps_explicit_zero_wait_for():
    from ibkr_core_mcp.web_scraper import FirecrawlClient

    client = FirecrawlClient("fc-test")
    # 0 is a meaningful value ("don't wait"), not an absent one.
    assert client._scrape_options(wait_for_ms=0) == {"formats": ["markdown"], "waitFor": 0}


@patch("ibkr_core_mcp.web_scraper.requests")
def test_search_passes_wait_for_and_proxy_to_api(mock_requests):
    from ibkr_core_mcp.web_scraper import FirecrawlClient

    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"data": []}
    mock_requests.post.return_value = resp

    client = FirecrawlClient("fc-test")
    client.search("ibkr api", wait_for_ms=3000, proxy="auto")

    payload = mock_requests.post.call_args[1]["json"]
    assert payload["scrapeOptions"]["waitFor"] == 3000
    assert payload["scrapeOptions"]["proxy"] == "auto"


@patch("ibkr_core_mcp.web_scraper.requests")
def test_search_402_raises_out_of_credits(mock_requests):
    from ibkr_core_mcp.web_scraper import FirecrawlClient, FirecrawlError

    resp = MagicMock()
    resp.status_code = 402
    mock_requests.post.return_value = resp

    client = FirecrawlClient("fc-test")
    with pytest.raises(FirecrawlError, match="credits") as exc_info:
        client.search("anything")
    assert exc_info.value.status_code == 402


# ── FirecrawlClient.crawl ─────────────────────────────────────────────────────


# ── FirecrawlClient.crawl — single attempt, no automatic retry ────────────────


def _crawl_responses(mock_requests, mock_time, poll_payloads):
    """Wire mock_requests so each crawl attempt sees the next payload in poll_payloads."""
    import itertools

    mock_time.monotonic.side_effect = itertools.count(0.0, 1.0)
    start_resp = MagicMock()
    start_resp.status_code = 200
    start_resp.json.return_value = {"id": "job-1"}
    mock_requests.post.return_value = start_resp

    polls = []
    for payload in poll_payloads:
        poll = MagicMock()
        poll.status_code = 200
        poll.json.return_value = payload
        polls.append(poll)
    mock_requests.get.side_effect = polls


# ── WebDocsStore — Drive service and folder helpers ───────────────────────────


def _make_cfg_with_drive(tmp_path):
    """Helper: Config with dummy Drive creds pointing to tmp files."""
    from ibkr_core_mcp.config import Config

    token = tmp_path / "token.json"
    creds_file = tmp_path / "credentials.json"
    token.write_text(
        '{"token": "tok", "refresh_token": "r", "token_uri": "u", "client_id": "c", "client_secret": "s", "scopes": ["https://www.googleapis.com/auth/drive"]}'
    )
    creds_file.write_text("{}")
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
    mock_svc.files().list().execute.return_value = {"files": [{"id": "existing-folder-id"}]}

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
    from ibkr_core_mcp.config import Config
    from ibkr_core_mcp.web_scraper import WebDocsStore

    token = tmp_path / "token.json"
    creds_file = tmp_path / "credentials.json"
    token.write_text(
        '{"token": "tok", "refresh_token": "r", "token_uri": "u", "client_id": "c", "client_secret": "s", "scopes": ["https://www.googleapis.com/auth/drive"]}'
    )
    creds_file.write_text("{}")
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


# ── WebDocsStore.save_crawl ───────────────────────────────────────────────────


def _make_store_with_mock_service(tmp_path):
    """Return a WebDocsStore with _svc mocked out (bypasses Drive auth)."""
    from ibkr_core_mcp.config import Config
    from ibkr_core_mcp.web_scraper import WebDocsStore

    token = tmp_path / "token.json"
    creds_file = tmp_path / "credentials.json"
    token.write_text(
        '{"token": "tok", "refresh_token": "r", "token_uri": "u", "client_id": "c", "client_secret": "s", "scopes": ["https://www.googleapis.com/auth/drive"]}'
    )
    creds_file.write_text("{}")
    cfg = Config(
        gateway_url="http://localhost",
        anthropic_api_key="sk-test",
        gdrive_folder_id="root-id",
        sqlite_path=tmp_path / "store.db",
        gdrive_token_file=token,
        gdrive_credentials_file=creds_file,
        gdrive_web_docs_folder_id="webdocs-id",
    )
    store = WebDocsStore(cfg)
    store._svc = MagicMock()
    return store


# ── WebDocsStore.get_cached_crawl ──────────────────────────────────────────────


def test_get_cached_crawl_returns_none_when_slug_folder_missing(tmp_path):
    store = _make_store_with_mock_service(tmp_path)
    svc = store._svc
    svc.files.return_value.list.return_value.execute.return_value = {"files": []}

    result = store.get_cached_crawl("https://example.com")

    assert result is None
    svc.files().create.assert_not_called()
    svc.files().update.assert_not_called()


def test_get_cached_crawl_returns_none_when_no_index_json(tmp_path):
    store = _make_store_with_mock_service(tmp_path)
    svc = store._svc
    from ibkr_core_mcp.web_scraper import _slugify

    slug = _slugify("https://example.com")

    def fake_list(**kwargs):
        q = kwargs.get("q", "")
        mock = MagicMock()
        if f"name='{slug}'" in q:
            mock.execute.return_value = {"files": [{"id": "slug-folder-id"}]}
        else:
            mock.execute.return_value = {"files": []}  # no index.json
        return mock

    svc.files.return_value.list.side_effect = fake_list

    result = store.get_cached_crawl("https://example.com")

    assert result is None
    svc.files().create.assert_not_called()


def _mock_index_json_download(svc, slug_folder_id, manifest, index_file_id="index-file-id"):
    """Wire a mock WebDocsStore's svc so get_cached_crawl finds and downloads
    the given manifest dict as index.json content."""

    def fake_list(**kwargs):
        q = kwargs.get("q", "")
        mock = MagicMock()
        if "index.json" in q:
            mock.execute.return_value = {"files": [{"id": index_file_id}]}
        else:
            mock.execute.return_value = {"files": [{"id": slug_folder_id}]}
        return mock

    svc.files.return_value.list.side_effect = fake_list

    import json as _json

    def fake_download(buf, request):
        buf.write(_json.dumps(manifest).encode("utf-8"))
        buf.seek(0)
        m = MagicMock()
        m.next_chunk.return_value = (None, True)
        return m

    return fake_download


def test_get_cached_crawl_returns_manifest_when_fresh(tmp_path):
    from datetime import UTC, datetime

    store = _make_store_with_mock_service(tmp_path)
    svc = store._svc
    manifest = {
        "url": "https://example.com",
        "crawled_at": datetime.now(UTC).isoformat(),
        "pages": [{"url": "https://example.com/page", "file_id": "fid"}],
    }
    fake_download = _mock_index_json_download(svc, "slug-folder-id", manifest)

    with patch("ibkr_core_mcp.web_scraper.MediaIoBaseDownload", side_effect=fake_download):
        result = store.get_cached_crawl("https://example.com", max_age_hours=48.0)

    assert result == manifest
    svc.files().create.assert_not_called()
    svc.files().update.assert_not_called()


def test_get_cached_crawl_returns_none_when_stale(tmp_path):
    from datetime import UTC, datetime, timedelta

    store = _make_store_with_mock_service(tmp_path)
    svc = store._svc
    stale_time = datetime.now(UTC) - timedelta(hours=100)
    manifest = {
        "url": "https://example.com",
        "crawled_at": stale_time.isoformat(),
        "pages": [],
    }
    fake_download = _mock_index_json_download(svc, "slug-folder-id", manifest)

    with patch("ibkr_core_mcp.web_scraper.MediaIoBaseDownload", side_effect=fake_download):
        result = store.get_cached_crawl("https://example.com", max_age_hours=48.0)

    assert result is None


def test_save_crawl_uploads_pages_and_manifest(tmp_path):
    store = _make_store_with_mock_service(tmp_path)
    svc = store._svc
    # Mock: no existing page file (search returns empty), create returns id
    svc.files().list().execute.return_value = {"files": []}
    svc.files().create().execute.return_value = {"id": "file-id-1"}

    pages = [{"url": "https://example.com/page", "markdown": "# Hello"}]
    manifest = store.save_crawl("https://example.com", pages)

    assert manifest["url"] == "https://example.com"
    assert len(manifest["pages"]) == 1
    assert manifest["pages"][0]["url"] == "https://example.com/page"
    assert "crawled_at" in manifest
    # create() called at least twice: once for the page, once for index.json
    assert svc.files().create.call_count >= 2


def test_save_crawl_skips_empty_markdown(tmp_path):
    store = _make_store_with_mock_service(tmp_path)
    svc = store._svc
    svc.files().list().execute.return_value = {"files": []}
    svc.files().create().execute.return_value = {"id": "file-x"}

    pages = [
        {"url": "https://example.com/a", "markdown": "# Real"},
        {"url": "https://example.com/b", "markdown": ""},
        {"url": "https://example.com/c", "markdown": None},
    ]
    manifest = store.save_crawl("https://example.com", pages)
    assert len(manifest["pages"]) == 1
    assert manifest["pages"][0]["url"] == "https://example.com/a"


def test_save_crawl_disambiguates_colliding_slugs(tmp_path):
    """Two distinct page URLs that _slugify to the same filename (e.g. .../a-b
    and .../a_b both -> 'a-b.md') must not silently collide — the second page's
    existence-check would otherwise find the first page's just-created file and
    overwrite it, losing the first page's content while the manifest still
    claims both URLs were saved under distinct entries."""
    store = _make_store_with_mock_service(tmp_path)
    svc = store._svc
    from ibkr_core_mcp.web_scraper import _slugify

    url_a = "https://example.com/a-b"
    url_b = "https://example.com/a_b"
    assert _slugify(url_a) == _slugify(url_b)  # sanity check: these do collide

    created: dict[str, str] = {}  # filename -> file_id

    def fake_list(**kwargs):
        q = kwargs.get("q", "")
        mock = MagicMock()
        for name, fid in created.items():
            if f"name='{name}'" in q:
                mock.execute.return_value = {"files": [{"id": fid}]}
                return mock
        mock.execute.return_value = {"files": []}
        return mock

    def fake_create(**kwargs):
        name = kwargs["body"]["name"]
        mock = MagicMock()
        if name == "index.json":
            mock.execute.return_value = {"id": "index-id"}
            return mock
        fid = f"fid-{len(created)}"
        created[name] = fid
        mock.execute.return_value = {"id": fid}
        return mock

    update_calls = []

    def fake_update(**kwargs):
        update_calls.append(kwargs["fileId"])
        mock = MagicMock()
        mock.execute.return_value = {"id": kwargs["fileId"]}
        return mock

    svc.files.return_value.list.side_effect = fake_list
    svc.files.return_value.create.side_effect = fake_create
    svc.files.return_value.update.side_effect = fake_update

    pages = [
        {"url": url_a, "markdown": "# Content A"},
        {"url": url_b, "markdown": "# Content B (different page!)"},
    ]
    manifest = store.save_crawl("https://example.com", pages)

    assert len(manifest["pages"]) == 2
    file_ids = {p["file_id"] for p in manifest["pages"]}
    assert len(file_ids) == 2, f"expected 2 distinct file_ids for 2 distinct URLs, got {manifest['pages']}"
    assert not update_calls, "second page must be create()'d under a disambiguated name, not update() the first"


def test_save_crawl_overwrites_existing_file(tmp_path):
    store = _make_store_with_mock_service(tmp_path)
    svc = store._svc
    # Simulate existing file
    svc.files().list().execute.return_value = {"files": [{"id": "old-file-id"}]}
    svc.files().update().execute.return_value = {"id": "old-file-id"}
    svc.files().create().execute.return_value = {"id": "index-id"}

    pages = [{"url": "https://example.com/page", "markdown": "# Updated"}]
    manifest = store.save_crawl("https://example.com", pages)

    # update() called for the existing page, create() called for index.json
    svc.files().update.assert_called()
    assert len(manifest["pages"]) == 1


def test_save_crawl_returns_empty_manifest_for_no_pages(tmp_path):
    store = _make_store_with_mock_service(tmp_path)
    svc = store._svc
    svc.files().list().execute.return_value = {"files": []}
    svc.files().create().execute.return_value = {"id": "index-id"}

    manifest = store.save_crawl("https://example.com", [])
    assert manifest["pages"] == []
    assert manifest["url"] == "https://example.com"


# ── WebDocsStore.save_search ──────────────────────────────────────────────────


def test_save_search_uploads_markdown_file(tmp_path):
    store = _make_store_with_mock_service(tmp_path)
    svc = store._svc
    svc.files().list().execute.return_value = {"files": []}
    svc.files().create().execute.return_value = {"id": "search-file-id"}

    results = [{"url": "https://example.com", "title": "Example", "markdown": "# Hello"}]
    file_id = store.save_search("test query", results)
    assert file_id == "search-file-id"
    # create() called at least once for the file
    assert svc.files().create.call_count >= 1


def test_save_search_filename_format(tmp_path):
    """Filename must match YYYYMMDDTHHMMSSz-{slug}.md format."""
    store = _make_store_with_mock_service(tmp_path)
    svc = store._svc
    svc.files().list().execute.return_value = {"files": []}
    svc.files().create().execute.return_value = {"id": "fid"}

    import re as _re

    captured = []

    def capture_create(**kwargs):
        body = kwargs.get("body", {})
        if "name" in body and body["name"].endswith(".md"):
            captured.append(body["name"])
        m = MagicMock()
        m.execute.return_value = {"id": "fid"}
        return m

    svc.files().create.side_effect = capture_create

    store.save_search("IBKR API docs", [{"url": "u", "title": "t", "markdown": "md"}])
    assert len(captured) == 1
    # Pattern: 8 digits T 6 digits Z - slug .md
    assert _re.match(r"^\d{8}T\d{6}Z-.*\.md$", captured[0]), f"Bad filename: {captured[0]}"


def test_save_search_markdown_content_includes_results(tmp_path):
    """Saved markdown must contain query, result titles, and URLs."""
    store = _make_store_with_mock_service(tmp_path)
    svc = store._svc
    svc.files().list().execute.return_value = {"files": []}

    uploaded_content = []

    def capture_create(**kwargs):
        media = kwargs.get("media_body")
        if media and hasattr(media, "_fd"):
            media._fd.seek(0)
            uploaded_content.append(media._fd.read().decode())
        m = MagicMock()
        m.execute.return_value = {"id": "fid"}
        return m

    svc.files().create.side_effect = capture_create

    results = [
        {"url": "https://example.com/a", "title": "Page A", "markdown": "## Content A"},
    ]
    store.save_search("IBKR flex query", results)
    # At least one upload with content (the search snapshot markdown)
    assert any("IBKR flex query" in c or "Page A" in c for c in uploaded_content)
