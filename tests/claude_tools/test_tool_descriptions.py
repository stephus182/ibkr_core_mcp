import re


def test_tools_returns_list_of_dicts(toolkit):
    tools = toolkit.tools
    assert isinstance(tools, list)
    assert len(tools) >= 14
    for t in tools:
        assert "name" in t
        assert "description" in t
        assert "input_schema" in t


def test_all_tools_have_required_fields(toolkit):
    for tool in toolkit.tools:
        assert isinstance(tool["name"], str)
        assert isinstance(tool["description"], str)
        schema = tool["input_schema"]
        assert schema.get("type") == "object"
        assert "properties" in schema


def test_execute_unknown_tool_returns_error(toolkit):
    text, fig = toolkit.execute("nonexistent_tool", {})
    assert "unknown" in text.lower() or "error" in text.lower()
    assert fig is None


def test_tools_count_matches_definitions_exactly(toolkit):
    """Tightened from the old 'at least 19' check: fails the moment a tool is
    added or removed without updating this test, instead of silently passing."""
    from ibkr_core_mcp.claude_tools import TOOL_DEFINITIONS

    assert len(toolkit.tools) == len(TOOL_DEFINITIONS)


def test_required_params_exist_in_properties(toolkit):
    """Every 'required' entry in a tool's schema must be a real property key."""
    for tool in toolkit.tools:
        schema = tool["input_schema"]
        required = schema.get("required", [])
        properties = schema.get("properties", {})
        for param in required:
            assert param in properties, (
                f"{tool['name']!r} lists {param!r} as required but it is not in properties: {sorted(properties)}"
            )


def test_no_tool_claims_execution_capability(toolkit):
    """ClaudeToolkit ships zero order-write tools by design (see CLAUDE.md's
    'Claude AI Tool Layer' section) — this is a regression guard, not a
    style check. If this ever fails, a future tool addition has accidentally
    implied write/execution capability in its description.

    Word-boundary matching (not plain substring): a bare `in` check false-
    positives on incidental phrasing like "buying power" (contains "buy") or
    "without placing the order" (contains "place"), neither of which claims
    execution capability.
    """
    execution_verbs = ("place", "buy", "sell", "submit", "cancel order", "modify order")
    for tool in toolkit.tools:
        description = tool["description"].lower()
        for verb in execution_verbs:
            assert not re.search(rf"\b{re.escape(verb)}\b", description), (
                f"{tool['name']!r} description contains {verb!r}: {tool['description']!r}"
            )


def test_scraper_tools_expose_wait_for_and_proxy(toolkit):
    for name in ("firecrawl_search", "firecrawl_crawl"):
        tool = next(t for t in toolkit.tools if t["name"] == name)
        schema = tool["input_schema"]
        props = schema.get("properties", {})
        required = schema.get("required", [])
        assert "wait_for_ms" in props
        assert "proxy" in props
        assert props["proxy"]["enum"] == ["basic", "enhanced", "auto"]
        assert name not in required
        assert "wait_for_ms" not in required
        assert "proxy" not in required
