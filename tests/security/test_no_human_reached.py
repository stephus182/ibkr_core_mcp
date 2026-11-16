"""No unit test can reach a human — a Touch ID prompt, a Gate 2 dialog (register F32) or the
login window (register F44).

The suite has structural guards for the network (pytest-socket, from configure time) and for
the operator's data (the audit hook, `test_no_real_data_io.py`). It had none for the two
gates, and on 2026-10-01 that was demonstrated the hard way: a mutation run skipped Gate 1 in
`cancel_order`, a test that patched Touch ID alone walked on to the REAL Gate 2 dialog, and it
opened on the operator's screen during a live session — for a fake order, with the DELETE
mocked and sockets blocked, so nothing reached IBKR; but whether that mutant was "caught" was
decided by which button a person clicked. Five older tests had the same shape.

A gate reaches a person through five doors, and `tests/conftest.py` shuts each from
`pytest_configure` on:

1. Apple's `LocalAuthentication` framework — Gate 1, in-process (`human_auth.require_touch_id`);
2. `AppKit` — the dialog itself, when `_order_dialog` runs in the test process;
3. `tkinter.Tk` — the non-macOS dialog;
4. a child process running `_order_dialog.py` or `osascript` — how `order_confirm` shows the
   dialog on macOS;
5. a child process that would open a browser window — the Chrome login window
   `GatewayManager.open_login_page()` starts (register F44), by the binary's name or an
   `--app=` argument.

A test that needs one of them supplies its own double, as the gate tests already did
(`monkeypatch.setitem(sys.modules, …)`, `patch("…order_confirm.subprocess.run")`); nothing is
exempt. This file is what fails when a door is open.

**Every test here is safe on a broken guard, which is how each was proven able to fail.** A
test of the gates must never be able to open one, so each either checks the guard is in place
before it calls anything real, or reaches something harmless: `osascript -e "return 1"` shows
nothing, the dialog script it launches is an empty decoy, and the incident is replayed with
the interpreter swapped for `true`.
"""

from __future__ import annotations

import contextlib
import shutil
import subprocess
import sys
import types
from unittest.mock import patch

import pytest

from ibkr_core_mcp import _order_dialog, human_auth, order_confirm
from tests import conftest

pytestmark = pytest.mark.security

_TRUE = shutil.which("true")
# Both read while collection imports this module, which is after `pytest_configure` shut the doors.
_ARMED_WHEN_THIS_MODULE_WAS_IMPORTED = conftest._HUMAN_GUARD["armed"]
_SHUT_WHEN_THIS_MODULE_WAS_IMPORTED = {
    name: isinstance(sys.modules.get(name), conftest._NoHumanFramework) for name in ("LocalAuthentication", "AppKit")
}


@contextlib.contextmanager
def refused(door: str):
    """The block must end in the guard's refusal naming `door`, and leave its record.

    The record is removed again: these refusals are the test's subject, not a test reaching
    a person, and `pytest_sessionfinish` fails the run on any that remain.
    """
    before = len(conftest._human_refusals)
    with pytest.raises(pytest.fail.Exception, match="reach a human") as caught:
        yield caught
    recorded = conftest._human_refusals[before:]
    del conftest._human_refusals[before:]
    assert len(recorded) == 1 and door in recorded[0], recorded


def test_touch_id_cannot_prompt(monkeypatch):
    """Door 1. `require_touch_id` imports the framework inside the call, so the stand-in is
    what it gets — and a `BaseException` passes its `except ImportError`."""
    assert sys.modules["LocalAuthentication"] is conftest._STAND_INS["LocalAuthentication"]  # before anything real
    monkeypatch.setattr(human_auth, "_TIMEOUT", 0.01)  # a stand-in that only waited must not cost a minute
    with refused("LocalAuthentication"):
        human_auth.require_touch_id("a unit test")


def test_the_dialog_cannot_run_inside_the_test_process():
    """Door 2. `_order_dialog._run_alert` builds the core's own AppKit window; here it gets the stand-in."""
    assert sys.modules["AppKit"] is conftest._STAND_INS["AppKit"]  # before anything real
    with refused("AppKit"):
        _order_dialog._run_alert({"title": "t", "details": {}, "confirm_label": "OK"})


def test_a_tk_window_cannot_open():
    """Door 3. Where `tkinter` is importable its `Tk` is replaced; where it is not, there is
    no door — `order_confirm.tk` is None and the dialog says no GUI is available."""
    try:
        import tkinter
    except ImportError:
        assert vars(order_confirm)["tk"] is None
        return
    replaced: object = tkinter.Tk
    assert replaced is conftest._no_tk_window  # before anything real
    with refused("tkinter"):
        tkinter.Tk()


@pytest.mark.skipif(
    shutil.which("osascript") is None, reason="osascript is macOS-only; the hook is tested by the decoy below"
)
def test_osascript_cannot_be_launched():
    """Door 4, the fallback dialog. The script only returns a number: on a broken guard this
    shows nothing."""
    assert conftest._HUMAN_GUARD["armed"] is True
    with refused("osascript"):
        subprocess.run(["osascript", "-e", "return 1"], capture_output=True, text=True, timeout=10, check=False)


def test_the_dialog_script_cannot_be_launched(tmp_path):
    """Door 4, the primary dialog. An empty decoy under the dialog script's own name: the
    refusal is by what would run, so a broken guard runs a file that does nothing."""
    decoy = tmp_path / "_order_dialog.py"
    decoy.write_text("pass\n")
    with refused("_order_dialog.py"):
        subprocess.run([sys.executable, str(decoy)], capture_output=True, text=True, timeout=10, check=False)


@pytest.mark.skipif(_TRUE is None, reason="needs a `true` executable to stand in for Chrome")
def test_a_browser_app_window_cannot_be_opened():
    """Door 5, the login window (register F44), by its flag. `true` stands in for Chrome: on a
    broken guard it runs and shows nothing."""
    assert conftest._HUMAN_GUARD["armed"] is True
    assert _TRUE is not None
    with refused("--app="):
        subprocess.run([_TRUE, "--app=https://localhost:5055"], capture_output=True, timeout=10, check=False)


@pytest.mark.skipif(_TRUE is None, reason="needs a `true` executable to stand in for Chrome")
def test_chrome_cannot_be_launched_by_name(tmp_path):
    """Door 5 by the binary's name, read whole — the macOS one, "Google Chrome", holds a space.
    A link to `true` under that name: on a broken guard it runs and shows nothing."""
    assert conftest._HUMAN_GUARD["armed"] is True
    assert _TRUE is not None
    decoy = tmp_path / "Google Chrome"
    decoy.symlink_to(_TRUE)
    with refused("Google Chrome"):
        subprocess.run([str(decoy)], capture_output=True, timeout=10, check=False)


@pytest.mark.skipif(_TRUE is None, reason="needs a `true` executable to stand in for the interpreter")
def test_the_2026_10_01_incident_ends_in_a_refusal_not_a_dialog(client, monkeypatch):
    """The real defect, replayed through the real call chain: Gate 1 skipped, Gate 2 left
    real. `cancel_order` → `confirm_cancel_dialog` → `_show_appkit_dialog` → `subprocess.run`
    must stop at the guard, with nothing sent.

    Harmless on a broken guard: the interpreter the dialog would be launched with is swapped
    for `true`, checked before the call, so the worst case is a process that exits at once.
    """
    assert conftest._HUMAN_GUARD["armed"] is True
    monkeypatch.setattr(sys, "platform", "darwin")  # the AppKit path, on any CI platform
    monkeypatch.setattr(sys, "executable", _TRUE)
    assert vars(order_confirm)["sys"] is sys and sys.executable == _TRUE  # before anything real
    with (
        patch("ibkr_core_mcp.client.require_touch_id"),  # the mutant: Gate 1 does not stop it
        patch.object(client, "get_order_status", return_value={}),
        patch.object(client._session, "delete") as sent,
        refused("_order_dialog.py"),
    ):
        client.cancel_order("U1234567", "9876543210")
    sent.assert_not_called()


def test_the_run_turns_red_at_its_end_when_an_attempt_was_recorded(monkeypatch, capsys):
    """The wiring behind the pure function: with one attempt on record the session's exit
    status becomes 1 and the report names it; with none, the status is left alone."""

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
    quiet = _Session()
    conftest.pytest_sessionfinish(quiet, 0)  # type: ignore[arg-type]
    assert quiet.exitstatus == 0 and capsys.readouterr().out == ""

    monkeypatch.setattr(conftest, "_human_refusals", ["subprocess.Popen osascript"])
    loud = _Session()
    conftest.pytest_sessionfinish(loud, 0)  # type: ignore[arg-type]
    out = capsys.readouterr().out
    assert loud.exitstatus == 1
    assert "A HUMAN GATE REACHED FOR" in out and "subprocess.Popen osascript" in out
    assert "REAL DATA REACHED FOR" not in out


def test_nothing_the_conftest_holds_takes_a_read_for_a_reach():
    """pytest scans the conftest's namespace for fixtures, and from 9.2.0 reads `_mock_name` off
    every object it finds there (`_pytest/fixtures.py`, `_find_wrapped_fixture_def`). The two
    stand-ins were found there, took that read for a test reaching a person, and every run ended
    red whatever its tests did. Nothing the conftest holds may answer a read so: neither the name
    pytest reads nor any other a tool might.
    """
    before = len(conftest._human_refusals)
    for value in list(vars(conftest).values()):
        for name in ("_mock_name", "_a_name_any_tool_might_read"):
            with contextlib.suppress(pytest.fail.Exception, Exception):  # what pytest's safe_getattr swallows
                getattr(value, name, None)
    recorded = conftest._human_refusals[before:]
    del conftest._human_refusals[before:]
    assert recorded == []


def test_no_module_of_the_suite_holds_a_stand_in():
    """pytest scans test modules and test classes for fixtures the same way it scans the conftest
    (`_pytest/python.py`; a class through every `__dict__` of its `__mro__`), so a stand-in held as
    an attribute of either brings the false alarm back. Every module of the suite this run has
    imported is checked, the conftest among them, every class found in one and every class nested
    in one of the suite's own: in a full run, all of them. By type, reading nothing off what it
    finds.
    """
    held: set[str] = set()
    for module_name, module in list(sys.modules.items()):
        if module is None or not (module_name == "tests" or module_name.startswith("tests.")):
            continue
        namespaces = [(module_name, dict(vars(module)))]
        pending = [(f"{module_name}.{name}", value) for name, value in vars(module).items() if isinstance(value, type)]
        seen: set[type] = set()
        while pending:  # every class, and every class nested in one of the suite's own (pytest collects those)
            where, klass = pending.pop()
            if klass in seen:
                continue
            seen.add(klass)
            for owner in klass.__mro__:
                namespace = dict(vars(owner))
                namespaces.append((where, namespace))
                pending += [
                    (f"{where}.{name}", value)
                    for name, value in namespace.items()
                    if isinstance(value, type) and str(value.__module__).startswith("tests")
                ]
        for where, namespace in namespaces:
            held.update(
                f"{where}.{attribute}"
                for attribute, value in namespace.items()
                if isinstance(value, conftest._NoHumanFramework)
            )
    assert sorted(held) == []


@pytest.mark.parametrize("framework", ["LocalAuthentication", "AppKit"])
def test_a_stand_in_refuses_the_name_pytest_reads_like_any_other(framework):
    """The stand-ins are kept out of the namespaces pytest scans, not taught to forgive a name:
    `_mock_name` read off a stand-in is still a refusal, and only dunder reads are let through
    (pytest, coverage and `inspect` read those off everything)."""
    stand_in = sys.modules[framework]
    assert isinstance(stand_in, conftest._NoHumanFramework)  # before anything real
    with refused(f"{framework}._mock_name") as caught:
        _ = stand_in._mock_name
    assert f"({framework}._mock_name)" in str(caught.value)  # the refusal names the read
    with pytest.raises(AttributeError):
        _ = stand_in.__wrapped__


def test_the_doors_are_shut_before_any_test_module_is_imported():
    """The stand-ins are in `sys.modules` and the guard is armed from `pytest_configure`, before
    collection imports a test module, so a module that reaches a framework while it is imported
    meets a stand-in and is refused. Arming once collection is over would also have quieted the
    false alarm, and that reach would then pass unseen; installing the stand-ins late would let it
    import the real framework, which is installed here (pyobjc).
    """
    assert _ARMED_WHEN_THIS_MODULE_WAS_IMPORTED is True
    assert _SHUT_WHEN_THIS_MODULE_WAS_IMPORTED == {"LocalAuthentication": True, "AppKit": True}


def test_the_doors_open_again_to_what_was_there(monkeypatch):
    """`pytest_unconfigure` puts back what configure replaced: a framework imported before the run
    gets its module back, one that was not is removed, `tkinter.Tk` is restored, and the guard is
    disarmed. Run on doubles of that record and of `tkinter` (a module that is not the real one,
    so this runs where tkinter is missing too), everything put back by monkeypatch when the test
    ends; between the call and the end the test only asserts, and the suite runs no thread that
    imports a framework meanwhile.
    """
    real = types.ModuleType("LocalAuthentication")  # stands for a framework imported before configure
    fake_tkinter = types.ModuleType("tkinter")
    real_tk = object()  # stands for the `Tk` that configure replaced
    record: dict[str, object] = {}
    record.update({"LocalAuthentication": real, "AppKit": record, "tkinter.Tk": real_tk})  # AppKit: nothing was there
    monkeypatch.setattr(conftest, "_displaced", record)
    monkeypatch.setitem(conftest._HUMAN_GUARD, "armed", True)
    monkeypatch.setitem(sys.modules, "tkinter", fake_tkinter)
    for name in ("LocalAuthentication", "AppKit"):
        monkeypatch.setitem(sys.modules, name, sys.modules[name])
    conftest._open_the_doors_again()
    assert sys.modules["LocalAuthentication"] is real
    assert "AppKit" not in sys.modules
    assert vars(fake_tkinter)["Tk"] is real_tk
    assert conftest._HUMAN_GUARD["armed"] is False
