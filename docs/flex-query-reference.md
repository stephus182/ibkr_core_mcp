# Historical Trade Data (Flex Queries) — Full Reference

The Client Portal API (`/iserver/account/trades`) returns only the **last 7 days** of trade history (current day + 6 previous). For full historical data, the package ships a complete Flex Query suite — the only manual step is the one-time Flex Query configuration on the IBKR website below. After that, `FlexQueryClient` fetches/parses statements and maintains the historical database end-to-end (upsert into `SQLiteStore` for unlimited history + daily GDrive parquet snapshots), and the toolkit exposes the full lifecycle as tools: `sync_flex_trades` (daily fetch), `sync_flex_archive` / `import_flex_file` (bulk/manual XML import), `check_flex_coverage` (history completeness), and `verify_flex_import` (SHA-256 manifest verification).

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
