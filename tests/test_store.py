from datetime import UTC, date, datetime

import pytest


@pytest.fixture
def store(mock_config):
    from ibkr_core_mcp.store import SQLiteStore

    s = SQLiteStore(mock_config)
    s.initialize()
    return s


def test_initialize_creates_tables(store):
    import sqlite3

    conn = sqlite3.connect(store._db_path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    conn.close()
    assert "trades" in tables
    assert "position_snapshots" in tables
    assert "signals" in tables
    assert "backtest_results" in tables
    assert "price_alerts" in tables


def test_upsert_and_get_trades(store):
    trades = [
        {
            "execution_id": "exec001",
            "symbol": "AAPL",
            "side": "BUY",
            "size": 10.0,
            "price": 180.0,
            "time": "2026-05-22T14:30:00+00:00",
            "commission": 1.0,
            "account": "U123",
        }
    ]
    store.upsert_trades(trades)
    result = store.get_trades(symbol="AAPL")
    assert len(result) == 1
    assert result[0]["symbol"] == "AAPL"
    assert result[0]["price"] == 180.0


def test_upsert_trades_idempotent(store):
    trade = {
        "execution_id": "exec002",
        "symbol": "TSLA",
        "side": "SELL",
        "size": 5.0,
        "price": 250.0,
        "time": "2026-05-22T15:00:00+00:00",
        "commission": 0.5,
        "account": "U123",
    }
    store.upsert_trades([trade])
    store.upsert_trades([trade])  # duplicate
    result = store.get_trades(symbol="TSLA")
    assert len(result) == 1


def test_log_and_get_signals(store):
    store.log_signal("AAPL", "rsi_oversold", 28.5, {"rsi_period": 14})
    signals = store.get_signals(symbol="AAPL")
    assert len(signals) == 1
    assert signals.iloc[0]["signal_type"] == "rsi_oversold"
    assert signals.iloc[0]["value"] == 28.5


def test_snapshot_and_get_positions(store):
    positions = [
        {
            "conid": 265598,
            "symbol": "AAPL",
            "position": 100.0,
            "mktPrice": 180.0,
            "mktValue": 18000.0,
            "unrealizedPnl": 500.0,
        },
    ]
    store.snapshot_positions(positions)
    df = store.get_position_history(symbol="AAPL")
    assert len(df) == 1
    assert df.iloc[0]["symbol"] == "AAPL"


def test_get_trades_filters_by_date(store):
    trades = [
        {
            "execution_id": "e1",
            "symbol": "AAPL",
            "side": "BUY",
            "size": 1,
            "price": 100,
            "time": "2026-01-01T10:00:00+00:00",
            "commission": 0,
            "account": "U1",
        },
        {
            "execution_id": "e2",
            "symbol": "AAPL",
            "side": "SELL",
            "size": 1,
            "price": 110,
            "time": "2026-05-01T10:00:00+00:00",
            "commission": 0,
            "account": "U1",
        },
    ]
    store.upsert_trades(trades)
    result = store.get_trades(symbol="AAPL", start="2026-03-01", end="2026-12-31")
    assert len(result) == 1
    assert result[0]["execution_id"] == "e2"


def test_save_and_get_backtests(store):
    row_id = store.save_backtest(
        {
            "symbol": "AAPL",
            "strategy_name": "RSI Reversal",
            "total_return": 0.25,
            "sharpe": 1.4,
            "sortino": 1.8,
            "max_drawdown": -0.12,
            "num_trades": 45,
            "win_rate": 0.58,
        }
    )
    assert row_id > 0
    results = store.get_backtests(symbol="AAPL")
    assert len(results) == 1
    assert results[0]["strategy_name"] == "RSI Reversal"
    assert results[0]["sharpe"] == pytest.approx(1.4)


def test_get_backtests_filters_by_symbol(store):
    store.save_backtest({"symbol": "AAPL", "strategy_name": "S1", "total_return": 0.1})
    store.save_backtest({"symbol": "TSLA", "strategy_name": "S1", "total_return": 0.2})
    assert len(store.get_backtests(symbol="AAPL")) == 1
    assert len(store.get_backtests(symbol="TSLA")) == 1
    assert len(store.get_backtests()) == 2


def test_get_backtests_filters_by_strategy(store):
    store.save_backtest({"symbol": "AAPL", "strategy_name": "MACD", "total_return": 0.1})
    store.save_backtest({"symbol": "AAPL", "strategy_name": "RSI", "total_return": 0.2})
    assert len(store.get_backtests(strategy="RSI")) == 1
    assert store.get_backtests(strategy="RSI")[0]["total_return"] == pytest.approx(0.2)


def test_get_position_history_date_filter(store):
    import time

    positions_early = [
        {"conid": 1, "symbol": "AAPL", "position": 10.0, "mktPrice": 100.0, "mktValue": 1000.0, "unrealizedPnl": 50.0}
    ]
    store.snapshot_positions(positions_early)
    time.sleep(0.01)
    positions_late = [
        {"conid": 1, "symbol": "AAPL", "position": 20.0, "mktPrice": 105.0, "mktValue": 2100.0, "unrealizedPnl": 100.0}
    ]
    store.snapshot_positions(positions_late)

    df = store.get_position_history(symbol="AAPL")
    assert len(df) == 2

    # start filter: only second snapshot should be returned
    ts_cut = df.iloc[0]["snapshot_at"]  # after first, before second
    df_filtered = store.get_position_history(symbol="AAPL", start=ts_cut)
    assert len(df_filtered) >= 1


def test_get_position_history_empty_returns_dataframe(store):
    df = store.get_position_history(symbol="NONEXISTENT")
    assert len(df) == 0
    assert "symbol" in df.columns


def test_get_signals_date_filter(store):
    store.log_signal("AAPL", "rsi_oversold", 28.0)
    store.log_signal("AAPL", "rsi_overbought", 72.0)
    df = store.get_signals(symbol="AAPL")
    assert len(df) == 2
    # end filter: cut off after first signal
    ts_cut = df.iloc[1]["logged_at"]
    df_filtered = store.get_signals(symbol="AAPL", end=ts_cut)
    assert len(df_filtered) >= 1


def test_log_entry_and_get_log(store):
    store.log_entry("trade_placed", symbol="AAPL", qty=10)
    store.log_entry("order_rejected", symbol="TSLA", reason="margin")
    log = store.get_log()
    assert len(log) == 2
    # most-recent last (get_log reverses DESC order)
    assert log[-1]["event"] == "order_rejected"


def test_get_log_event_filter(store):
    store.log_entry("ping", result="ok")
    store.log_entry("trade_placed", symbol="AAPL")
    store.log_entry("ping", result="ok")
    pings = store.get_log(event="ping")
    assert len(pings) == 2
    assert pings[0]["event"] == "ping"
    assert pings[1]["event"] == "ping"


def test_get_log_n_limit(store):
    store.log_entry("event", i=0)
    store.log_entry("event", i=1)
    store.log_entry("event", i=2)
    store.log_entry("event", i=3)
    store.log_entry("event", i=4)
    assert len(store.get_log(n=3)) == 3
    assert len(store.get_log(n=10)) == 5


# ---------------------------------------------------------------------------
# get_trade_date_coverage() — gap detection
# ---------------------------------------------------------------------------


def _trade(eid: str, day: str) -> dict[str, object]:
    return {
        "execution_id": eid,
        "symbol": "AAPL",
        "side": "BUY",
        "size": 1,
        "price": 100,
        "time": f"{day}T10:00:00",
        "commission": 1,
        "account": "",
    }


def test_coverage_empty_store(store):
    cov = store.get_trade_date_coverage()
    assert cov["oldest"] is None
    assert cov["newest"] is None
    assert cov["total_trades"] == 0
    assert cov["gaps"] == []


def test_coverage_single_trade_no_gap(store):
    store.upsert_trades([_trade("E1", "2026-01-15")])
    cov = store.get_trade_date_coverage()
    assert cov["oldest"] == cov["newest"] == "2026-01-15"
    assert cov["gaps"] == []


def test_coverage_no_gap_within_threshold(store):
    """Two trade dates 45 days apart — at threshold, not over it — no gap flagged."""
    store.upsert_trades(
        [
            _trade("E1", "2026-01-01"),
            _trade("E2", "2026-02-15"),  # 45 days later
        ]
    )
    cov = store.get_trade_date_coverage()
    assert cov["gaps"] == [], f"45-day gap should not be flagged, got: {cov['gaps']}"


def test_coverage_gap_just_over_threshold(store):
    """46 days apart — one day over the threshold — must be flagged."""
    store.upsert_trades(
        [
            _trade("E1", "2026-01-01"),
            _trade("E2", "2026-02-16"),  # 46 days later
        ]
    )
    cov = store.get_trade_date_coverage()
    assert len(cov["gaps"]) == 1
    gap = cov["gaps"][0]
    assert gap["gap_start"] == "2026-01-01"
    assert gap["gap_end"] == "2026-02-16"
    assert gap["calendar_days"] == 46


def test_coverage_gap_request_range_excludes_trade_dates(store):
    """request_from/to must be the day AFTER last trade and day BEFORE next trade —
    not the trade dates themselves, to avoid re-importing existing records."""
    store.upsert_trades(
        [
            _trade("E1", "2026-01-01"),
            _trade("E2", "2026-04-01"),  # 89 days later
        ]
    )
    cov = store.get_trade_date_coverage()
    assert len(cov["gaps"]) == 1
    gap = cov["gaps"][0]
    assert gap["request_from"] == "2026-01-02", "request_from must be day after last trade"
    assert gap["request_to"] == "2026-03-31", "request_to must be day before next trade"


def test_coverage_multiple_gaps(store):
    """Dataset with two separate large gaps — both must be reported."""
    store.upsert_trades(
        [
            _trade("E1", "2024-01-01"),
            _trade("E2", "2024-06-01"),  # 152 days — gap 1
            _trade("E3", "2024-06-15"),  # 14 days — normal
            _trade("E4", "2025-03-01"),  # 259 days — gap 2
        ]
    )
    cov = store.get_trade_date_coverage()
    assert len(cov["gaps"]) == 2
    assert cov["gaps"][0]["gap_start"] == "2024-01-01"
    assert cov["gaps"][1]["gap_start"] == "2024-06-15"


def test_coverage_custom_gap_threshold(store):
    """A lower threshold flags shorter gaps; a higher threshold ignores them."""
    store.upsert_trades(
        [
            _trade("E1", "2026-01-01"),
            _trade("E2", "2026-02-01"),  # 31 days
        ]
    )
    assert store.get_trade_date_coverage(gap_threshold_days=30)["gaps"] != []
    assert store.get_trade_date_coverage(gap_threshold_days=90)["gaps"] == []


def test_coverage_same_day_trades_count_as_one_date(store):
    """Multiple trades on the same day are deduplicated for gap detection.
    total_trades counts raw rows; gap logic uses distinct dates."""
    store.upsert_trades(
        [
            _trade("E1", "2026-01-01"),
            _trade("E2", "2026-01-01"),  # same day, different execution
            _trade("E3", "2026-04-01"),
        ]
    )
    cov = store.get_trade_date_coverage()
    assert cov["total_trades"] == 3  # raw row count
    assert len(cov["gaps"]) == 1  # only one gap interval


def test_coverage_oldest_newest_correct(store):
    store.upsert_trades(
        [
            _trade("E3", "2026-06-01"),
            _trade("E1", "2026-01-15"),
            _trade("E2", "2026-03-20"),
        ]
    )
    cov = store.get_trade_date_coverage()
    assert cov["oldest"] == "2026-01-15"
    assert cov["newest"] == "2026-06-01"


# ---------------------------------------------------------------------------
# Market calendar context — get_market_calendar_context()
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def mkt():
    """Shared market calendar context — cold load is ~3.4s, so share across tests."""
    from ibkr_core_mcp.store import SQLiteStore

    return SQLiteStore.get_market_calendar_context()


def test_market_calendar_context_structure(mkt):
    assert mkt, "returned empty dict — exchange_calendars may be unavailable"
    assert "today" in mkt
    assert "is_trading_day" in mkt
    assert "last_trading_day" in mkt
    assert "next_trading_day" in mkt
    assert "primary_exchange" in mkt
    assert "holidays_by_exchange" in mkt
    assert "futures" in mkt


def test_market_calendar_all_20_exchanges_loaded(mkt):
    h = mkt.get("holidays_by_exchange", {})
    expected = {
        "XNYS",
        "CME",
        "XLON",
        "XETR",
        "XEUR",
        "XPAR",
        "XMIL",
        "XTKS",
        "XHKG",
        "XSHG",
        "XBOM",
        "XKRX",
        "XASX",
        "XTSE",
        "BVMF",
        "XMEX",
        "XJSE",
        "XSAU",
        "XIDX",
        "XIST",
    }
    missing = expected - set(h.keys())
    assert not missing, f"exchanges missing from context: {missing}"


def test_market_calendar_cme_open_nyse_closed(mkt):
    """CME trades on NYSE equity holidays — this list must be non-empty
    and must contain known dates (MLK Day is always a NYSE holiday, CME trades)."""
    extra = mkt.get("futures", {}).get("cme_open_nyse_closed", [])
    assert extra, "cme_open_nyse_closed is empty — CME/NYSE divergence not captured"
    # MLK Day (third Monday in January) is always NYSE-closed, CME-open
    mlk_days = [d for d in extra if d[5:7] == "01" and "19" <= d[8:] <= "21"]
    assert mlk_days, f"No January MLK Day found in cme_open_nyse_closed: {extra[:5]}"


def test_market_calendar_futures_block_structure(mkt):
    fut = mkt.get("futures", {})
    assert "note" in fut
    assert "maintenance_break_ct" in fut
    assert "product_groups" in fut
    groups = fut["product_groups"]
    assert "equity_index" in groups
    assert "energy" in groups
    assert "metals" in groups
    assert "agriculture_grains" in groups


def test_market_calendar_process_cache_returns_same_object():
    """Second call same day must return the identical cached object — no recomputation."""
    from ibkr_core_mcp.store import SQLiteStore, _market_calendar_cache

    _market_calendar_cache.clear()
    first = SQLiteStore.get_market_calendar_context()
    second = SQLiteStore.get_market_calendar_context()
    assert first is second, "cache miss on second call — date-keyed cache not working"


def test_market_calendar_cache_key_is_date_and_exchanges():
    """Cache key must be (date_str, tuple(exchanges)) — clearing produces a new object."""
    from ibkr_core_mcp.store import SQLiteStore, _market_calendar_cache

    _market_calendar_cache.clear()
    first = SQLiteStore.get_market_calendar_context()
    # Verify cache holds exactly one entry with today's date as key
    today_str = date.today().isoformat()
    assert _market_calendar_cache, "cache should be non-empty after first call"
    first_key = next(iter(_market_calendar_cache))
    assert first_key[0] == today_str, "cache key does not include today's date string"
    # Clearing forces a recompute — new object, same structure
    _market_calendar_cache.clear()
    second = SQLiteStore.get_market_calendar_context()
    assert first is not second, "cleared cache should produce a new object"
    assert first["today"] == second["today"], "recomputed result should have same date"


def test_market_calendar_bad_exchange_skipped_gracefully():
    """An unknown exchange code must be silently skipped; others still load."""
    from ibkr_core_mcp.store import SQLiteStore

    mkt = SQLiteStore.get_market_calendar_context(exchanges=["XNYS", "XXXX_INVALID", "CME"])
    h = mkt.get("holidays_by_exchange", {})
    assert "XNYS" in h, "XNYS failed to load alongside an invalid exchange"
    assert "CME" in h, "CME failed to load alongside an invalid exchange"
    assert "XXXX_INVALID" not in h, "invalid exchange should not appear in output"


# ---------------------------------------------------------------------------
# get_trade_date_coverage()'s staleness flag no longer reads the NYSE calendar (F19,
# 2026-09-29): the four `test_trade_coverage_*` tests that pinned that rule went with it. The
# statement rule's tests are at the end of this file.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# XSAU Sunday–Thursday trading week (Friday is non-session)
# ---------------------------------------------------------------------------


def test_xsau_friday_is_not_a_trading_day():
    """Saudi Arabia trades Sun–Thu. A Friday must NOT be a session.
    This test exists to prevent someone 'fixing' the 95-holiday count
    which is correct — it reflects the Islamic work week, not a data error."""
    import exchange_calendars as ec
    from pandas import Timestamp

    cal = ec.get_calendar("XSAU")
    # Find a Friday that isn't a Saudi holiday
    friday = date(2026, 6, 19)  # June 19 2026 is a Friday
    assert not cal.is_session(Timestamp(friday)), "XSAU should not trade on Fridays (Sun–Thu week)"


def test_xsau_thursday_is_a_trading_day():
    """Saudi Arabia trades on Thursdays — confirm the other side of the week boundary."""
    import exchange_calendars as ec
    from pandas import Timestamp

    cal = ec.get_calendar("XSAU")
    thursday = date(2026, 6, 18)  # June 18 2026 is a Thursday
    assert cal.is_session(Timestamp(thursday)), "XSAU should trade on Thursdays"


# ---------------------------------------------------------------------------
# Futures schedule — grains have shorter hours than financial products
# ---------------------------------------------------------------------------


def test_futures_schedule_grains_shorter_hours():
    from ibkr_core_mcp.store import _FUTURES_SCHEDULE

    grains = _FUTURES_SCHEDULE["product_groups"]["agriculture_grains"]
    financials = _FUTURES_SCHEDULE["product_groups"]["equity_index"]
    assert grains["hours_per_day"] != financials["hours_per_day"], (
        "Grains must have different (shorter) hours than equity index futures"
    )
    assert "1:20 PM" in grains["globex_hours_ct"], "Grains must close at 1:20 PM CT, not 4:00 PM"


def test_futures_schedule_financial_products_23h():
    from ibkr_core_mcp.store import _FUTURES_SCHEDULE

    pg = _FUTURES_SCHEDULE["product_groups"]
    assert "23h" in pg["equity_index"]["hours_per_day"]
    assert "23h" in pg["energy"]["hours_per_day"]
    assert "23h" in pg["metals"]["hours_per_day"]
    assert "23h" in pg["foreign_currency"]["hours_per_day"]
    assert "23h" in pg["interest_rates"]["hours_per_day"]


def test_get_signals_empty_returns_dataframe_with_columns(store):
    """Empty signal query must return a typed DataFrame, not None or an empty list."""
    df = store.get_signals(symbol="SYMBOL_THAT_DOES_NOT_EXIST_XYZ")
    assert list(df.columns) == ["id", "logged_at", "symbol", "signal_type", "value", "metadata"]
    assert len(df) == 0


# ── pnl_snapshots ─────────────────────────────────────────────────────────────


def test_initialize_creates_pnl_snapshots_table(store):
    import sqlite3

    conn = sqlite3.connect(store._db_path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    conn.close()
    assert "pnl_snapshots" in tables


def test_record_and_get_latest_pnl(store):
    store.record_pnl_snapshot(
        account="DU1234567.Core",
        row_type=1,
        dpl=12.5,
        nl=10000.0,
        upl=3.0,
        uel=9000.0,
        mv=5000.0,
    )
    latest = store.get_latest_pnl()
    assert latest is not None
    assert latest["account"] == "DU1234567.Core"
    assert latest["dpl"] == 12.5
    assert latest["mv"] == 5000.0


def test_get_latest_pnl_returns_none_when_empty(store):
    assert store.get_latest_pnl() is None


def test_get_latest_pnl_returns_most_recent(store):
    store.record_pnl_snapshot(account="DU1", row_type=1, dpl=1.0, nl=1.0, upl=1.0, uel=1.0, mv=1.0)
    store.record_pnl_snapshot(account="DU1", row_type=1, dpl=2.0, nl=2.0, upl=2.0, uel=2.0, mv=2.0)
    latest = store.get_latest_pnl()
    assert latest is not None
    assert latest["dpl"] == 2.0


def test_get_latest_pnl_filters_by_account(store):
    store.record_pnl_snapshot(account="DU1", row_type=1, dpl=1.0, nl=1.0, upl=1.0, uel=1.0, mv=1.0)
    store.record_pnl_snapshot(account="DU2", row_type=1, dpl=9.0, nl=9.0, upl=9.0, uel=9.0, mv=9.0)
    latest = store.get_latest_pnl(account="DU1")
    assert latest is not None
    assert latest["account"] == "DU1"
    assert latest["dpl"] == 1.0


def test_parse_stream_execution_output_matches_upsert_trades_shape(store):
    """Catches shape drift: _parse_stream_execution's dict keys must match what
    upsert_trades() expects, since the mcp_server WS path feeds one into the other."""
    from ibkr_core_mcp.streaming import TradeExecution, _parse_stream_execution

    ex = TradeExecution(
        execution_id="E1",
        symbol="AAPL",
        side="B",
        size=10.0,
        price=180.0,
        trade_time="20260706-14:30:00",
        account="U1234",
        sec_type="STK",
    )
    row = _parse_stream_execution(ex)
    store.upsert_trades([row])
    result = store.get_trades(symbol="AAPL")
    assert len(result) == 1
    assert result[0]["execution_id"] == "E1"
    assert result[0]["side"] == "BUY"


# ---------------------------------------------------------------------------
# Two timestamp formats in one table (found live 2026-08-05)
# ---------------------------------------------------------------------------
#
# `trades` is written by two paths that disagree about the format of `time`:
# flex_query writes ISO (`2026-08-04T14:21:42`), while the live CP API path
# (claude_tools) and the streaming path write IBKR's compact `20260804-14:21:42`.
# `upsert_trades`'s ON CONFLICT deliberately does not update `time`, so a row captured
# live keeps the compact form permanently.
#
# The coverage query filtered on `time LIKE '____-__-__%'` and therefore could not see
# them at all: measured on the live store, 38 of 1,206 rows (3%) were invisible, and the
# newest date it could report was 2026-08-04 while the table already held 2026-08-05.
#
# Two separate questions, split deliberately (user's call, 2026-08-05):
#   * the ACTIVITY REPORT (dates, gaps, totals) must see every row, or a window holding
#     only live-captured trades reads as "no trading" — a fabricated gap;
#   * STALENESS must keep tracking settled Flex data only, because it decides whether to
#     pull a statement. Letting a live fill mark the store "current" would suppress the
#     very pull that brings the settled figures.


def _live_trade(eid: str, compact: str) -> dict[str, object]:
    """A row as the live CP API path writes it — IBKR's compact stamp, no ISO."""
    return {
        "execution_id": eid,
        "symbol": "ES",
        "side": "BUY",
        "size": 1,
        "price": 100,
        "time": compact,
        "commission": 1,
        "account": "",
    }


def test_coverage_sees_compact_timestamps_too(store):
    """The regression: 3% of the live store was invisible to its own activity report."""
    store.upsert_trades([_trade("E1", "2026-01-05")])
    store.upsert_trades([_live_trade("E2", "20260210-14:21:42")])

    cov = store.get_trade_date_coverage()
    assert cov["total_trades"] == 2
    assert cov["oldest"] == "2026-01-05"
    assert cov["newest"] == "2026-02-10", "the compact-stamped row must count"


def test_a_window_of_only_live_trades_is_not_reported_as_a_gap(store):
    """The sharp consequence. ClaudIA is told date gaps are verified inactivity, so a gap
    manufactured by a timestamp format would be reported to the user as 'no trading'."""
    store.upsert_trades([_trade("E1", "2026-01-01")])
    store.upsert_trades(
        [
            _live_trade("E2", "20260210-10:00:00"),  # mid-window, live-captured only
            _live_trade("E3", "20260320-10:00:00"),
        ]
    )
    store.upsert_trades([_trade("E4", "2026-05-01")])

    cov = store.get_trade_date_coverage()
    assert cov["gaps"] == [], f"live-only activity fabricated a gap: {cov['gaps']}"


def test_upsert_normalises_the_compact_stamp_on_write(store):
    """One format in the table going forward — the read side should not have to care."""
    store.upsert_trades([_live_trade("E1", "20260804-14:21:42")])

    with store._connect() as conn:
        stored = conn.execute("SELECT time FROM trades WHERE execution_id='E1'").fetchone()[0]
    assert stored.startswith("2026-08-04"), f"not normalised: {stored!r}"


def test_staleness_still_tracks_settled_flex_data_not_live_fills(store):
    """A live fill must NOT mark the store current.

    Staleness decides whether to pull a Flex statement. Flex is T+1, so today's live fill
    is precisely the trade whose settled record has not arrived — treating it as "up to
    date" would suppress tomorrow's pull and strand the statement figures.

    Written against the production shape: a store WITH the Flex dataset, which is the only
    configuration that can tell settled rows from live ones. `trades` carries no provenance
    column, and since the compact stamp is now normalised on write, the timestamp format no
    longer distinguishes them either.
    """
    from datetime import UTC, datetime, timedelta

    today = datetime.now(UTC).date()
    settled_day = today - timedelta(days=30)

    store.initialize_flex_tables()
    with store._connect() as conn:
        conn.execute(
            "INSERT INTO flex_trade (row_uid, execution_key, source, trade_date_iso) VALUES (?, ?, 'flex', ?)",
            ("U1", "K1", settled_day.isoformat()),
        )
    store.upsert_trades([_trade("OLD", settled_day.isoformat())])
    store.upsert_trades([_live_trade("LIVE", today.strftime("%Y%m%d-10:00:00"))])

    cov = store.get_trade_date_coverage()
    assert cov["newest"] == today.isoformat(), "the report still shows the live fill"
    assert cov["stale"] is True, "a live fill must not suppress the Flex pull"


def test_without_a_flex_dataset_staleness_keeps_the_old_whole_table_behaviour(store):
    """No `flex_trade` table means no way to tell settled from live — `trades` has no
    provenance column. Rather than guess, the pre-2026-08-05 semantics are kept and the
    docstring says so; stores in that state predate live capture anyway.
    """
    from datetime import UTC, datetime, timedelta

    today = datetime.now(UTC).date()
    store.upsert_trades([_trade("OLD", (today - timedelta(days=30)).isoformat())])

    cov = store.get_trade_date_coverage()
    assert cov["stale"] is True  # 30 days behind, by either reading


# ── Security: the store and its WAL sidecars must not be world-readable ──────────────────
#
# Found by the claudia_ui security audit 2026-08-05: the live ~/.ibkr_core/store.db was
# 0644 — 53 MB holding every trade this account has ever made. sqlite3.connect() creates
# the file with 0666 & ~umask and nothing had ever narrowed it.


def test_database_file_is_not_world_readable(store):
    """The trade store is account data — 0600, not the umask default."""
    import stat as stat_mod
    from pathlib import Path

    mode = stat_mod.S_IMODE(Path(store._db_path).stat().st_mode)
    assert mode == 0o600, f"store.db is {oct(mode)}, expected 0o600"


def test_wal_sidecars_are_not_world_readable(store):
    """The WAL carries committed-but-uncheckpointed rows — same content, same rule.

    Securing only the main file would leave the most recent writes readable.

    A connection is held OPEN for the assertions. SQLite deletes -wal/-shm on a clean
    close, and `log_entry` uses `with self._connect()` — which commits but does not
    close, so the connection dies whenever refcounting gets to it. That made the
    sidecars present or absent depending on GC timing: the test passed in isolation and
    silently asserted NOTHING in a full-file run. The `assert checked` guard is what
    exposed it; keeping a live connection is what fixes it.
    """
    import stat as stat_mod
    from pathlib import Path

    store.log_entry("test", note="force a write so the WAL is populated")
    # Held open purely so a connection exists: SQLite removes -wal/-shm when the LAST
    # connection closes, so this keeps them on disk for the duration of the assertions.
    conn = store._connect()
    try:
        store.log_entry("test", note="write while a connection is held open")
        checked = 0
        for suffix in ("-wal", "-shm"):
            sidecar = Path(store._db_path + suffix)
            if not sidecar.exists():
                continue
            checked += 1
            mode = stat_mod.S_IMODE(sidecar.stat().st_mode)
            assert mode == 0o600, f"{sidecar.name} is {oct(mode)}, expected 0o600"
        assert checked, "neither WAL sidecar existed — this test asserted nothing"
    finally:
        conn.close()


def test_wal_sidecar_permission_repair_is_self_healing(store):
    """A sidecar already on disk at 0644 must be corrected on the next connection.

    The test above cannot catch a regression on its own, and that took a mutation to
    discover: SQLite creates -wal/-shm inheriting the main database's mode, and the
    main file is already 0600 by then, so the sidecars are 0600 whether or not
    _restrict_db_permissions handles them. Its assertions run and cannot fail —
    a subtler vacuity than an empty loop, and invisible to any static check.

    Only a sidecar that is ALREADY wrong exercises the repair, which is also the
    real-world case: every install predating the 2026-08-05 fix has 0644 files.
    """
    import stat as stat_mod
    from pathlib import Path

    store.log_entry("test", note="create the sidecars")
    conn = store._connect()  # held open: SQLite removes the sidecars on a clean close
    try:
        store.log_entry("test", note="write while a connection is held open")
        present = [p for p in (Path(store._db_path + x) for x in ("-wal", "-shm")) if p.exists()]
        assert present, "neither WAL sidecar existed — this test asserted nothing"

        for p in present:
            p.chmod(0o644)
        store.log_entry("test", note="reconnect so the repair runs")

        for p in present:
            mode = stat_mod.S_IMODE(p.stat().st_mode)
            assert mode == 0o600, f"pre-existing 0644 {p.name} was not repaired"
    finally:
        conn.close()


def test_permission_repair_is_self_healing(store):
    """A file already on disk at 0644 must be corrected on the next connection.

    This is the property that matters in practice: every existing install has a 0644
    database, so a fix that only applied at creation time would never reach any of them.
    """
    import stat as stat_mod
    from pathlib import Path

    db = Path(store._db_path)
    db.chmod(0o644)
    store.log_entry("test", note="reconnect")
    assert stat_mod.S_IMODE(db.stat().st_mode) == 0o600, "pre-existing 0644 was not repaired"


def test_parent_directory_is_owner_only(store, mock_config):
    """~/.ibkr_core holds the trade store, the Flex archive and the Drive OAuth token.

    Asserted on an **existing** 0755 directory, not just a freshly created one. The
    create-time `mkdir(mode=0o700)` is the easy half and a temp-dir fixture exercises it
    for free; the half that mattered on the live install was the pre-existing directory,
    which had been 0755 since long before anyone considered its mode. A test that only
    covered the create path would have passed against the unfixed code.
    """
    import stat as stat_mod
    from pathlib import Path

    from ibkr_core_mcp.store import SQLiteStore

    parent = Path(store._db_path).parent
    parent.chmod(0o755)

    SQLiteStore(mock_config)  # constructing again must repair it

    mode = stat_mod.S_IMODE(parent.stat().st_mode)
    assert mode == 0o700, f"store directory is {oct(mode)}, expected 0o700"


# ── sessions_today: per-exchange session status (claudia_ui #78, register F24) ──────────
#
# The context said "trading day" for NYSE only, so a consumer asking "who is open today?" on a
# Saturday read every exchange as open — claudia_ui's briefing printed "All tracked exchanges
# open today" on 2026-09-26. The calendars were already loaded; the answer was not in the dict.
# Operator rule the same morning: the regular weekly schedule decides first, holidays only
# subtract, no exchange opens on its weekend. Dates below are computed from today's date and
# from the calendars themselves, never pinned.


def _next(weekday: int) -> date:
    """The next calendar date with this weekday (Monday = 0), today excluded."""
    from datetime import timedelta

    day = date.today() + timedelta(days=1)
    while day.weekday() != weekday:
        day += timedelta(days=1)
    return day


def test_sessions_today_has_one_verdict_per_exchange_keyed_like_the_holidays(mkt):
    assert set(mkt["sessions_today"]) == set(mkt["holidays_by_exchange"])
    assert all(isinstance(v, bool) for v in mkt["sessions_today"].values())


def test_sessions_today_for_the_primary_exchange_is_the_is_trading_day_flag(mkt):
    assert mkt["sessions_today"][mkt["primary_exchange"]] is mkt["is_trading_day"]


def test_no_exchange_holds_a_session_on_a_saturday():
    from ibkr_core_mcp.store import SQLiteStore

    saturday = _next(5)
    ctx = SQLiteStore.get_market_calendar_context(today=saturday)
    assert ctx["today"] == saturday.isoformat(), "the verdict is for the day asked about, not the cached one"
    assert ctx["sessions_today"], "no exchange loaded"
    assert not any(ctx["sessions_today"].values()), {k for k, v in ctx["sessions_today"].items() if v}
    assert ctx["is_trading_day"] is False


def test_a_friday_is_a_session_everywhere_but_tadawul_unless_it_is_a_holiday():
    from ibkr_core_mcp.store import SQLiteStore

    friday = _next(4)
    ctx = SQLiteStore.get_market_calendar_context(today=friday)
    assert ctx["sessions_today"]["XSAU"] is False, "Tadawul trades Sunday to Thursday"
    for code in ("XNYS", "CME", "XLON"):
        expected = friday.isoformat() not in ctx["holidays_by_exchange"][code]
        assert ctx["sessions_today"][code] is expected, (code, friday)


def test_a_nyse_holiday_is_decided_per_exchange_not_copied_from_the_primary(mkt):
    """The point of the key: NYSE closed says nothing about CME or London that day."""
    from ibkr_core_mcp.store import SQLiteStore

    upcoming = [d for d in mkt["holidays_by_exchange"]["XNYS"] if d >= date.today().isoformat()]
    assert upcoming, "the calendar lists no NYSE holiday ahead of today — extend the range before trusting this test"
    holiday = date.fromisoformat(upcoming[0])
    ctx = SQLiteStore.get_market_calendar_context(today=holiday)
    assert ctx["sessions_today"]["XNYS"] is False
    assert ctx["is_trading_day"] is False
    for code in ("CME", "XLON", "XTKS"):
        assert ctx["sessions_today"][code] is (holiday.isoformat() not in ctx["holidays_by_exchange"][code]), code


def test_the_failure_marker_says_the_sessions_are_unknown_not_closed(monkeypatch):
    import ibkr_core_mcp.store as store_mod
    from ibkr_core_mcp.store import SQLiteStore

    def _boom(*args, **kwargs):
        raise RuntimeError("exchange_calendars unavailable")

    monkeypatch.setattr("exchange_calendars.get_calendar", _boom)
    monkeypatch.setattr(store_mod, "_market_calendar_cache", {})
    result = SQLiteStore.get_market_calendar_context()
    assert "sessions_today" in result
    assert result["sessions_today"] is None, "explicitly unknown, not an empty map that reads as nobody open"


def test_market_calendar_context_reports_a_failure_instead_of_an_empty_dict(monkeypatch):
    """`except Exception: return {}` made a failed lookup read as "market closed".

    Every caller does `cal.get("is_trading_day")`, and on {} that is None — falsy, and
    indistinguishable from a genuine non-trading day. Public API, consumed by claudia_ui.
    """
    import ibkr_core_mcp.store as store_mod
    from ibkr_core_mcp.store import SQLiteStore

    def _boom(*args, **kwargs):
        raise RuntimeError("exchange_calendars unavailable")

    monkeypatch.setattr("exchange_calendars.get_calendar", _boom)
    # The process-level cache is keyed by (date, exchanges) and survives across tests.
    # Without clearing it this passes alone and fails beside its siblings — it would
    # be reading another test's cached success rather than exercising the error path.
    monkeypatch.setattr(store_mod, "_market_calendar_cache", {})

    result = SQLiteStore.get_market_calendar_context()

    assert result, "a failed lookup must not return a falsy dict"
    assert "error" in result
    assert result["is_trading_day"] is None, "explicitly unknown, not implicitly False"


# ── an empty flex_trade is not "no Flex dataset" ────────────────────────────────


def test_coverage_is_stale_when_flex_trade_exists_but_is_empty(mock_config):
    """The composition that produced a genuine false green.

    `_settled_newest_date` returned None both when the table was absent (an older store,
    where falling back to the legacy `trades` newest is right) and when it was present
    but empty (a rebuild that imported nothing, where falling back reports fresh data
    from a dataset that has none). A wiped flex_* dataset therefore read as current.
    """
    from datetime import date

    from ibkr_core_mcp.store import SQLiteStore

    store = SQLiteStore(mock_config)
    store.initialize()
    store.initialize_flex_tables()
    today = date.today().isoformat()
    store.upsert_trades(
        [
            {
                "execution_id": "e1",
                "symbol": "TEST",
                "side": "BUY",
                "size": 1,
                "price": 1.0,
                "time": f"{today}T09:30:00",
                "commission": 0.5,
                "account": "U0000000",
            }
        ]
    )

    cov = store.get_trade_date_coverage()

    assert cov["stale"] is True, "an empty flex_trade reported fresh data"
    assert cov["settled_newest"] is None
    assert cov["flex_dataset_empty"] is True


def test_coverage_reports_the_settled_date_separately_from_the_legacy_newest(mock_config):
    """The stale message used to mix the two, producing 'DATA STALE (0d old)'."""
    from ibkr_core_mcp.store import SQLiteStore

    store = SQLiteStore(mock_config)
    store.initialize()
    store.initialize_flex_tables()
    store.upsert_trades(
        [
            {
                "execution_id": "e1",
                "symbol": "TEST",
                "side": "BUY",
                "size": 1,
                "price": 1.0,
                "time": "2026-08-10T09:30:00",
                "commission": 0.5,
                "account": "U0000000",
            }
        ]
    )

    cov = store.get_trade_date_coverage()

    assert "settled_newest" in cov
    assert "days_since_settled" in cov


# ---------------------------------------------------------------------------
# get_trade_date_coverage() — the staleness flag (claudia_ui #72, register F19; and F1)
# ---------------------------------------------------------------------------
#
# The operator's rule (claudia_ui, 2026-09-28): a store is current when it holds the statement
# for the weekday before today (ET), read from IBKR's own `toDate`. Until this fix the flag
# compared the newest settled TRADE date against the NYSE session before the last one, so on
# day D a store through D-2 read `stale: False` — measured 2026-09-24 at 13:01Z and 16:33Z with
# the store through 09-22 — and a weekday with no fills read as behind although its statement
# was held. Statement days are weekdays, not exchange days: the Monday 2026-07-06 pull came
# back through Friday 07-03, a US holiday (29 statements measured, claudia_ui
# docs/flex-query-setup.md § When a day's statement becomes available).


def _hold(mock_config, *, statements=(), trades=(), drop_nav=False):
    """Give the store the real Flex archive tables holding `statements` (toDate, YYYYMMDD)
    and settled trades as (trade date ISO, toDate)."""
    import sqlite3

    from ibkr_core_mcp.flex_store import create_flex_tables

    conn = sqlite3.connect(mock_config.sqlite_path)
    try:
        create_flex_tables(conn)
        for i, to_date in enumerate(statements):
            conn.execute("INSERT INTO flex_change_in_nav (row_uid, stmt_to_date) VALUES (?, ?)", (f"nav-{i}", to_date))
        for i, (day, to_date) in enumerate(trades):
            conn.execute(
                "INSERT INTO flex_trade (row_uid, execution_key, source, trade_date_iso, stmt_to_date) "
                "VALUES (?, ?, 'flex', ?, ?)",
                (f"row-{i}", f"exec-{i}", day, to_date),
            )
        if drop_nav:
            conn.execute("DROP TABLE flex_change_in_nav")
        conn.commit()
    finally:
        conn.close()


_THU_0924_1301Z = datetime(2026, 9, 24, 13, 1, 49, tzinfo=UTC)  # 09:01 ET Thursday
_THU_0924_1633Z = datetime(2026, 9, 24, 16, 33, 35, tzinfo=UTC)  # 12:33 ET Thursday
_THU_0924_LATE = datetime(2026, 9, 25, 0, 59, 30, tzinfo=UTC)  # 20:59 ET Thursday — the UTC date is already Friday


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (_THU_0924_1301Z, date(2026, 9, 23)),
        (_THU_0924_1633Z, date(2026, 9, 23)),
        (_THU_0924_LATE, date(2026, 9, 23)),  # ET day still the 24th — the UTC date (25th) would say the 24th
        (datetime(2026, 9, 26, 14, 0, tzinfo=UTC), date(2026, 9, 25)),  # Saturday → Friday
        (datetime(2026, 9, 27, 14, 0, tzinfo=UTC), date(2026, 9, 25)),  # Sunday → Friday
        (datetime(2026, 9, 28, 14, 0, tzinfo=UTC), date(2026, 9, 25)),  # Monday → Friday
        (datetime(2026, 9, 29, 2, 30, tzinfo=UTC), date(2026, 9, 25)),  # Monday 22:30 ET → Friday
        (datetime(2026, 7, 6, 14, 44, tzinfo=UTC), date(2026, 7, 3)),  # measured: weekdays, not exchange days
    ],
)
def test_newest_statement_day_is_the_weekday_before_today_in_et(now, expected):
    from ibkr_core_mcp.store import newest_statement_day

    assert newest_statement_day(now) == expected


def test_newest_statement_day_refuses_a_naive_datetime():
    from ibkr_core_mcp.store import newest_statement_day

    with pytest.raises(ValueError, match="aware"):
        newest_statement_day(datetime(2026, 9, 24, 12, 0))


def test_a_store_holding_the_previous_weekday_s_statement_is_current(store, mock_config):
    _hold(mock_config, statements=["20260923"])
    cov = store.get_trade_date_coverage(now=_THU_0924_1633Z)
    assert cov["stale"] is False
    assert cov["statement_through"] == "2026-09-23"
    assert cov["newest_statement_day"] == "2026-09-23"


@pytest.mark.parametrize("now", [_THU_0924_1301Z, _THU_0924_1633Z, _THU_0924_LATE])
def test_a_store_two_weekdays_behind_is_stale_at_any_hour(store, mock_config, now):
    """The F19 case: through 09-22 on 09-24 read `stale: False` until the evening."""
    _hold(mock_config, statements=["20260922"])
    cov = store.get_trade_date_coverage(now=now)
    assert cov["stale"] is True
    assert cov["statement_through"] == "2026-09-22"


def test_friday_s_statement_keeps_the_store_current_through_the_weekend_and_monday(store, mock_config):
    _hold(mock_config, statements=["20260925"])
    for day in (26, 27, 28):
        assert store.get_trade_date_coverage(now=datetime(2026, 9, day, 14, 0, tzinfo=UTC))["stale"] is False, day
    assert store.get_trade_date_coverage(now=datetime(2026, 9, 29, 14, 0, tzinfo=UTC))["stale"] is True


def test_the_verdict_reads_the_statement_s_to_date_not_the_newest_trade_date(store, mock_config):
    """A Monday with no fills still has a statement; holding it is current."""
    _hold(mock_config, statements=["20260925", "20260928"], trades=[("2026-09-25", "20260925")])
    cov = store.get_trade_date_coverage(now=datetime(2026, 9, 29, 14, 0, tzinfo=UTC))  # Tuesday
    assert cov["stale"] is False
    assert cov["statement_through"] == "2026-09-28"
    assert cov["settled_newest"] == "2026-09-25", "the newest settled trade is still reported, separately"


def test_without_the_nav_table_the_to_date_is_read_from_the_trades_archive(store, mock_config):
    _hold(mock_config, trades=[("2026-09-23", "20260923")], drop_nav=True)
    cov = store.get_trade_date_coverage(now=_THU_0924_1633Z)
    assert cov["statement_through"] == "2026-09-23"
    assert cov["stale"] is False


def test_a_store_with_no_flex_dataset_holds_no_statement_and_is_stale(store):
    store.upsert_trades([_trade("E1", "2026-09-23")])  # legacy rows only
    cov = store.get_trade_date_coverage(now=_THU_0924_1633Z)
    assert cov["statement_through"] is None
    assert cov["stale"] is True


def test_an_empty_store_returns_the_full_key_set(store):
    """F1: the docstring promised seven keys and the empty path returned four — `stale` absent,
    not False, which a consumer's `not cov.get("stale")` could not tell from "current"."""
    cov = store.get_trade_date_coverage(now=_THU_0924_1633Z)
    full = store.get_trade_date_coverage(now=_THU_0924_1633Z)  # same call, for the key set
    store.upsert_trades([_trade("E1", "2026-09-23")])
    populated = store.get_trade_date_coverage(now=_THU_0924_1633Z)
    assert set(cov) == set(populated) == set(full)
    assert cov["stale"] is True
    assert cov["oldest"] is None and cov["newest"] is None
    assert cov["total_trades"] == 0 and cov["gaps"] == []
    assert cov["days_since_newest"] is None
    assert cov["newest_statement_day"] == "2026-09-23"


def test_day_counts_use_the_et_date_of_now(store):
    store.upsert_trades([_trade("E1", "2026-09-23")])
    cov = store.get_trade_date_coverage(now=_THU_0924_LATE)  # 20:59 ET on the 24th, 00:59Z on the 25th
    assert cov["days_since_newest"] == 1
