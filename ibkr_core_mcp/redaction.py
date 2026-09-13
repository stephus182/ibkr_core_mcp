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

# Each pattern names one shape of secret this package handles. Order matters only for
# readability; every pattern runs. Keep them specific: the model reads what survives.
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"Bearer\s+\S+"),  # Authorization headers (Firecrawl)
    re.compile(r"sk-ant-[A-Za-z0-9_\-]+"),  # Anthropic keys
    re.compile(r"\bfc-[A-Za-z0-9]{10,}"),  # Firecrawl keys
    re.compile(r"(?i)\b(t|token|key|api_key|apikey|password|secret|session_id)=[^&\s'\"]+"),  # query params
    re.compile(r"(?i)cookie:\s*[^\n]+"),  # Cookie headers
    re.compile(r"(?i)\b(token|key|password|secret)\s*[:=]\s*'?[A-Za-z0-9_\-]{8,}'?"),  # key: value
)


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
        first_line = pattern.sub("[redacted]", first_line)
    text = f"{type(exc).__name__}: {first_line}" if first_line else type(exc).__name__
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return text
