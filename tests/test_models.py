
import pandas as pd
import pytest


def test_contract_parses_ibkr_dict():
    from ibkr_core_mcp.models import Contract
    raw = {"conid": 265598, "symbol": "AAPL", "secType": "STK", "exchange": "NASDAQ", "currency": "USD"}
    c = Contract.model_validate(raw)
    assert c.conid == 265598
    assert c.symbol == "AAPL"
    assert c.sec_type == "STK"


def test_contract_missing_conid_raises():
    from ibkr_core_mcp.models import Contract
    with pytest.raises(ValueError):
        Contract.model_validate({"symbol": "AAPL"})


def test_position_parses_ibkr_dict():
    from ibkr_core_mcp.models import Position
    raw = {
        "conid": 265598, "contractDesc": "AAPL", "position": 100.0,
        "mktPrice": 180.0, "mktValue": 18000.0, "unrealizedPnl": 500.0, "realizedPnl": 0.0
    }
    p = Position.model_validate(raw)
    assert p.conid == 265598
    assert p.position == 100.0
    assert p.mkt_price == 180.0


def test_trade_parses_ibkr_dict():
    from ibkr_core_mcp.models import Trade
    raw = {
        "execution_id": "0001", "symbol": "AAPL", "side": "B",
        "size": 10.0, "price": 180.0, "time": "2026-05-22T14:30:00",
        "commission": 1.0, "account": "U123"
    }
    t = Trade.model_validate(raw)
    assert t.symbol == "AAPL"
    assert t.price == 180.0


def test_account_summary_parses_nested():
    from ibkr_core_mcp.models import AccountSummary
    raw = {
        "netliquidation": {"amount": 100000.0, "currency": "USD"},
        "totalcashvalue": {"amount": 50000.0, "currency": "USD"},
        "unrealizedpnl": {"amount": 1500.0, "currency": "USD"},
        "realizedpnl": {"amount": 300.0, "currency": "USD"},
    }
    s = AccountSummary.model_validate(raw)
    assert s.net_liquidation == 100000.0
    assert s.total_cash == 50000.0


def test_bars_to_dataframe_basic():
    from ibkr_core_mcp.models import bars_to_dataframe
    raw = {
        "data": [
            {"t": 1716393600000, "o": 180.0, "h": 182.0, "l": 179.0, "c": 181.0, "v": 1000000},
            {"t": 1716480000000, "o": 181.0, "h": 183.0, "l": 180.0, "c": 182.0, "v": 1100000},
        ]
    }
    df = bars_to_dataframe(raw)
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert len(df) == 2
    assert df.index.name == "date"


def test_bars_to_dataframe_empty():
    from ibkr_core_mcp.models import bars_to_dataframe
    df = bars_to_dataframe({"data": []})
    assert len(df) == 0


def test_notification_model():
    from ibkr_core_mcp.models import Notification
    raw = {"id": "n1", "date": "20260522-14:30:00", "headline": "Price alert", "body": "AAPL above 180", "isRead": False}
    n = Notification.model_validate(raw)
    assert n.headline == "Price alert"
    assert n.is_read is False


# ---------------------------------------------------------------------------
# Alias normalization (IBKR API field name variants)
# ---------------------------------------------------------------------------

def test_contract_normalizes_con_id_alias():
    """IBKR sometimes returns 'con_id' instead of 'conid' — must be normalized."""
    from ibkr_core_mcp.models import Contract
    raw = {"con_id": 265598, "symbol": "AAPL"}
    c = Contract.model_validate(raw)
    assert c.conid == 265598


def test_contract_normalizes_company_name_alias():
    """'companyName' (IBKR search result) must map to 'description'."""
    from ibkr_core_mcp.models import Contract
    raw = {"conid": 265598, "symbol": "AAPL", "companyName": "Apple Inc."}
    c = Contract.model_validate(raw)
    assert c.description == "Apple Inc."


def test_order_normalizes_ibkr_field_aliases():
    """IBKR order responses use camelCase aliases — must all normalize correctly."""
    from ibkr_core_mcp.models import Order
    raw = {
        "orderId": "42",
        "ticker": "AAPL",
        "totalSize": 10.0,
        "orderType": "LMT",
        "side": "BUY",
        "price": 180.0,
        "status": "Submitted",
    }
    o = Order.model_validate(raw)
    assert o.order_id == "42"
    assert o.symbol == "AAPL"
    assert o.qty == 10.0
    assert o.order_type == "LMT"


def test_account_summary_parses_scalar_amounts():
    """AccountSummary must handle raw scalar floats, not only nested {'amount': x} dicts."""
    from ibkr_core_mcp.models import AccountSummary
    raw = {
        "netliquidation": 100000.0,
        "totalcashvalue": 50000.0,
        "unrealizedpnl": 1500.0,
        "realizedpnl": 300.0,
    }
    s = AccountSummary.model_validate(raw)
    assert s.net_liquidation == 100000.0
    assert s.total_cash == 50000.0
    assert s.unrealized_pnl == 1500.0
