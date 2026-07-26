# Web Scraper Reference

Firecrawl (hosted, paid) for search and crawling, Crawl4AI (local, free, Playwright-based) as the
fallback that recovers what Firecrawl can't reach. This document covers both layers, every tunable,
the credit-cost model, paywalled-site logins, and what to do when a scrape comes back empty.

---

## 1. The two layers

| Layer | Module | Cost | What it's good at |
|---|---|---|---|
| **Firecrawl** | `web_scraper.py` | Paid, per-credit | Web *search* (nothing else here provides it), fast bulk crawling, clean markdown extraction |
| **Crawl4AI** | `scrape_fallback.py` | Free, local | Pages Firecrawl can't get: bot-blocked sites, and paywalled sites where you hold a subscription |

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
| `CRAWL4AI_PROFILES_DIR` | `crawl4ai_profiles_dir` | Paywalled-site logins | `~/.ibkr_core/crawl4ai_profiles` |

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
falls back exactly once, from the paid remote scraper to the free local one:

```text
firecrawl_crawl(url)
  │
  ├─ Rung 1: Firecrawl, one attempt                         ~1 credit/page
  │     ├─ >= 5 KB of markdown? ────────────────────────► save to Drive, done
  │     └─ anything else — thin, empty, job failed, timed out,
  │        401 / 402 / 429, network down ───────────────┐
  │                                                     │
  └─ Rung 2: Crawl4AI scrapes the root URL locally  ◄────┘   free
        using a saved login profile if one matches
        │
        └─ still nothing → explicit diagnosis naming the Firecrawl
                           failure, never "saved 0 page(s)"
```

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

**The fallback keeps the larger result, not the last one.** Both rungs are scored with the same
function and Crawl4AI's result replaces Firecrawl's only if it is genuinely bigger. So a
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

| Setting | Cost |
|---|---|
| `proxy` unset or `basic` | 1 credit per page |
| `proxy: "enhanced"` | up to 5 credits per page |
| `proxy: "auto"` | 1 credit if basic succeeds; up to 5 if it retries through enhanced |
| Crawl4AI (any rung 3 work) | free — it runs locally |

A crawl costs exactly one Firecrawl attempt. `enhanced`/`auto` are charged only when you ask for
them explicitly — nothing escalates you into the expensive path automatically, and the recovery
rung is free. A site that works costs exactly what it cost before this feature existed.

Firecrawl also enforces per-plan rate limits — as low as 1 request/minute for `/crawl` on the free
tier. The client retries 408/429/500/502/503/504 with exponential backoff plus jitter, honoring
`Retry-After` when present, capped at 30s and 3 attempts. Source:
<https://docs.firecrawl.dev/api-reference/errors>

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
| "Crawl of … produced no content" | Both rungs failed; the message names the Firecrawl cause | Check the host table. For a subscription site, `create-profile`. Try `wait_for_ms=3000` + `proxy="auto"`. For IBKR docs, use `.md` URLs. |
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

---

## 11. API reference

All types live in `ibkr_core_mcp.web_scraper` and `ibkr_core_mcp.scrape_fallback`. Note that
`FirecrawlClient` and `WebDocsStore` are **not** re-exported from the package root — only the
exception types `FirecrawlError` and `WebDocsStoreError` are.

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
