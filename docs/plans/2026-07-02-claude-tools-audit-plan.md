# claude_tools.py Full Audit — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute the audit specified in `docs/2026-07-02-claude-tools-audit-design.md` — measure token/latency reality, review all 42 tool handlers, verify every tool's documentation against official sources — and produce `docs/claude-tools-audit-2026-07.md` with decisions D1–D5, then apply the D5 documentation verdicts to `claude_tools.py`.

**Architecture:** Three evidence workstreams (WS1 quantify, WS2 code audit, WS3 docs verification) feed one synthesis. Reusable measurement scripts live in `scripts/audit/` (committed). Raw evidence (JSON, JSONL, scrapes) lives in `docs/superpowers/audit-evidence/` — inside the already-gitignored `docs/superpowers/` tree, so it persists locally without bloating the repo. The only production-code change is Task 13 (doc-text edits per D5).

**Tech Stack:** Python 3.11+ (`.venv` of ibkr_core_mcp), Anthropic SDK (`count_tokens` — free endpoint, verified 2026-07-02 at https://platform.claude.com/docs/en/docs/build-with-claude/token-counting), Firecrawl (scrapes), `ast` (static analysis), pytest/ruff/mypy (regression gates).

**Repos:** `ibkr_core_mcp` (this repo) and `claudia_ui` at `/Users/steph/Claude_Projects/claudia_ui` (temporary instrumentation, later reverted).

---

## Prerequisites (check before starting)

- [ ] `source /Users/steph/Claude_Projects/ibkr_core_mcp/.venv/bin/activate` works and `python -c "import anthropic"` succeeds.
- [ ] `ANTHROPIC_API_KEY` available (claudia_ui `.env` has it; Tasks 2–3 load it via `dotenv`).
- [ ] For Task 5 only: IBKR gateway running + authenticated (per CLAUDE.md: `GatewayManager().startup()`, log in via Chrome at `https://localhost:5055`). Requires the owner at the machine.
- [ ] For Task 10: `FIRECRAWL_API_KEY` in claudia_ui `.env` (or use the Firecrawl skill/CLI available in the Claude Code environment).

## File Structure

| Path | Role |
|---|---|
| `scripts/audit/count_tool_tokens.py` | Create — WS1a token measurement (rerunnable; also used after Task 13 to verify deltas) |
| `scripts/audit/dep_graph.py` | Create — WS2b intra-class call-graph extractor (AST) |
| `scripts/audit/dump_tool_texts.py` | Create — WS3 helper: dump every tool's name/description/input_schema to one markdown file |
| `scripts/audit/analyze_timing.py` | Create — WS1b JSONL → per-turn latency decomposition table |
| `docs/superpowers/audit-evidence/` | Local-only evidence: JSON results, timing JSONL, scraped pages |
| `docs/claude-tools-audit-2026-07.md` | Create — the audit report (decision summary + appendices A–G) |
| `/Users/steph/Claude_Projects/claudia_ui/claudia/_timing.py` | Create temporarily — opt-in JSONL timing logger; **deleted in Task 6** |
| `/Users/steph/Claude_Projects/claudia_ui/claudia/agent.py` | Modify temporarily — timing emits; **reverted in Task 6** |
| `ibkr_core_mcp/claude_tools.py` | Modify in Task 13 only — D5 doc-text edits (descriptions/docstrings), nothing structural |

Note on TDD: this is an audit — most tasks produce measurements and documents, not behavior, so there is nothing to test-drive. The scripts are verified by running them against known inputs (each task states the expected output). Task 13 (the only production change) is gated by the full existing test suite plus ruff/mypy.

---

### Task 1: Scaffold — evidence directory + report skeleton

**Files:**
- Create: `docs/superpowers/audit-evidence/` (directory)
- Create: `docs/claude-tools-audit-2026-07.md`

- [ ] **Step 1: Create the evidence directory**

```bash
mkdir -p /Users/steph/Claude_Projects/ibkr_core_mcp/docs/superpowers/audit-evidence/scrapes
```

- [ ] **Step 2: Create the report skeleton**

Write `docs/claude-tools-audit-2026-07.md` with exactly this content (sections are filled by later tasks; the skeleton states its own status so a half-finished report is never mistaken for a finished one):

```markdown
# claude_tools.py Audit — 2026-07

**Status:** IN PROGRESS — sections below are filled as workstreams complete.
**Spec:** docs/2026-07-02-claude-tools-audit-design.md
**Model used for all token counts:** claude-opus-4-8 (ClaudIA default)

## Decision summary

| # | Decision | Outcome | Evidence |
|---|---|---|---|
| D1 | Where ClaudIA slowness comes from | _pending — Task 12_ | Appendix B |
| D2 | Split go/no-go + architecture | _pending — Task 12_ | Appendices C, D, E |
| D3 | Tool-exposure strategy | _pending — Task 12_ | Appendices A, B, E |
| D4 | Sequencing vs. scraping-RAG layer 2 | _pending — Task 12_ | Appendices A, E |
| D5 | Documentation verdicts | _pending — Task 12_ | Appendix G |

## Appendix A — Token weight (WS1a)
_pending — Tasks 2–3_

## Appendix B — Latency decomposition (WS1b)
_pending — Tasks 4–6_

## Appendix C — Code findings table (WS2a)
_pending — Task 8_

## Appendix D — Cross-domain dependency graph (WS2b)
_pending — Task 7_

## Appendix E — Structural assessment (WS2c/2d)
_pending — Task 9_

## Appendix F — Tool → authoritative-source map (WS3a)
_pending — Task 10_

## Appendix G — Docs verdict table (WS3b/3c)
_pending — Task 11_
```

- [ ] **Step 3: Commit**

```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
git add docs/claude-tools-audit-2026-07.md
git commit -m "docs: audit report skeleton (claude_tools.py audit)"
```

---

### Task 2: WS1a — token measurement script

**Files:**
- Create: `scripts/audit/count_tool_tokens.py`
- Output: `docs/superpowers/audit-evidence/token_counts.json`

Method: leave-one-out. Counting a payload with all 42 tools, then 42 payloads each missing one tool, gives each tool's exact marginal cost (`all − without_i`), immune to the fixed tool-use system-prompt overhead the API adds. Baseline (no tools) isolates that overhead. ~46 free API calls (rate limit 2,000/min — no throttling needed).

- [ ] **Step 1: Write the script**

```python
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
```

- [ ] **Step 2: Run it**

```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
.venv/bin/python scripts/audit/count_tool_tokens.py \
    --out docs/superpowers/audit-evidence/token_counts.json
```

Expected: prints model, tool count (42 toolkit + 3 local = 45), totals, and a ranked top-10; JSON written. Sanity checks: every marginal > 0; `tool_surface_total` within ~2% of the sum of marginals (small interaction effects are normal); `static_prefix_total` plausibly in the thousands-to-tens-of-thousands range.

- [ ] **Step 3: TradingView tools — measure or record the gap**

If TradingView Desktop + the bridge are running, dump its tool list from the claudia venv and rerun with `--extra-tools`:

```bash
cd /Users/steph/Claude_Projects/claudia_ui
.venv/bin/python -c "
import json
from claudia.tradingview import TradingViewBridge   # class at claudia/tradingview.py:224
b = TradingViewBridge()
print(json.dumps(b.get_tools()))                    # sync method, tradingview.py:335
" > /Users/steph/Claude_Projects/ibkr_core_mcp/docs/superpowers/audit-evidence/tv_tools.json
```

If the bridge is not available (TradingView Desktop closed), do **not** fake it: record in Appendix A that TV tools (tradingview-mcp advertises 78 tools) were unmeasured and are an additional payload rider whenever the bridge is connected — with a one-line rerun instruction.

- [ ] **Step 4: Fill Appendix A (first half) in the report**

Copy into `docs/claude-tools-audit-2026-07.md` Appendix A: the totals block and the full ranked per-tool table (all 45 rows) from `token_counts.json`, plus the TV note from Step 3.

- [ ] **Step 5: Commit**

```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
git add scripts/audit/count_tool_tokens.py docs/claude-tools-audit-2026-07.md
git commit -m "audit(ws1a): token measurement script + ranked per-tool cost table"
```

---

### Task 3: WS1a — scraping-RAG layer-2 projection

**Files:**
- Create: `docs/superpowers/audit-evidence/layer2_tools.json`
- Modify: `docs/claude-tools-audit-2026-07.md` (Appendix A, second half)

- [ ] **Step 1: Write the three layer-2 tool schemas as a fixture**

Transcribe from the approved spec (`claudia_ui/docs/superpowers/specs/2026-07-01-scraping-rag-pipeline-design.md`, "Layer 2 — Tools" section) into `docs/superpowers/audit-evidence/layer2_tools.json`:

```json
[
  {
    "name": "list_web_docs",
    "description": "Enumerate all scraped web documents stored in Drive web_docs/. Metadata-only filters; returns the complete set with doc_id, kind, source_url, title, content_hash, saved_at, site, stale.",
    "input_schema": {
      "type": "object",
      "properties": {
        "kind": {"type": "string", "enum": ["crawl_page", "search_snapshot"], "description": "Filter by document kind (default: both)"},
        "url_contains": {"type": "string", "description": "Substring match on source_url or query (metadata only, not content)"}
      }
    }
  },
  {
    "name": "read_web_doc",
    "description": "Fetch one stored web document's full markdown by doc_id. Returns doc_id, source_url, title, saved_at, content_hash, markdown.",
    "input_schema": {
      "type": "object",
      "properties": {"doc_id": {"type": "string", "description": "Drive file id from list_web_docs"}},
      "required": ["doc_id"]
    }
  },
  {
    "name": "delete_web_docs",
    "description": "Delete stored web documents by exactly one selector: doc_id (single doc), site (whole crawled site), or older_than_days (prune old snapshots). Scoped to Drive web_docs/ only.",
    "input_schema": {
      "type": "object",
      "properties": {
        "doc_id": {"type": "string", "description": "Delete a single doc"},
        "site": {"type": "string", "description": "Delete a whole crawled site (folder + manifest)"},
        "older_than_days": {"type": "integer", "description": "Prune snapshots older than N days"}
      }
    }
  }
]
```

(These are projections for measurement — final schemas are decided when layer 2 is built.)

- [ ] **Step 2: Run the projection**

```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
.venv/bin/python scripts/audit/count_tool_tokens.py \
    --extra-tools docs/superpowers/audit-evidence/layer2_tools.json \
    --out docs/superpowers/audit-evidence/token_counts_with_layer2.json
```

Expected: tool count 48; new `tool_surface_total`. The layer-2 delta = this total minus Task 2's total.

- [ ] **Step 3: Complete Appendix A**

Add to the report: the layer-2 delta in absolute tokens and as % of the current tool surface — this is the D4 input ("does layer 2 meaningfully heavy the payload?").

- [ ] **Step 4: Commit**

```bash
git add docs/claude-tools-audit-2026-07.md
git commit -m "audit(ws1a): layer-2 token projection — D4 input"
```

---

### Task 4: WS1b — temporary timing instrumentation in claudia_ui

**Files:**
- Create: `/Users/steph/Claude_Projects/claudia_ui/claudia/_timing.py` (temporary)
- Modify: `/Users/steph/Claude_Projects/claudia_ui/claudia/agent.py` (temporary; anchors verified 2026-07-02: `handle_message` at line 299, stream open at 335, event loop at 342, tool-exec loop at 399–412)

Do **not** commit these changes — they are working-tree-only and reverted in Task 6.

- [ ] **Step 1: Create the logger module**

```python
"""Opt-in JSONL timing logger for the 2026-07 audit. Active only when
CLAUDIA_TIMING is set to a writable file path. TEMPORARY — delete after WS1b."""
from __future__ import annotations

import json
import os
import time

_PATH = os.environ.get("CLAUDIA_TIMING")


def emit(event: str, **fields: object) -> None:
    if not _PATH:
        return
    fields["event"] = event
    fields["t"] = time.monotonic()
    with open(_PATH, "a") as f:
        f.write(json.dumps(fields) + "\n")
```

- [ ] **Step 2: Instrument `agent.py`**

Add the import near the other module imports at the top of the file:

```python
from claudia._timing import emit
```

In `handle_message` (line 299), immediately after the docstring:

```python
        emit("user_message")
        api_turn = 0
```

Immediately before `async with self._client.messages.stream(` (line 335):

```python
            api_turn += 1
            first_event = False
            emit("api_call_start", turn=api_turn)
```

Inside the event loop, immediately after `etype = event.type` (line 343):

```python
                    if not first_event:
                        first_event = True
                        emit("first_event", turn=api_turn)
                    if etype == "message_start":
                        u = event.message.usage
                        emit("usage", turn=api_turn,
                             input_tokens=u.input_tokens,
                             cache_read=getattr(u, "cache_read_input_tokens", 0) or 0)
```

Immediately after the `async with ... as stream:` block closes (after line 362's loop ends, at the `# --- Stream complete ---` comment, line 364):

```python
            emit("stream_end", turn=api_turn, stop_reason=stop_reason)
```

In the tool-execution loop, wrap each execution — immediately before `async with cl.Step(name=tc["name"], type="tool") as step:` (line 402):

```python
                emit("tool_start", turn=api_turn, name=tc["name"])
```

and immediately after `step.output = result_text` (line 412):

```python
                emit("tool_end", turn=api_turn, name=tc["name"])
```

Finally, right after the `break` exits the `while True` loop (i.e., first statement after the loop):

```python
        emit("message_done", turns=api_turn)
```

- [ ] **Step 3: Smoke-test the logger without the UI**

```bash
cd /Users/steph/Claude_Projects/claudia_ui
CLAUDIA_TIMING=/tmp/timing_smoke.jsonl .venv/bin/python -c "
from claudia._timing import emit
emit('user_message'); emit('message_done', turns=0)
"
cat /tmp/timing_smoke.jsonl
```

Expected: two JSON lines with `event` and monotonic `t` fields.

---

### Task 5: WS1b — scripted sessions + analysis

**Files:**
- Create: `scripts/audit/analyze_timing.py` (in ibkr_core_mcp)
- Output: `docs/superpowers/audit-evidence/timing_run{1,2,3}.jsonl`
- Modify: `docs/claude-tools-audit-2026-07.md` (Appendix B)

Needs the owner at the machine: gateway login (Chrome + 2FA) and typing the scripted messages into Chainlit.

- [ ] **Step 1: Start gateway + ClaudIA with timing enabled**

```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
.venv/bin/python -c "from ibkr_core_mcp import GatewayManager; GatewayManager().startup()"
# log in at https://localhost:5055 (Chrome, 2FA), wait for "Client login succeeds"

cd /Users/steph/Claude_Projects/claudia_ui
CLAUDIA_TIMING=/Users/steph/Claude_Projects/ibkr_core_mcp/docs/superpowers/audit-evidence/timing_run1.jsonl \
  .venv/bin/chainlit run app.py   # or the project's usual launch command — check claudia_ui README/Makefile
```

- [ ] **Step 2: Run the scripted session — these 8 messages, verbatim, in order**

1. `Hello — summarize what you can do in two sentences.` (no-tool baseline)
2. `What are my current positions?`
3. `Fetch 6 months of daily AAPL history and add RSI and MACD.`
4. `Run a backtest on AAPL: buy when RSI < 30, sell when RSI > 70.`
5. `Show a market snapshot for AAPL, MSFT and the ES future.`
6. `What were my trades this week, and what's my realized P&L?`
7. `Generate PineScript for the backtest strategy you just ran.`
8. `List everything you have in the market-data cache.`

Repeat the whole session 3 times total (fresh chat each time, `CLAUDIA_TIMING` pointed at `timing_run2.jsonl`, `timing_run3.jsonl`), same market-hours condition, timestamps noted.

- [ ] **Step 3: Write the analyzer**

```python
#!/usr/bin/env python3
"""WS1b — turn timing JSONL into a per-message latency decomposition table.

Usage: python scripts/audit/analyze_timing.py evidence/timing_run1.jsonl [run2 run3 ...]
Emits a markdown table: per user message (position in session), median across runs of
  ttft        first_event − api_call_start  (turn 1)   — prompt processing
  stream      stream_end − api_call_start   (sum over turns)
  tools       Σ(tool_end − tool_start)
  api_turns   number of API calls for that message
  total       message_done − user_message
  residual    total − stream − tools        — history load, persistence, Chainlit steps
"""
from __future__ import annotations

import json
import statistics
import sys


def parse_run(path: str) -> list[dict]:
    msgs, cur = [], None
    for line in open(path):
        e = json.loads(line)
        if e["event"] == "user_message":
            cur = {"start": e["t"], "calls": {}, "tools": 0.0, "pending": {}}
            msgs.append(cur)
        elif cur is None:
            continue
        elif e["event"] == "api_call_start":
            cur["calls"][e["turn"]] = {"start": e["t"]}
        elif e["event"] == "first_event":
            cur["calls"][e["turn"]]["first"] = e["t"]
        elif e["event"] == "stream_end":
            cur["calls"][e["turn"]]["end"] = e["t"]
        elif e["event"] == "tool_start":
            cur["pending"][e["name"]] = e["t"]
        elif e["event"] == "tool_end":
            cur["tools"] += e["t"] - cur["pending"].pop(e["name"])
        elif e["event"] == "message_done":
            cur["end"] = e["t"]
    out = []
    for m in msgs:
        if "end" not in m:
            continue  # aborted message
        calls = sorted(m["calls"].items())
        stream = sum(c["end"] - c["start"] for _, c in calls if "end" in c)
        ttft = calls[0][1].get("first", calls[0][1]["start"]) - calls[0][1]["start"]
        total = m["end"] - m["start"]
        out.append({"ttft": ttft, "stream": stream, "tools": m["tools"],
                    "turns": len(calls), "total": total,
                    "residual": total - stream - m["tools"]})
    return out


def main() -> None:
    runs = [parse_run(p) for p in sys.argv[1:]]
    n = min(len(r) for r in runs)
    print("| msg # | ttft (s) | stream (s) | tools (s) | api turns | total (s) | residual (s) |")
    print("|---|---|---|---|---|---|---|")
    for i in range(n):
        med = lambda k: statistics.median(r[i][k] for r in runs)  # noqa: E731
        print(f"| {i + 1} | {med('ttft'):.2f} | {med('stream'):.2f} | {med('tools'):.2f} "
              f"| {med('turns'):.0f} | {med('total'):.2f} | {med('residual'):.2f} |")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the analysis**

```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
.venv/bin/python scripts/audit/analyze_timing.py \
    docs/superpowers/audit-evidence/timing_run{1,2,3}.jsonl
```

Expected: an 8-row markdown table of medians. Sanity: message 1 (no tools) has `tools ≈ 0` and 1 turn; tool-heavy messages show turns ≥ 2.

- [ ] **Step 5: Fill Appendix B**

Paste the table plus: the `usage` numbers from the JSONL (`input_tokens` per call — cross-check against Appendix A's static-prefix number), run timestamps/market condition, and the known limitation: *residual covers everything inside `handle_message` outside API+tools (history load, SQLite persistence, Chainlit step rendering); browser-side render time is not captured.*

- [ ] **Step 6: Commit**

```bash
git add scripts/audit/analyze_timing.py docs/claude-tools-audit-2026-07.md
git commit -m "audit(ws1b): latency decomposition — 3-run medians, 8-message script"
```

---

### Task 6: WS1b — revert claudia_ui instrumentation

**Files:**
- Delete: `/Users/steph/Claude_Projects/claudia_ui/claudia/_timing.py`
- Revert: `/Users/steph/Claude_Projects/claudia_ui/claudia/agent.py`

- [ ] **Step 1: Revert**

```bash
cd /Users/steph/Claude_Projects/claudia_ui
git restore claudia/agent.py
rm claudia/_timing.py
git status --short   # expected: no claudia/*.py changes remain
```

The JSONL evidence already lives in ibkr_core_mcp's evidence dir; nothing is lost.

---

### Task 7: WS2b — cross-domain dependency graph

**Files:**
- Create: `scripts/audit/dep_graph.py`
- Output: `docs/superpowers/audit-evidence/dep_graph.json`
- Modify: `docs/claude-tools-audit-2026-07.md` (Appendix D)

- [ ] **Step 1: Write the extractor**

```python
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
```

- [ ] **Step 2: Run it**

```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
.venv/bin/python scripts/audit/dep_graph.py ibkr_core_mcp/claude_tools.py
```

Expected: a mermaid flowchart. Sanity: helpers like `_first_account_id` and `_safe_error` should appear as high-in-degree targets; `execute` should not dominate (it dispatches via dict, not direct calls — if it shows every handler, the dispatch is call-based and the graph filter needs no change, just note it).

- [ ] **Step 3: Fill Appendix D**

Paste the mermaid graph. Then annotate it against the 2026-06-27 proposed 7-module split (market_data / portfolio / orders / trades / instruments / analytics / web): list every edge that crosses a proposed module boundary — these are the edges the split design must handle via composition (Option A) or boundary redraw. State the count explicitly: "N cross-domain edges; M helper edges."

- [ ] **Step 4: Commit**

```bash
git add scripts/audit/dep_graph.py docs/claude-tools-audit-2026-07.md
git commit -m "audit(ws2b): ClaudeToolkit dependency graph + split-boundary crossings"
```

---

### Task 8: WS2a — per-tool code findings table

**Files:**
- Modify: `docs/claude-tools-audit-2026-07.md` (Appendix C)
- Working notes: `docs/superpowers/audit-evidence/findings_notes.md`

This is a systematic read — judgment applied under a fixed rubric, so results are comparable across all 42 handlers.

- [ ] **Step 1: Build the handler index**

```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
grep -n "    def " ibkr_core_mcp/claude_tools.py
```

Map each of the 42 tool names to its handler method + line range (the dispatch dict in `execute()` at ~line 881 gives the name→method mapping).

- [ ] **Step 2: Build the test-coverage map**

```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
for t in fetch_market_data check_cache list_cache get_account_summary get_positions \
         get_trades sync_flex_archive import_flex_file check_flex_coverage \
         verify_flex_import sync_flex_trades get_live_orders diagnose_orders \
         get_ledger get_allocation get_pa_periods get_pa_performance \
         get_pa_transactions get_contract_info get_option_chain run_scanner \
         get_notifications add_indicators run_backtest generate_pinescript \
         get_analytics preview_order get_pnl search_contract get_futures \
         get_market_snapshot get_trading_schedule get_alerts create_price_alert \
         delete_alert activate_alert modify_price_alert get_watchlists \
         get_order_status delete_cache firecrawl_search firecrawl_crawl; do
  hits=$(grep -rl "$t" tests/ | tr '\n' ' ')
  echo "$t | ${hits:-NONE}"
done
```

Tools with `NONE` (or hits only in schema-listing tests, verify by reading the hit) get flagged untested.

- [ ] **Step 3: Review each handler against the rubric**

Read `claude_tools.py` top to bottom in handler-index order. For each handler record one row:

| Column | What to check |
|---|---|
| Tool | name |
| Handler / lines | method + range |
| Correctness | logic bugs; unhandled error paths; account-id via `_first_account_id()`/`_all_account_ids()` (never inline `get_accounts()`); conid via `contracts[0].get("conid") or contracts[0].get("con_id")` — both rules from CLAUDE.md §"Adding a New IBKR Endpoint" |
| Consistency | errors through `_safe_error`; return-shape uniform with siblings; params validated before network call |
| Weight | LOC; duplicated blocks shared with other handlers (name the sibling) |
| Tests | from Step 2: unit / integration / NONE |
| Severity | none / minor / defect |

Also complete WS2d (plumbing) as four extra rows at the bottom of the table: `execute()` dispatch, the `tuple[str, None]` figure-return signature (2026-06-27 notes bug #1 — verify current state before repeating the claim), `ClaudeToolkit.__init__` cost, and the single-event-loop comment at line ~868 (is the assumption still valid for the SSE `--stream` path?).

- [ ] **Step 4: Fill Appendix C and commit**

Paste the completed 46-row table (42 handlers + 4 plumbing rows) into Appendix C. Lead with a 3-line summary: counts by severity, untested-handler count, duplication hot spots.

```bash
git add docs/claude-tools-audit-2026-07.md
git commit -m "audit(ws2a): per-handler findings table, 42 tools + plumbing"
```

---

### Task 9: WS2c/2d — structural assessment (Appendix E)

**Files:**
- Modify: `docs/claude-tools-audit-2026-07.md` (Appendix E)

- [ ] **Step 1: Write the assessment**

Evaluate exactly three candidates, each against the same criteria (cross-domain edges from Appendix D, defect/duplication evidence from Appendix C, token facts from Appendix A, how the 3 layer-2 tools would land):

1. **Candidate 1 — status quo + helper extraction:** keep one file; extract duplicated blocks found in WS2a into private helpers. Cheapest; right answer if Appendix C shows the monolith is *not* causing defects.
2. **Candidate 2 — the 2026-06-27 7-module split** (market_data / portfolio / orders / trades / instruments / analytics / web; composition Option A). Assess against the *actual* dependency graph: does any proposed boundary cut a heavy edge?
3. **Candidate 3 — two-axis split:** definitions grouped by *exposure domain* (enables future per-context tool profiles for claudia_ui, D3) while handlers group by *dependency cluster* from Appendix D. More design, more power; only justified if D3 evidence says profiles are likely needed.

For each: 3–6 sentences of trade-offs, then one recommendation with the deciding evidence cited by appendix. Also state where the layer-2 web-docs tools land in the recommended structure.

- [ ] **Step 2: Commit**

```bash
git add docs/claude-tools-audit-2026-07.md
git commit -m "audit(ws2c): structural assessment — three candidates, one recommendation"
```

---

### Task 10: WS3a — tool → authoritative-source map + scrapes

**Files:**
- Modify: `docs/claude-tools-audit-2026-07.md` (Appendix F)
- Output: `docs/superpowers/audit-evidence/scrapes/*.md`

- [ ] **Step 1: Fill Appendix F starting from this mapping** (refine section anchors while scraping):

| Tool group | Tools | Authoritative source |
|---|---|---|
| Market data | fetch_market_data, get_market_snapshot, get_futures, get_trading_schedule | https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/ (marketdata/history, marketdata/snapshot, trsrv/futures, trsrv/secdef/schedule) |
| Contracts | search_contract, get_contract_info, get_option_chain | same CPAPI reference (iserver/secdef/search, secdef/info, secdef/strikes) |
| Portfolio/PA | get_account_summary, get_positions, get_ledger, get_allocation, get_pnl, get_pa_periods, get_pa_performance, get_pa_transactions | same CPAPI reference (portfolio/*, pa/*) |
| Orders (read) | get_live_orders, get_order_status, diagnose_orders, preview_order | CPAPI reference + https://www.interactivebrokers.com/campus/trading-lessons/request-modify-orders/ (two-call pattern) |
| Alerts | get_alerts, create_price_alert, delete_alert, activate_alert, modify_price_alert | CPAPI reference (iserver/account/alert*) |
| Scanner/watchlists/notifications | run_scanner, get_watchlists, get_notifications | CPAPI reference (iserver/scanner/params+run, watchlists, fyi) |
| Trades/Flex | get_trades, sync_flex_trades, sync_flex_archive, import_flex_file, check_flex_coverage, verify_flex_import | https://www.ibkrguides.com/clientportal/performanceandstatements/flex3.htm + flex3error.htm |
| Web scraping | firecrawl_search, firecrawl_crawl | https://docs.firecrawl.dev/api-reference/endpoint/scrape , https://docs.firecrawl.dev/api-reference/endpoint/crawl-get |
| Cache (GDrive) | check_cache, list_cache, delete_cache | https://developers.google.com/drive/api/reference/rest/v3 |
| **Internal-only** | add_indicators, run_backtest, generate_pinescript, get_analytics | No external API — verify descriptions against the package's own behavior (indicators.py, backtest.py, pinescript.py, analytics.py) instead of a scrape |

- [ ] **Step 2: Scrape each unique external URL**

Use the Firecrawl skill/CLI (or `WebDocsStore`-backed `firecrawl_search` where already wired). For each unique URL in the map (~10 pages): save markdown to `docs/superpowers/audit-evidence/scrapes/<slug>.md` and append `{url, retrieved_at}` to `scrapes/manifest.json`. If Firecrawl fails on a page → try Crawl4AI fallback → else record the page as unscraped (its tools become **unverified** in Task 11, per spec — never guessed).

- [ ] **Step 3: Commit**

```bash
git add docs/claude-tools-audit-2026-07.md
git commit -m "audit(ws3a): tool-to-source map, scrapes archived locally"
```

---

### Task 11: WS3b/3c — diff and verdicts (Appendix G)

**Files:**
- Create: `scripts/audit/dump_tool_texts.py`
- Output: `docs/superpowers/audit-evidence/tool_texts.md`
- Modify: `docs/claude-tools-audit-2026-07.md` (Appendix G)

- [ ] **Step 1: Write the dump helper**

```python
#!/usr/bin/env python3
"""WS3 — dump every tool's Claude-facing text to one markdown file for side-by-side
review against scraped official docs. No imports of the package (AST only).

Usage: python scripts/audit/dump_tool_texts.py > docs/superpowers/audit-evidence/tool_texts.md
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
            isinstance(t, ast.Name) and t.id == "TOOL_DEFINITIONS" for t in node.targets):
        tools = ast.literal_eval(node.value)
    elif (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
          and node.target.id == "TOOL_DEFINITIONS" and node.value is not None):
        tools = ast.literal_eval(node.value)
assert tools, "TOOL_DEFINITIONS not found"

for t in tools:
    print(f"## {t['name']}\n")
    print(f"**description:** {t['description']}\n")
    print("**input_schema:**\n```json")
    print(json.dumps(t.get("input_schema", {}), indent=2))
    print("```\n")
```

Run it:

```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
.venv/bin/python scripts/audit/dump_tool_texts.py > docs/superpowers/audit-evidence/tool_texts.md
grep -c "^## " docs/superpowers/audit-evidence/tool_texts.md   # expected: 42
```

- [ ] **Step 2: Produce the verdict per tool**

For each of the 42 tools, compare `tool_texts.md` (+ the handler docstring from the Task 8 read) against the scraped source (or package behavior for internal-only tools). Record one row:

| Tool | Verdict | Issue found | Proposed new text (Fix/Enrich/Trim only) | Source (URL + scrape date) |

Verdict rules (from the spec): **accurate** / **fix** (factually wrong) / **enrich** (missing load-bearing behavior — token-conscious: rich only for complex tools) / **trim** (verbose, no tool-choice value) / **unverified** (source unscrapeble — no proposed text, never guessed). Hunt specifically for: wrong endpoints/params, invented error semantics, missing pagination limits (e.g. the documented 1,000-point history cap), missing two-call patterns, T+1/delay caveats, subscription requirements.

- [ ] **Step 3: Fill Appendix G and commit**

Paste the 42-row table; lead with verdict counts (e.g. "N accurate, N fix, N enrich, N trim, N unverified").

```bash
git add scripts/audit/dump_tool_texts.py docs/claude-tools-audit-2026-07.md
git commit -m "audit(ws3): docs verdicts for all 42 tools with citations"
```

---

### Task 12: Synthesis — decide D1–D5, finish the report

**Files:**
- Modify: `docs/claude-tools-audit-2026-07.md` (decision summary + status)

- [ ] **Step 1: Fill the decision table** using the criteria fixed in the spec — each decision cites its appendix:

- **D1:** from Appendix B — name the components carrying ≥80% of median wall-clock; note explicitly whether prompt-processing time (ttft × turns, driven by the Appendix A static prefix) dominates. Do **not** recommend caching here — it's already decided and out of scope.
- **D2:** go/no-go per the spec rule (cleanly cuttable graph AND active harm shown in Appendix C). If go: name the winning candidate from Appendix E. If no-go: state the re-evaluation trigger.
- **D3:** all-tools vs. profiles per Appendix A/B evidence and Appendix E candidate 3 feasibility.
- **D4:** sequencing of layer 2 vs. split, from D2's outcome + Appendix A's layer-2 delta.
- **D5:** the Appendix G verdict counts; note that Task 13 applies them.

- [ ] **Step 2: Flip the report status line** to `**Status:** COMPLETE — D1–D4 are recommendations for future work; D5 applied in the companion commit.` Re-read the whole report once for internal consistency (numbers in the decision table must match the appendices).

- [ ] **Step 3: Commit**

```bash
git add docs/claude-tools-audit-2026-07.md
git commit -m "audit: synthesis — decisions D1-D5 with evidence"
```

- [ ] **Step 4: CHECKPOINT — owner reviews the report before Task 13.** D1–D4 are theirs to accept or amend; Task 13 proceeds only on the reviewed Appendix G.

---

### Task 13: Apply D5 verdicts to claude_tools.py (doc-only)

**Files:**
- Modify: `ibkr_core_mcp/claude_tools.py` (descriptions, `input_schema` texts, docstrings — **no logic**)
- Modify: `docs/claude-tools-audit-2026-07.md` (post-application addendum)

- [ ] **Step 1: Apply every Fix/Enrich/Trim row from Appendix G** — exact texts come from the table's "Proposed new text" column. Touch nothing structural; `accurate` and `unverified` rows are untouched.

- [ ] **Step 2: Run the full regression gate**

```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
.venv/bin/python -m pytest -m "not integration" -q
.venv/bin/python -m ruff check .
.venv/bin/python -m mypy .
```

Expected: all tests pass, ruff and mypy clean (they were green at commit e4f1973). If a test asserts an old description string, updating that assertion is in scope — it is part of the same doc change.

- [ ] **Step 3: Re-measure the token surface**

```bash
.venv/bin/python scripts/audit/count_tool_tokens.py \
    --out docs/superpowers/audit-evidence/token_counts_after_d5.json
```

Add an addendum line to Appendix A: tool-surface total before → after, net delta. (Enrichments cost, trims save; the net should reflect the token-conscious rule.)

- [ ] **Step 4: Commit**

```bash
git add ibkr_core_mcp/claude_tools.py tests/ docs/claude-tools-audit-2026-07.md
git commit -m "docs(tools): apply audit D5 verdicts to tool descriptions

Fix/enrich/trim per docs/claude-tools-audit-2026-07.md Appendix G.
Every change cites its official source in the audit report.
Doc-text only — no handler logic touched. Token delta recorded in
Appendix A addendum."
```

---

## Execution notes

- **Order:** Tasks 2–3 (tokens), 7–9 (code), 10–11 (docs) are independent blocks and may interleave. Tasks 4–6 (latency) need the owner present. Task 12 needs everything; Task 13 needs the Task 12 checkpoint.
- **Owner-in-the-loop points:** gateway login + scripted Chainlit sessions (Task 5); report review checkpoint (Task 12 Step 4).
- **Evidence is local-only** (`docs/superpowers/` is gitignored); the committed report must therefore quote every number it relies on — never reference evidence files as the only record.
