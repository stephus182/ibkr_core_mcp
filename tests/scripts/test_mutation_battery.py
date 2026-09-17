"""Prove the mutation battery works before trusting a single one of its results.

This file is the direct descendant of two incidents in the 2026-09-16 audit.

An ad-hoc runner **fabricated 15 results**: it passed `"tests/ -m 'not integration'"` as one
string, word-splitting handed pytest a literal `'not`, pytest errored, and the non-zero exit
was scored as "mutant caught". Every one of those 15 "caught" verdicts was an error message.
Two mutants the suite genuinely did not catch were hiding inside them. It was found by a
no-op control that should have survived and did not.

Then a `sed` mutation silently **never applied** — `ruff format` had re-flowed the target
line — and the run that followed measured nothing at all while looking identical to a real one.

So: a harness reports a result only when it can prove the mutation was applied, that pytest
actually ran, and that the file it edited went back exactly as it was. Anything else is
refused, loudly, rather than scored.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts/audit"))

import mutation_battery as mb  # noqa: E402

pytestmark = pytest.mark.scripts

GREEN = (0, "7 passed in 0.40s")
RED = (1, "1 failed, 6 passed in 0.42s")


def _target(tmp_path: Path) -> Path:
    f = tmp_path / "doc.md"
    f.write_text("| rows | **8** browser tests |\n")
    return f


def test_a_mutant_the_suite_catches_is_reported_caught(tmp_path):
    target = _target(tmp_path)

    def runner(args):
        return RED if "**10**" in target.read_text() else GREEN

    results = mb.run_battery([mb.Mutant("8->10", target, "**8**", "**10**")], ["tests/x.py"], runner=runner)
    assert [r.outcome for r in results] == [mb.CAUGHT]


def test_a_mutant_nothing_catches_is_reported_survived(tmp_path):
    target = _target(tmp_path)

    def runner(args):
        return GREEN

    results = mb.run_battery([mb.Mutant("8->10", target, "**8**", "**10**")], ["tests/x.py"], runner=runner)
    assert [r.outcome for r in results] == [mb.SURVIVED]


def test_a_mutation_that_never_applied_is_refused_not_scored(tmp_path):
    """The `sed`/`ruff format` incident: the anchor had moved, so nothing was mutated.

    A green suite against unmutated source must never be reported as SURVIVED either —
    that would be a real verdict drawn from a run that measured nothing.
    """
    target = _target(tmp_path)

    def runner(args):
        return GREEN

    results = mb.run_battery(
        [mb.Mutant("anchor moved", target, "text that is not in the file", "x")],
        ["tests/x.py"],
        runner=runner,
    )
    assert [r.outcome for r in results] == [mb.NOT_APPLIED]
    # Assert WHICH refusal fired. Two paths return NOT_APPLIED — a missing anchor, and a
    # replacement identical to the original — so without this the first check can be deleted
    # and the second answers in its place. Measured: that mutant survived until the detail
    # was asserted.
    assert "anchor not found" in results[0].detail


def test_a_run_where_pytest_never_ran_is_not_scored_as_caught(tmp_path):
    """The fabricated-15 incident, exactly: non-zero exit, but no test ever executed."""
    target = _target(tmp_path)
    seen: list[int] = []

    def runner(args):
        seen.append(1)
        if len(seen) == 1:
            return GREEN  # baseline
        return 4, "ERROR: file or directory not found: tests/typo.py"

    results = mb.run_battery([mb.Mutant("8->10", target, "**8**", "**10**")], ["tests/x.py"], runner=runner)
    assert [r.outcome for r in results] == [mb.DID_NOT_RUN]


def test_a_red_baseline_refuses_the_whole_battery(tmp_path):
    """The control runs FIRST. If the suite is already red, no verdict below it means anything."""
    target = _target(tmp_path)

    def runner(args):
        return RED

    with pytest.raises(mb.BatteryRefused):
        mb.run_battery([mb.Mutant("8->10", target, "**8**", "**10**")], ["tests/x.py"], runner=runner)


def test_a_baseline_that_never_ran_refuses_the_whole_battery(tmp_path):
    target = _target(tmp_path)

    def runner(args):
        return 4, "ERROR: usage error"

    with pytest.raises(mb.BatteryRefused):
        mb.run_battery([mb.Mutant("8->10", target, "**8**", "**10**")], ["tests/x.py"], runner=runner)


def test_every_mutated_file_is_restored_byte_identical(tmp_path):
    target = _target(tmp_path)
    before = target.read_bytes()

    def runner(args):
        return RED if "**10**" in target.read_text() else GREEN

    mb.run_battery([mb.Mutant("8->10", target, "**8**", "**10**")], ["tests/x.py"], runner=runner)
    assert target.read_bytes() == before


def test_a_run_that_rewrites_the_file_under_us_is_refused(tmp_path):
    """Guard 5. If the run itself edits the file, the verdict is not about the mutant.

    This test was wrong on its first draft: the fake runner clobbered the file during the
    CONTROL run too, so there was no mutation left to apply and the harness correctly said
    `NOT_APPLIED` instead of raising. The clobber has to land on the mutated run alone for
    this to be a test of guard 5 at all.
    """
    target = _target(tmp_path)
    runs: list[int] = []

    def runner(args):
        runs.append(1)
        if len(runs) > 1:  # the mutated run, not the control
            target.write_text("something else entirely\n")
        return GREEN

    with pytest.raises(mb.BatteryRefused):
        mb.run_battery([mb.Mutant("8->10", target, "**8**", "**10**")], ["tests/x.py"], runner=runner)

    assert target.read_text() == "| rows | **8** browser tests |\n", "the file must still be restored"


def test_the_real_runner_forbids_writing_bytecode(monkeypatch):
    """A stale `.pyc` executed a restored mutant on 2026-09-16: same-length edit, sub-second
    restore, so Python's mtime+size cache check was satisfied and four tests failed against
    correct source. The runner must disable bytecode entirely."""
    seen_cmd: list[str] = []
    seen_env: dict[str, str] = {}

    class _Proc:
        returncode = 0
        stdout = "1 passed"
        stderr = ""

    def fake_run(cmd, **kwargs):
        seen_cmd.extend(cmd)
        seen_env.update(kwargs["env"])
        return _Proc()

    # Delete it from the INHERITED environment first. Without this the assertion passes
    # whenever this suite is itself run by a battery: `subprocess_runner` exports the
    # variable, the child pytest inherits it, and `dict(os.environ)` carries it even when
    # the runner no longer adds it. Measured 2026-09-17 — removing the runner's own
    # assignment left this test GREEN under the battery and RED when run directly. A check
    # that cannot fail in the conditions it will actually run in.
    monkeypatch.delenv("PYTHONDONTWRITEBYTECODE", raising=False)
    monkeypatch.setattr("mutation_battery.subprocess.run", fake_run)
    mb.subprocess_runner(REPO_ROOT)(["tests/x.py"])

    assert seen_env.get("PYTHONDONTWRITEBYTECODE") == "1", "the runner must set it, not inherit it"
    assert "-B" in seen_cmd
