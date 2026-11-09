"""No unit test can start a process that reaches the operator's desktop or a daemon (register F45,
door 6, 2026-11-09): `docker`, `open` and `caffeinate`, refused by name.

The suite has structural guards for the network (pytest-socket), for the operator's data (the
audit hook of `test_no_real_data_io.py`) and for a person (the five doors of
`test_no_human_reached.py`). It had none for the machine. `gateway/manager.py` drives the docker
CLI — `docker restart` ends the live IBKR session held in the container's Java process —
launches Docker Desktop with `open -a Docker`, and (from F45) holds a `caffeinate -i` assertion
for the keepalive. Every test of it patches `subprocess.run` or `subprocess.Popen` by name, and
until today that was what kept a unit test off the operator's gateway: a test that patched one
call and not another, or a mutant that moved the call, would have restarted the live session
from a unit run — register F32's class (a real Gate 2 dialog opened on the operator's screen
from a mutation run, 2026-10-01), on the machine instead of the screen.

Inventoried before the door was built (2026-11-09, a recording hook over one full run): 16 real
starts, every one `git`, `python3.11` or `ruff`. So the door refuses the three names and exempts
nothing but integration tests, which run `docker exec` on the gateway's own log by design.

**Every test here is safe on a broken guard.** `docker --version` prints and exits; the `open`
and `caffeinate` cases run a decoy of that name linked to `true` — the real `open -a Docker`
would start Docker Desktop and the real `caffeinate -i` would hold the Mac awake, so neither is
ever the argv — and each asserts the refusal came before anything ran.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests import conftest

pytestmark = pytest.mark.security

_TRUE = shutil.which("true")


@contextlib.contextmanager
def refused(door: str):
    """The block must end in the guard's refusal naming `door`, and leave its record.

    The record is removed again: these refusals are the test's subject, not a test reaching the
    desktop, and `pytest_sessionfinish` fails the run on any that remain.
    """
    before = len(conftest._desktop_refusals)
    with pytest.raises(pytest.fail.Exception, match="reach the desktop") as caught:
        yield caught
    recorded = conftest._desktop_refusals[before:]
    del conftest._desktop_refusals[before:]
    assert len(recorded) == 1 and door in recorded[0], recorded


def _decoy(tmp_path: Path, name: str) -> str:
    """An executable named `name` that does nothing: a link to `true`."""
    assert _TRUE is not None
    decoy = tmp_path / name
    decoy.symlink_to(_TRUE)
    return str(decoy)


def test_docker_is_refused_by_name():
    """The container holds the live IBKR session; `docker restart` ends it. On a broken guard
    `docker --version` prints and exits — nothing is started."""
    assert conftest._DESKTOP_GUARD["armed"] is True  # before anything real
    with refused("docker"):
        subprocess.run(["docker", "--version"], capture_output=True, check=False)


@pytest.mark.skipif(_TRUE is None, reason="needs a `true` executable to stand in for `open`")
def test_opening_docker_desktop_is_refused(tmp_path):
    """`ensure_docker_running()`'s `open -a Docker` starts Docker Desktop on macOS. The decoy keeps
    the real command off this machine: on a broken guard `true -a Docker` runs nothing."""
    assert conftest._DESKTOP_GUARD["armed"] is True
    with refused("open"):
        subprocess.run([_decoy(tmp_path, "open"), "-a", "Docker"], capture_output=True, check=False)


@pytest.mark.skipif(_TRUE is None, reason="needs a `true` executable to stand in for `caffeinate`")
def test_caffeinate_is_refused(tmp_path):
    """The keepalive's sleep assertion (F45 step 2). A real `caffeinate -i` from a test would hold
    the Mac awake until killed; the decoy runs nothing."""
    assert conftest._DESKTOP_GUARD["armed"] is True
    with refused("caffeinate"):
        subprocess.Popen([_decoy(tmp_path, "caffeinate"), "-i"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@pytest.mark.skipif(_TRUE is None, reason="needs a `true` executable to stand in for `caffeinate`")
def test_a_shell_command_string_is_read_word_by_word(tmp_path):
    """`os.system` audits one string; the command is found as a word of it, by its last path
    component. Quoted, since the decoy's path may hold a space."""
    decoy = _decoy(tmp_path, "caffeinate")
    with refused("caffeinate"):
        os.system(f'"{decoy}" -i')  # noqa: S605 - refused before it runs; the decoy is `true`


def test_the_suites_own_starts_are_not_refused():
    """The inventory's names stay allowed: the guard is by name, not blanket. `git` and the
    interpreter are what the suite really starts; `bash` is what ClaudIA's inventory added."""
    assert subprocess.run(["git", "--version"], capture_output=True, check=False).returncode == 0
    assert subprocess.run([sys.executable, "-c", "pass"], capture_output=True, check=False).returncode == 0
    if shutil.which("bash") is not None:
        assert subprocess.run(["bash", "-c", "true"], capture_output=True, check=False).returncode == 0


@pytest.mark.skipif(_TRUE is None, reason="needs a `true` executable to stand in for `caffeinate`")
def test_a_refusal_swallowed_by_except_exception_still_fails_the_run(tmp_path):
    """`pytest.fail` is a `BaseException`, so `except Exception` cannot absorb it; a broader
    swallow leaves the record, and the record is what turns the run red at its end. Through the
    `caffeinate` decoy, so the `docker` mutation turns exactly its own test red."""
    before = len(conftest._desktop_refusals)
    with contextlib.suppress(BaseException):  # the swallow this test is about
        subprocess.run([_decoy(tmp_path, "caffeinate"), "-i"], capture_output=True, check=False)
    recorded = conftest._desktop_refusals[before:]
    del conftest._desktop_refusals[before:]
    assert recorded == ["subprocess.Popen caffeinate"], recorded
    assert conftest._desktop_violations(recorded) == ["a test started a desktop command: subprocess.Popen caffeinate"]


def test_the_run_turns_red_at_its_end_when_a_desktop_command_was_recorded(monkeypatch, capsys):
    """The wiring behind the pure function, as for the human doors: with one record the session's
    exit status becomes 1 and the report names the door; the other two reports stay silent."""

    class _Session:
        """The two attributes `pytest_sessionfinish` reads."""

        exitstatus = 0

        class config:
            """A config whose plugin manager has no terminal reporter."""

            class pluginmanager:
                """Answers every plugin lookup with None."""

                @staticmethod
                def get_plugin(name):
                    """No terminal reporter: the report goes to stdout."""
                    return None

    monkeypatch.setattr(conftest, "_operator_refusals", [])
    monkeypatch.setattr(conftest, "_human_refusals", [])
    monkeypatch.setattr(conftest, "_desktop_refusals", ["subprocess.Popen docker"])
    loud = _Session()
    conftest.pytest_sessionfinish(loud, 0)  # type: ignore[arg-type]
    out = capsys.readouterr().out
    assert loud.exitstatus == 1
    assert "A DESKTOP COMMAND REACHED FOR" in out and "subprocess.Popen docker" in out
    assert "A HUMAN GATE REACHED FOR" not in out and "REAL DATA REACHED FOR" not in out


def test_an_integration_test_is_exempt_from_its_setup_to_its_teardown(monkeypatch):
    """A live test reads the gateway's own log through `docker exec` by design (F45's
    `tests/test_gateway_live.py`), so the door opens for an integration-marked item at setup and
    shuts again at teardown — the operator-data hook's rule, and the same two pytest hooks."""

    class _Item:
        """An item carrying the `integration` marker."""

        @staticmethod
        def get_closest_marker(name):
            """Only `integration` is set."""
            return object() if name == "integration" else None

    monkeypatch.setitem(conftest._DESKTOP_GUARD, "armed", True)
    conftest.pytest_runtest_setup(_Item())
    assert conftest._DESKTOP_GUARD["armed"] is False
    conftest.pytest_runtest_teardown(_Item(), None)
    assert conftest._DESKTOP_GUARD["armed"] is True
