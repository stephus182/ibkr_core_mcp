# Backtest Sandbox: Subprocess Isolation — Design

**Created:** 2026-07-15
**Status:** Approved — ready for implementation plan

---

## Problem

`run_backtest()` (`ibkr_core_mcp/backtest.py:129`) executes untrusted `RestrictedPython`-compiled
strategy code inside a `ThreadPoolExecutor(max_workers=1)` with a 10-second timeout
(`_EXEC_TIMEOUT`). On timeout, the code calls `fut.cancel()` — a no-op for an already-running
thread. Strategy code containing `while True: pass` survives the timeout and continues consuming
CPU in an orphaned background thread until the whole host process exits.

This is currently documented as an accepted residual risk in `SECURITY.md` ("Thread timeout
non-termination... Full mitigation requires running the sandbox in a subprocess. Tracked for v2.0
scope") rather than fixed. This design closes that gap.

## Goals

- Make the timeout actually stop the runaway code — kill the OS process running it, not just
  abandon a `Future`.
- Keep `run_backtest()`'s public signature and exception contract (`BacktestSyntaxError`,
  `BacktestRuntimeError`, `BacktestResult`) unchanged. This is an internal-only rewrite.

## Non-goals (explicitly deferred)

- **CPU/memory resource limits** (`RLIMIT_CPU`, `RLIMIT_AS`, etc.) on the child process. Scoped
  out — this fix addresses exactly the documented gap (timeout doesn't actually kill), not a
  broader sandboxing hardening pass. A process boundary makes resource limits *possible* in the
  future, but adding them now is out of scope.
- **OS-level syscall restriction** (seccomp, macOS sandbox profiles, Docker). The existing
  "DataFrame write methods" residual risk in `SECURITY.md` (strategy code can call `df.to_csv()`
  etc.) is **not** closed by this change — a bare `multiprocessing.Process` boundary has no syscall
  filtering. That residual risk stays open and documented as such; this fix must not imply it's
  resolved.
- **Public API additions.** No new `timeout_s` parameter. Tests exercise the timeout path by
  monkeypatching the module-level `_EXEC_TIMEOUT` constant.

## Design

### Mechanism

Replace the `ThreadPoolExecutor` block with a raw `multiprocessing.get_context("spawn").Process`.
A raw `Process` (not `ProcessPoolExecutor`) is required because it's the only stdlib API that
gives a handle capable of actually terminating an in-flight task — `ProcessPoolExecutor.result(timeout=...)`
raising `TimeoutError` does **not** stop the pooled worker; the runaway code would keep running
in the pool indefinitely. `subprocess.run()` + a separate worker script (the pattern
`order_confirm.py` → `_order_dialog.py` already uses) was considered and rejected here: it would
require hand-rolling `DataFrame` serialization across stdin/stdout (parquet+base64, since JSON
loses dtype/index fidelity), whereas `multiprocessing.Process` args are pickled automatically by
the stdlib — safe here because both ends (parent and child) are our own trusted code, not
attacker-controlled deserialization.

Both `compile_restricted()` and `exec()` move into the child process — this isolates the *entire*
untrusted-code lifecycle behind the process boundary, not just the exec step (today, compilation
already runs in-process ahead of the thread; there's no reason to leave it there once a subprocess
exists).

### Data flow

1. Parent (`run_backtest`, unchanged code-length fast-fail still applies before any process is
   spawned): builds `ctx = multiprocessing.get_context("spawn")`, a `ctx.Queue()`, and a
   `ctx.Process(target=_execute_in_subprocess, args=(code, df, queue))`. `_execute_in_subprocess`
   is a new **module-level** function in `backtest.py` (must be module-level, not a nested closure,
   so `spawn` can pickle it by reference).
2. Child (`_execute_in_subprocess`): calls `compile_restricted(code, "<strategy>", "exec")`. On
   `SyntaxError`, puts `("syntax_error", str(e))` on the queue and returns. Otherwise builds the
   same sandbox dict as today (`safe_globals`, `_write_guard`, `_sandboxed_getattr`, `_SAFE_PD`,
   `_SAFE_NP`, `df`, etc.) and calls `exec(byte_code, sandbox)`. On success, puts
   `("ok", sandbox.get("df", df))`. On any `Exception`, puts
   `("runtime_error", f"{type(e).__name__}: {e}")` — same message format as today.
3. Parent: `process.start()`, then `process.join(timeout=_EXEC_TIMEOUT)`.
   - If the process is still alive after the join: **kill sequence** (see below), then raise
     `BacktestRuntimeError(f"Strategy timed out after {_EXEC_TIMEOUT}s")` — identical message to
     today.
   - If the process finished: non-blocking read from the queue (`queue.get_nowait()`). This is
     safe without a race: `multiprocessing.Queue`'s child-side default behavior is to block
     process exit until its background feeder thread has fully flushed all `put()` calls to the
     underlying pipe — so by the time `process.join()` confirms the child has exited, anything it
     put is already readable.
     - `("ok", result_df)` → proceed to the existing `"signal" not in result_df.columns` check and
       `_compute_metrics()`, both untouched.
     - `("syntax_error", msg)` → raise `BacktestSyntaxError(f"Strategy syntax error: {msg}")`.
     - `("runtime_error", msg)` → raise `BacktestRuntimeError(f"Strategy runtime error: {msg}")`.
     - Queue empty despite the process having exited (crash — e.g. `MemoryError` before it could
       put anything, or a segfault) → raise `BacktestRuntimeError` with a generic message
       referencing `process.exitcode`, instead of blocking forever on an empty queue.

### Kill sequence

New constant `_KILL_GRACE_S` (module-level, alongside `_EXEC_TIMEOUT`, matching the existing
`_S`-suffix naming convention used for `order_confirm.py`'s `_DIALOG_TIMEOUT_S`):

```python
process.terminate()       # SIGTERM
process.join(_KILL_GRACE_S)
if process.is_alive():
    process.kill()        # SIGKILL
    process.join()        # reap
```

No attempt to distinguish "cooperative shutdown" from "forced" — a sandboxed strategy process has
no legitimate cleanup to perform either way.

### What stays exactly as-is

- `_compute_metrics()`, `BacktestResult`, `BacktestResult.to_dict()` — untouched.
- The `_MAX_CODE_LEN` fast-fail — stays in the parent, before any process is created.
- `_write_guard`, `_sandboxed_getattr`, `_SAFE_NP`, `_SAFE_PD`, `_DENIED_ATTRS` — unchanged, just
  now referenced from inside `_execute_in_subprocess` instead of inline in `run_backtest`.
- `run_backtest()`'s signature, docstring contract, and both exception types.

## Testing

- New test: monkeypatch `ibkr_core_mcp.backtest._EXEC_TIMEOUT` (and `_KILL_GRACE_S` if needed to
  keep the test fast) to a small value (e.g. `0.3`), run `code = "while True: pass"`, assert
  `BacktestRuntimeError` is raised with a "timed out" message, and assert the whole call completes
  in well under a second of wall time (proves the kill is real, not a disguised hang).
- Same test also asserts `multiprocessing.active_children() == []` immediately after the call
  returns — the direct analog of the original bug report ("orphaned thread survives"); proves no
  process leaked.
- All 15 existing tests in `tests/test_backtest.py` must pass unmodified — the public contract
  (exception types, messages, `BacktestResult` shape) does not change.
- `docs/test-coverage.md:33`'s row noting the timeout path as "not deterministically triggerable"
  becomes stale once this lands — remove or rewrite it, and re-check `backtest.py`'s coverage %.

## Docs to update

- **`SECURITY.md`**: rewrite the "Thread timeout non-termination" residual-risk paragraph to state
  it's fixed (subprocess isolation with terminate→kill escalation), referencing this design doc.
  Separately, tighten the "DataFrame write methods" paragraph's phrasing so it's clear plain
  subprocess isolation (what this fix adds) is *not* the same as the OS-level restriction
  (seccomp/macOS sandbox/Docker) that paragraph says would be needed to close that gap — don't let
  the two residual-risk items blur together.
- **`SECURITY.md`**'s "Resource limits" table: update the "Execution timeout" row's mechanism
  description from `ThreadPoolExecutor.submit(...).result(timeout=10)` to the new
  `multiprocessing.Process` + terminate/kill description.
- **`docs/test-coverage.md`**: update the `backtest.py` coverage row per the testing note above.
