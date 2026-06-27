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
