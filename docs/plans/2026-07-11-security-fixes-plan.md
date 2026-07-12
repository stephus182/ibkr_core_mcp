# Security Fixes 2026-07-11 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all 6 findings from `docs/security-audit-2026-07-11.md` (4 High, 2 Medium) — no deferrals. Each task is independently testable and commits on its own.

**Architecture:** Six independent, mostly non-overlapping fixes across `backtest.py`, `client.py`, `gateway/manager.py`, `gateway/conf.yaml`, `scrape_fallback.py`, and `claude_tools.py`, plus doc corrections in `SECURITY.md`/`README.md` bundled into the task that falsifies each claim. A final Task 7 updates `SECURITY.md`'s Audit History table and closes out `docs/security-audit-2026-07-11.md`'s Status line once all six are verified green.

**Tech Stack:** Python 3.11+ (`.venv` of ibkr_core_mcp), pytest, RestrictedPython, pandas, `requests`/`urllib3`.

**Must run before starting:** `source /Users/steph/Claude_Projects/ibkr_core_mcp/.venv/bin/activate && pip install -e ".[dev]"` if not already set up. All commands below assume this venv is active and the cwd is the repo root.

---

## File Structure

| Path | Role in this plan |
|---|---|
| `ibkr_core_mcp/backtest.py` | Task 1 — deny `eval`/`query` in the sandbox `_getattr_` hook |
| `tests/test_backtest.py` | Task 1 — regression test |
| `ibkr_core_mcp/client.py` | Task 2 — add `_ORDER_ID_RE`/`_REPLY_ID_RE` + validation calls |
| `tests/test_client.py` | Task 2 — regression tests |
| `ibkr_core_mcp/gateway/manager.py` | Task 3 — bind Docker publish to loopback |
| `tests/test_gateway.py` | Task 3 — tighten existing test |
| `SECURITY.md` | Tasks 3, 5, 7 — correct false claims, add audit-history row |
| `README.md` | Task 3 — correct false claim |
| `ibkr_core_mcp/scrape_fallback.py` | Task 4 — dual-stack DNS resolution in `is_private_host` |
| `tests/test_scrape_fallback.py` | Task 4 — regression tests |
| `ibkr_core_mcp/gateway/conf.yaml` | Task 5 — scope IP allowlist to real RFC 1918 ranges |
| `ibkr_core_mcp/claude_tools.py` | Task 6 — path-boundary check in `_import_flex_file` |
| `tests/claude_tools/test_flex.py` | Task 6 — regression tests |
| `docs/security-audit-2026-07-11.md` | Task 7 — close out Status line |

---

## Prerequisites (check before starting)

- [ ] `cd /Users/steph/Claude_Projects/ibkr_core_mcp && source .venv/bin/activate && python -c "import ibkr_core_mcp"` succeeds.
- [ ] `pytest -m "not integration" -q` passes on current `main` before any change (baseline green).
- [ ] Work happens in a dedicated git worktree, not directly on `main` — see Task 0.

---

### Task 0: Set up isolated worktree

- [ ] **Step 1: Create worktree + branch**

```bash
git worktree add /Users/steph/Claude_Projects/ibkr_core_mcp-security-fixes -b security-fixes-2026-07-11
cd /Users/steph/Claude_Projects/ibkr_core_mcp-security-fixes
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

- [ ] **Step 2: Verify baseline is green**

Run: `pytest -m "not integration" -q`
Expected: all tests pass (0 failed). If not, stop — do not build fixes on a red baseline.

All subsequent tasks run inside this worktree directory.

---

### Task 1: Deny `eval`/`query` in the backtest sandbox (H-1, RCE)

**Files:**
- Modify: `ibkr_core_mcp/backtest.py:12` (import), `ibkr_core_mcp/backtest.py:22-32` (insert helper after `_write_guard`), `ibkr_core_mcp/backtest.py:142` (swap `_getattr_` value)
- Test: `tests/test_backtest.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_backtest.py` (after `test_sandbox_cannot_import_os`, which ends at line 126):

```python
def test_sandbox_blocks_dataframe_eval(ohlcv):
    """df.eval() runs pandas' OWN expression engine outside RestrictedPython's
    compiled-bytecode boundary — it can reach __globals__/sys.modules/os and
    achieve RCE. Must be blocked at the sandbox's _getattr_ hook.
    See docs/security-audit-2026-07-11.md H-1."""
    from ibkr_core_mcp.backtest import BacktestRuntimeError, run_backtest
    code = (
        "leak = df.eval(\"@df.__init__.__func__.__globals__['sys'].modules['os'].popen('id').read()\")\n"
        "df['signal'] = 0\n"
    )
    with pytest.raises(BacktestRuntimeError, match="eval"):
        run_backtest(code, ohlcv)


def test_sandbox_blocks_dataframe_query(ohlcv):
    """df.query() uses the same unsandboxed expression engine as df.eval()."""
    from ibkr_core_mcp.backtest import BacktestRuntimeError, run_backtest
    code = "df.query(\"close > 0\")\ndf['signal'] = 0\n"
    with pytest.raises(BacktestRuntimeError, match="query"):
        run_backtest(code, ohlcv)


def test_sandbox_still_allows_ordinary_dataframe_methods(ohlcv):
    """Denying eval/query must not break normal indicator-style strategy code."""
    from ibkr_core_mcp.backtest import run_backtest
    code = "df['signal'] = (df['close'] > df['close'].rolling(5).mean()).astype(int)"
    result = run_backtest(code, ohlcv)
    assert isinstance(result.total_return, float)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_backtest.py -k "blocks_dataframe" -v`
Expected: `test_sandbox_blocks_dataframe_eval` and `test_sandbox_blocks_dataframe_query` FAIL — `BacktestRuntimeError` is not raised (the payload executes; `raise Exception(leak)` propagates as a generic runtime error only if you already added an unrelated raise — with the code above, `df.eval(...)` succeeds silently and `pytest.raises` fails with "DID NOT RAISE"). `test_sandbox_still_allows_ordinary_dataframe_methods` should already PASS (baseline behavior, not yet changed).

- [ ] **Step 3: Add the denylist helper and wire it into the sandbox**

In `ibkr_core_mcp/backtest.py`, current lines 22-33 read:

```python
def _write_guard(ob: object) -> object:
    """Block writes to modules and safe namespaces; allow all other writes.

    Strategy code must assign columns (df['signal'] = ..., df.loc[...] = ...)
    but must not mutate the shared pd/np namespaces passed into the sandbox.
    We block writes to `types.ModuleType` and `types.SimpleNamespace` (our safe
    namespace wrappers) and allow everything else through untouched.
    """
    if isinstance(ob, (types.ModuleType, types.SimpleNamespace)):
        return full_write_guard(ob)
    return ob

# Safe numpy namespace — math/array operations only, no file I/O
```

Insert a new helper immediately after `_write_guard` (before the `# Safe numpy namespace` comment):

```python
def _write_guard(ob: object) -> object:
    """Block writes to modules and safe namespaces; allow all other writes.

    Strategy code must assign columns (df['signal'] = ..., df.loc[...] = ...)
    but must not mutate the shared pd/np namespaces passed into the sandbox.
    We block writes to `types.ModuleType` and `types.SimpleNamespace` (our safe
    namespace wrappers) and allow everything else through untouched.
    """
    if isinstance(ob, (types.ModuleType, types.SimpleNamespace)):
        return full_write_guard(ob)
    return ob


# df.eval()/df.query() run pandas' OWN expression engine (pandas/core/computation/
# expr.py) on a string, entirely outside compile_restricted's AST-level guards —
# it does unfiltered getattr/getitem/call resolution and can reach @varname (the
# sandbox's own locals), then walk __init__.__func__.__globals__ to pandas'
# unrestricted module globals, then sys.modules['os'] for RCE. safer_getattr does
# not block these — they're ordinary public method names, not dunders. Block them
# explicitly. See docs/security-audit-2026-07-11.md H-1.
_DENIED_ATTRS = frozenset({"eval", "query"})


def _sandboxed_getattr(obj: object, name: str, default: object = None) -> object:
    if name in _DENIED_ATTRS:
        raise AttributeError(
            f"backtest sandbox: access to {name!r} is blocked — pandas' own "
            "eval/query expression engine is not sandboxed by RestrictedPython"
        )
    return safer_getattr(obj, name, default)

# Safe numpy namespace — math/array operations only, no file I/O
```

Then change line 142 (inside the `sandbox` dict) from:

```python
        "_getattr_": safer_getattr,
```

to:

```python
        "_getattr_": _sandboxed_getattr,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_backtest.py -v`
Expected: all tests in the file PASS, including the 3 new ones and all pre-existing ones (especially `test_rsi_strategy`, `test_sandbox_cannot_mutate_shared_pd_namespace`, `test_sandbox_cannot_import_os` — confirms the fix doesn't regress existing sandbox behavior).

- [ ] **Step 5: Update the `run_backtest` docstring and SECURITY.md's now-inaccurate claim**

In `ibkr_core_mcp/backtest.py`, the `run_backtest` docstring currently says (around line 119-122):

```python
    Allowed: pd (safe subset), np (safe subset), basic builtins.
    Blocked: network access, os, sys, imports, attribute/name mutation.
    Not blocked: DataFrame public methods (df.to_csv etc.) — accepted residual
    risk, documented in SECURITY.md §Residual risk.
```

Change to:

```python
    Allowed: pd (safe subset), np (safe subset), basic builtins.
    Blocked: network access, os, sys, imports, attribute/name mutation,
    df.eval()/df.query() (pandas' own unsandboxed expression engine).
    Not blocked: other DataFrame public methods (df.to_csv etc.) — accepted
    residual risk, documented in SECURITY.md §Residual risk.
```

In `SECURITY.md`, the "Residual risk" section (around line 205) currently says:

```
**DataFrame write methods** — Strategy code can call `df.to_csv()`, `df.to_json()`, or `df.to_parquet()` on its own DataFrame copy. This can write the OHLCV market data passed to the sandbox to a local file, but cannot access credentials, read arbitrary paths, or make network calls. The `_SAFE_PD` namespace excludes all `pd.read_*` methods, so only write-only access to non-sensitive content is possible. Full elimination requires a subprocess with OS-level restrictions (`seccomp`, macOS sandbox, or Docker).
```

Replace with:

```
**DataFrame write methods** — Strategy code can call `df.to_csv()`, `df.to_json()`, or `df.to_parquet()` on its own DataFrame copy. This can write the OHLCV market data passed to the sandbox to a local file, but cannot access credentials, read arbitrary paths, or make network calls. The `_SAFE_PD` namespace excludes all `pd.read_*` methods, so only write-only access to non-sensitive content is possible. Full elimination requires a subprocess with OS-level restrictions (`seccomp`, macOS sandbox, or Docker).

**`DataFrame.eval`/`.query` (fixed 2026-07-11)** — Both methods run pandas' own expression engine on a string, entirely outside `compile_restricted`'s AST-level guards, and could reach `__globals__`/`sys.modules['os']` for full RCE (see `docs/security-audit-2026-07-11.md` H-1). The sandbox's `_getattr_` hook now denies `eval`/`query` by name before falling through to `safer_getattr`. Any future DataFrame method found to accept and internally evaluate a string as code (rather than treat it as data) should be added to `backtest.py`'s `_DENIED_ATTRS`.
```

- [ ] **Step 6: Run the full test suite**

Run: `pytest -m "not integration" -q`
Expected: all tests pass, no regressions outside `test_backtest.py`.

- [ ] **Step 7: Commit**

```bash
git add ibkr_core_mcp/backtest.py tests/test_backtest.py SECURITY.md
git commit -m "$(cat <<'EOF'
security: block DataFrame.eval/.query in backtest sandbox (RCE)

pandas' own eval/query expression engine runs outside RestrictedPython's
compiled-bytecode boundary and can reach __globals__/sys.modules/os for
full command execution from any run_backtest tool call. Deny both names
in the sandbox's _getattr_ hook.

See docs/security-audit-2026-07-11.md H-1.
EOF
)"
```

---

### Task 2: Validate `order_id`/`alert_id`/`reply_id` before URL construction (H-2, order-gate bypass)

**Files:**
- Modify: `ibkr_core_mcp/client.py:27` (add regexes), `ibkr_core_mcp/client.py:66-71` (add validators), and the 7 call sites listed below
- Test: `tests/test_client.py`

**Doc verification (per CLAUDE.md "API Docs First"):** IBKR's Client Portal API reference (cached at `docs/superpowers/audit-evidence/scrapes/cpapi-v1.md`, source `https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/`) documents `orderId` example values as pure digit strings (e.g. `.../order/status/1234567890`) and `alertId` explicitly as `int. Required` (line 2373, 2552 of the scrape) — both numeric. It documents `replyId` as `String. Required` with example value `a12b34c5-d678-9e012f-3456-7a890b12cd3e` (line 17113, 17138 of the scrape) — hex characters and hyphens, NOT numeric. Use two different regexes; do not assume `reply_id` is numeric.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_client.py` (after `test_validate_account_id_applied_to_write_methods`, which ends at line 596):

```python
@pytest.mark.parametrize("method_name,args", [
    ("get_order_status", ("../../etc/passwd",)),
    ("get_alert", ("../../etc/passwd",)),
])
def test_validate_order_id_rejects_path_traversal_read_methods(client, method_name, args):
    from ibkr_core_mcp.exceptions import ConfigError
    with pytest.raises(ConfigError, match="[Ii]nvalid"):
        getattr(client, method_name)(*args)


def test_delete_alert_rejects_path_traversal_alert_id(client):
    """The exact H-2 exploit path: alert_id='../order/<real orderId>' must never
    reach the network. See docs/security-audit-2026-07-11.md H-2."""
    from ibkr_core_mcp.exceptions import ConfigError
    with _patch("ibkr_core_mcp.client.require_touch_id") as mock_tid:
        with pytest.raises(ConfigError, match="[Ii]nvalid"):
            client.delete_alert("DU1234567", "../order/987654321")
    mock_tid.assert_not_called()


@pytest.mark.parametrize("bad_order_id", [
    "", "../order/1", "123/456", "123#456", "123 456", "abc123",
])
def test_validate_order_id_rejects_invalid_ids(client, bad_order_id):
    from ibkr_core_mcp.exceptions import ConfigError
    with pytest.raises(ConfigError, match="[Ii]nvalid"):
        client.get_order_status(bad_order_id)


def test_validate_order_id_accepts_valid_id(client):
    client._session.get = MagicMock(return_value=MagicMock(status_code=200, json=lambda: {}))
    client.get_order_status("987654321")  # must not raise ConfigError


@pytest.mark.parametrize("bad_reply_id", [
    "", "../reply/1", "abc/def", "abc def",
])
def test_validate_reply_id_rejects_invalid_ids(client, bad_reply_id):
    from ibkr_core_mcp.exceptions import ConfigError
    with pytest.raises(ConfigError, match="[Ii]nvalid"):
        client.reply_order(bad_reply_id)


def test_validate_reply_id_accepts_valid_uuid_shaped_id(client):
    """IBKR's documented replyId example: hex + hyphens, non-standard grouping —
    regex must not assume strict 8-4-4-4-12 UUID segments."""
    with _patch("ibkr_core_mcp.client.require_touch_id") as mock_tid, \
         _patch("ibkr_core_mcp.client.confirm_reply_dialog"):
        client._session.post = MagicMock(return_value=MagicMock(status_code=200, json=lambda: []))
        client.reply_order("a12b34c5-d678-9e012f-3456-7a890b12cd3e")
    mock_tid.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_client.py -k "order_id or reply_id or delete_alert_rejects" -v`
Expected: all new tests FAIL (no `ConfigError` currently raised for any of these — `get_order_status`, `get_alert`, `delete_alert`, `reply_order` accept any string today).

- [ ] **Step 3: Add the regexes and validators**

In `ibkr_core_mcp/client.py`, current line 27 reads:

```python
_ACCOUNT_ID_RE = re.compile(r"^[A-Z0-9]{4,12}$")
```

Change to:

```python
_ACCOUNT_ID_RE = re.compile(r"^[A-Z0-9]{4,12}$")

# IBKR order/alert IDs are numeric (CP API reference: order/status example
# ".../order/status/1234567890"; alertId documented as "int. Required").
_ORDER_ID_RE = re.compile(r"^\d+$")

# IBKR reply IDs are documented as "String. Required" with example value
# "a12b34c5-d678-9e012f-3456-7a890b12cd3e" — hex + hyphens, non-standard
# UUID grouping (not 8-4-4-4-12), so match on charset/length, not exact
# segment structure. Source: docs/superpowers/audit-evidence/scrapes/cpapi-v1.md
# (https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#place-order-reply)
_REPLY_ID_RE = re.compile(r"^[0-9a-fA-F-]{1,64}$")
```

Current lines 66-71 read:

```python
def _validate_account_id(account_id: str) -> None:
    """Raise ConfigError if account_id is not a valid IBKR account ID."""
    if not account_id or not _ACCOUNT_ID_RE.fullmatch(account_id):
        raise ConfigError(
            f"Invalid account_id {account_id!r}: must be 4–12 uppercase alphanumeric chars."
        )
```

Change to:

```python
def _validate_account_id(account_id: str) -> None:
    """Raise ConfigError if account_id is not a valid IBKR account ID."""
    if not account_id or not _ACCOUNT_ID_RE.fullmatch(account_id):
        raise ConfigError(
            f"Invalid account_id {account_id!r}: must be 4–12 uppercase alphanumeric chars."
        )


def _validate_order_id(order_id: str) -> None:
    """Raise ConfigError if order_id/alert_id is not a valid IBKR numeric ID.

    Prevents path traversal in URLs built by f-string interpolation — the same
    threat _validate_account_id addresses for account_id. Applies to order_id
    and alert_id (IBKR reuses the same numeric ID namespace for both — see
    docs/security-audit-2026-07-11.md H-2).
    """
    if not order_id or not _ORDER_ID_RE.fullmatch(order_id):
        raise ConfigError(f"Invalid order_id/alert_id {order_id!r}: must be numeric.")


def _validate_reply_id(reply_id: str) -> None:
    """Raise ConfigError if reply_id is not a plausible IBKR reply ID."""
    if not reply_id or not _REPLY_ID_RE.fullmatch(reply_id):
        raise ConfigError(f"Invalid reply_id {reply_id!r}: must be a hex/hyphen string.")
```

- [ ] **Step 4: Wire validation into each call site**

`get_order_status` (currently lines 777-784):

```python
    def get_order_status(self, order_id: str) -> dict[str, Any]:
        """Full order details for a specific order ID.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#order-status
        Endpoint: GET /iserver/account/order/status/{orderId}
        """
        _validate_order_id(order_id)
        self._ensure_accounts_initialized()
        return self._get(f"/iserver/account/order/status/{order_id}")
```

`modify_order` (currently lines 1113-1124) — add `_validate_order_id(order_id)` alongside the existing `_validate_account_id(account_id)`:

```python
    def modify_order(self, account_id: str, order_id: str, order: dict[str, Any]) -> dict[str, Any]:
        """Modify an existing order. Requires Touch ID (Gate 1) + tkinter dialog (Gate 2).

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#modify-order
                https://www.interactivebrokers.com/campus/trading-lessons/request-modify-orders/
        Endpoint: POST /iserver/account/{accountId}/order/{orderId}
        """
        _validate_account_id(account_id)
        _validate_order_id(order_id)
        self._ensure_accounts_initialized()
        require_touch_id(f"IBKR: Modify order {order_id}")
        confirm_modify_dialog(order_id, order, account_id)
        return self._post(f"/iserver/account/{account_id}/order/{order_id}", order)
```

`cancel_order` (currently lines 1126-1146) — add `_validate_order_id(order_id)`:

```python
    def cancel_order(
        self, account_id: str, order_id: str, order_details: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Cancel an order. Requires Touch ID (Gate 1) + tkinter confirmation dialog (Gate 2).

        `order_details` is optional display-only info (symbol/side/qty/price/TIF/etc.) shown
        in the Gate 2 dialog so the human can verify the right order before cancelling —
        mirrors modify_order()'s dialog, which already receives the full order dict. Found
        missing live 2026-07-10 — user-flagged hard requirement.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#cancel-order
                https://www.interactivebrokers.com/campus/trading-lessons/request-modify-orders/
        Endpoint: DELETE /iserver/account/{accountId}/order/{orderId}
        """
        _validate_account_id(account_id)
        _validate_order_id(order_id)
        self._ensure_accounts_initialized()
        require_touch_id(f"IBKR: Cancel order {order_id}")
        confirm_cancel_dialog(order_id, account_id, order_details)
        url = f"{self._base}/iserver/account/{account_id}/order/{order_id}"
        resp = with_retry(lambda: self._session.delete(url, timeout=30))
        return resp.json()
```

`reply_order` (currently lines 1148-1173) — add `_validate_reply_id(reply_id)`:

```python
    def reply_order(self, reply_id: str, ibkr_confirmed: bool = True) -> list[dict[str, Any]]:
        """Confirm an order requiring an explicit IBKR reply (e.g. after a warning).

        Requires Touch ID (Gate 1) + tkinter dialog (Gate 2).

        ## May need to be called in a loop (verified live 2026-07-06)
        This reply's own response can contain ANOTHER {"id", "message", ...} entry
        requiring a further reply_order() call — confirmed live, a single order
        needed 3 sequential replies before a terminal response. Callers must loop
        until the response has no "id"/"message" pair. Official docs: "Orders must
        be replied to immediately after receiving the reply message. Submitting
        other orders or other requests will cancel the order and attempts to
        acknowledge the reply will result in a 503 error" — so this loop must run
        back-to-back with no unrelated requests interleaved. `message` is the exact
        text IBKR wants the human to read before confirming; the caller (Gate 2
        dialog) must display it, not just the reply_id.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#place-order-reply
                https://www.interactivebrokers.com/campus/trading-lessons/request-modify-orders/
        Endpoint: POST /iserver/reply/{replyId}
        """
        _validate_reply_id(reply_id)
        self._ensure_accounts_initialized()
        require_touch_id(f"IBKR: Confirm order reply {reply_id}")
        confirm_reply_dialog(reply_id)
        data = self._post(f"/iserver/reply/{reply_id}", {"confirmed": ibkr_confirmed})
        return data if isinstance(data, list) else []
```

`get_alert` (currently lines 1280-1288):

```python
    def get_alert(self, alert_id: str) -> dict[str, Any]:
        """Full details for a specific alert by ID. Not account-scoped in the URL
        (same pattern as get_order_status) — IBKR resolves the alert from the
        session's logged-in account.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#get-alert
        Endpoint: GET /iserver/account/alert/{order_id}?type=Q
        """
        _validate_order_id(alert_id)
        return self._get(f"/iserver/account/alert/{alert_id}", params={"type": "Q"})
```

`delete_alert` (currently lines 1302-1311) — the exact H-2 exploit site:

```python
    def delete_alert(self, account_id: str, alert_id: str) -> dict[str, Any]:
        """Delete an alert permanently.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#delete-alert
        Endpoint: DELETE /iserver/account/{accountId}/alert/{alertId}
        """
        _validate_account_id(account_id)
        _validate_order_id(alert_id)
        url = f"{self._base}/iserver/account/{account_id}/alert/{alert_id}"
        resp = with_retry(lambda: self._session.delete(url, timeout=30))
        return resp.json()
```

`activate_alert` (currently lines 1313-1320) — `alert_id` goes into a JSON body, not a URL path, so it's not exploitable via path traversal, but validate for consistency (defense in depth, matches every other alert/order method):

```python
    def activate_alert(self, account_id: str, alert_id: str, activate: bool = True) -> dict[str, Any]:
        """Toggle alert on (activate=True) or off (activate=False) without deleting it.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#activate-alert
        Endpoint: POST /iserver/account/{accountId}/alert/activate
        """
        _validate_account_id(account_id)
        _validate_order_id(alert_id)
        return self._post(f"/iserver/account/{account_id}/alert/activate", {"alertId": alert_id, "alertActive": int(activate)})
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_client.py -v`
Expected: all tests pass, including the 7 new ones and all pre-existing ones.

- [ ] **Step 6: Update SECURITY.md's Confused Deputy Prevention section**

In `SECURITY.md`, the "Confused Deputy Prevention" section (around line 142-147) currently says:

```
- `account_id` values from LLM-generated tool input are validated with a strict regex before use in URLs or database queries, preventing path-manipulation attacks:

```python
_ACCOUNT_ID_RE = re.compile(r"^[A-Z0-9]{4,12}$")
# Blocks values like "../../iserver/auth/status", "../.env", etc.
```
```

Change to:

```
- `account_id`, `order_id`/`alert_id`, and `reply_id` values from LLM-generated tool input are validated with strict regexes before use in URLs, preventing path-manipulation attacks:

```python
_ACCOUNT_ID_RE = re.compile(r"^[A-Z0-9]{4,12}$")
_ORDER_ID_RE = re.compile(r"^\d+$")
_REPLY_ID_RE = re.compile(r"^[0-9a-fA-F-]{1,64}$")
# Blocks values like "../../iserver/auth/status", "../order/987654321", etc.
```

  (`order_id`/`alert_id` validation was added 2026-07-11 after an audit found `delete_alert(alert_id="../order/<id>")` could collapse to `cancel_order`'s URL — see `docs/security-audit-2026-07-11.md` H-2. `account_id` alone was not sufficient; every path-interpolated identifier needs the same treatment.)
```

- [ ] **Step 7: Run the full test suite**

Run: `pytest -m "not integration" -q`
Expected: all tests pass, no regressions.

- [ ] **Step 8: Commit**

```bash
git add ibkr_core_mcp/client.py tests/test_client.py SECURITY.md
git commit -m "$(cat <<'EOF'
security: validate order_id/alert_id/reply_id before URL construction

delete_alert(alert_id="../order/<id>") normalizes client-side (confirmed
against installed urllib3) to cancel_order's exact URL, bypassing Touch ID
and the confirmation dialog on live order cancellation. account_id already
had this protection (_ACCOUNT_ID_RE); order_id/alert_id/reply_id did not.

IBKR CP API reference confirms order_id/alert_id are numeric and reply_id
is a hex/hyphen string — see docs/superpowers/audit-evidence/scrapes/cpapi-v1.md.

See docs/security-audit-2026-07-11.md H-2.
EOF
)"
```

---

### Task 3: Bind gateway Docker container to loopback only (H-3, network exposure)

**Files:**
- Modify: `ibkr_core_mcp/gateway/manager.py:160`
- Test: `tests/test_gateway.py:162-176`
- Modify: `SECURITY.md` (Container Isolation Model section), `README.md:358`

- [ ] **Step 1: Write the failing test**

In `tests/test_gateway.py`, replace the existing `test_docker_run_includes_port_and_env_vars` (currently lines 162-176):

```python
    def test_docker_run_includes_port_and_env_vars(self) -> None:
        gm = GatewayManager(port=5055)
        with (
            patch.object(gm, "ensure_docker_running"),
            patch.object(gm, "container_exists", return_value=False),
            patch.object(gm, "image_exists", return_value=True),
            patch("subprocess.run") as mock_run,
        ):
            gm.start()
        args = mock_run.call_args.args[0]
        joined = " ".join(str(a) for a in args)
        assert "5055:5055" in joined
        assert "GATEWAY_PORT=5055" in joined
        assert "TICKLE_INTERVAL=60" in joined
```

with:

```python
    def test_docker_run_includes_port_and_env_vars(self) -> None:
        gm = GatewayManager(port=5055)
        with (
            patch.object(gm, "ensure_docker_running"),
            patch.object(gm, "container_exists", return_value=False),
            patch.object(gm, "image_exists", return_value=True),
            patch("subprocess.run") as mock_run,
        ):
            gm.start()
        args = mock_run.call_args.args[0]
        joined = " ".join(str(a) for a in args)
        assert "GATEWAY_PORT=5055" in joined
        assert "TICKLE_INTERVAL=60" in joined

    def test_docker_run_binds_port_to_loopback_only(self) -> None:
        """The gateway holds an authenticated IBKR session with no gate enforcement
        of its own — publishing beyond loopback makes it reachable from the LAN.
        See docs/security-audit-2026-07-11.md H-3."""
        gm = GatewayManager(port=5055)
        with (
            patch.object(gm, "ensure_docker_running"),
            patch.object(gm, "container_exists", return_value=False),
            patch.object(gm, "image_exists", return_value=True),
            patch("subprocess.run") as mock_run,
        ):
            gm.start()
        args = mock_run.call_args.args[0]
        assert "-p" in args
        p_value = args[args.index("-p") + 1]
        assert p_value == "127.0.0.1:5055:5055", (
            f"expected loopback-only publish, got {p_value!r}"
        )
```

- [ ] **Step 2: Run tests to verify the new one fails**

Run: `pytest tests/test_gateway.py -k "loopback" -v`
Expected: FAIL — `p_value` is `"5055:5055"`, not `"127.0.0.1:5055:5055"`.

- [ ] **Step 3: Fix the bind address**

In `ibkr_core_mcp/gateway/manager.py`, current code (around line 156-169):

```python
            subprocess.run(
                [
                    "docker", "run", "-d",
                    "--name", self.CONTAINER_NAME,
                    "-p", f"{self._port}:{self._port}",
                    # Pass env vars used by tickler.sh inside the container
                    "-e", f"GATEWAY_PORT={self._port}",
                    "-e", "TICKLE_INTERVAL=60",
                    "-e", f"TICKLE_BASE_URL=https://host.docker.internal:{self._port}/v1/api",
                    "-e", "TICKLE_ENDPOINT=/tickle",
                    self.IMAGE_NAME,
                ],
                check=True,
            )
```

Change the `-p` line to:

```python
            subprocess.run(
                [
                    "docker", "run", "-d",
                    "--name", self.CONTAINER_NAME,
                    "-p", f"127.0.0.1:{self._port}:{self._port}",
                    # Pass env vars used by tickler.sh inside the container
                    "-e", f"GATEWAY_PORT={self._port}",
                    "-e", "TICKLE_INTERVAL=60",
                    "-e", f"TICKLE_BASE_URL=https://host.docker.internal:{self._port}/v1/api",
                    "-e", "TICKLE_ENDPOINT=/tickle",
                    self.IMAGE_NAME,
                ],
                check=True,
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_gateway.py -v`
Expected: all tests pass.

- [ ] **Step 5: Correct `SECURITY.md`'s Container Isolation Model claim**

Current (around line 249):

```
The gateway container is started with `-p 5055:5055` — a single port binding to `localhost`. No host networking (`--network host`) is used, no host volumes are mounted, and no `--privileged` flag is passed. The gateway is unreachable from outside the machine.
```

Change to:

```
The gateway container is started with `-p 127.0.0.1:5055:5055` (fixed 2026-07-11 — the prior `-p 5055:5055` form, with no host-IP prefix, published the container on all host interfaces by Docker's default behavior, not loopback only; see `docs/security-audit-2026-07-11.md` H-3). No host networking (`--network host`) is used, no host volumes are mounted, and no `--privileged` flag is passed. The gateway is unreachable from outside the machine.
```

- [ ] **Step 6: Correct `README.md`'s equivalent claim**

`README.md:358` currently says the gateway runs "bound to `localhost:5055` only." Update it to match — search for the exact sentence in `README.md` around that line and confirm it still reads as originally quoted before editing (file may have shifted slightly); replace `localhost:5055 only` phrasing with `127.0.0.1:5055 only` if the port form is named explicitly, or leave the prose as-is if it already just says "localhost" generically without asserting the specific `-p` flag form (no code change needed if so — read the actual current line first, since this is a one-line, low-risk doc correction and the exact wording may not need to change if it's already accurate at the description level).

- [ ] **Step 7: Run the full test suite**

Run: `pytest -m "not integration" -q`
Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add ibkr_core_mcp/gateway/manager.py tests/test_gateway.py SECURITY.md README.md
git commit -m "$(cat <<'EOF'
security: bind gateway Docker container to loopback only

"-p {port}:{port}" (no host-IP prefix) publishes on all host interfaces by
Docker's default behavior, not localhost only as SECURITY.md/README.md
claimed — a network-adjacent device could reach the authenticated gateway
directly, bypassing Touch ID/dialog gates that only exist in this library's
Python call sites, not the gateway process itself.

See docs/security-audit-2026-07-11.md H-3.
EOF
)"
```

---

### Task 4: Dual-stack DNS resolution in the SSRF guard (H-4)

**Files:**
- Modify: `ibkr_core_mcp/scrape_fallback.py:91-110`
- Test: `tests/test_scrape_fallback.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_scrape_fallback.py`, add after `test_is_private_host_unresolvable_hostname_not_blocked` (ends at line 56):

```python
def test_is_private_host_blocks_aaaa_only_hostname_resolving_to_loopback(monkeypatch):
    """A hostname with no A record but an AAAA record pointing at ::1 must be
    blocked — socket.gethostbyname alone can't see AAAA records and used to
    fail open here. See docs/security-audit-2026-07-11.md H-4."""
    import socket

    from ibkr_core_mcp.scrape_fallback import is_private_host

    def _fake_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::1", 0, 0, 0))]

    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo)
    assert is_private_host("aaaa-only-evil.example") is True


def test_is_private_host_allows_aaaa_only_hostname_resolving_to_public_ipv6(monkeypatch):
    """A genuinely public IPv6-only hostname must still be allowed through."""
    import socket

    from ibkr_core_mcp.scrape_fallback import is_private_host

    def _fake_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2606:2800:220:1:248:1893:25c8:1946", 0, 0, 0))]

    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo)
    assert is_private_host("public-ipv6-only.example") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_scrape_fallback.py -k "aaaa" -v`
Expected: `test_is_private_host_blocks_aaaa_only_hostname_resolving_to_loopback` FAILS (current code calls `socket.gethostbyname`, not `getaddrinfo`, so the monkeypatch has no effect and the real `gethostbyname("aaaa-only-evil.example")` raises `gaierror` in the test sandbox, returning `False` — asserting `True` fails). The second test may pass or fail depending on environment DNS — that's expected and will be fixed by the same Step 3 change either way.

- [ ] **Step 3: Fix `is_private_host` to check all resolved addresses**

Current code (lines 91-110 of `ibkr_core_mcp/scrape_fallback.py`):

```python
    import ipaddress
    import socket

    # S104 false positive: "0.0.0.0" here is a *blocklist entry* in the SSRF
    # guard (rejecting requests to the all-interfaces address), not a bind.
    if host in ("localhost", "0.0.0.0") or host.startswith("127.") or host.startswith("169.254."):  # noqa: S104
        return True
    try:
        addr = ipaddress.ip_address(host)
        return addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved
    except ValueError:
        # Not a literal IP — resolve via DNS and re-check. Catches decimal
        # (2130706433) and hex (0x7f000001) encoded IPs as well as ordinary
        # hostnames that happen to resolve to a private address.
        try:
            resolved = socket.gethostbyname(host)
            addr = ipaddress.ip_address(resolved)
            return addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved
        except socket.gaierror:
            return False
```

Replace with:

```python
    import ipaddress
    import socket

    # S104 false positive: "0.0.0.0" here is a *blocklist entry* in the SSRF
    # guard (rejecting requests to the all-interfaces address), not a bind.
    if host in ("localhost", "0.0.0.0") or host.startswith("127.") or host.startswith("169.254."):  # noqa: S104
        return True
    try:
        addr = ipaddress.ip_address(host)
        return addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved
    except ValueError:
        # Not a literal IP — resolve via DNS and re-check. Catches decimal
        # (2130706433) and hex (0x7f000001) encoded IPs as well as ordinary
        # hostnames that happen to resolve to a private address.
        #
        # getaddrinfo (not gethostbyname) so AAAA-only hosts can't bypass this
        # by having no A record — gethostbyname is IPv4-only and used to treat
        # "unresolvable via IPv4" as "safe," which is wrong for a host that
        # resolves fine via IPv6. See docs/security-audit-2026-07-11.md H-4.
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror:
            return False
        for info in infos:
            sockaddr = info[4]
            ip_str = sockaddr[0]
            try:
                addr = ipaddress.ip_address(ip_str)
            except ValueError:
                continue
            if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
                return True
        return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_scrape_fallback.py -v`
Expected: all tests pass, including both new ones and all pre-existing `is_private_host`/`_reject_private_requests` tests (the pre-existing tests monkeypatch `socket.gethostbyname`, which is no longer called — confirm they still pass because `getaddrinfo` falls through to real DNS resolution for those test hostnames, OR update them to monkeypatch `getaddrinfo` instead if any fail; check actual output before deciding which).

If any pre-existing test in the file fails because it monkeypatches `socket.gethostbyname` (now unused), update that specific test to monkeypatch `socket.getaddrinfo` instead, returning the equivalent `(family, type, proto, canonname, sockaddr)` tuple shape used in the new tests above — do not delete or weaken the test's assertion, only change which socket function it mocks.

- [ ] **Step 5: Run the full test suite**

Run: `pytest -m "not integration" -q`
Expected: all tests pass, no regressions.

- [ ] **Step 6: Commit**

```bash
git add ibkr_core_mcp/scrape_fallback.py tests/test_scrape_fallback.py
git commit -m "$(cat <<'EOF'
security: resolve both A and AAAA records in the SSRF guard

is_private_host() used socket.gethostbyname, which is IPv4-only. An
AAAA-only hostname pointing at an internal IPv6 address (e.g. ::1) raised
gaierror and was treated as "unresolvable, therefore safe" — but Chromium's
actual fetch resolves dual-stack and would reach it anyway, bypassing both
SSRF layers that share this function. Switch to getaddrinfo and check every
returned address, not just the first IPv4 one.

See docs/security-audit-2026-07-11.md H-4.
EOF
)"
```

---

### Task 5: Scope gateway IP allowlist to actual RFC 1918 ranges (M-1)

**Files:**
- Modify: `ibkr_core_mcp/gateway/conf.yaml:24-29`
- Modify: `SECURITY.md` (conf.yaml Security Decisions table)

- [ ] **Step 1: Fix the allowlist**

Current (`ibkr_core_mcp/gateway/conf.yaml`, lines 22-29):

```yaml
ips:
  allow:
    - 127.*
    - 192.*
    - 131.216.*
    - 172.*
```

Replace with (bare-octet-glob syntax — this config format does not support CIDR, so the `172.16.0.0/12` RFC 1918 range must be enumerated as its 16 second-octet values):

```yaml
ips:
  allow:
    - 127.*
    - 192.168.*
    - 131.216.*
    - 172.16.*
    - 172.17.*
    - 172.18.*
    - 172.19.*
    - 172.20.*
    - 172.21.*
    - 172.22.*
    - 172.23.*
    - 172.24.*
    - 172.25.*
    - 172.26.*
    - 172.27.*
    - 172.28.*
    - 172.29.*
    - 172.30.*
    - 172.31.*
```

- [ ] **Step 2: Verify no test hardcodes the old allowlist shape**

Run: `grep -rn "ips.allow\|192\.\*\|172\.\*" tests/`
Expected: no matches (this file isn't parsed/asserted on by any current test — if the grep finds a match, read that test and update its expected list to match the new entries before proceeding).

- [ ] **Step 3: Correct `SECURITY.md`'s conf.yaml Security Decisions table**

Current row (around line 284):

```
| `ips.allow` | `127.*`, `192.*`, `172.*`, `131.216.*` | IBKR-required set: loopback + RFC 1918 private ranges + IBKR's own proxy infrastructure (`131.216.*`) needed for `proxyRemoteHost: api.ibkr.com` |
```

Change to:

```
| `ips.allow` | `127.*`, `192.168.*`, `172.16.*`–`172.31.*` (16 entries), `131.216.*` | Loopback + the *actual* RFC 1918 private ranges (fixed 2026-07-11 — `192.*`/`172.*` previously matched the full `192.0.0.0/8`/`172.0.0.0/8` blocks, 256×/16× broader than RFC 1918 and including public IPv4 space; see `docs/security-audit-2026-07-11.md` M-1) + IBKR's own proxy infrastructure (`131.216.*`) needed for `proxyRemoteHost: api.ibkr.com`. This allowlist is a compensating control, not the primary defense — see H-3's fix (Task 3) for why the container shouldn't be reachable beyond loopback in the first place. |
```

- [ ] **Step 4: Run the full test suite**

Run: `pytest -m "not integration" -q`
Expected: all tests pass (no code changes in this task, only config/docs — this step just confirms nothing else broke).

- [ ] **Step 5: Commit**

```bash
git add ibkr_core_mcp/gateway/conf.yaml SECURITY.md
git commit -m "$(cat <<'EOF'
security: scope gateway IP allowlist to actual RFC 1918 ranges

192.* and 172.* matched the full /8 blocks (256x and 16x broader than the
RFC 1918 192.168.0.0/16 and 172.16.0.0/12 ranges SECURITY.md claimed this
enforced), including public IPv4 space. Config format uses bare-octet
globs, not CIDR, so 172.16.0.0/12 is enumerated as its 16 second-octet
values.

See docs/security-audit-2026-07-11.md M-1.
EOF
)"
```

---

### Task 6: Fix `import_flex_file` path-boundary check (M-2)

**Files:**
- Modify: `ibkr_core_mcp/claude_tools.py:1368-1397`
- Test: `tests/claude_tools/test_flex.py`

- [ ] **Step 1: Write the failing test**

In `tests/claude_tools/test_flex.py`, add after `test_import_flex_file_blocked_path` (ends at line 266):

```python
def test_import_flex_file_blocks_sibling_prefixed_path(toolkit, tmp_path):
    """A prefix-string check (not a path-boundary check) incorrectly admits any
    directory whose name is a superstring of '.ibkr_core', e.g. '.ibkr_core_evil'.
    See docs/security-audit-2026-07-11.md M-2."""
    sibling = tmp_path / ".ibkr_core_evil"
    sibling.mkdir()
    xml_file = sibling / "archive.xml"
    xml_file.write_text("<FlexQueryResponse/>")

    with patch("pathlib.Path.home", return_value=tmp_path):
        text, fig = toolkit.execute("import_flex_file", {"path": str(xml_file)})
    assert fig is None
    assert "Blocked" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/claude_tools/test_flex.py -k "sibling_prefixed" -v`
Expected: FAIL — `str(resolved).startswith(str(allowed_root))` is `True` for this sibling path today (`.../​.ibkr_core_evil` starts with `.../​.ibkr_core`), so the file is read instead of blocked, and "Blocked" is not in `text`.

- [ ] **Step 3: Fix the boundary check**

Current code (`ibkr_core_mcp/claude_tools.py`, lines 1368-1389):

```python
    def _import_flex_file(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        """Import trades from a local Flex XML file into the SQLite store (idempotent).

        SECURITY: the path must resolve to a location under ~/.ibkr_core; anything
        else is blocked. This exists because the path arrives from the LLM and would
        otherwise allow prompt-injected reads of arbitrary local files. Returns a
        summary plus refreshed coverage, or a "Blocked:"/"File not found:" message.
        """
        from pathlib import Path

        from ibkr_core_mcp.flex_query import FlexQueryClient
        path = inputs["path"]
        # Path allowlist: only files under ~/.ibkr_core are permitted.
        # Prevents LLM prompt-injection from reading arbitrary local files.
        allowed_root = Path.home() / ".ibkr_core"
        resolved = Path(path).expanduser().resolve()
        if not str(resolved).startswith(str(allowed_root)):
            return f"Blocked: import path must be under {allowed_root}.", None
        if not resolved.exists():
            return f"File not found: {path}", None
        flex = FlexQueryClient(self._config, self._store, self._cache)
        trades = flex.import_from_file(path)
```

Replace with:

```python
    def _import_flex_file(self, inputs: dict[str, Any]) -> tuple[str, Any]:
        """Import trades from a local Flex XML file into the SQLite store (idempotent).

        SECURITY: the path must resolve to a location under ~/.ibkr_core; anything
        else is blocked. This exists because the path arrives from the LLM and would
        otherwise allow prompt-injected reads of arbitrary local files. Returns a
        summary plus refreshed coverage, or a "Blocked:"/"File not found:" message.
        """
        from pathlib import Path

        from ibkr_core_mcp.flex_query import FlexQueryClient
        path = inputs["path"]
        # Path allowlist: only files under ~/.ibkr_core are permitted.
        # Prevents LLM prompt-injection from reading arbitrary local files.
        # is_relative_to (not a string-prefix check) so a sibling directory whose
        # name is a superstring of ".ibkr_core" (e.g. ".ibkr_core_evil") can't
        # pass — see docs/security-audit-2026-07-11.md M-2.
        allowed_root = Path.home() / ".ibkr_core"
        resolved = Path(path).expanduser().resolve()
        if resolved != allowed_root and not resolved.is_relative_to(allowed_root):
            return f"Blocked: import path must be under {allowed_root}.", None
        if not resolved.exists():
            return f"File not found: {path}", None
        flex = FlexQueryClient(self._config, self._store, self._cache)
        trades = flex.import_from_file(str(resolved))
```

Note the last line: `flex.import_from_file(path)` → `flex.import_from_file(str(resolved))` — this passes the same validated, expanded/resolved path that was actually checked, not the raw caller-supplied string (which could differ, e.g. via `~` that was never expanded downstream).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/claude_tools/test_flex.py -v`
Expected: all tests pass, including the new one, `test_import_flex_file_happy_path` (still allows legitimate subdirectory files), and `test_import_flex_file_blocked_path` (still blocks unrelated paths like `/etc/passwd`).

- [ ] **Step 5: Run the full test suite**

Run: `pytest -m "not integration" -q`
Expected: all tests pass, no regressions.

- [ ] **Step 6: Commit**

```bash
git add ibkr_core_mcp/claude_tools.py tests/claude_tools/test_flex.py
git commit -m "$(cat <<'EOF'
security: fix path-boundary check in import_flex_file

str.startswith() on a resolved path string has no separator boundary, so
any sibling directory whose name is a superstring of ".ibkr_core" (e.g.
".ibkr_core_evil") incorrectly passed the allowlist. Use is_relative_to()
instead. Also pass the validated, resolved path to import_from_file()
rather than the raw unexpanded caller string.

See docs/security-audit-2026-07-11.md M-2.
EOF
)"
```

---

### Task 7: Close out the audit

**Files:**
- Modify: `docs/security-audit-2026-07-11.md` (Status line)
- Modify: `SECURITY.md` (Audit History table)

- [ ] **Step 1: Run the complete test suite one more time**

Run: `pytest -m "not integration" -q`
Expected: all tests pass. Also run `pytest tests/claude_tools/ -m "not integration" -q` to confirm the claude_tools subset specifically (per this repo's CLAUDE.md testing conventions) is green.

- [ ] **Step 2: Get the commit range for this branch**

Run: `git log --oneline main..HEAD`
Record the list of commit hashes/messages from Tasks 1–6 for the summary below.

- [ ] **Step 3: Update `docs/security-audit-2026-07-11.md`'s Status line**

Current line near the top of the file:

```
**Status:** 6 findings identified (4 High, 2 Medium). Fix plan: [`docs/plans/2026-07-11-security-fixes-plan.md`](plans/2026-07-11-security-fixes-plan.md). All findings must be fixed — none deferred.
```

Change to (fill in the actual short SHA range from Step 2 in place of `<first-sha>..<last-sha>`):

```
**Status:** All 6 findings resolved (4 High, 2 Medium). Fixes: `<first-sha>..<last-sha>` on branch `security-fixes-2026-07-11`, one commit per finding — see `docs/plans/2026-07-11-security-fixes-plan.md` for implementation detail on each.
```

- [ ] **Step 4: Add a row to `SECURITY.md`'s Audit History table**

Find the `## Audit History` table (around line 509-521). Add a new row immediately after the table's header/most-recent-entry row (matching the existing column format: Date | Commit | Scope | Findings):

```
| 2026-07-11 | `<first-sha>..<last-sha>` | Full codebase — 6-agent parallel audit + independent adversarial re-verification of every finding | 6 findings: 4 High, 2 Medium, all fixed. RCE via pandas eval/query in backtest sandbox; order_id/alert_id path traversal letting delete_alert collapse to cancel_order's URL (order-gate bypass); gateway Docker container published beyond loopback; SSRF guard IPv4-only DNS resolution (AAAA bypass); gateway IP allowlist broader than RFC 1918; import_flex_file path-prefix bypass. 1 candidate finding (Gate-2 dialog/order-dict TOCTOU) investigated and dropped — no reachable caller in this repo. |
```

Also update the "Full audit reports" line at the bottom of that section to include the new doc:

```
Full audit reports: [`docs/security-audit-2026-05-25.md`](docs/security-audit-2026-05-25.md) · [`docs/security-audit-2026-06-10.md`](docs/security-audit-2026-06-10.md) · [`docs/security-audit-2026-07-11.md`](docs/security-audit-2026-07-11.md)
```

- [ ] **Step 5: Commit**

```bash
git add docs/security-audit-2026-07-11.md SECURITY.md
git commit -m "$(cat <<'EOF'
docs: close out 2026-07-11 security audit — all 6 findings fixed

EOF
)"
```

---

## Self-Review Checklist (run before declaring the plan done)

- [ ] Every task's failing test actually fails for the stated reason before the fix (not for an unrelated typo/import error) — verify by reading the pytest failure output, not just the exit code.
- [ ] Every task's fix is the minimal change described — no drive-by refactors bundled in.
- [ ] `pytest -m "not integration" -q` is green after every single task, not just at the end.
- [ ] No task was skipped or downgraded to "documented residual" — all 6 findings have real code fixes, per the user's "all must be fixed" requirement.
- [ ] `git log --oneline main..HEAD` shows exactly 7 commits (Tasks 1–7), each scoped to one finding.
