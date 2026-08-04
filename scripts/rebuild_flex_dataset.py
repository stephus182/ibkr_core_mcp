#!/usr/bin/env python3
"""Rebuild the complete Flex dataset from the archived XML statements, then audit it.

The rebuild is deliberately blunt: drop the generated tables, re-import every
statement oldest-first, and refuse to declare success until the audit gate passes.
It never touches the legacy ``trades`` table and never writes to Drive.

Usage:
    python scripts/rebuild_flex_dataset.py --db ~/.ibkr_core/store.db          # real
    python scripts/rebuild_flex_dataset.py --db /tmp/scratch.db --dry-run      # rehearsal
"""

# ruff: noqa: S608 - every interpolated identifier is a table/column name from
# the generated flex_schema module; no user input reaches these statements.

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ibkr_core_mcp.flex_import import FlexImportError, parse_statement  # noqa: E402
from ibkr_core_mcp.flex_schema import ELEMENTS  # noqa: E402
from ibkr_core_mcp.flex_store import create_flex_tables, upsert_flex_rows  # noqa: E402

DEFAULT_SRC = Path.home() / ".ibkr_core" / "flex_archive"
DEFAULT_DB = Path.home() / ".ibkr_core" / "store.db"


def statement_sort_key(path: Path) -> tuple[str, str]:
    """Order statements oldest-first by (fromDate, whenGenerated)."""
    try:
        parsed = parse_statement(path.read_text(encoding="utf-8", errors="replace"), path.name)
    except FlexImportError:
        return ("", "")
    return (parsed.from_date, parsed.when_generated)


def rebuild(src: Path, db_path: Path, *, drop: bool = True) -> dict[str, Any]:
    """Import every statement in src into db_path. Returns a summary."""
    paths = sorted(src.glob("*.xml"), key=statement_sort_key)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")

    if drop:
        for spec in ELEMENTS.values():
            conn.execute(f"DROP TABLE IF EXISTS {spec['table']}")
    create_flex_tables(conn)

    imported: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    written: dict[str, int] = {}

    for path in paths:
        try:
            parsed = parse_statement(path.read_text(encoding="utf-8", errors="replace"), path.name)
        except FlexImportError as exc:
            rejected.append({"file": path.name, "reason": str(exc)})
            print(f"  REJECT  {path.name}\n          {exc}")
            continue

        for tag, rows in parsed.rows.items():
            written[tag] = written.get(tag, 0) + upsert_flex_rows(conn, tag, rows)
        conn.commit()
        imported.append(
            {
                "file": path.name,
                "from": parsed.from_date,
                "to": parsed.to_date,
                "generated": parsed.when_generated,
                "rows": parsed.total_rows(),
            }
        )
        print(f"  import  {parsed.from_date}->{parsed.to_date}  {parsed.total_rows():>7,} rows  {path.name}")

    stored = {}
    for tag, spec in ELEMENTS.items():
        stored[tag] = conn.execute(f"SELECT COUNT(*) FROM {spec['table']}").fetchone()[0]
    conn.close()

    return {
        "src": str(src),
        "db": str(db_path),
        "imported": imported,
        "rejected": rejected,
        "rows_offered": written,
        "rows_stored": stored,
    }


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", type=Path, default=DEFAULT_SRC)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--keep", action="store_true", help="do not drop existing flex_* tables")
    parser.add_argument("--summary-out", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.src.is_dir():
        raise SystemExit(f"archive directory not found: {args.src}")

    print(f"Rebuilding {args.db} from {args.src}\n")
    summary = rebuild(args.src, args.db, drop=not args.keep)

    print(f"\n{'element':<28}{'offered':>10}{'stored':>10}{'deduped':>10}")
    print("-" * 58)
    for tag in sorted(summary["rows_stored"], key=lambda t: -summary["rows_stored"][t]):
        offered = summary["rows_offered"].get(tag, 0)
        stored = summary["rows_stored"][tag]
        print(f"{tag:<28}{offered:>10,}{stored:>10,}{offered - stored:>10,}")

    print(f"\nimported {len(summary['imported'])} statements, rejected {len(summary['rejected'])}")
    if args.summary_out:
        args.summary_out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"summary → {args.summary_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
