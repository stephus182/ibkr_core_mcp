from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.flex


def test_sync_flex_trades_no_token(toolkit):
    text, _fig = toolkit.execute("sync_flex_trades", {})
    assert "IBKR_FLEX_TOKEN" in text


# ── _get_positions — empty and field fallback ─────────────────────────────────


def test_format_coverage_no_gaps():
    from ibkr_core_mcp.claude_tools import _format_coverage

    cov = {"oldest": "2024-01-01", "newest": "2024-12-31", "total_trades": 500, "stale": False, "gaps": []}
    text = "\n".join(_format_coverage(cov))
    assert "no periods" in text
    assert "gap(s)" not in text


def test_format_coverage_with_gaps():
    from ibkr_core_mcp.claude_tools import _format_coverage

    cov = {
        "oldest": "2024-01-01",
        "newest": "2024-12-31",
        "total_trades": 500,
        "stale": False,
        "gaps": [
            {
                "gap_start": "2024-03-01",
                "gap_end": "2024-06-01",
                "calendar_days": 92,
                "request_from": "2024-03-02",
                "request_to": "2024-05-31",
            }
        ],
    }
    text = "\n".join(_format_coverage(cov))
    assert "1 period" in text
    assert "inactivity or missing data" in text
    assert "2024-03-01" in text


def test_format_coverage_stale_flag():
    from ibkr_core_mcp.claude_tools import _format_coverage

    cov = {
        "oldest": "2024-01-01",
        "newest": "2024-06-01",
        "total_trades": 100,
        "stale": True,
        "statement_through": "2024-05-30",
        "newest_statement_day": "2024-06-14",
        "gaps": [],
    }
    text = "\n".join(_format_coverage(cov))
    assert "STALE" in text
    assert "statement through 2024-05-30" in text
    assert "the newest that can exist is through 2024-06-14" in text


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


def _archived_statement(*trade_ids: int) -> bytes:
    """An archived XML statement holding `trade_ids`, built by the real fixture builders."""
    from tests.flex_fixtures import statement, trade

    rows = "".join(
        trade(tradeID=str(t), transactionID=str(t + 100), ibExecID=f"0000cccc.{t:08d}.01.01") for t in trade_ids
    )
    return statement(rows).encode()


def _seed_dataset(toolkit, *trade_ids: int) -> None:
    """Store a statement holding `trade_ids` in the toolkit's own (temporary) Flex dataset."""
    from tests.flex_fixtures import seed_flex_dataset

    seed_flex_dataset(toolkit._config, _archived_statement(*trade_ids).decode())


def test_verify_flex_import_all_present(toolkit):
    """All tradeIDs in auto-synced XML are in the Flex dataset, hash matches manifest → hash verified."""
    import hashlib

    content_a = _archived_statement(9000001, 9000002)
    sha256_a = hashlib.sha256(content_a).hexdigest()
    _seed_dataset(toolkit, 9000001, 9000002)
    toolkit._cache.download_account_files.return_value = [("flex_U123_2024-01-01_REF.xml", content_a)]
    toolkit._store.get_flex_import_entry.return_value = {
        "sha256": sha256_a,
        "imported_at": "2024-01-01T00:00:00",
        "verified_at": None,
    }

    result, _ = toolkit.execute("verify_flex_import", {})
    assert "hash verified" in result
    assert "Missing from SQLite             : 0" in result


def test_verify_flex_import_missing_records(toolkit):
    """tradeID in XML but absent from the Flex dataset → flagged as missing."""
    _seed_dataset(toolkit, 9000001)  # 9000002 missing
    toolkit._cache.download_account_files.return_value = [
        ("flex_U123_2024-01-01_REF.xml", _archived_statement(9000001, 9000002))
    ]
    toolkit._store.get_flex_import_entry.return_value = None  # first encounter

    result, _ = toolkit.execute("verify_flex_import", {})
    assert "1 missing" in result
    assert "9000002" in result
    assert "re-import" in result


def test_verify_flex_import_checks_the_flex_dataset_not_the_legacy_table(toolkit):
    """Register F20: a statement the complete-capture write refused (schema drift) still
    reached the legacy `trades` table, so a check against that table verified an import the
    dataset every reader uses does not hold. The legacy answer is never asked for now."""
    toolkit._store.get_all_execution_ids.return_value = {"9000001", "9000002"}  # the legacy table's word
    toolkit._cache.download_account_files.return_value = [
        ("flex_U123_2024-01-01_REF.xml", _archived_statement(9000001, 9000002))
    ]
    toolkit._store.get_flex_import_entry.return_value = None

    result, _ = toolkit.execute("verify_flex_import", {})

    assert "2 missing" in result, "the dataset holds neither statement row"
    toolkit._store.get_all_execution_ids.assert_not_called()
    assert "0 tradeIDs in the Flex dataset" in result


def test_verify_flex_import_manual_pre_validated(toolkit):
    """Manual archive (ClaudIA_Full_Activity_*.xml) reported as pre-validated, not cross-checked."""
    toolkit._cache.download_account_files.return_value = [("ClaudIA_Full_Activity_123120.xml", _FLEX_XML_A)]
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

    store_cov = {"oldest": "2024-01-01", "newest": "2026-05-22", "total_trades": 150, "stale": False, "gaps": []}
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

    store_cov = {"oldest": "2024-01-01", "newest": "2024-06-30", "total_trades": 5, "stale": False, "gaps": []}
    toolkit._store.get_trade_date_coverage.return_value = store_cov

    mock_flex_instance = MagicMock()
    mock_flex_instance.import_from_file.return_value = [
        {"time": "2024-03-01T10:00:00", "symbol": "AAPL"},
        {"time": "2024-06-30T15:00:00", "symbol": "MSFT"},
    ]

    with (
        patch("pathlib.Path.home", return_value=tmp_path),
        patch("ibkr_core_mcp.flex_query.FlexQueryClient", return_value=mock_flex_instance),
    ):
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


def test_import_flex_file_blocks_sibling_prefixed_path(toolkit, tmp_path):
    """A prefix-string check (not a path-boundary check) incorrectly admits any
    directory whose name is a superstring of '.ibkr_core', e.g. '.ibkr_core_evil'.
    See docs/audits/security-audit-2026-07-11.md M-2."""
    sibling = tmp_path / ".ibkr_core_evil"
    sibling.mkdir()
    xml_file = sibling / "archive.xml"
    xml_file.write_text("<FlexQueryResponse/>")

    with patch("pathlib.Path.home", return_value=tmp_path):
        text, fig = toolkit.execute("import_flex_file", {"path": str(xml_file)})
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

    with (
        patch("pathlib.Path.home", return_value=tmp_path),
        patch("ibkr_core_mcp.flex_query.FlexQueryClient", return_value=mock_flex_instance),
    ):
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
        "oldest": None,
        "newest": None,
        "total_trades": 0,
        "stale": False,
        "gaps": [],
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


# ── the archive refusal must reach the user, not just the log ───────────────────


def test_sync_flex_trades_warns_that_the_archive_did_not_update(toolkit, monkeypatch):
    """A schema-drift refusal used to be invisible above the logging layer."""
    from ibkr_core_mcp import claude_tools as ct
    from ibkr_core_mcp.flex_query import FlexArchiveResult

    class FakeFlex:
        def __init__(self, *a, **k):
            self.last_archive_result = FlexArchiveResult(
                ok=False,
                src_file="s.xml",
                kind="schema-drift",
                reason="<Trade> has attribute(s) the schema does not know: ['brandNewIBKRField']",
            )
            self.last_backup_result = None

        def fetch_trades(self, account_id):
            return [{"time": "2026-08-10T09:30:00"}]

    monkeypatch.setattr(ct, "FlexQueryClient", FakeFlex, raising=False)
    monkeypatch.setattr("ibkr_core_mcp.flex_query.FlexQueryClient", FakeFlex)
    toolkit._config.flex_token = "tok"
    toolkit._config.flex_query_id = "123"
    monkeypatch.setattr(toolkit, "_first_account_id", lambda: ("U0000000", None))
    monkeypatch.setattr(
        toolkit._store,
        "get_trade_date_coverage",
        lambda **kw: {
            "oldest": "2024-01-01",
            "newest": "2026-08-10",
            "days_since_newest": 0,
            "settled_newest": None,
            "days_since_settled": None,
            "flex_dataset_empty": False,
            "stale": False,
            "total_trades": 1,
            "gaps": [],
        },
    )

    text, fig = toolkit._sync_flex_trades({"account_id": "U0000000"})

    assert "Flex archive NOT updated" in text
    assert "brandNewIBKRField" in text
    assert "legacy trades table DID update" in text
    assert "1 trades fetched" in text, "the successful part of the sync must still report"
    assert fig is None


def test_stale_message_names_the_statement_held_and_the_newest_that_can_exist():
    """'DATA STALE (0d old)' was self-contradictory: the 0d came from a different table. Since
    F19 the note carries the verdict's own evidence — the statement's `toDate` against the
    weekday before today — in the words claudia_ui's startup line uses."""
    from ibkr_core_mcp.claude_tools import _format_coverage

    lines = _format_coverage(
        {
            "oldest": "2024-01-01",
            "newest": "2026-09-24",
            "days_since_newest": 0,
            "settled_newest": "2026-09-22",
            "days_since_settled": 2,
            "flex_dataset_empty": False,
            "statement_through": "2026-09-22",
            "newest_statement_day": "2026-09-23",
            "stale": True,
            "total_trades": 10,
            "gaps": [],
        }
    )

    assert "statement through 2026-09-22; the newest that can exist is through 2026-09-23" in lines[0]
    assert "(0d old)" not in lines[0]
    assert "settled through" not in lines[0]


def test_stale_message_says_when_no_statement_is_held_at_all():
    from ibkr_core_mcp.claude_tools import _format_coverage

    lines = _format_coverage(
        {
            "oldest": "2024-01-01",
            "newest": "2026-09-24",
            "statement_through": None,
            "newest_statement_day": "2026-09-23",
            "stale": True,
            "total_trades": 10,
            "gaps": [],
        }
    )

    assert "no statement held; the newest that can exist is through 2026-09-23" in lines[0]


def test_empty_flex_dataset_is_reported_as_such():
    from ibkr_core_mcp.claude_tools import _format_coverage

    lines = _format_coverage(
        {
            "oldest": "2024-01-01",
            "newest": "2026-08-10",
            "days_since_newest": 0,
            "settled_newest": None,
            "days_since_settled": None,
            "flex_dataset_empty": True,
            "stale": True,
            "total_trades": 10,
            "gaps": [],
        }
    )

    assert "FLEX DATASET EMPTY" in lines[0]


# ── what a pull reports about the Drive backup and the dataset's soundness (2.2.0) ──


def _sync_with(toolkit, monkeypatch, backup, archive=None):
    """Run `_sync_flex_trades` against a fake Flex client whose pull left `backup` behind,
    and `archive` as what became of the statement in the `flex_*` tables."""
    from ibkr_core_mcp import claude_tools as ct

    class FakeFlex:
        def __init__(self, *a, **k):
            self.last_archive_result = archive
            self.last_backup_result = backup

        def fetch_trades(self, account_id):
            return [{"time": "2026-08-10T09:30:00"}]

    monkeypatch.setattr(ct, "FlexQueryClient", FakeFlex, raising=False)
    monkeypatch.setattr("ibkr_core_mcp.flex_query.FlexQueryClient", FakeFlex)
    toolkit._config.flex_token = "tok"
    toolkit._config.flex_query_id = "123"
    monkeypatch.setattr(
        toolkit._store,
        "get_trade_date_coverage",
        lambda **kw: {"oldest": "2024-01-01", "newest": "2026-08-10", "stale": False, "total_trades": 1, "gaps": []},
    )
    text, _ = toolkit._sync_flex_trades({"account_id": "U0000000"})
    return text


def test_sync_flex_trades_says_nothing_about_a_backup_nobody_configured(toolkit, monkeypatch):
    from ibkr_core_mcp.flex_query import FlexBackupResult

    text = _sync_with(toolkit, monkeypatch, FlexBackupResult("not-configured"))

    assert "store.db" not in text
    assert toolkit._store.log_entry.call_args.kwargs["backup"] == "not-configured"


@pytest.mark.parametrize(
    ("status", "reason", "expected"),
    [
        ("uploaded", None, "store.db backed up to Drive account_data/."),
        ("unchanged", None, "store.db unchanged by this pull — Drive backup left as is."),
        ("failed", "RuntimeError: drive is down", "⚠ store.db Drive backup failed: RuntimeError: drive is down"),
    ],
)
def test_sync_flex_trades_says_what_became_of_the_drive_backup(toolkit, monkeypatch, status, reason, expected):
    from ibkr_core_mcp.flex_query import FlexBackupResult

    text = _sync_with(toolkit, monkeypatch, FlexBackupResult(status, reason))

    assert expected in text.splitlines()
    assert toolkit._store.log_entry.call_args.kwargs["backup"] == status


def test_sync_flex_trades_reports_a_dataset_that_fails_validation(toolkit, monkeypatch):
    """The toolkit fixture's store file does not exist, which is an unreadable dataset —
    a failure, said in the tool's own result so every caller of the pull hears it."""
    text = _sync_with(toolkit, monkeypatch, None)

    assert "⚠ Trade dataset failed validation after the sync — dataset unreadable:" in text
    assert "unverified until this is resolved" in text
    assert toolkit._store.log_entry.call_args.kwargs["valid"] is False


def test_sync_flex_trades_says_nothing_about_a_sound_dataset(toolkit, monkeypatch):
    from tests.flex_fixtures import annual_statement, seed_flex_dataset

    seed_flex_dataset(toolkit._config, annual_statement(2025, trade_ids=(1, 2), pnl_per_trade=-5.0))

    text = _sync_with(toolkit, monkeypatch, None)

    assert "failed validation" not in text
    assert toolkit._store.log_entry.call_args.kwargs["valid"] is True


def test_what_the_pull_tool_records_is_what_last_pull_reads_back(toolkit, monkeypatch):
    """The writer and the reader, joined: the row `sync_flex_trades` writes with the real
    store is the outcome `flex_sync.last_pull` returns — every field, so a renamed key on
    either side is a red test, not a consumer silently reading "unknown"."""
    from ibkr_core_mcp.flex_query import FlexArchiveResult, FlexBackupResult
    from ibkr_core_mcp.flex_sync import last_pull
    from ibkr_core_mcp.store import SQLiteStore
    from tests.flex_fixtures import annual_statement, seed_flex_dataset

    seed_flex_dataset(toolkit._config, annual_statement(2025, trade_ids=(1, 2), pnl_per_trade=-5.0))
    toolkit._store = SQLiteStore(toolkit._config)

    _sync_with(
        toolkit,
        monkeypatch,
        FlexBackupResult("failed", "RuntimeError: drive is down"),
        archive=FlexArchiveResult(
            ok=False, src_file="flex.xml", kind="schema-drift", reason="unknown attribute fooBar"
        ),
    )
    outcome = last_pull(toolkit._config.sqlite_path)

    assert outcome is not None
    assert outcome.trades_fetched == 1
    assert (outcome.archive_ok, outcome.archive_reason) == (False, "unknown attribute fooBar")
    assert (outcome.backup, outcome.valid) == ("failed", True)
    assert outcome.problems == ("archive", "backup")
