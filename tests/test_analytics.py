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
    # `assert result >= 0` passed for a calmar() hard-wired to return 0.0. For a series
    # of positive returns the ratio must be strictly positive, and finite — an infinite
    # Calmar (zero drawdown) is a division artefact, not a measured edge.
    import math

    assert result > 0, "a positive-return series must have a positive Calmar"
    assert math.isfinite(result)


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
    import pandas as pd

    from ibkr_core_mcp.analytics import sortino

    all_positive = pd.Series([0.01, 0.02, 0.005, 0.015])
    assert sortino(all_positive) == 0.0


def test_cagr_empty_series_returns_zero():
    """n = 0/252 = 0 → cagr returns 0.0 instead of raising."""
    import pandas as pd

    from ibkr_core_mcp.analytics import cagr

    assert cagr(pd.Series([], dtype=float)) == 0.0


def test_calmar_zero_drawdown_returns_zero():
    """Flat equity (mdd == 0) → calmar returns 0.0, not ZeroDivisionError."""
    import pandas as pd

    from ibkr_core_mcp.analytics import calmar

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


# ---------------------------------------------------------------------------
# periods_for_timeframe — timeframe string → bars per year (annualisation)
# ---------------------------------------------------------------------------


def test_periods_for_timeframe_daily_weekly_monthly():
    from ibkr_core_mcp.analytics import periods_for_timeframe

    assert periods_for_timeframe("1d") == 252
    assert periods_for_timeframe("1D") == 252  # case-insensitive
    assert periods_for_timeframe("1w") == 52
    assert periods_for_timeframe("1m") == 12  # IBKR bar notation: m = month


def test_periods_for_timeframe_intraday_equity_rth():
    from ibkr_core_mcp.analytics import periods_for_timeframe

    assert periods_for_timeframe("1min") == 98280  # 390 bars/day x 252
    assert periods_for_timeframe("5min") == 19656  # 78 x 252
    assert periods_for_timeframe("15min") == 6552
    assert periods_for_timeframe("30min") == 3276
    assert periods_for_timeframe("1h") == 1638  # 6.5 x 252
    assert periods_for_timeframe("2h") == 819


def test_periods_for_timeframe_unrecognized_returns_none():
    from ibkr_core_mcp.analytics import periods_for_timeframe

    assert periods_for_timeframe("banana") is None
    assert periods_for_timeframe("") is None
    assert periods_for_timeframe("0d") is None


def test_sortino_reproduces_tradingview_official_example():
    """Pin the canonical target-downside-deviation form to TradingView's own
    worked example (support article 43000756110, 'Analysis: Sortino ratio',
    scraped 2026-07-07): monthly returns [0, 0, 3.2, -2.3]%, annual RFR 2% →
    per-period ratio ≈ 0.047. Our sortino annualizes by sqrt(periods), so
    divide that back out to compare."""
    import numpy as np
    import pandas as pd

    from ibkr_core_mcp.analytics import sortino

    returns = pd.Series([0.0, 0.0, 3.2, -2.3])
    per_period = sortino(returns, risk_free=2.0, periods=12) / np.sqrt(12)
    assert abs(per_period - 0.047) < 0.001


def test_sortino_counts_all_observations_in_downside_deviation():
    """The canonical form computes sqrt(mean(min(r − T, 0)²)) over ALL
    observations. The old simplified-discrete form took the sample std of the
    below-target returns only — with a single negative return that std is NaN
    (ddof=1) and it returned 0.0. Canonical must return the real value."""
    import numpy as np
    import pandas as pd

    from ibkr_core_mcp.analytics import sortino

    returns = pd.Series([0.01, 0.0, -0.02, 0.0])
    # TDD = sqrt(0.02² / 4) = 0.01; mean = -0.0025; ratio = -0.25 annualized
    expected = -0.0025 / 0.01 * np.sqrt(252)
    result = sortino(returns, periods=252)
    assert result != 0.0
    assert abs(result - expected) < 1e-9


def test_is_intraday_timeframe_agrees_with_periods_for_timeframe():
    """Both read the same bar-size vocabulary, so they must not disagree about what
    a string means. 'm' is a MONTH in IBKR's notation, not a minute — the one case
    where an outside reader is most likely to get it backwards."""
    from ibkr_core_mcp.analytics import is_intraday_timeframe, periods_for_timeframe

    for tf in ("1min", "5min", "30min", "1h", "4h"):
        assert is_intraday_timeframe(tf), tf
        assert periods_for_timeframe(tf) is not None, tf

    for tf in ("1d", "1w", "1m", "3m"):
        assert not is_intraday_timeframe(tf), tf
        assert periods_for_timeframe(tf) is not None, tf

    for tf in ("banana", "", "0min", "0h"):
        assert not is_intraday_timeframe(tf), tf
        assert periods_for_timeframe(tf) is None, tf


def test_max_drawdown_reproduces_the_investopedia_worked_example():
    """Pins peak SELECTION against a published example, which the current code gets right.

    "Assume an investment portfolio has an initial value of $500,000. The portfolio
    increases to $750,000 ... before plunging to $400,000 ... It then rebounds to
    $600,000, before dropping again to $350,000. Subsequently, it more than doubles to
    $800,000." → MDD = (350,000 − 750,000) / 750,000 = −53.33%, because "the initial peak
    of $750,000 is used ... The interim peak of $600,000 is not used, since it does not
    represent a new high", and the trough taken is $350,000 rather than the first dip to
    $400,000.
    https://www.investopedia.com/terms/m/maximum-drawdown-mdd.asp

    This is the control for the test below: the two differ only in whether the peak is the
    starting capital, so a fix for one must not break the other.
    """
    import itertools

    import pandas as pd

    from ibkr_core_mcp.analytics import max_drawdown

    values = [500_000, 750_000, 400_000, 600_000, 350_000, 800_000]
    returns = pd.Series([b / a - 1 for a, b in itertools.pairwise(values)])

    assert max_drawdown(returns) == pytest.approx(-0.5333, abs=1e-4)


def test_max_drawdown_counts_a_fall_from_the_starting_capital():
    """The equity curve began at the FIRST BAR's value, so the starting capital was never
    a peak and any drawdown beginning on bar 1 was invisible.

    Measured before the fix:

        returns              impl      true
        [-0.50, 0, 0, 0]    0.0000   -0.5000   halved on bar 1, reported as no drawdown
        [-0.50, +1.0, 0, 0] 0.0000   -0.5000   halved then fully recovered
        [-0.10] * 4        -0.2710   -0.3439   understated by 21%

    The first case also reported CAGR −1.0 beside a drawdown of zero, which cannot both be
    true. Drawdown is a RISK measure, and this understates it — the dangerous direction.
    Investopedia's example above is explicit that the series starts at the portfolio's
    initial value.
    """
    import pandas as pd

    from ibkr_core_mcp.analytics import max_drawdown

    halved_then_flat = pd.Series([-0.50, 0.0, 0.0, 0.0])
    assert max_drawdown(halved_then_flat) == pytest.approx(-0.50)

    halved_then_recovered = pd.Series([-0.50, 1.0, 0.0, 0.0])
    assert max_drawdown(halved_then_recovered) == pytest.approx(-0.50)

    steady_decline = pd.Series([-0.10] * 4)
    assert max_drawdown(steady_decline) == pytest.approx(-0.3439, abs=1e-4)


def test_max_drawdown_duration_counts_bars_below_the_starting_capital():
    """Same blind spot in the duration: a strategy under water from its first bar spent
    zero bars in drawdown, because bar 1 was its own peak."""
    import pandas as pd

    from ibkr_core_mcp.analytics import max_drawdown_duration

    assert max_drawdown_duration(pd.Series([-0.50, 0.0, 0.0, 0.0])) == 4
    assert max_drawdown_duration(pd.Series([-0.50, 1.0, 0.0, 0.0])) == 1


def test_calmar_is_not_zero_for_a_strategy_that_only_lost_money():
    """`calmar` returns 0.0 when max drawdown is 0.0, so a strategy that halved on its
    first bar scored the same Calmar as one that never drew down at all — while its CAGR
    said −100%."""
    import pandas as pd

    from ibkr_core_mcp.analytics import calmar

    ruined = pd.Series([-0.50, 0.0, 0.0, 0.0])

    assert calmar(ruined) < 0.0, "a total loss must not score Calmar 0.0"


# ── sharpe, pinned to a value rather than to a sign ────────────────────────────
#
# The 2026-09-16 analytics sweep recorded that "every test for sharpe, max_drawdown, cagr
# and calmar was a shape or sign assertion". It then fixed `max_drawdown` (DATA-25) and
# pinned it to Investopedia's worked example — and left the other three. `cagr` and
# `calmar` turned out to be well covered by the wider suite; `sharpe` was not. Two
# mutations survived the entire 1,461-test run:
#
#   `returns - risk_free`          instead of `returns - risk_free / periods`
#   `excess.std(ddof=0)`           instead of the default sample `ddof=1`
#
# Both are defect classes this same audit had already fixed ELSEWHERE — annualisation
# confusion is DATA-02, and a wrong `ddof` is DATA-21, where the Bollinger band width was
# out by exactly sqrt(20/19). Fixed on one branch, never swept.


def test_sharpe_matches_wikipedias_worked_example():
    """Wikipedia, *Sharpe ratio* § Examples, Example 2: a portfolio with an expected return
    of 12% and a standard deviation of 10%, against a risk-free rate of 5%, has a Sharpe
    ratio of (0.12 - 0.05) / 0.10 = **0.7**.

    Archived at `docs/audits/audit-evidence/scrapes/wiki-sharpe.md`.
    https://en.wikipedia.org/wiki/Sharpe_ratio#Examples

    The series below is constructed to have exactly that mean and that SAMPLE standard
    deviation, and is evaluated with `periods=1` so the figures are already annual and the
    sqrt(periods) factor is 1. That makes the assertion exercise three things a sign test
    cannot: the risk-free rate is non-zero, the standard deviation is the sample one, and
    the excess is taken per period.
    """
    import numpy as np

    from ibkr_core_mcp.analytics import sharpe

    d = 0.10 / np.sqrt(2)  # two points either side of the mean give sample std = d*sqrt(2)
    returns = pd.Series([0.12 - d, 0.12 + d])
    assert returns.mean() == pytest.approx(0.12)
    assert returns.std() == pytest.approx(0.10), "the fixture does not have the example's sigma"

    assert sharpe(returns, risk_free=0.05, periods=1) == pytest.approx(0.7)


def test_sharpe_de_annualises_the_risk_free_rate():
    """`risk_free` is an ANNUAL rate and the returns are per bar, so it must be divided by
    `periods` before it is subtracted. Subtracting it whole is invisible at the default
    `risk_free=0.0` — which is the only value the rest of this file ever passes, and why
    the mutation survived.

    Measured on 252 daily bars at a 4% rate: correct -2.36, un-de-annualised -70.93.
    """
    import numpy as np

    from ibkr_core_mcp.analytics import sharpe

    rng = np.random.default_rng(7)
    daily = pd.Series(rng.normal(0.0005, 0.01, 252))

    got = sharpe(daily, risk_free=0.04, periods=252)
    expected_excess = daily - 0.04 / 252
    expected = float(expected_excess.mean() / expected_excess.std() * np.sqrt(252))

    assert got == pytest.approx(expected)
    assert got == pytest.approx(-2.3623, abs=1e-4), "the measured reference has moved"

    whole_rate = daily - 0.04
    not_expected = float(whole_rate.mean() / whole_rate.std() * np.sqrt(252))
    assert abs(got - not_expected) > 60, "the two spellings are no longer distinguishable"


@pytest.mark.parametrize("n", [10, 30, 252])
def test_sharpe_uses_the_sample_standard_deviation(n):
    """`Series.std()` defaults to `ddof=1`. With `ddof=0` every Sharpe would be inflated by
    exactly sqrt(n/(n-1)) — 5.4% on 10 bars — which is the same signature that identified
    the Bollinger `ddof` defect (DATA-21, sqrt(20/19)). Asserting the ratio rather than a
    single value is what makes the cause unambiguous."""
    import numpy as np

    from ibkr_core_mcp.analytics import sharpe

    rng = np.random.default_rng(11)
    s = pd.Series(rng.normal(0.0005, 0.01, n))

    excess = s - 0.0
    population = float(excess.mean() / excess.std(ddof=0) * np.sqrt(252))
    assert population / sharpe(s, periods=252) == pytest.approx(np.sqrt(n / (n - 1)))


# ── cagr, pinned to a value rather than to a sign ──────────────────────────────
#
# Two mutations survived the whole 1,466-test unit run, and both are annualisation —
# the same defect class as DATA-02 (`run_backtest` annualising intraday Sharpe with
# periods=252) and as `sharpe`'s risk-free rate above:
#
#   `len(returns) / (periods * 2)`   the years denominator          0.5608 vs 0.2493
#   `total ** n`                     the exponent, inverted          6.4149 vs 0.2493
#
# Only "sum instead of compound" was caught. The 2026-09-16 analytics sweep named `cagr`
# as one of the four metrics whose tests were "shape or sign assertions" and then pinned
# only `max_drawdown`.


def test_cagr_matches_investopedias_worked_example():
    """Investopedia, *Compound Annual Growth Rate (CAGR)*: an investment growing from
    10,000 to 19,500 over three years has a CAGR of **24.93%**.
    https://www.investopedia.com/terms/c/cagr.asp

    `(1 + returns).prod()` for the series below is exactly 1.95, i.e. 19,500/10,000, and
    `periods=1` makes the bars annual so `n` is exactly 3 years.
    """
    from ibkr_core_mcp.analytics import cagr

    returns = pd.Series([0.25, 0.25, 0.248])
    assert float((1 + returns).prod()) == pytest.approx(1.95)

    assert cagr(returns, periods=1) == pytest.approx(0.2493, abs=1e-4)


def test_cagr_of_a_constant_annual_return_is_that_return():
    """The structural pin, and the one that makes the cause unambiguous. If every year
    returns exactly x, the compound annual growth rate is exactly x — for any x and any
    number of years. Both surviving mutants break this identity at every point: doubling
    the years denominator gives 0.5608 for x = 0.2493, and inverting the exponent gives
    6.4149.

    A worked example alone would not be enough: it fixes one (total, n) pair, and a defect
    in only one of the two could be absorbed by the other. The identity holds the pair.
    """
    from ibkr_core_mcp.analytics import cagr

    for x in (0.05, 0.2493, 0.40):
        for years in (2, 3, 10):
            assert cagr(pd.Series([x] * years), periods=1) == pytest.approx(x), f"x={x} over {years}y"


def test_cagr_converts_bar_count_to_years_with_periods():
    """`periods` is bars per YEAR, so `len(returns) / periods` is the elapsed years. 504
    daily bars at 0.1% per bar is two years of 0.1%-compounding: (1.001**504)**(1/2) - 1.

    Measured: correct 0.286434; years-denominator mutant 0.654913; exponent mutant 1.738736.
    """
    import numpy as np

    from ibkr_core_mcp.analytics import cagr

    daily = pd.Series(np.full(504, 0.001))
    expected = float((1.001**504) ** (252 / 504) - 1)

    assert cagr(daily, periods=252) == pytest.approx(expected)
    assert cagr(daily, periods=252) == pytest.approx(0.286434, abs=1e-6)


# ── calmar, pinned to a value rather than to a relation ────────────────────────
#
# Both mutations survived the whole unit run, including the crudest one available:
#
#   `cagr(returns, periods) * abs(mdd)`   MULTIPLY instead of divide
#   `max_drawdown(returns) * 2`           halve the ratio
#
# `calmar` is the third of the three metrics the 2026-09-16 analytics sweep named as
# "shape or sign assertions" and did not pin. The whole set is now pinned.


def test_calmar_is_cagr_over_absolute_max_drawdown():
    """Three annual returns of -20%, +50%, +20%, evaluated with `periods=1`.

    Hand-computed: the equity path is 0.80 → 1.20 → 1.44 from a starting 1.0, so the total
    factor is 1.44 and CAGR is 1.44^(1/3) - 1 = 0.1292432. The only fall is the first bar,
    from the starting capital, so max drawdown is exactly -0.20 — which also exercises
    DATA-25, the fix that made the starting capital a peak. Calmar is therefore
    0.1292432 / 0.20 = **0.6462162**.

    Asserting the value and not `calmar > 0` is the point: multiplying by the drawdown
    instead of dividing (0.0258 here) is still positive, still ordered the same way across
    strategies, and survived 1,469 tests.
    """
    from ibkr_core_mcp.analytics import cagr, calmar, max_drawdown

    returns = pd.Series([-0.20, 0.50, 0.20])

    assert cagr(returns, periods=1) == pytest.approx(0.1292432, abs=1e-7)
    assert max_drawdown(returns) == pytest.approx(-0.20)
    assert calmar(returns, periods=1) == pytest.approx(0.6462162, abs=1e-7)

    # the relation itself, so a change to either input is caught at the ratio too
    assert calmar(returns, periods=1) == pytest.approx(cagr(returns, periods=1) / abs(max_drawdown(returns)))


def test_calmar_is_larger_when_the_drawdown_is_smaller():
    """A dividing ratio improves as the denominator shrinks; a multiplying one gets worse.
    This is the direction test the value test cannot express on its own, and it is what
    distinguishes `cagr / |mdd|` from `cagr * |mdd|` structurally rather than numerically."""
    from ibkr_core_mcp.analytics import calmar

    shallow = pd.Series([-0.05, 0.20, 0.10])
    deep = pd.Series([-0.40, 0.20, 0.10])

    assert calmar(shallow, periods=1) > calmar(deep, periods=1)


def test_the_bar_size_grammar_is_written_once():
    """`is_intraday_timeframe` says it shares `periods_for_timeframe`'s parsing "so the two
    cannot drift". Measured 2026-09-17, `analytics.py` held two literal copies of the bar-size
    pattern, one per function (DATA-R7) — the shape by which a fix reaches one copy and not
    the other. The pattern is compiled once, and both read it."""
    import inspect

    from ibkr_core_mcp import analytics

    source = inspect.getsource(analytics)
    grammar = r"(\d+)\s*(min|h|d|w|m)"
    assert source.count(grammar) == 1, f"the bar-size grammar appears {source.count(grammar)} times"
