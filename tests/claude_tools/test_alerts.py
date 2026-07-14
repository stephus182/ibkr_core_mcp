
import pytest

pytestmark = pytest.mark.alerts

def test_execute_get_alerts_empty(toolkit):
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.get_alerts.return_value = []
    text, fig = toolkit.execute("get_alerts", {})
    assert "No price alerts" in text
    assert fig is None


def test_execute_get_alerts_returns_json(toolkit):
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.get_alerts.return_value = [
        {"orderId": 1, "alertName": "AAPL >= 200", "alertActive": 1}
    ]
    text, fig = toolkit.execute("get_alerts", {})
    assert "AAPL" in text
    assert fig is None


# create_price_alert conid resolution — via _resolve_snapshot_conid (verified
# 2026-07-07): the old implementation called self._client.search_contract directly,
# which per client.py's own docstring only supports STK/IND/BOND. The tool schema
# advertised FUT/OPT/FX support that was unreachable — FUT/CASH alerts would
# silently resolve to the wrong contract or fail. See docs/audits/claude-tools-audit-2026-07.md.

def test_execute_create_price_alert_resolves_symbol(toolkit):
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.search_contract.return_value = [{"conid": 265598, "symbol": "AAPL", "exchange": "NASDAQ"}]
    toolkit._client.create_alert.return_value = {"orderId": 42, "alertName": "AAPL >= 200"}
    text, fig = toolkit.execute("create_price_alert", {
        "symbol": "AAPL", "operator": ">=", "price": 200.0
    })
    toolkit._client.search_contract.assert_called_once_with("AAPL", "STK")
    toolkit._client.create_alert.assert_called_once()
    call_alert = toolkit._client.create_alert.call_args[0][1]
    assert call_alert["conditions"][0]["conid"] == 265598
    assert call_alert["conditions"][0]["operator"] == ">="
    assert call_alert["conditions"][0]["value"] == "200.0"
    assert call_alert["conditions"][0]["conditionType"] == "Price"
    assert fig is None


def test_execute_create_price_alert_futures_resolves_via_get_futures(toolkit):
    """FUT alerts must resolve via get_futures (front month), NOT search_contract —
    search_contract doesn't support FUT per client.py's documented endpoint scope."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.get_futures.return_value = [
        {"conid": 12345, "symbol": "CL", "expirationDate": "20260918"},
        {"conid": 12346, "symbol": "CL", "expirationDate": "20261016"},
    ]
    toolkit._client.create_alert.return_value = {"orderId": 7}
    toolkit.execute("create_price_alert", {
        "symbol": "CL", "sec_type": "FUT", "operator": ">=", "price": 85.0
    })
    toolkit._client.search_contract.assert_not_called()
    toolkit._client.get_futures.assert_called_once_with(["CL"])
    call_alert = toolkit._client.create_alert.call_args[0][1]
    assert call_alert["conditions"][0]["conid"] == 12345  # front month (earliest expiration)


def test_execute_create_price_alert_fx_resolves_via_currency_pairs(toolkit):
    """CASH (FX) alerts must resolve via get_currency_pairs, not search_contract."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.get_currency_pairs.return_value = [{"symbol": "EUR.USD", "conid": 99999}]
    toolkit._client.create_alert.return_value = {"orderId": 9}
    toolkit.execute("create_price_alert", {
        "symbol": "EUR.USD", "sec_type": "CASH", "operator": ">=", "price": 1.10
    })
    toolkit._client.search_contract.assert_not_called()
    toolkit._client.get_currency_pairs.assert_called_once_with("EUR")
    call_alert = toolkit._client.create_alert.call_args[0][1]
    assert call_alert["conditions"][0]["conid"] == 99999


def test_execute_create_price_alert_invalid_conid_returns_error(toolkit):
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.search_contract.return_value = [{"conid": "N/A", "symbol": "AAPL"}]
    text, fig = toolkit.execute("create_price_alert", {
        "symbol": "AAPL", "operator": ">=", "price": 200.0
    })
    assert "conid" in text.lower()
    toolkit._client.create_alert.assert_not_called()


def test_execute_create_price_alert_no_contract(toolkit):
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.search_contract.return_value = []
    text, fig = toolkit.execute("create_price_alert", {
        "symbol": "FAKE", "operator": "<=", "price": 50.0
    })
    assert "Could not resolve conid" in text or "No" in text
    toolkit._client.create_alert.assert_not_called()


def test_execute_create_price_alert_custom_name(toolkit):
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.search_contract.return_value = [{"conid": 265598}]
    toolkit._client.create_alert.return_value = {"orderId": 5}
    toolkit.execute("create_price_alert", {
        "symbol": "AAPL", "operator": ">=", "price": 200.0, "name": "My alert"
    })
    call_alert = toolkit._client.create_alert.call_args[0][1]
    assert call_alert["alertName"] == "My alert"


def test_execute_delete_alert(toolkit):
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.delete_alert.return_value = {"success": True}
    text, fig = toolkit.execute("delete_alert", {"alert_id": "42"})
    toolkit._client.delete_alert.assert_called_once_with("U123", "42")
    assert fig is None


def test_execute_activate_alert_default_true(toolkit):
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.activate_alert.return_value = {"success": True}
    toolkit.execute("activate_alert", {"alert_id": "42"})
    toolkit._client.activate_alert.assert_called_once_with("U123", "42", True)


def test_execute_activate_alert_deactivate(toolkit):
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.activate_alert.return_value = {"success": True}
    toolkit.execute("activate_alert", {"alert_id": "42", "activate": False})
    toolkit._client.activate_alert.assert_called_once_with("U123", "42", False)


# ── _safe_error — all exception branches ────────────────────────────────────

def test_modify_price_alert_happy_path(toolkit):
    """Modifies price and operator on an existing alert and returns result."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.get_alert.return_value = {
        "alertName": "AAPL >= 200",
        "tif": "GTC",
        "conditions": [{"value": "200.0", "operator": ">="}],
    }
    toolkit._client.create_alert.return_value = {"orderId": 7, "alertName": "AAPL >= 210"}
    text, fig = toolkit.execute("modify_price_alert", {
        "alert_id": "7", "price": 210.0, "operator": ">="
    })
    assert fig is None
    assert len(text) > 0
    # Confirm the patched value was sent
    sent = toolkit._client.create_alert.call_args[0][1]
    assert sent["conditions"][0]["value"] == "210.0"


def test_modify_price_alert_not_found(toolkit):
    """Returns 'not found' when get_alert returns empty."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.get_alert.return_value = {}
    text, fig = toolkit.execute("modify_price_alert", {
        "alert_id": "999", "price": 200.0
    })
    assert fig is None
    assert "not found" in text.lower()
    toolkit._client.create_alert.assert_not_called()


def test_modify_price_alert_name_update(toolkit):
    """Updates alertName field when 'name' is provided."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.get_alert.return_value = {
        "alertName": "old name", "tif": "GTC", "conditions": []
    }
    toolkit._client.create_alert.return_value = {"orderId": 3}
    toolkit.execute("modify_price_alert", {"alert_id": "3", "name": "new name"})
    sent = toolkit._client.create_alert.call_args[0][1]
    assert sent["alertName"] == "new name"


def test_modify_price_alert_error(toolkit):
    """Propagates exception through _safe_error."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.get_alert.side_effect = RuntimeError("alert service down")
    text, fig = toolkit.execute("modify_price_alert", {"alert_id": "1", "price": 200.0})
    assert fig is None
    assert "unexpected" in text.lower()


# ============================================================================
# _sync_flex_archive
# ============================================================================


