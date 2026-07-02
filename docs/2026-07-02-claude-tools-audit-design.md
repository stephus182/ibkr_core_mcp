# claude_tools.py Full Audit — Design

**Status:** Design approved 2026-07-02. Audit to be planned and executed next; implementation of findings is deliberately deferred.
**Scope repos:** `ibkr_core_mcp` (audited in depth) + `claudia_ui` (measured as the consumer).

## Problem

`ibkr_core_mcp/claude_tools.py` is 2,516 lines holding 42 tool schemas, 42 handlers, shared
helpers, and dispatch — the largest module in the package by 2×. ClaudIA (claudia_ui, Chainlit)
sends every schema (`toolkit.tools` + TradingView tools + local tools) on **every** Anthropic API
call, and already feels slow. The approved scraping-RAG pipeline (claudia_ui spec
`2026-07-01-scraping-rag-pipeline-design.md`, layer 2) would add 3 more tools on top.

Before any architectural change, we audit: is the toolkit actually the cause of the slowness,
does the god class need splitting (and how), and are the 42 tool descriptions accurate against
official documentation. The audit produces **evidence-backed recommendations for future work,
not immediate changes** — reflection over speed, per the project owner's direction.

**Confirmed fact motivating urgency (found during design):** claudia_ui uses **no prompt
caching** — no `cache_control` anywhere in `claudia/agent.py`. The full static prefix (system
prompt + 42+ tool schemas) is re-processed uncached on every message *and* every tool-loop turn.

## Prior art this audit builds on

- `docs/plans/2026-06-27-architecture-notes.md` — existing target split (7-module `tools/`
  package, composition "Option A"), deferred until a new tool domain lands. Names the
  cross-domain call graph as a mandatory precondition. This audit validates or amends it.
- `claudia_ui/docs/superpowers/specs/2026-07-01-scraping-rag-pipeline-design.md` — layer-2
  web-docs tools (`list_web_docs`, `read_web_doc`, `delete_web_docs`) whose sequencing this
  audit must decide.
- CLAUDE.md **docs-first rule** — all documentation claims verified against official sources
  via scrape, with cited URLs; never from memory.

## Decisions the audit must produce (D1–D5)

Criteria are fixed here, before data collection, so conclusions cannot be retro-fitted.

| # | Decision | Criteria |
|---|---|---|
| D1 | Where ClaudIA slowness comes from | Attribute ≥80% of measured wall-clock per turn to named components (API prompt processing, streaming, handler/IBKR time, Chainlit); state what prompt caching fixed and what remains. |
| D2 | Split go/no-go + final architecture | **Go** if the cross-domain dependency graph is cleanly cuttable (few/acyclic edges) AND the findings table shows the monolith actively causing defects or inconsistency. **No-go (defer again)** if evidence shows the problem is cosmetic. |
| D3 | Runtime tool-exposure strategy for claudia_ui | Compare "all tools + prompt caching" vs. "per-context tool profiles" on measured token cost and observed wrong-tool selections. Profiles recommended only if caching alone leaves a material problem. |
| D4 | Sequencing: split vs. scraping-RAG layer 2 | Decided by D2's outcome plus the measured token delta of adding the 3 layer-2 tools. |
| D5 | Per-tool documentation verdicts | 42-row verdict table (accurate / fix / enrich / trim) with citations and proposed replacement text + token delta for every non-accurate verdict. |

## Parallel track (not part of the audit): P0 prompt caching

The owner has already decided to implement prompt caching in claudia_ui (`cache_control` on the
tools block and system prompt) as an immediate quick win. It is a small, self-contained change
in the claudia_ui repo, executed **separately from and before** the audit's measurement rerun,
and it feeds Workstream 1c's before/after comparison. It is not a recommendation of this audit —
it is already decided — and it must not bias the architectural reflection.

## Workstream 1 — Quantify (numbers before opinions)

**1a. Token weight of the tool surface** — measured with the Anthropic `count_tokens` API
(exact, not estimated):

- Each of the 42 schemas individually → ranked cost-per-tool table.
- The full `tools=` payload exactly as claudia_ui sends it (`toolkit.tools` + TradingView
  `extra_tools` + `_LOCAL_TOOLS` from `claudia/agent.py:296`).
- The system prompt (rides on every call; part of the same static prefix).
- Projection: same totals with the 3 scraping-RAG layer-2 tools added (for D4).

**1b. Latency decomposition of a real ClaudIA session** — temporary timestamp instrumentation
around existing call sites in `claudia/agent.py` (no architecture changes), over a scripted
session of 6–8 representative messages (market-data fetch, backtest, multi-tool question,
plain chat). Per turn, decompose wall-clock into:

1. time-to-first-token from the Anthropic API (prompt processing — where the uncached prefix
   shows up),
2. total stream duration,
3. each `toolkit.execute()` handler duration (IBKR gateway time lives here),
4. tool-loop turn count per user message (each turn = one more full-prefix API call),
5. Chainlit render/overhead (residual).

**1c. Baseline vs. cached comparison** — run the same scripted session before and after the P0
prompt-caching change lands. Converts D1 from inference to measurement.

**Output:** measurements appendix — ranked token table, latency decomposition, before/after
caching comparison.

## Workstream 2 — Code audit (the architecture evidence)

**2a. Per-tool review** — every handler gets a row under one rubric:

- **Correctness** — logic bugs, unhandled error paths, convention adherence
  (`_first_account_id()` / `_all_account_ids()`, `conid`/`con_id` fallback per CLAUDE.md).
- **Consistency** — `_safe_error` usage, return-shape uniformity, naming, parameter validation.
- **Weight** — LOC, duplication with sibling handlers (shared-helper candidates).
- **Test coverage** — which tests exercise it, unit vs. integration, and which handlers have none.

**2b. Cross-domain dependency graph** — trace every handler→handler call inside `ClaudeToolkit`
plus shared-helper usage; output an explicit graph (mermaid). This is the precondition the
2026-06-27 notes require before any split; it confirms the proposed 7-module boundaries or shows
where they cut through a dependency.

**2c. Structural assessment** — evaluate the existing target (tools/ package, composition
Option A) against alternatives, including splitting *definitions* and *handlers* on different
axes (definitions grouped for exposure profiles, handlers grouped by dependency), and how the
layer-2 tools slot into each candidate. Trade-offs written down for each; one recommended;
none implemented.

**2d. Plumbing review** — `execute()` dispatch, the figure-return signature question
(2026-06-27 notes, pre-v1.0 bug #1), `ClaudeToolkit` construction cost, thread-safety notes for
the single-event-loop assumption (`claude_tools.py:868`).

**Output:** 42-row findings table, dependency graph, structural recommendation with trade-offs.

## Workstream 3 — Docs verification (Firecrawl-backed, docs-first rule)

**3a. Tool → authoritative-source map** — table pinning each of the 42 tools to the exact
official doc page/section that governs it (IBKR Client Portal API, Flex Web Service, WebSocket,
Google Drive v3, Firecrawl, Crawl4AI — canonical URLs already listed in CLAUDE.md).

**3b. Scrape and diff** — per tool, Firecrawl-scrape its doc page and compare against: the
schema `description` Claude sees, the `input_schema` (names, types, enums, defaults), and the
handler docstring. Target the incident class from CLAUDE.md's table: wrong endpoints, invented
error semantics, missing constraints (pagination limits, T+1 delays, two-call patterns,
subscription requirements).

**3c. Verdict per tool** — one of:

- **Accurate** — matches docs; leave alone.
- **Fix** — factually wrong vs. official docs (highest priority: misleads Claude every call).
- **Enrich** — missing load-bearing behavior that improves tool choice. Token-conscious:
  rich for complex tools, minimal for trivial ones (owner's explicit direction).
- **Trim** — verbose description whose tokens buy no tool-choice accuracy.

**3d. Evidence discipline** — every verdict cites source URL + scrape date per the CLAUDE.md
protocol. Scrapes saved via the existing `firecrawl_*`/`web_docs` machinery where useful —
which also exercises the audited tools in the real world. If Firecrawl fails on a page, the
Crawl4AI fallback applies; if both fail, the tool's verdict is marked **unverified**, never
guessed.

**Output:** source map + 42-row verdict table with citations and proposed replacement text
(with token delta) for every Fix/Enrich/Trim.

## Synthesis and report

One synthesis pass turns the three workstreams' evidence into D1–D5 using the pre-committed
criteria above.

**Deliverable:** `docs/claude-tools-audit-2026-07.md` (in `ibkr_core_mcp`, following the
`docs/security-audit-*.md` convention), decision
summary (D1–D5) up top, then appendices:

- A. Ranked token table + payload totals + layer-2 projection (WS1a)
- B. Latency decomposition + before/after caching (WS1b/1c)
- C. Code findings table, 42 rows (WS2a)
- D. Cross-domain dependency graph, mermaid (WS2b)
- E. Structural assessment + recommendation (WS2c/2d)
- F. Tool → source map (WS3a)
- G. Docs verdict table, 42 rows, with citations (WS3b/3c)

## Execution order

1. WS1a token math (fast, no dependencies) → 2. WS3 docs verification (scrape-heavy, can run
alongside code reading) → 3. WS2 code audit → 4. WS1b baseline latency run → 5. P0 caching lands
in claudia_ui (parallel track) → 6. WS1c cached rerun → 7. Synthesis + report.

Steps 1–3 have no ordering constraints between them; 4 must precede 6; 6 requires 5.

## Out of scope (YAGNI)

- Implementing the split, exposure profiles, doc-text changes, or layer 2 — all are *outputs*
  of the audit, planned separately after the owner reviews the report.
- `mcp_server.py` internals and the MCP-only alert tools (`add_price_alert`,
  `get_price_alerts`).
- TradingView bridge tools — counted in the token math (they ride in the same payload), not
  audited.
- Any change to the order-security gates (out of audit scope entirely; governed by
  `2026-05-24-human-auth-order-security.md`).

## Risks

1. **Instrumentation noise** — single-run latency numbers are noisy; the scripted session runs
   3× per condition and reports medians.
2. **Docs behind login/paywall** — some IBKR pages may not scrape cleanly; fallback to
   Crawl4AI, else mark **unverified** rather than assert.
3. **Live-session variability** — IBKR gateway latency varies by market hours; baseline and
   cached runs happen under comparable conditions and record timestamps.
4. **Token-count drift** — `count_tokens` results are model-specific; record the model ID used
   (must match ClaudIA's configured model).

## References

- Anthropic — prompt caching: https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching
- Anthropic — token counting: https://docs.anthropic.com/en/docs/build-with-claude/token-counting
- IBKR Client Portal API: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
- Full per-domain doc URL table: CLAUDE.md § "IBKR API Reference — Docs First"
- Prior architecture design: `docs/plans/2026-06-27-architecture-notes.md`
- Scraping-RAG pipeline spec: `claudia_ui/docs/superpowers/specs/2026-07-01-scraping-rag-pipeline-design.md`
- Code touch points: `ibkr_core_mcp/claude_tools.py` (`ClaudeToolkit`, `TOOL_DEFINITIONS`,
  `execute()`), `claudia_ui/claudia/agent.py` (`_all_tools`, streaming loop).
