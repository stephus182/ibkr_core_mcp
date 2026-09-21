"""Security constitution §2 — preview is not execution: the whatif path is the only order
path callable without gates, and the only one the model can reach.

`get_order_preview` posts to `…/orders/whatif` with the same body-building convention as
`place_order`, one literal apart. A refactor that "shares a submit helper" between the
two, or a copy-paste that drops `/whatif`, was lint-clean and fully typed on 2026-09-13
(docs/audits/security-architecture-audit-2026-09-13.md, B2).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from .structural import PACKAGE_DIR, attribute_names_referenced, function_named, functions_using_url_templates
from .test_order_write_boundary import GATE_CALLS, ORDER_WRITE_NAMES

pytestmark = pytest.mark.security

CLIENT = (PACKAGE_DIR / "client.py").read_text()
CLAUDE_TOOLS = (PACKAGE_DIR / "claude_tools.py").read_text()
WHATIF = r"/iserver/account/\{\}/orders/whatif$"


def test_get_order_preview_posts_only_to_whatif(client):
    with patch.object(client, "_post", return_value={}) as post:
        client.get_order_preview("U1234567", {"conid": 1, "side": "BUY", "quantity": 1, "orderType": "MKT"})
    assert post.call_count == 1
    assert post.call_args.args[0].endswith("/orders/whatif")


def test_get_order_preview_runs_no_gate(client):
    with (
        patch.object(client, "_post", return_value={}),
        patch("ibkr_core_mcp.client.require_touch_id") as touch,
        patch("ibkr_core_mcp.client.confirm_order_dialog") as dialog,
    ):
        client.get_order_preview("U1234567", {"conid": 1, "side": "BUY", "quantity": 1, "orderType": "MKT"})
    touch.assert_not_called()
    dialog.assert_not_called()


def test_the_whatif_endpoint_is_built_in_exactly_one_place():
    """The control is "the literal exists once", not "one method may preview".

    `get_bracket_preview` was added 2026-09-20 for the attached-profit-taker work: a bracket
    is one request carrying an array of tickets, so it cannot go through `get_order_preview`,
    which posts a single ticket. Rather than let a second method spell `/orders/whatif` for
    itself - the copy-paste this guard exists to catch - both delegate to `_whatif`, which
    owns the literal. So this assertion stayed a set of ONE as the surface grew.
    """
    assert set(functions_using_url_templates(CLIENT, (WHATIF,))) == {"_whatif"}


def test_get_bracket_preview_posts_only_to_whatif(client):
    with patch.object(client, "_post", return_value={}) as post:
        client.get_bracket_preview("U1234567", {"cOID": "REF", "conid": 1}, [{"parentId": "REF", "conid": 1}])
    assert post.call_count == 1
    assert post.call_args.args[0].endswith("/orders/whatif")


def test_get_bracket_preview_runs_no_gate(client):
    """A bracket preview must be as ungated as a single-order preview. It is the one bracket
    method the model can reach, so a gate creeping in here would be a gate the model triggers.
    """
    with (
        patch.object(client, "_post", return_value={}),
        patch("ibkr_core_mcp.client.require_touch_id") as touch,
        patch("ibkr_core_mcp.client.confirm_order_dialog") as dialog,
    ):
        client.get_bracket_preview("U1234567", {"cOID": "REF", "conid": 1}, [{"parentId": "REF", "conid": 1}])
    touch.assert_not_called()
    dialog.assert_not_called()


def test_bracket_preview_sends_both_legs_and_strips_display_keys(client):
    with patch.object(client, "_post", return_value={}) as post:
        client.get_bracket_preview(
            "U1234567",
            {"cOID": "REF", "conid": 1, "_companyName": "ACME"},
            [{"parentId": "REF", "conid": 1, "_multiplier": 50}],
        )
    orders = post.call_args.args[1]["orders"]
    assert len(orders) == 2, "both legs must reach the preview, or it prices the wrong thing"
    assert not [k for t in orders for k in t if k.startswith("_")], "display-only keys must be stripped"


@pytest.mark.parametrize(
    "parent, children, why",
    [
        ({"conid": 1}, [{"parentId": "REF"}], "no cOID on the parent"),
        ({"cOID": "REF"}, [], "no children"),
        ({"cOID": "REF"}, [{"parentId": "OTHER"}], "child points at a different parent"),
        ({"cOID": "REF"}, [{"parentId": "REF", "cOID": "OWN"}], "child carries its own cOID"),
        (
            {"cOID": "REF", "conid": 1},
            [{"parentId": "REF", "conid": 2}],
            "child is on a different contract — the whatif is blind to this (gap #36, Phase 0)",
        ),
    ],
)
def test_bracket_tickets_refuses_an_unlinked_pair(client, parent, children, why):
    """An unlinked "bracket" is two independent live orders - the exact outcome the user rule
    forbids, because a standalone opposite-side order can open the wrong position."""
    with pytest.raises(ValueError):
        client._bracket_tickets(parent, children)


def test_bracket_tickets_accepts_a_child_with_no_conid_of_its_own(client):
    """The contract rule refuses a STATED mismatch, never an absence: a child's conid is
    derived from the parent, so a ticket without one is the normal case."""
    tickets = client._bracket_tickets({"cOID": "REF", "conid": 1}, [{"parentId": "REF"}])
    assert len(tickets) == 2


def test_get_order_preview_calls_no_gate_in_source():
    fn = function_named(CLIENT, "get_order_preview")
    from .structural import call_lines

    assert call_lines(fn, GATE_CALLS) == []


def test_the_preview_tool_reaches_only_the_whatif_method(mock_config):
    """Drive the real handler with a mock client: among every order-related client method,
    only `get_order_preview` may be touched."""
    from ibkr_core_mcp.claude_tools import ClaudeToolkit

    client = MagicMock()
    client.get_stocks.return_value = [
        {"name": "TEST", "assetClass": "STK", "contracts": [{"conid": 265598, "exchange": "NASDAQ", "isUS": True}]}
    ]
    client.get_accounts.return_value = [{"accountId": "U1234567"}]
    # IBKR's real whatif shape (captured live 2026-09-21), not one invented to match the
    # reader — see LIVE_PREVIEW_ACCEPTED in tests/claude_tools/test_orders.py for why.
    client.get_order_preview.return_value = {
        "amount": {"amount": "185 USD", "commission": "1.00 USD", "total": "186.00 USD"},
        "equity": {"current": "60,000", "change": "-1", "after": "59,999"},
        "initial": {"current": "10,000", "change": "185", "after": "10,185"},
        "maintenance": {"current": "9,000", "change": "139", "after": "7,790"},
        "position": {"current": "0", "change": "1", "after": "1"},
        "error": None,
        "warns": [],
    }
    toolkit = ClaudeToolkit(client, MagicMock(), MagicMock(), mock_config)

    text, _ = toolkit.execute("preview_order", {"symbol": "TEST", "action": "BUY", "quantity": 1})

    assert text.startswith("Order Preview:")
    client.get_order_preview.assert_called_once()
    touched = {name for name, *_ in client.mock_calls if name.split(".")[0] in ORDER_WRITE_NAMES}
    assert not touched, touched


def test_the_preview_handler_names_no_order_write_in_source():
    handler = function_named(CLAUDE_TOOLS, "_preview_order")
    import ast

    referenced = attribute_names_referenced(ast.unparse(handler))
    assert referenced & ORDER_WRITE_NAMES == set()
    assert "get_order_preview" in referenced


def test_the_whatif_probe_sees_a_second_builder():
    snippet = 'def other(self, a):\n    return self._post(f"/iserver/account/{a}/orders/whatif", {})\n'
    assert set(functions_using_url_templates(snippet, (WHATIF,))) == {"other"}
