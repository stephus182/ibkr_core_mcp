"""Every test must be capable of failing for the reason its name gives.

Why this file exists
--------------------
On 2026-09-16 three `IBKRClient` methods were found returning `[]` for every call —
`get_pa_transactions` had done so since it was written, while IBKR was returning 11
transactions for a held contract. All three had **live** tests, against a real
authenticated gateway, and all three passed throughout, because each asserted only
`isinstance(result, list)` and `[]` is a list.

That is not an isolated slip. A scan the same day found 43 tests whose every assertion is
satisfied by a well-formed but wrong value, **38 of them in `tests/test_client_live.py`** —
the suite whose entire purpose is catching what a mock cannot. The repo already knew the
shape of this failure (`docs/web-scraper-reference.md` §10: "the mocks were weaker than the
dependency each time"); this is the same thing one level up, where the *assertions* are
weaker than the behaviour.

So: a test whose assertions are all trivially satisfiable is recorded here with the reason
it is allowed to be, or it fails this check. The point is not the count. It is that adding
a new shallow test should require saying so out loud.

What counts as trivially satisfiable
------------------------------------
An assertion a WRONG-but-well-formed value passes: `isinstance(x, list)` (satisfied by
`[]`), bare truthiness, `is not None`, `len(x) >= 0`. A test may of course contain these —
it fails only when it contains *nothing else*.
"""

from __future__ import annotations

import ast
import pathlib
import re

WEAK_ASSERTION_PATTERNS = (
    re.compile(r"^assert isinstance\([^)]+\)$"),
    re.compile(r"^assert \w+(\.\w+)*$"),
    re.compile(r"^assert \w+(\.\w+)* is not None$"),
    re.compile(r"^assert len\([^)]+\) [>=]=? 0$"),
)

# Tests whose only honest assertion IS "this ran and produced the right kind of thing".
# Each entry says why. A name here is a claim that nothing stronger is available — not a
# place to park a test that simply has not been written properly yet.
ALLOWED_SHALLOW: dict[str, str] = {
    "test_ordinary_indicator_strategies_still_run": "the property IS 'the sandbox does not reject ordinary code'; any result means it ran",
    "test_a_string_named_function_may_still_name_an_allowed_method": "asserts absence of a false positive; a returned value of any shape proves it",
    "test_sandbox_still_allows_ordinary_dataframe_methods": "same: the property is that it is not blocked",
    "test_rsi_strategy": "covered numerically by tests/test_indicators.py; here only that a strategy using it executes",
    "test_bars_to_dataframe_empty": "the subject IS the empty case — an empty frame is the correct answer",
}


# Anchored on this file, not on the working directory: `Path("tests")` walked from wherever
# pytest was started, so from anywhere but the repo root the scan found no files, no
# offenders, and passed (API-R7, 2026-09-17).
_TESTS_DIR = pathlib.Path(__file__).resolve().parent


def _weak(assertion: str) -> bool:
    return any(p.match(assertion) for p in WEAK_ASSERTION_PATTERNS)


def _tests_with_only_weak_assertions() -> list[tuple[str, str]]:
    found = []
    for path in sorted(_TESTS_DIR.rglob("test_*.py")):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:  # pragma: no cover - a broken test file fails elsewhere
            continue
        for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
            if not fn.name.startswith("test_"):
                continue
            asserts = [ast.unparse(n).strip() for n in ast.walk(fn) if isinstance(n, ast.Assert)]
            if asserts and all(_weak(a) for a in asserts):
                found.append((str(path), fn.name))
    return found


def test_no_test_asserts_only_things_a_wrong_value_would_satisfy():
    """A test that cannot distinguish right from well-formed-but-wrong is not a test."""
    offenders = [(p, n) for p, n in _tests_with_only_weak_assertions() if n not in ALLOWED_SHALLOW]
    assert not offenders, (
        "These tests would pass on a wrong-but-well-formed value — `[]` for a list, a "
        "default-constructed object, anything truthy:\n  "
        + "\n  ".join(f"{p}::{n}" for p, n in offenders)
        + "\n\nAssert something the real answer has and a wrong one does not. If the "
        "endpoint genuinely cannot guarantee content (the account holds no alerts, no open "
        "orders), skip loudly with that reason instead of asserting a type. If nothing "
        "stronger is possible, add the name to ALLOWED_SHALLOW with why."
    )


def test_the_allowed_shallow_list_has_no_stale_entries():
    """An exemption for a test that no longer exists, or is no longer shallow, makes the
    list look better-audited than it is — the same reasoning as `conftest.py`'s DNS
    exemption set, which had three dead names removed on 2026-08-07."""
    shallow = {n for _, n in _tests_with_only_weak_assertions()}
    stale = sorted(set(ALLOWED_SHALLOW) - shallow)
    assert not stale, f"ALLOWED_SHALLOW names tests that are no longer shallow (or no longer exist): {stale}"


def test_the_strength_scan_actually_sees_the_suite():
    """Vacuity guard for the scan above: a walk that finds no test files finds no offenders
    and passes, which is exactly what happened from outside the repo root (API-R7)."""
    scanned = list(_TESTS_DIR.rglob("test_*.py"))
    assert len(scanned) > 50, f"the scan found {len(scanned)} test files"
