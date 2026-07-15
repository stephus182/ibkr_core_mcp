# Crawl4AI Fallback Browser Reuse + Concurrency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop `firecrawl_crawl` from launching one Chromium process per fallback-needing page (reuse one browser per crawl call instead), and stop `firecrawl_search` from fetching fallbacks strictly sequentially (bound concurrency instead, since search results are different domains and can't share a browser the way crawl pages can).

**Architecture:** `Crawl4AIScraper.scrape_batch(urls, profile_domain)` opens one browser and sequentially `arun()`s every URL within it; `scrape()` becomes a 1-URL delegation to it. `claude_tools.py`'s `_scrape_with_fallback` splits into `_assess_fallback_need` (decide) + `_finalize_fallback_result` (turn an outcome into the final tuple), shared by both the new batched crawl path (`_apply_crawl4ai_fallback_batch`) and a bounded `ThreadPoolExecutor` in the search path.

**Tech Stack:** Python stdlib `concurrent.futures.ThreadPoolExecutor`, existing `crawl4ai`/Playwright integration (unchanged internals), `pytest` + `unittest.mock`.

**Design doc:** `docs/plans/2026-07-15-crawl4ai-fallback-browser-reuse-design.md` — read this first if anything below is ambiguous; this plan implements it exactly, no scope changes.

---

### Task 1: `Crawl4AIScraper.scrape_batch()` + `scrape()` delegation

**Files:**
- Modify: `ibkr_core_mcp/scrape_fallback.py:362-418` (the whole current `scrape()` method)
- Test: `tests/test_scrape_fallback.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_scrape_fallback.py` (after the existing `_install_fake_crawl4ai` helper and its tests, e.g. right after `test_crawl4ai_scraper_installs_ssrf_request_guard_hook`'s block ends around line 493):

```python
def _install_fake_crawl4ai_tracking(monkeypatch, markdown_by_url=None, fail_urls=frozenset()):
    """Separate fake-crawl4ai installer used only by scrape_batch tests below:
    tracks how many AsyncWebCrawler instances get constructed (proving reuse
    across multiple arun() calls within one scrape_batch() call) and which
    URLs were actually passed to arun(), in call order. Kept independent from
    _install_fake_crawl4ai above rather than changing that helper's return
    shape, since 5 existing tests depend on its exact 2-tuple return.
    """
    construction_count = {"value": 0}
    arun_urls: list[str] = []

    class FakeCrawlerStrategy:
        def set_hook(self, hook_type, hook):
            pass

    class FakeAsyncWebCrawler:
        def __init__(self, config=None):
            self.config = config
            self.crawler_strategy = FakeCrawlerStrategy()
            construction_count["value"] += 1

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def arun(self, url):
            arun_urls.append(url)
            if url in fail_urls:
                raise RuntimeError("fake crawl4ai failure")
            content = (markdown_by_url or {}).get(url, f"content for {url}")
            return _FakeCrawlResult(content)

    class FakeBrowserConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    fake_module = types.ModuleType("crawl4ai")
    fake_module.AsyncWebCrawler = FakeAsyncWebCrawler
    fake_module.BrowserConfig = FakeBrowserConfig
    monkeypatch.setitem(sys.modules, "crawl4ai", fake_module)
    return construction_count, arun_urls


def test_scrape_batch_reuses_one_browser_across_all_urls(monkeypatch, tmp_path):
    from ibkr_core_mcp.scrape_fallback import Crawl4AIScraper
    construction_count, arun_urls = _install_fake_crawl4ai_tracking(monkeypatch)

    scraper = Crawl4AIScraper(tmp_path)
    urls = ["https://example.com/a", "https://example.com/b", "https://example.com/c"]
    outcomes = scraper.scrape_batch(urls, profile_domain="https://example.com")

    assert construction_count["value"] == 1
    assert arun_urls == urls
    for url in urls:
        assert outcomes[url] == {"url": url, "markdown": f"content for {url}"}


def test_scrape_batch_isolates_one_url_failure_from_the_rest(monkeypatch, tmp_path):
    from ibkr_core_mcp.scrape_fallback import Crawl4AIScraper
    construction_count, _arun_urls = _install_fake_crawl4ai_tracking(
        monkeypatch, fail_urls=frozenset({"https://example.com/b"})
    )

    scraper = Crawl4AIScraper(tmp_path)
    urls = ["https://example.com/a", "https://example.com/b", "https://example.com/c"]
    outcomes = scraper.scrape_batch(urls, profile_domain="https://example.com")

    assert construction_count["value"] == 1  # browser stayed open despite the failure
    assert outcomes["https://example.com/a"] == {
        "url": "https://example.com/a", "markdown": "content for https://example.com/a",
    }
    assert isinstance(outcomes["https://example.com/b"], RuntimeError)
    assert outcomes["https://example.com/c"] == {
        "url": "https://example.com/c", "markdown": "content for https://example.com/c",
    }


def test_scrape_batch_empty_urls_returns_empty_dict_without_importing_crawl4ai(tmp_path):
    from ibkr_core_mcp.scrape_fallback import Crawl4AIScraper
    scraper = Crawl4AIScraper(tmp_path)
    assert scraper.scrape_batch([], profile_domain="https://example.com") == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_scrape_fallback.py -k scrape_batch -v`
Expected: FAIL — `AttributeError: 'Crawl4AIScraper' object has no attribute 'scrape_batch'` (method doesn't exist yet).

- [ ] **Step 3: Replace `scrape()` with `scrape_batch()` + a thin `scrape()` delegation**

In `ibkr_core_mcp/scrape_fallback.py`, replace the entire current `scrape()` method (starts at `def scrape(self, url: str) -> dict[str, str]:`, ends right before the blank lines preceding `def create_profile`) with:

```python
    def scrape_batch(
        self, urls: list[str], profile_domain: str
    ) -> dict[str, dict[str, str] | Exception]:
        """
        Scrape multiple URLs using ONE shared Crawl4AI browser session instead
        of launching a fresh Chromium per URL.

        Safe only when every URL in `urls` shares the same saved-profile
        decision -- true for pages within a single Firecrawl crawl() call,
        since Firecrawl's crawl() only returns pages within the same site as
        its root URL. Callers pass that root's domain as `profile_domain`,
        not each individual page's own domain.

        Installs the same Playwright-level SSRF guard (_reject_private_requests)
        as scrape() used to, once per session rather than once per URL -- it
        re-checks every request (navigation, redirects, subresources) the
        shared browser makes across the whole batch.

        Args:
            urls: URLs to fetch. Empty list returns {} without importing
                crawl4ai or launching a browser.
            profile_domain: Domain used to decide whether a saved login
                profile applies (profiles_dir/profile_domain). Pass the
                crawl's root domain -- all pages in one crawl share this
                decision by construction (see above).

        Returns:
            Dict keyed by each input URL. Each value is either a
            {"url": ..., "markdown": ...} result dict (same shape scrape()
            returns) or the Exception raised while fetching that specific
            URL -- one URL failing does not abort the rest of the batch or
            close the shared browser early.

        Raises:
            Crawl4AIUnavailableError: If `crawl4ai` is not installed. Raised
                before the browser is launched, before any URL is attempted --
                an install-time problem, not a per-URL one. Callers that want
                per-page graceful degradation (rather than the whole batch
                failing) must catch this around the scrape_batch() call
                itself, not expect it inside the returned dict.
        """
        if not urls:
            return {}

        try:
            from crawl4ai import AsyncWebCrawler, BrowserConfig
        except ImportError as exc:
            raise Crawl4AIUnavailableError(
                "Crawl4AI is not installed. Install with "
                "`pip install ibkr_core_mcp[scraper]` and then run `crawl4ai-setup`."
            ) from exc

        domain = _safe_domain(profile_domain)
        profile_dir = self._profiles_dir / domain
        if profile_dir.is_dir():
            browser_config = BrowserConfig(
                headless=True,
                use_managed_browser=True,
                user_data_dir=str(profile_dir),
            )
        else:
            browser_config = BrowserConfig(headless=True)

        async def _scrape_all() -> dict[str, dict[str, str] | Exception]:
            outcomes: dict[str, dict[str, str] | Exception] = {}
            async with AsyncWebCrawler(config=browser_config) as crawler:
                crawler.crawler_strategy.set_hook(
                    "on_page_context_created", _install_ssrf_guard
                )
                for u in urls:
                    try:
                        result = await crawler.arun(url=u)
                        markdown = result.markdown.raw_markdown if result.markdown else ""
                        outcomes[u] = {"url": u, "markdown": markdown}
                    except Exception as exc:
                        # Isolate one URL's failure from the rest of the batch --
                        # the caller inspects each outcome's type to decide how
                        # to degrade, matching scrape()'s single-URL contract.
                        outcomes[u] = exc
            return outcomes

        return _run_async(_scrape_all())  # type: ignore[no-any-return]

    def scrape(self, url: str) -> dict[str, str]:
        """
        Scrape a single URL with Crawl4AI.

        A 1-URL call to scrape_batch() -- see that method's docstring for the
        full behavior (browser lifecycle, SSRF guard, profile resolution).
        This method exists for callers that only ever need one URL at a time
        (e.g. the search-result fallback path, where each result is typically
        a different domain and batching wouldn't be valid anyway).

        Args:
            url: The URL to fetch.

        Returns:
            {"url": url, "markdown": <raw_markdown or "" if the page had none>}

        Raises:
            Crawl4AIUnavailableError: If `crawl4ai` is not installed.
            Exception: Whatever scrape_batch() caught for this URL specifically
                (e.g. a Playwright navigation error) is re-raised here, since a
                single-URL caller expects scrape() to either return or raise,
                not receive an outcome dict.
        """
        outcome = self.scrape_batch([url], profile_domain=url)[url]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome
```

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `pytest tests/test_scrape_fallback.py -k scrape_batch -v`
Expected: PASS — all 3 new tests green.

- [ ] **Step 5: Run the whole scrape_fallback test file to confirm no regressions**

Run: `pytest tests/test_scrape_fallback.py -v`
Expected: PASS — all tests including the 5 pre-existing `Crawl4AIScraper`-level tests
(`test_crawl4ai_scraper_raises_when_not_installed`, `test_crawl4ai_scraper_returns_markdown_and_url`,
`test_crawl4ai_scraper_uses_saved_profile_when_present`, `test_crawl4ai_scraper_no_profile_when_absent`,
`test_crawl4ai_scraper_installs_ssrf_request_guard_hook`), since `scrape()` still builds the exact
same `BrowserConfig`/hook/result shape via its delegation to `scrape_batch()`.

- [ ] **Step 6: Commit**

```bash
git add ibkr_core_mcp/scrape_fallback.py tests/test_scrape_fallback.py
git commit -m "$(cat <<'EOF'
feat: Crawl4AIScraper.scrape_batch() -- one browser for many URLs

Adds scrape_batch(urls, profile_domain), which launches ONE Chromium
session and sequentially arun()s every URL within it, isolating each
URL's failure from the rest. scrape() is rewritten as a 1-URL
delegation to it, removing the previously-duplicated browser-config-
building logic between the two methods.

Design: docs/plans/2026-07-15-crawl4ai-fallback-browser-reuse-design.md

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Split `_scrape_with_fallback` into `_assess_fallback_need` / `_finalize_fallback_result`

This is a pure refactor -- no new tests. Verification is that every existing test touching
`_scrape_with_fallback` still passes unchanged.

**Files:**
- Modify: `ibkr_core_mcp/claude_tools.py:2571-2665` (the whole current `_scrape_with_fallback` method)

- [ ] **Step 1: Replace `_scrape_with_fallback` with the three-method split**

In `ibkr_core_mcp/claude_tools.py`, replace the entire current `_scrape_with_fallback` method
(starts at `def _scrape_with_fallback(`, ends right before `def _handle_firecrawl_search`) with:

```python
    def _assess_fallback_need(
        self, url: str, markdown: str, metadata: dict[str, Any] | None
    ) -> tuple[bool, str, str]:
        """
        Decide whether `url` needs a Crawl4AI fallback fetch, without
        performing it -- the "decide" half of _scrape_with_fallback, split out
        so the crawl-path batch loop (_apply_crawl4ai_fallback_batch) can
        classify every page up front before opening a single shared browser.

        assess_quality decides "ok" / "ambiguous" / "fallback" from Firecrawl's
        own signals plus cheap heuristics. "ambiguous" results get one extra
        Claude call (judge_completeness_llm) before deciding whether to fall
        back -- this keeps the common case (clean results) free of any extra
        API call. A transient judge failure fails safe (keeps Firecrawl's
        content) rather than escalating to the slower Crawl4AI path.

        Args:
            url: Source URL for this result/page. Validated against
                 _validate_public_url as the last check before returning
                 needs_fallback=True -- this can't be skipped even though
                 firecrawl_crawl already validates its own root URL, since
                 this url may be a Firecrawl-discovered sub-page or search
                 result rather than the one the caller explicitly validated.
            markdown: Firecrawl's markdown for this result/page (may be empty).
            metadata: Firecrawl's per-result/per-page "metadata" dict, or None.

        Returns:
            (needs_fallback, markdown_if_not_needed, note_if_not_needed). When
            needs_fallback is True, the other two fields are "" -- the caller
            is responsible for actually fetching (via Crawl4AIScraper) and
            turning the outcome into a final result via
            _finalize_fallback_result. When needs_fallback is False, the
            caller should use markdown_if_not_needed/note_if_not_needed
            directly and must not call Crawl4AI at all for this URL.
        """
        from ibkr_core_mcp.scrape_fallback import assess_quality, judge_completeness_llm

        quality = assess_quality(markdown, metadata, url)
        if quality == "ok":
            return False, markdown, ""

        if quality == "ambiguous":
            try:
                if judge_completeness_llm(self._config, url, markdown):
                    return False, markdown, ""
            except Exception as exc:
                log.warning("judge_completeness_llm failed for %s: %s", url, exc)
                return (
                    False,
                    markdown,
                    "(Note: completeness check failed — showing Firecrawl's result as-is)",
                )

        blocked = self._validate_public_url(url)
        if blocked:
            return False, markdown, f"(Crawl4AI fallback skipped: {blocked})"

        return True, "", ""

    def _finalize_fallback_result(
        self, url: str, original_markdown: str, outcome: dict[str, str] | Exception
    ) -> tuple[str, str, bool]:
        """
        Turn a Crawl4AI fetch outcome into (final_markdown, note, used_fallback)
        -- the "after the fetch" half of _scrape_with_fallback, split out so
        both the single-URL path (_scrape_with_fallback) and the batch path
        (_apply_crawl4ai_fallback_batch, via Crawl4AIScraper.scrape_batch) can
        share the exact same note wording and exception-type handling.

        Args:
            url: The URL that was fetched (used only to compute the
                 saved-profile note below).
            original_markdown: Firecrawl's original markdown for this URL,
                 used as the fallback value whenever Crawl4AI's outcome isn't
                 usable.
            outcome: Either the successful {"url": ..., "markdown": ...}
                 result dict Crawl4AIScraper.scrape()/scrape_batch() produce,
                 or the Exception that was raised/collected while fetching
                 this URL.

        Returns:
            (final_markdown, note, used_fallback) -- used_fallback is True
            only when Crawl4AI's content actually replaced Firecrawl's.
        """
        import urllib.parse

        from ibkr_core_mcp.scrape_fallback import Crawl4AIUnavailableError

        if isinstance(outcome, Crawl4AIUnavailableError):
            return original_markdown, f"(Crawl4AI fallback unavailable: {outcome})", False
        if isinstance(outcome, Exception):
            log.warning("Crawl4AI fallback failed for %s: %s", url, outcome)
            return (
                original_markdown,
                "(Crawl4AI fallback failed — showing Firecrawl's partial result)",
                False,
            )

        fallback_markdown = outcome.get("markdown", "")
        if not fallback_markdown:
            return (
                original_markdown,
                "(Crawl4AI fallback returned no content — showing Firecrawl's partial result)",
                False,
            )

        domain = urllib.parse.urlparse(url).hostname or ""
        profile_dir = self._config.crawl4ai_profiles_dir / domain
        if profile_dir.is_dir():
            note = "(fetched via Crawl4AI fallback using a saved login profile)"
        else:
            note = (
                f"(fetched via Crawl4AI fallback — no saved login profile for {domain}; "
                f"if this is a paywalled site you subscribe to, run "
                f"`python -m ibkr_core_mcp.scrape_fallback create-profile {domain}` once)"
            )
        return fallback_markdown, note, True

    def _scrape_with_fallback(
        self, url: str, markdown: str, metadata: dict[str, Any] | None
    ) -> tuple[str, str, bool]:
        """
        Return (final_markdown, note, used_fallback) for a single Firecrawl
        result/page, falling back to Crawl4AI when Firecrawl's content looks
        incomplete (blocked, empty, or paywalled).

        Composes _assess_fallback_need (decide) and _finalize_fallback_result
        (turn a fetch outcome into the final tuple) around a single
        Crawl4AIScraper.scrape() call. Used directly by the search path
        (_handle_firecrawl_search), where each result is typically a
        different domain, so batching across results isn't valid -- see
        _apply_crawl4ai_fallback_batch for the crawl path's batched
        equivalent.

        Args:
            url: Source URL for this result/page.
            markdown: Firecrawl's markdown for this result/page (may be empty).
            metadata: Firecrawl's per-result/per-page "metadata" dict, or None.

        Returns:
            (final_markdown, note, used_fallback) -- see _finalize_fallback_result.
        """
        from ibkr_core_mcp.scrape_fallback import Crawl4AIScraper

        needs_fallback, md_if_not, note_if_not = self._assess_fallback_need(
            url, markdown, metadata
        )
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

- [ ] **Step 2: Run every existing test that touches `_scrape_with_fallback`**

Run: `pytest tests/claude_tools/test_web_scraping.py -v`
Expected: PASS -- every test in this file must still pass unmodified at this point (this task
changes `_scrape_with_fallback`'s internals only, not its signature or observable behavior; the
crawl-path tests that need updating for `scrape_batch` are handled in Task 3, not here).

- [ ] **Step 3: Commit**

```bash
git add ibkr_core_mcp/claude_tools.py
git commit -m "$(cat <<'EOF'
refactor: split _scrape_with_fallback into assess/finalize halves

Pure refactor, no behavior change -- _scrape_with_fallback now composes
_assess_fallback_need (classify, no fetch) and _finalize_fallback_result
(turn a fetch outcome into the final tuple) around a single scrape()
call. Prepares for the crawl-path batch loop (next commit), which needs
to run the "assess" half over every page before opening one shared
browser, then the "finalize" half per page against that batch's
outcomes.

Design: docs/plans/2026-07-15-crawl4ai-fallback-browser-reuse-design.md

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Batch the crawl path

**Files:**
- Modify: `ibkr_core_mcp/claude_tools.py` (add `_apply_crawl4ai_fallback_batch`, rewire `_handle_firecrawl_crawl`'s loop)
- Test: `tests/claude_tools/test_web_scraping.py` (update 3 existing tests)

- [ ] **Step 1: Add `_apply_crawl4ai_fallback_batch`**

In `ibkr_core_mcp/claude_tools.py`, insert this new method immediately after `_scrape_with_fallback`
(i.e. right before `def _handle_firecrawl_search`):

```python
    def _apply_crawl4ai_fallback_batch(
        self, root_url: str, pages: list[dict[str, Any]]
    ) -> int:
        """
        Apply Crawl4AI fallback to every page in `pages` that needs it,
        mutating each page's "markdown" key in place. Used only by
        _handle_firecrawl_crawl.

        Batches every fallback-needing page into ONE
        Crawl4AIScraper.scrape_batch() call (one shared browser) instead of
        one browser launch per page -- safe because Firecrawl's crawl() only
        returns pages within the same site as root_url, so every page here
        shares the same saved-profile decision.

        Args:
            root_url: The crawl's original root URL -- used only to determine
                the shared profile domain passed to scrape_batch().
            pages: Firecrawl's page list for this crawl (each a dict with at
                least "url", "markdown", "metadata" keys).

        Returns:
            Count of pages where Crawl4AI's content actually replaced
            Firecrawl's (mirrors _scrape_with_fallback's used_fallback,
            summed across pages).
        """
        import urllib.parse

        from ibkr_core_mcp.scrape_fallback import Crawl4AIScraper

        candidates: list[tuple[dict[str, Any], str]] = []
        for page in pages:
            url = page.get("url", "")
            needs_fallback, md_if_not, _note_if_not = self._assess_fallback_need(
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
            # A whole-batch failure (e.g. Crawl4AIUnavailableError, raised
            # before any URL is attempted) must degrade the same way a
            # per-URL failure would -- not crash the entire crawl.
            outcomes = {u: exc for u in urls}

        fallback_count = 0
        for page, original_markdown in candidates:
            url = page.get("url", "")
            outcome = outcomes.get(
                url, RuntimeError(f"Crawl4AI batch returned no result for {url}")
            )
            final_markdown, _note, used_fallback = self._finalize_fallback_result(
                url, original_markdown, outcome
            )
            page["markdown"] = final_markdown
            if used_fallback:
                fallback_count += 1
        return fallback_count
```

- [ ] **Step 2: Rewire `_handle_firecrawl_crawl`'s loop**

In `_handle_firecrawl_crawl`, replace this block:

```python
        # NOTE: each fallback call here launches its own Crawl4AI browser process
        # (Crawl4AIScraper.scrape has no connection/browser reuse across calls) and
        # runs sequentially. A crawl with many blocked/paywalled pages will pay
        # Chromium startup cost per page and can push total tool latency well past
        # Firecrawl's own timeout_s budget. Acceptable for now (fallback only fires
        # on already-incomplete pages, typically a minority) — worth revisiting with
        # a shared crawler instance or a fallback page cap if that stops holding.
        fallback_count = 0
        for page in pages:
            md, note, used_fallback = self._scrape_with_fallback(
                page.get("url", ""), page.get("markdown", ""), page.get("metadata")
            )
            page["markdown"] = md
            if used_fallback:
                fallback_count += 1
```

with:

```python
        # Every fallback-needing page in this crawl shares one Crawl4AI
        # browser session instead of one launch per page -- see
        # _apply_crawl4ai_fallback_batch's docstring for why this is safe
        # (Firecrawl's crawl() stays within one site, so every page here
        # shares the same saved-profile decision).
        fallback_count = self._apply_crawl4ai_fallback_batch(url, pages)
```

- [ ] **Step 3: Update the 3 existing tests that mock `.scrape` for the crawl path**

In `tests/claude_tools/test_web_scraping.py`:

In `test_firecrawl_crawl_applies_fallback_per_page`, replace:

```python
    mock_c4a_cls.return_value.scrape.return_value = {
        "url": "https://example.com/blocked",
        "markdown": "recovered page content",
    }
```

with:

```python
    mock_c4a_cls.return_value.scrape_batch.return_value = {
        "https://example.com/blocked": {
            "url": "https://example.com/blocked",
            "markdown": "recovered page content",
        },
    }
```

In `test_firecrawl_crawl_does_not_claim_fallback_used_when_unavailable`, replace:

```python
    mock_c4a_cls.return_value.scrape.side_effect = Crawl4AIUnavailableError(
        "Crawl4AI is not installed. Install with `pip install ibkr_core_mcp[scraper]`."
    )
```

with:

```python
    mock_c4a_cls.return_value.scrape_batch.side_effect = Crawl4AIUnavailableError(
        "Crawl4AI is not installed. Install with `pip install ibkr_core_mcp[scraper]`."
    )
```

In `test_firecrawl_crawl_never_fetches_blocked_subpage_url_via_crawl4ai`, replace:

```python
    toolkit.execute("firecrawl_crawl", {"url": "https://example.com"})
    mock_c4a_cls.return_value.scrape.assert_not_called()
```

with:

```python
    toolkit.execute("firecrawl_crawl", {"url": "https://example.com"})
    mock_c4a_cls.return_value.scrape_batch.assert_not_called()
```

- [ ] **Step 4: Run the crawl-path tests**

Run: `pytest tests/claude_tools/test_web_scraping.py -v`
Expected: PASS -- all tests, including the 3 just updated.

- [ ] **Step 5: Commit**

```bash
git add ibkr_core_mcp/claude_tools.py tests/claude_tools/test_web_scraping.py
git commit -m "$(cat <<'EOF'
fix: firecrawl_crawl reuses one Crawl4AI browser across a whole crawl

_apply_crawl4ai_fallback_batch replaces the per-page fallback loop:
classifies every page first (no browser), then makes ONE
scrape_batch() call for every page that needs fallback, instead of one
browser launch per page. A whole-batch failure (e.g. Crawl4AI not
installed) degrades the same way a per-page failure already did,
rather than crashing the crawl -- covered by
test_firecrawl_crawl_does_not_claim_fallback_used_when_unavailable.

Design: docs/plans/2026-07-15-crawl4ai-fallback-browser-reuse-design.md

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Bounded concurrency for the search path

**Files:**
- Modify: `ibkr_core_mcp/claude_tools.py:1-7` (add `ThreadPoolExecutor` import), `:25` area (add
  `_MAX_CONCURRENT_FALLBACKS` constant), `_handle_firecrawl_search`'s loop
- Test: `tests/claude_tools/test_web_scraping.py` (append one new test)

- [ ] **Step 1: Add the `ThreadPoolExecutor` import and the concurrency constant**

At the top of `ibkr_core_mcp/claude_tools.py`, add `from concurrent.futures import ThreadPoolExecutor`
to the import block (alphabetically before `import json`):

```python
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import logging
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo
```

Right after `_ET = ZoneInfo("America/New_York")` (around line 25), add:

```python
# Bounds worst-case simultaneous Crawl4AI browser launches in the search-result
# fallback loop. FirecrawlClient.search()'s own `limit` is already clamped to
# [1, 10] (see web_scraper.py), so this caps concurrent launches to half that.
_MAX_CONCURRENT_FALLBACKS = 5
```

- [ ] **Step 2: Write the failing test**

Append to `tests/claude_tools/test_web_scraping.py`:

```python
@patch("ibkr_core_mcp.web_scraper.FirecrawlClient")
def test_firecrawl_search_preserves_result_order_under_concurrent_fallback(mock_fc_cls):
    """Concurrent fallback execution (ThreadPoolExecutor.map) must not reorder
    results in the final output, even when different results' fallback
    fetches take different amounts of time -- the first result is given the
    LONGEST artificial delay specifically to prove ordering survives even
    when completion order differs from input order."""
    import time

    toolkit = _make_toolkit()
    mock_fc = MagicMock()
    mock_fc.search.return_value = [
        {"url": "https://a.example.com", "title": "A", "markdown": "", "metadata": {"statusCode": 403}},
        {"url": "https://b.example.com", "title": "B", "markdown": "", "metadata": {"statusCode": 403}},
        {"url": "https://c.example.com", "title": "C", "markdown": "", "metadata": {"statusCode": 403}},
    ]
    mock_fc_cls.return_value = mock_fc

    delays = {"https://a.example.com": 0.15, "https://b.example.com": 0.05, "https://c.example.com": 0.0}

    def fake_scrape_with_fallback(url, markdown, metadata):
        time.sleep(delays[url])
        label = url.split("//")[1].split(".")[0].upper()
        return f"recovered {label} content", "", True

    toolkit._scrape_with_fallback = fake_scrape_with_fallback  # type: ignore[method-assign]
    result, fig = toolkit.execute("firecrawl_search", {"query": "test"})

    a_pos = result.index("recovered A content")
    b_pos = result.index("recovered B content")
    c_pos = result.index("recovered C content")
    assert a_pos < b_pos < c_pos
```

- [ ] **Step 3: Run the test to verify it fails (or passes vacuously) against the current sequential code**

Run: `pytest tests/claude_tools/test_web_scraping.py -k preserves_result_order -v`
Expected: PASS already, since today's sequential loop trivially preserves order too -- this test
is a regression guard for the *upcoming* concurrency change, not a red/green signal for a bug that
exists yet. Confirm it passes now so you know it's a valid baseline before Step 4 changes the loop.

- [ ] **Step 4: Rewrite `_handle_firecrawl_search`'s loop**

In `_handle_firecrawl_search`, first add the `Crawl4AIScraper` import alongside the existing one at
the top of the method:

```python
        from ibkr_core_mcp.scrape_fallback import Crawl4AIScraper
        from ibkr_core_mcp.web_scraper import FirecrawlClient, FirecrawlError, WebDocsStore
```

Then replace this block:

```python
        lines = [f"## Search results for: {query}\n"]
        for i, r in enumerate(results, 1):
            md, note, _ = self._scrape_with_fallback(
                r.get("url", ""), r.get("markdown", ""), r.get("metadata")
            )
            r["markdown"] = md
            lines.append(f"### {i}. {r.get('title', '(no title)')}")
            lines.append(f"**URL:** {r.get('url', '')}\n")
            if md:
                lines.append(md[:2000])  # truncate very long pages
            if note:
                lines.append(note)
            lines.append("")
```

with:

```python
        # Search results are typically different domains each, so unlike the
        # crawl path's shared-browser batch, there's no valid single browser
        # config to reuse here -- instead fetch fallbacks concurrently
        # (bounded) so independent per-domain browser launches overlap
        # instead of queuing sequentially behind each other.
        if self._crawl4ai is None:
            self._crawl4ai = Crawl4AIScraper(self._config.crawl4ai_profiles_dir)
        with ThreadPoolExecutor(
            max_workers=min(_MAX_CONCURRENT_FALLBACKS, len(results))
        ) as executor:
            fallback_results = list(executor.map(
                lambda r: self._scrape_with_fallback(
                    r.get("url", ""), r.get("markdown", ""), r.get("metadata")
                ),
                results,
            ))

        lines = [f"## Search results for: {query}\n"]
        for i, (r, (md, note, _used)) in enumerate(zip(results, fallback_results), 1):
            r["markdown"] = md
            lines.append(f"### {i}. {r.get('title', '(no title)')}")
            lines.append(f"**URL:** {r.get('url', '')}\n")
            if md:
                lines.append(md[:2000])  # truncate very long pages
            if note:
                lines.append(note)
            lines.append("")
```

- [ ] **Step 5: Run the search-path tests**

Run: `pytest tests/claude_tools/test_web_scraping.py -v`
Expected: PASS -- all tests, including the new order-preservation test, now exercising the actual
concurrent path (Step 3 only established the baseline; this run proves it still holds after the
loop rewrite).

- [ ] **Step 6: Commit**

```bash
git add ibkr_core_mcp/claude_tools.py tests/claude_tools/test_web_scraping.py
git commit -m "$(cat <<'EOF'
fix: firecrawl_search fetches fallbacks concurrently, not sequentially

Search results are typically different domains, so a shared browser
(the crawl path's fix) isn't valid here -- bounded concurrency
(ThreadPoolExecutor, max 5 of Firecrawl's own 10-result cap) is the
right mechanism instead, so independent per-domain browser launches
overlap rather than queuing behind each other. ThreadPoolExecutor.map
preserves input order, so the output-formatting loop is unchanged
beyond consuming the pre-computed results list.

Design: docs/plans/2026-07-15-crawl4ai-fallback-browser-reuse-design.md

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Full-suite sanity check

**Files:** none modified -- verification only.

- [ ] **Step 1: Run the complete non-integration suite**

```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
pytest -m "not integration" -v > /tmp/full_suite_output.txt 2>&1
echo "Exit code: $?"
tail -30 /tmp/full_suite_output.txt
```

Expected: exit code 0, no failures. This confirms nothing outside `scrape_fallback.py`/
`claude_tools.py` regressed, and that all 4 new tests plus all updated tests are green together.

- [ ] **Step 2: Run mypy**

```bash
mypy ibkr_core_mcp/scrape_fallback.py ibkr_core_mcp/claude_tools.py
```

Expected: `Success: no issues found`.

- [ ] **Step 3: No commit needed** -- this task is verification-only; if either check fails,
return to the relevant earlier task and fix before considering the plan complete.

---

## Self-review notes (from plan authoring)

- **Spec coverage:** every section of the design doc (scrape_batch, scrape() delegation,
  _assess_fallback_need/_finalize_fallback_result split, _apply_crawl4ai_fallback_batch with its
  required try/except, bounded search concurrency, all 4 new tests, all 3 test updates) maps to a
  task above.
- **No placeholders:** none introduced.
- **Type consistency:** `scrape_batch(self, urls: list[str], profile_domain: str) -> dict[str, dict[str, str] | Exception]`
  (Task 1) matches its call sites in `scrape()` (Task 1) and `_apply_crawl4ai_fallback_batch` (Task 3)
  exactly -- same parameter names, same return shape assumed at each call site.
  `_assess_fallback_need(self, url, markdown, metadata) -> tuple[bool, str, str]` and
  `_finalize_fallback_result(self, url, original_markdown, outcome) -> tuple[str, str, bool]`
  (both defined in Task 2) are called with matching signatures from `_scrape_with_fallback` (Task 2)
  and `_apply_crawl4ai_fallback_batch` (Task 3).
