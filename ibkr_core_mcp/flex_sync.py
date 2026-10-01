"""The state of the Flex dataset: is it sound, what does it hold, is a pull due.

Pure SQLite, read-only, no network. `flex_query` performs a pull; this module answers the
questions asked around one:

* **Is the dataset sound?** — `validate_dataset`, and `validate_dataset_daily`, which proves
  it at most once a day per dataset and says when.
* **Did a pull change anything?** — `dataset_fingerprint`, the gate on the Drive backup
  `FlexQueryClient.fetch_trades` makes after every pull.
* **When was Flex last asked, and what does the store hold?** — `last_import`,
  `statement_through`.
* **Is a pull due?** — `pull_due`, over `store.newest_statement_day`.

**None of these raises.** Each is asked at a host's session start, where an unreadable store
must produce a sentence, not a traceback: an unreadable dataset is a *failed* validity (never
a pass), an unknown fingerprint is `None` (and unknown means "back up", never "unchanged"),
an unknown statement date is `None` (and unknown means "pull"). The figures themselves —
realised P&L, executions — are `flex_dataset.FlexDataset`'s, and those do raise.

Relocated from claudia_ui's `claudia/flex_sync.py` in 2.2.0 (claudia_ui
`docs/plans/2026-09-29-flex-boundary-decision.md`). The rules are the consumer's, unchanged;
what changed is who owns them. Two costs of the old placement are gone with it: the Drive
backup hung on the host's startup rather than on the pull, so a pull started any other way
left `account_data/store.db` stale (found live 2026-08-05); and the host carried its own copy
of the statement-day rule.

## Why validation exists

A host's opening line had always read "…, integrity validated" with nothing behind it:
`SQLiteStore.get_trade_date_coverage` is an activity report and says so. These checks make
the claim true — **0.19 s measured end to end** on the real 53 MB store (the pragma is
0.07–0.13 s of it):

| Check | Catches |
|---|---|
| `PRAGMA integrity_check` | a torn or truncated file — what the WAL-safe snapshot upload exists to prevent |
| `execution_key` unique | the duplicate-row defect that once produced 75 phantom trades |
| `execution_key` non-null | rows that can never merge with a later statement, so they duplicate on the next pull |
| Trade == Lot + WashSale | the realised-P&L identity, which decides whether `flex_trade` may be reported as realised P&L at all |

The identity is IBKR's documented behaviour ("For wash sales, the Realized P/L column will
contain the net realized amount, including loss disallowed" —
https://www.ibkrguides.com/reportingreference/reportguide/trades_realizedsummary.htm),
verified exact against 20 of 20 archived statements, and deliberately the same check as
`scripts/audit_flex_dataset.py`'s #17, so the cheap session gate and the full audit cannot
disagree about what "valid" means. The two key checks are unreachable on a store built by
today's writer — `execution_key` is the table's NOT NULL primary key — and are kept for a
store whose table predates that schema, which is the store the 75 duplicates lived in.

What this does NOT do: reconcile against the source XML. That is `verify_flex_import`'s job
and it needs the statement archive.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast

from ibkr_core_mcp.flex_dataset import UNOPENABLE, open_read_only
from ibkr_core_mcp.store import SQLiteStore, newest_statement_day

__all__ = [
    "DatasetCheck",
    "DatasetValidity",
    "LastImport",
    "PullOutcome",
    "ValidationOutcome",
    "dataset_fingerprint",
    "last_import",
    "last_pull",
    "newest_statement_day",
    "pull_due",
    "statement_through",
    "validate_dataset",
    "validate_dataset_daily",
]

log = logging.getLogger(__name__)

# Cent-denominated sums do not survive binary float exactly, so the identity is compared
# to the cent rather than to zero — the same allowance audit_flex_dataset.py #17 uses.
_PENNY = 0.01


@dataclass(frozen=True)
class DatasetCheck:
    """One named check and what it measured. `detail` is shown to the user on failure."""

    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class DatasetValidity:
    """The verdict of one validation.

    `empty` is not a pass and not a failure — it is "there is nothing here yet", which is
    what a fresh install looks like. Callers must say nothing rather than either claiming
    validation or raising an alarm.
    """

    checks: tuple[DatasetCheck, ...]
    empty: bool = False

    @property
    def failures(self) -> tuple[DatasetCheck, ...]:
        """Only the checks that failed, in the order they ran."""
        return tuple(c for c in self.checks if not c.passed)

    @property
    def ok(self) -> bool:
        """True when nothing failed.

        An `empty` verdict is `ok` — it carries no checks, so there is nothing to have
        failed. Callers that need to distinguish "passed" from "nothing to check" must read
        `empty`; `summary` already words the two differently.
        """
        return not self.failures

    @property
    def summary(self) -> str:
        """One line for a log or a notice — names the first failure, not a count."""
        if self.empty:
            return "no trade dataset yet — nothing to validate"
        if self.ok:
            return f"dataset validated ({len(self.checks)} checks)"
        first = self.failures[0]
        more = f" (+{len(self.failures) - 1} more)" if len(self.failures) > 1 else ""
        return f"{first.name}: {first.detail}{more}"


def _has_flex_tables(conn: sqlite3.Connection) -> bool:
    """Whether the three tables the checks read are present.

    Their absence means the Flex dataset was never built — a fresh install, not damage.
    All three are required because the realised identity spans them; checking only
    `flex_trade` would let a half-built schema look validatable.
    """
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    return {"flex_trade", "flex_lot", "flex_wash_sale"} <= names


def validate_dataset(sqlite_path: str | Path) -> DatasetValidity:
    """Validate the local Flex dataset. Never raises — a failure to check is a failure.

    Read-only: this runs while a host and its poller hold the same database open, and
    validation must not be able to write, checkpoint or lock.
    """
    try:
        conn = open_read_only(sqlite_path)
    except UNOPENABLE as exc:
        return DatasetValidity((DatasetCheck("dataset unreadable", False, str(exc)),))

    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            # Stop here: every count below would be read off a file SQLite just called
            # damaged, and reporting those numbers would dress corruption as detail.
            return DatasetValidity((DatasetCheck("file integrity", False, f"PRAGMA integrity_check: {integrity}"),))

        if not _has_flex_tables(conn):
            return DatasetValidity((), empty=True)

        total = conn.execute("SELECT COUNT(*) FROM flex_trade").fetchone()[0]
        if total == 0:
            return DatasetValidity((), empty=True)

        dupes = conn.execute(
            "SELECT COUNT(*) FROM (SELECT execution_key FROM flex_trade GROUP BY execution_key HAVING COUNT(*) > 1)"
        ).fetchone()[0]
        nulls = conn.execute("SELECT COUNT(*) FROM flex_trade WHERE execution_key IS NULL").fetchone()[0]

        realised = conn.execute(
            "SELECT COALESCE(SUM(fifo_pnl_realized), 0) FROM flex_trade WHERE source='flex'"
        ).fetchone()[0]
        lots = conn.execute("SELECT COALESCE(SUM(fifo_pnl_realized), 0) FROM flex_lot").fetchone()[0]
        wash = conn.execute("SELECT COALESCE(SUM(fifo_pnl_realized), 0) FROM flex_wash_sale").fetchone()[0]
        identity_gap = round(abs(realised - (lots + wash)), 2)

        return DatasetValidity(
            (
                DatasetCheck("file integrity", True, "PRAGMA integrity_check: ok"),
                DatasetCheck("execution_key is unique", dupes == 0, f"{dupes:,} duplicated key(s)"),
                DatasetCheck("execution_key is present", nulls == 0, f"{nulls:,} row(s) without a key"),
                DatasetCheck(
                    "realised P&L identity (trades == lots + wash sale)",
                    identity_gap <= _PENNY,
                    f"{realised:,.2f} vs {lots + wash:,.2f} — off by {identity_gap:,.2f}",
                ),
            )
        )
    except sqlite3.DatabaseError as exc:
        # A malformed page can surface here rather than in integrity_check.
        return DatasetValidity((DatasetCheck("dataset unreadable", False, str(exc)),))
    finally:
        conn.close()


def dataset_fingerprint(sqlite_path: str | Path) -> tuple[int, int, str | None] | None:
    """A cheap signature of the dataset: (rows, Flex-sourced rows, newest trade date).

    Compared across a pull to decide whether the Drive backup needs refreshing. Returns
    None when it cannot be taken — the caller treats that as "unknown", and unknown must
    fall through to uploading rather than to skipping.

    Flex-sourced rows are counted separately for a reason measured live on 2026-08-05:
    the statement merged onto nine existing live-captured rows via `execution_key`, so
    the total was 1,110 before and 1,110 after. A count-only fingerprint would have read
    that as "nothing changed" and skipped the backup — losing exactly the settled
    statement figures the pull was for. The source mix moved even though the count did not.
    """
    try:
        conn = open_read_only(sqlite_path)
    except UNOPENABLE:
        return None
    try:
        if not _has_flex_tables(conn):
            return None
        total = conn.execute("SELECT COUNT(*) FROM flex_trade").fetchone()[0]
        flex_rows = conn.execute("SELECT COUNT(*) FROM flex_trade WHERE source='flex'").fetchone()[0]
        newest = conn.execute("SELECT MAX(trade_date_iso) FROM flex_trade WHERE source='flex'").fetchone()[0]
        return (total, flex_rows, newest)
    except sqlite3.DatabaseError as exc:
        log.warning("dataset_fingerprint: %s", exc)
        return None
    finally:
        conn.close()


# ── "already updated today — do not check again" (operator rule, 2026-08-05) ──


@dataclass(frozen=True)
class LastImport:
    """When Flex was last asked for a statement, and which file the answer became."""

    at: datetime
    filename: str
    trade_count: int


@dataclass(frozen=True)
class ValidationOutcome:
    """A verdict plus **when it was established** — which is not always now.

    `reused` True means nothing was re-checked: a verdict from earlier today still
    describes this exact dataset. `validated_at` is the moment the checks actually ran,
    never the moment they were asked for, so a surface can state a time that is true.
    """

    validity: DatasetValidity
    validated_at: datetime
    reused: bool


def _record_path(sqlite_path: str | Path) -> Path:
    """Sidecar holding the last verdict. Named after the database it describes."""
    return Path(f"{sqlite_path}.validation.json")


def last_import(sqlite_path: str | Path) -> LastImport | None:
    """The most recent Flex pull on record (`flex_import_log`, source 'auto'), or None.

    The moment Flex last returned a statement — every successful pull writes its statement's
    row (a same-day repeat gets IBKR's cached statement and updates that row's time),
    including a pull that brings nothing new, so this is "last pulled", never "last changed".
    Rows with source 'manual' are hand-downloaded archive statements, registered when the
    archive check first sees them; they are not pulls.

    It is **not** the newest trade date: on 2026-08-05 those were 08-05 12:18 UTC and
    2026-08-04 respectively, a full day apart, because Flex is T+1.

    Returns None rather than a guess when the timestamp cannot be parsed, or the count is
    not an integer: no time on screen is better than a wrong one. A NULL count is 0 — the row
    itself proves a pull happened. Never raises.
    """
    try:
        conn = open_read_only(sqlite_path)
    except UNOPENABLE:
        return None
    try:
        row = conn.execute(
            "SELECT filename, imported_at, trade_id_count FROM flex_import_log "
            "WHERE source = 'auto' ORDER BY imported_at DESC, id DESC LIMIT 1"
        ).fetchone()
    except sqlite3.DatabaseError:
        return None  # table absent on a store that has never imported
    finally:
        conn.close()

    if not row or not row[1]:
        return None
    try:
        at = datetime.fromisoformat(str(row[1]))
    except ValueError:
        log.warning("last_import: unparseable imported_at %r", row[1])
        return None
    if at.tzinfo is None:
        at = at.replace(tzinfo=UTC)
    count = 0 if row[2] is None else row[2]
    if not isinstance(count, int):
        # `int()` here raised on text and on an infinite REAL, and cut 12.5 to 12 (claudia_ui gap #89).
        log.warning("last_import: unparseable trade_id_count %r", row[2])
        return None
    return LastImport(at=at, filename=str(row[0]), trade_count=count)


@dataclass(frozen=True)
class PullOutcome:
    """What the last recorded Flex pull did — typed, so no caller reads it out of text.

    A field is None when the pull did not record it: releases before 2.2.0 wrote no `backup`
    and no `valid`, and early ones no archive outcome. **None is unknown — not a problem,
    and not a success either.** The account the row names is deliberately not carried.
    """

    at: datetime
    """When the pull finished and wrote its record. Compare it with when you asked: a pull
    that raised before recording leaves an older pull's row as the newest."""
    trades_fetched: int | None
    archive_ok: bool | None
    """Whether the statement reached the `flex_*` tables. False means the archive refused it
    (a Flex field it does not know) while the legacy table still updated."""
    archive_reason: str | None
    backup: str | None
    """`FlexBackupResult.status`: `uploaded`, `unchanged`, `failed` or `not-configured`. With
    Drive configured it also says whether the pull changed the dataset."""
    valid: bool | None
    """`validate_dataset`'s verdict on the dataset as the pull left it."""

    @property
    def problems(self) -> tuple[str, ...]:
        """What is KNOWN to have gone wrong, in a fixed order: `archive`, `backup`, `validation`.

        Empty for a clean pull and for a row that recorded nothing. A caller that shows a
        pull under a tick takes its level from this, never from the tool's text.
        """
        found = []
        if self.archive_ok is False:
            found.append("archive")
        if self.backup == "failed":
            found.append("backup")
        if self.valid is False:
            found.append("validation")
        return tuple(found)


def _typed(data: dict[str, object], key: str, kind: type) -> object:
    """`data[key]` when it is absent, None or exactly a `kind`; raises `TypeError` otherwise.

    Exactly: `bool` is an `int` to Python, and a count of `True` is not a count.
    """
    value = data.get(key)
    if value is None or type(value) is kind:
        return value
    raise TypeError(f"{key} is {value!r}, not a {kind.__name__}")


def last_pull(sqlite_path: str | Path) -> PullOutcome | None:
    """The outcome of the most recent Flex pull on record (`session_log`, event `flex_sync`), or None.

    `sync_flex_trades` writes one such row after every pull it completes, whoever started
    it: what was fetched, whether the archive took the statement, what became of the Drive
    backup, and whether the dataset validates. Until 2.2.0 a consumer could learn that the
    archive had refused a statement only by finding "⚠" in the tool's text — and showed that
    text under a tick (claudia_ui gap #86, register F30); the backup's outcome joined the same
    text in 2.2.0. This reads the row back typed.

    None when the store cannot be opened, holds no such row, or the row is malformed: a
    value of the wrong type is never coerced — the string "false" is truthy — so the whole
    row is refused, with a warning. A pull made by calling `FlexQueryClient.fetch_trades`
    directly writes no row and is not seen here. Never raises.
    """
    try:
        conn = open_read_only(sqlite_path)
    except UNOPENABLE:
        return None
    try:
        row = conn.execute(
            "SELECT ts, data FROM session_log WHERE event = 'flex_sync' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    except sqlite3.DatabaseError:
        return None  # no session_log on a store that has never been initialised
    finally:
        conn.close()

    if not row:
        return None
    try:
        at = datetime.fromisoformat(str(row[0]))
    except ValueError:
        log.warning("last_pull: unparseable time %r", row[0])
        return None
    if at.tzinfo is None:
        at = at.replace(tzinfo=UTC)
    try:
        data = {} if row[1] is None else json.loads(row[1])
        if not isinstance(data, dict):
            raise TypeError(f"the record is a {type(data).__name__}, not an object")
        return PullOutcome(
            at=at,
            trades_fetched=cast("int | None", _typed(data, "trades_fetched", int)),
            archive_ok=cast("bool | None", _typed(data, "archive_ok", bool)),
            archive_reason=cast("str | None", _typed(data, "archive_reason", str)),
            backup=cast("str | None", _typed(data, "backup", str)),
            valid=cast("bool | None", _typed(data, "valid", bool)),
        )
    except (ValueError, TypeError) as exc:
        log.warning("last_pull: the record of %s is malformed — %s", at.isoformat(), exc)
        return None


def validate_dataset_daily(sqlite_path: str | Path, now: datetime | None = None) -> ValidationOutcome:
    """Validate at most once per calendar day per dataset, and say when it was proven.

    The operator's rule, 2026-08-05: *"If flex sync was performed and db already updated on
    T, do not check again. Just explicitly mention it was already updated: state the date
    and time."* Flex is T+1 and the store is pulled once a day, so re-running the checks
    on a byte-identical dataset cannot produce a new answer.

    Reuse requires **both** conditions, and the fingerprint is the load-bearing one:

    * the stored verdict was reached **today**, and
    * `dataset_fingerprint` still matches what it was computed against.

    So a pull that lands mid-session re-validates immediately rather than coasting on a
    verdict about data that no longer exists. Two things are deliberately never reused: a
    **failure** (it must be re-measured, not cached forward into a day of silence) and a
    verdict from any earlier day.

    The cache is an optimisation and is treated as one — an unwritable location, a
    corrupt sidecar or a malformed record costs the reuse, never the check.
    """
    now = now or datetime.now(UTC)
    fingerprint = dataset_fingerprint(sqlite_path)

    reusable = _reusable_verdict(_read_record(_record_path(sqlite_path)), fingerprint, now)
    if reusable is not None:
        return reusable

    validity = validate_dataset(sqlite_path)
    _write_record(_record_path(sqlite_path), validity, fingerprint, now)
    return ValidationOutcome(validity=validity, validated_at=now, reused=False)


def _reusable_verdict(
    stored: object, fingerprint: tuple[int, int, str | None] | None, now: datetime
) -> ValidationOutcome | None:
    """A stored verdict that still describes this dataset today, or None.

    Every field is checked before it is believed. The sidecar is an ordinary JSON file on
    disk that a person can edit, truncate or copy between machines, so it is parsed as
    untrusted input: anything unexpected returns None and costs one re-validation, which
    is the cheap failure. The expensive failure would be trusting a record that says
    "valid" about a dataset it was not computed against.
    """
    if not isinstance(stored, dict) or stored.get("ok") is not True:
        return None
    if fingerprint is None or stored.get("fingerprint") != list(fingerprint):
        return None

    raw_at = stored.get("validated_at")
    if not isinstance(raw_at, str):
        return None
    try:
        validated_at = datetime.fromisoformat(raw_at)
    except ValueError:
        return None
    if validated_at.tzinfo is None:
        validated_at = validated_at.replace(tzinfo=UTC)
    # Local calendar day, not UTC: "already checked today" has to mean the reader's today.
    if validated_at.astimezone().date() != now.astimezone().date():
        return None

    raw_checks = stored.get("checks")
    checks = tuple(
        DatasetCheck(name=str(c["name"]), passed=True, detail=str(c.get("detail", "")))
        for c in (raw_checks if isinstance(raw_checks, list) else [])
        if isinstance(c, dict) and isinstance(c.get("name"), str)
    )
    return ValidationOutcome(
        validity=DatasetValidity(checks, empty=bool(stored.get("empty"))),
        validated_at=validated_at,
        reused=True,
    )


def _read_record(path: Path) -> dict[str, object] | None:
    """The stored verdict, or None if there is not a usable one. Never raises."""
    try:
        record = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def _write_record(
    path: Path,
    validity: DatasetValidity,
    fingerprint: tuple[int, int, str | None] | None,
    now: datetime,
) -> None:
    """Store the verdict beside the database. Never raises — see `validate_dataset_daily`.

    **Nothing is written without a fingerprint.** Such a record could never be reused —
    reuse requires a fingerprint match — so writing one is pure cost, and the cost turned
    out to be real: an unreadable path still produced a file, and a test passing a
    `MagicMock` config wrote `<MagicMock name='mock._config.sqlite_path' id=…>.validation.json`
    into a repository root. Fourteen of them reached a commit before a pre-push file
    listing caught it. A path we could not read is not a path we should write beside.
    """
    if fingerprint is None:
        return
    record = {
        "validated_at": now.isoformat(),
        "ok": validity.ok,
        "empty": validity.empty,
        "fingerprint": list(fingerprint),
        "checks": [{"name": c.name, "detail": c.detail} for c in validity.checks if c.passed],
        "summary": validity.summary,
    }
    try:
        path.write_text(json.dumps(record, indent=2))
        # 0600 for the same reason the store itself is: the record summarises the account's
        # trade dataset — row counts, the newest trade date, the realised-P&L total the
        # checks were satisfied by. `write_text` honours the umask and does not touch an
        # existing file's mode, so this is unconditional and after every write.
        path.chmod(0o600)
    except OSError as exc:
        log.warning("Could not cache the dataset verdict (%s) — it will be re-checked", exc)


# ── The pull rule (operator 2026-09-28): pull unless the store already holds the ──
# ── statement for the weekday before today (ET).                                ──


def statement_through(sqlite_path: str | Path) -> date | None:
    """The newest statement day the store holds — IBKR's own `toDate` — or None.

    The same read `SQLiteStore.get_trade_date_coverage`'s `stale` flag makes
    (`SQLiteStore._statement_through`): `flex_change_in_nav`, one row per statement, then
    the settled rows of `flex_trade`. It is the statement's date, not a trade's: a weekday
    with no fills still has a statement. Anything unreadable is None, never a guess; the
    caller treats None as "pull".
    """
    try:
        conn = open_read_only(sqlite_path)
    except UNOPENABLE:
        return None
    try:
        return SQLiteStore._statement_through(conn)
    finally:
        conn.close()


def pull_due(now: datetime, held: date | None) -> bool:
    """True unless the store holds the newest statement that can exist.

    A pull made before IBKR publishes brings an older `toDate`, so the next start is still
    due: no clock is involved. A repeat pull the same day returns IBKR's cached statement,
    so an extra pull costs one request and changes nothing.

    Args:
        now: An aware datetime; the day is read on the ET calendar (`newest_statement_day`).
        held: `statement_through(...)` — None when nothing is held or it cannot be read.

    Raises:
        ValueError: If `now` is naive.
    """
    newest = newest_statement_day(now)
    return held is None or held < newest
