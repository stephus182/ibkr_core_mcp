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
from collections.abc import Iterable, Iterator
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


def _template(node: ast.expr) -> str | None:
    """A string literal or f-string as a template, `{}` standing for each interpolation."""
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
    return None


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
    found: dict[str, set[str]] = {}
    for fn in _functions(_tree(source)):
        for stmt in _body_without_docstring(fn):
            for node in ast.walk(stmt):
                if isinstance(node, ast.expr):
                    template = _template(node)
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
        elif isinstance(node, ast.Attribute):
            base = node.value
            if isinstance(base, ast.Name) and base.id == "os" and _SPAWN_OS_ATTRS.match(node.attr):
                sites.add(f"os.{node.attr}")
            if isinstance(base, ast.Name) and base.id == "asyncio" and node.attr.startswith("create_subprocess"):
                sites.add(f"asyncio.{node.attr}")
    return sites


def shell_true_keywords(source: str) -> list[int]:
    """Line numbers of any call passing `shell=True`."""
    lines: list[int] = []
    for node in ast.walk(_tree(source)):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                    lines.append(node.lineno)
    return lines
