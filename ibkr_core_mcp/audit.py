"""One redacted record per tool call and per order or session write — the package's audit trail.

MCP security checklist 8.1 (2026-11-09) asks that every action be logged with the minimum
fields and sensitive data redacted: timestamp, who, which tool, the parameters, a response
summary, the decision, a correlation id. Until that day the package kept none ("the client
transcript is the operator's trail", `docs/security-architecture.md` § 8, 2026-09-14), on the
ground that a parameter log would carry model-supplied URLs and paths into a channel the
redaction did not cover. This module is that channel, covered: **every string in a record
passes the package's one redaction** (`redaction.redact_text` — the secret shapes, the query
strings, the home directory), an account id is masked, a value is capped at 200 characters,
nesting at three levels, and **nothing of a response body is kept** — a result is its length.

Where a record is written from:

- `ClaudeToolkit.execute` — every tool call the model makes (`kind: tool_call`, `actor: model`);
  `mcp_server._dispatch` records its two server-local tools the same way;
- the seven gated order writes of `IBKRClient`, through `client._audited_write`
  (`kind: order_write`, `actor: operator` — the human at the gates; `decision` is the gates'
  own outcome: `sent`, `denied` at Gate 1, `declined` or `timed_out` at Gate 2, `refused` before
  any gate, `error` for anything else, the exception's type as `outcome`);
- the session owner's writes — `/logout`, `ssodh/init`, a container restart, the login page
  (`kind: session_write`; register F45 step 2).

**It is evidence, not a gate.** A write that fails is one redacted warning per path and never
an exception into the path it records. The file is the operator's alone: `0600`, in a `0700`
directory, one `.1` rotation at 20 MB. The default is `~/.ibkr_core/audit.jsonl`; a host passes
`Config.audit_log_path` (env `IBKR_AUDIT_LOG`) to `configure()` once at start — constructors do
not, so a `Config` built by hand in a test cannot repoint the record at the operator's directory.
A host names itself with `context(client=…, agent=…)`; the MCP server sets `client` from the
initialize handshake, and the gateway's command line names itself `ibkr_core_mcp.gateway` with
`agent` `none`. Records made inside one `call()` share its id, so a gate's record inside a
tool call correlates with the call.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import stat
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path

from ibkr_core_mcp.redaction import collapse_home, redact_error, redact_text

log = logging.getLogger(__name__)

_MAX_BYTES = 20 * 1024 * 1024
"""Past this size the file becomes `<name>.1` and a new one starts — one backup, never unbounded."""
_VALUE_LIMIT = 200
_DEPTH_LIMIT = 3
_ACCOUNT_ID = re.compile(r"\bU[0-9]{6,9}\b")
_MASK = "U******"

ORDER_FIELDS: tuple[str, ...] = (
    "conid",
    "side",
    "quantity",
    "orderType",
    "price",
    "auxPrice",
    "tif",
    "ticker",
    "symbol",
)
"""The fields of an order body a record keeps in clear — what a reader needs to recognise the
order; every other key is named, not valued."""

_path: Path | None = None
_warned: set[str] = set()
_call_id: ContextVar[str | None] = ContextVar("ibkr_core_mcp_audit_call_id", default=None)
_client: ContextVar[str] = ContextVar("ibkr_core_mcp_audit_client", default="unknown")
_agent: ContextVar[str] = ContextVar("ibkr_core_mcp_audit_agent", default="unknown")


def default_path() -> Path:
    """`~/.ibkr_core/audit.jsonl` — beside the trade store, under the same 0700 directory."""
    return Path.home() / ".ibkr_core" / "audit.jsonl"


def configure(path: str | os.PathLike[str]) -> None:
    """Where records go from now on. A host calls this once at start with `Config.audit_log_path`."""
    global _path
    _path = Path(path)


def summary_of(text: str) -> str:
    """What a record keeps of a result: its length, never its text."""
    return f"{len(text)} chars"


@contextlib.contextmanager
def call() -> Iterator[str]:
    """One correlation id for every record made inside the block — a tool call and the writes it leads to."""
    call_id = str(uuid.uuid4())
    token = _call_id.set(call_id)
    try:
        yield call_id
    finally:
        _call_id.reset(token)


@contextlib.contextmanager
def context(*, client: str | None = None, agent: str | None = None) -> Iterator[None]:
    """Name the client and the agent on every record made inside the block (a host's names)."""
    tokens = []
    if client is not None:
        tokens.append((_client, _client.set(client)))
    if agent is not None:
        tokens.append((_agent, _agent.set(agent)))
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)


def summarise(args: Sequence[object], kwargs: Mapping[str, object]) -> dict[str, object]:
    """A call's arguments reduced to what an order record needs: a scalar as itself (redacted
    at record time with every other string), a mapping as its `ORDER_FIELDS` plus the names of
    its keys, a sequence as its length, anything else as its type."""
    summarised: dict[str, object] = {f"arg{i}": _summarise_one(a) for i, a in enumerate(args)}
    summarised.update({key: _summarise_one(value) for key, value in kwargs.items()})
    return summarised


def _summarise_one(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        picked: dict[str, object] = {key: value[key] for key in ORDER_FIELDS if key in value}
        picked["keys"] = sorted(str(key) for key in value)[:20]
        return picked
    if isinstance(value, (list, tuple, set, frozenset)):
        return f"{len(value)} items"
    return type(value).__name__


def _redact_value(value: object, depth: int = 0) -> object:
    """Every string scrubbed, collapsed, masked and capped; nesting bounded; sizes bounded."""
    if depth > _DEPTH_LIMIT:
        return "…"
    if isinstance(value, str):
        return _ACCOUNT_ID.sub(_MASK, redact_text(value, _VALUE_LIMIT))
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Mapping):
        return {str(key)[:_VALUE_LIMIT]: _redact_value(item, depth + 1) for key, item in list(value.items())[:50]}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_redact_value(item, depth + 1) for item in list(value)[:50]]
    return _redact_value(str(value), depth)


def record(
    kind: str,
    *,
    actor: str,
    decision: str,
    outcome: str = "ok",
    params: Mapping[str, object] | None = None,
    summary: str | None = None,
    duration_ms: int | None = None,
    **fields: object,
) -> None:
    """Append one record. Never raises.

    Args:
        kind: `tool_call`, `order_write` or `session_write`.
        actor: `model` for a tool call, `operator` for a write a human gated.
        decision: What became of the action — `executed`, `unknown_tool`, `sent`, `denied`,
            `declined`, `timed_out`, `refused`, `error`.
        outcome: `ok`, or the exception's type name.
        params: The call's arguments (a tool's inputs, `summarise`'s view of a write's), redacted.
        summary: `summary_of(result)` — a length, never the text.
        duration_ms: How long the action took.
        **fields: `tool=` or `action=`, and anything else worth a column; redacted like `params`.
    """
    entry: dict[str, object] = {
        "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "id": _call_id.get() or str(uuid.uuid4()),
        "kind": kind,
        "actor": actor,
        "client": _client.get(),
        "agent": _agent.get(),
    }
    entry.update({key: _redact_value(value) for key, value in fields.items()})
    entry["params"] = _redact_value(dict(params or {}))
    entry["decision"] = decision
    entry["outcome"] = outcome
    if summary is not None:
        entry["summary"] = summary
    if duration_ms is not None:
        entry["duration_ms"] = duration_ms
    path = _path or default_path()
    try:
        _append(path, (json.dumps(entry, default=str) + "\n").encode())
    except Exception as exc:
        if str(path) not in _warned:
            _warned.add(str(path))
            log.warning("Audit record not written to %s: %s", collapse_home(str(path)), redact_error(exc))


def _append(path: Path, data: bytes) -> None:
    """One atomic append; the directory 0700, the file 0600, one rotation at the cap."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.exists():
        if stat.S_IMODE(path.stat().st_mode) != 0o600:
            os.chmod(path, 0o600)
        if path.stat().st_size + len(data) > _MAX_BYTES:
            os.replace(path, path.with_name(path.name + ".1"))
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
