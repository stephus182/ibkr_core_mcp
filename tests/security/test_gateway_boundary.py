"""Security constitution, register F45 — the gateway package is the consumer-independent home
of the IBKR session, and the model layer never reaches it.

Started with the string rule (step 1, commit 3/13); condition A's five checks arrive with
commit 5/13 and widen in step 2.

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

import pytest

from .structural import PACKAGE_DIR

pytestmark = pytest.mark.security

GATEWAY_DIR = PACKAGE_DIR / "gateway"

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
