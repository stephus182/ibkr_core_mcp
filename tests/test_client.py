import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def client(mock_config):
    from ibkr_core_mcp.client import IBKRClient
    from ibkr_core_mcp.auth import NoAuth
    return IBKRClient(mock_config, auth=NoAuth())


def test_ping_returns_false_on_401(client):
    with patch.object(client._session, "get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_get.return_value = mock_resp
        assert client.ping() is False


def test_ping_returns_true_when_authenticated(client):
    with patch.object(client._session, "get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"authenticated": True}
        mock_get.return_value = mock_resp
        assert client.ping() is True


def test_search_contract_returns_list(client):
    with patch.object(client._session, "get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {"conid": 265598, "symbol": "AAPL", "secType": "STK"}
        ]
        mock_get.return_value = mock_resp
        result = client.search_contract("AAPL")
    assert isinstance(result, list)
    assert result[0]["conid"] == 265598


def test_get_market_history_passes_params(client):
    with patch.object(client._session, "get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": []}
        mock_get.return_value = mock_resp
        client.get_market_history(265598, period="1Y", bar="1d")
    call_kwargs = mock_get.call_args
    assert "conid=265598" in str(call_kwargs) or "265598" in str(call_kwargs)


# Integration tests — require live gateway
@pytest.mark.integration
def test_live_ping(mock_config):
    from ibkr_core_mcp.client import IBKRClient
    from ibkr_core_mcp.auth import BrowserCookieAuth
    client = IBKRClient(mock_config, auth=BrowserCookieAuth())
    assert client.ping() is True


@pytest.mark.integration
def test_live_search_aapl(mock_config):
    from ibkr_core_mcp.client import IBKRClient
    from ibkr_core_mcp.auth import BrowserCookieAuth
    client = IBKRClient(mock_config, auth=BrowserCookieAuth())
    results = client.search_contract("AAPL")
    assert len(results) > 0
    assert any(r.get("symbol") == "AAPL" for r in results)
