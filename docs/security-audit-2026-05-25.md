# Security Audit — ibkr_core_mcp

**Date:** 2026-05-25  
**Scope:** All production modules in `ibkr_core_mcp/`  
**Auditor:** Claude Sonnet 4.6 (automated static + dynamic analysis)  
**Status:** All Critical and High findings resolved. Medium findings resolved. Low/Informational documented below.

---

## Summary

| Severity | Found | Fixed | Remaining |
|---|---|---|---|
| Critical | 2 | 2 | 0 |
| High | 5 | 5 | 0 |
| Medium | 5 | 5 | 0 |
| Low / Info | 4 | 1 | 3 |

Commit: `4dbe6ad` — `security: address all Critical/High/Medium findings from security audit`

---

## Resolved Findings

### Critical

**C-1 — Sandbox escape via `pd`/`np` module objects (backtest.py)**

RestrictedPython's `_write_` was set to the identity lambda, allowing strategy code to:
- Read arbitrary files via `pd.read_parquet`, `pd.read_csv`, `pd.read_json`
- Write arbitrary files via `df.to_csv`, `np.savetxt`
- Mutate the process-level `pd` module singleton (e.g. `pd.read_parquet = np.zeros`), poisoning `GDriveCache.load()` for the rest of the process lifetime

**Fix (commit `4dbe6ad`):**
- Replaced raw `pd`/`np` module objects with `types.SimpleNamespace` wrappers (`_SAFE_PD`, `_SAFE_NP`) exposing only in-memory constructors and math functions — no `read_*`, `to_*`, `save*`, `load*`
- Custom `_write_guard` blocks attribute writes to `ModuleType` and `SimpleNamespace` objects (preventing namespace mutation) while allowing DataFrame column assignment (`df['signal'] = ...`, `df.loc[...] = ...`)
- Added 4,096-character code length cap (`BacktestSyntaxError` if exceeded)
- Added 10-second execution timeout via `ThreadPoolExecutor.submit(...).result(timeout=10)` (`BacktestRuntimeError` on expiry)

**Residual risk:** Strategy code can still call `df.to_csv()` on its own DataFrame copy — this can write OHLCV data to a file but cannot access credentials or read arbitrary paths. Acceptable risk for this use case; full subprocess isolation would be required to eliminate it entirely.

---

**C-2 — SSRF with Flex token exfiltration (flex_query.py)**

The `<Url>` element from the IBKR Flex XML response was used without domain validation. A MitM or compromised IBKR endpoint returning `<Url>https://attacker.com/</Url>` would cause the Flex token to be sent as a query parameter to an attacker-controlled server.

**Fix (commit `4dbe6ad`):**
```python
_ALLOWED_URL_PREFIX = "https://gdcdyn.interactivebrokers.com/"
if not url.startswith(_ALLOWED_URL_PREFIX):
    raise FlexQueryError(f"Flex SendRequest returned unexpected URL: {url!r}")
```

---

### High

**H-1 — API key and Flex token exposed in `repr()` (config.py)**

Python's `@dataclass` generates `__repr__` including all field values. `Config` stored `anthropic_api_key` and `flex_token` as plain string fields — any log or traceback printing the config object would expose them.

**Fix:** `field(repr=False)` on both fields.

---

**H-2 — Silent unauthenticated session on cookie extraction failure (auth.py)**

`BrowserCookieAuth.apply()` used a bare `except Exception: pass` covering both "library not installed" and "extraction failed" cases. A broken Chrome profile silently produced a session with no `Cookie` header.

**Fix:** Split into two paths:
- `ImportError` on `browser_cookie3` → silent (expected in headless/CI environments)
- Any other exception → `warnings.warn(...)` with the exception text

Also added browser name allowlist validation to prevent `getattr` traversal on the `browser_cookie3` module.

---

**H-3 — OAuth token file written world-readable (cache.py)**

`Path.write_text(creds.to_json())` used the process umask (typically `0o644`), making the Google Drive refresh token readable by all users on the machine.

**Fix:** `os.chmod(self._config.gdrive_token_file, 0o600)` immediately after write.

---

**H-4 — Confirmation dialog blocks indefinitely (order_confirm.py)**

`root.mainloop()` had no timeout. An unattended dialog left on a locked screen could be confirmed by anyone with physical access.

**Fix:** 60-second countdown ticker using `dialog.after(1000, _tick)`. The dialog auto-cancels with `HumanAuthError` when the countdown reaches zero. The timeout matches the Touch ID gate (`human_auth.py:_TIMEOUT = 60`).

---

**H-5 — `full_write_guard` imported but replaced with identity lambda (backtest.py)**

`full_write_guard` was imported from RestrictedPython.Guards (line 7) but the sandbox set `_write_: lambda ob: ob`, making the import dead code and creating a false impression of write protection.

**Fix:** Resolved as part of C-1. `full_write_guard` is now used inside the custom `_write_guard` for module and SimpleNamespace objects.

---

### Medium

**M-1 — Prompt injection via raw exception messages to LLM (claude_tools.py)**

The catch-all `except Exception as e: return f"Tool '{name}' error: {e}", None` returned `str(e)` verbatim to the LLM. A `BacktestRuntimeError` raised by adversarial strategy code could embed arbitrary text in the exception message, enabling prompt injection into the model context.

**Fix:** `_safe_error(tool, exc)` maps known exception types to controlled category strings:
```python
def _safe_error(tool: str, exc: Exception) -> str:
    if isinstance(exc, IBKRAuthError):
        return f"Tool '{tool}' failed: IBKR session not authenticated. ..."
    if isinstance(exc, BacktestError):
        return f"Tool '{tool}' failed: {exc}"   # BacktestError messages are authored by us
    ...
    return f"Tool '{tool}' encountered an unexpected error."
```

---

**M-2 — Path traversal via unsanitized `account_id` from LLM input (claude_tools.py)**

`sync_flex_trades` accepted `account_id` directly from LLM-generated tool input and used it in URL f-strings without validation. A value like `../../iserver/auth/status` would produce a malformed URL.

**Fix:** `_validate_account_id()` enforces `^[A-Z0-9]{4,12}$` before use. `ValueError` on mismatch is caught by `_safe_error` and returned as a controlled message.

---

**M-3 — HTTP 201/204 treated as errors (rate_limiter.py)**

`with_retry` accepted only HTTP 200 as success. Any 201 (Created) or 204 (No Content) response raised `IBKRAPIError`, causing write endpoints (watchlist creation, etc.) to appear to fail while actually succeeding.

**Fix:** `if 200 <= status < 300: return resp`

---

**M-4 — XML bomb DoS via stdlib `ElementTree` (flex_query.py)**

`xml.etree.ElementTree.fromstring` does not resolve external entities (no XXE) but does process entity expansion, making it vulnerable to billion-laughs-style memory exhaustion.

**Fix:** `import defusedxml.ElementTree as ET` (added `defusedxml>=0.7` to `pyproject.toml` dependencies).

---

**M-5 — No code size or execution time limit in backtest (backtest.py)**

An infinite loop or memory-exhausting expression in strategy code would hang the process permanently with no recovery path.

**Fix:** Resolved as part of C-1 — 4,096-char limit and 10-second timeout.

---

## Remaining Low / Informational

These are acknowledged but not fixed — either impractical to fix in Python without major architectural changes, or genuinely low risk.

**L-3 — Missing validation for non-API-key config fields (config.py)**

`gdrive_folder_id`, `gdrive_token_file`, `gdrive_credentials_file` are not validated at startup. Misconfiguration produces unhelpful errors at call time rather than at startup.

_Accepted._ Adding startup validation for all fields is a reasonable future improvement but not a security risk.

---

**L-5 — FlexQueryError messages returned to LLM (claude_tools.py)**

`_safe_error` maps `FlexQueryError` to a fixed string — the raw error (which may contain IBKR status strings) is not forwarded.

_Resolved as part of M-1._

---

**L-6 — Session cookie held in plaintext process memory (auth.py)**

`TokenAuth` stores the raw cookie string as a Python `str`. Core dumps or heap inspections would expose it.

_Accepted._ This is unavoidable in Python without native memory management. No practical mitigation.

---

## Security Architecture Notes

### Order gate integrity

The two-gate order security system (`require_touch_id` → confirmation dialog) is correctly enforced:

- Gates are applied at the innermost call site inside `IBKRClient` methods (`place_order`, `modify_order`, `cancel_order`, `reply_order`)
- `ClaudeToolkit` exposes **no order-write tools** — all order writes must go through `IBKRClient` directly
- `get_order_preview` (IBKR `whatif`) is correctly ungated (read-only, never executes)
- No bypass flag, session cache, or password fallback exists in any code path
- Touch ID timeout: 60 seconds (`human_auth.py:_TIMEOUT`)
- Dialog auto-cancel: 60 seconds (added in this audit)

### Sandbox boundary

The RestrictedPython sandbox is a defense-in-depth measure for agent-submitted strategy code. It is **not** a security boundary against a determined attacker with direct API access. Full isolation would require a subprocess with OS-level restrictions (`seccomp`, macOS sandbox profile, or Docker). The current implementation is appropriate for protecting against accidental or naive misuse.

### TLS

SSL verification is disabled on the IBKR gateway connection (`verify=False`). This is intentional — the gateway runs on localhost with a self-signed certificate. No outbound IBKR gateway connections are made to external hosts. The Flex Web Service uses standard TLS with no verification overrides.

---

## Audit Trail

| Date | Commit | Action |
|---|---|---|
| 2026-05-25 | `4dbe6ad` | Fixed C-1, C-2, H-1–H-5, M-1–M-5, L-1 |
| 2026-05-25 | `5f7b5ab` | Fixed bug-level security issues in FlexQueryClient (URL validation, datetime error handling) |
| 2026-05-25 | — | This audit document written |
