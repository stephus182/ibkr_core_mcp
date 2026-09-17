# Consuming Projects

| Project | Repo | Uses |
|---|---|---|
| ClaudIA Trading Assistant | `github.com/stephus182/claudia_ui` | IBKRClient, GDriveCache, SQLiteStore, ClaudeToolkit, GatewayManager |
| Order Management UI | (future) | IBKRClient (order endpoints), SQLiteStore, ClaudeToolkit |
| ML Feature Pipeline | (future) | IBKRClient, GDriveCache, SQLiteStore, indicators |
| PineScript Generator | (future) | IBKRClient, GDriveCache, indicators, pinescript |
| Automated Scanner Bot | (future) | IBKRClient, SQLiteStore, analytics |

## Changes consumers should know about

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
