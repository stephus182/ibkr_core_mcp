# Official Documentation URLs — All External APIs

**IBKR Client Portal API** (`client.py`, `rate_limiter.py`, `claude_tools.py`)

| Topic | URL |
|---|---|
| **Client Portal API reference** (all CP endpoints) | https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/ |
| **Web API reference** | https://www.interactivebrokers.com/campus/ibkr-api-page/webapi-ref/ |
| **Orders / modify** (two-call pattern, field names) | https://www.interactivebrokers.com/campus/trading-lessons/request-modify-orders/ |
| **IBKR Campus** (general) | https://www.interactivebrokers.com/campus/ibkr-api-page/ |

**IBKR Flex Web Service** (`flex_query.py`)

| Topic | URL |
|---|---|
| **Flex Web Service setup** (endpoints, params, headers) | https://www.ibkrguides.com/clientportal/performanceandstatements/flex3.htm |
| **Flex Web Service error codes** (all 21 codes, last updated 2025-08-18 — re-verified live 2026-07-10, corrected from a stale 2025-10-03 note) | https://www.ibkrguides.com/clientportal/performanceandstatements/flex3error.htm |
| **Enable Flex Web Service** (one-time token + query setup) | https://www.ibkrguides.com/clientportal/performanceandstatements/flex-web-service.htm |
| **Configure Flex with AI** (natural-language Flex Query builder, last updated 2026-05-07) | https://www.ibkrguides.com/clientportal/configure-flex-with-ai.htm |

**IBKR WebSocket Streaming** (`streaming.py`)

| Topic | URL |
|---|---|
| **WebSocket API reference** (subscriptions, message format) | https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#websockets |
| **Market data subscriptions** (fields, tick types) | https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#market-data |
| **Trades subscription** (`str`/`utr`, execution fields) | https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#ws-trades-sub |
| **P&L subscription** (`spl`/`upl`, account P&L fields) | https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#ws-pnl-sub |

**Google Drive API v3** (`cache.py`)

| Topic | URL |
|---|---|
| **Drive API v3 reference** (files, upload, download) | https://developers.google.com/drive/api/reference/rest/v3 |
| **Python client library** (MediaIoBaseUpload, MediaIoBaseDownload) | https://googleapis.github.io/google-api-python-client/docs/dyn/drive_v3.html |
| **OAuth2 credentials** (token refresh, scopes) | https://google-auth.readthedocs.io/en/master/reference/google.oauth2.credentials.html |

**macOS LocalAuthentication** (`human_auth.py`)

| Topic | URL |
|---|---|
| **LAPolicy reference** (biometric policy constants) | https://developer.apple.com/documentation/localauthentication/lapolicy |
| **evaluatePolicy** (method, error codes) | https://developer.apple.com/documentation/localauthentication/lacontext/evaluatepolicy(_:localizedreason:reply:) |

**Web Scraping — Firecrawl + Crawl4AI fallback** (`web_scraper.py`, `scrape_fallback.py`)

| Topic | URL |
|---|---|
| **Firecrawl API reference** (scrape/search/crawl endpoints) | https://docs.firecrawl.dev/api-reference/endpoint/scrape , https://docs.firecrawl.dev/api-reference/endpoint/crawl-get |
| **Crawl4AI docs** (optional fallback; no built-in confidence score on Firecrawl side — confirmed 2026-06-30) | https://docs.crawl4ai.com/ |
| **Crawl4AI identity-based crawling** (`BrowserProfiler`, `BrowserConfig(use_managed_browser, user_data_dir)`) | https://docs.crawl4ai.com/advanced/identity-based-crawling/ |
| **Crawl4AI installation** (`crawl4ai-setup` post-install step) | https://docs.crawl4ai.com/core/installation/ |

`crawl4ai>=0.5.0` is a hard floor, verified against the published wheels on PyPI
(2026-06-30): `BrowserProfiler` does not exist in the 0.4.x series (checked 0.4.248,
the newest 0.4.x release) — it was introduced in 0.5.0. `crawl4ai<0.5.0` will import
successfully but raise `Crawl4AIUnavailableError` with a misleading "not installed"
message when `create_profile()` is actually called, since that message is only
generated from an `ImportError` on `BrowserProfiler`.
