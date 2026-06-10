import sys
from unittest.mock import MagicMock, patch

import pytest

from ibkr_core_mcp import HumanAuthError as _HumanAuthErrorPublic
from ibkr_core_mcp.exceptions import HumanAuthError, IBKRCoreError

# ---------------------------------------------------------------------------
# Exception class
# ---------------------------------------------------------------------------

def test_human_auth_error_is_ibkr_core_error():
    err = HumanAuthError("denied")
    assert isinstance(err, IBKRCoreError)
    assert str(err) == "denied"


def test_human_auth_error_exported_from_package():
    assert _HumanAuthErrorPublic is HumanAuthError


# ---------------------------------------------------------------------------
# require_touch_id
# ---------------------------------------------------------------------------

def _make_la_mock(can_eval=True, eval_err=None, reply_success=True, reply_error=None):
    """Build a LocalAuthentication sys.modules mock."""
    mock_ctx = MagicMock()
    mock_ctx.canEvaluatePolicy_error_.return_value = (can_eval, eval_err)

    def fake_evaluate(policy, reason, reply):
        reply(reply_success, reply_error)

    mock_ctx.evaluatePolicy_localizedReason_reply_.side_effect = fake_evaluate
    mock_la = MagicMock()
    mock_la.LAContext.new.return_value = mock_ctx
    mock_la.LAPolicyDeviceOwnerAuthenticationWithBiometrics = 2
    return mock_la


def test_require_touch_id_success(monkeypatch):
    mock_la = _make_la_mock(can_eval=True, reply_success=True)
    monkeypatch.setitem(sys.modules, "LocalAuthentication", mock_la)
    from ibkr_core_mcp.human_auth import require_touch_id
    require_touch_id("Test order")  # must not raise


def test_require_touch_id_reason_forwarded(monkeypatch):
    mock_la = _make_la_mock(can_eval=True, reply_success=True)
    monkeypatch.setitem(sys.modules, "LocalAuthentication", mock_la)
    from ibkr_core_mcp.human_auth import require_touch_id
    require_touch_id("IBKR: Place order — BUY 100 AAPL")
    call_args = mock_la.LAContext.new.return_value.evaluatePolicy_localizedReason_reply_.call_args
    assert call_args[0][1] == "IBKR: Place order — BUY 100 AAPL"


def test_require_touch_id_denied(monkeypatch):
    mock_la = _make_la_mock(can_eval=True, reply_success=False, reply_error="User cancelled")
    monkeypatch.setitem(sys.modules, "LocalAuthentication", mock_la)
    from ibkr_core_mcp.human_auth import require_touch_id
    with pytest.raises(HumanAuthError, match="Touch ID denied"):
        require_touch_id("Test order")


def test_require_touch_id_unavailable(monkeypatch):
    mock_la = _make_la_mock(can_eval=False, eval_err="No enrolled fingers")
    monkeypatch.setitem(sys.modules, "LocalAuthentication", mock_la)
    from ibkr_core_mcp.human_auth import require_touch_id
    with pytest.raises(HumanAuthError, match="Touch ID unavailable"):
        require_touch_id("Test order")


def test_require_touch_id_not_installed(monkeypatch):
    monkeypatch.setitem(sys.modules, "LocalAuthentication", None)
    from ibkr_core_mcp.human_auth import require_touch_id
    with pytest.raises(HumanAuthError, match="not installed"):
        require_touch_id("Test order")


def test_require_touch_id_timeout(monkeypatch):
    mock_ctx = MagicMock()
    mock_ctx.canEvaluatePolicy_error_.return_value = (True, None)
    mock_ctx.evaluatePolicy_localizedReason_reply_.side_effect = lambda p, r, cb: None
    mock_la = MagicMock()
    mock_la.LAContext.new.return_value = mock_ctx
    mock_la.LAPolicyDeviceOwnerAuthenticationWithBiometrics = 2
    monkeypatch.setitem(sys.modules, "LocalAuthentication", mock_la)

    from ibkr_core_mcp.human_auth import require_touch_id
    with patch("ibkr_core_mcp.human_auth.threading.Event") as mock_event_cls:
        mock_event = MagicMock()
        mock_event.wait.return_value = False
        mock_event_cls.return_value = mock_event
        with pytest.raises(HumanAuthError, match="timed out"):
            require_touch_id("Test order")
