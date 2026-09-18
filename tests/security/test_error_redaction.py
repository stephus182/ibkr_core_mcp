"""Security constitution §6 — error text that reaches the model or a log passes one
redaction function; Flex tokens, Bearer keys and cookies never appear in it.

`_safe_error` is that function for `execute()`, but three channels bypassed it on
2026-09-13: `_run_backtest` (`str(exc)`), `handle_read_resource`
(`f"{type(exc).__name__}: {exc}"`, carrying IBKRAPIError's 400-char gateway body) and the
web handlers (`f"… failed: {exc}"`). None carried a secret that day; the class of failure
is one copy-paste away, because a `requests` exception carries the full request URL —
probed: the Flex token in `?t=…` appears verbatim in the exception text
(docs/audits/security-architecture-audit-2026-09-13.md, B5).
"""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

from ibkr_core_mcp.redaction import redact_error

from .structural import PACKAGE_DIR, callee_name

pytestmark = pytest.mark.security

SECRETS = {
    "flex token in a URL": "https://ndcdyn.interactivebrokers.com/x?t=SECRET-FLEX-TOKEN-123&q=1",
    "bearer header": "Invalid header value: 'Bearer fc-SECRETSECRETSECRET1234'",
    "anthropic key": "sk-ant-api03-SECRETSECRETSECRET-abc",
    "firecrawl key": "key fc-abcdefghijklmnopqrstuvwxyz012345",
    "cookie header": "Cookie: api=SECRETCOOKIE; ibkr=SECRETCOOKIE2",
    "query token": "GET /flex?token=SECRETQ&other=1",
    # Review 2026-09-13: the first patterns anchored `\b` before token/key/secret, so any
    # identifier merely *containing* the word passed through verbatim.
    "oauth refresh": "https://oauth2.googleapis.com/token?client_secret=GOCSPX-SECRETX&refresh_token=1//SECRETREFRESH",
    "access token": "url: /x?access_token=SECRETACCESS",
    "userinfo": "https://user:SECRETPASS@host/path",
    "quoted key": 'api_key="SECRETQUOTED"',
    "lowercase bearer": "Authorization: bearer SECRETLOWER",
    "env dump": "IBKR_FLEX_TOKEN=SECRETENV ANTHROPIC_API_KEY=sk-ant-SECRETKEY",
    "session param": "GET /iserver?session=SECRETSESSION",
    # SEC-06, 2026-09-17: the identifier rule required the separator to follow the name
    # immediately, so every JSON or repr form — where a closing quote sits in between —
    # passed through verbatim. That is the shape an OAuth or Drive error body actually has,
    # and `redact_error` is what `WebDocsStore`/`gdrive_auth` failures pass through.
    "json body": '{"refresh_token": "SECRETJSON", "expires_in": 3600}',
    "json no space": '{"client_secret":"SECRETTIGHT"}',
    "python repr": "{'api_key': 'SECRETREPR'}",
    "json spaced value": '{"password": "SECRET PHRASE HERE"}',
    "drive error body": 'HttpError 401: {"error": "invalid_credentials", "access_token": "SECRETDRIVE"}',
    # SEC-R8, 2026-09-17: a quoted value severed before its closing quote — the shape a
    # body cut at `with_retry`'s or `_decode`'s 400-character preview has when the cut lands
    # inside the value — matched neither the quoted branch (no closing quote) nor the
    # unquoted one (the opening quote is not in its class), and passed through whole.
    "json severed value": 'HttpError 401: {"error": "x", "access_token": "SECRETSEVERED',
    "repr severed value": "{'refresh_token': 'SECRETSEVEREDREPR",
}


@pytest.mark.parametrize("label", sorted(SECRETS))
def test_secret_shaped_material_never_survives_redaction(label):
    text = redact_error(RuntimeError(SECRETS[label]))
    assert "SECRET" not in text, text
    assert "fc-abcdefghijklmnopqrstuvwxyz012345" not in text


def test_a_requests_failure_carrying_the_flex_token_is_scrubbed():
    """The real exception class, built the way `requests` builds it — no network needed."""
    exc = requests.exceptions.ConnectionError(
        "HTTPSConnectionPool(host='ndcdyn.interactivebrokers.com', port=443): Max retries exceeded "
        "with url: /AccountManagement/FlexWebService/SendRequest?t=SECRET-FLEX-TOKEN&q=123&v=3"
    )
    text = redact_error(exc)
    assert "SECRET-FLEX-TOKEN" not in text
    assert "ConnectionError" in text


def test_redaction_is_one_line_and_bounded():
    text = redact_error(ValueError("first line\nsecond line\n" + "x" * 2000))
    assert "\n" not in text
    assert len(text) <= 320
    assert text.startswith("ValueError: first line")


def test_ordinary_error_text_is_kept_for_the_model():
    text = redact_error(KeyError("rsi"))
    assert text == "KeyError: 'rsi'"
    text = redact_error(ValueError("Strategy must set df['signal'] (1=long, 0=flat, -1=short)"))
    assert "df['signal']" in text and "1=long" in text


# ── The operator's home directory is not part of a message ────────────────────


def test_the_home_directory_is_collapsed_to_a_tilde():
    """OWASP §6 lists filesystem paths beside tokens and stack traces in what must not reach
    the model. The username is exactly the part an absolute path adds that the model never
    needs — the Flex import's root is documented to it as `~/.ibkr_core` — and the 2026-07-11
    audit had already noted the blocked-path message "discloses the exact home-directory path
    on any invalid probe" without fixing it (H-2 write-up)."""
    home = str(Path.home())
    text = redact_error(FileNotFoundError(f"{home}/.ibkr_core/flex/missing.xml: not found"))
    assert home not in text
    assert "~/.ibkr_core/flex/missing.xml" in text, text


def test_a_blocked_flex_import_names_its_root_without_the_username(mock_config, tmp_path):
    """The one model-facing path message that is built by hand rather than from an exception,
    so `redact_error` never saw it: `_import_flex_file`'s refusal names the allowed root."""
    from ibkr_core_mcp.claude_tools import ClaudeToolkit

    toolkit = ClaudeToolkit(MagicMock(), MagicMock(), MagicMock(), mock_config)
    text, _ = toolkit.execute("import_flex_file", {"path": str(tmp_path / "elsewhere.xml")})

    assert text.startswith("Blocked:"), text
    assert str(Path.home()) not in text, text
    assert "~/.ibkr_core" in text, text


def test_a_home_of_one_character_is_left_alone(monkeypatch):
    """A pathological `HOME=/` must not turn every separator into a tilde: the guard is the
    difference between a shortened message and an unreadable one."""
    from ibkr_core_mcp.redaction import collapse_home

    monkeypatch.setenv("HOME", "/")
    assert collapse_home("/usr/local/share/x.xml") == "/usr/local/share/x.xml"


# ── Structural: every `except … as exc` interpolation in the model layer is redacted ───


def _unredacted_interpolations(source: str) -> list[int]:
    """Line numbers where a name bound by `except … as name` leaves the handler raw: an
    f-string, `str()`, `%`-formatting, `.format()`, `.args`, a logging call taking it as an
    argument, `log.exception(...)` or `exc_info=` (both print the raw traceback)."""
    offenders: list[int] = []
    for handler in ast.walk(ast.parse(source)):
        if not isinstance(handler, ast.ExceptHandler) or handler.name is None:
            continue
        bound = handler.name
        for node in ast.walk(handler):
            if isinstance(node, ast.FormattedValue) and _names_exc(node.value, bound):
                offenders.append(node.lineno)
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod) and _mentions_exc(node.right, bound):
                offenders.append(node.lineno)
            if isinstance(node, ast.Attribute) and node.attr == "args" and _names_exc(node.value, bound):
                offenders.append(node.lineno)
            if isinstance(node, ast.Call):
                func = node.func
                callee = callee_name(node)
                if callee == "str" and node.args and _names_exc(node.args[0], bound):
                    offenders.append(node.lineno)
                if callee == "format" and any(_names_exc(a, bound) for a in node.args):
                    offenders.append(node.lineno)
                is_log_call = (
                    isinstance(func, ast.Attribute)
                    and isinstance(func.value, ast.Name)
                    and func.value.id in ("log", "logger")
                )
                if is_log_call and (
                    callee == "exception"
                    or any(_names_exc(a, bound) for a in node.args)
                    or any(kw.arg == "exc_info" for kw in node.keywords)
                ):
                    offenders.append(node.lineno)
    return sorted(set(offenders))


def _mentions_exc(node: ast.expr, bound: str) -> bool:
    return any(_names_exc(n, bound) for n in ast.walk(node) if isinstance(n, ast.Name))


def _names_exc(node: ast.expr, bound: str) -> bool:
    return isinstance(node, ast.Name) and node.id == bound


@pytest.mark.parametrize("module", ["claude_tools.py", "mcp_server.py"])
def test_the_model_layer_interpolates_no_raw_exception(module):
    offenders = _unredacted_interpolations((PACKAGE_DIR / module).read_text())
    assert not offenders, f"{module}: raw exception text at lines {offenders}"


def test_the_interpolation_probe_sees_each_form():
    snippet = (
        "try:\n"
        "    pass\n"
        "except Exception as exc:\n"
        "    a = f'failed: {exc}'\n"
        "    b = str(exc)\n"
        "    log.warning('x %s', exc)\n"
        "    c = f'ok: {redact_error(exc)}'\n"
        "    d = 'x %s' % exc\n"
        "    e = '{}'.format(exc)\n"
        "    g = exc.args[0]\n"
        "    log.exception('boom')\n"
        "    log.error('boom', exc_info=True)\n"
    )
    assert _unredacted_interpolations(snippet) == [4, 5, 6, 8, 9, 10, 11, 12]


# ── The two log surfaces that were interpolating the absolute path (SEC-10) ────────────
#
# Both are driven under a throwaway HOME rather than read, because what matters is the
# record that is actually emitted. `collapse_home` resolves HOME too, so the code under
# test and the guard agree on what "home" means without either importing it from the other.


def _emitted(logger_name: str, run) -> list[str]:
    """Every message `run()` emits on `logger_name`."""
    import logging

    captured: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record):
            captured.append(record.getMessage())

    logger = logging.getLogger(logger_name)
    handler = _Capture()
    logger.addHandler(handler)
    previous = logger.level
    logger.setLevel(logging.DEBUG)
    try:
        run()
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)
    return captured


def test_the_sse_token_line_logs_the_token_file_without_the_username(monkeypatch, tmp_path):
    """`_issue_sse_token` deliberately logs the path and never the token. It logged the
    absolute path — `/Users/<name>/.ibkr_core/mcp_sse_token` — until 2026-09-17 (SEC-10),
    in the one line an operator is most likely to paste into an issue."""
    from ibkr_core_mcp.config import Config
    from ibkr_core_mcp.mcp_server import _issue_sse_token

    monkeypatch.setenv("HOME", str(tmp_path))
    config = Config(
        gateway_url="https://localhost:5055/v1/api",
        gdrive_folder_id="",
        sqlite_path=tmp_path / ".ibkr_core" / "store.db",
        gdrive_token_file=tmp_path / ".ibkr_core" / "token.json",
        gdrive_credentials_file=tmp_path / ".ibkr_core" / "creds.json",
    )

    token: dict[str, str] = {}
    messages = _emitted("ibkr_core_mcp.mcp_server", lambda: token.update(t=_issue_sse_token(config)))

    line = next(m for m in messages if "SSE bearer token" in m)
    assert str(tmp_path) not in line, line
    assert "~/.ibkr_core/mcp_sse_token" in line, line
    assert token["t"] not in line, "the token value itself must never be logged"


def test_the_store_chmod_warning_names_the_file_without_the_username(monkeypatch, tmp_path):
    """`store._restrict` reports a chmod it could not apply rather than swallowing it, and
    that message carried the absolute path. Found by the SEC-10 sweep, which the finding
    itself named only the SSE line — one call site is never the whole class."""
    from ibkr_core_mcp import store as store_module

    monkeypatch.setenv("HOME", str(tmp_path))
    target = tmp_path / ".ibkr_core" / "store.db"
    target.parent.mkdir(parents=True)
    target.write_text("")
    target.chmod(0o644)

    def refuse(self, mode):
        raise OSError("Operation not permitted")

    monkeypatch.setattr(Path, "chmod", refuse)
    messages = _emitted("ibkr_core_mcp.store", lambda: store_module._restrict(target, 0o600))

    assert messages, "the chmod failure was not logged at all — the check would be vacuous"
    assert str(tmp_path) not in messages[0], messages[0]
    assert "~/.ibkr_core/store.db" in messages[0], messages[0]
