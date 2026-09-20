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


def test_rate_limit_text_on_a_429_names_the_penalty_box_and_the_per_process_scope():
    """The advice was "Retry in a few seconds" until 2026-09-19 — against IBKR's documented
    fifteen-minute penalty box on the IP, and with the usual cause (another process on the same
    machine; pacing is per process, the limit per IP) unmentioned. The model relays this text."""
    msg = _safe_error("some_tool", IBKRRateLimitError("429", status_code=429))
    assert "penalty box" in msg
    assert "per process" in msg
    assert "few seconds" not in msg


def test_rate_limit_text_on_a_503_does_not_claim_a_penalty_box():
    """`with_retry` raises the same class on 503 — the gateway being unavailable, not a pacing
    verdict. Telling the model the IP is in a penalty box would send the user hunting for a second
    process and waiting fifteen minutes for a gateway that was merely down (review, 2026-09-19)."""
    msg = _safe_error("some_tool", IBKRRateLimitError("503", status_code=503))
    assert "503" in msg
    assert "penalty box" not in msg


def test_rate_limit_text_with_an_unknown_status_claims_neither():
    msg = _safe_error("some_tool", IBKRRateLimitError("429"))
    assert "rate limit" in msg.lower()
    assert "penalty box" not in msg
