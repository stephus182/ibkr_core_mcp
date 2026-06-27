# Changelog

All notable changes to `ibkr_core_mcp` are documented here.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [1.0.0] — unreleased

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

[Unreleased]: https://github.com/stephus182/ibkr_core_mcp/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/stephus182/ibkr_core_mcp/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/stephus182/ibkr_core_mcp/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/stephus182/ibkr_core_mcp/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/stephus182/ibkr_core_mcp/releases/tag/v0.1.0
