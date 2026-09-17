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


def test_every_tracked_file_stating_the_live_suite_size_agrees_with_it():
    """The count lives in three files, and a fix once reached two of them.

    DOCB-R3 corrected "11 tests" in `web-scraper-reference.md` and `CLAUDE.md`; DOCA-R2 then
    found `README.md` still saying 11 — *"the third site, missed when the first two were
    fixed"*. So this does not name the files: it finds every tracked file that states the
    size and requires all of them to agree with the suite itself. A fourth site added later
    is covered without anyone remembering to add it here.

    `docs/plans/` is excluded because the whole directory is gitignored (`.gitignore:55`) —
    a private working plan is not a published claim. `docs/audits/` is excluded because a
    dated audit records what was true on its day and must not be rewritten.
    """
    total = sum(_gate_counts().values())
    pattern = re.compile(r"(\d+) tests, ~\d+\s?s")
    skip = {".venv", ".git", "build", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"}

    claims: dict[str, int] = {}
    for path in sorted(_REPO.rglob("*")):
        if not path.is_file() or path.suffix not in {".md", ".py"}:
            continue
        rel = path.relative_to(_REPO).as_posix()
        if any(part in skip for part in path.parts) or rel.startswith(("docs/audits/", "docs/plans/")):
            continue
        for number, line in enumerate(path.read_text(errors="ignore").splitlines(), 1):
            if found := pattern.search(line):
                claims[f"{rel}:{number}"] = int(found.group(1))

    assert claims, "no tracked file states the live web suite size any more; update or remove this guard"
    wrong = {where: n for where, n in claims.items() if n != total}
    assert not wrong, f"the live web suite holds {total} tests; these disagree: {wrong}"


# ---------------------------------------------------------------------------
# The positions page size, stated in two files (API-05)
# ---------------------------------------------------------------------------

# Frozen here on purpose, not imported from the code under test. IBKR's own page says it
# twice — "The endpoint supports paging, each page will return up to 100 positions" and
# "One page contains a maximum of 100 positions"
# (https://ibkrcampus.com/docs/web-api/v1/endpoints/portfolio/positions). A guard that read
# the number out of `client.py` would follow the source anywhere it drifted, which is how a
# mutant survived in `tests/security/test_published_identifiers.py`.
_IBKR_POSITIONS_PAGE_SIZE = 100


def test_the_positions_page_size_agrees_across_every_place_that_states_it():
    """API-05. `get_positions` said "page 0 = first 30" while IBKR documents 100.

    Corrected in `client.py` in session 9 — and `docs/api-reference.md` kept saying 30, in
    the line directly above a section that same edit *added*. Two copies of one fact, one
    of them fixed. The number is small and the drift is invisible, so it is pinned here.
    """
    import inspect

    from ibkr_core_mcp.client import IBKRClient

    doc = (_REPO / "docs" / "api-reference.md").read_text()
    docstring = inspect.getdoc(IBKRClient.get_positions) or ""

    claimed = _documented(r"page 0 = first (\d+)", doc) | _documented(r"page 0 = first (\d+)", docstring)
    assert claimed, "neither file states a positions page size any more; update or remove this guard"
    assert claimed == {_IBKR_POSITIONS_PAGE_SIZE}, (
        f"positions page size claimed as {claimed}, IBKR documents {_IBKR_POSITIONS_PAGE_SIZE}"
    )


# ---------------------------------------------------------------------------
# docs/test-coverage.md's headline counts (DOCB-R1)
# ---------------------------------------------------------------------------


def test_test_coverage_headline_matches_a_real_collection():
    """DOCB-R1 drifted twice, the second time in a single day.

    The file has said "do not edit these numbers by hand; re-run the commands below" since
    2026-09-08. It was 30% wrong for eight days, was corrected on 2026-09-16, and by
    2026-09-17 read 1,459 / 100 / 1,559 against a real 1,523 / 102 / 1,625 — the audit's own
    sessions having added 64 unit tests. The rule was right both times and followed neither.

    So the count is taken from pytest, not from a person. Collection is spawned in a
    subprocess because pytest's own count is the only one that matches what the file claims
    to state: an AST count of `def test_` functions cannot see `parametrize` expansion, and
    that is exactly where a hand-count goes wrong. Coverage is deliberately NOT checked here
    — it needs a full instrumented run, which does not belong in the unit suite.
    """
    import subprocess
    import sys

    doc = (_REPO / "docs" / "test-coverage.md").read_text()
    stated = re.search(r"\*\*([\d,]+) unit tests · ([\d,]+) integration tests \(([\d,]+) total\)", doc)
    assert stated, "test-coverage.md no longer states its headline counts; update or remove this guard"
    unit, integration, total = (int(g.replace(",", "")) for g in stated.groups())
    assert unit + integration == total, f"the headline does not add up: {unit} + {integration} != {total}"

    def collected(marker):
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q", "-m", marker, "-p", "no:cacheprovider"],
            cwd=_REPO,
            capture_output=True,
            text=True,
            check=False,
        )
        lines = [ln for ln in proc.stdout.splitlines() if re.match(r"^tests/.*::", ln)]
        # Separate "nothing collected" from "collection broke" — a zero read as a real count
        # is the same failure as scoring a crashed pytest run as a caught mutant.
        assert lines, f"collection for -m {marker!r} produced no tests (exit {proc.returncode}):\n{proc.stdout[-2000:]}"
        return len(lines)

    assert collected("not integration") == unit, f"headline says {unit} unit tests"
    assert collected("integration") == integration, f"headline says {integration} integration tests"


# ---------------------------------------------------------------------------
# TOOL-R2 — `pyproject.toml` is a claim about what this package is
# ---------------------------------------------------------------------------

_MODEL_SDKS = ("anthropic", "openai", "google-generativeai", "google-genai", "cohere", "mistralai")


def _base_dependencies() -> list[str]:
    """`[project].dependencies` — what every consumer installs, no extras."""
    import tomllib

    return list(tomllib.loads((_REPO / "pyproject.toml").read_text())["project"]["dependencies"])


def _modules_importing(package: str) -> list[str]:
    """Every shipped module that imports `package` at any level."""
    hits = []
    for source in sorted((_REPO / "ibkr_core_mcp").rglob("*.py")):
        for node in ast.walk(ast.parse(source.read_text())):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module] if node.module else []
            else:
                continue
            if any(n == package or n.startswith(f"{package}.") for n in names):
                hits.append(f"{source.name}:{node.lineno}")
    return hits


def test_no_model_sdk_is_a_base_dependency():
    """A dependency nothing imports is a claim the package makes about itself that is false.

    `anthropic>=0.28` sat in `[project].dependencies` from the beginning: every consumer
    installed it, and **no shipped module ever imported it** — the only importer in the
    repository is `scripts/audit/count_tool_tokens.py`, an audit artifact. Someone reading
    `pyproject.toml` would conclude this library talks to Anthropic. It does not: it defines
    tools, and the host application owns the model client (TOOL-07, TOOL-R2, 2026-09-17).

    Stated over a list of vendors rather than one name, for the same reason as
    `test_config_carries_no_model_vendor_credential`: the rule is "this package does not
    call a model", not "this package does not call Anthropic".
    """
    base = " ".join(_base_dependencies()).lower()
    present = [sdk for sdk in _MODEL_SDKS if re.search(rf"(?:^| ){re.escape(sdk)}(?:[<>=!~\[ ]|$)", base)]

    assert not present, (
        f"model SDKs in [project].dependencies: {present}. Every consumer installs these. "
        "If a shipped module genuinely needs one, say so here; otherwise it belongs in an "
        "extra beside the script that imports it."
    )


def test_no_shipped_module_imports_a_model_sdk():
    """The other direction, so the rule above cannot be satisfied by a broken package.

    If a module under `ibkr_core_mcp/` ever does import one, the dependency must come back —
    and this test failing is how that gets noticed, rather than an ImportError in a consumer.
    """
    importers = {sdk: _modules_importing(sdk.replace("-", "_")) for sdk in _MODEL_SDKS}
    offenders = {sdk: where for sdk, where in importers.items() if where}

    assert not offenders, (
        f"shipped modules import a model SDK: {offenders}. ClaudeToolkit is a tool "
        "*definition* layer — CLAUDE.md's rule is that the bar for calling a model from here "
        "is 'no other design works'. If this is deliberate, add the dependency back to "
        "[project].dependencies in the same change."
    )


def test_the_import_probe_can_actually_find_an_import():
    """Vacuity guard: both tests above assert an absence, so the probe must be shown to work."""
    assert _modules_importing("requests"), "the import probe found no `requests` import — it is broken"
