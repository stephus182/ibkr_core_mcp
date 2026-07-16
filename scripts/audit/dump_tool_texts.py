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

tree = ast.parse(SRC.read_text())
tools = None
for node in ast.walk(tree):
    if isinstance(node, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id == "TOOL_DEFINITIONS" for t in node.targets
    ):
        tools = ast.literal_eval(node.value)
    elif (
        isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "TOOL_DEFINITIONS"
        and node.value is not None
    ):
        tools = ast.literal_eval(node.value)
assert tools, "TOOL_DEFINITIONS not found"

for t in tools:
    print(f"## {t['name']}\n")
    print(f"**description:** {t['description']}\n")
    print("**input_schema:**\n```json")
    print(json.dumps(t.get("input_schema", {}), indent=2))
    print("```\n")
