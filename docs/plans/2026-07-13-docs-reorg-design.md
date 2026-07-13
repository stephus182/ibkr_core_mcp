# Documentation Architecture Cleanup — Design

## Problem

`docs/` had become a flat dump of 25 top-level files plus two parallel, interleaved
conventions for design specs and implementation plans. Only 9 of 25 top-level files were
linked from anywhere (CLAUDE.md's Pointers section); the other 16 were discoverable only by
`ls`/`grep`. Living reference material (how things currently work) and dated point-in-time
records (audits, decisions, plans) sat side by side with no way to tell which was which.
Specs/plans specifically were split across four locations — `docs/*-design.md`,
`docs/plans/`, `docs/superpowers/specs/`, `docs/superpowers/plans/` — used interleaved by
date, not before/after: the root convention was used as recently as 2026-07-11, the
superpowers-skill convention as recently as 2026-07-12.

CLAUDE.md itself was *not* the problem this time — it was already cut from 743 to 218 lines
two days prior (`09bdb7a`, `d606174`) specifically to fix context bloat, and that fix holds.
This cleanup is scoped to `docs/` and does not touch CLAUDE.md.

## Decisions

### Category 1 — Reference (stays flat in `docs/`, hand-indexed)

Living documentation describing current behavior, read on demand, updated in place as the
code changes. Stays exactly where it is — no physical move. Indexed in the new
`docs/README.md` with one line + description each:

| File | Description |
| --- | --- |
| `api-reference.md` | Full reference for all `IBKRClient` methods — request/response shapes, exceptions raised |
| `tools-reference.md` | Full reference for all `ClaudeToolkit` tools (40 core + 2 optional scraper) — parameters, output shapes |
| `api-usage-examples.md` | Per-module usage examples (Setup, Market Data, Technical Indicators, Backtesting, Portfolio Analytics, Claude AI Tool Layer, PineScript Generation) |
| `order-management-examples.md` | Order management code examples (read-only, place/confirm, manual reply-chain control, modify/cancel, GTC quarter-end auto-cancel) |
| `gateway-auth-reference.md` | Gateway login walkthrough, `GatewayManager`, headless `TokenAuth` |
| `flex-query-reference.md` | Historical Trade Data / Flex Queries (one-time setup, usage, constraints) |
| `mcp-server-reference.md` | MCP Server (install, stdio/SSE transports, 44 tools, 4 resources, price alerts, TradingView integration) |
| `ibkr-api-behaviors-reference.md` | Known IBKR API behaviors, verified not assumed |
| `external-docs-reference.md` | Official documentation URLs, all external APIs |
| `consumers.md` | Consuming projects |
| `test-coverage.md` | Current unit/integration test counts, coverage %, run commands |
| `windows-setup.md` | Windows install/run guide — what works out of the box vs. what needs an extra step (Touch ID gate) |

### Category 2 — Design specs & Plans → consolidate into `docs/plans/`

Point-in-time records of what was decided (`*-design.md`) and how it was carried out
(`*-plan.md`), for both features and fixes. Not enumerated in `docs/README.md` — the index
names the directory and the naming convention, not each file, since new ones land every few
days and a hand-list would go stale immediately. Filenames keep their `YYYY-MM-DD-<topic>`
prefix, which makes chronological order equivalent to a plain filename sort — no renaming
needed for that property to hold.

22 files consolidate from 4 current locations into one:

- `docs/*-design.md` (4 files): `2026-05-22-ibkr-core-mcp-design.md`,
  `2026-07-02-claude-tools-audit-design.md`, `2026-07-06-order-reply-confirmation-design.md`,
  `2026-07-08-claude-tools-test-reorg-design.md`
- `docs/plans/*.md` (7 files, already in the target directory, unmoved):
  `2026-06-27-architecture-notes.md`, `2026-06-27-publication-readiness.md`,
  `2026-06-27-v2-architecture-plan.md`, `2026-07-02-claude-tools-audit-plan.md`,
  `2026-07-08-claude-tools-test-reorg-plan.md`, `2026-07-08-docs-accuracy-fixes-plan.md`,
  `2026-07-11-security-fixes-plan.md`
- `docs/superpowers/specs/*.md` (2 files): `2026-06-26-firecrawl-web-scraper-design.md`
  (no rename needed); `2026-05-24-human-auth-order-security.md` → rename to
  `2026-05-24-human-auth-order-security-design.md` (collision fix, see below)
- `docs/superpowers/plans/*.md` (9 files): `2026-05-23-ibkr-core-mcp-phase1.md`,
  `2026-05-23-ibkr-core-mcp-phase2.md`, `2026-05-26-ibkr-core-mcp-phase3.md`,
  `2026-06-26-firecrawl-web-scraper.md`, `2026-07-07-crawl4ai-live-test.md`,
  `2026-07-07-web-docs-cache-check-and-search.md`,
  `2026-07-07-web-scraper-drive-save-live-test.md`, `2026-07-12-order-dialog-cleanup.md`
  (none renamed); `2026-05-24-human-auth-order-security.md` → rename to
  `2026-05-24-human-auth-order-security-plan.md` (collision fix)

**Collision:** `docs/superpowers/specs/` and `docs/superpowers/plans/` both contain a
`2026-05-24-human-auth-order-security.md` (spec and plan sharing an identical filename).
Resolved by adding the `-design` / `-plan` suffix on the move, matching the suffix
convention the root-level files already use.

`docs/README.md` text for this category: *"Point-in-time records of what was decided and
how — a design spec (`*-design.md`) captures the why/what, a plan (`*-plan.md`) captures the
how, for both features and fixes. Filenames are `YYYY-MM-DD-<topic>-{design,plan}.md`;
sorting the directory by filename gives chronological order. These are not living documents
— once written they are not edited to reflect later changes; a later revisit gets a new
dated file. Browse the directory directly rather than looking for an index entry here."*

### Category 3 — Audits → consolidate into `docs/audits/`

Same point-in-time treatment as Plans. 9 files consolidate from `docs/` root:

- `security-audit-2026-05-25.md`, `security-audit-2026-05-26.md`,
  `security-audit-2026-05-27.md`, `security-audit-2026-06-10.md`,
  `security-audit-2026-06-23.md`, `security-audit-2026-07-11.md`
- `claude-tools-audit-2026-07.md` — a single accumulating log, not one-file-per-event;
  still consolidated here since it's the same *kind* of record
- `2026-06-30-quote-access-matrix.md` — reclassified from ambiguous to Audit: its content
  is an investigation triggered by a bug, cross-referencing a "previous audit," despite the
  filename not saying "audit"
- `live-test-log.md` — accumulated record of live-test runs, same nature as the above; as a
  single file (not an open-ended collection), it gets one explicit line in `docs/README.md`
  rather than "browse, don't enumerate" treatment, since one line never goes stale regardless
  of how much the file grows internally

Plus `docs/superpowers/audit-evidence/` (raw JSON/patch/jsonl evidence backing
`claude-tools-audit-2026-07.md`) moves to `docs/audits/audit-evidence/`, alongside the report
it supports.

`docs/README.md` text for this category: *"Point-in-time investigation and verification
records — security audits, code audits, and accumulated test-run logs
([`live-test-log.md`](audits/live-test-log.md)). Same treatment as Plans: dated filenames,
not retroactively edited. `audit-evidence/` holds raw supporting data for the 2026-07
claude_tools.py audit. Browse directly rather than looking for an index entry here."*

### New file — `docs/README.md`

The categorized catalog. GitHub auto-renders this as the `docs/` folder landing page, so it
also solves human/browser discoverability, not just agent lookup. Three sections matching
the categories above (Reference hand-listed with descriptions; Plans and Audits described as
directories/patterns, not enumerated).

### Cleanup

- **Delete `docs/future-doc-scraper.md`.** The problem it described (auth-gated external doc
  scraping) is solved by `web_scraper.py` + `scrape_fallback.py` (Firecrawl primary, Crawl4AI
  fallback with saved-login-profile reuse for paywalled sites). Note for the record: the
  *specific* mechanism it proposed — automatic change-detection/diffing when an external doc
  page updates, via content-hash comparison against a git-committed cache — was never built
  and nothing currently replaces that specific capability. Deleting because the underlying
  need is met by a more general implementation, not because the diffing idea was wrong; if
  automatic change-detection turns out to matter later, it should be re-proposed as its own
  design rather than resurrecting this file.
- **Fix the broken cross-reference in `2026-06-30-quote-access-matrix.md`.** It points to
  `docs/security-audit-2026-06-25.md`, which does not exist. Checked the closest candidate,
  `2026-06-23`: its scope is "13 modified files across correctness, packaging, type safety,
  and test coverage" — a general audit with no mention of quote/conid resolution, so it is
  not a scope match despite being the nearest date. No file anywhere is named or dated
  2026-06-25, and no other file references this specific investigation. Conclusion: the
  referenced audit was never saved under that name (or at all) — this isn't a recoverable
  typo. Fix by replacing the dead link with an honest note (e.g. "Previous audit: none on
  file") rather than guessing a replacement target.

### Cross-links

- Root `README.md` gets one line pointing to `docs/README.md` for the full documentation
  catalog.
- **CLAUDE.md is not modified** — explicit user decision. Its existing Pointers section
  (9 curated fast-path links) stays exactly as-is.

### Going-forward convention (recorded outside CLAUDE.md)

New specs/plans in this repo go in `docs/plans/YYYY-MM-DD-<topic>-{design,plan}.md`, not the
superpowers-skill's own default (`docs/superpowers/specs/`, `docs/superpowers/plans/`).
Since CLAUDE.md is off-limits for recording this, it's captured instead as an auto-memory
entry (`feedback_docs_plan_location.md`, saved 2026-07-13) that Claude reads every session
regardless of project files. The redirect is applied manually at the point a skill's default
path fires — there's no config file the skill itself reads for this. This very document is
the first file placed under the new convention.

## Industry-practice grounding

Checked against current sources rather than relying on training data, consistent with this
project's own "verify against official documentation" convention:

- **Anthropic's Claude Code memory docs** ([code.claude.com/docs/en/memory](https://code.claude.com/docs/en/memory),
  fetched 2026-07-13) confirm `@path` imports "are expanded and loaded into context at
  launch" regardless of file size, and that backtick-wrapping a path keeps it literal —
  exactly what commit `d606174` already applied, now confirmed against the current official
  text rather than commit-message paraphrase. Anthropic's own auto-memory system mirrors the
  structure proposed here: a small capped index (`MEMORY.md`, 200 lines/25KB) plus separate
  topic files read on demand and never loaded at launch — the same shape as
  `docs/README.md` + linked reference docs.
- **Diátaxis** ([diataxis.fr](https://diataxis.fr/)) validates the "Reference" category name
  and definition directly. It would further split that bucket into Reference (pure lookup,
  e.g. `api-reference.md`) vs. How-To (goal-oriented walkthroughs, e.g.
  `api-usage-examples.md`); not adopted here as a 4th top-level category — 12 files doesn't
  justify it yet. Revisit if the Reference bucket grows substantially.
- **Architecture Decision Records** ([adr.github.io](https://adr.github.io/)) validate the
  Plans/Audits treatment: once accepted, a record is immutable — a later revisit produces a
  new dated file that supersedes the old one, not an edit. This repo's git history already
  follows that pattern (audits and design docs are closed/superseded via new commits, never
  rewritten), so no convention change was needed there, only the discoverability layer.
- Not adopted here: Claude Code's first-party `.claude/rules/*.md` mechanism (path-scoped
  frontmatter that deterministically auto-loads a file when Claude touches matching globs —
  more reliable than a hand-written Pointers list, which depends on Claude noticing and
  choosing to read a plain-text pointer). This is a stronger mechanism than what CLAUDE.md
  uses today, but adopting it is a separate project from this one — it restructures
  CLAUDE.md-adjacent config, which is explicitly out of scope here.

## Out of scope

- Any CLAUDE.md edits.
- Adopting `.claude/rules/`.
- Renaming existing dated files beyond the one spec/plan collision fix (preserves git blame
  history for everything else).
- Building automatic change-detection/diffing for external documentation (the capability
  `future-doc-scraper.md` proposed but that was never built).

## Implementation notes

- Use `git mv` for every relocation so history follows the file, rather than delete+recreate.
- 22 files → `docs/plans/`, 9 files + 1 directory → `docs/audits/`, 12 files unmoved,
  1 file deleted, 1 file created (`docs/README.md`), 1 line added to root `README.md`.
