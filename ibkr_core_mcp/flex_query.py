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

# Official IBKR Flex Web Service endpoints.
# Source: https://www.ibkrguides.com/clientportal/performanceandstatements/flex3.htm
_BASE_URL = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/SendRequest"

# IBKR Flex GetStatement URL allowlist (SSRF guard).
# Official docs show ndcdyn for both steps, but live API returns gdcdyn for GetStatement.
# Both are legitimate IBKR Flex subdomains — allowlist covers both.
# Observed 2026-06-26: SendRequest → ndcdyn; GetStatement URL returned by IBKR → gdcdyn.
_ALLOWED_URL_PREFIXES = (
    "https://ndcdyn.interactivebrokers.com/",
    "https://gdcdyn.interactivebrokers.com/",
)

# Required by IBKR for programmatic access (documented requirement).
_REQUEST_HEADERS = {"User-Agent": "Python/3"}
_MAX_POLL_RETRIES = 5
_POLL_SLEEP = 3

# Official IBKR Flex Web Service Version 3 error codes.
# Source: https://www.ibkrguides.com/clientportal/performanceandstatements/flex3error.htm
# Format: code → (short_description, action)
_FLEX_ERROR_CODES: dict[str, tuple[str, str]] = {
    "1001": (
        "Statement could not be generated at this time.",
        "Transient — retry in a few minutes. If consistently failing, verify the Flex query "
        "is saved and enabled in IBKR (Reports → Flex Queries).",
    ),
    "1003": (
        "Statement is not available.",
        "The report for this date range does not exist or has not been generated.",
    ),
    "1004": (
        "Statement is incomplete at this time.",
        "Transient — data is still being assembled, retry shortly.",
    ),
    "1005": ("Settlement data is not ready.", "Transient — retry shortly."),
    "1006": ("FIFO P/L data is not ready.", "Transient — retry shortly."),
    "1007": ("MTM P/L data is not ready.", "Transient — retry shortly."),
    "1008": ("MTM and FIFO P/L data are not ready.", "Transient — retry shortly."),
    "1009": (
        "Server overload preventing statement generation.",
        "Transient — IBKR servers busy, retry later.",
    ),
    "1010": (
        "Legacy Flex Queries are no longer supported.",
        "Action required: convert your query to Activity Flex in IBKR Account Management.",
    ),
    "1011": (
        "Service account is inactive.",
        "Contact IBKR — the account linked to this query is inactive.",
    ),
    "1012": (
        "Token has expired.",
        "Regenerate token: IBKR → Reports → Flex Web Service → regenerate token, "
        "update IBKR_FLEX_TOKEN in .env.",
    ),
    "1013": (
        "IP restriction.",
        "Your IP address is not whitelisted for this token. Check the token's IP filter settings in IBKR.",
    ),
    "1014": (
        "Query is invalid.",
        "IBKR_FLEX_QUERY_ID in .env does not match a saved Flex query. "
        "Check: IBKR → Reports → Flex Queries → note the Query ID.",
    ),
    "1015": (
        "Token is invalid.",
        "IBKR_FLEX_TOKEN in .env is wrong or has been regenerated. "
        "Get the current token: IBKR → Reports → Flex Web Service.",
    ),
    "1016": (
        "Account is invalid.",
        "The account associated with this Flex query is invalid or inaccessible.",
    ),
    "1017": (
        "Reference code is invalid.",
        "Internal polling error — retry the sync. If persistent, the statement URL may have expired.",
    ),
    "1018": (
        "Too many requests from this token.",
        "Rate limit: max 1 request/second, 10 requests/minute per token. Wait 1 minute and retry.",
    ),
    "1019": (
        "Statement generation in progress.",
        "Transient — IBKR is generating the report, retry in 30 seconds.",
    ),
    "1020": (
        "Invalid request or unable to validate request.",
        "Check that IBKR_FLEX_TOKEN and IBKR_FLEX_QUERY_ID are correctly formatted in .env.",
    ),
    "1021": (
        "Statement could not be retrieved at this time.",
        "Transient — retry shortly.",
    ),
    # 1025 is not in the official table but has been observed in practice.
    # IBKR returns it as a Warn when a token has been locked after repeated failures.
    "1025": (
        "Query locked due to too many failed attempts.",
        "Regenerate your Flex token: IBKR → Reports → Flex Web Service → regenerate token, "
        "update IBKR_FLEX_TOKEN in .env, then restart ClaudIA.",
    ),
}


class FlexQueryClient:
    """Fetches historical trade data from the IBKR Flex Web Service.

    ## What Flex covers
    Flex Activity Statements contain the complete, authoritative execution record for the
    account — all trade origins are included (CP API, mobile app, TWS, web portal).
    Source: https://www.ibkrguides.com/orgportal/performanceandstatements/flex.htm

    ## Availability timing (T+1)
    Flex data is generated by IBKR's end-of-day processing. Today's trades are NEVER
    present in Flex on the same calendar day they execute. The report for a given trade
    date becomes available the following calendar day after IBKR's overnight batch runs.
    This T+1 behavior is observed; IBKR does not publish a specific cutoff time.

    ## Date range
    Via the Flex Web Service API, the `fd` (from date) and `td` (to date) parameters
    accept YYYYMMDD format with a maximum range of 365 days per request.
    The portal UI covers up to the 4 previous calendar years plus the current year.
    Source: https://www.ibkrguides.com/clientportal/performanceandstatements/flex3.htm

    ## What Flex does NOT cover
    - Today's intraday trades (use the CP API `/iserver/account/trades` for same-day fills,
      but note that endpoint is session-scoped and may miss mobile/TWS-placed orders)
    - Real-time prices or positions
    """

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

    def fetch_trades(
        self,
        account_id: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """Full workflow: fetch → parse → upsert SQLite → archive XML to Drive + log manifest.

        After a successful upsert, _archive_and_log uploads the raw XML to Drive
        account_data/ and writes a row to flex_import_log with SHA-256, trade_id_count,
        raw_trade_count, and verified_at set to now (import is complete by definition).
        The archive and manifest steps are non-fatal — a Drive failure does not abort
        a successful sync; trades are already in SQLite before the upload is attempted.

        start_date / end_date override the date range configured in the Flex query.
        Format: YYYYMMDD (e.g. "20260101"). Max range: 365 days.
        Source: https://www.ibkrguides.com/clientportal/performanceandstatements/flex3.htm
        (fd / td optional URL parameters)
        """
        if start_date is not None:
            _validate_flex_date(start_date, "start_date (fd)")
        if end_date is not None:
            _validate_flex_date(end_date, "end_date (td)")
        ref_code, url = self._send_request(start_date=start_date, end_date=end_date)
        xml_text = self._get_statement(url, ref_code)
        trades = self._parse_trades(xml_text)
        self._store.upsert_trades(trades)
        try:
            self._archive_and_log(xml_text, account_id, ref_code)
        except Exception:
            # Drive archive and manifest log are supplementary — trades already in SQLite.
            # A Drive auth failure must not abort a successful sync.
            pass
        return trades

    def _archive_and_log(self, xml_text: str, account_id: str, ref_code: str) -> None:
        """Archive raw Flex XML to Drive account_data/ and record it in the import manifest.

        Filename: flex_{account_id}_{date}_{ref_code}.xml  (auto-synced naming convention)
        - Uploads to account_data/ on Drive (not market_data/ — this is account data).
        - Computes SHA-256 of the XML bytes for future hash-based integrity checks.
        - Extracts unique tradeID count and raw <Trade> element count for the manifest.
        - raw_trade_count != trade_id_count would indicate within-file duplicate tradeIDs
          (should never occur from IBKR, flagged transparently if it does).
        - Sets verified_at = import timestamp because the tradeIDs were just upserted
          to SQLite; the import is complete at this point by definition.
        """
        import hashlib
        from datetime import UTC, datetime

        filename = f"flex_{account_id}_{date.today().isoformat()}_{ref_code}.xml"
        xml_bytes = xml_text.encode("utf-8")

        self._cache.upload_account_file_bytes(xml_bytes, filename, mimetype="application/xml")

        sha256 = hashlib.sha256(xml_bytes).hexdigest()
        unique_ids, raw_count = FlexQueryClient.extract_execution_ids(xml_text)
        now = datetime.now(UTC).isoformat()
        self._store.log_flex_import(
            filename=filename,
            sha256=sha256,
            trade_id_count=len(unique_ids),
            raw_trade_count=raw_count,
            source="auto",
            imported_at=now,
            verified_at=now,  # tradeIDs were just upserted — import is verified at this moment
        )

    def _send_request(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> tuple[str, str]:
        """Step 1: Send flex query request, return (reference_code, statement_url).

        start_date maps to the fd (from date) parameter; end_date maps to td (to date).
        Both are YYYYMMDD strings, pre-validated by fetch_trades().
        Source: https://www.ibkrguides.com/clientportal/performanceandstatements/flex3.htm
        """
        params: dict[str, str] = {
            "t": self._config.flex_token,
            "q": self._config.flex_query_id,
            "v": "3",
        }
        if start_date is not None:
            params["fd"] = start_date
        if end_date is not None:
            params["td"] = end_date
        resp = requests.get(
            _BASE_URL,
            params=params,
            headers=_REQUEST_HEADERS,
            timeout=30,
        )
        if resp.status_code != 200:
            raise FlexQueryError(f"Flex SendRequest HTTP {resp.status_code}")

        root = ET.fromstring(resp.content)
        status = root.findtext("Status") or ""
        ref_code = root.findtext("ReferenceCode") or ""
        url = root.findtext("Url") or ""

        if status in ("Fail", "Warn"):
            error_code = (root.findtext("ErrorCode") or "?").strip()
            error_msg = (root.findtext("ErrorMessage") or "").strip()
            desc, action = _FLEX_ERROR_CODES.get(error_code, ("Unknown error.", "Check IBKR Flex configuration."))
            raise FlexQueryError(
                f"Flex error {error_code}: {desc} {action}"
                + (f" (IBKR message: {error_msg})" if error_msg else "")
            )
        if status not in ("Success", "WhenAvailable") or not ref_code:
            raise FlexQueryError(f"Flex SendRequest unexpected response: status={status!r}")
        if not url:
            raise FlexQueryError("Flex SendRequest did not return a statement URL")
        if not any(url.startswith(p) for p in _ALLOWED_URL_PREFIXES):
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
                headers=_REQUEST_HEADERS,
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

    @staticmethod
    def extract_execution_ids(xml_text: str) -> tuple[set[str], int]:
        """Extract tradeID values from a Flex XML document.

        Lightweight — reads only the tradeID attribute, does not parse full records.
        Used by verify_flex_import to cross-check source XMLs against SQLite without
        re-importing or modifying any data.

        Returns:
            unique_ids  — set of non-empty tradeID strings (deduplicated).
            raw_count   — total number of <Trade> elements in the XML, including any
                          with missing or duplicate tradeIDs. If raw_count != len(unique_ids),
                          the XML contains within-file duplicate or blank tradeIDs, which
                          should never occur from IBKR but is flagged for transparency.
        """
        root = ET.fromstring(xml_text)
        unique_ids: set[str] = set()
        raw_count = 0
        for trade_el in root.iter("Trade"):
            raw_count += 1
            eid = (trade_el.get("tradeID") or "").strip()
            if eid:
                unique_ids.add(eid)
        return unique_ids, raw_count

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


def _validate_flex_date(value: str, name: str) -> None:
    """Raise ValueError if value is not a valid YYYYMMDD date string."""
    if not (len(value) == 8 and value.isdigit()):
        raise ValueError(
            f"Flex {name} must be in YYYYMMDD format (8 digits), got {value!r}. "
            f"Source: https://www.ibkrguides.com/clientportal/performanceandstatements/flex3.htm"
        )


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
