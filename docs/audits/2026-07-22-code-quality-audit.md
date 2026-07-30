# Code-Quality Audit — ruff/mypy/pytest, tests/ gap closure

**Date:** 2026-07-22 · **Branch:** `chore/2026-07-22-code-quality-audit` · 14 files changed, +123/-105

## 1. Summary

This repo's tooling was already mature going into this pass: ruff has a real, reasoned
rule set (`E,F,W,I,UP,S,B`), `[tool.mypy]` already ran `strict = true` against
`ibkr_core_mcp` itself (25 files, 0 errors), and pytest had markers/asyncio config in
place. The one real gap: `[tool.mypy]` never set `files =`, so `tests/` (39 modules) had
never actually been type-checked by CI or locally — only `mypy ibkr_core_mcp` ran.

Adding `tests` to `files` surfaced **1164 errors in 39 files**. Almost all of that (**981,
84%**) was `no-untyped-def`/`no-untyped-call` — this codebase's tests have zero signature
annotations by established convention (verified directly: 0 annotations across a sample
of existing test files before this pass). Demanding full `strict` on 747 tests' worth of
function signatures would be a large, disproportionate diff for no safety benefit, so a
narrow per-module override relaxes exactly those three flags for `tests.*` while every
other `strict` check — including `check_untyped_defs`, which still type-checks the *body*
of every untyped test function — stays on. That left **183 real findings** across 12
files, all individually triaged and fixed. Final state: **mypy 0/0 (68 files), ruff 0/0,
747/747 non-integration tests passing** (unchanged from the pre-pass baseline — no tests
added or removed, only fixed).

Two client-facing production files were touched, both typing-precision fixes with zero
behavior change: `ibkr_core_mcp/web_scraper.py` (return-type annotations widened to match
an already-documented return shape) and `.github/workflows/ci.yml` (mypy invocation
updated to match the new `files =` config). `ibkr_core_mcp/client.py` — the
order-execution surface named in the task as safety-critical — was **not modified**; its
2 test-file findings were pure test-side type-annotation additions.

## 2. Scope

- Ruff: already clean, config already reasoned (per-file-ignores with real justifications
  for each ignored rule). Nothing to add; ran throughout as the safety net.
- Mypy: the actual work. `ibkr_core_mcp/` strict-mode baseline was already 0 errors and
  stayed there; `tests/` had never been checked at all.
- Pytest: `-m "not integration"` run before starting, after every batch of file-level
  fixes, and at the end. Never ran `integration`-marked tests (need a live IBKR gateway).
- No sibling editable-install gotcha here (unlike claudia_ui's `ibkr_core_mcp` dependency)
  — this package has no editable local dependencies of its own.

## 3. Environment

| | |
|---|---|
| Python | 3.11.15 (fresh `.venv` in `.worktrees/code-quality-audit`) |
| Tool versions | ruff 0.15.22, mypy 2.3.0, pytest 9.1.1 |
| Install | `pip install -e ".[dev,server]"` — the `server` extra (`mcp`, `starlette`, `uvicorn`) is required for `tests/test_mcp_server.py`'s 17 tests to even collect; `.[dev]` alone produces 17 `ModuleNotFoundError` failures, none of which are a regression from this pass |

## 4. Mypy — Before / After

**Before:** `[tool.mypy]` had `strict = true`, `ignore_missing_imports = true`, and several
targeted per-module overrides — but no `files =`. `mypy ibkr_core_mcp` (the only invocation
anyone ever ran, including CI) was clean. Running `mypy ibkr_core_mcp tests` fresh (measured
directly, not assumed) found:

**1164 errors, 39 files:**

| Code | Count | Disposition |
|---|---|---|
| `no-untyped-def` | 866 | Configured away for `tests.*` — see below |
| `no-untyped-call` | 115 | Configured away for `tests.*` — see below |
| `union-attr` | 130 | Triaged individually — mostly one repeated pattern (below) |
| `attr-defined` | 26 | Triaged individually — module re-export access pattern |
| `arg-type` | 8 | Triaged individually |
| `type-arg` | 4 | Triaged individually — bare `dict` |
| `var-annotated` | 3 | Triaged individually |
| `index` | 3 | Triaged individually |
| `comparison-overlap` | 3 | Triaged individually — a real production annotation bug |
| `operator` | 2 | Triaged individually |
| `misc` | 2 | Triaged individually — dynamic-base-class pattern |
| `valid-type` | 1 | Triaged individually — same dynamic-base-class pattern |
| `unused-ignore` | 1 | Removed (stale, no-longer-needed ignore) |

**Config decision — measured, not assumed:** a draft override disabling only
`disallow_untyped_defs`/`disallow_incomplete_defs`/`disallow_untyped_calls` for `tests.*`
(everything else, including `check_untyped_defs`, `warn_unreachable`, `strict_equality`,
stays on) was tested before committing to it. Re-running `mypy` under that draft dropped
the count from 1164 to exactly **183** — confirming the 981 configured-away findings were
purely the missing-annotation boilerplate, and every genuine type-correctness signal
(`union-attr`, `attr-defined`, `arg-type`, etc.) survived the override intact, in 12 files:

```toml
[tool.mypy]
python_version = "3.12"
strict = true
ignore_missing_imports = true
files = ["ibkr_core_mcp", "tests"]

[[tool.mypy.overrides]]
module = "tests.*"
disallow_untyped_defs = false
disallow_incomplete_defs = false
disallow_untyped_calls = false
```

**183 findings, itemized by file (exact, reproducible via `grep -cE '^tests/.*: error:'`):**

| File | Count | Disposition |
|---|---|---|
| `tests/test_mcp_server.py` | 110 | Root-cause fix — 2 shared typed helpers replace 7 duplicated blocks |
| `tests/test_streaming.py` | 26 | Root-cause fix — `isinstance` narrowing at 7 sites |
| `tests/test_order_confirm.py` | 16 | Root-cause fix — patch the stdlib singleton directly, not via module re-export (11); local dict → 2 typed variables (5) |
| `tests/test_backtest.py` | 11 | Root-cause fix — import exceptions from `ibkr_core_mcp.exceptions` (9); documented `# type: ignore[misc,valid-type]`, dynamic base class (1); patch `threading` directly (1, same pattern as `test_order_confirm.py`) |
| `tests/test_local_browser.py` | 8 | `setattr(...)  # noqa: B010`, faked `ModuleType` (5); 2 explicit type annotations; 1 `list[dict]` → `list[dict[str, object]]` |
| `tests/test_web_scraper.py` | 4 | Root-cause fix in **production** code — `web_scraper.py` return-type precision, see below |
| `tests/test_crawl4ai_live.py` | 2 | Documented `# type: ignore[misc,valid-type]`, same dynamic-base-class pattern |
| `tests/test_client.py` | 2 | Explicit type annotations on 2 local test dict literals (non-order-execution paths) |
| `tests/test_store.py` | 1 | `dict` → `dict[str, object]` |
| `tests/test_rate_limiter.py` | 1 | `dict` → `dict[str, object]` |
| `tests/claude_tools/test_web_scraping.py` | 1 | Removed a stale `# type: ignore[method-assign]` (mypy itself flagged it unused) |
| `tests/claude_tools/test_trades.py` | 1 | `dict` → `dict[str, object]` |

**Notable clusters:**

- **`tests/test_mcp_server.py` (110 of 183)** — every resource/tool test drove the MCP
  SDK's low-level `server.request_handlers[type(req)](req)` dict directly, then accessed
  `.root.contents[0].text` / `.root.tools` on the resulting `ServerResult`, a ~15-member
  union type the SDK itself declares. mypy correctly can't narrow an unchecked attribute
  access on a union that wide. Fix: two small typed helpers
  (`_list_tool_names`, `_read_resource_text`) that do the real `isinstance` narrowing once,
  replacing 7 duplicated blocks of untyped dict-param construction and unchecked access.
  Root-cause fix, not suppression — and it deleted more lines than it added.
- **`tests/test_streaming.py` (26)** — `IBKRWebSocket._parse_message()` is declared
  `-> LiveQuote | list[TradeExecution] | PnLUpdate | None` (a real 3-way tagged union).
  Tests asserted only `is not None` before accessing variant-specific attributes. Fix:
  `assert isinstance(quote, LiveQuote)` / `assert isinstance(pnl, PnLUpdate)` at each of 7
  sites — narrows the type *and* strengthens the test (a future dispatch-logic bug now
  fails with a clear assertion instead of a confusing `AttributeError`).
- **`tests/test_order_confirm.py` / `test_backtest.py` (11 + 2)** — tests patched
  `oc.sys.platform` / `oc.subprocess.run` / `backtest.threading.Event` through the module's
  *imported* reference, which mypy's `implicit_reexport` check under `strict` doesn't
  recognize as an officially exported attribute. Since `sys`/`subprocess`/`threading` are
  stdlib module singletons, patching the test file's own `import sys` (etc.) reference
  patches the exact same object the production module sees — zero behavior change, and it
  removes an antipattern rather than suppressing it.
- **`tests/test_local_browser.py` (5 of 8)** — three test helpers built a fake `crawl4ai`
  module via `types.ModuleType("crawl4ai")` then set `fake_module.AsyncWebCrawler = ...`.
  A plain `ModuleType` has no such static attribute. Ruff's `B010` (no-op `setattr`) and
  mypy's `attr-defined` disagree on the right shape here — `setattr()` is the only form
  that satisfies mypy (dynamic calls aren't attribute-checked) while assignment satisfies
  ruff. Resolved with `setattr(...)  # noqa: B010` plus a one-line reason, since the module
  is deliberately being faked wholesale for `sys.modules` injection, not a normal object.
- **Dynamic base classes (2 sites, `test_backtest.py` + `test_crawl4ai_live.py`)** —
  `_real_event_cls = threading.Event; class X(_real_event_cls): ...` and the equivalent
  pattern for `crawl4ai.AsyncWebCrawler`. mypy doesn't treat a local variable assignment as
  a type alias, so subclassing it is flagged (`misc` + `valid-type`). Documented
  `# type: ignore[misc,valid-type]` — fixing this properly would mean restructuring how
  these tests monkeypatch a live subprocess/browser class hierarchy, disproportionate to
  what's a correct, working, already-reviewed test pattern.
- **`web_scraper.py` real production bug, 4 sites** — `FirecrawlClient.search()` and
  `.crawl()` (plus an internal helper and a loop variable) were annotated
  `-> list[dict[str, str]]`, but both methods' own docstrings already documented a
  `"metadata": dict` field returned alongside the `str` fields — the annotation didn't
  match the method's own documented contract. Widened to `list[dict[str, Any]]` in all 4
  matching spots (`Any` already imported). Zero behavior change — callers were never
  restricted by the narrower type since Python doesn't enforce it at runtime — but it's a
  genuine annotation-precision bug in production code, not a test-side workaround, so it's
  called out separately from the test-only fixes above.

**After: 0 errors, 68 source files** (re-confirmed with a fresh `.mypy_cache`).

## 5. Ruff

No config changes — the existing `select = ["E","F","W","I","UP","S","B"]` set with its
reasoned `ignore`/per-file-ignore list was already clean and stayed clean throughout.
`ruff format --check .` also clean (73 files). Every edit in this pass was re-checked
against ruff after landing; the `setattr`/`noqa` tension in §4 was the only place ruff and
mypy pulled in different directions.

## 6. Test Suite

Baseline reproduced first: **747 passed, 0 failures** (`pytest -m "not integration"`,
after installing the `server` extra — see §3). Re-run after every file-level fix batch and
once more at the very end: **747 passed, 0 failures**, unchanged. No new tests were added
or removed — every fix here was either a type-annotation addition, a narrowing
`isinstance`/`assert`, or a mechanically-equivalent patch-target swap (`oc.sys` →
`sys`), none of which change what a test actually exercises.

## 7. Order-Execution Safety Check

Per the task's explicit heightened-scrutiny requirement: `ibkr_core_mcp/client.py`
(`place_order`, `modify_order`, `cancel_order`, `reply_order`, and the two `_and_confirm`
chain methods) was **not edited** in this pass. Its 2 test-file findings
(`tests/test_client.py:286,1071`, both `var-annotated` on local test dict literals) were
resolved with type annotations only, in test code, on non-order test paths (a
`cancel_order` dialog-args capture and an option-chain strikes payload). No gate logic,
parameter handling, rounding, or coercion was touched anywhere in this pass.

## 8. CI

`.github/workflows/ci.yml`'s `Type check (mypy)` step ran `mypy ibkr_core_mcp` explicitly
— now that `[tool.mypy]` sets `files = ["ibkr_core_mcp", "tests"]`, updated to a bare
`mypy` invocation so CI actually checks what the config now declares, matching local usage.

## 9. Overall Assessment

The tooling maturity this repo already had (real ruff rule selection, `strict = true` on
the main package, security-lint rules via `S`) meant this pass was almost entirely about
closing one specific, well-scoped gap — `tests/` was never in mypy's `files` — rather than
building anything from scratch. The 1164→183→0 numbers look dramatic but the substance is
modest: 84% was boilerplate the codebase's own testing convention already accepted, and
the 183 real findings clustered into a handful of repeated patterns (one MCP SDK
union-narrowing idiom, one stdlib-module-patching antipattern, one dynamic-base-class
idiom) rather than 183 independent problems. One genuine, if minor, production typing bug
was found and fixed (`web_scraper.py`'s return-type/docstring mismatch). Nothing in
`client.py`'s gated order-execution surface was touched. **Green across the board: mypy
0/0 (68 files), ruff 0/0, pytest 747/747.**

## Appendix: Commands Used

```bash
# Environment
python3.11 -m venv .venv
pip install -e ".[dev,server]"

# Baselines
rm -rf .mypy_cache .ruff_cache
mypy ibkr_core_mcp tests --show-error-codes   # 1164 errors, 39 files
ruff check . --statistics                       # clean

# Fix loop (repeated per file)
mypy tests/<file>.py --show-error-codes
ruff check tests/<file>.py
pytest tests/<file>.py -m "not integration" -q

# Final
mypy                                # Success: no issues found in 68 source files
ruff check .                        # All checks passed!
ruff format --check .               # 73 files already formatted
pytest -m "not integration" -q      # 747 passed, 86 deselected
```
