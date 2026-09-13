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
