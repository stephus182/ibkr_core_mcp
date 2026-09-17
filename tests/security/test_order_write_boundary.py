"""Security constitution §1 — no order reaches IBKR except through the four gated
`IBKRClient` methods, and no toolkit or MCP handler references them or their endpoints.

The gates (Touch ID, then a confirmation dialog) live inside `place_order`,
`modify_order`, `cancel_order` and `reply_order` (+ `_resolve_one_reply` for the chained
replies). That is the right place — innermost call site — but until 2026-09-13 it was
enforced by docstrings and grep: `client._post("/iserver/account/…/orders", …)` from a new
tool handler would have been lint-clean, fully typed and gate-free
(docs/audits/security-architecture-audit-2026-09-13.md, B1). These tests read the source.
"""

from __future__ import annotations

import re

import pytest

from .structural import (
    PACKAGE_DIR,
    attribute_names_referenced,
    call_lines,
    function_named,
    functions_calling,
    functions_using_url_templates,
    methods_reaching_the_network,
    names_referenced,
    package_sources,
)

pytestmark = pytest.mark.security

CLIENT = (PACKAGE_DIR / "client.py").read_text()
MODEL_LAYER = {name: (PACKAGE_DIR / name).read_text() for name in ("claude_tools.py", "mcp_server.py")}

# The `{}`-templated forms of the three order-WRITE endpoints. Read endpoints differ in
# shape: `/iserver/account/orders` (no account segment) and `/iserver/account/order/status/`.
ORDER_WRITE_PATTERNS = (
    r"/iserver/account/\{\}/orders$",  # POST place
    r"/iserver/account/\{\}/order/\{\}$",  # POST modify, DELETE cancel
    r"/iserver/reply/\{\}$",  # POST reply
)
GATED_OWNERS = {"place_order", "modify_order", "cancel_order", "reply_order", "_resolve_one_reply"}
GATE_CALLS = (
    "require_touch_id",
    "confirm_order_dialog",
    "confirm_modify_dialog",
    "confirm_cancel_dialog",
    "confirm_reply_dialog",
)
NETWORK_CALLS = ("_post", "_get", "_put", "with_retry")
ORDER_WRITE_NAMES = {
    "place_order",
    "modify_order",
    "cancel_order",
    "reply_order",
    "place_order_and_confirm",
    "modify_order_and_confirm",
    "_resolve_one_reply",
    "_authorize_order_write",
    "OrderWriteAuthorization",
    "_post",
    "_put",
    "_session",
}


def test_order_write_endpoints_are_built_only_inside_the_gated_methods():
    owners = functions_using_url_templates(CLIENT, ORDER_WRITE_PATTERNS)
    assert set(owners) == GATED_OWNERS, owners


def test_every_gated_method_runs_a_gate_before_its_first_network_call():
    for name in GATED_OWNERS:
        fn = function_named(CLIENT, name)
        gates = call_lines(fn, GATE_CALLS)
        network = call_lines(fn, NETWORK_CALLS)
        assert gates, f"{name} calls no gate"
        assert network, f"{name} makes no network call"
        assert min(gates) < min(network), f"{name}: network call at line {min(network)} precedes a gate"


def test_the_model_layer_never_references_an_order_write():
    """`claude_tools.py` and `mcp_server.py` are what the model can drive. Neither may name
    an order-write method, the raw `_post`/`_session` primitives, or the authorization
    value — whether to call it, mock it, or mint it."""
    for filename, source in MODEL_LAYER.items():
        hits = (attribute_names_referenced(source) | names_referenced(source)) & ORDER_WRITE_NAMES
        assert not hits, f"{filename} references {sorted(hits)}"


def test_order_write_authorizations_are_minted_in_exactly_one_place():
    """An `OrderWriteAuthorization` lets a chained reply skip a second fingerprint. Only
    `client._authorize_order_write` — which has just run Touch ID — may construct one."""
    owners: dict[str, set[str]] = {}
    for path, source in package_sources():
        found = functions_calling(source, "OrderWriteAuthorization")
        if found:
            owners[path.name] = found
    assert owners == {"client.py": {"_authorize_order_write"}}, owners


# ── Guards on the guards ───────────────────────────────────────────────────────


def test_the_endpoint_probe_sees_a_new_call_site():
    sneaky = (
        "class C:\n"
        "    def sneaky(self, account_id, body):\n"
        '        return self._post(f"/iserver/account/{account_id}/orders", body)\n'
        "    def also_sneaky(self, reply_id):\n"
        '        url = f"{self._base}/iserver/reply/{reply_id}"\n'
        "        return url\n"
    )
    assert set(functions_using_url_templates(sneaky, ORDER_WRITE_PATTERNS)) == {"sneaky", "also_sneaky"}


# Both cases above build the URL with an f-string, which is the form client.py happens to
# use today — so on their own they prove only that the probe fires for the shape already
# there. The property this suite claims is stronger: that an order-write URL built ANYWHERE
# outside the gated set is seen. These are the ordinary Python spellings of the same URL.
# Each was verified missed before the probe was widened on 2026-09-16.
_SNEAKY_SPELLINGS = {
    "concatenation": (
        "class C:\n"
        "    def sneaky(self, account_id, body):\n"
        '        return self._post("/iserver/account/" + account_id + "/orders", body)\n'
    ),
    "percent-format": (
        "class C:\n"
        "    def sneaky(self, account_id, body):\n"
        '        return self._post("/iserver/account/%s/orders" % account_id, body)\n'
    ),
    "str.format": (
        "class C:\n"
        "    def sneaky(self, account_id, body):\n"
        '        return self._post("/iserver/account/{}/orders".format(account_id), body)\n'
    ),
    "str.join": (
        "class C:\n"
        "    def sneaky(self, account_id, body):\n"
        '        return self._post("/".join(["/iserver/account", account_id, "orders"]), body)\n'
    ),
    "module-level constant": (
        '_PLACE = "/iserver/account/{}/orders"\n'
        "class C:\n"
        "    def sneaky(self, account_id, body):\n"
        "        return self._post(_PLACE.format(account_id), body)\n"
    ),
    "built over two statements": (
        "class C:\n"
        "    def sneaky(self, account_id, body):\n"
        '        path = "/iserver/account/" + account_id\n'
        '        return self._post(path + "/orders", body)\n'
    ),
}


@pytest.mark.parametrize("spelling", sorted(_SNEAKY_SPELLINGS))
def test_the_endpoint_probe_sees_a_call_site_however_the_url_is_spelled(spelling):
    """A gate-free order write must be visible whatever string idiom builds its URL.

    Until 2026-09-16 the probe reconstructed only `ast.Constant` and `ast.JoinedStr`, in
    function bodies. Every spelling below was therefore invisible, and a new order-write
    call site written in any of them would have passed `pytest -m security` silently —
    which is the single thing this test exists to prevent. The f-string cases above passed
    throughout, so the suite looked green and specific while covering one member of a class.

    The limitation was recorded nowhere: `docs/security-architecture.md` § 5 states the
    property as "endpoint templates only in the gated set", unqualified.
    """
    seen = functions_using_url_templates(_SNEAKY_SPELLINGS[spelling], ORDER_WRITE_PATTERNS)
    assert "sneaky" in seen, f"a {spelling} order-write URL is invisible to the probe"


def test_the_reference_probe_sees_an_order_write_in_a_handler():
    snippet = "def _auto_cancel(self, inputs):\n    return self._client.cancel_order(inputs['a'], inputs['o'])\n"
    assert attribute_names_referenced(snippet) & ORDER_WRITE_NAMES == {"cancel_order"}


@pytest.mark.parametrize("primitive", ["_get", "_post", "_put"])
def test_the_ordering_probe_sees_a_network_call_before_a_gate(primitive):
    """Parameterised over every HTTP primitive the client has.

    `_put` was added 2026-09-16 for the two FYI write endpoints. A primitive the probe does
    not know about is a way to reach the network before a gate that this file would not
    see — which is the whole point of the file.
    """
    snippet = f'def bad(self):\n    self.{primitive}("/x")\n    require_touch_id("later")\n'
    fn = function_named(snippet, "bad")
    assert min(call_lines(fn, NETWORK_CALLS)) < min(call_lines(fn, GATE_CALLS))


def test_the_ordering_probe_knows_every_http_primitive_the_client_has():
    """The list above is hand-written; this fails if `client.py` grows another primitive."""
    primitives = set(re.findall(r"^    def (_[a-z]+)\(self, path", CLIENT, re.M))
    assert primitives, "no HTTP primitives matched — the check would be vacuous"

    assert primitives <= set(NETWORK_CALLS), (
        f"HTTP primitives the ordering probe cannot see: {sorted(primitives - set(NETWORK_CALLS))}"
    )


# ── The body the dialog showed is the body that is sent ────────────────────────


@pytest.mark.parametrize("method", ["place_order", "modify_order"])
def test_a_body_mutated_after_the_dialog_is_not_the_body_sent(client, method):
    """Gate 2 renders the caller's dict; the request body was then built from that same
    dict *after* the dialog returned. A caller mutating it in that window — a concurrent
    proposal update, a bug — would send what the human never saw. The 2026-07-11 audit
    noted it and dropped it as unreachable; the fix is one copy (audit 2026-09-13, B9)."""
    from unittest.mock import patch

    order = {"conid": 1, "side": "BUY", "quantity": 1, "orderType": "MKT", "tif": "DAY"}
    shown = {}

    def dialog(*args, **kwargs):
        shown.update(args[1] if method == "modify_order" else args[0])
        order["quantity"] = 999  # the CALLER's dict changes while the human is looking

    with (
        patch("ibkr_core_mcp.client.require_touch_id"),
        patch("ibkr_core_mcp.client.confirm_order_dialog", side_effect=dialog),
        patch("ibkr_core_mcp.client.confirm_modify_dialog", side_effect=dialog),
        patch.object(client, "_post", return_value={}) as post,
    ):
        if method == "place_order":
            client.place_order("U1234567", order)
            sent = post.call_args.args[1]["orders"][0]
        else:
            client.modify_order("U1234567", "123", order)
            sent = post.call_args.args[1]
    assert shown["quantity"] == 1
    assert sent["quantity"] == 1, "the body sent is not the body the dialog showed"


# ── The gate-ordering check, transitively ──────────────────────────────────────


# One call is allowed to precede the gates, and only this one. IBKR documents
# `GET /iserver/accounts` as a prerequisite that "must be called before modifying an order"
# (`client.get_brokerage_accounts` docstring, receive-brokerage-accounts.md), and the
# ordering is deliberate: `tests/test_client.py::test_place_order_initializes_accounts_
# before_touch_id` requires it by name, so that a dead session fails fast instead of after
# two human gates. It is a READ of the operator's own account list, on loopback, and it can
# neither place, modify, cancel nor confirm an order.
PRE_GATE_EXEMPT = {
    "_ensure_accounts_initialized": (
        "IBKR's documented prerequisite for order operations; a GET of the operator's own "
        "account list. Ordering pinned by test_place_order_initializes_accounts_before_touch_id."
    ),
}


def test_no_gated_method_reaches_the_network_indirectly_before_a_gate():
    """`test_every_gated_method_runs_a_gate_before_its_first_network_call` asks whether a
    gated method calls `_get`/`_post`/`_put` ITSELF. The property four documents stated was
    broader — "both gates ... before any network call reaches IBKR" — and one call deeper
    was invisible: every gated method opens with `_ensure_accounts_initialized()`, which
    issues `GET /iserver/accounts` on a fresh session, before Gate 1 (SEC-02).

    Driven 2026-09-16 with Gate 1 denying: 1 request on a fresh session, 0 once the flag is
    already set. The second arm is what proves the first is real rather than a harness
    artefact — and the documents have been corrected to the property that is both true and
    the one that matters: no ORDER-WRITE request precedes the gates.
    """
    reaching = methods_reaching_the_network(CLIENT, NETWORK_CALLS) - set(PRE_GATE_EXEMPT)
    offenders = {}
    for name in GATED_OWNERS:
        fn = function_named(CLIENT, name)
        gates = call_lines(fn, GATE_CALLS)
        early = [ln for ln in call_lines(fn, reaching - {name}) if ln < min(gates)]
        if early:
            offenders[name] = early
    assert offenders == {}, f"network reached before a gate, indirectly: {offenders}"


def test_the_transitive_probe_sees_the_exempted_call():
    """The control. Without the exemption the probe must report all four gated methods —
    otherwise `test_no_gated_method_reaches_the_network_indirectly_before_a_gate` passes
    because the probe is blind, not because the property holds."""
    reaching = methods_reaching_the_network(CLIENT, NETWORK_CALLS)
    assert "_ensure_accounts_initialized" in reaching

    seen = set()
    for name in GATED_OWNERS:
        fn = function_named(CLIENT, name)
        gates = call_lines(fn, GATE_CALLS)
        if [ln for ln in call_lines(fn, reaching - {name}) if ln < min(gates)]:
            seen.add(name)
    assert seen == {"place_order", "modify_order", "cancel_order", "reply_order"}, seen


def test_the_transitive_probe_ignores_a_helper_that_touches_nothing():
    """The counter-case: a probe that called everything network-reaching would make the
    exemption list meaningless. Pure validators must not be flagged."""
    reaching = methods_reaching_the_network(CLIENT, NETWORK_CALLS)
    for pure in ("_validate_conid", "_validate_account_id", "_order_label", "_require_numeric"):
        assert pure not in reaching, f"{pure} does not touch the network"


def test_no_pre_gate_exemption_outlives_its_call_site():
    """An exemption nothing exercises is a hole left open for a reason that has expired."""
    for name in PRE_GATE_EXEMPT:
        used = any(call_lines(function_named(CLIENT, owner), (name,)) for owner in GATED_OWNERS)
        assert used, f"{name} is exempted but no gated method calls it"


@pytest.mark.parametrize(
    ("name", "call"),
    [
        ("place_order", lambda c: c.place_order("U1234567", {"conid": 265598, "side": "BUY", "quantity": 1})),
        ("modify_order", lambda c: c.modify_order("U1234567", "123", {"conid": 265598, "quantity": 1})),
        ("cancel_order", lambda c: c.cancel_order("U1234567", "123")),
        ("reply_order", lambda c: c.reply_order("11111111-1111-4111-8111-111111111111")),
    ],
)
def test_a_denied_gate_1_sends_no_order_write_however_fresh_the_session(client, name, call):
    """The behavioural half of SEC-02, and the property the documents now state.

    On a FRESH session one request precedes the gates — `GET /iserver/accounts`, IBKR's
    documented prerequisite. Zero order writes do, whether the session is fresh or not.
    Both arms are asserted: without the pre-initialised case the test cannot distinguish
    "no order write escaped" from "nothing was attempted at all".
    """
    from unittest.mock import MagicMock, patch

    from ibkr_core_mcp.exceptions import HumanAuthError

    for fresh in (False, True):
        client._accounts_initialized = not fresh
        seen: list[tuple[str, str]] = []

        def record(method, url, *args, _seen=seen, **kwargs):
            _seen.append((method, url))
            response = MagicMock()
            response.status_code = 200
            response.json.return_value = {"accounts": ["U1234567"]}
            return response

        with (
            patch.object(client._session, "request", side_effect=record),
            patch("ibkr_core_mcp.client.require_touch_id", side_effect=HumanAuthError("denied")),
            patch("ibkr_core_mcp.client.confirm_order_dialog"),
            patch("ibkr_core_mcp.client.confirm_modify_dialog"),
            patch("ibkr_core_mcp.client.confirm_cancel_dialog"),
            patch("ibkr_core_mcp.client.confirm_reply_dialog"),
            pytest.raises(HumanAuthError),
        ):
            call(client)

        writes = [u for m, u in seen if m in {"POST", "DELETE"}]
        assert writes == [], f"{name}: order write escaped a denied gate: {writes}"

        reads = [u for m, u in seen if m == "GET"]
        expected = 1 if fresh else 0
        assert len(reads) == expected, f"{name}: fresh={fresh} expected {expected} GET, got {reads}"
        if fresh:
            assert reads[0].endswith("/iserver/accounts")
