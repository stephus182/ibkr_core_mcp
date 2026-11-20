"""Is this environment what a fresh install would give? Compare it, package by package.

Why this exists. `pyproject.toml` leaves the base dependencies free to move upward on purpose,
and CI resolves them fresh on every run. A development `.venv` does neither: it keeps what it
had the day it was built. Nothing compared the two until 2026-11-12, when the release
worktree's environment turned out to differ from CI's install in 56 of 115 packages — pandas
3.0.6 against 3.1.1, RestrictedPython 8.5 against 9.0, and the gate tools themselves (ruff,
mypy, pytest). Four green local gates were therefore green on other versions than CI's, and the
first CI run on the branch went red on a test only the newer pandas exposed.

Comparing with CI is not enough either. CI runs on Linux and never installs the macOS-only
`pyobjc` packages behind both order gates; this check, run on a Mac, is the only one that sees
them. That evening they were a major version behind (12.2.2 against 13.0).

How it works. It reads `[project].dependencies` and the named extras from `pyproject.toml`,
asks pip what a fresh install of them would be — `pip install --dry-run --ignore-installed
--report`, which resolves for this interpreter and platform and installs nothing — and compares
each package of that resolve with what is installed here. The project itself is never built.

Run, from anywhere, with the environment's own interpreter:

    python scripts/check_env_drift.py [--extras dev,server] [--pyproject PATH]

Exit 0 when every package of the fresh resolve is installed at that version, 1 when at least
one is not (each named, with the line that aligns them), 2 when the comparison could not be
made — no network, an index error, an empty resolve. **2 is not 0**: a check that reports "no
drift" because it compared nothing is the defect this script was written to end.

It needs the network, so it is not one of the four gates and not in the pre-push hook. When to
run it is in `CLAUDE.md` § Dev Setup.

Source: https://pip.pypa.io/en/stable/reference/installation-report/
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any

DEFAULT_EXTRAS = ("dev", "server")
"""The extras of `pip install -e ".[dev,server]"`, the documented development install."""

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


class DriftCheckError(RuntimeError):
    """The comparison could not be made. Never to be read as 'no drift'."""


@dataclass(frozen=True)
class Drift:
    """One package of the fresh resolve that this environment does not hold at that version."""

    name: str
    installed: str | None
    fresh: str


def canonical(name: str) -> str:
    """A distribution name in the normalised form of the packaging specification.

    Source: https://packaging.python.org/en/latest/specifications/name-normalization/
    """
    return re.sub(r"[-_.]+", "-", name).lower()


def read_requirements(pyproject: Path, extras: Sequence[str]) -> list[str]:
    """The base dependencies plus those of each named extra, as `pyproject.toml` writes them.

    Raises:
        DriftCheckError: An extra the project does not define.
    """
    project = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]
    optional: Mapping[str, list[str]] = project.get("optional-dependencies", {})
    requirements = list(project.get("dependencies", []))
    for extra in extras:
        if extra not in optional:
            raise DriftCheckError(f"no such extra in {pyproject.name}: {extra!r} (it defines {sorted(optional)})")
        requirements.extend(optional[extra])
    return requirements


def parse_report(text: str) -> dict[str, str]:
    """The installation report pip wrote, as `{canonical name: version}`.

    Raises:
        DriftCheckError: The report lists no packages — nothing was resolved, so nothing can
            be compared.
    """
    report: dict[str, Any] = json.loads(text)
    fresh = {
        canonical(item["metadata"]["name"]): str(item["metadata"]["version"]) for item in report.get("install", [])
    }
    if not fresh:
        raise DriftCheckError("pip's report lists no packages — nothing was resolved")
    return fresh


def fresh_resolve(
    requirements: Sequence[str], *, python: str = sys.executable, run: Runner = subprocess.run
) -> dict[str, str]:
    """What pip would install for `requirements` into an empty environment, installing nothing.

    Raises:
        DriftCheckError: pip did not complete, or its report is empty.
    """
    with tempfile.TemporaryDirectory(prefix="env-drift-") as tmp:
        wanted = Path(tmp) / "requirements.txt"
        report = Path(tmp) / "report.json"
        wanted.write_text("\n".join(requirements) + "\n", encoding="utf-8")
        command = [python, "-m", "pip", "install", "--dry-run", "--ignore-installed", "--quiet"]
        command += ["--report", str(report), "-r", str(wanted)]
        done = run(command, capture_output=True, text=True, check=False)
        if done.returncode != 0 or not report.exists():
            detail = (done.stderr or "").strip().splitlines()[-1:] or ["no output"]
            raise DriftCheckError(f"pip exited {done.returncode}: {detail[0]}")
        return parse_report(report.read_text(encoding="utf-8"))


def installed_versions(names: Iterable[str]) -> dict[str, str | None]:
    """The version of each named distribution in this environment, `None` when absent."""
    found: dict[str, str | None] = {}
    for name in names:
        try:
            found[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            found[name] = None
    return found


def find_drift(fresh: Mapping[str, str], installed: Mapping[str, str | None]) -> list[Drift]:
    """Every package of the fresh resolve not installed at that version, by name."""
    return [
        Drift(name, installed.get(name), version)
        for name, version in sorted(fresh.items())
        if installed.get(name) != version
    ]


def main(
    argv: Sequence[str] | None = None,
    *,
    run: Runner = subprocess.run,
    installed: Callable[[Iterable[str]], Mapping[str, str | None]] = installed_versions,
) -> int:
    """Compare and report. Returns the exit code: 0 no drift, 1 drift, 2 could not check."""
    parser = argparse.ArgumentParser(description="Compare this environment with a fresh resolve of the project.")
    parser.add_argument("--extras", default=",".join(DEFAULT_EXTRAS), help="comma-separated (default: dev,server)")
    parser.add_argument(
        "--pyproject", type=Path, default=Path(__file__).resolve().parent.parent / "pyproject.toml", metavar="PATH"
    )
    args = parser.parse_args(argv)
    extras = [extra.strip() for extra in args.extras.split(",") if extra.strip()]
    try:
        fresh = fresh_resolve(read_requirements(args.pyproject, extras), run=run)
    except (DriftCheckError, OSError, ValueError, KeyError) as exc:
        print(f"COULD NOT CHECK — this is not 'no drift': {exc}", file=sys.stderr)
        return 2
    drift = find_drift(fresh, installed(fresh))
    if not drift:
        print(f"no drift: all {len(fresh)} packages of a fresh resolve of [{','.join(extras)}] are installed")
        return 0
    print(f"DRIFT: {len(drift)} of {len(fresh)} packages differ from a fresh resolve of [{','.join(extras)}]")
    for item in drift:
        print(f"  {item.name:36} installed {item.installed or 'not installed':16} fresh {item.fresh}")
    print("to align (read CLAUDE.md § Dev Setup first if a pyobjc package is listed):")
    print(f"  {sys.executable} -m pip install " + " ".join(f'"{item.name}=={item.fresh}"' for item in drift))
    return 1


if __name__ == "__main__":
    sys.exit(main())
