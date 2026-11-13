"""The read side of the Flex dataset — typed answers, read-only, never raw rows.

`flex_query` fetches a statement, `flex_import` parses it, `flex_store` writes it. This
module is the fourth part: what the stored dataset *means*. Every consumer that asks what
was realised, by which asset class, on which statement, asks here — this package's own
tools, its MCP server, and a host application such as claudia_ui — so they cannot answer
differently (claudia_ui `docs/plans/2026-09-29-flex-boundary-decision.md`: the core answers
questions about the account; the host decides when to ask and how to show the answer).

Until 2.2.0 these queries lived in claudia_ui (`claudia/dashboard_data.py`, nine SQL
statements on this package's tables) while the model's `get_trades` summed a different
table, and the two disagreed on lifetime realised P&L (register F20).

## The realised-P&L rule — do not re-derive it

```sql
SELECT SUM(fifo_pnl_realized) FROM flex_trade
 WHERE source='flex' AND trade_date_iso BETWEEN ? AND ?
```

**No open/close filter.** Settled 2026-08-04 against IBKR's own `SymbolSummary` in 20 of 20
archived statements and its annual statements in 6 of 6 years (`scripts/audit_flex_dataset.py`
checks 17 and 17c; `docs/flex-query-reference.md` § How to compute realised P&L). Two traps:

1. Filtering on `open_close_indicator` is wrong — a buy that closes a short and opens a long
   is flagged `O` and still realises.
2. `flex_lot` is **pre-wash-sale** tax-lot detail; summing it overstates losses.
   `Trade == Lot + WashSale`. Lots are the right basis for a *count* of round trips and the
   wrong one for money, which is why `TypeBreakdown` reads both tables and labels each.

`source='flex'` rows are statement rows. A `source='live'` row is this package's own
placeholder for a fill whose statement has not arrived: it carries no trade date and no
realised figure, and it settles nothing.

## A day is IBKR's trade date

Windows bucket on `trade_date` — the session a fill belongs to, which IBKR states only in the
statement — never on a clock. IBKR rolls a fill forward to the next trading day after its
venue's session boundary: an evening futures fill, an overnight-session stock fill and an FX
fill after the IdealPro roll all carry the next trade date, and a weekend or a holiday rolls
to the next *trading* day. The boundaries were measured on a real account's statements in
claudia_ui (`claudia/dashboard_data.py`, module docstring). Nothing here derives a day from a
timestamp, and nothing may: a second definition of "day" beside IBKR's would drift from it.

## Read-only, by construction

Every connection is opened with SQLite's `mode=ro` URI parameter — "The mode query parameter
determines if the new database is opened read-only, read-write, read-write and created if it
does not exist" (https://www.sqlite.org/uri.html § 3.3) — and a write on it raises
`OperationalError: attempt to write a readonly database`
(https://docs.python.org/3/library/sqlite3.html#how-to-work-with-sqlite-uris). The URI is
built with `Path.as_uri()`, which percent-encodes the path. A hand-formatted
`f"file:{path}?mode=ro"` is not safe: SQLite reads the query string after the first `?`, the
fragment after `#`, and decodes `%HH` escapes (uri.html § 3.1–3.2), so over a path holding
any of the three it loses `mode=ro` and opens — creating it — a different file, read-write
(measured 2026-09-30, SQLite 3.53.4). `as_uri()` has one hole of its own: it writes a NUL
as `%00`, where SQLite ends the URI's path and opens the prefix, so `open_read_only` refuses a
path holding one — a NUL names no file on any file system. The store runs in WAL mode; a read-only open of a WAL
database needs the `-shm`/`-wal` files to exist or the directory to be writable
(https://www.sqlite.org/wal.html § 5), which the store's own directory always is. Nothing
here creates a table, sets a pragma, changes a file mode or repairs anything: the write
side (`SQLiteStore`) owns all of that.

## Errors

A figure that cannot be read is not a zero. Every method of `FlexDataset` raises
`StoreError` when the file, a table or a column is missing, when the database is damaged,
or when a stored date it has to parse does not parse; the caller decides what an unreadable
dataset means on its surface. The window sums compare trade dates as text and parse none, so
a row whose date is not an ISO date is simply outside every window — which is why the full
dataset audit proves every stored trade date is ISO (`scripts/audit_flex_dataset.py`, check
5b). The never-raising questions about the dataset's *state* — is it sound, what does it
hold, is a pull due — live in `flex_sync`.

## Threads

A `FlexDataset` wraps one `sqlite3` connection, which belongs to the thread that opened it
(`check_same_thread`, https://docs.python.org/3/library/sqlite3.html#sqlite3.connect). Open,
ask, close, on one thread:

```python
with FlexDataset.open(config.sqlite_path) as flex:
    week = flex.realised_window(monday, today)
```
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from types import TracebackType
from typing import Any, Self

from ibkr_core_mcp.exceptions import StoreError

__all__ = [
    "UNOPENABLE",
    "FlexCoverage",
    "FlexDataset",
    "FlexExecution",
    "RealisedPoint",
    "RealisedWindow",
    "RoundTripStats",
    "TypeBreakdown",
    "gain_pct_over",
    "open_read_only",
]

log = logging.getLogger(__name__)

# What `open_read_only` raises when the store cannot be opened: SQLite's own errors, and the
# errors of a value that names no file — a test double (`TypeError`), a relative path with no
# working directory (`OSError`), a NUL or an unencodable name (`ValueError`). `FlexDataset.open`
# turns each into `StoreError`; the never-raise readers in `flex_sync` catch the tuple whole.
UNOPENABLE: tuple[type[Exception], ...] = (sqlite3.Error, OSError, TypeError, ValueError)


def open_read_only(sqlite_path: str | Path) -> sqlite3.Connection:
    """Open the store read-only — that file, and no other. The one read-only opener in this
    package and its scripts.

    `mode=ro` never creates a file: a missing path raises `sqlite3.OperationalError`
    ("unable to open database file") instead of leaving an empty database behind.
    `row_factory` is `sqlite3.Row`, matching `SQLiteStore._connect`.

    The path is opened as `SQLiteStore._connect` opens it, so the reader and the writer name
    the same file: `absolute()` is the least a URI needs (SQLite resolves a relative path
    against the working directory), and `~` is not expanded — `Config.from_env` has already
    expanded it once, and SQLite never does. A NUL is refused here: `Path.as_uri()` writes it
    `%00`, where SQLite ends a URI's path and opens what precedes it (`sqlite3ParseUri` in
    its `src/main.c`, not in its documentation pages; measured on 3.53.4).

    Args:
        sqlite_path: The store's path (`Config.sqlite_path`).

    Raises:
        TypeError: `sqlite_path` is not a path (a test double, None).
        OSError: `sqlite_path` is relative and the working directory no longer exists.
        ValueError: `sqlite_path` holds a NUL, or a character the file system cannot encode.
        sqlite3.Error: the file cannot be opened. Together these are `UNOPENABLE`; callers in
            this package convert them — `FlexDataset.open` to `StoreError`, the `flex_sync`
            functions to their own "unreadable" answers.
    """
    path = Path(sqlite_path).absolute()
    if "\x00" in str(path):
        raise ValueError("a path holding a NUL names no file")
    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _num(value: Any) -> float:
    """Coerce a stored numeric to float; 0.0 for NULL or anything unparseable."""
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _day(value: Any) -> date | None:
    """A stored ISO trade date as a `date`; None for NULL.

    Raises:
        StoreError: If the stored value is not an ISO date — the writer never stores one, so
            such a row is damage, and a figure computed around it would be a guess.
    """
    if value is None or value == "":
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise StoreError(f"Flex dataset unreadable: stored trade date {value!r} is not an ISO date") from exc


# ── Answers ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RealisedWindow:
    """Realised P&L over one date window, from the Flex dataset.

    `total` is the plain sum of `fifo_pnl_realized` with no open/close filter — the rule
    settled against IBKR's own statements (module docstring). `by_asset` splits it by
    `asset_category` (`FUT` / `STK` / `OPT` / `FUND` / `CASH`).

    `currencies` is what the window actually contained, not an assumption. When it holds
    more than one code the total is a sum across currencies and a surface must say so
    rather than stamping one ISO code on it.

    There is no `name` field: `start`/`end` identify the window completely, and the caller
    already knows which one it asked for. A name carried here and never read is a second
    place for "week" to be wrong.

    ⚠ **This is not the same quantity as the account ledger's `realizedpnl`, and the two
    must never be added.** Both are realised P&L, over different windows (this one is T+1
    and never includes today; the ledger's is today only) and on different day boundaries
    (this one on IBKR's trade date; the ledger on IBKR's accounting roll, late in the ET
    evening at an hour that varies). They are also defined on different cost bases — this
    one IBKR's *statement* basis, the ledger's its real-time `avgCost` — which are different
    by construction and not guaranteed to agree; the one time both were measured on the
    same trade they agreed to the cent. The measurements, and the projection they
    corrected, are in claudia_ui's `claudia/dashboard_data.py` (module docstring, § Two
    realised figures).
    """

    start: date
    end: date
    total: float
    trade_count: int
    by_asset: Mapping[str, float] = field(default_factory=dict)
    currencies: tuple[str, ...] = ()

    @property
    def currency_label(self) -> str:
        """ISO code for `total`, "mixed" across several currencies, or "" when unknown.

        An **empty** window returns the empty string rather than "USD": nothing was
        realised, so there is no currency to state, and stating one anyway would be a guess.
        """
        if len(self.currencies) == 1:
            return self.currencies[0]
        if not self.currencies:
            return ""
        return "mixed"

    def asset_total(self, *categories: str) -> float:
        """Sum of `by_asset` over the named categories (missing ones count as 0.0)."""
        return sum(self.by_asset.get(c, 0.0) for c in categories)


@dataclass(frozen=True)
class RealisedPoint:
    """One day on the realised-P&L curve: that day's realisation and the running total."""

    day: date
    realised: float
    cumulative: float


@dataclass(frozen=True)
class RoundTripStats:
    """Winners vs losers over closed round trips, from `flex_lot`.

    **This is a count, never a P&L total.** `flex_lot` is pre-wash-sale tax-lot detail
    (`Trade == Lot + WashSale`), so summing it overstates losses by the disallowed amount.
    The money figure is `RealisedWindow.total`; the two must be labelled distinctly
    wherever they appear together.

    Lots are the right basis for the *count* because a lot is a genuine round trip — open →
    close, with a holding period — whereas executions include opening legs and
    wash-sale-zeroed closes that are neither a win nor a loss. On a real account's year,
    executions that realised exactly zero outnumbered the winners and losers together,
    while its closed lots held no scratch at all (measured in claudia_ui, 2026-08-04).
    """

    start: date
    end: date
    closed_lots: int
    winners: int
    losers: int
    scratches: int
    gross_win: float
    gross_loss: float

    @property
    def win_rate(self) -> float | None:
        """Winners as a percentage of decided lots, or None when nothing closed.

        Scratches are excluded from the denominator: a lot that realised exactly 0.00 is
        neither won nor lost, and counting it as a loss would understate the rate. None
        rather than 0.0 for an empty window, so a surface can render "—" instead of a 0%
        win rate that reads like a catastrophic week.
        """
        decided = self.winners + self.losers
        return 100.0 * self.winners / decided if decided else None


@dataclass(frozen=True)
class TypeBreakdown:
    """Realised performance for one asset class over one window.

    **Two different sources, deliberately, and they must stay labelled apart.**

    * `net` is the money figure, from `flex_trade.fifo_pnl_realized` — the rule settled
      against IBKR's own annual statements 6/6 years exactly.
    * `gross_win` / `gross_loss` / the counts come from `flex_lot`, which is
      **pre-wash-sale** tax-lot detail (`Trade == Lot + WashSale`). Summing lots as the
      money figure overstates losses by the disallowed amount.

    So `gross_win + gross_loss` will not always equal `net`, and that is correct rather
    than a bug. A surface showing both must say which is which — the same rule
    `RoundTripStats` carries.

    A lot is the right unit for a *count*: it is a genuine round trip (open -> close),
    whereas an execution list includes opening legs and wash-sale-zeroed closes that are
    neither a win nor a loss. A host may also build one from its own reconstruction of the
    fills not yet on a statement (claudia_ui's pending window does); the fields mean the
    same thing there.
    """

    asset_class: str
    net: float
    gross_win: float
    gross_loss: float
    winners: int
    losers: int
    scratches: int

    @property
    def closed_lots(self) -> int:
        """Round trips that closed in this window, decided or not."""
        return self.winners + self.losers + self.scratches

    @property
    def win_rate(self) -> float | None:
        """Winners as a percentage of *decided* lots, or None when nothing decided.

        Scratches are excluded from the denominator: a lot realising exactly 0.00 is
        neither won nor lost, and counting it as a loss understates the rate. None rather
        than 0.0 for an empty window, so a surface renders an em dash instead of a 0% that
        reads like a catastrophic week.
        """
        decided = self.winners + self.losers
        return 100.0 * self.winners / decided if decided else None

    @property
    def gain_pct(self) -> float | None:
        """Gross wins as a percentage of the gross traded either way (claudia_ui, 2026-09-29).

        The win rate counts lots; this weighs them: nine wins totalling 500 against one
        loss of 500 is a 90% win rate and a 50% gain rate. None when nothing was gained or
        lost, so a surface renders an em dash rather than a rate over nothing.
        """
        return gain_pct_over((self,))

    @property
    def win_loss_ratio(self) -> float | None:
        """Gross win over gross loss, or None when nothing was lost.

        None rather than infinity: a window with no losing lot has no ratio, and rendering
        one invites a comparison that does not exist.
        """
        return self.gross_win / abs(self.gross_loss) if self.gross_loss else None

    @property
    def average_win(self) -> float | None:
        """Mean size of a winning lot, or None when there were none."""
        return self.gross_win / self.winners if self.winners else None

    @property
    def average_loss(self) -> float | None:
        """Mean size of a losing lot (negative), or None when there were none.

        Reported beside `average_win` because **the count and the money can tell opposite
        stories, and both are needed to read a window correctly.** One win of 3,000 against
        five losses of 600 is a 17% win rate — dreadful by count — and break-even in money.
        The inverse happens too: a class with no winning lot at all can carry small
        average losses while another class's better win rate sits on losses an order of
        magnitude larger.

        Splitting by asset class is not cosmetic for the same reason: a futures lot and an
        equity lot differ by their contract multiplier alone, so pooling them makes the
        averages describe nothing real.
        """
        return self.gross_loss / self.losers if self.losers else None


def gain_pct_over(rows: Iterable[TypeBreakdown]) -> float | None:
    """Gross wins over gross wins plus gross losses across `rows`, in percent, or None.

    Computed on the summed gross figures, not averaged over rows: 800 of gains against
    500 of losses is 61.5% whatever the split by asset class.
    """
    rows = tuple(rows)
    wins = sum(r.gross_win for r in rows)
    losses = sum(abs(r.gross_loss) for r in rows)
    traded = wins + losses
    return round(100.0 * wins / traded, 1) if traded else None


@dataclass(frozen=True)
class FlexCoverage:
    """How far the Flex dataset reaches: the newest statement *trade date*, or None.

    What has not landed in Flex yet is a host's to reconstruct from live fills, decided by
    execution id (`FlexDataset.settled_execution_ids`). This is not the statement's own
    `toDate`: a weekday with no fills has a statement and no trade, so
    `flex_sync.statement_through` can be later than `through`. Whether a pull is due is
    decided by the `toDate`, never by this.
    """

    through: date | None


@dataclass(frozen=True)
class FlexExecution:
    """One execution as IBKR's statement reports it.

    `execution_id` is IBKR's execution id (`ibExecID`, the dataset's merge key — the same id
    `/iserver/account/trades` reports). `trade_id` is IBKR's `tradeID`, the id the XML
    archive and `verify_flex_import` compare by. `quantity` is signed (a sell is negative, as
    Flex stores it). `commission` is a positive cost (Flex stores it negative). `realised` is
    `fifo_pnl_realized` — the figure the realised-P&L rule sums. `trade_date` is IBKR's trade
    date; `time` is the statement's `dateTime` in ISO form with **no timezone** (IBKR
    declares none in the XML), so it orders executions within this dataset and is never
    compared with a clock from another source. `multiplier` is None when the statement
    carried none; a money figure cannot be derived from such a row.
    """

    execution_id: str
    trade_id: int | None
    account: str
    conid: int | None
    symbol: str
    asset_class: str
    currency: str
    quantity: float
    price: float
    commission: float
    multiplier: float | None
    trade_date: date | None
    time: str
    realised: float


def _execution(row: sqlite3.Row) -> FlexExecution:
    """One `flex_trade` row as a `FlexExecution`.

    The two queries that feed this select the same fourteen columns, written out in each so
    the SQL text stays a literal (nothing is ever interpolated into a statement here).
    """
    return FlexExecution(
        execution_id=str(row["execution_key"]),
        trade_id=int(row["trade_id"]) if row["trade_id"] is not None else None,
        account=str(row["account_id"] or ""),
        conid=int(row["conid"]) if row["conid"] is not None else None,
        symbol=str(row["symbol"] or ""),
        asset_class=str(row["asset_category"] or ""),
        currency=str(row["currency"] or "").upper(),
        quantity=_num(row["quantity"]),
        price=_num(row["trade_price"]),
        commission=abs(_num(row["ib_commission"])),
        multiplier=float(row["multiplier"]) if row["multiplier"] is not None else None,
        trade_date=_day(row["trade_date_iso"]),
        time=str(row["date_time_iso"] or ""),
        realised=_num(row["fifo_pnl_realized"]),
    )


# ── The reader ────────────────────────────────────────────────────────────────


class FlexDataset:
    """Read-only, typed access to the Flex dataset in the store.

    Build one with `FlexDataset.open(path)` and use it as a context manager. See the module
    docstring for the rule each figure follows, the error contract and the thread rule.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        """Wrap an already-open connection. Use `FlexDataset.open`; this exists for it.

        Args:
            conn: A connection from `open_read_only`. It is closed by `close()`.
        """
        self._conn = conn

    @classmethod
    def open(cls, sqlite_path: str | Path) -> Self:
        """Open the store read-only.

        Args:
            sqlite_path: The store's path (`Config.sqlite_path`).

        Raises:
            StoreError: If the file does not exist or cannot be opened, or `sqlite_path`
                names no file at all (`UNOPENABLE`). The message carries the reason and not
                the path — the caller knows which store it asked for, and an absolute path
                in an error string is how a username reaches a tool result
                (`redaction.collapse_home`).
        """
        try:
            return cls(open_read_only(sqlite_path))
        except UNOPENABLE as exc:
            raise StoreError(f"Flex dataset unreadable: {exc}") from exc

    def close(self) -> None:
        """Close the connection. Safe to call twice."""
        self._conn.close()

    def __enter__(self) -> Self:
        """Return the reader itself; the connection is already open."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the connection, whatever happened inside the block."""
        self.close()

    def _rows(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        """Run one fixed-text query; a SQLite failure becomes `StoreError`."""
        try:
            return self._conn.execute(sql, params).fetchall()
        except sqlite3.Error as exc:
            raise StoreError(f"Flex dataset unreadable: {exc}") from exc

    # ── Realised P&L ────────────────────────────────────────────────────────

    def realised_window(self, start: date, end: date) -> RealisedWindow:
        """Realised P&L between `start` and `end` inclusive, split by asset class.

        The predicate is `source='flex' AND trade_date_iso BETWEEN ? AND ?` — no open/close
        filter, deliberately (module docstring). `source='flex'` excludes the placeholder
        rows, which carry no trade date and no realised figure.
        """
        rows = self._rows(
            """
            SELECT asset_category, currency,
                   COUNT(*) AS n, SUM(fifo_pnl_realized) AS pnl
              FROM flex_trade
             WHERE source = 'flex'
               AND trade_date_iso BETWEEN ? AND ?
             GROUP BY asset_category, currency
            """,
            (start.isoformat(), end.isoformat()),
        )
        by_asset: dict[str, float] = {}
        currencies: set[str] = set()
        total = 0.0
        count = 0
        for row in rows:
            pnl = float(row["pnl"] or 0.0)
            asset = str(row["asset_category"] or "?")
            by_asset[asset] = by_asset.get(asset, 0.0) + pnl
            total += pnl
            count += int(row["n"] or 0)
            if row["currency"]:
                currencies.add(str(row["currency"]).upper())
        return RealisedWindow(
            start=start,
            end=end,
            total=total,
            trade_count=count,
            by_asset=by_asset,
            currencies=tuple(sorted(currencies)),
        )

    def realised_series(self, start: date, end: date) -> tuple[RealisedPoint, ...]:
        """Daily realised P&L between `start` and `end` inclusive, with a running total.

        Only days that actually traded appear — the cumulative line therefore steps between
        them rather than drawing a flat run through non-trading days. That is the honest
        shape for a realisation curve: nothing was realised on the days in between, and
        inventing zero-rows would imply the account was observed on days no statement covers.
        """
        rows = self._rows(
            """
            SELECT trade_date_iso AS day, SUM(fifo_pnl_realized) AS pnl
              FROM flex_trade
             WHERE source = 'flex'
               AND trade_date_iso BETWEEN ? AND ?
             GROUP BY trade_date_iso
             ORDER BY trade_date_iso
            """,
            (start.isoformat(), end.isoformat()),
        )
        out: list[RealisedPoint] = []
        running = 0.0
        for row in rows:
            day = _day(row["day"])
            if day is None:  # BETWEEN never matches NULL; kept for the type, not for data
                continue
            pnl = float(row["pnl"] or 0.0)
            running += pnl
            out.append(RealisedPoint(day, pnl, running))
        return tuple(out)

    def round_trip_stats(self, start: date, end: date) -> RoundTripStats:
        """Closed-lot win/loss counts between `start` and `end` inclusive.

        Queries `flex_lot`, which has neither a `trade_date_iso` nor a `source` column — so
        the bounds are formatted to its compact `YYYYMMDD` `trade_date`, and there is no
        source predicate because every lot is Flex-derived.

        `gross_win`/`gross_loss` are lot-basis subtotals for a win/loss ratio; they are
        **not** realised P&L and their difference is not the account's realised total. See
        `RoundTripStats`.
        """
        lo, hi = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
        row = self._rows(
            """
            SELECT COUNT(*)                                          AS n,
                   SUM(CASE WHEN fifo_pnl_realized > 0 THEN 1 ELSE 0 END) AS wins,
                   SUM(CASE WHEN fifo_pnl_realized < 0 THEN 1 ELSE 0 END) AS losses,
                   SUM(CASE WHEN COALESCE(fifo_pnl_realized, 0) = 0 THEN 1 ELSE 0 END) AS flat,
                   SUM(CASE WHEN fifo_pnl_realized > 0 THEN fifo_pnl_realized ELSE 0 END) AS gross_win,
                   SUM(CASE WHEN fifo_pnl_realized < 0 THEN fifo_pnl_realized ELSE 0 END) AS gross_loss
              FROM flex_lot
             WHERE trade_date BETWEEN ? AND ?
            """,
            (lo, hi),
        )[0]
        return RoundTripStats(
            start=start,
            end=end,
            closed_lots=int(row["n"] or 0),
            winners=int(row["wins"] or 0),
            losers=int(row["losses"] or 0),
            scratches=int(row["flat"] or 0),
            gross_win=float(row["gross_win"] or 0.0),
            gross_loss=float(row["gross_loss"] or 0.0),
        )

    def realised_by_type(self, start: date, end: date) -> tuple[TypeBreakdown, ...]:
        """Per-asset-class realised performance between `start` and `end` inclusive.

        Returns a row **only for asset classes that actually did something** in the window —
        no zero rows for classes that were never traded — ordered by absolute net so the
        class that moved the money most is first.

        The two halves are queried separately because the tables disagree on shape:
        `flex_trade` has `trade_date_iso` (ISO) and `source`, and the sum is filtered to
        `source='flex'` with **no open/close filter**; `flex_lot` has neither column, so it
        takes compact `YYYYMMDD` bounds and no source predicate.
        """
        lo_iso, hi_iso = start.isoformat(), end.isoformat()
        lo_c, hi_c = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")

        nets = {
            str(r["asset_category"] or "?"): float(r["net"] or 0.0)
            for r in self._rows(
                "SELECT asset_category, SUM(fifo_pnl_realized) AS net FROM flex_trade "
                "WHERE source = 'flex' AND trade_date_iso BETWEEN ? AND ? "
                "GROUP BY asset_category",
                (lo_iso, hi_iso),
            )
        }
        lots = {
            str(r["asset_category"] or "?"): r
            for r in self._rows(
                """
                SELECT asset_category,
                       SUM(CASE WHEN fifo_pnl_realized > 0 THEN 1 ELSE 0 END) AS wins,
                       SUM(CASE WHEN fifo_pnl_realized < 0 THEN 1 ELSE 0 END) AS losses,
                       SUM(CASE WHEN COALESCE(fifo_pnl_realized, 0) = 0 THEN 1 ELSE 0 END) AS flat,
                       SUM(CASE WHEN fifo_pnl_realized > 0 THEN fifo_pnl_realized ELSE 0 END) AS gw,
                       SUM(CASE WHEN fifo_pnl_realized < 0 THEN fifo_pnl_realized ELSE 0 END) AS gl
                  FROM flex_lot
                 WHERE trade_date BETWEEN ? AND ?
                 GROUP BY asset_category
                """,
                (lo_c, hi_c),
            )
        }

        out = [
            TypeBreakdown(
                asset_class=asset,
                net=round(nets.get(asset, 0.0), 2),
                gross_win=round(float(lot["gw"] or 0.0) if lot is not None else 0.0, 2),
                gross_loss=round(float(lot["gl"] or 0.0) if lot is not None else 0.0, 2),
                winners=int(lot["wins"] or 0) if lot is not None else 0,
                losers=int(lot["losses"] or 0) if lot is not None else 0,
                scratches=int(lot["flat"] or 0) if lot is not None else 0,
            )
            for asset in sorted(set(nets) | set(lots))
            if (lot := lots.get(asset)) is not None or nets.get(asset)
        ]
        return tuple(sorted(out, key=lambda b: -abs(b.net)))

    # ── What the dataset holds ──────────────────────────────────────────────

    def coverage(self) -> FlexCoverage:
        """The newest statement trade date, or None when the dataset holds no statement row."""
        newest = self._rows("SELECT MAX(trade_date_iso) AS d FROM flex_trade WHERE source = 'flex'")[0]["d"]
        return FlexCoverage(through=_day(newest))

    def settled_execution_ids(self, ids: Iterable[str]) -> frozenset[str]:
        """The subset of `ids` IBKR has already put on a statement.

        An execution is settled if and only if its id is a `source='flex'` `execution_key`.
        Flex's key is IBKR's `ibExecID`, the same dotted id `/iserver/account/trades` reports
        as `execution_id` (measured 2026-09-24 in claudia_ui: 4 of 4 live ids found as Flex
        keys). A `source='live'` row is this package's own placeholder and settles nothing.

        The whole id list travels as one bound parameter through SQLite's `json_each`
        (https://www.sqlite.org/json1.html § 4.24), so the SQL text is fixed — nothing is
        interpolated — and no parameter-count limit applies however many ids are asked.
        """
        wanted = sorted(set(ids))
        if not wanted:
            return frozenset()
        rows = self._rows(
            "SELECT execution_key FROM flex_trade WHERE source = 'flex'"
            " AND execution_key IN (SELECT value FROM json_each(?))",
            (json.dumps(wanted),),
        )
        return frozenset(str(r["execution_key"]) for r in rows)

    def trade_ids(self) -> frozenset[str]:
        """Every IBKR `tradeID` the statements hold, as the XML archive spells them.

        `verify_flex_import` compares an archived statement's tradeIDs with this set: the
        question is whether the dataset every reader uses holds them. (It read the legacy
        `trades` table until 2.2.0, so a statement the complete-capture write had refused —
        `FlexArchiveResult.ok` False — still verified as imported.)
        """
        rows = self._rows("SELECT trade_id FROM flex_trade WHERE source = 'flex' AND trade_id IS NOT NULL")
        return frozenset(str(r["trade_id"]) for r in rows)

    # ── Executions ──────────────────────────────────────────────────────────

    def contract_executions(self, conids: Iterable[int]) -> tuple[FlexExecution, ...]:
        """Every statement execution of `conids`, grouped by contract in statement order.

        The order is explicit — `conid`, then IBKR's `trade_date`, the statement `date_time`,
        and the execution key as the last tie-break — because a FIFO over these rows is only
        as good as its order. Two fills of one contract can share a second (real statements
        hold such pairs, some at different prices), and the statement gives no finer clock,
        so the key makes the order deterministic rather than true.

        Contracts are matched by `conid`, never by symbol: a ticker is not a unique key.
        """
        wanted = sorted({int(c) for c in conids})
        if not wanted:
            return ()
        rows = self._rows(
            "SELECT execution_key, trade_id, account_id, conid, symbol, asset_category, currency,"
            " quantity, trade_price, ib_commission, multiplier, trade_date_iso, date_time_iso,"
            " fifo_pnl_realized"
            " FROM flex_trade"
            " WHERE source = 'flex'"
            " AND conid IN (SELECT value FROM json_each(?))"
            " ORDER BY conid, trade_date, date_time, execution_key",
            (json.dumps(wanted),),
        )
        return tuple(_execution(r) for r in rows)

    def executions(
        self,
        *,
        symbol: str | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> tuple[FlexExecution, ...]:
        """Statement executions, newest first, optionally filtered.

        Args:
            symbol: IBKR's statement symbol, matched whole and without regard to the case of
                its ASCII letters — SQLite's NOCASE, which folds those 26 and nothing else
                (https://www.sqlite.org/datatype3.html § 7). IBKR spells some listings
                in mixed case; the legacy table upper-cased them, the statement does not.
                For a future the symbol is the contract's local symbol (`ESU6`), not its
                root (`ES`).
            start: First trade date to include.
            end: Last trade date to include — inclusive, on IBKR's trade date.

        Summing `realised` over the result is the realised-P&L rule applied to the filter:
        with no `symbol` it equals `realised_window(start, end).total`.
        """
        rows = self._rows(
            "SELECT execution_key, trade_id, account_id, conid, symbol, asset_category, currency,"
            " quantity, trade_price, ib_commission, multiplier, trade_date_iso, date_time_iso,"
            " fifo_pnl_realized"
            " FROM flex_trade"
            " WHERE source = 'flex'"
            " AND (?1 IS NULL OR symbol = ?1 COLLATE NOCASE)"
            " AND (?2 IS NULL OR trade_date_iso >= ?2)"
            " AND (?3 IS NULL OR trade_date_iso <= ?3)"
            " ORDER BY trade_date DESC, date_time DESC, execution_key DESC",
            (
                symbol or None,
                start.isoformat() if start else None,
                end.isoformat() if end else None,
            ),
        )
        return tuple(_execution(r) for r in rows)
