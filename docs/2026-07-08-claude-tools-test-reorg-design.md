# claude_tools test suite restructure — design

**Date:** 2026-07-08
**Scope:** `tests/test_claude_tools.py`'s domain split (177 collected tests) is
the core of this plan. Repo-wide test count is 753 (669 non-integration + 84
integration). Two small additions extend past that one file, justified by
measured full-suite data below: (1) an equivalent sleep-mock fix for 6 tests
in `test_client.py` that share the exact same root-cause bug, and (2)
promoting the guardrail fixture to the root `tests/conftest.py` so it protects
all 753 tests, not just the claude_tools subset. No other file is
reorganized — see "Why not restructure the whole repo" below.

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

```text
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
| --- | --- | --- |
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

## Why not restructure the whole repo

`test_claude_tools.py` (2373 lines, 177 tests) is a genuine outlier, not a
symptom of a repo-wide problem: the next-largest file is `test_client.py` at
910 lines (2.6× smaller), then a steady drop-off (`test_web_scraper.py` 618,
`test_store.py` 559, `test_flex_query.py` 517, `test_scrape_fallback.py` 514,
`test_streaming.py` 498). No other file mixes 42 unrelated tool domains with
zero grouping the way this one did — splitting the rest into domain-folders
now would solve a problem that doesn't exist yet elsewhere. Revisit only if a
specific file later grows to a comparable size/test-count.

Full-suite timing (`pytest -m "not integration" --durations=25`: 669 tests,
24.76s) confirms this: of the ~15.74s of "fixable dead weight" found across
the whole suite, 9.68s is the 3 claude_tools tests already in scope here, and
5.52s (`test_store.py`'s `mkt` fixture, `scope="module"`, real
`exchange_calendars` computation for 20 exchanges) is legitimate, already
correctly amortized — not a bug, not touched. The remaining 6.06s is a
same-shape bug in a different file, addressed as a small paired fix below
rather than a reorg (see "test_client.py sleep fix").

## test_client.py sleep fix (paired with this plan)

`client.py:755` — `get_live_orders()` does an **unconditional**
`time.sleep(1)` between its documented two-call warmup (`?force=true` then the
real fetch), regardless of whether the mocked response already contains data.
`test_client.py`'s `_mock_orders_response()` helper never patches
`time.sleep`, so all 6 `test_get_live_orders_*` tests pay this for real:
1.01s × 6 = 6.06s, ~24% of the entire non-integration suite's runtime.

Fix (test-only, no reorg — `test_client.py` isn't disorganized, just missing
this one mock): wrap each of the 6 tests' `_mock_orders_response(...)` context
in `patch("time.sleep")`, matching the exact convention `test_rate_limiter.py`
already uses. This is folded into the same implementation pass as the
claude_tools work since it's the same root-cause bug, found by the same
`--durations` sweep — not a separate initiative.

## Fixtures — `tests/claude_tools/conftest.py` and root `tests/conftest.py`

Only the `toolkit` fixture moves to `tests/claude_tools/conftest.py` (currently inline in
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

**New: an autouse guardrail fixture, added directly to the root
`tests/conftest.py`** — added specifically because of the measured findings
above (claude_tools' 3 tests, `test_client.py`'s 6 tests), and promoted repo-
wide immediately rather than staged locally-then-promoted, since the same bug
shape already proved itself in two unrelated files. Makes it structurally
impossible for *any* future test, in any file, to silently reintroduce a
multi-second real sleep or a real network call:

```python
import pytest
from pytest_socket import disable_socket, enable_socket


@pytest.fixture(autouse=True)
def _no_real_io(request, monkeypatch):
    if request.node.get_closest_marker("integration"):
        yield  # live/integration tests intentionally hit real sockets and timing
        return
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    disable_socket()
    yield
    enable_socket()
```

Root-level placement means it must not break the 5 existing live/integration
files (`test_client_live.py`, `test_alerts_live.py`, `test_web_scraper_live.py`,
`test_web_scraper_drive_live.py`, `test_crawl4ai_live.py`) — confirmed all 5
consistently carry the `integration` marker, so the `get_closest_marker` check
above is a reliable gate. **Implementation must verify `pytest-socket`'s
official recommended pattern for per-test enable/disable against its docs
before writing this** (CLAUDE.md's docs-first rule) — the exact
`disable_socket()`/`enable_socket()` pairing shown here is illustrative, not
yet confirmed against the library's current API.

Requires adding `pytest-socket` to the `dev` extra in `pyproject.toml`
alongside the existing `pytest>=8.0`, `pytest-asyncio>=0.23`, `pytest-mock>=3.12`.
Besides this guardrail, `tests/claude_tools/conftest.py` itself only gains the
`toolkit` fixture — nothing else in the current file is shared across enough
tests to justify a new fixture (YAGNI).

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
- `test_client.py`'s 6 `test_get_live_orders_*` tests drop from ~1.01s each to
  near-zero once wrapped in `patch("time.sleep")`.
- Full repo `pytest -m "not integration"` runtime drops from ~24.76s to
  roughly ~9s (removing ~15.74s combined) — spot-checked, not assumed.
- `pytest tests/test_client_live.py tests/test_alerts_live.py --collect-only`
  (or a full `pytest -m integration --collect-only`) still collects the same
  tests after the root conftest change, confirming the `integration`-marker
  gate correctly exempts live tests from the socket/sleep guardrail.

## Out of scope

- Layer 3 (live/integration tests) — stays exactly where it is today; the
  root guardrail fixture explicitly exempts anything marked `integration`.
- Description-vs-handler behavioral matching — deferred, tracked as a known
  gap in `TEST_INDEX.md`.
- Handler-side injectable-sleep refactor in `claude_tools.py` (`:1128`,
  `:2272`) **and** `client.py` (`:755`, plus 3 other `time.sleep(1)` sites at
  `:168`, `:774`, `:825` not yet individually audited for test impact) —
  flagged as a follow-up in `TEST_INDEX.md`'s "Known gaps," not implemented.
  The test-side fix (patching `time.sleep` in the affected tests) ships now;
  making the production retry logic itself injectable/configurable is a
  separate, later change.
- Domain-folder reorganization of any file other than `test_claude_tools.py`
  — no other file shows the size/disorganization signal that justified it
  here (see "Why not restructure the whole repo" above).
- Any other change to `ibkr_core_mcp/claude_tools.py` or `ibkr_core_mcp/client.py`
  themselves — both stay test-only changes; the only "production-adjacent"
  additions are a new dev-only dependency (`pytest-socket`) and mock-content/
  mock-patching changes inside tests.
