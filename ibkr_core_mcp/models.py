from __future__ import annotations
from typing import Any
import pandas as pd
from pydantic import BaseModel, model_validator, Field


class Contract(BaseModel):
    conid: int
    symbol: str
    sec_type: str = Field(default="", alias="secType")
    exchange: str = ""
    currency: str = "USD"
    description: str = Field(default="", alias="companyName")

    model_config = {"populate_by_name": True}

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "secType" in data and "sec_type" not in data:
                data.setdefault("sec_type", data["secType"])
            if "con_id" in data and "conid" not in data:
                data["conid"] = data["con_id"]
            if "companyName" in data and "description" not in data:
                data.setdefault("description", data["companyName"])
        return data


class Position(BaseModel):
    conid: int = 0
    symbol: str = Field(default="", alias="contractDesc")
    position: float
    mkt_price: float = Field(default=0.0, alias="mktPrice")
    mkt_value: float = Field(default=0.0, alias="mktValue")
    unrealized_pnl: float = Field(default=0.0, alias="unrealizedPnl")
    realized_pnl: float = Field(default=0.0, alias="realizedPnl")

    model_config = {"populate_by_name": True}

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if isinstance(data, dict):
            for alias, name in [
                ("mktPrice", "mkt_price"),
                ("mktValue", "mkt_value"),
                ("unrealizedPnl", "unrealized_pnl"),
                ("realizedPnl", "realized_pnl"),
                ("contractDesc", "symbol"),
            ]:
                if alias in data and name not in data:
                    data.setdefault(name, data[alias])
        return data


class Trade(BaseModel):
    execution_id: str = ""
    symbol: str
    side: str = ""
    size: float = 0.0
    price: float = 0.0
    time: str = ""
    commission: float = 0.0
    account: str = ""


class Order(BaseModel):
    order_id: str = Field(default="", alias="orderId")
    status: str = ""
    symbol: str = Field(default="", alias="ticker")
    side: str = ""
    qty: float = Field(default=0.0, alias="totalSize")
    price: float = 0.0
    order_type: str = Field(default="", alias="orderType")

    model_config = {"populate_by_name": True}

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if isinstance(data, dict):
            for alias, name in [
                ("orderId", "order_id"),
                ("ticker", "symbol"),
                ("totalSize", "qty"),
                ("orderType", "order_type"),
            ]:
                if alias in data and name not in data:
                    data.setdefault(name, data[alias])
        return data


class AccountSummary(BaseModel):
    net_liquidation: float = 0.0
    total_cash: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if isinstance(data, dict):
            def _amount(key: str) -> float:
                v = data.get(key, {})
                if isinstance(v, dict):
                    return float(v.get("amount", 0))
                return float(v or 0)
            return {
                "net_liquidation": _amount("netliquidation"),
                "total_cash": _amount("totalcashvalue"),
                "unrealized_pnl": _amount("unrealizedpnl"),
                "realized_pnl": _amount("realizedpnl"),
            }
        return data


class Notification(BaseModel):
    id: str = ""
    date: str = ""
    headline: str = ""
    body: str = ""
    is_read: bool = Field(default=False, alias="isRead")

    model_config = {"populate_by_name": True}

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "isRead" in data and "is_read" not in data:
                data.setdefault("is_read", data["isRead"])
        return data


def bars_to_dataframe(raw: dict) -> pd.DataFrame:
    """Convert IBKR market history API response to standard OHLCV DataFrame."""
    bars = raw.get("data", [])
    if not bars:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = pd.DataFrame(bars)
    df["t"] = pd.to_datetime(df["t"], unit="ms")
    df = df.rename(columns={"t": "date", "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
    df = df.set_index("date")[["open", "high", "low", "close", "volume"]].sort_index()
    return df
