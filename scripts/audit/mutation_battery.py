"""Mutation battery — with the guards this audit learned it needs, the hard way.

A mutation test asks: if I deliberately break the code, does the suite notice? It is the
only direct evidence that a green suite means anything. It is also trivially self-deceiving,
and every guard below is here because its absence already produced a wrong answer in this
repository:

1. **The control runs FIRST and must be green.** An ad-hoc runner once passed
   `"tests/ -m 'not integration'"` as a single string; word-splitting handed pytest a literal
   `'not`, pytest errored, and the non-zero exit was scored as "mutant caught". It
   **fabricated 15 results**, two of which were hiding genuinely unpinned code (`cagr`,
   `calmar`). Running the unmutated control first turns that from a silent wrong answer into
   an immediate refusal.
2. **A mutation that did not apply is refused, never scored.** A `sed` edit silently missed
   because `ruff format` had re-flowed the target line; the run that followed measured
   nothing while looking exactly like a real one.
3. **"pytest did not run" is a distinct outcome from "tests failed".** Both are non-zero.
   Conflating them is what produced incident 1.
4. **Bytecode writing is disabled.** A same-length edit (`0o600` -> `0o644`) restored inside
   the same mtime second satisfied Python's mtime+size cache check, so a stale `.pyc` kept
   executing the *mutant* against restored source, failing four tests that were correct.
5. **The file must still hold the mutation when the run ends, and go back byte-identical.**
   Added while writing this module's tests: if the run itself rewrites the file, the verdict
   was not measuring the mutant. (The first four were what the shell version had.)

The runner is injected so the harness itself can be tested without spawning pytest —
`tests/scripts/test_mutation_battery.py` drives every outcome above.

Usage::

    from pathlib import Path
    import mutation_battery as mb

    doc = Path("docs/web-scraper-reference.md")
    results = mb.run_battery(
        [mb.Mutant("table says 10 browser tests", doc, "**8** browser tests", "**10** browser tests")],
        ["tests/test_config_docs_consistency.py"],
    )
    print(mb.format_results(results))

Every mutant must come back `caught`. A `survived` is an unpinned behaviour; a `not-applied`
or `did-not-run` is a broken harness and means the whole run is worthless, not that one line
of it is.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

CAUGHT = "caught"
SURVIVED = "survived"
NOT_APPLIED = "not-applied"
DID_NOT_RUN = "did-not-run"

# (exit code, combined stdout+stderr)
Runner = Callable[[Sequence[str]], "tuple[int, str]"]


class BatteryRefused(RuntimeError):
    """Raised instead of reporting results that cannot be trusted."""


@dataclass(frozen=True)
class Mutant:
    """One deliberate break: replace the first `old` in `path` with `new`."""

    name: str
    path: Path
    old: str
    new: str


@dataclass(frozen=True)
class Result:
    """What happened to one mutant. `outcome` is one of the four module constants."""

    name: str
    outcome: str
    detail: str


def classify(returncode: int, output: str) -> tuple[str, str]:
    """Turn a pytest run into an outcome, distinguishing "failed" from "never ran"."""
    tail = next((line for line in reversed(output.strip().splitlines()) if line.strip()), "")
    detail = f"exit={returncode} | {tail}"
    if "no tests ran" in output or not re.search(r"\b\d+ (passed|failed|error)", output):
        return DID_NOT_RUN, detail
    if re.search(r"\b\d+ (failed|error)", output):
        return CAUGHT, detail
    return SURVIVED, detail


def subprocess_runner(repo_root: Path) -> Runner:
    """The real runner: pytest in a subprocess, exit code read directly.

    `capture_output` rather than a shell pipe on purpose. `pytest ... | tail -1` returns
    `tail`'s exit status, which is how a red suite was pushed as green on 2026-09-16.
    """

    def run(args: Sequence[str]) -> tuple[int, str]:
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        proc = subprocess.run(
            [sys.executable, "-B", "-m", "pytest", *args, "-q", "--no-header", "-p", "no:cacheprovider"],
            cwd=repo_root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        return proc.returncode, f"{proc.stdout}{proc.stderr}"

    return run


def _run_one(mutant: Mutant, pytest_args: Sequence[str], runner: Runner) -> Result:
    original = mutant.path.read_bytes()
    text = mutant.path.read_text()

    # Guard 2: refuse a mutation that did not apply, rather than measuring unmutated source.
    if mutant.old not in text:
        return Result(mutant.name, NOT_APPLIED, f"anchor not found in {mutant.path.name}")
    mutated_text = text.replace(mutant.old, mutant.new, 1)
    if mutated_text == text:
        return Result(mutant.name, NOT_APPLIED, "replacement is identical to the original")

    try:
        mutant.path.write_text(mutated_text)
        mutated = mutant.path.read_bytes()
        if mutated == original:
            return Result(mutant.name, NOT_APPLIED, "file unchanged after writing the mutation")

        returncode, output = runner(pytest_args)

        # Guard 5: the run must not have rewritten the file under us.
        if mutant.path.read_bytes() != mutated:
            raise BatteryRefused(
                f"{mutant.name}: {mutant.path} changed during the run — the verdict is not about this mutant"
            )

        outcome, detail = classify(returncode, output)
        return Result(mutant.name, outcome, detail)
    finally:
        mutant.path.write_bytes(original)
        if mutant.path.read_bytes() != original:  # pragma: no cover - filesystem failure
            raise BatteryRefused(f"{mutant.name}: {mutant.path} could not be restored")


def run_battery(
    mutants: Sequence[Mutant],
    pytest_args: Sequence[str],
    *,
    runner: Runner | None = None,
    repo_root: Path | None = None,
) -> list[Result]:
    """Run every mutant, refusing rather than reporting anything untrustworthy.

    The unmutated control runs **first**, not last: if the suite is already red, or pytest
    cannot run at all, no verdict underneath it means anything and none is produced.
    """
    root = repo_root or Path(__file__).resolve().parents[2]
    run = runner or subprocess_runner(root)

    outcome, detail = classify(*run(pytest_args))
    if outcome != SURVIVED:
        raise BatteryRefused(f"control run is not green ({outcome}): {detail} — refusing to score any mutant")

    return [_run_one(m, pytest_args, run) for m in mutants]


def format_results(results: Sequence[Result]) -> str:
    """One line per mutant; `!!` marks a survivor, `XX` a result that was refused."""
    mark = {CAUGHT: "  ok", SURVIVED: "  !!", NOT_APPLIED: "  XX", DID_NOT_RUN: "  XX"}
    return "\n".join(f"{mark[r.outcome]}  {r.name} -> {r.outcome}  [{r.detail}]" for r in results)
