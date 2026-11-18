"""The test suite.

It refuses to be imported while the environment would change what a run checks (register F59).
pytest prepends `PYTEST_ADDOPTS` to every command line, loads `PYTEST_PLUGINS` and honours
`PYTEST_DISABLE_PLUGIN_AUTOLOAD`, so a value left in a shell could narrow a run to a few tests, or
switch the root conftest's guards off with `--noconftest`, and the command would not show it.
pytest imports this package for every module of the suite, conftest or not, so the refusal holds
when the conftest does not load. Before refusing it takes itself out of `sys.modules`: pytest's
importlib mode keeps a package whose `__init__` raised, and every later module would import past
it (measured 2026-11-18). The root conftest's `pytest_configure` refuses the same, for a second
session in a process that has imported this package already.
"""

import os
import sys

RUN_CHANGING_VARIABLES = ("PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTEST_DISABLE_PLUGIN_AUTOLOAD")


def run_changing_variables_refusal() -> str | None:
    """The refusal to give while one of `RUN_CHANGING_VARIABLES` is set, or None when none is.

    It names the variables, never their values. An empty value counts as unset, as pytest reads
    all three.
    """
    named = [name for name in RUN_CHANGING_VARIABLES if os.environ.get(name)]
    if not named:
        return None
    return (
        f"The environment sets {', '.join(named)}, which would change what this run checks. "
        f"Unset {'it' if len(named) == 1 else 'them'}, and pass the options on the command line instead."
    )


_REFUSAL = run_changing_variables_refusal()
if _REFUSAL is not None:
    sys.modules.pop(__name__, None)
    raise RuntimeError(_REFUSAL)
