"""IBKRClient — the IBKR Client Portal Web API surface (78 public methods).

Wraps market data, contracts, portfolio, orders, alerts, watchlists, and session
management. Rate limiting and 429/503 backoff are handled transparently by
`rate_limiter.py`.

**Return types.** 29 endpoints return models from `models.py` — `search_contract` and
`get_secdef` (`Contract`), `get_positions` and `get_all_positions` (`Position`),
`get_trades` (`Trade`), `get_live_orders` (`Order`), `get_account_summary`
(`AccountSummary`), `get_notifications` (`Notification`), `get_accounts`,
`get_account_meta` and `get_subaccounts` (`Account`), `get_auth_status` (`AuthStatus`), `get_alerts` (`Alert`),
`get_mta_alert` (`MTAAlert`), `get_watchlists` (`Watchlist`), `get_watchlist`
(`WatchlistDetail`), `get_currency_pairs` (`CurrencyPair`), `get_secdef_info`
(`SecDefInfo`), `get_contract_info` and `get_contract_info_and_rules` (`ContractDetails`),
`get_contract_rules` (`ContractRules`), `get_futures` (`FutureContract`), `get_stocks`
(`StockSearchResult`), `get_contract_algos` (`Algo`), `get_trading_schedule`
(`TradingSchedule`), `get_market_history` and `get_market_history_paginated`
(`MarketHistory`), `get_option_chain` (`OptionChain`) and `get_brokerage_accounts`
(`BrokerageSession`). The rest are not untyped by accident: every endpoint in
`tests/fixtures/ibkr_live_shapes.json` either returns a model or carries a recorded reason
why it does not, and `test_every_captured_endpoint_is_typed_or_reasoned` fails when a new
capture belongs to neither set. This said "Six"
while naming seven, against a real eight, until 2026-09-17: the paging helper added for
API-17 never reached the list (API-12). Its name is deliberately not repeated in this
sentence — a mutation that removed it from the list above survived while the prose still
carried it. The point of naming them is that the claim can be checked rather than believed,
which only works if something checks it —
`test_the_module_docstring_names_every_method_that_returns_a_model` now does, over a model
set **derived from `models.py`**: its first version froze the six models that existed when
it was written, so the six methods added on 2026-09-17 were invisible to it and this
paragraph would have gone stale with the suite green. The rest return the decoded response as-is, and
their annotations say so. This file claimed to return "typed models from `models.py`
where the shape is stable" from the day it was written until 2026-09-16, when not one
method did (audit finding API-11); the claim is now a list, so it can be checked.

Those models never replace the payload. Each one is also a mapping over exactly what
IBKR sent — `position["mktValue"]`, `dict(position)`, `len(position)` — so a typed
return cannot narrow a 51-key position to seven fields. A record that will not validate
is passed through as the plain dict it arrived as rather than dropped, which is why the
annotations are `list[Position | dict[str, Any]]` and not `list[Position]`. See
`models.py` for the reasoning and `tests/fixtures/ibkr_live_shapes.json` for the
captured responses both are checked against.

**Security invariant.** Every order write method — `place_order`, `modify_order`,
`cancel_order`, `reply_order`, and the `*_and_confirm` variants — runs two
sequential human gates (Touch ID, then a visual confirmation dialog) *before* any
**order-write request** reaches IBKR. One read precedes them, deliberately:
`_ensure_accounts_initialized()` issues IBKR's documented order prerequisite
`GET /iserver/accounts` once per session, so a dead session fails before the human is
asked rather than after. Nothing else does, and no write does — checked transitively by
`tests/security/test_order_write_boundary.py` (SEC-02, 2026-09-16). The gates are
enforced here, at the innermost call site,
precisely so that no caller can route around them; they must never be moved
outward, cached, or made bypassable. Read-only methods (`get_order_preview`, the
order-status readers, alert management) are deliberately ungated. See the Security
section of `CLAUDE.md` before touching any of this.

Endpoint reference: https://www.interactivebrokers.com/docs/web-api/
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

import requests
import urllib3

from ibkr_core_mcp.auth import AuthStrategy, BrowserCookieAuth
from ibkr_core_mcp.config import Config
from ibkr_core_mcp.exceptions import ConfigError, HumanAuthError, IBKRAPIError
from ibkr_core_mcp.human_auth import (
    ORDER_WRITE_AUTHORIZATION_TTL_S,
    OrderWriteAuthorization,
    require_touch_id,
)
from ibkr_core_mcp.models import (
    Account,
    AccountSummary,
    Alert,
    Algo,
    AuthStatus,
    BrokerageSession,
    Contract,
    ContractDetails,
    ContractRules,
    CurrencyPair,
    FutureContract,
    MarketHistory,
    MTAAlert,
    Notification,
    OptionChain,
    Order,
    Position,
    SecDefInfo,
    StockSearchResult,
    Trade,
    TradingSchedule,
    Watchlist,
    WatchlistDetail,
    parse_many,
    parse_one,
)
from ibkr_core_mcp.order_confirm import (
    confirm_cancel_dialog,
    confirm_modify_dialog,
    confirm_order_dialog,
    confirm_reply_dialog,
    reply_message_text,
)
from ibkr_core_mcp.rate_limiter import with_retry

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Account IDs are uppercase alphanumeric, 4–12 chars (e.g. "U1234567", "DU12345").
# This prevents path traversal in URLs and matches the claude_tools validator.
_ACCOUNT_ID_RE = re.compile(r"^[A-Z0-9]{4,12}$")

# Every numeric path segment: order and alert IDs (CP API reference: order/status example
# ".../order/status/1234567890"; alertId documented as "int. Required"), conids, positions
# page indices and FYI notification IDs — all non-negative integers in IBKR's
# documentation. `[0-9]` rather than `\d`, which matches Unicode digits that int() accepts
# and a URL path does not (SECURITY.md § confused deputy). One rule, one regex: until
# 2026-09-17 a byte-identical `_ORDER_ID_RE` sat six lines above this one behind its own
# validator and message (SEC-R7); `_require_numeric` is now the single validator.
_NUMERIC_PATH_SEGMENT_RE = re.compile(r"^[0-9]+$")

# The two delivery channels IBKR documents, and the only two values that form a real path.
_DELIVERY_OPTIONS = frozenset({"device", "email"})

# IBKR reply IDs are documented as "String. Required" with example value
# "a12b34c5-d678-9e012f-3456-7a890b12cd3e" — hex + hyphens, non-standard
# UUID grouping (not 8-4-4-4-12), so match on charset/length, not exact
# segment structure. Source: docs/audits/audit-evidence/scrapes/cpapi-v1.md
# (https://ibkrcampus.com/docs/web-api/v1/endpoints/orders/place-order-reply-confirmation.md)
#
# **Measured 2026-09-16 against 24 reply IDs IBKR actually sent**, recovered from the
# persisted `ibkr_replies` reply logs of real orders placed 2026-09-10/11 (claudia_ui's
# decision store, which is not part of this repository). All 24 matched. Every one was a
# standard lowercase UUID — 36 characters, 8-4-4-4-12 — which the *documented example is
# not*: its third group is six characters. Matching on charset rather than on UUID
# structure is what lets this accept both, and tightening it to a UUID pattern would
# reject the only example IBKR publishes. The IDs themselves are deliberately not
# reproduced here: this repository is public and they are the account holder's.
_REPLY_ID_RE = re.compile(r"^[0-9a-fA-F-]{1,64}$")

# ---------------------------------------------------------------------------
# Market history pagination helpers
# /iserver/marketdata/history is capped at 1000 data points per request.
# Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/market-data/historical-market-data.md
# ---------------------------------------------------------------------------

_PERIOD_RE = re.compile(r"^(\d+)(min|h|d|w|m|y)$", re.IGNORECASE)
_UNIT_TO_DAYS: dict[str, float] = {
    "min": 1 / 1440,
    "h": 1 / 24,
    "d": 1,
    "w": 7,
    "m": 30,
    "y": 365,
}
# Bars per calendar day, used only for pagination chunk sizing — not exposed to callers.
#
# These are deliberately the WORST CASE: a continuously-traded instrument (a ~24h futures
# session) with `outsideRth=true`. Sizing for US equity regular hours under-counts a futures
# day by ~3.7x, and an under-count is what silently loses data.
#
# The previous table claimed "US equity trading hours" and was wrong for every intraday
# size. Measured live 2026-09-15 (GLD, outsideRth=true), requesting exactly one chunk width
# and comparing what arrived:
#
#     bar     old value   chunk asked   actually spanned   implied true bpd
#     1min    135.0       7d            1.03d              ~971
#     5min    27.0        29d           7.14d              ~140
#     30min   4.5         177d          43.15d             ~23
#     1h      3.25        246d          89.25d             ~11
#     4h      0.8         1000d         331d               ~3
#     1d      0.69        1000d         1456d              0.687   <- correct
#     1w      0.143       1000d         1454d              0.144   <- correct
#
# Only the daily and weekly entries were right. Note also that bars-per-*calendar*-day is
# not a constant: it falls as a window covers more weekends. That is why correctness cannot
# rest on this table at all — `get_market_history_paginated` advances its cursor by the data
# it actually received, and these values only decide how many requests that takes.
_BARS_PER_CALENDAR_DAY: dict[str, float] = {
    "1min": 1440.0,
    "2min": 720.0,
    "3min": 480.0,
    "5min": 288.0,
    "10min": 144.0,
    "15min": 96.0,
    "30min": 48.0,
    "1h": 24.0,
    "2h": 12.0,
    "3h": 8.0,
    "4h": 6.0,
    "8h": 3.0,
    "1d": 0.69,
    "1w": 0.143,
    "1m": 0.033,
}

# The largest `period` for which IBKR permits each `bar`, in calendar days.
#
# From the official Step Size table ("the permitted minimum and maximum bar size for any
# given period"), scraped 2026-09-15 from
# https://ibkrcampus.com/docs/web-api/v1/endpoints/market-data/historical-market-data.md
#
#     period      1min  1h        1d        1w          1m       3m       6m       1y      2y/3y    15y
#     bar         1min  1min-8h   1min-8h   10min-1w    1h-1m    2h-1m    4h-1m    8h-1m   1d-1m    1w-1m
#
# A request outside the table is NOT rejected. Measured 2026-09-15, `7d/1min` returned real
# 1-minute bars, merely capped at 1000 — but the documented contract does not promise that,
# and the same class of out-of-range input (uppercase units) is already known to make this
# endpoint silently substitute a different bar size. Staying inside the table is what keeps
# the returned bar size the one that was asked for.
_MAX_PERIOD_DAYS_FOR_BAR: dict[str, float] = {
    "1min": 1,
    "2min": 1,
    "3min": 1,
    "5min": 1,
    "10min": 7,
    "15min": 7,
    "30min": 7,
    "1h": 30,
    "2h": 90,
    "3h": 90,
    "4h": 180,
    "8h": 365,
    "1d": 1095,
    "1w": 5475,
    "1m": 5475,
}
_MAX_POINTS = 1000
_CHUNK_SAFETY = 0.80  # target 80% of limit per chunk
_MAX_CHUNKS = 120  # runaway guard; a stalled cursor must not loop forever


def _parse_period_days(period: str) -> float | None:
    """Return approximate calendar days for a period string, or None if unparseable."""
    m = _PERIOD_RE.match(period)
    if not m:
        return None
    return float(m.group(1)) * _UNIT_TO_DAYS[m.group(2).lower()]


def _chunk_days_for_bar(bar: str) -> int:
    """Calendar days per request chunk: under the point cap AND inside IBKR's step table.

    Two independent ceilings, both of which the previous version ignored:

    1. **The 1000-point cap.** Exceeding it does not error — the endpoint returns the newest
       1000 bars and drops the rest silently.
    2. **The permitted period for this bar size** (`_MAX_PERIOD_DAYS_FOR_BAR`). A 1-minute
       bar is only offered for periods up to 1d, however few points that is.

    The old floor of `max(7, ...)` made the result at least a week for every bar size, which
    for `1min` is ~10,000 points against a 1000-point cap — so every intraday chunk asked for
    roughly an order of magnitude more than could come back. Now floored at one day, which is
    the smallest period this function can express.
    """
    b = bar.lower()
    bpd = _BARS_PER_CALENDAR_DAY.get(b, 0.69)
    by_points = int(_MAX_POINTS * _CHUNK_SAFETY / bpd)
    by_step = int(_MAX_PERIOD_DAYS_FOR_BAR.get(b, 1000))
    return max(1, min(1000, by_points, by_step))


def _fits_in_one_call(total_days: float, bar: str) -> bool:
    """Whether a whole request can be served by a single un-paginated call.

    The pagination loop's cursor advances to the oldest bar that actually ARRIVED, so once
    inside it correctness no longer depends on any size estimate. The fast path skips that
    loop, and therefore does depend on one — which is only safe when the estimate says the
    request fits inside the endpoint's 1000-point cap with the same safety margin every
    chunk width uses.

    Guarding the fast path on `total_days <= chunk_days` alone was not enough: chunk widths
    are floored at one day, and one day of 1-minute bars is 1440 points. `1min` is the only
    bar size whose floor exceeds the cap, and `period="1d", bar="1min"` therefore returned
    the newest 1000 bars — 69.4% of the day — with no error (found 2026-09-16; the loop
    itself was fixed in 2a228d7, whose live checks used 5d/1min and 30d/5min, both of which
    take the loop).

    Under-estimating is the safe direction here: it costs an extra request, never data.

    Source for the cap: https://ibkrcampus.com/docs/web-api/v1/endpoints/market-data/historical-market-data.md
    """
    return total_days * _BARS_PER_CALENDAR_DAY.get(bar.lower(), 0.69) <= _MAX_POINTS * _CHUNK_SAFETY


log = logging.getLogger(__name__)


def _order_write_scope(kind: str, account_id: str, body: Mapping[str, Any], order_id: str | None = None) -> str:
    """The transaction's own data as a scope string — what one Gate 1 is bound to.

    The canonical body is exactly what reaches IBKR: display-only `_`-prefixed keys are
    dropped (they never leave the machine), keys are sorted, values serialised with
    `default=str`. Hashed so the scope is opaque and fixed-length; a body altered after the
    fingerprint — a price, the quantity, the conid — hashes differently and the
    authorization no longer covers it (EU RTS 2018/389 Art. 5(1)(d), in code). The scope is
    of the body *as sent*, not of its economics: `7900` and `7900.0` are different bodies,
    which is right, because a chain always carries one body object end to end.

    The account is part of the scope. It was not until 2026-09-17: the scope held the body
    and the order id only, so an authorization earned for one account covered a
    byte-identical body sent to another, and a human who approved a write against account A
    could have had it carried to account B without a second prompt (audit finding SEC-07).
    `account_id` is required rather than optional so a call site that forgets it fails
    loudly instead of quietly minting the weaker scope.

    Args:
        kind: "place", "modify" or "cancel".
        account_id: The account the write is aimed at — part of the transaction.
        body: The order body about to be sent.
        order_id: The live order's id for modify/cancel, part of the scope.

    Returns:
        `"<kind>:<account>:<digest>"`, or `"<kind>:<account>:<order_id>:<digest>"` when an
        order id is given.
    """
    canonical = {k: v for k, v in body.items() if not str(k).startswith("_")}
    digest = hashlib.sha256(json.dumps(canonical, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]
    head = f"{kind}:{account_id}"
    return f"{head}:{order_id}:{digest}" if order_id is not None else f"{head}:{digest}"


def _order_label(order: Mapping[str, Any]) -> str:
    """`BUY 1 ES` — the one line every Gate 1 prompt and every dialog names an order by.

    Read once here so the prompt, the authorization and the reply dialogs cannot disagree
    about which order they are for. `ticker` is IBKR's field; `symbol` is what a caller
    may still say; either is accepted, as `place_order` always has.
    """
    symbol = order.get("ticker", order.get("symbol", "UNKNOWN"))
    return f"{order.get('side', '?')} {order.get('quantity', '?')} {symbol}"


def _authorize_order_write(
    reason: str, scope: str, label: str, ttl_s: float = ORDER_WRITE_AUTHORIZATION_TTL_S
) -> OrderWriteAuthorization:
    """Gate 1 for one order write: Touch ID, then the authorization it grants.

    Lives here, beside the standalone prompts, so that every Gate 1 in the package goes
    through the one `require_touch_id` reference this module holds — one seam to reason
    about, one seam a test doubles. (A first cut put it in `human_auth`, where it called
    that module's own reference and slipped past every existing double; 2026-09-11.)

    Args:
        reason: The Touch ID prompt text, completing "Python is trying to …".
        scope: The transaction's own data, from `_order_write_scope`.
        label: The order's one-line description, for the reply dialogs' title.
        ttl_s: Validity window; `ORDER_WRITE_AUTHORIZATION_TTL_S` unless a test shortens it.

    Returns:
        The authorization. Raises `HumanAuthError` (from `require_touch_id`) on any denial.
    """
    require_touch_id(reason)
    return OrderWriteAuthorization(scope, label, time.monotonic(), ttl_s)


def _validate_account_id(account_id: str) -> None:
    """Raise ConfigError if account_id is not a valid IBKR account ID."""
    if not account_id or not _ACCOUNT_ID_RE.fullmatch(account_id):
        raise ConfigError(f"Invalid account_id {account_id!r}: must be 4–12 uppercase alphanumeric chars.")


def _validate_order_id(order_id: str) -> None:
    """Raise ConfigError if order_id/alert_id is not a valid IBKR numeric ID.

    Prevents path traversal in URLs built by f-string interpolation — the same
    threat _validate_account_id addresses for account_id. Applies to order_id
    and alert_id (IBKR reuses the same numeric ID namespace for both — see
    docs/audits/security-audit-2026-07-11.md H-2). The rule is `_require_numeric`'s,
    shared with conids, page indices and notification IDs (SEC-R7).
    """
    _require_numeric(order_id, "order_id/alert_id")


def _validate_reply_id(reply_id: str) -> None:
    """Raise ConfigError if reply_id is not a plausible IBKR reply ID."""
    if not reply_id or not _REPLY_ID_RE.fullmatch(reply_id):
        raise ConfigError(f"Invalid reply_id {reply_id!r}: must be a hex/hyphen string.")


def _require_numeric(value: object, label: str) -> None:
    """Raise ConfigError unless `value` is a non-negative integer, or text spelling one.

    Type annotations do not survive into the interpolation. `get_contract_info(conid: int)`
    renders whatever it is handed, and `/iserver/secdef/search` returns `conid` as a
    **string** ("265598"), so a string here is an ordinary value rather than a hypothetical
    misuse. Invariant 9 asks that every path-interpolated identifier pass a regex; these
    are identifiers, so they do.
    """
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ConfigError(f"Invalid {label} {value!r}: must be a non-negative integer.")
    text = str(value)
    if not _NUMERIC_PATH_SEGMENT_RE.fullmatch(text):
        raise ConfigError(f"Invalid {label} {value!r}: must be a non-negative integer.")


def _validate_conid(conid: int | str) -> None:
    """Raise ConfigError if conid is not a non-negative integer."""
    _require_numeric(conid, "conid")


def _validate_page(page: int | str) -> None:
    """Raise ConfigError if a positions page index is not a non-negative integer."""
    _require_numeric(page, "page")


def _validate_notification_id(notification_id: str) -> None:
    """Raise ConfigError if notification_id is not a non-negative integer.

    IBKR's own 400 for this endpoint reads "Missing, empty, **non-numeric**, or
    out-of-range parameter", so numeric is the documented shape, not an inference.
    Source: https://www.interactivebrokers.com/docs/web-api/api-reference/trading/trading-fy-is-and-notifications/read-fyi-notification.md
    """
    _require_numeric(notification_id, "notification_id")


def _validate_delivery_option(option: str) -> None:
    """Raise ConfigError unless `option` is one of the two documented delivery channels.

    IBKR publishes exactly two, and they are different endpoints rather than one
    parameterised path — see `update_delivery_option` for what differs between them.
    """
    if option not in _DELIVERY_OPTIONS:
        raise ConfigError(f"Invalid delivery option {option!r}: must be one of {sorted(_DELIVERY_OPTIONS)}.")


def _as_reply_list(data: Any) -> list[dict[str, Any]]:
    """Normalize a /iserver/reply/{replyId} JSON body to list[dict] (place_order's shape)."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]
    return []


def _as_reply_dict(data: Any) -> dict[str, Any]:
    """Normalize a /iserver/reply/{replyId} JSON body to dict (modify_order's shape)."""
    if isinstance(data, dict):
        return data
    if isinstance(data, list) and data:
        return data[0]
    return {}


def _flatten_buckets(data: Any, path: str) -> list[Any]:
    """The rows of a response that is either a bare array or an object of arrays.

    `/trsrv/futures` and `/trsrv/stocks` answer `{"ES": [...], "CL": [...]}` keyed by
    symbol, `/iserver/currency/pairs` keyed by currency and `/portfolio/positions/{conid}`
    keyed by account id; each is flattened to one list, and a bare array is itself. Four
    methods spelled this four ways until 2026-09-17, and three of them iterated the VALUES
    of whatever object arrived — so a 2xx `{"error": "…"}`, the shape IBKR uses for a
    rejection, became the characters of its message and `parse_many` was handed
    one-character rows with IBKR's words discarded (API-R10). An object with no array in it
    is not a set of buckets: one carrying `error` is raised as `IBKRAPIError` with IBKR's
    message, and any other is no rows.
    """
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    buckets = [bucket for bucket in data.values() if isinstance(bucket, list)]
    if not buckets and "error" in data:
        raise IBKRAPIError(f"{path} returned an error: {data['error']}")
    return [row for bucket in buckets for row in bucket]


def _decode(resp: requests.Response, path: str) -> Any:
    """IBKR's JSON body — or `IBKRAPIError`, never a `requests` exception.

    `with_retry` has already raised on every non-2xx status, so everything arriving here
    answered 200..299. That is not a promise of JSON: the Client Portal Gateway serves an
    HTML page once its session lapses, and an empty 200 is what a proxy in front of it
    returns. `resp.json()` then raises `requests.exceptions.JSONDecodeError`, which is
    **outside this package's hierarchy** — so a caller doing exactly what `exceptions.py`
    tells it to do, `except IBKRCoreError`, did not catch it, and the message it got
    ("Expecting value: line 1 column 1") named neither the endpoint nor what arrived.
    Measured 2026-09-17; audit finding API-15.

    One function rather than a `try` repeated at six call sites, for the reason API-10
    recorded: when a rule has to be spelled out in N places, it ends up holding in N-1.
    `ping` is the single exemption — a liveness probe that answers False rather than
    raising — and `test_every_client_request_helper_decodes_through_the_same_guard` fails
    if a seventh decode appears beside this one instead of through it.

    Args:
        resp: A response `with_retry` has already accepted as 2xx.
        path: The request path, for the error message.

    Returns:
        The decoded body, exactly as IBKR sent it.

    Raises:
        IBKRAPIError: The body did not decode. Carries the status and, as `with_retry`
            does for an error status, at most 400 characters of what arrived.
    """
    try:
        return resp.json()
    except (ValueError, requests.exceptions.InvalidJSONError) as exc:
        try:
            preview = resp.text[:400]
        except Exception:  # a body that cannot even be read is still an API error, not a crash
            preview = ""
        raise IBKRAPIError(
            f"IBKR gateway returned HTTP {resp.status_code} for {path} with a body that is not JSON: {preview}",
            status_code=resp.status_code,
        ) from exc


class IBKRClient:
    """Wraps all IBKR Client Portal API endpoints. Returns raw dicts.

    All endpoints connect only to localhost. Any non-localhost gateway URL raises
    ConfigError at construction time.

    Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/introduction.md
    All docs pages are fully public (no login required). Endpoint behavior
    is verified against official documentation per the "Docs First" rule.
    """

    def __init__(
        self,
        config: Config,
        auth: AuthStrategy | None = None,
    ) -> None:
        """Build a client bound to a local gateway.

        Args:
            config: Supplies `gateway_url`.
            auth: Authentication strategy; defaults to `BrowserCookieAuth()`.

        Raises:
            ConfigError: If `gateway_url` is not a loopback host. TLS verification
                is disabled for this session because the gateway ships a
                self-signed certificate, so the host is pinned to localhost to keep
                that exemption from ever applying to a remote server.
        """
        self._base = config.gateway_url.rstrip("/")
        _host = urlparse(config.gateway_url).hostname
        if _host not in ("localhost", "127.0.0.1", "::1"):
            raise ConfigError(
                f"IBKRClient: verify=False is only permitted for localhost; "
                f"got {_host!r}. Set IBKR_GATEWAY_URL to a localhost address."
            )
        self._session = requests.Session()
        self._session.verify = False
        auth = auth or BrowserCookieAuth()
        auth.apply(self._session)
        self._accounts_initialized = False

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self._base}{path}"
        resp = with_retry(lambda: self._session.get(url, params=params, timeout=30), path=path)
        return _decode(resp, path)

    def _post(self, path: str, body: dict[str, Any] | None = None) -> Any:
        url = f"{self._base}{path}"
        resp = with_retry(lambda: self._session.post(url, json=body or {}, timeout=30), path=path)
        return _decode(resp, path)

    def _put(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """PUT with an empty JSON body — the shape both FYI write endpoints document.

        Added 2026-09-16 with the API-20/21 fixes. `tests/security/test_order_write_boundary.py`
        names it alongside `_post` and `_session`, so a new order-write call site cannot
        reach the network through it either.
        """
        url = f"{self._base}{path}"
        resp = with_retry(lambda: self._session.put(url, params=params, json={}, timeout=30), path=path)
        return _decode(resp, path)

    # ------------------------------------------------------------------
    # Session
    # ------------------------------------------------------------------

    def ping(self) -> bool:
        """Quick connectivity check. Returns True if gateway is reachable and authenticated.

        Uses a 5-second timeout and never raises — returns False on any error.
        Retries once after tickle() to work around an IBKR gateway quirk where
        the first /iserver/auth/status call of a new session returns authenticated=false
        even when fully logged in.

        Note: official docs list this endpoint as POST /iserver/auth/status, but this
        method calls it via GET, which has worked reliably in production (this method
        is the live 60s ConnectivityChecker poll path). Not changed without a live-gateway
        test confirming POST behaves identically — see get_auth_status() for the same
        discrepancy on a code path with no production callers.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/session/authentication-status.md
        """
        # /iserver/auth/status returns authenticated=false on the very first request of a new
        # gateway session (IBKR quirk) even when the user is fully logged in.
        # Retry once after a tickle() to let the gateway warm up.
        for attempt in range(2):
            try:
                resp = self._session.get(f"{self._base}/iserver/auth/status", timeout=5)
            except Exception:
                return False
            if resp.status_code == 401:
                return False
            try:
                if resp.json().get("authenticated", False):
                    return True
            except Exception:
                return False
            if attempt == 0:
                self.tickle()
                time.sleep(1)
        return False

    def get_auth_status(self) -> AuthStatus | dict[str, Any]:
        """Full authentication status including authenticated, competing, connected fields.

        Note: official docs document this endpoint as POST /iserver/auth/status (request
        object: empty JSON body). This method calls it via GET, matching ping()'s
        production-verified behavior (see ping() docstring) rather than the documented
        method, since no live test has been run to confirm POST is required. This method
        itself has no callers elsewhere in the codebase as of 2026-06-30.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/session/authentication-status.md
        Endpoint: GET /iserver/auth/status (see Note above)
        """
        return parse_one(AuthStatus, self._get("/iserver/auth/status"))

    def tickle(self) -> bool:
        """Keep the session alive. Returns True on HTTP 200. Never raises.

        Call every few minutes during idle periods. ConnectivityChecker calls this
        every 60s as a side effect of its /tickle poll, preventing IBKR auto-logout.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/session/ping-the-server.md
        Endpoint: POST /tickle
        """
        try:
            resp = self._session.post(f"{self._base}/tickle", timeout=5)
            return resp.status_code == 200
        except Exception:
            return False

    def reauthenticate(self) -> dict[str, Any]:
        """Request a new authentication session.

        Officially marked (Deprecated) — IBKR docs state all interest in
        reauthenticating the gateway session should be handled via
        POST /iserver/auth/ssodh/init instead. That endpoint is not implemented in
        this client: it is described as "essential for using all endpoints besides
        /portfolio" and is invoked by the browser-based Client Portal Gateway login
        flow (https://localhost:5055) itself, not by application code — claudia_ui's
        GatewayManager relies on that browser flow rather than calling it directly.

        Use only when get_auth_status() shows authenticated=false and the user
        has not recently logged in. Do NOT call proactively — it terminates any
        active authenticated session, including fresh logins.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/session/re-authenticate-the-brokerage-session-deprecated.md
        Endpoint: POST /iserver/reauthenticate (Deprecated)
        """
        return self._post("/iserver/reauthenticate")

    def validate_sso(self) -> dict[str, Any]:
        """Validate the SSO token. Used after initial login to confirm the session is active.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/session/validate-sso.md
        Endpoint: GET /sso/validate
        """
        return self._get("/sso/validate")

    # ------------------------------------------------------------------
    # Market Data
    # ------------------------------------------------------------------

    def get_market_history(
        self, conid: int, period: str = "1y", bar: str = "1d", outside_rth: bool = False
    ) -> MarketHistory | dict[str, Any]:
        """OHLCV bars via iserver/marketdata/history.

        ## Case sensitivity (verified live 2026-07-06)
        IBKR period/bar units are lowercase. Uppercase inputs are NOT rejected —
        the API silently substitutes a ~84-bar default (period='6M' returned 4
        months of dailies; '6m' returned the true 6 months). Inputs are therefore
        lowercased here before the request.

        Returns {"startTime": "...", "data": [{"o":..., "h":..., "l":..., "c":..., "v":..., "t":...}, ...]}.

        ## Data point limit (officially documented)
        Maximum 1000 data points per request. Pacing: 10 requests/second and 50 per
        minute on this endpoint (`rate_limiter.ENDPOINT_LIMITS`, paced before the request
        goes out). This line said "Concurrent request limit: 5" until 2026-09-17 — the value
        IBKR replaced at its 2026-08 documentation move (API-03), surviving here as a third
        prose copy after the two in `docs/` were corrected.
        Exceeding either limit returns HTTP 429.

        ## Valid period and bar values (from official docs, verified 2026-06-26)
        period: {1-30}min, {1-8}h, {1-1000}d, {1-792}w, {1-182}m, {1-15}y. Default: 1w.
        bar: 1min, 2min, 3min, 5min, 10min, 15min, 30min, 1h, 2h, 3h, 4h, 8h, 1d, 1w, 1m

        Step size — valid bar range and default for each period:
          period 1min → bar 1min       default 1min
          period 1h   → bar 1min-8h    default 1min
          period 1d   → bar 1min-8h    default 1min
          period 1w   → bar 10min-1w   default 15min
          period 1m   → bar 1h-1m      default 30min
          period 3m   → bar 2h-1m      default 1d
          period 6m   → bar 4h-1m      default 1d
          period 1y   → bar 8h-1m      default 1d
          period 2y   → bar 1d-1m      default 1d
          period 3y   → bar 1d-1m      default 1w
          period 15y  → bar 1w-1m      default 1w

        For requests that may exceed 1000 data points, use get_market_history_paginated()
        which chunks the request automatically using the startTime parameter.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/market-data/historical-market-data.md
        Endpoint: GET /iserver/marketdata/history
        """
        return parse_one(
            MarketHistory,
            self._get(
                "/iserver/marketdata/history",
                {"conid": conid, "period": period.lower(), "bar": bar.lower(), "outsideRth": str(outside_rth).lower()},
            ),
        )

    def get_market_history_paginated(
        self,
        conid: int,
        period: str = "1y",
        bar: str = "1d",
        outside_rth: bool = False,
    ) -> MarketHistory | dict[str, Any]:
        """Fetch OHLCV bars, assembling several requests when one cannot hold the span.

        A single request is capped at ~1000 data points, so a long lookback has to be
        pulled in chunks and merged. Results are merged, sorted by timestamp and
        deduplicated. This is the primary entry point for ClaudeToolkit.fetch_market_data().

        ## `startTime` is the END of the window, not the start

        The parameter that makes chunking work is also the one that is easy to read
        backwards. IBKR's OpenAPI spec (https://api.ibkr.com/gw/api/v3/api-docs) defines it
        as "a fixed UTC date-time reference point for the historical data request, **from
        which the specified period extends**" — and `direction` decides which way:

          -1  "data will begin away from the start time, ending at the current time/startTime"
           1  "begins at the start time, moving towards the current time"

        Measured against the live gateway 2026-08-05, conid 756733 (SPY), anchor
        `20231109-00:00:00`, `period=100d`:

          direction omitted  ->  99 pts, 2023-06-20 -> 2023-11-07
          direction=-1       ->  99 pts, 2023-06-20 -> 2023-11-07   (identical)
          direction=1        ->  {"error": "Chart data unavailable"}

        So the window **ends** at the anchor, the default is backwards, and the documented
        forward direction does not work on this endpoint even though `startTime` is
        supplied — exactly the condition the spec says it requires. `direction=-1` is now
        sent explicitly: relying on an undocumented default means a change at IBKR silently
        reverses every paged request.

        **This method read the parameter as the start until 2026-08-05.** Each chunk was
        therefore requested a full chunk-width too early and the newest chunk was never
        fetched at all. The failure was silent and plausible: SPY `5y`/`1w` returned 291
        well-formed weekly bars covering 2018-04-19 → 2023-10-30, while the raw endpoint
        returned 2021-08-09 → 2026-08-03. Nothing errored; the data was simply 1,010 days
        stale, and any analysis run on it would have been confidently wrong. It affected
        every request wider than one chunk — `3y`/`5y` on most bars, and `1y`/`2y` on `1h`.

        The newest chunk sends **no** `startTime`: "If omitted, the current time is used".
        Measured the same day on SPY `30d`/`1d` — omitted reached 2026-08-05, an explicit
        timestamp of that same moment reached 08-04, and midnight-today reached 08-03. Only
        the omitted form returns today's bar.

        Chunk sizes by bar, from `_chunk_days_for_bar` (80% of the 1000-point cap,
        against the worst-case continuously-traded day in `_BARS_PER_CALENDAR_DAY`):
          1min  → 1-calendar-day chunks
          2min  → 1-calendar-day chunks
          3min  → 1-calendar-day chunks
          5min  → 1-calendar-day chunks
          10min → 5-calendar-day chunks
          15min → 7-calendar-day chunks
          30min → 7-calendar-day chunks
          1h    → 30-calendar-day chunks
          2h    → 66-calendar-day chunks
          3h    → 90-calendar-day chunks
          4h    → 133-calendar-day chunks
          8h    → 266-calendar-day chunks
          1d    → 1000-calendar-day chunks
          1w    → 1000-calendar-day chunks
          1m    → 1000-calendar-day chunks

        Until 2026-09-17 the hourly row carried the width from *before* the 2026-09-15 live
        re-measurement — eight times the real one — and the table listed four bars of
        fifteen (API-08). The superseded number is deliberately not written in this
        paragraph in row form: a sentence that restates a checkable line can satisfy, or
        spuriously trip, the check that guards it. It is no longer maintained by hand:
        `test_the_documented_chunk_table_matches_what_the_code_computes` fails if any row
        disagrees with the function.

        **The assembled span is a floor, not an exact match.** IBKR sizes each chunk's
        response by its own bar alignment, so the union can reach further back than asked:
        measured 2026-08-05, SPY `5y`/`1w` returned 316 bars spanning 6.0 years and
        `3y`/`1w` returned 209 spanning 4.0. Callers get *at least* the requested period,
        ending at the present. Trimming to an exact window is deliberately not done here —
        silently discarding real bars a caller may want is the worse failure, and the
        DataFrame carries its own index for anyone who needs a precise slice.

        Endpoint: GET /iserver/marketdata/history
        """
        from datetime import datetime, timedelta

        total_days = _parse_period_days(period)
        chunk_days = _chunk_days_for_bar(bar)

        # The fast path is an optimisation and is only sound when ONE call can carry the
        # whole span: a width that fits in a chunk still overflows the 1000-point cap for
        # 1-minute bars (see _fits_in_one_call). When in doubt, take the loop — it costs a
        # request and cannot lose data.
        if total_days is None or (total_days <= chunk_days and _fits_in_one_call(total_days, bar)):
            return self.get_market_history(conid, period, bar, outside_rth)

        all_bars: list[dict[str, Any]] = []
        envelope: dict[str, Any] = {}
        now = datetime.utcnow()
        target = now - timedelta(days=total_days)

        # The cursor is the END of the next window, and it advances to the OLDEST bar that
        # actually arrived — never by the width that was requested. That distinction is the
        # whole correctness argument: a chunk that hits the 1000-point cap covers less ground
        # than it asked for, and the endpoint says so only by returning fewer bars. Advancing
        # by the request width opened an unannounced hole between every pair of chunks
        # (measured 2026-09-15: 30d/1min returned ~15% of its bars, in five islands).
        # Advancing by the response cannot lose data whatever the size estimate does — it
        # only takes more requests.
        cursor: datetime | None = None  # None == "now"
        truncation_warning: str | None = None
        for _ in range(_MAX_CHUNKS):
            params: dict[str, Any] = {
                "conid": conid,
                "period": f"{chunk_days}d",
                "bar": bar,
                "outsideRth": str(outside_rth).lower(),
            }
            if cursor is not None:
                # `startTime` is the END of the window (see the method docstring), so the
                # anchor is where this chunk stops, not where it starts.
                params["startTime"] = cursor.strftime("%Y%m%d-%H:%M:%S")
                params["direction"] = -1
            # The first chunk sends NO startTime: "If omitted, the current time is used"
            # (IBKR's OpenAPI spec). Measured 2026-08-05 on SPY 30d/1d — omitted reached
            # 2026-08-05, an explicit timestamp of the same moment reached 08-04, and
            # midnight-today reached 08-03. Only the omitted form returns today's bar,
            # and on a trading surface today is the bar that matters most.
            result = self._get("/iserver/marketdata/history", params)
            if not result:
                break
            if not envelope:
                envelope = {k: v for k, v in result.items() if k != "data"}
            bars = result.get("data") or []
            if not bars:
                break
            all_bars.extend(bars)

            stamps = [b["t"] for b in bars if b.get("t") is not None]
            if not stamps:
                break
            oldest = datetime.utcfromtimestamp(min(stamps) / 1000)
            if cursor is not None and oldest >= cursor:
                # No progress: the window did not move back. Stopping beats looping.
                log.warning("market history pagination stalled at %s (conid=%s bar=%s)", oldest, conid, bar)
                break
            cursor = oldest
            if oldest <= target:
                break
        else:
            # The loop ran to exhaustion: every chunk returned data and the target was
            # never reached, so the answer is well-formed and covers less than was asked.
            # A log line reaches no caller, no model and no cache — measured against the
            # truncating stub, `180d/1min` comes back with 46% of its span and `1y/5min`
            # with 33%, and a backtest labelled "1 year" that silently saw four months
            # draws a conclusion about a period it never had. So the response says so, in
            # the response (audit finding API-02, 2026-09-16).
            truncated_at = cursor.strftime("%Y-%m-%d") if cursor is not None else "an unknown date"
            truncation_warning = (
                f"INCOMPLETE: asked for {period} of {bar} bars but stopped at the "
                f"{_MAX_CHUNKS}-chunk safety guard. The data returned goes back only to "
                f"{truncated_at}, not the full {period}. Request a shorter period, or a "
                f"larger bar size, to cover the whole span."
            )
            log.warning(
                "market history pagination hit the %d-chunk guard (conid=%s period=%s bar=%s); "
                "returned data starts at %s, not the full requested span",
                _MAX_CHUNKS,
                conid,
                period,
                bar,
                cursor,
            )

        if not all_bars:
            return {}

        seen: set[int] = set()
        unique: list[dict[str, Any]] = []
        for b in sorted(all_bars, key=lambda x: x.get("t", 0)):
            t = b.get("t")
            if t is not None and t not in seen:
                seen.add(t)
                unique.append(b)

        result_envelope = dict(envelope)
        if truncation_warning is not None:
            # Namespaced so it can never collide with a field IBKR adds to its own envelope.
            result_envelope["ibkr_core_warning"] = truncation_warning
        return parse_one(MarketHistory, {**result_envelope, "data": unique})

    def get_market_snapshot(self, conids: list[int], fields: list[str] | None = None) -> list[dict[str, Any]]:
        """Live quote snapshot for one or more contracts. Returns [] if response is not a list.

        Default fields:
          31  Last Price    — may be prefixed C (prev close) or H (halted)
          55  Symbol
          70  High          — current day high
          71  Low           — current day low
          82  Change        — price change vs prior close
          83  Change %      — change as percentage
          84  Bid Price     — highest bid
          86  Ask Price     — lowest ask
          87  Volume        — day volume (K/M suffix for thousands/millions)
          6509 Availability — first char: R=RealTime, D=Delayed, N=NotSubscribed,
                              Z=Frozen, Y=FrozenDelayed, O=API agreement incomplete

        Subscription note: field 6509 starting with 'N' = no market data subscription for
        that exchange. Different exchanges require separate IBKR subscriptions — NYSE, NASDAQ,
        NYSE Arca (ETFs) are each distinct. Without a subscription, price fields are absent
        and 6509 returns 'N'. Check Account Management → Settings → Market Data Subscriptions.

        Note: per official docs, /iserver/accounts is documented as required only before
        order writes/reads (see get_brokerage_accounts()), not before market data snapshots.
        This method does not call it.

        First snapshot call for a new conid initialises the subscription but returns no
        price fields — caller should retry after ~1s.

        Limits: max 100 conids per request, max 50 fields per request.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/market-data/live-market-data-snapshot.md
        Changelog: https://www.interactivebrokers.com/campus/ibkr-api-page/web-api-changelog/
        Endpoint: GET /iserver/marketdata/snapshot
        """
        field_str = ",".join(fields or ["31", "55", "70", "71", "82", "83", "84", "86", "87", "6509"])
        data = self._get(
            "/iserver/marketdata/snapshot", {"conids": ",".join(str(c) for c in conids), "fields": field_str}
        )
        return data if isinstance(data, list) else []

    def unsubscribe_market_data(self, conid: int) -> dict[str, Any]:
        """Unsubscribe a specific contract from streaming market data.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/market-data/unsubscribe-single.md
        Endpoint: POST /iserver/marketdata/unsubscribe
        """
        return self._post("/iserver/marketdata/unsubscribe", {"conid": conid})

    def unsubscribe_all_market_data(self) -> dict[str, Any]:
        """Cancel all active streaming market data subscriptions.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/market-data/unsubscribe-all.md
        Endpoint: GET /iserver/marketdata/unsubscribeall
        """
        return self._get("/iserver/marketdata/unsubscribeall")

    # ------------------------------------------------------------------
    # Contract / Security Definition
    # ------------------------------------------------------------------

    def search_contract(self, symbol: str, sec_type: str = "STK") -> list[Contract | dict[str, Any]]:
        """Resolve a symbol to one or more contracts. Returns [] if no match.

        Returns [{"conid", "companyHeader", "companyName", "symbol", "description",
        "restricted", "sections", "secType"}]. Corrected 2026-08-05 — this previously
        documented `exchange` and `currency` keys, and **neither exists**: the endpoint
        returns no currency at all, and the exchange appears only as `description`
        ("Primary exchange of the contract", a bare code like "BATS" or "MEXI") and inside
        `sections`. A caller reading a currency off this response reads `None`, which is
        the one field that separates a US listing from its foreign twin.

        **The order of the returned list is not documented as meaningful**, so `[0]` is not
        "the best match". It is the Mexican listing for IGV. Callers that need *the* conid
        for a symbol must use `ClaudeToolkit._resolve_stock_conid` (`/trsrv/stocks`, which
        carries `isUS`), never this.

        sec_type: officially documented valid values are "STK", "IND", "BOND" only.
        FUT and CASH (FX) are NOT supported here — use get_futures() (/trsrv/futures)
        and get_currency_pairs() (/iserver/currency/pairs) respectively. OPT requires
        the separate secdef/search -> secdef/info flow (see get_secdef_info()).

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/contract/search-contract-by-symbol.md
                (read 2026-08-05; the old cpapi-v1 anchor redirects and drops the fragment)
        Endpoint: GET /iserver/secdef/search
        """
        data = self._get("/iserver/secdef/search", {"symbol": symbol, "secType": sec_type})
        return parse_many(Contract, data)

    def get_contract_info(self, conid: int) -> ContractDetails | dict[str, Any]:
        """Full contract metadata: exchange, currency, primary exchange, trading class, multiplier.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/contract/contract-information-by-contract-id.md
        Endpoint: GET /iserver/contract/{conid}/info
        """
        _validate_conid(conid)
        return parse_one(ContractDetails, self._get(f"/iserver/contract/{conid}/info"))

    def get_contract_info_and_rules(self, conid: int) -> ContractDetails | dict[str, Any]:
        """Contract info plus trading rules (min tick, valid order types, etc.).

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/contract/find-all-info-and-rules-for-a-given-contract.md
        Endpoint: GET /iserver/contract/{conid}/info-and-rules
        """
        _validate_conid(conid)
        return parse_one(ContractDetails, self._get(f"/iserver/contract/{conid}/info-and-rules"))

    def get_contract_algos(self, conid: int) -> list[Algo | dict[str, Any]]:
        """Available algorithmic order types for a contract: [{id, name, parameters}, ...].

        The response is an OBJECT wrapping the array — ``{"algos": [...]}`` — matching the
        endpoint's documented "algos: Array of objects". Corrected 2026-09-16: this method
        read ``data if isinstance(data, list) else []``, which cannot match an object, so it
        returned ``[]`` on every call; a live gateway returned 10 algos for GLD. Same shape
        and cause as ``get_currency_pairs`` (2026-06-30), ``get_secdef`` (2026-07-28) and
        ``get_watchlists`` (2026-08-11) — see ``docs/ibkr-api-behaviors-reference.md``.

        A bare list is still accepted; the only cost is tolerating a shape IBKR does not
        currently publish, and the alternative is another silent empty.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/contract/search-algo-params-by-contract-id.md
        Endpoint: GET /iserver/contract/{conid}/algos
        """
        _validate_conid(conid)
        data = self._get(f"/iserver/contract/{conid}/algos")
        if isinstance(data, dict):
            return parse_many(Algo, data.get("algos"))
        return parse_many(Algo, data)

    def get_secdef_info(self, conid: int) -> SecDefInfo | dict[str, Any]:
        """Security definition info: type, symbol, currency, exchange, listing exchange.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/contract/search-sec-def-information-by-conid.md
        Endpoint: GET /iserver/secdef/info
        """
        return parse_one(SecDefInfo, self._get("/iserver/secdef/info", {"conid": conid}))

    def get_option_strikes(
        self, conid: int, sec_type: str, month: str, exchange: str = "SMART"
    ) -> dict[str, list[float]]:
        """Available strikes for one expiry month, split into call/put arrays.

        month format per the official spec: {3-char month}{2-char year}, e.g. "JAN26".
        Returns {"call": [...], "put": [...]} — the documented response shape (there
        is no "strike" key; earlier code read one and always got []). Always returns
        empty arrays unless /iserver/secdef/search was called for the same underlying
        beforehand (without the `name` field).

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/contract/search-strikes-by-underlying-contract-id.md
        Endpoint: GET /iserver/secdef/strikes
        """
        data = self._get(
            "/iserver/secdef/strikes", {"conid": conid, "sectype": sec_type, "month": month, "exchange": exchange}
        )
        return {"call": data.get("call", []), "put": data.get("put", [])}

    def get_option_chain(
        self, symbol: str, month: str | None = None, exchange: str = "SMART"
    ) -> OptionChain | dict[str, Any]:
        """Option chain for an underlying via the documented two-step flow.

        1. GET /iserver/secdef/search?symbol=<sym> — required first call (primes the
           session; strikes returns empty arrays otherwise) and source of the OPT
           section's expiry months ("JAN26;FEB26;...").
        2. GET /iserver/secdef/strikes for the requested month (format "JAN26"),
           defaulting to the nearest available expiry.

        Returns {"symbol", "conid", "months": [all expiries], "month": <queried>,
        "call": [strikes], "put": [strikes]}. Raises IBKRAPIError when the underlying
        has no OPT section or no expiry months.

        Reimplemented 2026-07-07 (audit register item 6) — replaces the previous call
        to /trsrv/secdef/chains, which is absent from the documented CP API and 404'd
        on every call.
        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/contract/search-contract-by-symbol.md
        Endpoints: GET /iserver/secdef/search + GET /iserver/secdef/strikes
        """
        results = self._get("/iserver/secdef/search", {"symbol": symbol})
        conid: int | None = None
        months: list[str] = []
        for entry in results or []:
            sections = entry.get("sections") or []
            opt = next((s for s in sections if s.get("secType") == "OPT"), None)
            if opt is not None and entry.get("conid"):
                conid = int(entry["conid"])
                months = [m for m in (opt.get("months") or "").split(";") if m]
                break
        if conid is None:
            raise IBKRAPIError(f"No options available for {symbol!r} — secdef/search returned no OPT section.")
        if not months:
            raise IBKRAPIError(f"No option expiry months listed for {symbol!r} (conid {conid}).")
        chosen = month.upper() if month else months[0]
        strikes = self._get(
            "/iserver/secdef/strikes",
            {"conid": conid, "sectype": "OPT", "month": chosen, "exchange": exchange},
        )
        return parse_one(
            OptionChain,
            {
                "symbol": symbol.upper(),
                "conid": conid,
                "months": months,
                "month": chosen,
                "call": strikes.get("call", []),
                "put": strikes.get("put", []),
            },
        )

    def get_bond_filters(self, symbol: str, issue_id: str) -> dict[str, Any]:
        """Available filter criteria for bond search.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/contract/search-bond-filter-information.md
        Endpoint: GET /iserver/secdef/bond-filters
        """
        return self._get("/iserver/secdef/bond-filters", {"symbol": symbol, "issuerId": issue_id})

    def get_futures(self, symbols: list[str]) -> list[FutureContract | dict[str, Any]]:
        """Futures contracts for root symbols, flattened to one list.

        IBKR returns {"CL": [...], "ES": [...]} — `_flatten_buckets` concatenates the
        arrays, raises `IBKRAPIError` on a 2xx `{"error": …}` object, and answers [] for
        any other shape.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/contract/security-future-by-symbol.md
        Endpoint: GET /trsrv/futures
        """
        data = self._get("/trsrv/futures", {"symbols": ",".join(symbols)})
        return parse_many(FutureContract, _flatten_buckets(data, "/trsrv/futures"))

    def get_stocks(self, symbols: list[str]) -> list[StockSearchResult | dict[str, Any]]:
        """Stock contracts for symbols. Same dict-flattening behaviour as get_futures().

        The response is keyed by symbol; each value is a list of company records carrying
        `name`, `assetClass` and a `contracts` list, and each contract carries `conid`,
        `exchange` and **`isUS`** — *"States whether the contract is hosted in the United
        States or not"*. That boolean is why this endpoint, and not
        `/iserver/secdef/search`, is the one that can answer "which listing did they mean".

        Flattening drops the symbol key, so callers resolving more than one symbol at a
        time cannot tell the records apart — pass one symbol per call when that matters.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/contract/security-stocks-by-symbol.md
                (read 2026-08-05; the old cpapi-v1 anchor redirects and drops the fragment)
        Endpoint: GET /trsrv/stocks
        """
        data = self._get("/trsrv/stocks", {"symbols": ",".join(symbols)})
        return parse_many(StockSearchResult, _flatten_buckets(data, "/trsrv/stocks"))

    def get_trading_schedule(
        self,
        asset_class: str,
        symbol: str = "",
        exchange: str = "",
        exchange_filter: str = "",
        conid: int | str = "",
    ) -> list[TradingSchedule | dict[str, Any]]:
        """Trading hours, sessions, and timezone for a contract.

        **IBKR publishes three pages for "trading schedule" and they do not agree.** The
        API Reference below is the one this method follows; it was confirmed against a live
        gateway on 2026-09-16, key for key.

        - `api-reference/.../get-trading-schedule.md` — **authoritative for this endpoint.**
          `assetClass` and `symbol` required, `exchange`/`exchangeFilter` optional. It
          documents **no `conid` parameter at all**, and its response object matches the
          wire exactly, all six keys.
        - `v1/endpoints/contract/trading-schedule-by-symbol.md` — the older narrative page.
          It lists **both** `conid` and `symbol` as *Required*, which no gateway accepts,
          and its response object omits `exchange` and `description`. Do not follow it.
        - `v1/endpoints/contract/trading-schedule-new.md` — a **different endpoint**,
          `GET /contract/trading-schedule`, keyed by `conid` and returning a different
          shape. Not implemented here.

        `conid` is accepted as an undocumented alternative to `symbol`: the gateway refuses
        both together and refuses neither, with

            {"error":"Bad Request: assetClass and exactly one of symbol/conid are required"}

        so this method requires exactly one and refuses the other two cases locally rather
        than spending a request to be told. Prefer `symbol`, which is the documented one.

        `exchange` matters more than it looks, and **omitting it returns the most**:
        measured on AAPL, no exchange **141 rows**, `ISLAND` 125, `SMART` **0**.

        SMART is IBKR's smart-routing destination and the right default nearly everywhere —
        `get_option_chain`, secdef strikes and the alert condition all pass it correctly.
        Here it is the exception: this `exchange` means *a venue with published trading
        hours*, not a route, and SMART has none, so the endpoint returns an empty list
        rather than an error. The fixture's `trading_schedule` was that empty list until
        the 2026-09-17 re-capture, which dropped the `exchange` argument and recorded the
        141 rows the endpoint really returns — so this paragraph described a fixture that
        no longer existed for a day. The empty case is reproduced by passing
        `exchange="SMART"`, not by reading the fixture.

        Returns IBKR's rows unchanged: `id`, `tradeVenueId`, `exchange`, `description`,
        `timezone`, `schedules[]`. There is no `regularTradingHours` or `liquidHours` —
        `docs/tools-reference.md` promised both until 2026-09-16 and neither exists.

        Source: https://ibkrcampus.com/docs/web-api/api-reference/trading/trading-contracts/get-trading-schedule.md
        Endpoint: GET /trsrv/secdef/schedule
        """
        has_conid = conid != ""
        if has_conid == bool(symbol):
            raise ConfigError(
                "get_trading_schedule needs exactly one of symbol or conid — IBKR returns "
                'HTTP 400 "assetClass and exactly one of symbol/conid are required" for '
                "both together and for neither."
            )
        params = {"assetClass": asset_class}
        if has_conid:
            _validate_conid(conid)
            params["conid"] = str(conid)
        else:
            params["symbol"] = symbol
        if exchange:
            params["exchange"] = exchange
        if exchange_filter:
            params["exchangeFilter"] = exchange_filter
        return parse_many(TradingSchedule, self._get("/trsrv/secdef/schedule", params))

    def get_secdef(self, conids: list[int]) -> list[Contract | dict[str, Any]]:
        """Batch security definitions for up to 200 conids: [{conid, currency, ...}, ...].

        The response is an OBJECT wrapping the array — ``{"secdef": [{...}, {...}]}`` —
        not a bare list. Corrected 2026-07-28: this method previously returned
        ``data if isinstance(data, list) else []``, so it discarded every result and
        returned ``[]`` on every call, silently. Identical in shape and cause to the
        ``get_currency_pairs`` defect fixed 2026-06-30; both endpoints key their array
        under a name, and both were read as if the array were the whole body.

        A bare list is still accepted, since the only cost is tolerating a response IBKR
        does not currently document and the alternative is another silent empty.

        Each record carries ``currency``, ``listingExchange``, ``countryCode``, ``isUS``,
        ``name``, ``assetClass`` and more — the same facts
        ``/iserver/secdef/info`` returns one conid at a time. This is the batch path for
        them (200 conids/request per IBKR's usage limits), so prefer it over a loop.

        **Live-verified 2026-09-16** (the gateway was offline when this was written, and
        this note used to say the fix rested on the documentation alone):
        `get_secdef([265598, 272093])` returned 2 records carrying `conid`, `currency`,
        `assetClass`, `countryCode`, `fullName`, `allExchanges` and the rest.
        `tests/test_client_live.py::test_get_secdef_batch` covers it.

        Source: https://www.interactivebrokers.com/docs/web-api/v1/endpoints/contract/search-the-security-definition-by-contract-id
                (scraped 2026-07-28: "Returns a list of security definitions for the
                given conids `GET /trsrv/secdef`", Response Object "secdef: array")
        Endpoint: GET /trsrv/secdef?conids=<comma-separated>
        """
        data = self._get("/trsrv/secdef", {"conids": ",".join(str(c) for c in conids)})
        if isinstance(data, dict):
            data = data.get("secdef")
        return parse_many(Contract, data)

    def get_currency_pairs(self, currency: str) -> list[CurrencyPair | dict[str, Any]]:
        """Available FX pairs for a target currency: [{symbol, conid, ccyPair}, ...].

        Response is keyed by the requested currency, e.g. {"USD": [{"symbol": "USD.SGD",
        "conid": 37928772, "ccyPair": "SGD"}, ...]} — flattened to a list here, same
        dict-flattening behaviour as get_futures()/get_stocks().

        Corrected 2026-06-30: previously called the undocumented /iserver/secdef/currency
        (always returned [] — response is a dict, not a list, so the old isinstance(list)
        check silently discarded every result). /iserver/secdef/search also does not
        document CASH as a valid secType (only STK, IND, BOND) — this is the only
        documented FX resolution path.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/contract/currency-pairs.md
        Endpoint: GET /iserver/currency/pairs
        """
        data = self._get("/iserver/currency/pairs", {"currency": currency})
        return parse_many(CurrencyPair, _flatten_buckets(data, "/iserver/currency/pairs"))

    def get_contract_rules(self, conid: int, is_buy: bool = True) -> ContractRules | dict[str, Any]:
        """Order rules for a contract: min tick, valid order types, size constraints.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/contract/search-contract-rules.md
        Endpoint: POST /iserver/contract/rules
        """
        return parse_one(ContractRules, self._post("/iserver/contract/rules", {"conid": conid, "isBuy": is_buy}))

    # ------------------------------------------------------------------
    # Portfolio
    # ------------------------------------------------------------------

    def get_accounts(self) -> list[Account | dict[str, Any]]:
        """All accounts associated with the authenticated session. Returns [] if not a list.

        Returns [{"accountId": "U1234567", ...}].

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/portfolio/portfolio-accounts.md
        Endpoint: GET /portfolio/accounts
        """
        return parse_many(Account, self._get("/portfolio/accounts"))

    def get_subaccounts(self) -> list[Account | dict[str, Any]]:
        """Sub-accounts for IB Family accounts and advisors. Returns [] if not a list.

        Returns `Account` rows: this endpoint's records were measured key-for-key identical
        to `/portfolio/accounts` (24 keys, 2026-09-17), so it shares that model rather than
        getting a second one that would drift from it.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/portfolio/portfolio-subaccounts.md
        Endpoint: GET /portfolio/subaccounts
        """
        return parse_many(Account, self._get("/portfolio/subaccounts"))

    def get_account_meta(self, account_id: str) -> Account | dict[str, Any]:
        """Account metadata: display name, status, type.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/portfolio/specific-accounts-portfolio-information.md
        Endpoint: GET /portfolio/{accountId}/meta
        """
        _validate_account_id(account_id)
        return parse_one(Account, self._get(f"/portfolio/{account_id}/meta"))

    def get_account_summary(self, account_id: str) -> AccountSummary | dict[str, Any]:
        """Net liquidation and cash. Response uses nested {"amount": value} objects.

        **This endpoint publishes no profit-and-loss key.** Its page documents none, and
        a 108-key capture on 2026-09-16 contained none; `AccountSummary.unrealized_pnl`
        and `.realized_pnl` accordingly read `None`, not `0.0`. P&L comes from
        `get_pnl()` (/iserver/account/pnl/partitioned), as `upnl.{account}.{upl,dpl}`.
        The docstring here said "Net liquidation, cash, P&L" until 2026-09-16.

        The returned `AccountSummary` keeps the whole response: `summary["netliquidation"]`
        is IBKR's own `{"amount", "currency", "isNull", "timestamp", "value"}` object,
        including the currency the four typed attributes drop.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/portfolio/portfolio-summary.md
        Endpoint: GET /portfolio/{accountId}/summary
        """
        _validate_account_id(account_id)
        return parse_one(AccountSummary, self._get(f"/portfolio/{account_id}/summary"))

    def get_account_ledger(self, account_id: str) -> dict[str, Any]:
        """Cash balances by currency with detailed ledger fields.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/portfolio/portfolio-ledger.md
        Endpoint: GET /portfolio/{accountId}/ledger
        """
        _validate_account_id(account_id)
        return self._get(f"/portfolio/{account_id}/ledger")

    def get_account_allocation(self, account_id: str) -> dict[str, Any]:
        """Portfolio breakdown by asset class, sector, and industry.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/portfolio/portfolio-allocation-single.md
        Endpoint: GET /portfolio/{accountId}/allocation
        """
        _validate_account_id(account_id)
        return self._get(f"/portfolio/{account_id}/allocation")

    def get_positions(self, account_id: str, page: int = 0) -> list[Position | dict[str, Any]]:
        """Open positions, one page at a time (page 0 = first 100). Returns [] if not a list.

        The page size is **100**, not 30. IBKR's cited page says so twice — "The endpoint
        supports paging, each page will return up to 100 positions" and "One page contains a
        maximum of 100 positions" (audit finding API-05, corrected 2026-09-16). Nothing in
        this package chunked by 30, so the figure was a docstring claim only.

        Documentation-confirmed, live-indeterminate: the gateway build here returns no
        `pageSize` field at all (measured 2026-09-16 — every row had `pageSize: None`), and
        the test account holds 2 positions, so the boundary cannot be observed directly.

        **Use `get_all_positions` unless you specifically want one page.** Both callers —
        `ClaudeToolkit._get_positions` and the `ibkr://positions/current` resource — took
        this method's default and stopped, so an account past one page was reported with
        its first page and no indication there were more (API-17, fixed 2026-09-16).

        Returns [{"conid": ..., "contractDesc": ..., "position": ..., "mktPrice": ...,
        "mktValue": ..., "unrealizedPnl": ..., "realizedPnl": ...}].

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/portfolio/positions.md
        Endpoint: GET /portfolio/{accountId}/positions/{page}
        """
        _validate_account_id(account_id)
        _validate_page(page)
        data = self._get(f"/portfolio/{account_id}/positions/{page}")
        return parse_many(Position, data)

    def get_all_positions(self, account_id: str, max_pages: int = 50) -> list[Position | dict[str, Any]]:
        """Every open position, paging until the account runs out.

        `get_positions` returns one page and every caller took the default, so an account
        with more than one page of positions was reported with its first page and no
        indication there were more — API-17, the same silently-incomplete shape as API-02.

        **This does not need to know the page size**, which is what makes it safe to ship
        without an account big enough to test the boundary. Measured live 2026-09-16 on a
        2-position account: page 0 returned both rows, and pages 1, 2 and 5 each returned
        `[]` rather than an error. So "read until a page comes back empty" is correct
        whether IBKR's page holds 30 or 100 — the unresolved half of API-05.

        A page shorter than the one before it is the last page, so no confirming request is
        spent on a rate-limited endpoint.

        `max_pages` is a runaway guard, and hitting it **raises**. Returning a quietly
        truncated list would be exactly the defect API-02 was: an incomplete answer that
        looks complete. There is no response envelope here to carry a warning in.
        """
        collected: list[Position | dict[str, Any]] = []
        previous = -1
        for page in range(max_pages):
            rows = self.get_positions(account_id, page=page)
            if not rows:
                return collected
            collected.extend(rows)
            if previous >= 0 and len(rows) < previous:
                return collected
            previous = len(rows)
        raise IBKRAPIError(
            f"get_all_positions stopped at max_pages={max_pages} with {len(collected)} "
            f"positions and more still available. Raise max_pages if this account really "
            f"holds that many; otherwise this is a paging bug, not a large account."
        )

    def get_positions_by_conid(self, conid: int) -> list[dict[str, Any]]:
        """Position data for a specific contract across all accounts, flattened to one list.

        The gateway returns an **account-keyed object** — ``{"U1234567": [...],
        "U1234567C": [...]}``, one bucket per account holding the contract. The keys are
        account ids, so no fixed key name can find them; every bucket is concatenated.

        This **diverges from the endpoint's own documentation**, whose sample is a bare
        array, so both shapes are accepted and the divergence is recorded (verified live
        2026-09-16, ``docs/ibkr-api-behaviors-reference.md``). Until then the method read
        ``data if isinstance(data, list) else []`` and reported no position for a contract
        the account actually held.

        Note the cited page is the one that declares this endpoint. ``positions-by-conid.md``
        is a similarly-named page documenting ``GET /portfolio/{acctId}/position/{conid}`` —
        a different endpoint — and reading the shape off it gives the wrong answer.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/portfolio/position-contract-info.md
        Endpoint: GET /portfolio/positions/{conid}
        """
        _validate_conid(conid)
        data = self._get(f"/portfolio/positions/{conid}")
        # Keyed by account id, one bucket per account holding the contract, so the key
        # names are account-specific and cannot be looked up by a fixed name.
        rows = _flatten_buckets(data, "/portfolio/positions/{conid}")
        return [row for row in rows if isinstance(row, dict)]

    def get_position(self, account_id: str, conid: int) -> dict[str, Any]:
        """Position for a specific account + contract pair.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/portfolio/positions-by-conid.md
        Endpoint: GET /portfolio/{accountId}/position/{conid}
        """
        _validate_account_id(account_id)
        _validate_conid(conid)
        return self._get(f"/portfolio/{account_id}/position/{conid}")

    def get_combo_positions(self, account_id: str) -> list[dict[str, Any]]:
        """Combo/spread positions for an account. Returns [] if not a list.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/portfolio/combination-positions.md
        Endpoint: GET /portfolio/{accountId}/combo/positions
        """
        _validate_account_id(account_id)
        data = self._get(f"/portfolio/{account_id}/combo/positions")
        return data if isinstance(data, list) else []

    def get_portfolio_allocation(self, account_ids: list[str]) -> dict[str, Any]:
        """Aggregated allocation across multiple accounts.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/portfolio/portfolio-allocation-all.md
        Endpoint: POST /portfolio/allocation
        """
        return self._post("/portfolio/allocation", {"acctIds": account_ids})

    def invalidate_positions_cache(self, account_id: str) -> dict[str, Any]:
        """Force-refresh the IBKR position cache. Call before get_positions() if data looks stale.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/portfolio/invalidate-backend-portfolio-cache.md
        Endpoint: POST /portfolio/{accountId}/positions/invalidate
        """
        _validate_account_id(account_id)
        return self._post(f"/portfolio/{account_id}/positions/invalidate")

    # ------------------------------------------------------------------
    # Orders (read-only)
    # ------------------------------------------------------------------

    # Statuses that indicate an order is still active in the market.
    # Filled/Cancelled orders are executions, not live orders.
    _TERMINAL_STATUSES = frozenset(
        {
            "Filled",
            "Cancelled",
            "ApiCancelled",
            "Expired",
        }
    )

    def _read_live_orders(self) -> Any:
        """One plain read of /iserver/account/orders, unwrapped from its envelope."""
        data = self._get("/iserver/account/orders")
        return data.get("orders", data) if isinstance(data, dict) else data

    def _prime_orders_subscription(self) -> None:
        """Instantiate the orders subscription, for a session that has not read yet.

        "A fresh brokerage session returns an EMPTY list on the first call" — the same
        warmup `get_trades` handles by re-reading. `force=true` is IBKR's documented way
        to "clear saved information and make a fresh request for orders", and its own
        response is expected to be blank:

            "Force the system to clear saved information and make a fresh request for
             orders. Submission will appear as a blank array."
            https://www.interactivebrokers.com/docs/web-api/v1/endpoints/order-monitoring/live-orders

        This used to run before EVERY read, which spent two slots of a 1-req/5-secs
        endpoint to answer one question. Measured live 2026-09-16 on a warm session,
        three consecutive plain reads each returned the open order without it, while the
        unconditional pair made `get_live_orders()` take 5.17 s and 10.07 s back to back
        once pacing was honoured (audit finding API-14).
        """
        self._get("/iserver/account/orders?force=true")
        time.sleep(1)

    def get_live_orders(self) -> list[Order | dict[str, Any]]:
        """Working orders only (PreSubmitted, Submitted, ApiPending, PendingSubmit, PendingCancel, Inactive).

        Two-call pattern required: first call with ?force=true instantiates the subscription;
        second call returns the actual live order list.
        Inactive = order exists on IBKR but is stalled (e.g. failed risk check).

        **An unrecognisable response raises rather than returning `[]`.** The documented
        body is `{"orders": [...], "snapshot": bool}`. Until 2026-08-07 anything else —
        an error object returned with HTTP 200, a scalar, a dict with no `orders` key —
        fell through to `return []`, which answers "do I have working orders?" with a
        confident *no*. That is the one wrong answer this method must never give, and
        `get_orders_raw` existing as a diagnostic escape hatch is the sign the shape was
        already known to surprise. An empty *list* from IBKR is still returned as `[]`:
        that empty is an answer.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/order-monitoring/live-orders.md
                https://www.interactivebrokers.com/campus/trading-lessons/request-modify-orders/
        Endpoint: GET /iserver/account/orders

        Returns:
            Working orders only, terminal statuses filtered out.

        Raises:
            IBKRAPIError: If the response body is not the documented shape, so the
                caller can tell "the gateway did not answer" from "nothing is working".
        """
        self._ensure_accounts_initialized()
        orders = self._read_live_orders()
        if isinstance(orders, list) and not orders:
            # Empty may mean "no live orders" or "subscription not primed yet", and the
            # two are indistinguishable in the response. Prime and read once more; if it
            # was genuinely empty this costs one extra call and still returns [].
            self._prime_orders_subscription()
            orders = self._read_live_orders()
        if not isinstance(orders, list):
            raise IBKRAPIError(
                f"/iserver/account/orders returned {type(orders).__name__}, not the documented "
                f"orders array. Refusing to report this as 'no live orders'. Use get_orders_raw() "
                f"or the diagnose_orders tool to see what the gateway actually sent.",
                status_code=0,
            )
        working = [o for o in orders if o.get("status") and o.get("status") not in self._TERMINAL_STATUSES]
        return parse_many(Order, working)

    def get_orders_raw(self) -> Any:
        """Raw, unfiltered /iserver/account/orders response, for diagnostics.

        Same documented two-call warmup as get_live_orders, but returns the response
        exactly as IBKR sent it — no status filtering, no shape normalization. Used
        by ClaudeToolkit's diagnose_orders to show what the server actually returned.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/order-monitoring/live-orders.md
        Endpoint: GET /iserver/account/orders
        """
        self._ensure_accounts_initialized()
        data = self._get("/iserver/account/orders")
        orders = data.get("orders", data) if isinstance(data, dict) else data
        if isinstance(orders, list) and not orders:
            self._prime_orders_subscription()
            data = self._get("/iserver/account/orders")
        return data

    def get_order_status(self, order_id: str) -> dict[str, Any]:
        """Full order details for a specific order ID.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/order-monitoring/order-status.md
        Endpoint: GET /iserver/account/order/status/{orderId}
        """
        _validate_order_id(order_id)
        self._ensure_accounts_initialized()
        return self._get(f"/iserver/account/order/status/{order_id}")

    def get_trades(self) -> list[Trade | dict[str, Any]]:
        """Trade executions for the current day + up to 6 previous days (7-day window).

        **This is the package's direct access point for TODAY's and recent fills** —
        the only REST source that can contain same-day executions (Flex is T+1 and
        never contains today). Exposed to the LLM as `get_trades(source='live')`.

        ## ?days parameter — corrected 2026-08-06 against the official page
        IBKR's reference says: "Returns a list of trades for the currently selected
        account for current day and six previous days", and its own example passes
        `days=3`. It documents **no maximum**
        (https://ibkrcampus.com/docs/web-api/v1/endpoints/order-monitoring/trades.md).

        Two claims previously stated here were wrong and are corrected rather than
        quietly deleted, because both were repeated downstream:

        * "up to a maximum of 7 days" — **not documented.** A `days=30` request was
          accepted and returned rows on 2026-08-06, though every fill it returned fell
          inside seven days anyway, so that observation does not establish whether a
          wider window is honoured. 7 is what we ask for, not a known ceiling.
        * "If unspecified, only the current day is returned" — **contradicted**, by the
          sentence quoted above and by measurement: a no-parameter call returned the same
          23 rows as `days=30` on 2026-08-06.

        Oddity worth knowing: `days=1` and `days=2` returned **zero** rows on a day that
        had fills, while wider requests returned them. A narrow request is not a reliable
        way to ask "did anything trade today".

        ⚠ **The docs advise calling this endpoint once per session**, and the CP rate
        limit table allows 1 request per 5 seconds. Callers on a timer must not poll it
        unconditionally — `claudia/dashboard_poller.py` refetches only when the ledger's
        `realizedpnl` moves, which happens if and only if a position closed.

        ## Origin coverage — verified live 2026-07-06
        The official reference documents only "trades for the currently selected
        account"; origin scope is not stated. Verified live: once the subscription
        is primed (warmup above), mobile-placed fills DO appear — origin coverage
        is complete. The 2026-07-02 "mobile fills missing" observation was the
        unprimed first call, not an origin filter (audit Appendix B finding 2).

        ## When this is NOT the right tool
        - Full history beyond 7 days → FlexQueryClient.fetch_trades (T+1, all origins)
        - Real-time execution push → use the WebSocket `str` (trades) topic instead:
          IBKRWebSocket.subscribe_executions(realtime_updates_only, days) in streaming.py,
          which normalizes each push via _parse_stream_execution into this same trades
          table shape

        ## Two-call warmup (verified live 2026-07-06)
        A fresh brokerage session returns an EMPTY list on the first call and the
        actual fills on a follow-up call — the same subscription-instantiation
        behavior as /iserver/account/orders. An empty first response is therefore
        retried once after a 1 s pause; two empty responses mean genuinely no
        trades. (This warmup was the real cause of the 2026-07-02 'mobile fills
        missing' observation — origin coverage is complete once primed.)

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/order-monitoring/trades.md
        Endpoint: GET /iserver/account/trades
        """
        # days=7 requests maximum lookback; without it IBKR returns today's session only
        data = self._get("/iserver/account/trades?days=7")
        if isinstance(data, list) and data:
            return parse_many(Trade, data)
        time.sleep(1)  # empty first response may be the unprimed subscription
        data = self._get("/iserver/account/trades?days=7")
        return parse_many(Trade, data)

    # ------------------------------------------------------------------
    # Portfolio Analyst
    # ------------------------------------------------------------------

    def get_pa_periods(self, account_ids: list[str]) -> list[str]:
        """Available period strings for Portfolio Analyst queries.

        Verified live 2026-06-30: returns ["1D", "7D", "MTD", "1M", "YTD", "1Y"].
        The response is a dict keyed by account ID, each value containing period data
        plus a top-level "periods" key with the list of valid period strings.

        Response shape (live-verified):
          {
            "pm": "TWR", "nd": 366, ...,
            "<accountId>": {
              "1D": {"nav": [...], "cps": [...], ...},
              ...
              "periods": ["1D", "7D", "MTD", "1M", "YTD", "1Y"],
              "baseCurrency": "USD", ...
            }
          }

        The "periods" list is nested inside each account sub-dict, NOT at the top level.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/portfolio-analyst/all-periods.md
        Endpoint: POST /pa/allperiods
        """
        data = self._post("/pa/allperiods", {"acctIds": account_ids})
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            # "periods" is nested inside each account sub-dict (live-verified 2026-06-30)
            for v in data.values():
                if isinstance(v, dict):
                    periods = v.get("periods")
                    if isinstance(periods, list):
                        return periods
            # Fallback: check top-level keys (alternative response shape)
            for key in ("periods", "Period", "allPeriods", "period"):
                val = data.get(key)
                if isinstance(val, list):
                    return val
        return []

    def get_pa_periods_raw(self, account_ids: list[str]) -> Any:
        """Raw /pa/allperiods response, for diagnosing unrecognized shapes.

        get_pa_periods() extracts the period list from the documented nesting; when
        that extraction returns [], this method exposes the untouched response so the
        caller can identify the shape (used by ClaudeToolkit's get_pa_periods fallback).

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/portfolio-analyst/all-periods.md
        Endpoint: POST /pa/allperiods
        """
        return self._post("/pa/allperiods", {"acctIds": account_ids})

    def get_pa_performance(self, account_ids: list[str], period: str) -> dict[str, Any]:
        """NAV cumulative performance series for the given period.

        Valid period strings (live-verified 2026-06-30 against /pa/performance):
        "1D", "7D", "MTD", "1M", "YTD", "1Y". All return HTTP 200.
        "last7days" / "last30days" / "ytd" etc. return HTTP 400 — those strings
        are not valid for this endpoint. Use get_pa_periods() to retrieve the
        authoritative list for the account.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/portfolio-analyst/account-performance.md
        Endpoint: POST /pa/performance
        """
        return self._post("/pa/performance", {"acctIds": account_ids, "period": period})

    def get_pa_transactions(
        self,
        account_ids: list[str],
        conids: list[int],
        currency: str = "USD",
        days: int | None = None,
    ) -> list[dict[str, Any]]:
        """Transaction history from IBKR Portfolio Analyst — dividends, buys, sells, transfers.

        Covers all trade origins (CP API, mobile, TWS, web portal) — not session-scoped.
        Only one conid per call is supported (IBKR limitation per official docs).

        The response is an OBJECT — ``{"transactions": [...], "rpnl": {...}, "currency",
        "from", "to", "id", "nd"}`` — and the endpoint documents no bare-array form at all.
        Corrected 2026-09-16: this method read ``data if isinstance(data, list) else []``,
        which therefore could not match ANY response, and had returned ``[]`` for every
        account since it was written. Measured live against an account holding the queried
        contract: IBKR returned 11 transactions, this method returned 0.

        Bug fixed 2026-06-30: previous signature took `period: str` and sent it as the
        request body field "period" — both wrong. Required fields are `conids` (array of
        ints) and `currency` (string). `days` is optional (int). Old calls returned HTTP
        400 because `conids` and `currency` were missing from the request body.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/portfolio-analyst/transaction-history.md
        Endpoint: POST /pa/transactions
        """
        body: dict[str, Any] = {
            "acctIds": account_ids,
            "conids": conids,
            "currency": currency,
        }
        if days is not None:
            body["days"] = days
        data = self._post("/pa/transactions", body)
        if isinstance(data, dict):
            rows = data.get("transactions")
            return rows if isinstance(rows, list) else []
        return data if isinstance(data, list) else []

    # ------------------------------------------------------------------
    # Scanner
    # ------------------------------------------------------------------

    def get_scanner_params(self) -> dict[str, Any]:
        """Available scanner types and filter parameters.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/scanner/iserver-scanner-parameters.md
        Endpoint: GET /iserver/scanner/params
        """
        return self._get("/iserver/scanner/params")

    def run_iserver_scanner(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Run a scanner with full parameter control. Returns [] if no contracts matched.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/scanner/iserver-market-scanner.md
        Endpoint: POST /iserver/scanner/run
        """
        data = self._post("/iserver/scanner/run", params)
        contracts = data.get("contracts", data) if isinstance(data, dict) else data
        return contracts if isinstance(contracts, list) else []

    # ------------------------------------------------------------------
    # FYI / Notifications
    # ------------------------------------------------------------------

    def get_notifications(self, max_results: int = 10) -> list[Notification | dict[str, Any]]:
        """Account notifications — order fills, margin calls, system messages.

        IBKR enforces a hard cap of 10 notifications per request.
        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/fy-is-and-notifications/get-a-list-of-notifications.md
        Endpoint: GET /fyi/notifications
        """
        max_results = min(max(1, max_results), 10)
        data = self._get("/fyi/notifications", {"max": max_results})
        return parse_many(Notification, data)

    def get_unread_count(self) -> int:
        """Number of unread FYI notifications.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/fy-is-and-notifications/unread-bulletins.md
        Endpoint: GET /fyi/unreadnumber
        """
        data = self._get("/fyi/unreadnumber")
        return data.get("unreadNumber", 0) if isinstance(data, dict) else 0

    def get_delivery_options(self) -> dict[str, Any]:
        """Notification delivery channel configuration.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/fy-is-and-notifications/get-delivery-options.md
        Endpoint: GET /fyi/deliveryoptions
        """
        return self._get("/fyi/deliveryoptions")

    def get_mta_alert(self) -> MTAAlert | dict[str, Any]:
        """Mobile Trading Alerts — account-level watchdog alerts.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/alerts/get-mta-alert.md
        Endpoint: GET /iserver/account/mta
        """
        return parse_one(MTAAlert, self._get("/iserver/account/mta"))

    def get_alerts(self, account_id: str) -> list[Alert | dict[str, Any]]:
        """All price alerts configured on the account. The orderId field is the alert ID.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/alerts/get-a-list-of-available-alerts.md
        Endpoint: GET /iserver/account/{accountId}/alerts
        """
        _validate_account_id(account_id)
        return parse_many(Alert, self._get(f"/iserver/account/{account_id}/alerts"))

    # ------------------------------------------------------------------
    # Watchlists (read-only)
    # ------------------------------------------------------------------

    def get_watchlists(self) -> list[Watchlist | dict[str, Any]]:
        """All watchlists for the account, user-created first, then IB-created.

        Returns watchlist *metadata* — `id`, `name`, `read_only`, `type`. The
        constituent symbols are not in this response; fetch them per watchlist with
        `get_watchlist(id)`.

        IBKR wraps the lists in a dict — `{"data": {"user_lists": [...],
        "system_lists": [...]}, "action": ..., "MID": ...}` — and never returns a bare
        array. This method previously read `data if isinstance(data, list) else []`,
        which therefore discarded every watchlist and reported none for an account that
        had eight (found 2026-07-23 against a live gateway, fixed 2026-08-11; see
        `docs/plans/2026-07-23-get-watchlists-empty-bug.md`). The bare-list branch is
        kept only as tolerance for a shape IBKR has never actually sent.

        `system_lists` are included because the caller asked for *all* watchlists;
        IBKR's own `read_only: true` marks them, so no synthetic tagging is added.

        Source: https://www.interactivebrokers.com/docs/web-api/v1/endpoints/watchlists/get-all-watchlists
        Endpoint: GET /iserver/watchlists
        """
        data = self._get("/iserver/watchlists", {"SC": "USER_WATCHLIST"})
        if isinstance(data, list):
            return parse_many(Watchlist, [w for w in data if isinstance(w, dict)])
        if not isinstance(data, dict):
            return []
        payload = data.get("data")
        if not isinstance(payload, dict):
            return []
        watchlists: list[dict[str, Any]] = []
        for key in ("user_lists", "system_lists"):
            entries = payload.get(key)
            if isinstance(entries, list):
                watchlists.extend(w for w in entries if isinstance(w, dict))
        return parse_many(Watchlist, watchlists)

    def get_watchlist(self, watchlist_id: str) -> WatchlistDetail | dict[str, Any]:
        """Contents of a specific watchlist. Uses the watchlist ID as a query param.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/watchlists/get-watchlist-information.md
        Endpoint: GET /iserver/watchlist
        """
        return parse_one(WatchlistDetail, self._get("/iserver/watchlist", {"id": watchlist_id}))

    # ------------------------------------------------------------------
    # Event Contracts (read-only)
    #
    # IBKR markets these as "Event Contracts" (ForecastEx and CME event/forecast
    # contracts, modelled on options) and serves them under `/forecast/*`. This package
    # called `/events/contracts` and `/events/show` until 2026-09-17 — paths that appear
    # **zero times** in IBKR's complete documentation index and have never worked for
    # anyone. Those two methods were removed, not repaired (audit finding API-R4); the
    # precedent is `get_regulatory_snapshot`, deleted in `6a50f06` when its endpoint went.
    #
    # **These five are documentation-verified and NOT wire-verified.** Every path, query
    # parameter and requiredness below was read from IBKR's own API-reference page for the
    # endpoint (each cited per method, retrieved 2026-09-17 with a fabricated control URL
    # in the same batch to prove the check could fail). None has been executed against a
    # live gateway, because event contracts need a subscription this account does not hold.
    # The owner's position (2026-09-17): a subscription may be opened later for development
    # purposes, it is **not a priority**, and until then these are **expressly not validated**
    # — a decision on record, not a gap. `tests/test_client_event_contracts.py` holds that
    # state and fails the day a captured response appears, which is the day to type them.
    # That is why **none of them returns a model**: this package's rule is that a model is
    # validated against a captured response, never against a reading of the documentation
    # (`models.py`, and the six models that were wrong for the package's life). They return
    # the decoded response and say so. `tests/test_client_event_contracts.py` pins the
    # request each one builds — which is knowable — and asserts nothing about the response.
    # ------------------------------------------------------------------

    def get_forecast_categories(self) -> Any:
        """Event Contract category tree: category ids, parent ids and markets.

        Takes no parameters. Use the ids it returns for the more granular discovery calls.

        Documented errors: 401, 500, 503 — **no 404**, which is worth knowing because an
        unentitled account is reported some other way (API-R4).

        Source: https://ibkrcampus.com/docs/web-api/api-reference/trading/trading-event-contracts/get-forecast-categories.md
        Endpoint: GET /forecast/category/tree
        """
        return self._get("/forecast/category/tree")

    def get_forecast_contract(self, conid: int | str) -> Any:
        """Instrument details for one event contract, including its Yes and No sides.

        IBKR documents `conid` as a **string** query parameter; it is accepted here as
        either and validated as numeric, matching every other conid in this file.

        Args:
            conid: The event contract's identifier.

        Source: https://ibkrcampus.com/docs/web-api/api-reference/trading/trading-event-contracts/get-forecast-contract.md
        Endpoint: GET /forecast/contract/details
        """
        _validate_conid(conid)
        return self._get("/forecast/contract/details", {"conid": conid})

    def get_forecast_market(self, underlying_conid: int | str, exchange: str | None = None) -> Any:
        """Every contract affiliated with one underlying market conid.

        Args:
            underlying_conid: The market's underlying contract identifier (IBKR's
                `underlyingConid`, documented required).
            exchange: Optional exchange; IBKR determines one internally when omitted.

        Source: https://ibkrcampus.com/docs/web-api/api-reference/trading/trading-event-contracts/get-forecast-markets.md
        Endpoint: GET /forecast/contract/market
        """
        _validate_conid(underlying_conid)
        params: dict[str, Any] = {"underlyingConid": underlying_conid}
        if exchange:
            params["exchange"] = exchange
        return self._get("/forecast/contract/market", params)

    def get_forecast_rules(self, conid: int | str) -> Any:
        """Trading rules for one event contract: payout, price increment, source agency.

        Args:
            conid: The event contract's identifier.

        Source: https://ibkrcampus.com/docs/web-api/api-reference/trading/trading-event-contracts/get-forecast-rules.md
        Endpoint: GET /forecast/contract/rules
        """
        _validate_conid(conid)
        return self._get("/forecast/contract/rules", {"conid": conid})

    def get_forecast_schedules(self, conid: int | str) -> Any:
        """Liquid and extended trading hours for one event contract, by date.

        Args:
            conid: The event contract's identifier.

        Source: https://ibkrcampus.com/docs/web-api/api-reference/trading/trading-event-contracts/get-forecast-schedule.md
        Endpoint: GET /forecast/contract/schedules
        """
        _validate_conid(conid)
        return self._get("/forecast/contract/schedules", {"conid": conid})

    # ------------------------------------------------------------------
    # Order Management (write — human auth required)
    # ------------------------------------------------------------------

    def place_order(
        self,
        account_id: str,
        order: dict[str, Any],
        *,
        authorization: OrderWriteAuthorization | None = None,
    ) -> list[dict[str, Any]]:
        """Place a new order. Requires Touch ID (Gate 1) + tkinter confirmation dialog (Gate 2).

        `authorization` (2026-09-11): the value `place_order_and_confirm` earned for this exact
        account and body. When it covers both, Gate 1 is not repeated; Gate 2 always runs. Called
        directly with none — the documented single-shot use — it prompts as it always has.

        Both security gates fire before the order is sent. HumanAuthError is raised if
        either gate fails or times out. The one request that may precede them is the
        session's first `GET /iserver/accounts` (see this module's docstring); no write does. ClaudIA constraint: ClaudeToolkit exposes no tool calling
        this method — order execution is UI-layer only, triggered by physical button click.

        ## GTC orders are not indefinite (verified live 2026-07-06, IBKR convention)
        A GTC order auto-cancels at the end of the calendar quarter *following* the
        current one — not simply "year-end." Placed in Q3 -> cancels end of Q4;
        placed in Q1 -> cancels end of Q2. Confirmed live: an order placed 2026-07-06
        (Q3) returned a final reply message "will be automatically canceled at
        20261231 16:00:00 EST" (end of Q4), matching the rule exactly. This is a
        normal IBKR lifecycle behavior, not a bug — the reply chain (see below)
        surfaces the exact cancellation timestamp for each GTC order placed.
        Source: https://www.interactivebrokers.com/campus/trading-lessons/mosaic-good-till-cancelled-gtc-order-type/

        ## Order confirmation may require multiple chained replies (verified live 2026-07-06)
        place_order's response can include an {"id", "message", "messageIds", ...} entry
        requiring reply_order(id). CRITICALLY, reply_order's own response can ALSO
        return another such entry — confirmed live: a single AAPL limit order required
        THREE sequential replies (price-band %, no-market-data, mandatory-cap-price)
        before returning a terminal {"order_status": "Submitted", ...}. Callers must
        loop reply_order() until a response with no "id"/"message" is returned.
        Official docs warn the reply must be answered immediately — other requests in
        between risk invalidating it (503 on the next reply attempt). See CLAUDE.md's
        Order Management section and the audit report for the live-verified pattern.

        US Futures and Futures Options (FUT/FOP): caller must include manualIndicator=True
        in the order dict, for CME Group Rule 536-B compliance (required since May 1, 2025).
        order_flow.py adds it automatically when sec_type is "FUT" or "FOP".

        Do NOT send extOperator. The docs list it beside manualIndicator, but IBKR rejects
        any non-empty value on this account class as undocumented field 8089 (whatif
        isolation 2026-07-23; re-confirmed live 2026-09-20 on ES Dec-26, where two whatifs
        differing only in this field returned a full margin impact without it and
        HTTP 500 {"error":"Can not contain field # 8089"} with it). manualIndicator alone
        is accepted — this docstring previously claimed HTTP 400 without both, which the
        measurement contradicts.
        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/web-api-changelog/
                https://ibkrcampus.com/docs/web-api/v1/endpoints/orders/place-order.md

        Returns whatever IBKR sent, always as a list. The endpoint publishes THREE shapes:
        the normal array, the Alternate (reply-required) array, and a bare object
        ``{"error": "We cannot accept an order at the limit price you selected..."}``. Until
        2026-09-16 the body was read as a list, so that rejection became ``[]`` — an order
        IBKR refused for a stated reason, reported to the caller as an empty response with
        IBKR's own words discarded. ``_as_reply_list`` wraps the object into a one-element
        list; it already existed, but was applied only by ``place_order_and_confirm``, one
        layer too far out to save the dict.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/orders/place-order.md
                https://www.interactivebrokers.com/campus/trading-lessons/request-modify-orders/
        Endpoint: POST /iserver/account/{accountId}/orders
        """
        _validate_account_id(account_id)
        self._ensure_accounts_initialized()
        # The body the dialog shows is the body that is sent: a private copy, so a caller
        # mutating its dict between the dialog and the POST changes nothing here (audit
        # 2026-09-13, B9; noted and dropped as unreachable 2026-07-11).
        order = dict(order)
        # Gate 1. A chain started by place_order_and_confirm already earned an
        # authorization for exactly this account and body; anything else — a direct call, an expired
        # window, a body that no longer matches — prompts. Fails closed. (2026-09-11)
        scope = _order_write_scope("place", account_id, order)
        if authorization is None or not authorization.covers(scope):
            require_touch_id(f"place an IBKR order — {_order_label(order)}")
        else:
            log.info("Gate 1: place covered by authorization %s", scope)
        confirm_order_dialog(order, account_id)
        # Strip display-only fields (underscore-prefixed, e.g. _companyName).
        # These carry Gate-2 dialog metadata and are not valid IBKR request fields.
        # Note: ticker IS a valid IBKR field (optional) and is NOT stripped.
        # manualIndicator is FUT/FOP only (CME Rule 536-B) — caller adds it for futures;
        # omit here to avoid type-rejection on equity orders. extOperator is NOT sent at
        # all: IBKR rejects any non-empty value as field 8089 (see place_order's docstring).
        # Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/orders/place-order.md
        api_order = {k: v for k, v in order.items() if not k.startswith("_")}
        data = self._post(f"/iserver/account/{account_id}/orders", {"orders": [api_order]})
        # IBKR's documented rejection is a bare OBJECT — `{"error": "We cannot accept an
        # order at the limit price you selected..."}` (place-order.md, under Alternate
        # Response Object, alongside the two array shapes). Reading the body as a list
        # discarded it and handed the caller `[]`, which is what "nothing happened" looks
        # like too. `_as_reply_list` is the existing one-element-list wrapper; it was only
        # ever applied by `place_order_and_confirm`, one layer too late to save the dict.
        return _as_reply_list(data)

    def modify_order(
        self,
        account_id: str,
        order_id: str,
        order: dict[str, Any],
        *,
        authorization: OrderWriteAuthorization | None = None,
    ) -> dict[str, Any]:
        """Modify an existing order. Requires Touch ID (Gate 1) + tkinter dialog (Gate 2).

        `authorization` (2026-09-11): the value `modify_order_and_confirm` earned for this
        exact replacement body and order id. When it covers them, Gate 1 is not repeated;
        Gate 2 always runs. Called directly with none, it prompts as it always has.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/orders/modify-order.md
                https://www.interactivebrokers.com/campus/trading-lessons/request-modify-orders/
        Endpoint: POST /iserver/account/{accountId}/order/{orderId}
        """
        _validate_account_id(account_id)
        _validate_order_id(order_id)
        self._ensure_accounts_initialized()
        order = dict(order)  # the body shown is the body sent — see place_order
        # Gate 1 — the same rule as place_order: covered by the chain's authorization for
        # exactly this account, body and order id, or prompt. Fails closed. (2026-09-11)
        scope = _order_write_scope("modify", account_id, order, order_id=order_id)
        if authorization is None or not authorization.covers(scope):
            require_touch_id(f"modify IBKR order {order_id}")
        else:
            log.info("Gate 1: modify covered by authorization %s", scope)
        confirm_modify_dialog(order_id, order, account_id)
        # Display-only `_`-prefixed keys (the futures label, multiplier, currency,
        # `_changes`, `_current_description`) never reach IBKR — the same convention as
        # place_order, applied here since 2026-09-10.
        api_order = {k: v for k, v in order.items() if not k.startswith("_")}
        return self._post(f"/iserver/account/{account_id}/order/{order_id}", api_order)

    def cancel_order(
        self, account_id: str, order_id: str, order_details: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Cancel an order. Requires Touch ID (Gate 1) + tkinter confirmation dialog (Gate 2).

        `order_details` is optional display-only info (symbol/side/qty/price/TIF/etc.) shown
        in the Gate 2 dialog so the human can verify the right order before cancelling —
        mirrors modify_order()'s dialog, which already receives the full order dict. Found
        missing live 2026-07-10 — user-flagged hard requirement.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/orders/cancel-order.md
                https://www.interactivebrokers.com/campus/trading-lessons/request-modify-orders/
        Endpoint: DELETE /iserver/account/{accountId}/order/{orderId}
        """
        _validate_account_id(account_id)
        _validate_order_id(order_id)
        self._ensure_accounts_initialized()
        require_touch_id(f"cancel IBKR order {order_id}")
        # Cancel is a single write with no reply chain, so no authorization value — but
        # the log must still witness the fingerprint (2026-09-11: 8 of 12 prompts logged).
        log.info("Gate 1: granted for cancel:%s", order_id)
        confirm_cancel_dialog(order_id, account_id, order_details)
        path = f"/iserver/account/{account_id}/order/{order_id}"
        url = f"{self._base}{path}"
        resp = with_retry(lambda: self._session.delete(url, timeout=30), path=path)
        return _decode(resp, path)

    def reply_order(self, reply_id: str, ibkr_confirmed: bool = True) -> list[dict[str, Any]]:
        """Confirm an order requiring an explicit IBKR reply (e.g. after a warning).

        Requires Touch ID (Gate 1) + tkinter dialog (Gate 2).

        ## May need to be called in a loop (verified live 2026-07-06)
        This reply's own response can contain ANOTHER {"id", "message", ...} entry
        requiring a further reply_order() call — confirmed live, a single order
        needed 3 sequential replies before a terminal response. Callers must loop
        until the response has no "id"/"message" pair. Official docs: "Orders must
        be replied to immediately after receiving the reply message. Submitting
        other orders or other requests will cancel the order and attempts to
        acknowledge the reply will result in a 503 error" — so this loop must run
        back-to-back with no unrelated requests interleaved. `message` is the exact
        text IBKR wants the human to read before confirming; the caller (Gate 2
        dialog) must display it, not just the reply_id.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/orders/place-order-reply-confirmation.md
                https://www.interactivebrokers.com/campus/trading-lessons/request-modify-orders/
        Endpoint: POST /iserver/reply/{replyId}
        """
        _validate_reply_id(reply_id)
        self._ensure_accounts_initialized()
        require_touch_id(f"confirm an IBKR order reply {reply_id}")
        confirm_reply_dialog(reply_id)
        data = self._post(f"/iserver/reply/{reply_id}", {"confirmed": ibkr_confirmed})
        return data if isinstance(data, list) else []

    def _resolve_one_reply(
        self,
        entry: dict[str, Any],
        reply_log: list[dict[str, Any]] | None = None,
        *,
        authorization: OrderWriteAuthorization | None = None,
        scope: str | None = None,
    ) -> Any:
        """Run Gate 2 — and Gate 1 unless the chain's authorization covers it — for one
        reply-chain entry, then tell IBKR the outcome.

        `entry` is a single {"id", "message", "messageOptions"?, ...} dict — the first
        (and only) element of a /iserver/reply/{replyId}-shaped response, or the bare
        dict modify_order() returns. Extracts reply_id/message/options itself so
        place_order_and_confirm() and modify_order_and_confirm() don't duplicate that
        extraction — the two gates and the confirm/decline POST are identical
        regardless of which endpoint started the chain. Returns the raw parsed JSON
        from the confirmation POST (caller normalizes list vs. dict per its own
        return-type contract via _as_reply_list()/_as_reply_dict()).

        On decline (HumanAuthError from confirm_reply_dialog), POSTs
        {"confirmed": False} to IBKR *before* re-raising — unlike the standalone
        reply_order(), which raises without ever contacting IBKR and leaves the
        order ambiguous on IBKR's side. This is a deliberate behavior change, not
        a bug: see docs/plans/archive/security-orders/2026-07-06-order-reply-confirmation-design.md.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/orders/place-order-reply-confirmation.md
        Endpoint: POST /iserver/reply/{replyId}

        `authorization` / `scope` (2026-09-11): the chain's authorization and the scope it was
        granted for. A reply covered by them validates through its dialog alone — the user's
        rule, matching IBKR Mobile and TWS; the dialog's title then names the order. Without
        them the reply prompts, exactly as `reply_order()` always has.

        `reply_log`, when given, receives one record per reply: `reply_id`, the raw
        `message`, `message_text` (tags stripped, entities unescaped), `message_options`,
        `confirmed` and a UTC `at` stamp. The record is appended BEFORE the gates with
        `confirmed: False` and flipped to True only once the human has confirmed, so a
        Touch ID failure or a decline leaves an honest record. claudia_ui gap #38
        (2026-09-10): two human-confirmed IBKR precautions had left no trace anywhere.
        """
        reply_id = entry["id"]
        # Invariant 9: this URL is built here as well as in `reply_order`, and only that
        # one validated (audit finding SEC-03). The same strict regex is used in both, now
        # that it rests on measurement rather than on IBKR's example — see `_REPLY_ID_RE`.
        _validate_reply_id(reply_id)
        message = " ".join(entry.get("message", []))
        options = entry.get("messageOptions")
        record: dict[str, Any] = {
            "reply_id": reply_id,
            "message": message,
            "message_text": reply_message_text(message),
            "message_options": options,
            "confirmed": False,
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        if reply_log is not None:
            reply_log.append(record)
        # Gate 1 for a reply: the same check the write ran, with the scope the chain
        # computed from the body it sent. No authorization, no scope, expired, or for
        # another write — prompt. Never a silent pass on presence alone. (2026-09-11)
        if authorization is None or scope is None or not authorization.covers(scope):
            require_touch_id(f"confirm an IBKR order reply {reply_id}")
        else:
            log.info("Gate 1: reply %s covered by authorization %s", reply_id, scope)
        try:
            # The unauthorised path keeps its call exactly as before — no label to show.
            reply_kwargs = {"order_label": authorization.label} if authorization is not None else {}
            confirm_reply_dialog(reply_id, message, options, **reply_kwargs)
        except HumanAuthError:
            self._post(f"/iserver/reply/{reply_id}", {"confirmed": False})
            raise HumanAuthError("User declined IBKR order reply") from None
        record["confirmed"] = True
        return self._post(f"/iserver/reply/{reply_id}", {"confirmed": True})

    def place_order_and_confirm(
        self,
        account_id: str,
        order: dict[str, Any],
        *,
        reply_log: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Place an order and resolve its full reply chain, looping until a terminal response.

        One Touch ID for the whole chain (2026-09-11): Gate 1 runs here, once, bound to this
        body and to 300 s; the write and every precaution reply verify that same
        authorization and keep their dialogs. IBKR Mobile and TWS ask once per placement;
        so does this.

        Calls the existing place_order() for the initial submission — Gate 1 + Gate 2
        already run correctly there and are unchanged. If IBKR's response requires a
        reply (an {"id", "message", ...} entry — verified live 2026-07-06, a single
        AAPL limit order needed THREE sequential replies: price-band %, no-market-data,
        mandatory-cap-price, before a terminal {"order_status": "Submitted", ...}), this
        method automatically loops Gate 1 + Gate 2 + the confirm POST for each reply in
        the chain, showing the human the *actual* IBKR warning text at every step
        (see confirm_reply_dialog()'s `message` parameter) rather than just a reply_id.

        Runs the loop body back-to-back with no unrelated requests interleaved — IBKR's
        docs warn that a reply left pending while other requests are made will 503 on
        the next reply attempt. If the human declines any reply in the chain,
        HumanAuthError is raised (see _resolve_one_reply() for the decline-then-POST
        semantics, a deliberate change from reply_order()'s behavior).

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/orders/place-order.md
                https://ibkrcampus.com/docs/web-api/v1/endpoints/orders/place-order-reply-confirmation.md
        Endpoint: POST /iserver/account/{accountId}/orders, then POST /iserver/reply/{replyId}*

        `reply_log` collects one record per resolved reply (see _resolve_one_reply); the
        return value stays the terminal response.
        """
        scope = _order_write_scope("place", account_id, order)
        label = _order_label(order)
        authorization = _authorize_order_write(f"place an IBKR order — {label}", scope, label)
        log.info("Gate 1: granted for %s (%s)", scope, label)
        response = _as_reply_list(self.place_order(account_id, order, authorization=authorization))
        while response and "id" in response[0]:
            response = _as_reply_list(
                self._resolve_one_reply(response[0], reply_log, authorization=authorization, scope=scope)
            )
        return response

    def modify_order_and_confirm(
        self,
        account_id: str,
        order_id: str,
        order: dict[str, Any],
        *,
        reply_log: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Modify an order and resolve its full reply chain, looping until a terminal response.

        One Touch ID for the whole chain (2026-09-11): modify is its own transaction and
        keeps its own Gate 1 — run here, once, bound to this account, replacement body and order id
        and to 300 s — and its precaution replies verify that same authorization behind
        their dialogs. IBKR Mobile and TWS ask once per modification; so does this.

        Same loop/display/decline semantics as place_order_and_confirm() — see that
        method's docstring — applied to modify_order() instead of place_order(). IBKR's
        reply-chain shape for modify is documented as the same {"id", "message", ...}
        pattern as place_order's chain (per the CP API reply docs cited on
        reply_order()). Note: modify_order()'s own return type is a single dict (not a
        list), so this method checks for "id"/"message" directly on that dict.

        This method was added proactively — it has the identical never-loops-replies
        gap that place_order() had before place_order_and_confirm() was added — but
        that gap has NOT been verified live for modify_order specifically (no live
        modify test has been run as of 2026-07-06; only the place_order 3-reply chain
        is live-verified, see place_order_and_confirm()'s docstring).

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/orders/modify-order.md
                https://ibkrcampus.com/docs/web-api/v1/endpoints/orders/place-order-reply-confirmation.md
        Endpoint: POST /iserver/account/{accountId}/order/{orderId}, then POST /iserver/reply/{replyId}*

        `reply_log` collects one record per resolved reply (see _resolve_one_reply); the
        return value stays the terminal response.
        """
        scope = _order_write_scope("modify", account_id, order, order_id=order_id)
        label = f"{_order_label(order)} (order {order_id})"
        authorization = _authorize_order_write(f"modify IBKR order {order_id}", scope, label)
        log.info("Gate 1: granted for %s (%s)", scope, label)
        response = self.modify_order(account_id, order_id, order, authorization=authorization)
        while "id" in response:
            response = _as_reply_dict(
                self._resolve_one_reply(response, reply_log, authorization=authorization, scope=scope)
            )
        return response

    def _whatif(self, account_id: str, orders: list[dict[str, Any]]) -> dict[str, Any]:
        """The ONE place that builds the whatif path. Read-only, no security gates.

        Both preview entry points come through here — a single ticket and a bracket array —
        so the `/orders/whatif` literal is written once. The risk this guards is not a method
        previewing too much, it is a second method spelling the path for itself and one day
        dropping `/whatif`: that copy-paste was lint-clean and fully typed on 2026-09-13
        (docs/audits/security-architecture-audit-2026-09-13.md, B2). Pinned by
        `tests/security/test_preview_is_not_execution.py`, which asserts this is the only
        function in `client.py` building it.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/orders/preview-order-what-if-order.md
        Endpoint: POST /iserver/account/{accountId}/orders/whatif
        """
        _validate_account_id(account_id)
        self._ensure_accounts_initialized()
        return self._post(f"/iserver/account/{account_id}/orders/whatif", {"orders": orders})

    def get_order_preview(self, account_id: str, order: dict[str, Any]) -> dict[str, Any]:
        """Whatif order preview — cost, commission, margin impact. Read-only, no security gates.

        One ticket. A bracket cannot come through here — it is one request carrying an array,
        so it has its own entry point (`get_bracket_preview`); both post through `_whatif`.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/orders/preview-order-what-if-order.md
        Endpoint: POST /iserver/account/{accountId}/orders/whatif
        """
        # Strip display-only fields (underscore-prefixed) — same convention as place_order.
        # Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/orders/place-order.md
        api_order = {k: v for k, v in dict(order).items() if not k.startswith("_")}
        return self._whatif(account_id, [api_order])

    def _bracket_tickets(self, parent: dict[str, Any], children: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Validate the parent→child link and strip display fields.

        `cOID` on the parent, `parentId == cOID` on every child, no `cOID` on a child — IBKR's
        stated rules for a bracket ticket array. Refusing an unlinked pair is the point: two
        tickets that are not linked are two INDEPENDENT live orders, and a standalone
        opposite-side order can open the wrong position rather than close one.

        Source: https://ibkrcampus.com/docs/web-api/api-reference/trading/trading-orders/submit-new-order.md
        """
        ref = parent.get("cOID")
        if not ref or not children:
            raise ValueError("A bracket needs a parent cOID and at least one child")
        for kid in children:
            if kid.get("parentId") != ref or kid.get("cOID"):
                raise ValueError("Each bracket child must carry parentId == the parent's cOID and no cOID")
        return [{k: v for k, v in t.items() if not k.startswith("_")} for t in (parent, *children)]

    def get_bracket_preview(
        self, account_id: str, parent: dict[str, Any], children: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Whatif for a bracket — the endpoint previews "an order ticket or bracket of orders".

        Read-only, no gates, like `get_order_preview`. Both legs are sent, because a preview of
        the parent alone prices something the user is not about to submit.

        Source: https://ibkrcampus.com/docs/web-api/api-reference/trading/trading-orders/preview-margin-impact.md
        Endpoint: POST /iserver/account/{accountId}/orders/whatif
        """
        return self._whatif(account_id, self._bracket_tickets(parent, children))

    # ------------------------------------------------------------------
    # Alerts (write)
    # ------------------------------------------------------------------

    def get_alert(self, alert_id: str) -> dict[str, Any]:
        """Full details for a specific alert by ID. Not account-scoped in the URL
        (same pattern as get_order_status) — IBKR resolves the alert from the
        session's logged-in account.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/alerts/get-details-of-a-specific-alert.md
        Endpoint: GET /iserver/account/alert/{order_id}?type=Q
        """
        _validate_order_id(alert_id)
        return self._get(f"/iserver/account/alert/{alert_id}", params={"type": "Q"})

    def create_alert(self, account_id: str, alert: dict[str, Any]) -> dict[str, Any]:
        """Create a price alert. The alert dict must match the IBKR alert payload schema.

        Use ClaudeToolkit.execute("create_price_alert", ...) instead — it resolves
        conid and exchange automatically.

        `orderId` distinguishes create from modify: omitted or 0 creates, an existing alert
        id modifies that alert ("optional; used in case of modification and represent Alert
        Id"). `conditions[].operator` is an enum of `>=`, `<=`, `>`, `<`, `==` — but see
        `docs/ibkr-api-behaviors-reference.md`: a body containing `>=` or `<=` is rejected
        before it reaches IBKR with an opaque HTML `403 Access Denied`, and **none of the five can
        create an alert through the gateway**: `>=` and `<=` never arrive, while `>`, `<` and
        `==` arrive and are refused by IBKR's own engine,
        `{"error":"Condition #1:can't recognize fix [>]"}` (measured 2026-09-16).

        This said "only `>`, `<` and `==` are usable through the gateway" until 2026-09-16.
        They are not usable; they are merely *not blocked by the 403 filter*, which is a
        different claim and sends a reader down a dead end.

        The citation below is NOT the `v1/endpoints/alerts/` page the rest of this section
        uses — that page (`create-or-modify-alert.md`) returns "# Page Not Found", and no
        page under `v1/endpoints/` declares this endpoint. The real one lives under
        `api-reference/trading/trading-alerts/` and is **absent from `llms.txt`**, which is
        why the index could not find it; `firecrawl_search` did, exactly as CLAUDE.md says
        it should when the index is silent.

        Source: https://www.interactivebrokers.com/docs/web-api/api-reference/trading/trading-alerts/create-alert.md
                (verified 2026-09-16, 28,219 B, with a fabricated control URL in the same batch)
        Endpoint: POST /iserver/account/{accountId}/alert
        """
        _validate_account_id(account_id)
        return self._post(f"/iserver/account/{account_id}/alert", alert)

    def delete_alert(self, account_id: str, alert_id: str) -> dict[str, Any]:
        """Delete an alert permanently.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/alerts/delete-an-alert.md
        Endpoint: DELETE /iserver/account/{accountId}/alert/{alertId}
        """
        _validate_account_id(account_id)
        _validate_order_id(alert_id)
        path = f"/iserver/account/{account_id}/alert/{alert_id}"
        url = f"{self._base}{path}"
        resp = with_retry(lambda: self._session.delete(url, timeout=30), path=path)
        return _decode(resp, path)

    def activate_alert(self, account_id: str, alert_id: str, activate: bool = True) -> dict[str, Any]:
        """Toggle alert on (activate=True) or off (activate=False) without deleting it.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/alerts/activate-or-deactivate-an-alert.md
        Endpoint: POST /iserver/account/{accountId}/alert/activate
        """
        _validate_account_id(account_id)
        _validate_order_id(alert_id)
        return self._post(
            f"/iserver/account/{account_id}/alert/activate", {"alertId": alert_id, "alertActive": int(activate)}
        )

    # ------------------------------------------------------------------
    # Watchlists (write)
    # ------------------------------------------------------------------

    def create_watchlist(self, name: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
        """Create a new watchlist. rows is a list of {"C": conid} objects.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/watchlists/create-a-watchlist.md
        Endpoint: POST /iserver/watchlist
        """
        return self._post("/iserver/watchlist", {"id": name, "name": name, "rows": rows})

    def delete_watchlist(self, watchlist_id: str) -> dict[str, Any]:
        """Delete a watchlist permanently. watchlist_id is passed as query param `id`.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/watchlists/delete-a-watchlist.md
        Endpoint: DELETE /iserver/watchlist
        """
        url = f"{self._base}/iserver/watchlist"
        resp = with_retry(
            lambda: self._session.delete(url, params={"id": watchlist_id}, timeout=30),
            path="/iserver/watchlist",
        )
        return _decode(resp, "/iserver/watchlist")

    # ------------------------------------------------------------------
    # FYI (write)
    # ------------------------------------------------------------------

    def mark_notification_read(self, notification_id: str) -> dict[str, Any]:
        """Mark a FYI notification as read.

        **Corrected 2026-09-16 (audit finding API-20).** This sent
        `POST /fyi/notifications/{id}/read` — a verb and a path IBKR publishes nowhere.
        Both of IBKR's documentation families independently document
        `PUT /fyi/notifications/{notificationId}` with an empty JSON body, including the
        page this docstring already cited.

        The live test meant to cover it accepted a successful result, HTTP 400, HTTP 404
        **and** HTTP 423 — every outcome the call can produce — so it passed whether or not
        the endpoint existed.

        `notification_id` is numeric: the endpoint's own 400 reads "Missing, empty,
        **non-numeric**, or out-of-range parameter".

        Returns {"V": 1, "T": <ms>} — V acknowledges the edit, T is how long it took.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/fy-is-and-notifications/mark-notification-read.md
                https://www.interactivebrokers.com/docs/web-api/api-reference/trading/trading-fy-is-and-notifications/read-fyi-notification.md
        Endpoint: PUT /fyi/notifications/{notificationId}
        """
        _validate_notification_id(notification_id)
        return self._put(f"/fyi/notifications/{notification_id}")

    def update_delivery_option(
        self,
        device_id: str | None,
        option: str,
        enabled: bool,
        device_name: str = "",
        ui_name: str = "",
    ) -> dict[str, Any]:
        """Enable or disable a notification delivery channel.

        **Corrected 2026-09-16 (audit finding API-21).** This built
        `POST /fyi/deliveryoptions/{option}` with `{"deviceId", "enabled"}` for any
        `option`. IBKR publishes two delivery endpoints, and they agree on neither the
        verb nor how parameters are passed, so one parameterised path could not serve
        both:

        | option | Method | Path | Parameters |
        |---|---|---|---|
        | `device` | POST | /fyi/deliveryoptions/device | JSON body: deviceName, deviceId, uiName, enabled |
        | `email` | PUT | /fyi/deliveryoptions/email | query: enabled=true / false |

        So the `device` call sent 2 of the 4 documented fields — the same defect shape as
        the alert-modify body — and the `email` call was wrong in both verb and parameter
        style and could not have worked. `option` is now checked against the two
        documented values rather than interpolated as given (audit finding SEC-03).

        The two documentation families disagree on whether the `device` body fields are
        required: `v1/endpoints` marks all four Required, `api-reference` marks them
        optional. All four are sent, which satisfies either reading. `device_name` and
        `ui_name` default to `device_id` when not given, matching IBKR's own example,
        where all three carry the same APN token.

        Args:
            device_id: The device's ID code. Ignored for `option="email"`.
            option: "device" or "email".
            enabled: Whether the channel should receive notifications.
            device_name: Human-readable device name; defaults to `device_id`.
            ui_name: Interface title; defaults to `device_id`.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/fy-is-and-notifications/enable-disable-device-option.md
                https://ibkrcampus.com/docs/web-api/v1/endpoints/fy-is-and-notifications/enable-disable-email-option.md
        Endpoint: POST /fyi/deliveryoptions/device | PUT /fyi/deliveryoptions/email
        """
        _validate_delivery_option(option)
        if option == "email":
            # The flag is a query parameter here, and lowercase text — not a JSON bool.
            return self._put("/fyi/deliveryoptions/email", {"enabled": "true" if enabled else "false"})
        if not device_id:
            raise ConfigError("update_delivery_option(option='device') requires a device_id.")
        return self._post(
            "/fyi/deliveryoptions/device",
            {
                "deviceName": device_name or device_id,
                "deviceId": device_id,
                "uiName": ui_name or device_id,
                "enabled": enabled,
            },
        )

    # ------------------------------------------------------------------
    # Account / Admin
    # ------------------------------------------------------------------

    def get_brokerage_accounts(self) -> BrokerageSession | dict[str, Any]:
        """List of accounts the user has trading access to, their aliases, the currently
        selected account, and per-account capability flags (supportsCashQty,
        supportsFractions, allowCustomerTime, etc).

        Per official docs, this endpoint must be called before modifying an order or
        querying open orders. _ensure_accounts_initialized() calls this once per
        IBKRClient instance and caches the result; every order read/write method calls
        it first, so callers never need to call this directly under normal use.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/accounts/receive-brokerage-accounts.md
        Endpoint: GET /iserver/accounts
        """
        return parse_one(BrokerageSession, self._get("/iserver/accounts"))

    def _ensure_accounts_initialized(self) -> None:
        """Calls get_brokerage_accounts() once per session, satisfying the documented
        prerequisite before order writes/reads. Cached on self._accounts_initialized —
        cheap to call at the top of every order-related method.
        """
        if not self._accounts_initialized:
            self.get_brokerage_accounts()
            self._accounts_initialized = True

    def switch_account(self, account_id: str) -> dict[str, Any]:
        """Switch the active account. For advisors and family accounts.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/accounts/switch-account.md
        Endpoint: POST /iserver/account
        """
        _validate_account_id(account_id)
        return self._post("/iserver/account", {"acctId": account_id})

    def get_pnl(self) -> dict[str, Any]:
        """Real-time partitioned P&L — daily, unrealized, realized — across all positions.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/accounts/account-profit-and-loss.md
        Endpoint: GET /iserver/account/pnl/partitioned
        """
        return self._get("/iserver/account/pnl/partitioned")

    def logout(self) -> dict[str, Any]:
        """End the current IBKR session.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/session/logout-of-the-current-session.md
        Endpoint: POST /logout
        """
        return self._post("/logout")
