# Web Scraper Robustness — Design Spec

**Date:** 2026-07-25
**Status:** Approved, ready for implementation plan
**Affects:** `ibkr_core_mcp/web_scraper.py`, `ibkr_core_mcp/claude_tools.py`, `docs/`

---

## 1. Problem

`FirecrawlClient.crawl()` returns 0 pages on `interactivebrokers.com` hosts and reports it as
success. The tool output reads:

```text
Crawl complete: saved 0 page(s) from https://www.interactivebrokers.com/... to Drive.
```

Nothing in that message tells the caller the crawl was blocked. The Crawl4AI fallback — the
layer built specifically to recover from blocked scrapes — never runs.

### 1.1 Evidence this is a real, already-diagnosed block

`docs/audits/audit-evidence/scrapes/manifest.json` records three attempts against the same IBKR
URL on 2026-07-02:

| Method | Result |
|---|---|
| `firecrawl` (default options) | **failed** — 152 bytes, "Akamai edge-block error page (Reference #102...), not real content" |
| `webfetch` | **failed** — HTTP 403 Forbidden |
| `firecrawl` with `--wait-for 3000 --proxy auto` | **ok** — 91,918 bytes of real content |

The fix is known and proven against this exact host. It was simply never wired into
`FirecrawlClient`.

### 1.2 Why the safety net never fires

`ClaudeToolkit._apply_crawl4ai_fallback_batch` (`claude_tools.py:2861`) iterates **over the page
list** to decide which pages need Crawl4AI:

```python
for page in pages:
    needs_fallback, ... = self._assess_fallback_need(...)
```

When Firecrawl returns `[]`, there are zero iterations, zero candidates, and an early
`return 0`. **A per-page fallback cannot recover a failure that produces no pages.** This is
structural, not a tuning problem.

### 1.3 Three separate exits, none of which reach the fallback

Attempt-level failure leaves `crawl()` by three different routes, and each one bypasses recovery
in a different way:

| Route | Code | What the caller sees |
|---|---|---|
| Job status `failed` | `web_scraper.py:407-408` | `raise FirecrawlError` — aborts before any fallback |
| HTTP error mid-poll | `web_scraper.py:359`, `:401` — bare `raise_for_status()` | Raw `requests.HTTPError`; the handler only catches `FirecrawlError`, so it **escapes uncaught** |
| Deadline hit / completed-empty | `web_scraper.py:410-415` | Returns `[]` silently with only a log warning |

There is no single point where "we got nothing" is decided, so there is no single point where
recovery can be attached. That is the root cause of the scraper's long-running unreliability, and
fixing it is the core of this design.

### 1.4 A contributing cause: the default timeout is under-budgeted

`timeout_s` is not Firecrawl's timeout — it is *our own polling patience*
(`web_scraper.py:347-415`). The default is 120s for up to 50 pages. A slow, JS-heavy site
routinely exceeds that, so today's default can manufacture a "timeout, 0 pages" result that is
not a block at all.

---

## 2. Verified API facts

Checked against live Firecrawl documentation on 2026-07-25 (per CLAUDE.md's **API Docs First**
rule):

- **Source:** <https://docs.firecrawl.dev/v1/api-reference/endpoint/crawl-post>
- **v1 `scrapeOptions` supports** `waitFor`, `proxy`, `timeout`, `maxAge`, `location`, `actions`,
  `blockAds`, `onlyMainContent`. **No v2 migration is required** to fix this bug.
- **`proxy` accepts** `basic` (fast, basic anti-bot), `enhanced` (sophisticated anti-bot, **up to
  5 credits**), `auto` (try basic, retry with enhanced on failure).
- v1 is documented as superseded by v2 but is functional and carries no published sunset date.
  Staying on v1 keeps this change to a bug fix rather than a migration.

---

## 3. Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | Auto-escalate once, rather than only exposing options | The LLM cannot be relied on to know it must retry with stealth options. Cost is bounded because escalation only fires after a failure. |
| D2 | Crawl4AI the root URL as last resort | Closes the structural gap in §1.2 — a zero-page result now still has a recovery path. |
| D3 | Options on both `crawl()` and `search()`; escalation logic on `crawl()` only | `search()` results already reach Crawl4AI per-result via `assess_quality`, so its structural gap is already covered. |
| D4 | Default `timeout_s` scales with `max_pages` | Fixes §1.4 without making small crawls slow. |
| D5 | No `FIRECRAWL_ESCALATE_PROXY` kill-switch | Spend is bounded by actual failures, and a caller who wants control can pass `proxy` explicitly. YAGNI. |
| D6 | Escalation lives in `FirecrawlClient`, Crawl4AI last-resort in the handler | Respects the layering `web_scraper.py:10-12` already declares: client + Drive persistence only; fallback logic in `scrape_fallback.py`; orchestration in `claude_tools.py`. Fixes the library for **all** consumers, not just `ClaudeToolkit`. |

---

## 4. Architecture — the recovery ladder

```text
crawl_detailed(url)
  │
  ├─ Attempt 1: cheap defaults                              ~1 credit/page
  │     └─ usable content? ──────────────────────────────► return
  │
  ├─ Attempt 2: waitFor=3000, proxy="auto"                  up to 5 credits/page
  │     (only for block-shaped failures — see §5.3)
  │     └─ usable content? ──────────────────────────────► return (escalated=True)
  │
  └─ handler: still no content
        ├─ Crawl4AI scrapes the root URL locally            free
        │     └─ content? ─────────────────────────────────► save + report which layer won
        └─ still nothing ────────────────────────────────► explicit diagnosis, never "saved 0 page(s)"
```

### 4.1 The single rule

> **Escalate unless attempt 1 produced usable content.**

"Usable content" means: at least one returned page whose `markdown` is non-empty after
`.strip()`. No outcome-kind carve-outs — a completed-empty crawl, a timed-out-with-nothing crawl,
and a `failed` job all take the same path, because from the caller's perspective they are the
same event.

The single exception is failures that a stealth retry provably cannot fix (§5.3).

---

## 5. `web_scraper.py` changes

### 5.1 `CrawlOutcome`

```python
@dataclass(frozen=True)
class CrawlOutcome:
    """Result of a crawl, including how it was obtained and why it failed."""

    pages: list[dict[str, Any]]      # same page dicts crawl() returns today
    status: str                      # "completed" | "timeout" | "failed" | "api_error"
    escalated: bool                  # attempt 2 (waitFor + proxy) ran
    attempts: int                    # 1 or 2
    timeout_s: int                   # the resolved per-attempt budget actually used
    detail: str                      # human-readable failure reason; "" when clean
    error: FirecrawlError | None     # preserved so crawl() can re-raise it

    @property
    def has_content(self) -> bool:
        return any((p.get("markdown") or "").strip() for p in self.pages)
```

### 5.2 Method surface

```python
_ESCALATION_WAIT_FOR_MS = 3000   # manifest.json 2026-07-02: "--wait-for 3000 --proxy auto succeeded"
_ESCALATION_PROXY = "auto"
_ESCALATION_MIN_TIMEOUT_S = 180
```

- `_scrape_options(*, wait_for_ms=None, proxy=None, timeout_ms=None) -> dict` — one builder used
  by **both** `search()` and `crawl()`, so the two endpoints cannot drift. Omits keys that are
  `None` so the request body matches today's byte-for-byte when no options are passed.
- `search(query, limit=5, *, wait_for_ms=None, proxy=None, timeout_ms=None)` — new keyword-only
  params, no escalation loop.
- `_resolve_timeout(max_pages, timeout_s) -> int` — see §5.4.
- `_attempt_crawl(url, max_pages, timeout_s, scrape_options) -> CrawlOutcome` — **total**: always
  returns a `CrawlOutcome`, never raises for a job-level or transport problem. This is the heart
  of the fix.
- `crawl_detailed(url, max_pages=50, timeout_s=None, *, wait_for_ms=None, proxy=None) -> CrawlOutcome`
  — runs attempt 1, applies the §4.1 rule, optionally runs attempt 2.
- `crawl(url, max_pages=50, timeout_s=None)` — **return type unchanged, source-compatible for
  every existing caller.** Becomes:

  ```python
  outcome = self.crawl_detailed(...)
  if outcome.error is not None:
      raise outcome.error
  return outcome.pages
  ```

  This preserves the documented `Raises: FirecrawlError` contract for existing library consumers
  while letting `crawl_detailed()` hand the same failure to the handler as data.

  **One deliberate behavior change:** `timeout_s` becomes `int | None = None` on both `crawl()`
  and `crawl_detailed()`, so an unspecified budget is derived per §5.4 rather than fixed at 120.
  Every existing call site still compiles and runs unchanged; a caller that relied on the
  implicit 120s now gets a budget scaled to its `max_pages`. That is the point of D4 — passing
  `timeout_s=120` explicitly restores the old value exactly.

### 5.3 Failure classification

`_attempt_crawl` maps every possible ending to one row:

| Condition | `status` | `error` set | Escalate? |
|---|---|---|---|
| Completed, ≥1 non-empty markdown | `completed` | no | no — we have content |
| Completed, 0 pages or all-empty | `completed` | no | **yes** |
| Deadline hit, ≥1 non-empty markdown | `timeout` | no | no — partial content is content |
| Deadline hit, no content | `timeout` | no | **yes** |
| Job status `failed` | `failed` | `FirecrawlError("Crawl job failed: …")` | **yes** |
| HTTP 401 (invalid key) | `api_error` | `FirecrawlError(…, 401)` | **no** |
| HTTP 402 (out of credits) | `api_error` | `FirecrawlError(…, 402)` | **no** |
| HTTP 429 after backoff exhausted | `api_error` | `FirecrawlError(…, 429)` | **no** |
| Other HTTP / `requests` exception | `api_error` | `FirecrawlError(str(exc), status_code or None)` | **no** |

**Why the bottom four do not escalate:** they are account-level or transport-level problems. A
slower, more expensive retry through a stealth proxy cannot fix a bad key, an empty credit
balance, an active rate-limit, or a connection failure to `api.firecrawl.dev` — it only burns
time and money to fail identically, and in the 429 case makes the throttling worse. These skip
straight to the free, local Crawl4AI rung, which is genuinely the right move when you are rate
limited or out of credits.

**New:** HTTP 402 must be added to `_raise_for_status`. Today it falls through to
`resp.raise_for_status()` and surfaces as a raw `requests.HTTPError`.

### 5.4 Timeout budget

`timeout_s` is explicitly **per attempt**. When not passed:

```python
resolved = min(600, max(120, 6 * max_pages))     # max_pages already clamped to [1, 100]
```

| `max_pages` | resolved `timeout_s` |
|---|---|
| 1–20 | 120 |
| 50 (default) | 300 |
| 100 | 600 |

The escalated attempt gets `max(resolved, _ESCALATION_MIN_TIMEOUT_S)`. Stealth is slower by
construction — `waitFor=3000` adds 3s per page and `proxy="auto"` retries a failed basic fetch
through the enhanced proxy — so reusing a budget that just timed out would reproduce the timeout
and waste the credits.

The resolved value is logged and carried on `CrawlOutcome.timeout_s` so it is never a mystery
number to a caller who did not pass one.

---

## 6. `claude_tools.py` changes

### 6.1 `_handle_firecrawl_crawl`

1. Call `crawl_detailed()` instead of `crawl()`.
2. Run the existing per-page `_apply_crawl4ai_fallback_batch` as today.
3. **New:** if the page list is *still* content-free, run a single
   `Crawl4AIScraper.scrape(root_url)` and wrap the result as a normal page dict
   (`{"url", "markdown", "metadata": {}}`) so it flows into `save_crawl()` with no special-casing
   downstream. Reuse the existing `_finalize_fallback_result()` to turn the scrape outcome into
   markdown + note, so this rung's wording matches every other Crawl4AI path.
   `Crawl4AIUnavailableError` and any scrape exception degrade to "no content", never propagate.

   **Check emptiness after step 2, not before.** `outcome.has_content` reflects Firecrawl's
   original pages; `_apply_crawl4ai_fallback_batch` mutates `page["markdown"]` in place and may
   have already filled them in. Testing the stale value would fire a redundant root scrape on a
   crawl the per-page fallback just rescued. Re-evaluate the mutated list.
4. Broaden the `except FirecrawlError` to also catch `requests.RequestException` and
   `Exception`, so the §1.3 uncaught-exception route is closed at the handler as well as at the
   client.
5. Rewrite the result message. It always reports which layer produced the content, whether
   escalation ran, and the resolved timeout. **The string `"Crawl complete: saved 0 page(s)"`
   becomes unreachable** — a zero-content crawl returns a diagnosis naming the likely cause
   (bot-block / JS-render / rate limit) and the next step.

### 6.2 Tool schemas

Both `firecrawl_crawl` and `firecrawl_search` gain optional `wait_for_ms` and `proxy`
properties, described as advanced overrides. Neither is required; the defaults mean "let the
client decide", so existing callers are unaffected. `firecrawl_crawl`'s `timeout_s` description
changes to document the derived default.

---

## 7. `docs/web-scraper-reference.md` (new)

Modeled on `docs/gateway-auth-reference.md`. Linked from CLAUDE.md's **Pointers** section.

1. **What it is** — the two layers, and which tool to reach for
2. **Configuration** — every env var it touches, plus the standalone-dev 4-var exception
3. **The recovery ladder** — §4's diagram, the single rule, what each rung costs
4. **Every tunable** — `max_pages`, `timeout_s` (with the `6 × max_pages` derivation and clamps),
   `wait_for_ms`, `proxy`, `force_refresh`, `limit`, `save_to_drive`, with defaults
5. **Credit-cost model** — `basic` = 1, `enhanced`/`auto` = up to 5, and exactly where escalation
   can bill
6. **Drive cache layout** — folder tree, the 48h manifest reuse rule, `force_refresh`
7. **Per-host quirks table** — leading with: *for IBKR's own docs, don't scrape at all* — append
   `.md` to any `interactivebrokers.com/docs/web-api/` URL, or use their `llms.txt` index. Then
   `interactivebrokers.com` (Akamai edge-block, needs `waitFor` + `proxy`), `ibkrguides.com` and
   `docs.firecrawl.dev` (work on defaults), paywalled sites (`create-profile`)
8. **Troubleshooting** — symptom → cause → fix
9. **Verified behaviors** — each quirk with its date and evidence link, in the style of
   `docs/ibkr-api-behaviors-reference.md`
10. **API reference** — `FirecrawlClient`, `CrawlOutcome`, `WebDocsStore` signatures

---

## 8. Test plan

TDD per project convention — test first, watch it fail, then implement.

### 8.1 New unit tests (`tests/test_web_scraper.py`)

- Escalation fires on each no-content outcome: completed-empty, completed-all-whitespace,
  timeout-with-zero-pages, job `failed`
- Escalation does **not** fire when attempt 1 returns content, including timeout-with-partial
- Escalation does **not** fire on 401, 402, 429
- The escalated request body actually contains `scrapeOptions.waitFor == 3000` and
  `scrapeOptions.proxy == "auto"`
- Never more than 2 attempts, for any failure shape
- `_resolve_timeout` derivation and both clamps; an explicit `timeout_s` always wins
- Escalated attempt uses `max(resolved, 180)`
- `crawl()` still returns a plain `list[dict]` and still raises `FirecrawlError` on a failed job
- `_scrape_options` omits `None` keys — an options-free call produces today's exact request body

### 8.2 New handler tests (`tests/claude_tools/`)

- Zero-content crawl triggers exactly one `Crawl4AIScraper.scrape(root_url)` call
- Crawl4AI content is saved via `save_crawl` and named in the message
- `"saved 0 page(s)"` never appears in any handler output
- `Crawl4AIUnavailableError` and a raw `requests.HTTPError` both degrade to a diagnosis message
  rather than propagating

### 8.3 Live test (`tests/test_web_scraper_live.py`, `@pytest.mark.integration`)

**A real crawl of an `interactivebrokers.com` URL.** This is the test that proves the fix, since
that host is the one that has never worked. Kept cheap: `max_pages=1`.

### 8.4 Existing tests that will need updating

The escalation changes call counts and mock consumption in tests that currently return
zero-content crawls:

| Test | Why it changes |
|---|---|
| `test_crawl_failed_status_raises` | Still raises, but only after the escalated attempt — needs a second poll response |
| `test_crawl_max_pages_clamped` | Polls `{"status": "completed", "data": []}` → now escalates; `mock_requests.post.call_args` becomes the *escalated* call |
| Any test using `mock_time.monotonic.side_effect = [0.0, 1.0]` | A second poll loop consumes more `monotonic()` values → `StopIteration`. Extend the lists or switch to `itertools.count`. |

`test_crawl_empty_and_error_pages_included` is unaffected — it returns a page with real markdown,
so `has_content` is true and no escalation occurs.

---

## 9. Risks and trade-offs

- **Worst-case wall clock grows.** With `max_pages=50`: attempt 1 (300s) + attempt 2 (300s) +
  Crawl4AI (~60s) ≈ 11 minutes for a fully-blocked site. This can exceed an MCP client's call
  timeout. Mitigation: the ladder only reaches that depth when every rung fails, and callers
  needing bounded latency pass `timeout_s` explicitly. Documented in §7 items 4 and 8.
- **Escalation costs credits.** Up to 5 per page on attempt 2. Bounded because it fires only
  after a zero-content result (D5).
- **v1 remains superseded.** This change deliberately does not migrate to v2 (§2). If v1 is ever
  sunset, `_scrape_options` is the single seam where the migration happens.

---

## 10. Files touched

| File | Change |
|---|---|
| `ibkr_core_mcp/web_scraper.py` | `CrawlOutcome`, `_scrape_options`, `_resolve_timeout`, `_attempt_crawl`, `crawl_detailed`, `crawl()` wrapper, `search()` params, 402 in `_raise_for_status` |
| `ibkr_core_mcp/claude_tools.py` | `_handle_firecrawl_crawl` last-resort + honest reporting, broadened exception handling, two tool schemas |
| `ibkr_core_mcp/__init__.py` | **No change.** `FirecrawlClient` and `WebDocsStore` are not exported today — only `FirecrawlError`/`WebDocsStoreError` are. `CrawlOutcome` follows that convention and is imported from `ibkr_core_mcp.web_scraper` directly. |
| `docs/web-scraper-reference.md` | **New** — §7 |
| `CLAUDE.md` | Correct the scraper paragraph (it currently asserts `crawl()` "does not expose" `waitFor`/`proxy` and "fails silently" — both false on merge); add Pointers entry |
| `docs/tools-reference.md` | New parameters on both scraper tools |
| `tests/test_web_scraper.py` | §8.1 + §8.4 |
| `tests/claude_tools/` | §8.2 |
| `tests/test_web_scraper_live.py` | §8.3 |

---

## 11. Verification

```bash
ruff check . && ruff format --check .
mypy
pytest -m "not integration"
FIRECRAWL_API_KEY=fc-... pytest tests/test_web_scraper_live.py -v -m integration
```

Done means: lint clean, mypy clean, unit suite green, **and the live IBKR crawl returns real
content** — the outcome §1.1 proved is achievable but the code has never delivered.
