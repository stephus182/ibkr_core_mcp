"""Archive and database fixtures for the `scripts/` CLI tests.

Every archive here is built on a `tmp_path`, never against `~/.ibkr_core/flex_archive`,
and every database is a fresh temporary file, never `~/.ibkr_core/store.db`. That is not
politeness: `rebuild_flex_dataset.py` drops all 14 `flex_*` tables, and a test that
pointed at the real store would destroy six years of trade history.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ibkr_core_mcp.config import Config
from ibkr_core_mcp.flex_schema import ELEMENTS
from ibkr_core_mcp.store import SQLiteStore
from tests.flex_fixtures import (
    TRUNCATED_XML,
    WARN_1019_XML,
    annual_statement,
    element,
    statement,
    trade,
)


@pytest.fixture
def empty_archive(tmp_path: Path) -> Path:
    """A directory that exists but holds no statements — the schema-wipe trigger."""
    src = tmp_path / "empty_archive"
    src.mkdir()
    return src


@pytest.fixture
def annual_archive(tmp_path: Path) -> Path:
    """Two annual statements plus one partial-period statement.

    Two full calendar years mean the annual reconciliation (17c) has material to work
    with, and the partial statement is there so "annual" cannot be satisfied by simply
    accepting every statement present.
    """
    src = tmp_path / "annual_archive"
    src.mkdir()
    (src / "stmt_2024.xml").write_text(
        annual_statement(2024, trade_ids=(700001, 700002), pnl_per_trade=25.0), encoding="utf-8"
    )
    (src / "stmt_2025.xml").write_text(
        annual_statement(2025, trade_ids=(700003,), pnl_per_trade=-10.0), encoding="utf-8"
    )
    (src / "stmt_2026_partial.xml").write_text(
        statement(
            trade(tradeID="700004", ibExecID="0000aaaa.70000004.01.01", tradeDate="20260615"),
            from_date="20260101",
            to_date="20260630",
            when_generated="20260701;120000",
        ),
        encoding="utf-8",
    )
    # One row of every remaining element type, so check 16 ("each table has rows") has
    # something to find in all 14 tables. Trade and Lot are excluded deliberately: an
    # attribute-less Trade would break the distribution checks, and an attribute-less Lot
    # carries no realised P&L and resolves to no trade, which checks 17e/17f rightly fail.
    other = "".join(element(tag) for tag in ELEMENTS if tag not in {"Trade", "Lot"})
    (src / "stmt_misc.xml").write_text(
        statement(other, from_date="20260701", to_date="20260731", when_generated="20260801;120000"),
        encoding="utf-8",
    )
    return src


@pytest.fixture
def poisoned_archive(annual_archive: Path) -> Path:
    """A good archive with one IBKR error payload in it — the real 2026-07-02 shape.

    This is not hypothetical: a 226-byte `ErrorCode 1019` response sat in the production
    archive until 2026-08-10, and re-fetching from Drive brings it straight back.
    """
    (annual_archive / "flex_U0000000_2026-07-02_2928480049.xml").write_text(WARN_1019_XML, encoding="utf-8")
    return annual_archive


@pytest.fixture
def truncated_archive(annual_archive: Path) -> Path:
    """A good archive with one statement cut off mid-write."""
    (annual_archive / "stmt_truncated.xml").write_text(TRUNCATED_XML, encoding="utf-8")
    return annual_archive


@pytest.fixture
def empty_db(tmp_path: Path) -> Path:
    """A database with the full production schema created, but no rows.

    Built through `SQLiteStore` rather than `create_flex_tables` alone so it carries
    `trades` and `flex_import_log` too — the audit compares the archive against the
    import log, and a fixture holding only the `flex_*` tables would exercise a shape
    production never has.
    """
    db = tmp_path / "store.db"
    store = SQLiteStore(
        Config(
            gateway_url="https://localhost:5055/v1/api",
            anthropic_api_key="test-key",
            gdrive_folder_id="test-folder-id",
            sqlite_path=db,
            gdrive_token_file=tmp_path / "token.json",
            gdrive_credentials_file=tmp_path / "credentials.json",
        )
    )
    store.initialize()
    store.initialize_flex_tables()
    return db
