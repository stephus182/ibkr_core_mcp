# Human Authentication — IBKR Order Security
**Date:** 2026-05-24  
**Status:** Approved  
**Scope:** `ibkr_core_mcp` — order write endpoints only

---

## Problem

All IBKR order write operations (`place_order`, `modify_order`, `cancel_order`, `reply_order`) are currently ungated. Any caller — including a compromised Claude tool, a bug, or malicious code — can send live orders to Interactive Brokers with no human in the loop. This is unacceptable for a system managing real financial positions.

## Security Requirement

**No order may be placed, modified, cancelled, or confirmed without explicit human validation on every operation.** There is no session cache, no bypass flag, no fallback. A failed or missing validation raises immediately and nothing reaches IBKR.

---

## Architecture

Two sequential gates are enforced inside `IBKRClient`, as the **first two lines** of each write method, before any network call:

```
Gate 1: Touch ID (biometric)     →  require_touch_id(reason)
Gate 2: Visual confirmation popup →  confirm_order_dialog(order, account_id)
         ↓ only if both pass
Gate 3: IBKR API call            →  self._post(...) / self._session.delete(...)
```

Failure at either gate raises `HumanAuthError` and the method returns immediately. The IBKR endpoint is never contacted.

---

## New Modules

### `human_auth.py`

Single responsibility: call Apple's `LocalAuthentication` framework and block until the result arrives.

```python
def require_touch_id(reason: str) -> None:
    """Block until Touch ID succeeds, or raise HumanAuthError."""
```

- Uses `pyobjc-framework-LocalAuthentication` (pip-installable macOS dependency)
- Policy: `LAPolicyDeviceOwnerAuthenticationWithBiometrics` — Touch ID only, no password fallback
- Synchronous via `threading.Event`; calling thread blocked until Apple callback fires
- Timeout: 60 seconds — raises `HumanAuthError("Touch ID timed out")`
- Touch ID unavailable (no hardware, not enrolled): raises `HumanAuthError("Touch ID unavailable: ...")`
- Touch ID denied: raises `HumanAuthError("Touch ID denied: ...")`

**No silent fallback exists.** If biometrics are unavailable, the call fails hard.

### `order_confirm.py`

Single responsibility: display a modal tkinter dialog with full order details and require an explicit mouse click on "SEND TO IBKR" before returning.

```python
def confirm_order_dialog(order: dict, account_id: str) -> None:
    """Show order confirmation dialog, or raise HumanAuthError if cancelled."""
```

Dialog properties:
- Always-on-top (`-topmost True`)
- Modal (`grab_set()`) — blocks all other app interaction
- **Enter key does not confirm** — mouse click on "SEND TO IBKR" required
- Cancel button (or window close) raises `HumanAuthError("Order cancelled by user")`
- Displays: Account, Action (BUY/SELL/SSHORT), Symbol, Quantity, Order Type, Price (if limit), TIF
- Prominent warning banner: *"This is a LIVE order. It will be sent to Interactive Brokers and may result in real financial transactions that cannot be undone."*

Dialog layout:
```
┌─────────────────────────────────────────────┐
│  ⚠  LIVE ORDER CONFIRMATION                 │
├─────────────────────────────────────────────┤
│  Account:     U1234567                      │
│  Action:      BUY                           │
│  Symbol:      AAPL                          │
│  Quantity:    100                           │
│  Order Type:  LIMIT                         │
│  Price:       $182.50                       │
│  TIF:         DAY                           │
├─────────────────────────────────────────────┤
│  ⚠ This is a LIVE order. It will be sent   │
│  to Interactive Brokers and may result in  │
│  real financial transactions that cannot   │
│  be undone.                                │
├─────────────────────────────────────────────┤
│      [ CANCEL ]        [ SEND TO IBKR ]    │
└─────────────────────────────────────────────┘
```

`modify_order` and `cancel_order` show tailored dialogs ("Modify order {order_id}" / "Cancel order {order_id}") with the same two-button confirmation pattern.

---

## Changes to Existing Files

### `exceptions.py`

Add one new exception:

```python
class HumanAuthError(IBKRCoreError):
    """Raised when Touch ID is denied, times out, or the user cancels the confirmation dialog."""
```

### `client.py`

Gate added to four write methods only:

| Method | Gate reason string |
|---|---|
| `place_order` | `"IBKR: Place order — {side} {qty} {symbol}"` |
| `modify_order` | `"IBKR: Modify order {order_id}"` |
| `cancel_order` | `"IBKR: Cancel order {order_id}"` |
| `reply_order` | `"IBKR: Confirm order reply {reply_id}"` |

**Explicitly ungated** (no execution risk):
- `get_order_preview` — IBKR `whatif` endpoint, read-only, no execution
- `create_alert`, `delete_alert`, `activate_alert` — price notifications, not order execution

### `pyproject.toml`

```toml
"pyobjc-framework-LocalAuthentication; sys_platform == 'darwin'",
```

Added to `[project.dependencies]`. macOS-only platform marker ensures the package installs cleanly on other platforms (though order write calls will fail if attempted there — correct behaviour, since IBKR gateway requires macOS same-machine auth anyway).

### `__init__.py`

Export `HumanAuthError` and `require_touch_id` as part of the public API surface.

---

## Tests

New test file: `tests/test_human_auth.py`

- Mock `LAContext` via `unittest.mock.patch`
- `test_require_touch_id_success` — callback fires `True`, no exception
- `test_require_touch_id_denied` — callback fires `False`, raises `HumanAuthError`
- `test_require_touch_id_unavailable` — `canEvaluatePolicy` returns `False`, raises `HumanAuthError`
- `test_require_touch_id_timeout` — `done.wait()` returns `False`, raises `HumanAuthError`

New test file: `tests/test_order_confirm.py`

- Mock `tkinter.Tk` and `tkinter.Toplevel`
- `test_confirm_dialog_yes` — simulate "SEND TO IBKR" click, no exception raised
- `test_confirm_dialog_cancel` — simulate "CANCEL" click, raises `HumanAuthError`
- `test_confirm_dialog_close` — simulate window close, raises `HumanAuthError`

Updated: `tests/test_client.py`

- Patch `require_touch_id` and `confirm_order_dialog` to verify they are called before the HTTP request for each gated method
- Verify ungated methods (`get_order_preview`, etc.) do NOT call `require_touch_id`

---

## CLAUDE.md Update

Add a prominent **Security** section at the top of CLAUDE.md covering:
- Human auth requirement for all order writes
- The two-gate architecture (Touch ID + dialog)
- Which endpoints are gated vs. ungated
- Constraint that this must never be bypassed

---

## Security Properties

| Property | Value |
|---|---|
| Auth mechanism | Apple Touch ID (`LAPolicyDeviceOwnerAuthenticationWithBiometrics`) |
| Password fallback | None — biometrics only |
| Session caching | None — per-operation, every call |
| Timeout | 60 seconds |
| Bypass flag | None |
| Silent fallback | None — unavailable hardware = hard fail |
| Network call on failure | Never |
| Enforcement layer | `IBKRClient` (innermost) — all callers blocked |
