"""Portfolio analytics — Sharpe, Sortino, Calmar, CAGR, drawdown, and win-rate metrics.

Conventions (verified against sources 2026-07-02; see each function's docstring):
- Annualisation uses `periods` = bars per YEAR (derive via periods_for_timeframe()).
- `sortino` implements the simplified discrete variant, not canonical target
downside deviation; `calmar` is whole-series (formally the MAR-ratio convention),
not Young's trailing-36-month Calmar. Both variants are widespread, but numbers
are not comparable across tools that use the canonical forms — read the docstrings before quoting these figures against external references.
"""

from __future__ import annotations

import re
from typing import Any

import numpy as np
import pandas as pd

_TRADING_DAYS_PER_YEAR = 252
# Bars per year at n=1, per bar-size unit (IBKR bar notation; 'm' = month).
# Intraday assumes the US equity regular session: 6.5 h = 390 min per day.
_BARS_PER_YEAR_BY_UNIT = {
    "min": 390 * _TRADING_DAYS_PER_YEAR,  # 98,280
    "h": int(6.5 * _TRADING_DAYS_PER_YEAR),  # 1,638
    "d": _TRADING_DAYS_PER_YEAR,
    "w": 52,
    "m": 12,
}


def periods_for_timeframe(timeframe: str) -> int | None:
    """Bars per year for a bar-size string — the `periods` annualisation input.

    Follows IBKR bar-size notation, case-insensitive: '5min', '1h', '1d', '1w',
    '1m' (month — not minute, matching IBKR's bar values). Intraday counts assume
    the US equity regular session (6.5 h/day, 252 days/yr); for near-24h products
    (e.g. CME futures) this understates bars per year — pass an explicit
    ``periods=`` to full_report()/sharpe() when that precision matters.

    Returns None when the string is not a recognized bar size.
    """
    m = re.fullmatch(r"(\d+)\s*(min|h|d|w|m)", timeframe.strip().lower())
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    if n <= 0:
        return None
    return max(1, round(_BARS_PER_YEAR_BY_UNIT[unit] / n))


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

    Note: ex-post Sharpe annualised by sqrt(periods), which assumes IID per-bar
    returns — autocorrelated (e.g. trending intraday) series overstate the
    annualised figure. Source: Lo (2002), "The Statistics of Sharpe Ratios",
    Financial Analysts Journal 58(4): https://doi.org/10.2469/faj.v58.n4.2453
    (citation verified 2026-07-02).
    """
    excess = returns - risk_free / periods
    std = excess.std()
    if not std or pd.isna(std):
        return 0.0
    return float(excess.mean() / std * np.sqrt(periods))


def sortino(returns: pd.Series, risk_free: float = 0.0, periods: int = 252) -> float:
    """Annualised Sortino ratio (penalises only downside volatility).

    Implements the CANONICAL target-downside-deviation form: the denominator is
    sqrt(mean(min(r − T, 0)²)) computed over ALL observations, without
    mean-centering (Sortino/van der Meer; Rollinger & Hoffman "Sortino: A Sharper
    Ratio"). This matches TradingView's documented calculation exactly — their
    reference implementation sums min(0, r − target)² over every period and
    divides by the total period count (support article 43000756110, "Analysis:
    Sortino ratio", verified 2026-07-07) — so figures are comparable with TV and
    other canonical-form tools.

    MIGRATED 2026-07-07 (audit register item 12, owner-decided after verifying
    TradingView's definition): previously this was the *simplified discrete*
    form (sample std of only the below-target excess returns) that the canonical
    authors explicitly disfavor. Sortino figures computed before the migration
    are NOT comparable with current output — on real data the delta reached
    +55.8% for a flat-heavy signal strategy (see
    scripts/audit/sortino_calmar_worked_example.py).
    Source: https://en.wikipedia.org/wiki/Sortino_ratio (Definition section) +
    https://www.tradingview.com/support/solutions/43000756110-analysis-sortino-ratio/

    Args:
        returns: Per-bar return series.
        risk_free: Annualised risk-free rate. Default 0.
        periods: Trading periods per year. See ``sharpe`` for values.

    Returns:
        Annualised Sortino ratio; 0.0 if target downside deviation is zero
        (no below-target returns) or the series is empty.
    """
    if len(returns) == 0:
        return 0.0
    excess = returns - risk_free / periods
    downside = float(np.sqrt(np.mean(np.square(np.minimum(excess, 0.0)))))
    if downside == 0 or np.isnan(downside):
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
    return 0.0 if n <= 0 or total <= 0 else float(total ** (1.0 / n) - 1)


def calmar(returns: pd.Series, periods: int = 252) -> float:
    """Calmar ratio: CAGR divided by absolute max drawdown. 0.0 if drawdown is zero.

    VARIANT NOTE (verified 2026-07-02; owner-decided KEEP 2026-07-07, audit
    register item 12): computed over the WHOLE supplied series. Young's original
    Calmar (Futures, 1991) uses the trailing 36 months on a monthly basis; the
    from-inception form implemented here is formally the MAR-ratio convention.
    On any window <= 36 months the two coincide over the available data, which
    covers every stored backtest — hence the decision to keep this form.
    Source: https://en.wikipedia.org/wiki/Calmar_ratio (Young 1991 definition and
    the Calmar-vs-MAR distinction).
    """
    mdd = max_drawdown(returns)
    return 0.0 if mdd == 0 else float(cagr(returns, periods) / abs(mdd))


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


def full_report(
    returns: pd.Series,
    trades: list[dict[str, Any]] | None = None,
    periods: int = 252,
) -> dict[str, Any]:
    """Complete performance report combining return-series and trade-level metrics.

    Args:
        returns: Per-bar return series.
        trades: Optional list of trade dicts with 'pnl' or 'realizedPnl' fields.
            If provided, adds win_rate, profit_factor, avg_win_loss_ratio, total_trades.
        periods: Trading periods per year for annualisation — 252 for daily (default),
            98,280 for 1-min bars (390 × 252), 19,656 for 5-min bars (78 × 252).
            Derive from a bar-size string with ``periods_for_timeframe()``.
            (Earlier versions of this docstring gave per-day counts here — wrong
            unit for this parameter.)

    Returns:
        Dict with keys: total_return, cagr, sharpe, sortino, calmar, max_drawdown,
        max_drawdown_duration, num_bars, and optionally trade-level metrics.
    """
    report: dict[str, Any] = {
        "total_return": float((1 + returns).prod() - 1),
        "cagr": cagr(returns, periods),
        "sharpe": sharpe(returns, periods=periods),
        "sortino": sortino(returns, periods=periods),
        "calmar": calmar(returns, periods),
        "max_drawdown": max_drawdown(returns),
        "max_drawdown_duration": max_drawdown_duration(returns),
        "num_bars": len(returns),
    }
    return report | trade_summary(trades) if trades else report


def _pnl(trade: dict[str, Any]) -> float:
    return float(trade.get("pnl", trade.get("realizedPnl", 0)))
