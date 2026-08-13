import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
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
    commands: dict[str, Callable[[], None]] = {}
    close_cmd: Callable[[], None] | None = None

    def fake_button(parent, **kwargs):
        text = kwargs.get("text", "")
        cmd = kwargs.get("command")
        if cmd:
            commands[text] = cmd
        return MagicMock()

    mock_root = MagicMock()
    mock_dialog = MagicMock()

    def fake_protocol(event, cmd):
        nonlocal close_cmd
        if event == "WM_DELETE_WINDOW":
            close_cmd = cmd

    mock_dialog.protocol.side_effect = fake_protocol

    def fake_mainloop():
        if click_label is None:
            if close_cmd:
                close_cmd()
        elif click_label in commands:
            commands[click_label]()

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
        abandon_label="DO NOT SEND",
    )


def test_dispatch_darwin_uses_appkit_first():
    import ibkr_core_mcp.order_confirm as oc

    with (
        patch.object(sys, "platform", "darwin"),
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
        patch.object(sys, "platform", "darwin"),
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
        patch.object(sys, "platform", "darwin"),
        patch.object(oc, "_show_appkit_dialog", side_effect=RuntimeError("AppKit dialog failed")),
        patch.object(oc, "_show_osascript_dialog") as mock_osa,
    ):
        oc._show_confirm_dialog(**_dialog_args())
    mock_osa.assert_called_once()


def test_show_confirm_dialog_tkinter_confirm_does_not_raise():
    import ibkr_core_mcp.order_confirm as oc

    mock_tk = _make_tk_mock("SEND TO IBKR")
    with patch.object(sys, "platform", "linux"), patch("ibkr_core_mcp.order_confirm.tk", mock_tk):
        oc._show_confirm_dialog(**_dialog_args())  # must not raise


def test_show_confirm_dialog_tkinter_cancel_raises():
    import ibkr_core_mcp.order_confirm as oc

    mock_tk = _make_tk_mock("CANCEL")
    with patch.object(sys, "platform", "linux"), patch("ibkr_core_mcp.order_confirm.tk", mock_tk):
        with pytest.raises(HumanAuthError, match="cancelled by user"):
            oc._show_confirm_dialog(**_dialog_args())


def test_show_confirm_dialog_tkinter_window_close_raises():
    import ibkr_core_mcp.order_confirm as oc

    mock_tk = _make_tk_mock(None)  # None → close protocol fires
    with patch.object(sys, "platform", "linux"), patch("ibkr_core_mcp.order_confirm.tk", mock_tk):
        with pytest.raises(HumanAuthError, match="cancelled by user"):
            oc._show_confirm_dialog(**_dialog_args())


def test_show_confirm_dialog_raises_when_no_gui_available():
    import ibkr_core_mcp.order_confirm as oc

    with patch.object(sys, "platform", "linux"), patch("ibkr_core_mcp.order_confirm.tk", None):
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

    with patch.object(subprocess, "run", return_value=_appkit_proc("CONFIRMED\n")):
        oc._show_appkit_dialog("T", {"Action": "BUY"}, "warn", "SEND TO IBKR", "BUY", "DO NOT SEND")


def test_appkit_dialog_cancelled_raises_humanauth():
    import ibkr_core_mcp.order_confirm as oc

    with patch.object(subprocess, "run", return_value=_appkit_proc("CANCELLED\n")):
        with pytest.raises(HumanAuthError, match="cancelled by user"):
            oc._show_appkit_dialog("T", {"Action": "BUY"}, "warn", "SEND TO IBKR", "BUY", "DO NOT SEND")


def test_appkit_dialog_subprocess_failure_raises_runtimeerror():
    """Non-zero exit = broken subprocess → RuntimeError so caller can fall back."""
    import ibkr_core_mcp.order_confirm as oc

    with patch.object(subprocess, "run", return_value=_appkit_proc("", returncode=1, stderr="ERROR: no AppKit")):
        with pytest.raises(RuntimeError, match="AppKit dialog failed"):
            oc._show_appkit_dialog("T", {"Action": "BUY"}, "warn", "SEND TO IBKR", "BUY", "DO NOT SEND")


def test_appkit_dialog_timeout_raises_humanauth():
    import ibkr_core_mcp.order_confirm as oc

    with patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired(cmd="dialog", timeout=70)):
        with pytest.raises(HumanAuthError, match="timed out"):
            oc._show_appkit_dialog("T", {"Action": "BUY"}, "warn", "SEND TO IBKR", "BUY", "DO NOT SEND")


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


# ============================================================================
# Side extraction — which banner colour the human actually sees
# ============================================================================


def test_modify_dialog_carries_the_side_from_ibkrs_own_key():
    """IBKR's live-order dict uses "side"; only confirm_order_dialog sets "Action".

    _show_confirm_dialog read "Action" alone, so a SELL modify reached the dialog with
    side "" and rendered the dark-green BUY banner over a live sell. The detail lines
    showed side: SELL, but the colour — the part designed to be read first — did not.
    """
    import ibkr_core_mcp.order_confirm as oc

    with patch.object(sys, "platform", "darwin"), patch.object(oc, "_show_appkit_dialog") as mock_appkit:
        oc.confirm_modify_dialog("123", {"side": "SELL", "quantity": 500, "price": 180}, "U1")

    assert mock_appkit.call_args.args[4] == "SELL"


def test_modify_dialog_accepts_capitalised_side_key():
    import ibkr_core_mcp.order_confirm as oc

    with patch.object(sys, "platform", "darwin"), patch.object(oc, "_show_appkit_dialog") as mock_appkit:
        oc.confirm_modify_dialog("123", {"Side": "SELL"}, "U1")

    assert mock_appkit.call_args.args[4] == "SELL"


def test_place_dialog_still_carries_action():
    """The one dialog that already worked must keep working."""
    import ibkr_core_mcp.order_confirm as oc

    with patch.object(sys, "platform", "darwin"), patch.object(oc, "_show_appkit_dialog") as mock_appkit:
        oc.confirm_order_dialog({"side": "SELL", "ticker": "AAPL", "quantity": 1}, "U1")

    assert mock_appkit.call_args.args[4] == "SELL"


def test_cancel_dialog_without_order_detail_has_no_side():
    """Nothing establishes a side here, so nothing may be asserted about one."""
    import ibkr_core_mcp.order_confirm as oc

    with patch.object(sys, "platform", "darwin"), patch.object(oc, "_show_appkit_dialog") as mock_appkit:
        oc.confirm_cancel_dialog("123", "U1")

    assert mock_appkit.call_args.args[4] is None


def test_cancel_dialog_carries_side_when_order_detail_is_supplied():
    import ibkr_core_mcp.order_confirm as oc

    with patch.object(sys, "platform", "darwin"), patch.object(oc, "_show_appkit_dialog") as mock_appkit:
        oc.confirm_cancel_dialog("123", "U1", {"side": "SELL", "ticker": "AAPL"})

    assert mock_appkit.call_args.args[4] == "SELL"


def test_reply_dialog_has_no_side():
    import ibkr_core_mcp.order_confirm as oc

    with patch.object(sys, "platform", "darwin"), patch.object(oc, "_show_appkit_dialog") as mock_appkit:
        oc.confirm_reply_dialog("r1", "Confirm this order?")

    assert mock_appkit.call_args.args[4] is None


# ---------------------------------------------------------------------------
# Gate 2 button labels — the abandon button must never be confusable with the
# confirm button. Found live 2026-08-13 (B3): the cancel dialog offered
# "CANCEL ORDER" (perform the cancellation) beside "CANCEL" (abandon it) —
# adjacent, same first word, opposite meaning, on a live order.
#
# Asserted over EVERY public Gate 2 dialog, not just the cancel one: the defect
# is a shared renderer hardcoding a clause that is wrong for one caller, so the
# control has to cover the class or it will pass again the next time a dialog
# is added.
# ---------------------------------------------------------------------------


def _invoke_every_gate2_dialog():
    """Yield (name, kwargs) for each public Gate 2 dialog, with the renderer mocked."""
    import ibkr_core_mcp.order_confirm as oc

    cases = (
        ("confirm_order_dialog", lambda: oc.confirm_order_dialog(
            {"ticker": "AAPL", "side": "BUY", "quantity": 1, "price": 150.0}, "U123")),
        ("confirm_modify_dialog", lambda: oc.confirm_modify_dialog(
            "8001", {"side": "SELL", "quantity": 2}, "U123")),
        ("confirm_cancel_dialog", lambda: oc.confirm_cancel_dialog(
            "8001", "U123", {"side": "BUY", "quantity": 1})),
        ("confirm_reply_dialog", lambda: oc.confirm_reply_dialog("r-1", "some warning")),
    )
    for name, call in cases:
        with patch("ibkr_core_mcp.order_confirm._show_confirm_dialog") as mock_show:
            call()
        yield name, mock_show.call_args.kwargs


def test_every_gate2_dialog_passes_an_explicit_abandon_label():
    for name, kwargs in _invoke_every_gate2_dialog():
        assert kwargs.get("abandon_label"), (
            f"{name} passes no abandon_label — the abandon button is hardcoded in each "
            f"backend, so no caller can make it unambiguous"
        )


def test_no_gate2_dialog_offers_two_buttons_sharing_a_first_word():
    for name, kwargs in _invoke_every_gate2_dialog():
        confirm = str(kwargs.get("confirm_label", ""))
        abandon = str(kwargs.get("abandon_label", ""))
        assert confirm and abandon, f"{name} is missing a button label"
        assert confirm.split()[0].upper() != abandon.split()[0].upper(), (
            f"{name}: confirm={confirm!r} and abandon={abandon!r} begin with the same "
            f"word — a mis-click inverts the outcome on a live order"
        )
        assert abandon.upper() != confirm.upper()
        assert not confirm.upper().startswith(abandon.upper() + " "), (
            f"{name}: abandon={abandon!r} is a prefix of confirm={confirm!r}"
        )


def test_abandon_label_reaches_the_appkit_subprocess_payload():
    """The label must cross the process boundary, not just the mock.

    _show_appkit_dialog renders in a subprocess fed by JSON on stdin. A label that
    stopped at the Python call would leave the real button reading whatever
    _order_dialog.py defaults to — the mock would still be satisfied.
    """
    import ibkr_core_mcp.order_confirm as oc

    captured: dict[str, str] = {}

    def fake_run(cmd, input=None, **kwargs):  # noqa: A002 - matches subprocess.run
        captured["payload"] = input
        return MagicMock(returncode=0, stdout="CONFIRMED", stderr="")

    with patch.object(subprocess, "run", side_effect=fake_run):
        oc._show_appkit_dialog("T", {"Action": "BUY"}, "warn", "CANCEL ORDER", "BUY", "KEEP ORDER")

    import json

    sent = json.loads(captured["payload"])
    assert sent["abandon_label"] == "KEEP ORDER"
    assert sent["confirm_label"] == "CANCEL ORDER"


def test_order_dialog_subprocess_never_defaults_abandon_to_the_confirm_word():
    """A payload missing abandon_label must not fall back to 'CANCEL'.

    _order_dialog.py runs standalone, so a caller that forgets the key must not be able
    to recreate the CANCEL/CANCEL ORDER collision by omission.
    """
    src = (Path(__file__).parent.parent / "ibkr_core_mcp" / "_order_dialog.py").read_text()
    assert 'data.get("abandon_label"' in src, "_order_dialog.py does not read abandon_label"
    assert 'addButtonWithTitle_("CANCEL")' not in src, "abandon button is still hardcoded"
    match = re.search(r'data\.get\("abandon_label",\s*"([^"]*)"\)', src)
    assert match, "abandon_label default not found"
    assert match.group(1).split()[0].upper() != "CANCEL", (
        f"default abandon label {match.group(1)!r} starts with CANCEL — collides with 'CANCEL ORDER'"
    )


# ---------------------------------------------------------------------------
# Gate 2 currency — the dialog must never assert a currency nothing established.
# Found 2026-08-13 (gap #24): price_str was f"${price}" and the total was
# f"${...} USD", hardcoded, on the last human-readable surface before an
# irreversible action, for an account that holds EUR-denominated equities.
# "$" alone is shared by USD/MXN/CAD/AUD/HKD/SGD.
# ---------------------------------------------------------------------------


def _order_dialog_details(order: dict) -> str:
    import ibkr_core_mcp.order_confirm as oc

    with patch("ibkr_core_mcp.order_confirm._show_confirm_dialog") as mock_show:
        oc.confirm_order_dialog(order, "U123")
    details = mock_show.call_args.kwargs["details"]
    return " | ".join(f"{k}: {v}" for k, v in details.items())


def test_gate2_does_not_assert_a_currency_when_the_order_carries_none():
    rendered = _order_dialog_details(
        {"ticker": "AAPL", "side": "BUY", "quantity": 1, "price": 150.0}
    )
    assert "$" not in rendered, f"bare $ asserted with no currency established: {rendered}"
    assert "USD" not in rendered, f"USD asserted with no currency established: {rendered}"


def test_gate2_uses_the_orders_own_currency_when_it_is_provided():
    rendered = _order_dialog_details(
        {"ticker": "SAP", "side": "BUY", "quantity": 10, "price": 100.0, "_currency": "EUR"}
    )
    assert "EUR" in rendered, f"order currency EUR not shown: {rendered}"
    assert "USD" not in rendered, f"USD asserted over an EUR order: {rendered}"
    assert "$" not in rendered, f"bare $ rendered for a non-dollar currency: {rendered}"


def test_gate2_renders_usd_as_an_iso_code_not_a_dollar_sign():
    rendered = _order_dialog_details(
        {"ticker": "AAPL", "side": "BUY", "quantity": 1, "price": 150.0, "_currency": "USD"}
    )
    assert "USD" in rendered
    assert "$" not in rendered, f"$ is shared by six currencies — use the ISO code: {rendered}"


def test_gate2_futures_notional_does_not_assert_usd():
    rendered = _order_dialog_details(
        {"ticker": "ES", "side": "BUY", "quantity": 1, "price": 5000.0, "_multiplier": 50}
    )
    assert "USD" not in rendered, f"futures notional hardcodes USD: {rendered}"
    assert "$" not in rendered
