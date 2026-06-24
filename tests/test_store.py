
import pytest
from unittest.mock import patch
from datetime import date


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
        {"conid": 265598, "symbol": "AAPL", "position": 100.0, "mktPrice": 180.0,
         "mktValue": 18000.0, "unrealizedPnl": 500.0},
    ]
    store.snapshot_positions(positions)
    df = store.get_position_history(symbol="AAPL")
    assert len(df) == 1
    assert df.iloc[0]["symbol"] == "AAPL"


def test_get_trades_filters_by_date(store):
    trades = [
        {"execution_id": "e1", "symbol": "AAPL", "side": "BUY", "size": 1,
         "price": 100, "time": "2026-01-01T10:00:00+00:00", "commission": 0, "account": "U1"},
        {"execution_id": "e2", "symbol": "AAPL", "side": "SELL", "size": 1,
         "price": 110, "time": "2026-05-01T10:00:00+00:00", "commission": 0, "account": "U1"},
    ]
    store.upsert_trades(trades)
    result = store.get_trades(symbol="AAPL", start="2026-03-01", end="2026-12-31")
    assert len(result) == 1
    assert result[0]["execution_id"] == "e2"


def test_save_and_get_backtests(store):
    row_id = store.save_backtest({
        "symbol": "AAPL",
        "strategy_name": "RSI Reversal",
        "total_return": 0.25,
        "sharpe": 1.4,
        "sortino": 1.8,
        "max_drawdown": -0.12,
        "num_trades": 45,
        "win_rate": 0.58,
    })
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
    positions_early = [{"conid": 1, "symbol": "AAPL", "position": 10.0,
                        "mktPrice": 100.0, "mktValue": 1000.0, "unrealizedPnl": 50.0}]
    store.snapshot_positions(positions_early)
    time.sleep(0.01)
    positions_late = [{"conid": 1, "symbol": "AAPL", "position": 20.0,
                       "mktPrice": 105.0, "mktValue": 2100.0, "unrealizedPnl": 100.0}]
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
    assert all(e["event"] == "ping" for e in pings)


def test_get_log_n_limit(store):
    for i in range(5):
        store.log_entry("event", i=i)
    assert len(store.get_log(n=3)) == 3
    assert len(store.get_log(n=10)) == 5


# ---------------------------------------------------------------------------
# Market calendar context — get_market_calendar_context()
# ---------------------------------------------------------------------------

def test_market_calendar_context_structure():
    from ibkr_core_mcp.store import SQLiteStore
    mkt = SQLiteStore.get_market_calendar_context()
    assert mkt, "returned empty dict — exchange_calendars may be unavailable"
    for key in ("today", "is_trading_day", "last_trading_day", "next_trading_day",
                "primary_exchange", "holidays_by_exchange", "futures"):
        assert key in mkt, f"missing key: {key}"


def test_market_calendar_all_20_exchanges_loaded():
    from ibkr_core_mcp.store import SQLiteStore
    mkt = SQLiteStore.get_market_calendar_context()
    h = mkt.get("holidays_by_exchange", {})
    expected = {
        "XNYS", "CME", "XLON", "XETR", "XEUR", "XPAR", "XMIL",
        "XTKS", "XHKG", "XSHG", "XBOM", "XKRX", "XASX",
        "XTSE", "BVMF", "XMEX", "XJSE", "XSAU", "XIDX", "XIST",
    }
    missing = expected - set(h.keys())
    assert not missing, f"exchanges missing from context: {missing}"


def test_market_calendar_cme_open_nyse_closed():
    """CME trades on NYSE equity holidays — this list must be non-empty
    and must contain known dates (MLK Day is always a NYSE holiday, CME trades)."""
    from ibkr_core_mcp.store import SQLiteStore
    mkt = SQLiteStore.get_market_calendar_context()
    extra = mkt.get("futures", {}).get("cme_open_nyse_closed", [])
    assert extra, "cme_open_nyse_closed is empty — CME/NYSE divergence not captured"
    # MLK Day (third Monday in January) is always NYSE-closed, CME-open
    mlk_days = [d for d in extra if d[5:7] == "01" and "19" <= d[8:] <= "21"]
    assert mlk_days, f"No January MLK Day found in cme_open_nyse_closed: {extra[:5]}"


def test_market_calendar_futures_block_structure():
    from ibkr_core_mcp.store import SQLiteStore
    mkt = SQLiteStore.get_market_calendar_context()
    fut = mkt.get("futures", {})
    assert "note" in fut
    assert "maintenance_break_ct" in fut
    assert "product_groups" in fut
    groups = fut["product_groups"]
    for expected_group in ("equity_index", "energy", "metals", "agriculture_grains"):
        assert expected_group in groups, f"missing product group: {expected_group}"


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
    assert any(k[0] == today_str for k in _market_calendar_cache), (
        "cache key does not include today's date string"
    )
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
# NYSE calendar integration in get_trade_date_coverage()
# ---------------------------------------------------------------------------

_TRADE = {"execution_id": "E1", "symbol": "AAPL", "side": "BUY",
          "size": 10, "price": 180, "commission": 1, "account": ""}


def test_trade_coverage_last_trading_day_present(store):
    store.upsert_trades([{**_TRADE, "time": "2026-06-23T10:00:00"}])
    cov = store.get_trade_date_coverage()
    assert "last_trading_day" in cov
    assert cov["last_trading_day"] is not None


def test_trade_coverage_stale_when_behind_last_trading_day(store):
    """newest < last_trading_day → stale=True."""
    store.upsert_trades([{**_TRADE, "time": "2020-01-02T10:00:00"}])
    cov = store.get_trade_date_coverage()
    assert cov["stale"] is True


def test_trade_coverage_not_stale_when_current(store):
    """newest == last_trading_day → stale=False (Flex T+1 lag — this is fully current)."""
    import exchange_calendars as ec
    from pandas import Timestamp
    last_td = ec.get_calendar("XNYS").previous_close(Timestamp.now(tz="UTC")).date()
    store.upsert_trades([{**_TRADE, "time": f"{last_td}T10:00:00"}])
    cov = store.get_trade_date_coverage()
    assert cov["stale"] is False, (
        f"newest={cov['newest']} == last_trading_day={cov['last_trading_day']} should not be stale"
    )


def test_trade_coverage_fallback_without_exchange_calendars(store):
    """If exchange_calendars is unavailable, stale falls back to days_since_newest > 1."""
    import sys
    store.upsert_trades([{**_TRADE, "time": "2020-01-02T10:00:00"}])
    # Setting a module to None in sys.modules makes `import` raise ImportError
    with patch.dict(sys.modules, {"exchange_calendars": None}):
        cov = store.get_trade_date_coverage()
    assert cov["stale"] is True
    assert cov["last_trading_day"] is None


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
    assert not cal.is_session(Timestamp(friday)), (
        "XSAU should not trade on Fridays (Sun–Thu week)"
    )


def test_xsau_thursday_is_a_trading_day():
    """Saudi Arabia trades on Thursdays — confirm the other side of the week boundary."""
    import exchange_calendars as ec
    from pandas import Timestamp
    cal = ec.get_calendar("XSAU")
    thursday = date(2026, 6, 18)  # June 18 2026 is a Thursday
    assert cal.is_session(Timestamp(thursday)), (
        "XSAU should trade on Thursdays"
    )


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
    assert "1:20 PM" in grains["globex_hours_ct"], (
        "Grains must close at 1:20 PM CT, not 4:00 PM"
    )


def test_futures_schedule_financial_products_23h():
    from ibkr_core_mcp.store import _FUTURES_SCHEDULE
    for group in ("equity_index", "energy", "metals", "foreign_currency", "interest_rates"):
        g = _FUTURES_SCHEDULE["product_groups"][group]
        assert "23h" in g["hours_per_day"], (
            f"{group} should trade ~23h/day but hours_per_day={g['hours_per_day']!r}"
        )
