import re
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Success/failure assertions for ClaudeToolkit.execute()
# ---------------------------------------------------------------------------
# `execute()` wraps every handler in `try/except Exception: return _safe_error(...)`
# and returns `(str, fig)`. It therefore ALWAYS returns a non-empty string with
# `fig is None`, whatever happens. That makes the suite's long-standing
# `assert len(text) > 0` and `assert fig is None` tautologies: a handler that raised
# on every input would pass them for all 44 tools. Four tests had no other assertion
# at all.
#
# These matchers key off the *shapes* `_safe_error` and `execute` produce rather than
# copies of their strings, and tests/claude_tools/test_assert_helpers.py drives the
# real `_safe_error` with a real instance of every exception type it branches on. If
# someone rewords a branch there, that meta-test fails — rather than this matcher
# silently ceasing to match and turning every caller green again.
_SAFE_ERROR_RE = re.compile(r"^Tool '.+?' (?:failed:|encountered an unexpected error)")
_UNKNOWN_TOOL_RE = re.compile(r"^Unknown tool: ")
# `_run_backtest` deliberately bypasses _safe_error for sandbox errors, returning the
# detail un-redacted so the model can correct code it wrote itself. That is a second
# error channel, and without this pattern `assert_tool_succeeded` would pass on a
# strategy that failed to compile. Driven by the real handler in
# test_assert_helpers.py::test_rejects_the_backtest_sandbox_error_channel, so a
# reworded prefix fails there rather than silently disarming this.
_BACKTEST_ERROR_RE = re.compile(r"^Backtest failed: ")


def _tool_error_reason(text: str) -> str | None:
    """Return why `text` is a failure result, or None if it looks like real output."""
    if not text:
        return "empty string"
    if _SAFE_ERROR_RE.match(text):
        return "_safe_error output"
    if _UNKNOWN_TOOL_RE.match(text):
        return "unregistered tool name"
    if _BACKTEST_ERROR_RE.match(text):
        return "backtest sandbox error"
    return None


def assert_tool_succeeded(text: str) -> None:
    """Fail unless `text` is genuine tool output rather than a swallowed error.

    Use instead of `assert len(text) > 0`, which cannot fail. Note this asserts the
    tool did not *error* — it says nothing about the content being correct, so keep
    the specific assertions alongside it.

    Args:
        text: The first element of `ClaudeToolkit.execute()`'s return tuple.

    Raises:
        AssertionError: If `text` is empty, a `_safe_error` string, or the
            `Unknown tool:` string returned for an unregistered name.
    """
    reason = _tool_error_reason(text)
    if reason is not None:
        raise AssertionError(f"tool did not succeed ({reason}): {text[:300]!r}")


def assert_tool_failed(text: str, containing: str | None = None) -> None:
    """Fail unless `text` is an error result — the counterpart for error-path tests.

    Args:
        text: The first element of `ClaudeToolkit.execute()`'s return tuple.
        containing: Optional substring the error must mention, so a test for one
            failure mode does not pass on a different one.

    Raises:
        AssertionError: If `text` looks like successful output, or if `containing`
            is given and absent.
    """
    if _tool_error_reason(text) is None:
        raise AssertionError(f"expected a tool error, got real output: {text[:300]!r}")
    if containing is not None and containing not in text:
        raise AssertionError(f"expected error mentioning {containing!r}, got: {text[:300]!r}")


@pytest.fixture
def toolkit(mock_config):
    from ibkr_core_mcp.claude_tools import ClaudeToolkit

    client = MagicMock()
    # A single unambiguous US listing — the shape /trsrv/stocks returns for an ordinary
    # ticker. Set here rather than in each test because most tests that resolve a symbol
    # are not *about* resolution (preview_order, pa_transactions, alerts); a bare
    # MagicMock would make them fail on the resolver's structure instead of on their own
    # subject. Tests that ARE about resolution override it.
    client.get_stocks.return_value = [
        {
            "name": "TEST CO",
            "assetClass": "STK",
            "contracts": [{"conid": 265598, "exchange": "NASDAQ", "isUS": True}],
        }
    ]
    # Currency is read once per resolved conid; keep it a real string so output
    # assertions see "USD" rather than a MagicMock repr.
    client.get_secdef_info.return_value = [{"conid": 265598, "currency": "USD"}]
    cache = MagicMock()
    store = MagicMock()
    return ClaudeToolkit(client, cache, store, mock_config)
