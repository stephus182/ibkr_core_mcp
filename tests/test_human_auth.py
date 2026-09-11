import re as _re
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path as _Path
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


# ---------------------------------------------------------------------------
# Touch ID reason grammar (gap #25, found 2026-08-13 at all five call sites).
#
# macOS composes the prompt as "<App> is trying to " + localizedReason
# (human_auth.py, evaluatePolicy_localizedReason_reply_). Every reason began with
# the noun phrase "IBKR: ", producing "Python is trying to IBKR: Cancel order 8001."
# Cosmetic in effect, but it is the Gate 1 biometric prompt — the surface whose whole
# job is to state plainly what is about to happen.
#
# Scanned from source rather than by invoking the five client methods: this must cover
# the CLASS, so a call site added later is caught without anyone remembering to
# extend a fixture.
# ---------------------------------------------------------------------------


def _touch_id_reasons() -> list[str]:
    src = (_Path(__file__).parent.parent / "ibkr_core_mcp" / "client.py").read_text()
    return _re.findall(r'require_touch_id\(\s*f?"([^"]*)"', src)


def test_touch_id_call_sites_are_discoverable():
    reasons = _touch_id_reasons()
    assert len(reasons) >= 5, f"expected the known Gate 1 call sites, found {reasons}"


def test_every_touch_id_reason_completes_the_system_prompt_grammatically():
    for reason in _touch_id_reasons():
        rendered = f"Python is trying to {reason}."
        assert not _re.match(r"^[A-Za-z]+:", reason), f"reason starts with a label prefix, rendering: {rendered!r}"
        assert reason[:1].islower(), (
            f"reason must begin with a lowercase verb completing 'is trying to', rendering: {rendered!r}"
        )


# ---------------------------------------------------------------------------
# One authorization per order write (claudia_ui gap #47, user rule 2026-09-11)
# ---------------------------------------------------------------------------


def test_authorization_covers_its_own_scope_until_it_expires(monkeypatch):
    """One fingerprint covers one transaction for a bounded time, and nothing else."""
    from ibkr_core_mcp import human_auth

    now = [1000.0]
    monkeypatch.setattr("ibkr_core_mcp.human_auth.time.monotonic", lambda: now[0])
    auth = human_auth.OrderWriteAuthorization(scope="place:abc", label="BUY 1 ES", granted_at=1000.0, ttl_s=300.0)
    assert auth.covers("place:abc")
    assert not auth.covers("place:abd")  # a different order
    assert not auth.covers("modify:1:abc")  # a different action
    now[0] = 1299.0
    assert auth.covers("place:abc") and not auth.expired
    now[0] = 1300.0
    assert auth.expired and not auth.covers("place:abc")


def test_authorize_order_write_is_touch_id_then_a_frozen_value(monkeypatch):
    """Gate 1 exactly as before, then a frozen token — and no module state appears."""
    from ibkr_core_mcp import human_auth

    calls: list[str] = []
    monkeypatch.setattr(human_auth, "require_touch_id", lambda reason: calls.append(reason))
    monkeypatch.setattr("ibkr_core_mcp.human_auth.time.monotonic", lambda: 42.0)
    auth = human_auth.authorize_order_write("place an IBKR order — BUY 1 ES", "place:abc", "BUY 1 ES")
    assert calls == ["place an IBKR order — BUY 1 ES"]
    assert auth == human_auth.OrderWriteAuthorization("place:abc", "BUY 1 ES", 42.0, 300.0)
    with pytest.raises(FrozenInstanceError):
        auth.scope = "other"  # type: ignore[misc]
    assert not any(isinstance(v, human_auth.OrderWriteAuthorization) for v in vars(human_auth).values()), (
        "an authorization must never be held at module level"
    )


def test_authorize_order_write_grants_nothing_when_touch_id_is_denied(monkeypatch):
    """A refused fingerprint raises before any value exists."""
    from ibkr_core_mcp import human_auth

    def deny(reason: str) -> None:
        raise HumanAuthError("Touch ID denied")

    monkeypatch.setattr(human_auth, "require_touch_id", deny)
    with pytest.raises(HumanAuthError):
        human_auth.authorize_order_write("place an IBKR order — BUY 1 ES", "place:abc", "BUY 1 ES")
