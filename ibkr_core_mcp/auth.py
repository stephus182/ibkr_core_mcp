from __future__ import annotations
from typing import Protocol
import requests


class AuthStrategy(Protocol):
    def apply(self, session: requests.Session) -> None: ...


class NoAuth:
    """No-op strategy — for testing or pre-authenticated sessions."""

    def apply(self, session: requests.Session) -> None:
        pass


class TokenAuth:
    """Inject a pre-obtained cookie string directly into the session header."""

    def __init__(self, cookie_string: str) -> None:
        self._cookie_string = cookie_string.strip()

    def apply(self, session: requests.Session) -> None:
        session.headers.update({"Cookie": self._cookie_string})


class BrowserCookieAuth:
    """Read Chrome's localhost cookies and inject them as a raw Cookie header.

    requests silently drops cookies for 'localhost' via the cookie jar,
    so we build the Cookie header manually.
    """

    def __init__(self, browser: str = "chrome") -> None:
        self._browser = browser

    def apply(self, session: requests.Session) -> None:
        try:
            import browser_cookie3

            loader = getattr(browser_cookie3, self._browser)
            jar = loader(domain_name="localhost")
            parts = [f"{c.name}={c.value}" for c in jar]
            if parts:
                session.headers.update({"Cookie": "; ".join(parts)})
        except Exception:
            pass  # headless environments, wrong browser, or no cookies
