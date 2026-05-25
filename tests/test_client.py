import pytest
from unittest.mock import MagicMock, patch, patch as _patch


@pytest.fixture
def client(mock_config):
    from ibkr_core_mcp.client import IBKRClient
    from ibkr_core_mcp.auth import NoAuth
    return IBKRClient(mock_config, auth=NoAuth())


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
        mock_resp.json.return_value = [
            {"conid": 265598, "symbol": "AAPL", "secType": "STK"}
        ]
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


# Integration tests — require live gateway
@pytest.mark.integration
def test_live_ping(mock_config):
    from ibkr_core_mcp.client import IBKRClient
    from ibkr_core_mcp.auth import BrowserCookieAuth
    client = IBKRClient(mock_config, auth=BrowserCookieAuth())
    assert client.ping() is True


@pytest.mark.integration
def test_live_search_aapl(mock_config):
    from ibkr_core_mcp.client import IBKRClient
    from ibkr_core_mcp.auth import BrowserCookieAuth
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
    with _patch("ibkr_core_mcp.client.require_touch_id", side_effect=lambda r: call_order.append("touch_id")) as mock_tid, \
         _patch("ibkr_core_mcp.client.confirm_order_dialog", side_effect=lambda o, a: call_order.append("dialog")) as mock_dlg, \
         _patch.object(client._session, "post") as mock_post:
        mock_post.return_value = _make_ok_response([{"orderId": "1"}])
        client.place_order("U1234567", order)
    assert call_order == ["touch_id", "dialog"]
    mock_tid.assert_called_once()
    mock_dlg.assert_called_once()
    mock_post.assert_called_once()


def test_place_order_aborts_if_touch_id_fails(client):
    from ibkr_core_mcp.exceptions import HumanAuthError
    order = {"ticker": "AAPL", "side": "BUY", "quantity": 100}
    with _patch("ibkr_core_mcp.client.require_touch_id", side_effect=HumanAuthError("denied")), \
         _patch.object(client._session, "post") as mock_post:
        with pytest.raises(HumanAuthError):
            client.place_order("U1234567", order)
    mock_post.assert_not_called()


def test_place_order_aborts_if_dialog_cancelled(client):
    from ibkr_core_mcp.exceptions import HumanAuthError
    order = {"ticker": "AAPL", "side": "BUY", "quantity": 100}
    with _patch("ibkr_core_mcp.client.require_touch_id"), \
         _patch("ibkr_core_mcp.client.confirm_order_dialog", side_effect=HumanAuthError("cancelled")), \
         _patch.object(client._session, "post") as mock_post:
        with pytest.raises(HumanAuthError):
            client.place_order("U1234567", order)
    mock_post.assert_not_called()


def test_modify_order_aborts_if_touch_id_fails(client):
    from ibkr_core_mcp.exceptions import HumanAuthError
    with _patch("ibkr_core_mcp.client.require_touch_id", side_effect=HumanAuthError("denied")), \
         _patch.object(client._session, "post") as mock_post:
        with pytest.raises(HumanAuthError):
            client.modify_order("U1234567", "ORD123", {"side": "SELL"})
    mock_post.assert_not_called()


def test_cancel_order_aborts_if_touch_id_fails(client):
    from ibkr_core_mcp.exceptions import HumanAuthError
    with _patch("ibkr_core_mcp.client.require_touch_id", side_effect=HumanAuthError("denied")), \
         _patch.object(client._session, "delete") as mock_del:
        with pytest.raises(HumanAuthError):
            client.cancel_order("U1234567", "ORD456")
    mock_del.assert_not_called()


def test_reply_order_aborts_if_touch_id_fails(client):
    from ibkr_core_mcp.exceptions import HumanAuthError
    with _patch("ibkr_core_mcp.client.require_touch_id", side_effect=HumanAuthError("denied")), \
         _patch.object(client._session, "post") as mock_post:
        with pytest.raises(HumanAuthError):
            client.reply_order("RPL789")
    mock_post.assert_not_called()


def test_modify_order_calls_both_gates(client):
    call_order = []
    with _patch("ibkr_core_mcp.client.require_touch_id", side_effect=lambda r: call_order.append("touch_id")), \
         _patch("ibkr_core_mcp.client.confirm_modify_dialog", side_effect=lambda o_id, o, a: call_order.append("dialog")), \
         _patch.object(client._session, "post") as mock_post:
        mock_post.return_value = _make_ok_response({"status": "modified"})
        client.modify_order("U1234567", "ORD123", {"side": "SELL"})
    assert call_order == ["touch_id", "dialog"]
    mock_post.assert_called_once()


def test_cancel_order_calls_both_gates(client):
    call_order = []
    with _patch("ibkr_core_mcp.client.require_touch_id", side_effect=lambda r: call_order.append("touch_id")), \
         _patch("ibkr_core_mcp.client.confirm_cancel_dialog", side_effect=lambda o_id, a: call_order.append("dialog")), \
         _patch.object(client._session, "delete") as mock_del:
        mock_del.return_value = _make_ok_response({"status": "cancelled"})
        client.cancel_order("U1234567", "ORD456")
    assert call_order == ["touch_id", "dialog"]
    mock_del.assert_called_once()


def test_reply_order_calls_both_gates(client):
    call_order = []
    with _patch("ibkr_core_mcp.client.require_touch_id", side_effect=lambda r: call_order.append("touch_id")), \
         _patch("ibkr_core_mcp.client.confirm_reply_dialog", side_effect=lambda r: call_order.append("dialog")), \
         _patch.object(client._session, "post") as mock_post:
        mock_post.return_value = _make_ok_response([{"status": "submitted"}])
        client.reply_order("RPL789")
    assert call_order == ["touch_id", "dialog"]
    mock_post.assert_called_once()


def test_modify_order_aborts_if_dialog_cancelled(client):
    from ibkr_core_mcp.exceptions import HumanAuthError
    with _patch("ibkr_core_mcp.client.require_touch_id"), \
         _patch("ibkr_core_mcp.client.confirm_modify_dialog", side_effect=HumanAuthError("cancelled")), \
         _patch.object(client._session, "post") as mock_post:
        with pytest.raises(HumanAuthError):
            client.modify_order("U1234567", "ORD123", {"side": "SELL"})
    mock_post.assert_not_called()


def test_cancel_order_aborts_if_dialog_cancelled(client):
    from ibkr_core_mcp.exceptions import HumanAuthError
    with _patch("ibkr_core_mcp.client.require_touch_id"), \
         _patch("ibkr_core_mcp.client.confirm_cancel_dialog", side_effect=HumanAuthError("cancelled")), \
         _patch.object(client._session, "delete") as mock_del:
        with pytest.raises(HumanAuthError):
            client.cancel_order("U1234567", "ORD456")
    mock_del.assert_not_called()


def test_reply_order_aborts_if_dialog_cancelled(client):
    from ibkr_core_mcp.exceptions import HumanAuthError
    with _patch("ibkr_core_mcp.client.require_touch_id"), \
         _patch("ibkr_core_mcp.client.confirm_reply_dialog", side_effect=HumanAuthError("cancelled")), \
         _patch.object(client._session, "post") as mock_post:
        with pytest.raises(HumanAuthError):
            client.reply_order("RPL789")
    mock_post.assert_not_called()


def test_get_order_preview_has_no_gate(client):
    """whatif endpoint is read-only — must NOT trigger Touch ID."""
    order = {"ticker": "AAPL", "side": "BUY", "quantity": 100}
    with _patch("ibkr_core_mcp.client.require_touch_id") as mock_tid, \
         _patch.object(client._session, "post") as mock_post:
        mock_post.return_value = _make_ok_response({"equity": 5000})
        client.get_order_preview("U1234567", order)
    mock_tid.assert_not_called()
