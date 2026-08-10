"""`audit_flex_dataset.py` prints "N/N checks passed" — N must not be self-selected.

The gate's denominator used to be "however many checks happened to run". The calendar-year
reconciliation — the most important check in the file, the one whose comment explains why
the per-statement checks are insufficient — sat inside `if annual:` and simply vanished
when no annual statement was found, leaving a summary that was *true* about a set that no
longer contained it.

The other half of the same defect: check 15's passing evidence was the string literal
`"222 attributes across 14 elements"`, printed identically whether it compared 222
attributes or zero.
"""

from __future__ import annotations

import sqlite3

import audit_flex_dataset
import pytest
import rebuild_flex_dataset

from tests.flex_fixtures import WARN_1019_XML

pytestmark = pytest.mark.scripts


@pytest.fixture
def built(annual_archive, empty_db):
    """A database rebuilt from the synthetic archive — the gate's normal input."""
    rebuild_flex_dataset.rebuild(annual_archive, empty_db, backup=False)
    return annual_archive, empty_db


# ── the Gate itself ─────────────────────────────────────────────────────────────


def test_gate_fails_when_an_expected_check_never_runs():
    """A discovery step that finds nothing must be a failed check, not no check."""
    gate = audit_flex_dataset.Gate(expected=frozenset({"a.", "b."}))
    gate.check("a. ran", True)

    gate.finalize()

    assert gate.failed == 1
    assert any("b." in name for ok, name, _ in gate.results if not ok)


def test_gate_counts_every_expected_check_in_the_denominator():
    gate = audit_flex_dataset.Gate(expected=frozenset({"a.", "b."}))
    gate.check("a. ran", True)
    gate.finalize()

    assert len(gate.results) == 2, "the vanished check left the denominator too"


def test_gate_rejects_an_unregistered_check_id():
    """A typo'd or unlisted id must fail loudly, not quietly join the tally."""
    gate = audit_flex_dataset.Gate(expected=frozenset({"a."}))

    with pytest.raises(KeyError, match="zz."):
        gate.check("zz. never registered", True)


def test_gate_rejects_a_duplicate_non_family_check_id():
    """Two different checks sharing one id is what made '17.' ambiguous across runs."""
    gate = audit_flex_dataset.Gate(expected=frozenset({"a."}))
    gate.check("a. first", True)

    with pytest.raises(ValueError, match="a."):
        gate.check("a. second, different check", True)


def test_gate_allows_a_declared_family_to_repeat():
    """Per-element and per-year checks legitimately repeat their id."""
    gate = audit_flex_dataset.Gate(expected=frozenset({"16."}), families=frozenset({"16."}))
    gate.check("16. flex_trade", True)
    gate.check("16. flex_lot", True)
    gate.finalize()

    assert gate.failed == 0
    assert len(gate.results) == 2


def test_every_check_the_script_runs_is_registered(built):
    """EXPECTED_CHECKS must not drift from the checks actually in the file."""
    src, db = built
    audit_flex_dataset.run_gate(db, src)  # raises KeyError on any unregistered id


# ── annual-window discovery ─────────────────────────────────────────────────────


def test_annual_windows_returns_nothing_for_quarterly_only():
    rows = [("20260101", "20260331"), ("20260401", "20260630")]
    assert audit_flex_dataset.annual_windows(rows) == []


def test_annual_windows_rejects_a_start_one_day_past_the_window():
    """A re-pull producing fromDate=20260108 silently removed the reconciliation."""
    assert audit_flex_dataset.annual_windows([("20260107", "20261231")])
    assert audit_flex_dataset.annual_windows([("20260108", "20261231")]) == []


def test_annual_windows_survives_a_null_to_date():
    """A NULL stmt_to_date used to raise TypeError, crashing the whole audit."""
    assert audit_flex_dataset.annual_windows([("20240102", None)]) == []
    assert audit_flex_dataset.annual_windows([(None, "20241231")]) == []


def test_annual_windows_finds_a_real_annual_statement():
    assert audit_flex_dataset.annual_windows([("20240102", "20241231")]) == [("2024", "20240102", "20241231")]


def test_gate_fails_when_no_annual_statement_is_found(built, capsys):
    """An archive of only partial statements must report the loss, not hide it.

    Asserted on the named check, not just the exit code: with no annual window the 17c
    family also never runs and `finalize` fails it, so `rc == 1` alone would pass even
    with the discovery check deleted.
    """
    src, db = built
    conn = sqlite3.connect(db)
    conn.execute("UPDATE flex_trade SET stmt_from_date='20260401', stmt_to_date='20260630'")
    conn.commit()
    conn.close()

    rc = audit_flex_dataset.run_gate(db, src)

    assert rc == 1
    assert "[FAIL] 17a." in capsys.readouterr().out


# ── check 15: measured evidence, not a literal ──────────────────────────────────


def test_check_15_evidence_counts_the_actual_source(built, capsys):
    src, db = built
    audit_flex_dataset.run_gate(db, src)

    out = capsys.readouterr().out
    assert "222 attributes across 14 elements" not in out, "hardcoded evidence survived"
    assert "15. every XML attribute has a schema entry" in out


def test_check_15_fails_when_the_source_yielded_no_attributes(built, tmp_path, capsys):
    """Zero attributes compared is not a pass — it is nothing to compare.

    Asserted on check 15 by name: an empty source fails many checks, so `rc == 1` would
    pass even with the vacuous-truth hole reopened.
    """
    src, db = built
    bare = tmp_path / "bare"
    bare.mkdir()

    rc = audit_flex_dataset.run_gate(db, bare)

    assert rc == 1
    assert "[FAIL] 15. every XML attribute has a schema entry" in capsys.readouterr().out


# ── the archive itself must be sound and current ────────────────────────────────


def test_archive_with_an_error_payload_fails_the_gate(built):
    """source_truth counted rejects into a number it then returned and never read."""
    src, db = built
    (src / "flex_U0000000_2026-07-02_2928480049.xml").write_text(WARN_1019_XML, encoding="utf-8")

    rc = audit_flex_dataset.run_gate(db, src)

    assert rc == 1


def test_archive_missing_an_imported_statement_fails_the_gate(built):
    """The stale-archive case: the audit compared against an out-of-date source.

    Found live on 2026-08-10 — the production archive was one statement behind the
    database, so five checks failed and named a data problem that did not exist.
    """
    src, db = built
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO flex_import_log (filename, sha256, trade_id_count, raw_trade_count, "
        "source, imported_at, verified_at) VALUES (?,?,?,?,?,?,?)",
        ("flex_U0000000_2026-08-06_4602951826.xml", "abc", 1, 1, "auto", "2026-08-06", "2026-08-06"),
    )
    conn.commit()
    conn.close()

    rc = audit_flex_dataset.run_gate(db, src)

    assert rc == 1


def test_null_statement_window_fails_the_gate(built, capsys):
    """NULL window dates silently removed 17c and crashed on 17d; now they are named.

    Asserted on check 22 specifically — a NULL window also empties the annual discovery,
    so the exit code alone cannot show that the missing dates were themselves reported.
    """
    src, db = built
    conn = sqlite3.connect(db)
    conn.execute("UPDATE flex_trade SET stmt_to_date=NULL")
    conn.commit()
    conn.close()

    rc = audit_flex_dataset.run_gate(db, src)

    assert rc == 1
    assert "[FAIL] 22. every Flex row records a complete statement window" in capsys.readouterr().out


# ── the audit must never write ──────────────────────────────────────────────────


def test_audit_opens_the_database_read_only(built, monkeypatch):
    """Asserted on the connect string, because 'nothing changed' passes either way.

    A hash comparison alone cannot distinguish `mode=ro` from a read-write connection
    that happens not to write — so the binding assertion is the URI itself.
    """
    src, db = built
    opened = []
    real_connect = sqlite3.connect

    def spy(target, *args, **kwargs):
        opened.append(str(target))
        return real_connect(target, *args, **kwargs)

    monkeypatch.setattr("audit_flex_dataset.sqlite3.connect", spy)
    audit_flex_dataset.run_gate(db, src)

    assert opened and all("mode=ro" in target for target in opened), opened


def test_a_clean_rebuild_passes_the_gate(built):
    """The happy path must survive every new refusal added above."""
    src, db = built
    assert audit_flex_dataset.run_gate(db, src) == 0
