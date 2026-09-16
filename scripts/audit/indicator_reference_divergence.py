"""Worked-example evidence for the 2026-09-16 indicator audit (DATA-01 and its sweep).

Measures the PRE-FIX indicator formulas against the source authorities' own published
worked examples, and the post-fix ones beside them, so the size of each divergence is
reproducible rather than asserted. The reference columns are imported from
`tests/test_indicators_worked_examples.py`, which holds them verbatim from three
spreadsheets StockCharts ChartSchool publishes alongside its definitions.

The legacy formulas below are reproduced inline, clearly as history. They are what
`ibkr_core_mcp/indicators.py` computed before this audit; nothing imports them.

Needs no network and no credentials:
  .venv/bin/python scripts/audit/indicator_reference_divergence.py

Result 2026-09-16 (recorded in docs/audits/release-readiness-audit-2026-09-16.md):

    RSI        worst divergence 19.7791   (bar 15: 50.75 read neutral, published 70.53
                                           reads overbought — opposite signals)
    ATR        worst divergence  0.1232   = 22.2% relative; also printed a value on
                                           bar 1, where ATR has no definition
    Bollinger  worst divergence  0.1165   = band width 2.60% too wide, exactly
                                           sqrt(20/19) - 1, which is the ddof=1 vs
                                           ddof=0 ratio and confirms the cause

Every post-fix figure agrees with the published column to within that spreadsheet's
own rounding (5e-5 or better).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Run as `python scripts/audit/<this>.py` from the repo root: Python puts the script's
# own directory on sys.path, not the working directory, so the reference columns in
# tests/ are not importable without this.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ibkr_core_mcp import indicators
from tests.test_indicators_worked_examples import (
    ATR_CLOSE,
    ATR_EXPECTED,
    ATR_HIGH,
    ATR_LOW,
    BB_PRICE,
    BB_UPPER,
    RSI_CLOSE,
    RSI_EXPECTED,
)


def _frame(high: list[float], low: list[float], close: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": close,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.ones(len(close)),
        },
        index=pd.RangeIndex(len(close)),
    )


def _published(values: list[float | None]) -> pd.Series:
    return pd.Series([np.nan if v is None else v for v in values], dtype=float)


def legacy_rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Pre-2026-09-16 rsi(): Wilder's alpha, but seeded with the first observation."""
    delta = df["close"].diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, float("nan"))
    result = 100 - (100 / (1 + rs))
    result = result.mask((loss == 0) & (gain > 0), 100.0)
    return result.mask((gain == 0) & (loss > 0), 0.0)


def legacy_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Pre-2026-09-16 atr(): the same wrong seed, on True Range."""
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - df["close"].shift(1)).abs(),
            (df["low"] - df["close"].shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def legacy_bollinger_upper(df: pd.DataFrame, period: int = 20, std: float = 2.0) -> pd.Series:
    """Pre-2026-09-16 bollinger_bands(): pandas' default ddof=1 sample deviation."""
    mid = df["close"].rolling(period).mean()
    return mid + std * df["close"].rolling(period).std()


def _worst(got: pd.Series, expected: pd.Series) -> float:
    got = pd.Series(got).reset_index(drop=True)
    published = expected.notna()
    return float((got[published] - expected[published]).abs().max())


def _cell(series: pd.Series, i: int) -> str:
    value = series.iloc[i]
    return "n/a" if pd.isna(value) else f"{value:.4f}"


def main() -> None:
    """Print the divergence table for both formula generations."""
    rsi_df = _frame(RSI_CLOSE, RSI_CLOSE, RSI_CLOSE)
    atr_df = _frame(ATR_HIGH, ATR_LOW, ATR_CLOSE)
    bb_df = _frame(BB_PRICE, BB_PRICE, BB_PRICE)

    rows = [
        (
            "RSI(14)",
            _worst(legacy_rsi(rsi_df), _published(RSI_EXPECTED)),
            _worst(indicators.rsi(rsi_df), _published(RSI_EXPECTED)),
        ),
        (
            "ATR(14)",
            _worst(legacy_atr(atr_df), _published(ATR_EXPECTED)),
            _worst(indicators.atr(atr_df), _published(ATR_EXPECTED)),
        ),
        (
            "BB upper(20,2)",
            _worst(legacy_bollinger_upper(bb_df), _published(BB_UPPER)),
            _worst(indicators.bollinger_bands(bb_df)["bb_upper"], _published(BB_UPPER)),
        ),
    ]

    print(f"{'indicator':<16}{'legacy worst':>14}{'current worst':>16}")
    for name, legacy, current in rows:
        print(f"{name:<16}{legacy:>14.6f}{current:>16.2e}")

    print()
    print("Bar-by-bar, RSI(14) around the first published value:")
    legacy, current = legacy_rsi(rsi_df), indicators.rsi(rsi_df)
    published = _published(RSI_EXPECTED)
    print(f"{'bar':>5}{'legacy':>10}{'current':>10}{'published':>12}")
    for i in (0, 13, 14, 15, 18, 26, 32):
        cells = [_cell(series, i) for series in (legacy, current, published)]
        print(f"{i + 1:>5}{cells[0]:>10}{cells[1]:>10}{cells[2]:>12}")


if __name__ == "__main__":
    main()
