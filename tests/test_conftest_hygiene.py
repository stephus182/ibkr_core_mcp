"""Guards on tests/conftest.py's own security-relevant state.

_REAL_DNS_EXEMPT_TESTS grants named tests the right to make real DNS calls, bypassing
the _no_real_io fixture. A stale name in it is not inert: it is an exemption nothing
uses, and it makes the set read as more curated than it is. Three such names survived
from tools deleted on 2026-07-30 until an audit on 2026-08-07 — nothing was watching.
"""

import re
from pathlib import Path

from .conftest import _REAL_DNS_EXEMPT_TESTS

_TESTS_DIR = Path(__file__).parent


def _all_test_function_names() -> set[str]:
    names: set[str] = set()
    for path in _TESTS_DIR.rglob("test_*.py"):
        names.update(re.findall(r"^def (test_\w+)", path.read_text(), re.M))
    return names


def test_every_dns_exemption_names_a_test_that_exists():
    """A name matching no test grants an exemption to nothing."""
    stale = sorted(_REAL_DNS_EXEMPT_TESTS - _all_test_function_names())
    assert not stale, f"stale DNS exemptions (delete these from tests/conftest.py): {stale}"


def test_the_probe_itself_finds_tests():
    """Guard on the guard: if the rglob or regex broke, the check above would pass
    by finding nothing — the exact failure mode this whole audit is about."""
    found = _all_test_function_names()
    assert len(found) > 500, f"only found {len(found)} test functions; the scan is broken"
    assert "test_every_dns_exemption_names_a_test_that_exists" in found


def test_the_exemption_list_is_not_empty():
    """If it ever empties, the list has been gutted rather than curated."""
    assert len(_REAL_DNS_EXEMPT_TESTS) >= 10
