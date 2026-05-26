# ibkr_core_mcp — Developer Guide

Standalone pip-installable Python package providing a complete IBKR Client Portal API client, Google Drive parquet cache, SQLite store, backtest sandbox, technical indicators, portfolio analytics, Claude AI tool layer, and PineScript generation utilities.

**Design spec:** `docs/specs/2026-05-22-ibkr-core-mcp-design.md`

---

## Install

```bash
# From GitHub (any consuming project)
pip install git+https://github.com/stephus182/ibkr_core_mcp.git

# Pinned version
pip install git+https://github.com/stephus182/ibkr_core_mcp.git@v0.1.0

# Local editable dev
pip install -e /Users/steph/Claude_Projects/ibkr_core_mcp
```

---

## Dev Setup

```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

**Python:** 3.11+ required. Use Homebrew Python on macOS (`brew install python`).  
**Package manager:** `brew install` for macOS tooling, `pip install -e ".[dev]"` for Python deps.

---

## Environment Variables

Create `.env` in any consuming project (not in this repo):

```
IBKR_GATEWAY_URL=https://localhost:5055/v1/api
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_DRIVE_FOLDER_ID=1abc...xyz
IBKR_SQLITE_PATH=~/.ibkr_core/store.db
GDRIVE_TOKEN_FILE=~/.ibkr_core/token.json
GDRIVE_CREDENTIALS_FILE=~/.ibkr_core/credentials.json
```

Never commit `.env`, `token.json`, or `credentials.json`.

---

## Package Structure

```
ibkr_core_mcp/
├── __init__.py        # Public API — import everything from here
├── auth.py            # Auth strategies: BrowserCookieAuth, TokenAuth, NoAuth
├── client.py          # All 79 IBKR Client Portal API endpoints
├── models.py          # Pydantic v2 schemas for all response types
├── exceptions.py      # Custom exception hierarchy (IBKRCoreError → subclasses)
├── cache.py           # Google Drive parquet cache (market data, shared cross-machine)
├── store.py           # SQLite store (trades, signals, backtest results, positions)
├── backtest.py        # RestrictedPython sandbox executor
├── indicators.py      # Technical indicators (RSI, MACD, BB, ATR, VWAP, OBV, ...)
├── analytics.py       # Performance metrics (Sharpe, Sortino, Calmar, drawdown, ...)
├── claude_tools.py    # Claude tool definitions + handlers (18 tools, portable)
├── pinescript.py      # PineScript v5 generation from strategies and indicators
├── rate_limiter.py    # Token-bucket rate limiter + exponential backoff on 429
└── config.py          # Config dataclass loaded from environment variables
```

---

## IBKR API

### Setup

```python
from ibkr_core_mcp import IBKRClient, GDriveCache, SQLiteStore, Config

cfg = Config.from_env()          # reads .env
client = IBKRClient(cfg)
cache  = GDriveCache(cfg)
store  = SQLiteStore(cfg)
```

---

### Security & Fingerprint Authentication

**ALL order write operations require two sequential human validations. There is no bypass.**

Every call to `place_order`, `modify_order`, `cancel_order`, or `reply_order` must pass both gates — in order — before any network call reaches IBKR:

| Gate | Mechanism | Behaviour |
|---|---|---|
| **Gate 1 — Touch ID** | Apple `LocalAuthentication` (`LAPolicyDeviceOwnerAuthenticationWithBiometrics`) | Fingerprint only — no password fallback. 60-second timeout. |
| **Gate 2 — Visual confirmation** | tkinter modal dialog with full order details + live-order disclaimer | Explicit mouse click required. Enter key does not confirm. |

If either gate fails (denied, timeout, cancelled), `HumanAuthError` is raised immediately and the IBKR endpoint is never contacted.

**Gated endpoints:**

| Method | Gates |
|---|---|
| `place_order` | Touch ID → confirm dialog |
| `modify_order` | Touch ID → modify dialog |
| `cancel_order` | Touch ID → cancel dialog |
| `reply_order` | Touch ID → reply dialog |

**Explicitly ungated (read-only, no execution risk):**

| Method | Reason |
|---|---|
| `get_order_preview` | IBKR `whatif` — simulates, never executes |
| `get_live_orders` / `get_order_status` | Read-only |
| `create_alert` / `delete_alert` / `activate_alert` | Price notifications, not order execution |

**Rules for contributors:**

- Never add a bypass flag, session cache, or fallback to `require_touch_id` or any dialog function.
- Never move the gates out of `IBKRClient` — enforcement must be at the innermost call site.
- Never add password/PIN fallback — `LAPolicyDeviceOwnerAuthenticationWithBiometrics` is the required policy.
- Any PR that weakens these gates will be rejected.

---

### Gateway Authentication & Session

The IBKR Client Portal Gateway must run on the **same machine** as the browser used to authenticate. No cloud deployment possible.

`BrowserCookieAuth` (default) reads Chrome's cookie store for `localhost`. On first use:

1. Start the gateway: `docker compose up` in the IB_MCP repo
2. Open `https://localhost:5055` in Chrome
3. Log in with IBKR credentials + 2FA (approve push notification on phone)
4. Wait for "Client login succeeds" in browser
5. The package reads the session cookie automatically

For headless use (ML batch jobs), pass a pre-extracted cookie string:
```python
from ibkr_core_mcp import IBKRClient, TokenAuth, Config

client = IBKRClient(Config.from_env(), auth=TokenAuth("cookie_string_here"))
```

**Session constraints:**
- Session expires without activity — call `client.tickle()` every 60 s to keep it alive
- Rate limit: ~5 requests/second — handled transparently by `rate_limiter.py`

---

### Market Data

Fetch OHLCV bars via the IBKR gateway with automatic Google Drive parquet caching. Cache is shared across machines via Drive.

```python
from ibkr_core_mcp import IBKRClient, GDriveCache, Config, bars_to_dataframe

cfg = Config.from_env()
client = IBKRClient(cfg)
cache  = GDriveCache(cfg)

symbol, timeframe, period, end = "AAPL", "1D", "1Y", "2026-05-22"

if cache.check(symbol, timeframe, period, end):
    df = cache.load(symbol, timeframe, period, end)
else:
    contracts = client.search_contract(symbol)
    conid = contracts[0]["conid"]
    bars  = client.get_market_history(conid, period=period, bar="1d")
    df    = bars_to_dataframe(bars)
    cache.save(df, symbol, timeframe, period, end)
```

**Constraints:**
- Snapshot data may be 15-min delayed depending on market data subscription level
- Most endpoints require `conid` (contract ID) — use `client.search_contract(symbol)` to resolve

---

### Technical Indicators

14 pure-function indicators computed on a DataFrame. All return a Series or DataFrame of new columns.

```python
from ibkr_core_mcp import indicators

df = cache.load("AAPL", "1D", "1Y", "2026-05-22")
df = indicators.add_all(df)           # adds all 14 indicator columns in-place

# Individual indicators
rsi      = indicators.rsi(df, period=14)
macd_df  = indicators.macd(df)        # columns: macd, signal, histogram
bb_df    = indicators.bollinger_bands(df)
atr      = indicators.atr(df)
vwap     = indicators.vwap(df)
```

Available: `sma`, `ema`, `rsi`, `macd`, `bollinger_bands`, `atr`, `stochastic`, `williams_r`, `keltner_channels`, `vwap`, `obv`, `volume_sma`, `volume_ratio`, `add_all`

---

### Backtesting

Run strategy code in a `RestrictedPython` sandbox — no network, no file I/O, no `os` access.

```python
from ibkr_core_mcp import run_backtest

code = """
df['signal'] = 0
df.loc[df['rsi'] < 30, 'signal'] = 1
df.loc[df['rsi'] > 70, 'signal'] = -1
"""
result = run_backtest(code, df, strategy_name="RSI Mean Reversion")
print(f"Sharpe: {result.sharpe:.2f}  |  Max DD: {result.max_drawdown:.1f}%  |  Win rate: {result.win_rate:.0%}")
```

`BacktestResult` fields: `sharpe`, `sortino`, `calmar`, `max_drawdown`, `cagr`, `win_rate`, `profit_factor`, `trades`, `equity_curve`

---

### Historical Trade Data (Flex Queries)

The Client Portal API (`/iserver/account/trades`) returns only the **last 6 days** of trade history. For full historical data, configure a Flex Query on the IBKR website and use `FlexQueryClient`:

**One-time setup on IBKR website:**
1. Log in → Reports → Flex Queries → Create
2. Select "Trades" activity type, all fields, all dates
3. Note the Token and Query ID → add to `.env`:

```
IBKR_FLEX_TOKEN=your_token_here
IBKR_FLEX_QUERY_ID=your_query_id_here
```

**Usage:**
```python
from ibkr_core_mcp import FlexQueryClient, SQLiteStore, GDriveCache, Config

cfg   = Config.from_env()
store = SQLiteStore(cfg)
cache = GDriveCache(cfg)
flex  = FlexQueryClient(cfg, store, cache)

# Fetch → parse → upsert SQLite → save daily GDrive parquet
trades = flex.fetch_trades("U1234567")
print(f"Loaded {len(trades)} trades")

# Query historical trades from SQLite (unlimited history)
all_trades = store.get_trades(symbol="AAPL", start="2022-01-01")
```

The daily parquet snapshot is saved to GDrive under key `FLEX_TRADES_ALL_{account_id}_{YYYY-MM-DD}`. Run `flex.fetch_trades()` daily (cron or agent schedule) to keep the store current.

**Constraints:**
- Flex Token and Query ID must be configured manually on the IBKR website — they are not the same as Client Portal credentials
- Statement generation is asynchronous; `FlexQueryClient` polls up to 5 times (15 s total) before raising `FlexQueryError`

---

### Order Management

> **All write operations require fingerprint (Touch ID) + visual confirmation. See [Security & Fingerprint Authentication](#security--fingerprint-authentication).**

**Read-only — no auth required:**
```python
# List open orders
orders = client.get_live_orders()
for o in orders:
    print(f"{o['orderId']}  {o.get('ticker')}  {o.get('side')}  qty={o.get('remainingQuantity')}")

# Preview an order before placing (whatif — never executes)
preview = client.get_order_preview(account_id, order)
print(f"Estimated cost: {preview.get('equity', '?')}")
```

**Place a live order — Gate 1 (Touch ID) + Gate 2 (confirmation dialog):**
```python
from ibkr_core_mcp import IBKRClient, Config, HumanAuthError

cfg    = Config.from_env()
client = IBKRClient(cfg)

contracts = client.search_contract("AAPL")
order = {
    "conid":     contracts[0]["conid"],
    "ticker":    "AAPL",
    "side":      "BUY",
    "quantity":  10,
    "orderType": "LIMIT",
    "price":     182.50,
    "tif":       "DAY",
}

try:
    responses = client.place_order(account_id, order)
    for resp in responses:
        if "id" in resp:
            client.reply_order(resp["id"])   # IBKR confirmation step — also gated
except HumanAuthError as e:
    print(f"Order not sent: {e}")
```

**Modify or cancel — each triggers Touch ID + dialog:**
```python
try:
    client.modify_order(account_id, order_id, {"price": 180.00, "tif": "DAY"})
except HumanAuthError as e:
    print(f"Modification not sent: {e}")

try:
    client.cancel_order(account_id, order_id)
except HumanAuthError as e:
    print(f"Cancellation not sent: {e}")
```

**IBKR order constraints:**
- Trade history via API limited to last 6 days — `SQLiteStore` persists indefinitely
- Orders require `conid` — resolve via `client.search_contract(symbol)`

---

### Portfolio Analytics

```python
from ibkr_core_mcp import analytics

# Live positions and account summary (read-only)
positions = client.get_positions(account_id)
summary   = client.get_account_summary(account_id)

# Full performance report from equity returns + trade history
trades = store.get_trades()
report = analytics.full_report(equity_returns, trades)
# → { sharpe, sortino, calmar, max_drawdown, cagr, win_rate, profit_factor, avg_win_loss_ratio, ... }

print(f"Sharpe: {report['sharpe']:.2f}  |  Calmar: {report['calmar']:.2f}  |  Max DD: {report['max_drawdown']:.1f}%")
```

Available metrics: `sharpe`, `sortino`, `calmar`, `cagr`, `max_drawdown`, `max_drawdown_duration`, `win_rate`, `profit_factor`, `avg_win_loss_ratio`, `trade_summary`

---

### Claude AI Tool Layer

Exposes all IBKR capabilities as Claude tool definitions. Drop into any Claude-powered app.

```python
from ibkr_core_mcp import IBKRClient, GDriveCache, SQLiteStore, ClaudeToolkit, Config
import anthropic

cfg     = Config.from_env()
toolkit = ClaudeToolkit(IBKRClient(cfg), GDriveCache(cfg), SQLiteStore(cfg), cfg)

client   = anthropic.Anthropic()
response = client.messages.create(
    model="claude-sonnet-4-6",
    tools=toolkit.tools,          # 19 IBKR tools, ready to use
    messages=[{"role": "user", "content": "Show my open positions and run a backtest on AAPL"}],
)
for block in response.content:
    if block.type == "tool_use":
        text, fig = toolkit.execute(block.name, block.input)
```

Note: `ClaudeToolkit` exposes no order-write tools. Order placement must go through `IBKRClient` directly, which enforces the fingerprint gates.

---

### PineScript Generation

Generate TradingView PineScript v5 directly from backtest results or indicator configs.

```python
from ibkr_core_mcp import pinescript

# From a backtest result
script = pinescript.strategy_from_backtest(result, df)
print(script)   # paste directly into TradingView Pine Editor

# From signals DataFrame
script = pinescript.strategy_from_signals(df, strategy_name="RSI Reversal")

# Indicator-only script
script = pinescript.indicator_script(df, indicators=["rsi", "macd", "bollinger_bands"])
```

---

## Adding a New IBKR Endpoint

1. **`client.py`** — add method, return typed model
2. **`models.py`** — add Pydantic model for response if new shape
3. **`claude_tools.py`** — add tool definition + handler if useful for Claude
4. **`tests/test_client.py`** — add integration test marked `@pytest.mark.integration`
5. Update `__init__.py` if new model needs to be exported

---

## Running Tests

```bash
# Unit tests only (no gateway, no Drive, no IBKR account needed)
pytest -m "not integration"

# All tests (requires live IBKR gateway + .env)
pytest

# Specific module
pytest tests/test_indicators.py -v
```

---

## Consuming Projects

| Project | Repo | Uses |
|---|---|---|
| IBKR Research Dashboard | `github.com/stephus182/IB_MCP` | IBKRClient, GDriveCache, ClaudeToolkit, indicators, run_backtest, pinescript |
| Order Management UI | (future) | IBKRClient (order endpoints), SQLiteStore, ClaudeToolkit |
| ML Feature Pipeline | (future) | IBKRClient, GDriveCache, SQLiteStore, indicators |
| PineScript Generator | (future) | IBKRClient, GDriveCache, indicators, pinescript |
| Automated Scanner Bot | (future) | IBKRClient, SQLiteStore, analytics |

---

## Publishing a New Version

```bash
git tag v0.3.0
git push origin v0.3.0
```

Consumers pin to: `pip install git+https://github.com/stephus182/ibkr_core_mcp.git@v0.3.0`
