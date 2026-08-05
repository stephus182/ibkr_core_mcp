"""IBKRClient — the complete IBKR Client Portal Web API surface (74 endpoints).

Wraps market data, contracts, portfolio, orders, alerts, watchlists, and session
management, returning typed models from `models.py` where the shape is stable.
Rate limiting and 429/503 backoff are handled transparently by `rate_limiter.py`.

**Security invariant.** Every order write method — `place_order`, `modify_order`,
`cancel_order`, `reply_order`, and the `*_and_confirm` variants — runs two
sequential human gates (Touch ID, then a visual confirmation dialog) *before* any
network call reaches IBKR. The gates are enforced here, at the innermost call site,
precisely so that no caller can route around them; they must never be moved
outward, cached, or made bypassable. Read-only methods (`get_order_preview`, the
order-status readers, alert management) are deliberately ungated. See the Security
section of `CLAUDE.md` before touching any of this.

Endpoint reference: https://www.interactivebrokers.com/docs/web-api/
"""

from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import urlparse

import requests
import urllib3

from ibkr_core_mcp.auth import AuthStrategy, BrowserCookieAuth
from ibkr_core_mcp.config import Config
from ibkr_core_mcp.exceptions import ConfigError, HumanAuthError, IBKRAPIError
from ibkr_core_mcp.human_auth import require_touch_id
from ibkr_core_mcp.order_confirm import (
    confirm_cancel_dialog,
    confirm_modify_dialog,
    confirm_order_dialog,
    confirm_reply_dialog,
)
from ibkr_core_mcp.rate_limiter import with_retry

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Account IDs are uppercase alphanumeric, 4–12 chars (e.g. "U1234567", "DU12345").
# This prevents path traversal in URLs and matches the claude_tools validator.
_ACCOUNT_ID_RE = re.compile(r"^[A-Z0-9]{4,12}$")

# IBKR order/alert IDs are numeric (CP API reference: order/status example
# ".../order/status/1234567890"; alertId documented as "int. Required").
_ORDER_ID_RE = re.compile(r"^[0-9]+$")

# IBKR reply IDs are documented as "String. Required" with example value
# "a12b34c5-d678-9e012f-3456-7a890b12cd3e" — hex + hyphens, non-standard
# UUID grouping (not 8-4-4-4-12), so match on charset/length, not exact
# segment structure. Source: docs/audits/audit-evidence/scrapes/cpapi-v1.md
# (https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#place-order-reply)
_REPLY_ID_RE = re.compile(r"^[0-9a-fA-F-]{1,64}$")

# ---------------------------------------------------------------------------
# Market history pagination helpers
# /iserver/marketdata/history is capped at 1000 data points per request.
# Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
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
# Conservative bars-per-calendar-day estimates (US equity trading hours).
# Used only for pagination chunk sizing — not exposed to callers.
_BARS_PER_CALENDAR_DAY: dict[str, float] = {
    "1min": 135.0,
    "2min": 67.5,
    "3min": 45.0,
    "5min": 27.0,
    "10min": 13.5,
    "15min": 9.0,
    "30min": 4.5,
    "1h": 3.25,
    "2h": 1.6,
    "3h": 1.1,
    "4h": 0.8,
    "8h": 0.4,
    "1d": 0.69,
    "1w": 0.143,
    "1m": 0.033,
}
_MAX_POINTS = 1000
_CHUNK_SAFETY = 0.80  # target 80% of limit per chunk


def _parse_period_days(period: str) -> float | None:
    """Return approximate calendar days for a period string, or None if unparseable."""
    m = _PERIOD_RE.match(period)
    if not m:
        return None
    return float(m.group(1)) * _UNIT_TO_DAYS[m.group(2).lower()]


def _chunk_days_for_bar(bar: str) -> int:
    """Max calendar days per request chunk that stays safely under 1000 data points."""
    bpd = _BARS_PER_CALENDAR_DAY.get(bar.lower(), 0.69)
    days = int(_MAX_POINTS * _CHUNK_SAFETY / bpd)
    return max(7, min(1000, days))


def _validate_account_id(account_id: str) -> None:
    """Raise ConfigError if account_id is not a valid IBKR account ID."""
    if not account_id or not _ACCOUNT_ID_RE.fullmatch(account_id):
        raise ConfigError(f"Invalid account_id {account_id!r}: must be 4–12 uppercase alphanumeric chars.")


def _validate_order_id(order_id: str) -> None:
    """Raise ConfigError if order_id/alert_id is not a valid IBKR numeric ID.

    Prevents path traversal in URLs built by f-string interpolation — the same
    threat _validate_account_id addresses for account_id. Applies to order_id
    and alert_id (IBKR reuses the same numeric ID namespace for both — see
    docs/audits/security-audit-2026-07-11.md H-2).
    """
    if not order_id or not _ORDER_ID_RE.fullmatch(order_id):
        raise ConfigError(f"Invalid order_id/alert_id {order_id!r}: must be numeric.")


def _validate_reply_id(reply_id: str) -> None:
    """Raise ConfigError if reply_id is not a plausible IBKR reply ID."""
    if not reply_id or not _REPLY_ID_RE.fullmatch(reply_id):
        raise ConfigError(f"Invalid reply_id {reply_id!r}: must be a hex/hyphen string.")


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


class IBKRClient:
    """Wraps all IBKR Client Portal API endpoints. Returns raw dicts.

    All endpoints connect only to localhost. Any non-localhost gateway URL raises
    ConfigError at construction time.

    Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
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
        resp = with_retry(lambda: self._session.get(url, params=params, timeout=30))
        return resp.json()

    def _post(self, path: str, body: dict[str, Any] | None = None) -> Any:
        url = f"{self._base}{path}"
        resp = with_retry(lambda: self._session.post(url, json=body or {}, timeout=30))
        return resp.json()

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

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#auth-status
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

    def get_auth_status(self) -> dict[str, Any]:
        """Full authentication status including authenticated, competing, connected fields.

        Note: official docs document this endpoint as POST /iserver/auth/status (request
        object: empty JSON body). This method calls it via GET, matching ping()'s
        production-verified behavior (see ping() docstring) rather than the documented
        method, since no live test has been run to confirm POST is required. This method
        itself has no callers elsewhere in the codebase as of 2026-06-30.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#auth-status
        Endpoint: GET /iserver/auth/status (see Note above)
        """
        return self._get("/iserver/auth/status")

    def tickle(self) -> bool:
        """Keep the session alive. Returns True on HTTP 200. Never raises.

        Call every few minutes during idle periods. ConnectivityChecker calls this
        every 60s as a side effect of its /tickle poll, preventing IBKR auto-logout.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#tickle
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

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#reauthenticate
        Endpoint: POST /iserver/reauthenticate (Deprecated)
        """
        return self._post("/iserver/reauthenticate")

    def validate_sso(self) -> dict[str, Any]:
        """Validate the SSO token. Used after initial login to confirm the session is active.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#sso-validate
        Endpoint: GET /sso/validate
        """
        return self._get("/sso/validate")

    # ------------------------------------------------------------------
    # Market Data
    # ------------------------------------------------------------------

    def get_market_history(
        self, conid: int, period: str = "1y", bar: str = "1d", outside_rth: bool = False
    ) -> dict[str, Any]:
        """OHLCV bars via iserver/marketdata/history.

        ## Case sensitivity (verified live 2026-07-06)
        IBKR period/bar units are lowercase. Uppercase inputs are NOT rejected —
        the API silently substitutes a ~84-bar default (period='6M' returned 4
        months of dailies; '6m' returned the true 6 months). Inputs are therefore
        lowercased here before the request.

        Returns {"startTime": "...", "data": [{"o":..., "h":..., "l":..., "c":..., "v":..., "t":...}, ...]}.

        ## Data point limit (officially documented)
        Maximum 1000 data points per request. Concurrent request limit: 5.
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

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#hist-md
        Endpoint: GET /iserver/marketdata/history
        """
        return self._get(
            "/iserver/marketdata/history",
            {"conid": conid, "period": period.lower(), "bar": bar.lower(), "outsideRth": str(outside_rth).lower()},
        )

    def get_market_history_paginated(
        self,
        conid: int,
        period: str = "1y",
        bar: str = "1d",
        outside_rth: bool = False,
    ) -> dict[str, Any]:
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

        Chunk sizes by bar (targeting 80% of the 1000-point limit):
          1d  → 1000-calendar-day chunks  (~690 trading days each)
          1w  → 1000-calendar-day chunks  (~142 trading weeks each)
          1h  → 246-calendar-day chunks   (~160 trading days × 6.5h each)
          1m  → 1000-calendar-day chunks  (~33 months each)

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

        if total_days is None or total_days <= chunk_days:
            return self.get_market_history(conid, period, bar, outside_rth)

        all_bars: list[dict[str, Any]] = []
        envelope: dict[str, Any] = {}
        now = datetime.utcnow()
        total = int(total_days)
        offset = 0

        while offset < total:
            n = min(chunk_days, total - offset)
            params: dict[str, Any] = {
                "conid": conid,
                "period": f"{n}d",
                "bar": bar,
                "outsideRth": str(outside_rth).lower(),
            }
            if offset:
                # `startTime` is the END of the window (see the method docstring), so the
                # anchor is where this chunk stops, not where it starts.
                params["startTime"] = (now - timedelta(days=offset)).strftime("%Y%m%d-%H:%M:%S")
                params["direction"] = -1
            # offset == 0 sends NO startTime: "If omitted, the current time is used"
            # (IBKR's OpenAPI spec). Measured 2026-08-05 on SPY 30d/1d — omitted reached
            # 2026-08-05, an explicit timestamp of the same moment reached 08-04, and
            # midnight-today reached 08-03. Only the omitted form returns today's bar,
            # and on a trading surface today is the bar that matters most.
            result = self._get("/iserver/marketdata/history", params)
            if result:
                if not envelope:
                    envelope = {k: v for k, v in result.items() if k != "data"}
                all_bars.extend(result.get("data") or [])
            offset += n

        if not all_bars:
            return {}

        seen: set[int] = set()
        unique: list[dict[str, Any]] = []
        for b in sorted(all_bars, key=lambda x: x.get("t", 0)):
            t = b.get("t")
            if t is not None and t not in seen:
                seen.add(t)
                unique.append(b)

        return {**envelope, "data": unique}

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

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#md-snapshot
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

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#md-unsubscribe-single
        Endpoint: POST /iserver/marketdata/unsubscribe
        """
        return self._post("/iserver/marketdata/unsubscribe", {"conid": conid})

    def unsubscribe_all_market_data(self) -> dict[str, Any]:
        """Cancel all active streaming market data subscriptions.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#md-unsubscribe-all
        Endpoint: GET /iserver/marketdata/unsubscribeall
        """
        return self._get("/iserver/marketdata/unsubscribeall")

    # ------------------------------------------------------------------
    # Contract / Security Definition
    # ------------------------------------------------------------------

    def search_contract(self, symbol: str, sec_type: str = "STK") -> list[dict[str, Any]]:
        """Resolve a symbol to one or more contracts. Returns [] if no match.

        Returns [{"conid": ..., "symbol": ..., "companyName": ..., "exchange": ..., "currency": ...}].

        sec_type: officially documented valid values are "STK", "IND", "BOND" only.
        FUT and CASH (FX) are NOT supported here — use get_futures() (/trsrv/futures)
        and get_currency_pairs() (/iserver/currency/pairs) respectively. OPT requires
        the separate secdef/search -> secdef/info flow (see get_secdef_info()).

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#sec-search
        Endpoint: GET /iserver/secdef/search
        """
        data = self._get("/iserver/secdef/search", {"symbol": symbol, "secType": sec_type})
        return data if isinstance(data, list) else []

    def get_contract_info(self, conid: int) -> dict[str, Any]:
        """Full contract metadata: exchange, currency, primary exchange, trading class, multiplier.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#info-conid-contract
        Endpoint: GET /iserver/contract/{conid}/info
        """
        return self._get(f"/iserver/contract/{conid}/info")

    def get_contract_info_and_rules(self, conid: int) -> dict[str, Any]:
        """Contract info plus trading rules (min tick, valid order types, etc.).

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#info-rules-contract
        Endpoint: GET /iserver/contract/{conid}/info-and-rules
        """
        return self._get(f"/iserver/contract/{conid}/info-and-rules")

    def get_contract_algos(self, conid: int) -> list[dict[str, Any]]:
        """Available algorithmic order types for a contract. Returns [] if none.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#algo-conid-contract
        Endpoint: GET /iserver/contract/{conid}/algos
        """
        data = self._get(f"/iserver/contract/{conid}/algos")
        return data if isinstance(data, list) else []

    def get_secdef_info(self, conid: int) -> dict[str, Any]:
        """Security definition info: type, symbol, currency, exchange, listing exchange.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#secdef-info-contract
        Endpoint: GET /iserver/secdef/info
        """
        return self._get("/iserver/secdef/info", {"conid": conid})

    def get_option_strikes(
        self, conid: int, sec_type: str, month: str, exchange: str = "SMART"
    ) -> dict[str, list[float]]:
        """Available strikes for one expiry month, split into call/put arrays.

        month format per the official spec: {3-char month}{2-char year}, e.g. "JAN26".
        Returns {"call": [...], "put": [...]} — the documented response shape (there
        is no "strike" key; earlier code read one and always got []). Always returns
        empty arrays unless /iserver/secdef/search was called for the same underlying
        beforehand (without the `name` field).

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#strike-conid-contract
        Endpoint: GET /iserver/secdef/strikes
        """
        data = self._get(
            "/iserver/secdef/strikes", {"conid": conid, "sectype": sec_type, "month": month, "exchange": exchange}
        )
        return {"call": data.get("call", []), "put": data.get("put", [])}

    def get_option_chain(self, symbol: str, month: str | None = None, exchange: str = "SMART") -> dict[str, Any]:
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
        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#search-symbol-contract
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
        return {
            "symbol": symbol.upper(),
            "conid": conid,
            "months": months,
            "month": chosen,
            "call": strikes.get("call", []),
            "put": strikes.get("put", []),
        }

    def get_bond_filters(self, symbol: str, issue_id: str) -> dict[str, Any]:
        """Available filter criteria for bond search.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#search-bond-filters
        Endpoint: GET /iserver/secdef/bond-filters
        """
        return self._get("/iserver/secdef/bond-filters", {"symbol": symbol, "issuerId": issue_id})

    def get_futures(self, symbols: list[str]) -> list[dict[str, Any]]:
        """Futures contracts for root symbols. Returns [] if response shape is unexpected.

        IBKR returns {"CL": [...], "ES": [...]} — this method flattens to a list.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#trsrv-future-contract
        Endpoint: GET /trsrv/futures
        """
        data = self._get("/trsrv/futures", {"symbols": ",".join(symbols)})
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return [c for contracts in data.values() for c in (contracts or [])]
        return []

    def get_stocks(self, symbols: list[str]) -> list[dict[str, Any]]:
        """Stock contracts for symbols. Same dict-flattening behaviour as get_futures().

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#trsrv-stock-contract
        Endpoint: GET /trsrv/stocks
        """
        data = self._get("/trsrv/stocks", {"symbols": ",".join(symbols)})
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return [c for contracts in data.values() for c in (contracts or [])]
        return []

    def get_trading_schedule(
        self, asset_class: str, symbol: str, exchange: str, exchange_filter: str = ""
    ) -> list[dict[str, Any]]:
        """Trading hours, sessions, and timezone for a symbol/exchange.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#trsrv-schedule-contract
        Endpoint: GET /trsrv/secdef/schedule
        """
        params = {"assetClass": asset_class, "symbol": symbol, "exchange": exchange}
        if exchange_filter:
            params["exchangeFilter"] = exchange_filter
        return self._get("/trsrv/secdef/schedule", params)

    def get_secdef(self, conids: list[int]) -> list[dict[str, Any]]:
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

        Not live-verified: the gateway was offline when this was written, so the fix
        rests on the endpoint documentation alone. `tests/test_client_live.py` covers it
        when a gateway is available.

        Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/contract/search-the-security-definition-by-contract-id
                (scraped 2026-07-28: "Returns a list of security definitions for the
                given conids `GET /trsrv/secdef`", Response Object "secdef: array")
        Endpoint: GET /trsrv/secdef?conids=<comma-separated>
        """
        data = self._get("/trsrv/secdef", {"conids": ",".join(str(c) for c in conids)})
        if isinstance(data, dict):
            rows = data.get("secdef")
            return rows if isinstance(rows, list) else []
        return data if isinstance(data, list) else []

    def get_currency_pairs(self, currency: str) -> list[dict[str, Any]]:
        """Available FX pairs for a target currency: [{symbol, conid, ccyPair}, ...].

        Response is keyed by the requested currency, e.g. {"USD": [{"symbol": "USD.SGD",
        "conid": 37928772, "ccyPair": "SGD"}, ...]} — flattened to a list here, same
        dict-flattening behaviour as get_futures()/get_stocks().

        Corrected 2026-06-30: previously called the undocumented /iserver/secdef/currency
        (always returned [] — response is a dict, not a list, so the old isinstance(list)
        check silently discarded every result). /iserver/secdef/search also does not
        document CASH as a valid secType (only STK, IND, BOND) — this is the only
        documented FX resolution path.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#get-currency-pairs
        Endpoint: GET /iserver/currency/pairs
        """
        data = self._get("/iserver/currency/pairs", {"currency": currency})
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return [c for contracts in data.values() for c in (contracts or [])]
        return []

    def get_contract_rules(self, conid: int, is_buy: bool = True) -> dict[str, Any]:
        """Order rules for a contract: min tick, valid order types, size constraints.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#rules-contract
        Endpoint: POST /iserver/contract/rules
        """
        return self._post("/iserver/contract/rules", {"conid": conid, "isBuy": is_buy})

    # ------------------------------------------------------------------
    # Portfolio
    # ------------------------------------------------------------------

    def get_accounts(self) -> list[dict[str, Any]]:
        """All accounts associated with the authenticated session. Returns [] if not a list.

        Returns [{"accountId": "U1234567", ...}].

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#portfolio-accounts
        Endpoint: GET /portfolio/accounts
        """
        data = self._get("/portfolio/accounts")
        return data if isinstance(data, list) else []

    def get_subaccounts(self) -> list[dict[str, Any]]:
        """Sub-accounts for IB Family accounts and advisors. Returns [] if not a list.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#portfolio-subaccounts
        Endpoint: GET /portfolio/subaccounts
        """
        data = self._get("/portfolio/subaccounts")
        return data if isinstance(data, list) else []

    def get_account_meta(self, account_id: str) -> dict[str, Any]:
        """Account metadata: display name, status, type.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#portfolio-meta
        Endpoint: GET /portfolio/{accountId}/meta
        """
        _validate_account_id(account_id)
        return self._get(f"/portfolio/{account_id}/meta")

    def get_account_summary(self, account_id: str) -> dict[str, Any]:
        """Net liquidation, cash, P&L. Response uses nested {"amount": value} objects.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#portfolio-summary
        Endpoint: GET /portfolio/{accountId}/summary
        """
        _validate_account_id(account_id)
        return self._get(f"/portfolio/{account_id}/summary")

    def get_account_ledger(self, account_id: str) -> dict[str, Any]:
        """Cash balances by currency with detailed ledger fields.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#portfolio-ledger
        Endpoint: GET /portfolio/{accountId}/ledger
        """
        _validate_account_id(account_id)
        return self._get(f"/portfolio/{account_id}/ledger")

    def get_account_allocation(self, account_id: str) -> dict[str, Any]:
        """Portfolio breakdown by asset class, sector, and industry.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#portfolio-allocation-single
        Endpoint: GET /portfolio/{accountId}/allocation
        """
        _validate_account_id(account_id)
        return self._get(f"/portfolio/{account_id}/allocation")

    def get_positions(self, account_id: str, page: int = 0) -> list[dict[str, Any]]:
        """Open positions, paginated (page 0 = first 30). Returns [] if not a list.

        Returns [{"conid": ..., "contractDesc": ..., "position": ..., "mktPrice": ...,
        "mktValue": ..., "unrealizedPnl": ..., "realizedPnl": ...}].

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#positions
        Endpoint: GET /portfolio/{accountId}/positions/{page}
        """
        _validate_account_id(account_id)
        data = self._get(f"/portfolio/{account_id}/positions/{page}")
        return data if isinstance(data, list) else []

    def get_positions_by_conid(self, conid: int) -> list[dict[str, Any]]:
        """Position data for a specific contract across all accounts. Returns [] if not a list.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#position-contract-info
        Endpoint: GET /portfolio/positions/{conid}
        """
        data = self._get(f"/portfolio/positions/{conid}")
        return data if isinstance(data, list) else []

    def get_position(self, account_id: str, conid: int) -> dict[str, Any]:
        """Position for a specific account + contract pair.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#contract-positions
        Endpoint: GET /portfolio/{accountId}/position/{conid}
        """
        _validate_account_id(account_id)
        return self._get(f"/portfolio/{account_id}/position/{conid}")

    def get_combo_positions(self, account_id: str) -> list[dict[str, Any]]:
        """Combo/spread positions for an account. Returns [] if not a list.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#portfolio-combo
        Endpoint: GET /portfolio/{accountId}/combo/positions
        """
        _validate_account_id(account_id)
        data = self._get(f"/portfolio/{account_id}/combo/positions")
        return data if isinstance(data, list) else []

    def get_portfolio_allocation(self, account_ids: list[str]) -> dict[str, Any]:
        """Aggregated allocation across multiple accounts.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#portfolio-allocation-all
        Endpoint: POST /portfolio/allocation
        """
        return self._post("/portfolio/allocation", {"acctIds": account_ids})

    def invalidate_positions_cache(self, account_id: str) -> dict[str, Any]:
        """Force-refresh the IBKR position cache. Call before get_positions() if data looks stale.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#portfolio-invalidate
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

    def get_live_orders(self) -> list[dict[str, Any]]:
        """Working orders only (PreSubmitted, Submitted, ApiPending, PendingSubmit, PendingCancel, Inactive).

        Two-call pattern required: first call with ?force=true instantiates the subscription;
        second call returns the actual live order list.
        Inactive = order exists on IBKR but is stalled (e.g. failed risk check).

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#live-orders
                https://www.interactivebrokers.com/campus/trading-lessons/request-modify-orders/
        Endpoint: GET /iserver/account/orders
        """
        self._ensure_accounts_initialized()
        self._get("/iserver/account/orders?force=true")  # instantiate subscription
        time.sleep(1)
        data = self._get("/iserver/account/orders")  # retrieve actual data
        orders = data.get("orders", data) if isinstance(data, dict) else data
        if not isinstance(orders, list):
            return []
        return [o for o in orders if o.get("status") and o.get("status") not in self._TERMINAL_STATUSES]

    def get_orders_raw(self) -> Any:
        """Raw, unfiltered /iserver/account/orders response, for diagnostics.

        Same documented two-call warmup as get_live_orders, but returns the response
        exactly as IBKR sent it — no status filtering, no shape normalization. Used
        by ClaudeToolkit's diagnose_orders to show what the server actually returned.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#live-orders
        Endpoint: GET /iserver/account/orders
        """
        self._ensure_accounts_initialized()
        self._get("/iserver/account/orders?force=true")  # instantiate subscription
        time.sleep(1)
        return self._get("/iserver/account/orders")

    def get_order_status(self, order_id: str) -> dict[str, Any]:
        """Full order details for a specific order ID.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#order-status
        Endpoint: GET /iserver/account/order/status/{orderId}
        """
        _validate_order_id(order_id)
        self._ensure_accounts_initialized()
        return self._get(f"/iserver/account/order/status/{order_id}")

    def get_trades(self) -> list[dict[str, Any]]:
        """Trade executions for the current day + up to 6 previous days (7-day window).

        **This is the package's direct access point for TODAY's and recent fills** —
        the only REST source that can contain same-day executions (Flex is T+1 and
        never contains today). Exposed to the LLM as `get_trades(source='live')`.

        ## ?days parameter (officially documented, re-verified 2026-07-02)
        Specify the number of days to receive executions for, up to a maximum of 7 days.
        If unspecified, only the current day is returned. We always pass days=7 for
        maximum lookback. The docs also advise calling this endpoint once per session.

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

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#trades
        Endpoint: GET /iserver/account/trades
        """
        # days=7 requests maximum lookback; without it IBKR returns today's session only
        data = self._get("/iserver/account/trades?days=7")
        if isinstance(data, list) and data:
            return data
        time.sleep(1)  # empty first response may be the unprimed subscription
        data = self._get("/iserver/account/trades?days=7")
        return data if isinstance(data, list) else []

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

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#pa-all-periods
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

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#pa-all-periods
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

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#pa-account-performance
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

        Bug fixed 2026-06-30: previous signature took `period: str` and sent it as the
        request body field "period" — both wrong. Required fields are `conids` (array of
        ints) and `currency` (string). `days` is optional (int). Old calls returned HTTP
        400 because `conids` and `currency` were missing from the request body.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#pa-transaction-history
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
        return data if isinstance(data, list) else []

    # ------------------------------------------------------------------
    # Scanner
    # ------------------------------------------------------------------

    def get_scanner_params(self) -> dict[str, Any]:
        """Available scanner types and filter parameters.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#iserver-scanner-parameters
        Endpoint: GET /iserver/scanner/params
        """
        return self._get("/iserver/scanner/params")

    def run_iserver_scanner(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Run a scanner with full parameter control. Returns [] if no contracts matched.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#iserver-market-scanner
        Endpoint: POST /iserver/scanner/run
        """
        data = self._post("/iserver/scanner/run", params)
        contracts = data.get("contracts", data) if isinstance(data, dict) else data
        return contracts if isinstance(contracts, list) else []

    # ------------------------------------------------------------------
    # FYI / Notifications
    # ------------------------------------------------------------------

    def get_notifications(self, max_results: int = 10) -> list[dict[str, Any]]:
        """Account notifications — order fills, margin calls, system messages.

        IBKR enforces a hard cap of 10 notifications per request.
        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#notification-list
        Endpoint: GET /fyi/notifications
        """
        max_results = min(max(1, max_results), 10)
        data = self._get("/fyi/notifications", {"max": max_results})
        return data if isinstance(data, list) else []

    def get_unread_count(self) -> int:
        """Number of unread FYI notifications.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#unread-bulletins
        Endpoint: GET /fyi/unreadnumber
        """
        data = self._get("/fyi/unreadnumber")
        return data.get("unreadNumber", 0) if isinstance(data, dict) else 0

    def get_delivery_options(self) -> dict[str, Any]:
        """Notification delivery channel configuration.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#get-delivery
        Endpoint: GET /fyi/deliveryoptions
        """
        return self._get("/fyi/deliveryoptions")

    def get_mta_alert(self) -> dict[str, Any]:
        """Mobile Trading Alerts — account-level watchdog alerts.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#get-mta-alert
        Endpoint: GET /iserver/account/mta
        """
        return self._get("/iserver/account/mta")

    def get_alerts(self, account_id: str) -> list[dict[str, Any]]:
        """All price alerts configured on the account. The orderId field is the alert ID.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#get-alert-list
        Endpoint: GET /iserver/account/{accountId}/alerts
        """
        _validate_account_id(account_id)
        data = self._get(f"/iserver/account/{account_id}/alerts")
        return data if isinstance(data, list) else []

    # ------------------------------------------------------------------
    # Watchlists (read-only)
    # ------------------------------------------------------------------

    def get_watchlists(self) -> list[dict[str, Any]]:
        """All watchlists for the account. Returns [] if not a list.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#all-watchlists
        Endpoint: GET /iserver/watchlists
        """
        data = self._get("/iserver/watchlists", {"SC": "USER_WATCHLIST"})
        return data if isinstance(data, list) else []

    def get_watchlist(self, watchlist_id: str) -> dict[str, Any]:
        """Contents of a specific watchlist. Uses the watchlist ID as a query param.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#watchlist-info
        Endpoint: GET /iserver/watchlist
        """
        return self._get("/iserver/watchlist", {"id": watchlist_id})

    # ------------------------------------------------------------------
    # Events Contracts
    # ------------------------------------------------------------------

    def get_event_contracts(self, conids: list[int]) -> list[dict[str, Any]]:
        """Event-based contracts (e.g. political outcome contracts). Returns [] if not a list.

        WARNING: /events/contracts does not appear in the official IBKR Client Portal API or
        Web API reference (verified 2026-06-30, full page scan of both docs pages). If IBKR
        has an event contracts API it may be on a separate unreleased documentation page.
        This method will raise IBKRAPIError (404) until the correct endpoint is identified.

        Source: unverified — endpoint not found in official docs
        Endpoint: GET /events/contracts
        """
        data = self._get("/events/contracts", {"conids": ",".join(str(c) for c in conids)})
        return data if isinstance(data, list) else []

    def get_event_contract(self, conid: int) -> dict[str, Any]:
        """Details for a specific event contract.

        WARNING: /events/show does not appear in the official IBKR Client Portal API or
        Web API reference (verified 2026-06-30, full page scan of both docs pages). Same
        class of unverified endpoint as get_event_contracts().

        Source: unverified — endpoint not found in official docs
        Endpoint: GET /events/show
        """
        return self._get("/events/show", {"conid": conid})

    # ------------------------------------------------------------------
    # Order Management (write — human auth required)
    # ------------------------------------------------------------------

    def place_order(self, account_id: str, order: dict[str, Any]) -> list[dict[str, Any]]:
        """Place a new order. Requires Touch ID (Gate 1) + tkinter confirmation dialog (Gate 2).

        Both security gates fire before any network call. HumanAuthError is raised if either
        gate fails or times out. ClaudIA constraint: ClaudeToolkit exposes no tool calling
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

        US Futures and Futures Options (FUT/FOP): caller must include both manualIndicator=True
        and extOperator="<user>" in the order dict. Required since May 1, 2025 for CME Group
        Rule 536-B compliance. IBKR returns HTTP 400 without them for FUT/FOP orders.
        order_flow.py adds these automatically when sec_type is "FUT" or "FOP".
        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/web-api-changelog/
                https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#place-order

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#place-order
                https://www.interactivebrokers.com/campus/trading-lessons/request-modify-orders/
        Endpoint: POST /iserver/account/{accountId}/orders
        """
        _validate_account_id(account_id)
        self._ensure_accounts_initialized()
        symbol = order.get("ticker", order.get("symbol", "UNKNOWN"))
        side = order.get("side", "?")
        qty = order.get("quantity", "?")
        require_touch_id(f"IBKR: Place order — {side} {qty} {symbol}")
        confirm_order_dialog(order, account_id)
        # Strip display-only fields (underscore-prefixed, e.g. _companyName).
        # These carry Gate-2 dialog metadata and are not valid IBKR request fields.
        # Note: ticker IS a valid IBKR field (optional) and is NOT stripped.
        # manualIndicator / extOperator are FUT/FOP only (CME Rule 536-B) — caller adds them
        # for futures; omit here to avoid type-rejection on equity orders.
        # Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#place-order
        api_order = {k: v for k, v in order.items() if not k.startswith("_")}
        data = self._post(f"/iserver/account/{account_id}/orders", {"orders": [api_order]})
        return data if isinstance(data, list) else []

    def modify_order(self, account_id: str, order_id: str, order: dict[str, Any]) -> dict[str, Any]:
        """Modify an existing order. Requires Touch ID (Gate 1) + tkinter dialog (Gate 2).

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#modify-order
                https://www.interactivebrokers.com/campus/trading-lessons/request-modify-orders/
        Endpoint: POST /iserver/account/{accountId}/order/{orderId}
        """
        _validate_account_id(account_id)
        _validate_order_id(order_id)
        self._ensure_accounts_initialized()
        require_touch_id(f"IBKR: Modify order {order_id}")
        confirm_modify_dialog(order_id, order, account_id)
        return self._post(f"/iserver/account/{account_id}/order/{order_id}", order)

    def cancel_order(
        self, account_id: str, order_id: str, order_details: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Cancel an order. Requires Touch ID (Gate 1) + tkinter confirmation dialog (Gate 2).

        `order_details` is optional display-only info (symbol/side/qty/price/TIF/etc.) shown
        in the Gate 2 dialog so the human can verify the right order before cancelling —
        mirrors modify_order()'s dialog, which already receives the full order dict. Found
        missing live 2026-07-10 — user-flagged hard requirement.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#cancel-order
                https://www.interactivebrokers.com/campus/trading-lessons/request-modify-orders/
        Endpoint: DELETE /iserver/account/{accountId}/order/{orderId}
        """
        _validate_account_id(account_id)
        _validate_order_id(order_id)
        self._ensure_accounts_initialized()
        require_touch_id(f"IBKR: Cancel order {order_id}")
        confirm_cancel_dialog(order_id, account_id, order_details)
        url = f"{self._base}/iserver/account/{account_id}/order/{order_id}"
        resp = with_retry(lambda: self._session.delete(url, timeout=30))
        return resp.json()

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

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#place-order-reply
                https://www.interactivebrokers.com/campus/trading-lessons/request-modify-orders/
        Endpoint: POST /iserver/reply/{replyId}
        """
        _validate_reply_id(reply_id)
        self._ensure_accounts_initialized()
        require_touch_id(f"IBKR: Confirm order reply {reply_id}")
        confirm_reply_dialog(reply_id)
        data = self._post(f"/iserver/reply/{reply_id}", {"confirmed": ibkr_confirmed})
        return data if isinstance(data, list) else []

    def _resolve_one_reply(self, entry: dict[str, Any]) -> Any:
        """Run Gate 1 + Gate 2 for one reply-chain entry, then tell IBKR the outcome.

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
        a bug: see docs/2026-07-06-order-reply-confirmation-design.md.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#place-order-reply
        Endpoint: POST /iserver/reply/{replyId}
        """
        reply_id = entry["id"]
        message = " ".join(entry.get("message", []))
        options = entry.get("messageOptions")
        require_touch_id(f"IBKR: Confirm order reply {reply_id}")
        try:
            confirm_reply_dialog(reply_id, message, options)
        except HumanAuthError:
            self._post(f"/iserver/reply/{reply_id}", {"confirmed": False})
            raise HumanAuthError("User declined IBKR order reply") from None
        return self._post(f"/iserver/reply/{reply_id}", {"confirmed": True})

    def place_order_and_confirm(self, account_id: str, order: dict[str, Any]) -> list[dict[str, Any]]:
        """Place an order and resolve its full reply chain, looping until a terminal response.

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

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#place-order
                https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#place-order-reply
        Endpoint: POST /iserver/account/{accountId}/orders, then POST /iserver/reply/{replyId}*
        """
        response = _as_reply_list(self.place_order(account_id, order))
        while response and "id" in response[0]:
            response = _as_reply_list(self._resolve_one_reply(response[0]))
        return response

    def modify_order_and_confirm(self, account_id: str, order_id: str, order: dict[str, Any]) -> dict[str, Any]:
        """Modify an order and resolve its full reply chain, looping until a terminal response.

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

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#modify-order
                https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#place-order-reply
        Endpoint: POST /iserver/account/{accountId}/order/{orderId}, then POST /iserver/reply/{replyId}*
        """
        response = self.modify_order(account_id, order_id, order)
        while "id" in response:
            response = _as_reply_dict(self._resolve_one_reply(response))
        return response

    def get_order_preview(self, account_id: str, order: dict[str, Any]) -> dict[str, Any]:
        """Whatif order preview — cost, commission, margin impact. Read-only, no security gates.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#whatif-order
        Endpoint: POST /iserver/account/{accountId}/orders/whatif
        """
        _validate_account_id(account_id)
        self._ensure_accounts_initialized()
        # Strip display-only fields (underscore-prefixed) — same convention as place_order.
        # Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#place-order
        api_order = {k: v for k, v in order.items() if not k.startswith("_")}
        return self._post(f"/iserver/account/{account_id}/orders/whatif", {"orders": [api_order]})

    # ------------------------------------------------------------------
    # Alerts (write)
    # ------------------------------------------------------------------

    def get_alert(self, alert_id: str) -> dict[str, Any]:
        """Full details for a specific alert by ID. Not account-scoped in the URL
        (same pattern as get_order_status) — IBKR resolves the alert from the
        session's logged-in account.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#get-alert
        Endpoint: GET /iserver/account/alert/{order_id}?type=Q
        """
        _validate_order_id(alert_id)
        return self._get(f"/iserver/account/alert/{alert_id}", params={"type": "Q"})

    def create_alert(self, account_id: str, alert: dict[str, Any]) -> dict[str, Any]:
        """Create a price alert. The alert dict must match the IBKR alert payload schema.

        Use ClaudeToolkit.execute("create_price_alert", ...) instead — it resolves
        conid and exchange automatically.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#create-alert
        Endpoint: POST /iserver/account/{accountId}/alert
        """
        _validate_account_id(account_id)
        return self._post(f"/iserver/account/{account_id}/alert", alert)

    def delete_alert(self, account_id: str, alert_id: str) -> dict[str, Any]:
        """Delete an alert permanently.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#delete-alert
        Endpoint: DELETE /iserver/account/{accountId}/alert/{alertId}
        """
        _validate_account_id(account_id)
        _validate_order_id(alert_id)
        url = f"{self._base}/iserver/account/{account_id}/alert/{alert_id}"
        resp = with_retry(lambda: self._session.delete(url, timeout=30))
        return resp.json()

    def activate_alert(self, account_id: str, alert_id: str, activate: bool = True) -> dict[str, Any]:
        """Toggle alert on (activate=True) or off (activate=False) without deleting it.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#activate-alert
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

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#create-watchlist
        Endpoint: POST /iserver/watchlist
        """
        return self._post("/iserver/watchlist", {"id": name, "name": name, "rows": rows})

    def delete_watchlist(self, watchlist_id: str) -> dict[str, Any]:
        """Delete a watchlist permanently. watchlist_id is passed as query param `id`.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#delete-watchlist
        Endpoint: DELETE /iserver/watchlist
        """
        url = f"{self._base}/iserver/watchlist"
        resp = with_retry(lambda: self._session.delete(url, params={"id": watchlist_id}, timeout=30))
        return resp.json()

    # ------------------------------------------------------------------
    # FYI (write)
    # ------------------------------------------------------------------

    def mark_notification_read(self, notification_id: str) -> dict[str, Any]:
        """Mark a FYI notification as read.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#read-notification
        Endpoint: POST /fyi/notifications/{notificationId}/read
        """
        return self._post(f"/fyi/notifications/{notification_id}/read")

    def update_delivery_option(self, device_id: str, option: str, enabled: bool) -> dict[str, Any]:
        """Enable or disable a notification delivery channel.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#enable-device
        Endpoint: POST /fyi/deliveryoptions/{option}
        """
        return self._post(f"/fyi/deliveryoptions/{option}", {"deviceId": device_id, "enabled": enabled})

    # ------------------------------------------------------------------
    # Account / Admin
    # ------------------------------------------------------------------

    def get_brokerage_accounts(self) -> dict[str, Any]:
        """List of accounts the user has trading access to, their aliases, the currently
        selected account, and per-account capability flags (supportsCashQty,
        supportsFractions, allowCustomerTime, etc).

        Per official docs, this endpoint must be called before modifying an order or
        querying open orders. _ensure_accounts_initialized() calls this once per
        IBKRClient instance and caches the result; every order read/write method calls
        it first, so callers never need to call this directly under normal use.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#get-brokerage-accounts
        Endpoint: GET /iserver/accounts
        """
        return self._get("/iserver/accounts")

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

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#switch-account
        Endpoint: POST /iserver/account
        """
        _validate_account_id(account_id)
        return self._post("/iserver/account", {"acctId": account_id})

    def get_pnl(self) -> dict[str, Any]:
        """Real-time partitioned P&L — daily, unrealized, realized — across all positions.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#account-pnl
        Endpoint: GET /iserver/account/pnl/partitioned
        """
        return self._get("/iserver/account/pnl/partitioned")

    def logout(self) -> dict[str, Any]:
        """End the current IBKR session.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#logout
        Endpoint: POST /logout
        """
        return self._post("/logout")
