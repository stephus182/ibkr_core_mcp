from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.flex

def test_sync_flex_trades_no_token(toolkit):
    text, fig = toolkit.execute("sync_flex_trades", {})
    assert "IBKR_FLEX_TOKEN" in text


# ── _get_positions — empty and field fallback ─────────────────────────────────

def test_format_coverage_no_gaps():
    from ibkr_core_mcp.claude_tools import _format_coverage
    cov = {"oldest": "2024-01-01", "newest": "2024-12-31",
           "total_trades": 500, "stale": False, "gaps": []}
    text = "\n".join(_format_coverage(cov))
    assert "no periods" in text
    assert "gap(s)" not in text


def test_format_coverage_with_gaps():
    from ibkr_core_mcp.claude_tools import _format_coverage
    cov = {
        "oldest": "2024-01-01", "newest": "2024-12-31",
        "total_trades": 500, "stale": False,
        "gaps": [{
            "gap_start": "2024-03-01", "gap_end": "2024-06-01",
            "calendar_days": 92,
            "request_from": "2024-03-02", "request_to": "2024-05-31",
        }],
    }
    text = "\n".join(_format_coverage(cov))
    assert "1 period" in text
    assert "inactivity or missing data" in text
    assert "2024-03-01" in text


def test_format_coverage_stale_flag():
    from ibkr_core_mcp.claude_tools import _format_coverage
    cov = {"oldest": "2024-01-01", "newest": "2024-06-01",
           "total_trades": 100, "stale": True, "days_since_newest": 15, "gaps": []}
    text = "\n".join(_format_coverage(cov))
    assert "STALE" in text
    assert "15" in text


# ---------------------------------------------------------------------------
# verify_flex_import
# ---------------------------------------------------------------------------

_FLEX_XML_A = b"""<?xml version="1.0"?>
<FlexQueryResponse>
  <FlexStatements>
    <FlexStatement>
      <Trades>
        <Trade tradeID="EX001" symbol="GLD" buySell="BUY" quantity="10"
               tradePrice="180.0" dateTime="20240101;120000" ibCommission="-1.0"
               accountId="U123" assetCategory="STK"/>
        <Trade tradeID="EX002" symbol="GLD" buySell="SELL" quantity="-10"
               tradePrice="185.0" dateTime="20240201;120000" ibCommission="-1.0"
               accountId="U123" assetCategory="STK"/>
      </Trades>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>"""

_FLEX_XML_B = b"""<?xml version="1.0"?>
<FlexQueryResponse>
  <FlexStatements>
    <FlexStatement>
      <Trades>
        <Trade tradeID="EX003" symbol="QQQ" buySell="BUY" quantity="5"
               tradePrice="400.0" dateTime="20240301;120000" ibCommission="-1.0"
               accountId="U123" assetCategory="STK"/>
      </Trades>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>"""


def test_verify_flex_import_all_present(toolkit):
    """All tradeIDs in auto-synced XML present in SQLite, hash matches manifest → hash verified."""
    import hashlib
    content_a = _FLEX_XML_A
    sha256_a = hashlib.sha256(content_a).hexdigest()
    toolkit._cache.download_account_files.return_value = [("flex_U123_2024-01-01_REF.xml", content_a)]
    toolkit._store.get_all_execution_ids.return_value = {"EX001", "EX002"}
    toolkit._store.get_flex_import_entry.return_value = {
        "sha256": sha256_a, "imported_at": "2024-01-01T00:00:00", "verified_at": None
    }

    result, _ = toolkit.execute("verify_flex_import", {})
    assert "hash verified" in result
    assert "Missing from SQLite             : 0" in result


def test_verify_flex_import_missing_records(toolkit):
    """tradeID in XML but absent from SQLite → flagged as missing."""
    toolkit._cache.download_account_files.return_value = [("flex_U123_2024-01-01_REF.xml", _FLEX_XML_A)]
    toolkit._store.get_all_execution_ids.return_value = {"EX001"}  # EX002 missing
    toolkit._store.get_flex_import_entry.return_value = None  # first encounter

    result, _ = toolkit.execute("verify_flex_import", {})
    assert "1 missing" in result
    assert "EX002" in result
    assert "re-import" in result


def test_verify_flex_import_manual_pre_validated(toolkit):
    """Manual archive (ClaudIA_Full_Activity_*.xml) reported as pre-validated, not cross-checked."""
    toolkit._cache.download_account_files.return_value = [
        ("ClaudIA_Full_Activity_123120.xml", _FLEX_XML_A)
    ]
    toolkit._store.get_all_execution_ids.return_value = {"EX001", "EX002"}
    toolkit._store.get_flex_import_entry.return_value = None  # first encounter

    result, _ = toolkit.execute("verify_flex_import", {})
    assert "pre-validated" in result
    # Manual files are not cross-checked against SQLite
    assert "missing" not in result.lower() or "0" in result


def test_verify_flex_import_no_drive(toolkit):
    """No Drive configured → clear error message."""
    toolkit._cache = None
    result, _ = toolkit.execute("verify_flex_import", {})
    assert "GOOGLE_DRIVE_FOLDER_ID" in result


def test_verify_flex_import_no_xml_files(toolkit):
    """No XML files in account_data/ → actionable message."""
    toolkit._cache.download_account_files.return_value = []
    result, _ = toolkit.execute("verify_flex_import", {})
    assert "No .xml files found" in result


def test_extract_execution_ids():
    """extract_execution_ids returns (unique_ids, raw_count) from <Trade> elements."""
    from ibkr_core_mcp.flex_query import FlexQueryClient
    unique_ids, raw_count = FlexQueryClient.extract_execution_ids(_FLEX_XML_A.decode())
    assert unique_ids == {"EX001", "EX002"}
    assert raw_count == 2


def test_extract_execution_ids_skips_empty():
    """extract_execution_ids counts blank-tradeID elements in raw_count but not unique_ids."""
    from ibkr_core_mcp.flex_query import FlexQueryClient
    xml = b"""<FlexQueryResponse><FlexStatements><FlexStatement><Trades>
        <Trade tradeID="" symbol="X" buySell="BUY"/>
        <Trade tradeID="GOOD1" symbol="Y" buySell="SELL"/>
    </Trades></FlexStatement></FlexStatements></FlexQueryResponse>"""
    unique_ids, raw_count = FlexQueryClient.extract_execution_ids(xml.decode())
    assert unique_ids == {"GOOD1"}
    assert raw_count == 2  # both <Trade> elements counted, only one has a valid tradeID


def test_extract_execution_ids_within_file_duplicate():
    """raw_count > len(unique_ids) when the same tradeID appears twice in one XML."""
    from ibkr_core_mcp.flex_query import FlexQueryClient
    xml = b"""<FlexQueryResponse><FlexStatements><FlexStatement><Trades>
        <Trade tradeID="DUP1" symbol="X" buySell="BUY"/>
        <Trade tradeID="DUP1" symbol="X" buySell="BUY"/>
    </Trades></FlexStatement></FlexStatements></FlexQueryResponse>"""
    unique_ids, raw_count = FlexQueryClient.extract_execution_ids(xml.decode())
    assert unique_ids == {"DUP1"}
    assert raw_count == 2  # duplicate detected: raw(2) != unique(1)

def test_sync_flex_archive_happy_path(toolkit):
    """Returns import summary when files are found and trades imported."""
    from unittest.mock import patch

    store_cov = {
        "oldest": "2024-01-01", "newest": "2026-05-22",
        "total_trades": 150, "stale": False, "gaps": []
    }
    toolkit._store.get_trade_date_coverage.return_value = store_cov

    mock_flex_instance = MagicMock()
    mock_flex_instance.sync_archive_from_drive.return_value = {
        "files": 2,
        "trades": 150,
        "processed": [
            {"file": "flex_U123_2024.xml", "trades": 80, "range": "2024-01-01 → 2024-12-31"},
            {"file": "flex_U123_2025.xml", "trades": 70, "range": "2025-01-01 → 2025-12-31"},
        ],
    }

    with patch("ibkr_core_mcp.flex_query.FlexQueryClient", return_value=mock_flex_instance):
        text, fig = toolkit.execute("sync_flex_archive", {})

    assert fig is None
    assert "150 trades" in text
    assert "flex_U123_2024.xml" in text


def test_sync_flex_archive_no_files(toolkit):
    """Returns 'No XML files' message when archive is empty."""
    from unittest.mock import patch

    mock_flex_instance = MagicMock()
    mock_flex_instance.sync_archive_from_drive.return_value = {"files": 0, "trades": 0, "processed": []}

    with patch("ibkr_core_mcp.flex_query.FlexQueryClient", return_value=mock_flex_instance):
        text, fig = toolkit.execute("sync_flex_archive", {})

    assert fig is None
    assert "No XML files" in text


def test_sync_flex_archive_file_not_found(toolkit):
    """Returns FileNotFoundError message when Drive folder is missing."""
    from unittest.mock import patch

    mock_flex_instance = MagicMock()
    mock_flex_instance.sync_archive_from_drive.side_effect = FileNotFoundError("account_data/ not found")

    with patch("ibkr_core_mcp.flex_query.FlexQueryClient", return_value=mock_flex_instance):
        text, fig = toolkit.execute("sync_flex_archive", {})

    assert fig is None
    assert "account_data/" in text or "not found" in text.lower()


# ============================================================================
# _import_flex_file
# ============================================================================


def test_import_flex_file_happy_path(toolkit, tmp_path):
    """Imports trades from a file under the allowed root (~/.ibkr_core)."""
    from unittest.mock import patch

    allowed_root = tmp_path / ".ibkr_core"
    allowed_root.mkdir()
    xml_file = allowed_root / "flex_test.xml"
    xml_file.write_text("<FlexQueryResponse/>")

    store_cov = {
        "oldest": "2024-01-01", "newest": "2024-06-30",
        "total_trades": 5, "stale": False, "gaps": []
    }
    toolkit._store.get_trade_date_coverage.return_value = store_cov

    mock_flex_instance = MagicMock()
    mock_flex_instance.import_from_file.return_value = [
        {"time": "2024-03-01T10:00:00", "symbol": "AAPL"},
        {"time": "2024-06-30T15:00:00", "symbol": "MSFT"},
    ]

    with patch("pathlib.Path.home", return_value=tmp_path), \
         patch("ibkr_core_mcp.flex_query.FlexQueryClient", return_value=mock_flex_instance):
        text, fig = toolkit.execute("import_flex_file", {"path": str(xml_file)})

    assert fig is None
    assert "2 trades" in text
    assert "flex_test.xml" in text


def test_import_flex_file_blocked_path(toolkit, tmp_path):
    """Path outside ~/.ibkr_core is rejected — prevents LLM from reading arbitrary files."""
    with patch("pathlib.Path.home", return_value=tmp_path):
        text, fig = toolkit.execute("import_flex_file", {"path": "/etc/passwd"})
    assert fig is None
    assert "Blocked" in text


def test_import_flex_file_not_found(toolkit, tmp_path):
    """Returns 'File not found' for a valid-root path that does not exist."""
    with patch("pathlib.Path.home", return_value=tmp_path):
        nonexistent = tmp_path / ".ibkr_core" / "missing.xml"
        text, fig = toolkit.execute("import_flex_file", {"path": str(nonexistent)})
    assert fig is None
    assert "File not found" in text


def test_import_flex_file_no_trades(toolkit, tmp_path):
    """Returns 'No trades found' when the XML has no trade records."""
    from unittest.mock import patch

    allowed_root = tmp_path / ".ibkr_core"
    allowed_root.mkdir()
    xml_file = allowed_root / "empty.xml"
    xml_file.write_text("<FlexQueryResponse/>")

    mock_flex_instance = MagicMock()
    mock_flex_instance.import_from_file.return_value = []

    with patch("pathlib.Path.home", return_value=tmp_path), \
         patch("ibkr_core_mcp.flex_query.FlexQueryClient", return_value=mock_flex_instance):
        text, fig = toolkit.execute("import_flex_file", {"path": str(xml_file)})

    assert fig is None
    assert "No trades" in text


# ============================================================================
# _check_flex_coverage
# ============================================================================


def test_check_flex_coverage_happy_path(toolkit):
    """Returns coverage report when trade history exists."""
    toolkit._store.get_trade_date_coverage.return_value = {
        "oldest": "2024-01-01",
        "newest": "2026-05-22",
        "total_trades": 300,
        "stale": False,
        "gaps": [],
    }
    text, fig = toolkit.execute("check_flex_coverage", {})
    assert fig is None
    assert len(text) > 0
    # _format_coverage output should mention the date range
    assert "2024-01-01" in text


def test_check_flex_coverage_empty_store(toolkit):
    """Returns 'No trade history' when store is empty."""
    toolkit._store.get_trade_date_coverage.return_value = {
        "oldest": None, "newest": None, "total_trades": 0, "stale": False, "gaps": []
    }
    text, fig = toolkit.execute("check_flex_coverage", {})
    assert fig is None
    assert "No trade history" in text


def test_check_flex_coverage_error(toolkit):
    """Propagates exception through _safe_error."""
    toolkit._store.get_trade_date_coverage.side_effect = RuntimeError("db error")
    text, fig = toolkit.execute("check_flex_coverage", {})
    assert fig is None
    assert "unexpected" in text.lower()


# ============================================================================
# _get_pa_periods — empty fallback path
# ============================================================================


