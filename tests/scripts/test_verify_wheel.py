"""`scripts/verify_wheel.py` — the built wheel is installed and exercised before it can be published.

Every gate ahead of it runs against `pip install -e .` — the checkout, not the artifact — and
`twine check` reads metadata. Nothing installed the wheel. So a file dropped from
`[tool.setuptools.package-data]` (`gateway/conf.yaml`, say, which the Dockerfile `COPY`s)
would pass four green gates and `twine check`, upload immutably, and break
`GatewayManager.build_image()` on the first `pip install` from PyPI. And an import probe run
from the repo root would not notice: with the current directory on `sys.path` it resolves
`ibkr_core_mcp` to the source tree — measured 2026-09-19, an interpreter with nothing installed
imported the checkout from the repo root and nothing from anywhere else.

These tests hold the script's own logic. The script is run end to end by `publish.yml`'s build
job and by hand before a release; it was watched failing on 2026-09-19 against a wheel with
`conf.yaml` deleted and against a wrong `--expect-version`, and passing on the real 2.0.1 wheel.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import verify_wheel as vw

pytestmark = pytest.mark.scripts

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_exactly_one_wheel_is_required(tmp_path):
    """Zero wheels means nothing was built; two means the wrong one could be checked."""
    with pytest.raises(vw.VerifyError, match="no \\.whl"):
        vw.select_wheel(tmp_path)
    first = tmp_path / "ibkr_core_mcp-2.0.1-py3-none-any.whl"
    first.write_bytes(b"")
    assert vw.select_wheel(tmp_path) == first
    (tmp_path / "ibkr_core_mcp-2.0.2-py3-none-any.whl").write_bytes(b"")
    with pytest.raises(vw.VerifyError, match="2 wheels"):
        vw.select_wheel(tmp_path)


def test_expected_version_is_read_from_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "9.8.7"\n')
    assert vw.expected_version(tmp_path / "pyproject.toml") == "9.8.7"


def test_expected_version_is_canonicalised_the_way_setuptools_writes_it(tmp_path):
    """setuptools normalises per PEP 440, so the wheel says `2.1.0rc1` for a pyproject `2.1.0-rc1`;
    a literal comparison would block a release for a correct wheel (review, 2026-09-19)."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "2.1.0-rc1"\n')
    assert vw.expected_version(tmp_path / "pyproject.toml") == "2.1.0rc1"


def test_the_data_file_list_covers_every_non_python_file_the_package_ships():
    """A data file added to the package must be added to the probe, or the probe cannot miss it.

    The list is deliberately NOT derived from `pyproject.toml`'s package-data: removing an
    entry there is exactly the failure the probe exists to catch, so the two must be
    independent. This test is what keeps the hand-written list honest instead.
    """
    package = REPO_ROOT / "ibkr_core_mcp"
    shipped = sorted(
        str(p.relative_to(package))
        for p in package.rglob("*")
        if p.is_file()
        and p.suffix != ".py"
        and not any(part.startswith((".", "__")) for part in p.relative_to(package).parts)
    )
    assert shipped, "found no data files under ibkr_core_mcp/ — the scan itself is broken"
    assert set(shipped) <= set(vw.DATA_FILES), f"shipped but not probed: {sorted(set(shipped) - set(vw.DATA_FILES))}"


def test_every_representative_name_is_public_api():
    import ibkr_core_mcp

    for name in vw.REPRESENTATIVE_API:
        assert name in ibkr_core_mcp.__all__, f"{name!r} is not exported by ibkr_core_mcp.__all__"


def test_missing_or_empty_data_files_are_named(tmp_path):
    for rel in vw.DATA_FILES:
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("content")
    (tmp_path / "py.typed").write_text("")  # the PEP 561 marker is legitimately empty
    assert vw.missing_data_files(tmp_path) == []

    (tmp_path / "gateway" / "conf.yaml").unlink()
    (tmp_path / "gateway" / "run_gateway.sh").write_text("")
    assert vw.missing_data_files(tmp_path) == ["gateway/conf.yaml", "gateway/run_gateway.sh"]


def test_location_check_requires_the_venv_and_refuses_the_checkout(tmp_path):
    venv = tmp_path / "venv"
    repo = tmp_path / "repo"
    installed = venv / "lib" / "python3.12" / "site-packages" / "ibkr_core_mcp" / "__init__.py"
    assert vw.location_failures(installed, must_be_under=venv, must_not_be_under=repo) == []

    checkout = repo / "ibkr_core_mcp" / "__init__.py"
    failures = vw.location_failures(checkout, must_be_under=venv, must_not_be_under=repo)
    assert len(failures) == 2
    assert any("checkout" in f for f in failures)
    assert any("not under the venv" in f for f in failures)


def test_version_check_compares_the_attribute_and_the_metadata_with_the_expectation():
    assert vw.version_failures("2.0.1", "2.0.1", expected="2.0.1") == []
    # `__version__` falls back to "0.0.0" when importlib.metadata cannot see the distribution
    assert vw.version_failures("0.0.0", "2.0.1", expected="2.0.1") == ["__version__ is '0.0.0', expected '2.0.1'"]
    assert vw.version_failures("2.0.1", "2.0.1", expected="2.0.2") == [
        "__version__ is '2.0.1', expected '2.0.2'",
        "installed metadata says '2.0.1', expected '2.0.2'",
    ]


def _fake_dist(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    wheel = dist / "ibkr_core_mcp-2.0.1-py3-none-any.whl"
    wheel.write_bytes(b"")
    return dist, wheel


def test_main_installs_checks_and_probes_outside_the_checkout_then_adds_the_server_extra(tmp_path, monkeypatch):
    """The order of operations is the property: install, pip check, probe under -I from a
    directory that is not the checkout — once for the base wheel, once with `[server]`."""
    dist, wheel = _fake_dist(tmp_path)
    calls: list[tuple[list[str], Path | None]] = []

    def fake_run(cmd, cwd=None):
        calls.append(([str(c) for c in cmd], cwd))
        return 0

    monkeypatch.setattr(vw, "_run", fake_run)
    monkeypatch.setattr(vw, "_create_venv", lambda where, python: where / "bin" / "python")

    assert vw.main(["--dist", str(dist), "--expect-version", "2.0.1"]) == 0

    installs = [c for c, _ in calls if c[1:4] == ["-m", "pip", "install"]]
    assert [c[-1] for c in installs] == [str(wheel), f"{wheel}[server]"]
    checks = [c for c, _ in calls if c[1:4] == ["-m", "pip", "check"]]
    assert len(checks) == 2

    probes = [(c, cwd) for c, cwd in calls if "--probe" in c]
    assert len(probes) == 2
    assert "--server" not in probes[0][0] and "--server" in probes[1][0]
    for cmd, cwd in probes:
        assert cmd[1] == "-I", cmd
        assert cwd is not None and not Path(cwd).resolve().is_relative_to(REPO_ROOT), cwd
        assert "--expect-version" in cmd and cmd[cmd.index("--expect-version") + 1] == "2.0.1"
        assert cmd[cmd.index("--must-not-be-under") + 1] == str(REPO_ROOT)


def test_a_failing_step_stops_the_run_and_is_named(tmp_path, monkeypatch, capsys):
    dist, _ = _fake_dist(tmp_path)

    def fake_run(cmd, cwd=None):
        return 1 if [str(c) for c in cmd][1:5] == ["-m", "pip", "check"] else 0

    monkeypatch.setattr(vw, "_run", fake_run)
    monkeypatch.setattr(vw, "_create_venv", lambda where, python: where / "bin" / "python")

    assert vw.main(["--dist", str(dist), "--expect-version", "2.0.1"]) == 1
    out = capsys.readouterr().out
    assert "pip check" in out and "FAILED" in out


def test_a_venv_that_cannot_be_created_is_a_named_failure_not_a_traceback(tmp_path, monkeypatch, capsys):
    """`--python` pointing at nothing, or a runner without ensurepip: the release log must say
    which step failed, as it does for every other step (review, 2026-09-19)."""
    import subprocess

    dist, _ = _fake_dist(tmp_path)

    def cannot(where, python):
        raise subprocess.CalledProcessError(1, [python, "-m", "venv", str(where)])

    monkeypatch.setattr(vw, "_create_venv", cannot)
    monkeypatch.setattr(vw, "_run", lambda cmd, cwd=None: 0)
    assert vw.main(["--dist", str(dist), "--expect-version", "2.0.1"]) == 1
    out = capsys.readouterr().out
    assert "FAILED: create venv" in out


def test_an_empty_dist_dir_is_refused_before_any_venv_is_created(tmp_path, monkeypatch, capsys):
    (tmp_path / "dist").mkdir()

    def no_venv(where, python):
        raise AssertionError("a venv was created for a dist dir with no wheel")

    monkeypatch.setattr(vw, "_create_venv", no_venv)
    assert vw.main(["--dist", str(tmp_path / "dist"), "--expect-version", "2.0.1"]) == 1
    assert "no .whl" in capsys.readouterr().out
