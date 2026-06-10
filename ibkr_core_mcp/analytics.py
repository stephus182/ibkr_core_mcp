from __future__ import annotations
import numpy as np
import pandas as pd


def sharpe(returns: pd.Series, risk_free: float = 0.0, periods: int = 252) -> float:
    excess = returns - risk_free / periods
    std = excess.std()
    if not std or pd.isna(std):
        return 0.0
    return float(excess.mean() / std * np.sqrt(periods))


def sortino(returns: pd.Series, risk_free: float = 0.0, periods: int = 252) -> float:
    excess = returns - risk_free / periods
    downside = excess[excess < 0].std()
    if not downside or pd.isna(downside):
        return 0.0
    return float(excess.mean() / downside * np.sqrt(periods))


def max_drawdown(returns: pd.Series) -> float:
    equity = (1 + returns).cumprod()
    peak = equity.cummax().replace(0, float("nan"))
    dd = (equity - peak) / peak
    return float(dd.min()) if len(dd) > 0 else 0.0


def max_drawdown_duration(returns: pd.Series) -> int:
    equity = (1 + returns).cumprod()
    peak = equity.cummax()
    in_dd = (equity < peak).astype(int)
    max_dur = 0
    cur = 0
    for v in in_dd:
        cur = cur + 1 if v else 0
        max_dur = max(max_dur, cur)
    return max_dur


def cagr(returns: pd.Series, periods: int = 252) -> float:
    total = float((1 + returns).prod())
    n = len(returns) / periods
    if n <= 0 or total <= 0:
        return 0.0
    return float(total ** (1.0 / n) - 1)


def calmar(returns: pd.Series, periods: int = 252) -> float:
    mdd = max_drawdown(returns)
    if mdd == 0:
        return 0.0
    return float(cagr(returns, periods) / abs(mdd))


def win_rate(trades: list[dict]) -> float:
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if _pnl(t) > 0)
    return wins / len(trades)


def profit_factor(trades: list[dict]) -> float:
    gains = sum(_pnl(t) for t in trades if _pnl(t) > 0)
    losses = sum(abs(_pnl(t)) for t in trades if _pnl(t) < 0)
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return gains / losses


def avg_win_loss_ratio(trades: list[dict]) -> float:
    wins = [_pnl(t) for t in trades if _pnl(t) > 0]
    losses = [abs(_pnl(t)) for t in trades if _pnl(t) < 0]
    avg_w = sum(wins) / len(wins) if wins else 0.0
    avg_l = sum(losses) / len(losses) if losses else 0.0
    if avg_l == 0:
        return float("inf") if avg_w > 0 else 0.0
    return avg_w / avg_l


def trade_summary(trades: list[dict]) -> dict:
    return {
        "total_trades": len(trades),
        "win_rate": win_rate(trades),
        "profit_factor": profit_factor(trades),
        "avg_win_loss_ratio": avg_win_loss_ratio(trades),
    }


def full_report(returns: pd.Series, trades: list[dict] | None = None) -> dict:
    report: dict = {
        "total_return": float((1 + returns).prod() - 1),
        "cagr": cagr(returns),
        "sharpe": sharpe(returns),
        "sortino": sortino(returns),
        "calmar": calmar(returns),
        "max_drawdown": max_drawdown(returns),
        "max_drawdown_duration": max_drawdown_duration(returns),
        "num_bars": len(returns),
    }
    if trades:
        report.update(trade_summary(trades))
    return report


def _pnl(trade: dict) -> float:
    return float(trade.get("pnl", trade.get("realizedPnl", 0)))
