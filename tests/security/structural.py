"""AST helpers for the structural security tests.

These answer questions like "which functions in this module build an order-endpoint
URL?" or "which modules import subprocess?" from source, not from behaviour. A
behavioural test needs an input that reaches the code; a structural one sees the code
whether or not anything calls it yet — which is the point when the thing being guarded
against is a *new* call site (docs/audits/security-architecture-audit-2026-09-13.md,
Phase 4).

Every checker takes source text (or a path) and returns plain data, so each test file
can feed it a deliberately-violating snippet and prove the checker still fires.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable, Iterator, Mapping
from functools import lru_cache
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parents[2] / "ibkr_core_mcp"
SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"


def package_sources() -> Iterator[tuple[Path, str]]:
    """Every `.py` under the package, as (path, source)."""
    for path in sorted(PACKAGE_DIR.rglob("*.py")):
        yield path, path.read_text()


@lru_cache(maxsize=64)
def _tree(source: str) -> ast.Module:
    """Parse once per distinct source text: the security tests re-read the same two large
    modules dozens of times per session (review 2026-09-13)."""
    return ast.parse(source)


def callee_name(call: ast.Call) -> str | None:
    """The name a call invokes — bare (`f(...)`) or the last attribute (`a.b.f(...)`)."""
    f = call.func
    return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None


_PERCENT_PLACEHOLDER = re.compile(r"%[-+ #0-9.*]*[hlL]?[diouxXeEfFgGcrsa%]")


def _template(node: ast.expr, names: Mapping[str, str] | None = None, depth: int = 0) -> str | None:
    """A string expression rendered as a template, `{}` standing for each interpolation.

    Handles the ordinary Python spellings of "build a URL", not just the one this codebase
    happens to use. Until 2026-09-16 only `ast.Constant` and `ast.JoinedStr` were
    reconstructed, so `"/iserver/account/" + acct + "/orders"`, the `%` form, `str.join`
    and a module-level constant were all invisible to
    `functions_using_url_templates` — and therefore to the test asserting that order-write
    URLs are built only inside the gated methods. A new gate-free call site written in any
    of them would have passed `pytest -m security` silently. `names` carries module-level
    and already-assigned local string constants so a URL built across two statements is
    still seen.

    Returns None when the node is not a string-shaped expression, so a caller can tell
    "not a string" from "a string with no literal parts".
    """
    if depth > 10:  # pathological nesting; refuse rather than recurse forever
        return None
    names = names or {}

    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value

    if isinstance(node, ast.JoinedStr):
        parts = []
        for value in node.values:
            if isinstance(value, ast.Constant):
                parts.append(str(value.value))
            else:
                parts.append("{}")
        return "".join(parts)

    if isinstance(node, ast.Name):
        return names.get(node.id)

    # "a" + x + "b"
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _template(node.left, names, depth + 1)
        right = _template(node.right, names, depth + 1)
        if left is None and right is None:
            return None
        return (left if left is not None else "{}") + (right if right is not None else "{}")

    # "a%sb" % x
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        left = _template(node.left, names, depth + 1)
        if left is None:
            return None
        return _PERCENT_PLACEHOLDER.sub(lambda m: "%" if m.group(0) == "%%" else "{}", left)

    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        owner = _template(node.func.value, names, depth + 1)
        # "sep".join([...])
        if node.func.attr == "join" and owner is not None and node.args:
            seq = node.args[0]
            if isinstance(seq, (ast.List, ast.Tuple)):
                parts = [_template(e, names, depth + 1) or "{}" for e in seq.elts]
                return owner.join(parts)
            return None
        # "a{}b".format(x) — the literal already carries its own placeholders
        if node.func.attr == "format" and owner is not None:
            return owner

    return None


def _string_assignments(statements: Iterable[ast.stmt], names: dict[str, str]) -> None:
    """Record `NAME = <string expression>` into `names`, in statement order."""
    for stmt in statements:
        if isinstance(stmt, ast.Assign):
            rendered = _template(stmt.value, names)
            if rendered is None:
                continue
            for target in stmt.targets:
                if isinstance(target, ast.Name):
                    names[target.id] = rendered


def _functions(tree: ast.AST) -> Iterator[ast.FunctionDef | ast.AsyncFunctionDef]:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def _body_without_docstring(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.stmt]:
    body = fn.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        return body[1:]
    return body


def functions_using_url_templates(source: str, patterns: Iterable[str]) -> dict[str, set[str]]:
    """Map each function name to the URL templates in its body (docstring excluded) that
    match any of `patterns` (regexes over the `{}`-templated form)."""
    compiled = [re.compile(p) for p in patterns]
    tree = _tree(source)
    # Module-level string constants are visible to every function, so a URL parked in one
    # and formatted inside a method is still that method's call site.
    module_names: dict[str, str] = {}
    _string_assignments(getattr(tree, "body", []), module_names)

    found: dict[str, set[str]] = {}
    for fn in _functions(tree):
        names = dict(module_names)
        body = _body_without_docstring(fn)
        for stmt in body:
            # Resolve assignments as they are reached, so a URL assembled across several
            # statements is reconstructed rather than lost at the first local variable.
            _string_assignments([stmt], names)
            for node in ast.walk(stmt):
                if isinstance(node, ast.expr):
                    template = _template(node, names)
                    if template is not None and any(c.search(template) for c in compiled):
                        found.setdefault(fn.name, set()).add(template)
    return found


def attribute_names_referenced(source: str) -> set[str]:
    """Every `<something>.<attr>` attribute name read or called anywhere in `source`."""
    return {node.attr for node in ast.walk(_tree(source)) if isinstance(node, ast.Attribute)}


def names_referenced(source: str) -> set[str]:
    """Every bare `Name` (loads, stores, calls) anywhere in `source`."""
    return {node.id for node in ast.walk(_tree(source)) if isinstance(node, ast.Name)}


def functions_calling(source: str, callee: str) -> set[str]:
    """Names of functions whose body calls `callee` (as a bare name or an attribute)."""
    return {fn.name for fn in _functions(_tree(source)) if call_lines(fn, (callee,))}


def call_lines(fn: ast.FunctionDef | ast.AsyncFunctionDef, callees: Iterable[str]) -> list[int]:
    """Line numbers of calls to any of `callees` inside `fn`."""
    wanted = set(callees)
    lines: list[int] = []
    for stmt in _body_without_docstring(fn):
        for node in ast.walk(stmt):
            if isinstance(node, ast.Call) and callee_name(node) in wanted:
                lines.append(node.lineno)
    return sorted(lines)


def function_named(source: str, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    for fn in _functions(_tree(source)):
        if fn.name == name:
            return fn
    raise KeyError(name)


_SPAWN_MODULES = frozenset({"subprocess", "multiprocessing", "webbrowser"})
_SPAWN_OS_ATTRS = re.compile(r"^(system|popen|spawn\w*|exec\w*|fork\w*|posix_spawn\w*)$")


def spawn_sites(source: str) -> set[str]:
    """Descriptions of every process-spawning construct in `source`: a spawn-module import,
    an `os.system`/`os.popen`/`os.spawn*`/`os.exec*`/`os.fork*` attribute, or an
    `asyncio.create_subprocess_*` call."""
    sites: set[str] = set()
    for node in ast.walk(_tree(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in _SPAWN_MODULES:
                    sites.add(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".")[0]
            if root in _SPAWN_MODULES:
                sites.add(f"from {node.module} import …")
            elif root == "os":
                # `os` is not a spawn module, so importing the function out of it slipped
                # past both rules: the module rule above does not match, and `system('x')`
                # is a plain Name call rather than the `os.system` attribute the rule below
                # looks for. Same names, different spelling, invisible (SEC-08, 2026-09-17).
                # Matched on the imported name, not the local one, so `as` cannot hide it.
                for alias in node.names:
                    if _SPAWN_OS_ATTRS.match(alias.name):
                        sites.add(f"from os import {alias.name}")
        elif isinstance(node, ast.Attribute):
            base = node.value
            if isinstance(base, ast.Name) and base.id == "os" and _SPAWN_OS_ATTRS.match(node.attr):
                sites.add(f"os.{node.attr}")
            if isinstance(base, ast.Name) and base.id == "asyncio" and node.attr.startswith("create_subprocess"):
                sites.add(f"asyncio.{node.attr}")
    return sites


def keyword_literal_lines(source: str, keyword: str, value: object) -> list[int]:
    """Line numbers of every call passing `keyword=<value>` as a literal.

    The general form of `shell_true_keywords`: "nothing in the package passes this dangerous
    keyword" is one check whether the keyword is `shell=True` on a subprocess call or
    `validate_input=False` on the MCP call-tool decorator. The comparison is identity, so
    `value` is meant to be a singleton — `True`, `False`, `None`.
    """
    lines: list[int] = []
    for node in ast.walk(_tree(source)):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == keyword and isinstance(kw.value, ast.Constant) and kw.value.value is value:
                    lines.append(node.lineno)
    return sorted(lines)


def shell_true_keywords(source: str) -> list[int]:
    """Line numbers of any call passing `shell=True`."""
    return keyword_literal_lines(source, "shell", True)


def path_interpolations(source: str) -> list[tuple[str, str, str]]:
    """Every value interpolated into a URL path, as (function, expression, path literal).

    A path literal is an f-string whose constant parts begin with "/" and contain no
    whitespace. The whitespace rule is not cosmetic: without it this reports
    `get_live_orders`' error message, which begins "/iserver/account/orders returned …"
    and is not a URL at all.

    This answers invariant 9 ("every path-interpolated identifier passes its regex"),
    which until 2026-09-16 had no test and was false for three methods.
    """
    found: list[tuple[str, str, str]] = []
    for node in ast.walk(_tree(source)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            if not isinstance(inner, ast.JoinedStr):
                continue
            literal = "".join(v.value for v in inner.values if isinstance(v, ast.Constant) and isinstance(v.value, str))
            if not literal.startswith("/") or any(c.isspace() for c in literal):
                continue
            for value in inner.values:
                if isinstance(value, ast.FormattedValue):
                    found.append((node.name, ast.unparse(value.value), literal))
    return found


def arguments_passed_to(source: str, function: str, callees: Iterable[str]) -> set[str]:
    """Every expression `function` passes to one of `callees`, unparsed.

    Asking "does this function validate *anything*" is not the question invariant 9 poses.
    A method can validate its account id and interpolate an unchecked page number in the
    same URL — `get_positions` did exactly that — so the check has to be per value.
    """
    wanted = set(callees)
    fn = function_named(source, function)
    passed: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and callee_name(node) in wanted:
            passed.update(ast.unparse(a) for a in node.args)
    return passed


def methods_reaching_the_network(source: str, primitives: Iterable[str]) -> set[str]:
    """Every method that reaches the network, directly or through another method.

    `test_order_write_boundary` asked only whether a gated method calls `_get`/`_post`
    itself. Its stated property is broader — "gate before first network call" — and
    `_ensure_accounts_initialized()` satisfied the check while issuing
    `GET /iserver/accounts`, because the request is one call deeper
    (release-readiness audit 2026-09-16, SEC-02). The fixed point below closes that gap for
    any depth, so a helper introduced tomorrow is covered without being named.
    """
    direct = set(primitives)
    callers: dict[str, set[str]] = {}
    for fn in _functions(_tree(source)):
        callees: set[str] = set()
        for stmt in _body_without_docstring(fn):
            for node in ast.walk(stmt):
                if isinstance(node, ast.Call):
                    name = callee_name(node)
                    if name:
                        callees.add(name)
        callers[fn.name] = callees

    reaching = {name for name, callees in callers.items() if callees & direct}
    while True:
        grown = {name for name, callees in callers.items() if callees & reaching}
        if grown <= reaching:
            return reaching | direct
        reaching |= grown
