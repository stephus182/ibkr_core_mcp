# claude_tools Test Index

Domain-organized tests for `ibkr_core_mcp/claude_tools.py`'s 44 tools. See
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
  `tests/test_web_scraper_dev_cache_live.py`, `tests/test_crawl4ai_live.py` —
  all marked `integration`, requiring a live IBKR gateway and/or real
  credentials. `test_web_scraper_dev_cache_live.py` specifically covers
  Drive caching when developing ibkr_core_mcp standalone (a local,
  gitignored `.env` with just `FIRECRAWL_API_KEY`, `GDRIVE_WEB_DOCS_FOLDER_ID`,
  and token/credentials paths — no `GOOGLE_DRIVE_FOLDER_ID` needed), as
  distinct from `test_web_scraper_drive_live.py`'s claudia_ui-production-folder path.

## Domain files

| File | Tools / helpers covered | Marker | Test count |
| --- | --- | --- | --- |
| `test_tool_descriptions.py` | `TOOL_DEFINITIONS` schema shape, tool count, execution-verb scan | (none — spans all tools) | 6 |
| `test_market_data.py` | check_cache, list_cache, delete_cache, fetch_market_data, search_contract, get_futures, get_market_snapshot (+ `_resolve_snapshot_conid`), get_contract_info, get_option_chain, run_scanner, get_trading_schedule, add_indicators | `market_data` | 38 |
| `test_account.py` | get_account_summary, get_positions, get_ledger, get_pnl, get_allocation, get_watchlists, get_notifications | `account` | 25 |
| `test_trades.py` | get_trades, `_parse_live_trades` | `trades` | 10 |
| `test_orders.py` | get_live_orders, diagnose_orders, preview_order, get_order_status | `orders` | 16 |
| `test_flex.py` | sync_flex_trades, sync_flex_archive, import_flex_file, check_flex_coverage, verify_flex_import, `_format_coverage`, `FlexQueryClient.extract_execution_ids` | `flex` | 22 |
| `test_alerts.py` | get_alerts, create_price_alert, delete_alert, activate_alert, modify_price_alert | `alerts` | 15 |
| `test_pa_analytics.py` | get_analytics, get_pa_periods, get_pa_performance, get_pa_transactions | `pa_analytics` | 12 |
| `test_backtest_pinescript.py` | run_backtest, generate_pinescript | `backtest_pinescript` | 8 |
| `test_web_scraping.py` | firecrawl_search, search_site, crawl_site, fetch_page, `_validate_public_url` | `web_scraping` | 27 |
| `../test_web_tools_live.py` | **LIVE** acceptance for firecrawl_search / search_site / crawl_site / fetch_page. Mandatory before any scraper change is called done — see `docs/web-scraper-reference.md` §10 |
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
- **`_REAL_DNS_EXEMPT_TESTS` in the root `tests/conftest.py`:** tests in
  `test_web_scraping.py` are exempted, by name, from the `_no_real_io`
  guardrail's socket block. Their purpose is exercising the real SSRF/DNS
  validation path (`ClaudeToolkit._validate_public_url` ->
  `local_browser.is_private_host` -> `socket.gethostbyname`) against a real
  public hostname (`example.com`/`wsj.com`) — mocking DNS away would weaken
  coverage of that security-critical logic, so they keep making a real (fast)
  DNS lookup instead.

  The count is deliberately not restated here: it said 14 while the set held 20,
  and a number in prose drifts silently. `tests/test_conftest_hygiene.py` now
  asserts that every name in the set matches a real test — three names for tools
  deleted on 2026-07-30 survived in it until 2026-08-07, granting an exemption
  nothing used. Prune the set in the same commit as any test deletion.

  If a future change makes
  `is_private_host` mockable/injectable, these could move to the fully-mocked
  guardrail instead — not attempted here to avoid weakening the security
  logic under test as part of a test-reorg change.
