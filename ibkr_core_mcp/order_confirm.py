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


def confirm_order_dialog(order: dict[str, Any], account_id: str) -> None:
    """Gate 2 for place_order. Raises HumanAuthError if user does not confirm.

    Shows an AppKit colored dialog (green=BUY, red=SELL) with full order details,
    a CANCEL button, and a SEND TO IBKR button. Auto-cancels after 60 seconds.
    Falls back to osascript if the AppKit subprocess fails; tkinter on non-macOS.
    Futures notional uses the _multiplier display field: price × qty × multiplier.

    Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/orders/place-order.md
    """
    symbol = order.get("ticker", order.get("symbol", "UNKNOWN"))
    company_name = order.get("_companyName", order.get("companyName", ""))
    symbol_str = f"{symbol} — {company_name}" if company_name else symbol
    side = order.get("side", "?")
    qty = order.get("quantity", "?")
    order_type = order.get("orderType", order.get("order_type", "MARKET"))
    price = order.get("price")
    tif = order.get("tif", order.get("timeInForce", "DAY"))
    multiplier = order.get("_multiplier")
    price_str = f"${price}" if price is not None else "MARKET"
    try:
        if price is not None and multiplier is not None:
            # Futures: notional = price × qty × multiplier
            notional = float(price) * float(qty) * float(multiplier)
            total_str = f"${notional:,.2f} USD (×{multiplier:g} multiplier)"
        elif price is not None:
            total_str = f"${float(price) * float(qty):,.2f} USD"
        else:
            total_str = "Market"
    except (TypeError, ValueError):
        total_str = "—"
    _show_confirm_dialog(
        title="⚠  LIVE ORDER CONFIRMATION",
        details={
            "Account": account_id,
            "Action": side,
            "Symbol": symbol_str,
            "Quantity": str(qty),
            "Order Type": order_type,
            "Price": price_str,
            "TIF": tif,
            "Total (est.)": total_str,
        },
        disclaimer=(
            "This is a LIVE order. It will be sent to Interactive Brokers "
            "and may result in real financial transactions that cannot be undone."
        ),
        confirm_label="SEND TO IBKR",
    )


def confirm_modify_dialog(order_id: str, order: dict[str, Any], account_id: str) -> None:
    """Gate 2 for modify_order."""
    _show_confirm_dialog(
        title="⚠  MODIFY ORDER CONFIRMATION",
        details={
            **{k: str(v) for k, v in order.items() if k not in ("Order ID", "Account")},
            "Order ID": order_id,
            "Account": account_id,
        },
        disclaimer="This will MODIFY a live order at Interactive Brokers.",
        confirm_label="MODIFY ORDER",
    )


def confirm_cancel_dialog(order_id: str, account_id: str, order: dict[str, Any] | None = None) -> None:
    """Gate 2 for cancel_order.

    `order` is optional display-only detail (symbol/side/qty/price/TIF/etc.) so the human
    can visually verify which order they're cancelling — mirrors confirm_modify_dialog's
    pattern. None preserves the old order-id-only dialog for any caller without full order
    detail available. Found missing live 2026-07-10 — user-flagged hard requirement.
    """
    details: dict[str, Any] = {}
    if order:
        details.update({k: str(v) for k, v in order.items() if k not in ("Order ID", "Account")})
    details["Order ID"] = order_id
    details["Account"] = account_id
    _show_confirm_dialog(
        title="⚠  CANCEL ORDER CONFIRMATION",
        details=details,
        disclaimer="This will CANCEL a live order at Interactive Brokers.",
        confirm_label="CANCEL ORDER",
    )


def confirm_reply_dialog(reply_id: str, message: str = "", options: list[str] | None = None) -> None:
    """Gate 2 for reply_order. Shows the ACTUAL IBKR warning text, not just the reply_id.

    `message` defaults to "" so the standalone reply_order() call site (which only ever
    had a bare reply_id to work with) keeps showing a blank message exactly as before —
    that call site is unchanged by this task. place_order_and_confirm() /
    modify_order_and_confirm() are the callers that pass a real `message`.

    `options` (IBKR's messageOptions, e.g. varying button wording like "Yes"/"No" vs.
    "Decline"/"Accept and Continue") is accepted for signature completeness only — it is
    NOT surfaced as actual dialog button labels. The dialog keeps this package's own
    consistent confirm_label / cancel wording.

    HTML is stripped from `message` before display since the AppKit/tkinter/osascript
    dialogs are plain text and IBKR reply messages have been observed containing tags
    (e.g. "<h4>...</h4>", verified live 2026-07-06).
    """
    # `options` is intentionally unused below — reserved for a future caller that wants
    # to log/inspect IBKR's messageOptions; never rendered as dialog button labels (see
    # docstring above).
    details: dict[str, Any] = {"Reply ID": reply_id}
    if message:
        details["Message"] = _strip_html(message)
    _show_confirm_dialog(
        title="⚠  CONFIRM ORDER REPLY",
        details=details,
        disclaimer="This will CONFIRM a pending order at Interactive Brokers.",
        confirm_label="CONFIRM REPLY",
    )


def _strip_html(text: str) -> str:
    """Strip HTML tags from IBKR reply message text for display in plain-text dialogs.

    Only matches well-formed tags (e.g. "<h4>", "</h4>", "<br/>", '<span class="x">')
    — NOT a bare "<" or ">" that isn't part of a tag. A naive r"<[^>]+>" would delete
    everything between an unrelated "<" (e.g. a message reading "price must be < 100.50")
    and the next unrelated ">" anywhere later in the string, corrupting real content.
    """
    return re.sub(r"</?[a-zA-Z][a-zA-Z0-9]*(?:\s[^<>]*)?/?>", "", text)


def _show_confirm_dialog(title: str, details: dict[str, Any], disclaimer: str, confirm_label: str) -> None:
    """Render a modal confirmation dialog. Raises HumanAuthError if user cancels or closes.

    macOS primary path: AppKit colored dialog (green for BUY, red for SELL) via subprocess.
    macOS fallback: osascript plain dialog if AppKit subprocess fails.
    Non-macOS: tkinter fallback.
    """
    if sys.platform == "darwin":
        side = str(details.get("Action", "")).upper()
        try:
            _show_appkit_dialog(title, details, disclaimer, confirm_label, side)
            return
        except HumanAuthError:
            raise  # user decision — do not fall back
        except Exception:
            pass  # AppKit subprocess failed — fall back to plain osascript
        _show_osascript_dialog(title, details, disclaimer, confirm_label)
    elif tk is not None:
        _show_tkinter_dialog(title, details, disclaimer, confirm_label)
    else:
        raise HumanAuthError("No GUI dialog available: not on macOS and tkinter is not installed.")


def _show_appkit_dialog(title: str, details: dict[str, Any], disclaimer: str, confirm_label: str, side: str) -> None:
    """Colored macOS confirmation dialog via AppKit, run as a subprocess.

    The subprocess gets its own main thread so NSApplication can run without
    conflicting with the host application's asyncio event loop (e.g. the
    Panel/Bokeh Tornado loop in ClaudIA).
    Green banner for BUY, red banner for SELL.

    Raises HumanAuthError if user cancels/times out.
    Raises RuntimeError if the subprocess itself fails (caller falls back to osascript).
    """
    payload = _json.dumps(
        {
            "title": title,
            "details": details,
            "disclaimer": disclaimer,
            "confirm_label": confirm_label,
            "side": side,
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


def _show_osascript_dialog(title: str, details: dict[str, Any], disclaimer: str, confirm_label: str) -> None:
    """Native macOS confirmation dialog via osascript.

    Uses AppleScript 'display dialog' with caution icon, two buttons (CANCEL / confirm),
    and a hard timeout. The default button is CANCEL so accidental Enter does nothing.

    Source: https://developer.apple.com/library/archive/documentation/AppleScript/Conceptual/AppleScriptLangGuide/reference/ASLR_cmds.html#//apple_ref/doc/uid/TP40000983-CH216-SW12
    """
    detail_lines = "\n".join(f"{k}: {v}" for k, v in details.items())
    message = f"{detail_lines}\n\n{disclaimer}"

    script = (
        f"set dlg to display dialog {_as_str(message)} "
        f"with title {_as_str(title)} "
        f'buttons {{"CANCEL", {_as_str(confirm_label)}}} '
        f'default button "CANCEL" '
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
    if proc.returncode != 0 or output in ("", "timeout", "CANCEL"):
        raise HumanAuthError("Order cancelled by user")
    if output != confirm_label:
        raise HumanAuthError(f"Unexpected dialog response: {output!r}")


def _as_str(text: str) -> str:
    """Escape a Python string for AppleScript: wrap in quotes, escape backslashes and quotes."""
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _show_tkinter_dialog(title: str, details: dict[str, Any], disclaimer: str, confirm_label: str) -> None:
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

    tk.Button(btn_frame, text="CANCEL", command=on_cancel, width=12, bg="#bdc3c7", font=("Helvetica", 11)).pack(
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
