"""Tests for `ibkr_core_mcp.flex_dataset` — the read side of the Flex dataset.

Every dataset here is built by the real parser and the real writer
(`flex_fixtures.seed_flex_dataset`), so the reader is tested against the schema it will
meet, not against a table shaped to fit it. Every figure, price, id and time is fabricated:
this package is public, and a captured figure's value is never what a test tests — the
shape of the case is (claudia_ui's rule, 2026-09-21).

The main fixture carries, deliberately, the four ways the realised-P&L rule has been broken
by a plausible "improvement" — each of them made for real during the 2026-08-04 dataset
rebuild, and each first pinned in claudia_ui's `tests/test_dashboard_data.py`:

  * a wash-sale-zeroed close (realises exactly 0.00 while its lot shows the loss),
  * an *opening* leg that realises (`openCloseIndicator="O"` with a non-zero figure),
  * a live Client Portal placeholder with no trade date at all,
  * a non-USD trade.

That the relocated queries give the operator's real answers — every day, week, month and
year, to the cent — is proven on the real store by the relocation's equivalence run
(claudia_ui `docs/plans/2026-09-30-flex-boundary-plan.md`), not by copying real figures here.
"""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from ibkr_core_mcp.exceptions import StoreError
from ibkr_core_mcp.flex_dataset import (
    UNOPENABLE,
    FlexCoverage,
    FlexDataset,
    RoundTripStats,
    TypeBreakdown,
    gain_pct_over,
    open_read_only,
)
from ibkr_core_mcp.store import SQLiteStore
from tests.flex_fixtures import lot, seed_flex_dataset, statement, trade

_TODAY = date(2026, 8, 6)  # a Thursday; its week starts Monday 2026-08-03


def _trade(n: int, day: str, asset: str, currency: str, open_close: str, pnl: float, **over: str) -> str:
    """Statement trade number `n` on ISO `day`, with ids no other row shares."""
    compact = day.replace("-", "")
    attrs = {
        "tradeID": str(7_000_000 + n),
        "transactionID": str(8_000_000 + n),
        "ibExecID": f"0000aaaa.{n:08d}.01.01",
        "tradeDate": compact,
        "reportDate": compact,
        "dateTime": f"{compact};{100000 + n:06d}",
        "assetCategory": asset,
        "currency": currency,
        "openCloseIndicator": open_close,
        "fifoPnlRealized": str(pnl),
    }
    attrs.update(over)
    return trade(**attrs)


# (trade date, asset, currency, open/close, fifoPnlRealized) — fabricated.
_TRADES = [
    # --- this week (Mon 2026-08-03 onwards) ---
    ("2026-08-03", "FUT", "USD", "C", -300.00),
    ("2026-08-03", "FUT", "USD", "O", 0.0),
    # An OPENING leg that realises: a buy closing a short and opening a long. Filtering on
    # the open/close indicator would drop this and understate the week by 125.00.
    ("2026-08-04", "STK", "USD", "O", 125.00),
    # A wash-sale-zeroed close: a real closing trade whose entire loss is disallowed.
    ("2026-08-05", "STK", "USD", "C", 0.0),
    ("2026-08-06", "STK", "USD", "C", 50.00),
    # --- earlier this month, before this week ---
    ("2026-08-01", "FUT", "USD", "C", -10.00),
    # --- earlier this year, before this month ---
    ("2026-03-10", "OPT", "USD", "C", -20.00),
    ("2026-02-02", "STK", "EUR", "C", -5.00),
    # --- last year: must never reach a 2026 window ---
    ("2025-12-31", "FUT", "USD", "C", 900.00),
]

# (trade date YYYYMMDD, asset, fifoPnlRealized) — closed lots, pre-wash-sale. Fabricated.
_LOTS = [
    ("20260803", "FUT", -300.00),
    ("20260804", "FUT", 125.00),
    ("20260805", "STK", -80.00),  # the pre-wash-sale detail behind the 0.00 trade above
    ("20260806", "FUT", 50.00),
    ("20260801", "STK", -10.00),
    ("20251231", "FUT", 900.00),
]

#: A fill captured from the Client Portal whose statement has not arrived: no trade date,
#: no realised figure. It must appear in no answer.
_PLACEHOLDER = {
    "execution_id": "0000live.00000001.01.01",
    "symbol": "TESTZ6",
    "side": "B",
    "size": 1,
    "price": 100.0,
    "time": "20260806-15:00:00",
    "commission": 1.25,
    "account": "U0000000",
}


def _seed(config, trades=_TRADES, lots=_LOTS, live=(_PLACEHOLDER,)):
    rows = [_trade(i, *row[:5], **(row[5] if len(row) > 5 else {})) for i, row in enumerate(trades, start=1)]
    rows += [lot(tradeDate=day, assetCategory=asset, fifoPnlRealized=str(pnl)) for day, asset, pnl in lots]
    seed_flex_dataset(config, statement("".join(rows), from_date="20250101", to_date="20260806"))
    if live:
        SQLiteStore(config).upsert_flex_trades_from_live(list(live))


def _sql(config, query: str, *params: object):
    """One value read with plain SQL — the independent side of a comparison."""
    conn = open_read_only(config.sqlite_path)
    try:
        return conn.execute(query, params).fetchone()[0]
    finally:
        conn.close()


def _write(config, statement_sql: str, *params: object) -> None:
    """A deliberate write into the TEST store — to build a state the writer never produces."""
    conn = sqlite3.connect(config.sqlite_path)
    try:
        conn.execute(statement_sql, params)
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def flex(mock_config):
    """The reader over the trap-carrying dataset described in the module docstring."""
    _seed(mock_config)
    with FlexDataset.open(mock_config.sqlite_path) as dataset:
        yield dataset


# ── Opening: read-only, never creating ────────────────────────────────────────


def test_the_connection_cannot_write(mock_config, flex):
    """A display surface must not be able to change the trade store."""
    conn = open_read_only(mock_config.sqlite_path)
    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("DELETE FROM flex_trade")
    finally:
        conn.close()
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        flex._conn.execute("DELETE FROM flex_trade")


def test_a_missing_store_is_an_error_and_is_not_created(tmp_path):
    missing = tmp_path / "nope.db"
    with pytest.raises(StoreError, match="unreadable"):
        FlexDataset.open(missing)
    assert list(tmp_path.iterdir()) == [], "opening a missing store created something"


def test_a_path_holding_uri_metacharacters_opens_that_file_and_no_other(mock_config, tmp_path):
    """SQLite reads a URI's query after `?`, its fragment after `#`, and decodes `%HH`. A
    hand-formatted `file:{path}?mode=ro` over such a path loses `mode=ro` and creates a
    different file read-write (measured 2026-09-30)."""
    odd_dir = tmp_path / "odd dir #1 ?x %41"
    odd_dir.mkdir()
    config = replace(mock_config, sqlite_path=odd_dir / "store.db")
    _seed(config)
    before = sorted(p.name for p in tmp_path.iterdir())

    with FlexDataset.open(config.sqlite_path) as dataset:
        assert dataset.coverage() == FlexCoverage(through=date(2026, 8, 6))

    assert sorted(p.name for p in tmp_path.iterdir()) == before, "the open created a file beside the directory"


def _marked(path: Path, marker: str) -> Path:
    """A database at `path` whose one row names it — a TEST store, written on purpose."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE marker (v)")
    conn.execute("INSERT INTO marker VALUES (?)", (marker,))
    conn.commit()
    conn.close()
    return path


def test_a_nul_is_refused_even_when_its_prefix_is_a_store(tmp_path):
    """A NUL names no file on any file system. Written as `%00` into the URI it would end the
    path, and the store at the prefix — a real one here — would open in place of an error
    (claudia_ui gap #89; plan § 13, item 16)."""
    _marked(tmp_path / "store", "the prefix")
    with pytest.raises(ValueError, match="NUL"):
        open_read_only(tmp_path / "store\x00.db")
    with pytest.raises(StoreError, match="unreadable"):
        FlexDataset.open(tmp_path / "store\x00.db")


def test_every_unopenable_error_is_one_the_readers_catch():
    """`UNOPENABLE` is the opener's whole error contract, stated once and imported by the
    never-raise readers in `flex_sync`: each case above raises one of its members."""
    assert set(UNOPENABLE) == {sqlite3.Error, OSError, TypeError, ValueError}
    assert all(issubclass(member, Exception) for member in UNOPENABLE)


def test_a_store_without_the_flex_tables_is_unreadable_not_empty(mock_config):
    """No tables means the dataset was never built. A figure from it would be a zero
    nobody measured, so every answer refuses instead."""
    SQLiteStore(mock_config).initialize()  # the legacy tables only
    with FlexDataset.open(mock_config.sqlite_path) as dataset:
        for ask in (
            lambda: dataset.realised_window(date(2026, 1, 1), _TODAY),
            lambda: dataset.realised_series(date(2026, 1, 1), _TODAY),
            lambda: dataset.round_trip_stats(date(2026, 1, 1), _TODAY),
            lambda: dataset.realised_by_type(date(2026, 1, 1), _TODAY),
            dataset.coverage,
            lambda: dataset.settled_execution_ids(["a"]),
            dataset.trade_ids,
            lambda: dataset.contract_executions([1]),
            dataset.executions,
        ):
            with pytest.raises(StoreError, match="unreadable"):
                ask()


def test_a_stored_date_that_does_not_parse_is_refused_not_guessed(mock_config):
    """The writer only ever stores ISO trade dates (`flex_import.normalise_date` refuses
    anything else); a row that holds something else is damage, and every answer that has to
    parse it says so rather than skipping or zeroing. `2026-08-99` sorts inside every range,
    so the series reaches it; a value sorting outside the range would be outside every
    window instead — the audit gate's check 5b is what proves no such row exists."""
    _seed(mock_config)
    _write(mock_config, "UPDATE flex_trade SET trade_date_iso = '2026-08-99' WHERE trade_id = 7000005")
    with FlexDataset.open(mock_config.sqlite_path) as dataset:
        for ask in (dataset.executions, dataset.coverage, lambda: dataset.realised_series(date.min, date.max)):
            with pytest.raises(StoreError, match="not an ISO date"):
                ask()
        # A window that does not reach the damaged row still answers.
        assert dataset.realised_window(date(2026, 8, 3), date(2026, 8, 4)).trade_count == 3


# ── Realised windows: the verified rule ───────────────────────────────────────


def test_week_total_matches_a_plain_unfiltered_sum(mock_config, flex):
    """-300.00 + 0.00 + 125.00 + 0.00 + 50.00, pinned against the same sum taken in SQL."""
    win = flex.realised_window(date(2026, 8, 3), _TODAY)
    expected = _sql(
        mock_config,
        "SELECT SUM(fifo_pnl_realized) FROM flex_trade WHERE source='flex'"
        " AND trade_date_iso BETWEEN '2026-08-03' AND '2026-08-06'",
    )
    assert win.total == pytest.approx(expected)
    assert win.total == pytest.approx(-125.00)
    assert (win.start, win.end) == (date(2026, 8, 3), _TODAY)


def test_opening_leg_that_realises_is_counted(mock_config, flex):
    """Trap 1: an `O` row with a non-zero figure is in the total. The same window with the
    wrong filter differs by exactly that row."""
    win = flex.realised_window(date(2026, 8, 3), _TODAY)
    with_filter = _sql(
        mock_config,
        "SELECT SUM(fifo_pnl_realized) FROM flex_trade WHERE source='flex'"
        " AND open_close_indicator LIKE '%C%'"
        " AND trade_date_iso BETWEEN '2026-08-03' AND '2026-08-06'",
    )
    assert win.total - with_filter == pytest.approx(125.00)


def test_wash_sale_zeroed_close_contributes_zero_not_the_lot_loss(mock_config, flex):
    """Trap 2: `flex_lot` is pre-wash-sale detail; its -80.00 must not leak into the total."""
    win = flex.realised_window(date(2026, 8, 3), _TODAY)
    lot_sum = _sql(
        mock_config,
        "SELECT SUM(fifo_pnl_realized) FROM flex_lot WHERE trade_date BETWEEN '20260803' AND '20260806'",
    )
    assert lot_sum == pytest.approx(-205.00)
    assert win.total != pytest.approx(lot_sum)


def test_live_rows_are_excluded_entirely(flex):
    """The placeholder has no trade date and is counted in no window."""
    ytd = flex.realised_window(date(2026, 1, 1), _TODAY)
    assert ytd.trade_count == 8  # every 2026 statement row; the placeholder and 2025 excluded
    assert flex.realised_window(date.min, date.max).trade_count == 9


def test_a_placeholder_is_excluded_by_its_source_not_by_its_missing_date(mock_config):
    """Were a placeholder ever to carry a trade date and a figure — which no writer produces
    (`live_trade_rows` leaves both NULL) — no answer may include it. The rule is
    `source = 'flex'`, not "has a date"."""
    _seed(mock_config)
    _write(
        mock_config,
        "UPDATE flex_trade SET trade_date_iso = ?, trade_date = ?, fifo_pnl_realized = 999999,"
        " asset_category = 'FUT', currency = 'USD' WHERE source = 'live'",
        "2026-08-05",
        "20260805",
    )
    with FlexDataset.open(mock_config.sqlite_path) as dataset:
        week = dataset.realised_window(date(2026, 8, 3), _TODAY)
        assert week.total == pytest.approx(-125.00)
        assert week.trade_count == 5
        assert dataset.realised_series(date(2026, 8, 3), _TODAY)[-1].cumulative == pytest.approx(-125.00)
        assert all(abs(r.net) < 10_000 for r in dataset.realised_by_type(date(2026, 8, 3), _TODAY))
        assert [e.execution_id for e in dataset.executions(start=date(2026, 8, 5), end=date(2026, 8, 5))] == [
            "0000aaaa.00000004.01.01"
        ]
    _write(mock_config, "UPDATE flex_trade SET trade_date_iso = '2026-12-31' WHERE source = 'live'")
    with FlexDataset.open(mock_config.sqlite_path) as dataset:
        assert dataset.coverage() == FlexCoverage(through=date(2026, 8, 6))


def test_year_boundary_excludes_last_years_trade(flex):
    ytd = flex.realised_window(date(2026, 1, 1), _TODAY)
    assert ytd.total == pytest.approx(-125.00 - 10.00 - 20.00 - 5.00)


def test_window_splits_by_asset_class(flex):
    ytd = flex.realised_window(date(2026, 1, 1), _TODAY)
    assert ytd.by_asset["FUT"] == pytest.approx(-310.00)
    assert ytd.by_asset["STK"] == pytest.approx(170.00)
    assert ytd.by_asset["OPT"] == pytest.approx(-20.00)
    assert ytd.asset_total("STK", "OPT") == pytest.approx(150.00)
    assert ytd.asset_total("NOPE") == 0.0


def test_currency_label_reports_mixed_rather_than_assuming_usd(flex):
    ytd = flex.realised_window(date(2026, 1, 1), _TODAY)
    assert set(ytd.currencies) == {"EUR", "USD"}
    assert ytd.currency_label == "mixed"
    assert flex.realised_window(date(2026, 8, 3), _TODAY).currency_label == "USD"


def test_an_empty_window_states_no_currency_rather_than_guessing_usd(flex):
    win = flex.realised_window(date(2026, 6, 1), date(2026, 6, 7))
    assert (win.total, win.trade_count, win.by_asset) == (0.0, 0, {})
    assert win.currency_label == ""


# ── Realised series ───────────────────────────────────────────────────────────


def test_series_is_daily_with_a_running_total(flex):
    pts = flex.realised_series(date(2026, 8, 3), _TODAY)
    assert [p.day for p in pts] == [date(2026, 8, 3), date(2026, 8, 4), date(2026, 8, 5), date(2026, 8, 6)]
    assert pts[0].realised == pytest.approx(-300.00)  # both 08-03 rows summed
    assert pts[-1].cumulative == pytest.approx(-125.00)
    assert pts[-1].cumulative == pytest.approx(flex.realised_window(date(2026, 8, 3), _TODAY).total)


def test_series_excludes_live_rows_and_other_years(flex):
    pts = flex.realised_series(date(2026, 1, 1), _TODAY)
    assert all(p.day.year == 2026 for p in pts)
    assert len(pts) == 7  # 08-03's two rows collapse into one point


# ── Round trips ───────────────────────────────────────────────────────────────


def test_round_trip_stats_counts_lots_not_executions(flex):
    st = flex.round_trip_stats(date(2026, 8, 3), _TODAY)
    assert (st.closed_lots, st.winners, st.losers, st.scratches) == (4, 2, 2, 0)
    assert st.gross_win == pytest.approx(175.00)
    assert st.gross_loss == pytest.approx(-380.00)
    assert st.win_rate == pytest.approx(50.0)


def test_round_trip_stats_uses_compact_dates_for_flex_lot(flex):
    """`flex_lot` has no ISO date column — ISO bounds would match nothing, silently."""
    assert flex.round_trip_stats(date(2026, 1, 1), _TODAY).closed_lots == 5  # the 2025 lot excluded
    assert flex.round_trip_stats(date(2025, 1, 1), date(2025, 12, 31)).closed_lots == 1


def test_win_rate_excludes_scratches_and_is_none_when_nothing_closed(flex):
    empty = flex.round_trip_stats(date(2026, 6, 1), date(2026, 6, 7))
    assert (empty.closed_lots, empty.win_rate) == (0, None)
    scratch = RoundTripStats(
        start=date(2026, 1, 1),
        end=date(2026, 1, 2),
        closed_lots=3,
        winners=1,
        losers=1,
        scratches=1,
        gross_win=10.0,
        gross_loss=-5.0,
    )
    assert scratch.win_rate == pytest.approx(50.0)


# ── Coverage ──────────────────────────────────────────────────────────────────


def test_coverage_is_the_newest_statement_trade_date(flex):
    """The placeholder moves nothing: it has no trade date and is not a statement row."""
    assert flex.coverage() == FlexCoverage(through=date(2026, 8, 6))


def test_coverage_of_a_dataset_with_no_statement_row(mock_config):
    """Tables present, nothing settled: None, not a crash or a made-up date."""
    _seed(mock_config, trades=(), lots=())
    with FlexDataset.open(mock_config.sqlite_path) as dataset:
        assert dataset.coverage() == FlexCoverage(through=None)


# ── Per-asset-class breakdown ─────────────────────────────────────────────────

_BREAKDOWN_TRADES = [
    ("2026-08-03", "FUT", "USD", "C", -400.00),
    ("2026-08-04", "FUT", "USD", "C", 60.00),
    ("2026-08-04", "STK", "USD", "C", -90.00),
    ("2026-07-01", "FUT", "USD", "C", 11.00),  # outside the window
]
_BREAKDOWN_LOTS = [
    ("20260803", "FUT", -400.00),
    ("20260804", "FUT", 200.00),
    ("20260804", "FUT", -140.00),
    ("20260804", "STK", -90.00),
    ("20260804", "OPT", 0.0),  # a scratch: neither won nor lost, and no OPT trade at all
]


@pytest.fixture
def breakdown(mock_config):
    """FUT and STK activity, an OPT lot that realised nothing, and a live placeholder."""
    _seed(mock_config, trades=_BREAKDOWN_TRADES, lots=_BREAKDOWN_LOTS)
    with FlexDataset.open(mock_config.sqlite_path) as dataset:
        yield dataset


def test_breakdown_splits_by_asset_class(breakdown):
    by = {r.asset_class: r for r in breakdown.realised_by_type(date(2026, 8, 3), date(2026, 8, 6))}
    assert by["FUT"].net == pytest.approx(-340.00, abs=0.005)
    assert by["STK"].net == pytest.approx(-90.00, abs=0.005)


def test_breakdown_takes_money_from_trades_and_counts_from_lots(breakdown):
    """The two-source rule, pinned: `net` from `flex_trade`, counts and gross from `flex_lot`."""
    fut = next(r for r in breakdown.realised_by_type(date(2026, 8, 3), date(2026, 8, 6)) if r.asset_class == "FUT")
    assert fut.net == pytest.approx(-340.00, abs=0.005)
    assert fut.gross_win == pytest.approx(200.00, abs=0.005)
    assert fut.gross_loss == pytest.approx(-540.00, abs=0.005)
    assert fut.winners == 1 and fut.losers == 2


def test_net_is_the_trade_figure_where_the_lots_say_something_else(flex):
    """In the main fixture the two tables disagree, as they do on a real wash sale: STK
    realised +175.00 on its trades while its one closed lot shows -80.00, and FUT's lots
    carry the 125.00 and 50.00 that the statement booked to STK trades. A `net` read from
    the lots passes the test above — its lot sum equals its trade sum — which is how that
    test stayed green in claudia_ui with the rule unpinned (found by a mutation, 2026-09-30)."""
    by = {r.asset_class: r for r in flex.realised_by_type(date(2026, 8, 3), _TODAY)}
    assert by["STK"].net == pytest.approx(175.00)
    assert by["STK"].gross_win + by["STK"].gross_loss == pytest.approx(-80.00)
    assert by["FUT"].net == pytest.approx(-300.00)
    assert by["FUT"].gross_win + by["FUT"].gross_loss == pytest.approx(-125.00)


def test_breakdown_excludes_other_windows(breakdown):
    rows = breakdown.realised_by_type(date(2026, 8, 3), date(2026, 8, 6))
    assert sum(r.net for r in rows) == pytest.approx(-430.00, abs=0.005)  # the July 11.00 is not in it


def test_round_trip_stats_count_a_scratch_as_neither(breakdown):
    """The OPT lot realised exactly 0.00: closed, and neither a winner nor a loser."""
    st = breakdown.round_trip_stats(date(2026, 8, 4), date(2026, 8, 4))
    assert (st.closed_lots, st.winners, st.losers, st.scratches) == (4, 1, 2, 1)
    assert st.win_rate == pytest.approx(100.0 / 3)


def test_only_asset_classes_that_traded_appear(breakdown):
    assert [r.asset_class for r in breakdown.realised_by_type(date(2026, 8, 3), date(2026, 8, 3))] == ["FUT"]


def test_a_class_that_only_scratched_still_appears(breakdown):
    """OPT closed a lot at exactly 0.00 — activity with no money is still activity."""
    rows = breakdown.realised_by_type(date(2026, 8, 4), date(2026, 8, 4))
    opt = next(r for r in rows if r.asset_class == "OPT")
    assert opt.closed_lots == 1 and opt.scratches == 1 and opt.net == 0.0


def test_scratches_are_excluded_from_the_win_rate(breakdown):
    rows = breakdown.realised_by_type(date(2026, 8, 4), date(2026, 8, 4))
    assert next(r for r in rows if r.asset_class == "OPT").win_rate is None
    assert next(r for r in rows if r.asset_class == "FUT").win_rate == pytest.approx(50.0)


def test_rows_are_ordered_by_how_much_money_moved(breakdown):
    """By absolute net, then the stable order of the classes: never alphabetical."""
    rows = breakdown.realised_by_type(date(2026, 8, 3), date(2026, 8, 6))
    assert [r.asset_class for r in rows] == ["FUT", "STK", "OPT"]


def test_the_order_is_by_size_of_the_move_whatever_its_sign(mock_config):
    """A +500 class is read before a -100 one: absolute size, not the signed figure."""
    _seed(
        mock_config,
        trades=[("2026-08-04", "STK", "USD", "C", -100.0), ("2026-08-04", "FUT", "USD", "C", 500.0)],
        lots=(),
    )
    with FlexDataset.open(mock_config.sqlite_path) as dataset:
        rows = dataset.realised_by_type(date(2026, 8, 4), date(2026, 8, 4))
    assert [r.asset_class for r in rows] == ["FUT", "STK"]


def test_an_empty_window_returns_nothing(breakdown):
    assert breakdown.realised_by_type(date(2026, 8, 5), date(2026, 8, 5)) == ()


def test_averages_are_none_rather_than_zero_when_absent(breakdown):
    rows = breakdown.realised_by_type(date(2026, 8, 4), date(2026, 8, 4))
    opt = next(r for r in rows if r.asset_class == "OPT")
    assert opt.average_win is None and opt.average_loss is None


def test_win_loss_ratio_is_none_rather_than_infinite(mock_config):
    _seed(mock_config, trades=[("2026-08-04", "FUT", "USD", "C", 100.0)], lots=[("20260804", "FUT", 100.0)])
    with FlexDataset.open(mock_config.sqlite_path) as dataset:
        row = dataset.realised_by_type(date(2026, 8, 4), date(2026, 8, 4))[0]
    assert row.win_loss_ratio is None
    assert row.win_rate == pytest.approx(100.0)


def test_average_win_and_loss_expose_what_the_win_rate_hides(mock_config):
    """One large win against five small losses: a poor win RATE and a good result."""
    _seed(
        mock_config,
        trades=[("2026-08-04", "FUT", "USD", "C", 2400.0)],
        lots=[("20260804", "FUT", 3000.0)] + [("20260804", "FUT", -120.0)] * 5,
    )
    with FlexDataset.open(mock_config.sqlite_path) as dataset:
        row = dataset.realised_by_type(date(2026, 8, 4), date(2026, 8, 4))[0]
    assert row.win_rate == pytest.approx(16.67, abs=0.01)
    assert row.net == pytest.approx(2400.0)
    assert row.average_win == pytest.approx(3000.0)
    assert row.average_loss == pytest.approx(-120.0)
    assert row.win_loss_ratio == pytest.approx(5.0)


@pytest.mark.parametrize(
    ("gross_win", "gross_loss", "expected"),
    [(800.0, -500.0, 61.5), (500.0, -500.0, 50.0), (100.0, 0.0, 100.0), (0.0, -100.0, 0.0), (0.0, 0.0, None)],
)
def test_gain_pct_is_the_share_of_the_gross_traded_amount_that_was_gains(gross_win, gross_loss, expected):
    row = TypeBreakdown("FUT", 0.0, gross_win, gross_loss, 0, 0, 0)
    assert row.gain_pct == expected


def test_gain_pct_over_rows_is_computed_on_the_summed_gross_figures():
    rows = [TypeBreakdown("FUT", 0.0, 700.0, -100.0, 1, 1, 0), TypeBreakdown("STK", 0.0, 100.0, -400.0, 1, 1, 0)]
    assert gain_pct_over(rows) == 61.5
    assert gain_pct_over(iter(rows)) == 61.5, "a one-pass iterable must give the same answer"
    assert gain_pct_over([]) is None


# ── Settled execution ids, and the statements' trade ids ──────────────────────


@pytest.fixture
def keyed(mock_config):
    """Two statement executions keyed `a` and `b`, and the live placeholder."""
    _seed(
        mock_config,
        trades=[
            ("2026-08-03", "FUT", "USD", "C", 1.0, {"ibExecID": "a"}),
            ("2026-08-03", "FUT", "USD", "C", 2.0, {"ibExecID": "b"}),
        ],
        lots=(),
    )
    with FlexDataset.open(mock_config.sqlite_path) as dataset:
        yield dataset


def test_settled_ids_are_the_ones_the_statements_hold(keyed):
    assert keyed.settled_execution_ids(["a", "c"]) == frozenset({"a"})
    assert keyed.settled_execution_ids(iter(["b", "b", "a"])) == frozenset({"a", "b"})


def test_a_stored_live_row_does_not_settle_an_execution(keyed):
    """The placeholder is this package's own row, not IBKR's statement."""
    assert keyed.settled_execution_ids([_PLACEHOLDER["execution_id"]]) == frozenset()


def test_no_ids_asks_nothing(keyed):
    assert keyed.settled_execution_ids([]) == frozenset()


def test_an_id_is_data_never_sql(keyed):
    """The list travels as one bound JSON parameter; a quote in an id is just a character."""
    assert keyed.settled_execution_ids(["a' OR '1'='1", 'b"]', "a"]) == frozenset({"a"})


def test_trade_ids_are_the_statements_trade_ids_as_the_archive_spells_them(keyed):
    """What `verify_flex_import` compares an archived XML's tradeIDs with. A placeholder has
    no tradeID; the ids come back as the strings the XML carries."""
    assert keyed.trade_ids() == frozenset({"7000001", "7000002"})


# ── Executions ────────────────────────────────────────────────────────────────

_A, _B = 20001, 20002  # fabricated conids


@pytest.fixture
def book(mock_config):
    """Contract A's open, close and re-open, one contract-B fill, a row with no multiplier,
    two fills in one second, and a live placeholder on contract A. The oldest fill carries
    the key that sorts last (`z.1`), so an order taken from the keys alone is visibly wrong.
    Every figure is fabricated."""
    fut = {"assetCategory": "FUT", "currency": "USD", "openCloseIndicator": "O", "fifoPnlRealized": "0"}
    a = {**fut, "conid": str(_A), "symbol": "AAAZ6", "multiplier": "1000"}
    rows = [
        trade(
            **a,
            tradeID="1",
            transactionID="1",
            ibExecID="z.1",
            tradeDate="20260922",
            dateTime="20260922;100000",
            quantity="1",
            tradePrice="10.00",
            ibCommission="-2.00",
        ),
        trade(
            **{**a, "fifoPnlRealized": "796.00"},
            tradeID="2",
            transactionID="2",
            ibExecID="a.2",
            tradeDate="20260923",
            dateTime="20260923;090000",
            quantity="-1",
            tradePrice="10.80",
            ibCommission="-2.00",
            buySell="SELL",
        ),
        trade(
            **a,
            tradeID="3",
            transactionID="3",
            ibExecID="a.3",
            tradeDate="20260928",
            dateTime="20260928;110000",
            quantity="2",
            tradePrice="11.00",
            ibCommission="-4.00",
        ),
        trade(
            **{**a, "multiplier": ""},
            tradeID="4",
            transactionID="4",
            ibExecID="a.4",
            tradeDate="20260928",
            dateTime="20260928;120000",
            quantity="1",
            tradePrice="11.10",
            ibCommission="-2.00",
        ),
        # Two fills in the same second, stored in the opposite order to their keys.
        trade(
            **a,
            tradeID="6",
            transactionID="6",
            ibExecID="a.6",
            tradeDate="20260928",
            dateTime="20260928;130000",
            quantity="1",
            tradePrice="11.30",
            ibCommission="-2.00",
        ),
        trade(
            **a,
            tradeID="5",
            transactionID="5",
            ibExecID="a.5",
            tradeDate="20260928",
            dateTime="20260928;130000",
            quantity="1",
            tradePrice="11.20",
            ibCommission="-2.00",
        ),
        trade(
            **fut,
            conid=str(_B),
            symbol="BBBZ6",
            multiplier="50",
            tradeID="7",
            transactionID="7",
            ibExecID="b.1",
            tradeDate="20260928",
            dateTime="20260928;103000",
            quantity="-1",
            tradePrice="5000.00",
            ibCommission="-2.00",
            buySell="SELL",
        ),
    ]
    seed_flex_dataset(mock_config, statement("".join(rows), from_date="20260922", to_date="20260928"))
    SQLiteStore(mock_config).upsert_flex_trades_from_live(
        [{**_PLACEHOLDER, "execution_id": "a.9", "symbol": "AAAZ6", "conid": _A, "time": "20260929-01:00:00"}]
    )
    with FlexDataset.open(mock_config.sqlite_path) as dataset:
        yield dataset


def test_contract_executions_are_the_statement_rows_in_statement_order(book):
    rows = book.contract_executions([_A])
    # `z.1` is the oldest fill and sorts last by key: the order is the statement's, the key
    # only breaks a tie. `a.9` is a placeholder and is not a statement row.
    assert [e.execution_id for e in rows] == ["z.1", "a.2", "a.3", "a.4", "a.5", "a.6"]
    first = rows[0]
    assert (first.conid, first.symbol, first.asset_class, first.currency) == (_A, "AAAZ6", "FUT", "USD")
    assert (first.quantity, first.price, first.multiplier) == (1.0, 10.0, 1000.0)
    assert first.commission == 2.0  # Flex stores it negative; a cost is positive
    assert (first.trade_id, first.account) == (1, "U0000000")
    assert first.trade_date == date(2026, 9, 22)
    assert first.time == "2026-09-22T10:00:00"
    assert (rows[1].quantity, rows[1].realised) == (-1.0, 796.0)


def test_a_statement_row_without_a_multiplier_says_so(book):
    """None, never a defaulted 1.0: a futures fill priced at multiplier 1 is wrong by 1000x."""
    by_id = {e.execution_id: e for e in book.contract_executions([_A])}
    assert by_id["a.4"].multiplier is None


def test_two_fills_in_one_second_come_back_in_key_order(book):
    """The statement gives no finer clock; the key makes the order the same every time."""
    ids = [e.execution_id for e in book.contract_executions([_A])]
    assert ids.index("a.5") < ids.index("a.6")


def test_contract_executions_group_by_contract(book):
    rows = book.contract_executions([_B, _A, _B])
    assert [(e.conid, e.execution_id) for e in rows] == [
        (_A, "z.1"),
        (_A, "a.2"),
        (_A, "a.3"),
        (_A, "a.4"),
        (_A, "a.5"),
        (_A, "a.6"),
        (_B, "b.1"),
    ]


def test_contract_executions_of_nothing_and_of_an_unknown_contract(book):
    assert book.contract_executions([]) == ()
    assert book.contract_executions([1]) == ()


def test_executions_are_newest_first(book):
    ids = [e.execution_id for e in book.executions()]
    assert ids == ["a.6", "a.5", "a.4", "a.3", "b.1", "a.2", "z.1"]


def test_executions_filter_by_symbol_case_insensitively(book):
    assert {e.symbol for e in book.executions(symbol="bbbz6")} == {"BBBZ6"}
    assert book.executions(symbol="BBB") == (), "a future's statement symbol is its local symbol, not its root"


def test_a_symbol_ibkr_spells_in_mixed_case_is_found_in_any_case(mock_config):
    """IBKR spells some listings with a lowercase letter (a German share's `d` suffix, for
    one). The legacy table stored every symbol upper-cased and its reader upper-cased the
    question, so the two met; the statement keeps IBKR's spelling, so an upper-cased question
    alone finds nothing. SQLite's NOCASE folds the 26 ASCII letters and nothing else
    (https://www.sqlite.org/datatype3.html § 7) — every character a ticker spells."""
    from tests.flex_fixtures import seed_flex_dataset, statement, trade

    seed_flex_dataset(mock_config, statement(trade(symbol="TSTd")))
    with FlexDataset.open(mock_config.sqlite_path) as dataset:
        for asked in ("TSTd", "TSTD", "tstd"):
            assert [e.symbol for e in dataset.executions(symbol=asked)] == ["TSTd"], asked
        assert dataset.executions(symbol="TST") == ()


def test_executions_take_both_bounds_on_the_trade_date_inclusive(book):
    """The end day is included. The legacy reader compared a date against a timestamp, so
    `end='2026-09-23'` silently dropped every fill on the 23rd."""
    assert [e.execution_id for e in book.executions(start=date(2026, 9, 23), end=date(2026, 9, 23))] == ["a.2"]
    assert [e.execution_id for e in book.executions(end=date(2026, 9, 23))] == ["a.2", "z.1"]
    assert len(book.executions(start=date(2026, 9, 28))) == 5


def test_the_sum_over_executions_is_the_window_total(flex):
    """One read path: the listing and the window cannot disagree."""
    for start, end in ((date(2026, 8, 3), _TODAY), (date(2026, 1, 1), _TODAY), (date(2025, 1, 1), _TODAY)):
        listed = flex.executions(start=start, end=end)
        window = flex.realised_window(start, end)
        assert sum(e.realised for e in listed) == pytest.approx(window.total)
        assert len(listed) == window.trade_count


# ── One read-only opener for the package and its scripts ──────────────────────


def _sqlite_uri_queries(source: str) -> set[str]:
    """The functions (or `<module>`) holding a string that carries a SQLite URI query.

    `?mode=` in a string piece is how a hand-formatted URI looks, f-string parts included.
    Docstrings are skipped: prose may show the wrong form in order to warn against it.
    """
    import ast

    tree = ast.parse(source)
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    found: set[str] = set()

    def visit(node: ast.AST, function: str) -> None:
        for child in ast.iter_child_nodes(node):
            text = child.value if isinstance(child, ast.Constant) and isinstance(child.value, str) else None
            if text is not None and id(child) not in docstrings and "?mode=" in text:
                found.add(function)
            visit(child, child.name if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef) else function)

    visit(tree, "<module>")
    return found


def test_no_module_formats_a_sqlite_uri_by_hand():
    """`open_read_only` is the only place a `mode=` URI is built. A hand-formatted
    `f"file:{path}?mode=ro"` over a path holding `?`, `#` or `%` opens — and creates — a
    different file read-write (measured 2026-09-30); two scripts carried it, one of them in
    the check that stops a rebuild destroying live fills."""
    from pathlib import Path

    import ibkr_core_mcp

    package = Path(ibkr_core_mcp.__file__).resolve().parent
    sites: dict[str, set[str]] = {}
    for directory in (package, package.parent / "scripts"):
        for path in sorted(directory.rglob("*.py")):
            if found := _sqlite_uri_queries(path.read_text()):
                sites[path.name] = found
    assert sites == {"flex_dataset.py": {"open_read_only"}}, sites


def test_the_uri_probe_sees_the_hand_formatted_form():
    snippet = '''
def ok():
    """Never write f"file:{path}?mode=ro" by hand."""

def bad(path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)

TOP = "file:x.db?mode=rw"
'''
    assert _sqlite_uri_queries(snippet) == {"bad", "<module>"}
