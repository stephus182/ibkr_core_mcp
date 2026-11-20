"""Tests for `ibkr_core_mcp.gateway.session` — the gateway session's one owner.

Moved from the consumer that wrote them on 2026-11-09 (register F45, step 2), unchanged in what
they assert: a moved test is the specification of a move. Their fixture URLs became loopback
ones because every sending function in this package pins its URL first (condition C), and the
`wire` fixture stands in the gateway's log reader too, because the owner here reads the log
itself by default and a unit test runs no `docker exec` (door 6).

The invariants are asserted **over every phase**, not over a representative one. That choice is
the lesson from the defect that started the owner: the broken code returned a correct-looking
value for the case anyone would have tested, and was wrong for the two cases that mattered.
Parametrising over the whole enum is what makes a future ninth phase fail loudly instead of
silently inheriting a default.
"""

from __future__ import annotations

import ast
import json
import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from ibkr_core_mcp.exceptions import ConfigError, RestartRefusedError
from ibkr_core_mcp.gateway import session as session_module
from ibkr_core_mcp.gateway.preflight import EXIT_READY, GatewayState, LoginEvent
from ibkr_core_mcp.gateway.session import (
    COMPETE,
    GatewaySession,
    SessionPhase,
    SessionState,
    SuspendLock,
    _pid_alive,
    _tick,
    attempt_soft_recovery,
    classify,
    declare,
    describe,
    keepalive_loop,
    observe,
    release_session,
)

_NOW = datetime(2026, 8, 6, 13, 0, tzinfo=UTC)
_URL = "https://localhost:5055/v1/api"  # loopback: every sending function pins its URL (condition C)

# Every phase, so the invariant tests below cannot quietly skip one.
ALL_PHASES = list(SessionPhase)
SUSPENDED = {SessionPhase.AUTHENTICATING, SessionPhase.RECOVERING}


# ── Readings, matching what this gateway actually returns ────────────────────


def _down() -> GatewayState:
    """The gateway process is not answering at all."""
    return GatewayState(reachable=False, detail="ConnectionError")


def _free() -> GatewayState:
    """Reachable, holding nothing — HTTP 401 on tickle and sso/validate."""
    return GatewayState(reachable=True, detail="HTTP 401 — no session yet")


def _authenticated() -> GatewayState:
    """Brokerage session up. Whether it is LIVE depends on the data check."""
    return GatewayState(reachable=True, authenticated=True, connected=True)


def _borrowed() -> GatewayState:
    """The 2026-08-05 diagnosis: SSO valid, owned by IBKR Mobile, unauthenticated here."""
    return GatewayState(
        reachable=True,
        authenticated=False,
        connected=False,
        sso_valid=True,
        client_app="IBKRMOBILE_000.a-000",
        sso_user="ibkruser",
        user_id=99999999,
    )


def _contested() -> GatewayState:
    """Another IBKR client is competing for the single brokerage session."""
    return GatewayState(reachable=True, competing=True)


# ── classify: the single definition of what a reading means ──────────────────


@pytest.mark.parametrize(
    "reading,data_ok,expected",
    [
        (_down(), False, SessionPhase.DOWN),
        (_down(), True, SessionPhase.DOWN),  # unreachable wins over any data claim
        (_free(), False, SessionPhase.FREE),
        (_authenticated(), True, SessionPhase.LIVE),
        (_authenticated(), False, SessionPhase.DEGRADED),
        (_borrowed(), False, SessionPhase.BORROWED),
        (_contested(), False, SessionPhase.CONTESTED),
    ],
)
def test_classify_maps_each_reading_to_its_phase(reading, data_ok, expected):
    """Every reading this gateway produces has exactly one phase."""
    assert classify(reading, data_ok) is expected


def test_live_is_unreachable_without_a_data_confirmation():
    """The invariant: an authenticated flag alone can never produce LIVE.

    The brokerage half and the data half are documented as independent subsystems with
    different prerequisites, and were observed diverging on this account on 2026-08-04
    (ledger live while `/iserver/account/orders` returned `no bridge`). Reporting an
    unconfirmed session as live publishes figures nobody can vouch for.
    """
    assert classify(_authenticated(), data_ok=False) is SessionPhase.DEGRADED
    assert classify(_authenticated(), data_ok=True) is SessionPhase.LIVE


def test_classify_requires_data_ok_explicitly():
    """No default: forgetting to confirm must be a TypeError, never a silent LIVE."""
    with pytest.raises(TypeError):
        classify(_authenticated())  # type: ignore[call-arg]


def test_a_working_session_outranks_a_competing_claim():
    """Matches `gateway_preflight.verdict` step for step — one definition, not two.

    `verdict` checks `authenticated and connected` before `competing`, so this must too;
    a second, drifting definition of the same reading is the class of mistake the whole
    plan exists to remove.
    """
    both = GatewayState(reachable=True, authenticated=True, connected=True, competing=True)
    assert classify(both, data_ok=True) is SessionPhase.LIVE


def test_classify_never_returns_a_declared_phase():
    """AUTHENTICATING and RECOVERING describe an operation, not a reading."""
    readings = [_down(), _free(), _authenticated(), _borrowed(), _contested()]
    produced = {classify(r, ok) for r in readings for ok in (True, False)}
    assert produced.isdisjoint(SUSPENDED)


# ── The suspension invariant, over every phase ───────────────────────────────


@pytest.mark.parametrize("phase", ALL_PHASES)
def test_suspension_is_exactly_the_two_declared_phases(phase):
    """Total suspension, with no carve-outs (plan §8.1).

    Any request renews the session, so an exception for one actor reintroduces the
    traffic that made `POST /logout` unable to clear a borrowed session on 2026-08-05.
    """
    state = SessionState(phase=phase, as_of=_NOW)
    assert state.is_suspended is (phase in SUSPENDED)
    assert state.may_call_ibkr is (phase not in SUSPENDED)


@pytest.mark.parametrize("phase", ALL_PHASES)
def test_only_live_permits_account_data(phase):
    """DEGRADED must not read as usable — it is the state where figures look fine."""
    assert SessionState(phase=phase, as_of=_NOW).is_live is (phase is SessionPhase.LIVE)


@pytest.mark.parametrize("phase", ALL_PHASES)
def test_every_phase_has_a_reason(phase):
    """A phase with no wording would reach the UI as a blank explanation."""
    assert describe(phase).strip()


def test_borrowed_names_the_app_holding_the_session():
    """The field that actually explains a stuck login is the one a user needs to see."""
    assert "IBKRMOBILE_000.a-000" in describe(SessionPhase.BORROWED, _borrowed())


# ── declare: the hole that must stay closed ──────────────────────────────────


@pytest.mark.parametrize("phase", sorted(SUSPENDED))
def test_the_two_operational_phases_may_be_declared(phase):
    """These describe something the owner is doing and cannot be read off the wire."""
    assert declare(phase, now=_NOW).phase is phase


@pytest.mark.parametrize("phase", [p for p in ALL_PHASES if p not in SUSPENDED])
def test_an_observed_phase_can_never_be_declared(phase):
    """Otherwise `declare(LIVE)` would assert a confirmed session without confirming."""
    with pytest.raises(ValueError, match="observed phase"):
        declare(phase)


# ── Staleness: same rule the dashboard already enforces ──────────────────────


def test_a_failed_read_does_not_refresh_as_of():
    """Age must keep growing, or a session frozen 20 minutes ago reads as one second old."""
    established = observe(_authenticated(), data_ok=True, now=_NOW)
    later = established.stale_copy("gateway stopped answering")

    assert later.as_of == _NOW
    assert later.phase is SessionPhase.LIVE
    assert later.detail == "gateway stopped answering"
    assert later.age_seconds(now=_NOW + timedelta(minutes=20)) == pytest.approx(1200)


def test_age_is_never_negative():
    """A clock that steps backwards must not produce a negative age."""
    state = observe(_free(), data_ok=False, now=_NOW)
    assert state.age_seconds(now=_NOW - timedelta(seconds=30)) == 0.0


def test_observe_keeps_the_evidence_the_phase_came_from():
    """A decision must be explainable from the reading it was made on, not a later one."""
    state = observe(_borrowed(), data_ok=False, now=_NOW)
    assert state.gateway is not None
    assert state.gateway.client_app == "IBKRMOBILE_000.a-000"
    assert state.data_ok is False


# ── The holder ───────────────────────────────────────────────────────────────


def test_starts_unread_not_down():
    """ "Not read yet" and "the gateway is down" must not look identical to a consumer.

    Gap #26. This test used to assert `DOWN` here, pinning the defect it names: the honest
    reading sat in `detail` while the phase — the only thing `ConnectivityChecker` looks at
    — claimed an outage. Every startup therefore told the user to log in to Client Portal
    against a healthy gateway (observed live 2026-08-13 and 2026-09-15), the action that
    escalates into the IB Key challenge.
    """
    session = GatewaySession()
    assert session.phase is SessionPhase.UNREAD
    assert "not been read" in session.state().detail


def test_classify_never_returns_unread():
    """UNREAD is the absence of a reading, so no reading can produce it.

    That is what makes it a one-way door: once the first poll publishes, the session can
    never return to UNREAD, and a consumer that saw any other phase can trust it is real.
    """
    readings = [_down(), _free(), _authenticated(), _borrowed(), _contested()]
    produced = {classify(r, ok) for r in readings for ok in (True, False)}
    assert SessionPhase.UNREAD not in produced


def test_subscribers_fire_only_on_a_phase_change():
    """A notification repeated every poll trains the reader to dismiss it."""
    session = GatewaySession()
    seen: list[SessionPhase] = []
    session.subscribe(lambda s: seen.append(s.phase))

    assert session.publish(observe(_free(), False, now=_NOW)) is True
    assert session.publish(observe(_free(), False, now=_NOW)) is False  # same phase
    assert session.publish(observe(_authenticated(), True, now=_NOW)) is True

    assert seen == [SessionPhase.FREE, SessionPhase.LIVE]


def test_a_republish_with_a_new_reason_is_not_a_transition():
    """Same situation, new wording — the staleness path must not toast on every poll."""
    session = GatewaySession()
    session.publish(observe(_authenticated(), True, now=_NOW))
    seen: list[SessionPhase] = []
    session.subscribe(lambda s: seen.append(s.phase))

    assert session.publish(session.state().stale_copy("gateway timed out")) is False
    assert seen == []


def test_one_failing_subscriber_does_not_starve_the_others():
    """The moment a subscriber raises is the moment the rest most need telling."""
    session = GatewaySession()
    reached: list[str] = []
    session.subscribe(lambda s: (_ for _ in ()).throw(RuntimeError("boom")))
    session.subscribe(lambda s: reached.append("second"))

    session.publish(observe(_free(), False, now=_NOW))

    assert reached == ["second"]


def test_unsubscribe_stops_delivery_and_is_idempotent():
    """Per-session teardown must be safe to run twice — Panel destroys sessions abruptly."""
    session = GatewaySession()
    seen: list[SessionPhase] = []
    unsubscribe = session.subscribe(lambda s: seen.append(s.phase))

    unsubscribe()
    unsubscribe()  # must not raise
    session.publish(observe(_free(), False, now=_NOW))

    assert seen == []


@pytest.mark.parametrize("phase", ALL_PHASES)
def test_the_holder_predicates_agree_with_the_state(phase):
    """The holder must never form a second opinion about its own state."""
    session = GatewaySession()
    session.publish(SessionState(phase=phase, as_of=_NOW))

    assert session.is_live() is session.state().is_live
    assert session.is_suspended() is session.state().is_suspended
    assert session.may_call_ibkr() is session.state().may_call_ibkr


# ═══════════════════════════════════════════════════════════════════════════
# Stage 2 — the owner acts.
#
# The defect that started the plan was an ORDERING bug that returned a
# correct-looking value, so these assert call sequences and forbidden actions,
# not just outcomes.
# ═══════════════════════════════════════════════════════════════════════════

_MUTATORS = {"start", "restart"}


class FakeManager:
    """Records every call it receives, in order, so sequence can be asserted."""

    def __init__(self, running: bool = False, reachable: bool = True) -> None:
        """Configure whether the container is running and whether it answers."""
        self.calls: list[str] = []
        self._running = running
        self._reachable = reachable

    def ensure_docker_running(self, timeout: int = 60) -> None:
        """Record the call."""
        self.calls.append("ensure_docker_running")

    def is_running(self) -> bool:
        """Record the call and report the configured state."""
        self.calls.append("is_running")
        return self._running

    def start(self, *, force: bool = False) -> None:
        """Record the call and mark the container running."""
        self.calls.append("start" if not force else "start(force)")
        self._running = True

    def restart(self, *, force: bool = False) -> None:
        """Record the call and mark the container running."""
        self.calls.append("restart" if not force else "restart(force)")
        self._running = True

    def wait_for_gateway(self, timeout: int = 120, poll_interval: int = 3) -> bool:
        """Record the call and report the configured reachability."""
        self.calls.append("wait_for_gateway")
        return self._reachable

    def open_login_page(self) -> None:
        """Record the call."""
        self.calls.append("open_login_page")


class FakeWindow:
    """A stand-in for the core's `LoginWindow`: records its close in the manager's call log."""

    def __init__(self, manager: FakeManager, ours: bool = True) -> None:
        """`ours=False` is the leftover case: the launch went to a Chrome already running."""
        self._manager = manager
        self._ours = ours

    def close(self) -> bool:
        """Record the call and report whether the window was ours to close."""
        self._manager.calls.append("close_login_window")
        return self._ours


class WindowManager(FakeManager):
    """A manager whose `open_login_page()` returns a window handle, as the core's does from 2.2.0."""

    def __init__(self, ours: bool = True, **kwargs: bool) -> None:
        """Configure the container as `FakeManager` does, and whether the window will be ours."""
        super().__init__(**kwargs)
        self.window = FakeWindow(self, ours=ours)

    def open_login_page(self) -> FakeWindow:  # type: ignore[override]
        """Record the call and hand back the window."""
        self.calls.append("open_login_page")
        return self.window


@pytest.fixture
def wire(monkeypatch, tmp_path):
    """Patch read_state/confirm_session/read_login_events, recording reads in the manager's call log."""

    def _install(manager, readings, confirmations=(True,)):
        """Queue readings and data-confirmations; the last of each repeats."""
        reads = list(readings)
        confs = list(confirmations)

        def fake_read(url, timeout=5.0):
            """Stand-in for read_state that appends to the manager's call log."""
            manager.calls.append("read_state")
            return reads.pop(0) if len(reads) > 1 else reads[0]

        def fake_confirm(url, timeout=10.0):
            """Stand-in for confirm_session."""
            ok = confs.pop(0) if len(confs) > 1 else confs[0]
            return ok, "account(s) <redacted>" if ok else "no bridge"

        monkeypatch.setattr("ibkr_core_mcp.gateway.session.read_state", fake_read)
        monkeypatch.setattr("ibkr_core_mcp.gateway.session.confirm_session", fake_confirm)
        # The owner reads the gateway's log itself by default (a `docker exec`, refused by door 6
        # in a unit test): stood in as "unreadable", which is what the consumer's `None` meant.
        monkeypatch.setattr(
            "ibkr_core_mcp.gateway.session.read_login_events",
            lambda timeout=15.0: (None, "no container in a unit test"),
        )
        return SuspendLock(path=tmp_path / "session.suspend")

    return _install


def _clock():
    """A monotonic clock advancing 5s per call, so timeouts expire without sleeping."""
    state = {"t": 0.0}

    def tick() -> float:
        """Advance the clock 5s and return it."""
        state["t"] += 5.0
        return state["t"]

    return tick


def _establish(session, gm, lock, **kw):
    """Run establish with sleeping and clocks stubbed out."""
    return session.establish(
        gm,
        url=_URL,
        emit=kw.pop("emit", lambda _: None),
        lock=lock,
        sleep=lambda _: None,
        monotonic=_clock(),
        **kw,
    )


# ── The ordering guarantee ───────────────────────────────────────────────────


def test_a_running_container_is_never_mutated_before_the_session_is_read(wire):
    """The defect this plan replaced, pinned: no start/restart before `read_state`.

    Until 2026-08-06 `panel_app._on_start_gateway` called `GatewayManager.start()` —
    which removes any existing container — and only then read the session. Asserted on
    the sequence, because the old code's return value looked correct.
    """
    gm = FakeManager(running=True)
    lock = wire(gm, [_authenticated()])
    session = GatewaySession()

    _establish(session, gm, lock)

    read_at = gm.calls.index("read_state")
    assert [c for c in gm.calls[:read_at] if c in _MUTATORS] == [], gm.calls


def test_a_stopped_container_is_started_before_the_read(wire):
    """A stopped container cannot hold a session, so starting it destroys no evidence."""
    gm = FakeManager(running=False)
    lock = wire(gm, [_free()])
    session = GatewaySession()

    _establish(session, gm, lock)

    assert gm.calls.index("start") < gm.calls.index("read_state")


# ── Which phases earn a login page ───────────────────────────────────────────


def test_a_live_session_is_left_alone(wire):
    """Re-authenticating a working session escalates into the IB Key challenge."""
    gm = FakeManager(running=True)
    lock = wire(gm, [_authenticated()], confirmations=[True])
    session = GatewaySession()

    result = _establish(session, gm, lock)

    assert result.phase is SessionPhase.LIVE
    assert "open_login_page" not in gm.calls


def test_degraded_does_not_trigger_a_login(wire):
    """A login cannot fix a market-data outage and would discard a working session."""
    gm = FakeManager(running=True)
    lock = wire(gm, [_authenticated()], confirmations=[False])
    session = GatewaySession()

    result = _establish(session, gm, lock)

    assert result.phase is SessionPhase.DEGRADED
    assert "open_login_page" not in gm.calls


def test_contested_is_never_auto_resolved(wire):
    """Evicting the other client starts the tug-of-war this module exists to prevent."""
    gm = FakeManager(running=True)
    lock = wire(gm, [_contested()])
    session = GatewaySession()

    result = _establish(session, gm, lock)

    assert result.phase is SessionPhase.CONTESTED
    assert "open_login_page" not in gm.calls
    assert "restart" not in gm.calls


def test_borrowed_does_not_restart_unless_allowed(wire):
    """A restart destroys a live session, so it stays opt-in per call."""
    gm = FakeManager(running=True)
    lock = wire(gm, [_borrowed()])
    session = GatewaySession()

    result = _establish(session, gm, lock)

    assert result.phase is SessionPhase.BORROWED
    assert "restart" not in gm.calls
    assert "open_login_page" not in gm.calls


def test_free_opens_the_login_page_and_confirms_before_declaring_success(wire):
    """LIVE requires the data call, not just an authenticated flag."""
    gm = FakeManager(running=True)
    lock = wire(gm, [_free(), _authenticated()], confirmations=[True])
    session = GatewaySession()

    result = _establish(session, gm, lock)

    assert result.phase is SessionPhase.LIVE
    assert gm.calls.index("read_state") < gm.calls.index("open_login_page")


def test_an_authenticated_flag_alone_never_ends_the_wait(wire):
    """Authenticated with the data half dark must time out, never report success."""
    gm = FakeManager(running=True)
    lock = wire(gm, [_free(), _authenticated()], confirmations=[False])
    session = GatewaySession()

    result = _establish(session, gm, lock, login_timeout=20)

    assert result.phase is not SessionPhase.LIVE


# ── The suspend lock ─────────────────────────────────────────────────────────


def test_the_lock_is_held_during_the_login_and_released_after(wire, tmp_path):
    """Any request renews the session, so everything must be silent during a login."""
    gm = FakeManager(running=True)
    lock = wire(gm, [_free(), _authenticated()], confirmations=[True])
    session = GatewaySession()
    seen: list[bool] = []

    original = gm.open_login_page

    def spy() -> None:
        """Record whether the lock was active at the moment the page opened."""
        seen.append(SuspendLock.is_active(lock.path))
        original()

    gm.open_login_page = spy  # type: ignore[method-assign]
    _establish(session, gm, lock)

    assert seen == [True], "the suspend lock was not held while the login page was open"
    assert not lock.path.exists(), "the lock leaked after the login completed"


def test_the_lock_is_released_even_when_the_login_raises(wire, tmp_path):
    """A leaked lock silences every keepalive with nothing on screen to explain it."""
    gm = FakeManager(running=True)
    lock = wire(gm, [_free()])
    session = GatewaySession()

    def boom() -> None:
        """Fail the way a browser launch can."""
        raise RuntimeError("no browser")

    gm.open_login_page = boom  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        _establish(session, gm, lock)

    assert not lock.path.exists()


def test_a_lock_naming_a_dead_process_is_ignored(tmp_path):
    """A crash must degrade to 'no suspension', never wedge every tickler forever."""
    path = tmp_path / "session.suspend"
    path.write_text(json.dumps({"pid": 999999, "reason": "crashed", "since": "x"}))
    assert SuspendLock.is_active(path) is False


def test_a_lock_naming_a_live_process_suspends(tmp_path):
    """The live case, so the dead-PID test above cannot pass for the wrong reason."""
    path = tmp_path / "session.suspend"
    path.write_text(json.dumps({"pid": os.getpid(), "reason": "login", "since": "x"}))
    assert SuspendLock.is_active(path) is True


@pytest.mark.parametrize("body", ["", "not json", "{}", '{"pid": "abc"}'])
def test_a_malformed_lock_fails_open(tmp_path, body):
    """Failing closed would silence every tickler because a file got truncated."""
    path = tmp_path / "session.suspend"
    path.write_text(body)
    assert SuspendLock.is_active(path) is False


def test_an_absent_lock_is_not_active(tmp_path):
    """The ordinary case: no file, no suspension."""
    assert SuspendLock.is_active(tmp_path / "nope") is False


# ── Recovery ─────────────────────────────────────────────────────────────────


def test_recovery_restarts_the_container_and_never_calls_logout(wire, monkeypatch):
    """`POST /logout` did not work (three ticklers renewed through it) and its scope
    relative to IBKR Mobile is undocumented. Recovery must not depend on it."""
    gm = FakeManager(running=True)
    lock = wire(gm, [_free()])
    session = GatewaySession()
    posts: list[str] = []
    monkeypatch.setattr(
        "ibkr_core_mcp.gateway.session.requests.post",
        lambda *a, **k: posts.append(str(a)),
        raising=False,
    )

    session.recover(gm, url=_URL, emit=lambda _: None, lock=lock)

    assert "restart" in gm.calls
    assert posts == [], "recovery must not POST to the gateway"


def test_recovery_holds_the_lock_across_the_restart(wire):
    """No tickler may re-establish the session being cleared."""
    gm = FakeManager(running=True)
    lock = wire(gm, [_free()])
    session = GatewaySession()
    seen: list[bool] = []

    original = gm.restart

    def spy(*, force: bool = False) -> None:
        """Record whether the lock was active at the moment of the restart."""
        seen.append(SuspendLock.is_active(lock.path))
        original(force=force)

    gm.restart = spy  # type: ignore[method-assign]
    session.recover(gm, url=_URL, emit=lambda _: None, lock=lock)

    assert seen == [True]
    assert not lock.path.exists()


class RefusingManager(FakeManager):
    """A manager whose restart guard refuses unless forced — what the real `start()` does on a
    LIVE, REFUSED or VALIDATING reading (register F45, condition F)."""

    def restart(self, *, force: bool = False) -> None:
        """Record the attempt; refuse unless forced."""
        self.calls.append("restart" if not force else "restart(force)")
        if not force:
            raise RestartRefusedError("Session is LIVE\n\nDo not log in again.", code=EXIT_READY)
        self._running = True


def test_a_refused_restart_is_published_as_the_current_reading_with_the_reason(wire):
    """The guard lives inside `start()`; the owner turns its refusal into a reading — the phase
    read off the wire, the refusal as `detail` — never an exception to a button, and never a
    session left in RECOVERING."""
    gm = RefusingManager(running=True)
    lock = wire(gm, [_authenticated()], confirmations=[True])
    session = GatewaySession()
    lines: list[str] = []

    result = session.recover(gm, url=_URL, emit=lines.append, lock=lock)

    assert result.phase is SessionPhase.LIVE
    assert "Session is LIVE" in result.detail
    assert result.is_suspended is False
    assert gm.calls.count("restart") == 1 and "restart(force)" not in gm.calls
    assert not lock.path.exists(), "the lock leaked after a refused restart"
    assert any("refused" in line.lower() for line in lines), lines


def test_force_reaches_the_manager_and_overrides_the_guard(wire):
    gm = RefusingManager(running=True)
    lock = wire(gm, [_free()])
    session = GatewaySession()

    result = session.recover(gm, url=_URL, emit=lambda _: None, lock=lock, force=True)

    assert "restart(force)" in gm.calls
    assert result.phase is SessionPhase.FREE


def test_establish_never_forces_a_restart(wire):
    """From BORROWED with `allow_restart`, the owner asks for a restart and lets the guard decide:
    a borrowed session is not refused, so it goes ahead — but never with `force`."""
    gm = FakeManager(running=True)
    lock = wire(gm, [_borrowed(), _free()])
    session = GatewaySession()

    _establish(session, gm, lock, allow_restart=True, login_timeout=20)

    assert "restart" in gm.calls and "restart(force)" not in gm.calls


# ── Unreachable ──────────────────────────────────────────────────────────────


def test_an_unreachable_gateway_is_never_sent_a_login_page(wire):
    """Nothing is read from, and no page opened for, a gateway that does not answer."""
    gm = FakeManager(running=True, reachable=False)
    lock = wire(gm, [_free()])
    session = GatewaySession()

    result = _establish(session, gm, lock)

    assert result.phase is SessionPhase.DOWN
    assert "open_login_page" not in gm.calls
    assert "read_state" not in gm.calls


# ── The invariant, over every starting phase ─────────────────────────────────


@pytest.mark.parametrize(
    "reading,confirm",
    [
        (_authenticated(), True),
        (_authenticated(), False),
        (_free(), True),
        (_contested(), False),
        (_borrowed(), False),
    ],
)
def test_the_login_page_is_never_opened_without_a_read_first(wire, reading, confirm):
    """The CLAUDE.md rule, asserted over every branch rather than one of them."""
    gm = FakeManager(running=True)
    lock = wire(gm, [reading], confirmations=[confirm])
    session = GatewaySession()

    _establish(session, gm, lock, login_timeout=20)

    if "open_login_page" in gm.calls:
        assert gm.calls.index("read_state") < gm.calls.index("open_login_page")


def test_a_timed_out_login_does_not_leave_the_session_suspended(wire):
    """AUTHENTICATING left in place would suspend every tickler indefinitely."""
    gm = FakeManager(running=True)
    lock = wire(gm, [_free()])
    session = GatewaySession()

    result = _establish(session, gm, lock, login_timeout=20)

    assert result.phase is not SessionPhase.AUTHENTICATING
    assert result.is_suspended is False
    assert "IBKR Mobile" in result.detail or "Mobile" in result.detail


# ── Gap #93: the owner reads the gateway's log around the login page ─────────────
#
# A login IBKR refused leaves the HTTP side exactly as no login does, so the owner — the one
# place every route to a login passes through — reads the gateway's own log through
# `read_login`, which defaults to `manager.read_login_events` (the one spawn module). Operator,
# 2026-10-12: a note before the page, and the wait ended at once when the new login is refused
# too ("B plus the early stop").

_VALIDATED_AT_10 = [
    LoginEvent("2026-10-07 10:00:00", "login", ""),
    LoginEvent("2026-10-07 10:00:00", "authenticated", ""),
]
_REFUSED_AT_11 = [
    LoginEvent("2026-10-07 11:00:00", "login", ""),
    LoginEvent("2026-10-07 11:00:00", "validate", "401"),
    LoginEvent("2026-10-07 11:00:13", "giving up", ""),
]
_VALIDATING_AT_12 = [
    LoginEvent("2026-10-07 12:00:00", "login", ""),
    LoginEvent("2026-10-07 12:00:01", "validate", "401"),
]


def _log_reads(*readings: tuple[list[LoginEvent] | None, str]) -> Any:
    """A `read_login` returning each reading in turn, the last repeating."""
    queue = list(readings)

    def read() -> tuple[list[LoginEvent] | None, str]:
        """Stand-in for `manager.read_login_events`."""
        return queue.pop(0) if len(queue) > 1 else queue[0]

    return read


@pytest.mark.parametrize(
    ("before", "noted"),
    [(_VALIDATED_AT_10 + _REFUSED_AT_11, True), (_REFUSED_AT_11 + _VALIDATED_AT_10, False)],
    ids=["last-login-refused", "last-login-validated"],
)
def test_a_refused_last_login_is_named_before_the_login_page_opens(wire, before, noted):
    """From FREE the owner opened the page with no word, whatever the log held — the 10-07
    record (a browser login IBKR refused, then the launcher, then a second refused login at
    17:55:30 UTC) fits that, though no launcher output was kept to prove it. The note comes
    first, and only when the last login was refused: a warning on every login would be one
    nobody reads."""
    gm = FakeManager(running=True)
    lock = wire(gm, [_free(), _authenticated()], confirmations=[True])
    session = GatewaySession()

    _establish(
        session,
        gm,
        lock,
        read_login=_log_reads((before, "")),
        emit=lambda line: gm.calls.append(line),
    )

    notes = [i for i, c in enumerate(gm.calls) if "IBKR refused the last gateway login" in c]
    assert bool(notes) is noted
    assert all(i < gm.calls.index("open_login_page") for i in notes)


def test_a_login_ibkr_is_still_answering_gets_no_second_page(wire):
    """The one case the owner gained in the move (register F45, step 2): the newest login has no
    answer yet — IBKR takes up to 13 s (measured), or the gateway stalled mid-validation — so a
    second page would be a second login against the one being answered. The pre-flight's
    VALIDATING rule, applied where the page would open; the FREE reading is returned, no lock
    taken, and the guidance said."""
    gm = WindowManager(running=True)
    lock = wire(gm, [_free()])
    session = GatewaySession()
    lines: list[str] = []

    result = _establish(
        session, gm, lock, read_login=_log_reads((_VALIDATED_AT_10 + _VALIDATING_AT_12, "")), emit=lines.append
    )

    assert "open_login_page" not in gm.calls
    assert result.phase is SessionPhase.FREE and result.is_suspended is False
    assert not lock.path.exists()
    assert any("has not answered the last gateway login" in line for line in lines), lines
    assert any("Do not log in again" in line for line in lines), lines


def test_a_newer_refused_login_ends_the_wait_at_once(wire):
    """The early stop: a login refused after the page opened ends the wait with the guidance,
    instead of sitting out the 300 s. "Newer" is the log's own timestamps — a login line later
    than the last one seen before the page — never a clock."""
    gm = FakeManager(running=True)
    lock = wire(gm, [_free()])
    session = GatewaySession()

    result = _establish(
        session,
        gm,
        lock,
        login_timeout=300,
        read_login=_log_reads((_VALIDATED_AT_10, ""), (_VALIDATED_AT_10 + _REFUSED_AT_11, "")),
    )

    assert "IBKR's website" in result.detail
    assert gm.calls.count("read_state") <= 3  # stopped on the first poll, not after 60
    assert result.is_suspended is False


@pytest.mark.parametrize(
    "before",
    [(_REFUSED_AT_11, ""), (None, "no such container")],
    ids=["the-refusal-already-seen", "log-unreadable-before-the-page"],
)
def test_only_a_login_made_after_the_page_opened_can_end_the_wait(wire, before):
    """The operator's one gateway login after the website login must get its full wait: the
    refusal the note already named is not news. And with no readable log before the page,
    nothing tells an old refusal from a new one — so the wait runs as it always did."""
    gm = FakeManager(running=True)
    lock = wire(gm, [_free()])
    session = GatewaySession()

    result = _establish(
        session,
        gm,
        lock,
        login_timeout=20,
        read_login=_log_reads(before, (_REFUSED_AT_11, "")),
    )

    assert "IBKR's website" not in result.detail
    assert gm.calls.count("read_state") > 3


# ── The login window (gap #102, core F44) ────────────────────────────────────


def test_the_login_window_closes_at_the_first_authenticated_and_connected_reading(wire):
    """Operator 2026-10-13: "when connected and authenificated, the window closes itself" — at the
    first such reading, before the data half is confirmed: the login's job is done there."""
    gm = WindowManager(running=True)
    lock = wire(gm, [_free(), _authenticated(), _authenticated()], confirmations=[False, True])
    session = GatewaySession()

    _establish(session, gm, lock)

    assert gm.calls.count("close_login_window") == 1
    third_read = [i for i, c in enumerate(gm.calls) if c == "read_state"][2]
    assert gm.calls.index("close_login_window") < third_read


@pytest.mark.parametrize("ending", ["timed-out", "borrowed", "refused"])
def test_a_login_that_did_not_validate_leaves_the_window_open_and_says_so(wire, ending):
    """Operator 2026-10-13: "Do not auto-close if it fails! … user can acknoledge the failure and
    manually clsoe the window" — and the message says to."""
    gm = WindowManager(running=True)
    lock = wire(gm, [_free(), _borrowed()] if ending == "borrowed" else [_free()])
    session = GatewaySession()
    kw: dict[str, Any] = {"login_timeout": 20}
    if ending == "refused":
        kw = {
            "login_timeout": 300,
            "read_login": _log_reads((_VALIDATED_AT_10, ""), (_VALIDATED_AT_10 + _REFUSED_AT_11, "")),
        }
    lines: list[str] = []

    _establish(session, gm, lock, emit=lines.append, **kw)

    assert "close_login_window" not in gm.calls
    assert any("Close the login window" in line for line in lines), lines


def test_a_window_that_was_not_ours_to_close_is_named(wire):
    """Measured 2026-10-13: a launch on a profile already running is handed to it, and the handle
    cannot reach that window. Said, not hidden."""
    gm = WindowManager(running=True, ours=False)
    lock = wire(gm, [_free(), _authenticated()])
    session = GatewaySession()
    lines: list[str] = []

    _establish(session, gm, lock, emit=lines.append)

    assert any("close it yourself" in line.lower() for line in lines), lines


def test_a_browser_tab_gets_no_window_line(wire):
    """No handle (the core fell back to a tab, or the pinned 2.1.0): nothing to close, nothing said
    about a window — today's lines, unchanged."""
    gm = FakeManager(running=True)
    lock = wire(gm, [_free()])
    session = GatewaySession()
    lines: list[str] = []

    _establish(session, gm, lock, emit=lines.append, login_timeout=20)

    assert not any("login window" in line.lower() for line in lines), lines


# ═══════════════════════════════════════════════════════════════════════════
# Stage 3 — polling, and the last session-affecting write.
#
# These migrated from tests/test_status.py on 2026-08-06 with the code they
# describe: `ssodh/init` was ConnectivityChecker's, and a monitor able to
# re-establish a session is a second authority over it (plan invariant §3.1).
# ═══════════════════════════════════════════════════════════════════════════


def _resp(status: int, body: object) -> MagicMock:
    """A stand-in requests.Response with the given status and JSON body."""
    m = MagicMock()
    m.status_code = status
    m.json.return_value = body
    return m


def test_soft_recovery_reports_success_only_when_the_body_says_authenticated(monkeypatch):
    """HTTP 200 is not the answer — the body is.

    IBKR signals a real competing session with HTTP 200 and `authenticated: false` rather
    than an error status, so a status-code-only check would report a recovery that did
    not happen.
    """
    body = {"iserver": {"authStatus": {"authenticated": True, "connected": True}}}
    monkeypatch.setattr("ibkr_core_mcp.gateway.session.requests.post", lambda *a, **k: _resp(200, body))
    assert attempt_soft_recovery(_URL) is True


def test_soft_recovery_200_but_not_authenticated_is_a_failure(monkeypatch):
    """The competing-session shape: 200, with the body saying it did not work."""
    body = {"iserver": {"authStatus": {"authenticated": False, "connected": True}}}
    monkeypatch.setattr("ibkr_core_mcp.gateway.session.requests.post", lambda *a, **k: _resp(200, body))
    assert attempt_soft_recovery(_URL) is False


def test_soft_recovery_non_200_is_a_failure(monkeypatch):
    """Anything but 200 means the bridge was not raised."""
    monkeypatch.setattr("ibkr_core_mcp.gateway.session.requests.post", lambda *a, **k: _resp(500, {}))
    assert attempt_soft_recovery(_URL) is False


def test_soft_recovery_never_raises(monkeypatch):
    """It runs when things are already broken, so it must survive that."""

    def boom(*a, **k):
        """Fail the way an unreachable gateway does."""
        raise OSError("refused")

    monkeypatch.setattr("ibkr_core_mcp.gateway.session.requests.post", boom)
    assert attempt_soft_recovery(_URL) is False


def test_soft_recovery_never_sets_compete_true(monkeypatch):
    """`compete: true` would force-evict a live IBKR Mobile or TWS session.

    The single brokerage session per username means eviction is a real consequence, not a
    theoretical one — this must never be flipped to win a race.
    """
    captured: dict[str, Any] = {}

    def capture(*args, **kwargs):
        """Record the JSON body the call would send."""
        captured.update(kwargs.get("json") or {})
        return _resp(200, {"iserver": {"authStatus": {"authenticated": True}}})

    monkeypatch.setattr("ibkr_core_mcp.gateway.session.requests.post", capture)
    attempt_soft_recovery(_URL)
    assert captured.get("compete") is False


@pytest.mark.asyncio
async def test_polling_is_skipped_entirely_while_suspended():
    """A poll is a `/tickle`, and a `/tickle` renews.

    Polling through a login or a recovery would be the owner defeating its own
    suspension — the precise failure the plan exists to remove.
    """
    session = GatewaySession()
    session.publish(declare(SessionPhase.AUTHENTICATING))
    with patch.object(session, "read_now") as read:
        await session._poll_once()
    read.assert_not_called()


@pytest.mark.asyncio
async def test_soft_recovery_fires_only_from_a_previously_live_session(monkeypatch):
    """IBKR's documented soft-timeout signature, and only after the session worked.

    `ssodh/init` raises the bridge; it cannot supply an authentication that never
    happened (measured 2026-08-05 — two inits moved `connected` False→True and left
    `authenticated` False both times). Firing it on a settling login would be a write
    against a session nobody has established yet.
    """
    soft = GatewayState(reachable=True, authenticated=False, connected=True)
    calls: list[str] = []

    def _tried(*a, **k):
        """Record the attempt and report that recovery did not succeed."""
        calls.append("tried")
        return False

    monkeypatch.setattr(
        "ibkr_core_mcp.gateway.session.attempt_soft_recovery",
        _tried,
    )

    # From FREE: no recovery — nothing was ever established.
    session = GatewaySession()
    session.publish(observe(_free(), False))
    with patch.object(session, "read_now", return_value=observe(soft, False)):
        await session._poll_once()
    assert calls == []

    # From LIVE: the documented soft timeout, so it is attempted.
    session.publish(observe(_authenticated(), True))
    with patch.object(session, "read_now", return_value=observe(soft, False)):
        await session._poll_once()
    assert calls == ["tried"]


@pytest.mark.asyncio
async def test_no_soft_recovery_on_a_hard_disconnect(monkeypatch):
    """`connected` false is not a soft timeout; init cannot help and must not be sent."""
    calls: list[str] = []

    def _tried(*a, **k):
        """Record the attempt and report that recovery did not succeed."""
        calls.append("tried")
        return False

    monkeypatch.setattr(
        "ibkr_core_mcp.gateway.session.attempt_soft_recovery",
        _tried,
    )
    session = GatewaySession()
    session.publish(observe(_authenticated(), True))

    with patch.object(session, "read_now", return_value=observe(_down(), False)):
        await session._poll_once()

    assert calls == []


# ── F1: the two interpretations of one reading must agree, by mechanism ──────


def test_classify_and_verdict_agree_over_every_possible_reading():
    """`classify` and `gateway_preflight.verdict` interpret the same fields — exhaustively.

    `classify`'s docstring says it "deliberately matches `gateway_preflight.verdict` step
    for step, so the two can never disagree about the same reading". A docstring is a
    claim, not a mechanism: nothing stopped either function from being edited alone, and
    two definitions of "the session is borrowed" drifting apart is exactly the failure
    this project has already been bitten by elsewhere (the realised-P&L rule, the
    accounting day boundary).

    So the agreement is asserted here over the **complete cross-product** of every field
    either function reads — 512 readings — rather than over a handful of examples. A
    representative case is what the original lifecycle defect passed.

    The correspondence is written as data because it is not one-to-one: `verdict` has no
    `DEGRADED`, since the pre-flight makes no data call and cannot tell a confirmed
    session from an authenticated-but-dark one. `EXIT_READY` therefore legitimately
    covers both, and that is the single place the two are allowed to differ in
    granularity — never in conclusion.
    """
    from itertools import product

    from ibkr_core_mcp.gateway.preflight import (
        EXIT_BORROWED,
        EXIT_CONTESTED,
        EXIT_FREE,
        EXIT_READY,
        EXIT_UNREACHABLE,
        verdict,
    )

    equivalent = {
        EXIT_UNREACHABLE: {SessionPhase.DOWN},
        EXIT_READY: {SessionPhase.LIVE, SessionPhase.DEGRADED},
        EXIT_CONTESTED: {SessionPhase.CONTESTED},
        EXIT_BORROWED: {SessionPhase.BORROWED},
        EXIT_FREE: {SessionPhase.FREE},
    }

    readings = 0
    for (
        reachable,
        authenticated,
        connected,
        competing,
        collision,
        sso_valid,
        client_app,
        user_id,
        data_ok,
    ) in product(
        (False, True),
        (False, True),
        (False, True),
        (False, True),
        (False, True),
        (False, True),
        ("", "IBKRMOBILE_000.a-000"),
        (None, 99999999),
        (False, True),
    ):
        state = GatewayState(
            reachable=reachable,
            authenticated=authenticated,
            connected=connected,
            competing=competing,
            collision=collision,
            sso_valid=sso_valid,
            client_app=client_app,
            user_id=user_id,
        )
        code, _, _ = verdict(state)
        phase = classify(state, data_ok)
        readings += 1
        assert phase in equivalent[code], (
            f"verdict() and classify() disagree about {state!r} (data_ok={data_ok}): "
            f"exit code {code} vs phase {phase.value}. They read the same fields and "
            "must reach the same conclusion — change both, or derive one from the other."
        )

    # Pinned so a field added to GatewayState without extending this loop is visible as a
    # dropped count rather than passing quietly over a smaller space than it claims.
    assert readings == 512


# ── Moved from the consumer's preflight tests: the one session write that lived beside them ──


def test_release_reports_ibkrs_own_status_field_not_merely_a_200():
    """`{"status": false}` with HTTP 200 is a failed release — the slot is not free."""
    ok_resp, bad_resp = MagicMock(), MagicMock()
    ok_resp.status_code = bad_resp.status_code = 200
    ok_resp.json.return_value = {"status": True}
    bad_resp.json.return_value = {"status": False}

    with patch("ibkr_core_mcp.gateway.session.requests.post", return_value=ok_resp):
        assert release_session(_URL)[0] is True
    with patch("ibkr_core_mcp.gateway.session.requests.post", return_value=bad_resp):
        assert release_session(_URL)[0] is False


# ── Condition C, the behavioural half: the two writes pin their URL before sending ───────────


@pytest.mark.parametrize("write", [release_session, attempt_soft_recovery])
def test_a_session_write_refuses_a_non_loopback_url_before_any_request(write, monkeypatch):
    """`test_tls_policy.py` holds the pin's line in source; this holds what it does: a URL that is
    not loopback never reaches `requests`."""
    sent: list[str] = []
    monkeypatch.setattr("ibkr_core_mcp.gateway.session.requests.post", lambda *a, **k: sent.append(str(a)))
    with pytest.raises(ConfigError):
        write("https://gateway.example.invalid/v1/api")
    assert sent == []


# ── Condition E: the lock is private, and a pid below 1 is malformed ────────────────────────


@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_the_lock_file_is_private_and_its_directory_too(tmp_path):
    """0600 on the file, 0700 on a directory the lock created — the lock sits beside the trade
    store, in the operator's data directory, and nothing there is for another user."""
    lock = SuspendLock(path=tmp_path / "fresh" / "session.suspend")
    lock.acquire("login in progress")
    try:
        assert stat.S_IMODE(lock.path.stat().st_mode) == 0o600
        assert stat.S_IMODE(lock.path.parent.stat().st_mode) == 0o700
        assert json.loads(lock.path.read_text())["pid"] == os.getpid()
    finally:
        lock.release()
    assert not lock.path.exists()


@pytest.mark.parametrize("pid", [0, -1])
def test_a_lock_naming_pid_zero_or_negative_is_malformed_not_active(tmp_path, pid):
    """`os.kill(0, 0)` and `os.kill(-1, 0)` address process groups and succeed (review probes M3
    and M4): a lock saying `pid: 0` would have suspended every keepalive forever."""
    path = tmp_path / "session.suspend"
    path.write_text(json.dumps({"pid": pid, "reason": "x", "since": "x"}))
    assert SuspendLock.is_active(path) is False
    assert _pid_alive(pid) is False


def test_pid_alive_on_posix_asks_the_kernel_with_signal_zero():
    assert _pid_alive(os.getpid(), windows=False) is True
    assert _pid_alive(999999, windows=False) is False


def test_pid_alive_on_windows_asks_kernel32_and_closes_the_handle():
    """On Windows `os.kill(pid, 0)` would TERMINATE the process (the `os` documentation: any
    signal but the two console events "will cause the process to be unconditionally killed"),
    so the check is `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)`: a handle means alive and
    is closed at once; 0 means gone."""

    class Kernel32:
        def __init__(self, handle: int) -> None:
            self.handle = handle
            self.calls: list[tuple[str, tuple[Any, ...]]] = []

        def OpenProcess(self, access: int, inherit: bool, pid: int) -> int:
            self.calls.append(("OpenProcess", (access, inherit, pid)))
            return self.handle

        def CloseHandle(self, handle: int) -> int:
            self.calls.append(("CloseHandle", (handle,)))
            return 1

    alive = Kernel32(handle=42)
    assert _pid_alive(1234, windows=True, kernel32=alive) is True
    assert alive.calls == [("OpenProcess", (0x1000, False, 1234)), ("CloseHandle", (42,))]

    gone = Kernel32(handle=0)
    assert _pid_alive(1234, windows=True, kernel32=gone) is False
    assert gone.calls == [("OpenProcess", (0x1000, False, 1234))]


# ── Condition F: `compete` is a Final False, spelled once ───────────────────────────────────


def test_compete_is_a_final_false_and_the_only_spelling_in_the_posted_body():
    """`compete: true` evicts a live IBKR Mobile or TWS session. The behavioural test above sees
    what one call sends; this holds the source: the key appears once, its value is the constant,
    and the constant is annotated `Final` so a later assignment is a type error."""
    assert COMPETE is False
    tree = ast.parse(Path(session_module.__file__).read_text(encoding="utf-8"))
    spellings = [node for node in ast.walk(tree) if isinstance(node, ast.Constant) and node.value == "compete"]
    assert len(spellings) == 1, "the wire key `compete` must be spelled in exactly one place"
    (body,) = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Dict) and any(isinstance(k, ast.Constant) and k.value == "compete" for k in node.keys)
    ]
    value = dict(zip([ast.unparse(k) for k in body.keys if k is not None], body.values, strict=True))["'compete'"]
    assert isinstance(value, ast.Name) and value.id == "COMPETE"
    (declaration,) = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "COMPETE"
    ]
    assert ast.unparse(declaration.annotation) == "Final"
    assert isinstance(declaration.value, ast.Constant) and declaration.value.value is False


# ── The owner reads the gateway's log itself ────────────────────────────────────────────────


def test_the_owner_reads_the_gateway_log_itself_by_default(wire, monkeypatch):
    """The consumer handed the reader in from its one spawn module; here that module is in the
    package, so `_establish` defaults to `manager.read_login_events` and a caller passes nothing."""
    gm = FakeManager(running=True)
    lock = wire(gm, [_free(), _authenticated()], confirmations=[True])
    reads: list[float] = []

    def recorder(timeout: float = 15.0) -> tuple[list[LoginEvent] | None, str]:
        reads.append(timeout)
        return None, "no container in a unit test"

    monkeypatch.setattr("ibkr_core_mcp.gateway.session.read_login_events", recorder)
    _establish(GatewaySession(), gm, lock)

    assert reads, "the owner did not read the gateway's log before the login page"


# ── The keepalive loop: the host-side tickler that honours the lock (register F45, step 2) ─────
#
# Replaces the consumer's bash script and its tests: an active lock → SUSPENDED and no request;
# 200 → OK and the sleep assertion held; anything else → WARN and the assertion released; a line
# only on a state change; the URL pinned before the first request.


class FakeAwake:
    """Records `hold` / `release` in order."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def hold(self) -> None:
        self.calls.append("hold")

    def release(self) -> None:
        self.calls.append("release")


def _tickle(status: int | Exception):
    def get(url, timeout=5.0, verify=True):
        if isinstance(status, Exception):
            raise status
        return _resp(status, {})

    return get


def _loop(monkeypatch, tmp_path, status, *, ticks: int = 1, lock_active: bool = False) -> tuple[list[str], FakeAwake]:
    monkeypatch.setattr("ibkr_core_mcp.gateway.session.requests.get", _tickle(status))
    lock = tmp_path / "session.suspend"
    if lock_active:
        lock.write_text(json.dumps({"pid": os.getpid(), "reason": "login", "since": "x"}))
    lines: list[str] = []
    awake = FakeAwake()
    remaining = {"n": ticks}

    def sleep(_seconds: float) -> None:
        remaining["n"] -= 1
        if remaining["n"] <= 0:
            raise KeyboardInterrupt  # the operator's Ctrl-C; `once=False` loops until then

    with pytest.raises(KeyboardInterrupt):
        keepalive_loop(_URL, lock_path=lock, interval=55.0, awake=awake, sleep=sleep, say=lines.append)
    return lines, awake


def test_an_active_lock_means_suspended_and_no_request(monkeypatch, tmp_path):
    """The one renewer outside every host process; the lock is the only thing that can reach it."""
    sent: list[str] = []
    monkeypatch.setattr("ibkr_core_mcp.gateway.session.requests.get", lambda *a, **k: sent.append(str(a)))
    lock = tmp_path / "session.suspend"
    lock.write_text(json.dumps({"pid": os.getpid(), "reason": "login", "since": "x"}))
    lines: list[str] = []
    awake = FakeAwake()

    keepalive_loop(_URL, lock_path=lock, awake=awake, say=lines.append, once=True)

    assert sent == []
    assert any("SUSPENDED" in line for line in lines), lines
    assert "hold" not in awake.calls, "the machine is not held awake for a session that does not exist yet"


def test_a_200_is_ok_and_holds_the_machine_awake(monkeypatch, tmp_path):
    lines, awake = _loop(monkeypatch, tmp_path, 200)
    assert any("OK  (HTTP 200)" in line for line in lines), lines
    assert awake.calls[0] == "hold"


@pytest.mark.parametrize(
    ("status", "state", "calls"),
    [(200, "OK", ["hold"]), (401, "WARN", ["release"]), (OSError("refused"), "WARN", ["release"])],
    ids=["200", "401", "unreachable"],
)
def test_one_tick_holds_on_ok_and_releases_on_warn(monkeypatch, tmp_path, status, state, calls):
    """The tick itself, apart from the loop's own release on the way out: the assertion follows the
    gateway's answer, so a Mac is held awake for a session worth keeping and for nothing else."""
    monkeypatch.setattr("ibkr_core_mcp.gateway.session.requests.get", _tickle(status))
    awake = FakeAwake()
    assert _tick(_URL, tmp_path / "session.suspend", awake)[0] == state
    assert awake.calls == calls


@pytest.mark.parametrize("status", [401, 500, OSError("refused")], ids=["401", "500", "unreachable"])
def test_anything_else_is_warn_and_releases_the_assertion(monkeypatch, tmp_path, status):
    """A 401 is a gateway with no session: nothing worth keeping the Mac awake for. An exception
    reads as HTTP 000, as `curl` reported it; its text is not printed."""
    lines, awake = _loop(monkeypatch, tmp_path, status)
    warn = [line for line in lines if "WARN" in line]
    assert warn and "gateway may be down or not authenticated" in warn[0], lines
    assert awake.calls[0] == "release", "released on the WARN tick itself, not only when the loop ends"
    if isinstance(status, Exception):
        assert "HTTP 000" in warn[0] and "refused" not in warn[0]


def test_a_line_only_on_a_state_change(monkeypatch, tmp_path):
    """Under launchd the loop runs for months; a line per tick would grow the log unbounded."""
    lines, _ = _loop(monkeypatch, tmp_path, 200, ticks=4)
    ok = [line for line in lines if "OK  (HTTP 200)" in line]
    assert len(ok) == 1, lines


def test_the_first_line_names_what_is_tickled_and_how_often(monkeypatch, tmp_path):
    lines, _ = _loop(monkeypatch, tmp_path, 200)
    assert lines[0].startswith("Starting") and f"{_URL}/tickle" in lines[0] and "55" in lines[0]


def test_the_assertion_is_released_when_the_loop_ends(monkeypatch, tmp_path):
    """Ctrl-C or SIGTERM: the `finally` releases `caffeinate`, or the child would hold the Mac
    awake after the daemon is gone — the bash script's `trap cleanup EXIT INT TERM`."""
    _, awake = _loop(monkeypatch, tmp_path, 200)
    assert awake.calls[-1] == "release"


def test_the_keepalive_refuses_a_non_loopback_url_before_any_request(monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr("ibkr_core_mcp.gateway.session.requests.get", lambda *a, **k: sent.append(str(a)))
    with pytest.raises(ConfigError):
        keepalive_loop("ftp://nope", awake=FakeAwake(), say=lambda _: None, once=True)
    assert sent == []


# ── Every session write leaves an audit record (MCP security checklist 8.1; register F45, step 2) ─


def _records(tmp_path) -> list[dict[str, Any]]:
    path = tmp_path / "audit.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_release_session_leaves_one_record_with_ibkrs_answer(monkeypatch, tmp_path):
    monkeypatch.setattr("ibkr_core_mcp.gateway.session.requests.post", lambda *a, **k: _resp(200, {"status": False}))
    release_session(_URL)
    (record,) = _records(tmp_path)
    assert record["kind"] == "session_write" and record["action"] == "logout"
    assert record["actor"] == "operator" and record["decision"] == "not_released"


def test_soft_recovery_leaves_one_record_by_the_owner(monkeypatch, tmp_path):
    body = {"iserver": {"authStatus": {"authenticated": True, "connected": True}}}
    monkeypatch.setattr("ibkr_core_mcp.gateway.session.requests.post", lambda *a, **k: _resp(200, body))
    attempt_soft_recovery(_URL)
    (record,) = _records(tmp_path)
    assert record["kind"] == "session_write" and record["action"] == "ssodh_init"
    assert record["actor"] == "owner" and record["decision"] == "recovered"


def test_a_failed_write_records_the_exceptions_type_and_never_its_text(monkeypatch, tmp_path):
    """A `requests` error carries its URL; the record carries the type (as `redact_error` would
    the text, but the record needs no text at all)."""

    def boom(*a, **k):
        raise OSError("refused at https://localhost:5055/v1/api?token=secret-value")

    monkeypatch.setattr("ibkr_core_mcp.gateway.session.requests.post", boom)
    release_session(_URL)
    (record,) = _records(tmp_path)
    assert record["decision"] == "error" and record["outcome"] == "OSError"
    assert "secret-value" not in json.dumps(record)


@pytest.mark.parametrize("refused", [False, True], ids=["restarted", "refused"])
def test_recover_records_the_restart_or_its_refusal(wire, tmp_path, refused):
    gm = RefusingManager(running=True) if refused else FakeManager(running=True)
    lock = wire(gm, [_authenticated() if refused else _free()], confirmations=[True])
    session = GatewaySession()

    session.recover(gm, url=_URL, emit=lambda _: None, lock=lock)

    (record,) = [r for r in _records(tmp_path) if r["kind"] == "session_write"]
    assert record["action"] == "restart" and record["actor"] == "operator"
    assert record["params"] == {"force": False}
    if refused:
        assert record["decision"] == "refused" and record["outcome"] == f"code {EXIT_READY}"
    else:
        assert record["decision"] == "restarted" and record["outcome"] == "ok"
