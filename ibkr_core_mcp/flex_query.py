from __future__ import annotations
import time
import defusedxml.ElementTree as ET
from datetime import date
from typing import TYPE_CHECKING

import requests

from ibkr_core_mcp.config import Config
from ibkr_core_mcp.exceptions import FlexQueryError

if TYPE_CHECKING:
    from ibkr_core_mcp.cache import GDriveCache
    from ibkr_core_mcp.store import SQLiteStore

_BASE_URL = "https://gdcdyn.interactivebrokers.com/Universal/servlet/FlexStatementService"
_ALLOWED_URL_PREFIX = "https://gdcdyn.interactivebrokers.com/"
_MAX_POLL_RETRIES = 5
_POLL_SLEEP = 3


class FlexQueryClient:
    """Fetches historical account data from IBKR Flex Web Service."""

    def __init__(self, config: Config, store: "SQLiteStore", cache: "GDriveCache") -> None:
        self._config = config
        self._store = store
        self._cache = cache

    def fetch_trades(self, account_id: str) -> list[dict]:
        """Full workflow: fetch → parse → upsert SQLite → save GDrive parquet."""
        import pandas as pd

        ref_code, url = self._send_request()
        xml_text = self._get_statement(url, ref_code)
        trades = self._parse_trades(xml_text)

        self._store.upsert_trades(trades)

        if trades:
            df = pd.DataFrame(trades)
            today = date.today().isoformat()
            self._cache.save(df, "FLEX_TRADES", "ALL", account_id, today)

        return trades

    def _send_request(self) -> tuple[str, str]:
        """Step 1: Send flex query request, return (reference_code, statement_url)."""
        resp = requests.get(
            _BASE_URL,
            params={"t": self._config.flex_token, "q": self._config.flex_query_id, "v": "3"},
            timeout=30,
        )
        if resp.status_code != 200:
            raise FlexQueryError(f"Flex SendRequest HTTP {resp.status_code}")

        root = ET.fromstring(resp.content)
        status = root.findtext("Status") or ""
        ref_code = root.findtext("ReferenceCode") or ""
        url = root.findtext("Url") or ""

        if status not in ("Success", "WhenAvailable") or not ref_code:
            raise FlexQueryError(f"Flex SendRequest unexpected response: status={status!r}")
        if not url:
            raise FlexQueryError("Flex SendRequest did not return a statement URL")
        if not url.startswith(_ALLOWED_URL_PREFIX):
            raise FlexQueryError(f"Flex SendRequest returned unexpected URL: {url!r}")

        return ref_code, url

    def _get_statement(self, url: str, reference_code: str) -> str:
        """Step 2: Poll until statement is ready, return XML string.

        URL allowlist enforcement is the responsibility of _send_request, which
        validates every URL returned by the IBKR API before passing it here.
        fetch_trades() is the only public entry point and always calls
        _send_request first, so the invariant is maintained at the call-graph
        level rather than repeated here.
        """
        for attempt in range(_MAX_POLL_RETRIES):
            resp = requests.get(
                url,
                params={"t": self._config.flex_token, "q": reference_code, "v": "3"},
                timeout=60,
            )
            if resp.status_code != 200:
                raise FlexQueryError(f"Flex GetStatement HTTP {resp.status_code}")

            root = ET.fromstring(resp.content)
            status = root.findtext("Status")
            if status == "WhenAvailable":
                if attempt < _MAX_POLL_RETRIES - 1:
                    time.sleep(_POLL_SLEEP)
                    continue
                raise FlexQueryError(
                    f"Flex statement not ready after {_MAX_POLL_RETRIES} attempts"
                )

            return resp.content.decode("utf-8", errors="replace")

        raise FlexQueryError(f"Flex statement not ready after {_MAX_POLL_RETRIES} attempts")

    def _parse_trades(self, xml_text: str) -> list[dict]:
        """Parse <Trade> elements from Flex XML into dicts matching trades table schema."""
        root = ET.fromstring(xml_text)
        trades = []
        for trade_el in root.iter("Trade"):
            raw_dt = trade_el.get("dateTime", "")
            time_iso = _parse_flex_datetime(raw_dt)
            trades.append({
                "execution_id": trade_el.get("tradeID", ""),
                "symbol": (trade_el.get("symbol") or "").upper(),
                "side": trade_el.get("buySell", ""),
                "size": _safe_float(trade_el.get("quantity")),
                "price": _safe_float(trade_el.get("tradePrice")),
                "time": time_iso,
                "commission": abs(_safe_float(trade_el.get("ibCommission"))),
                "account": trade_el.get("accountId", ""),
            })
        return trades


def _parse_flex_datetime(raw: str) -> str:
    """Convert IBKR Flex dateTime 'YYYYMMDD;HHMMSS' to ISO 'YYYY-MM-DDTHH:MM:SS'."""
    try:
        date_part, time_part = raw.split(";")
        return f"{date_part[:4]}-{date_part[4:6]}-{date_part[6:8]}T{time_part[:2]}:{time_part[2:4]}:{time_part[4:6]}"
    except ValueError as exc:
        raise FlexQueryError(f"Unexpected Flex dateTime format: {raw!r}") from exc


def _safe_float(val: str | None) -> float:
    try:
        return float(val or 0)
    except (ValueError, TypeError):
        return 0.0
