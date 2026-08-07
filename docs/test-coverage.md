# Test Coverage — ibkr_core_mcp

**917 unit tests · 92 integration tests (1,009 total) · ~83% line coverage (non-integration)** — measured 2026-08-07; re-measure with `pytest --collect-only -q`, do not edit this number by hand

> Counts re-measured 2026-07-30 with `pytest --collect-only`. The coverage figure is carried
> over from the run below and was **not** re-measured (`pytest-cov` is not installed in the
> current venv); 7 tests were added since, all to `test_local_browser.py` and
> `test_tool_descriptions.py`, so treat 83% as a floor rather than a current reading.
Run: `pytest -m "not integration"` · Integration only: `pytest -m integration` (requires live gateway)
Counts and coverage below regenerated 2026-07-30 via
`pytest -m "not integration" --cov=ibkr_core_mcp --cov-report=term-missing`; re-run that command
after any significant test or source addition rather than hand-editing these numbers.

Live integration test log: [`docs/audits/live-test-log.md`](audits/live-test-log.md)

---

## 100% Coverage (no gaps)

| Module | Notes |
|---|---|
| `analytics.py` | All metric functions including all zero/empty edge cases |
| `config.py` | Config dataclass and validation |
| `exceptions.py` | Exception hierarchy |
| `gateway/__init__.py` | Re-export only |
| `gdrive_auth.py` | Google Drive OAuth token helper (55 statements) — pure logic, no live Drive call |
| `indicators.py` | All technical indicator functions |

---

## Near-complete (90%+) — remaining lines documented below

| Module | Coverage | Uncovered lines | Reason |
|---|---|---|---|
| `local_browser.py` | 95% | 137–138, 510, 599, 739, 846–852, 856 | Unparseable IP literal from DNS resolution (`ValueError` continue branch in `is_private_host`), and interactive `create_profile` / CLI paths that need a real TTY and a real browser — covered live, not by unit tests. |
| `models.py` | 99% | 147 | `return data` fallback in `AccountSummary._normalize` when input is not a dict — IBKR API always sends a dict; no known real-world trigger |
| `human_auth.py` | 96% | 14 | macOS `LocalAuthentication` import — requires Touch ID hardware; not unit-testable |
| `store.py` | 92% | 273–275, 303–308, 312–317, 321–323, 334–337, 528–529, 543 | Market-calendar exchange-loader edge branches and a catastrophic-exception fallback in `get_market_calendar_context` — exercised paths cover all known failure modes |
| `rate_limiter.py` | 93% | 106–107 | Non-429/503 HTTP error body-preview formatting inside `with_retry` — requires a live gateway response with a non-retryable status |
| `__init__.py` | 92% | 57–58 | Optional-dependency import guard (module absent from environment) |
| `auth.py` | 90% | 54, 78, 86–87 | `browser_cookie3` import and cookie-apply path — requires a real installed browser's cookie store |
| `pinescript.py` | 90% | 141–142, 230, 232, 234, 237 | KeyError in template `.format()` (only triggers if a template variable is missing from a custom indicator dict — not reachable via public API); timeframe-inference edge cases for sub-1-minute and multi-day intervals |
| `web_scraper.py` | 90% | 89–90, 230, 391–403, 430, 565–566, 587–588, 638–639 | Retry-After parse fallback, a 4xx branch in `_raise_for_status`, and Drive error paths in `WebDocsStore` (upload/manifest failures). The old `crawl()` pagination branches are gone with the method itself (2026-07-30). |

---

## Expected low coverage — live external dependencies or subprocess execution

These modules are fully functional but read as low-coverage for reasons other than missing tests: most
require live infrastructure to unit-test meaningfully; `backtest.py` is a different case — its logic runs
inside a spawned child process, invisible to single-process coverage instrumentation.

| Module | Coverage | Why low |
|---|---|---|
| `backtest.py` | 82% | Uncovered: 34–36, 50–55, 138–139, 159–186, 298. Most of this is *not* actually untested: `_write_guard`, `_sandboxed_getattr`, and all of `_execute_in_subprocess` (lines 34–36, 50–55, 159–186) run inside the sandboxed strategy's `multiprocessing.Process` child (see `docs/plans/2026-07-15-backtest-sandbox-subprocess-isolation-design.md`) — `coverage.py`'s default single-process instrumentation can't see code executing in a different OS process, even though the same 20 tests that exercised this logic pre-rewrite still exercise it today. Verified with multiprocessing-aware coverage (`COVERAGE_PROCESS_START` + `concurrency=multiprocessing`, a one-off local check, not wired into CI): real line coverage is ~92%. The two lines that are genuinely untested even under that measurement: `_terminate_then_kill`'s SIGKILL-escalation branch (138–139 — reached only if a killed process is somehow still alive after the SIGTERM grace period) and the success-path reap safety net (298 — reached only if the child is somehow still alive moments after a successful `send()`), both rare defensive branches with no deterministic trigger. |
| `cache.py` | 59% | All GDrive API operations (upload, download, manifest) require live OAuth tokens and Drive access. Error paths exercised in integration tests only. |
| `mcp_server.py` | 65% | SSE transport wiring (`uvicorn`, `starlette` app/routes) and MCP protocol request handlers exercise the full tool chain — require a live IBKR gateway + MCP client. Tested integration-only. |
| `gateway/manager.py` | 72% | Docker container lifecycle (`ensure_docker_running`, `image_exists`) and the interactive startup flow require Docker Desktop and a terminal for user input. All pure logic is tested. |
| `client.py` | 64% | IBKR Client Portal REST API endpoints — all require a running gateway at `localhost:5055`. Tested live via integration tests. The tested 64% covers shared infrastructure: auth, request signing, pagination math, error handling, retry logic. |
| `_order_dialog.py` | 83% | macOS AppKit `NSAlert`/`NSRunLoop` modal dialog subprocess (Gate 2's actual display code, split into its own process — see the pyobjc/Tahoe/Python 3.14 spurious-auto-confirm workaround) — requires a real running display/event loop, not unit-testable |
| `order_confirm.py` | 84% | AppleScript `display dialog` fallback path and countdown-tick internals — require a running display/event loop; macOS only |
| `flex_query.py` | 81% | `import_from_file` (reads a real file), `sync_archive_from_drive`, and `_archive_and_log` (require live GDrive) are integration paths. All error-handling paths (`_send_request`, `_get_statement`, `_parse_trades`) are 100% unit-tested. `_archive_and_log` verified live 2026-06-26 (see below). |
| `streaming.py` | 89% | WebSocket I/O methods (`connect`, `subscribe`, `listen`, `disconnect`) require a live IBKR WebSocket. `_parse_message` (the pure parsing logic) is fully tested; only network I/O is untested. |
| `claude_tools.py` | 89% | The untested 11% is live tool handlers that call `IBKRClient` methods and require a running IBKR gateway, plus a few defensive branches. Pure functions (`_parse_live_trades`, `_format_coverage`, tool definitions and routing) are fully tested. |

---

## What the unit tests specifically lock down

These are the load-bearing paths with regression tests. Editing any of them will fail specific named tests.

### Data integrity

| Path | Tests |
|---|---|
| `_parse_live_trades` — required fields, side normalization, commission sign | `test_parse_live_trades_*` (10 tests) |
| `_parse_trades` — 20% invalid-records guard (at threshold: no raise; above: raises) | `test_parse_trades_integrity_guard_*` |
| `_parse_trades` — skip on missing tradeID/symbol/buySell, raise on bad datetime | `test_parse_trades_*` |
| `get_trade_date_coverage` — gap detection boundary (45d = no flag, 46d = flagged) | `test_coverage_gap_*` (9 tests) |
| `get_trade_date_coverage` — `request_from/to` excludes trade dates themselves | `test_coverage_gap_request_range_excludes_trade_dates` |
| `get_trade_date_coverage` — NYSE calendar staleness vs fallback | `test_trade_coverage_*` (4 tests) |
| `_format_coverage` — gap instructions rendered, stale note rendered | `test_format_coverage_*` (3 tests) |
| `extract_execution_ids` — returns (unique_ids, raw_count); blank tradeID counted in raw but not unique; within-file duplicate detected | `test_extract_execution_ids_*` (3 tests) |
| `verify_flex_import` — all present (hash match), missing records, no Drive, no files, manual pre-validated | `test_verify_flex_import_*` (4 tests) |
| `log_flex_import` / `get_flex_import_entry` / `mark_flex_import_verified` — manifest CRUD | tested via `test_verify_flex_import_*` (mock store) |

### IBKR error handling (regression guard for real incidents)

| Path | Tests |
|---|---|
| Error 1001 (rate limit) — message includes "rate limit" and "5 minutes" | `test_send_request_error_1001_*` |
| Error 1025 (lockout) — message includes "1025" and "regenerate" | `test_send_request_warn_1025_*` |
| Unknown Fail/Warn error codes — not silently swallowed | `test_send_request_fail_unknown_*`, `test_send_request_warn_unknown_*` |
| URL allowlist — non-IBKR URL rejected | `test_send_request_rejects_non_ibkr_url` |

### Market calendar

| Path | Tests |
|---|---|
| All 20 exchanges load in `holidays_by_exchange` | `test_market_calendar_all_20_exchanges_loaded` |
| `cme_open_nyse_closed` non-empty, contains MLK Day | `test_market_calendar_cme_open_nyse_closed` |
| Futures block has note, maintenance_break_ct, all product groups | `test_market_calendar_futures_block_structure` |
| Process-level cache returns same object on second call | `test_market_calendar_process_cache_returns_same_object` |
| Cache key is `(date_str, exchanges)` — clearing forces recompute | `test_market_calendar_cache_key_is_date_and_exchanges` |
| Bad exchange code skipped, others still load | `test_market_calendar_bad_exchange_skipped_gracefully` |
| XSAU Friday is not a trading day (Sun–Thu week — 95 "holidays" is correct) | `test_xsau_friday_is_not_a_trading_day` |
| Grains close at 1:20 PM CT, not 4 PM (shorter than financial futures) | `test_futures_schedule_grains_shorter_hours` |

### Model alias normalization (IBKR API field name variants)

| Path | Tests |
|---|---|
| `Contract`: `secType`, `con_id`, `companyName` aliases | `test_contract_normalizes_*` |
| `Order`: `orderId`, `ticker`, `totalSize`, `orderType` aliases | `test_order_normalizes_ibkr_field_aliases` |
| `AccountSummary`: nested `{"amount": x}` dict and raw scalar both parse | `test_account_summary_parses_*` |

### Analytics edge cases

| Path | Tests |
|---|---|
| `sortino` with no negative bars → 0.0, not ZeroDivisionError | `test_sortino_no_negative_returns_is_zero` |
| `cagr` with empty series → 0.0 | `test_cagr_empty_series_returns_zero` |
| `calmar` with zero drawdown → 0.0 | `test_calmar_zero_drawdown_returns_zero` |
| `avg_win_loss_ratio` all-zero pnl → 0.0 (not inf) | `test_avg_win_loss_ratio_all_zero_returns_zero` |
| `avg_win_loss_ratio` with losses → correct ratio | `test_avg_win_loss_ratio_with_losses` |

### Backtest safety boundaries

| Path | Tests |
|---|---|
| Code exceeds `_MAX_CODE_LEN` → `BacktestSyntaxError` | `test_code_length_limit_raises` |
| Strategy omits `df['signal']` → `BacktestRuntimeError` | `test_missing_signal_column_raises` |

---

## Live integration tests (verified against real IBKR + GDrive)

These paths cannot be exercised in unit tests. Verified manually against a live account.

| Path | Date | Result |
|---|---|---|
| `fetch_trades` → `_archive_and_log` → Drive upload → `log_flex_import` | 2026-06-26 | `flex_U1675699_2026-06-26_4997140278.xml`: trade_id_count=161, raw_trade_count=161, source=auto, verified_at set at import time |
| `verify_flex_import` — hash match path (auto file, hash unchanged) | pending | — |
| `verify_flex_import` — manual file pre-validated path | pending | — |
| `sync_archive_from_drive` — full Drive XML re-import | pending | — |

---

## Running coverage locally

```bash
# Unit tests only (no IBKR gateway needed)
pytest -m "not integration" --cov=ibkr_core_mcp --cov-report=term-missing

# Full suite (requires live IBKR gateway at localhost:5055)
pytest --cov=ibkr_core_mcp --cov-report=term-missing
```
