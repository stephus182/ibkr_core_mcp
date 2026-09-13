#!/usr/bin/env python3
"""WS3 — dump every tool's Claude-facing text to one markdown file for side-by-side
review against scraped official docs. No imports of the package (AST only).

Usage: python scripts/audit/dump_tool_texts.py > docs/audits/audit-evidence/tool_texts.md
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "ibkr_core_mcp" / "claude_tools.py"


def _public_definitions(node: ast.expr) -> list[dict[str, object]]:
    """`ast.literal_eval` of TOOL_DEFINITIONS with each entry's `capabilities` dropped.

    The field (2026-09-13) is a `frozenset(...)` call — not a literal — and is stripped by
    `ClaudeToolkit.tools` before the schema reaches the API, so the text and token counts
    measured here stay those of the real payload.
    """
    assert isinstance(node, ast.List)
    public: list[dict[str, object]] = []
    for entry in node.elts:
        assert isinstance(entry, ast.Dict)
        kept = [
            (k, v)
            for k, v in zip(entry.keys, entry.values, strict=True)
            if not (isinstance(k, ast.Constant) and k.value == "capabilities")
        ]
        public.append(ast.literal_eval(ast.Dict(keys=[k for k, _ in kept], values=[v for _, v in kept])))
    return public


tree = ast.parse(SRC.read_text())
tools = None
for node in ast.walk(tree):
    if isinstance(node, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id == "TOOL_DEFINITIONS" for t in node.targets
    ):
        tools = _public_definitions(node.value)
    elif (
        isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "TOOL_DEFINITIONS"
        and node.value is not None
    ):
        tools = _public_definitions(node.value)
assert tools, "TOOL_DEFINITIONS not found"

for t in tools:
    print(f"## {t['name']}\n")
    print(f"**description:** {t['description']}\n")
    print("**input_schema:**\n```json")
    print(json.dumps(t.get("input_schema", {}), indent=2))
    print("```\n")
