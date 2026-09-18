# ibkr_core_mcp Documentation

The full catalog. `CLAUDE.md`'s Design spec line and Pointers section carry the handful of
links needed most often; everything the project documents is indexed here.

Three kinds of document live under `docs/`, and the difference is about **maintenance, not
topic**:

| Kind | Where | Contract |
|---|---|---|
| **Reference** | `docs/*.md` | Living. Describes current behaviour; edited in place as the code changes. If it's wrong, fix it. |
| **Plans** | `docs/plans/` | Point-in-time. What was decided and how. Never retroactively edited — a revisit gets a new dated file. **Gitignored**, so deletions are permanent. |
| **Audits** | `docs/audits/` | Point-in-time. What was found on a given day, with evidence. Never retroactively edited. |

---

## Reference — by theme

Every living document, grouped by what you'd be doing when you need it.

### Getting the thing running

| File | Description |
|---|---|
| [`gateway-auth-reference.md`](gateway-auth-reference.md) | Gateway login walkthrough, `GatewayManager`, headless `TokenAuth`. **Start here** — nothing else works until the gateway is authenticated |
| [`windows-setup.md`](windows-setup.md) | Windows install/run guide — what works out of the box vs. what needs an extra step (Touch ID gate) |
| [`consumers.md`](consumers.md) | Which projects install this package, and what they use it for |

### Calling the API

| File | Description |
|---|---|
| [`api-reference.md`](api-reference.md) | Full reference for all `IBKRClient` methods — request/response shapes, exceptions raised |
| [`api-usage-examples.md`](api-usage-examples.md) | Per-module usage examples (Setup, Market Data, Technical Indicators, Backtesting, Portfolio Analytics, Claude AI Tool Layer, PineScript Generation) |
| [`symbology-reference.md`](symbology-reference.md) | How a ticker becomes a contract — why `/trsrv/stocks` + `isUS`, why a ticker is not a unique key, and the ask-don't-guess rule (the IGV/MXN defect) |
| [`ibkr-api-behaviors-reference.md`](ibkr-api-behaviors-reference.md) | Known IBKR API behaviors, **verified not assumed** — read before diagnosing anything surprising |

### Placing orders (two human gates, no bypass)

| File | Description |
|---|---|
| [`order-management-examples.md`](order-management-examples.md) | Order management code examples (read-only, place/confirm, manual reply-chain control, modify/cancel, GTC quarter-end auto-cancel) |
| [`security-architecture.md`](security-architecture.md) | **Living security design** — principals and threat model (incl. AI-generated changes), privilege tiers, the trust-boundary map, the eleven invariants each with its enforcing test, subsystem designs (gates, sandbox, SSRF, redaction, transport), CI as a security instrument, the dated decision log, change recipes. `SECURITY.md` is the control inventory; the audits are the evidence |

> The gate policy itself — Touch ID → visual confirmation, enforced inside `IBKRClient`,
> with **one Touch ID for a whole confirmation chain and a dialog for every reply in it** —
> is specified in `CLAUDE.md` and `README.md`'s Security section, and its rationale is in
> [`plans/archive/security-orders/HISTORY.md`](plans/archive/security-orders/HISTORY.md).

### Tool layers (Claude + MCP)

| File | Description |
|---|---|
| [`tools-reference.md`](tools-reference.md) | Full reference for all 44 `ClaudeToolkit` tools (40 core + 4 web) — parameters, output shapes |
| [`mcp-server-reference.md`](mcp-server-reference.md) | MCP Server (install, stdio/SSE transports, 46 tools, 4 resources, price alerts, TradingView integration) |

### Historical trade data (Flex)

| File | Description |
|---|---|
| [`flex-query-reference.md`](flex-query-reference.md) | Historical Trade Data / Flex Queries — setup, complete-capture import, **realised-P&L semantics settled against IBKR** (no open/close filter; `Trade == Lot + WashSale`) |
| [`audits/flex-xml-structure-audit.md`](audits/flex-xml-structure-audit.md) | **Generated** — every element and attribute IBKR emits, with types and cardinality. Regenerate with `scripts/audit_flex_xml.py`; values redacted by allowlist. Machine-readable twin: `audits/audit-evidence/flex-xml-structure.json` |

### Web scraping

| File | Description |
|---|---|
| [`web-scraper-reference.md`](web-scraper-reference.md) | The 4 web tools — tunables, credit model, paywalled-site logins, per-host quirks, troubleshooting, live-test log |
| [`web-scraping-methodology.md`](web-scraping-methodology.md) | **How to approach a host you haven't scraped before** — the four-way matrix, what each failure shape looks like, where we stop on the anti-bot ladder |

### Working on the package itself

| File | Description |
|---|---|
| [`test-coverage.md`](test-coverage.md) | Current unit/integration test counts, per-module coverage with every gap explained, and the commands to re-measure |
| [`external-docs-reference.md`](external-docs-reference.md) | Official documentation URLs for every external API — the **docs-first** rule's source list |
| [`python-package-landscape.md`](python-package-landscape.md) | Charting/quant/stats package landscape — what we have, what's a real gap, and what would duplicate existing code. Read before adding a dependency |

---

## Plans (`docs/plans/`)

What was decided and how — a design spec captures the why/what, an implementation plan the
how, for both features and fixes. Filenames carry a `YYYY-MM-DD-<topic>` prefix so sorting
by name gives chronological order; a `-design.md`/`-plan.md` suffix distinguishes the two
documents for one topic where both exist.

**Start at [`plans/INDEX.md`](plans/INDEX.md).** Reorganized 2026-08-11: the root holds only
live plans; finished work moves to `plans/archive/<theme>/`, where each theme's `HISTORY.md`
distils what it decided and why. Read the `HISTORY.md` before the originals — those were
written to be executed, not read.

| Theme | Covers |
|---|---|
| [`archive/web-scraper/`](plans/archive/web-scraper/HISTORY.md) | Firecrawl → fallback ladder → cloud rung → all of it deleted; the four-tool end state |
| [`archive/docs/`](plans/archive/docs/HISTORY.md) | Docs reorg, the IBKR docs-site move and its 200-that-means-404 traps, `ruff D` |
| [`archive/security-orders/`](plans/archive/security-orders/HISTORY.md) | The two human-auth gates, chained reply confirmation, the six-finding security pass |
| [`archive/core-buildout/`](plans/archive/core-buildout/HISTORY.md) | Phases 1–3 (foundation, Pydantic, MCP + streaming), publication readiness |
| [`archive/testing-audits/`](plans/archive/testing-audits/HISTORY.md) | The `claude_tools` audit; the flat-file → `tests/claude_tools/` restructure |
| [`archive/infrastructure/`](plans/archive/infrastructure/HISTORY.md) | Backtest subprocess isolation; `GatewayManager` silent-exception fix |

⚠️ **A plan's checkboxes and `Status:` line are not status signals.** Several shipped plans
show every box unticked. Verify against the code.

---

## Audits (`docs/audits/`)

Point-in-time investigation and verification records, plus the accumulated live-test log.
Dated filenames, not retroactively edited.

| Audit | What it covers |
|---|---|
| [`live-test-log.md`](audits/live-test-log.md) | **Running log** — every live integration run against a real gateway/Drive/Firecrawl, dated. Append, don't rewrite |
| [`claude-tools-audit-2026-07.md`](audits/claude-tools-audit-2026-07.md) | The full `claude_tools.py` audit — 42 tool descriptions vs official docs, token measurements, the follow-up register |
| [`2026-08-10-flex-dataset-audit.md`](audits/2026-08-10-flex-dataset-audit.md) | Flex dataset completeness — the live data-loss window and the row deleted |
| [`2026-07-22-code-quality-audit.md`](audits/2026-07-22-code-quality-audit.md) | `tests/` mypy gap — 1,164 → 183 → 0 errors, and the `tests.*` override rationale |
| [`2026-06-30-quote-access-matrix.md`](audits/2026-06-30-quote-access-matrix.md) | Which quote fields the account's subscriptions actually return, per instrument type |
| [`release-readiness-audit-2026-09-16.md`](audits/release-readiness-audit-2026-09-16.md) | **Latest** — the whole-package release-readiness audit and its running register: 173 findings across security, API, tools, data, docs and the web scraper, each with its evidence and its closing test; the per-domain counts are machine-checked by `scripts/audit/check_register.py`. Plan: `plans/2026-09-16-release-readiness-audit.md` |
| [`owasp-mcp-guide-applicability-2026-09-14.md`](audits/owasp-mcp-guide-applicability-2026-09-14.md) | The OWASP *Practical Guide for Secure MCP Server Development* v1.0 mapped item by item onto this deployment — 49 items classified applies / partly / not applicable, with what each decision rests on; the principal external security baseline since 2026-09-14 |
| [`security-architecture-audit-2026-09-13.md`](audits/security-architecture-audit-2026-09-13.md) | Security *architecture* audit: trust-boundary map, 10 invariants, 3 confirmed issues (sandbox arbitrary file read/write, SSE DNS rebinding) fixed test-first, the `tests/security/` constitution, pip-audit + gitleaks gates, probe evidence and the red→green record |
| [`security-audit-2026-07-11.md`](audits/security-audit-2026-07-11.md) | Security audit — 6 findings (4 High, 2 Medium), all fixed and verified in code |
| [`security-audit-2026-06-23.md`](audits/security-audit-2026-06-23.md) · [`-06-10`](audits/security-audit-2026-06-10.md) · [`-05-27`](audits/security-audit-2026-05-27.md) · [`-05-26`](audits/security-audit-2026-05-26.md) · [`-05-25`](audits/security-audit-2026-05-25.md) | Earlier security passes, superseded by the 2026-07-11 audit but kept as the dated record |

`audit-evidence/` holds raw supporting data — dependency graphs, token counts, timing runs
and page captures for the 2026-07 `claude_tools.py` audit, plus `flex-xml-structure.json`.

**Two files here break the "dated, never edited" rule, deliberately.**
`flex-xml-structure-audit.md` and its `audit-evidence/flex-xml-structure.json` twin are
**generated**, not written: `scripts/audit_flex_xml.py` rewrites both (and
`ibkr_core_mcp/flex_schema.py`) from a real Flex statement whenever IBKR emits an attribute
we have not seen. They carry no date because they describe the schema as of the last run,
not a finding as of a day. Do not hand-edit either — change the generator. Their paths are
the script's `--md-out` / `--json-out` defaults, so moving one means moving the default too.

---

## Coverage check

Everything under `docs/` is indexed above: **18 reference documents** (17 at `docs/` root
plus the generated Flex schema report under `audits/`), **14 audits**, and the plans index
with its 6 archive themes. Nothing is orphaned — and that is now a test, not a sentence:
`test_every_tracked_reference_and_audit_document_is_in_the_docs_catalog` fails the suite for
any `docs/*.md` or `docs/audits/*.md` this file does not name. It was added on 2026-09-17,
when this paragraph read "Nothing is orphaned. Last verified 2026-09-13" while the two most
recent audits — the OWASP applicability decision and the release-readiness register — were
missing from the table above.
