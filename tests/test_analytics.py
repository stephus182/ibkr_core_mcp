import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def flat_returns():
    """Daily returns of exactly 0% — all metrics should be 0."""
    return pd.Series([0.0] * 252)


@pytest.fixture
def positive_returns():
    """Steady +0.1% per day — Sharpe should be high, max_drawdown ~0."""
    np.random.seed(1)
    base = 0.001
    noise = np.random.randn(252) * 0.005
    return pd.Series(base + noise)


@pytest.fixture
def crash_returns():
    """+1% for 100 days, -50% one day, then +0.5% for 151 days."""
    r = [0.01] * 100 + [-0.50] + [0.005] * 151
    return pd.Series(r)


def test_sharpe_flat_is_zero(flat_returns):
    from ibkr_core_mcp.analytics import sharpe
    assert sharpe(flat_returns) == 0.0


def test_sharpe_positive_returns_gt_zero(positive_returns):
    from ibkr_core_mcp.analytics import sharpe
    assert sharpe(positive_returns) > 0


def test_sortino_positive_gt_sharpe(positive_returns):
    from ibkr_core_mcp.analytics import sharpe, sortino
    # Sortino ignores upside deviation so should be >= Sharpe for positive returns
    assert sortino(positive_returns) >= sharpe(positive_returns)


def test_max_drawdown_negative(crash_returns):
    from ibkr_core_mcp.analytics import max_drawdown
    mdd = max_drawdown(crash_returns)
    assert mdd < 0
    assert mdd <= -0.40  # at least 40% drawdown


def test_max_drawdown_flat_is_zero(flat_returns):
    from ibkr_core_mcp.analytics import max_drawdown
    assert max_drawdown(flat_returns) == 0.0


def test_max_drawdown_duration_after_crash(crash_returns):
    from ibkr_core_mcp.analytics import max_drawdown_duration
    dur = max_drawdown_duration(crash_returns)
    assert dur >= 100  # recovery takes at least 100 bars


def test_cagr_positive_returns_positive(positive_returns):
    from ibkr_core_mcp.analytics import cagr
    assert cagr(positive_returns) > 0


def test_calmar_positive(positive_returns):
    from ibkr_core_mcp.analytics import calmar
    result = calmar(positive_returns)
    # May be 0 if no drawdown, but should not be negative
    assert result >= 0


def test_win_rate_empty():
    from ibkr_core_mcp.analytics import win_rate
    assert win_rate([]) == 0.0


def test_win_rate_all_winning():
    from ibkr_core_mcp.analytics import win_rate
    trades = [{"pnl": 100.0}, {"pnl": 50.0}, {"pnl": 25.0}]
    assert win_rate(trades) == 1.0


def test_win_rate_mixed():
    from ibkr_core_mcp.analytics import win_rate
    trades = [{"pnl": 100.0}, {"pnl": -50.0}]
    assert win_rate(trades) == 0.5


def test_profit_factor_no_losses():
    from ibkr_core_mcp.analytics import profit_factor
    trades = [{"pnl": 100.0}, {"pnl": 50.0}]
    pf = profit_factor(trades)
    assert pf == float("inf")


def test_profit_factor_equal_wins_losses():
    from ibkr_core_mcp.analytics import profit_factor
    trades = [{"pnl": 100.0}, {"pnl": -100.0}]
    assert profit_factor(trades) == 1.0


def test_full_report_keys(positive_returns):
    from ibkr_core_mcp.analytics import full_report
    report = full_report(positive_returns)
    for key in ["total_return", "cagr", "sharpe", "sortino", "calmar", "max_drawdown", "max_drawdown_duration", "num_bars"]:
        assert key in report


def test_full_report_with_trades(positive_returns):
    from ibkr_core_mcp.analytics import full_report
    trades = [{"pnl": 200.0}, {"pnl": -50.0}, {"pnl": 75.0}]
    report = full_report(positive_returns, trades=trades)
    assert "win_rate" in report
    assert "profit_factor" in report
