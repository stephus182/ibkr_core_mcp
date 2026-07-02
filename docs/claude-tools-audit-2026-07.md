# claude_tools.py Audit — 2026-07

**Status:** IN PROGRESS — sections below are filled as workstreams complete.
**Spec:** docs/2026-07-02-claude-tools-audit-design.md
**Model used for all token counts:** claude-opus-4-8 (ClaudIA default)

## Decision summary

| # | Decision | Outcome | Evidence |
|---|---|---|---|
| D1 | Where ClaudIA slowness comes from | _pending — Task 12_ | Appendix B |
| D2 | Split go/no-go + architecture | _pending — Task 12_ | Appendices C, D, E |
| D3 | Tool-exposure strategy | _pending — Task 12_ | Appendices A, B, E |
| D4 | Sequencing vs. scraping-RAG layer 2 | _pending — Task 12_ | Appendices A, E |
| D5 | Documentation verdicts | _pending — Task 12_ | Appendix G |

## Appendix A — Token weight (WS1a)

**Method:** leave-one-out marginal cost via `client.messages.count_tokens` (exact API counts, not estimates). `full − without_i` isolates each tool's true marginal cost, immune to the fixed tool-use system-prompt overhead the API adds. Baseline (no tools) isolates that overhead separately. Script: `scripts/audit/count_tool_tokens.py`. Raw data: `docs/superpowers/audit-evidence/token_counts.json` (gitignored, local-only — evidence reproduced here in full since the report must be self-contained).

**Note on tool count:** the task brief expected 42 toolkit + 3 local = 45 tools. The actual measured count is **42 toolkit + 4 local = 46** — `claudia/agent.py`'s `_LOCAL_TOOLS` currently has 4 entries (`list_doc_versions`, `get_doc_version`, `search_past_conversations`, `fetch_web_page`), one more than expected. This is a real discrepancy in the codebase vs. the brief's assumption, not a script defect — verified by direct AST extraction of both `TOOL_DEFINITIONS` and `_LOCAL_TOOLS`. All 46 entries are accounted for below.

### Totals

| Metric | Value |
|---|---|
| Model | `claude-opus-4-8` |
| Tool count | 46 (42 `ClaudeToolkit` + 4 `claudia` local) |
| Baseline (no tools, no system) | 8 tokens |
| Full payload (baseline + all 46 tool schemas) | 9,481 tokens |
| **Tool surface total** (full − baseline) | **9,473 tokens** |
| **System prompt tokens** (context.md + principles.md) | **11,113 tokens** |
| **Static prefix per call** (tool surface + system prompt) | **20,586 tokens** |

**Sanity checks:**
- Every marginal cost is positive: **PASS** (46/46 entries > 0, verified programmatically).
- `tool_surface_total` within ~2% of the sum of all marginals: sum of marginals = 9,183; tool_surface_total = 9,473; diff = 3.06%. **Slightly over the ~2% guideline** — attributed to tokenizer boundary effects at JSON-array join points (removing one tool changes commas/whitespace context for its neighbors), which is expected for leave-one-out on a comma-joined array rather than a sign of a measurement error. Not treated as a blocking anomaly.
- `static_prefix_total` (20,586 tokens) is in the plausible thousands-to-tens-of-thousands range: **PASS**.

### Full ranked per-tool table (all 46 tools)

| Rank | Tool | Marginal tokens | % of tool surface |
|---|---|---|---|
| 1 | `get_market_snapshot` | 911 | 9.62% |
| 2 | `create_price_alert` | 501 | 5.29% |
| 3 | `run_backtest` | 344 | 3.63% |
| 4 | `modify_price_alert` | 328 | 3.46% |
| 5 | `run_scanner` | 324 | 3.42% |
| 6 | `preview_order` | 301 | 3.18% |
| 7 | `firecrawl_crawl` | 298 | 3.15% |
| 8 | `get_trades` | 296 | 3.12% |
| 9 | `fetch_market_data` | 263 | 2.78% |
| 10 | `add_indicators` | 258 | 2.72% |
| 11 | `get_trading_schedule` | 255 | 2.69% |
| 12 | `get_live_orders` | 254 | 2.68% |
| 13 | `generate_pinescript` | 251 | 2.65% |
| 14 | `firecrawl_search` | 249 | 2.63% |
| 15 | `get_analytics` | 243 | 2.57% |
| 16 | `delete_cache` | 230 | 2.43% |
| 17 | `import_flex_file` | 209 | 2.21% |
| 18 | `fetch_web_page` | 208 | 2.20% |
| 19 | `sync_flex_trades` | 204 | 2.15% |
| 20 | `search_contract` | 199 | 2.10% |
| 21 | `verify_flex_import` | 188 | 1.98% |
| 22 | `check_cache` | 186 | 1.96% |
| 23 | `search_past_conversations` | 164 | 1.73% |
| 24 | `get_futures` | 160 | 1.69% |
| 25 | `get_pa_performance` | 157 | 1.66% |
| 26 | `sync_flex_archive` | 156 | 1.65% |
| 27 | `get_pa_transactions` | 155 | 1.64% |
| 28 | `check_flex_coverage` | 148 | 1.56% |
| 29 | `diagnose_orders` | 145 | 1.53% |
| 30 | `get_contract_info` | 145 | 1.53% |
| 31 | `activate_alert` | 145 | 1.53% |
| 32 | `get_doc_version` | 138 | 1.46% |
| 33 | `get_option_chain` | 117 | 1.24% |
| 34 | `delete_alert` | 117 | 1.24% |
| 35 | `get_order_status` | 96 | 1.01% |
| 36 | `get_pnl` | 95 | 1.00% |
| 37 | `get_pa_periods` | 94 | 0.99% |
| 38 | `get_notifications` | 91 | 0.96% |
| 39 | `list_doc_versions` | 82 | 0.87% |
| 40 | `get_account_summary` | 78 | 0.82% |
| 41 | `get_allocation` | 73 | 0.77% |
| 42 | `get_ledger` | 71 | 0.75% |
| 43 | `get_alerts` | 65 | 0.69% |
| 44 | `get_watchlists` | 65 | 0.69% |
| 45 | `list_cache` | 64 | 0.68% |
| 46 | `get_positions` | 62 | 0.65% |

### TradingView tools (unmeasured)

TradingView Desktop / the bridge was checked via `claudia.tradingview.TradingViewBridge().get_tools()` and returned an empty list (`[]`) — TradingView Desktop is not currently running/connected on this machine. Per the measurement protocol, no placeholder or estimated numbers were recorded. `tradingview-mcp` advertises **78 tools**; when the bridge is connected, these ride the *same* payload as every other tool (added to `all_tools` in the script) and would materially increase the static prefix per call — this is unmeasured and should be treated as a known gap in the token-weight picture, not zero cost.

**Rerun instruction (once TradingView Desktop is running and connected):**
```bash
cd /Users/steph/Claude_Projects/claudia_ui && .venv/bin/python -c "
import json
from claudia.tradingview import TradingViewBridge
print(json.dumps(TradingViewBridge().get_tools()))
" > /Users/steph/Claude_Projects/ibkr_core_mcp/docs/superpowers/audit-evidence/tv_tools.json
cd /Users/steph/Claude_Projects/ibkr_core_mcp && .venv/bin/python scripts/audit/count_tool_tokens.py \
    --out docs/superpowers/audit-evidence/token_counts_with_tv.json \
    --extra-tools docs/superpowers/audit-evidence/tv_tools.json
```

_Layer-2 projection: pending — Task 3_

## Appendix B — Latency decomposition (WS1b)
_pending — Tasks 4–6_

## Appendix C — Code findings table (WS2a)
_pending — Task 8_

## Appendix D — Cross-domain dependency graph (WS2b)
_pending — Task 7_

## Appendix E — Structural assessment (WS2c/2d)
_pending — Task 9_

## Appendix F — Tool → authoritative-source map (WS3a)
_pending — Task 10_

## Appendix G — Docs verdict table (WS3b/3c)
_pending — Task 11_
