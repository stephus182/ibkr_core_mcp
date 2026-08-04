#!/usr/bin/env python3
"""Audit the structure of every IBKR Flex XML statement in a directory.

Why this exists
---------------
The previous trade dataset was built by a parser that kept 10 of the 85 attributes
IBKR publishes on each ``<Trade>`` element, and silently dropped the rest. The loss
was invisible for months because nothing ever compared the database against the
source XML.

This script is that comparison. It derives the complete element/attribute inventory
**from the data**, not from a hand-written list, and emits it as JSON. That JSON is
the single source of truth consumed by ``ibkr_core_mcp.flex_schema`` to generate the
tables, which is what makes "every attribute in the XML has a column" a checkable
invariant rather than an aspiration.

Outputs
-------
- ``flex-xml-structure.json``  machine-readable inventory (feeds flex_schema)
- ``flex-xml-structure-audit.md``  human-readable report

Usage
-----
    python scripts/audit_flex_xml.py [--src ~/.ibkr_core/flex_archive] \
                                     [--json-out PATH] [--md-out PATH]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import defusedxml.ElementTree as ET

DEFAULT_SRC = Path.home() / ".ibkr_core" / "flex_archive"

# An element is "enum-like" (worth listing every distinct value) below this many
# distinct values. Above it we record only the cardinality and a few samples.
ENUM_MAX_DISTINCT = 40

# Attributes whose observed VALUES may appear in the published audit output.
#
# This is an allowlist, not a denylist, and deliberately so: the audit runs over real
# account statements and this package is published. Anything not named here is reported
# as cardinality and type only. A new IBKR attribute is therefore redacted by default
# rather than disclosed by default — the first version of this script leaked the account
# number 27 times, the holder's name, and 77 ISIN/CUSIP identifiers into a committed doc.
#
# Everything listed is structural: a parser has to branch on it, and none of it
# identifies an account, a holding or a position.
ALWAYS_ENUMERATE = {
    "levelOfDetail",
    "assetCategory",
    "openCloseIndicator",
    "transactionType",
    "buySell",
    "putCall",
    "notes",
    "code",
    "type",
    "securityIDType",
    "subCategory",
    "currency",
    "ibCommissionCurrency",
}

# Flex statement wrapper elements: they carry no data of their own, only children.
CONTAINER_TAGS = {
    "FlexQueryResponse",
    "FlexStatements",
    "FlexStatement",
    "Trades",
    "Lots",
    "Orders",
    "OpenPositions",
    "CashTransactions",
    "CorporateActions",
    "Transfers",
    "SecuritiesInfo",
    "ConversionRates",
    "StmtFunds",
    "FxPositions",
    "TransactionTaxes",
    "UnbundledCommissionDetails",
    "ChangeInNAVs",
    "SalesTaxes",
    "WashSales",
    "SymbolSummaries",
    "AssetSummaries",
}

_NUMERIC_RE = re.compile(r"^-?\d+$")
_DECIMAL_RE = re.compile(r"^-?\d*\.\d+$")
_DATE_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})$")
_DATETIME_SEMI_RE = re.compile(r"^\d{8};\d{6}$")

# Attribute names that are dates. Shape alone is not enough: an 8-digit IBKR conid
# (e.g. 12658199) matches ^\d{8}$ and was being classified as a date, which made
# `conid` look like a date column in the first run of this audit.
_DATE_ATTR_RE = re.compile(r"(date|expiry|maturity)", re.IGNORECASE)

# Attribute names that are money / price / quantity / rate and must be REAL even when
# every observed value happens to be a whole number. Several of these (taxes, strike,
# accruedInt, origTradePrice) are 0 on every row in the current archive, so pure
# inference types them INTEGER — correct for the sample, wrong for the domain.
# This override can only *widen* a type; it never drops or renames an attribute.
_NUMERIC_ATTR_RE = re.compile(
    r"(price|amount|money|cost|proceeds|cash|value|pnl|commission|tax|fee|"
    r"interest|quantity|multiplier|rate|basis|strike|accrued|balance|"
    r"credit|debit|dividend|weight|fineness|adjust)",
    re.IGNORECASE,
)


def classify_value(value: str, attr: str = "") -> str:
    """Return a coarse type tag for one attribute value. Empty string → 'empty'.

    `attr` disambiguates the ^\\d{8}$ collision between dates and numeric IDs.
    """
    value = value.strip()
    if not value:
        return "empty"
    if _DATETIME_SEMI_RE.match(value):
        return "datetime"
    match = _DATE_RE.match(value)
    if match and _DATE_ATTR_RE.search(attr):
        year, month, day = (int(g) for g in match.groups())
        if 1900 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31:
            return "date"
    if _NUMERIC_RE.match(value):
        return "int"
    if _DECIMAL_RE.match(value):
        return "float"
    return "text"


def sql_type_for(type_counts: Counter[str], attr: str = "") -> str:
    """Choose a SQLite column type from observed value types (widest wins).

    Dates stay TEXT (IBKR's YYYYMMDD strings sort correctly as text and survive
    round-tripping without a timezone assumption).
    """
    seen = {t for t, n in type_counts.items() if n and t != "empty"}
    if not seen:
        # Never populated in this archive. TEXT is the safe home for an unknown domain,
        # unless the name says it is numeric.
        return "REAL" if _NUMERIC_ATTR_RE.search(attr) else "TEXT"
    if seen <= {"int", "float"}:
        if seen == {"int"} and not _NUMERIC_ATTR_RE.search(attr):
            return "INTEGER"
        return "REAL"
    return "TEXT"


class ElementStats:
    """Accumulated observations for one XML element type across all files."""

    def __init__(self, tag: str) -> None:
        """Start accumulating observations for one element tag."""
        self.tag = tag
        self.count = 0
        self.attr_present: Counter[str] = Counter()
        self.attr_nonempty: Counter[str] = Counter()
        self.attr_types: dict[str, Counter[str]] = defaultdict(Counter)
        self.attr_values: dict[str, Counter[str]] = defaultdict(Counter)
        self.attr_maxlen: Counter[str] = Counter()
        self.files: set[str] = set()
        self.has_text = False

    def observe(self, element: ET.Element, filename: str) -> None:
        """Fold one XML element's attributes into the running statistics."""
        self.count += 1
        self.files.add(filename)
        if (element.text or "").strip():
            self.has_text = True
        for key, raw in element.attrib.items():
            value = (raw or "").strip()
            self.attr_present[key] += 1
            self.attr_types[key][classify_value(raw, key)] += 1
            self.attr_maxlen[key] = max(self.attr_maxlen[key], len(value))
            if value:
                self.attr_nonempty[key] += 1
                # Bound memory: stop collecting once clearly high-cardinality,
                # unless the attribute is one we always want fully enumerated.
                bucket = self.attr_values[key]
                if key in ALWAYS_ENUMERATE or len(bucket) <= ENUM_MAX_DISTINCT:
                    bucket[value] += 1

    def to_dict(self) -> dict[str, Any]:
        """Serialise the accumulated statistics for the JSON inventory."""
        attributes = {}
        for key in sorted(self.attr_present):
            values = self.attr_values.get(key, Counter())
            # Disclosure is allowlist-only (see ALWAYS_ENUMERATE): everything else
            # reports shape without content, because these are real statements.
            enumerable = key in ALWAYS_ENUMERATE
            attributes[key] = {
                "present": self.attr_present[key],
                "nonempty": self.attr_nonempty[key],
                "pct_nonempty": round(100 * self.attr_nonempty[key] / self.count, 2),
                "sql_type": sql_type_for(self.attr_types[key], key),
                "value_types": dict(self.attr_types[key]),
                "max_len": self.attr_maxlen[key],
                "distinct": len(values) if enumerable else "redacted",
                "values": dict(values.most_common(ENUM_MAX_DISTINCT)) if enumerable else {},
                "samples": [v for v, _ in values.most_common(3)] if enumerable else [],
            }
        return {
            "tag": self.tag,
            "count": self.count,
            "files": len(self.files),
            "has_text_content": self.has_text,
            "attribute_count": len(self.attr_present),
            "attributes": attributes,
        }


# No \b anchors: the account number is embedded as `flex_U1234567_...` and `_` is a word
# character, so a word boundary never matches between them — the first version of this
# mask silently did nothing.
_ACCOUNT_RE = re.compile(r"U\d{6,9}")


def mask_account(text: str) -> str:
    """Mask IBKR account numbers. Statement filenames embed them (flex_U1234567_...)."""
    return _ACCOUNT_RE.sub("U*******", text or "")


def audit_directory(src: Path) -> dict[str, Any]:
    """Walk every .xml in src and return the full structural inventory."""
    stats: dict[str, ElementStats] = {}
    file_reports: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []

    for path in sorted(src.glob("*.xml")):
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError as exc:
            rejected.append({"file": mask_account(path.name), "reason": f"XML parse error: {exc}"})
            continue

        if root.tag != "FlexQueryResponse":
            # e.g. <FlexStatementResponse><Status>Fail</Status><ErrorCode>...
            detail = " ".join(f"{child.tag}={(child.text or '').strip()}" for child in root.iter() if child is not root)
            rejected.append(
                {
                    "file": mask_account(path.name),
                    "reason": mask_account(f"root is <{root.tag}>, not <FlexQueryResponse>. {detail}".strip()),
                }
            )
            continue

        per_file: Counter[str] = Counter()
        for element in root.iter():
            if element.tag in CONTAINER_TAGS:
                continue
            stats.setdefault(element.tag, ElementStats(element.tag)).observe(element, path.name)
            per_file[element.tag] += 1

        statement = root.find(".//FlexStatement")
        file_reports.append(
            {
                "file": mask_account(path.name),
                "query_name": root.get("queryName", ""),
                "type": root.get("type", ""),
                "from_date": statement.get("fromDate", "") if statement is not None else "",
                "to_date": statement.get("toDate", "") if statement is not None else "",
                "when_generated": statement.get("whenGenerated", "") if statement is not None else "",
                "elements": dict(per_file.most_common()),
            }
        )

    return {
        "source_dir": str(src),
        "files_audited": len(file_reports),
        "files_rejected": rejected,
        "file_reports": file_reports,
        "elements": {tag: stats[tag].to_dict() for tag in sorted(stats, key=lambda t: -stats[t].count)},
    }


def render_markdown(inventory: dict[str, Any]) -> str:
    """Render the inventory as a reference document."""
    out: list[str] = []
    add = out.append

    add("# IBKR Flex XML — structure audit")
    add("")
    add("**Generated by** `scripts/audit_flex_xml.py` — re-run it, do not hand-edit.")
    add("")
    add(
        "> **Values are redacted by default.** This audit runs over real account statements. "
        "Only structural enumerations a parser must branch on (`assetCategory`, "
        "`openCloseIndicator`, `levelOfDetail`, `notes`, …) disclose their values; every "
        "other attribute reports shape only, and account numbers are masked. See "
        "`ALWAYS_ENUMERATE` in the generator."
    )
    add("")
    add(
        "This document is derived from the archived statements themselves, not from IBKR's "
        "published field lists. It is the source of truth for `ibkr_core_mcp.flex_schema`, "
        "which generates one table per element type with one column per attribute."
    )
    add("")
    add(
        "Field *meanings* come from IBKR and are cited where they matter: "
        "[Trades report](https://www.ibkrguides.com/reportingreference/reportguide/trades_default.htm) · "
        "[Codes](https://www.ibkrguides.com/reportingreference/reportguide/codes.htm) · "
        "[Flex Queries](https://www.ibkrguides.com/clientportal/performanceandstatements/flex.htm)"
    )
    add("")

    rejected = inventory["files_rejected"]
    add(f"**Files audited:** {inventory['files_audited']}  ·  **rejected:** {len(rejected)}")
    add("")
    if rejected:
        add("## Rejected files")
        add("")
        add("These are not statements and must never be imported:")
        add("")
        for entry in rejected:
            add(f"- `{entry['file']}` — {entry['reason']}")
        add("")

    add("## Statement coverage")
    add("")
    add("| File | Query | Type | From | To | Generated |")
    add("|---|---|---|---|---|---|")
    for report in inventory["file_reports"]:
        add(
            f"| `{report['file']}` | {report['query_name']} | {report['type']} | "
            f"{report['from_date']} | {report['to_date']} | {report['when_generated']} |"
        )
    add("")

    add("## Element inventory")
    add("")
    add("| Element | Rows | Files | Attributes |")
    add("|---|---:|---:|---:|")
    for tag, data in inventory["elements"].items():
        add(f"| `{tag}` | {data['count']:,} | {data['files']} | {data['attribute_count']} |")
    add("")

    for tag, data in inventory["elements"].items():
        add(f"## `<{tag}>` — {data['count']:,} rows, {data['attribute_count']} attributes")
        add("")
        add("| Attribute | Non-empty | % | SQL type | Distinct | Sample / values |")
        add("|---|---:|---:|---|---:|---|")
        attributes = data["attributes"]
        for key in sorted(attributes, key=lambda k: (-attributes[k]["nonempty"], k)):
            info = attributes[key]
            if info["nonempty"] == 0:
                detail = "**never populated in this archive**"
            elif info["values"] and len(info["values"]) <= 12:
                detail = " · ".join(
                    f"`{v}`×{n}" if v else f"`(empty)`×{n}" for v, n in list(info["values"].items())[:12]
                )
            else:
                detail = " · ".join(f"`{s}`" for s in info["samples"])
            add(
                f"| `{key}` | {info['nonempty']:,} | {info['pct_nonempty']:.0f} | "
                f"{info['sql_type']} | {info['distinct']} | {detail} |"
            )
        add("")

    return "\n".join(out) + "\n"


# ── schema generation ────────────────────────────────────────────────────────

# Elements whose rows are keyed by a derived execution key so that the live CP API
# path and the Flex path converge on the same row. Everything else is keyed by a
# deterministic content hash (see `row_uid` in flex_schema).
EXECUTION_KEYED = {"Trade"}

_SNAKE_1 = re.compile(r"(.)([A-Z][a-z]+)")
_SNAKE_2 = re.compile(r"([a-z0-9])([A-Z])")


def snake_case(name: str) -> str:
    """CamelCase / PascalCase / ACRONYMCase → snake_case.

    ibExecID → ib_exec_id · fifoPnlRealized → fifo_pnl_realized · isAPIOrder → is_api_order
    """
    return _SNAKE_2.sub(r"\1_\2", _SNAKE_1.sub(r"\1_\2", name)).lower()


def build_schema(inventory: dict[str, Any]) -> dict[str, Any]:
    """Turn the inventory into a table/column specification, checking for collisions."""
    schema: dict[str, Any] = {}
    for tag, data in inventory["elements"].items():
        columns: dict[str, dict[str, str]] = {}
        collisions: dict[str, list[str]] = defaultdict(list)
        for attr in sorted(data["attributes"]):
            column = snake_case(attr)
            collisions[column].append(attr)
            columns[attr] = {"column": column, "sql_type": data["attributes"][attr]["sql_type"]}
        clashing = {c: a for c, a in collisions.items() if len(a) > 1}
        if clashing:
            raise SystemExit(f"snake_case collision in <{tag}>: {clashing}")
        schema[tag] = {
            "table": f"flex_{snake_case(tag)}",
            "key": "execution_key" if tag in EXECUTION_KEYED else "row_uid",
            "row_count_seen": data["count"],
            "columns": columns,
        }
    return schema


SCHEMA_HEADER = '''"""Flex XML → SQLite schema. GENERATED FILE — do not edit by hand.

Regenerate with::

    python scripts/audit_flex_xml.py --src ~/.ibkr_core/flex_archive

Every attribute IBKR emits gets a column. That is the whole point: the previous
trade dataset was built by a parser that kept 10 of 85 attributes and silently
dropped the rest, and nothing detected it for months. Deriving the column set from
the statements themselves makes "every attribute has a column" a testable invariant
(see tests/test_flex_schema.py) instead of a promise.

Keying
------
``Trade`` is keyed by ``execution_key`` so a fill arriving from the live Client
Portal API and the same fill arriving later from Flex converge on one row:

    execution_key = ibExecID            when non-empty
                  = "flex:" + tradeID   otherwise   (exactly one 2021 trade)

Every other element is keyed by ``row_uid``, a deterministic content hash that also
folds in how many times that exact content has already been seen *within the same
statement*. Byte-identical sibling rows do occur (10 of them, in ``Lot`` and
``WashSale``), so a plain content hash would silently drop them, while a plain
positional key would defeat de-duplication across the overlapping statement windows.
"""
'''


def render_schema_module(schema: dict[str, Any], inventory: dict[str, Any]) -> str:
    """Emit ibkr_core_mcp/flex_schema.py."""
    out = [SCHEMA_HEADER, "", "from __future__ import annotations", "", "from typing import Any", ""]
    out.append(f"#: Source archive audited to build this file: {inventory['files_audited']} statements.")
    out.append("ELEMENTS: dict[str, dict[str, Any]] = {")
    for tag, spec in schema.items():
        out.append(f'    "{tag}": {{')
        out.append(f'        "table": "{spec["table"]}",')
        out.append(f'        "key": "{spec["key"]}",')
        out.append('        "columns": {')
        for attr, info in spec["columns"].items():
            out.append(f'            "{attr}": ("{info["column"]}", "{info["sql_type"]}"),')
        out.append("        },")
        out.append("    },")
    out.append("}")
    out.append("")
    out.append("#: Every attribute name seen in the audited archive, per element.")
    out.append("KNOWN_ATTRIBUTES: dict[str, frozenset[str]] = {")
    for tag, spec in schema.items():
        names = ", ".join(f'"{a}"' for a in sorted(spec["columns"]))
        out.append(f'    "{tag}": frozenset({{{names}}}),')
    out.append("}")
    out.append("")
    return "\n".join(out)


def _canonicalise(path: Path) -> None:
    """Run `ruff format` over a generated file so regeneration round-trips.

    Without this the generator emits one long `frozenset({...})` per element, ruff
    reformats it on the next `ruff format` run, and re-running the generator then
    produces a 900-line diff that is pure whitespace. Formatting at generation time
    means "regenerate and diff" is a meaningful check that the *data* changed.
    """
    import shutil
    import subprocess

    ruff = shutil.which("ruff")
    if not ruff:
        print("  (ruff not found — generated schema left unformatted)")
        return
    subprocess.run([ruff, "format", "--quiet", str(path)], check=False)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", type=Path, default=DEFAULT_SRC)
    parser.add_argument("--json-out", type=Path, default=Path("docs/flex-xml-structure.json"))
    parser.add_argument("--md-out", type=Path, default=Path("docs/flex-xml-structure-audit.md"))
    parser.add_argument("--schema-out", type=Path, default=Path("ibkr_core_mcp/flex_schema.py"))
    args = parser.parse_args(argv)

    if not args.src.is_dir():
        raise SystemExit(f"source directory not found: {args.src}")

    inventory = audit_directory(args.src)

    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(inventory, indent=2, sort_keys=False), encoding="utf-8")
    args.md_out.parent.mkdir(parents=True, exist_ok=True)
    args.md_out.write_text(render_markdown(inventory), encoding="utf-8")

    schema = build_schema(inventory)
    args.schema_out.parent.mkdir(parents=True, exist_ok=True)
    args.schema_out.write_text(render_schema_module(schema, inventory), encoding="utf-8")
    _canonicalise(args.schema_out)

    print(f"Audited {inventory['files_audited']} files from {args.src}")
    if inventory["files_rejected"]:
        print(f"REJECTED {len(inventory['files_rejected'])}:")
        for entry in inventory["files_rejected"]:
            print(f"   {entry['file']}: {entry['reason']}")
    print(f"\n{'element':<32}{'rows':>9}{'attrs':>7}")
    for tag, data in inventory["elements"].items():
        print(f"{tag:<32}{data['count']:>9,}{data['attribute_count']:>7}")
    total_columns = sum(len(spec["columns"]) for spec in schema.values())
    print(f"\n{len(schema)} tables, {total_columns} attribute columns generated")
    print(f"\nJSON   → {args.json_out}\nMD     → {args.md_out}\nSCHEMA → {args.schema_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
