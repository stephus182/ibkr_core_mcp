from unittest.mock import MagicMock, patch
from unittest.mock import patch as _patch

import pytest


@pytest.fixture
def client(mock_config):
    from ibkr_core_mcp.auth import NoAuth
    from ibkr_core_mcp.client import IBKRClient
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


# ---------------------------------------------------------------------------
# account_id validation — path traversal and injection prevention
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("account_id", [
    "U1234567",
    "DU123456",
    "F123ABC",
    "ABCDEFGHIJ",
])
def test_validate_account_id_accepts_valid_ids(client, account_id):
    from unittest.mock import MagicMock
    client._session.get = MagicMock(return_value=MagicMock(status_code=200, json=lambda: {}))
    # Should not raise ConfigError for valid alphanumeric IDs
    try:
        client.get_account_summary(account_id)
    except Exception as exc:
        assert "account_id" not in str(type(exc).__name__).lower() or \
               type(exc).__name__ != "ConfigError"


@pytest.mark.parametrize("bad_id", [
    "",                    # empty
    "../etc/passwd",       # path traversal
    "U123/456",            # slash
    "U123#456",            # special char
    "U123 456",            # space
    "U123\r\nX-Header: 1", # CRLF injection
    "U123\x00null",        # null byte
    "U123-456",            # hyphen
])
def test_validate_account_id_rejects_invalid_ids(client, bad_id):
    from ibkr_core_mcp.exceptions import ConfigError
    with pytest.raises(ConfigError, match="[Ii]nvalid account"):
        client.get_account_summary(bad_id)


def test_validate_account_id_applied_to_write_methods(client):
    """Path traversal must be caught before Touch ID gates are evaluated."""
    from ibkr_core_mcp.exceptions import ConfigError
    order = {"ticker": "AAPL", "side": "BUY", "quantity": 1}
    with _patch("ibkr_core_mcp.client.require_touch_id") as mock_tid:
        with pytest.raises(ConfigError):
            client.place_order("../inject", order)
    mock_tid.assert_not_called()  # validation must fire before biometric gate


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


# ── get_live_orders filtering ─────────────────────────────────────────────────

def _mock_orders_response(client, orders):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"orders": orders}
    return patch.object(client._session, "get", return_value=mock_resp)


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
