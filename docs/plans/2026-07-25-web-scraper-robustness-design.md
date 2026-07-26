# Web Scraper Robustness — Design Spec

**Date:** 2026-07-25
**Status:** Approved, ready for implementation plan
**Affects:** `ibkr_core_mcp/web_scraper.py`, `ibkr_core_mcp/scrape_fallback.py`,
`ibkr_core_mcp/claude_tools.py`, `docs/`

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

Attempt-level failure leaves `crawl()` by three different routes, each bypassing recovery
differently:

| Route | Code | What the caller sees |
|---|---|---|
| Job status `failed` | `web_scraper.py:407-408` | `raise FirecrawlError` — aborts before any fallback |
| HTTP error mid-poll | `web_scraper.py:359`, `:401` — bare `raise_for_status()` | Raw `requests.HTTPError`; the handler only catches `FirecrawlError`, so it **escapes uncaught** |
| Deadline hit / completed-empty | `web_scraper.py:410-415` | Returns `[]` silently with only a log warning |

There is no single point where "we got nothing" is decided, so there is nowhere to attach
recovery. That is the root cause of the scraper's long-running unreliability.

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
  Staying on v1 keeps this a bug fix rather than a migration.

---

## 3. Core design decision — measure the output, don't classify the failure

An earlier draft of this spec introduced a `CrawlOutcome` dataclass carrying
`status`/`error`/`detail`/`escalated`/`attempts`, plus a nine-row table classifying every way an
attempt could end. It was rejected as over-built, and rightly:

> **You never act on *how* the crawl failed — only on *whether you got content*.**

Blocked, timed out, job-failed, and completed-empty all produce the same next move. So the
decision is a single measurement on the output, not a taxonomy of failures:

```python
_MIN_USEFUL_BYTES = 5 * 1024


def content_bytes(pages: list[dict[str, Any]]) -> int:
    """Total bytes of extracted markdown across a page list."""
    return sum(len((p.get("markdown") or "").encode("utf-8")) for p in pages)
```

One module-level function in `web_scraper.py`, imported by `claude_tools.py`, used at every rung
of the ladder. No new types, no status enum, no parallel error channel — roughly 25 lines of new
client code instead of ~120, with correspondingly fewer places for a bug to live.

### 3.1 Threshold calibration

5 KB is not a guess. Measured from this repo's own scrape cache
(`docs/audits/audit-evidence/scrapes/`):

| Artifact | Bytes | Reality |
|---|---|---|
| IBKR Akamai block page | **152** | failure |
| `firecrawl-crawl-get-endpoint.md` | 12,933 | good content |
| `flex3error.htm` | 16,891 | good content |
| `flex3.htm` | 20,898 | good content |
| IBKR `request-modify-orders` (after stealth retry) | 91,918 | good content |

The failure/success gap spans two orders of magnitude. 5 KB sits ~34× above the largest observed
failure and ~2.5× below the smallest observed success, and is deliberately set high enough to
also catch partial/truncated extractions that returned *something* but plainly not a page.

### 3.2 Keep the best rung, not the last

Every rung's result is scored with the same `content_bytes()`, and the ladder returns the
**largest** result seen, not the most recent:

```python
best = max(candidates, key=content_bytes)
```

This matters because 5 KB is an aggressive threshold: a legitimately short 3 KB page will run the
whole ladder and still measure "too small" at the end. Keeping the best result makes the ladder
monotonic — you can never finish with less than rung 1 already produced, and a Crawl4AI result
that is thinner than Firecrawl's can never silently downgrade the output. It also removes any
need to special-case "small but real" pages: they simply pass through, and the final message
reports the byte count rather than claiming failure.

---

## 4. Architecture — the recovery ladder

```text
crawl(url)
  │
  ├─ Rung 1: Firecrawl, cheap defaults                      ~1 credit/page
  │     └─ content_bytes >= 5 KB? ───────────────────────► return
  │
  ├─ Rung 2: Firecrawl, waitFor=3000 + proxy="auto"         up to 5 credits/page
  │     └─ content_bytes >= 5 KB? ───────────────────────► return best-of(rung 1, rung 2)
  │
  └─ handler: still under threshold
        ├─ per-page Crawl4AI batch (existing behavior)      free
        ├─ Crawl4AI scrapes the root URL, using a saved     free
        │  login profile when one matches the domain (§6)
        └─ report byte counts and which layer won —
           never "Crawl complete: saved 0 page(s)"
```

### 4.1 The single rule

> **Escalate unless the result already carries `_MIN_USEFUL_BYTES` of markdown.**

No outcome-kind carve-outs. A completed-empty crawl, a timed-out crawl, and a `failed` job are
the same event from the caller's perspective and take the same path.

---

## 5. `web_scraper.py` changes

### 5.1 Making an attempt total

Rung 1 must not raise, or there is nothing to measure. This replaces the entire failure-
classification table from the rejected draft:

```python
try:
    pages = self._try_crawl(url, max_pages, timeout_s, scrape_options)
except FirecrawlError as exc:
    if exc.status_code in (401, 402, 429):
        raise                      # account-level — a retry fails identically
    pages = []
except requests.RequestException:
    pages = []
```

**Why 401/402/429 still raise:** a bad key, an empty credit balance, and an active rate-limit are
account-level problems. A slower, more expensive stealth retry cannot fix any of them; it burns
time and money to fail identically, and in the 429 case makes the throttling worse. Raising
`FirecrawlError` preserves `crawl()`'s documented contract, and the handler already catches it
and can still choose the free local Crawl4AI rung — which is exactly the right move when you are
rate-limited or out of credits.

**New:** HTTP 402 must be added to `_raise_for_status`. Today it falls through to
`resp.raise_for_status()` and surfaces as a raw `requests.HTTPError`.

`_try_crawl` is today's `crawl()` body verbatim, with the two bare `raise_for_status()` calls at
`web_scraper.py:359` and `:401` converted to `_raise_for_status()` so every HTTP error becomes a
`FirecrawlError` the block above can classify.

### 5.2 Method surface

```python
_ESCALATION_WAIT_FOR_MS = 3000   # manifest.json 2026-07-02: "--wait-for 3000 --proxy auto succeeded"
_ESCALATION_PROXY = "auto"
_ESCALATION_MIN_TIMEOUT_S = 180
```

- `_scrape_options(*, wait_for_ms=None, proxy=None, timeout_ms=None) -> dict` — one builder used
  by **both** `search()` and `crawl()` so the two endpoints cannot drift. Omits `None` keys, so an
  options-free call produces today's request body byte-for-byte.
- `search(query, limit=5, *, wait_for_ms=None, proxy=None, timeout_ms=None)` — new keyword-only
  params, no escalation loop. Its per-result path already reaches Crawl4AI via `assess_quality`.
- `_resolve_timeout(max_pages, timeout_s) -> int` — see §5.3.
- `_try_crawl(...) -> list[dict]` — one attempt; today's polling/pagination body unchanged.
- `crawl(url, max_pages=50, timeout_s=None, *, wait_for_ms=None, proxy=None) -> list[dict]` — the
  ladder's rungs 1–2 plus best-of selection. **Return type unchanged; source-compatible with
  every existing call site.**

  **Two deliberate behavior changes**, both requiring a docstring update:

  - `timeout_s` becomes `int | None = None`, so an unspecified budget is derived per §5.3 rather
    than fixed at 120. Passing `timeout_s=120` explicitly restores the old value exactly.
  - **`crawl()` no longer raises on a `failed` job.** Today's docstring documents
    `Raises: FirecrawlError — if the crawl job transitions to status "failed"`; under §5.1 that
    case escalates and then returns whatever the ladder produced. `FirecrawlError` is now raised
    only for 401/402/429. This is the intended fix for §1.3's first row — a `failed` job aborting
    before any recovery is precisely the bug — but it *is* a contract change for direct library
    consumers, so it belongs in the release notes, not just the docstring.

### 5.3 Timeout budget

`timeout_s` is explicitly **per attempt**. When not passed:

```python
resolved = min(600, max(120, 6 * max_pages))     # max_pages already clamped to [1, 100]
```

| `max_pages` | resolved `timeout_s` |
|---|---|
| 1–20 | 120 |
| 50 (default) | 300 |
| 100 | 600 |

Rung 2 gets `max(resolved, _ESCALATION_MIN_TIMEOUT_S)`. Stealth is slower by construction —
`waitFor=3000` adds 3s per page and `proxy="auto"` retries a failed basic fetch through the
enhanced proxy — so reusing a budget that just timed out would reproduce the timeout and waste
the credits. The resolved value is logged so it is never a mystery number.

---

## 6. Paywalled sites (FT, WSJ, Bloomberg)

The mechanism already exists and works: `create_profile()` runs Crawl4AI's `BrowserProfiler` in a
real visible browser, the user logs in by hand, and the resulting cookie/localStorage profile is
copied to `~/.ibkr_core/crawl4ai_profiles/<domain>/`. `scrape_batch()` then runs with
`use_managed_browser=True, user_data_dir=<profile>`. **No password is ever seen or stored by this
package** — only the resulting browser session. `_PAYWALL_MARKERS` already carries WSJ/FT/
Bloomberg/Barron's stub phrasing.

```bash
python -m ibkr_core_mcp.scrape_fallback create-profile https://www.ft.com
```

Two gaps to close.

### 6.1 Profile lookup is exact-hostname only

`_safe_domain()` returns the literal lowercased hostname, and `scrape_batch()` checks exactly
`profiles_dir / <that hostname>`. A profile created for `www.ft.com` is therefore **not found**
for a `ft.com` or `markets.ft.com` URL — the scrape silently falls back to anonymous and returns
the paywall stub, with nothing indicating the profile you created exists.

Fix: add `_resolve_profile_dir(profiles_dir, host) -> Path | None`, trying in order:

1. the exact host (`markets.ft.com`)
2. the host with a leading `www.` stripped (`ft.com`)
3. progressively strip the leftmost label while **at least two labels remain**
   (`markets.ft.com` → `ft.com`)

Return the first match, else `None`. `scrape_batch()` uses it in place of the current
`profile_dir.is_dir()` check; `_finalize_fallback_result()`'s "no saved login profile" note uses
it too, so the message can't claim a profile is missing when lookup would have found one.

Two notes on scope: matching only ever broadens *toward the registrable domain*, never toward a
sibling — a profile for `ft.com` can serve `markets.ft.com`, which is intended, and cookie
scoping still applies. Multi-part suffixes (`ft.co.uk`) stop at `co.uk`, which will simply never
match a saved profile; no public-suffix list is worth adding for that.

### 6.2 No visibility into saved profiles

There is no way to list profiles or tell whether a session has expired — expiry presents as a
mysteriously truncated article. Add a `list-profiles` subcommand printing each saved domain, its
path, and its age in days. The CLI already anticipates this: `_main()`'s argparse subparser
structure was kept specifically so a second subcommand could be added without a breaking change.

---

## 7. `claude_tools.py` changes

### 7.1 `_handle_firecrawl_crawl`

1. Call `crawl()` as today — the escalation is now internal to the client, so this call site
   barely changes.
2. Run the existing per-page `_apply_crawl4ai_fallback_batch`.
3. **New:** if `content_bytes(pages) < _MIN_USEFUL_BYTES` *after* step 2, run a single
   `Crawl4AIScraper.scrape(root_url)` and wrap the result as a normal page dict
   (`{"url", "markdown", "metadata": {}}`) so it flows into `save_crawl()` with no special-casing
   downstream. Reuse the existing `_finalize_fallback_result()` so this rung's wording matches
   every other Crawl4AI path. Keep whichever of the two page lists scores higher (§3.2).
   `Crawl4AIUnavailableError` and any scrape exception degrade to "no content", never propagate.

   **Measure after step 2, not before.** `_apply_crawl4ai_fallback_batch` mutates
   `page["markdown"]` in place; testing a value captured before it ran would fire a redundant root
   scrape on a crawl the per-page fallback just rescued.

4. Broaden `except FirecrawlError` to also catch `requests.RequestException`, closing the §1.3
   uncaught-exception route at the handler as well as at the client.
5. Rewrite the result message to report the byte count and which layer produced the content.
   **The string `"Crawl complete: saved 0 page(s)"` becomes unreachable** — a content-free crawl
   returns a diagnosis naming the likely cause (bot-block / JS-render / rate limit) and the next
   step.

### 7.2 Tool schemas

Both `firecrawl_crawl` and `firecrawl_search` gain optional `wait_for_ms` and `proxy` properties,
described as advanced overrides. Neither is required, so existing callers are unaffected.
`firecrawl_crawl`'s `timeout_s` description documents the derived default.

---

## 8. `docs/web-scraper-reference.md` (new)

Modeled on `docs/gateway-auth-reference.md`. Linked from CLAUDE.md's **Pointers** section.

1. **What it is** — the two layers, and which tool to reach for
2. **Configuration** — every env var it touches, plus the standalone-dev 4-var exception
3. **The recovery ladder** — §4's diagram, the single rule, what each rung costs
4. **Every tunable** — `max_pages`, `timeout_s` (with the `6 × max_pages` derivation and clamps),
   `wait_for_ms`, `proxy`, `force_refresh`, `limit`, `save_to_drive`, with defaults
5. **Credit-cost model** — `basic` = 1, `enhanced`/`auto` = up to 5, and exactly where escalation
   can bill
6. **Paywalled sites** — the FT/WSJ/Bloomberg `create-profile` walkthrough, what is and is not
   stored, `list-profiles`, how domain matching resolves (§6.1), and what an expired session looks
   like
7. **Drive cache layout** — folder tree, the 48h manifest reuse rule, `force_refresh`
8. **Per-host quirks table** — leading with: *for IBKR's own docs, don't scrape at all* — append
   `.md` to any `interactivebrokers.com/docs/web-api/` URL, or use their `llms.txt` index. Then
   `interactivebrokers.com` (Akamai edge-block, needs `waitFor` + `proxy`), `ibkrguides.com` and
   `docs.firecrawl.dev` (work on defaults)
9. **Troubleshooting** — symptom → cause → fix
10. **Verified behaviors** — each quirk with its date and evidence link, in the style of
    `docs/ibkr-api-behaviors-reference.md`
11. **API reference** — `FirecrawlClient`, `content_bytes`, `WebDocsStore` signatures

---

## 9. Test plan

TDD per project convention — test first, watch it fail, then implement.

### 9.1 `content_bytes` (`tests/test_web_scraper.py`)

- Sums across pages; treats `None` and missing `markdown` as 0
- Counts UTF-8 **bytes**, not characters (a multi-byte page must not be undercounted)
- Empty list → 0

### 9.2 Escalation

- Rung 2 fires on each under-threshold rung-1 result: zero pages, all-empty markdown,
  timeout-with-nothing, job `failed`, and a 4 KB partial
- Rung 2 does **not** fire when rung 1 clears 5 KB
- Rung 2 does **not** fire on 401, 402, 429 — those still raise `FirecrawlError`
- The escalated request body contains `scrapeOptions.waitFor == 3000` and
  `scrapeOptions.proxy == "auto"`
- Never more than 2 Firecrawl attempts, for any failure shape
- Best-of selection: when rung 2 returns *less* than rung 1, rung 1's pages are returned
- `_resolve_timeout` derivation and both clamps; an explicit `timeout_s` always wins; rung 2 uses
  `max(resolved, 180)`
- `_scrape_options` omits `None` keys — an options-free call produces today's exact request body

### 9.3 Handler (`tests/claude_tools/`)

- Under-threshold crawl triggers exactly one `Crawl4AIScraper.scrape(root_url)` call
- A crawl the per-page batch fallback already rescued triggers **no** root scrape
- Crawl4AI content is saved via `save_crawl` and named in the message
- `"saved 0 page(s)"` never appears in any handler output
- `Crawl4AIUnavailableError` and a raw `requests.HTTPError` both degrade to a diagnosis message

### 9.4 Profile resolution (`tests/test_scrape_fallback.py`)

- Exact host wins when present
- `www.ft.com` profile resolves for `ft.com` and `markets.ft.com`
- Stripping stops at two labels — never returns a bare-TLD match
- No match → `None` → anonymous scrape, and the "no saved profile" note is emitted
- `list-profiles` prints saved domains with ages

### 9.5 Live (`tests/test_web_scraper_live.py`, `@pytest.mark.integration`)

**A real crawl of an `interactivebrokers.com` URL.** This is the test that proves the fix, since
that host is the one that has never worked. Kept cheap: `max_pages=1`.

### 9.6 Existing tests that will need updating

Escalation changes call counts and mock consumption in tests that currently return under-threshold
crawls:

| Test | Why it changes |
|---|---|
| `test_crawl_failed_status_raises` | The job-failed path no longer raises — it escalates, then returns `[]`. Rewrite to assert the escalation and empty return; move the raise assertion to a new 401/402 test. |
| `test_crawl_max_pages_clamped` | Polls `{"status": "completed", "data": []}` → now escalates; `mock_requests.post.call_args` becomes the *escalated* call |
| Any test using `mock_time.monotonic.side_effect = [0.0, 1.0]` | A second poll loop consumes more `monotonic()` values → `StopIteration`. Extend the lists or switch to `itertools.count`. |
| Tests asserting a returned page list under 5 KB | Now trigger escalation; give the mock a second poll response or pad the fixture markdown past the threshold |

`test_crawl_empty_and_error_pages_included` needs its fixture markdown padded past 5 KB;
otherwise its assertions are unaffected.

---

## 10. Risks and trade-offs

- **Worst-case wall clock grows.** With `max_pages=50`: rung 1 (300s) + rung 2 (300s) + Crawl4AI
  (~60s) ≈ 11 minutes for a fully-blocked site, which can exceed an MCP client's call timeout.
  Mitigation: the ladder only reaches that depth when every rung fails, and callers needing bounded
  latency pass `timeout_s` explicitly. Documented in §8 items 4 and 9.
- **5 KB will occasionally over-trigger.** A legitimately short page runs the full ladder and
  spends escalation credits for no gain. Accepted deliberately: §3.2's best-of rule means the
  output is still correct, only the cost and latency are wasted, and the alternative (a lower
  threshold) lets truncated extractions through silently.
- **Escalation costs credits.** Up to 5 per page on rung 2, bounded because it fires only after an
  under-threshold result.
- **v1 remains superseded.** This change deliberately does not migrate to v2 (§2). If v1 is ever
  sunset, `_scrape_options` is the single seam where the migration happens.

---

## 11. Files touched

| File | Change |
|---|---|
| `ibkr_core_mcp/web_scraper.py` | `content_bytes`, `_MIN_USEFUL_BYTES`, `_scrape_options`, `_resolve_timeout`, `_try_crawl`, ladder in `crawl()`, `search()` params, 402 in `_raise_for_status`, `_raise_for_status` at the two bare `raise_for_status()` sites |
| `ibkr_core_mcp/scrape_fallback.py` | `_resolve_profile_dir` + use in `scrape_batch`, `list-profiles` subcommand |
| `ibkr_core_mcp/claude_tools.py` | `_handle_firecrawl_crawl` root last-resort + honest reporting, broadened exception handling, `_finalize_fallback_result` profile-note lookup, two tool schemas |
| `ibkr_core_mcp/__init__.py` | **No change.** `FirecrawlClient`/`WebDocsStore` are not exported today — only `FirecrawlError`/`WebDocsStoreError`. `content_bytes` follows that convention. |
| `docs/web-scraper-reference.md` | **New** — §8 |
| `CLAUDE.md` | Correct the scraper paragraph (it currently asserts `crawl()` "does not expose" `waitFor`/`proxy` and "fails silently" — both false on merge); add Pointers entry |
| `docs/tools-reference.md` | New parameters on both scraper tools |
| `tests/test_web_scraper.py` | §9.1, §9.2, §9.6 |
| `tests/test_scrape_fallback.py` | §9.4 |
| `tests/claude_tools/` | §9.3 |
| `tests/test_web_scraper_live.py` | §9.5 |

---

## 12. Verification

```bash
ruff check . && ruff format --check .
mypy
pytest -m "not integration"
FIRECRAWL_API_KEY=fc-... pytest tests/test_web_scraper_live.py -v -m integration
```

Done means: lint clean, mypy clean, unit suite green, **and the live IBKR crawl returns real
content** — the outcome §1.1 proved is achievable but the code has never delivered.
