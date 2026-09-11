import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any
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
    return {
        "title": "Test",
        "details": {"Symbol": "AAPL", "Action": "BUY"},
        "disclaimer": "Live order warning",
        "confirm_label": "SEND TO IBKR",
        "abandon_label": "DO NOT SEND",
    }


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
        pytest.raises(HumanAuthError, match="cancelled by user"),
    ):
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
    with (
        patch.object(sys, "platform", "linux"),
        patch("ibkr_core_mcp.order_confirm.tk", mock_tk),
        pytest.raises(HumanAuthError, match="cancelled by user"),
    ):
        oc._show_confirm_dialog(**_dialog_args())


def test_show_confirm_dialog_tkinter_window_close_raises():
    import ibkr_core_mcp.order_confirm as oc

    mock_tk = _make_tk_mock(None)  # None → close protocol fires
    with (
        patch.object(sys, "platform", "linux"),
        patch("ibkr_core_mcp.order_confirm.tk", mock_tk),
        pytest.raises(HumanAuthError, match="cancelled by user"),
    ):
        oc._show_confirm_dialog(**_dialog_args())


def test_show_confirm_dialog_raises_when_no_gui_available():
    import ibkr_core_mcp.order_confirm as oc

    with (
        patch.object(sys, "platform", "linux"),
        patch("ibkr_core_mcp.order_confirm.tk", None),
        pytest.raises(HumanAuthError, match="tkinter is not installed"),
    ):
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

    with (
        patch.object(subprocess, "run", return_value=_appkit_proc("CANCELLED\n")),
        pytest.raises(HumanAuthError, match="cancelled by user"),
    ):
        oc._show_appkit_dialog("T", {"Action": "BUY"}, "warn", "SEND TO IBKR", "BUY", "DO NOT SEND")


def test_appkit_dialog_subprocess_failure_raises_runtimeerror():
    """Non-zero exit = broken subprocess → RuntimeError so caller can fall back."""
    import ibkr_core_mcp.order_confirm as oc

    with (
        patch.object(subprocess, "run", return_value=_appkit_proc("", returncode=1, stderr="ERROR: no AppKit")),
        pytest.raises(RuntimeError, match="AppKit dialog failed"),
    ):
        oc._show_appkit_dialog("T", {"Action": "BUY"}, "warn", "SEND TO IBKR", "BUY", "DO NOT SEND")


def test_appkit_dialog_timeout_raises_humanauth():
    import ibkr_core_mcp.order_confirm as oc

    with (
        patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired(cmd="dialog", timeout=70)),
        pytest.raises(HumanAuthError, match="timed out"),
    ):
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


def test_confirm_cancel_dialog_shows_typed_order_details_when_provided():
    """User-flagged hard requirement, 2026-07-10: the cancel dialog must show full order
    details, not just an opaque order ID. Since 2026-09-10 those details are the typed rows
    every Gate 2 dialog shares, never the raw dict (claudia_ui gaps #27(b–e), #40)."""
    with patch("ibkr_core_mcp.order_confirm._show_confirm_dialog") as mock_show:
        from ibkr_core_mcp.order_confirm import confirm_cancel_dialog

        confirm_cancel_dialog(
            "ORD456",
            "U1234567",
            {"ticker": "AAPL", "side": "BUY", "quantity": 1, "orderType": "LMT", "price": 100.0, "tif": "GTC"},
        )
    details = mock_show.call_args.kwargs["details"]
    assert details["Order ID"] == "ORD456"
    assert details["Account"] == "U1234567"
    assert details["Symbol"] == "AAPL"
    assert details["Action"] == "BUY"
    assert details["Price"] == "100.0"
    assert details["TIF"] == "GTC"
    assert "symbol" not in details and "side" not in details and "price" not in details
    assert list(details).count("Order ID") == 1


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
        (
            "confirm_order_dialog",
            lambda: oc.confirm_order_dialog({"ticker": "AAPL", "side": "BUY", "quantity": 1, "price": 150.0}, "U123"),
        ),
        ("confirm_modify_dialog", lambda: oc.confirm_modify_dialog("8001", {"side": "SELL", "quantity": 2}, "U123")),
        ("confirm_cancel_dialog", lambda: oc.confirm_cancel_dialog("8001", "U123", {"side": "BUY", "quantity": 1})),
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

    def fake_run(cmd, input=None, **kwargs):
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


def _order_dialog_details(order: dict[str, object]) -> str:
    import ibkr_core_mcp.order_confirm as oc

    with patch("ibkr_core_mcp.order_confirm._show_confirm_dialog") as mock_show:
        oc.confirm_order_dialog(order, "U123")
    details = mock_show.call_args.kwargs["details"]
    return " | ".join(f"{k}: {v}" for k, v in details.items())


def test_gate2_does_not_assert_a_currency_when_the_order_carries_none():
    rendered = _order_dialog_details({"ticker": "AAPL", "side": "BUY", "quantity": 1, "price": 150.0})
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
    rendered = _order_dialog_details({"ticker": "ES", "side": "BUY", "quantity": 1, "price": 5000.0, "_multiplier": 50})
    assert "USD" not in rendered, f"futures notional hardcodes USD: {rendered}"
    assert "$" not in rendered


# ---------------------------------------------------------------------------
# outsideRTH row (2026-09-04) — the attribute that decides when a futures stop can fire
# belongs in the human's view. Shown whenever the body carries it, Yes/No verbatim; absent
# when the caller sent nothing (IBKR's default applies and nothing is claimed).
# ---------------------------------------------------------------------------


def test_confirm_order_dialog_shows_outside_rth_when_the_body_carries_it():
    """True → 'Yes', False → 'No', keyed 'Outside RTH', placed after TIF."""
    from ibkr_core_mcp.order_confirm import confirm_order_dialog

    for value, shown in ((True, "Yes"), (False, "No")):
        order = {
            "ticker": "ES",
            "side": "BUY",
            "quantity": 1,
            "orderType": "STP",
            "price": 7725.0,
            "tif": "GTC",
            "outsideRTH": value,
        }
        with patch("ibkr_core_mcp.order_confirm._show_confirm_dialog") as mock_show:
            confirm_order_dialog(order, "U1234567")
        details = mock_show.call_args.kwargs["details"]
        assert details["Outside RTH"] == shown
        keys = list(details)
        assert keys.index("Outside RTH") == keys.index("TIF") + 1


def test_confirm_order_dialog_omits_outside_rth_when_the_body_does_not_carry_it():
    """No attribute sent → no row: the dialog must not claim a value nobody set."""
    from ibkr_core_mcp.order_confirm import confirm_order_dialog

    order = {"ticker": "AAPL", "side": "BUY", "quantity": 1, "orderType": "LMT", "price": 150.0, "tif": "DAY"}
    with patch("ibkr_core_mcp.order_confirm._show_confirm_dialog") as mock_show:
        confirm_order_dialog(order, "U1234567")
    assert "Outside RTH" not in mock_show.call_args.kwargs["details"]


def test_confirm_order_dialog_omits_outside_rth_when_the_key_is_present_but_not_a_bool():
    """Review 2026-09-04 #4: a present-but-None key must not render as 'No' — the dialog
    claims nothing it was not given a real value for."""
    from ibkr_core_mcp.order_confirm import confirm_order_dialog

    order = {
        "ticker": "ES",
        "side": "BUY",
        "quantity": 1,
        "orderType": "STP",
        "price": 7725.0,
        "tif": "GTC",
        "outsideRTH": None,
    }
    with patch("ibkr_core_mcp.order_confirm._show_confirm_dialog") as mock_show:
        confirm_order_dialog(order, "U1234567")
    assert "Outside RTH" not in mock_show.call_args.kwargs["details"]


# ---------------------------------------------------------------------------
# Futures notional (2026-09-04). Live: Gate 2 showed 'Total (est.): 7,735.00' for ONE ES
# contract — price × qty with no multiplier, 50× short of the 386,750 USD it stood for.
# The multiplier now arrives as _multiplier when known; when the caller could not learn
# it, _multiplier_unknown=True and the dialog must refuse to print a number.
# ---------------------------------------------------------------------------


def test_confirm_order_dialog_futures_notional_uses_the_multiplier_and_currency():
    """price × qty × multiplier, with the ISO currency the caller established."""
    from ibkr_core_mcp.order_confirm import confirm_order_dialog

    order = {
        "ticker": "ES",
        "_companyName": "ESU6 · expires 2026-09-18 · ×50",
        "side": "BUY",
        "quantity": 1,
        "orderType": "STP",
        "price": 7735.0,
        "tif": "GTC",
        "_multiplier": 50.0,
        "_currency": "USD",
    }
    with patch("ibkr_core_mcp.order_confirm._show_confirm_dialog") as mock_show:
        confirm_order_dialog(order, "U1")
    details = mock_show.call_args.kwargs["details"]
    assert details["Total (est.)"] == "386,750.00 USD (×50 multiplier)"
    assert "ESU6" in details["Symbol"]


def test_confirm_order_dialog_refuses_a_notional_when_the_multiplier_is_unknown():
    """No multiplier on a futures order → no number, an honest dash and the reason."""
    from ibkr_core_mcp.order_confirm import confirm_order_dialog

    order = {
        "ticker": "ES",
        "side": "BUY",
        "quantity": 1,
        "orderType": "STP",
        "price": 7735.0,
        "tif": "GTC",
        "_multiplier_unknown": True,
    }
    with patch("ibkr_core_mcp.order_confirm._show_confirm_dialog") as mock_show:
        confirm_order_dialog(order, "U1")
    total = mock_show.call_args.kwargs["details"]["Total (est.)"]
    assert "7,735.00" not in total
    assert "multiplier unknown" in total.lower()


def test_reply_message_text_strips_tags_then_unescapes_entities():
    """Order matters: unescaping first would turn a literal '&lt;b&gt;' into '<b>', which the
    tag stripper would then delete. Live 2026-09-10 (claudia_ui gap #39): IBKR's Stop Variant
    disclosure reached the dialog with '&nbsp;&nbsp;&nbsp;' between every sentence."""
    from ibkr_core_mcp.order_confirm import reply_message_text

    text = (
        "<h4>Stop Variant Order Confirmation</h4>&nbsp;&nbsp;&nbsp;A Stop Order is an "
        "instruction to buy or sell.&nbsp;&nbsp;&nbsp;Price must be &lt;b&gt; 100."
    )
    shown = reply_message_text(text)
    assert "&nbsp;" not in shown and "&lt;" not in shown and "<h4>" not in shown
    # The heading is its own line now: <h4> is block-level, so deleting it with no
    # separator is what produced "Cap PriceTo avoid" live (gap #39).
    assert shown.startswith("Stop Variant Order Confirmation\n\xa0\xa0\xa0A Stop Order")
    assert shown.endswith("Price must be <b> 100.")


def test_a_block_tag_becomes_a_line_break_not_nothing():
    """A heading must not fuse into the sentence after it (claudia_ui gap #39).

    The exact string IBKR sent on 2026-09-10 for order 1793215923. That gap recorded the
    run-on as IBKR's own text — "`_resolve_one_reply` joins the message list with a space"
    — and reading the raw message disproved it: the HTML is correct, a block element ends
    its own line, and deleting it with no separator was ours.
    """
    from ibkr_core_mcp.order_confirm import reply_message_text

    raw = (
        "t your order has on the market price. <h4>Confirm Mandatory Cap Price</h4>To "
        "avoid trading at a price that is not consistent with a fair and orderly market, IB"
    )
    shown = reply_message_text(raw)
    assert "PriceTo" not in shown
    assert "Confirm Mandatory Cap Price\nTo avoid trading" in shown


def test_the_banner_states_the_action_not_the_side():
    """A cancel reads CANCEL ORDER in red whatever the order's side (claudia_ui gap #42).

    Read live 2026-09-10: a dialog titled CANCEL ORDER CONFIRMATION, with a CANCEL ORDER
    button, carried a confident green `BUY ORDER` banner — the largest and most
    pre-attentive element on the screen saying the opposite of the act being authorised.
    The side is not lost: it is on the rows as `Action:`.
    """
    from ibkr_core_mcp._order_dialog import _banner

    red = (0.72, 0.10, 0.10)
    amber = (0.55, 0.42, 0.05)
    for side in ("BUY", "SELL", "B", None):
        assert _banner(side, "CANCEL") == (red, "CANCEL ORDER")
        assert _banner(side, "MODIFY") == (amber, "MODIFY ORDER")


def test_the_banner_still_reads_the_side_when_placing():
    """Placement has no competing action, so the side is what matters — and an unstated
    side must still look unstated rather than defaulting to a confident green buy."""
    from ibkr_core_mcp._order_dialog import _banner

    assert _banner("BUY", None) == ((0.10, 0.50, 0.20), "BUY ORDER")
    assert _banner("SELL", None) == ((0.72, 0.10, 0.10), "SELL ORDER")
    assert _banner("SHORT", None) == ((0.72, 0.10, 0.10), "SELL ORDER")
    assert _banner(None, None) == ((0.55, 0.42, 0.05), "REVIEW ORDER")
    assert _banner("", None) == ((0.55, 0.42, 0.05), "REVIEW ORDER")


def test_quantity_never_shows_a_trailing_point_zero():
    """IBKR reports `size` as '1.0'; a human writes 1 (claudia_ui gap #42)."""
    from ibkr_core_mcp.order_confirm import _quantity_text

    assert _quantity_text("1.0") == "1"
    assert _quantity_text(1.0) == "1"
    assert _quantity_text(3) == "3"
    assert _quantity_text("2.5") == "2.5"
    assert _quantity_text(1000000.0) == "1000000"  # never scientific notation
    assert _quantity_text("?") == "?"


def test_cancel_and_modify_dialogs_declare_their_action():
    """The renderer cannot infer the action, so each dialog states it (gap #42)."""
    from ibkr_core_mcp.order_confirm import confirm_cancel_dialog, confirm_modify_dialog

    with patch("ibkr_core_mcp.order_confirm._show_confirm_dialog") as mock_show:
        confirm_cancel_dialog("555", "U1", {"side": "BUY", "quantity": "1.0", "ticker": "ES"})
    assert mock_show.call_args.kwargs["action"] == "CANCEL"
    assert mock_show.call_args.kwargs["details"]["Quantity"] == "1"

    with patch("ibkr_core_mcp.order_confirm._show_confirm_dialog") as mock_show:
        confirm_modify_dialog("555", {"side": "BUY", "quantity": 1, "ticker": "ES"}, "U1")
    assert mock_show.call_args.kwargs["action"] == "MODIFY"


def test_confirm_reply_dialog_shows_the_cleaned_message():
    with patch("ibkr_core_mcp.order_confirm._show_confirm_dialog") as mock_show:
        from ibkr_core_mcp.order_confirm import confirm_reply_dialog

        confirm_reply_dialog("RPL1", "Confirm&nbsp;Mandatory Cap Price<br/>")
    assert mock_show.call_args.kwargs["details"]["Message"] == "Confirm\xa0Mandatory Cap Price"


_TYPED_ROW_KEYS = {
    "Account",
    "Action",
    "Symbol",
    "Quantity",
    "Order Type",
    "Price",
    "Stop",
    "TIF",
    "Outside RTH",
    "Total (est.)",
    "Order ID",
    "Changes",
    "Currently at IBKR",
}


def test_every_order_dialog_shows_only_typed_rows_and_the_order_id_once():
    """claudia_ui gap #40 (screenshots 2026-09-10): the modify dialog was the raw body
    (`orderType`, `manualIndicator: True`), the cancel dialog the raw proposal (`order_id` and
    `Order ID` both, `limit_price: None`). All three dialogs now draw from one row builder."""
    from ibkr_core_mcp.order_confirm import (
        confirm_cancel_dialog,
        confirm_modify_dialog,
        confirm_order_dialog,
    )

    body = {
        "conid": 649180671,
        "orderType": "STP",
        "side": "BUY",
        "tif": "GTC",
        "quantity": 1,
        "ticker": "ES",
        "manualIndicator": True,
        "price": 7895.0,
        "outsideRTH": True,
        "limit_price": None,
        "_companyName": "ESU6 · expires 2026-09-18 · x50",
        "_multiplier": 50.0,
        "_currency": "USD",
        "_changes": [{"field": "stop_price", "previous_value": 7900.0}],
        "_current_description": "Buy 1 ES Sep18'26 Stop 7900.00, GTC",
    }
    calls: list[dict[str, Any]] = []
    with patch("ibkr_core_mcp.order_confirm._show_confirm_dialog", side_effect=lambda **kw: calls.append(kw)):
        confirm_order_dialog(body, "U1")
        confirm_modify_dialog("975324733", body, "U1")
        confirm_cancel_dialog("975324733", "U1", body)
    assert len(calls) == 3
    for kw in calls:
        details = kw["details"]
        assert set(details) <= _TYPED_ROW_KEYS, details
        assert "None" not in details.values()
        assert "manualIndicator" not in details
        assert details["Symbol"] == "ES — ESU6 · expires 2026-09-18 · x50"
        assert details["Price"] == "7895.0 USD"
        assert details["Outside RTH"] == "Yes"
        assert details["Total (est.)"] == "394,750.00 USD (×50 multiplier)"
    assert "Order ID" not in calls[0]["details"]
    assert calls[1]["details"]["Order ID"] == "975324733"
    assert calls[1]["details"]["Changes"] == "stop price 7900.0 → 7895.0"
    assert calls[1]["details"]["Currently at IBKR"] == "Buy 1 ES Sep18'26 Stop 7900.00, GTC"
    assert calls[2]["details"]["Order ID"] == "975324733"
    assert calls[2]["details"]["Currently at IBKR"] == "Buy 1 ES Sep18'26 Stop 7900.00, GTC"
    assert "Changes" not in calls[2]["details"]


def test_stop_limit_dialog_shows_the_stop_as_its_own_row():
    """A stop-limit's trigger lives in auxPrice; no dialog showed it before 2026-09-10."""
    with patch("ibkr_core_mcp.order_confirm._show_confirm_dialog") as mock_show:
        from ibkr_core_mcp.order_confirm import confirm_order_dialog

        confirm_order_dialog(
            {
                "ticker": "AAPL",
                "side": "SELL",
                "quantity": 2,
                "orderType": "STOP_LIMIT",
                "price": 100.0,
                "auxPrice": 98.0,
                "tif": "DAY",
                "_currency": "USD",
            },
            "U1",
        )
    details = mock_show.call_args.kwargs["details"]
    keys = list(details)
    assert details["Price"] == "100.0 USD" and details["Stop"] == "98.0 USD"
    assert keys.index("Stop") == keys.index("Price") + 1
    assert keys.index("TIF") == keys.index("Stop") + 1


def test_modify_dialog_changes_row_covers_every_field_kind():
    """Each proposal field maps to the body key carrying its new value; unknown → '?'."""
    from ibkr_core_mcp.order_confirm import confirm_modify_dialog

    body = {
        "ticker": "AAPL",
        "side": "BUY",
        "quantity": 3,
        "orderType": "LMT",
        "price": 105.0,
        "tif": "DAY",
        "outsideRTH": True,
        "_changes": [
            {"field": "limit_price", "previous_value": 100.0},
            {"field": "quantity", "previous_value": 1},
            {"field": "tif", "previous_value": "GTC"},
            {"field": "outside_rth", "previous_value": False},
            {"field": "mystery", "previous_value": 7},
            "not a dict",
        ],
    }
    with patch("ibkr_core_mcp.order_confirm._show_confirm_dialog") as mock_show:
        confirm_modify_dialog("1", body, "U1")
    assert mock_show.call_args.kwargs["details"]["Changes"] == (
        "limit price 100.0 → 105.0\nquantity 1 → 3\ntif GTC → DAY\noutside rth No → Yes\nmystery 7 → ?"
    )


def test_confirm_cancel_dialog_without_order_keeps_the_id_only_shape():
    """A caller without detail still gets the order-id-only dialog, unchanged."""
    with patch("ibkr_core_mcp.order_confirm._show_confirm_dialog") as mock_show:
        from ibkr_core_mcp.order_confirm import confirm_cancel_dialog

        confirm_cancel_dialog("ORD456", "U1234567")
    assert mock_show.call_args.kwargs["details"] == {"Order ID": "ORD456", "Account": "U1234567"}
