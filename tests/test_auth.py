from unittest.mock import MagicMock, patch

import requests


def test_no_auth_applies_nothing():
    from ibkr_core_mcp.auth import NoAuth
    session = requests.Session()
    NoAuth().apply(session)
    assert "Cookie" not in session.headers


def test_token_auth_sets_cookie_header():
    from ibkr_core_mcp.auth import TokenAuth
    session = requests.Session()
    TokenAuth("session=abc123; ibkey=xyz").apply(session)
    assert session.headers.get("Cookie") == "session=abc123; ibkey=xyz"


def test_token_auth_strips_whitespace():
    from ibkr_core_mcp.auth import TokenAuth
    session = requests.Session()
    TokenAuth("  session=abc  ").apply(session)
    assert session.headers.get("Cookie") == "session=abc"


def test_browser_cookie_auth_applies_without_error():
    from ibkr_core_mcp.auth import BrowserCookieAuth
    session = requests.Session()
    with patch("browser_cookie3.chrome", return_value=[]):
        BrowserCookieAuth().apply(session)
    assert "Cookie" not in session.headers


def test_browser_cookie_auth_injects_cookies():
    from ibkr_core_mcp.auth import BrowserCookieAuth

    mock_cookie = MagicMock()
    mock_cookie.name = "ibkey"
    mock_cookie.value = "tok123"

    session = requests.Session()
    with patch("browser_cookie3.chrome", return_value=[mock_cookie]):
        BrowserCookieAuth().apply(session)

    assert "ibkey=tok123" in session.headers.get("Cookie", "")


def test_browser_cookie_auth_silences_errors():
    from ibkr_core_mcp.auth import BrowserCookieAuth
    session = requests.Session()
    with patch("browser_cookie3.chrome", side_effect=Exception("no chrome")):
        BrowserCookieAuth().apply(session)  # Must not raise
