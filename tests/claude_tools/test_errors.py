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

pytestmark = pytest.mark.errors


@pytest.mark.parametrize(
    "tool,exc,expected_substrs",
    [
        pytest.param("some_tool", IBKRAuthError("session expired"), ("authenticated",), id="ibkr_auth"),
        pytest.param("some_tool", IBKRRateLimitError("429"), ("rate limit",), id="rate_limit"),
        pytest.param("some_tool", IBKRAPIError("error", status_code=500), ("500",), id="api_error"),
        pytest.param("some_tool", CacheError("drive down"), ("drive", "cache"), id="cache"),
        pytest.param("run_backtest", BacktestSyntaxError("bad indent"), ("syntax",), id="backtest_syntax"),
        pytest.param("run_backtest", BacktestRuntimeError("ZeroDivision"), ("runtime",), id="backtest_runtime"),
        pytest.param("run_backtest", BacktestError("failed"), ("backtest",), id="backtest_generic"),
        pytest.param("sync_flex_trades", FlexQueryError("timeout"), ("flex",), id="flex_query"),
        pytest.param("some_tool", ConfigError("missing key"), ("configuration",), id="config"),
        pytest.param("some_tool", KeyError("symbol"), ("missing", "field"), id="key_error"),
        pytest.param("some_tool", RuntimeError("something odd"), ("unexpected",), id="unexpected"),
        pytest.param("some_tool", StoreError("disk full"), ("store",), id="store_error"),
        pytest.param("place_order", HumanAuthError("Touch ID cancelled"), ("authentication",), id="human_auth"),
    ],
)
def test_safe_error_mapping(tool, exc, expected_substrs):
    msg = _safe_error(tool, exc)
    assert any(substr in msg.lower() for substr in expected_substrs), (
        f"expected one of {expected_substrs!r} in {msg.lower()!r}"
    )
