# Security Architecture

The living design document for how `ibkr_core_mcp` keeps a language model, a web page, and a
future coding agent away from a live brokerage account — and how that is *enforced* rather
than intended.

**How this differs from the other two security documents.**

| Document | Kind | Answers |
|---|---|---|
| `SECURITY.md` | Policy and control inventory (the GitHub-conventional file, public-facing) | "What controls exist, where, and how do I report a vulnerability?" |
| **`docs/security-architecture.md`** (this file) | Living design | "Where are the boundaries, what must stay true, what enforces it, why was it built this way, and how do I change it without breaking it?" |
| `docs/audits/security-architecture-audit-2026-09-13.md` and earlier audits | Point-in-time evidence, never retroactively edited | "What was found on that day, what was proven, what was done?" |

When a control changes, `SECURITY.md` and this file change together; the audit that motivated
the change stays as it was.

---

## 1. Principals and threat model

| Principal | Trusted for | Not trusted for | Where it enters |
|---|---|---|---|
| **Human operator** | Configuration, credentials, approving each order write at the keyboard | Unattended automation of order writes (by design: every write needs a fingerprint and a click) | `.env`, the CLI, the two gates |
| **The model** (Claude, through `ClaudeToolkit` or the MCP server) | Reads, analysis, strategy code, proposing orders | Executing orders, reading credentials, reaching the local network, running unconfined code | Tool `inputs` dicts, resource URIs |
| **Web content** returned by `fetch_page`, `crawl_site`, `search_site`, `firecrawl_search` | Nothing | Anything — it is the prompt-injection vector | Back into the model context |
| **IBKR gateway** (localhost) | Market and account data | Rendering: reply messages are shown on Gate 2 and are HTML-stripped first | `IBKRClient._get/_post`, `IBKRWebSocket` |
| **Flex Web Service, Firecrawl, Google** | Their own data | Redirecting us: Flex statement URLs are allowlisted by prefix | `flex_query.py`, `web_scraper.py`, `cache.py` |
| **In-process code** (the host app, a dependency) | Everything the process can do | — this package does not defend the process against itself | Direct calls |
| **A future coding agent** editing this repo | Producing lint-clean, typed, green changes | Preserving a boundary it never saw named | `git commit` |

The last row is the one the 2026-09-13 audit was about. The question it asked of every
boundary was: *could a perfectly linted, perfectly typed, fully tested change violate this
silently?* Where the answer was yes, the boundary now has a test that reads the source.

**Out of scope, on purpose.** OS-level compromise of the operator's machine; an attacker with
the operator's browser session and physical presence; in-process code that monkeypatches the
gates (documented in `human_auth.OrderWriteAuthorization`); the operator approving a bad order.

---

## 2. Privilege tiers

Every capability in the package sits in one of six tiers. The model may reach the first five
through tools; the sixth it cannot reach at all.

| Tier | Meaning | Examples |
|---|---|---|
| **READ** | Reads IBKR, Drive or SQLite; changes nothing | `get_positions`, `get_market_snapshot`, `check_cache` |
| **COMPUTE** | In-process computation on fetched data | `add_indicators`, `get_analytics`, `generate_pinescript` |
| **EXTERNAL IO** | Writes outside the process but not to the account: Drive, SQLite, a remote service, the local browser | `fetch_market_data`, `crawl_site`, `sync_flex_trades`, `firecrawl_search` |
| **LOCAL SENSITIVE IO** | Reads browser cookies, saved browser profiles, local files under an allowlisted root | `get_pnl` (cookie read for the WebSocket touch), `fetch_page` (profiles), `import_flex_file` |
| **ACCOUNT STATE** | Mutates IBKR server-side state that is *not* an order | `create_price_alert`, `delete_alert`, `activate_alert`, `modify_price_alert` |
| **ORDER EXECUTION** | Places, modifies, cancels or confirms an order | `IBKRClient.place_order` and its three siblings — **no tool** |

`SANDBOX_EXECUTION` (`run_backtest`) is EXTERNAL IO in effect — it runs model-written code in a
child process — and is treated as its own capability because its boundary is a different
mechanism (§ 6.3).

The machine form of this table is the `capabilities` frozenset on every tool definition
(`claude_tools.CAPABILITIES`; § 5, invariant 3).

---

## 3. Trust-boundary map

```
SOURCE                  VALIDATION / NORMALISATION            SERVICE                         PRIVILEGED SINK
──────                  ──────────────────────────            ───────                         ───────────────
model tool inputs ────► input allowlists (preview),           ClaudeToolkit handler ────────► IBKRClient reads          [READ]
                        identifier regexes (client.py),                                  ──► IBKRClient alert writes   [ACCOUNT STATE]
                        cache-key regexes (cache.py),                                    ──► GDriveCache / WebDocsStore [EXTERNAL IO]
                        path-under-root (import_flex_file),                              ──► SQLiteStore               [EXTERNAL IO]
                        compile_restricted + attribute        backtest.run_backtest ────────► spawn child, exec         [SANDBOX]
                          allowlist (run_backtest),
                        _validate_public_url (layer 1) ───►   local_browser.scrape/crawl ──► Chromium + route guard    [EXTERNAL IO]
                                                              search_site_detailed ────────► httpx seeder (layer 1 only)

MCP HTTP request ─────► TransportSecuritySettings ───────────► SseServerTransport ─────────► every tool above
                        (Host / Origin loopback only)

web page content ─────► assess_quality (honesty flag) ───────► back into the model context    (no sink; the model is the sink)

IBKR reply message ───► reply_message_text (HTML strip) ─────► Gate 2 dialog                  (rendered to the human)

host app (in-process) ► _validate_account_id/_order_id ──────► IBKRClient.place_order ───────► Gate 1 ─► Gate 2 ─► POST /orders  [ORDER EXECUTION]
                                                              IBKRClient.get_order_preview ──► POST /orders/whatif  [ORDER PREVIEW, ungated]

exceptions (any) ─────► _safe_error (type → sentence)  ──────► tool result
                        redact_error (detail, scrubbed) ─────► tool result / log
```

The full tool-by-tool classification (validation, service, sink, declared capabilities) is
Phase 1 of the 2026-09-13 audit; it is the reference when a tool's declaration is in doubt.

---

## 4. The privileged sinks and who may touch them

| Sink | Only through | Guarded by |
|---|---|---|
| `POST /iserver/account/{acct}/orders`, `POST …/order/{id}`, `DELETE …/order/{id}`, `POST /iserver/reply/{id}` | `place_order`, `modify_order`, `cancel_order`, `reply_order`, `_resolve_one_reply` | Gate 1 + Gate 2 inside each; AST test that no other function builds these paths |
| `POST …/orders/whatif` | `get_order_preview` | AST test that only it builds the path and it calls no gate |
| IBKR alerts / watchlists / FYI / account switch | `IBKRClient` ungated writers | Identifier regexes; capability declaration `ACCOUNT_STATE` |
| Google Drive | `GDriveCache`, `WebDocsStore` | Cache-key regexes, slugs `[a-z0-9-]`, OAuth token file 0600 |
| SQLite | `SQLiteStore`, `flex_store` | Bound parameters; allowlisted dynamic fragments; generated schema |
| Local files | `_import_flex_file`, profile dirs, token persist | `resolve()` + `is_relative_to(~/.ibkr_core)`; `_safe_domain`; 0600 |
| Browser cookie store | `BrowserCookieAuth` | Browser-name allowlist; CR/LF stripped; only ever sent to loopback |
| Chromium / httpx | `Crawl4AIScraper.scrape`, `crawl_site`, `search_site_detailed` | `_validate_public_url` before, `_reject_private_requests` per request (browser paths) |
| Subprocess | `order_confirm`, `gateway/manager`, `backtest` | AST module allowlist; no `shell=True`; constant or JSON-on-stdin arguments |
| RestrictedPython `exec` | `backtest._execute_in_subprocess` | Attribute allowlist; frozen namespace; child process; watchdog |

---

## 5. The ten invariants and their enforcement

Each row is a property that must stay true regardless of implementation. "Mechanism" is the
code that makes it true; "Enforcement" is the test that fails when it stops being true;
"To change" is the deliberate path when it genuinely must move.

| # | Invariant | Mechanism | Enforcement (`tests/security/`) | To change deliberately |
|---|---|---|---|---|
| 1 | No order reaches IBKR except through the four gated `IBKRClient` methods, and the model layer never references them | Gates at the innermost call site; `_authorize_order_write` the one minter of `OrderWriteAuthorization` | `test_order_write_boundary.py`: endpoint templates only in the gated set; gate before first network call; `claude_tools.py`/`mcp_server.py` free of order-write names, `_post`, `_session`, `OrderWriteAuthorization`; body copied before the gates | Add the new function to `GATED_OWNERS` **and** give it both gates; there is no other legitimate change |
| 2 | Preview is not execution | `get_order_preview` posts to `/orders/whatif`, calls no gate | `test_preview_is_not_execution.py`: path asserted; literal built once; `preview_order` touches only `get_order_preview` | None foreseeable |
| 3 | Every tool declares its capabilities; none declares `ORDER_EXECUTION` | `capabilities` on all 46 definitions; `tools` strips the field | `test_tool_capabilities.py`: declared, known, non-empty; `ORDER_EXECUTION` set empty; `READ_ONLY` exclusive; every sink the handler's source touches is declared | New tool: declare; new sink in an existing handler: add to the declaration **and** the mutating-tool list in the test |
| 4 | Strategy code cannot touch the filesystem, processes or network; what it can touch is frozen | Attribute allowlist for pandas/numpy; string-function name check; child process; capped error line; `build_sandbox()` | `test_sandbox_boundary.py`: canary read/write/clipboard/open/import; 7 by-name forms; named aggregation; frozen globals and namespaces | Add the name to `_PANDAS_ALLOWED_ATTRS` **and** re-check it cannot take a path, buffer or callable that escapes; update the frozen sets |
| 5 | Every externally derived URL is checked before the fetch and on every browser request | `_validate_public_url` (layer 1: scheme, host, literal parsing with `inet_aton`, DNS); `_reject_private_requests` (layer 2, Playwright route) | `test_ssrf_boundary.py`: 20-row literal table; validate-before-reach ordering in every handler; both crawler entry points install the guard | New fetch tool: call `_validate_public_url` before constructing anything; if it is not a browser, say in its docstring that it has layer 1 only |
| 6 | Error text reaching the model or a log passes one redaction function | `_safe_error` (type → sentence) for `execute()`; `redact_error` (detail, scrubbed, one line) everywhere else | `test_error_redaction.py`: secret shapes never survive; no `except … as exc` in the model layer is interpolated, `str()`'d or logged raw | Never interpolate `exc`; wrap it |
| 7 | Unit tests cannot open sockets, resolve names, or see credentials | pytest-socket from `pytest_configure`; `_no_real_io` opens a window only for `integration` and DNS-exempt tests; `_no_real_secrets` stubs `load_dotenv` and removes secret names | `test_no_live_io.py`; `test_conftest_hygiene.py` for the exemption list | A test that needs DNS goes in `_REAL_DNS_EXEMPT_TESTS` with the reason; one that needs a secret sets a fake with `monkeypatch.setenv` |
| 8 | Processes are spawned only from three named modules, never through a shell | List-form `subprocess.run`; JSON on stdin for the dialog | `test_subprocess_boundary.py`: import allowlist; no `shell=True` | Add the module to `ALLOWED_SPAWN_MODULES` with the reason, in the same commit |
| 9 | Every path-interpolated identifier passes its regex | `_ACCOUNT_ID_RE`, `_ORDER_ID_RE`, `_REPLY_ID_RE` applied in every URL-building method | Existing `test_client.py` cases; the 2026-07-11 audit's H-2 | New URL with an interpolated id: validate it in the method, whichever module builds the URL |
| 10 | The HTTP transport validates `Host` and `Origin` | `TransportSecuritySettings` in `build_sse_app` | `test_transport_security.py`: 421 / 403 / loopback passes | Adding a host means adding it to both allowlists; the test names the accepted set |

`pytest -m security` runs the whole set in about ten seconds; it is also part of every
unit run, of the pre-push hook, and of CI.

---

## 6. Subsystem designs

### 6.1 Order writes — two gates and one authorization

`place_order`, `modify_order`, `cancel_order` and `reply_order` each run **Gate 1**
(`human_auth.require_touch_id`, `LAPolicyDeviceOwnerAuthentication`, 60 s) and then **Gate 2**
(`order_confirm.*`, a modal with the full order and an explicit button; Enter does not
confirm; 60 s auto-cancel) *before* the first network call. The gates are inside the client
methods, not in a wrapper, so there is no way to call the method and skip them.

The chained variants `place_order_and_confirm` / `modify_order_and_confirm` take **one**
fingerprint per write and pass an `OrderWriteAuthorization` down the call chain: bound to the
SHA-256 of the canonical body (`_order_write_scope`), 300 s, frame-local, checked identically
at the write and at every IBKR precaution reply, expiring closed. Every reply still gets its
dialog. The value is minted only by `_authorize_order_write`, right after Touch ID succeeds;
the AST test holds that to one function. The body the dialog shows is a private copy taken at
method entry, so the caller's dict cannot change what is sent.

What this does not defend against: in-process code constructing an authorization by hand, or
monkeypatching `require_touch_id`. That code already has `_post`. The gates defend against the
model and against unattended automation, not against the process.

### 6.2 Preview

`get_order_preview` builds the same body shape and posts to `/orders/whatif`. It is ungated
because the endpoint simulates. The structural risk is that the two paths are one literal
apart, which is why the literal, its owner, and the handler's reach are all pinned by tests.

### 6.3 The backtest sandbox

Strategy code is model-written, so it is treated as hostile. Four layers:

1. **`compile_restricted`** (RestrictedPython): no `import`, no `_`-prefixed names, no
   `open`/`eval`/`exec` builtins, guarded attribute access.
2. **Attribute allowlist** (`backtest._sandboxed_getattr`): on any pandas or numpy object or
   class, only the names in `_PANDAS_ALLOWED_ATTRS` / `_NUMPY_ALLOWED_ATTRS` resolve. The
   string-function argument of `apply`/`agg`/`aggregate`/`transform` — and every keyword of
   named aggregation — faces the same list, because pandas resolves those names with its own
   `getattr`. This replaced a two-name denylist after the 2026-09-13 audit showed
   `df.style.from_custom_template` reading any file and `df.to_csv` writing any path.
3. **Process isolation**: `multiprocessing` spawn child, `Pipe` result, daemon watchdog that
   `SIGTERM`s then `SIGKILL`s at 10 s, 4,096-char code limit.
4. **A bounded error channel**: the child sends one line, capped at 300 chars — enough for the
   model to fix its own code, not enough to be a transfer.

The namespace is a value (`build_sandbox()`), so the test suite pins its key set and the two
safe namespaces. The child still runs with the operator's uid; an OS-level sandbox
(`sandbox-exec`) is the next layer if the allowlist ever proves insufficient (§ 9).

### 6.4 SSRF — two layers, and one path with only one

**Layer 1**, `ClaudeToolkit._validate_public_url` → `local_browser.is_private_host`: scheme must
be http/https; hostname required; `localhost`/`0.0.0.0`/`127.*`/`169.254.*` short-circuit;
canonical literals classified; every other literal parsed with `socket.inet_aton` (decimal,
hex, octal, short forms — the C library's rules, which are Chromium's) before DNS; resolved
addresses checked for private, loopback, link-local, reserved, unspecified, `100.64.0.0/10`
and the IPv4 inside an IPv4-mapped IPv6 address.

**Layer 2**, `_reject_private_requests`, a Playwright route handler installed on every browser
`scrape` and `crawl_site` open: re-checks every request Chromium makes — navigation, each
redirect, each subresource — at the moment it is sent. This is what closes DNS rebinding and
redirect-to-private.

**`search_site` has layer 1 only.** It drives crawl4ai's httpx sitemap seeder, not a browser.
Exposure is limited to what a sitemap/robots/`<head>` parse can return; the docstring says so.

### 6.5 Error text — two functions, one rule

`_safe_error` maps an exception *type* to a fixed sentence and is what `execute()` returns for
anything a handler did not catch. `redact_error` is for the places that need detail: type name
plus the first line of the message, secret-shaped material scrubbed, one line, 300 chars. The
rule enforced by test: a name bound by `except … as` is never interpolated, `str()`'d or logged
in `claude_tools.py` or `mcp_server.py` except through `redact_error`. The reason is concrete —
a `requests` exception carries the full request URL, and the Flex token travels in `?t=…`.

### 6.6 Transport

stdio is the default and has no HTTP surface. `--transport sse` binds `127.0.0.1` and passes
`TransportSecuritySettings` so only loopback `Host` and `Origin` values are accepted (any
port). Without those settings the MCP SDK disables its DNS-rebinding protection, which is how
it ran until 2026-09-13.

### 6.7 Test isolation

Sockets are blocked from `pytest_configure` onward; `_no_real_io` opens a window only for
`integration`-marked tests and the curated DNS-exempt list (guarded by
`test_conftest_hygiene.py`). `_no_real_secrets` makes `config.load_dotenv` a no-op and removes
every secret-named variable, so `Config()` in a test cannot pull the repository's `.env` into
the process.

### 6.8 The capability registry

Every entry of `TOOL_DEFINITIONS` and both server-local definitions carry `capabilities`. The
vocabulary is `claude_tools.CAPABILITIES`; the semantics are in its docstring. The honesty
test derives, from the handler's own source, which sinks it touches (client writes, store
writes, cache writes, the sandbox, the browser, the seeder, Firecrawl, Flex) and requires each
to be declared. `ClaudeToolkit.tools` strips the field, because the Anthropic tool schema
rejects unknown keys.

---

## 7. CI as a security instrument

| Gate | Detects | Blind to | Blocking |
|---|---|---|---|
| ruff check (incl. `S`) | Known-bad calls: `shell=True`, `verify=False` without a reason, `assert`, weak hashes | Architecture; anything list-form | yes |
| ruff format | — | — | yes |
| mypy strict | Type errors, unstubbed dependencies | Everything typed correctly and wrong | yes |
| pytest unit, including `tests/security/` | Behaviour, and the ten invariants above (structural and canary) | Anything without a test | yes |
| **pip-audit** (`dependency-audit` job) | A known-vulnerable version in the **resolved** tree, `[dev,server,scraper]`, fresh resolution, per push and weekly | Unknown vulnerabilities | yes for fixable; no-fix findings go in `security/pip-audit-ignores.txt` with a reason and a re-check date |
| **gitleaks** (`secret-scan` job) | A committed secret in the pushed range | History before the scan started (run `gitleaks git --redact` locally) | yes |
| **CodeQL default setup** (GitHub, outside `ci.yml`) | Actions-workflow injection and permissions; a fixed set of Python patterns (URL-substring checks, weak hashing, insecure protocols, …) | **Taint from this codebase's untrusted source** — tool `inputs` dicts are not "remote flow sources" under the `remote` threat model, so its injection queries cannot fire here; not a merge gate | no |
| **Dependabot alerts** (GitHub) | Advisories against the *manifest's* direct dependencies | Transitive dependencies (the nltk advisory was seen by pip-audit only) | no |

Two facts to keep straight when reading results: CodeQL's zero open alerts is partly blindness,
not cleanliness — the `tests/security/` suite is the coverage for the model-input boundary; and
a `gh run watch … | tail` reports `tail`'s exit status, so read `gh run view --json conclusion`
or `--exit-status` without a pipe.

---

## 8. Decision log

Dated, so a future reader can tell a decision from a default.

| Date | Decision | Why | Revisit if |
|---|---|---|---|
| 2026-05 | Gates live inside `IBKRClient`, at the innermost call site | A wrapper can be bypassed by calling what it wraps | Never; make it observable instead (done 2026-09-13) |
| 2026-07-11 | `eval`/`query` denied by name in the sandbox | Pandas' expression engine escapes RestrictedPython | Superseded by the allowlist |
| 2026-09-11 | One Touch ID per order write, authorization frame-local and body-bound | Matches IBKR Mobile/TWS; OWASP/NIST "authentication fatigue"; every reply still gets a dialog | Never cache, never make global |
| 2026-09-13 | **Allowlist, not denylist**, for sandbox attribute access | Two demonstrated escapes through ordinary public method names; a denylist is the eval/query fix forever | A strategy genuinely needs a name: add it with a check that it takes no path, buffer or callable |
| 2026-09-13 | No OS-level sandbox yet | The allowlist held against 22 probed forms; `sandbox-exec` would replace the spawn child with a platform-specific subprocess | The allowlist is found insufficient, or strategies must run untrusted third-party code |
| 2026-09-13 | Capabilities as a frozenset on each tool definition, not a class hierarchy | Fits the existing dict registry; one filter strips it; three tests hold it | The registry itself is rewritten |
| 2026-09-13 | Detail via `redact_error`, not blanket `_safe_error` | The model must see enough of a sandbox or browser failure to act; the danger is secrets, not detail | — |
| 2026-09-13 | pip-audit over the full tree with a reasoned ignore file; **no dependency ceilings** | Ceilings for security are churn; floors bump when a fix ships; no-fix findings are the only ignores | — |
| 2026-09-13 | CodeQL default setup **kept, not extended, not made a gate** | Free on a public repo; one real catch (workflow permissions) and one false positive in three months; structurally blind to tool inputs; `security-extended` would add low-precision noise (`verify=False`, `assert`) already reasoned at the site | Alerts start recurring on the same dismissed pattern, or the repo gains web request handlers CodeQL can model |
| 2026-09-13 | Semgrep not added | Every uncovered class is a 30-line `ast` test with zero noise and no new tool | External contributors, or a second HTTP client |
| 2026-09-13 | Dependabot alerts kept; no `dependabot.yml` version-update PRs | Floors are unpinned, so update PRs would be churn; alerts cost nothing | — |

---

## 9. Known limits and open items

- **The sandbox child runs as the operator.** The allowlist is the boundary; there is no
  OS-level confinement. (§ 6.3)
- **`search_site` has one SSRF layer.** Documented; the seeder is not a browser. (§ 6.4)
- **In-process bypass of Gate 1 by design.** `place_order(authorization=…)` trusts a value
  only `_authorize_order_write` should mint; the AST test holds the minting site, not the
  caller. (§ 6.1)
- **Docker bridge siblings** can reach the gateway container (SECURITY.md § Residual risk);
  accepted while no other container shares the host.
- **In-memory secrets** (session cookie, keys) are plain Python strings.
- **Coverage as a security instrument** — a named-module branch-coverage report — is
  proposed in the audit and not started.
- **CodeQL cannot see tool inputs.** Do not read its zero as coverage of the model boundary.

---

## 10. Change recipes

**Add a tool.** Add the definition with a `capabilities` set (never `ORDER_EXECUTION`); add the
handler to `execute()`'s dict; if it writes anywhere, add it to the mutating-tool list in
`test_tool_capabilities.py` and to SECURITY.md's capability table; if it fetches a URL, call
`_validate_public_url` first and, if it opens a browser, install the route guard; if it shows
an exception, wrap it in `redact_error`. Run `pytest -m security`; every one of those is a
failing test if forgotten.

**Add an IBKR endpoint.** Validate every path-interpolated identifier with the regex helpers
in `client.py`. If it writes an order, it is one of the four gated methods or it does not
exist. If it mutates anything else, the tool that exposes it declares `ACCOUNT_STATE`.

**Add a subprocess.** Add the module to `ALLOWED_SPAWN_MODULES` with a one-line reason; list
form; constants or stdin, never a model-derived argument; never `shell=True`.

**Expose something new to strategy code.** Add it to `build_sandbox()`, to the frozen set in
`test_sandbox_boundary.py`, and — if it is a pandas/numpy name — to the allowlist after
checking it accepts no path, buffer, callable or string that is resolved as a name.

**Change a gate.** Read CLAUDE.md § Security and SECURITY.md § Two-Gate System first; the
policy (`LAPolicyDeviceOwnerAuthentication`, once per write, dialog per reply) is deliberate.
Then run `test_order_write_boundary.py` and update the same three documents in one commit.

**Accept a pip-audit finding.** Only if there is no fixed release. One line in
`security/pip-audit-ignores.txt`: ID, why the code path is unreachable or the risk accepted,
date added, re-check date.

---

## 11. Cross-references

- Controls and disclosure: `SECURITY.md`
- Contributor rules: `CLAUDE.md` § Security & Fingerprint Authentication
- The audit that produced this document, with probe evidence: `docs/audits/security-architecture-audit-2026-09-13.md`
- Earlier security audits: `docs/audits/security-audit-2026-07-11.md` and predecessors
- Order flow examples: `docs/order-management-examples.md`
- Web scraper boundaries: `docs/web-scraper-reference.md`, `docs/web-scraping-methodology.md`
