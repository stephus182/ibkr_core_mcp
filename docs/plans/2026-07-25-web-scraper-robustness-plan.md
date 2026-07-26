# Web Scraper Robustness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `firecrawl_crawl` recover from bot-blocked sites instead of silently reporting "saved 0 page(s)", and make saved login profiles work for paywalled sites whose hostname doesn't match the profile exactly.

**Architecture:** One measurement — total bytes of extracted markdown — drives a three-rung recovery ladder: Firecrawl with cheap defaults, Firecrawl with `waitFor`+`proxy`, then a local Crawl4AI scrape of the root URL. Each rung is scored with the same function and the best result wins, so the ladder can never return less than the first rung produced. No new types, no status enums.

**Tech Stack:** Python 3.11, `requests`, Firecrawl REST API v1, Crawl4AI (Playwright), pytest, ruff, mypy strict.

**Spec:** `docs/plans/2026-07-25-web-scraper-robustness-design.md`

---

## File Structure

| File | Responsibility after this plan |
|---|---|
| `ibkr_core_mcp/web_scraper.py` | Firecrawl protocol + Drive persistence. Gains the size measurement, the options builder, the timeout formula, and the two-rung escalation. Unchanged responsibility — no fallback logic enters this file. |
| `ibkr_core_mcp/scrape_fallback.py` | Crawl4AI fallback + SSRF guard. Gains flexible profile-directory resolution and a `list-profiles` CLI subcommand. |
| `ibkr_core_mcp/claude_tools.py` | Orchestration. Gains the root-URL last resort and honest result reporting; two tool schemas gain optional overrides. |
| `docs/web-scraper-reference.md` | **New.** The user-facing reference for the whole scraper. |

The layering in `web_scraper.py`'s module docstring (lines 10-12) is deliberate and must survive: **client + Drive persistence only; fallback logic in `scrape_fallback.py`; orchestration in `claude_tools.py`.** Do not import `scrape_fallback` from `web_scraper`.

---

## Conventions you must follow

- **Docstrings are lint-enforced.** `ruff`'s pydocstyle `D1xx` rules are on for `ibkr_core_mcp/`. Every new public *and* private module-level function, method, and class needs a docstring or `ruff check .` fails. Summary opens on the **first** line (`D212`), not the second.
- **`tests/` is exempt from `D`.** Test functions need no docstrings, and by established convention carry **no type annotations**. Don't add any.
- **mypy runs strict** against `ibkr_core_mcp/`. Annotate everything you add there.
- Run `ruff format .` before every commit.
- Tests mock the module's `requests` and `time` via `@patch("ibkr_core_mcp.web_scraper.requests")` / `@patch("ibkr_core_mcp.web_scraper.time")`. Keep that convention.

---

## Task 1: The size measurement

**Files:**
- Modify: `ibkr_core_mcp/web_scraper.py` (module constants near line 64; new function after `_slugify`)
- Test: `tests/test_web_scraper.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_web_scraper.py`, after the `_slugify` tests (around line 47):

```python
def test_content_bytes_sums_markdown_across_pages():
    from ibkr_core_mcp.web_scraper import content_bytes

    assert content_bytes([{"markdown": "abc"}, {"markdown": "de"}]) == 5


def test_content_bytes_treats_missing_and_none_markdown_as_zero():
    from ibkr_core_mcp.web_scraper import content_bytes

    assert content_bytes([{"markdown": None}, {}, {"markdown": ""}]) == 0


def test_content_bytes_counts_utf8_bytes_not_characters():
    from ibkr_core_mcp.web_scraper import content_bytes

    # U+00E9 is one character but two bytes in UTF-8. A page of accented text
    # must not be undercounted into a false "blocked" verdict.
    assert content_bytes([{"markdown": "é" * 10}]) == 20


def test_content_bytes_empty_list_is_zero():
    from ibkr_core_mcp.web_scraper import content_bytes

    assert content_bytes([]) == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_web_scraper.py -k content_bytes -v`
Expected: 4 FAILED with `ImportError: cannot import name 'content_bytes'`

- [ ] **Step 3: Implement**

In `ibkr_core_mcp/web_scraper.py`, add after the `_FIRECRAWL_MAX_NEXT_CHUNKS` constant (line 64):

```python
# Minimum total markdown a crawl must yield before it is treated as a success.
# Calibrated against this repo's own scrape cache (docs/audits/audit-evidence/scrapes/):
# the largest observed failure is a 152-byte Akamai edge-block page, and the smallest
# observed real documentation page is 12,933 bytes. 5 KB sits ~34x above the former
# and ~2.5x below the latter, and is set high enough to also catch partial extractions
# that returned something but plainly not a page. See
# docs/plans/2026-07-25-web-scraper-robustness-design.md section 3.1.
_MIN_USEFUL_BYTES = 5 * 1024

# Escalation options for a crawl that came back under _MIN_USEFUL_BYTES. Proven against
# interactivebrokers.com in docs/audits/audit-evidence/scrapes/manifest.json (2026-07-02):
# "retry with --wait-for 3000 --proxy auto succeeded after prior firecrawl-default and
# webfetch failures". Both are documented v1 scrapeOptions fields:
# https://docs.firecrawl.dev/v1/api-reference/endpoint/crawl-post (verified 2026-07-25).
_ESCALATION_WAIT_FOR_MS = 3000
_ESCALATION_PROXY = "auto"

# Floor for the escalated attempt's polling budget. Stealth is slower by construction —
# waitFor adds 3s per page and proxy="auto" retries a failed basic fetch through the
# enhanced proxy — so reusing a budget that just timed out would reproduce the timeout.
_ESCALATION_MIN_TIMEOUT_S = 180

# Firecrawl statuses where a stealth retry cannot help: a bad key, an empty credit
# balance, and an active rate limit are account-level, not page-level. Retrying burns
# time and money to fail identically, and in the 429 case worsens the throttling.
_NON_ESCALATING_STATUSES = frozenset({401, 402, 429})
```

Then add this module-level function immediately after `_slugify` (after line 151):

```python
def content_bytes(pages: list[dict[str, Any]]) -> int:
    """Return the total bytes of extracted markdown across a list of crawl pages.

    This is the single signal the recovery ladder branches on. The decision a caller
    actually needs is "did I get content?", which is a property of the output — not of
    how the attempt ended. Blocked, timed out, job-failed and completed-empty all
    produce the same next move, so they need no separate representation.

    Counts UTF-8 **bytes**, not characters, so a page of accented or CJK text is not
    undercounted into a false "blocked" verdict.

    Args:
        pages: Page dicts as returned by `FirecrawlClient.crawl()`. A missing or None
            "markdown" key contributes zero rather than raising, since Firecrawl returns
            both shapes for pages it failed to extract.

    Returns:
        Total markdown size in bytes; 0 for an empty list.
    """
    return sum(len((page.get("markdown") or "").encode("utf-8")) for page in pages)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_web_scraper.py -k content_bytes -v`
Expected: 4 passed

- [ ] **Step 5: Lint, type-check, commit**

```bash
ruff format . && ruff check . && mypy
git add ibkr_core_mcp/web_scraper.py tests/test_web_scraper.py
git commit -m "feat(scraper): add content_bytes measurement and escalation constants

The single signal the recovery ladder branches on. Threshold calibrated
against docs/audits/audit-evidence/scrapes/ rather than guessed: largest
observed failure 152 B, smallest observed real page 12,933 B."
```

---

## Task 2: The shared scrapeOptions builder

**Files:**
- Modify: `ibkr_core_mcp/web_scraper.py` — new `_scrape_options` method on `FirecrawlClient`; `search()` at lines 201-252
- Test: `tests/test_web_scraper.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_web_scraper.py` after `test_search_limit_clamped_to_10`:

```python
def test_scrape_options_default_is_todays_request_body():
    from ibkr_core_mcp.web_scraper import FirecrawlClient

    client = FirecrawlClient("fc-test")
    assert client._scrape_options() == {"formats": ["markdown"]}


def test_scrape_options_includes_wait_for_and_proxy_when_given():
    from ibkr_core_mcp.web_scraper import FirecrawlClient

    client = FirecrawlClient("fc-test")
    assert client._scrape_options(wait_for_ms=3000, proxy="auto", timeout_ms=60000) == {
        "formats": ["markdown"],
        "waitFor": 3000,
        "proxy": "auto",
        "timeout": 60000,
    }


def test_scrape_options_keeps_explicit_zero_wait_for():
    from ibkr_core_mcp.web_scraper import FirecrawlClient

    client = FirecrawlClient("fc-test")
    # 0 is a meaningful value ("don't wait"), not an absent one.
    assert client._scrape_options(wait_for_ms=0) == {"formats": ["markdown"], "waitFor": 0}


@patch("ibkr_core_mcp.web_scraper.requests")
def test_search_passes_wait_for_and_proxy_to_api(mock_requests):
    from ibkr_core_mcp.web_scraper import FirecrawlClient

    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"data": []}
    mock_requests.post.return_value = resp

    client = FirecrawlClient("fc-test")
    client.search("ibkr api", wait_for_ms=3000, proxy="auto")

    payload = mock_requests.post.call_args[1]["json"]
    assert payload["scrapeOptions"]["waitFor"] == 3000
    assert payload["scrapeOptions"]["proxy"] == "auto"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_web_scraper.py -k "scrape_options or search_passes" -v`
Expected: FAILED — `AttributeError: 'FirecrawlClient' object has no attribute '_scrape_options'` and `TypeError: search() got an unexpected keyword argument 'wait_for_ms'`

- [ ] **Step 3: Implement**

In `FirecrawlClient`, add after `_raise_for_status` (after line 199):

```python
    def _scrape_options(
        self,
        *,
        wait_for_ms: int | None = None,
        proxy: str | None = None,
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        """Build the Firecrawl `scrapeOptions` payload shared by search() and crawl().

        One builder for both endpoints so their request bodies cannot drift apart, and
        so a future v2 migration has exactly one seam to change.

        Every option is omitted when None rather than sent as null, which keeps an
        options-free call byte-for-byte identical to the request this client sent before
        these parameters existed.

        Field reference (all confirmed present in v1 scrapeOptions):
        https://docs.firecrawl.dev/v1/api-reference/endpoint/crawl-post (verified 2026-07-25)

        Args:
            wait_for_ms: Milliseconds to wait for JavaScript rendering before extracting.
                0 is meaningful ("don't wait") and is passed through; only None omits it.
            proxy: One of "basic" (1 credit), "enhanced" (up to 5 credits), or "auto"
                (basic, retried through enhanced on failure).
            timeout_ms: Per-page scrape timeout in milliseconds, distinct from this
                client's own polling budget.

        Returns:
            The scrapeOptions dict to embed in a /search or /crawl request body.
        """
        options: dict[str, Any] = {"formats": ["markdown"]}
        if wait_for_ms is not None:
            options["waitFor"] = wait_for_ms
        if proxy is not None:
            options["proxy"] = proxy
        if timeout_ms is not None:
            options["timeout"] = timeout_ms
        return options
```

Change `search`'s signature (line 201) to:

```python
    def search(
        self,
        query: str,
        limit: int = 5,
        *,
        wait_for_ms: int | None = None,
        proxy: str | None = None,
        timeout_ms: int | None = None,
    ) -> list[dict[str, Any]]:
```

Add to `search`'s existing docstring `Args:` block, after the `limit:` entry:

```
            wait_for_ms: Advanced override — milliseconds to wait for JavaScript
                rendering before extraction. See _scrape_options.
            proxy: Advanced override — "basic", "enhanced", or "auto". See
                _scrape_options. Note "enhanced"/"auto" can cost up to 5 credits.
            timeout_ms: Advanced override — per-page scrape timeout in milliseconds.
```

And replace the inline options in its request body (line 236):

```python
                    "scrapeOptions": self._scrape_options(
                        wait_for_ms=wait_for_ms, proxy=proxy, timeout_ms=timeout_ms
                    ),
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_web_scraper.py -k "scrape_options or search" -v`
Expected: all passed — including the pre-existing `test_search_*` tests, which prove the default body is unchanged.

- [ ] **Step 5: Lint, type-check, commit**

```bash
ruff format . && ruff check . && mypy
git add ibkr_core_mcp/web_scraper.py tests/test_web_scraper.py
git commit -m "feat(scraper): add shared _scrape_options builder, expose it on search()

One builder for /search and /crawl so their request bodies cannot drift.
None-valued options are omitted, keeping an options-free call byte-for-byte
identical to today's request."
```

---

## Task 3: The derived timeout budget

**Files:**
- Modify: `ibkr_core_mcp/web_scraper.py` — new module-level `_resolve_timeout`
- Test: `tests/test_web_scraper.py`

- [ ] **Step 1: Write the failing tests**

```python
import pytest


@pytest.mark.parametrize(
    ("max_pages", "expected"),
    [(1, 120), (20, 120), (21, 126), (50, 300), (100, 600)],
)
def test_resolve_timeout_scales_with_max_pages(max_pages, expected):
    from ibkr_core_mcp.web_scraper import _resolve_timeout

    assert _resolve_timeout(max_pages, None) == expected


def test_resolve_timeout_explicit_value_wins():
    from ibkr_core_mcp.web_scraper import _resolve_timeout

    assert _resolve_timeout(100, 45) == 45


def test_resolve_timeout_explicit_value_has_a_floor():
    from ibkr_core_mcp.web_scraper import _resolve_timeout

    assert _resolve_timeout(50, 5) == 10
```

(`import pytest` is already at the top of this test file — don't add it twice.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_web_scraper.py -k resolve_timeout -v`
Expected: FAILED with `ImportError: cannot import name '_resolve_timeout'`

- [ ] **Step 3: Implement**

Add to `ibkr_core_mcp/web_scraper.py` after `content_bytes`:

```python
def _resolve_timeout(max_pages: int, timeout_s: int | None) -> int:
    """Return the per-attempt polling budget in seconds for a crawl.

    `timeout_s` is this client's own polling patience, not Firecrawl's timeout — see
    FirecrawlClient.crawl(). The old fixed 120s default was under-budgeted for its own
    50-page default: a slow, JS-heavy site routinely exceeds it, manufacturing a
    "timed out with nothing" result that is not a block at all. Scaling with page count
    keeps small crawls fast while giving large ones room to finish.

    Args:
        max_pages: Page cap for this crawl, already clamped to [1, 100] by the caller.
        timeout_s: An explicit caller-supplied budget, or None to derive one.

    Returns:
        The explicit value (floored at 10s, matching the previous behavior), or
        `min(600, max(120, 6 * max_pages))` when none was supplied.
    """
    if timeout_s is not None:
        return max(10, timeout_s)
    return min(600, max(120, 6 * max_pages))
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_web_scraper.py -k resolve_timeout -v`
Expected: 7 passed

- [ ] **Step 5: Lint, type-check, commit**

```bash
ruff format . && ruff check . && mypy
git add ibkr_core_mcp/web_scraper.py tests/test_web_scraper.py
git commit -m "feat(scraper): derive crawl polling budget from max_pages

120s for 50 pages was under-budgeted and could manufacture a false
'timed out with nothing' verdict on a site that was merely slow."
```

---

## Task 4: Make every HTTP error a FirecrawlError, and extract one attempt

**Files:**
- Modify: `ibkr_core_mcp/web_scraper.py` — `_raise_for_status` (191-199), `crawl` body (254-415)
- Test: `tests/test_web_scraper.py`

This task is a pure refactor plus one new status code. Behavior visible to callers must not change yet — the ladder arrives in Task 6.

- [ ] **Step 1: Write the failing tests**

```python
@patch("ibkr_core_mcp.web_scraper.requests")
def test_search_402_raises_out_of_credits(mock_requests):
    from ibkr_core_mcp.web_scraper import FirecrawlClient, FirecrawlError

    resp = MagicMock()
    resp.status_code = 402
    mock_requests.post.return_value = resp

    client = FirecrawlClient("fc-test")
    with pytest.raises(FirecrawlError, match="credits") as exc_info:
        client.search("anything")
    assert exc_info.value.status_code == 402


@patch("ibkr_core_mcp.web_scraper.time")
@patch("ibkr_core_mcp.web_scraper.requests")
def test_crawl_poll_http_error_raises_firecrawl_error_not_requests_error(mock_requests, mock_time):
    from ibkr_core_mcp.web_scraper import FirecrawlClient, FirecrawlError

    mock_time.monotonic.side_effect = [0.0, 1.0]

    start_resp = MagicMock()
    start_resp.status_code = 200
    start_resp.json.return_value = {"id": "job-poll-error"}

    poll = MagicMock()
    poll.status_code = 403

    mock_requests.post.return_value = start_resp
    mock_requests.get.return_value = poll

    client = FirecrawlClient("fc-test")
    # Before this change a 403 mid-poll escaped as a raw requests.HTTPError, which
    # ClaudeToolkit's handler does not catch. It must be a FirecrawlError.
    with pytest.raises(FirecrawlError):
        client.crawl("https://example.com", timeout_s=120)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_web_scraper.py -k "402 or poll_http_error" -v`
Expected: 2 FAILED — the 402 test raises `requests.HTTPError` from `resp.raise_for_status()`, and the poll test raises whatever `MagicMock.raise_for_status()` does rather than `FirecrawlError`.

- [ ] **Step 3: Implement**

Replace `_raise_for_status` (lines 191-199) with:

```python
    def _raise_for_status(self, resp: requests.Response) -> None:
        """Translate Firecrawl HTTP errors into FirecrawlError with a status code.

        Every HTTP failure leaves this client as a FirecrawlError, never as a raw
        requests.HTTPError — callers (and ClaudeToolkit's handler) catch one exception
        type, and crawl()'s escalation logic can read `status_code` to decide whether a
        retry could possibly help.
        """
        if resp.status_code == 401:
            raise FirecrawlError("Invalid FIRECRAWL_API_KEY", 401)
        if resp.status_code == 402:
            raise FirecrawlError("Firecrawl account is out of credits", 402)
        if resp.status_code == 429:
            raise FirecrawlError("Rate limit exceeded — wait before retrying", 429)
        if resp.status_code >= 500:
            raise FirecrawlError(f"Firecrawl service error: {resp.status_code}", resp.status_code)
        if resp.status_code >= 400:
            raise FirecrawlError(f"Firecrawl request failed: HTTP {resp.status_code}", resp.status_code)
```

Now rename `crawl` to `_try_crawl` and change only its signature and three lines of its body. The polling and pagination logic is unchanged.

New signature (replacing lines 254-259):

```python
    def _try_crawl(
        self,
        url: str,
        max_pages: int,
        timeout_s: int,
        scrape_options: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Run exactly one Firecrawl crawl attempt: start the job, poll it, follow
        pagination, and return whatever pages it produced.

        Callers pass an already-clamped `max_pages` and an already-resolved `timeout_s`
        (see _resolve_timeout), plus a prepared scrapeOptions dict (see _scrape_options).
        The retry/escalation decision belongs to crawl(), not here — this method's only
        job is to execute one attempt faithfully.

        Args:
            url: Root URL to crawl. SSRF validation is the caller's responsibility.
            max_pages: Page cap, already clamped to [1, 100].
            timeout_s: Polling budget in seconds, already resolved.
            scrape_options: The scrapeOptions payload to send.

        Returns:
            Page dicts with "url", "markdown", and "metadata" keys. Empty-markdown and
            error pages are included, not filtered, so callers can see and recover from
            them. Partial results are returned on timeout rather than raising.

        Raises:
            FirecrawlError: On any HTTP failure, or if the job reports status "failed".
        """
```

Inside the body, make exactly three edits:

1. The job-start request body (line 318) becomes:

```python
                json={"url": url, "limit": max_pages, "scrapeOptions": scrape_options},
```

2. Delete the two clamping lines at 310-311 (`max_pages = ...` and `timeout_s = ...`) — the caller now owns both.

3. Replace both bare `raise_for_status()` calls with the client's own translator:

- line 359: `poll.raise_for_status()` → `self._raise_for_status(poll)`
- line 401: `next_resp.raise_for_status()` → `self._raise_for_status(next_resp)`

Finally add a temporary `crawl` that preserves today's public behavior exactly, so the suite stays green until Task 6 replaces it:

```python
    def crawl(
        self,
        url: str,
        max_pages: int = 50,
        timeout_s: int | None = None,
    ) -> list[dict[str, Any]]:
        """Crawl a site starting from url and return all pages as markdown.

        Replaced by the escalating implementation in the next commit; for now this is a
        faithful wrapper preserving the previous single-attempt behavior.
        """
        max_pages = max(1, min(100, max_pages))
        return self._try_crawl(url, max_pages, _resolve_timeout(max_pages, timeout_s), self._scrape_options())
```

Move the original `crawl` docstring's `Args:`/`Returns:`/`Raises:` prose onto `_try_crawl`, keeping the detailed notes about SSRF validation of discovered sub-pages and unfiltered error pages.

- [ ] **Step 4: Run the full crawl test suite**

Run: `pytest tests/test_web_scraper.py -v`
Expected: all passed. Every pre-existing crawl test still passes — this task changed no observable behavior except that a 4xx mid-poll is now a `FirecrawlError`.

- [ ] **Step 5: Lint, type-check, commit**

```bash
ruff format . && ruff check . && mypy
git add ibkr_core_mcp/web_scraper.py tests/test_web_scraper.py
git commit -m "refactor(scraper): extract _try_crawl, make every HTTP error a FirecrawlError

A 4xx mid-poll previously escaped as a raw requests.HTTPError, which the
ClaudeToolkit handler does not catch — one of three failure exits that
bypassed recovery entirely. Also adds HTTP 402 (out of credits), which
previously fell through to raise_for_status()."
```

---

## Task 5: Let existing crawl tests opt out of escalation

**Files:**
- Modify: `tests/test_web_scraper.py`

Every pre-existing crawl test returns tiny markdown (`"# Page"`, `"# Real"`) or no pages at all. Once Task 6 lands, all of them would trigger a second attempt and run their mocks dry. Rather than padding nine fixtures past 5 KB, give them a fixture that turns the threshold off — they are testing polling, pagination and clamping, not escalation.

- [ ] **Step 1: Add the fixture**

Add near the top of `tests/test_web_scraper.py`, after the imports:

```python
@pytest.fixture
def no_escalation(monkeypatch):
    monkeypatch.setattr("ibkr_core_mcp.web_scraper._MIN_USEFUL_BYTES", 0)
```

With the threshold at 0, any result — including an empty page list — clears it, so `crawl()` returns after one attempt exactly as it does today.

- [ ] **Step 2: Apply it to every existing crawl test**

Add `no_escalation` as the **last** parameter of these eight test functions (after the `mock_time`/`mock_requests` mock parameters, since `@patch` decorators inject theirs right-to-left and pytest fixtures fill the remainder):

- `test_crawl_job_start_retries_on_429_then_succeeds`
- `test_crawl_polls_until_completed`
- `test_crawl_timeout_returns_partial_results`
- `test_crawl_keeps_pages_with_empty_markdown_and_metadata`
- `test_crawl_max_pages_clamped`
- `test_crawl_follows_next_cursor_for_large_results`
- `test_crawl_next_cursor_fetch_retries_on_429_then_succeeds`
- `test_crawl_next_cursor_stops_on_repeated_url`

Example — `test_crawl_polls_until_completed` becomes:

```python
@patch("ibkr_core_mcp.web_scraper.time")
@patch("ibkr_core_mcp.web_scraper.requests")
def test_crawl_polls_until_completed(mock_requests, mock_time, no_escalation):
```

Do **not** add it to `test_crawl_failed_status_raises` or `test_crawl_poll_http_error_raises_firecrawl_error_not_requests_error` — those are rewritten in Task 6.

- [ ] **Step 3: Run the suite**

Run: `pytest tests/test_web_scraper.py -v`
Expected: all passed, unchanged. The fixture is inert until Task 6 introduces escalation.

- [ ] **Step 4: Commit**

```bash
ruff format . && ruff check .
git add tests/test_web_scraper.py
git commit -m "test(scraper): add no_escalation fixture to existing crawl tests

These tests cover polling, pagination and clamping, not escalation. Turning
the size threshold off keeps them single-attempt once the ladder lands,
instead of padding nine fixtures past 5 KB."
```

---

## Task 6: The escalation ladder

**Files:**
- Modify: `ibkr_core_mcp/web_scraper.py` — new `_attempt`, rewritten `crawl`
- Test: `tests/test_web_scraper.py`

- [ ] **Step 1: Write the failing tests**

First, a helper for building a page big enough to clear the threshold. Add it next to the `no_escalation` fixture:

```python
_BIG_MARKDOWN = "# Real page\n\n" + ("word " * 2000)  # ~10 KB, comfortably over 5 KB
```

Then the escalation tests:

```python
def _crawl_responses(mock_requests, mock_time, poll_payloads):
    """Wire mock_requests so each crawl attempt sees the next payload in poll_payloads."""
    import itertools

    mock_time.monotonic.side_effect = itertools.count(0.0, 1.0)
    start_resp = MagicMock()
    start_resp.status_code = 200
    start_resp.json.return_value = {"id": "job-1"}
    mock_requests.post.return_value = start_resp

    polls = []
    for payload in poll_payloads:
        poll = MagicMock()
        poll.status_code = 200
        poll.json.return_value = payload
        polls.append(poll)
    mock_requests.get.side_effect = polls


@patch("ibkr_core_mcp.web_scraper.time")
@patch("ibkr_core_mcp.web_scraper.requests")
def test_crawl_escalates_when_first_attempt_returns_no_pages(mock_requests, mock_time):
    from ibkr_core_mcp.web_scraper import FirecrawlClient

    _crawl_responses(
        mock_requests,
        mock_time,
        [
            {"status": "completed", "data": []},
            {"status": "completed", "data": [{"metadata": {"sourceURL": "https://example.com/a"}, "markdown": _BIG_MARKDOWN}]},
        ],
    )

    client = FirecrawlClient("fc-test")
    pages = client.crawl("https://example.com", timeout_s=120)

    assert len(pages) == 1
    assert mock_requests.post.call_count == 2
    escalated = mock_requests.post.call_args_list[1][1]["json"]
    assert escalated["scrapeOptions"]["waitFor"] == 3000
    assert escalated["scrapeOptions"]["proxy"] == "auto"


@patch("ibkr_core_mcp.web_scraper.time")
@patch("ibkr_core_mcp.web_scraper.requests")
def test_crawl_escalates_when_first_attempt_is_under_threshold(mock_requests, mock_time):
    from ibkr_core_mcp.web_scraper import FirecrawlClient

    _crawl_responses(
        mock_requests,
        mock_time,
        [
            {"status": "completed", "data": [{"metadata": {"sourceURL": "https://example.com/a"}, "markdown": "tiny"}]},
            {"status": "completed", "data": [{"metadata": {"sourceURL": "https://example.com/a"}, "markdown": _BIG_MARKDOWN}]},
        ],
    )

    client = FirecrawlClient("fc-test")
    pages = client.crawl("https://example.com", timeout_s=120)

    assert pages[0]["markdown"] == _BIG_MARKDOWN
    assert mock_requests.post.call_count == 2


@patch("ibkr_core_mcp.web_scraper.time")
@patch("ibkr_core_mcp.web_scraper.requests")
def test_crawl_does_not_escalate_when_first_attempt_clears_threshold(mock_requests, mock_time):
    from ibkr_core_mcp.web_scraper import FirecrawlClient

    _crawl_responses(
        mock_requests,
        mock_time,
        [{"status": "completed", "data": [{"metadata": {"sourceURL": "https://example.com/a"}, "markdown": _BIG_MARKDOWN}]}],
    )

    client = FirecrawlClient("fc-test")
    pages = client.crawl("https://example.com", timeout_s=120)

    assert len(pages) == 1
    assert mock_requests.post.call_count == 1


@patch("ibkr_core_mcp.web_scraper.time")
@patch("ibkr_core_mcp.web_scraper.requests")
def test_crawl_keeps_the_better_rung_when_escalation_returns_less(mock_requests, mock_time):
    from ibkr_core_mcp.web_scraper import FirecrawlClient

    partial = "x" * 4000  # under 5 KB, so it escalates — but it is still real content
    _crawl_responses(
        mock_requests,
        mock_time,
        [
            {"status": "completed", "data": [{"metadata": {"sourceURL": "https://example.com/a"}, "markdown": partial}]},
            {"status": "completed", "data": []},
        ],
    )

    client = FirecrawlClient("fc-test")
    pages = client.crawl("https://example.com", timeout_s=120)

    # The ladder is monotonic: it can never return less than a previous rung produced.
    assert pages[0]["markdown"] == partial


@patch("ibkr_core_mcp.web_scraper.time")
@patch("ibkr_core_mcp.web_scraper.requests")
def test_crawl_failed_job_escalates_then_returns_empty(mock_requests, mock_time):
    from ibkr_core_mcp.web_scraper import FirecrawlClient

    _crawl_responses(
        mock_requests,
        mock_time,
        [
            {"status": "failed", "error": "blocked by robots.txt"},
            {"status": "failed", "error": "blocked by robots.txt"},
        ],
    )

    client = FirecrawlClient("fc-test")
    # A failed job used to raise before any recovery could run — that abort is the bug.
    assert client.crawl("https://example.com", timeout_s=120) == []
    assert mock_requests.post.call_count == 2


@patch("ibkr_core_mcp.web_scraper.time")
@patch("ibkr_core_mcp.web_scraper.requests")
def test_crawl_401_raises_without_escalating(mock_requests, mock_time):
    from ibkr_core_mcp.web_scraper import FirecrawlClient, FirecrawlError

    import itertools

    mock_time.monotonic.side_effect = itertools.count(0.0, 1.0)
    start_resp = MagicMock()
    start_resp.status_code = 401
    mock_requests.post.return_value = start_resp

    client = FirecrawlClient("fc-test")
    with pytest.raises(FirecrawlError, match="FIRECRAWL_API_KEY"):
        client.crawl("https://example.com", timeout_s=120)
    # A stealth retry cannot fix a bad key — don't spend a second attempt on it.
    assert mock_requests.post.call_count == 1


@patch("ibkr_core_mcp.web_scraper.time")
@patch("ibkr_core_mcp.web_scraper.requests")
def test_crawl_escalated_attempt_gets_a_larger_budget(mock_requests, mock_time):
    from ibkr_core_mcp.web_scraper import FirecrawlClient

    _crawl_responses(
        mock_requests,
        mock_time,
        [{"status": "completed", "data": []}, {"status": "completed", "data": []}],
    )

    client = FirecrawlClient("fc-test")
    with patch.object(FirecrawlClient, "_try_crawl", return_value=[]) as spy:
        client.crawl("https://example.com", max_pages=1, timeout_s=120)

    # Rung 1 uses the caller's 120s; rung 2 is floored at 180s because stealth is slower.
    assert spy.call_args_list[0][0][2] == 120
    assert spy.call_args_list[1][0][2] == 180


@patch("ibkr_core_mcp.web_scraper.time")
@patch("ibkr_core_mcp.web_scraper.requests")
def test_crawl_never_makes_more_than_two_attempts(mock_requests, mock_time):
    from ibkr_core_mcp.web_scraper import FirecrawlClient

    _crawl_responses(
        mock_requests,
        mock_time,
        [{"status": "completed", "data": []}, {"status": "completed", "data": []}],
    )

    client = FirecrawlClient("fc-test")
    assert client.crawl("https://example.com", timeout_s=120) == []
    assert mock_requests.post.call_count == 2
```

Finally, **delete** `test_crawl_failed_status_raises` (line 325) — `test_crawl_failed_job_escalates_then_returns_empty` replaces it — and **update** `test_crawl_poll_http_error_raises_firecrawl_error_not_requests_error` from Task 4 to assert the new behavior instead:

```python
@patch("ibkr_core_mcp.web_scraper.time")
@patch("ibkr_core_mcp.web_scraper.requests")
def test_crawl_poll_http_error_escalates_then_returns_empty(mock_requests, mock_time):
    from ibkr_core_mcp.web_scraper import FirecrawlClient

    import itertools

    mock_time.monotonic.side_effect = itertools.count(0.0, 1.0)
    start_resp = MagicMock()
    start_resp.status_code = 200
    start_resp.json.return_value = {"id": "job-poll-error"}
    poll = MagicMock()
    poll.status_code = 403
    mock_requests.post.return_value = start_resp
    mock_requests.get.return_value = poll

    client = FirecrawlClient("fc-test")
    # A 403 mid-poll used to escape as a raw requests.HTTPError the handler never caught.
    assert client.crawl("https://example.com", timeout_s=120) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_web_scraper.py -k "escalat or 401_raises or two_attempts or better_rung" -v`
Expected: FAILED — `crawl()` currently makes exactly one attempt, so `post.call_count` is 1 everywhere and the failed-job test raises.

- [ ] **Step 3: Implement**

Add `_attempt` to `FirecrawlClient`, just before `_try_crawl`:

```python
    def _attempt(
        self,
        url: str,
        max_pages: int,
        timeout_s: int,
        scrape_options: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Run one crawl attempt, converting every recoverable failure into an empty
        page list so the caller has something to measure.

        This is the piece that makes the recovery ladder possible. Previously a crawl
        could end three different ways — a raised FirecrawlError on a failed job, a raw
        requests.HTTPError mid-poll, or a silent empty return on deadline — so there was
        no single point at which "we got nothing" was decided, and therefore nowhere to
        attach recovery. Every route now ends in a list.

        Args:
            url: Root URL to crawl.
            max_pages: Page cap, already clamped.
            timeout_s: Polling budget, already resolved.
            scrape_options: The scrapeOptions payload for this attempt.

        Returns:
            The attempt's pages, or [] if it failed recoverably.

        Raises:
            FirecrawlError: For account-level failures only (401 bad key, 402 out of
                credits, 429 rate limited). A slower, more expensive retry cannot fix
                any of them, and in the 429 case would worsen the throttling — so these
                propagate rather than consuming an escalation.
        """
        try:
            return self._try_crawl(url, max_pages, timeout_s, scrape_options)
        except FirecrawlError as exc:
            if exc.status_code in _NON_ESCALATING_STATUSES:
                raise
            log.warning("firecrawl crawl attempt for %s failed: %s", url, exc)
            return []
        except requests.RequestException as exc:
            log.warning("firecrawl crawl attempt for %s failed: %s", url, exc)
            return []
```

Replace the temporary `crawl` from Task 4 with:

```python
    def crawl(
        self,
        url: str,
        max_pages: int = 50,
        timeout_s: int | None = None,
        *,
        wait_for_ms: int | None = None,
        proxy: str | None = None,
    ) -> list[dict[str, Any]]:
        """Crawl a site starting from url and return all pages as markdown.

        Runs up to two Firecrawl attempts. The first uses cheap defaults. If it yields
        less than _MIN_USEFUL_BYTES of markdown — whether because the site blocked us,
        the job failed, the budget ran out, or the pages came back empty — a second
        attempt runs with waitFor and an anti-bot proxy, options proven against
        interactivebrokers.com (see _ESCALATION_WAIT_FOR_MS).

        The better of the two results is returned, so the ladder is monotonic: it can
        never hand back less than the first attempt already produced, and a thin
        escalated result can never silently replace a good cheap one. That is what makes
        a threshold this aggressive safe — a legitimately short page costs a wasted
        retry, never a wrong answer.

        A caller that still gets nothing should fall back to a local scrape;
        ClaudeToolkit._handle_firecrawl_crawl does exactly that with Crawl4AI.

        Args:
            url: Root URL to crawl from. Must be a public http/https URL. The caller is
                responsible for SSRF validation. Note this only validates the root — the
                individual page URLs in the returned list were discovered by Firecrawl
                and are re-checked independently by ClaudeToolkit._validate_public_url
                before any local fetch of them.
            max_pages: Upper bound on pages to crawl. Clamped to [1, 100].
            timeout_s: Polling budget **per attempt**, in seconds. None derives one from
                max_pages (see _resolve_timeout). Worst-case wall clock is therefore
                roughly twice this value when both attempts run.
            wait_for_ms: Advanced override for the first attempt's JS render wait. The
                escalated attempt uses _ESCALATION_WAIT_FOR_MS unless this is set, in
                which case the caller's value is respected on both attempts.
            proxy: Advanced override for the first attempt's proxy mode, same handling
                as wait_for_ms. "enhanced"/"auto" can cost up to 5 credits per page.

        Returns:
            Page dicts with "url", "markdown" and "metadata" keys. Empty-markdown and
            error pages are included, not filtered, so callers can see and recover from
            them. Returns [] when both attempts came back with nothing.

        Raises:
            FirecrawlError: Only for account-level failures — 401 (invalid key), 402
                (out of credits), 429 (rate limited). Note this method no longer raises
                when the crawl job itself reports "failed"; that case escalates and then
                returns whatever the ladder produced, which is the point of the ladder.
        """
        max_pages = max(1, min(100, max_pages))
        resolved_timeout = _resolve_timeout(max_pages, timeout_s)

        first = self._attempt(
            url,
            max_pages,
            resolved_timeout,
            self._scrape_options(wait_for_ms=wait_for_ms, proxy=proxy),
        )
        if content_bytes(first) >= _MIN_USEFUL_BYTES:
            return first

        log.warning(
            "firecrawl crawl of %s returned %d B (under the %d B threshold) — "
            "retrying with waitFor and an anti-bot proxy",
            url,
            content_bytes(first),
            _MIN_USEFUL_BYTES,
        )
        second = self._attempt(
            url,
            max_pages,
            max(resolved_timeout, _ESCALATION_MIN_TIMEOUT_S),
            self._scrape_options(
                wait_for_ms=_ESCALATION_WAIT_FOR_MS if wait_for_ms is None else wait_for_ms,
                proxy=_ESCALATION_PROXY if proxy is None else proxy,
            ),
        )
        # max() returns the first maximal element, so a tie keeps the cheaper rung.
        return max(first, second, key=content_bytes)
```

- [ ] **Step 4: Run the full suite**

Run: `pytest tests/test_web_scraper.py -v`
Expected: all passed, including every pre-existing crawl test via the `no_escalation` fixture from Task 5.

- [ ] **Step 5: Lint, type-check, commit**

```bash
ruff format . && ruff check . && mypy
git add ibkr_core_mcp/web_scraper.py tests/test_web_scraper.py
git commit -m "feat(scraper): escalate a content-free crawl with waitFor and proxy

Rung 1 uses cheap defaults; if it yields under 5 KB of markdown for any
reason, rung 2 retries with waitFor=3000 and proxy=auto — the options proven
against interactivebrokers.com in the repo's own scrape manifest. The better
of the two results wins, so the ladder can never return less than rung 1
produced.

BREAKING: crawl() no longer raises when the job reports 'failed'. That abort
happened before any recovery could run and is the bug being fixed.
FirecrawlError is now raised only for 401/402/429."
```

---

## Task 7: Flexible profile-directory resolution

**Files:**
- Modify: `ibkr_core_mcp/scrape_fallback.py` — new `_resolve_profile_dir`, used in `scrape_batch` (line ~420)
- Modify: `ibkr_core_mcp/claude_tools.py` — `_finalize_fallback_result` (line ~2795)
- Test: `tests/test_scrape_fallback.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_resolve_profile_dir_prefers_exact_host(tmp_path):
    from ibkr_core_mcp.scrape_fallback import _resolve_profile_dir

    (tmp_path / "markets.ft.com").mkdir()
    (tmp_path / "ft.com").mkdir()

    assert _resolve_profile_dir(tmp_path, "https://markets.ft.com/x") == tmp_path / "markets.ft.com"


def test_resolve_profile_dir_strips_www(tmp_path):
    from ibkr_core_mcp.scrape_fallback import _resolve_profile_dir

    (tmp_path / "ft.com").mkdir()

    assert _resolve_profile_dir(tmp_path, "https://www.ft.com/x") == tmp_path / "ft.com"


def test_resolve_profile_dir_finds_parent_domain_for_subdomain(tmp_path):
    from ibkr_core_mcp.scrape_fallback import _resolve_profile_dir

    (tmp_path / "wsj.com").mkdir()

    assert _resolve_profile_dir(tmp_path, "https://www.wsj.com/articles/x") == tmp_path / "wsj.com"


def test_resolve_profile_dir_stops_at_two_labels(tmp_path):
    from ibkr_core_mcp.scrape_fallback import _resolve_profile_dir

    # A bare-TLD directory must never be matched — stripping stops while two labels remain.
    (tmp_path / "com").mkdir()

    assert _resolve_profile_dir(tmp_path, "https://deep.sub.example.com/x") is None


def test_resolve_profile_dir_returns_none_when_nothing_matches(tmp_path):
    from ibkr_core_mcp.scrape_fallback import _resolve_profile_dir

    assert _resolve_profile_dir(tmp_path, "https://www.ft.com/x") is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_scrape_fallback.py -k resolve_profile_dir -v`
Expected: 5 FAILED with `ImportError: cannot import name '_resolve_profile_dir'`

- [ ] **Step 3: Implement**

Add to `ibkr_core_mcp/scrape_fallback.py` after `_safe_domain`:

```python
def _resolve_profile_dir(profiles_dir: Path, url_or_domain: str) -> Path | None:
    """Find the saved browser profile that applies to a URL, or None if there is none.

    Lookup used to be exact-hostname only, which silently defeated the feature it was
    built for: a profile created for "www.ft.com" was not found for a "ft.com" or
    "markets.ft.com" article, so the scrape fell back to anonymous and returned the
    paywall stub with nothing indicating the profile existed.

    Candidates are tried most-specific first: the exact host, the host without a leading
    "www.", then progressively broader parents while at least two labels remain. Matching
    therefore only ever broadens *toward* the registrable domain, never toward a sibling
    host — a profile for "ft.com" can serve "markets.ft.com", which is intended, and
    cookie scoping still applies on top. Stopping at two labels means a directory named
    after a bare TLD can never be matched.

    Multi-part suffixes ("ft.co.uk") stop at "co.uk", which will simply never match a
    saved profile. No public-suffix list is worth adding for that.

    Args:
        profiles_dir: Root holding one profile directory per domain
            (Config.crawl4ai_profiles_dir).
        url_or_domain: A URL or bare domain; only its hostname is used.

    Returns:
        The first matching profile directory, or None to scrape anonymously.
    """
    host = _safe_domain(url_or_domain)
    candidates = [host]
    if host.startswith("www."):
        candidates.append(host[len("www.") :])
    labels = host.split(".")
    while len(labels) > 2:
        labels = labels[1:]
        candidate = ".".join(labels)
        if candidate not in candidates:
            candidates.append(candidate)
    for candidate in candidates:
        path = profiles_dir / candidate
        if path.is_dir():
            return path
    return None
```

In `scrape_batch`, replace the exact-match block:

```python
        domain = _safe_domain(profile_domain)
        profile_dir = self._profiles_dir / domain
        if profile_dir.is_dir():
```

with:

```python
        profile_dir = _resolve_profile_dir(self._profiles_dir, profile_domain)
        if profile_dir is not None:
```

(The `user_data_dir=str(profile_dir)` line below it is unchanged.)

In `ibkr_core_mcp/claude_tools.py`'s `_finalize_fallback_result`, replace:

```python
        domain = urllib.parse.urlparse(url).hostname or ""
        profile_dir = self._config.crawl4ai_profiles_dir / domain
        if profile_dir.is_dir():
```

with:

```python
        from ibkr_core_mcp.scrape_fallback import _resolve_profile_dir

        domain = urllib.parse.urlparse(url).hostname or ""
        if _resolve_profile_dir(self._config.crawl4ai_profiles_dir, url) is not None:
```

so the "no saved login profile" note cannot claim a profile is missing when the scrape would have found one.

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_scrape_fallback.py tests/claude_tools/test_web_scraping.py -v`
Expected: all passed

- [ ] **Step 5: Lint, type-check, commit**

```bash
ruff format . && ruff check . && mypy
git add ibkr_core_mcp/scrape_fallback.py ibkr_core_mcp/claude_tools.py tests/test_scrape_fallback.py
git commit -m "fix(scraper): resolve login profiles across www and subdomains

A profile created for www.ft.com was silently not found for ft.com or
markets.ft.com, so paywalled scrapes fell back to anonymous and returned the
subscription stub. Matching now broadens toward the registrable domain,
stopping while two labels remain so a bare-TLD directory can never match."
```

---

## Task 8: `list-profiles` CLI subcommand

**Files:**
- Modify: `ibkr_core_mcp/scrape_fallback.py` — new `list_profiles`, `_main` (line ~518)
- Test: `tests/test_scrape_fallback.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_list_profiles_returns_empty_for_missing_dir(tmp_path):
    from ibkr_core_mcp.scrape_fallback import list_profiles

    assert list_profiles(tmp_path / "nope") == []


def test_list_profiles_reports_each_saved_domain(tmp_path):
    from ibkr_core_mcp.scrape_fallback import list_profiles

    (tmp_path / "www.ft.com").mkdir()
    (tmp_path / "wsj.com").mkdir()
    (tmp_path / "stray-file.txt").write_text("not a profile")

    entries = list_profiles(tmp_path)

    assert [name for name, _path, _age in entries] == ["www.ft.com", "wsj.com"]
    assert all(age >= 0 for _name, _path, age in entries)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_scrape_fallback.py -k list_profiles -v`
Expected: 2 FAILED with `ImportError: cannot import name 'list_profiles'`

- [ ] **Step 3: Implement**

Add `import time` to the stdlib imports at the top of `scrape_fallback.py` (after `import threading`).

Add after `create_profile`:

```python
def list_profiles(profiles_dir: Path) -> list[tuple[str, Path, float]]:
    """Return every saved browser profile with its path and age in days.

    Saved sessions expire, and until now expiry presented as a mysteriously truncated
    article with no way to check what was saved or how old it was. Age is taken from the
    directory's mtime, which create_profile sets when it copies the profile in.

    Args:
        profiles_dir: Root holding one profile directory per domain
            (Config.crawl4ai_profiles_dir). A missing directory is not an error.

    Returns:
        (domain, path, age_days) tuples sorted by domain. Non-directory entries are
        skipped. Empty list when nothing is saved.
    """
    if not profiles_dir.is_dir():
        return []
    now = time.time()
    entries: list[tuple[str, Path, float]] = []
    for child in sorted(profiles_dir.iterdir()):
        if not child.is_dir():
            continue
        entries.append((child.name, child, (now - child.stat().st_mtime) / 86400))
    return entries
```

In `_main`, add the subparser after the `create-profile` one:

```python
    subparsers.add_parser(
        "list-profiles",
        help="List saved login profiles and how old each session is.",
    )
```

and extend the dispatch:

```python
    if args.command == "create-profile":
        config = Config.from_env()
        dest = create_profile(args.url_or_domain, config.crawl4ai_profiles_dir)
        print(f"Profile saved to {dest}")
    elif args.command == "list-profiles":
        config = Config.from_env()
        entries = list_profiles(config.crawl4ai_profiles_dir)
        if not entries:
            print(f"No saved profiles in {config.crawl4ai_profiles_dir}")
            return
        for domain, path, age_days in entries:
            print(f"{domain:<30} {age_days:>6.1f} days  {path}")
```

Also update `_main`'s docstring — it currently says "Only one subcommand exists today (`create-profile`)". Replace that sentence with: "Two subcommands exist: `create-profile` and `list-profiles`."

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_scrape_fallback.py -k list_profiles -v`
Expected: 2 passed

Then verify the CLI by hand:

Run: `python -m ibkr_core_mcp.scrape_fallback list-profiles`
Expected: either a table of saved domains, or `No saved profiles in /Users/.../.ibkr_core/crawl4ai_profiles`

- [ ] **Step 5: Lint, type-check, commit**

```bash
ruff format . && ruff check . && mypy
git add ibkr_core_mcp/scrape_fallback.py tests/test_scrape_fallback.py
git commit -m "feat(scraper): add list-profiles subcommand

Saved sessions expire, and expiry previously presented as a mysteriously
truncated article with no way to check what was saved or how old it was."
```

---

## Task 9: The handler's last resort and honest reporting

**Files:**
- Modify: `ibkr_core_mcp/claude_tools.py` — new `_crawl4ai_root_scrape`, rewritten `_handle_firecrawl_crawl` (lines 2988-3070)
- Test: `tests/claude_tools/test_web_scraping.py`

- [ ] **Step 1: Enlarge the shared test fixture**

`_REALISTIC_MARKDOWN` at the top of `tests/claude_tools/test_web_scraping.py` is about 1.8 KB — under the new 5 KB threshold, so every handler test using it would now trigger the root fallback. A real documentation page is 12-90 KB, so make the fixture realistic rather than patching the threshold. Rename the existing string to `_REALISTIC_PARAGRAPH` and add below it:

```python
# Repeated to ~7 KB so it clears web_scraper._MIN_USEFUL_BYTES, matching the size of a
# real documentation page (12.9-91.9 KB in docs/audits/audit-evidence/scrapes/).
_REALISTIC_MARKDOWN = _REALISTIC_PARAGRAPH * 4
```

- [ ] **Step 2: Write the failing tests**

```python
def test_crawl_falls_back_to_crawl4ai_root_when_firecrawl_returns_nothing():
    from ibkr_core_mcp.claude_tools import ClaudeToolkit

    toolkit = _make_toolkit()
    toolkit._firecrawl = MagicMock()
    toolkit._firecrawl.crawl.return_value = []
    toolkit._web_docs = MagicMock()
    toolkit._web_docs.get_cached_crawl.return_value = None
    toolkit._web_docs.save_crawl.return_value = {
        "url": "https://www.interactivebrokers.com/docs/",
        "crawled_at": "2026-07-25T00:00:00+00:00",
        "pages": [{"url": "https://www.interactivebrokers.com/docs/", "file_id": "f1"}],
    }
    toolkit._crawl4ai = MagicMock()
    toolkit._crawl4ai.scrape.return_value = {
        "url": "https://www.interactivebrokers.com/docs/",
        "markdown": _REALISTIC_MARKDOWN,
    }

    text, _payload = toolkit.execute(
        "firecrawl_crawl", {"url": "https://www.interactivebrokers.com/docs/"}
    )

    toolkit._crawl4ai.scrape.assert_called_once_with("https://www.interactivebrokers.com/docs/")
    saved_pages = toolkit._web_docs.save_crawl.call_args[0][1]
    assert saved_pages[0]["markdown"] == _REALISTIC_MARKDOWN
    assert "Crawl4AI" in text


def test_crawl_does_not_root_scrape_when_firecrawl_returned_content():
    toolkit = _make_toolkit()
    toolkit._firecrawl = MagicMock()
    toolkit._firecrawl.crawl.return_value = [
        {"url": "https://example.com/a", "markdown": _REALISTIC_MARKDOWN, "metadata": {}}
    ]
    toolkit._web_docs = MagicMock()
    toolkit._web_docs.get_cached_crawl.return_value = None
    toolkit._web_docs.save_crawl.return_value = {
        "url": "https://example.com",
        "crawled_at": "2026-07-25T00:00:00+00:00",
        "pages": [{"url": "https://example.com/a", "file_id": "f1"}],
    }
    toolkit._crawl4ai = MagicMock()

    toolkit.execute("firecrawl_crawl", {"url": "https://example.com"})

    toolkit._crawl4ai.scrape.assert_not_called()


def test_crawl_never_reports_zero_pages_as_success():
    toolkit = _make_toolkit()
    toolkit._firecrawl = MagicMock()
    toolkit._firecrawl.crawl.return_value = []
    toolkit._web_docs = MagicMock()
    toolkit._web_docs.get_cached_crawl.return_value = None
    toolkit._crawl4ai = MagicMock()
    toolkit._crawl4ai.scrape.return_value = {"url": "https://example.com", "markdown": ""}

    text, _payload = toolkit.execute("firecrawl_crawl", {"url": "https://example.com"})

    assert "saved 0 page(s)" not in text
    assert "no content" in text.lower()
    toolkit._web_docs.save_crawl.assert_not_called()


def test_crawl_degrades_when_crawl4ai_is_not_installed():
    from ibkr_core_mcp.scrape_fallback import Crawl4AIUnavailableError

    toolkit = _make_toolkit()
    toolkit._firecrawl = MagicMock()
    toolkit._firecrawl.crawl.return_value = []
    toolkit._web_docs = MagicMock()
    toolkit._web_docs.get_cached_crawl.return_value = None
    toolkit._crawl4ai = MagicMock()
    toolkit._crawl4ai.scrape.side_effect = Crawl4AIUnavailableError("not installed")

    text, _payload = toolkit.execute("firecrawl_crawl", {"url": "https://example.com"})

    assert "no content" in text.lower()


def test_crawl_reports_network_failure_instead_of_raising():
    import requests

    toolkit = _make_toolkit()
    toolkit._firecrawl = MagicMock()
    toolkit._firecrawl.crawl.side_effect = requests.ConnectionError("dns failure")
    toolkit._web_docs = MagicMock()
    toolkit._web_docs.get_cached_crawl.return_value = None

    text, _payload = toolkit.execute("firecrawl_crawl", {"url": "https://example.com"})

    assert "network" in text.lower()
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `pytest tests/claude_tools/test_web_scraping.py -k "root or zero_pages or not_installed or network" -v`
Expected: FAILED — no root scrape happens, the message still says "saved 0 page(s)", and the `ConnectionError` propagates.

- [ ] **Step 4: Implement**

Add this method to `ClaudeToolkit`, just before `_handle_firecrawl_crawl`:

```python
    def _crawl4ai_root_scrape(self, url: str) -> list[dict[str, Any]]:
        """Fetch a crawl's root URL locally with Crawl4AI as the ladder's last rung.

        The per-page fallback (_apply_crawl4ai_fallback_batch) iterates over Firecrawl's
        page list, so it cannot recover a crawl that produced no pages at all — the exact
        failure this closes. Fetching the root at least yields the landing page, and does
        it locally and free, which is also the right move when Firecrawl is rate-limited
        or out of credits.

        Args:
            url: The crawl's root URL, already SSRF-validated by the caller.

        Returns:
            A single-page list shaped like Firecrawl's own output so it flows into
            save_crawl unchanged, or [] when Crawl4AI produced nothing or is unavailable.
        """
        from ibkr_core_mcp.scrape_fallback import Crawl4AIScraper

        if self._crawl4ai is None:
            self._crawl4ai = Crawl4AIScraper(self._config.crawl4ai_profiles_dir)

        outcome: dict[str, str] | Exception
        try:
            outcome = self._crawl4ai.scrape(url)
        except Exception as exc:
            outcome = exc

        markdown, _note, used_fallback = self._finalize_fallback_result(url, "", outcome)
        if not used_fallback or not markdown:
            return []
        return [{"url": url, "markdown": markdown, "metadata": {}}]
```

In `_handle_firecrawl_crawl`, change the input parsing block so `timeout_s` can be absent and the two new overrides are read:

```python
        max_pages = int(inputs.get("max_pages", 50))
        timeout_s_raw = inputs.get("timeout_s")
        timeout_s = int(timeout_s_raw) if timeout_s_raw is not None else None
        wait_for_raw = inputs.get("wait_for_ms")
        wait_for_ms = int(wait_for_raw) if wait_for_raw is not None else None
        proxy = inputs.get("proxy") or None
        force_refresh = bool(inputs.get("force_refresh", False))
```

Replace the crawl call and everything after it (from `try: pages = self._firecrawl.crawl(...)` to the end of the method) with:

```python
        import requests

        from ibkr_core_mcp.web_scraper import _MIN_USEFUL_BYTES, content_bytes

        try:
            pages = self._firecrawl.crawl(
                url,
                max_pages=max_pages,
                timeout_s=timeout_s,
                wait_for_ms=wait_for_ms,
                proxy=proxy,
            )
        except FirecrawlError as exc:
            return f"Firecrawl crawl failed (HTTP {exc.status_code}): {exc}", None
        except requests.RequestException as exc:
            return f"Firecrawl crawl failed (network error): {exc}", None

        firecrawl_bytes = content_bytes(pages)

        # Every fallback-needing page in this crawl shares one Crawl4AI browser session
        # instead of one launch per page -- see _apply_crawl4ai_fallback_batch's
        # docstring for why that is safe.
        fallback_count = self._apply_crawl4ai_fallback_batch(url, pages)

        # Measured after the batch pass, which mutates page["markdown"] in place: testing
        # a value captured before it ran would fire a redundant root scrape on a crawl
        # the per-page fallback just rescued.
        root_rescued = False
        if content_bytes(pages) < _MIN_USEFUL_BYTES:
            root_pages = self._crawl4ai_root_scrape(url)
            if content_bytes(root_pages) > content_bytes(pages):
                pages = root_pages
                root_rescued = True

        final_bytes = content_bytes(pages)
        if final_bytes == 0:
            return (
                f"Crawl of {url} produced no content.\n"
                f"Firecrawl returned {firecrawl_bytes} B even after retrying with "
                f"waitFor and an anti-bot proxy, and the local Crawl4AI fallback also "
                f"returned nothing.\n"
                f"Likely causes: the site blocks automated clients, its content is "
                f"rendered by JavaScript the scraper did not wait for, or your Firecrawl "
                f"plan is rate-limited or out of credits.\n"
                f"Next: if this is a site you subscribe to, run "
                f"`python -m ibkr_core_mcp.scrape_fallback create-profile {url}` once. "
                f"For IBKR documentation, append `.md` to the page URL instead of "
                f"crawling it.",
                None,
            )

        try:
            manifest = self._web_docs.save_crawl(url, pages)
        except Exception as exc:
            return f"Crawl completed ({len(pages)} pages) but Drive save failed: {exc}", None

        saved = len(manifest["pages"])
        source = "Crawl4AI (Firecrawl returned nothing usable)" if root_rescued else "Firecrawl"
        fallback_line = (
            f"\nCrawl4AI fallback used for {fallback_count} page(s) Firecrawl couldn't fully extract."
            if fallback_count
            else ""
        )
        return (
            f"Crawl complete: saved {saved} page(s) ({final_bytes} B) from {url} to Drive.\n"
            f"Source: {source}\n"
            f"Crawled at: {manifest['crawled_at']}\n"
            f"Pages: "
            + ", ".join(p["url"] for p in manifest["pages"][:10])
            + ("..." if saved > 10 else "")
            + fallback_line,
            None,
        )
```

- [ ] **Step 5: Run the tests**

Run: `pytest tests/claude_tools/test_web_scraping.py -v`
Expected: all passed

- [ ] **Step 6: Lint, type-check, commit**

```bash
ruff format . && ruff check . && mypy
git add ibkr_core_mcp/claude_tools.py tests/claude_tools/test_web_scraping.py
git commit -m "feat(scraper): add Crawl4AI root last resort, stop reporting empty crawls as success

The per-page fallback iterates over the page list, so it could never recover a
crawl that produced no pages — the structural gap behind 'Crawl complete: saved
0 page(s)' on blocked sites. A content-free crawl now scrapes its root URL
locally and, failing that, returns a diagnosis naming the likely cause."
```

---

## Task 10: Expose the overrides on both tool schemas

**Files:**
- Modify: `ibkr_core_mcp/claude_tools.py` — `TOOL_DEFINITIONS` entries at lines 840-905
- Test: `tests/claude_tools/test_tool_descriptions.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/claude_tools/test_tool_descriptions.py`:

```python
def test_scraper_tools_expose_wait_for_and_proxy():
    from ibkr_core_mcp.claude_tools import TOOL_DEFINITIONS

    for name in ("firecrawl_search", "firecrawl_crawl"):
        tool = next(t for t in TOOL_DEFINITIONS if t["name"] == name)
        props = tool["input_schema"]["properties"]
        assert "wait_for_ms" in props
        assert "proxy" in props
        assert props["proxy"]["enum"] == ["basic", "enhanced", "auto"]
        assert name not in tool["input_schema"]["required"]
        assert "wait_for_ms" not in tool["input_schema"]["required"]
        assert "proxy" not in tool["input_schema"]["required"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/claude_tools/test_tool_descriptions.py -k wait_for -v`
Expected: FAILED with `AssertionError: assert 'wait_for_ms' in {...}`

- [ ] **Step 3: Implement**

Add these two properties to **both** the `firecrawl_search` and `firecrawl_crawl` schemas, inside their `properties` dicts:

```python
                "wait_for_ms": {
                    "type": "integer",
                    "description": (
                        "Advanced override: milliseconds to wait for JavaScript rendering "
                        "before extracting. Usually unnecessary — a crawl that comes back "
                        "empty is retried automatically with 3000."
                    ),
                },
                "proxy": {
                    "type": "string",
                    "enum": ["basic", "enhanced", "auto"],
                    "description": (
                        "Advanced override: Firecrawl proxy mode. 'basic' costs 1 credit, "
                        "'enhanced' up to 5, 'auto' retries with enhanced only if basic "
                        "fails. Usually unnecessary — a crawl that comes back empty is "
                        "retried automatically with 'auto'."
                    ),
                },
```

Also update `firecrawl_crawl`'s `timeout_s` description to document the derived default:

```python
                "timeout_s": {
                    "type": "integer",
                    "description": (
                        "Max seconds to wait per attempt. Default scales with max_pages "
                        "(6s per page, clamped to 120-600s). A blocked site runs two "
                        "attempts, so worst-case wall clock is roughly double this."
                    ),
                },
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/claude_tools/ -v`
Expected: all passed

- [ ] **Step 5: Lint, commit**

```bash
ruff format . && ruff check . && mypy
git add ibkr_core_mcp/claude_tools.py tests/claude_tools/test_tool_descriptions.py
git commit -m "feat(scraper): expose wait_for_ms and proxy on both scraper tool schemas"
```

---

## Task 11: Prove it against the host that never worked

**Files:**
- Modify: `tests/test_web_scraper_live.py`

- [ ] **Step 1: Write the live test**

Add to `tests/test_web_scraper_live.py`:

```python
@pytest.mark.integration
def test_crawl_interactivebrokers_returns_real_content():
    from ibkr_core_mcp.web_scraper import FirecrawlClient, content_bytes

    # The host this whole feature exists for. Firecrawl's defaults hit an Akamai
    # edge-block here (152 bytes of error page); the escalated attempt should recover
    # real content. Kept to one page to stay cheap.
    client = FirecrawlClient(os.environ["FIRECRAWL_API_KEY"])
    pages = client.crawl(
        "https://www.interactivebrokers.com/campus/trading-lessons/request-modify-orders/",
        max_pages=1,
        timeout_s=180,
    )

    assert pages, "crawl returned no pages — escalation did not recover the block"
    assert content_bytes(pages) > 5 * 1024
```

Check the top of the file for how `FIRECRAWL_API_KEY` is read and how tests skip without it; match that convention exactly rather than the `os.environ[...]` shown above if the file already has a fixture or skip marker for it.

- [ ] **Step 2: Run it**

Run: `FIRECRAWL_API_KEY=fc-... pytest tests/test_web_scraper_live.py::test_crawl_interactivebrokers_returns_real_content -v -m integration`
Expected: PASSED, with real content returned.

**If it fails**, do not weaken the assertion. It means the escalation did not recover the block, and the design's core premise needs re-examination against `docs/audits/audit-evidence/scrapes/manifest.json`. Report the actual byte count and stop.

- [ ] **Step 3: Commit**

```bash
git add tests/test_web_scraper_live.py
git commit -m "test(scraper): live-verify escalation recovers interactivebrokers.com

The host that has never worked. Firecrawl defaults hit an Akamai edge-block
here; this asserts the escalated attempt returns real content."
```

---

## Task 12: Documentation

**Files:**
- Modify: `docs/web-scraper-reference.md` (already written — remove its status banner)
- Modify: `CLAUDE.md`, `docs/tools-reference.md`

- [ ] **Step 1: Remove the reference doc's status banner**

`docs/web-scraper-reference.md` already exists and documents the finished state. It opens with a blockquote beginning `> **Status.**` warning the reader that the ladder and profile matching may not have landed yet. Delete that entire blockquote — once this plan is complete the warning is false, and a stale warning is worse than none.

Everything else in the doc was written against this plan's implementation. Do not rewrite it; verify it in Step 4.

- [ ] **Step 2: Correct CLAUDE.md**

The scraper paragraph currently reads, in part:

> `FirecrawlClient.crawl()` returns 0 pages on `interactivebrokers.com` (it needs Firecrawl's `waitFor`/`proxy` options, which the client does not expose) and fails silently rather than reporting the block.

Both claims are false after this work. Replace with a sentence stating that the client now escalates automatically and falls back to Crawl4AI, and keep the standing advice to prefer `.md` URLs and `llms.txt` over scraping IBKR at all. Add to the **Pointers** list:

```markdown
- Web scraper (Firecrawl + Crawl4AI, recovery ladder, paywalled-site login profiles,
  per-host quirks, troubleshooting): `docs/web-scraper-reference.md`
```

- [ ] **Step 3: Update tools-reference.md**

Document `wait_for_ms` and `proxy` on both `firecrawl_search` (line 716) and `firecrawl_crawl` (line 730), and correct `firecrawl_crawl`'s `timeout_s` default to the derived formula.

- [ ] **Step 4: Verify every claim**

Re-read the new doc against the code as merged. Every default, clamp, threshold and CLI command in it must match the implementation — this repo has a history of doc-accuracy audits and the reference doc is the thing people will trust.

Run: `pytest -m "not integration"` and confirm the tool count and any numbers quoted in the doc still hold.

- [ ] **Step 5: Commit**

```bash
git add docs/web-scraper-reference.md docs/tools-reference.md CLAUDE.md
git commit -m "docs: add web scraper reference, correct stale CLAUDE.md claims

CLAUDE.md asserted that crawl() does not expose waitFor/proxy and fails
silently on IBKR hosts. Both are false as of this branch."
```

---

## Final verification

- [ ] **Run everything**

```bash
ruff check . && ruff format --check .
mypy
pytest -m "not integration"
FIRECRAWL_API_KEY=fc-... pytest tests/test_web_scraper_live.py -v -m integration
```

Expected: lint clean, mypy clean, full unit suite green, and the live IBKR crawl returning real content.

- [ ] **Confirm the bug is actually gone**

The original symptom was `firecrawl_crawl` on an `interactivebrokers.com` URL reporting `Crawl complete: saved 0 page(s)`. Run that same call through `ClaudeToolkit.execute` with real credentials and confirm it now either returns real content or an explicit diagnosis — never a zero-page success.
