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


#: Every check id this audit is expected to produce. A check that does not run is a
#: failure, not an absence — `Gate.finalize` turns any id missing from a run into a FAIL.
#: The id is the leading token of the check's name, which is also the only stable
#: identifier the audit has across runs; that is why duplicates are rejected outright.
#:
#: Retired ids, deliberately not reused: 6, 10, 11, 13.
EXPECTED_CHECKS = frozenset(
    {
        "0.",  # every archive file parses
        "0b.",  # archive holds every statement the import log recorded
        "15.",  # every XML attribute has a schema entry
        "15b.",  # every schema column exists in the database
        "16.",  # per-element row counts (family)
        "1.",  # flex_trade rows == distinct tradeIDs
        "2.",  # no duplicate ib_exec_id
        "3.",  # no blank asset_category
        "4.",  # fifo_pnl_realized stored where the XML had it
        "4b.",  # fifo_pnl_realized values match the XML
        "5.",  # date_time_iso uniformly ISO
        "5b.",  # trade_date_iso uniformly YYYY-MM-DD
        "7.",  # asset_category distribution
        "8.",  # open_close_indicator distribution
        "9.",  # note codes documented
        "12.",  # ib_commission sign preserved
        "14.",  # raw_attrs completeness
        "18.",  # live rows carry the merge key
        "19.",  # live rows do not guess a trading day
        "20.",  # live SELL quantities signed
        "21.",  # live rows parsed their timestamp
        "22.",  # statement window dates are complete
        "17.",  # realised P&L reconciles
        "17a.",  # annual statements were discovered at all
        "17c.",  # per-calendar-year reconciliation (family)
        "17d.",  # no trading day outside every annual window
        "17e.",  # every closed lot carries a realised-P&L value
        "17f.",  # every closed lot resolves to a stored trade
    }
)

#: Ids that legitimately repeat — one per element, one per calendar year.
FAMILY_CHECKS = frozenset({"16.", "17c."})


class Gate:
    """Collects pass/fail results so every check runs even after one fails.

    The summary line prints ``passed/total``. Before 2026-08-10 the total was simply
    however many checks had run, so a check that silently did not execute shrank the
    denominator with it and the summary stayed true — the calendar-year reconciliation
    disappeared exactly that way whenever no annual statement was found. The expected-id
    registry is what makes the denominator fixed and the summary meaningful.
    """

    def __init__(self, expected: frozenset[str], families: frozenset[str] = frozenset()) -> None:
        """Start with an empty result set and the ids this run must produce."""
        self.results: list[tuple[bool, str, str]] = []
        self.expected = expected
        self.families = families
        self.seen: set[str] = set()

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        """Record and print one result. Returns `ok` so callers can chain.

        Raises if the id is unregistered (a typo, or a check added without declaring it)
        or if a non-family id is used twice (two different checks sharing one identifier,
        which is what made ``"17."`` ambiguous in run-to-run comparisons).
        """
        check_id = name.split(" ", 1)[0]
        if check_id not in self.expected:
            raise KeyError(f"{check_id} is not in EXPECTED_CHECKS — declare it or fix the name")
        if check_id in self.seen and check_id not in self.families:
            raise ValueError(f"{check_id} is used by two different checks — ids must be unique")
        self.seen.add(check_id)

        self.results.append((ok, name, detail))
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
        return ok

    def finalize(self) -> None:
        """Record a failure for every expected check that never ran."""
        for check_id in sorted(self.expected - self.seen):
            self.results.append((False, f"{check_id} expected check never ran", "no result was recorded"))
            print(f"  [FAIL] {check_id} expected check never ran — no result was recorded")

    @property
    def failed(self) -> int:
        """Number of checks that did not pass."""
        return sum(1 for ok, _, _ in self.results if not ok)


def annual_windows(rows: Any) -> list[tuple[str, str, str]]:
    """Pick IBKR's annual statements out of `(from_date, to_date)` pairs.

    An annual statement runs first trading day → last trading day, so it is recognised
    from its dates rather than a filename: same calendar year, opening in the first week,
    closing in the last.

    Missing dates yield nothing rather than raising. A NULL ``stmt_to_date`` used to
    reach ``t[:4]`` and abort the entire audit with a TypeError, while a NULL
    ``stmt_from_date`` was filtered out in SQL and vanished silently — two different
    failure modes for the same missing data. Check 22 is what reports them.
    """
    found: list[tuple[str, str, str]] = []
    for from_date, to_date in rows:
        if not from_date or not to_date:
            continue
        if from_date[:4] == to_date[:4] and from_date[4:] <= "0107" and to_date[4:] >= "1224":
            found.append((from_date[:4], from_date, to_date))
    return sorted(found)


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
    rejected: list[str] = []
    files_parsed = 0
    # Per-tradeID views, so distributions can be compared against a database that stores
    # one row per tradeID rather than one row per XML occurrence.
    cat_by_trade: dict[str, str] = {}
    oc_by_trade: dict[str, str] = {}
    commission_by_trade: dict[str, float] = {}

    for path in sorted(src.glob("*.xml")):
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError:
            rejected.append(f"{path.name}: not well-formed XML")
            continue
        if root.tag != "FlexQueryResponse":
            rejected.append(f"{path.name}: root is <{root.tag}>, not a statement")
            continue
        files_parsed += 1
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
        "files_parsed": files_parsed,
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
    gate = Gate(expected=EXPECTED_CHECKS, families=FAMILY_CHECKS)

    print("\n── Source archive ──────────────────────────────────────────────────")

    # 0. The archive this whole audit compares against must itself be sound. These
    # rejections were counted and returned by source_truth, and then never read: a
    # truncated or error-payload file silently shrank the "source of truth" while every
    # downstream comparison reported agreement with what remained.
    gate.check(
        "0. every file in the archive is a parseable statement",
        not truth["rejected"],
        "; ".join(truth["rejected"]) if truth["rejected"] else f"{truth['files_parsed']} parsed",
    )

    # 0b. ...and it must be *current*. Measured 2026-08-10: the local archive was one
    # statement behind the database, so five checks failed and described a data problem
    # that did not exist. A stale source of truth produces false reds as readily as a
    # missing check produces false greens.
    archived = {path.name for path in src.glob("*.xml")}
    try:
        imported = {r["filename"] for r in q("SELECT filename FROM flex_import_log")}
    except sqlite3.DatabaseError:
        imported = set()
    absent = sorted(imported - archived)
    gate.check(
        "0b. archive holds every statement the import log recorded",
        not absent,
        f"{len(absent)} missing: {absent}" if absent else f"{len(imported)} logged imports present",
    )

    print("\n── Structure ───────────────────────────────────────────────────────")

    # 15. Every attribute the XML carries has a column.
    #
    # The evidence is measured, not asserted. It used to be the literal string
    # "222 attributes across 14 elements", printed identically for an archive of 3
    # statements or 0 — and `not missing_columns` is vacuously true when nothing was
    # read at all, so an empty source printed a confident PASS.
    missing_columns: dict[str, list[str]] = {}
    for tag, attrs in truth["attrs_seen"].items():
        known = {attr for attr in ELEMENTS[tag]["columns"]}
        gap = attrs - known
        if gap:
            missing_columns[tag] = sorted(gap)
    attrs_counted = sum(len(a) for a in truth["attrs_seen"].values())
    gate.check(
        "15. every XML attribute has a schema entry",
        not missing_columns and bool(truth["attrs_seen"]),
        json.dumps(missing_columns)
        if missing_columns
        else f"{attrs_counted} attributes across {len(truth['attrs_seen'])} elements",
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

    # 17c. Calendar-year totals against IBKR's own ANNUAL statements.
    #
    # The per-statement checks prove agreement inside a statement window; they do not
    # prove that bucketing by calendar year reproduces IBKR's annual figure, because a
    # statement window and a calendar year are not the same boundary. An annual statement
    # runs first trading day → last trading day, so a trade on Jan 1 or Dec 31 could in
    # principle fall outside every annual window and be reported by us but not by IBKR.
    #
    # Measured 2026-08-04: no such trade exists in six years of history, and all six
    # annual totals reconcile exactly. This check keeps that true.
    #
    # NOTE: the per-statement comparison this reasoning refers to compares *totals*
    # inside a window (checks 4/4b, per trade). A direct per-statement SymbolSummary
    # reconciliation does not exist yet — `source_truth` computes `symbol_summary_pnl`
    # for it and nothing reads it. Do not read the paragraph above as claiming otherwise.
    windows = [
        (r["f"], r["t"])
        for r in q("SELECT DISTINCT stmt_from_date f, stmt_to_date t FROM flex_trade WHERE source='flex'")
    ]
    incomplete = sum(1 for f, t in windows if not f or not t)
    gate.check(
        "22. every Flex row records a complete statement window",
        incomplete == 0,
        f"{incomplete} row group(s) with a NULL from/to date",
    )

    annual = annual_windows(windows)
    # A discovery step that finds nothing must itself be a failed check. This block used
    # to be wrapped in `if annual:`, so an archive of only quarterly statements — or a
    # re-pull starting 20260108, one day past the window — removed the reconciliation
    # entirely while the summary went on reporting "N/N checks passed".
    gate.check(
        "17a. annual statements were found to reconcile against",
        bool(annual),
        f"{len(annual)} annual window(s): {[y for y, _, _ in annual]}"
        if annual
        else "no annual statement in the archive — the calendar-year reconciliation cannot run",
    )
    for year, f, t in annual:
        ibkr = q(
            "SELECT COALESCE(SUM(fifo_pnl_realized),0) v FROM flex_symbol_summary "
            "WHERE stmt_from_date=? AND stmt_to_date=?",
            (f, t),
        ).fetchone()["v"]
        ours = q(
            "SELECT COALESCE(SUM(fifo_pnl_realized),0) v FROM flex_trade "
            "WHERE source='flex' AND substr(trade_date,1,4)=?",
            (year,),
        ).fetchone()["v"]
        gate.check(
            f"17c. calendar {year} == IBKR annual statement",
            abs(ibkr - ours) < 0.01,
            f"IBKR {ibkr:,.2f} vs ours {ours:,.2f}",
        )

    if annual:
        covered = " OR ".join("(trade_date BETWEEN ? AND ?)" for _ in annual)
        params = [x for _, f, t in annual for x in (f, t)]
        latest = max(t for _, _, t in annual)
        orphans = q(
            f"SELECT COUNT(DISTINCT trade_date) c FROM flex_trade WHERE source='flex' "
            f"AND trade_date IS NOT NULL AND trade_date <= '{latest}' AND NOT ({covered})",
            params,
        ).fetchone()["c"]
        gate.check(
            "17d. no trading day falls outside every annual statement window",
            orphans == 0,
            f"{orphans} orphaned trading date(s)",
        )

    gate.check(
        "17. realised P&L reconciles: trades == lots + wash-sale disallowed",
        abs(realised - (lots_pnl + wash_pnl)) < 0.01,
        f"{realised:,.2f} vs {lots_pnl + wash_pnl:,.2f}",
    )

    # 17e. Capture check that IS a gate: every closed lot must be stored with a P&L value.
    lots_missing = q("SELECT COUNT(*) c FROM flex_lot WHERE fifo_pnl_realized IS NULL").fetchone()["c"]
    gate.check("17e. every closed lot carries a realised-P&L value", lots_missing == 0, f"{lots_missing} missing")

    # 17f. The trade/lot linkage is intact: Lot.transaction_id is the OPENING transaction,
    # so every lot must resolve to a trade we hold.
    orphan_lots = q(
        "SELECT COUNT(*) c FROM flex_lot l "
        "WHERE NOT EXISTS (SELECT 1 FROM flex_trade t WHERE t.transaction_id = l.transaction_id)"
    ).fetchone()["c"]
    gate.check("17f. every closed lot resolves to a stored trade", orphan_lots == 0, f"{orphan_lots} orphaned")

    conn.close()
    gate.finalize()
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
