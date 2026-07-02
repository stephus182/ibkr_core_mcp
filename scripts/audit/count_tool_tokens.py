#!/usr/bin/env python3
"""WS1a — measure token weight of the ClaudIA tool surface via count_tokens.

Counts (all exact, per https://platform.claude.com/docs/en/docs/build-with-claude/token-counting):
  - baseline: messages only (isolates the tool-use system overhead)
  - full toolkit payload (TOOL_DEFINITIONS + claudia _LOCAL_TOOLS [+ optional TV tools])
  - leave-one-out marginal cost per tool
  - system prompt (claudia context.md + principles.md)

Usage:
  python scripts/audit/count_tool_tokens.py \
      --env-file /Users/steph/Claude_Projects/claudia_ui/.env \
      --out docs/superpowers/audit-evidence/token_counts.json \
      [--extra-tools path/to/extra_tools.json]   # e.g. layer-2 projection or TV dump
"""
from __future__ import annotations

import argparse
import ast
import json
import os
from pathlib import Path

import anthropic
from dotenv import load_dotenv

CLAUDIA = Path("/Users/steph/Claude_Projects/claudia_ui")
MSG = [{"role": "user", "content": "hello"}]


def literal_assign(py_file: Path, name: str):
    """Extract a module-level literal assignment (handles both x = ... and x: T = ...)."""
    tree = ast.parse(py_file.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == name and node.value is not None:
                return ast.literal_eval(node.value)
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            t = node.targets[0]
            if isinstance(t, ast.Name) and t.id == name:
                return ast.literal_eval(node.value)
    raise SystemExit(f"{name} not found as a literal in {py_file}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--env-file", default=str(CLAUDIA / ".env"))
    p.add_argument("--model", default=os.environ.get("CLAUDIA_MODEL", "claude-opus-4-8"))
    p.add_argument("--out", required=True)
    p.add_argument("--extra-tools", help="JSON file with additional tool dicts to include")
    args = p.parse_args()

    load_dotenv(args.env_file)
    client = anthropic.Anthropic()

    repo = Path(__file__).resolve().parents[2]
    toolkit_tools = literal_assign(repo / "ibkr_core_mcp" / "claude_tools.py", "TOOL_DEFINITIONS")
    local_tools = literal_assign(CLAUDIA / "claudia" / "agent.py", "_LOCAL_TOOLS")
    extra = json.loads(Path(args.extra_tools).read_text()) if args.extra_tools else []
    all_tools = toolkit_tools + local_tools + extra

    def count(**kw) -> int:
        return client.messages.count_tokens(model=args.model, messages=MSG, **kw).input_tokens

    baseline = count()
    full = count(tools=all_tools)

    marginals: dict[str, int] = {}
    for i, tool in enumerate(all_tools):
        without = all_tools[:i] + all_tools[i + 1:]
        marginals[tool["name"]] = full - count(tools=without)

    # System prompt = context.md + principles.md (Drive overrides may differ slightly;
    # this measures the committed baseline, which is what rides on most calls).
    sys_text = (CLAUDIA / "docs" / "context.md").read_text() + (
        CLAUDIA / "docs" / "principles.md"
    ).read_text()
    system_tokens = count(system=sys_text) - baseline

    result = {
        "model": args.model,
        "baseline_no_tools": baseline,
        "full_payload_with_tools": full,
        "tool_surface_total": full - baseline,
        "system_prompt_tokens": system_tokens,
        "static_prefix_total": (full - baseline) + system_tokens,
        "tool_count": len(all_tools),
        "per_tool_marginal": dict(sorted(marginals.items(), key=lambda kv: -kv[1])),
    }
    Path(args.out).write_text(json.dumps(result, indent=2))

    print(f"model={args.model}  tools={len(all_tools)}")
    print(f"tool surface: {result['tool_surface_total']:,} tok   "
          f"system prompt: {system_tokens:,} tok   "
          f"static prefix/call: {result['static_prefix_total']:,} tok")
    print("\ntop 10 heaviest tools:")
    for name, tok in list(result["per_tool_marginal"].items())[:10]:
        print(f"  {tok:6,}  {name}")


if __name__ == "__main__":
    main()
