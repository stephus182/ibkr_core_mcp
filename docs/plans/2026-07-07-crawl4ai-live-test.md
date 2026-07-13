# Crawl4AI Live Fallback Test — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove the Crawl4AI fallback (`ibkr_core_mcp/scrape_fallback.py`) actually works against a real Playwright-driven Chromium browser, not just mocked unit tests — both the happy path (real page scrape) and the SSRF pre-check that must hold with or without Crawl4AI installed.

**Architecture:** New live-test file `tests/test_crawl4ai_live.py`, following the repo's `test_*_live.py` convention (`tests/test_client_live.py`, `tests/test_web_scraper_live.py`): module-scoped skip fixture when the optional `crawl4ai` dependency isn't importable, `@pytest.mark.integration` marker, real network/browser calls, no mocking of `crawl4ai` itself. Targets `https://example.com` — a static, stable, zero-risk page — for the real-scrape assertions, so the suite is deterministic and repeatable rather than dependent on some arbitrary site's uptime/content.

**Tech Stack:** `crawl4ai>=0.5.0` (Playwright/Chromium under the hood), pytest, the existing `ClaudeToolkit._scrape_with_fallback` / `Crawl4AIScraper` code (no production code changes in this plan — `scrape_fallback.py` and `claude_tools.py` are already correct per the existing mocked test suite in `tests/test_scrape_fallback.py`).

---

## File Structure

- Create: `tests/test_crawl4ai_live.py` — the new live test file (fixtures + 3 tests)
- No production code changes — this plan only adds a live-test layer on top of the already-implemented, already-unit-tested fallback (see `docs/claude-tools-audit-2026-07.md`'s crawl4ai-fallback history and `tests/test_scrape_fallback.py`'s 40+ mocked tests).

---

### Task 1: Write the crawl4ai-availability skip fixture and the first real-scrape test

**Files:**
- Create: `tests/test_crawl4ai_live.py`

- [ ] **Step 1: Write the test file**

```python
"""Live integration tests for the real Crawl4AI fallback (Playwright-driven).

Unlike tests/test_web_scraper_live.py (Firecrawl only, no crawl4ai) and
tests/test_scrape_fallback.py (crawl4ai fully mocked), these tests require
the optional `crawl4ai` dependency actually installed with its browser
downloaded:
    pip install "ibkr_core_mcp[scraper]"
    crawl4ai-setup

All tests requiring a real browser skip automatically if `crawl4ai` isn't
importable. The SSRF pre-check test does NOT require crawl4ai — it must
hold regardless of whether the optional dependency is installed.

Run:
    pytest tests/test_crawl4ai_live.py -v -m integration
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture(scope="module")
def crawl4ai_available():
    try:
        import crawl4ai  # noqa: F401
    except ImportError:
        pytest.skip(
            "crawl4ai not installed — run `pip install ibkr_core_mcp[scraper]` "
            "then `crawl4ai-setup`"
        )


@pytest.fixture()
def toolkit(tmp_path):
    from ibkr_core_mcp.claude_tools import ClaudeToolkit
    from ibkr_core_mcp.config import Config

    config = Config(
        gateway_url="https://localhost:5055/v1/api",
        anthropic_api_key="test-key",
        gdrive_folder_id="",
        sqlite_path=tmp_path / "store.db",
        gdrive_token_file=tmp_path / "token.json",
        gdrive_credentials_file=tmp_path / "credentials.json",
        crawl4ai_profiles_dir=tmp_path / "crawl4ai_profiles",
    )
    return ClaudeToolkit(MagicMock(), MagicMock(), MagicMock(), config)


@pytest.mark.integration
def test_crawl4ai_scraper_real_browser_scrape(crawl4ai_available, tmp_path):
    """Direct Crawl4AIScraper.scrape() against a real, stable, static page —
    proves the real Playwright/Chromium round-trip works end to end."""
    from ibkr_core_mcp.scrape_fallback import Crawl4AIScraper

    scraper = Crawl4AIScraper(tmp_path / "profiles")
    result = scraper.scrape("https://example.com")

    assert result["url"] == "https://example.com"
    assert "Example Domain" in result["markdown"]
```

- [ ] **Step 2: Run it to confirm it SKIPS (crawl4ai not yet installed)**

Run: `pytest tests/test_crawl4ai_live.py -v -m integration`
Expected: `1 skipped` — reason `"crawl4ai not installed — run ..."`. This confirms the skip fixture itself works before we make the real dependency available.

- [ ] **Step 3: Commit**

```bash
git add tests/test_crawl4ai_live.py
git commit -m "test: add crawl4ai live-test skeleton (skips until crawl4ai is installed)"
```

---

### Task 2: Install crawl4ai and its browser, confirm the real scrape passes

**Files:** none (environment only)

- [ ] **Step 1: Install the optional scraper extra**

Run: `cd /path/to/ibkr_core_mcp && source .venv/bin/activate && pip install -e ".[scraper]"`
Expected: `crawl4ai>=0.5.0` and its transitive deps (including `playwright`) install successfully.

- [ ] **Step 2: Download the Playwright browser crawl4ai needs**

Run: `crawl4ai-setup`
Expected: completes without error (this is the one-time post-install step documented in CLAUDE.md's Web Scraping reference table). If it reports Chromium already present (there is already a cached Chromium under `~/Library/Caches/ms-playwright` from another project), that's fine — `crawl4ai-setup` verifies/repairs its own expected browser version rather than blindly re-downloading.

- [ ] **Step 3: Verify the import chain crawl4ai_available checks for**

Run: `python -c "from crawl4ai import AsyncWebCrawler, BrowserConfig, BrowserProfiler; print('ok')"`
Expected: prints `ok`

- [ ] **Step 4: Re-run the live test — now it should actually launch a browser**

Run: `pytest tests/test_crawl4ai_live.py -v -m integration`
Expected: `test_crawl4ai_scraper_real_browser_scrape PASSED` (takes a few seconds — real Chromium launch + page load)

- [ ] **Step 5: Commit**

There's no code change in this task (environment setup only) — nothing to commit. Proceed to Task 3.

---

### Task 3: Add the deterministic fallback-wiring test (forces the real fallback path)

Real Firecrawl results are not deterministically bad/incomplete, so we can't
reliably script "Firecrawl fails on page X, triggering the fallback" against
a live target. Instead, force `assess_quality()`'s "fallback" verdict
directly by feeding `_scrape_with_fallback` an empty markdown string for a
real URL — this exercises the exact same code path
(`ClaudeToolkit._scrape_with_fallback` → `Crawl4AIScraper.scrape`) with a
real browser, without depending on Firecrawl's live behavior.

**Files:**
- Modify: `tests/test_crawl4ai_live.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_crawl4ai_live.py`:

```python
@pytest.mark.integration
def test_scrape_with_fallback_triggers_real_crawl4ai_on_empty_firecrawl_result(
    crawl4ai_available, toolkit
):
    """Empty Firecrawl markdown makes assess_quality() return "fallback",
    which skips the LLM judge entirely and routes straight to the real
    Crawl4AIScraper — proving the full wiring, not just the isolated unit."""
    markdown, note = toolkit._scrape_with_fallback("https://example.com", "", {})

    assert "Example Domain" in markdown
    assert "Crawl4AI fallback" in note
```

- [ ] **Step 2: Run it to confirm it passes**

Run: `pytest tests/test_crawl4ai_live.py -v -m integration -k real_crawl4ai_on_empty`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_crawl4ai_live.py
git commit -m "test: prove real Crawl4AI fallback wiring via forced-empty-markdown case"
```

---

### Task 4: Add the SSRF pre-check test (must hold with or without crawl4ai)

**Files:**
- Modify: `tests/test_crawl4ai_live.py`

- [ ] **Step 1: Write the test (no `crawl4ai_available` dependency — runs even without the optional install)**

Append to `tests/test_crawl4ai_live.py`:

```python
@pytest.mark.integration
def test_scrape_with_fallback_blocks_private_host_before_any_browser_launch(toolkit):
    """The Python-level SSRF guard (_validate_public_url) must reject a
    private-host URL before Crawl4AI is even imported — this must hold
    whether or not the optional `crawl4ai` dependency is installed, so this
    test intentionally does not depend on the crawl4ai_available fixture."""
    markdown, note = toolkit._scrape_with_fallback("http://127.0.0.1:9/", "", {})

    assert markdown == ""
    assert "Blocked" in note
```

- [ ] **Step 2: Run it to confirm it passes**

Run: `pytest tests/test_crawl4ai_live.py -v -m integration -k blocks_private_host`
Expected: PASS (fast — no browser launched)

- [ ] **Step 3: Commit**

```bash
git add tests/test_crawl4ai_live.py
git commit -m "test: verify SSRF guard blocks private hosts independent of crawl4ai install state"
```

---

### Task 5: Full-suite sanity check

**Files:** none

- [ ] **Step 1: Run the new file standalone with real crawl4ai installed**

Run: `pytest tests/test_crawl4ai_live.py -v -m integration`
Expected: `3 passed`

- [ ] **Step 2: Run the full non-integration suite to confirm nothing else broke**

Run: `pytest -q -m "not integration"`
Expected: same pass count as before this plan (652 at time of writing) plus any new non-integration tests — no regressions. The 3 new tests are `@pytest.mark.integration` so they're excluded from this run; that's expected.

- [ ] **Step 3: ruff + mypy**

Run: `ruff check tests/test_crawl4ai_live.py`
Expected: `All checks passed!`

Run: `mypy ibkr_core_mcp` (tests/ is intentionally excluded from CI's mypy scope per `.github/workflows/ci.yml` — see the existing `test_alerts_live.py`/`test_client_live.py` pattern, which have the same untyped-def style)
Expected: `Success: no issues found`

---

## Self-Review Notes

- **Spec coverage:** "test crawl4ai fallback" → Tasks 1–3. "live test crawl4ai works" → Tasks 1–2 (real browser scrape) and Task 5 (full-suite confirmation). SSRF (a natural companion given the fallback's two-layer design) → Task 4, included since it's the other half of "does the fallback actually work safely."
- **No placeholders:** every step has real, complete code or an exact command with expected output.
- **Type consistency:** `Crawl4AIScraper(profiles_dir)` and `ClaudeToolkit._scrape_with_fallback(url, markdown, metadata)` signatures match `ibkr_core_mcp/scrape_fallback.py` and `ibkr_core_mcp/claude_tools.py` as they exist today (verified 2026-07-07, post register-item-15 consolidation commit `54e8513`).
