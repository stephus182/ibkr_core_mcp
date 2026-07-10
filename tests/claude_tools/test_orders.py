
import pytest

pytestmark = pytest.mark.orders

def test_execute_get_live_orders_filters_filled(toolkit):
    # The client-layer filtering is already tested in test_client.py;
    # this confirms the tool correctly labels an empty working set.
    toolkit._client.get_live_orders.return_value = []
    text, fig = toolkit.execute("get_live_orders", {})
    assert "No open orders" in text
    assert fig is None


def test_execute_get_live_orders_shows_working_orders(toolkit):
    toolkit._client.get_live_orders.return_value = [
        {"orderId": 1, "ticker": "AAPL", "side": "BUY",
         "totalSize": 100, "price": 185.0, "status": "Submitted"},
    ]
    text, fig = toolkit.execute("get_live_orders", {})
    assert "AAPL" in text
    assert "Submitted" in text
    assert fig is None


def test_preview_order_lmt_includes_price(toolkit):
    toolkit._client.get_accounts.return_value = [{"accountId": "U1234"}]
    toolkit._client.search_contract.return_value = [{"conid": 265598}]
    toolkit._client.get_order_preview.return_value = {
        "commission": "1.05",
        "equity": {"amount": 99000, "change": -18200},
        "initMarginChange": "500",
        "maintMarginChange": "300",
    }
    text, fig = toolkit.execute("preview_order", {
        "symbol": "AAPL", "action": "BUY", "quantity": 100,
        "order_type": "LMT", "limit_price": 182.50,
    })
    call_order = toolkit._client.get_order_preview.call_args[0][1]
    assert call_order["price"] == 182.50
    assert "Order Preview" in text


def test_preview_order_mkt_no_price(toolkit):
    toolkit._client.get_accounts.return_value = [{"accountId": "U1234"}]
    toolkit._client.search_contract.return_value = [{"conid": 265598}]
    toolkit._client.get_order_preview.return_value = {"commission": "0.00"}
    toolkit.execute("preview_order", {
        "symbol": "AAPL", "action": "BUY", "quantity": 10, "order_type": "MKT"
    })
    call_order = toolkit._client.get_order_preview.call_args[0][1]
    assert "price" not in call_order


def test_preview_order_stp_maps_stop_price_to_price(toolkit):
    """STP orders carry the trigger in `price` — CP API place-order spec:
    "For STP|TRAIL this is the stop price."
    Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#place-order"""
    toolkit._client.get_accounts.return_value = [{"accountId": "U1234"}]
    toolkit._client.search_contract.return_value = [{"conid": 265598}]
    toolkit._client.get_order_preview.return_value = {"commission": "1.00"}
    text, _ = toolkit.execute("preview_order", {
        "symbol": "AAPL", "action": "SELL", "quantity": 10,
        "order_type": "STP", "stop_price": 170.0,
    })
    call_order = toolkit._client.get_order_preview.call_args[0][1]
    assert call_order["price"] == 170.0
    assert "auxPrice" not in call_order
    assert "Order Preview" in text


def test_preview_order_stop_limit_maps_limit_to_price_and_stop_to_aux(toolkit):
    """STOP_LIMIT requires both: price = limit price, auxPrice = stop price.
    Spec: "You must specify both price and auxPrice for STOP_LIMIT|TRAILLMT orders."
    Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#place-order"""
    toolkit._client.get_accounts.return_value = [{"accountId": "U1234"}]
    toolkit._client.search_contract.return_value = [{"conid": 265598}]
    toolkit._client.get_order_preview.return_value = {"commission": "1.00"}
    toolkit.execute("preview_order", {
        "symbol": "AAPL", "action": "SELL", "quantity": 10,
        "order_type": "STOP_LIMIT", "limit_price": 168.0, "stop_price": 170.0,
    })
    call_order = toolkit._client.get_order_preview.call_args[0][1]
    assert call_order["price"] == 168.0
    assert call_order["auxPrice"] == 170.0


def test_preview_order_stp_without_stop_price_errors_before_network(toolkit):
    toolkit._client.get_accounts.return_value = [{"accountId": "U1234"}]
    toolkit._client.search_contract.return_value = [{"conid": 265598}]
    text, _ = toolkit.execute("preview_order", {
        "symbol": "AAPL", "action": "SELL", "quantity": 10, "order_type": "STP",
    })
    assert "stop_price" in text
    toolkit._client.get_order_preview.assert_not_called()


def test_preview_order_stop_limit_missing_either_price_errors(toolkit):
    toolkit._client.get_accounts.return_value = [{"accountId": "U1234"}]
    toolkit._client.search_contract.return_value = [{"conid": 265598}]
    text, _ = toolkit.execute("preview_order", {
        "symbol": "AAPL", "action": "SELL", "quantity": 10,
        "order_type": "STOP_LIMIT", "limit_price": 168.0,
    })
    assert "stop_price" in text
    text, _ = toolkit.execute("preview_order", {
        "symbol": "AAPL", "action": "SELL", "quantity": 10,
        "order_type": "STOP_LIMIT", "stop_price": 170.0,
    })
    assert "limit_price" in text
    toolkit._client.get_order_preview.assert_not_called()


def test_preview_order_lmt_without_limit_price_errors_before_network(toolkit):
    """price is 'Required for LMT' per the CP API spec — previously sent priceless
    and left IBKR to reject it with an unactionable 500."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U1234"}]
    toolkit._client.search_contract.return_value = [{"conid": 265598}]
    text, _ = toolkit.execute("preview_order", {
        "symbol": "AAPL", "action": "BUY", "quantity": 10, "order_type": "LMT",
    })
    assert "limit_price" in text
    toolkit._client.get_order_preview.assert_not_called()


def test_preview_order_rejects_types_the_tool_cannot_complete(toolkit):
    """TRAIL/TRAILLMT need trailingAmt/trailingType (not exposed by this tool);
    MOC/LOC are absent from the documented CP API order types. Admitting them
    reproduced the audit's 'whitelist admits what it can't complete' defect."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U1234"}]
    toolkit._client.search_contract.return_value = [{"conid": 265598}]
    for bad_type in ("TRAIL", "TRAILLMT", "MOC", "LOC"):
        text, _ = toolkit.execute("preview_order", {
            "symbol": "AAPL", "action": "BUY", "quantity": 10,
            "order_type": bad_type, "stop_price": 170.0, "limit_price": 168.0,
        })
        assert "Invalid order_type" in text, bad_type
    toolkit._client.get_order_preview.assert_not_called()


# ---------------------------------------------------------------------------
# _format_coverage — pure formatting helper for trade history summaries
# ---------------------------------------------------------------------------

def test_diagnose_orders_happy_path(toolkit):
    """Returns formatted order lines when orders list is non-empty.

    Uses the public client.get_orders_raw() — the handler must not reach into
    client._get (audit register item 11)."""
    toolkit._client.get_orders_raw.return_value = {"orders": [
        {"orderId": 99, "ticker": "AAPL", "side": "BUY",
         "totalSize": 10, "price": 182.5, "status": "Submitted",
         "clientId": "42", "orderRef": "ref1"}
    ]}
    text, fig = toolkit.execute("diagnose_orders", {})
    assert fig is None
    assert "orderId=99" in text
    assert "AAPL" in text
    assert "/iserver/account/orders" in text
    toolkit._client._get.assert_not_called()


def test_diagnose_orders_empty_list(toolkit):
    """Returns 'genuinely empty' message when orders list is []."""
    toolkit._client.get_orders_raw.return_value = {"orders": []}
    text, fig = toolkit.execute("diagnose_orders", {})
    assert fig is None
    assert "genuinely empty" in text.lower()


def test_diagnose_orders_unexpected_shape(toolkit):
    """Returns shape-error message when IBKR returns a non-list response."""
    toolkit._client.get_orders_raw.return_value = "bad_string"
    text, fig = toolkit.execute("diagnose_orders", {})
    assert fig is None
    assert "Unexpected response shape" in text


def test_diagnose_orders_shows_filtered_status(toolkit):
    """Filled orders are labelled [FILTERED by get_live_orders]."""
    toolkit._client.get_orders_raw.return_value = {"orders": [
        {"orderId": 1, "ticker": "TSLA", "side": "SELL",
         "totalSize": 5, "price": 200.0, "status": "Filled",
         "clientId": "1"}
    ]}
    text, fig = toolkit.execute("diagnose_orders", {})
    assert "FILTERED" in text


def test_execute_get_live_orders_labels_claudia_staged_via_order_ref(toolkit):
    """IBKR's real Live Orders field is order_ref (snake_case), not orderRef/cOID —
    2026-07-10 live finding: every order fell through to EXTERNAL because neither
    checked key ever matched a real response."""
    toolkit._client.get_live_orders.return_value = [
        {"orderId": 1, "ticker": "AAPL", "side": "BUY", "totalSize": 1,
         "price": 100.0, "status": "Submitted", "order_ref": "CLAUDIA-1783692527147"},
    ]
    text, fig = toolkit.execute("get_live_orders", {})
    assert "ClaudIA-staged" in text
    assert "EXTERNAL" not in text


def test_execute_get_live_orders_still_falls_back_to_external_without_order_ref(toolkit):
    """Regression guard: an order with no order_ref/orderRef/cOID and clientId=0 must
    still show as EXTERNAL — this is the correct behavior for genuinely external orders."""
    toolkit._client.get_live_orders.return_value = [
        {"orderId": 2, "ticker": "EEM", "side": "BUY", "totalSize": 1,
         "price": 50.0, "status": "Submitted", "clientId": 0},
    ]
    text, fig = toolkit.execute("get_live_orders", {})
    assert "EXTERNAL" in text


def test_diagnose_orders_labels_claudia_staged_via_order_ref(toolkit):
    """_diagnose_orders must use the same order_ref-first lookup as _get_live_orders —
    they were inconsistent before this fix (get_live_orders computed an origin label,
    diagnose_orders only showed raw clientId/ref with no origin at all)."""
    toolkit._client.get_orders_raw.return_value = {"orders": [
        {"orderId": 1, "ticker": "AAPL", "side": "BUY", "totalSize": 1,
         "price": 100.0, "status": "Submitted", "order_ref": "CLAUDIA-1783692527147"},
    ]}
    text, fig = toolkit.execute("diagnose_orders", {})
    assert "ClaudIA-staged" in text


# ============================================================================
# _get_pa_performance
# ============================================================================


def test_get_order_status_happy_path(toolkit):
    """Returns JSON order status for the given order ID."""
    toolkit._client.get_order_status.return_value = {
        "orderId": 42, "status": "Submitted", "filledQuantity": 0
    }
    text, fig = toolkit.execute("get_order_status", {"order_id": "42"})
    assert fig is None
    assert "Submitted" in text
    assert "42" in text
    toolkit._client.get_order_status.assert_called_once_with("42")


def test_get_order_status_error(toolkit):
    """Propagates exception through _safe_error."""
    toolkit._client.get_order_status.side_effect = RuntimeError("order not found")
    text, fig = toolkit.execute("get_order_status", {"order_id": "99"})
    assert fig is None
    assert "unexpected" in text.lower()


# ============================================================================
# _delete_cache
# ============================================================================


