from __future__ import annotations
try:
    import tkinter as tk  # type: ignore[import]
except (ModuleNotFoundError, ImportError):  # Python without Tk support (CI, headless)
    tk = None  # type: ignore[assignment]
from ibkr_core_mcp.exceptions import HumanAuthError


def confirm_order_dialog(order: dict, account_id: str) -> None:
    """Gate 2 for place_order. Raises HumanAuthError if user does not confirm."""
    symbol = order.get("ticker", order.get("symbol", "UNKNOWN"))
    side = order.get("side", "?")
    qty = order.get("quantity", "?")
    order_type = order.get("orderType", order.get("order_type", "MARKET"))
    price = order.get("price")
    tif = order.get("tif", order.get("timeInForce", "DAY"))
    price_str = f"${price}" if price is not None else "MARKET"
    _show_confirm_dialog(
        title="⚠  LIVE ORDER CONFIRMATION",
        details={
            "Account": account_id,
            "Action": side,
            "Symbol": symbol,
            "Quantity": str(qty),
            "Order Type": order_type,
            "Price": price_str,
            "TIF": tif,
        },
        disclaimer=(
            "This is a LIVE order. It will be sent to Interactive Brokers "
            "and may result in real financial transactions that cannot be undone."
        ),
        confirm_label="SEND TO IBKR",
    )


def confirm_modify_dialog(order_id: str, order: dict, account_id: str) -> None:
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


def confirm_cancel_dialog(order_id: str, account_id: str) -> None:
    """Gate 2 for cancel_order."""
    _show_confirm_dialog(
        title="⚠  CANCEL ORDER CONFIRMATION",
        details={"Order ID": order_id, "Account": account_id},
        disclaimer="This will CANCEL a live order at Interactive Brokers.",
        confirm_label="CANCEL ORDER",
    )


def confirm_reply_dialog(reply_id: str) -> None:
    """Gate 2 for reply_order."""
    _show_confirm_dialog(
        title="⚠  CONFIRM ORDER REPLY",
        details={"Reply ID": reply_id},
        disclaimer="This will CONFIRM a pending order at Interactive Brokers.",
        confirm_label="CONFIRM REPLY",
    )


def _show_confirm_dialog(
    title: str, details: dict, disclaimer: str, confirm_label: str
) -> None:
    """Render modal dialog. Raises HumanAuthError if user cancels or closes."""
    if tk is None:
        raise HumanAuthError(
            "tkinter is not available in this Python installation. "
            "Install a Tk-enabled Python to use the GUI confirmation dialog."
        )
    confirmed: dict = {"value": False}

    root = tk.Tk()
    root.withdraw()

    dialog = tk.Toplevel(root)
    dialog.title(title)
    dialog.attributes("-topmost", True)
    dialog.resizable(False, False)
    dialog.grab_set()

    # --- Title bar ---
    title_frame = tk.Frame(dialog, bg="#c0392b", pady=8)
    title_frame.pack(fill="x")
    tk.Label(
        title_frame, text=title, bg="#c0392b", fg="white",
        font=("Helvetica", 13, "bold"),
    ).pack()

    # --- Order details ---
    detail_frame = tk.Frame(dialog, padx=20, pady=10)
    detail_frame.pack(fill="x")
    for i, (key, val) in enumerate(details.items()):
        tk.Label(detail_frame, text=f"{key}:", font=("Helvetica", 11, "bold"),
                 anchor="w").grid(row=i, column=0, sticky="w", pady=2)
        tk.Label(detail_frame, text=str(val), font=("Helvetica", 11),
                 anchor="w").grid(row=i, column=1, sticky="w", padx=(10, 0), pady=2)

    # --- Disclaimer ---
    disc_frame = tk.Frame(dialog, bg="#ffeaa7", padx=15, pady=10)
    disc_frame.pack(fill="x", padx=10, pady=5)
    tk.Label(
        disc_frame, text=disclaimer, bg="#ffeaa7", wraplength=340,
        font=("Helvetica", 10), justify="left",
    ).pack()

    # --- Buttons ---
    btn_frame = tk.Frame(dialog, pady=10)
    btn_frame.pack()

    def on_cancel() -> None:
        confirmed["value"] = False
        dialog.destroy()
        root.destroy()

    def on_confirm() -> None:
        confirmed["value"] = True
        dialog.destroy()
        root.destroy()

    tk.Button(btn_frame, text="CANCEL", command=on_cancel, width=12,
              bg="#bdc3c7", font=("Helvetica", 11)).pack(side="left", padx=10)
    tk.Button(btn_frame, text=confirm_label, command=on_confirm, width=18,
              bg="#e74c3c", fg="white", font=("Helvetica", 11, "bold")).pack(side="left", padx=10)

    dialog.protocol("WM_DELETE_WINDOW", on_cancel)

    dialog.update_idletasks()
    w = dialog.winfo_width()
    h = dialog.winfo_height()
    x = (dialog.winfo_screenwidth() - w) // 2
    y = (dialog.winfo_screenheight() - h) // 2
    dialog.geometry(f"+{x}+{y}")

    root.mainloop()

    if not confirmed["value"]:
        raise HumanAuthError("Order cancelled by user")
