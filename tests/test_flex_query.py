from unittest.mock import MagicMock, patch

import pytest

from ibkr_core_mcp.exceptions import FlexQueryError

SEND_REQUEST_XML_SUCCESS = b"""<?xml version="1.0" ?>
<FlexStatementResponse timestamp="20230415;091500">
  <Status>Success</Status>
  <ReferenceCode>9876543210</ReferenceCode>
  <Url>https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/GetStatement</Url>
</FlexStatementResponse>"""

SEND_REQUEST_XML_WHEN_AVAILABLE = b"""<?xml version="1.0" ?>
<FlexStatementResponse>
  <Status>WhenAvailable</Status>
  <ReferenceCode>9876543210</ReferenceCode>
  <Url>https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/GetStatement</Url>
</FlexStatementResponse>"""

SEND_REQUEST_XML_NO_URL = b"""<?xml version="1.0" ?>
<FlexStatementResponse>
  <Status>Success</Status>
  <ReferenceCode>9876543210</ReferenceCode>
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


# ---------------------------------------------------------------------------
# Bootstrap — exception and config
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def flex_client(mock_config):
    from ibkr_core_mcp.flex_query import FlexQueryClient
    mock_config.flex_token = "tok123"
    mock_config.flex_query_id = "123456"
    store = MagicMock()
    cache = MagicMock()
    return FlexQueryClient(mock_config, store, cache)


# ---------------------------------------------------------------------------
# _send_request
# ---------------------------------------------------------------------------

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


def test_send_request_raises_when_url_missing(flex_client):
    with patch("ibkr_core_mcp.flex_query.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = SEND_REQUEST_XML_NO_URL
        mock_get.return_value = mock_resp
        with pytest.raises(FlexQueryError, match="statement URL"):
            flex_client._send_request()


# ---------------------------------------------------------------------------
# _get_statement
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# _parse_trades
# ---------------------------------------------------------------------------

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


def test_parse_trades_raises_on_malformed_datetime(flex_client):
    xml = b"""<FlexQueryResponse><FlexStatements><FlexStatement><Trades>
        <Trade tradeID="1" symbol="AAPL" buySell="BUY" quantity="1"
               tradePrice="100" dateTime="BADFORMAT" ibCommission="0" accountId="U1" />
    </Trades></FlexStatement></FlexStatements></FlexQueryResponse>"""
    with pytest.raises(FlexQueryError, match="dateTime format"):
        flex_client._parse_trades(xml.decode())


def test_parse_trades_tolerates_non_numeric_quantity(flex_client):
    xml = """<FlexQueryResponse><FlexStatements><FlexStatement><Trades>
        <Trade tradeID="X1" symbol="AAPL" buySell="BUY" quantity="N/A"
               tradePrice="182.50" dateTime="20230415;091530" ibCommission="-1.05" accountId="U1234567" />
    </Trades></FlexStatement></FlexStatements></FlexQueryResponse>"""
    trades = flex_client._parse_trades(xml)
    assert len(trades) == 1
    assert trades[0]["size"] == 0.0
    assert trades[0]["price"] == 182.50


# ---------------------------------------------------------------------------
# fetch_trades
# ---------------------------------------------------------------------------

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
    flex_client._cache.save.assert_not_called()


# ---------------------------------------------------------------------------
# _send_request — IBKR error codes (regression guard for 1001/1025 incident)
# ---------------------------------------------------------------------------

def _mock_get(content: bytes):
    """Return a requests.get mock that responds with HTTP 200 and given content."""
    resp = MagicMock(status_code=200, content=content)
    return patch("ibkr_core_mcp.flex_query.requests.get", return_value=resp)


_FAIL_1001 = b"""<?xml version="1.0" ?>
<FlexStatementResponse>
  <Status>Fail</Status>
  <ErrorCode>1001</ErrorCode>
  <ErrorMessage>Too many requests</ErrorMessage>
</FlexStatementResponse>"""

_WARN_1025 = b"""<?xml version="1.0" ?>
<FlexStatementResponse>
  <Status>Warn</Status>
  <ErrorCode>1025</ErrorCode>
  <ErrorMessage>Query locked due to too many failed attempts</ErrorMessage>
</FlexStatementResponse>"""

_FAIL_UNKNOWN = b"""<?xml version="1.0" ?>
<FlexStatementResponse>
  <Status>Fail</Status>
  <ErrorCode>9999</ErrorCode>
  <ErrorMessage>Unrecognised condition</ErrorMessage>
</FlexStatementResponse>"""

_WARN_UNKNOWN = b"""<?xml version="1.0" ?>
<FlexStatementResponse>
  <Status>Warn</Status>
  <ErrorCode>8888</ErrorCode>
  <ErrorMessage>Some transient warning</ErrorMessage>
</FlexStatementResponse>"""

_BAD_URL = b"""<?xml version="1.0" ?>
<FlexStatementResponse>
  <Status>Success</Status>
  <ReferenceCode>1234567890</ReferenceCode>
  <Url>https://evil.example.com/steal?t=TOKEN</Url>
</FlexStatementResponse>"""


def test_send_request_error_1001_auth_failure(flex_client):
    """Error 1001 must raise with auth-failure diagnosis, not a raw IBKR error."""
    with _mock_get(_FAIL_1001):
        with pytest.raises(FlexQueryError, match="1001"):
            flex_client._send_request()


def test_send_request_error_1001_message_mentions_retry(flex_client):
    """The 1001 message must say it is transient and suggest a retry."""
    with _mock_get(_FAIL_1001):
        with pytest.raises(FlexQueryError, match="Transient"):
            flex_client._send_request()


def test_send_request_warn_1025_lockout(flex_client):
    """Error 1025 (Warn status) must raise with token regeneration instructions."""
    with _mock_get(_WARN_1025):
        with pytest.raises(FlexQueryError, match="1025"):
            flex_client._send_request()


def test_send_request_warn_1025_mentions_regenerate(flex_client):
    """The 1025 message must tell the user to regenerate the Flex token."""
    with _mock_get(_WARN_1025):
        with pytest.raises(FlexQueryError, match="regenerate"):
            flex_client._send_request()


def test_send_request_fail_unknown_error_code(flex_client):
    """Unknown Fail codes must still raise (not silently succeed)."""
    with _mock_get(_FAIL_UNKNOWN):
        with pytest.raises(FlexQueryError, match="9999"):
            flex_client._send_request()


def test_send_request_warn_unknown_error_code(flex_client):
    """Unknown Warn codes must still raise (not silently succeed)."""
    with _mock_get(_WARN_UNKNOWN):
        with pytest.raises(FlexQueryError, match="8888"):
            flex_client._send_request()


def test_send_request_rejects_non_ibkr_url(flex_client):
    """URL allowlist must reject any URL not on the known IBKR Flex subdomains."""
    with _mock_get(_BAD_URL):
        with pytest.raises(FlexQueryError, match="unexpected URL"):
            flex_client._send_request()


_GDCDYN_URL = b"""<?xml version="1.0" ?>
<FlexStatementResponse>
  <Status>Success</Status>
  <ReferenceCode>1234567890</ReferenceCode>
  <Url>https://gdcdyn.interactivebrokers.com/AccountManagement/FlexWebService/GetStatement</Url>
</FlexStatementResponse>"""


def test_send_request_accepts_gdcdyn_url(flex_client):
    """gdcdyn.interactivebrokers.com must be accepted — IBKR live API returns this subdomain
    for GetStatement even though official docs show ndcdyn.
    Observed 2026-06-26: SendRequest response contained gdcdyn URL, rejected by old allowlist.
    """
    with _mock_get(_GDCDYN_URL):
        ref, url = flex_client._send_request()
    assert "gdcdyn.interactivebrokers.com" in url


def test_send_request_includes_fd_td_when_provided(flex_client):
    """fd and td params are passed to IBKR when start_date / end_date are set.

    Source: https://www.ibkrguides.com/clientportal/performanceandstatements/flex3.htm
    """
    with patch("ibkr_core_mcp.flex_query.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = SEND_REQUEST_XML_SUCCESS
        mock_get.return_value = mock_resp
        flex_client._send_request(start_date="20260101", end_date="20260625")
    call_params = mock_get.call_args.kwargs["params"]
    assert call_params["fd"] == "20260101"
    assert call_params["td"] == "20260625"


def test_send_request_omits_fd_td_when_none(flex_client):
    """fd and td params must NOT be sent when start_date / end_date are None."""
    with patch("ibkr_core_mcp.flex_query.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = SEND_REQUEST_XML_SUCCESS
        mock_get.return_value = mock_resp
        flex_client._send_request()
    call_params = mock_get.call_args.kwargs["params"]
    assert "fd" not in call_params
    assert "td" not in call_params


def test_invalid_date_format_raises(flex_client):
    """fetch_trades must raise ValueError for non-YYYYMMDD date strings."""
    with pytest.raises(ValueError, match="YYYYMMDD"):
        flex_client.fetch_trades("U1234567", start_date="2026-01-01")  # dashes not allowed


# ---------------------------------------------------------------------------
# _parse_trades — 20% integrity guard boundary
# ---------------------------------------------------------------------------

def _flex_xml(valid_count: int, invalid_count: int) -> str:
    """Build Flex XML with valid trades and trades missing tradeID (which are skipped)."""
    valid = "".join(
        f'<Trade tradeID="V{i}" symbol="AAPL" buySell="BUY" quantity="1"'
        f' tradePrice="100" dateTime="20230415;091530" ibCommission="0" accountId="U1" />'
        for i in range(valid_count)
    )
    # Missing tradeID — the required-field check causes these to be skipped
    bad = "".join(
        f'<Trade symbol="BAD{i}" buySell="BUY" quantity="1"'
        f' tradePrice="100" dateTime="20230415;091530" ibCommission="0" accountId="U1" />'
        for i in range(invalid_count)
    )
    return (
        "<FlexQueryResponse><FlexStatements><FlexStatement><Trades>"
        + valid + bad
        + "</Trades></FlexStatement></FlexStatements></FlexQueryResponse>"
    )


def test_parse_trades_integrity_guard_at_threshold_does_not_raise(flex_client):
    """8 valid + 2 invalid = 20% skipped — exactly at the threshold, must NOT raise."""
    xml = _flex_xml(valid_count=8, invalid_count=2)
    trades = flex_client._parse_trades(xml)
    assert len(trades) == 8


def test_parse_trades_integrity_guard_above_threshold_raises(flex_client):
    """7 valid + 3 invalid = 30% skipped — above threshold, must raise FlexQueryError."""
    xml = _flex_xml(valid_count=7, invalid_count=3)
    with pytest.raises(FlexQueryError, match="Data integrity"):
        flex_client._parse_trades(xml)


# ---------------------------------------------------------------------------
# _parse_flex_datetime — date-only path
# ---------------------------------------------------------------------------

def test_parse_flex_datetime_date_only():
    """YYYYMMDD format (no time) must produce T00:00:00 timestamp."""
    from ibkr_core_mcp.flex_query import _parse_flex_datetime
    result = _parse_flex_datetime("20260625")
    assert result == "2026-06-25T00:00:00"


# ---------------------------------------------------------------------------
# _validate_flex_date — end_date path
# ---------------------------------------------------------------------------

def test_invalid_end_date_format_raises(flex_client):
    """fetch_trades must raise ValueError for non-YYYYMMDD end_date strings."""
    with pytest.raises(ValueError, match="YYYYMMDD"):
        flex_client.fetch_trades("U1234567", end_date="2026/06/25")
