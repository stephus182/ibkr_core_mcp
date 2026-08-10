"""`audit_flex_xml.py` regenerates `flex_schema.py`; it must not be able to empty it.

The generated module is the single source of truth for every `flex_*` table, and every
downstream consumer agrees with it by construction. So when the generator wrote an empty
`ELEMENTS` from an empty source directory — printing "Audited 0 files" and exiting 0 —
the whole subsystem self-consistently agreed the schema was empty, and no check anywhere
disagreed.

`--src` pointing somewhere plausible-but-wrong is not exotic: the archive lives outside
the repo, and a directory of `<FlexStatementResponse>` error payloads from a failed sync
is the exact case the parser already knows how to reject.
"""

from __future__ import annotations

import audit_flex_xml
import pytest

from ibkr_core_mcp.flex_schema import ELEMENTS
from tests.flex_fixtures import TRUNCATED_XML, WARN_1019_XML, element, statement, trade

pytestmark = pytest.mark.scripts


def _outputs(tmp_path):
    """Redirect all three generated artefacts away from the real repo files."""
    return [
        "--schema-out",
        str(tmp_path / "flex_schema.py"),
        "--json-out",
        str(tmp_path / "structure.json"),
        "--md-out",
        str(tmp_path / "structure.md"),
    ]


def _full_archive(src):
    """One statement per element type, so the generated schema matches the real one."""
    src.mkdir(exist_ok=True)
    for tag in ELEMENTS:
        (src / f"{tag}.xml").write_text(statement(element(tag)), encoding="utf-8")
    return src


# ── refuse to generate from nothing ─────────────────────────────────────────────


def test_refuses_an_empty_source_directory_before_writing_anything(empty_archive, tmp_path, capsys):
    """The out-path must not exist afterwards — refusing after the write is no guard.

    The message is asserted, not just the exit code: an empty source also trips the
    shrink guard (a schema of nothing drops all 14 elements), so a bare `rc == 2` would
    pass even with this guard deleted and could not tell the two apart.
    """
    rc = audit_flex_xml.main(["--src", str(empty_archive), *_outputs(tmp_path)])

    assert rc == 2
    assert "no parseable statements" in capsys.readouterr().out
    assert not (tmp_path / "flex_schema.py").exists(), "schema written despite no source"


def test_refuses_an_archive_of_only_error_payloads(tmp_path):
    """A failed sync leaves a directory of <FlexStatementResponse> error documents."""
    src = tmp_path / "all_errors"
    src.mkdir()
    (src / "a.xml").write_text(WARN_1019_XML, encoding="utf-8")
    (src / "b.xml").write_text(WARN_1019_XML, encoding="utf-8")

    rc = audit_flex_xml.main(["--src", str(src), *_outputs(tmp_path)])

    assert rc == 2
    assert not (tmp_path / "flex_schema.py").exists()


def test_refuses_when_every_file_is_unparseable(tmp_path):
    src = tmp_path / "truncated"
    src.mkdir()
    (src / "a.xml").write_text(TRUNCATED_XML, encoding="utf-8")

    assert audit_flex_xml.main(["--src", str(src), *_outputs(tmp_path)]) == 2


# ── refuse to shrink an existing schema ─────────────────────────────────────────


def test_refuses_to_remove_an_element_from_the_schema(tmp_path):
    """A partial archive must not silently delete tables the schema already has.

    This is the guard a file-count floor cannot provide: a statement containing only
    `<Trade>` passes any "did we read some files?" test while dropping 13 of 14 tables.
    """
    src = tmp_path / "trades_only"
    src.mkdir()
    (src / "a.xml").write_text(statement(trade()), encoding="utf-8")

    rc = audit_flex_xml.main(["--src", str(src), *_outputs(tmp_path)])

    assert rc == 2
    assert not (tmp_path / "flex_schema.py").exists()


def test_refuses_to_remove_an_attribute_from_an_existing_element(tmp_path):
    """Losing columns is as destructive as losing tables, and less visible."""
    src = _full_archive(tmp_path / "missing_attr")
    stripped = trade().replace(' fifoPnlRealized="0"', "")
    (src / "Trade.xml").write_text(statement(stripped), encoding="utf-8")

    rc = audit_flex_xml.main(["--src", str(src), *_outputs(tmp_path)])

    assert rc == 2


def test_allow_shrink_is_the_explicit_override(tmp_path):
    src = tmp_path / "trades_only"
    src.mkdir()
    (src / "a.xml").write_text(statement(trade()), encoding="utf-8")

    rc = audit_flex_xml.main(["--src", str(src), *_outputs(tmp_path), "--allow-shrink"])

    assert rc == 0
    assert (tmp_path / "flex_schema.py").exists()


def test_allows_the_schema_to_grow(tmp_path):
    """Capturing a newly added IBKR attribute is the entire purpose of this script."""
    src = _full_archive(tmp_path / "grown")
    (src / "Trade.xml").write_text(
        statement(trade().replace("<Trade ", '<Trade brandNewIBKRField="42" ')), encoding="utf-8"
    )

    rc = audit_flex_xml.main(["--src", str(src), *_outputs(tmp_path)])

    assert rc == 0
    assert "brandNewIBKRField" in (tmp_path / "flex_schema.py").read_text()


# ── report rejections before destroying anything ────────────────────────────────


def test_reports_rejected_files_before_writing(tmp_path, capsys):
    """A rejection printed after the write is a post-mortem, not a warning."""
    src = _full_archive(tmp_path / "mixed")
    (src / "zz_bad.xml").write_text(WARN_1019_XML, encoding="utf-8")

    audit_flex_xml.main(["--src", str(src), *_outputs(tmp_path)])

    out = capsys.readouterr().out
    assert "REJECTED" in out
    assert out.index("REJECTED") < out.index("generated"), "rejections reported after the write"


def test_a_complete_archive_regenerates_the_same_schema(tmp_path):
    """The happy path must survive all of the above, with no shrink override."""
    src = _full_archive(tmp_path / "complete")

    rc = audit_flex_xml.main(["--src", str(src), *_outputs(tmp_path)])

    assert rc == 0
    generated = (tmp_path / "flex_schema.py").read_text()
    for tag in ELEMENTS:
        assert f'"{tag}"' in generated
