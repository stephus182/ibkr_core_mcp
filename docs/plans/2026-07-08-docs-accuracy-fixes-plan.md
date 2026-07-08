# CLAUDE.md / README.md Accuracy Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix five confirmed inaccuracies in `README.md` and `CLAUDE.md`, found during a manual verification pass on 2026-07-08 that checked every checkable factual/numeric claim in both docs against the actual code.

**Architecture:** Documentation-only changes — no source code is modified anywhere in this plan. Every task is a `README.md` and/or `CLAUDE.md` edit, verified with `grep` (there is no test suite for prose). Task 1 (Gate 1 security policy) is the highest-priority task: it corrects a claim that currently promises a stronger security guarantee than the code actually provides.

**Tech Stack:** Markdown only. No code, no dependencies, no tests to run.

**Do not:**
- Modify any file under `ibkr_core_mcp/` (the package source) — the decision for this plan (confirmed with the repo owner, Steph, on 2026-07-08) is to update the *docs* to match the current code, not to change `human_auth.py`'s policy.
- Run `git tag` or `git push` for any version number — Task 4 only edits documentation *examples* of how to tag a release; it must never actually create or push a tag.
- Touch `docs/plans/2026-07-08-claude-tools-test-reorg-plan.md`, `CHANGELOG.md`, or any file not explicitly named in a task below.

---

## Background — how each finding was verified

All five findings below were confirmed by reading the actual implementation, not by inspection of the docs alone:

1. **Gate 1 policy mismatch:** `ibkr_core_mcp/human_auth.py:16-31` imports and uses `LAPolicyDeviceOwnerAuthentication`, not `LAPolicyDeviceOwnerAuthenticationWithBiometrics`. The code's own comment (lines 25-28) says the biometrics-only policy "was rejected immediately on a failed scan with no recovery path." Steph confirmed the real-world reason: a fingerprint scan can legitimately fail to read (wet/dry finger, worn ridge detail, sensor angle) even when the account owner is the one pressing the sensor — the fallback exists for physical read-reliability, not to weaken the gate for convenience. Both `README.md` and `CLAUDE.md` currently document the biometrics-only policy as an absolute guarantee, including a contributor rule in `CLAUDE.md` stating a PR implementing exactly what the code already does ("Any PR that weakens these gates will be rejected") should be rejected. Decision (Steph, 2026-07-08): update the docs to accurately describe the real policy; do not change the code.
2. **Package Structure diagram incomplete:** `CLAUDE.md`'s `## Package Structure` ASCII diagram (lines 55-80) lists 14 top-level `.py` files plus `gateway/`. `ls ibkr_core_mcp/*.py` shows 21 top-level `.py` files (excluding the private `_order_dialog.py`, a subprocess helper for `order_confirm.py` that doesn't warrant its own top-level entry). The 7 missing from the diagram — `flex_query.py`, `mcp_server.py`, `streaming.py`, `human_auth.py`, `order_confirm.py`, `web_scraper.py`, `scrape_fallback.py` — each already have their own full section elsewhere in the same `CLAUDE.md` file, so this isn't a case of undocumented functionality, just a stale top-level map.
3. **Endpoint count stale:** The same diagram's `client.py` comment says "All 79 IBKR Client Portal API endpoints." Counting public (non-underscore-prefixed) methods on `IBKRClient` — `grep -oP "^    def \K[a-zA-Z_]+(?=\()" ibkr_core_mcp/client.py | grep -v "^_" | wc -l` — gives 75, not 79.
4. **Market calendar example wrong on 3 counts:** `CLAUDE.md`'s `## Portfolio Analytics` section (lines 402-410) shows a `get_market_calendar_context()` example with a `# NYSE + CME (default)` comment — the real default (`ibkr_core_mcp/store.py:434-453`) is 20 exchanges (G20 + Eurex), not 2. The example's shown return shape (`{"generated_at": ..., "exchanges": {...}}`) doesn't match the real return shape, confirmed by calling the function directly: `{"today", "is_trading_day", "last_trading_day", "next_trading_day", "primary_exchange", "holidays_by_exchange"}` — which is exactly what `README.md`'s parallel example (lines 376-392) already shows correctly. And the `# add LSE` comment on the custom-exchange-list example implies additive behavior; the actual code (`if exchanges is None: exchanges = [...]`) replaces the default list entirely when you pass one — `get_market_calendar_context(["XLON"])` returns *only* XLON, not the 20 defaults plus XLON.
5. **Stale version examples in `CLAUDE.md`:** `git tag -l --sort=-v:refname` shows the actual latest release is `v1.0.0` (`pyproject.toml`'s `version = "1.0.0"` agrees). `CLAUDE.md`'s `## Install` section pins to `@v0.1.0` (the *very first* tag) as its example, while `README.md`'s equivalent example already correctly uses `@v1.0.0`. `CLAUDE.md`'s `## Publishing a New Version` section instructs `git tag v0.3.0` as if it were the next tag to create — but `v0.3.0` was already tagged and released long ago (visible in `git tag -l`), so a contributor following those exact commands literally would try to recreate an existing tag.

---

## Task 1: Fix Gate 1 security policy documentation (README.md + CLAUDE.md)

**Files:**
- Modify: `README.md:44`, `README.md:339-340`
- Modify: `CLAUDE.md:107`, `CLAUDE.md:135-138`

This is one task covering both files because splitting it across two commits would leave the two docs contradicting each other in the intermediate state.

- [x] **Step 1: Fix the Requirements table in `README.md`**

Find (line 44):
```markdown
| Policy | `LAPolicyDeviceOwnerAuthenticationWithBiometrics` — biometric only, **no password fallback** |
```

Replace with:
```markdown
| Policy | `LAPolicyDeviceOwnerAuthentication` — Touch ID/Face ID first, falls back to the device's system password if the biometric scan fails or is cancelled |
```

- [x] **Step 2: Fix the Gate 1 description in `README.md`'s Security section**

Find (lines 339-340):
```markdown
- **Policy:** `LAPolicyDeviceOwnerAuthenticationWithBiometrics` — fingerprint or Face ID only
- **No fallback:** Password / PIN entry is explicitly excluded. If biometrics are unavailable the call raises `HumanAuthError` immediately.
```

Replace with:
```markdown
- **Policy:** `LAPolicyDeviceOwnerAuthentication` — tries Touch ID/Face ID first, falls back to the device's system password if the biometric scan fails or is cancelled. This is a deliberate choice, not an oversight: a fingerprint scan can legitimately fail to read even for the genuine account owner (wet or dry skin, worn ridge detail, sensor angle), and `LAPolicyDeviceOwnerAuthenticationWithBiometrics` (biometrics-only) has no recovery path on a failed scan — it fails outright with no retry. The password fallback is Apple's own LocalAuthentication recovery mechanism, evaluated and kept for exactly that reliability reason.
- **No bypass inside the library:** Whichever path succeeds (biometric or system password), `ibkr_core_mcp` itself never intercepts, caches, or skips this call — every order-write attempt calls `require_touch_id()` fresh. If both the biometric scan and the system password fail, or `LocalAuthentication` is unavailable, `HumanAuthError` is raised immediately and the order is never submitted.
```

- [x] **Step 3: Fix the Gate 1 row in `CLAUDE.md`'s gate table**

Find (line 107):
```markdown
| **Gate 1 — Touch ID** | Apple `LocalAuthentication` (`LAPolicyDeviceOwnerAuthenticationWithBiometrics`) | Fingerprint only — no password fallback. 60-second timeout. |
```

Replace with:
```markdown
| **Gate 1 — Touch ID** | Apple `LocalAuthentication` (`LAPolicyDeviceOwnerAuthentication`) | Touch ID/Face ID first, falls back to the device's system password on a failed/cancelled biometric scan. 60-second timeout. |
```

- [x] **Step 4: Fix the contributor rules in `CLAUDE.md`**

Find (lines 135-138):
```markdown
- Never add a bypass flag, session cache, or fallback to `require_touch_id` or any dialog function.
- Never move the gates out of `IBKRClient` — enforcement must be at the innermost call site.
- Never add password/PIN fallback — `LAPolicyDeviceOwnerAuthenticationWithBiometrics` is the required policy.
- Any PR that weakens these gates will be rejected.
```

Replace with:
```markdown
- Never add a bypass flag, session cache, or library-side fallback to `require_touch_id` or any dialog function — no code path may skip or cache a prior Touch ID / dialog success.
- Never move the gates out of `IBKRClient` — enforcement must be at the innermost call site.
- The required policy is `LAPolicyDeviceOwnerAuthentication` (Touch ID/Face ID, falling back to the device's system password on a failed/cancelled biometric scan). This is Apple LocalAuthentication's own recovery path for a genuinely-failed biometric read (wet/dry finger, worn ridge detail, sensor angle) — not a bypass this library adds. `LAPolicyDeviceOwnerAuthenticationWithBiometrics` (biometrics-only) was evaluated and rejected: a failed scan under that policy has no recovery path at all. Do not change this policy without updating both this file and `README.md`'s Security section in the same PR.
- Any PR that weakens these gates *beyond* the documented policy above — e.g. adding a code path that skips `require_touch_id`/`confirm_order_dialog` entirely, caches a prior success, or adds a fallback beyond the OS's own password prompt — will be rejected.
```

- [x] **Step 5: Verify no stale references remain**

Run:
```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
grep -n "LAPolicyDeviceOwnerAuthenticationWithBiometrics\|no password fallback\|No fallback.*Password" README.md CLAUDE.md
```
Expected: no output (empty). If anything prints, the corresponding edit above didn't apply cleanly — re-check the exact line.

- [x] **Step 6: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "$(cat <<'EOF'
docs: correct Gate 1 Touch ID policy claims to match actual code

Both docs claimed LAPolicyDeviceOwnerAuthenticationWithBiometrics
(biometrics-only, no password fallback) as an absolute guarantee,
including a contributor rule saying a PR matching the actual code
would be rejected. The real implementation (human_auth.py:16-31) uses
LAPolicyDeviceOwnerAuthentication, which falls back to the device's
system password on a failed/cancelled biometric scan — a deliberate
choice for biometric read reliability (a scan can legitimately fail
even for the genuine account owner), not a security weakening for
convenience. Docs updated to describe the real policy accurately;
no code changed.
EOF
)"
```

---

## Task 2: Rewrite `CLAUDE.md`'s Package Structure diagram

**Files:**
- Modify: `CLAUDE.md:55-80`

Adds the 7 missing modules (each already documented in its own section elsewhere in `CLAUDE.md` — this task only fixes the top-level map) and fixes the endpoint count from 79 to 75 in the same edit, since both changes are inside the same code block.

- [x] **Step 1: Replace the whole Package Structure code block**

Find (the full block, `CLAUDE.md` lines 57-80):
```
ibkr_core_mcp/
├── __init__.py        # Public API — import everything from here
├── auth.py            # Auth strategies: BrowserCookieAuth, TokenAuth, NoAuth
├── client.py          # All 79 IBKR Client Portal API endpoints
├── models.py          # Pydantic v2 schemas for all response types
├── exceptions.py      # Custom exception hierarchy (IBKRCoreError → subclasses)
├── cache.py           # Google Drive parquet cache (market data, shared cross-machine)
├── store.py           # SQLite store (trades, signals, backtest results, positions)
├── backtest.py        # RestrictedPython sandbox executor
├── indicators.py      # Technical indicators (RSI, MACD, BB, ATR, VWAP, OBV, ...)
├── analytics.py       # Performance metrics (Sharpe, Sortino, Calmar, drawdown, ...)
├── claude_tools.py    # Claude tool definitions + handlers (42 tools, portable)
├── pinescript.py      # PineScript v5 generation from strategies and indicators
├── rate_limiter.py    # Token-bucket rate limiter + exponential backoff on 429
├── config.py          # Config dataclass loaded from environment variables
└── gateway/
    ├── manager.py     # GatewayManager — Docker lifecycle, auth polling
    ├── Dockerfile     # eclipse-temurin:21 + IBKR Client Portal zip
    ├── conf.yaml      # Gateway config (port, SSL, CORS, IP allowlist)
    ├── run_gateway.sh # Entrypoint: start Java process + tickler
    ├── tickler.sh     # Periodic POST /tickle to keep session alive
    └── healthcheck.sh # curl-based readiness probe used by run_gateway.sh
```

Replace with:
```
ibkr_core_mcp/
├── __init__.py           # Public API — import everything from here
├── auth.py               # Auth strategies: BrowserCookieAuth, TokenAuth, NoAuth
├── client.py             # All 75 IBKR Client Portal API endpoints
├── models.py             # Pydantic v2 schemas for all response types
├── exceptions.py         # Custom exception hierarchy (IBKRCoreError → subclasses)
├── cache.py              # Google Drive parquet cache (market data, shared cross-machine)
├── store.py              # SQLite store (trades, signals, backtest results, positions)
├── flex_query.py         # FlexQueryClient — Flex Web Service historical trade sync (T+1, unlimited history)
├── backtest.py           # RestrictedPython sandbox executor
├── indicators.py         # Technical indicators (RSI, MACD, BB, ATR, VWAP, OBV, ...)
├── analytics.py          # Performance metrics (Sharpe, Sortino, Calmar, drawdown, ...)
├── claude_tools.py       # Claude tool definitions + handlers (42 tools, portable)
├── mcp_server.py         # MCP server (stdio + SSE transports) — 44 tools, 4 resources
├── human_auth.py         # Gate 1: Touch ID / Face ID biometric authentication
├── order_confirm.py      # Gate 2: visual order confirmation dialog (tkinter/AppKit)
├── streaming.py          # IBKRWebSocket — live quotes, execution/P&L push; AlertManager
├── web_scraper.py        # FirecrawlClient + WebDocsStore — search/crawl, Drive snapshots
├── scrape_fallback.py    # Crawl4AI fallback + SSRF guard for web scraping
├── pinescript.py         # PineScript v5 generation from strategies and indicators
├── rate_limiter.py       # Token-bucket rate limiter + exponential backoff on 429
├── config.py             # Config dataclass loaded from environment variables
└── gateway/
    ├── manager.py        # GatewayManager — Docker lifecycle, auth polling
    ├── Dockerfile        # eclipse-temurin:21 + IBKR Client Portal zip
    ├── conf.yaml         # Gateway config (port, SSL, CORS, IP allowlist)
    ├── run_gateway.sh    # Entrypoint: start Java process + tickler
    ├── tickler.sh        # Periodic POST /tickle to keep session alive
    └── healthcheck.sh    # curl-based readiness probe used by run_gateway.sh
```

Note: `_order_dialog.py` (a private AppKit subprocess helper called by `order_confirm.py`) is deliberately left out of this diagram — it's an internal implementation detail, not a public top-level module, consistent with no other underscore-prefixed file appearing in this list.

- [x] **Step 2: Verify the file list matches reality**

Run:
```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
comm -23 <(ls ibkr_core_mcp/*.py | xargs -n1 basename | grep -v "^_" | sort) <(grep -oP '(?<=├── |└── )[a-z_]+\.py' CLAUDE.md | sort -u)
```
Expected: no output (empty) — every non-underscore top-level `.py` file is now represented in the diagram. If any filename prints, it's still missing from the block above.

- [x] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "$(cat <<'EOF'
docs: add 7 missing modules to CLAUDE.md's Package Structure diagram

flex_query.py, mcp_server.py, streaming.py, human_auth.py,
order_confirm.py, web_scraper.py, and scrape_fallback.py all exist and
each already have their own full section elsewhere in CLAUDE.md, but
were missing from the top-level file map. Also corrected the
client.py endpoint count comment from 79 to 75 (actual public method
count on IBKRClient, verified by grep).
EOF
)"
```

---

## Task 3: Fix `CLAUDE.md`'s market calendar context example

**Files:**
- Modify: `CLAUDE.md:404-410`

- [x] **Step 1: Replace the example block**

Find (lines 404-410):
```python
# Trading calendar for the current + next year — holidays, half-days, session hours
ctx = SQLiteStore.get_market_calendar_context()          # NYSE + CME (default)
ctx = SQLiteStore.get_market_calendar_context(["XLON"])  # add LSE

# Returns: { "generated_at": "...", "exchanges": { "XNYS": { "holidays": [...], ... }, ... } }
```

Replace with:
```python
# Trading calendar for the current + next year — holidays, half-days, session hours
ctx = SQLiteStore.get_market_calendar_context()            # default: 20 exchanges (G20 + Eurex)
ctx = SQLiteStore.get_market_calendar_context(["XLON"])     # REPLACES the default — returns XLON only, not default+XLON

# Returns: { "today": "...", "is_trading_day": bool, "last_trading_day": "...",
#            "next_trading_day": "...", "primary_exchange": "XNYS",
#            "holidays_by_exchange": { "XNYS": ["2026-01-01", ...], "CME": [...], ... } }
# See README.md's "Market Calendar" section for the full 20-exchange default list and a worked example.
```

- [x] **Step 2: Verify the stale shape is gone**

Run:
```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
grep -n '"generated_at"\|NYSE + CME (default)\|# add LSE' CLAUDE.md
```
Expected: no output (empty).

- [x] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "$(cat <<'EOF'
docs: fix stale get_market_calendar_context() example in CLAUDE.md

Three separate inaccuracies in one code block: the "NYSE + CME
(default)" comment (actual default is 20 exchanges, G20 + Eurex,
confirmed in store.py); the shown return shape (generated_at/exchanges
keys don't exist — live-verified real shape is today/is_trading_day/
last_trading_day/next_trading_day/primary_exchange/holidays_by_exchange,
matching what README.md already showed correctly); and the "add LSE"
comment, which implies passing a custom exchange list is additive when
it actually replaces the default list entirely.
EOF
)"
```

---

## Task 4: Fix stale version examples in `CLAUDE.md`

**Files:**
- Modify: `CLAUDE.md:16`, `CLAUDE.md:718-725`

**This task edits documentation text only. Do not run `git tag` or `git push` for any real tag as part of this task — Step 1 and Step 2 below only change example strings inside markdown code fences.**

- [x] **Step 1: Fix the pinned-version install example**

Find (line 16):
```markdown
# Pinned version
pip install git+https://github.com/stephus182/ibkr_core_mcp.git@v0.1.0
```

Replace with:
```markdown
# Pinned version
pip install git+https://github.com/stephus182/ibkr_core_mcp.git@v1.0.0
```

- [x] **Step 2: Fix the "Publishing a New Version" section**

Find (lines 718-725):
```markdown
## Publishing a New Version

```bash
git tag v0.3.0
git push origin v0.3.0
```

Consumers pin to: `pip install git+https://github.com/stephus182/ibkr_core_mcp.git@v0.3.0`
```

Replace with:
```markdown
## Publishing a New Version

Check the current latest tag first — do not reuse an existing one:

```bash
git tag -l --sort=-v:refname | head -1
```

Then tag and push the next version (semver — bump patch/minor/major as appropriate for the change):

```bash
git tag vX.Y.Z
git push origin vX.Y.Z
```

Consumers pin to: `pip install git+https://github.com/stephus182/ibkr_core_mcp.git@vX.Y.Z`
```

- [x] **Step 3: Verify the stale tags are gone from the text**

Run:
```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
grep -n "v0\.1\.0\|v0\.3\.0" CLAUDE.md
```
Expected: no output (empty).

- [x] **Step 4: Confirm this task made no actual git tag/push (safety check)**

Run:
```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
git tag -l | sort -V
```
Expected: identical output to before this task started — `v0.1.0 v0.2.0 v0.3.0 v0.4.0 v1.0.0`, nothing new added. If a new tag appears, something went wrong — do not push it; ask before proceeding.

- [x] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "$(cat <<'EOF'
docs: fix stale version examples in CLAUDE.md

Install section pinned to @v0.1.0 (the very first tag ever cut);
README.md's equivalent example already correctly used @v1.0.0 (current
actual latest, confirmed via git tag -l and pyproject.toml). Publishing
section instructed `git tag v0.3.0` as if it were the next version to
create, but v0.3.0 was already tagged and released — a contributor
following those exact commands literally would try to recreate an
existing tag. Replaced with a vX.Y.Z placeholder plus an explicit
`git tag -l --sort=-v:refname` check for the real current latest.
EOF
)"
```

---

## Task 5: Final verification sweep

**Files:** none modified — read-only verification of Tasks 1-4.

- [x] **Step 1: Full stale-reference grep across both files**

Run:
```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
grep -n "LAPolicyDeviceOwnerAuthenticationWithBiometrics\|no password fallback\|generated_at.*exchanges\|NYSE + CME (default)\|v0\.1\.0\|v0\.3\.0\|All 79 IBKR" README.md CLAUDE.md
```
Expected: no output (empty). This re-checks every literal string this plan set out to remove, in one pass.

- [x] **Step 2: Confirm the Package Structure diagram is complete**

Run:
```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
comm -23 <(ls ibkr_core_mcp/*.py | xargs -n1 basename | grep -v "^_" | sort) <(grep -oP '(?<=├── |└── )[a-z_]+\.py' CLAUDE.md | sort -u)
```
Expected: no output (empty).

- [x] **Step 3: Confirm no source code changed**

Run:
```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
git diff main --stat -- ibkr_core_mcp/
```
(Replace `main` with the actual base branch this work started from if different.)
Expected: no output (empty) — this plan must not have touched any file under `ibkr_core_mcp/`.

- [x] **Step 4: Confirm no new git tags were created**

Run:
```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
git tag -l | sort -V
```
Expected: `v0.1.0`, `v0.2.0`, `v0.3.0`, `v0.4.0`, `v1.0.0` — same 5 tags as before this plan started, nothing added.

- [x] **Step 5: Read through both files once, end to end**

Open `README.md` and `CLAUDE.md` and read the sections touched by Tasks 1-4 (Requirements table, Security section, Package Structure, Portfolio Analytics, Install, Publishing a New Version) to confirm they read naturally and consistently with each other — not just that the grep checks pass. Look specifically for any place the two files describe the same fact differently (e.g., Gate 1's policy is now described identically in both).

No commit for this task — it's verification only. If Task 5 finds nothing, the plan is complete.
