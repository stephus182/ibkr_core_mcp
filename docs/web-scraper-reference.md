# Web Scraper Reference

> **Status: closed 2026-07-30.** The scraper is finished and verified; treat further work as a
> new project with its own justification, not as continuation. Closing state: 44 toolkit tools,
> **790 unit + 19 live tests green**, `ruff check` + `ruff format` + `mypy` clean.
>
> One capability remains **designed but not demonstrated**: reading a paywalled article
> end-to-end (§6). It needs the account holder to run `create-profile` on **FT** by hand — WSJ
> is impossible at any price (DataDome, HTTP 401, 1 byte, with or without a login). That is the
> only open item, and it needs hands rather than code.
>
> **Before changing anything here, read §10.** Every defect this subsystem ever had was found by
> running a tool, never by a test failing. A green unit suite is not evidence.

**Four tools, one job each, and no fallback between them.** Anything that takes a URL goes
to the free local browser (Crawl4AI). Firecrawl is kept for exactly one thing the browser
cannot do: search the web when you have no URL yet. This document covers all four tools,
every tunable, the credit model, paywalled-site logins, and what to do when a scrape comes
back empty.

---

## 1. The four tools

| Tool | Engine | Cost | Job |
|---|---|---|---|
| `firecrawl_search` | Firecrawl | ~1 credit | **Find pages anywhere.** A query with no site in mind. The only whole-web search. |
| `search_site` | Crawl4AI | free | **Find pages on one site.** Domain + query, BM25-ranked. |
| `crawl_site` | Crawl4AI | free | **Archive a site** to Drive under `web_docs/{url-slug}/`. |
| `fetch_page` | Crawl4AI | free | **Read one page** as markdown. Opens paywalled sites with a saved login. |

Read that table as a pipeline: the first two *find*, the last two *read*. `search_site` and
`firecrawl_search` both end by telling you to call `fetch_page` on whichever result you
want — because none of the finders returns page text, deliberately.

### 1.1 Why there is no longer a ladder

Until 2026-07-30 this was a two-rung recovery ladder: Firecrawl ran first, and Crawl4AI was
reachable only *underneath* it when a paid result came back thin. About 900 lines existed to
arbitrate between them — `_merge_pages`, `_assess_fallback_need`, `_scrape_with_fallback`,
`_apply_crawl4ai_fallback_batch`, `_crawl4ai_root_scrape`, and an LLM judge that spent a
Haiku call deciding whether a page looked complete.

All of it is gone, because the premise was wrong. **The "fallback" was never the weaker
engine** (§5.2): on the same URLs minutes apart, local returned 17,364 B in 1.2 s where
Firecrawl returned 14,341 B in 16.8 s, and 8,786 B in 1.3 s against 5,515 B in 13.2 s.
Bigger, ~10× faster, free. A ladder that tries the slower, costlier, thinner engine first
and falls back to the better one is upside down.

Once each tool has one job, there is nothing to fall back *from*. The consequences are worth
naming because they are the whole return on this refactor:

- **No arbitration code.** Nothing decides between engines because nothing competes.
- **No LLM call anywhere in the scraper.** `judge_completeness_llm` was the single documented
  exception to "ClaudeToolkit is the only layer that talks to Anthropic" (`CLAUDE.md`), and
  it was invisible to a host app's own token accounting. It is not better-guarded now; it
  does not exist.
- **`WebDocsStore` never noticed.** It takes `{"url", "markdown"}` dicts and never knew which
  engine produced them, so `crawl_site` replaced `firecrawl_crawl` beneath it as a drop-in.
  Same Drive layout, same 48h manifest cache, same slug-collision handling.

What this cost: whole-web search still needs Firecrawl, so the dependency and its key remain.
That is ~167 lines — `search()` is a single POST with no polling and no pagination, which is
why keeping it was nearly free while deleting the crawl half saved ~330.

### 1.2 Four different things are called "Crawl4AI"

Searching for Crawl4AI docs returns all four. Only the first is used here, and picking the
wrong one sends you to an API that does not match the code in front of you. Surveyed 2026-07-28.

| # | Thing | What it is | Used here? |
|---|---|---|---|
| 1 | **`crawl4ai` OSS library** (PyPI, 0.9.2 as of 2026-07-15) | Playwright-based crawler that runs locally. Docs: `docs.crawl4ai.com` (v0.9.x) | **Yes** — `local_browser.py`, behind `fetch_page`, `crawl_site` and `search_site` |
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

Handlers live in `claude_tools.py`. The split is deliberate: `web_scraper.py` never imports
`local_browser.py`, so the Firecrawl client stays a pure protocol wrapper.

`fetch_page` was added on 2026-07-28 and closed a real gap: until then the only way to read a
single known URL was to run a whole site crawl at it, and nothing could open a paywall, because
the browser was reachable only *underneath* a Firecrawl call. Three successive plans tuned the
ladder's rung order while a missing entry point was the actual problem. `search_site` and
`crawl_site` (2026-07-30) finished the job by giving the browser the other two entry points, at
which point the ladder had nothing left to do.

---

## 2. Configuration

| Env var | Field | Required for | Default |
|---|---|---|---|
| `FIRECRAWL_API_KEY` | `firecrawl_api_key` | **`firecrawl_search` only.** Without it that one tool reports "not available" rather than raising. `fetch_page`, `crawl_site` and `search_site` need no key at all — they are a local browser and public sitemaps. | — |
| `ANTHROPIC_API_KEY` | `anthropic_api_key` | **Nothing in the scraper.** The completeness judge that used it was deleted 2026-07-30 (§1.1). Still required by `Config` itself. | — |
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

---

## 3. How each tool behaves when things go wrong

There is no recovery ladder to catch a bad result any more, so every tool has to be honest
about its own output. That honesty is the replacement for the fallback, and it is enforced
in three places by the same `assess_quality` signal.

### 3.1 A page count is not evidence of content

**`crawl_site` refuses to archive pages that are not content.** Live 2026-07-30: crawling
`docs.crawl4ai.com/core/` returned exactly one 44-byte page — nginx's `403 Forbidden`,
because that path is a directory prefix rather than a page — and an earlier build of the
handler reported *"Crawl complete: saved 1 page(s)"* while filing the error into the research
archive. Nothing is saved when every page grades `fallback`, and the reply quotes the
offending text so the cause is visible.

Only an **all-`fallback`** verdict refuses. `assess_quality`'s `ambiguous` band exists for
genuinely short pages, and discarding those would be its own kind of wrong.

> This was the third instance of one trap in this codebase: `saved 0 page(s)` reported as
> success, `fetch_page`'s `(1 B)` reading like a short page, and now a 403 archived as a
> document. Each time, the tool reported the *shape* of success while holding nothing.
> Assume a fourth is waiting somewhere.

### 3.2 A ranked list is not evidence of relevance

**`search_site` returns nothing rather than pad an answer.** BM25 does not score a
non-matching page 0.0 — it gives *every* page an identical neutral 0.5. The first live run
answered the nonsense query `"zzzq nonexistent topic xyzzy"` with ten confidently-ranked
pages: the Privacy Policy, the Contributing Guide, the home page. Measured signature, 87 URLs
per run on `docs.crawl4ai.com`:

| query | max score | distinct scores |
|---|---|---|
| "deep crawling strategy" | 1.000 | 4 — one peak, three 0.400s, 82 zeros |
| "save a browser login profile for a paywalled site" | 1.000 | 5 |
| "zzzq nonexistent topic xyzzy" | **0.500** | **1** — all 87 identical |
| "qqqqq wwwww eeeee rrrrr" | **0.500** | **1** — all 87 identical |

With any term overlap the best page normalises to 1.0 and misses fall to 0.0. With none,
everything sits at neutral. So "nothing matched" is a *completely flat* distribution, not a
low score — and the vendor's own `score_threshold` cannot express that: 0.51 empties the
nonsense query but also discards the genuine 0.400 and 0.389 hits from a real one.

**`extract_head=True` is mandatory, not a default.** Without it, zero URLs are scored and the
list comes back in arbitrary sitemap order. The vendor's documented example omits the flag,
so copying it yields something that looks like ranked search and is not. Pinned by
`test_search_site_forces_extract_head`.

### 3.3 A byte count is not a warning

**`fetch_page` flags anything that fails `assess_quality`.** `wsj.com` returns exactly 1 B,
and `# Fetched: <url>` / `(1 B)` reads like a successful fetch of a short page. The reply
carries an explicit "this content looks incomplete" instead. See §6 for why WSJ specifically
can never be fixed by a login.

---

## 4. Every tunable

### `crawl_site`

| Parameter | Default | Range | Notes |
|---|---|---|---|
| `url` | — | required | Public http/https only. SSRF-validated before the browser starts. Use a real page URL, not a directory prefix — `/core/` 403s where `/core/quickstart/` works. |
| `max_pages` | 25 | [1, 100] | ~1.2 s per page measured, so 25 ≈ 30 s. |
| `max_depth` | 2 | [0, 5] | Link-hops from the root. 0 fetches only the root. |
| `force_refresh` | `false` | | Skip the 48h Drive manifest cache (§7). |

Every hop stays on the root's host (`include_external=False`). That is a safety property, not
just scoping — it is what stops a hostile page walking the crawler onto another host. The
Playwright per-request SSRF guard is installed as well, and matters most here, because a deep
crawl follows links nobody could have pre-validated.

### `search_site`

| Parameter | Default | Range |
|---|---|---|
| `domain` | — | required, bare hostname — no scheme, no path |
| `query` | — | required, non-empty |
| `limit` | 10 | [1, 50] — bounds the *answer*, not the candidate pool |
| `source` | `sitemap+cc` | `sitemap` (fast, official) / `cc` (Common Crawl) / `sitemap+cc` |

Measured on `docs.crawl4ai.com`: `sitemap` 87 URLs in 5.0 s, `sitemap+cc` 90 in 5.9 s. The
seeder is asked for up to 1,000 URLs regardless of `limit`, because scoring is sparse and a
cap applied *before* ranking would truncate the candidate pool rather than the answer.

### `fetch_page`

| Parameter | Default | Notes |
|---|---|---|
| `url` | — | required. Public http/https only, SSRF-validated before the browser is constructed. |

No Drive write, deliberately: `crawl_site` is the archiving tool, and this one answers "read
me this page" where the result *is* the message.

### `firecrawl_search`

| Parameter | Default | Range |
|---|---|---|
| `query` | — | required, non-empty |
| `limit` | 5 | clamped to [1, 10] |
| `save_to_drive` | `false` | snapshot to `web_docs/searches/` |
| `wait_for_ms` | none | advanced, opt-in |
| `proxy` | none | advanced, opt-in — `basic` / `enhanced` / `auto` |

It returns URLs, titles and a ~400-character snippet — **not** full page text. Until
2026-07-30 it fanned out up to five concurrent local browsers to re-fetch every result;
`fetch_page` is that route now, and a better one.

## 5. Credit-cost model

**Firecrawl — `firecrawl_search` only:**

| Setting | Cost |
|---|---|
| `proxy` unset or `basic` | 1 credit per page |
| `proxy: "enhanced"` | up to 5 credits per page |
| `proxy: "auto"` | 1 credit if basic succeeds; up to 5 if it retries through enhanced |

**Crawl4AI local — `fetch_page`, `crawl_site`, `search_site`:** free. It runs on this machine, so there is no quota, no key and no per-page cost.

A crawl costs exactly one Firecrawl attempt. `enhanced`/`auto` are charged only when you ask for
them explicitly — nothing escalates you into the expensive path automatically.
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
rungs — it wraps the same OSS library this repo already runs locally and free, so at best it would
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
   `local_browser.py` already does the same thing locally, for free, with no key and nothing
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
`ibkrguides.com`), 0.5–1.5 s each, and 3/3 in 2.4 s (0.8 s per page) through one shared browser
session — measured via a `scrape_batch` helper that has since been removed, `crawl_site` now
owning multi-page work. `example.com` returned 166 B locally against Firecrawl's recorded 167 B —
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
> the deciding factor. An earlier note in §11 read WSJ's 1 B as "no login profile"; that
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
python -m ibkr_core_mcp.local_browser create-profile https://www.ft.com
```

This opens a **real, visible browser**. Log in by hand, then confirm in the terminal. The
resulting cookies and local storage are copied to `~/.ibkr_core/crawl4ai_profiles/<domain>/`.

**No password is ever seen or stored by this package** — only the resulting browser session.
Nothing is transmitted anywhere; the profile is a local directory.

**2. Read the article** — `fetch_page` on the URL. It goes straight to the browser, finds the
profile by domain, and returns the full text. Do **not** route a paywalled article through
`firecrawl_search` first: Firecrawl cannot log in, so it spends a credit to be handed the
subscription stub. `fetch_page` and `crawl_site` both use the saved profile, and both state
whether one was found, so a stub is never silently mistaken for the article.

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
python -m ibkr_core_mcp.local_browser list-profiles
```

Prints each saved domain, its path, and how many days old the session is. Sessions expire; when
one does, the symptom is a truncated article rather than an error. Re-run `create-profile` for
that domain.

---

## 7. Drive cache layout

`crawl_site` always persists. `firecrawl_search` persists only when `save_to_drive=true`. `fetch_page` and `search_site` never write to Drive.

```text
<gdrive_folder_id>/
  web_docs/                              ← or GDRIVE_WEB_DOCS_FOLDER_ID
    <url-slug>/                          ← one folder per crawled root URL
      index.json                         ← {url, crawled_at, pages: [{url, file_id}]}
      <page-slug>.md                     ← one file per page
    searches/
      <YYYYMMDDTHHMMSSZ>-<query-slug>.md
```

**Crawls are cached for 48 hours.** Before opening a browser at all, `crawl_site` checks
Drive for an existing manifest for that URL. If one exists and is under 48h old, it returns the
cached result and fetches nothing. Pass `force_refresh=true` to override.

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
| "firecrawl_search is not available: FIRECRAWL_API_KEY is not configured" | No key in the environment | Set `FIRECRAWL_API_KEY`. Only `firecrawl_search` needs it — the other three tools work without one. |
| "Crawl of … fetched N page(s) but none of them is content" | Every page graded `fallback`. **Nothing was saved** — the reply quotes the offending text | Read the quote. A `403 Forbidden` usually means you gave a directory prefix; use a real page URL. Otherwise anti-bot, a login wall, or unfinished JS. |
| "No pages on … matched" | The site was reachable and scored; nothing on it is about that query. A real answer, not a failure | Different wording, or `source="sitemap+cc"`. Use `firecrawl_search` to look beyond the one domain. |
| `search_site` returns fewer results than `limit` | BM25 is sparse — typically 4 of 87 URLs score above zero | Working as intended. The tail would be pages the query never matched. |
| Page returns exactly **1 B** at `http=401` | Anti-bot (DataDome on WSJ) refusing the automated browser. **A login profile does not help** — the block precedes authentication | No fix from this side. See §6. |
| Article is truncated on a site you subscribe to | No profile matched, or the session expired — but rule out anti-bot first (row above) | `list-profiles` to check; re-run `create-profile` |
| "needs the local browser" / "Crawl4AI is not installed" | Optional extra absent | `pip install "ibkr_core_mcp[scraper]" && crawl4ai-setup` |
| Same URL crawled twice returns instantly | 48h Drive cache hit — working as designed | `force_refresh=true` to re-crawl |
| A crawl is slower than expected | ~1.2 s per page, and `max_depth` multiplies the page count | Lower `max_pages` or `max_depth`. There is no polling budget to raise any more — nothing waits on a remote job. |

**SSRF protection is two-layered and not optional.** `ClaudeToolkit._validate_public_url` rejects
private, loopback and link-local hosts before any URL reaches Crawl4AI, and a Playwright-level
per-request guard re-checks every navigation, redirect and subresource at the moment it is sent —
closing DNS-rebinding gaps the first layer cannot. A blocked URL produces a message, not a
silent skip.

---

## 10. Live testing — mandatory, and how to run it

**A green unit suite is not evidence that these tools work.** Every defect in the
2026-07-30 rewrite was found by running a tool, never by a test failing: four in one
session, each behind a passing suite. Before that, `create_profile` shipped with three
green tests having never once been executed, and broke on its first real invocation for
three independent reasons. Mocks here have repeatedly been weaker than the dependency they
stand in for — a fake seeder scores a miss 0.0, the real one scores it 0.5.

So the rule for this subsystem is: **any change to a web tool requires a live run before
it is called done, and the run is recorded in §11.**

### The suite

```bash
pytest tests/test_web_tools_live.py -v -m integration
```

11 tests, ~28 s, and every one is a regression guard for a defect a live run found — the
docstring names which. Read the docstring before concluding a failing test is wrong.

| Requirement | Gates | Cost |
|---|---|---|
| `[scraper]` extra + `crawl4ai-setup` | the 10 browser tests | free |
| `FIRECRAWL_API_KEY` | 1 whole-web search test | ~1 credit |

Each requirement skips independently rather than failing, so a machine without a Firecrawl
key still gets 10 of 11.

**An exhausted quota is not a test failure.** HTTP 402 (out of credits) and 429 (rate
limited) describe the account, so the affected tests skip with the real message in the skip
reason rather than reporting a defect that does not exist — loud, never swallowed. This
fired for real on 2026-07-30. The three browser tools are unaffected by any of it: free is
free.

### What it covers, and why each one exists

| Test | The defect it guards |
|---|---|
| `search_site_ranks_the_right_page_first` | `extract_head=True` is mandatory — without it **zero** URLs are scored and the list is sitemap order, while still looking ranked. **The vendor's own example omits the flag.** |
| `search_site_reports_no_match_instead_of_ranking_noise` | BM25 scores a non-match **0.5, not 0.0**. A nonsense query once returned ten confidently-ranked pages: Privacy Policy, Contributing Guide, home page. |
| `search_site_needs_no_firecrawl_key` | Free site search is why the paid crawl rung could go. A key requirement creeping back would silently undo that. |
| `fetch_page_returns_real_content_without_crying_wolf` | A guard that fires on everything is as useless as one that never fires. |
| `fetch_page_flags_an_anti_bot_stub_rather_than_presenting_it` | `wsj.com` returns 1 B at HTTP 401; `(1 B)` reads like a short page unless something says otherwise. |
| `crawl_site_refuses_to_archive_an_error_page` | A 44-byte nginx 403 was archived while the reply said "Crawl complete: saved 1 page(s)". |
| `crawl_site_archives_a_real_page_and_does_not_duplicate_the_root` | The deep-crawl strategy returns the root **twice**, depth 0 and depth 1; undeduplicated the manifest claims a page count the archive lacks. |
| `firecrawl_search_reaches_hosts_search_site_never_could` | The entire justification for keeping the Firecrawl dependency. |
| `private_hosts_are_refused_before_any_request` ×3 | Every URL-taking tool must refuse a private host *before* the request it is meant to prevent. |

### Sibling suites

| File | Scope |
|---|---|
| `tests/test_web_tools_live.py` | **the four tools end to end — start here** |
| `tests/test_local_browser.py` | browser internals, crawl4ai mocked |
| `tests/test_crawl4ai_live.py` | one real Playwright round-trip |
| `tests/test_web_scraper_live.py` | the Firecrawl client directly |
| `tests/test_web_scraper_drive_live.py` | real Drive persistence |

### Choosing a target

**Not `example.com`.** It yields ~166 B, which correctly grades `fallback`, so it is a bad
probe for anything but the too-thin path — it would make a working tool look broken.
`docs.crawl4ai.com` is used throughout: small sitemap, static content, tolerant of
automation. `docs.crawl4ai.com/core/` is deliberately kept as the 403 fixture.

---

## 11. Verified behaviors

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
| 2026-07-30 | **Closing verification.** Full review of code, docstrings and every doc, then the whole gate: `ruff check` + `ruff format` + `mypy` clean, **790 unit tests**, **19 live tests** in 38 s across five suites. Tool counts corrected in 9 places (they had drifted to 42/43/45 against a real 44 toolkit / 46 MCP), and README, SECURITY.md, `api-usage-examples.md` and `test-coverage.md` were still describing the deleted ladder — including SECURITY.md documenting its SSRF mitigation in terms of three functions that no longer exist. **The mitigation itself was never weakened; only its call sites moved.** |
| 2026-07-30 | **The live Drive tests demanded a var the code does not need, and so never ran.** Their fixture required `GOOGLE_DRIVE_FOLDER_ID` — the one var this repo's documented standalone-dev `.env` deliberately omits — while `WebDocsStore` is happy with *either* that or `GDRIVE_WEB_DOCS_FOLDER_ID`. Root cause: the test re-implemented the store's folder lookup (query for `web_docs` under the root) instead of calling `_get_web_docs_folder_id()`, and the duplicate needed more than the original. Both tests therefore skipped on every default run, silently, because **a skip is not a failure**. Fixed by requiring only what the code requires and resolving the folder through the store. **19/19 live now pass on this repo's own `.env` with no special setup**, and both roots still work. |
| 2026-07-30 | **Full live suite green with credits restored: 19 passed, 0 skipped for credit reasons.** `test_web_tools_live.py` 11/11 in 32 s (the 402 skip now a pass), `test_web_scraper_live.py` 4/4, `test_crawl4ai_live.py` 1/1, `test_web_scraper_dev_cache_live.py` 1/1, `test_web_scraper_drive_live.py` 2/2. **Total cost: 17 Firecrawl credits.** The browser tools spent nothing. The Drive pair needs `GOOGLE_DRIVE_FOLDER_ID`, which this repo's standalone-dev `.env` deliberately omits — pass it explicitly to run them. |
| 2026-07-30 | **`test_crawl_site_saves_pages_to_drive` had never once executed.** Repointed earlier the same day from the deleted `firecrawl_crawl`, it stayed skipped — first on a missing `GOOGLE_DRIVE_FOLDER_ID`, then on the 402 — so the rewrite was unverified for hours while looking fine. Run properly it passes. **A repointed test is a new test: it has not run until you have watched it run.** |
| 2026-07-30 | **The Firecrawl free tier ran dry mid-session (HTTP 402), and the live suite is what found it.** A day of scraper work exhausted the credits. Four live tests across three files were failing as though the code had regressed. 402 and 429 describe the *account*, not the code under test, so all four now **skip with the real message in the skip reason** — loud, never swallowed into a green run. Note the client *raises* `FirecrawlError` for account statuses rather than returning text, so a string-based guard cannot see that path and it needed its own handler. **The three browser tools were unaffected: free is free.** |
| 2026-07-30 | **Live acceptance suite run: 10 passed, 1 skipped in 27 s** (the skip being the 402 above) (`pytest tests/test_web_tools_live.py -m integration`), covering all four tools through `ClaudeToolkit.execute()` — ranking, the no-match plateau, the anti-bot flag, the 403 refusal, root deduplication, whole-web reach, and SSRF refusal on all three URL-taking tools. This is the run that promoted the session's throwaway verification scripts into committed, repeatable tests. |
| 2026-07-30 | **Crawl4AI searches a site natively, and free.** `AsyncUrlSeeder` + BM25 on `docs.crawl4ai.com`: "deep crawling strategy" ranked `/core/deep-crawling/` first at 1.000; "save a browser login profile for a paywalled site" ranked `/advanced/undetected-browser/` first at 1.000. 87 URLs from the sitemap in 5.0 s, 90 in 5.9 s with `sitemap+cc`. This is what made `search_site` possible and Firecrawl's crawl half redundant. It is **domain-scoped by construction** (`urls(domain, config)`), so it can search *a* site but never *the web* — which is the entire reason `firecrawl_search` survives. |
| 2026-07-30 | **`extract_head=True` is mandatory for BM25, and the vendor's example omits it.** With it, 87 of 87 URLs carry a `relevance_score`. Without it, **zero** do and the list is sitemap order. Head extraction is what BM25 scores against. Copying the documented example verbatim produces something that looks like ranked search and is not. Pinned by `test_search_site_forces_extract_head`. |
| 2026-07-30 | **A non-matching BM25 query scores 0.5, not 0.0.** The first live `search_site` run answered "zzzq nonexistent topic xyzzy" with ten confidently-ranked pages — Privacy Policy, Contributing Guide, home page — every one at exactly 0.500. Two nonsense queries each produced 87 URLs at 0.5 with **one** distinct score; two real queries peaked at 1.0 with 4–5 distinct scores. So "nothing matched" is a *flat distribution*, not a low score. The unit tests had mocked a miss as 0.0 — **a mock weaker than its dependency**, the same failure mode that let `create_profile` ship having never run. |
| 2026-07-30 | **The deep-crawl strategy returns the root URL twice**, at depth 0 and depth 1, byte-identical (`docs.crawl4ai.com/` twice at 14,030 B in a 6-page crawl). Fed straight to `save_crawl` that writes one file but appends two manifest entries, so the reply claims a page count the archive does not contain. Found by probing the real API *before* writing `crawl_site`, not by a test failing after. `include_external=False` was confirmed in the same run: 6 pages, exactly one hostname. |
| 2026-07-30 | **An error page is still a page.** Crawling `docs.crawl4ai.com/core/` returned one 44-byte page — nginx's `403 Forbidden`, because that path is a directory prefix — and the handler reported "Crawl complete: saved 1 page(s)" while filing it into the research archive. Third instance of this trap here, after "saved 0 page(s)" as success and `fetch_page`'s "(1 B)". `crawl_site` now refuses to save when every page grades `fallback`, and quotes the offending text. |
| 2026-07-30 | **The Retry-After cap was a doc error, not a code error.** This reference said the client honors `Retry-After` "capped at 30s"; Firecrawl's published snippet applies `min(2 ** attempt, 30)` to the *exponential branch only* and says of the header "wait **at least** that long". The code matched the vendor all along. Caught only because the vendor page was re-fetched before editing the code to match the sentence — the standing rule works in this direction too. |
| 2026-07-28 | **The paywall path had never been executed.** `~/.ibkr_core/crawl4ai_profiles` did not exist on this machine — no login profile had ever been created — while §6, the profile-lookup code, the `create-profile` CLI and the paywall markers were all present, tested and documented. A capability can be complete in every respect except having been run once. |
| 2026-07-28 | The `janbuchar/crawl4ai` Apify Actor had **0 successful public runs out of 29 in 30 days** (26 failed, 3 aborted) with a latest build from 2025-05-06, per Apify's own public API. Its `isDeprecated` flag is nonetheless `false`, and its 3.26 rating comes from 2 reviews. Rejected as a rung — see §5.1. Judge a hosted dependency by run statistics, not status flags or stars. |
| 2026-07-28 | `crawl4ai` OSS is at 0.9.2 and this repo's `crawl4ai>=0.5.0` floor is still correct: the two published migration guides (webscraping-strategy, table extraction v0.7.3) touch APIs `local_browser.py` does not use — it uses only `AsyncWebCrawler`, `BrowserConfig` and `BrowserProfiler`. Checked so it need not be re-checked. |
| 2026-07-28 | **A consuming project can silently run stale ibkr_core_mcp code.** claudia_ui installs this package with `editable_mode=strict`, which resolves imports through a snapshotted symlink farm under `build/__editable__…/`. A module added after that install is **invisible** — a newly added `ibkr_core_mcp` module raised `ModuleNotFoundError` in ClaudIA while existing on disk here. Re-run the editable install in every consumer after adding a module, not just after adding a tool. |
| 2026-07-28 | **The `[scraper]` extra was not installed in claudia_ui**, so inside ClaudIA the fallback rung was dark: detection worked, recovery dead-ended, and nothing said so. Fixed the same day by installing `crawl4ai` + Playwright there. A capability can be fully coded, fully tested and fully documented and still be unreachable in the app that needs it — check the consumer, not just the library. |

---

## 12. API reference

All types live in `ibkr_core_mcp.web_scraper` and `ibkr_core_mcp.local_browser`. Note that
`FirecrawlClient` and `WebDocsStore` are **not** re-exported from the package root — only the
exception types `FirecrawlError` and `WebDocsStoreError` are.

```python
from ibkr_core_mcp.web_scraper import FirecrawlClient, WebDocsStore, content_bytes

# Whole-web search — the only Firecrawl surface that still exists.
client = FirecrawlClient(api_key)                      # ValueError if key is empty
client.search(query, limit=5, *, wait_for_ms=None, proxy=None, timeout_ms=None)
# -> list[{"url", "title", "markdown", "metadata"}]
# `.crawl()` was REMOVED 2026-07-30 — use local_browser.crawl_site().

content_bytes(pages) -> int                            # total UTF-8 bytes of markdown

# Drive persistence — engine-agnostic; it never knew who produced its pages.
store = WebDocsStore(config)                           # no network I/O at construction
store.get_cached_crawl(url, max_age_hours=48.0)        # -> manifest dict | None
store.save_crawl(url, pages)                           # -> manifest dict
store.save_search(query, results)                      # -> Drive file ID
```

```python
from ibkr_core_mcp.local_browser import (
    Crawl4AIScraper, Crawl4AIUnavailableError, assess_quality, crawl_site, create_profile,
    list_profiles, search_site,
)

# One page.
Crawl4AIScraper(profiles_dir).scrape(url)              # -> {"url", "markdown"}

# A whole site, shaped for save_crawl(). Same-host only; root deduplicated.
crawl_site(url, profiles_dir, max_pages=25, max_depth=2)
# -> list[{"url", "markdown", "metadata": {"depth": int}}]

# Pages within one site, BM25-ranked. [] means nothing matched, which is an answer.
search_site(domain, query, limit=10, source="sitemap+cc")
# -> list[{"url", "title", "score"}]

assess_quality(markdown, metadata, url)                # -> "ok" | "ambiguous" | "fallback"
create_profile(url_or_domain, profiles_dir)            # -> Path (interactive, needs a TTY)
list_profiles(profiles_dir)                            # -> [(domain, path, age_days)]
```

`judge_completeness_llm` was removed 2026-07-30 — the scraper makes no Anthropic API call.

**Related:** `docs/tools-reference.md` (tool schemas), `docs/external-docs-reference.md` (official
URLs for every external API).
