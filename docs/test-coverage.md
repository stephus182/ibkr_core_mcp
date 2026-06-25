# Test Coverage — ibkr_core_mcp

**363 tests · 72% line coverage (non-integration)**
Run: `pytest -m "not integration"` · Full suite: `pytest`

---

## 100% Coverage (no gaps)

| Module | Notes |
|---|---|
| `__init__.py` | Public exports, version |
| `analytics.py` | All metric functions including all zero/empty edge cases |
| `config.py` | Config dataclass and validation |
| `exceptions.py` | Exception hierarchy |
| `gateway/__init__.py` | Re-export only |
| `indicators.py` | All technical indicator functions |
| `rate_limiter.py` | Token bucket implementation |

---

## Near-complete (90%+) — remaining lines documented below

| Module | Coverage | Uncovered lines | Reason |
|---|---|---|---|
| `store.py` | 99% | 341–342 | `except Exception: return {}` in `get_market_calendar_context` — fires only on catastrophic unhandled exception inside the calendar build block; all known failure modes are tested via specific paths |
| `models.py` | 99% | 117 | `return data` fallback in `AccountSummary._normalize` when input is not a dict — IBKR API always sends a dict; no known real-world trigger |
| `human_auth.py` | 96% | 14 | macOS `LocalAuthentication` import — requires Touch ID hardware; not unit-testable |
| `backtest.py` | 96% | 30, 163–164 | Line 30: non-Module write-guard fallback (only fires for exotic object types); 163–164: `concurrent.futures.TimeoutError` path in strategy executor — requires real timeout, not deterministically triggerable |
| `auth.py` | 91% | 50, 64, 72–73 | `TokenAuth.__repr__` (trivial); `browser_cookie3` import and cookie apply — requires a real browser install |
| `order_confirm.py` | 92% | 135–136, 166–171 | tkinter `after_cancel` and countdown tick — require a running display/event loop; macOS only |
| `pinescript.py` | 90% | 134–135, 220, 222, 224, 227 | KeyError in template `.format()` (only triggers if a template variable is missing from a custom indicator dict — not reachable via public API); timeframe inference edge cases for sub-1-minute and multi-day intervals |

---

## Expected low coverage — live external dependencies

These modules are fully functional but cannot be meaningfully unit-tested without live infrastructure.

| Module | Coverage | Why low |
|---|---|---|
| `cache.py` | 33% | All GDrive API operations (upload, download, manifest) require live OAuth tokens and Drive access. Error paths exercised in integration tests only. |
| `client.py` | 58% | IBKR Client Portal REST API endpoints — all require a running gateway at `localhost:5055`. Tested live via integration tests. The tested 42% covers shared infrastructure: auth, request signing, error handling, retry logic. |
| `mcp_server.py` | 49% | MCP protocol request handlers exercise the full tool chain. Require live IBKR gateway + MCP client. Tested integration-only. |
| `streaming.py` | 82% | WebSocket I/O methods (`connect`, `subscribe`, `listen`, `disconnect`) require a live IBKR WebSocket. `_parse_message` (the pure parsing logic) is 100% tested; only network I/O is untested. |
| `gateway/manager.py` | 73% | Docker container lifecycle (`ensure_docker_running`, `image_exists`) and interactive startup flow (268–304) require Docker Desktop and a terminal for user input. All pure logic is tested. |
| `claude_tools.py` | 68% | The tested 32% covers all pure functions: `_parse_live_trades` (10 tests), `_format_coverage` (3 tests), tool definitions and routing. The untested 32% is live tool handlers that call `IBKRClient` methods — all require a running IBKR gateway. |
| `flex_query.py` | 77% | `import_from_file` (reads a real file) and `sync_archive_from_drive` (requires GDrive) are integration paths. All error-handling paths (`_send_request`, `_get_statement`, `_parse_trades`) are 100% unit-tested. |

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

## Running coverage locally

```bash
# Unit tests only (no IBKR gateway needed)
pytest -m "not integration" --cov=ibkr_core_mcp --cov-report=term-missing

# Full suite (requires live IBKR gateway at localhost:5055)
pytest --cov=ibkr_core_mcp --cov-report=term-missing
```
