# Backtest Sandbox Subprocess Isolation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the backtest sandbox so a strategy that times out is actually killed, not orphaned — `run_backtest("while True: pass", df)` must return control to the caller with `BacktestRuntimeError` and leave nothing running behind it.

**Architecture:** Replace `backtest.py`'s `ThreadPoolExecutor(max_workers=1)` with a `multiprocessing.get_context("spawn").Process`. Both `compile_restricted()` and `exec()` move into a new module-level `_execute_in_subprocess()` worker function that runs in the child. On timeout, the parent escalates `terminate()` (SIGTERM) → `kill()` (SIGKILL) — a real OS process can be forcibly stopped, unlike a thread.

**Tech Stack:** Python stdlib `multiprocessing` (spawn context), existing `RestrictedPython` sandbox (unchanged), `pytest` + `monkeypatch`.

**Design doc:** `docs/plans/2026-07-15-backtest-sandbox-subprocess-isolation-design.md` — read this first if anything below is ambiguous; this plan implements it exactly, no scope changes.

---

## Before you start: why Task 1 has no commit, and why the new test can hang if the fix is wrong

`concurrent.futures.thread` registers a shutdown hook (`_python_exit`, verified via `inspect.getsource` in `concurrent/futures/thread.py`) that unconditionally calls `.join()` on every worker thread the pool ever created — no timeout. A thread stuck in `while True: pass` never returns from that `join()`, which means the **entire host Python process can become unable to exit**, not just leak CPU in the background. This is worse than `SECURITY.md`'s current wording ("unbounded CPU consumption") suggests.

Practical consequence for this plan: any test that submits `while True: pass` to a *broken* implementation (today's threaded code, or a subprocess fix with a bug in the kill-escalation path) can hang the whole test process forever. This dev machine has neither `timeout`/`gtimeout` (checked: not installed) nor the `pytest-timeout` plugin (checked: not in `pyproject.toml`), so every step below that risks this uses a **backgrounded shell process with an explicit PID check + `kill -9` fallback** instead of relying on either.

---

### Task 1: Confirm the current bug's real severity (diagnostic only, no commit)

**Files:** none modified — this task writes a throwaway script to the scratchpad, runs it, and deletes it.

- [ ] **Step 1: Write the diagnostic script**

Write this to `/tmp/verify_backtest_thread_leak.py` (or your scratchpad dir — this file is never committed):

```python
"""Throwaway diagnostic: proves the pre-fix ThreadPoolExecutor bug hangs process exit.
Run this, then check (from another shell) whether the process is still alive after ~8s.
"""
import sys
sys.path.insert(0, ".")
from ibkr_core_mcp import backtest
import pandas as pd

backtest._EXEC_TIMEOUT = 1  # don't wait the real 10s for this manual check

df = pd.DataFrame({
    "open": [1.0] * 5, "high": [1.0] * 5, "low": [1.0] * 5,
    "close": [1.0] * 5, "volume": [1.0] * 5,
})

try:
    backtest.run_backtest("while True: pass", df)
except Exception as e:
    print(f"run_backtest raised as expected: {e}", flush=True)

print("About to exit the interpreter now. If this is the LAST line you ever see, "
      "the bug is confirmed: the orphaned thread is blocking process shutdown.", flush=True)
```

- [ ] **Step 2: Run it in the background and check whether it's still alive after 8s**

```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
python3.11 /tmp/verify_backtest_thread_leak.py > /tmp/verify_output.txt 2>&1 &
DIAG_PID=$!
sleep 8
if kill -0 "$DIAG_PID" 2>/dev/null; then
    echo "CONFIRMED: PID $DIAG_PID is still alive after 8s — process cannot exit. Killing it now."
    kill -9 "$DIAG_PID"
else
    echo "Process exited on its own — unexpected, re-check before proceeding."
fi
cat /tmp/verify_output.txt
```

Expected: `CONFIRMED: PID ... is still alive after 8s`, and `/tmp/verify_output.txt` shows the "run_backtest raised as expected" line followed by the "About to exit" line — proving `run_backtest()` itself returned/raised promptly (~1s) while the process as a whole never got to finish exiting.

- [ ] **Step 3: Clean up**

```bash
rm /tmp/verify_backtest_thread_leak.py /tmp/verify_output.txt
```

No commit — this task is purely diagnostic, to see the bug firsthand (including its full severity) before rewriting blind.

---

### Task 2: Replace the ThreadPoolExecutor with a killable subprocess

**Files:**
- Modify: `ibkr_core_mcp/backtest.py:1-19` (imports, constants), `:176-196` (execution block)
- Test: `tests/test_backtest.py` (append one new test)

- [ ] **Step 1: Update imports and constants in `backtest.py`**

Replace lines 1-19 (from `"""RestrictedPython..."""` through `_EXEC_TIMEOUT = 10  # seconds`) with:

```python
"""RestrictedPython sandbox executor for backtesting strategy code on OHLCV DataFrames."""
from __future__ import annotations

import multiprocessing
import queue
import types
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from RestrictedPython import compile_restricted, safe_globals
from RestrictedPython.Guards import full_write_guard, safer_getattr
from RestrictedPython.Limits import limited_range

from ibkr_core_mcp import analytics as _analytics
from ibkr_core_mcp.exceptions import BacktestRuntimeError, BacktestSyntaxError

_MAX_CODE_LEN = 4096
_EXEC_TIMEOUT = 10  # seconds
_KILL_GRACE_S = 1.0  # seconds to wait after SIGTERM before escalating to SIGKILL
```

(This removes `import concurrent.futures` and adds `import multiprocessing`, `import queue`.)

- [ ] **Step 2: Add the module-level subprocess worker function**

Insert this new function immediately **before** `def run_backtest(` (i.e. right after the `_SAFE_PD = types.SimpleNamespace(...)` block, before the `@dataclass class BacktestResult` block — placement doesn't matter functionally since it only needs `_write_guard`, `_sandboxed_getattr`, `_SAFE_PD`, `_SAFE_NP` to already be defined above it, which they are):

```python
def _execute_in_subprocess(code: str, df: pd.DataFrame, result_queue: Any) -> None:
    """Compile and run strategy code inside an isolated child process.

    Runs entirely in the child (both compile_restricted and exec) so the parent
    can kill the whole OS process on timeout — a thread cannot be forcibly
    stopped once it's running, a process can. `result_queue` is a
    multiprocessing.Queue; puts a ("ok", df) / ("syntax_error", msg) /
    ("runtime_error", msg) tuple.
    """
    try:
        byte_code = compile_restricted(code, "<strategy>", "exec")
    except SyntaxError as e:
        result_queue.put(("syntax_error", str(e)))
        return

    sandbox: dict[str, Any] = {
        **safe_globals,
        "_write_": _write_guard,
        "_getattr_": _sandboxed_getattr,
        "_getitem_": lambda ob, key: ob[key],
        "_getiter_": iter,
        "pd": _SAFE_PD,
        "np": _SAFE_NP,
        "float": float,
        "int": int,
        "abs": abs,
        "range": limited_range,
        "len": len,
        "df": df,
    }
    try:
        exec(byte_code, sandbox)  # noqa: S102
    except Exception as e:
        result_queue.put(("runtime_error", f"{type(e).__name__}: {e}"))
        return

    result_queue.put(("ok", sandbox.get("df", df)))
```

- [ ] **Step 3: Replace `run_backtest`'s execution block**

In `run_backtest`, replace everything from `sandbox: dict[str, Any] = {` (the sandbox-building block) through the `finally: pool.shutdown(wait=False)` line — i.e. replace this entire chunk:

```python
    sandbox: dict[str, Any] = {
        **safe_globals,
        "_write_": _write_guard,
        "_getattr_": _sandboxed_getattr,
        "_getitem_": lambda ob, key: ob[key],
        "_getiter_": iter,
        "pd": _SAFE_PD,
        "np": _SAFE_NP,
        "float": float,
        "int": int,
        "abs": abs,
        "range": limited_range,
        "len": len,
        "df": df.copy(),
    }

    def _run(byte_code: types.CodeType, sandbox: dict[str, Any]) -> None:
        exec(byte_code, sandbox)  # noqa: S102

    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        fut = pool.submit(_run, byte_code, sandbox)
        try:
            fut.result(timeout=_EXEC_TIMEOUT)
        except concurrent.futures.TimeoutError:
            fut.cancel()
            raise BacktestRuntimeError(
                f"Strategy timed out after {_EXEC_TIMEOUT}s"
            ) from None
        except Exception as e:
            # Include the exception type: str(KeyError('rsi')) is just "'rsi'",
            # which is not actionable on its own for the LLM that wrote the code.
            raise BacktestRuntimeError(
                f"Strategy runtime error: {type(e).__name__}: {e}"
            ) from e
    finally:
        pool.shutdown(wait=False)

    result_df: pd.DataFrame = sandbox.get("df", df)
```

with:

```python
    ctx = multiprocessing.get_context("spawn")
    result_queue: Any = ctx.Queue()
    process = ctx.Process(target=_execute_in_subprocess, args=(code, df, result_queue))
    process.start()
    process.join(_EXEC_TIMEOUT)

    if process.is_alive():
        process.terminate()
        process.join(_KILL_GRACE_S)
        if process.is_alive():
            process.kill()
            process.join()
        raise BacktestRuntimeError(f"Strategy timed out after {_EXEC_TIMEOUT}s")

    try:
        status, payload = result_queue.get_nowait()
    except queue.Empty:
        raise BacktestRuntimeError(
            f"Strategy process exited unexpectedly (exit code {process.exitcode})"
        ) from None

    if status == "syntax_error":
        raise BacktestSyntaxError(f"Strategy syntax error: {payload}")
    if status == "runtime_error":
        raise BacktestRuntimeError(f"Strategy runtime error: {payload}")

    result_df: pd.DataFrame = payload
```

Note: the `try: byte_code = compile_restricted(...) except SyntaxError:` block that currently sits **above** the sandbox block in `run_backtest` (right after the `_MAX_CODE_LEN` check) must be **deleted entirely** — compilation now happens inside `_execute_in_subprocess`, not in the parent. After this task, `run_backtest`'s body should read: the `_MAX_CODE_LEN` check, then directly the `ctx = multiprocessing.get_context(...)` block above, then the unchanged `if "signal" not in result_df.columns:` check and `return _compute_metrics(...)` call.

- [ ] **Step 4: Write the regression test**

Append to `tests/test_backtest.py`:

```python
def test_timeout_actually_kills_runaway_process(ohlcv, monkeypatch):
    """A strategy that never returns must be killed, not merely abandoned.

    Regression test for the ThreadPoolExecutor-era bug where Future.cancel()
    could not stop an already-running thread: `while True: pass` would survive
    the timeout and burn CPU in an orphaned thread forever — and could even
    block the whole host process from exiting, since ThreadPoolExecutor
    registers a non-daemon-thread join in its interpreter-shutdown hook.
    If this fix ever regresses back to something unkillable, this test will
    hang instead of failing cleanly — a hang here IS the failure signal.
    """
    import multiprocessing
    import time

    from ibkr_core_mcp import backtest
    from ibkr_core_mcp.backtest import BacktestRuntimeError, run_backtest

    monkeypatch.setattr(backtest, "_EXEC_TIMEOUT", 0.5)
    monkeypatch.setattr(backtest, "_KILL_GRACE_S", 0.2)

    start = time.monotonic()
    with pytest.raises(BacktestRuntimeError, match="timed out"):
        run_backtest("while True: pass", ohlcv)
    elapsed = time.monotonic() - start

    assert elapsed < 5.0, (
        f"took {elapsed:.1f}s — kill sequence did not terminate the process promptly"
    )
    assert multiprocessing.active_children() == [], "runaway strategy process was not cleaned up"
```

- [ ] **Step 5: Run the full backtest test suite (with a background-and-check guard, same reasoning as Task 1)**

```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
pytest tests/test_backtest.py -v > /tmp/backtest_test_output.txt 2>&1 &
TEST_PID=$!
sleep 30
if kill -0 "$TEST_PID" 2>/dev/null; then
    echo "TESTS HUNG after 30s (PID $TEST_PID) — the kill-escalation path has a bug. Killing now."
    kill -9 "$TEST_PID"
    cat /tmp/backtest_test_output.txt
else
    wait "$TEST_PID"
    echo "Exit code: $?"
    cat /tmp/backtest_test_output.txt
fi
```

Expected: exit code 0, all 16 tests pass (15 existing + the new one), completes in a few seconds — the 30s window is a generous safety net, not the expected runtime.

- [ ] **Step 6: Run mypy to catch any typing issues from the rewrite**

```bash
mypy ibkr_core_mcp/backtest.py
```

Expected: `Success: no issues found`. If it complains about `result_queue: Any` or the `_execute_in_subprocess` signature, fix inline — `Any` is intentionally used for the queue parameter to sidestep `multiprocessing.Queue`'s generic-subscripting friction; don't fight mypy into a more specific type here, it's an internal-only helper.

- [ ] **Step 7: Commit**

```bash
git add ibkr_core_mcp/backtest.py tests/test_backtest.py
git commit -m "$(cat <<'EOF'
fix: run backtest sandbox in a killable subprocess, not a thread

ThreadPoolExecutor's Future.cancel() cannot stop an already-running
thread, so a strategy like `while True: pass` survived the 10s timeout
and kept burning CPU in an orphaned thread — worse, concurrent.futures.
thread registers a non-daemon-thread join in its shutdown hook, so the
whole host process could hang indefinitely on exit once this happened.

Replaces the thread pool with a multiprocessing.Process (spawn context)
running both compile_restricted and exec in the child; on timeout the
parent escalates terminate() -> kill() to actually stop the process.
Scoped to just the timeout-kill fix, per design doc — no resource
limits, no public API change (run_backtest's signature is unchanged;
tests reach the timeout via monkeypatching _EXEC_TIMEOUT).

Design: docs/plans/2026-07-15-backtest-sandbox-subprocess-isolation-design.md

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Update SECURITY.md

**Files:**
- Modify: `SECURITY.md` (two separate edits — the residual-risk paragraph, and the resource-limits table row)

- [ ] **Step 1: Rewrite the "Thread timeout non-termination" paragraph**

Find this paragraph (in the `### Residual risk` section):

```
**Thread timeout non-termination** — The sandbox runs in a `ThreadPoolExecutor` thread. `Future.cancel()` cannot stop a thread that is already executing. Strategy code containing `while True: pass` will survive the 10-second timeout and continue consuming CPU in a background thread until the process exits. This does not allow filesystem writes beyond the DataFrame methods above, and the 4,096-character code limit constrains what can be submitted, but it does create unbounded CPU consumption. Full mitigation requires running the sandbox in a subprocess. Tracked for v2.0 scope.
```

Replace it with (fill in today's actual date in place of `YYYY-MM-DD`):

```
**Thread timeout non-termination (fixed YYYY-MM-DD)** — The sandbox previously ran in a `ThreadPoolExecutor` thread; `Future.cancel()` cannot stop a thread that is already executing, so strategy code containing `while True: pass` survived the 10-second timeout and kept consuming CPU in a background thread. This was worse than "unbounded CPU consumption" alone: `concurrent.futures.thread` registers a non-daemon-thread join in its interpreter-shutdown hook, so a host process that ever hit this path could hang indefinitely on exit, unable to terminate cleanly without a forced kill. The sandbox now runs strategy code (both `compile_restricted` and `exec`) in an isolated `multiprocessing.Process` (spawn context); on timeout the parent calls `terminate()` (SIGTERM), then escalates to `kill()` (SIGKILL) after a short grace period if the process hasn't exited — a real OS process can be forcibly stopped, unlike a thread. See `docs/plans/2026-07-15-backtest-sandbox-subprocess-isolation-design.md`.
```

**Important — do not touch the adjacent "DataFrame write methods" paragraph.** That paragraph's claim that full elimination "requires a subprocess with OS-level restrictions (`seccomp`, macOS sandbox, or Docker)" is still true after this fix: a bare `multiprocessing.Process` boundary has no syscall filtering, so `df.to_csv()` etc. remain an open residual risk. This fix does not close that gap — leave that paragraph as-is.

- [ ] **Step 2: Update the "Resource limits" table**

Find:

```
| Execution timeout | 10 seconds | `BacktestRuntimeError` (via `ThreadPoolExecutor.submit(...).result(timeout=10)`) |
```

Replace with:

```
| Execution timeout | 10 seconds | `BacktestRuntimeError` (via `multiprocessing.Process` + `terminate()`/`kill()` escalation on timeout — see `backtest.py`) |
```

- [ ] **Step 3: Commit**

```bash
git add SECURITY.md
git commit -m "$(cat <<'EOF'
docs: update SECURITY.md for backtest subprocess isolation fix

Marks the thread-timeout-non-termination residual risk as fixed and
documents the actual severity found while implementing the fix (it
could hang the whole host process on exit, not just leak CPU). Leaves
the separate DataFrame-write-methods residual risk untouched -- plain
subprocess isolation doesn't add OS-level syscall restriction, so that
gap is still open.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Update docs/test-coverage.md

**Files:**
- Modify: `docs/test-coverage.md`

- [ ] **Step 1: Regenerate real coverage numbers**

```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
pytest -m "not integration" --cov=ibkr_core_mcp --cov-report=term-missing > /tmp/coverage_output.txt 2>&1
grep "backtest.py" /tmp/coverage_output.txt
```

- [ ] **Step 2: Update the `backtest.py` row**

The current row (in the "Near-complete (90%+)" table) reads:

```
| `backtest.py` | 97% | 185–186 | `concurrent.futures.TimeoutError` path in strategy executor — requires a real timeout, not deterministically triggerable |
```

Using the actual output from Step 1: if `backtest.py` now shows 100% (the timeout path is deterministically tested via `test_timeout_actually_kills_runaway_process`'s monkeypatched short timeout, so this specific gap should close), move the row from the "Near-complete (90%+)" table to the "100% Coverage (no gaps)" table instead — as a single-column entry matching that table's format (`| backtest.py | All ... |`, matching the style of the existing `indicators.py`/`analytics.py` rows there). If any lines remain uncovered for a different reason, keep the row in "Near-complete" but replace the timeout-related "Uncovered lines"/"Reason" text with whatever `pytest --cov-report=term-missing` actually reports — do not leave the old, now-inaccurate `concurrent.futures.TimeoutError`/"not deterministically triggerable" wording in place, since that's no longer true.

Also re-check and update the file's top-line summary (`**N unit tests · M integration tests (N+M total) · P% line coverage**` and the "regenerated <date>" note) to match the new totals from Step 1's output — this file's own stated convention is to regenerate rather than hand-edit these numbers.

- [ ] **Step 3: Commit**

```bash
git add docs/test-coverage.md
git commit -m "$(cat <<'EOF'
docs: refresh test-coverage.md for backtest subprocess isolation

The timeout path (previously "not deterministically triggerable") is
now covered by test_timeout_actually_kills_runaway_process's
monkeypatched short timeout. Regenerated counts/coverage via the
documented command rather than hand-editing.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Full-suite sanity check

**Files:** none modified — verification only.

- [ ] **Step 1: Run the complete non-integration suite**

```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
pytest -m "not integration" -v > /tmp/full_suite_output.txt 2>&1 &
TEST_PID=$!
sleep 60
if kill -0 "$TEST_PID" 2>/dev/null; then
    echo "SUITE HUNG after 60s (PID $TEST_PID) — investigate before proceeding. Killing now."
    kill -9 "$TEST_PID"
else
    wait "$TEST_PID"
    echo "Exit code: $?"
fi
tail -30 /tmp/full_suite_output.txt
```

Expected: exit code 0, no failures, no hang. This confirms the rewrite didn't regress anything outside `backtest.py` (nothing else in the codebase imports from `backtest.py` except `claude_tools.py`'s `_run_backtest` handler, which only calls the unchanged public `run_backtest()` function).

- [ ] **Step 2: No commit needed** — this task is verification-only; if it fails, return to Task 2 and fix before considering the plan complete.

---

## Self-review notes (from plan authoring)

- **Spec coverage:** every section of the design doc (mechanism, data flow, kill sequence, crash handling, `SECURITY.md` updates, `test-coverage.md` update, non-goals) maps to a task above. No design-doc requirement without a corresponding task.
- **No placeholders:** the one `YYYY-MM-DD` in Task 3 is an explicit instruction to fill in the actual run date, not an unresolved TBD.
- **Type consistency:** `_execute_in_subprocess(code: str, df: pd.DataFrame, result_queue: Any) -> None` in Task 2 Step 2 matches its call site `ctx.Process(target=_execute_in_subprocess, args=(code, df, result_queue))` in Task 2 Step 3 — same three positional args, same order.
