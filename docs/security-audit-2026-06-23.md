# ibkr_core_mcp — Code Audit 2026-06-23

**Scope:** All commits since the 2026-06-10 audit — 13 modified files across correctness,
packaging, type safety, and test coverage.

**Previous audit:** `docs/security-audit-2026-06-10.md`

---

## Summary

| Category | Findings | Fixed | Deferred |
|---|---|---|---|
| Correctness | 4 | 4 | 0 |
| Packaging / quality | 8 | 8 | 0 |
| Test coverage gaps | 4 areas | 4 | 0 |
| Security | 0 new | — | — |

All findings from previous audits remain resolved. No new security issues found.

---

## Correctness Findings

### C-01 — `ping()` swallowed `tickle()` exceptions (FIXED)

**File:** `client.py:ping()`

The original `try/except` block wrapped both the status check and the `tickle()` call. Any
exception from `tickle()` — including auth errors or network failures — was silently swallowed,
causing callers to misdiagnose session liveness.

**Fix:** Split into two separate try/except blocks — one for the HTTP request, one for the
`tickle()` retry. `tickle()` exceptions now propagate normally.

---

### C-02 — Drive `market_data/` folder non-deterministic on multiple matches (FIXED)

**File:** `cache.py:_resolve_cache_folder()`

When more than one `market_data` subfolder existed in Drive (possible after a failed mkdir),
`list()` returned them in undefined order, risking a data split between the "canonical" and a
duplicate folder.

**Fix:** Added `orderBy="createdTime asc"` so the oldest (canonical) folder is always
selected. Added a `WARNING` log when duplicates exist. Added `_reset_cache_folder()` to
clear the stale handle on any Drive exception in `load()`.

---

### C-03 — HMDS extra columns leaked into cached parquet (FIXED)

**File:** `claude_tools.py:_fetch_market_data()`

The inline DataFrame construction in `_fetch_market_data` used `pd.DataFrame(data)` directly on
the raw IBKR HMDS response. HMDS includes undocumented extra columns (e.g., `v`, `gap`) that
vary by contract type and were silently included in cached parquet files, causing schema drift
between parquet files for different instruments.

**Fix:** Replaced the inline build with `bars_to_dataframe(raw)` — the same canonical
OHLCV normalizer used by the public API — which always produces the same 5-column schema.

---

### C-04 — `_validate_account_id` regex inconsistency (FIXED)

**Files:** `client.py`, `claude_tools.py`

`client.py` used `^[A-Za-z0-9]+$` (mixed case, unbounded length) while `claude_tools.py` used
`^[A-Z0-9]{4,12}$` (uppercase, length-constrained). An account ID accepted at the tool layer
could be rejected at the client layer (or vice versa) depending on call path.

**Fix:** Both now use `^[A-Z0-9]{4,12}$` matching real IBKR account ID format (e.g.
`U1234567`, `DU12345`).

---

## Packaging / Quality Findings

### P-01 — `py.typed` at repo root, invisible to pip consumers (FIXED)

**File:** `py.typed` (was at root, moved to `ibkr_core_mcp/py.typed`)

PEP 561 requires `py.typed` to be inside the package directory. The marker at the repo root
was never included in the installed package, so mypy treated the package as untyped when
consumed via pip. Also registered in `[tool.setuptools.package-data]`.

---

### P-02 — OS classifiers missing Linux and Windows (FIXED)

**File:** `pyproject.toml`

Only `"Operating System :: MacOS"` was declared. Added Linux and Windows classifiers since
the core package (excluding gateway Docker and Touch ID) is cross-platform.

---

### P-03 — `websockets` ImportError gives no install guidance (FIXED)

**File:** `streaming.py:connect()`

A bare `import websockets` would raise a generic `ModuleNotFoundError`. Fixed with a wrapped
re-raise that includes the install command: `pip install 'ibkr_core_mcp[server]'`.

---

### P-04 — `AuthStrategy` Protocol not exported (FIXED)

**File:** `__init__.py`

`AuthStrategy` was defined in `auth.py` and used as the standard auth injection point, but
was not exported from the public surface. Consumers implementing custom auth strategies could
not type-check against it without an internal import. Added to `__init__.py` imports and
`__all__`.

---

### P-05 — README inaccuracies (FIXED)

| Location | Issue | Fix |
|---|---|---|
| Line 54 | `pip install ibkr_core_mcp` (PyPI) | `git+https://...` (actual install) |
| Line 136 | `claude-opus-4-8` (wrong model) | `claude-sonnet-4-6` |
| Line 201 | `--streaming` flag | `--stream` |
| Line 21 | Analytics desc included "Beta/return attribution" (unimplemented) | Corrected to actual metrics |
| Line 260 | `IBKR_SQLITE_PATH` marked required | Marked optional (has a default) |

---

### P-06 — CHANGELOG absent (FIXED)

No changelog existed for v0.1.0–v0.4.0. `CHANGELOG.md` added covering all four releases.

---

### P-07 — Stale tool counts in docs (FIXED)

`CLAUDE.md` and `SECURITY.md` still referenced 22 tools; actual count is 33 (`ClaudeToolkit`)
+ 2 MCP-only = 35. Updated.

---

## Test Coverage Gaps (all filled)

### T-01 — `SQLiteStore` backtest and log methods untested

Added: `save_backtest`, `get_backtests` (symbol filter, strategy filter), `get_position_history`
date filters, `get_signals` date filters, `log_entry`, `get_log` (event filter, `n` limit).

### T-02 — `IBKRWebSocket._parse_message` edge cases untested

Added: bare-dict `data` (not wrapped in list), empty list, `conid` fallback from topic string,
non-numeric field silently skipped. Also: localhost guard, websockets `ModuleNotFoundError`
with install hint, `subscribe()` and `listen()` guards before `connect()`.

### T-03 — `mcp_server` resource handlers and retry loop untested

Added: all three resource handlers (`ibkr://accounts`, `ibkr://positions/current`,
`ibkr://trades/recent`, unknown URI → `[]`), `get_price_alerts` with results,
`_stream_loop_with_retry` retry-on-error and `CancelledError` propagation.

### T-04 — `ClaudeToolkit` handler gaps

Added: `_safe_error` all 10 exception branches, `_fetch_market_data` live (cache-miss) path,
`_sync_flex_trades` missing-token early return, `_get_positions` empty and field-fallback
(`contractDesc` → `ticker` → `symbol`), `_get_pnl` empty and non-numeric-skip, `_preview_order`
LMT (includes `price`) and MKT (no `price`).

---

## Test Count

| Audit | Tests |
|---|---|
| 2026-06-10 | 170 |
| 2026-06-23 | 300 (+130) |

---

## Security Assessment

No new security issues found. The two-gate order protection (Touch ID + tkinter modal),
`RestrictedPython` sandbox, input validation, and `SECURITY.md` policy all remain intact
and unchanged from the previous audit.

---

## Remaining Known Gaps

| ID | Sev | Description | Status |
|---|---|---|---|
| SEC-09 | LOW | Subprocess dialog isolation (tkinter in-process) | Deferred — architectural |
| B-03 | LOW | Sandbox `df` escape via in-place mutation | Accepted residual |

No new deferred items.
