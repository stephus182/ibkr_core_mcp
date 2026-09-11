"""Gate 1 of the order-write security model: Touch ID / Face ID.

`require_touch_id()` blocks on Apple's LocalAuthentication framework and raises
`HumanAuthError` on any failure, denial, cancellation, or timeout (60s). It is
called by `IBKRClient`'s order write methods before Gate 2 (the visual confirmation
dialog in `order_confirm.py`) and before any request reaches IBKR.

The policy is `LAPolicyDeviceOwnerAuthentication`: biometrics first, falling back
to the device password if the biometric read genuinely fails. That fallback is
Apple's own recovery path, not a bypass added here — the stricter biometrics-only
policy was evaluated and rejected because a failed scan under it leaves the user no
recovery at all.

There is deliberately no bypass flag and no *cache* of a prior success — nothing that
lets a later, unrelated write ride on an earlier fingerprint. An `OrderWriteAuthorization`,
granted by `client._authorize_order_write`, is not that: it is one authorization for one
write, bound to that write's own data and to a 300 s window, held only by the call chain
that earned it, checked identically at the write and at every reply, and expiring closed.
The precaution replies IBKR sends for that same write validate through their dialogs
without a second fingerprint — the user's rule (2026-09-11), matching IBKR Mobile and TWS,
which ask for one biometric per placement, modification or cancellation. The standards say
the same: the unit of authorization is the transaction (OWASP Transaction Authorization
1.5, EU RTS 2018/389 Art. 5); intent is an explicit button, not a biometric (NIST SP
800-63B-4 "Authentication Intent"); repeated approval prompts are a named threat (NIST
"Authentication Fatigue", CISA "push fatigue"). Sources and quotes: claudia_ui
`docs/api-reference.md` § Order authorization. Do not add a cache; do not make an
authorization global; do not let a reply skip its dialog.

https://developer.apple.com/documentation/localauthentication/lapolicy
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

from ibkr_core_mcp.exceptions import HumanAuthError

_TIMEOUT = 60

# How long one Gate 1 covers one order write. Justified on our own measurements, not on
# a vendor number (Apple's reuse constant page prints no value): each reply dialog
# auto-cancels at 60 s, the longest chain seen is three replies (2026-09-10), and IBKR
# requires the chain to run back-to-back — 300 s covers three dialogs at their limit plus
# latency, and sits well inside NIST SP 800-63B-4's tightest inactivity timeout (15 min).
ORDER_WRITE_AUTHORIZATION_TTL_S = 300.0


@dataclass(frozen=True)
class OrderWriteAuthorization:
    """One human authorization for one order write, bound to that write's own data.

    Created by `client._authorize_order_write` immediately after a successful Touch ID — the
    one seam every Gate 1 prompt in this package goes through — and passed
    *down* the call chain that needed it — `place_order_and_confirm` → `place_order` →
    `_resolve_one_reply` — so the precaution replies IBKR sends for that same write do not
    each demand a fresh fingerprint. It lives only in that call frame: no module state, no
    attribute on the client, nothing persisted, nothing shared across actions. That is the
    difference between an authorization and the cache this module refuses.

    `scope` is the transaction's own data (`client._order_write_scope`): the canonical body
    about to be sent, hashed — a body altered after the fingerprint is a different scope and
    `covers()` is False. The write and every reply run the same `covers(scope)` check with
    the scope the chain computed from the body it sent. `label` is the one-line order
    description the reply dialogs put in their title. Expiry fails closed: the holder
    prompts again.

    Why once per write: the user's rule (2026-09-11), matching IBKR Mobile and TWS, and
    what the standards describe — see the module docstring.

    What it is not a defence against: in-process code. Anything running inside this
    process can construct one by hand and pass it to `place_order` — the same power it
    already had to monkeypatch `require_touch_id` or call `_post` directly. The gates guard
    against the model (no tool reaches a write) and against automation acting without a
    human; they never guarded the process against its own code, and this value does not
    change that boundary.
    """

    scope: str
    label: str
    granted_at: float
    ttl_s: float

    @property
    def expired(self) -> bool:
        """True once the window has passed — the holder must prompt again."""
        return (time.monotonic() - self.granted_at) >= self.ttl_s

    def covers(self, scope: str) -> bool:
        """True only for the same transaction inside the window."""
        return scope == self.scope and not self.expired


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
