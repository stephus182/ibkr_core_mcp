"""Security constitution §8 — processes are spawned only from three named modules, never
through a shell, never with model-derived arguments.

Ruff's S603/S607 are ignored repo-wide (every existing call is list-form and resolves
`docker`/`open`/`osascript` on PATH on purpose), which means a *new* `subprocess.run`
anywhere in the package passes lint unremarked
(docs/audits/security-architecture-audit-2026-09-13.md, B8). This test names the modules
that may spawn and makes a fourth one a failure, not a review comment.
"""

from __future__ import annotations

import pytest

from .structural import PACKAGE_DIR, SCRIPTS_DIR, package_sources, shell_true_keywords, spawn_sites

pytestmark = pytest.mark.security

# Relative to the package directory. Each entry says what it spawns and why it is allowed.
ALLOWED_SPAWN_MODULES = {
    "order_confirm.py",  # Gate 2: the AppKit dialog subprocess and the osascript fallback
    "gateway/manager.py",  # docker CLI, `open -a Docker`, webbrowser for the login page
    "backtest.py",  # the multiprocessing spawn context isolating strategy code
}


def test_only_the_named_modules_spawn_processes():
    spawning = {
        str(path.relative_to(PACKAGE_DIR)): sorted(sites)
        for path, source in package_sources()
        if (sites := spawn_sites(source))
    }
    assert set(spawning) == ALLOWED_SPAWN_MODULES, spawning


def test_nothing_in_the_package_or_scripts_passes_shell_true():
    offenders = {}
    for path in sorted([*PACKAGE_DIR.rglob("*.py"), *SCRIPTS_DIR.rglob("*.py")]):
        if lines := shell_true_keywords(path.read_text()):
            offenders[str(path)] = lines
    assert not offenders, offenders


def test_the_spawn_probe_sees_each_form():
    """SEC-08: `from os import system` was invisible.

    The probe recognised a spawn *module* imported by name, and `os.<attr>` written as an
    attribute — but `os` is not a spawn module, so importing the function out of it went
    unseen and `system('x')` looked like an ordinary call. `execv` and the `as` form are
    here because the same hole covers every name the attribute rule already matches, and
    renaming on import is the obvious next spelling.
    """
    snippet = (
        "import subprocess\n"
        "from multiprocessing import Process\n"
        "import os, asyncio\n"
        "from os import system\n"
        "from os import execv as run_it\n"
        "os.system('x')\n"
        "os.popen('x')\n"
        "asyncio.create_subprocess_exec('x')\n"
    )
    assert spawn_sites(snippet) == {
        "import subprocess",
        "from multiprocessing import …",
        "from os import system",
        "from os import execv",
        "os.system",
        "os.popen",
        "asyncio.create_subprocess_exec",
    }


def test_the_spawn_probe_does_not_flag_an_innocent_os_import():
    """The rule is the attribute list, not the module: `from os import path` is ordinary."""
    assert spawn_sites("from os import path, environ\nprint(path, environ)\n") == set()


def test_the_shell_probe_sees_shell_true():
    assert shell_true_keywords("import subprocess\nsubprocess.run('ls', shell=True)\n") == [2]
