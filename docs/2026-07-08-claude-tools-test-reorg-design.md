# claude_tools test suite restructure — design

**Date:** 2026-07-08
**Scope:** `tests/test_claude_tools.py` only (177 collected tests). Repo-wide test
count is 753; this does not touch any other test file.

## Problem

`tests/test_claude_tools.py` is a single 2373-line, 177-test flat file covering
all 42 tools in `ClaudeToolkit`. There is no grouping, no markers, and no
schema-level guardrail that a tool's advertised description matches what
`ClaudeToolkit` actually ships (e.g. no order-write tool should ever claim
execution capability — see CLAUDE.md's "Claude AI Tool Layer" section).

**Measured, not assumed:** `pytest tests/test_claude_tools.py --durations=15`
shows the file runs in 11.5s, and 86% of that (10s) is 3 tests:
`test_fetch_market_data_empty_data` (4.01s), `test_firecrawl_search_returns_formatted_results`
(3.91s), `test_firecrawl_crawl_saves_pages_to_drive` (2.05s). Root causes:

- `test_fetch_market_data_empty_data` exercises the real `time.sleep(2)` retry
  loop at `claude_tools.py:1128` (IBKR's documented 3-attempt/2s warmup retry),
  unmocked — unlike `tests/test_rate_limiter.py`, which already wraps its retry
  tests in `patch("time.sleep")`.
- The two firecrawl tests mock markdown content (`"# Hello"`, `"# Page"`) short
  enough to fall under `assess_quality`'s ~40-word floor, classifying it
  `"fallback"` quality — which skips past the Firecrawl mock entirely and
  constructs a real `Crawl4AIScraper` that hits `https://example.com` over the
  actual network (`claude_tools.py:2599`). These tests' names claim to test
  formatting/Drive-save, not the network fallback path — the short fixture
  content is accidentally exercising untested-by-name behavior.

This is the dominant lever for "reduce test time at scale," not file layout —
splitting into domain files relocates these costs without removing them; if
future tests add retry/fallback coverage without noticing this gap, wall time
keeps growing for real (sleeps, network flakiness in CI) independent of test
count.

## Directory layout

```
tests/claude_tools/
├── __init__.py                    # empty, matches tests/__init__.py pattern
├── conftest.py                    # `toolkit` fixture only
├── TEST_INDEX.md                  # domain → tools → marker → count map
├── test_tool_descriptions.py      # Layer 1: schema/description honesty
├── test_market_data.py            # Layer 2
├── test_account.py                # Layer 2
├── test_trades.py                 # Layer 2
├── test_orders.py                 # Layer 2
├── test_flex.py                   # Layer 2
├── test_alerts.py                 # Layer 2
├── test_pa_analytics.py           # Layer 2
├── test_backtest_pinescript.py    # Layer 2
├── test_web_scraping.py           # Layer 2
└── test_errors.py                 # Layer 2
```

`tests/test_claude_tools.py` is deleted once the split is verified equivalent.
`test_pa_analytics.py` / `test_backtest_pinescript.py` are named to avoid reader
confusion with the existing `tests/test_analytics.py` / `tests/test_backtest.py`
(different modules — analytics.py / backtest.py — vs. the claude_tools handlers
that wrap them). No test function is renamed; every test keeps its exact name
from today so `git blame` / history stays meaningful and no assertions change.

## Test-to-file mapping

| File | Tools / helpers covered | Approx. count |
|---|---|---|
| `test_tool_descriptions.py` | `TOOL_DEFINITIONS` schema shape, tool count, execution-verb scan (new) | 4 existing + new |
| `test_market_data.py` | check_cache, list_cache, delete_cache, fetch_market_data, search_contract, get_futures, get_market_snapshot (+ `_resolve_snapshot_conid`), get_contract_info, get_option_chain, run_scanner, get_trading_schedule, add_indicators | ~40 |
| `test_account.py` | get_account_summary, get_positions, get_ledger, get_pnl, get_allocation, get_watchlists, get_notifications | ~24 |
| `test_trades.py` | get_trades, `_parse_live_trades` | 9 |
| `test_orders.py` | get_live_orders, diagnose_orders, preview_order, get_order_status | 16 |
| `test_flex.py` | sync_flex_trades, sync_flex_archive, import_flex_file, check_flex_coverage, verify_flex_import, `_format_coverage`, `flex_query.extract_execution_ids` | ~21 |
| `test_alerts.py` | get_alerts, create_price_alert, delete_alert, activate_alert, modify_price_alert | 16 |
| `test_pa_analytics.py` | get_analytics, get_pa_periods, get_pa_performance, get_pa_transactions | 11 |
| `test_backtest_pinescript.py` | run_backtest, generate_pinescript | 8 |
| `test_web_scraping.py` | firecrawl_search, firecrawl_crawl, `_scrape_with_fallback`, `_validate_public_url` | ~25 |
| `test_errors.py` | `_safe_error` | 10 → 1 parametrized |

Total: 177 test *cases* preserved exactly (verified via `pytest --collect-only -q`
before and after the move) — collected *item* count may show 168 once the 10
`test_safe_error_*` functions become 1 parametrized test with 10 cases (see
below); no coverage is lost.

## Fixes applied during the move

Applied while relocating tests (not left for a follow-up), since these tests
are being physically rewritten into new files regardless:

- `test_fetch_market_data_empty_data` → moves into `test_market_data.py`
  wrapped in `with patch("time.sleep"):` (matching `test_rate_limiter.py`'s
  existing convention), removing ~4s of real delay. Also covered for free by
  the new autouse `_no_real_io` fixture, but the explicit patch stays for
  readability/intent at the call site.
- `test_firecrawl_search_returns_formatted_results` and
  `test_firecrawl_crawl_saves_pages_to_drive` → move into `test_web_scraping.py`
  with their mocked markdown lengthened to realistic, unambiguous "ok"-quality
  content (≥40 words, no paywall keywords), so they exercise the happy path
  their names actually claim to test instead of silently falling through to
  the Crawl4AI/network branch. The `_no_real_io` fixture's `disable_socket()`
  also becomes a hard backstop: if quality classification ever regresses again,
  the test now fails fast with a clear "socket blocked" error instead of
  quietly making a real HTTP request.
- `test_safe_error_*` (10 functions) → collapse into one
  `@pytest.mark.parametrize` table `test_safe_error_mapping` in
  `test_errors.py`. Pure input→output mapping, no per-case mock wiring, the
  cleanest parametrize candidate in the file. `preview_order`,
  `get_market_snapshot`, and `verify_flex_import` clusters stay as separate
  named functions — each case wires distinct mock responses and asserts
  different things, so collapsing them would hurt readability more than it
  helps.

## Fixtures — `tests/claude_tools/conftest.py`

Only the `toolkit` fixture moves here (currently inline in
`test_claude_tools.py`):

```python
@pytest.fixture
def toolkit(mock_config):
    from ibkr_core_mcp.claude_tools import ClaudeToolkit
    client = MagicMock()
    cache = MagicMock()
    store = MagicMock()
    return ClaudeToolkit(client, cache, store, mock_config)
```

`mock_config` and `tmp_db` keep living in the root `tests/conftest.py` — pytest
resolves fixtures up the directory chain automatically, so nothing there needs
to change.

**New: an autouse guardrail fixture**, added specifically because of the
measured findings above — makes it structurally impossible for a future test
in this domain to silently reintroduce a multi-second real sleep or a real
network call:

```python
import pytest
from pytest_socket import disable_socket


@pytest.fixture(autouse=True)
def _no_real_io(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    disable_socket()  # any real socket.connect() now raises SocketBlockedError
```

Requires adding `pytest-socket` to the `dev` extra in `pyproject.toml`
alongside the existing `pytest>=8.0`, `pytest-asyncio>=0.23`, `pytest-mock>=3.12`.
No other new fixtures are introduced — nothing else in the current file is
shared across enough tests to justify one (YAGNI).

## Markers

Register in `pyproject.toml` alongside the existing `integration` marker:

```toml
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

Each domain file gets one module-level `pytestmark = pytest.mark.<domain>` —
no per-test decoration. `test_tool_descriptions.py` gets no domain marker (it
spans all tools by definition). This enables `pytest -m flex` repo-wide or
`pytest tests/claude_tools/test_flex.py` file-scoped, without touching any
test body.

## `test_tool_descriptions.py` (Layer 1)

Generalizes today's 4 loose checks and adds two new ones:

1. `test_tools_returns_list_of_dicts` — unchanged
2. `test_all_tools_have_required_fields` — unchanged (every tool has
   name/description/input_schema)
3. `test_execute_unknown_tool_returns_error` — unchanged
4. Tool count == `len(TOOL_DEFINITIONS)` exactly — **tightens** today's loose
   "at least 19" into an exact-match assertion, so the test fails the moment a
   tool is added or removed without a matching update here.
5. **New:** every `required` entry in each tool's `input_schema` actually
   appears as a key in that schema's `properties`.
6. **New:** no tool `description` contains an execution-capability verb
   (`place`, `buy`, `sell`, `submit`, `cancel order`, `modify order`) — a
   regression guard for the CLAUDE.md invariant that `ClaudeToolkit` exposes
   zero order-write tools.

**Explicitly out of scope for this file:** description-vs-handler behavioral
matching (e.g., verifying a description's claim like "falls back to X" against
the handler's actual code path). Deferred as a documented gap in
`TEST_INDEX.md` rather than attempted now — flagged by the user as something
that needs a clearer mechanism before it's worth the brittleness risk.

## `TEST_INDEX.md`

A short reference page at `tests/claude_tools/TEST_INDEX.md`:

- The table from "Test-to-file mapping" above (file → tools → marker → count)
- A "Layers" section: Layer 1 = `test_tool_descriptions.py`, Layer 2 = the 9
  domain files (all mocked, no network), Layer 3 = live/integration — explicitly
  **not** part of this directory; pointer to the existing
  `tests/test_client_live.py`, `tests/test_alerts_live.py`,
  `tests/test_web_scraper_live.py`, `tests/test_web_scraper_drive_live.py`,
  `tests/test_crawl4ai_live.py` (unchanged, out of scope here)
- A "Known gaps / follow-ups" section noting:
  - The deferred description-vs-handler behavioral check (see above)
  - **Handler-side testability gap (not fixed here):** `claude_tools.py:1128`
    and `:2272` hardcode `time.sleep(...)` inline rather than accepting an
    injectable sleep function, unlike `rate_limiter.py`'s `with_retry`, which
    at least centralizes its retry logic in one place even though it also
    sleeps directly. A future small refactor — e.g. both call sites taking a
    `sleep_fn: Callable[[float], None] = time.sleep` parameter, or routing
    through a shared retry helper — would let tests mock retries without
    reaching into `time.sleep` globally. Flagged, not implemented: this reorg
    stays test-only.

## CLAUDE.md update

Extend the existing "Running Tests" section with targeted commands:

```bash
pytest tests/claude_tools/                            # all claude_tools unit tests
pytest tests/claude_tools/ -m "not integration"        # same, explicit
pytest tests/claude_tools/test_flex.py                 # one domain file
pytest -m orders                                       # one domain, repo-wide
pytest tests/claude_tools/test_tool_descriptions.py    # schema/description honesty only
```

## Verification

- `pytest --collect-only -q` for `tests/claude_tools/` accounts for all 177
  original test cases (10 of them now as 1 parametrized function with 10
  params, per the `_safe_error` consolidation above), plus whatever new tests
  `test_tool_descriptions.py` adds.
- Full repo `pytest -m "not integration"` passes with the same pass/fail
  outcome as before the move — same assertions, same behavior, only the 3
  slow tests' *mock setup* changes (not their intent).
- `tests/test_claude_tools.py` is removed only after the above two checks
  pass.
- File runtime drops from ~11.5s to roughly ~1.5s (removing the ~10s of real
  sleep/network) — spot-checked via `--durations=15` after the move, not just
  assumed.

## Out of scope

- Layer 3 (live/integration tests) — stays exactly where it is today.
- Description-vs-handler behavioral matching — deferred, tracked as a known
  gap in `TEST_INDEX.md`.
- Handler-side injectable-sleep refactor (`claude_tools.py:1128`, `:2272`) —
  flagged as a follow-up in `TEST_INDEX.md`'s "Known gaps," not implemented.
- Any other change to `ibkr_core_mcp/claude_tools.py` itself — this stays a
  test-only reorganization; the only "production-adjacent" additions are a new
  dev-only dependency (`pytest-socket`) and mock-content changes inside tests.
