"""SQLite persistence for trades, signals, positions, and backtest results.

The durable local record of what actually happened, as distinct from `cache.py`,
which holds re-fetchable market data. Flex import manifests live here too, so a
historical trade sync can be verified after the fact.

Also memoises market-calendar context per (date, exchanges) in a process-level
dict: the exchange_calendars lookup is pure for a given trading date, so it is
recomputed only when the date rolls over.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from ibkr_core_mcp.config import Config

log = logging.getLogger(__name__)

# Process-level cache for market calendar context.
# Key: (date_str, tuple(exchange_codes)) — recomputed only when the date changes.
_market_calendar_cache: dict[tuple[str, tuple[str, ...]], dict[str, Any]] = {}


def _restrict(path: Path, mode: int) -> None:
    """Narrow `path` to `mode` if it exists and differs. Never raises.

    A permissions repair must not be able to take the store down — a read that would
    have succeeded at 0644 still succeeds, and refusing to open the database because a
    chmod failed would trade a confidentiality gap for an availability outage. It is
    logged rather than swallowed, because a chmod that silently never lands is
    indistinguishable from a control that was never written.

    The existence check is not a race guard; it is what keeps the WAL sidecars optional
    (they do not exist before the first connection, and `-shm` never exists in the
    single-process case).
    """
    try:
        if path.exists() and stat.S_IMODE(path.stat().st_mode) != mode:
            path.chmod(mode)
    except OSError as exc:
        log.warning("Could not restrict %s to %o: %s", path, mode, exc)


# SQL that reads a trade date out of `trades.time` regardless of which writer produced it.
# Flex writes ISO (2026-08-04T14:21:42); the live CP API and streaming paths write IBKR's
# compact 20260804-14:21:42. Kept as one constant so the date range, the gap scan and any
# future reader cannot drift into understanding different subsets of the same table.
_TRADE_DATE_SQL = """
    CASE
        WHEN time LIKE '____-__-__%' THEN substr(time, 1, 10)
        WHEN time LIKE '________-%'  THEN
            substr(time, 1, 4) || '-' || substr(time, 5, 2) || '-' || substr(time, 7, 2)
    END
"""


def _iso_trade_time(value: Any) -> Any:
    """IBKR's compact `YYYYMMDD-HH:MM:SS` as ISO `YYYY-MM-DDTHH:MM:SS`.

    Anything already ISO, or not a string, or not matching the compact shape, is returned
    untouched — this normalises a known format, it does not guess at unknown ones. A
    timestamp we cannot parse is left exactly as the API gave it rather than coerced into
    something plausible.
    """
    if not isinstance(value, str) or len(value) < 9 or value[8] != "-" or not value[:8].isdigit():
        return value
    return f"{value[:4]}-{value[4:6]}-{value[6:8]}T{value[9:]}"


# Static CME Globex product schedule.
# Futures are NOT securities — most trade ~23h/day with a 1h maintenance break.
# All times are CT (Chicago Time). IBKR routes all CME products via Globex (electronic).
# Source: CME Group — cmegroup.com/trading-hours.html
_FUTURES_SCHEDULE: dict[str, Any] = {
    "note": (
        "Futures are not securities. Most CME Globex products trade ~23h/day "
        "Sunday 5:00 PM CT → Friday 4:00 PM CT, with a daily 4:00–5:00 PM CT maintenance break. "
        "CME stays open on several NYSE holidays (see cme_open_nyse_closed). "
        "IBKR routes all CME products electronically via Globex — no pit sessions."
    ),
    "maintenance_break_ct": "4:00 PM – 5:00 PM CT daily (Mon–Thu)",
    "product_groups": {
        "equity_index": {
            "exchange": "CME",
            "products": ["ES", "NQ", "RTY", "YM", "MES", "MNQ"],
            "globex_hours_ct": "Sun 5:00 PM – Fri 4:00 PM",
            "hours_per_day": "~23h (maintenance break 4–5 PM CT)",
        },
        "energy": {
            "exchange": "NYMEX",
            "products": ["CL", "NG", "RB", "HO", "MCL"],
            "globex_hours_ct": "Sun 5:00 PM – Fri 4:00 PM",
            "hours_per_day": "~23h (maintenance break 4–5 PM CT)",
        },
        "metals": {
            "exchange": "COMEX",
            "products": ["GC", "SI", "HG", "PL", "PA", "MGC"],
            "globex_hours_ct": "Sun 5:00 PM – Fri 4:00 PM",
            "hours_per_day": "~23h (maintenance break 4–5 PM CT)",
        },
        "foreign_currency": {
            "exchange": "CME",
            "products": ["6E", "6J", "6B", "6A", "6C", "6S", "M6E"],
            "globex_hours_ct": "Sun 5:00 PM – Fri 4:00 PM",
            "hours_per_day": "~23h (maintenance break 4–5 PM CT)",
        },
        "interest_rates": {
            "exchange": "CBOT",
            "products": ["ZN", "ZB", "ZF", "ZT", "ZQ", "SR3"],
            "globex_hours_ct": "Sun 5:00 PM – Fri 4:00 PM",
            "hours_per_day": "~23h (maintenance break 4–5 PM CT)",
        },
        "agriculture_grains": {
            "exchange": "CBOT",
            "products": ["ZC", "ZS", "ZW", "ZO", "ZR", "KE"],
            "globex_hours_ct": "Sun 7:00 PM – Fri 1:20 PM (with 45-min break 7:45–8:30 AM CT)",
            "hours_per_day": "~17h — significantly shorter than other CME products",
            "note": "Grains close at 1:20 PM CT, not 4:00 PM. Thin liquidity after 1 PM CT.",
        },
        "softs_livestock": {
            "exchange": "CME/CBOT",
            "products": ["LE", "GF", "HE", "CC", "KC", "SB", "CT", "OJ"],
            "globex_hours_ct": "Varies by product — generally shorter than financial futures",
            "note": "Check CME product specs individually. Hours vary more than financial products.",
        },
    },
}


class SQLiteStore:
    """Persistent SQLite store for ibkr_core_mcp local data.

    Default path: ~/.ibkr_core/store.db (IBKR_SQLITE_PATH env var).
    WAL journal mode is enabled on every connection for safe concurrent reads.

    Tables:
      trades             — all Flex-synced and live-API trade executions
      flex_import_log    — SHA-256 integrity manifest for imported Flex XML files
      position_snapshots — timestamped position snapshots
      backtest_results   — vectorised backtest run history
      price_alerts       — local price alert records (separate from IBKR server alerts)
      signals            — ML/indicator signal log
      session_log        — operational event log (flex_sync, startup, errors)
      pnl_snapshots      — append-only account P&L ticks (WebSocket spl topic)

    This store is NOT the claudia.db conversation store (see ConversationStore in
    claudia_ui). It holds IBKR market and trade data only.
    """

    def __init__(self, config: Config) -> None:
        """Resolve the database path and ensure its parent directory exists, mode 0700.

        Creating the directory here (rather than at first query) means a fresh
        checkout with a default `~/.ibkr_core/` path works without manual setup.
        The database file and schema are created by `initialize()`.

        `mkdir(mode=...)` applies only to a directory this call actually creates, and it
        is masked by the umask besides — so the existing-directory case is corrected
        explicitly below. That distinction is the whole finding: the live
        `~/.ibkr_core/` was `0755` because it had been created long before anyone thought
        about its mode, and a create-time-only fix would have left it that way forever.
        The directory holds the trade store, the Flex XML archive and the Drive OAuth
        token, so 0700 is the floor.

        Args:
            config: Supplies `sqlite_path`.
        """
        self._db_path = str(config.sqlite_path)
        parent = Path(self._db_path).parent
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        _restrict(parent, 0o700)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        self._restrict_db_permissions()
        return conn

    def _restrict_db_permissions(self) -> None:
        """Hold the database and both WAL sidecars at 0600. Never raises.

        `sqlite3.connect()` creates the database with `0666 & ~umask` — 0644 in practice,
        i.e. every trade this account has ever made, world-readable. It was exactly that
        on the live store — a multi-year, tens-of-megabytes trade history — until the
        2026-08-05 claudia_ui security audit measured it.

        **`-wal` and `-shm` are not incidental.** The WAL holds committed transactions
        that have not been checkpointed yet, so it carries the same content as the
        database and is created by SQLite with the same permissive default. Securing the
        main file alone would leave the most recent writes readable.

        Called from `_connect()` rather than `initialize()` because the sidecars do not
        exist until a connection opens, and because this must be **self-healing**: the
        files already on disk predate this code, so a create-time-only fix would never
        reach them. The mode is compared before chmod'ing, so the steady-state cost is
        three `stat` calls per connection and no syscall churn.
        """
        for suffix in ("", "-wal", "-shm"):
            _restrict(Path(self._db_path + suffix), 0o600)

    def initialize(self) -> None:
        """Create all tables if they don't exist."""
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS trades (
                    execution_id TEXT PRIMARY KEY,
                    symbol       TEXT NOT NULL,
                    side         TEXT NOT NULL,
                    size         REAL NOT NULL,
                    price        REAL NOT NULL,
                    time         TEXT NOT NULL,
                    commission   REAL DEFAULT 0.0,
                    account      TEXT DEFAULT '',
                    asset_class  TEXT DEFAULT '',
                    realized_pnl REAL DEFAULT NULL
                );

                CREATE TABLE IF NOT EXISTS position_snapshots (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_at  TEXT NOT NULL,
                    conid        INTEGER,
                    symbol       TEXT NOT NULL,
                    position     REAL NOT NULL,
                    mkt_price    REAL DEFAULT 0.0,
                    mkt_value    REAL DEFAULT 0.0,
                    unrealized_pnl REAL DEFAULT 0.0
                );

                CREATE TABLE IF NOT EXISTS signals (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    logged_at   TEXT NOT NULL,
                    symbol      TEXT NOT NULL,
                    signal_type TEXT NOT NULL,
                    value       REAL,
                    metadata    TEXT
                );

                -- Migrations: add columns introduced in later versions
                -- These are no-ops when the column already exists (OperationalError is caught below)
            """)
            for col, defn in [
                ("asset_class", "TEXT DEFAULT ''"),
                ("realized_pnl", "REAL DEFAULT NULL"),
            ]:
                try:
                    conn.execute(f"ALTER TABLE trades ADD COLUMN {col} {defn}")
                except sqlite3.OperationalError:
                    pass  # column already exists
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS backtest_results (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_at        TEXT NOT NULL,
                    symbol        TEXT NOT NULL,
                    strategy_name TEXT NOT NULL,
                    total_return  REAL,
                    sharpe        REAL,
                    sortino       REAL,
                    max_drawdown  REAL,
                    num_trades    INTEGER,
                    win_rate      REAL,
                    metadata      TEXT
                );

                CREATE TABLE IF NOT EXISTS price_alerts (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    conid        INTEGER NOT NULL,
                    symbol       TEXT    NOT NULL,
                    threshold    REAL    NOT NULL,
                    direction    TEXT    NOT NULL CHECK (direction IN ('above', 'below')),
                    created_at   TEXT    NOT NULL,
                    triggered_at TEXT
                );

                CREATE TABLE IF NOT EXISTS session_log (
                    id       INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts       TEXT NOT NULL,
                    event    TEXT NOT NULL,
                    data     TEXT
                );

                -- Import manifest: one row per Flex XML file archived to Drive.
                -- source='manual'  → user-downloaded historical archive, pre-validated.
                -- source='auto'    → ClaudIA auto-sync via Flex Web Service.
                -- sha256           → SHA-256 of XML bytes at log time; used to detect
                --                    if the Drive file was modified after import.
                -- raw_trade_count  → raw <Trade> element count in the XML.
                -- trade_id_count   → unique tradeID count (== raw unless IBKR emitted
                --                    a within-file duplicate, which should never occur).
                -- verified_at      → NULL until the first successful integrity check
                --                    (all tradeIDs present in SQLite); updated on re-check.
                CREATE TABLE IF NOT EXISTS flex_import_log (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename         TEXT NOT NULL UNIQUE,
                    sha256           TEXT NOT NULL,
                    trade_id_count   INTEGER NOT NULL,
                    raw_trade_count  INTEGER NOT NULL,
                    source           TEXT NOT NULL CHECK (source IN ('manual', 'auto')),
                    imported_at      TEXT NOT NULL,
                    verified_at      TEXT
                );

                CREATE TABLE IF NOT EXISTS pnl_snapshots (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    account      TEXT NOT NULL,
                    row_type     INTEGER,
                    dpl          REAL,
                    nl           REAL,
                    upl          REAL,
                    uel          REAL,
                    mv           REAL,
                    recorded_at  TEXT NOT NULL
                );
            """)

    def upsert_trades(self, trades: list[dict[str, Any]]) -> None:
        """Insert or update trades by execution_id.

        `time` is normalised to ISO on the way in. Three paths write this table and two
        of them disagreed about the format: `flex_query` writes ISO
        (`2026-08-04T14:21:42`) while the live CP API path and the streaming path write
        IBKR's compact `20260804-14:21:42`. Because the ON CONFLICT clause below
        deliberately does not update `time` — the first observation of a fill is the
        authoritative one — a row captured live kept the compact form permanently.

        Measured on the live store 2026-08-05: 38 of 1,206 rows (3%). They were invisible
        to `get_trade_date_coverage`, which matched on the ISO shape, so the newest date
        it could report was 2026-08-04 while the table already held 2026-08-05. Normalising
        here means the read side no longer has to know that two formats ever existed.
        """
        self.initialize()
        # Ensure new optional columns exist in every row — older callers omit them
        rows = [
            {
                "asset_class": "",
                "realized_pnl": None,
                **t,
                "time": _iso_trade_time(t.get("time")),
            }
            for t in trades
        ]
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO trades
                    (execution_id, symbol, side, size, price, time, commission, account,
                     asset_class, realized_pnl)
                VALUES
                    (:execution_id, :symbol, :side, :size, :price, :time, :commission, :account,
                     :asset_class, :realized_pnl)
                ON CONFLICT(execution_id) DO UPDATE SET
                    price=excluded.price,
                    commission=excluded.commission,
                    asset_class=COALESCE(NULLIF(excluded.asset_class,''), asset_class),
                    realized_pnl=COALESCE(excluded.realized_pnl, realized_pnl)
                """,
                rows,
            )

    # ── Complete Flex archive (one table per XML element type) ─────────────────

    def initialize_flex_tables(self) -> None:
        """Create the generated flex_* tables. Idempotent.

        Separate from initialize() because these tables are generated from
        :mod:`ibkr_core_mcp.flex_schema` rather than hand-written DDL.
        """
        from .flex_store import create_flex_tables

        self.initialize()
        with self._connect() as conn:
            create_flex_tables(conn)

    def upsert_flex_statement(self, parsed: Any) -> dict[str, int]:
        """Store every element of one parsed Flex statement. Returns rows offered per tag.

        `parsed` is a :class:`ibkr_core_mcp.flex_import.ParsedStatement`. Typed as Any to
        keep this module free of an import cycle (flex_store imports flex_import, which
        imports flex_schema — none of which should import store).
        """
        from .flex_store import upsert_flex_rows

        self.initialize_flex_tables()
        written: dict[str, int] = {}
        with self._connect() as conn:
            for tag, rows in parsed.rows.items():
                written[tag] = upsert_flex_rows(conn, tag, rows)
        return written

    def upsert_flex_trades_from_live(self, records: list[dict[str, Any]]) -> int:
        """Store live Client Portal fills into flex_trade, keyed to merge with Flex later.

        A live record carries a handful of fields; the Flex statement for the same fill
        carries 85 and arrives T+1. Both derive the same ``execution_key`` from IBKR's
        exec id, so the later Flex row lands on the same row rather than creating the
        duplicate this design previously produced 75 of.
        """
        from .flex_import import live_trade_rows
        from .flex_store import upsert_flex_rows

        rows = live_trade_rows(records)
        if not rows:
            return 0
        self.initialize_flex_tables()
        with self._connect() as conn:
            return upsert_flex_rows(conn, "Trade", rows)

    # ── Flex import manifest ───────────────────────────────────────────────────

    def log_flex_import(
        self,
        filename: str,
        sha256: str,
        trade_id_count: int,
        raw_trade_count: int,
        source: str,
        imported_at: str,
        verified_at: str | None = None,
    ) -> None:
        """Insert or replace a Flex XML import record in the manifest.

        ON CONFLICT(filename) updates all fields except filename itself. The conflict
        case arises when fetch_trades is retried for the same account+date (producing
        the same filename), e.g. after a transient error or the double-start bug seen
        in session_log. Hash and counts are updated to reflect the latest fetch.

        source must be 'manual' (user-downloaded historical archive, pre-validated)
        or 'auto' (ClaudIA Flex Web Service sync).
        """
        self.initialize()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO flex_import_log
                    (filename, sha256, trade_id_count, raw_trade_count, source,
                     imported_at, verified_at)
                VALUES
                    (:filename, :sha256, :trade_id_count, :raw_trade_count, :source,
                     :imported_at, :verified_at)
                ON CONFLICT(filename) DO UPDATE SET
                    sha256          = excluded.sha256,
                    trade_id_count  = excluded.trade_id_count,
                    raw_trade_count = excluded.raw_trade_count,
                    imported_at     = excluded.imported_at,
                    verified_at     = excluded.verified_at
                """,
                {
                    "filename": filename,
                    "sha256": sha256,
                    "trade_id_count": trade_id_count,
                    "raw_trade_count": raw_trade_count,
                    "source": source,
                    "imported_at": imported_at,
                    "verified_at": verified_at,
                },
            )

    def get_flex_import_entry(self, filename: str) -> dict[str, Any] | None:
        """Return the manifest entry for a filename, or None if not yet logged."""
        self.initialize()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM flex_import_log WHERE filename = ?", (filename,)).fetchone()
        return dict(row) if row else None

    def get_flex_import_log(self) -> list[dict[str, Any]]:
        """Return all manifest entries ordered by imported_at ascending."""
        self.initialize()
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM flex_import_log ORDER BY imported_at ASC").fetchall()
        return [dict(r) for r in rows]

    def mark_flex_import_verified(self, filename: str, verified_at: str) -> None:
        """Set verified_at for a manifest entry after a successful integrity check."""
        self.initialize()
        with self._connect() as conn:
            conn.execute(
                "UPDATE flex_import_log SET verified_at = ? WHERE filename = ?",
                (verified_at, filename),
            )

    def get_all_execution_ids(self) -> set[str]:
        """Return the set of all execution_ids currently stored in the trades table.

        Used by verify_flex_import to cross-check against source XML files.
        Does not modify data.
        """
        self.initialize()
        with self._connect() as conn:
            rows = conn.execute("SELECT execution_id FROM trades").fetchall()
        return {r["execution_id"] for r in rows}

    @staticmethod
    def _settled_newest_date(conn: sqlite3.Connection) -> str | None:
        """Newest **settled** trade date — `flex_trade` rows sourced from a statement.

        None when there is no Flex dataset to ask (an older store, or one that has never
        synced), which sends the caller back to the whole-table answer. Deliberately
        excludes `source='live'`: those are the fills whose statement has not arrived, and
        counting them would mark the store current precisely when a pull is due.
        """
        try:
            row = conn.execute("SELECT MAX(trade_date_iso) FROM flex_trade WHERE source = 'flex'").fetchone()
        except sqlite3.DatabaseError:
            return None  # table absent — store predates the Flex dataset
        return str(row[0]) if row and row[0] else None

    def get_trade_date_coverage(self, gap_threshold_days: int = 45) -> dict[str, Any]:
        """Return trade activity distribution from the trades table.

        Reports the date range and periods with no recorded executions.
        This is an ACTIVITY REPORT, not an import integrity check:
        - Periods with no trades may reflect genuine inactivity (e.g. a 30-day hold)
          or missing imports — only the account holder can distinguish the two.
        - Data values are never validated or modified: IBKR is the authoritative source.
        - To verify import completeness against source XMLs, use verify_flex_import.

        **The report and the staleness flag answer two different questions, and since
        2026-08-05 they read two different things.**

        The *report* (oldest / newest / total / gaps) covers **every** row, whichever
        writer produced it. It used to match on the ISO shape alone, which silently
        excluded rows written by the live CP API and streaming paths in IBKR's compact
        format — 38 of 1,206 on the live store, so the newest date it could report was
        2026-08-04 while the table already held 2026-08-05. The sharp consequence was not
        the missing day: a window containing *only* live-captured trades would appear as a
        45+ day hole and be reported as inactivity, and ClaudIA's system prompt tells it
        that date gaps are verified inactivity. A fabricated gap would have been passed to
        the user as fact.

        The *staleness* flag deliberately still tracks **settled Flex data only**, read
        from `flex_trade` where that table exists. It decides whether to pull a statement,
        and Flex is T+1 — so today's live fill is precisely the trade whose settled record
        has *not* arrived. Letting it mark the store "current" would suppress the very pull
        that brings the settled figures. Where `flex_trade` is absent (a store predating
        the Flex dataset) it falls back to the ISO-format rows in `trades`, which is what
        the Flex importer writes and therefore the same question asked of older data.

        Returns: oldest, newest, total_trades, gaps, days_since_newest, last_trading_day,
        stale.
        """
        self.initialize()
        with self._connect() as conn:
            # S608: the only interpolation is `_TRADE_DATE_SQL`, a module-level constant
            # of literal SQL — no caller input reaches this string. Kept as a constant
            # rather than inlined so the date range, the gap scan and any future reader
            # cannot drift into understanding different subsets of the same table.
            rows = conn.execute(
                f"SELECT DISTINCT {_TRADE_DATE_SQL} AS d FROM trades WHERE d IS NOT NULL ORDER BY d"  # noqa: S608
            ).fetchall()
            total = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
            settled_newest = self._settled_newest_date(conn)

        if not rows:
            return {"oldest": None, "newest": None, "total_trades": 0, "gaps": []}

        from datetime import date, timedelta

        dates = [date.fromisoformat(r["d"]) for r in rows]
        gaps = []
        for i in range(1, len(dates)):
            delta = (dates[i] - dates[i - 1]).days
            if delta > gap_threshold_days:
                # The missing window starts the day after the last trade and ends
                # the day before the next trade — that's the exact range to request.
                fill_from = (dates[i - 1] + timedelta(days=1)).isoformat()
                fill_to = (dates[i] - timedelta(days=1)).isoformat()
                gaps.append(
                    {
                        "gap_start": dates[i - 1].isoformat(),
                        "gap_end": dates[i].isoformat(),
                        "calendar_days": delta,
                        "request_from": fill_from,
                        "request_to": fill_to,
                    }
                )

        newest = dates[-1]
        days_since_newest = (date.today() - newest).days
        # Staleness asks about SETTLED data only (see the docstring). Falling back to the
        # report's own newest keeps the old behaviour for stores with no Flex dataset.
        settled = date.fromisoformat(settled_newest) if settled_newest else newest

        try:
            import exchange_calendars as ec
            from pandas import Timestamp

            _cal = ec.get_calendar("XNYS")
            last_trading_day = _cal.previous_close(Timestamp.now(tz="UTC")).date()
            # Flex publishes yesterday's trades today — newest == yesterday is always normal.
            # Only flag stale when data is 2+ trading days behind (genuine gap, not Flex lag).
            penultimate_trading_day = _cal.previous_close(Timestamp(last_trading_day.isoformat(), tz="UTC")).date()
            stale = settled < penultimate_trading_day
        except Exception:
            # Fallback: stale if missing more than 2 calendar days (covers weekends)
            last_trading_day = None
            stale = (date.today() - settled).days > 2

        return {
            "oldest": dates[0].isoformat(),
            "newest": newest.isoformat(),
            "days_since_newest": days_since_newest,
            "last_trading_day": last_trading_day.isoformat() if last_trading_day else None,
            "stale": stale,
            "total_trades": total,
            "gaps": gaps,
        }

    @staticmethod
    def get_market_calendar_context(
        exchanges: list[str] | None = None,
    ) -> dict[str, Any]:
        """Return trading calendar context for one or more exchanges.

        Covers the full current year (past + future) plus the next calendar year,
        giving complete holiday visibility with minimal data (~10-15 holidays/exchange/year).

        Default: 20 exchanges covering full G20 + Eurex (XNYS, CME, XLON, XETR, XEUR,
        XPAR, XMIL, XTKS, XHKG, XSHG, XBOM, XKRX, XASX, XTSE, BVMF, XMEX, XJSE,
        XSAU, XIDX, XIST). Pass a custom list to restrict to a subset.

        Uses the exchange_calendars library (MIC codes, not IBKR venue codes).
        Process-level cache keyed by (today's date, tuple of exchange codes): first
        call per day is ~3.4s (numpy array loading for 20 exchanges); subsequent calls
        are ~0.01ms. Cache auto-invalidates at midnight (new date = new cache key).

        CME futures schedule injected from _FUTURES_SCHEDULE (static, CT hours).
        cme_open_nyse_closed: computed dynamically — CME sessions where NYSE is closed
        (MLK Day, Presidents Day, Memorial Day, Juneteenth, Labor Day, etc.).

        Source (exchange_calendars library): https://github.com/gerrymanoim/exchange_calendars
        Source (CME product hours): https://www.cmegroup.com/trading-hours.html
        """
        if exchanges is None:
            # Full G20 coverage + Eurex futures. Excludes Russia (XMOS — IBKR
            # suspended most Russian securities since 2022 sanctions) and
            # Argentina (XBUE — capital controls, very limited IBKR access).
            # Saudi Arabia (XSAU) trades Sun–Thu; Fridays appear as "holidays"
            # from a Mon–Fri perspective — this is correct, not a data error.
            exchanges = [
                # US
                "XNYS",
                "CME",
                # Europe — equities + Eurex derivatives
                "XLON",
                "XETR",
                "XEUR",
                "XPAR",
                "XMIL",
                # Asia-Pacific
                "XTKS",
                "XHKG",
                "XSHG",
                "XBOM",
                "XKRX",
                "XASX",
                # Americas (ex-US)
                "XTSE",
                "BVMF",
                "XMEX",
                # Africa / Middle East
                "XJSE",
                "XSAU",
                # Other G20
                "XIDX",
                "XIST",
            ]
        try:
            from datetime import date as _date

            _cache_key = (_date.today().isoformat(), tuple(exchanges))
            if _cache_key in _market_calendar_cache:
                return _market_calendar_cache[_cache_key]

            from datetime import date, timedelta

            import exchange_calendars as ec
            from pandas import Timestamp

            now = Timestamp.now(tz="UTC")
            today = date.today()
            year_start = date(today.year, 1, 1)
            year_end = date(today.year + 1, 12, 31)

            primary = ec.get_calendar(exchanges[0])
            last_td = primary.previous_close(now).date()
            next_td = primary.next_open(now).date()
            is_trading_day = bool(primary.is_session(Timestamp(today)))

            # Build all weekdays in current year + next year
            all_weekdays = {
                year_start + timedelta(days=i)
                for i in range((year_end - year_start).days + 1)
                if (year_start + timedelta(days=i)).weekday() < 5
            }

            import contextlib

            holidays_by_exchange: dict[str, list[str]] = {}
            for xcode in exchanges:
                with contextlib.suppress(Exception):
                    cal = ec.get_calendar(xcode)
                    # Cap end to calendar's precomputed range (~1 year from today)
                    cal_end = min(year_end, cal.last_session.date())
                    cal_start = max(year_start, cal.first_session.date())
                    sessions = set(cal.sessions_in_range(Timestamp(cal_start), Timestamp(cal_end)).date)
                    weekdays_in_range = {d for d in all_weekdays if cal_start <= d <= cal_end}
                    holidays_by_exchange[xcode] = sorted(d.isoformat() for d in (weekdays_in_range - sessions))

            # Days CME trades when NYSE is closed — futures keep going on equity holidays
            cme_extra: list[str] = []
            with contextlib.suppress(Exception):
                cme_cal = ec.get_calendar("CME")
                nyse_cal = ec.get_calendar("XNYS")
                cme_cap = min(year_end, cme_cal.last_session.date())
                nyse_cap = min(year_end, nyse_cal.last_session.date())
                range_cap = min(cme_cap, nyse_cap)
                cme_sessions = set(cme_cal.sessions_in_range(Timestamp(year_start), Timestamp(range_cap)).date)
                nyse_sessions = set(nyse_cal.sessions_in_range(Timestamp(year_start), Timestamp(range_cap)).date)
                cme_extra = sorted(d.isoformat() for d in (cme_sessions - nyse_sessions))

            result = {
                "today": today.isoformat(),
                "is_trading_day": is_trading_day,
                "last_trading_day": last_td.isoformat(),
                "next_trading_day": next_td.isoformat(),
                "primary_exchange": exchanges[0],
                "holidays_by_exchange": holidays_by_exchange,
                "futures": _FUTURES_SCHEDULE | {"cme_open_nyse_closed": cme_extra},
            }
            _market_calendar_cache[_cache_key] = result
            return result
        except Exception:
            return {}

    _ALLOWED_TIME_COLS = frozenset({"time", "snapshot_at", "logged_at"})

    @staticmethod
    def _apply_filters(
        query: str,
        params: list[Any],
        symbol: str | None,
        start: str | None,
        end: str | None,
        time_col: str,
    ) -> tuple[str, list[Any]]:
        if time_col not in SQLiteStore._ALLOWED_TIME_COLS:
            raise ValueError(f"Invalid time_col {time_col!r}. Allowed: {sorted(SQLiteStore._ALLOWED_TIME_COLS)}")
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol.upper())
        if start:
            query += f" AND {time_col} >= ?"
            params.append(start)
        if end:
            query += f" AND {time_col} <= ?"
            params.append(end)
        return query, params

    def get_trades(
        self,
        symbol: str | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return trades, optionally filtered by symbol and date range."""
        self.initialize()
        query, params = self._apply_filters("SELECT * FROM trades WHERE 1=1", [], symbol, start, end, "time")
        query += " ORDER BY time DESC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def snapshot_positions(self, positions: list[dict[str, Any]]) -> None:
        """Save a timestamped snapshot of current positions."""
        self.initialize()
        now = datetime.now(tz=UTC).isoformat()
        rows = [
            {
                "snapshot_at": now,
                "conid": p.get("conid"),
                "symbol": p.get("symbol", ""),
                "position": p.get("position", 0.0),
                "mkt_price": p.get("mktPrice", 0.0),
                "mkt_value": p.get("mktValue", 0.0),
                "unrealized_pnl": p.get("unrealizedPnl", 0.0),
            }
            for p in positions
        ]
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO position_snapshots
                    (snapshot_at, conid, symbol, position, mkt_price, mkt_value, unrealized_pnl)
                VALUES
                    (:snapshot_at, :conid, :symbol, :position, :mkt_price, :mkt_value, :unrealized_pnl)
                """,
                rows,
            )

    def record_pnl_snapshot(
        self,
        account: str,
        row_type: int | None,
        dpl: float | None,
        nl: float | None,
        upl: float | None,
        uel: float | None,
        mv: float | None,
    ) -> None:
        """Insert one P&L snapshot row. Called once per WS spl tick — append-only, no dedup."""
        self.initialize()
        now = datetime.now(tz=UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO pnl_snapshots (account, row_type, dpl, nl, upl, uel, mv, recorded_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (account, row_type, dpl, nl, upl, uel, mv, now),
            )

    def get_latest_pnl(self, account: str | None = None) -> dict[str, Any] | None:
        """Most recent P&L snapshot, optionally filtered by account. None if never recorded
        (e.g. server never started with --stream)."""
        self.initialize()
        query = "SELECT * FROM pnl_snapshots"
        params: list[Any] = []
        if account:
            query += " WHERE account = ?"
            params.append(account)
        query += " ORDER BY recorded_at DESC, id DESC LIMIT 1"
        with self._connect() as conn:
            row = conn.execute(query, params).fetchone()
        return dict(row) if row else None

    def get_position_history(
        self,
        symbol: str | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> pd.DataFrame:
        """Return position snapshot history as DataFrame."""
        self.initialize()
        query, params = self._apply_filters(
            "SELECT * FROM position_snapshots WHERE 1=1", [], symbol, start, end, "snapshot_at"
        )
        query += " ORDER BY snapshot_at"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        if not rows:
            return pd.DataFrame(
                columns=["id", "snapshot_at", "conid", "symbol", "position", "mkt_price", "mkt_value", "unrealized_pnl"]
            )
        return pd.DataFrame([dict(r) for r in rows])

    def log_signal(
        self,
        symbol: str,
        signal_type: str,
        value: float,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record a signal (from ML model, scanner, or indicator)."""
        self.initialize()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO signals (logged_at, symbol, signal_type, value, metadata)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    datetime.now(tz=UTC).isoformat(),
                    symbol.upper(),
                    signal_type,
                    value,
                    json.dumps(metadata) if metadata else None,
                ),
            )

    def get_signals(
        self,
        symbol: str | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> pd.DataFrame:
        """Return logged signals as DataFrame, optionally filtered by symbol and date range.

        Returns an empty DataFrame with the correct schema if no rows match.
        Sorted ascending by logged_at.
        """
        self.initialize()
        query, params = self._apply_filters("SELECT * FROM signals WHERE 1=1", [], symbol, start, end, "logged_at")
        query += " ORDER BY logged_at"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        if not rows:
            return pd.DataFrame(columns=["id", "logged_at", "symbol", "signal_type", "value", "metadata"])
        return pd.DataFrame([dict(r) for r in rows])

    def save_backtest(self, result: dict[str, Any]) -> int:
        """Store a backtest result dict[str, Any]. Returns row id."""
        self.initialize()
        now = datetime.now(tz=UTC).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO backtest_results
                    (run_at, symbol, strategy_name, total_return, sharpe, sortino,
                     max_drawdown, num_trades, win_rate, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now,
                    result.get("symbol", ""),
                    result.get("strategy_name", ""),
                    result.get("total_return"),
                    result.get("sharpe"),
                    result.get("sortino"),
                    result.get("max_drawdown"),
                    result.get("num_trades"),
                    result.get("win_rate"),
                    json.dumps(result.get("metadata")) if result.get("metadata") else None,
                ),
            )
            return cursor.lastrowid or 0

    def get_backtests(self, symbol: str | None = None, strategy: str | None = None) -> list[dict[str, Any]]:
        """Return backtest results, optionally filtered by symbol and strategy name.

        Results are sorted by run_at descending (most recent first).
        """
        self.initialize()
        query = "SELECT * FROM backtest_results WHERE 1=1"
        params: list[Any] = []
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol.upper())
        if strategy:
            query += " AND strategy_name = ?"
            params.append(strategy)
        query += " ORDER BY run_at DESC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def add_alert(self, conid: int, symbol: str, threshold: float, direction: str) -> int:
        """Insert a price alert. direction must be 'above' or 'below'. Returns new id."""
        if direction not in ("above", "below"):
            raise ValueError(f"direction must be 'above' or 'below', got {direction!r}")
        self.initialize()
        now = datetime.now(tz=UTC).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO price_alerts (conid, symbol, threshold, direction, created_at) VALUES (?, ?, ?, ?, ?)",
                (conid, symbol.upper(), threshold, direction, now),
            )
            return cur.lastrowid or 0

    def get_alerts(self, active_only: bool = True) -> list[dict[str, Any]]:
        """Return alerts; active_only=True excludes already-triggered alerts."""
        self.initialize()
        query = "SELECT * FROM price_alerts"
        if active_only:
            query += " WHERE triggered_at IS NULL"
        query += " ORDER BY created_at DESC"
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(query).fetchall()]

    def log_entry(self, event: str, **data: Any) -> None:
        """Append an event to the local session_log table."""
        self.initialize()
        now = datetime.now(tz=UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO session_log (ts, event, data) VALUES (?, ?, ?)",
                (now, event, json.dumps(data) if data else None),
            )

    def get_log(self, n: int = 100, event: str | None = None) -> list[dict[str, Any]]:
        """Return the last n session log entries, optionally filtered by event name."""
        self.initialize()
        query = "SELECT * FROM session_log"
        params: list[Any] = []
        if event:
            query += " WHERE event = ?"
            params.append(event)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(n)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in reversed(rows)]

    def mark_alert_triggered(self, alert_id: int) -> None:
        """Record that an alert fired by setting triggered_at to now."""
        self.initialize()
        now = datetime.now(tz=UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE price_alerts SET triggered_at = ? WHERE id = ?",
                (now, alert_id),
            )
