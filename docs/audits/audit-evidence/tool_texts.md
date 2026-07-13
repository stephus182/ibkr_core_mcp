## fetch_market_data

**description:** Fetch OHLCV historical data for a symbol from IBKR. Checks Google Drive cache first; only calls IBKR on a cache miss. Returns a summary of the data retrieved.

**input_schema:**
```json
{
  "type": "object",
  "properties": {
    "symbol": {
      "type": "string",
      "description": "Ticker, e.g. AAPL"
    },
    "period": {
      "type": "string",
      "description": "History period, e.g. '1Y', '6M'"
    },
    "bar": {
      "type": "string",
      "description": "Bar size, e.g. '1d', '1h'",
      "default": "1d"
    },
    "end": {
      "type": "string",
      "description": "End date YYYY-MM-DD, defaults to today"
    }
  },
  "required": [
    "symbol",
    "period"
  ]
}
```

## check_cache

**description:** Check whether data for a symbol/timeframe is cached in Google Drive.

**input_schema:**
```json
{
  "type": "object",
  "properties": {
    "symbol": {
      "type": "string"
    },
    "timeframe": {
      "type": "string",
      "description": "e.g. '1D'"
    },
    "period": {
      "type": "string",
      "description": "e.g. '1Y'"
    },
    "end": {
      "type": "string",
      "description": "End date YYYY-MM-DD"
    }
  },
  "required": [
    "symbol",
    "timeframe",
    "period",
    "end"
  ]
}
```

## list_cache

**description:** List all datasets currently cached in Google Drive.

**input_schema:**
```json
{
  "type": "object",
  "properties": {},
  "required": []
}
```

## get_account_summary

**description:** Retrieve account net liquidation value, cash balance, and P&L from IBKR.

**input_schema:**
```json
{
  "type": "object",
  "properties": {},
  "required": []
}
```

## get_positions

**description:** Get all open positions for the IBKR account.

**input_schema:**
```json
{
  "type": "object",
  "properties": {},
  "required": []
}
```

## get_trades

**description:** Get trade history. source='live' queries IBKR directly (last 6 days only). source='store' queries the local SQLite store — unlimited history, includes all data synced via sync_flex_trades. Use source='store' for any analysis beyond 6 days.

**input_schema:**
```json
{
  "type": "object",
  "properties": {
    "symbol": {
      "type": "string",
      "description": "Filter by symbol (optional)"
    },
    "source": {
      "type": "string",
      "description": "'live' (IBKR API, last 6 days) or 'store' (SQLite, unlimited history including Flex syncs)",
      "default": "store"
    },
    "start": {
      "type": "string",
      "description": "Start date YYYY-MM-DD (store source only, optional)"
    },
    "end": {
      "type": "string",
      "description": "End date YYYY-MM-DD (store source only, optional)"
    }
  },
  "required": []
}
```

## sync_flex_archive

**description:** Download all Flex XML files from the 'ibkr_flex_archive' Google Drive subfolder and import them into the local SQLite trade store. Use for historical backfill: upload year-by-year XML files to Drive first, then run this once. Duplicates are handled automatically. Runs check_flex_coverage at the end.

**input_schema:**
```json
{
  "type": "object",
  "properties": {},
  "required": []
}
```

## import_flex_file

**description:** Import a locally downloaded IBKR Flex XML file into the SQLite trade store. Use for historical backfill: download year-by-year XMLs from the IBKR website (Performance & Reports → Flex Queries → Run with custom date range), save each file to ~/.ibkr_core/flex_archive/, then call this tool for each file. Duplicates are handled automatically (idempotent).

**input_schema:**
```json
{
  "type": "object",
  "properties": {
    "path": {
      "type": "string",
      "description": "Absolute path to the Flex XML file"
    }
  },
  "required": [
    "path"
  ]
}
```

## check_flex_coverage

**description:** Report the trade activity date range from the local SQLite store: oldest trade, newest trade, total record count, and periods of 45+ calendar days with no recorded executions (which may reflect genuine inactivity or missing imports — use verify_flex_import to distinguish). Does not verify completeness against source.

**input_schema:**
```json
{
  "type": "object",
  "properties": {},
  "required": []
}
```

## verify_flex_import

**description:** Verify Flex import completeness by comparing source XML archives in Google Drive account_data/ against the local SQLite trades table. For each XML file, extracts all tradeIDs and checks whether they are present in SQLite. Reports per-file counts (XML records vs SQLite matches) and an aggregate summary. A missing tradeID means that execution was not imported. Does not modify any data — read-only integrity check against the source files.

**input_schema:**
```json
{
  "type": "object",
  "properties": {},
  "required": []
}
```

## sync_flex_trades

**description:** Fetch the full historical trade history from IBKR Flex Web Service and store it in the local SQLite database and Google Drive cache. Requires IBKR_FLEX_TOKEN and IBKR_FLEX_QUERY_ID to be configured. Run this once or daily to keep historical trade data current beyond the 6-day API limit.

**input_schema:**
```json
{
  "type": "object",
  "properties": {
    "account_id": {
      "type": "string",
      "description": "IBKR account ID (optional \u2014 resolved automatically if omitted)"
    }
  },
  "required": []
}
```

## get_live_orders

**description:** Get ALL non-terminal orders for the account regardless of origin — includes orders placed via IBKR mobile, TWS, web portal, or ClaudIA staging. Uses the account-scoped endpoint which returns every working order on the account. IMPORTANT: orders placed via mobile or TWS CANNOT be modified or cancelled by the API. When reporting such orders, explicitly state: 'I can see this order but cannot modify or cancel it — use IBKR mobile or TWS to manage it.' Never skip or silently omit externally-placed orders. Always flag their origin when it differs from ClaudIA staging.

**input_schema:**
```json
{
  "type": "object",
  "properties": {},
  "required": []
}
```

## diagnose_orders

**description:** Return the raw unfiltered IBKR orders API response for debugging. Use when get_live_orders returns empty but the user believes they have open orders. Shows ALL orders regardless of status, plus the raw response shape, so you can identify whether orders are present but filtered, or genuinely absent.

**input_schema:**
```json
{
  "type": "object",
  "properties": {},
  "required": []
}
```

## get_ledger

**description:** Get cash balance and ledger information by currency for the IBKR account.

**input_schema:**
```json
{
  "type": "object",
  "properties": {},
  "required": []
}
```

## get_allocation

**description:** Get portfolio allocation breakdown by asset class, industry, and category.

**input_schema:**
```json
{
  "type": "object",
  "properties": {},
  "required": []
}
```

## get_pa_periods

**description:** Get the list of valid period strings for Portfolio Analyst queries (performance and transactions). Call this first if unsure which period to use.

**input_schema:**
```json
{
  "type": "object",
  "properties": {},
  "required": []
}
```

## get_pa_performance

**description:** Get portfolio NAV performance from IBKR Portfolio Analyst. Use get_pa_periods first to discover valid period strings.

**input_schema:**
```json
{
  "type": "object",
  "properties": {
    "period": {
      "type": "string",
      "description": "Valid period string from get_pa_periods, e.g. 'last7days', 'last30days', 'ytd', 'last365days'"
    }
  },
  "required": [
    "period"
  ]
}
```

## get_pa_transactions

**description:** Get transaction history from IBKR Portfolio Analyst (all origins: mobile, TWS, API). Use get_pa_periods first to discover valid period strings.

**input_schema:**
```json
{
  "type": "object",
  "properties": {
    "period": {
      "type": "string",
      "description": "Valid period string from get_pa_periods, e.g. 'last7days', 'ytd'"
    }
  },
  "required": [
    "period"
  ]
}
```

## get_contract_info

**description:** Get full contract details for a symbol (conid, exchange, currency, trading hours, etc.).

**input_schema:**
```json
{
  "type": "object",
  "properties": {
    "symbol": {
      "type": "string",
      "description": "Ticker symbol"
    },
    "sec_type": {
      "type": "string",
      "description": "Security type, default STK",
      "default": "STK"
    }
  },
  "required": [
    "symbol"
  ]
}
```

## get_option_chain

**description:** Get the options chain for a symbol — expirations, strikes, and contract IDs.

**input_schema:**
```json
{
  "type": "object",
  "properties": {
    "symbol": {
      "type": "string"
    },
    "exchange": {
      "type": "string",
      "default": "SMART"
    }
  },
  "required": [
    "symbol"
  ]
}
```

## run_scanner

**description:** Run an IBKR market scanner to find stocks matching criteria. Common scan_code values: 'TOP_PERC_GAIN', 'TOP_PERC_LOSE', 'MOST_ACTIVE', 'HIGH_VS_13W_HL', 'LOW_VS_13W_HL', 'NEAR_52W_HL'.

**input_schema:**
```json
{
  "type": "object",
  "properties": {
    "scan_code": {
      "type": "string",
      "description": "Scanner type, e.g. 'TOP_PERC_GAIN'"
    },
    "instrument": {
      "type": "string",
      "description": "e.g. 'STK'",
      "default": "STK"
    },
    "location_code": {
      "type": "string",
      "description": "e.g. 'STK.US.MAJOR'",
      "default": "STK.US.MAJOR"
    },
    "max_results": {
      "type": "integer",
      "default": 25
    }
  },
  "required": [
    "scan_code"
  ]
}
```

## get_notifications

**description:** Retrieve IBKR FYI notifications and unread alerts.

**input_schema:**
```json
{
  "type": "object",
  "properties": {
    "max_results": {
      "type": "integer",
      "default": 10
    }
  },
  "required": []
}
```

## add_indicators

**description:** Load cached market data for a symbol and compute all technical indicators (RSI, MACD, Bollinger Bands, ATR, VWAP, OBV, Stochastic, Williams %R, Keltner Channels). Returns a summary of current indicator values.

**input_schema:**
```json
{
  "type": "object",
  "properties": {
    "symbol": {
      "type": "string",
      "description": "Ticker symbol"
    },
    "timeframe": {
      "type": "string",
      "description": "e.g. '1D'"
    },
    "period": {
      "type": "string",
      "description": "e.g. '1Y'"
    },
    "end": {
      "type": "string",
      "description": "End date YYYY-MM-DD"
    }
  },
  "required": [
    "symbol",
    "timeframe",
    "period",
    "end"
  ]
}
```

## run_backtest

**description:** Execute a Python strategy in a sandboxed environment against cached market data. Strategy code receives a pandas DataFrame `df` with OHLCV columns and must set df['signal'] = 1 (long), 0 (flat), or -1 (short). Returns Sharpe ratio, total return, max drawdown, trade count, and win rate.

**input_schema:**
```json
{
  "type": "object",
  "properties": {
    "code": {
      "type": "string",
      "description": "Python strategy code string"
    },
    "symbol": {
      "type": "string",
      "description": "Ticker symbol"
    },
    "timeframe": {
      "type": "string",
      "description": "e.g. '1D'"
    },
    "period": {
      "type": "string",
      "description": "e.g. '1Y'"
    },
    "end": {
      "type": "string",
      "description": "End date YYYY-MM-DD"
    },
    "strategy_name": {
      "type": "string",
      "description": "Human-readable name",
      "default": ""
    }
  },
  "required": [
    "code",
    "symbol",
    "timeframe",
    "period",
    "end"
  ]
}
```

## generate_pinescript

**description:** Generate a PineScript v5 script for TradingView from a list of indicators or from a previously run backtest strategy. Output can be pasted directly into the TradingView Pine Editor.

**input_schema:**
```json
{
  "type": "object",
  "properties": {
    "symbol": {
      "type": "string",
      "description": "Ticker symbol"
    },
    "indicators": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "description": "List of indicators: 'rsi', 'macd', 'bollinger_bands', 'ema', 'sma', 'atr'"
    },
    "strategy_name": {
      "type": "string",
      "description": "Optional name for the script",
      "default": ""
    }
  },
  "required": [
    "symbol",
    "indicators"
  ]
}
```

## get_analytics

**description:** Compute full portfolio/strategy analytics on cached OHLCV data: Sharpe ratio, Sortino ratio, Calmar ratio, CAGR, max drawdown, and drawdown duration.

**input_schema:**
```json
{
  "type": "object",
  "properties": {
    "symbol": {
      "type": "string",
      "description": "Ticker symbol"
    },
    "timeframe": {
      "type": "string",
      "description": "e.g. '1D'"
    },
    "period": {
      "type": "string",
      "description": "e.g. '1Y'"
    },
    "end": {
      "type": "string",
      "description": "End date YYYY-MM-DD"
    }
  },
  "required": [
    "symbol",
    "timeframe",
    "period",
    "end"
  ]
}
```

## preview_order

**description:** Preview an order using IBKR's whatif endpoint — returns estimated cost, commission, margin impact, and buying power effect WITHOUT placing the order. Use this before proposing a trade to verify feasibility and cost.

**input_schema:**
```json
{
  "type": "object",
  "properties": {
    "symbol": {
      "type": "string",
      "description": "Ticker symbol, e.g. AAPL"
    },
    "action": {
      "type": "string",
      "description": "'BUY' or 'SELL'"
    },
    "quantity": {
      "type": "integer",
      "description": "Number of shares"
    },
    "order_type": {
      "type": "string",
      "description": "'MKT', 'LMT', or 'STP'",
      "default": "MKT"
    },
    "limit_price": {
      "type": "number",
      "description": "Limit price (required if order_type='LMT')"
    }
  },
  "required": [
    "symbol",
    "action",
    "quantity"
  ]
}
```

## get_pnl

**description:** Get real-time partitioned P&L for the IBKR account: daily P&L, unrealized P&L, and realized P&L broken down by position.

**input_schema:**
```json
{
  "type": "object",
  "properties": {},
  "required": []
}
```

## search_contract

**description:** Search for IBKR contracts by symbol and security type. Returns conid, exchange, currency, and description. Use this to discover conids before calling tools that require one.

**input_schema:**
```json
{
  "type": "object",
  "properties": {
    "symbol": {
      "type": "string",
      "description": "Ticker symbol, e.g. CL, AAPL, SPY"
    },
    "sec_type": {
      "type": "string",
      "description": "Security type: STK, FUT, OPT, FX, IND, CFD, BOND (default: STK)"
    }
  },
  "required": [
    "symbol"
  ]
}
```

## get_futures

**description:** Look up futures contracts for one or more symbols. Returns available expiry months, conids, and exchange info. Useful for CL, ES, NQ, GC, and other futures.

**input_schema:**
```json
{
  "type": "object",
  "properties": {
    "symbols": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "description": "List of root symbols, e.g. ['CL', 'ES']"
    }
  },
  "required": [
    "symbols"
  ]
}
```

## get_market_snapshot

**description:** Get market data snapshot for one or more symbols: last price, bid, ask, high, low, change, change%, and volume. Each quote includes _data_status ('Live (Real-Time)' when subscribed, 'Delayed (15–20 min)' when not) and _quote_time (timestamp in ET). Always report both to the user.

Resolution by sec_type:
- STK (default): equities and ETFs. For international listings, pass exchange   to select the right venue (e.g. exchange='AMS' for ASML on Euronext Amsterdam,   exchange='ETR' for SAP on Xetra, exchange='TSE' for Toyota on Tokyo SE,   exchange='HKEX' for HSBC on HK). Without exchange, the first result is used.
- IND: indices (SPX, NDX, DAX, FTSE, N225). Use exchange for non-US indices.
- FUT: futures by root symbol. Front-month contract is selected automatically   from /trsrv/futures (e.g. ES, NQ, CL, GC, ZC, ZN, 6E). Do NOT pass expiry   in the symbol — use root symbol only.
- CASH: FX spot pairs. Pass the pair as 'EUR.USD', 'USD.JPY', 'GBP.USD', etc.   (base.quote format). IBKR routes FX via IDEALPRO.
- BOND: bonds via IBKR bond search. Specify CUSIP or issuer symbol.
- OPT: options require a prior search_contract + secdef/info flow to resolve   the option conid. Call search_contract first, then get_market_snapshot with   the resolved conid directly (not ticker).

**input_schema:**
```json
{
  "type": "object",
  "properties": {
    "symbols": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "description": "Ticker symbols. For FX: 'EUR.USD' format. For FUT: root symbol only ('ES', not 'ESH25'). For international STK: ticker as listed on the exchange."
    },
    "sec_type": {
      "type": "string",
      "description": "Security type: STK (default), IND, FUT, CASH, BOND"
    },
    "exchange": {
      "type": "string",
      "description": "Optional. Filter to a specific exchange listing for STK/IND. IBKR exchange codes: AMS (Euronext Amsterdam), ETR (Xetra), LSE (London), TSE (Tokyo), HKEX (Hong Kong), ASX (Sydney), TSX (Toronto), BVSP (Brazil), NSE (India). Omit for US equities (SMART routing used)."
    }
  },
  "required": [
    "symbols"
  ]
}
```

## get_trading_schedule

**description:** Get the trading schedule and session hours for a symbol: regular trading hours, pre/post-market sessions, and next trading date. Useful for futures (e.g. CL on NYMEX) and equities.

**input_schema:**
```json
{
  "type": "object",
  "properties": {
    "symbol": {
      "type": "string",
      "description": "Ticker symbol, e.g. CL, AAPL"
    },
    "asset_class": {
      "type": "string",
      "description": "Asset class: STK, FUT, OPT, FX (default: STK)"
    },
    "exchange": {
      "type": "string",
      "description": "Exchange, e.g. NYMEX, NYSE, NASDAQ (default: SMART)"
    }
  },
  "required": [
    "symbol"
  ]
}
```

## get_alerts

**description:** List all IBKR price alerts configured on the account.

**input_schema:**
```json
{
  "type": "object",
  "properties": {},
  "required": []
}
```

## create_price_alert

**description:** Create a native IBKR price alert for a symbol. The alert fires server-side (even when the app is closed) when the price crosses the threshold. Use '>=' for above and '<=' for below.

**input_schema:**
```json
{
  "type": "object",
  "properties": {
    "symbol": {
      "type": "string",
      "description": "Ticker symbol, e.g. AAPL, CL"
    },
    "sec_type": {
      "type": "string",
      "description": "Security type: STK, FUT, OPT, FX (default: STK)"
    },
    "operator": {
      "type": "string",
      "enum": [
        ">=",
        "<="
      ],
      "description": "'>=' triggers when price reaches or exceeds threshold; '<=' when it falls to or below"
    },
    "price": {
      "type": "number",
      "description": "Price threshold"
    },
    "tif": {
      "type": "string",
      "enum": [
        "GTC",
        "DAY"
      ],
      "description": "Time in force: 'GTC' (good till cancelled, default) or 'DAY' (expires at market close)"
    },
    "outside_rth": {
      "type": "boolean",
      "description": "If true, alert also monitors extended hours (pre-market and after-hours). Default false (regular hours only). Useful for earnings."
    },
    "name": {
      "type": "string",
      "description": "Human-readable alert name (default: auto-generated from symbol and price)"
    },
    "repeat": {
      "type": "boolean",
      "description": "Whether to repeat the alert after it fires (default: false)"
    }
  },
  "required": [
    "symbol",
    "operator",
    "price"
  ]
}
```

## delete_alert

**description:** Delete an IBKR price alert by its alert ID. Use get_alerts first to find the ID.

**input_schema:**
```json
{
  "type": "object",
  "properties": {
    "alert_id": {
      "type": "string",
      "description": "Alert ID from get_alerts"
    }
  },
  "required": [
    "alert_id"
  ]
}
```

## activate_alert

**description:** Activate or deactivate an existing IBKR price alert without deleting it.

**input_schema:**
```json
{
  "type": "object",
  "properties": {
    "alert_id": {
      "type": "string",
      "description": "Alert ID from get_alerts"
    },
    "activate": {
      "type": "boolean",
      "description": "true to activate, false to deactivate (default: true)"
    }
  },
  "required": [
    "alert_id"
  ]
}
```

## modify_price_alert

**description:** Modify an existing IBKR price alert. Fetches the current alert by ID and applies only the fields you provide, leaving others unchanged. Use get_alerts first to find the alert ID.

**input_schema:**
```json
{
  "type": "object",
  "properties": {
    "alert_id": {
      "type": "string",
      "description": "Alert ID from get_alerts"
    },
    "price": {
      "type": "number",
      "description": "New price threshold"
    },
    "operator": {
      "type": "string",
      "enum": [
        ">=",
        "<="
      ],
      "description": "New operator: '>=' (above) or '<=' (below)"
    },
    "tif": {
      "type": "string",
      "enum": [
        "GTC",
        "DAY"
      ],
      "description": "New time in force: GTC or DAY"
    },
    "outside_rth": {
      "type": "boolean",
      "description": "New session scope: true = extended hours, false = regular hours only"
    },
    "name": {
      "type": "string",
      "description": "New alert name"
    }
  },
  "required": [
    "alert_id"
  ]
}
```

## get_watchlists

**description:** List all IBKR watchlists and their contents.

**input_schema:**
```json
{
  "type": "object",
  "properties": {},
  "required": []
}
```

## get_order_status

**description:** Get the status and details of a specific order by its order ID.

**input_schema:**
```json
{
  "type": "object",
  "properties": {
    "order_id": {
      "type": "string",
      "description": "IBKR order ID"
    }
  },
  "required": [
    "order_id"
  ]
}
```

## delete_cache

**description:** Delete a specific dataset from the Google Drive cache. Use when cached data is stale and needs to be re-fetched.

**input_schema:**
```json
{
  "type": "object",
  "properties": {
    "symbol": {
      "type": "string",
      "description": "Ticker symbol"
    },
    "timeframe": {
      "type": "string",
      "description": "Bar size, e.g. 1D, 1H"
    },
    "period": {
      "type": "string",
      "description": "Lookback period, e.g. 1Y, 6M"
    },
    "end": {
      "type": "string",
      "description": "End date YYYY-MM-DD"
    }
  },
  "required": [
    "symbol",
    "timeframe",
    "period",
    "end"
  ]
}
```

## firecrawl_search

**description:** Search the web using Firecrawl and return full page content as markdown. Use for research, news, or fetching technical documentation. Optionally saves a Drive snapshot under web_docs/searches/ for later reference. Requires FIRECRAWL_API_KEY to be set.

**input_schema:**
```json
{
  "type": "object",
  "properties": {
    "query": {
      "type": "string",
      "description": "Search query"
    },
    "limit": {
      "type": "integer",
      "description": "Max results to return (1-10, default 5)",
      "default": 5
    },
    "save_to_drive": {
      "type": "boolean",
      "description": "If true, save a markdown snapshot to Drive (default false)",
      "default": false
    }
  },
  "required": [
    "query"
  ]
}
```

## firecrawl_crawl

**description:** Crawl an entire website starting from a URL and save all pages to Drive under web_docs/{url-slug}/. Returns a summary of pages saved. Crawls are asynchronous — Firecrawl polls until done or timeout. Use for archiving IBKR documentation or other reference sites. Requires FIRECRAWL_API_KEY to be set.

**input_schema:**
```json
{
  "type": "object",
  "properties": {
    "url": {
      "type": "string",
      "description": "Root URL to crawl from (public http/https only)"
    },
    "max_pages": {
      "type": "integer",
      "description": "Maximum pages to crawl (1-100, default 50)",
      "default": 50
    },
    "timeout_s": {
      "type": "integer",
      "description": "Max seconds to wait for crawl to complete (default 120)",
      "default": 120
    }
  },
  "required": [
    "url"
  ]
}
```

