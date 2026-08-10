#!/usr/bin/env python3
"""Rebuild the complete Flex dataset from the archived XML statements, then audit it.

The rebuild is deliberately blunt: drop the generated tables, re-import every
statement oldest-first, and refuse to declare success until the audit gate passes.
It never touches the legacy ``trades`` table and never writes to Drive.

**Everything is proven before anything is destroyed.** A pre-flight parses every
statement first; if the archive is empty, holds an unparseable file, or the database
holds live Client-Portal rows that the archive cannot reproduce, the run refuses
*before* the first ``DROP``. This ordering is the whole point: a check that runs after
the drop is a post-mortem, not a gate. Until 2026-08-10 there was no gate at all —
``main()`` ended in an unconditional ``return 0``, so a run in which every statement was
rejected erased six years of history and reported success to any caller checking ``$?``.

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
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from audit_flex_dataset import run_gate  # noqa: E402

from ibkr_core_mcp.flex_import import FlexImportError, ParsedStatement, parse_statement  # noqa: E402
from ibkr_core_mcp.flex_schema import ELEMENTS  # noqa: E402
from ibkr_core_mcp.flex_store import create_flex_tables, upsert_flex_rows  # noqa: E402

DEFAULT_SRC = Path.home() / ".ibkr_core" / "flex_archive"
DEFAULT_DB = Path.home() / ".ibkr_core" / "store.db"


class RebuildRefused(Exception):
    """The rebuild stopped before running any destructive statement.

    Always raised from the pre-flight, never mid-import: by contract, catching this
    means the database is exactly as it was before the call.
    """


@dataclass(frozen=True)
class Preflight:
    """The archive, parsed once, with its failures kept rather than discarded."""

    statements: list[ParsedStatement]
    unparseable: list[tuple[Path, str]]
    files_seen: int


def preflight(src: Path) -> Preflight:
    """Parse every statement in `src` once, oldest-first, keeping the failures.

    The previous implementation parsed each file twice — once inside the sort key,
    which threw the whole `ParsedStatement` away to keep two strings, and once for the
    import. Worse, a file that failed to parse sorted to `("", "")`, i.e. *first*,
    quietly breaking the oldest-first ordering that `upsert_flex_rows`' "later-generated
    statement wins" rule depends on.
    """
    parsed: list[ParsedStatement] = []
    unparseable: list[tuple[Path, str]] = []
    paths = sorted(src.glob("*.xml"))

    for path in paths:
        try:
            parsed.append(parse_statement(path.read_text(encoding="utf-8", errors="replace"), path.name))
        except FlexImportError as exc:
            unparseable.append((path, str(exc)))

    parsed.sort(key=lambda p: (p.from_date, p.when_generated))
    return Preflight(statements=parsed, unparseable=unparseable, files_seen=len(paths))


def live_row_count(db_path: Path) -> int:
    """Count Client-Portal rows in flex_trade that no XML statement can reproduce.

    A live row is written by `SQLiteStore.upsert_flex_trades_from_live` the moment a
    fill is seen, and is enriched by its Flex statement T+1. Between those two events
    the row exists in the database and nowhere else — dropping the table destroys it
    permanently. Returns 0 if the table does not exist yet.
    """
    if not db_path.exists():
        return 0
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM flex_trade WHERE source='live'").fetchone()[0])
    except sqlite3.DatabaseError:
        return 0  # table absent — nothing to lose
    finally:
        conn.close()


def check_preflight(pre: Preflight, db_path: Path, *, drop: bool, drop_live: bool) -> None:
    """Raise :class:`RebuildRefused` unless it is safe to destroy and rebuild."""
    if pre.files_seen == 0:
        raise RebuildRefused(
            "archive holds no .xml statements — refusing to rebuild from nothing. "
            "Run scripts/fetch_flex_archive.py first."
        )

    if pre.unparseable:
        lines = "\n".join(f"    {path.name}: {reason}" for path, reason in pre.unparseable)
        raise RebuildRefused(
            f"{len(pre.unparseable)} of {pre.files_seen} statement(s) could not be parsed. "
            f"Rebuilding would silently shrink the dataset by whatever they contain:\n{lines}\n"
            "  Remove or re-fetch them, then re-run. There is deliberately no override."
        )

    if drop and not drop_live:
        live = live_row_count(db_path)
        if live:
            raise RebuildRefused(
                f"{live} live Client-Portal row(s) in flex_trade are not yet in any statement "
                "and cannot be re-imported from the archive. Run sync_flex_trades to let the "
                "T+1 statement absorb them, or pass --drop-live to discard them."
            )


def backup_database(db_path: Path) -> Path | None:
    """Snapshot the database beside itself, before anything is dropped.

    Returns the backup path, or None if there was no database to back up. Uses SQLite's
    own online-backup API rather than a file copy so a WAL-mode database is captured
    consistently.
    """
    if not db_path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    target = db_path.with_name(f"{db_path.name}.pre-rebuild-{stamp}.bak")
    source = sqlite3.connect(db_path)
    dest = sqlite3.connect(target)
    try:
        source.backup(dest)
    finally:
        dest.close()
        source.close()
    return target


def rebuild(
    src: Path,
    db_path: Path,
    *,
    drop: bool = True,
    drop_live: bool = False,
    backup: bool = True,
    pre: Preflight | None = None,
) -> dict[str, Any]:
    """Import every statement in src into db_path. Returns a summary.

    Refuses via :class:`RebuildRefused` before touching the database if the archive
    cannot account for what is already stored. `pre` lets a caller reuse a pre-flight it
    has already run, so no statement is parsed twice in one invocation.
    """
    pre = pre or preflight(src)
    check_preflight(pre, db_path, drop=drop, drop_live=drop_live)

    backup_path = backup_database(db_path) if backup else None
    if backup_path:
        print(f"  backup  {backup_path}")

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")

    if drop:
        for spec in ELEMENTS.values():
            conn.execute(f"DROP TABLE IF EXISTS {spec['table']}")
    create_flex_tables(conn)

    imported: list[dict[str, Any]] = []
    written: dict[str, int] = {}

    for parsed in pre.statements:
        for tag, rows in parsed.rows.items():
            written[tag] = written.get(tag, 0) + upsert_flex_rows(conn, tag, rows)
        conn.commit()
        imported.append(
            {
                "file": parsed.src_file,
                "from": parsed.from_date,
                "to": parsed.to_date,
                "generated": parsed.when_generated,
                "rows": parsed.total_rows(),
            }
        )
        print(f"  import  {parsed.from_date}->{parsed.to_date}  {parsed.total_rows():>7,} rows  {parsed.src_file}")

    stored = {}
    for tag, spec in ELEMENTS.items():
        stored[tag] = conn.execute(f"SELECT COUNT(*) FROM {spec['table']}").fetchone()[0]
    conn.close()

    return {
        "src": str(src),
        "db": str(db_path),
        "backup": str(backup_path) if backup_path else None,
        "imported": imported,
        "rejected": [{"file": path.name, "reason": reason} for path, reason in pre.unparseable],
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
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="parse and validate the archive, print the plan, write nothing",
    )
    parser.add_argument(
        "--drop-live",
        action="store_true",
        help="discard live Client-Portal rows that no statement can reproduce",
    )
    parser.add_argument("--no-backup", action="store_true", help="skip the pre-drop database backup")
    args = parser.parse_args(argv)

    if not args.src.is_dir():
        raise SystemExit(f"archive directory not found: {args.src}")

    drop = not args.keep
    pre = preflight(args.src)
    try:
        check_preflight(pre, args.db, drop=drop, drop_live=args.drop_live)
    except RebuildRefused as exc:
        print(f"\nREFUSED  {exc}")
        return 2

    if args.dry_run:
        print(f"\ndry run — {len(pre.statements)} statement(s) would be imported into {args.db}:")
        for parsed in pre.statements:
            print(f"  {parsed.from_date}->{parsed.to_date}  {parsed.total_rows():>7,} rows  {parsed.src_file}")
        print("nothing was written")
        return 0

    print(f"Rebuilding {args.db} from {args.src}\n")
    summary = rebuild(
        args.src,
        args.db,
        drop=drop,
        drop_live=args.drop_live,
        backup=not args.no_backup,
        pre=pre,
    )

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

    # The docstring has promised since day one that this refuses to declare success
    # until the audit gate passes. It never called it, and returned 0 unconditionally.
    # There is deliberately no --skip-audit: the exit code is the only thing a wrapper,
    # Makefile or CI step ever looks at.
    print("\n── Audit gate ──────────────────────────────────────────────────────")
    return run_gate(args.db, args.src)


if __name__ == "__main__":
    sys.exit(main())
