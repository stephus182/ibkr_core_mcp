import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest


def _install_fake_appkit(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Inject a MagicMock as sys.modules['AppKit'] so _order_dialog can be
    imported/exercised on any OS without real PyObjC/AppKit installed."""
    fake_appkit = MagicMock(name="AppKit")
    monkeypatch.setitem(sys.modules, "AppKit", fake_appkit)
    return fake_appkit


def _fake_dialog(
    monkeypatch: pytest.MonkeyPatch, response: int = 1000
) -> tuple[MagicMock, list[tuple[Any, MagicMock]]]:
    """The fake AppKit every dialog test runs against: the modal loop answers `response`; `NSButton`
    hands out a DISTINCT mock per button, recorded with the frame it was made in; `NSMakeRect`
    answers its own arguments so frames can be read.

    A bare MagicMock answers every `initWithFrame_` with the same object, so a colour, a selector
    or a frame put on the wrong button would be invisible.
    """
    fake = _install_fake_appkit(monkeypatch)
    fake.NSApplication.sharedApplication.return_value.runModalForWindow_.return_value = response
    made: list[tuple[Any, MagicMock]] = []

    def _button(frame: Any) -> MagicMock:
        button = MagicMock(name=f"button{len(made)}")
        made.append((frame, button))
        return button

    fake.NSButton.alloc.return_value.initWithFrame_.side_effect = _button
    fake.NSMakeRect.side_effect = lambda *xywh: xywh
    return fake, made


def _by_title(made: list[tuple[Any, MagicMock]]) -> dict[str, tuple[Any, MagicMock]]:
    """Each button under the title it was given — the only way this file identifies a button
    (by title, never by position: the SEC-R4 lesson of 2026-09-17, below)."""
    return {button.setTitle_.call_args.args[0]: (frame, button) for frame, button in made}


def _window_frame(fake: MagicMock) -> Any:
    return fake.NSWindow.alloc.return_value.initWithContentRect_styleMask_backing_defer_.call_args.args[0]


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


def _label_texts(fake: MagicMock) -> list[str]:
    """Every plain string put on a text field: the banner's word and the heading."""
    return [
        c.args[0]
        for c in fake.NSTextField.alloc.return_value.initWithFrame_.return_value.setStringValue_.call_args_list
    ]


def _painted(button: MagicMock) -> Any:
    """The colour a button's own layer was filled with, or None if it was left alone."""
    fill = button.layer.return_value.setBackgroundColor_
    return fill.call_args.args[0] if fill.called else None


def test_buy_order_uses_green_banner(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    fake, _made = _fake_dialog(monkeypatch, response=1000)

    from ibkr_core_mcp import _order_dialog

    _order_dialog._run_alert(_base_payload(side="BUY"))

    assert _banner_colour(fake) == (0.10, 0.50, 0.20, 1.0)
    assert "BUY ORDER" in _label_texts(fake)
    assert capsys.readouterr().out.strip() == "CONFIRMED"


def test_sell_order_uses_red_banner(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    fake, _made = _fake_dialog(monkeypatch, response=0)

    from ibkr_core_mcp import _order_dialog

    _order_dialog._run_alert(_base_payload(side="SELL"))

    assert _banner_colour(fake) == (0.72, 0.10, 0.10, 1.0)
    assert "SELL ORDER" in _label_texts(fake)
    assert capsys.readouterr().out.strip() == "CANCELLED"


def test_short_side_counts_as_sell(monkeypatch: pytest.MonkeyPatch) -> None:
    fake, _made = _fake_dialog(monkeypatch, response=0)

    from ibkr_core_mcp import _order_dialog

    _order_dialog._run_alert(_base_payload(side="SSHORT"))

    assert _banner_colour(fake) == (0.72, 0.10, 0.10, 1.0)


def test_main_exits_1_on_bad_json_stdin(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO("not json"))
    from ibkr_core_mcp import _order_dialog

    with pytest.raises(SystemExit) as exc_info:
        _order_dialog.main()
    assert exc_info.value.code == 1
    assert "ERROR: bad payload" in capsys.readouterr().err


def test_abort_timer_scheduled_on_main_thread_in_modal_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """The timer sits in the modal loop's own mode — Apple: `runModal(for:)` "does not perform
    any tasks (such as firing timers) that are not associated with the modal run loop" — and
    its callback aborts the modal through the application."""
    fake, _made = _fake_dialog(monkeypatch)
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
    call_args[2](mock_timer_obj)
    fake.NSApplication.sharedApplication.return_value.abortModal.assert_called_once_with()


def test_unknown_side_uses_a_neutral_banner_not_a_confident_buy(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Cancel and reply dialogs carry no side at all — they must not read as a BUY.

    `data.get("side", "BUY")` made the *default* a confident dark-green "BUY ORDER".
    The banner is the pre-attentive cue, read before any text, so on 3 of the 4 Gate 2
    dialogs it was asserting something nobody had established. An unknown side is
    unknown; it is not a buy, and it is not a sell either.
    """
    fake, _made = _fake_dialog(monkeypatch, response=1000)

    from ibkr_core_mcp import _order_dialog

    payload = _base_payload()
    del payload["side"]
    _order_dialog._run_alert(payload)

    label_calls = _label_texts(fake)
    assert "BUY ORDER" not in label_calls, "an absent side must not render as a BUY"
    assert "SELL ORDER" not in label_calls, "nor as a SELL — neutral means neutral"
    assert "REVIEW ORDER" in label_calls
    # A caution yellow since 2026-10-01 (register F6): the operator found the first amber,
    # (0.55, 0.42, 0.05), "not a good color" on the rendered dialog.
    assert _banner_colour(fake) == (0.90, 0.72, 0.00, 1.0)
    assert capsys.readouterr().out.strip() == "CONFIRMED"


def test_empty_side_string_is_also_neutral(monkeypatch: pytest.MonkeyPatch) -> None:
    """order_confirm passed "" for every non-place dialog, which is just as unknown."""
    fake, _made = _fake_dialog(monkeypatch)

    from ibkr_core_mcp import _order_dialog

    _order_dialog._run_alert(_base_payload(side=""))

    label_calls = _label_texts(fake)
    assert "REVIEW ORDER" in label_calls
    assert "BUY ORDER" not in label_calls


def test_the_abandon_button_cannot_report_confirmed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The other direction: no response but the confirm code may mean CONFIRMED.

    The abandon button stops the loop with 1001; −1000 is `NSModalResponseStop`; 0 is nothing
    this file ever sends. All have to come out as CANCELLED, or a widened comparison would
    turn an abandon into a placement.
    """
    for response in (1001, -1000, 0):
        _fake_dialog(monkeypatch, response=response)

        from ibkr_core_mcp import _order_dialog

        _order_dialog._run_alert(_base_payload())
        assert capsys.readouterr().out.strip() == "CANCELLED", f"response {response} was not treated as an abandon"


# ── The rows (claudia_ui gap #42; operator designs 2026-10-17 and 2026-10-19) ──────────────────


def test_a_row_whose_key_starts_with_the_warning_sign_is_drawn_red_and_bold(monkeypatch: pytest.MonkeyPatch) -> None:
    """The bracket dialog's `⚠ Partial fill` line and the cancel dialog's linked-order rows
    (operator, 2026-10-17): label AND value in the banner's red, both bold. An ordinary row
    keeps its regular label in the label colour."""
    fake, _made = _fake_dialog(monkeypatch)
    colours: dict[tuple[float, ...], MagicMock] = {}
    fake.NSColor.colorWithRed_green_blue_alpha_.side_effect = lambda *rgba: colours.setdefault(
        rgba, MagicMock(name=f"colour{rgba}")
    )

    from ibkr_core_mcp import _order_dialog

    _order_dialog._run_alert(
        _base_payload(details={"Symbol": "AAPL", "⚠ Partial fill": "Quantity 2: a partial fill …"})
    )

    runs = {
        c.args[0]: c.args[1]
        for c in fake.NSAttributedString.alloc.return_value.initWithString_attributes_.call_args_list
    }
    red = colours[(0.72, 0.10, 0.10, 1.0)]
    bold, regular = fake.NSFont.boldSystemFontOfSize_.return_value, fake.NSFont.systemFontOfSize_.return_value
    for text in ("⚠ Partial fill: ", "Quantity 2: a partial fill …"):
        assert runs[text][fake.NSFontAttributeName] is bold, text
        assert runs[text][fake.NSForegroundColorAttributeName] is red, text
    assert runs["Symbol: "][fake.NSFontAttributeName] is regular
    assert runs["Symbol: "][fake.NSForegroundColorAttributeName] is fake.NSColor.labelColor.return_value
    assert runs["AAPL"][fake.NSForegroundColorAttributeName] is fake.NSColor.labelColor.return_value


def test_a_section_is_drawn_as_a_title_once_above_its_indented_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    """Operator design 2026-10-19: the bracket dialog is three sections — the title once, in
    bold, a blank line before it, its rows beneath it indented — never `Parent — Symbol` on
    every row. A warning row inside a section is red and bold like a top-level one."""
    fake, _made = _fake_dialog(monkeypatch)
    colours: dict[tuple[float, ...], MagicMock] = {}
    fake.NSColor.colorWithRed_green_blue_alpha_.side_effect = lambda *rgba: colours.setdefault(
        rgba, MagicMock(name=f"colour{rgba}")
    )

    from ibkr_core_mcp import _order_dialog

    _order_dialog._run_alert(
        _base_payload(
            details={
                "Account": "U1",
                "Action": "BUY",
                "Parent": {"Symbol": "F", "⚠ Partial fill": "Quantity 2 …"},
                "Stop loss": {"Held by IBKR": "until the parent fills"},
            }
        )
    )

    calls = fake.NSAttributedString.alloc.return_value.initWithString_attributes_.call_args_list
    texts = [c.args[0] for c in calls]
    runs = {c.args[0]: c.args[1] for c in calls}
    bold, regular = fake.NSFont.boldSystemFontOfSize_.return_value, fake.NSFont.systemFontOfSize_.return_value
    red = colours[(0.72, 0.10, 0.10, 1.0)]
    # the title once, bold, after a blank line; the rows indented beneath it
    assert texts.index("\n\n") < texts.index("Parent") < texts.index("    Symbol: ") < texts.index("F")
    assert runs["Parent"][fake.NSFontAttributeName] is bold
    assert runs["    Symbol: "][fake.NSFontAttributeName] is regular and runs["F"][fake.NSFontAttributeName] is bold
    assert "Parent — Symbol: " not in runs
    assert texts.index("Stop loss") < texts.index("    Held by IBKR: ")
    assert runs["    ⚠ Partial fill: "][fake.NSForegroundColorAttributeName] is red
    assert runs["Quantity 2 …"][fake.NSFontAttributeName] is bold
    assert runs["Account: "][fake.NSFontAttributeName] is regular


# ── One layout for every dialog (claudia_ui gap #111, operator 2026-11-06/07) ─────────────────
#
# NSAlert drew the dialog until 2026-11-07 and chose among three layouts by its content's height
# and its labels' width (measured off-screen 2026-11-06): the same bracket dialog came out side by
# side at the bottom right one time, stacked and centred the next. The dialog is now the core's
# own window: one shape at every height, the buttons found BY TITLE here, never by position.


def test_a_decision_is_a_modal_code_and_only_the_confirm_method_gives_the_confirm_code() -> None:
    """The buttons' target is plain Python (PyObjC forwards target/action to it — measured
    2026-11-07): each method ends the modal loop with the code `outcome_token` reads for it."""
    from ibkr_core_mcp import _order_dialog

    app = MagicMock(name="NSApp")
    _order_dialog._Decision(app).confirm_(None)
    app.stopModalWithCode_.assert_called_once_with(1000)
    assert _order_dialog.outcome_token(1000) == "CONFIRMED"

    app.reset_mock()
    _order_dialog._Decision(app).abandon_(None)
    app.stopModalWithCode_.assert_called_once_with(1001)
    assert _order_dialog.outcome_token(1001) == "CANCELLED"


def test_the_window_is_titled_only_sits_at_the_modal_panel_level_and_is_run_modally(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A titled-only style mask has no close, minimise or zoom button (measured): the only ways
    out are the two buttons, Escape and the timer. The mask is the constant ITSELF — an OR with
    any other bit would be a different object. No NSAlert is built."""
    fake, _made = _fake_dialog(monkeypatch)
    from ibkr_core_mcp import _order_dialog

    _order_dialog._run_alert(_base_payload())

    init = fake.NSWindow.alloc.return_value.initWithContentRect_styleMask_backing_defer_
    assert init.call_args.args[1] is fake.NSWindowStyleMaskTitled
    window = init.return_value
    window.setLevel_.assert_called_once_with(fake.NSModalPanelWindowLevel)
    fake.NSApplication.sharedApplication.return_value.runModalForWindow_.assert_called_once_with(window)
    assert not fake.NSAlert.alloc.called
    assert capsys.readouterr().out.strip() == "CONFIRMED"


def test_the_row_is_two_equal_buttons_blue_left_red_right_centred(monkeypatch: pytest.MonkeyPatch) -> None:
    """The operator's rule: buttons CENTRED, side by side, blue then red, always. Read off the
    frames, by title: same size and baseline, 12 pt apart, the pair centred in the window."""
    fake, made = _fake_dialog(monkeypatch)
    colours: dict[tuple[float, ...], MagicMock] = {}  # one mock per rgba, so the banner's green cannot pass as red
    fake.NSColor.colorWithRed_green_blue_alpha_.side_effect = lambda *rgba: colours.setdefault(
        rgba, MagicMock(name=f"colour{rgba}")
    )
    from ibkr_core_mcp import _order_dialog

    _order_dialog._run_alert(_base_payload(confirm_label="SEND TO IBKR", abandon_label="DO NOT SEND"))

    by_title = _by_title(made)
    (bx, by, bw, bh), blue = by_title["SEND TO IBKR"]
    (rx, ry, rw, rh), red = by_title["DO NOT SEND"]
    window_w = _window_frame(fake)[2]
    assert (bw, bh) == (rw, rh) and by == ry, "two equal buttons on one baseline"
    assert bx + bw + 12 == rx, "blue left of red, 12 pt apart"
    assert bx == window_w - (rx + rw), "the pair centred in the window"
    assert _painted(blue) is fake.NSColor.systemBlueColor.return_value.CGColor.return_value
    assert _painted(red) is colours[(0.72, 0.10, 0.10, 1.0)].CGColor.return_value, (
        "the banner's own red, not the BUY green"
    )


def test_the_shape_is_the_same_at_every_height(monkeypatch: pytest.MonkeyPatch) -> None:
    """The gap's own claim: a short cancel dialog and a tall two-child bracket draw the same row.
    The detail block measured at 100 pt and at 2,000 pt gives identical button frames and window
    width; only the window's height differs."""
    from ibkr_core_mcp import _order_dialog

    seen: list[tuple[list[Any], Any]] = []
    for detail_height in (100.0, 2000.0):
        fake, made = _fake_dialog(monkeypatch)
        detail = fake.NSMutableAttributedString.alloc.return_value.init.return_value
        detail.boundingRectWithSize_options_context_.return_value.size.height = detail_height
        _order_dialog._run_alert(_base_payload())
        seen.append(([frame for frame, _button in made], _window_frame(fake)))

    (short_frames, short_window), (tall_frames, tall_window) = seen
    assert short_frames == tall_frames, "the row does not move or re-shape with the content"
    assert short_window[2] == tall_window[2], "the window keeps its width"
    assert tall_window[3] - short_window[3] == 1900.0, "only the height follows the content"


def test_the_button_titled_send_stops_the_loop_with_the_confirm_code_and_the_other_cannot(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The binding between a button's TITLE and what pressing it means, end to end: the selector
    set on the button names the target method; that method's code is what `runModalForWindow_`
    returns; `outcome_token` reads it. Swapping the two selectors made GO BACK place the order
    (the SEC-R4 lesson, 2026-09-17) — so both directions are asserted by title."""
    fake, made = _fake_dialog(monkeypatch)
    from ibkr_core_mcp import _order_dialog

    _order_dialog._run_alert(_base_payload(confirm_label="SEND TO IBKR", abandon_label="GO BACK"))
    assert capsys.readouterr().out.strip() == "CONFIRMED"  # the fake loop answered 1000

    app = fake.NSApplication.sharedApplication.return_value
    by_title = _by_title(made)

    def code_of(title: str) -> int:
        """Press the button named `title` the way AppKit would: its selector, on its target."""
        _frame, button = by_title[title]
        target = button.setTarget_.call_args.args[0]
        selector = button.setAction_.call_args.args[0]
        app.stopModalWithCode_.reset_mock()
        getattr(target, selector.replace(":", "_"))(button)  # PyObjC's selector → method name
        return int(app.stopModalWithCode_.call_args.args[0])

    assert _order_dialog.outcome_token(code_of("SEND TO IBKR")) == "CONFIRMED"
    assert _order_dialog.outcome_token(code_of("GO BACK")) == "CANCELLED"
    by_title["SEND TO IBKR"][1].setKeyEquivalent_.assert_called_once_with("")
    by_title["GO BACK"][1].setKeyEquivalent_.assert_called_once_with("\x1b")
    # "Explicit mouse click on the confirm button" (SECURITY.md § Gate 2; OWASP Transaction Authorization
    # § 1.1, WYSIWYS): with Full Keyboard Access on, Space presses the focused button, so the validating
    # button refuses keyboard focus altogether. The abandon button may take it — Space can then only abandon.
    by_title["SEND TO IBKR"][1].setRefusesFirstResponder_.assert_called_once_with(True)
    assert not by_title["GO BACK"][1].setRefusesFirstResponder_.called


def test_the_icon_is_the_hosts_file_kept_as_is_or_the_cores_own_glyph_as_a_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`icon_path` is the host's mark (`order_confirm.set_dialog_icon`), drawn as it is — a host's
    logo keeps its colours. With none, the core's own generic exchange glyph (`assets/exchange-icon.png`,
    black on transparent) is drawn as a TEMPLATE image, so AppKit tints it to the label colour in
    light and dark mode alike (operator 2026-11-07: generic, simple, Windows-compatible PNG).
    An icon is never a reason to fail a confirmation: an unreadable file falls back to the
    application's icon."""
    from ibkr_core_mcp import _order_dialog

    fake, _made = _fake_dialog(monkeypatch)
    _order_dialog._run_alert(_base_payload(icon_path="/tmp/mark.png"))
    load = fake.NSImage.alloc.return_value.initWithContentsOfFile_
    load.assert_called_once_with("/tmp/mark.png")
    image_view = fake.NSImageView.alloc.return_value.initWithFrame_.return_value
    image_view.setImage_.assert_called_once_with(load.return_value)
    assert not load.return_value.setTemplate_.called, "a host's icon keeps its own colours"

    fake, _made = _fake_dialog(monkeypatch)
    _order_dialog._run_alert(_base_payload())
    load = fake.NSImage.alloc.return_value.initWithContentsOfFile_
    load.assert_called_once_with(str(_order_dialog._DEFAULT_ICON))
    assert _order_dialog._DEFAULT_ICON.is_file(), "the core ships the glyph it draws"
    load.return_value.setTemplate_.assert_called_once_with(True)
    fake.NSImageView.alloc.return_value.initWithFrame_.return_value.setImage_.assert_called_once_with(load.return_value)

    # A host file AppKit cannot read → the core's glyph stands in (as a template); the glyph
    # unreadable too → the application's icon. Distinct mocks per path, so the test can tell.
    fake, _made = _fake_dialog(monkeypatch)
    glyph = MagicMock(name="core-glyph")
    fake.NSImage.alloc.return_value.initWithContentsOfFile_.side_effect = lambda path: (
        None if path == "/tmp/unreadable.png" else glyph
    )
    _order_dialog._run_alert(_base_payload(icon_path="/tmp/unreadable.png"))
    fake.NSImageView.alloc.return_value.initWithFrame_.return_value.setImage_.assert_called_once_with(glyph)
    glyph.setTemplate_.assert_called_once_with(True)

    for payload in (_base_payload(), _base_payload(icon_path="/tmp/unreadable.png")):
        fake, _made = _fake_dialog(monkeypatch)
        fake.NSImage.alloc.return_value.initWithContentsOfFile_.return_value = None  # nothing readable at all
        _order_dialog._run_alert(payload)
        image_view = fake.NSImageView.alloc.return_value.initWithFrame_.return_value
        image_view.setImage_.assert_called_once_with(
            fake.NSApplication.sharedApplication.return_value.applicationIconImage.return_value
        )


def test_the_default_icon_is_found_beside_the_modules_real_file_not_beside_a_symlink_to_it(
    tmp_path: Path,
) -> None:
    """Live, 2026-11-07: the first dialog after the glyph was added drew the application's icon.
    `order_confirm` runs this script by path, and under a strict editable install that path is a
    symlink in a farm snapshotted at install time — `assets/` did not exist beside the symlink.
    The glyph is looked for beside the module's REAL file, so a symlinked module still finds it."""
    from ibkr_core_mcp import _order_dialog

    real_dir = tmp_path / "real_package"
    real_dir.mkdir()
    (real_dir / "assets").mkdir()
    glyph = real_dir / "assets" / "exchange-icon.png"
    glyph.write_bytes(b"png")
    (real_dir / "_order_dialog.py").write_text("")
    farm = tmp_path / "farm"
    farm.mkdir()
    link = farm / "_order_dialog.py"
    link.symlink_to(real_dir / "_order_dialog.py")

    assert _order_dialog._default_icon(str(link)) == glyph
    assert _order_dialog._default_icon(str(real_dir / "_order_dialog.py")) == glyph, "a real path is unchanged"
    assert _order_dialog._DEFAULT_ICON.is_file(), "the core ships the glyph it draws"
