# Web Scraping Methodology — reading real sites with the local browser

How to approach a site you have not scraped before, what its failure modes look like from the
outside, and where this project deliberately stops. Companion to
`web-scraper-reference.md`, which documents the four tools themselves.

Every measurement here was taken on this machine and is dated. Every vendor claim carries its
source URL. Where the two disagree, the measurement wins and the disagreement is stated.

---

## 1. The method: change one variable at a time

**Before concluding anything about a new paywalled or protected host, run the four-way
matrix.** Two cells is not enough, and the reason is a real, expensive mistake:

| | no profile | saved login profile |
|---|---|---|
| **headless** | | |
| **visible** | | |

On 2026-07-30, `ft.com` and `wsj.com` produced *the same outward symptom* — a paywalled site
returning something other than the article — from two completely different causes:

| Host | headless + no profile | headless + profile | visible + profile | Cause |
|---|---|---|---|---|
| `ft.com` | 25,238 B barrier page | 1,213 B challenge | **35,394 B full article** | Fingerprint mismatch — fixable in one boolean |
| `wsj.com` | 1 B / HTTP 401 | 1 B / HTTP 401 | 1 B / HTTP 401 | DataDome, upstream of authentication |

WSJ's failure was generalised to "paywalls are blocked". That inference left FT untested for
two days while a one-line fix sat in plain sight. The repo's own phrasing, written the day
before the discovery: **a plausible cause that matches the symptom is still a guess until you
change the other variable.**

A corollary worth stating separately: **a site being reachable is not the same as its content
being readable.** `ft.com`'s home page returned 59,455 B at HTTP 200 anonymously, which made
FT look solved. On an actual article the same configuration returned the paywall barrier page.
Measure the thing you actually want, not a proxy for it.

## 2. Reading the failure — a field guide

Blocked pages rarely announce themselves. Each of these was mistaken for something else here
at least once.

| What you see | What it usually is | Tell |
|---|---|---|
| Exactly **1 B** at `http=401`/`403` | Anti-bot refusing the automated browser at the edge | A byte count that reads like a successful fetch of a short page. **A login profile cannot help — the block precedes authentication.** |
| ~25 KB of plausible page, no article body | The site's **paywall barrier page** | Subscription pricing, "Try unlimited access", offer links. Grades `ambiguous`, not `fallback`. |
| ~1 KB "Security Verification" / "Just a moment" / captcha | A **challenge**, not content | Returns HTTP 200 and looks like a page. The most dangerous shape, because nothing about it is obviously an error. |
| A 44-byte nginx 403 archived as a document | An **error page is still a page** | Crawlers count it. Third instance of this trap in this repo — assume a fourth exists. |
| Full-looking page, article truncated mid-way | **Expired session**, or no profile matched | Check profile *name* and *age*: a profile named `www.example.com` does not serve `example.com`. |
| 0 B, no exception | **Two browsers contending for one profile** | Only one Chrome may hold a `user_data_dir`. Serialised since 2026-07-30. |

Crawl4AI has its own detector for several of these, keyed on *structural* HTML markers —
element IDs, script sources, form actions — rather than keywords, so a page that merely
mentions "CAPTCHA" is not flagged. It covers HTTP 403/429 with short bodies, Cloudflare "Just
a moment", Akamai "Access Denied", PerimeterX, reCAPTCHA/hCaptcha injection, and
Imperva/Incapsula/Sucuri firewall pages.
Source: <https://docs.crawl4ai.com/advanced/anti-bot-and-fallback/>

**This project does not use that detector.** It uses `assess_quality` (word counts + paywall
markers), which predates it and which every tool already branches on. Worth revisiting — the
vendor's covers block shapes ours does not, and the two are complementary rather than
competing.

## 3. The escalation ladder, and where we stop

Crawl4AI offers three tiers, and documents progressive enhancement: start regular + stealth,
escalate to undetected, then combine.
Source: <https://docs.crawl4ai.com/advanced/undetected-browser/>

| Tier | Defeats | This project |
|---|---|---|
| **Regular browser** | Nothing specifically; `--disable-blink-features=AutomationControlled` is on by default | ✅ **what we use** |
| **Stealth mode** (`BrowserConfig(enable_stealth=True)`) | `navigator.webdriver`, plugin emulation, navigator properties, common automation leaks. Partial CDP detection | ❌ not used |
| **Undetected browser** (`UndetectedAdapter`) | Deep browser patches, full CDP detection. Vendor names **Cloudflare and DataDome** explicitly | ❌ **deliberately not used** |

**An honest correction to our own docs.** `web-scraper-reference.md` says of `wsj.com`
"nothing works from here". What is actually true is *nothing we are willing to do* works from
here. Crawl4AI ships a mode aimed precisely at DataDome; we have never tried it, and we are
not going to. That is a **scope decision, not a technical impossibility**, and the two should
not be conflated — a future reader deserves to know which one they are inheriting.

The reasoning for stopping: defeating bot detection is a treadmill (the vendor updates, your
scraper breaks, repeat), and it is detection evasion pursued as its own goal rather than a
side effect of reading something you pay for. The sanctioned route for Dow Jones content is a
Factiva / content-API licence.

**Note what the boundary is not.** Using your own paid login in a real browser is not evasion,
and the visible-browser requirement in §4 is not a stealth technique — it is making a session
consistent with the browser that created it.

## 4. Identity-based crawling — the part we do use

Crawl4AI's "managed browser" model: a persistent profile directory holding cookies and local
storage, so the crawler browses as a real logged-in user. *"If you can see the data in your own
browser, you can automate its retrieval with your genuine identity."*
Source: <https://docs.crawl4ai.com/advanced/identity-based-crawling/>

Two rules govern every profiled fetch here, both measured rather than assumed:

**Visible, not headless.** A profile carries short-lived bot-management cookies minted by the
visible browser that created it — FT's jar holds 15 `__cf_bm` (Cloudflare Bot Management)
entries beside `FTSession_s`. Replaying them headless is a fingerprint mismatch. A profiled
headless fetch is *strictly worse than no profile at all*: it trades the barrier page for a
challenge. The vendor's own stealth example carries the same advice as a bare comment —
`headless=False  # Better for avoiding detection` — without explaining why; the mechanism
above is ours, measured.

**Serialised per profile.** A profile is a real Chrome `user_data_dir` guarded by a
`SingletonLock`. Two concurrent profiled fetches of one domain returned 0 B and 0 B; the same
pair anonymously returned 25,242 B and 25,293 B.

Anonymous fetches are subject to neither — headless, parallel, no lock.

**Name the profile after the registrable domain.** Matching broadens on the URL being fetched,
never on the profile name: a `www.ft.com` directory serves only `www.ft.com`, while `ft.com`
serves `ft.com`, `www.ft.com` and `markets.ft.com`.

## 5. Per-host playbook

| Host class | Example | Approach |
|---|---|---|
| **Static docs / reference** | `docs.crawl4ai.com`, `ibkrguides.com` | Defaults. `crawl_site` to archive, `search_site` to find. ~1.2 s/page. Prefer `.md` URLs where offered. |
| **Intermittent edge-block** | `interactivebrokers.com` (Akamai) | Comes and goes — a 152-byte block observed 2026-07-02, plain success 2026-07-25. Not a permanent property. Retry; the local browser often succeeds where the paid API did not. |
| **Paywall + session** | `ft.com` | `create-profile <registrable-domain>` once, then `fetch_page`. Visible + serialised are automatic. **This class is most sites.** |
| **Edge anti-bot** | `wsj.com` (DataDome) | Out of scope here (§3). Detect and report; do not retry, and do not create a profile expecting it to help — one exists and does not. |
| **Untested paywall** | Bloomberg, Barron's | Assume WSJ-like until measured. **Run the §1 matrix.** Check for HTTP 401 / ~1 B before blaming the profile. |

## 6. Worth adopting, not yet adopted

Non-evasive robustness the vendor documents and we do not use:

- **`wait_until="load"`** on protected sites. The default `domcontentloaded` can return
  *before* the anti-bot sensor finishes — which is a plausible contributor to challenge pages
  and costs nothing to change.
- **`max_retries` + `fallback_fetch_function`** on `CrawlerRunConfig`. The vendor's own tip is
  `max_retries=0` plus a fallback function "if you just want a safety net without burning time
  on retries" — close to this project's temperament.
- **`crawl_stats`** for attribution: how many attempts, which path worked.

Deliberately not adopted: **proxy rotation**. It is the standard next rung and it is aimed at
IP-level blocking, which we have never actually observed — the one real block on record
(IBKR/Akamai) was beaten by the local browser directly.

## 7. What the wider ecosystem uses Crawl4AI for

Context for where this project sits, not endorsements. Common production patterns: LLM data
pipelines and agent tooling (its stated design goal — markdown-first output); CSS/XPath
extraction where HTML is stable, and schema-based LLM extraction where it is not; deep
crawling with URL-pattern and content-type filters plus tag exclusions to cut navigation
noise. A representative worked example crawls the CIA World Factbook with BFS, depth limits
and `LXMLWebScrapingStrategy`, writing one markdown file per URL — structurally the same
shape as `crawl_site` → `WebDocsStore`.

One ecosystem-wide gotcha worth repeating because it bites on every fresh machine:
**`crawl4ai-setup` must be run** after install to fetch the Playwright browsers. Here that is
part of the `[scraper]` extra's setup, and forgetting it produces a failure only at tool-call
time, because every scraper import is lazy.

**This project deliberately does not use LLM-based extraction.** The scraper makes no
Anthropic call at all — with one tool per job there is nothing to arbitrate, and the LLM judge
that used to exist was deleted rather than better-guarded.

## 8. Sources

**This document's own sources were found and read by the tools it documents.** `search_site`
was given `docs.crawl4ai.com` and the query *"identity based crawling saved browser login
profile"*; BM25 returned `/advanced/identity-based-crawling/` at **1.000** and
`/advanced/undetected-browser/` at 0.386. A second query, *"undetected browser anti-bot
detection"*, put `/advanced/undetected-browser/` first at 1.000 and surfaced
`/advanced/anti-bot-and-fallback/` at 0.485 — a page neither query named. `fetch_page` then
read all three (24,850 B / 22,216 B / 17,888 B).

That is the find-then-read split working end to end on a live site, and it is worth more as
evidence than any unit test: the ranking was useful, the fetches were complete, and nothing
needed a second attempt. Scraped 2026-07-30:

- <https://docs.crawl4ai.com/advanced/identity-based-crawling/> — managed browsers, persistent profiles
- <https://docs.crawl4ai.com/advanced/undetected-browser/> — the three tiers, progressive enhancement
- <https://docs.crawl4ai.com/advanced/anti-bot-and-fallback/> — block detection, retries, escalation

Ecosystem survey (web search, 2026-07-30):

- <https://mcavdar.com/blog/crawl4ai-in-action-real-world-use-cases-for-smarter-web-scraping>
- <https://mrscraper.com/blog/crawl4ai-modern-web-crawling-guide>
- <https://47billion.com/blog/web-scraping-for-ai-pipelines-what-actually-works-in-2026/>

Measurements: `web-scraper-reference.md` §11 Live Test Log.
