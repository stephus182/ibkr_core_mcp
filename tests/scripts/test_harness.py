"""Characterization tests: prove the `scripts/` harness works before relying on it.

These assert what the code does *today*, unchanged. They exist so that a red test in the
sibling modules means "the guard is missing", not "the import machinery is broken" — the
audit that prompted this work is precisely about not trusting a green run you never
established the meaning of.
"""

from __future__ import annotations

import audit_flex_dataset
import audit_flex_xml
import fetch_flex_archive
import pytest
import rebuild_flex_dataset

pytestmark = pytest.mark.scripts


def test_every_flex_script_imports_and_exposes_a_main():
    """The four CLIs are importable as bare modules via pyproject's pythonpath."""
    for module in (rebuild_flex_dataset, audit_flex_dataset, audit_flex_xml, fetch_flex_archive):
        assert callable(module.main), f"{module.__name__} has no main()"


def test_rebuild_imports_a_synthetic_archive(annual_archive, empty_db):
    """rebuild() reads the archive and writes rows — the baseline behaviour."""
    n_files = len(list(annual_archive.glob("*.xml")))
    summary = rebuild_flex_dataset.rebuild(annual_archive, empty_db, backup=False)
    assert len(summary["imported"]) == n_files
    assert summary["rejected"] == []
    assert summary["rows_stored"]["Trade"] == 4


def test_audit_gate_runs_against_a_rebuilt_database(annual_archive, empty_db):
    """run_gate executes end-to-end and returns an int exit code."""
    rebuild_flex_dataset.rebuild(annual_archive, empty_db, backup=False)
    assert audit_flex_dataset.run_gate(empty_db, annual_archive) in (0, 1)


def test_audit_flex_xml_generates_a_schema_from_a_synthetic_archive(annual_archive, tmp_path):
    """The generator produces a non-empty ELEMENTS when given real statements."""
    inventory = audit_flex_xml.audit_directory(annual_archive)
    assert inventory["files_audited"] == len(list(annual_archive.glob("*.xml")))
    assert inventory["files_rejected"] == []
    assert "Trade" in audit_flex_xml.build_schema(inventory)
