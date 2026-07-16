from unittest.mock import MagicMock, patch

import pytest

from ibkr_core_mcp.exceptions import HumanAuthError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tk_mock(click_label: str | None):
    """
    Build a patched tkinter mock that simulates a button click inside mainloop.
    click_label=None simulates window-close (protocol WM_DELETE_WINDOW fires).
    """
    captured = {"commands": {}, "close_cmd": None}

    def fake_button(parent, **kwargs):
        text = kwargs.get("text", "")
        cmd = kwargs.get("command")
        if cmd:
            captured["commands"][text] = cmd
        return MagicMock()

    mock_root = MagicMock()
    mock_dialog = MagicMock()

    def fake_protocol(event, cmd):
        if event == "WM_DELETE_WINDOW":
            captured["close_cmd"] = cmd

    mock_dialog.protocol.side_effect = fake_protocol

    def fake_mainloop():
        if click_label is None:
            if captured["close_cmd"]:
                captured["close_cmd"]()
        elif click_label in captured["commands"]:
            captured["commands"][click_label]()

    mock_root.mainloop.side_effect = fake_mainloop

    mock_tk = MagicMock()
    mock_tk.Tk.return_value = mock_root
    mock_tk.Toplevel.return_value = mock_dialog
    mock_tk.Frame.return_value = MagicMock()
    mock_tk.Label.return_value = MagicMock()
    mock_tk.Button.side_effect = fake_button
    return mock_tk


# ---------------------------------------------------------------------------
# _show_confirm_dialog — dispatch (never runs a real dialog: every backend
# is mocked; platform is forced per test)
# ---------------------------------------------------------------------------


def _dialog_args():
    return dict(
        title="Test",
        details={"Symbol": "AAPL", "Action": "BUY"},
        disclaimer="Live order warning",
        confirm_label="SEND TO IBKR",
    )


def test_dispatch_darwin_uses_appkit_first():
    import ibkr_core_mcp.order_confirm as oc

    with (
        patch.object(oc.sys, "platform", "darwin"),
        patch.object(oc, "_show_appkit_dialog") as mock_appkit,
        patch.object(oc, "_show_osascript_dialog") as mock_osa,
    ):
        oc._show_confirm_dialog(**_dialog_args())
    mock_appkit.assert_called_once()
    mock_osa.assert_not_called()


def test_dispatch_darwin_appkit_cancel_does_not_fall_back():
    """HumanAuthError from AppKit = user decision — must NOT retry via osascript."""
    import ibkr_core_mcp.order_confirm as oc

    with (
        patch.object(oc.sys, "platform", "darwin"),
        patch.object(oc, "_show_appkit_dialog", side_effect=HumanAuthError("Order cancelled by user")),
        patch.object(oc, "_show_osascript_dialog") as mock_osa,
    ):
        with pytest.raises(HumanAuthError, match="cancelled by user"):
            oc._show_confirm_dialog(**_dialog_args())
    mock_osa.assert_not_called()


def test_dispatch_darwin_appkit_failure_falls_back_to_osascript():
    """Non-HumanAuthError from AppKit (subprocess broke) → osascript fallback."""
    import ibkr_core_mcp.order_confirm as oc

    with (
        patch.object(oc.sys, "platform", "darwin"),
        patch.object(oc, "_show_appkit_dialog", side_effect=RuntimeError("AppKit dialog failed")),
        patch.object(oc, "_show_osascript_dialog") as mock_osa,
    ):
        oc._show_confirm_dialog(**_dialog_args())
    mock_osa.assert_called_once()


def test_show_confirm_dialog_tkinter_confirm_does_not_raise():
    import ibkr_core_mcp.order_confirm as oc

    mock_tk = _make_tk_mock("SEND TO IBKR")
    with patch.object(oc.sys, "platform", "linux"), patch("ibkr_core_mcp.order_confirm.tk", mock_tk):
        oc._show_confirm_dialog(**_dialog_args())  # must not raise


def test_show_confirm_dialog_tkinter_cancel_raises():
    import ibkr_core_mcp.order_confirm as oc

    mock_tk = _make_tk_mock("CANCEL")
    with patch.object(oc.sys, "platform", "linux"), patch("ibkr_core_mcp.order_confirm.tk", mock_tk):
        with pytest.raises(HumanAuthError, match="cancelled by user"):
            oc._show_confirm_dialog(**_dialog_args())


def test_show_confirm_dialog_tkinter_window_close_raises():
    import ibkr_core_mcp.order_confirm as oc

    mock_tk = _make_tk_mock(None)  # None → close protocol fires
    with patch.object(oc.sys, "platform", "linux"), patch("ibkr_core_mcp.order_confirm.tk", mock_tk):
        with pytest.raises(HumanAuthError, match="cancelled by user"):
            oc._show_confirm_dialog(**_dialog_args())


def test_show_confirm_dialog_raises_when_no_gui_available():
    import ibkr_core_mcp.order_confirm as oc

    with patch.object(oc.sys, "platform", "linux"), patch("ibkr_core_mcp.order_confirm.tk", None):
        with pytest.raises(HumanAuthError, match="tkinter is not installed"):
            oc._show_confirm_dialog(**_dialog_args())


# ---------------------------------------------------------------------------
# _show_appkit_dialog — subprocess protocol (subprocess.run always mocked)
# ---------------------------------------------------------------------------


def _appkit_proc(stdout="", returncode=0, stderr=""):
    proc = MagicMock()
    proc.stdout = stdout
    proc.returncode = returncode
    proc.stderr = stderr
    return proc


def test_appkit_dialog_confirmed_does_not_raise():
    import ibkr_core_mcp.order_confirm as oc

    with patch.object(oc.subprocess, "run", return_value=_appkit_proc("CONFIRMED\n")):
        oc._show_appkit_dialog("T", {"Action": "BUY"}, "warn", "SEND TO IBKR", "BUY")


def test_appkit_dialog_cancelled_raises_humanauth():
    import ibkr_core_mcp.order_confirm as oc

    with patch.object(oc.subprocess, "run", return_value=_appkit_proc("CANCELLED\n")):
        with pytest.raises(HumanAuthError, match="cancelled by user"):
            oc._show_appkit_dialog("T", {"Action": "BUY"}, "warn", "SEND TO IBKR", "BUY")


def test_appkit_dialog_subprocess_failure_raises_runtimeerror():
    """Non-zero exit = broken subprocess → RuntimeError so caller can fall back."""
    import ibkr_core_mcp.order_confirm as oc

    with patch.object(oc.subprocess, "run", return_value=_appkit_proc("", returncode=1, stderr="ERROR: no AppKit")):
        with pytest.raises(RuntimeError, match="AppKit dialog failed"):
            oc._show_appkit_dialog("T", {"Action": "BUY"}, "warn", "SEND TO IBKR", "BUY")


def test_appkit_dialog_timeout_raises_humanauth():
    import subprocess as _sp

    import ibkr_core_mcp.order_confirm as oc

    with patch.object(oc.subprocess, "run", side_effect=_sp.TimeoutExpired(cmd="dialog", timeout=70)):
        with pytest.raises(HumanAuthError, match="timed out"):
            oc._show_appkit_dialog("T", {"Action": "BUY"}, "warn", "SEND TO IBKR", "BUY")


# ---------------------------------------------------------------------------
# Public helpers — verify they call _show_confirm_dialog with right args
# ---------------------------------------------------------------------------


def test_confirm_order_dialog_passes_correct_fields():
    order = {"ticker": "AAPL", "side": "BUY", "quantity": 100, "orderType": "LIMIT", "price": 182.50, "tif": "DAY"}
    with patch("ibkr_core_mcp.order_confirm._show_confirm_dialog") as mock_show:
        from ibkr_core_mcp.order_confirm import confirm_order_dialog

        confirm_order_dialog(order, "U1234567")
    mock_show.assert_called_once()
    kwargs = mock_show.call_args.kwargs
    assert kwargs["details"]["Account"] == "U1234567"
    assert kwargs["details"]["Symbol"] == "AAPL"
    assert kwargs["details"]["Action"] == "BUY"
    assert kwargs["confirm_label"] == "SEND TO IBKR"


def test_confirm_modify_dialog_passes_order_id():
    with patch("ibkr_core_mcp.order_confirm._show_confirm_dialog") as mock_show:
        from ibkr_core_mcp.order_confirm import confirm_modify_dialog

        confirm_modify_dialog("ORD123", {"side": "SELL"}, "U1234567")
    kwargs = mock_show.call_args.kwargs
    assert kwargs["details"]["Order ID"] == "ORD123"
    assert "MODIFY" in kwargs["confirm_label"]


def test_confirm_cancel_dialog_passes_order_id():
    with patch("ibkr_core_mcp.order_confirm._show_confirm_dialog") as mock_show:
        from ibkr_core_mcp.order_confirm import confirm_cancel_dialog

        confirm_cancel_dialog("ORD456", "U1234567")
    kwargs = mock_show.call_args.kwargs
    assert kwargs["details"]["Order ID"] == "ORD456"
    assert "CANCEL" in kwargs["confirm_label"]


def test_confirm_cancel_dialog_shows_order_details_when_provided():
    """User-flagged hard requirement, 2026-07-10: the cancel dialog must show full
    order details (symbol/side/qty/price/TIF), not just an opaque order ID — mirrors
    what confirm_modify_dialog already does."""
    with patch("ibkr_core_mcp.order_confirm._show_confirm_dialog") as mock_show:
        from ibkr_core_mcp.order_confirm import confirm_cancel_dialog

        confirm_cancel_dialog(
            "ORD456",
            "U1234567",
            {"symbol": "AAPL", "side": "BUY", "quantity": 1, "orderType": "LMT", "price": 100.0},
        )
    kwargs = mock_show.call_args.kwargs
    assert kwargs["details"]["Order ID"] == "ORD456"
    assert kwargs["details"]["Account"] == "U1234567"
    assert kwargs["details"]["symbol"] == "AAPL"
    assert kwargs["details"]["side"] == "BUY"
    assert kwargs["details"]["price"] == "100.0"


def test_confirm_reply_dialog_passes_reply_id():
    with patch("ibkr_core_mcp.order_confirm._show_confirm_dialog") as mock_show:
        from ibkr_core_mcp.order_confirm import confirm_reply_dialog

        confirm_reply_dialog("RPL789")
    kwargs = mock_show.call_args.kwargs
    assert kwargs["details"]["Reply ID"] == "RPL789"
    assert "CONFIRM" in kwargs["confirm_label"]


def test_confirm_reply_dialog_no_message_key_when_empty():
    """Unchanged call site (bare reply_id, no message) must not show a blank Message line."""
    with patch("ibkr_core_mcp.order_confirm._show_confirm_dialog") as mock_show:
        from ibkr_core_mcp.order_confirm import confirm_reply_dialog

        confirm_reply_dialog("RPL789")
    kwargs = mock_show.call_args.kwargs
    assert "Message" not in kwargs["details"]


def test_confirm_reply_dialog_passes_message_through():
    with patch("ibkr_core_mcp.order_confirm._show_confirm_dialog") as mock_show:
        from ibkr_core_mcp.order_confirm import confirm_reply_dialog

        confirm_reply_dialog("RPL789", "Price is outside band.")
    kwargs = mock_show.call_args.kwargs
    assert kwargs["details"]["Reply ID"] == "RPL789"
    assert kwargs["details"]["Message"] == "Price is outside band."


def test_confirm_reply_dialog_strips_html_from_message():
    with patch("ibkr_core_mcp.order_confirm._show_confirm_dialog") as mock_show:
        from ibkr_core_mcp.order_confirm import confirm_reply_dialog

        confirm_reply_dialog("RPL789", "<h4>Warning</h4> price band exceeded")
    kwargs = mock_show.call_args.kwargs
    assert "<h4>" not in kwargs["details"]["Message"]
    assert "Warning" in kwargs["details"]["Message"]
    assert "price band exceeded" in kwargs["details"]["Message"]


def test_confirm_reply_dialog_does_not_corrupt_lone_angle_brackets():
    """A naive r"<[^>]+>" strip would delete "< 100.50 to qualify... >" style content
    whenever the message contains a literal comparison operator, not just real HTML tags.
    """
    with patch("ibkr_core_mcp.order_confirm._show_confirm_dialog") as mock_show:
        from ibkr_core_mcp.order_confirm import confirm_reply_dialog

        confirm_reply_dialog("RPL789", "Price must be < 100.50 to qualify")
    kwargs = mock_show.call_args.kwargs
    assert kwargs["details"]["Message"] == "Price must be < 100.50 to qualify"


def test_confirm_reply_dialog_accepts_options_without_error():
    """options is accepted for signature completeness; must not change dialog rendering."""
    with patch("ibkr_core_mcp.order_confirm._show_confirm_dialog") as mock_show:
        from ibkr_core_mcp.order_confirm import confirm_reply_dialog

        confirm_reply_dialog("RPL789", "msg", ["Yes", "No"])
    kwargs = mock_show.call_args.kwargs
    assert kwargs["confirm_label"] == "CONFIRM REPLY"
