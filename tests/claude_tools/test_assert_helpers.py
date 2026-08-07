"""Meta-tests for the assertion helpers in conftest.py.

These exist because the helpers are the instrument the rest of the claude_tools suite
measures with, and an instrument that silently stops detecting is worse than no
instrument at all — it converts every test using it back into a tautology while still
looking rigorous.

`assert_tool_succeeded` recognises failure by matching `_safe_error`'s output shape.
That coupling is deliberate but fragile in one direction: reword a prefix in
`_safe_error` and the matcher stops matching, every caller goes green, and nothing
fails. `test_rejects_every_safe_error_branch` closes that by calling the real
`_safe_error` with a real instance of every exception type it branches on, rather than
asserting against transcribed copies of its strings.
"""

import pytest

from ibkr_core_mcp.claude_tools import _safe_error
from ibkr_core_mcp.exceptions import (
    BacktestError,
    BacktestRuntimeError,
    BacktestSyntaxError,
    CacheError,
    ConfigError,
    FlexQueryError,
    HumanAuthError,
    IBKRAPIError,
    IBKRAuthError,
    IBKRRateLimitError,
    StoreError,
)

from .conftest import assert_tool_failed, assert_tool_succeeded

# One instance per branch in _safe_error, in source order, plus the catch-all.
# A branch added there without a row here means the new error string is unverified.
_EVERY_SAFE_ERROR_INPUT = [
    IBKRAuthError("no session"),
    IBKRRateLimitError("429"),
    IBKRAPIError("bad request", status_code=400),
    CacheError("drive down"),
    BacktestSyntaxError("bad syntax"),
    BacktestRuntimeError("blew up"),
    BacktestError("generic"),
    FlexQueryError("1001"),
    ConfigError("missing key"),
    StoreError("locked"),
    HumanAuthError("cancelled"),
    KeyError("symbol"),
    ValueError("something nobody anticipated"),
]


@pytest.mark.parametrize("exc", _EVERY_SAFE_ERROR_INPUT, ids=lambda e: type(e).__name__)
def test_rejects_every_safe_error_branch(exc):
    """Every string _safe_error can produce must be recognised as a failure.

    Calls the real _safe_error rather than comparing against copied literals, so
    rewording a branch there fails here instead of silently disarming the helper.
    """
    text = _safe_error("some_tool", exc)
    with pytest.raises(AssertionError):
        assert_tool_succeeded(text)
    assert_tool_failed(text)


def test_rejects_the_unknown_tool_string():
    """`execute()` returns this for an unregistered name, bypassing _safe_error entirely.

    Three tests in this suite passed for years against a tool deleted on 2026-07-30
    because their assertions were satisfied by exactly this string.
    """
    text = "Unknown tool: firecrawl_crawl"
    with pytest.raises(AssertionError):
        assert_tool_succeeded(text)
    assert_tool_failed(text)


def test_rejects_the_backtest_sandbox_error_channel(toolkit):
    """`_run_backtest` returns sandbox errors un-redacted, bypassing _safe_error entirely.

    Drives the real handler with code that cannot compile rather than asserting against
    a copied prefix, so rewording that return fails here instead of leaving
    `assert_tool_succeeded` blind to every failed backtest.
    """
    import numpy as np
    import pandas as pd

    n = 40
    toolkit._cache.check.return_value = True
    toolkit._cache.load.return_value = pd.DataFrame(
        {
            "open": np.ones(n),
            "high": np.ones(n),
            "low": np.ones(n),
            "close": np.ones(n),
            "volume": np.ones(n),
        },
        index=pd.date_range("2025-01-01", periods=n, freq="B"),
    )
    text, _ = toolkit.execute(
        "run_backtest",
        {
            "code": "this is not valid python(((",
            "symbol": "AAPL",
            "timeframe": "1D",
            "period": "1Y",
            "end": "2026-05-22",
        },
    )
    with pytest.raises(AssertionError):
        assert_tool_succeeded(text)
    assert_tool_failed(text)


def test_accepts_ordinary_tool_output():
    """The guard against a matcher so broad it rejects everything."""
    assert_tool_succeeded("## Account Summary\n\nNet Liquidation Value: **$100,000.00**")
    assert_tool_succeeded("No open positions.")


def test_accepts_output_that_merely_mentions_failure():
    """Only the _safe_error/unknown-tool *shapes* count, not the word 'failed'.

    A tool that legitimately reports a partial result ("2 of 3 symbols resolved; BADTKR
    failed") is a success. Matching on the bare word would make those tests unfixable.
    """
    assert_tool_succeeded("Resolved 2 of 3 symbols. BADTKR failed to resolve and was skipped.")


def test_empty_output_is_not_a_success():
    """`len(text) > 0` was the tautology this helper replaces; don't reintroduce it inverted."""
    with pytest.raises(AssertionError):
        assert_tool_succeeded("")


def test_assert_tool_failed_rejects_a_successful_result():
    """The counterpart must not be a tautology either."""
    with pytest.raises(AssertionError):
        assert_tool_failed("## Account Summary\n\nNet Liquidation Value: **$100,000.00**")


def test_assert_tool_failed_checks_the_substring_when_given_one():
    text = _safe_error("get_positions", IBKRAuthError("no session"))
    assert_tool_failed(text, containing="not authenticated")
    with pytest.raises(AssertionError):
        assert_tool_failed(text, containing="rate limit")
