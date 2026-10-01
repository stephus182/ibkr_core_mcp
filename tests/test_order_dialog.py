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
    fake.NSColor.colorWithRed_green_blue_alpha_.assert_called_once_with(0.90, 0.72, 0.00, 1.0)
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


# ── Button roles, the banner, the host's icon (register F6, reviewed on screen 2026-10-01) ──


def _fake_with_two_buttons(monkeypatch: pytest.MonkeyPatch) -> tuple[MagicMock, MagicMock, MagicMock, MagicMock]:
    """A fake AppKit whose alert hands out two DISTINCT buttons — index 0 confirm, 1 abandon.

    A bare MagicMock answers every `objectAtIndex_` with the same object, so a tint put on the
    wrong button would be invisible.
    """
    fake = _install_fake_appkit(monkeypatch)
    alert = fake.NSAlert.alloc.return_value.init.return_value
    alert.runModal.return_value = 1000
    confirm, abandon = MagicMock(name="confirm-button"), MagicMock(name="abandon-button")
    alert.buttons.return_value.objectAtIndex_.side_effect = lambda index: (confirm, abandon)[index]
    return fake, alert, confirm, abandon


def _painted(button: MagicMock) -> Any:
    """The colour a button's own layer was filled with, or None if it was left alone.

    The LAYER, not `bezelColor`: AppKit draws a tinted bezel only while the window is active,
    and an inactive dialog showed white titles on grey (operator's screenshot, 2026-10-01 —
    the dialog had opened while they were typing elsewhere).
    """
    fill = button.layer.return_value.setBackgroundColor_
    return fill.call_args.args[0] if fill.called else None


def _titles(fake: MagicMock) -> list[tuple[str, bool]]:
    """Each attributed title built: (text, whether it is white)."""
    white = fake.NSColor.whiteColor.return_value
    calls = fake.NSAttributedString.alloc.return_value.initWithString_attributes_.call_args_list
    return [(c.args[0], white in c.args[1].values()) for c in calls]


def test_a_validating_button_is_solid_blue_with_a_white_title(monkeypatch: pytest.MonkeyPatch) -> None:
    fake, _alert, confirm, abandon = _fake_with_two_buttons(monkeypatch)
    from ibkr_core_mcp import _order_dialog

    _order_dialog._run_alert(
        _base_payload(confirm_role="validate", abandon_label="LEAVE UNCHANGED", abandon_role="neutral")
    )

    assert _painted(confirm) is fake.NSColor.systemBlueColor.return_value.CGColor.return_value
    confirm.setWantsLayer_.assert_called_once_with(True)
    confirm.layer.return_value.setCornerRadius_.assert_called_once()  # the pill shape of the system's own buttons
    confirm.setBezelColor_.assert_not_called()  # a tinted bezel turns grey in an inactive window
    confirm.setAttributedTitle_.assert_called_once()
    assert ("SEND TO IBKR", True) in _titles(fake)
    assert _painted(abandon) is None
    abandon.setWantsLayer_.assert_not_called()
    abandon.setAttributedTitle_.assert_not_called()


def test_a_discarding_button_is_solid_red_the_banners_own_red(monkeypatch: pytest.MonkeyPatch) -> None:
    """The cancel dialog as the operator settled it: `CANCEL ORDER` validates, in blue;
    `KEEP ORDER` discards, in red. Not AppKit's `hasDestructiveAction` — pale pink with red
    text, shown and rejected — and the SAME red as the banner, by one constant."""
    fake, _alert, confirm, abandon = _fake_with_two_buttons(monkeypatch)
    from ibkr_core_mcp import _order_dialog

    _order_dialog._run_alert(
        _base_payload(
            side=None,
            action="CANCEL",
            confirm_label="CANCEL ORDER",
            confirm_role="validate",
            abandon_label="KEEP ORDER",
            abandon_role="discard",
        )
    )

    red = (*_order_dialog._RED, 1.0)
    assert _order_dialog._RED == (0.72, 0.10, 0.10)
    assert [c.args for c in fake.NSColor.colorWithRed_green_blue_alpha_.call_args_list] == [red, red]  # banner, button
    assert _painted(abandon) is fake.NSColor.colorWithRed_green_blue_alpha_.return_value.CGColor.return_value
    abandon.setHasDestructiveAction_.assert_not_called()
    abandon.setBezelColor_.assert_not_called()
    assert _painted(confirm) is fake.NSColor.systemBlueColor.return_value.CGColor.return_value
    assert ("CANCEL ORDER", True) in _titles(fake) and ("KEEP ORDER", True) in _titles(fake)


def test_the_abandon_button_takes_its_own_role(monkeypatch: pytest.MonkeyPatch) -> None:
    """`DO NOT SEND` throws the order away: red, beside the blue `SEND TO IBKR`."""
    fake, _alert, confirm, abandon = _fake_with_two_buttons(monkeypatch)
    from ibkr_core_mcp import _order_dialog

    _order_dialog._run_alert(
        _base_payload(confirm_role="validate", abandon_label="DO NOT SEND", abandon_role="discard")
    )

    assert _painted(confirm) is fake.NSColor.systemBlueColor.return_value.CGColor.return_value
    assert _painted(abandon) is fake.NSColor.colorWithRed_green_blue_alpha_.return_value.CGColor.return_value
    assert ("SEND TO IBKR", True) in _titles(fake) and ("DO NOT SEND", True) in _titles(fake)


@pytest.mark.parametrize("role", ["neutral", None, "primary"], ids=["neutral", "unstated", "unknown"])
def test_a_button_with_no_colour_role_is_left_as_the_system_draws_it(
    monkeypatch: pytest.MonkeyPatch, role: str | None
) -> None:
    """The dialog process is lenient — the caller's side refuses an unknown role — and never
    tints by default: a missing key must not paint a button."""
    fake, _alert, confirm, abandon = _fake_with_two_buttons(monkeypatch)
    from ibkr_core_mcp import _order_dialog

    payload = _base_payload(abandon_label="KEEP ORDER")
    if role is not None:
        payload.update(confirm_role=role, abandon_role=role)
    _order_dialog._run_alert(payload)

    for button in (confirm, abandon):
        assert _painted(button) is None
        button.setWantsLayer_.assert_not_called()
        button.setBezelColor_.assert_not_called()
        button.setAttributedTitle_.assert_not_called()
    fake.NSColor.systemBlueColor.assert_not_called()


def test_the_tints_are_applied_after_the_alert_is_laid_out(monkeypatch: pytest.MonkeyPatch) -> None:
    """Measured off-screen on macOS 27: a title set before `layout()` did not survive it."""
    _fake, alert, confirm, abandon = _fake_with_two_buttons(monkeypatch)
    from ibkr_core_mcp import _order_dialog

    events: list[str] = []
    alert.layout.side_effect = lambda: events.append("layout")
    confirm.layer.return_value.setBackgroundColor_.side_effect = lambda colour: events.append("confirm tint")
    abandon.layer.return_value.setBackgroundColor_.side_effect = lambda colour: events.append("abandon tint")

    def shown() -> int:
        """The modal runs: record it and answer as the confirm button."""
        events.append("shown")
        return 1000

    alert.runModal.side_effect = shown

    _order_dialog._run_alert(
        _base_payload(confirm_role="validate", abandon_label="DO NOT SEND", abandon_role="discard")
    )

    assert events == ["layout", "confirm tint", "abandon tint", "shown"]


def test_the_banner_colours_are_the_ones_agreed_on_screen() -> None:
    """One red for SELL, CANCEL and the discarding button; green BUY; a caution yellow where
    no side is stated — the first amber was "not a good color"."""
    from ibkr_core_mcp import _order_dialog

    assert _order_dialog._banner("SELL", None) == (_order_dialog._RED, "SELL ORDER")
    assert _order_dialog._banner("BUY", "CANCEL") == (_order_dialog._RED, "CANCEL ORDER")
    assert _order_dialog._banner("SELL", "MODIFY") == (_order_dialog._RED, "MODIFY ORDER")
    assert _order_dialog._banner("BUY", None) == ((0.10, 0.50, 0.20), "BUY ORDER")
    assert _order_dialog._banner(None, None) == ((0.90, 0.72, 0.00), "REVIEW ORDER")


def test_the_banner_text_is_centred_across_the_dialog_in_white(monkeypatch: pytest.MonkeyPatch) -> None:
    """Centred over the buttons below it ("cleaner"), white on every banner — yellow included,
    which the operator chose over black after seeing both."""
    fake = _install_fake_appkit(monkeypatch)
    fake.NSAlert.alloc.return_value.init.return_value.runModal.return_value = 1000
    from ibkr_core_mcp import _order_dialog

    _order_dialog._run_alert(_base_payload(side=None))

    field = fake.NSTextField.alloc.return_value.initWithFrame_.return_value
    field.setAlignment_.assert_called_once_with(fake.NSTextAlignmentCenter)
    field.setTextColor_.assert_called_once_with(fake.NSColor.whiteColor.return_value)
    assert (0, 12, _order_dialog._DIALOG_WIDTH, 24) in [c.args for c in fake.NSMakeRect.call_args_list]


def test_a_hosts_icon_replaces_the_default_when_it_can_be_read(monkeypatch: pytest.MonkeyPatch) -> None:
    fake, alert, _confirm, _abandon = _fake_with_two_buttons(monkeypatch)
    from ibkr_core_mcp import _order_dialog

    _order_dialog._run_alert(_base_payload(icon_path="/somewhere/mark.png"))

    loader = fake.NSImage.alloc.return_value.initWithContentsOfFile_
    loader.assert_called_once_with("/somewhere/mark.png")
    alert.setIcon_.assert_called_once_with(loader.return_value)


def test_an_icon_that_cannot_be_read_leaves_the_default_and_the_dialog_still_runs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Never a reason to fail a confirmation: AppKit answers None for an unreadable file."""
    fake, alert, _confirm, _abandon = _fake_with_two_buttons(monkeypatch)
    fake.NSImage.alloc.return_value.initWithContentsOfFile_.return_value = None
    from ibkr_core_mcp import _order_dialog

    _order_dialog._run_alert(_base_payload(icon_path="/nowhere/missing.png"))

    alert.setIcon_.assert_not_called()
    assert capsys.readouterr().out.strip() == "CONFIRMED"


@pytest.mark.parametrize("icon_path", [None, ""], ids=["unset", "empty"])
def test_no_icon_is_loaded_when_the_host_set_none(monkeypatch: pytest.MonkeyPatch, icon_path: str | None) -> None:
    fake, alert, _confirm, _abandon = _fake_with_two_buttons(monkeypatch)
    from ibkr_core_mcp import _order_dialog

    _order_dialog._run_alert(_base_payload(icon_path=icon_path))

    fake.NSImage.alloc.assert_not_called()
    alert.setIcon_.assert_not_called()


# ── The validating button comes first, whichever way the system lays the row out ──
#
# NSAlert stacks two long buttons with the first on top, and puts two short ones side by side
# with the first on the RIGHT. `VALIDATE` / `DISCARD` are short: the operator saw DISCARD
# first and asked for "Validate first" (2026-10-01).


def _row(
    fake: MagicMock,
    alert: MagicMock,
    confirm: MagicMock,
    abandon: MagicMock,
    *,
    orientation: int,
    order: list[MagicMock],
) -> MagicMock:
    """The button row the alert built: an NSStackView with this orientation and arranged order."""
    row = MagicMock(name="button-row")
    row.orientation.return_value = orientation
    row.arrangedSubviews.return_value = order
    confirm.superview.return_value = row
    abandon.superview.return_value = row
    return row


def test_side_by_side_the_validating_button_is_moved_first(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake, alert, confirm, abandon = _fake_with_two_buttons(monkeypatch)
    row = _row(fake, alert, confirm, abandon, orientation=0, order=[abandon, confirm])
    from ibkr_core_mcp import _order_dialog

    _order_dialog._run_alert(
        _base_payload(
            confirm_label="VALIDATE", abandon_label="DISCARD", confirm_role="validate", abandon_role="discard"
        )
    )

    row.insertArrangedSubview_atIndex_.assert_called_once_with(confirm, 0)
    # Moving a button is not re-adding it: the confirm button is still the one that confirms.
    assert capsys.readouterr().out.strip() == "CONFIRMED"


def test_stacked_the_row_is_left_as_the_system_built_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stacked, the system arranges the confirm button first — on top (measured, macOS 27)."""
    fake, alert, confirm, abandon = _fake_with_two_buttons(monkeypatch)
    row = _row(fake, alert, confirm, abandon, orientation=1, order=[confirm, abandon])
    from ibkr_core_mcp import _order_dialog

    _order_dialog._run_alert(_base_payload(abandon_label="DO NOT SEND"))

    row.insertArrangedSubview_atIndex_.assert_not_called()


def test_side_by_side_and_already_first_nothing_is_moved(monkeypatch: pytest.MonkeyPatch) -> None:
    fake, alert, confirm, abandon = _fake_with_two_buttons(monkeypatch)
    row = _row(fake, alert, confirm, abandon, orientation=0, order=[confirm, abandon])
    from ibkr_core_mcp import _order_dialog

    _order_dialog._run_alert(_base_payload(confirm_label="VALIDATE", abandon_label="DISCARD"))

    row.insertArrangedSubview_atIndex_.assert_not_called()


def test_the_buttons_are_moved_before_they_are_painted_and_after_the_layout(monkeypatch: pytest.MonkeyPatch) -> None:
    fake, alert, confirm, abandon = _fake_with_two_buttons(monkeypatch)
    row = _row(fake, alert, confirm, abandon, orientation=0, order=[abandon, confirm])
    from ibkr_core_mcp import _order_dialog

    events: list[str] = []
    alert.layout.side_effect = lambda: events.append("layout")
    row.insertArrangedSubview_atIndex_.side_effect = lambda view, index: events.append("moved")
    confirm.layer.return_value.setBackgroundColor_.side_effect = lambda colour: events.append("painted")

    _order_dialog._run_alert(_base_payload(confirm_label="VALIDATE", abandon_label="DISCARD", confirm_role="validate"))

    assert events == ["layout", "moved", "painted"]


def test_a_row_this_code_does_not_recognise_never_fails_the_dialog(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Another macOS may build the row differently: the order is a nicety, the confirmation is
    not. Whatever the row answers — or raises — the dialog still runs."""
    _fake, _alert, confirm, _abandon = _fake_with_two_buttons(monkeypatch)
    confirm.superview.side_effect = RuntimeError("no such view")
    from ibkr_core_mcp import _order_dialog

    _order_dialog._run_alert(_base_payload(confirm_label="VALIDATE", abandon_label="DISCARD", confirm_role="validate"))

    assert capsys.readouterr().out.strip() == "CONFIRMED"
    assert _painted(confirm) is not None  # and the colours are still applied
