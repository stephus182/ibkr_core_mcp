"""Worked example for audit register item 12: sortino/calmar variant decision.

Computes both variants of each metric on REAL data — the cached AAPL 1D 6m bars
(AAPL_1D_6M_2026-07-06, 121 rows) that back the stored 'MACD Long-Only' backtest —
for two real return series: buy-and-hold, and the MACD(12,26,9) long-only strategy.

Sortino variants (target T = 0):
  current   = mean(excess) / sample_std(excess[excess < 0]) * sqrt(252)
              (simplified discrete form — std over ONLY the below-target returns)
  canonical = mean(excess) / sqrt(mean(min(excess, 0)^2)) * sqrt(252)
              (target downside deviation over ALL observations, no mean-centering
               — Sortino/van der Meer, Rollinger & Hoffman "Sortino: A Sharper Ratio")
  Source: https://en.wikipedia.org/wiki/Sortino_ratio

Calmar variants:
  current = CAGR(whole series) / |maxDD(whole series)|   (MAR-ratio convention)
  Young 1991 = same ratio over the TRAILING 36 MONTHS of monthly data
  Source: https://en.wikipedia.org/wiki/Calmar_ratio

Run (needs Drive credentials; reads claudia_ui's .env for them):
  .venv/bin/python scripts/audit/sortino_calmar_worked_example.py

Result 2026-07-07 (recorded in docs/claude-tools-audit-2026-07.md, Findings
analysis → Open-item priorities): buy-and-hold 2.1924 → 2.3395 (+6.7%);
MACD long-only 1.9954 → 3.1083 (+55.8%). Calmar variants coincide on any
window <= 36 months, so the 6-month example cannot distinguish them.

DECISION EXECUTED 2026-07-07: analytics.sortino was migrated to the canonical
TDD form after verifying TradingView's documented calculation matches it
(support article 43000756110). The 'sortino current' column below therefore
now equals 'sortino canonical' when rerun; the historical delta this script
demonstrated is preserved in the audit report. analytics.calmar kept as
whole-series MAR (owner decision).
"""

import numpy as np
import pandas as pd
from dotenv import load_dotenv

from ibkr_core_mcp import Config, GDriveCache, analytics

PERIODS = 252
ENV_FILE = "/Users/steph/Claude_Projects/claudia_ui/.env"


def sortino_current(returns: pd.Series) -> float:
    return analytics.sortino(returns, periods=PERIODS)


def sortino_canonical(returns: pd.Series, target: float = 0.0) -> float:
    excess = returns - target
    tdd = float(np.sqrt(np.mean(np.square(np.minimum(excess, 0.0)))))
    if tdd == 0:
        return 0.0
    return float(excess.mean() / tdd * np.sqrt(PERIODS))


def main() -> None:
    load_dotenv(ENV_FILE)
    cache = GDriveCache(Config.from_env())
    df = cache.load("AAPL", "1D", "6m", "2026-07-06")
    close = df["close"] if "close" in df.columns else df["c"]
    bh = close.pct_change().dropna()

    # Reconstruct the stored 'MACD Long-Only' strategy on the same bars:
    # long when MACD line > signal line, flat otherwise (position lagged one bar).
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    position = (macd_line > signal_line).astype(int).shift(1).fillna(0)
    strat = (bh * position.reindex(bh.index).fillna(0)).astype(float)

    print(f"Dataset: AAPL 1D 6m ending 2026-07-06 — {len(df)} bars, {len(bh)} returns")
    print(f"Bars span: {df.index[0]} .. {df.index[-1]}")
    print()
    print(f"{'series':<22}{'sortino current':>17}{'sortino canonical':>19}{'delta %':>9}")
    for name, r in (("buy-and-hold", bh), ("MACD long-only", strat)):
        cur = sortino_current(r)
        can = sortino_canonical(r)
        delta = (can - cur) / cur * 100 if cur else float("nan")
        print(f"{name:<22}{cur:>17.4f}{can:>19.4f}{delta:>8.1f}%")
    print()
    print("calmar (current = whole-series MAR convention):")
    for name, r in (("buy-and-hold", bh), ("MACD long-only", strat)):
        print(f"  {name:<20} {analytics.calmar(r, periods=PERIODS):.4f}")
    months = (df.index[-1] - df.index[0]).days / 30.44
    print(
        f"\nYoung-1991 trailing-36-month Calmar: NOT COMPUTABLE on this series — "
        f"only {months:.1f} months of data (needs 36). On any window <= 36 months "
        "the two conventions coincide over the available data."
    )


if __name__ == "__main__":
    main()
