"""Security constitution, the TLS sentence made test-held (register F45, condition C): every
function that disables certificate verification pins its URL to loopback first, and the set
of such functions is exactly the one declared here.

`SECURITY.md` said "exactly three code paths disable certificate verification, and every one is
pinned to loopback before it can run" from 2026-07 on, and until 2026-11-09 nothing held either
half: the count was a sentence, and the two pins were inline tuples written twice
(`client.py`, `streaming.py`) while the manager's two polls had no pin at all (probe M6, F45
security review). The gateway session owner's move brings seven more certificate-exempt calls
into the package, so the claim is held here before any of them lands: one helper
(`config.require_loopback_url` / `is_loopback_url`), called on a line before the first
disabling line of every function that has one.

What "disables verification" means, in every spelling the package uses: a `verify=False`
keyword on a call, an assignment of `False` to an attribute named `verify`, an assignment of
`ssl.CERT_NONE` to `verify_mode`, or `check_hostname = False`. A new spelling is a new entry in
`_disabling_lines`, not a reason to loosen the allowlist.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator

import pytest

from .structural import PACKAGE_DIR, call_lines, package_sources

pytestmark = pytest.mark.security

# Relative to the package directory: module → the functions in it that disable verification.
# Every entry is a call to the local gateway over its self-signed certificate, and each is
# proven below to pin its URL first. Adding an entry means adding the pin to the function.
ALLOWLIST: dict[str, set[str]] = {
    "client.py": {"__init__"},  # IBKRClient: `self._session.verify = False`
    "streaming.py": {"connect"},  # IBKRWebSocket: `CERT_NONE`, `check_hostname = False`
    "gateway/manager.py": {"is_gateway_reachable", "is_authenticated"},  # the two polls
    "gateway/preflight.py": {"read_state", "_read_sso", "confirm_session"},  # the readings (F45 step 1)
}
PIN_CALLS = ("is_loopback_url", "require_loopback_url")


def _functions(tree: ast.AST) -> Iterator[ast.FunctionDef | ast.AsyncFunctionDef]:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def _is_false(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value is False


def _disabling_lines(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[int]:
    """Lines inside `fn` that disable certificate verification, in any of the four spellings."""
    lines: set[int] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            if any(kw.arg == "verify" and _is_false(kw.value) for kw in node.keywords):
                lines.add(node.lineno)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            if value is None:
                continue
            for target in targets:
                if not isinstance(target, ast.Attribute):
                    continue
                if target.attr in ("verify", "check_hostname") and _is_false(value):
                    lines.add(node.lineno)
                if target.attr == "verify_mode" and isinstance(value, ast.Attribute) and value.attr == "CERT_NONE":
                    lines.add(node.lineno)
    return sorted(lines)


def disabling_functions(source: str) -> dict[str, list[int]]:
    """Every function in `source` that disables verification → its disabling lines."""
    found: dict[str, list[int]] = {}
    for fn in _functions(ast.parse(source)):
        if lines := _disabling_lines(fn):
            found.setdefault(fn.name, []).extend(lines)
    return found


def unpinned(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """Why `fn` fails the ordering rule, or None: no pin call at all, or the first pin on a line
    after the first disabling line."""
    disabling = _disabling_lines(fn)
    pins = call_lines(fn, PIN_CALLS)
    if not pins:
        return f"{fn.name}: disables verification at line {min(disabling)} and never pins its URL"
    if min(pins) > min(disabling):
        return f"{fn.name}: disables verification at line {min(disabling)}, pins only at line {min(pins)}"
    return None


def test_the_functions_that_disable_verification_are_exactly_the_allowlist():
    """Both directions: a new certificate-exempt call anywhere is red until it is declared here,
    and a declared one that no longer exists is red too."""
    sites = {
        str(path.relative_to(PACKAGE_DIR)): set(found)
        for path, source in package_sources()
        if (found := disabling_functions(source))
    }
    assert sites == ALLOWLIST, sites


def test_every_disabling_function_pins_its_url_on_a_line_before():
    """The pin — a call to `is_loopback_url` or `require_loopback_url` — precedes the first line
    that disables verification, in every function the allowlist names."""
    defects = []
    for module, names in ALLOWLIST.items():
        tree = ast.parse((PACKAGE_DIR / module).read_text())
        for fn in _functions(tree):
            if fn.name in names and _disabling_lines(fn) and (why := unpinned(fn)) is not None:
                defects.append(f"{module}: {why}")
    assert defects == [], defects


# ── Guards on the guards ───────────────────────────────────────────────────────


def _only(source: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    (fn,) = _functions(ast.parse(source))
    return fn


def test_the_probe_sees_an_unpinned_call_and_fails_it():
    snippet = "def bad(u):\n    return requests.get(u, verify=False)\n"
    assert disabling_functions(snippet) == {"bad": [2]}
    assert unpinned(_only(snippet)) == "bad: disables verification at line 2 and never pins its URL"


def test_a_pin_after_the_call_is_not_a_pin():
    snippet = "def late(u):\n    r = requests.get(u, verify=False)\n    require_loopback_url(u)\n    return r\n"
    assert unpinned(_only(snippet)) == "late: disables verification at line 2, pins only at line 3"


def test_a_pin_before_the_call_passes():
    snippet = "def good(u):\n    require_loopback_url(u)\n    return requests.get(u, verify=False)\n"
    assert unpinned(_only(snippet)) is None
    snippet = (
        "def good(u):\n    if not is_loopback_url(u):\n        raise E()\n    return requests.get(u, verify=False)\n"
    )
    assert unpinned(_only(snippet)) is None


@pytest.mark.parametrize(
    ("spelling", "snippet"),
    [
        ("verify keyword", "def f(s, u):\n    return s.get(u, verify=False)\n"),
        ("verify attribute", "def f(s):\n    s.verify = False\n"),
        ("check_hostname", "def f(c):\n    c.check_hostname = False\n"),
        ("CERT_NONE", "def f(c):\n    c.verify_mode = ssl.CERT_NONE\n"),
    ],
)
def test_the_probe_sees_each_spelling(spelling, snippet):
    assert disabling_functions(snippet) == {"f": [2]}, spelling


def test_the_probe_ignores_verification_left_on():
    snippet = "def f(s, c, u):\n    s.verify = True\n    c.check_hostname = True\n    c.verify_mode = ssl.CERT_REQUIRED\n    return s.get(u, verify=True)\n"
    assert disabling_functions(snippet) == {}


# ── The one context the package builds pins its own TLS minimum ─────────────────────────────


def _pins_minimum_tls_1_2(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Whether `fn` assigns `ssl.TLSVersion.TLSv1_2` to an attribute named `minimum_version`."""
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Attribute) and t.attr == "minimum_version" for t in node.targets
        ):
            value = node.value
            if isinstance(value, ast.Attribute) and value.attr == "TLSv1_2":
                return True
    return False


def test_the_websocket_context_pins_tls_1_2_as_its_minimum_in_source():
    """MCP security checklist 5.1 (2026-11-09). Every other connection goes through `requests`,
    whose urllib3 ≥ 2 negotiates TLS 1.2 or later by default; the one `SSLContext` this package
    builds — `IBKRWebSocket.connect` — says so itself. Measured the same day: the interpreter's
    default was already TLS 1.2 (Python 3.11.18, OpenSSL 3.5.9), so this is the package's own
    statement, held here, not an inheritance from whatever OpenSSL configuration the host has."""
    source = (PACKAGE_DIR / "streaming.py").read_text()
    connect = next(fn for fn in _functions(ast.parse(source)) if fn.name == "connect")
    assert _pins_minimum_tls_1_2(connect), "IBKRWebSocket.connect does not set minimum_version = TLSVersion.TLSv1_2"


def test_the_minimum_probe_sees_the_pin_and_its_absence():
    assert _pins_minimum_tls_1_2(_only("def f(c):\n    c.minimum_version = ssl.TLSVersion.TLSv1_2\n"))
    assert not _pins_minimum_tls_1_2(_only("def f(c):\n    c.verify_mode = ssl.CERT_NONE\n"))
    assert not _pins_minimum_tls_1_2(_only("def f(c):\n    c.minimum_version = ssl.TLSVersion.TLSv1\n"))
