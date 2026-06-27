# Publication Readiness Plan — ibkr_core_mcp
**Created:** 2026-06-27  
**Status:** In progress  
**Context:** Three code quality audit passes have resolved 39 findings. What remains is test coverage, one model polish, and a claudia_ui label sync.

---

## What's done (for context)

Across three audit passes (commits 7dd6db3, 2d582ce, 3910bc9):
- 39 findings resolved: dead code removed, docstrings completed, MCP fixed, tool counts corrected, notifications clamp fixed, HMDS references removed, indicators documented, silent swallows logged, auth flow fixed in WebDocsStore, plotly dependency removed, `FirecrawlError`/`WebDocsStoreError` exported, `_safe_error` extended, `_BROWSER_LOADERS` removed, 7 module docstrings added, `store._apply_filters` time_col allowlist added
- **426 unit tests pass** on every commit

---

## Remaining tasks

### Task 1 — Unit tests for untested ClaudeToolkit handlers
**Priority: HIGH**  
**File:** `tests/test_claude_tools.py`  
**Pattern:** All existing handler tests mock `IBKRClient`, `GDriveCache`, `SQLiteStore`. Follow the same pattern.

The following 15 handlers have zero unit test coverage. Add one test per handler minimum — happy path + at least one error path each:

| Handler | IBKR endpoint mocked | Key assertion |
|---|---|---|
| `_diagnose_orders` | `get_live_orders()` | Output contains order count or "no orders" |
| `_get_pa_performance` | `get_pa_performance()` | Returns period metrics string |
| `_get_pa_transactions` | `get_pa_transactions()` | Returns transactions; 400 error triggers get_pa_periods fallback |
| `_get_contract_info` | `get_contract_info()` | Returns contract details string |
| `_get_option_chain` | `get_option_chain()` | Returns strikes/expiries string |
| `_run_scanner` | `run_scanner()` | Returns scan results string |
| `_get_watchlists` | `get_watchlists()` | Returns raw IBKR response (intentional — watchlist format not normalized) |
| `_get_trading_schedule` | `get_trading_schedule()` | Returns schedule string |
| `_get_allocation` | `get_allocation()` | Returns allocation breakdown string |
| `_get_order_status` | `get_order_status()` | Returns status string |
| `_delete_cache` | `cache.delete()` | Confirms deletion message |
| `_modify_price_alert` | `store.modify_alert()` | Returns confirmation; verify alert ID passed correctly |
| `_sync_flex_archive` | `cache.download_account_files()` | Returns count of files synced |
| `_import_flex_file` | `flex_query.import_from_bytes()` (or `store.upsert_trades()`) | Returns trade count |
| `_check_flex_coverage` | `flex_query.check_coverage()` (or `store.get_trades()`) | Returns coverage report string |

**Also add:**
- `_get_pa_transactions`: test the HTTP 400 fallback path specifically (mock `get_pa_transactions` to raise `IBKRAPIError(400, ...)` → verify get_pa_periods is called and periods list appears in output)
- `_get_pa_periods`: test the fallback path (mock `get_pa_periods()` to return `[]` → verify raw endpoint is called and raw response appears)

**Note:** Check the actual handler signatures in `claude_tools.py` before writing tests — some handlers may call `_fetch_market_data` internally (for contract resolution), which has its own mock pattern in the existing tests.

---

### Task 2 — Unit tests for GDriveCache Drive paths
**Priority: HIGH**  
**File:** `tests/test_cache.py`  
**Pattern:** Use `unittest.mock.MagicMock` to mock the Drive service, same as web_scraper tests do in `tests/test_web_scraper.py`.

Add tests for:
- `load()` — happy path: mock Drive `files().list()` returns one file, mock `MediaIoBaseDownload` → returns DataFrame
- `load()` — miss path: `files().list()` returns empty → `CacheMissError` raised
- `load()` — Drive error: `files().list()` raises Exception → `CacheMissError` raised (folder unavailable branch)
- `save()` — new file: `files().list()` returns empty → `files().create()` called
- `save()` — update: `files().list()` returns existing → `files().update()` called
- `save()` — Drive error: `files().create()` raises → `CacheWriteError` raised
- `delete()` — file found: `files().delete()` called for each matching file; manifest entry removed
- `delete()` — file not found: no `files().delete()` call; no error raised

For mocking `MediaIoBaseDownload`, look at how `test_web_scraper.py` mocks Drive download operations — same library.

---

### Task 3 — Pydantic Field descriptions on aliased fields
**Priority: LOW**  
**File:** `ibkr_core_mcp/models.py`  
**Impact:** IDE autocomplete / `model.model_fields` / auto-generated API docs.

Add `description=` to `Field()` calls on aliased fields that would confuse a consumer:

```python
# Position model
conid: int = Field(default=0, alias="conid")  # no alias confusion, ok as is
symbol: str = Field(default="", alias="contractDesc", description="Ticker symbol (IBKR field: contractDesc)")
qty: float = Field(default=0.0, alias="position", description="Position size in shares/contracts (IBKR field: position)")
mkt_price: float = Field(default=0.0, alias="mktPrice", description="Current market price")
mkt_value: float = Field(default=0.0, alias="mktValue", description="Current market value")
unrealized_pnl: float = Field(default=0.0, alias="unrealizedPnl", description="Unrealized P&L")

# Order model — qty, side, status aliases are non-obvious
qty: float = Field(default=0.0, alias="totalSize", description="Total order quantity (IBKR field: totalSize)")
remaining_qty: float = Field(default=0.0, alias="remainingQuantity", description="Unfilled quantity")
side: str = Field(default="", alias="side", description="BUY or SELL")

# Trade model
symbol: str = Field(default="", alias="symbol")
quantity: float = Field(default=0.0, alias="quantity")
price: float = Field(default=0.0, alias="price")
```

Only add `description=` where the alias diverges meaningfully from the field name. Don't add it to trivially named fields.

---

## Claudia compatibility notes — MUST READ before any change to ibkr_core_mcp

**claudia_ui** (`/Users/steph/Claude_Projects/claudia_ui`) imports from ibkr_core_mcp:
- `app.py`: `IBKRClient`, `BrowserCookieAuth`, `Config`, `ClaudeToolkit`, `GDriveCache`, `SQLiteStore`
- `app.py`: `GatewayManager` from `ibkr_core_mcp.gateway`
- `order_flow.py`: `IBKRClient`, `BrowserCookieAuth`, `Config`
- claudia does NOT use indicators, analytics, or pinescript directly — all go through ClaudeToolkit tools

**No breaking changes** were introduced in the three audit passes for claudia. Verified:
- `macd_signal` rename only affects direct indicator callers; claudia uses the `add_indicators` tool
- `plotly` removal: was never used, no claudia code referenced it
- `WebDocsStoreError`/`FirecrawlError` additions: additive, non-breaking
- `store._apply_filters` validation: internal only, all callers use hardcoded column names
- notification clamp 100→10: behavior change at IBKR API boundary, no claudia code assumed 100

**claudia_ui action needed — LOW priority, non-breaking:**  
`claudia/session_reporter.py` `_TOOL_LABELS` dict is missing three tools added in the firecrawl feature pass. These fall back to the raw tool name (harmless), but should be added for completeness:

```python
# Add to _TOOL_LABELS in claudia/session_reporter.py:
"verify_flex_import": "Trades: verify Flex import",
"firecrawl_search": "Web: Firecrawl search",
"firecrawl_crawl": "Web: Firecrawl crawl",
```

---

## What is NOT in scope

- TradingView bridge changes (separate project)
- claudia_ui architecture changes
- New ibkr_core_mcp features
- Performance optimization

---

## Definition of done

- [ ] Task 1: all 15 handlers have at least 1 passing unit test; PA transaction 400 fallback tested
- [ ] Task 2: 8 Drive path tests added to test_cache.py; all pass
- [ ] Task 3: `description=` added to aliased fields in Position, Order, Trade models
- [ ] claudia_ui session_reporter._TOOL_LABELS updated with 3 missing tools
- [ ] `pytest -m "not integration"` passes with no new failures
- [ ] git push to origin/main
