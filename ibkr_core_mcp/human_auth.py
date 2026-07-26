"""Gate 1 of the order-write security model: Touch ID / Face ID.

`require_touch_id()` blocks on Apple's LocalAuthentication framework and raises
`HumanAuthError` on any failure, denial, cancellation, or timeout (60s). It is
called by `IBKRClient`'s order write methods before Gate 2 (the visual confirmation
dialog in `order_confirm.py`) and before any request reaches IBKR.

The policy is `LAPolicyDeviceOwnerAuthentication`: biometrics first, falling back
to the device password if the biometric read genuinely fails. That fallback is
Apple's own recovery path, not a bypass added here — the stricter biometrics-only
policy was evaluated and rejected because a failed scan under it leaves the user no
recovery at all. There is deliberately no bypass flag and no caching of a prior
success; every gated call re-authenticates. Do not add one.

https://developer.apple.com/documentation/localauthentication/lapolicy
"""

from __future__ import annotations

import threading
from typing import Any

from ibkr_core_mcp.exceptions import HumanAuthError

_TIMEOUT = 60


def require_touch_id(reason: str) -> None:
    """Block until Touch ID succeeds. Raises HumanAuthError on any failure."""
    if not reason or not reason.strip():
        raise HumanAuthError("require_touch_id: reason must be a non-empty string")
    try:
        from LocalAuthentication import (
            LAContext,
            LAPolicyDeviceOwnerAuthentication,
        )
    except (ImportError, TypeError):
        raise HumanAuthError("Touch ID unavailable: pyobjc-framework-LocalAuthentication not installed") from None

    # LAPolicyDeviceOwnerAuthentication: tries Touch ID first, falls back to
    # system password if the biometric scan fails or is cancelled.
    # LAPolicyDeviceOwnerAuthenticationWithBiometrics (biometrics-only) was
    # rejected immediately on a failed scan with no recovery path.
    ctx = LAContext.new()
    can_eval, err = ctx.canEvaluatePolicy_error_(LAPolicyDeviceOwnerAuthentication, None)
    if not can_eval:
        raise HumanAuthError(f"Touch ID unavailable: {err}")

    done = threading.Event()
    result: dict[str, Any] = {}

    def _reply(success: bool, error: object) -> None:
        result["ok"] = success
        result["error"] = error
        done.set()

    ctx.evaluatePolicy_localizedReason_reply_(LAPolicyDeviceOwnerAuthentication, reason, _reply)

    if not done.wait(timeout=_TIMEOUT):
        raise HumanAuthError(f"Touch ID timed out after {_TIMEOUT}s")
    if not result.get("ok"):
        raise HumanAuthError(f"Touch ID denied: {result.get('error')!r}")
