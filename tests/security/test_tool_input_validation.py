"""Security constitution §11 — on the MCP transport, an argument set that fails a tool's
`inputSchema` never reaches a handler.

The property holds because `mcp_server.build_server` registers `handle_call_tool` through the
SDK's `@server.call_tool(validate_input=True)`, which runs
`jsonschema.validate(arguments, tool.inputSchema)` before calling the handler (mcp 1.29.0,
`mcp/server/lowlevel/server.py`). `True` is also the SDK's default, and until 2026-09-14 that
default was the whole of the guarantee: nothing in this package said so, and no test sent a
malformed argument. That matters because `mcp` is the one dependency with a hard ceiling —
2.0 removed the decorator this handler is registered with (`pyproject.toml`) — so a port could
drop the check while every existing MCP test, all of which send well-formed arguments, stayed
green.

OWASP, *A Practical Guide for Secure MCP Server Development* v1.0 §3: "Define and enforce JSON
Schemas for every tool's inputs (from the model) and outputs (back to the model). Reject any
request that doesn't match the expected schema." The applicability decision is
docs/audits/owasp-mcp-guide-applicability-2026-09-14.md.

The Anthropic-API path (`ClaudeToolkit.execute`) has no schema step of its own: handlers coerce
what they read and anything that raises becomes one fixed `_safe_error` sentence. That path is
covered by the handler tests; this file is about the MCP one.
"""

from __future__ import annotations

import ast
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from mcp.server import Server
from mcp.types import CallToolRequest, CallToolRequestParams, CallToolResult, TextContent

from ibkr_core_mcp.mcp_server import _ALL_TOOL_DEFS, _EXISTING_TOOL_NAMES, build_server

from .structural import PACKAGE_DIR, function_named, keyword_literal_lines, package_sources

pytestmark = pytest.mark.security

#: One malformed argument set per rejection the schemas are supposed to make, over both a
#: toolkit tool and a server-local one.
MALFORMED = [
    pytest.param("fetch_page", {"url": 123}, id="wrong-type"),
    pytest.param("fetch_page", {}, id="missing-required"),
    pytest.param(
        "add_price_alert",
        {"conid": 1, "symbol": "X", "threshold": 1.0, "direction": "sideways"},
        id="enum-violation",
    ),
    pytest.param(
        "add_price_alert",
        {"conid": "one", "symbol": "X", "threshold": 1.0, "direction": "above"},
        id="wrong-type-server-local",
    ),
]


async def _call(server: Server, name: str, arguments: dict[str, Any]) -> CallToolResult:
    """Drive the real `tools/call` request handler, as a connected client would."""
    req = CallToolRequest(method="tools/call", params=CallToolRequestParams(name=name, arguments=arguments))
    result = await server.request_handlers[type(req)](req)
    assert isinstance(result.root, CallToolResult)
    return result.root


def _text(result: CallToolResult) -> str:
    block = result.content[0]
    assert isinstance(block, TextContent)
    return block.text


@pytest.fixture
def server():
    """A real server over mock collaborators.

    `_dispatch` is the single funnel every tool call passes through after validation, and it
    is patched in each test below, so nothing behind it runs and neither the toolkit nor the
    store needs to be real.
    """
    return build_server(MagicMock(), MagicMock())


@pytest.mark.parametrize("name, arguments", MALFORMED)
async def test_a_malformed_argument_set_is_rejected_before_any_handler_runs(server, name, arguments):
    with patch("ibkr_core_mcp.mcp_server._dispatch") as dispatch:
        result = await _call(server, name, arguments)
    assert result.isError is True
    assert _text(result).startswith("Input validation error"), _text(result)
    dispatch.assert_not_called()


async def test_a_well_formed_argument_set_reaches_the_handler(server):
    with patch("ibkr_core_mcp.mcp_server._dispatch", return_value="ran") as dispatch:
        result = await _call(server, "fetch_page", {"url": "https://example.com/"})
    assert result.isError is not True
    assert _text(result) == "ran"
    assert dispatch.call_args.args[:2] == ("fetch_page", {"url": "https://example.com/"})


def test_every_name_the_dispatcher_routes_is_a_listed_tool():
    """The SDK validates only `if validate_input and tool`, and `tool` is None for any name
    `tools/list` did not return — it logs "not listed, no validation will be performed" and
    calls the handler anyway (mcp 1.29.0, server.py). So the property above rests on a second
    fact: every name `_dispatch` can route is a listed tool. Invariant 3 holds that for the
    toolkit's 44; this holds it for the two the server adds itself."""
    dispatch = ast.unparse(function_named((PACKAGE_DIR / "mcp_server.py").read_text(), "_dispatch"))
    routed: set[str] = set()
    for node in ast.walk(ast.parse(dispatch)):
        if not (isinstance(node, ast.Compare) and isinstance(node.left, ast.Name) and node.left.id == "name"):
            continue
        if not isinstance(node.ops[0], ast.Eq):
            continue
        target = node.comparators[0]
        if isinstance(target, ast.Constant) and isinstance(target.value, str):
            routed.add(target.value)
    listed = {str(t["name"]) for t in _ALL_TOOL_DEFS}
    assert routed, "the dispatch-name probe found no routed names to check"
    assert routed <= listed, sorted(routed - listed)
    assert listed >= _EXISTING_TOOL_NAMES


def test_nothing_in_the_package_opts_out_of_input_validation():
    """Contributor rule 12, as a test rather than a review comment. Structural rather than
    behavioural so it fires on a new registration site that nothing calls yet."""
    offenders = {
        str(path.relative_to(PACKAGE_DIR)): lines
        for path, source in package_sources()
        if (lines := keyword_literal_lines(source, "validate_input", False))
    }
    assert not offenders, offenders


# ── Guards on the guards ───────────────────────────────────────────────────────


@pytest.mark.parametrize("name, arguments", MALFORMED)
async def test_the_probe_sees_each_malformed_set_reach_the_handler_when_validation_is_off(name, arguments):
    """Prove every case above can fail. The same request against the same server, with only
    the call handler re-registered to opt out of validation, reaches the handler with the bad
    arguments — so each parametrised case is asserting something that is not true by default.
    (Re-registering overwrites `request_handlers[CallToolRequest]`; the production `list_tools`
    handler stays, which is what makes the tool schemas visible to the SDK at all.)"""
    server = build_server(MagicMock(), MagicMock())
    reached: list[tuple[str, dict[str, Any]]] = []

    async def unvalidated(tool: str, arguments_: dict[str, Any] | None) -> list[TextContent]:
        reached.append((tool, arguments_ or {}))
        return [TextContent(type="text", text="reached")]

    server.call_tool(validate_input=False)(unvalidated)

    result = await _call(server, name, arguments)

    assert result.isError is not True
    assert reached == [(name, arguments)]


def test_the_opt_out_probe_sees_the_keyword():
    snippet = "@server.call_tool(validate_input=False)\nasync def h(n, a):\n    return []\n"
    assert keyword_literal_lines(snippet, "validate_input", False) == [1]
    assert keyword_literal_lines("server.call_tool()(h)\n", "validate_input", False) == []
