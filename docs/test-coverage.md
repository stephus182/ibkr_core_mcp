# Test Coverage — ibkr_core_mcp

**1,764 unit tests · 102 integration tests (1,866 total) · 89% line coverage (non-integration)** — re-measured 2026-09-21 with the commands below. Seven net (eight added, one removed) with the fix for **Gate 2 degrading silently when a caller omits display-only keys** — both halves reproduced LIVE that day by scripts calling this package directly, neither reachable from claudia_ui. A futures order setting neither `_multiplier` nor `_multiplier_unknown` was not recognised as a future at all, so it printed `price × quantity` as the notional: `Total (est.): 7,300.00` for one ES contract standing for 365,000 — the same wrong number the 2026-09-04 fix was written for, through a door it did not cover. `is_future` now also accepts `secType` and `manualIndicator`, and the guard is **narrowed, not closed**, which the tests and the code both say. A stock without the keys must still print its total (multiplier 1), pinned by its own test, because a blanket refusal would blank every equity dialog — that test passed before the fix and is what makes the other two discriminating rather than merely red. The second half: a cancel with no `order_details` showed an order id and an account number and nothing else; `cancel_order` now fetches the detail itself, **between Gate 1 and Gate 2** — an earlier placement broke the SEC-02 invariant that no network call precedes the gates and was caught by `tests/security/test_order_write_boundary.py`, then **reordered rather than exempted**. A passing test had asserted the id-only dialog as correct, which is why it read as intentional; it is replaced by one keeping the shape and requiring the gap to be named. Coverage re-run: total unchanged at 89%, `client.py` unchanged at 87%, `order_confirm.py` 96%. Previously: seven added by the control that closes the class the `preview_order` defect belonged to. The whatif shape was **missing from `tests/fixtures/ibkr_live_shapes.json`**, deliberately — the capture script is read-only and says `get_order_preview` "simulates but still POSTs an order body, so it is captured only with the owner present and asking for it". That condition was met, so it is captured, redacted and registered (41 endpoints). `tests/test_readers_against_live_shapes.py` now runs a reader against the captured shape through a mapping that records every key lookup that MISSED, asserting no reader indexes a key IBKR does not send — values are irrelevant, which is why a fully redacted fixture proves it. `test_published_identifiers.py` gained the other half: its redaction guard covered that one file while real balances were committed in a hand-written constant two directories away, so a `LIVE_*` payload literal must now be declared synthetic with a reason. Its first version carried an escape clause ("the file mentions the fixture") that made it **vacuous** — caught by re-running the check with a declaration removed, and deleted rather than patched. Coverage re-run: total unchanged at 89%, `claude_tools.py` unchanged at 90%. Previously: two added with the `modify_order_and_confirm` reply-loop fix: `modify_order`'s response went into `while "id" in response` **unnormalised**, which on IBKR's documented array is a membership test, not a key test — so a modify that raised a precaution returned that precaution as though it were the result, unshown and unanswered, with the modification never applied. Every prior test mocked the INITIAL response as a bare dict, a shape IBKR does not send; the list-shaped *reply* case was already covered, so only the first response was blind. The new tests use the array shape for the initial response and are verified discriminating by neutralising `_as_reply_dict` in memory rather than editing the source. Coverage re-run: total unchanged at 89%, `client.py` unchanged at 87%. Previously: five added with the `preview_order` fix: the tool read `commission`, `equity.amount`, `initMarginChange` and `maintMarginChange` — **four keys the whatif does not send** — so every margin figure and the commission rendered `N/A` on every real call, and it read neither `error` nor `warns`, so a preview IBKR REFUSED rendered identically to one it accepted. Measured live that day: a `BUY 2 ES` the account could not support returned IBKR's "Available Funds … insufficient" plus three warnings, none of which reached the model. The tests could not have caught it — the mock was invented to match the reader (`{"commission": "1.05", "equity": {"amount": …}, "initMarginChange": …}`) and asserted only the REQUEST payload plus the literal "Order Preview", never a rendered figure. Every fabricated preview mock in the suite is now the shape captured live (`LIVE_PREVIEW_ACCEPTED` / `LIVE_PREVIEW_REFUSED`), and the new tests pin each figure to the key IBKR actually uses, the refusal appearing before any figure, an accepted preview NOT claiming a refusal, warnings surfaced with HTML stripped onto one line, and an omitted block named absent rather than rendered as a number. Coverage re-run: total unchanged at 89%, `claude_tools.py` unchanged at 90%. Previously: six added by the Phase 1 self-review, which found the new write path exempt from two class-level security controls it should have joined: the behavioural half of SEC-02 (`test_a_denied_gate_1_sends_no_order_write_however_fresh_the_session`, a hand-written list of four) and the body-the-dialog-showed-is-the-body-sent control (a hand-written list of two). Both now cover the bracket, the first with a guard asserting its case list covers every public gated write. The same review moved the contract-mismatch refusal forward into `_bracket_tickets`, so a place is refused before Touch ID and a mismatched pair cannot be previewed either. Before that, 12 tests added with `place_bracket_and_confirm`: one array in one POST, one Touch ID scoped to the WHOLE array, one Gate 2, every ticket's reply answered in index order — including two that pin defects the single-order idiom would ship, a precaution raised against the SECOND ticket going unanswered and a terminal leg being dropped when another leg replies — plus the already-answered-reply loop guard, the pre-gate refusal of an unlinked child, the decline path, the reply log, and IBKR's bare-object rejection surviving as its own words rather than as an empty list. Coverage re-run and unchanged at 89%; every line of the new method is covered. Earlier the same day: 19 tests added with `confirm_bracket_dialog`, the Gate 2 dialog for a bracket: both legs on one screen, the five refusals it enforces — no child, no parent side, a same-side child, an unlinked child, a child on another contract — the child shown as held rather than working, one notional row named as the parent's, both legs rendered through the one shared row builder, two same-kind legs kept distinct, and a structural check that the Gate 2 dialog enumeration covers every `confirm_*_dialog` in the module rather than a hand-written list. Coverage re-run and unchanged at 89%; every line of the new function is covered). Previously re-measured 2026-09-20 with the commands below (three tests added with the front-month fix, gap #58: an expired contract is never the front month, `ltd` decides over `expirationDate`, and a row with no usable date is kept rather than dropped; coverage re-run and unchanged at 89%). Earlier the same day: `get_bracket_preview` (7) and the M7 / field-8089 fix (1). Previously re-measured 2026-09-19  (after the 2.0.1 release: 21 tests added for the wheel smoke test and the rate-limit visibility pass, then 2 for the PEP 440 canonical-version guard; coverage unchanged, as that guard reads `pyproject.toml` and no shipped module) with the commands below, per-module figures included, not carried over. Do not edit these numbers by hand; re-run the commands below.

> **These numbers were 30% wrong for eight days.** The file read 1,008 / 93 / 1,101 / 85% from
> 2026-09-08 while the tree had grown to 1,459 unit tests across 26 commits, and **12 of 28
> per-module figures had drifted**. The file's own rule — "do not edit these numbers by hand;
> re-run the commands below" — was correct and nobody ran them. Two of the drifts were caused
> by the release-readiness audit itself: `indicators.py` fell out of the 100% table (its DATA-01
> fix added two early returns with no test) and `models.py` dropped 99% → 95% (`IBKRResponse`'s
> `items()`, `values()` and `.raw` had none either). Both are pinned now and both are back.
> Re-measured after that: `indicators.py` 100%, `models.py` 98%.
>
> **And they drifted again, in one day.** On 2026-09-17 the headline still read 1,459 / 100 /
> 1,559 while the tree held **1,523 / 102 / 1,625** — the audit's own sessions had added 64
> unit tests since. Coverage was the only one of the four that held, at 87%. The rule above
> was right twice and followed neither time, so the counts are now machine-checked:
> `tests/test_config_docs_consistency.py` collects the suite and fails if this headline
> disagrees — and the guard counts itself, so adding it moved the figure from 1,523 to
> **1,524** and the first run of it failed on exactly that. The file now counts a tree
> that includes the thing counting it. A number a human must remember to update is a number that will be wrong (DOCB-R1).
>
> **And then the guard did its job.** The API-11 typing work later the same day took the
> tree to **1,624 / 102 / 1,726** and coverage from 87% to **89%**, and the headline was
> red on the first run rather than eight days later. `models.py` went 98% → 99% and
> `client.py` 81% → 86%, both because 29 methods' return paths are now driven against
> captured live responses. `client.py`'s row had also been carrying two contradictory
> figures — "the tested 74%" inside a row headed 81% — from two different runs; one now.

Run: `pytest -m "not integration"` · Integration only: `pytest -m integration` (requires live gateway)

**How to re-measure.** `pytest-cov` is *not* installed in this venv, so `--cov` flags fail
with `unrecognized arguments`. The `coverage` package itself is present — drive it directly:

```bash
# The pipe into grep is a COUNT, not a gate: it returns grep's status, so a collection error
# would yield a quietly wrong number. Capture pytest's own status first (CLAUDE.md, "No gate
# command may be piped").
pytest --collect-only -q -m "not integration" -p no:cacheprovider > /tmp/u.txt; echo "exit=$?"
grep -cE '^tests/.*::' /tmp/u.txt                                        # unit count
pytest --collect-only -q -m integration -p no:cacheprovider > /tmp/i.txt; echo "exit=$?"
grep -cE '^tests/.*::' /tmp/i.txt                                        # integration count
coverage run --source=ibkr_core_mcp -m pytest -m "not integration" -q; echo "exit=$?"
coverage report -m
```

> **Note on the previous reading.** This file carried `~83%` from 2026-07-30 with an explicit
> caveat that it was a floor, never re-measured, because `pytest-cov` was missing. The direct
> `coverage run` above settles it at **85%** — so the floor held. The per-module figures below
> were re-measured in the same run; several had drifted by 1–9 points in both directions
> (`client.py` 64% → 74%, `cache.py` 59% → 51%).

Live integration test log: [`docs/audits/live-test-log.md`](audits/live-test-log.md)

---

## 100% Coverage (no gaps)

| Module | Notes |
|---|---|
| `analytics.py` | All metric functions including all zero/empty edge cases |
| `config.py` | Config dataclass and validation |
| `exceptions.py` | Exception hierarchy |
| `gateway/__init__.py` | Re-export only |
| `flex_schema.py` | **Generated** by `scripts/audit_flex_xml.py` — column definitions only, no logic |
| `gdrive_auth.py` | Google Drive OAuth token helper (27 statements) — pure logic, no live Drive call |
| `indicators.py` | All technical indicator functions |

---

## Near-complete (90%+) — remaining lines documented below

| Module | Coverage | Uncovered lines | Reason |
|---|---|---|---|
| `local_browser.py` | 95% | 161–162, 184, 486–487, 586, 792, 1083, 1190–1196, 1200 | Unparseable IP literal from DNS resolution (`ValueError` continue branch in `is_private_host`), and interactive `create_profile` / CLI paths that need a real TTY and a real browser — covered live, not by unit tests. |
| `flex_import.py` | 90% | 180, 232–236, 240–241, 269, 273–274, 279–283, 340 | Type-coercion failure branches (`INTEGER`/`REAL` attributes that IBKR has never emitted as non-numeric), the unparseable-date raise in `normalise_datetime`, the blank-`execId` skip and unparseable-timestamp warning in the live-fill path, and the `counts()` accessor. Every one is a defensive branch against IBKR changing a format — the raising behaviour is deliberate (see `flex_import.py`'s refusal-on-unknown-attribute contract), so these fire only on a schema change, which is exactly when you want them loud. |
| `flex_store.py` | 97% | 126, 134 |
| `models.py` | 99% | 100, 337, 976 | Three defensive branches: the non-dict input path in `IBKRResponse._keep_raw_payload`, the `return data` fallback in `AccountSummary._reduce`, and `json_default`'s raise for an object that is neither a model nor JSON-native. IBKR sends a dict on every endpoint captured, so none has a known real-world trigger. |
| `human_auth.py` | 98% | 101 | macOS `LocalAuthentication` import — requires Touch ID hardware; not unit-testable |
| `store.py` | 93% | 408, 424, 451–453, 481–484, 488–491, 495–497, 508–511, 799 | Market-calendar exchange-loader edge branches and a catastrophic-exception fallback in `get_market_calendar_context` — exercised paths cover all known failure modes |
| `rate_limiter.py` | 98% | 368–369 | Non-429/503 HTTP error body-preview formatting inside `with_retry` — requires a live gateway response with a non-retryable status |
| `__init__.py` | 92% | 64–65 | Optional-dependency import guard (module absent from environment) |
| `auth.py` | 93% | 81, 142–143 | `browser_cookie3` import and cookie-apply path — requires a real installed browser's cookie store |
| `pinescript.py` | 90% | 143–144, 232, 234, 236, 239 | KeyError in template `.format()` (only triggers if a template variable is missing from a custom indicator dict — not reachable via public API); timeframe-inference edge cases for sub-1-minute and multi-day intervals |
| `web_scraper.py` | 95% | 88–89, 229, 427, 562–563, 584–585, 648–649 | Retry-After parse fallback, a 4xx branch in `_raise_for_status`, and Drive error paths in `WebDocsStore` (upload/manifest failures). The old `crawl()` pagination branches are gone with the method itself (2026-07-30). |

---

## Expected low coverage — live external dependencies or subprocess execution

These modules are fully functional but read as low-coverage for reasons other than missing tests: most
require live infrastructure to unit-test meaningfully; `backtest.py` is a different case — its logic runs
inside a spawned child process, invisible to single-process coverage instrumentation.

| Module | Coverage | Why low |
|---|---|---|
| `backtest.py` | 88% | Uncovered: 34–36, 50–55, 138–139, 159–186, 298. Most of this is *not* actually untested: `_write_guard`, `_sandboxed_getattr`, and all of `_execute_in_subprocess` (lines 34–36, 50–55, 159–186) run inside the sandboxed strategy's `multiprocessing.Process` child (see `docs/plans/archive/infrastructure/2026-07-15-backtest-sandbox-subprocess-isolation-design.md`) — `coverage.py`'s default single-process instrumentation can't see code executing in a different OS process, even though the same 20 tests that exercised this logic pre-rewrite still exercise it today. Verified with multiprocessing-aware coverage (`COVERAGE_PROCESS_START` + `concurrency=multiprocessing`, a one-off local check, not wired into CI): real line coverage is ~92%. The two lines that are genuinely untested even under that measurement: `_terminate_then_kill`'s SIGKILL-escalation branch (138–139 — reached only if a killed process is somehow still alive after the SIGTERM grace period) and the success-path reap safety net (298 — reached only if the child is somehow still alive moments after a successful `send()`), both rare defensive branches with no deterministic trigger. |
| `cache.py` | 51% | All GDrive API operations (upload, download, manifest) require live OAuth tokens and Drive access. Error paths exercised in integration tests only. |
| `mcp_server.py` | 81% | SSE transport wiring (`uvicorn`, `starlette` app/routes) and MCP protocol request handlers exercise the full tool chain — require a live IBKR gateway + MCP client. Tested integration-only. |
| `gateway/manager.py` | 73% | Docker container lifecycle (`ensure_docker_running`, `image_exists`) and the interactive startup flow require Docker Desktop and a terminal for user input. All pure logic is tested. |
| `client.py` | 87% | IBKR Client Portal REST API endpoints — all require a running gateway at `localhost:5055`. Tested live via integration tests. The tested share covers shared infrastructure: auth, request signing, pagination math, error handling, retry logic — and, since the API-11 typing work, the return path of 29 methods driven against captured live responses. (This row carried a second, contradictory figure — "the tested 74%" beside a headline of 81% — from two different runs; one number now.) |
| `_order_dialog.py` | 89% | macOS AppKit `NSAlert`/`NSRunLoop` modal dialog subprocess (Gate 2's actual display code, split into its own process — see the pyobjc/Tahoe/Python 3.14 spurious-auto-confirm workaround) — requires a real running display/event loop, not unit-testable |
| `order_confirm.py` | 96% | AppleScript `display dialog` fallback path and countdown-tick internals — require a running display/event loop; macOS only |
| `flex_query.py` | 83% | `import_from_file` (reads a real file), `sync_archive_from_drive`, and `_archive_and_log` (require live GDrive) are integration paths. All error-handling paths (`_send_request`, `_get_statement`, `_parse_trades`) are 100% unit-tested. `_archive_and_log` verified live 2026-06-26 (see below). |
| `streaming.py` | 90% | WebSocket I/O methods (`connect`, `subscribe`, `listen`, `disconnect`) require a live IBKR WebSocket. `_parse_message` (the pure parsing logic) is fully tested; only network I/O is untested. |
| `claude_tools.py` | 90% | The untested 11% is live tool handlers that call `IBKRClient` methods and require a running IBKR gateway, plus a few defensive branches. Pure functions (`_parse_live_trades`, `_format_coverage`, tool definitions and routing) are fully tested. |

---

## What the unit tests specifically lock down

These are the load-bearing paths with regression tests. Editing any of them will fail specific named tests.
The counts in the tables below are collected test ids matching each name prefix, measured
2026-09-17 — four of them had drifted (10→9, 9→2, 3→2, 4→5) since they were last typed.

### Data integrity

| Path | Tests |
|---|---|
| `_parse_live_trades` — required fields, side normalization, commission sign | `test_parse_live_trades_*` (9 tests) |
| `_parse_trades` — 20% invalid-records guard (at threshold: no raise; above: raises) | `test_parse_trades_integrity_guard_*` |
| `_parse_trades` — skip on missing tradeID/symbol/buySell, raise on bad datetime | `test_parse_trades_*` |
| `get_trade_date_coverage` — gap detection boundary (45d = no flag, 46d = flagged) | `test_coverage_gap_*` (2 tests) |
| `get_trade_date_coverage` — `request_from/to` excludes trade dates themselves | `test_coverage_gap_request_range_excludes_trade_dates` |
| `get_trade_date_coverage` — NYSE calendar staleness vs fallback | `test_trade_coverage_*` (4 tests) |
| `_format_coverage` — gap instructions rendered, stale note rendered | `test_format_coverage_*` (3 tests) |
| `extract_execution_ids` — returns (unique_ids, raw_count); blank tradeID counted in raw but not unique; within-file duplicate detected | `test_extract_execution_ids_*` (2 tests) |
| `verify_flex_import` — all present (hash match), missing records, no Drive, no files, manual pre-validated | `test_verify_flex_import_*` (5 tests) |
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
| `fetch_trades` → `_archive_and_log` → Drive upload → `log_flex_import` | 2026-06-26 | `flex_UXXXX699_2026-06-26_4997140278.xml`: trade_id_count=161, raw_trade_count=161, source=auto, verified_at set at import time |
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
