from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import urlparse

import requests
import urllib3

from ibkr_core_mcp.auth import AuthStrategy, BrowserCookieAuth
from ibkr_core_mcp.config import Config
from ibkr_core_mcp.exceptions import ConfigError
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

# ---------------------------------------------------------------------------
# Market history pagination helpers
# /iserver/marketdata/history is capped at 1000 data points per request.
# Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
# ---------------------------------------------------------------------------

_PERIOD_RE = re.compile(r"^(\d+)(min|h|d|w|m|y)$", re.IGNORECASE)
_UNIT_TO_DAYS: dict[str, float] = {
    "min": 1 / 1440, "h": 1 / 24, "d": 1, "w": 7, "m": 30, "y": 365,
}
# Conservative bars-per-calendar-day estimates (US equity trading hours).
# Used only for pagination chunk sizing — not exposed to callers.
_BARS_PER_CALENDAR_DAY: dict[str, float] = {
    "1min": 135.0, "2min": 67.5, "3min": 45.0, "5min": 27.0,
    "10min": 13.5, "15min": 9.0, "30min": 4.5,
    "1h": 3.25, "2h": 1.6, "3h": 1.1, "4h": 0.8, "8h": 0.4,
    "1d": 0.69, "1w": 0.143, "1m": 0.033,
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
        raise ConfigError(
            f"Invalid account_id {account_id!r}: must be 4–12 uppercase alphanumeric chars."
        )


class IBKRClient:
    """Wraps all IBKR Client Portal API endpoints. Returns raw dicts.

    All endpoints connect only to localhost. Any non-localhost gateway URL raises
    ConfigError at construction time.

    Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
    Note: The official IBKR CP API reference requires authentication to access.
    Endpoint behavior documented here is verified through testing and official
    IBKR Campus lessons where publicly accessible.
    """

    def __init__(
        self,
        config: Config,
        auth: AuthStrategy | None = None,
    ) -> None:
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

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
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

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: GET /iserver/auth/status
        """
        return self._get("/iserver/auth/status")

    def tickle(self) -> bool:
        """Keep the session alive. Returns True on HTTP 200. Never raises.

        Call every few minutes during idle periods. ConnectivityChecker calls this
        every 60s as a side effect of its /tickle poll, preventing IBKR auto-logout.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: POST /tickle
        """
        try:
            resp = self._session.post(f"{self._base}/tickle", timeout=5)
            return resp.status_code == 200
        except Exception:
            return False

    def reauthenticate(self) -> dict[str, Any]:
        """Request a new authentication session.

        Use only when get_auth_status() shows authenticated=false and the user
        has not recently logged in. Do NOT call proactively — it terminates any
        active authenticated session, including fresh logins.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: POST /iserver/reauthenticate
        """
        return self._post("/iserver/reauthenticate")

    def validate_sso(self) -> dict[str, Any]:
        """Validate the SSO token. Used after initial login to confirm the session is active.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: POST /sso/validate
        """
        return self._post("/sso/validate")

    # ------------------------------------------------------------------
    # Market Data
    # ------------------------------------------------------------------

    def get_market_history(self, conid: int, period: str = "1Y", bar: str = "1d", outside_rth: bool = False) -> dict[str, Any]:
        """OHLCV bars via iserver/marketdata/history.

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

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: GET /iserver/marketdata/history
        """
        return self._get("/iserver/marketdata/history", {"conid": conid, "period": period, "bar": bar, "outsideRth": str(outside_rth).lower()})

    def get_market_history_paginated(
        self,
        conid: int,
        period: str = "1Y",
        bar: str = "1d",
        outside_rth: bool = False,
    ) -> dict[str, Any]:
        """Fetch OHLCV bars with automatic pagination for requests exceeding 1000 data points.

        Wraps get_market_history() and chunks large requests using the startTime parameter,
        walking backwards from today in calendar-day windows sized to stay safely under
        the 1000-point limit. Results are merged, sorted by timestamp, and deduplicated.

        This is the primary entry point for ClaudeToolkit.fetch_market_data().

        Chunk sizes by bar (targeting 80% of the 1000-point limit):
          1d  → 1000-calendar-day chunks  (~690 trading days each)
          1w  → 1000-calendar-day chunks  (~142 trading weeks each)
          1h  → 197-calendar-day chunks   (~128 trading days × 6.5h each)
          1m  → 1000-calendar-day chunks  (~33 months each)

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
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
            chunk_start = now - timedelta(days=offset + n)
            result = self._get("/iserver/marketdata/history", {
                "conid": conid,
                "period": f"{n}d",
                "bar": bar,
                "outsideRth": str(outside_rth).lower(),
                "startTime": chunk_start.strftime("%Y%m%d-00:00:00"),
            })
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

        Two-call pattern: /iserver/accounts must be called before the first snapshot request
        (handled at session init). First snapshot call for a new conid initialises the
        subscription but returns no price fields — caller should retry after ~1s.

        Limits: max 100 conids per request, max 50 fields per request.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#md-snapshot
        Changelog: https://www.interactivebrokers.com/campus/ibkr-api-page/web-api-changelog/
        Endpoint: GET /iserver/marketdata/snapshot
        """
        field_str = ",".join(fields or ["31", "55", "70", "71", "82", "83", "84", "86", "87", "6509"])
        data = self._get("/iserver/marketdata/snapshot", {"conids": ",".join(str(c) for c in conids), "fields": field_str})
        return data if isinstance(data, list) else []

    def get_market_data_fields(self) -> dict[str, Any]:
        """Available field codes and their human-readable names.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: GET /iserver/marketdata/fields
        """
        return self._get("/iserver/marketdata/fields")

    def get_market_data_periods(self) -> dict[str, Any]:
        """Valid period strings for market history requests (e.g. "1D", "1W", "1M", "1Y").

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: GET /iserver/marketdata/periods
        """
        return self._get("/iserver/marketdata/periods")

    def get_market_data_bars(self) -> dict[str, Any]:
        """Valid bar size strings for market history requests (e.g. "1min", "1h", "1d").

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: GET /iserver/marketdata/bars
        """
        return self._get("/iserver/marketdata/bars")

    def unsubscribe_market_data(self, conid: int) -> dict[str, Any]:
        """Unsubscribe a specific contract from streaming market data.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: POST /iserver/marketdata/unsubscribe
        """
        return self._post("/iserver/marketdata/unsubscribe", {"conid": conid})

    def unsubscribe_all_market_data(self) -> dict[str, Any]:
        """Unsubscribe all active streaming market data subscriptions.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: POST /iserver/marketdata/unsubscribeall
        """
        return self._post("/iserver/marketdata/unsubscribeall")

    def get_md_snapshot(self, conids: list[int], fields: list[str] | None = None) -> list[dict[str, Any]]:
        """Alternative snapshot endpoint. Same semantics as get_market_snapshot().

        Use when /iserver/marketdata/snapshot returns empty. Default fields: 31 (last), 55 (symbol).

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: GET /md/snapshot
        """
        field_str = ",".join(fields or ["31", "55"])
        data = self._get("/md/snapshot", {"conids": ",".join(str(c) for c in conids), "fields": field_str})
        return data if isinstance(data, list) else []

    def get_market_data_availability(self) -> dict[str, Any]:
        """Market data subscription availability for the account.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: GET /iserver/marketdata/availability
        """
        return self._get("/iserver/marketdata/availability")

    # ------------------------------------------------------------------
    # Contract / Security Definition
    # ------------------------------------------------------------------

    def search_contract(self, symbol: str, sec_type: str = "STK") -> list[dict[str, Any]]:
        """Resolve a symbol to one or more contracts. Returns [] if no match.

        Returns [{"conid": ..., "symbol": ..., "companyName": ..., "exchange": ..., "currency": ...}].
        sec_type: "STK", "FUT", "OPT", "FX", "IND", "CFD", "BOND".

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: GET /iserver/secdef/search
        """
        data = self._get("/iserver/secdef/search", {"symbol": symbol, "secType": sec_type})
        return data if isinstance(data, list) else []

    def get_contract_info(self, conid: int) -> dict[str, Any]:
        """Full contract metadata: exchange, currency, primary exchange, trading class, multiplier.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: GET /iserver/contract/{conid}/info
        """
        return self._get(f"/iserver/contract/{conid}/info")

    def get_contract_info_and_rules(self, conid: int) -> dict[str, Any]:
        """Contract info plus trading rules (min tick, valid order types, etc.).

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: GET /iserver/contract/{conid}/info-and-rules
        """
        return self._get(f"/iserver/contract/{conid}/info-and-rules")

    def get_contract_algos(self, conid: int) -> list[dict[str, Any]]:
        """Available algorithmic order types for a contract. Returns [] if none.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: GET /iserver/contract/{conid}/algos
        """
        data = self._get(f"/iserver/contract/{conid}/algos")
        return data if isinstance(data, list) else []

    def get_secdef_info(self, conid: int) -> dict[str, Any]:
        """Security definition info: type, symbol, currency, exchange, listing exchange.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: GET /iserver/secdef/info
        """
        return self._get("/iserver/secdef/info", {"conid": conid})

    def get_option_strikes(self, conid: int, sec_type: str, month: str, exchange: str = "SMART") -> list[float]:
        """Available strike prices for an options chain. month format: "JAN2026".

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: GET /iserver/secdef/strikes
        """
        data = self._get("/iserver/secdef/strikes", {"conid": conid, "sectype": sec_type, "month": month, "exchange": exchange})
        return data.get("strike", [])

    def get_option_chain(self, symbol: str, exchange: str = "SMART", currency: str = "USD") -> dict[str, Any]:
        """Full options chain — all expirations, strikes, and conids.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: GET /trsrv/secdef/chains
        """
        return self._get("/trsrv/secdef/chains", {"symbol": symbol, "exchange": exchange, "currency": currency})

    def get_bond_filters(self, symbol: str, issue_id: str) -> dict[str, Any]:
        """Available filter criteria for bond search.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: GET /iserver/secdef/bond-filters
        """
        return self._get("/iserver/secdef/bond-filters", {"symbol": symbol, "issuerId": issue_id})

    def get_futures(self, symbols: list[str]) -> list[dict[str, Any]]:
        """Futures contracts for root symbols. Returns [] if response shape is unexpected.

        IBKR returns {"CL": [...], "ES": [...]} — this method flattens to a list.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
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

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: GET /trsrv/stocks
        """
        data = self._get("/trsrv/stocks", {"symbols": ",".join(symbols)})
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return [c for contracts in data.values() for c in (contracts or [])]
        return []

    def get_trading_schedule(self, asset_class: str, symbol: str, exchange: str, exchange_filter: str = "") -> dict[str, Any]:
        """Trading hours, sessions, and timezone for a symbol/exchange.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: GET /trsrv/secdef/schedule
        """
        params = {"assetClass": asset_class, "symbol": symbol, "exchange": exchange}
        if exchange_filter:
            params["exchangeFilter"] = exchange_filter
        return self._get("/trsrv/secdef/schedule", params)

    def get_secdef(self, conids: list[int]) -> list[dict[str, Any]]:
        """Batch security definitions for multiple conids. Returns [] if response is not a list.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: GET /trsrv/secdef
        """
        data = self._get("/trsrv/secdef", {"conids": ",".join(str(c) for c in conids)})
        return data if isinstance(data, list) else []

    def get_currency_pairs(self, currency: str) -> list[dict[str, Any]]:
        """Available FX pairs for a base currency. Returns [] if response is not a list.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: GET /iserver/secdef/currency
        """
        data = self._get("/iserver/secdef/currency", {"currency": currency})
        return data if isinstance(data, list) else []

    def get_contract_rules(self, conid: int, is_buy: bool = True) -> dict[str, Any]:
        """Order rules for a contract: min tick, valid order types, size constraints.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: POST /iserver/contract/rules
        """
        return self._post("/iserver/contract/rules", {"conid": conid, "isBuy": is_buy})

    # ------------------------------------------------------------------
    # Portfolio
    # ------------------------------------------------------------------

    def get_accounts(self) -> list[dict[str, Any]]:
        """All accounts associated with the authenticated session. Returns [] if not a list.

        Returns [{"accountId": "U1234567", ...}].

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: GET /portfolio/accounts
        """
        data = self._get("/portfolio/accounts")
        return data if isinstance(data, list) else []

    def get_subaccounts(self) -> list[dict[str, Any]]:
        """Sub-accounts for IB Family accounts and advisors. Returns [] if not a list.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: GET /portfolio/subaccounts
        """
        data = self._get("/portfolio/subaccounts")
        return data if isinstance(data, list) else []

    def get_account_meta(self, account_id: str) -> dict[str, Any]:
        """Account metadata: display name, status, type.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: GET /portfolio/{accountId}/meta
        """
        _validate_account_id(account_id)
        return self._get(f"/portfolio/{account_id}/meta")

    def get_account_summary(self, account_id: str) -> dict[str, Any]:
        """Net liquidation, cash, P&L. Response uses nested {"amount": value} objects.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: GET /portfolio/{accountId}/summary
        """
        _validate_account_id(account_id)
        return self._get(f"/portfolio/{account_id}/summary")

    def get_account_ledger(self, account_id: str) -> dict[str, Any]:
        """Cash balances by currency with detailed ledger fields.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: GET /portfolio/{accountId}/ledger
        """
        _validate_account_id(account_id)
        return self._get(f"/portfolio/{account_id}/ledger")

    def get_account_allocation(self, account_id: str) -> dict[str, Any]:
        """Portfolio breakdown by asset class, sector, and industry.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: GET /portfolio/{accountId}/allocation
        """
        _validate_account_id(account_id)
        return self._get(f"/portfolio/{account_id}/allocation")

    def get_positions(self, account_id: str, page: int = 0) -> list[dict[str, Any]]:
        """Open positions, paginated (page 0 = first 30). Returns [] if not a list.

        Returns [{"conid": ..., "contractDesc": ..., "position": ..., "mktPrice": ...,
        "mktValue": ..., "unrealizedPnl": ..., "realizedPnl": ...}].

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: GET /portfolio/{accountId}/positions/{page}
        """
        _validate_account_id(account_id)
        data = self._get(f"/portfolio/{account_id}/positions/{page}")
        return data if isinstance(data, list) else []

    def get_positions_by_conid(self, conid: int) -> list[dict[str, Any]]:
        """Position data for a specific contract across all accounts. Returns [] if not a list.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: GET /portfolio/positions/{conid}
        """
        data = self._get(f"/portfolio/positions/{conid}")
        return data if isinstance(data, list) else []

    def get_position(self, account_id: str, conid: int) -> dict[str, Any]:
        """Position for a specific account + contract pair.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: GET /portfolio/{accountId}/position/{conid}
        """
        _validate_account_id(account_id)
        return self._get(f"/portfolio/{account_id}/position/{conid}")

    def get_combo_positions(self, account_id: str) -> list[dict[str, Any]]:
        """Combo/spread positions for an account. Returns [] if not a list.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: GET /portfolio/{accountId}/combo/positions
        """
        _validate_account_id(account_id)
        data = self._get(f"/portfolio/{account_id}/combo/positions")
        return data if isinstance(data, list) else []

    def get_portfolio_allocation(self, account_ids: list[str]) -> dict[str, Any]:
        """Aggregated allocation across multiple accounts.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: POST /portfolio/allocation
        """
        return self._post("/portfolio/allocation", {"acctIds": account_ids})

    def invalidate_positions_cache(self, account_id: str) -> dict[str, Any]:
        """Force-refresh the IBKR position cache. Call before get_positions() if data looks stale.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: POST /portfolio/{accountId}/positions/invalidate
        """
        _validate_account_id(account_id)
        return self._post(f"/portfolio/{account_id}/positions/invalidate")

    # ------------------------------------------------------------------
    # Orders (read-only)
    # ------------------------------------------------------------------

    # Statuses that indicate an order is still active in the market.
    # Filled/Cancelled orders are executions, not live orders.
    _TERMINAL_STATUSES = frozenset({
        "Filled", "Cancelled", "ApiCancelled", "Expired",
    })

    def get_live_orders(self) -> list[dict[str, Any]]:
        """Working orders only (PreSubmitted, Submitted, ApiPending, PendingSubmit, PendingCancel, Inactive).

        Two-call pattern required: first call with ?force=true instantiates the subscription;
        second call returns the actual live order list.
        Inactive = order exists on IBKR but is stalled (e.g. failed risk check).

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
                https://www.interactivebrokers.com/campus/trading-lessons/request-modify-orders/
        Endpoint: GET /iserver/account/orders
        """
        self._get("/iserver/account/orders?force=true")  # instantiate subscription
        time.sleep(1)
        data = self._get("/iserver/account/orders")  # retrieve actual data
        orders = data.get("orders", data) if isinstance(data, dict) else data
        if not isinstance(orders, list):
            return []
        return [o for o in orders if o.get("status") and o.get("status") not in self._TERMINAL_STATUSES]

    def get_order_status(self, order_id: str) -> dict[str, Any]:
        """Full order details for a specific order ID.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: GET /iserver/account/order/status/{orderId}
        """
        return self._get(f"/iserver/account/order/status/{order_id}")

    def get_trades(self) -> list[dict[str, Any]]:
        """Recent trade executions visible in the current CP API session (~6 days lookback).

        Returns trades for the account for current day and up to six previous days.
        It is advised to call this endpoint once per session (per official docs).

        ## ?days parameter (officially documented, verified 2026-06-26)
        Specify the number of days to receive executions for, up to a maximum of 7 days.
        If unspecified, only the current day is returned. We always pass days=7 for
        maximum lookback.

        "Currently selected account" in the IBKR docs refers to multi-account users
        who need to explicitly select an account. Single-account users: all trades on
        the account appear regardless of where they were placed (CP API, mobile, TWS).

        ## When this is NOT the right tool
        - Full history beyond 7 days → use FlexQueryClient.fetch_trades (T+1, all origins)

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: GET /iserver/account/trades
        """
        # days=7 requests maximum lookback; without it IBKR returns today's session only
        data = self._get("/iserver/account/trades?days=7")
        return data if isinstance(data, list) else []

    # ------------------------------------------------------------------
    # Portfolio Analyst
    # ------------------------------------------------------------------

    def get_pa_periods(self, account_ids: list[str]) -> list[str]:
        """Available period strings for Portfolio Analyst queries.

        Documented period values (verified 2026-06-26): "1D", "7D", "MTD", "1M", "YTD", "1Y".
        The response object includes a `{Period Value}` key per period, each containing
        nav (NAV data), cps (cumulative performance), freq, dates, and startNav.

        Response extraction handles multiple observed shapes:
        - list of strings: returned directly
        - dict with 'Period' key: extract the list
        - dict with 'allPeriods' key: extract the list

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: POST /pa/allperiods
        """
        data = self._post("/pa/allperiods", {"acctIds": account_ids})
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("Period", "allPeriods", "periods", "period"):
                val = data.get(key)
                if isinstance(val, list):
                    return val
        return []

    def get_pa_performance(self, account_ids: list[str], period: str) -> dict[str, Any]:
        """NAV performance for the given period.

        Valid periods: "last7days", "last30days", "ytd", "last365days", "alltime".

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: POST /pa/performance
        """
        return self._post("/pa/performance", {"acctIds": account_ids, "period": period})

    def get_pa_transactions(self, account_ids: list[str], period: str) -> list[dict[str, Any]]:
        """Transaction history from IBKR Portfolio Analyst — all origins, not session-scoped.

        ## Coverage
        Portfolio Analyst uses IBKR's back-office data. Unlike /iserver/account/trades,
        it includes transactions from all origins: CP API, mobile app, TWS, and web portal.
        It is not scoped to the current session.

        ## days parameter (officially documented, verified 2026-06-26)
        Specify the number of days to receive transaction data for. Defaults to 90 days
        of transaction history if unspecified.

        ## Availability
        PA uses IBKR back-office data. Timing relative to same-day execution is not
        stated in the official docs. Observed: same-day fills appear to be accessible,
        but this has not been confirmed across all trade origins and time zones.

        ## Period values
        Valid period strings come from /pa/allperiods (get_pa_periods).
        Documented values: "1D", "7D", "MTD", "1M", "YTD", "1Y".
        Use get_pa_periods first to confirm what IBKR returns for your account.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: POST /pa/transactions
        """
        data = self._post("/pa/transactions", {"acctIds": account_ids, "period": period})
        return data if isinstance(data, list) else []

    # ------------------------------------------------------------------
    # Scanner
    # ------------------------------------------------------------------

    def get_scanner_params(self) -> dict[str, Any]:
        """Available scanner types and filter parameters.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: GET /iserver/scanner/params
        """
        return self._get("/iserver/scanner/params")

    def run_iserver_scanner(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Run a scanner with full parameter control. Returns [] if no contracts matched.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
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
        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#fyi-notifications
        Endpoint: GET /fyi/notifications
        """
        max_results = min(max(1, max_results), 10)
        data = self._get("/fyi/notifications", {"max": max_results})
        return data if isinstance(data, list) else []

    def get_unread_count(self) -> int:
        """Number of unread FYI notifications.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: GET /fyi/unreadnumber
        """
        data = self._get("/fyi/unreadnumber")
        return data.get("unreadNumber", 0) if isinstance(data, dict) else 0

    def get_delivery_options(self) -> dict[str, Any]:
        """Notification delivery channel configuration.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: GET /fyi/deliveryoptions
        """
        return self._get("/fyi/deliveryoptions")

    def get_mta_alert(self) -> dict[str, Any]:
        """Mobile Trading Alerts — account-level watchdog alerts.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: GET /iserver/account/mta
        """
        return self._get("/iserver/account/mta")

    def get_alerts(self, account_id: str) -> list[dict[str, Any]]:
        """All price alerts configured on the account. The orderId field is the alert ID.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
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

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: GET /iserver/account/watchlists
        """
        data = self._get("/iserver/account/watchlists")
        return data if isinstance(data, list) else []

    def get_watchlist(self, watchlist_id: str) -> dict[str, Any]:
        """Contents of a specific watchlist.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: GET /iserver/account/watchlist/{watchlistId}
        """
        return self._get(f"/iserver/account/watchlist/{watchlist_id}")

    # ------------------------------------------------------------------
    # Events Contracts
    # ------------------------------------------------------------------

    def get_event_contracts(self, conids: list[int]) -> list[dict[str, Any]]:
        """Event-based contracts (e.g. political outcome contracts). Returns [] if not a list.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: GET /events/contracts
        """
        data = self._get("/events/contracts", {"conids": ",".join(str(c) for c in conids)})
        return data if isinstance(data, list) else []

    def get_event_contract(self, conid: int) -> dict[str, Any]:
        """Details for a specific event contract.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
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

        US Futures (secType=FUT): caller must include manualIndicator=true in the order dict.
        Required since May 1, 2025 for CME Group Rule 536-B compliance. IBKR returns an
        error without it for futures orders.
        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/web-api-changelog/

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
                https://www.interactivebrokers.com/campus/trading-lessons/request-modify-orders/
        Endpoint: POST /iserver/account/{accountId}/orders
        """
        _validate_account_id(account_id)
        symbol = order.get("ticker", order.get("symbol", "UNKNOWN"))
        side = order.get("side", "?")
        qty = order.get("quantity", "?")
        require_touch_id(f"IBKR: Place order — {side} {qty} {symbol}")
        confirm_order_dialog(order, account_id)
        data = self._post(f"/iserver/account/{account_id}/orders", {"orders": [order]})
        return data if isinstance(data, list) else []

    def modify_order(self, account_id: str, order_id: str, order: dict[str, Any]) -> dict[str, Any]:
        """Modify an existing order. Requires Touch ID (Gate 1) + tkinter dialog (Gate 2).

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
                https://www.interactivebrokers.com/campus/trading-lessons/request-modify-orders/
        Endpoint: POST /iserver/account/{accountId}/order/{orderId}
        """
        _validate_account_id(account_id)
        require_touch_id(f"IBKR: Modify order {order_id}")
        confirm_modify_dialog(order_id, order, account_id)
        return self._post(f"/iserver/account/{account_id}/order/{order_id}", order)

    def cancel_order(self, account_id: str, order_id: str) -> dict[str, Any]:
        """Cancel an order. Requires Touch ID (Gate 1) + tkinter confirmation dialog (Gate 2).

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
                https://www.interactivebrokers.com/campus/trading-lessons/request-modify-orders/
        Endpoint: DELETE /iserver/account/{accountId}/order/{orderId}
        """
        _validate_account_id(account_id)
        require_touch_id(f"IBKR: Cancel order {order_id}")
        confirm_cancel_dialog(order_id, account_id)
        url = f"{self._base}/iserver/account/{account_id}/order/{order_id}"
        resp = with_retry(lambda: self._session.delete(url, timeout=30))
        return resp.json()

    def reply_order(self, reply_id: str, ibkr_confirmed: bool = True) -> list[dict[str, Any]]:
        """Confirm an order requiring an explicit IBKR reply (e.g. after a warning).

        Requires Touch ID (Gate 1) + tkinter dialog (Gate 2).

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
                https://www.interactivebrokers.com/campus/trading-lessons/request-modify-orders/
        Endpoint: POST /iserver/reply/{replyId}
        """
        require_touch_id(f"IBKR: Confirm order reply {reply_id}")
        confirm_reply_dialog(reply_id)
        data = self._post(f"/iserver/reply/{reply_id}", {"confirmed": ibkr_confirmed})
        return data if isinstance(data, list) else []

    def get_order_preview(self, account_id: str, order: dict[str, Any]) -> dict[str, Any]:
        """Whatif order preview — cost, commission, margin impact. Read-only, no security gates.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: POST /iserver/account/{accountId}/orders/whatif
        """
        _validate_account_id(account_id)
        return self._post(f"/iserver/account/{account_id}/orders/whatif", {"orders": [order]})

    # ------------------------------------------------------------------
    # Alerts (write)
    # ------------------------------------------------------------------

    def get_alert(self, account_id: str, alert_id: str) -> dict[str, Any]:
        """Full details for a specific alert by ID.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: GET /iserver/account/{accountId}/alert/{alertId}
        """
        _validate_account_id(account_id)
        return self._get(f"/iserver/account/{account_id}/alert/{alert_id}")

    def create_alert(self, account_id: str, alert: dict[str, Any]) -> dict[str, Any]:
        """Create a price alert. The alert dict must match the IBKR alert payload schema.

        Use ClaudeToolkit.execute("create_price_alert", ...) instead — it resolves
        conid and exchange automatically.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: POST /iserver/account/{accountId}/alert
        """
        _validate_account_id(account_id)
        return self._post(f"/iserver/account/{account_id}/alert", alert)

    def delete_alert(self, account_id: str, alert_id: str) -> dict[str, Any]:
        """Delete an alert permanently.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: DELETE /iserver/account/{accountId}/alert/{alertId}
        """
        _validate_account_id(account_id)
        url = f"{self._base}/iserver/account/{account_id}/alert/{alert_id}"
        resp = with_retry(lambda: self._session.delete(url, timeout=30))
        return resp.json()

    def activate_alert(self, account_id: str, alert_id: str, activate: bool = True) -> dict[str, Any]:
        """Toggle alert on (activate=True) or off (activate=False) without deleting it.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: POST /iserver/account/{accountId}/alert/activate
        """
        _validate_account_id(account_id)
        return self._post(f"/iserver/account/{account_id}/alert/activate", {"alertId": alert_id, "alertActive": int(activate)})

    # ------------------------------------------------------------------
    # Watchlists (write)
    # ------------------------------------------------------------------

    def create_watchlist(self, name: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
        """Create a new watchlist. rows is a list of {"C": conid} objects.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: POST /iserver/account/watchlist
        """
        return self._post("/iserver/account/watchlist", {"id": name, "name": name, "rows": rows})

    def delete_watchlist(self, watchlist_id: str) -> dict[str, Any]:
        """Delete a watchlist permanently.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: DELETE /iserver/account/watchlist/{watchlistId}
        """
        url = f"{self._base}/iserver/account/watchlist/{watchlist_id}"
        resp = with_retry(lambda: self._session.delete(url, timeout=30))
        return resp.json()

    # ------------------------------------------------------------------
    # FYI (write)
    # ------------------------------------------------------------------

    def mark_notification_read(self, notification_id: str) -> dict[str, Any]:
        """Mark a FYI notification as read.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: POST /fyi/notifications/{notificationId}/read
        """
        return self._post(f"/fyi/notifications/{notification_id}/read")

    def update_delivery_option(self, device_id: str, option: str, enabled: bool) -> dict[str, Any]:
        """Enable or disable a notification delivery channel.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: POST /fyi/deliveryoptions/{option}
        """
        return self._post(f"/fyi/deliveryoptions/{option}", {"deviceId": device_id, "enabled": enabled})

    # ------------------------------------------------------------------
    # Account / Admin
    # ------------------------------------------------------------------

    def switch_account(self, account_id: str) -> dict[str, Any]:
        """Switch the active account. For advisors and family accounts.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: POST /iserver/account
        """
        _validate_account_id(account_id)
        return self._post("/iserver/account", {"acctId": account_id})

    def get_pnl(self) -> dict[str, Any]:
        """Real-time partitioned P&L — daily, unrealized, realized — across all positions.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: GET /iserver/account/pnl/partitioned
        """
        return self._get("/iserver/account/pnl/partitioned")

    def logout(self) -> dict[str, Any]:
        """End the current IBKR session.

        Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
        Endpoint: POST /logout
        """
        return self._post("/logout")
