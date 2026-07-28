# ibkr_core_mcp Documentation

This directory holds three kinds of documentation. See `CLAUDE.md`'s Design spec line and
Pointers section for the most commonly needed links; this file is the full catalog.

## Reference

Living documentation describing current behavior — read on demand, updated in place as the
code changes.

| File | Description |
| --- | --- |
| [`api-reference.md`](api-reference.md) | Full reference for all `IBKRClient` methods — request/response shapes, exceptions raised |
| [`symbology-reference.md`](symbology-reference.md) | How a ticker becomes a contract — why `/trsrv/stocks` + `isUS`, why a ticker is not a unique key, and the ask-don't-guess rule (the IGV/MXN defect) |
| [`tools-reference.md`](tools-reference.md) | Full reference for all 42 `ClaudeToolkit` tools (40 core + 2 web scraper) — parameters, output shapes |
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

Point-in-time records of what was decided and how — a design spec captures the why/what, an
implementation plan captures the how, for both features and fixes. Every filename carries a
`YYYY-MM-DD-<topic>` prefix, so sorting the directory by filename gives chronological order;
where a `-design.md`/`-plan.md` suffix is present it distinguishes the two documents for the
same topic, but not every file uses the suffix — some use a plain descriptive topic name
instead. These are not living documents — once written they are not edited to reflect later
changes; a later revisit gets a new dated file. Browse the directory directly rather than
looking for an index entry here.

## Audits (`docs/audits/`)

Point-in-time investigation and verification records — security audits, code audits, and
accumulated test-run logs ([`live-test-log.md`](audits/live-test-log.md)). Same treatment as
Plans: dated filenames, not retroactively edited. `audit-evidence/` holds raw supporting data
for the 2026-07 `claude_tools.py` audit. Browse directly rather than looking for an index
entry here.
