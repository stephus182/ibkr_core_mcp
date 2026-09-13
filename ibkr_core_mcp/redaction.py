"""One redaction function for exception text that leaves the process as a message.

`claude_tools._safe_error` maps an exception *type* to a fixed sentence and is the right
tool when the model needs no detail. Some channels do need detail — the sandbox error the
model must fix, a browser failure it can act on, a resource handler's reason — and until
2026-09-13 each of those interpolated `{exc}` on its own. None carried a secret that day;
the class of failure is one copy-paste away, because a `requests` exception carries the
full request URL, and the Flex token travels in `?t=…` (probed, verbatim in the text).

`redact_error` is the single path for every such channel in `claude_tools.py` and
`mcp_server.py`, enforced by `tests/security/test_error_redaction.py`: type name plus the
first line of the message, secret-shaped material scrubbed, one line, bounded length.
See docs/audits/security-architecture-audit-2026-09-13.md, B5.
"""

from __future__ import annotations

import re

_MAX_LEN = 300

# Shape-based, not name-based (review 2026-09-13): the first version anchored `\b` before
# `token`/`key`/`secret`, so `refresh_token=`, `client_secret=`, `access_token=` and a URL's
# userinfo all passed through verbatim. The rules now are: every Authorization/Cookie value;
# the two key prefixes this package handles; any URL userinfo; any URL query string whole
# (the model never needs a query value); and any `identifier=value` / `identifier: value`
# whose identifier contains a credential word. Order matters where rules overlap.
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\bbearer\s+\S+"),
    re.compile(r"(?i)cookie:\s*[^\n]+"),
    re.compile(r"sk-ant-[A-Za-z0-9_\-]+"),
    re.compile(r"\bfc-[A-Za-z0-9]{10,}"),
    re.compile(r"://[^/\s@:]+:[^/\s@]+@"),  # https://user:password@host → https://[redacted]@host
    re.compile(r"\?[^\s'\"]+"),  # ?t=…&q=… → ?[redacted]
    re.compile(
        r"(?i)\b(?:[\w\-]*(?:token|secret|passw|pwd|session|credential|auth)[\w\-]*"
        r"|api[_\-]?key|access[_\-]?key|secret[_\-]?key|private[_\-]?key|key)"
        r"\s*[=:]\s*['\"]?[^\s'\"&;,]+"
    ),
)

_REDACTED = "[redacted]"


def _scrub(match: re.Match[str]) -> str:
    """Keep the recognisable head of a match (`?`, `://`, `Cookie:`) and replace the rest."""
    text = match.group(0)
    for head in ("://", "?"):
        if text.startswith(head):
            return head + _REDACTED + ("@" if head == "://" else "")
    if text.lower().startswith("cookie:"):
        return "Cookie: " + _REDACTED
    return _REDACTED


def redact_error(exc: BaseException, limit: int = _MAX_LEN) -> str:
    """`TypeName: first line of the message`, secrets scrubbed, bounded, no newline.

    Args:
        exc: The exception whose text is about to be shown to the model or logged.
        limit: Maximum length of the returned text.

    Returns:
        A single line safe to place in a tool result or a log record.
    """
    message = str(exc)
    first_line = message.splitlines()[0] if message else ""
    for pattern in _SECRET_PATTERNS:
        first_line = pattern.sub(_scrub, first_line)
    text = f"{type(exc).__name__}: {first_line}" if first_line else type(exc).__name__
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return text
