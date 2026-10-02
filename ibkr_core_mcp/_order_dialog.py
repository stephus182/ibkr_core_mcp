"""Gate 2 order confirmation dialog — AppKit subprocess runner.

Called by order_confirm._show_appkit_dialog() as a subprocess so it gets its
own main thread and can spin up NSApplication without conflicting with the host
application's asyncio event loop (e.g. the Panel/Bokeh Tornado loop in ClaudIA).
NSApplication must own the main thread; any embedding host that already runs an
event loop there would deadlock, hence the subprocess.

Protocol
--------
stdin  : JSON payload — side, details (dict), disclaimer, confirm_label, title,
         timeout_s (see _run_alert's docstring for defaults)
stdout : one of CONFIRMED (the confirm button), CANCELLED (the abandon button or the window
         closed) or TIMED_OUT (the modal dismissed itself after timeout_s with no decision) —
         the three module constants below, which order_confirm imports so the reader and the
         writer cannot drift. Until 2026-09-29 the timeout printed CANCELLED, and a consumer
         reported an order the timeout had KEPT as cancelled (claudia_ui #67, register F21).
stderr : "ERROR: <msg>" on fatal failure
exit   : 0 on any of the three outcomes, 1 on fatal error
"""

from __future__ import annotations

import json
import sys
import warnings
from typing import Any

# Cocoa constants (kept as local int literals rather than imported from AppKit —
# these are the actual runtime values already exercised by this file; naming them
# here documents intent without adding another PyObjC-bridging dependency).
_NS_APPLICATION_ACTIVATION_POLICY_ACCESSORY = 1
_NS_BOX_CUSTOM = 4
_NS_NO_TITLE = 0
_NS_ALERT_FIRST_BUTTON_RETURN = 1000
#: What `runModal()` returns after `NSApp.abortModal()` — MEASURED −1001 on this machine on
#: 2026-09-29 (a probe printing the raw response after the 3 s timer). Apple documents the
#: constant by name only ("Modal session was broken with abortModal()",
#: https://developer.apple.com/documentation/appkit/nsapplication/modalresponse/abort); an
#: earlier comment here said −1000, which is NSModalResponseStop, and the first build of the
#: TIMED_OUT outcome keyed on it printed CANCELLED on the real dialog. The script therefore
#: decides from its own timer flag first and reads this value only as the second signal.
_NS_MODAL_RESPONSE_ABORT = -1001

CONFIRMED = "CONFIRMED"
CANCELLED = "CANCELLED"
TIMED_OUT = "TIMED_OUT"


def outcome_token(response: int, *, timed_out: bool = False) -> str:
    """The word for how the modal ended: the timer, the confirm button, or anything else.

    `timed_out` is the script's own record that its auto-dismiss timer fired and called
    `NSApp.abortModal()`; it decides first, because a fact the script established beats a
    return code it has to interpret. `NSModalResponseAbort` (measured −1001) is the second
    signal, for a modal broken by `abortModal()` without the flag. `NSAlertFirstButtonReturn`
    (1000) is the first button — always the confirm button here. Anything else is a human
    declining: the second (abandon) button, 1001, or any other way the panel was dismissed.
    Sources: https://developer.apple.com/documentation/appkit/nsapplication/abortmodal() ("return
    NSModalResponseAbort"), .../modalresponse/alertfirstbuttonreturn; the value measured 2026-09-29.
    """
    if timed_out or response == _NS_MODAL_RESPONSE_ABORT:
        return TIMED_OUT
    if response == _NS_ALERT_FIRST_BUTTON_RETURN:
        return CONFIRMED
    return CANCELLED


_NS_STRING_DRAWING_USES_LINE_FRAGMENT_ORIGIN = 1  # NSStringDrawingOptions
_DIALOG_WIDTH = 420

# The one red of this dialog: the SELL and CANCEL banners and a discarding button. The operator
# asked for the button's red to match the banner's (2026-10-01), and preferred this one to
# IBKR's own #D91222 and to the system red after seeing each on the rendered dialog.
_RED = (0.72, 0.10, 0.10)

# What a button's colour says (register F6, settled by the operator on these dialogs,
# 2026-10-01): on every dialog the button that VALIDATES the action is blue and the button that
# DISCARDS it is red — go ahead, or back out — and the banner says what the action is. A first
# version coloured by consequence (a red `CANCEL ORDER` beside a grey `KEEP ORDER`) and read as
# "ambiguous". It is one rule for every dialog, so it is not a setting.
_BANNER_H = 48
_GAP = 8


def main() -> None:
    """Entry point: read the JSON payload from stdin and run the alert it describes."""
    try:
        data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, OSError) as exc:
        print(f"ERROR: bad payload — {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        _run_alert(data)
    except SystemExit:
        raise
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


def _banner(side: str | None, action: str | None) -> tuple[tuple[float, float, float], str]:
    """The banner's colour and text: the ACTION being authorised, else the order's side.

    The banner is the largest, most pre-attentive element on the dialog, and until
    2026-09-10 it could only say a side. With the side finally readable on the typed rows
    (claudia_ui gap #40), a cancel dialog titled CANCEL ORDER CONFIRMATION rendered a
    confident green "BUY ORDER" — the cue said the opposite of the act being authorised
    (gap #42, read live). An action therefore wins over the side: what is being authorised
    is the cancel, not the buy, and the side is already on the rows as `Action:`. Modify
    states its action in the text and keeps the order's colour (user decision 2026-09-10).

    Side still decides the *place* dialog, and stays three-valued on purpose:
    `data.get("side", "BUY")` once made the DEFAULT a confident green "BUY ORDER", so
    cancel and reply dialogs — which carry no side — and every SELL modify rendered as a
    buy. An unstated side has to look unstated.

    Args:
        side: The order's side, or None where the caller established none.
        action: The action being authorised ("CANCEL", "MODIFY"), or None for a placement.

    Returns:
        ((red, green, blue), banner text).
    """
    act = str(action or "").strip().upper()
    if act == "CANCEL":
        return _RED, "CANCEL ORDER"  # destructive, whatever the side
    if act == "MODIFY":
        # The text states the action; the colour follows the order's side, as IB does
        # (user decision 2026-09-10 23:20 — the amber shipped that evening was wrong by
        # decision, not by defect). An unstated side still looks unstated.
        colour, _ = _side_colour(side)
        return colour, "MODIFY ORDER"
    return _side_colour(side)


def _side_colour(side: str | None) -> tuple[tuple[float, float, float], str]:
    """The order's colour and side word: green BUY, red SELL, amber when unstated.

    Three-valued on purpose — `data.get("side", "BUY")` once made the DEFAULT a confident
    green, so dialogs with no side rendered as buys. An unstated side has to look unstated.
    Shared by the place dialog (which shows the side word) and the modify banner (which
    shows only the colour), so the two cannot disagree about what a side looks like.
    """
    text = str(side).upper() if side is not None else ""
    if any(k in text for k in ("SELL", "SHORT")):
        return _RED, "SELL ORDER"
    if "BUY" in text:
        return (0.10, 0.50, 0.20), "BUY ORDER"
    # A caution yellow (operator, 2026-10-01): the first amber, (0.55, 0.42, 0.05), was "not a
    # good color" on the rendered dialog; this one, a shade darker than the first yellow tried.
    return (0.90, 0.72, 0.00), "REVIEW ORDER"  # neither confirmed nor denied


def _run_alert(data: dict[str, Any]) -> None:
    """Build and run the app-modal NSAlert described by `data`.

    Keys read from `data` (all optional except where noted):
      side          - "BUY"/"SELL"/etc; anything containing SELL or SHORT gets
                       the red banner, everything else gets the green one.
      details       - dict rendered as "key: value" lines in the alert body.
      disclaimer    - free text appended after the details.
      confirm_label - text for the right-hand (confirm) button. Default "CONFIRM".
      title         - alert message text. Default "LIVE ORDER CONFIRMATION".
      icon_path     - an image file the host application supplies as the alert's icon. With
                       none, or one AppKit cannot read, the alert keeps its default icon.
      timeout_s     - seconds before the modal dismisses itself. Reported as TIMED_OUT —
                       its own outcome, never a decision. Default 60.

    Prints CONFIRMED, CANCELLED or TIMED_OUT to stdout (`outcome_token`); never raises for
    user input, only for a genuinely broken AppKit call (caught by main()'s caller).

    Layout (2026-09-11, claudia_ui gap #42): NSAlert's informative text cannot be styled,
    so the order detail and the disclaimer both live in the accessory view — the detail
    rows with their values in bold and labels regular, above the disclaimer, above the
    coloured banner: the reading order the dialog always had — and the informative text
    is left empty. Row heights are measured with
    `boundingRectWithSize_options_context_` at the dialog width, so a long row such as
    `Currently at IBKR: …` wraps instead of clipping.
    """
    from AppKit import (
        NSAlert,
        NSApplication,
        NSAttributedString,
        NSBox,
        NSColor,
        NSFont,
        NSFontAttributeName,
        NSForegroundColorAttributeName,
        NSImage,
        NSMakeRect,
        NSMakeSize,
        NSModalPanelRunLoopMode,
        NSMutableAttributedString,
        NSRunLoop,
        NSTextAlignmentCenter,
        NSTextField,
        NSTimer,
        NSView,
    )

    (r, g, b), label_text = _banner(data.get("side"), data.get("action"))
    bg_color = NSColor.colorWithRed_green_blue_alpha_(r, g, b, 1.0)

    details = data.get("details", {})
    disclaimer = data.get("disclaimer", "")
    confirm_label = data.get("confirm_label", "CONFIRM")
    # Default is deliberately NOT "CANCEL": this button sits beside confirm_label, and on the
    # cancel dialog "CANCEL" vs "CANCEL ORDER" meant abandon-vs-perform with the same first
    # word (found live 2026-08-13). A missing key must not be able to recreate that collision.
    abandon_label = data.get("abandon_label", "GO BACK")
    title = data.get("title", "LIVE ORDER CONFIRMATION")
    timeout_s = int(data.get("timeout_s", 60))

    # Initialize NSApplication as an accessory app (no Dock icon, no menu bar)
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(_NS_APPLICATION_ACTIVATION_POLICY_ACCESSORY)

    alert = NSAlert.alloc().init()
    alert.setMessageText_(title)
    alert.setInformativeText_("")
    # The host's own mark, where it set one (`order_confirm.set_dialog_icon`). This package
    # ships none. An unreadable file answers None and the default icon stays: an icon is never
    # a reason to fail a confirmation. Size and position stay the system's.
    icon_path = data.get("icon_path")
    if icon_path:
        icon = NSImage.alloc().initWithContentsOfFile_(str(icon_path))
        if icon is not None:
            alert.setIcon_(icon)

    # Buttons: first added = rightmost = NSAlertFirstButtonReturn (1000)
    alert.addButtonWithTitle_(confirm_label)  # right
    alert.addButtonWithTitle_(abandon_label)  # left

    # No Return key on confirm (prevent accidental submission); Escape for cancel
    buttons = alert.buttons()
    buttons.objectAtIndex_(0).setKeyEquivalent_("")  # disable Return on confirm
    buttons.objectAtIndex_(1).setKeyEquivalent_("\x1b")  # Escape = cancel

    def _attributed(text: str, font: Any) -> Any:
        """An attributed string in `font`, in the label colour."""
        return NSAttributedString.alloc().initWithString_attributes_(
            text,
            {NSFontAttributeName: font, NSForegroundColorAttributeName: NSColor.labelColor()},
        )

    def _measure(value: Any) -> float:
        """The wrapped height of `value` at the dialog width."""
        rect = value.boundingRectWithSize_options_context_(
            NSMakeSize(_DIALOG_WIDTH - 2 * _GAP, 10_000),
            _NS_STRING_DRAWING_USES_LINE_FRAGMENT_ORIGIN,
            None,
        )
        return float(rect.size.height) + 2

    def _field(value: Any, y: float, height: float) -> Any:
        """A read-only, borderless text field showing `value`."""
        field = NSTextField.alloc().initWithFrame_(NSMakeRect(_GAP, y, _DIALOG_WIDTH - 2 * _GAP, height))
        field.setAttributedStringValue_(value)
        field.setBezeled_(False)
        field.setEditable_(False)
        field.setSelectable_(False)
        field.setDrawsBackground_(False)
        return field

    # The order detail is what the human is agreeing to (user design 2026-09-10/11,
    # claudia_ui gap #42): values bold, labels regular — each row two runs, joined by
    # regular newlines and measured as one block so long rows wrap — above the
    # disclaimer, above the banner: the reading order the dialog always had.
    regular, bold = NSFont.systemFontOfSize_(13), NSFont.boldSystemFontOfSize_(13)
    detail_value = NSMutableAttributedString.alloc().init()
    for i, (key, val) in enumerate(details.items()):
        if i:
            detail_value.appendAttributedString_(_attributed("\n", regular))
        detail_value.appendAttributedString_(_attributed(f"{key}: ", regular))
        detail_value.appendAttributedString_(_attributed(str(val), bold))
    detail_h = _measure(detail_value)
    disclaimer_value = _attributed(disclaimer, NSFont.systemFontOfSize_(12))
    disclaimer_h = _measure(disclaimer_value)
    total_h = _BANNER_H + _GAP + disclaimer_h + _GAP + detail_h
    container = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, _DIALOG_WIDTH, total_h))
    # Coloured banner via NSBox, at the bottom
    box = NSBox.alloc().initWithFrame_(NSMakeRect(0, 0, _DIALOG_WIDTH, _BANNER_H))
    box.setBoxType_(_NS_BOX_CUSTOM)
    box.setFillColor_(bg_color)
    box.setBorderColor_(bg_color)
    box.setTitlePosition_(_NS_NO_TITLE)
    container.addSubview_(box)

    # Centred across the dialog, over the buttons below it (operator, 2026-10-01).
    lbl = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 12, _DIALOG_WIDTH, 24))
    lbl.setAlignment_(NSTextAlignmentCenter)
    lbl.setStringValue_(label_text)
    lbl.setFont_(NSFont.boldSystemFontOfSize_(16))
    lbl.setTextColor_(NSColor.whiteColor())
    lbl.setBackgroundColor_(NSColor.clearColor())
    lbl.setBezeled_(False)
    lbl.setEditable_(False)
    lbl.setSelectable_(False)
    container.addSubview_(lbl)

    container.addSubview_(_field(disclaimer_value, _BANNER_H + _GAP, disclaimer_h))
    container.addSubview_(_field(detail_value, _BANNER_H + _GAP + disclaimer_h + _GAP, detail_h))
    alert.setAccessoryView_(container)

    # The confirm button is solid blue, the abandon button solid red, white titles. Applied AFTER
    # `layout()` — measured off-screen on macOS 27, a title set before it did not survive.
    #
    # The fill is the button's own LAYER, not `bezelColor`. AppKit draws a tinted bezel only
    # while the window is active: a dialog that opened while the operator was typing in
    # another window showed white titles on grey, both buttons alike (their screenshot,
    # 2026-10-01; reproduced off-screen). A layer's background does not depend on that. Blue
    # is the system's own; red is the banner's `_RED` — `hasDestructiveAction` draws pale pink
    # with red text, which the operator rejected. Return stays disabled on the confirm button
    # on purpose.
    alert.layout()

    # The validating button comes FIRST in its row, whichever way the system lays the row out
    # (operator, 2026-10-01). Measured on macOS 27: stacked, the row is already arranged
    # confirm-first (on top); side by side it is arranged abandon-first, so `VALIDATE` /
    # `DISCARD` came out as DISCARD, VALIDATE. Moved within the row the alert built, never
    # re-added, so the button that reports CONFIRMED is unchanged. A row built some other way
    # (another macOS) is left as it is: the order is a nicety, and nothing here may fail a
    # confirmation.
    try:
        confirm_button = alert.buttons().objectAtIndex_(0)
        row = confirm_button.superview()
        if next(iter(row.arrangedSubviews())) is not confirm_button:
            row.insertArrangedSubview_atIndex_(confirm_button, 0)
    except Exception:  # noqa: S110 - best-effort ordering; the dialog runs either way
        pass

    for index, label, tint in (
        (0, confirm_label, NSColor.systemBlueColor()),
        (1, abandon_label, NSColor.colorWithRed_green_blue_alpha_(*_RED, 1.0)),
    ):
        button = alert.buttons().objectAtIndex_(index)
        button.setWantsLayer_(True)
        with warnings.catch_warnings():
            # PyObjC notes that a CGColor crosses as an untyped pointer unless the Quartz
            # bindings are installed; it is handed straight back to AppKit, which is its use.
            warnings.simplefilter("ignore")
            button.layer().setBackgroundColor_(tint.CGColor())
        button.layer().setCornerRadius_(button.frame().size.height / 2)  # the pill the system draws
        button.setAttributedTitle_(
            NSAttributedString.alloc().initWithString_attributes_(
                label,
                {NSFontAttributeName: button.font(), NSForegroundColorAttributeName: NSColor.whiteColor()},
            )
        )

    # Auto-dismiss after timeout — NSApp.abortModal() returns NSModalResponseAbort (-1000).
    # Must run on the main thread: AppKit's threading rules require UI/run-loop calls there
    # (Apple Cocoa Thread Safety Summary), and NSAlert.runModal() pumps NSModalPanelRunLoopMode,
    # so the timer is scheduled directly into that mode on the current (main) run loop rather
    # than fired from a background thread.
    fired = {"timeout": False}

    def _abort(_timer: Any) -> None:
        """Timer callback: record that the timer fired, then abort the modal — reported as TIMED_OUT."""
        fired["timeout"] = True
        try:
            from AppKit import NSApp

            NSApp.abortModal()
        except Exception:  # noqa: S110 - best-effort abort; the modal may already be gone
            pass

    abort_timer = NSTimer.timerWithTimeInterval_repeats_block_(timeout_s, False, _abort)
    NSRunLoop.currentRunLoop().addTimer_forMode_(abort_timer, NSModalPanelRunLoopMode)

    app.activateIgnoringOtherApps_(True)
    response = alert.runModal()
    abort_timer.invalidate()

    print(outcome_token(response, timed_out=fired["timeout"]))


if __name__ == "__main__":
    main()
