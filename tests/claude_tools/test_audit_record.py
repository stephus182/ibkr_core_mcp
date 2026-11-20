"""Every tool call leaves one audit record (MCP security checklist 8.1, 2026-11-09): the tool, the
redacted parameters, the decision, the outcome's type, the result's size — never the result."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from ibkr_core_mcp import audit


def _records(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_every_tool_call_leaves_one_record(toolkit, tmp_path):
    path = tmp_path / "audit.jsonl"
    audit.configure(path)
    with patch.object(toolkit, "_get_account_summary", return_value=("Net liquidation: 1,000.00 USD", None)):
        toolkit.execute("get_account_summary", {})
    (rec,) = _records(path)
    assert rec["kind"] == "tool_call" and rec["tool"] == "get_account_summary" and rec["actor"] == "model"
    assert rec["decision"] == "executed" and rec["outcome"] == "ok"
    assert rec["summary"] == "29 chars" and isinstance(rec["duration_ms"], int)
    assert "Net liquidation" not in json.dumps(rec)  # a length, never the text


def test_an_unknown_tool_records_unknown_tool(toolkit, tmp_path):
    path = tmp_path / "audit.jsonl"
    audit.configure(path)
    toolkit.execute("no_such_tool", {"x": 1})
    (rec,) = _records(path)
    assert rec["decision"] == "unknown_tool" and rec["tool"] == "no_such_tool"


def test_a_failing_handler_records_error_with_the_type_only(toolkit, tmp_path):
    path = tmp_path / "audit.jsonl"
    audit.configure(path)
    with patch.object(toolkit, "_get_account_summary", side_effect=RuntimeError("boom ?t=SECRET-TOKEN")):
        toolkit.execute("get_account_summary", {})
    (rec,) = _records(path)
    assert rec["decision"] == "error" and rec["outcome"] == "RuntimeError"
    assert "SECRET" not in json.dumps(rec)


def test_parameters_are_recorded_redacted(toolkit, tmp_path):
    path = tmp_path / "audit.jsonl"
    audit.configure(path)
    toolkit.execute("fetch_page", {"url": "https://x.example/page?token=SECRET-QUERY"})
    (rec,) = _records(path)
    assert rec["tool"] == "fetch_page"
    assert "SECRET" not in json.dumps(rec)
    assert "https://x.example/page?" in json.dumps(rec)
