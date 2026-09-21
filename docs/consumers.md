# Consuming Projects

| Project | Repo | Uses |
|---|---|---|
| ClaudIA Trading Assistant | `github.com/stephus182/claudia_ui` | IBKRClient, GDriveCache, SQLiteStore, ClaudeToolkit, GatewayManager |
| Order Management UI | (future) | IBKRClient (order endpoints), SQLiteStore, ClaudeToolkit |
| ML Feature Pipeline | (future) | IBKRClient, GDriveCache, SQLiteStore, indicators |
| PineScript Generator | (future) | IBKRClient, GDriveCache, indicators, pinescript |
| Automated Scanner Bot | (future) | IBKRClient, SQLiteStore, analytics |

## Changes consumers should know about

### 2.1.0 — brackets, and three stricter refusals

**New public API.** A bracket — a parent order plus its held children — is one POST of a
ticket array, and it has its own entry point rather than a branch of the single-order path:

| Name | What it is |
|---|---|
| `IBKRClient.place_bracket_and_confirm(account_id, parent, children)` | Touch-ID gated. **One** Gate 1 bound to the whole array, **one** Gate 2 showing every leg, then every ticket's reply chain resolved |
| `IBKRClient.get_bracket_preview(account_id, parent, children)` | Whatif for both legs. Read-only, ungated, like `get_order_preview` |
| `pair_bracket_response(tickets, entries)` → `BracketPairing` | Which returned entry is which leg. A **module-level function**, not a method on `IBKRClient` — `from ibkr_core_mcp import pair_bracket_response` |

**IBKR's bracket response is not index-aligned with the submission.** Two separate live
sends returned `[child, parent]` for a `[parent, child]` array, so pairing `entries[i]` with
`tickets[i]` reads the parent's status off the child. Use `pair_bracket_response`; it matches
by identifier. It is public for exactly this reason — the rule is IBKR protocol knowledge and
belongs in one repository, not copied into each consumer.

`BracketPairing`'s fields are typed `Mapping[str, Any]`, **not** `dict`. Raw wire dicts
satisfy that unchanged; a consumer annotating `dict[str, Any]` will go red under mypy, which
is why the type is declared this way in the release that first publishes it rather than
widened later.

**Three things that used to be accepted are now refused.** None is reachable from a correct
bracket, and all were unreachable from claudia_ui, which does not yet use this seam:

- `_bracket_tickets` and `confirm_bracket_dialog` now refuse a child on the parent's own side
  or carrying no side, a parent carrying no `cOID` or no side, a child carrying its own
  `cOID`, and a child quantity that cannot be compared with the parent's (including `NaN`).
  The refusal happens **before Gate 1**, so no fingerprint is taken for a bracket that could
  never be placed.
- `reply_order` now returns IBKR's body wrapped in a list when it is not already one, instead
  of discarding it as `[]`. A caller reading `result[0]` on a non-empty response is unchanged;
  a caller relying on `[]` to mean "non-list body" was relying on information loss.
- Gate 2 refuses rather than approving when a bracket's quantities cannot be compared.

**Fixes a consumer may notice.** `preview_order` now reports IBKR's refusal and every
warning, and reads the margin and commission keys IBKR actually sends (four of its five
figures were `N/A` on every real call before). A futures order is recognised from IBKR's own
`secType` spelling (`"265598:FUT"`), so its notional is no longer printed as
`price × quantity`. A bare futures root resolves to a contract that is still tradeable.

### 2.0.1 — the package is on PyPI

`pip install "ibkr-core-mcp>=2.0.1,<3"` replaces the `git+https://…@vX.Y.Z` pin. claudia_ui: its
`pyproject.toml` dependency and the `core-ref.txt` checkout in its CI both move to the PyPI
specifier.

### 2026-09-17 — BREAKING: 29 `IBKRClient` methods return models, not dicts

`get_positions`, `get_all_positions`, `get_live_orders`, `get_trades`, `get_accounts`,
`get_contract_info`, `search_contract` and 22 more — `client.py`'s module docstring names
every one — return `IBKRResponse` models (audit finding API-11). A model is a **mapping over
exactly what IBKR sent**: `row["mktValue"]`, `row.get(...)`, `in`, `len`, iteration and
`dict(row)` all work unchanged, and a record that fails validation is passed through as the
dict it arrived as. It is **not a `dict`**.

What breaks, measured in ClaudIA on 2026-09-17 with rows built from the live fixture
(audit finding API-R6):

| ClaudIA parser | Guard | Raw dicts | Typed rows |
|---|---|---|---|
| `dashboard_data.parse_orders` | `isinstance(row, dict)` | 1 of 1 | **0 of 1** |
| `contract_identity.parse_contract_info` | `isinstance(info, dict)` | identity | **None** |
| `dashboard_data.parse_positions` | `isinstance(row, Mapping)` | 2 of 2 | **0 of 2** |
| `live_realised.parse_fills` | `isinstance(row, Mapping)` | 4 of 4 | **0 of 4** |

Both suites stayed green throughout, because every mock returns a dict — the blind spot this
package had already documented for its own handlers.

- **`isinstance(row, Mapping)` guards**: no change required. `IBKRResponse` derives from
  `collections.abc.Mapping[str, Any]` since the same day; it had served the protocol without
  being one, because the ABC has no structural hook.
- **Protocols and annotations written against `dict`**: a method returning `Model | dict[str,
  Any]` does not satisfy `-> dict[str, Any]`, so mypy goes red on the upgrade — ClaudIA's did,
  six errors in two files. Declare `Mapping[str, Any]`, and `Sequence[Mapping[str, Any]]` for a
  list, since `list` is invariant; a `dict` from the older core satisfies both, so the change is
  safe before and after the pin moves.
- **`isinstance(row, dict)` guards**: widen to `Mapping`. A model will never be a `dict`. In
  ClaudIA that is two lines, `parse_orders` and `parse_contract_info`.
- **`json.dumps(row)`**: pass `default=json_default` — `from ibkr_core_mcp import json_default`.
- **`row == {...}`**: compare `dict(row)`.
- **Typing**: every model is importable from the package root, e.g. `from ibkr_core_mcp import
  ContractDetails`; a method's annotation is `Model | dict[str, Any]`, the dict being the
  pass-through for a record that would not validate.

### 2026-09-17 — `anthropic` is no longer a base dependency

Moved to the `dev` extra: no module under `ibkr_core_mcp/` imports it, and the only importer
in the repository is an audit script. If your project imports `anthropic`, declare it in your
own dependencies — it was previously arriving by accident.

### 2026-09-17 — BREAKING: `Config` no longer carries an Anthropic key

`Config.anthropic_api_key` is removed and `Config.from_env()` no longer raises when
`ANTHROPIC_API_KEY` is unset. Nothing in this package ever read the field (audit finding
TOOL-07), while `mcp_server` refused to start without it.

- **`Config.from_env()` callers**: no change required.
- **Keyword `Config(...)` constructions**: delete `anthropic_api_key=`.
- **Positional `Config(...)` constructions**: the second argument is now `gdrive_folder_id`.
- **Anything reading `config.anthropic_api_key`**: read the environment, or construct the SDK
  client with no argument — `anthropic.Anthropic()` and `AsyncAnthropic()` read
  `ANTHROPIC_API_KEY` themselves. ClaudIA already does this (`claudia/agent.py`) and needs no
  change; it neither constructs `Config(...)` directly nor reads the field.
- **MCP setup**: `ANTHROPIC_API_KEY` can be dropped from the `env` block in
  `claude_desktop_config.json`. The server never used it.

The rule going forward: this package makes no model calls, so it carries **no model credentials
from any vendor**. A host app owns its model client and its own key.

### 2026-08-10 — Flex sync and coverage text

`sync_flex_trades` and `check_flex_coverage` can now emit two lines they never did before.
Host apps that render this text verbatim (ClaudIA's opening status does) will show them.

- **`⚠ Flex archive NOT updated (<kind>): <reason>`** — leads the `sync_flex_trades`
  response when the complete-capture write into the `flex_*` tables refused while the
  legacy `trades` upsert succeeded. Previously that refusal reached a log line and nothing
  else, so a sync that had silently stopped populating the Flex dataset still reported
  "Flex sync complete". The trade count still follows; the warning does not replace it.
- **`⚠ FLEX DATASET EMPTY`** — replaces the staleness note when `flex_trade` exists but
  holds no settled rows.

The staleness note also changed shape: it now reads
`⚠ DATA STALE (settled through 2026-08-05, 5d)` instead of `⚠ DATA STALE (0d old)`. The
old form mixed two tables — `stale` is derived from `flex_trade` while the day count came
from the legacy `trades` table — and could report `0d old` while warning that data was
stale. `get_trade_date_coverage` gained `settled_newest`, `days_since_settled` and
`flex_dataset_empty` alongside the existing keys; no existing key changed meaning.
