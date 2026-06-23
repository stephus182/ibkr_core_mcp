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
    from ibkr_core_mcp.streaming import IBKRWebSocket
    from ibkr_core_mcp.exceptions import StreamingError
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
        with pytest.raises(ModuleNotFoundError, match="ibkr_core_mcp\\[server\\]"):
            await ws.connect()
