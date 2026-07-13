> ## Documentation Index
>
> Fetch the complete documentation index at: [/llms.txt](https://docs.firecrawl.dev/llms.txt)
>
> Use this file to discover all available pages before exploring further.

[Skip to main content](https://docs.firecrawl.dev/migrate-to-v2#content-area)

[Firecrawl Docs home page![light logo](https://mintcdn.com/firecrawl/iilnMwCX-8eR1yOO/logo/logo.png?fit=max&auto=format&n=iilnMwCX-8eR1yOO&q=85&s=c45b3c967c19a39190e76fe8e9c2ed5a)![dark logo](https://mintcdn.com/firecrawl/iilnMwCX-8eR1yOO/logo/logo-dark.png?fit=max&auto=format&n=iilnMwCX-8eR1yOO&q=85&s=3fee4abe033bd3c26e8ad92043a91c17)](https://firecrawl.dev/)

v1English

Search...

Ctrl K

- [Status](https://firecrawl.betteruptime.com/)
- [Support](mailto:help@firecrawl.com)
- [Sign Up](https://www.firecrawl.dev/signin?utm_source=firecrawl_docs&utm_medium=nav_bar&utm_content=sign_up)
- [firecrawl/firecrawl\\
\\
142,774](https://github.com/firecrawl/firecrawl "firecrawl/firecrawl")
- [firecrawl/firecrawl\\
\\
142,774](https://github.com/firecrawl/firecrawl "firecrawl/firecrawl")

Search...

Navigation

Get Started

Migrating from v1 to v2

[Documentation](https://docs.firecrawl.dev/introduction) [SDKs](https://docs.firecrawl.dev/sdks/overview) [Integrations](https://www.firecrawl.dev/app) [API Reference](https://docs.firecrawl.dev/v1/api-reference/introduction)

- [Playground](https://firecrawl.dev/playground)
- [Blog](https://firecrawl.dev/blog)
- [Community](https://discord.gg/firecrawl)
- [Changelog](https://firecrawl.dev/changelog)

### Get Started

- [Introduction](https://docs.firecrawl.dev/introduction)
- [MCP Server](https://docs.firecrawl.dev/mcp-server)
- [Migrating from v1 to v2](https://docs.firecrawl.dev/migrate-to-v2)
- [Advanced Scraping Guide](https://docs.firecrawl.dev/advanced-scraping-guide)
- Plans and Billing


### Standard Features

- Scrape

- [Crawl](https://docs.firecrawl.dev/features/crawl)
- [Map](https://docs.firecrawl.dev/features/map)
- [Search](https://docs.firecrawl.dev/features/search)

### Agentic Features

- [FIRE-1 (Beta)](https://docs.firecrawl.dev/agents/fire-1)

### Webhooks

- [Overview](https://docs.firecrawl.dev/webhooks/overview)
- [Event Types](https://docs.firecrawl.dev/webhooks/events)
- [Security](https://docs.firecrawl.dev/webhooks/security)
- [Testing](https://docs.firecrawl.dev/webhooks/testing)

### Dashboard

- [Overview](https://docs.firecrawl.dev/dashboard)

### Contributing

- [Open Source vs Cloud](https://docs.firecrawl.dev/contributing/open-source-or-cloud)
- [Running Locally](https://docs.firecrawl.dev/contributing/guide)
- [Self-hosting](https://docs.firecrawl.dev/contributing/self-host)

## On this page

- [Overview](https://docs.firecrawl.dev/migrate-to-v2#overview)
  - [Key Improvements](https://docs.firecrawl.dev/migrate-to-v2#key-improvements)
- [Quick migration checklist](https://docs.firecrawl.dev/migrate-to-v2#quick-migration-checklist)
- [SDK surface (v2)](https://docs.firecrawl.dev/migrate-to-v2#sdk-surface-v2)
  - [JS/TS](https://docs.firecrawl.dev/migrate-to-v2#js%2Fts)
  - [Method name changes (v1 → v2)](https://docs.firecrawl.dev/migrate-to-v2#method-name-changes-v1-%E2%86%92-v2)
  - [Python (sync)](https://docs.firecrawl.dev/migrate-to-v2#python-sync)
  - [Method name changes (v1 → v2)](https://docs.firecrawl.dev/migrate-to-v2#method-name-changes-v1-%E2%86%92-v2-2)
  - [Python (async)](https://docs.firecrawl.dev/migrate-to-v2#python-async)
- [Formats and scrape options](https://docs.firecrawl.dev/migrate-to-v2#formats-and-scrape-options)
  - [JSON format](https://docs.firecrawl.dev/migrate-to-v2#json-format)
  - [Screenshot format](https://docs.firecrawl.dev/migrate-to-v2#screenshot-format)
- [Crawl options mapping (v1 → v2)](https://docs.firecrawl.dev/migrate-to-v2#crawl-options-mapping-v1-%E2%86%92-v2)
- [Crawl prompt + params preview](https://docs.firecrawl.dev/migrate-to-v2#crawl-prompt-%2B-params-preview)

![Firecrawl](https://docs.firecrawl.dev/logo/light.svg)![Firecrawl](https://docs.firecrawl.dev/logo/dark.svg)

### Ready to build?

Start getting web data for free and scale seamlessly as your project expands. **No credit card needed.**

[Start for free](https://www.firecrawl.dev/signin?utm_source=firecrawl_docs&utm_medium=docs_card&utm_content=start_for_free) [See our plans](https://www.firecrawl.dev/pricing?utm_source=firecrawl_docs&utm_medium=docs_card&utm_content=see_our_plans)

Get Started

# Migrating from v1 to v2

Copy page

Key changes, mappings, and before/after snippets to upgrade your integration to v2.

Copy page

## [​](https://docs.firecrawl.dev/migrate-to-v2\#overview)  Overview

### [​](https://docs.firecrawl.dev/migrate-to-v2\#key-improvements)  Key Improvements

- **Faster by default**: Requests are cached with `maxAge` defaulting to 2 days, and sensible defaults like `blockAds`, `skipTlsVerification`, and `removeBase64Images` are enabled.
- **New summary format**: You can now specify `"summary"` as a format to directly receive a concise summary of the page content.
- **Updated JSON extraction**: JSON extraction and change tracking now use an object format: `{ type: "json", prompt, schema }`. The old `"extract"` format has been renamed to `"json"`.
- **Enhanced screenshot options**: Use the object form: `{ type: "screenshot", fullPage, quality, viewport }`.
- **New search sources**: Search across `"news"` and `"images"` in addition to web results by setting the `sources` parameter.
- **Smart crawling with prompts**: Pass a natural-language `prompt` to crawl and the system derives paths/limits automatically. Use the new /crawl/params-preview endpoint to inspect the derived options before starting a job.

## [​](https://docs.firecrawl.dev/migrate-to-v2\#quick-migration-checklist)  Quick migration checklist

- Replace v1 client usage with v2 clients:
  - JS: `const firecrawl = new Firecrawl({ apiKey: 'fc-YOUR-API-KEY' })`
  - Python: `firecrawl = Firecrawl(api_key='fc-YOUR-API-KEY')`
  - API: use the new `https://api.firecrawl.dev/v2/` endpoints.
- Update formats:
  - Use `"summary"` where needed
  - JSON mode: Use `{ type: "json", prompt, schema }` for JSON extraction
  - Screenshot and Screenshot@fullPage: Use screenshot object format when specifying options
- Adopt standardized async flows in the SDKs:
  - Crawls: `startCrawl` \+ `getCrawlStatus` (or `crawl` waiter)
  - Batch: `startBatchScrape` \+ `getBatchScrapeStatus` (or `batchScrape` waiter)
  - Extract: `startExtract` \+ `getExtractStatus` (or `extract` waiter)
- Crawl options mapping (see below)
- Check crawl `prompt` with `/crawl/params-preview`

## [​](https://docs.firecrawl.dev/migrate-to-v2\#sdk-surface-v2)  SDK surface (v2)

### [​](https://docs.firecrawl.dev/migrate-to-v2\#js/ts)  JS/TS

#### [​](https://docs.firecrawl.dev/migrate-to-v2\#method-name-changes-v1-%E2%86%92-v2)  Method name changes (v1 → v2)

**Scrape, Search, and Map**

| v1 (Firecrawl) | v2 (Firecrawl) |
| --- | --- |
| `scrapeUrl(url, ...)` | `scrape(url, options?)` |
| `search(query, ...)` | `search(query, options?)` |
| `mapUrl(url, ...)` | `map(url, options?)` |

**Crawling**

| v1 | v2 |
| --- | --- |
| `crawlUrl(url, ...)` | `crawl(url, options?)` (waiter) |
| `asyncCrawlUrl(url, ...)` | `startCrawl(url, options?)` |
| `checkCrawlStatus(id, ...)` | `getCrawlStatus(id)` |
| `cancelCrawl(id)` | `cancelCrawl(id)` |
| `checkCrawlErrors(id)` | `getCrawlErrors(id)` |

**Batch Scraping**

| v1 | v2 |
| --- | --- |
| `batchScrapeUrls(urls, ...)` | `batchScrape(urls, opts?)` (waiter) |
| `asyncBatchScrapeUrls(urls, ...)` | `startBatchScrape(urls, opts?)` |
| `checkBatchScrapeStatus(id, ...)` | `getBatchScrapeStatus(id)` |
| `checkBatchScrapeErrors(id)` | `getBatchScrapeErrors(id)` |

**Extraction**

| v1 | v2 |
| --- | --- |
| `extract(urls?, params?)` | `extract(args)` |
| `asyncExtract(urls, params?)` | `startExtract(args)` |
| `getExtractStatus(id)` | `getExtractStatus(id)` |

**Other / Removed**

| v1 | v2 |
| --- | --- |
| `generateLLMsText(...)` | (not in v2 SDK) |
| `checkGenerateLLMsTextStatus(id)` | (not in v2 SDK) |
| `crawlUrlAndWatch(...)` | `watcher(jobId, ...)` |
| `batchScrapeUrlsAndWatch(...)` | `watcher(jobId, ...)` |

* * *

### [​](https://docs.firecrawl.dev/migrate-to-v2\#python-sync)  Python (sync)

#### [​](https://docs.firecrawl.dev/migrate-to-v2\#method-name-changes-v1-%E2%86%92-v2-2)  Method name changes (v1 → v2)

**Scrape, Search, and Map**

| v1 | v2 |
| --- | --- |
| `scrape_url(...)` | `scrape(...)` |
| `search(...)` | `search(...)` |
| `map_url(...)` | `map(...)` |

**Crawling**

| v1 | v2 |
| --- | --- |
| `crawl_url(...)` | `crawl(...)` (waiter) |
| `async_crawl_url(...)` | `start_crawl(...)` |
| `check_crawl_status(...)` | `get_crawl_status(...)` |
| `cancel_crawl(...)` | `cancel_crawl(...)` |

**Batch Scraping**

| v1 | v2 |
| --- | --- |
| `batch_scrape_urls(...)` | `batch_scrape(...)` (waiter) |
| `async_batch_scrape_urls(...)` | `start_batch_scrape(...)` |
| `get_batch_scrape_status(...)` | `get_batch_scrape_status(...)` |
| `get_batch_scrape_errors(...)` | `get_batch_scrape_errors(...)` |

**Extraction**

| v1 | v2 |
| --- | --- |
| `extract(...)` | `extract(...)` |
| `start_extract(...)` | `start_extract(...)` |
| `get_extract_status(...)` | `get_extract_status(...)` |

**Other / Removed**

| v1 | v2 |
| --- | --- |
| `generate_llms_text(...)` | (not in v2 SDK) |
| `get_generate_llms_text_status(...)` | (not in v2 SDK) |
| `watch_crawl(...)` | `watcher(job_id, ...)` |

* * *

### [​](https://docs.firecrawl.dev/migrate-to-v2\#python-async)  Python (async)

- `AsyncFirecrawl` mirrors the same methods (all awaitable).

## [​](https://docs.firecrawl.dev/migrate-to-v2\#formats-and-scrape-options)  Formats and scrape options

- Use string formats for basics: `"markdown"`, `"html"`, `"rawHtml"`, `"links"`, `"summary"`, `"images"`.
- Instead of `parsePDF` use `parsers: [ { "type": "pdf" } | "pdf" ]`.
- Use object formats for JSON, change tracking, and screenshots:

### [​](https://docs.firecrawl.dev/migrate-to-v2\#json-format)  JSON format

Node

Python

cURL

```
const formats = [ {\
  "type": "json",\
  "prompt": "Extract the company mission from the page."\
}];

doc = firecrawl.scrape(url, { formats });
```

### [​](https://docs.firecrawl.dev/migrate-to-v2\#screenshot-format)  Screenshot format

Node

Python

cURL

```
// Screenshot format (JS)
const formats = [ { "type": "screenshot", "fullPage": true, "quality": 80, "viewport": { "width": 1280, "height": 800 } } ];

doc = firecrawl.scrape(url, { formats });
```

## [​](https://docs.firecrawl.dev/migrate-to-v2\#crawl-options-mapping-v1-%E2%86%92-v2)  Crawl options mapping (v1 → v2)

| v1 | v2 |
| --- | --- |
| `allowBackwardCrawling` | (removed) use `crawlEntireDomain` |
| `maxDepth` | (removed) use `maxDiscoveryDepth` |
| `ignoreSitemap` (bool) | `sitemap` (e.g., `"only"`, `"skip"`, or `"include"`) |
| (none) | `prompt` |

## [​](https://docs.firecrawl.dev/migrate-to-v2\#crawl-prompt-+-params-preview)  Crawl prompt + params preview

See crawl params preview examples:

Node

Python

cURL

```
import { Firecrawl } from 'firecrawl';

const firecrawl = new Firecrawl({ apiKey: "fc-YOUR-API-KEY" });

const params = await firecrawl.crawlParamsPreview('https://docs.firecrawl.dev', 'Extract docs and blog');
console.log(params);
```

[Suggest edits](https://github.com/firecrawl/firecrawl-docs/edit/main/migrate-to-v2.mdx) [Raise issue](https://github.com/firecrawl/firecrawl-docs/issues/new?title=Issue%20on%20docs&body=Path:%20/migrate-to-v2)

[Firecrawl MCP Server\\
\\
Previous](https://docs.firecrawl.dev/mcp-server) [Advanced Scraping Guide\\
\\
Next](https://docs.firecrawl.dev/advanced-scraping-guide)

Ctrl+I

[Firecrawl Docs home page![light logo](https://mintcdn.com/firecrawl/iilnMwCX-8eR1yOO/logo/logo.png?fit=max&auto=format&n=iilnMwCX-8eR1yOO&q=85&s=c45b3c967c19a39190e76fe8e9c2ed5a)![dark logo](https://mintcdn.com/firecrawl/iilnMwCX-8eR1yOO/logo/logo-dark.png?fit=max&auto=format&n=iilnMwCX-8eR1yOO&q=85&s=3fee4abe033bd3c26e8ad92043a91c17)](https://firecrawl.dev/)

[discord](https://discord.gg/firecrawl) [github](https://github.com/firecrawl/firecrawl) [linkedin](https://www.linkedin.com/company/firecrawl) [x](https://x.com/firecrawl)

[Get credentials](https://docs.firecrawl.dev/ai-onboarding) [Agent onboarding (SKILL.md)](https://www.firecrawl.dev/agent-onboarding/SKILL.md) [Agent auth (auth.md)](https://www.firecrawl.dev/auth.md) [Agent docs (llms.txt)](https://docs.firecrawl.dev/llms.txt) [Full docs (llms-full.txt)](https://docs.firecrawl.dev/llms-full.txt) [MCP server](https://docs.firecrawl.dev/mcp-server)

[discord](https://discord.gg/firecrawl) [github](https://github.com/firecrawl/firecrawl) [linkedin](https://www.linkedin.com/company/firecrawl) [x](https://x.com/firecrawl)

[Powered byThis documentation is built and hosted on Mintlify, a developer documentation platform](https://www.mintlify.com/?utm_campaign=poweredBy&utm_medium=referral&utm_source=firecrawl)