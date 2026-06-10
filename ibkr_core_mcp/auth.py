from __future__ import annotations

import logging
import re
import warnings
from typing import Protocol

import requests

_log = logging.getLogger(__name__)

_ALLOWED_BROWSERS = frozenset({"chrome", "chromium", "firefox", "safari", "edge"})

# RFC 6265 §4.1.1 — cookie-octet excludes control characters, whitespace,
# double-quote, comma, semicolon, and backslash.  Strip CR/LF at minimum to
# prevent HTTP response-splitting / header injection.
_CRLF_RE = re.compile(r"[\r\n]")
_BROWSER_LOADERS: dict[str, str] = {
    "chrome": "chrome", "chromium": "chromium", "firefox": "firefox",
    "safari": "safari", "edge": "edge",
}


def _sanitize_cookie_token(value: str) -> str:
    """Remove CR and LF characters to prevent HTTP header injection."""
    return _CRLF_RE.sub("", value)


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

    def __repr__(self) -> str:
        return "TokenAuth(cookie_string='<redacted>')"

    __str__ = __repr__


class BrowserCookieAuth:
    """Read browser localhost cookies and inject them as a raw Cookie header.

    requests silently drops cookies for 'localhost' via the cookie jar,
    so we build the Cookie header manually.
    """

    def __init__(self, browser: str = "chrome") -> None:
        if browser not in _ALLOWED_BROWSERS:
            raise ValueError(
                f"Unsupported browser {browser!r}. Allowed: {sorted(_ALLOWED_BROWSERS)}"
            )
        self._browser = browser

    def apply(self, session: requests.Session) -> None:
        try:
            import browser_cookie3
        except ImportError:
            return  # headless — library not installed, silently skip

        try:
            loader = getattr(browser_cookie3, _BROWSER_LOADERS[self._browser])
            jar = loader(domain_name="localhost")
            # Strip CR/LF from names and values to prevent HTTP header injection.
            parts = [
                f"{_sanitize_cookie_token(c.name)}={_sanitize_cookie_token(c.value)}"
                for c in jar
                if c.name and _sanitize_cookie_token(c.name)
            ]
            if parts:
                session.headers.update({"Cookie": "; ".join(parts)})
            else:
                warnings.warn(
                    "BrowserCookieAuth: no localhost cookies found in "
                    f"{self._browser}. Session will be unauthenticated.",
                    stacklevel=2,
                )
        except Exception as exc:
            warnings.warn(
                f"BrowserCookieAuth: cookie extraction failed ({type(exc).__name__}). "
                "Session will be unauthenticated.",
                stacklevel=2,
            )
