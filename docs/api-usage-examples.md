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
# The hours are a key part (2.2.0): regular trading hours (False) or all hours IBKR has (True) —
# IBKR's daily stock bar differs between the two on every day measured. A future's all-hours bar
# is stamped at its session open (18:00 ET the evening before); keep the stamp, read it by that rule.
hours = {"outside_rth": False}

if cache.check(symbol, timeframe, period, end, **hours):
    df = cache.load(symbol, timeframe, period, end, **hours)
    row = cache.entry(symbol, timeframe, period, end, **hours)  # the manifest row: rows, cached_at,
    print(row.get("listing") or "listing not recorded")         # outside_rth, and the listing saved below
else:
    # A ticker is not a listing. /trsrv/stocks carries `isUS` per contract; /iserver/secdef/search
    # does not, and its result order is undocumented — its first match for IGV is the Mexican
    # listing, in MXN. The toolkit's resolver takes the one US listing and ASKS when it is not
    # unique (`_resolve_stock_conid`); this example stops instead of guessing.
    records = client.get_stocks([symbol])
    us = [(r["name"], c) for r in records for c in r["contracts"] if c.get("isUS")]
    if len(us) != 1:
        raise SystemExit(f"{symbol}: {len(us)} US listings — name the exchange rather than pick one")
    name, contract = us[0]
    conid = int(contract["conid"])
    info  = client.get_secdef_info(conid)                   # a LIST live (2026-07-28); the currency is on its row
    currency = (info[0] if isinstance(info, list) else info).get("currency")
    bars  = client.get_market_history(conid, period=period, bar="1d", outside_rth=hours["outside_rth"])
    df    = bars_to_dataframe(bars)
    # Keep the listing beside the bars, so a later cache hit can say what it serves (2.2.0).
    cache.save(df, symbol, timeframe, period, end, **hours,
               listing={"conid": conid, "name": name, "exchange": contract["exchange"], "currency": currency})
```

**Constraints:**
- Snapshot data may be 15-min delayed depending on market data subscription level
- Most endpoints require `conid` (contract ID). For a stock, resolve through `client.get_stocks`
  and its `isUS` flag as above; `client.search_contract(symbol)` returns neither `isUS` nor a
  currency, and taking its first match is how a US ETF was once priced in pesos

## Technical Indicators

Pure-function indicators computed on a DataFrame. All return a Series or DataFrame of new columns.

```python
from ibkr_core_mcp import indicators

df = cache.load("AAPL", "1D", "1Y", "2026-05-22")
df = indicators.add_all(df)           # returns a new DataFrame (copy) with 20 indicator columns added

# Individual indicators
rsi      = indicators.rsi(df, period=14)
macd_df  = indicators.macd(df)        # columns: macd, macd_signal, histogram
bb_df    = indicators.bollinger_bands(df)
atr      = indicators.atr(df)
vwap     = indicators.vwap(df)        # per-session; needs a DatetimeIndex (see Conventions)
vwap_all = indicators.vwap(df, anchor=None)   # whole-frame cumulative, opt-in
vwap_cme = indicators.vwap(df, tz="America/New_York", session_open="18:00")  # a CME session, not the UTC day
kc_df    = indicators.keltner_channels(df)    # EMA(20) ± 2 × ATR(10) — ATR length is separate
tr       = indicators.true_range(df)

# A price source and a moving-average type, in TradingView's names (2.2.0)
sma_200  = indicators.sma(df, 200, source="hl2")                  # Series named "sma_200_hl2"
bands    = indicators.bollinger_bands(df, 200, 2.5, source="hl2") # basis and deviation both on hl2
wma_50   = indicators.moving_average(df, 50, "WMA", "hlc3")       # SMA, EMA, SMMA (RMA), WMA, VWMA
rsi_hl2  = indicators.rsi(df, 14, source="hl2")                   # close unless told otherwise
```

Available: `sma`, `ema`, `moving_average`, `price_source`, `rsi`, `macd`, `bollinger_bands`, `atr`, `true_range`, `stochastic`, `williams_r`, `keltner_channels`, `vwap`, `obv`, `volume_sma`, `volume_ratio`, `add_all`; the lists `SOURCES` and `MA_TYPES`

**Every `source` defaults to `close`** — the textbook definition, unchanged. The eight sources,
the five types, and what each setting corresponds to in TradingView:
[`indicators-reference.md`](indicators-reference.md).

### Conventions — which variant each indicator implements

Every formula here was checked against its source authority on 2026-09-16, and four
were wrong. The divergences were measured against worked examples those authorities
publish themselves; `scripts/audit/indicator_reference_divergence.py` reproduces the
table, and `tests/test_indicators_worked_examples.py` pins the values so they cannot
drift back. Don't change any of the following without doing the same.

| Indicator | Variant, and why | Warm-up |
|---|---|---|
| `rsi`, `atr` | **Wilder's smoothing, seeded with the SMA of the first `period` values** — not `ewm(alpha=1/period)`, which seeds with the first observation. Seeding it wrong put RSI up to 19.8 points and ATR up to 22% off ChartSchool's published examples. | NaN until the seed bar |
| `ema`, `macd` | **Seeded with the first close**, matching TradingView's `pine_ema`. Deliberately *not* the Wilder seed above, and deliberately not StockCharts' SMA seed — our generated PineScript runs on TradingView. Verified correct, unchanged. | none |
| `bollinger_bands` | **Population standard deviation (ddof=0)**. Both StockCharts and TradingView (`ta.stdev`'s `biased=true` default) use it; pandas' `.std()` default is ddof=1, which made every band 2.60% too wide. | NaN for `period - 1` bars |
| `stochastic` | **Fast** (%K unsmoothed, %D = 3-period SMA of %K). Charting packages often default to Slow, so the lines will differ from theirs — that is the variant, not a bug. | NaN for `k - 1` bars |
| `keltner_channels` | EMA(`period`) ± `atr_mult` × ATR(`atr_period`), defaulting to ChartSchool's (20, 2.0, **10**) triple. The authorities genuinely differ here — TradingView's `ta.kc` uses an EMA of true range at the basis length — so `atr_period` exists to address either. | follows ATR |
| `vwap` | **Resets every session** (`anchor="D"`). VWAP is defined over one trading day; accumulating across a whole frame answers no question. A session is the calendar day of the index as given — the **UTC** day for `bars_to_dataframe` frames, which is the exchange day for regular-hours US and European bars and is not for a CME session (it opens 18:00 New York and crosses midnight UTC an hour later); pass `tz` and `session_open` for the exchange's clock (DATA-R6, 2026-09-17). Raises on a non-DatetimeIndex rather than silently running cumulatively. On daily or coarser bars it degenerates to the bar's typical price, which is why `add_indicators` reports it only for intraday timeframes. | none |
| `obv`, `williams_r`, `sma` | Verified correct against ChartSchool, unchanged. | per definition |

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

ctx = SQLiteStore.get_market_calendar_context(today=some_date)  # the verdicts for another day (aware of nothing but the date)

# Returns: { "today": "...", "is_trading_day": bool (the PRIMARY exchange only), "last_trading_day": "...",
#            "next_trading_day": "...", "primary_exchange": "XNYS",
#            "sessions_today": { "XNYS": True, "CME": True, ..., "XSAU": False },  # one verdict per exchange; None on failure
#            "early_closes_today": { "XNYS": {"close": "13:00", "tz": "America/New_York"} },  # half days only; never CME; None on failure
#            "holidays_by_exchange": { "XNYS": ["2026-01-01", ...], "CME": [...], ... },
#            "futures": { "cme_open_nyse_closed": [...], "holiday_schedule_today": bool, ... } }  # hours on a holiday: CME's own page
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
    tools=toolkit.tools,          # 44 tools, ready to use
    messages=[{"role": "user", "content": "Show my open positions and run a backtest on AAPL"}],
)
for block in response.content:
    if block.type == "tool_use":
        text, fig = toolkit.execute(block.name, block.input)
```

Note: `fig` is currently always `None` — reserved for a future chart-returning tool, no current tool populates it.

Note: `ClaudeToolkit` exposes no order-write tools. Order placement must go through `IBKRClient` directly, which enforces the fingerprint gates.

**No layering exception any more.** `local_browser.judge_completeness_llm()` used to be the
one place `ibkr_core_mcp` called the Anthropic API directly with `config.anthropic_api_key`
rather than only handing `ClaudeToolkit.tools` to a host app — a call a host's own token
accounting could not see. It arbitrated between two scraper engines; the second engine was
removed on 2026-07-30, so the call has no job and is deleted. **`ClaudeToolkit` is now the only
layer that talks to the Anthropic API, with no exceptions.** Adding one back requires that no
other design works, not merely that the call is cheap.

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
