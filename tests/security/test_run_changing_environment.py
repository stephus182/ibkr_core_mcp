"""The environment cannot change what a run of this suite checks (register F59; checklist B2g).

pytest prepends `PYTEST_ADDOPTS` to every command line, loads the plugins `PYTEST_PLUGINS` names
and honours `PYTEST_DISABLE_PLUGIN_AUTOLOAD` (pytest 9.2.0, `_pytest/config/__init__.py`), and the
command shows none of it. Measured 2026-11-18, before this file: a `-k` left in a shell made the
pre-push hook print "all four gates green" after 9 tests of 2,950; `--force-enable-socket` let a
unit test create a socket; `--noconftest` switched off every guard of the root conftest at once,
the doors to a human, the socket block, the operator-data and desktop hooks, the null keychain and
the secret scrub.

Three layers refuse it, and the tests here hold each:

1. `tests/__init__.py`, which pytest imports for every module of the suite, conftest or not, in
   every import mode and under `--continue-on-collection-errors`;
2. the root conftest's `pytest_configure`, for a second session in a process that has imported
   the package already;
3. `.githooks/pre-push`, in shell, before any gate, where no pytest option reaches.

**Every test here is safe on a broken guard.** A child that should be refused only collects, and
only this file, which reaches nothing; the hook runs in a scratch repository whose gates are
stubs that write their names.

What none of this refuses, on purpose: a `--noconftest`, `-p no:…` or `-o addopts=` typed on the
command line, or an edited file. That is a decision made in the command, like `git push
--no-verify`, and a run started that way is not a gate (`docs/security-architecture.md` § 9).
"""

import os
import pathlib
import subprocess
import sys
from fnmatch import fnmatch

import pytest

pytestmark = pytest.mark.security

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_THIS_FILE = pathlib.Path(__file__).resolve()
_HOOK = _ROOT / ".githooks" / "pre-push"

# The three of the variables pytest documents (`pytest --help`, `_pytest/helpconfig.py`) that change
# which tests run, or with which plugins. Of the others it documents, `PYTEST_DEBUG_TEMPROOT` moves
# `tmp_path` and the rest change output; pytest-timeout's `PYTEST_TIMEOUT` moves the 300 s backstop,
# so a run can hang or fail but not pass (`docs/security-architecture.md` § 9). Written here, not
# imported: a list the code under test dropped a name from would drop the case that checks it.
_PYTEST_READS = ("PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTEST_DISABLE_PLUGIN_AUTOLOAD")
# A value for each that would change the run if it were let through.
_VALUES = {"PYTEST_ADDOPTS": "--noconftest", "PYTEST_PLUGINS": "pytester", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}


def _environment(**variables: str) -> dict[str, str]:
    """This process's environment without its `PYTEST_` variables, with `variables` added."""
    kept = {name: value for name, value in os.environ.items() if not name.startswith("PYTEST_")}
    return {**kept, **variables}


def _collect_only(arguments: list[str], env: dict[str, str]) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(
        [sys.executable, "-B", "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", *arguments],
        cwd=_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


@pytest.mark.parametrize("import_mode", ["prepend", "importlib"])
@pytest.mark.parametrize("name", _PYTEST_READS)
def test_the_package_refuses_every_import_while_the_environment_would_change_the_run(name, import_mode):
    """The conftest is switched off on the command line, so nothing but `tests/__init__.py` can
    refuse. This file is named twice and kept twice, and the session continues after an error:
    importlib mode keeps a package whose `__init__` raised, and before the package took itself out
    of `sys.modules` the second import walked past it and collected a test (measured 2026-11-18,
    the whole suite: 2,814 tests). Without autoload, `-p pytest_socket` lets pyproject's
    `--allow-unix-socket` parse, so the refusal answers rather than pytest's usage error."""
    plugin = ["-p", "pytest_socket"] if name == "PYTEST_DISABLE_PLUGIN_AUTOLOAD" else []
    arguments = ["--noconftest", f"--import-mode={import_mode}", "--continue-on-collection-errors"]
    done = _collect_only(
        [*arguments, "--keep-duplicates", *plugin, str(_THIS_FILE), str(_THIS_FILE)],
        _environment(**{name: _VALUES[name]}),
    )
    lines = done.stdout.splitlines()
    collected = [line for line in lines if "::" in line]
    refused = [line for line in lines if line.startswith(f"E   RuntimeError: The environment sets {name},")]
    assert (collected, len(refused)) == ([], 2), done.stdout[-3000:] + done.stderr[-3000:]


def test_a_second_session_in_a_process_that_has_imported_the_package_is_refused_by_the_conftest():
    """`tests/__init__.py` runs once per process. A second session, with a variable set after the
    package was imported, is refused by the root conftest's `pytest_configure` as a usage error,
    before it arms anything. The session collects only this file, under a `-k` no test matches, so
    a refusal that no longer fires collects nothing and exits 5."""
    probe = (
        "import os, sys\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "import tests\n"
        "import pytest\n"
        "os.environ['PYTEST_ADDOPTS'] = '-k a_name_no_test_has'\n"
        "sys.exit(pytest.main(['--collect-only', '-q', '-p', 'no:cacheprovider', sys.argv[2]]))\n"
    )
    done = subprocess.run(
        [sys.executable, "-B", "-c", probe, str(_ROOT), str(_THIS_FILE)],
        cwd=_ROOT,
        env=_environment(),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    message = "ERROR: The environment sets PYTEST_ADDOPTS, which would change what this run checks."
    assert (done.returncode, message in done.stderr) == (4, True), done.stdout[-3000:] + done.stderr[-3000:]


def _run_the_hook(scratch: pathlib.Path, env: dict[str, str]) -> tuple["subprocess.CompletedProcess[str]", list[str]]:
    """Run `.githooks/pre-push` in a scratch repository whose `.venv/bin/ruff`, `mypy` and `pytest`
    are stubs that write their name and arguments, and return the run and the gates it reached.
    `GIT_` variables are left out: a hook sets them, and they would point git back at this one."""
    repo = scratch / "repo"
    stubs = repo / ".venv" / "bin"
    stubs.mkdir(parents=True)
    reached = scratch / "reached.txt"
    for tool in ("ruff", "mypy", "pytest"):
        stub = stubs / tool
        stub.write_text(f'#!/bin/sh\necho "{tool} $*" >> "{reached}"\n')
        stub.chmod(0o755)
    env = {name: value for name, value in env.items() if not name.startswith("GIT_")}
    subprocess.run(["git", "init", "-q", str(repo)], env=env, capture_output=True, timeout=60, check=True)
    done = subprocess.run(
        ["sh", str(_HOOK)], cwd=repo, env=env, capture_output=True, text=True, timeout=60, check=False
    )
    return done, reached.read_text().splitlines() if reached.exists() else []


def test_the_pre_push_hook_reaches_its_four_gates_when_nothing_is_set(tmp_path):
    """The proof that the stubs below are reached at all: with nothing set the hook runs the four
    gates, in CI's order, through to green."""
    done, gates = _run_the_hook(tmp_path, _environment())
    assert [gate.split()[0] for gate in gates] == ["ruff", "ruff", "mypy", "pytest"], done.stderr
    assert (done.returncode, done.stdout.strip()) == (0, "pre-push: all four gates green"), done.stderr


@pytest.mark.parametrize("newlines_only", [False, True], ids=["a-value", "newlines-only"])
@pytest.mark.parametrize("name", _PYTEST_READS)
def test_the_pre_push_hook_refuses_each_variable_before_any_gate(tmp_path, name, newlines_only):
    """In shell, before the first gate, so `--noconftest` in the variable cannot reach it. A value made
    only of newlines is set for pytest, and was let through while the hook read it by command
    substitution, which drops trailing newlines (found by the review, 2026-11-18)."""
    value = "\n\n" if newlines_only else _VALUES[name]
    done, gates = _run_the_hook(tmp_path, _environment(**{name: value}))
    assert (done.returncode, gates) == (1, []), done.stdout + done.stderr
    assert done.stderr.startswith(f"pre-push: {name} is set in the environment"), done.stderr


def test_the_refusal_names_the_variables_set_and_none_of_their_values(monkeypatch):
    """Error text names, never values (`docs/security-architecture.md` § 6.5). An empty value is
    unset, as pytest reads all three. The package's list is pytest's three."""
    from tests import RUN_CHANGING_VARIABLES, run_changing_variables_refusal

    assert sorted(RUN_CHANGING_VARIABLES) == sorted(_PYTEST_READS)
    for name in _PYTEST_READS:
        monkeypatch.setenv(name, "")
    assert run_changing_variables_refusal() is None
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "\n")  # set, for pytest and for the hook
    assert run_changing_variables_refusal() == (
        "The environment sets PYTEST_DISABLE_PLUGIN_AUTOLOAD, which would change what this run checks. "
        "Unset it, and pass the options on the command line instead."
    )
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "")
    canary = "a-value-7c1e-no-message-may-hold"
    monkeypatch.setenv("PYTEST_PLUGINS", canary)
    one = run_changing_variables_refusal()
    for name in _PYTEST_READS:
        monkeypatch.setenv(name, canary)
    every = run_changing_variables_refusal()
    assert one == (
        "The environment sets PYTEST_PLUGINS, which would change what this run checks. "
        "Unset it, and pass the options on the command line instead."
    )
    assert every is not None and every.startswith(f"The environment sets {', '.join(_PYTEST_READS)}, which")
    assert canary not in every and "Unset them," in every


def test_pytest_imports_the_package_for_every_test_module_and_finds_no_doctest_file():
    """The package's refusal reaches a module only through `import tests`. pytest decides that with
    `resolve_package_path`, asked here rather than imitated: it walks up while a directory holds an
    `__init__.py` and its name is an identifier, so a module under `tests/foo-bar/`, or in a folder
    without `__init__.py`, is imported under its bare name, without the package. A `test*.txt` file
    is collected as a doctest (pytest's default `--doctest-glob`) and imports nothing. Both escaped the
    first version of this test (found by the review, 2026-11-18). pyproject sets no `testpaths`, so a
    bare `pytest` collects from the repository's root; walked as pytest walks, without the
    directories its `norecursedirs` default leaves out."""
    from _pytest.pathlib import resolve_package_path

    left_out = {"build", "dist", "node_modules", "venv", "CVS", "_darcs", "{arch}"}
    modules: list[pathlib.Path] = []
    doctest_files: list[str] = []
    for directory, subdirectories, files in os.walk(_ROOT):
        subdirectories[:] = [d for d in subdirectories if not d.startswith(".") and d not in left_out]
        modules += [pathlib.Path(directory, f) for f in files if f.endswith(".py") and f.startswith("test_")]
        modules += [pathlib.Path(directory, f) for f in files if f.endswith("_test.py")]
        doctest_files += [str(pathlib.Path(directory, f).relative_to(_ROOT)) for f in files if fnmatch(f, "test*.txt")]
    assert len(modules) > 50, f"the walk found {len(modules)} test modules: it is broken"
    tests = _ROOT / "tests"
    escaping = sorted(str(m.relative_to(_ROOT)) for m in modules if resolve_package_path(m) != tests)
    assert (escaping, doctest_files) == ([], [])
