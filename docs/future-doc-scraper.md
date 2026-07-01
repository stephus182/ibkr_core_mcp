# Future: Documentation Scraper Service

## Problem

External API documentation changes with new releases. Manual copy-paste of authenticated
pages is not maintainable — it cannot detect changes, cannot run on a schedule, and
creates stale citations in docstrings whenever IBKR (or any other dependency) ships updates.

## Scope

A general-purpose web scraper that fetches **all** documentation needed by `ibkr_core_mcp`
and its dependents — not limited to IBKR. Intended targets include:

Firecrawl scrape results (2026-06-30) — what is reachable without auth:

| Source | URL | Firecrawl result | Auth required | Priority |
|---|---|---|---|---|
| IBKR CP API reference | https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/ | **Blocked** (Cloudflare 403) | Yes — IBKR Campus login | High |
| IBKR Web API reference | https://www.interactivebrokers.com/campus/ibkr-api-page/webapi-ref/ | **Blocked** (Cloudflare 403) | Yes — IBKR Campus login | High |
| IBKR Flex Web Service error codes | https://www.ibkrguides.com/clientportal/performanceandstatements/flex3error.htm | **Scraped** — all 21 codes, last updated 2025-10-03 | No | Done |
| IBKR Flex Web Service setup | https://www.ibkrguides.com/clientportal/performanceandstatements/flex3.htm | Nav only (main content auth-gated) | Partial | High |
| Enable Flex Web Service | https://www.ibkrguides.com/clientportal/performanceandstatements/flex-web-service.htm | Nav only (main content auth-gated) | Partial | Medium |
| Configure Flex with AI | https://www.ibkrguides.com/clientportal/configure-flex-with-ai.htm | **Scraped** — full content, last updated 2026-05-07 | No | Low |
| IBKR Campus reporting lessons | https://ibkrcampus.com/trading-lessons/client-portal-reporting/ | Login gate only | Yes | Low |
| IBKR TWS API docs | https://interactivebrokers.github.io/tws-api/ | Not tested | No — public | Medium |
| Anthropic API docs | https://docs.anthropic.com/ | Not tested | No — public | Medium |

## Proposed Architecture

```
ibkr_core_mcp/
  doc_scraper.py          — Playwright auth + extraction engine
  docs/ibkr-api/          — cached output committed to repo
    cpapi-v1/
      trading-accounts.md
      market-data.md
      orders.md
      ...
    webapi-ref/
      ...
    manifest.json         — per-source: scraped-at, content hash, change log
```

**Flow:**
1. `python -m ibkr_core_mcp.doc_scraper refresh [--source ibkr|all]`
2. Playwright headless browser logs into IBKR Campus with website credentials
   (env vars: `IBKR_CAMPUS_USER`, `IBKR_CAMPUS_PASSWORD` — separate from CP Gateway creds)
3. Navigates all API reference pages, extracts endpoint docs as structured Markdown
4. Computes content hash per page — reports what changed since last run
5. Saves to `docs/ibkr-api/`; cached files are committed to git so the team benefits
   without each member running the scraper

**Rate limiting:** Default max once per day per source. `--force` bypasses.

**Optional dependency:** `pip install ibkr_core_mcp[docs]` installs Playwright + Chromium.
Base package stays lightweight — scraper is not imported unless explicitly used.

## Pending Doc Verification Items (blockers for this feature)

The 11 items in `claudia_ui/docs/project-status.md §Pending Doc Verification` are the
first batch to resolve once the scraper is built. Until then, those items are marked
"observed, not documented" in the relevant docstrings.

## TOS Note

Scraping documentation for personal development tooling (no redistribution) is standard
practice. Use conservative rate limits and do not cache behind a public endpoint.
