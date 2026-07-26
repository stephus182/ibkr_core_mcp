# Docs Accuracy Pass + pydocstyle `D` Enablement — Plan

**Date:** 2026-07-25
**Goal:** Bring the living documentation back to factual accuracy (IBKR doc-site migration,
post-Panel-migration claims), reduce now-useless Chainlit references, close all 39 docstring
coverage gaps, and enable `ruff` `pydocstyle` `D` so the coverage gaps cannot silently return.

**Scope:** Living docs only — `README.md`, `CLAUDE.md`, `SECURITY.md`, `CHANGELOG.md`,
`docs/*.md`, plus package docstrings in `ibkr_core_mcp/`.
**Explicitly out of scope:** `docs/plans/` and `docs/audits/`. Those are dated point-in-time
records; their Chainlit references were accurate on their date and must not be rewritten.
History is not falsified.

---

## Findings

### F1 — IBKR migrated the entire Web API documentation site (81 stale deep links)

The old single-page reference at `www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/`
has been replaced by a Fern-hosted docs site at `interactivebrokers.com/docs/web-api/…`.

Verified 2026-07-25:
- `curl` of the old URL returns **HTTP 200** with `rel="canonical"` =
  `https://interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/introduction`.
- The old page body is now an 8.7 KB SPA shell, versus the 808 KB single-page reference
  captured in `docs/audits/audit-evidence/scrapes/cpapi-v1.md` on 2026-07-02.
- **Every `#anchor` fragment is silently dead**: the redirect drops the fragment and lands the
  reader on the Introduction page. A link checker sees 200 and reports success — this is why
  the rot went unnoticed.

Authoritative new index: `https://www.interactivebrokers.com/docs/web-api/llms.txt`
(517 pages; 241 fetched as markdown for mapping). Any page also serves clean markdown by
appending `.md`.

Stale-link distribution:

| File | Links |
|---|---|
| `docs/api-reference.md` | 75 |
| `docs/external-docs-reference.md` | 3 |
| `README.md` | 1 |
| `docs/gateway-auth-reference.md` | 1 |
| `docs/tools-reference.md` | 1 |
| **Total** | **81** |

Two anchors were already broken *before* the migration and are confirmed by the new
structure — they never existed on the old page either:

| File | Old anchor | Correct target |
|---|---|---|
| `docs/gateway-auth-reference.md:48` | `#rate-limiting` | `web-api-v-1-0-documentation/pacing-limitations` |
| `docs/api-reference.md:213` | `#sec-search` | `endpoints/contract/search-contract-by-symbol` |

Non-anchored old URLs (`…/web-api-changelog/`, `…/cpapi-v1/`) still resolve correctly via
redirect, but are updated to canonical new URLs for durability.

### F2 — `docs/python-package-landscape.md` charting section is factually wrong

The section headed *"Current state: no charting library exists anywhere in the pipeline"* is
false as of the Panel migration. Verified in `/Users/steph/Claude_Projects/claudia_ui`:

- `pyproject.toml` declares `panel>=1.9` **and** `bokeh>=3.7` as a direct dependency.
- `claudia/panel_chart.py` renders a **Bokeh candlestick chart** (segment wicks + two `vbar`
  glyphs, teal up / red down), shipped as Task 10.1 and verified live 2026-07-24.

Consequently these claims are stale and must be rewritten, not merely renamed:
- L24 "Neither `ibkr_core_mcp` nor `claudia_ui` … declares Matplotlib, Altair, Plotly …"
- L27 "`claudia_ui`'s only UI dependency is `chainlit>=2.0`"
- L28–30 the Chainlit `cl.Image`/`cl.Pyplot`/`cl.Plotly` rendering seam
- L41 Plotly "would be the natural pick … since Chainlit has first-class `cl.Plotly` support"
- L42 ECharts "No JS-frontend surface in `claudia_ui`" — Panel/Bokeh *is* a JS frontend surface
- L48 "Plotly is the best fit given Chainlit's built-in element support"

### F3 — Chainlit references to reduce or reframe

Living docs (in scope), 10 references:

| Location | Action |
|---|---|
| `README.md:108` | Reframe — "non-interactive environments" is the real point, not the framework |
| `README.md:360` | Reframe to a Panel button; the two-gate argument is framework-independent |
| `README.md:471` | Correct — ClaudIA is a **Panel**-based assistant |
| `docs/python-package-landscape.md` ×7 | Rewritten wholesale under F2 |

Package docstrings (3) — **reframe, do not delete.** The constraint they document is real and
still applies: Panel/Bokeh also runs a Tornado asyncio event loop, so the subprocess-owns-its-
own-main-thread design is still required. Make them framework-neutral ("the host application's
asyncio event loop"):

- `ibkr_core_mcp/_order_dialog.py:5`
- `ibkr_core_mcp/order_confirm.py:175`
- `ibkr_core_mcp/gateway/manager.py:14`

### F4 — WITHDRAWN (false positive)

An initial sweep flagged three `README.md` anchors as broken. They are **correct**. The fault
was in the checker: it collapsed consecutive whitespace to a single hyphen, whereas GitHub
emits one hyphen per space. Headings containing `(`, `&`, or `—` therefore produce a double
hyphen (`security--fingerprint-authentication`), exactly as the README already had them.
Re-verified with GitHub's slug rules: **all internal links and anchors across all 18 living
docs resolve.** No change made.

### F5 — 39 docstring coverage gaps

`ruff check ibkr_core_mcp/ --select D100,D101,D102,D103,D104,D105,D106,D107` → 39 findings:
D100 ×11 (module), D102 ×10 (public method), D107 ×15 (`__init__`), D103/D104/D105 ×1 each.

### F6 — `FirecrawlClient.crawl()` returns 0 pages silently on IBKR hosts

Diagnosed while verifying F1. The API key is valid and `search()`/`crawl()` both work
(control: `example.com` returned 1 page). But `crawl()` on `interactivebrokers.com` returns an
empty list with no error — the 2026-07-02 evidence run needed Firecrawl's `waitFor`/`proxy`
options, which the sanctioned client does not expose. **Documentation-only in this plan**;
a code fix is a separate change and is not undertaken here.

### Verified-correct (no action)

- Tool/endpoint counts: `claude_tools` 42, MCP 44 (42 + 2 alert tools), 4 resources,
  `client.py` 74 endpoints — all match the docs.
- Version `1.2.2` matches the latest tag `v1.2.2`.
- `get_regulatory_snapshot` removal is documented accurately.
- All 60 distinct non-IBKR external URLs return 200. The four apparent failures are all
  correct-by-design: `api.firecrawl.dev/v1` (API base, not a page), two `pip install …@vX.Y.Z`
  targets (not browsable), and `wsj.com` 401 (a paywall example in the scraper docs — the 401
  *is* the point).

---

## Tasks

Order matters: docs accuracy first, then docstrings, then the `D` gate, then `CLAUDE.md` /
`README.md` last (per the request) so they describe the finished state.

### Task 1 — Rewrite the 81 stale IBKR links

**Files:** `docs/api-reference.md` (75), `docs/external-docs-reference.md` (3),
`README.md` (1), `docs/gateway-auth-reference.md` (1), `docs/tools-reference.md` (1)

Apply the generated mapping in `link_map.tsv` (old anchor → new URL, resolved against IBKR's
own `llms.txt`). Base URL `https://www.interactivebrokers.com/docs/web-api/`.

- [ ] Apply mapping via scripted replace, one file at a time
- [ ] Re-run the external link checker; expect 0 failures
- [ ] `git commit -m "docs: repoint 81 IBKR Web API links to the migrated Fern doc site"`

### Task 2 — Fix the three broken internal anchors (F4)

- [ ] Correct the anchors to match the real headings in `SECURITY.md` / `CLAUDE.md`
- [ ] Re-run the internal link checker; expect "all internal links OK"

### Task 3 — Rewrite the charting section of `python-package-landscape.md` (F2)

- [ ] Replace the "no charting library" section with the Panel/Bokeh reality
- [ ] Update the Plotly and ECharts rows and the recommendation
- [ ] `git commit -m "docs: correct charting landscape for the Panel/Bokeh migration"`

### Task 4 — Reframe the 3 package docstrings (F3)

- [ ] Make each framework-neutral; keep the technical reason intact
- [ ] `pytest -m "not integration"` still green

### Task 5 — Close all 39 docstring gaps (F5)

- [ ] Write real docstrings — no filler restating the name
- [ ] `ruff check ibkr_core_mcp/ --select D100,D101,D102,D103,D104,D105,D106,D107` → 0

### Task 6 — Enable pydocstyle `D` (F5 gate)

Mirror `claudia_ui`'s configuration, set 2026-07-25 by the same owner, so both repos enforce
the same rule: enable `D` for the **coverage** rules, ignore the formatting-opinion codes that
conflict with this codebase's multi-paragraph, cites-the-source-URL docstring style.

```toml
select = [..., "D"]
ignore = [
    ...
    "D203",  # incompatible with D211 (ruff warns and drops it anyway)
    "D205",  # blank line required between summary and description
    "D209",  # multi-line closing quotes on their own line
    "D213",  # summary on the second line — see the correction below
    "D301",  # backslash in docstring requires a raw string
    "D400",  # summary must end with a period
    "D401",  # summary must be in imperative mood
    "D413",  # blank line required after the last section
    "D415",  # summary must end with punctuation
]

[tool.ruff.lint.per-file-ignores]
"tests/*" = [..., "D"]
"scripts/audit/*" = ["D"]
```

**Correction — `D212` vs `D213`.** This plan originally proposed ignoring `D212`, assuming the
house style opened the summary on the line below `"""`. Measured instead of assumed: **346
docstrings open on the first line, 36 on the second.** So the house style is first-line, and
`D213` is the one to ignore — matching `claudia_ui` exactly. The 36 stragglers were normalised
with `ruff check --select D212 --fix` (mechanical, auto-fixable).

**Also added:** `scripts/audit/*` is exempt from `D`. Those five files are one-off evidence
scripts committed as run, the same category as `claudia_ui`'s excluded `docs/probes`. The
exemption is scoped to `D` only — every other rule still applies to them.

**One D403 was not auto-fixed.** `order_confirm.py` had a docstring opening `"""tkinter
fallback dialog…`; ruff's fix capitalises the first word, which would have produced `Tkinter`
— wrong, since the module name is lowercase. Reworded to `"""Fallback tkinter dialog…` instead.

- [x] Apply config; `ruff check .` clean; `ruff format --check .` clean

### Task 7 — Update `CLAUDE.md` and `README.md` (last)

- [ ] `README.md`: Chainlit → Panel (3 refs), document the `D` lint gate
- [ ] `CLAUDE.md`: add `D` to the Linting section; note the IBKR doc-site migration under
      the "API Docs First" convention, including the new `llms.txt` index and `.md` suffix
- [ ] Final `ruff check . && ruff format --check . && mypy && pytest -m "not integration"`
