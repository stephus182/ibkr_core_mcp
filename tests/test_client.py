from unittest.mock import MagicMock, patch
from unittest.mock import patch as _patch

import pytest


@pytest.fixture
def client(mock_config):
    from ibkr_core_mcp.auth import NoAuth
    from ibkr_core_mcp.client import IBKRClient
    c = IBKRClient(mock_config, auth=NoAuth())
    # Pre-mark accounts as initialized so existing order/auth tests below don't need
    # to also mock the /iserver/accounts prerequisite call. Tests for
    # _ensure_accounts_initialized() itself reset this flag explicitly.
    c._accounts_initialized = True
    return c


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
    with patch.object(client._session, "get") as mock_get:
        mock_get.return_value = _make_ok_response({"orders": []})
        client.get_live_orders()
    first_call_url = mock_get.call_args_list[0][0][0]
    assert first_call_url == f"{client._base}/iserver/accounts"
    assert client._accounts_initialized is True


def test_place_order_initializes_accounts_before_touch_id(client):
    client._accounts_initialized = False
    order = {"ticker": "AAPL", "side": "BUY", "quantity": 100}
    with _patch("ibkr_core_mcp.client.require_touch_id") as mock_tid, \
         _patch("ibkr_core_mcp.client.confirm_order_dialog"), \
         patch.object(client._session, "get") as mock_get, \
         _patch.object(client._session, "post") as mock_post:
        mock_get.return_value = _make_ok_response({"accounts": ["U1234567"]})
        mock_post.return_value = _make_ok_response([{"orderId": "1"}])
        client.place_order("U1234567", order)
    mock_get.assert_called_once_with(f"{client._base}/iserver/accounts", params=None, timeout=30)
    mock_tid.assert_called_once()
    assert client._accounts_initialized is True


def test_get_order_preview_initializes_accounts(client):
    client._accounts_initialized = False
    order = {"ticker": "AAPL", "side": "BUY", "quantity": 100}
    with patch.object(client._session, "get") as mock_get, \
         _patch.object(client._session, "post") as mock_post:
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
    from ibkr_core_mcp.exceptions import ConfigError
    client._session.get = MagicMock(return_value=MagicMock(status_code=200, json=lambda: {}))
    # Valid IDs must not raise ConfigError — any other exception (e.g. from mock shape) is ignored
    try:
        client.get_account_summary(account_id)
    except ConfigError:
        pytest.fail(f"ConfigError raised for valid account_id {account_id!r}")


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


def test_get_currency_pairs_handles_dict_response(client):
    """IBKR /iserver/currency/pairs returns {"USD": [{symbol, conid, ccyPair}]}.

    Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#get-currency-pairs
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


# ── ping() retry behaviour (Fix #2 — IBKR first-call quirk) ─────────────────

def test_ping_retries_once_when_first_call_returns_unauthenticated(client):
    """ping() retries once when first call returns authenticated=false (IBKR quirk)."""
    responses = [
        MagicMock(status_code=200, json=MagicMock(return_value={"authenticated": False})),
        MagicMock(status_code=200, json=MagicMock(return_value={"authenticated": True})),
    ]
    with patch.object(client._session, "get", side_effect=responses), \
         patch.object(client, "tickle", return_value=True), \
         patch("ibkr_core_mcp.client.time.sleep"):
        result = client.ping()
    assert result is True


def test_ping_returns_false_when_both_attempts_unauthenticated(client):
    """ping() returns False if authenticated=false on both the first and second attempt."""
    not_authed = MagicMock(status_code=200, json=MagicMock(return_value={"authenticated": False}))
    with patch.object(client._session, "get", return_value=not_authed) as mock_get, \
         patch.object(client, "tickle", return_value=True), \
         patch("ibkr_core_mcp.client.time.sleep"):
        result = client.ping()
    assert result is False
    assert mock_get.call_count == 2, "ping() must attempt exactly twice when not authenticated"


def test_ping_calls_tickle_between_first_and_second_attempt(client):
    """ping() must call tickle() exactly once, between the two attempts."""
    responses = [
        MagicMock(status_code=200, json=MagicMock(return_value={"authenticated": False})),
        MagicMock(status_code=200, json=MagicMock(return_value={"authenticated": True})),
    ]
    with patch.object(client._session, "get", side_effect=responses), \
         patch.object(client, "tickle", return_value=True) as mock_tickle, \
         patch("ibkr_core_mcp.client.time.sleep"):
        client.ping()
    mock_tickle.assert_called_once()


def test_ping_returns_false_immediately_on_401_without_retry(client):
    """ping() must return False immediately on HTTP 401 — no retry, no tickle."""
    resp_401 = MagicMock(status_code=401)
    with patch.object(client._session, "get", return_value=resp_401) as mock_get, \
         patch.object(client, "tickle") as mock_tickle:
        result = client.ping()
    assert result is False
    assert mock_get.call_count == 1, "Must not retry on 401"
    mock_tickle.assert_not_called()
