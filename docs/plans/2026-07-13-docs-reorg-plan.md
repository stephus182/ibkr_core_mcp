# Documentation Architecture Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize `docs/` per `docs/plans/2026-07-13-docs-reorg-design.md` — 12 reference
files stay flat, 22 design/plan files consolidate into `docs/plans/`, 9 audit files + 1
evidence directory consolidate into `docs/audits/`, one dead file is deleted, one dead link is
fixed, and a new `docs/README.md` catalog is created.

**Architecture:** This is a file-move task, not a code-feature task — there is no code under
test. "Verification" steps use `git status`/`ls`/`grep` instead of `pytest` to confirm each
move landed correctly and nothing references a now-stale path. All relocations use `git mv`
so history follows the file. A discovery made while scoping this plan (approved by the user,
not in the original design doc): ~28 in-repo comments/docstrings/links outside `docs/`
(`SECURITY.md`, several `ibkr_core_mcp/*.py` files, several `tests/*.py` files, and
`scripts/audit/*.py`) point at files this plan moves. Task 6 fixes those. Two lookalike
matches in `gdrive_auth.py`/`test_gdrive_auth.py` point at a **different repo** (`claudia_ui`)
and are explicitly left untouched.

**Tech Stack:** Plain `git mv`, `grep`, and manual markdown editing. No build step.

---

## Pre-flight

- [ ] **Step 1: Confirm clean working tree**

```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
git status --porcelain
```

Expected: empty output. If not empty, stop and ask the user before proceeding — do not move
files on top of uncommitted work.

- [ ] **Step 2: Snapshot the current file inventory for later diffing**

```bash
git ls-files docs/ | sort > /tmp/docs-before.txt
wc -l /tmp/docs-before.txt
```

Expected: 41 lines (25 top-level + 8 in `docs/plans/` incl. the design doc itself + 2 in
`docs/superpowers/specs/` + 9 in `docs/superpowers/plans/` + 26 under
`docs/superpowers/audit-evidence/` including the `scrapes/` subdir — exact count isn't the
point, this file is just a diff baseline for Step-by-step verification later).

---

### Task 1: Move Audits (Category 3) into `docs/audits/`

**Files:**
- Move: 6 `docs/security-audit-2026-*.md` files → `docs/audits/`
- Move: `docs/claude-tools-audit-2026-07.md` → `docs/audits/claude-tools-audit-2026-07.md`
- Move: `docs/2026-06-30-quote-access-matrix.md` → `docs/audits/2026-06-30-quote-access-matrix.md`
- Move: `docs/live-test-log.md` → `docs/audits/live-test-log.md`
- Move: `docs/superpowers/audit-evidence/` (directory, 26 files incl. `scrapes/`) → `docs/audits/audit-evidence/`

`git mv` creates destination directories automatically, so there's no separate `mkdir` step.

- [ ] **Step 1: Move the 9 audit files**

```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
git mv docs/security-audit-2026-05-25.md docs/audits/security-audit-2026-05-25.md
git mv docs/security-audit-2026-05-26.md docs/audits/security-audit-2026-05-26.md
git mv docs/security-audit-2026-05-27.md docs/audits/security-audit-2026-05-27.md
git mv docs/security-audit-2026-06-10.md docs/audits/security-audit-2026-06-10.md
git mv docs/security-audit-2026-06-23.md docs/audits/security-audit-2026-06-23.md
git mv docs/security-audit-2026-07-11.md docs/audits/security-audit-2026-07-11.md
git mv docs/claude-tools-audit-2026-07.md docs/audits/claude-tools-audit-2026-07.md
git mv docs/2026-06-30-quote-access-matrix.md docs/audits/2026-06-30-quote-access-matrix.md
git mv docs/live-test-log.md docs/audits/live-test-log.md
```

- [ ] **Step 2: Move the audit-evidence directory**

```bash
git mv docs/superpowers/audit-evidence docs/audits/audit-evidence
```

- [ ] **Step 3: Verify the moves**

```bash
ls docs/audits/ | sort
find docs/audits/audit-evidence -type f | wc -l
```

Expected: `docs/audits/` lists exactly the 9 files above plus the `audit-evidence/` directory;
the evidence file count matches what `find docs/superpowers/audit-evidence -type f | wc -l`
reported before the move (26, including `scrapes/`'s 13 files and the `.keep` file).

- [ ] **Step 4: Commit**

```bash
git add -A docs/audits docs/superpowers
git commit -m "docs: consolidate audits and evidence into docs/audits/"
```

---

### Task 2: Move Design specs & Plans (Category 2) into `docs/plans/`, resolving the filename collision

**Files:**
- Move: 4 `docs/*-design.md` files → `docs/plans/`
- Move: `docs/superpowers/specs/2026-06-26-firecrawl-web-scraper-design.md` → `docs/plans/` (no rename)
- Move: `docs/superpowers/specs/2026-05-24-human-auth-order-security.md` → `docs/plans/2026-05-24-human-auth-order-security-design.md` (collision fix)
- Move: 8 `docs/superpowers/plans/*.md` files → `docs/plans/` (no rename)
- Move: `docs/superpowers/plans/2026-05-24-human-auth-order-security.md` → `docs/plans/2026-05-24-human-auth-order-security-plan.md` (collision fix)

The 7 files already in `docs/plans/` (`2026-06-27-architecture-notes.md`,
`2026-06-27-publication-readiness.md`, `2026-06-27-v2-architecture-plan.md`,
`2026-07-02-claude-tools-audit-plan.md`, `2026-07-08-claude-tools-test-reorg-plan.md`,
`2026-07-08-docs-accuracy-fixes-plan.md`, `2026-07-11-security-fixes-plan.md`) and this plan's
own design doc (`2026-07-13-docs-reorg-design.md`) are already in place — nothing to do for
those.

- [ ] **Step 1: Move the 4 root-level `*-design.md` files**

```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
git mv docs/2026-05-22-ibkr-core-mcp-design.md docs/plans/2026-05-22-ibkr-core-mcp-design.md
git mv docs/2026-07-02-claude-tools-audit-design.md docs/plans/2026-07-02-claude-tools-audit-design.md
git mv docs/2026-07-06-order-reply-confirmation-design.md docs/plans/2026-07-06-order-reply-confirmation-design.md
git mv docs/2026-07-08-claude-tools-test-reorg-design.md docs/plans/2026-07-08-claude-tools-test-reorg-design.md
```

- [ ] **Step 2: Move `docs/superpowers/specs/`, applying the collision rename**

```bash
git mv docs/superpowers/specs/2026-06-26-firecrawl-web-scraper-design.md docs/plans/2026-06-26-firecrawl-web-scraper-design.md
git mv docs/superpowers/specs/2026-05-24-human-auth-order-security.md docs/plans/2026-05-24-human-auth-order-security-design.md
```

- [ ] **Step 3: Move `docs/superpowers/plans/`, applying the collision rename**

```bash
git mv docs/superpowers/plans/2026-05-23-ibkr-core-mcp-phase1.md docs/plans/2026-05-23-ibkr-core-mcp-phase1.md
git mv docs/superpowers/plans/2026-05-23-ibkr-core-mcp-phase2.md docs/plans/2026-05-23-ibkr-core-mcp-phase2.md
git mv docs/superpowers/plans/2026-05-26-ibkr-core-mcp-phase3.md docs/plans/2026-05-26-ibkr-core-mcp-phase3.md
git mv docs/superpowers/plans/2026-06-26-firecrawl-web-scraper.md docs/plans/2026-06-26-firecrawl-web-scraper.md
git mv docs/superpowers/plans/2026-07-07-crawl4ai-live-test.md docs/plans/2026-07-07-crawl4ai-live-test.md
git mv docs/superpowers/plans/2026-07-07-web-docs-cache-check-and-search.md docs/plans/2026-07-07-web-docs-cache-check-and-search.md
git mv docs/superpowers/plans/2026-07-07-web-scraper-drive-save-live-test.md docs/plans/2026-07-07-web-scraper-drive-save-live-test.md
git mv docs/superpowers/plans/2026-07-12-order-dialog-cleanup.md docs/plans/2026-07-12-order-dialog-cleanup.md
git mv docs/superpowers/plans/2026-05-24-human-auth-order-security.md docs/plans/2026-05-24-human-auth-order-security-plan.md
```

- [ ] **Step 4: Verify no collision remains and the count is right**

```bash
git ls-files docs/plans | wc -l
ls docs/plans/2026-05-24-human-auth-order-security*
find docs/superpowers -type f -not -name ".DS_Store"
```

Expected: `git ls-files docs/plans` (tracked files only, so it's unaffected by any untracked
scratch files sitting in the directory) reports **23** — 7 pre-existing + the
`2026-07-13-docs-reorg-design.md` design doc (8 total before this task) + 15 newly moved in
Steps 1–3 (4 + 2 + 9). The third command prints **nothing** — confirming `docs/superpowers/`
holds no tracked files left. The `2026-05-24-human-auth-order-security*` glob shows exactly
`-design.md` and `-plan.md`, no bare unsuffixed file.

- [ ] **Step 5: Remove the now-empty `docs/superpowers/` tree and its stray `.DS_Store`**

```bash
git status --porcelain docs/superpowers
find docs/superpowers -type d -empty -delete 2>/dev/null
rm -f docs/superpowers/.DS_Store
find docs/superpowers -mindepth 0 2>/dev/null
```

Expected: `git status --porcelain docs/superpowers` prints nothing (the `.DS_Store` was
already gitignored/untracked, so removing it doesn't touch git state). The final `find` prints
nothing — `docs/superpowers` itself is gone.

- [ ] **Step 6: Commit**

```bash
git add -A docs/plans docs/superpowers
git commit -m "docs: consolidate design specs and plans into docs/plans/"
```

---

### Task 3: Delete `docs/future-doc-scraper.md`

**Files:**
- Delete: `docs/future-doc-scraper.md`

- [ ] **Step 1: Delete via git**

```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
git rm docs/future-doc-scraper.md
```

- [ ] **Step 2: Verify**

```bash
ls docs/future-doc-scraper.md 2>&1
```

Expected: `No such file or directory`.

- [ ] **Step 3: Commit**

```bash
git commit -m "docs: delete future-doc-scraper.md, superseded by web_scraper.py + scrape_fallback.py"
```

---

### Task 4: Fix the dead cross-reference in `quote-access-matrix.md`

**Files:**
- Modify: `docs/audits/2026-06-30-quote-access-matrix.md` (moved in Task 1, so edit it at its new path)

- [ ] **Step 1: Replace the dead link with an honest note**

Current line 9 (verified during scoping, before Task 1's move):
```
**Previous audit:** `docs/security-audit-2026-06-25.md`
```

This points at a file that has never existed anywhere in this repo's history. The closest
candidate by date, `2026-06-23`, is a general audit ("13 modified files across correctness,
packaging, type safety, and test coverage") with no mention of quote/conid resolution — not a
scope match. Replace with:
```
**Previous audit:** none on file
```

- [ ] **Step 2: Verify the edit**

```bash
grep -n "Previous audit" docs/audits/2026-06-30-quote-access-matrix.md
```

Expected: `**Previous audit:** none on file` — no reference to `2026-06-25` remains.

- [ ] **Step 3: Commit**

```bash
git add docs/audits/2026-06-30-quote-access-matrix.md
git commit -m "docs: fix dead previous-audit link in quote-access-matrix.md"
```

---

### Task 5: Fix the one living-reference link broken by the move

**Files:**
- Modify: `docs/test-coverage.md`

`docs/test-coverage.md` is a Category-1 Reference doc (stays flat in `docs/`, updated in
place). It links to `live-test-log.md` as a same-directory relative link
(`` [`docs/live-test-log.md`](live-test-log.md) ``). Task 1 moved `live-test-log.md` into
`docs/audits/`, so this link now 404s. This is the one Reference-doc link the move actually
breaks — other internal doc-to-doc mentions found during scoping are inside point-in-time
Plan/Audit documents, which the design doc explicitly treats as immutable once written, so
those are intentionally left as-is.

- [ ] **Step 1: Confirm the current broken link**

```bash
grep -n "live-test-log" docs/test-coverage.md
```

Expected: `[`docs/live-test-log.md`](live-test-log.md)` on line 6 (or nearby).

- [ ] **Step 2: Fix the relative path**

Change:
```
[`docs/live-test-log.md`](live-test-log.md)
```
to:
```
[`docs/audits/live-test-log.md`](audits/live-test-log.md)
```

- [ ] **Step 3: Verify**

```bash
grep -n "live-test-log" docs/test-coverage.md
```

Expected: link target is `audits/live-test-log.md`.

- [ ] **Step 4: Commit**

```bash
git add docs/test-coverage.md
git commit -m "docs: fix test-coverage.md link to moved live-test-log.md"
```

---

### Task 6: Fix in-repo references outside `docs/` that point at moved/deleted files

**Files:**
- Modify: `SECURITY.md`
- Modify: `ibkr_core_mcp/claude_tools.py`
- Modify: `ibkr_core_mcp/client.py`
- Modify: `ibkr_core_mcp/flex_query.py`
- Modify: `ibkr_core_mcp/scrape_fallback.py`
- Modify: `ibkr_core_mcp/backtest.py`
- Modify: `tests/test_backtest.py`
- Modify: `tests/test_gateway.py`
- Modify: `tests/test_client_live.py`
- Modify: `tests/test_flex_query.py`
- Modify: `tests/test_client.py`
- Modify: `tests/test_alerts_live.py`
- Modify: `tests/claude_tools/test_flex.py`
- Modify: `tests/claude_tools/test_alerts.py`
- Modify: `tests/claude_tools/test_account.py`
- Modify: `scripts/audit/dump_tool_texts.py`
- Modify: `scripts/audit/count_tool_tokens.py`
- Modify: `scripts/audit/sortino_calmar_worked_example.py`
- Modify: `scripts/audit/dep_graph.py` (this one is an actual hardcoded write path, not just a comment)

**Explicitly NOT modified:** `ibkr_core_mcp/gdrive_auth.py:7` and `tests/test_gdrive_auth.py:4`
both mention `docs/superpowers/specs/2026-07-10-gdrive-auth-dedup-design.md` — that path is
annotated `(claudia_ui repo)` in both places, i.e. it names a file in a *different* repository
that this reorg does not touch. Leave both lines exactly as they are.

All substitutions are literal path replacements:
- `docs/security-audit-2026-07-11.md` → `docs/audits/security-audit-2026-07-11.md`
- `docs/security-audit-2026-05-25.md` → `docs/audits/security-audit-2026-05-25.md`
- `docs/security-audit-2026-06-10.md` → `docs/audits/security-audit-2026-06-10.md`
- `docs/claude-tools-audit-2026-07.md` → `docs/audits/claude-tools-audit-2026-07.md`
- `docs/superpowers/audit-evidence/` → `docs/audits/audit-evidence/`
- `docs/live-test-log.md` → `docs/audits/live-test-log.md`

- [ ] **Step 1: Apply the substitutions**

```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp

files=(
  SECURITY.md
  ibkr_core_mcp/claude_tools.py
  ibkr_core_mcp/client.py
  ibkr_core_mcp/flex_query.py
  ibkr_core_mcp/scrape_fallback.py
  ibkr_core_mcp/backtest.py
  tests/test_backtest.py
  tests/test_gateway.py
  tests/test_client_live.py
  tests/test_flex_query.py
  tests/test_client.py
  tests/test_alerts_live.py
  tests/claude_tools/test_flex.py
  tests/claude_tools/test_alerts.py
  tests/claude_tools/test_account.py
  scripts/audit/dump_tool_texts.py
  scripts/audit/count_tool_tokens.py
  scripts/audit/sortino_calmar_worked_example.py
  scripts/audit/dep_graph.py
)

for f in "${files[@]}"; do
  sed -i '' \
    -e 's#docs/security-audit-2026-07-11\.md#docs/audits/security-audit-2026-07-11.md#g' \
    -e 's#docs/security-audit-2026-05-25\.md#docs/audits/security-audit-2026-05-25.md#g' \
    -e 's#docs/security-audit-2026-06-10\.md#docs/audits/security-audit-2026-06-10.md#g' \
    -e 's#docs/claude-tools-audit-2026-07\.md#docs/audits/claude-tools-audit-2026-07.md#g' \
    -e 's#docs/superpowers/audit-evidence/#docs/audits/audit-evidence/#g' \
    -e 's#docs/live-test-log\.md#docs/audits/live-test-log.md#g' \
    "$f"
done
```

Note: `sed -i ''` (empty string after `-i`) is the BSD/macOS form used by this repo's
environment (Darwin) — do not drop the `''`, it would otherwise treat the next `-e` as the
backup-suffix argument and corrupt the edit.

- [ ] **Step 2: Verify no stale outside-docs references remain (except the two intentional exceptions)**

```bash
grep -rn --include="*.md" --include="*.py" -E "docs/security-audit-2026-[0-9-]+\.md|docs/claude-tools-audit-2026-07\.md|docs/superpowers/audit-evidence|docs/live-test-log\.md" . --exclude-dir=.git --exclude-dir=docs --exclude-dir=.claude
```

Expected: only two lines print, both containing `docs/superpowers/specs/2026-07-10-gdrive-auth-dedup-design.md (claudia_ui repo)` — in `ibkr_core_mcp/gdrive_auth.py` and
`tests/test_gdrive_auth.py`. If anything else prints, a substitution was missed — fix it before
continuing.

- [ ] **Step 3: Confirm the edits didn't touch runtime behavior — run the affected test files**

```bash
pytest tests/test_backtest.py tests/test_gateway.py tests/test_flex_query.py tests/test_client.py tests/claude_tools/test_flex.py tests/claude_tools/test_alerts.py tests/claude_tools/test_account.py -m "not integration" -q
```

Expected: all pass. These edits only touched comment/docstring text, never executable
strings, so no behavior change is expected — this run is a safety net, not a prediction of
failure.

- [ ] **Step 4: Full unit suite as a final safety net**

```bash
pytest -m "not integration" -q
```

Expected: same pass count as the repo had before this plan started (no regressions from a
docs-only change set).

- [ ] **Step 5: Commit**

```bash
git add SECURITY.md ibkr_core_mcp/ tests/ scripts/audit/
git commit -m "docs: repoint in-repo references to moved audit docs and evidence"
```

---

### Task 7: Create `docs/README.md`

**Files:**
- Create: `docs/README.md`

This is the categorized catalog described in the design doc: Reference hand-listed with
descriptions, Plans and Audits described as directories/conventions (not enumerated).

- [ ] **Step 1: Write the file**

```markdown
# ibkr_core_mcp Documentation

This directory holds three kinds of documentation. See `CLAUDE.md`'s Pointers section for the
9 most commonly needed links; this file is the full catalog.

## Reference

Living documentation describing current behavior — read on demand, updated in place as the
code changes.

| File | Description |
| --- | --- |
| [`api-reference.md`](api-reference.md) | Full reference for all `IBKRClient` methods — request/response shapes, exceptions raised |
| [`tools-reference.md`](tools-reference.md) | Full reference for all `ClaudeToolkit` tools (40 core + 2 optional scraper) — parameters, output shapes |
| [`api-usage-examples.md`](api-usage-examples.md) | Per-module usage examples (Setup, Market Data, Technical Indicators, Backtesting, Portfolio Analytics, Claude AI Tool Layer, PineScript Generation) |
| [`order-management-examples.md`](order-management-examples.md) | Order management code examples (read-only, place/confirm, manual reply-chain control, modify/cancel, GTC quarter-end auto-cancel) |
| [`gateway-auth-reference.md`](gateway-auth-reference.md) | Gateway login walkthrough, `GatewayManager`, headless `TokenAuth` |
| [`flex-query-reference.md`](flex-query-reference.md) | Historical Trade Data / Flex Queries (one-time setup, usage, constraints) |
| [`mcp-server-reference.md`](mcp-server-reference.md) | MCP Server (install, stdio/SSE transports, 44 tools, 4 resources, price alerts, TradingView integration) |
| [`ibkr-api-behaviors-reference.md`](ibkr-api-behaviors-reference.md) | Known IBKR API behaviors, verified not assumed |
| [`external-docs-reference.md`](external-docs-reference.md) | Official documentation URLs, all external APIs |
| [`consumers.md`](consumers.md) | Consuming projects |
| [`test-coverage.md`](test-coverage.md) | Current unit/integration test counts, coverage %, run commands |
| [`windows-setup.md`](windows-setup.md) | Windows install/run guide — what works out of the box vs. what needs an extra step (Touch ID gate) |

## Plans (`docs/plans/`)

Point-in-time records of what was decided and how — a design spec (`*-design.md`) captures
the why/what, a plan (`*-plan.md`) captures the how, for both features and fixes. Filenames
are `YYYY-MM-DD-<topic>-{design,plan}.md`; sorting the directory by filename gives
chronological order. These are not living documents — once written they are not edited to
reflect later changes; a later revisit gets a new dated file. Browse the directory directly
rather than looking for an index entry here.

## Audits (`docs/audits/`)

Point-in-time investigation and verification records — security audits, code audits, and
accumulated test-run logs ([`live-test-log.md`](audits/live-test-log.md)). Same treatment as
Plans: dated filenames, not retroactively edited. `audit-evidence/` holds raw supporting data
for the 2026-07 `claude_tools.py` audit. Browse directly rather than looking for an index
entry here.
```

- [ ] **Step 2: Verify all Reference-category links resolve**

```bash
for f in api-reference.md tools-reference.md api-usage-examples.md order-management-examples.md gateway-auth-reference.md flex-query-reference.md mcp-server-reference.md ibkr-api-behaviors-reference.md external-docs-reference.md consumers.md test-coverage.md windows-setup.md docs/audits/live-test-log.md; do
  path="docs/$f"
  [ "$f" = "docs/audits/live-test-log.md" ] && path="$f"
  test -f "$path" && echo "OK: $path" || echo "MISSING: $path"
done
```

Expected: every line says `OK:`.

- [ ] **Step 3: Commit**

```bash
git add docs/README.md
git commit -m "docs: add docs/README.md catalog"
```

---

### Task 8: Point root `README.md` at the new catalog

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add one line**

Find the root `README.md`'s top section (after the intro paragraph and "Who is this for?"
blockquote, before or after the Feature overview table — place it directly under the intro so
it's the first thing a reader sees) and add:

```markdown
📚 Full documentation catalog: [`docs/README.md`](docs/README.md)
```

- [ ] **Step 2: Verify**

```bash
grep -n "docs/README.md" README.md
```

Expected: one match.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: link docs/README.md catalog from root README"
```

---

### Task 9: Final verification

- [ ] **Step 1: Confirm CLAUDE.md was never touched**

```bash
git diff --stat main -- CLAUDE.md
```

Expected: empty output (or, if not run from a feature branch relative to `main`, run
`git log --oneline -1 -- CLAUDE.md` before and after this plan and confirm the commit hash is
unchanged from Pre-flight).

- [ ] **Step 2: Full repo-wide dead-reference sweep**

```bash
grep -rn --include="*.md" --include="*.py" -E "docs/future-doc-scraper\.md|docs/superpowers/(specs|plans)/" . --exclude-dir=.git --exclude-dir=.claude
```

Expected: no output at all (the `gdrive_auth.py` claudia_ui mentions use `specs/2026-07-10-...`
which is covered by this same pattern — re-check: those two lines **will** match here since
the pattern is `docs/superpowers/specs/`. That's expected and correct — they refer to a
different repo's path, not a dead reference in this one. Confirm exactly 2 lines print, both
in `gdrive_auth.py`/`test_gdrive_auth.py`, both annotated `(claudia_ui repo)`).

- [ ] **Step 3: Full test suite one more time**

```bash
pytest -m "not integration" -q
```

Expected: all green, matching the baseline count from Task 6 Step 4.

- [ ] **Step 4: Review the full commit sequence**

```bash
git log --oneline -9
git diff --stat HEAD~9 HEAD -- docs/ README.md SECURITY.md ibkr_core_mcp/ tests/ scripts/
```

Confirm the diffstat shows renames (`R` in `git status`, or `git diff -M` similarity) for every
moved file, not delete+add pairs — this is what proves `git mv` preserved history.

- [ ] **Step 5: Report to user**

Summarize: files moved (22 → `docs/plans/`, 9 + 1 dir → `docs/audits/`), 1 deleted, 2 dead
links fixed, ~28 outside-docs references repointed, `docs/README.md` created, root `README.md`
updated, CLAUDE.md untouched, test suite green. Do not push — leave that decision to the user.
