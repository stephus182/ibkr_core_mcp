from unittest.mock import MagicMock, patch

import pytest
import requests


def _make_response(status_code: int, json_data: dict[str, object] | None = None):
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(response=resp)
    return resp


def test_success_returns_response():
    from ibkr_core_mcp.rate_limiter import with_retry

    mock_fn = MagicMock(return_value=_make_response(200, {"ok": True}))
    result = with_retry(mock_fn)
    assert result.status_code == 200
    assert mock_fn.call_count == 1


def test_429_retries_then_raises():
    from ibkr_core_mcp.exceptions import IBKRRateLimitError
    from ibkr_core_mcp.rate_limiter import with_retry

    mock_fn = MagicMock(return_value=_make_response(429))
    with patch("time.sleep"), pytest.raises(IBKRRateLimitError):
        with_retry(mock_fn, max_retries=2)
    assert mock_fn.call_count == 3  # 1 + 2 retries


def test_429_succeeds_on_retry():
    from ibkr_core_mcp.rate_limiter import with_retry

    responses = [_make_response(429), _make_response(200, {"data": 1})]
    mock_fn = MagicMock(side_effect=responses)
    with patch("time.sleep"):
        result = with_retry(mock_fn, max_retries=2)
    assert result.status_code == 200
    assert mock_fn.call_count == 2


def test_401_raises_auth_error_immediately():
    from ibkr_core_mcp.exceptions import IBKRAuthError
    from ibkr_core_mcp.rate_limiter import with_retry

    mock_fn = MagicMock(return_value=_make_response(401))
    with pytest.raises(IBKRAuthError):
        with_retry(mock_fn)
    assert mock_fn.call_count == 1  # no retries on 401


def test_other_http_error_raises_api_error():
    from ibkr_core_mcp.exceptions import IBKRAPIError
    from ibkr_core_mcp.rate_limiter import with_retry

    mock_fn = MagicMock(return_value=_make_response(500))
    with pytest.raises(IBKRAPIError) as exc_info:
        with_retry(mock_fn)
    assert exc_info.value.status_code == 500


def test_the_429_error_names_the_penalty_box_and_the_per_process_budget():
    """The moment the limit bites is the moment the user learns it exists.

    `EndpointPacer`'s budget is per process and IBKR's limit is per IP (its class docstring),
    so the usual cause of a 429 here is a second script, a test run or the MCP server on the
    same machine. Until 2026-09-19 the exception said "Rate limit exceeded after 3 retries
    (HTTP 429)" and nothing else, and the README said nothing about rate limits at all.
    """
    from ibkr_core_mcp.exceptions import IBKRRateLimitError
    from ibkr_core_mcp.rate_limiter import with_retry

    with patch("time.sleep"), pytest.raises(IBKRRateLimitError) as info:
        with_retry(MagicMock(return_value=_make_response(429)), max_retries=1)
    message = str(info.value)
    assert info.value.status_code == 429
    assert "HTTP 429" in message
    assert "fifteen-minute penalty box" in message
    assert "per process" in message
    # The other in-process cause: the pacer sends a call it cannot pace within 65 s, after warning.
    assert "warn" in message.lower()


def test_the_503_error_does_not_claim_a_penalty_box():
    """A 503 is the gateway being unavailable, not a pacing violation — the two must not be conflated."""
    from ibkr_core_mcp.exceptions import IBKRRateLimitError
    from ibkr_core_mcp.rate_limiter import with_retry

    with patch("time.sleep"), pytest.raises(IBKRRateLimitError) as info:
        with_retry(MagicMock(return_value=_make_response(503)), max_retries=1)
    assert info.value.status_code == 503
    assert "HTTP 503" in str(info.value)
    assert "penalty box" not in str(info.value)


def test_503_retries_then_raises():
    from ibkr_core_mcp.exceptions import IBKRRateLimitError
    from ibkr_core_mcp.rate_limiter import with_retry

    mock_fn = MagicMock(return_value=_make_response(503))
    with patch("time.sleep"), pytest.raises(IBKRRateLimitError):
        with_retry(mock_fn, max_retries=2)
    assert mock_fn.call_count == 3  # initial + 2 retries


def test_503_succeeds_on_retry():
    from ibkr_core_mcp.rate_limiter import with_retry

    responses = [_make_response(503), _make_response(200, {"ok": True})]
    mock_fn = MagicMock(side_effect=responses)
    with patch("time.sleep"):
        result = with_retry(mock_fn, max_retries=2)
    assert result.status_code == 200


def test_backoff_delays_increase_exponentially():
    from ibkr_core_mcp.exceptions import IBKRRateLimitError
    from ibkr_core_mcp.rate_limiter import with_retry

    mock_fn = MagicMock(return_value=_make_response(429))
    sleep_calls = []
    with patch("time.sleep", side_effect=lambda s: sleep_calls.append(s)), pytest.raises(IBKRRateLimitError):
        with_retry(mock_fn, max_retries=3)
    # Each delay should be strictly greater than the previous
    assert len(sleep_calls) == 3
    assert sleep_calls[1] > sleep_calls[0]
    assert sleep_calls[2] > sleep_calls[1]


def test_every_attempt_is_paced_not_only_the_first():
    """A retry is a request too.

    `with_retry` paced once, before its loop, so a 503 retry on a 1-per-5-seconds
    endpoint went out after the 1 s backoff unpaced and the pacer's window never saw
    it — the pacer then believed the next call was free (API-R8, 2026-09-17). Every
    attempt has to pass through `pace`, in order, before it is sent.
    """
    from ibkr_core_mcp import rate_limiter

    events: list[str] = []
    responses = [_make_response(503), _make_response(200, {"ok": True})]

    def send():
        events.append("send")
        return responses.pop(0)

    def fake_pace(path):
        events.append(f"pace {path}")
        return 0.0

    with patch.object(rate_limiter, "pace", side_effect=fake_pace), patch("time.sleep"):
        rate_limiter.with_retry(send, max_retries=2, path="/iserver/account/orders")

    assert events == [
        "pace /iserver/account/orders",
        "send",
        "pace /iserver/account/orders",
        "send",
    ]
