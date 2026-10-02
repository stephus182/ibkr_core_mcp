"""Tests for `ibkr_core_mcp.flex_sync` — the state of the Flex dataset.

Relocated with the module from claudia_ui's `tests/test_flex_sync.py` (2.2.0); every test
below the first section is that file's, unchanged but for the import path, so a changed
answer is a changed behaviour.

Two rules drive the module, both set by the operator on 2026-08-05 after a live session
found the Drive backup silently stale:

1. **A pull that does not refresh the backup is incomplete.** (`FlexQueryClient.fetch_trades`
   now makes that backup itself — `tests/test_flex_query.py`.)
2. **But do not add weight.** Flex is T+1 data — one pull per session is the whole refresh
   budget, and re-uploading 53 MB that did not change is pure cost. So the upload is
   conditional on the data actually moving, which is what `dataset_fingerprint` decides.

The validation exists because a host's opening line always *claimed* "integrity validated"
without anything having checked. These tests pin the claim to real checks.

**The small hand-built tables are deliberate here, and only here.** Two of the four checks
guard states today's writer cannot produce — `execution_key` is the real table's NOT NULL
primary key — so a duplicate or a NULL key can only be shown on a table shaped like the
pre-rebuild store. The last section runs the same functions against a dataset the real
writer built, so the hand-built shape is not the only thing they have ever met.
"""

import sqlite3

import pytest

from ibkr_core_mcp.flex_sync import dataset_fingerprint, validate_dataset

# ── fixtures ──────────────────────────────────────────────────────────────────


def _make_db(path, *, trades=1, lots=True, wash=True) -> None:
    """A miniature but structurally faithful store.db.

    The realised identity below is IBKR's documented behaviour and the one invariant
    CLAUDE.md names outright: Trade == Lot + WashSale.
    """
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE flex_trade (
            execution_key TEXT, source TEXT, fifo_pnl_realized REAL, trade_date_iso TEXT
        );
        CREATE TABLE flex_lot (fifo_pnl_realized REAL);
        CREATE TABLE flex_wash_sale (fifo_pnl_realized REAL);
        CREATE TABLE trades (execution_id TEXT);
        """
    )
    for i in range(trades):
        conn.execute(
            "INSERT INTO flex_trade VALUES (?, 'flex', ?, ?)",
            (f"key-{i}", -100.0, "2026-08-04"),
        )
    if lots:
        conn.executemany("INSERT INTO flex_lot VALUES (?)", [(-250.0,)] * trades)
    if wash:
        conn.executemany("INSERT INTO flex_wash_sale VALUES (?)", [(150.0,)] * trades)
    conn.commit()
    conn.close()


@pytest.fixture
def good_db(tmp_path):
    """Path to a throwaway store holding a sound Flex dataset."""
    path = tmp_path / "store.db"
    _make_db(path)
    return str(path)


# ── validate_dataset ──────────────────────────────────────────────────────────


def test_a_sound_dataset_passes_every_check(good_db):
    """A sound dataset passes, is not flagged empty, and really ran every check."""
    validity = validate_dataset(good_db)
    assert validity.ok is True
    assert validity.empty is False
    assert validity.failures == ()
    assert len(validity.checks) >= 4


def test_duplicate_execution_keys_fail(good_db):
    """The exact defect that produced 75 duplicate rows before the merge fix."""
    conn = sqlite3.connect(good_db)
    conn.execute("INSERT INTO flex_trade VALUES ('key-0', 'flex', -100.0, '2026-08-04')")
    conn.commit()
    conn.close()

    validity = validate_dataset(good_db)
    assert validity.ok is False
    assert any("execution_key" in f.name for f in validity.failures)


def test_null_execution_key_fails(good_db):
    """A NULL execution key fails validation — it is the row's identity."""
    conn = sqlite3.connect(good_db)
    conn.execute("INSERT INTO flex_trade VALUES (NULL, 'flex', -100.0, '2026-08-04')")
    conn.commit()
    conn.close()

    validity = validate_dataset(good_db)
    assert validity.ok is False


def test_realised_identity_breaking_fails(good_db):
    """Trade == Lot + WashSale. Summing flex_lot instead of flex_trade is the trap
    CLAUDE.md warns about; if the relationship breaks, the dataset is not usable for
    the realised windows the dashboard reports."""
    conn = sqlite3.connect(good_db)
    conn.execute("INSERT INTO flex_lot VALUES (-9999.0)")
    conn.commit()
    conn.close()

    validity = validate_dataset(good_db)
    assert validity.ok is False
    assert any("realised" in f.name.lower() for f in validity.failures)


def test_an_empty_dataset_is_not_a_corrupt_one(tmp_path):
    """A fresh install has no trades. That must read as 'nothing to validate', not as
    a failure — otherwise every first run opens with a false integrity alarm."""
    path = tmp_path / "store.db"
    _make_db(path, trades=0, lots=False, wash=False)

    validity = validate_dataset(str(path))
    assert validity.empty is True
    assert validity.ok is True
    assert validity.failures == ()


def test_a_database_without_flex_tables_is_empty_not_broken(tmp_path):
    """No Flex tables means empty, not broken: a fresh install has nothing to validate yet."""
    path = tmp_path / "store.db"
    sqlite3.connect(path).close()

    validity = validate_dataset(str(path))
    assert validity.empty is True
    assert validity.ok is True


def test_a_missing_file_reports_honestly_instead_of_raising(tmp_path):
    """A missing file reports a failure with a reason rather than crashing startup."""
    validity = validate_dataset(str(tmp_path / "nope.db"))
    assert validity.ok is False
    assert validity.failures  # says what happened rather than crashing startup


def test_a_damaged_file_fails_validation(tmp_path):
    """A damaged file must never pass — this is the risk the WAL-safe snapshot upload
    exists to prevent, so the check that would notice it has to be real.

    The dataset is grown past a single page first: a scribble into a small database's
    free space leaves `PRAGMA integrity_check` reporting `ok`, which made an earlier
    version of this test pass vacuously.

    Which branch catches it is deliberately not asserted, because it is not stable:
    this scribble makes SQLite *raise* `DatabaseError: database disk image is malformed`
    while running the pragma, rather than return a non-`ok` string from it. Both paths
    lead to the same verdict, and both are covered — asserting the mechanism here would
    pin behaviour that belongs to SQLite.
    """
    path = tmp_path / "store.db"
    _make_db(path, trades=2000)
    assert path.stat().st_size > 4096 * 8  # enough pages that the write lands on data
    with open(path, "r+b") as fh:
        fh.seek(4096 * 4)
        fh.write(b"\xde\xad\xbe\xef" * 1024)

    validity = validate_dataset(str(path))
    assert validity.ok is False
    assert validity.empty is False  # damaged is not "nothing here yet"


def test_summary_line_names_the_first_failure(good_db):
    """The one-line summary names the check that failed, so the log is actionable."""
    conn = sqlite3.connect(good_db)
    conn.execute("INSERT INTO flex_trade VALUES ('key-0', 'flex', -100.0, '2026-08-04')")
    conn.commit()
    conn.close()

    line = validate_dataset(good_db).summary
    assert "execution_key" in line


# ── dataset_fingerprint — the "did this pull change anything" decision ─────────


def test_fingerprint_is_stable_when_nothing_changes(good_db):
    """An unchanged dataset fingerprints identically — that is what skips the Drive re-upload."""
    assert dataset_fingerprint(good_db) == dataset_fingerprint(good_db)


def test_fingerprint_moves_when_a_trade_lands(good_db):
    """A new trade moves the fingerprint, so the backup follows the data."""
    before = dataset_fingerprint(good_db)
    conn = sqlite3.connect(good_db)
    conn.execute("INSERT INTO flex_trade VALUES ('key-new', 'flex', -1.0, '2026-08-05')")
    conn.commit()
    conn.close()

    assert dataset_fingerprint(good_db) != before


def test_fingerprint_moves_when_a_live_row_is_merged_into_flex(good_db):
    """The 2026-08-05 case: row COUNT was unchanged (1,110 before and after) because
    the Flex statement merged onto the nine live rows via execution_key. A count-only
    fingerprint would have called that 'no change' and skipped the backup, losing the
    settled statement figures. The source mix has to be part of the fingerprint."""
    conn = sqlite3.connect(good_db)
    conn.execute("INSERT INTO flex_trade VALUES ('key-live', 'live', -1.0, '2026-08-05')")
    conn.commit()
    conn.close()
    before = dataset_fingerprint(good_db)

    conn = sqlite3.connect(good_db)
    conn.execute("UPDATE flex_trade SET source='flex' WHERE execution_key='key-live'")
    conn.commit()
    conn.close()

    assert dataset_fingerprint(good_db) != before


def test_fingerprint_of_a_missing_file_is_not_an_error(tmp_path):
    """Used to gate an upload; it must never be the thing that breaks startup."""
    assert dataset_fingerprint(str(tmp_path / "nope.db")) is None


# ── "already updated today — do not check again" (user rule, 2026-08-05) ──────
#
# Flex is T+1 and the store is pulled once a day. Re-running the checks on a byte-identical
# dataset every time a session starts is work that cannot produce a new answer, and it puts
# an unqualified "integrity validated" on screen with no indication of *when* anything was
# actually established. So the verdict is cached with the fingerprint it was computed
# against, and reused for the rest of the day — the UI then states the time it was proven
# rather than implying it happened just now.

from datetime import UTC, datetime, timedelta  # noqa: E402
from pathlib import Path  # noqa: E402
from unittest.mock import patch  # noqa: E402

from ibkr_core_mcp.flex_sync import last_import, validate_dataset_daily  # noqa: E402

_NOW = datetime(2026, 8, 5, 14, 30, tzinfo=UTC)


def _import_log(path, when: datetime, filename: str = "flex_U1234567_2026-08-05.xml") -> None:
    """Write one `flex_import_log` row stamped at `when`, creating the table if needed."""
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS flex_import_log ("
        "id INTEGER PRIMARY KEY, filename TEXT, sha256 TEXT, trade_id_count INTEGER,"
        "raw_trade_count INTEGER, source TEXT, imported_at TEXT, verified_at TEXT)"
    )
    conn.execute(
        "INSERT INTO flex_import_log (filename, trade_id_count, raw_trade_count, source,"
        " imported_at, verified_at) VALUES (?, 105, 105, 'auto', ?, ?)",
        (filename, when.isoformat(), when.isoformat()),
    )
    conn.commit()
    conn.close()


def test_the_first_run_of_the_day_actually_validates(good_db):
    """The day's first run really validates and reports when it proved it."""
    outcome = validate_dataset_daily(good_db, now=_NOW)
    assert outcome.reused is False
    assert outcome.validity.ok is True
    assert outcome.validated_at == _NOW


def test_the_second_run_reuses_the_verdict_without_rechecking(good_db):
    """The second run does no work, and reports when the verdict was proven, not when asked."""
    validate_dataset_daily(good_db, now=_NOW)
    with patch("ibkr_core_mcp.flex_sync.validate_dataset") as never:
        outcome = validate_dataset_daily(good_db, now=_NOW + timedelta(hours=2))
    never.assert_not_called()  # the whole point: no work, not merely a fast path
    assert outcome.reused is True
    assert outcome.validity.ok is True
    assert outcome.validated_at == _NOW  # reports when it was PROVEN, not when it was asked


def test_a_changed_dataset_is_revalidated_the_same_day(good_db):
    """A pull that changed the data invalidates the cached verdict, same day or not."""
    validate_dataset_daily(good_db, now=_NOW)
    conn = sqlite3.connect(good_db)
    conn.execute("INSERT INTO flex_trade VALUES ('key-new', 'flex', -1.0, '2026-08-05')")
    conn.commit()
    conn.close()

    outcome = validate_dataset_daily(good_db, now=_NOW + timedelta(minutes=1))
    assert outcome.reused is False  # a pull landed; the old verdict no longer describes it


def test_yesterdays_verdict_is_not_reused_today(good_db):
    """A verdict does not survive the day boundary."""
    validate_dataset_daily(good_db, now=_NOW - timedelta(days=1))
    outcome = validate_dataset_daily(good_db, now=_NOW)
    assert outcome.reused is False


def test_a_failed_verdict_is_never_reused(good_db):
    """A failure is re-measured every time, never cached forward."""
    conn = sqlite3.connect(good_db)
    conn.execute("INSERT INTO flex_trade VALUES ('key-0', 'flex', -100.0, '2026-08-04')")
    conn.commit()
    conn.close()

    first = validate_dataset_daily(good_db, now=_NOW)
    assert first.validity.ok is False
    second = validate_dataset_daily(good_db, now=_NOW + timedelta(minutes=1))
    assert second.reused is False  # a failure must be re-measured, never cached forward


def test_an_unwritable_location_still_validates(good_db):
    """Caching is an optimisation. Losing it must cost speed, never the check."""
    with patch("ibkr_core_mcp.flex_sync.Path.write_text", side_effect=OSError("read-only fs")):
        outcome = validate_dataset_daily(good_db, now=_NOW)
    assert outcome.validity.ok is True
    assert outcome.reused is False


def test_a_corrupt_cache_file_is_ignored_rather_than_trusted(good_db):
    """An unreadable cache file causes a fresh validation rather than a trusted stale verdict."""
    validate_dataset_daily(good_db, now=_NOW)
    Path(f"{good_db}.validation.json").write_text("{not json")

    outcome = validate_dataset_daily(good_db, now=_NOW + timedelta(minutes=1))
    assert outcome.reused is False
    assert outcome.validity.ok is True


# ── last_import — when the store was actually updated ─────────────────────────


def test_last_import_reports_the_most_recent_pull(good_db):
    """The newest import row wins, by timestamp rather than insertion order."""
    _import_log(good_db, datetime(2026, 8, 4, 17, 59, tzinfo=UTC), "older.xml")
    _import_log(good_db, datetime(2026, 8, 5, 12, 18, 1, tzinfo=UTC), "newest.xml")

    record = last_import(good_db)
    assert record is not None
    assert record.filename == "newest.xml"
    assert record.at == datetime(2026, 8, 5, 12, 18, 1, tzinfo=UTC)


def test_last_import_counts_only_flex_pulls(good_db):
    """`flex_import_log` also registers hand-downloaded archive statements (source
    'manual', stamped when the archive check first sees them); that is not a Flex pull."""
    _import_log(good_db, datetime(2026, 9, 28, 14, 44, tzinfo=UTC), "flex_pull.xml")
    conn = sqlite3.connect(good_db)
    conn.execute(
        "INSERT INTO flex_import_log (filename, source, imported_at) VALUES (?, 'manual', ?)",
        ("ClaudIA_Full_Activity_123125.xml", "2026-09-28T15:00:00+00:00"),
    )
    conn.commit()
    conn.close()

    record = last_import(good_db)
    assert record is not None and record.filename == "flex_pull.xml"


def test_last_import_is_none_before_anything_was_ever_imported(good_db):
    """With no import history there is no last import to report."""
    assert last_import(good_db) is None


def test_last_import_survives_an_unparseable_timestamp(good_db):
    """An unparseable timestamp yields None — no time is better than a wrong time on screen."""
    conn = sqlite3.connect(good_db)
    conn.execute(
        "CREATE TABLE flex_import_log (id INTEGER PRIMARY KEY, filename TEXT, sha256 TEXT,"
        " trade_id_count INTEGER, raw_trade_count INTEGER, source TEXT, imported_at TEXT,"
        " verified_at TEXT)"
    )
    conn.execute("INSERT INTO flex_import_log (filename, source, imported_at) VALUES ('x.xml', 'auto', 'never')")
    conn.commit()
    conn.close()

    assert last_import(good_db) is None  # no time is better than a wrong time on screen


def test_an_unreadable_path_writes_no_sidecar_at_all(tmp_path, monkeypatch):
    """Regression, 2026-08-05: it used to write one anyway.

    `_write_record` fired even when the dataset could not be fingerprinted, so any caller
    with an unusable path left a file behind — and a unit test passing a `MagicMock`
    config wrote `<MagicMock name='mock._config.sqlite_path' id=…>.validation.json` into
    the repository root. Fourteen reached a commit. Such a record can never be reused
    (reuse requires a fingerprint match), so writing it was cost with no benefit.
    """
    monkeypatch.chdir(tmp_path)
    outcome = validate_dataset_daily(str(tmp_path / "does-not-exist.db"), now=_NOW)

    assert outcome.validity.ok is False  # still reports honestly
    assert outcome.reused is False
    assert list(tmp_path.glob("*.validation.json")) == []
    assert list(tmp_path.iterdir()) == []  # nothing dropped anywhere


def test_a_mock_shaped_path_leaves_the_working_directory_clean(tmp_path, monkeypatch):
    """The exact shape that littered the repo: a path that is not a path."""
    from unittest.mock import MagicMock

    monkeypatch.chdir(tmp_path)
    validate_dataset_daily(MagicMock(), now=_NOW)

    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------------------
# The startup pull rule (operator 2026-09-28, supersedes gap #72's "fruitful pull since
# midnight ET"): pull unless the store already holds the statement for the weekday before
# today (ET). Flex is T+1 and IBKR serves one statement per weekday — every one of our 29
# pulls, 2026-06-26 → 09-28, at any hour, came back through the previous weekday and never
# the same day — and a repeat pull on the same day returns the cached statement, so an
# extra pull costs one request and changes nothing.
# ---------------------------------------------------------------------------


def _nav_rows(path, *to_dates: str) -> None:
    """One `flex_change_in_nav` row per archived statement, as the core's archive stores it."""
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS flex_change_in_nav (row_uid TEXT, src_file TEXT, stmt_to_date TEXT)")
    for i, to_date in enumerate(to_dates):
        conn.execute("INSERT INTO flex_change_in_nav VALUES (?, ?, ?)", (f"r{i}", f"f{i}.xml", to_date))
    conn.commit()
    conn.close()


def test_statement_through_is_the_newest_statement_the_store_holds(good_db):
    """The evidence is the statement's own `toDate`, not a trade date: a weekday with no
    trades still has a statement."""
    from datetime import date

    from ibkr_core_mcp.flex_sync import statement_through

    _nav_rows(good_db, "20260923", "20260925", "20260924")
    assert statement_through(good_db) == date(2026, 9, 25)


def test_statement_through_is_none_when_nothing_can_be_read(good_db, tmp_path):
    """No archive table, an empty one, an unparseable date, a missing file: unknown, never
    a guess — and unknown makes the pull due."""
    from ibkr_core_mcp.flex_sync import statement_through

    assert statement_through(good_db) is None  # table absent
    _nav_rows(good_db)
    assert statement_through(good_db) is None  # table empty
    _nav_rows(good_db, "not a date")
    assert statement_through(good_db) is None
    assert statement_through(str(tmp_path / "missing.db")) is None


@pytest.mark.parametrize(
    ("now_utc", "through", "due", "why"),
    [
        ("2026-09-28T14:44:00+00:00", "2026-09-25", False, "Mon: Friday's statement is the newest"),
        ("2026-09-28T14:44:00+00:00", "2026-09-24", True, "Mon: Friday's is missing"),
        ("2026-09-29T12:00:00+00:00", "2026-09-25", True, "Tue: Monday's is missing"),
        ("2026-09-29T12:00:00+00:00", "2026-09-28", False, "Tue: Monday's is held"),
        ("2026-09-26T14:42:00+00:00", "2026-09-25", False, "Sat: Friday's is the newest"),
        ("2026-09-27T14:42:00+00:00", "2026-09-25", False, "Sun: Friday's is the newest"),
        ("2026-09-26T14:42:00+00:00", "2026-09-24", True, "Sat: Friday's is missing"),
        ("2026-09-28T14:44:00+00:00", None, True, "unknown is not current"),
        ("2026-09-29T03:30:00+00:00", "2026-09-25", False, "23:30 ET Mon is still Monday in ET"),
        ("2026-09-29T04:30:00+00:00", "2026-09-25", True, "00:30 ET Tue: Monday's can exist"),
    ],
)
def test_a_pull_is_due_unless_the_store_holds_the_previous_weekdays_statement(now_utc, through, due, why):
    """The whole rule. Weekdays, not exchange days: the 07-06 pull came back through the
    07-03 US holiday. A pull made before IBKR publishes brings an older `toDate`, so the next
    start is still due — no clock in the rule."""
    from datetime import date, datetime

    from ibkr_core_mcp.flex_sync import pull_due

    held = date.fromisoformat(through) if through else None
    assert pull_due(datetime.fromisoformat(now_utc), held) is due, why


def test_pull_due_refuses_a_naive_now():
    """A naive datetime has no ET date; refusing it is safer than assuming UTC."""
    from datetime import datetime

    from ibkr_core_mcp.flex_sync import pull_due

    with pytest.raises(ValueError):
        pull_due(datetime(2026, 9, 28, 10, 44), None)


# ── four behaviours the relocation's mutation battery found unpinned (2026-09-30) ──
#
# Each of these survived a deliberate break with the tests above green: the damaged-file
# test reaches its verdict through SQLite RAISING, never through a non-"ok" pragma result;
# the NULL-key test also broke the realised identity, so either check failing passed it;
# a placeholder never carries a figure, so nothing showed the identity is over statement
# rows only; and nothing read the sidecar's mode.


def test_a_failed_integrity_check_is_reported_in_sqlites_own_words(tmp_path):
    """The pragma can answer with findings instead of raising. `x` is declared NOT NULL
    after a NULL was stored in it, which `integrity_check` reports as a row of text."""
    path = tmp_path / "store.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE t (x);
        INSERT INTO t VALUES (NULL);
        PRAGMA writable_schema = ON;
        UPDATE sqlite_master SET sql = 'CREATE TABLE t (x NOT NULL)' WHERE name = 't';
        PRAGMA writable_schema = OFF;
        """
    )
    conn.commit()
    conn.close()

    validity = validate_dataset(str(path))

    assert validity.ok is False and validity.empty is False
    assert [c.name for c in validity.checks] == ["file integrity"], "nothing is counted off a damaged file"
    assert "NULL value in t.x" in validity.checks[0].detail


def test_a_null_execution_key_fails_its_own_check(good_db):
    """The identity is kept balanced, so the only thing wrong is the key."""
    conn = sqlite3.connect(good_db)
    conn.execute("INSERT INTO flex_trade VALUES (NULL, 'flex', -100.0, '2026-08-04')")
    conn.execute("INSERT INTO flex_lot VALUES (-250.0)")
    conn.execute("INSERT INTO flex_wash_sale VALUES (150.0)")
    conn.commit()
    conn.close()

    validity = validate_dataset(good_db)

    assert [f.name for f in validity.failures] == ["execution_key is present"]
    assert validity.failures[0].detail == "1 row(s) without a key"


def test_the_identity_is_over_statement_rows_only(good_db):
    """A placeholder carrying a figure — which no writer produces — is not realised P&L."""
    conn = sqlite3.connect(good_db)
    conn.execute("INSERT INTO flex_trade VALUES ('key-live', 'live', -1.0, '2026-08-05')")
    conn.commit()
    conn.close()

    assert validate_dataset(good_db).ok is True


def test_the_verdict_sidecar_is_private(good_db):
    """It summarises the account's trade dataset; 0600, like the store beside it."""
    import stat

    validate_dataset_daily(good_db, now=_NOW)
    record = Path(f"{good_db}.validation.json")
    assert stat.S_IMODE(record.stat().st_mode) == 0o600


def test_a_verdict_sidecar_left_world_readable_is_corrected_on_the_next_write(good_db):
    """The chmod is unconditional: `write_text` leaves an existing file's mode alone, so a
    record created before the rule was corrected by the next verdict or never. claudia_ui's
    2026-08-05 security audit (L-2) found the real store's record at 0644."""
    import stat

    record = Path(f"{good_db}.validation.json")
    record.write_text("{}")
    record.chmod(0o644)

    validate_dataset_daily(good_db, now=_NOW)

    assert stat.S_IMODE(record.stat().st_mode) == 0o600


# ── against a dataset the real writer built ───────────────────────────────────
#
# Everything above runs on tables written by hand. These run the same functions on a store
# built by `parse_statement` + `SQLiteStore.upsert_flex_statement`, the only writer there is.


def _real_store(mock_config, *statements):
    from tests.flex_fixtures import annual_statement, seed_flex_dataset

    seed_flex_dataset(
        mock_config, *(statements or (annual_statement(2025, trade_ids=(101, 102, 103), pnl_per_trade=-50.0),))
    )
    return mock_config.sqlite_path


def test_a_dataset_built_by_the_real_writer_validates(mock_config):
    """Three trades of -50.00 with their three lots: every check runs and passes."""
    path = _real_store(mock_config)
    validity = validate_dataset(path)
    assert validity.ok is True and validity.empty is False
    assert [c.name for c in validity.checks] == [
        "file integrity",
        "execution_key is unique",
        "execution_key is present",
        "realised P&L identity (trades == lots + wash sale)",
    ]
    assert dataset_fingerprint(path) == (3, 3, "2025-06-15")


def test_a_lot_the_trades_do_not_account_for_breaks_the_identity_on_the_real_schema(mock_config):
    from tests.flex_fixtures import annual_statement, lot, statement

    path = _real_store(
        mock_config,
        annual_statement(2025, trade_ids=(101,), pnl_per_trade=-50.0),
        statement(lot(tradeDate="20250616", fifoPnlRealized="-9999")),
    )
    validity = validate_dataset(path)
    assert validity.ok is False
    assert [f.name for f in validity.failures] == ["realised P&L identity (trades == lots + wash sale)"]
    assert "off by 9,999.00" in validity.failures[0].detail


def test_a_live_placeholder_moves_the_fingerprint_and_not_the_identity(mock_config):
    """A fill captured before its statement is a row (the total moves) but not a statement
    row (the Flex count, the newest trade date and the realised identity do not)."""
    from ibkr_core_mcp.store import SQLiteStore

    path = _real_store(mock_config)
    SQLiteStore(mock_config).upsert_flex_trades_from_live(
        [
            {
                "execution_id": "0000live.1.01.01",
                "symbol": "TEST",
                "side": "B",
                "size": 1,
                "price": 1.0,
                "time": "20260105-15:00:00",
                "commission": 1.0,
                "account": "U0000000",
            }
        ]
    )
    assert dataset_fingerprint(path) == (4, 3, "2025-06-15")
    assert validate_dataset(path).ok is True


def test_statement_through_is_the_to_date_of_a_statement_with_no_trades(mock_config):
    """A weekday with no fills still has a statement; holding it is what "through" means."""
    from datetime import date

    from ibkr_core_mcp.flex_sync import statement_through
    from tests.flex_fixtures import annual_statement, element, statement

    path = _real_store(
        mock_config,
        annual_statement(2025, trade_ids=(101,), pnl_per_trade=-50.0),
        statement(element("ChangeInNAV", accountId="U0000000"), from_date="20260105", to_date="20260105"),
    )
    assert statement_through(path) == date(2026, 1, 5)
    assert dataset_fingerprint(path) == (1, 1, "2025-06-15"), "the newest TRADE date is a different question"


def test_statement_through_falls_back_to_the_settled_trades_without_the_nav_table(mock_config):
    """The core's rule since register F19: an archive whose `flex_change_in_nav` is absent
    still carries each statement's `toDate` on its trade rows. (claudia_ui's copy read the
    NAV table only and answered None here.)"""
    import sqlite3 as sq
    from datetime import date

    from ibkr_core_mcp.flex_sync import statement_through

    path = _real_store(mock_config)  # the annual statement: toDate 2025-12-31
    conn = sq.connect(path)
    conn.execute("DROP TABLE flex_change_in_nav")
    conn.commit()
    conn.close()
    assert statement_through(path) == date(2025, 12, 31)


def test_the_state_functions_read_a_store_whose_path_holds_uri_metacharacters(mock_config, tmp_path):
    """One opener for every reader (`flex_dataset.open_read_only`): a `?` or `#` in the path
    must not turn a read into the creation of a different file."""
    from dataclasses import replace

    from ibkr_core_mcp.flex_sync import last_import, statement_through

    odd = tmp_path / "odd #2 ?y"
    odd.mkdir()
    path = _real_store(replace(mock_config, sqlite_path=odd / "store.db"))
    before = sorted(p.name for p in tmp_path.iterdir())

    assert validate_dataset(path).ok is True
    assert dataset_fingerprint(path) == (3, 3, "2025-06-15")
    assert statement_through(path) is not None
    assert last_import(path) is None
    assert sorted(p.name for p in tmp_path.iterdir()) == before


def test_pull_due_is_the_store_s_own_stale_verdict(mock_config):
    """One rule in one package: `pull_due(now, statement_through(path))` and
    `get_trade_date_coverage(now=now)["stale"]` are the same sentence."""
    from datetime import UTC, datetime

    from ibkr_core_mcp.flex_sync import newest_statement_day, pull_due, statement_through
    from ibkr_core_mcp.store import SQLiteStore
    from ibkr_core_mcp.store import newest_statement_day as the_store_s
    from tests.flex_fixtures import element, statement

    assert newest_statement_day is the_store_s, "one definition of the statement day"
    path = _real_store(
        mock_config, statement(element("ChangeInNAV", accountId="U0000000"), from_date="20260925", to_date="20260925")
    )
    store = SQLiteStore(mock_config)
    for now in (
        datetime(2026, 9, 28, 14, 44, tzinfo=UTC),  # Monday: Friday's statement is the newest
        datetime(2026, 9, 29, 12, 0, tzinfo=UTC),  # Tuesday: Monday's is missing
        datetime(2026, 9, 27, 14, 42, tzinfo=UTC),  # Sunday
    ):
        assert pull_due(now, statement_through(path)) is store.get_trade_date_coverage(now=now)["stale"], now


# ---------------------------------------------------------------------------
# Never raises, through the one opener (claudia_ui plan § 13, items 9, 17 and 18).
# `open_read_only` raises `UNOPENABLE` — SQLite's errors, and `TypeError`, `OSError` and
# `ValueError` for a value that names no file — and every reader here answers "unreadable"
# for each member. `mode=ro` is tested once, on the opener; a spy holds each reader to it,
# because a reader never writes, so a read-write open would show in no answer.
# ---------------------------------------------------------------------------
from datetime import date  # noqa: E402

from ibkr_core_mcp import flex_sync  # noqa: E402
from ibkr_core_mcp.flex_sync import statement_through  # noqa: E402


def _full_store(path) -> None:
    """`_make_db` plus the two tables `last_import` and `statement_through` read."""
    _make_db(path)
    _import_log(path, datetime(2026, 8, 5, 12, 18, tzinfo=UTC), "statement-20260804.xml")
    _nav_rows(path, "20260804")


# Each reader, with what a real answer from `_full_store` looks like — so a comparison
# cannot pass by both sides being "unreadable".
_READERS = [
    pytest.param(validate_dataset, lambda v: v.ok and not v.empty, id="validate_dataset"),
    pytest.param(dataset_fingerprint, lambda v: v == (1, 1, "2026-08-04"), id="dataset_fingerprint"),
    pytest.param(last_import, lambda v: v.filename == "statement-20260804.xml", id="last_import"),
    pytest.param(statement_through, lambda v: v == date(2026, 8, 4), id="statement_through"),
]

# Each reader, with its own "unreadable" answer.
_UNREADABLE = [
    pytest.param(
        validate_dataset,
        lambda v: [c.name for c in v.failures] == ["dataset unreadable"],
        id="validate_dataset",
    ),
    pytest.param(dataset_fingerprint, lambda v: v is None, id="dataset_fingerprint"),
    pytest.param(last_import, lambda v: v is None, id="last_import"),
    pytest.param(statement_through, lambda v: v is None, id="statement_through"),
]


@pytest.mark.parametrize(("read", "is_real"), _READERS)
def test_the_full_store_gives_each_reader_a_real_answer(read, is_real, tmp_path):
    """The canary on `_full_store` and `_READERS`: each reader's real answer is what the
    tests below compare against."""
    _full_store(tmp_path / "store.db")
    assert is_real(read(tmp_path / "store.db")) is True


@pytest.mark.parametrize(("read", "is_real"), _READERS)
def test_every_reader_opens_through_the_one_read_only_opener(read, is_real, tmp_path, monkeypatch):
    """`mode=ro` is tested once, on `open_read_only`; this holds each reader to it. On
    claudia_ui's side a `mode=rw` mutant of a per-module opener survived every reader test
    (gap #89), which is why the opener is the one place the mode is pinned (item 18)."""
    from ibkr_core_mcp.flex_dataset import open_read_only

    opened = []

    def spy(path):
        """Record the path, then open it with the real opener."""
        opened.append(path)
        return open_read_only(path)

    monkeypatch.setattr(flex_sync, "open_read_only", spy)
    store = tmp_path / "store.db"
    _full_store(store)

    assert is_real(read(store)) is True
    assert opened == [store]


@pytest.mark.parametrize(("read", "unreadable"), _UNREADABLE)
def test_a_nul_in_the_path_is_unreadable_even_when_its_prefix_is_a_store(read, unreadable, tmp_path):
    """A NUL names no file. The URI would carry it as `%00`, where SQLite ends the path — so the
    store built at the prefix here would be read in its place (measured on claudia_ui's copy,
    gap #89; item 16). The case passes vacuously when nothing exists at the prefix."""
    _full_store(tmp_path / "store")
    assert unreadable(read(tmp_path / "store\x00.db")) is True


# ── last_import's count (item 17) ────────────────────────────────────────────


def test_last_import_reads_the_count_and_a_null_count_is_zero(good_db):
    """The count is the row's `trade_id_count`; a NULL — a row written before the column was
    filled — reads as 0, not as unknown, because the row itself proves a pull happened."""
    _import_log(good_db, datetime(2026, 8, 5, 12, 18, tzinfo=UTC))
    record = last_import(good_db)
    assert record is not None and record.trade_count == 105

    conn = sqlite3.connect(good_db)
    conn.execute("UPDATE flex_import_log SET trade_id_count = NULL")
    conn.commit()
    conn.close()
    record = last_import(good_db)
    assert record is not None and record.trade_count == 0


@pytest.mark.parametrize("count", ["n/a", 9e999, 12.5], ids=["text", "infinite", "fraction"])
def test_last_import_is_none_rather_than_a_guess_when_the_count_is_not_an_integer(good_db, count, caplog):
    """`int()` raised on the first two (`ValueError`, `OverflowError`) — out of a reader that
    promises never to — and truncated the third to 12. None rather than a guess, as for the
    timestamp (claudia_ui gap #89)."""
    _import_log(good_db, datetime(2026, 8, 5, 12, 18, tzinfo=UTC))
    conn = sqlite3.connect(good_db)
    conn.execute("UPDATE flex_import_log SET trade_id_count = ?", (count,))
    conn.commit()
    conn.close()

    assert last_import(good_db) is None
    assert "trade_id_count" in caplog.text


# ── last_pull — what the last recorded Flex pull did (register F30) ──────────────
#
# A consumer showed the pull tool's text under a tick and could learn that the archive had
# refused a statement, or that the Drive backup had failed, only by reading "⚠" out of that
# text. The pull already writes its outcome to `session_log`; `last_pull` reads it back
# typed. Rows are written here with the real store, as the tool writes them.


from ibkr_core_mcp.flex_sync import PullOutcome, last_pull  # noqa: E402

_CLEAN = {
    "account": "U0000000",
    "trades_fetched": 120,
    "newest": "2026-09-30",
    "total": 1285,
    "archive_ok": True,
    "archive_reason": None,
    "backup": "uploaded",
    "valid": True,
}


def _store_with_pulls(mock_config, *rows):
    """A real store whose `session_log` holds one `flex_sync` event per row, in order."""
    from ibkr_core_mcp.store import SQLiteStore

    store = SQLiteStore(mock_config)
    for row in rows:
        store.log_entry("flex_sync", **row)
    return mock_config.sqlite_path


def _rewrite_last_event(path, *, ts=None, data=None):
    """Put raw text into the newest `session_log` row — the shapes the writer never produces."""
    conn = sqlite3.connect(str(path))
    if ts is not None:
        conn.execute("UPDATE session_log SET ts = ? WHERE id = (SELECT MAX(id) FROM session_log)", (ts,))
    if data is not None:
        conn.execute("UPDATE session_log SET data = ? WHERE id = (SELECT MAX(id) FROM session_log)", (data,))
    conn.commit()
    conn.close()


def test_last_pull_reads_back_what_the_pull_recorded(mock_config):
    """Every field the tool writes, typed; a clean pull names no problem."""
    before = datetime.now(UTC)
    outcome = last_pull(_store_with_pulls(mock_config, _CLEAN))

    assert isinstance(outcome, PullOutcome)
    assert before - timedelta(seconds=5) <= outcome.at <= datetime.now(UTC) + timedelta(seconds=5)
    assert outcome.at.tzinfo is not None
    assert (outcome.trades_fetched, outcome.archive_ok, outcome.archive_reason) == (120, True, None)
    assert (outcome.backup, outcome.valid) == ("uploaded", True)
    assert outcome.problems == ()


@pytest.mark.parametrize(
    ("changes", "problems"),
    [
        ({"archive_ok": False, "archive_reason": "unknown column fooBar"}, ("archive",)),
        ({"backup": "failed"}, ("backup",)),
        ({"valid": False}, ("validation",)),
        (
            {"archive_ok": False, "archive_reason": "x", "backup": "failed", "valid": False},
            ("archive", "backup", "validation"),
        ),
        ({"backup": "unchanged"}, ()),
        ({"backup": "not-configured"}, ()),
    ],
    ids=["archive-refused", "backup-failed", "dataset-invalid", "all-three-in-order", "backup-unchanged", "no-drive"],
)
def test_last_pull_names_what_is_known_to_have_gone_wrong(mock_config, changes, problems):
    """The names a consumer chooses its level from — never the tool's text."""
    outcome = last_pull(_store_with_pulls(mock_config, {**_CLEAN, **changes}))

    assert outcome is not None and outcome.problems == problems
    if "archive_reason" in changes:
        assert outcome.archive_reason == changes["archive_reason"]


def test_last_pull_is_the_newest_pull_not_the_first(mock_config):
    """Two pulls on record: the later one answers."""
    path = _store_with_pulls(mock_config, {**_CLEAN, "backup": "failed"}, {**_CLEAN, "trades_fetched": 7})

    outcome = last_pull(path)

    assert outcome is not None and (outcome.trades_fetched, outcome.problems) == (7, ())


def test_last_pull_ignores_other_events(mock_config):
    """`session_log` holds every kind of event; only a pull is a pull."""
    from ibkr_core_mcp.store import SQLiteStore

    path = _store_with_pulls(mock_config, {**_CLEAN, "trades_fetched": 3})
    SQLiteStore(mock_config).log_entry("startup", valid=False, backup="failed")

    outcome = last_pull(path)

    assert outcome is not None and (outcome.trades_fetched, outcome.problems) == (3, ())


def test_a_time_without_a_zone_is_read_as_utc(mock_config):
    """The writer stamps UTC with an offset; a bare stamp from an older row is the same clock."""
    path = _store_with_pulls(mock_config, _CLEAN)
    _rewrite_last_event(path, ts="2026-09-30T20:44:46")

    outcome = last_pull(path)

    assert outcome is not None and outcome.at == datetime(2026, 9, 30, 20, 44, 46, tzinfo=UTC)


def test_last_pull_never_raises_and_never_invents(tmp_path, mock_config):
    """No store, a directory, a path SQLite cannot open, a store with no log, a store with no
    pull: None each time."""
    from ibkr_core_mcp.store import SQLiteStore

    assert last_pull(tmp_path / "absent.db") is None
    assert last_pull(tmp_path) is None
    assert last_pull(str(tmp_path / "nul\x00.db")) is None
    not_a_db = tmp_path / "garbage.db"
    not_a_db.write_bytes(b"this is not a database")
    assert last_pull(not_a_db) is None
    bare = tmp_path / "bare.db"
    sqlite3.connect(str(bare)).close()
    assert last_pull(bare) is None  # no session_log table
    SQLiteStore(mock_config).initialize()
    assert last_pull(mock_config.sqlite_path) is None  # the table, and no pull in it
