from __future__ import annotations
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ibkr_core_mcp.config import Config
from ibkr_core_mcp.exceptions import StoreError


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
                    account      TEXT DEFAULT ''
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
            """)

    def upsert_trades(self, trades: list[dict]) -> None:
        """Insert or update trades by execution_id."""
        self.initialize()
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO trades
                    (execution_id, symbol, side, size, price, time, commission, account)
                VALUES
                    (:execution_id, :symbol, :side, :size, :price, :time, :commission, :account)
                ON CONFLICT(execution_id) DO UPDATE SET
                    price=excluded.price,
                    commission=excluded.commission
                """,
                trades,
            )

    def get_trades(
        self,
        symbol: str | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> list[dict]:
        """Return trades, optionally filtered by symbol and date range."""
        self.initialize()
        query = "SELECT * FROM trades WHERE 1=1"
        params: list[Any] = []
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol.upper())
        if start:
            query += " AND time >= ?"
            params.append(start)
        if end:
            query += " AND time <= ?"
            params.append(end)
        query += " ORDER BY time DESC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def snapshot_positions(self, positions: list[dict]) -> None:
        """Save a timestamped snapshot of current positions."""
        self.initialize()
        now = datetime.now(tz=timezone.utc).isoformat()
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
        query = "SELECT * FROM position_snapshots WHERE 1=1"
        params: list[Any] = []
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol.upper())
        if start:
            query += " AND snapshot_at >= ?"
            params.append(start)
        if end:
            query += " AND snapshot_at <= ?"
            params.append(end)
        query += " ORDER BY snapshot_at"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return pd.DataFrame([dict(r) for r in rows])

    def log_signal(
        self,
        symbol: str,
        signal_type: str,
        value: float,
        metadata: dict | None = None,
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
                    datetime.now(tz=timezone.utc).isoformat(),
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
        query = "SELECT * FROM signals WHERE 1=1"
        params: list[Any] = []
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol.upper())
        if start:
            query += " AND logged_at >= ?"
            params.append(start)
        if end:
            query += " AND logged_at <= ?"
            params.append(end)
        query += " ORDER BY logged_at"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return pd.DataFrame([dict(r) for r in rows])

    def save_backtest(self, result: dict) -> int:
        """Store a backtest result dict. Returns row id."""
        self.initialize()
        now = datetime.now(tz=timezone.utc).isoformat()
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
    ) -> list[dict]:
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
