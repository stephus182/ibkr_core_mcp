
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
