"""Security constitution §13, register F45 — the gateway package is the consumer-independent
home of the IBKR session, and the model layer never reaches it (condition A of the F45
security review).

Five checks, beside `test_order_write_boundary.py`'s "the model layer never references an
order write": (1) `claude_tools.py` and `mcp_server.py` import nothing from
`ibkr_core_mcp.gateway`, in either statement form, however deep the block; (2) neither names a
session write — `logout`, `reauthenticate`, `release_session`, `attempt_soft_recovery`,
`GatewaySession`, `SuspendLock`, `GatewayManager`, `get_session`, `read_login_events`,
`KeepAwake`, `restart_refusal` — to call, mock or mint; (3) the guard on those two, the probe
M1 of the review: a READ_ONLY tool handler that imported `GatewayManager` under `if False:`
and called `.restart()` passed the whole security suite on 2026-11-08, so that snippet is
what the checkers are proven against; (4) the three session endpoints — `ssodh/init`,
`/logout`, `reauthenticate` — are *called* only in the owner set (an HTTP-verb or client
primitive call whose source names one, or a method named so), which at step 1 is
`IBKRClient.logout` and `IBKRClient.reauthenticate`, deprecated at step 2 when the owner
module joins; (5) a `GatewayManager` is *driven* — `start`, `restart`, `stop`, `startup` on a
constructed or bound one — and the login page opened only inside the gateway package's own
modules; constructing one and handing it to the owner stays legal, which is how a host's
button reaches the gateway. (4) and (5) are the consumer's `test_gateway_ownership.py` AST
walks, ported: a text match counted prose, since every message about a borrowed session names
the endpoints that could not clear it.

Why this file rather than a capability: the gateway package declares no tool, and
`test_tool_capabilities.py` catches `logout` only as an *undeclared* `ACCOUNT_STATE` sink — a
handler that declared the capability and called it would pass (probe M2). OWASP LLM06:2025:
"Limit the extensions that LLM agents are allowed to call to only the minimum necessary."

**The string rule** (step 1, commit 3/13). Every message the gateway package prints names the
package's own commands and documents

**The string rule.** Every message the gateway package prints names the package's own commands
and documents — `python -m ibkr_core_mcp.gateway …`, `docs/gateway-auth-reference.md` — never
a consumer's. The functions moved here from the consumer that wrote them carried its command
names in their guidance (`python -m claudia.…`, `scripts/gateway-reset.sh`,
`scripts/ibkr-keepalive.sh`, `docs/ibkr-gateway.md`), and a core that tells its operator to run
a command it does not ship is a core that does not work without that consumer. Held over every
string literal — docstrings included, since they are literals and reach `help()` — in
`ibkr_core_mcp/gateway/*.py`, case-insensitively. A `#` comment is not a literal: it cannot be
printed, and the history of who wrote what belongs there.
"""

from __future__ import annotations

import ast
import re

import pytest

from .structural import PACKAGE_DIR, attribute_names_referenced, callee_name, names_referenced, package_sources

pytestmark = pytest.mark.security

GATEWAY_DIR = PACKAGE_DIR / "gateway"
MODEL_LAYER = {name: (PACKAGE_DIR / name).read_text() for name in ("claude_tools.py", "mcp_server.py")}

# Every name through which a session is created, destroyed, re-established or its container
# touched — the package's today and F45's step 2, so a step-2 name reaching the model layer
# before its commit is red here first.
SESSION_WRITE_NAMES = frozenset(
    {
        "logout",
        "reauthenticate",
        "release_session",
        "attempt_soft_recovery",
        "GatewaySession",
        "SuspendLock",
        "GatewayManager",
        "get_session",
        "read_login_events",
        "KeepAwake",
        "restart_refusal",
    }
)

# (4) The endpoints that create, destroy or re-establish a session, and the functions allowed
# to call them — relative to the package directory. Step 2 adds `gateway/session.py`'s owner.
SESSION_WRITE_ENDPOINTS = re.compile(r"ssodh/init|/logout|reauthenticate")
SESSION_WRITE_OWNERS: dict[str, set[str]] = {
    "client.py": {"logout", "reauthenticate"},  # deprecated at step 2, removed in 3.0
    "gateway/session.py": {"release_session", "attempt_soft_recovery"},  # the owner (F45 step 2)
}
# The calls that send: `requests`' verbs and the client's own primitives.
_SENDERS = frozenset({"get", "post", "put", "patch", "delete", "head", "request", "_get", "_post", "_put"})

# (5) The methods that destroy whatever session the container holds, or open a login with no
# pre-flight; and the modules allowed to drive a manager that way. Step 2 adds the owner.
MANAGER_DRIVERS = frozenset({"start", "restart", "stop", "startup"})
MANAGER_DRIVING_MODULES = frozenset({"gateway/manager.py"})
LOGIN_OPENERS = frozenset({"open_login_page", "open"})  # `open` as in `webbrowser.open`
LOGIN_OPENING_MODULES = frozenset({"gateway/manager.py", "gateway/session.py"})  # the owner, from FREE only

# Lower-case; matched against each literal lower-cased. `python -m claudia` is covered by `claudia`.
CONSUMER_NAMES = ("claudia", "gateway-reset.sh", "ibkr-keepalive.sh", "docs/ibkr-gateway.md")


def string_literals(source: str) -> list[tuple[int, str]]:
    """Every string constant in `source` with its line — docstrings and f-string parts included."""
    return [
        (node.lineno, node.value)
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def consumer_mentions(source: str) -> list[str]:
    """Each literal in `source` that names the consumer or one of its commands or documents."""
    hits = []
    for lineno, text in string_literals(source):
        lowered = text.lower()
        hits += [f"line {lineno}: {name!r}" for name in CONSUMER_NAMES if name in lowered]
    return hits


def test_no_string_in_the_gateway_package_names_the_consumer_or_its_commands():
    offenders = {
        path.name: hits for path in sorted(GATEWAY_DIR.glob("*.py")) if (hits := consumer_mentions(path.read_text()))
    }
    assert offenders == {}, offenders


def test_the_string_probe_sees_each_form():
    """A docstring, a plain string, an f-string part, another letter case — and not a comment."""
    snippet = (
        '"""Run python -m claudia.gateway_preflight first."""\n'
        'GUIDE = "see docs/ibkr-gateway.md"\n'
        "def f(x):\n"
        "    # claudia_ui wrote this\n"
        '    return f"then ./scripts/Gateway-Reset.sh {x}"\n'
    )
    assert consumer_mentions(snippet) == [
        "line 1: 'claudia'",
        "line 2: 'docs/ibkr-gateway.md'",
        "line 5: 'gateway-reset.sh'",
    ]


# ── Condition A: the model layer never reaches the gateway package ───────────────────────────


def gateway_imports(source: str) -> list[str]:
    """Every import of the gateway package in `source`, in either form, at any depth."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [alias.name for alias in node.names if alias.name.startswith("ibkr_core_mcp.gateway")]
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.startswith("ibkr_core_mcp.gateway") or (node.level and module.split(".")[0] == "gateway"):
                found.append(f"from {'.' * node.level}{module} import …")
    return found


def test_the_model_layer_imports_nothing_from_the_gateway_package():
    """(1) Both statement forms, nested blocks included — an import under `if False:` is still
    an import the file can be made to run."""
    for filename, source in MODEL_LAYER.items():
        assert gateway_imports(source) == [], f"{filename} imports the gateway package"


def test_the_model_layer_names_no_session_write():
    """(2) Neither file names a session write — to call it, mock it or mint it."""
    for filename, source in MODEL_LAYER.items():
        hits = (names_referenced(source) | attribute_names_referenced(source)) & SESSION_WRITE_NAMES
        assert not hits, f"{filename} references {sorted(hits)}"


_M1 = (
    "class ClaudeToolkit:\n"
    "    def _get_positions(self, inputs):\n"
    "        if False:\n"
    "            from ibkr_core_mcp.gateway import GatewayManager\n"
    "\n"
    "            GatewayManager().restart()\n"
    "        return self._client.get_positions()\n"
)


def test_the_m1_probe_is_seen_by_both_checks():
    """(3) The review's probe M1: a READ_ONLY handler importing `GatewayManager` under `if False:`
    and calling `.restart()` passed 350 security tests on 2026-11-08. Both checks see it."""
    assert gateway_imports(_M1) == ["from ibkr_core_mcp.gateway import …"]
    assert (names_referenced(_M1) | attribute_names_referenced(_M1)) & SESSION_WRITE_NAMES == {"GatewayManager"}


def test_a_relative_or_plain_import_is_seen_too():
    snippet = "import ibkr_core_mcp.gateway.manager as m\nfrom .gateway.session import get_session\n"
    assert gateway_imports(snippet) == ["ibkr_core_mcp.gateway.manager", "from .gateway.session import …"]


# ── Condition A, the owner set: who may write to a session endpoint ─────────────────────────


def _functions(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def session_endpoint_callers(source: str) -> set[str]:
    """Functions in `source` that **call** a session endpoint: a sender (`requests.post`,
    `self._post`, …) whose source names one, or a method named one (`.reauthenticate()`).

    An AST walk, not a text match: every message about a borrowed session names the endpoints
    that could not clear it, and a text match counted that prose (the consumer's first guard
    did, and was allowlisted into uselessness for it).
    """
    callers: set[str] = set()
    for fn in _functions(ast.parse(source)):
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call):
                continue
            name = callee_name(node)
            if name is None:
                continue
            # A method named so, or a sender whose call text names an endpoint — `ast.unparse` of
            # the one call, not `ast.get_source_segment`, which re-splits the whole file per node
            # (over `client.py`'s thousands of calls that cost 28 s).
            named_so = SESSION_WRITE_ENDPOINTS.search(name) is not None
            sends_to = name in _SENDERS and SESSION_WRITE_ENDPOINTS.search(ast.unparse(node)) is not None
            if named_so or sends_to:
                callers.add(fn.name)
    return callers


def test_only_the_owner_set_writes_to_a_session_endpoint():
    """(4) `ssodh/init`, `/logout` and `reauthenticate` create or destroy sessions; called from
    several modules they are several authorities over one session."""
    owners = {
        str(path.relative_to(PACKAGE_DIR)): found
        for path, source in package_sources()
        if (found := session_endpoint_callers(source))
    }
    assert owners == SESSION_WRITE_OWNERS, owners


def test_the_endpoint_probe_sees_a_call_and_ignores_prose():
    sneaky = (
        "class C:\n"
        "    def sneaky(self):\n"
        '        return self._post("/logout")\n'
        "    def also(self):\n"
        "        return self._client.reauthenticate()\n"
        "    def plain(self, u):\n"
        '        return requests.post(f"{u}/iserver/auth/ssodh/init", json={})\n'
        "    def prose(self):\n"
        '        return "POST /logout could not clear it; ssodh/init raises the bridge"\n'
    )
    assert session_endpoint_callers(sneaky) == {"sneaky", "also", "plain"}


# ── Condition A, the owner set: who may drive a manager, who may open the login ─────────────


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else ""
    return ""


def _constructs_a_manager(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and _dotted(node.func).split(".")[-1] == "GatewayManager"


def manager_drivers(source: str) -> set[str]:
    """Functions in `source` that call one of `MANAGER_DRIVERS` on a constructed or bound
    `GatewayManager`. Constructing one and passing it on is not driving it."""
    tree = ast.parse(source)
    bound = {
        _dotted(target)
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign) and _constructs_a_manager(node.value)
        for target in node.targets
        if _dotted(target)
    }
    drivers: set[str] = set()
    for fn in _functions(tree):
        for node in ast.walk(fn):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in MANAGER_DRIVERS
            ):
                receiver = node.func.value
                if _constructs_a_manager(receiver) or _dotted(receiver) in bound:
                    drivers.add(fn.name)
    return drivers


def login_openers(source: str) -> set[str]:
    """Functions in `source` that call `open_login_page` or `webbrowser.open`."""
    found: set[str] = set()
    for fn in _functions(ast.parse(source)):
        for node in ast.walk(fn):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                attr = node.func.attr
                if attr == "open_login_page" or (attr == "open" and _dotted(node.func.value) == "webbrowser"):
                    found.add(fn.name)
    return found


def test_a_manager_is_driven_only_inside_the_gateway_package():
    """(5) `start`, `restart` and `stop` destroy whatever session the container holds; `startup`
    opens a login. The consumer's original defect was exactly this — a button calling
    `GatewayManager.start()` before the pre-flight that was to inspect the container."""
    driving = {str(path.relative_to(PACKAGE_DIR)) for path, source in package_sources() if manager_drivers(source)}
    assert driving <= MANAGER_DRIVING_MODULES, driving


def test_the_login_page_is_opened_only_inside_the_gateway_package():
    """Every route to a login page passes the package's own sequence."""
    opening = {str(path.relative_to(PACKAGE_DIR)) for path, source in package_sources() if login_openers(source)}
    assert opening <= LOGIN_OPENING_MODULES, opening


def test_the_driver_probe_sees_each_shape_and_lets_a_handover_through():
    snippet = (
        "from ibkr_core_mcp.gateway import GatewayManager\n"
        "def a():\n"
        "    GatewayManager().restart()\n"
        "def b():\n"
        "    gm = GatewayManager()\n"
        "    gm.stop()\n"
        "def c():\n"
        "    GatewayManager().startup()\n"
        "def handover():\n"
        "    return get_session().establish(GatewayManager(), emit=print)\n"
        "def other():\n"
        "    process.start()\n"
    )
    assert manager_drivers(snippet) == {"a", "b", "c"}
    assert login_openers(
        "def d(gm):\n    gm.open_login_page()\ndef e(u):\n    webbrowser.open(u)\ndef f(p):\n    open(p)\n"
    ) == {"d", "e"}
