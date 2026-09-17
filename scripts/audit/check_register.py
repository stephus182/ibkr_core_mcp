"""Reconcile the release-readiness audit's register against its own per-finding list.

The register states counts per domain; a separate table lists every open finding by id.
Two representations of one fact, maintained by hand, in a document whose whole purpose is
finding exactly that defect — and on 2026-09-17 they diverged, the register saying 11 open
while the list still showed 18, because a session closed seven findings and updated only
the counts. The same shape as WEB-03 ("a fix that reached two of three copies") and API-05
("page 0 = first 30" surviving in the second of two files).

So the per-finding table is the source of truth for WHICH findings are open, and the
register's counts are checked against it rather than kept in parallel.

Run: python scripts/audit/check_register.py [path-to-audit.md]
Exit code 0 when every representation agrees, 1 otherwise, with each disagreement named.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

_DEFAULT = Path(__file__).resolve().parents[2] / "docs/audits/release-readiness-audit-2026-09-16.md"
# `DOCB-R1`, not `DOCB-R-1`: the re-derived series has no second hyphen, and a pattern
# demanding one silently skipped all 19 of them on 2026-09-17, which made a reconciliation
# look 21 short. The negative lookahead drops `SEC-2026`-shaped date fragments.
_ID_RE = r"(?:SEC|WEB|TOOL|API|DATA|DOCA|DOCB)-R?(?!20[0-9]{2}\b)[0-9]+"
_ID = re.compile(rf"`({_ID_RE})`")

# Named only as the endpoints of a written-off range, so they carry no claim and were never
# fixed. "Written off" is not "closed": these must not be counted as either.
_WRITTEN_OFF_ENDPOINTS = frozenset(
    {"DATA-03", "DATA-06", "DATA-10", "DATA-11", "DATA-18", "DATA-19", "DOCA-03", "DOCB-02"}
)


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _register_rows(text: str) -> tuple[dict[str, tuple[int, ...]], tuple[int, ...]]:
    """Domain -> (total, closed, open, no-claim, written-off), plus the stated Total row."""
    start = text.index("| Domain | Total | Closed |")
    block = text[start : text.index("\n\n", start)]
    rows: dict[str, tuple[int, ...]] = {}
    stated: tuple[int, ...] = ()
    for line in block.splitlines():
        cells = _cells(line)
        if len(cells) != 6 or cells[1] in ("Total", "---:", "---"):
            continue

        def num(cell: str) -> int:
            m = re.search(r"\d+", cell.replace("**", ""))
            return int(m.group()) if m else 0

        values = tuple(num(c) for c in cells[1:])
        if "Total" in cells[0]:
            stated = values
        else:
            rows[cells[0].strip("`*")] = values
    return rows, stated


def _open_ids(text: str) -> list[str]:
    """Every finding id in the per-finding open table, which starts at the TOOL-01 row."""
    start = text.index("| ID | Sev | Claim, in brief |")
    block = text[start : text.index("\n\n", start)]
    ids: list[str] = []
    for line in block.splitlines():
        if line.startswith("|") and (found := _ID.search(line)):
            ids.append(found.group(1))
    return ids


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else _DEFAULT
    text = path.read_text()
    rows, stated = _register_rows(text)
    ids = _open_ids(text)

    problems: list[str] = []

    summed = tuple(sum(v[i] for v in rows.values()) for i in range(5))
    if summed != stated:
        problems.append(f"register rows sum to {summed} but the Total row states {stated}")

    total, closed, open_, no_claim, written_off = stated
    if closed + open_ + 1 + no_claim + written_off != total:
        problems.append(f"{closed} + {open_} + 1 partial + {no_claim} + {written_off} != {total}")

    # The per-finding table carries the partial (API-11) alongside the open ones.
    listed = [i for i in ids if i != "API-11"]
    if len(listed) != open_:
        problems.append(f"register says {open_} open; the per-finding table lists {len(listed)}: {sorted(listed)}")

    # Every closed finding must have a written identity somewhere in the document. A closure
    # with no id is one nobody can re-verify later, which is what this whole pass was about.
    named = set(re.findall(_ID_RE, text)) - set(ids) - _WRITTEN_OFF_ENDPOINTS
    if len(named) != closed:
        problems.append(f"register says {closed} closed; {len(named)} closed findings are named in the document")

    per_domain = Counter(i.split("-")[0] for i in listed)
    for domain, values in rows.items():
        if domain.endswith("-R"):
            continue
        if per_domain.get(domain, 0) != values[2]:
            problems.append(f"{domain}: register says {values[2]} open, the table lists {per_domain.get(domain, 0)}")

    if problems:
        print(f"REGISTER INCONSISTENT ({len(problems)}):")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(
        f"register consistent: {total} findings, {closed} closed, {open_} open (+1 partial), {written_off} written off"
    )
    print(f"per-finding table lists {len(listed)} open ids, matching the register")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
