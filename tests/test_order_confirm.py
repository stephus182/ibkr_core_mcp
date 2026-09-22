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
    assert details["Price"] == "100.00"
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
        (
            "confirm_bracket_dialog",
            lambda: oc.confirm_bracket_dialog(
                {"ticker": "ES", "side": "SELL", "quantity": 1, "orderType": "LMT", "price": 7725.0, "cOID": "C-1"},
                [
                    {
                        "ticker": "ES",
                        "side": "BUY",
                        "quantity": 1,
                        "orderType": "LMT",
                        "price": 7700.0,
                        "parentId": "C-1",
                    }
                ],
                "U123",
            ),
        ),
    )
    for name, call in cases:
        with patch("ibkr_core_mcp.order_confirm._show_confirm_dialog") as mock_show:
            call()
        yield name, mock_show.call_args.kwargs


def test_the_gate2_dialog_enumeration_covers_every_confirm_dialog():
    """The two controls below are only as wide as the list above, and that list is written
    by hand — so a dialog added without a case in it is silently exempt from both. That is
    the exact failure the class-level framing exists to prevent ("it will pass again the
    next time a dialog is added"), so the list is itself asserted against the module.
    """
    import ibkr_core_mcp.order_confirm as oc

    public = {
        name
        for name in dir(oc)
        if name.startswith("confirm_") and name.endswith("_dialog") and callable(getattr(oc, name))
    }
    covered = {name for name, _ in _invoke_every_gate2_dialog()}
    assert public == covered, f"Gate 2 dialogs not enumerated: {sorted(public - covered)}"


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

    green, red, amber = (0.10, 0.50, 0.20), (0.72, 0.10, 0.10), (0.55, 0.42, 0.05)
    for side in ("BUY", "SELL", "B", None):
        assert _banner(side, "CANCEL") == (red, "CANCEL ORDER")
    # Modify states the action but keeps the ORDER'S colour, as IB does (user decision
    # 2026-09-10 23:20; the amber shipped that evening was wrong by decision, not defect).
    assert _banner("BUY", "MODIFY") == (green, "MODIFY ORDER")
    assert _banner("SELL", "MODIFY") == (red, "MODIFY ORDER")
    assert _banner(None, "MODIFY") == (amber, "MODIFY ORDER")  # an unstated side still looks unstated


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


def test_both_sides_of_a_change_are_formatted_alike():
    """A diff is read by comparing two values, so they must be rendered the same way.

    Live 2026-09-10 on one order, one stop-price change rendered three ways: the
    chat card said `stop_price: 7900.0 → 7950`, Gate 2 said `stop price 7900.0 → 7950.0`.
    Each surface printed whatever type the value arrived as — a float from the proposal's
    `previous_value`, an int from the model's replacement body.
    """
    from ibkr_core_mcp.order_confirm import change_value_text

    assert change_value_text("stop_price", 7900.0) == "7,900.00"
    assert change_value_text("stop_price", 7950) == "7,950.00"
    assert change_value_text("limit_price", "100.5") == "100.50"
    assert change_value_text("quantity", 1.0) == "1"
    assert change_value_text("quantity", "2.0") == "2"
    assert change_value_text("outside_rth", True) == "Yes"
    assert change_value_text("outside_rth", False) == "No"
    assert change_value_text("tif", "GTC") == "GTC"
    assert change_value_text("order_type", "STP") == "STP"
    assert change_value_text("stop_price", None) == "?"
    assert change_value_text("stop_price", "?") == "?"  # _format_changes's unknown sentinel


def test_the_gate2_changes_row_uses_the_shared_formatter():
    """The dialog's diff line must agree with the approval text to the character."""
    from ibkr_core_mcp.order_confirm import _format_changes

    order = {
        "auxPrice": 7950,
        "quantity": 2.0,
        "_changes": [
            {"field": "stop_price", "previous_value": 7900.0},
            {"field": "quantity", "previous_value": "1.0"},
        ],
    }
    assert _format_changes(order) == "stop price 7,900.00 → 7,950.00\nquantity 1 → 2"


def test_confirm_reply_dialog_shows_the_cleaned_message():
    with patch("ibkr_core_mcp.order_confirm._show_confirm_dialog") as mock_show:
        from ibkr_core_mcp.order_confirm import confirm_reply_dialog

        confirm_reply_dialog("11111111-1111-4111-8111-111111111111", "Confirm&nbsp;Mandatory Cap Price<br/>")
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
    # An execution attribute is ADMITTED to the screen on purpose (2026-09-22). It is not a
    # relaxation of gap #40: identity, routing and compliance keys are still refused below.
    # The two rules are opposites by design — what changes how the order EXECUTES must be
    # visible, what merely identifies or routes it must not clutter the last human screen.
    "All-or-None",
    # A5: named when the bracket-parent check could not be completed. Never silent.
    "Bracket size check",
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
        "allOrNone": True,
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
        assert details["Price"] == "7,895.00"  # index points, not money (2026-09-11)
        assert details["Outside RTH"] == "Yes"
        # The other half of the same rule: an execution attribute the caller sent IS on the
        # screen. Before 2026-09-22 this key reached IBKR and appeared on no row.
        assert details["All-or-None"] == "Yes"
        assert details["Total (est.)"] == "394,750.00 USD (×50 multiplier)"
    assert "Order ID" not in calls[0]["details"]
    assert calls[1]["details"]["Order ID"] == "975324733"
    assert calls[1]["details"]["Changes"] == "stop price 7,900.00 → 7,895.00"
    assert calls[1]["details"]["Currently at IBKR"] == "Buy 1 ES Sep18'26 Stop 7900.00, GTC"
    assert calls[2]["details"]["Order ID"] == "975324733"
    assert calls[2]["details"]["Currently at IBKR"] == "Buy 1 ES Sep18'26 Stop 7900.00, GTC"
    assert "Changes" not in calls[2]["details"]


def test_an_execution_attribute_the_caller_sends_reaches_the_last_human_screen():
    """The defect this closes, measured 2026-09-22: a body carrying `allOrNone`,
    `trailingAmt` and `trailingType` produced a dialog row set BYTE-IDENTICAL to a body
    carrying none of them, while `client.place_order` sent all three to IBKR verbatim.

    `allOrNone` decides whether the order may fill in parts — IBKR: "execute the order
    entirely or not execute at all" — so it changes what the human is agreeing to.
    Source: https://www.interactivebrokers.com/docs/web-api/api-reference/trading/trading-orders/submit-new-order.md
    """
    from ibkr_core_mcp.order_confirm import _order_rows

    plain = {"conid": 265598, "orderType": "LMT", "side": "BUY", "quantity": 1,
             "ticker": "GLD", "price": 300.0, "tif": "DAY"}  # fmt: skip
    loaded = dict(plain, allOrNone=True, trailingAmt=1.5, trailingType="amt")
    control, rows = _order_rows(plain, "U1"), _order_rows(loaded, "U1")

    assert set(rows) - set(control) == {"All-or-None", "Trailing amount", "Trailing type"}
    assert rows["All-or-None"] == "Yes"
    assert rows["Trailing amount"] == "1.5"
    # The control is what makes this able to fail: a plain body must NOT grow these rows.
    assert "All-or-None" not in control


def test_an_execution_attribute_this_package_has_never_heard_of_is_shown_not_hidden():
    """Unknown fails TOWARD the screen, which is the whole point of the mechanism.

    The attributes that matter are the ones nobody thought to enumerate: IBKR adds order
    fields, and a dialog built as an allow-list goes quiet on each new one while
    `place_order`'s `_`-strip keeps forwarding it. A key with no human label is rendered
    under its own name rather than dropped.
    """
    from ibkr_core_mcp.order_confirm import _order_rows

    rows = _order_rows(
        {
            "orderType": "LMT",
            "side": "BUY",
            "quantity": 1,
            "ticker": "GLD",
            "price": 300.0,
            "someFutureIBKRField": "surprising",
        },
        "U1",
    )
    assert rows["someFutureIBKRField"] == "surprising"


def test_ibkrs_own_lowercase_outside_rth_spelling_is_not_invisible():
    """IBKR writes `outsideRth` in the curl example and `outsideRTH` in the Python example
    on the SAME page. Only the capitalised form gets the typed `Outside RTH` row, so a
    caller copying IBKR's own curl example sent an execution attribute that no dialog
    mentioned. Measured live 2026-09-22, the gateway ACCEPTS that spelling and silently
    DISCARDS it — an order sent `outsideRth: true` read back `outside_rth: False` — so the
    row names it as ineffective rather than showing it as though it had applied.

    Source: https://www.interactivebrokers.com/docs/web-api/v1/endpoints/orders/place-order.md
    """
    from ibkr_core_mcp.order_confirm import _order_rows

    rows = _order_rows(
        {"orderType": "LMT", "side": "BUY", "quantity": 1, "ticker": "GLD", "price": 300.0, "outsideRth": True},
        "U1",
    )
    # The row does not merely SHOW the attribute — it says the attribute does nothing.
    # Measured live 2026-09-22: an order sent `outsideRth: true` read back
    # `outside_rth: False`, so the gateway accepts the key and silently discards it.
    # Showing it as a working attribute would trade one wrong impression for another.
    assert rows["outsideRth — IGNORED by IBKR (the effective field is outsideRTH)"] == "Yes"


def test_identity_routing_and_compliance_keys_stay_off_the_screen():
    """The counter-case, and the reason the suppression list exists (claudia_ui gap #40).

    Admitting execution attributes must NOT turn the dialog back into a body dump. `conid`,
    `acctId`, `cOID`/`parentId`, `secType` and `manualIndicator` (CME Rule 536-B metadata)
    identify or route the order; none of them changes how it executes, and the dialog is
    the most legible surface before an irreversible action, not a body dump.
    """
    from ibkr_core_mcp.order_confirm import _order_rows

    rows = _order_rows(
        {
            "conid": 649180671,
            "conidex": "649180671@CME",
            "acctId": "U123",
            "cOID": "C-1",
            "parentId": "C-1",
            "secType": "649180671:FUT",
            "manualIndicator": True,
            "orderType": "LMT",
            "side": "BUY",
            "quantity": 1,
            "ticker": "ES",
            "price": 7895.0,
        },
        "U1",
    )
    for hidden in ("conid", "conidex", "acctId", "cOID", "parentId", "secType", "manualIndicator"):
        assert hidden not in rows, f"{hidden} reached the screen"


def test_a_body_key_present_with_a_none_value_is_not_a_row():
    """`{"limit_price": None}` is an absent field spelled out, not an attribute. The same
    rule the `Outside RTH` row already applies — a present None is not a value — and the
    exact shape claudia_ui gap #40 complained about (`limit_price: None` on a cancel
    dialog)."""
    from ibkr_core_mcp.order_confirm import _order_rows

    rows = _order_rows(
        {
            "orderType": "LMT",
            "side": "BUY",
            "quantity": 1,
            "ticker": "GLD",
            "price": 300.0,
            "limit_price": None,
            "allOrNone": None,
        },
        "U1",
    )
    assert "limit_price" not in rows
    assert "All-or-None" not in rows
    assert "None" not in rows.values()


def test_the_bracket_dialog_does_not_mutate_the_tickets_it_is_given():
    """The dialog fills a child's MISSING contract keys from the parent so both legs are
    described alike on one screen. That inheritance is for the SCREEN: `confirm_bracket_dialog`
    is public API, a caller may hold those dicts and send them itself, and order parameters
    are immutable — a dialog that edits the order it is confirming is confirming a different
    order from the one it was handed.

    This is the discriminating half of the pair. Its twin in `tests/test_client.py`,
    `test_the_dialogs_inherited_keys_never_reach_the_wire`, cannot fail on this mutation:
    `place_bracket_and_confirm` builds its tickets from private copies before the dialog
    runs, so the wire is safe either way. Measured 2026-09-22 — that is exactly why this one
    exists, and why the twin's docstring says so.
    """
    import copy

    from ibkr_core_mcp.order_confirm import confirm_bracket_dialog

    parent = {
        "conid": 649180671,
        "cOID": "C-1",
        "ticker": "ES",
        "secType": "649180671:FUT",
        "side": "SELL",
        "quantity": 1,
        "orderType": "LMT",
        "price": 7725.0,
        "tif": "GTC",
        "_companyName": "ESU6 · SEP26",
        "_multiplier": 50,
        "_currency": "USD",
    }
    # No ticker, no secType, no display keys: the case inheritance exists for, and the shape
    # this package's own documented bracket example produces.
    children = [
        {
            "conid": 649180671,
            "parentId": "C-1",
            "side": "BUY",
            "quantity": 1,
            "orderType": "LMT",
            "price": 7700.0,
            "tif": "GTC",
        }
    ]
    parent_before, children_before = copy.deepcopy(parent), copy.deepcopy(children)

    with patch("ibkr_core_mcp.order_confirm._show_confirm_dialog") as mock_show:
        confirm_bracket_dialog(parent, children, "U1")

    # The screen DID inherit, or this test would pass by the mechanism never running.
    assert mock_show.call_args.kwargs["details"]["Profit taker — Symbol"] == "ES — ESU6 · SEP26"
    # ...and not one key of the caller's own dicts moved.
    assert parent == parent_before
    assert children == children_before


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
    assert details["Price"] == "100.00 USD" and details["Stop"] == "98.00 USD"
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
        "limit price 100.00 → 105.00\nquantity 1 → 3\ntif GTC → DAY\noutside rth No → Yes\nmystery 7 → ?"
    )


def test_reply_dialog_title_names_the_order_when_told():
    """With Gate 1 once per write (2026-09-11) this dialog is the only gate on a reply,
    so its title says which order it is about; the standalone reply path stays as it was."""
    from ibkr_core_mcp.order_confirm import confirm_reply_dialog

    with patch("ibkr_core_mcp.order_confirm._show_confirm_dialog") as mock_show:
        confirm_reply_dialog("11111111-1111-4111-8111-111111111111", "Confirm?", None, order_label="BUY 1 ES")
    assert mock_show.call_args.kwargs["title"] == "⚠  CONFIRM ORDER REPLY — BUY 1 ES"
    with patch("ibkr_core_mcp.order_confirm._show_confirm_dialog") as mock_show:
        confirm_reply_dialog("11111111-1111-4111-8111-111111111111", "Confirm?")
    assert mock_show.call_args.kwargs["title"] == "⚠  CONFIRM ORDER REPLY"


def _fake_appkit(detail_height: float = 90.0, disclaimer_height: float = 34.0):
    """A MagicMock AppKit: NSAlert confirms; attributed strings report the given heights."""
    ak = MagicMock()
    alert = ak.NSAlert.alloc.return_value.init.return_value
    alert.runModal.return_value = 1000
    detail = ak.NSMutableAttributedString.alloc.return_value.init.return_value
    detail.boundingRectWithSize_options_context_.return_value = MagicMock(size=MagicMock(height=detail_height))
    made = ak.NSAttributedString.alloc.return_value.initWithString_attributes_
    made.return_value.boundingRectWithSize_options_context_.return_value = MagicMock(
        size=MagicMock(height=disclaimer_height)
    )
    return ak


def test_dialog_renders_the_order_detail_bold_and_keeps_the_reading_order():
    """User design 2026-09-10/11: the full order detail on every pop-up, in bold.

    NSAlert informative text is plain, so detail and disclaimer live in the accessory view:
    detail (bold) above the disclaimer (regular) above the banner — the order read today.
    """
    import sys

    from ibkr_core_mcp._order_dialog import _run_alert

    ak = _fake_appkit()
    with patch.dict(sys.modules, {"AppKit": ak, "Foundation": MagicMock()}):
        _run_alert(
            {
                "title": "T",
                "details": {"Action": "BUY", "Symbol": "ES — ESU6", "Quantity": "1"},
                "disclaimer": "This is a LIVE order.",
                "confirm_label": "SEND",
                "abandon_label": "DO NOT SEND",
                "side": "BUY",
                "timeout_s": 1,
            }
        )
    alert = ak.NSAlert.alloc.return_value.init.return_value
    alert.setInformativeText_.assert_called_once_with("")
    made = ak.NSAttributedString.alloc.return_value.initWithString_attributes_
    disc_text, disc_attrs = made.call_args_list[-1].args
    assert disc_text == "This is a LIVE order."
    assert disc_attrs[ak.NSFontAttributeName] == ak.NSFont.systemFontOfSize_.return_value
    # container = banner 48 + gap 8 + disclaimer (34 + 2) + gap 8 + detail (90 + 2); the
    # container is the first rect made, the banner box the second; then the disclaimer field
    # sits just above the banner and the detail field above that — the reading order.
    rects = [c.args for c in ak.NSMakeRect.call_args_list]
    assert rects[0] == (0, 0, 420, 48 + 8 + 36 + 8 + 92)
    assert rects[1] == (0, 0, 420, 48)
    assert (8, 48 + 8, 404, 36) in rects  # disclaimer field
    assert (8, 48 + 8 + 36 + 8, 404, 92) in rects  # detail field, above it


def test_a_futures_price_is_not_a_currency_amount():
    """`Price: 7,900.00 USD` on an ES order was wrong: the price is 7,900 index points and the
    USD figure is the ×50 total (user, 2026-09-11). Futures price rows carry no currency;
    the total, which IS money, keeps it; a stock's price is money and keeps it too."""
    from ibkr_core_mcp.order_confirm import _order_rows

    fut = _order_rows(
        {
            "ticker": "ES",
            "side": "BUY",
            "quantity": 1,
            "orderType": "STOP_LIMIT",
            "price": 7895.0,
            "auxPrice": 7900.0,
            "tif": "GTC",
            "_multiplier": 50.0,
            "_currency": "USD",
        },
        "U1",
    )
    assert fut["Price"] == "7,895.00" and fut["Stop"] == "7,900.00"
    assert fut["Total (est.)"] == "394,750.00 USD (×50 multiplier)"
    unknown = _order_rows(
        {
            "ticker": "ES",
            "side": "BUY",
            "quantity": 1,
            "orderType": "STP",
            "price": 7900.0,
            "_multiplier_unknown": True,
            "_currency": "USD",
        },
        "U1",
    )
    assert unknown["Price"] == "7,900.00"
    stk = _order_rows(
        {"ticker": "AAPL", "side": "BUY", "quantity": 10, "orderType": "LMT", "price": 150.0, "_currency": "USD"},
        "U1",
    )
    assert stk["Price"] == "150.00 USD" and stk["Total (est.)"] == "1,500.00 USD"


def test_a_price_is_shown_to_its_own_precision_not_rounded_to_cents():
    """Two decimals is a currency habit, and most traded instruments do not tick in cents.

    `f"{float(v):,.2f}"` made a 6E limit of 1.08455 read `1.08`, a ZN 1/64 tick of
    110.171875 read `110.17`, and two NG prices a full tick apart render identically —
    on the last screen before Touch ID, while the body carried the full value
    (claudia_ui audit 2026-09-13, finding A-3). Two decimals stay the floor, so every
    round figure reads as it always did.
    """
    from ibkr_core_mcp.order_confirm import change_value_text

    assert change_value_text("limit_price", 1.08455) == "1.08455"
    assert change_value_text("limit_price", 110.171875) == "110.171875"
    assert change_value_text("stop_price", 4.1235) == "4.1235"
    assert change_value_text("stop_price", 4.1249) == "4.1249"
    # A full NG tick apart: these used to be the same string on screen.
    assert change_value_text("limit_price", 3.001) != change_value_text("limit_price", 3.002)
    # The floor and the separator are unchanged.
    assert change_value_text("limit_price", 6100.0) == "6,100.00"
    assert change_value_text("stop_price", 7950) == "7,950.00"
    assert change_value_text("limit_price", "100.5") == "100.50"


def test_price_text_safe_is_the_total_form_of_the_same_rule():
    """One definition of "render a broker price exactly", for every surface in both repos.

    `price_text` raises, deliberately, so a caller that must not print a non-number can say
    so. Every *display* surface needs the opposite: a render that dies is how a card
    disappears. Rather than each caller writing its own try/except — claudia_ui had two
    private copies of this rule and the dashboard a third — the total form lives here beside
    the strict one, and `change_value_text` is defined in terms of it.
    """
    from ibkr_core_mcp.order_confirm import price_text_safe

    # Exact where it can be.
    assert price_text_safe(1.08455) == "1.08455"
    assert price_text_safe(110.171875) == "110.171875"
    assert price_text_safe(6100.0) == "6,100.00"
    # Unchanged where it cannot: an IBKR string that already carries a separator, and the
    # non-numbers a `number`-typed field admits.
    assert price_text_safe("7,900.00") == "7,900.00"
    assert price_text_safe(float("nan")) == "nan"
    assert price_text_safe("n/a") == "n/a"
    assert price_text_safe("") == ""


def test_the_dialog_does_not_claim_an_order_type_requires_a_price():
    """Naming the gap is right; naming a requirement is a second false claim.

    The first version of the A-2 fix read `— (no price sent; a {type} order needs one)`,
    which is untrue of every type that legitimately carries none. MIDPRICE is the one this
    package documents itself: `claude_tools.py` calls `limit_price` an optional price cap
    for it, and `_preview_order` builds exactly that body. TRAIL and MOC are the same shape.
    Found by review 2026-09-14, and it is the defect A-2 fixed pointed the other way — the
    dialog stating something about the order that the order does not say.
    """
    from ibkr_core_mcp.order_confirm import _order_rows

    for order_type in ("MIDPRICE", "TRAIL", "MOC", "LMT"):
        rows = _order_rows(
            {"ticker": "AAPL", "side": "BUY", "quantity": 10, "orderType": order_type},
            "U1",
        )
        assert "needs one" not in rows["Price"], f"{order_type}: dialog asserted a requirement"
        assert "requires" not in rows["Price"], f"{order_type}: dialog asserted a requirement"
        assert order_type not in rows["Price"], f"{order_type}: the claim names the type"


def test_a_body_with_no_order_type_is_not_read_as_a_market_order():
    """`MARKET` was the default for a field the caller never sent.

    Harmless while it only filled a label; A-2 made it load-bearing, because `is_market`
    now decides whether a missing price is normal or a gap. A body IBKR would reject for
    having no `orderType` rendered as a complete market order (review 2026-09-14).
    """
    from ibkr_core_mcp.order_confirm import _order_rows

    for body in (
        {"ticker": "AAPL", "side": "BUY", "quantity": 10},
        {"ticker": "AAPL", "side": "BUY", "quantity": 10, "orderType": None},
        {"ticker": "AAPL", "side": "BUY", "quantity": 10, "orderType": ""},
    ):
        rows = _order_rows(body, "U1")
        assert rows["Order Type"] != "MARKET", f"{body} was labelled a market order"
        assert rows["Price"] != "MARKET", f"{body} was priced as a market order"
        assert rows["Total (est.)"] != "Market"


def test_price_text_refuses_a_non_finite_price():
    """The one branch that stops `NaN` appearing on an order dialog had no test.

    Both A-3 tests reach `price_text` through `change_value_text`, which swallows
    `InvalidOperation` — so the guard could have been deleted with the suite green
    (review 2026-09-14, W1).
    """
    from decimal import InvalidOperation

    import pytest as _pytest

    from ibkr_core_mcp.order_confirm import change_value_text, price_text

    for bad in (float("nan"), float("inf"), float("-inf")):
        with _pytest.raises(InvalidOperation):
            price_text(bad)
    # And the caller that is meant to survive it still does.
    assert change_value_text("limit_price", float("nan")) == "nan"


def test_price_text_does_not_render_an_unbounded_string():
    """A string price can carry any exponent; the row it becomes is read by a human.

    `price_text("1e-10000000")` returned a ten-million-character string, which
    `change_value_text` would have handed to the dialog as one row (review 2026-09-14).
    """
    from ibkr_core_mcp.order_confirm import price_text

    rendered = price_text("1e-10000000")
    assert len(rendered) < 40, f"{len(rendered)} characters reached the dialog"
    # The cap must not disturb anything a real instrument quotes.
    assert price_text(110.171875) == "110.171875"
    assert price_text(1.08455) == "1.08455"


def test_a_priced_order_type_without_a_price_is_never_labelled_market():
    """`Price: MARKET` beside `Order Type: LMT` described an order the body did not carry.

    The fallback was written for MKT, which legitimately sends no price, and applied to
    every type (claudia_ui audit 2026-09-13, finding A-2). The dialog is the last human
    surface before Touch ID, so it names the gap rather than guessing an order type.
    claudia_ui now rejects such a proposal before the button is drawn; this is the
    independent half, for every other caller of `place_order`.
    """
    from ibkr_core_mcp.order_confirm import _order_rows

    for order_type in ("LMT", "STP", "STOP_LIMIT"):
        rows = _order_rows(
            {
                "ticker": "AAPL",
                "side": "BUY",
                "quantity": 10,
                "orderType": order_type,
                "tif": "DAY",
                "_currency": "USD",
            },
            "U1",
        )
        assert rows["Price"] != "MARKET", f"{order_type} with no price was labelled MARKET"
        assert "no price" in rows["Price"], f"the {order_type} row does not name the gap"
        assert rows["Total (est.)"] != "Market", f"{order_type} totalled as a market order"

    market = _order_rows(
        {"ticker": "AAPL", "side": "BUY", "quantity": 10, "orderType": "MKT", "tif": "DAY"},
        "U1",
    )
    assert market["Price"] == "MARKET", "a real market order must still read MARKET"
    assert market["Total (est.)"] == "Market"


def test_dialog_bolds_the_values_not_the_labels():
    """User read of the first smoke (2026-09-11): bold is right, but for the values only —
    `Action:` regular, `BUY` bold — so each row is two runs, joined by regular newlines."""
    import sys

    from ibkr_core_mcp._order_dialog import _run_alert

    ak = _fake_appkit()
    with patch.dict(sys.modules, {"AppKit": ak, "Foundation": MagicMock()}):
        _run_alert(
            {
                "title": "T",
                "details": {"Action": "BUY", "Quantity": "1"},
                "disclaimer": "D",
                "confirm_label": "SEND",
                "abandon_label": "DO NOT SEND",
                "side": "BUY",
                "timeout_s": 1,
            }
        )
    made = ak.NSAttributedString.alloc.return_value.initWithString_attributes_
    bold = ak.NSFont.boldSystemFontOfSize_.return_value
    regular = ak.NSFont.systemFontOfSize_.return_value
    runs = [(c.args[0], c.args[1][ak.NSFontAttributeName]) for c in made.call_args_list]
    assert runs == [
        ("Action: ", regular),
        ("BUY", bold),
        ("\n", regular),
        ("Quantity: ", regular),
        ("1", bold),
        ("D", regular),
    ]


def test_futures_quantity_row_names_the_contract_size():
    """claudia_ui gap #45: `x50` used to ride on the Symbol line as if it were part of the
    contract's name. Size sits with size — the Quantity row — and only when the multiplier
    is known; a stock's quantity is plain shares."""
    from ibkr_core_mcp.order_confirm import _order_rows

    fut = _order_rows(
        {
            "ticker": "ES",
            "side": "BUY",
            "quantity": 1,
            "orderType": "STP",
            "price": 7900.0,
            "_multiplier": 50.0,
            "_currency": "USD",
        },
        "U1",
    )
    assert fut["Quantity"] == "1 (×50 per contract)"
    unknown = _order_rows(
        {
            "ticker": "ES",
            "side": "BUY",
            "quantity": 2,
            "orderType": "STP",
            "price": 7900.0,
            "_multiplier_unknown": True,
        },
        "U1",
    )
    assert unknown["Quantity"] == "2 (multiplier unknown)"
    stk = _order_rows(
        {"ticker": "AAPL", "side": "BUY", "quantity": 10, "orderType": "LMT", "price": 150.0, "_currency": "USD"}, "U1"
    )
    assert stk["Quantity"] == "10"


# ---------------------------------------------------------------------------
# SEC-09 — "Return cannot confirm" holds on all three renderers, by three
# different mechanisms. Each is checked against the renderer that implements it.
# ---------------------------------------------------------------------------


def test_the_osascript_dialog_makes_the_abandon_button_the_default():
    """The AppleScript renderer is the only one with a default button, and it is abandon.

    Driven rather than read: the script text is whatever `_show_osascript_dialog`
    actually hands to `osascript`, captured from the call.
    """
    from ibkr_core_mcp import order_confirm as oc

    captured: dict[str, str] = {}

    def fake_run(argv, **kwargs):
        captured["script"] = argv[-1]
        return MagicMock(returncode=0, stdout="SEND TO IBKR", stderr="")

    with patch("ibkr_core_mcp.order_confirm.subprocess.run", side_effect=fake_run):
        oc._show_osascript_dialog("LIVE ORDER CONFIRMATION", {"Symbol": "AAPL"}, "live", "SEND TO IBKR", "GO BACK")

    script = captured["script"]
    assert 'default button "GO BACK"' in script, f"the abandon button is not the AppleScript default:\n{script}"
    assert 'default button "SEND TO IBKR"' not in script, "Return would confirm the order on the osascript fallback"


def test_the_tkinter_dialog_gives_no_button_a_default_or_a_return_binding():
    """Tk's `Button` class binds `<space>` and the mouse — never `<Return>` (Tk's own
    `button.tcl`), so the non-macOS renderer refuses Return by adding nothing. This test
    fails if a future edit adds the `default=` option or binds a Return key to a button,
    either of which would hand the confirm button a keystroke.

    `SECURITY.md` § Gate 2 said "the default button is the abandon one" of all three
    renderers until 2026-09-17; that is the `osascript` mechanism alone (SEC-09).
    """
    from ibkr_core_mcp import order_confirm as oc

    button_kwargs: list[dict[str, Any]] = []
    commands: dict[str, Callable[[], None]] = {}

    def fake_button(parent, **kwargs):
        button_kwargs.append(kwargs)
        if kwargs.get("command"):
            commands[kwargs.get("text", "")] = kwargs["command"]
        return MagicMock()

    mock_tk = _make_tk_mock("SEND TO IBKR")
    mock_tk.Button.side_effect = fake_button
    mock_tk.Tk.return_value.mainloop.side_effect = lambda: commands["SEND TO IBKR"]()

    with patch.object(oc, "tk", mock_tk):
        oc._show_tkinter_dialog("LIVE ORDER CONFIRMATION", {"Symbol": "AAPL"}, "live", "SEND TO IBKR", "GO BACK")

    assert button_kwargs, "no buttons were built — the check would be vacuous"
    defaulted = [k.get("text") for k in button_kwargs if k.get("default")]
    assert not defaulted, f"these tkinter buttons are marked default: {defaulted}"

    dialog = mock_tk.Toplevel.return_value
    bound = [str(call.args[0]) for call in dialog.bind.call_args_list]
    assert not [b for b in bound if "Return" in b or "KP_Enter" in b], f"a Return key is bound on the dialog: {bound}"


# ---------------------------------------------------------------------------
# Gate 2 for a bracket — one dialog, both legs (claudia_ui gap #36, Phase 1 Task 1.1)
# ---------------------------------------------------------------------------


def _bracket_parent() -> dict[str, Any]:
    return {
        "ticker": "ES",
        "side": "SELL",
        "quantity": 1,
        "orderType": "LMT",
        "price": 7725.0,
        "tif": "GTC",
        "cOID": "CLAUDIA-1",
        "_multiplier": 50,
        "_currency": "USD",
        "_companyName": "ESU6 · SEP26 · expires 2026-09-18",
    }


def _bracket_child(**overrides: Any) -> dict[str, Any]:
    child = {
        "ticker": "ES",
        "side": "BUY",
        "quantity": 1,
        "orderType": "LMT",
        "price": 7700.0,
        "tif": "GTC",
        "parentId": "CLAUDIA-1",
    }
    child.update(overrides)
    return child


def _bracket_call(parent: dict[str, Any], children: list[dict[str, Any]]) -> dict[str, Any]:
    """Every kwarg `confirm_bracket_dialog` hands the shared renderer."""
    from ibkr_core_mcp.order_confirm import confirm_bracket_dialog

    with patch("ibkr_core_mcp.order_confirm._show_confirm_dialog") as mock_show:
        confirm_bracket_dialog(parent, children, "U1234567")
    return dict(mock_show.call_args.kwargs)


def _bracket_details(parent: dict[str, Any], children: list[dict[str, Any]]) -> dict[str, Any]:
    """Just the display rows."""
    return dict(_bracket_call(parent, children)["details"])


def test_bracket_dialog_shows_both_legs_in_one_call():
    """One Gate 2 for the pair: the human sees the parent AND the child before SEND.

    D4 — two dialogs would allow the parent to go with the child declined, the exact
    state the design forbids.
    """
    kwargs = _bracket_call(_bracket_parent(), [_bracket_child()])
    assert kwargs["title"] == "⚠  LIVE BRACKET ORDER CONFIRMATION"
    assert kwargs["confirm_label"] == "SEND TO IBKR"
    assert kwargs["abandon_label"] == "DO NOT SEND"
    d = kwargs["details"]
    assert d["Account"] == "U1234567"
    assert d["Parent — Symbol"] == "ES — ESU6 · SEP26 · expires 2026-09-18"
    assert d["Parent — Quantity"] == "1 (×50 per contract)"
    assert d["Parent — Order Type"] == "LMT"
    assert d["Parent — Price"] == "7,725.00"
    assert d["Parent — TIF"] == "GTC"
    assert d["Profit taker — Action"] == "BUY"
    assert d["Profit taker — Symbol"] == "ES — ESU6 · SEP26 · expires 2026-09-18"
    assert d["Profit taker — Order Type"] == "LMT"
    assert d["Profit taker — Price"] == "7,700.00"
    assert d["Profit taker — TIF"] == "GTC"


def test_bracket_dialog_says_the_child_is_held_never_working():
    """`PreSubmitted` is a working state for a single order and a HELD one for a bracket
    child (review 2026-09-08 item 2). The dialog must never call the child working."""
    d = _bracket_details(_bracket_parent(), [_bracket_child()])
    assert d["Profit taker"] == "held by IBKR until the parent fills"
    rendered = " ".join(f"{k}: {v}" for k, v in d.items()).lower()
    assert "working" not in rendered


def test_bracket_dialog_labels_the_notional_as_the_parents_only():
    """Review item 8: a bracket's two legs are OPPOSITE, so a row called `Total` would be
    read as their sum. Exactly one notional row, and it names whose it is."""
    d = _bracket_details(_bracket_parent(), [_bracket_child()])
    assert d["Parent notional (est.)"] == "386,250.00 USD (×50 multiplier)"
    assert "Total (est.)" not in d
    notionals = [k for k in d if "notional" in k.lower() or "total" in k.lower()]
    assert notionals == ["Parent notional (est.)"], notionals


def test_bracket_dialog_side_colour_is_the_parents():
    """`_extract_side` reads `Action`: it must be the PARENT's side. The banner is the
    pre-attentive cue, and a bracket's child is always the opposite side."""
    d = _bracket_details(_bracket_parent(), [_bracket_child()])
    assert d["Action"] == "SELL"


def test_bracket_dialog_refuses_a_child_on_the_same_side():
    from ibkr_core_mcp.order_confirm import confirm_bracket_dialog

    with patch("ibkr_core_mcp.order_confirm._show_confirm_dialog"), pytest.raises(HumanAuthError, match="opposite"):
        confirm_bracket_dialog(_bracket_parent(), [_bracket_child(side="SELL")], "U1234567")


def test_bracket_dialog_refuses_a_child_with_no_parent_link():
    """A child without `parentId` is a standalone opposite-side order — live immediately,
    able to open the wrong position (user rule 2026-09-07)."""
    from ibkr_core_mcp.order_confirm import confirm_bracket_dialog

    child = _bracket_child()
    del child["parentId"]
    with patch("ibkr_core_mcp.order_confirm._show_confirm_dialog"), pytest.raises(HumanAuthError, match="parent"):
        confirm_bracket_dialog(_bracket_parent(), [child], "U1234567")


def test_bracket_dialog_refuses_a_child_linked_to_a_different_parent():
    """Defence in depth behind `_bracket_tickets`: a `parentId` that is not this parent's
    `cOID` links the leg to some other order."""
    from ibkr_core_mcp.order_confirm import confirm_bracket_dialog

    with patch("ibkr_core_mcp.order_confirm._show_confirm_dialog"), pytest.raises(HumanAuthError, match="parent"):
        confirm_bracket_dialog(_bracket_parent(), [_bracket_child(parentId="SOMEONE-ELSE")], "U1234567")


def test_bracket_dialog_refuses_an_empty_child_list():
    """A bracket with no child is a plain order and must go through `confirm_order_dialog`,
    which the single-order tests pin."""
    from ibkr_core_mcp.order_confirm import confirm_bracket_dialog

    with patch("ibkr_core_mcp.order_confirm._show_confirm_dialog"), pytest.raises(HumanAuthError, match="no child"):
        confirm_bracket_dialog(_bracket_parent(), [], "U1234567")


def _bracket(parent_qty=1, child_qtys=(1, 1)):
    """A parent and one child per entry in `child_qtys`; None means the quantity is DERIVED."""
    parent = {
        "conid": 1,
        "cOID": "C-1",
        "side": "BUY",
        "quantity": parent_qty,
        "ticker": "F",
        "orderType": "LMT",
        "price": 13.0,
        "tif": "GTC",
    }
    kinds = ["LMT", "STP", "STP", "STP"]
    children = []
    for i, qty in enumerate(child_qtys):
        kid = {"parentId": "C-1", "side": "SELL", "orderType": kinds[i], "price": 14.0 + i, "tif": "GTC"}
        if qty is not None:
            kid["quantity"] = qty
        children.append(kid)
    return parent, children


def test_a_multi_child_bracket_discloses_that_the_children_outsize_the_parent():
    """A two-child bracket renders two full-size SELLs under a one-lot BUY, and nothing said
    only one of them can fill — so the arithmetic read as an instruction to sell twice what
    was being bought. That is the alarming reading and the wrong one.

    The disclosure is NOT a guardrail: IBKR's own published bracket is a full-size profit
    taker AND a full-size stop on one position (50/50/50), so refusing the aggregate would
    refuse the standard shape. See `_bracket_tickets` for why H1 stays per-child.
    """
    details = _bracket_details(*_bracket(parent_qty=1, child_qtys=(1, 1)))
    disclosure = details["Children together"]
    assert "total 2 against a parent of 1" in disclosure
    assert "one filling cancels the others" in disclosure
    # Dated and hedged, never stated as a permanent guarantee about THIS order.
    assert "2026-09-22" in disclosure
    assert "cannot verify the link for the order about to be submitted" in disclosure
    # The partial-fill unknown is disclosed, not policed.
    assert "PARTIALLY" in disclosure


@pytest.mark.parametrize(
    ("why", "parent_qty", "child_qtys"),
    [
        ("a single child cannot outsize anything by aggregation", 1, (1,)),
        ("a genuine scale-out does not oversubscribe the parent", 3, (1, 1)),
        ("equal aggregate is not an excess", 2, (1, 1)),
    ],
)
def test_the_aggregate_disclosure_stays_quiet_when_there_is_nothing_to_disclose(why, parent_qty, child_qtys):
    """The counter-cases, and what makes the test above discriminating rather than a banner
    printed on every bracket. A warning shown always is a warning read never."""
    details = _bracket_details(*_bracket(parent_qty=parent_qty, child_qtys=child_qtys))
    assert "Children together" not in details, why


def test_a_child_with_no_stated_quantity_counts_as_full_size_in_the_disclosure():
    """`_bracket_tickets` documents an absent child quantity as DERIVED from the parent, so
    an all-derived two-child bracket is two full-size legs and the arithmetic is still
    exact. Counting an absent quantity as ZERO would suppress the disclosure on exactly the
    bracket that most needs it — the one whose legs the caller never sized by hand."""
    details = _bracket_details(*_bracket(parent_qty=1, child_qtys=(None, None)))
    assert "total 2 against a parent of 1" in details["Children together"]


def test_the_disclosure_drops_the_arithmetic_when_the_parent_states_no_quantity():
    """The only case where the numbers cannot be stated. The disclosure must still appear —
    the mutual-exclusivity point does not depend on arithmetic — but it must not invent a
    total it cannot compute, which is this package's rule everywhere else on this dialog
    (an unknown is named, never guessed)."""
    parent, children = _bracket(parent_qty=1, child_qtys=(None, None))
    del parent["quantity"]
    disclosure = _bracket_details(parent, children)["Children together"]
    assert "each sized to the full parent quantity" in disclosure
    assert "total" not in disclosure.split("They are exits")[0]


def test_bracket_dialog_child_inherits_the_parents_contract_display_keys():
    """Both legs are the SAME contract (D2), so both must render the same way.

    Measured 2026-09-21 by rendering one ES bracket both ways through `_order_rows`: without
    inheritance the child's Symbol row drops to `ES` where the parent reads
    `ES — ESU6 · SEP26 · expires 2026-09-18`, and its Quantity to `1` where the parent reads
    `1 (×50 per contract)`. One instrument, one dialog, two descriptions — and the leg
    missing its month and multiplier is the one the human has never seen before.

    The price rows do NOT diverge: a bare child carries no `_currency` either, so both
    render `7,7xx.00`. An earlier version of this test asserted `"USD" not in` the child's
    price, which passes with or without the fix — a test that cannot fail is not a control.
    """
    d = _bracket_details(_bracket_parent(), [_bracket_child()])
    assert d["Profit taker — Symbol"] == d["Parent — Symbol"] == "ES — ESU6 · SEP26 · expires 2026-09-18"
    assert d["Profit taker — Quantity"] == d["Parent — Quantity"] == "1 (×50 per contract)"


def test_bracket_dialog_never_overrides_a_display_key_the_child_carries():
    """Inheritance fills gaps; it never overwrites what the caller established."""
    d = _bracket_details(_bracket_parent(), [_bracket_child(_companyName="ITS OWN LABEL", _multiplier=50)])
    assert d["Profit taker — Symbol"] == "ES — ITS OWN LABEL"


# The two futures signals added on 2026-09-21 — `secType` and `manualIndicator` — are read
# by `_order_rows` but were not inherited by a bracket child, so one ES bracket rendered:
#
#   Parent — Price         7,300.00        (recognised as a future: no currency on points)
#   Profit taker — Price   7,400.00 USD    (not recognised: index points labelled dollars)
#
# which is the divergence `_CONTRACT_DISPLAY_KEYS` exists to prevent, and which its own
# comment says was measured NOT to happen — a measurement taken with `_multiplier` set,
# before the two new doors existed. 7,400 points is 370,000 USD, not 7,400.


@pytest.mark.parametrize("signal", [{"manualIndicator": True}, {"secType": "649180671:FUT"}])
def test_bracket_dialog_legs_agree_on_the_instrument_class_however_it_was_declared(signal):
    """Both legs of one futures bracket must price in the same units. A child inherits the
    parent's instrument class whichever of the four signals established it."""
    parent = {
        "cOID": "C-1",
        "conid": 1,
        "ticker": "ES",
        "side": "BUY",
        "quantity": 1,
        "orderType": "LMT",
        "price": 7300.0,
        "_currency": "USD",
        **signal,
    }
    child = {
        "parentId": "C-1",
        "conid": 1,
        "ticker": "ES",
        "side": "SELL",
        "quantity": 1,
        "orderType": "LMT",
        "price": 7400.0,
    }
    d = _bracket_details(parent, [child])
    assert "USD" not in d["Parent — Price"], d["Parent — Price"]
    assert "USD" not in d["Profit taker — Price"], (
        f"index points labelled as currency on the leg the human has never seen: {d['Profit taker — Price']!r}"
    )


def test_bracket_dialog_still_shows_the_currency_on_BOTH_legs_of_an_equity_bracket():
    """The discriminating half. Inheriting the instrument class must not suppress the
    currency for a stock, whose price really is quoted in money — a blanket change would
    strip `USD` from every equity bracket."""
    parent = {
        "cOID": "C-1",
        "conid": 265598,
        "ticker": "AAPL",
        "side": "BUY",
        "quantity": 10,
        "orderType": "LMT",
        "price": 150.0,
        "secType": "265598:STK",
        "_currency": "USD",
    }
    child = {
        "parentId": "C-1",
        "conid": 265598,
        "ticker": "AAPL",
        "side": "SELL",
        "quantity": 10,
        "orderType": "LMT",
        "price": 160.0,
    }
    d = _bracket_details(parent, [child])
    assert "USD" in d["Parent — Price"], d["Parent — Price"]
    assert "USD" in d["Profit taker — Price"], d["Profit taker — Price"]


def test_bracket_dialog_does_not_MUTATE_the_tickets_it_is_shown():
    """The inheritance must stay inside the dialog's own display copy.

    Two of the inherited keys — `secType` and `manualIndicator` — are REAL IBKR body
    fields, not `_`-prefixed display keys, so writing them onto the caller's child dict
    would add fields to a ticket the caller never declared. Gate 2 reads the order; it does
    not edit it.

    This is deliberately a test of the DIALOG and not of `place_bracket_and_confirm`: that
    method builds its ticket array before the dialog runs, so no change here could reach
    the wire through it, and a test written against it would be unable to fail. Verified
    discriminating by replacing the merged copy with `child.update(inherited)`, which fails
    on the `secType` assertion below.
    """
    from ibkr_core_mcp.order_confirm import confirm_bracket_dialog

    parent = {
        "cOID": "C-1",
        "conid": 1,
        "ticker": "ES",
        "side": "BUY",
        "quantity": 1,
        "orderType": "LMT",
        "price": 7300.0,
        "secType": "649180671:FUT",
        "manualIndicator": True,
        "_currency": "USD",
        "_companyName": "ESZ6",
    }
    child = {
        "parentId": "C-1",
        "conid": 1,
        "ticker": "ES",
        "side": "SELL",
        "quantity": 1,
        "orderType": "LMT",
        "price": 7400.0,
    }
    parent_before, child_before = dict(parent), dict(child)
    with patch("ibkr_core_mcp.order_confirm._show_confirm_dialog"):
        confirm_bracket_dialog(parent, [child], "U1234567")
    assert child == child_before, f"Gate 2 edited the child ticket: {child!r}"
    assert parent == parent_before, f"Gate 2 edited the parent ticket: {parent!r}"


def test_bracket_dialog_formats_every_value_through_the_one_row_builder():
    """Review item 8 — one formatter, not two.

    Every currency, precision, multiplier and missing-price rule lives in `_order_rows`.
    A second formatter for the bracket would drift from it silently, which is how the
    same price came to render two ways in one dialog before (claudia_ui gap #46). This
    pins the call, not the appearance: mutate `_order_rows` and this test goes red.
    """
    import ibkr_core_mcp.order_confirm as oc

    with (
        patch.object(oc, "_order_rows", wraps=oc._order_rows) as spy,
        patch.object(oc, "_show_confirm_dialog"),
    ):
        oc.confirm_bracket_dialog(_bracket_parent(), [_bracket_child()], "U1234567")
    assert spy.call_count == 2, "each leg must be rendered by the shared row builder"


def test_bracket_dialog_shows_a_stop_loss_child_under_its_own_name():
    """D1 makes the profit taker v1, but the signature takes a list and a `stop_loss`
    sibling is designed to be additive — a STP child must not be labelled a profit taker."""
    d = _bracket_details(_bracket_parent(), [_bracket_child(orderType="STP", price=None, auxPrice=7800.0)])
    assert d["Stop loss"] == "held by IBKR until the parent fills"
    assert "Profit taker" not in d


def test_bracket_dialog_shows_the_outside_rth_attribute_of_each_leg():
    """R4 (user, 2026-09-21): the child inherits the parent's `outsideRTH`. The dialog
    shows what each ticket actually carries — it derives nothing here."""
    d = _bracket_details(_bracket_parent() | {"outsideRTH": True}, [_bracket_child(outsideRTH=True)])
    assert d["Parent — Outside RTH"] == "Yes"
    assert d["Profit taker — Outside RTH"] == "Yes"


def test_bracket_dialog_refuses_a_parent_with_no_side():
    """The opposite-side rule is unverifiable without the parent's side, and the banner
    colour is the pre-attentive cue. Unknown must not be able to pass as checked."""
    from ibkr_core_mcp.order_confirm import confirm_bracket_dialog

    parent = _bracket_parent()
    del parent["side"]
    with patch("ibkr_core_mcp.order_confirm._show_confirm_dialog"), pytest.raises(HumanAuthError, match="side"):
        confirm_bracket_dialog(parent, [_bracket_child()], "U1234567")


def test_bracket_dialog_shows_every_child_when_two_are_the_same_kind():
    """Two legs of one kind must not collapse into one set of rows.

    The rows are keyed by the leg's label, so a second profit taker (a scale-out) would
    overwrite the first — and the human would authorise two live children having seen one.
    """
    d = _bracket_details(
        _bracket_parent(),
        [_bracket_child(price=7700.0), _bracket_child(price=7650.0)],
    )
    assert d["Profit taker"] == "held by IBKR until the parent fills"
    assert d["Profit taker 2"] == "held by IBKR until the parent fills"
    assert d["Profit taker — Price"] == "7,700.00"
    assert d["Profit taker 2 — Price"] == "7,650.00"


def test_bracket_dialog_refuses_a_child_on_a_different_contract():
    """A mismatched contract is refused in TWO places, and this is the second of them.

    `client._bracket_tickets` checks it with the other structural rules, so the place path
    refuses before Touch ID. This copy is not redundant: `confirm_bracket_dialog` is public
    API and can be called without that method, and the check must run BEFORE the display keys
    are inherited a few lines below — inheriting the parent's `_companyName` onto a mismatched
    child would render the parent's own contract name on the child's rows and hide the
    mismatch on the last screen before the send.

    Neither copy can be replaced by the preview. Phase 0 measured live on 2026-09-20 that a
    child on a *different instrument* returns a whatif response byte-identical to a valid one,
    because the preview reads the first ticket and silently discards the rest (claudia_ui gap
    #36). A bracket whose "profit taker" is on another contract previews clean, so without
    these two checks it would reach IBKR as a resting order on an instrument the human never
    authorised.
    """
    from ibkr_core_mcp.order_confirm import confirm_bracket_dialog

    parent = _bracket_parent() | {"conid": 649180671}
    child = _bracket_child(conid=999999999)
    with patch("ibkr_core_mcp.order_confirm._show_confirm_dialog"), pytest.raises(HumanAuthError, match="contract"):
        confirm_bracket_dialog(parent, [child], "U1234567")


def test_bracket_dialog_accepts_a_child_that_names_the_same_contract():
    """The check is a mismatch refusal, not a requirement that the child carry a conid."""
    d = _bracket_details(_bracket_parent() | {"conid": 649180671}, [_bracket_child(conid=649180671)])
    assert d["Profit taker"] == "held by IBKR until the parent fills"


def test_bracket_dialog_accepts_a_child_that_carries_no_conid_of_its_own():
    """The child's conid is derived from the parent (D2), so a ticket without one is normal
    and must not be refused — only a stated mismatch is."""
    d = _bracket_details(_bracket_parent() | {"conid": 649180671}, [_bracket_child()])
    assert d["Profit taker"] == "held by IBKR until the parent fills"


# ---------------------------------------------------------------------------
# Gate 2 must not degrade SILENTLY when a caller omits display-only keys.
# Both defects below were reproduced LIVE on 2026-09-21 by probe scripts that
# called this package directly, not through claudia_ui. claudia_ui's own path
# always supplies the keys (_apply_futures_display_facts sets either
# _multiplier or _multiplier_unknown, never neither), so neither defect is
# reachable from the shipping UI — but order_confirm is public API and the
# guarantee cannot rest on every caller remembering.
# ---------------------------------------------------------------------------


def _total_row(order: dict[str, object]) -> str:
    from ibkr_core_mcp.order_confirm import confirm_order_dialog

    with patch("ibkr_core_mcp.order_confirm._show_confirm_dialog") as mock_show:
        confirm_order_dialog(order, "U1234567")
    return str(mock_show.call_args.kwargs["details"].get("Total (est.)"))


def test_a_futures_order_with_manual_indicator_never_prints_price_times_quantity():
    """The live defect: an ES body carrying manualIndicator (CME 536-B, FUT/FOP only) but
    neither multiplier key printed `Total (est.): 7,300.00` for a contract worth 365,000.

    That is not an estimate, it is the notional divided by 50 — the same wrong number the
    2026-09-04 fix was written for, reached through a door that fix did not cover.
    """
    total = _total_row(
        {
            "ticker": "ES",
            "side": "BUY",
            "quantity": 1,
            "orderType": "LMT",
            "price": 7300.00,
            "tif": "GTC",
            "manualIndicator": True,
        }
    )
    assert "7,300.00" not in total, f"printed a 50x-wrong notional as fact: {total!r}"
    assert "multiplier unknown" in total


# IBKR's place-order body spells `secType` with the CONID IN FRONT of the asset class —
# `"265598@STK"` in its Python example and `"265598:STK"` in its JSON example, the only two
# worked examples the endpoint publishes. The `api-reference` field table calls it "IB asset
# class identifier" and gives no format at all. A matcher comparing the WHOLE string to
# "FUT"/"FOP" therefore recognises no body IBKR documents, and an ES order carrying
# `secType: "649180671:FUT"` printed `Total (est.): 7,300.00` for a contract standing for
# 365,000 — the same 50x-wrong notional the multiplier rules exist to prevent, reached
# through the signal added to prevent it (review 2026-09-21).
#
# The bare form is kept: a caller may still send one, and refusing it would narrow the
# guarantee. Every spelling is one asset class, so every spelling must classify.
# Source: https://www.interactivebrokers.com/docs/web-api/v1/endpoints/orders/place-order.md
#         https://www.interactivebrokers.com/docs/web-api/api-reference/trading/trading-orders/submit-new-order.md
_FUTURES_SEC_TYPES = ["FUT", "FOP", "649180671:FUT", "649180671@FUT", "649180671:FOP", "fut"]


@pytest.mark.parametrize("sec_type", _FUTURES_SEC_TYPES)
def test_a_futures_order_is_recognised_however_ibkr_spells_secType(sec_type):
    """The guarantee through `secType` rather than 536-B, for every spelling IBKR uses."""
    total = _total_row(
        {
            "ticker": "ES",
            "side": "BUY",
            "quantity": 1,
            "orderType": "LMT",
            "price": 7300.00,
            "tif": "GTC",
            "secType": sec_type,
        }
    )
    assert "7,300.00" not in total, f"printed a 50x-wrong notional as fact for {sec_type!r}: {total!r}"
    assert "multiplier unknown" in total


@pytest.mark.parametrize("sec_type", ["STK", "265598:STK", "265598@STK"])
def test_a_stock_order_STILL_prints_its_total_however_secType_is_spelled(sec_type):
    """The discriminating half of the parse. Widening the match must not swallow equities:
    a stock's multiplier is 1, so price x quantity is the right number and must keep
    printing. A parse that returned the conid, or the whole string, would break this."""
    total = _total_row(
        {
            "ticker": "AAPL",
            "side": "BUY",
            "quantity": 10,
            "orderType": "LMT",
            "price": 150.00,
            "tif": "DAY",
            "secType": sec_type,
            "_currency": "USD",
        }
    )
    assert "1,500.00" in total, total


def test_a_stock_order_without_multiplier_keys_STILL_prints_its_total():
    """The discriminating half. A stock's multiplier is 1, so price x quantity is correct and
    must keep printing — claudia_ui sends no `secType` and no multiplier keys for equities, so
    a blanket refusal would blank the total on every real stock dialog."""
    total = _total_row(
        {
            "ticker": "AAPL",
            "side": "BUY",
            "quantity": 10,
            "orderType": "LMT",
            "price": 150.00,
            "tif": "DAY",
            "_currency": "USD",
        }
    )
    assert "1,500.00" in total, total


def test_cancel_dialog_without_detail_NAMES_the_gap_instead_of_hiding_it():
    """Reproduced live 2026-09-21: a detail-less cancel rendered Order ID + Account and nothing
    else, so the human authorised the cancellation of an order id they could not verify. An
    order id is not human-checkable; with several orders resting, nothing on that screen
    distinguishes a disposable test order from the stop protecting a real position.

    The id-only SHAPE is not the defect — being silent about it is. This previously asserted
    the bare two-key dict (test renamed from ..._keeps_the_id_only_shape).
    """
    from ibkr_core_mcp.order_confirm import confirm_cancel_dialog

    with patch("ibkr_core_mcp.order_confirm._show_confirm_dialog") as mock_show:
        confirm_cancel_dialog("ORD456", "U1234567")
    details = mock_show.call_args.kwargs["details"]
    assert details["Order ID"] == "ORD456"
    assert details["Account"] == "U1234567"
    joined = " ".join(f"{k} {v}" for k, v in details.items()).lower()
    assert "not available" in joined, f"degraded silently: {details!r}"


def test_bracket_dialog_ALSO_refuses_a_child_larger_than_the_parent():
    """H1 at Gate 2, not only at `_bracket_tickets`.

    The dialog already repeats the link and contract rules, and its docstring gives the reason:
    it is public API and callable without the ticket builder. H1 belongs in that same set — this
    is the last screen before an irreversible write, and a rule enforced in only one of two
    reachable paths is enforced in neither when the other one is taken.
    """
    from ibkr_core_mcp.order_confirm import confirm_bracket_dialog

    parent = {"cOID": "C-1", "conid": 1, "side": "SELL", "quantity": 1, "orderType": "LMT", "price": 10.0}
    child = {"parentId": "C-1", "conid": 1, "side": "BUY", "quantity": 2, "orderType": "LMT", "price": 9.0}
    with (
        patch("ibkr_core_mcp.order_confirm._show_confirm_dialog") as mock_show,
        pytest.raises(HumanAuthError, match="larger than the parent"),
    ):
        confirm_bracket_dialog(parent, [child], "U1234567")
    mock_show.assert_not_called()


# `confirm_bracket_dialog`'s `Raises:` lists six refusals. Three of them had an escape
# clause its twin `_bracket_tickets` does not have, measured 2026-09-21 by driving each:
#
#   child 5, parent states NO quantity                   -> ACCEPTED (H1 skipped entirely)
#   child quantity 'abc', parent states NO quantity      -> ACCEPTED
#   parent has NO cOID, child parentId = another order   -> ACCEPTED
#
# All three are unreachable through `place_bracket_and_confirm`, which runs the ticket
# builder first — and that is the point: the ONLY reason these rules are repeated in the
# dialog is that it is public API callable without the ticket builder, which is exactly the
# path on which they did not hold. `_bracket_tickets` states the principle the dialog broke:
# "A quantity that cannot be compared is refused rather than assumed compliant, so the rule
# cannot be walked through by a malformed value."


def test_bracket_dialog_refuses_an_oversized_child_when_the_PARENT_states_no_quantity():
    """`and parent.get("quantity") is not None` was the walk-through: a parent with no
    quantity disabled H1 rather than making the pair unverifiable."""
    from ibkr_core_mcp.order_confirm import confirm_bracket_dialog

    parent = {"cOID": "C-1", "conid": 1, "side": "SELL", "orderType": "LMT", "price": 10.0}
    child = {"parentId": "C-1", "conid": 1, "side": "BUY", "quantity": 5, "orderType": "LMT", "price": 9.0}
    with (
        patch("ibkr_core_mcp.order_confirm._show_confirm_dialog") as mock_show,
        pytest.raises(HumanAuthError, match="quantity"),
    ):
        confirm_bracket_dialog(parent, [child], "U1234567")
    mock_show.assert_not_called()


def test_bracket_dialog_refuses_an_UNPARSEABLE_child_quantity_even_with_no_parent_quantity():
    """The same hole, reached with a malformed value instead of a large one. With a parent
    quantity present this already refused; without one it did not run at all."""
    from ibkr_core_mcp.order_confirm import confirm_bracket_dialog

    parent = {"cOID": "C-1", "conid": 1, "side": "SELL", "orderType": "LMT", "price": 10.0}
    child = {"parentId": "C-1", "conid": 1, "side": "BUY", "quantity": "abc", "orderType": "LMT", "price": 9.0}
    with (
        patch("ibkr_core_mcp.order_confirm._show_confirm_dialog") as mock_show,
        pytest.raises(HumanAuthError, match="quantity"),
    ):
        confirm_bracket_dialog(parent, [child], "U1234567")
    mock_show.assert_not_called()


def test_bracket_dialog_refuses_a_parent_carrying_NO_cOID():
    """The docstring lists "a child linked to some other order" as a refusal, and the check
    was `if parent_coid and link != parent_coid` — so a parent with no cOID silently disabled
    it. A child whose `parentId` cannot be checked against this parent may be attaching to
    someone else's resting order, which is worse than being standalone, and the dialog is the
    last screen before the write. `_bracket_tickets` has required a parent cOID all along.
    """
    from ibkr_core_mcp.order_confirm import confirm_bracket_dialog

    parent = {"conid": 1, "side": "SELL", "quantity": 1, "orderType": "LMT", "price": 10.0}
    child = {
        "parentId": "SOMEONE-ELSES-ORDER",
        "conid": 1,
        "side": "BUY",
        "quantity": 1,
        "orderType": "LMT",
        "price": 9.0,
    }
    with (
        patch("ibkr_core_mcp.order_confirm._show_confirm_dialog") as mock_show,
        pytest.raises(HumanAuthError, match="cOID"),
    ):
        confirm_bracket_dialog(parent, [child], "U1234567")
    mock_show.assert_not_called()


def test_bracket_dialog_refuses_a_child_carrying_its_OWN_cOID():
    """IBKR: a cOID "should not be set for the child of a bracket order". `_bracket_tickets`
    refuses one; the dialog did not, so the rule held on one of two reachable paths.
    Source: https://ibkrcampus.com/docs/web-api/api-reference/trading/trading-orders/submit-new-order.md
    """
    from ibkr_core_mcp.order_confirm import confirm_bracket_dialog

    parent = {"cOID": "C-1", "conid": 1, "side": "SELL", "quantity": 1, "orderType": "LMT", "price": 10.0}
    child = {
        "parentId": "C-1",
        "cOID": "CHILD-OWN",
        "conid": 1,
        "side": "BUY",
        "quantity": 1,
        "orderType": "LMT",
        "price": 9.0,
    }
    with (
        patch("ibkr_core_mcp.order_confirm._show_confirm_dialog") as mock_show,
        pytest.raises(HumanAuthError, match="cOID"),
    ):
        confirm_bracket_dialog(parent, [child], "U1234567")
    mock_show.assert_not_called()


def test_bracket_dialog_still_accepts_a_child_that_carries_NO_quantity():
    """The discriminating half of the H1 tightening. A child's quantity is DERIVED from the
    parent, so an absent one is the normal case and must not be swept up by refusing an
    absent PARENT quantity. Refusing this would refuse a legitimate bracket."""
    from ibkr_core_mcp.order_confirm import confirm_bracket_dialog

    parent = {"cOID": "C-1", "conid": 1, "side": "SELL", "quantity": 1, "orderType": "LMT", "price": 10.0}
    child = {"parentId": "C-1", "conid": 1, "side": "BUY", "orderType": "LMT", "price": 9.0}
    with patch("ibkr_core_mcp.order_confirm._show_confirm_dialog") as mock_show:
        confirm_bracket_dialog(parent, [child], "U1234567")
    mock_show.assert_called_once()


def test_bracket_dialog_accepts_an_equal_and_a_smaller_child():
    """The discriminating half — H1 is a ceiling, not an equality, and equal is the normal case."""
    from ibkr_core_mcp.order_confirm import confirm_bracket_dialog

    parent = {"cOID": "C-1", "conid": 1, "side": "SELL", "quantity": 5, "orderType": "LMT", "price": 10.0}
    for qty in (5, 2):
        child = {"parentId": "C-1", "conid": 1, "side": "BUY", "quantity": qty, "orderType": "LMT", "price": 9.0}
        with patch("ibkr_core_mcp.order_confirm._show_confirm_dialog") as mock_show:
            confirm_bracket_dialog(parent, [child], "U1234567")
        mock_show.assert_called_once()
