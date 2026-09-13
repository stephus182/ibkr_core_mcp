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

import pytest

from .structural import (
    PACKAGE_DIR,
    attribute_names_referenced,
    call_lines,
    function_named,
    functions_calling,
    functions_using_url_templates,
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
NETWORK_CALLS = ("_post", "_get", "with_retry")
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


def test_the_reference_probe_sees_an_order_write_in_a_handler():
    snippet = "def _auto_cancel(self, inputs):\n    return self._client.cancel_order(inputs['a'], inputs['o'])\n"
    assert attribute_names_referenced(snippet) & ORDER_WRITE_NAMES == {"cancel_order"}


def test_the_ordering_probe_sees_a_network_call_before_a_gate():
    snippet = 'def bad(self):\n    self._post("/x")\n    require_touch_id("later")\n'
    fn = function_named(snippet, "bad")
    assert min(call_lines(fn, NETWORK_CALLS)) < min(call_lines(fn, GATE_CALLS))


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
