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
    label_calls = [
        c.args[0]
        for c in fake.NSTextField.alloc.return_value.initWithFrame_.return_value.setStringValue_.call_args_list
    ]
    assert "BUY ORDER" in label_calls
    assert capsys.readouterr().out.strip() == "CONFIRMED"


def test_sell_order_uses_red_banner(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    fake = _install_fake_appkit(monkeypatch)
    fake.NSAlert.alloc.return_value.init.return_value.runModal.return_value = 0

    from ibkr_core_mcp import _order_dialog

    _order_dialog._run_alert(_base_payload(side="SELL"))

    fake.NSColor.colorWithRed_green_blue_alpha_.assert_called_once_with(0.72, 0.10, 0.10, 1.0)
    label_calls = [
        c.args[0]
        for c in fake.NSTextField.alloc.return_value.initWithFrame_.return_value.setStringValue_.call_args_list
    ]
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


def test_main_exits_1_on_bad_json_stdin(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO("not json"))
    from ibkr_core_mcp import _order_dialog

    with pytest.raises(SystemExit) as exc_info:
        _order_dialog.main()
    assert exc_info.value.code == 1
    assert "ERROR: bad payload" in capsys.readouterr().err


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
