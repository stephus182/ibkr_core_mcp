"""Invariant 9 — every path-interpolated identifier passes its regex.

`docs/security-architecture.md` has claimed this since 2026-09-13. It had **no test**
(audit finding SEC-04) and was **false for three methods** (SEC-03): `_resolve_one_reply`,
`mark_notification_read` and `update_delivery_option` each interpolated a caller-supplied
value straight into a URL path. The 2026-07-11 audit's H-2 is what the invariant exists to
prevent — `delete_alert(alert_id="../order/<id>")` collapsing onto `cancel_order`'s URL.

The rule this file enforces: for every value interpolated into a path literal, the
enclosing function either calls a validator, or the pair appears in `ALLOWED` with a
reason. Nothing is silently exempt — an exemption has to be written down.
"""

import pytest

from tests.security.structural import arguments_passed_to, path_interpolations

pytestmark = pytest.mark.security

CLIENT = "ibkr_core_mcp/client.py"

VALIDATORS = frozenset(
    {
        "_validate_account_id",
        "_validate_order_id",
        "_validate_reply_id",
        "_validate_conid",
        "_validate_page",
        "_validate_notification_id",
        "_validate_delivery_option",
    }
)

# (function, interpolated expression) -> why it needs no regex.
ALLOWED = {
    ("ping", "self._base"): "the gateway base URL, fixed at construction and pinned to loopback",
    ("tickle", "self._base"): "the gateway base URL, fixed at construction and pinned to loopback",
    ("delete_watchlist", "self._base"): "the gateway base URL, fixed at construction and pinned to loopback",
}


def _client_source():
    with open(CLIENT) as fh:
        return fh.read()


def test_every_path_interpolated_identifier_is_validated_or_explicitly_allowed():
    source = _client_source()
    interpolations = path_interpolations(source)
    assert len(interpolations) > 20, f"the checker found only {len(interpolations)} — it has stopped seeing paths"

    unguarded = []
    for function, expression, literal in interpolations:
        if (function, expression) in ALLOWED:
            continue
        if expression in arguments_passed_to(source, function, VALIDATORS):
            continue
        unguarded.append(f"{function}: {literal!r} <- {expression}")

    assert not unguarded, "path-interpolated values with no validator and no recorded exemption:\n  " + "\n  ".join(
        unguarded
    )


def test_the_checker_fires_on_a_deliberately_unguarded_path():
    """The control. Without this, a checker that had stopped working would read as a pass."""
    snippet = 'def bad(self, thing):\n    return self._get(f"/fyi/notifications/{thing}/read")\n'

    found = path_interpolations(snippet)

    assert found == [("bad", "thing", "/fyi/notifications//read")]
    assert not arguments_passed_to(snippet, "bad", VALIDATORS)


def test_the_checker_ignores_a_string_that_merely_starts_with_a_path():
    """`get_live_orders` raises with a message beginning "/iserver/account/orders returned …".

    A first version of this checker reported it as a path interpolation. Whitespace in the
    literal is what separates a URL from prose about one.
    """
    snippet = 'def noisy(self, orders):\n    raise ValueError(f"/iserver/account/orders returned {type(orders).__name__}, not a list")\n'

    assert path_interpolations(snippet) == []


def test_every_allowed_exemption_still_exists():
    """An exemption for an interpolation that no longer exists is a stale licence."""
    live = {(fn, expr) for fn, expr, _ in path_interpolations(_client_source())}

    stale = [key for key in ALLOWED if key not in live]

    assert not stale, f"ALLOWED lists interpolations that no longer exist: {stale}"


# ---------------------------------------------------------------------------
# _REPLY_ID_RE — measured, not inferred (SEC-11, closed 2026-09-16)
# ---------------------------------------------------------------------------


def test_reply_id_regex_accepts_the_shape_ibkr_actually_sends():
    """Checked against 24 reply IDs IBKR really sent, before this test was written.

    They came from the persisted reply logs of real orders placed 2026-09-10/11, in the
    consuming project's decision store — not in this repository, which is public, and the
    IDs are the account holder's. All 24 matched `_REPLY_ID_RE`. Every one was a standard
    lowercase UUID: 36 characters, 8-4-4-4-12.

    The IDs are not reproduced; the measured *shape* is, so that tightening the pattern
    to something that rejects a real reply fails here. A rejection would land in the
    middle of a reply chain and leave a placed order unconfirmed at IBKR.
    """
    from ibkr_core_mcp.client import _REPLY_ID_RE

    observed_shape = "d1f448d8-d821-47d1-80b6-0be54afb32ec".replace("d1f448d8", "0" * 8)
    assert len(observed_shape) == 36
    assert [len(part) for part in observed_shape.split("-")] == [8, 4, 4, 4, 12]

    assert _REPLY_ID_RE.fullmatch(observed_shape)


def test_reply_id_regex_still_accepts_ibkrs_own_documented_example():
    """IBKR's published example is **not** a valid UUID — its third group is six characters.

    So a pattern written as a UUID would reject the only example IBKR gives, while a
    charset pattern accepts both it and the 24 real IDs. That is why this matches on
    characters and length rather than on structure.
    """
    from ibkr_core_mcp.client import _REPLY_ID_RE

    documented = "a12b34c5-d678-9e012f-3456-7a890b12cd3e"
    assert [len(part) for part in documented.split("-")] == [8, 4, 6, 4, 12], "not the documented example"

    assert _REPLY_ID_RE.fullmatch(documented)


@pytest.mark.parametrize(
    "hostile",
    [
        "../order/987654321",
        "../../iserver/auth/status",
        "abc/def",
        "abc?x=1",
        "abc#frag",
        "abc%2f..%2f",
        "",
        "not-hex-zzzz",
    ],
)
def test_reply_id_regex_rejects_anything_that_would_leave_its_path_segment(hostile):
    from ibkr_core_mcp.client import _REPLY_ID_RE

    assert not _REPLY_ID_RE.fullmatch(hostile)
