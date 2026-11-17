"""Security constitution §4, the other half — what the sandbox ALLOWS has to work in the
process a strategy really runs in: a child that `run_backtest` has just spawned.

Until 2026-11-13 it did not. CPython's `PyImport_Import` looks `__import__` up in the builtins
of the innermost Python frame, and while C code called directly by a strategy is running that
frame is the strategy's, whose builtins deliberately have none. So `arr.max()` raised
`KeyError: '__import__'` in a fresh child: numpy fetches the Python helper behind that method
through the import API on first use. The suite could not see it. One strategy in it called a
method on a numpy array in a child, and it passed because an earlier pandas line of the same
strategy had made numpy's call first, until pandas 3.1.0 stopped. The strategies it runs in
the pytest process could never show it: there the call has long been made from an ordinary
frame (checklist B2a; the measurements are in
`docs/plans/2026-11-12-sandbox-lazy-import-plan.md`, a local working document).

Two rules follow, and every test below obeys one of them:

* A test about what a strategy CAN do runs in a fresh child. One `run_backtest` call is one
  spawned interpreter in which nothing has run but the package's imports, the unpickling of
  the frame and `build_sandbox`. The set-up lines used here (`df['close']`, `.to_numpy()`,
  `df.index[0]`) were measured not to make any of the calls under test.
* A test about what a strategy CANNOT do may run in-process: a refusal does not depend on
  what ran before.
"""

from __future__ import annotations

import datetime
import multiprocessing
import sys
from multiprocessing.connection import Connection
from typing import Any

import numpy as np
import pandas as pd
import pytest
from RestrictedPython import compile_restricted, safe_builtins

from ibkr_core_mcp import backtest
from ibkr_core_mcp.backtest import build_sandbox, run_backtest
from ibkr_core_mcp.exceptions import BacktestRuntimeError

pytestmark = pytest.mark.security

_SETUP = "c = df['close']\narr = c.to_numpy()\nts = df.index[0]\n"


@pytest.fixture
def ohlcv():
    n = 60
    rng = np.random.default_rng(0)
    close = 100 + np.cumsum(rng.standard_normal(n))
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 1000.0},
        index=idx,
    )


# ── What a strategy can do, cold ──────────────────────────────────────────────

# One statement per way C code asks for an import underneath an allowed operation. The key
# is the test id; the comment names who asks, and for what.
_ALLOWED_OPERATIONS = {
    # numpy forwards ten array methods to Python helpers in numpy._core._methods
    "array.max()": "x = arr.max()",
    "array.mean()": "x = arr.mean()",
    "array.std()": "x = arr.std()",
    "array.sum()": "x = arr.sum()",
    "array.clip()": "x = arr.clip(0, 1)",
    "numpy scalar.max()": "x = arr[0].max()",
    # numpy prints an array through numpy._core.arrayprint, a dtype through numpy._core._dtype
    "str(array)": "x = str(arr)",
    "f-string of an array": "x = f'{arr}'",
    "str(dtype)": "x = str(arr.dtype)",
    # CPython's datetime imports `time` on every strftime, and `_strptime` to parse
    "Timestamp.strftime()": "x = ts.strftime('%Y-%m-%d')",
    "f-string of a Timestamp with a format": "x = f'{ts:%Y}'",
    "datetime.strptime()": "x = ts.to_pydatetime().strptime('2025-01-02', '%Y-%m-%d')",
    # numpy fetches numpy.matrix; before the fix this one killed the child with SIGSEGV
    "ufunc.outer()": "x = np.maximum.outer(arr[:3], arr[:3])",
    "array * Timedelta": "x = arr * (df.index[1] - df.index[0])",
    # a lambda written in the strategy has the strategy's globals, whoever calls it
    "a strategy lambda called by pandas": "x = c.rolling(5).apply(lambda w: w.max(), raw=True)",
    # numpy parses a comma-separated dtype string in numpy._core._internal
    "structured dtype string": "x = np.zeros(3, dtype='i4,f4')",
    # CPython itself, by version: `_pylong` from 3.12, `warnings` for every C-level warning in 3.13
    "division of very large integers": "x = (10**5000) // (10**3000)",
    "a numpy floating-point warning": "z = np.zeros(3)\nx = z / z",
}


@pytest.mark.parametrize("operation", sorted(_ALLOWED_OPERATIONS))
def test_an_allowed_operation_runs_in_a_fresh_child(ohlcv, operation):
    """Cold by construction: `run_backtest` spawns one interpreter for this one statement."""
    result = run_backtest(_SETUP + _ALLOWED_OPERATIONS[operation] + "\ndf['signal'] = 0\n", ohlcv)
    assert result.num_trades == 0


def test_a_forwarded_array_method_returns_the_right_value_in_a_fresh_child(ohlcv):
    """Running is not enough: the value is numpy's. The strategy checks it against pandas."""
    code = (
        _SETUP
        + "if arr.max() != c.max() or arr.mean() != np.mean(arr):\n    raise ValueError('wrong value')\ndf['signal'] = 0\n"
    )
    assert run_backtest(code, ohlcv).num_trades == 0


def test_numpys_own_error_reaches_the_model_instead_of_an_import_error(ohlcv):
    """numpy needs an import to FORMAT some of its errors. Before the fix the strategy was
    told `KeyError: '__import__'` in place of the TypeError it had actually caused, and the
    error text is all the model has to correct its own code."""
    with pytest.raises(BacktestRuntimeError) as info:
        run_backtest(_SETUP + "x = arr + pd.NaT\ndf['signal'] = 0\n", ohlcv)
    assert "TypeError" in str(info.value)
    assert "__import__" not in str(info.value)


# ── The vocabulary, swept in one fresh child ──────────────────────────────────


def _sweep_strategy() -> str:
    """Strategy source that calls the sandbox's numpy vocabulary and reports what could not import.

    Built from the allowlists themselves, so a name added to one of them is swept without
    anyone remembering to add it here. Every call sits in its own `try`: most argument forms
    are wrong for most names, and a TypeError is not what this looks for. `note` keeps only
    the three texts the defect produces. Each group stops the strategy if it found anything,
    so that an unpatched sandbox reports from the first group and never reaches `ufunc.outer`,
    which kills the child when its import is refused.
    """
    lines = [
        "found = []",
        "def note(label, exc):",
        "    text = str(exc)",
        "    if '__import__' in text or 'backtest sandbox' in text or 'Unable to configure default ndarray' in text:",
        "        found.append(label + ' -> ' + text[:70])",
        "def stop_if_found(group):",
        "    if found:",
        "        raise ValueError(group + ': ' + str(len(found)) + ' could not import, e.g. ' + ' | '.join(found[:2]))",
        # Literal arrays first: nothing in pandas has run on them, so nothing has made these calls yet.
        "def arrays():",
        "    return [np.array([1.5, -2.0, 3.0]), np.arange(4), np.array([True, False]), np.zeros((2, 2)),",
        "            np.array(2.5), np.array([1.5])[0], np.array(['a', 'b']), np.array([None, 1.5])]",
        "def frame_arrays():",
        "    return [df['close'].to_numpy(), df[['open', 'close']].to_numpy(), df.index.to_numpy(),",
        "            (df.index - df.index[0]).to_numpy()]",
    ]

    def attempt(label: str, statement: str, indent: str = "") -> list[str]:
        return [
            f"{indent}try:",
            f"{indent}    {statement}",
            f"{indent}except Exception as e:",
            f"{indent}    note({label!r}, e)",
        ]

    # 1. every allowed attribute of a numpy array or scalar, called five ways
    for name in sorted(backtest._NUMPY_ALLOWED_ATTRS):
        lines += [f"def sweep_{name}(o):", "    m = None"]
        lines += attempt(f"array.{name}", f"m = o.{name}", "    ")
        lines += ["    if callable(m):"]
        for args in ("", "0", "0, 1", "axis=0", "'i4,f4'"):
            lines += attempt(f"array.{name}({args})", f"m({args})", "        ")
        lines += ["for o in arrays():", f"    sweep_{name}(o)"]
    lines += ["stop_if_found('array methods on literal arrays')"]
    for name in sorted(backtest._NUMPY_ALLOWED_ATTRS):
        lines += ["for o in frame_arrays():", f"    sweep_{name}(o)"]
    lines += ["stop_if_found('array methods on arrays taken from the frame')"]

    # 2. printing
    lines += ["for o in arrays() + frame_arrays():"]
    for statement in ("str(o)", "repr(o)", "f'{o}'", "'%s' % (o,)", "str(o.dtype)", "repr(o.dtype)"):
        lines += attempt(statement, f"x = {statement}", "    ")
    lines += ["stop_if_found('printing')"]

    # 3. every function of the safe numpy namespace, and every allowed method of its ufuncs
    callables = sorted(n for n, v in vars(backtest._SAFE_NP).items() if callable(v))
    ufuncs = [n for n in callables if isinstance(getattr(backtest._SAFE_NP, n), np.ufunc)]
    lines += ["for a in arrays() + frame_arrays():"]
    for name in callables:
        for args in ("a", "a, a", "a, 0", "3", "3, dtype='i4,f4'", "2, dtype={'f': ('i4', 0)}"):
            lines += attempt(f"np.{name}({args})", f"x = np.{name}({args})", "    ")
    lines += ["stop_if_found('numpy functions')", "for a in arrays():"]
    for name in ufuncs:
        for method in sorted(backtest._UFUNC_ALLOWED_ATTRS - {"nin", "nout"}):
            for args in ("a", "a, a", "a, 0", "a, [0, 1]"):
                lines += attempt(f"np.{name}.{method}({args})", f"x = np.{name}.{method}({args})", "    ")
    lines += ["stop_if_found('ufunc methods')"]

    # 4. operators between arrays, numpy scalars and pandas scalars (the warnings of 3.13 are here)
    lines += [
        "operands = arrays()[:6] + frame_arrays() + [np.zeros(3), pd.NaT, df.index[0], df.index[1] - df.index[0], 2, 2.5]",
        "for a in operands:",
        "    for b in operands:",
    ]
    for op in ("+", "-", "*", "/", "//", "%", "**", "==", "<"):
        lines += attempt(f"a {op} b", f"x = a {op} b", "        ")
    lines += attempt("divmod(a, b)", "x = divmod(a, b)", "        ")
    for statement in (
        "x = (10**5000) // (10**3000)",
        "x = divmod(10**5000, 10**3000)",
        "x = np.log(np.zeros(3))",
        "x = np.sqrt(-np.ones(3))",
        "x = np.exp(np.ones(3) * 1000.0)",
    ):
        lines += attempt(statement, statement)
    lines += ["stop_if_found('operators')"]

    # 5. dates: the allowed names of a Timestamp and a Timedelta, and every public name of the
    #    four datetime types, which no allowlist governs
    lines += ["ts = df.index[0]", "td = df.index[1] - df.index[0]", "stamps = [ts, ts.tz_localize('UTC'), td, pd.NaT]"]
    pandas_scalar_names = sorted(
        n for n in backtest._PANDAS_ALLOWED_ATTRS if hasattr(pd.Timestamp, n) or hasattr(pd.Timedelta, n)
    )
    python_names = sorted(
        {
            n
            for t in (datetime.datetime, datetime.date, datetime.time, datetime.timedelta)
            for n in dir(t)
            if not n.startswith("_")
        }
    )
    python_dates = "[ts.to_pydatetime(), ts.date(), ts.time(), ts.to_pydatetime() - ts.to_pydatetime()]"
    for owner, names in (("stamps", pandas_scalar_names), (python_dates, python_names)):
        lines += [f"for o in {owner}:"]
        for name in names:
            lines += ["    m = None"]
            lines += attempt(f"date.{name}", f"m = o.{name}", "    ")
            lines += ["    if callable(m):"]
            for args in ("", "'%Y'", "0", "'2025-01-02', '%Y-%m-%d'"):
                lines += attempt(f"date.{name}({args})", f"m({args})", "        ")
    for statement in ("x = f'{ts:%Y}'", "x = repr(ts.tz_localize('UTC'))", "x = str(ts)", "x = str(td)"):
        lines += attempt(statement, statement)
    lines += ["stop_if_found('dates')"]

    # 6. functions written in the strategy and called by pandas
    for statement in (
        "x = df['close'].rolling(5).apply(lambda w: w.max(), raw=True)",
        "x = df[['open', 'close']].apply(lambda col: col.to_numpy().mean())",
    ):
        lines += attempt(statement, statement)
    lines += ["stop_if_found('strategy functions called by pandas')", "df['signal'] = 0"]
    return "\n".join(lines) + "\n"


def _answer_of_a_fresh_child(target: Any, *args: Any) -> Any:
    """Start `target(*args, conn)` in a spawned interpreter and return what it sends."""
    ctx = multiprocessing.get_context("spawn")
    reader, writer = ctx.Pipe(duplex=False)
    process = ctx.Process(target=target, args=(*args, writer))
    process.start()
    writer.close()
    try:
        if not reader.poll(60):
            pytest.fail("the child did not answer within 60 s")
        return reader.recv()
    except EOFError:
        process.join(5)
        pytest.fail(f"the child died without answering (exit code {process.exitcode})")
    finally:
        reader.close()
        process.join(5)
        if process.is_alive():
            process.kill()
            process.join()


def test_the_numpy_vocabulary_runs_in_one_fresh_child_without_an_import_it_cannot_get(ohlcv):
    """The guard that would have caught the defect before a dependency release did.

    The target is the real child entry point, so the compile, the namespace and the `exec`
    are the ones a backtest uses; only `run_backtest`'s 4,096-character limit is bypassed,
    because a sweep of the vocabulary does not fit in it. One child is enough, and it need
    not be cold for every statement: a refused import fills no cache, so the same request is
    refused again wherever it comes back, and the first statement of the first group already
    runs before anything else has. CI runs this weekly on a fresh resolve for Python 3.11,
    3.12 and 3.13, which is where a new numpy, pandas or CPython first meets it.
    """
    status, payload = _answer_of_a_fresh_child(backtest._execute_in_subprocess, _sweep_strategy(), ohlcv)
    assert status == "ok", payload


# ── What a strategy still cannot do ───────────────────────────────────────────

_IMPORT_STATEMENTS = {
    "import": "import os\n",
    "from-import": "from os import path\n",
    "import-as": "import numpy as np\n",
    "inside a function that is called": "def f():\n    import os\n    return os\nx = f()\n",
    "inside a function pandas calls": "def g(v):\n    import os\n    return 1.0\nx = df['close'].map(g)\n",
}


@pytest.mark.parametrize("form", sorted(_IMPORT_STATEMENTS))
def test_an_import_statement_in_strategy_code_is_still_refused(ohlcv, form):
    """The import service exists for C code only. A strategy's own `import` looks in the
    frame's builtins DICT, which holds no `__import__`, and CPython refuses it as before."""
    with pytest.raises(ImportError, match="__import__ not found"):
        exec(compile_restricted(_IMPORT_STATEMENTS[form], "<s>", "exec"), build_sandbox(ohlcv.copy()))  # noqa: S102


_REACHING_FOR_THE_BUILTINS = {
    "the name __builtins__": "x = __builtins__\n",
    "the name __import__": "x = __import__('os')\n",
    "a function's __globals__": "x = (lambda: 0).__globals__\n",
    "an attribute inside an f-string": "x = f'{df.__class__}'\n",
    "a frame through a generator": "x = (v for v in [1]).gi_frame\n",
}


@pytest.mark.parametrize("form", sorted(_REACHING_FOR_THE_BUILTINS))
def test_strategy_code_cannot_name_its_way_to_the_builtins_object(form):
    """The import service is an attribute of the object passed as `__builtins__`. What keeps
    strategy code away from that object is RestrictedPython's compiler: no name or attribute
    that starts with an underscore, no frame attribute. If one of these ever compiles, what
    the service exposes has to be examined again before anything else is done."""
    with pytest.raises(SyntaxError, match=r"starts with|restricted name"):
        compile_restricted(_REACHING_FOR_THE_BUILTINS[form], "<s>", "exec")


def test_the_attribute_guard_refuses_the_service_even_on_the_builtins_object(ohlcv):
    """Second layer: handed the builtins object itself, the sandbox's `_getattr_` hook still
    refuses `__import__`, as it refuses every name that starts with an underscore."""
    builtins = build_sandbox(ohlcv)["__builtins__"]
    with pytest.raises(AttributeError, match="starts with"):
        backtest._sandboxed_getattr(builtins, "__import__")


def test_strategy_frames_resolve_builtins_in_restrictedpythons_safe_set_and_nothing_else(ohlcv):
    """A name here is a builtin handed to model-written code. Each one is a name of
    RestrictedPython's safe set and RestrictedPython's own object; `__import__` in particular is
    not among them. WHICH names of that set a strategy gets is this project's list, held by
    `test_sandbox_builtins_are_exactly_the_documented_set` in `test_sandbox_boundary.py`."""
    builtins = build_sandbox(ohlcv)["__builtins__"]
    namespace = builtins if isinstance(builtins, dict) else vars(builtins)
    assert "__import__" not in namespace
    assert all(name in safe_builtins and namespace[name] is safe_builtins[name] for name in namespace)
    assert namespace is not safe_builtins, "each sandbox gets its own copy, not RestrictedPython's shared dict"


def test_the_import_service_loads_nothing_and_returns_nothing():
    """CPython discards what `__import__` returns to `PyImport_Import` and reads the module
    from `sys.modules` itself, so the service has nothing to return and no reason to load:
    it answers for a loaded module and refuses any other, in words that explain themselves."""
    serve: Any = backtest._serve_c_import  # as CPython calls it: name, globals, locals, fromlist, level
    assert "this" not in sys.modules, "precondition: pick a standard-library module nothing has loaded"
    with pytest.raises(ImportError, match=r"backtest sandbox: .*'this'"):
        serve("this", {}, {}, [], 0)
    assert "this" not in sys.modules
    assert serve("numpy", {}, {}, [], 0) is None


def test_the_modules_loaded_ahead_of_a_strategy_are_exactly_the_documented_ones():
    """Each name here is a module the child loads for no other reason than that C code may
    ask for it later. Adding one is a decision; make it here too."""
    assert backtest._PRELOADED_FOR_C_CODE == ("_strptime", "_pylong")


def _child_with_strptime_unloaded(when: str, code: str, df: pd.DataFrame, conn: Connection) -> None:
    """Spawn target. `_strptime` is the one module C code asks for that a test can unload."""
    if when == "before the real child runs":
        sys.modules.pop("_strptime", None)
        backtest._execute_in_subprocess(code, df, conn)
        return
    backtest._preload_for_c_code()
    sandbox = build_sandbox(df)
    sys.modules.pop("_strptime", None)  # after everything the real child does before the strategy
    try:
        exec(compile_restricted(code, "<strategy>", "exec"), sandbox)  # noqa: S102
    except Exception as exc:
        conn.send(("runtime_error", f"{type(exc).__name__}: {exc}"))
        return
    conn.send(("ok", None))


_STRPTIME = "x = df.index[0].to_pydatetime().strptime('2025-01-02', '%Y-%m-%d')\ndf['signal'] = 0\n"


def test_the_child_loads_what_c_code_will_ask_for_before_the_strategy_runs(ohlcv):
    """pandas happens to import `_strptime` today. The child does not rely on that: with the
    module unloaded first, the real child entry point loads it again and `strptime` works."""
    status, payload = _answer_of_a_fresh_child(
        _child_with_strptime_unloaded, "before the real child runs", _STRPTIME, ohlcv
    )
    assert status == "ok", payload


def test_a_module_the_sandbox_has_not_loaded_is_refused_in_words_that_explain_themselves(ohlcv):
    """Fails closed, and says what happened: the module's name, and that the limit is the
    sandbox's and not a mistake in the strategy."""
    status, payload = _answer_of_a_fresh_child(
        _child_with_strptime_unloaded, "after the sandbox is built", _STRPTIME, ohlcv
    )
    assert status == "runtime_error"
    assert "backtest sandbox" in payload and "'_strptime'" in payload and "not an error in the strategy" in payload
