# _order_dialog.py Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring `ibkr_core_mcp/_order_dialog.py` (the Gate 2 AppKit confirmation-dialog subprocess) up to industry-standard quality: fix a real cross-thread AppKit bug, replace magic numbers with named constants, close a dangling doc reference, and add characterization tests that lock down its current (and fixed) behavior.

**Architecture:** No change to the subprocess protocol (stdin JSON in, `CONFIRMED`/`CANCELLED` on stdout, `ERROR: ...` on stderr, exit 0/1) and no change to Gate 2's security properties (confirm button still requires an explicit click, Return is still disabled on confirm, Escape still cancels). Only internal implementation quality changes.

**Tech Stack:** Python 3.11+, PyObjC (`AppKit`), pytest with `unittest.mock.MagicMock` injected into `sys.modules["AppKit"]` (no real macOS GUI needed for the mocked tests).

---

## Context for the engineer picking this up

`ibkr_core_mcp/_order_dialog.py` is spawned as a subprocess by `_show_appkit_dialog()` in `ibkr_core_mcp/order_confirm.py` so it can own its own main thread and run an `NSAlert` modally without fighting the host app's asyncio loop. It is part of Gate 2 (visual order confirmation) described in `CLAUDE.md`'s Security & Fingerprint Authentication section — **do not weaken the gate** (don't make the confirm button easier to trigger, don't re-enable Return-to-confirm, don't remove the click requirement) while doing this cleanup.

There is currently no test file for `_order_dialog.py` itself — `tests/test_order_confirm.py` only tests the caller, always mocking `subprocess.run`, so it treats `_order_dialog.py` as an opaque external script. This plan adds a real test file for it, `tests/test_order_dialog.py`, by injecting a `MagicMock()` as `sys.modules["AppKit"]` before importing/calling the module's functions — this works on any OS since PyObjC isn't actually touched.

**Known finding driving Task 3** (verified against Apple's docs/community references, not assumed — see `CLAUDE.md`'s "API Docs First" convention):
- AppKit's threading rules require UI/run-loop interaction on the main thread (Apple's Cocoa Thread Safety Summary: https://developer.apple.com/library/archive/documentation/Cocoa/Conceptual/Multithreading/ThreadSafetySummary/ThreadSafetySummary.html — `NSApplication`/modal-session calls are not documented as safe from a background thread).
- The current code calls `NSApp.abortModal()` from a Python `threading.Timer` background thread — a genuine cross-thread AppKit violation, not just a style nit.
- `NSAlert.runModal()` pumps the run loop in `NSModalPanelRunLoopMode` (confirmed via Apple docs + community references on auto-dismissing `NSAlert` with a timer). The idiomatic, verified-safe fix is a **main-thread `NSTimer`** added to the current run loop for that mode — not `performSelectorOnMainThread:withObject:waitUntilDone:`, whose 3-argument form only services `NSDefaultRunLoopMode` and would silently never fire while the alert is modal (this would be a strictly worse regression: the 60s auto-dismiss would stop working at all instead of just being fragile).
- Because this behavior is genuinely dependent on live AppKit run-loop timing (not something a `MagicMock` can prove), Task 3 includes both a mock-based test (asserts the correct APIs are called with the correct arguments) **and** a manual live-run verification step on this machine.

---

## Task 1: Characterization tests for existing `_run_alert` behavior

**Files:**
- Create: `tests/test_order_dialog.py`

- [ ] **Step 1: Write the test file with a fake-AppKit helper and BUY/SELL banner tests**

```python
import sys
from typing import Any
from unittest.mock import MagicMock

import pytest


def _install_fake_appkit(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Inject a MagicMock as sys.modules['AppKit'] so _order_dialog can be
    imported/exercised on any OS without real PyObjC/AppKit installed."""
    fake_appkit = MagicMock(name="AppKit")
    monkeypatch.setitem(sys.modules, "AppKit", fake_appkit)
    return fake_appkit


def _base_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "side": "BUY",
        "details": {"Symbol": "AAPL", "Action": "BUY", "Quantity": 100},
        "disclaimer": "This will place a LIVE order.",
        "confirm_label": "SEND TO IBKR",
        "title": "LIVE ORDER CONFIRMATION",
        "timeout_s": 60,
    }
    payload.update(overrides)
    return payload


def test_buy_order_uses_green_banner(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    fake = _install_fake_appkit(monkeypatch)
    fake.NSAlert.alloc.return_value.init.return_value.runModal.return_value = 1000

    from ibkr_core_mcp import _order_dialog
    _order_dialog._run_alert(_base_payload(side="BUY"))

    fake.NSColor.colorWithRed_green_blue_alpha_.assert_called_once_with(0.10, 0.50, 0.20, 1.0)
    label_calls = [c.args[0] for c in fake.NSTextField.alloc.return_value.initWithFrame_.return_value.setStringValue_.call_args_list]
    assert "BUY ORDER" in label_calls
    assert capsys.readouterr().out.strip() == "CONFIRMED"


def test_sell_order_uses_red_banner(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    fake = _install_fake_appkit(monkeypatch)
    fake.NSAlert.alloc.return_value.init.return_value.runModal.return_value = 0

    from ibkr_core_mcp import _order_dialog
    _order_dialog._run_alert(_base_payload(side="SELL"))

    fake.NSColor.colorWithRed_green_blue_alpha_.assert_called_once_with(0.72, 0.10, 0.10, 1.0)
    label_calls = [c.args[0] for c in fake.NSTextField.alloc.return_value.initWithFrame_.return_value.setStringValue_.call_args_list]
    assert "SELL ORDER" in label_calls
    assert capsys.readouterr().out.strip() == "CANCELLED"


def test_short_side_counts_as_sell(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    fake = _install_fake_appkit(monkeypatch)
    fake.NSAlert.alloc.return_value.init.return_value.runModal.return_value = 0

    from ibkr_core_mcp import _order_dialog
    _order_dialog._run_alert(_base_payload(side="SSHORT"))

    fake.NSColor.colorWithRed_green_blue_alpha_.assert_called_once_with(0.72, 0.10, 0.10, 1.0)


def test_confirm_button_return_key_disabled_and_cancel_uses_escape(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install_fake_appkit(monkeypatch)
    alert_mock = fake.NSAlert.alloc.return_value.init.return_value
    alert_mock.runModal.return_value = 1000
    confirm_btn = MagicMock()
    cancel_btn = MagicMock()
    alert_mock.buttons.return_value.objectAtIndex_.side_effect = lambda i: confirm_btn if i == 0 else cancel_btn

    from ibkr_core_mcp import _order_dialog
    _order_dialog._run_alert(_base_payload())

    confirm_btn.setKeyEquivalent_.assert_called_once_with("")
    cancel_btn.setKeyEquivalent_.assert_called_once_with("\x1b")
```

- [ ] **Step 2: Run the new tests**

Run: `pytest tests/test_order_dialog.py -v`
Expected: All 4 tests PASS immediately — these characterize existing, already-correct behavior, so there's no red/green cycle here; a passing result on first run confirms the fake-AppKit harness is wired correctly.

- [ ] **Step 3: Commit**

```bash
git add tests/test_order_dialog.py
git commit -m "test: add characterization tests for _order_dialog._run_alert"
```

---

## Task 2: Characterization test for `main()`'s error handling

**Files:**
- Modify: `tests/test_order_dialog.py`

- [ ] **Step 1: Add a test for the bad-JSON stdin path**

```python
def test_main_exits_1_on_bad_json_stdin(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO("not json"))
    from ibkr_core_mcp import _order_dialog
    with pytest.raises(SystemExit) as exc_info:
        _order_dialog.main()
    assert exc_info.value.code == 1
    assert "ERROR: bad payload" in capsys.readouterr().err
```

- [ ] **Step 2: Run it**

Run: `pytest tests/test_order_dialog.py::test_main_exits_1_on_bad_json_stdin -v`
Expected: PASS (existing `main()` already handles this correctly).

- [ ] **Step 3: Commit**

```bash
git add tests/test_order_dialog.py
git commit -m "test: add characterization test for _order_dialog.main JSON error path"
```

---

## Task 3: Fix cross-thread AppKit call in the auto-dismiss timer

**Files:**
- Modify: `ibkr_core_mcp/_order_dialog.py:14-19` (imports), `:38-48` (AppKit import list), `:107-121` (timer)
- Modify: `tests/test_order_dialog.py`

- [ ] **Step 1: Write the failing test (asserts main-thread NSTimer scheduling, not threading.Timer)**

```python
def test_abort_timer_scheduled_on_main_thread_in_modal_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install_fake_appkit(monkeypatch)
    alert_mock = fake.NSAlert.alloc.return_value.init.return_value
    alert_mock.runModal.return_value = 1000
    mock_timer_obj = MagicMock(name="scheduled_timer")
    fake.NSTimer.timerWithTimeInterval_repeats_block_.return_value = mock_timer_obj

    from ibkr_core_mcp import _order_dialog
    _order_dialog._run_alert(_base_payload(timeout_s=42))

    fake.NSTimer.timerWithTimeInterval_repeats_block_.assert_called_once()
    call_args = fake.NSTimer.timerWithTimeInterval_repeats_block_.call_args.args
    assert call_args[0] == 42
    assert call_args[1] is False
    assert callable(call_args[2])

    fake.NSRunLoop.currentRunLoop.return_value.addTimer_forMode_.assert_called_once_with(
        mock_timer_obj, fake.NSModalPanelRunLoopMode
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_order_dialog.py::test_abort_timer_scheduled_on_main_thread_in_modal_mode -v`
Expected: FAIL — current code uses `threading.Timer`, so `fake.NSTimer.timerWithTimeInterval_repeats_block_` is never called (assertion error: `Expected 'timerWithTimeInterval_repeats_block_' to have been called once. Called 0 times.`)

- [ ] **Step 3: Implement the fix**

In `ibkr_core_mcp/_order_dialog.py`, remove the now-unused module-level import (line 18):

```python
import threading
```
→ delete this line entirely.

Add `NSModalPanelRunLoopMode`, `NSRunLoop`, `NSTimer` to the existing `from AppKit import (...)` block inside `_run_alert` (currently lines 39-48):

```python
    from AppKit import (
        NSAlert,
        NSApplication,
        NSBox,
        NSColor,
        NSFont,
        NSMakeRect,
        NSModalPanelRunLoopMode,
        NSRunLoop,
        NSTextField,
        NSTimer,
        NSView,
    )
```

Replace the timer block (currently lines 107-117):

```python
    # Auto-dismiss after timeout — NSApp.abortModal() returns NSModalResponseAbort (-1000)
    def _abort() -> None:
        try:
            from AppKit import NSApp
            NSApp.abortModal()
        except Exception:
            pass

    timer = threading.Timer(timeout_s, _abort)
    timer.daemon = True
    timer.start()
```

with:

```python
    # Auto-dismiss after timeout — NSApp.abortModal() returns NSModalResponseAbort (-1000).
    # Must run on the main thread: AppKit's threading rules require UI/run-loop calls there
    # (Apple Cocoa Thread Safety Summary), and NSAlert.runModal() pumps NSModalPanelRunLoopMode,
    # so the timer is scheduled directly into that mode on the current (main) run loop rather
    # than fired from a background thread.
    def _abort(_timer: Any) -> None:
        try:
            from AppKit import NSApp
            NSApp.abortModal()
        except Exception:
            pass

    abort_timer = NSTimer.timerWithTimeInterval_repeats_block_(timeout_s, False, _abort)
    NSRunLoop.currentRunLoop().addTimer_forMode_(abort_timer, NSModalPanelRunLoopMode)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_order_dialog.py -v`
Expected: All tests PASS, including the new one.

- [ ] **Step 5: Manual live verification (mocks can't prove real run-loop timing)**

This behavior depends on genuine AppKit run-loop scheduling that a `MagicMock` cannot exercise. Verify on this Mac before trusting the fix:

```bash
python3 -c "
import json, subprocess, sys, time
payload = json.dumps({
    'side': 'BUY', 'details': {'Symbol': 'TEST'}, 'disclaimer': 'test',
    'confirm_label': 'CONFIRM', 'title': 'Timeout test', 'timeout_s': 3,
})
start = time.time()
proc = subprocess.run([sys.executable, 'ibkr_core_mcp/_order_dialog.py'],
                       input=payload, capture_output=True, text=True, timeout=15)
elapsed = time.time() - start
print(f'stdout={proc.stdout!r} elapsed={elapsed:.1f}s')
assert proc.stdout.strip() == 'CANCELLED', 'expected auto-dismiss to cancel'
assert 3 <= elapsed < 8, f'expected auto-dismiss around 3s, took {elapsed:.1f}s'
print('OK: dialog auto-dismissed on schedule from the modal run loop')
"
```

A dialog window will briefly appear and should auto-dismiss itself after ~3 seconds without any click. Confirm the printed `OK` line. If it hangs instead (waits the full 15s subprocess timeout), the run-loop mode fix didn't take — stop and re-check the mode constant/import before proceeding, do not paper over it.

- [ ] **Step 6: Commit**

```bash
git add ibkr_core_mcp/_order_dialog.py tests/test_order_dialog.py
git commit -m "fix: schedule dialog auto-dismiss timer on main thread's modal run loop

NSApp.abortModal() was being called from a background threading.Timer,
violating AppKit's main-thread-only rule for UI/run-loop calls. Fixed by
scheduling an NSTimer directly into NSModalPanelRunLoopMode on the main
thread, matching how NSAlert.runModal() pumps its run loop."
```

---

## Task 4: Replace magic Cocoa integer literals with named constants

**Files:**
- Modify: `ibkr_core_mcp/_order_dialog.py`

- [ ] **Step 1: Add module-level constants**

After the imports (after line 19, before `def main()`):

```python
# Cocoa constants (kept as local int literals rather than imported from AppKit —
# these are the actual runtime values already exercised by this file; naming them
# here documents intent without adding another PyObjC-bridging dependency).
_NS_APPLICATION_ACTIVATION_POLICY_ACCESSORY = 1
_NS_BOX_CUSTOM = 4
_NS_NO_TITLE = 0
_NS_ALERT_FIRST_BUTTON_RETURN = 1000
```

- [ ] **Step 2: Replace the four call sites**

`app.setActivationPolicy_(1)  # NSApplicationActivationPolicyAccessory` →
`app.setActivationPolicy_(_NS_APPLICATION_ACTIVATION_POLICY_ACCESSORY)`

`box.setBoxType_(4)` (comment above: `# Colored banner via NSBox (NSBoxCustom = 4, NSNoTitle = 0)`) →
`box.setBoxType_(_NS_BOX_CUSTOM)`

`box.setTitlePosition_(0)` →
`box.setTitlePosition_(_NS_NO_TITLE)`

`print("CONFIRMED" if response == 1000 else "CANCELLED")` (comment above: `# NSAlertFirstButtonReturn = 1000`) →
`print("CONFIRMED" if response == _NS_ALERT_FIRST_BUTTON_RETURN else "CANCELLED")`

Remove the now-redundant inline comments at each of these four sites (the constant names carry the meaning now); keep the one-line block comment on `# Colored banner via NSBox (...)` only if it still reads naturally without the `= 4`/`= 0` annotations, otherwise trim it to `# Colored banner via NSBox`.

- [ ] **Step 3: Run full test file to confirm no behavior changed**

Run: `pytest tests/test_order_dialog.py -v`
Expected: All tests still PASS (values are identical, only named now).

- [ ] **Step 4: Commit**

```bash
git add ibkr_core_mcp/_order_dialog.py
git commit -m "refactor: name Cocoa magic-number constants in _order_dialog.py"
```

---

## Task 5: Close the dangling doc reference and document the private helpers

**Files:**
- Modify: `ibkr_core_mcp/_order_dialog.py`

- [ ] **Step 1: Fix the module docstring's stdin line**

Current (line 9):
```python
stdin  : JSON payload (see _run_alert for keys)
```

Replace with:
```python
stdin  : JSON payload — side, details (dict), disclaimer, confirm_label, title,
         timeout_s (see _run_alert's docstring for defaults)
```

- [ ] **Step 2: Add a docstring to `_run_alert`**

```python
def _run_alert(data: dict[str, Any]) -> None:
    """Build and run the app-modal NSAlert described by `data`.

    Keys read from `data` (all optional except where noted):
      side          - "BUY"/"SELL"/etc; anything containing SELL or SHORT gets
                       the red banner, everything else gets the green one.
      details       - dict rendered as "key: value" lines in the alert body.
      disclaimer    - free text appended after the details.
      confirm_label - text for the right-hand (confirm) button. Default "CONFIRM".
      title         - alert message text. Default "LIVE ORDER CONFIRMATION".
      timeout_s     - seconds before auto-dismiss (counts as cancel). Default 60.

    Prints "CONFIRMED" or "CANCELLED" to stdout; never raises for user input,
    only for a genuinely broken AppKit call (caught by main()'s caller).
    """
```

- [ ] **Step 3: Add a one-line docstring to `_abort`**

```python
    def _abort(_timer: Any) -> None:
        """Timer callback: abort the running modal session (counts as cancel)."""
```

- [ ] **Step 4: Add a one-line docstring to `main`**

```python
def main() -> None:
    """Entry point: read the JSON payload from stdin and run the alert it describes."""
```

- [ ] **Step 5: Run full suite + lint**

Run: `ruff check ibkr_core_mcp/_order_dialog.py && mypy ibkr_core_mcp/_order_dialog.py && pytest tests/test_order_dialog.py -v`
Expected: ruff clean, no new mypy errors attributable to this file, all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add ibkr_core_mcp/_order_dialog.py
git commit -m "docs: document _order_dialog.py payload keys and private helpers"
```

---

## Task 6: Full verification pass

**Files:** none (verification only)

- [ ] **Step 1: Run the full non-integration suite**

Run: `pytest -m "not integration"`
Expected: All tests pass, including the new `tests/test_order_dialog.py` file and the existing `tests/test_order_confirm.py` (unaffected, since it only mocks at the `subprocess.run` boundary).

- [ ] **Step 2: Run ruff and mypy across the touched files**

Run: `ruff check ibkr_core_mcp/_order_dialog.py tests/test_order_dialog.py && mypy ibkr_core_mcp/_order_dialog.py`
Expected: Clean.

- [ ] **Step 3: Re-run the manual live-dialog check from Task 3, Step 5**

Confirms the main-thread timer fix still auto-dismisses correctly after all subsequent edits (constants/docstrings shouldn't affect it, but this is a security-gate file — confirm, don't assume).

- [ ] **Step 4: Final review against `CLAUDE.md`'s Gate 2 rules**

Re-read the current `ibkr_core_mcp/_order_dialog.py` and confirm: confirm button still requires an explicit click (Return still disabled via `setKeyEquivalent_("")`), Escape still cancels, no bypass/cache/fallback was introduced anywhere in this file. Do not commit this step — it's a checklist, not a code change.

---

## Self-review notes (from plan authoring)

- **Spec coverage:** "industry standard" → Task 3 (real bug fix) + Task 4 (magic numbers). "clean" → Task 4 + Task 5. "efficient" → checked; no inefficiency found in this file (it runs once per dialog invocation, no hot loops), so no dedicated task — forcing one would be a placeholder. "documented" → Task 5. All four target qualities are covered.
- **Placeholder scan:** none found — every step has literal code.
- **Type consistency:** `_abort` changes signature from `() -> None` to `(_timer: Any) -> None` because `NSTimer`'s block callback receives the timer instance as its argument; this is reflected consistently in both the Task 3 test and implementation steps.
