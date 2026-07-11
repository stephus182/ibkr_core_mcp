# Historical Trade Data (Flex Queries) — Full Reference

The Client Portal API (`/iserver/account/trades`) returns only the **last 7 days** of trade history (current day + 6 previous). For full historical data, the package ships a complete Flex Query suite — the only manual step is the one-time Flex Query configuration on the IBKR website below. After that, `FlexQueryClient` fetches/parses statements and maintains the historical database end-to-end (upsert into `SQLiteStore` for unlimited history + raw-XML archive to Drive for audit/verification), and the toolkit exposes the full lifecycle as tools: `sync_flex_trades` (daily fetch), `sync_flex_archive` / `import_flex_file` (bulk/manual XML import), `check_flex_coverage` (history completeness), and `verify_flex_import` (SHA-256 manifest verification).

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

# Fetch → parse → upsert SQLite → archive raw XML to Drive + manifest log
trades = flex.fetch_trades("U1234567")
print(f"Loaded {len(trades)} trades")

# Query historical trades from SQLite (unlimited history)
all_trades = store.get_trades(symbol="AAPL", start="2022-01-01")
```

Each fetch archives the raw Flex XML to Drive `account_data/` as
`flex_{account_id}_{YYYY-MM-DD}_{ref_code}.xml` and logs a SHA-256 manifest entry (tradeID
count, raw `<Trade>` element count, import/verified timestamps) via `SQLiteStore.log_flex_import()`
— this is what `verify_flex_import` checks against. The trade *data* itself lives only in
SQLite (unlimited history); there is no separate OHLCV-style parquet snapshot of trades on
Drive — GDrive parquet caching (`cache.check`/`.load`/`.save`) is for market data bars only.
A Drive archive/manifest failure is logged but does not abort a successful SQLite sync (trades
are already upserted by that point). Run `flex.fetch_trades()` daily (cron or agent schedule)
to keep the store current.

**Constraints:**
- Flex Token and Query ID must be configured manually on the IBKR website — they are not the same as Client Portal credentials
- Statement generation is asynchronous; `FlexQueryClient` polls up to 5 times, 3 s apart (~12 s worst case), before raising `FlexQueryError`
