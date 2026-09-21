import itertools
import pathlib
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, call, patch
from unittest.mock import patch as _patch

import pytest

from ibkr_core_mcp.exceptions import ConfigError, HumanAuthError, IBKRAPIError
from tests.security.structural import annotation_names_a_model, response_model_names

# The `client` fixture lives in tests/conftest.py (shared with tests/security/).


def test_ping_returns_false_on_401(client):
    with patch.object(client._session, "get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_get.return_value = mock_resp
        assert client.ping() is False


def test_ping_returns_true_when_authenticated(client):
    with patch.object(client._session, "get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"authenticated": True}
        mock_get.return_value = mock_resp
        assert client.ping() is True


def test_search_contract_returns_list(client):
    with patch.object(client._session, "get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [{"conid": 265598, "symbol": "AAPL", "secType": "STK"}]
        mock_get.return_value = mock_resp
        result = client.search_contract("AAPL")
    assert isinstance(result, list)
    assert result[0]["conid"] == 265598


def test_get_market_history_passes_params(client):
    with patch.object(client._session, "get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": []}
        mock_get.return_value = mock_resp
        client.get_market_history(265598, period="1Y", bar="1d")
    call_kwargs = mock_get.call_args
    assert "conid=265598" in str(call_kwargs) or "265598" in str(call_kwargs)


def test_get_alert_calls_correct_endpoint(client):
    """Per official docs (cpapi-v1#get-alert), the endpoint is not account-scoped
    in the URL and requires type=Q — unlike the other alert endpoints, which are
    all /iserver/account/{accountId}/alert...
    """
    with patch.object(client._session, "get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"orderId": 9876543210, "alertName": "AAPL >= 200"}
        mock_get.return_value = mock_resp
        result = client.get_alert("9876543210")
    url = mock_get.call_args[0][0]
    params = mock_get.call_args.kwargs.get("params")
    assert url == f"{client._base}/iserver/account/alert/9876543210"
    assert params == {"type": "Q"}
    assert result["alertName"] == "AAPL >= 200"


# ── /iserver/accounts prerequisite (get_brokerage_accounts / _ensure_accounts_initialized) ──


def test_get_brokerage_accounts_calls_correct_endpoint(client):
    with patch.object(client._session, "get") as mock_get:
        mock_get.return_value = _make_ok_response({"accounts": ["U1234567"], "selectedAccount": "U1234567"})
        result = client.get_brokerage_accounts()
    url = mock_get.call_args[0][0]
    assert url == f"{client._base}/iserver/accounts"
    assert result["selectedAccount"] == "U1234567"


def test_ensure_accounts_initialized_calls_once(client):
    client._accounts_initialized = False
    with patch.object(client._session, "get") as mock_get:
        mock_get.return_value = _make_ok_response({"accounts": ["U1234567"]})
        client._ensure_accounts_initialized()
        client._ensure_accounts_initialized()
    mock_get.assert_called_once()
    assert client._accounts_initialized is True


def test_get_live_orders_initializes_accounts_first(client):
    client._accounts_initialized = False
    with patch.object(client._session, "get") as mock_get, patch("time.sleep"):
        mock_get.return_value = _make_ok_response({"orders": []})
        client.get_live_orders()
    first_call_url = mock_get.call_args_list[0][0][0]
    assert first_call_url == f"{client._base}/iserver/accounts"
    assert client._accounts_initialized is True


def test_place_order_initializes_accounts_before_touch_id(client):
    client._accounts_initialized = False
    order = {"ticker": "AAPL", "side": "BUY", "quantity": 100}
    with (
        _patch("ibkr_core_mcp.client.require_touch_id") as mock_tid,
        _patch("ibkr_core_mcp.client.confirm_order_dialog"),
        patch.object(client._session, "get") as mock_get,
        _patch.object(client._session, "post") as mock_post,
    ):
        mock_get.return_value = _make_ok_response({"accounts": ["U1234567"]})
        mock_post.return_value = _make_ok_response([{"orderId": "1"}])
        client.place_order("U1234567", order)
    mock_get.assert_called_once_with(f"{client._base}/iserver/accounts", params=None, timeout=30)
    mock_tid.assert_called_once()
    assert client._accounts_initialized is True


def test_get_order_preview_initializes_accounts(client):
    client._accounts_initialized = False
    order = {"ticker": "AAPL", "side": "BUY", "quantity": 100}
    with patch.object(client._session, "get") as mock_get, _patch.object(client._session, "post") as mock_post:
        mock_get.return_value = _make_ok_response({"accounts": ["U1234567"]})
        mock_post.return_value = _make_ok_response({"equity": 5000})
        client.get_order_preview("U1234567", order)
    mock_get.assert_called_once()
    assert client._accounts_initialized is True


# Integration tests — require live gateway
@pytest.mark.integration
def test_live_ping(mock_config):
    from ibkr_core_mcp.auth import BrowserCookieAuth
    from ibkr_core_mcp.client import IBKRClient

    client = IBKRClient(mock_config, auth=BrowserCookieAuth())
    assert client.ping() is True


@pytest.mark.integration
def test_live_search_aapl(mock_config):
    from ibkr_core_mcp.auth import BrowserCookieAuth
    from ibkr_core_mcp.client import IBKRClient

    client = IBKRClient(mock_config, auth=BrowserCookieAuth())
    results = client.search_contract("AAPL")
    assert len(results) > 0
    assert any(r.get("symbol") == "AAPL" for r in results)


# ---------------------------------------------------------------------------
# Order gate tests
# ---------------------------------------------------------------------------


def _make_ok_response(payload=None):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = payload or {}
    return mock_resp


def test_place_order_calls_touch_id_before_post(client):
    order = {"ticker": "AAPL", "side": "BUY", "quantity": 100, "orderType": "LIMIT", "price": 182.5}
    call_order = []
    with (
        _patch(
            "ibkr_core_mcp.client.require_touch_id", side_effect=lambda r: call_order.append("touch_id")
        ) as mock_tid,
        _patch(
            "ibkr_core_mcp.client.confirm_order_dialog", side_effect=lambda o, a: call_order.append("dialog")
        ) as mock_dlg,
        _patch.object(client._session, "post") as mock_post,
    ):
        mock_post.return_value = _make_ok_response([{"orderId": "1"}])
        client.place_order("U1234567", order)
    assert call_order == ["touch_id", "dialog"]
    mock_tid.assert_called_once()
    mock_dlg.assert_called_once()
    mock_post.assert_called_once()


def test_place_order_aborts_if_touch_id_fails(client):

    order = {"ticker": "AAPL", "side": "BUY", "quantity": 100}
    with (
        _patch("ibkr_core_mcp.client.require_touch_id", side_effect=HumanAuthError("denied")),
        _patch.object(client._session, "post") as mock_post,
        pytest.raises(HumanAuthError),
    ):
        client.place_order("U1234567", order)
    mock_post.assert_not_called()


def test_place_order_aborts_if_dialog_cancelled(client):

    order = {"ticker": "AAPL", "side": "BUY", "quantity": 100}
    with (
        _patch("ibkr_core_mcp.client.require_touch_id"),
        _patch("ibkr_core_mcp.client.confirm_order_dialog", side_effect=HumanAuthError("cancelled")),
        _patch.object(client._session, "post") as mock_post,
        pytest.raises(HumanAuthError),
    ):
        client.place_order("U1234567", order)
    mock_post.assert_not_called()


def test_modify_order_aborts_if_touch_id_fails(client):

    with (
        _patch("ibkr_core_mcp.client.require_touch_id", side_effect=HumanAuthError("denied")),
        _patch.object(client._session, "post") as mock_post,
        pytest.raises(HumanAuthError),
    ):
        client.modify_order("U1234567", "1234567890", {"side": "SELL"})
    mock_post.assert_not_called()


def test_cancel_order_aborts_if_touch_id_fails(client):

    with (
        _patch("ibkr_core_mcp.client.require_touch_id", side_effect=HumanAuthError("denied")),
        _patch.object(client._session, "delete") as mock_del,
        pytest.raises(HumanAuthError),
    ):
        client.cancel_order("U1234567", "9876543210")
    mock_del.assert_not_called()


def test_reply_order_aborts_if_touch_id_fails(client):

    with (
        _patch("ibkr_core_mcp.client.require_touch_id", side_effect=HumanAuthError("denied")),
        _patch.object(client._session, "post") as mock_post,
        pytest.raises(HumanAuthError),
    ):
        client.reply_order("abc123def456")
    mock_post.assert_not_called()


def test_modify_order_calls_both_gates(client):
    call_order = []
    with (
        _patch("ibkr_core_mcp.client.require_touch_id", side_effect=lambda r: call_order.append("touch_id")),
        _patch(
            "ibkr_core_mcp.client.confirm_modify_dialog", side_effect=lambda o_id, o, a: call_order.append("dialog")
        ),
        _patch.object(client._session, "post") as mock_post,
    ):
        mock_post.return_value = _make_ok_response({"status": "modified"})
        client.modify_order("U1234567", "1234567890", {"side": "SELL"})
    assert call_order == ["touch_id", "dialog"]
    mock_post.assert_called_once()


def test_cancel_order_calls_both_gates(client):
    call_order = []
    with (
        _patch("ibkr_core_mcp.client.require_touch_id", side_effect=lambda r: call_order.append("touch_id")),
        _patch(
            "ibkr_core_mcp.client.confirm_cancel_dialog",
            side_effect=lambda o_id, a, order=None: call_order.append("dialog"),
        ),
        _patch.object(client._session, "delete") as mock_del,
    ):
        mock_del.return_value = _make_ok_response({"status": "cancelled"})
        client.cancel_order("U1234567", "9876543210")
    assert call_order == ["touch_id", "dialog"]
    mock_del.assert_called_once()


def test_cancel_order_passes_order_details_to_dialog(client):
    captured: dict[str, object] = {}
    with (
        _patch("ibkr_core_mcp.client.require_touch_id"),
        _patch(
            "ibkr_core_mcp.client.confirm_cancel_dialog",
            side_effect=lambda o_id, a, order=None: captured.update(order or {}),
        ),
        _patch.object(client._session, "delete") as mock_del,
    ):
        mock_del.return_value = _make_ok_response({"status": "cancelled"})
        client.cancel_order("U1234567", "9876543210", order_details={"symbol": "AAPL", "side": "SELL"})
    assert captured == {"symbol": "AAPL", "side": "SELL"}


def test_reply_order_calls_both_gates(client):
    call_order = []
    with (
        _patch("ibkr_core_mcp.client.require_touch_id", side_effect=lambda r: call_order.append("touch_id")),
        _patch("ibkr_core_mcp.client.confirm_reply_dialog", side_effect=lambda r: call_order.append("dialog")),
        _patch.object(client._session, "post") as mock_post,
    ):
        mock_post.return_value = _make_ok_response([{"status": "submitted"}])
        client.reply_order("abc123def456")
    assert call_order == ["touch_id", "dialog"]
    mock_post.assert_called_once()


def test_modify_order_aborts_if_dialog_cancelled(client):

    with (
        _patch("ibkr_core_mcp.client.require_touch_id"),
        _patch("ibkr_core_mcp.client.confirm_modify_dialog", side_effect=HumanAuthError("cancelled")),
        _patch.object(client._session, "post") as mock_post,
        pytest.raises(HumanAuthError),
    ):
        client.modify_order("U1234567", "1234567890", {"side": "SELL"})
    mock_post.assert_not_called()


def test_cancel_order_aborts_if_dialog_cancelled(client):

    with (
        _patch("ibkr_core_mcp.client.require_touch_id"),
        _patch("ibkr_core_mcp.client.confirm_cancel_dialog", side_effect=HumanAuthError("cancelled")),
        _patch.object(client._session, "delete") as mock_del,
        pytest.raises(HumanAuthError),
    ):
        client.cancel_order("U1234567", "9876543210")
    mock_del.assert_not_called()


def test_reply_order_aborts_if_dialog_cancelled(client):

    with (
        _patch("ibkr_core_mcp.client.require_touch_id"),
        _patch("ibkr_core_mcp.client.confirm_reply_dialog", side_effect=HumanAuthError("cancelled")),
        _patch.object(client._session, "post") as mock_post,
        pytest.raises(HumanAuthError),
    ):
        client.reply_order("abc123def456")
    mock_post.assert_not_called()


def test_get_order_preview_has_no_gate(client):
    """whatif endpoint is read-only — must NOT trigger Touch ID."""
    order = {"ticker": "AAPL", "side": "BUY", "quantity": 100}
    with (
        _patch("ibkr_core_mcp.client.require_touch_id") as mock_tid,
        _patch.object(client._session, "post") as mock_post,
    ):
        mock_post.return_value = _make_ok_response({"equity": 5000})
        client.get_order_preview("U1234567", order)
    mock_tid.assert_not_called()


# ---------------------------------------------------------------------------
# place_order_and_confirm / modify_order_and_confirm — reply-chain orchestration
# ---------------------------------------------------------------------------


def test_place_order_and_confirm_zero_replies(client):
    """place_order returns a terminal response straight through — no reply loop entered."""
    order = {"ticker": "AAPL", "side": "BUY", "quantity": 10}
    with (
        _patch("ibkr_core_mcp.client.require_touch_id") as mock_tid,
        _patch("ibkr_core_mcp.client.confirm_order_dialog"),
        _patch("ibkr_core_mcp.client.confirm_reply_dialog") as mock_reply_dlg,
        _patch.object(client._session, "post") as mock_post,
    ):
        mock_post.return_value = _make_ok_response([{"order_status": "Submitted", "orderId": "1"}])
        result = client.place_order_and_confirm("U1234567", order)
    assert result == [{"order_status": "Submitted", "orderId": "1"}]
    mock_post.assert_called_once()
    mock_reply_dlg.assert_not_called()
    assert mock_tid.call_count == 1  # only place_order's own gate fires


def test_place_order_and_confirm_one_reply(client):
    order = {"ticker": "AAPL", "side": "BUY", "quantity": 10}
    with (
        _patch("ibkr_core_mcp.client.require_touch_id") as mock_tid,
        _patch("ibkr_core_mcp.client.confirm_order_dialog"),
        _patch("ibkr_core_mcp.client.confirm_reply_dialog") as mock_reply_dlg,
        _patch.object(client._session, "post") as mock_post,
    ):
        mock_post.side_effect = [
            _make_ok_response(
                [
                    {
                        "id": "11111111-1111-4111-8111-111111111111",
                        "message": ["Order price is outside of the Price Band."],
                    }
                ]
            ),
            _make_ok_response([{"order_status": "Submitted"}]),
        ]
        result = client.place_order_and_confirm("U1234567", order)
    assert result == [{"order_status": "Submitted"}]
    assert mock_post.call_count == 2
    mock_reply_dlg.assert_called_once_with(
        "11111111-1111-4111-8111-111111111111",
        "Order price is outside of the Price Band.",
        None,
        order_label="BUY 10 AAPL",
    )
    confirm_call = mock_post.call_args_list[1]
    assert confirm_call[0][0] == f"{client._base}/iserver/reply/11111111-1111-4111-8111-111111111111"
    assert confirm_call.kwargs.get("json") == {"confirmed": True}
    # One Gate 1 for the write; the reply rode on it (2026-09-11). Before that day this
    # line read `== 2` — the write's gate plus one reply gate — which is the defect.
    assert mock_tid.call_count == 1


def test_place_order_and_confirm_three_chained_replies(client):
    """Matches the live-verified shape: reply -> reply -> reply -> terminal (2026-07-06)."""
    order = {"ticker": "AAPL", "side": "BUY", "quantity": 10}
    with (
        _patch("ibkr_core_mcp.client.require_touch_id"),
        _patch("ibkr_core_mcp.client.confirm_order_dialog"),
        _patch("ibkr_core_mcp.client.confirm_reply_dialog") as mock_reply_dlg,
        _patch.object(client._session, "post") as mock_post,
    ):
        mock_post.side_effect = [
            _make_ok_response(
                [{"id": "11111111-1111-4111-8111-111111111111", "message": ["Price is outside of the Price Band."]}]
            ),
            _make_ok_response(
                [{"id": "22222222-2222-4222-8222-222222222222", "message": ["No market data for this contract."]}]
            ),
            _make_ok_response(
                [
                    {
                        "id": "33333333-3333-4333-8333-333333333333",
                        "message": ["This order requires a mandatory cap price."],
                    }
                ]
            ),
            _make_ok_response([{"order_status": "Submitted"}]),
        ]
        result = client.place_order_and_confirm("U1234567", order)
    assert result == [{"order_status": "Submitted"}]
    assert mock_post.call_count == 4
    assert mock_reply_dlg.call_args_list == [
        call(
            "11111111-1111-4111-8111-111111111111",
            "Price is outside of the Price Band.",
            None,
            order_label="BUY 10 AAPL",
        ),
        call(
            "22222222-2222-4222-8222-222222222222", "No market data for this contract.", None, order_label="BUY 10 AAPL"
        ),
        call(
            "33333333-3333-4333-8333-333333333333",
            "This order requires a mandatory cap price.",
            None,
            order_label="BUY 10 AAPL",
        ),
    ]
    urls = [c[0][0] for c in mock_post.call_args_list]
    assert urls[1:] == [
        f"{client._base}/iserver/reply/11111111-1111-4111-8111-111111111111",
        f"{client._base}/iserver/reply/22222222-2222-4222-8222-222222222222",
        f"{client._base}/iserver/reply/33333333-3333-4333-8333-333333333333",
    ]


def test_place_order_and_confirm_passes_message_options(client):
    order = {"ticker": "AAPL", "side": "BUY", "quantity": 10}
    with (
        _patch("ibkr_core_mcp.client.require_touch_id"),
        _patch("ibkr_core_mcp.client.confirm_order_dialog"),
        _patch("ibkr_core_mcp.client.confirm_reply_dialog") as mock_reply_dlg,
        _patch.object(client._session, "post") as mock_post,
    ):
        mock_post.side_effect = [
            _make_ok_response(
                [
                    {
                        "id": "11111111-1111-4111-8111-111111111111",
                        "message": ["Confirm?"],
                        "messageOptions": ["Yes", "No"],
                    }
                ]
            ),
            _make_ok_response([{"order_status": "Submitted"}]),
        ]
        client.place_order_and_confirm("U1234567", order)
    mock_reply_dlg.assert_called_once_with(
        "11111111-1111-4111-8111-111111111111", "Confirm?", ["Yes", "No"], order_label="BUY 10 AAPL"
    )


def test_place_order_and_confirm_decline_mid_chain(client):
    """confirm_reply_dialog raises HumanAuthError -> POST confirmed:False sent first, then re-raised.

    Deliberate behavior change vs. reply_order(), which raises without ever contacting
    IBKR on cancel, leaving the order ambiguous on IBKR's side.
    """

    order = {"ticker": "AAPL", "side": "BUY", "quantity": 10}
    with (
        _patch("ibkr_core_mcp.client.require_touch_id"),
        _patch("ibkr_core_mcp.client.confirm_order_dialog"),
        _patch("ibkr_core_mcp.client.confirm_reply_dialog", side_effect=HumanAuthError("cancelled")),
        _patch.object(client._session, "post") as mock_post,
    ):
        mock_post.side_effect = [
            _make_ok_response([{"id": "11111111-1111-4111-8111-111111111111", "message": ["Price band warning."]}]),
            _make_ok_response({"confirmed": False}),
        ]
        with pytest.raises(HumanAuthError):
            client.place_order_and_confirm("U1234567", order)
    assert mock_post.call_count == 2
    decline_call = mock_post.call_args_list[1]
    assert decline_call[0][0] == f"{client._base}/iserver/reply/11111111-1111-4111-8111-111111111111"
    assert decline_call.kwargs.get("json") == {"confirmed": False}


def test_modify_order_and_confirm_zero_replies(client):
    with (
        _patch("ibkr_core_mcp.client.require_touch_id") as mock_tid,
        _patch("ibkr_core_mcp.client.confirm_modify_dialog"),
        _patch("ibkr_core_mcp.client.confirm_reply_dialog") as mock_reply_dlg,
        _patch.object(client._session, "post") as mock_post,
    ):
        mock_post.return_value = _make_ok_response({"order_status": "Submitted"})
        result = client.modify_order_and_confirm("U1234567", "1234567890", {"price": 180.0})
    assert result == {"order_status": "Submitted"}
    mock_post.assert_called_once()
    mock_reply_dlg.assert_not_called()
    assert mock_tid.call_count == 1


def test_modify_order_and_confirm_chained_replies(client):
    with (
        _patch("ibkr_core_mcp.client.require_touch_id"),
        _patch("ibkr_core_mcp.client.confirm_modify_dialog"),
        _patch("ibkr_core_mcp.client.confirm_reply_dialog") as mock_reply_dlg,
        _patch.object(client._session, "post") as mock_post,
    ):
        mock_post.side_effect = [
            _make_ok_response({"id": "11111111-1111-4111-8111-111111111111", "message": ["Price band warning."]}),
            _make_ok_response({"id": "22222222-2222-4222-8222-222222222222", "message": ["No market data."]}),
            _make_ok_response({"order_status": "Submitted"}),
        ]
        result = client.modify_order_and_confirm("U1234567", "1234567890", {"price": 180.0})
    assert result == {"order_status": "Submitted"}
    assert mock_post.call_count == 3
    assert mock_reply_dlg.call_args_list == [
        call(
            "11111111-1111-4111-8111-111111111111",
            "Price band warning.",
            None,
            order_label="? ? UNKNOWN (order 1234567890)",
        ),
        call(
            "22222222-2222-4222-8222-222222222222",
            "No market data.",
            None,
            order_label="? ? UNKNOWN (order 1234567890)",
        ),
    ]


def test_modify_order_and_confirm_decline_mid_chain(client):

    with (
        _patch("ibkr_core_mcp.client.require_touch_id"),
        _patch("ibkr_core_mcp.client.confirm_modify_dialog"),
        _patch("ibkr_core_mcp.client.confirm_reply_dialog", side_effect=HumanAuthError("cancelled")),
        _patch.object(client._session, "post") as mock_post,
    ):
        mock_post.side_effect = [
            _make_ok_response({"id": "11111111-1111-4111-8111-111111111111", "message": ["Price band warning."]}),
            _make_ok_response({"confirmed": False}),
        ]
        with pytest.raises(HumanAuthError):
            client.modify_order_and_confirm("U1234567", "1234567890", {"price": 180.0})
    assert mock_post.call_count == 2
    decline_call = mock_post.call_args_list[1]
    assert decline_call[0][0] == f"{client._base}/iserver/reply/11111111-1111-4111-8111-111111111111"
    assert decline_call.kwargs.get("json") == {"confirmed": False}


# ---------------------------------------------------------------------------
# _as_reply_list / _as_reply_dict — shape normalizers for the reply chain
#
# IBKR's official docs (cpapi-v1#place-order-reply and #modify-order, fetched live
# 2026-07-06) document /iserver/reply/{replyId} responses as JSON ARRAYS in every
# example given, for both endpoints and both the reply-required and terminal shapes:
#   [{"id": "...", "message": [...], "isSuppressed": false, "messageIds": [...]}]
#   [{"order_id": "1234567890", "order_status": "Submitted", "encrypt_message": "1"}]
# _as_reply_list() is used by place_order_and_confirm() (list-shaped contract) and
# _as_reply_dict() by modify_order_and_confirm() (dict-shaped contract), regardless of
# which raw shape the reply POST actually returns.
#
# CORRECTED 2026-09-21. This block used to say "modify_order()'s own EXISTING return type
# in this codebase is a bare dict though (unchanged by this task)". **It is not, and never
# was** — `modify_order` returns `self._post(...)` unwrapped, `_post` returns `Any`, and a
# live modify on 2026-09-21 returned
# `[{"order_id": "1275120921", "local_order_id": "CLAUDIA-...", "order_status": "Submitted",
# "encrypt_message": "1"}]` — an array, matching IBKR's documented example to the field.
#
# That one belief was the entire blind spot. Everything around it was right: the docs were
# read, both normalizers were written, and the list-shaped *reply* case was tested
# end-to-end. Only the INITIAL response was left unnormalised, so
# `while "id" in response` ran as a list-MEMBERSHIP test against it — `"id" in [{"id": ...}]`
# is False — and a modify that raised a precaution returned that precaution as though it
# were the result. The human was never shown it, never answered it, and the modification was
# never applied. The tests could not catch it because every one of them mocked the initial
# response as a bare dict, which IBKR does not send.
# ---------------------------------------------------------------------------


def test_as_reply_list_wraps_a_bare_dict():
    from ibkr_core_mcp.client import _as_reply_list

    data = {"order_id": "1234567890", "order_status": "Submitted", "encrypt_message": "1"}
    assert _as_reply_list(data) == [data]


def test_as_reply_list_passes_through_a_list():
    from ibkr_core_mcp.client import _as_reply_list

    data = [{"id": "11111111-1111-4111-8111-111111111111", "message": ["warn"]}]
    assert _as_reply_list(data) == data


def test_as_reply_list_returns_empty_for_unexpected_shape():
    from ibkr_core_mcp.client import _as_reply_list

    assert _as_reply_list(None) == []
    assert _as_reply_list("not json") == []


def test_as_reply_dict_unwraps_a_single_element_list():
    """The reciprocal case: IBKR's documented reply response is list-wrapped
    (per the official example above) even though modify_order_and_confirm() needs
    a dict — a single-element list must be unwrapped, not treated as terminal-with-no-id.
    """
    from ibkr_core_mcp.client import _as_reply_dict

    data = [{"order_id": "1234567890", "order_status": "Submitted", "encrypt_message": "1"}]
    assert _as_reply_dict(data) == data[0]


def test_as_reply_dict_passes_through_a_bare_dict():
    from ibkr_core_mcp.client import _as_reply_dict

    data = {"id": "11111111-1111-4111-8111-111111111111", "message": ["warn"]}
    assert _as_reply_dict(data) == data


def test_as_reply_dict_returns_empty_for_unexpected_shape():
    from ibkr_core_mcp.client import _as_reply_dict

    assert _as_reply_dict([]) == {}
    assert _as_reply_dict(None) == {}


def test_modify_order_and_confirm_handles_ibkr_documented_list_shaped_reply(client):
    """End-to-end (not just the pure normalizer): the reply-confirm POST comes back
    in IBKR's actual documented array shape (see module comment above) even though
    modify_order()'s own initial response is a bare dict — exercises _as_reply_dict()'s
    unwrap branch through the real modify_order_and_confirm() call path.
    """
    with (
        _patch("ibkr_core_mcp.client.require_touch_id"),
        _patch("ibkr_core_mcp.client.confirm_modify_dialog"),
        _patch("ibkr_core_mcp.client.confirm_reply_dialog"),
        _patch.object(client._session, "post") as mock_post,
    ):
        mock_post.side_effect = [
            _make_ok_response({"id": "11111111-1111-4111-8111-111111111111", "message": ["Price band warning."]}),
            _make_ok_response([{"order_id": "1234567890", "order_status": "Submitted", "encrypt_message": "1"}]),
        ]
        result = client.modify_order_and_confirm("U1234567", "1234567890", {"price": 180.0})
    assert result == {"order_id": "1234567890", "order_status": "Submitted", "encrypt_message": "1"}


def test_modify_reply_survives_ibkr_array_shaped_INITIAL_response(client):
    """The case every previous test missed: `modify_order`'s OWN response is an array.

    IBKR documents this endpoint as returning an array and a live modify on 2026-09-21
    returned one. Before the 2026-09-21 fix `while "id" in response` was a membership test
    here, so this precaution was returned as the terminal result: no dialog, no answer, and
    the modification silently not applied. Fails against that code.
    """
    with (
        _patch("ibkr_core_mcp.client.require_touch_id"),
        _patch("ibkr_core_mcp.client.confirm_modify_dialog"),
        _patch("ibkr_core_mcp.client.confirm_reply_dialog") as mock_reply_dlg,
        _patch.object(client._session, "post") as mock_post,
    ):
        mock_post.side_effect = [
            # IBKR's documented precaution shape — ARRAY-wrapped, as the module comment says.
            _make_ok_response([{"id": "11111111-1111-4111-8111-111111111111", "message": ["Price band warning."]}]),
            _make_ok_response([{"order_id": "1234567890", "order_status": "Submitted", "encrypt_message": "1"}]),
        ]
        result = client.modify_order_and_confirm("U1234567", "1234567890", {"price": 180.0})

    # The human was asked. That is the property that was lost.
    mock_reply_dlg.assert_called_once()
    assert mock_post.call_count == 2
    assert result == {"order_id": "1234567890", "order_status": "Submitted", "encrypt_message": "1"}


def test_modify_with_no_reply_returns_the_array_wrapped_terminal_unwrapped(client):
    """The live 2026-09-21 shape: an array-wrapped terminal response and no precaution.

    The real modify that day raised no reply at all — the place of the same order raised a
    value-limit precaution and the modify, still over the same limit, raised none. The
    terminal entry must be unwrapped, and no dialog may be shown.
    """
    with (
        _patch("ibkr_core_mcp.client.require_touch_id"),
        _patch("ibkr_core_mcp.client.confirm_modify_dialog"),
        _patch("ibkr_core_mcp.client.confirm_reply_dialog") as mock_reply_dlg,
        _patch.object(client._session, "post") as mock_post,
    ):
        mock_post.return_value = _make_ok_response(
            [{"order_id": "1275120921", "order_status": "Submitted", "encrypt_message": "1"}]
        )
        result = client.modify_order_and_confirm("U1234567", "1275120921", {"price": 7250.0})

    mock_reply_dlg.assert_not_called()
    mock_post.assert_called_once()
    assert result == {"order_id": "1275120921", "order_status": "Submitted", "encrypt_message": "1"}


# ---------------------------------------------------------------------------
# account_id validation — path traversal and injection prevention
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "account_id",
    [
        "U1234567",
        "DU123456",
        "F123ABC",
        "ABCDEFGHIJ",
    ],
)
def test_validate_account_id_accepts_valid_ids(client, account_id):
    from unittest.mock import MagicMock

    from ibkr_core_mcp.exceptions import ConfigError

    client._session.get = MagicMock(return_value=MagicMock(status_code=200, json=lambda: {}))
    # Valid IDs must not raise ConfigError — any other exception (e.g. from mock shape) is ignored
    try:
        client.get_account_summary(account_id)
    except ConfigError:
        pytest.fail(f"ConfigError raised for valid account_id {account_id!r}")


@pytest.mark.parametrize(
    "bad_id",
    [
        "",  # empty
        "../etc/passwd",  # path traversal
        "U123/456",  # slash
        "U123#456",  # special char
        "U123 456",  # space
        "U123\r\nX-Header: 1",  # CRLF injection
        "U123\x00null",  # null byte
        "U123-456",  # hyphen
    ],
)
def test_validate_account_id_rejects_invalid_ids(client, bad_id):
    from ibkr_core_mcp.exceptions import ConfigError

    with pytest.raises(ConfigError, match=r"[Ii]nvalid account"):
        client.get_account_summary(bad_id)


def test_validate_account_id_applied_to_write_methods(client):
    """Path traversal must be caught before Touch ID gates are evaluated."""
    from ibkr_core_mcp.exceptions import ConfigError

    order = {"ticker": "AAPL", "side": "BUY", "quantity": 1}
    with _patch("ibkr_core_mcp.client.require_touch_id") as mock_tid, pytest.raises(ConfigError):
        client.place_order("../inject", order)
    mock_tid.assert_not_called()  # validation must fire before biometric gate


@pytest.mark.parametrize(
    "method_name,args",
    [
        ("get_order_status", ("../../etc/passwd",)),
        ("get_alert", ("../../etc/passwd",)),
    ],
)
def test_validate_order_id_rejects_path_traversal_read_methods(client, method_name, args):
    from ibkr_core_mcp.exceptions import ConfigError

    with pytest.raises(ConfigError, match=r"[Ii]nvalid"):
        getattr(client, method_name)(*args)


def test_delete_alert_rejects_path_traversal_alert_id(client):
    """The exact H-2 exploit path: alert_id='../order/<real orderId>' must never
    reach the network. See docs/audits/security-audit-2026-07-11.md H-2."""
    from ibkr_core_mcp.exceptions import ConfigError

    with (
        _patch("ibkr_core_mcp.client.require_touch_id") as mock_tid,
        pytest.raises(ConfigError, match=r"[Ii]nvalid"),
    ):
        client.delete_alert("DU1234567", "../order/987654321")
    mock_tid.assert_not_called()


@pytest.mark.parametrize(
    "bad_order_id",
    [
        "",
        "../order/1",
        "123/456",
        "123#456",
        "123 456",
        "abc123",
        "١٢٣",
    ],
)
def test_validate_order_id_rejects_invalid_ids(client, bad_order_id):
    from ibkr_core_mcp.exceptions import ConfigError

    with pytest.raises(ConfigError, match=r"[Ii]nvalid"):
        client.get_order_status(bad_order_id)


def test_validate_order_id_accepts_valid_id(client):
    client._session.get = MagicMock(return_value=MagicMock(status_code=200, json=lambda: {}))
    client.get_order_status("987654321")  # must not raise ConfigError


@pytest.mark.parametrize(
    "bad_reply_id",
    [
        "",
        "../reply/1",
        "abc/def",
        "abc def",
    ],
)
def test_validate_reply_id_rejects_invalid_ids(client, bad_reply_id):
    from ibkr_core_mcp.exceptions import ConfigError

    with pytest.raises(ConfigError, match=r"[Ii]nvalid"):
        client.reply_order(bad_reply_id)


def test_validate_reply_id_accepts_valid_uuid_shaped_id(client):
    """IBKR's documented replyId example: hex + hyphens, non-standard grouping —
    regex must not assume strict 8-4-4-4-12 UUID segments."""
    with (
        _patch("ibkr_core_mcp.client.require_touch_id") as mock_tid,
        _patch("ibkr_core_mcp.client.confirm_reply_dialog"),
    ):
        client._session.post = MagicMock(return_value=MagicMock(status_code=200, json=lambda: []))
        client.reply_order("a12b34c5-d678-9e012f-3456-7a890b12cd3e")
    mock_tid.assert_called_once()


# ── get_stocks / get_futures dict-response fix ───────────────────────────────


def test_get_stocks_handles_dict_response(client):
    """IBKR /trsrv/stocks returns {"AAPL": [{conid: ...}]}, not a list."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "AAPL": [{"conid": 265598, "assetClass": "STK"}],
        "MSFT": [{"conid": 272093, "assetClass": "STK"}],
    }
    with patch.object(client._session, "get", return_value=mock_resp):
        result = client.get_stocks(["AAPL", "MSFT"])
    assert len(result) == 2
    conids = {c["conid"] for c in result}
    assert conids == {265598, 272093}


def test_get_stocks_handles_list_response(client):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [{"conid": 265598, "symbol": "AAPL"}]
    with patch.object(client._session, "get", return_value=mock_resp):
        result = client.get_stocks(["AAPL"])
    assert len(result) == 1


def test_get_stocks_returns_empty_on_unexpected_type(client):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = "unexpected"
    with patch.object(client._session, "get", return_value=mock_resp):
        result = client.get_stocks(["AAPL"])
    assert result == []


def test_get_futures_handles_dict_response(client):
    """IBKR /trsrv/futures returns {"ES": [{conid: ...}]}, not a list."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "ES": [{"conid": 495512557, "expiry": "20240920"}],
    }
    with patch.object(client._session, "get", return_value=mock_resp):
        result = client.get_futures(["ES"])
    assert len(result) == 1
    assert result[0]["conid"] == 495512557


def test_get_currency_pairs_handles_dict_response(client):
    """IBKR /iserver/currency/pairs returns {"USD": [{symbol, conid, ccyPair}]}.

    Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/contract/currency-pairs.md
    """
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "USD": [
            {"symbol": "USD.SGD", "conid": 37928772, "ccyPair": "SGD"},
            {"symbol": "USD.JPY", "conid": 15016062, "ccyPair": "JPY"},
        ],
    }
    with patch.object(client._session, "get", return_value=mock_resp) as mock_get:
        result = client.get_currency_pairs("USD")
    assert len(result) == 2
    assert {c["symbol"] for c in result} == {"USD.SGD", "USD.JPY"}
    called_url = mock_get.call_args[0][0]
    assert "/iserver/currency/pairs" in called_url


def test_get_currency_pairs_returns_empty_on_unexpected_type(client):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = "unexpected"
    with patch.object(client._session, "get", return_value=mock_resp):
        result = client.get_currency_pairs("USD")
    assert result == []


# ── get_secdef: the array is under a key, not the whole body ─────────────────


def test_get_secdef_unwraps_the_secdef_key(client):
    """IBKR /trsrv/secdef returns {"secdef": [...]}, not a bare array.

    Regression for a silent total failure: the old body was
    `data if isinstance(data, list) else []`, so every call returned [] — the same
    defect, in the same shape, as test_get_currency_pairs_handles_dict_response above.
    A method that always returns empty looks exactly like an instrument with no data.

    Source: https://www.interactivebrokers.com/docs/web-api/v1/endpoints/contract/search-the-security-definition-by-contract-id
    """
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "secdef": [
            {"conid": 12658199, "currency": "USD", "listingExchange": "BATS", "isUS": True},
            {"conid": 325209548, "currency": "MXN", "listingExchange": "MEXI", "isUS": False},
        ],
    }
    with patch.object(client._session, "get", return_value=mock_resp) as mock_get:
        result = client.get_secdef([12658199, 325209548])

    assert len(result) == 2
    assert {r["currency"] for r in result} == {"USD", "MXN"}
    called_url = mock_get.call_args[0][0]
    assert "/trsrv/secdef" in called_url


def test_get_secdef_uses_get_with_comma_separated_conids(client):
    """GET with ?conids=, per the endpoint reference. The Additional Usage Limits table
    lists a POST row for `/trsv/secdef` (note IBKR's own path typo); the endpoint page
    documents GET and shows `requests.get(...)`. The endpoint page is the authority —
    a limits table is not a method specification."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"secdef": []}
    with patch.object(client._session, "get", return_value=mock_resp) as mock_get:
        client.get_secdef([1, 2, 3])

    assert mock_get.call_args.kwargs["params"] == {"conids": "1,2,3"}


def test_get_secdef_returns_empty_on_unexpected_shapes(client):
    """A missing or non-list `secdef` key, and a non-dict body, all yield []."""
    for payload in ({"secdef": "nope"}, {}, "unexpected", None):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = payload
        with patch.object(client._session, "get", return_value=mock_resp):
            assert client.get_secdef([1]) == [], payload


def test_get_secdef_still_accepts_a_bare_list(client):
    """Tolerated deliberately: the only cost is accepting an undocumented shape, and the
    alternative failure mode is another silent empty."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [{"conid": 265598, "currency": "USD"}]
    with patch.object(client._session, "get", return_value=mock_resp):
        result = client.get_secdef([265598])
    # A typed return compares by payload, not by literal: a model is never == a dict.
    assert [dict(c) for c in result] == [{"conid": 265598, "currency": "USD"}]


# ── get_live_orders filtering ─────────────────────────────────────────────────


@contextmanager
def _mock_orders_response(client, orders):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"orders": orders}
    with patch.object(client._session, "get", return_value=mock_resp), patch("time.sleep"):
        yield


def test_get_live_orders_excludes_filled(client):
    orders = [
        {"orderId": 1, "ticker": "AAPL", "status": "Submitted"},
        {"orderId": 2, "ticker": "CL", "status": "Filled"},
    ]
    with _mock_orders_response(client, orders):
        result = client.get_live_orders()
    assert len(result) == 1
    assert result[0]["status"] == "Submitted"


def test_get_live_orders_excludes_cancelled(client):
    orders = [
        {"orderId": 1, "ticker": "AAPL", "status": "Cancelled"},
        {"orderId": 2, "ticker": "SPY", "status": "ApiCancelled"},
        {"orderId": 3, "ticker": "GLD", "status": "PreSubmitted"},
    ]
    with _mock_orders_response(client, orders):
        result = client.get_live_orders()
    assert len(result) == 1
    assert result[0]["status"] == "PreSubmitted"


def test_get_live_orders_includes_all_working_statuses(client):
    working = ["PreSubmitted", "Submitted", "ApiPending", "PendingSubmit", "PendingCancel", "Inactive"]
    orders = [{"orderId": i, "ticker": "X", "status": s} for i, s in enumerate(working)]
    with _mock_orders_response(client, orders):
        result = client.get_live_orders()
    assert len(result) == len(working)


def test_get_live_orders_empty_when_all_filled(client):
    orders = [
        {"orderId": 1, "ticker": "CL", "status": "Filled"},
        {"orderId": 2, "ticker": "IGV", "status": "Filled"},
    ]
    with _mock_orders_response(client, orders):
        result = client.get_live_orders()
    assert result == []


def test_get_live_orders_handles_missing_status(client):
    # Orders with no status field should be excluded (unknown state, not working)
    orders = [
        {"orderId": 1, "ticker": "AAPL"},
        {"orderId": 2, "ticker": "SPY", "status": "Submitted"},
    ]
    with _mock_orders_response(client, orders):
        result = client.get_live_orders()
    assert len(result) == 1
    assert result[0]["ticker"] == "SPY"


# ── ping() retry behaviour (Fix #2 — IBKR first-call quirk) ─────────────────


def test_ping_retries_once_when_first_call_returns_unauthenticated(client):
    """ping() retries once when first call returns authenticated=false (IBKR quirk)."""
    responses = [
        MagicMock(status_code=200, json=MagicMock(return_value={"authenticated": False})),
        MagicMock(status_code=200, json=MagicMock(return_value={"authenticated": True})),
    ]
    with (
        patch.object(client._session, "get", side_effect=responses),
        patch.object(client, "tickle", return_value=True),
        patch("ibkr_core_mcp.client.time.sleep"),
    ):
        result = client.ping()
    assert result is True


def test_ping_returns_false_when_both_attempts_unauthenticated(client):
    """ping() returns False if authenticated=false on both the first and second attempt."""
    not_authed = MagicMock(status_code=200, json=MagicMock(return_value={"authenticated": False}))
    with (
        patch.object(client._session, "get", return_value=not_authed) as mock_get,
        patch.object(client, "tickle", return_value=True),
        patch("ibkr_core_mcp.client.time.sleep"),
    ):
        result = client.ping()
    assert result is False
    assert mock_get.call_count == 2, "ping() must attempt exactly twice when not authenticated"


def test_ping_calls_tickle_between_first_and_second_attempt(client):
    """ping() must call tickle() exactly once, between the two attempts."""
    responses = [
        MagicMock(status_code=200, json=MagicMock(return_value={"authenticated": False})),
        MagicMock(status_code=200, json=MagicMock(return_value={"authenticated": True})),
    ]
    with (
        patch.object(client._session, "get", side_effect=responses),
        patch.object(client, "tickle", return_value=True) as mock_tickle,
        patch("ibkr_core_mcp.client.time.sleep"),
    ):
        client.ping()
    mock_tickle.assert_called_once()


def test_ping_returns_false_immediately_on_401_without_retry(client):
    """ping() must return False immediately on HTTP 401 — no retry, no tickle."""
    resp_401 = MagicMock(status_code=401)
    with (
        patch.object(client._session, "get", return_value=resp_401) as mock_get,
        patch.object(client, "tickle") as mock_tickle,
    ):
        result = client.ping()
    assert result is False
    assert mock_get.call_count == 1, "Must not retry on 401"
    mock_tickle.assert_not_called()


# ── get_trades — two-call warmup (verified live 2026-07-06) ───────────────────


def test_get_trades_retries_once_when_first_call_empty(client):
    """Live-verified 2026-07-06: a fresh session returns [] on the first call and
    the fills on the second — same subscription warmup as /iserver/account/orders.
    A single empty call must not be reported as 'no trades'."""
    trades = [{"execution_id": "e1", "symbol": "ES", "side": "S", "trade_time": "20260702-05:29:28"}]
    responses = [_make_ok_response([]), _make_ok_response(trades)]
    with (
        patch.object(client._session, "get", side_effect=responses) as mock_get,
        patch("ibkr_core_mcp.client.time.sleep"),
    ):
        client._accounts_initialized = True
        result = client.get_trades()
    assert [dict(t) for t in result] == trades
    assert mock_get.call_count == 2


def test_get_trades_single_call_when_data_returned(client):
    """A primed session answers on the first call — no second request."""
    trades = [{"execution_id": "e1", "symbol": "ES", "side": "B", "trade_time": "20260701-14:32:23"}]
    with patch.object(client._session, "get", return_value=_make_ok_response(trades)) as mock_get:
        client._accounts_initialized = True
        result = client.get_trades()
    assert [dict(t) for t in result] == trades
    assert mock_get.call_count == 1


def test_get_trades_empty_after_retry_returns_empty(client):
    """Two empty responses = genuinely no trades in the window."""
    responses = [_make_ok_response([]), _make_ok_response([])]
    with (
        patch.object(client._session, "get", side_effect=responses) as mock_get,
        patch("ibkr_core_mcp.client.time.sleep"),
    ):
        client._accounts_initialized = True
        result = client.get_trades()
    assert result == []
    assert mock_get.call_count == 2


# ── get_market_history — period/bar case normalization (verified live 2026-07-06) ──


def test_get_market_history_normalizes_period_and_bar_case(client):
    """Live-verified 2026-07-06: IBKR treats period='6M' as unrecognized and silently
    returns a ~84-bar default (4 months), while '6m' returns the true 6 months.
    Uppercase inputs must be lowercased before the request (root cause of audit
    register #9, '6 months → 84 bars')."""
    with patch.object(client._session, "get", return_value=_make_ok_response({"data": []})) as mock_get:
        client.get_market_history(265598, period="6M", bar="1D")
    params = mock_get.call_args[1].get("params") or mock_get.call_args[0][1]
    assert params["period"] == "6m"
    assert params["bar"] == "1d"


# ---------------------------------------------------------------------------
# get_option_strikes / get_option_chain — documented secdef flow
# Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/contract/search-strikes-by-underlying-contract-id.md
# ---------------------------------------------------------------------------


def test_get_option_strikes_returns_call_and_put_arrays(client):
    """/iserver/secdef/strikes responds {"call": [...], "put": [...]} — there is
    no "strike" key in the documented response (the old code read one)."""
    payload = {"call": [185.0, 190.0], "put": [180.0, 185.0]}
    with patch.object(client._session, "get", return_value=_make_ok_response(payload)) as mock_get:
        result = client.get_option_strikes(265598, "OPT", "JAN26")
    assert result == {"call": [185.0, 190.0], "put": [180.0, 185.0]}
    params = mock_get.call_args[1].get("params") or {}
    assert params["sectype"] == "OPT"
    assert params["month"] == "JAN26"
    assert params["exchange"] == "SMART"


def test_get_option_chain_uses_documented_search_then_strikes_flow(client):
    """Reimplemented per the documented flow: secdef/search (primes the session,
    yields the OPT section's months) then secdef/strikes for one month."""
    search_payload = [
        {
            "conid": "265598",
            "symbol": "AAPL",
            "sections": [
                {"secType": "STK"},
                {"secType": "OPT", "months": "JAN26;FEB26;MAR26"},
            ],
        }
    ]
    strikes_payload = {"call": [185.0], "put": [180.0]}
    with patch.object(client, "_get", side_effect=[search_payload, strikes_payload]) as mock_get:
        chain = client.get_option_chain("AAPL")
    assert chain["conid"] == 265598
    assert chain["months"] == ["JAN26", "FEB26", "MAR26"]
    assert chain["month"] == "JAN26"  # defaults to nearest expiry
    assert chain["call"] == [185.0]
    assert chain["put"] == [180.0]
    first_call = mock_get.call_args_list[0]
    assert "/iserver/secdef/search" in first_call[0][0]
    second_call = mock_get.call_args_list[1]
    assert "/iserver/secdef/strikes" in second_call[0][0]


def test_get_option_chain_honors_requested_month(client):
    search_payload = [
        {
            "conid": "265598",
            "symbol": "AAPL",
            "sections": [{"secType": "OPT", "months": "JAN26;FEB26"}],
        }
    ]
    strikes_payload: dict[str, list[float]] = {"call": [], "put": []}
    with patch.object(client, "_get", side_effect=[search_payload, strikes_payload]) as mock_get:
        chain = client.get_option_chain("AAPL", month="feb26")
    assert chain["month"] == "FEB26"
    params = mock_get.call_args_list[1][0][1]
    assert params["month"] == "FEB26"


def test_get_option_chain_raises_when_no_opt_section(client):
    from ibkr_core_mcp.exceptions import IBKRAPIError

    search_payload = [{"conid": "1", "symbol": "XONE", "sections": [{"secType": "STK"}]}]
    with (
        patch.object(client, "_get", side_effect=[search_payload]),
        pytest.raises(IBKRAPIError, match=r"[Nn]o option"),
    ):
        client.get_option_chain("XONE")


# ---------------------------------------------------------------------------
# get_orders_raw / get_pa_periods_raw — public wrappers replacing the toolkit's
# private-API reach-ins (audit register item 11)
# ---------------------------------------------------------------------------


def test_get_orders_raw_returns_unfiltered_without_re_priming(client):
    """Raw diagnostic dump: no status filtering — terminal orders must survive — and,
    since 2026-09-16, no unconditional `force=true` ahead of the read.

    This asserted the old force-first pair. That pair spent two slots of a 1-req/5-secs
    endpoint on every call to answer one question, and a warm session does not need it
    (measured live: three consecutive plain reads each returned the open order).
    """
    payload = {"orders": [{"orderId": 1, "status": "Filled"}]}
    with (
        patch.object(client, "_get", side_effect=[payload]) as mock_get,
        patch("ibkr_core_mcp.client.time.sleep"),
    ):
        raw = client.get_orders_raw()
    assert raw == payload  # unfiltered — Filled order retained
    assert [c[0][0] for c in mock_get.call_args_list] == ["/iserver/account/orders"]


def test_get_orders_raw_primes_when_the_read_comes_back_empty(client):
    """The cold-session path the warmup exists for, kept for the diagnostic dump too."""
    payload = {"orders": [{"orderId": 1, "status": "Filled"}]}
    with (
        patch.object(client, "_get", side_effect=[{"orders": []}, None, payload]) as mock_get,
        patch("ibkr_core_mcp.client.time.sleep"),
    ):
        raw = client.get_orders_raw()
    assert raw == payload
    assert [c[0][0] for c in mock_get.call_args_list] == [
        "/iserver/account/orders",
        "/iserver/account/orders?force=true",
        "/iserver/account/orders",
    ]


def test_get_pa_periods_raw_posts_account_ids(client):
    payload = {"U1": {"periods": ["1D", "7D"]}}
    with patch.object(client, "_post", return_value=payload) as mock_post:
        raw = client.get_pa_periods_raw(["U1"])
    assert raw == payload
    assert mock_post.call_args[0][0] == "/pa/allperiods"
    assert mock_post.call_args[0][1] == {"acctIds": ["U1"]}


# ── get_market_history_paged — the startTime anchor (live-measured 2026-08-05) ──
#
# `startTime` is the END of the returned window, not the start. IBKR's own OpenAPI spec
# (https://api.ibkr.com/gw/api/v3/api-docs) calls it "a fixed UTC date-time reference point
# ... from which the specified period extends", and measurement settles which way it
# extends: anchored at 20231109 with period=100d, the endpoint returned 2023-06-20 →
# 2023-11-07 with `direction` omitted AND with `direction=-1`, identically. `direction=1`
# — documented as supported whenever startTime is included — returned
# {"error": "Chart data unavailable"}.
#
# The pagination read it as the start, so every chunk was requested a full chunk-width too
# early and the most recent chunk was never fetched at all. Measured against the live
# gateway: SPY 5y/1w returned 2018-04-19 → 2023-10-30 while the raw endpoint returned
# 2021-08-09 → 2026-08-03. Silent: the caller got 291 plausible weekly bars ending 1,010
# days ago and nothing said so.


_BAR_SECONDS = {
    "1min": 60,
    "2min": 120,
    "3min": 180,
    "5min": 300,
    "10min": 600,
    "15min": 900,
    "30min": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "8h": 28800,
    "1d": 86400,
    "1w": 604800,
}


def _paged_calls(client, period, bar, monkeypatch_now=None):
    """Run the paged fetch against a faithful stub; return the params of each request.

    The stub used to return a single bar stamped at epoch ~0 for every call. That made the
    double far weaker than the endpoint it stood for: it could never reach the 1000-point
    cap, so it could not express the truncation that silently dropped ~85% of the bars on
    any intraday request (see the block below). It also meant the cursor-advancing loop had
    nothing real to advance along. `_capped_get` returns dated bars and truncates the way
    IBKR does.
    """
    fake, calls = _capped_get(bar_seconds=_BAR_SECONDS.get(bar.lower(), 86400))
    with patch.object(client, "_get", side_effect=fake):
        client.get_market_history_paginated(265598, period=period, bar=bar)
    return calls


def test_paged_newest_chunk_omits_starttime_so_it_reaches_today(client):
    """The regression that mattered: the newest chunk must reach today.

    Anchoring it a chunk-width back (the old behaviour) dropped the most recent chunk
    entirely and shifted every later one by the same amount. Omitting `startTime` is what
    reaches today — measured 2026-08-05 on SPY 30d/1d, omitted returned through 08-05
    while an explicit timestamp of the same moment returned only through 08-04.
    """
    calls = _paged_calls(client, "5y", "1d")

    assert len(calls) > 1, "5y/1d must paginate, or this test proves nothing"
    assert "startTime" not in calls[0]
    assert "direction" not in calls[0]


def test_paged_chunks_anchor_on_delivered_data_not_on_requested_width(client):
    """Each anchor must be where the previous response actually ended, not where it was
    asked to end.

    This replaces a test that asserted anchors sat at cumulative *requested* day offsets.
    That held only while every chunk returned everything it asked for — exactly the
    assumption the 1000-point cap breaks. The property that matters is unchanged (windows
    abut, no hole between them); only the thing it is measured against has moved from the
    request to the response.
    """
    from datetime import datetime

    calls = _paged_calls(client, "5y", "1d")
    assert len(calls) > 1, "5y/1d must paginate, or this test proves nothing"

    fake, _ = _capped_get(bar_seconds=86400)
    prev_oldest = None
    for i, params in enumerate(calls):
        if i:
            anchor = datetime.strptime(params["startTime"], "%Y%m%d-%H:%M:%S")
            assert prev_oldest is not None
            drift = abs((anchor - prev_oldest).total_seconds())
            assert drift < 120, (
                f"chunk {i} anchored {drift / 86400:.2f}d away from the oldest bar "
                f"chunk {i - 1} returned — that difference is missing data"
            )
        resp = fake("/iserver/marketdata/history", params)
        prev_oldest = datetime.utcfromtimestamp(min(b["t"] for b in resp["data"]) / 1000)


def test_paged_requests_state_the_direction_explicitly(client):
    """`direction` defaults to backwards *by measurement*, not by documentation — the
    spec's own wording implies the opposite, and `direction=1` errors outright. Stating
    -1 means a change to IBKR's default cannot silently reverse every paged request."""
    calls = _paged_calls(client, "5y", "1d")
    anchored = [c for c in calls if "startTime" in c]
    assert anchored, "nothing to check"
    assert all(str(c.get("direction")) == "-1" for c in anchored)


def test_paged_covers_the_whole_requested_span(client):
    """Coverage is what came back, not what was asked for.

    The old assertion summed the `period=` values across chunks. Under truncation those
    two quantities diverge completely — the request widths still summed to 5 years while
    the delivered bars covered a fraction of it.
    """
    from datetime import datetime, timedelta

    fake, _ = _capped_get(bar_seconds=86400)
    with patch.object(client, "_get", side_effect=fake):
        out = client.get_market_history_paginated(265598, period="5y", bar="1d")

    stamps = sorted(b["t"] for b in out.get("data", []))
    oldest = datetime.utcfromtimestamp(stamps[0] / 1000)
    shortfall = (oldest - (datetime.utcnow() - timedelta(days=5 * 365))).total_seconds() / 86400
    assert shortfall < 2, f"5y requested, oldest delivered bar is {shortfall:.1f}d short"


def test_paged_single_chunk_requests_are_not_paginated(client):
    """A period inside one chunk must go through the plain call — no startTime, no
    direction, so the untouched fast path stays untouched."""
    with (
        patch.object(client, "get_market_history", return_value={"data": []}) as plain,
        patch.object(client, "_get") as paged,
    ):
        client.get_market_history_paginated(265598, period="6m", bar="1d")
    plain.assert_called_once()
    paged.assert_not_called()


# ============================================================================
# get_live_orders: an unrecognisable response is not "you have no orders"
# ============================================================================
# The documented response is {"orders": [...], "snapshot": bool}:
# https://ibkrcampus.com/docs/web-api/v1/endpoints/order-monitoring/live-orders.md
# Anything else used to `return []`, answering a safety-relevant question -- "do I
# have working orders?" -- with a confident no. get_orders_raw exists precisely
# because this shape can surprise, which is the tell that it was known to.


def _mock_raw_orders_body(client, body):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = body
    return patch.object(client._session, "get", return_value=mock_resp)


def test_get_live_orders_raises_on_an_unrecognisable_response(client):
    """A 200 whose body is not the documented shape must not read as "no orders"."""
    from ibkr_core_mcp.exceptions import IBKRAPIError

    with (
        _mock_raw_orders_body(client, {"error": "no subscription", "statusCode": 500}),
        patch("time.sleep"),
        pytest.raises(IBKRAPIError) as excinfo,
    ):
        client.get_live_orders()

    assert "get_orders_raw" in str(excinfo.value), "the message must name the diagnostic escape hatch"


def test_get_live_orders_raises_on_a_scalar_response(client):
    from ibkr_core_mcp.exceptions import IBKRAPIError

    with _mock_raw_orders_body(client, "service unavailable"), patch("time.sleep"), pytest.raises(IBKRAPIError):
        client.get_live_orders()


def test_get_live_orders_returns_empty_for_a_genuine_empty_list(client):
    """The one empty that IS an answer: IBKR said orders, and there were none."""
    with _mock_raw_orders_body(client, {"orders": [], "snapshot": True}), patch("time.sleep"):
        assert client.get_live_orders() == []


def test_get_live_orders_accepts_a_bare_list_response(client):
    """Some gateway builds return the array directly rather than wrapped."""
    with _mock_raw_orders_body(client, [{"orderId": 1, "status": "Submitted"}]), patch("time.sleep"):
        assert len(client.get_live_orders()) == 1


# ----------------------------------------------------------------------
# get_watchlists — the 2026-07-23 silent-empty bug
#
# IBKR returns a *dict* ({"data": {"user_lists": [...], "system_lists": [...]}}),
# never a bare list, so the original `return data if isinstance(data, list) else []`
# discarded every watchlist and reported "none found" for an account with 8.
# Shapes below are from the official endpoint doc, re-fetched 2026-08-11:
# https://www.interactivebrokers.com/docs/web-api/v1/endpoints/watchlists/get-all-watchlists
# ----------------------------------------------------------------------


def _watchlist_response(client, payload):
    with patch.object(client._session, "get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = payload
        mock_get.return_value = mock_resp
        return client.get_watchlists()


def test_get_watchlists_parses_documented_user_lists(client):
    """The documented nested shape must yield the watchlists, not []."""
    result = _watchlist_response(
        client,
        {
            "data": {
                "scanners_only": False,
                "show_scanners": False,
                "bulk_delete": False,
                "user_lists": [
                    {"is_open": False, "read_only": False, "name": "Test Watchlist", "id": "1234", "type": "watchlist"}
                ],
            },
            "action": "content",
            "MID": "1",
        },
    )
    assert [w["id"] for w in result] == ["1234"]
    assert result[0]["name"] == "Test Watchlist"


def test_get_watchlists_includes_system_lists(client):
    """`system_lists` are IB-created watchlists and count as watchlists too."""
    result = _watchlist_response(
        client,
        {
            "data": {
                "user_lists": [{"id": "u1", "name": "Mine", "read_only": False}],
                "system_lists": [{"id": "s1", "name": "US Indices and ETFs", "read_only": True}],
            }
        },
    )
    assert [w["id"] for w in result] == ["u1", "s1"]
    # IBKR's own read_only flag distinguishes them — no synthetic tagging needed.
    assert result[1]["read_only"] is True


def test_get_watchlists_empty_account_returns_empty_list(client):
    """A genuinely empty account still reports empty — the fix must not invent rows."""
    assert _watchlist_response(client, {"data": {"user_lists": []}, "action": "content"}) == []


def test_get_watchlists_tolerates_bare_list(client):
    """Defensive: if IBKR ever returns a bare list, don't regress to []."""
    result = _watchlist_response(client, [{"id": "wl1", "name": "Legacy"}])
    assert [w["id"] for w in result] == ["wl1"]


def test_get_watchlists_ignores_non_dict_entries(client):
    """Malformed entries are skipped rather than crashing the caller."""
    result = _watchlist_response(client, {"data": {"user_lists": [{"id": "ok", "name": "Good"}, "junk", None]}})
    assert [w["id"] for w in result] == ["ok"]


def test_get_watchlists_handles_unexpected_payload(client):
    """An unrecognised shape yields [] rather than raising."""
    assert _watchlist_response(client, {"unexpected": True}) == []
    assert _watchlist_response(client, "not json at all") == []


def test_place_order_and_confirm_records_each_reply_in_the_callers_log(client):
    """claudia_ui gap #38 (2026-09-10): two human-confirmed IBKR precautions left no trace
    because only the terminal response was returned. The caller-owned list gets one record per
    reply — raw and cleaned text, confirmed flag, UTC stamp — and the return value is unchanged."""
    order = {"ticker": "ES", "side": "BUY", "quantity": 1}
    reply_log: list[dict[str, Any]] = []
    with (
        _patch("ibkr_core_mcp.client.require_touch_id"),
        _patch("ibkr_core_mcp.client.confirm_order_dialog"),
        _patch("ibkr_core_mcp.client.confirm_reply_dialog"),
        _patch.object(client._session, "post") as mock_post,
    ):
        mock_post.side_effect = [
            _make_ok_response(
                [
                    {
                        "id": "11111111-1111-4111-8111-111111111111",
                        "message": ["Value estimate of 395,000 USD exceeds", "the Total Value Limit."],
                        "messageOptions": ["ok"],
                    }
                ]
            ),
            _make_ok_response(
                [{"id": "22222222-2222-4222-8222-222222222222", "message": ["Stop Variant&nbsp;Order Confirmation"]}]
            ),
            _make_ok_response([{"order_id": "975324733", "order_status": "PreSubmitted"}]),
        ]
        result = client.place_order_and_confirm("U1234567", order, reply_log=reply_log)
    assert result == [{"order_id": "975324733", "order_status": "PreSubmitted"}]
    assert [r["reply_id"] for r in reply_log] == [
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
    ]
    assert reply_log[0]["message"] == "Value estimate of 395,000 USD exceeds the Total Value Limit."
    assert reply_log[0]["message_options"] == ["ok"]
    assert reply_log[1]["message"] == "Stop Variant&nbsp;Order Confirmation"  # raw, never cleaned
    assert reply_log[1]["message_text"] == "Stop Variant\xa0Order Confirmation"
    assert all(r["confirmed"] is True for r in reply_log)
    assert all(r["at"].endswith("Z") for r in reply_log)


def test_place_order_and_confirm_logs_a_declined_reply_as_not_confirmed(client):
    """A decline is recorded (confirmed False) before the decline POST and the re-raise."""

    order = {"ticker": "ES", "side": "BUY", "quantity": 1}
    reply_log: list[dict[str, Any]] = []
    with (
        _patch("ibkr_core_mcp.client.require_touch_id"),
        _patch("ibkr_core_mcp.client.confirm_order_dialog"),
        _patch(
            "ibkr_core_mcp.client.confirm_reply_dialog",
            side_effect=[None, HumanAuthError("cancelled")],
        ),
        _patch.object(client._session, "post") as mock_post,
    ):
        mock_post.side_effect = [
            _make_ok_response([{"id": "11111111-1111-4111-8111-111111111111", "message": ["first"]}]),
            _make_ok_response([{"id": "22222222-2222-4222-8222-222222222222", "message": ["second"]}]),
            _make_ok_response({"confirmed": False}),
        ]
        with pytest.raises(HumanAuthError):
            client.place_order_and_confirm("U1234567", order, reply_log=reply_log)
    assert [(r["reply_id"], r["confirmed"]) for r in reply_log] == [
        ("11111111-1111-4111-8111-111111111111", True),
        ("22222222-2222-4222-8222-222222222222", False),
    ]
    assert mock_post.call_args_list[2].kwargs.get("json") == {"confirmed": False}


def test_place_order_and_confirm_without_a_log_is_unchanged(client):
    """`reply_log` is optional: callers that pass nothing get exactly the old behaviour."""
    order = {"ticker": "AAPL", "side": "BUY", "quantity": 10}
    with (
        _patch("ibkr_core_mcp.client.require_touch_id"),
        _patch("ibkr_core_mcp.client.confirm_order_dialog"),
        _patch("ibkr_core_mcp.client.confirm_reply_dialog"),
        _patch.object(client._session, "post") as mock_post,
    ):
        mock_post.side_effect = [
            _make_ok_response([{"id": "11111111-1111-4111-8111-111111111111", "message": ["x"]}]),
            _make_ok_response([{"order_status": "Submitted"}]),
        ]
        assert client.place_order_and_confirm("U1234567", order) == [{"order_status": "Submitted"}]


def test_modify_order_and_confirm_records_replies_too(client):
    """The modify chain records its replies the same way as the place chain."""
    reply_log: list[dict[str, Any]] = []
    with (
        _patch("ibkr_core_mcp.client.require_touch_id"),
        _patch("ibkr_core_mcp.client.confirm_modify_dialog"),
        _patch("ibkr_core_mcp.client.confirm_reply_dialog"),
        _patch.object(client._session, "post") as mock_post,
    ):
        mock_post.side_effect = [
            _make_ok_response({"id": "99999999-9999-4999-8999-999999999999", "message": ["price band"]}),
            _make_ok_response({"order_id": "1", "order_status": "Submitted"}),
        ]
        result = client.modify_order_and_confirm("U1234567", "1", {"side": "BUY"}, reply_log=reply_log)
    assert result == {"order_id": "1", "order_status": "Submitted"}
    assert [(r["reply_id"], r["confirmed"]) for r in reply_log] == [("99999999-9999-4999-8999-999999999999", True)]


def test_modify_order_strips_display_only_keys_before_posting(client):
    """The `_`-prefixed display convention (label, multiplier, currency, `_changes`,
    `_current_description`) now applies to modify exactly as to place (2026-09-10)."""
    with (
        _patch("ibkr_core_mcp.client.require_touch_id"),
        _patch("ibkr_core_mcp.client.confirm_modify_dialog"),
        _patch.object(client._session, "post") as mock_post,
    ):
        mock_post.return_value = _make_ok_response({"order_id": "1", "order_status": "Submitted"})
        client.modify_order(
            "U1234567",
            "1",
            {"side": "SELL", "price": 10.0, "_currency": "USD", "_changes": [], "_current_description": "x"},
        )
    assert mock_post.call_args.kwargs.get("json") == {"side": "SELL", "price": 10.0}


# ---------------------------------------------------------------------------
# One authorization per order write (claudia_ui gap #47, user rule 2026-09-11)
# ---------------------------------------------------------------------------


def test_order_write_scope_is_the_account_and_the_canonical_body():
    """Dynamic linking: the same order to the same account gives the same scope; any
    change — the body, the order id, or the account — gives a different one.

    Display-only `_` keys never leave the machine and must not move the scope. The account
    was added on 2026-09-17 (SEC-07): without it an authorization earned for one account
    covered a byte-identical body sent to another."""
    from ibkr_core_mcp.client import _order_write_scope

    body = {
        "conid": 649180671,
        "side": "BUY",
        "quantity": 1,
        "orderType": "STP",
        "auxPrice": 7900,
        "tif": "GTC",
        "cOID": "CLAUDIA-1",
    }
    same = dict(reversed(list(body.items())))
    acct, other = "U1111111", "U9999999"
    assert _order_write_scope("place", acct, body) == _order_write_scope("place", acct, same)
    assert _order_write_scope("place", acct, {**body, "_companyName": "x"}) == _order_write_scope("place", acct, body)
    assert _order_write_scope("place", acct, {**body, "auxPrice": 7901}) != _order_write_scope("place", acct, body)
    assert _order_write_scope("place", acct, body).startswith(f"place:{acct}:")
    assert _order_write_scope("modify", acct, body, order_id="42").startswith(f"modify:{acct}:42:")
    assert _order_write_scope("modify", acct, body, order_id="42") != _order_write_scope(
        "modify", acct, body, order_id="43"
    )
    # SEC-07: the account moves the scope, for both kinds.
    assert _order_write_scope("place", acct, body) != _order_write_scope("place", other, body)
    assert _order_write_scope("modify", acct, body, order_id="42") != _order_write_scope(
        "modify", other, body, order_id="42"
    )


def test_order_label_is_side_quantity_symbol_from_either_spelling():
    """The one line every prompt and dialog names the order by."""
    from ibkr_core_mcp.client import _order_label

    assert _order_label({"side": "BUY", "quantity": 1, "ticker": "ES"}) == "BUY 1 ES"
    assert _order_label({"side": "SELL", "quantity": 2, "symbol": "AAPL"}) == "SELL 2 AAPL"
    assert _order_label({"conid": 1}) == "? ? UNKNOWN"


def _three_reply_chain():
    """The live-verified shape: reply → reply → reply → terminal."""
    return [
        _make_ok_response(
            [{"id": "11111111-1111-4111-8111-111111111111", "message": ["Price is outside of the Price Band."]}]
        ),
        _make_ok_response(
            [{"id": "22222222-2222-4222-8222-222222222222", "message": ["No market data for this contract."]}]
        ),
        _make_ok_response(
            [{"id": "33333333-3333-4333-8333-333333333333", "message": ["This order requires a mandatory cap price."]}]
        ),
        _make_ok_response([{"order_status": "Submitted"}]),
    ]


def test_place_order_and_confirm_asks_for_one_fingerprint_and_four_dialogs(client):
    """The user's rule (2026-09-11): authenticate once per write, validate every message.

    Measured 2026-09-10: this chain cost FOUR Touch IDs. IBKR Mobile and TWS ask once."""
    order = {"ticker": "ES", "side": "BUY", "quantity": 1, "conid": 649180671}
    with (
        _patch("ibkr_core_mcp.client.require_touch_id") as touch_id,
        _patch("ibkr_core_mcp.client.confirm_order_dialog") as order_dlg,
        _patch("ibkr_core_mcp.client.confirm_reply_dialog") as reply_dlg,
        _patch.object(client._session, "post") as mock_post,
    ):
        mock_post.side_effect = _three_reply_chain()
        client.place_order_and_confirm("U1234567", order)
    assert touch_id.call_count == 1
    assert touch_id.call_args.args[0] == "place an IBKR order — BUY 1 ES"
    assert order_dlg.call_count == 1
    assert reply_dlg.call_count == 3
    assert all(c.kwargs.get("order_label") == "BUY 1 ES" for c in reply_dlg.call_args_list)


def test_a_reply_with_no_authorization_still_prompts(client):
    """Fail closed: the standalone paths behave exactly as before."""
    with (
        _patch("ibkr_core_mcp.client.require_touch_id") as touch_id,
        _patch("ibkr_core_mcp.client.confirm_reply_dialog"),
        _patch.object(client._session, "post") as mock_post,
    ):
        mock_post.return_value = _make_ok_response([{"order_status": "Submitted"}])
        client._resolve_one_reply({"id": "11111111-1111-4111-8111-111111111111", "message": ["x"]})
    touch_id.assert_called_once()


def test_a_reply_with_an_expired_or_foreign_authorization_prompts_again(client):
    """Expiry and mismatch both fail closed — never a silent pass on presence alone."""
    import time as _time

    from ibkr_core_mcp.human_auth import OrderWriteAuthorization

    stale = OrderWriteAuthorization("place:x", "BUY 1 ES", granted_at=_time.monotonic() - 10_000.0, ttl_s=1.0)
    foreign = OrderWriteAuthorization("place:other", "SELL 1 ES", granted_at=_time.monotonic(), ttl_s=300.0)
    for auth in (stale, foreign):
        with (
            _patch("ibkr_core_mcp.client.require_touch_id") as touch_id,
            _patch("ibkr_core_mcp.client.confirm_reply_dialog"),
            _patch.object(client._session, "post") as mock_post,
        ):
            mock_post.return_value = _make_ok_response([{"order_status": "Submitted"}])
            client._resolve_one_reply(
                {"id": "11111111-1111-4111-8111-111111111111", "message": ["x"]}, authorization=auth, scope="place:x"
            )
        touch_id.assert_called_once()


def test_place_order_prompts_when_the_body_no_longer_matches_the_authorization(client):
    """Mutation: an authorization for one body does not cover another (dynamic linking)."""
    import time as _time

    from ibkr_core_mcp.client import _order_write_scope
    from ibkr_core_mcp.human_auth import OrderWriteAuthorization

    body = {"ticker": "ES", "side": "BUY", "quantity": 1, "conid": 649180671, "auxPrice": 7900}
    auth = OrderWriteAuthorization(_order_write_scope("place", "U1234567", body), "BUY 1 ES", _time.monotonic(), 300.0)
    with (
        _patch("ibkr_core_mcp.client.require_touch_id") as touch_id,
        _patch("ibkr_core_mcp.client.confirm_order_dialog"),
        _patch.object(client._session, "post") as mock_post,
    ):
        mock_post.return_value = _make_ok_response([{"order_status": "Submitted"}])
        client.place_order("U1234567", {**body, "auxPrice": 7800}, authorization=auth)
        touch_id.assert_called_once()
        touch_id.reset_mock()
        client.place_order("U1234567", body, authorization=auth)
        touch_id.assert_not_called()


def test_place_order_prompts_when_the_authorization_was_for_another_account(client):
    """SEC-07. The scope bound the body and the order id but not the account.

    So an authorization earned for one account covered a byte-identical body sent to
    another: the human approved a write against account A and the same authorization would
    have carried it to account B without a second prompt. The account is part of the
    transaction, so it belongs in the transaction's own data.

    Both ids here are from the frozen placeholder set in
    `tests/security/test_published_identifiers.py` — this is a PUBLIC repository and any
    other account-shaped string fails that scan.
    """
    import time as _time

    from ibkr_core_mcp.client import _order_write_scope
    from ibkr_core_mcp.human_auth import OrderWriteAuthorization

    body = {"ticker": "ES", "side": "BUY", "quantity": 1, "conid": 649180671, "auxPrice": 7900}
    auth = OrderWriteAuthorization(_order_write_scope("place", "U1111111", body), "BUY 1 ES", _time.monotonic(), 300.0)
    with (
        _patch("ibkr_core_mcp.client.require_touch_id") as touch_id,
        _patch("ibkr_core_mcp.client.confirm_order_dialog"),
        _patch.object(client._session, "post") as mock_post,
    ):
        mock_post.return_value = _make_ok_response([{"order_status": "Submitted"}])
        client.place_order("U9999999", body, authorization=auth)
        touch_id.assert_called_once()
        touch_id.reset_mock()
        client.place_order("U1111111", body, authorization=auth)
        touch_id.assert_not_called()


def test_declining_a_reply_still_ends_the_chain_after_one_fingerprint(client):
    """DO NOT REPLY declines to IBKR and aborts (the existing decline test pins the POST);
    the authorization dies with the call frame — no second fingerprint was ever asked."""
    order = {"ticker": "ES", "side": "BUY", "quantity": 1, "conid": 649180671}
    with (
        _patch("ibkr_core_mcp.client.require_touch_id") as touch_id,
        _patch("ibkr_core_mcp.client.confirm_order_dialog"),
        _patch("ibkr_core_mcp.client.confirm_reply_dialog", side_effect=[None, HumanAuthError("declined")]),
        _patch.object(client._session, "post") as mock_post,
    ):
        mock_post.side_effect = [*_three_reply_chain()[:2], _make_ok_response([])]
        with pytest.raises(HumanAuthError):
            client.place_order_and_confirm("U1234567", order)
    assert touch_id.call_count == 1


def test_authorize_order_write_is_touch_id_then_a_frozen_value(monkeypatch):
    """Gate 1 through the one seam this module holds, then the token it grants."""
    from ibkr_core_mcp import client as client_mod
    from ibkr_core_mcp.human_auth import OrderWriteAuthorization

    calls: list[str] = []
    monkeypatch.setattr(client_mod, "require_touch_id", lambda reason: calls.append(reason))
    monkeypatch.setattr("ibkr_core_mcp.client.time.monotonic", lambda: 42.0)
    auth = client_mod._authorize_order_write("place an IBKR order — BUY 1 ES", "place:abc", "BUY 1 ES")
    assert calls == ["place an IBKR order — BUY 1 ES"]
    assert auth == OrderWriteAuthorization("place:abc", "BUY 1 ES", 42.0, 300.0)


def test_authorize_order_write_grants_nothing_when_touch_id_is_denied(monkeypatch):
    """A refused fingerprint raises before any value exists."""
    from ibkr_core_mcp import client as client_mod

    def deny(reason: str) -> None:
        raise HumanAuthError("Touch ID denied")

    monkeypatch.setattr(client_mod, "require_touch_id", deny)
    with pytest.raises(HumanAuthError):
        client_mod._authorize_order_write("place an IBKR order — BUY 1 ES", "place:abc", "BUY 1 ES")


def test_modify_order_and_confirm_asks_for_one_fingerprint(client):
    """Modify is its own transaction — its own Touch ID — and its replies ride on it."""
    order = {
        "conid": 649180671,
        "side": "BUY",
        "quantity": 1,
        "orderType": "STP",
        "auxPrice": 7950,
        "tif": "GTC",
        "ticker": "ES",
    }
    with (
        _patch("ibkr_core_mcp.client.require_touch_id") as touch_id,
        _patch("ibkr_core_mcp.client.confirm_modify_dialog") as modify_dlg,
        _patch("ibkr_core_mcp.client.confirm_reply_dialog") as reply_dlg,
        _patch.object(client._session, "post") as mock_post,
    ):
        mock_post.side_effect = [
            _make_ok_response({"id": "11111111-1111-4111-8111-111111111111", "message": ["Confirm?"]}),
            _make_ok_response({"order_id": "42", "order_status": "Submitted"}),
        ]
        client.modify_order_and_confirm("U1234567", "42", order)
    assert touch_id.call_count == 1
    assert touch_id.call_args.args[0] == "modify IBKR order 42"
    assert modify_dlg.call_count == 1 and reply_dlg.call_count == 1
    assert reply_dlg.call_args.kwargs["order_label"] == "BUY 1 ES (order 42)"


def test_cancel_order_logs_its_gate1_grant(client, caplog):
    """The server log is the independent witness of the fingerprint count: on 2026-09-11 it
    showed 8 of 12 prompts because the four cancels wrote no `Gate 1` line. Now they do."""
    import logging

    with (
        _patch("ibkr_core_mcp.client.require_touch_id"),
        _patch("ibkr_core_mcp.client.confirm_cancel_dialog"),
        _patch.object(client._session, "delete") as mock_del,
        caplog.at_level(logging.INFO, logger="ibkr_core_mcp.client"),
    ):
        mock_del.return_value = _make_ok_response({"msg": "Request was submitted", "order_id": 9876543210})
        client.cancel_order("U1234567", "9876543210")
    assert "Gate 1: granted for cancel:9876543210" in caplog.text


# ============================================================================
# Paginated history must not silently truncate — measured defect, 2026-09-15
# ============================================================================
#
# The endpoint returns at most 1000 data points per request (officially documented:
# https://ibkrcampus.com/docs/web-api/v1/endpoints/market-data/historical-market-data.md
# "This endpoint provides a maximum of 1000 data points"). It does NOT error when a
# window would exceed that — it silently returns the newest 1000 and drops the rest.
#
# `_chunk_days_for_bar` sized chunks from `_BARS_PER_CALENDAR_DAY`, which was wrong for
# every intraday bar size, and then floored the result at 7 days. Measured live against a
# real gateway on 2026-09-15 (GLD, outsideRth=true), asking for exactly one chunk width:
#
#     bar     declared bpd   chunk asked   actually spanned   true bpd
#     1min    135            7d            1.03d              ~971
#     5min    27             29d           7.14d              ~140
#     30min   4.5            177d          43.15d             ~23
#     1h      3.25           246d          89.25d             ~11
#     4h      0.8            1000d         331d               ~3
#     1d      0.69           1000d         1456d              0.687   (correct)
#     1w      0.143          1000d         1454d              0.144   (correct)
#
# Only the daily and weekly entries were calibrated. Every intraday size was wrong by
# 2.7x to 7x, so the loop advanced its cursor a full chunk width while the response
# covered a fraction of it — leaving an unannounced hole between every pair of chunks.
# `get_market_history_paginated(conid, period="30d", bar="1min")` returned a well-formed
# result missing roughly 85% of its bars.
#
# It stayed green because the existing stub returns ONE bar per call and therefore never
# reaches the cap — a double easier than the real thing. The stub below caps like the
# real endpoint does, which is the whole point of it.


def _capped_get(bar_seconds: int, max_points: int = 1000, bars_per_day: float = 86400.0):
    """A `_get` double that truncates like IBKR: newest `max_points` bars, silently.

    `bars_per_day` defaults to a continuously-traded instrument (a 24h futures session),
    which is the worst case and the one that must not lose data.
    """
    import calendar
    from datetime import datetime, timedelta

    calls: list[dict[str, Any]] = []

    def _fake(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        params = params or {}
        calls.append(params)
        end = (
            datetime.strptime(params["startTime"], "%Y%m%d-%H:%M:%S") if params.get("startTime") else datetime.utcnow()
        )
        days = float(str(params["period"]).rstrip("dhwmy") or 0)
        unit = str(params["period"]).lstrip("0123456789.")
        days = days / 24.0 if unit == "h" else days
        start = end - timedelta(days=days)
        step = timedelta(seconds=bar_seconds)
        stamps: list[datetime] = []
        t = end
        while t > start and len(stamps) < 10 * max_points:
            stamps.append(t)
            t -= step
        stamps = stamps[:max_points]  # IBKR keeps the NEWEST 1000 and drops the rest
        # `stamps` are naive datetimes holding UTC, matching client.py's `datetime.utcnow()`.
        # `.timestamp()` would read them as LOCAL time and shift every bar by the machine's
        # UTC offset, while client.py decodes with the naive-UTC `utcfromtimestamp` — the two
        # then disagree by that offset, silently, and the disagreement is zero on a UTC CI
        # runner. `calendar.timegm` is the naive-UTC inverse and keeps the double honest.
        return {
            "data": [
                {"t": calendar.timegm(s.timetuple()) * 1000, "o": 1, "h": 1, "l": 1, "c": 1, "v": 1}
                for s in sorted(stamps)
            ]
        }

    return _fake, calls


def test_paged_intraday_leaves_no_gap_when_the_endpoint_caps_at_1000(client):
    """The defect, stated as a property: no hole may open between chunks.

    A chunk that hits the 1000-point cap covers less ground than it asked for. If the
    loop still advances by the requested width, the difference is lost silently. This is
    the assertion the old day-counting loop cannot satisfy for any intraday bar.
    """
    fake, _ = _capped_get(bar_seconds=60)
    with patch.object(client, "_get", side_effect=fake):
        out = client.get_market_history_paginated(265598, period="30d", bar="1min")

    stamps = sorted(b["t"] for b in out.get("data", []))
    assert stamps, "no bars returned at all"
    gaps = [(b - a) / 1000 for a, b in itertools.pairwise(stamps) if b - a > 60_000]
    assert not gaps, (
        f"{len(gaps)} gap(s) in a 1-minute series; largest {max(gaps) / 3600:.1f}h. "
        "A chunk hit the 1000-point cap and the cursor advanced past what it returned."
    )


def test_paged_intraday_reaches_back_the_full_requested_period(client):
    """Coverage measured in delivered bars, not in requested chunk widths.

    The old test summed `period=` values across chunks, which is what the caller asked
    for, not what arrived. Under truncation those two diverge completely.
    """
    from datetime import datetime, timedelta

    fake, _ = _capped_get(bar_seconds=60)
    with patch.object(client, "_get", side_effect=fake):
        out = client.get_market_history_paginated(265598, period="30d", bar="1min")

    stamps = sorted(b["t"] for b in out.get("data", []))
    oldest = datetime.utcfromtimestamp(stamps[0] / 1000)
    wanted = datetime.utcnow() - timedelta(days=30)
    short_by = (oldest - wanted).total_seconds() / 86400
    assert short_by < 1.0, f"30d requested, oldest bar is only {30 - short_by:.1f}d back"


def test_chunk_width_never_exceeds_ibkrs_permitted_period_for_that_bar():
    """Staying inside the Step Size table is a correctness property, not tidiness.

    A period outside the permitted range for a bar is not rejected — and this endpoint is
    already known to answer an out-of-range input by silently substituting a *different*
    bar size (measured for uppercase units: `6M` returned ~84 bars where `6m` returned six
    months). A chunk wider than the table allows is therefore a request whose returned bar
    size is not guaranteed to be the one asked for.

    Source, scraped 2026-09-15:
    https://ibkrcampus.com/docs/web-api/v1/endpoints/market-data/historical-market-data.md
    """
    from ibkr_core_mcp.client import _MAX_PERIOD_DAYS_FOR_BAR, _chunk_days_for_bar

    for bar, permitted in _MAX_PERIOD_DAYS_FOR_BAR.items():
        assert _chunk_days_for_bar(bar) <= permitted, (
            f"{bar}: chunk of {_chunk_days_for_bar(bar)}d exceeds IBKR's permitted "
            f"maximum period of {permitted}d for that bar size"
        )


def test_chunk_width_stays_within_the_1000_point_cap():
    """Over the cap the newest 1000 bars come back and the rest are dropped with no error.

    Because the loop advances by what it *receives*, a truncated chunk is safe — and for the
    finest bars it is actually optimal: `1d/1min` on a 24h instrument asks for 1440 and gets
    a full 1000, advancing further per request than any narrower window could. There is no
    `{n}d` period below one day, so that case is a floor, not a miscalculation.

    What is a defect is a chunk over the cap for a bar where a narrower period **does**
    exist — the old behaviour asked seven days of 1-minute bars, ~10,000 points against a
    cap of 1000, when a 1-day window was available and fits far better.
    """
    from ibkr_core_mcp.client import _BARS_PER_CALENDAR_DAY, _MAX_POINTS, _chunk_days_for_bar

    for bar, bpd in _BARS_PER_CALENDAR_DAY.items():
        days = _chunk_days_for_bar(bar)
        points = days * bpd
        assert points <= _MAX_POINTS or days == 1, (
            f"{bar}: a {days}d chunk implies {points:.0f} points against a "
            f"{_MAX_POINTS}-point cap, and a narrower period was available"
        )


def test_intraday_bars_per_day_are_sized_for_a_24h_session_not_equity_hours():
    """The regression that produced the defect: the table was calibrated for US equity
    regular hours, so every futures request under-counted by ~3.7x and over-asked by the
    same factor. Measured live 2026-09-15 — GLD with `outsideRth=true` returns ~960
    one-minute bars per calendar day, and a 24h future would return 1440.
    """
    from ibkr_core_mcp.client import _BARS_PER_CALENDAR_DAY

    assert _BARS_PER_CALENDAR_DAY["1min"] >= 960, (
        "1-minute bars must be sized for a continuously-traded session; "
        "anything lower under-counts a futures day and silently over-asks"
    )
    for bar, minutes in (("5min", 5), ("15min", 15), ("1h", 60)):
        assert _BARS_PER_CALENDAR_DAY[bar] == pytest.approx(1440 / minutes), (
            f"{bar} must scale with the 1-minute figure over a 24h session"
        )


def test_paged_single_chunk_intraday_still_reaches_back_the_full_period(client):
    """The branch `2a228d7` did not reach: a request that fits in ONE chunk width but not
    in one 1000-point call.

    `_chunk_days_for_bar("1min")` floors at 1 day, and one day of 1-minute bars is 1440
    points against a 1000-point cap. Because `total_days <= chunk_days` is then true, the
    method short-circuited to a single un-paginated `get_market_history` — bypassing the
    very loop whose cursor makes correctness independent of the size estimate — and
    returned the newest 1000 bars with no error and no warning: 69.4% of the day.

    `1min` is the only bar size whose one-day floor exceeds the cap, and it is the most
    used intraday size. The 2026-09-15 live verification used 5d/1min and 30d/5min, both
    of which take the loop, so this branch was never exercised.

    The fast path is an optimisation, and it is only sound when a single call demonstrably
    fits. That is what this test pins.
    """
    from datetime import datetime, timedelta

    fake, calls = _capped_get(bar_seconds=60)
    with patch.object(client, "_get", side_effect=fake):
        out = client.get_market_history_paginated(265598, period="1d", bar="1min")

    stamps = sorted(b["t"] for b in out.get("data", []))
    assert stamps, "no bars returned at all"
    oldest = datetime.utcfromtimestamp(stamps[0] / 1000)
    short_by = (oldest - (datetime.utcnow() - timedelta(days=1))).total_seconds() / 86400
    assert short_by < 0.05, (
        f"1d of 1-minute bars requested, oldest bar is only {1 - short_by:.2f}d back "
        f"({len(stamps)} bars in {len(calls)} request(s)). The single-chunk fast path "
        "returned one capped call instead of paginating."
    )


def test_paged_daily_bars_that_fit_in_one_call_are_not_paginated(client):
    """The counter-case that stops the fix becoming "always paginate".

    A request whose whole span fits inside one 1000-point call must still cost exactly one
    request — 1 day of DAILY bars is one bar, and paginating it would both waste a request
    and over-fetch, since the loop asks for a full `chunk_days` width (1000 days here).
    """
    fake, calls = _capped_get(bar_seconds=86400, bars_per_day=1.0)
    with patch.object(client, "_get", side_effect=fake):
        client.get_market_history_paginated(265598, period="1d", bar="1d")

    assert len(calls) == 1, f"a one-bar request should cost one call, took {len(calls)}: {calls}"
    assert "startTime" not in calls[0], "a single-call request must not paginate"
    # The over-fetch assertion, and the one with teeth: the loop asks for a full
    # `chunk_days` width (1000d for daily bars), so a fix that simply always paginated
    # would still cost one call here while silently requesting a thousand days of history
    # for a one-day question. Counting calls alone does not catch that.
    assert calls[0]["period"] == "1d", f"asked IBKR for {calls[0]['period']!r}, caller asked for '1d'"


def test_capped_get_stub_timestamps_are_utc_regardless_of_local_timezone():
    """The pagination doubles must not shift with the developer's timezone.

    `_capped_get` builds bars from `datetime.utcnow()` — a naive datetime holding UTC —
    and encodes them with `.timestamp()`, which interprets a naive datetime as LOCAL time.
    `client.py` decodes with `datetime.utcfromtimestamp()`, which is naive-UTC. The two
    disagree by the local UTC offset, so every coverage assertion in this file silently
    moved by that offset: on a UTC runner (CI) the skew is zero, on UTC-4 it is four hours.

    That is how a test can be "green everywhere it runs" and still be measuring something
    other than what it claims. Found 2026-09-16 while sweeping the period/bar matrix, where
    it made eight correct combinations look short.
    """
    import os
    import time
    from datetime import datetime

    # Pin a non-UTC zone for the duration. Without this the test is vacuous on a UTC
    # runner — which is exactly why CI never noticed, and why asserting it only on the
    # developer's machine would be no guard at all.
    previous = os.environ.get("TZ")
    os.environ["TZ"] = "America/New_York"
    time.tzset()
    try:
        fake, _ = _capped_get(bar_seconds=60)
        result = fake("/iserver/marketdata/history", {"conid": 1, "period": "1d", "bar": "1min"})
        newest = max(b["t"] for b in result["data"])

        # Decode exactly as client.py does, and compare to the clock the stub itself read.
        decoded = datetime.utcfromtimestamp(newest / 1000)
        skew_hours = abs((decoded - datetime.utcnow()).total_seconds()) / 3600
    finally:
        if previous is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = previous
        time.tzset()

    assert skew_hours < 1.0, (
        f"stub bars land {skew_hours:.1f}h from UTC now — the double disagrees with the "
        "code it stands in for, by exactly the local UTC offset"
    )


# ---------------------------------------------------------------------------
# The "object wrapping the array" class of silent empty.
#
# `return data if isinstance(data, list) else []` reports "none" for a response that is
# an OBJECT keying the array under a name. Found and fixed three times already —
# get_currency_pairs (2026-06-30), get_secdef (2026-07-28), get_watchlists (found live
# 2026-07-23, fixed 2026-08-11) — and never swept. These three are the remaining live
# instances, each confirmed against a real gateway on 2026-09-16 with real data being
# discarded: 10 algos, an open position, and 11 transactions.
# ---------------------------------------------------------------------------


def test_get_contract_algos_reads_the_algos_array_out_of_its_wrapper(client):
    """`{"algos": [...]}` — documented as "algos: Array of objects", measured live at 10.

    Source: https://www.interactivebrokers.com/docs/web-api/v1/endpoints/contract/search-algo-params-by-contract-id.md
    """
    payload = {"algos": [{"id": "Adaptive", "name": "Adaptive"}, {"id": "TWAP", "name": "TWAP"}]}
    with patch.object(client, "_get", return_value=payload):
        # `Algo` rows since 2026-09-17; compare the payload they carry, because
        # `IBKRResponse.__eq__` is pydantic's, not a dict's.
        assert [dict(a) for a in client.get_contract_algos(51529211)] == payload["algos"]


def test_get_positions_by_conid_flattens_the_account_keyed_wrapper(client):
    """Live 2026-09-16 the gateway returned `{"<acct>": [...], "<acct>C": [...]}`.

    The published sample shows a bare array instead, so both shapes are accepted — the
    documented one and the one the gateway actually sends. Recorded as a verified-not-
    assumed divergence in docs/ibkr-api-behaviors-reference.md.

    Source: https://www.interactivebrokers.com/docs/web-api/v1/endpoints/portfolio/positions-by-conid.md
    """
    payload = {
        "U1111111": [{"acctId": "U1111111", "conid": 51529211, "position": 10.0}],
        "U1111111C": [{"acctId": "U1111111C", "conid": 51529211, "position": 4.0}],
    }
    with patch.object(client, "_get", return_value=payload):
        rows = client.get_positions_by_conid(51529211)
    assert len(rows) == 2, "both account buckets must survive"
    assert {r["acctId"] for r in rows} == {"U1111111", "U1111111C"}


def test_get_positions_by_conid_still_accepts_the_documented_bare_array(client):
    """The counter-case: the published sample is a bare array, so it must keep working."""
    rows = [{"acctId": "U1111111", "conid": 265598, "position": 614.2639}]
    with patch.object(client, "_get", return_value=rows):
        assert client.get_positions_by_conid(265598) == rows


def test_get_pa_transactions_reads_the_transactions_array_out_of_its_wrapper(client):
    """`{"transactions": [...], "rpnl": {...}, "currency": ..., "from": ..., "to": ...}`.

    The endpoint is documented as returning an object and never a bare array, so the
    `isinstance(data, list)` check could not match on any response: the method returned
    `[]` for every account, always. Measured live 2026-09-16 against an account holding
    the queried contract: 11 transactions returned by IBKR, 0 by this method.

    Source: https://www.interactivebrokers.com/docs/web-api/v1/endpoints/portfolio-analyst/transaction-history.md
    """
    txns = [{"acctid": "U1111111", "conid": 51529211, "amt": "-100.0", "date": "20260804", "type": "BUY"}]
    payload = {
        "id": "getTransactions",
        "currency": "USD",
        "from": 1757980800000,
        "to": 1789516800000,
        "nd": 366,
        "rpnl": {"amt": 1.0, "data": []},
        "transactions": txns,
    }
    with patch.object(client, "_post", return_value=payload):
        assert client.get_pa_transactions(["U1111111"], [51529211], "USD", 365) == txns


# Endpoints whose top-level response is a BARE ARRAY, so `data if isinstance(data, list)
# else []` is correct for them.
#
# How each line was established, 2026-09-16 — page names were NOT guessed. Every page under
# `v1/endpoints/` in `llms.txt` (123 of them) was fetched, each page's own endpoint
# declaration was extracted (`GET /portfolio/positions/{conid}` and the unbackticked and
# `{{ jinja }}` variants), and the method was matched to the page DECLARING ITS ENDPOINT.
# That matters: `positions-by-conid.md` and `position-contract-info.md` are both plausible
# names for `get_positions_by_conid`, and the first one documents a different endpoint
# entirely — matching by name picked the wrong page and produced a wrong "divergence".
# Matched this way, all 14 `Source:` URLs already in client.py are correct.
#
# "documented" is the top-level bracket of the JSON sample under that page's own
# "Response Object" heading. "live" is the raw type observed against an authenticated
# gateway the same day. A fabricated control URL was fetched in the same batch and
# correctly returned "# Page Not Found", so the check was capable of failing.
_BARE_ARRAY_ENDPOINTS = {
    "get_market_snapshot": "market-data/live-market-data-snapshot: documented ARRAY; live list",
    "search_contract": "contract/search-contract-by-symbol: documented ARRAY; live list of 3",
    "get_accounts": "portfolio/portfolio-accounts: documented ARRAY; live list of 1",
    "get_subaccounts": "portfolio/portfolio-subaccounts: documented ARRAY; live list of 1",
    "get_positions": "portfolio/positions: documented ARRAY; live list of 2",
    "get_trades": "order-monitoring/trades: documented ARRAY; live list of 4",
    "get_notifications": "fy-is-and-notifications/get-a-list-of-notifications: documented ARRAY; live list of 3",
    "get_alerts": "alerts/get-a-list-of-available-alerts: documented ARRAY; live list, empty (account holds no alerts)",
    "get_combo_positions": (
        "portfolio/combination-positions: documented ARRAY; live UNCONFIRMED — HTTP 500, "
        "the account holds no combo positions, so no payload was observed"
    ),
    "reply_order": (
        "orders/place-order-reply-confirmation: documented ARRAY, and the only shape that page "
        "publishes; live UNVERIFIED — a reply is an order write and is never driven by a test"
    ),
    "get_forecast_market": (
        "trading-event-contracts/get-forecast-markets: documented OBJECT with a `contracts` list; "
        "live UNVERIFIED — event contracts need a subscription this account does not hold, so no "
        "response has ever been observed. The row it replaced, `get_event_contracts`, called a "
        "path absent from IBKR's documentation entirely (API-R4)"
    ),
}


def test_no_new_endpoint_silently_discards_an_object_response():
    """Guard against a defect class this repo has now fixed four times.

    `return data if isinstance(data, list) else []` turns "the response was an object"
    into "there was no data" — silently, with no error and no log. It has been found and
    fixed in `get_currency_pairs` (2026-06-30), `get_secdef` (2026-07-28), `get_watchlists`
    (found live 2026-07-23, fixed 2026-08-11) and, on 2026-09-16, in `get_contract_algos`,
    `get_positions_by_conid` and `get_pa_transactions` — the last of which had returned an
    empty list for every account since it was written, while IBKR was returning 11
    transactions.

    Four point-fixes and no sweep is what let the fourth happen, so this is the sweep made
    permanent: a method may use the bare pattern only if its endpoint is on
    `_BARE_ARRAY_ENDPOINTS` with the evidence that says why. A new method using it fails
    here until someone checks the actual response shape — which is the whole point, because
    every instance of this bug was invisible until somebody looked at a real payload.
    """
    import ast
    import pathlib

    from ibkr_core_mcp import client as client_mod

    # The module actually imported, not a path relative to wherever pytest was started:
    # from outside the repo root this raised FileNotFoundError (API-R7, 2026-09-17).
    source = pathlib.Path(client_mod.__file__).read_text()
    lines = source.splitlines()
    offenders = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.FunctionDef):
            continue
        # The code, not the docstring: a method whose docstring QUOTES the bare pattern to
        # explain its own fix tripped this guard on 2026-09-17 the moment its code stopped
        # carrying the `isinstance(data, dict)` exemption (API-R10) — the third guard in two
        # days to read prose. Matching starts at the first statement after the docstring.
        statements = node.body[1:] if ast.get_docstring(node) is not None else node.body
        if not statements:
            continue
        body = "\n".join(lines[statements[0].lineno - 1 : node.end_lineno])
        if "isinstance(data, list) else []" not in body:
            continue
        if "isinstance(data, dict)" in body:
            continue  # already unwraps an object before falling back
        if node.name not in _BARE_ARRAY_ENDPOINTS:
            offenders.append(f"{node.name} (line {node.lineno})")

    assert not offenders, (
        "These methods collapse an object response to [] without unwrapping it, and are "
        "not recorded as returning a bare array:\n  "
        + "\n  ".join(offenders)
        + "\n\nCheck the endpoint's real response against a live gateway AND its published "
        "sample. If it truly returns a bare array, add it to _BARE_ARRAY_ENDPOINTS with "
        "that evidence. If it returns an object, unwrap the array — see get_secdef."
    )


def test_place_order_surfaces_ibkrs_rejection_object_instead_of_an_empty_list(client):
    """IBKR's documented rejection is a top-level OBJECT, and it must reach the caller.

    `place-order.md` documents three response shapes: the normal array, the Alternate
    (reply-required) array, and — under that same Alternate heading — a bare object:

        {"error": "We cannot accept an order at the limit price you selected. Please
                   submit your order using a limit price that is closer to the current
                   market price of 197.79. ..."}

    `return data if isinstance(data, list) else []` collapsed that to `[]`, so an order
    IBKR refused for a stated reason was reported to the caller as an empty response —
    indistinguishable from "nothing happened", with the reason discarded. On the order
    path that is the one place where losing IBKR's own words is least acceptable.

    `_as_reply_list` already existed to turn a bare dict into a one-element list, but it
    is applied by `place_order_and_confirm` one layer OUTSIDE `place_order`, so the dict
    was destroyed before the defence ever saw it.

    Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/orders/place-order.md
    """
    rejection = {
        "error": "We cannot accept an order at the limit price you selected. "
        "Please submit your order using a limit price that is closer to the current market price."
    }
    order = {"ticker": "AAPL", "side": "BUY", "quantity": 100, "orderType": "LIMIT", "price": 1.0}
    with (
        _patch("ibkr_core_mcp.client.require_touch_id"),
        _patch("ibkr_core_mcp.client.confirm_order_dialog"),
        _patch.object(client._session, "post") as mock_post,
    ):
        mock_post.return_value = _make_ok_response(rejection)
        result = client.place_order("U1234567", order)

    assert result, "IBKR's rejection reason was discarded — the caller sees nothing"
    assert result[0].get("error") == rejection["error"]


def test_place_order_still_returns_the_documented_array_unchanged(client):
    """The counter-case: the normal and reply-required responses are arrays and must pass
    through untouched, so the fix above cannot quietly re-wrap them."""
    payload = [{"id": "07a13a5a", "message": ["price exceeds the Percentage constraint of 3%"]}]
    order = {"ticker": "AAPL", "side": "BUY", "quantity": 100, "orderType": "LIMIT", "price": 182.5}
    with (
        _patch("ibkr_core_mcp.client.require_touch_id"),
        _patch("ibkr_core_mcp.client.confirm_order_dialog"),
        _patch.object(client._session, "post") as mock_post,
    ):
        mock_post.return_value = _make_ok_response(payload)
        assert client.place_order("U1234567", order) == payload


def _orders_paths(mock_get, client):
    """Just the /iserver/account/orders request paths, in order."""
    return [
        call[0][0].replace(client._base, "")
        for call in mock_get.call_args_list
        if "/iserver/account/orders" in call[0][0]
    ]


def test_get_live_orders_does_not_re_prime_when_the_first_read_returns_orders(client):
    """The `force=true` call was made before EVERY read. It is a subscription warmup —
    "A fresh brokerage session returns an EMPTY list on the first call" — so it is needed
    once per session, not once per call, and the sibling `get_trades` already reads first
    and only retries on empty.

    Measured live 2026-09-16 on a warm session: three consecutive plain reads with no
    `force=true` ahead of them each returned the open order. Meanwhile the endpoint is
    published at 1 req/5 secs, so the unconditional pair cost a full extra slot of a
    rate-limited endpoint every single time — `get_live_orders()` took 5.17 s, and 10.07 s
    when called twice in a row.
    """
    client._accounts_initialized = True
    orders = [{"orderId": 1, "ticker": "AAPL", "status": "Submitted"}]
    with patch.object(client._session, "get") as mock_get, patch("time.sleep"):
        mock_get.return_value = _make_ok_response({"orders": orders})
        result = client.get_live_orders()

    paths = _orders_paths(mock_get, client)
    assert result and result[0]["orderId"] == 1
    assert paths == ["/iserver/account/orders"], f"expected one plain read, got {paths}"
    assert not any("force=true" in p for p in paths), "warmup fired despite data arriving"


def test_get_live_orders_primes_the_subscription_when_the_first_read_is_empty(client):
    """The counter-case, and the reason the warmup exists at all. Without it, "read once
    and trust the empty" would satisfy the test above while breaking a cold session —
    which is the exact bug the unconditional warmup was guarding against.
    """
    client._accounts_initialized = True
    orders = [{"orderId": 7, "ticker": "SPY", "status": "PreSubmitted"}]
    with patch.object(client._session, "get") as mock_get, patch("time.sleep"):
        mock_get.side_effect = [
            _make_ok_response({"orders": []}),  # cold session
            _make_ok_response({"orders": []}),  # force=true, documented to return blank
            _make_ok_response({"orders": orders}),  # primed
        ]
        result = client.get_live_orders()

    paths = _orders_paths(mock_get, client)
    assert result and result[0]["orderId"] == 7
    assert paths == [
        "/iserver/account/orders",
        "/iserver/account/orders?force=true",
        "/iserver/account/orders",
    ], paths


def test_get_live_orders_still_reports_a_genuine_empty_after_priming(client):
    """An empty list is a real answer — "that empty is an answer". Priming must not turn
    "no live orders" into an error or an endless retry."""
    client._accounts_initialized = True
    with patch.object(client._session, "get") as mock_get, patch("time.sleep"):
        mock_get.return_value = _make_ok_response({"orders": []})
        result = client.get_live_orders()

    assert result == []
    assert len(_orders_paths(mock_get, client)) == 3, "must prime exactly once, then stop"


def test_paginated_history_declares_it_when_the_chunk_guard_truncates(client):
    """`_MAX_CHUNKS` produced a well-formed short answer and only a log line.

    A `log.warning` reaches no caller, no model and no cache. Measured against the
    IBKR-accurate truncating stub, the shortfall is not marginal:

        180d/1min  ->  120 chunks, 83.2 of 180 days  =  46% of what was asked
        1y/5min    ->  120 chunks, 119.6 of 365 days =  33%

    A backtest labelled "1 year" that silently covers four months draws a conclusion
    about a period it never saw. The response must say so in the response.
    """
    fake, calls = _capped_get(bar_seconds=60, bars_per_day=1440.0)
    with patch.object(client, "_get", side_effect=fake):
        out = client.get_market_history_paginated(265598, period="180d", bar="1min")

    from ibkr_core_mcp.client import _MAX_CHUNKS

    assert len(calls) == _MAX_CHUNKS, "this request must actually hit the guard"
    assert out.get("data"), "bars still come back — they are real, just fewer"
    warning = out.get("ibkr_core_warning")
    assert warning, "a truncated result must carry a warning the caller can read"
    assert "180d" in warning, warning
    assert str(_MAX_CHUNKS) in warning, warning


def test_paginated_history_says_nothing_when_it_covered_the_whole_request(client):
    """The counter-case. A warning on every response is a warning on none, and
    "always warn" would satisfy the test above."""
    fake, calls = _capped_get(bar_seconds=60, bars_per_day=1440.0)
    with patch.object(client, "_get", side_effect=fake):
        out = client.get_market_history_paginated(265598, period="30d", bar="1min")

    from ibkr_core_mcp.client import _MAX_CHUNKS

    assert len(calls) < _MAX_CHUNKS, "this request must NOT hit the guard"
    assert "ibkr_core_warning" not in out, f"unexpected warning: {out.get('ibkr_core_warning')}"


def test_paginated_history_removes_bars_repeated_across_a_chunk_seam():
    """De-duplication had no test of its own, and live data cannot supply one.

    Measured against the real gateway 2026-09-16, consecutive chunks came back with no
    overlap at all (5d/5min: 299 bars from the chunks, 299 unique; 5d/1min: 1495 and
    1495), so the live suite cannot exercise this — a mutant removing the de-dup survives
    there. In the unit suite that mutant was "caught" only by accident: the early return
    it introduced also skipped the API-02 truncation warning, so an unrelated test failed.
    That is not coverage, which is why this exists.

    `get_market_history_paginated` anchors each chunk at the previous chunk's OLDEST
    timestamp, so a boundary bar returned by both chunks is exactly what the cursor
    protocol invites.

    Note the parameters: `30d`/`1min` is chosen because it does NOT satisfy
    `_fits_in_one_call`, so the pagination loop actually runs. A first attempt used
    `30d`/`1d`, which takes the un-paginated fast path — the stub's chunks came straight
    back untouched and the test was measuring nothing. That is the same fast-path blind
    spot as API-01.
    """
    import calendar
    import pathlib
    from datetime import datetime, timedelta

    from ibkr_core_mcp.client import IBKRClient
    from ibkr_core_mcp.config import Config

    cfg = Config(
        gateway_url="https://localhost:5055/v1/api",
        gdrive_folder_id="x",
        sqlite_path=pathlib.Path("/tmp/x.db"),
        gdrive_token_file=pathlib.Path("/tmp/t.json"),
        gdrive_credentials_file=pathlib.Path("/tmp/c.json"),
    )
    c = IBKRClient(cfg)

    def ms(dt):
        return calendar.timegm(dt.timetuple()) * 1000

    # Recent bars, so the loop does not stop on its first chunk for being past the target.
    now = datetime.utcnow()
    minute = timedelta(minutes=1)

    def chunk(first, count):
        return {
            "data": [
                {"t": ms(now - (first + i) * minute), "o": 1, "h": 1, "l": 1, "c": 1, "v": 1} for i in range(count)
            ]
        }

    # The second chunk repeats the first's oldest bar — the shared seam.
    served = iter([chunk(0, 500), chunk(499, 500), {"data": []}])

    with patch.object(c, "_get", side_effect=lambda *a, **k: next(served, {"data": []})):
        out = c.get_market_history_paginated(265598, period="30d", bar="1min")

    stamps = [b["t"] for b in out["data"]]
    assert len(stamps) > 900, f"the pagination loop did not run — only {len(stamps)} bars"
    assert len(stamps) == len(set(stamps)), (
        f"the shared boundary bar survived: {len(stamps)} bars, {len(set(stamps))} unique"
    )
    assert stamps == sorted(stamps), "bars must come back in ascending time order"


# ---------------------------------------------------------------------------
# FYI writes — both methods contradicted the pages they cite (API-20, API-21)
# ---------------------------------------------------------------------------


def test_mark_notification_read_uses_the_documented_verb_and_path(client):
    """IBKR documents `PUT /fyi/notifications/{notificationId}` with an empty body.

    This method sent `POST /fyi/notifications/{id}/read` — a verb and a path IBKR
    publishes nowhere. Two independent documentation families agree:
    v1/endpoints/fy-is-and-notifications/mark-notification-read.md and
    api-reference/trading/trading-fy-is-and-notifications/read-fyi-notification.md.

    The live test that was meant to cover this accepted success, 400, 404 and 423 —
    every outcome the call can produce — so it passed whether or not the endpoint existed.
    """
    with patch.object(client._session, "put") as mock_put:
        mock_put.return_value = _make_ok_response({"V": 1, "T": 12})
        result = client.mark_notification_read("2026091616556319")

    url = mock_put.call_args.args[0] if mock_put.call_args.args else mock_put.call_args.kwargs["url"]
    assert url.endswith("/fyi/notifications/2026091616556319")
    assert not url.endswith("/read")
    assert result == {"V": 1, "T": 12}


def test_mark_notification_read_rejects_a_traversing_id(client):
    with patch.object(client._session, "put") as mock_put, pytest.raises(ConfigError):
        client.mark_notification_read("../../iserver/account/orders")
    mock_put.assert_not_called()


def test_update_delivery_option_device_sends_the_four_documented_fields(client):
    """`device` is POST /fyi/deliveryoptions/device with a JSON body.

    The body was `{"deviceId", "enabled"}` — 2 of the 4 fields the endpoint documents,
    the same shape of defect as the alert-modify body (TOOL-01).
    """
    with patch.object(client._session, "post") as mock_post:
        mock_post.return_value = _make_ok_response({"V": 1})
        client.update_delivery_option("apn://mtws@ABC", "device", True, device_name="iPhone", ui_name="iPhone")

    url = mock_post.call_args.args[0] if mock_post.call_args.args else mock_post.call_args.kwargs["url"]
    assert url.endswith("/fyi/deliveryoptions/device")
    assert mock_post.call_args.kwargs["json"] == {
        "deviceName": "iPhone",
        "deviceId": "apn://mtws@ABC",
        "uiName": "iPhone",
        "enabled": True,
    }


def test_update_delivery_option_email_is_a_put_with_a_query_parameter(client):
    """`email` is PUT /fyi/deliveryoptions/email?enabled=… — a different verb and a
    different parameter style from `device`, which is why one parameterised path could
    not serve both."""
    with patch.object(client._session, "put") as mock_put:
        mock_put.return_value = _make_ok_response({"V": 1})
        client.update_delivery_option(None, "email", False)

    url = mock_put.call_args.args[0] if mock_put.call_args.args else mock_put.call_args.kwargs["url"]
    assert url.endswith("/fyi/deliveryoptions/email")
    assert mock_put.call_args.kwargs["params"] == {"enabled": "false"}


def test_update_delivery_option_rejects_an_undocumented_channel(client):
    with (
        patch.object(client._session, "post") as mock_post,
        patch.object(client._session, "put") as mock_put,
        pytest.raises(ConfigError),
    ):
        client.update_delivery_option("d", "sms", True)
    mock_post.assert_not_called()
    mock_put.assert_not_called()


def test_get_trading_schedule_sends_conid_instead_of_symbol_not_alongside_it(client):
    """IBKR's page marks **both** `conid` and `symbol` Required. The live gateway disagrees:

        {"error":"Bad Request: assetClass and exactly one of symbol/conid are required"}

    Measured 2026-09-16 against an authenticated gateway. Sending both is an HTTP 400 every
    time, so the first version of this fix — which appended `conid` beside `symbol` because
    the documentation called it Required — shipped a guaranteed error. The documentation is
    wrong and the gateway is the authority.
    """
    from unittest.mock import patch

    with patch.object(client, "_get", return_value=[]) as get:
        client.get_trading_schedule("STK", exchange="ISLAND", conid=265598)

    params = get.call_args.args[1]
    assert params["conid"] == "265598"
    assert "symbol" not in params, "symbol must not be sent alongside conid — IBKR returns 400"
    assert params["assetClass"] == "STK"


def test_get_trading_schedule_sends_symbol_when_no_conid_is_given(client):
    """The counter-case, and the ordinary call: symbol alone, no `conid` key at all."""
    from unittest.mock import patch

    with patch.object(client, "_get", return_value=[]) as get:
        client.get_trading_schedule("STK", "AAPL", "ISLAND")

    params = get.call_args.args[1]
    assert params["symbol"] == "AAPL"
    assert "conid" not in params


def test_get_trading_schedule_refuses_both_symbol_and_conid_before_the_network(client):
    """Fail fast and locally, rather than spending a request to be told 400 by IBKR. The
    message names the constraint the gateway enforces, in IBKR's own words."""
    from unittest.mock import patch

    from ibkr_core_mcp.exceptions import ConfigError

    with patch.object(client, "_get") as get, pytest.raises(ConfigError, match="exactly one"):
        client.get_trading_schedule("STK", "AAPL", "ISLAND", conid=265598)

    get.assert_not_called()


def test_get_trading_schedule_refuses_neither_symbol_nor_conid(client):
    """`assetClass` alone is also a 400. Both arms, so the check cannot be satisfied by
    always raising or never raising."""
    from unittest.mock import patch

    from ibkr_core_mcp.exceptions import ConfigError

    with patch.object(client, "_get") as get, pytest.raises(ConfigError, match="exactly one"):
        client.get_trading_schedule("STK", exchange="ISLAND")

    get.assert_not_called()


# ── API-17: every caller read page 0 and stopped ──────────────────────────────


def test_get_all_positions_pages_until_an_empty_page(client):
    """A page past the end returns `[]`, not an error — measured live 2026-09-16 on an
    account holding 2 positions: page 0 → `['GLD', 'IGV']`, pages 1, 2 and 5 → `[]`.

    That settles API-17 without settling API-05. The documented page size is 100 and this
    gateway build returns no `pageSize` field at all, so the boundary is unobservable here
    — but a loop that reads until a page comes back empty never needs to know the size.
    """
    from unittest.mock import patch

    pages = {0: [{"conid": 1}] * 100, 1: [{"conid": 2}] * 100, 2: [{"conid": 3}] * 7, 3: []}
    with patch.object(client, "get_positions", side_effect=lambda a, page=0: pages[page]) as gp:
        result = client.get_all_positions("U1234567")

    assert len(result) == 207
    # Pages 0, 1, 2 — and NOT 3. Page 2 is short, which already identifies it as the last;
    # the first version of this test expected a fourth call and contradicted
    # `test_get_all_positions_stops_on_a_short_page_without_an_extra_request` below.
    assert [c.kwargs["page"] for c in gp.call_args_list] == [0, 1, 2]


def test_get_all_positions_stops_on_a_short_page_without_an_extra_request(client):
    """A page shorter than the previous one is the last page, so there is no reason to spend
    another request confirming it. `/portfolio/{id}/positions` is rate-limited and the
    account this was measured on would otherwise pay a second call to learn nothing."""
    from unittest.mock import patch

    pages = {0: [{"conid": 1}] * 100, 1: [{"conid": 2}] * 3, 2: []}
    with patch.object(client, "get_positions", side_effect=lambda a, page=0: pages[page]) as gp:
        result = client.get_all_positions("U1234567")

    assert len(result) == 103
    assert gp.call_count == 2, "a short page is the last page — no confirming request"


def test_get_all_positions_tells_the_caller_when_it_hits_the_guard(client):
    """API-02 was 'a short answer announced only to a log file'. A runaway guard that
    silently truncates is the same defect, so hitting it raises rather than returning a
    quietly incomplete list — there is no envelope on this endpoint to carry a warning."""
    from unittest.mock import patch

    from ibkr_core_mcp.exceptions import IBKRAPIError

    with (
        patch.object(client, "get_positions", side_effect=lambda a, page=0: [{"conid": page}] * 100),
        pytest.raises(IBKRAPIError, match="max_pages"),
    ):
        client.get_all_positions("U1234567", max_pages=3)


def test_get_all_positions_handles_an_account_with_nothing(client):
    """The empty case must not loop and must not raise."""
    from unittest.mock import patch

    with patch.object(client, "get_positions", return_value=[]) as gp:
        assert client.get_all_positions("U1234567") == []
    assert gp.call_count == 1


# ---------------------------------------------------------------------------
# Docstrings that restate what the code computes (API-08, API-12)
# ---------------------------------------------------------------------------


def test_the_documented_chunk_table_matches_what_the_code_computes():
    """API-08. The table said `1h -> 246-calendar-day chunks`; the function returns 30.

    The 2026-09-15 live re-measurement of `_BARS_PER_CALENDAR_DAY` moved every intraday
    chunk width — 246 was the *old* 1h value, and it is still printed in the measurement
    table above the constant as the width that was asked for. The prose followed the
    correction nowhere.
    """
    import ast
    import inspect
    import re

    from ibkr_core_mcp.client import IBKRClient, _chunk_days_for_bar

    doc = inspect.getdoc(IBKRClient.get_market_history_paginated) or ""
    rows = re.findall(r"^\s*(\w+)\s*→\s*([\d,]+)-calendar-day chunks", doc, re.M)
    assert rows, "the chunk table is gone from the docstring; update or remove this guard"

    wrong = {
        bar: (int(claimed.replace(",", "")), _chunk_days_for_bar(bar))
        for bar, claimed in rows
        if int(claimed.replace(",", "")) != _chunk_days_for_bar(bar)
    }
    assert not wrong, f"documented chunk width vs computed, per bar: {wrong}"

    # Completeness, not just correctness. Checking only the rows that are present lets a
    # deleted row pass unnoticed — the table would still be internally consistent and
    # silently cover fewer bars, which is how it came to list four of fifteen.
    from ibkr_core_mcp.client import _BARS_PER_CALENDAR_DAY

    documented = {bar for bar, _ in rows}
    assert documented == set(_BARS_PER_CALENDAR_DAY), (
        f"the table documents {sorted(documented)}; the function supports {sorted(_BARS_PER_CALENDAR_DAY)}"
    )
    assert ast is not None  # keep the import meaningful if the parse above changes


def test_the_module_docstring_names_every_method_that_returns_a_model():
    """API-12. It said "Six endpoints return models", then named seven.

    Eight actually did: `get_all_positions` was added for API-17 and never reached the list.
    The docstring exists so the claim can be checked rather than believed (CLAUDE.md), which
    only works if something checks it — and on 2026-09-17 this guard was itself found not to,
    for any model added after it was written, because its model set was six hand-typed names.
    The set is derived from `models.py` now.
    """
    import ast
    import re

    from ibkr_core_mcp import client as client_mod

    source = pathlib.Path(client_mod.__file__).read_text()
    tree = ast.parse(source)
    module_doc = ast.get_docstring(tree) or ""

    # Derived from models.py, never hand-typed. The first version of this guard froze the
    # six models that existed when it was written, so the six methods added by the
    # 2026-09-17 tranche — Account, AuthStatus, Alert, Watchlist, CurrencyPair — were
    # invisible to it and the docstring went stale without a single test failing. A check
    # whose oracle is a hand-kept list stops checking the day the list stops being kept.
    models = response_model_names()
    assert len(models) >= 6, f"only {len(models)} response models found — the derivation is broken"
    returning = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and not node.name.startswith("_")
        and node.returns is not None
        and annotation_names_a_model(ast.unparse(node.returns), models)
    }
    assert returning, "no method returns a model any more; update or remove this guard"

    block = module_doc[module_doc.index("**Return types.**") :].split("\n\n")[0]
    named = {
        m for m in re.findall(r"`(\w+)`", block) if m in returning or m.startswith("get_") or m == "search_contract"
    }
    named -= models

    assert named == returning, (
        f"the module docstring names {sorted(named)}; the code returns models from {sorted(returning)}"
    )

    # The count was an English number word against a hand-written map from `Four` to
    # `Twenty`, and the map ran out at 23 on 2026-09-17 — the guard would then have failed
    # for every future tranche regardless of whether the docstring was right. A numeral
    # needs no map, and a map nobody maintains is the defect this file keeps finding.
    stated = re.search(r"\*\*Return types\.\*\*\s+(\d+) endpoints return models", module_doc)
    assert stated, "the docstring no longer states how many endpoints return models"
    assert int(stated.group(1)) == len(returning), (
        f"the docstring says {stated.group(1)} endpoints; {len(returning)} return models"
    )


# ---------------------------------------------------------------------------
# API-15 — a 200 whose body is not JSON must stay inside the package's hierarchy
# ---------------------------------------------------------------------------


def _non_json_200(body: str) -> MagicMock:
    """A 2xx response whose body will not decode — what `requests` really raises."""
    import requests

    resp = MagicMock()
    resp.status_code = 200
    resp.text = body
    resp.json.side_effect = requests.exceptions.JSONDecodeError("Expecting value", body, 0)
    return resp


@pytest.mark.parametrize(
    "body",
    [
        pytest.param("<html><body>Sign in to IBKR</body></html>", id="the gateway's HTML page"),
        pytest.param("", id="an empty 200"),
    ],
)
def test_a_200_that_is_not_json_raises_inside_the_package_hierarchy(client, body):
    """`exceptions.py` opens with "Every error raised by this package derives from
    `IBKRCoreError`". It did not: `with_retry` raises on any non-2xx, so `resp.json()` only
    ever sees a 2xx — but a 2xx is not a promise of JSON. The gateway serves an HTML page
    once its session lapses, and `requests.exceptions.JSONDecodeError` then escaped a
    caller's `except IBKRCoreError` with a message naming neither the endpoint nor what
    arrived (audit finding API-15, reproduced 2026-09-17).
    """
    from ibkr_core_mcp.exceptions import IBKRAPIError, IBKRCoreError

    with (
        patch.object(client._session, "get", return_value=_non_json_200(body)),
        pytest.raises(IBKRCoreError) as caught,
    ):
        client.get_auth_status()

    assert isinstance(caught.value, IBKRAPIError)
    assert caught.value.status_code == 200
    assert "/iserver/auth/status" in str(caught.value), "the message must name the endpoint"
    assert body[:40] in str(caught.value) or not body, "the message must show what arrived instead"


def test_every_client_request_helper_decodes_through_the_same_guard():
    """The guard is one function, not a habit repeated at six call sites.

    `_get`, `_post` and `_put` each decoded with a bare `resp.json()`, and so did the three
    methods that call `self._session.delete` directly — `cancel_order`, `delete_alert`,
    `delete_watchlist`. Six places to keep in step is the shape that produced API-10
    (`IBKR_AUTH_BROWSER` honoured at one construction site of three), so the decode lives in
    one place and this test fails if a seventh appears beside it rather than through it.
    """
    import ast

    from ibkr_core_mcp import client as client_mod

    tree = ast.parse(pathlib.Path(client_mod.__file__).read_text())
    bare: set[str] = set()
    for function in ast.walk(tree):
        if not isinstance(function, ast.FunctionDef):
            continue
        for node in ast.walk(function):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "json":
                bare.add(function.name)

    assert bare == {"ping", "_decode"}, (
        f"these functions decode a response outside `_decode`: {sorted(bare - {'ping', '_decode'})}. "
        "`ping` is the one exemption — a liveness probe with its own try/except that answers "
        "False rather than raising, so it has no error to put in the hierarchy."
    )


# ── API-R10: a 2xx error object is a rejection, not a bucket of rows ──────────


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(lambda c: c.get_futures(["ES"]), id="get_futures"),
        pytest.param(lambda c: c.get_stocks(["AAPL"]), id="get_stocks"),
        pytest.param(lambda c: c.get_currency_pairs("USD"), id="get_currency_pairs"),
        pytest.param(lambda c: c.get_positions_by_conid(265598), id="get_positions_by_conid"),
    ],
)
def test_a_keyed_list_endpoint_raises_on_an_error_object_rather_than_fabricating_rows(client, call):
    """Four methods flatten `{"KEY": [...], ...}` into one list, in four spellings.

    Three of them iterated whatever the object's values were, so a 2xx `{"error": "…"}` —
    the shape IBKR uses for a rejection — became the characters of the message, and
    `parse_many` was handed one-character rows: `get_futures` answered
    `["n", "o", " ", "b", "r", "i", "d", "g", "e"]` for `{"error": "no bridge"}`, with the
    message discarded (API-R10, 2026-09-17). The fourth returned `[]`, which is what
    "no positions" looks like. An error is an error: it is raised, with IBKR's words.
    """
    from ibkr_core_mcp.exceptions import IBKRAPIError

    with (
        patch.object(client, "_get", return_value={"error": "no bridge"}),
        pytest.raises(IBKRAPIError, match="no bridge"),
    ):
        call(client)


def test_an_empty_keyed_object_is_simply_no_rows(client):
    """The counter-case: `{"XYZ": []}` and `{}` are legitimate empty answers, not errors."""
    with patch.object(client, "_get", return_value={"XYZ": []}):
        assert client.get_futures(["XYZ"]) == []
    with patch.object(client, "_get", return_value={}):
        assert client.get_stocks(["XYZ"]) == []


# ---------------------------------------------------------------------------
# place_bracket_and_confirm — one request, one Gate 1, one Gate 2, every reply
# answered (claudia_ui gap #36, Phase 1 Task 1.2)
# ---------------------------------------------------------------------------

_RID_1 = "11111111-1111-4111-8111-111111111111"
_RID_2 = "22222222-2222-4222-8222-222222222222"


def _bracket_pair() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    parent = {
        "conid": 649180671,
        "cOID": "CLAUDIA-1",
        "ticker": "ES",
        "side": "SELL",
        "quantity": 1,
        "orderType": "LMT",
        "price": 7725.0,
        "tif": "GTC",
        "_companyName": "ESU6 · SEP26",
        "_multiplier": 50,
    }
    child = {
        "conid": 649180671,
        "parentId": "CLAUDIA-1",
        "ticker": "ES",
        "side": "BUY",
        "quantity": 1,
        "orderType": "LMT",
        "price": 7700.0,
        "tif": "GTC",
    }
    return parent, [child]


def test_place_bracket_posts_one_array_carrying_the_link_and_no_display_keys(client):
    """One request, not two: the pair is atomic at IBKR, with no window in which the child
    is live alone."""
    parent, children = _bracket_pair()
    with (
        _patch("ibkr_core_mcp.client.require_touch_id"),
        _patch("ibkr_core_mcp.client.confirm_bracket_dialog"),
        _patch.object(client._session, "post") as mock_post,
    ):
        mock_post.return_value = _make_ok_response([{"order_id": "1"}, {"order_id": "2"}])
        client.place_bracket_and_confirm("U1234567", parent, children)
    mock_post.assert_called_once()
    assert mock_post.call_args[0][0] == f"{client._base}/iserver/account/U1234567/orders"
    body = mock_post.call_args.kwargs["json"]
    assert [o.get("cOID") for o in body["orders"]] == ["CLAUDIA-1", None]
    assert [o.get("parentId") for o in body["orders"]] == [None, "CLAUDIA-1"]
    assert all(not k.startswith("_") for o in body["orders"] for k in o), "display-only keys reached IBKR"


def test_place_bracket_runs_touch_id_once_then_the_bracket_dialog_then_posts(client):
    """D4: one Touch ID and ONE Gate 2 for the pair. Two dialogs would permit the parent to
    go with the child declined — the state a bracket exists to prevent."""
    parent, children = _bracket_pair()
    seq: list[str] = []
    with (
        _patch("ibkr_core_mcp.client.require_touch_id", side_effect=lambda r: seq.append("touch")),
        _patch("ibkr_core_mcp.client.confirm_bracket_dialog", side_effect=lambda *a: seq.append("dialog")),
        _patch("ibkr_core_mcp.client.confirm_order_dialog", side_effect=lambda *a: seq.append("SINGLE-DIALOG")),
        _patch.object(client._session, "post") as mock_post,
    ):

        def _record_post(*_a: Any, **_k: Any) -> Any:
            seq.append("post")
            return _make_ok_response([{"order_id": "1"}])

        mock_post.side_effect = _record_post
        client.place_bracket_and_confirm("U1234567", parent, children)
    assert seq == ["touch", "dialog", "post"]


def test_place_bracket_resolves_a_reply_that_arrives_on_the_SECOND_ticket(client):
    """THE defect review item 1 names (2026-09-08).

    The reply array's indices correspond to the indices of the tickets in the submission.
    `while response and "id" in response[0]` — correct for one ticket — inspects the parent
    only, so a precaution raised against the CHILD is never shown, never answered, and the
    child is silently dropped while the parent goes live alone: a resting position with no
    exit, which is the one outcome a bracket exists to prevent.
    """
    parent, children = _bracket_pair()
    with (
        _patch("ibkr_core_mcp.client.require_touch_id"),
        _patch("ibkr_core_mcp.client.confirm_bracket_dialog"),
        _patch("ibkr_core_mcp.client.confirm_reply_dialog") as mock_reply_dlg,
        _patch.object(client._session, "post") as mock_post,
    ):
        mock_post.side_effect = [
            _make_ok_response([{"order_id": "1"}, {"id": _RID_2, "message": ["Child precaution."]}]),
            _make_ok_response([{"order_id": "2", "order_status": "PreSubmitted"}]),
        ]
        result = client.place_bracket_and_confirm("U1234567", parent, children)
    mock_reply_dlg.assert_called_once()
    assert mock_reply_dlg.call_args[0][0] == _RID_2
    assert {e.get("order_id") for e in result} == {"1", "2"}


def test_place_bracket_keeps_a_terminal_leg_while_another_leg_still_replies(client):
    """The plan's loop replaces the whole response with the reply's response, which DROPS the
    parent's terminal entry — and the read-back needs its order id to confirm the leg."""
    parent, children = _bracket_pair()
    with (
        _patch("ibkr_core_mcp.client.require_touch_id"),
        _patch("ibkr_core_mcp.client.confirm_bracket_dialog"),
        _patch("ibkr_core_mcp.client.confirm_reply_dialog"),
        _patch.object(client._session, "post") as mock_post,
    ):
        mock_post.side_effect = [
            _make_ok_response([{"order_id": "PARENT-1"}, {"id": _RID_2, "message": ["Child precaution."]}]),
            # A per-ticket reply response: it says nothing about the parent.
            _make_ok_response([{"order_id": "CHILD-2", "order_status": "PreSubmitted"}]),
        ]
        result = client.place_bracket_and_confirm("U1234567", parent, children)
    assert {e.get("order_id") for e in result} == {"PARENT-1", "CHILD-2"}


def test_place_bracket_does_not_duplicate_when_a_reply_returns_the_whole_array(client):
    """The other plausible shape (M6 is unmeasured): the reply's response repeats every
    ticket. The terminal set must not then carry the parent twice."""
    parent, children = _bracket_pair()
    with (
        _patch("ibkr_core_mcp.client.require_touch_id"),
        _patch("ibkr_core_mcp.client.confirm_bracket_dialog"),
        _patch("ibkr_core_mcp.client.confirm_reply_dialog"),
        _patch.object(client._session, "post") as mock_post,
    ):
        mock_post.side_effect = [
            _make_ok_response([{"order_id": "PARENT-1"}, {"id": _RID_2, "message": ["Child precaution."]}]),
            _make_ok_response([{"order_id": "PARENT-1"}, {"order_id": "CHILD-2"}]),
        ]
        result = client.place_bracket_and_confirm("U1234567", parent, children)
    assert [e.get("order_id") for e in result] == ["PARENT-1", "CHILD-2"]


def test_place_bracket_answers_every_pending_reply_in_index_order_back_to_back(client):
    """IBKR 503s a reply left pending while other requests are made, so the chain runs
    back-to-back; index order is the order the human sees the legs in."""
    parent, children = _bracket_pair()
    with (
        _patch("ibkr_core_mcp.client.require_touch_id"),
        _patch("ibkr_core_mcp.client.confirm_bracket_dialog"),
        _patch("ibkr_core_mcp.client.confirm_reply_dialog") as mock_reply_dlg,
        _patch.object(client._session, "post") as mock_post,
    ):
        mock_post.side_effect = [
            _make_ok_response(
                [{"id": _RID_1, "message": ["Parent precaution."]}, {"id": _RID_2, "message": ["Child."]}]
            ),
            _make_ok_response([{"order_id": "PARENT-1"}]),
            _make_ok_response([{"order_id": "CHILD-2"}]),
        ]
        result = client.place_bracket_and_confirm("U1234567", parent, children)
    assert [c[0][0] for c in mock_reply_dlg.call_args_list] == [_RID_1, _RID_2]
    posted = [c[0][0] for c in mock_post.call_args_list]
    assert posted[1] == f"{client._base}/iserver/reply/{_RID_1}"
    assert posted[2] == f"{client._base}/iserver/reply/{_RID_2}"
    assert {e.get("order_id") for e in result} == {"PARENT-1", "CHILD-2"}


def test_place_bracket_refuses_a_reply_id_it_has_already_answered(client):
    """A precaution re-sent after it was confirmed is a loop, not a chain. Each round needs a
    human dialog, so this would otherwise prompt forever."""
    parent, children = _bracket_pair()
    with (
        _patch("ibkr_core_mcp.client.require_touch_id"),
        _patch("ibkr_core_mcp.client.confirm_bracket_dialog"),
        _patch("ibkr_core_mcp.client.confirm_reply_dialog"),
        _patch.object(client._session, "post") as mock_post,
    ):
        mock_post.side_effect = itertools.repeat(
            _make_ok_response([{"id": _RID_1, "message": ["Same precaution, again."]}])
        )
        with pytest.raises(IBKRAPIError, match="already"):
            client.place_bracket_and_confirm("U1234567", parent, children)


def test_place_bracket_gate_1_is_bound_to_every_leg_not_just_the_parent(client):
    """One Gate 1 covers the whole transaction, so the scope must hash the whole ticket
    ARRAY. Bound to the parent alone, a child could be altered after Touch ID and still ride
    the authorization (the defect SEC-07 fixed for the account, pointed at the child)."""
    parent, children = _bracket_pair()
    altered = [dict(children[0], price=1.0)]
    scopes: list[str] = []

    def _capture(reason, scope, label, *a, **k):
        scopes.append(scope)
        from ibkr_core_mcp.human_auth import OrderWriteAuthorization

        return OrderWriteAuthorization(scope, label, __import__("time").monotonic(), 300.0)

    for kids in (children, altered):
        with (
            _patch("ibkr_core_mcp.client._authorize_order_write", side_effect=_capture),
            _patch("ibkr_core_mcp.client.confirm_bracket_dialog"),
            _patch.object(client._session, "post") as mock_post,
        ):
            mock_post.return_value = _make_ok_response([{"order_id": "1"}])
            client.place_bracket_and_confirm("U1234567", parent, kids)
    assert scopes[0] != scopes[1], "the child's price is outside the authorization's scope"


def test_place_bracket_refuses_an_unlinked_child_before_any_gate(client):
    """Two unlinked tickets are two INDEPENDENT live orders; the opposite-side one can open a
    position rather than close one. Refused before Touch ID — nothing to authorise."""
    parent, _ = _bracket_pair()
    with (
        _patch("ibkr_core_mcp.client.require_touch_id") as mock_tid,
        _patch("ibkr_core_mcp.client.confirm_bracket_dialog") as mock_dlg,
        _patch.object(client._session, "post") as mock_post,
        pytest.raises(ValueError),
    ):
        client.place_bracket_and_confirm("U1234567", parent, [{"side": "BUY", "quantity": 1}])
    mock_tid.assert_not_called()
    mock_dlg.assert_not_called()
    mock_post.assert_not_called()


def test_place_bracket_declining_a_reply_tells_ibkr_and_raises(client):
    """Same decline semantics as the single-order chain: IBKR is told {"confirmed": false}
    before the raise, rather than left with the reply pending."""
    parent, children = _bracket_pair()
    with (
        _patch("ibkr_core_mcp.client.require_touch_id"),
        _patch("ibkr_core_mcp.client.confirm_bracket_dialog"),
        _patch("ibkr_core_mcp.client.confirm_reply_dialog", side_effect=HumanAuthError("no")),
        _patch.object(client._session, "post") as mock_post,
    ):
        mock_post.side_effect = [
            _make_ok_response([{"order_id": "1"}, {"id": _RID_2, "message": ["Child precaution."]}]),
            _make_ok_response({}),
        ]
        with pytest.raises(HumanAuthError):
            client.place_bracket_and_confirm("U1234567", parent, children)
    assert mock_post.call_args_list[-1].kwargs.get("json") == {"confirmed": False}


def test_place_bracket_logs_every_reply_when_a_reply_log_is_given(client):
    """gap #38: a waved-through precaution must leave a trace. The bracket needs it doubly —
    its chain is per ticket."""
    parent, children = _bracket_pair()
    reply_log: list[dict[str, Any]] = []
    with (
        _patch("ibkr_core_mcp.client.require_touch_id"),
        _patch("ibkr_core_mcp.client.confirm_bracket_dialog"),
        _patch("ibkr_core_mcp.client.confirm_reply_dialog"),
        _patch.object(client._session, "post") as mock_post,
    ):
        mock_post.side_effect = [
            _make_ok_response([{"id": _RID_1, "message": ["Parent."]}, {"id": _RID_2, "message": ["Child."]}]),
            _make_ok_response([{"order_id": "PARENT-1"}]),
            _make_ok_response([{"order_id": "CHILD-2"}]),
        ]
        client.place_bracket_and_confirm("U1234567", parent, children, reply_log=reply_log)
    assert [r["reply_id"] for r in reply_log] == [_RID_1, _RID_2]
    assert all(r["confirmed"] for r in reply_log)


def test_place_bracket_keeps_ibkrs_words_when_it_refuses_the_bracket(client):
    """IBKR's documented Alternate Response Object is a bare OBJECT, not an array.

    Read as a list it becomes `[]` — an order IBKR refused for a stated reason, reported to
    the caller as an empty response with IBKR's own words discarded. That was live on the
    single-order path until 2026-09-16; the bracket path must not reintroduce it.
    """
    parent, children = _bracket_pair()
    with (
        _patch("ibkr_core_mcp.client.require_touch_id"),
        _patch("ibkr_core_mcp.client.confirm_bracket_dialog"),
        _patch.object(client._session, "post") as mock_post,
    ):
        mock_post.return_value = _make_ok_response(
            {"error": "We cannot accept an order at the limit price you selected."}
        )
        result = client.place_bracket_and_confirm("U1234567", parent, children)
    assert result == [{"error": "We cannot accept an order at the limit price you selected."}]


def test_place_bracket_refuses_a_child_on_another_contract_before_touch_id(client):
    """A mismatched contract is refused with the other structural rules, BEFORE Gate 1.

    It used to be caught only by `confirm_bracket_dialog`, which runs after Touch ID — so
    the human was fingerprinted for a bracket that was then refused. The dialog keeps its own
    copy of the check as defence in depth (it is public API), but nothing reaches it here.
    """
    parent, children = _bracket_pair()
    with (
        _patch("ibkr_core_mcp.client.require_touch_id") as mock_tid,
        _patch("ibkr_core_mcp.client.confirm_bracket_dialog") as mock_dlg,
        _patch.object(client._session, "post") as mock_post,
        pytest.raises(ValueError, match="same contract"),
    ):
        client.place_bracket_and_confirm("U1234567", parent, [dict(children[0], conid=999999999)])
    mock_tid.assert_not_called()
    mock_dlg.assert_not_called()
    mock_post.assert_not_called()


# --- cancel_order fetches its own dialog detail when the caller supplies none -------------
# User-flagged 2026-09-21 after a probe script reproduced it live: the Gate 2 cancel dialog
# rendered an order id and an account number and nothing else. An order id is not something
# a human can verify against the order they mean, and a cancel cannot be undone.


def test_cancel_without_details_FETCHES_them_so_the_dialog_is_never_an_opaque_id(client):
    """The fix. The caller passes nothing; the dialog still receives real order detail."""
    status = {
        "symbol": "AAPL",
        "side": "S",
        "total_size": "10.0",
        "order_type": "LIMIT",
        "limit_price": "150.00",
        "tif": "GTC",
        "company_name": "APPLE INC",
        "currency": "USD",
        "sec_type": "STK",
        "order_description_with_contract": "Sell 10 AAPL Limit 150.00, GTC",
    }
    seen = {}
    with (
        _patch.object(client, "get_order_status", return_value=status),
        _patch("ibkr_core_mcp.client.require_touch_id"),
        _patch(
            "ibkr_core_mcp.client.confirm_cancel_dialog",
            side_effect=lambda o_id, a, order=None: seen.update({"det": order}),
        ),
        _patch.object(client._session, "delete") as mock_del,
    ):
        mock_del.return_value = _make_ok_response({"msg": "Request was submitted"})
        client.cancel_order("U1234567", "9876543210")
    det = seen["det"]
    assert det["ticker"] == "AAPL"
    assert det["side"] == "SELL"  # IBKR's 'S' mapped to a word a human reads
    assert det["price"] == "150.00"
    assert det["_current_description"] == "Sell 10 AAPL Limit 150.00, GTC"


def test_cancel_detail_fetch_marks_a_FUTURE_multiplier_unknown(client):
    """An order-status read never carries the contract multiplier, and price x quantity on a
    future is the notional divided by it — so the dialog must be told to refuse the number."""
    status = {
        "symbol": "ES",
        "side": "B",
        "total_size": "1.0",
        "order_type": "LIMIT",
        "limit_price": "7300.00",
        "tif": "DAY",
        "sec_type": "FUT",
    }
    seen = {}
    with (
        _patch.object(client, "get_order_status", return_value=status),
        _patch("ibkr_core_mcp.client.require_touch_id"),
        _patch(
            "ibkr_core_mcp.client.confirm_cancel_dialog",
            side_effect=lambda o_id, a, order=None: seen.update({"det": order}),
        ),
        _patch.object(client._session, "delete") as mock_del,
    ):
        mock_del.return_value = _make_ok_response({"msg": "Request was submitted"})
        client.cancel_order("U1234567", "9876543210")
    assert seen["det"]["_multiplier_unknown"] is True


def test_a_failed_detail_read_does_NOT_block_the_cancel(client):
    """Display is not permission. `/iserver/account/order/status` is rate-limited — measured
    HTTP 503 live on 2026-09-21 — and a cancel must not become impossible because a display
    read failed. The dialog names the gap instead (see test_order_confirm)."""
    seen = {}
    with (
        _patch.object(client, "get_order_status", side_effect=RuntimeError("HTTP 503")),
        _patch("ibkr_core_mcp.client.require_touch_id"),
        _patch(
            "ibkr_core_mcp.client.confirm_cancel_dialog",
            side_effect=lambda o_id, a, order=None: seen.update({"det": order}),
        ),
        _patch.object(client._session, "delete") as mock_del,
    ):
        mock_del.return_value = _make_ok_response({"msg": "Request was submitted"})
        client.cancel_order("U1234567", "9876543210")
    assert seen["det"] is None
    mock_del.assert_called_once()


def test_caller_supplied_details_are_NOT_overwritten_by_a_fetch(client):
    """claudia_ui already reads the order before Touch ID and passes richer detail than a
    status read gives. The fetch is a fallback, never a second source of truth."""
    mine = {"ticker": "GLD", "side": "SELL", "quantity": 1, "_multiplier": 50}
    seen = {}
    with (
        _patch.object(client, "get_order_status", side_effect=AssertionError("must not fetch")),
        _patch("ibkr_core_mcp.client.require_touch_id"),
        _patch(
            "ibkr_core_mcp.client.confirm_cancel_dialog",
            side_effect=lambda o_id, a, order=None: seen.update({"det": order}),
        ),
        _patch.object(client._session, "delete") as mock_del,
    ):
        mock_del.return_value = _make_ok_response({"msg": "Request was submitted"})
        client.cancel_order("U1234567", "9876543210", mine)
    assert seen["det"] is mine


# --- H1: the child is NEVER larger than the parent ----------------------------------------
# User hard rule, 2026-09-21: "Obviously your child can NEVER be larger than the parent !!
# hard rule !!" Enforced here, with the other structural rules, so a violating bracket is
# refused BEFORE Touch ID and `get_bracket_preview` inherits the check by construction.
#
# Why it belongs in code at all, when the child's quantity is DERIVED from the parent's: the
# derivation lives in claudia_ui, and this is public API. The same reasoning as the link and
# contract checks — a rule that only holds because every caller remembers is not enforced.


def test_place_bracket_refuses_a_child_LARGER_than_the_parent_before_touch_id(client):
    """The hard rule. A child of 2 against a parent of 1 would, once released, close 1 and
    OPEN 1 in the opposite direction — the exact harm the never-split rule exists to prevent,
    reached through quantity instead of through an unlinked ticket."""
    parent, children = _bracket_pair()
    with (
        _patch("ibkr_core_mcp.client.require_touch_id") as mock_tid,
        _patch("ibkr_core_mcp.client.confirm_bracket_dialog") as mock_dlg,
        _patch.object(client._session, "post") as mock_post,
        pytest.raises(ValueError, match="larger than the parent"),
    ):
        client.place_bracket_and_confirm("U1234567", parent, [dict(children[0], quantity=2)])
    mock_tid.assert_not_called()
    mock_dlg.assert_not_called()
    mock_post.assert_not_called()


def test_bracket_preview_refuses_a_child_larger_than_the_parent_too(client):
    """The preview runs the same validation, so a violating pair cannot be priced either —
    and the whatif would have priced it happily, being blind to the child (measured
    2026-09-20)."""
    parent, children = _bracket_pair()
    with (
        _patch.object(client._session, "post") as mock_post,
        pytest.raises(ValueError, match="larger than the parent"),
    ):
        client.get_bracket_preview("U1234567", parent, [dict(children[0], quantity=99)])
    mock_post.assert_not_called()


def test_a_child_EQUAL_to_the_parent_is_accepted(client):
    """The discriminating half, and the normal case: IBKR's own definition of a profit taker
    is 'the same order quantity as the parent'. A rule that refused this would refuse every
    real bracket."""
    parent, children = _bracket_pair()
    tickets = client._bracket_tickets(parent, [dict(children[0], quantity=1)])
    assert [t["quantity"] for t in tickets] == [1, 1]


def test_a_child_SMALLER_than_the_parent_is_accepted(client):
    """Scaling out is legitimate — take profit on part of the position. H1 is a ceiling, not
    an equality."""
    parent, children = _bracket_pair()
    tickets = client._bracket_tickets(dict(parent, quantity=5), [dict(children[0], quantity=2)])
    assert [t["quantity"] for t in tickets] == [5, 2]


def test_a_child_with_NO_quantity_is_accepted_because_it_is_derived(client):
    """Only a STATED violation is refused — the same convention as the conid check. A child
    carrying no quantity is normal; it is derived from the parent."""
    parent, children = _bracket_pair()
    kid = {k: v for k, v in children[0].items() if k != "quantity"}
    tickets = client._bracket_tickets(parent, [kid])
    assert "quantity" not in tickets[1]


def test_an_unparseable_quantity_does_not_silently_pass_the_H1_check(client):
    """A quantity that cannot be compared must not be treated as compliant. Refuse rather
    than guess — the alternative is a hard rule that any malformed value walks through."""
    parent, children = _bracket_pair()
    with pytest.raises(ValueError, match="quantity"):
        client._bracket_tickets(parent, [dict(children[0], quantity="two")])


# --- pair_bracket_response: which entry belongs to which ticket ---------------------------
# Three gaps found 2026-09-21, all live: nothing confirmed IBKR had ATTACHED the child,
# nothing asserted one entry per ticket, and the response order is not the submission order.

_PARENT_TICKET = {"cOID": "CLAUDIA-1", "conid": 1, "side": "SELL", "quantity": 1}
_CHILD_TICKET = {"parentId": "CLAUDIA-1", "conid": 1, "side": "BUY", "quantity": 1}
_PARENT_ENTRY = {"order_id": "900", "order_status": "Submitted", "local_order_id": "CLAUDIA-1"}
_CHILD_ENTRY = {"order_id": "901", "order_status": "PreSubmitted", "parent_order_id": "900"}


def test_pairing_matches_by_identifier_when_the_response_is_REVERSED():
    """The live shape. Both sends on 2026-09-21 returned [child, parent] for a [parent, child]
    submission, so index pairing would swap the legs — reading the parent's status off the
    child and vice versa."""
    from ibkr_core_mcp.client import pair_bracket_response

    paired = pair_bracket_response([_PARENT_TICKET, _CHILD_TICKET], [_CHILD_ENTRY, _PARENT_ENTRY])
    assert paired.ok, paired.problems
    assert paired.parent is _PARENT_ENTRY
    assert paired.children == (_CHILD_ENTRY,)


def test_pairing_reports_a_child_attached_to_SOMETHING_ELSE():
    """The catastrophic shape, and the one nothing checked: IBKR accepts the array but the
    child is not attached to our parent. It is then a live independent opposite-side order."""
    from ibkr_core_mcp.client import pair_bracket_response

    stray = dict(_CHILD_ENTRY, parent_order_id="777")
    paired = pair_bracket_response([_PARENT_TICKET, _CHILD_TICKET], [_PARENT_ENTRY, stray])
    assert not paired.ok
    assert any("not this parent" in p for p in paired.problems), paired.problems
    assert paired.children == ()


def test_pairing_reports_a_DROPPED_leg():
    """One entry per ticket was documented and never asserted."""
    from ibkr_core_mcp.client import pair_bracket_response

    paired = pair_bracket_response([_PARENT_TICKET, _CHILD_TICKET], [_PARENT_ENTRY])
    assert not paired.ok
    assert any("child ticket(s) submitted, 0 linked back" in p for p in paired.problems), paired.problems


def test_pairing_keeps_IBKRS_WORDS_for_a_refused_leg_the_M9_shape():
    """Measured live: a non-tick child came back as order_id '-1', order_status 'Failed', with
    the reason in `text` and NO parent_order_id — while the parent landed anyway. The pairing
    must surface that sentence, not drop the entry."""
    from ibkr_core_mcp.client import pair_bracket_response

    failed = {
        "order_id": "-1",
        "order_status": "Failed",
        "text": "The price 7330.10 does not conform to the minimum price variation of 0.25.",
    }
    inactive_parent = dict(_PARENT_ENTRY, order_status="Inactive")
    paired = pair_bracket_response([_PARENT_TICKET, _CHILD_TICKET], [failed, inactive_parent])
    assert not paired.ok
    assert paired.parent is inactive_parent
    assert paired.unmatched == (failed,)
    assert any("minimum price variation" in p for p in paired.problems), paired.problems


def test_pairing_reports_a_missing_parent_rather_than_guessing_one():
    from ibkr_core_mcp.client import pair_bracket_response

    paired = pair_bracket_response([_PARENT_TICKET, _CHILD_TICKET], [_CHILD_ENTRY])
    assert paired.parent is None
    assert any("cOID" in p for p in paired.problems), paired.problems


def test_pairing_does_NOT_claim_a_per_child_mapping():
    """IBKR echoes no identifier of ours on a child, so two children cannot be told apart in
    the response. `children` is a SET of entries, never a per-ticket list — the type itself
    has to refuse to imply otherwise."""
    from ibkr_core_mcp.client import pair_bracket_response

    kid2 = {"order_id": "902", "order_status": "PreSubmitted", "parent_order_id": "900"}
    paired = pair_bracket_response(
        [_PARENT_TICKET, _CHILD_TICKET, dict(_CHILD_TICKET)],
        [_PARENT_ENTRY, _CHILD_ENTRY, kid2],
    )
    assert paired.ok, paired.problems
    assert {id(c) for c in paired.children} == {id(_CHILD_ENTRY), id(kid2)}


def test_place_bracket_LOGS_a_response_that_does_not_pair(client, caplog):
    """The check must not be opt-in. A caller that never calls `pair_bracket_response` still
    leaves a record — and the bracket is NOT raised over, because the orders are already
    placed and throwing would destroy the only account of what happened."""
    import logging

    parent, children = _bracket_pair()
    stray = {"order_id": "901", "order_status": "PreSubmitted", "parent_order_id": "999"}
    landed = {"order_id": "900", "order_status": "Submitted", "local_order_id": "CLAUDIA-1"}
    with (
        _patch("ibkr_core_mcp.client.require_touch_id"),
        _patch("ibkr_core_mcp.client.confirm_bracket_dialog"),
        _patch.object(client._session, "post") as mock_post,
        caplog.at_level(logging.ERROR, logger="ibkr_core_mcp.client"),
    ):
        mock_post.return_value = _make_ok_response([landed, stray])
        result = client.place_bracket_and_confirm("U1234567", parent, children)
    assert result == [landed, stray], "IBKR's response must survive the check intact"
    assert any("not this parent" in r.getMessage() for r in caplog.records), caplog.text
