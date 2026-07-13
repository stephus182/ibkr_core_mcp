# Human Auth — IBKR Order Security Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Gate all IBKR order write operations behind two sequential human checkpoints — Touch ID biometric auth followed by a visual confirmation dialog — enforced at `IBKRClient` level with no bypass path.

**Architecture:** `human_auth.py` owns the Touch ID call (pyobjc `LocalAuthentication`); `order_confirm.py` owns the tkinter modal dialog; `IBKRClient` calls both as its first two lines in each write method before any network call. `HumanAuthError` is raised on any failure at either gate — the IBKR endpoint is never contacted.

**Tech Stack:** `pyobjc-framework-LocalAuthentication` (Apple biometrics), `tkinter` (stdlib, modal dialog), `pytest` + `unittest.mock` (testing).

---

## File Map

| Action | File | Responsibility |
|---|---|---|
| Modify | `ibkr_core_mcp/exceptions.py` | Add `HumanAuthError` |
| Create | `ibkr_core_mcp/human_auth.py` | `require_touch_id(reason)` — pyobjc Touch ID gate |
| Create | `ibkr_core_mcp/order_confirm.py` | Modal dialog — 4 public functions + `_show_confirm_dialog` |
| Modify | `ibkr_core_mcp/client.py` | Add 2-gate call to `place_order`, `modify_order`, `cancel_order`, `reply_order` |
| Modify | `ibkr_core_mcp/__init__.py` | Export `HumanAuthError`, `require_touch_id` |
| Modify | `pyproject.toml` | Add `pyobjc-framework-LocalAuthentication; sys_platform == 'darwin'` |
| Modify | `CLAUDE.md` | Add Security section |
| Create | `tests/test_human_auth.py` | Unit tests for Touch ID module |
| Create | `tests/test_order_confirm.py` | Unit tests for confirmation dialog |
| Modify | `tests/test_client.py` | Tests verifying gates fire before HTTP calls |

---

## Task 1: Add `HumanAuthError` to exceptions and exports

**Files:**
- Modify: `ibkr_core_mcp/exceptions.py`
- Modify: `ibkr_core_mcp/__init__.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_human_auth.py` with just the exception test for now:

```python
# tests/test_human_auth.py
from ibkr_core_mcp.exceptions import IBKRCoreError, HumanAuthError


def test_human_auth_error_is_ibkr_core_error():
    err = HumanAuthError("denied")
    assert isinstance(err, IBKRCoreError)
    assert str(err) == "denied"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/python -m pytest tests/test_human_auth.py::test_human_auth_error_is_ibkr_core_error -v
```

Expected: `FAILED` — `ImportError: cannot import name 'HumanAuthError'`

- [ ] **Step 3: Add `HumanAuthError` to `exceptions.py`**

Open `ibkr_core_mcp/exceptions.py` and append after `ConfigError`:

```python
class HumanAuthError(IBKRCoreError):
    """Raised when Touch ID is denied, times out, unavailable, or the user cancels the confirmation dialog."""
```

- [ ] **Step 4: Export in `__init__.py`**

In `ibkr_core_mcp/__init__.py`, add `HumanAuthError` to the exceptions import block:

```python
from ibkr_core_mcp.exceptions import (
    IBKRCoreError,
    IBKRAuthError,
    IBKRRateLimitError,
    IBKRAPIError,
    CacheError,
    CacheMissError,
    CacheWriteError,
    StoreError,
    BacktestError,
    BacktestSyntaxError,
    BacktestRuntimeError,
    ConfigError,
    HumanAuthError,
)
```

- [ ] **Step 5: Run test to verify it passes**

```bash
.venv/bin/python -m pytest tests/test_human_auth.py::test_human_auth_error_is_ibkr_core_error -v
```

Expected: `PASSED`

- [ ] **Step 6: Commit**

```bash
git add ibkr_core_mcp/exceptions.py ibkr_core_mcp/__init__.py tests/test_human_auth.py
git commit -m "feat: HumanAuthError — base exception for order auth gates"
```

---

## Task 2: `human_auth.py` — Touch ID module

**Files:**
- Create: `ibkr_core_mcp/human_auth.py`
- Modify: `tests/test_human_auth.py`
- Modify: `ibkr_core_mcp/__init__.py`

- [ ] **Step 1: Write all failing tests**

Add to `tests/test_human_auth.py`:

```python
import sys
import threading
from unittest.mock import MagicMock, patch
import pytest
from ibkr_core_mcp.exceptions import HumanAuthError


def _make_la_mock(can_eval=True, eval_err=None, reply_success=True, reply_error=None):
    """Build a LocalAuthentication sys.modules mock."""
    mock_ctx = MagicMock()
    mock_ctx.canEvaluatePolicy_error_.return_value = (can_eval, eval_err)

    def fake_evaluate(policy, reason, reply):
        reply(reply_success, reply_error)

    mock_ctx.evaluatePolicy_localizedReason_reply_.side_effect = fake_evaluate
    mock_la = MagicMock()
    mock_la.LAContext.new.return_value = mock_ctx
    mock_la.LAPolicyDeviceOwnerAuthenticationWithBiometrics = 2
    return mock_la


def test_require_touch_id_success(monkeypatch):
    mock_la = _make_la_mock(can_eval=True, reply_success=True)
    monkeypatch.setitem(sys.modules, "LocalAuthentication", mock_la)
    from ibkr_core_mcp.human_auth import require_touch_id
    require_touch_id("Test order")  # must not raise


def test_require_touch_id_denied(monkeypatch):
    mock_la = _make_la_mock(can_eval=True, reply_success=False, reply_error="User cancelled")
    monkeypatch.setitem(sys.modules, "LocalAuthentication", mock_la)
    from ibkr_core_mcp.human_auth import require_touch_id
    with pytest.raises(HumanAuthError, match="Touch ID denied"):
        require_touch_id("Test order")


def test_require_touch_id_unavailable(monkeypatch):
    mock_la = _make_la_mock(can_eval=False, eval_err="No enrolled fingers")
    monkeypatch.setitem(sys.modules, "LocalAuthentication", mock_la)
    from ibkr_core_mcp.human_auth import require_touch_id
    with pytest.raises(HumanAuthError, match="Touch ID unavailable"):
        require_touch_id("Test order")


def test_require_touch_id_not_installed(monkeypatch):
    monkeypatch.setitem(sys.modules, "LocalAuthentication", None)
    from ibkr_core_mcp.human_auth import require_touch_id
    with pytest.raises(HumanAuthError, match="not installed"):
        require_touch_id("Test order")


def test_require_touch_id_timeout(monkeypatch):
    mock_ctx = MagicMock()
    mock_ctx.canEvaluatePolicy_error_.return_value = (True, None)
    # evaluatePolicy never calls reply — simulates timeout
    mock_ctx.evaluatePolicy_localizedReason_reply_.side_effect = lambda p, r, cb: None
    mock_la = MagicMock()
    mock_la.LAContext.new.return_value = mock_ctx
    mock_la.LAPolicyDeviceOwnerAuthenticationWithBiometrics = 2
    monkeypatch.setitem(sys.modules, "LocalAuthentication", mock_la)

    from ibkr_core_mcp.human_auth import require_touch_id
    # Patch threading.Event.wait to return False immediately (simulates timeout)
    with patch("ibkr_core_mcp.human_auth.threading.Event") as mock_event_cls:
        mock_event = MagicMock()
        mock_event.wait.return_value = False
        mock_event_cls.return_value = mock_event
        with pytest.raises(HumanAuthError, match="timed out"):
            require_touch_id("Test order")
```

- [ ] **Step 2: Run tests to verify they all fail**

```bash
.venv/bin/python -m pytest tests/test_human_auth.py -v --ignore-glob="*test_human_auth_error*"
```

Expected: all `FAILED` — `ModuleNotFoundError: No module named 'ibkr_core_mcp.human_auth'`

- [ ] **Step 3: Create `ibkr_core_mcp/human_auth.py`**

```python
from __future__ import annotations
import threading
from ibkr_core_mcp.exceptions import HumanAuthError

_TIMEOUT = 60


def require_touch_id(reason: str) -> None:
    """Block until Touch ID succeeds. Raises HumanAuthError on any failure."""
    try:
        from LocalAuthentication import (  # type: ignore[import]
            LAContext,
            LAPolicyDeviceOwnerAuthenticationWithBiometrics,
        )
    except (ImportError, TypeError):
        raise HumanAuthError(
            "Touch ID unavailable: pyobjc-framework-LocalAuthentication not installed"
        )

    ctx = LAContext.new()
    can_eval, err = ctx.canEvaluatePolicy_error_(
        LAPolicyDeviceOwnerAuthenticationWithBiometrics, None
    )
    if not can_eval:
        raise HumanAuthError(f"Touch ID unavailable: {err}")

    done = threading.Event()
    result: dict = {}

    def _reply(success: bool, error: object) -> None:
        result["ok"] = success
        result["error"] = error
        done.set()

    ctx.evaluatePolicy_localizedReason_reply_(
        LAPolicyDeviceOwnerAuthenticationWithBiometrics, reason, _reply
    )

    if not done.wait(timeout=_TIMEOUT):
        raise HumanAuthError(f"Touch ID timed out after {_TIMEOUT}s")
    if not result.get("ok"):
        raise HumanAuthError(f"Touch ID denied: {result.get('error')}")
```

- [ ] **Step 4: Run tests to verify they all pass**

```bash
.venv/bin/python -m pytest tests/test_human_auth.py -v
```

Expected: all `PASSED`

- [ ] **Step 5: Export `require_touch_id` in `__init__.py`**

Add after the exceptions import block in `ibkr_core_mcp/__init__.py`:

```python
from ibkr_core_mcp.human_auth import require_touch_id
```

- [ ] **Step 6: Commit**

```bash
git add ibkr_core_mcp/human_auth.py ibkr_core_mcp/__init__.py tests/test_human_auth.py
git commit -m "feat: human_auth — Touch ID gate via pyobjc LocalAuthentication"
```

---

## Task 3: `order_confirm.py` — Modal confirmation dialog

**Files:**
- Create: `ibkr_core_mcp/order_confirm.py`
- Create: `tests/test_order_confirm.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_order_confirm.py`:

```python
from unittest.mock import MagicMock, patch, call
import pytest
from ibkr_core_mcp.exceptions import HumanAuthError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tk_mock(click_label: str | None):
    """
    Build a patched tkinter mock that simulates a button click inside mainloop.
    click_label=None simulates window-close (protocol WM_DELETE_WINDOW fires).
    """
    captured = {"commands": {}, "close_cmd": None}

    def fake_button(parent, **kwargs):
        text = kwargs.get("text", "")
        cmd = kwargs.get("command")
        if cmd:
            captured["commands"][text] = cmd
        return MagicMock()

    mock_root = MagicMock()
    mock_dialog = MagicMock()

    def fake_protocol(event, cmd):
        if event == "WM_DELETE_WINDOW":
            captured["close_cmd"] = cmd

    mock_dialog.protocol.side_effect = fake_protocol

    def fake_mainloop():
        if click_label is None:
            if captured["close_cmd"]:
                captured["close_cmd"]()
        elif click_label in captured["commands"]:
            captured["commands"][click_label]()

    mock_root.mainloop.side_effect = fake_mainloop

    mock_tk = MagicMock()
    mock_tk.Tk.return_value = mock_root
    mock_tk.Toplevel.return_value = mock_dialog
    mock_tk.Frame.return_value = MagicMock()
    mock_tk.Label.return_value = MagicMock()
    mock_tk.Button.side_effect = fake_button
    return mock_tk


# ---------------------------------------------------------------------------
# _show_confirm_dialog
# ---------------------------------------------------------------------------

def test_show_confirm_dialog_confirm_does_not_raise():
    mock_tk = _make_tk_mock("SEND TO IBKR")
    with patch("ibkr_core_mcp.order_confirm.tk", mock_tk):
        from ibkr_core_mcp.order_confirm import _show_confirm_dialog
        _show_confirm_dialog(
            title="Test",
            details={"Symbol": "AAPL"},
            disclaimer="Live order warning",
            confirm_label="SEND TO IBKR",
        )  # must not raise


def test_show_confirm_dialog_cancel_raises():
    mock_tk = _make_tk_mock("CANCEL")
    with patch("ibkr_core_mcp.order_confirm.tk", mock_tk):
        from ibkr_core_mcp.order_confirm import _show_confirm_dialog
        with pytest.raises(HumanAuthError, match="cancelled by user"):
            _show_confirm_dialog(
                title="Test",
                details={"Symbol": "AAPL"},
                disclaimer="Live order warning",
                confirm_label="SEND TO IBKR",
            )


def test_show_confirm_dialog_window_close_raises():
    mock_tk = _make_tk_mock(None)  # None → close protocol fires
    with patch("ibkr_core_mcp.order_confirm.tk", mock_tk):
        from ibkr_core_mcp.order_confirm import _show_confirm_dialog
        with pytest.raises(HumanAuthError, match="cancelled by user"):
            _show_confirm_dialog(
                title="Test",
                details={"Symbol": "AAPL"},
                disclaimer="Live order warning",
                confirm_label="SEND TO IBKR",
            )


# ---------------------------------------------------------------------------
# Public helpers — verify they call _show_confirm_dialog with right args
# ---------------------------------------------------------------------------

def test_confirm_order_dialog_passes_correct_fields():
    order = {"ticker": "AAPL", "side": "BUY", "quantity": 100,
              "orderType": "LIMIT", "price": 182.50, "tif": "DAY"}
    with patch("ibkr_core_mcp.order_confirm._show_confirm_dialog") as mock_show:
        from ibkr_core_mcp.order_confirm import confirm_order_dialog
        confirm_order_dialog(order, "U1234567")
    mock_show.assert_called_once()
    kwargs = mock_show.call_args.kwargs
    assert kwargs["details"]["Account"] == "U1234567"
    assert kwargs["details"]["Symbol"] == "AAPL"
    assert kwargs["details"]["Action"] == "BUY"
    assert kwargs["confirm_label"] == "SEND TO IBKR"


def test_confirm_modify_dialog_passes_order_id():
    with patch("ibkr_core_mcp.order_confirm._show_confirm_dialog") as mock_show:
        from ibkr_core_mcp.order_confirm import confirm_modify_dialog
        confirm_modify_dialog("ORD123", {"side": "SELL"}, "U1234567")
    kwargs = mock_show.call_args.kwargs
    assert kwargs["details"]["Order ID"] == "ORD123"
    assert "MODIFY" in kwargs["confirm_label"]


def test_confirm_cancel_dialog_passes_order_id():
    with patch("ibkr_core_mcp.order_confirm._show_confirm_dialog") as mock_show:
        from ibkr_core_mcp.order_confirm import confirm_cancel_dialog
        confirm_cancel_dialog("ORD456", "U1234567")
    kwargs = mock_show.call_args.kwargs
    assert kwargs["details"]["Order ID"] == "ORD456"
    assert "CANCEL" in kwargs["confirm_label"]


def test_confirm_reply_dialog_passes_reply_id():
    with patch("ibkr_core_mcp.order_confirm._show_confirm_dialog") as mock_show:
        from ibkr_core_mcp.order_confirm import confirm_reply_dialog
        confirm_reply_dialog("RPL789")
    kwargs = mock_show.call_args.kwargs
    assert kwargs["details"]["Reply ID"] == "RPL789"
    assert "CONFIRM" in kwargs["confirm_label"]
```

- [ ] **Step 2: Run tests to verify they all fail**

```bash
.venv/bin/python -m pytest tests/test_order_confirm.py -v
```

Expected: all `FAILED` — `ModuleNotFoundError: No module named 'ibkr_core_mcp.order_confirm'`

- [ ] **Step 3: Create `ibkr_core_mcp/order_confirm.py`**

```python
from __future__ import annotations
import tkinter as tk
from ibkr_core_mcp.exceptions import HumanAuthError


def confirm_order_dialog(order: dict, account_id: str) -> None:
    """Gate 2 for place_order. Raises HumanAuthError if user does not confirm."""
    symbol = order.get("ticker", order.get("symbol", "UNKNOWN"))
    side = order.get("side", "?")
    qty = order.get("quantity", "?")
    order_type = order.get("orderType", order.get("order_type", "MARKET"))
    price = order.get("price", None)
    tif = order.get("tif", order.get("timeInForce", "DAY"))
    price_str = f"${price}" if price is not None else "MARKET"
    _show_confirm_dialog(
        title="⚠  LIVE ORDER CONFIRMATION",
        details={
            "Account": account_id,
            "Action": side,
            "Symbol": symbol,
            "Quantity": str(qty),
            "Order Type": order_type,
            "Price": price_str,
            "TIF": tif,
        },
        disclaimer=(
            "This is a LIVE order. It will be sent to Interactive Brokers "
            "and may result in real financial transactions that cannot be undone."
        ),
        confirm_label="SEND TO IBKR",
    )


def confirm_modify_dialog(order_id: str, order: dict, account_id: str) -> None:
    """Gate 2 for modify_order."""
    _show_confirm_dialog(
        title="⚠  MODIFY ORDER CONFIRMATION",
        details={"Order ID": order_id, "Account": account_id,
                 **{k: str(v) for k, v in order.items()}},
        disclaimer="This will MODIFY a live order at Interactive Brokers.",
        confirm_label="MODIFY ORDER",
    )


def confirm_cancel_dialog(order_id: str, account_id: str) -> None:
    """Gate 2 for cancel_order."""
    _show_confirm_dialog(
        title="⚠  CANCEL ORDER CONFIRMATION",
        details={"Order ID": order_id, "Account": account_id},
        disclaimer="This will CANCEL a live order at Interactive Brokers.",
        confirm_label="CANCEL ORDER",
    )


def confirm_reply_dialog(reply_id: str) -> None:
    """Gate 2 for reply_order."""
    _show_confirm_dialog(
        title="⚠  CONFIRM ORDER REPLY",
        details={"Reply ID": reply_id},
        disclaimer="This will CONFIRM a pending order at Interactive Brokers.",
        confirm_label="CONFIRM REPLY",
    )


def _show_confirm_dialog(
    title: str, details: dict, disclaimer: str, confirm_label: str
) -> None:
    """Render modal dialog. Raises HumanAuthError if user cancels or closes."""
    confirmed: dict = {"value": False}

    root = tk.Tk()
    root.withdraw()

    dialog = tk.Toplevel(root)
    dialog.title(title)
    dialog.attributes("-topmost", True)
    dialog.resizable(False, False)
    dialog.grab_set()

    # --- Title bar ---
    title_frame = tk.Frame(dialog, bg="#c0392b", pady=8)
    title_frame.pack(fill="x")
    tk.Label(
        title_frame, text=title, bg="#c0392b", fg="white",
        font=("Helvetica", 13, "bold"),
    ).pack()

    # --- Order details ---
    detail_frame = tk.Frame(dialog, padx=20, pady=10)
    detail_frame.pack(fill="x")
    for i, (key, val) in enumerate(details.items()):
        tk.Label(detail_frame, text=f"{key}:", font=("Helvetica", 11, "bold"),
                 anchor="w").grid(row=i, column=0, sticky="w", pady=2)
        tk.Label(detail_frame, text=str(val), font=("Helvetica", 11),
                 anchor="w").grid(row=i, column=1, sticky="w", padx=(10, 0), pady=2)

    # --- Disclaimer ---
    disc_frame = tk.Frame(dialog, bg="#ffeaa7", padx=15, pady=10)
    disc_frame.pack(fill="x", padx=10, pady=5)
    tk.Label(
        disc_frame, text=disclaimer, bg="#ffeaa7", wraplength=340,
        font=("Helvetica", 10), justify="left",
    ).pack()

    # --- Buttons ---
    btn_frame = tk.Frame(dialog, pady=10)
    btn_frame.pack()

    def on_cancel() -> None:
        confirmed["value"] = False
        dialog.destroy()
        root.destroy()

    def on_confirm() -> None:
        confirmed["value"] = True
        dialog.destroy()
        root.destroy()

    tk.Button(btn_frame, text="CANCEL", command=on_cancel, width=12,
              bg="#bdc3c7", font=("Helvetica", 11)).pack(side="left", padx=10)
    tk.Button(btn_frame, text=confirm_label, command=on_confirm, width=18,
              bg="#e74c3c", fg="white", font=("Helvetica", 11, "bold")).pack(side="left", padx=10)

    dialog.protocol("WM_DELETE_WINDOW", on_cancel)

    dialog.update_idletasks()
    w = dialog.winfo_width()
    h = dialog.winfo_height()
    x = (dialog.winfo_screenwidth() - w) // 2
    y = (dialog.winfo_screenheight() - h) // 2
    dialog.geometry(f"+{x}+{y}")

    root.mainloop()

    if not confirmed["value"]:
        raise HumanAuthError("Order cancelled by user")
```

- [ ] **Step 4: Run tests to verify they all pass**

```bash
.venv/bin/python -m pytest tests/test_order_confirm.py -v
```

Expected: all `PASSED`

- [ ] **Step 5: Commit**

```bash
git add ibkr_core_mcp/order_confirm.py tests/test_order_confirm.py
git commit -m "feat: order_confirm — tkinter modal dialog for live order confirmation"
```

---

## Task 4: Gate order write methods in `client.py`

**Files:**
- Modify: `ibkr_core_mcp/client.py`
- Modify: `tests/test_client.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_client.py`:

```python
from unittest.mock import patch as _patch


# ---------------------------------------------------------------------------
# Order gate tests
# ---------------------------------------------------------------------------

def _make_ok_response(payload=None):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = payload or {}
    return mock_resp


def test_place_order_calls_touch_id_before_post(client):
    order = {"ticker": "AAPL", "side": "BUY", "quantity": 100, "orderType": "LIMIT", "price": 182.5}
    call_order = []
    with _patch("ibkr_core_mcp.client.require_touch_id", side_effect=lambda r: call_order.append("touch_id")) as mock_tid, \
         _patch("ibkr_core_mcp.client.confirm_order_dialog", side_effect=lambda o, a: call_order.append("dialog")) as mock_dlg, \
         _patch.object(client._session, "post") as mock_post:
        mock_post.return_value = _make_ok_response([{"orderId": "1"}])
        client.place_order("U1234567", order)
    assert call_order == ["touch_id", "dialog"]
    mock_tid.assert_called_once()
    mock_dlg.assert_called_once()
    mock_post.assert_called_once()


def test_place_order_aborts_if_touch_id_fails(client):
    from ibkr_core_mcp.exceptions import HumanAuthError
    order = {"ticker": "AAPL", "side": "BUY", "quantity": 100}
    with _patch("ibkr_core_mcp.client.require_touch_id", side_effect=HumanAuthError("denied")), \
         _patch.object(client._session, "post") as mock_post:
        with pytest.raises(HumanAuthError):
            client.place_order("U1234567", order)
    mock_post.assert_not_called()


def test_place_order_aborts_if_dialog_cancelled(client):
    from ibkr_core_mcp.exceptions import HumanAuthError
    order = {"ticker": "AAPL", "side": "BUY", "quantity": 100}
    with _patch("ibkr_core_mcp.client.require_touch_id"), \
         _patch("ibkr_core_mcp.client.confirm_order_dialog", side_effect=HumanAuthError("cancelled")), \
         _patch.object(client._session, "post") as mock_post:
        with pytest.raises(HumanAuthError):
            client.place_order("U1234567", order)
    mock_post.assert_not_called()


def test_modify_order_calls_both_gates(client):
    with _patch("ibkr_core_mcp.client.require_touch_id") as mock_tid, \
         _patch("ibkr_core_mcp.client.confirm_modify_dialog") as mock_dlg, \
         _patch.object(client._session, "post") as mock_post:
        mock_post.return_value = _make_ok_response({"status": "modified"})
        client.modify_order("U1234567", "ORD123", {"side": "SELL"})
    mock_tid.assert_called_once()
    mock_dlg.assert_called_once()
    mock_post.assert_called_once()


def test_cancel_order_calls_both_gates(client):
    with _patch("ibkr_core_mcp.client.require_touch_id") as mock_tid, \
         _patch("ibkr_core_mcp.client.confirm_cancel_dialog") as mock_dlg, \
         _patch.object(client._session, "delete") as mock_del:
        mock_del.return_value = _make_ok_response({"status": "cancelled"})
        client.cancel_order("U1234567", "ORD456")
    mock_tid.assert_called_once()
    mock_dlg.assert_called_once()
    mock_del.assert_called_once()


def test_reply_order_calls_both_gates(client):
    with _patch("ibkr_core_mcp.client.require_touch_id") as mock_tid, \
         _patch("ibkr_core_mcp.client.confirm_reply_dialog") as mock_dlg, \
         _patch.object(client._session, "post") as mock_post:
        mock_post.return_value = _make_ok_response([{"status": "submitted"}])
        client.reply_order("RPL789")
    mock_tid.assert_called_once()
    mock_dlg.assert_called_once()
    mock_post.assert_called_once()


def test_get_order_preview_has_no_gate(client):
    """whatif endpoint is read-only — must NOT trigger Touch ID."""
    order = {"ticker": "AAPL", "side": "BUY", "quantity": 100}
    with _patch("ibkr_core_mcp.client.require_touch_id") as mock_tid, \
         _patch.object(client._session, "post") as mock_post:
        mock_post.return_value = _make_ok_response({"equity": 5000})
        client.get_order_preview("U1234567", order)
    mock_tid.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they all fail**

```bash
.venv/bin/python -m pytest tests/test_client.py -k "order" -v
```

Expected: all `FAILED` — `AssertionError: require_touch_id not called` (gates not wired yet)

- [ ] **Step 3: Update imports in `client.py`**

At the top of `ibkr_core_mcp/client.py`, add after existing imports:

```python
from ibkr_core_mcp.human_auth import require_touch_id
from ibkr_core_mcp.order_confirm import (
    confirm_order_dialog,
    confirm_modify_dialog,
    confirm_cancel_dialog,
    confirm_reply_dialog,
)
```

- [ ] **Step 4: Gate the four write methods in `client.py`**

Replace the four methods (currently around lines 271–290) with:

```python
    # Order Management (write — human auth required)
    def place_order(self, account_id: str, order: dict) -> list[dict]:
        symbol = order.get("ticker", order.get("symbol", "UNKNOWN"))
        side = order.get("side", "?")
        qty = order.get("quantity", "?")
        require_touch_id(f"IBKR: Place order — {side} {qty} {symbol}")
        confirm_order_dialog(order, account_id)
        data = self._post(f"/iserver/account/{account_id}/orders", {"orders": [order]})
        return data if isinstance(data, list) else []

    def modify_order(self, account_id: str, order_id: str, order: dict) -> dict:
        require_touch_id(f"IBKR: Modify order {order_id}")
        confirm_modify_dialog(order_id, order, account_id)
        return self._post(f"/iserver/account/{account_id}/order/{order_id}", order)

    def cancel_order(self, account_id: str, order_id: str) -> dict:
        require_touch_id(f"IBKR: Cancel order {order_id}")
        confirm_cancel_dialog(order_id, account_id)
        url = f"{self._base}/iserver/account/{account_id}/order/{order_id}"
        resp = with_retry(lambda: self._session.delete(url, timeout=30))
        return resp.json()

    def reply_order(self, reply_id: str, confirmed: bool = True) -> list[dict]:
        require_touch_id(f"IBKR: Confirm order reply {reply_id}")
        confirm_reply_dialog(reply_id)
        data = self._post(f"/iserver/reply/{reply_id}", {"confirmed": confirmed})
        return data if isinstance(data, list) else []
```

- [ ] **Step 5: Run all order tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/test_client.py -k "order" -v
```

Expected: all `PASSED`

- [ ] **Step 6: Run full test suite to check for regressions**

```bash
.venv/bin/python -m pytest -m "not integration" -q
```

Expected: all tests pass, no regressions

- [ ] **Step 7: Commit**

```bash
git add ibkr_core_mcp/client.py tests/test_client.py
git commit -m "feat: client — Touch ID + confirmation dialog gate on all order write methods"
```

---

## Task 5: Add pyobjc dependency to `pyproject.toml`

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add the macOS-gated dependency**

In `pyproject.toml`, add to the `dependencies` list:

```toml
"pyobjc-framework-LocalAuthentication; sys_platform == 'darwin'",
```

The full dependencies block becomes:

```toml
dependencies = [
    "requests>=2.31",
    "urllib3>=2.0",
    "pydantic>=2.0",
    "anthropic>=0.28",
    "pandas>=2.2",
    "numpy>=1.26",
    "plotly>=5.22",
    "RestrictedPython>=7.0",
    "pyarrow>=16.0",
    "google-api-python-client>=2.130",
    "google-auth-httplib2>=0.2",
    "google-auth-oauthlib>=1.2",
    "python-dotenv>=1.0",
    "browser-cookie3>=0.19",
    "pyobjc-framework-LocalAuthentication; sys_platform == 'darwin'",
]
```

- [ ] **Step 2: Reinstall and verify import**

```bash
.venv/bin/pip install -e ".[dev]" --quiet
.venv/bin/python -c "from LocalAuthentication import LAContext; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "build: add pyobjc-framework-LocalAuthentication for macOS Touch ID"
```

---

## Task 6: Update `CLAUDE.md` with security section

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add the security section**

Insert the following block immediately after the first `---` separator in `CLAUDE.md` (after the one-line description, before `## Install`):

```markdown
---

## Security — Order Write Protection

**ALL order write operations require two sequential human validations. There is no bypass.**

### Two-gate architecture

Every call to `place_order`, `modify_order`, `cancel_order`, or `reply_order` on `IBKRClient` must pass both gates — in order — before any network call is made:

1. **Gate 1 — Touch ID** (`human_auth.require_touch_id`): Apple biometric auth via `LocalAuthentication`. Policy: `LAPolicyDeviceOwnerAuthenticationWithBiometrics` — Touch ID only, no password fallback. 60-second timeout.
2. **Gate 2 — Visual confirmation** (`order_confirm`): tkinter modal dialog showing full order details and a live-order disclaimer. Requires explicit mouse click on the action button. Enter key does not confirm.

If either gate fails (denied, timeout, cancelled), `HumanAuthError` is raised immediately and the IBKR endpoint is never contacted.

### Gated endpoints

| Method | Gate |
|---|---|
| `place_order` | Touch ID + confirm dialog |
| `modify_order` | Touch ID + modify dialog |
| `cancel_order` | Touch ID + cancel dialog |
| `reply_order` | Touch ID + reply dialog |

### Explicitly ungated

| Method | Reason |
|---|---|
| `get_order_preview` | IBKR `whatif` — read-only, no execution |
| `create_alert` / `delete_alert` / `activate_alert` | Price notifications, not order execution |

### Rules for contributors

- **Never add a bypass flag, session cache, or fallback** to `require_touch_id` or any dialog function.
- **Never move the gates** out of `IBKRClient` into a higher layer — enforcement must be at the innermost call site.
- **Never add password/PIN fallback** — `LAPolicyDeviceOwnerAuthenticationWithBiometrics` is the required policy.
- Any PR that weakens these gates will be rejected.

```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: CLAUDE.md — add order security section with two-gate architecture"
```

---

## Task 7: Full test suite + version bump + tag

**Files:**
- Modify: `ibkr_core_mcp/__init__.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Run the full unit test suite**

```bash
.venv/bin/python -m pytest -m "not integration" -v
```

Expected: all tests pass (109 existing + new order gate tests + human_auth + order_confirm tests)

- [ ] **Step 2: Bump version to 0.3.0 in `pyproject.toml`**

Change:
```toml
version = "0.2.0"
```
To:
```toml
version = "0.3.0"
```

- [ ] **Step 3: Bump version in `__init__.py`**

Change:
```python
__version__ = "0.2.0"
```
To:
```python
__version__ = "0.3.0"
```

- [ ] **Step 4: Commit version bump**

```bash
git add pyproject.toml ibkr_core_mcp/__init__.py
git commit -m "feat: v0.3.0 — human auth order security (Touch ID + confirmation dialog)"
```

- [ ] **Step 5: Tag and push**

```bash
git tag v0.3.0
git push origin main --tags
```

Expected output:
```
To https://github.com/stephus182/ibkr_core_mcp.git
   d428e11..XXXXXXX  main -> main
 * [new tag]         v0.3.0 -> v0.3.0
```

---

## Self-Review

**Spec coverage check:**
- ✅ Touch ID gate (`LAPolicyDeviceOwnerAuthenticationWithBiometrics`, 60s timeout) — Task 2
- ✅ Visual confirmation popup with order details + disclaimer + SEND button — Task 3
- ✅ Enforcement in `IBKRClient` before any network call — Task 4
- ✅ No bypass: abort on Touch ID failure OR dialog cancel — Task 4 tests
- ✅ `get_order_preview` explicitly ungated — Task 4 test `test_get_order_preview_has_no_gate`
- ✅ `HumanAuthError` in exception hierarchy — Task 1
- ✅ pyobjc dependency with macOS platform marker — Task 5
- ✅ CLAUDE.md security section — Task 6
- ✅ `require_touch_id` exported from `__init__.py` — Task 2 Step 5

**Placeholder scan:** No TBD, no TODO, all code blocks are complete.

**Type consistency:**
- `require_touch_id(reason: str) -> None` — used consistently in Tasks 2 and 4
- `confirm_order_dialog(order: dict, account_id: str) -> None` — matches Task 3 definition and Task 4 call
- `confirm_modify_dialog(order_id: str, order: dict, account_id: str) -> None` — consistent
- `confirm_cancel_dialog(order_id: str, account_id: str) -> None` — consistent
- `confirm_reply_dialog(reply_id: str) -> None` — consistent
- `_show_confirm_dialog(title, details, disclaimer, confirm_label)` — all callers use keyword args
