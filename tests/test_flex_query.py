import pytest


def test_config_has_flex_fields(mock_config):
    assert hasattr(mock_config, "flex_token")
    assert hasattr(mock_config, "flex_query_id")


def test_flex_query_error_is_ibkr_core_error():
    from ibkr_core_mcp.exceptions import FlexQueryError, IBKRCoreError
    err = FlexQueryError("failed")
    assert isinstance(err, IBKRCoreError)
    assert str(err) == "failed"


def test_flex_query_error_exported_from_package():
    from ibkr_core_mcp import FlexQueryError
    from ibkr_core_mcp.exceptions import FlexQueryError as _internal
    assert FlexQueryError is _internal


import xml.etree.ElementTree as ET
from unittest.mock import MagicMock, patch
from ibkr_core_mcp.exceptions import FlexQueryError


SEND_REQUEST_XML_SUCCESS = b"""<?xml version="1.0" ?>
<FlexStatementResponse timestamp="20230415;091500">
  <Status>Success</Status>
  <ReferenceCode>9876543210</ReferenceCode>
  <Url>https://gdcdyn.interactivebrokers.com/Universal/servlet/FlexStatementService.GetStatement</Url>
</FlexStatementResponse>"""

SEND_REQUEST_XML_WHEN_AVAILABLE = b"""<?xml version="1.0" ?>
<FlexStatementResponse>
  <Status>WhenAvailable</Status>
  <ReferenceCode>9876543210</ReferenceCode>
  <Url>https://gdcdyn.interactivebrokers.com/Universal/servlet/FlexStatementService.GetStatement</Url>
</FlexStatementResponse>"""

GET_STATEMENT_XML = b"""<?xml version="1.0" ?>
<FlexQueryResponse queryName="Trades" type="AF">
  <FlexStatements count="1">
    <FlexStatement accountId="U1234567" fromDate="20200101" toDate="20230415">
      <Trades>
        <Trade tradeID="111222333" symbol="AAPL" buySell="BUY" quantity="100"
               tradePrice="182.50" dateTime="20230415;091530"
               ibCommission="-1.05" accountId="U1234567" />
        <Trade tradeID="444555666" symbol="MSFT" buySell="SELL" quantity="50"
               tradePrice="310.00" dateTime="20230414;143000"
               ibCommission="-0.85" accountId="U1234567" />
      </Trades>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>"""

GET_STATEMENT_XML_WHEN_AVAILABLE = b"""<?xml version="1.0" ?>
<FlexStatementResponse>
  <Status>WhenAvailable</Status>
</FlexStatementResponse>"""


@pytest.fixture
def flex_client(mock_config):
    from ibkr_core_mcp.flex_query import FlexQueryClient
    mock_config.flex_token = "tok123"
    mock_config.flex_query_id = "123456"
    store = MagicMock()
    cache = MagicMock()
    return FlexQueryClient(mock_config, store, cache)


def test_send_request_returns_reference_code(flex_client):
    with patch("ibkr_core_mcp.flex_query.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = SEND_REQUEST_XML_SUCCESS
        mock_get.return_value = mock_resp
        ref_code, url = flex_client._send_request()
    assert ref_code == "9876543210"
    assert "GetStatement" in url


def test_send_request_raises_on_http_error(flex_client):
    with patch("ibkr_core_mcp.flex_query.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_get.return_value = mock_resp
        with pytest.raises(FlexQueryError, match="HTTP 500"):
            flex_client._send_request()


def test_get_statement_returns_xml_on_success(flex_client):
    with patch("ibkr_core_mcp.flex_query.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = GET_STATEMENT_XML
        mock_get.return_value = mock_resp
        xml_text = flex_client._get_statement(
            "https://example.com/GetStatement", "9876543210"
        )
    assert "<Trade" in xml_text


def test_get_statement_polls_when_available(flex_client):
    responses = [
        MagicMock(status_code=200, content=GET_STATEMENT_XML_WHEN_AVAILABLE),
        MagicMock(status_code=200, content=GET_STATEMENT_XML_WHEN_AVAILABLE),
        MagicMock(status_code=200, content=GET_STATEMENT_XML),
    ]
    with patch("ibkr_core_mcp.flex_query.requests.get", side_effect=responses), \
         patch("ibkr_core_mcp.flex_query.time.sleep"):
        xml_text = flex_client._get_statement(
            "https://example.com/GetStatement", "9876543210"
        )
    assert "<Trade" in xml_text


def test_get_statement_raises_after_max_retries(flex_client):
    always_pending = MagicMock(status_code=200, content=GET_STATEMENT_XML_WHEN_AVAILABLE)
    with patch("ibkr_core_mcp.flex_query.requests.get", return_value=always_pending), \
         patch("ibkr_core_mcp.flex_query.time.sleep"):
        with pytest.raises(FlexQueryError, match="not ready"):
            flex_client._get_statement("https://example.com/GetStatement", "9876543210")


def test_parse_trades_maps_fields_correctly(flex_client):
    trades = flex_client._parse_trades(GET_STATEMENT_XML.decode())
    assert len(trades) == 2
    aapl = next(t for t in trades if t["symbol"] == "AAPL")
    assert aapl["execution_id"] == "111222333"
    assert aapl["side"] == "BUY"
    assert aapl["size"] == 100.0
    assert aapl["price"] == 182.50
    assert aapl["commission"] == 1.05
    assert aapl["account"] == "U1234567"
    assert aapl["time"] == "2023-04-15T09:15:30"


def test_parse_trades_returns_empty_on_no_trades(flex_client):
    xml = b"""<FlexQueryResponse><FlexStatements><FlexStatement><Trades/></FlexStatement></FlexStatements></FlexQueryResponse>"""
    trades = flex_client._parse_trades(xml.decode())
    assert trades == []


def test_fetch_trades_calls_upsert_and_cache(flex_client):
    with patch.object(flex_client, "_send_request", return_value=("REF123", "https://example.com/Get")), \
         patch.object(flex_client, "_get_statement", return_value=GET_STATEMENT_XML.decode()), \
         patch.object(flex_client, "_parse_trades", return_value=[{"execution_id": "1"}]):
        result = flex_client.fetch_trades("U1234567")
    flex_client._store.upsert_trades.assert_called_once_with([{"execution_id": "1"}])
    flex_client._cache.save.assert_called_once()
    assert result == [{"execution_id": "1"}]


def test_fetch_trades_returns_empty_list_on_no_trades(flex_client):
    with patch.object(flex_client, "_send_request", return_value=("REF123", "https://example.com/Get")), \
         patch.object(flex_client, "_get_statement", return_value="<FlexQueryResponse><FlexStatements><FlexStatement><Trades/></FlexStatement></FlexStatements></FlexQueryResponse>"):
        result = flex_client.fetch_trades("U1234567")
    assert result == []
    flex_client._store.upsert_trades.assert_called_once_with([])
