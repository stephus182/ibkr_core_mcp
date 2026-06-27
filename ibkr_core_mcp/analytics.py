"""Portfolio analytics — Sharpe, Sortino, Calmar, CAGR, drawdown, and win-rate metrics."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def sharpe(returns: pd.Series, risk_free: float = 0.0, periods: int = 252) -> float:
    """Annualised Sharpe ratio.

    Args:
        returns: Per-bar return series (e.g. daily close-to-close pct change).
        risk_free: Annualised risk-free rate (e.g. 0.05 for 5 %). Default 0.
        periods: Trading periods per year used for annualisation.
            252 = daily bars (default). Use 252*390 for 1-minute bars,
            52 for weekly bars, 12 for monthly bars.

    Returns:
        Annualised Sharpe ratio; 0.0 if std is zero or NaN.
    """
    excess = returns - risk_free / periods
    std = excess.std()
    if not std or pd.isna(std):
        return 0.0
    return float(excess.mean() / std * np.sqrt(periods))


def sortino(returns: pd.Series, risk_free: float = 0.0, periods: int = 252) -> float:
    """Annualised Sortino ratio (penalises only downside volatility).

    Args:
        returns: Per-bar return series.
        risk_free: Annualised risk-free rate. Default 0.
        periods: Trading periods per year. See ``sharpe`` for values.

    Returns:
        Annualised Sortino ratio; 0.0 if downside std is zero or NaN.
    """
    excess = returns - risk_free / periods
    downside = excess[excess < 0].std()
    if not downside or pd.isna(downside):
        return 0.0
    return float(excess.mean() / downside * np.sqrt(periods))


def max_drawdown(returns: pd.Series) -> float:
    """Maximum peak-to-trough drawdown as a negative fraction (e.g. -0.25 = -25 %).

    Returns 0.0 for an empty series.
    """
    equity = (1 + returns).cumprod()
    peak = equity.cummax().replace(0, float("nan"))
    dd = (equity - peak) / peak
    return float(dd.min()) if len(dd) > 0 else 0.0


def max_drawdown_duration(returns: pd.Series) -> int:
    """Longest consecutive streak of bars spent below a prior equity peak, in bars."""
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
    """Compound Annual Growth Rate.

    Args:
        returns: Per-bar return series.
        periods: Trading periods per year. See ``sharpe`` for values.
    """
    total = float((1 + returns).prod())
    n = len(returns) / periods
    if n <= 0 or total <= 0:
        return 0.0
    return float(total ** (1.0 / n) - 1)


def calmar(returns: pd.Series, periods: int = 252) -> float:
    """Calmar ratio: CAGR divided by absolute max drawdown. 0.0 if drawdown is zero."""
    mdd = max_drawdown(returns)
    if mdd == 0:
        return 0.0
    return float(cagr(returns, periods) / abs(mdd))


def win_rate(trades: list[dict[str, Any]]) -> float:
    """Fraction of trades with positive P&L. Reads 'pnl' or 'realizedPnl' field."""
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if _pnl(t) > 0)
    return wins / len(trades)


def profit_factor(trades: list[dict[str, Any]]) -> float:
    """Gross profit divided by gross loss. Returns inf if no losing trades, 0.0 if no trades."""
    gains = sum(_pnl(t) for t in trades if _pnl(t) > 0)
    losses = sum(abs(_pnl(t)) for t in trades if _pnl(t) < 0)
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return gains / losses


def avg_win_loss_ratio(trades: list[dict[str, Any]]) -> float:
    """Average winning trade size divided by average losing trade size."""
    wins = [_pnl(t) for t in trades if _pnl(t) > 0]
    losses = [abs(_pnl(t)) for t in trades if _pnl(t) < 0]
    avg_w = sum(wins) / len(wins) if wins else 0.0
    avg_l = sum(losses) / len(losses) if losses else 0.0
    if avg_l == 0:
        return float("inf") if avg_w > 0 else 0.0
    return avg_w / avg_l


def trade_summary(trades: list[dict[str, Any]]) -> dict[str, Any]:
    """Win rate, profit factor, and avg win/loss ratio rolled into one dict."""
    return {
        "total_trades": len(trades),
        "win_rate": win_rate(trades),
        "profit_factor": profit_factor(trades),
        "avg_win_loss_ratio": avg_win_loss_ratio(trades),
    }


def full_report(returns: pd.Series, trades: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Complete performance report combining return-series and trade-level metrics.

    Args:
        returns: Per-bar return series (daily by default — affects CAGR/Sharpe/Sortino/Calmar).
            Pass ``periods`` to the underlying functions if using intraday bars.
        trades: Optional list of trade dicts with 'pnl' or 'realizedPnl' fields.
            If provided, adds win_rate, profit_factor, avg_win_loss_ratio, total_trades.

    Returns:
        Dict with keys: total_return, cagr, sharpe, sortino, calmar, max_drawdown,
        max_drawdown_duration, num_bars, and optionally trade-level metrics.
    """
    report: dict[str, Any] = {
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


def _pnl(trade: dict[str, Any]) -> float:
    return float(trade.get("pnl", trade.get("realizedPnl", 0)))
