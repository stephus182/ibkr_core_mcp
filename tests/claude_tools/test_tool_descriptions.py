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


def test_firecrawl_search_exposes_wait_for_and_proxy(toolkit):
    """Was a loop over firecrawl_search AND firecrawl_crawl. The crawl tool was removed
    on 2026-07-30 — crawl_site does that job locally and free — so only search remains,
    and these anti-bot overrides only ever applied to a Firecrawl request anyway."""
    tool = next(t for t in toolkit.tools if t["name"] == "firecrawl_search")
    schema = tool["input_schema"]
    props = schema.get("properties", {})
    required = schema.get("required", [])
    assert "wait_for_ms" in props
    assert "proxy" in props
    assert props["proxy"]["enum"] == ["basic", "enhanced", "auto"]
    assert "wait_for_ms" not in required
    assert "proxy" not in required


def test_the_crawl_and_search_tools_route_by_capability(toolkit):
    """The whole point of the 2026-07-30 refactor: one tool per job, and the model has to
    be able to tell them apart from their descriptions alone.

    firecrawl_search is the only whole-web search; search_site is domain-scoped and free;
    crawl_site archives; fetch_page reads one page. If two of these ever start describing
    themselves the same way, the model will pick the wrong one and the ladder we deleted
    will effectively come back as a routing bug.
    """
    names = {t["name"] for t in toolkit.tools}
    assert {"firecrawl_search", "search_site", "crawl_site", "fetch_page"} <= names
    assert "firecrawl_crawl" not in names, "the paid crawl rung was removed; crawl_site replaces it"

    by_name = {t["name"]: t["description"] for t in toolkit.tools}
    assert "fetch_page" in by_name["search_site"], "search_site must hand off to fetch_page"
    assert "firecrawl_search" in by_name["search_site"], "search_site must name the whole-web alternative"
    assert "search_site" in by_name["crawl_site"], "crawl_site must point at the finder"


# Tools that existed once and were deleted. A description may never send the model to one:
# it is not in the tools array, so the call cannot be made, and the model has no way to learn
# that from the text it was given.
_REMOVED_TOOLS = ("firecrawl_crawl", "judge_completeness_llm")


def test_no_description_routes_the_model_to_a_deleted_tool(toolkit):
    """`test_the_crawl_and_search_tools_route_by_capability` already asserts the deleted tools
    are absent from the *names*. That is what let this slip: `firecrawl_crawl` was removed from
    the array on 2026-07-30 while `fetch_page`'s description kept saying "For API or reference
    documentation prefer firecrawl_search / firecrawl_crawl", found 2026-07-30 by reading what
    the model actually receives.

    Descriptions are the only tool guidance the model ever sees — a rule in a Python docstring
    reaches nobody. So a dangling cross-reference is a live routing defect, not a typo.
    """
    for tool in toolkit.tools:
        for removed in _REMOVED_TOOLS:
            assert removed not in tool["description"], (
                f"{tool['name']}'s description points the model at '{removed}', which no longer exists"
            )


def test_fetch_page_names_a_challenge_page_as_a_block(toolkit):
    """A captcha/"Security Verification" interstitial is a block, and the failure mode is that
    it does not look like one: it returns a plausible page rather than an error, so the model
    retries or reports the challenge text as the article. wsj.com's 1 B case was already
    called out; ft.com's challenge (observed 2026-07-30 when a profile was replayed headless)
    is the same class and needed saying too.
    """
    description = next(t for t in toolkit.tools if t["name"] == "fetch_page")["description"]
    assert "Security Verification" in description or "captcha" in description.lower()
    assert "do not retry" in description.lower() or "rather than retrying" in description.lower()


def _snapshot_description(toolkit) -> str:
    return next(t for t in toolkit.tools if t["name"] == "get_market_snapshot")["description"]


def test_snapshot_description_instructs_reporting_the_currency(toolkit):
    """The model only reports what the *description* asks for — docstrings never reach it.

    Live 2026-07-28: the description said "Always report both" of _data_status and
    _quote_time and ClaudIA reported both in every answer, while _currency went
    unmentioned in the description and was rendered as a bare '$91.42'. The field being
    present in the JSON is necessary and demonstrably not sufficient.
    """
    description = _snapshot_description(toolkit)
    assert "_currency" in description


def test_snapshot_description_forbids_a_bare_currency_symbol(toolkit):
    """'$' is not a currency. It is USD, MXN, CAD, AUD, HKD and SGD at once — and the
    regression this guards is precisely IGV priced in pesos reading as dollars."""
    description = _snapshot_description(toolkit)
    assert "ISO" in description
    assert "MXN" in description
    assert "$" in description


def test_snapshot_description_does_not_promise_first_result_is_used(toolkit):
    """Stale since the isUS resolver landed: without `exchange` the US listing is
    selected, or an ambiguity question is returned — never 'the first result'."""
    description = _snapshot_description(toolkit)
    assert "first result is used" not in description
