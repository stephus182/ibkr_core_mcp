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
stdout : "CONFIRMED" or "CANCELLED"
stderr : "ERROR: <msg>" on fatal failure
exit   : 0 on user decision, 1 on fatal error
"""

from __future__ import annotations

import json
import sys
from typing import Any

# Cocoa constants (kept as local int literals rather than imported from AppKit —
# these are the actual runtime values already exercised by this file; naming them
# here documents intent without adding another PyObjC-bridging dependency).
_NS_APPLICATION_ACTIVATION_POLICY_ACCESSORY = 1
_NS_BOX_CUSTOM = 4
_NS_NO_TITLE = 0
_NS_ALERT_FIRST_BUTTON_RETURN = 1000
_NS_STRING_DRAWING_USES_LINE_FRAGMENT_ORIGIN = 1  # NSStringDrawingOptions
_DIALOG_WIDTH = 420
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
        return (0.72, 0.10, 0.10), "CANCEL ORDER"  # dark red — destructive, whatever the side
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
        return (0.72, 0.10, 0.10), "SELL ORDER"
    if "BUY" in text:
        return (0.10, 0.50, 0.20), "BUY ORDER"
    return (0.55, 0.42, 0.05), "REVIEW ORDER"  # neither confirmed nor denied


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

    Layout (2026-09-11, claudia_ui gap #42): NSAlert's informative text cannot be styled,
    so the order detail and the disclaimer both live in the accessory view — the detail
    in bold above the disclaimer above the coloured banner, the reading order the dialog
    always had — and the informative text is left empty. Row heights are measured with
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
        NSMakeRect,
        NSMakeSize,
        NSModalPanelRunLoopMode,
        NSRunLoop,
        NSTextField,
        NSTimer,
        NSView,
    )

    (r, g, b), label_text = _banner(data.get("side"), data.get("action"))
    bg_color = NSColor.colorWithRed_green_blue_alpha_(r, g, b, 1.0)

    details = data.get("details", {})
    detail_text = "\n".join(f"{k}: {v}" for k, v in details.items())
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

    # Buttons: first added = rightmost = NSAlertFirstButtonReturn (1000)
    alert.addButtonWithTitle_(confirm_label)  # right
    alert.addButtonWithTitle_(abandon_label)  # left

    # No Return key on confirm (prevent accidental submission); Escape for cancel
    buttons = alert.buttons()
    buttons.objectAtIndex_(0).setKeyEquivalent_("")  # disable Return on confirm
    buttons.objectAtIndex_(1).setKeyEquivalent_("\x1b")  # Escape = cancel

    def _attributed(text: str, font: Any) -> tuple[Any, float]:
        """An attributed string in `font`, and its wrapped height at the dialog width."""
        value = NSAttributedString.alloc().initWithString_attributes_(
            text,
            {NSFontAttributeName: font, NSForegroundColorAttributeName: NSColor.labelColor()},
        )
        rect = value.boundingRectWithSize_options_context_(
            NSMakeSize(_DIALOG_WIDTH - 2 * _GAP, 10_000),
            _NS_STRING_DRAWING_USES_LINE_FRAGMENT_ORIGIN,
            None,
        )
        return value, float(rect.size.height) + 2

    def _field(value: Any, y: float, height: float) -> Any:
        """A read-only, borderless text field showing `value`."""
        field = NSTextField.alloc().initWithFrame_(NSMakeRect(_GAP, y, _DIALOG_WIDTH - 2 * _GAP, height))
        field.setAttributedStringValue_(value)
        field.setBezeled_(False)
        field.setEditable_(False)
        field.setSelectable_(False)
        field.setDrawsBackground_(False)
        return field

    # The order detail is what the human is agreeing to: bold, above the disclaimer,
    # above the banner — the reading order the dialog always had (user design
    # 2026-09-10/11, claudia_ui gap #42). Heights are measured, so long rows wrap.
    detail_value, detail_h = _attributed(detail_text, NSFont.boldSystemFontOfSize_(13))
    disclaimer_value, disclaimer_h = _attributed(disclaimer, NSFont.systemFontOfSize_(12))
    total_h = _BANNER_H + _GAP + disclaimer_h + _GAP + detail_h
    container = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, _DIALOG_WIDTH, total_h))
    # Coloured banner via NSBox, at the bottom
    box = NSBox.alloc().initWithFrame_(NSMakeRect(0, 0, _DIALOG_WIDTH, _BANNER_H))
    box.setBoxType_(_NS_BOX_CUSTOM)
    box.setFillColor_(bg_color)
    box.setBorderColor_(bg_color)
    box.setTitlePosition_(_NS_NO_TITLE)
    container.addSubview_(box)

    lbl = NSTextField.alloc().initWithFrame_(NSMakeRect(14, 12, 392, 24))
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

    # Auto-dismiss after timeout — NSApp.abortModal() returns NSModalResponseAbort (-1000).
    # Must run on the main thread: AppKit's threading rules require UI/run-loop calls there
    # (Apple Cocoa Thread Safety Summary), and NSAlert.runModal() pumps NSModalPanelRunLoopMode,
    # so the timer is scheduled directly into that mode on the current (main) run loop rather
    # than fired from a background thread.
    def _abort(_timer: Any) -> None:
        """Timer callback: abort the running modal session (counts as cancel)."""
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

    print("CONFIRMED" if response == _NS_ALERT_FIRST_BUTTON_RETURN else "CANCELLED")


if __name__ == "__main__":
    main()
