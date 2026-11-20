"""`scripts/check_env_drift.py` — is this environment what a fresh install would give?

The base dependencies float upward on purpose and CI resolves them fresh on every run, while a
development `.venv` keeps what it had the day it was built. On 2026-11-12 the release worktree's
environment differed from CI's install in 56 of 115 packages — pandas, RestrictedPython, and the
gate tools themselves (ruff, mypy, pytest) — so four green local gates were green on other
versions than CI's, and the first CI run on the branch went red on a test that only the newer
pandas exposed. Nothing had compared the two. And CI could not have shown the rest: the
macOS-only `pyobjc` packages behind both order gates were a major version behind, and a Linux
runner never installs them.

These tests hold the script's own logic and never touch the network: pip is replaced by a
function that writes a report where the real one would. The report they read,
`tests/fixtures/pip_dry_run_report.json`, is three entries of a real `pip install --dry-run
--ignore-installed --report` (pip 26.2.1, 2026-11-12) cut down to the fields the script reads —
sliced from the wire, not written to match the parser.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import check_env_drift as ced
import pytest

pytestmark = pytest.mark.scripts

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
REAL_REPORT = REPO_ROOT / "tests" / "fixtures" / "pip_dry_run_report.json"
FRESH = {"pandas": "3.1.1", "restrictedpython": "9.0", "pyobjc-core": "13.0"}


def _pip(returncode=0, report=None, stderr=""):
    """A stand-in for `subprocess.run` that writes `report` where pip was told to."""

    def run(cmd, **kwargs):
        if report is not None:
            Path(cmd[cmd.index("--report") + 1]).write_text(report, encoding="utf-8")
        return subprocess.CompletedProcess(cmd, returncode, stdout="", stderr=stderr)

    return run


def test_the_requirements_come_from_pyproject_and_follow_the_extras():
    """What is resolved is what `pip install -e ".[dev,server]"` asks for, read from the one
    place it is written — not a second list that could fall behind it."""
    pyproject = REPO_ROOT / "pyproject.toml"
    default = ced.read_requirements(pyproject, ["dev", "server"])
    assert any(r.startswith("pandas") for r in default)
    assert any(r.startswith("pytest>=") for r in default)
    assert any(r.startswith("mcp") for r in default)
    assert not any(r.startswith("crawl4ai") for r in default)
    assert any(r.startswith("crawl4ai") for r in ced.read_requirements(pyproject, ["scraper"]))


def test_an_extra_the_project_does_not_define_is_refused():
    with pytest.raises(ced.DriftCheckError, match="no such extra"):
        ced.read_requirements(REPO_ROOT / "pyproject.toml", ["nonexistent"])


def test_a_real_pip_report_is_read_by_name_and_version():
    assert ced.parse_report(REAL_REPORT.read_text(encoding="utf-8")) == FRESH


def test_a_report_that_resolved_nothing_is_refused():
    """An empty resolve compared with any environment finds no difference. That is not "no
    drift", it is a check that did not happen."""
    with pytest.raises(ced.DriftCheckError, match="no packages"):
        ced.parse_report('{"version": "1", "install": []}')


def test_drift_is_each_package_whose_installed_version_is_not_the_fresh_one():
    installed = {"pandas": "3.0.6", "restrictedpython": "9.0", "pyobjc-core": "12.2.2"}
    assert ced.find_drift(FRESH, installed) == [
        ced.Drift("pandas", "3.0.6", "3.1.1"),
        ced.Drift("pyobjc-core", "12.2.2", "13.0"),
    ]


def test_a_package_a_fresh_install_would_add_is_drift_too():
    installed = {"pandas": "3.1.1", "restrictedpython": "9.0", "pyobjc-core": None}
    assert ced.find_drift(FRESH, installed) == [ced.Drift("pyobjc-core", None, "13.0")]


def test_names_are_compared_in_canonical_form():
    """pip reports `RestrictedPython`, a freeze says `restrictedpython`, a wheel `pyobjc_core`."""
    assert ced.canonical("RestrictedPython") == "restrictedpython"
    assert ced.canonical("pyobjc_core") == ced.canonical("pyobjc.core") == "pyobjc-core"


def test_an_environment_that_matches_exits_0(capsys):
    code = ced.main([], run=_pip(report=REAL_REPORT.read_text(encoding="utf-8")), installed=lambda names: dict(FRESH))
    assert code == 0
    assert "no drift" in capsys.readouterr().out


def test_drift_exits_1_and_names_the_package_and_both_versions(capsys):
    behind = dict(FRESH, pandas="3.0.6")
    code = ced.main([], run=_pip(report=REAL_REPORT.read_text(encoding="utf-8")), installed=lambda names: behind)
    out = capsys.readouterr().out
    assert code == 1
    assert "pandas" in out and "3.0.6" in out and "3.1.1" in out
    assert "pandas==3.1.1" in out, "the line that aligns it must be printed, exact version and all"
    assert "restrictedpython" not in out, "a package that matches is not drift"


def test_a_pip_that_failed_exits_2_and_is_never_reported_as_no_drift(capsys):
    """Offline, or an index error: nothing was compared. The exit code and the words must both
    say so — a check that cannot fail is the defect this script exists to end."""
    code = ced.main([], run=_pip(returncode=1, stderr="ERROR: Could not find a version"), installed=lambda names: {})
    captured = capsys.readouterr()
    assert code == 2
    assert "no drift" not in captured.out
    assert "could not check" in captured.err.lower()
