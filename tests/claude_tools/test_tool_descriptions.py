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
    return str(next(t for t in toolkit.tools if t["name"] == "get_market_snapshot")["description"])


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


# ── Description honesty as a PROPERTY, not as a list of known cases ────────────
#
# This file is the description-honesty suite and it held six hand-written assertions about
# six descriptions somebody had thought of. TOOL-03, TOOL-04 and TOOL-05 were three nobody
# had — so the suite was green while a description sent users to a folder no code reads,
# another promised page content the handler truncates to 400 characters, and a third
# declared itself read-only while performing two database writes.
#
# The three checks below are properties over ALL tools, so the next one is caught without
# anybody thinking of it. Each was run against the tree before it was fixed and reported
# exactly the known offender — that is what makes a green run afterwards mean something.
#
# The shared root, found while verifying them: each of the three handlers' own DOCSTRING is
# accurate ("Returns where to look, not what is there"; "Updates verified_at in the
# manifest"). The 2026-07-30 refactor updated the docstrings and left the descriptions.
# Docstrings are for humans; the description is the only text the model ever sees.

_MUTATING_CAPABILITIES = {"DATABASE", "GOOGLE_DRIVE", "ACCOUNT_STATE"}
_READ_ONLY_CLAIM = re.compile(
    r"does not modify|never modifies|read-only|readonly|makes no changes|without modifying", re.I
)
_FOLDER_TOKEN = re.compile(r"'([a-z0-9_]{5,})'|\b([a-z0-9_]{5,}/)")


def _capability_names(tool):
    return {c.name if hasattr(c, "name") else str(c) for c in tool.get("capabilities", ())}


def test_the_capability_source_actually_carries_capabilities():
    """Vacuity guard for the test below, and it has already fired once.

    That test first read `toolkit.tools`, which is the wire format sent to the Anthropic
    API and deliberately drops `capabilities` — so `_capability_names` returned an empty
    set for every tool and the check passed against a tree that contained a known
    offender. `TOOL_DEFINITIONS` is the declaration; `toolkit.tools` is the projection.
    """
    from ibkr_core_mcp.claude_tools import TOOL_DEFINITIONS

    assert all("capabilities" in t for t in TOOL_DEFINITIONS)
    declared = {c for t in TOOL_DEFINITIONS for c in _capability_names(t)}
    assert declared & _MUTATING_CAPABILITIES, "no tool declares a mutating capability — check is vacuous"


def test_no_description_claims_read_only_while_declaring_a_mutating_capability():
    """`verify_flex_import` said "Does not modify any data — read-only integrity check"
    while declaring `DATABASE` and calling `store.log_flex_import()` and
    `store.mark_flex_import_verified()` (TOOL-05).

    Both writes go to `flex_import_log`, the import manifest, and **neither touches the
    `trades` table** — checked in `store.py`, not assumed. So the description was not
    describing a dangerous tool, it was making an unqualified claim about a tool that does
    write. The fix names what it writes rather than reversing the claim.

    The capability declaration was right all along; `test_tool_capabilities.py` checks that
    every sink is declared. Nothing checked the description against it.
    """
    from ibkr_core_mcp.claude_tools import TOOL_DEFINITIONS

    offenders = {
        str(t["name"]): sorted(_capability_names(t) & _MUTATING_CAPABILITIES)
        for t in TOOL_DEFINITIONS
        if _READ_ONLY_CLAIM.search(str(t["description"])) and _capability_names(t) & _MUTATING_CAPABILITIES
    }
    assert offenders == {}, f"descriptions claiming read-only while declaring a write: {offenders}"


def test_every_folder_a_description_names_exists_somewhere_in_the_code(package_source, toolkit):
    """`sync_flex_archive` told users to upload to `'ibkr_flex_archive'`; the handler reads
    `account_data/` and says so in its own error message. The string appeared **exactly
    once in the whole package — inside that description** (TOOL-03).

    Counting occurrences rather than searching is deliberate: a first attempt stripped the
    descriptions from the source and searched the remainder, which found nothing, because
    the description is split across source lines and the strip silently failed. A check
    that reports clean against a known offender is broken, not clean.
    """
    all_descriptions = "\n".join(t["description"] for t in toolkit.tools)

    def count(token, text):
        return len(re.findall(rf"\b{re.escape(token)}\b", text))

    offenders = {}
    for tool in toolkit.tools:
        for quoted, slashed in _FOLDER_TOKEN.findall(tool["description"]):
            token = (quoted or slashed).rstrip("/")
            if token in {"markdown", "google", "drive", "sqlite", "python"}:
                continue
            if count(token, package_source) == count(token, all_descriptions):
                offenders[tool["name"]] = token
    assert offenders == {}, f"descriptions naming a folder no code reads: {offenders}"


def test_no_description_promises_content_a_handler_truncates(toolkit):
    """`firecrawl_search` promised "return full page content as markdown" while the handler
    emits `" ".join(markdown.split())[:400]` — a 400-character snippet with an ellipsis
    (TOOL-04). Its own docstring says the opposite: "Returns where to look, not what is
    there. `fetch_page` reads a chosen result."

    The 2026-07-30 refactor gave each tool one job and made `firecrawl_search` a finder;
    the description still advertised the deleted behaviour, which is the more expensive
    kind of wrong — a model that believes it will not call `fetch_page`.
    """
    promises_full_content = re.compile(r"full page content|complete page content|entire page", re.I)
    offenders = [t["name"] for t in toolkit.tools if promises_full_content.search(t["description"])]
    assert offenders == [], f"descriptions promising full page content: {offenders}"
