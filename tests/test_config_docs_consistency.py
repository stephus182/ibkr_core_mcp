"""Guards that documented defaults match the code.

`.env.example` said `https://localhost:5055` while `Config.from_env` defaulted to
`https://localhost:5055/v1/api`, and `IBKRClient` appends endpoint paths verbatim to
whatever it is given. So copying `.env.example` — the documented way to start —
produced `https://localhost:5055/portfolio/accounts` and every request 404'd. A
wrong default in an example file is a bug with a documentation-shaped disguise.
"""

import ast
import re
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent


def _env_example_value(key: str) -> str:
    for line in (_REPO / ".env.example").read_text().splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    raise AssertionError(f"{key} not found in .env.example")


def test_env_example_gateway_url_matches_the_code_default():
    import inspect

    from ibkr_core_mcp import config as config_mod

    src = inspect.getsource(config_mod.Config.from_env)
    m = re.search(r'os\.environ\.get\(\s*"IBKR_GATEWAY_URL",\s*"([^"]+)"', src)
    assert m, "could not locate the IBKR_GATEWAY_URL default in Config.from_env"
    assert _env_example_value("IBKR_GATEWAY_URL") == m.group(1)


def test_gateway_url_default_carries_the_api_prefix():
    """The specific breakage: paths are appended verbatim, so the prefix is load-bearing."""
    assert _env_example_value("IBKR_GATEWAY_URL").endswith("/v1/api")


def test_readme_documents_the_same_gateway_default():
    readme = (_REPO / "README.md").read_text()
    assert _env_example_value("IBKR_GATEWAY_URL") in readme


def test_readme_tool_count_matches_the_code():
    """README said "42 ready-made Claude AI tools" while TOOL_DEFINITIONS held 44 —
    and README's own line 232 already said 44. Two numbers, one source of truth."""
    from ibkr_core_mcp.claude_tools import TOOL_DEFINITIONS

    readme = (_REPO / "README.md").read_text()
    claimed = {int(n) for n in re.findall(r"(\d+) ready-made Claude AI tools", readme)}
    assert claimed, "README no longer states a tool count; update or remove this guard"
    assert claimed == {len(TOOL_DEFINITIONS)}, f"README claims {claimed}, code has {len(TOOL_DEFINITIONS)}"


# ---------------------------------------------------------------------------
# The live web suite's requirements table (docs/web-scraper-reference.md § 10)
# ---------------------------------------------------------------------------

_LIVE_SUITE = _REPO / "tests" / "test_web_tools_live.py"
_SCRAPER_DOC = _REPO / "docs" / "web-scraper-reference.md"


def _collected_count(fn) -> int:
    """How many items pytest collects for one test function — 1 unless parametrised."""
    total = 1
    for dec in fn.decorator_list:
        if not isinstance(dec, ast.Call):
            continue
        func = dec.func
        if isinstance(func, ast.Attribute):
            name = func.attr
        elif isinstance(func, ast.Name):
            name = func.id
        else:
            continue
        if name != "parametrize" or len(dec.args) < 2:
            continue
        cases = dec.args[1]
        assert isinstance(cases, ast.List | ast.Tuple), (
            "parametrize cases are no longer a literal — this guard can no longer count them"
        )
        total *= len(cases.elts)
    return total


def _gate_counts() -> dict[str, int]:
    """Classify every live-suite test item by the requirement that gates it.

    Read from the AST rather than by running the suite, because this runs in the unit
    table. The classification was validated by running the real suite under each
    condition on 2026-09-17 (§10 of the scraper reference records the four runs):
    blocking `import crawl4ai` skipped exactly **8**; removing the key skipped exactly
    **1**; with both absent exactly **3** still passed, in 0.44 s with no network.
    """
    text = _LIVE_SUITE.read_text()
    lines = text.splitlines()
    counts = {"browser": 0, "firecrawl": 0, "neither": 0}
    for node in ast.walk(ast.parse(text)):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if not node.name.startswith("test_"):
            continue
        body = "\n".join(lines[node.lineno - 1 : node.end_lineno or node.lineno])
        if "browser_available" in {a.arg for a in node.args.args}:
            counts["browser"] += _collected_count(node)
        elif "FIRECRAWL_API_KEY" in body:
            counts["firecrawl"] += _collected_count(node)
        else:
            counts["neither"] += _collected_count(node)
    return counts


def _documented(pattern: str, text: str) -> set[int]:
    return {int(n) for n in re.findall(pattern, text)}


def _requirements_table(doc: str) -> str:
    """Just the rows of § 10's requirements table.

    Scoped deliberately. The first version of this guard scanned the whole document and
    failed on § 10's own history note — *"this table read 'the 10 browser tests' until
    2026-09-17"* — which states the superseded number on purpose. A guard that cannot
    tell a live claim from a record of a corrected one would force the record to be
    deleted to stay green, which is the wrong direction: the table is the claim, the
    blockquote is the history, and only the table is checked.
    """
    rows: list[str] = []
    for line in doc.splitlines():
        if not line.startswith("|"):
            if rows:
                break
            continue
        if not rows and not ("Requirement" in line and "Gates" in line):
            continue
        rows.append(line)
    assert rows, "§ 10's requirements table is gone; update or remove this guard"
    return "\n".join(rows)


def test_scraper_doc_gate_counts_match_the_live_suite():
    """The table drifted twice: it said 11 tests when there were 12 (DOCB-R3), and
    "the 10 browser tests" when `browser_available` gated 8 (2026-09-17). Both were
    found by a human reading, months apart. The counts are derivable, so derive them."""
    doc = _requirements_table(_SCRAPER_DOC.read_text())
    actual = _gate_counts()

    for label, pattern in (
        ("browser", r"\*{0,2}(\d+)\*{0,2} browser tests"),
        ("firecrawl", r"\*{0,2}(\d+)\*{0,2} whole-web search test"),
        ("neither", r"\*{0,2}(\d+)\*{0,2} private-host refusals"),
    ):
        claimed = _documented(pattern, doc)
        assert claimed, f"§10's table no longer states a {label} count; update or remove this guard"
        assert claimed == {actual[label]}, f"§10 claims {claimed} {label} tests, the suite has {actual[label]}"


def test_scraper_doc_total_matches_the_sum_of_its_own_rows():
    """`8 + 1 + 3 = 12` must hold against the suite, not just against itself — a partial
    edit that fixes one row and leaves the headline is the exact failure seen twice."""
    doc = _SCRAPER_DOC.read_text()
    claimed = _documented(r"(\d+) tests, ~\d+\s?s", doc)
    assert claimed, "§10 no longer states a suite size; update or remove this guard"
    assert claimed == {sum(_gate_counts().values())}


def test_claude_md_and_the_scraper_doc_state_the_same_suite_size():
    """DOCB-R3: both said 11 while the suite held 12. One source of truth, two files."""
    claude_md = (_REPO / "CLAUDE.md").read_text()
    claimed = _documented(r"(\d+) tests, ~\d+\s?s", claude_md)
    assert claimed, "CLAUDE.md no longer states the live web suite size; update or remove this guard"
    assert claimed == {sum(_gate_counts().values())}
