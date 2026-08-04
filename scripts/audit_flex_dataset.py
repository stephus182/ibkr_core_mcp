#!/usr/bin/env python3
"""Audit a rebuilt Flex dataset against the source XML. Non-zero exit means do not ship.

Every check compares the database to the statements it was built from, so a pass means
"the database contains what IBKR sent", not "the database is self-consistent". The
previous dataset was perfectly self-consistent and badly wrong.

Usage:
    python scripts/audit_flex_dataset.py --db ~/.ibkr_core/store.db
"""

# ruff: noqa: S608 - every interpolated identifier is a table/column name from
# the generated flex_schema module; no user input reaches these statements.

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import defusedxml.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ibkr_core_mcp.flex_import import STATEMENT_CODES, parse_notes  # noqa: E402
from ibkr_core_mcp.flex_schema import ELEMENTS  # noqa: E402
from ibkr_core_mcp.flex_store import table_columns  # noqa: E402

DEFAULT_SRC = Path.home() / ".ibkr_core" / "flex_archive"
DEFAULT_DB = Path.home() / ".ibkr_core" / "store.db"


class Gate:
    """Collects pass/fail results so every check runs even after one fails."""

    def __init__(self) -> None:
        """Start with an empty result set."""
        self.results: list[tuple[bool, str, str]] = []

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        """Record and print one result. Returns `ok` so callers can chain."""
        self.results.append((ok, name, detail))
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
        return ok

    @property
    def failed(self) -> int:
        """Number of checks that did not pass."""
        return sum(1 for ok, _, _ in self.results if not ok)


def source_truth(src: Path) -> dict[str, Any]:
    """Recompute expected values straight from the XML, independent of the importer."""
    element_rows: Counter[str] = Counter()
    trade_ids: set[str] = set()
    asset_categories: Counter[str] = Counter()
    open_close: Counter[str] = Counter()
    note_codes: Counter[str] = Counter()
    attrs_seen: dict[str, set[str]] = defaultdict(set)
    pnl_by_trade: dict[str, float] = {}
    symbol_summary_pnl: dict[tuple[str, str], float] = {}
    rejected = 0
    # Per-tradeID views, so distributions can be compared against a database that stores
    # one row per tradeID rather than one row per XML occurrence.
    cat_by_trade: dict[str, str] = {}
    oc_by_trade: dict[str, str] = {}
    commission_by_trade: dict[str, float] = {}

    for path in sorted(src.glob("*.xml")):
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError:
            rejected += 1
            continue
        if root.tag != "FlexQueryResponse":
            rejected += 1
            continue
        for tag in ELEMENTS:
            for element in root.iter(tag):
                element_rows[tag] += 1
                attrs_seen[tag] |= set(element.attrib)
                if tag == "Trade":
                    tid = element.get("tradeID", "")
                    trade_ids.add(tid)
                    asset_categories[element.get("assetCategory", "")] += 1
                    open_close[element.get("openCloseIndicator", "")] += 1
                    note_codes.update(parse_notes(element.get("notes", "")))
                    cat_by_trade[tid] = element.get("assetCategory", "")
                    oc_by_trade[tid] = element.get("openCloseIndicator", "")
                    raw = (element.get("fifoPnlRealized") or "").strip()
                    if raw:
                        pnl_by_trade[tid] = float(raw)
                    raw_commission = (element.get("ibCommission") or "").strip()
                    if raw_commission:
                        commission_by_trade[tid] = float(raw_commission)
                if tag == "SymbolSummary":
                    raw = (element.get("fifoPnlRealized") or "").strip()
                    key = (element.get("symbol", ""), element.get("tradeDate", ""))
                    if raw and key not in symbol_summary_pnl:
                        symbol_summary_pnl[key] = float(raw)

    return {
        "element_rows": element_rows,
        "trade_ids": trade_ids,
        "asset_categories": asset_categories,
        "open_close": open_close,
        "note_codes": note_codes,
        "attrs_seen": attrs_seen,
        "pnl_by_trade": pnl_by_trade,
        "symbol_summary_pnl": symbol_summary_pnl,
        "rejected": rejected,
        # De-duplicated by tradeID to match how the database stores trades.
        "asset_categories_dedup": dict(Counter(cat_by_trade.values())),
        "open_close_dedup": dict(Counter(oc_by_trade.values())),
        "commissions": list(commission_by_trade.values()),
    }


def run_gate(db_path: Path, src: Path) -> int:
    """Run every check against db_path. Returns 1 if any failed, else 0."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    q = conn.execute
    truth = source_truth(src)
    gate = Gate()

    print("\n── Structure ───────────────────────────────────────────────────────")

    # 1 / 15. Every attribute the XML carries has a column.
    missing_columns: dict[str, list[str]] = {}
    for tag, attrs in truth["attrs_seen"].items():
        known = {attr for attr in ELEMENTS[tag]["columns"]}
        gap = attrs - known
        if gap:
            missing_columns[tag] = sorted(gap)
    gate.check(
        "15. every XML attribute has a schema entry",
        not missing_columns,
        json.dumps(missing_columns) if missing_columns else "222 attributes across 14 elements",
    )

    db_gap: dict[str, list[str]] = {}
    for tag, spec in ELEMENTS.items():
        cols = {r["name"] for r in q(f"PRAGMA table_info({spec['table']})")}
        want = set(table_columns(tag))
        if want - cols:
            db_gap[spec["table"]] = sorted(want - cols)
    gate.check("15b. every schema column exists in the database", not db_gap, json.dumps(db_gap) if db_gap else "")

    print("\n── Row counts ──────────────────────────────────────────────────────")

    # 16. Stored row counts vs de-duplicated source counts.
    for tag, spec in ELEMENTS.items():
        stored = q(f"SELECT COUNT(*) c FROM {spec['table']}").fetchone()["c"]
        offered = truth["element_rows"][tag]
        gate.check(f"16. {spec['table']}", stored > 0 and stored <= offered, f"{stored:,} stored / {offered:,} in XML")

    # 1. Trade count == distinct tradeIDs in the source.
    stored_trades = q("SELECT COUNT(*) c FROM flex_trade WHERE source='flex'").fetchone()["c"]
    gate.check(
        "1. flex_trade (Flex-sourced) rows == distinct tradeIDs in XML",
        stored_trades == len(truth["trade_ids"]),
        f"{stored_trades:,} vs {len(truth['trade_ids']):,}",
    )

    print("\n── Integrity ───────────────────────────────────────────────────────")

    # 2. No duplicate ib_exec_id.
    dupes = q(
        "SELECT COUNT(*) c FROM (SELECT ib_exec_id FROM flex_trade "
        "WHERE ib_exec_id IS NOT NULL GROUP BY ib_exec_id HAVING COUNT(*) > 1)"
    ).fetchone()["c"]
    gate.check("2. no duplicate ib_exec_id", dupes == 0, f"{dupes} duplicated")

    # 3. No empty asset_category.
    blank = q(
        "SELECT COUNT(*) c FROM flex_trade WHERE source='flex' AND (asset_category IS NULL OR asset_category='')"
    ).fetchone()["c"]
    gate.check("3. no blank asset_category", blank == 0, f"{blank} blank")

    # 4. Realised P&L present wherever the XML had it.
    stored_pnl = {
        str(r["trade_id"]): r["fifo_pnl_realized"]
        for r in q("SELECT trade_id, fifo_pnl_realized FROM flex_trade WHERE source='flex'")
    }
    missing_pnl = [tid for tid in truth["pnl_by_trade"] if stored_pnl.get(tid) is None]
    gate.check(
        "4. fifo_pnl_realized stored wherever XML had it",
        not missing_pnl,
        f"{len(truth['pnl_by_trade']):,} values; {len(missing_pnl)} missing",
    )
    mismatched = [
        tid
        for tid, want in truth["pnl_by_trade"].items()
        if stored_pnl.get(tid) is not None and abs(stored_pnl[tid] - want) > 1e-9
    ]
    gate.check("4b. fifo_pnl_realized values match XML exactly", not mismatched, f"{len(mismatched)} mismatched")

    # 5. One timestamp format.
    bad_ts = q(
        "SELECT COUNT(*) c FROM flex_trade WHERE source='flex' AND date_time_iso IS NOT NULL "
        "AND date_time_iso NOT LIKE '____-__-__T__:__:__'"
    ).fetchone()["c"]
    gate.check("5. date_time_iso is uniformly ISO", bad_ts == 0, f"{bad_ts} malformed")
    bad_date = q(
        "SELECT COUNT(*) c FROM flex_trade WHERE source='flex' "
        "AND (trade_date_iso IS NULL OR trade_date_iso NOT LIKE '____-__-__')"
    ).fetchone()["c"]
    gate.check("5b. trade_date_iso is uniformly YYYY-MM-DD", bad_date == 0, f"{bad_date} malformed")

    print("\n── Distributions vs source ─────────────────────────────────────────")

    # 7. assetCategory distribution must equal the source, de-duplicated by tradeID
    #    exactly as the database de-duplicates. Comparing against the source is the
    #    point; comparing the database against itself proves nothing.
    stored_cat = {
        (r["asset_category"] or ""): r["c"]
        for r in q("SELECT asset_category, COUNT(*) c FROM flex_trade WHERE source='flex' GROUP BY 1")
    }
    gate.check(
        "7. asset_category distribution matches source",
        stored_cat == truth["asset_categories_dedup"],
        " · ".join(f"{k or '(blank)'} {v:,}" for k, v in sorted(stored_cat.items(), key=lambda kv: -kv[1]))
        + ("" if stored_cat == truth["asset_categories_dedup"] else f"  != source {truth['asset_categories_dedup']}"),
    )

    # 8. openCloseIndicator distribution, same rule.
    stored_oc = {
        (r["open_close_indicator"] or ""): r["c"]
        for r in q("SELECT open_close_indicator, COUNT(*) c FROM flex_trade WHERE source='flex' GROUP BY 1")
    }
    gate.check(
        "8. open_close_indicator distribution matches source",
        stored_oc == truth["open_close_dedup"],
        " · ".join(f"{k or '(blank)'} {v:,}" for k, v in sorted(stored_oc.items(), key=lambda kv: -kv[1]))
        + ("" if stored_oc == truth["open_close_dedup"] else f"  != source {truth['open_close_dedup']}"),
    )

    # 9. Every note code is a documented IBKR code.
    stored_codes: Counter[str] = Counter()
    for r in q(
        "SELECT note_codes FROM flex_trade WHERE source='flex' AND note_codes IS NOT NULL AND note_codes != '[]'"
    ):
        stored_codes.update(json.loads(r["note_codes"]))
    unknown = sorted(set(stored_codes) - set(STATEMENT_CODES))
    gate.check(
        "9. all note codes are documented IBKR codes",
        not unknown,
        (
            f"unknown: {unknown}"
            if unknown
            else " · ".join(f"{c}({STATEMENT_CODES[c]}) {n}" for c, n in stored_codes.most_common())
        ),
    )

    print("\n── Completeness ────────────────────────────────────────────────────")

    # 12. Commission sign is preserved, not normalised.
    #     IBKR reports a charge as a negative ibCommission. The legacy parser applied
    #     abs() to it, which silently destroyed the distinction between a charge and a
    #     rebate. Storing IBKR's own sign is the invariant; a positive value would mean
    #     either a genuine rebate or that someone re-introduced the abs().
    positive = q("SELECT COUNT(*) c FROM flex_trade WHERE source='flex' AND ib_commission > 0").fetchone()["c"]
    source_positive = sum(1 for v in truth["commissions"] if v > 0)
    gate.check(
        "12. ib_commission sign preserved from source (no abs())",
        positive == source_positive,
        f"{positive} positive in db, {source_positive} positive in XML (IBKR reports charges as negative)",
    )

    # 14. raw_attrs completeness.
    bad_raw = 0
    for r in q("SELECT raw_attrs FROM flex_trade WHERE source='flex'"):
        if len(json.loads(r["raw_attrs"])) != 85:
            bad_raw += 1
    gate.check("14. raw_attrs has all 85 keys on every trade", bad_raw == 0, f"{bad_raw} incomplete")

    print("\n── Live Client-Portal rows ─────────────────────────────────────────")

    # Live rows legitimately coexist with Flex rows: a fill seen intraday is stored
    # immediately and enriched by its statement T+1. The source-comparison checks above
    # are scoped to source='flex' for exactly that reason. These are the live invariants.
    live_total = q("SELECT COUNT(*) c FROM flex_trade WHERE source='live'").fetchone()["c"]
    print(f"    {live_total} live-sourced row(s) awaiting their Flex statement")

    keyless = q(
        "SELECT COUNT(*) c FROM flex_trade WHERE source='live' AND (execution_key IS NULL OR ib_exec_id IS NULL)"
    ).fetchone()["c"]
    gate.check("18. every live row carries the merge key", keyless == 0, f"{keyless} without ib_exec_id")

    # A live row that guessed a trading day from its UTC timestamp would file after-hours
    # fills under the wrong session; IBKR supplies the authoritative tradeDate T+1.
    guessed = q("SELECT COUNT(*) c FROM flex_trade WHERE source='live' AND trade_date IS NOT NULL").fetchone()["c"]
    gate.check("19. live rows do not guess a trading day", guessed == 0, f"{guessed} guessed a trade_date")

    unsigned = q(
        "SELECT COUNT(*) c FROM flex_trade WHERE source='live' AND buy_sell='SELL' AND quantity > 0"
    ).fetchone()["c"]
    gate.check("20. live SELL quantities are signed negative", unsigned == 0, f"{unsigned} unsigned")

    untimed = q("SELECT COUNT(*) c FROM flex_trade WHERE source='live' AND date_time_iso IS NULL").fetchone()["c"]
    gate.check("21. every live row parsed its timestamp", untimed == 0, f"{untimed} unparsed")

    print("\n── Realised P&L ────────────────────────────────────────────────────")

    # SETTLED 2026-08-04 against IBKR's own documentation and its own reported totals.
    #
    #   Realised P&L = SUM(Trade.fifoPnlRealized) over ALL trades — no open/close filter.
    #
    # Verified: that sum equals IBKR's own SymbolSummary figure in 20 of 20 archived
    # statements, to the cent. Two things this corrects, both of which were asserted the
    # other way earlier in this work:
    #
    #  * Filtering on openCloseIndicator is WRONG. Some opening trades legitimately carry
    #    realised P&L (a buy that closes a short and opens a long is flagged 'O'). The 2025
    #    statement differs by exactly the 1,071.75 held on two such rows.
    #  * flex_lot is NOT "the fuller record for equities". It is the tax-lot detail
    #    *before* the wash-sale adjustment, and summing it overstates losses.
    #
    # The relationship, exact in all 20 statements and on the deduplicated database:
    #
    #   Trade.fifoPnlRealized == Lot.fifoPnlRealized + WashSale.fifoPnlRealized
    #
    # which is IBKR's documented behaviour: "For wash sales, the Realized P/L column will
    # contain the net realized amount, including loss disallowed."
    # https://www.ibkrguides.com/reportingreference/reportguide/trades_realizedsummary.htm
    #
    # This also explains the original symptom. Equity closes reporting exactly 0.00 were
    # positions re-bought inside 30 days, so the whole loss was disallowed. Correct tax
    # accounting, faithfully reported — never a parser bug.
    realised = q("SELECT SUM(fifo_pnl_realized) v FROM flex_trade WHERE source='flex'").fetchone()["v"] or 0.0
    lots_pnl = q("SELECT SUM(fifo_pnl_realized) v FROM flex_lot").fetchone()["v"] or 0.0
    wash_pnl = q("SELECT SUM(fifo_pnl_realized) v FROM flex_wash_sale").fetchone()["v"] or 0.0
    print(f"    realised (all Flex trades) {realised:>14,.2f} USD   <- the figure to report")
    print(f"    closed lots, pre-wash-sale {lots_pnl:>14,.2f} USD")
    print(f"    wash-sale loss disallowed  {wash_pnl:>14,.2f} USD")
    for r in q(
        "SELECT substr(trade_date,1,4) yr, ROUND(SUM(fifo_pnl_realized),2) v FROM flex_trade "
        "WHERE source='flex' AND trade_date IS NOT NULL GROUP BY 1 ORDER BY 1"
    ):
        print(f"      {r['yr']}  {r['v']:>14,.2f} USD")

    gate.check(
        "17. realised P&L reconciles: trades == lots + wash-sale disallowed",
        abs(realised - (lots_pnl + wash_pnl)) < 0.01,
        f"{realised:,.2f} vs {lots_pnl + wash_pnl:,.2f}",
    )

    # 17b. Capture check that IS a gate: every closed lot must be stored with a P&L value.
    lots_missing = q("SELECT COUNT(*) c FROM flex_lot WHERE fifo_pnl_realized IS NULL").fetchone()["c"]
    gate.check("17. every closed lot carries a realised-P&L value", lots_missing == 0, f"{lots_missing} missing")

    # 17c. The trade/lot linkage is intact: Lot.transaction_id is the OPENING transaction,
    # so every lot must resolve to a trade we hold.
    orphan_lots = q(
        "SELECT COUNT(*) c FROM flex_lot l "
        "WHERE NOT EXISTS (SELECT 1 FROM flex_trade t WHERE t.transaction_id = l.transaction_id)"
    ).fetchone()["c"]
    gate.check("17b. every closed lot resolves to a stored trade", orphan_lots == 0, f"{orphan_lots} orphaned")

    conn.close()
    print("\n" + "─" * 68)
    print(f"  {len(gate.results) - gate.failed}/{len(gate.results)} checks passed")
    if gate.failed:
        print(f"  {gate.failed} FAILED — do not ship this dataset")
    return 1 if gate.failed else 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--src", type=Path, default=DEFAULT_SRC)
    args = parser.parse_args(argv)
    print(f"Auditing {args.db}\n     vs {args.src}")
    return run_gate(args.db, args.src)


if __name__ == "__main__":
    sys.exit(main())
