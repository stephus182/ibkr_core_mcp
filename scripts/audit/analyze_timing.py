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
from typing import Any


def parse_run(path: str) -> list[dict[str, Any]]:
    msgs: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
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
    out: list[dict[str, Any]] = []
    for m in msgs:
        if "end" not in m:
            continue  # aborted message
        calls = sorted(m["calls"].items())
        stream = sum(c["end"] - c["start"] for _, c in calls if "end" in c)
        ttft = calls[0][1].get("first", calls[0][1]["start"]) - calls[0][1]["start"]
        total = m["end"] - m["start"]
        out.append(
            {
                "ttft": ttft,
                "stream": stream,
                "tools": m["tools"],
                "turns": len(calls),
                "total": total,
                "residual": total - stream - m["tools"],
            }
        )
    return out


def main() -> None:
    runs = [parse_run(p) for p in sys.argv[1:]]
    n = min(len(r) for r in runs)

    def med(i: int, k: str) -> float:
        return float(statistics.median(r[i][k] for r in runs))

    print("| msg # | ttft (s) | stream (s) | tools (s) | api turns | total (s) | residual (s) |")
    print("|---|---|---|---|---|---|---|")
    for i in range(n):
        print(
            f"| {i + 1} | {med(i, 'ttft'):.2f} | {med(i, 'stream'):.2f} "
            f"| {med(i, 'tools'):.2f} | {med(i, 'turns'):.0f} "
            f"| {med(i, 'total'):.2f} | {med(i, 'residual'):.2f} |"
        )


if __name__ == "__main__":
    main()
