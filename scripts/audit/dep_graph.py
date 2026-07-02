#!/usr/bin/env python3
"""WS2b — extract the intra-class call graph of ClaudeToolkit via AST.

For every method of ClaudeToolkit, list which other ClaudeToolkit methods it calls
(self.<name>(...)). This is the precondition graph from docs/plans/2026-06-27-
architecture-notes.md. Output: JSON adjacency map + mermaid flowchart on stdout.

Usage: python scripts/audit/dep_graph.py ibkr_core_mcp/claude_tools.py
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path


def main() -> None:
    src = Path(sys.argv[1]).read_text()
    tree = ast.parse(src)
    cls = next(n for n in ast.walk(tree)
               if isinstance(n, ast.ClassDef) and n.name == "ClaudeToolkit")
    methods = {n.name for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}

    graph: dict[str, list[str]] = {}
    for fn in cls.body:
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        calls = set()
        for node in ast.walk(fn):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "self"
                    and node.func.attr in methods
                    and node.func.attr != fn.name):
                calls.add(node.func.attr)
        if calls:
            graph[fn.name] = sorted(calls)

    Path("docs/superpowers/audit-evidence/dep_graph.json").write_text(
        json.dumps(graph, indent=2))

    print("```mermaid\nflowchart LR")
    for src_m, targets in sorted(graph.items()):
        for t in targets:
            print(f"    {src_m} --> {t}")
    print("```")


if __name__ == "__main__":
    main()
