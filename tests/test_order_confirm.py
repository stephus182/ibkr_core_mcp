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
# _show_confirm_dialog
# ---------------------------------------------------------------------------

def test_show_confirm_dialog_confirm_does_not_raise():
    mock_tk = _make_tk_mock("SEND TO IBKR")
    with patch("ibkr_core_mcp.order_confirm.tk", mock_tk):
        from ibkr_core_mcp.order_confirm import _show_confirm_dialog
        _show_confirm_dialog(
            title="Test",
            details={"Symbol": "AAPL"},
            disclaimer="Live order warning",
            confirm_label="SEND TO IBKR",
        )  # must not raise


def test_show_confirm_dialog_cancel_raises():
    mock_tk = _make_tk_mock("CANCEL")
    with patch("ibkr_core_mcp.order_confirm.tk", mock_tk):
        from ibkr_core_mcp.order_confirm import _show_confirm_dialog
        with pytest.raises(HumanAuthError, match="cancelled by user"):
            _show_confirm_dialog(
                title="Test",
                details={"Symbol": "AAPL"},
                disclaimer="Live order warning",
                confirm_label="SEND TO IBKR",
            )


def test_show_confirm_dialog_window_close_raises():
    mock_tk = _make_tk_mock(None)  # None → close protocol fires
    with patch("ibkr_core_mcp.order_confirm.tk", mock_tk):
        from ibkr_core_mcp.order_confirm import _show_confirm_dialog
        with pytest.raises(HumanAuthError, match="cancelled by user"):
            _show_confirm_dialog(
                title="Test",
                details={"Symbol": "AAPL"},
                disclaimer="Live order warning",
                confirm_label="SEND TO IBKR",
            )


# ---------------------------------------------------------------------------
# Public helpers — verify they call _show_confirm_dialog with right args
# ---------------------------------------------------------------------------

def test_confirm_order_dialog_passes_correct_fields():
    order = {"ticker": "AAPL", "side": "BUY", "quantity": 100,
              "orderType": "LIMIT", "price": 182.50, "tif": "DAY"}
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


def test_confirm_reply_dialog_passes_reply_id():
    with patch("ibkr_core_mcp.order_confirm._show_confirm_dialog") as mock_show:
        from ibkr_core_mcp.order_confirm import confirm_reply_dialog
        confirm_reply_dialog("RPL789")
    kwargs = mock_show.call_args.kwargs
    assert kwargs["details"]["Reply ID"] == "RPL789"
    assert "CONFIRM" in kwargs["confirm_label"]
