from __future__ import annotations

import time
from datetime import date
from typing import TYPE_CHECKING, Any

import defusedxml.ElementTree as ET
import requests

from ibkr_core_mcp.config import Config
from ibkr_core_mcp.exceptions import FlexQueryError

if TYPE_CHECKING:
    from ibkr_core_mcp.cache import GDriveCache
    from ibkr_core_mcp.store import SQLiteStore

_BASE_URL = "https://gdcdyn.interactivebrokers.com/Universal/servlet/FlexStatementService.SendRequest"
_ALLOWED_URL_PREFIX = "https://gdcdyn.interactivebrokers.com/"
_MAX_POLL_RETRIES = 5
_POLL_SLEEP = 3


class FlexQueryClient:
    """Fetches historical account data from IBKR Flex Web Service."""

    def __init__(self, config: Config, store: SQLiteStore, cache: GDriveCache) -> None:
        self._config = config
        self._store = store
        self._cache = cache

    def import_from_file(self, xml_path: str) -> list[dict[str, Any]]:
        """Parse a locally downloaded Flex XML file → upsert SQLite → return trades.

        Use for historical backfill. Duplicates are handled by upsert (idempotent).
        Trade archive data lives in SQLite; the parquet cache is for OHLCV market data.
        """
        from pathlib import Path

        xml_text = Path(xml_path).read_text(encoding="utf-8", errors="replace")
        trades = self._parse_trades(xml_text)
        self._store.upsert_trades(trades)
        return trades

    def sync_archive_from_drive(self) -> dict[str, Any]:
        """Download all XML files from account_data/ on Drive and import them into SQLite.

        Returns a summary: files processed, total trades upserted, and coverage stats.
        """
        import tempfile
        from pathlib import Path

        files = self._cache.download_account_files(extension=".xml")
        if not files:
            return {"files": 0, "trades": 0, "coverage": None}

        total_trades = 0
        processed = []
        for filename, content in files:
            with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            try:
                trades = self.import_from_file(tmp_path)
                total_trades += len(trades)
                dates = sorted(t["time"][:10] for t in trades) if trades else []
                processed.append({
                    "file": filename,
                    "trades": len(trades),
                    "range": f"{dates[0]} → {dates[-1]}" if dates else "no trades",
                })
            finally:
                Path(tmp_path).unlink(missing_ok=True)

        coverage = self._store.get_trade_date_coverage()
        return {"files": len(processed), "trades": total_trades, "processed": processed, "coverage": coverage}

    def fetch_trades(self, account_id: str) -> list[dict[str, Any]]:
        """Full workflow: fetch → parse → upsert SQLite → save GDrive parquet."""
        ref_code, url = self._send_request()
        xml_text = self._get_statement(url, ref_code)
        trades = self._parse_trades(xml_text)
        self._store.upsert_trades(trades)
        self._save_trades_to_cache(trades, "FLEX_TRADES")
        return trades

    def _save_trades_to_cache(self, trades: list[dict[str, Any]], cache_key: str) -> None:
        """Persist a trade list to the GDrive parquet cache."""
        if not trades:
            return
        import pandas as pd

        account_id = trades[0].get("account", "UNKNOWN")
        df = pd.DataFrame(trades)
        self._cache.save(df, cache_key, "ALL", account_id, date.today().isoformat())

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

        if status == "Fail":
            error_code = root.findtext("ErrorCode") or "?"
            error_msg = root.findtext("ErrorMessage") or "unknown"
            if error_code == "1001":
                raise FlexQueryError(
                    "IBKR rate limit (error 1001) — wait ~5 minutes and retry. "
                    "This happens when the same query is called too frequently."
                )
            raise FlexQueryError(f"Flex error {error_code}: {error_msg}")
        if status == "Warn":
            error_code = root.findtext("ErrorCode") or "?"
            error_msg = root.findtext("ErrorMessage") or "unknown"
            if error_code == "1025":
                raise FlexQueryError(
                    "IBKR locked this query (error 1025 — too many failed attempts). "
                    "Regenerate your Flex token: IBKR → Reports → Flex Web Service → regenerate token, "
                    "update IBKR_FLEX_TOKEN in .env, then restart ClaudIA."
                )
            raise FlexQueryError(f"Flex Warn {error_code}: {error_msg}")
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

    def _parse_trades(self, xml_text: str) -> list[dict[str, Any]]:
        """Parse <Trade> elements from Flex XML into dicts matching trades table schema.

        Validates required fields per record. Skips invalid records and logs them.
        Raises FlexQueryError if more than 20% of records are invalid (likely corrupt file).
        """
        import logging
        log = logging.getLogger(__name__)

        root = ET.fromstring(xml_text)
        trades: list[dict[str, Any]] = []
        skipped: list[str] = []

        for trade_el in root.iter("Trade"):
            execution_id = (trade_el.get("tradeID") or "").strip()
            symbol = (trade_el.get("symbol") or "").upper().strip()
            side = (trade_el.get("buySell") or "").strip()
            raw_dt = trade_el.get("dateTime", "")

            if not execution_id:
                skipped.append(f"missing tradeID (symbol={symbol or '?'})")
                continue
            if not symbol:
                skipped.append(f"missing symbol (tradeID={execution_id})")
                continue
            if not side:
                skipped.append(f"missing buySell (tradeID={execution_id}, symbol={symbol})")
                continue

            try:
                time_iso = _parse_flex_datetime(raw_dt)
            except FlexQueryError as exc:
                skipped.append(str(exc))
                continue

            # tradePnl is IBKR's realized P&L for this execution (account currency).
            # assetCategory: STK, FUT, OPT, BOND, CASH, etc.
            raw_pnl = trade_el.get("tradePnl") or trade_el.get("fifoPnlRealized")
            trades.append({
                "execution_id": execution_id,
                "symbol": symbol,
                "side": side,
                "size": _safe_float(trade_el.get("quantity")),
                "price": _safe_float(trade_el.get("tradePrice")),
                "time": time_iso,
                "commission": abs(_safe_float(trade_el.get("ibCommission"))),
                "account": trade_el.get("accountId", ""),
                "asset_class": (trade_el.get("assetCategory") or "").strip().upper(),
                "realized_pnl": _safe_float(raw_pnl) if raw_pnl else None,
            })

        total = len(trades) + len(skipped)
        if skipped:
            log.warning("Skipped %d/%d invalid trade records: %s", len(skipped), total, skipped[:5])
        if total > 0 and len(skipped) / total > 0.20:
            raise FlexQueryError(
                f"Data integrity failure: {len(skipped)}/{total} records invalid — possible corrupt file. "
                f"First errors: {skipped[:3]}"
            )
        return trades


def _parse_flex_datetime(raw: str) -> str:
    """Convert IBKR Flex dateTime to ISO 'YYYY-MM-DDTHH:MM:SS'.

    Handles formats:
      'YYYYMMDD;HHMMSS'  — standard with semicolon separator
      'YYYYMMDD'         — date-only (older exports or date-range queries)
    """
    if ";" in raw:
        date_part, time_part = raw.split(";", 1)
        return f"{date_part[:4]}-{date_part[4:6]}-{date_part[6:8]}T{time_part[:2]}:{time_part[2:4]}:{time_part[4:6]}"
    if len(raw) == 8 and raw.isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}T00:00:00"
    raise FlexQueryError(f"Unexpected Flex dateTime format: {raw!r}")


def _safe_float(val: str | None) -> float:
    try:
        return float(val or 0)
    except (ValueError, TypeError):
        return 0.0
