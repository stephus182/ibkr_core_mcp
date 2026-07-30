# API Usage Examples

Per-module "how to call this" examples. Not safety-critical or architectural — pull this in
when actually writing code against a specific module. Security rules for order write
operations live in CLAUDE.md itself, not here.

## Setup

```python
from ibkr_core_mcp import IBKRClient, GDriveCache, SQLiteStore, Config

cfg = Config.from_env()          # reads .env
client = IBKRClient(cfg)
cache  = GDriveCache(cfg)
store  = SQLiteStore(cfg)
```

## Market Data

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

## Technical Indicators

14 pure-function indicators computed on a DataFrame. All return a Series or DataFrame of new columns.

```python
from ibkr_core_mcp import indicators

df = cache.load("AAPL", "1D", "1Y", "2026-05-22")
df = indicators.add_all(df)           # returns a new DataFrame (copy) with 20 indicator columns added

# Individual indicators
rsi      = indicators.rsi(df, period=14)
macd_df  = indicators.macd(df)        # columns: macd, macd_signal, histogram
bb_df    = indicators.bollinger_bands(df)
atr      = indicators.atr(df)
vwap     = indicators.vwap(df)
```

Available: `sma`, `ema`, `rsi`, `macd`, `bollinger_bands`, `atr`, `stochastic`, `williams_r`, `keltner_channels`, `vwap`, `obv`, `volume_sma`, `volume_ratio`, `add_all`

## Backtesting

Run strategy code in a `RestrictedPython` sandbox — no network, no file I/O, no `os` access.

```python
from ibkr_core_mcp import run_backtest

code = """
df['signal'] = 0
df.loc[df['rsi'] < 30, 'signal'] = 1
df.loc[df['rsi'] > 70, 'signal'] = -1
"""
result = run_backtest(code, df, strategy_name="RSI Mean Reversion")
print(f"Sharpe: {result.sharpe:.2f}  |  Max DD: {result.max_drawdown:.1%}  |  Win rate: {result.win_rate:.0%}")
```

`BacktestResult` fields: `symbol`, `strategy_name`, `total_return`, `sharpe`, `sortino`, `max_drawdown`, `num_trades`, `win_rate`, `equity_curve`

## Portfolio Analytics

```python
from ibkr_core_mcp import analytics

# Live positions and account summary (read-only)
positions = client.get_positions(account_id)
summary   = client.get_account_summary(account_id)

# Full performance report from equity returns + trade history
trades = store.get_trades()
report = analytics.full_report(equity_returns, trades)           # daily bars (default)
report = analytics.full_report(equity_returns, trades, periods=98280)  # 1-min bars (390 * 252)
# → { total_return, cagr, sharpe, sortino, calmar, max_drawdown, max_drawdown_duration,
#     num_bars, total_trades, win_rate, profit_factor, avg_win_loss_ratio }
# trade-derived keys (total_trades, win_rate, profit_factor, avg_win_loss_ratio) are only
# present when `trades` is passed — they're merged into the top-level dict, not nested.

print(f"Sharpe: {report['sharpe']:.2f}  |  Calmar: {report['calmar']:.2f}  |  Max DD: {report['max_drawdown']:.1%}")
```

Available metrics: `total_return`, `cagr`, `sharpe`, `sortino`, `calmar`, `max_drawdown`, `max_drawdown_duration`, `num_bars`, `total_trades`, `win_rate`, `profit_factor`, `avg_win_loss_ratio`

**Market calendar context** (static method on `SQLiteStore`):

```python
# Trading calendar for the current + next year — holidays, half-days, session hours
ctx = SQLiteStore.get_market_calendar_context()            # default: 20 exchanges (G20 + Eurex)
ctx = SQLiteStore.get_market_calendar_context(["XLON"])     # REPLACES the default — returns XLON only, not default+XLON

# Returns: { "today": "...", "is_trading_day": bool, "last_trading_day": "...",
#            "next_trading_day": "...", "primary_exchange": "XNYS",
#            "holidays_by_exchange": { "XNYS": ["2026-01-01", ...], "CME": [...], ... },
#            "futures": { "cme_open_nyse_closed": [...], ... } }  # CME/NYSE futures-session overrides
# See README.md's "Market Calendar" section for the full 20-exchange default list and a worked example.
```

Used internally by `ClaudeToolkit.get_analytics()` to give the LLM context-aware trading-day awareness.

## Claude AI Tool Layer

Exposes all IBKR capabilities as Claude tool definitions. Drop into any Claude-powered app.

```python
from ibkr_core_mcp import IBKRClient, GDriveCache, SQLiteStore, ClaudeToolkit, Config
import anthropic

cfg     = Config.from_env()
toolkit = ClaudeToolkit(IBKRClient(cfg), GDriveCache(cfg), SQLiteStore(cfg), cfg)

client   = anthropic.Anthropic()
response = client.messages.create(
    model="claude-sonnet-4-6",
    tools=toolkit.tools,          # 43 tools, ready to use
    messages=[{"role": "user", "content": "Show my open positions and run a backtest on AAPL"}],
)
for block in response.content:
    if block.type == "tool_use":
        text, fig = toolkit.execute(block.name, block.input)
```

Note: `fig` is currently always `None` — reserved for a future chart-returning tool, no current tool populates it.

Note: `ClaudeToolkit` exposes no order-write tools. Order placement must go through `IBKRClient` directly, which enforces the fingerprint gates.

**Layering exception:** `local_browser.judge_completeness_llm()` (used by the
`firecrawl_search`/`firecrawl_crawl` handlers) is the one place `ibkr_core_mcp` calls
the Anthropic API directly with `config.anthropic_api_key`, rather than only handing
`ClaudeToolkit.tools` to a host app's own client. This was a deliberate, scoped
choice (a single cheap Haiku completeness check) — don't treat it as precedent for
adding more direct API calls elsewhere without the same scrutiny; a host app's own
token-usage tracking won't see this call's cost.

## PineScript Generation

Generate TradingView PineScript v5 directly from backtest results or indicator configs.

```python
from ibkr_core_mcp import pinescript

# From a backtest result
script = pinescript.strategy_from_backtest(result, df)
print(script)   # paste directly into TradingView Pine Editor

# From signals DataFrame
script = pinescript.strategy_from_signals("RSI Reversal", df["signal"], symbol="AAPL", timeframe="1D")

# Indicator-only script
script = pinescript.indicator_script("AAPL Indicators", ["rsi", "macd", "bollinger_bands"], params={})
```
