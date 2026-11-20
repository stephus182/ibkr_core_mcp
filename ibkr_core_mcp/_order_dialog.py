"""Gate 2 order confirmation dialog — AppKit subprocess runner.

Called by order_confirm._show_appkit_dialog() as a subprocess so it gets its
own main thread and can spin up NSApplication without conflicting with the host
application's asyncio event loop (e.g. the Panel/Bokeh Tornado loop in ClaudIA).
NSApplication must own the main thread; any embedding host that already runs an
event loop there would deadlock, hence the subprocess.

The dialog is the core's OWN modal window (`_build_dialog`), one layout at every height, since
2026-11-07 (claudia_ui gap #111). Until then it was an `NSAlert`, which chooses among three
layouts by its content's height and its labels' width (measured off-screen 2026-11-06): the same
bracket dialog came out with its buttons side by side at the bottom right one time and stacked
and centred the next, and the swap that put the validating button first worked on one of the
three. The operator's rule: buttons CENTRED, side by side, blue then red, always.

Protocol
--------
stdin  : JSON payload — side, action, details (dict), disclaimer, confirm_label, abandon_label,
         title, icon_path (see _build_dialog's docstring for defaults) and timeout_s (default 60,
         read by _run_alert)
stdout : one of CONFIRMED (the confirm button), CANCELLED (the abandon button or the window
         closed) or TIMED_OUT (the modal dismissed itself after timeout_s with no decision) —
         the three module constants below, which order_confirm imports so the reader and the
         writer cannot drift. Until 2026-09-29 the timeout printed CANCELLED, and a consumer
         reported an order the timeout had KEPT as cancelled (claudia_ui #67, register F21).
stderr : "ERROR: <msg>" on fatal failure
exit   : 0 on any of the three outcomes, 1 on fatal error
"""

from __future__ import annotations

import contextlib
import json
import sys
import warnings
from pathlib import Path
from typing import Any

# Cocoa constants (kept as local int literals rather than imported from AppKit —
# these are the actual runtime values already exercised by this file; naming them
# here documents intent without adding another PyObjC-bridging dependency).
_NS_APPLICATION_ACTIVATION_POLICY_ACCESSORY = 1
_NS_BOX_CUSTOM = 4
_NS_NO_TITLE = 0
_NS_WINDOW_BACKING_STORE_BUFFERED = 2
_NS_BEZEL_STYLE_ROUNDED = 1
_NS_CONTROL_SIZE_LARGE = 3
_NS_IMAGE_SCALE_PROPORTIONALLY_UP_OR_DOWN = 3
#: What the modal loop returns after `NSApp.abortModal()` — MEASURED −1001 on this machine on
#: 2026-09-29, on `NSAlert.runModal()` (a probe printing the raw response after the 3 s timer);
#: Apple documents `runModal(for:)` — the loop since 2026-11-07 — returning the same constant,
#: and by name only ("Modal session was broken with abortModal()",
#: https://developer.apple.com/documentation/appkit/nsapplication/modalresponse/abort); an
#: earlier comment here said −1000, which is NSModalResponseStop, and the first build of the
#: TIMED_OUT outcome keyed on it printed CANCELLED on the real dialog. The script therefore
#: decides from its own timer flag first and reads this value only as the second signal; the
#: timer path was seen live on the own window 2026-11-07 (TIMED_OUT after 60 s).
_NS_MODAL_RESPONSE_ABORT = -1001
#: The code each button ends the modal loop with (`stopModalWithCode_`,
#: https://developer.apple.com/documentation/appkit/nsapplication/stopmodal(withcode:): "runModal(for:)
#: returns the given returnCode"). They are the values NSAlert answered with until 2026-11-07
#: (`NSAlertFirstButtonReturn` / `NSAlertSecondButtonReturn`), kept so that `outcome_token`'s
#: reading is unchanged: 1000 is the validating button and the only code that means CONFIRMED.
_CONFIRM_CODE = 1000
_ABANDON_CODE = 1001

CONFIRMED = "CONFIRMED"
CANCELLED = "CANCELLED"
TIMED_OUT = "TIMED_OUT"


def outcome_token(response: int, *, timed_out: bool = False) -> str:
    """The word for how the modal ended: the timer, the confirm button, or anything else.

    `timed_out` is the script's own record that its auto-dismiss timer fired and called
    `NSApp.abortModal()`; it decides first, because a fact the script established beats a
    return code it has to interpret. `NSModalResponseAbort` (measured −1001) is the second
    signal, for a modal broken by `abortModal()` without the flag. `_CONFIRM_CODE` (1000) is
    what the validating button's action stops the loop with — and nothing else does. Anything
    else is a human declining: the abandon button's `_ABANDON_CODE`, 1001, or any other way
    the window was dismissed.
    Sources: https://developer.apple.com/documentation/appkit/nsapplication/abortmodal() ("return
    NSModalResponseAbort"), .../nsapplication/runmodal(for:); the abort value measured 2026-09-29.
    """
    if timed_out or response == _NS_MODAL_RESPONSE_ABORT:
        return TIMED_OUT
    if response == _CONFIRM_CODE:
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

# The one layout (claudia_ui gap #111, operator 2026-11-06): the 420-pt body inside a 452-pt
# window; two equal 150 × 32 buttons 12 pt apart, centred; a 56-pt icon over a 22-pt title.
_MARGIN = 16
_BUTTON_W, _BUTTON_H, _BUTTON_GAP = 150, 32, 12
_ICON = 56
_TITLE_H = 22


def _default_icon(module_file: str) -> Path:
    """The dialog's default icon, found beside this module's REAL file.

    A generic exchange glyph, solid black on a transparent 1024-px PNG, drawn as a template image
    (`assets/exchange-icon.svg` is its vector source, kept for a Windows `.ico`); shipped as package
    data (pyproject `[tool.setuptools.package-data]`, `scripts/verify_wheel.py` DATA_FILES). A host
    replaces it with `order_confirm.set_dialog_icon`.

    `resolve()` matters: a strict editable install runs this script through a symlink farm
    snapshotted at install time, and a directory added since is not in the farm — on 2026-11-07
    the first live dialog after the glyph was added drew the application's icon instead, because
    `__file__` named the farm's symlink and `assets/` did not exist beside it. For a wheel the
    path has no symlink and `resolve()` changes nothing.
    """
    return Path(module_file).resolve().with_name("assets") / "exchange-icon.png"


_DEFAULT_ICON = _default_icon(__file__)


def main() -> None:
    """Entry point: read the JSON payload from stdin and run the dialog it describes."""
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


class _Decision:
    """The two buttons' target: a click ends the modal loop with the code `outcome_token` reads.

    Plain Python, not an `NSObject` subclass: PyObjC forwards a control's target/action to a
    Python object by the selector's name (`confirm:` → `confirm_`; measured off-screen
    2026-11-07, claudia_ui `docs/plans/probes/2026-11-07-gate2-own-panel/`), so this module
    stays importable with no AppKit — `order_confirm` imports its tokens on every platform —
    and the chain click → code → token is tested directly.

    Lifetime, measured 2026-11-07 (claudia_ui `…/probes/2026-11-07-gate2-own-panel/probe_target_lifetime.py`):
    `NSControl.target` is weak (https://developer.apple.com/documentation/appkit/nscontrol/target)
    and points at PyObjC's proxy of this object, which lives in the autorelease pool it was made
    in — the outer, process-wide pool, which this one-shot script never recycles (AppKit's own
    per-event pools are nested and drain only their own contents). Holding the Python instance
    does NOT hold the proxy: `objc.recycleAutoreleasePool()` made a target None. Live, the real
    modal loop kept the target through a 49-second dialog and the timer fired at 60 s on another
    (claudia_ui Live Test Log, 2026-11-07). If the proxy were ever gone, a click would do nothing
    and the dialog would end as TIMED_OUT — never as CONFIRMED.
    """

    def __init__(self, app: Any) -> None:
        self._app = app

    def confirm_(self, _sender: Any) -> None:
        """The validating button: the one code that reads CONFIRMED."""
        self._app.stopModalWithCode_(_CONFIRM_CODE)

    def abandon_(self, _sender: Any) -> None:
        """The abandon button: leaves everything as it was."""
        self._app.stopModalWithCode_(_ABANDON_CODE)


def _build_dialog(data: dict[str, Any], app: Any) -> tuple[Any, _Decision]:
    """The dialog window described by `data`, built and laid out, not shown.

    Keys read from `data` (all optional):
      side, action  - the banner's colour and word (`_banner`).
      details       - dict rendered as "key: value" rows; a dict value is a titled section.
      disclaimer    - free text under the rows.
      confirm_label - the validating button's title. Default "CONFIRM".
      abandon_label - the abandon button's title. Default "GO BACK".
      title         - the heading. Default "LIVE ORDER CONFIRMATION".
      icon_path     - an image file the host application supplies (`order_confirm.set_dialog_icon`).
                      With none, or one AppKit cannot read, the application's own icon.

    One layout for every dialog — place, modify, cancel, reply, bracket — at every height
    (claudia_ui gap #111, operator 2026-11-06), top to bottom: the icon; the title; the detail
    rows (values bold, labels regular, a section's title once over its indented rows, `⚠` rows
    bold in the banner's red — claudia_ui gap #42, operator designs 2026-09-10/11, 10-17, 10-19);
    the disclaimer; the banner; and ONE row of two equal buttons centred under it, the
    validating button blue on the LEFT, the abandon button red on the RIGHT. Frames are laid
    bottom-up from measured heights (`boundingRectWithSize_options_context_` at the body width,
    so a long row wraps instead of clipping); nothing here reads the content's height to choose
    a shape.

    The window is titled with no title and no close, minimise or zoom button (a titled-only style
    mask has none — measured 2026-11-07): the ways out are the two buttons, Escape and the
    timer. `runModalForWindow_` centres it and makes it key itself
    (https://developer.apple.com/documentation/appkit/nsapplication/runmodal(for:)).

    Returns the window and the buttons' target (`_Decision`, whose docstring records what keeps
    it alive while the loop runs).
    """
    from AppKit import (
        NSAttributedString,
        NSBox,
        NSButton,
        NSColor,
        NSFont,
        NSFontAttributeName,
        NSForegroundColorAttributeName,
        NSImage,
        NSImageView,
        NSMakeRect,
        NSMakeSize,
        NSModalPanelWindowLevel,
        NSMutableAttributedString,
        NSTextAlignmentCenter,
        NSTextField,
        NSView,
        NSWindow,
        NSWindowStyleMaskTitled,
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

    def _attributed(text: str, font: Any, colour: Any = None) -> Any:
        """An attributed string in `font`; the label colour unless a colour is given."""
        return NSAttributedString.alloc().initWithString_attributes_(
            text,
            {
                NSFontAttributeName: font,
                NSForegroundColorAttributeName: NSColor.labelColor() if colour is None else colour,
            },
        )

    def _measure(value: Any) -> float:
        """The wrapped height of `value` at the body width."""
        rect = value.boundingRectWithSize_options_context_(
            NSMakeSize(_DIALOG_WIDTH - 2 * _GAP, 10_000),
            _NS_STRING_DRAWING_USES_LINE_FRAGMENT_ORIGIN,
            None,
        )
        return float(rect.size.height) + 2

    def _field(value: Any, y: float, height: float) -> Any:
        """A read-only, borderless text field showing `value`, inset in the body."""
        field = NSTextField.alloc().initWithFrame_(NSMakeRect(_MARGIN + _GAP, y, _DIALOG_WIDTH - 2 * _GAP, height))
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
    # A row whose key starts with ⚠ is a warning — label and value both bold, in the banner's
    # red: the bracket dialog's partial-fill line and the cancel dialog's linked-order rows
    # (operator, 2026-10-17). Made only when a dialog carries one, so every other dialog's
    # AppKit calls are exactly what they were.
    all_keys = [k for key, val in details.items() for k in ((key, *val) if isinstance(val, dict) else (key,))]
    warning_colour = (
        NSColor.colorWithRed_green_blue_alpha_(*_RED, 1.0) if any(str(k).startswith("⚠") for k in all_keys) else None
    )

    def _row(key: Any, val: Any, indent: str) -> None:
        colour = warning_colour if str(key).startswith("⚠") else None
        detail_value.appendAttributedString_(
            _attributed(f"{indent}{key}: ", regular if colour is None else bold, colour)
        )
        detail_value.appendAttributedString_(_attributed(str(val), bold, colour))

    # A dict value is a SECTION (the bracket dialog's Parent / Profit taker / Stop loss,
    # operator design 2026-10-19): a blank line, its title once in bold, its rows indented
    # beneath it — the shape `order_confirm._detail_lines` gives the plain renderers.
    after_section = False
    for i, (key, val) in enumerate(details.items()):
        if isinstance(val, dict):
            if i:
                detail_value.appendAttributedString_(_attributed("\n\n", regular))
            detail_value.appendAttributedString_(_attributed(str(key), bold))
            for sub_key, sub_val in val.items():
                detail_value.appendAttributedString_(_attributed("\n", regular))
                _row(sub_key, sub_val, "    ")
            after_section = True
            continue
        if i:
            detail_value.appendAttributedString_(_attributed("\n\n" if after_section else "\n", regular))
        after_section = False
        _row(key, val, "")
    detail_h = _measure(detail_value)
    disclaimer_value = _attributed(disclaimer, NSFont.systemFontOfSize_(12))
    disclaimer_h = _measure(disclaimer_value)

    # Bottom to top: the row, the banner, the disclaimer, the detail rows, the title, the icon.
    width = _DIALOG_WIDTH + 2 * _MARGIN
    y: float = _MARGIN
    body_h = _BANNER_H + _GAP + disclaimer_h + _GAP + detail_h
    total_h = y + _BUTTON_H + _MARGIN + body_h + 12 + _TITLE_H + _GAP + _ICON + _GAP
    root = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, width, total_h))

    # The row. The validating button is solid blue, the abandon button solid red, white titles.
    # The fill is the button's own LAYER, not `bezelColor`: AppKit draws a tinted bezel only
    # while the window is active, and a dialog that opened while the operator was typing in
    # another window showed white titles on grey, both buttons alike (their screenshot,
    # 2026-10-01; reproduced off-screen). Blue is the system's own; red is the banner's `_RED`
    # — `hasDestructiveAction` draws pale pink with red text, which the operator rejected.
    # Return has no key equivalent on either button (none by default — Apple's NSButton page);
    # Escape is the abandon button's. The validating button also REFUSES keyboard focus
    # (`refusesFirstResponder`, https://developer.apple.com/documentation/appkit/nscontrol/refusesfirstresponder):
    # with Full Keyboard Access on, Space presses the focused button, and a keystroke meant for
    # another window must not be able to send an order — "explicit mouse click on the confirm
    # button" (SECURITY.md § Gate 2; OWASP Transaction Authorization § 1.1, What You See Is What
    # You Sign; operator 2026-11-07). The abandon button may take focus: Space can then only abandon.
    decision = _Decision(app)
    red = NSColor.colorWithRed_green_blue_alpha_(*_RED, 1.0)
    left = (width - (2 * _BUTTON_W + _BUTTON_GAP)) / 2
    for x, label, selector, key, mouse_only, tint in (
        (left, confirm_label, "confirm:", "", True, NSColor.systemBlueColor()),
        (left + _BUTTON_W + _BUTTON_GAP, abandon_label, "abandon:", "\x1b", False, red),
    ):
        button = NSButton.alloc().initWithFrame_(NSMakeRect(x, y, _BUTTON_W, _BUTTON_H))
        button.setBezelStyle_(_NS_BEZEL_STYLE_ROUNDED)
        button.setControlSize_(_NS_CONTROL_SIZE_LARGE)
        button.setTitle_(label)
        button.setTarget_(decision)
        button.setAction_(selector)
        button.setKeyEquivalent_(key)
        if mouse_only:
            button.setRefusesFirstResponder_(True)
        button.setWantsLayer_(True)
        with warnings.catch_warnings():
            # PyObjC notes that a CGColor crosses as an untyped pointer unless the Quartz
            # bindings are installed; it is handed straight back to AppKit, which is its use.
            warnings.simplefilter("ignore")
            button.layer().setBackgroundColor_(tint.CGColor())
        button.layer().setCornerRadius_(_BUTTON_H / 2)  # the pill the system draws
        button.setAttributedTitle_(
            NSAttributedString.alloc().initWithString_attributes_(
                label,
                {NSFontAttributeName: button.font(), NSForegroundColorAttributeName: NSColor.whiteColor()},
            )
        )
        root.addSubview_(button)
    y += _BUTTON_H + _MARGIN

    # The banner: an NSBox the body's width, its word centred over the row (operator, 2026-10-01).
    box = NSBox.alloc().initWithFrame_(NSMakeRect(_MARGIN, y, _DIALOG_WIDTH, _BANNER_H))
    box.setBoxType_(_NS_BOX_CUSTOM)
    box.setFillColor_(bg_color)
    box.setBorderColor_(bg_color)
    box.setTitlePosition_(_NS_NO_TITLE)
    root.addSubview_(box)
    lbl = NSTextField.alloc().initWithFrame_(NSMakeRect(_MARGIN, y + 12, _DIALOG_WIDTH, 24))
    lbl.setAlignment_(NSTextAlignmentCenter)
    lbl.setStringValue_(label_text)
    lbl.setFont_(NSFont.boldSystemFontOfSize_(16))
    lbl.setTextColor_(NSColor.whiteColor())
    lbl.setBackgroundColor_(NSColor.clearColor())
    lbl.setBezeled_(False)
    lbl.setEditable_(False)
    lbl.setSelectable_(False)
    root.addSubview_(lbl)
    y += _BANNER_H + _GAP

    root.addSubview_(_field(disclaimer_value, y, disclaimer_h))
    y += disclaimer_h + _GAP
    root.addSubview_(_field(detail_value, y, detail_h))
    y += detail_h + 12

    heading = NSTextField.alloc().initWithFrame_(NSMakeRect(0, y, width, _TITLE_H))
    heading.setAlignment_(NSTextAlignmentCenter)
    heading.setStringValue_(title)
    heading.setFont_(NSFont.boldSystemFontOfSize_(15))
    heading.setBezeled_(False)
    heading.setEditable_(False)
    heading.setSelectable_(False)
    heading.setDrawsBackground_(False)
    root.addSubview_(heading)
    y += _TITLE_H + _GAP

    # The host's own mark where it set one, drawn as it is (a logo keeps its colours); else the
    # core's generic exchange glyph as a TEMPLATE image, which AppKit tints to the label colour
    # in light and dark mode alike (operator 2026-11-07: generic, simple, a PNG for Windows too).
    # An unreadable file answers None and the next one stands in, the application's icon last:
    # an icon is never a reason to fail a confirmation.
    icon_path = data.get("icon_path")
    icon = NSImage.alloc().initWithContentsOfFile_(str(icon_path)) if icon_path else None
    if icon is None:
        icon = NSImage.alloc().initWithContentsOfFile_(str(_DEFAULT_ICON))
        if icon is not None:
            icon.setTemplate_(True)
    if icon is None:
        icon = app.applicationIconImage()
    image = NSImageView.alloc().initWithFrame_(NSMakeRect((width - _ICON) / 2, y, _ICON, _ICON))
    image.setImage_(icon)
    image.setImageScaling_(_NS_IMAGE_SCALE_PROPORTIONALLY_UP_OR_DOWN)
    root.addSubview_(image)

    window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(0, 0, width, total_h), NSWindowStyleMaskTitled, _NS_WINDOW_BACKING_STORE_BUFFERED, False
    )
    window.setContentView_(root)
    window.setLevel_(NSModalPanelWindowLevel)  # over other windows, as an alert's panel is
    return window, decision


def _run_alert(data: dict[str, Any]) -> None:
    """Build the dialog described by `data`, run it app-modally, print how it ended.

    `timeout_s` (default 60) is the one key read here: the seconds before the modal dismisses
    itself, reported as TIMED_OUT — its own outcome, never a decision. The rest of the payload
    is `_build_dialog`'s.

    Prints CONFIRMED, CANCELLED or TIMED_OUT to stdout (`outcome_token`); never raises for
    user input, only for a genuinely broken AppKit call (caught by main()'s caller).
    """
    from AppKit import NSApplication, NSModalPanelRunLoopMode, NSRunLoop, NSTimer

    timeout_s = int(data.get("timeout_s", 60))

    # Initialize NSApplication as an accessory app (no Dock icon, no menu bar)
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(_NS_APPLICATION_ACTIVATION_POLICY_ACCESSORY)
    window, _decision = _build_dialog(data, app)  # the target's lifetime: `_Decision`'s docstring

    # Auto-dismiss after timeout — NSApp.abortModal() returns NSModalResponseAbort.
    # Must run on the main thread: AppKit's threading rules require UI/run-loop calls there
    # (Apple Cocoa Thread Safety Summary), and runModalForWindow_ pumps NSModalPanelRunLoopMode —
    # "it does not perform any tasks (such as firing timers) that are not associated with the
    # modal run loop" (Apple, runModal(for:)) — so the timer is scheduled directly into that
    # mode on the current (main) run loop rather than fired from a background thread.
    fired = {"timeout": False}

    def _abort(_timer: Any) -> None:
        """Timer callback: record that the timer fired, then abort the modal — reported as TIMED_OUT."""
        fired["timeout"] = True
        with contextlib.suppress(Exception):  # best-effort abort; the modal may already be gone
            app.abortModal()

    abort_timer = NSTimer.timerWithTimeInterval_repeats_block_(timeout_s, False, _abort)
    NSRunLoop.currentRunLoop().addTimer_forMode_(abort_timer, NSModalPanelRunLoopMode)

    app.activateIgnoringOtherApps_(True)
    response = app.runModalForWindow_(window)
    abort_timer.invalidate()

    print(outcome_token(response, timed_out=fired["timeout"]))


if __name__ == "__main__":
    main()
