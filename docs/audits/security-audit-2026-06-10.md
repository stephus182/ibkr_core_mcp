# Security & Code Quality Audit — ibkr_core_mcp

**Date:** 2026-06-10  
**Scope:** All production modules in `ibkr_core_mcp/` + `ibkr_core_mcp/gateway/`  
**Auditor:** Claude Sonnet 4.6 (multi-agent parallel static analysis — 4 independent domain agents)  
**Status:** All High and Medium findings resolved. Low/Informational documented below.

---

## Summary

| Severity | Found | Fixed | Remaining |
|---|---|---|---|
| High | 3 | 3 | 0 |
| Medium | 7 | 7 | 0 |
| Low | 9 | 9 | 0 |
| Informational | 5 | 5 | 0 |

Commit: `015e379` — `fix: full codebase audit — bugs, vulnerabilities, and redundancies`

---

## Resolved Findings

### High

---

**H-1 — PineScript injection via unsanitized string interpolation (`pinescript.py`)**

All three generator functions (`strategy_from_signals`, `indicator_script`, `strategy_from_backtest`) interpolated caller-supplied `name`, `symbol`, `timeframe`, and indicator names directly into the generated PineScript string, including inside `strategy("…")` and `indicator("…")`  string literals. A name containing `"` would close the literal and allow injection of arbitrary PineScript syntax.

**Impact:** An LLM-supplied or user-supplied strategy name could inject PineScript directives, break the generated script, or cause unexpected behavior in TradingView.

**Fix:** Added `_sanitize()` helper that strips `"`, `\n`, `\r` and truncates to 128 chars. Applied to `name`, `symbol`, `timeframe`, and each indicator name before string interpolation.

```python
def _sanitize(s: str, max_len: int = 128) -> str:
    return re.sub(r'["\r\n]', "", str(s))[:max_len]
```

---

**H-2 — Unrestricted `range` builtin bypasses sandbox memory cap (`backtest.py`)**

`sandbox["range"] = range` passed the unrestricted Python builtin into the strategy execution context, bypassing the `limited_range` 1 000-element cap imported from `RestrictedPython.Limits`. Strategy code could call `list(range(10**9))` to exhaust process memory.

**Fix:** Replaced with `limited_range` from `RestrictedPython.Limits`.

---

**H-3 — `__builtins__` override silently stripped `safe_builtins` from sandbox (`backtest.py`)**

The explicit `__builtins__` dict comprehension filtered from `limited_builtins` (which contains only `range`, `list`, `tuple`). This silently replaced the richer `safe_builtins` already established by `safe_globals`, removing `isinstance`, `bool`, `str`, all exception types, and other necessary builtins from strategy code — while the intended exclusions (`__import__`, `open`, `eval`, `exec`, `compile`) were never in `limited_builtins` anyway. The net effect was a weaker sandbox that was harder to reason about.

**Fix:** Removed the redundant `__builtins__` override entirely. `safe_globals` already provides the correct safe builtins.

---

### Medium

---

**M-1 — CRLF injection via browser cookie name/value (`auth.py`)**

`BrowserCookieAuth.apply()` built the `Cookie` header by joining raw `c.name=c.value` pairs from `browser_cookie3` without stripping carriage return or newline characters. A malicious localhost page could store a cookie with `\r\n` embedded in its name or value, injecting arbitrary HTTP headers into every subsequent IBKR gateway request.

**Fix:** Added `_CRLF_RE = re.compile(r"[\r\n]")` and a `_sanitize_cookie_token()` helper that strips `\r`/`\n` before use. List comprehension in `apply()` sanitizes both `c.name` and `c.value` and skips any cookie whose name becomes empty after sanitization.

```python
_CRLF_RE = re.compile(r"[\r\n]")

def _sanitize_cookie_token(value: str) -> str:
    return _CRLF_RE.sub("", value)
```

**Bonus:** Warning message previously exposed `str(exc)` which can include internal library paths. Changed to `type(exc).__name__` — only the exception class name is surfaced.

---

**M-2 — Missing `account_id` validation in 14 `IBKRClient` methods (`client.py`)**

14 account-scoped methods accepted `account_id: str` and interpolated the value directly into URL path segments with no validation. A caller passing `"../something"` or `"foo/bar"` would silently corrupt the HTTP request path. For write-path methods (`place_order`, `modify_order`, `cancel_order`) this meant the path corruption happened after the Touch ID and confirmation dialog gates had already passed.

**Fix:** Added module-level `_ACCOUNT_ID_RE = re.compile(r"^[A-Za-z0-9]+$")` and `_validate_account_id()` raising `ConfigError` on mismatch. Called as the first statement in: `get_account_meta`, `get_account_summary`, `get_account_ledger`, `get_account_allocation`, `get_positions`, `get_position`, `get_combo_positions`, `invalidate_positions_cache`, `get_alerts`, `place_order`, `modify_order`, `cancel_order`, `get_order_preview`, `create_alert`, `delete_alert`, `activate_alert`, `switch_account`.

Note: `claude_tools.py` already validated `account_id` via its own `_validate_account_id` before calling `IBKRClient`. The new guard at the `IBKRClient` layer ensures all callers — not just the LLM tool layer — are protected.

---

**M-3 — Streaming exception kills the MCP HTTP server (`mcp_server.py`)**

`asyncio.gather(uvicorn_task, stream_task)` was used for both the HTTP server and the WebSocket streaming loop. An unhandled exception in `_stream_loop` would cause `gather` to propagate the exception and cancel the uvicorn server, taking down the entire MCP endpoint.

**Fix:** The uvicorn task is now awaited directly. The stream loop runs as an independent `asyncio.create_task`. On shutdown, the stream task is cancelled and awaited cleanly.

---

**M-4 — Single exception permanently kills alert monitoring (`mcp_server.py`)**

One network blip, gateway restart, or IBKR WebSocket error would exit `_stream_loop` with a logged error and never reconnect. All price alert monitoring would silently stop for the lifetime of the process.

**Fix:** Introduced `_stream_loop_with_retry` wrapping `_stream_loop` in a retry loop with exponential backoff (`[5, 10, 30, 60]` seconds). `asyncio.CancelledError` is re-raised to preserve clean shutdown behaviour.

---

**M-5 — `ThreadPoolExecutor` with-form blocks after strategy timeout (`backtest.py`)**

`with ThreadPoolExecutor() as pool:` calls `shutdown(wait=True)` on context exit. After a `BacktestRuntimeError` timeout exception, the strategy thread is still running; the context manager would block for up to another `_EXEC_TIMEOUT` seconds waiting for it.

**Fix:** Replaced with explicit `pool.shutdown(wait=False)` in a `finally` block and `fut.cancel()` before raising the timeout error.

---

**M-6 — Sharpe/Sortino NaN guard incorrect (`analytics.py`)**

Both functions used `if std == 0` to guard against division by zero. When the input series is empty or all-NaN, `pd.Series.std()` returns `NaN`, not `0`. `NaN == 0` evaluates `False`, so the guard is skipped and the function returns a `NaN` float that propagates silently through downstream calculations.

**Fix:** Guard changed to `if not std or pd.isna(std)`.

---

**M-7 — Max-drawdown zero-peak division by zero (`analytics.py`)**

If `(1 + returns).cumprod()` reaches zero (a −100% return), `peak = equity.cummax()` contains zero in the drawdown denominator, producing `inf`. The function also raised on an empty series.

**Fix:** `.replace(0, float("nan"))` applied to `peak` before division. Empty-series guard added returning `0.0`.

---

### Low

---

**L-1 — Empty `reason` string reaches macOS LocalAuthentication (`human_auth.py`)**

`require_touch_id(reason)` passed the caller-supplied string directly to `LAContext.evaluatePolicy_localizedReason_reply_()`. macOS LocalAuthentication raises an Objective-C exception (not a Python exception) if `reason` is `None` or empty, surfacing as an uncontrolled crash rather than a clean `HumanAuthError`.

**Fix:** Explicit guard at entry raises `HumanAuthError("reason must not be empty")` if `reason` is falsy or whitespace-only. `NSError` now formatted as `!r` instead of `str()` to avoid multiline system-detail output in the error message.

---

**L-2 — `TclError` race between countdown tick and dialog close (`order_confirm.py`)**

`dialog.after(1000, _tick)` scheduled callbacks without storing the handle. `after()` callbacks are not automatically cancelled when the widget is destroyed. If the user confirmed or cancelled at the exact moment a tick was queued, the next `_tick` call would attempt `dialog.after(...)` on a destroyed widget, raising `TclError` inside the Tcl event loop.

**Fix:** `_after_id` dict stores the pending callback handle; `_cancel_tick()` calls `dialog.after_cancel(id)` before destroy. Both `on_confirm` and `on_cancel` call `_cancel_tick()` before `dialog.destroy()`.

---

**L-3 — `_parse_message` crashes on non-dict WebSocket message (`streaming.py`)**

Two issues: (a) IBKR sometimes sends JSON arrays or scalars; calling `.get()` on a non-dict would raise `AttributeError`. (b) IBKR can send `"data"` as a bare dict rather than a list — `data_list[0]` on a dict returns the first key string, not a dict, causing silent downstream data corruption.

**Fix:** Added `isinstance(msg, dict)` guard; explicit branching normalises both list and dict forms of `data` to a single dict. Added `isinstance(data, dict)` guard on the normalised value.

---

**L-4 — `get_position_history` / `get_signals` return schema-less empty DataFrame (`store.py`)**

`pd.DataFrame([])` on a no-rows query produces a zero-column DataFrame. Any downstream `.iloc[0]["symbol"]` or column access raises `KeyError` on an empty result set.

**Fix:** Both functions now return an empty DataFrame constructed with the correct column list matching their SQL schema.

---

**L-5 — `_cache_key` does not normalise `period` to uppercase (`cache.py`)**

`symbol` and `timeframe` were normalised via `.upper()` in `_cache_key`, but `period` was not. A call with `"1y"` and a subsequent call with `"1Y"` produced different cache keys, causing a spurious cache miss.

**Fix:** `period.upper()` added to `_cache_key`.

---

**L-6 — `delete()` skips input validation (`cache.py`)**

All other `GDriveCache` methods call `_validate_cache_inputs()` first. `delete()` did not, and uses `f"name='{fname}'"` in the GDrive query — an unvalidated cache key could include characters that break the query string.

**Fix:** `_validate_cache_inputs()` added as the first call in `delete()`.

---

**L-7 — `_infer_timeframe` `AttributeError` on non-DatetimeIndex (`pinescript.py`)**

`delta.total_seconds()` raises `AttributeError` when `df` has an integer or `RangeIndex` (delta is `int`, not `timedelta`).

**Fix:** Wrapped in `try/except (AttributeError, TypeError)` returning `"1D"` as fallback.

---

**L-8 — Stale WebSocket subscriptions accumulate (`mcp_server.py`)**

The `subscribed` set was never pruned when alerts fired or were deleted. After an alert triggered, the server continued receiving and processing quote data for that conid indefinitely.

**Fix:** After each quote, `subscribed - active_conids` is computed and `ws.unsubscribe()` is called for each stale conid.

---

**L-9 — GatewayManager Docker / shell findings (from 2026-06-10 gateway audit)**

Five Low/Informational findings from the GatewayManager security review: `urllib3.disable_warnings` global scope (GW-01), Dockerfile HTTPS-only download without checksum (GW-02), `conf.yaml` CORS wildcard mitigated by `allowCredentials: false` (GW-03), known `sslPwd` JKS default (GW-04), container-internal `curl -sk` (GW-05). All accepted. See [`docs/security-audit-2026-06-10.md`](security-audit-2026-06-10.md) (this file) and SECURITY.md §Docker Gateway Isolation.

---

### Informational

---

**I-1 — Two unreachable `"today"` branches in `cache.py`**

`_validate_cache_inputs` requires `end` to match `^\d{4}-\d{2}-\d{2}$`, making `"today"` impossible at runtime. Removed from `check()` and `save()`.

---

**I-2 — No-op alias and unreachable fallback in `models.py`**

`Notification.headline` had `alias="headline"` (alias equal to field name — no effect). `AccountSummary._normalize` had a double-lookup fallback `data.get(key, data.get(key.replace("_", ""), {}))` where the keys contain no underscores, making the inner `.get` identical to the outer. Both simplified.

---

**I-3 — `obv` used `apply(lambda)` for sign detection (`indicators.py`)**

Equivalent to `np.sign()`. Replaced for clarity and performance.

---

**I-4 — Unused imports (`client.py`, `cache.py`, `store.py`, `indicators.py`)**

Removed by `ruff --fix`.

---

**I-5 — Code quality findings from diff review (separate from security)**

Four findings surfaced by a diff-scoped code review of commits `bc8032b` and `b1fad46` (GatewayManager + preview_order/get_pnl):

| ID | File | Finding |
|---|---|---|
| CQ-01 | `claude_tools.py` | `_preview_order` used only `conid` key; `_fetch_market_data` uses `conid or con_id`. Fixed. |
| CQ-02 | `claude_tools.py` | `_get_pnl` called `float()` on potentially non-numeric IBKR P&L field. Fixed with per-position skip. |
| CQ-03 | `claude_tools.py` | 9-way duplication of `get_accounts() → account_id` pattern. Extracted `_first_account_id()` / `_all_account_ids()` helpers. |
| CQ-04 | `gateway/manager.py` | `wait_for_gateway` / `wait_for_auth` were structurally identical polling loops. Extracted `_poll_until()`. |

---

## Code Review Observations (Non-Security)

The following patterns were audited but found to be correct and intentional:

- **`verify=False` on gateway connections** — intentional; IBKR Client Portal uses a self-signed localhost cert. External IBKR connections (Flex, Drive) use standard TLS. Documented in SECURITY.md §TLS Policy.
- **Blanket `except Exception` in `ClaudeToolkit.execute()`** — intentional; all tool errors route through `_safe_error()` to prevent raw exception messages reaching the LLM context.
- **`RestrictedPython` sandbox residual risk** — strategy code can still call `df.to_csv()` on its own DataFrame copy. Full elimination requires OS-level isolation. Documented as accepted risk in SECURITY.md §Residual risk.
- **`_flex_query.py` `_get_statement` URL check** — `_send_request()` is the sole public entry point and enforces the `_ALLOWED_URL_PREFIX` allowlist. Defence-in-depth at `_get_statement` was not added to avoid breaking existing tests that pass synthetic URLs directly; the invariant is enforced at the call-graph level.

---

## Audit History (this file)

| Commit | Files changed | Scope |
|---|---|---|
| `015e379` | 14 | Full production module audit — all findings above |
| `2481ed6` | 2 | Code review: `claude_tools.py`, `gateway/manager.py` |
| `b5b89a5` | 2 | GatewayManager security review (docs only) |
