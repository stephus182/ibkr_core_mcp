# Changelog

All notable changes to `ibkr_core_mcp` are documented here.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

### Changed
- **The web scraper is now four tools with one job each and no fallback between them** (2026-07-30). Anything that takes a URL goes to the free local browser; Firecrawl keeps only whole-web search, the one thing the browser cannot do. `firecrawl_search` finds pages anywhere, `search_site` finds pages on one site, `crawl_site` archives a site to Drive, `fetch_page` reads one page. The first two return URLs; the last two return text.

  **The two-rung ladder was deleted because its premise was backwards.** It ran the paid engine first and fell back to the free one. Measured on the same URLs minutes apart: local returned 17,364 B in 1.2 s where Firecrawl returned 14,341 B in 16.8 s, and 8,786 B in 1.3 s against 5,515 B in 13.2 s — bigger, ~10× faster, free. Roughly 900 lines of arbitration went with it (`_merge_pages`, `_assess_fallback_need`, `_finalize_fallback_result`, `_scrape_with_fallback`, `_apply_crawl4ai_fallback_batch`, `_crawl4ai_root_scrape`, `_handle_firecrawl_crawl`), plus 330 lines of Firecrawl crawl machinery — job start, the 5 s polling loop, `next` pagination and its three termination guards. Net across the refactor: ~1,100 insertions against ~2,000 deletions.

  **The scraper no longer calls the Anthropic API at all.** `judge_completeness_llm` was the single documented exception to "ClaudeToolkit is the only layer that talks to Anthropic", and invisible to a host app's own token accounting. It is not better-guarded; with one engine per job there is nothing for a model to arbitrate.

  `WebDocsStore` is untouched — all 303 lines, the same `web_docs/` Drive layout, the same 48h manifest cache, the same slug-collision handling. It never referenced `FirecrawlClient` in code, only in docstrings, which is what let `crawl_site` slot in beneath it as a drop-in rather than a migration.

- **`firecrawl_search` finds without reading.** It used to fan out up to five concurrent local browsers to re-fetch every result, because Firecrawl's extraction was the only thing between the model and the page. It now returns URLs, titles and a ~400-character snippet, and points at `fetch_page`. Removing the extraction step is also what makes the search/read split legible to the model.

### Added
- **`search_site` — BM25-ranked page discovery within one domain.** Free: Crawl4AI's `AsyncUrlSeeder` over public sitemaps and the Common Crawl index, scored against each page's extracted `<head>`. ~5 s for 87 URLs. Two findings only a live run produced, both now load-bearing. **`extract_head=True` is mandatory, not a default** — with it 87 of 87 URLs are scored; without it *zero* are and the list is sitemap order. The vendor's own documented example omits the flag, so copying it yields something that looks like ranked search and is not. **A non-matching query scores 0.5, not 0.0** — the first live run answered "zzzq nonexistent topic xyzzy" with ten confidently-ranked pages (Privacy Policy, Contributing Guide, home page), every one at exactly 0.500, because BM25 gives every page a neutral score when no term overlaps. The unit tests had mocked a miss as 0.0: a mock weaker than its dependency, the same failure mode that let `create_profile` ship having never run. "Nothing matched" is now detected as a completely flat distribution, which the vendor's own `score_threshold` cannot express (0.51 empties the nonsense query but also discards genuine 0.400 hits).
- **`crawl_site` — archive a site with the local browser.** Breadth-first, same-host only (`include_external=False`, a safety property: it stops a hostile page walking the crawler onto another host), into the existing `WebDocsStore`. Works on sites behind a login, which the paid rung could not do at all. Two more live-only findings: **the strategy returns the root URL twice**, depth 0 and depth 1 byte-identical, which would make `save_crawl` write one file but record two manifest entries — found by probing the real API before writing the function. And **an error page is still a page**: crawling `docs.crawl4ai.com/core/` returned one 44-byte nginx `403 Forbidden` (that path is a directory prefix) and the handler reported "Crawl complete: saved 1 page(s)" while filing it into the research archive. That is the third instance of this trap here, after "saved 0 page(s)" reported as success and `fetch_page`'s "(1 B)" reading like a short page. It now refuses to save when every page grades `fallback`, and quotes the offending text.
- **`fetch_page` — a single-URL browser fetch tool** (44 tools total, 46 via the MCP server). Until now the only way to read one known URL was `firecrawl_crawl` against it, which archives up to 50 pages to Drive to answer a question about one — and which cannot open a paywall at all, because Crawl4AI was reachable only as a fallback *underneath* a Firecrawl attempt. `fetch_page` goes straight to the local browser: it finds a saved login profile by domain, states in its reply whether one was used, and returns the full article instead of the subscription stub. This is the piece that makes the paywalled-site capability (`docs/web-scraper-reference.md` §6) actually reachable; everything else — profile lookup, paywall detection, the `create-profile` CLI — was already built and tested. SSRF-validated before the browser is constructed, and degrades to a message (not a traceback) when the `[scraper]` extra is absent, the browser crashes, or the page comes back empty.

### Removed
- **The Crawl4AI Cloud rung** (`crawl4ai_cloud.py`, 432 lines, 37 tests, added earlier the same day). The recovery ladder is two rungs again: Firecrawl → local Crawl4AI. It bought nothing the local browser did not already do — on the only real block ever observed (2026-07-02, IBKR/Akamai) the free local rung won with 144,125 chars, so the paid rung addressed a failure mode never once seen. It also could not serve the requirement that motivated Crawl4AI in the first place: opening a paywall through Cloud would mean uploading a logged-in WSJ/FT session to a third party, and the vendor's own SDK does not even wrap that endpoint. `Config.crawl4ai_api_key`/`crawl4ai_api_url` and the `crawl4ai-cloud-sdk` dependency go with it; `Config.crawl4ai_profiles_dir` (the near-identically-named *paywall* setting) is unaffected. Findings from the live API — four vendor-doc errors and a response field that misreports its own billing — are preserved in `docs/web-scraper-reference.md` §5.1 as evidence for the standing "a published reference is a claim, not evidence" rule.

### Fixed
- **The crawl ladder's root rescue discarded Firecrawl's pages instead of adding to them.** `_handle_firecrawl_crawl` did `pages = root_pages` whenever the local rung's single root page outweighed everything Firecrawl returned. That honored the documented promise ("a fallback can never shrink what Firecrawl already returned") bytewise while breaking it page-wise: three genuinely complete ~1.5 KB documentation pages measure under the 5 KB bar, so a larger root scrape archived one page to Drive and silently dropped the other three. The rescue now merges by URL (`_merge_pages`), larger markdown winning when both rungs return the same URL, so it can only ever add. Because merging cannot cost anything, the rung no longer has to win outright to be used, and the `Source:` line names both rungs when both contributed. Regression tests: `test_root_rescue_keeps_firecrawls_pages_instead_of_replacing_them`, `test_root_rescue_prefers_the_larger_markdown_for_a_duplicated_url`, `test_local_rung_does_not_replace_a_larger_firecrawl_result`.
- **`fetch_page`'s tool description promised the model something false.** It named WSJ among the paywalled sites that "return the full article instead of the subscription stub". Re-measured 2026-07-30 with a real saved WSJ profile in place: `wsj.com` returns 1 B at HTTP 401 ("Blocked by anti-bot protection: DataDome captcha") headless *or* visible, with the profile *or* without — the block precedes authentication, so no login can move it. The description now says a saved profile is needed, names `wsj.com` as confirmed-blocked, and tells the model to report the block rather than retry or claim the page was read. `docs/web-scraper-reference.md` §6 carries the full status, and `ft.com` (59,455 B, HTTP 200, no profile) is identified as the host to prove the paywall path on.
- `FirecrawlClient.search()`/`.crawl()` were annotated `-> list[dict[str, str]]`, but both methods' own docstrings already documented a `"metadata": dict` field returned alongside the `str` fields — the annotation didn't match the method's own contract. Widened to `list[dict[str, Any]]` (4 sites in `web_scraper.py`); no behavior change, Python never enforced the narrower type at runtime. Found during the 2026-07-22 code-quality audit — see `docs/audits/2026-07-22-code-quality-audit.md`.
- `get_account_summary` no longer claims `/portfolio/{accountId}/summary` carries P&L fields — that endpoint's ~90-key response never includes `unrealizedpnl`/`realizedpnl` (live-verified 2026-07-17, confirmed against official docs); the tool description and formatter now point to `get_ledger`/`get_pnl` instead. See `docs/plans/2026-07-17-account-pnl-display-fixes.md` in the sibling `claudia_ui` repo.
- `get_pnl` (`/iserver/account/pnl/partitioned`) returned an empty `{"upnl": {}}` on a cold gateway session — even with open positions and real P&L — until something subscribed to the `spl` WebSocket topic at least once (live-verified 2026-07-17; same undocumented warm-up class as `/iserver/marketdata/snapshot`). `_get_pnl` now self-primes: on an empty first response it does a best-effort `spl` subscribe/unsubscribe touch and retries once, never raising on failure.
- Backtest sandbox strategy code that timed out (e.g. `while True: pass`) survived the 10-second timeout indefinitely in an orphaned `ThreadPoolExecutor` thread — `Future.cancel()` cannot stop a thread already executing. Worse, `concurrent.futures.thread` registers a non-daemon-thread join in its interpreter-shutdown hook, so a host process that ever hit this path could hang indefinitely on exit. The sandbox now runs strategy code in an isolated `multiprocessing.Process`, with a daemon watchdog thread that force-kills the child (SIGTERM, then SIGKILL after a grace period) if the timeout elapses — a real OS process can be forcibly stopped, unlike a thread. `run_backtest()`'s public signature and exception contract are unchanged. See `SECURITY.md`'s "Thread timeout non-termination" entry for the full mechanism.

### Changed
- `[tool.mypy]` now sets `files = ["ibkr_core_mcp", "tests"]` — `tests/` (39 modules, 747 tests) had never actually been type-checked by CI or locally, only `ibkr_core_mcp/` was. A narrow `tests.*` override relaxes `disallow_untyped_defs`/`disallow_incomplete_defs`/`disallow_untyped_calls` (this codebase's tests have zero signature annotations by established convention) while every other `strict` check, including body-level `check_untyped_defs`, stays on. Surfaced 183 real findings across 12 test files, all fixed; CI's `mypy` step updated to match. Full inventory and triage: `docs/audits/2026-07-22-code-quality-audit.md`.

---

## [1.2.2] — 2026-07-15

### Fixed
- Dev `.venv` was accidentally built on Python 3.14 (Homebrew never had 3.11 installed on this machine) — reverted to 3.11; `requires-python` now pins `>=3.11,<3.14` and rejects 3.14 interpreters at install time, matching the `3.11`–`3.13` classifiers already declared. No 3.14-specific code existed in the package itself; this is a guardrail against future silent drift, not a functional-incompatibility fix.
- `websockets` moved from the `[server]` optional extra into base `dependencies` — `IBKRWebSocket`/`AlertManager` are exported from the package's top-level `__init__.py` as core public API, not server-only functionality, but their sole dependency was gated behind an extra alongside `mcp`/`starlette`/`uvicorn` (which remain server-only — they're used exclusively by the standalone `mcp_server.py` entry point). Consumers that `import IBKRWebSocket` directly without running the MCP server previously got a silent `ModuleNotFoundError` at runtime instead of an install-time failure.

---

## [1.2.0] — 2026-07-14

### Added
- Firecrawl requests now retry on 429/408/5xx with Retry-After-aware exponential backoff (search, crawl job-start, crawl polling)
- `firecrawl_crawl` checks a Drive read-cache (<48h) before re-fetching a previously-archived URL

### Fixed
- `get_pa_transactions` was sending IBKR the wrong request body (a period string instead of a resolved conid) — redesigned to take `symbol`/`sec_type`/`currency`/`days`, matching `client.py`'s real signature
- `FirecrawlClient.crawl()` now follows the `"next"` pagination cursor — crawls whose result exceeded 10MB were silently truncated to the first chunk; retry loop bounded
- `_scrape_with_fallback`'s "Crawl4AI fallback used" reporting no longer overcounts — it now returns an explicit `used_fallback` flag instead of inferring from a non-empty note; `WebDocsStore.save_crawl` disambiguates filenames that collide after slugifying (e.g. `/a-b` vs `/a_b`)
- `gdrive_auth.load_or_refresh_credentials()` docstring promises it never raises, but an uncaught `RefreshError` from a revoked/expired token could propagate anyway — now caught and treated as no-credentials, matching the documented contract
- `pyproject.toml`'s `version` field was never bumped for the `v1.1.0` tag (stayed at `1.0.0`) — since `__version__` is derived via `importlib.metadata`, any `v1.1.0` install silently self-reported `1.0.0`. Corrected to `1.2.0` here; that stale `v1.1.0` tag itself is left as-is rather than rewritten.

---

## [1.2.1] — 2026-07-14

### Fixed
- `docs/api-usage-examples.md`: two print statements used `:.1f}%` instead of `:.1%` for `max_drawdown` (a negative fraction), which would silently print a 30% drawdown as "-0.3%"; the Portfolio Analytics 1-minute-bar example passed `periods=1440` (minutes/day) instead of `98280` (bars/year), mis-annualizing Sharpe/Sortino/CAGR/Calmar by ~68x

---

## [1.1.0] — 2026-07-12

### Added
- Crawl4AI fallback (`local_browser.py`) for incomplete/paywalled Firecrawl results, gated by an LLM completeness check
- WebSocket `str` (trades) and `spl` (P&L) topics added to `IBKRWebSocket`
- `IBKRClient.place_order_and_confirm()` / `modify_order_and_confirm()` — loop Gate 1 (Touch ID) + Gate 2 (dialog showing the real IBKR reply text) across a chained-reply sequence until a terminal order state is reached
- `cancel_order()` gained an optional `order_details` param so Gate 2's cancel dialog shows full order details instead of just the order ID
- Futures support (STK/FUT/FOP) added to order staging
- `client.get_orders_raw()` / `get_pa_periods_raw()` made public — removes the last private `client._get`/`client._post` reach-ins from `claude_tools.py`
- `get_option_chain` reimplemented via the documented `secdef/search` → `secdef/strikes` flow

### Fixed
- SSRF guard closes DNS-rebinding and open-redirect gaps in the Crawl4AI fallback path
- `preview_order` gains `stop_price`/`sec_type` schema fields with correct `price`/`auxPrice` mapping for STP/STOP_LIMIT orders (previously a live HTTP 500 for any stop order)
- `get_option_strikes` read a nonexistent `'strike'` key and claimed the wrong month format (`'JAN2026'` vs IBKR's actual `'JAN26'`)
- `get_pnl` response shape corrected to match IBKR's documented `/iserver/account/pnl/partitioned` format; `create_price_alert`'s advertised FUT/OPT/FX support was unreachable and now resolves through the same conid-resolution path as market data
- `get_live_orders`/`diagnose_orders` checked `orderRef`/`cOID` instead of IBKR's real `order_ref` field — every order, including ClaudIA's own, fell through to an unreliable `clientId` check and was mislabeled EXTERNAL
- Chained order-reply confirmations (e.g. price-band %, no-market-data, mandatory-cap-price warnings) now auto-resolve through Gate 1 + Gate 2 instead of requiring manual `reply_order()` calls per step; the reply dialog shows the real IBKR warning text (HTML-stripped) instead of just a reply ID
- `run_backtest` sandbox errors now surface the real exception type and message (plus available DataFrame columns and the `signal` contract) instead of a redacted "strategy runtime error" — the LLM can no longer self-correct from a blanked message
- `get_analytics` annualizes by the request's actual timeframe instead of always assuming daily bars
- Flex `_get_statement` no longer swallows a `Warn`/error-1019 response as if it were a valid (empty) statement
- `get_market_history` period/bar values are lowercased before the request — IBKR silently mis-serves uppercase periods (e.g. `'6M'` returned ~4 months of data, not 6) and the tool schema itself had been teaching the LLM the wrong case
- `get_trades()` auto-retries an empty first response once — `/iserver/account/trades` has the same two-call subscription warmup as `/iserver/account/orders`; a prior "mobile fills missing" observation was this warmup, not an origin filter
- False "DATA STALE" warning on Flex sync no longer fires on ordinary T+1 lag (newest trade == yesterday); threshold now requires 2+ trading days with no new data
- `_create_alert` correctly detects a 403 response returned as toolkit text (the internal `except IBKRAPIError` branch never fired, since `ClaudeToolkit.execute()` already converts it to text)
- Gate 1 Touch ID policy corrected in-code and in docs to `LAPolicyDeviceOwnerAuthentication` (biometric with system-password fallback, not biometric-only)

### Security
- 5 GitHub CodeQL alerts resolved: least-privilege `permissions: contents: read` added to the CI test job; 3 `py/incomplete-url-substring-sanitization` false positives replaced with structural checks or suppressed with justification
- `DataFrame.eval`/`.query` blocked in the backtest sandbox — both run pandas' own expression engine outside `RestrictedPython`'s AST guards and could reach `sys.modules['os']` for RCE
- `order_id`/`alert_id`/`reply_id` now validated against strict regexes before URL construction — `delete_alert(alert_id="../order/<id>")` previously normalized to `cancel_order`'s exact URL, bypassing Touch ID and the confirmation dialog on live order cancellation
- `_ORDER_ID_RE` tightened from Unicode `\d` (accepted non-ASCII digit code points) to an explicit `[0-9]` class
- Gateway Docker container now binds to `127.0.0.1` explicitly — the prior `-p {port}:{port}` form published on all host interfaces by Docker's default behavior, not loopback-only as documented
- Gateway `conf.yaml` IP allowlist scoped from `192.*`/`172.*` (which matched the full `/8` blocks, including public IPv4 space) to the actual RFC 1918 ranges
- SSRF guard (`scrape_fallback.is_private_host`) now resolves both A and AAAA records via `getaddrinfo` — an IPv6-only private host previously bypassed the guard entirely via `gethostbyname`'s IPv4-only resolution
- `import_flex_file`'s path-boundary check switched from `str.startswith()` to `Path.is_relative_to()` — a sibling directory whose name was a superstring of `.ibkr_core` (e.g. `.ibkr_core_evil`) previously passed the allowlist

### Changed
- `analytics.sortino` migrated to the canonical target-downside-deviation form (Sortino's own definition, computed over all observations, not just below-target ones) — pre-migration Sortino figures are not directly comparable to figures produced after this change
- `claude_tools.py` full audit (design decisions D1–D5): several tool descriptions and behaviors corrected across the 42-tool set

---

## [1.0.0] — 2026-06-27

### Fixed
- `analytics.full_report()` hardcoded `periods=252` — now accepts `periods: int = 252` kwarg; intraday callers now get correct annualised Sharpe/Sortino/Calmar/CAGR
- `ClaudeToolkit.execute()` return type corrected to `tuple[str, None]` — was documented as returning an optional plotly figure but always returned `None`; second element reserved for future figure support
- mypy: 14 type errors resolved across 5 files (see below)
  - Missing `Path` import in `cache.py`
  - Missing `log` logger in `flex_query.py`
  - Bare `dict` / `list[dict]` annotations upgraded to fully typed equivalents
  - `conid` passed as `str` where `int` expected in two `ClaudeToolkit` handlers
  - Untyped lambda replaced with typed `def _has_prices(...)` in market snapshot handler
  - `Credentials.from_authorized_user_file` suppressed with `# type: ignore[no-untyped-call]` (third-party stub gap)
  - `save_crawl` return type narrowed; Drive file IDs wrapped in `str()`
- `__version__` now derived from `importlib.metadata` — single source of truth is `pyproject.toml`; eliminates drift between `__init__.py` and `pyproject.toml`

### Added
- Firecrawl web scraper integration: `firecrawl_search` and `firecrawl_crawl` Claude tools, `FirecrawlClient`, `WebDocsStore` with Drive persistence
- `SQLiteStore.get_market_calendar_context()` — NYSE + CME trading calendar for LLM context-aware scheduling
- `get_market_calendar_context`, `FirecrawlError`, `WebDocsStoreError` exported from `__init__.py`
- SSRF guard on `firecrawl_crawl` — only `https://` URLs with public hostnames accepted
- 484 unit tests (46 new ClaudeToolkit handler tests, 13 GDriveCache Drive path tests)
- Source: URLs on all IBKR Client Portal API docstrings
- `Field(description=...)` on all aliased Pydantic model fields — IDE autocomplete and `model.model_fields` expose IBKR wire-format field names
- `AuthStrategy` Protocol exported from `ibkr_core_mcp.__init__`
- `py.typed` registered in `[tool.setuptools.package-data]`
- Complete IBKR Flex error code table (21 official codes) in `flex_query.py`
- Docstrings with official IBKR CP API source citations on all 76 `IBKRClient` public methods
- Optional `start_date` / `end_date` parameters added to `FlexQueryClient.fetch_trades()`

### Changed
- `plotly` removed from package dependencies — was never used
- Dead HMDS code removed from `client.py`
- `_BROWSER_LOADERS` dict removed from `auth.py` — was mapping each name to itself

### Security
- `store._apply_filters` `time_col` parameter validated against allowlist before SQL interpolation
- Silent exception swallowing replaced with `log.warning(...)` in `flex_query.py` and `claude_tools._run_backtest`
- `WebDocsStore._get_service()` token file written with `0o600` permissions

---

## [Unreleased — earlier]

### Added
- `py.typed` registered in `[tool.setuptools.package-data]`
- Docs-first principle established: all external API behavior must be verified against official documentation before implementation; reference URLs added to `CLAUDE.md`, `README.md`, and inline comments
- Complete IBKR Flex error code table (21 official codes) in `flex_query.py`, sourced from https://www.ibkrguides.com/clientportal/performanceandstatements/flex3error.htm
- `with_retry()` docstring cites official IBKR rate limit policy and documents Retry-After behavior
- Optional `start_date` / `end_date` parameters (`fd` / `td`) added to `FlexQueryClient.fetch_trades()` for date-range overrides
- `_validate_flex_date()` helper in `flex_query.py` enforces YYYYMMDD format

### Fixed
- `ping()` try/except split so `tickle()` errors are no longer silently swallowed
- Drive `market_data/` folder discovery now sorts by `createdTime asc`; warns when duplicates exist
- Account ID regex unified: both `client.py` and `claude_tools.py` now enforce `^[A-Z0-9]{4,12}$`
- `py.typed` moved into `ibkr_core_mcp/` package directory (was at repo root — invisible to pip consumers)
- OS classifiers expanded: Linux and Windows added alongside macOS
- README: `--streaming` flag corrected to `--stream`, git+ install form, model ID updated
- **Flex Web Service endpoint** corrected from `gdcdyn.interactivebrokers.com` to `ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/` — wrong from day one
- **Required `User-Agent: Python/3` header** added to all Flex requests
- **Flex error 1001** correctly documented as transient generation failure (not rate limit)

---

## [0.4.0] — 2026-06-10

### Added
- **MCP server** (`ibkr_core_mcp.mcp_server`): 33 tools + 2 MCP-only alert tools + 3 resources; supports stdio and HTTP/SSE transports
- `--stream` flag for MCP server: enables WebSocket live quotes and price alert delivery
- **Streaming** (`streaming.py`): `IBKRWebSocket`, `LiveQuote` dataclass, `AlertManager`
- Price alerts persisted to SQLite (`price_alerts` table); `add_price_alert` / `get_price_alerts` MCP tools
- `sync_flex_trades` Claude tool for pulling full historical trade history via Flex Query
- `FlexQueryClient` hardens datetime parsing, URL validation, and type annotations
- Drive layout: `market_data/` subfolder auto-created inside `GOOGLE_DRIVE_FOLDER_ID`; `db/` subfolder for claudia.db
- `IBKRWebSocket` localhost guard — refuses non-localhost URLs at connect time
- 170 unit tests passing

### Security
- Full security audit (2026-05-25): all Critical/High/Medium findings resolved
- `SECURITY.md` added with responsible disclosure policy and threat model

---

## [0.3.0] — 2026-05-28

### Added
- **Touch ID gate** (`human_auth.py`): `require_touch_id()` via `pyobjc-framework-LocalAuthentication`; fingerprint-only, no password fallback, 60 s timeout
- **Confirmation dialogs** (`order_confirm.py`): tkinter modal for place/modify/cancel/reply; mouse click required, Enter key does not confirm
- Two-gate enforcement on all order write methods: `place_order`, `modify_order`, `cancel_order`, `reply_order`
- `HumanAuthError` exception exported from public surface
- Read-only endpoints explicitly ungated: `get_order_preview`, `get_live_orders`, `get_order_status`, alert endpoints

### Security
- Order write path requires fingerprint + visual confirmation before any IBKR network call
- `CLAUDE.md` security section documents two-gate architecture and contributor rules

---

## [0.2.0] — 2026-05-22

### Added
- **Technical indicators** (`indicators.py`): 14 pure-function indicators — SMA, EMA, RSI, MACD, Bollinger Bands, ATR, Stochastic, Williams %R, Keltner Channels, VWAP, OBV, Volume SMA, Volume Ratio; `add_all()` convenience
- **Portfolio analytics** (`analytics.py`): Sharpe, Sortino, Calmar, CAGR, max drawdown, max drawdown duration, win rate, profit factor, avg win/loss ratio, `full_report()`
- **Backtesting sandbox** (`backtest.py`): `RestrictedPython` executor; no network, no file I/O, no `os` access; `BacktestResult` dataclass
- **PineScript generation** (`pinescript.py`): v5 strategy and indicator scripts from backtest results or signal series; injection-safe `_sanitize()` helper
- **Pydantic v2 models** (`models.py`): `Contract`, `Position`, `Trade`, `Order`, `AccountSummary`, `Notification`; `bars_to_dataframe()` OHLCV normalizer
- `ClaudeToolkit` expanded to 19 tools including `add_indicators`, `run_backtest`, `generate_pinescript`, `get_analytics`
- `FlexQueryClient` for full historical trade data via IBKR Flex Web Service (6-day API limit bypass)

---

## [0.1.0] — 2026-05-15

### Added
- **`IBKRClient`** with all 79 IBKR Client Portal API endpoints
- **`GDriveCache`**: Google Drive parquet cache for OHLCV market data; manifest with TTL
- **`SQLiteStore`**: trades, position snapshots, signals, backtest results, log entries
- **`ClaudeToolkit`**: 15 Claude tool definitions + handlers (read-only, no order execution)
- **`GatewayManager`**: Docker lifecycle management for IBKR Client Portal Gateway
- **`Config`**: dataclass loaded from environment variables; `from_env()` factory
- Auth strategies: `BrowserCookieAuth` (Chrome cookie), `TokenAuth`, `NoAuth`
- Custom exception hierarchy: `IBKRCoreError` → 12 typed subclasses
- Token-bucket rate limiter + exponential backoff on 429 (`rate_limiter.py`)
- `py.typed` marker (PEP 561)
- Full unit test suite (no gateway required for unit tests)

---

[Unreleased]: https://github.com/stephus182/ibkr_core_mcp/compare/v1.2.2...HEAD
[1.2.2]: https://github.com/stephus182/ibkr_core_mcp/compare/v1.2.1...v1.2.2
[1.2.1]: https://github.com/stephus182/ibkr_core_mcp/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/stephus182/ibkr_core_mcp/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/stephus182/ibkr_core_mcp/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/stephus182/ibkr_core_mcp/compare/v0.4.0...v1.0.0
[0.4.0]: https://github.com/stephus182/ibkr_core_mcp/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/stephus182/ibkr_core_mcp/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/stephus182/ibkr_core_mcp/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/stephus182/ibkr_core_mcp/releases/tag/v0.1.0
