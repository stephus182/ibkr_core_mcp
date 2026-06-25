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


def _validate_account_id(account_id: str) -> None:
    """Raise ConfigError if account_id is not a valid IBKR account ID."""
    if not account_id or not _ACCOUNT_ID_RE.fullmatch(account_id):
        raise ConfigError(
            f"Invalid account_id {account_id!r}: must be 4–12 uppercase alphanumeric chars."
        )


class IBKRClient:
    """Wraps all IBKR Client Portal API endpoints. Returns raw dicts."""

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

    def _refresh_auth(self, auth: AuthStrategy) -> None:
        auth.apply(self._session)

    # Session
    def ping(self) -> bool:
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
        return self._get("/iserver/auth/status")

    def tickle(self) -> bool:
        try:
            resp = self._session.post(f"{self._base}/tickle", timeout=5)
            return resp.status_code == 200
        except Exception:
            return False

    def reauthenticate(self) -> dict[str, Any]:
        return self._post("/iserver/reauthenticate")

    def validate_sso(self) -> dict[str, Any]:
        return self._post("/sso/validate")

    # Market Data
    def get_market_history(self, conid: int, period: str = "1Y", bar: str = "1d", outside_rth: bool = False) -> dict[str, Any]:
        return self._get("/iserver/marketdata/history", {"conid": conid, "period": period, "bar": bar, "outsideRth": str(outside_rth).lower()})

    def get_market_snapshot(self, conids: list[int], fields: list[str] | None = None) -> list[dict[str, Any]]:
        field_str = ",".join(fields or ["31", "55", "70", "71", "84", "86"])
        data = self._get("/iserver/marketdata/snapshot", {"conids": ",".join(str(c) for c in conids), "fields": field_str})
        return data if isinstance(data, list) else []

    def get_market_data_fields(self) -> dict[str, Any]:
        return self._get("/iserver/marketdata/fields")

    def get_market_data_periods(self) -> dict[str, Any]:
        return self._get("/iserver/marketdata/periods")

    def get_market_data_bars(self) -> dict[str, Any]:
        return self._get("/iserver/marketdata/bars")

    def get_hmds_history(self, conid: int, period: str = "1Y", bar: str = "1d", outside_rth: bool = False) -> dict[str, Any]:
        return self._get("/hmds/history", {"conid": conid, "period": period, "bar": bar, "outsideRth": str(outside_rth).lower()})

    def unsubscribe_market_data(self, conid: int) -> dict[str, Any]:
        return self._post("/iserver/marketdata/unsubscribe", {"conid": conid})

    def unsubscribe_all_market_data(self) -> dict[str, Any]:
        return self._post("/iserver/marketdata/unsubscribeall")

    def get_md_snapshot(self, conids: list[int], fields: list[str] | None = None) -> list[dict[str, Any]]:
        field_str = ",".join(fields or ["31", "55"])
        data = self._get("/md/snapshot", {"conids": ",".join(str(c) for c in conids), "fields": field_str})
        return data if isinstance(data, list) else []

    def get_market_data_availability(self) -> dict[str, Any]:
        return self._get("/iserver/marketdata/availability")

    # Contract / Security Definition
    def search_contract(self, symbol: str, sec_type: str = "STK") -> list[dict[str, Any]]:
        data = self._get("/iserver/secdef/search", {"symbol": symbol, "secType": sec_type})
        return data if isinstance(data, list) else []

    def get_contract_info(self, conid: int) -> dict[str, Any]:
        return self._get(f"/iserver/contract/{conid}/info")

    def get_contract_info_and_rules(self, conid: int) -> dict[str, Any]:
        return self._get(f"/iserver/contract/{conid}/info-and-rules")

    def get_contract_algos(self, conid: int) -> list[dict[str, Any]]:
        data = self._get(f"/iserver/contract/{conid}/algos")
        return data if isinstance(data, list) else []

    def get_secdef_info(self, conid: int) -> dict[str, Any]:
        return self._get("/iserver/secdef/info", {"conid": conid})

    def get_option_strikes(self, conid: int, sec_type: str, month: str, exchange: str = "SMART") -> list[float]:
        data = self._get("/iserver/secdef/strikes", {"conid": conid, "sectype": sec_type, "month": month, "exchange": exchange})
        return data.get("strike", [])

    def get_option_chain(self, symbol: str, exchange: str = "SMART", currency: str = "USD") -> dict[str, Any]:
        return self._get("/trsrv/secdef/chains", {"symbol": symbol, "exchange": exchange, "currency": currency})

    def get_bond_filters(self, symbol: str, issue_id: str) -> dict[str, Any]:
        return self._get("/iserver/secdef/bond-filters", {"symbol": symbol, "issuerId": issue_id})

    def get_futures(self, symbols: list[str]) -> list[dict[str, Any]]:
        data = self._get("/trsrv/futures", {"symbols": ",".join(symbols)})
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return [c for contracts in data.values() for c in (contracts or [])]
        return []

    def get_stocks(self, symbols: list[str]) -> list[dict[str, Any]]:
        data = self._get("/trsrv/stocks", {"symbols": ",".join(symbols)})
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return [c for contracts in data.values() for c in (contracts or [])]
        return []

    def get_trading_schedule(self, asset_class: str, symbol: str, exchange: str, exchange_filter: str = "") -> dict[str, Any]:
        params = {"assetClass": asset_class, "symbol": symbol, "exchange": exchange}
        if exchange_filter:
            params["exchangeFilter"] = exchange_filter
        return self._get("/trsrv/secdef/schedule", params)

    def get_secdef(self, conids: list[int]) -> list[dict[str, Any]]:
        data = self._get("/trsrv/secdef", {"conids": ",".join(str(c) for c in conids)})
        return data if isinstance(data, list) else []

    def get_currency_pairs(self, currency: str) -> list[dict[str, Any]]:
        data = self._get("/iserver/secdef/currency", {"currency": currency})
        return data if isinstance(data, list) else []

    def get_contract_rules(self, conid: int, is_buy: bool = True) -> dict[str, Any]:
        return self._post("/iserver/contract/rules", {"conid": conid, "isBuy": is_buy})

    # Portfolio
    def get_accounts(self) -> list[dict[str, Any]]:
        data = self._get("/portfolio/accounts")
        return data if isinstance(data, list) else []

    def get_subaccounts(self) -> list[dict[str, Any]]:
        data = self._get("/portfolio/subaccounts")
        return data if isinstance(data, list) else []

    def get_account_meta(self, account_id: str) -> dict[str, Any]:
        _validate_account_id(account_id)
        return self._get(f"/portfolio/{account_id}/meta")

    def get_account_summary(self, account_id: str) -> dict[str, Any]:
        _validate_account_id(account_id)
        return self._get(f"/portfolio/{account_id}/summary")

    def get_account_ledger(self, account_id: str) -> dict[str, Any]:
        _validate_account_id(account_id)
        return self._get(f"/portfolio/{account_id}/ledger")

    def get_account_allocation(self, account_id: str) -> dict[str, Any]:
        _validate_account_id(account_id)
        return self._get(f"/portfolio/{account_id}/allocation")

    def get_positions(self, account_id: str, page: int = 0) -> list[dict[str, Any]]:
        _validate_account_id(account_id)
        data = self._get(f"/portfolio/{account_id}/positions/{page}")
        return data if isinstance(data, list) else []

    def get_positions_by_conid(self, conid: int) -> list[dict[str, Any]]:
        data = self._get(f"/portfolio/positions/{conid}")
        return data if isinstance(data, list) else []

    def get_position(self, account_id: str, conid: int) -> dict[str, Any]:
        _validate_account_id(account_id)
        return self._get(f"/portfolio/{account_id}/position/{conid}")

    def get_combo_positions(self, account_id: str) -> list[dict[str, Any]]:
        _validate_account_id(account_id)
        data = self._get(f"/portfolio/{account_id}/combo/positions")
        return data if isinstance(data, list) else []

    def get_portfolio_allocation(self, account_ids: list[str]) -> dict[str, Any]:
        return self._post("/portfolio/allocation", {"acctIds": account_ids})

    def invalidate_positions_cache(self, account_id: str) -> dict[str, Any]:
        _validate_account_id(account_id)
        return self._post(f"/portfolio/{account_id}/positions/invalidate")

    # Orders (read-only)

    # Statuses that indicate an order is still active in the market.
    # Filled/Cancelled orders are executions, not live orders.
    _TERMINAL_STATUSES = frozenset({
        "Filled", "Cancelled", "ApiCancelled", "Expired",
    })

    def get_live_orders(self) -> list[dict[str, Any]]:
        """Return all non-terminal orders across all asset classes (equities, futures, FX).

        Inverted filter: exclude only definitively closed statuses (Filled, Cancelled,
        Expired) so unknown or asset-class-specific status strings are never silently
        dropped. force=true bypasses IBKR's server-side cache so orders placed via TWS
        or mobile are included.
        """
        data = self._get("/iserver/account/orders?force=true")
        orders = data.get("orders", data) if isinstance(data, dict) else data
        if not isinstance(orders, list):
            return []
        return [o for o in orders if o.get("status") and o.get("status") not in self._TERMINAL_STATUSES]

    def get_order_status(self, order_id: str) -> dict[str, Any]:
        return self._get(f"/iserver/account/order/status/{order_id}")

    def get_trades(self) -> list[dict[str, Any]]:
        data = self._get("/iserver/account/trades")
        return data if isinstance(data, list) else []

    # Portfolio Analyst
    def get_pa_periods(self, account_ids: list[str]) -> list[str]:
        data = self._post("/pa/allperiods", {"acctIds": account_ids})
        return data if isinstance(data, list) else []

    def get_pa_performance(self, account_ids: list[str], period: str) -> dict[str, Any]:
        return self._post("/pa/performance", {"acctIds": account_ids, "period": period})

    def get_pa_transactions(self, account_ids: list[str], period: str) -> list[dict[str, Any]]:
        data = self._post("/pa/transactions", {"acctIds": account_ids, "period": period})
        return data if isinstance(data, list) else []

    # Scanner
    def get_scanner_params(self) -> dict[str, Any]:
        return self._get("/iserver/scanner/params")

    def run_iserver_scanner(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        data = self._post("/iserver/scanner/run", params)
        contracts = data.get("contracts", data) if isinstance(data, dict) else data
        return contracts if isinstance(contracts, list) else []

    def run_hmds_scanner(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        data = self._post("/hmds/scanner", params)
        return data if isinstance(data, list) else []

    # FYI / Notifications
    def get_notifications(self, max_results: int = 10) -> list[dict[str, Any]]:
        max_results = min(max(1, max_results), 100)
        data = self._get("/fyi/notifications", {"max": max_results})
        return data if isinstance(data, list) else []

    def get_unread_count(self) -> int:
        data = self._get("/fyi/unreadnumber")
        return data.get("unreadNumber", 0) if isinstance(data, dict) else 0

    def get_delivery_options(self) -> dict[str, Any]:
        return self._get("/fyi/deliveryoptions")

    def get_mta_alert(self) -> dict[str, Any]:
        return self._get("/iserver/account/mta")

    def get_alerts(self, account_id: str) -> list[dict[str, Any]]:
        _validate_account_id(account_id)
        data = self._get(f"/iserver/account/{account_id}/alerts")
        return data if isinstance(data, list) else []

    # Watchlists (read-only)
    def get_watchlists(self) -> list[dict[str, Any]]:
        data = self._get("/iserver/account/watchlists")
        return data if isinstance(data, list) else []

    def get_watchlist(self, watchlist_id: str) -> dict[str, Any]:
        return self._get(f"/iserver/account/watchlist/{watchlist_id}")

    # Events Contracts
    def get_event_contracts(self, conids: list[int]) -> list[dict[str, Any]]:
        data = self._get("/events/contracts", {"conids": ",".join(str(c) for c in conids)})
        return data if isinstance(data, list) else []

    def get_event_contract(self, conid: int) -> dict[str, Any]:
        return self._get("/events/show", {"conid": conid})

    # Order Management (write — human auth required)
    def place_order(self, account_id: str, order: dict[str, Any]) -> list[dict[str, Any]]:
        _validate_account_id(account_id)
        symbol = order.get("ticker", order.get("symbol", "UNKNOWN"))
        side = order.get("side", "?")
        qty = order.get("quantity", "?")
        require_touch_id(f"IBKR: Place order — {side} {qty} {symbol}")
        confirm_order_dialog(order, account_id)
        data = self._post(f"/iserver/account/{account_id}/orders", {"orders": [order]})
        return data if isinstance(data, list) else []

    def modify_order(self, account_id: str, order_id: str, order: dict[str, Any]) -> dict[str, Any]:
        _validate_account_id(account_id)
        require_touch_id(f"IBKR: Modify order {order_id}")
        confirm_modify_dialog(order_id, order, account_id)
        return self._post(f"/iserver/account/{account_id}/order/{order_id}", order)

    def cancel_order(self, account_id: str, order_id: str) -> dict[str, Any]:
        _validate_account_id(account_id)
        require_touch_id(f"IBKR: Cancel order {order_id}")
        confirm_cancel_dialog(order_id, account_id)
        url = f"{self._base}/iserver/account/{account_id}/order/{order_id}"
        resp = with_retry(lambda: self._session.delete(url, timeout=30))
        return resp.json()

    def reply_order(self, reply_id: str, ibkr_confirmed: bool = True) -> list[dict[str, Any]]:
        require_touch_id(f"IBKR: Confirm order reply {reply_id}")
        confirm_reply_dialog(reply_id)
        data = self._post(f"/iserver/reply/{reply_id}", {"confirmed": ibkr_confirmed})
        return data if isinstance(data, list) else []

    def get_order_preview(self, account_id: str, order: dict[str, Any]) -> dict[str, Any]:
        _validate_account_id(account_id)
        return self._post(f"/iserver/account/{account_id}/orders/whatif", {"orders": [order]})

    # Alerts (write)
    def get_alert(self, account_id: str, alert_id: str) -> dict[str, Any]:
        _validate_account_id(account_id)
        return self._get(f"/iserver/account/{account_id}/alert/{alert_id}")

    def create_alert(self, account_id: str, alert: dict[str, Any]) -> dict[str, Any]:
        _validate_account_id(account_id)
        return self._post(f"/iserver/account/{account_id}/alert", alert)

    def delete_alert(self, account_id: str, alert_id: str) -> dict[str, Any]:
        _validate_account_id(account_id)
        url = f"{self._base}/iserver/account/{account_id}/alert/{alert_id}"
        resp = with_retry(lambda: self._session.delete(url, timeout=30))
        return resp.json()

    def activate_alert(self, account_id: str, alert_id: str, activate: bool = True) -> dict[str, Any]:
        _validate_account_id(account_id)
        return self._post(f"/iserver/account/{account_id}/alert/activate", {"alertId": alert_id, "alertActive": int(activate)})

    # Watchlists (write)
    def create_watchlist(self, name: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
        return self._post("/iserver/account/watchlist", {"id": name, "name": name, "rows": rows})

    def delete_watchlist(self, watchlist_id: str) -> dict[str, Any]:
        url = f"{self._base}/iserver/account/watchlist/{watchlist_id}"
        resp = with_retry(lambda: self._session.delete(url, timeout=30))
        return resp.json()

    # FYI (write)
    def mark_notification_read(self, notification_id: str) -> dict[str, Any]:
        return self._post(f"/fyi/notifications/{notification_id}/read")

    def update_delivery_option(self, device_id: str, option: str, enabled: bool) -> dict[str, Any]:
        return self._post(f"/fyi/deliveryoptions/{option}", {"deviceId": device_id, "enabled": enabled})

    # Account / Admin
    def switch_account(self, account_id: str) -> dict[str, Any]:
        _validate_account_id(account_id)
        return self._post("/iserver/account", {"acctId": account_id})

    def get_brokerage_accounts(self) -> dict[str, Any]:
        return self._get("/portfolio/accounts")

    def get_pnl(self) -> dict[str, Any]:
        return self._get("/iserver/account/pnl/partitioned")

    def logout(self) -> dict[str, Any]:
        return self._post("/logout")
