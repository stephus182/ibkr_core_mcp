"""SQLite persistence for the complete Flex statement archive.

One table per XML element type, one column per attribute — the DDL is generated from
:mod:`ibkr_core_mcp.flex_schema`, which is itself generated from the statements. No
column list is written by hand anywhere in this path, which is what makes "every
attribute IBKR emits has a home" checkable rather than aspirational.

Conflict handling differs by table, deliberately:

``flex_trade``
    Keyed on ``execution_key`` so the live Client Portal view and the Flex view of one
    fill converge. On conflict the row with the **later** ``stmt_when_generated`` wins,
    so the result does not depend on import order. IBKR does restate: across the
    archive, ``rtn`` differs for 102 trades and ``cost`` for one. ``fifoPnlRealized``
    never differs, which is why realised P&L is safe to aggregate.

everything else
    Keyed on ``row_uid`` (content hash + intra-statement occurrence index). A conflict
    means byte-identical content already stored, so there is nothing to update.
"""

# ruff: noqa: S608 - every interpolated identifier is a table/column name from
# the generated flex_schema module; no user input reaches these statements.

from __future__ import annotations

import sqlite3
from typing import Any

from .flex_import import DERIVED_COLUMNS, META_COLUMNS
from .flex_schema import ELEMENTS

__all__ = [
    "FLEX_TABLES",
    "create_flex_tables",
    "flex_table_ddl",
    "table_columns",
    "upsert_flex_rows",
]

FLEX_TABLES: dict[str, str] = {tag: spec["table"] for tag, spec in ELEMENTS.items()}

# Columns worth an index, where present. Query patterns: bucket by trading day,
# filter by instrument, reconcile by identifier.
#
# `src_file` is deliberately NOT indexed: it is provenance, not a query predicate, and
# indexing it on flex_conversion_rate alone cost 3.8 MB — more than the entire trades
# table. Provenance is still stored on every row, just not indexed.
_INDEXED = ("trade_date_iso", "trade_date", "report_date", "symbol", "conid", "asset_category")

# Tables large enough that a per-row index is a real cost. ConversionRate is 80k rows of
# FX reference data — four attributes, repeated across every statement — and accounts for
# most of the database. It gets no secondary indexes; look-ups go through the primary key.
_UNINDEXED_TABLES = {"flex_conversion_rate"}


def table_columns(tag: str) -> dict[str, str]:
    """Return {column_name: sql_type} for one element's table, in DDL order.

    Raises ValueError if an XML attribute would land on a reserved column name. That
    cannot happen with IBKR's current 222 attribute names, but `setdefault` would have
    resolved such a clash *silently* — the attribute's values would vanish into a meta
    column and the schema-completeness audit would still pass, because the column exists.
    A future IBKR field called `source` is exactly the kind of thing this project has
    already been bitten by once.
    """
    spec = ELEMENTS[tag]
    columns: dict[str, str] = {}
    # Key first, then provenance/meta, then derived, then every XML attribute.
    columns[spec["key"]] = "TEXT NOT NULL"
    if spec["key"] != "row_uid":
        columns["row_uid"] = "TEXT NOT NULL"
    columns.update(META_COLUMNS)
    columns.update(DERIVED_COLUMNS.get(tag, {}))
    reserved = set(columns)

    for attr, (column, sql_type) in spec["columns"].items():
        if column in reserved:
            raise ValueError(
                f"<{tag}> attribute {attr!r} maps to reserved column {column!r}. "
                f"Rename the derived/meta column in flex_import.py — do not let the "
                f"attribute be absorbed silently."
            )
        columns[column] = sql_type
    return columns


def flex_table_ddl(tag: str) -> list[str]:
    """Return the CREATE TABLE + CREATE INDEX statements for one element type."""
    spec = ELEMENTS[tag]
    table = spec["table"]
    key = spec["key"]
    columns = table_columns(tag)

    body = [f"    {name} {sql_type}" for name, sql_type in columns.items()]
    body.append(f"    PRIMARY KEY ({key})")
    statements = [f"CREATE TABLE IF NOT EXISTS {table} (\n" + ",\n".join(body) + "\n)"]

    if tag == "Trade":
        # 1:1 with execution_key in the whole archive; a violation means two different
        # executions claimed one IBKR tradeID, which is worth failing loudly on.
        statements.append(  # noqa: S608 - identifiers come from the generated schema
            f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{table}_trade_id ON {table}(trade_id)"
        )
        statements.append(f"CREATE INDEX IF NOT EXISTS idx_{table}_ib_exec_id ON {table}(ib_exec_id)")
    if table not in _UNINDEXED_TABLES:
        for column in _INDEXED:
            if column in columns:
                statements.append(f"CREATE INDEX IF NOT EXISTS idx_{table}_{column} ON {table}({column})")
    return statements


def create_flex_tables(conn: sqlite3.Connection) -> None:
    """Create every Flex archive table and index. Idempotent."""
    for tag in ELEMENTS:
        for statement in flex_table_ddl(tag):
            conn.execute(statement)


def upsert_flex_rows(conn: sqlite3.Connection, tag: str, rows: list[dict[str, Any]]) -> int:
    """Insert rows for one element type. Returns the number of rows written.

    Missing columns are an error rather than a silent NULL: the parser and the schema
    are generated from the same source, so a mismatch means one of them drifted.
    """
    if not rows:
        return 0
    spec = ELEMENTS[tag]
    table = spec["table"]
    key = spec["key"]
    columns = list(table_columns(tag))

    missing = set(columns) - set(rows[0])
    if missing:
        raise ValueError(f"{table}: parser produced no value for {sorted(missing)} — schema drift")

    placeholders = ", ".join(f":{name}" for name in columns)
    column_list = ", ".join(columns)

    if tag == "Trade":
        # Later-generated statement wins, so import order cannot change the outcome.
        #
        # COALESCE on the *stored* side is load-bearing, not defensive: a live Client
        # Portal fill is stored with stmt_when_generated = NULL, and `'20260804;…' >= NULL`
        # is NULL, not true. Without the COALESCE the T+1 Flex statement would never
        # overwrite the live placeholder and the row would keep 5 fields instead of 85.
        #
        # The reverse stays correctly blocked: a live row arriving after Flex compares
        # NULL >= '20260804;…', which is NULL, so it cannot clobber the richer row.
        updatable = [c for c in columns if c != key]
        assignments = ", ".join(f"{c}=excluded.{c}" for c in updatable)
        sql = (
            f"INSERT INTO {table} ({column_list}) VALUES ({placeholders}) "
            f"ON CONFLICT({key}) DO UPDATE SET {assignments} "
            f"WHERE excluded.stmt_when_generated >= COALESCE({table}.stmt_when_generated, '')"
        )
    else:
        sql = f"INSERT INTO {table} ({column_list}) VALUES ({placeholders}) ON CONFLICT({key}) DO NOTHING"

    payload = [{name: row.get(name) for name in columns} for row in rows]
    conn.executemany(sql, payload)
    return len(payload)
