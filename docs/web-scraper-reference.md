# Web Scraper Reference

Two engines, split by what they are good at. **Firecrawl** (hosted, paid) does search and bulk
crawling — API and reference documentation is its home ground. **Crawl4AI local** (free, a real
Playwright browser on this machine) does complex JavaScript-heavy sites and paywalled sites you
subscribe to. This document covers both layers, every tunable, the credit-cost model,
paywalled-site logins, and what to do when a scrape comes back empty.

---

## 1. The two layers

| Layer | Module | Cost | What it's good at |
|---|---|---|---|
| **Firecrawl** | `web_scraper.py` | Paid, per-credit | Web *search* (nothing else here provides it), fast bulk crawling, clean markdown extraction |
| **Crawl4AI local** | `scrape_fallback.py` | Free, local | Pages Firecrawl can't get: JavaScript-heavy sites, bot-blocked sites, and paywalled sites where you hold a subscription |

They meet in two places, and the distinction matters:

- **As a ladder** — `firecrawl_search` and `firecrawl_crawl` try Firecrawl first and fall back to
  Crawl4AI when the result looks thin (§3).
- **As a door** — `fetch_page` goes straight to the browser for a single URL, with no Firecrawl
  attempt at all. That is the right route for a paywalled article: Firecrawl cannot log in, so
  trying it first only spends a credit to be told about a subscription wall.

### 1.1 Four different things are called "Crawl4AI"

Searching for Crawl4AI docs returns all four. Only the first is used here, and picking the
wrong one sends you to an API that does not match the code in front of you. Surveyed 2026-07-28.

| # | Thing | What it is | Used here? |
|---|---|---|---|
| 1 | **`crawl4ai` OSS library** (PyPI, 0.9.2 as of 2026-07-15) | Playwright-based crawler that runs locally. Docs: `docs.crawl4ai.com` (v0.9.x) | **Yes** — `scrape_fallback.py`, behind both the ladder and `fetch_page` |
| 2 | **Crawl4AI Cloud** (`api.crawl4ai.com`) | The vendor's hosted REST API, credit-billed | **No — built, then removed 2026-07-28. See §5.1** |
| 3 | **`crawl4ai-cloud-sdk`** (PyPI, 1.2.0) | The vendor's own Python client for #2 | **No** — removed alongside #2 |
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

**Three tools are exposed to the model:**

| Tool | Use it for |
|---|---|
| `firecrawl_search` | "Find me pages about X." Returns full markdown for each hit. Optionally snapshots to Drive. |
| `firecrawl_crawl` | "Archive this site." Crawls from a root URL and always saves to Drive under `web_docs/{url-slug}/`. |
| `fetch_page` | "Read me this page." One URL, straight to the local browser, no Firecrawl attempt and no Drive write. |

`fetch_page` was added on 2026-07-28 and closes a real gap: until then the only way to read a
single known URL was to run `firecrawl_crawl` against it, which archives a whole site to Drive to
answer a question about one page — and which cannot open a paywall at all, because Crawl4AI was
reachable only as a fallback *underneath* a Firecrawl call. Three successive plans tuned the
ladder's rung order while this was the actual missing piece.

---

## 2. Configuration

| Env var | Field | Required for | Default |
|---|---|---|---|
| `FIRECRAWL_API_KEY` | `firecrawl_api_key` | `firecrawl_search` and `firecrawl_crawl`. Without it they return "not available" rather than raising. **`fetch_page` needs no key** — it is a local browser. | — |
| `ANTHROPIC_API_KEY` | `anthropic_api_key` | The completeness judge (section 3.2) | — (required by `Config` itself) |
| `GOOGLE_DRIVE_FOLDER_ID` | `gdrive_folder_id` | Drive persistence, unless `GDRIVE_WEB_DOCS_FOLDER_ID` is set | — |
| `GDRIVE_WEB_DOCS_FOLDER_ID` | `gdrive_web_docs_folder_id` | Overrides the `web_docs/` root | auto-created under `gdrive_folder_id` |
| `GDRIVE_TOKEN_FILE` | `gdrive_token_file` | Drive OAuth | `~/.ibkr_core/token.json` |
| `GDRIVE_CREDENTIALS_FILE` | `gdrive_credentials_file` | Drive OAuth | `~/.ibkr_core/credentials.json` |
| `CRAWL4AI_PROFILES_DIR` | `crawl4ai_profiles_dir` | Paywalled-site logins (local layer) | `~/.ibkr_core/crawl4ai_profiles` |

`CRAWL4AI_PROFILES_DIR` is the only Crawl4AI setting. `CRAWL4AI_API_KEY` and `CRAWL4AI_API_URL`
configured the hosted rung removed on 2026-07-28 (§5.1) and are now ignored wherever they remain
set.

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
falls back once — paid remote, then free local:

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
        ├─ got content? ────────────────────────────────► MERGE into rung 1's pages,
        │                                                  save the union to Drive
        └─ nothing at all → explicit diagnosis naming EACH rung's
                            failure, never "saved 0 page(s)"
```

**The rescue only ever adds.** Rung 2's page is merged into rung 1's list rather than replacing
it, so no outcome of the local rung can remove anything Firecrawl already extracted. When both
rungs return the same URL, the larger markdown wins — re-fetching a page Firecrawl already had
upgrades that page instead of duplicating or thinning it.

> **This used to be `pages = root_pages`, and it lost real content.** The old rule was "replace
> if strictly larger", which honored the promise bytewise and broke it page-wise: three
> genuinely complete doc pages of ~1.5 KB each measure under the 5 KB bar, so a larger root
> scrape discarded all three and archived one. Fixed 2026-07-30 (`_merge_pages` in
> `claude_tools.py`); regression tests
> `test_root_rescue_keeps_firecrawls_pages_instead_of_replacing_them` and
> `test_local_rung_does_not_replace_a_larger_firecrawl_result`.

Because merging cannot cost anything, rung 2 no longer has to win outright to be used — it runs
whenever rung 1 came in under the bar, and whatever it finds is kept. The `Source:` line names
both rungs when both contributed (`Firecrawl + Crawl4AI (local rung added the root page)`) and
one rung when only one did.

**Why the free local rung is the last one.** On the only real failure observed to date
(2026-07-28, the IBKR campus reference), Firecrawl returned 0 pages and thinned another page to a
nav shell, and a plain fetch 403'd — while local Crawl4AI fetched both cleanly, 144,125 chars from
the page that settled the whole symbology question. A paid, proxied third rung was built on
2026-07-28 for the case local supposedly could not solve, and removed the same day: local had
already beaten the only block on record, so the rung addressed a failure mode never once observed.
See §5.1.

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

**A short page costs one free local fetch, never a wrong answer.** A legitimately short 3 KB page
still measures "too small" and runs the local rung — but since the rescue merges (above), a thin
Crawl4AI result cannot replace a better Firecrawl one, and a good one is simply added. The
threshold decides *whether to look further*, not *what to keep*.

**Measured cost of looking further (2026-07-30, this machine):** a local fetch is **0.5–1.5 s**
per URL, or **0.8 s** per page through the crawl path's shared browser session. Against a
`timeout_s` budget of 120–600 s, taking the local rung adds well under 1% to worst-case wall
clock. This is the number behind "the fallback has no downside" — see §5.2.

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

**Crawl4AI local (rung 2, and every `fetch_page` call):** free — it runs on this machine.

A crawl costs exactly one Firecrawl attempt. `enhanced`/`auto` are charged only when you ask for
them explicitly — nothing escalates you into the expensive path automatically, and rung 2 is free.
A site that works costs exactly what it cost before this feature existed.

### Rate limits and plans

Firecrawl enforces per-plan rate limits — as low as 1 request/minute for `/crawl` on the free
tier. The client retries 408/429/500/502/503/504 up to 3 times, matching the vendor's own
published snippet exactly. **The 30s cap applies to the exponential branch only, not to
`Retry-After`:**

```python
delay = float(retry_after) if retry_after else min(2 ** attempt, 30) + random.random()
```

When the server sends `Retry-After`, that value is honored in full — Firecrawl's wording is
"wait **at least** that long", so capping it would retry early and earn a second 429. Rate limits
are measured per minute, so the realistic ceiling is ~60s per retry. Source:
<https://docs.firecrawl.dev/api-reference/errors> and <https://docs.firecrawl.dev/rate-limits>,
both re-verified 2026-07-30.

> An earlier revision of this line read "honoring `Retry-After` when present, capped at 30s and
> 3 attempts", which reads as though the cap covers both branches. It does not, and the code was
> right — the doc was wrong. Caught on 2026-07-30 only because the vendor page was re-fetched
> before "fixing" the code to match this sentence.

Crawl4AI local has no rate limit and no quota — it is a browser on this machine. The
search-result path launches up to `_MAX_CONCURRENT_FALLBACKS = 5` local scrapes in parallel; the
only ceiling is this machine's memory.

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
duplicate the local rung while costing money.

Worth knowing: `isDeprecated: false` on a wrapper with a 0% success rate is exactly the sort of
"looks configured, is dark" signal this ladder exists to avoid trusting. Judge a hosted
dependency by its run statistics, not its status flag or star rating — 3.26 stars from two
reviewers said nothing, and the run stats said everything.

Other Apify actors wrapping Crawl4AI do have healthy success rates (e.g.
`bikram07/web-to-markdown-crawl4ai`, 33/41 in 30 days) but have single-digit user counts and no
vendor backing, so they trade our current dependency for a less-supported one.

**Crawl4AI Cloud — built, then removed the same day (2026-07-28).** A third, paid rung
(`crawl4ai_cloud.py`, 432 lines, 37 tests, merged as PR #2) scraped through the vendor's hosted
API with managed proxies. It was removed hours later. **Do not re-add it without new evidence** —
specifically, without a real block that the local browser rung failed to beat.

Three things killed it:

1. **It bought nothing the local browser did not already do.** Its stated purpose was an
   IP-level block aimed at this machine's address. On the only real block ever observed
   (2026-07-02, IBKR/Akamai), the free local rung won outright — 144,125 chars. The rung
   addressed a failure mode that has never once occurred.
2. **It could not serve the primary requirement at all.** The reason this repo needs Crawl4AI is
   paywalled sites (§6). Cloud has a `POST /v1/profiles` endpoint, but using it means uploading a
   logged-in WSJ or FT session to a third party — and the vendor's own SDK does not even wrap it.
   `scrape_fallback.py` already does the same thing locally, for free, with no key and nothing
   leaving the machine.
3. **The plan that built it argued against itself.** Its own §2 established that local was the
   rung that worked, then concluded "put Cloud last" instead of asking whether Cloud was needed —
   the same mistake three prior plans made, each tuning rung *order* while the actual gap was
   that nothing could reach the browser directly for one URL. That gap is what `fetch_page` (§1)
   now closes.

**What was learned before it went** — verified by live call, kept because it cost real credits
and because it is evidence for the standing rule that *a published reference is a claim, not
evidence*:

| Claim (vendor docs or response body) | What the live API actually did |
|---|---|
| `GET /v1/usage` returns `crawl.credits_daily_limit` / `crawl.credits_remaining_today` | Neither key exists. It returns `plan.daily_credits` and `credits.remaining_today`. |
| "`X-RateLimit-*` headers on every response" | No such header on `/v1/usage`. Quota logic must read the body. |
| No `dry_run` parameter documented | `dry_run: true` on `POST /v1/scrape` works, is free, and returns a pricing quote — found only by probing. Its body has no `success` and no `markdown` key. |
| `usage.credits_used: 5.0` in a scrape response | The `/v1/usage` ledger moved by exactly **1**. The response body's own field is wrong; `credits_remaining` agreed with the ledger. This bad field is almost certainly the origin of an earlier "~10 scrapes/day" budget. |
| `crawl4ai-cloud-sdk` 1.2.0 defaults to `strategy="auto"` | The vendor's own API rejects its own SDK's default with a 422 — only `"browser"` and `"http"` are accepted. **A mocked crawler accepts any argument, so no unit test can catch this.** It surfaced on the first live run. |

Confirmed correct, for the record: auth is `X-API-Key` (not `Authorization: Bearer`), and `proxy`
is an object whose string form `"direct"` is a hard 422 — omit the field to skip a proxy.

Two keys were issued, one per project. **They share a single 50/day pool** — settled by
experiment, not by reading: spending one credit on one key moved *both* ledgers 8 → 9.

**Self-hosting the OSS crawler — not evaluated, and now with less reason to be.** Crawl4AI
documents a self-hosting path (<https://docs.crawl4ai.com/core/self-hosting/>). Running the OSS
library on a remote box would give a *different IP* without per-credit billing. It would not give
managed residential rotation, and it adds a host to operate. Since the local rung has never yet
lost to a block, there is nothing here to solve — revisit only if one is observed.

**There is no official Crawl4AI MCP server** for either the OSS library or Cloud — checked
2026-07-28 against the docs sitemap (87 pages, no MCP page) and the Cloud `llms-full.txt` (no
occurrence). Noted because this repo *is* an MCP project and the absence is otherwise easy to
mistake for "not found yet".

### 5.2 Head-to-head: is falling back to Crawl4AI a downside?

**No. Measured 2026-07-30, both rungs run against the same URLs within minutes of each other.**
The question is worth settling with numbers because "we had to fall back to the free thing"
sounds like a degradation, and on this evidence it is the opposite.

| URL | Firecrawl | local Crawl4AI | verdict |
|---|---|---|---|
| `docs.firecrawl.dev/introduction` | 14,341 B in 16.8 s, 1 credit | **17,364 B in 1.2 s, free** | local wins on size and speed |
| `interactivebrokers.com/docs/web-api/` | 5,515 B in 13.2 s, 1 credit | **8,786 B in 1.3 s, free** | local wins on size and speed |

Local reliability the same day: **4/4 targets fetched** (the two above plus `example.com` and
`ibkrguides.com`), 0.5–1.5 s each, and 3/3 in 2.4 s through one shared `scrape_batch` session
(0.8 s per page). `example.com` returned 166 B locally against Firecrawl's recorded 167 B —
near-identical, confirming that page is genuinely tiny rather than blocked.

Read the timings carefully: the Firecrawl column is **this client's** wall clock, which includes
its own 5 s polling cadence (`_try_crawl` sleeps 5 s before the first poll), not the vendor's raw
service time. The size comparison carries no such caveat.

**So the pivot costs nothing and usually gains.** What Firecrawl still uniquely provides is
*search* — finding pages when you have no URL — and breadth, crawling a whole site from one root.
For a URL you already hold, the local rung is the better instrument, which is exactly why
`fetch_page` exists as a door rather than only as a fallback (§1).

The one honest caveat: these are documentation hosts. A site with serious anti-bot protection can
refuse the local browser outright — see §6, where WSJ does exactly that.

---

## 6. Paywalled sites (FT, WSJ, Bloomberg)

Crawl4AI can use a saved browser session, so a site you subscribe to returns full articles instead
of the subscription stub. This is the capability the whole local layer exists for.

> ### ⚠ Status: the mechanism works; the capability is **still unproven end-to-end**
>
> Read this before relying on it. Verified 2026-07-30:
>
> | Step | State |
> |---|---|
> | Save a profile (`create-profile`) | ✅ works — a real WSJ profile exists, 331 cookies incl. `DJSESSION` |
> | Find the right profile for a URL (`_resolve_profile_dir`) | ✅ works — resolves `www.wsj.com` correctly |
> | Hand that session to a scrape | ✅ works — the browser launches against the saved `user_data_dir` |
> | **Get a paywalled article back** | ❌ **never once observed** |
>
> **WSJ cannot be the proof, and no profile will change that.** `wsj.com` answers this machine's
> browser with **HTTP 401, DataDome captcha, 1 B of markdown** — identically in all four
> combinations tested: headless or visible window, with the saved profile or without it. The
> block lands on the *automated browser*, before any cookie is consulted, so the login is never
> the deciding factor. An earlier note in §10 read WSJ's 1 B as "no login profile"; that
> diagnosis was wrong, and the profile that has since been created did not move the number.
>
> **FT is reachable** — `ft.com` returns 59,455 B, HTTP 200, headless, with no profile at all. So
> the browser is not the problem in general; DataDome specifically is. FT is therefore the
> realistic candidate for proving the paywall path, and doing so needs the account holder to run
> `create-profile https://www.ft.com` by hand and then open a subscriber-only article.
>
> Until that run happens, treat "reads paywalled articles" as **designed and wired, not
> demonstrated**. The tool output itself is honest about this: a 1 B DataDome stub trips
> `assess_quality` and `fetch_page` prints its incompleteness NOTE, so a stub is never presented
> as the article.

**Two steps, and the first is once per site.**

**1. Save the login** — interactive, needs your hands:

```bash
python -m ibkr_core_mcp.scrape_fallback create-profile https://www.ft.com
```

This opens a **real, visible browser**. Log in by hand, then confirm in the terminal. The
resulting cookies and local storage are copied to `~/.ibkr_core/crawl4ai_profiles/<domain>/`.

**No password is ever seen or stored by this package** — only the resulting browser session.
Nothing is transmitted anywhere; the profile is a local directory.

**2. Read the article** — `fetch_page` on the URL. It goes straight to the browser, finds the
profile by domain, and returns the full text. Do **not** route a paywalled article through
`firecrawl_search` or `firecrawl_crawl` first: Firecrawl cannot log in, so it spends a credit to
be handed the subscription stub, and only then falls back to the browser that could have gone
first. The tool's reply always states whether a profile was used, so a stub is never silently
mistaken for the article.

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
| `wsj.com` | **Blocked outright.** DataDome answers the automated browser with HTTP 401 and 1 B, headless or not, with or without a saved login (2026-07-30). | Nothing works from here. Do not create a profile expecting it to help — one exists and does not. |
| `ft.com` | Reachable. 59,455 B at HTTP 200 headless, no profile (2026-07-30). Free content only — subscriber articles untested. | `create-profile` once (section 6) if you subscribe. This is the host to prove the paywall path on. |
| Bloomberg / Barron's | Metered paywall; not tested against the local browser | Assume WSJ-like anti-bot until measured. Check for HTTP 401 / ~1 B before blaming the profile. |

---

## 9. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| "not available: FIRECRAWL_API_KEY is not configured" | No key in the environment | Set `FIRECRAWL_API_KEY` in the consuming project's `.env` |
| "Crawl of … produced no content" | Every configured rung failed; the message names each cause | Check the host table. For a subscription site, `create-profile`. Try `wait_for_ms=3000` + `proxy="auto"`. For IBKR docs, use `.md` URLs. |
| Crawl returns fewer pages than expected | Polling budget exhausted, not a block | Raise `timeout_s`; partial results are returned, not discarded |
| Result says `Source: Crawl4AI (Firecrawl failed — HTTP 402…)` | Out of credits; the local rung already rescued the crawl | Top up when convenient. The content is real. |
| `Source: Crawl4AI (Firecrawl failed — HTTP 429…)` | Plan rate limit; the local rung already rescued the crawl | Nothing. Free tier allows 2 `/crawl` per minute; the client already retried with backoff. |
| `Source: Firecrawl + Crawl4AI (local rung added the root page)` | Firecrawl came in under 5 KB, so the local rung ran and its root page was merged in. Both rungs' content is present | Nothing — this is the ladder working. Firecrawl's pages were kept, not replaced. |
| Page returns exactly **1 B** and `http=401` | Anti-bot protection (DataDome on WSJ) refusing the automated browser. **A login profile does not help** — the block precedes authentication | No fix from this side. See §6. Use a host that permits automation, or read that article by hand. |
| Article is truncated on a site you subscribe to | No profile matched, or the session expired — but rule out anti-bot first (row above) | `list-profiles` to check; re-run `create-profile` |
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
| 2026-07-28 | **`docs.crawl4ai.com` DOES serve `llms-full.txt`** — 243,158 B of `text/plain` at `/assets/llm.txt/txt/llms-full.txt`, plus 13 modular topic files and `diagrams/` variants, all mirrored in the repo under `docs/md_v2/assets/llm.txt/`. What is absent is only an **index at the conventional root**: `/llms.txt` and `/llms-full.txt` 404, and the 404 body is a 31 KB HTML page, so a probe checking merely for non-empty content "succeeds" with a navigation shell. **An earlier revision of this table asserted the files did not exist at all** — inferred from those two root 404s without opening the repo. A 404 at a guessed path is evidence about the path, not the vendor. |
| 2026-07-28 | **`create-profile` demanded an unrelated Anthropic key.** `_main` built a full `Config.from_env()` just to read `crawl4ai_profiles_dir`, and `from_env()` raises when `ANTHROPIC_API_KEY` is unset — so saving a browser login failed with an error naming a key the operation never uses. The CLI test hid it by *setting* the key rather than asking why it was needed. Both profile subcommands now use `config.crawl4ai_profiles_dir_from_env()`, which shares the same variable and default but requires nothing else. |
| 2026-07-28 | **`create-profile` without a TTY silently saves an empty profile.** Crawl4AI's keyboard listener needs a terminal; without one `_listen_unix` fails on termios, the fallback's `input()` raises EOFError, and EOF is treated as the user pressing 'q' — so the profile saves before any login happens. The result passes `_resolve_profile_dir`, so `fetch_page` reports "Used a saved login profile" while returning the paywall stub. The CLI now refuses without `sys.stdin.isatty()`. **Never run it through a pipe, script or task runner.** |
| 2026-07-28 | **`create_profile()` must run on the main thread, and had never been run at all.** It routed through `_run_async()`, which hands the coroutine to a worker thread so scraping can survive being called from inside a running event loop. But `BrowserProfiler.create_profile()` installs SIGINT and SIGTERM handlers, and `signal.signal()` raises `ValueError: signal only works in main thread of the main interpreter` anywhere else — so the `create-profile` CLI failed on **every** invocation, while three mocked tests stayed green because their fake profiler installs no handler. Now uses `asyncio.run()` with an explicit main-thread guard. **Found on the first real run, by a human typing the documented command.** |
| 2026-07-28 | **`fetch_page` live baseline, no login profile:** `wsj.com` returns exactly **1 B** — the browser is served nothing at all, not a teaser. `ft.com`'s free homepage returns 57,737 B and a real docs page 11,807 B. A byte count on its own therefore cannot distinguish "short page" from "blocked", which is why the reply runs `assess_quality` and flags anything that is not `ok` as incomplete. *(The stated cause was wrong — see the 2026-07-30 entry below. The measurement was right.)* |
| 2026-07-30 | **WSJ's 1 B is DataDome, not a missing login.** With a real saved profile now in place (331 cookies including `DJSESSION`), `wsj.com` still returns **1 B and HTTP 401, "Blocked by anti-bot protection: DataDome captcha"** — identically across all four combinations: headless + profile, visible window + profile, visible + no profile, headless + no profile. The block lands on the automated browser before any cookie is read, so no profile can move it. The 2026-07-28 entry above attributed the same 1 B to "no login profile"; creating one falsified that. **A plausible cause that matches the symptom is still a guess until the other variable is changed.** |
| 2026-07-30 | **FT is reachable, WSJ is not** — `ft.com` returns 59,455 B at HTTP 200 headless with no profile at all (consistent with 57,737 B on 2026-07-28). So the local browser is not broadly blocked; DataDome specifically blocks it. FT is the realistic candidate for finally proving the paywall path end-to-end. |
| 2026-07-30 | **The local rung beats the paid rung on documentation hosts, on size and speed.** Same URLs, minutes apart: `docs.firecrawl.dev/introduction` 14,341 B / 16.8 s via Firecrawl vs **17,364 B / 1.2 s** local; `interactivebrokers.com/docs/web-api/` 5,515 B / 13.2 s vs **8,786 B / 1.3 s**. Local fetched 4/4 targets that day (0.5–1.5 s each; 0.8 s per page batched). Firecrawl's timings include this client's own 5 s poll cadence; the byte counts have no such caveat. This is the evidence for "falling back is not a downside" — §5.2. |
| 2026-07-30 | **The root rescue was discarding Firecrawl's pages.** `pages = root_pages` honored the ladder's byte-level promise while breaking it page-wise: a crawl of three complete ~1.5 KB doc pages measures under the 5 KB bar, so a larger root scrape replaced all three with one. Now merged by URL, larger markdown winning per URL (`_merge_pages`). Found by re-reading the invariant against the code that was supposed to implement it, not by any failing test. |
| 2026-07-30 | **The two engines agree on the `url` key, so the merge really does dedupe.** A unit test cannot establish this — both sides are invented. Run live against `example.com`: Firecrawl's page key (from `metadata.sourceURL`) and Crawl4AI's (the requested URL) were both exactly `'https://example.com'`, so `_merge_pages` returned **1** page, not 2. Firecrawl's 167 B also beat local's 166 B and was kept, exercising "larger markdown wins" on real data. Had the keys differed by so much as a trailing slash, every root rescue would have archived the root page twice. |
| 2026-07-30 | **The `Retry-After` cap was a doc error, not a code error.** This reference said the client honors `Retry-After` "capped at 30s"; Firecrawl's published snippet applies `min(2 ** attempt, 30)` to the *exponential branch only* and says of the header "wait **at least** that long". The code matched the vendor all along. Caught only because the vendor page was re-fetched before editing the code to match the sentence — the standing rule works in this direction too. |
| 2026-07-28 | **The paywall path had never been executed.** `~/.ibkr_core/crawl4ai_profiles` did not exist on this machine — no login profile had ever been created — while §6, the profile-lookup code, the `create-profile` CLI and the paywall markers were all present, tested and documented. A capability can be complete in every respect except having been run once. |
| 2026-07-28 | The `janbuchar/crawl4ai` Apify Actor had **0 successful public runs out of 29 in 30 days** (26 failed, 3 aborted) with a latest build from 2025-05-06, per Apify's own public API. Its `isDeprecated` flag is nonetheless `false`, and its 3.26 rating comes from 2 reviews. Rejected as a rung — see §5.1. Judge a hosted dependency by run statistics, not status flags or stars. |
| 2026-07-28 | `crawl4ai` OSS is at 0.9.2 and this repo's `crawl4ai>=0.5.0` floor is still correct: the two published migration guides (webscraping-strategy, table extraction v0.7.3) touch APIs `scrape_fallback.py` does not use — it uses only `AsyncWebCrawler`, `BrowserConfig` and `BrowserProfiler`. Checked so it need not be re-checked. |
| 2026-07-28 | **A consuming project can silently run stale ibkr_core_mcp code.** claudia_ui installs this package with `editable_mode=strict`, which resolves imports through a snapshotted symlink farm under `build/__editable__…/`. A module added after that install is **invisible** — a newly added `ibkr_core_mcp` module raised `ModuleNotFoundError` in ClaudIA while existing on disk here. Re-run the editable install in every consumer after adding a module, not just after adding a tool. |
| 2026-07-28 | **The `[scraper]` extra was not installed in claudia_ui**, so inside ClaudIA the fallback rung was dark: detection worked, recovery dead-ended, and nothing said so. Fixed the same day by installing `crawl4ai` + Playwright there. A capability can be fully coded, fully tested and fully documented and still be unreachable in the app that needs it — check the consumer, not just the library. |

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
