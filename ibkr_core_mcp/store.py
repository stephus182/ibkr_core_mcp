from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from ibkr_core_mcp.config import Config

# Process-level cache for market calendar context.
# Key: (date_str, tuple(exchange_codes)) — recomputed only when the date changes.
_market_calendar_cache: dict[tuple[str, tuple[str, ...]], dict[str, Any]] = {}

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
    """Persistent SQLite store for trades, position snapshots, and signals."""

    def __init__(self, config: Config) -> None:
        self._db_path = str(config.sqlite_path)
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

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
            """)

    def upsert_trades(self, trades: list[dict[str, Any]]) -> None:
        """Insert or update trades by execution_id."""
        self.initialize()
        # Ensure new optional columns exist in every row — older callers omit them
        rows = [
            {
                "asset_class": "",
                "realized_pnl": None,
                **t,
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

    def get_trade_date_coverage(self, gap_threshold_days: int = 45) -> dict[str, Any]:
        """Return coverage stats and actionable gaps in the trades table.

        A gap is a period longer than gap_threshold_days with no trades. Gaps this
        large almost certainly represent missing imports rather than inactivity.
        Each gap entry includes the exact date range to request from IBKR.
        Returns: oldest, newest, total_trades, gaps.
        """
        self.initialize()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT substr(time, 1, 10) as d FROM trades WHERE time LIKE '____-__-__%' ORDER BY d"
            ).fetchall()
            total = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]

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
                gaps.append({
                    "gap_start": dates[i - 1].isoformat(),
                    "gap_end": dates[i].isoformat(),
                    "calendar_days": delta,
                    "request_from": fill_from,
                    "request_to": fill_to,
                })

        newest = dates[-1]
        days_since_newest = (date.today() - newest).days

        try:
            import exchange_calendars as ec
            from pandas import Timestamp
            _cal = ec.get_calendar("XNYS")
            last_trading_day = _cal.previous_close(Timestamp.now(tz="UTC")).date()
            stale = newest < last_trading_day
        except Exception:
            # Fallback: stale if missing more than 1 calendar day
            last_trading_day = None
            stale = days_since_newest > 1

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

        Default exchanges: NYSE (XNYS) and CME (XCME) — covers US equities and futures.
        Pass additional exchange codes for international coverage
        (XLON=LSE, XTOK=Tokyo, XASX=Sydney, XETR=Frankfurt, XHKG=Hong Kong, XTSE=Toronto…).
        """
        if exchanges is None:
            # Full G20 coverage + Eurex futures. Excludes Russia (XMOS — IBKR
            # suspended most Russian securities since 2022 sanctions) and
            # Argentina (XBUE — capital controls, very limited IBKR access).
            # Saudi Arabia (XSAU) trades Sun–Thu; Fridays appear as "holidays"
            # from a Mon–Fri perspective — this is correct, not a data error.
            exchanges = [
                # US
                "XNYS", "CME",
                # Europe — equities + Eurex derivatives
                "XLON", "XETR", "XEUR", "XPAR", "XMIL",
                # Asia-Pacific
                "XTKS", "XHKG", "XSHG", "XBOM", "XKRX", "XASX",
                # Americas (ex-US)
                "XTSE", "BVMF", "XMEX",
                # Africa / Middle East
                "XJSE", "XSAU",
                # Other G20
                "XIDX", "XIST",
            ]
        try:
            from datetime import date as _date
            _cache_key = (_date.today().isoformat(), tuple(exchanges))
            if _cache_key in _market_calendar_cache:
                return _market_calendar_cache[_cache_key]

            import exchange_calendars as ec
            from pandas import Timestamp
            from datetime import date, timedelta

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
                    sessions = set(
                        cal.sessions_in_range(Timestamp(cal_start), Timestamp(cal_end)).date
                    )
                    weekdays_in_range = {
                        d for d in all_weekdays if cal_start <= d <= cal_end
                    }
                    holidays_by_exchange[xcode] = sorted(
                        d.isoformat() for d in (weekdays_in_range - sessions)
                    )

            # Days CME trades when NYSE is closed — futures keep going on equity holidays
            cme_extra: list[str] = []
            with contextlib.suppress(Exception):
                cme_cal = ec.get_calendar("CME")
                nyse_cal = ec.get_calendar("XNYS")
                cme_cap = min(year_end, cme_cal.last_session.date())
                nyse_cap = min(year_end, nyse_cal.last_session.date())
                range_cap = min(cme_cap, nyse_cap)
                cme_sessions = set(
                    cme_cal.sessions_in_range(Timestamp(year_start), Timestamp(range_cap)).date
                )
                nyse_sessions = set(
                    nyse_cal.sessions_in_range(Timestamp(year_start), Timestamp(range_cap)).date
                )
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

    @staticmethod
    def _apply_filters(
        query: str,
        params: list[Any],
        symbol: str | None,
        start: str | None,
        end: str | None,
        time_col: str,
    ) -> tuple[str, list[Any]]:
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
        query, params = self._apply_filters(
            "SELECT * FROM trades WHERE 1=1", [], symbol, start, end, "time"
        )
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
                columns=["id", "snapshot_at", "conid", "symbol", "position",
                         "mkt_price", "mkt_value", "unrealized_pnl"]
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
        self.initialize()
        query, params = self._apply_filters(
            "SELECT * FROM signals WHERE 1=1", [], symbol, start, end, "logged_at"
        )
        query += " ORDER BY logged_at"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        if not rows:
            return pd.DataFrame(
                columns=["id", "logged_at", "symbol", "signal_type", "value", "metadata"]
            )
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

    def get_backtests(
        self, symbol: str | None = None, strategy: str | None = None
    ) -> list[dict[str, Any]]:
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
                "INSERT INTO price_alerts (conid, symbol, threshold, direction, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
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
