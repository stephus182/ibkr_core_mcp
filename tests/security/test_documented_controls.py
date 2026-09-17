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


def test_the_documented_0600_token_write_lives_where_security_md_says():
    """`SECURITY.md` § OAuth Token File Permissions quotes the `os.open(..., 0o600)` +
    `os.chmod` sequence and names where it lives. That claim had drifted in both
    directions: `cache.GDriveCache._get_service` was still named after it had been
    refactored to delegate, and `web_scraper.WebDocsStore._get_service` was named
    correctly — because it held a third independent copy of the OAuth dance, which is
    exactly what let `b1a4efb`'s `RefreshError` fix reach two call sites out of three
    (WEB-03).

    The control is now in one place. This test fails if a second copy appears, or if the
    one copy moves without the document following it.
    """
    sequence = "os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600"
    package = _ROOT / "ibkr_core_mcp"
    holders = sorted(p.name for p in package.rglob("*.py") if sequence in p.read_text())

    # Two secrets, two writers, and they are different secrets — this test found the second
    # one itself when a first version asserted a single holder and failed.
    #   gdrive_auth.py  the Google Drive OAuth refresh token (this section)
    #   mcp_server.py   the per-launch SSE bearer token (§ Transport Security), whose own
    #                   comment cites gdrive_auth for the same O_CREAT/chmod reasoning
    assert holders == ["gdrive_auth.py", "mcp_server.py"], f"the 0600 write now lives in {holders}"

    # The property that matters for the Drive token: ONE implementation, and neither of the
    # two consumers carries a copy. Both did once; the copy in web_scraper.py is what missed
    # b1a4efb's RefreshError fix.
    for consumer in ("cache.py", "web_scraper.py"):
        assert sequence not in (package / consumer).read_text(), f"{consumer} has its own copy of the token write again"
        assert "load_or_refresh_credentials" in (package / consumer).read_text(), (
            f"{consumer} no longer delegates to gdrive_auth"
        )

    security_md = (_ROOT / "SECURITY.md").read_text()
    section = security_md[security_md.index("### OAuth Token File Permissions") :][:2000]
    assert "gdrive_auth.persist_credentials" in section
    assert "the one place it exists" in section, "the document no longer claims a single holder"


def test_the_architecture_doc_states_the_real_number_of_secret_shapes():
    """A count in a document beside a table in code: it read 14 against a real 13.

    Nobody had checked it, and SEC-06 then moved the real figure to 18 — so the doc was
    wrong before the change and would have stayed wrong after it. The same shape as the
    live-suite size (DOCA-R2) and the coverage headline (DOCB-R1): a number a human must
    remember to update is a number that will be wrong.
    """
    import re

    from .test_error_redaction import SECRETS

    doc = (_ROOT / "docs" / "security-architecture.md").read_text()
    claimed = {int(n) for n in re.findall(r"(\d+) secret shapes", doc)}
    assert claimed, "the architecture doc no longer states a secret-shape count; update or remove this guard"
    assert claimed == {len(SECRETS)}, f"the doc claims {claimed} secret shapes; the table holds {len(SECRETS)}"


# Ungated writes that are POST-as-query: IBKR takes a request body for them because the
# query has parameters, and they change nothing on its servers. Exempt by name with the
# reason written down, the way `test_order_write_boundary.PRE_GATE_EXEMPT` is — an unnamed
# exemption is how an inventory comes to look complete while it is not (SEC-12, SEC-R2).
_POST_AS_QUERY = {
    "get_contract_rules": "POST /iserver/contract/rules — reads order rules for a conid",
    "get_pa_periods_raw": "POST /pa/performance — the unparsed form of get_pa_periods",
    "get_portfolio_allocation": "POST /portfolio/allocation — reads a breakdown for given accounts",
    "run_iserver_scanner": "POST /iserver/scanner/run — runs a market scan, stores nothing",
}

_GATED_ORDER_WRITES = frozenset(
    {
        "place_order",
        "place_order_and_confirm",
        "modify_order",
        "modify_order_and_confirm",
        "cancel_order",
        "reply_order",
    }
)


def _client_write_methods() -> dict[str, list[str]]:
    """Every public `IBKRClient` method that issues a non-GET request.

    Both spellings count. There is no `_delete` helper, so `cancel_order` and
    `delete_watchlist` call `self._session.delete(...)` directly — a first version of this
    probe looked only for `_post`/`_put`/`_delete` helpers and silently missed four methods,
    including a gated one. A probe that cannot see a whole spelling is the defect this file
    exists to catch.
    """
    import ast

    source = (_ROOT / "ibkr_core_mcp" / "client.py").read_text()
    writes: dict[str, list[str]] = {}
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.FunctionDef) or node.name.startswith("_"):
            continue
        verbs = set()
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Call) or not isinstance(sub.func, ast.Attribute):
                continue
            func = sub.func
            if func.attr in {"_post", "_put"}:
                verbs.add(func.attr)
            elif (
                func.attr in {"post", "put", "delete", "patch"}
                and isinstance(func.value, ast.Attribute)
                and func.value.attr == "_session"
            ):
                verbs.add(f"session.{func.attr}")
        if verbs:
            writes[node.name] = sorted(verbs)
    return writes


def test_every_client_write_is_gated_or_named_in_the_inventory():
    """SEC-R2. SECURITY.md's ungated-mutations table listed three of nine.

    None of the missing ones was reachable from the model layer — measured — so the boundary
    held and the *inventory* did not. That is exactly SEC-12's shape one level up: a control
    inventory with a gap reads as complete, and the next reader trusts it.
    """
    inventory = (_ROOT / "SECURITY.md").read_text()
    writes = _client_write_methods()
    assert len(writes) >= 20, f"the write probe found only {len(writes)} methods — it has stopped seeing a spelling"

    unlisted = [
        name
        for name in sorted(writes)
        if name not in _GATED_ORDER_WRITES and name not in _POST_AS_QUERY and f"`{name}`" not in inventory
    ]
    assert not unlisted, (
        f"these client methods write to IBKR but appear nowhere in SECURITY.md: {unlisted}. "
        "Add each to the ungated-mutations table, or to _POST_AS_QUERY with its reason."
    )


def test_the_write_probe_sees_both_spellings():
    """Vacuity guard: the probe must find the gated writes, including the session form."""
    writes = _client_write_methods()
    assert "place_order" in writes and writes["place_order"] == ["_post"]
    assert "cancel_order" in writes and writes["cancel_order"] == ["session.delete"]
    assert "mark_notification_read" in writes and writes["mark_notification_read"] == ["_put"]


_NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9}


def _collapse_home_call_sites() -> dict[str, int]:
    """Every call to `collapse_home` in the package, by file."""
    import ast

    sites: dict[str, int] = {}
    for source_file in sorted((_ROOT / "ibkr_core_mcp").rglob("*.py")):
        calls = 0
        for node in ast.walk(ast.parse(source_file.read_text())):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
            if name == "collapse_home":
                calls += 1
        if calls:
            sites[source_file.name] = calls
    return sites


def test_security_md_states_the_real_number_of_collapse_home_surfaces():
    """SEC-10: `collapse_home` is an inventory of call sites, not a filter, so the inventory
    is the control — and an inventory nobody counts is how this one came to be wrong.

    The function's docstring said it covered "the model or a log"; two log lines wrote the
    absolute path anyway, and the finding named only one of them. A number a human must
    remember to update is a number that will be wrong (DOCA-R2, DOCB-R1, the secret-shape
    count) — so this reads both sides and compares them.
    """
    sites = _collapse_home_call_sites()
    assert sites, "no collapse_home calls found at all — the check would be vacuous"

    text = (_ROOT / "SECURITY.md").read_text()
    stated = re.findall(r"\*\*(\w+) surfaces call it\*\*", text)
    assert len(stated) == 1, f"SECURITY.md states the collapse_home surface count {len(stated)} times, expected once"
    claimed = _NUMBER_WORDS[stated[0].lower()]

    assert claimed == sum(sites.values()), (
        f"SECURITY.md says {stated[0]} surfaces call collapse_home; the package has "
        f"{sum(sites.values())}: {sites}. Add the new one to the inventory and give it a "
        "canary in test_error_redaction.py, or the inventory reads as complete while it is not."
    )
