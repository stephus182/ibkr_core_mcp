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

from typing import Any, TypeVar

import pandas as pd
from pydantic import (
    AliasChoices,
    BaseModel,
    Field,
    PrivateAttr,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_core.core_schema import ValidatorFunctionWrapHandler

ModelT = TypeVar("ModelT", bound="IBKRResponse")


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

    **One dict behaviour does not carry over: `model == {...}` is False.** Equality is
    pydantic's, by type and field values. Compare `dict(model)` instead. This shows up
    in tests that assert against a response literal, and essentially nowhere else.
    """

    model_config = {"populate_by_name": True, "extra": "ignore"}

    _raw: dict[str, Any] = PrivateAttr(default_factory=dict)

    @model_validator(mode="wrap")
    @classmethod
    def _keep_raw_payload(cls, data: Any, handler: ValidatorFunctionWrapHandler) -> Any:
        """Snapshot the input, drop IBKR's nulls, then validate as usual.

        A `null` is how this API spells "not applicable", not a malformed value: a search
        for AAPL returns a bond aggregate whose `symbol`, `companyName` and `description`
        are all null, and the portfolio summary documents `amount` as "May return null if
        price value not required". Typed attributes therefore take their default where a
        null arrived, and the null itself stays readable as `model["symbol"]`.
        """
        if not isinstance(data, dict):
            return handler(data)
        snapshot = dict(data)
        model = handler({k: v for k, v in snapshot.items() if v is not None})
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

    def __iter__(self) -> Any:
        """Iterate IBKR's keys.

        This deliberately overrides `BaseModel.__iter__`, which yields `(name, value)`
        pairs. Every other accessor here speaks the mapping protocol, and iteration
        disagreeing with all of them is a trap rather than a nicety — it turned
        `sorted(summary)` into a list of tuples and broke a live test that had read the
        endpoint's keys that way for months. Use `model_dump()` for the field pairs.
        """
        return iter(self._payload())

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


class Account(IBKRResponse):
    """One account, from `/portfolio/accounts` or `/portfolio/{accountId}/meta`.

    **One model for both endpoints on purpose.** Their key sets were measured identical
    (24 keys, 2026-09-17) against `tests/fixtures/ibkr_live_shapes.json`, and
    `test_one_account_model_serves_both_endpoints` fails if they ever diverge — two models
    that are supposed to match are two models that will stop matching.

    `accountId` and `id` both appear and held the same value in the capture. Both stay
    readable; `account_id` reads the documented one. `claude_tools._first_account_id`
    centralises the same fallback for raw dicts.

    IBKR's `type` is exposed as `account_type`, because a field named `type` shadows the
    builtin at every call site that touches it.

    Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/portfolio/portfolio-accounts.md
    """

    account_id: str = Field(default="", alias="accountId", description="Account identifier (IBKR field: accountId)")
    account_van: str = Field(
        default="", alias="accountVan", description="Masked account number (IBKR field: accountVan)"
    )
    account_title: str = Field(default="", alias="accountTitle", description="Account title (IBKR field: accountTitle)")
    display_name: str = Field(
        default="", alias="displayName", description="Name shown in IBKR UIs (IBKR field: displayName)"
    )
    account_type: str = Field(default="", alias="type", description="INDIVIDUAL, JOINT, ... (IBKR field: type)")
    trading_type: str = Field(
        default="", alias="tradingType", description="Trading permissions code (IBKR field: tradingType)"
    )
    currency: str = Field(default="", description="Base currency")
    ib_entity: str = Field(default="", alias="ibEntity", description="IBKR legal entity (IBKR field: ibEntity)")
    brokerage_access: bool = Field(
        default=False, alias="brokerageAccess", description="Whether brokerage features are enabled"
    )


class AuthStatus(IBKRResponse):
    """Session state from `/iserver/auth/status`.

    The four flags are what a caller branches on, and `competing` is the one that matters
    operationally: the gateway allows one brokerage session per username, so another IBKR
    app taking it is reported here rather than as an error. `client.ping()` reads
    `authenticated` off the raw response and is deliberately left untyped — it is a
    liveness probe that answers False rather than raising.

    Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/session/auth-status.md
    """

    authenticated: bool = Field(default=False, description="Brokerage session is authenticated")
    connected: bool = Field(default=False, description="Gateway is connected to IBKR")
    competing: bool = Field(default=False, description="Another session holds this username")
    message: str = Field(default="", description="Human-readable status text")
    server_info: dict[str, Any] = Field(
        default_factory=dict, alias="serverInfo", description="serverName/serverVersion (IBKR field: serverInfo)"
    )


class Alert(IBKRResponse):
    """One price alert, from `/iserver/account/{accountId}/alerts`.

    **`alert_active` and `alert_repeatable` are IBKR enum ints (0/1), not booleans**, while
    `alert_triggered` in the same record really is a bool — measured, not assumed. Declaring
    the first two as `bool` would rewrite 0/1 into False/True and lose which spelling IBKR
    used; the alert-body work had to undo exactly that confusion once already
    (`outsideRth`/`alertRepeatable` are enum ints, never Python bools).

    `order_id` is IBKR's identifier for the alert — alerts are orders on its side — and it
    arrives as an int but goes back out inside a URL path, so it is normalised to text the
    way `Order.order_id` is. The int stays readable as `alert["order_id"]`.

    Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/alerts/get-a-list-of-alerts.md
    """

    order_id: str = Field(default="", description="Alert identifier, as text (IBKR sends an int)")
    account: str = Field(default="", description="Account the alert belongs to")
    alert_name: str = Field(default="", description="Alert name")
    alert_active: int = Field(default=0, description="Enabled flag, 0 or 1 — an enum int, not a bool")
    alert_repeatable: int = Field(default=0, description="Repeat flag, 0 or 1 — an enum int, not a bool")
    alert_triggered: bool = Field(
        default=False, description="Whether the alert has fired (IBKR sends a real bool here)"
    )
    order_time: str = Field(default="", description="Creation time as IBKR formats it")

    @field_validator("order_id", mode="before")
    @classmethod
    def _id_as_text(cls, value: Any) -> Any:
        """IBKR sends an int; it is interpolated into a URL path, so keep it as text."""
        return str(value) if isinstance(value, int) else value


class Watchlist(IBKRResponse):
    """One watchlist, from `/iserver/watchlists`.

    **The id looks numeric and is not** — `"1111.11"` in the capture. Declaring `int` or
    `float` would corrupt the value that goes straight back into
    `/iserver/watchlist?id=`, which is the same class of defect as a digits-only order-id
    pattern admitting Unicode digits (DOCA-01).

    Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/watchlists/get-all-watchlists.md
    """

    id: str = Field(default="", description="Watchlist identifier, text — may contain a dot")
    name: str = Field(default="", description="Watchlist name")
    type: str = Field(default="", description="Watchlist kind, e.g. `watchlist`")
    read_only: bool = Field(default=False, description="Whether the list can be modified")
    is_open: bool = Field(default=False, description="Whether the list is currently open in a UI")
    modified: int = Field(default=0, description="Last-modified epoch as IBKR sends it")


class CurrencyPair(IBKRResponse):
    """One FX pair, from `/iserver/currency/pairs`.

    `ccyPair` is the quote currency alone (`SGD`) and `symbol` is the full pair
    (`USD.SGD`) — not interchangeable, which is why both are named.

    Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/fx/currency-pairs.md
    """

    symbol: str = Field(default="", description="Full pair, e.g. USD.SGD")
    ccy_pair: str = Field(default="", alias="ccyPair", description="Quote currency, e.g. SGD (IBKR field: ccyPair)")
    conid: int = Field(default=0, description="IBKR contract identifier")


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


def parse_one(model: type[ModelT], data: Any) -> ModelT | Any:
    """Validate `data` into `model`, or hand it back untouched if it will not parse.

    IBKR adds and renames response fields without notice, and has shipped rows missing
    ones its own documentation calls required. Raising would turn one odd record into a
    failed call; dropping it would turn a partial oddity into "you have no positions".
    Neither is acceptable for data a human or a model then trades on, so an unparseable
    payload is returned exactly as it arrived — still a mapping, still complete, just
    without the typed attributes.

    That is why the return type is a union. Code that reads `row["mktValue"]` works
    either way; code that reads `row.mkt_value` has to check which it got, and should.
    """
    try:
        return model.model_validate(data)
    except ValidationError:
        return data


def parse_many(model: type[ModelT], rows: Any) -> list[ModelT | Any]:
    """Validate each record with `parse_one`, keeping every row in its original order.

    Returns `[]` for anything that is not a list — the endpoints this serves already
    treated a non-list response as "no records".
    """
    if not isinstance(rows, list):
        return []
    return [parse_one(model, row) for row in rows]


def json_default(obj: Any) -> Any:
    """`json.dumps(..., default=json_default)` — render a model as the payload IBKR sent.

    `json.dumps` does not know an `IBKRResponse`, and several handlers serialise a client
    response straight to the model layer. Without this, threading typed returns into
    `client.py` turned `ibkr://positions/current` into `{"error": "Object of type
    Position is not JSON serializable"}` — a resource that still answered 200 and simply
    stopped carrying positions. Pass this wherever a response may be serialised.
    """
    if isinstance(obj, IBKRResponse):
        return dict(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")
