"""`scripts/audit/check_register.py` — the register's own consistency guard, proven able to fire.

Session 13 (2026-09-17) recorded the first open re-derived findings (`API-R7…R11`,
`TOOL-R4…R6`, `SEC-R6/R7`, `DATA-R6/R7`) and the checker rejected the honest table: it
attributed an open `API-R7` to the `API` row and skipped every `-R` row, so a table with one
row per series could not be consistent unless the count sat on the wrong row. It keys on the
series now. These two tests hold that, and hold that it still fires when a count is wrong.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts/audit"))

import check_register as cr  # noqa: E402

pytestmark = pytest.mark.scripts


def _register(api_open: int, api_r_open: int) -> str:
    """A minimal register: a base row, a re-derived row, and two open re-derived findings."""
    return f"""# register

| Domain | Total | Closed | Open, with a claim | No claim recorded | Written off |
|---|---:|---:|---:|---:|---:|
| `API` | 2 | 2 | {api_open} | — | — |
| `API-R` | 3 | 1 | {api_r_open} | — | — |
| **Total** | **5** | **3** | **{api_open + api_r_open}** | **0** | **0** |

### Open findings that do have a claim

| ID | Sev | Claim, in brief |
|---|---|---|
| `API-R2` | Low | open |
| `API-R3` | Nit | open |

Closed and named: `API-1`, `API-2`, `API-R1`.
"""


def test_open_re_derived_findings_are_attributed_to_their_own_row(tmp_path, capsys):
    """`API-R2` and `API-R3` open belong to the `API-R` row, not to `API`."""
    path = tmp_path / "audit.md"
    path.write_text(_register(api_open=0, api_r_open=2))

    assert cr.main(["check_register", str(path)]) == 0, capsys.readouterr().out


def test_a_wrong_open_count_on_a_re_derived_row_is_named(tmp_path, capsys):
    """The sums still agree, so only the per-series check can catch this — and it must."""
    path = tmp_path / "audit.md"
    path.write_text(_register(api_open=1, api_r_open=1))

    assert cr.main(["check_register", str(path)]) == 1
    assert "API-R: register says 1 open, the table lists 2" in capsys.readouterr().out
