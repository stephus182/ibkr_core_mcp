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
from pathlib import Path

_MAX_LEN = 300

# Shape-based, not name-based (review 2026-09-13): the first version anchored `\b` before
# `token`/`key`/`secret`, so `refresh_token=`, `client_secret=`, `access_token=` and a URL's
# userinfo all passed through verbatim. The rules now are: every Authorization/Cookie value;
# the two key prefixes this package handles; any URL userinfo; any URL query string whole
# (the model never needs a query value); and any `identifier=value` / `identifier: value`
# whose identifier contains a credential word — **including the quoted forms**,
# `{"identifier": "value"}` and `{'identifier': 'value'}`, which is what a JSON error
# body looks like and which the rule missed until 2026-09-17 (SEC-06). Order matters
# where rules overlap.
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
        # The identifier may be quoted, so the closing quote sits between it and the
        # separator: `{"refresh_token": "…"}`. Requiring the separator to follow the name
        # immediately let every JSON and repr form through verbatim, which is exactly the
        # shape an OAuth or Drive error body has (SEC-06, 2026-09-17).
        r"['\"]?\s*[=:]\s*"
        # A quoted value is consumed to its closing quote, so a secret containing spaces
        # cannot leave its tail behind; an unquoted one stops at the first delimiter.
        r"(?:'[^']*'|\"[^\"]*\"|[^\s'\"&;,]+)"
    ),
)

_REDACTED = "[redacted]"


def collapse_home(text: str) -> str:
    """Rewrite the operator's home directory as `~` wherever it appears in `text`.

    One definition of "show a path" for every surface that shows one to the model or a log,
    the way `order_confirm.price_text_safe` is one definition of rendering a broker price.
    What the model needs — which file, under which root — survives; the account name it does
    not need does not.

    OWASP's *A Practical Guide for Secure MCP Server Development* v1.0 §6 (Safe Error
    Handling) lists filesystem paths beside tokens and stack traces in what must not be
    returned to the model or client, and the 2026-07-11 audit had already observed in passing
    that `_import_flex_file` "discloses the exact home-directory path on any invalid probe".
    Both were closed on 2026-09-14; the applicability decision is
    docs/audits/owasp-mcp-guide-applicability-2026-09-14.md § Phase 1, §6 row.

    A home path shorter than two characters (a pathological `HOME=/`) is left alone:
    substituting every separator would destroy the message this exists to keep readable.
    An unresolvable home is left alone for the same reason.

    Args:
        text: Any message about to be shown to the model or written to a log.

    Returns:
        The same text with the home directory written as `~`.
    """
    try:
        home = str(Path.home())
    except (OSError, RuntimeError):  # no resolvable home directory
        return text
    if len(home) < 2:
        return text
    return text.replace(home, "~")


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

    The home directory is collapsed to `~` (`collapse_home`, 2026-09-14) before the length
    cap, so the shortening buys message rather than spending it.

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
    first_line = collapse_home(first_line)
    text = f"{type(exc).__name__}: {first_line}" if first_line else type(exc).__name__
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return text
