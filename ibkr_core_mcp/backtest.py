from __future__ import annotations
from dataclasses import dataclass, field
import pandas as pd
import numpy as np

from RestrictedPython import compile_restricted, safe_globals, limited_builtins
from RestrictedPython.Guards import safer_getattr, full_write_guard

from ibkr_core_mcp.exceptions import BacktestSyntaxError, BacktestRuntimeError
from ibkr_core_mcp import analytics as _analytics


@dataclass
class BacktestResult:
    symbol: str
    strategy_name: str
    total_return: float
    sharpe: float
    sortino: float
    max_drawdown: float
    num_trades: int
    win_rate: float
    equity_curve: pd.Series = field(default_factory=pd.Series)

    def to_dict(self) -> dict:
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


def run_backtest(
    code: str,
    df: pd.DataFrame,
    strategy_name: str = "",
    symbol: str = "",
) -> BacktestResult:
    """Execute strategy code in a RestrictedPython sandbox and return performance metrics.

    Strategy code receives `df` (OHLCV DataFrame) and must set df['signal']:
        1 = long, 0 = flat, -1 = short
    Allowed: pandas (pd), numpy (np), basic builtins.
    Blocked: network, file I/O, os, sys.
    """
    try:
        byte_code = compile_restricted(code, "<strategy>", "exec")
    except SyntaxError as e:
        raise BacktestSyntaxError(f"Strategy syntax error: {e}") from e

    # RestrictedPython requires explicit write/getattr guards in the sandbox dict
    sandbox: dict = {
        **safe_globals,
        "_write_": lambda ob: ob,       # allow writes to all objects (pd/np trusted)
        "_getattr_": safer_getattr,
        "_getitem_": lambda ob, key: ob[key],
        "_getiter_": iter,
        "__builtins__": {
            k: v for k, v in limited_builtins.items()
            if k not in ("__import__", "open", "eval", "exec", "compile")
        },
        "pd": pd,
        "np": np,
        "float": float,
        "int": int,
        "abs": abs,
        "range": range,
        "len": len,
        "df": df.copy(),
    }

    try:
        exec(byte_code, sandbox)  # noqa: S102
    except Exception as e:
        raise BacktestRuntimeError(f"Strategy runtime error: {e}") from e

    result_df: pd.DataFrame = sandbox.get("df", df)

    if "signal" not in result_df.columns:
        raise BacktestRuntimeError("Strategy must set df['signal'] (1=long, 0=flat, -1=short)")

    return _compute_metrics(result_df, strategy_name=strategy_name, symbol=symbol)


def _compute_metrics(df: pd.DataFrame, strategy_name: str, symbol: str) -> BacktestResult:
    sig = df["signal"].fillna(0).shift(1).fillna(0)  # trade on next bar open
    price_returns = df["close"].pct_change().fillna(0)
    strategy_returns = sig * price_returns

    equity = (1 + strategy_returns).cumprod()

    # Count trades (signal changes)
    signal_changes = (sig.diff().abs() > 0).sum()
    num_trades = int(signal_changes)

    # Win rate: fraction of non-zero return bars where we profited
    active = strategy_returns[sig != 0]
    wr = float((active > 0).sum() / len(active)) if len(active) > 0 else 0.0

    total_return = float(equity.iloc[-1] - 1) if len(equity) > 0 else 0.0

    # Flat strategy
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
