# Official Documentation URLs — All External APIs

> **IBKR relocated their Web API documentation (found 2026-07-25).** Every link below is
> already repointed. The old base — `interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/`,
> a single ~800 KB page — is now a Fern-hosted site at `interactivebrokers.com/docs/web-api/`.
>
> **The old URLs still return HTTP 200.** They redirect to the new Introduction page and drop
> the `#anchor` en route, so a stale deep link looks healthy to a link checker while sending
> the reader to the wrong page. Treat any surviving `cpapi-v1/#…` reference as broken
> regardless of its status code.
>
> Fastest ways to verify a claim against the new site:
>
> | Method | URL |
> |---|---|
> | Clean markdown of any page | append `.md` to the page URL |
> | Full documentation index (517 pages) | https://www.interactivebrokers.com/docs/web-api/llms.txt |
> | MCP server (Claude Code, Cursor, …) | https://ibkrcampus.com/docs/web-api/_mcp/server |
>
> `FirecrawlClient.crawl()` returns 0 pages on `interactivebrokers.com` — the host needs
> Firecrawl's `waitFor`/`proxy` options, which the client does not expose, and it fails
> silently rather than signalling the block. Use the `.md` / `llms.txt` routes instead.

**IBKR Client Portal API** (`client.py`, `rate_limiter.py`, `claude_tools.py`)

| Topic | URL |
|---|---|
| **Client Portal API reference** (all CP endpoints — cited per-endpoint throughout `client.py`, see `docs/api-reference.md`) | https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/introduction |
| **Pacing limitations** (global 10 req/s + the per-endpoint table; backs `rate_limiter.py`) | https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/pacing-limitations |
| **Web API changelog** (field/behavior changes, e.g. Dec 2025 snapshot fields, May 2025 FUT/FOP `manualIndicator`/`extOperator` requirement) | https://www.interactivebrokers.com/docs/web-api/changelog |
| **Orders / modify / cancel** (two-call pattern, field names) | https://www.interactivebrokers.com/campus/trading-lessons/request-modify-orders/ |
| **GTC order lifecycle** (quarter-end auto-cancel behavior) | https://www.interactivebrokers.com/campus/trading-lessons/mosaic-good-till-cancelled-gtc-order-type/ |
| **IBKR Campus** (general) | https://www.interactivebrokers.com/campus/ibkr-api-page/ |
| **Historical market data limitations** (TWS API — 50 concurrent request cap, BID_ASK 2x weighting) | https://interactivebrokers.github.io/tws-api/historical_limitations.html |

**IBKR Flex Web Service** (`flex_query.py`)

| Topic | URL |
|---|---|
| **Flex Web Service setup** (endpoints, params, headers) | https://www.ibkrguides.com/clientportal/performanceandstatements/flex3.htm |
| **Flex Web Service error codes** (20 official codes — 1001, 1003-1021, no 1002 — last updated 2025-08-18, re-verified live 2026-07-14; `flex_query.py`'s `_FLEX_ERROR_CODES` carries a 21st entry, 1025, explicitly commented as observed in practice but not in this official table) | https://www.ibkrguides.com/clientportal/performanceandstatements/flex3error.htm |
| **Enable Flex Web Service** (one-time token + query setup) | https://www.ibkrguides.com/clientportal/performanceandstatements/flex-web-service.htm |
| **Configure Flex with AI** (natural-language Flex Query builder, last updated 2026-05-07) | https://www.ibkrguides.com/clientportal/configure-flex-with-ai.htm |
| **Flex Queries — landing page** (navigation index only: Run/Create/Edit Flex Query links, delivery settings, 4-year retention note — live-fetched 2026-07-14; kept as a general Flex-Queries pointer, no longer cited as the source for the "all trade origins" claim below; institutional equivalent at `orgportal/performanceandstatements/flex.htm` if this package ever needs to support orgportal accounts) | https://www.ibkrguides.com/clientportal/performanceandstatements/flex.htm |
| **Activity Statements** (account-level reports, not per-platform logs — backs `flex_query.py`'s "What Flex covers" claim) | https://www.interactivebrokers.com/campus/glossary-terms/activity-statements/ |

**Citation fix (2026-07-14):** `flex_query.py`'s "## What Flex covers" docstring (and two copies
of the same claim in `claude_tools.py`) previously cited the orgportal landing page above as
`Source:` for "all trade origins are included (CP API, mobile app, TWS, web portal)." Live-fetching
that URL showed it's only a generic navigation index page — it never made an origin-completeness
claim, so the citation didn't back the text next to it. Reworded the claim to what's actually
sourced (Activity Statements are account-level reports, not per-platform logs — confirmed by the
Activity Statements glossary page above) and re-pointed `Source:` to that page; the specific
enumeration of origins (CP API, mobile, TWS, web portal) is attributed to this repo's own
separately-verified claim instead (`get_trades()`'s "Origin coverage — verified live 2026-07-06"
note in `client.py`), not re-presented as independently sourced from the glossary page.

**IBKR WebSocket Streaming** (`streaming.py`)

| Topic | URL |
|---|---|
| **WebSocket API reference** (connection, subscriptions, message format — also covers market-data `smd`/`umd` subscriptions, which IBKR does not document under a separate anchor) | https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/websockets/introduction |
| **Trades subscription** (`str`/`utr`, execution fields) | https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/websockets/order-position-operations/request-trades-data |
| **P&L subscription** (`spl`/`upl`, account P&L fields) | https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/websockets/order-position-operations/request-profit-loss |

**Google Drive API v3** (`cache.py`)

| Topic | URL |
|---|---|
| **Drive API v3 reference** (files, upload, download; `cache.py` also cites the `files.list` sub-page directly) | https://developers.google.com/drive/api/reference/rest/v3 , https://developers.google.com/drive/api/reference/rest/v3/files/list |
| **Python quickstart** (OAuth flow, `InstalledAppFlow`) | https://developers.google.com/drive/api/quickstart/python |
| **OAuth2 credentials** (token refresh, scopes) | https://google-auth.readthedocs.io/en/stable/reference/google.oauth2.credentials.html |

**macOS LocalAuthentication** (`human_auth.py` — Gate 1) **and AppleScript** (`order_confirm.py` — Gate 2)

| Topic | URL |
|---|---|
| **LAPolicy reference** (biometric policy constants, incl. `LAPolicyDeviceOwnerAuthentication`) | https://developer.apple.com/documentation/localauthentication/lapolicy |
| **evaluatePolicy** (method, error codes) | https://developer.apple.com/documentation/localauthentication/lacontext/evaluatepolicy(_:localizedreason:reply:) |
| **AppleScript `display dialog`** (Gate 2's visual confirmation mechanism) | https://developer.apple.com/library/archive/documentation/AppleScript/Conceptual/AppleScriptLangGuide/reference/ASLR_cmds.html |

`human_auth.py` itself has no inline `Source:` comment citing these — the two URLs above are the
correct canonical references for `LAPolicyDeviceOwnerAuthentication` and the pyobjc-bound
`evaluatePolicy_localizedReason_reply_` it calls, but that mapping currently lives only here,
not in the code.

**Anthropic API** (`claude_tools.py`)

| Topic | URL |
|---|---|
| **Tool use** (schema conventions `TOOL_DEFINITIONS` follows) | https://platform.claude.com/docs/en/docs/build-with-claude/tool-use |
| **Messages API** (request/response shape `ClaudeToolkit.execute()` is designed around) | https://platform.claude.com/docs/en/api/messages |

`docs.anthropic.com` now 301-redirects to `platform.claude.com` for both pages above
(re-verified live 2026-07-14) — updated to the new canonical domain.

**Web Scraping — Firecrawl + Crawl4AI local** (`web_scraper.py`, `local_browser.py`)

| Topic | URL |
|---|---|
| **Firecrawl API reference — v1** (search/crawl endpoints — `web_scraper.py`'s `BASE_URL` is `https://api.firecrawl.dev/v1`; it only calls `POST /v1/search` and `POST /v1/crawl` + `GET /v1/crawl/{id}`, never `/v1/scrape`. The bare `docs.firecrawl.dev/api-reference/endpoint/...` paths now render **v2** docs — use the `/v1/...`-prefixed paths below, re-verified live 2026-07-14, to match what this repo actually targets) | https://docs.firecrawl.dev/v1/api-reference/endpoint/search , https://docs.firecrawl.dev/v1/api-reference/endpoint/crawl-post , https://docs.firecrawl.dev/v1/api-reference/endpoint/crawl-get |
| **Crawl4AI docs — home** (OSS library, our rung 2; no built-in confidence score on the Firecrawl side — confirmed 2026-06-30. Site is labelled **v0.9.x**, matching PyPI 0.9.2) | https://docs.crawl4ai.com/ |
| **Crawl4AI — `llms-full.txt`** (243,158 B of `text/plain`. **Start here** for any OSS-library question. The same directory holds 13 modular topic files — `simple_crawling`, `config_objects`, `deep_crawling`, `extraction-llm`, `extraction-no-llm`, `docker`, `installation`, `cli`, `url_seeder`, `multi_urls_crawling`, `http_based_crawler_strategy`, `deep_crawl_advanced_filters_scorers` — plus `diagrams/` variants; mirrored in the repo under `docs/md_v2/assets/llm.txt/`) | https://docs.crawl4ai.com/assets/llm.txt/txt/llms-full.txt |
| **Crawl4AI — complete SDK reference** (same material as `llms-full.txt` but served as ~988 KB of HTML, not plain text — prefer the file above) | https://docs.crawl4ai.com/complete-sdk-reference/ |
| **Crawl4AI — docs sitemap** (the machine-readable index: 87 pages) | https://docs.crawl4ai.com/sitemap.xml |
| **Crawl4AI identity-based crawling** (`BrowserProfiler`, `BrowserConfig(use_managed_browser, user_data_dir)`) | https://docs.crawl4ai.com/advanced/identity-based-crawling/ |
| **Crawl4AI anti-bot / fallback, undetected browser, proxy & security** (directly relevant to rung 2's job — beating blocks locally before the paid rung is reached) | https://docs.crawl4ai.com/advanced/ |
| **Crawl4AI installation** (`crawl4ai-setup` post-install step) | https://docs.crawl4ai.com/core/installation/ |
| **Crawl4AI CHANGELOG** (confirms `BrowserProfiler`'s introduction — see below) | https://github.com/unclecode/crawl4ai/blob/main/CHANGELOG.md |
| **Crawl4AI migration guides** (webscraping-strategy, and table extraction v0.7.3. **Neither affects this repo** — `local_browser.py` uses only `AsyncWebCrawler`, `BrowserConfig` and `BrowserProfiler`, none of the migrated APIs. Checked 2026-07-28 so a future reader need not re-check) | https://docs.crawl4ai.com/migration/webscraping-strategy-migration/ , https://docs.crawl4ai.com/migration/table_extraction_v073/ |

⚠️ **Four products share the name "Crawl4AI".** Only the first is used here: the **OSS
library** (PyPI `crawl4ai`, rung 2 and `fetch_page`). The others are **Crawl4AI Cloud**
(`api.crawl4ai.com`, a hosted credit-billed REST API), **`crawl4ai-cloud-sdk`** (PyPI, the
vendor's client for it), and the **`janbuchar/crawl4ai` Apify Actor**. Cloud was built and
then removed on 2026-07-28 — see §5.1 of `docs/web-scraper-reference.md` for why, and for
the API facts learned before it went, which are recorded there rather than here because
nothing in this repo calls that API any more.

`crawl4ai>=0.5.0` is a hard floor, verified against the published wheels on PyPI
(2026-06-30): `BrowserProfiler` does not exist in the 0.4.x series (checked 0.4.248,
the newest 0.4.x release) — it was introduced in 0.5.0. `crawl4ai<0.5.0` will import
successfully but raise `Crawl4AIUnavailableError` with a misleading "not installed"
message when `create_profile()` is actually called, since that message is only
generated from an `ImportError` on `BrowserProfiler`. Confirmed 2026-07-14 (follow-up
plan Task 5) against Crawl4AI's own CHANGELOG (fetched via `FirecrawlClient.crawl()`
from `raw.githubusercontent.com/unclecode/crawl4ai/main/CHANGELOG.md`): the entry for
**Version 0.5.0 (2025-03-02)** lists under "Added" — `*(profiles)* Add BrowserProfiler
class for dedicated browser profile management` — matching the PyPI-wheel finding
exactly and dating the introduction precisely.

---

## Missing URLs / known gaps (live-verification pass, 2026-07-14)

Pages this repo's citations point at, or should plausibly point at, but that this pass could not
fully resolve — listed for a future pass rather than guessed at now:

- **A clientportal-scoped Flex Queries overview page — resolved 2026-07-14 (follow-up plan
  Task 4).** `https://www.ibkrguides.com/clientportal/performanceandstatements/flex.htm` exists
  (HTTP 200, fetched via `FirecrawlClient.crawl()`) and is the exact retail-portal equivalent of
  the orgportal page previously cited: identical structure and prose (same "Instructions", "About
  Flex Queries", "Additional Resources" sections and last-updated date), with only the sub-page
  links (`clientportal/...` vs `orgportal/...`) and the institutional-specific "Proprietary
  Interface"/"Proprietary Trading Groups" resource links (present on the orgportal page, replaced
  by "Client Portal" resource links on this one) differing. Since `ibkr_core_mcp` talks to
  individual brokerage accounts via the CP API (not institutional orgportal accounts), the
  clientportal page is the better fit and now **replaces** the orgportal row above for consistency
  with every other Flex citation in this table — both pages carry equivalent information, so
  listing both was judged unnecessary.
- **An official IBKR page that explicitly enumerates "Activity Statements include trades placed
  via CP API, mobile, TWS, and web portal."** The Activity Statements glossary page (line 20)
  confirms statements are account-level (not per-platform), but no single fetched page spells out
  all four origins together for Flex specifically — the enumeration currently rests on this
  repo's own live-verified `get_trades()` observation, not an IBKR citation. See the "Citation
  fix" note above.

  **Follow-up search, still empty (2026-07-14, follow-up plan Task 3):** re-searched specifically
  for this enumeration via `FirecrawlClient.search()` (the same sanctioned method
  `ClaudeToolkit.firecrawl_search` wraps), using these query phrasings:
  - "IBKR Flex Activity Statement all order origins TWS mobile API"
  - "Interactive Brokers Activity Statement trade origin completeness"
  - "Interactive Brokers Flex Query includes trades from all trading platforms"
  - "IBKR Activity Statement CP API mobile TWS web portal trades included"
  - "IBKR trade confirmation report all order entry platforms consolidated"
  - "Interactive Brokers statements reflect trades regardless of order entry method"
  - "IBKR API trades endpoint origin mobile TWS web CP API"
  - "Interactive Brokers Client Portal API trades vs TWS mobile consolidated reporting"

  Fetched full markdown (via `FirecrawlClient.crawl()`) of every plausible result:
  - `interactivebrokers.com/campus/ibkr-api-page/flex-web-service/` (Flex Web Service page)
  - `interactivebrokers.com/campus/glossary-terms/activity-flex-query/`
  - `interactivebrokers.com/campus/glossary-terms/trade-confirmation-flex-query/`
  - `interactivebrokers.com/campus/glossary-terms/default-trades-flex-query/`
  - `interactivebrokers.com/campus/glossary-terms/statement-type/`
  - `interactivebrokers.com/campus/glossary-terms/trade-confirmation-report/` (glossary
    definition, distinct from the instructions page below)
  - `ibkrguides.com/orgportal/performanceandstatements/typestatement.htm` ("Types of Statements")
  - `ibkrguides.com/orgportal/performanceandstatements/activityflex.htm` ("Create an Activity
    Flex Query")
  - `ibkrguides.com/orgportal/performanceandstatements/tradeflex.htm` ("Trade Confirmation Flex
    Queries")
  - `ibkrguides.com/adminportal/performanceandstatements/runtradeconfirm.htm` ("Trade
    Confirmation Report" — step-by-step run instructions, distinct from the glossary entry above)
  - `interactivebrokers.com/campus/trading-lessons/client-portal-reporting/` ("Reporting Tools"
    trading lesson)
  - `interactivebrokers.ie/en/whyib/reporting.php` (reporting overview)
  - `interactivebrokers.com/webinars/Statements_Trade_Confirmations.pdf` (older webinar deck —
    its closest hit, "Trade Confirmation Reports: intraday trade confirmations for all orders,"
    says "all orders" but never names CP API, mobile, TWS, or web portal, and the deck predates
    the CP API entirely: no `API`, `TWS`, or `platform` keyword occurs anywhere in its text)

  None of the above enumerate the four origins together. Conclusion unchanged — see the parent
  bullet and the "Citation fix" note above; no citation was replaced with a guessed URL.
- **`docs.firecrawl.dev/v1/api-reference/endpoint/scrape`** — not fetched (code never calls
  `/v1/scrape`, so not needed for verification), but would complete the picture if ever added as a
  contrast citation explaining why this repo doesn't use it.
- **Re-tested 2026-07-14 (follow-up plan Task 1, `docs/plans/2026-07-14-doc-improvement-upgraded-scraper-plan.md`)
  through the upgraded `ClaudeToolkit.firecrawl_crawl`** (retry-with-backoff and the Drive
  read-cache were both exercised — the latter via `get_cached_crawl`'s pre-check on every call, the
  former by an observed `HTTP 429` on one call that retried and succeeded moments later. Crawl4AI
  fallback was *available* but not shown to have fired: its loop only runs over pages `crawl()`
  actually returned, which was empty for 4 of the 5 URLs, and for the one URL that did succeed
  (`platform.claude.com/docs/en/api/messages`) the tool output had no
  `"Crawl4AI fallback used for N page(s)..."` line — the large real-markdown yield suggests
  Firecrawl's own result was already complete and `assess_quality` never routed it to fallback;
  `max_pages=1` throughout), the "likely JS-rendered" guess above was wrong — the retry/cache
  upgrade didn't touch the actual cause, and it isn't JS rendering. `crawl()`'s poll loop
  (`web_scraper.py:299-333`) never surfaces Firecrawl's internal `total`/`completed` job-progress
  fields to its caller, only the final page list, so those aren't usable as sanctioned evidence —
  root cause for each URL below was instead confirmed with a plain, non-Firecrawl HTTP check
  (`curl -I -L` for redirects, a plain fetch of `robots.txt`) to find where the URL actually leads,
  then that destination was re-confirmed as fetchable via `ClaudeToolkit.firecrawl_crawl` itself
  (sanctioned, no raw Firecrawl API calls):
  - `developers.google.com/drive/api/reference/rest/v3/files/list` and
    `developers.google.com/drive/api/quickstart/python` — `curl -I -L` shows both return `HTTP 301`
    with `Location: /workspace/drive/api/...`, i.e. both permanently redirect to a
    `developers.google.com/workspace/drive/api/...` path (Google's Workspace-docs migration;
    confirmed live 2026-07-14). `ClaudeToolkit.firecrawl_crawl` still returns 0 pages for the
    pre-redirect seed URL, but called directly on the post-redirect URLs
    (`.../workspace/drive/api/reference/rest/v3/files/list` and
    `.../workspace/drive/api/quickstart/python`) it reports `"Crawl complete: saved 1 page(s) from
    {url} to Drive."` for both (verified live 2026-07-14). The doc citations above still point at
    the pre-redirect URLs deliberately — they're not broken links (a browser or `WebFetch` follows
    the redirect fine) — but `FirecrawlClient.crawl()` cannot resolve them without either following
    the redirect itself before calling `/v1/crawl`, or being pointed at the canonical post-redirect
    URL.
  - `google-auth.readthedocs.io/en/stable/reference/google.oauth2.credentials.html` — a plain fetch
    of `google-auth.readthedocs.io/robots.txt` shows an explicit `Disallow: /en/stable/` line (and
    `/en/master/`, both marked "Hidden version"; confirmed live 2026-07-14). `ClaudeToolkit.firecrawl_crawl`
    still returns 0 pages for this URL. The equivalent un-disallowed path,
    `google-auth.readthedocs.io/en/latest/reference/google.oauth2.credentials.html` (not matched by
    any `Disallow` rule), returns `"Crawl complete: saved 1 page(s) from {url} to Drive."` via the
    same sanctioned call (verified live 2026-07-14) — same underlying content, no robots block.
    This is a genuine, working robots.txt restriction, not a bug in this repo's code; `WebFetch`
    doesn't honor `robots.txt` the same way, which is why it got content anyway last pass.
  - `platform.claude.com/docs/en/docs/build-with-claude/tool-use` — `curl -I -L` shows two chained
    `HTTP 307` redirects (`/docs/en/docs/build-with-claude/tool-use` →
    `/docs/en/build-with-claude/tool-use` → `/docs/en/agents-and-tools/tool-use/overview`; confirmed
    live 2026-07-14), same out-of-scope-redirect cause as the Drive URLs above. Called directly on
    the final `/docs/en/agents-and-tools/tool-use/overview` target, `ClaudeToolkit.firecrawl_crawl`
    reports `"Crawl complete: saved 1 page(s) from {url} to Drive."` (verified live 2026-07-14);
    its content (tool-use overview, schema/round-trip conventions) matches this repo's existing
    citation description — no doc change needed. The pre-redirect URL cited above is still correct
    to keep citing (it's a working, permanent redirect for a browser or `WebFetch`), just not
    resolvable by `FirecrawlClient.crawl()` as-is.
  - `platform.claude.com/docs/en/api/messages` — **now succeeds directly**: `curl -I -L` shows a
    plain `HTTP 200`, no redirect involved. `ClaudeToolkit.firecrawl_crawl` returned
    `"Crawl complete: saved 1 page(s) from {url} to Drive."` (~1.39MB of real markdown, verified
    live 2026-07-14); content is the Messages API schema reference, consistent with the existing
    citation's description — no discrepancy found.

  Net: of the original 5, 1 now succeeds outright (Messages API — no redirect to trip over) and the
  other 4 have a confirmed, specific cause (redirect-scope or robots.txt), not a vague JS-rendering
  guess. None of these are addressed by the retry-with-backoff/Drive-cache upgrade, since none of
  them were rate-limit or repeat-fetch problems — fixing the redirect-scope gap (if ever prioritized)
  would mean either following the seed URL's redirect chain before calling `/v1/crawl`, or having
  callers pass the canonical post-redirect URL directly; the robots.txt block is not something to
  "fix" at all — it's a real crawling restriction to respect, not this repo's error.

**Resolved 2026-07-14 (follow-up plan Task 2):** `FirecrawlClient.crawl()`'s poll loop previously
never followed the `next` pagination cursor Firecrawl's `GET /crawl/{id}` response includes for
crawls whose completed result exceeds 10MB, silently truncating large crawls to the first chunk
despite the method's own "returns all pages collected" docstring claim. Fixed via TDD, bounded by
a chunk cap, a seen-URL cycle guard, and the caller's own `timeout_s` deadline.
