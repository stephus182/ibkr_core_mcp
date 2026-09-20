"""Install the wheel that was just built into a fresh venv and prove the ARTIFACT works.

Why this exists. Every other gate runs against the checkout: CI and `publish.yml`'s gates job
do `pip install -e .`, so ruff, mypy and pytest see the source tree, and `twine check` reads
the metadata without installing anything. Nothing between `python -m build` and the upload
ever installed the wheel — and PyPI files are immutable, so a wheel that installs but does not
work costs a version number. What a green editable suite cannot see:

- a file missing from `[tool.setuptools.package-data]`. The checkout has `gateway/conf.yaml`
  whether or not the wheel does, and `GatewayManager.build_image()` hands Docker the context
  at `Path(__file__).resolve().parent`, so the omission surfaces on the consumer's machine;
- a version the metadata disagrees with. `__version__` is `importlib.metadata.version(...)`,
  and on 2026-09-19 the development venv's interpreter reported `2.0.1` from the repo root
  (the checkout's `ibkr_core_mcp.egg-info`, found through the current directory on
  `sys.path`) and `1.2.2` from anywhere else (site-packages' stale editable dist-info);
- an extra whose requirement set no longer imports. `[server]` is a `Requires-Dist` line in
  the wheel's metadata; the gates install it from `pyproject.toml`, never from the wheel.

How it proves the artifact and not the checkout. The venv lives in a temporary directory, the
probe runs with `python -I` (isolated mode: neither the current directory nor the script's
directory on `sys.path`, no `PYTHON*` environment) from that directory, and it fails if
`ibkr_core_mcp.__file__` resolves anywhere but under the venv. Measured 2026-09-19: an
interpreter with nothing installed imported the checkout from the repo root under plain
`python -c` and nothing at all under `-I`.

Run, from the repo root, after `python -m build`:

    python scripts/verify_wheel.py [--dist dist] [--python PY] [--expect-version X.Y.Z] [--keep]

Exit 0 when every check passes, 1 otherwise, each failure named. `publish.yml`'s build job
runs it between `twine check` and the artifact upload. This is deliberately NOT the unit
suite rerun against the wheel: the suite establishes behaviour, this establishes distribution.
The sdist gets no step of its own because `python -m build` already builds the wheel FROM the
sdist ("Building wheel from sdist" in its log), so an sdist that cannot produce the wheel
fails the build step before this one runs.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = REPO_ROOT / "pyproject.toml"

# Files the package needs BY PATH at runtime, relative to the installed package directory.
# Deliberately not derived from pyproject.toml's package-data: an entry dropped from there is
# exactly the failure this probe exists to catch, so the two lists must be independent.
# `tests/scripts/test_verify_wheel.py` holds that every non-Python file in the source package
# appears here, which is what keeps a hand-written list honest.
DATA_FILES: tuple[str, ...] = (
    "py.typed",  # PEP 561 marker — without it a consumer's mypy treats the package as untyped
    "_order_dialog.py",  # Gate 2's display subprocess; order_confirm.py runs it by path, not by import
    "gateway/Dockerfile",  # the Docker build context GatewayManager.build_image() hands to docker
    "gateway/conf.yaml",  # COPY'd by the Dockerfile
    "gateway/run_gateway.sh",  # COPY'd by the Dockerfile; the container's ENTRYPOINT
    "gateway/healthcheck.sh",  # COPY'd by the Dockerfile
)
_MAY_BE_EMPTY = frozenset({"py.typed"})

# A representative slice of the public API, roughly one name per subsystem; each must resolve
# on the installed package. `import ibkr_core_mcp` already executes every import in
# `__init__.py`, so this is the explicit, readable half of the check — `__all__` is resolved in
# full as well.
REPRESENTATIVE_API: tuple[str, ...] = (
    "IBKRClient",
    "Config",
    "ClaudeToolkit",
    "SQLiteStore",
    "GDriveCache",
    "GatewayManager",
    "FlexQueryClient",
    "IBKRWebSocket",
    "AlertManager",
    "run_backtest",
    "require_touch_id",
    "indicators",
    "analytics",
    "pinescript",
)


class VerifyError(Exception):
    """A precondition that refuses to proceed — named, so the release log says what was wrong."""


def select_wheel(dist: Path) -> Path:
    """The one wheel in `dist`. Zero means nothing was built; two means the wrong one could be checked."""
    wheels = sorted(dist.glob("*.whl"))
    if not wheels:
        raise VerifyError(f"no .whl in {dist} — run `python -m build` first")
    if len(wheels) > 1:
        raise VerifyError(f"{len(wheels)} wheels in {dist}, expected exactly one: {[w.name for w in wheels]}")
    return wheels[0]


def canonical_version(version: str) -> str:
    """`version` as setuptools writes it into the wheel — PEP 440 normalised — or as given if `packaging` is absent.

    setuptools normalises `[project].version` when it builds (`2.1.0-rc1` becomes `2.1.0rc1` in
    METADATA, and so in `importlib.metadata.version()` and `__version__`), so a literal comparison
    would block a release for a wheel that is correct. `packaging` is present wherever a wheel is
    built (`build` depends on it) and wherever pytest runs; the fallback is for anything else.
    """
    try:
        from packaging.version import Version
    except ImportError:  # pragma: no cover — see the docstring
        return version
    return str(Version(version))


def expected_version(pyproject: Path) -> str:
    """`[project].version`, canonicalised — the value the tag, the CHANGELOG and the wheel must all agree with."""
    with pyproject.open("rb") as fh:
        return canonical_version(str(tomllib.load(fh)["project"]["version"]))


def missing_data_files(package_dir: Path) -> list[str]:
    """Every entry of `DATA_FILES` that is absent from the installed package, or empty when it must not be."""
    missing: list[str] = []
    for rel in DATA_FILES:
        path = package_dir / rel
        if not path.is_file() or (rel not in _MAY_BE_EMPTY and path.stat().st_size == 0):
            missing.append(rel)
    return missing


def location_failures(module_file: Path, *, must_be_under: Path, must_not_be_under: Path) -> list[str]:
    """Where `ibkr_core_mcp` was imported from must be the venv and must not be the checkout."""
    resolved = module_file.resolve()
    failures: list[str] = []
    if not resolved.is_relative_to(must_be_under.resolve()):
        failures.append(f"ibkr_core_mcp imported from {resolved}, not under the venv {must_be_under}")
    if resolved.is_relative_to(must_not_be_under.resolve()):
        failures.append(f"ibkr_core_mcp imported from the checkout: {resolved}")
    return failures


def version_failures(attribute: str, metadata: str, *, expected: str) -> list[str]:
    """`__version__` and the installed distribution's metadata must both equal the expected version."""
    failures: list[str] = []
    if attribute != expected:
        failures.append(f"__version__ is {attribute!r}, expected {expected!r}")
    if metadata != expected:
        failures.append(f"installed metadata says {metadata!r}, expected {expected!r}")
    return failures


def probe(expected: str, must_be_under: Path, must_not_be_under: Path, server: bool) -> list[str]:
    """Every check on the installed package. Runs inside the fresh venv, under `python -I`."""
    try:
        pkg = importlib.import_module("ibkr_core_mcp")
    except Exception as exc:  # the report is the point: any failure to import IS the finding
        return [f"import ibkr_core_mcp failed: {type(exc).__name__}: {exc}"]
    module_file = Path(str(pkg.__file__))
    print(f"  imported from {module_file}")
    failures = location_failures(module_file, must_be_under=must_be_under, must_not_be_under=must_not_be_under)

    try:
        metadata_version = importlib.metadata.version("ibkr_core_mcp")
    except importlib.metadata.PackageNotFoundError:
        metadata_version = "<no distribution metadata>"
    print(f"  __version__ {pkg.__version__} (metadata {metadata_version})")
    failures += version_failures(str(pkg.__version__), metadata_version, expected=expected)

    api_failures = [
        f"public name missing: ibkr_core_mcp.{name}" for name in REPRESENTATIVE_API if not hasattr(pkg, name)
    ]
    api_failures += [
        f"__all__ names {name!r} but it does not resolve" for name in pkg.__all__ if not hasattr(pkg, name)
    ]
    failures += api_failures
    print(f"  {len(pkg.__all__)} names in __all__ resolve" if not api_failures else "  public API: see failures")

    failures += [f"packaged file missing or empty: {rel}" for rel in missing_data_files(module_file.parent)]
    try:
        manager = importlib.import_module("ibkr_core_mcp.gateway.manager")
    except Exception as exc:  # same reason as above
        failures.append(f"import ibkr_core_mcp.gateway.manager failed: {type(exc).__name__}: {exc}")
    else:
        docker_dir = getattr(manager, "_DOCKER_DIR", None)
        if docker_dir is None:
            failures.append(
                "gateway.manager._DOCKER_DIR is gone — point this probe at whatever build_image() reads now"
            )
        elif not (Path(docker_dir) / "Dockerfile").is_file():
            failures.append(f"GatewayManager's Docker context {docker_dir} has no Dockerfile")
        else:
            print(f"  Docker context {docker_dir} carries its Dockerfile")

    if server:
        try:
            server_mod = importlib.import_module("ibkr_core_mcp.mcp_server")
        except Exception as exc:  # same reason as above
            failures.append(
                f"import ibkr_core_mcp.mcp_server failed with [server] installed: {type(exc).__name__}: {exc}"
            )
        else:
            if not callable(getattr(server_mod, "build_server", None)):
                failures.append("mcp_server.build_server is missing")
            else:
                print("  ibkr_core_mcp.mcp_server imports; build_server is present")
    return failures


def _run(cmd: list[str], cwd: Path | None = None) -> int:
    """Run one step, streaming its output; the return code is the verdict."""
    return subprocess.run(cmd, cwd=cwd, check=False).returncode


def _create_venv(where: Path, python: str) -> Path:
    """A fresh venv at `where`, built by `python`; returns its interpreter."""
    subprocess.run([python, "-m", "venv", str(where)], check=True)
    if os.name == "nt":
        return where / "Scripts" / "python.exe"
    return where / "bin" / "python"


def _report(failures: list[str]) -> int:
    for failure in failures:
        print(f"FAIL: {failure}")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    """Build a venv, install the wheel, `pip check`, probe; then again with the `[server]` extra."""
    parser = argparse.ArgumentParser(description="Install the built wheel into a fresh venv and prove it works.")
    parser.add_argument("--dist", type=Path, default=REPO_ROOT / "dist", help="directory holding exactly one .whl")
    parser.add_argument("--python", default=sys.executable, help="interpreter that builds the venv (default: this one)")
    parser.add_argument("--expect-version", default=None, help="default: [project].version in pyproject.toml")
    parser.add_argument("--keep", action="store_true", help="leave the venv in place for inspection")
    # Probe mode — internal. The driver re-runs this file inside the venv with these flags.
    parser.add_argument("--probe", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--must-be-under", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--must-not-be-under", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--server", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.probe:
        return _report(probe(args.expect_version, args.must_be_under, args.must_not_be_under, args.server))

    expected = canonical_version(args.expect_version) if args.expect_version else expected_version(PYPROJECT)
    try:
        wheel = select_wheel(args.dist.resolve())
    except VerifyError as exc:
        print(f"FAILED: {exc}")
        return 1

    # Outside the checkout on purpose; RUNNER_TEMP is GitHub Actions' per-job scratch directory.
    work = Path(tempfile.mkdtemp(prefix="ibkr-core-mcp-wheel-", dir=os.environ.get("RUNNER_TEMP")))
    venv_dir = work / "venv"
    print(f"wheel:  {wheel}\nexpect: {expected}\nvenv:   {venv_dir}")
    try:
        try:
            python = str(_create_venv(venv_dir, args.python))
        except (subprocess.CalledProcessError, OSError) as exc:
            print(f"FAILED: create venv with {args.python}: {exc}")
            return 1
        probe_cmd = [
            python,
            "-I",
            str(Path(__file__).resolve()),
            "--probe",
            "--expect-version",
            expected,
            "--must-be-under",
            str(venv_dir),
            "--must-not-be-under",
            str(REPO_ROOT),
        ]
        steps: list[tuple[str, list[str]]] = [
            ("pip install <wheel>", [python, "-m", "pip", "install", "--quiet", str(wheel)]),
            ("pip check", [python, "-m", "pip", "check"]),
            ("probe (base install)", probe_cmd),
            ("pip install <wheel>[server]", [python, "-m", "pip", "install", "--quiet", f"{wheel}[server]"]),
            ("pip check ([server])", [python, "-m", "pip", "check"]),
            ("probe ([server])", [*probe_cmd, "--server"]),
        ]
        for name, cmd in steps:
            print(f"--- {name}")
            if _run(cmd, cwd=work) != 0:
                print(f"FAILED: {name}")
                return 1
        print(f"OK: {wheel.name} installs, imports from the venv, reports {expected}, and carries its packaged files")
        return 0
    finally:
        if args.keep:
            print(f"kept {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
