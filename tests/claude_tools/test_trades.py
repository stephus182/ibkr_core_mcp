import pytest

from ibkr_core_mcp.claude_tools import _parse_live_trades

pytestmark = pytest.mark.trades


def test_execute_get_trades(toolkit):
    toolkit._client.get_trades.return_value = [
        {"execution_id": "E1", "symbol": "AAPL", "side": "BUY", "size": 10, "price": 180, "time": "2026-05-22T10:00:00"}
    ]
    toolkit._store.upsert_trades.return_value = None
    text, fig = toolkit.execute("get_trades", {"source": "live"})
    assert "AAPL" in text
    assert fig is None


# --- _parse_live_trades unit tests ---


def _raw(overrides: dict[str, object]) -> dict[str, object]:
    base = {
        "execution_id": "EX1",
        "symbol": "AAPL",
        "side": "B",
        "size": 10,
        "price": 180.0,
        "time": "2026-05-22T10:00:00",
        "commission": -1.0,
        "account": "U123456",
    }
    base.update(overrides)
    return base


def test_parse_live_trades_side_normalization():
    parsed, skipped = _parse_live_trades([_raw({"side": "B"}), _raw({"side": "S", "execution_id": "EX2"})])
    assert skipped == 0
    assert parsed[0]["side"] == "BUY"
    assert parsed[1]["side"] == "SELL"


def test_parse_live_trades_already_normalized_side():
    parsed, skipped = _parse_live_trades([_raw({"side": "BUY"}), _raw({"side": "SELL", "execution_id": "EX2"})])
    assert skipped == 0
    assert parsed[0]["side"] == "BUY"
    assert parsed[1]["side"] == "SELL"


def test_parse_live_trades_commission_abs():
    parsed, _ = _parse_live_trades([_raw({"commission": -2.5})])
    assert parsed[0]["commission"] == 2.5


def test_parse_live_trades_skips_missing_execution_id():
    # No fallback to loop index — record must be skipped
    t = _raw({})
    del t["execution_id"]
    parsed, skipped = _parse_live_trades([t])
    assert len(parsed) == 0
    assert skipped == 1


def test_parse_live_trades_skips_missing_symbol():
    parsed, skipped = _parse_live_trades([_raw({"symbol": "", "ticker": ""})])
    assert len(parsed) == 0
    assert skipped == 1


def test_parse_live_trades_skips_invalid_side():
    parsed, skipped = _parse_live_trades([_raw({"side": "X"})])
    assert len(parsed) == 0
    assert skipped == 1


def test_parse_live_trades_skips_missing_time():
    t = _raw({"time": "", "trade_time": ""})
    parsed, skipped = _parse_live_trades([t])
    assert len(parsed) == 0
    assert skipped == 1


def test_parse_live_trades_alternate_field_names():
    # IBKR API uses different field names in different endpoints
    t = {
        "execId": "EX99",
        "ticker": "CL",
        "side": "B",
        "filledQuantity": 5,
        "avgPrice": 78.5,
        "trade_time": "2026-05-22T14:30:00",
        "commission": -0.85,
        "acctID": "U999999",
    }
    parsed, skipped = _parse_live_trades([t])
    assert skipped == 0
    assert parsed[0]["execution_id"] == "EX99"
    assert parsed[0]["symbol"] == "CL"
    assert parsed[0]["side"] == "BUY"
    assert parsed[0]["size"] == 5
    assert parsed[0]["price"] == 78.5
    assert parsed[0]["commission"] == 0.85
    assert parsed[0]["account"] == "U999999"


def test_parse_live_trades_upsert_error_surfaced(toolkit):
    toolkit._client.get_trades.return_value = [
        {"execution_id": "E1", "symbol": "AAPL", "side": "B", "size": 10, "price": 180, "time": "2026-05-22T10:00:00"}
    ]
    toolkit._store.upsert_trades.side_effect = RuntimeError("DB locked")
    text, fig = toolkit.execute("get_trades", {"source": "live"})
    # Raw exception must NOT leak to LLM — only a controlled message appears
    assert "DB locked" not in text
    assert "could not be saved" in text.lower()
