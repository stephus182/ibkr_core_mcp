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
    assert "total_return" in report
    assert "cagr" in report
    assert "sharpe" in report
    assert "sortino" in report
    assert "calmar" in report
    assert "max_drawdown" in report
    assert "max_drawdown_duration" in report
    assert "num_bars" in report


def test_full_report_with_trades(positive_returns):
    from ibkr_core_mcp.analytics import full_report
    trades = [{"pnl": 200.0}, {"pnl": -50.0}, {"pnl": 75.0}]
    report = full_report(positive_returns, trades=trades)
    assert "win_rate" in report
    assert "profit_factor" in report


# ---------------------------------------------------------------------------
# Edge-case branches (zero / empty inputs)
# ---------------------------------------------------------------------------

def test_sortino_no_negative_returns_is_zero():
    """All-positive returns → downside std is NaN → sortino returns 0.0, not ZeroDivisionError."""
    from ibkr_core_mcp.analytics import sortino
    import pandas as pd
    all_positive = pd.Series([0.01, 0.02, 0.005, 0.015])
    assert sortino(all_positive) == 0.0


def test_cagr_empty_series_returns_zero():
    """n = 0/252 = 0 → cagr returns 0.0 instead of raising."""
    from ibkr_core_mcp.analytics import cagr
    import pandas as pd
    assert cagr(pd.Series([], dtype=float)) == 0.0


def test_calmar_zero_drawdown_returns_zero():
    """Flat equity (mdd == 0) → calmar returns 0.0, not ZeroDivisionError."""
    from ibkr_core_mcp.analytics import calmar
    import pandas as pd
    flat = pd.Series([0.0, 0.0, 0.0, 0.0])
    assert calmar(flat) == 0.0


def test_profit_factor_all_zero_pnl_returns_zero():
    """No wins and no losses (all pnl == 0) → avg_l == 0, avg_w == 0 → returns 0.0, not inf."""
    from ibkr_core_mcp.analytics import profit_factor
    trades = [{"pnl": 0.0}, {"pnl": 0.0}]
    assert profit_factor(trades) == 0.0


def test_avg_win_loss_ratio_with_losses():
    """Normal path: avg_w / avg_l when both sides exist."""
    from ibkr_core_mcp.analytics import avg_win_loss_ratio
    trades = [{"pnl": 200.0}, {"pnl": -100.0}]
    assert avg_win_loss_ratio(trades) == 2.0


def test_avg_win_loss_ratio_all_zero_returns_zero():
    """avg_l == 0 and avg_w == 0 (all pnl zero) → returns 0.0, not inf."""
    from ibkr_core_mcp.analytics import avg_win_loss_ratio
    trades = [{"pnl": 0.0}, {"pnl": 0.0}]
    assert avg_win_loss_ratio(trades) == 0.0


def test_full_report_empty_returns_gracefully():
    """Empty return series must not raise ZeroDivisionError."""
    import pandas as pd
    from ibkr_core_mcp.analytics import full_report
    empty = pd.Series([], dtype=float)
    result = full_report(empty)
    assert result["sharpe"] == 0.0
    assert result["max_drawdown"] == 0.0
    assert result["num_bars"] == 0


def test_sharpe_periods_parameter_affects_result():
    """Different periods values must produce different Sharpe ratios for the same returns."""
    import pandas as pd
    from ibkr_core_mcp.analytics import sharpe
    rng = pd.Series([0.001, -0.002, 0.003, -0.001, 0.002] * 10)
    daily_sharpe = sharpe(rng, periods=252)
    intraday_sharpe = sharpe(rng, periods=252 * 390)
    assert daily_sharpe != intraday_sharpe
