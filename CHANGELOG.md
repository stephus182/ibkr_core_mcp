# Changelog

All notable changes to `ibkr_core_mcp` are documented here.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

### Added
- `AuthStrategy` Protocol exported from `ibkr_core_mcp.__init__`
- `py.typed` registered in `[tool.setuptools.package-data]`
- Docs-first principle established: all external API behavior must be verified against official documentation before implementation; reference URLs added to `CLAUDE.md`, `README.md`, and inline comments
- Complete IBKR Flex error code table (21 official codes) in `flex_query.py`, sourced from https://www.ibkrguides.com/clientportal/performanceandstatements/flex3error.htm
- Docstrings with official IBKR CP API source citations on all 76 `IBKRClient` public methods; `client.py` now self-documents its behavior directly in code
- `with_retry()` docstring cites official IBKR rate limit policy and documents Retry-After behavior; 100% coverage confirmed
- Optional `start_date` / `end_date` parameters (`fd` / `td`) added to `FlexQueryClient.fetch_trades()` for date-range overrides; format YYYYMMDD, max 365 days per official docs
- `_validate_flex_date()` helper in `flex_query.py` enforces YYYYMMDD format with official source citation
- 5 new tests for `FlexQueryClient` date params and `_parse_flex_datetime` date-only path; total 363 unit tests

### Fixed
- `ping()` try/except split so `tickle()` errors are no longer silently swallowed
- Drive `market_data/` folder discovery now sorts by `createdTime asc`; warns when duplicates exist
- Stale Drive folder handle cleared on any Drive exception in `load()` and `save()`
- `_fetch_market_data()` in `ClaudeToolkit` uses canonical `bars_to_dataframe()` to prevent HMDS schema drift in cached parquet
- Account ID regex unified: both `client.py` and `claude_tools.py` now enforce `^[A-Z0-9]{4,12}$`
- `py.typed` moved into `ibkr_core_mcp/` package directory (was at repo root — invisible to pip consumers)
- OS classifiers expanded: Linux and Windows added alongside macOS
- `websockets` import now raises a clear `ModuleNotFoundError` with install instructions when missing
- README: `--streaming` flag corrected to `--stream`, `pip install ibkr_core_mcp` replaced with git+ form, model ID updated to `claude-sonnet-4-6`, analytics description corrected, `IBKR_SQLITE_PATH` marked optional
- **Flex Web Service endpoint** corrected from `gdcdyn.interactivebrokers.com/Universal/servlet/FlexStatementService.SendRequest` to `ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/SendRequest` — wrong host and path from day one; source: https://www.ibkrguides.com/clientportal/performanceandstatements/flex3.htm
- **Required `User-Agent: Python/3` header** added to all Flex requests (per official documentation; requests without this header are rejected silently)
- **Flex error 1001** correctly documented as transient generation failure (retry) — was previously mislabeled "rate limit" then "auth failure"; source: https://www.ibkrguides.com/clientportal/performanceandstatements/flex3error.htm; actual auth errors are 1014 (invalid query) and 1015 (invalid token)

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
