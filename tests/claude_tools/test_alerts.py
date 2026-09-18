import re
from pathlib import Path
from typing import Any

import pytest

from .conftest import assert_tool_failed, assert_tool_succeeded

pytestmark = pytest.mark.alerts


def test_execute_get_alerts_empty(toolkit):
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.get_alerts.return_value = []
    text, fig = toolkit.execute("get_alerts", {})
    assert "No price alerts" in text
    assert fig is None


def test_execute_get_alerts_returns_json(toolkit):
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.get_alerts.return_value = [{"orderId": 1, "alertName": "AAPL >= 200", "alertActive": 1}]
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
    toolkit._client.create_alert.return_value = {"orderId": 42, "alertName": "AAPL >= 200"}
    _text, fig = toolkit.execute("create_price_alert", {"symbol": "AAPL", "operator": ">=", "price": 200.0})
    # STK resolves via /trsrv/stocks since 2026-07-28 (the conftest fixture supplies a
    # single US listing, conid 265598); /iserver/secdef/search must not be consulted.
    toolkit._client.get_stocks.assert_called_once_with(["AAPL"])
    toolkit._client.search_contract.assert_not_called()
    toolkit._client.create_alert.assert_called_once()
    call_alert = toolkit._client.create_alert.call_args[0][1]
    # conidex, not conid+exchange — IBKR documents one concatenated field (TOOL-02).
    assert call_alert["conditions"][0]["conidex"] == "265598@SMART"
    assert call_alert["conditions"][0]["operator"] == ">="
    assert call_alert["conditions"][0]["value"] == "200.0"
    # `conditionType` is gone: IBKR documents no such field, and `type: 1` means Price.
    assert call_alert["conditions"][0]["type"] == 1
    assert "conditionType" not in call_alert["conditions"][0]
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
    toolkit.execute("create_price_alert", {"symbol": "CL", "sec_type": "FUT", "operator": ">=", "price": 85.0})
    toolkit._client.search_contract.assert_not_called()
    toolkit._client.get_futures.assert_called_once_with(["CL"])
    call_alert = toolkit._client.create_alert.call_args[0][1]
    assert call_alert["conditions"][0]["conidex"] == "12345@SMART"  # front month (earliest expiration)


def test_execute_create_price_alert_fx_resolves_via_currency_pairs(toolkit):
    """CASH (FX) alerts must resolve via get_currency_pairs, not search_contract."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.get_currency_pairs.return_value = [{"symbol": "EUR.USD", "conid": 99999}]
    toolkit._client.create_alert.return_value = {"orderId": 9}
    toolkit.execute("create_price_alert", {"symbol": "EUR.USD", "sec_type": "CASH", "operator": ">=", "price": 1.10})
    toolkit._client.search_contract.assert_not_called()
    toolkit._client.get_currency_pairs.assert_called_once_with("EUR")
    call_alert = toolkit._client.create_alert.call_args[0][1]
    assert call_alert["conditions"][0]["conidex"] == "99999@SMART"


def test_execute_create_price_alert_invalid_conid_returns_error(toolkit):
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.get_stocks.return_value = [
        {"name": "APPLE INC", "assetClass": "STK", "contracts": [{"conid": "N/A", "exchange": "NASDAQ", "isUS": True}]}
    ]
    text, _fig = toolkit.execute("create_price_alert", {"symbol": "AAPL", "operator": ">=", "price": 200.0})
    assert "conid" in text.lower()
    toolkit._client.create_alert.assert_not_called()


def test_execute_create_price_alert_no_contract(toolkit):
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    # STK resolves via /trsrv/stocks since 2026-07-28, not /iserver/secdef/search.
    toolkit._client.get_stocks.return_value = []
    text, _fig = toolkit.execute("create_price_alert", {"symbol": "FAKE", "operator": "<=", "price": 50.0})
    assert "Could not resolve conid" in text or "No" in text
    toolkit._client.create_alert.assert_not_called()


def test_execute_create_price_alert_custom_name(toolkit):
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.search_contract.return_value = [{"conid": 265598}]
    toolkit._client.create_alert.return_value = {"orderId": 5}
    toolkit.execute("create_price_alert", {"symbol": "AAPL", "operator": ">=", "price": 200.0, "name": "My alert"})
    call_alert = toolkit._client.create_alert.call_args[0][1]
    assert call_alert["alertName"] == "My alert"


def test_execute_delete_alert(toolkit):
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.delete_alert.return_value = {"success": True}
    _text, fig = toolkit.execute("delete_alert", {"alert_id": "42"})
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
    text, fig = toolkit.execute("modify_price_alert", {"alert_id": "7", "price": 210.0, "operator": ">="})
    assert fig is None
    assert len(text) > 0
    # Confirm the patched value was sent
    sent = toolkit._client.create_alert.call_args[0][1]
    assert sent["conditions"][0]["value"] == "210.0"


def test_modify_price_alert_not_found(toolkit):
    """Returns 'not found' when get_alert returns empty."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.get_alert.return_value = {}
    text, fig = toolkit.execute("modify_price_alert", {"alert_id": "999", "price": 200.0})
    assert fig is None
    assert "not found" in text.lower()
    toolkit._client.create_alert.assert_not_called()


def test_modify_price_alert_name_update(toolkit):
    """Updates alertName field when 'name' is provided."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.get_alert.return_value = {"alertName": "old name", "tif": "GTC", "conditions": []}
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
    assert_tool_failed(text, containing="unexpected error")


# ============================================================================
# _sync_flex_archive
# ============================================================================


def test_create_price_alert_explains_the_gateway_operator_block_on_403(toolkit):
    """A 403 here has one known cause, and it is not the account's permissions.

    Measured 2026-09-16 against a live authenticated gateway: a request body containing
    `>=` or `<=` never reaches IBKR — the gateway answers an opaque HTML
    `403 Error 403 - Access Denied`, logging nothing. Those are the only two operators
    IBKR's alert engine accepts: `>`, `<`, `==` and every other spelling reach IBKR and
    come back `{"error":"Condition #1:can't recognize fix [>]"}`.

    So alert creation is impossible through the Client Portal Gateway as published, and
    `DELETE` — also a write — works fine, which rules out the "no trading session"
    explanation this repo recorded for months.

    The tool cannot fix that. It can stop reporting someone else's defect as the caller's
    problem: `_safe_error`'s generic text sends a reader off to check account permissions
    that are not the cause.
    """
    from ibkr_core_mcp.exceptions import IBKRAPIError

    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.search_contract.return_value = [{"conid": 265598, "symbol": "AAPL"}]
    toolkit._client.create_alert.side_effect = IBKRAPIError(
        "IBKR gateway returned HTTP 403: Error 403 - Access Denied", status_code=403
    )

    text, fig = toolkit.execute("create_price_alert", {"symbol": "AAPL", "operator": ">=", "price": 250.0})

    assert fig is None
    assert "operator" in text.lower(), text
    # Names the real cause AND explicitly rules out the wrong one this repo recorded for
    # months. Asserting the absence of the word "permission" would be wrong — the message
    # has to use it in order to deny it.
    assert "NOT an account permissions problem" in text, text
    assert ">=" in text and "<=" in text, "the blocked operators are not named"
    assert "ibkr-api-behaviors-reference" in text, "the reader is not pointed at the evidence"


# The LIVE response from GET /iserver/account/alert/1331320792, captured 2026-09-16 from an
# authenticated Client Portal Gateway (build 2023-04-24) against a real alert created on
# IBKR Mobile. Not a documentation example — this is what the gateway actually returns, and
# it is snake_case throughout: 26 top-level keys, none camelCase.
_LIVE_ALERT_DETAIL = {
    "account": "U1234567",
    "order_id": 1331320792,
    "alert_name": "AAPL <= 1.00",
    "tif": "GTC",
    "expire_time": None,
    "alert_active": 1,
    "alert_repeatable": 0,
    "alert_email": "trader@example.com",
    "alert_send_message": 1,
    "alert_message": "$MESSAGE$",
    "alert_show_popup": 0,
    "alert_play_audio": None,
    "order_status": "Submitted",
    "alert_triggered": False,
    "fg_color": "#FFFFFF",
    "bg_color": "#0000CC",
    "order_not_editable": False,
    "itws_orders_only": 0,
    "alert_mta_currency": None,
    "alert_mta_defaults": "9:STATE=0,MIN=-10000",
    "tool_id": None,
    "time_zone": None,
    "alert_default_type": None,
    "condition_size": 1,
    "condition_outside_rth": 1,
    "conditions": [
        {
            "condition_type": 1,
            "conidex": "265598@SMART",
            "contract_description_1": "AAPL",
            "condition_operator": "<=",
            "condition_trigger_method": "2",
            "condition_value": "1.00",
            "condition_logic_bind": "n",
            "condition_time_zone": None,
        }
    ],
}

# Every field the create/modify endpoint documents. Anything else is a field IBKR never asked
# for. https://www.interactivebrokers.com/docs/web-api/api-reference/trading/trading-alerts/create-alert
_REQUEST_KEYS = {
    "alertName",
    "alertMessage",
    "alertRepeatable",
    "outsideRth",
    "tif",
    "conditions",
    "orderId",
    "email",
    "expireTime",
    "iTWSOrdersOnly",
    "sendMessage",
    "showPopup",
}
_CONDITION_KEYS = {"conidex", "logicBind", "operator", "triggerMethod", "type", "value", "timeZone"}
_REQUIRED_KEYS = {"alertName", "alertMessage", "alertRepeatable", "outsideRth", "tif", "conditions"}
_REQUIRED_CONDITION_KEYS = {"conidex", "logicBind", "operator", "triggerMethod", "type", "value"}


def test_alert_detail_translates_into_the_documented_request_shape():
    """TOOL-01. The GET and POST shapes share almost no field name, and the handler posted
    the GET response back with three camelCase keys written on top of it.

    Measured against the live gateway 2026-09-16: the detail response has 26 top-level keys,
    none camelCase; the request schema has 19 fields, none snake_case; exactly two names
    (`conditions`, `tif`) appear in both. Seventeen of the nineteen request fields were
    therefore absent by name from what we sent.
    """
    from ibkr_core_mcp.claude_tools import _alert_detail_to_request

    body = _alert_detail_to_request(_LIVE_ALERT_DETAIL)

    assert set(body) >= _REQUIRED_KEYS, f"missing required fields: {sorted(_REQUIRED_KEYS - set(body))}"
    assert body["alertName"] == "AAPL <= 1.00"
    assert body["alertMessage"] == "$MESSAGE$"
    assert body["alertRepeatable"] == 0
    assert body["outsideRth"] == 1
    assert body["tif"] == "GTC"
    assert body["email"] == "trader@example.com"
    assert body["sendMessage"] == 1
    assert body["showPopup"] == 0
    assert body["iTWSOrdersOnly"] == 0

    condition = body["conditions"][0]
    assert set(condition) >= _REQUIRED_CONDITION_KEYS
    assert condition["conidex"] == "265598@SMART"
    assert condition["operator"] == "<="
    assert condition["value"] == "1.00"
    assert condition["type"] == 1
    assert condition["logicBind"] == "n"
    assert condition["triggerMethod"] == "2"


def test_the_translated_body_carries_orderId_so_it_is_a_modify():
    """The sharpest consequence, stated on its own because it changes what the call MEANS.

    `IBKRClient.create_alert`: "orderId distinguishes create from modify: omitted or 0
    creates, an existing alert id modifies that alert". The detail response supplies
    `order_id`; the body needs `orderId`. Without the translation a modify silently became a
    create — leaving the original alert untouched and adding a second one.
    """
    from ibkr_core_mcp.claude_tools import _alert_detail_to_request

    body = _alert_detail_to_request(_LIVE_ALERT_DETAIL)

    assert body["orderId"] == 1331320792


def test_the_translated_body_carries_no_field_ibkr_did_not_document():
    """The stale snake_case keys must be gone, not shadowed.

    `order_status`, `alert_triggered`, `fg_color`, `alert_mta_defaults`,
    `contract_description_1` and the rest are read-only detail fields. Asserted against
    IBKR's documented request schema rather than a list of keys that happen to be wrong now.
    """
    from ibkr_core_mcp.claude_tools import _alert_detail_to_request

    body = _alert_detail_to_request(_LIVE_ALERT_DETAIL)

    assert not set(body) - _REQUEST_KEYS, f"undocumented fields: {sorted(set(body) - _REQUEST_KEYS)}"
    extra = set(body["conditions"][0]) - _CONDITION_KEYS
    assert not extra, f"undocumented condition fields: {sorted(extra)}"


def test_translation_omits_optional_fields_that_are_null():
    """`expire_time` and `condition_time_zone` are null on this alert and both map to
    optional request fields. An optional field present-but-null is not the same request as
    one that is absent, and `expireTime` is documented as meaningful only with tif=GTD —
    this alert is GTC."""
    from ibkr_core_mcp.claude_tools import _alert_detail_to_request

    body = _alert_detail_to_request(_LIVE_ALERT_DETAIL)

    assert "expireTime" not in body
    assert "timeZone" not in body["conditions"][0]


def test_modify_price_alert_sends_a_translated_modify_body(toolkit):
    """End to end: the handler must post the translated shape, carrying `orderId`, with the
    caller's patch applied to the TRANSLATED field names rather than beside the stale ones."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U1234567"}]
    toolkit._client.get_alert.return_value = dict(_LIVE_ALERT_DETAIL)
    toolkit._client.create_alert.return_value = {"success": True, "order_id": 1331320792}

    text, _ = toolkit.execute("modify_price_alert", {"alert_id": "1331320792", "name": "AAPL audit", "price": 2.50})

    assert_tool_succeeded(text)
    account_id, body = toolkit._client.create_alert.call_args[0]
    assert account_id == "U1234567"
    assert body["orderId"] == 1331320792, "a modify without orderId creates a second alert"
    assert body["alertName"] == "AAPL audit"
    # `str(2.50)` is "2.5" — the handler stringifies the caller's float as-is, which is
    # pre-existing behaviour and what IBKR receives. Asserted as it is, not as it looks.
    assert body["conditions"][0]["value"] == "2.5"
    assert body["conditions"][0]["operator"] == "<=", "an unset field must be carried unchanged"
    assert not set(body) - _REQUEST_KEYS, f"undocumented fields: {sorted(set(body) - _REQUEST_KEYS)}"
    assert "alert_name" not in body and "condition_outside_rth" not in body


def _stub_alert_client(toolkit):
    """A toolkit whose conid resolution and alert write are stubbed, for body assertions."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U1234567"}]
    toolkit._client.get_stocks.return_value = [
        {"name": "APPLE INC", "assetClass": "STK", "contracts": [{"conid": 265598, "exchange": "NASDAQ", "isUS": True}]}
    ]
    toolkit._client.create_alert.return_value = {"order_id": 1, "success": True}
    toolkit._client.create_alert.reset_mock()
    return toolkit


# ---------------------------------------------------------------------------
# TOOL-02 — the create body's condition used field names IBKR does not document
# ---------------------------------------------------------------------------


def test_create_price_alert_sends_the_documented_condition_fields(toolkit):
    """IBKR documents six Required condition fields; this sent four, two of them wrong.

    From IBKR's own capture (`docs/audits/audit-evidence/scrapes/cpapi-v1.md`, the
    create/modify alert body): `conidex` ("conid@exchange"), `logicBind`, `operator`,
    `triggerMethod`, `type`, `value` — plus `timeZone` for MTA alerts only.

    This handler sent `conid` and `exchange` as two separate keys, omitted `logicBind`
    and `triggerMethod` entirely, and added `conditionType: "Price"`, which appears
    nowhere in IBKR's documentation — `type: 1` already means Price. Corroborated by the
    account holder's own alert, whose GET detail returns `conidex`,
    `condition_logic_bind` and `condition_trigger_method`.

    The live page is `api-reference/trading/trading-alerts/create-alert.md` (28,399 B,
    fetched 2026-09-16 alongside a fabricated control that returned "# Page Not Found").
    It is **absent from `llms.txt`**, which is why the index cannot find it, and the
    `v1/endpoints/alerts/create-or-modify-alert.md` that five files cited returns
    "# Page Not Found". Both it and the archived capture agree on these six fields.
    """
    toolkit._client.get_accounts.return_value = [{"accountId": "U1234567"}]
    toolkit._client.get_stocks.return_value = [
        {"name": "APPLE INC", "assetClass": "STK", "contracts": [{"conid": 265598, "exchange": "NASDAQ", "isUS": True}]}
    ]
    toolkit._client.create_alert.return_value = {"order_id": 1, "success": True}

    toolkit.execute("create_price_alert", {"symbol": "AAPL", "operator": ">", "price": 250.0})

    condition = toolkit._client.create_alert.call_args.args[1]["conditions"][0]
    assert condition["conidex"] == "265598@SMART"
    assert condition["logicBind"] == "n", "END — a single-condition alert binds to nothing after it"
    assert condition["triggerMethod"] == "0", "IBKR: 'Pass the string representation of zero'"
    assert condition["type"] == 1
    assert condition["operator"] == ">"
    assert condition["value"] == "250.0"
    assert "conid" not in condition and "exchange" not in condition, "conidex replaces both"
    assert "conditionType" not in condition, "not a field IBKR documents"


def test_create_price_alert_body_carries_only_documented_fields(toolkit):
    """`isSizeCondition` appears in neither the live page nor the archived capture.

    It is the same class as `conditionType`: a field invented alongside the real ones.
    Checked against `api-reference/trading/trading-alerts/create-alert.md` (28,399 B,
    fetched 2026-09-16 with a fabricated control that returned "# Page Not Found") and
    against `docs/audits/audit-evidence/scrapes/cpapi-v1.md`; zero occurrences in both.
    """
    _stub_alert_client(toolkit)

    toolkit.execute("create_price_alert", {"symbol": "AAPL", "operator": ">=", "price": 250.0})

    body = toolkit._client.create_alert.call_args.args[1]
    documented = {
        "alertName",
        "alertMessage",
        "alertRepeatable",
        "outsideRth",
        "tif",
        "conditions",
        "orderId",
        "email",
        "expireTime",
        "iTWSOrdersOnly",
        "sendMessage",
        "showPopup",
    }
    assert set(body) <= documented, f"fields IBKR does not document: {sorted(set(body) - documented)}"


def test_create_price_alert_sends_enum_numbers_not_python_bools(toolkit):
    """IBKR documents `outsideRth` and `alertRepeatable` as enums of 0 and 1.

    `alertRepeatable` was already `int(...)`; `outsideRth` was passed straight through as a
    Python bool, which serialises to `true`/`false`, not `1`/`0`. The account holder's own
    alert returns `condition_outside_rth: 0` — an int.
    """
    _stub_alert_client(toolkit)

    toolkit.execute(
        "create_price_alert",
        {"symbol": "AAPL", "operator": ">=", "price": 250.0, "outside_rth": True, "repeat": True},
    )

    body = toolkit._client.create_alert.call_args.args[1]
    assert body["outsideRth"] == 1 and not isinstance(body["outsideRth"], bool)
    assert body["alertRepeatable"] == 1 and not isinstance(body["alertRepeatable"], bool)


def test_create_price_alert_tif_offers_only_what_ibkr_documents(toolkit):
    """IBKR's `tif` enum is GTC and GTD. The schema offered GTC and **DAY**.

    `DAY` appears nowhere in IBKR's alert documentation, and the schema described it as
    "expires at market close" — a behaviour no page states.
    """
    from ibkr_core_mcp.claude_tools import TOOL_DEFINITIONS

    schema: Any = next(t for t in TOOL_DEFINITIONS if t["name"] == "create_price_alert")
    assert schema["input_schema"]["properties"]["tif"]["enum"] == ["GTC", "GTD"]


def test_create_price_alert_refuses_gtd_without_an_expiry(toolkit):
    """IBKR: `expireTime` is "Used with a tif of GTD only", and GTD means nothing without it."""
    _stub_alert_client(toolkit)

    text, _ = toolkit.execute("create_price_alert", {"symbol": "AAPL", "operator": ">=", "price": 250.0, "tif": "GTD"})

    assert "expire_time" in text
    toolkit._client.create_alert.assert_not_called()


def test_create_price_alert_passes_an_expiry_through_for_gtd(toolkit):
    _stub_alert_client(toolkit)

    toolkit.execute(
        "create_price_alert",
        {"symbol": "AAPL", "operator": ">=", "price": 250.0, "tif": "GTD", "expire_time": "20270101-12:00:00"},
    )

    assert toolkit._client.create_alert.call_args.args[1]["expireTime"] == "20270101-12:00:00"


# ---------------------------------------------------------------------------
# TOOL-R3 (2026-09-17): TOOL-02's tif fix reached `create_price_alert` and not `modify`
# ---------------------------------------------------------------------------


def _tool(name):
    from ibkr_core_mcp.claude_tools import TOOL_DEFINITIONS

    return next(t for t in TOOL_DEFINITIONS if t["name"] == name)


def test_modify_price_alert_offers_the_same_tif_vocabulary_as_create():
    """IBKR documents `tif` as GTC or GTD and `expireTime` as "used with a tif of GTD only".

    TOOL-02 (2026-09-16) removed `DAY` from `create_price_alert` and added `expire_time`.
    `modify_price_alert` kept `["GTC", "DAY"]` and no `expire_time` input, so the model was
    offered a value IBKR does not accept on one tool and refused it on the other — one fix
    applied to one branch of the same body and never swept.
    """
    create, modify = _tool("create_price_alert"), _tool("modify_price_alert")

    assert modify["input_schema"]["properties"]["tif"]["enum"] == create["input_schema"]["properties"]["tif"]["enum"]
    assert "DAY" not in modify["input_schema"]["properties"]["tif"]["enum"]
    assert "expire_time" in modify["input_schema"]["properties"]


def test_modify_price_alert_refuses_gtd_without_an_expiry(toolkit):
    """A GTD alert with no expiry is not a request IBKR can act on — the create tool says so."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.get_alert.return_value = {
        "order_id": 7,
        "alert_name": "AAPL <= 1.00",
        "tif": "GTC",
        "conditions": [],
    }

    text, _ = toolkit.execute("modify_price_alert", {"alert_id": "7", "tif": "GTD"})

    assert "expire_time" in text
    toolkit._client.create_alert.assert_not_called()


def test_modify_price_alert_sends_the_expiry_under_ibkrs_name(toolkit):
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.get_alert.return_value = {
        "order_id": 7,
        "alert_name": "AAPL <= 1.00",
        "tif": "GTC",
        "conditions": [],
    }
    toolkit._client.create_alert.return_value = {"orderId": 7}

    toolkit.execute("modify_price_alert", {"alert_id": "7", "tif": "GTD", "expire_time": "20261231-16:00:00"})

    sent = toolkit._client.create_alert.call_args[0][1]
    assert sent["tif"] == "GTD"
    assert sent["expireTime"] == "20261231-16:00:00"


def test_modify_price_alert_keeps_an_existing_expiry_when_only_tif_changes(toolkit):
    """The detail response carries `expire_time`; translated, it satisfies GTD on its own."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.get_alert.return_value = {
        "order_id": 7,
        "alert_name": "AAPL <= 1.00",
        "tif": "GTC",
        "expire_time": "20261231-16:00:00",
        "conditions": [],
    }
    toolkit._client.create_alert.return_value = {"orderId": 7}

    toolkit.execute("modify_price_alert", {"alert_id": "7", "tif": "GTD"})

    sent = toolkit._client.create_alert.call_args[0][1]
    assert sent["tif"] == "GTD" and sent["expireTime"] == "20261231-16:00:00"


# ---------------------------------------------------------------------------
# TOOL-01's closing property: the alert-write block is stated everywhere it matters,
# and stops being stated everywhere the day it lifts
# ---------------------------------------------------------------------------

_BLOCK_MARKER = "not possible through the Client Portal Gateway as published"
_UNLOCK_MARKER = "alert-write round trip: PASS"


def test_the_alert_write_block_is_stated_everywhere_it_matters_until_it_lifts():
    """Price-alert creation and modification cannot succeed through the gateway IBKR publishes:
    it refuses any body carrying `>=` or `<=` before IBKR sees it, and IBKR's engine refuses
    the three operators the gateway lets through (measured 2026-09-16; the elimination table
    is `docs/ibkr-api-behaviors-reference.md` § Price alerts). Not this package's defect, and
    not something it can fix — but `README.md` and `docs/tools-reference.md` went on
    describing the tools as working, and `tests/test_alerts_live.py` said the write path was
    "validated manually through the ClaudIA UI", which runs on the same gateway.

    So the status is held the way the event-contract status is: one phrase, present in every
    place a reader would form the belief, and **required to be absent everywhere the day
    `docs/audits/live-test-log.md` records a passing round trip** — so the warning cannot
    outlive the block any more than the block could go unmentioned.
    """
    from ibkr_core_mcp.claude_tools import TOOL_DEFINITIONS

    repo = Path(__file__).resolve().parents[2]
    surfaces = {
        "create_price_alert description": next(
            t["description"] for t in TOOL_DEFINITIONS if t["name"] == "create_price_alert"
        ),
        "modify_price_alert description": next(
            t["description"] for t in TOOL_DEFINITIONS if t["name"] == "modify_price_alert"
        ),
        "README.md": (repo / "README.md").read_text(),
        "docs/tools-reference.md": (repo / "docs/tools-reference.md").read_text(),
        "docs/ibkr-api-behaviors-reference.md": (repo / "docs/ibkr-api-behaviors-reference.md").read_text(),
        "tests/test_alerts_live.py": (repo / "tests/test_alerts_live.py").read_text(),
    }
    log = (repo / "docs/audits/live-test-log.md").read_text()
    # The log's own "Deliberately not covered" section names the unlock phrase, in backticks,
    # so a reader knows what to write. Read literally, that sentence IS the unlock — the first
    # run of this test took the unlock branch on the prose explaining it (API-12's defect: a
    # document that explains a check trips the check it explains). Inline code is stripped
    # before looking; a real run entry writes the phrase plainly.
    log_outside_code = re.sub(r"`[^`\n]*`", "", log)

    if _UNLOCK_MARKER in log_outside_code:
        stale = [name for name, text in surfaces.items() if _BLOCK_MARKER in text]
        assert not stale, (
            f"the live-test log records a passing alert-write round trip, but these still say the "
            f"write is {_BLOCK_MARKER!r}: {stale}. Remove the statement everywhere, retire the "
            "'Deliberately not covered' section, and delete this test's unlock branch."
        )
        return

    missing = [name for name, text in surfaces.items() if _BLOCK_MARKER not in text]
    assert not missing, f"these surfaces do not state that alert writes are {_BLOCK_MARKER!r}: {missing}"
    assert "Deliberately not covered — alert writes" in log, (
        "docs/audits/live-test-log.md must carry a 'Deliberately not covered — alert writes' section "
        "beside the event-contracts one, so an absence in the log is not mistaken for an omission"
    )


# ---------------------------------------------------------------------------
# TOOL-R4 / TOOL-R5 — the alert-write classifier reads the status, and both
# alert bodies send IBKR's enum int (release-readiness audit 2026-09-16, Phase 4)
# ---------------------------------------------------------------------------


def test_the_alert_write_classifier_reads_the_status_not_the_digits():
    """`403` inside an error's TEXT is not a 403.

    `_alert_write_error` answered the "permanently blocked upstream, do not retry" text for
    any exception whose text contained the digits. Probed 2026-09-17 (TOOL-R4): a 500 whose
    reference number carries them and a 400 for an alert id that does both got it, and the
    model was told not to retry a transient failure. Every gateway status arrives as an
    `IBKRAPIError` with `status_code` set by `with_retry`, so the code is the only thing
    worth reading.
    """
    from ibkr_core_mcp.claude_tools import _alert_write_error
    from ibkr_core_mcp.exceptions import IBKRAPIError

    assert (
        _alert_write_error(IBKRAPIError("IBKR gateway returned HTTP 500: internal error, ref 84031", status_code=500))
        is None
    )
    assert (
        _alert_write_error(IBKRAPIError("IBKR gateway returned HTTP 400: alert 1403 not found", status_code=400))
        is None
    )
    # Outside the hierarchy there is no status at all, whatever the text says.
    assert _alert_write_error(RuntimeError("HTTP 403 from something that is not the gateway")) is None
    # The counter-case: the real block still gets the honest text.
    real = IBKRAPIError("IBKR gateway returned HTTP 403: Error 403 - Access Denied", status_code=403)
    assert _alert_write_error(real) is not None


def test_create_price_alert_does_not_report_a_500_as_the_operator_block(toolkit):
    """End to end: a transient 500 whose text happens to contain `403` must reach the
    caller as the 500 it is, not as "blocked upstream, do not retry" (TOOL-R4)."""
    from ibkr_core_mcp.exceptions import IBKRAPIError

    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.search_contract.return_value = [{"conid": 265598, "symbol": "AAPL"}]
    toolkit._client.create_alert.side_effect = IBKRAPIError(
        "IBKR gateway returned HTTP 500: internal error, ref 84031", status_code=500
    )

    text, fig = toolkit.execute("create_price_alert", {"symbol": "AAPL", "operator": ">", "price": 250.0})

    assert fig is None
    assert "NOT an account permissions problem" not in text, text
    assert "HTTP 500" in text, text


def test_modify_price_alert_sends_outsideRth_as_ibkrs_enum_int(toolkit):
    """IBKR documents `outsideRth` as an enum of 0 and 1; a Python bool serialises as
    `true`. Create casts (TOOL-02); modify wrote the caller's bool over the translated
    body's int, so the same field went out in two shapes from two handlers (TOOL-R5)."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U1234567"}]
    toolkit._client.get_alert.return_value = dict(_LIVE_ALERT_DETAIL)
    toolkit._client.create_alert.return_value = {"success": True, "order_id": 1331320792}

    text, _ = toolkit.execute("modify_price_alert", {"alert_id": "1331320792", "outside_rth": True})

    assert_tool_succeeded(text)
    _, body = toolkit._client.create_alert.call_args[0]
    assert body["outsideRth"] == 1
    assert not isinstance(body["outsideRth"], bool), "a bool serialises as true, which is not the documented enum"


def test_the_two_alert_vocabularies_share_exactly_the_names_the_maps_say():
    """The detail response and the create/modify request are two vocabularies, and the
    source described their overlap twice with different numbers: "26 keys, exactly two
    shared" above the maps and "34 keys, exactly three" in the modify docstring (TOOL-R6).
    Both were half right — 26 is the top level, 34 counts the 8 inside `conditions[]`, and
    the third shared name, `conidex`, is one of those 8. Measured here from the live capture
    and the maps, so the prose has one number to cite.
    """
    from ibkr_core_mcp.claude_tools import _ALERT_CONDITION_TO_REQUEST, _ALERT_DETAIL_TO_REQUEST

    conditions = _LIVE_ALERT_DETAIL["conditions"]
    assert isinstance(conditions, list)
    top, nested = set(_LIVE_ALERT_DETAIL), set(conditions[0])
    assert (len(top), len(nested)) == (26, 8)

    request_top = set(_ALERT_DETAIL_TO_REQUEST.values()) | {"conditions"}
    request_nested = set(_ALERT_CONDITION_TO_REQUEST.values())
    assert request_top == _REQUEST_KEYS and request_nested == _CONDITION_KEYS
    assert len(request_top) + len(request_nested) == 19

    assert top & request_top == {"conditions", "tif"}
    assert nested & request_nested == {"conidex"}
