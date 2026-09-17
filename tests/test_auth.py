from unittest.mock import MagicMock, patch

import pytest
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


# ---------------------------------------------------------------------------
# IBKR_AUTH_BROWSER — honoured everywhere, not just on one path (API-10)
# ---------------------------------------------------------------------------


def test_browser_cookie_auth_honours_ibkr_auth_browser(monkeypatch):
    """API-10. The variable selected the browser on exactly one of three call sites.

    `claude_tools`' P&L WebSocket read it from `os.environ` and passed it in; `client.py`'s
    default auth and `mcp_server.py`'s stream path both constructed `BrowserCookieAuth()`
    bare and got Chrome. An operator on Firefox therefore had a working P&L subscription and
    an unauthenticated session everywhere else — and the symptom is the generic "no localhost
    cookies found in chrome", which names the browser they did not choose.
    """
    from ibkr_core_mcp.auth import BrowserCookieAuth

    monkeypatch.setenv("IBKR_AUTH_BROWSER", "firefox")
    assert BrowserCookieAuth()._browser == "firefox"


def test_an_explicit_browser_argument_still_wins_over_the_environment(monkeypatch):
    from ibkr_core_mcp.auth import BrowserCookieAuth

    monkeypatch.setenv("IBKR_AUTH_BROWSER", "firefox")
    assert BrowserCookieAuth("safari")._browser == "safari"


def test_the_default_is_chrome_when_the_variable_is_unset(monkeypatch):
    from ibkr_core_mcp.auth import BrowserCookieAuth

    monkeypatch.delenv("IBKR_AUTH_BROWSER", raising=False)
    assert BrowserCookieAuth()._browser == "chrome"


def test_a_bogus_ibkr_auth_browser_fails_fast_and_names_the_variable(monkeypatch):
    """The allow-list is what keeps an arbitrary name away from `getattr(browser_cookie3, …)`.

    Reading the value from the environment must not weaken that: an unsupported name raises
    at construction exactly as an unsupported argument does. The message names the variable
    because an operator who typed it needs to know which input was rejected.
    """
    from ibkr_core_mcp.auth import BrowserCookieAuth

    monkeypatch.setenv("IBKR_AUTH_BROWSER", "netscape")
    with pytest.raises(ValueError, match="IBKR_AUTH_BROWSER"):
        BrowserCookieAuth()


def test_ibkr_clients_default_auth_honours_ibkr_auth_browser(monkeypatch, tmp_path):
    """The path the finding is actually about: every `IBKRClient` built without an explicit
    `auth=`, which is the documented way to build one.

    `IBKRClient` applies the strategy and does not keep it, so the selection is observed by
    spying on `apply` rather than by reading an attribute. Doing that also keeps the test off
    the real cookie store — a first draft asserted on `client._auth`, and the resulting
    construction went and read this machine's actual Edge profile (it warned
    "cookie extraction failed (BrowserCookieError)"), which is real local I/O in a unit test.
    """
    from ibkr_core_mcp.auth import BrowserCookieAuth
    from ibkr_core_mcp.client import IBKRClient
    from ibkr_core_mcp.config import Config

    selected: list[str] = []
    monkeypatch.setattr(BrowserCookieAuth, "apply", lambda self, session: selected.append(self._browser))
    monkeypatch.setenv("IBKR_AUTH_BROWSER", "edge")

    IBKRClient(
        Config(
            gateway_url="https://localhost:5055/v1/api",
            gdrive_folder_id="",
            sqlite_path=tmp_path / "store.db",
            gdrive_token_file=tmp_path / "token.json",
            gdrive_credentials_file=tmp_path / "credentials.json",
        )
    )
    assert selected == ["edge"], "IBKRClient's default auth ignored IBKR_AUTH_BROWSER"


def test_no_call_site_pins_a_browser_name_past_the_environment():
    """API-10 was a divergence between construction sites, so the sites are checked.

    Three existed; one passed a browser and two did not, so the variable worked on one path.
    The fix moved the env read inside `BrowserCookieAuth`, which only holds while no call
    site goes back to supplying a literal. A caller with a genuine reason to pin a browser
    should pass a variable, or add itself here with that reason written down.
    """
    import ast
    from pathlib import Path

    pinned = []
    for path in Path(__file__).resolve().parent.parent.joinpath("ibkr_core_mcp").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if name != "BrowserCookieAuth":
                continue
            literal = node.args and isinstance(node.args[0], ast.Constant)
            if literal or any(isinstance(k.value, ast.Constant) for k in node.keywords if k.arg == "browser"):
                pinned.append(f"{path.name}:{node.lineno}")

    assert not pinned, f"these sites hardcode a browser and so ignore IBKR_AUTH_BROWSER: {pinned}"
