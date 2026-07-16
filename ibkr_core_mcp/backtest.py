"""RestrictedPython sandbox executor for backtesting strategy code on OHLCV DataFrames."""
from __future__ import annotations

import multiprocessing
import queue
import types
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from RestrictedPython import compile_restricted, safe_globals
from RestrictedPython.Guards import full_write_guard, safer_getattr
from RestrictedPython.Limits import limited_range

from ibkr_core_mcp import analytics as _analytics
from ibkr_core_mcp.exceptions import BacktestRuntimeError, BacktestSyntaxError

_MAX_CODE_LEN = 4096
_EXEC_TIMEOUT = 10  # seconds
_KILL_GRACE_S = 1.0  # seconds to wait after SIGTERM before escalating to SIGKILL


def _write_guard(ob: object) -> object:
    """Block writes to modules and safe namespaces; allow all other writes.

    Strategy code must assign columns (df['signal'] = ..., df.loc[...] = ...)
    but must not mutate the shared pd/np namespaces passed into the sandbox.
    We block writes to `types.ModuleType` and `types.SimpleNamespace` (our safe
    namespace wrappers) and allow everything else through untouched.
    """
    if isinstance(ob, (types.ModuleType, types.SimpleNamespace)):
        return full_write_guard(ob)
    return ob


# df.eval()/df.query() run pandas' OWN expression engine (pandas/core/computation/
# expr.py) on a string, entirely outside compile_restricted's AST-level guards —
# it does unfiltered getattr/getitem/call resolution and can reach @varname (the
# sandbox's own locals), then walk __init__.__func__.__globals__ to pandas'
# unrestricted module globals, then sys.modules['os'] for RCE. safer_getattr does
# not block these — they're ordinary public method names, not dunders. Block them
# explicitly. See docs/audits/security-audit-2026-07-11.md H-1.
_DENIED_ATTRS = frozenset({"eval", "query"})


def _sandboxed_getattr(obj: object, name: str, default: object = None) -> object:
    if name in _DENIED_ATTRS:
        raise AttributeError(
            f"backtest sandbox: access to {name!r} is blocked — pandas' own "
            "eval/query expression engine is not sandboxed by RestrictedPython"
        )
    return safer_getattr(obj, name, default)  # type: ignore[no-untyped-call]


# Safe numpy namespace — math/array operations only, no file I/O
_SAFE_NP = types.SimpleNamespace(
    array=np.array,
    zeros=np.zeros,
    ones=np.ones,
    nan=np.nan,
    inf=np.inf,
    where=np.where,
    isnan=np.isnan,
    isinf=np.isinf,
    mean=np.mean,
    std=np.std,
    sum=np.sum,
    cumsum=np.cumsum,
    cumprod=np.cumprod,
    diff=np.diff,
    log=np.log,
    log2=np.log2,
    exp=np.exp,
    sqrt=np.sqrt,
    abs=np.abs,
    maximum=np.maximum,
    minimum=np.minimum,
    clip=np.clip,
    percentile=np.percentile,
    arange=np.arange,
    linspace=np.linspace,
    sign=np.sign,
    floor=np.floor,
    ceil=np.ceil,
    round=np.round,
    argmax=np.argmax,
    argmin=np.argmin,
)

# Safe pandas namespace — in-memory constructors only, no read_*/to_* I/O
_SAFE_PD = types.SimpleNamespace(
    DataFrame=pd.DataFrame,
    Series=pd.Series,
    concat=pd.concat,
    to_datetime=pd.to_datetime,
    isna=pd.isna,
    notna=pd.notna,
    NaT=pd.NaT,
    NA=pd.NA,
)


@dataclass
class BacktestResult:
    """Performance metrics returned by run_backtest()."""

    symbol: str
    strategy_name: str
    total_return: float
    sharpe: float
    sortino: float
    max_drawdown: float
    num_trades: int
    win_rate: float
    equity_curve: pd.Series = field(default_factory=pd.Series)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "strategy_name": self.strategy_name,
            "total_return": self.total_return,
            "sharpe": self.sharpe,
            "sortino": self.sortino,
            "max_drawdown": self.max_drawdown,
            "num_trades": self.num_trades,
            "win_rate": self.win_rate,
        }


def _execute_in_subprocess(code: str, df: pd.DataFrame, result_queue: Any) -> None:
    """Compile and run strategy code inside an isolated child process.

    Runs entirely in the child (both compile_restricted and exec) so the parent
    can kill the whole OS process on timeout — a thread cannot be forcibly
    stopped once it's running, a process can. `result_queue` is a
    multiprocessing.Queue; puts a ("ok", df) / ("syntax_error", msg) /
    ("runtime_error", msg) tuple.
    """
    try:
        byte_code = compile_restricted(code, "<strategy>", "exec")
    except SyntaxError as e:
        result_queue.put(("syntax_error", str(e)))
        return

    sandbox: dict[str, Any] = {
        **safe_globals,
        "_write_": _write_guard,
        "_getattr_": _sandboxed_getattr,
        "_getitem_": lambda ob, key: ob[key],
        "_getiter_": iter,
        "pd": _SAFE_PD,
        "np": _SAFE_NP,
        "float": float,
        "int": int,
        "abs": abs,
        "range": limited_range,
        "len": len,
        "df": df,
    }
    try:
        exec(byte_code, sandbox)  # noqa: S102
    except Exception as e:
        result_queue.put(("runtime_error", f"{type(e).__name__}: {e}"))
        return

    result_queue.put(("ok", sandbox.get("df", df)))


def run_backtest(
    code: str,
    df: pd.DataFrame,
    strategy_name: str = "",
    symbol: str = "",
) -> BacktestResult:
    """Execute strategy code in a RestrictedPython sandbox and return performance metrics.

    Strategy code receives `df` (OHLCV DataFrame) and must set df['signal']:
        1 = long, 0 = flat, -1 = short
    Allowed: pd (safe subset), np (safe subset), basic builtins.
    Blocked: network access, os, sys, imports, attribute/name mutation,
    df.eval()/df.query() (pandas' own unsandboxed expression engine).
    Not blocked: other DataFrame public methods (df.to_csv etc.) — accepted
    residual risk, documented in SECURITY.md §Residual risk.
    """
    if len(code) > _MAX_CODE_LEN:
        raise BacktestSyntaxError(
            f"Strategy code exceeds {_MAX_CODE_LEN} character limit ({len(code)} chars)"
        )

    # safe_globals already sets __builtins__ = safe_builtins, which excludes
    # __import__, open, eval, exec, compile, print and all introspection attrs.
    # We do NOT override __builtins__ further — replacing it with the tiny
    # limited_builtins dict would strip most safe builtins and make strategies
    # unable to use isinstance, bool, etc.
    ctx = multiprocessing.get_context("spawn")
    result_queue: Any = ctx.Queue()
    process = ctx.Process(target=_execute_in_subprocess, args=(code, df, result_queue))
    process.start()

    # Read from the queue *while* waiting rather than join()-then-get_nowait():
    # a multiprocessing.Queue's child-side feeder thread blocks the child's
    # actual process exit until every put() payload is fully flushed through
    # the OS pipe. For a result DataFrame larger than the pipe buffer (a few
    # KB-64KB depending on OS), join()-then-get_nowait() would see the child
    # as still "alive" well past the point it finished computing, producing a
    # false timeout. Queue.get(timeout=...) actively drains the pipe as bytes
    # arrive, so the feeder thread never blocks on a full pipe.
    try:
        status, payload = result_queue.get(timeout=_EXEC_TIMEOUT)
    except queue.Empty:
        if process.is_alive():
            process.terminate()
            process.join(_KILL_GRACE_S)
            if process.is_alive():
                process.kill()
                process.join()
            raise BacktestRuntimeError(f"Strategy timed out after {_EXEC_TIMEOUT}s") from None
        # The child already exited without ever putting a result (e.g. a
        # segfault or an OOM-kill) — that's a crash, not a slow strategy.
        process.join()
        exitcode = process.exitcode
        detail = f"killed by signal {-exitcode}" if exitcode and exitcode < 0 else f"exit code {exitcode}"
        raise BacktestRuntimeError(f"Strategy process exited unexpectedly ({detail})") from None

    # Got a result — reap the child. Should be near-instant now that the
    # queue has been drained (the feeder thread's write already completed).
    process.join(_KILL_GRACE_S)
    if process.is_alive():
        process.terminate()
        process.join(_KILL_GRACE_S)
        if process.is_alive():
            process.kill()
            process.join()

    if status == "syntax_error":
        raise BacktestSyntaxError(f"Strategy syntax error: {payload}")
    if status == "runtime_error":
        raise BacktestRuntimeError(f"Strategy runtime error: {payload}")

    result_df: pd.DataFrame = payload

    if "signal" not in result_df.columns:
        raise BacktestRuntimeError("Strategy must set df['signal'] (1=long, 0=flat, -1=short)")

    return _compute_metrics(result_df, strategy_name=strategy_name, symbol=symbol)


def _compute_metrics(df: pd.DataFrame, strategy_name: str, symbol: str) -> BacktestResult:
    sig = df["signal"].fillna(0).shift(1).fillna(0)  # trade on next bar open
    price_returns = df["close"].pct_change().fillna(0)
    strategy_returns = sig * price_returns

    equity = (1 + strategy_returns).cumprod()

    signal_changes = (sig.diff().abs() > 0).sum()
    num_trades = int(signal_changes)

    active = strategy_returns[sig != 0]
    wr = float((active > 0).sum() / len(active)) if len(active) > 0 else 0.0

    total_return = float(equity.iloc[-1] - 1) if len(equity) > 0 else 0.0

    if (sig == 0).all():
        return BacktestResult(
            symbol=symbol,
            strategy_name=strategy_name,
            total_return=0.0,
            sharpe=0.0,
            sortino=0.0,
            max_drawdown=0.0,
            num_trades=0,
            win_rate=0.0,
            equity_curve=equity,
        )

    return BacktestResult(
        symbol=symbol,
        strategy_name=strategy_name,
        total_return=total_return,
        sharpe=_analytics.sharpe(strategy_returns),
        sortino=_analytics.sortino(strategy_returns),
        max_drawdown=_analytics.max_drawdown(strategy_returns),
        num_trades=num_trades,
        win_rate=wr,
        equity_curve=equity,
    )
