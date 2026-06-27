# Architecture Notes — claude_tools.py refactor

**Created:** 2026-06-27  
**Status:** Deferred — do at first new-domain addition, not before v1.0

---

## Current state

`ibkr_core_mcp/claude_tools.py` is 2,000+ lines containing four distinct responsibilities:
- Tool DEFINITIONS (42 JSON schemas)
- Tool HANDLERS (42 implementation methods)
- Shared utilities (_safe_error, _first_account_id, _all_account_ids, SSRF guard)
- Dispatch (execute() router)

This is a developer experience problem, not a runtime performance problem. Dispatch is O(1), initialization happens once, IBKR network latency dominates all execution time. The god class does not make the package slower.

---

## Target architecture (when refactoring)

```
ibkr_core_mcp/
├── claude_tools.py          # ClaudeToolkit facade — stays as public API surface
└── tools/
    ├── __init__.py
    ├── _base.py             # _safe_error, _first_account_id, _all_account_ids
    ├── market_data.py       # DEFINITIONS + handlers: fetch, cache, snapshot, futures
    ├── portfolio.py         # DEFINITIONS + handlers: positions, summary, ledger, PA
    ├── orders.py            # DEFINITIONS + handlers: live orders, alerts, preview
    ├── trades.py            # DEFINITIONS + handlers: trades, flex sync/import
    ├── instruments.py       # DEFINITIONS + handlers: contracts, options, scanner
    ├── analytics.py         # DEFINITIONS + handlers: indicators, backtest, pinescript
    └── web.py               # DEFINITIONS + handlers: firecrawl, SSRF guard
```

`claude_tools.py` becomes a thin aggregator:

```python
from ibkr_core_mcp.tools.market_data import MARKET_DATA_TOOLS, MarketDataHandlers
# ...

TOOL_DEFINITIONS = [*MARKET_DATA_TOOLS, *PORTFOLIO_TOOLS, ...]

class ClaudeToolkit:
    def __init__(self, client, cache, store, config):
        self._market  = MarketDataHandlers(client, cache, config)
        self._portfolio = PortfolioHandlers(client, store, config)
        # ...
        self.tools = TOOL_DEFINITIONS

    def execute(self, name, inputs):
        # dispatch dict assembled from all domain handlers
        ...
```

**claudia_ui does not change** — it still uses `ClaudeToolkit(client, cache, store, config)` and `execute()`. Public API is unchanged.

---

## When to do it

**Do NOT do this before v1.0.** The refactor is ~1 day, touches every test that patches ClaudeToolkit internals, and introduces regression risk without adding user-visible value.

**Right moment:** First time a new tool domain is added (options analytics, news tools, etc.) — refactor in the same PR as the new feature so the split pays for itself immediately.

---

## Fix BEFORE v1.0 (different list — these are bugs, not architecture)

1. `execute()` always returns `(text, None)` — the figure promise is a lie. Fix: change signature to `tuple[str, None]` or implement figure return for backtest/analytics tools.
2. `full_report()` hardcodes `periods=252` with no override — wrong numbers for intraday. Fix: add `periods: int = 252` kwarg.
3. `human_auth.py` crashes on non-macOS at import time (not call site). Fix: platform guard that raises `HumanAuthError` clearly on Linux/Windows.
4. mypy has not been run since recent additions — run and fix before tagging v1.0.
5. No CHANGELOG — add before publish (consumers need upgrade guidance).
6. Version in `__init__.py` and `pyproject.toml` duplicated — use `importlib.metadata.version()`.
