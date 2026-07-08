# claude_tools Test Suite Restructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `tests/test_claude_tools.py` (2373 lines, 177 tests, zero internal
structure) into a domain-organized `tests/claude_tools/` package with markers,
shared fixtures, and a new schema/description-honesty test file — while fixing
the 3 tests discovered to make real sleeps/network calls, plus a same-shape bug
in `test_client.py`, and adding a repo-wide guardrail fixture so this class of
bug can't silently recur.

**Architecture:** 9 domain test files + `test_tool_descriptions.py` (Layer 1) +
`test_errors.py`, all under `tests/claude_tools/`, sharing one `toolkit`
fixture in a local `conftest.py`. Bulk test bodies move via exact `sed` line
extraction from the original file (not hand-retyped — see "How the bulk moves
work" below) to guarantee byte-for-byte fidelity. A small number of tests are
rewritten by hand where behavior actually changes (the 3 slow tests, the
`_safe_error` parametrize table, the 6 `test_client.py` tests).

**Tech Stack:** pytest 8.x, `pytest-socket` (new dev dependency), `unittest.mock`.

**Design doc:** `docs/2026-07-08-claude-tools-test-reorg-design.md` — read this
first if anything below is unclear on *why*, not just *what*.

---

## How the bulk moves work

`tests/test_claude_tools.py` is not deleted until Task 19, so it remains
available as a reference throughout. For each domain file, the task gives you
an exact shell command using `sed -n 'START,ENDp;START2,END2p;...' tests/test_claude_tools.py`
to extract the verbatim test bodies for that domain, in file order, and pipe
them into the new file behind a small header. **The line ranges were derived
from `grep -n "^def test_"` against the file and spot-checked, but were not
individually verified line-by-line for every boundary.** If a domain file's
`pytest --collect-only` step fails with a `SyntaxError` or `IndentationError`,
or a function looks visibly cut off at the top/bottom when you check the
output file, open `tests/test_claude_tools.py` at the reported line and adjust
the range by a few lines — the extraction is mechanical but the exact
boundary (blank line vs. comment banner) wasn't hand-verified for all ~45
ranges. Do not skip the `--collect-only` and full-run verification steps in
each task; they exist specifically to catch this.

---

## Task 1: Capture baseline test inventory (before any changes)

**Files:** none created/modified — this is a read-only safety net for Task 19.

- [x] **Step 1: Capture the sorted list of test names currently in the file**

Run:
```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
pytest tests/test_claude_tools.py --collect-only -q | grep "::" | sed 's/.*:://' | sort > /tmp/claude_tools_baseline.txt
wc -l /tmp/claude_tools_baseline.txt
```
Expected: `177 /tmp/claude_tools_baseline.txt`

- [x] **Step 2: Confirm current full-suite timing baseline (for the final comparison in Task 19)**

Run:
```bash
pytest -m "not integration" -q 2>&1 | tail -3
```
Expected: `669 passed, 84 deselected` and a runtime around 24-25s. Note the
exact number down — Task 19 compares against it.

No commit for this task (nothing changed yet).

---

## Task 2: Add pytest-socket dependency and register pytest markers

**Files:**
- Modify: `pyproject.toml`

- [x] **Step 1: Add `pytest-socket` to the `dev` extra**

In `pyproject.toml`, find:
```toml
dev = ["pytest>=8.0", "pytest-asyncio>=0.23", "pytest-mock>=3.12", "mypy>=1.8", "ruff>=0.3"]
```
Replace with:
```toml
dev = ["pytest>=8.0", "pytest-asyncio>=0.23", "pytest-mock>=3.12", "pytest-socket>=0.7", "mypy>=1.8", "ruff>=0.3"]
```

- [x] **Step 2: Register the new markers**

Find:
```toml
[tool.pytest.ini_options]
markers = ["integration: requires live IBKR gateway and credentials"]
```
Replace with:
```toml
[tool.pytest.ini_options]
markers = [
    "integration: requires live IBKR gateway and credentials",
    "market_data: claude_tools market-data handlers",
    "account: claude_tools account/portfolio handlers",
    "trades: claude_tools trade-history handlers",
    "orders: claude_tools order read/preview handlers",
    "flex: claude_tools Flex Query handlers",
    "alerts: claude_tools price-alert handlers",
    "pa_analytics: claude_tools PA/analytics handlers",
    "backtest_pinescript: claude_tools backtest/pinescript handlers",
    "web_scraping: claude_tools firecrawl/scrape-fallback handlers",
    "errors: claude_tools _safe_error mapping",
]
```

- [x] **Step 3: Install the new dependency**

Run: `pip install -e ".[dev]"`
Expected: `pytest-socket` installed, no errors.

- [x] **Step 4: Verify markers are recognized**

Run: `pytest --markers | grep -E "market_data|account|trades|orders|flex|alerts|pa_analytics|backtest_pinescript|web_scraping|errors"`
Expected: all 10 new marker lines printed, no "unknown marker" warnings anywhere.

- [x] **Step 5: Commit**

```bash
git add pyproject.toml
git commit -m "$(cat <<'EOF'
build: add pytest-socket dev dependency and register claude_tools test markers

Prepares for the tests/claude_tools/ domain split and the repo-wide
sleep/socket guardrail fixture added in the next task.
EOF
)"
```

---

## Task 3: Add the repo-wide `_no_real_io` guardrail fixture

**Files:**
- Modify: `tests/conftest.py`

This fixture is added to the ROOT conftest (not `tests/claude_tools/conftest.py`)
so it protects all 753 tests, not just the claude_tools subset — see the
design doc's "Why not restructure the whole repo" section. It must exempt
anything marked `integration`, since the 5 live test files intentionally use
real sockets and timing.

- [x] **Step 1: Read the current file to confirm exact current content**

Run: `cat tests/conftest.py`
Expected: the existing `tmp_db` and `mock_config` fixtures, nothing else.

- [x] **Step 2: Add the guardrail fixture**

Append to `tests/conftest.py`:
```python

@pytest.fixture(autouse=True)
def _no_real_io(request, monkeypatch):
    """Block real sleeps and real network I/O in every non-integration test.

    Added after discovering 3 claude_tools tests and 6 client.py tests were
    silently paying real wall-clock time (unmocked time.sleep) or making a
    real network call (unmocked Crawl4AI construction) despite being "unit"
    tests. Exempts anything marked `integration`, which intentionally hits
    a real gateway/network.
    """
    if request.node.get_closest_marker("integration"):
        yield
        return
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    from pytest_socket import disable_socket, enable_socket
    disable_socket()
    yield
    enable_socket()
```

- [x] **Step 3: Verify non-integration tests still pass (this is the risky step — a bad fixture breaks everything)**

Run: `pytest -m "not integration" -q 2>&1 | tail -5`
Expected: `669 passed, 84 deselected` — same counts as Task 1's baseline. If
anything newly fails, read the failure: it means some non-integration test
was relying on a real sleep or real socket somewhere not yet identified.
Do not proceed until this is green.

- [x] **Step 4: Verify integration tests are unaffected (collection only — don't require live gateway)**

Run: `pytest -m integration --collect-only -q 2>&1 | tail -5`
Expected: `84 tests collected` (or however many `--collect-only` reports),
no collection errors. This confirms the marker-based exemption doesn't break
anything at collection time; actually running integration tests requires a
live gateway and is out of scope for this verification.

- [x] **Step 5: Commit**

```bash
git add tests/conftest.py
git commit -m "$(cat <<'EOF'
test: add repo-wide guardrail against real sleeps and network calls

Autouse fixture in the root conftest blocks time.sleep and real sockets
for every non-integration test, exempting anything marked `integration`
which intentionally uses real timing/network. Closes off the bug class
found in claude_tools and client.py (see docs/2026-07-08-claude-tools-test-reorg-design.md).
EOF
)"
```

---

## Task 4: Create the `tests/claude_tools/` package skeleton

**Files:**
- Create: `tests/claude_tools/__init__.py`
- Create: `tests/claude_tools/conftest.py`

- [x] **Step 1: Create the empty init file**

Run: `touch tests/claude_tools/__init__.py`

- [x] **Step 2: Create the local conftest with the `toolkit` fixture**

Write `tests/claude_tools/conftest.py`:
```python
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def toolkit(mock_config):
    from ibkr_core_mcp.claude_tools import ClaudeToolkit
    client = MagicMock()
    cache = MagicMock()
    store = MagicMock()
    return ClaudeToolkit(client, cache, store, mock_config)
```

- [x] **Step 3: Verify the fixture is discoverable**

Run: `pytest tests/claude_tools/ --collect-only -q`
Expected: `no tests ran` (no test files exist yet) but no collection errors —
confirms `conftest.py` itself is syntactically valid and `mock_config` resolves
from the root `tests/conftest.py`.

- [x] **Step 4: Commit**

```bash
git add tests/claude_tools/__init__.py tests/claude_tools/conftest.py
git commit -m "test: scaffold tests/claude_tools/ package with toolkit fixture"
```

---

## Task 5: Create `test_tool_descriptions.py` (Layer 1)

**Files:**
- Create: `tests/claude_tools/test_tool_descriptions.py`

- [x] **Step 1: Extract the 3 unchanged verbatim tests**

Run:
```bash
{
cat <<'HEADER'
import pytest

HEADER
sed -n '17,40p' tests/test_claude_tools.py
} > tests/claude_tools/test_tool_descriptions.py
```

- [x] **Step 2: Append the tightened tool-count test (replaces the old "at least 19" check) and the 2 new tests**

Append to `tests/claude_tools/test_tool_descriptions.py`:
```python

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
                f"{tool['name']!r} lists {param!r} as required but it is not "
                f"in properties: {sorted(properties)}"
            )


def test_no_tool_claims_execution_capability(toolkit):
    """ClaudeToolkit ships zero order-write tools by design (see CLAUDE.md's
    'Claude AI Tool Layer' section) — this is a regression guard, not a
    style check. If this ever fails, a future tool addition has accidentally
    implied write/execution capability in its description."""
    execution_verbs = ("place", "buy", "sell", "submit", "cancel order", "modify order")
    for tool in toolkit.tools:
        description = tool["description"].lower()
        for verb in execution_verbs:
            assert verb not in description, (
                f"{tool['name']!r} description contains {verb!r}: {tool['description']!r}"
            )
```

- [x] **Step 3: Verify collection and pass**

Run: `pytest tests/claude_tools/test_tool_descriptions.py -v`
Expected: 6 tests pass (`test_tools_returns_list_of_dicts`,
`test_all_tools_have_required_fields`, `test_execute_unknown_tool_returns_error`,
`test_tools_count_matches_definitions_exactly`,
`test_required_params_exist_in_properties`,
`test_no_tool_claims_execution_capability`).

- [x] **Step 4: Lint**

Run: `ruff check tests/claude_tools/test_tool_descriptions.py --fix`
Expected: no remaining issues (or auto-fixed). Re-run Step 3's pytest command
to confirm still green if ruff changed anything.

- [x] **Step 5: Commit**

```bash
git add tests/claude_tools/test_tool_descriptions.py
git commit -m "test: add claude_tools Layer 1 schema/description honesty tests"
```

---

## Task 6: Create `test_market_data.py` (with the sleep-retry fix)

**Files:**
- Create: `tests/claude_tools/test_market_data.py`

- [x] **Step 1: Extract the market-data test bodies**

Run:
```bash
{
cat <<'HEADER'
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.market_data

HEADER
sed -n '42,84p;212,230p;323,440p;666,714p;715,745p;746,775p;1753,1786p;1787,1826p;1827,1862p;1900,1934p;1986,2013p' tests/test_claude_tools.py
} > tests/claude_tools/test_market_data.py
```

- [x] **Step 2: Fix `test_fetch_market_data_empty_data` to not depend on the real 4s retry sleep**

The `_no_real_io` root fixture already neutralizes `time.sleep` for this test,
so it will pass fast regardless — but add an explicit `patch("time.sleep")`
at the call site anyway, matching `test_rate_limiter.py`'s existing convention,
so the test's intent (verifying the "no data after 3 attempts" message, not
verifying real timing) is clear to a future reader without relying on an
autouse fixture they may not know exists. Find this test in the new file:
```python
def test_fetch_market_data_empty_data(toolkit):
    """Paginated endpoint returning empty → error message with 'no data'."""
    toolkit._cache.check.return_value = False
    toolkit._client.search_contract.return_value = [{"conid": 265598}]
    toolkit._client.get_market_history_paginated.return_value = {"data": []}
    text, fig = toolkit.execute("fetch_market_data", {"symbol": "AAPL", "period": "1Y", "bar": "1d"})
    assert "no data" in text.lower()
```
Replace with:
```python
def test_fetch_market_data_empty_data(toolkit):
    """Paginated endpoint returning empty → error message with 'no data'."""
    toolkit._cache.check.return_value = False
    toolkit._client.search_contract.return_value = [{"conid": 265598}]
    toolkit._client.get_market_history_paginated.return_value = {"data": []}
    with patch("time.sleep"):
        text, fig = toolkit.execute("fetch_market_data", {"symbol": "AAPL", "period": "1Y", "bar": "1d"})
    assert "no data" in text.lower()
```

- [x] **Step 3: Verify collection count**

Run: `pytest tests/claude_tools/test_market_data.py --collect-only -q | tail -3`
Expected: `38 tests collected` (if this doesn't match, see "How the bulk moves
work" above — check for a cut-off function near one of the range boundaries).

- [x] **Step 4: Verify all pass and confirm the timing fix worked**

Run: `pytest tests/claude_tools/test_market_data.py -v --durations=5`
Expected: all tests pass; `test_fetch_market_data_empty_data` no longer
appears among the slowest durations (should be under 0.1s, down from 4.01s).

- [x] **Step 5: Lint**

Run: `ruff check tests/claude_tools/test_market_data.py --fix`, then re-run
Step 4's pytest command if anything changed.

- [x] **Step 6: Commit**

```bash
git add tests/claude_tools/test_market_data.py
git commit -m "test: extract claude_tools market-data tests, fix unmocked retry sleep"
```

---

## Task 7: Create `test_account.py`

**Files:**
- Create: `tests/claude_tools/test_account.py`

- [x] **Step 1: Extract**

Run:
```bash
{
cat <<'HEADER'
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.account

HEADER
sed -n '85,95p;198,207p;783,833p;834,891p;892,945p;1863,1899p;1935,1960p;2314,2337p' tests/test_claude_tools.py
} > tests/claude_tools/test_account.py
```

- [x] **Step 2: Verify collection count**

Run: `pytest tests/claude_tools/test_account.py --collect-only -q | tail -3`
Expected: `20 tests collected`.

- [x] **Step 3: Verify all pass**

Run: `pytest tests/claude_tools/test_account.py -v`
Expected: all pass.

- [x] **Step 4: Lint**

Run: `ruff check tests/claude_tools/test_account.py --fix`, re-verify Step 3 if changed.

- [x] **Step 5: Commit**

```bash
git add tests/claude_tools/test_account.py
git commit -m "test: extract claude_tools account/portfolio tests"
```

---

## Task 8: Create `test_trades.py`

**Files:**
- Create: `tests/claude_tools/test_trades.py`

- [x] **Step 1: Extract**

This domain needs the top-level `_parse_live_trades` import (used directly by
several tests, not via the `toolkit` fixture):
```bash
{
cat <<'HEADER'
from unittest.mock import MagicMock, patch

import pytest

from ibkr_core_mcp.claude_tools import _parse_live_trades

pytestmark = pytest.mark.trades

HEADER
sed -n '96,119p;120,197p' tests/test_claude_tools.py
} > tests/claude_tools/test_trades.py
```

- [x] **Step 2: Verify collection count**

Run: `pytest tests/claude_tools/test_trades.py --collect-only -q | tail -3`
Expected: `10 tests collected`.

- [x] **Step 3: Verify all pass**

Run: `pytest tests/claude_tools/test_trades.py -v`
Expected: all pass.

- [x] **Step 4: Lint**

Run: `ruff check tests/claude_tools/test_trades.py --fix`, re-verify if changed.

- [x] **Step 5: Commit**

```bash
git add tests/claude_tools/test_trades.py
git commit -m "test: extract claude_tools trade-history tests"
```

---

## Task 9: Create `test_orders.py`

**Files:**
- Create: `tests/claude_tools/test_orders.py`

- [x] **Step 1: Extract**

```bash
{
cat <<'HEADER'
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.orders

HEADER
sed -n '441,460p;946,1064p;1628,1677p;1961,1985p' tests/test_claude_tools.py
} > tests/claude_tools/test_orders.py
```

- [x] **Step 2: Verify collection count**

Run: `pytest tests/claude_tools/test_orders.py --collect-only -q | tail -3`
Expected: `16 tests collected`.

- [x] **Step 3: Verify all pass**

Run: `pytest tests/claude_tools/test_orders.py -v`

- [x] **Step 4: Lint**

Run: `ruff check tests/claude_tools/test_orders.py --fix`, re-verify if changed.

- [x] **Step 5: Commit**

```bash
git add tests/claude_tools/test_orders.py
git commit -m "test: extract claude_tools order read/preview tests"
```

---

## Task 10: Create `test_flex.py`

**Files:**
- Create: `tests/claude_tools/test_flex.py`

Note the `extract_execution_ids` range ends at line 1220, not 1250 as a naive
read of the next test's start line would suggest — there's a `_make_toolkit()`
helper function for the web-scraping tests sitting between them (lines
1222-1247) that must NOT end up in this file. See design doc discovery notes.

- [x] **Step 1: Extract**

```bash
{
cat <<'HEADER'
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.flex

HEADER
sed -n '776,782p;1065,1133p;1134,1189p;1190,1220p;2071,2131p;2132,2203p;2204,2242p' tests/test_claude_tools.py
} > tests/claude_tools/test_flex.py
```

- [x] **Step 2: Verify collection count**

Run: `pytest tests/claude_tools/test_flex.py --collect-only -q | tail -3`
Expected: `22 tests collected`. If it's higher and includes anything named
`test_firecrawl_*` or `_make_toolkit` artifacts, the 1190,1220 range grabbed
too much — re-check line 1220 is the last line of
`test_extract_execution_ids_within_file_duplicate` (ends with
`assert raw_count == 2  # duplicate detected: raw(2) != unique(1)`) and
line 1222 starts the `# === Firecrawl handler tests ===` banner.

- [x] **Step 3: Verify all pass**

Run: `pytest tests/claude_tools/test_flex.py -v`

- [x] **Step 4: Lint**

Run: `ruff check tests/claude_tools/test_flex.py --fix`, re-verify if changed.

- [x] **Step 5: Commit**

```bash
git add tests/claude_tools/test_flex.py
git commit -m "test: extract claude_tools Flex Query tests"
```

---

## Task 11: Create `test_alerts.py`

**Files:**
- Create: `tests/claude_tools/test_alerts.py`

- [x] **Step 1: Extract**

```bash
{
cat <<'HEADER'
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.alerts

HEADER
sed -n '461,484p;485,564p;565,572p;573,588p;2014,2070p' tests/test_claude_tools.py
} > tests/claude_tools/test_alerts.py
```

- [x] **Step 2: Verify collection count**

Run: `pytest tests/claude_tools/test_alerts.py --collect-only -q | tail -3`
Expected: `15 tests collected`.

- [x] **Step 3: Verify all pass**

Run: `pytest tests/claude_tools/test_alerts.py -v`

- [x] **Step 4: Lint**

Run: `ruff check tests/claude_tools/test_alerts.py --fix`, re-verify if changed.

- [x] **Step 5: Commit**

```bash
git add tests/claude_tools/test_alerts.py
git commit -m "test: extract claude_tools price-alert tests"
```

---

## Task 12: Create `test_pa_analytics.py`

**Files:**
- Create: `tests/claude_tools/test_pa_analytics.py`

- [x] **Step 1: Extract**

```bash
{
cat <<'HEADER'
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.pa_analytics

HEADER
sed -n '305,322p;1678,1703p;1704,1752p;2243,2313p' tests/test_claude_tools.py
} > tests/claude_tools/test_pa_analytics.py
```

- [x] **Step 2: Verify collection count**

Run: `pytest tests/claude_tools/test_pa_analytics.py --collect-only -q | tail -3`
Expected: `11 tests collected`.

- [x] **Step 3: Verify all pass**

Run: `pytest tests/claude_tools/test_pa_analytics.py -v`

- [x] **Step 4: Lint**

Run: `ruff check tests/claude_tools/test_pa_analytics.py --fix`, re-verify if changed.

- [x] **Step 5: Commit**

```bash
git add tests/claude_tools/test_pa_analytics.py
git commit -m "test: extract claude_tools PA/analytics tests"
```

---

## Task 13: Create `test_backtest_pinescript.py`

**Files:**
- Create: `tests/claude_tools/test_backtest_pinescript.py`

- [x] **Step 1: Extract**

```bash
{
cat <<'HEADER'
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.backtest_pinescript

HEADER
sed -n '231,251p;252,304p;2338,2373p' tests/test_claude_tools.py
} > tests/claude_tools/test_backtest_pinescript.py
```

- [x] **Step 2: Verify collection count**

Run: `pytest tests/claude_tools/test_backtest_pinescript.py --collect-only -q | tail -3`
Expected: `8 tests collected`.

- [x] **Step 3: Verify all pass**

Run: `pytest tests/claude_tools/test_backtest_pinescript.py -v`

- [x] **Step 4: Lint**

Run: `ruff check tests/claude_tools/test_backtest_pinescript.py --fix`, re-verify if changed.

- [x] **Step 5: Commit**

```bash
git add tests/claude_tools/test_backtest_pinescript.py
git commit -m "test: extract claude_tools backtest/pinescript tests"
```

---

## Task 14: Create `test_web_scraping.py` (with the quality-classification fix)

**Files:**
- Create: `tests/claude_tools/test_web_scraping.py`

- [x] **Step 1: Extract (includes the `_make_toolkit()` helper at the top of this range)**

```bash
{
cat <<'HEADER'
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.web_scraping

_REALISTIC_MARKDOWN = (
    "# IBKR API Documentation Overview\n\n"
    "The Interactive Brokers Client Portal API provides programmatic access to "
    "account information, market data, and order management functionality for "
    "developers building automated trading applications. This reference covers "
    "authentication flows, the two-call warmup pattern required by several "
    "endpoints, and the rate limits enforced per endpoint group. Developers "
    "should note that market data snapshots may be delayed by fifteen minutes "
    "unless a real-time data subscription is active on the account. Historical "
    "data requests are paginated in batches of up to one thousand data points "
    "and support both daily and intraday bar sizes. Order placement endpoints "
    "require an active brokerage session established through the gateway browser-based "
    "login flow, since the Client Portal Gateway must run on the "
    "same machine as the browser used for authentication. Session cookies "
    "expire after a period of inactivity, so client applications are expected "
    "to call the tickle endpoint at regular intervals to keep the session "
    "alive. This documentation also describes the Flex Web Service, a separate "
    "reporting mechanism that provides back-office trade data with a one-day "
    "settlement delay, in contrast to the near-real-time data available "
    "through the standard Client Portal endpoints described above in detail. "
    "Readers who need a deeper technical walkthrough should consult the full "
    "endpoint reference table later in this guide, which lists every supported "
    "operation alongside its required parameters and expected response shape."
)

HEADER
sed -n '1222,1627p' tests/test_claude_tools.py
} > tests/claude_tools/test_web_scraping.py
```

- [x] **Step 2: Verify `_REALISTIC_MARKDOWN` is actually >= 200 words (the "ok"-quality threshold)**

Run:
```bash
python3 -c "
from tests.claude_tools.test_web_scraping import _REALISTIC_MARKDOWN
print(len(_REALISTIC_MARKDOWN.split()))
"
```
Expected: a number >= 200 (223 expected). If under 200, the content will be
classified "ambiguous" and still trigger a real (unmocked) `judge_completeness_llm`
call to the Anthropic API — the exact bug being fixed. Do not proceed if under 200.

- [x] **Step 3: Fix `test_firecrawl_search_returns_formatted_results` to use realistic content**

Find in the new file:
```python
def test_firecrawl_search_returns_formatted_results(mock_fc_cls):
    toolkit = _make_toolkit()
    mock_fc = MagicMock()
    mock_fc.search.return_value = [
        {"url": "https://example.com", "title": "Example", "markdown": "# Hello"}
    ]
    mock_fc_cls.return_value = mock_fc

    result, fig = toolkit.execute("firecrawl_search", {"query": "IBKR API", "limit": 3})
    assert "## Search results for: IBKR API" in result
    assert fig is None
    mock_fc.search.assert_called_once_with("IBKR API", limit=3)
```
Replace the `mock_fc.search.return_value` line with:
```python
    mock_fc.search.return_value = [
        {"url": "https://example.com", "title": "Example", "markdown": _REALISTIC_MARKDOWN}
    ]
```

- [x] **Step 4: Fix `test_firecrawl_crawl_saves_pages_to_drive` the same way**

Find:
```python
    mock_fc.crawl.return_value = [
        {"url": "https://example.com/page", "markdown": "# Page"}
    ]
```
Replace with:
```python
    mock_fc.crawl.return_value = [
        {"url": "https://example.com/page", "markdown": _REALISTIC_MARKDOWN}
    ]
```

- [x] **Step 5: Verify collection count**

Run: `pytest tests/claude_tools/test_web_scraping.py --collect-only -q | tail -3`
Expected: `22 tests collected`.

- [x] **Step 6: Verify all pass and confirm both timing fixes worked**

Run: `pytest tests/claude_tools/test_web_scraping.py -v --durations=5`
Expected: all pass; neither `test_firecrawl_search_returns_formatted_results`
nor `test_firecrawl_crawl_saves_pages_to_drive` appears among the slowest
durations (both should be under 0.1s, down from 3.91s/2.05s).

- [x] **Step 7: Confirm the fix didn't just move the network call somewhere else**

Run: `pytest tests/claude_tools/test_web_scraping.py -k "returns_formatted_results or saves_pages_to_drive" -v -p no:cacheprovider`
Expected: both pass with no `SocketBlockedError` — if either raises
`SocketBlockedError`, the markdown is still landing in "fallback" or
"ambiguous" quality; re-check the word count (Step 2) and re-verify no
`_PAYWALL_MARKERS` phrase (`subscribe to continue`, `sign in to continue
reading`, `already a subscriber`, `unlock this article`, `create a free
account to continue`, `this content is reserved for subscribers`) appears in
`_REALISTIC_MARKDOWN`.

- [x] **Step 8: Lint**

Run: `ruff check tests/claude_tools/test_web_scraping.py --fix`, re-verify Step 6 if changed.

- [x] **Step 9: Commit**

```bash
git add tests/claude_tools/test_web_scraping.py
git commit -m "$(cat <<'EOF'
test: extract claude_tools web-scraping tests, fix accidental live network calls

Two tests' mocked markdown was short enough to fall under assess_quality's
40-word floor, silently falling through to a real Crawl4AI fetch of
https://example.com. Replaced with realistic >=200-word content that lands
in the "ok" quality bucket the tests actually intend to exercise.
EOF
)"
```

---

## Task 15: Create `test_errors.py` (parametrized, with 2 new branch-coverage cases)

**Files:**
- Create: `tests/claude_tools/test_errors.py`

This file is hand-written, not extracted — the 11 original `test_safe_error_*`
functions collapse into one parametrized test, plus 2 new cases for
`StoreError` and `HumanAuthError`, which are real branches in `_safe_error`
with zero prior test coverage (discovered while transcribing this table).

- [x] **Step 1: Write the file**

```python
import pytest

from ibkr_core_mcp.claude_tools import _safe_error
from ibkr_core_mcp.exceptions import (
    BacktestError,
    BacktestRuntimeError,
    BacktestSyntaxError,
    CacheError,
    ConfigError,
    FlexQueryError,
    HumanAuthError,
    IBKRAPIError,
    IBKRAuthError,
    IBKRRateLimitError,
    StoreError,
)

pytestmark = pytest.mark.errors


@pytest.mark.parametrize(
    "tool,exc,expected_substrs",
    [
        pytest.param("some_tool", IBKRAuthError("session expired"), ("authenticated",), id="ibkr_auth"),
        pytest.param("some_tool", IBKRRateLimitError("429"), ("rate limit",), id="rate_limit"),
        pytest.param("some_tool", IBKRAPIError("error", status_code=500), ("500",), id="api_error"),
        pytest.param("some_tool", CacheError("drive down"), ("drive", "cache"), id="cache"),
        pytest.param("run_backtest", BacktestSyntaxError("bad indent"), ("syntax",), id="backtest_syntax"),
        pytest.param("run_backtest", BacktestRuntimeError("ZeroDivision"), ("runtime",), id="backtest_runtime"),
        pytest.param("run_backtest", BacktestError("failed"), ("backtest",), id="backtest_generic"),
        pytest.param("sync_flex_trades", FlexQueryError("timeout"), ("flex",), id="flex_query"),
        pytest.param("some_tool", ConfigError("missing key"), ("configuration",), id="config"),
        pytest.param("some_tool", KeyError("symbol"), ("missing", "field"), id="key_error"),
        pytest.param("some_tool", RuntimeError("something odd"), ("unexpected",), id="unexpected"),
        pytest.param("some_tool", StoreError("disk full"), ("store",), id="store_error"),
        pytest.param("place_order", HumanAuthError("Touch ID cancelled"), ("authentication",), id="human_auth"),
    ],
)
def test_safe_error_mapping(tool, exc, expected_substrs):
    msg = _safe_error(tool, exc)
    assert any(substr in msg.lower() for substr in expected_substrs), (
        f"expected one of {expected_substrs!r} in {msg.lower()!r}"
    )
```

- [x] **Step 2: Verify collection count**

Run: `pytest tests/claude_tools/test_errors.py --collect-only -q | tail -3`
Expected: `13 tests collected` (1 parametrized function × 13 cases).

- [x] **Step 3: Verify all pass**

Run: `pytest tests/claude_tools/test_errors.py -v`
Expected: all 13 cases pass, including the 2 new ones (`store_error`,
`human_auth`) that had zero prior coverage.

- [x] **Step 4: Lint**

Run: `ruff check tests/claude_tools/test_errors.py --fix`, re-verify Step 3 if changed.

- [x] **Step 5: Commit**

```bash
git add tests/claude_tools/test_errors.py
git commit -m "$(cat <<'EOF'
test: consolidate _safe_error tests into one parametrized table

Collapses 11 near-identical functions into a single table test and adds
2 new cases (StoreError, HumanAuthError) that were real _safe_error
branches with zero prior test coverage.
EOF
)"
```

---

## Task 16: Create `TEST_INDEX.md`

**Files:**
- Create: `tests/claude_tools/TEST_INDEX.md`

- [x] **Step 1: Write the file**

```markdown
# claude_tools Test Index

Domain-organized tests for `ibkr_core_mcp/claude_tools.py`'s 42 tools. See
`docs/2026-07-08-claude-tools-test-reorg-design.md` for the full rationale.

## Layers

- **Layer 1 — schema/description honesty:** `test_tool_descriptions.py`.
  Verifies `TOOL_DEFINITIONS` shape, exact tool count, and that no tool
  description implies execution capability (`ClaudeToolkit` ships zero
  order-write tools by design).
- **Layer 2 — handler unit tests:** the 9 domain files below. Fully mocked
  (`toolkit` fixture from `conftest.py`), no real network or gateway.
- **Layer 3 — live/integration:** intentionally **not** part of this
  directory. Lives in `tests/test_client_live.py`, `tests/test_alerts_live.py`,
  `tests/test_web_scraper_live.py`, `tests/test_web_scraper_drive_live.py`,
  `tests/test_crawl4ai_live.py` — all marked `integration`, requiring a live
  IBKR gateway and/or real credentials.

## Domain files

| File | Tools / helpers covered | Marker | Test count |
| --- | --- | --- | --- |
| `test_tool_descriptions.py` | `TOOL_DEFINITIONS` schema shape, tool count, execution-verb scan | (none — spans all tools) | 6 |
| `test_market_data.py` | check_cache, list_cache, delete_cache, fetch_market_data, search_contract, get_futures, get_market_snapshot (+ `_resolve_snapshot_conid`), get_contract_info, get_option_chain, run_scanner, get_trading_schedule, add_indicators | `market_data` | 38 |
| `test_account.py` | get_account_summary, get_positions, get_ledger, get_pnl, get_allocation, get_watchlists, get_notifications | `account` | 20 |
| `test_trades.py` | get_trades, `_parse_live_trades` | `trades` | 10 |
| `test_orders.py` | get_live_orders, diagnose_orders, preview_order, get_order_status | `orders` | 16 |
| `test_flex.py` | sync_flex_trades, sync_flex_archive, import_flex_file, check_flex_coverage, verify_flex_import, `_format_coverage`, `FlexQueryClient.extract_execution_ids` | `flex` | 22 |
| `test_alerts.py` | get_alerts, create_price_alert, delete_alert, activate_alert, modify_price_alert | `alerts` | 15 |
| `test_pa_analytics.py` | get_analytics, get_pa_periods, get_pa_performance, get_pa_transactions | `pa_analytics` | 11 |
| `test_backtest_pinescript.py` | run_backtest, generate_pinescript | `backtest_pinescript` | 8 |
| `test_web_scraping.py` | firecrawl_search, firecrawl_crawl, `_scrape_with_fallback`, `_validate_public_url` | `web_scraping` | 22 |
| `test_errors.py` | `_safe_error` (parametrized, 13 cases) | `errors` | 13 |

## Running targeted subsets

```bash
pytest tests/claude_tools/                            # all claude_tools unit tests
pytest tests/claude_tools/ -m "not integration"        # same, explicit
pytest tests/claude_tools/test_flex.py                 # one domain file
pytest -m orders                                       # one domain, repo-wide
pytest tests/claude_tools/test_tool_descriptions.py    # schema/description honesty only
```

## Known gaps / follow-ups

- **Description-vs-handler behavioral matching** (e.g., verifying a
  description's claim like "falls back to X" against the handler's actual
  code path) is not implemented in `test_tool_descriptions.py`. Deferred —
  needs a clearer mechanism before it's worth the brittleness risk.
- **Handler-side testability gap:** `claude_tools.py:1128` and `:2272`, and
  `client.py:168`, `:755`, `:774`, `:825` all hardcode `time.sleep(...)`
  inline rather than accepting an injectable sleep function. The *tests* are
  fixed (see this directory's `test_market_data.py` and the repo-wide
  `_no_real_io` guardrail in the root `tests/conftest.py`), but the
  production retry logic itself isn't yet configurable/injectable. A future
  small refactor — e.g. a shared retry helper, or a `sleep_fn` parameter
  defaulting to `time.sleep` — would remove the need for the guardrail
  fixture entirely. Not implemented here; this reorg stayed test-only.
```

- [x] **Step 2: Commit**

```bash
git add tests/claude_tools/TEST_INDEX.md
git commit -m "docs: add tests/claude_tools/TEST_INDEX.md"
```

---

## Task 17: Update CLAUDE.md with targeted test commands

**Files:**
- Modify: `CLAUDE.md`

- [x] **Step 1: Find the "Running Tests" section**

Run: `grep -n "## Running Tests" -A 15 CLAUDE.md`
Expected: the existing section with `pytest -m "not integration"`,
`pytest`, and `pytest tests/test_indicators.py -v` examples.

- [x] **Step 2: Add targeted claude_tools commands**

Find:
```
# Specific module
pytest tests/test_indicators.py -v
```
Replace with:
```
# Specific module
pytest tests/test_indicators.py -v

# Targeted claude_tools subsets (see tests/claude_tools/TEST_INDEX.md)
pytest tests/claude_tools/                            # all claude_tools unit tests
pytest tests/claude_tools/ -m "not integration"        # same, explicit
pytest tests/claude_tools/test_flex.py                 # one domain file
pytest -m orders                                       # one domain, repo-wide
pytest tests/claude_tools/test_tool_descriptions.py    # schema/description honesty only
```

- [x] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add targeted claude_tools test commands to CLAUDE.md"
```

---

## Task 18: Fix `test_client.py`'s 6 `get_live_orders` tests (unconditional sleep)

**Files:**
- Modify: `tests/test_client.py`

`client.py:755`'s `get_live_orders()` does an **unconditional** `time.sleep(1)`
between its two-call warmup, regardless of mock content. The `_no_real_io`
root fixture from Task 3 already neutralizes this, so these 6 tests are
already fast — but add explicit patches at the call sites for the same
readability reason as Task 6, and because `test_get_live_orders_initializes_accounts_first`
doesn't use the shared helper so needs its own patch.

- [x] **Step 1: Add the `contextlib` import**

Find in `tests/test_client.py`:
```python
from unittest.mock import MagicMock, call, patch
from unittest.mock import patch as _patch
```
Replace with:
```python
from contextlib import contextmanager
from unittest.mock import MagicMock, call, patch
from unittest.mock import patch as _patch
```

- [x] **Step 2: Fix the shared `_mock_orders_response` helper (fixes 5 of the 6 tests with one change)**

Find:
```python
def _mock_orders_response(client, orders):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"orders": orders}
    return patch.object(client._session, "get", return_value=mock_resp)
```
Replace with:
```python
@contextmanager
def _mock_orders_response(client, orders):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"orders": orders}
    with patch.object(client._session, "get", return_value=mock_resp), patch("time.sleep"):
        yield
```
No changes needed to the 5 tests that use this helper
(`test_get_live_orders_excludes_filled`, `test_get_live_orders_excludes_cancelled`,
`test_get_live_orders_includes_all_working_statuses`,
`test_get_live_orders_empty_when_all_filled`,
`test_get_live_orders_handles_missing_status`) — the `with _mock_orders_response(...):`
call sites are unchanged.

- [x] **Step 3: Fix the 6th test, which doesn't use the shared helper**

Find:
```python
def test_get_live_orders_initializes_accounts_first(client):
    client._accounts_initialized = False
    with patch.object(client._session, "get") as mock_get:
        mock_get.return_value = _make_ok_response({"orders": []})
        client.get_live_orders()
    first_call_url = mock_get.call_args_list[0][0][0]
    assert first_call_url == f"{client._base}/iserver/accounts"
    assert client._accounts_initialized is True
```
Replace with:
```python
def test_get_live_orders_initializes_accounts_first(client):
    client._accounts_initialized = False
    with patch.object(client._session, "get") as mock_get, patch("time.sleep"):
        mock_get.return_value = _make_ok_response({"orders": []})
        client.get_live_orders()
    first_call_url = mock_get.call_args_list[0][0][0]
    assert first_call_url == f"{client._base}/iserver/accounts"
    assert client._accounts_initialized is True
```

- [x] **Step 4: Verify all 6 pass and are fast**

Run: `pytest tests/test_client.py -k get_live_orders -v --durations=10`
Expected: all 6 pass; none appear among durations over 0.1s (down from ~1.01s each).

- [x] **Step 5: Verify the full file still passes**

Run: `pytest tests/test_client.py -q`
Expected: same pass count as before this change (check against Task 1's
knowledge that `test_client.py` contributes to the 669 non-integration total
— no count should change, only timing).

- [x] **Step 6: Lint**

Run: `ruff check tests/test_client.py --fix`, re-verify Step 5 if changed.

- [x] **Step 7: Commit**

```bash
git add tests/test_client.py
git commit -m "$(cat <<'EOF'
test: fix unmocked time.sleep in test_client.py's get_live_orders tests

get_live_orders() does an unconditional time.sleep(1) between its two-call
warmup regardless of mock content, so all 6 tests paid ~1.01s of real
wall-clock time each (6.06s total, ~24% of the non-integration suite's
runtime) despite being unit tests. Same root-cause bug as the claude_tools
findings, different file.
EOF
)"
```

---

## Task 19: Final verification, delete the old file, final commit

**Files:**
- Delete: `tests/test_claude_tools.py`

- [x] **Step 1: Diff test names between old and new (excluding the intentionally-consolidated safe_error tests)**

Run:
```bash
pytest tests/claude_tools/ --collect-only -q | grep "::" | sed 's/.*:://' | sed 's/\[.*\]//' | sort -u > /tmp/claude_tools_after.txt
grep -v safe_error /tmp/claude_tools_baseline.txt > /tmp/claude_tools_baseline_no_safe_error.txt
comm -23 /tmp/claude_tools_baseline_no_safe_error.txt /tmp/claude_tools_after.txt
```
Expected: **empty output**. Any line printed is a test name that existed
before and is missing now — investigate and restore it before continuing.

- [x] **Step 2: Confirm the new package's total test count**

Run: `pytest tests/claude_tools/ --collect-only -q | tail -3`
Expected: `181 tests collected`
(6 + 38 + 20 + 10 + 16 + 22 + 15 + 11 + 8 + 22 + 13 = 181).
This is +4 vs. the original 177: `test_tool_descriptions.py` goes from 4
tests (3 verbatim + the old "at least 19" check) to 6 (same 3 verbatim +
3 new: exact-count, required-in-properties, no-execution-verb) — net +2.
`test_errors.py` goes from 11 original functions to 13 parametrized cases —
net +2. If your total differs, re-add the per-file expected counts from
each task's Step 2/3 and find which file is off.

- [x] **Step 3: Full claude_tools directory run**

Run: `pytest tests/claude_tools/ -v 2>&1 | tail -20`
Expected: all 187 pass, 0 failures, 0 errors.

- [x] **Step 4: Delete the old file**

Run: `rm tests/test_claude_tools.py`

- [x] **Step 5: Full repo non-integration run — compare against Task 1's baseline**

Run: `pytest -m "not integration" -q 2>&1 | tail -5`
Expected: pass count changes from 669 to roughly 669 − 177 + 181 = 673 (or
whatever your Step 2 total was), same 84 deselected, and runtime drops from
~24-25s to roughly ~9s (removing the ~15.74s of fixed dead weight — 9.68s
claude_tools + 6.06s test_client.py). If runtime didn't drop, check that
Task 3's `_no_real_io` fixture and Task 6/14/18's explicit patches actually
landed (re-run with `--durations=10` to see what's still slow).

- [x] **Step 6: Full repo mypy/ruff sanity check (nothing left broken)**

Run: `ruff check . && mypy ibkr_core_mcp/`
Expected: no new errors introduced by this reorg (pre-existing errors, if
any, are not this plan's concern).

- [x] **Step 7: Final commit**

```bash
git add -A
git commit -m "$(cat <<'EOF'
test: remove tests/test_claude_tools.py, superseded by tests/claude_tools/

All 177 original tests (plus 2 new StoreError/HumanAuthError safe_error
cases and 2 new Layer 1 schema tests) now live in tests/claude_tools/,
organized by domain with markers and a shared toolkit fixture. Verified
via name-diff against the pre-migration baseline (docs/2026-07-08-claude-tools-test-reorg-design.md
has full rationale). Non-integration suite runtime drops from ~24.76s to
~9s after this and the paired test_client.py fix (both fixed the same
unmocked time.sleep/network-call bug class).
EOF
)"
```

- [x] **Step 8: Confirm clean git state**

Run: `git status`
Expected: clean working tree, all changes committed across Tasks 2-19.

---

## Self-Review Notes (for whoever executes this plan)

- **Spec coverage:** every section of `docs/2026-07-08-claude-tools-test-reorg-design.md`
  maps to a task: directory layout → Tasks 4-15; markers → Task 2; fixtures →
  Tasks 3-4; `test_tool_descriptions.py` → Task 5; `TEST_INDEX.md` → Task 16;
  CLAUDE.md → Task 17; the 3 slow-test fixes → Tasks 6 and 14; `_safe_error`
  parametrization → Task 15; `test_client.py` fix → Task 18; root guardrail →
  Task 3; verification → Task 19.
- **Boundary risk is real and acknowledged up front** (see "How the bulk
  moves work") rather than pretending every one of the ~45 `sed` ranges was
  independently hand-verified — it wasn't, at this level of effort. The
  `--collect-only` count check in every task's Step 2/3 is the actual safety
  net, not the ranges themselves.
- **Type/name consistency check:** `toolkit` fixture name matches across
  Task 4's `conftest.py` and every domain file; `_no_real_io` fixture name is
  consistent between Task 3's design and its usage description in Task 6/14's
  explanatory text; `_REALISTIC_MARKDOWN` name is consistent within Task 14.
