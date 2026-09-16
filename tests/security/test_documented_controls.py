"""SECURITY.md's control inventory must match the code it describes.

**This is a documentation-accuracy check, not one of the eleven invariants.** The invariants
are listed in SECURITY.md § Security Regression Suite; nothing here adds to that list. It
exists because a *stale copy of a control* is its own failure mode, and this repository has
now produced that failure three times: the per-endpoint rate-limit table (API-03), the
Wilder seeding described in prose beside code that did something else, and this one.

The finding (DOCA-01, 2026-09-16): SECURITY.md printed the order-id mitigation as

    _ORDER_ID_RE = re.compile(r"^\\d+$")

while `client.py` had `r"^[0-9]+$"`. The two are not equivalent. Python's `\\d` matches any
Unicode decimal digit and `int()` accepts them, so `\\d+` admits Arabic-Indic "١٢٣" (int
reads 123) and the mixed "1٢2" (int reads **122** — a different order id than the string
appears to name). The documented mitigation was therefore weaker than the implemented one,
and a reader copying it would have reintroduced the gap that audit 2026-07-11 H-2 closed —
a gap whose fix that same file records further down.
"""

import pathlib
import re

import pytest

pytestmark = pytest.mark.security

_RE_DEFINITION = re.compile(r"^(_\w+_RE)\s*=\s*re\.compile\((r?[\"'].*?[\"'])\)", re.M)
_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _documented_identifier_regexes() -> dict[str, str]:
    """The regexes SECURITY.md presents as the current path-traversal mitigation.

    Read from the fenced block that follows the confused-deputy bullet, and deliberately
    NOT from the whole file: the audit log at the end quotes historical values on purpose,
    and rewriting a record of what happened would be worse than the drift this guards.
    """
    text = (_ROOT / "SECURITY.md").read_text()
    marker = "_ACCOUNT_ID_RE"
    assert marker in text, "SECURITY.md no longer shows the identifier regexes at all"
    block = marker + text.split(marker, 1)[1].split("```", 1)[0]
    return dict(_RE_DEFINITION.findall(block))


def _implemented_identifier_regexes() -> dict[str, str]:
    """Every `_*_RE` actually compiled in client.py."""
    return dict(_RE_DEFINITION.findall((_ROOT / "ibkr_core_mcp" / "client.py").read_text()))


def test_security_md_quotes_the_identifier_regexes_verbatim():
    """Each documented regex must be character-for-character what the code compiles."""
    documented = _documented_identifier_regexes()
    implemented = _implemented_identifier_regexes()

    assert documented, "no regexes parsed out of SECURITY.md — the check would be vacuous"

    for name, shown in documented.items():
        assert name in implemented, f"SECURITY.md documents {name}, which client.py no longer defines"
        assert shown == implemented[name], (
            f"SECURITY.md shows {name} = {shown} but client.py compiles {implemented[name]}. "
            "A documented mitigation that differs from the implemented one is a trap for "
            "whoever copies it."
        )


def test_every_implemented_identifier_regex_is_documented():
    """The other direction: a new path-interpolated identifier must not be added to the
    code and left out of the control inventory, which would make the inventory read as
    complete while it is not."""
    documented = _documented_identifier_regexes()
    implemented = _implemented_identifier_regexes()

    missing = sorted(set(implemented) - set(documented))
    assert not missing, f"client.py compiles {missing}, absent from SECURITY.md's mitigation block"


def test_the_documented_order_id_regex_rejects_unicode_digits():
    """States the property the character class exists for, rather than only comparing
    strings — so this still means something if the spelling changes."""
    documented = _documented_identifier_regexes()
    order_id = re.compile(documented["_ORDER_ID_RE"].lstrip("r").strip("\"'"))

    assert order_id.match("123"), "ASCII digits must be accepted"
    for unicode_digits in ("١٢٣", "१२३", "1٢2"):
        assert int(unicode_digits) is not None, "int() accepts these, which is the danger"
        assert not order_id.match(unicode_digits), (
            f"the documented regex admits {unicode_digits!r}, which int() silently converts"
        )


def test_every_security_test_file_appears_in_the_suite_inventory():
    """SECURITY.md's suite table must list every file that runs under `-m security`.

    The table reads as the inventory of this suite, so a file missing from it makes the
    inventory look complete while it is not — the same defect as invariant 9 being listed
    in the constitution with no test behind it (SEC-04). This file was itself the missing
    one: it was added during the 2026-09-16 audit and left out of the table it exists to
    police, which is how it got written.
    """
    table = (_ROOT / "SECURITY.md").read_text().split("## Security Regression Suite")[1]
    documented = set(re.findall(r"^\| `(test_\w+\.py)`", table, re.M))
    on_disk = {p.name for p in (_ROOT / "tests" / "security").glob("test_*.py")}

    assert on_disk, "no security test files found — the check would be vacuous"
    assert on_disk - documented == set(), (
        f"security tests missing from SECURITY.md's suite table: {sorted(on_disk - documented)}"
    )
    assert documented - on_disk == set(), (
        f"SECURITY.md lists suite files that do not exist: {sorted(documented - on_disk)}"
    )
