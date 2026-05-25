# ibkr_core_mcp — Developer Guide

Standalone pip-installable Python package providing a complete IBKR Client Portal API client, Google Drive parquet cache, SQLite store, backtest sandbox, technical indicators, portfolio analytics, Claude AI tool layer, and PineScript generation utilities.

**Design spec:** `docs/specs/2026-05-22-ibkr-core-mcp-design.md`

---

## Security — Order Write Protection

**ALL order write operations require two sequential human validations. There is no bypass.**

### Two-gate architecture

Every call to `place_order`, `modify_order`, `cancel_order`, or `reply_order` on `IBKRClient` must pass both gates — in order — before any network call is made:

1. **Gate 1 — Touch ID** (`human_auth.require_touch_id`): Apple biometric auth via `LocalAuthentication`. Policy: `LAPolicyDeviceOwnerAuthenticationWithBiometrics` — Touch ID only, no password fallback. 60-second timeout.
2. **Gate 2 — Visual confirmation** (`order_confirm`): tkinter modal dialog showing full order details and a live-order disclaimer. Requires explicit mouse click on the action button. Enter key does not confirm.

If either gate fails (denied, timeout, cancelled), `HumanAuthError` is raised immediately and the IBKR endpoint is never contacted.

### Gated endpoints

| Method | Gate |
|---|---|
| `place_order` | Touch ID + confirm dialog |
| `modify_order` | Touch ID + modify dialog |
| `cancel_order` | Touch ID + cancel dialog |
| `reply_order` | Touch ID + reply dialog |

### Explicitly ungated

| Method | Reason |
|---|---|
| `get_order_preview` | IBKR `whatif` — read-only, no execution |
| `create_alert` / `delete_alert` / `activate_alert` | Price notifications, not order execution |

### Rules for contributors

- **Never add a bypass flag, session cache, or fallback** to `require_touch_id` or any dialog function.
- **Never move the gates** out of `IBKRClient` into a higher layer — enforcement must be at the innermost call site.
- **Never add password/PIN fallback** — `LAPolicyDeviceOwnerAuthenticationWithBiometrics` is the required policy.
- Any PR that weakens these gates will be rejected.

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

## Usage Examples

### Minimal setup
```python
from ibkr_core_mcp import IBKRClient, GDriveCache, SQLiteStore, Config

cfg = Config.from_env()          # reads .env
client = IBKRClient(cfg)
cache = GDriveCache(cfg)
store = SQLiteStore(cfg)
```

### Fetch market data (cache-first)
```python
from ibkr_core_mcp import IBKRClient, GDriveCache, Config, CacheMissError

cfg = Config.from_env()
client = IBKRClient(cfg)
cache = GDriveCache(cfg)

symbol, timeframe, period, end = "AAPL", "1D", "1Y", "2026-05-22"

if cache.check(symbol, timeframe, period, end):
    df = cache.load(symbol, timeframe, period, end)
else:
    contracts = client.search_contract(symbol)
    conid = contracts[0].conid
    bars = client.get_market_history(conid, period=period, bar="1d")
    df = bars_to_dataframe(bars)
    cache.save(df, symbol, timeframe, period, end)
```

### Technical indicators
```python
from ibkr_core_mcp import indicators

df = cache.load("AAPL", "1D", "1Y", "2026-05-22")
df = indicators.add_all(df)         # adds all indicator columns
rsi = indicators.rsi(df, period=14)
macd_df = indicators.macd(df)       # columns: macd, signal, histogram
bb_df = indicators.bollinger_bands(df)
```

### Run a backtest
```python
from ibkr_core_mcp import run_backtest

code = """
df['signal'] = 0
df.loc[df['rsi'] < 30, 'signal'] = 1
df.loc[df['rsi'] > 70, 'signal'] = -1
"""
result = run_backtest(code, df, strategy_name="RSI Mean Reversion")
print(f"Sharpe: {result.sharpe:.2f}, Max DD: {result.max_drawdown:.1f}%")
```

### Claude tool layer (in any Claude-powered app)
```python
from ibkr_core_mcp import IBKRClient, GDriveCache, SQLiteStore, ClaudeToolkit, Config
import anthropic

cfg = Config.from_env()
toolkit = ClaudeToolkit(IBKRClient(cfg), GDriveCache(cfg), SQLiteStore(cfg), cfg)

client = anthropic.Anthropic()
response = client.messages.create(
    model="claude-sonnet-4-6",
    tools=toolkit.tools,          # all 18 IBKR tools, ready to use
    messages=[{"role": "user", "content": "Show my open positions"}],
)
for block in response.content:
    if block.type == "tool_use":
        text, fig = toolkit.execute(block.name, block.input)
```

### Generate PineScript
```python
from ibkr_core_mcp import pinescript

script = pinescript.strategy_from_backtest(result, df)
print(script)   # paste directly into TradingView Pine Editor
```

### Portfolio analytics
```python
from ibkr_core_mcp import analytics

trades = client.get_trades()
positions = client.get_positions(account_id)
report = analytics.full_report(equity_returns, trades)
# → { sharpe, sortino, calmar, max_drawdown, win_rate, profit_factor, ... }
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

## Auth Notes

The IBKR Client Portal Gateway must run on the **same machine** as the browser used to authenticate. No cloud deployment possible.

`BrowserCookieAuth` (default) reads Chrome's cookie store for `localhost`. On first use:
1. Start the gateway: `docker compose up` in the IB_MCP repo
2. Open `https://localhost:5055` in Chrome
3. Log in with IBKR credentials + 2FA (approve push notification on phone)
4. Wait for "Client login succeeds" in browser
5. The package reads the session cookie automatically

If running headless (ML batch jobs), use `TokenAuth(cookie_string)` by passing the cookie string extracted from a prior authenticated session.

---

## Publishing a New Version

```bash
git tag v0.1.0
git push origin v0.1.0
```

Consumers then pin to: `pip install git+https://github.com/stephus182/ibkr_core_mcp.git@v0.1.0`

---

## Known IBKR API Constraints

- **Session timeout:** Gateway session expires without activity. Use `/tickle` every 60s.
- **Rate limits:** ~5 requests/second. The package handles this transparently via `rate_limiter.py`.
- **Trade history:** IBKR only returns last 6 days via API. `SQLiteStore` persists indefinitely.
- **conid vs symbol:** Most endpoints require contract ID (`conid`). Use `client.search_contract(symbol)` to resolve.
- **Same-machine auth:** Browser auth must happen on the same host running the gateway.
- **Market data delay:** Snapshot data may be 15-min delayed depending on subscription level.
