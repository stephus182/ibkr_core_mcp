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

    side = str(data.get("side", "BUY")).upper()
    is_sell = any(k in side for k in ("SELL", "SHORT"))

    if is_sell:
        r, g, b = 0.72, 0.10, 0.10  # dark red
        label_text = "SELL ORDER"
    else:
        r, g, b = 0.10, 0.50, 0.20  # dark green
        label_text = "BUY ORDER"

    bg_color = NSColor.colorWithRed_green_blue_alpha_(r, g, b, 1.0)

    details = data.get("details", {})
    detail_text = "\n".join(f"{k}: {v}" for k, v in details.items())
    disclaimer = data.get("disclaimer", "")
    confirm_label = data.get("confirm_label", "CONFIRM")
    title = data.get("title", "LIVE ORDER CONFIRMATION")
    timeout_s = int(data.get("timeout_s", 60))

    # Initialize NSApplication as an accessory app (no Dock icon, no menu bar)
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(_NS_APPLICATION_ACTIVATION_POLICY_ACCESSORY)

    alert = NSAlert.alloc().init()
    alert.setMessageText_(title)
    alert.setInformativeText_(f"{detail_text}\n\n{disclaimer}")

    # Buttons: first added = rightmost = NSAlertFirstButtonReturn (1000)
    alert.addButtonWithTitle_(confirm_label)  # right
    alert.addButtonWithTitle_("CANCEL")  # left

    # No Return key on confirm (prevent accidental submission); Escape for cancel
    buttons = alert.buttons()
    buttons.objectAtIndex_(0).setKeyEquivalent_("")  # disable Return on confirm
    buttons.objectAtIndex_(1).setKeyEquivalent_("\x1b")  # Escape = cancel

    # Colored banner via NSBox
    container = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 420, 48))
    box = NSBox.alloc().initWithFrame_(NSMakeRect(0, 0, 420, 48))
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
        except Exception:
            pass

    abort_timer = NSTimer.timerWithTimeInterval_repeats_block_(timeout_s, False, _abort)
    NSRunLoop.currentRunLoop().addTimer_forMode_(abort_timer, NSModalPanelRunLoopMode)

    app.activateIgnoringOtherApps_(True)
    response = alert.runModal()
    abort_timer.invalidate()

    print("CONFIRMED" if response == _NS_ALERT_FIRST_BUTTON_RETURN else "CANCELLED")


if __name__ == "__main__":
    main()
