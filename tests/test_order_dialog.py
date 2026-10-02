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


def _banner_colour(fake: MagicMock) -> tuple[float, ...]:
    """The first custom colour the dialog makes is its banner's; the abandon button's red follows."""
    made: tuple[float, ...] = fake.NSColor.colorWithRed_green_blue_alpha_.call_args_list[0].args
    return made


def test_buy_order_uses_green_banner(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    fake = _install_fake_appkit(monkeypatch)
    fake.NSAlert.alloc.return_value.init.return_value.runModal.return_value = 1000

    from ibkr_core_mcp import _order_dialog

    _order_dialog._run_alert(_base_payload(side="BUY"))

    assert _banner_colour(fake) == (0.10, 0.50, 0.20, 1.0)
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

    assert _banner_colour(fake) == (0.72, 0.10, 0.10, 1.0)
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

    assert _banner_colour(fake) == (0.72, 0.10, 0.10, 1.0)


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


def test_unknown_side_uses_a_neutral_banner_not_a_confident_buy(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Cancel and reply dialogs carry no side at all — they must not read as a BUY.

    `data.get("side", "BUY")` made the *default* a confident dark-green "BUY ORDER".
    The banner is the pre-attentive cue, read before any text, so on 3 of the 4 Gate 2
    dialogs it was asserting something nobody had established. An unknown side is
    unknown; it is not a buy, and it is not a sell either.
    """
    fake = _install_fake_appkit(monkeypatch)
    fake.NSAlert.alloc.return_value.init.return_value.runModal.return_value = 1000

    from ibkr_core_mcp import _order_dialog

    payload = _base_payload()
    del payload["side"]
    _order_dialog._run_alert(payload)

    label_calls = [
        c.args[0]
        for c in fake.NSTextField.alloc.return_value.initWithFrame_.return_value.setStringValue_.call_args_list
    ]
    assert "BUY ORDER" not in label_calls, "an absent side must not render as a BUY"
    assert "SELL ORDER" not in label_calls, "nor as a SELL — neutral means neutral"
    assert "REVIEW ORDER" in label_calls
    # A caution yellow since 2026-10-01 (register F6): the operator found the first amber,
    # (0.55, 0.42, 0.05), "not a good color" on the rendered dialog.
    assert _banner_colour(fake) == (0.90, 0.72, 0.00, 1.0)
    assert capsys.readouterr().out.strip() == "CONFIRMED"


def test_empty_side_string_is_also_neutral(monkeypatch: pytest.MonkeyPatch) -> None:
    """order_confirm passed "" for every non-place dialog, which is just as unknown."""
    fake = _install_fake_appkit(monkeypatch)
    fake.NSAlert.alloc.return_value.init.return_value.runModal.return_value = 1000

    from ibkr_core_mcp import _order_dialog

    _order_dialog._run_alert(_base_payload(side=""))

    label_calls = [
        c.args[0]
        for c in fake.NSTextField.alloc.return_value.initWithFrame_.return_value.setStringValue_.call_args_list
    ]
    assert "REVIEW ORDER" in label_calls
    assert "BUY ORDER" not in label_calls


def test_the_button_that_reports_confirmed_is_the_confirm_button(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The binding between a button's *title* and what pressing it means.

    `_run_alert` addresses its buttons by index: the first one added is the one AppKit
    answers with `NSAlertFirstButtonReturn` (1000), which is the single value this file
    turns into "CONFIRMED", and index 0 is also the button whose Return key is cleared.
    Nothing tied that index to a title, so swapping the two `addButtonWithTitle_` lines
    left the suite green while making GO BACK place the order and SEND TO IBKR abandon
    it — measured against the whole 1,537-test run on 2026-09-17 (audit finding SEC-R4).

    The two assertions here are therefore by title, never by position.
    """
    fake = _install_fake_appkit(monkeypatch)
    alert_mock = fake.NSAlert.alloc.return_value.init.return_value
    alert_mock.runModal.return_value = 1000  # NSAlertFirstButtonReturn

    titles: list[str] = []
    alert_mock.addButtonWithTitle_.side_effect = titles.append
    buttons: dict[int, MagicMock] = {}
    alert_mock.buttons.return_value.objectAtIndex_.side_effect = lambda i: buttons.setdefault(i, MagicMock())

    from ibkr_core_mcp import _order_dialog

    _order_dialog._run_alert(_base_payload(confirm_label="SEND TO IBKR", abandon_label="GO BACK"))

    assert titles == ["SEND TO IBKR", "GO BACK"], (
        f"buttons were added in the order {titles}; the first added is the one AppKit "
        "reports as NSAlertFirstButtonReturn, which _run_alert prints as CONFIRMED"
    )
    assert capsys.readouterr().out.strip() == "CONFIRMED"

    by_title = {title: buttons[index] for index, title in enumerate(titles)}
    by_title["SEND TO IBKR"].setKeyEquivalent_.assert_called_once_with("")
    by_title["GO BACK"].setKeyEquivalent_.assert_called_once_with("\x1b")


def test_the_abandon_button_cannot_report_confirmed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The other direction: the second button's response must never mean CONFIRMED.

    AppKit answers 1001 (`NSAlertSecondButtonReturn`) for the abandon button and -1000
    (`NSModalResponseAbort`) for the timeout. Both have to come out as CANCELLED, or a
    widened comparison would turn an abandon into a placement.
    """
    for response in (1001, -1000, 0):
        fake = _install_fake_appkit(monkeypatch)
        alert_mock = fake.NSAlert.alloc.return_value.init.return_value
        alert_mock.runModal.return_value = response

        from ibkr_core_mcp import _order_dialog

        _order_dialog._run_alert(_base_payload())
        assert capsys.readouterr().out.strip() == "CANCELLED", f"response {response} was not treated as an abandon"


# ── Button colours and order (register F6, settled with the operator on screen 2026-10-01) ──


def _fake_with_two_buttons(monkeypatch: pytest.MonkeyPatch) -> tuple[MagicMock, MagicMock, MagicMock, MagicMock]:
    """A fake AppKit whose alert hands out two DISTINCT buttons — index 0 confirm, 1 abandon.

    A bare MagicMock answers every `objectAtIndex_` with the same object, so a colour put on
    the wrong button would be invisible.
    """
    fake = _install_fake_appkit(monkeypatch)
    alert = fake.NSAlert.alloc.return_value.init.return_value
    alert.runModal.return_value = 1000
    confirm, abandon = MagicMock(name="confirm-button"), MagicMock(name="abandon-button")
    alert.buttons.return_value.objectAtIndex_.side_effect = lambda index: (confirm, abandon)[index]
    return fake, alert, confirm, abandon


def _painted(button: MagicMock) -> Any:
    """The colour a button's own layer was filled with, or None if it was left alone."""
    fill = button.layer.return_value.setBackgroundColor_
    return fill.call_args.args[0] if fill.called else None


def test_the_confirm_button_is_painted_blue_and_the_abandon_button_red(monkeypatch: pytest.MonkeyPatch) -> None:
    """The colour is read before the label: swapped, the button that sends would be the red one."""
    fake, _alert, confirm, abandon = _fake_with_two_buttons(monkeypatch)
    from ibkr_core_mcp import _order_dialog

    _order_dialog._run_alert(_base_payload(abandon_label="DO NOT SEND"))

    assert _painted(confirm) is fake.NSColor.systemBlueColor.return_value.CGColor.return_value
    assert _painted(abandon) is fake.NSColor.colorWithRed_green_blue_alpha_.return_value.CGColor.return_value


def test_the_validating_button_is_moved_first_and_is_still_the_one_that_confirms(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Side by side the system arranges the abandon button first. The confirm button is moved
    within the row, never re-added: a re-added button would change which click confirms."""
    _fake, _alert, confirm, abandon = _fake_with_two_buttons(monkeypatch)
    row = MagicMock(name="button-row")
    row.arrangedSubviews.return_value = [abandon, confirm]
    confirm.superview.return_value = row
    from ibkr_core_mcp import _order_dialog

    _order_dialog._run_alert(_base_payload(confirm_label="VALIDATE", abandon_label="DISCARD"))

    row.insertArrangedSubview_atIndex_.assert_called_once_with(confirm, 0)
    assert capsys.readouterr().out.strip() == "CONFIRMED"


def test_a_row_this_code_does_not_recognise_never_fails_the_dialog(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Another macOS may build the row differently: the order is a nicety, the confirmation is not."""
    _fake, _alert, confirm, _abandon = _fake_with_two_buttons(monkeypatch)
    confirm.superview.side_effect = RuntimeError("no such view")
    from ibkr_core_mcp import _order_dialog

    _order_dialog._run_alert(_base_payload(confirm_label="VALIDATE", abandon_label="DISCARD"))

    assert capsys.readouterr().out.strip() == "CONFIRMED"
