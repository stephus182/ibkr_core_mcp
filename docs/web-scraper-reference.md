# Web Scraper Reference

Firecrawl (hosted, paid) for search and crawling, then two fallbacks that recover what Firecrawl
can't reach: Crawl4AI local (free, Playwright-based) and Crawl4AI Cloud (hosted, paid, managed
proxies). This document covers all three layers, every tunable, the credit-cost model,
paywalled-site logins, and what to do when a scrape comes back empty.

---

## 1. The three layers

| Layer | Module | Cost | What it's good at |
|---|---|---|---|
| **Firecrawl** | `web_scraper.py` | Paid, per-credit | Web *search* (nothing else here provides it), fast bulk crawling, clean markdown extraction |
| **Crawl4AI local** | `scrape_fallback.py` | Free, local | Pages Firecrawl can't get: bot-blocked sites, and paywalled sites where you hold a subscription |
| **Crawl4AI Cloud** | `crawl4ai_cloud.py` | Paid, per-credit | The one case local can't solve: an IP-level block or challenge aimed at *this machine's* address, which managed/residential proxies defeat |

Do not confuse the two Crawl4AI layers. `scrape_fallback.Crawl4AIScraper` runs a browser on this
machine; `crawl4ai_cloud.Crawl4AICloudClient` is an HTTP client for a hosted API. They share a
vendor name and nothing else.

### 1.1 Four different things are called "Crawl4AI"

Searching for Crawl4AI docs returns all four. Only the first two are used here, and picking the
wrong one sends you to an API that does not match the code in front of you. Surveyed 2026-07-28.

| # | Thing | What it is | Used here? |
|---|---|---|---|
| 1 | **`crawl4ai` OSS library** (PyPI, 0.9.2 as of 2026-07-15) | Playwright-based crawler that runs locally. Docs: `docs.crawl4ai.com` (v0.9.x) | **Yes — rung 2**, via `scrape_fallback.py` |
| 2 | **Crawl4AI Cloud** (`api.crawl4ai.com`) | The vendor's hosted REST API, credit-billed. Docs: `llms-full.txt` | **Yes — rung 3**, via `crawl4ai_cloud.py` |
| 3 | **`crawl4ai-cloud-sdk`** (PyPI, 1.2.0) | The vendor's own Python client for #2 | **Adopting** — see §5.2 |
| 4 | **`janbuchar/crawl4ai` Apify Actor** | A community wrapper around #1, run on Apify's platform | **No — rejected, see §5.1** |

They also differ in *documentation shape*, which matters under this repo's API-docs-first rule:

- #1 **does publish `llms-full.txt`** — 243,158 bytes of `text/plain` at
  <https://docs.crawl4ai.com/assets/llm.txt/txt/llms-full.txt>, mirrored in the repo under
  `docs/md_v2/assets/llm.txt/txt/`. Beside it sit **13 modular topic files** (`simple_crawling`,
  `config_objects`, `deep_crawling`, `deep_crawl_advanced_filters_scorers`, `extraction-llm`,
  `extraction-no-llm`, `multi_urls_crawling`, `url_seeder`, `http_based_crawler_strategy`,
  `docker`, `installation`, `cli`), all served as `text/plain`, plus `diagrams/` variants. These
  are the pieces the site's "LLM Context Builder" assembles. **Prefer these over
  `complete-sdk-reference/`**, which is the same material wrapped in ~988 KB of HTML.
  What genuinely does not exist is an **index at the conventional root**: `/llms.txt` and
  `/llms-full.txt` both 404, and the 404 body is a 31 KB HTML page — so a probe that only checks
  for non-empty content "succeeds" and hands back a navigation shell.
- #2 publishes `llms-full.txt` at its root, and its human `/docs/...` pages are the opposite
  failure — a JavaScript SPA returning a 696-byte shell to `curl`.

> **This section was wrong when first written, and the mistake is worth keeping.** It claimed #1
> shipped no `llms.txt` at all. That came from probing two guessed root paths, getting 404s, and
> concluding absence — without opening the repository, where the files are plainly visible under
> `docs/md_v2/assets/`. A 404 at a guessed path is evidence about that path, not about the vendor.
> **Check the source repo before concluding a vendor does not ship something**, especially when
> the 404 body is itself a valid-looking HTML page.

Orchestration between them lives in `claude_tools.py`. That split is deliberate: `web_scraper.py`
never imports `scrape_fallback.py`, so the Firecrawl client stays a pure protocol wrapper.

**Two tools are exposed to the model:**

| Tool | Use it for |
|---|---|
| `firecrawl_search` | "Find me pages about X." Returns full markdown for each hit. Optionally snapshots to Drive. |
| `firecrawl_crawl` | "Archive this site." Crawls from a root URL and always saves to Drive under `web_docs/{url-slug}/`. |

There is no single-page scrape tool. To archive one page, call `firecrawl_crawl` with
`max_pages=1`.

---

## 2. Configuration

| Env var | Field | Required for | Default |
|---|---|---|---|
| `FIRECRAWL_API_KEY` | `firecrawl_api_key` | Both tools. Without it they return "not available" rather than raising. | — |
| `ANTHROPIC_API_KEY` | `anthropic_api_key` | The completeness judge (section 3.2) | — (required by `Config` itself) |
| `GOOGLE_DRIVE_FOLDER_ID` | `gdrive_folder_id` | Drive persistence, unless `GDRIVE_WEB_DOCS_FOLDER_ID` is set | — |
| `GDRIVE_WEB_DOCS_FOLDER_ID` | `gdrive_web_docs_folder_id` | Overrides the `web_docs/` root | auto-created under `gdrive_folder_id` |
| `GDRIVE_TOKEN_FILE` | `gdrive_token_file` | Drive OAuth | `~/.ibkr_core/token.json` |
| `GDRIVE_CREDENTIALS_FILE` | `gdrive_credentials_file` | Drive OAuth | `~/.ibkr_core/credentials.json` |
| `CRAWL4AI_PROFILES_DIR` | `crawl4ai_profiles_dir` | Paywalled-site logins (local layer) | `~/.ibkr_core/crawl4ai_profiles` |
| `CRAWL4AI_API_KEY` | `crawl4ai_api_key` | The Cloud rung. **Without it the rung is skipped silently** and the ladder behaves exactly as it did when it had two rungs. | — |
| `CRAWL4AI_API_URL` | `crawl4ai_api_url` | Overriding the Cloud base URL (staging) | `https://api.crawl4ai.com` |

Crawl4AI is an optional extra. Without it, the fallback layer reports itself unavailable and
Firecrawl's result is returned as-is:

```bash
pip install "ibkr_core_mcp[scraper]"
crawl4ai-setup                 # installs the Playwright browser
```

**Developing this package standalone.** With no `.env` here, both tools correctly report "not
configured" and never touch Drive. To exercise Drive caching while working on `ibkr_core_mcp` in
isolation, a local `.env` in this repo is fine — it is gitignored. Only four vars are needed, and
`GOOGLE_DRIVE_FOLDER_ID` is not among them: `FIRECRAWL_API_KEY`, `GDRIVE_WEB_DOCS_FOLDER_ID` (an
existing `web_docs/` folder ID), `GDRIVE_TOKEN_FILE`, and `GDRIVE_CREDENTIALS_FILE` (reuse an
already-authenticated token to skip interactive OAuth). Verify with:

```bash
pytest tests/test_web_scraper_dev_cache_live.py -v -m integration
```

---

## 3. The recovery ladder

A crawl of a site that fights back used to return zero pages and report it as success. It now
falls back twice — paid remote, then free local, then paid remote again with managed proxies:

```text
firecrawl_crawl(url)
  │
  ├─ Rung 1: Firecrawl, one attempt                         ~1 credit/page
  │     ├─ >= 5 KB of markdown? ────────────────────────► save to Drive, done
  │     └─ anything else — thin, empty, job failed, timed out,
  │        401 / 402 / 429, network down ───────────────┐
  │                                                     │
  ├─ Rung 2: Crawl4AI scrapes the root URL locally  ◄────┘   free
  │     using a saved login profile if one matches
  │     ├─ >= 5 KB now? ────────────────────────────────► save to Drive, done
  │     └─ still short ─────────────────────────────────┐
  │                                                     │
  └─ Rung 3: Crawl4AI Cloud scrapes the root URL   ◄─────┘   1 credit (no proxy)
        skipped silently if CRAWL4AI_API_KEY is unset
        │
        └─ still nothing → explicit diagnosis naming EACH rung's
                           failure, never "saved 0 page(s)"
```

**Why the paid cloud rung goes last, behind the free local one.** On the only real failure
observed to date (2026-07-28, the IBKR campus reference), Firecrawl returned 0 pages and thinned
another page to a nav shell, and a plain fetch 403'd — while local Crawl4AI fetched both cleanly,
144,125 chars from the page that settled the whole symbology question. The free rung was the one
that worked. A paid rung ahead of it would have spent credits to be overtaken by something free.

The asymmetry decides it. Cloud-before-local wastes the daily budget on pages local already
serves. Local-before-cloud costs one extra local attempt — seconds, free — before reaching the
rung that can beat an IP block. What Cloud is *for* is the case local cannot solve: a block aimed
at this machine's own address. That is a last resort, not a second one.

**Why only one Firecrawl attempt.** Firecrawl's Free tier allows **2** `/crawl` requests per
minute (<https://docs.firecrawl.dev/rate-limits>, verified 2026-07-25). An automatic stealth
retry would spend a whole minute's budget on one URL and rate-limit the very next call — so the
second attempt would frequently *cause* the failure it was meant to fix. The local rung is free,
runs immediately, and needs no budget at all, so it is the better place to go.

Stealth is not gone, just opt-in: pass `wait_for_ms=3000` and `proxy="auto"` when you know a host
needs them. See section 4.

### 3.1 The one rule

> **Fall back to the local scraper unless Firecrawl already returned 5 KB of markdown.**

The decision is a single measurement — `content_bytes(pages)`, the total UTF-8 size of all
extracted markdown — not a classification of how the attempt ended. Blocked, timed out, job
failed, and completed-empty all mean the same thing to a caller and take the same path.

**Why 5 KB.** Measured from this repo's own scrape cache in
`docs/audits/audit-evidence/scrapes/`:

| Artifact | Bytes | Reality |
|---|---|---|
| IBKR Akamai edge-block page | 152 | failure |
| `firecrawl-crawl-get-endpoint.md` | 12,933 | good content |
| `flex3error.htm` | 16,891 | good content |
| `flex3.htm` | 20,898 | good content |
| IBKR `request-modify-orders` | 91,918 | good content |

5 KB sits ~34× above the largest observed failure and ~2.5× below the smallest observed success.

**The fallback keeps the larger result, not the last one.** All three rungs are scored with the
same function and a later rung's result replaces an earlier one only if it is genuinely bigger. So a
legitimately short 3 KB page still measures "too small" and runs the local rung, but the output
stays correct — a thin Crawl4AI result can never silently replace a better Firecrawl one. The
cost of a short page is one free local fetch, never a wrong answer.

**Account-level failures fall back too.** HTTP 401 (bad key), 402 (out of credits), 429 (rate
limited) and a dead network all mean Firecrawl is unusable right now — which is precisely when a
free, local scraper is worth the most. The crawl does not abort; it drops to Crawl4AI and, if
that also comes back empty, names the Firecrawl failure in the final message so you know whether
to top up, wait, or fix a key.

### 3.2 The per-page fallback (search, and pages within a crawl)

Separately from the ladder, every individual page is graded by `assess_quality()`:

| Verdict | Trigger | Action |
|---|---|---|
| `fallback` | Metadata reports HTTP ≥ 400 or an error, **or** fewer than 40 words | Straight to Crawl4AI |
| `ambiguous` | A known paywall phrase is present, **or** 40–200 words | One cheap Haiku call (`judge_completeness_llm`) decides |
| `ok` | Everything else | Keep Firecrawl's content, no extra API call |

The judge only fires on the borderline band, so clean results cost nothing extra. A transient
judge failure fails safe — it keeps Firecrawl's content rather than escalating.

For a crawl, every fallback-needing page shares **one** Crawl4AI browser session rather than one
launch per page. That is safe because Firecrawl's crawl stays within one site, so every page
shares the same profile decision.

---

## 4. Every tunable

### `firecrawl_crawl`

| Parameter | Default | Range | Notes |
|---|---|---|---|
| `url` | — | required | Public http/https only. SSRF-validated before any request. |
| `max_pages` | 50 | clamped to [1, 100] | |
| `timeout_s` | derived | ≥ 10 | Whole polling budget. Derived as `min(600, max(120, 6 × max_pages))` — 120s up to 20 pages, 300s at 50, 600s at 100. |
| `force_refresh` | `false` | | Skip the Drive cache check (section 5). |
| `wait_for_ms` | none | | Advanced, opt-in. Milliseconds to wait for JS rendering. Try `3000` on a JS-rendered site that came back empty. |
| `proxy` | none | `basic`/`enhanced`/`auto` | Advanced, opt-in. Try `auto` on a site that blocks automated clients. |

`timeout_s` is **our polling patience, not Firecrawl's timeout.** The old fixed 120s default was
under-budgeted for its own 50-page default and could manufacture a "timed out with nothing" result
on a site that was merely slow.

**Worst-case wall clock** is `timeout_s` plus the Crawl4AI scrape — about 5½ minutes at
`max_pages=50` for a fully-blocked site. There is no second Firecrawl attempt to double it. If
you need tighter latency, pass `timeout_s` explicitly.

Neither `wait_for_ms` nor `proxy` is ever applied automatically. When they are unset they are
omitted from the request entirely, so a default call is byte-for-byte the request this client
sent before these parameters existed.

### `firecrawl_search`

| Parameter | Default | Range |
|---|---|---|
| `query` | — | required, non-empty |
| `limit` | 5 | clamped to [1, 10] |
| `save_to_drive` | `false` | |
| `wait_for_ms` | none | advanced |
| `proxy` | none | advanced |

Search has no root-URL fallback — it doesn't need one. Each result is graded and recovered
individually by section 3.2, and results are typically on different domains, so a whole-query
retry would be the wrong shape. Per-result markdown is truncated to 2,000 characters in the tool
output; the full text is what gets saved to Drive.

---

## 5. Credit-cost model

**Firecrawl (rung 1):**

| Setting | Cost |
|---|---|
| `proxy` unset or `basic` | 1 credit per page |
| `proxy: "enhanced"` | up to 5 credits per page |
| `proxy: "auto"` | 1 credit if basic succeeds; up to 5 if it retries through enhanced |

**Crawl4AI local (rung 2):** free — it runs on this machine.

**Crawl4AI Cloud (rung 3)** — measured live 2026-07-28 via `dry_run` estimates, which are
themselves free:

| `proxy` | Cost per scrape |
|---|---|
| omitted (what the ladder sends) | **1 credit** |
| `{"mode": "datacenter"}` | 2 credits |
| `{"mode": "residential", "country": "US"}` | 5 credits |

A crawl costs exactly one Firecrawl attempt. `enhanced`/`auto` are charged only when you ask for
them explicitly — nothing escalates you into the expensive path automatically, and rung 2 is free.
A site that works costs exactly what it cost before this feature existed.

### Rate limits and plans

Firecrawl enforces per-plan rate limits — as low as 1 request/minute for `/crawl` on the free
tier. The client retries 408/429/500/502/503/504 with exponential backoff plus jitter, honoring
`Retry-After` when present, capped at 30s and 3 attempts. Source:
<https://docs.firecrawl.dev/api-reference/errors>

Crawl4AI Cloud's plans, from `GET /v1/usage` and
<https://api.crawl4ai.com/llms-full.txt> (both read 2026-07-28):

| Plan | Requests/min | Daily credits | Concurrent |
|---|---|---|---|
| Free | 10 | 50 | 1 |
| Starter | 30 | 500 | 2 |
| Pro | 60 | 5,000 | 5 |

**This account is on Free as of 2026-07-28** — 50 credits/day, so ~50 no-proxy cloud scrapes a
day. Both scrapers are on free plans deliberately while this integration is tested, and either
may move to paid.

**No tier number above is encoded anywhere in the code, by design.** The daily allowance is read
from `plan.daily_credits` on `/v1/usage`, the per-call remainder from `usage.credits_remaining` in
the scrape response, and the low-balance warning fires below a *fifth of the reported allowance*
rather than below a credit count. "Warn under 10" is right for a 50/day plan and silently useless
on a 5,000/day one. An upgrade therefore needs no code change.

Two Crawl4AI behaviours differ from Firecrawl and will cost money if you assume otherwise:

- **429 means quota exhaustion, not backpressure.** `Crawl4AICloudClient` never retries — not
  429, not 503. Retrying would spend the daily budget to fail more slowly.
  `web_scraper._request_with_backoff` is deliberately *not* reused or parameterised; its
  retry-on-429 is correct for Firecrawl and wrong here.
- **`proxy` is an object, not a string.** `{"mode": ...}`, and the string `"direct"` is a hard
  422 (verified live). To scrape without a proxy, omit the field entirely.

**Serialise cloud calls.** The free plan allows 1 concurrent request. The ladder calls the cloud
rung once per crawl and is safe, but the search-result path launches up to
`_MAX_CONCURRENT_FALLBACKS = 5` local scrapes in parallel — if the cloud client is ever wired into
*that* path, it must serialise first or it will 429 against itself.

**Note for the eventual paid transition:** `web_scraper.py`'s comment about "Firecrawl Free
allows 2 `/crawl` per minute" is likewise a tier fact living in a comment. It becomes wrong on
upgrade. Not changed here, but recorded so the move to paid has a checklist rather than a hunt.

### 5.1 Alternatives evaluated and rejected

Recorded so nobody spends an afternoon re-evaluating them. Re-check the numbers before
reversing any of these — they are a snapshot, not a verdict for all time.

**`janbuchar/crawl4ai` Apify Actor** — <https://apify.com/janbuchar/crawl4ai>. A community
wrapper (not vendor-published) that runs the OSS library on Apify's platform, invoked with
`apify_client` and billed per usage. **Rejected 2026-07-28 on its own published run statistics**,
read from Apify's public API (`GET https://api.apify.com/v2/acts/janbuchar~crawl4ai`, no auth):

| Metric (Apify's own `stats`) | Value |
|---|---|
| Public runs, last 30 days | **0 succeeded**, 26 failed, 3 aborted, 29 total |
| Latest build | `0.0.57`, finished **2025-05-06** — over a year stale against OSS 0.9.2 |
| Reviews | rating 3.26, from **2 reviews** |
| Users | 787 all-time, but 25 in 90 days and 4 in the last 7 |
| `isDeprecated` flag | `false` — so the flag tells you nothing; the run stats do |

A rung whose upstream fails every public run is worse than no rung: it adds a paid dependency, a
third credential, and latency, in exchange for a failure. It also could not sit *between* our
rungs — it wraps the same OSS library rung 2 already runs locally and free, so at best it would
duplicate rung 2 while costing money, and it offers nothing rung 3's managed proxies do not.

Worth knowing: `isDeprecated: false` on a wrapper with a 0% success rate is exactly the sort of
"looks configured, is dark" signal this ladder exists to avoid trusting. Judge a hosted
dependency by its run statistics, not its status flag or star rating — 3.26 stars from two
reviewers said nothing, and the run stats said everything.

Other Apify actors wrapping Crawl4AI do have healthy success rates (e.g.
`bikram07/web-to-markdown-crawl4ai`, 33/41 in 30 days) but have single-digit user counts and no
vendor backing, so they trade our current dependency for a less-supported one.

**Self-hosting the OSS crawler — not evaluated, but the obvious free alternative to rung 3.**
Crawl4AI documents a self-hosting path (<https://docs.crawl4ai.com/core/self-hosting/>). Running
the OSS library on a remote box would give the *different IP* that is most of why rung 3 exists,
without per-credit billing. What it would **not** give is managed **residential** proxy rotation,
which is the part that beats a determined block — a single rented IP is itself easily blocked.
So it is a plausible cheaper middle rung, not a replacement for Cloud. Left unbuilt deliberately:
it adds a host to operate, and the ladder currently costs 1 credit only on pages two free rungs
already failed.

### 5.2 The vendor SDK is preferred over a hand-rolled client

**Standing preference: favour the vendor's own integration.** The first cut of
`crawl4ai_cloud.py` hand-rolled `POST /v1/scrape` on `requests`. `crawl4ai-cloud-sdk` (the
vendor's own client, PyPI 1.2.0) is the better base, and inspection confirms it does not cost us
any of the invariants this ladder depends on. Evaluated 2026-07-28 by reading its source, not its
README:

| Invariant we need | What the SDK does |
|---|---|
| **Never retry a 429** | `_client.py` raises on 429 **immediately**. The retry `continue` branches cover only 5xx, `httpx.TimeoutException` and `httpx.RequestError`. |
| Distinguish quota from rate limit | Better than ours: splits `RateLimitError` (with `.retry_after`, `.limit`, `.remaining`) from `QuotaExceededError` (with `.quota_type`). Our single error type could not. |
| `proxy` as an object, never `"direct"` | Native `ProxyConfig(mode, country, sticky_session)` plus a `normalize_proxy` helper; `scrape()` accepts `str | dict | ProxyConfig`. |
| Free request-shape validation | `dry_run=True` is a first-class parameter, routed through `_dry_run_estimate`, which returns the raw quote — the same scrape/estimate split we arrived at by trial. |
| Typed page result | `MarkdownResponse` carries `markdown`, `fit_markdown`, `metadata` and `usage` (`credits_used` / `credits_remaining`). |

Two things it does **not** solve, both of which we handle rather than inherit:

1. **It wraps no `/v1/usage` endpoint** — its endpoint set covers `/v1/crawl/storage` but not
   usage. The low-balance threshold in §5 must stay relative to `plan.daily_credits`, which only
   `/v1/usage` reports, so one small direct call is retained for that and documented as such.
2. **`max_retries` defaults to 3**, and while 429 is exempt, a retried *timeout* could re-issue a
   scrape the server already executed — billing the same page twice. We pass a value that
   disables retries, for the same budget reason the 429 rule exists.

Cost of adoption is near zero: `httpx`, the SDK's only substantial dependency, is already in the
tree via `anthropic`.

**There is no official Crawl4AI MCP server** for either the OSS library or Cloud — checked
2026-07-28 against the docs sitemap (87 pages, no MCP page) and the Cloud `llms-full.txt` (no
occurrence). Noted because this repo *is* an MCP project and the absence is otherwise easy to
mistake for "not found yet".

---

## 6. Paywalled sites (FT, WSJ, Bloomberg)

Crawl4AI can use a saved browser session, so a site you subscribe to returns full articles instead
of the subscription stub.

```bash
python -m ibkr_core_mcp.scrape_fallback create-profile https://www.ft.com
```

This opens a **real, visible browser**. Log in by hand, then confirm in the terminal. The
resulting cookies and local storage are copied to `~/.ibkr_core/crawl4ai_profiles/<domain>/`.

**No password is ever seen or stored by this package** — only the resulting browser session.
Nothing is transmitted anywhere; the profile is a local directory.

### Which profile applies to which URL

Lookup tries the most specific candidate first and broadens toward the registrable domain:

1. the exact hostname — `markets.ft.com`
2. the hostname without a leading `www.` — `ft.com`
3. progressively broader parents, while at least two labels remain — `markets.ft.com` → `ft.com`

So one profile created for `www.ft.com` serves `ft.com`, `markets.ft.com`, and any other
subdomain. Matching only ever broadens; a profile for `ft.com` is never used for an unrelated
host. Stopping at two labels means a directory named after a bare TLD can never match.

Multi-part suffixes (`ft.co.uk`) stop at `co.uk`, which will simply never match a saved profile —
create that profile under its exact hostname.

### Checking what you have

```bash
python -m ibkr_core_mcp.scrape_fallback list-profiles
```

Prints each saved domain, its path, and how many days old the session is. Sessions expire; when
one does, the symptom is a truncated article rather than an error. Re-run `create-profile` for
that domain.

---

## 7. Drive cache layout

`firecrawl_crawl` always persists. `firecrawl_search` persists only when `save_to_drive=true`.

```text
<gdrive_folder_id>/
  web_docs/                              ← or GDRIVE_WEB_DOCS_FOLDER_ID
    <url-slug>/                          ← one folder per crawled root URL
      index.json                         ← {url, crawled_at, pages: [{url, file_id}]}
      <page-slug>.md                     ← one file per page
    searches/
      <YYYYMMDDTHHMMSSZ>-<query-slug>.md
```

**Crawls are cached for 48 hours.** Before calling Firecrawl at all, `firecrawl_crawl` checks
Drive for an existing manifest for that URL. If one exists and is under 48h old, it returns the
cached result and makes **zero** Firecrawl requests. Pass `force_refresh=true` to override.

The 48h figure is this repo's own choice, using Firecrawl's v2 `maxAge` default (172,800,000 ms)
as an externally-validated reference point for "how fresh is fresh enough" for reference
documentation. Note the v1 API this client targets documents that parameter's default as `0`.

Slug collisions are handled: two URLs that slugify identically (`/a-b` and `/a_b`) get `-2`, `-3`
suffixes rather than overwriting each other.

---

## 8. Per-host notes

### Don't scrape IBKR's docs at all

This will save you more credits than every other item on this page combined. IBKR's Web API docs
are AI-friendly:

- **Append `.md` to any page URL** for clean markdown:
  `https://www.interactivebrokers.com/docs/web-api/<page>.md`
- **`https://www.interactivebrokers.com/docs/web-api/llms.txt`** is a complete 517-page index
- There is an MCP server at `https://ibkrcampus.com/docs/web-api/_mcp/server`

Use `WebFetch` on those. No Firecrawl credits, no bot-block, no ladder.

Note that the **old** doc URLs (`interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#anchor`)
still return HTTP 200 while silently redirecting to the new site's Introduction page and dropping
the anchor. A link checker reports success while the reader lands on the wrong page. Never cite
one.

### Host table

| Host | Behavior | What to do |
|---|---|---|
| `interactivebrokers.com` | Intermittent. An Akamai edge-block (152-byte error page) was observed 2026-07-02; on 2026-07-25 a plain Firecrawl attempt succeeded (17,346 B on `request-modify-orders`, 5,718 B on `/docs/web-api/`). Treat the block as something that comes and goes, not a permanent property. | Prefer `.md` URLs regardless — they cost no credits. If it does block, add `wait_for_ms=3000` + `proxy="auto"`, or let the local rung take it. |
| `ibkrguides.com` | Works on defaults | Nothing special |
| `docs.firecrawl.dev` | Works on defaults | Nothing special |
| FT / WSJ / Bloomberg / Barron's | Metered paywall; stub content without a session | `create-profile` once per domain (section 6) |

---

## 9. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| "not available: FIRECRAWL_API_KEY is not configured" | No key in the environment | Set `FIRECRAWL_API_KEY` in the consuming project's `.env` |
| "Crawl of … produced no content" | Every configured rung failed; the message names each cause | Check the host table. For a subscription site, `create-profile`. Try `wait_for_ms=3000` + `proxy="auto"`. For IBKR docs, use `.md` URLs. |
| That message says nothing about Crawl4AI Cloud | `CRAWL4AI_API_KEY` is unset, so rung 3 was skipped | Working as designed — the ladder stays silent about a rung you haven't configured. Set the key to enable it. |
| `Source: Crawl4AI Cloud (…)` | Both Firecrawl and the local rung came up short; the cloud rung rescued it | Nothing. The line after it reports credits remaining today. |
| Cloud rung reports HTTP 429 | Daily credit quota exhausted (**not** backpressure — this client never retries 429) | Wait for the daily reset, or upgrade the plan. Check `GET /v1/usage`. |
| Cloud rung reports HTTP 422 | The page returned no HTML, or a malformed request | Verify the URL is crawlable. Use `Crawl4AICloudClient.estimate()` to validate a request shape for free. |
| Log warns "only N of M daily credits remain" | Balance fell under a fifth of the plan's allowance | Informational. The threshold is relative, so it tracks a plan upgrade automatically. |
| Crawl returns fewer pages than expected | Polling budget exhausted, not a block | Raise `timeout_s`; partial results are returned, not discarded |
| Result says `Source: Crawl4AI (Firecrawl failed — HTTP 402…)` | Out of credits; the local rung already rescued the crawl | Top up when convenient. The content is real. |
| `Source: Crawl4AI (Firecrawl failed — HTTP 429…)` | Plan rate limit; the local rung already rescued the crawl | Nothing. Free tier allows 2 `/crawl` per minute; the client already retried with backoff. |
| Article is truncated on a site you subscribe to | No profile matched, or the session expired | `list-profiles` to check; re-run `create-profile` |
| "Crawl4AI fallback unavailable" | Optional extra not installed | `pip install "ibkr_core_mcp[scraper]" && crawl4ai-setup` |
| Same URL crawled twice returns instantly | 48h Drive cache hit — working as designed | `force_refresh=true` to re-crawl |
| A crawl took ~5-6 minutes | Firecrawl used its whole budget, then the local rung ran | Pass an explicit smaller `timeout_s` |

**SSRF protection is two-layered and not optional.** `ClaudeToolkit._validate_public_url` rejects
private, loopback and link-local hosts before any URL reaches Crawl4AI, and a Playwright-level
per-request guard re-checks every navigation, redirect and subresource at the moment it is sent —
closing DNS-rebinding gaps the first layer cannot. A blocked URL produces a message, not a
silent skip.

---

## 10. Verified behaviors

Each entry was observed, not assumed. Evidence lives in
`docs/audits/audit-evidence/scrapes/manifest.json` unless noted.

| Date | Behavior |
|---|---|
| 2026-07-02 | `interactivebrokers.com` serves an Akamai edge-block page (152 bytes, "Reference #102…") to Firecrawl's default scrape, and HTTP 403 to `WebFetch`. Retrying with `--wait-for 3000 --proxy auto` returned 91,918 bytes of real content. |
| 2026-07-14 | Firecrawl's documented retryable statuses are 408/429/500/502/503/504, with `Retry-After` honored when present. <https://docs.firecrawl.dev/api-reference/errors> |
| 2026-07-14 | `maxAge`'s documented default is `0` on v1 (caching off) and 172,800,000 ms on v2. The 48h Drive cache here is this repo's own policy. |
| 2026-07-25 | v1 `scrapeOptions` supports `waitFor`, `proxy`, `timeout`, `maxAge`, `location`, `actions`, `blockAds`, `onlyMainContent`. No v2 migration is needed to use them. <https://docs.firecrawl.dev/v1/api-reference/endpoint/crawl-post> |
| 2026-07-25 | `proxy` accepts `basic`, `enhanced` (up to 5 credits), and `auto`. |
| 2026-07-25 | IBKR moved their Web API docs from `campus/ibkr-api-page/cpapi-v1/` to `docs/web-api/`. Old URLs return HTTP 200 but redirect and drop the anchor. |
| 2026-07-25 | The 2026-07-02 IBKR edge-block did **not** reproduce: a default Firecrawl crawl returned 17,346 B for `campus/trading-lessons/request-modify-orders/` and 5,718 B for `docs/web-api/`. `waitFor=3000` + `proxy="auto"` was also exercised against the live API and is accepted, so the opt-in stealth path works when a host does block. Evidence: `tests/test_web_scraper_live.py::test_crawl_interactivebrokers_returns_real_content`. |
| 2026-07-25 | `/crawl` rate limits are per plan and per minute: Free 2, Hobby 20, Standard 100, Growth 1000. This is why the crawl makes one Firecrawl attempt and then falls back locally rather than retrying. <https://docs.firecrawl.dev/rate-limits> |
| 2026-07-25 | `example.com` yields 167 B of markdown through Firecrawl — below the 5 KB threshold, so it is a poor live-test target: it triggers the fallback on every run. `docs.firecrawl.dev/introduction` yields 14,341 B. |
| 2026-07-28 | Crawl4AI Cloud authenticates with `X-API-Key`, **not** `Authorization: Bearer`. Key format `sk_live_…`. |
| 2026-07-28 | `GET /v1/usage` returns `{"plan": {"daily_credits", "rate_per_minute", "concurrent", …}, "credits": {"used_today", "remaining_today", "daily_limit"}, …}`. The vendor's own `llms-full.txt` documents a different shape for this endpoint (`crawl.credits_daily_limit`, `crawl.credits_remaining_today`) — **those keys do not exist**. The published reference is stale; the live response is the source of truth. |
| 2026-07-28 | **No `X-RateLimit-*` response headers were present** on `/v1/usage`, though `llms-full.txt` claims "headers on every response". Quota logic is built on the response body instead. |
| 2026-07-28 | `dry_run: true` on `POST /v1/scrape` works and is **free** — it returns a pricing quote (`credits`, `credits_exact`, `breakdown`) without executing. It is **not documented** anywhere in `llms-full.txt`; found by probing. Four dry runs left `credits.used_today` at 0. |
| 2026-07-28 | A dry-run response body has **no `success` key and no `markdown` key**. It is a quote, not a page. This broke the first version of the client, which checked `success` unconditionally and raised on every real dry run — caught only by the live suite, because the unit test asserted against a hand-written body that had a `success` key the API never sends. Hence `estimate()` is a separate method from `scrape()`. |
| 2026-07-28 | **`usage.credits_used` in the scrape response body is wrong.** A no-proxy scrape reported `credits_used: 5.0` while the `/v1/usage` ledger moved by exactly **1** (3 → 4) and the `dry_run` quote had priced it at 1.0. `usage.credits_remaining` agreed with the ledger. Almost certainly the origin of the earlier "some operations cost 5 credits" budget. The client reads only `credits_remaining`. |
| 2026-07-28 | `markdown` (17,834 B) is larger than `fit_markdown` (12,186 B) on the same response, confirming `fit` prunes. The client prefers `markdown` and falls back to `fit_markdown`, because the ladder's question is "is there enough content?" and a pruned nav shell is the failure that sent the crawl here. |
| 2026-07-28 | Measured `POST /v1/scrape` cost: **1 credit** with `proxy` omitted, 2 with `{"mode":"datacenter"}`, 5 with `{"mode":"residential","country":"US"}`. Both planning documents assumed 5 flat and budgeted "~10 scrapes/day"; the real no-proxy ceiling on Free is ~50/day. |
| 2026-07-28 | `proxy` as the bare string `"direct"` returns **HTTP 422** with `detail[0].loc == ["body","proxy"]` (pydantic `model_attributes_type`), not a silently-ignored value. To scrape without a proxy the field must be omitted entirely. |
| 2026-07-28 | `https://api.crawl4ai.com/docs/skills/crawl4ai/SKILL.md` and `.../references/api-full-reference.md` both return a 696-byte HTML shell to `curl` — they are a JavaScript SPA. `llms-full.txt` (~59 KB, plain text) is the only machine-readable reference. |
| 2026-07-28 | **`docs.crawl4ai.com` DOES serve `llms-full.txt`** — 243,158 B of `text/plain` at `/assets/llm.txt/txt/llms-full.txt`, plus 13 modular topic files and `diagrams/` variants, all mirrored in the repo under `docs/md_v2/assets/llm.txt/`. What is absent is only an **index at the conventional root**: `/llms.txt` and `/llms-full.txt` 404, and the 404 body is a 31 KB HTML page, so a probe checking merely for non-empty content "succeeds" with a navigation shell. **An earlier revision of this table asserted the files did not exist at all** — inferred from those two root 404s without opening the repo. A 404 at a guessed path is evidence about the path, not the vendor. |
| 2026-07-28 | The `janbuchar/crawl4ai` Apify Actor had **0 successful public runs out of 29 in 30 days** (26 failed, 3 aborted) with a latest build from 2025-05-06, per Apify's own public API. Its `isDeprecated` flag is nonetheless `false`, and its 3.26 rating comes from 2 reviews. Rejected as a rung — see §5.1. Judge a hosted dependency by run statistics, not status flags or stars. |
| 2026-07-28 | `crawl4ai` OSS is at 0.9.2 and this repo's `crawl4ai>=0.5.0` floor is still correct: the two published migration guides (webscraping-strategy, table extraction v0.7.3) touch APIs `scrape_fallback.py` does not use — it uses only `AsyncWebCrawler`, `BrowserConfig` and `BrowserProfiler`. Checked so it need not be re-checked. |
| 2026-07-28 | The two Crawl4AI keys in this project (`ibkr_core_mcp/.env`, `claudia_ui/.env`) are **distinct** values — SHA-256 `0528d8cf…` vs `9d3b6a21…`, both 51 chars, both live, both reporting Free/50 credits. Compared by hash, not by prefix and length. One key per project is deliberate. |

---

## 11. API reference

All types live in `ibkr_core_mcp.web_scraper`, `ibkr_core_mcp.scrape_fallback` and
`ibkr_core_mcp.crawl4ai_cloud`. Note that `FirecrawlClient` and `WebDocsStore` are **not**
re-exported from the package root — only the exception types `FirecrawlError` and
`WebDocsStoreError` are.

```python
from ibkr_core_mcp.web_scraper import FirecrawlClient, WebDocsStore, content_bytes

# Firecrawl
client = FirecrawlClient(api_key)                      # ValueError if key is empty

client.search(query, limit=5, *, wait_for_ms=None, proxy=None, timeout_ms=None)
# -> list[{"url", "title", "markdown", "metadata"}]

client.crawl(url, max_pages=50, timeout_s=None, *, wait_for_ms=None, proxy=None)
# -> list[{"url", "markdown", "metadata"}]
# ONE Firecrawl attempt. Returns [] on a failed job, a 4xx mid-poll, or a timeout.
# Raises FirecrawlError only for 401 / 402 / 429 — the handler catches those and
# still falls back to Crawl4AI, using the exception only to name the cause.

content_bytes(pages) -> int                            # total UTF-8 bytes of markdown

# Drive persistence
store = WebDocsStore(config)                           # no network I/O at construction
store.get_cached_crawl(url, max_age_hours=48.0)        # -> manifest dict | None
store.save_crawl(url, pages)                           # -> manifest dict
store.save_search(query, results)                      # -> Drive file ID
```

```python
from ibkr_core_mcp.crawl4ai_cloud import Crawl4AICloudClient, Crawl4AICloudError

# Crawl4AI Cloud — rung 3. POST /v1/scrape only; /v1/site is not implemented.
cloud = Crawl4AICloudClient(api_key, base_url="https://api.crawl4ai.com")  # ValueError if key empty

cloud.scrape(url, *, proxy_mode=None, proxy_country=None)
# -> {"url", "markdown", "metadata"}   — the same page dict the other rungs produce
# NEVER retries: 429 means quota exhaustion here, not backpressure.
# Raises Crawl4AICloudError (with .status_code) on any HTTP error, and on a 200
# whose body reports success: false.
# `proxy` is omitted from the request entirely when proxy_mode is None — the string
# "direct" is a 422, not a no-op.

cloud.estimate(url, *, proxy_mode=None, proxy_country=None)
# -> the raw dry-run quote: {"credits", "credits_exact", "breakdown", ...}
# FREE. No execution, no charge. Use it to validate a request shape without paying.
# Note the quote body has no "success" and no "markdown" — it is not a page.

cloud.usage()                                          # -> {"plan", "credits", "storage", "llm"}
# Costs a request against the per-minute limit, but no credits.

cloud.last_credits_remaining                           # float | None — set after a scrape
```

```python
from ibkr_core_mcp.scrape_fallback import (
    Crawl4AIScraper, Crawl4AIUnavailableError, assess_quality, create_profile, list_profiles,
)

scraper = Crawl4AIScraper(profiles_dir)
scraper.scrape(url)                                    # -> {"url", "markdown"}
scraper.scrape_batch(urls, profile_domain=domain)      # -> {url: result | Exception}

assess_quality(markdown, metadata, url)                # -> "ok" | "ambiguous" | "fallback"
create_profile(url_or_domain, profiles_dir)            # -> Path (interactive)
list_profiles(profiles_dir)                            # -> [(domain, path, age_days)]
```

**Related:** `docs/tools-reference.md` (tool schemas), `docs/external-docs-reference.md` (official
URLs for every external API), `docs/plans/2026-07-25-web-scraper-robustness-design.md` (why the
ladder is shaped this way).
