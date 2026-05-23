import pytest
import requests
from unittest.mock import MagicMock, patch


def _make_response(status_code: int, json_data: dict | None = None):
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
    from ibkr_core_mcp.rate_limiter import with_retry
    from ibkr_core_mcp.exceptions import IBKRRateLimitError
    mock_fn = MagicMock(return_value=_make_response(429))
    with patch("time.sleep"):
        with pytest.raises(IBKRRateLimitError):
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
    from ibkr_core_mcp.rate_limiter import with_retry
    from ibkr_core_mcp.exceptions import IBKRAuthError
    mock_fn = MagicMock(return_value=_make_response(401))
    with pytest.raises(IBKRAuthError):
        with_retry(mock_fn)
    assert mock_fn.call_count == 1  # no retries on 401


def test_other_http_error_raises_api_error():
    from ibkr_core_mcp.rate_limiter import with_retry
    from ibkr_core_mcp.exceptions import IBKRAPIError
    mock_fn = MagicMock(return_value=_make_response(500))
    with pytest.raises(IBKRAPIError) as exc_info:
        with_retry(mock_fn)
    assert exc_info.value.status_code == 500
