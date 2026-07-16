# Crawl4AI Fallback: Browser Reuse (Crawl) + Bounded Concurrency (Search) — Design

**Created:** 2026-07-15
**Status:** Approved — ready for implementation plan

---

## Problem

`Crawl4AIScraper.scrape(url)` (`ibkr_core_mcp/scrape_fallback.py:362`) launches a fresh headless
Chromium process on every call — documented as an accepted tradeoff in its own docstring
("Launches a fresh headless Chromium instance per call... see the caller-side note...") and in
`claude_tools.py:2787-2793`'s comment on `_handle_firecrawl_crawl`'s per-page fallback loop.

Two distinct call sites are affected differently:

- **`_handle_firecrawl_crawl`**: loops over every page in one crawl, calling
  `_scrape_with_fallback` (which calls `Crawl4AIScraper.scrape`) sequentially per page. Firecrawl's
  `crawl()` only returns pages within the same site as the root URL (confirmed:
  `web_scraper.py:250`, "Crawl a site starting from url"), so every page in one crawl call needs
  the *same* `BrowserConfig` (same saved-login-profile decision). A crawl with many
  blocked/paywalled pages pays full Chromium startup cost once per page, sequentially, which can
  push total tool latency past the caller's own `timeout_s` budget.
- **`_handle_firecrawl_search`**: loops over search results, also calling `_scrape_with_fallback`
  sequentially per result. Results are typically different domains, each potentially needing a
  *different* saved profile — browser/config reuse across the loop isn't valid here the way it is
  for the crawl loop. But the loop is still fully sequential, so N slow browser launches still
  queue up back-to-back with no reuse *or* parallelism benefit.

## Goals

- Crawl path: replace N sequential Chromium launches (one per fallback-needing page) with one
  Chromium launch per `firecrawl_crawl` call, reused across every page in it.
- Search path: replace N sequential Chromium launches with bounded concurrent launches, since
  reuse isn't valid across different domains but independent parallel launches are.
- Preserve every existing observable behavior: `_scrape_with_fallback`'s contract (used directly by
  many existing tests), all note text, all exception-type-specific degradation behavior
  (`Crawl4AIUnavailableError` vs. generic failure vs. empty result), and the SSRF guard's coverage
  (every individual page/result URL is still validated before any local fetch, regardless of
  batching or concurrency).

## Non-goals (explicitly deferred)

- **No overall time budget/deadline on the fallback batch itself** (e.g. "stop fetching more pages
  once cumulative fallback time exceeds N seconds"). That's a different problem (slow individual
  page loads, not launch overhead) than what was found, and solving it raises its own design
  questions (what happens to skipped pages — original content? a note?) that weren't part of this
  finding. Deferred, not silently dropped.
- **No shared, persistent browser pool spanning `ClaudeToolkit`'s whole lifetime** (i.e. reused
  across separate tool calls, not just within one). This tool is an occasional
  reference-doc-archiving utility (per its own tool description), not a high-QPS service — a
  persistent pool's added complexity (idle-eviction, cross-call thread-safety, profile-per-domain
  lifecycle) isn't justified by the actual load pattern.
- **No change to `judge_completeness_llm`** (the Haiku completeness-check call) beyond it now
  potentially running concurrently across search results — its existing single-call, fail-safe
  (catch-and-keep-original-on-error) behavior is unchanged and already handles a transient failure
  correctly, concurrent or not.

## Design

### 1. `scrape_fallback.py` — `Crawl4AIScraper.scrape_batch`

```python
def scrape_batch(self, urls: list[str], profile_domain: str) -> dict[str, dict[str, str] | Exception]:
```

Opens **one** `AsyncWebCrawler` (config built once from `profile_domain` — the caller passes the
crawl's *root* domain, not each page's own domain, since same-site pages share the same profile
decision by construction). Installs the SSRF hook (`_install_ssrf_guard`) once on that single
session. Then sequentially `await crawler.arun(url)`s every URL in `urls` *within* that one
session — each URL's outcome is caught independently (`try/except Exception` per URL, inside the
loop) and stored in the returned dict as either a `{"url", "markdown"}` result dict or the raised
`Exception` object. One URL failing never aborts the batch or closes the browser early. Empty
`urls` returns `{}` immediately, before even checking whether `crawl4ai` is installed.
`Crawl4AIUnavailableError` (missing dependency) still raises synchronously, before any browser
launches — an install-time problem, not a per-URL one — so callers must handle it as a possible
exception from the call itself, not expect it inside the returned dict (see the `claude_tools.py`
batch caller below, which does exactly this).

`scrape(url)` is rewritten as a 1-URL delegation to `scrape_batch`:

```python
def scrape(self, url: str) -> dict[str, str]:
    outcome = self.scrape_batch([url], profile_domain=url)[url]
    if isinstance(outcome, Exception):
        raise outcome
    return outcome
```

This removes the duplicated browser-config-building logic between the two methods — `scrape_batch`
becomes the one real implementation. Verified against all 5 existing `Crawl4AIScraper`-level tests
in `tests/test_scrape_fallback.py`: since `scrape()` still builds the exact same `BrowserConfig`
from the exact same domain-of-`url` and installs the exact same hook exactly once, none of those
tests need to change.

### 2. `claude_tools.py` — crawl path

`_scrape_with_fallback` (used by the search path — see below — and directly by several existing
tests) keeps its exact existing signature and return contract, but its body is split into two
private pieces so the crawl path can reuse the "decide" half without the "fetch" half:

- `_assess_fallback_need(url, markdown, metadata) -> tuple[bool, str, str]` — returns
  `(needs_fallback, markdown_if_not_needed, note_if_not_needed)`. Contains everything in today's
  `_scrape_with_fallback` *before* the `self._crawl4ai.scrape(url)` call: the `assess_quality`
  check, the ambiguous-case `judge_completeness_llm` call (including its own fail-safe
  except-and-keep-original branch, unchanged), and the SSRF `_validate_public_url` pre-check.
- `_finalize_fallback_result(url, original_markdown, outcome: dict[str, str] | Exception) -> tuple[str, str, bool]`
  — everything *after* that call: turns either a successful result dict or a raised exception into
  `(final_markdown, note, used_fallback)`, distinguishing `Crawl4AIUnavailableError` from a generic
  failure from an empty-content result, exactly matching today's three distinct note strings.

`_scrape_with_fallback` itself becomes:

```python
def _scrape_with_fallback(self, url, markdown, metadata):
    needs_fallback, md_if_not, note_if_not = self._assess_fallback_need(url, markdown, metadata)
    if not needs_fallback:
        return md_if_not, note_if_not, False
    if self._crawl4ai is None:
        self._crawl4ai = Crawl4AIScraper(self._config.crawl4ai_profiles_dir)
    try:
        result = self._crawl4ai.scrape(url)
    except Exception as exc:
        return self._finalize_fallback_result(url, markdown, exc)
    return self._finalize_fallback_result(url, markdown, result)
```

New `_apply_crawl4ai_fallback_batch(root_url, pages) -> int` (used only by
`_handle_firecrawl_crawl`, replacing its entire `for page in pages: ...` block):

```python
def _apply_crawl4ai_fallback_batch(self, root_url, pages):
    candidates = []  # list of (page, original_markdown)
    for page in pages:
        url = page.get("url", "")
        needs_fallback, md_if_not, _note = self._assess_fallback_need(
            url, page.get("markdown", ""), page.get("metadata")
        )
        if needs_fallback:
            candidates.append((page, page.get("markdown", "")))
        else:
            page["markdown"] = md_if_not

    if not candidates:
        return 0

    if self._crawl4ai is None:
        self._crawl4ai = Crawl4AIScraper(self._config.crawl4ai_profiles_dir)

    urls = [p.get("url", "") for p, _ in candidates]
    root_domain = urllib.parse.urlparse(root_url).hostname or ""
    try:
        outcomes = self._crawl4ai.scrape_batch(urls, profile_domain=root_domain)
    except Exception as exc:
        outcomes = {u: exc for u in urls}

    fallback_count = 0
    for page, original_markdown in candidates:
        url = page.get("url", "")
        outcome = outcomes.get(url, RuntimeError(f"Crawl4AI batch returned no result for {url}"))
        final_markdown, _note, used_fallback = self._finalize_fallback_result(
            url, original_markdown, outcome
        )
        page["markdown"] = final_markdown
        if used_fallback:
            fallback_count += 1
    return fallback_count
```

The `try/except` around the `scrape_batch(...)` call is required, not optional: `scrape_batch` can
raise `Crawl4AIUnavailableError` synchronously (before touching any URL), and that must degrade
the same way a per-URL failure would — every candidate falls back to "unavailable," keeping
Firecrawl's original content — rather than crashing `_handle_firecrawl_crawl` entirely.
(Caught during this design's self-review: an earlier draft omitted this and would have regressed
`test_firecrawl_crawl_does_not_claim_fallback_used_when_unavailable`.)

Confirmed the per-page `note` string returned by today's loop is already discarded by
`_handle_firecrawl_crawl` (only `used_fallback`/count is used) — so nothing is lost by the batch
version not threading per-page notes through.

### 3. `claude_tools.py` — search path

New module-level constant `_MAX_CONCURRENT_FALLBACKS = 5` (Firecrawl's own `search()` `limit` is
already clamped to `[1, 10]`, so this bounds worst-case simultaneous browser launches to half that
ceiling). `_handle_firecrawl_search`'s sequential loop:

```python
for i, r in enumerate(results, 1):
    md, note, _ = self._scrape_with_fallback(r.get("url", ""), r.get("markdown", ""), r.get("metadata"))
    ...
```

becomes a bounded-concurrency version using `ThreadPoolExecutor.map`, which preserves input order
in its results (unlike `as_completed`), so the existing output-formatting loop needs no other
change:

```python
if self._crawl4ai is None:
    self._crawl4ai = Crawl4AIScraper(self._config.crawl4ai_profiles_dir)
with ThreadPoolExecutor(max_workers=min(_MAX_CONCURRENT_FALLBACKS, len(results))) as executor:
    fallback_results = list(executor.map(
        lambda r: self._scrape_with_fallback(r.get("url", ""), r.get("markdown", ""), r.get("metadata")),
        results,
    ))
for i, (r, (md, note, _used)) in enumerate(zip(results, fallback_results), 1):
    r["markdown"] = md
    ... # rest of the existing per-result formatting, unchanged
```

`max_workers=min(...)` never hits the `ValueError: max_workers must be greater than 0` edge case
because `_handle_firecrawl_search` already early-returns (`"No results found for: {query}"`)
before this point whenever `results` is empty — `len(results) >= 1` always holds here.

Pre-initializing `self._crawl4ai` before submitting avoids two threads racing to construct it
simultaneously — harmless either way (no I/O in `Crawl4AIScraper.__init__`), but explicit is
cheaper than leaving an implicit race for a future reader to puzzle over.

`_scrape_with_fallback`'s internals (`assess_quality`, `judge_completeness_llm`,
`_validate_public_url`/`is_private_host`, and `Crawl4AIScraper.scrape` itself) involve no shared
mutable state across calls, so concurrent execution from multiple threads on the same `ClaudeToolkit`
instance is safe without further changes.

## Testing

- **3 existing tests need updating** (all in `tests/claude_tools/test_web_scraping.py`, all
  currently mocking `Crawl4AIScraper.scrape`, all need to mock `.scrape_batch` instead, returning a
  `dict[url, outcome]`):
  - `test_firecrawl_crawl_applies_fallback_per_page`
  - `test_firecrawl_crawl_never_fetches_blocked_subpage_url_via_crawl4ai`
  - `test_firecrawl_crawl_does_not_claim_fallback_used_when_unavailable` — this one specifically
    exercises the fixed try/except-around-`scrape_batch` gap above; must mock
    `.scrape_batch.side_effect = Crawl4AIUnavailableError(...)` and confirm the crawl still
    completes with the original content, not an unhandled exception.
- All other existing tests (single-URL `Crawl4AIScraper` tests in `test_scrape_fallback.py`,
  `_scrape_with_fallback`-level tests, search-path tests) need zero changes — verified their exact
  assertions trace correctly through the refactored code above.
- **New tests:**
  - `scrape_batch` launches exactly one `AsyncWebCrawler` for N URLs (assert construction count via
    a fake `AsyncWebCrawler.__init__` call counter, extending the existing
    `_install_fake_crawl4ai` test helper).
  - One URL's exception inside a `scrape_batch` call doesn't prevent the other URLs in the same
    batch from succeeding (fake crawler's `arun` raises for one URL, returns normally for others).
  - `scrape()` still produces identical `BrowserConfig`/hook/result behavior post-refactor (reuse
    of existing single-URL test assertions is sufficient; no new test needed beyond confirming the
    existing 5 pass unmodified).
  - Search-path: results stay in input order in the final formatted output despite concurrent
    execution (e.g. 3 results where the 2nd's fallback fetch is artificially slower than the
    1st/3rd's, assert output order is still 1, 2, 3).
