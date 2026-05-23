# ibkr_core_mcp — Design Specification
**Date:** 2026-05-22  
**Author:** Stephane Menard + Claude Sonnet 4.6  
**Status:** Approved for implementation

---

## 1. Purpose

`ibkr_core_mcp` is a standalone, pip-installable Python package that provides a complete, typed interface to Interactive Brokers' Client Portal API, a Google Drive parquet cache, a SQLite trade/signal store, a RestrictedPython backtest sandbox, technical indicators, portfolio analytics, PineScript generation utilities, and a ready-made Claude AI tool layer.

Any project — trading dashboards, ML pipelines, order management UIs, PineScript generators — installs this single package and gets the full IBKR platform without rebuilding.

```
pip install git+https://github.com/stephus182/ibkr_core_mcp.git
```

---

## 2. Scope

### In scope (this package)
- All 79 IBKR Client Portal API endpoints (read-only + query POST endpoints)
- Google Drive parquet cache for market data
- SQLite store for trades, signals, backtest results, position snapshots
- RestrictedPython backtest sandbox
- Technical indicators computed from cached OHLCV data
- Portfolio and strategy performance analytics
- Claude AI tool definitions and handlers (portable across any Claude-powered UI)
- PineScript v5 generation from indicators and strategy parameters
- Auth abstraction (browser cookie, explicit token)
- Rate limiting and retry logic
- Pydantic typed models for all IBKR responses
- Custom exception hierarchy

### Out of scope (future — separate project)
- Order placement, modification, cancellation
- Alert and watchlist write operations
- Any UI layer (Streamlit, web, CLI)
- Model training or ML inference

---

## 3. Repository Structure

```
ibkr_core_mcp/                    ← git repo root
├── ibkr_core_mcp/                ← installable package
│   ├── __init__.py               # Public API surface
│   ├── auth.py                   # Auth strategies
│   ├── client.py                 # All IBKR API endpoints
│   ├── models.py                 # Pydantic schemas
│   ├── exceptions.py             # Custom exception hierarchy
│   ├── cache.py                  # Google Drive parquet cache
│   ├── store.py                  # SQLite store
│   ├── backtest.py               # RestrictedPython sandbox
│   ├── indicators.py             # Technical indicators
│   ├── analytics.py              # Performance metrics
│   ├── claude_tools.py           # Claude tool definitions + handlers
│   ├── pinescript.py             # PineScript v5 generation
│   ├── rate_limiter.py           # Retry / throttle
│   └── config.py                 # Config loading
├── tests/
│   ├── conftest.py
│   ├── test_client.py
│   ├── test_cache.py
│   ├── test_store.py
│   ├── test_backtest.py
│   ├── test_indicators.py
│   ├── test_analytics.py
│   └── test_pinescript.py
├── docs/
│   └── api/                      # Per-module API reference
├── examples/
│   ├── fetch_aapl.py
│   ├── run_backtest.py
│   └── generate_pinescript.py
├── pyproject.toml
├── README.md
├── CLAUDE.md
└── py.typed                      # PEP 561 — enables mypy/pyright in consumers
```

---

## 4. Installation and Configuration

### Install
```bash
# Latest from GitHub
pip install git+https://github.com/stephus182/ibkr_core_mcp.git

# Pinned version (recommended for production)
pip install git+https://github.com/stephus182/ibkr_core_mcp.git@v0.1.0

# Editable local dev
pip install -e /path/to/ibkr_core_mcp
```

### Environment variables (`.env` in the consuming project)
```
IBKR_GATEWAY_URL=https://localhost:5055/v1/api
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_DRIVE_FOLDER_ID=1abc...
IBKR_SQLITE_PATH=~/.ibkr_core/store.db     # optional, defaults here
```

### Minimal usage
```python
from ibkr_core_mcp import IBKRClient, GDriveCache, SQLiteStore
from ibkr_core_mcp.config import Config

cfg = Config.from_env()                    # reads .env or environment
client = IBKRClient(cfg)
cache = GDriveCache(cfg)
store = SQLiteStore(cfg)
```

---

## 5. Module Design

### 5.1 `config.py`
Loads all configuration from environment variables. Single `Config` dataclass passed into every module — no module reads `.env` itself.

```python
@dataclass
class Config:
    gateway_url: str          # IBKR_GATEWAY_URL
    anthropic_api_key: str    # ANTHROPIC_API_KEY
    gdrive_folder_id: str     # GOOGLE_DRIVE_FOLDER_ID
    sqlite_path: Path         # IBKR_SQLITE_PATH
    gdrive_token_file: Path   # GDRIVE_TOKEN_FILE
    gdrive_credentials_file: Path

    @classmethod
    def from_env(cls, dotenv_path: str | None = None) -> "Config": ...
```

---

### 5.2 `exceptions.py`
Custom exception hierarchy. All package errors inherit from `IBKRCoreError` so callers can catch broadly or narrowly.

```
IBKRCoreError
├── IBKRAuthError          # 401, session expired, cookies not found
├── IBKRRateLimitError     # 429, too many requests
├── IBKRAPIError           # Other gateway HTTP errors
├── CacheError
│   ├── CacheMissError
│   └── CacheWriteError
├── StoreError
├── BacktestError
│   ├── BacktestSyntaxError
│   └── BacktestRuntimeError
└── ConfigError
```

---

### 5.3 `auth.py`
Pluggable auth strategies. Decouples authentication from the IBKR client so ML batch jobs, headless servers, and interactive dashboards can each use the right strategy.

```python
class AuthStrategy(Protocol):
    def apply(self, session: requests.Session) -> None: ...

class BrowserCookieAuth:
    """Reads Chrome's cookie store for localhost (macOS/Linux/Windows)."""
    def apply(self, session: requests.Session) -> None: ...

class TokenAuth:
    """Injects a pre-obtained session token or cookie string."""
    def __init__(self, cookie_string: str): ...
    def apply(self, session: requests.Session) -> None: ...

class NoAuth:
    """No-op — for testing against a pre-authenticated session."""
    def apply(self, session: requests.Session) -> None: ...
```

`IBKRClient` accepts any `AuthStrategy`. Default is `BrowserCookieAuth`.

---

### 5.4 `models.py`
Pydantic v2 models for all IBKR API response types. Ensures downstream projects get typed, validated data — not raw dicts.

```python
# Core primitives
class OHLCVBar(BaseModel): ...          # t, open, high, low, close, volume
class Contract(BaseModel): ...          # conid, symbol, secType, exchange, currency
class Position(BaseModel): ...          # conid, symbol, position, mktPrice, mktValue, unrealPnl, realizedPnl
class Trade(BaseModel): ...             # orderId, execId, time, symbol, side, qty, price, commission
class Order(BaseModel): ...             # orderId, status, symbol, side, qty, price, orderType
class AccountSummary(BaseModel): ...    # netLiquidation, totalCashValue, unrealizedPnL, realizedPnL
class Ledger(BaseModel): ...            # currency, cashBalance, settledCash, accruals
class Allocation(BaseModel): ...        # byAssetClass, byIndustry, byCategory

# Portfolio Analyst
class PAPerformance(BaseModel): ...     # nav, returns, dates
class PATransaction(BaseModel): ...     # date, type, amount, symbol

# Options
class OptionChain(BaseModel): ...       # symbol, expirations, strikes
class ContractInfo(BaseModel): ...      # full contract details + trading rules

# Scanner
class ScannerResult(BaseModel): ...    # conid, symbol, description, score

# FYI
class Notification(BaseModel): ...     # id, date, title, body, isRead

# Backtest
class BacktestResult(BaseModel): ...   # symbol, strategy_name, total_return, sharpe, sortino, max_drawdown, num_trades, win_rate, equity_curve (pd.DataFrame, excluded from JSON)
```

---

### 5.5 `rate_limiter.py`
Transparent request throttle and retry. Wraps the `requests.Session` — callers never think about rate limits.

```python
class RateLimiter:
    """Token-bucket rate limiter + exponential backoff on 429/503."""
    def __init__(self, requests_per_second: float = 5.0): ...

# Decorator for client methods:
@rate_limited
def get_market_data_history(...): ...
```

- Default: 5 req/s (IBKR guideline)
- On 429: exponential backoff with jitter, max 3 retries
- On 503: retry once after 2s
- Raises `IBKRRateLimitError` if retries exhausted

---

### 5.6 `client.py`
The core IBKR API wrapper. All 79 endpoints. Read-only and query-POST endpoints only — no order placement, no state-modifying alerts/watchlists (reserved for a future `ibkr_orders_mcp` package).

#### Session management
```python
class IBKRClient:
    def __init__(self, config: Config, auth: AuthStrategy | None = None): ...
    def ping(self) -> bool: ...
    def reauthenticate(self) -> bool: ...
```

#### Market Data (10 endpoints)
```python
def get_market_history(conid, period, bar, outside_rth) -> list[OHLCVBar]: ...
def get_market_snapshot(conids, fields) -> list[dict]: ...
def get_market_data_fields(self) -> dict: ...
def get_market_data_periods(self) -> dict: ...
def get_market_data_bars(self) -> dict: ...
def get_hmds_history(conid, period, bar, outside_rth) -> list[OHLCVBar]: ...
```

#### Contract / Security Definition (13 endpoints)
```python
def search_contract(symbol, sec_type) -> list[Contract]: ...
def get_contract_info(conid) -> ContractInfo: ...
def get_contract_info_and_rules(conid) -> ContractInfo: ...
def get_contract_algos(conid) -> list[dict]: ...
def get_secdef_info(conid) -> dict: ...
def get_option_strikes(conid, sec_type, month, exchange) -> list[float]: ...
def get_option_chain(symbol, exchange, currency) -> OptionChain: ...
def get_bond_filters(symbol, issue_id) -> dict: ...
def get_futures(symbols) -> list[Contract]: ...
def get_stocks(symbols) -> list[Contract]: ...
def get_trading_schedule(asset_class, symbol, exchange, exchange_filter) -> dict: ...
def get_secdef(conids) -> list[dict]: ...
def get_currency_pairs(currency) -> list[dict]: ...
```

#### Portfolio (13 endpoints)
```python
def get_accounts(self) -> list[dict]: ...
def get_subaccounts(self) -> list[dict]: ...
def get_account_meta(account_id) -> dict: ...
def get_account_summary(account_id) -> AccountSummary: ...
def get_account_ledger(account_id) -> dict[str, Ledger]: ...
def get_account_allocation(account_id) -> Allocation: ...
def get_positions(account_id, page=0) -> list[Position]: ...
def get_positions_by_conid(conid) -> list[Position]: ...
def get_position(account_id, conid) -> Position: ...
def get_combo_positions(account_id) -> list[dict]: ...
def get_portfolio_allocation(account_ids) -> dict: ...
def invalidate_positions_cache(account_id) -> None: ...
```

#### Order Monitoring — read-only (3 endpoints)
```python
def get_live_orders(self) -> list[Order]: ...
def get_order_status(order_id) -> Order: ...
def get_trades(self) -> list[Trade]: ...
```

#### Portfolio Analyst (3 endpoints)
```python
def get_pa_periods(account_ids) -> list[str]: ...
def get_pa_performance(account_ids, period) -> PAPerformance: ...
def get_pa_transactions(account_ids, period) -> list[PATransaction]: ...
```

#### Scanner (3 endpoints)
```python
def get_scanner_params(self) -> dict: ...
def run_iserver_scanner(params: dict) -> list[ScannerResult]: ...
def run_hmds_scanner(params: dict) -> list[ScannerResult]: ...
```

#### FYI / Notifications (8 endpoints — read-only)
```python
def get_notifications(max=10) -> list[Notification]: ...
def get_unread_count(self) -> int: ...
def get_delivery_options(self) -> dict: ...
```

#### Session (read-only)
```python
def get_auth_status(self) -> dict: ...
def tickle(self) -> bool: ...
def validate_sso(self) -> dict: ...
```

---

### 5.7 `cache.py`
Google Drive parquet cache for OHLCV market data. Shared across machines. Identical to current `gdrive_cache.py` but refactored to accept `Config`, use `models.OHLCVBar`, and raise `CacheError` subclasses.

```python
class GDriveCache:
    def __init__(self, config: Config): ...
    def check(self, symbol, timeframe, period, end) -> bool: ...
    def load(self, symbol, timeframe, period, end) -> pd.DataFrame: ...
    def save(self, df, symbol, timeframe, period, end) -> None: ...
    def list_cached(self) -> list[dict]: ...
    def delete(self, symbol, timeframe, period, end) -> None: ...
```

Key: `{SYMBOL}_{TIMEFRAME}_{PERIOD}_{END}` → `manifest.json` in Drive folder.  
Manifest TTL: 60s in-memory to avoid redundant Drive API calls.

---

### 5.8 `store.py`
SQLite store for structured, persistent data that the Drive cache doesn't cover.

```python
class SQLiteStore:
    def __init__(self, config: Config): ...

    # Trades (IBKR only returns last 6 days — this persists indefinitely)
    def upsert_trades(self, trades: list[Trade]) -> None: ...
    def get_trades(self, symbol=None, start=None, end=None) -> list[Trade]: ...

    # Positions snapshot (timestamped)
    def snapshot_positions(self, positions: list[Position]) -> None: ...
    def get_position_history(self, symbol=None, start=None, end=None) -> pd.DataFrame: ...

    # Backtest results
    def save_backtest(self, result: BacktestResult) -> int: ...
    def get_backtests(self, symbol=None, strategy=None) -> list[BacktestResult]: ...

    # Signal log (for ML / automation)
    def log_signal(self, symbol, signal_type, value, metadata=None) -> None: ...
    def get_signals(self, symbol=None, start=None, end=None) -> pd.DataFrame: ...
```

Schema auto-created on first use. Uses WAL mode for concurrent read safety.

---

### 5.9 `backtest.py`
RestrictedPython sandbox executor. Identical to current implementation, refactored to use `models.BacktestResult` and raise `BacktestError` subclasses.

```python
# BacktestResult is defined in models.py — imported here for reference
# class BacktestResult(BaseModel):
#     symbol, strategy_name, total_return, sharpe, sortino,
#     max_drawdown, num_trades, win_rate, equity_curve (pd.DataFrame)

def run_backtest(code: str, df: pd.DataFrame, strategy_name="") -> BacktestResult: ...
```

Strategy code contract:
- Receives `df` with columns: `open`, `high`, `low`, `close`, `volume`
- Must set `df['signal']` = 1 (long), 0 (flat), -1 (short)
- Allowed imports: `pandas`, `numpy`, `plotly`
- No network, no file I/O, no `os`

---

### 5.10 `indicators.py`
Technical indicators computed on pandas DataFrames. Pure functions — no side effects, no IBKR calls.

```python
# Trend
def sma(df, period=20) -> pd.Series: ...
def ema(df, period=20) -> pd.Series: ...
def macd(df, fast=12, slow=26, signal=9) -> pd.DataFrame: ...   # macd, signal, histogram
def vwap(df) -> pd.Series: ...

# Momentum
def rsi(df, period=14) -> pd.Series: ...
def stochastic(df, k=14, d=3) -> pd.DataFrame: ...
def williams_r(df, period=14) -> pd.Series: ...

# Volatility
def bollinger_bands(df, period=20, std=2) -> pd.DataFrame: ...  # upper, mid, lower
def atr(df, period=14) -> pd.Series: ...
def keltner_channels(df, period=20, atr_mult=2) -> pd.DataFrame: ...

# Volume
def obv(df) -> pd.Series: ...
def volume_sma(df, period=20) -> pd.Series: ...
def volume_ratio(df, period=20) -> pd.Series: ...

# All indicators — returns df with all columns added
def add_all(df) -> pd.DataFrame: ...
```

All functions take a DataFrame with standard OHLCV columns and return a Series or DataFrame with the same index.

---

### 5.11 `analytics.py`
Performance and risk metrics. Works on both backtest equity curves and real trade history.

```python
# From equity curve (pd.Series of returns)
def sharpe(returns, risk_free=0.0, periods=252) -> float: ...
def sortino(returns, risk_free=0.0, periods=252) -> float: ...
def calmar(returns, periods=252) -> float: ...
def max_drawdown(returns) -> float: ...
def max_drawdown_duration(returns) -> int: ...   # bars
def cagr(returns, periods=252) -> float: ...

# From trade list
def win_rate(trades: list[Trade]) -> float: ...
def profit_factor(trades: list[Trade]) -> float: ...
def avg_win_loss_ratio(trades: list[Trade]) -> float: ...
def trade_summary(trades: list[Trade]) -> dict: ...

# Full report — returns dict of all metrics
def full_report(returns: pd.Series, trades: list[Trade] | None = None) -> dict: ...
```

---

### 5.12 `claude_tools.py`
Ready-made Claude tool definitions and handlers. Any Claude-powered project imports this and immediately has a full IBKR research assistant — no tool wiring needed.

```python
class ClaudeToolkit:
    def __init__(self, client: IBKRClient, cache: GDriveCache,
                 store: SQLiteStore, config: Config): ...

    # Tool schema list — pass directly to anthropic messages.create(tools=...)
    @property
    def tools(self) -> list[dict]: ...

    # Execute a tool call from Claude's response
    def execute(self, name: str, inputs: dict) -> tuple[str, Any]: ...
                # returns (text_result, optional_plotly_fig)
```

#### Tools exposed to Claude:
| Tool | Description |
|---|---|
| `fetch_market_data` | Fetch OHLCV from IBKR or Drive cache |
| `check_cache` | Check Drive manifest |
| `get_positions` | All open positions |
| `get_account_summary` | Net liq, cash, P&L |
| `get_trades` | Recent trade history (IBKR + SQLite) |
| `get_live_orders` | Open orders |
| `get_pa_performance` | NAV performance over period |
| `get_pa_transactions` | Transaction history |
| `get_ledger` | Cash and currency balances |
| `get_allocation` | Portfolio allocation breakdown |
| `get_contract_info` | Full contract details |
| `get_option_chain` | Options chain for symbol |
| `run_scanner` | Market scanner |
| `get_notifications` | IBKR FYI notifications |
| `add_indicators` | Compute technical indicators on cached data |
| `run_backtest` | Execute strategy in sandbox |
| `generate_pinescript` | Generate PineScript v5 from strategy |
| `get_analytics` | Full performance report |

---

### 5.13 `pinescript.py`
Generates valid PineScript v5 scripts from strategy parameters or indicator configurations. Output can be pasted directly into TradingView.

```python
def strategy_from_signals(
    name: str,
    signals: pd.Series,        # index=datetime, values=1/0/-1
    symbol: str,
    timeframe: str,
) -> str: ...                  # returns PineScript v5 string

def indicator_script(
    name: str,
    indicators: list[str],     # e.g. ["rsi", "macd", "bollinger_bands"]
    params: dict,
) -> str: ...

def strategy_from_backtest(
    backtest_result: BacktestResult,
    df: pd.DataFrame,
) -> str: ...
```

Generated scripts include: study/strategy declaration, input parameters (user-configurable in TradingView), plot statements for each indicator/signal, strategy entry/exit calls.

---

## 6. Public API (`__init__.py`)

The package exports a clean, flat surface. Callers never need to know internal module paths.

```python
from ibkr_core_mcp import (
    # Core
    IBKRClient,
    GDriveCache,
    SQLiteStore,
    Config,
    ClaudeToolkit,

    # Auth
    BrowserCookieAuth,
    TokenAuth,

    # Models
    OHLCVBar, Contract, Position, Trade, Order,
    AccountSummary, Ledger, Allocation, ContractInfo,
    PAPerformance, PATransaction, OptionChain,
    ScannerResult, Notification, BacktestResult,

    # Exceptions
    IBKRCoreError, IBKRAuthError, IBKRRateLimitError,
    IBKRAPIError, CacheError, StoreError, BacktestError,

    # Functional modules (used directly)
    indicators,
    analytics,
    pinescript,
)
```

---

## 7. Data Flow

### Market data fetch (cache-first)
```
Caller: cache.check(symbol, timeframe, period, end)
  HIT  → cache.load() → pd.DataFrame
  MISS → client.search_contract(symbol)
           → client.get_market_history(conid, ...)
           → cache.save(df)
           → pd.DataFrame
```

### Claude tool call (inside any Claude-powered app)
```
toolkit = ClaudeToolkit(client, cache, store, config)
# Pass to Claude:
tools=toolkit.tools
# When Claude responds with tool_use:
text, fig = toolkit.execute(tool_name, tool_inputs)
```

### Backtest + PineScript
```
df = cache.load(symbol, timeframe, period, end)
df = indicators.add_all(df)
result = run_backtest(strategy_code, df)
store.save_backtest(result)
script = pinescript.strategy_from_backtest(result, df)
```

---

## 8. Error Handling

All public methods raise typed exceptions from `exceptions.py`. No bare `dict` errors, no string error codes.

```python
try:
    df = cache.load("AAPL", "1D", "1Y", "2026-05-22")
except CacheMissError:
    df = client.get_market_history(...)
except IBKRAuthError:
    # session expired — re-authenticate
except IBKRRateLimitError as e:
    # already retried internally — surface to caller
```

The `rate_limiter.py` handles 429/503 transparently before raising `IBKRRateLimitError`.

---

## 9. Testing Strategy

All tests in `tests/`. Two categories:

**Unit tests** (no network, no Drive, no gateway):
- `test_indicators.py` — all indicator functions with synthetic data
- `test_analytics.py` — all metrics with known return series
- `test_backtest.py` — sandbox execution, error cases, NaN handling
- `test_pinescript.py` — script generation, valid PineScript v5 syntax
- `test_models.py` — Pydantic validation, edge cases

**Integration tests** (require live IBKR gateway):
- `test_client.py` — marked `@pytest.mark.integration`
- `test_cache.py` — requires `GOOGLE_DRIVE_FOLDER_ID`
- `test_store.py` — SQLite, uses temp file

Run unit tests only: `pytest -m "not integration"`  
Run all: `pytest` (requires `.env` with live credentials)

---

## 10. `pyproject.toml` (key fields)

```toml
[project]
name = "ibkr_core_mcp"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "requests>=2.31",
    "urllib3>=2.0",
    "pydantic>=2.0",
    "anthropic>=0.28",
    "pandas>=2.2",
    "numpy>=1.26",
    "plotly>=5.22",
    "RestrictedPython>=7.0",
    "pyarrow>=16.0",
    "google-api-python-client>=2.130",
    "google-auth-httplib2>=0.2",
    "google-auth-oauthlib>=1.2",
    "python-dotenv>=1.0",
    "browser-cookie3>=0.19",
]

[project.optional-dependencies]
dev = ["pytest", "pytest-mock", "mypy", "ruff"]
```

---

## 11. CLAUDE.md (for the ibkr_core_mcp repo)

The `CLAUDE.md` in the new repo will document:
- How to set up the dev environment (`pip install -e ".[dev]"`)
- How to run unit vs integration tests
- How to add a new IBKR endpoint (pattern: add to `client.py`, add Pydantic model, add Claude tool, add test)
- Auth setup (Chrome + IBKR gateway on same machine)
- How to publish a new version (`git tag v0.x.x && git push --tags`)
- Package import conventions

---

## 12. Migration from Current Dashboard

The existing `IBKR_mcp` dashboard repo will:
1. Add `ibkr_core_mcp` to its `requirements.txt`
2. Replace `from tools import ibkr_client` → `from ibkr_core_mcp import IBKRClient`
3. Replace `from tools import gdrive_cache` → `from ibkr_core_mcp import GDriveCache`
4. Replace `from tools import backtest` → `from ibkr_core_mcp import run_backtest`
5. Replace tool definitions in `chat.py` → `ClaudeToolkit(client, cache, store, cfg).tools`
6. Keep `components/` (Streamlit UI) — unchanged, dashboard-specific

The dashboard becomes a thin UI layer: layout + Streamlit rendering. All business logic lives in the package.

---

## 13. Future Projects That Use This Package

| Project | Imports |
|---|---|
| Streamlit research dashboard (current) | `IBKRClient`, `GDriveCache`, `ClaudeToolkit`, `indicators`, `run_backtest`, `pinescript` |
| Order management UI | `IBKRClient` (future order endpoints), `SQLiteStore`, `ClaudeToolkit` |
| ML feature pipeline | `IBKRClient`, `GDriveCache`, `SQLiteStore`, `indicators` |
| PineScript generator | `IBKRClient`, `GDriveCache`, `indicators`, `pinescript` |
| Automated scanner/alert bot | `IBKRClient`, `SQLiteStore`, `analytics`, `notifier` (future) |

---

## 14. Implementation Phases

### Phase 1 — Package scaffold + core (Week 1)
- New GitHub repo `ibkr_core_mcp`
- `pyproject.toml`, `py.typed`, `CLAUDE.md`
- `config.py`, `exceptions.py`, `models.py`, `auth.py`, `rate_limiter.py`
- `client.py` — all 79 endpoints (starting from current `ibkr_client.py`)
- Unit test skeleton

### Phase 2 — Cache, store, backtest (Week 1-2)
- `cache.py` (refactored from current `gdrive_cache.py`)
- `store.py` (SQLite — new)
- `backtest.py` (refactored from current)
- Integration tests for cache + store

### Phase 3 — Analytics, indicators, PineScript (Week 2)
- `indicators.py`
- `analytics.py`
- `pinescript.py`
- Unit tests for all

### Phase 4 — Claude tools + migration (Week 2-3)
- `claude_tools.py` — all 18 tools
- Migrate current dashboard to import from package
- End-to-end test: dashboard → package → IBKR → Drive → SQLite

### Phase 5 — Documentation + publish (Week 3)
- `README.md` with quickstart
- `docs/api/` per-module reference
- `examples/` scripts
- Tag `v0.1.0`
