"""Gate 2 order confirmation dialog — AppKit subprocess runner.

Called by order_confirm._show_appkit_dialog() as a subprocess so it gets its
own main thread and can spin up NSApplication without conflicting with the
Chainlit asyncio event loop.

Protocol
--------
stdin  : JSON payload (see _run_alert for keys)
stdout : "CONFIRMED" or "CANCELLED"
stderr : "ERROR: <msg>" on fatal failure
exit   : 0 on user decision, 1 on fatal error
"""
from __future__ import annotations

import json
import sys
import threading


def main() -> None:
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


def _run_alert(data: dict) -> None:
    from AppKit import (  # type: ignore[import]
        NSAlert,
        NSApplication,
        NSBox,
        NSColor,
        NSFont,
        NSMakeRect,
        NSTextField,
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
    app.setActivationPolicy_(1)  # NSApplicationActivationPolicyAccessory

    alert = NSAlert.alloc().init()
    alert.setMessageText_(title)
    alert.setInformativeText_(f"{detail_text}\n\n{disclaimer}")

    # Buttons: first added = rightmost = NSAlertFirstButtonReturn (1000)
    alert.addButtonWithTitle_(confirm_label)  # right
    alert.addButtonWithTitle_("CANCEL")       # left

    # No Return key on confirm (prevent accidental submission); Escape for cancel
    buttons = alert.buttons()
    buttons.objectAtIndex_(0).setKeyEquivalent_("")       # disable Return on confirm
    buttons.objectAtIndex_(1).setKeyEquivalent_("\x1b")  # Escape = cancel

    # Colored banner via NSBox (NSBoxCustom = 4, NSNoTitle = 0)
    container = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 420, 48))
    box = NSBox.alloc().initWithFrame_(NSMakeRect(0, 0, 420, 48))
    box.setBoxType_(4)
    box.setFillColor_(bg_color)
    box.setBorderColor_(bg_color)
    box.setTitlePosition_(0)
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

    # Auto-dismiss after timeout — NSApp.abortModal() returns NSModalResponseAbort (-1000)
    def _abort() -> None:
        try:
            from AppKit import NSApp  # type: ignore[import]
            NSApp.abortModal()
        except Exception:
            pass

    timer = threading.Timer(timeout_s, _abort)
    timer.daemon = True
    timer.start()

    app.activateIgnoringOtherApps_(True)
    response = alert.runModal()
    timer.cancel()

    # NSAlertFirstButtonReturn = 1000
    print("CONFIRMED" if response == 1000 else "CANCELLED")


if __name__ == "__main__":
    main()
