"""The authoritative state of the IBKR gateway session — one owner, one answer.

Moved into this package on 2026-11-09 (register F45, step 2) from the consumer that wrote it
on 2026-08-06, with its tests as the specification of the move. The file is layered, and the
layering is deliberate:

* **Pure.** `SessionPhase`, `SessionState`, `classify`, `observe`, `declare`, `describe` and
  `GatewaySession`'s holder half — no I/O of any kind, so the rules can be exhaustively tested
  before anything depends on them.
* **Acts.** `SuspendLock`, `_establish`, `_recover`, `release_session` — the only code in this
  package permitted to drive a login, post to a session endpoint or mutate the container.
* **Polls.** `GatewaySession.start/stop`, `_poll_once` and `attempt_soft_recovery` — the
  background read every other component subscribes to, and the last session-affecting write.

Everything from the acting layer down performs blocking I/O and must be called via
`asyncio.to_thread` from an event loop.

## The problem this exists to solve

Several independent actors touch the gateway on their own timers — a host's pollers and its
WebSocket, its model's tools, a keepalive loop, the manager, a reset by hand. Between them they
issued session-affecting writes from three modules and mutated the container from two, and
fixing one participant kept revealing the next gap, because there was no place where an
invariant could be stated. Six such gaps were found in one day (2026-08-06), each *after* the
previous fix — including one where the pre-flight ran after the container it was inspecting
had already been destroyed.

## The fact the whole design turns on

> "If the gateway has not received **any requests** for several minutes an open session will
> automatically timeout."
> — https://www.interactivebrokers.com/docs/web-api/v1/endpoints/session/ping-the-server.md

Renewal is not a tickler's job: *every* request renews the session. A 15-second poller alone
keeps one alive indefinitely without a single `/tickle`. That is why `POST /logout` could not
clear the borrowed session diagnosed on 2026-08-05 — three ticklers, a poller and a
reconnecting WebSocket were all renewing the very session being cleared — and why `SUSPENDED`
has to mean *everything*: a single actor left running during recovery is enough to defeat it.

## The states

| Phase | Meaning | Who may talk to the gateway |
|---|---|---|
| `UNREAD` | no reading yet — the initial state, left on the first read and never re-entered | not suspended, so any actor may try; no figure is vouched for (`is_live` is false) |
| `DOWN` | container not running, or the Java process is not answering | nobody |
| `FREE` | reachable, holds no session — the only state a login may start from | owner reads |
| `AUTHENTICATING` | login page open, user at 2FA | **owner reads only** |
| `LIVE` | authenticated, connected, **and confirmed against a data endpoint** | everyone |
| `DEGRADED` | authenticated but the data half is dark | owner reads |
| `BORROWED` | the gateway holds an SSO session issued to another IBKR app | owner reads |
| `CONTESTED` | another client is competing for the single brokerage session | owner reads |
| `RECOVERING` | a session is deliberately being cleared | **nobody, ticklers included** |

`DEGRADED` exists because the brokerage half and the data half are **documented as
independent** and have been **observed diverging** — on 2026-08-04 `/portfolio/{id}/ledger`
served live figures while `/iserver/account/orders` returned HTTP 400
`{"error": "Bad Request: no bridge"}`.

⚠ **`hmds: {"error": "no bridge"}` in the `/tickle` body is NOT a market-data outage, and must
not be wired to this state.** Measured 2026-08-06 on a fully healthy session: `authenticated:
true`, `connected: true`, `hmds: {"error": "no bridge"}` — and at the same moment
`/iserver/marketdata/history` returned real bars and `/iserver/marketdata/snapshot` live quotes.
(The same measurement settled that the **first** `/iserver/marketdata/snapshot` call after a
subscription returns only `conid` with no fields; calls 2 and 3 carry the quote.)

## Why `LIVE` requires a data call and not a flag

`authStatus.authenticated` describes the **brokerage** session. The portfolio endpoints are a
different subsystem with a different prerequisite — IBKR documents it as *"/portfolio/accounts
or /portfolio/subaccounts must be called prior to this endpoint"*
(https://www.interactivebrokers.com/docs/web-api/v1/endpoints/portfolio/portfolio-ledger.md) —
and the two have been observed disagreeing in both directions. So `LIVE` is only reachable with
positive confirmation from a real data call (`preflight.confirm_session`), which is also that
documented prerequisite: one call discharges both obligations. `classify` therefore takes
`data_ok` as a required argument, with no default: forgetting to confirm must be a `TypeError`,
not a silent `LIVE`.

## Security conditions held here (register F45)

Every URL a function here sends to passes `require_loopback_url` first (condition C,
`tests/security/test_tls_policy.py`); every exception rendered into a reading or a log line
passes `redact_error` (condition G); the suspend lock is written 0600 in a 0700 directory and a
lock naming a pid below 1 is malformed, never active (condition E); `compete` is a `Final`
False spelled once (condition F). `ssodh/init` and `/logout` are posted from this module and
nowhere else in the package (`tests/security/test_gateway_boundary.py`); each of the three
session writes — the logout, the soft recovery, the restart that clears a session — leaves one
redacted `session_write` record in the audit log (MCP security checklist 8.1).
"""

from __future__ import annotations

import asyncio
import ctypes
import json
import logging
import os
import time
import warnings
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Final, Protocol

import requests
import urllib3

from ibkr_core_mcp import audit
from ibkr_core_mcp.config import require_loopback_url
from ibkr_core_mcp.exceptions import RestartRefusedError
from ibkr_core_mcp.gateway.manager import read_login_events
from ibkr_core_mcp.gateway.preflight import (
    _VALIDATING_GUIDANCE,
    REFUSED_GUIDANCE,
    GatewayState,
    LastLogin,
    LoginEvent,
    confirm_session,
    gateway_api_url,
    last_login,
    read_state,
)
from ibkr_core_mcp.redaction import redact_error

log = logging.getLogger(__name__)


class SessionPhase(StrEnum):
    """The nine states a gateway session can be in.

    A `StrEnum` so a phase renders readably in a log line and compares to a literal in a test
    without `.value` ceremony.

    Six are *observed* — `classify` derives them from a reading. Two are *declared*:
    `AUTHENTICATING` and `RECOVERING` describe an operation the owner is performing and cannot
    be read off the wire, because the gateway looks identical during a login it is waiting on
    and a login nobody has started.

    One is neither: `UNREAD`, the holder's initial state, meaning *no reading exists yet*. It is
    a one-way door — nothing can publish it, because `classify` never returns it and `declare`
    refuses it — so a consumer that sees any other phase knows it came from evidence. The
    initial state used to be `DOWN`, a claim about the gateway made with no evidence at all,
    and a host's first connectivity poll, landing before the first read, turned it into "the
    gateway is disconnected — log in" on every start.
    """

    UNREAD = "unread"

    DOWN = "down"
    FREE = "free"
    AUTHENTICATING = "authenticating"
    LIVE = "live"
    DEGRADED = "degraded"
    BORROWED = "borrowed"
    CONTESTED = "contested"
    RECOVERING = "recovering"


# The phases in which *nothing* may touch the gateway — not the pollers, not the WebSocket,
# not the ticklers, not a model's tools. Total, with no carve-outs, and that is the decision
# rather than an oversight: because any request renews the session, an exception for "just
# the agent" or "just the keepalive" reintroduces precisely the traffic that made
# `POST /logout` unable to clear a borrowed session on 2026-08-05.
_SUSPENDED_PHASES = frozenset({SessionPhase.AUTHENTICATING, SessionPhase.RECOVERING})

# The phases in which account data may be requested at all. Only one qualifies: `LIVE` is
# defined as "authenticated, connected and confirmed", which is exactly the condition under
# which a figure on screen can be vouched for.
_DATA_PHASES = frozenset({SessionPhase.LIVE})

POLL_INTERVAL = 60.0
"""Seconds between session reads.

Matches IBKR's *"It is expected to call this endpoint approximately every 60 seconds"*
(https://www.interactivebrokers.com/docs/web-api/v1/endpoints/session/ping-the-server.md). The
read is a `/tickle`, so polling and renewing are the same act — which is the whole reason the
suspend lock has to cover this loop too.
"""

COMPETE: Final = False
"""What `attempt_soft_recovery` posts as `compete` to `ssodh/init` — and must keep posting.

`compete: true` force-evicts a concurrent IBKR Mobile or TWS session; only one brokerage
session exists per username, so eviction is a real consequence, not a theoretical one. The
value is annotated `Final` so a later assignment is a type error, spelled here once, and
held by `tests/test_gateway_session.py` in source and on the wire (register F45, condition F).
"""


@dataclass(frozen=True)
class SessionState:
    """One reading of the session, with the evidence it was derived from.

    `as_of` is **when the evidence was obtained**, never when the loop last woke up. A failed
    read must carry the previous `as_of` forward (see `stale_copy`) so age keeps growing
    instead of being masked by a fresh timestamp: on a trading surface, stale data that looks
    current is the worst available failure.

    `gateway` is the raw `GatewayState` the phase was derived from, kept so a caller can
    explain a decision using the evidence it was actually made on. Re-reading to explain a
    decision would describe a different instant, which is how contradictory messages get
    written. It is None only for a declared phase, where there is no reading.
    """

    phase: SessionPhase
    as_of: datetime
    detail: str = ""
    gateway: GatewayState | None = None
    data_ok: bool | None = None

    def age_seconds(self, now: datetime | None = None) -> float:
        """Seconds since this state's evidence was obtained. Never negative."""
        return max(0.0, ((now or datetime.now(UTC)) - self.as_of).total_seconds())

    @property
    def is_live(self) -> bool:
        """Whether account data may be requested and trusted right now."""
        return self.phase in _DATA_PHASES

    @property
    def is_suspended(self) -> bool:
        """Whether **all** gateway traffic is currently forbidden.

        The predicate every actor checks before issuing any request, including the ticklers
        whose entire purpose is to issue requests.
        """
        return self.phase in _SUSPENDED_PHASES

    @property
    def may_call_ibkr(self) -> bool:
        """Whether an actor is permitted to make any gateway call at all.

        Distinct from `is_live`, and the distinction is load-bearing. `is_live` gates actors
        that need *data* — a dashboard poller, an execution listener. This gates actors that
        merely need *reachability*, including a model's tools: a tool call against a `FREE`
        gateway simply 401s and the error is informative, whereas the same call during
        `AUTHENTICATING` is renewal traffic aimed at the session being established.
        """
        return not self.is_suspended

    def stale_copy(self, detail: str) -> SessionState:
        """Copy of this state with a new reason attached and **`as_of` unchanged**.

        What the owner publishes when a read fails: the phase and evidence are the last ones
        actually established, and the age keeps growing. There is deliberately **no `now`
        parameter**: an ignored one would be a trap, since a caller passing `now=` would
        reasonably expect it to land in `as_of`, the single thing this method leaves alone.
        """
        return replace(self, detail=detail)


def classify(state: GatewayState, data_ok: bool) -> SessionPhase:
    """Map one gateway reading plus a data-endpoint result to an observed phase.

    Pure, total, and the single definition of what a reading *means*. The ordering below
    deliberately matches `preflight.verdict` step for step, so the two can never disagree about
    the same reading — held over the full cross-product of their fields by
    `tests/test_gateway_session.py`. In particular `authenticated and connected` is tested
    **before** `competing`, exactly as `verdict` does: a session that works is working,
    whatever else is claiming it.

    Args:
        state: The reading, from `preflight.read_state`.
        data_ok: Whether a real data endpoint answered. **Required, with no default** — `LIVE`
            is unreachable without positive confirmation, and a defaulted argument would let a
            caller who forgot to confirm silently obtain it. Pass False whenever the check has
            not been made; the result is `DEGRADED`, which is honest, and which no consumer
            treats as usable.

    Returns:
        One of the six *observed* phases. `AUTHENTICATING` and `RECOVERING` are declared by the
        owner and are never returned here.
    """
    if not state.reachable:
        return SessionPhase.DOWN
    if state.authenticated and state.connected:
        return SessionPhase.LIVE if data_ok else SessionPhase.DEGRADED
    if state.competing or state.collision:
        return SessionPhase.CONTESTED
    if state.sso_valid and state.client_app and not state.authenticated:
        return SessionPhase.BORROWED
    return SessionPhase.FREE


# Human-readable reasons, one per observed phase. Held here rather than built at the call site
# so the wording cannot drift between a status light, a chat line and the command line.
_PHASE_DETAIL = {
    SessionPhase.UNREAD: "The session has not been read yet.",
    SessionPhase.DOWN: "The gateway process is not answering.",
    SessionPhase.FREE: "No session — a login now should succeed.",
    SessionPhase.LIVE: "Authenticated and confirmed against a data endpoint.",
    SessionPhase.DEGRADED: "Authenticated, but the data half is not answering.",
    SessionPhase.BORROWED: "The gateway holds a session issued to another IBKR app.",
    SessionPhase.CONTESTED: "Another IBKR client is competing for the session.",
    SessionPhase.AUTHENTICATING: "A login is in progress — all gateway traffic suspended.",
    SessionPhase.RECOVERING: "Clearing the session — all gateway traffic suspended.",
}


def describe(phase: SessionPhase, state: GatewayState | None = None) -> str:
    """The one-line reason for a phase, naming the other app when one is known."""
    detail = _PHASE_DETAIL[phase]
    if phase is SessionPhase.BORROWED and state is not None and state.client_app:
        return f"The gateway holds a session issued to {state.client_app}."
    return detail


def observe(state: GatewayState, data_ok: bool, now: datetime | None = None) -> SessionState:
    """Build a complete `SessionState` from a reading. The normal way to make one."""
    phase = classify(state, data_ok)
    return SessionState(
        phase=phase,
        as_of=now or datetime.now(UTC),
        detail=describe(phase, state),
        gateway=state,
        data_ok=data_ok,
    )


def declare(phase: SessionPhase, now: datetime | None = None) -> SessionState:
    """Build a state for a *declared* phase — one the owner is causing, not reading.

    Only `AUTHENTICATING` and `RECOVERING` may be declared. Every other phase is a claim about
    the gateway and must come from evidence, so declaring one would be a way to assert `LIVE`
    without having confirmed it — the exact hole `classify`'s mandatory `data_ok` closes.
    """
    if phase not in _SUSPENDED_PHASES:
        raise ValueError(
            f"{phase} cannot be declared: an observed phase must come from `observe()`, "
            f"and `unread` is only ever the initial state. Only "
            f"{sorted(p.value for p in _SUSPENDED_PHASES)} may be declared."
        )
    return SessionState(phase=phase, as_of=now or datetime.now(UTC), detail=describe(phase))


@dataclass
class GatewaySession:
    """Holds the current `SessionState` and notifies subscribers when the phase changes.

    The holder half: no polling, no writes, no I/O. `establish()` and `recover()` are the
    **only** entry points in this package that open a login page or mutate a container holding
    a session.

    Subscribers fire on **phase transitions only**, never on every republish: a notification
    repeated every poll trains the reader to dismiss it. A republish that carries a new
    `detail` but the same phase is still the same situation.
    """

    _state: SessionState = field(
        default_factory=lambda: SessionState(
            phase=SessionPhase.UNREAD,
            as_of=datetime.now(UTC),
            detail=describe(SessionPhase.UNREAD),
        )
    )
    _subscribers: list[Callable[[SessionState], None]] = field(default_factory=list)
    _task: asyncio.Task[None] | None = None
    _poll_url: str | None = None
    _interval: float = POLL_INTERVAL

    def state(self) -> SessionState:
        """The current state. Synchronous, no I/O — safe from a UI callback.

        The state is a frozen dataclass replaced wholesale, so a reader can never observe a
        half-updated one: the attribute either still points at the old object or already
        points at the complete new one.
        """
        return self._state

    @property
    def phase(self) -> SessionPhase:
        """Shorthand for `state().phase`."""
        return self._state.phase

    def is_live(self) -> bool:
        """Whether account data may be requested and trusted. What pollers gate on."""
        return self._state.is_live

    def is_suspended(self) -> bool:
        """Whether all gateway traffic is forbidden. What *everything* gates on."""
        return self._state.is_suspended

    def may_call_ibkr(self) -> bool:
        """Whether any gateway call is permitted. What a model's tools gate on."""
        return self._state.may_call_ibkr

    def publish(self, state: SessionState) -> bool:
        """Replace the state, notifying subscribers if the phase changed.

        Returns whether the phase changed, so a caller can log a transition without re-deriving
        it. A subscriber that raises is logged (redacted) and skipped: one bad callback must
        not stop the others from being told the session went down, which is the moment they
        most need to know.
        """
        previous, self._state = self._state, state
        if previous.phase is state.phase:
            return False
        log.info(
            "Gateway session %s -> %s (%s)",
            previous.phase.value,
            state.phase.value,
            state.detail,
        )
        for callback in list(self._subscribers):
            try:
                callback(state)
            except Exception as exc:
                log.warning("Gateway session subscriber failed; continuing: %s", redact_error(exc))
        return True

    def read_now(self, url: str | None = None) -> SessionState:
        """Read the gateway, confirm the data half, publish and return the new state.

        Blocking HTTP — call via `asyncio.to_thread` from an event loop. Two GETs plus, when
        the brokerage session is up, the `/portfolio/accounts` confirmation that `LIVE`
        requires.

        A read that cannot reach the gateway publishes `DOWN` with a fresh `as_of`, because
        "unreachable" is itself an observation. A read that *succeeds* but finds the data half
        dark publishes `DEGRADED` — never `LIVE`.
        """
        api_url = url or gateway_api_url()
        reading = read_state(api_url)
        data_ok = False
        if reading.authenticated and reading.connected:
            data_ok, detail = confirm_session(api_url)
            state = observe(reading, data_ok)
            if not data_ok:
                state = replace(state, detail=f"{state.detail} ({detail})")
            self.publish(state)
            return self._state
        self.publish(observe(reading, data_ok))
        return self._state

    def establish(self, manager: GatewayManagerLike, **kwargs: object) -> SessionState:
        """Bring the session to `LIVE`, or explain why it cannot get there.

        The **only** entry point in this package that opens a login page or starts a
        container. See `_establish` for the ordering contract and the evidence behind it.
        """
        return _establish(self, manager, **kwargs)  # type: ignore[arg-type]

    def recover(self, manager: GatewayManagerLike, **kwargs: object) -> SessionState:
        """Clear an unusable session by restarting the container.

        The **only** entry point that mutates a container holding a session. Deliberately does
        not call `POST /logout` — see `_recover` for both reasons.
        """
        return _recover(self, manager, **kwargs)  # type: ignore[arg-type]

    # ── Background polling ────────────────────────────────────────────────────

    def start(self, url: str | None = None, interval: float = POLL_INTERVAL) -> None:
        """Begin polling the session. Idempotent; restarts a finished task.

        One task for the whole process, blocking work on a worker thread, and a synchronous
        cached read for every consumer.
        """
        if self._task is None or self._task.done():
            self._poll_url = url
            self._interval = interval
            self._task = asyncio.create_task(self._poll_loop())
            log.info("GatewaySession polling started (interval=%.0fs)", interval)

    def stop(self) -> None:
        """Cancel the polling task. Safe when polling was never started."""
        if self._task and not self._task.done():
            self._task.cancel()
            log.info("GatewaySession polling stopped")

    async def _poll_loop(self) -> None:
        """Poll immediately, then every `interval` seconds until cancelled.

        Every exception except `CancelledError` is logged and the loop continues: this loop is
        what every other component reads its connectivity from, so one bad response must not
        leave the whole host believing the gateway is unreachable forever.
        """
        try:
            await self._poll_once()
        except Exception as exc:
            log.warning("GatewaySession initial poll error: %s", redact_error(exc))
        while True:
            try:
                await asyncio.sleep(self._interval)
                await self._poll_once()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.warning("GatewaySession poll error: %s", redact_error(exc))

    async def _poll_once(self) -> None:
        """One read, plus the one narrowly-scoped write the owner is allowed to make.

        **Skipped entirely while suspended.** A poll is a `/tickle`, and a `/tickle` renews —
        so polling through a login or a recovery would be the owner defeating its own
        suspension, which is the failure mode the owner exists to remove.

        The soft-recovery step fires only on IBKR's documented signature *and* only from a
        previously-`LIVE` session: `connected` with `authenticated` false, after the session
        was working. Never on a settling login (that starts from `DOWN`/`FREE`) and never on a
        hard disconnect (`connected` false), because `ssodh/init` raises the bridge and cannot
        supply an authentication that never happened.
        """
        if self._state.is_suspended:
            return
        was_live = self._state.phase is SessionPhase.LIVE
        state = await asyncio.to_thread(self.read_now, self._poll_url)
        if (
            was_live
            and state.phase is not SessionPhase.LIVE
            and state.gateway is not None
            and state.gateway.connected
            and not state.gateway.authenticated
            and await asyncio.to_thread(attempt_soft_recovery, self._poll_url or gateway_api_url())
        ):
            log.info("GatewaySession: soft timeout recovered via ssodh/init")
            await asyncio.to_thread(self.read_now, self._poll_url)

    def subscribe(self, callback: Callable[[SessionState], None]) -> Callable[[], None]:
        """Register `callback` for phase transitions. Returns an unsubscribe callable.

        Unsubscribing is idempotent and safe from a torn-down UI session.
        """
        self._subscribers.append(callback)

        def unsubscribe() -> None:
            """Remove `callback`. Safe to call more than once."""
            if callback in self._subscribers:
                self._subscribers.remove(callback)

        return unsubscribe


# ══════════════════════════════════════════════════════════════════════════════
# The owner acts. Everything below performs I/O.
#
# These are the ONLY functions in the package permitted to mutate the gateway
# container or to drive a login. The pure layer above is what they are correct
# against.
# ══════════════════════════════════════════════════════════════════════════════


class LoginWindowLike(Protocol):
    """The handle `open_login_page()` returns when it opened a window of its own (register F44).

    A browser tab has no handle, so a manager may also return `None`.
    """

    def close(self) -> bool:
        """End the window; `False` when it was not ours to close."""
        ...


class GatewayManagerLike(Protocol):
    """The slice of `GatewayManager` the owner uses.

    A Protocol rather than the concrete class so the orchestration is testable without Docker.
    That matters more than usual here: the defect that started the owner was an *ordering* bug
    that returned a correct-looking value, so the tests have to observe the call sequence,
    which means the manager has to be substitutable.
    """

    def ensure_docker_running(self, timeout: int = ...) -> None:
        """Start the Docker daemon if it is not already up."""
        ...

    def is_running(self) -> bool:
        """Whether the gateway container is currently running."""
        ...

    def start(self, *, force: bool = False) -> None:
        """Start the gateway on a fresh Java process — a clean, unauthenticated session. A
        current container is restarted in place and keeps its log; any other is recreated
        (register F43). Guarded: a LIVE, REFUSED or VALIDATING session raises
        `RestartRefusedError` unless `force` (condition F)."""
        ...

    def restart(self, *, force: bool = False) -> None:
        """`start(force=force)`: a fresh process, so whatever session the container held is gone."""
        ...

    def wait_for_gateway(self, timeout: int = ..., poll_interval: int = ...) -> bool:
        """Block until the Java process answers HTTP. False on timeout."""
        ...

    def open_login_page(self) -> LoginWindowLike | None:
        """Open the login — a small window of its own when Chrome is found, else a browser
        tab, for which there is no handle (`None`)."""
        ...


DEFAULT_SUSPEND_LOCK = Path.home() / ".ibkr_core" / "session.suspend"
"""Where the cross-process suspend flag lives, beside `store.db` in the same directory.

The path is a contract: a host's installed keepalive reads it from outside this process,
under launchd with `$HOME` set (confirmed 2026-08-06 by a daemon logging `SUSPENDED` while a
lock was held, then `OK` once released), so it does not move.
"""

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
"""The one Win32 access right `_pid_alive` asks for: enough to open a handle, nothing more."""


def _pid_alive(pid: int, *, windows: bool | None = None, kernel32: Any = None) -> bool:
    """Whether process `pid` exists, without touching it.

    POSIX: `os.kill(pid, 0)` — signal 0 tests existence; `PermissionError` means alive and
    owned by another user. **Windows is different, and the difference is lethal:** there
    `os.kill` with any signal other than the two console events "will cause the process to be
    unconditionally killed by the TerminateProcess API"
    (https://docs.python.org/3/library/os.html#os.kill), so reading the lock would have killed
    its owner. On Windows the check is `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)`: a
    handle means alive and is closed at once; 0 means gone.

    A pid below 1 is never alive: 0 and negatives address process groups, and `os.kill(0, 0)`
    succeeds for this process's own group (register F45, condition E).

    Args:
        pid: The process id from the lock file.
        windows: Which branch to take; None reads `os.name`. A test seam.
        kernel32: The Win32 library to ask; None loads the real one. A test seam.
    """
    if pid < 1:
        return False
    on_windows = (os.name == "nt") if windows is None else windows
    if on_windows:
        if kernel32 is None:
            windll: Any = getattr(ctypes, "windll", None)  # exists on Windows only; typed Any for mypy elsewhere
            kernel32 = windll.kernel32
        handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@dataclass
class SuspendLock:
    """A cross-process "do not touch the gateway" flag.

    Renewers live in different runtimes — a keepalive loop on the host (this package's own,
    or a host's) and the owner's poll inside the host process — and other hosts may run their
    own. No in-process mechanism can suspend all of them, so the flag has to be something every
    one of them can read cheaply. A file is the only such thing.

    ## Why a PID is written into it

    A lock that outlives the process holding it is worse than no lock: it would silently stop
    every tickler forever, and the symptom — sessions quietly timing out — looks nothing like
    its cause. So the owning PID is written in, and `is_active` treats a lock whose PID is gone
    as absent. A crash therefore degrades to "no suspension", which cannot be worse than no
    lock at all.

    ## Why it is not an OS file lock

    `flock` releases on process death, which sounds ideal, but a shell reader cannot test it
    without holding it. A plain file plus a liveness check is readable by `sh` in one line.

    ## Its mode

    0600, in a directory created 0700 (a directory that already exists keeps its mode — it is
    the store's to narrow). The lock sits beside the trade store in the operator's data
    directory, and nothing there is for another user (register F45, condition E).
    """

    path: Path = DEFAULT_SUSPEND_LOCK
    _held: bool = False

    def acquire(self, reason: str) -> None:
        """Write the flag. Idempotent — re-acquiring only refreshes the reason."""
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        payload = json.dumps({"pid": os.getpid(), "reason": reason, "since": datetime.now(UTC).isoformat()})
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(payload)
        self._held = True

    def release(self) -> None:
        """Remove the flag. Safe when it was never acquired or already gone.

        A release that fails is logged once, redacted — the path is under the operator's home
        directory, which must not appear in a log line in clear (invariant 6).
        """
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            log.warning("Could not release the gateway suspend lock: %s", redact_error(exc))
        self._held = False

    def __enter__(self) -> SuspendLock:
        """Support `with` use; acquire happens separately, with its reason."""
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Always release, including when the body raised.

        The lock suppresses every keepalive in the system, so leaking one on an exception would
        leave the session slowly dying with nothing on screen to explain it.
        """
        self.release()

    @classmethod
    def is_active(cls, path: Path = DEFAULT_SUSPEND_LOCK) -> bool:
        """Whether a **live** process is currently suspending gateway traffic.

        A lock naming a dead PID is stale and reported as inactive, so a crash cannot wedge the
        system. An unreadable or malformed lock — a pid below 1 included — is also treated as
        inactive: failing open matches the behaviour without a lock, whereas failing closed
        would silence every tickler because a file got truncated.
        """
        try:
            data = json.loads(path.read_text())
            pid = int(data["pid"])
        except (OSError, ValueError, KeyError, TypeError):
            return False
        return _pid_alive(pid)


def release_session(gateway_url_: str, timeout: float = 10.0) -> tuple[bool, str]:
    """`POST /logout` — make the gateway drop the session it is holding. Opt-in only.

    Deliberately **not** part of `read_state`: that function's contract is that it cannot
    change anything, and a check which might destroy a session is not a check. This is one of
    the two session writes in the package, it is reached only by an explicit `--release`, and
    it is never run automatically.

    ⚠ **Scope is NOT documented.** IBKR's page says exactly one thing — *"Logs the user out of
    the gateway session. Any further activity requires re-authentication."*
    (https://www.interactivebrokers.com/docs/web-api/v1/endpoints/session/logout-of-the-current-session.md)
    — and nothing about whether that cascades to a session held by TWS or IBKR Mobile. Only one
    brokerage session exists per username across Client Portal, TWS and IBKR Mobile
    (https://www.interactivebrokers.com/docs/web-api/authentication/multiple-sessions.md), so the
    *a priori* case for a cascade is real. Until someone deliberately tests it — with nothing
    at risk on the phone — treat a release as **potentially ending an IBKR Mobile session
    too**, and never run it while another app is being used to manage a live position.

    Returns:
        (released, detail). `released` reflects IBKR's own `status` field, not merely a 200 —
        the endpoint returns `{"status": true}` on success and the distinction matters when the
        point is to know whether the slot is actually free.

    Raises:
        ConfigError: `gateway_url_` is not a loopback host — before any request.
    """
    require_loopback_url(gateway_url_)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", urllib3.exceptions.InsecureRequestWarning)
            resp = requests.post(f"{gateway_url_}/logout", timeout=timeout, verify=False)  # noqa: S501 - localhost gateway, self-signed cert; pinned above (SECURITY.md § TLS Policy)
    except Exception as exc:
        audit.record("session_write", actor="operator", decision="error", outcome=type(exc).__name__, action="logout")
        return False, redact_error(exc)
    if resp.status_code != 200:
        audit.record(
            "session_write",
            actor="operator",
            decision="not_released",
            outcome=f"HTTP {resp.status_code}",
            action="logout",
        )
        return False, f"HTTP {resp.status_code}"
    try:
        released, detail = bool(resp.json().get("status")), resp.text.strip()
    except Exception:
        released, detail = False, resp.text.strip()[:120]
    audit.record(
        "session_write", actor="operator", decision="released" if released else "not_released", action="logout"
    )
    return released, detail


# Guidance attached to a login that never completed. It leads with the other-app collision
# because that is both the likeliest cause and the one the pre-flight is structurally unable
# to see: measured 2026-08-06, a live IBKR Mobile login left /tickle and /sso/validate
# answering 401 and the check reading FREE.
_LOGIN_INCOMPLETE_GUIDANCE = (
    "No confirmed session. Only one brokerage session exists per username, and a session "
    "held by TWS, IBKR Mobile or a Client Portal tab is NOT visible from here until the "
    "gateway holds one — so if the login was rejected rather than abandoned, that is the "
    "first thing to check. Nothing was retried and no second login page was opened. "
    "`python -m ibkr_core_mcp.gateway diagnose` prints the last login as the gateway's "
    "own log records it."
)

_CLOSE_THE_WINDOW = "  Close the login window (⌘Q on macOS)."
"""Said at every end of the wait but a validated one, when a window of our own was opened.
Operator 2026-10-13: a failed login's window is not auto-closed, so the failure can be
acknowledged. ⌘Q, not the red button: on macOS a closed window leaves its Chrome running
(measured), and the next login would open in that leftover, out of reach."""

_NOT_OURS_TO_CLOSE = (
    "  The login window was not ours to close — it had already closed, or it opened in a "
    "Chrome left from an earlier login. Close it yourself if it is still open (⌘Q on macOS)."
)


LoginReader = Callable[[], tuple[Sequence[LoginEvent] | None, str]]
"""How `_establish` reads the gateway's own log; `manager.read_login_events` by default."""


def _seen_login(read_login: LoginReader) -> tuple[bool, LastLogin | None]:
    """Whether the gateway's log could be read, and its newest login."""
    events, _problem = read_login()
    if events is None:
        return False, None
    return True, last_login(events)


def _establish(
    session: GatewaySession,
    manager: GatewayManagerLike,
    *,
    url: str | None = None,
    emit: Callable[[str], None] | None = None,
    open_login: bool = True,
    allow_restart: bool = False,
    reach_timeout: int = 120,
    login_timeout: float = 300.0,
    poll_interval: float = 5.0,
    lock: SuspendLock | None = None,
    sleep: Callable[[float], None] | None = None,
    monotonic: Callable[[], float] | None = None,
    read_login: LoginReader | None = None,
) -> SessionState:
    """Take the gateway from wherever it is to `LIVE`, or explain why it cannot get there.

    Implemented as a module function taking the session, rather than a method, purely so the
    whole sequence is visible in one place; `GatewaySession.establish` is the public entry
    point and simply calls this.

    ## The order is the contract

    1. Ensure Docker is running.
    2. Start the container **only if it is not already running**. A running container may hold
       a session and only a read is entitled to say whether it does — so it is never removed,
       restarted or otherwise touched before step 4. This is the exact defect the owner was
       written for: a host's button called `GatewayManager.start()`, which removed any
       existing container, *before* the pre-flight that was supposed to inspect it.
    3. Wait for the Java process to answer.
    4. Read and classify. A stopped or absent container cannot hold a session, so steps 2 and 3
       cannot have destroyed evidence.
    5. Open the login page **only** from `FREE`, and only with the suspend lock held. A window
       of our own (register F44) is closed at the first authenticated-and-connected reading
       and left open — with a line saying to close it — on every other end. No handle (a tab):
       the lines say "page".

    ## Why the lock wraps the login and not just the recovery

    Any request renews the session, so every actor must be silent while one is being
    established — pollers, the WebSocket, every tickler and a model's tools. Measured in the
    gateway's own log during a real login attempt on 2026-08-06, with a host running:

        13:12:25  ws /v1/api/ws -> {"message":"waiting for session"}
        13:12:26  GET /v1/api/portfolio/{accountId}/ledger,401
        13:12:30  GET /v1/api/portfolio/{accountId}/positions/0,401

    ## The gateway's own log, around the login page

    A login IBKR refused leaves the HTTP side exactly as no login does, so FREE alone would
    open the page with no word. The log is read once before the page (`read_login`, the
    manager's own reader by default — a `docker exec`, so a test passes a stand-in): a login
    IBKR has not answered yet gets no second page (the pre-flight's VALIDATING rule); a refused
    last login is named, with the remedy. The page still opens — the remedy is a website login
    THEN one gateway login, and withholding the page would deadlock it. During the wait, a
    login newer than the one seen before the page (the log's own timestamps, never a clock)
    that IBKR refused too ends the wait at once. No readable log before the page, no early
    stop: nothing would tell old from new. The read runs inside the container and sends the
    gateway no request, so the suspension holds.

    Returns the final published `SessionState`. Never raises for an ordinary gateway problem:
    unreachable, contested, borrowed and "the user did not finish" are all normal answers that
    a caller mid-startup has to branch on rather than catch.
    """
    say = emit or (lambda line: log.info("%s", line))
    api_url = url or gateway_api_url()
    _sleep = sleep or time.sleep
    _now = monotonic or time.monotonic
    suspend = lock if lock is not None else SuspendLock()
    read_log: LoginReader = read_login if read_login is not None else read_login_events

    say("▶ Ensuring Docker is running…")
    manager.ensure_docker_running()

    if manager.is_running():
        say("▶ Gateway container already running — leaving it alone until the session is read.")
    else:
        say("▶ No gateway container running — starting one…")
        manager.start()

    say(f"▶ Waiting for the gateway to answer (up to {reach_timeout}s)…")
    if not manager.wait_for_gateway(timeout=reach_timeout):
        session.publish(
            SessionState(
                phase=SessionPhase.DOWN,
                as_of=datetime.now(UTC),
                detail=(
                    f"The gateway did not answer within {reach_timeout}s. The login page "
                    "will not load either — run `python -m ibkr_core_mcp.gateway diagnose` "
                    "for the last login as the gateway's own log records it."
                ),
            )
        )
        return session.state()

    say("▶ Reading the session before touching anything…")
    state = session.read_now(api_url)
    say(f"   {state.phase.value}: {state.detail}")

    if state.phase is SessionPhase.LIVE:
        say("✔ Already authenticated — not opening the login page.")
        return state

    if state.phase is SessionPhase.CONTESTED:
        # Never auto-resolved. Evicting the other client starts the tug-of-war this module
        # exists to prevent, and closing that app is something the user can do deliberately in
        # a way this process cannot do for them.
        return state

    if state.phase is SessionPhase.BORROWED:
        if not allow_restart:
            return state
        state = _recover(session, manager, url=api_url, emit=say, reach_timeout=reach_timeout, lock=suspend)
        if state.phase is not SessionPhase.FREE:
            return state

    if state.phase is SessionPhase.DEGRADED:
        # Authenticated but the data half is dark. A login cannot fix that and would throw away
        # a working brokerage session to chase a market-data outage.
        say("✕ Authenticated, but the data half is not answering — a login would not help.")
        return state

    if state.phase is not SessionPhase.FREE or not open_login:
        return state

    # ── FREE: the one phase that earns a login page ──────────────────────────
    readable, seen = _seen_login(read_log)
    if seen is not None and seen.outcome == "validating":
        # IBKR has not answered the newest login (at most 13 s, measured) — or the gateway
        # stalled mid-validation. A second page now is a second login against the one being
        # answered; the pre-flight's own rule says do not. The one case added in the move
        # (register F45, step 2): the consumer's owner had no rule for it, and step 1's gate
        # inside `startup()`, which held it, went with the body it guarded.
        say(f"⚠ IBKR has not answered the last gateway login yet ({seen.at} UTC) — no second login page.")
        say(f"  {_VALIDATING_GUIDANCE}")
        return state
    if seen is not None and seen.outcome == "refused":
        say(f"⚠ IBKR refused the last gateway login ({seen.at} UTC).")
        say(f"  {REFUSED_GUIDANCE}")
    suspend.acquire("login in progress")
    try:
        session.publish(declare(SessionPhase.AUTHENTICATING))
        window = manager.open_login_page()
        opened = "window" if window is not None else "page"
        say(f"▶ Login {opened} opened. Complete it through to 'Client login succeeds'.")
        say(f"  Nothing else will touch the gateway for up to {int(login_timeout)}s.")

        deadline = _now() + login_timeout
        announced = False
        while _now() < deadline:
            reading = read_state(api_url)
            if reading.authenticated and reading.connected:
                if window is not None:  # the login's job is done; the data half is checked next
                    if not window.close():
                        say(_NOT_OURS_TO_CLOSE)
                    window = None
                ok, detail = confirm_session(api_url)
                if ok:
                    say(f"✔ Session established and serving data — {detail}")
                    session.publish(observe(reading, True))
                    return session.state()
                if not announced:
                    say(f"   authenticated, waiting for the data half — {detail}")
                    announced = True
            elif reading.sso_valid and reading.client_app and not reading.authenticated:
                say(f"✕ The gateway is now holding {reading.client_app}'s session.")
                if window is not None:
                    say(_CLOSE_THE_WINDOW)
                session.publish(observe(reading, False))
                return session.state()
            if readable:
                _, newest = _seen_login(read_log)
                if newest is not None and newest.outcome == "refused" and (seen is None or newest.at > seen.at):
                    say(f"✕ IBKR refused this login too ({newest.at} UTC).")
                    if window is not None:
                        say(_CLOSE_THE_WINDOW)
                    session.publish(session.read_now(api_url).stale_copy(REFUSED_GUIDANCE))
                    return session.state()
            _sleep(poll_interval)

        # Timed out. Republished as a fresh reading rather than left in AUTHENTICATING: leaving
        # the declared phase in place would suspend every tickler indefinitely.
        if window is not None:
            say(_CLOSE_THE_WINDOW)
        final = session.read_now(api_url)
        session.publish(final.stale_copy(_LOGIN_INCOMPLETE_GUIDANCE))
        return session.state()
    finally:
        suspend.release()


def _recover(
    session: GatewaySession,
    manager: GatewayManagerLike,
    *,
    url: str | None = None,
    emit: Callable[[str], None] | None = None,
    reach_timeout: int = 120,
    lock: SuspendLock | None = None,
    force: bool = False,
) -> SessionState:
    """Clear a session the gateway cannot use, by restarting the container.

    The restart is guarded inside `manager.start()` (condition F): a LIVE, REFUSED or
    VALIDATING session raises `RestartRefusedError`, which this turns into a reading — the
    phase read off the wire, the refusal as `detail` — never an exception to a button, and
    never a session left in RECOVERING. `force` is passed through, and only an operator's
    explicit `--force` sets it; `_establish` never does.

    ## Why this does not call `POST /logout`

    Two independent reasons, both evidence:

    1. **It does not work.** On 2026-08-05 `/logout` returned `{"status": true}` and the session
       came straight back with a full 10-minute window, because three separate ticklers renewed
       it every 60 seconds. Restarting the container did clear it.
    2. **Its scope is undocumented.** IBKR's page says only *"Logs the user out of the gateway
       session. Any further activity requires re-authentication."* — nothing about whether that
       cascades to TWS or IBKR Mobile
       (https://www.interactivebrokers.com/docs/web-api/v1/endpoints/session/logout-of-the-current-session.md).
       Since only one brokerage session exists per username, a cascade is plausible, and
       logging a user out of the phone they are managing a live position on is not a risk
       worth taking for a call that did not work anyway.

    `release_session` still exists behind an explicit `--release` for deliberate manual use.
    Nothing automatic calls it.

    The suspend lock is held across the whole operation so no tickler can re-establish what is
    being cleared, and released in `finally` — a leaked lock would silence every keepalive with
    nothing on screen to explain the session slowly dying.
    """
    say = emit or (lambda line: log.info("%s", line))
    api_url = url or gateway_api_url()
    suspend = lock if lock is not None else SuspendLock()

    suspend.acquire("recovering the session")
    try:
        session.publish(declare(SessionPhase.RECOVERING))
        say("▶ Restarting the gateway container to clear the session, unless the session must be kept…")
        try:
            manager.restart(force=force)
        except RestartRefusedError as exc:
            audit.record(
                "session_write",
                actor="operator",
                decision="refused",
                outcome=f"code {exc.code}",
                action="restart",
                params={"force": force},
            )
            say(f"✕ Restart refused: {exc.reason}")
            session.publish(session.read_now(api_url).stale_copy(exc.reason))
            return session.state()
        audit.record("session_write", actor="operator", decision="restarted", action="restart", params={"force": force})
        if not manager.wait_for_gateway(timeout=reach_timeout):
            session.publish(
                SessionState(
                    phase=SessionPhase.DOWN,
                    as_of=datetime.now(UTC),
                    detail="The gateway did not come back after the restart.",
                )
            )
            return session.state()
        state = session.read_now(api_url)
        say(f"   after restart: {state.phase.value}")
        return state
    finally:
        suspend.release()


# ══════════════════════════════════════════════════════════════════════════════
# The keepalive — the host-side tickler, which honours the lock.
# ══════════════════════════════════════════════════════════════════════════════


class Awake(Protocol):
    """What the keepalive holds while the gateway answers: `manager.KeepAwake`, or a stand-in."""

    def hold(self) -> None:
        """Hold the machine awake."""
        ...

    def release(self) -> None:
        """Let it sleep."""
        ...


KEEPALIVE_INTERVAL = 55.0
"""Seconds between tickles — slightly under IBKR's recommended ~1 per minute
(https://www.interactivebrokers.com/docs/web-api/v1/endpoints/session/ping-the-server.md)."""


def _tick(api_url: str, lock_path: Path, awake: Awake, timeout: float = 5.0) -> tuple[str, str]:
    """One tick: `(state, http_code)` — `SUSPENDED` with no request while a live process holds
    the lock (and the assertion untouched: nothing is held awake for a session that does not
    exist yet); else `GET /tickle` → `OK` and `hold()` on 200, `WARN` and `release()` on anything
    else, an exception reading as `000` the way `curl` reported it, its text never printed."""
    if SuspendLock.is_active(lock_path):
        return "SUSPENDED", ""
    require_loopback_url(api_url)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", urllib3.exceptions.InsecureRequestWarning)
            resp = requests.get(f"{api_url}/tickle", timeout=timeout, verify=False)  # noqa: S501 - localhost gateway, self-signed cert; pinned above (SECURITY.md § TLS Policy)
        code = str(resp.status_code)
    except Exception:
        code = "000"
    if code == "200":
        awake.hold()
        return "OK", code
    awake.release()
    return "WARN", code


def keepalive_loop(
    api_url: str,
    *,
    lock_path: Path = DEFAULT_SUSPEND_LOCK,
    interval: float = KEEPALIVE_INTERVAL,
    awake: Awake,
    sleep: Callable[[float], None] = time.sleep,
    say: Callable[[str], None] = print,
    once: bool = False,
) -> None:
    """Keep the gateway's session alive from outside any host process, honouring the lock.

    IBKR renews a session on **any** request, so this is the one renewer a login or a recovery
    cannot silence in-process — the lock file is the only thing that reaches it, and a tick
    under an active lock sends nothing. Behaviour identical to the consumer's bash loop it
    replaces: `GET /tickle` every `interval` seconds, a line only on a state change (under
    launchd the loop runs for months), the sleep assertion held on OK and released on WARN, and
    released on the way out whatever ended the loop — Ctrl-C, or the SIGTERM the command line
    turns into `SystemExit`. `say` is expected to flush (the command line's does): under launchd
    stdout is a file and block-buffered, and the `SUSPENDED` line is live evidence only if it
    lands at once.

    Args:
        api_url: The gateway's API base URL; pinned to loopback before anything is sent.
        lock_path: The suspend lock to honour; the package's default path, a contract.
        interval: Seconds between ticks.
        awake: The sleep assertion to hold and release.
        sleep: Injected for tests.
        say: Where the lines go.
        once: One tick, then return — the test seam.

    Raises:
        ConfigError: `api_url` is not a loopback host — before the first request.
    """
    require_loopback_url(api_url)
    tickle = f"{api_url}/tickle"
    say(f"Starting — tickling {tickle} every {interval:g}s")
    last = ""
    try:
        while True:
            state, code = _tick(api_url, lock_path, awake)
            if state != last:
                stamp = datetime.now().astimezone().strftime("%H:%M:%S %Z")
                if state == "SUSPENDED":
                    say(f"{stamp}  SUSPENDED  — a login or recovery is in progress; not tickling")
                elif state == "OK":
                    say(f"{stamp}  OK  (HTTP {code})")
                else:
                    say(f"{stamp}  WARN  (HTTP {code}) — gateway may be down or not authenticated")
                last = state
            if once:
                return
            sleep(interval)
    finally:
        awake.release()


_SESSION: GatewaySession | None = None


def get_session() -> GatewaySession:
    """The process-wide session owner.

    A single instance per process: two owners would be two authorities, which is the condition
    this module exists to remove. A host's button, the command line and every subscriber must
    be talking about the same session or the suspend guarantee means nothing.
    """
    global _SESSION
    if _SESSION is None:
        _SESSION = GatewaySession()
    return _SESSION


# ══════════════════════════════════════════════════════════════════════════════
# The owner polls, and owns the last session-affecting write.
# ══════════════════════════════════════════════════════════════════════════════


def attempt_soft_recovery(url: str, timeout: float = 5.0) -> bool:
    """`POST /iserver/auth/ssodh/init` — raise the brokerage bridge after a soft timeout.

    A session-affecting write, so the owner's: a monitor that can silently re-establish a
    session is a second authority over it.

    ## What it can and cannot do — measured, not assumed

    It raises the bridge and nothing more. Measured 2026-08-05 during the borrowed-session
    diagnosis, two inits moved `connected` False→True and left `authenticated` False both
    times: **it cannot supply an authentication that never happened**. So it is worth trying
    for IBKR's documented soft-timeout signature (previously working, now `connected` with
    `authenticated` false) and worthless for anything else — which is exactly how
    `GatewaySession._poll_once` gates it.

    `compete` is `COMPETE`, a `Final` False, and must stay that way: it must never force-evict
    a concurrent IBKR Mobile or TWS session. IBKR signals a real competing session with HTTP 200
    and `authenticated: false` in the body rather than an error status, so the body is checked,
    not merely the status code.

    Source: https://www.interactivebrokers.com/docs/web-api/v1/endpoints/session/initialize-brokerage-session.md

    Raises:
        ConfigError: `url` is not a loopback host — before any request.
    """
    require_loopback_url(url)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", urllib3.exceptions.InsecureRequestWarning)
            resp = requests.post(
                f"{url}/iserver/auth/ssodh/init",
                json={"publish": True, "compete": COMPETE},
                timeout=timeout,
                verify=False,  # noqa: S501 - localhost gateway, self-signed cert; pinned above (SECURITY.md § TLS Policy)
            )
        if resp.status_code != 200:
            audit.record(
                "session_write",
                actor="owner",
                decision="not_recovered",
                outcome=f"HTTP {resp.status_code}",
                action="ssodh_init",
            )
            return False
        body = resp.json()
    except Exception as exc:
        audit.record("session_write", actor="owner", decision="error", outcome=type(exc).__name__, action="ssodh_init")
        log.debug("ssodh/init failed: %s", redact_error(exc))
        return False
    auth = (body.get("iserver") or {}).get("authStatus") or body
    recovered = bool(auth.get("authenticated"))
    audit.record(
        "session_write", actor="owner", decision="recovered" if recovered else "not_recovered", action="ssodh_init"
    )
    return recovered
