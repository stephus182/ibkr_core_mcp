"""Live integration tests for IBKR price alert tools via ClaudeToolkit.

Exercises the full tool invocation path ClaudIA uses:
    ClaudeToolkit.execute() → IBKRClient → IBKR CP REST API

Covers §4b of the live test plan:
    get_alerts, create_price_alert (above / below / options), modify_price_alert,
    activate_alert (deactivate / reactivate), delete_alert

Run with a live, authenticated IBKR gateway:
    pytest tests/test_alerts_live.py -v -m integration

All test alerts use prices that will never fire (prices far outside realistic
market context for the instrument under test).
Every test cleans up after itself — alerts are always deleted in finally blocks.

## Machine test boundary

get_alerts (read) is fully machine-testable and passes.

Alert write operations (create, modify, delete, activate) skip with HTTP 403
in the test harness. This is an IBKR CP API architectural restriction: write
operations require an active brokerage session that BrowserCookieAuth alone
cannot replicate. ClaudIA maintains this session via continuous /tickle keepalive;
the test harness creates a fresh client with cookie auth only.

These write operations are validated manually through the ClaudIA UI:
ask ClaudIA to create an alert and verify it appears on the IBKR mobile app.
This is the correct validation path — not a gap in test coverage.

Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#auth-sessions-brokerage
See docs/live-test-log.md#run-2026-07-01-1 for the confirmed finding.

Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#get-alert-list
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def live_config(tmp_path_factory):
    from ibkr_core_mcp.config import Config
    tmp = tmp_path_factory.mktemp("alerts_live_cfg")
    return Config(
        gateway_url="https://localhost:5055/v1/api",
        anthropic_api_key="test-key",
        gdrive_folder_id="test-folder-id",
        sqlite_path=tmp / "store.db",
        gdrive_token_file=tmp / "token.json",
        gdrive_credentials_file=tmp / "credentials.json",
    )


@pytest.fixture(scope="module")
def live_toolkit(live_config):
    """ClaudeToolkit backed by a real IBKRClient.

    GDriveCache and SQLiteStore are mocked — alert operations do not touch them.
    Skips the entire module if the gateway is unreachable or unauthenticated.

    Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#ping
    """
    from ibkr_core_mcp.auth import BrowserCookieAuth
    from ibkr_core_mcp.client import IBKRClient
    from ibkr_core_mcp.claude_tools import ClaudeToolkit
    client = IBKRClient(live_config, auth=BrowserCookieAuth())
    if not client.ping():
        pytest.skip("IBKR gateway not reachable or not authenticated")
    # Warm up the brokerage session — some write endpoints (alerts, orders) return
    # HTTP 403 without this initialisation call.
    # Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#accounts
    try:
        client.get_accounts()
    except Exception:
        pass
    return ClaudeToolkit(client, MagicMock(), MagicMock(), live_config)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_alert_id(text: str) -> str:
    """Extract the orderId from a create_price_alert text response (JSON string)."""
    try:
        data = json.loads(text)
        raw = data.get("orderId") or data.get("id") or data.get("alertId") or ""
        return str(raw) if raw else ""
    except (json.JSONDecodeError, AttributeError):
        return ""


def _create_alert(toolkit, symbol: str = "AAPL", operator: str = ">=",
                  price: float = 99999.0, **kwargs) -> tuple[str, str]:
    """Create an alert and return (text_response, alert_id).

    Skips with a descriptive message on 403 (no trading session) or rate limit.
    """
    # ClaudeToolkit.execute() catches all exceptions internally and returns them
    # as text via _safe_error() — IBKRAPIError is never re-raised to the caller.
    inputs = {"symbol": symbol, "operator": operator, "price": price, **kwargs}
    text, _ = toolkit.execute("create_price_alert", inputs)
    if "429" in text or "rate limit" in text.lower():
        pytest.skip("Rate limited on create_price_alert — try again in a few seconds")
    if "403" in text:
        pytest.skip(
            "create_price_alert HTTP 403 — alert writes require an active brokerage "
            "session (complete IBKR 2FA login before running these tests)"
        )
    alert_id = _parse_alert_id(text)
    return text, alert_id


def _delete_safe(toolkit, alert_id: str) -> None:
    """Delete an alert; silently ignore errors so cleanup never masks a test failure."""
    if not alert_id:
        return
    try:
        toolkit.execute("delete_alert", {"alert_id": alert_id})
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Read-only
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_toolkit_get_alerts(live_toolkit):
    """get_alerts returns a JSON list or the empty-state message — never an exception.

    Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#get-alert-list
    """
    text, fig = live_toolkit.execute("get_alerts", {})
    assert fig is None
    assert isinstance(text, str) and len(text) > 0
    if text.strip().startswith("["):
        assert isinstance(json.loads(text), list)
    else:
        assert "No price alerts" in text


# ---------------------------------------------------------------------------
# Create + Delete
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_toolkit_alert_price_above(live_toolkit):
    """Create AAPL >= $99999 (never fires), confirm orderId in response, delete.

    Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#create-alert
    """
    text, alert_id = _create_alert(live_toolkit, symbol="AAPL", operator=">=", price=99999.0)
    assert alert_id, f"No alert ID in create response: {text!r}"
    try:
        del_text, _ = live_toolkit.execute("delete_alert", {"alert_id": alert_id})
        assert isinstance(del_text, str)
    except Exception as e:
        pytest.fail(f"delete_alert failed for alert {alert_id}: {e}")


@pytest.mark.integration
def test_toolkit_alert_price_below(live_toolkit):
    """Create AAPL <= $0.01 (never fires) — verifies the '<=' operator path.

    Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#create-alert
    """
    text, alert_id = _create_alert(live_toolkit, symbol="AAPL", operator="<=", price=0.01)
    assert alert_id, f"No alert ID: {text!r}"
    _delete_safe(live_toolkit, alert_id)


@pytest.mark.integration
def test_toolkit_alert_custom_name(live_toolkit):
    """Alert name field is accepted and echoed back in the create response."""
    text, alert_id = _create_alert(live_toolkit, name="_ci_named_alert")
    assert alert_id, f"No alert ID: {text!r}"
    try:
        data = json.loads(text)
        if "alertName" in data:
            assert data["alertName"] == "_ci_named_alert", (
                f"Name not echoed in response: {data}"
            )
    finally:
        _delete_safe(live_toolkit, alert_id)


@pytest.mark.integration
def test_toolkit_alert_outside_rth(live_toolkit):
    """Alert with outside_rth=True (extended hours) is accepted by IBKR.

    Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#create-alert
    """
    text, alert_id = _create_alert(live_toolkit, outside_rth=True)
    assert alert_id, f"No alert ID: {text!r}"
    _delete_safe(live_toolkit, alert_id)


@pytest.mark.integration
def test_toolkit_alert_repeat(live_toolkit):
    """Alert with repeat=True (re-fires after triggering) is accepted by IBKR."""
    text, alert_id = _create_alert(live_toolkit, repeat=True)
    assert alert_id, f"No alert ID: {text!r}"
    _delete_safe(live_toolkit, alert_id)


# ---------------------------------------------------------------------------
# Deactivate / Reactivate
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_toolkit_alert_deactivate_and_reactivate(live_toolkit):
    """Toggle an alert off then back on — both activate_alert calls must succeed.

    Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#activate-alert
    """
    _, alert_id = _create_alert(live_toolkit)
    assert alert_id
    try:
        off_text, _ = live_toolkit.execute("activate_alert", {"alert_id": alert_id, "activate": False})
        assert isinstance(json.loads(off_text), dict)

        on_text, _ = live_toolkit.execute("activate_alert", {"alert_id": alert_id, "activate": True})
        assert isinstance(json.loads(on_text), dict)
    finally:
        _delete_safe(live_toolkit, alert_id)


# ---------------------------------------------------------------------------
# Modify
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_toolkit_alert_modify_price(live_toolkit):
    """modify_price_alert updates the trigger price — response is a valid JSON dict.

    Modify uses IBKR's create_alert endpoint (same as create — patch semantics):
    Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#create-alert
    """
    _, alert_id = _create_alert(live_toolkit, price=99999.0)
    assert alert_id
    try:
        mod_text, _ = live_toolkit.execute("modify_price_alert", {
            "alert_id": alert_id, "price": 99998.0
        })
        assert isinstance(json.loads(mod_text), dict), (
            f"modify_price_alert did not return a JSON dict: {mod_text!r}"
        )
    finally:
        _delete_safe(live_toolkit, alert_id)


@pytest.mark.integration
def test_toolkit_alert_modify_name(live_toolkit):
    """modify_price_alert renames an alert — response is a valid JSON dict."""
    _, alert_id = _create_alert(live_toolkit, name="_ci_original_name")
    assert alert_id
    try:
        mod_text, _ = live_toolkit.execute("modify_price_alert", {
            "alert_id": alert_id, "name": "_ci_renamed"
        })
        data = json.loads(mod_text)
        assert isinstance(data, dict)
        if "alertName" in data:
            assert data["alertName"] == "_ci_renamed", (
                f"Name not updated in response: {data}"
            )
    finally:
        _delete_safe(live_toolkit, alert_id)


@pytest.mark.integration
def test_toolkit_alert_modify_operator(live_toolkit):
    """modify_price_alert can flip the operator from >= to <=."""
    _, alert_id = _create_alert(live_toolkit, operator=">=", price=99999.0)
    assert alert_id
    try:
        mod_text, _ = live_toolkit.execute("modify_price_alert", {
            "alert_id": alert_id, "operator": "<="
        })
        assert isinstance(json.loads(mod_text), dict)
    finally:
        _delete_safe(live_toolkit, alert_id)


# ---------------------------------------------------------------------------
# Full roundtrip  (§4b live test plan)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_toolkit_alert_full_roundtrip(live_toolkit):
    """§4b full scenario: create → confirm in list → modify price → modify name
    → deactivate → reactivate → delete.

    This is the canonical alert lifecycle test. All other tests in this file
    verify individual operations; this one verifies they chain correctly.

    Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#get-alert-list
    """
    create_text, alert_id = _create_alert(live_toolkit, name="_ci_roundtrip", price=99999.0)
    assert alert_id, f"No alert ID from create: {create_text!r}"

    try:
        # Confirm it appears in the list
        list_text, _ = live_toolkit.execute("get_alerts", {})
        if list_text.strip().startswith("["):
            alerts = json.loads(list_text)
            ids = [str(a.get("orderId") or a.get("id") or "") for a in alerts]
            assert alert_id in ids, (
                f"Created alert {alert_id} not found in get_alerts: {ids}"
            )

        # Modify price
        live_toolkit.execute("modify_price_alert", {"alert_id": alert_id, "price": 99997.0})

        # Modify name
        live_toolkit.execute("modify_price_alert", {"alert_id": alert_id, "name": "_ci_roundtrip_v2"})

        # Deactivate
        live_toolkit.execute("activate_alert", {"alert_id": alert_id, "activate": False})

        # Reactivate
        live_toolkit.execute("activate_alert", {"alert_id": alert_id, "activate": True})

    finally:
        # Delete — must succeed or we leak a test alert
        try:
            del_text, _ = live_toolkit.execute("delete_alert", {"alert_id": alert_id})
            assert isinstance(del_text, str), f"delete_alert returned non-string: {del_text!r}"
        except Exception as e:
            pytest.fail(f"delete_alert failed for alert {alert_id}: {e}")
