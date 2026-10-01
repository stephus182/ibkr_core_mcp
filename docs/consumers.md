# Consuming Projects

| Project | Repo | Uses |
|---|---|---|
| ClaudIA Trading Assistant | `github.com/stephus182/claudia_ui` | IBKRClient, GDriveCache, SQLiteStore, ClaudeToolkit, GatewayManager |
| Order Management UI | (future) | IBKRClient (order endpoints), SQLiteStore, ClaudeToolkit |
| ML Feature Pipeline | (future) | IBKRClient, GDriveCache, SQLiteStore, indicators |
| PineScript Generator | (future) | IBKRClient, GDriveCache, indicators, pinescript |
| Automated Scanner Bot | (future) | IBKRClient, SQLiteStore, analytics |

## Changes consumers should know about

### Unreleased — `IBKRWebSocket.connect()` completes IBKR's handshake

`connect()` used to return the moment the socket opened. IBKR drops any topic sent before its
`sts` frame ("Authentication Status", sent on every new connection) and says nothing, so a
consumer that subscribed straight after `connect()` — every consumer did — could hold a socket
that stayed open, heartbeated, and never delivered (claudia_ui gap #68: its automatic fill
report had never fired in production). `connect()` now returns once `sts` has reported
`authenticated: true`; frames read on the way reach `listen()` first, in order.

What changes for a caller:

- `await ws.connect()` can now take a moment (IBKR's own example waits three seconds before
  its first topic) and raises `StreamingError` after `auth_timeout` seconds without an `sts`
  (default 10), or when `sts` reports the brokerage session as not authenticated. The socket is
  closed before the error is raised. A retry loop that already catches exceptions from
  `connect()` needs nothing new; one that treated `connect()` as infallible now has an error to
  handle — the error is the truth it was missing.
- Subscribing right after `connect()` is now correct. Remove any sleep added to work around
  the drop.
- `listen()` still yields `LiveQuote | TradeExecution | PnLUpdate` only. `sts` and the other
  unsolicited topics are logged (DEBUG, by topic; WARNING for an `sts` reporting the session
  unauthenticated mid-stream), never yielded.
- The constructor's `session_cookie` is unchanged. Its docstring now names IBKR's documented
  form, `api=<session>` from `POST /tickle`; measured 2026-09-24, the gateway authenticated
  the socket with and without it, so this is documentation, not a behaviour change.

### Unreleased — `get_trade_date_coverage`: the `stale` flag follows the statement rule

The flag used to compare the newest settled **trade** date with the NYSE session before the
last one, so on day D a store through D-2 read `stale: False` all day (claudia_ui gap #72,
measured 2026-09-24), and a weekday with no fills read as behind although its statement was
held. It now applies one sentence: **the store is current when it holds the statement for the
weekday before today (ET)** — "holds" read from IBKR's own `toDate` in the Flex archive, "the
weekday before today" from `ibkr_core_mcp.store.newest_statement_day(now)`, which is public
so a consumer can stop carrying its own copy (claudia_ui's `flex_sync.newest_statement_day`
is that function).

What changes for a caller:

- Two keys added: `statement_through` (IBKR's `toDate` of the newest statement held, ISO or
  None) and `newest_statement_day` (ISO). One removed: `last_trading_day` — the NYSE date the
  old rule needed. The market calendar's own `last_trading_day`, in
  `get_market_calendar_context`, is unchanged.
- `stale` is `statement_through is None or statement_through < newest_statement_day`. A store
  with no Flex archive at all is stale; so is one whose archive holds no statement.
- The empty store returns **every** key (register F1) — `stale: True`, `oldest`, `newest` and
  `days_since_newest` None, `total_trades` 0 — where it used to return four. A consumer that
  read a missing `stale` as "current" was wrong before and gets the right answer now.
- `days_since_newest` and `days_since_settled` count to the ET date of `now`; the latter is
  None when no settled trade exists (it used to borrow the legacy table's date).
- `get_trade_date_coverage(now=<aware datetime>)` is new and optional: the verdict is for that
  instant, the current time by default.
- `check_flex_coverage`'s stale note carries the verdict's evidence:
  `⚠ DATA STALE (statement through 2026-09-22; the newest that can exist is through 2026-09-23)`.

### Unreleased — a Gate 2 timeout is its own outcome

The dialog's auto-dismiss used to raise the abandon button's `HumanAuthError("Order cancelled by
user")`, so a consumer could not tell a declined dialog from one nobody answered — and told its
user an order was cancelled when the timeout had kept it (claudia_ui gap #67, register F21, seen
live 2026-09-25). Now:

- `ConfirmationTimeoutError`, a subclass of `HumanAuthError` exported from `ibkr_core_mcp`, is
  raised when the dialog dismisses itself with no decision, on all three renderers (the AppKit
  subprocess, the osascript fallback, tkinter). Its message names what the timeout leaves:
  "Confirmation dialog timed out after 60 s with no decision — nothing was sent to IBKR; the
  order is as it was". Catch it before `HumanAuthError` to record a timeout as a timeout; a bare
  `except HumanAuthError` keeps working.
- The dialog script prints `TIMED_OUT` beside `CONFIRMED` and `CANCELLED`; `order_confirm`
  imports the three tokens from `_order_dialog`, so the reader cannot drift from the writer.
- A consumer that classified the abandon message by its text ("cancelled by user") no longer
  sees a timeout under it; one that already matched "timed out" gets the right stage for free.
- The abandon button's own message is unchanged ("Order cancelled by user"). Its rewording per
  dialog (not sent / kept / left unchanged) and the button colours are register F6, to be
  decided with the operator.

### Unreleased — `get_market_calendar_context` says who holds a session today, per exchange

`is_trading_day` was, and is, the **primary** exchange's flag (NYSE by default), and
`holidays_by_exchange` is built from weekdays, so a consumer asking "who is open today?" on a
Saturday found nobody in any holiday list and read every exchange as open — claudia_ui's
startup briefing printed "All tracked exchanges open today" on Saturday 2026-09-26 (gap #78,
register F24). The calendars were loaded; the answer was not in the dict.

- New key `sessions_today: dict[str, bool]`, keyed like `holidays_by_exchange`, one verdict per
  exchange from its own calendar (`is_session(today)`): a Saturday is `False` everywhere, a
  Friday is `False` for Tadawul, a NYSE holiday says nothing about CME or London.
- On the failure marker (`{"error": ..., "is_trading_day": None}`) it is `None` — unknown, not
  an empty map that would read as "nobody open".
- New optional `today=` (a `date`): the verdicts for that day rather than the current one; the
  process cache keys on it. `last_trading_day` / `next_trading_day` are then relative to that
  day's midnight UTC.
- The weekday rule a consumer had to carry itself (claudia_ui's briefing decides a weekend
  before reading any list) can be deleted once it reads `sessions_today`.

### Unreleased — `cancel_order` can carry the CME Rule 536-B tag

IBKR documents `manualIndicator` as required on a futures or futures-option **cancel**, as it is
on a place and a modify: "Regardless of original submission, the cancellation must also include
the manualIndicator tag". `cancel_order` sent a bare `DELETE`, which IBKR accepts (seventeen futures
cancels measured, 2026-07-28 to 09-24) — accepted, not shown compliant.

- **New, keyword-only:** `cancel_order(account_id, order_id, order_details=None, *,
  manual_indicator=None)`. `True` → `?manualIndicator=true`, `False` → `?manualIndicator=false`,
  `None` → the bare `DELETE`, exactly as before. Nothing changes for a caller that passes nothing.
- **What a consumer should do:** pass `manual_indicator=True` when a person cancels a FUT or FOP
  order (`False` if your own automation does). Leave it out for other classes. The package does
  not derive it: only the caller knows the contract class and who decided.
- **Strict on purpose:** anything that is not a bool or `None` raises `OrderValidationError`
  before Touch ID — the string `"false"` is truthy and would otherwise be sent as `true`.
- **Measured 2026-10-01:** a tagged cancel of a resting ES limit order was accepted and read back
  `Cancelled`; the gateway's request log shows the query string. IBKR answers a tagged and a bare
  cancel with the same body, so check the log line `cancel:<id> manualIndicator=…`, not the
  response, to know which was sent. `extOperator` is not sent (rejected on a place as field 8089).
- claudia_ui passes it for futures cancels once its pin moves to this release (its gap #7).

### Unreleased — the Flex dataset has a typed read API, and every reader in this package uses it

The package owns the Flex dataset and what it means (claudia_ui's Flex boundary, decided
2026-09-29). Until now a consumer that wanted realised P&L by window, closed-lot statistics or
"is this fill on a statement yet" wrote SQL against `flex_trade` and `flex_lot` — claudia_ui
held twenty-two such statements — while this package's own `get_trades(source='store')` summed
a different table and reported a different lifetime figure (register F20).

What changes for a caller:

- **Ask `ibkr_core_mcp.flex_dataset.FlexDataset`, not the tables.** Open, ask, close, on one
  thread:

  ```python
  from ibkr_core_mcp.flex_dataset import FlexDataset

  with FlexDataset.open(config.sqlite_path) as flex:
      week = flex.realised_window(monday, today)   # RealisedWindow: total, by_asset, currencies
      settled = flex.settled_execution_ids(ids)    # frozenset of the ids a statement holds
  ```

  Every method raises `StoreError` when the dataset cannot be read — a missing file, table or
  column, a damaged database, an unparseable stored date — so an unreadable store is never
  shown as zero. The connection is `mode=ro`; nothing the reader does can write. The path is
  opened as `SQLiteStore` opens it — no `~` expansion, a relative path against the working
  directory — and a path holding a NUL is refused rather than cut at it.
- **The dataset's state is `ibkr_core_mcp.flex_sync`:** `validate_dataset`,
  `validate_dataset_daily`, `dataset_fingerprint`, `last_import`, `statement_through`,
  `pull_due`. These never raise. claudia_ui carried them as `claudia/flex_sync.py`; same names,
  same signatures, same answers.
- **A pull backs the store up to Drive by itself.** `FlexQueryClient.fetch_trades` uploads
  `store.db` to `account_data/` when the pull changed the dataset and records the outcome in
  `last_backup_result`. A consumer that made this backup after its own pull should stop: a
  second upload re-sends the file the pull has just sent.
- **`get_trades(source='store')`, `verify_flex_import`, `ibkr://trades/recent` and
  `get_trade_date_coverage` read the Flex dataset.** Their totals and counts change where the
  legacy table was wrong: each execution appears once, `total_trades` counts executions, the
  realised total matches `realised_window`. The resource keeps its keys. The tools' text
  changes as the CHANGELOG lists; a host that renders it verbatim (claudia_ui's System log
  does) shows the new backup and validation lines of `sync_flex_trades`.
- **`SQLiteStore.get_trades` and `get_all_execution_ids` are deprecated** (legacy table; removed
  in 3.0). Their replacements are `FlexDataset.executions` and `FlexDataset.trade_ids`.

### 2.1.0 — brackets, and three stricter refusals

**New public API.** A bracket — a parent order plus its held children — is one POST of a
ticket array, and it has its own entry point rather than a branch of the single-order path:

| Name | What it is |
|---|---|
| `IBKRClient.place_bracket_and_confirm(account_id, parent, children)` | Touch-ID gated. **One** Gate 1 bound to the whole array, **one** Gate 2 showing every leg, then every ticket's reply chain resolved |
| `IBKRClient.get_bracket_preview(account_id, parent, children)` | Whatif for a parent plus its children. Read-only, ungated, like `get_order_preview`. Both legs are sent so the array is validated as one unit, but IBKR prices the **first ticket only** — a mismatched bracket previews clean (measured live 2026-09-20, re-confirmed 2026-09-22), so a clean preview is never evidence about the child |
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

**Gate 2 shows more rows than it did in 2.0.1, because it now shows every execution-affecting
body key.** Until 2026-09-22 a non-`_` key the dialog had no typed row for was sent to IBKR
verbatim and appeared on no row — measured that day, a body carrying `allOrNone`,
`trailingAmt` and `trailingType` rendered a row set byte-identical to a body carrying none of
them, so the human authorised an order whose execution differed from the one on screen, while
Gate 1's scope hash had been binding those values all along. Unknown now fails **toward** the
screen: a key this package has never heard of is rendered under its own name rather than
hidden, with a short suppression list for identity, routing and compliance keys (`conid`,
`acctId`, `cOID`/`parentId`, `secType`, `manualIndicator`) and a present `None` skipped. Three
smaller changes to the same screen: a body carrying `ticker: None` no longer renders
`Symbol: None`, an unnamed contract prints its conid instead of a bare `UNKNOWN`, and a
bracket child inherits the parent's `ticker` — this package's own documented bracket example
printed `Symbol: UNKNOWN` on both children, the two legs the human has never seen before.

**Nothing a consumer imports changed.** `order_confirm.price_text_safe` and
`order_confirm.change_value_text` — the two symbols claudia_ui imports and pins in its
`tests/security/test_cross_repo_contract.py` — are untouched by that commit, and no consumer
imports `_order_rows` or asserts on the dialog's row set (grepped across claudia_ui on
2026-09-22: one comment names `_order_rows`, with no import and no assertion behind it). A
consumer rendering its own proposal card from the same body is unaffected. A golden-text test
over the *dialog* would need updating, and none exists today.

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
