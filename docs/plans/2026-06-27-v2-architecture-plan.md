# v2.0 Architecture Plan — ibkr_core_mcp

**Created:** 2026-06-27  
**Status:** Draft — post v1.0 work  
**Prerequisite:** v1.0 tagged and claudia verified stable on it

---

## Context and motivation

v1.0 ships with `claude_tools.py` as a ~2,000-line god class containing four distinct responsibilities:
- Tool DEFINITIONS (42 JSON schemas)
- Tool HANDLERS (42 implementation methods)  
- Shared utilities (`_safe_error`, `_first_account_id`, `_all_account_ids`, SSRF guard)
- Dispatch (`execute()` router)

This is a developer experience problem, not a runtime performance problem. The split is purely internal — `ClaudeToolkit`'s public API (`__init__`, `.tools`, `.execute()`) is unchanged in v2.0. claudia and the dashboard call the same interface.

See also: `2026-06-27-architecture-notes.md` for the full design decision and the unresolved cross-domain call pattern question.

---

## Design principle: Stripe resource pattern

```
ibkr_core_mcp/
├── claude_tools.py          ← ClaudeToolkit facade (public API, unchanged)
└── tools/
    ├── __init__.py
    ├── _base.py             ← shared: _safe_error, _first_account_id, _all_account_ids
    ├── market_data.py       ← DEFINITIONS + handlers
    ├── portfolio.py
    ├── orders.py
    ├── trades.py
    ├── instruments.py
    ├── analytics.py
    └── web.py
```

`ClaudeToolkit` becomes a thin aggregator:

```python
from ibkr_core_mcp.tools.market_data import MARKET_DATA_TOOLS, MarketDataHandlers
from ibkr_core_mcp.tools.portfolio import PORTFOLIO_TOOLS, PortfolioHandlers
# ...

TOOL_DEFINITIONS = [*MARKET_DATA_TOOLS, *PORTFOLIO_TOOLS, ...]

class ClaudeToolkit:
    def __init__(self, client, cache, store, config):
        self._market    = MarketDataHandlers(client, cache, config)
        self._portfolio = PortfolioHandlers(client, store, config)
        self._orders    = OrdersHandlers(client, store, config)
        self._trades    = TradesHandlers(client, store, cache, config)
        self._instruments = InstrumentsHandlers(client, config)
        self._analytics = AnalyticsHandlers(cache, store, config)
        self._web       = WebHandlers(cache, config)
        self.tools = TOOL_DEFINITIONS

    def execute(self, name: str, inputs: dict[str, Any]) -> tuple[str, None]:
        # dispatch dict assembled from all domain handlers
        ...
```

---

## Domain split — tool groupings

| Domain file | Tools | Dependencies |
|---|---|---|
| `market_data.py` | `fetch_market_data`, `check_cache`, `list_cache`, `delete_cache`, `get_market_snapshot`, `get_futures` | client, cache |
| `portfolio.py` | `get_account_summary`, `get_positions`, `get_ledger`, `get_allocation`, `get_pnl`, `get_pa_periods`, `get_pa_performance`, `get_pa_transactions` | client |
| `orders.py` | `get_live_orders`, `diagnose_orders`, `preview_order`, `get_order_status`, `get_alerts`, `create_price_alert`, `modify_price_alert`, `delete_alert`, `activate_alert` | client, store |
| `trades.py` | `get_trades`, `sync_flex_archive`, `import_flex_file`, `check_flex_coverage`, `verify_flex_import`, `sync_flex_trades` | client, store, cache |
| `instruments.py` | `get_contract_info`, `get_option_chain`, `search_contract`, `get_trading_schedule`, `run_scanner`, `get_watchlists`, `get_notifications` | client |
| `analytics.py` | `add_indicators`, `run_backtest`, `generate_pinescript`, `get_analytics` | cache, store |
| `web.py` | `firecrawl_search`, `firecrawl_crawl` | cache (for WebDocsStore) |

---

## Unresolved design question (must decide before coding)

**Cross-domain handler calls.** Some handlers call other handlers.  
Example: `_run_backtest` in analytics may call `_fetch_market_data` from market_data.

**Option A — Composition (recommended):**  
Pass the dependent handler at construction time.
```python
class AnalyticsHandlers:
    def __init__(self, cache, store, config, market: MarketDataHandlers):
        self._market = market
    
    def _run_backtest(self, inputs):
        df = self._market.fetch_market_data(inputs)  # clean cross-domain call
        ...
```

**Option B — Route through aggregator:**  
`AnalyticsHandlers` holds a back-reference to `ClaudeToolkit` and calls `self._toolkit.execute(...)`. Creates circular references and makes testing harder. Not recommended.

**Pre-conditions before starting the refactor:**
1. `grep -n "self\._[a-z]" ibkr_core_mcp/claude_tools.py` — list all internal handler-to-handler calls
2. Draw the actual dependency graph (which handlers call which)
3. Decide Option A or B with justification
4. Only then begin moving files

---

## What changes in v2.0 for consumers

**Nothing.** claudia, the dashboard, and any other consumer continue to use:
```python
toolkit = ClaudeToolkit(client, cache, store, config)
toolkit.tools        # same list of dicts
toolkit.execute(name, inputs)  # same (str, None) return
```

The split is 100% internal. The compatibility test: run claudia's test suite unchanged after the refactor. If it passes, the refactor is safe.

---

## What changes for contributors

- **Adding a new tool:** open the relevant domain file, add DEFINITION + handler in one place. No scrolling through 2,000 lines.
- **Testing:** each domain handler can be instantiated with only its required dependencies. `MarketDataHandlers(client, cache, config)` — no store, no MCP wiring.
- **Parallel development:** two features in different domains have zero merge conflicts.

---

## Suggested v2.0 sequencing

v2.0 should be triggered by the first new tool domain addition, not as a standalone refactor sprint. The value of the split compounds — every new tool added to the new structure costs less than it would cost today.

**Candidate triggers:**
- Options analytics domain (options pricing, Greeks, IV surface)
- News / sentiment domain (earnings, news feeds via Firecrawl)
- Multi-account / advisor domain (DMA, account groups)

**Recommended v2.0 PR structure:**
1. PR 1: `tools/_base.py` — extract shared helpers (small, low risk, no behavior change)
2. PR 2: Split one domain (e.g., `tools/analytics.py`) — proves the pattern works end-to-end before touching more
3. PR 3–N: Remaining domains one at a time, each with full tests
4. Final PR: Add the new feature domain that triggered the refactor

---

## v2.0 additional scope (beyond architecture)

These were identified but deferred from v1.0:

| Item | Description |
|---|---|
| `execute()` figure return | Implement actual plotly figures for backtest/analytics tools (currently always `None`) |
| Async client | `IBKRClient` is fully synchronous — blocks event loop in MCP server for every IBKR call. An async variant (`AsyncIBKRClient`) using `httpx` would unblock concurrent tool calls |
| Connection pooling | `requests.Session` reuse across calls — currently a new connection per request path |
| Multi-account support | `_first_account_id()` assumes one account. `_all_account_ids()` exists but most handlers don't use it |
| Options chain tools | Greeks, IV surface, expiration filtering — natural next domain after v1.0 |

---

## Notes from conversation (2026-06-27)

Key decisions reached in design discussion:

- **The god class is a cognitive problem, not a runtime problem.** Dispatch is O(1), init happens once, IBKR network latency dominates. The split pays for itself in developer velocity, not execution speed.
- **claudia must not change.** The public API surface (`ClaudeToolkit.__init__`, `.tools`, `.execute()`) is the contract. Internal restructuring is invisible to consumers.
- **Don't rush.** v1.0 ships the tested, documented, type-clean foundation. v2.0 adds structure when the codebase needs it — at the point of the next feature addition.
- **LangChain's one-class-per-tool is overkill** for 42 tools owned by one team. Stripe's resource-per-domain pattern is the right level of granularity.
- **The cross-domain call pattern is the only non-obvious risk.** If two domain modules need each other without a clear ownership rule, the dependency graph becomes harder to read than the original god class. Design it first, code second.
