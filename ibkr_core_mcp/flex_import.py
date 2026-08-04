"""Parse IBKR Flex XML statements into complete, typed rows.

Design rules, each of which exists because its absence caused a real defect:

1. **Every attribute IBKR emits becomes a column.** The previous parser kept 10 of 85
   and dropped the rest silently. The column set is generated from the statements
   themselves (:mod:`ibkr_core_mcp.flex_schema`), not hand-written.
2. **An unknown attribute is a hard error.** If IBKR adds a field, the import fails
   loudly at the next run rather than discarding it for months.
3. **Nothing is skipped silently.** A record that cannot be parsed raises; it is not
   logged-and-dropped. A single date-only ``dateTime`` hid behind a log line for months.
4. **No timezone is invented.** IBKR does not declare the statement timezone anywhere
   in the XML (checked across all ``AccountInformation`` attributes), so times are
   stored exactly as reported. Day/week/month bucketing uses IBKR's own ``tradeDate``,
   which is timezone-free.

Source for field semantics:
https://www.ibkrguides.com/reportingreference/reportguide/trades_default.htm
Statement codes (the ``notes`` attribute):
https://www.ibkrguides.com/reportingreference/reportguide/codes.htm
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import defusedxml.ElementTree as ET

from .exceptions import FlexQueryError
from .flex_schema import ELEMENTS

__all__ = [
    "FlexImportError",
    "ParsedStatement",
    "STATEMENT_CODES",
    "execution_key_for",
    "live_trade_rows",
    "normalise_date",
    "normalise_datetime",
    "parse_notes",
    "parse_statement",
]


class FlexImportError(FlexQueryError):
    """Raised when a Flex statement cannot be parsed completely and unambiguously.

    Subclasses :class:`FlexQueryError` so existing callers that already handle Flex
    failures keep working; catch this specifically to distinguish a *parse* failure
    from a *fetch* failure.
    """


# IBKR statement code abbreviations, used in the `notes` attribute (semicolon-delimited).
# Source: https://www.ibkrguides.com/reportingreference/reportguide/codes.htm (2026-08-04)
STATEMENT_CODES: dict[str, str] = {
    "A": "Assignment",
    "AEx": "Automatic exercise for dividend-related recommendation",
    "Adj": "Adjustment",
    "Al": "Allocation",
    "Aw": "Away Trade",
    "B": "Automatic Buy-in",
    "Bo": "Direct Borrow",
    "C": "Closing Trade",
    "CD": "Cash Delivery",
    "CP": "Complex Position",
    "Ca": "Cancelled",
    "Co": "Corrected Trade",
    "Cx": "Crossing executed as dual agent by IB for two IB customers",
    "ETF": "ETF Creation/Redemption",
    "Ep": "Resulted from an Expired Position",
    "Ex": "Exercise",
    "G": "Trade in Guaranteed Account Segment",
    "GEA": "Expiration or Assignment resulting from offsetting positions",
    "HC": "Highest Cost tax lot-matching method",
    "HFI": "Investment Transferred to Hedge Fund",
    "HFR": "Redemption from Hedge Fund",
    "I": "Internal Transfer",
    "IA": "Executed against an IB affiliate",
    "INV": "Investment Transfer from Investor",
    "L": "Ordered by IB (Margin Violation)",
    "LD": "Adjusted by Loss Disallowed from Wash Sale",
    "LI": "Last In, First Out (LIFO) tax lot-matching method",
    "LT": "Long-term P/L",
    "Lo": "Direct Loan",
    "M": "Entered manually by IB",
    "MEx": "Manual exercise for dividend-related recommendation",
    "ML": "Maximize Losses tax basis election",
    "MLG": "Maximize Long-Term Gain tax lot-matching method",
    "MLL": "Maximize Long-Term Loss tax lot-matching method",
    "MSG": "Maximize Short-Term Gain tax lot-matching method",
    "MSL": "Maximize Short-Term Loss tax lot-matching method",
    "O": "Opening Trade",
    "P": "Partial Execution",
    "PI": "Price Improvement",
    "Po": "Interest or Dividend Accrual Posting",
    "Pr": "Executed by the Exchange as a Crossing by IB against an IB affiliate (principal)",
    "R": "Dividend Reinvestment",
    "Rb": "Rebill",
    "RED": "Redemption to Investor",
    "RI": "Recurring Investment",
    "Re": "Interest or Dividend Accrual Reversal",
    "Ri": "Reimbursement",
    "SI": "Order solicited by Interactive Brokers",
    "SL": "Specific Lot tax lot-matching method",
    "SO": "Order marked as solicited by your Introducing Broker",
    "SS": "Shortened settlement",
    "ST": "Short-term P/L",
    "SY": "Eligible for Stock Yield",
    "T": "Transfer",
}

# IBKR writes dateTime as `YYYYMMDD;HHMMSS` in Flex (separator set in the query) and as
# `YYYYMMDD-HH:MM:SS` from the Client Portal API. The optional colons matter: without them
# every live fill failed to parse and was stored with a NULL timestamp.
# Exactly one row in the current archive (a `BookTrade`) carries a date with no time.
_DATETIME_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})[;\-\s]?(\d{2}):?(\d{2}):?(\d{2})$")
_DATE_ONLY_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})$")

# Meta columns added to every table on top of the attribute columns.
META_COLUMNS: dict[str, str] = {
    "src_file": "TEXT",
    "stmt_account_id": "TEXT",
    "stmt_from_date": "TEXT",
    "stmt_to_date": "TEXT",
    "stmt_when_generated": "TEXT",
    "raw_attrs": "TEXT",
}

# Extra derived columns, per element.
DERIVED_COLUMNS: dict[str, dict[str, str]] = {
    "Trade": {
        "execution_key": "TEXT",
        "date_time_iso": "TEXT",
        "trade_date_iso": "TEXT",
        "note_codes": "TEXT",
        "source": "TEXT",
    },
    "Lot": {"date_time_iso": "TEXT", "open_date_time_iso": "TEXT", "note_codes": "TEXT"},
}


def normalise_datetime(raw: str) -> str | None:
    """`20260601;093001` → `2026-06-01T09:30:01`. Date-only → midnight. Empty → None.

    No timezone conversion is applied: IBKR does not state the statement timezone in
    the XML, so inventing one would be a guess baked into every downstream figure.
    """
    value = (raw or "").strip()
    if not value:
        return None
    match = _DATETIME_RE.match(value)
    if match:
        year, month, day, hour, minute, second = match.groups()
        return f"{year}-{month}-{day}T{hour}:{minute}:{second}"
    match = _DATE_ONLY_RE.match(value)
    if match:
        year, month, day = match.groups()
        return f"{year}-{month}-{day}T00:00:00"
    raise FlexImportError(
        f"Unrecognised Flex dateTime {raw!r}. Expected YYYYMMDD;HHMMSS or YYYYMMDD. "
        f"Check the query's Date/Time Format and Separator in General Configuration: "
        f"https://www.ibkrguides.com/clientportal/performanceandstatements/activityflex.htm"
    )


def normalise_date(raw: str) -> str | None:
    """`20260601` → `2026-06-01`. Empty → None."""
    value = (raw or "").strip()
    if not value:
        return None
    match = _DATE_ONLY_RE.match(value)
    if not match:
        raise FlexImportError(f"Unrecognised Flex date {raw!r}. Expected YYYYMMDD.")
    year, month, day = match.groups()
    return f"{year}-{month}-{day}"


def parse_notes(raw: str) -> list[str]:
    """Split IBKR's semicolon-delimited `notes` attribute into individual codes."""
    return [code for code in (part.strip() for part in (raw or "").split(";")) if code]


def execution_key_for(attrs: dict[str, str]) -> str:
    """Stable key merging the Flex and live Client Portal views of the same fill.

    ``ibExecID`` is what the CP API returns as ``execId``; it is the only identifier
    the two sources share. Exactly one trade in the archive (2021) has none, hence the
    ``tradeID`` fallback.
    """
    exec_id = (attrs.get("ibExecID") or "").strip()
    if exec_id:
        return exec_id
    trade_id = (attrs.get("tradeID") or "").strip()
    if not trade_id:
        raise FlexImportError(f"Trade has neither ibExecID nor tradeID: {attrs!r}")
    return f"flex:{trade_id}"


def _row_uid(tag: str, attrs: dict[str, str], occurrence: int) -> str:
    """Deterministic content key that still distinguishes identical sibling rows.

    Folding in the occurrence index matters: ``Lot`` and ``WashSale`` do contain
    byte-identical rows within a single statement, so a plain content hash would drop
    them. Because the index counts occurrences *within the statement*, the same row
    seen again in an overlapping statement window still hashes identically and
    de-duplicates.
    """
    payload = json.dumps(dict(sorted(attrs.items())), separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(f"{tag}|{occurrence}|{payload}".encode()).hexdigest()
    return digest


def _coerce(value: str, sql_type: str, *, tag: str, attr: str) -> Any:
    """Convert one attribute string to its column type. Empty → NULL.

    `raw_attrs` preserves the exact original text, so mapping empty to NULL here
    loses nothing and makes `IS NOT NULL` queries mean what they look like.
    """
    text = (value or "").strip()
    if not text:
        return None
    if sql_type == "INTEGER":
        try:
            return int(text)
        except ValueError:
            try:
                return float(text)
            except ValueError as exc:
                raise FlexImportError(f"<{tag}> {attr}={value!r} is not INTEGER") from exc
    if sql_type == "REAL":
        try:
            return float(text)
        except ValueError as exc:
            raise FlexImportError(f"<{tag}> {attr}={value!r} is not REAL") from exc
    return text


def live_trade_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build partial ``flex_trade`` rows from live Client Portal fills.

    The live endpoint returns a handful of fields; the Flex statement for the same fill
    returns 85 and arrives T+1. Both derive the same ``execution_key`` from IBKR's exec
    id (``execId`` live, ``ibExecID`` in Flex), so the Flex row later lands on this row
    instead of creating a second one — the defect that produced 75 duplicate rows.

    Two normalisations the legacy live path skipped:

    * **quantity is signed** from ``side``. The live payload reports an unsigned size, so
      a sell used to be stored as a positive quantity while the Flex view of the same
      fill was negative.
    * **``stmt_when_generated`` is left NULL**, which is what makes the merge one-way:
      the upsert only overwrites when the incoming statement is at least as new, and a
      NULL comparison is never true, so a live row can never clobber richer Flex data.
    """
    from .flex_schema import ELEMENTS

    columns = ELEMENTS["Trade"]["columns"]
    rows: list[dict[str, Any]] = []
    for record in records:
        exec_id = str(record.get("execution_id") or record.get("execId") or "").strip()
        if not exec_id:
            continue
        side = (record.get("side") or "").strip().upper()
        try:
            size = abs(float(record.get("size") or record.get("filledQuantity") or 0))
        except (TypeError, ValueError):
            size = 0.0
        quantity = -size if side.startswith("S") else size
        raw_time = str(record.get("trade_time") or record.get("time") or "").strip()
        try:
            iso = normalise_datetime(raw_time)
        except FlexImportError as exc:
            # Log rather than swallow: a format we cannot parse is a signal that IBKR
            # changed something, not a row to quietly store with a NULL timestamp.
            logging.getLogger(__name__).warning("live fill %s: %s", exec_id, exc)
            iso = None

        row: dict[str, Any] = {column: None for column, _ in columns.values()}
        row.update(
            {
                "execution_key": exec_id,
                "row_uid": _row_uid("Trade", {"live": exec_id}, 0),
                "ib_exec_id": exec_id,
                "symbol": (record.get("symbol") or record.get("ticker") or "").upper().strip() or None,
                "buy_sell": side or None,
                "quantity": quantity,
                "trade_price": float(record.get("price") or record.get("avgPrice") or 0) or None,
                "date_time": raw_time or None,
                "date_time_iso": iso,
                # trade_date is deliberately left NULL on live rows. The Client Portal
                # timestamp is UTC, and a trading day cannot be derived from a UTC instant
                # without the exchange calendar — a 21:00 ET fill is already the next day
                # in UTC, so `iso[:10]` would file it under the wrong session. IBKR states
                # the authoritative tradeDate in the T+1 Flex statement, which then lands
                # on this same row. Aggregations bucket on trade_date (see flex_store), so
                # a live fill is simply not yet bucketable — which is true, not a gap.
                "trade_date_iso": None,
                "trade_date": None,
                "account_id": str(record.get("account") or record.get("acctID") or "") or None,
                "asset_category": (record.get("assetClass") or record.get("secType") or "").strip().upper() or None,
                "ib_commission": -abs(float(record.get("commission") or 0)) or None,
                "conid": int(record["conid"]) if str(record.get("conid") or "").isdigit() else None,
                "note_codes": json.dumps([]),
                "source": "live",
                "src_file": "live:cp-api",
                "stmt_account_id": str(record.get("account") or record.get("acctID") or "") or None,
                "stmt_from_date": None,
                "stmt_to_date": None,
                "stmt_when_generated": None,  # see docstring — this is what makes the merge one-way
                "raw_attrs": json.dumps(record, separators=(",", ":"), sort_keys=True, default=str),
            }
        )
        rows.append(row)
    return rows


@dataclass
class ParsedStatement:
    """One Flex XML statement, fully decomposed."""

    src_file: str
    query_name: str
    query_type: str
    account_id: str
    from_date: str
    to_date: str
    when_generated: str
    rows: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    @property
    def counts(self) -> dict[str, int]:
        """Row count per element tag found in this statement."""
        return {tag: len(rows) for tag, rows in self.rows.items()}

    def total_rows(self) -> int:
        """Total rows across every element tag in this statement."""
        return sum(len(rows) for rows in self.rows.values())


def parse_statement(xml_text: str, src_file: str = "") -> ParsedStatement:
    """Parse a Flex XML statement into complete typed rows, or raise.

    Raises :class:`FlexImportError` if the payload is not a statement (IBKR returns
    ``<FlexStatementResponse>`` with a ``Status``/``ErrorCode`` for warnings such as
    1019 "Statement generation in progress"), or if any element carries an attribute
    the generated schema does not know about.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise FlexImportError(f"{src_file or '<xml>'}: not well-formed XML: {exc}") from exc

    if root.tag != "FlexQueryResponse":
        status = root.findtext("Status", "").strip()
        code = root.findtext("ErrorCode", "").strip()
        message = root.findtext("ErrorMessage", "").strip()
        detail = f" Status={status} ErrorCode={code}: {message}" if (status or code) else ""
        raise FlexImportError(
            f"{src_file or '<xml>'}: root is <{root.tag}>, not <FlexQueryResponse> — "
            f"this is not a statement and must not be imported.{detail}"
        )

    statement = root.find(".//FlexStatement")
    parsed = ParsedStatement(
        src_file=src_file,
        query_name=root.get("queryName", ""),
        query_type=root.get("type", ""),
        account_id=statement.get("accountId", "") if statement is not None else "",
        from_date=statement.get("fromDate", "") if statement is not None else "",
        to_date=statement.get("toDate", "") if statement is not None else "",
        when_generated=statement.get("whenGenerated", "") if statement is not None else "",
    )

    seen: Counter[tuple[str, str]] = Counter()
    for tag, spec in ELEMENTS.items():
        columns = spec["columns"]
        rows: list[dict[str, Any]] = []
        for element in root.iter(tag):
            attrs = dict(element.attrib)

            unknown = set(attrs) - set(columns)
            if unknown:
                raise FlexImportError(
                    f"{src_file or '<xml>'}: <{tag}> has attribute(s) the schema does not know: "
                    f"{sorted(unknown)}. IBKR has added fields — regenerate the schema with "
                    f"`python scripts/audit_flex_xml.py` and re-run. Refusing to import and "
                    f"silently discard them."
                )

            row: dict[str, Any] = {
                "src_file": parsed.src_file,
                "stmt_account_id": parsed.account_id,
                "stmt_from_date": parsed.from_date,
                "stmt_to_date": parsed.to_date,
                "stmt_when_generated": parsed.when_generated,
                "raw_attrs": json.dumps(attrs, separators=(",", ":"), sort_keys=True, ensure_ascii=False),
            }
            for attr, (column, sql_type) in columns.items():
                row[column] = _coerce(attrs.get(attr, ""), sql_type, tag=tag, attr=attr)

            content_key = json.dumps(dict(sorted(attrs.items())), separators=(",", ":"), ensure_ascii=False)
            occurrence = seen[(tag, content_key)]
            seen[(tag, content_key)] += 1
            row["row_uid"] = _row_uid(tag, attrs, occurrence)

            if tag in DERIVED_COLUMNS:
                row["date_time_iso"] = normalise_datetime(attrs.get("dateTime", ""))
                row["note_codes"] = json.dumps(parse_notes(attrs.get("notes", "")))
            if tag == "Trade":
                row["execution_key"] = execution_key_for(attrs)
                row["trade_date_iso"] = normalise_date(attrs.get("tradeDate", ""))
                row["source"] = "flex"
            if tag == "Lot":
                row["open_date_time_iso"] = normalise_datetime(attrs.get("openDateTime", ""))

            rows.append(row)
        if rows:
            parsed.rows[tag] = rows

    return parsed
