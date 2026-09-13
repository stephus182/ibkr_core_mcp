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


def test_the_whatif_endpoint_is_built_only_by_get_order_preview():
    assert set(functions_using_url_templates(CLIENT, (WHATIF,))) == {"get_order_preview"}


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
    client.get_order_preview.return_value = {"commission": "1.00", "equity": {"amount": "1", "change": "0"}}
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
