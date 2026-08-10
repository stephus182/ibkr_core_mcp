"""`rebuild_flex_dataset.py` must not be able to destroy the dataset silently.

The script drops all 14 `flex_*` tables and re-imports the archive. Before 2026-08-10 it
did that **first** and validated **never**: a run in which every statement was rejected
erased six years of trade history and still returned 0.

Two of these tests guard something that was live, not theoretical, on the day they were
written: the production archive was one statement behind the database, so a rebuild would
have permanently destroyed 7 real trades carrying thousands of dollars of realised P&L,
and those rows existed in no other file.
"""

from __future__ import annotations

import hashlib
import sqlite3

import pytest
import rebuild_flex_dataset
from audit_flex_dataset import run_gate

from ibkr_core_mcp.config import Config
from ibkr_core_mcp.flex_import import parse_statement
from ibkr_core_mcp.store import SQLiteStore
from tests.flex_fixtures import WARN_1019_XML, annual_statement

pytestmark = pytest.mark.scripts


def _trade_count(db) -> int:
    conn = sqlite3.connect(db)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM flex_trade").fetchone()[0])
    finally:
        conn.close()


def _seed_live_row(db) -> None:
    """Put a Client Portal fill into flex_trade via the real production path.

    These rows arrive from `/iserver/account/trades` and are enriched by their Flex
    statement T+1. Until that happens they exist **only** here — the XML archive does
    not contain them, so a DROP is unrecoverable.
    """
    store = SQLiteStore(
        Config(
            gateway_url="https://localhost:5055/v1/api",
            anthropic_api_key="test-key",
            gdrive_folder_id="test-folder-id",
            sqlite_path=db,
            gdrive_token_file=db.parent / "token.json",
            gdrive_credentials_file=db.parent / "credentials.json",
        )
    )
    store.initialize()
    store.upsert_flex_trades_from_live(
        [
            {
                "execution_id": "0000aaaa.99999999.01.01",
                "symbol": "TEST",
                "side": "SELL",
                "size": 3,
                "price": 100.0,
                "trade_time": "20260810;143000",
                "account": "U0000000",
                "commission": 1.0,
            }
        ]
    )


# ── the archive must be proven good before anything is dropped ──────────────────


def test_refuses_to_drop_when_any_statement_is_unparseable(annual_archive, empty_db):
    """One error payload in the archive must abort the rebuild, not shrink the dataset.

    The 226-byte `ErrorCode 1019` response written in here sat in the real archive for
    five weeks and comes back from Drive on every fetch.
    """
    rebuild_flex_dataset.rebuild(annual_archive, empty_db, backup=False)
    before = _trade_count(empty_db)
    assert before > 0

    (annual_archive / "flex_U0000000_2026-07-02_2928480049.xml").write_text(WARN_1019_XML, encoding="utf-8")
    rc = rebuild_flex_dataset.main(["--src", str(annual_archive), "--db", str(empty_db)])

    assert rc == 2
    assert _trade_count(empty_db) == before, "rows were destroyed despite the refusal"


def test_refuses_a_truncated_statement(truncated_archive, empty_db):
    """A half-written file is the disk-full shape; it must not silently shrink the set."""
    rc = rebuild_flex_dataset.main(["--src", str(truncated_archive), "--db", str(empty_db)])
    assert rc == 2


def test_refuses_an_archive_with_no_xml_files(empty_archive, empty_db):
    """An existing but empty directory must not be read as 'nothing to import, fine'."""
    rc = rebuild_flex_dataset.main(["--src", str(empty_archive), "--db", str(empty_db)])
    assert rc == 2


# ── live Client-Portal rows exist nowhere else ──────────────────────────────────


def test_refuses_to_drop_while_live_rows_exist(annual_archive, empty_db):
    """A live fill awaiting its T+1 statement cannot be re-imported from the archive."""
    _seed_live_row(empty_db)

    rc = rebuild_flex_dataset.main(["--src", str(annual_archive), "--db", str(empty_db)])

    assert rc == 2
    conn = sqlite3.connect(empty_db)
    live = conn.execute("SELECT COUNT(*) FROM flex_trade WHERE source='live'").fetchone()[0]
    conn.close()
    assert live == 1, "the unenriched live fill was destroyed"


def test_drop_live_discards_only_with_the_explicit_flag(annual_archive, empty_db):
    """The escape hatch exists, but it must be asked for by name."""
    _seed_live_row(empty_db)

    rc = rebuild_flex_dataset.main(["--src", str(annual_archive), "--db", str(empty_db), "--drop-live"])

    assert rc == 0
    conn = sqlite3.connect(empty_db)
    live = conn.execute("SELECT COUNT(*) FROM flex_trade WHERE source='live'").fetchone()[0]
    conn.close()
    assert live == 0


# ── a backup, taken before the destruction rather than after ────────────────────


def test_makes_a_backup_before_dropping(annual_archive, empty_db):
    """The backup must capture the pre-drop contents, not the post-rebuild ones."""
    _seed_live_row(empty_db)
    before = _trade_count(empty_db)

    rebuild_flex_dataset.main(["--src", str(annual_archive), "--db", str(empty_db), "--drop-live"])

    backups = sorted(empty_db.parent.glob(f"{empty_db.name}.pre-rebuild-*.bak"))
    assert backups, "no backup was written"
    conn = sqlite3.connect(backups[-1])
    backed_up = conn.execute("SELECT COUNT(*) FROM flex_trade").fetchone()[0]
    conn.close()
    assert backed_up == before, "the backup holds post-drop state, so it restores nothing"


def test_no_backup_flag_skips_it(annual_archive, empty_db):
    rebuild_flex_dataset.main(["--src", str(annual_archive), "--db", str(empty_db), "--no-backup"])
    assert not list(empty_db.parent.glob(f"{empty_db.name}.pre-rebuild-*.bak"))


# ── --dry-run, which the docstring promised and argparse rejected ───────────────


def test_dry_run_flag_exists_and_writes_nothing(annual_archive, empty_db):
    """`--dry-run` is advertised in the module docstring; it must actually exist.

    Asserted on the file's bytes, not on row counts: re-importing the same archive
    produces an identical count, so a count comparison cannot tell "wrote nothing" from
    "rewrote the same thing" — which is exactly the distinction the flag promises.
    """
    rebuild_flex_dataset.rebuild(annual_archive, empty_db, backup=False)
    before_rows = _trade_count(empty_db)
    before_bytes = hashlib.sha256(empty_db.read_bytes()).hexdigest()
    assert before_rows > 0

    rc = rebuild_flex_dataset.main(["--src", str(annual_archive), "--db", str(empty_db), "--dry-run"])

    assert rc == 0
    assert _trade_count(empty_db) == before_rows
    assert hashlib.sha256(empty_db.read_bytes()).hexdigest() == before_bytes, "--dry-run wrote to the database"
    assert not list(empty_db.parent.glob(f"{empty_db.name}.pre-rebuild-*.bak"))


def test_dry_run_reports_a_bad_archive_without_touching_the_database(poisoned_archive, empty_db):
    rc = rebuild_flex_dataset.main(["--src", str(poisoned_archive), "--db", str(empty_db), "--dry-run"])
    assert rc == 2


# ── the preflight parse is the one the import uses ──────────────────────────────


def test_each_statement_is_parsed_exactly_once(annual_archive, empty_db, monkeypatch):
    """Sorting used to fully parse every file and throw the result away."""
    calls = []
    real = parse_statement

    def counting(xml_text, src_file=""):
        calls.append(src_file)
        return real(xml_text, src_file)

    monkeypatch.setattr("rebuild_flex_dataset.parse_statement", counting)
    rebuild_flex_dataset.rebuild(annual_archive, empty_db)

    n_files = len(list(annual_archive.glob("*.xml")))
    assert len(calls) == n_files, f"parsed {len(calls)} times for {n_files} files"


# ── the docstring's promise: no success until the gate passes ───────────────────


def test_returns_nonzero_when_the_audit_gate_fails(annual_archive, empty_db, monkeypatch):
    """The module docstring promised this from day one; main() returned 0 regardless."""
    monkeypatch.setattr("rebuild_flex_dataset.run_gate", lambda db, src: 1)

    rc = rebuild_flex_dataset.main(["--src", str(annual_archive), "--db", str(empty_db)])

    assert rc == 1


def test_actually_calls_the_gate(annual_archive, empty_db, monkeypatch):
    """Calling it and discarding the result is the defect, so record the call itself."""
    calls = []
    real = run_gate

    def spy(db, src):
        calls.append((db, src))
        return real(db, src)

    monkeypatch.setattr("rebuild_flex_dataset.run_gate", spy)
    rebuild_flex_dataset.main(["--src", str(annual_archive), "--db", str(empty_db)])

    assert len(calls) == 1


def test_returns_zero_on_a_clean_synthetic_rebuild(annual_archive, empty_db):
    assert rebuild_flex_dataset.main(["--src", str(annual_archive), "--db", str(empty_db)]) == 0


def test_a_wiped_dataset_no_longer_reports_success(annual_archive, empty_db, monkeypatch):
    """The composition that matters: importing nothing must not exit 0.

    Check 16 ("each table has rows") already failed on an emptied database; nothing
    consulted it, so the erase-everything run still returned 0 to its caller.
    """
    monkeypatch.setattr("rebuild_flex_dataset.upsert_flex_rows", lambda conn, tag, rows: 0)

    rc = rebuild_flex_dataset.main(["--src", str(annual_archive), "--db", str(empty_db)])

    assert rc == 1


def test_sort_is_oldest_first_by_from_date_then_when_generated(tmp_path):
    """Later-generated statements must win, so import order is load-bearing."""
    src = tmp_path / "ordered"
    src.mkdir()
    (src / "c.xml").write_text(annual_statement(2025, trade_ids=(3,)), encoding="utf-8")
    (src / "a.xml").write_text(annual_statement(2023, trade_ids=(1,)), encoding="utf-8")
    (src / "b.xml").write_text(annual_statement(2024, trade_ids=(2,)), encoding="utf-8")

    pre = rebuild_flex_dataset.preflight(src)

    assert [p.from_date for p in pre.statements] == ["20230102", "20240102", "20250102"]


def test_same_from_date_orders_by_when_generated(tmp_path):
    src = tmp_path / "same_day"
    src.mkdir()
    (src / "late.xml").write_text(
        annual_statement(2024, trade_ids=(1,)).replace("20250102;120000", "20250105;120000"),
        encoding="utf-8",
    )
    (src / "early.xml").write_text(annual_statement(2024, trade_ids=(2,)), encoding="utf-8")

    pre = rebuild_flex_dataset.preflight(src)

    assert [p.when_generated for p in pre.statements] == ["20250102;120000", "20250105;120000"]
