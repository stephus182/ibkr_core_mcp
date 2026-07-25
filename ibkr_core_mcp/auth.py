"""Authentication strategies for the IBKR Client Portal gateway.

Three interchangeable implementations of the `AuthStrategy` protocol:

- `BrowserCookieAuth` (default) reads the gateway session cookie out of a local
  browser's cookie store. The gateway must therefore run on the *same machine* as
  the browser used to log in — there is no cloud-deployable variant.
- `TokenAuth` supplies a pre-obtained session token, for headless/batch callers
  that manage the session themselves.
- `NoAuth` sends nothing, for tests and for gateways fronted by another layer.

Cookie values are sanitised before use: per RFC 6265 §4.1.1 a cookie-octet may not
contain control characters, so CR/LF are stripped to prevent header injection.

See `docs/gateway-auth-reference.md` for the full login walkthrough.
"""

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


def _sanitize_cookie_token(value: str) -> str:
    """Remove CR and LF characters to prevent HTTP header injection."""
    return _CRLF_RE.sub("", value)


class AuthStrategy(Protocol):
    """Protocol for IBKR Client Portal authentication strategies."""

    def apply(self, session: requests.Session) -> None:
        """Mutate `session` in place so subsequent requests carry credentials."""
        ...


class NoAuth:
    """No-op strategy — for testing or pre-authenticated sessions."""

    def apply(self, session: requests.Session) -> None:
        """Leave the session untouched; credentials are supplied elsewhere."""


class TokenAuth:
    """Inject a pre-obtained cookie string directly as the Cookie request header.

    CRLF characters are stripped from the cookie value to prevent HTTP header
    injection. RFC 6265 §4.1.1 defines the cookie-octet character set and
    prohibits CR and LF in cookie values.
    Source: https://www.rfc-editor.org/rfc/rfc6265#section-4.1.1
    """

    def __init__(self, cookie_string: str) -> None:
        """Store `cookie_string`, stripped and sanitised of CR/LF.

        Args:
            cookie_string: A raw `Cookie` header value obtained out of band.
        """
        self._cookie_string = _sanitize_cookie_token(cookie_string.strip())

    def apply(self, session: requests.Session) -> None:
        """Set the sanitised cookie as the session's `Cookie` header."""
        session.headers.update({"Cookie": self._cookie_string})

    def __repr__(self) -> str:
        """Return a repr with the cookie redacted, so it is never logged."""
        return "TokenAuth(cookie_string='<redacted>')"

    __str__ = __repr__


class BrowserCookieAuth:
    """Read browser localhost cookies and inject them as a raw Cookie header.

    The requests library silently drops cookies for 'localhost' via the cookie
    jar (cookiejar domain matching requires a dot-prefixed domain, which
    'localhost' never satisfies). We bypass the jar entirely and build the
    Cookie header manually from browser_cookie3.

    CRLF stripping on both cookie name and value prevents HTTP header injection.
    RFC 6265 §4.1.1: cookie-octet excludes control characters including CR/LF.
    Source: https://www.rfc-editor.org/rfc/rfc6265#section-4.1.1

    Supported browsers: chrome, chromium, firefox, safari, edge.
    Uses browser_cookie3 for cross-platform cookie extraction.
    Source: https://github.com/borisbabic/browser_cookie3
    """

    def __init__(self, browser: str = "chrome") -> None:
        """Select which browser's cookie store to read.

        Args:
            browser: One of chrome, chromium, firefox, safari, edge.

        Raises:
            ValueError: If `browser` is not one of the supported names. Validated
                here rather than at `apply()` time so a typo fails fast, and so the
                name can never reach `getattr` on the browser_cookie3 module.
        """
        if browser not in _ALLOWED_BROWSERS:
            raise ValueError(f"Unsupported browser {browser!r}. Allowed: {sorted(_ALLOWED_BROWSERS)}")
        self._browser = browser

    def apply(self, session: requests.Session) -> None:
        """Copy localhost cookies from the browser into the session's Cookie header.

        Builds the header by hand instead of populating the cookie jar: cookiejar
        domain matching requires a dot-prefixed domain, which `localhost` never
        satisfies, so requests would silently drop every cookie. A missing
        browser_cookie3 is treated as headless and skipped rather than raising.
        """
        try:
            import browser_cookie3
        except ImportError:
            return  # headless — library not installed, silently skip

        try:
            loader = getattr(browser_cookie3, self._browser)
            jar = loader(domain_name="localhost")
            # Strip CR/LF from names and values to prevent HTTP header injection.
            if parts := [
                f"{_sanitize_cookie_token(c.name)}={_sanitize_cookie_token(c.value)}"
                for c in jar
                if c.name and _sanitize_cookie_token(c.name)
            ]:
                session.headers.update({"Cookie": "; ".join(parts)})
            else:
                warnings.warn(
                    "BrowserCookieAuth: no localhost cookies found in "
                    f"{self._browser}. Session will be unauthenticated.",
                    stacklevel=2,
                )
        except Exception as exc:
            warnings.warn(
                f"BrowserCookieAuth: cookie extraction failed ({type(exc).__name__}). Session will be unauthenticated.",
                stacklevel=2,
            )
