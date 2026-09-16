"""Pydantic v2 response models for IBKR Client Portal API endpoints.

**These models are views over IBKR's payload, never a replacement for it.**

Every model here derives from `IBKRResponse`, which keeps the response exactly as it
arrived and exposes it through the mapping protocol. `position.mkt_value` is the typed,
documented, alias-normalised view; `position["mktValue"]` and `dict(position)` are what
IBKR sent, unchanged. Both are always available, and the second never loses a field.

That separation is not decorative. On 2026-09-16 these models were measured against
captured live responses (`tests/fixtures/ibkr_live_shapes.json`) for the first time:

| Model | Endpoint | Result before the fix |
|---|---|---|
| `Order` | `/iserver/account/orders` | **raised** — `orderId` arrives as `int`, the field declared `str` |
| `Contract` | `/trsrv/secdef` | **raised** — those rows carry `ticker`, not `symbol` |
| `Notification` | `/fyi/notifications` | validated with **every field empty** — IBKR sends `D/ID/FC/MD/MS/R` |
| `Trade` | `/iserver/account/trades` | `time` always `""` — the key is `trade_time` |
| `Position` | `/portfolio/{id}/positions` | kept 7 of 51 keys |
| `AccountSummary` | `/portfolio/{id}/summary` | kept 4 of 108 keys, dropping every currency |

All six passed their unit tests throughout, because each test built the model's input by
hand. A fixture whose shape you chose cannot tell you whether the shape is right.

When adding a model: derive from `IBKRResponse`, cite the endpoint's `.md` page, and add
the endpoint to `tests/fixtures/ibkr_live_shapes.json` so the model is checked against a
real response rather than against your reading of the documentation.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from pydantic import AliasChoices, BaseModel, Field, PrivateAttr, field_validator, model_validator
from pydantic_core.core_schema import ValidatorFunctionWrapHandler


class IBKRResponse(BaseModel):
    """Base for IBKR response models: typed attributes that discard nothing.

    Subclasses declare the fields worth naming and typing. This base keeps the
    untouched payload alongside them and serves it through `__getitem__`, `get`,
    `keys`, `items`, `values`, `in` and `len` — so `dict(model)` round-trips the
    response byte for byte, and code written against the raw dicts these endpoints
    used to return keeps working unchanged.

    Reading a raw key gives IBKR's own value and type; reading the attribute gives the
    normalised one. They can legitimately differ — `Order.order_id` is `"1986940574"`
    where `order["orderId"]` is `1986940574` — and where they do, the field's
    description says so.
    """

    model_config = {"populate_by_name": True, "extra": "ignore"}

    _raw: dict[str, Any] = PrivateAttr(default_factory=dict)

    @model_validator(mode="wrap")
    @classmethod
    def _keep_raw_payload(cls, data: Any, handler: ValidatorFunctionWrapHandler) -> Any:
        """Snapshot the input before any normaliser sees it, then validate as usual."""
        snapshot = dict(data) if isinstance(data, dict) else None
        model = handler(data)
        if snapshot is not None:
            model._raw = snapshot
        return model

    @property
    def raw(self) -> dict[str, Any]:
        """A copy of the response exactly as IBKR sent it."""
        return dict(self._payload())

    def _payload(self) -> dict[str, Any]:
        """The raw response, or the field values when the model was built in Python."""
        return self._raw if self._raw else self.model_dump()

    # -- mapping protocol -------------------------------------------------
    # `dict(model)` prefers keys()/__getitem__ over BaseModel.__iter__, so defining
    # these two is what makes a model round-trip to the payload it came from.

    def __getitem__(self, key: str) -> Any:
        """Return IBKR's own value for `key`."""
        return self._payload()[key]

    def get(self, key: str, default: Any = None) -> Any:
        """Return IBKR's own value for `key`, or `default` if it was not sent."""
        return self._payload().get(key, default)

    def __contains__(self, key: object) -> bool:
        """True if IBKR sent `key`."""
        return key in self._payload()

    def __len__(self) -> int:
        """Number of keys IBKR sent."""
        return len(self._payload())

    def keys(self) -> Any:
        """The keys IBKR sent."""
        return self._payload().keys()

    def items(self) -> Any:
        """The key/value pairs IBKR sent."""
        return self._payload().items()

    def values(self) -> Any:
        """The values IBKR sent."""
        return self._payload().values()


class Contract(IBKRResponse):
    """IBKR contract descriptor from /iserver/secdef/search or /trsrv/secdef.

    The two endpoints do not agree on field names, and this model accepts both:
    search results carry `symbol`/`secType`, `/trsrv/secdef` rows carry `ticker` and
    `assetClass`. Neither is required — a row that omits one leaves the attribute empty
    rather than failing, because a missing label is not a malformed contract.

    Two traps, both measured against live responses:

    - On `/iserver/secdef/search`, IBKR's own `description` key holds the **exchange**
      ("NASDAQ"), not a description. `Contract.description` deliberately carries
      `companyName` instead; IBKR's value stays reachable as `contract["description"]`.
    - `conid` arrives as a string from search and as an int from `/trsrv/secdef`. The
      attribute is always `int`; `contract["conid"]` is whatever IBKR sent.
    - `/trsrv/secdef` carries the company name in `name`; its `fullName` holds the
      *ticker* ("AAPL"), which is the reverse of what the names suggest.

    `sec_type` is left empty for search results on purpose: those publish the available
    security types as a `sections` list, and picking one of them here would be a guess.
    Read `contract["sections"]` when you need them.

    Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/contract/search-contract-by-symbol.md
    Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/contract/security-definition.md
    """

    conid: int = Field(validation_alias=AliasChoices("conid", "con_id"))
    symbol: str = Field(
        default="",
        validation_alias=AliasChoices("symbol", "ticker"),
        description="Ticker symbol (IBKR fields: symbol, or ticker on /trsrv/secdef)",
    )
    sec_type: str = Field(
        default="",
        validation_alias=AliasChoices("secType", "assetClass"),
        description="Security type — STK, OPT, FUT, CASH (IBKR fields: secType, or assetClass on /trsrv/secdef)",
    )
    exchange: str = Field(
        default="",
        validation_alias=AliasChoices("exchange", "listingExchange"),
        description="Exchange (IBKR fields: exchange, or listingExchange on /trsrv/secdef)",
    )
    currency: str = Field(default="", description="Trading currency (IBKR field: currency) — empty when not stated")
    description: str = Field(
        default="",
        validation_alias=AliasChoices("companyName", "name"),
        description="Company or instrument name (IBKR fields: companyName, or name on /trsrv/secdef)",
    )


class Position(IBKRResponse):
    """Open position from /portfolio/{accountId}/positions/{page}.

    IBKR sends roughly 50 keys per position — contract metadata, base-currency mirrors,
    increment rules. The six named here are the ones every caller wants; the rest stay
    reachable through the mapping protocol (`position["avgCost"]`, `dict(position)`).

    Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/portfolio/positions.md
    """

    conid: int = 0
    symbol: str = Field(default="", alias="contractDesc", description="Ticker symbol (IBKR field: contractDesc)")
    position: float
    mkt_price: float = Field(default=0.0, alias="mktPrice", description="Current market price (IBKR field: mktPrice)")
    mkt_value: float = Field(
        default=0.0, alias="mktValue", description="Current market value in account currency (IBKR field: mktValue)"
    )
    unrealized_pnl: float = Field(
        default=0.0, alias="unrealizedPnl", description="Unrealized P&L (IBKR field: unrealizedPnl)"
    )
    realized_pnl: float = Field(default=0.0, alias="realizedPnl", description="Realized P&L (IBKR field: realizedPnl)")


class Trade(IBKRResponse):
    """Trade execution record — matches the trades table schema in SQLiteStore.

    Populated from /iserver/account/trades or IBKR Flex XML (all origins: CP API, TWS, mobile).
    The endpoint spells the execution timestamp `trade_time`; `time` is this model's name
    for it, and reads `trade_time` when that is what arrived.

    Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/order-monitoring/trades.md
    """

    execution_id: str = ""
    symbol: str
    side: str = ""
    size: float = 0.0
    price: float = 0.0
    time: str = Field(default="", alias="trade_time", description="Execution timestamp (IBKR field: trade_time)")
    commission: float = 0.0
    account: str = ""


class Order(IBKRResponse):
    """Working order from /iserver/account/orders.

    `order_id` is a string because every method that consumes one — `get_order_status`,
    `cancel_order`, `modify_order` — takes a string. IBKR returns it as an int, so this
    model converts; `order["orderId"]` still gives the int IBKR sent.

    `price` is likewise a string on the wire ("150.00") and a float here.

    Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/order-monitoring/live-orders.md
    """

    order_id: str = Field(default="", alias="orderId", description="IBKR order ID as text (IBKR field: orderId, int)")
    status: str = ""
    symbol: str = Field(default="", alias="ticker", description="Ticker symbol (IBKR field: ticker)")
    side: str = ""
    qty: float = Field(
        default=0.0, alias="totalSize", description="Total order quantity in shares/contracts (IBKR field: totalSize)"
    )
    price: float = 0.0
    order_type: str = Field(
        default="", alias="orderType", description="Order type — LMT, MKT, STP, etc. (IBKR field: orderType)"
    )

    @field_validator("order_id", mode="before")
    @classmethod
    def _order_id_as_text(cls, value: Any) -> Any:
        """IBKR sends orderId as an int; every method that takes one takes a string."""
        return str(value) if isinstance(value, int) else value


class AccountSummary(IBKRResponse):
    """Parsed account summary from /portfolio/{accountId}/summary.

    This model is a **reduction**, not a mirror. IBKR documents an open key/value
    structure — "a total of 45-135 unique values" — where each entry is
    `{"amount": float, "currency": str, "isNull": bool, "timestamp": int, "value": str}`
    and most entries repeat per account segment (`-c` commodities, `-s` securities). A
    2026-09-16 capture returned 108 keys. `_reduce` pulls out four amounts and drops the
    currencies with them, so read `summary["netliquidation"]` when the currency matters;
    the full payload is always there.

    **A field is `None` when the key was absent, and that is not the same as zero.**
    Neither `unrealizedpnl` nor `realizedpnl` appeared in the measured response, and the
    endpoint's documentation names no profit-and-loss entry; they read `0.0` here until
    2026-09-16, which was an assertion the data never supported. Realised and unrealised
    P&L come from /iserver/account/pnl/partitioned — `IBKRClient.get_pnl()`, whose
    `upnl.{account}` object carries `upl` and `dpl`.

    Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/portfolio/portfolio-summary.md
    """

    net_liquidation: float | None = None
    total_cash: float | None = None
    unrealized_pnl: float | None = None
    realized_pnl: float | None = None

    @model_validator(mode="before")
    @classmethod
    def _reduce(cls, data: Any) -> Any:
        if isinstance(data, dict):

            def _amount(key: str) -> float | None:
                if key not in data:
                    return None
                value = data[key]
                if isinstance(value, dict):
                    amount = value.get("amount")
                    return None if amount is None else float(amount)
                return None if value is None else float(value)

            return {
                "net_liquidation": _amount("netliquidation"),
                "total_cash": _amount("totalcashvalue"),
                "unrealized_pnl": _amount("unrealizedpnl"),
                "realized_pnl": _amount("realizedpnl"),
            }
        return data


class Notification(IBKRResponse):
    """FYI notification from /fyi/notifications.

    IBKR names these fields with one- and two-letter codes: `D` date, `ID` identifier,
    `MS` title, `MD` content, `R` read flag (0/1), `FC` FYI code. This model reads those
    codes; it previously declared `id`/`date`/`headline`/`body`/`isRead`, which the
    endpoint has never sent, and so returned an empty object for every notification.

    `date` is a string holding UNIX epoch seconds ("1789580611.0"), and `body` is HTML.
    Neither is converted — the endpoint's values are passed through as sent.

    Source: https://www.interactivebrokers.com/docs/web-api/v1/endpoints/fy-is-and-notifications/get-a-list-of-notifications.md
    """

    id: str = Field(default="", alias="ID", description="Notification identifier (IBKR field: ID)")
    date: str = Field(default="", alias="D", description="Epoch-seconds timestamp as text (IBKR field: D)")
    headline: str = Field(default="", alias="MS", description="Notification title (IBKR field: MS)")
    body: str = Field(default="", alias="MD", description="Notification content, HTML (IBKR field: MD)")
    is_read: bool = Field(default=False, alias="R", description="Read flag, 0 or 1 (IBKR field: R)")
    fyi_code: str = Field(default="", alias="FC", description="FYI category code (IBKR field: FC)")


def bars_to_dataframe(raw: dict[str, Any]) -> pd.DataFrame:
    """Convert IBKR market history API response to a standard OHLCV DataFrame.

    Input format (from /iserver/marketdata/history):
      {"startTime": "...", "data": [{"o": float, "h": float, "l": float,
                                      "c": float, "v": float, "t": int}, ...]}
    where "t" is a UNIX timestamp in milliseconds (UTC).

    Returns a DataFrame indexed by a UTC DatetimeIndex named "date", with columns:
      open, high, low, close, volume (sorted ascending by date).
    Returns an empty DataFrame with those columns if "data" is missing or empty.

    Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/market-data/historical-market-data.md
    """
    bars = raw.get("data", [])
    if not bars:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = pd.DataFrame(bars)
    df["t"] = pd.to_datetime(df["t"], unit="ms")
    df = df.rename(columns={"t": "date", "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
    df = df.set_index("date")[["open", "high", "low", "close", "volume"]].sort_index()
    return df
