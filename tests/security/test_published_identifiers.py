"""This repository is public. No file it tracks may carry the account holder's real
IBKR account number.

The rule already existed and was already enforced — in exactly one place.
`scripts/audit/capture_live_response_shapes.py` rewrites every account number to
`U1234567` before writing `tests/fixtures/ibkr_live_shapes.json`, and asserts afterwards
that no other one survived. That assertion covers the one file the script writes.

Meanwhile 33 occurrences of the real account number sat in eight tracked files —
two living documents, two unit-test modules and four audit records — published on
2026-09-16 at `github.com/stephus182/ibkr_core_mcp`, visibility PUBLIC. The same shape as
every other finding in this audit: a control that holds on the branch it was written for
and was never swept across the class.

An account number is not a credential; it cannot authenticate or trade. What it does is
name the account holder to their broker, beside a real name and address in every commit.

This test is a guard, not a twelfth security invariant. The eleven are unchanged.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.security

REPO_ROOT = Path(__file__).resolve().parents[2]

# IBKR account numbers are `U` + 7 digits (live) — the shape `client.py` validates.
# Deliberately NOT anchored with `\b` on the left: the first version was, and `_` is a
# word character, so every `flex_U<real>_2026-07-02_2928480049.xml` filename was
# invisible to it — four of the eight offending files, missed by the check written to
# find them. The right-hand guard is a negative lookahead so a longer number is not
# truncated into a false match.
ACCOUNT_SHAPED = re.compile(r"U[0-9]{7}(?![0-9])")

# Fictional numbers this repository uses on purpose. Each is a placeholder in test
# fixtures or documentation examples, never an account that exists.
PLACEHOLDERS = frozenset(
    {
        "U1234567",
        "U0000000",
        "U1111111",
        "U9999999",
    }
)

# `docs/audits/audit-evidence/scrapes/` holds IBKR's own documentation, captured verbatim
# on a dated run. The account numbers in it are IBKR's published examples, not ours, and
# rewriting a capture would falsify the record of what was retrieved (CLAUDE.md).
VERBATIM_CAPTURES = "docs/audits/audit-evidence/scrapes/"

# The fire tests below need an account number that is NOT a placeholder. Writing one as a
# literal put it in this file, this file is tracked, and the scan reads tracked files — so
# the first commit of this test was refused by the pre-push hook, by this test, for
# carrying the very thing it forbids. That is the check working. Assembled at runtime, the
# seven digits never appear together in the source and the exemption list stays tight.
CONTROL_ACCOUNT = "U" + "765" + "4321"


def _tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout
    return [p for p in out.split("\0") if p]


def _account_numbers_in(path: str) -> set[str]:
    try:
        text = (REPO_ROOT / path).read_text(errors="ignore")
    except (OSError, UnicodeDecodeError):
        return set()
    return set(ACCOUNT_SHAPED.findall(text))


def test_the_scanner_actually_reads_the_tree():
    """Vacuity guard. The placeholders are known to be present in the tree, so a run that
    finds none of them found nothing at all and the check below would pass for free."""
    tracked = _tracked_files()
    assert len(tracked) > 100, f"git ls-files returned {len(tracked)} paths"
    seen: set[str] = set()
    for path in tracked:
        seen |= _account_numbers_in(path)
    assert seen >= PLACEHOLDERS, f"placeholders the scanner failed to find: {sorted(PLACEHOLDERS - seen)}"


def test_no_tracked_file_carries_a_real_account_number():
    offenders: dict[str, list[str]] = {}
    for path in _tracked_files():
        if path.startswith(VERBATIM_CAPTURES):
            continue
        found = sorted(_account_numbers_in(path) - PLACEHOLDERS)
        if found:
            offenders[path] = found
    assert not offenders, "real account numbers in a PUBLIC repository: " + "; ".join(
        f"{p} -> {', '.join(v)}" for p, v in sorted(offenders.items())
    )


def test_the_check_fires_on_a_number_that_is_not_a_placeholder(tmp_path):
    """The control. Without it, a scan finding nothing is indistinguishable from a regex
    that matches nothing — which is how the live suite's 38 type-only assertions passed."""
    sample = tmp_path / "leak.md"
    sample.write_text(f"the account is {CONTROL_ACCOUNT} and the placeholder is U1234567\n")
    found = set(ACCOUNT_SHAPED.findall(sample.read_text())) - PLACEHOLDERS
    assert found == {CONTROL_ACCOUNT}


@pytest.mark.parametrize(
    "template",
    [
        "the account is {}",
        "flex_{}_2026-07-02_2928480049.xml",  # `_U` — missed by a `\\b`-anchored pattern
        'data["{}"]["periods"]',
        "{}.Core",
    ],
)
def test_the_check_fires_however_the_number_is_embedded(template):
    """Each spelling below appears in the tree. The `flex_…` one is the reason this test
    exists: the first version of the pattern anchored on `\\b`, and `_` is a word character,
    so it reported four offending files instead of eight."""
    assert set(ACCOUNT_SHAPED.findall(template.format(CONTROL_ACCOUNT))) == {CONTROL_ACCOUNT}


def test_the_pattern_does_not_truncate_a_longer_number():
    """The counter-case for the lookahead. Without it `U12345678` would read as `U1234567`
    — a placeholder — and a genuinely different number would be silently exempted."""
    assert ACCOUNT_SHAPED.findall("U12345678") == []


def test_the_capture_script_still_redacts():
    """The one control that did hold. If this rewrite is ever dropped, the fixture becomes
    a ninth publisher and the test above would be the only thing left."""
    script = (REPO_ROOT / "scripts/audit/capture_live_response_shapes.py").read_text()
    assert '"U1234567"' in script, "the fixture capture no longer rewrites account numbers"


# ── The live-shape fixture ─────────────────────────────────────────────────────
#
# `tests/fixtures/ibkr_live_shapes.json` is 27 IBKR endpoints captured from the account
# holder's own gateway. It is the evidence that caught six broken response models, so it
# is worth keeping — but every value in it was theirs. These tests hold the redaction
# against the committed file, so the capture script's own assertion is no longer the only
# thing standing between a live capture and a public commit.

FIXTURE = REPO_ROOT / "tests/fixtures/ibkr_live_shapes.json"

# Frozen copies of the redactor's two allow-lists. See
# `test_the_redactor_has_not_widened_its_own_exemptions` for why they are duplicated and
# not imported.
#
# Endpoints whose bytes are identical for every IBKR customer — contract and market
# reference data, which names nobody.
PUBLIC_ENDPOINTS = frozenset(
    {
        "search_contract",
        "contract_info",
        "secdef",
        "stocks",
        "currency_pairs",
        "trading_schedule",
        "market_snapshot",
        "scanner_params",
    }
)

# Keys kept inside an owner-scoped payload. Each holds IBKR vocabulary — a currency code,
# an asset class, an envelope label — never an amount, a holding or an identifier.
EXEMPT_KEYS = frozenset(
    {
        "currency",
        "cashccy",
        "sectype",
        "sec_type",
        "assetclass",
        "type",
        "key",
        "secondkey",
        "rowtype",
        "isnull",
        "severity",
        "group",
        "model",
        "__truncated__",
    }
)


def _fixture_scalars():
    import json

    def walk(obj, key=None):
        if isinstance(obj, dict):
            for k, v in obj.items():
                yield from walk(v, k if isinstance(k, str) else None)
        elif isinstance(obj, list):
            for v in obj:
                yield from walk(v, key)
        else:
            yield key, obj

    payload = json.loads(FIXTURE.read_text())
    for endpoint, body in payload.items():
        for key, value in walk(body):
            yield endpoint, key, value


def test_the_fixture_carries_no_owner_scoped_value():
    """Every scalar in an owner-scoped endpoint is a placeholder, a boolean, a 0/1 flag,
    or sits under an explicitly exempted structural key. Nothing else.

    Stated as `is a placeholder` rather than `differs from the original`, because the
    second form passes for a value that was never captured at all, and the first does not.
    """
    allowed = {"REDACTED", "1111.11", "U1234567", 1111111, 1111.11}
    survivors = [
        (endpoint, key, value)
        for endpoint, key, value in _fixture_scalars()
        if endpoint not in PUBLIC_ENDPOINTS
        and not (isinstance(value, bool) or value is None)
        and value not in allowed
        and value not in (0, 1)
        and not (key and key.lower() in EXEMPT_KEYS)
    ]
    assert not survivors, f"real values in a published fixture: {survivors[:10]}"


def test_the_redactor_has_not_widened_its_own_exemptions():
    """The lists above are frozen HERE, deliberately duplicated from the redactor.

    The first version of this file imported `STRUCTURAL` and `PUBLIC_ENDPOINTS` from
    `redact_live_payload.py` and exempted whatever they contained. Re-adding `fullname` to
    the redactor — the exact bug that published `GLD` and `IGV` as holdings — therefore
    widened the code and the test that checks it in one edit, and the mutant survived. A
    test that reads its own oracle from the thing under test cannot fail.

    Adding an exemption is now a two-file change, and the second file is this one, where
    the reason has to be written down.
    """
    import sys

    sys.path.insert(0, str(REPO_ROOT / "scripts/audit"))
    import redact_live_payload

    assert {k.lower() for k in redact_live_payload.STRUCTURAL} == EXEMPT_KEYS, (
        "the redactor's exemption list no longer matches the frozen list in this test"
    )
    assert set(redact_live_payload.PUBLIC_ENDPOINTS) == PUBLIC_ENDPOINTS, (
        "the redactor's public-endpoint list no longer matches the frozen list in this test"
    )


def test_the_fixture_scan_is_not_vacuous():
    """If the walker returns nothing, or the fixture has lost its endpoints, the test above
    passes for free — which is precisely how the original redaction assertion passed."""
    import json

    payload = json.loads(FIXTURE.read_text())
    assert len(payload) >= 40, f"the fixture has lost endpoints: {len(payload)}"

    scalars = list(_fixture_scalars())
    assert len(scalars) > 1000, f"the fixture walk found {len(scalars)} scalars"

    # Counted from the file, not from the walk: these endpoints were captured as empty
    # containers and yield no scalars at all, so a walk-derived endpoint count runs short.
    # Recorded here because the first version of this guard asserted the walk count and
    # failed for that reason.
    #
    # The set changed on 2026-09-17's re-capture: `trading_schedule` left it (141 entries
    # this time, against the empty list TOOL-R1 recorded for SMART) and `pa_transactions`
    # joined it. Two endpoints are absent from the fixture entirely rather than empty:
    # `unread_count`, which answered HTTP 423 `{"status":"waiting for reply"}` on every
    # attempt — the same flakiness TOOL-12 measured over four consecutive tries against a
    # healthy authenticated gateway — and `event_contracts`, which was removed outright on
    # 2026-09-17: it called a path absent from IBKR's documentation, and the `/forecast/*`
    # endpoints that replaced it need a subscription this account does not hold (API-R4).
    walked = {e for e, _, _ in scalars}
    assert set(payload) - walked == {"combo_positions", "pa_transactions", "positions_by_conid"}


@pytest.mark.parametrize(
    "needle",
    [
        "Stephane",
        "Menard",  # the account holder's legal name, in accountTitle and displayName
        "52054",  # net liquidation value
        "21985",  # total cash / settled cash
        "176643",  # buying power
        "00010181.",  # IBKR execution IDs on four real futures fills
        "CLAUDIA-",  # the consuming app's order reference on a resting order
    ],
)
def test_the_specific_values_that_were_published_are_gone(needle):
    """Named one by one, from the diff of what commit `ffd6014` actually pushed. A class
    test can be satisfied by a rule that happens to cover the class; this cannot."""
    assert needle not in FIXTURE.read_text(), f"{needle!r} is still in the fixture"


def test_the_fixture_still_validates_against_the_models():
    """The counter-case. A redactor that emptied the file would pass every test above.
    `tests/test_models_live_shapes.py` is the real guard — 32 tests that parse these
    payloads — and this asserts the fixture is still substantial enough to feed it."""
    import json

    payload = json.loads(FIXTURE.read_text())
    assert len(json.dumps(payload)) > 20_000, "the fixture has been gutted, not redacted"
    assert payload["positions"] and payload["trades"] and payload["account_summary"]
