# Continued Docs Accuracy Audit — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply the exhaustive, full-file-read cross-check methodology proven on `docs/tools-reference.md` ↔ `ibkr_core_mcp/claude_tools.py` (2026-07-14, commit `1bccb2c`) to the remaining `docs/*.md` reference files against their corresponding source, in priority order. That pass replaced an earlier single-agent sampled read-through (2026-07-13) which had missed 15 discrepancies, including one real bug: `get_pa_transactions`'s handler was silently sending IBKR the wrong request body (a `period` string positionally where `client.py` expected a `conids` list). The other `docs/*.md` files went through the same kind of sampled pass on 2026-07-13 and have not yet had the exhaustive treatment — this plan closes that gap file by file.

**Architecture:** One task per doc↔code pair, in priority order. Each task:
1. Dispatches a fresh `general-purpose` Agent (never `Explore` — Explore reads excerpts and is explicitly documented as unsuitable for cross-file consistency checks) with a fully self-contained investigation prompt instructing it to read both files in full and report discrepancies only, no edits.
2. The calling session triages the report into doc-only fixes vs. real code-behavior bugs.
3. Doc-only fixes are applied directly. Any real code bug is fixed via TDD (superpowers:test-driven-development — write the failing test first, watch it fail, then implement).
4. Full unit suite reruns green (`pytest -m "not integration" -q`).
5. A second fresh Agent re-verifies every finding as PASS before the task's commit.

Each doc↔code pair is independent (no shared state), so tasks can run in parallel across sessions/agents — but every task below is written fully self-contained so it also works run standalone, one at a time, in one session (the order they're numbered in is priority, not a dependency chain).

**Tech Stack:** `Agent` tool (`subagent_type: general-purpose`), pytest, git. No new dependencies.

**Do not:**
- Modify `docs/plans/`, `docs/audits/`, or any file not named in a given task's discrepancy report.
- Resolve a Gate 1/Gate 2 (Touch ID / order-confirmation) doc-vs-code mismatch unilaterally by picking "update the doc." Per the precedent in `docs/plans/2026-07-08-docs-accuracy-fixes-plan.md` Task 1, any finding that touches the security-gate guarantees in CLAUDE.md's "Security & Fingerprint Authentication" section must be confirmed with the repo owner before choosing doc-edit vs. code-edit — CLAUDE.md explicitly states neither may be weakened without an accompanying README.md update in the same PR.
- Treat a clean report as license to skip the re-verification agent (step 5 in every task) — that second pass is what caught the stale `add_indicators` description text in the 2026-07-14 pass; skipping it defeats the point of this plan.

---

## Priority queue

| # | Doc file | Code file(s) | Doc / code lines | Audit style |
|---|---|---|---|---|
| 1 | `docs/api-reference.md` | `ibkr_core_mcp/client.py` | 892 / 1451 | Method-table, same style as the completed `tools-reference.md` pass |
| 2 | `docs/mcp-server-reference.md` | `ibkr_core_mcp/mcp_server.py` | 113 / 317 | Tool/resource-list |
| 3 | `docs/order-management-examples.md` | `client.py` order methods, `order_confirm.py`, `human_auth.py` | 91 / ~1866 combined | Security-critical code-example style |
| 4 | `docs/gateway-auth-reference.md` | `gateway/manager.py`, `auth.py` | 49 / 447 combined | Session/auth-critical, narrative + example |
| 5 | `docs/flex-query-reference.md` | `ibkr_core_mcp/flex_query.py` | 44 / 515 | Method + behavior-notes style |
| 6 | `docs/api-usage-examples.md` | Multiple modules (see Task 6) | 172 / — | Example-code style |
| 7 | `docs/ibkr-api-behaviors-reference.md` | Multiple (client.py, streaming.py, flex_query.py) | 9 (dense) / — | Claim-by-claim re-verification |
| 8 | `docs/external-docs-reference.md` | — (external URLs) | 64 / — | Citation/URL accuracy only |

**Skipped, with reason:**
- `docs/test-coverage.md` — regenerated from a live `pytest --cov` run in the 2026-07-13 pass; low drift risk until the next major test-suite change.
- `docs/README.md`, `docs/consumers.md`, `docs/windows-setup.md` — structural/informational, not schema- or behavior-claim-bearing; low value for this method.

---

## Task 1: `docs/api-reference.md` ↔ `ibkr_core_mcp/client.py`

**Files:**
- Investigate: `docs/api-reference.md` (892 lines), `ibkr_core_mcp/client.py` (1451 lines)
- Modify: `docs/api-reference.md` (doc-only fixes), possibly `ibkr_core_mcp/client.py` and its tests (if a real bug is found)
- Test (if code fix needed): `tests/test_client.py` or `tests/test_client_live.py` per existing convention

This is the single highest-value remaining target — same class of doc (per-method reference table) and comparable size to the just-completed `tools-reference.md` pass, against the largest source file in the package.

- [ ] **Step 1: Dispatch the investigation agent**

Use the `Agent` tool, `subagent_type: general-purpose`, `run_in_background: false`, with this exact prompt:

```
Repo: /Users/steph/Claude_Projects/ibkr_core_mcp (ibkr_core_mcp — an IBKR trading API client
package). docs/api-reference.md documents every public method on IBKRClient in
ibkr_core_mcp/client.py. It was rewritten from client.py's own docstrings on 2026-07-13 (added
4 previously-undocumented methods), but that rewrite was not an exhaustive line-by-line
cross-check — it's known to have been a single-pass regeneration. A separate exhaustive
tool-by-tool audit of docs/tools-reference.md against claude_tools.py on 2026-07-14 (commit
1bccb2c) found 15 discrepancies a prior sampled pass missed, including one real bug. This task
applies the same exhaustive method to api-reference.md vs client.py. Pure research/verification
— do NOT edit any files. Report findings only.

Read /Users/steph/Claude_Projects/ibkr_core_mcp/docs/api-reference.md in full (892 lines).
Read /Users/steph/Claude_Projects/ibkr_core_mcp/ibkr_core_mcp/client.py in full (1451 lines —
read it across multiple Read calls if your window truncates it; do not work from an excerpt).

Enumerate every public (non-underscore-prefixed) method on IBKRClient:
`grep -oP "^    def \K[a-zA-Z_]+(?=\()" ibkr_core_mcp/client.py | grep -v "^_"`
For EVERY one of those methods, do all of the following:

1. Find its exact section in api-reference.md (matched by method name + signature). If it's
   missing entirely, that's a critical finding.
2. Compare the doc's claimed signature (parameter names, types, defaults, return type) against
   the actual `def` line and type hints in client.py.
3. Compare the doc's prose description against the method's own docstring in client.py — the
   docstring is ground truth (many already carry `Source:`/`Endpoint:` citations per CLAUDE.md
   convention), not the doc's paraphrase of it.
4. Compare the doc's claimed HTTP method + path against what the method's body actually calls
   (`self._get(...)`, `self._post(...)`, `self._delete(...)` etc. — read the literal path
   string, including any f-string interpolation).
5. Compare the doc's claimed return shape / example JSON against the method's actual return
   type and any docstring-documented response shape.
6. Check for any method in client.py with NO corresponding doc section at all — cross off each
   method name as you find its doc section; anything left unchecked is a missing doc entry.

Do not stop after finding a few issues in one section (e.g. Market Data) and summarize the rest
as "checks out" without having gone method-by-method — that is the exact failure mode this pass
exists to catch. Go through every section in the doc (Session, Market Data, Contract/Security
Definition, Portfolio, Orders, Trades, Alerts, Watchlists, Notifications, Scanner, Flex,
Streaming, or whatever sections the doc actually has).

Report a numbered list of concrete discrepancies, each with: method name, doc line number, code
file:line, and a one-sentence description of the mismatch. Flag prominently (as item 1, with a
"FUNCTIONAL BUG" prefix) anything where the doc's claimed behavior differs from actual code
behavior in a way that suggests the code itself — not just the doc — might be wrong (i.e. an
argument-order mismatch, a wrong default, a signature the doc shows working that the code would
actually reject). Also report a one-line confirmation for every method that checked out clean,
so full coverage is visible. Keep the total response under 1400 words; if it would run longer,
prioritize discrepancies over clean confirmations.
```

- [ ] **Step 2: Triage the report**

Read the returned findings. For each discrepancy, classify as:
- **Doc-only** — client.py behavior is correct; `docs/api-reference.md` text is wrong. Fix directly with `Edit`.
- **Possible code bug** — the doc's claimed behavior doesn't match the code, and the code's behavior looks unintentional (e.g. an argument passed in the wrong position/type, a default that contradicts the method's own docstring). Do not assume the doc is right or the code is right — read the call site and, if it exists, the corresponding test in `tests/test_client.py` / `tests/test_client_live.py` to determine which one reflects the actual intended IBKR contract. If genuinely ambiguous, use the `AskUserQuestion` tool rather than guessing (this task touches `client.py`, which every other module in the package depends on).

- [ ] **Step 3: Fix any real code bug with TDD**

If Step 2 found a code bug: follow superpowers:test-driven-development exactly — write a failing test in `tests/test_client.py` reproducing the bug, run it and confirm it fails for the right reason, implement the minimal fix in `client.py`, rerun and confirm it passes. Do not skip the RED step.

- [ ] **Step 4: Apply doc-only fixes**

Edit `docs/api-reference.md` for every doc-only discrepancy from Step 2.

- [ ] **Step 5: Run the full unit suite**

```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
python -m pytest -m "not integration" -q
```
Expected: all tests pass, same or higher count than before this task (717 passed as of commit `1bccb2c`).

- [ ] **Step 6: Dispatch a fresh verification agent**

Use the `Agent` tool again (new agent, no memory of Steps 1-5) with a prompt listing each discrepancy found in Step 1 and asking it to re-read the current state of both files and report PASS/FAIL per item, plus rerun the pytest command above and report the summary line. Follow the exact structure used in the `tools-reference.md` re-verification pass (see this session's transcript / commit `1bccb2c` for the prompt shape). All items must come back PASS before proceeding.

- [ ] **Step 7: Commit**

```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
git add docs/api-reference.md ibkr_core_mcp/client.py tests/test_client.py
git commit -m "$(cat <<'EOF'
docs: exhaustive api-reference.md vs client.py cross-check

<Fill in with the actual count and a one-line summary of what was
found — e.g. "Fixed N doc discrepancies (wrong endpoints/signatures/
return shapes)" and, if applicable, "and one real bug in <method>
(TDD, N new tests)." Do not commit this placeholder line verbatim.>

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `docs/mcp-server-reference.md` ↔ `ibkr_core_mcp/mcp_server.py`

**Files:**
- Investigate: `docs/mcp-server-reference.md` (113 lines), `ibkr_core_mcp/mcp_server.py` (317 lines)
- Modify: `docs/mcp-server-reference.md` (doc-only fixes expected — `mcp_server.py` is a thin dispatch/resource layer over `ClaudeToolkit`, which Task tools-reference.md already verified, so a code bug here is less likely but not impossible in the resource/transport-specific logic)

`mcp_server.py`'s tool surface is built from `ClaudeToolkit.tools` (`_dispatch()` at line 63 routes by name to `toolkit.execute()`), so the 42 `ClaudeToolkit` tools are already verified as of commit `1bccb2c`. This task's real value is the 2 additional MCP-only surfaces: **resources** (`ibkr://...` URIs) and any MCP-specific tool-count/transport claims the doc makes that aren't just a restatement of `claude_tools.py`.

- [ ] **Step 1: Dispatch the investigation agent**

```
Repo: /Users/steph/Claude_Projects/ibkr_core_mcp. docs/mcp-server-reference.md documents the
MCP server in ibkr_core_mcp/mcp_server.py (44 tools, 4 resources, stdio + SSE transports, price
alerts, TradingView integration). The 42 base ClaudeToolkit tools it wraps were already
exhaustively verified against claude_tools.py on 2026-07-14 (commit 1bccb2c) — do not re-derive
that; focus on what's specific to mcp_server.py itself. Pure research/verification — do NOT
edit any files. Report findings only.

Read /Users/steph/Claude_Projects/ibkr_core_mcp/docs/mcp-server-reference.md in full (113
lines). Read /Users/steph/Claude_Projects/ibkr_core_mcp/ibkr_core_mcp/mcp_server.py in full (317
lines).

Check specifically:
1. Tool count claim: doc says "Tools (44)" — mcp_server.py exposes the 42 ClaudeToolkit tools
   plus how many MCP-only tools? Find the actual total by reading build_server() and _dispatch()
   (mcp_server.py:63, :90) and any tool list/registration code. Flag if 44 is wrong.
2. Resources: doc says "4 resources." Find every `ibkr://...` resource URI registered in
   mcp_server.py (read_resource handler or equivalent) and compare against what the doc lists —
   name, URI pattern, and what data each one actually returns.
3. Transports: doc claims stdio + SSE/HTTP transport support. Verify both transports are wired
   up in mcp_server.py (or wherever the entry point / main() at mcp_server.py:296 dispatches
   to), and that the doc's install/run instructions for each transport match actual CLI args or
   environment variables the code reads.
4. Price alerts section: the doc claims "programmatic" price alert support via MCP — verify
   this maps to actual code (create_price_alert/modify_price_alert/delete_alert/activate_alert
   tools, or a separate MCP-specific mechanism) rather than being aspirational text.
5. TradingView integration section: verify every code/config example in this section (webhook
   URLs, payload shapes, etc.) against actual code that handles it, if any exists in this repo
   (search for "tradingview" case-insensitive across ibkr_core_mcp/).

Report a numbered list of concrete discrepancies (doc line number + code file:line + one-sentence
mismatch), plus one-line clean confirmations for everything that checked out. Keep total response
under 800 words.
```

- [ ] **Step 2: Triage, fix, verify — same procedure as Task 1 Steps 2-6**, scaled to this file's size. Doc-only fixes go straight to `Edit`; any code-level finding gets a TDD fix per superpowers:test-driven-development before the doc is touched.

- [ ] **Step 3: Run the full unit suite**

```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
python -m pytest -m "not integration" -q
```

- [ ] **Step 4: Commit**

```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
git add docs/mcp-server-reference.md
git commit -m "docs: exhaustive mcp-server-reference.md vs mcp_server.py cross-check

<Fill in with actual findings summary — do not commit verbatim.>

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 3: `docs/order-management-examples.md` ↔ order-write path (`client.py`, `order_confirm.py`, `human_auth.py`)

**Files:**
- Investigate: `docs/order-management-examples.md` (91 lines), `ibkr_core_mcp/client.py` (order-related methods only), `ibkr_core_mcp/order_confirm.py` (364 lines: `confirm_order_dialog`, `confirm_modify_dialog`, `confirm_cancel_dialog`, `confirm_reply_dialog`), `ibkr_core_mcp/human_auth.py` (51 lines: `require_touch_id`)
- Modify: `docs/order-management-examples.md` only, unless Step 2 finds a security-gate discrepancy — in that case, stop and follow the "Do not" rule at the top of this plan (confirm with the repo owner before choosing which side to fix).

This is the highest-stakes doc in the queue: CLAUDE.md points to it as *the* canonical reference for order-management code examples, and it directly documents the two-gate (Touch ID + visual confirmation) security flow. This task's audit style is different from Tasks 1-2 — it's code-example verification (does every snippet still compile against current signatures) plus behavior-claim verification (does the doc's description of gate sequencing, chained replies, and GTC/quarter-end auto-cancel match the actual code), not a parameter table.

- [ ] **Step 1: Dispatch the investigation agent**

```
Repo: /Users/steph/Claude_Projects/ibkr_core_mcp. docs/order-management-examples.md is the
canonical code-example reference for order placement/modification/cancellation, pointed to
directly from CLAUDE.md's Security & Fingerprint Authentication section. It documents:
read-only order preview/status, place+confirm flow, manual reply-chain control,
modify/cancel, and GTC quarter-end auto-cancel behavior. Pure research/verification — do NOT
edit any files. Report findings only. This file is security-sensitive: if you find anything
where the doc's description of the two-gate (Touch ID then visual confirmation) flow doesn't
match the actual code, flag it as "SECURITY-SENSITIVE FINDING" at the top of your report,
separate from ordinary doc drift — do not just mix it into the numbered list.

Read /Users/steph/Claude_Projects/ibkr_core_mcp/docs/order-management-examples.md in full (91
lines).
Read /Users/steph/Claude_Projects/ibkr_core_mcp/ibkr_core_mcp/human_auth.py in full (51 lines —
this is require_touch_id(), Gate 1).
Read /Users/steph/Claude_Projects/ibkr_core_mcp/ibkr_core_mcp/order_confirm.py in full (364
lines — confirm_order_dialog/confirm_modify_dialog/confirm_cancel_dialog/confirm_reply_dialog,
Gate 2).
Read the order-related methods in /Users/steph/Claude_Projects/ibkr_core_mcp/ibkr_core_mcp/client.py:
place_order, place_order_and_confirm, modify_order, modify_order_and_confirm, cancel_order,
reply_order, get_order_preview, get_live_orders, get_order_status, get_orders_raw (grep each
name to find its definition, then read the full method body).

For every code snippet in docs/order-management-examples.md:
1. Verify every method call in the snippet matches the actual current signature (parameter
   names, order, types) in client.py — a snippet using stale parameter names would silently
   fail or behave differently for a reader who copies it.
2. Verify the snippet's claimed gate sequence (does place_order call require_touch_id() then
   confirm_order_dialog(), in that order, with no way to skip either) actually matches
   client.py's place_order/place_order_and_confirm implementation.
3. Verify the doc's description of place_order_and_confirm's chained-reply behavior (does it
   call Touch ID + a reply dialog for EVERY chained reply IBKR asks for, not just once) against
   the actual loop in client.py's place_order_and_confirm.
4. Verify any GTC / quarter-end auto-cancel behavior claim against actual code or an inline
   Source: citation — flag if the claim has no code backing and no cited source.
5. Verify the "read-only, ungated" methods the doc lists (get_order_preview, get_live_orders,
   get_order_status, get_orders_raw) genuinely never call require_touch_id or any confirm_*
   dialog function, by reading their full bodies.

Report a numbered list of concrete discrepancies (doc line number + code file:line + one-sentence
mismatch), with any security-sensitive finding called out separately at the top per the
instruction above. Also report one-line clean confirmations for everything that checked out.
Keep total response under 900 words.
```

- [ ] **Step 2: Triage.** If the report contains a "SECURITY-SENSITIVE FINDING," stop this task and use `AskUserQuestion` (or ask directly) to confirm with the repo owner whether the fix is a doc correction or a code correction, per this plan's "Do not" rule — do not proceed autonomously. For ordinary doc drift (stale parameter names, wrong sequencing description with no security implication), apply fixes directly.

- [ ] **Step 3: Apply fixes, run the full unit suite, dispatch a fresh verification agent** — same procedure as Task 1 Steps 3-6, scoped to this file.

```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
python -m pytest -m "not integration" -q
```

- [ ] **Step 4: Commit**

```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
git add docs/order-management-examples.md
git commit -m "docs: exhaustive order-management-examples.md vs order-write path cross-check

<Fill in with actual findings summary — do not commit verbatim. If a
security-sensitive finding was resolved, name the owner-confirmed
resolution explicitly per the precedent in commit history for
docs/plans/2026-07-08-docs-accuracy-fixes-plan.md Task 1.>

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 4: `docs/gateway-auth-reference.md` ↔ `gateway/manager.py` + `auth.py`

**Files:**
- Investigate: `docs/gateway-auth-reference.md` (49 lines), `ibkr_core_mcp/gateway/manager.py` (337 lines: `GatewayManager` — `is_docker_available`, `ensure_docker_running`, `image_exists`, `build_image`, `is_running`, `container_exists`, `start`, `stop`, `restart`, `is_gateway_reachable`, `is_authenticated`, `wait_for_gateway`, `wait_for_auth`, `open_login_page`, `startup`), `ibkr_core_mcp/auth.py` (110 lines: `AuthStrategy` protocol, `NoAuth`, `TokenAuth`, `BrowserCookieAuth`)
- Modify: `docs/gateway-auth-reference.md` only, unless a security/session-handling discrepancy is found (same escalation rule as Task 3 — session auth is adjacent to the security-critical surface even though it's not one of the two order-write gates).

- [ ] **Step 1: Dispatch the investigation agent**

```
Repo: /Users/steph/Claude_Projects/ibkr_core_mcp. docs/gateway-auth-reference.md documents the
IBKR Client Portal Gateway login walkthrough, GatewayManager (Docker lifecycle + auth polling),
and headless TokenAuth usage for batch jobs. Pure research/verification — do NOT edit any
files. Report findings only.

Read /Users/steph/Claude_Projects/ibkr_core_mcp/docs/gateway-auth-reference.md in full (49
lines).
Read /Users/steph/Claude_Projects/ibkr_core_mcp/ibkr_core_mcp/gateway/manager.py in full (337
lines) — GatewayManager's public methods are: is_docker_available, ensure_docker_running,
image_exists, build_image, is_running, container_exists, start, stop, restart,
is_gateway_reachable, is_authenticated, wait_for_gateway, wait_for_auth, open_login_page,
startup.
Read /Users/steph/Claude_Projects/ibkr_core_mcp/ibkr_core_mcp/auth.py in full (110 lines) —
AuthStrategy protocol, NoAuth, TokenAuth, BrowserCookieAuth.

For every GatewayManager method and every auth.py class the doc mentions:
1. Verify the doc's description of what it does/returns matches the actual method body and
   docstring (not just the method name).
2. Verify every code example in the doc (constructor calls, method call sequences, expected
   return values/exceptions) against the actual current signatures.
3. Verify the doc's claimed default timeout/poll-interval values (e.g. for wait_for_gateway,
   wait_for_auth) against the actual defaults in the method signatures.
4. Verify CLAUDE.md's summary claim ("Session expires without activity — call client.tickle()
   every 60s to keep it alive. Rate limit ~5 requests/second") is elaborated correctly (or not
   contradicted) in this doc, and that any tickle()-related example matches client.py's actual
   tickle() method.
5. Verify BrowserCookieAuth's documented cookie source (which browser(s), which OS keychain/
   storage mechanism) against the actual implementation — this is the kind of claim likely to
   drift silently if the underlying cookie-extraction library or OS behavior changed.
6. Check TokenAuth's documented use case ("headless batch jobs") against what the class
   actually requires as input and how it differs operationally from BrowserCookieAuth.

Report a numbered list of concrete discrepancies (doc line number + code file:line + one-sentence
mismatch), flagging anything that could cause a session/auth failure for someone following the
doc as "OPERATIONAL RISK" at the top, separate from cosmetic drift. Report one-line clean
confirmations for everything that checked out. Keep total response under 700 words.
```

- [ ] **Step 2: Triage, fix, verify, run tests** — same procedure as Task 1 Steps 2-6, scoped to this file. Escalate any "OPERATIONAL RISK" finding per this plan's "Do not" rule before fixing.

```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
python -m pytest -m "not integration" -q
```

- [ ] **Step 3: Commit**

```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
git add docs/gateway-auth-reference.md
git commit -m "docs: exhaustive gateway-auth-reference.md vs gateway/manager.py + auth.py cross-check

<Fill in with actual findings summary — do not commit verbatim.>

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 5: `docs/flex-query-reference.md` ↔ `ibkr_core_mcp/flex_query.py`

**Files:**
- Investigate: `docs/flex-query-reference.md` (44 lines), `ibkr_core_mcp/flex_query.py` (515 lines: `FlexQueryClient` — `import_from_file`, `sync_archive_from_drive`, `fetch_trades`, `extract_execution_ids`)
- Modify: `docs/flex-query-reference.md` only

- [ ] **Step 1: Dispatch the investigation agent**

```
Repo: /Users/steph/Claude_Projects/ibkr_core_mcp. docs/flex-query-reference.md documents
Historical Trade Data / Flex Queries: one-time setup, usage, and constraints, for
ibkr_core_mcp/flex_query.py's FlexQueryClient. Pure research/verification — do NOT edit any
files. Report findings only.

Read /Users/steph/Claude_Projects/ibkr_core_mcp/docs/flex-query-reference.md in full (44 lines).
Read /Users/steph/Claude_Projects/ibkr_core_mcp/ibkr_core_mcp/flex_query.py in full (515 lines)
— FlexQueryClient's public methods: import_from_file, sync_archive_from_drive, fetch_trades,
extract_execution_ids (staticmethod).

Cross-check:
1. Setup instructions (env vars IBKR_FLEX_TOKEN / IBKR_FLEX_QUERY_ID, or whatever the doc
   claims) against what fetch_trades/the client constructor actually reads from Config.
2. Every method's signature and behavior (params, return shape) against the doc's description.
3. The doc's claimed T+1 latency behavior and any constraints (e.g. max lookback, required IBKR
   account permissions) against comments/docstrings in flex_query.py — flag any constraint the
   doc claims that isn't backed by a code comment or citation, and any constraint in the code
   that the doc omits.
4. The doc's claimed Flex endpoint URL(s) against the actual URLs in flex_query.py's request
   code (note: this repo has a known-sensitive history here — CLAUDE.md's "API Docs First"
   table documents a real incident where the Flex endpoint URL was wrong for the entire life of
   the codebase, so treat any URL claim in this doc with extra scrutiny and verify it against
   the literal string in flex_query.py, not by pattern-matching what "looks right").
5. SSRF guard: if the doc mentions any allowlist of permitted Flex response URLs
   (_ALLOWED_URL_PREFIXES or similar), verify the doc's list matches the actual list in
   flex_query.py exactly.

Report a numbered list of concrete discrepancies (doc line number + code file:line + one-sentence
mismatch), plus one-line clean confirmations for everything that checked out. Keep total response
under 600 words.
```

- [ ] **Step 2: Triage, fix, verify, run tests** — same procedure as Task 1 Steps 2-6.

```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
python -m pytest -m "not integration" -q
```

- [ ] **Step 3: Commit**

```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
git add docs/flex-query-reference.md
git commit -m "docs: exhaustive flex-query-reference.md vs flex_query.py cross-check

<Fill in with actual findings summary — do not commit verbatim.>

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 6: `docs/api-usage-examples.md` ↔ multiple modules

**Files:**
- Investigate: `docs/api-usage-examples.md` (172 lines) — per CLAUDE.md this covers Setup, Market Data, Technical Indicators, Backtesting, Portfolio Analytics, Claude AI Tool Layer, PineScript Generation
- Cross-reference: `ibkr_core_mcp/config.py` (`Config`), `ibkr_core_mcp/client.py` (`IBKRClient`), `ibkr_core_mcp/cache.py` (`GDriveCache`), `ibkr_core_mcp/store.py` (`SQLiteStore`), `ibkr_core_mcp/indicators.py`, `ibkr_core_mcp/backtest.py`, `ibkr_core_mcp/analytics.py`, `ibkr_core_mcp/claude_tools.py` (`ClaudeToolkit` — already exhaustively verified as of `1bccb2c`, so this task only needs to check that api-usage-examples.md's *construction/setup* examples for it are current, not re-verify each tool), `ibkr_core_mcp/pinescript.py`
- Modify: `docs/api-usage-examples.md` only

- [x] **Step 1: Dispatch the investigation agent**

```
Repo: /Users/steph/Claude_Projects/ibkr_core_mcp. docs/api-usage-examples.md is the per-module
usage-example reference pointed to from CLAUDE.md's "Basic object setup used throughout the
codebase" line. It covers Setup, Market Data, Technical Indicators, Backtesting, Portfolio
Analytics, Claude AI Tool Layer, and PineScript Generation sections, each with runnable-looking
code examples. Pure research/verification — do NOT edit any files. Report findings only.

Read /Users/steph/Claude_Projects/ibkr_core_mcp/docs/api-usage-examples.md in full (172 lines).
For each section's code examples, read the actual current constructor/method signatures they
call:
- Setup section → ibkr_core_mcp/config.py (Config), ibkr_core_mcp/client.py (IBKRClient
  __init__), ibkr_core_mcp/cache.py (GDriveCache __init__), ibkr_core_mcp/store.py (SQLiteStore
  __init__)
- Market Data section → relevant IBKRClient methods (fetch/history methods) in client.py
- Technical Indicators section → ibkr_core_mcp/indicators.py's public functions
- Backtesting section → ibkr_core_mcp/backtest.py's public functions/classes
- Portfolio Analytics section → relevant IBKRClient portfolio-analyst methods in client.py
- Claude AI Tool Layer section → ibkr_core_mcp/claude_tools.py's ClaudeToolkit constructor and
  .execute()/.tools — NOTE: the 42 individual tools were already exhaustively verified against
  claude_tools.py on 2026-07-14 (commit 1bccb2c); do not re-derive that, only check that this
  doc's construction/setup examples (how to instantiate ClaudeToolkit, how to call .execute())
  are current.
- PineScript Generation section → ibkr_core_mcp/pinescript.py's public functions

For every code example: verify every constructor call, method call, and parameter name against
the actual current signature. Flag any example that would raise a TypeError or produce
different output if run today. Flag any claimed return shape / printed output that doesn't
match what the actual code produces.

Report a numbered list of concrete discrepancies (doc line number + code file:line + one-sentence
mismatch), plus one-line clean confirmations per section for everything that checked out. Keep
total response under 700 words.
```

- [x] **Step 2: Triage, fix, verify, run tests** — same procedure as Task 1 Steps 2-6.

```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
python -m pytest -m "not integration" -q
```

- [x] **Step 3: Commit**

```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
git add docs/api-usage-examples.md
git commit -m "docs: exhaustive api-usage-examples.md vs source cross-check

<Fill in with actual findings summary — do not commit verbatim.>

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 7: `docs/ibkr-api-behaviors-reference.md` — claim-by-claim re-verification

**Files:**
- Investigate: `docs/ibkr-api-behaviors-reference.md` (9 lines, each a dense multi-sentence factual claim with a stated verification date)
- Cross-reference: `ibkr_core_mcp/client.py`, `ibkr_core_mcp/streaming.py`, `ibkr_core_mcp/flex_query.py`, `ibkr_core_mcp/claude_tools.py`
- Modify: `docs/ibkr-api-behaviors-reference.md` only

This file is structurally different from Tasks 1-6 — it's not a schema/example doc but a set of "verified, not assumed" behavioral claims, each carrying a specific date of observation. The audit style here is claim-by-claim: does each claim still hold given the current code, and is the citation still accurate.

- [ ] **Step 1: Dispatch the investigation agent**

```
Repo: /Users/steph/Claude_Projects/ibkr_core_mcp. docs/ibkr-api-behaviors-reference.md is a
short but dense file of "verified, not assumed" IBKR API behavioral claims, each with a stated
observation date, existing specifically because CLAUDE.md's "API Docs First" rule was created
after two real incidents caused by assumption-based development (a misdiagnosed Flex error code,
and a wrong Flex endpoint URL that meant the Flex API never worked from day one). Pure
research/verification — do NOT edit any files. Report findings only.

Read /Users/steph/Claude_Projects/ibkr_core_mcp/docs/ibkr-api-behaviors-reference.md in full (9
lines — each line is a dense paragraph, read every one carefully, don't skim).

For each of the 5 claims in the file, re-verify against current code:
1. "/iserver/account/orders — two-call pattern" — find the code in claude_tools.py that
   implements the two-call pattern for get_live_orders/diagnose_orders and confirm it still
   works this way.
2. "/iserver/marketdata/history — max 1000 points, 3x retry with 2s delay, pagination via
   startTime chunks" — find fetch_market_data / get_market_history_paginated in client.py and
   claude_tools.py and confirm the exact retry count, delay, and chunking key still match.
3. "/iserver/account/trades — days=7 max, all-origins-after-warmup behavior, WebSocket str
   topic persists to the same trades table via _parse_stream_execution" — find get_trades in
   client.py, the get_trades handler in claude_tools.py, subscribe_executions/
   unsubscribe_executions in streaming.py, and _parse_stream_execution — confirm each claim.
4. "Flex Web Service — T+1, all origins, separate token+query ID" — confirm against
   flex_query.py's FlexQueryClient and config.py's flex_token/flex_query_id fields.
5. "Flex endpoint — SendRequest goes to ndcdyn, GetStatement observed at gdcdyn, both
   allowlisted in _ALLOWED_URL_PREFIXES, requires a User-Agent header" — confirm the literal
   URL strings and the allowlist contents in flex_query.py exactly match this claim.

For each claim, report VERIFIED (still holds, code reference to prove it), STALE (claim no
longer matches code — cite the code that contradicts it), or UNVERIFIABLE (would require a live
IBKR gateway/Flex call to confirm — note this rather than guessing). Also flag any claim whose
cited Source: URL looks like it may have moved (do not fetch external URLs yourself unless
asked — just note if the URL shape looks unusual/inconsistent with other citations in the repo).
Keep total response under 600 words.
```

- [ ] **Step 2: Triage, fix, verify, run tests** — same procedure as Task 1 Steps 2-6. A STALE finding here may indicate actual behavior drift in IBKR's API, not just a doc typo — if so, treat it with the same "API Docs First" scrutiny CLAUDE.md requires (verify against current official docs via WebFetch before rewriting the claim, per CLAUDE.md's Conventions section).

```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
python -m pytest -m "not integration" -q
```

- [ ] **Step 3: Commit**

```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
git add docs/ibkr-api-behaviors-reference.md
git commit -m "docs: re-verify ibkr-api-behaviors-reference.md claims against current code

<Fill in with actual findings summary — do not commit verbatim.>

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 8: `docs/external-docs-reference.md` — citation accuracy

**Files:**
- Investigate: `docs/external-docs-reference.md` (64 lines — official documentation URL tables for Client Portal, Flex, WebSocket, Drive, LocalAuthentication, web scraping)
- Modify: `docs/external-docs-reference.md` only

Lowest functional risk in this queue (it's a pointer table, not executable-claim-bearing), but still worth a pass since CLAUDE.md's "API Docs First" protocol depends on these URLs being the actual correct starting points.

- [ ] **Step 1: Dispatch the investigation agent**

```
Repo: /Users/steph/Claude_Projects/ibkr_core_mcp. docs/external-docs-reference.md is a table of
official documentation URLs (Client Portal, Flex, WebSocket, Google Drive, Apple
LocalAuthentication, web scraping) that CLAUDE.md's "API Docs First" rule directs contributors
to check before writing any endpoint-related code. Pure research/verification — do NOT edit any
files, do NOT fetch any external URLs (that's for a later live-check, not this pass). Report
findings only.

Read /Users/steph/Claude_Projects/ibkr_core_mcp/docs/external-docs-reference.md in full (64
lines).

Cross-reference every URL listed in this doc against the URLs actually cited inline in source
code (client.py, flex_query.py, streaming.py, cache.py, human_auth.py, claude_tools.py,
web_scraper.py, scrape_fallback.py all carry inline "Source:" comments per CLAUDE.md
convention — grep for "Source:" and "https://" across ibkr_core_mcp/). For each URL in this
doc:
1. Confirm the same URL (or an equivalently-scoped one) appears as a Source: citation somewhere
   in the actual implementation it's meant to document — if a doc URL has no corresponding
   in-code citation anywhere, flag it as possibly orphaned/unused.
2. Confirm every in-code Source: URL that SHOULD be represented in this reference doc (because
   it documents a whole subsystem, not a one-off implementation detail) actually appears here —
   flag any subsystem-level citation that's missing from this doc entirely.

Report a numbered list of mismatches (doc line number + code file:line + one-sentence
description), plus a one-line confirmation for every URL category that checked out. Keep total
response under 500 words.
```

- [ ] **Step 2: Triage, fix, verify, run tests** — same procedure as Task 1 Steps 2-6 (a doc-only fix here should just be an `Edit`; do not fetch or change any live URL as part of this task — that's future live-verification work, out of scope here).

```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
python -m pytest -m "not integration" -q
```

- [ ] **Step 3: Commit**

```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
git add docs/external-docs-reference.md
git commit -m "docs: cross-check external-docs-reference.md citations against in-code Source: comments

<Fill in with actual findings summary — do not commit verbatim.>

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Final verification sweep (after all 8 tasks)

- [x] **Step 1: Full unit suite one more time**

```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
python -m pytest -m "not integration" -q
```
Expected: all green, count ≥ 717 (the baseline as of commit `1bccb2c`; higher if any task added tests for a real bug fix).

Actual (2026-07-14, after Task 6): `730 passed, 85 deselected` — green, above baseline.

- [x] **Step 2: Confirm every task's doc file changed and every task committed separately**

```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
git log --oneline 1bccb2c..HEAD -- docs/
```
Expected: one commit per task (8 total, or fewer if some tasks were run together — but never a single mega-commit covering multiple doc files, per this repo's established pattern of one focused commit per fix).

- [x] **Step 3: Update memory**

If this plan was executed by a Claude Code session with access to the project's memory system, update `project_docs_accuracy_pass_2026_07_13.md` (or create a new dated memory) recording: which of the 8 tasks found real code bugs (not just doc drift) vs. which came back clean, so a future doc-audit pass knows which files are lower-risk to skip next time.

---

## Closing note — all 8 tasks complete (2026-07-14)

Tasks 1/2/3/5/8 executed and committed under ad-hoc (non-plan-template) commit
messages before this plan file's checkboxes were kept in sync; Task 6 was the
one task never executed until this pass, and Tasks 4/7 were executed earlier
but their actual fixes landed in files other than their own target doc. Recording
all 8 here so a future pass doesn't re-run `git log -- <target-doc>` alone and
wrongly conclude a task was skipped:

| # | Doc file | Outcome | Fix landed in | Commit |
|---|---|---|---|---|
| 1 | `docs/api-reference.md` | doc drift found, fixed | `docs/api-reference.md` | `468c2ec` |
| 2 | `docs/mcp-server-reference.md` | doc drift found, fixed | `docs/mcp-server-reference.md` | `ec49289` |
| 3 | `docs/order-management-examples.md` | doc drift found, fixed | `docs/order-management-examples.md` | `984f13b` |
| 4 | `docs/gateway-auth-reference.md` | doc itself clean; found stale rate-limit claim ("~5 req/s" vs. actual 10 req/s) elsewhere | `CLAUDE.md` (Gateway Authentication & Session section) | `b040ca0` |
| 5 | `docs/flex-query-reference.md` | doc drift found, fixed | `docs/flex-query-reference.md` | `cfa4122` |
| 6 | `docs/api-usage-examples.md` | 3 doc-only formatting/unit bugs found, fixed (`max_drawdown` needed `:.1%` not `:.1f}%` in two print statements; `full_report(..., periods=1440)` used minutes/day instead of bars/year, corrected to `98280`) — no code bug | `docs/api-usage-examples.md` | *(this commit)* |
| 7 | `docs/ibkr-api-behaviors-reference.md` | all 5 claims re-verified VERIFIED, doc itself clean; found stale docstring elsewhere | `ibkr_core_mcp/client.py` (`get_trades()` docstring, wrongly claimed WebSocket str topic unimplemented) | `7531b3e` |
| 8 | `docs/external-docs-reference.md` | doc drift found, fixed | `docs/external-docs-reference.md` | `eec9cbe` |

Final unit suite: 730 passed, 85 deselected (baseline at plan creation was 717).
Two tasks (4, 7) found their doc target already accurate but surfaced real drift
in an adjacent file (`CLAUDE.md`, `client.py`) via the same exhaustive cross-check
method — evidence the method generalizes beyond its original `tools-reference.md`
target, not just a one-off.
