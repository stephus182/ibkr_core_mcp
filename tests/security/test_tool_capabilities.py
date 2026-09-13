"""Security constitution §3 — every model-callable tool declares its capabilities, and
the set of tools declaring ORDER_EXECUTION is empty.

Until 2026-09-13 the only answer to "which tools mutate state?" was a prose table in
SECURITY.md that said "42 read-only tools". The registry held 44 + 2, and eight of them
mutate state outside the machine (docs/audits/security-architecture-audit-2026-09-13.md,
B3). Each tool definition now carries a `capabilities` set, and this file checks it
three ways: the declaration exists and is well-formed; the ORDER_EXECUTION set is
empty; and — the part that keeps the declarations honest — the sinks a handler's source
actually touches are all declared.
"""

from __future__ import annotations

import ast

import pytest

from ibkr_core_mcp.claude_tools import CAPABILITIES, READ_LIKE_CAPABILITIES, TOOL_DEFINITIONS, tool_capabilities
from ibkr_core_mcp.mcp_server import _ALL_TOOL_DEFS, build_server

from .structural import PACKAGE_DIR, attribute_names_referenced, function_named, names_referenced
from .test_order_write_boundary import ORDER_WRITE_NAMES

pytestmark = pytest.mark.security

CLAUDE_TOOLS = (PACKAGE_DIR / "claude_tools.py").read_text()

# Categories that change state somewhere; READ_ONLY may share a declaration with none of
# them (LOCAL_IO — reading browser cookies or a saved profile — is the one companion).
# Derived, so a capability added to the vocabulary is mutating until proven otherwise.
MUTATING = CAPABILITIES - READ_LIKE_CAPABILITIES

#: Every tool the MCP server lists: the toolkit's 44 plus the two server-local ones.
ALL_CAPABILITIES = {str(t["name"]): frozenset(t["capabilities"]) for t in _ALL_TOOL_DEFS}

# What a referenced name implies about the handler that references it. Keys are attribute
# or bare names as they appear in the handler's own source; helper methods that hide a
# sink (`fetch_trades` uploads to Drive inside FlexQueryClient) are named by the method
# the handler calls.
IMPLIED_BY_CLIENT_ATTR = {
    **dict.fromkeys(ORDER_WRITE_NAMES, "ORDER_EXECUTION"),
    "get_order_preview": "ORDER_PREVIEW",
    **dict.fromkeys(
        (
            "create_alert",
            "delete_alert",
            "activate_alert",
            "create_watchlist",
            "delete_watchlist",
            "switch_account",
            "logout",
            "mark_notification_read",
            "update_delivery_option",
            "unsubscribe_market_data",
            "unsubscribe_all_market_data",
            "invalidate_positions_cache",
            "reauthenticate",
        ),
        "ACCOUNT_STATE",
    ),
}
STORE_WRITE_PREFIXES = ("upsert", "save", "log", "add", "record", "insert", "delete", "update", "mark", "snapshot")
CACHE_WRITE_PREFIXES = ("save", "upload", "delete", "put")
IMPLIED_BY_NAME = {
    "_run_backtest": {"SANDBOX_EXECUTION"},
    "_get_crawl4ai": {"WEB_FETCH", "LOCAL_IO"},
    "crawl_site": {"WEB_FETCH", "LOCAL_IO"},
    "search_site_detailed": {"WEB_FETCH"},
    "_firecrawl": {"NETWORK"},
    "fetch_trades": {"NETWORK", "GOOGLE_DRIVE", "DATABASE"},
    "sync_archive_from_drive": {"DATABASE"},
    "import_from_file": {"DATABASE", "LOCAL_IO"},
    "_prime_pnl_subscription": {"LOCAL_IO"},
    "save_crawl": {"GOOGLE_DRIVE"},
    "save_search": {"GOOGLE_DRIVE"},
}


def _handler_source(tool: str) -> str:
    """The source of the toolkit method `execute()` dispatches `tool` to."""
    execute = function_named(CLAUDE_TOOLS, "execute")
    for node in ast.walk(execute):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=True):
                if isinstance(key, ast.Constant) and key.value == tool and isinstance(value, ast.Attribute):
                    return ast.unparse(function_named(CLAUDE_TOOLS, value.attr))
    raise KeyError(tool)


def _implied(tool_source: str) -> set[str]:
    implied: set[str] = set()
    tree = ast.parse(tool_source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        owner = node.value
        owner_name = owner.attr if isinstance(owner, ast.Attribute) else None
        if owner_name == "_client" and node.attr in IMPLIED_BY_CLIENT_ATTR:
            implied.add(IMPLIED_BY_CLIENT_ATTR[node.attr])
        if owner_name == "_store" and node.attr.startswith(STORE_WRITE_PREFIXES):
            implied.add("DATABASE")
        if owner_name == "_cache" and node.attr.startswith(CACHE_WRITE_PREFIXES):
            implied.add("GOOGLE_DRIVE")
    for name in attribute_names_referenced(tool_source) | names_referenced(tool_source):
        implied |= IMPLIED_BY_NAME.get(name, set())
    return implied


# ── Declarations ───────────────────────────────────────────────────────────────


def test_every_registered_tool_declares_a_non_empty_known_capability_set():
    for tool in _ALL_TOOL_DEFS:
        caps = tool.get("capabilities")
        assert isinstance(caps, frozenset) and caps, f"{tool['name']} declares no capabilities"
        assert caps <= CAPABILITIES, f"{tool['name']} declares unknown capabilities {caps - CAPABILITIES}"


def test_order_execution_has_no_legal_spelling():
    """The forbidden capability is not in the vocabulary, so declaring it fails the
    unknown-capability check by construction — a stronger guarantee than an empty set."""
    assert "ORDER_EXECUTION" not in CAPABILITIES
    assert {name for name, caps in ALL_CAPABILITIES.items() if "ORDER_EXECUTION" in caps} == set()


def test_the_toolkit_map_is_the_toolkit_half_of_the_server_map():
    assert tool_capabilities() == {
        k: v for k, v in ALL_CAPABILITIES.items() if k in {t["name"] for t in TOOL_DEFINITIONS}
    }
    assert len(ALL_CAPABILITIES) == len(TOOL_DEFINITIONS) + 2


def test_every_dispatchable_handler_has_a_definition_and_vice_versa():
    """`execute()`'s dispatch dict and `TOOL_DEFINITIONS` are two registries; a handler in
    one but not the other either has no declaration or can never be called."""
    execute = function_named(CLAUDE_TOOLS, "execute")
    dispatched = set()
    for node in ast.walk(execute):
        if isinstance(node, ast.Dict):
            dispatched |= {k.value for k in node.keys if isinstance(k, ast.Constant)}
    assert dispatched == {t["name"] for t in TOOL_DEFINITIONS}


async def test_list_tools_carries_annotations_derived_from_the_declaration(mock_config):
    """The MCP-native hints exist for clients that gate confirmation prompts on them."""
    from unittest.mock import MagicMock

    from mcp.types import ListToolsRequest, ListToolsResult

    from ibkr_core_mcp.claude_tools import ClaudeToolkit
    from ibkr_core_mcp.store import SQLiteStore

    server = build_server(ClaudeToolkit(MagicMock(), MagicMock(), MagicMock(), mock_config), SQLiteStore(mock_config))
    req = ListToolsRequest(method="tools/list")
    result = await server.request_handlers[type(req)](req)
    assert isinstance(result.root, ListToolsResult)
    hints = {}
    for tool in result.root.tools:
        assert tool.annotations is not None, tool.name
        hints[tool.name] = tool.annotations
    assert hints["get_positions"].readOnlyHint is True and hints["get_positions"].destructiveHint is False
    assert hints["delete_cache"].readOnlyHint is False and hints["delete_cache"].destructiveHint is True
    assert hints["fetch_page"].openWorldHint is True and hints["get_positions"].openWorldHint is False
    assert hints["run_backtest"].readOnlyHint is False and hints["run_backtest"].destructiveHint is False


def test_read_only_tools_declare_no_mutating_capability():
    for name, caps in ALL_CAPABILITIES.items():
        if "READ_ONLY" in caps:
            assert not caps & MUTATING, f"{name} is READ_ONLY yet declares {caps & MUTATING}"


def test_the_schemas_handed_to_the_model_carry_no_capabilities_key(mock_config):
    """The Anthropic API rejects unknown keys on a tool; `tools` must strip the field."""
    from unittest.mock import MagicMock

    from ibkr_core_mcp.claude_tools import ClaudeToolkit

    toolkit = ClaudeToolkit(MagicMock(), MagicMock(), MagicMock(), mock_config)
    assert all("capabilities" not in t for t in toolkit.tools)
    assert [t["name"] for t in toolkit.tools] == [t["name"] for t in TOOL_DEFINITIONS]


# ── Honesty: the source agrees with the declaration ────────────────────────────


@pytest.mark.parametrize("tool", [t["name"] for t in TOOL_DEFINITIONS])
def test_every_sink_a_handler_touches_is_declared(tool):
    declared = ALL_CAPABILITIES[tool]
    implied = _implied(_handler_source(tool))
    assert implied <= declared, f"{tool} touches {sorted(implied - declared)} but declares only {sorted(declared)}"


def test_the_mutating_tool_list_is_the_documented_one():
    """The answer to "which tools mutate state?", frozen. Update SECURITY.md with it."""
    mutating = {name for name, caps in ALL_CAPABILITIES.items() if caps & MUTATING}
    assert mutating == {
        "fetch_market_data",
        "delete_cache",
        "get_trades",
        "sync_flex_trades",
        "sync_flex_archive",
        "import_flex_file",
        "verify_flex_import",
        "run_backtest",
        "preview_order",
        "create_price_alert",
        "modify_price_alert",
        "delete_alert",
        "activate_alert",
        "firecrawl_search",
        "crawl_site",
        "search_site",
        "fetch_page",
        "add_price_alert",
    }


# ── Guard on the guard ─────────────────────────────────────────────────────────


def test_the_implication_probe_sees_an_undeclared_sink():
    snippet = "def _h(self, inputs):\n    self._client.create_alert('U1', {})\n    self._store.save_backtest({})\n"
    assert _implied(snippet) == {"ACCOUNT_STATE", "DATABASE"}
