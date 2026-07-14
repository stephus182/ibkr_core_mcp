# Follow-up Doc Improvement Using the Upgraded `web_scraper` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Follow up on the specific gaps and open questions left by the 2026-07-14 live-verification
pass (`docs/plans/2026-07-14-continued-docs-audit-plan.md`, commit `b1a4efb`), now that
`ibkr_core_mcp/web_scraper.py` has been upgraded (commit `da5289f`, merged to `main` after that
pass) with:

- **Retry-with-backoff** on all three Firecrawl request call sites (search, crawl job-start, crawl
  polling) — honors `Retry-After` when present, else `min(2**attempt, 30)` + jitter, retryable on
  429/408/500/502/503/504. This directly addresses the repeated `RATE LIMITED, retrying in Ns`
  failures the previous pass hit and had to hand-roll its own backoff loop around.
- **Drive read-cache** — `WebDocsStore.get_cached_crawl(url, max_age_hours=48.0)` returns an
  existing Drive manifest for a URL if it's less than 48h old, with **zero Firecrawl requests**.
  `ClaudeToolkit`'s `firecrawl_crawl` tool now checks this automatically; pass
  `force_refresh: true` to bypass it. This is the fix for the exact problem flagged mid-pass
  last time ("WebDocsStore never checks for existing cached content before fetching").

**Do not repeat the previous pass's workaround.** That pass built its own ad-hoc Python script
around `FirecrawlClient.crawl()` directly, with manual `time.sleep()` backoff and scratch-file
caching, specifically because the Drive cache didn't exist yet and rate-limiting had to be handled
by hand. That reason no longer applies. Every task below should route fetches through
`ClaudeToolkit.firecrawl_crawl` / `firecrawl_search` (or `WebDocsStore.get_cached_crawl` +
`FirecrawlClient` directly if not running inside a `ClaudeToolkit` context) so the retry and Drive
caching are actually exercised — that's the point of this plan's title. Do **not** write a new
manual scratch-file cache or a hand-rolled sleep/backoff loop; if you find yourself doing either,
stop and check whether you're bypassing the upgrade instead of using it.

**Do not repeat this plan's own methodology mistake from the prior pass:** check
`docs/audits/audit-evidence/scrapes/manifest.json` (and Drive's `web_docs/` folder, via the
upgraded `get_cached_crawl`) for existing fresh coverage before fetching anything new.

**Tech Stack:** `Agent` tool (`subagent_type: general-purpose`), `ClaudeToolkit.firecrawl_crawl`
/ `firecrawl_search`, pytest, git. No new dependencies.

**Do not:**
- Modify `docs/plans/` or `docs/audits/` (except this plan's own checkbox updates as tasks
  complete).
- Silently invent a replacement URL for an unresolved citation — if a task can't find a
  definitive official source, document that explicitly (as the prior pass did for the Flex
  "all trade origins" claim) rather than guessing.
- Treat "the tool returned a cached result" as license to skip verifying the *content* is still
  accurate — a 48h-old cache being reused doesn't mean the underlying claim in the doc is correct,
  only that the fetch was cheap. Read what comes back.

---

## Priority queue

| # | Task | Source of the open question |
|---|---|---|
| 1 | Re-attempt the 5 pages `FirecrawlClient.crawl()` returned zero content for last time | `project_docs_accuracy_pass_2026_07_13.md` memory, "Real findings from live-fetching" |
| 2 | Fix `FirecrawlClient.crawl()`'s missing `next`-cursor pagination for >10MB results | `docs/external-docs-reference.md`'s "Missing URLs / known gaps" section |
| 3 | Find a properly-sourced citation for the Flex "all trade origins included" claim | Same section, "Citation fix" note in the Flex table |
| 4 | Check for a `clientportal`-scoped Flex Queries overview page (consistency with the rest of the Flex URL table) | Same section |
| 5 | Confirm Crawl4AI's `BrowserProfiler` 0.5.0-introduction claim against release notes/changelog | Same section |

---

## Task 1: Re-attempt the 5 previously-empty Firecrawl fetches

**Files:**
- Investigate only — no doc edits expected unless a fetch succeeds and reveals new information
  worth adding to `docs/gateway-auth-reference.md` or `docs/external-docs-reference.md`.

Last time, `FirecrawlClient.crawl(url, max_pages=1)` returned zero pages entirely (not a 429, a
genuinely empty result) for these 5 URLs — `WebFetch` was used as a fallback and got real content
for all of them, suggesting a JS-rendering limitation rather than a rate-limit problem:
- `https://developers.google.com/drive/api/reference/rest/v3/files/list`
- `https://developers.google.com/drive/api/quickstart/python`
- `https://google-auth.readthedocs.io/en/stable/reference/google.oauth2.credentials.html`
- `https://docs.anthropic.com/en/docs/build-with-claude/tool-use` (now `platform.claude.com/docs/en/docs/build-with-claude/tool-use` — already fixed in docs, but worth re-testing the fetch itself)
- `https://docs.anthropic.com/en/api/messages` (now `platform.claude.com/docs/en/api/messages`)

- [x] **Step 1: Re-fetch each URL through the upgraded client**

Use `ClaudeToolkit.firecrawl_crawl` (or `FirecrawlClient.crawl()` directly with the new
retry-with-backoff already built in — no manual sleep loop needed) for each of the 5 URLs above
(using the updated `platform.claude.com` URLs for the last two). For each:
1. Record whether it now returns real markdown content or is still empty.
2. If still empty for all 5, that confirms this is a content-extraction limitation (likely
   JS-rendered SPA pages Firecrawl's default scrape can't handle without `waitFor`/proxy options
   the current `crawl()` method signature doesn't expose), not something the retry/cache upgrade
   was meant to fix — document this conclusion plainly, don't leave it ambiguous.
3. If any now succeed, compare the returned content against the `WebFetch`-derived summaries
   already in the docs (`docs/gateway-auth-reference.md`'s Google Drive / OAuth sections,
   `docs/external-docs-reference.md`'s Anthropic API rows) and flag any discrepancy.

- [x] **Step 2: Report findings, no fix needed if inconclusive**

If this step reveals `crawl()` still can't extract JS-rendered pages, that's a known, documented
limitation (not a bug to fix in this task) — note it in
`docs/external-docs-reference.md`'s "Missing URLs / known gaps" section instead of leaving Task 1
open-ended.

---

## Task 2: Fix `FirecrawlClient.crawl()`'s missing pagination cursor

**Files:**
- Modify: `ibkr_core_mcp/web_scraper.py` (`FirecrawlClient.crawl()`)
- Test: `tests/test_web_scraper.py`

`crawl()`'s poll loop reads `data.get("data")` per poll but never reads or follows
`data.get("next")` — the cursor Firecrawl's `GET /crawl/{id}` response includes when the crawl's
completed result exceeds 10MB ("The URL to retrieve the next 10MB of data"). For a large crawl,
`crawl()` currently returns only the first chunk despite its own docstring's claim that it
"returns all pages collected."

- [x] **Step 1: Confirm the gap still exists**

Read the current `ibkr_core_mcp/web_scraper.py`'s `crawl()` method in full. Confirm `next` is
still unread. (If commit `da5289f`'s retry-with-backoff changes touched this method's structure,
re-verify the finding against the current code rather than assuming the old line numbers still
apply.)

- [x] **Step 2: Write a failing test (TDD, superpowers:test-driven-development)**

Mock a crawl-poll response sequence where the final "completed" response includes a `"next"` URL
and fewer pages than the crawl's total; assert `crawl()` currently returns only the first batch
(RED — confirms the bug), then implement following `next` until it's absent, accumulating all
pages, then confirm GREEN.

- [x] **Step 3: Run the full unit suite**

```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
python -m pytest -m "not integration" -q
```

- [x] **Step 4: Dispatch a fresh verification agent, then commit**

Same pattern as prior passes: fresh `Agent`, re-read the fixed method and the new test, confirm
PASS, rerun the suite, then commit with a message citing the `next`-cursor Firecrawl behavior and
this plan.

---

## Task 3: Source the Flex "all trade origins included" claim properly

**Files:**
- Investigate: `ibkr_core_mcp/flex_query.py`, `ibkr_core_mcp/claude_tools.py` (3 occurrences of
  the "What Flex covers" docstring)
- Modify: same files' `Source:` citations, plus `docs/external-docs-reference.md`'s Flex table

The prior pass re-pointed this claim's citation to IBKR's Activity Statements glossary page
(confirms account-level, not per-platform, reporting) but could not find a single official page
that explicitly enumerates "CP API, mobile app, TWS, web portal" together for Flex specifically.

- [x] **Step 1: Search for a better source using `firecrawl_search`**

Use `ClaudeToolkit.firecrawl_search` (or `FirecrawlClient.search()` directly) with queries such as
"IBKR Flex Activity Statement all order origins TWS mobile API", "Interactive Brokers Activity
Statement trade origin completeness", etc. — try a few phrasings. Read full markdown for any
promising result (`WebDocsStore.get_cached_crawl` first if a Drive snapshot already exists for a
candidate URL).

- [x] **Step 2: If found, update the citation; if not, document that explicitly**

If a page explicitly backs the claim, update `Source:` in all 3 docstring locations and the Flex
row in `docs/external-docs-reference.md`. If nothing definitive turns up after a reasonable
search effort, update the "Missing URLs / known gaps" section to say a further search was
attempted and still came up empty, rather than leaving it looking un-investigated.

- [x] **Step 3: Run the full unit suite, verify, commit** (same pattern as prior tasks).

---

## Task 4: Check for a `clientportal`-scoped Flex Queries overview page

**Files:**
- Modify: `docs/external-docs-reference.md` (Flex table) if a page is found

Every other Flex citation in `docs/external-docs-reference.md`'s table is a `clientportal` page
except the orgportal (institutional) Flex Queries landing page. Check whether
`https://www.ibkrguides.com/clientportal/performanceandstatements/flex.htm` (or similar) exists
and is the retail-portal equivalent — if so, consider whether it's a better fit for a
individual-account-focused package than the orgportal page, or whether both should be listed.

- [x] **Step 1: Fetch and compare**, using `firecrawl_crawl`/`get_cached_crawl` as above.
- [x] **Step 2: Update the doc if a better/complementary page is found; otherwise note the
  orgportal page is intentional (e.g. if no clientportal equivalent exists) in the doc.**
- [x] **Step 3: Run the full unit suite, verify, commit.**

---

## Task 5: Confirm Crawl4AI `BrowserProfiler` 0.5.0 introduction against release notes

**Files:**
- Modify: `docs/external-docs-reference.md` (Crawl4AI section) if a citation is found

CLAUDE.md and `docs/external-docs-reference.md` state `crawl4ai>=0.5.0` is a hard floor because
`BrowserProfiler` doesn't exist in 0.4.x, verified only via PyPI wheel inspection (0.4.248 checked)
— no `docs.crawl4ai.com` page or changelog has been cited confirming *when* it was introduced.

- [x] **Step 1: Search Crawl4AI's GitHub releases/CHANGELOG** (e.g.
  `https://github.com/unclecode/crawl4ai/releases` or a `CHANGELOG.md` in the repo) via
  `firecrawl_crawl` for the 0.5.0 release notes mentioning `BrowserProfiler`.
- [x] **Step 2: If found, add the citation to `docs/external-docs-reference.md`'s Crawl4AI
  section, replacing "unverifiable from these pages alone" with the actual source. If not found,
  leave the PyPI-wheel-inspection method as the citation — it's still valid evidence, just note
  that a docs/changelog citation was searched for and not found.**

  Found: `https://raw.githubusercontent.com/unclecode/crawl4ai/main/CHANGELOG.md`, fetched via
  `FirecrawlClient.crawl()`, has a "Version 0.5.0 (2025-03-02)" entry listing under "Added" —
  `*(profiles)* Add BrowserProfiler class for dedicated browser profile management`. Added as
  a citation (table row + paragraph) in `docs/external-docs-reference.md`'s Crawl4AI section
  and removed the corresponding "Missing URLs / known gaps" bullet.
- [x] **Step 3: Run the full unit suite, verify, commit.**

---

## Final verification sweep (after all 5 tasks)

- [ ] **Step 1: Full unit suite one more time**

```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
python -m pytest -m "not integration" -q
```

- [ ] **Step 2: Confirm each task committed separately**

```bash
git log --oneline <starting-sha>..HEAD -- docs/ ibkr_core_mcp/
```

- [ ] **Step 3: Update memory**

Update `project_docs_accuracy_pass_2026_07_13.md` (or a new dated memory) with which of these 5
follow-ups actually got resolved vs. remained open, so the next pass doesn't re-investigate the
same dead ends.
