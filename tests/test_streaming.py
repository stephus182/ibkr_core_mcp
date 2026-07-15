import json

import pytest

# ── SQLiteStore alert methods (sync) ─────────────────────────────────────────

def test_add_and_get_alert(tmp_db, mock_config):
    from ibkr_core_mcp.store import SQLiteStore
    store = SQLiteStore(mock_config)
    aid = store.add_alert(265598, "AAPL", 190.0, "above")
    assert isinstance(aid, int) and aid > 0
    alerts = store.get_alerts(active_only=True)
    assert len(alerts) == 1
    assert alerts[0]["symbol"] == "AAPL"
    assert alerts[0]["direction"] == "above"
    assert alerts[0]["triggered_at"] is None


def test_add_alert_invalid_direction(tmp_db, mock_config):
    from ibkr_core_mcp.store import SQLiteStore
    store = SQLiteStore(mock_config)
    with pytest.raises(ValueError, match="direction"):
        store.add_alert(265598, "AAPL", 190.0, "sideways")


def test_mark_alert_triggered(tmp_db, mock_config):
    from ibkr_core_mcp.store import SQLiteStore
    store = SQLiteStore(mock_config)
    aid = store.add_alert(265598, "AAPL", 190.0, "above")
    store.mark_alert_triggered(aid)
    assert len(store.get_alerts(active_only=True)) == 0
    assert store.get_alerts(active_only=False)[0]["triggered_at"] is not None


# ── LiveQuote ────────────────────────────────────────────────────────────────

def test_live_quote_fields():
    from ibkr_core_mcp.streaming import LiveQuote
    q = LiveQuote(conid=265598, symbol="AAPL", last=182.5, bid=182.4, ask=182.6)
    assert q.conid == 265598
    assert q.last == 182.5


# ── AlertManager ─────────────────────────────────────────────────────────────

def test_alert_above_triggered(tmp_db, mock_config):
    from ibkr_core_mcp.store import SQLiteStore
    from ibkr_core_mcp.streaming import AlertManager, LiveQuote
    store = SQLiteStore(mock_config)
    store.add_alert(265598, "AAPL", 185.0, "above")
    mgr = AlertManager(store)
    triggered = mgr.check_quote(LiveQuote(conid=265598, symbol="AAPL", last=190.0))
    assert len(triggered) == 1
    assert triggered[0]["threshold"] == 185.0


def test_alert_above_not_triggered(tmp_db, mock_config):
    from ibkr_core_mcp.store import SQLiteStore
    from ibkr_core_mcp.streaming import AlertManager, LiveQuote
    store = SQLiteStore(mock_config)
    store.add_alert(265598, "AAPL", 195.0, "above")
    mgr = AlertManager(store)
    assert mgr.check_quote(LiveQuote(conid=265598, symbol="AAPL", last=190.0)) == []


def test_alert_below_triggered(tmp_db, mock_config):
    from ibkr_core_mcp.store import SQLiteStore
    from ibkr_core_mcp.streaming import AlertManager, LiveQuote
    store = SQLiteStore(mock_config)
    store.add_alert(265598, "AAPL", 175.0, "below")
    mgr = AlertManager(store)
    triggered = mgr.check_quote(LiveQuote(conid=265598, symbol="AAPL", last=170.0))
    assert len(triggered) == 1


def test_alert_not_fired_twice(tmp_db, mock_config):
    from ibkr_core_mcp.store import SQLiteStore
    from ibkr_core_mcp.streaming import AlertManager, LiveQuote
    store = SQLiteStore(mock_config)
    store.add_alert(265598, "AAPL", 185.0, "above")
    mgr = AlertManager(store)
    mgr.check_quote(LiveQuote(conid=265598, symbol="AAPL", last=190.0))
    assert mgr.check_quote(LiveQuote(conid=265598, symbol="AAPL", last=195.0)) == []


def test_check_quote_skips_no_last_price(tmp_db, mock_config):
    from ibkr_core_mcp.store import SQLiteStore
    from ibkr_core_mcp.streaming import AlertManager, LiveQuote
    store = SQLiteStore(mock_config)
    store.add_alert(265598, "AAPL", 185.0, "above")
    mgr = AlertManager(store)
    assert mgr.check_quote(LiveQuote(conid=265598, symbol="AAPL", last=None)) == []


# ── IBKRWebSocket._parse_message (no real WS needed) ────────────────────────

def test_parse_market_data_message():
    from ibkr_core_mcp.streaming import IBKRWebSocket
    ws = object.__new__(IBKRWebSocket)
    raw = json.dumps({
        "topic": "smd+265598",
        "data": [{"31": "182.50", "55": "AAPL", "conid": 265598}],
    })
    quote = ws._parse_message(raw)
    assert quote is not None
    assert quote.conid == 265598
    assert quote.symbol == "AAPL"
    assert quote.last == 182.50


def test_parse_system_message_returns_none():
    from ibkr_core_mcp.streaming import IBKRWebSocket
    ws = object.__new__(IBKRWebSocket)
    assert ws._parse_message(json.dumps({"topic": "system", "success": "true"})) is None


def test_parse_invalid_json_returns_none():
    from ibkr_core_mcp.streaming import IBKRWebSocket
    ws = object.__new__(IBKRWebSocket)
    assert ws._parse_message("not json") is None


def test_parse_bare_dict_data():
    """data field as bare dict (not wrapped in a list) should still parse."""
    from ibkr_core_mcp.streaming import IBKRWebSocket
    ws = object.__new__(IBKRWebSocket)
    raw = json.dumps({
        "topic": "smd+265598",
        "data": {"31": "190.00", "55": "AAPL", "conid": 265598},
    })
    quote = ws._parse_message(raw)
    assert quote is not None
    assert quote.last == 190.0


def test_parse_empty_data_list_returns_none():
    from ibkr_core_mcp.streaming import IBKRWebSocket
    ws = object.__new__(IBKRWebSocket)
    raw = json.dumps({"topic": "smd+265598", "data": []})
    assert ws._parse_message(raw) is None


def test_parse_conid_fallback_from_topic():
    """When conid is absent from data, it should be parsed from the topic string."""
    from ibkr_core_mcp.streaming import IBKRWebSocket
    ws = object.__new__(IBKRWebSocket)
    raw = json.dumps({
        "topic": "smd+12345",
        "data": [{"31": "100.0"}],
    })
    quote = ws._parse_message(raw)
    assert quote is not None
    assert quote.conid == 12345


def test_parse_non_numeric_price_skipped():
    """A non-numeric price field should be silently skipped, not raise."""
    from ibkr_core_mcp.streaming import IBKRWebSocket
    ws = object.__new__(IBKRWebSocket)
    raw = json.dumps({
        "topic": "smd+265598",
        "data": [{"31": "N/A", "55": "AAPL", "conid": 265598}],
    })
    quote = ws._parse_message(raw)
    assert quote is not None
    assert quote.last is None
    assert quote.symbol == "AAPL"


# ── IBKRWebSocket async guards ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_subscribe_before_connect_raises():
    from ibkr_core_mcp.streaming import IBKRWebSocket
    ws = object.__new__(IBKRWebSocket)
    ws._ws = None
    with pytest.raises(RuntimeError, match="connect"):
        await ws.subscribe(265598)


@pytest.mark.asyncio
async def test_listen_before_connect_raises():
    from ibkr_core_mcp.streaming import IBKRWebSocket
    ws = object.__new__(IBKRWebSocket)
    ws._ws = None
    with pytest.raises(RuntimeError, match="connect"):
        async for _ in ws.listen():
            break


@pytest.mark.asyncio
async def test_connect_rejects_non_localhost():
    """IBKRWebSocket must raise StreamingError for non-localhost URLs."""
    from unittest.mock import MagicMock, patch

    from ibkr_core_mcp.exceptions import StreamingError
    from ibkr_core_mcp.streaming import IBKRWebSocket
    ws = IBKRWebSocket("https://external.broker.com:5055/v1/api", "cookie=abc")
    # Patch websockets so the import succeeds; the localhost guard fires before connect()
    with patch.dict("sys.modules", {"websockets": MagicMock()}):
        with pytest.raises(StreamingError, match="localhost"):
            await ws.connect()


@pytest.mark.asyncio
async def test_connect_missing_websockets_raises_import_error():
    """websockets absent → ModuleNotFoundError with install instructions."""
    import sys
    from unittest.mock import patch

    from ibkr_core_mcp.streaming import IBKRWebSocket
    ws = IBKRWebSocket("https://localhost:5055/v1/api", "cookie=abc")
    with patch.dict(sys.modules, {"websockets": None}):
        with pytest.raises(ModuleNotFoundError, match="base dependency of ibkr_core_mcp"):
            await ws.connect()


# ── TradeExecution / PnLUpdate dataclasses ───────────────────────────────────

def test_trade_execution_fields():
    from ibkr_core_mcp.streaming import TradeExecution
    ex = TradeExecution(execution_id="E1", symbol="AAPL", side="BUY", size=10, price=180.0)
    assert ex.execution_id == "E1"
    assert ex.symbol == "AAPL"
    assert ex.side == "BUY"
    assert ex.size == 10
    assert ex.price == 180.0
    assert ex.conid is None  # optional, defaults to None


def test_pnl_update_fields():
    from ibkr_core_mcp.streaming import PnLUpdate
    pnl = PnLUpdate(account="DU1234567.Core", dpl=12.5, nl=10000.0, upl=3.0, uel=9000.0, mv=5000.0)
    assert pnl.account == "DU1234567.Core"
    assert pnl.dpl == 12.5
    assert pnl.nl == 10000.0
    assert pnl.row_type is None  # optional, defaults to None


# ── _parse_message dispatch: str (trade executions) ──────────────────────────

def test_parse_str_single_execution():
    from ibkr_core_mcp.streaming import IBKRWebSocket
    ws = object.__new__(IBKRWebSocket)
    raw = json.dumps({
        "topic": "str",
        "args": [{
            "execution_id": "E1", "symbol": "AAPL", "side": "B",
            "size": "10", "price": "180.5", "trade_time": "20260706-14:30:00",
            "trade_time_r": 1751812200, "conid": "265598", "account": "U1234",
        }],
    })
    result = ws._parse_message(raw)
    assert isinstance(result, list)
    assert len(result) == 1
    ex = result[0]
    assert ex.execution_id == "E1"
    assert ex.symbol == "AAPL"
    assert ex.size == 10.0
    assert ex.price == 180.5
    assert ex.conid == 265598
    assert ex.trade_time_epoch == 1751812200


def test_parse_str_multiple_executions():
    from ibkr_core_mcp.streaming import IBKRWebSocket
    ws = object.__new__(IBKRWebSocket)
    raw = json.dumps({
        "topic": "str",
        "args": [
            {"execution_id": "E1", "symbol": "AAPL"},
            {"execution_id": "E2", "symbol": "MSFT"},
        ],
    })
    result = ws._parse_message(raw)
    assert isinstance(result, list)
    assert len(result) == 2
    assert {ex.execution_id for ex in result} == {"E1", "E2"}


def test_parse_str_malformed_entry_skipped_per_record():
    """A record missing execution_id is dropped; other records in the same message survive."""
    from ibkr_core_mcp.streaming import IBKRWebSocket
    ws = object.__new__(IBKRWebSocket)
    raw = json.dumps({
        "topic": "str",
        "args": [
            {"symbol": "NO_ID"},
            {"execution_id": "E2", "symbol": "MSFT"},
        ],
    })
    result = ws._parse_message(raw)
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0].execution_id == "E2"


def test_parse_str_empty_args_returns_none():
    from ibkr_core_mcp.streaming import IBKRWebSocket
    ws = object.__new__(IBKRWebSocket)
    raw = json.dumps({"topic": "str", "args": []})
    assert ws._parse_message(raw) is None


def test_parse_str_non_numeric_fields_skipped():
    """Non-numeric size/price/conid must be coerced to None, not raise."""
    from ibkr_core_mcp.streaming import IBKRWebSocket
    ws = object.__new__(IBKRWebSocket)
    raw = json.dumps({
        "topic": "str",
        "args": [{"execution_id": "E1", "size": "N/A", "price": "N/A", "conid": "N/A"}],
    })
    result = ws._parse_message(raw)
    assert isinstance(result, list)
    ex = result[0]
    assert ex.size is None
    assert ex.price is None
    assert ex.conid is None


# ── _parse_message dispatch: spl (P&L) ────────────────────────────────────────

def test_parse_spl_valid():
    from ibkr_core_mcp.streaming import IBKRWebSocket
    ws = object.__new__(IBKRWebSocket)
    raw = json.dumps({
        "topic": "spl",
        "args": {"DU1234567.Core": {"rowType": 1, "dpl": 12.5, "nl": 10000.0,
                                     "upl": 3.0, "uel": 9000.0, "mv": 5000.0}},
    })
    pnl = ws._parse_message(raw)
    assert pnl is not None
    assert pnl.account == "DU1234567.Core"
    assert pnl.row_type == 1
    assert pnl.dpl == 12.5
    assert pnl.mv == 5000.0


def test_parse_spl_non_numeric_fields_skipped():
    from ibkr_core_mcp.streaming import IBKRWebSocket
    ws = object.__new__(IBKRWebSocket)
    raw = json.dumps({
        "topic": "spl",
        "args": {"DU1234567.Core": {"dpl": "N/A"}},
    })
    pnl = ws._parse_message(raw)
    assert pnl is not None
    assert pnl.dpl is None


def test_parse_spl_empty_args_returns_none():
    from ibkr_core_mcp.streaming import IBKRWebSocket
    ws = object.__new__(IBKRWebSocket)
    raw = json.dumps({"topic": "spl", "args": {}})
    assert ws._parse_message(raw) is None


# ── _parse_message dispatch: unknown topic regression ────────────────────────

def test_parse_unknown_topic_returns_none():
    """A genuinely novel unknown topic must still return None after the dispatch refactor."""
    from ibkr_core_mcp.streaming import IBKRWebSocket
    ws = object.__new__(IBKRWebSocket)
    assert ws._parse_message(json.dumps({"topic": "blb+265598", "args": {}})) is None


# ── subscribe_executions / unsubscribe_executions / subscribe_pnl / unsubscribe_pnl ──

@pytest.mark.asyncio
async def test_subscribe_executions_sends_wire_string():
    from unittest.mock import AsyncMock

    from ibkr_core_mcp.streaming import IBKRWebSocket
    ws = object.__new__(IBKRWebSocket)
    ws._ws = AsyncMock()
    await ws.subscribe_executions(realtime_updates_only=True, days=3)
    ws._ws.send.assert_awaited_once_with('str+{"realtimeUpdatesOnly": true, "days": 3}')


@pytest.mark.asyncio
async def test_subscribe_executions_before_connect_raises():
    from ibkr_core_mcp.streaming import IBKRWebSocket
    ws = object.__new__(IBKRWebSocket)
    ws._ws = None
    with pytest.raises(RuntimeError, match="connect"):
        await ws.subscribe_executions()


@pytest.mark.asyncio
async def test_unsubscribe_executions_sends_wire_string():
    from unittest.mock import AsyncMock

    from ibkr_core_mcp.streaming import IBKRWebSocket
    ws = object.__new__(IBKRWebSocket)
    ws._ws = AsyncMock()
    await ws.unsubscribe_executions()
    ws._ws.send.assert_awaited_once_with("utr")


@pytest.mark.asyncio
async def test_unsubscribe_executions_before_connect_is_noop():
    from ibkr_core_mcp.streaming import IBKRWebSocket
    ws = object.__new__(IBKRWebSocket)
    ws._ws = None
    await ws.unsubscribe_executions()  # must not raise


@pytest.mark.asyncio
async def test_subscribe_pnl_sends_wire_string():
    from unittest.mock import AsyncMock

    from ibkr_core_mcp.streaming import IBKRWebSocket
    ws = object.__new__(IBKRWebSocket)
    ws._ws = AsyncMock()
    await ws.subscribe_pnl()
    ws._ws.send.assert_awaited_once_with("spl+{}")


@pytest.mark.asyncio
async def test_subscribe_pnl_before_connect_raises():
    from ibkr_core_mcp.streaming import IBKRWebSocket
    ws = object.__new__(IBKRWebSocket)
    ws._ws = None
    with pytest.raises(RuntimeError, match="connect"):
        await ws.subscribe_pnl()


@pytest.mark.asyncio
async def test_unsubscribe_pnl_sends_wire_string():
    from unittest.mock import AsyncMock

    from ibkr_core_mcp.streaming import IBKRWebSocket
    ws = object.__new__(IBKRWebSocket)
    ws._ws = AsyncMock()
    await ws.unsubscribe_pnl()
    ws._ws.send.assert_awaited_once_with("upl")


@pytest.mark.asyncio
async def test_unsubscribe_pnl_before_connect_is_noop():
    from ibkr_core_mcp.streaming import IBKRWebSocket
    ws = object.__new__(IBKRWebSocket)
    ws._ws = None
    await ws.unsubscribe_pnl()  # must not raise


# ── listen() flattening of list[TradeExecution] ──────────────────────────────

@pytest.mark.asyncio
async def test_listen_flattens_execution_list():
    """listen() must yield each TradeExecution individually, not the wrapping list."""
    from ibkr_core_mcp.streaming import IBKRWebSocket, TradeExecution

    async def fake_ws():
        yield json.dumps({
            "topic": "str",
            "args": [
                {"execution_id": "E1"},
                {"execution_id": "E2"},
            ],
        })

    ws = object.__new__(IBKRWebSocket)
    ws._ws = fake_ws()
    items = [item async for item in ws.listen()]
    assert len(items) == 2
    assert all(isinstance(i, TradeExecution) for i in items)
    assert [i.execution_id for i in items] == ["E1", "E2"]


# ── _parse_stream_execution ──────────────────────────────────────────────────

def test_parse_stream_execution_field_mapping():
    from ibkr_core_mcp.streaming import TradeExecution, _parse_stream_execution
    ex = TradeExecution(
        execution_id="E1", symbol="AAPL", side="B", size=10.0, price=180.5,
        trade_time="20260706-14:30:00", account="U1234", sec_type="STK",
    )
    row = _parse_stream_execution(ex)
    assert row == {
        "execution_id": "E1",
        "symbol": "AAPL",
        "side": "BUY",
        "size": 10.0,
        "price": 180.5,
        "time": "20260706-14:30:00",
        "commission": 0.0,
        "account": "U1234",
        "asset_class": "STK",
        "realized_pnl": None,
    }


@pytest.mark.parametrize("raw_side,expected", [("B", "BUY"), ("S", "SELL"), ("BUY", "BUY"), ("SELL", "SELL")])
def test_parse_stream_execution_side_normalization(raw_side, expected):
    from ibkr_core_mcp.streaming import TradeExecution, _parse_stream_execution
    ex = TradeExecution(execution_id="E1", side=raw_side)
    assert _parse_stream_execution(ex)["side"] == expected
