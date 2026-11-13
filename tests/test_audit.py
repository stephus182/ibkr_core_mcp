"""Tests for `ibkr_core_mcp.audit` — the redacted, append-only record of every tool call and every
order and session write (MCP security checklist 8.1, 2026-11-09).

The record is evidence, not a gate: it never raises into the path it records, every string in it
has passed the package's one redaction (secret shapes, the home directory, account ids), nothing
of a response body is kept, and the file is the operator's alone (0600 in a 0700 directory).
"""

from __future__ import annotations

import json
import logging
import stat
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from ibkr_core_mcp import audit
from ibkr_core_mcp.exceptions import ConfirmationDeclinedError, ConfirmationTimeoutError, HumanAuthError


def _lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


# ── The record ──────────────────────────────────────────────────────────────────


def test_a_record_is_one_json_line_with_the_fields(tmp_path):
    path = tmp_path / "logs" / "audit.jsonl"
    audit.configure(path)
    audit.record(
        "tool_call",
        actor="model",
        tool="get_positions",
        params={"page": 0},
        decision="executed",
        outcome="ok",
        summary="1234 chars",
        duration_ms=12,
    )
    (rec,) = _lines(path)
    assert rec["kind"] == "tool_call" and rec["tool"] == "get_positions" and rec["decision"] == "executed"
    assert rec["ts"].endswith("Z") and uuid.UUID(rec["id"])
    assert rec["actor"] == "model" and rec["outcome"] == "ok" and rec["duration_ms"] == 12
    assert rec["params"] == {"page": 0}
    assert rec["client"] == "unknown" and rec["agent"] == "unknown"


def test_params_are_redacted_capped_depth_limited_and_account_ids_masked(tmp_path, monkeypatch):
    """The 2026-09-14 objection to a parameter log — model-supplied URLs and paths in a channel
    `redact_error` does not cover — answered: every string passes the same patterns, the home
    directory collapses, an account id is masked, a value is capped, nesting is bounded."""
    monkeypatch.setenv("HOME", str(tmp_path))
    path = tmp_path / "audit.jsonl"
    audit.configure(path)
    audit.record(
        "tool_call",
        actor="model",
        tool="fetch_page",
        params={
            "url": "https://x.example/x?t=SECRET-FLEX-TOKEN&q=1",
            "path": f"{tmp_path}/.ibkr_core/flex/a.xml",
            "account_id": "U1234567",
            "header": "Authorization: Bearer fc-SECRETSECRETSECRET1234",
            "nested": {"d1": {"d2": {"d3": {"d4": "too deep"}}}},
            "long": "y" * 1000,
            "number": 3,
            "flag": True,
        },
        decision="executed",
    )
    (rec,) = _lines(path)
    text = json.dumps(rec)
    assert "SECRET" not in text
    assert str(tmp_path) not in text and "~/.ibkr_core/flex/a.xml" in text
    assert "U1234567" not in text and "U******" in text
    assert len(rec["params"]["long"]) <= 201
    assert rec["params"]["nested"]["d1"]["d2"]["d3"] == "…"
    assert rec["params"]["number"] == 3 and rec["params"]["flag"] is True


def test_the_file_is_0600_in_a_0700_directory(tmp_path):
    path = tmp_path / "private" / "audit.jsonl"
    audit.configure(path)
    audit.record("tool_call", actor="model", tool="t", decision="executed")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_an_existing_file_left_open_to_others_is_narrowed(tmp_path):
    path = tmp_path / "audit.jsonl"
    path.write_text("")
    path.chmod(0o644)
    audit.configure(path)
    audit.record("tool_call", actor="model", tool="t", decision="executed")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_the_record_rotates_once_at_the_size_cap(tmp_path, monkeypatch):
    """One backup, never unbounded growth: past the cap the file becomes `.1` and a new one starts."""
    monkeypatch.setattr(audit, "_MAX_BYTES", 300)
    path = tmp_path / "audit.jsonl"
    audit.configure(path)
    for i in range(6):
        audit.record("tool_call", actor="model", tool=f"tool{i}", decision="executed")
    backup = path.with_name("audit.jsonl.1")
    assert backup.exists() and _lines(backup)
    assert _lines(path)
    assert not path.with_name("audit.jsonl.2").exists()


def test_records_inside_one_call_share_its_correlation_id(tmp_path):
    path = tmp_path / "audit.jsonl"
    audit.configure(path)
    with audit.call() as call_id:
        audit.record("tool_call", actor="model", tool="t", decision="executed")
        audit.record("order_write", actor="operator", action="place_order", decision="sent")
    audit.record("tool_call", actor="model", tool="t", decision="executed")
    first, second, third = _lines(path)
    assert first["id"] == second["id"] == call_id
    assert third["id"] != call_id


def test_the_host_names_its_client_and_agent(tmp_path):
    path = tmp_path / "audit.jsonl"
    audit.configure(path)
    with audit.context(client="host 1.0", agent="model-x"):
        audit.record("tool_call", actor="model", tool="t", decision="executed")
    audit.record("tool_call", actor="model", tool="t", decision="executed")
    inside, outside = _lines(path)
    assert inside["client"] == "host 1.0" and inside["agent"] == "model-x"
    assert outside["client"] == "unknown" and outside["agent"] == "unknown"


def test_a_write_failure_is_one_redacted_warning_and_never_raises(tmp_path, monkeypatch, caplog):
    """Fail-open: the record is evidence, not a gate. The warning names the file with `~`, never
    the account name (the `collapse_home` inventory)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    blocker = tmp_path / "blocker"
    blocker.write_text("")  # a file where the directory should be
    path = blocker / "audit.jsonl"
    audit.configure(path)
    with caplog.at_level(logging.WARNING, logger="ibkr_core_mcp.audit"):
        audit.record("tool_call", actor="model", tool="t", decision="executed")
        audit.record("tool_call", actor="model", tool="t", decision="executed")
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert str(tmp_path) not in warnings[0] and "~/blocker/audit.jsonl" in warnings[0]


def test_the_summary_is_a_count_never_the_text():
    assert audit.summary_of("a" * 300) == "300 chars"
    assert audit.summary_of("") == "0 chars"


def test_the_default_path_is_under_the_operator_directory():
    assert audit.default_path() == Path.home() / ".ibkr_core" / "audit.jsonl"


def test_call_arguments_are_summarised_to_what_an_order_record_needs():
    """An order dict keeps the fields a reader needs to recognise the order and the names of the
    rest; a list is its length; a scalar is itself (redacted later with every other string)."""
    order = {
        "conid": 265598,
        "side": "BUY",
        "quantity": 1,
        "orderType": "LMT",
        "price": 150.5,
        "tif": "DAY",
        "ticker": "AAPL",
        "acctId": "U1234567",
        "cOID": "x",
    }
    summarised = audit.summarise(("U1234567", order, [order, order]), {"manual_indicator": True})
    assert summarised["arg0"] == "U1234567"  # masked at record time
    assert summarised["arg1"] == {
        "conid": 265598,
        "side": "BUY",
        "quantity": 1,
        "orderType": "LMT",
        "price": 150.5,
        "tif": "DAY",
        "ticker": "AAPL",
        "keys": ["acctId", "cOID", "conid", "orderType", "price", "quantity", "side", "ticker", "tif"],
    }
    assert summarised["arg2"] == "2 items"
    assert summarised["manual_indicator"] is True


# ── The order writes record through the gates' own outcomes ─────────────────────


_ORDER = {"conid": 265598, "side": "BUY", "quantity": 1, "orderType": "MKT", "tif": "DAY", "ticker": "AAPL"}


def _order_records(path: Path) -> list[dict[str, Any]]:
    return [r for r in _lines(path) if r["kind"] == "order_write"]


def test_a_sent_order_write_records_sent_with_its_label_and_a_masked_account(client, tmp_path):
    path = tmp_path / "audit.jsonl"
    audit.configure(path)
    with (
        patch("ibkr_core_mcp.client.require_touch_id"),
        patch("ibkr_core_mcp.client.confirm_order_dialog"),
        patch.object(client, "_post", return_value=[{"order_id": "1"}]),
    ):
        client.place_order("U1234567", _ORDER)
    (rec,) = _order_records(path)
    assert rec["action"] == "place_order" and rec["decision"] == "sent" and rec["outcome"] == "ok"
    assert rec["actor"] == "operator"
    text = json.dumps(rec)
    assert "BUY" in text and "AAPL" in text and "U1234567" not in text and "U******" in text


def test_a_denied_gate_1_records_denied_and_nothing_was_sent(client, tmp_path):
    path = tmp_path / "audit.jsonl"
    audit.configure(path)
    with (
        patch("ibkr_core_mcp.client.require_touch_id", side_effect=HumanAuthError("denied")),
        patch.object(client, "_post") as post,
        pytest.raises(HumanAuthError),
    ):
        client.cancel_order("U1234567", "123")
    post.assert_not_called()
    (rec,) = _order_records(path)
    assert rec["action"] == "cancel_order" and rec["decision"] == "denied" and rec["outcome"] == "HumanAuthError"


@pytest.mark.parametrize(
    ("error", "decision"),
    [
        (ConfirmationDeclinedError("Not sent — nothing reached IBKR."), "declined"),
        (ConfirmationTimeoutError("timed out"), "timed_out"),
    ],
    ids=["declined", "timed-out"],
)
def test_a_gate_2_outcome_records_its_own_decision(client, tmp_path, error, decision):
    path = tmp_path / "audit.jsonl"
    audit.configure(path)
    with (
        patch("ibkr_core_mcp.client.require_touch_id"),
        patch("ibkr_core_mcp.client.confirm_order_dialog", side_effect=error),
        patch.object(client, "_post") as post,
        pytest.raises(HumanAuthError),
    ):
        client.place_order("U1234567", _ORDER)
    post.assert_not_called()
    (rec,) = _order_records(path)
    assert rec["decision"] == decision and rec["outcome"] == type(error).__name__


def test_a_refused_order_records_refused(client, tmp_path):
    """A refusal before any gate — an invalid identifier — is `refused`, not `error`."""
    from ibkr_core_mcp.exceptions import ConfigError

    path = tmp_path / "audit.jsonl"
    audit.configure(path)
    with patch.object(client, "_post") as post, pytest.raises(ConfigError):
        client.cancel_order("not an account", "123")
    post.assert_not_called()
    (rec,) = _order_records(path)
    assert rec["decision"] == "refused" and rec["outcome"] == "ConfigError"
