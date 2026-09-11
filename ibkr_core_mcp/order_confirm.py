"""Gate 2 of the order-write security model: visual order confirmation.

After Touch ID (Gate 1, `human_auth.py`) succeeds, the user is shown a modal dialog
carrying the full order details and a live-order disclaimer, and must click to
confirm. The Enter key deliberately does not confirm — the gate exists to defeat
reflexive acceptance, so it requires a pointed, explicit action. Any cancellation
or timeout raises `HumanAuthError` and the IBKR endpoint is never contacted.

Three backends, tried in order: an AppKit `NSAlert` run in a subprocess (colour-coded
by side; see `_order_dialog.py` for why it must be a subprocess), a tkinter modal,
and an AppleScript `display dialog` fallback. A host with none of them available
fails closed rather than proceeding unconfirmed.
"""

from __future__ import annotations

import contextlib
import html
import json as _json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    import tkinter as tk
except ImportError:  # Python without Tk support (CI, headless, Python 3.14 Homebrew)
    tk = None  # type: ignore[assignment]
from ibkr_core_mcp.exceptions import HumanAuthError

_DIALOG_TIMEOUT_S = 60  # auto-cancels if unattended


def _quantity_text(qty: Any) -> str:
    """The order's quantity as a human writes it.

    IBKR's order status reports `size` as a string — `'1.0'` for one contract — so the
    cancel dialog showed `Quantity: 1.0` while the modify dialog, fed from the proposal,
    showed `1` (claudia_ui gap #42, read live 2026-09-10). Anything unparseable is shown
    unchanged rather than guessed at.

    Args:
        qty: The quantity from a proposal or from an IBKR status row.

    Returns:
        The quantity as text, without a trailing `.0`.
    """
    try:
        value = float(qty)
    except (TypeError, ValueError):
        return str(qty)
    return str(int(value)) if value.is_integer() else str(value)


def _order_rows(order: dict[str, Any], account_id: str) -> dict[str, str]:
    """The typed rows every Gate 2 dialog shows for an order (place, modify, cancel).

    `order` is an IBKR-shaped body plus the display-only `_`-prefixed keys the callers add
    (`_companyName`, `_multiplier`, `_multiplier_unknown`, `_currency`). Raw body keys never
    reach the screen: until 2026-09-10 the modify and cancel dialogs forwarded their dict
    verbatim — `orderType`, `manualIndicator: True`, `limit_price: None`, a reason blob, the
    order id twice — so the last human-readable surface before an irreversible action was
    the least legible one (claudia_ui gap #40).
    """
    symbol = order.get("ticker", order.get("symbol", "UNKNOWN"))
    company_name = order.get("_companyName", order.get("companyName", ""))
    symbol_str = f"{symbol} — {company_name}" if company_name else symbol
    # IBKR-shaped bodies say `side`; a live-order dict from another caller may say
    # `Side`; a pre-built row set says `Action`. All three feed the banner colour.
    side = order.get("side", order.get("Side", order.get("Action", "?")))
    qty = order.get("quantity", "?")
    order_type = order.get("orderType", order.get("order_type", "MARKET"))
    price = order.get("price")
    aux_price = order.get("auxPrice")
    tif = order.get("tif", order.get("timeInForce", "DAY"))
    multiplier = order.get("_multiplier")
    # Currency is displayed only when the caller established one, and always as an ISO
    # code. Until 2026-08-13 this rendered f"${price}" and a hardcoded "USD": "$" is
    # shared by USD/MXN/CAD/AUD/HKD/SGD, and this account holds EUR-denominated equities,
    # so the last surface before an irreversible action asserted a currency nothing had
    # established. A wrong-currency price is dangerous precisely because it reads as
    # ordinary. No currency in the order means no currency shown — never a guess.
    currency = str(order.get("_currency") or order.get("currency") or "").strip().upper()
    ccy = f" {currency}" if currency else ""
    # The same formatter as the Changes row, so one dialog cannot show one number two
    # ways: live 2026-09-10 it read `Price: 6945.0 USD` four lines above
    # `limit price 6,995.00 → 6,945.00` (claudia_ui gap #46).
    # A futures price is quoted in the contract's own units — index points for ES — not
    # in currency; the money figure is the multiplied total. `Price: 7,900.00 USD` was wrong
    # (user, 2026-09-11). No unit is printed rather than a guessed one: no IB field names
    # the quotation unit, and "points" would be wrong for crude or a bond future.
    is_future = multiplier is not None or bool(order.get("_multiplier_unknown"))
    price_ccy = "" if is_future else ccy
    price_str = f"{change_value_text('limit_price', price)}{price_ccy}" if price is not None else "MARKET"
    try:
        if order.get("_multiplier_unknown"):
            # A futures order whose multiplier the caller could not learn. price × qty here
            # is not an estimate, it is wrong by the multiplier — live 2026-09-04 it printed
            # 7,735.00 for one ES contract standing for 386,750 USD. Say so instead.
            total_str = "— (contract multiplier unknown; not price × quantity)"
        elif price is not None and multiplier is not None:
            # Futures: notional = price × qty × multiplier
            notional = float(price) * float(qty) * float(multiplier)
            total_str = f"{notional:,.2f}{ccy} (×{multiplier:g} multiplier)"
        elif price is not None:
            total_str = f"{float(price) * float(qty):,.2f}{ccy}"
        else:
            total_str = "Market"
    except (TypeError, ValueError):
        total_str = "—"
    rows = {
        "Account": account_id,
        "Action": side,
        "Symbol": symbol_str,
        "Quantity": _quantity_text(qty),
        "Order Type": order_type,
        "Price": price_str,
    }
    if aux_price is not None:
        # A stop-limit's trigger lives in auxPrice; no dialog showed it before 2026-09-10.
        rows["Stop"] = f"{change_value_text('stop_price', aux_price)}{price_ccy}"
    rows["TIF"] = tif
    # The outside-RTH attribute decides WHEN a stop on a US future can trigger (IBKR
    # simulates those stops and fires them only in RTH unless it is set), so it belongs on
    # the last screen before the send. Shown only when the caller sent it — an absent
    # attribute means IBKR's default applies, and the dialog claims nothing it was not
    # given (2026-09-04).
    if isinstance(order.get("outsideRTH"), bool):  # a present None is not a value
        rows["Outside RTH"] = "Yes" if order["outsideRTH"] else "No"
    rows["Total (est.)"] = total_str
    return rows


# Proposal field → the replacement-body key(s) carrying its new value, first present wins.
# `stop_price` sits in `auxPrice` on a stop-limit and in `price` on a plain stop (IBKR's
# field spec; see claudia_ui order_flow's body construction).
_CHANGE_FIELD_KEYS: dict[str, tuple[str, ...]] = {
    "limit_price": ("price",),
    "stop_price": ("auxPrice", "price"),
    "quantity": ("quantity",),
    "tif": ("tif",),
    "order_type": ("orderType",),
    "outside_rth": ("outsideRTH",),
    "action": ("side",),
}


def _yes_no(value: Any) -> Any:
    """Booleans read as Yes/No on a dialog; every other value passes through."""
    return ("Yes" if value else "No") if isinstance(value, bool) else value


_PRICE_CHANGE_FIELDS = ("limit_price", "stop_price")


def change_value_text(field: str, value: Any) -> str:
    """One rendering of a changed field's value, shared by every surface that shows a diff.

    A diff exists to be compared at a glance, so the two sides of the arrow have to be
    formatted alike. Until 2026-09-10 they were not: on order 1793215935 one stop-price
    change rendered as `stop_price: 7900.0 -> 7950` in the chat card and `stop price
    7900.0 -> 7950.0` on Gate 2, because each surface printed whatever type the value
    happened to arrive as — a float from the proposal's `previous_value`, an int from the
    model's replacement. Public so claudia_ui's approval text uses this definition rather
    than a third copy, the same reason `reply_message_text` is public.

    Prices take the thousands-and-two-decimals form the rest of the approval text already
    uses; a whole quantity loses its `.0`; booleans read Yes/No; None renders `?` rather
    than the string "None", matching `_format_changes`'s rule that an unknown is never a
    guess.

    Args:
        field: The changed field's name, from `propose_modify`'s `changes[].field` enum.
        value: That field's value, before or after.

    Returns:
        The value as it should appear on a dialog or in the approval text.
    """
    if value is None:
        return "?"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if field in _PRICE_CHANGE_FIELDS:
        try:
            return f"{float(value):,.2f}"
        except (TypeError, ValueError):
            return str(value)
    if field == "quantity":
        return _quantity_text(value)
    return str(value)


def _format_changes(order: dict[str, Any]) -> str:
    """Render `order["_changes"]` as one `<field> <previous> → <new>` line per entry, "" if none.

    The new value is read from the replacement body itself, so the row can never disagree
    with what is about to be sent; an unknown field renders `?` rather than a guess.
    """
    lines: list[str] = []
    for change in order.get("_changes") or []:
        if not isinstance(change, dict) or not change.get("field"):
            continue
        field = str(change["field"])
        new: Any = "?"
        for key in _CHANGE_FIELD_KEYS.get(field, ()):
            if order.get(key) is not None:
                new = order[key]
                break
        previous = change_value_text(field, change.get("previous_value"))
        lines.append(f"{field.replace('_', ' ')} {previous} → {change_value_text(field, new)}")
    return "\n".join(lines)


def confirm_order_dialog(order: dict[str, Any], account_id: str) -> None:
    """Gate 2 for place_order. Raises HumanAuthError if user does not confirm.

    Shows an AppKit colored dialog (green=BUY, red=SELL) with full order details,
    a DO NOT SEND button, and a SEND TO IBKR button. Auto-cancels after 60 seconds.
    Falls back to osascript if the AppKit subprocess fails; tkinter on non-macOS.
    Futures notional uses the _multiplier display field: price × qty × multiplier. When the
    caller sets _multiplier_unknown instead, no number is printed at all (2026-09-04).

    Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/orders/place-order.md
    """
    _show_confirm_dialog(
        title="⚠  LIVE ORDER CONFIRMATION",
        details=_order_rows(order, account_id),
        disclaimer=(
            "This is a LIVE order. It will be sent to Interactive Brokers "
            "and may result in real financial transactions that cannot be undone."
        ),
        confirm_label="SEND TO IBKR",
        abandon_label="DO NOT SEND",
    )


def confirm_modify_dialog(order_id: str, order: dict[str, Any], account_id: str) -> None:
    """Gate 2 for modify_order. Raises HumanAuthError if the user does not confirm.

    `order` is the fresh replacement body the caller dispatches plus display-only keys:
    `_changes` (the proposal's `{"field", "previous_value"}` list) renders one `Changes`
    line per field as `<field> <previous> → <new>`, and `_current_description` (IBKR's own
    `order_description_with_contract` from a status read) renders as `Currently at IBKR`.
    Before 2026-09-10 the dict was forwarded verbatim — `orderType`, `manualIndicator:
    True`, `outsideRTH: True` — with no month, notional, currency or before/after
    (claudia_ui gap #40). The side is read as `side`, so the banner colour is right for
    SELL modifies (before 2026-09 every SELL modify rendered green).

    Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/orders/modify-order.md
    """
    details = _order_rows(order, account_id)
    details["Order ID"] = order_id
    changes = _format_changes(order)
    if changes:
        details["Changes"] = changes
    current = order.get("_current_description")
    if current:
        details["Currently at IBKR"] = str(current)
    _show_confirm_dialog(
        title="⚠  MODIFY ORDER CONFIRMATION",
        details=details,
        disclaimer="This will MODIFY a live order at Interactive Brokers.",
        confirm_label="MODIFY ORDER",
        abandon_label="LEAVE UNCHANGED",
        action="MODIFY",
    )


def confirm_cancel_dialog(order_id: str, account_id: str, order: dict[str, Any] | None = None) -> None:
    """Gate 2 for cancel_order.

    `order` is optional display-only detail in the IBKR body shape (`side`, `quantity`,
    `orderType`, `price`/`auxPrice`, `tif`, `outsideRTH`, `ticker`, plus the `_`-prefixed
    display keys); `_current_description` — IBKR's `order_description_with_contract` —
    renders as `Currently at IBKR`. None keeps the order-id-only dialog for a caller
    without detail. Found missing live 2026-07-10 (user-flagged hard requirement); rendered
    as the raw proposal dict until 2026-09-10 — `order_id` and `Order ID` both,
    `limit_price: None`, the reason blob (claudia_ui gaps #27(b–e), #40).
    """
    if order:
        details = _order_rows(order, account_id)
        details["Order ID"] = order_id
        current = order.get("_current_description")
        if current:
            details["Currently at IBKR"] = str(current)
    else:
        details = {"Order ID": order_id, "Account": account_id}
    _show_confirm_dialog(
        title="⚠  CANCEL ORDER CONFIRMATION",
        details=details,
        disclaimer="This will CANCEL a live order at Interactive Brokers.",
        confirm_label="CANCEL ORDER",
        abandon_label="KEEP ORDER",
        action="CANCEL",
    )


def confirm_reply_dialog(
    reply_id: str,
    message: str = "",
    options: list[str] | None = None,
    *,
    order_label: str | None = None,
) -> None:
    """Gate 2 for reply_order. Shows the ACTUAL IBKR warning text, not just the reply_id.

    `message` defaults to "" so the standalone reply_order() call site (which only ever
    had a bare reply_id to work with) keeps showing a blank message exactly as before —
    that call site is unchanged by this task. place_order_and_confirm() /
    modify_order_and_confirm() are the callers that pass a real `message`.

    `options` (IBKR's messageOptions, e.g. varying button wording like "Yes"/"No" vs.
    "Decline"/"Accept and Continue") is accepted for signature completeness only — it is
    NOT surfaced as actual dialog button labels. The dialog keeps this package's own
    consistent confirm_label / abandon_label wording.

    HTML tags are stripped and entities unescaped (`reply_message_text`) before display
    since the AppKit/tkinter/osascript dialogs are plain text and IBKR reply messages have
    been observed containing tags (e.g. "<h4>...</h4>", verified live 2026-07-06) and
    entities (`&nbsp;` between every sentence of the Stop Variant disclosure, 2026-09-10).

    `order_label` (2026-09-11): with Gate 1 once per order write, this dialog is the only
    gate on a reply, so its title names the order — `⚠  CONFIRM ORDER REPLY — BUY 1 ES`.
    The standalone `reply_order()` path passes none and keeps the bare title.
    """
    # `options` is intentionally unused below — reserved for a future caller that wants
    # to log/inspect IBKR's messageOptions; never rendered as dialog button labels (see
    # docstring above).
    details: dict[str, Any] = {"Reply ID": reply_id}
    if message:
        details["Message"] = reply_message_text(message)
    title = "⚠  CONFIRM ORDER REPLY" + (f" — {order_label}" if order_label else "")
    _show_confirm_dialog(
        title=title,
        details=details,
        disclaimer="This will CONFIRM a pending order at Interactive Brokers.",
        confirm_label="CONFIRM REPLY",
        abandon_label="DO NOT REPLY",
    )


# Block-level elements end a line in HTML, so deleting them outright fuses the text on
# either side. Measured live 2026-09-10: IBKR sent "…on the market price. <h4>Confirm
# Mandatory Cap Price</h4>To avoid trading…" — correct HTML — and the dialog read
# "Cap PriceTo avoid" (claudia_ui gap #39, whose recorded cause blamed IBKR's own text).
_BLOCK_TAG = re.compile(
    r"</?(?:br|p|div|h[1-6]|li|ul|ol|tr|table|blockquote|hr)(?:\s[^<>]*)?/?>",
    re.IGNORECASE,
)


def _strip_html(text: str) -> str:
    """Strip HTML tags from IBKR reply message text for display in plain-text dialogs.

    Block-level tags become a newline; every other tag is removed. Only well-formed tags
    match (e.g. "<h4>", "</h4>", "<br/>", '<span class="x">') — NOT a bare "<" or ">" that
    isn't part of a tag. A naive r"<[^>]+>" would delete everything between an unrelated
    "<" (e.g. a message reading "price must be < 100.50") and the next unrelated ">"
    anywhere later in the string, corrupting real content.

    Leading and trailing newlines are trimmed — a message ending in "<br/>" would otherwise
    gain a blank last line — but only newlines: IBKR indents with `&nbsp;`, which
    `str.strip()` would eat.
    """
    text = _BLOCK_TAG.sub("\n", text)
    text = re.sub(r"</?[a-zA-Z][a-zA-Z0-9]*(?:\s[^<>]*)?/?>", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip("\n")


def reply_message_text(message: str) -> str:
    """IBKR reply text as a human should read it: tags stripped, then entities unescaped.

    The order matters: unescaping first would turn a literal `&lt;b&gt;` into `<b>`, which
    the tag stripper would then delete. Live 2026-09-10 the Stop Variant disclosure reached
    the dialog with `&nbsp;&nbsp;&nbsp;` between every sentence (claudia_ui gap #39). Used by
    the reply dialog and by the reply record `IBKRClient` hands back to callers.
    """
    return html.unescape(_strip_html(message))


_SIDE_KEYS = ("Action", "side", "Side")


def _extract_side(details: dict[str, Any]) -> str | None:
    """Return the order side from whichever key carries it, or None if none does.

    Three sources disagree on the key. Since 2026-09-10 all three order dialogs build
    their rows through `_order_rows`, which folds `side`/`Side` into `Action`; a caller
    handing a raw dict straight to this renderer may still say `side` or `Side`; and
    `confirm_reply_dialog` has no side at all. Reading only
    `Action` — as this did until 2026-08-07 — meant three of the four Gate 2 dialogs
    reached `_order_dialog` with no side, where the default was a confident green
    "BUY ORDER" banner over what could be a live sell.

    Returning None rather than a guess is the point. The banner is the pre-attentive
    cue, read before any text, so an unknown side must render as unknown; the caller
    must not be able to mistake "nobody told us" for "it is a buy".

    Args:
        details: The display dict handed to the dialog.

    Returns:
        The uppercased side, or None when no key carries one (and when a key is
        present but empty, which is equally uninformative).
    """
    for key in _SIDE_KEYS:
        raw = details.get(key)
        if raw is not None and str(raw).strip():
            return str(raw).upper()
    return None


def _show_confirm_dialog(
    title: str,
    details: dict[str, Any],
    disclaimer: str,
    confirm_label: str,
    abandon_label: str,
    action: str | None = None,
) -> None:
    """Render a modal confirmation dialog. Raises HumanAuthError if user cancels or closes.

    macOS primary path: AppKit colored dialog (green BUY, red SELL, amber when the side
    is unknown) via subprocess.
    macOS fallback: osascript plain dialog if AppKit subprocess fails.
    Non-macOS: tkinter fallback.

    `abandon_label` is a required parameter, not a default, because this renderer is shared
    by all four Gate 2 dialogs and it used to hardcode "CANCEL" for the abandon button.
    On the *cancel* dialog that produced "CANCEL ORDER" (perform it) beside "CANCEL"
    (abandon it): two adjacent buttons, same first word, opposite meanings, on a live
    order. Found by looking at the rendered dialog live on 2026-08-13 (B3) — no amount of
    code reading had caught it. Making the caller state the label is what stops a future
    dialog from silently inheriting a word that contradicts its own confirm button;
    `test_no_gate2_dialog_offers_two_buttons_sharing_a_first_word` enforces it over the class.
    """
    if sys.platform == "darwin":
        side = _extract_side(details)
        try:
            _show_appkit_dialog(title, details, disclaimer, confirm_label, side, abandon_label, action)
            return
        except HumanAuthError:
            raise  # user decision — do not fall back
        except Exception:  # noqa: S110 - AppKit subprocess failed; fall back to plain osascript
            pass
        _show_osascript_dialog(title, details, disclaimer, confirm_label, abandon_label)
    elif tk is not None:
        _show_tkinter_dialog(title, details, disclaimer, confirm_label, abandon_label)
    else:
        raise HumanAuthError("No GUI dialog available: not on macOS and tkinter is not installed.")


def _show_appkit_dialog(
    title: str,
    details: dict[str, Any],
    disclaimer: str,
    confirm_label: str,
    side: str | None,
    abandon_label: str,
    action: str | None = None,
) -> None:
    """Colored macOS confirmation dialog via AppKit, run as a subprocess.

    The subprocess gets its own main thread so NSApplication can run without
    conflicting with the host application's asyncio event loop (e.g. the
    Panel/Bokeh Tornado loop in ClaudIA).

    Green banner for BUY, red for SELL, amber "REVIEW ORDER" when `side` is None —
    cancel and reply dialogs genuinely have no side, and colouring those green would
    assert something no caller established.

    Raises HumanAuthError if user cancels/times out.
    Raises RuntimeError if the subprocess itself fails (caller falls back to osascript).
    """
    payload = _json.dumps(
        {
            "title": title,
            "details": details,
            "disclaimer": disclaimer,
            "confirm_label": confirm_label,
            "abandon_label": abandon_label,
            "side": side,
            "action": action,
            "timeout_s": _DIALOG_TIMEOUT_S,
        }
    )
    dialog_script = Path(__file__).parent / "_order_dialog.py"
    try:
        proc = subprocess.run(
            [sys.executable, str(dialog_script)],
            input=payload,
            capture_output=True,
            text=True,
            timeout=_DIALOG_TIMEOUT_S + 10,
        )
    except subprocess.TimeoutExpired as exc:
        raise HumanAuthError("Confirmation dialog timed out") from exc

    if proc.returncode != 0:
        raise RuntimeError(f"AppKit dialog failed: {proc.stderr.strip() or 'unknown error'}")

    output = proc.stdout.strip()
    if output != "CONFIRMED":
        raise HumanAuthError("Order cancelled by user")


def _show_osascript_dialog(
    title: str, details: dict[str, Any], disclaimer: str, confirm_label: str, abandon_label: str
) -> None:
    """Native macOS confirmation dialog via osascript.

    Uses AppleScript 'display dialog' with caution icon, two buttons (abandon / confirm),
    and a hard timeout. The default button is the abandon one so accidental Enter does nothing.

    Source: https://developer.apple.com/library/archive/documentation/AppleScript/Conceptual/AppleScriptLangGuide/reference/ASLR_cmds.html#//apple_ref/doc/uid/TP40000983-CH216-SW12
    """
    detail_lines = "\n".join(f"{k}: {v}" for k, v in details.items())
    message = f"{detail_lines}\n\n{disclaimer}"

    script = (
        f"set dlg to display dialog {_as_str(message)} "
        f"with title {_as_str(title)} "
        f"buttons {{{_as_str(abandon_label)}, {_as_str(confirm_label)}}} "
        f"default button {_as_str(abandon_label)} "
        f"giving up after {_DIALOG_TIMEOUT_S} "
        f"with icon caution\n"
        f"if gave up of dlg then\n"
        f'    return "timeout"\n'
        f"else\n"
        f"    return button returned of dlg\n"
        f"end if"
    )
    try:
        proc = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=_DIALOG_TIMEOUT_S + 5,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        raise HumanAuthError(f"Confirmation dialog failed: {exc}") from exc

    output = proc.stdout.strip()
    if proc.returncode != 0 or output in ("", "timeout", abandon_label):
        raise HumanAuthError("Order cancelled by user")
    if output != confirm_label:
        raise HumanAuthError(f"Unexpected dialog response: {output!r}")


def _as_str(text: str) -> str:
    """Escape a Python string for AppleScript: wrap in quotes, escape backslashes and quotes."""
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _show_tkinter_dialog(
    title: str, details: dict[str, Any], disclaimer: str, confirm_label: str, abandon_label: str
) -> None:
    """Fallback tkinter dialog for non-macOS environments.

    Must be called from the main thread. Auto-cancels after _DIALOG_TIMEOUT_S seconds.

    Security note: on_confirm runs inside the same process as all pip dependencies.
    A compromised dependency with access to tk._default_root could call root.after(0, on_confirm)
    to synthetically confirm without user interaction. Touch ID (Gate 1) already ran before
    this dialog, providing defense-in-depth.
    """
    confirmed: dict[str, Any] = {"value": False}

    root = tk.Tk()
    root.withdraw()

    dialog = tk.Toplevel(root)
    dialog.title(title)
    dialog.attributes("-topmost", True)
    dialog.resizable(False, False)
    dialog.grab_set()

    title_frame = tk.Frame(dialog, bg="#c0392b", pady=8)
    title_frame.pack(fill="x")
    tk.Label(
        title_frame,
        text=title,
        bg="#c0392b",
        fg="white",
        font=("Helvetica", 13, "bold"),
    ).pack()

    detail_frame = tk.Frame(dialog, padx=20, pady=10)
    detail_frame.pack(fill="x")
    for i, (key, val) in enumerate(details.items()):
        tk.Label(detail_frame, text=f"{key}:", font=("Helvetica", 11, "bold"), anchor="w").grid(
            row=i, column=0, sticky="w", pady=2
        )
        tk.Label(detail_frame, text=str(val), font=("Helvetica", 11), anchor="w").grid(
            row=i, column=1, sticky="w", padx=(10, 0), pady=2
        )

    disc_frame = tk.Frame(dialog, bg="#ffeaa7", padx=15, pady=10)
    disc_frame.pack(fill="x", padx=10, pady=5)
    tk.Label(
        disc_frame,
        text=disclaimer,
        bg="#ffeaa7",
        wraplength=340,
        font=("Helvetica", 10),
        justify="left",
    ).pack()

    btn_frame = tk.Frame(dialog, pady=10)
    btn_frame.pack()

    remaining: dict[str, Any] = {"secs": _DIALOG_TIMEOUT_S}
    _after_id: dict[str, Any] = {"id": None}

    def _cancel_tick() -> None:
        if _after_id["id"] is not None:
            with contextlib.suppress(Exception):
                dialog.after_cancel(_after_id["id"])
            _after_id["id"] = None

    def on_cancel() -> None:
        _cancel_tick()
        confirmed["value"] = False
        dialog.destroy()
        root.destroy()

    def on_confirm() -> None:
        _cancel_tick()
        confirmed["value"] = True
        dialog.destroy()
        root.destroy()

    tk.Button(btn_frame, text=abandon_label, command=on_cancel, width=16, bg="#bdc3c7", font=("Helvetica", 11)).pack(
        side="left", padx=10
    )
    tk.Button(
        btn_frame,
        text=confirm_label,
        command=on_confirm,
        width=18,
        bg="#e74c3c",
        fg="white",
        font=("Helvetica", 11, "bold"),
    ).pack(side="left", padx=10)

    countdown_var = tk.StringVar(value=f"Auto-cancels in {remaining['secs']}s")
    tk.Label(dialog, textvariable=countdown_var, fg="#888888", font=("Helvetica", 9)).pack(pady=(0, 6))

    def _tick() -> None:
        remaining["secs"] -= 1
        if remaining["secs"] <= 0:
            on_cancel()
        else:
            countdown_var.set(f"Auto-cancels in {remaining['secs']}s")
            _after_id["id"] = dialog.after(1000, _tick)

    _after_id["id"] = dialog.after(1000, _tick)
    dialog.protocol("WM_DELETE_WINDOW", on_cancel)
    dialog.update_idletasks()
    w, h = dialog.winfo_width(), dialog.winfo_height()
    x = (dialog.winfo_screenwidth() - w) // 2
    y = (dialog.winfo_screenheight() - h) // 2
    dialog.geometry(f"+{x}+{y}")
    root.mainloop()

    if not confirmed["value"]:
        raise HumanAuthError("Order cancelled by user")
