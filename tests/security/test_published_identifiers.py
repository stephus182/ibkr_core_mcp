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

# The account class the capture redactor masks — `U` + six to nine digits — and nothing
# narrower: the two controls cover one class, held byte-for-byte by
# `test_the_guard_covers_exactly_the_class_the_redactor_masks`. Until 2026-09-17 this was
# `U` + exactly seven digits, with a comment attributing that shape to `client.py`, whose
# `_ACCOUNT_ID_RE` is a path-safety allow-list (`^[A-Z0-9]{4,12}$`) and says nothing about
# how long an account number is (SEC-R6). A paper account (`DU…`) is found through its
# `U` + digits tail, since the left side is unanchored.
#
# Deliberately NOT anchored with `\b` on the left: the first version was, and `_` is a
# word character, so every `flex_U<real>_2026-07-02_2928480049.xml` filename was
# invisible to it — four of the eight offending files, missed by the check written to
# find them. The right-hand guard is a negative lookahead so a longer number is not
# truncated into a false match. `[0-9]`, not `\d`, for the reason SECURITY.md records
# for `_NUMERIC_PATH_SEGMENT_RE`.
ACCOUNT_SHAPED = re.compile(r"U[0-9]{6,9}(?![0-9])")

# Fictional numbers this repository uses on purpose. Each is a placeholder in test
# fixtures or documentation examples, never an account that exists.
PLACEHOLDERS = frozenset(
    {
        "U1234567",
        "U0000000",
        "U1111111",
        "U9999999",
        # Six-digit placeholders, in the class since the guard widened (SEC-R6):
        # `tests/claude_tools/test_trades.py`'s two fake accounts and the `DU123456`
        # paper-account example in `tests/test_client.py`.
        "U123456",
        "U999999",
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


@pytest.mark.parametrize("digits", [6, 7, 8, 9])
def test_the_check_fires_on_every_length_the_redactor_masks(digits):
    """SEC-R6. The first version of this guard matched `U` + exactly seven digits while the
    redactor masks six to nine, so a six- or eight-digit id would have passed the guard the
    capture script refuses. Assembled at runtime for the same reason as `CONTROL_ACCOUNT`."""
    number = "U" + ("98" + "7654321")[:digits]
    assert len(number) == digits + 1
    assert set(ACCOUNT_SHAPED.findall(f"account {number} here")) - PLACEHOLDERS == {number}


def test_the_pattern_does_not_truncate_a_longer_number():
    """The counter-case for the lookahead. Without it an eight-digit number would read as
    its first seven digits — possibly a placeholder — and a genuinely different number
    would be silently exempted; and a ten-digit one, outside the class, would read as a
    nine-digit id it is not."""
    eight = CONTROL_ACCOUNT + "0"
    ten = CONTROL_ACCOUNT + "000"
    assert ACCOUNT_SHAPED.findall(eight) == [eight]
    assert ACCOUNT_SHAPED.findall(ten) == []


def test_the_guard_covers_exactly_the_class_the_redactor_masks():
    """SEC-R6. Two controls, one class: what the redactor rewrites before the fixture is
    written is what this guard refuses in a tracked file. The pattern is frozen HERE, not
    imported, for the reason `test_the_redactor_has_not_widened_its_own_exemptions` gives
    — so narrowing the redactor is a two-file change — and compared byte-for-byte, so the
    two cannot drift by a digit again."""
    import sys

    sys.path.insert(0, str(REPO_ROOT / "scripts/audit"))
    import redact_live_payload

    assert ACCOUNT_SHAPED.pattern == redact_live_payload.ACCOUNT_ID_RE.pattern, (
        "the committed-file guard and the capture redactor no longer match the same account class"
    )
    # And the property, stated on probes rather than on spelling: every length the
    # redactor rewrites, this guard finds; every length it leaves, this guard leaves.
    for digits in range(4, 12):
        number = "U" + ("98" + "76543210" + "9")[:digits]
        masked = redact_live_payload.ACCOUNT_ID_RE.sub("X", number) != number
        found = bool(ACCOUNT_SHAPED.findall(number))
        assert masked == found, f"{digits} digits: redactor masks={masked}, guard finds={found}"


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


# ── Captured payloads OUTSIDE the fixture ─────────────────────────────────────
#
# Added 2026-09-21, after real account balances — equity with loan value, Commodities net
# liquidation value, initial and maintenance margin — were committed to this PUBLIC
# repository inside a hand-written test constant called `LIVE_PREVIEW_ACCEPTED`.
#
# Everything above guards `tests/fixtures/ibkr_live_shapes.json` and **only** that file.
# It passed while the leak sat two directories away. The control covered the instance, not
# the class.
#
# A full solution would recognise a captured IBKR payload anywhere in the suite, which is
# not decidable from source. This is the tractable part of it: a constant whose NAME claims
# live provenance must say which kind it is. Naming something `LIVE_*` and pasting real
# figures into it is exactly the mistake that happened, and it now fails here until the
# author declares the constant synthetic — a line a reviewer can see.
#
# Limits, stated so this is not mistaken for more than it is:
#   * it keys on the NAME. A real payload in a constant called `_SAMPLE` is not caught.
#   * it does not inspect values. A constant declared synthetic is taken at its word.
# What it does buy: you cannot add a payload that *claims* to be live without a deliberate,
# reviewable declaration, and the declaration is where "did you redact this?" gets asked.

# Constants whose name says LIVE and whose values are FABRICATED. Each needs a reason.
SYNTHETIC_LIVE_CONSTANTS = {
    # Keys and nesting captured from the whatif on 2026-09-21; every figure replaced.
    # The shape is what catches a reader indexing keys IBKR does not send, so the numbers
    # carry no weight — and a whatif response is nothing but account balances.
    ("tests/claude_tools/test_orders.py", "LIVE_PREVIEW_ACCEPTED"),
    ("tests/claude_tools/test_orders.py", "LIVE_PREVIEW_REFUSED"),
    # One alert detail body. Pre-dates this control; kept as declared rather than silently
    # grandfathered, so its provenance is written down like the others.
    ("tests/claude_tools/test_alerts.py", "_LIVE_ALERT_DETAIL"),
}


def _live_named_constants():
    """Module-level constants in tests/ whose name claims live provenance."""
    import ast

    for path in sorted((REPO_ROOT / "tests").rglob("*.py")):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:  # pragma: no cover - a broken test file fails elsewhere
            continue
        for node in tree.body:
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Dict | ast.List):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name) and "LIVE" in target.id.upper():
                    yield str(path.relative_to(REPO_ROOT)), target.id


def test_every_live_named_payload_constant_is_declared_synthetic():
    """A `LIVE_*` constant written as a dict/list LITERAL must be declared synthetic.

    Fails for a NEW `LIVE_*` payload nobody has declared — the 2026-09-21 mistake, caught
    where it would be made rather than after it is published.

    **There is deliberately no exemption for "the file reads the fixture".** The first
    version of this test had one — `"ibkr_live_shapes" not in path.read_text()` — and it
    made the whole control VACUOUS: `test_orders.py` mentions that filename in a comment,
    so the mistake this test exists to catch walked straight through it. Proven by
    re-running the check with the declaration removed: it reported nothing.

    None is needed. `_live_named_constants` only yields dict/list **literals**; a constant
    built from the fixture is a Call (`json.loads(...)`) and is never yielded. So the
    scanner cannot see a registry-derived constant, and every literal it does see is a
    hand-written payload that has to be declared.
    """
    undeclared = [
        (path, name) for path, name in _live_named_constants() if (path, name) not in SYNTHETIC_LIVE_CONSTANTS
    ]
    assert not undeclared, (
        "payload constants claim live provenance but are not declared synthetic and do not "
        f"read the redacted fixture: {undeclared}. Either build it from "
        "tests/fixtures/ibkr_live_shapes.json, or add it to SYNTHETIC_LIVE_CONSTANTS with "
        "the reason its values are fabricated. Real account figures must not be committed: "
        "both repositories are public."
    )


def test_the_declared_synthetic_list_has_not_gone_stale():
    """A declaration for a constant that no longer exists is a stale exemption — it reads
    as coverage and provides none, the same failure this whole file exists to prevent."""
    present = set(_live_named_constants())
    stale = [entry for entry in SYNTHETIC_LIVE_CONSTANTS if entry not in present]
    assert not stale, f"declared synthetic, but no longer in the tree: {stale}"


def test_the_live_constant_scan_is_not_vacuous():
    """If the walker finds nothing, both tests above pass for free."""
    found = list(_live_named_constants())
    assert len(found) >= 3, f"the scan found {len(found)} live-named constants: {found}"


# ---------------------------------------------------------------------------------------
# The CLASS the account-number guard does not cover: IBKR order and alert ids, and account
# balance figures. Added 2026-09-22.
#
# Why this exists. `ACCOUNT_SHAPED` matches `U[0-9]{6,9}` and nothing else, so on 2026-09-22
# a sweep found seven tracked files publishing identifiers from the owner's live account —
# four order ids, one alert id (six times), and a pair of margin figures duplicated in the
# CHANGELOG and in `claude_tools.py` — with the whole suite green throughout. Commit
# 7209ce1, whose own message is "remove real account figures from test fixtures and
# CHANGELOG", had scrubbed two numbers 48 lines away from a pair it left untouched.
#
# That is the same failure mode this file already records for the account-number pattern
# (SEC-13: "a control scoped to one field class is not a control"), one field class over.
#
# An order id is not a credential — it cannot be acted on without the account and a session
# — but CLAUDE.md's standing rule for this PUBLIC repository names it explicitly alongside
# balances, positions, P&L and fill history, and the rule is what is being enforced here.
#
# The approach is deliberately a DENY-LIST OF KNOWN-REAL VALUES rather than a shape pattern.
# A bare 10-digit number is indistinguishable from a conid, a timestamp or a port, so a
# shape rule would either drown in false positives or be tuned until it found nothing. What
# is enforceable is: once a real identifier has been identified, it never comes back.
PUBLISHED_REAL_IDENTIFIERS = frozenset(
    {
        "1331320792",  # alert id, created on IBKR Mobile 2026-09-16
        "1986940574",  # order id, live-orders read 2026-09-16
        "1793215935",  # order id, stop-price modify 2026-09-10
        "1275120921",  # order id, modify reply-array measurement 2026-09-21
        "24,583",  # ESZ6 initial margin change, 2026-09-21
        "18,459",  # ESZ6 maintenance margin change, 2026-09-21
    }
)

# Synthetic stand-ins that replaced them. Present in the tree on purpose, and asserted
# present below so this guard cannot pass by scanning nothing.
SYNTHETIC_IDENTIFIER_STANDINS = frozenset({"1234567890"})


def _identifier_scan_corpus() -> list[tuple[str, str]]:
    """(path, text) for every tracked file the two checks below read.

    ONE walker, deliberately, shared by the guard and by its vacuity control. Written as two
    loops first, and the mutation showed why that is wrong: emptying the guard's own loop
    left the control passing, because the control walked the tree separately and still saw
    everything. A control that cannot observe the thing it certifies is decoration
    (2026-09-22).

    This file is skipped because the deny-list must NAME the values it forbids, so the guard
    flags itself otherwise — which it did on its first run, the same shape this repository
    has been bitten by three times: a source-reading test tripping on the prose explaining
    it. The path is spelled from `__file__` so it cannot drift.
    """
    own_path = Path(__file__).resolve().relative_to(REPO_ROOT).as_posix()
    corpus: list[tuple[str, str]] = []
    for path in _tracked_files():
        if path.startswith(VERBATIM_CAPTURES) or path == own_path:
            continue
        try:
            corpus.append((path, (REPO_ROOT / path).read_text(errors="ignore")))
        except (OSError, UnicodeDecodeError):
            continue
    return corpus


def test_no_tracked_file_republishes_a_known_real_identifier():
    """The class guard. Every value here was live in a tracked file on 2026-09-22 and was
    removed; this is what stops one coming back in a later edit or a revert."""
    offenders: dict[str, list[str]] = {}
    for path, text in _identifier_scan_corpus():
        found = sorted(value for value in PUBLISHED_REAL_IDENTIFIERS if value in text)
        if found:
            offenders[path] = found
    assert not offenders, "identifiers from the owner's live account are back in a PUBLIC repository: " + "; ".join(
        f"{p} -> {', '.join(v)}" for p, v in sorted(offenders.items())
    )


def test_the_identifier_scan_is_not_vacuous():
    """The control this file demands of every other check it holds, and it reads the SAME
    corpus as the guard above — so a walker that goes blind fails here too. That is not
    hypothetical: the account-number guard sat green over seven offending files because its
    pattern covered one field class, and an empty walker is the cheaper version of the same
    mistake."""
    corpus = _identifier_scan_corpus()
    assert len(corpus) > 100, f"the scan corpus holds {len(corpus)} files"
    blob = "".join(text for _, text in corpus)
    missing = sorted(s for s in SYNTHETIC_IDENTIFIER_STANDINS if s not in blob)
    assert not missing, f"the scan cannot see the synthetic stand-ins it replaced them with: {missing}"
