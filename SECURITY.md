# Security Policy — ibkr_core_mcp

This document describes the security model, threat mitigations, and responsible disclosure process for `ibkr_core_mcp`. It is the **control inventory**; the design behind it — principals, privilege tiers, the trust-boundary map, the invariants and the tests that enforce them, the decision log — is `docs/security-architecture.md`, and the dated evidence is in `docs/audits/`. The external baseline it is measured against is the OWASP GenAI Security Project's *A Practical Guide for Secure MCP Server Development* (v1.0, February 2026); the section-by-section applicability decision is `docs/audits/owasp-mcp-guide-applicability-2026-09-14.md`. The package connects a Claude AI agent to live brokerage infrastructure; security is treated as a first-class architectural concern throughout, not an afterthought.

---

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Email: **stephane.menard@gmail.com**

Include:
- A description of the vulnerability and its potential impact
- Steps to reproduce or a proof-of-concept
- The affected version(s) and component(s)

You will receive an acknowledgement within 48 hours. Critical findings will be patched on a priority basis.

---

## Security Scope and Deployment Model

`ibkr_core_mcp` is built for **one operator on one personal workstation**. Everything it
protects sits on that machine:

- **Local processes only.** The MCP server, the Claude client (Claude Desktop, Claude Code, or
  a host app such as `claudia_ui`) and the IBKR Client Portal Gateway (Docker, published on
  loopback) all run on the operator's machine. The server runs as the operator's own user
  because its two strongest controls cannot run anywhere else: Gate 1 is Touch ID on that
  machine, Gate 2 is a dialog on that screen, and the IBKR session is read from that user's
  browser cookie store.
- **stdio is the trust path.** The default transport hands the server its pipes from the
  process that spawned it; there is no network surface and no third party to authenticate.
- **SSE is optional and lower-trust.** `--transport sse` binds `127.0.0.1`, validates `Host`
  and `Origin`, and requires this launch's bearer token — the browser, the LAN and any other
  local process each have to get past one of those (§ MCP Transports). Prefer stdio; start SSE
  only for a local consumer that needs it.
- **Not this deployment:** a public or remote MCP endpoint; more than one tenant or user;
  delegated or enterprise identities; a shared service account; Kubernetes or a service
  mesh; a marketplace of third-party tools loaded at runtime. The tool set is the installed
  package version.

Read every control below, and every external baseline, through that model. OWASP
recommendations whose failure class cannot arise here — OAuth/OIDC client authentication,
tenant-scoped authorization and session isolation, token brokerage, network policy, SIEM
feeds, workload identity, signed tool manifests and registries, AIBOM, policy engines — are
classified **not applicable** in `docs/audits/owasp-mcp-guide-applicability-2026-09-14.md`,
and that is a security conclusion, not a backlog.

---

## Threat Model

`ibkr_core_mcp` sits at the boundary between an LLM agent (Claude) and a live IBKR brokerage account. The principals, and what each is trusted for:

| Principal | Trusted for | Explicitly not trusted for |
|---|---|---|
| **Human operator** | Configuration, credential management, approving each order write at the keyboard | Unattended automation of order writes |
| **LLM / Claude agent** | Read operations, analysis, strategy generation, proposing orders | Order execution, credential access, unconfined code execution, reaching the local network |
| **Web content** returned by the four web tools | Nothing — it is the prompt-injection vector | Anything |
| **A future coding agent** editing this repository | Producing lint-clean, typed, green changes | Preserving a boundary it never saw named — which is why each boundary has a test that reads the source (§ Security Regression Suite) |

This separation is enforced **architecturally**, not by policy, and since 2026-09-13 it is also **machine-checked**: no combination of prompt, tool call, or LLM-generated input can bypass the human-in-the-loop controls — they require physical presence at the machine — and a change that would open such a path fails `pytest -m security`. In-process code (the host application, a dependency) is not a principal this package defends against; it already has everything the process has.

The secondary threat surface is the LLM tool boundary. External content is treated as untrusted: controls bound the privileged effects it can reach — no credential, no order write, no unconfined execution — while prompt-injection-driven composition remains a documented residual risk (§ Tool composition under prompt injection; `docs/audits/owasp-mcp-guide-applicability-2026-09-14.md` § Phase 3 E; `docs/security-architecture.md` § 9). Syntactic injection into a URL or a SQL statement is a separate, closable problem and is closed by validation at each sink; semantic prompt injection is not, and no sanitiser here claims to neutralise it. Error text must never carry a secret. The full model, with privilege tiers and the trust-boundary map, is `docs/security-architecture.md` §§ 1–3.

---

## External Baselines — OWASP (Principal), MCP (Supporting)

The principal external baseline is the OWASP GenAI Security Project's
[*A Practical Guide for Secure MCP Server Development*, v1.0, February 2026](https://genai.owasp.org/resource/a-practical-guide-for-secure-mcp-server-development/)
— the PDF behind that page's *Download* link, cited by section below. It was retrieved in
full on 2026-09-14 and mapped item by item in
`docs/audits/owasp-mcp-guide-applicability-2026-09-14.md`. The summary:

| OWASP domain | Standing here | Where in this document |
|---|---|---|
| Landscape — tool poisoning, code injection, credential leakage, excessive permissions | Covered; code execution and permissions are *stronger* than the guide asks (an attribute allowlist in a child process; a mechanical honesty test instead of manual review) | § LLM / AI Boundary Controls, § Backtest Sandbox |
| Landscape — rug pulls; §2 signed manifests; §7 signing | Not applicable — architecture: no tool is loaded at runtime; integrity is the pinned git tag | — |
| Landscape / §1 — session, identity and tenant isolation; lifecycle; per-session quotas | Not applicable — deployment model: one principal. Compute isolation applies and holds | § Backtest Sandbox |
| §1 — local transport: prefer stdio; bind loopback; validate Origin; authenticate clients | All four: stdio is the default and preferred; SSE binds loopback, validates `Host`/`Origin`, and requires this launch's bearer token | § MCP Transports |
| §2 — descriptions match behaviour; minimal fields to the model | Held by test, from source, on every run | § Capability declarations |
| §3 — input schemas; output schemas; sanitization; size limits | Inputs validated against `inputSchema` on the MCP transport (invariant 11, tested since 2026-09-14); outputs are text, with a rule for future structured tools; sanitization covered; sizes measured, no page cap by decision | § Tool inputs and outputs |
| §4 — structured invocation; human-in-the-loop for high-risk actions | Covered; the order-write checkpoint is *stronger* than an MCP elicitation (out-of-band, server-side, cannot be answered by a client) | § Two-Gate System |
| §5 — OAuth 2.1/OIDC, delegation, token lifetimes | Not applicable — no remote server, no client token. "Sessions are state, not identity" and "centralize enforcement" hold | § Session Security |
| §6 — secrets, containers, segmentation, supply chain, CI gates, error handling | CI gates, `pip-audit`, `gitleaks` and error redaction covered — including the filesystem paths on OWASP's list, collapsed to `~` since 2026-09-14; vault, container and segmentation not applicable (loopback binds; a server that must run as the operator; `.env` read once and never logged, though its 0600 mode is the operator's doing, not something this package sets); Actions SHA-pinning declined while CI holds no secret | § Secrets Management, § Security Regression Suite |
| §7 — governance: review, audit logs, non-human identities | Review is a standing practice for one maintainer; the client transcript is the audit trail; NHI not applicable | — |
| §8 — SAST/SCA, runtime protection, SIEM, Scorecard | ruff `S`, CodeQL, `ast` tests, `pip-audit`; OS-level confinement is the documented next layer for the sandbox; SIEM and Scorecard not applicable | § Security Regression Suite |

The official [MCP security best practices](https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices)
page is a **supporting, protocol-specific reference**, not a second framework. It is written
as a companion to the MCP Authorization specification, and most of its sections
(confused-deputy OAuth proxies, token passthrough, state-handle hijacking, scope minimization
of OAuth tokens) describe conditions this deployment does not have. Two of its sections are
more specific than the OWASP guide and are cited where they apply: SSRF (redirect targets,
encoding tricks, DNS time-of-check/time-of-use — § Network Security) and local server
hardening (stdio, or a token / IPC for HTTP — § MCP Transports), together with the
[transports specification's security warning](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports#security-warning)
(Origin validation MUST; loopback bind and authentication SHOULD). Until 2026-09-14 this
document carried a six-row mapping onto that page; it is retired because the OWASP guide
covers the same ground more broadly, and two of the rows had come to cite sections that now
mean something else.

---

## Order Execution Security — Two-Gate System

**All order write operations require two sequential human-in-the-loop validations: one biometric per order write, and a dialog with an explicit button for every message. There is no bypass and no session cache; the biometric's own OS recovery path (the device password after a failed scan) is the one fallback, by design.**

### Gate 1 — Biometric Authentication (Touch ID)

| Property | Value |
|---|---|
| Mechanism | Apple `LocalAuthentication` — `LAPolicyDeviceOwnerAuthentication` (biometrics first, device password on a failed scan) |
| Frequency | **Once per order write.** Place, modify and cancel each take one Touch ID — as IBKR Mobile and TWS ask once per placement, modification or cancellation — and the precaution replies IBKR sends for that write validate through their own dialogs (explicit button, order named in the title) without a second fingerprint. `client._authorize_order_write` → `human_auth.OrderWriteAuthorization`: bound to the write's own account id and body (hashed; the account joined the scope 2026-09-17, SEC-07), 300 s, checked identically at the write and at every reply, fails closed, never persisted, never global. User rule 2026-09-11; sources (OWASP, NIST SP 800-63B-4, CISA, EU RTS 2018/389, Apple) in claudia_ui `docs/api-reference.md` § Order authorization. |
| Password / PIN fallback | **Device password after a failed biometric read** — Apple's own recovery path under this policy. The biometrics-only policy (`…WithBiometrics`) was evaluated and rejected: a failed scan under it leaves the user no recovery at all (`human_auth.py`). Corrected 2026-09-11: this document had claimed biometrics-only with no fallback while the code never did (claudia_ui gap #48). |
| Timeout | 60 seconds; raises `HumanAuthError` on expiry |
| On denial | `HumanAuthError` raised immediately; IBKR endpoint is never contacted |
| Location | `ibkr_core_mcp/human_auth.py` |

`LAPolicyDeviceOwnerAuthentication` is distinct from `LAPolicyDeviceOwnerAuthenticationWithBiometrics`: under the former the OS itself offers the device password after a failed biometric read. The code chose it deliberately (`human_auth.py`); until 2026-09-11 this paragraph described the latter, which was never the policy in force.

### Gate 2 — Visual Order Confirmation Dialog

| Property | Value |
|---|---|
| Mechanism | On macOS an AppKit `NSAlert` run in a subprocess (`_order_dialog.py`, banner colour-coded by side: green BUY, red SELL, dark red CANCEL, amber when the side is unknown), falling back to an `osascript` dialog if that subprocess fails; a `tkinter` modal on other platforms. All three show the typed order rows and a live-order disclaimer |
| Confirmation | Explicit mouse click on the confirm button (labelled for the action: SEND TO IBKR / MODIFY ORDER / CANCEL ORDER / CONFIRM REPLY). **Return confirms on none of the three renderers**, by three different mechanisms: AppKit clears the Return key equivalent off the confirm button and gives Escape to the abandon one, so no button is default at all; `osascript` names the abandon button `default button`; `tkinter` marks no default, and Tk's `Button` class binds `<space>` and the mouse — never `<Return>`. This row read "the default button is the abandon one" until 2026-09-17, which held for `osascript` alone (SEC-09); each mechanism now has the test that checks it |
| Button → verdict | AppKit answers `NSAlertFirstButtonReturn` (1000) for the **first button added**, and that is the only response `_order_dialog.py` turns into `CONFIRMED`. Nothing tied that position to a title, so swapping the two `addButtonWithTitle_` lines — which would make GO BACK place the order and SEND TO IBKR abandon it — passed all 1,537 unit tests when it was tried on 2026-09-17 (SEC-R4). `test_the_button_that_reports_confirmed_is_the_confirm_button` and `test_the_abandon_button_cannot_report_confirmed` now assert the binding by title, never by position |
| Auto-cancel | 60-second countdown ticker; raises `HumanAuthError` on expiry |
| Rationale for timeout | Prevents an unattended dialog on a locked screen from being confirmed by physical access |
| Location | `ibkr_core_mcp/order_confirm.py` |

### Enforcement Location

Both gates are applied at the **innermost call site** inside `IBKRClient`, not at the tool layer or any middleware. This ensures no code path can bypass them by calling the method differently.

```
place_order()   ──► require_touch_id() ──► confirm_dialog() ──► POST /iserver/account/{id}/orders
modify_order()  ──► require_touch_id() ──► modify_dialog()  ──► POST /iserver/account/{id}/order/{orderId}
cancel_order()  ──► require_touch_id() ──► cancel_dialog()  ──► DELETE /iserver/account/{id}/order/{orderId}
reply_order()   ──► require_touch_id() ──► reply_dialog()   ──► POST /iserver/reply/{replyId}
```

`place_order_and_confirm` / `modify_order_and_confirm` run the write's gates once and then, for
each precaution reply IBKR returns, the reply dialog (covered by the write's
`OrderWriteAuthorization`, so no second fingerprint). The order dict is copied at method entry,
so the body the dialog shows is the body sent. Since 2026-09-13 this whole shape is read from
the source by `tests/security/test_order_write_boundary.py`: those five functions are the only
ones that may build an order-write URL, each must call a gate before its first network call,
and `claude_tools.py` / `mcp_server.py` may not name any of them.

### Gated vs. Ungated Endpoints

**Gated (Touch ID → confirmation dialog required before any order-write request):**

| `IBKRClient` method | Dialog shown |
|---|---|
| `place_order` | Full order details + live-order disclaimer |
| `modify_order` | Change summary (old → new) |
| `cancel_order` | Cancellation confirmation |
| `reply_order` | IBKR reply confirmation |

**Explicitly ungated.** What these have in common is not that they read — it is that none of
them can place, modify, cancel or confirm an order. That is the property the gates protect, and
it is held by construction: `ORDER_EXECUTION` is not a capability any tool can declare
(§ Capability declarations). They are *not* all read-only.

*Read-only and simulation:*

| `IBKRClient` method | Reason |
|---|---|
| `get_order_preview` | IBKR `whatif` endpoint — simulates, never executes |
| `get_live_orders` / `get_order_status` / `get_orders_raw` | Read-only |

*Ungated non-order `ACCOUNT_STATE` mutations* — these do change state on IBKR's servers. They are
ungated deliberately: a price notification is not an execution path, and the two gates are
reserved for order writes.

| `IBKRClient` method | What it changes |
|---|---|
| `create_alert` | `POST` — creates a price alert (given an existing alert id, modifies it) |
| `delete_alert` | `DELETE` — removes a price alert permanently |
| `activate_alert` | `POST` — enables or disables an existing alert |

**The alerts are not the only ones.** This table listed three ungated state-changing methods
until 2026-09-17 while the client had nine (audit finding `SEC-R2`); an inventory missing an
entry reads as complete while it is not, which is `SEC-12` one level up. The rest:

| `IBKRClient` method | What it changes |
|---|---|
| `create_watchlist` | `POST` — creates a watchlist |
| `delete_watchlist` | `DELETE` — removes a watchlist permanently |
| `mark_notification_read` | `PUT` — marks one FYI notification read |
| `update_delivery_option` | `POST`/`PUT` — enables or disables a notification delivery channel |
| `switch_account` | `POST` — changes the active account (advisor / family accounts) |
| `unsubscribe_market_data` | `POST` — drops a streaming market-data subscription |
| `invalidate_positions_cache` | `POST` — force-refreshes IBKR's position cache |
| `logout` / `reauthenticate` / `tickle` | `POST` — session lifecycle |

**None of the nine is reachable from the model layer** — measured 2026-09-17 by searching
`claude_tools.py` and `mcp_server.py` for each name. The only ungated writes a tool can reach
are `run_iserver_scanner` and `get_pa_periods_raw`, and both are POST-as-query: IBKR takes a
request body for them, they change nothing. So this was a gap in the *inventory*, not in the
boundary. `tests/security/test_documented_controls.py` now fails if a write method in
`client.py` is neither gated nor named here.

Until 2026-09-14 the read-only table was headed "read-only; no execution risk" for all six methods, which
was wrong for the three alert writes. The capability registry had them right the whole time —
`create_price_alert`, `modify_price_alert`, `delete_alert`, `activate_alert` are the
`ACCOUNT_STATE` row of § Capability declarations — so this is a documentation correction only;
no classification, gate or behaviour changed.

---

## LLM / AI Boundary Controls

### No order writes in the tool surface

`ClaudeToolkit` exposes **44 tools** to the LLM (46 through the MCP server, which adds two
local price-alert tools). **None of them can place, modify, cancel or confirm an order** —
`tests/security/test_tool_capabilities.py` asserts that `ORDER_EXECUTION` is not even a legal
capability — it is absent from the vocabulary, so a definition that tries fails the
unknown-capability check by construction. They are *not* all read-only, and until 2026-09-13 this section
said "42 read-only tools" while eight of them mutated state outside the machine
(docs/audits/security-architecture-audit-2026-09-13.md, B3). The complete tool surface is:

| Category | Tools |
|---|---|
| Market data | `fetch_market_data`, `check_cache`, `list_cache`, `delete_cache`, `get_market_snapshot` |
| Contracts | `search_contract`, `get_contract_info`, `get_option_chain`, `get_futures` |
| Account | `get_account_summary`, `get_positions`, `get_ledger`, `get_allocation`, `get_pnl` |
| Trades | `get_trades`, `sync_flex_trades`, `sync_flex_archive`, `check_flex_coverage`, `import_flex_file`, `verify_flex_import` |
| Orders (read, plus the whatif preview) | `get_live_orders`, `preview_order`, `get_order_status`, `diagnose_orders` |
| Scheduling | `get_trading_schedule` |
| Watchlists | `get_watchlists` |
| Scanners | `run_scanner` |
| Notifications | `get_notifications` |
| Price alerts (IBKR server-side — `ACCOUNT_STATE`) | `create_price_alert`, `modify_price_alert`, `delete_alert`, `activate_alert`, `get_alerts` |
| Analytics & backtest | `add_indicators`, `run_backtest`, `generate_pinescript`, `get_analytics` |
| PA reporting | `get_pa_periods`, `get_pa_performance`, `get_pa_transactions` |
| Web scraping | `firecrawl_search`, `search_site`, `crawl_site`, `fetch_page` |

### Capability declarations

Every tool definition carries a `capabilities` frozenset drawn from `claude_tools.CAPABILITIES`
(`READ_ONLY`, `COMPUTE`, `NETWORK`, `WEB_FETCH`, `LOCAL_IO`, `GOOGLE_DRIVE`, `DATABASE`,
`ACCOUNT_STATE`, `ORDER_PREVIEW`, `SANDBOX_EXECUTION` — and deliberately not `ORDER_EXECUTION`);
`ClaudeToolkit.tools` strips the field before schemas reach the Anthropic API, and
`tool_capabilities()` returns the toolkit's map (the two server-local tools are declared beside
their definitions in `mcp_server.py`). The MCP server derives the protocol-native
`ToolAnnotations` (`readOnlyHint`, `destructiveHint`, `openWorldHint`) from the same set, so an
MCP client that gates its confirmation prompts on those hints sees them. The test suite checks
four things: every tool declares a non-empty known set; `ORDER_EXECUTION` has no legal spelling;
the `execute()` dispatch dict and `TOOL_DEFINITIONS` name the same tools; and every sink a
handler's own source touches (an IBKR write, a store write, a Drive write, the sandbox, the
browser, Firecrawl, Flex) is declared. The tools
that mutate state, as that test freezes them:

| Capability | Tools |
|---|---|
| `ACCOUNT_STATE` (IBKR server-side, ungated) | `create_price_alert`, `modify_price_alert`, `delete_alert`, `activate_alert` |
| `ORDER_PREVIEW` | `preview_order` |
| `GOOGLE_DRIVE` (write/delete) | `fetch_market_data`, `delete_cache`, `sync_flex_trades`, `firecrawl_search` (with `save_to_drive`), `crawl_site` |
| `DATABASE` (SQLite write) | `get_trades`, `sync_flex_trades`, `sync_flex_archive`, `import_flex_file`, `verify_flex_import`, `run_backtest`, `add_price_alert` |
| `SANDBOX_EXECUTION` | `run_backtest` |
| `WEB_FETCH` | `fetch_page`, `crawl_site`, `search_site` |
| `NETWORK` (remote service) | `sync_flex_trades`, `firecrawl_search` |

Order placement must go through `IBKRClient` directly, which enforces both gates; `tests/security/test_order_write_boundary.py` asserts that `claude_tools.py` and `mcp_server.py` never reference an order-write method, `_post`, `_session` or `OrderWriteAuthorization`.

This is OWASP's *Excessive Permissions* item and its §4 human-in-the-loop checkpoint in the strong form: the model's maximum scope is the five reachable tiers, and the order-write elevation is an out-of-band human act inside the server that no tool call — and no MCP client answering an elicitation on the user's behalf — can perform.

### The model as a confused deputy

A confused deputy is a trusted intermediary manipulated into using its privileges on an attacker's behalf; here the deputy is the model and the attacker is whatever it read. (The MCP best-practices page's section of that name is about OAuth proxy servers, a condition this deployment does not have.) In this system:

- The LLM (deputy) has no path to order execution regardless of instruction — no tool exists for it to call.
- Every value interpolated into a URL path is validated before use, preventing path-manipulation attacks:

```python
_ACCOUNT_ID_RE = re.compile(r"^[A-Z0-9]{4,12}$")
_ORDER_ID_RE = re.compile(r"^[0-9]+$")
_REPLY_ID_RE = re.compile(r"^[0-9a-fA-F-]{1,64}$")
_NUMERIC_PATH_SEGMENT_RE = re.compile(r"^[0-9]+$")
# Blocks values like "../../iserver/auth/status", "../order/987654321", etc.
```

`_NUMERIC_PATH_SEGMENT_RE` backs `_validate_conid`, `_validate_page` and
`_validate_notification_id`, added 2026-09-16. Those three values carry `int` annotations
that do not survive into the interpolation — and `/iserver/secdef/search` returns `conid`
as a **string** — so a string there is an ordinary value, not a hypothetical misuse.

`_REPLY_ID_RE` is applied in both places that build `/iserver/reply/{id}` — `reply_order`
and `_resolve_one_reply`. Only the first validated until 2026-09-16 (SEC-03).

**It is measured, not inferred.** The pattern was drawn from IBKR's single documented
example; on 2026-09-16 it was checked against **24 reply IDs IBKR actually sent**,
recovered from the persisted reply logs of real orders placed 2026-09-10/11 in the
consuming project's decision store. All 24 matched. Every one was a standard lowercase
UUID (36 characters, 8-4-4-4-12) — which the documented example is **not**: its third
group is six characters. Matching on charset rather than on UUID structure is what accepts
both, and tightening this to a UUID pattern would reject the only example IBKR publishes.
The IDs are not reproduced here: this repository is public and they are the account
holder's.

One path segment is not a regex at all: `update_delivery_option`'s `option` is checked
against `_DELIVERY_OPTIONS = frozenset({"device", "email"})`, the two channels IBKR
publishes, because no other value forms a real path.

**This bullet said "`account_id`, `order_id`/`alert_id`, and `reply_id` … are validated"
until 2026-09-16, and that was a claim about three names rather than about the property.**
An AST enumeration found 36 path interpolations and 10 with no validator for the value
being interpolated — including `get_positions`' page index, in a method that validated its
account id in the same URL. `tests/security/test_path_identifier_validation.py` now holds
the property itself: every interpolated value is passed to a validator, or listed with a
reason (audit findings SEC-03, SEC-04).

`_ORDER_ID_RE` is `[0-9]`, never `\d`. Python's `\d` matches Unicode decimal digits, and
`int()` accepts them: `\d+` admits `"١٢٣"` (Arabic-Indic), which `int()` reads as 123, and
`"1٢2"`, which it reads as **122** — a different order id than the string appears to name.
This block printed the `\d` form until 2026-09-16 while `client.py` had `[0-9]`, so the
documented mitigation was weaker than the implemented one and a reader copying it would have
reintroduced the gap; the fix itself is recorded in the audit log at the end of this file.
`tests/security/test_documented_controls.py` now fails if the two drift apart again.

  (`order_id`/`alert_id` validation was added 2026-07-11 after an audit found `delete_alert(alert_id="../order/<id>")` could collapse to `cancel_order`'s URL — see `docs/audits/security-audit-2026-07-11.md` H-2. `account_id` alone was not sufficient; every path-interpolated identifier needs the same treatment.)

### Error text and raw payloads reach the model only through redaction

OWASP §6 (*Safe Error Handling*: no stack traces, tokens, filesystem paths or tool internals in what the model or client sees) and §3 (sanitize outputs) are the baseline. Raw API responses, exception messages and external service errors are never forwarded to the model unsanitized: they may carry attacker-controlled content from an IBKR response or from strategy code, and a `requests` exception carries the full request URL. (Until 2026-09-14 this section was framed as the MCP page's *token passthrough* anti-pattern, which is about forwarding a client's OAuth token downstream — a different thing, and one that cannot arise here because the server receives no client token.)

All tool errors go through `_safe_error`, which maps exception types to controlled strings:

```python
def _safe_error(tool: str, exc: Exception) -> str:
    if isinstance(exc, IBKRAuthError):
        return f"Tool '{tool}' failed: IBKR session not authenticated. Re-open the gateway and log in."
    if isinstance(exc, IBKRAPIError):
        return f"Tool '{tool}' failed: IBKR gateway returned an error (HTTP {exc.status_code})."
    if isinstance(exc, BacktestRuntimeError):
        return f"Tool '{tool}' failed: strategy raised a runtime error."
    if isinstance(exc, FlexQueryError):
        return f"Tool '{tool}' failed: Flex Web Service error. Check IBKR_FLEX_TOKEN and IBKR_FLEX_QUERY_ID, or retry — ..."
    ...  # one fixed sentence per exception type; the status code is the only value interpolated
    return f"Tool '{tool}' encountered an unexpected error."
```

Adversarial strategy code that raises exceptions with embedded payloads cannot inject text into the model context through this path. Raw IBKR API error bodies, Flex XML content, and Python runtime exception messages are never forwarded.

Where a handler must show the model *detail* — the sandbox error it has to fix, a browser
failure it can act on, a resource handler's reason — it goes through one function,
`redaction.redact_error`: exception type plus the first line of the message, secret-shaped
material scrubbed by *shape* — Authorization and Cookie values, `sk-ant-`/`fc-` keys, URL
userinfo, every URL query string whole, and any `identifier=value` — quoted or not, so the
JSON and repr forms `{"identifier": "value"}` are covered too (SEC-06) — whose identifier contains
token/secret/password/session/credential/auth or names an API, access, secret or private key
(the first version anchored on exact words and let `refresh_token=` through; review
2026-09-13) — one line, 300 characters. A `requests` exception carries the full request URL,
and the Flex token travels in `?t=…` — probed 2026-09-13, verbatim in the text — which is why
every `{exc}`, `str(exc)`, `%`/`.format` interpolation, `.args` read, log call, `log.exception`
and `exc_info=` in `claude_tools.py` and `mcp_server.py` is routed through it and
`tests/security/test_error_redaction.py` fails on any that is not.

OWASP's list also names **filesystem paths**, and the username an absolute path carries is
exactly what the model never needs: the Flex import's root is documented to it as
`~/.ibkr_core`, while the refusal message spelled out `/Users/<name>/.ibkr_core` in full —
something the 2026-07-11 audit noted in passing ("discloses the exact home-directory path on
any invalid probe") and left. Since 2026-09-14 one function, `redaction.collapse_home`,
rewrites the home directory as `~`. One definition of "show a
path", the way `price_text_safe` is one definition of showing a broker price.

**Four surfaces call it**, and the set is an inventory rather than a filter, because a library
must not reconfigure the host application's logging: `redact_error` applies it to all exception
text before the length cap; `_import_flex_file` builds its refusal from it; and, since
2026-09-17, `mcp_server._issue_sse_token`'s token-file line and `store._restrict`'s
chmod-failure warning. Those last two are **logs, not model surfaces** — the rule below is
about the model and was never broken — but the function's own docstring claimed "every surface
that shows one to the model or a log" while both wrote `/Users/<name>/…` in full (audit finding
SEC-10; the store one came out of its sweep, which is why the count is stated and checked
rather than left to a reader). `test_error_redaction.py` drives each of the four under a
throwaway `HOME`. `local_browser._main`'s `print`s are deliberately outside the inventory: the
operator's own terminal, with `create-profile` refusing to run without a TTY.

### Tool inputs and outputs

**Inputs (invariant 11).** On the MCP transport an argument set that fails the tool's
`inputSchema` never reaches a handler: the SDK runs `jsonschema.validate` before calling
`handle_call_tool`, and `build_server` now says `validate_input=True` explicitly rather than
inheriting it. Until 2026-09-14 the property was the SDK's default and nothing more — no test
sent a malformed argument — which matters because `mcp` is the one dependency with a hard
ceiling (`mcp<2`: 2.0 removed the decorator carrying that default), so a port could drop the
check while every existing test stayed green.
`tests/security/test_tool_input_validation.py` now drives four malformed sets (wrong type,
missing required, enum violation, and the same on a server-local tool) through the real
request handler and asserts `_dispatch` — the single funnel behind every tool call — is never
reached; that no call anywhere in the package passes `validate_input=False`; and, because the
SDK validates only tools it has listed, that every name `_dispatch` routes is a listed tool.
A probe proves all four cases reach the handler once validation is switched off.
On the Anthropic-API path (`ClaudeToolkit.execute`) there is no schema step: handlers coerce
what they read and any exception becomes one fixed `_safe_error` sentence.

**Outputs.** All 46 tools return unstructured text; none declares an `outputSchema`, so there
is nothing to validate and none was invented. Rule: a future tool that returns structured
content declares an `outputSchema` and lets the SDK validate it. Output size was measured
rather than capped. List outputs are bounded: 50 rows from `get_trades`' store branch, 20 from
its CP-API-session branch, 50 from `get_pa_transactions`, 10 page URLs from `crawl_site`. The
sandbox's error channel is capped twice — the child sends one `redact_error` line of 300
characters, and the handler re-caps at 1,000 so a multi-violation RestrictedPython list is not
cut a second time. `fetch_page` returns the whole page (typically 5–35 KB; 144,125 characters
is the largest on record, `docs/web-scraper-reference.md` § 5). No cap is imposed there — the page is untrusted at
any size, and a silent clip would hide content from the operator. If a host ever reports
context exhaustion, the fix is explicit, marked truncation, not silent clipping.

### Tool composition under prompt injection

The capability registry classifies tools one at a time; it is not a composition control, so
OWASP's warning about chained calls was checked against concrete chains
(`docs/audits/owasp-mcp-guide-applicability-2026-09-14.md` § Phase 3 E). One is real: a
fetched page can instruct the model to read account data (`get_positions`,
`get_account_summary`, `get_trades`, `get_pnl`) and then call `fetch_page` or `crawl_site`
with that data in the URL — exfiltration to an attacker-chosen public host through two
individually permitted tools. It is not closable inside this package without breaking the web
tools, because any public URL can carry data, hostname labels included. The other two web
tools are weaker channels, not equivalent ones: `firecrawl_search` sends its query to
Firecrawl, not to a host the page chooses, and `search_site` ranks locally with BM25 and takes
a domain rather than a path — a domain the attacker controls is still a channel, but a much
narrower one.
What bounds it: no credential leaves (no tool returns one; `test_error_redaction.py`), no
order is placed (`test_order_write_boundary.py`), every fetch tool carries
`openWorldHint=true` for clients that confirm outbound calls, and the URL is visible in the
transcript. **Accepted, 2026-09-14.** The other chains checked — alert writes, cache
deletion, archiving hostile content to Drive, sandboxed compute, re-importing the operator's
own Flex archive — add no privilege beyond their declarations, and no chain reaches an order
write.

---

## Code Execution Security — Backtest Sandbox

Model-written strategy code runs in a `RestrictedPython` sandbox inside a child process — OWASP's *Code Injection & Unsafe Execution* item and §1's "run in isolated subprocesses": restricted file system access, restricted network access, and explicit resource limits.

### What is blocked

| Capability | Mechanism |
|---|---|
| `import` statements | Blocked syntactically by `compile_restricted` |
| `open`, `eval`, `exec`, `compile` | Removed from `__builtins__` |
| Network access (`urllib`, `requests`, `socket`) | Not importable — `__import__` removed |
| OS access (`os`, `sys`, `subprocess`) | Not importable |
| Module mutation (`pd.read_parquet = ...`) | Custom `_write_guard` blocks writes to `ModuleType` and `SimpleNamespace` |

### Safe namespaces

Raw `pd` and `np` module objects are replaced with `types.SimpleNamespace` wrappers that expose only in-memory operations:

- `_SAFE_PD`: `DataFrame`, `Series`, `concat`, `to_datetime`, `isna`, `notna`, `NaT`, `NA`
- `_SAFE_NP`: arithmetic, array creation, and math functions only — no `load*`, `save*`, `read_*`, `to_*`

This keeps `pd.read_*` out of reach and stops strategy code poisoning the process-level module
singletons. It does **not** by itself restrict what `df` — a real DataFrame — can do; that is
the attribute allowlist below.

### Attribute allowlist (2026-09-13)

`_sandboxed_getattr` applies an **allowlist** to every pandas or numpy object, instance or
class: only the names in `backtest._PANDAS_ALLOWED_ATTRS` / `_NUMPY_ALLOWED_ATTRS` resolve — the
vectorised-strategy vocabulary (arithmetic, reductions, indexing, rolling/ewm/expanding/groupby
windows, reshaping, `.str`/`.dt`, in-memory `to_numpy`/`to_list`/`to_frame`/`to_dict`). No
`to_*` writer, no `style`, no `plot`, no `info`, no `attrs`. The string-function argument of
`apply`/`agg`/`aggregate`/`transform` faces the same list, because pandas resolves that name
with its own unguarded `getattr`. `pd.DataFrame` and `pd.Series` are exposed as constructor
*functions*, not classes: a class hands out unbound methods whose first argument is the object,
which the string-function guard could not see — `pd.Series.apply(df['close'], 'to_csv', …)`
wrote a file after the first fix (fresh-eye review, 2026-09-13). Positional function specs of
any list-like shape are checked (dict views and generators reached pandas untouched); named
aggregation checks the function half of `(column, func)`; a column label (`df.close`) passes as
data when no DataFrame method shadows it. The runtime-error text returned to the model is one
line capped at 300 characters.

Why an allowlist: the 2026-09-13 audit demonstrated, by execution, that the previous two-name
denylist (`eval`, `query`) left `df.style.from_custom_template(dir, file)` rendering **any file**
through jinja2 into the error channel (arbitrary read, A1), `df.to_csv(path, header=False)`
writing **attacker-chosen bytes to any path** as the operator (A2), `df.to_clipboard()` spawning
`pbcopy`, and `df.apply("to_csv", path_or_buf=path)` / `df.pipe(pd.DataFrame.to_csv, path)`
reaching the writer by name. Every one of those is an ordinary public method. Naming the bad
ones one at a time is the `eval`/`query` fix again, forever. `tests/security/test_sandbox_boundary.py`
holds each path closed with canary files and pins the sandbox globals and the two safe
namespaces to frozen sets — widening any of them is a security change made in that test too.

### Resource limits

| Limit | Value | Error on breach |
|---|---|---|
| Code length | 4,096 characters | `BacktestSyntaxError` |
| Execution timeout | 10 seconds | `BacktestRuntimeError` (via a daemon watchdog thread that force-kills the `multiprocessing.Process` running the strategy — see `backtest.py`) |

### Residual risk

**DataFrame write methods (fixed 2026-09-13)** — This paragraph used to say strategy code
could write "the OHLCV market data passed to the sandbox to a local file, but cannot access
credentials, read arbitrary paths, or make network calls". The first half understated it (the
content was arbitrary) and the second half was false (`Styler.from_custom_template` read any
file). Both are closed by the attribute allowlist above. What remains: the sandbox child runs
with the operator's uid and no OS-level confinement, so the allowlist is the boundary. An
OS-level second layer (`sandbox-exec` on macOS) is the next step if that ever proves
insufficient.

**`DataFrame.eval`/`.query` (fixed 2026-07-11)** — Both methods run pandas' own expression engine on a string, entirely outside `compile_restricted`'s AST-level guards, and could reach `__globals__`/`sys.modules['os']` for full RCE (see `docs/audits/security-audit-2026-07-11.md` H-1). The sandbox's `_getattr_` hook denies `eval`/`query` by name with a specific message. Since 2026-09-13 that denylist is superseded in effect by the attribute allowlist above — neither name is on it — and the rule for a newly discovered string-evaluating method is the inverse: it is blocked unless someone adds it to `_PANDAS_ALLOWED_ATTRS`, which is the security change.

**Thread timeout non-termination (fixed 2026-07-16)** — The sandbox once ran strategy code in a `ThreadPoolExecutor` thread, which `Future.cancel()` cannot stop: `while True: pass` outlived the 10-second timeout and could hang the host at exit. It now runs in a `multiprocessing` spawn child with a `Pipe` for the result and a daemon watchdog that escalates SIGTERM → SIGKILL at the deadline — a process can be killed, a thread cannot, and killing it is also what unblocks the parent's pipe read. Design and review record: `docs/plans/archive/infrastructure/2026-07-15-backtest-sandbox-subprocess-isolation-design.md`.

---

## MCP Transports — stdio Preferred; SSE Loopback-Bound, Validated and Authenticated

**stdio is the default and the preferred transport** (OWASP §1 "prefer STDIO"; the MCP best-practices page's "use the stdio transport to limit access to just the MCP client"). The client is the process that spawned the server; there is no HTTP surface and no third party to authenticate.

`--transport sse` serves HTTP on `127.0.0.1:5174`. That bind stops the LAN, not the operator's
own browser: a page whose DNS answer flips to 127.0.0.1 becomes same-origin with the server,
opens `/sse`, reads the session id, and can POST JSON-RPC to `/messages/` — every tool, from an
unattended tab. The MCP SDK ships DNS-rebinding protection but **disables it when no settings
are passed** ("for backwards compatibility"), which is how `SseServerTransport("/messages/")` ran
until 2026-09-13 (audit A3). `mcp_server.build_sse_app` now passes `TransportSecuritySettings`
allowing only loopback `Host` and `Origin` values on any port; a foreign `Host` gets 421, a
foreign `Origin` 403. `tests/security/test_transport_security.py` drives the Starlette app both
ways; the SDK applies the same check to the `GET /sse` handshake and to `POST /messages/`.

### The per-launch bearer token (2026-09-14)

Host/Origin validation keeps out the browser and the LAN. It does nothing about another
*process* on the same machine, which needs no DNS trick and no browser — a second user
account, or a sandboxed app allowed loopback access, can simply `GET /sse`, read the session
id from the `endpoint` event, and call every tool. OWASP §1 ("if you must use local HTTP …
still utilize explicit authorization/authentication"), the MCP best-practices page ("require
an authorization token", "use unix domain sockets") and the
[transports specification](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports#security-warning)
("SHOULD implement proper authentication") all name the step.

Every SSE request must now present `Authorization: Bearer <token>`:

| Property | Value |
|---|---|
| Token | `secrets.token_urlsafe(32)`, fresh on every launch — nothing to configure, nothing to rotate, and it stops working when the server does |
| Where it goes | `~/.ibkr_core/mcp_sse_token`, mode 0600, in the directory `SQLiteStore` already holds at 0700. Only the path is logged, never the value: a terminal is scrolled, screen-shared and often captured |
| What is gated | The whole app — `/sse` as well as `/messages/`. Gating only the POST route would leave the half that hands out session ids open |
| Comparison | `hmac.compare_digest` over the entire header value, scheme included, so a prefix of the token is not distinguishable by timing |
| Order | Before the SDK's Host/Origin check, so an unauthenticated caller learns nothing about the loopback policy |
| Mechanism | `_BearerTokenGate`, pure ASGI — a Starlette `BaseHTTPMiddleware` buffers the response and would break the event stream |
| Not optional | `build_sse_app(server, token)` takes the token as a required argument, so an unauthenticated server cannot be built by forgetting one |

This was first written down, the same day, as an accepted residual with the fix "presented for
the owner's decision" on the belief that existing SSE clients would break. The review checked
the premise instead of repeating it: there are no SSE consumers — `claudia_ui` does not run
this server, desktop clients use stdio, nothing starts it from a launch agent — and the SDK's
own `mcp.client.sse.sse_client` already accepts `headers=`. With the cost at zero, the
standing rule applies: fix it rather than document it.

A client reads the token from the file; anything running as the operator can read that file,
which is the same boundary as the `.env` and the browser cookie store. The gate defends
against *other* local principals, not against code running as the operator. stdio remains the
preferred transport and needs none of this.

## Security Regression Suite — `tests/security/`

The 2026-09-13 audit's conclusion was that the important properties held by convention, and a
lint-clean, fully typed change could violate any of them silently. Each now has a test that
reads the source or drives the code, and a `security` marker (`pytest -m security`, ~10 s).
The last row, and the bearer-token half of the transport row, came from the 2026-09-14 OWASP
recalibration (`docs/audits/owasp-mcp-guide-applicability-2026-09-14.md`); the path-identifier
row from the 2026-09-16 release-readiness audit, which found property **(9)** listed in this
constitution with **no test at all** and false for three methods (findings SEC-03 and SEC-04) —
the constitution had eleven entries and the table ten; the published-identifier row from the
same audit, which found the account holder's account number in eight tracked files and their
legal name, balances, holdings and executed trades in a committed fixture (finding SEC-13);
the rest from the 2026-09-13 audit:

| File | Property held |
|---|---|
| `test_order_write_boundary.py` | The three order-write endpoints are built only inside the gated methods; each runs a gate before its first network call; the model layer never names an order write; `OrderWriteAuthorization` is minted in one function; the body Gate 2 shows is the body sent |
| `test_preview_is_not_execution.py` | `/orders/whatif` is built only by `get_order_preview`, which runs no gate; `preview_order` touches no other order method |
| `test_tool_capabilities.py` | Every tool declares capabilities; none declares `ORDER_EXECUTION`; `READ_ONLY` never shares a declaration with a mutating capability; every sink a handler touches is declared |
| `test_sandbox_boundary.py` | Strategy code cannot read, write, spawn or import — by attribute, by string name, by class attribute or by list-like spec; column labels and named aggregation still work; the error channel is one bounded line; sandbox globals and safe namespaces are frozen sets |
| `test_ssrf_boundary.py` | A twenty-row table of local/reserved address forms is blocked; every browser- or seeder-reaching handler validates first; both crawler entry points install the Playwright guard and `search_site` installs the httpx hook |
| `test_error_redaction.py` | Secret-shaped material (18 forms, userinfo, OAuth parameters and the quoted JSON forms included) never survives `redact_error`; no `except … as exc` in the model layer is interpolated, `%`/`.format`ted, `.args`-read, logged, `log.exception`ed or `exc_info`ed raw |
| `test_no_live_io.py` | Name resolution and TCP are blocked in unit tests; no variable the package reads (derived from source) is visible; `Config()` loads no `.env` |
| `test_subprocess_boundary.py` | Only `order_confirm`, `gateway/manager` and `backtest` spawn processes; no `shell=True` anywhere |
| `test_documented_controls.py` | The regexes this document presents as the mitigation are character-for-character what `client.py` compiles, in both directions; the documented `order_id` pattern actually rejects Unicode digits; every file running under `-m security` appears in the table above |
| `test_path_identifier_validation.py` | Every value interpolated into a URL path in `client.py` is itself passed to a validator, or listed with a reason; the checker fires on an unguarded snippet, ignores prose that merely begins with a path, and holds no exemption for an interpolation that no longer exists |
| `test_published_identifiers.py` | No tracked file in this PUBLIC repository carries the account holder's real account number, and the live-shape fixture carries no owner-scoped value at all — every scalar in it is a placeholder, a flag, or sits under a named structural exemption; the scan is proven non-vacuous against the placeholders it must find, and against the specific values that were once published |
| `test_transport_security.py` | The SSE transport rejects foreign `Host`/`Origin` and accepts loopback, with or without a port; it answers 401 to an absent, wrong, prefix, case-altered or scheme-altered bearer credential on both routes, and lets the real token through |
| `test_tool_input_validation.py` | On the MCP transport an argument set that fails the tool's `inputSchema` never reaches `_dispatch`; a well-formed one does; no call in the package passes `validate_input=False`; every name the dispatcher routes is a listed tool (the SDK validates no other); the probe reaches the handler for all four sets with validation off |

Each structural file also feeds its checker a deliberately-violating snippet, so the guard is
proven able to fire. The properties, as a constitution: **(1)** no order reaches IBKR except
through the four gated methods, and the model layer never references them; **(2)** preview is
not execution; **(3)** every tool declares its capabilities and none declares `ORDER_EXECUTION`;
**(4)** strategy code cannot touch the filesystem, processes or network, and its allowlist is
frozen; **(5)** every externally derived URL is checked before the fetch and on every browser
request; **(6)** error text reaching the model or a log passes one redaction function; **(7)**
unit tests cannot open sockets, resolve names or see credentials; **(8)** processes are spawned
only from three named modules, never through a shell; **(9)** every value
interpolated into a URL path is validated, or carries a written exemption; **(10)** the HTTP transport validates `Host`
and `Origin` and admits only the holder of this launch's bearer token; **(11)** on the MCP
transport an argument set that fails the tool's `inputSchema` never reaches a handler.

CI adds two gates the four code gates cannot provide: `pip-audit` over a **fresh resolve** of
`.[dev,server,scraper]` (requirements mode — `pip install --dry-run --report` in a throwaway
venv, installing nothing — weekly as well as per push, ignores only from
`security/pip-audit-ignores.txt` with a reason and a re-check date) and `gitleaks` over the
pushed range (`.gitleaks.toml`: default rules plus the Firecrawl and Anthropic key shapes).

The distinction matters and has already cost time: auditing the *installed* tree reports
what this machine happens to have, which is not what CI checks. During this audit a local
installed-tree run showed 50 vulnerabilities and a fix version that does not exist under
OSV, none of which CI sees (2026-09-16 near-miss).

## Session Security

### Gateway Session

The IBKR Client Portal Gateway is bound to `localhost` by design — no cloud deployment is supported. This limits the session hijacking surface: an attacker must have local machine access.

The MCP page's hijacking section (now *State Handle Hijacking*, about server-minted handles presented as tool arguments) does not apply: this server mints no handles and serves one principal. The session that matters locally is IBKR's:

- `BrowserCookieAuth` re-reads the session cookie from Chrome's store on each client instantiation — there is no persistent server-side session store that can be enumerated or guessed.
- `TokenAuth` (headless mode) holds the cookie as a Python `str` in process memory. It is not written to disk.
- The cookie is not logged or included in any `repr()` output, and it is only ever sent to a loopback host: `IBKRClient.__init__` and `IBKRWebSocket.connect` both refuse a non-loopback gateway URL before attaching it.
- The gateway validates the session server-side on every request; a stale or invalid cookie returns HTTP 401, which is surfaced as `IBKRAuthError` immediately (see rate limiter below — 401 is **never** retried).

### Browser Allowlist

`BrowserCookieAuth` validates the browser name against an explicit allowlist before `getattr` access on the `browser_cookie3` module:

```python
_ALLOWED_BROWSERS = frozenset({"chrome", "chromium", "firefox", "safari", "edge"})
```

This prevents traversal attacks via arbitrary attribute names on the module.

### Session Extraction Failure Handling

Import and extraction failures are handled distinctly to prevent silent unauthenticated sessions:

- `ImportError` on `browser_cookie3` → silent (expected in CI/headless environments where no browser is present)
- Any other exception → `warnings.warn` with the exception text (signals a broken Chrome profile or extraction failure to the operator)

---

## Docker Gateway Isolation — GatewayManager

`GatewayManager` (`ibkr_core_mcp/gateway/`) manages the Docker container that runs the IBKR Client Portal Gateway Java process. The following properties are verified:

### Container Isolation Model

The gateway container is started with `-p 127.0.0.1:5055:5055` (fixed 2026-07-11 — the prior `-p 5055:5055` form, with no host-IP prefix, published the container on all host interfaces by Docker's default behavior, not loopback only; see `docs/audits/security-audit-2026-07-11.md` H-3). No host networking (`--network host`) is used, no host volumes are mounted, and no `--privileged` flag is passed. The gateway is unreachable over the network from outside the machine.

### Residual risk — Docker bridge-network sibling containers

The host-loopback binding above closes external/LAN reachability, but does not fully isolate the gateway from *other containers on the same Docker host*. `GatewayManager` attaches the gateway to Docker's implicit default bridge network (no `--network` flag is passed). Verified empirically (2026-07-11): a host process connecting via `127.0.0.1` is NAT'd through the bridge and arrives at the container with a *bridge gateway* source IP (e.g. `172.17.0.1`), not `127.0.0.1` — this is why `conf.yaml`'s `ips.allow` legitimately needs the `172.16.*`–`172.31.*` range (see M-1's fix) for the host's own forwarded traffic to pass at all. That same requirement means a second, completely unrelated container on the same default bridge — launched with no `-p` flag, no special privileges — can reach the gateway directly on its internal bridge IP, bypassing the host-only publish entirely; its connection arrives from an IP the allowlist cannot distinguish from the host's own forwarded traffic (confirmed live: a throwaway sibling container reached the gateway's port and was logged as a plain `172.17.0.x` peer).

Accepted rather than fixed, for now, because the practical precondition is steep: exploiting this still requires a valid IBKR session cookie to do anything against the gateway's API, and a sibling container has no path to the host's browser cookie store or environment variables merely by sharing a bridge network — reachability alone isn't authorization. It also only matters if the host is *also* running unrelated Docker workloads; `GatewayManager` itself never creates a second container. If this needs closing later, attaching the gateway to an isolated custom bridge network (instead of the implicit default) would raise the bar from "any container on the host's default bridge" to "a container that specifically joins this network" — cheap, but not implemented here since it was assessed as out of proportion to the risk it removes.

### Subprocess Injection Analysis

All `docker` CLI calls in `manager.py` use list form (`subprocess.run(["docker", ...], ...)`), never `shell=True`. The three values that appear in subprocess arguments are:

| Value | Type | Source | Injection risk |
|---|---|---|---|
| `self._port` | `int` | Constructor parameter | None — integers cannot carry shell metacharacters |
| `self.IMAGE_NAME` | class constant `"ibkr-core-gateway"` | Hardcoded | None |
| `self.CONTAINER_NAME` | class constant `"ibkr_core_gateway"` | Hardcoded | None |

No user-supplied string reaches any subprocess argument.

### Shell Scripts (healthcheck.sh, run_gateway.sh)

The two bundled shell scripts receive all configuration via Docker environment variables set by `manager.py`:

| Variable | Set to | How |
|---|---|---|
| `GATEWAY_PORT` | `int` port value | `-e GATEWAY_PORT={self._port}` |

All values originate from `manager.py` constants or the integer `port` parameter. No external input is expanded by the shell inside the container.

`GATEWAY_PORT` is the only variable passed, and the shrink is itself the security change. A third script, `tickler.sh`, ran a `while true` loop POSTing `/tickle` on three `TICKLE_*` variables; it left the image on 2026-08-06 and the tree on 2026-08-07, and the variables stopped being passed the same day. An in-container renewal loop is not a neutral convenience — it cannot see the host-side suspend flag that coordinates a login, and on 2026-08-05 three of them kept a **borrowed** SSO session alive through every attempt to clear it (`POST /logout` could not; `docker restart` could). Renewal is the caller's, from the host. `healthcheck.sh` was changed from POST to GET on the same reasoning: `/tickle` is documented as preventing a session from ending, so a POST there is a session-affecting write dressed as a health check.

### conf.yaml Security Decisions

The gateway configuration file (`gateway/conf.yaml`) is a derivative of the IBKR-provided template. Each security-relevant setting is intentional:

| Setting | Value | Rationale |
|---|---|---|
| `cors.origin.allowed` | `"*"` | IBKR default; mitigated by `allowCredentials: false` — the browser will not send authentication cookies in cross-origin requests, so any cross-origin request will receive HTTP 401 |
| `cors.allowCredentials` | `false` | Prevents credential forwarding in CORS requests; effective mitigation for the wildcard origin |
| `ips.allow` | `127.*`, `192.168.*`, `172.16.*`–`172.31.*` (16 entries), `131.216.*` | Loopback + the *actual* RFC 1918 private ranges (fixed 2026-07-11 — `192.*`/`172.*` previously matched the full `192.0.0.0/8`/`172.0.0.0/8` blocks, 256×/16× broader than RFC 1918 and including public IPv4 space; see `docs/audits/security-audit-2026-07-11.md` M-1) + IBKR's own proxy infrastructure (`131.216.*`) needed for `proxyRemoteHost: api.ibkr.com`. This allowlist is a compensating control, not the primary defense — see H-3's fix for why the container shouldn't be reachable beyond loopback in the first place. |
| `sslPwd` | `"mywebapi"` | Well-known default password for the IBKR-bundled self-signed JKS keystore. Not a secret — all IBKR Client Portal users share this default cert and password. The certificate is self-signed and localhost-only. |
| `listenSsl` | `true` | Gateway always uses HTTPS, even on loopback |

### Supply Chain — Dockerfile

The Dockerfile downloads the IBKR Client Portal zip at build time:

```dockerfile
RUN curl -O https://download2.interactivebrokers.com/portal/clientportal.gw.zip
```

TLS certificate verification is performed (no `-k` flag). There is no SHA-256 checksum verification of the zip — this is an accepted risk in the same class as `pip install` or `apt-get install` without a separately verified hash. The download source is IBKR's official distribution server over HTTPS.

The Docker layer cache means the download only occurs on the first `docker build`. Subsequent starts use the cached image.

### urllib3.disable_warnings — Scope

`manager.py` calls `urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)` at module import time. This is a **process-global** side effect: it suppresses `InsecureRequestWarning` for all `requests` calls in the same Python process, not only gateway health-check calls.

This is intentional. Exactly three code paths disable certificate verification, and every one is pinned to loopback before it can run: the gateway health and auth polls in `manager.py` (`requests.get(..., verify=False)` against `https://localhost:{port}`), the `IBKRClient` session (`self._session.verify = False`, permitted only because the constructor raises `ConfigError` for any non-loopback `gateway_url`), and `IBKRWebSocket.connect` (`ssl.CERT_NONE`, after the same loopback check). No external IBKR or third-party call disables verification; `client.py` also calls `urllib3.disable_warnings` at import. The warning suppression prevents console noise from expected behaviour; it does not weaken any other connection's actual TLS verification.

---

## Secrets Management

### API Keys and Tokens in Config

`flex_token` and `firecrawl_api_key` are declared `field(repr=False)` in the `Config` dataclass:

```python
@dataclass
class Config:
    flex_token:        str = field(default="", repr=False)
    firecrawl_api_key: str = field(default="", repr=False)
```

`anthropic_api_key` was the third until 2026-09-17, when the field was removed outright: the
package makes no model call and never read it (TOOL-07), and
`test_config_carries_no_model_vendor_credential` holds that no vendor's model credential returns
under any name. Both remaining fields are excluded from `repr()`, preventing accidental exposure in logs, tracebacks, and debug output. Exception text is the other channel a key can travel through — a `requests` failure carries the full request URL, Flex token included — which is why every exception the model layer shows or logs passes through `redaction.redact_error` (§ Error text and raw payloads reach the model only through redaction).

### Credentials Never in Version Control

`.env`, `token.json`, and `credentials.json` must never be committed to the repository. The package loads credentials from environment variables only — never hardcoded defaults. Two checks stand behind the rule: `gitleaks` scans every pushed range in CI (`.gitleaks.toml`), and the unit-test suite never sees the operator's values — `tests/conftest.py` makes `load_dotenv` a no-op and removes every secret-named variable, so a test cannot pass on a real key by accident (`tests/security/test_no_live_io.py`).

### OAuth Token File Permissions

The Google Drive OAuth refresh token file is written with `0o600` permissions immediately after creation:

```python
fd = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as fh:
    fh.write(creds.to_json())
os.chmod(token_path, 0o600)   # O_CREAT's mode applies only on creation; the chmod covers an existing file
```

(`gdrive_auth.persist_credentials` — **the one place it exists.** `cache.GDriveCache` and
`web_scraper.WebDocsStore` both delegate to it.)

> This read "and the same sequence in `cache.GDriveCache._get_service` and
> `web_scraper.WebDocsStore._get_service`" until 2026-09-16, and was stale in one direction
> and about to be stale in the other. `cache.py` had already been refactored to delegate, so
> the sequence had not been there for some time; `web_scraper.py` still had its own copy, and
> that copy was the defect — it called `creds.refresh(Request())` with no handler, so a
> revoked Google refresh token raised instead of re-running the interactive flow (WEB-03).
> Three implementations of one control is how a fix reaches two of them: `b1a4efb` added
> `RefreshError` handling on 2026-07-13 and its file list has no `web_scraper.py`.
> `tests/security/test_documented_controls.py` now fails if this claim and the tree disagree.

This restricts read access to the file owner, preventing other local users from reading the refresh token.

### In-Memory Secrets

The IBKR session cookie is held in process memory as a Python `str`. Core dumps or heap inspections could expose it. This is unavoidable in Python without native memory management — no practical mitigation exists short of OS-level memory protection. Operators should ensure core dumps are disabled in production environments.

---

## Network Security

### SSRF Prevention (Flex Web Service)

The IBKR Flex Web Service returns a `<Url>` element used in a subsequent HTTP request. A MitM attacker or compromised IBKR endpoint could return `<Url>https://attacker.com/</Url>`, causing the Flex token to be sent as a query parameter to an attacker-controlled server.

Mitigation — strict allowlist prefix check before any request is made:

```python
_ALLOWED_URL_PREFIXES = ("https://ndcdyn.interactivebrokers.com/", ...)   # IBKR's Flex hosts, https only

if not any(url.startswith(p) for p in _ALLOWED_URL_PREFIXES):
    raise FlexQueryError(f"Flex SendRequest returned unexpected URL: {url!r}")
```

The MCP best-practices page's [SSRF section](https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices#server-side-request-forgery-ssrf) is the specific reference for this class — attacker-influenced metadata redirecting a request — and its notes on redirect targets, encoding tricks and DNS time-of-check/time-of-use are why the browser path below has a second, per-request layer. (The OWASP guide has no SSRF section; this is the one place the MCP page is the more specific source.)

### SSRF Prevention (Web Scraping — the local browser)

Three of the four web tools fetch **from the host machine**: `fetch_page` and `crawl_site` drive
a local Chromium via Playwright, and `search_site` drives crawl4ai's httpx sitemap seeder. That
is a materially different risk profile from `firecrawl_search`, where a remote API does the
fetching and no local network is reachable at all.

The exposure is not only the URL the operator typed. `crawl_site` follows same-host links it
discovers as it goes, and `search_site` resolves a domain the model supplied — attacker-
influenceable inputs that nobody pre-approved.

> **Restructured 2026-07-30.** This section previously described the guard as sitting inside a
> Firecrawl→Crawl4AI *fallback* ladder (`_assess_fallback_need`, `_apply_crawl4ai_fallback_batch`,
> `_scrape_with_fallback`). That ladder and all three functions were deleted when the browser
> became the primary engine. **The two layers below are unchanged and were never weakened** —
> only the call sites moved.

Mitigation — `ClaudeToolkit._validate_public_url` (`claude_tools.py`) is called before **every**
URL or host that can reach the local browser:

```python
def _validate_public_url(self, url: str) -> str | None:
    # Blocks non-http/https schemes, missing hostnames, localhost/link-local
    # hostnames, and literal or DNS-resolved private/loopback/reserved IPs
    # (including decimal/hex-encoded IP literals, e.g. http://2130706433/).
```

Three call sites, one per browser-driving tool, each **before** the browser is constructed —
a late check has already made the request it was meant to prevent:

| Handler | What is validated |
|---|---|
| `_handle_fetch_page` | the page URL |
| `_handle_crawl_site` | the crawl root URL |
| `_handle_search_site` | the domain, as `https://{domain}/` |

Covered by `test_web_tools_live.py::test_private_hosts_are_refused_before_any_request`,
parametrized across all three, which asserts the refusal happens with `crawl4ai` absent as well
— rejection must not depend on the browser being installed.

**Defense in depth — two independent SSRF layers, not one.** A single validate-then-fetch check has a structural gap: it resolves DNS once, in one process, and the actual browser fetch happens moments later, in a different process, with its own independent DNS resolution — vulnerable to DNS rebinding (attacker serves a public IP at validation time, a private IP at fetch time via TTL=0) and to redirect-based bypass (a URL that passes validation responds with a redirect to a private address, which is never re-checked). This was identified during the 2026-07-01 audit and closed with a second, independent layer rather than left as an accepted gap:

1. **Pre-fetch check** — `ClaudeToolkit._validate_public_url`, above. Cheap, runs before a browser is even launched, blocks the common case.
2. **Per-request browser-level check** — `local_browser._reject_private_requests`, a Playwright request-interception handler installed via Crawl4AI's `on_page_context_created` hook on every scrape:

```python
async def _reject_private_requests(route, request):
    host = (urllib.parse.urlparse(request.url).hostname or "").lower()
    if _is_private(url):
        await route.abort()
        return
    for _ in range(_MAX_REDIRECT_HOPS):
        response = await route.fetch(url=url, method=method, max_redirects=0)
        if response.status not in _REDIRECT_STATUSES:
            await route.fulfill(response=response)
            return
        url = urllib.parse.urljoin(url, response.headers.get("location"))
        if _is_private(url):
            await route.abort()
            return
    await route.abort()
```

This handler intercepts every request Chromium makes during the page load — the initial
navigation and every subresource — and re-resolves + re-checks each one at the moment it's
actually about to be sent, inside the same browser process. **Redirect hops are resolved by the
handler itself**, one at a time with `max_redirects=0`, so every URL in a chain is checked and
not merely the one the caller supplied.

> **This paragraph was wrong until 2026-09-16, and the gap it described as closed was open.**
> The handler ended in `route.continue_()`, which hands the request to Chromium — and Chromium
> follows a 3xx *internally*, emitting no second route event. Subresources did fire the hook
> (45 route events measured on an asset-heavy page), so the glob was never the problem; the hop
> was simply invisible. `https://<public-host>/redirect-to?url=http://127.0.0.1:<port>/` fetched
> the loopback page and returned it to the model, reproduced with a canary server whose own
> access log recorded the connection. The claim below — that this was "verified … against the
> Chromium/Playwright network stack, which routes redirects … through the same
> request-interception path as the initial navigation" — was the specific sentence that was
> false. `search_site`'s httpx half was correct throughout, because httpx runs its request hook
> per hop. The test that was meant to hold this asserted only that a handler had been
> *registered*, on a fake page object, so it stayed green the whole time; it is now backed by
> `tests/test_web_tools_live.py::test_a_public_url_that_redirects_to_loopback_never_reaches_it`,
> which uses real Chromium, a real redirector and a real server whose request counter is the
> assertion.

DNS rebinding is narrowed but not eliminated: the check that matters is the one immediately
before Chromium connects rather than an earlier check in a different process, but
`is_private_host` still performs its own resolution, so a TTL-0 flip between that lookup and
Chromium's remains theoretically possible. Redirects to a private address are now aborted
regardless of what the original URL looked like. Both layers share one implementation (`local_browser.is_private_host`) so they cannot silently drift apart. Since 2026-09-13 that implementation also parses every
non-canonical literal locally with `socket.inet_aton` before asking DNS — decimal, hex,
**octal** (`0177.0.0.1`, which the system resolver reads as public 177.0.0.1 and Chromium as
127.0.0.1) and short forms — and blocks the RFC 6598 shared range `100.64.0.0/10` (CGNAT,
Tailscale) and the IPv4 inside an IPv4-mapped IPv6 address. `tests/security/test_ssrf_boundary.py`
holds a table of twenty forms, none needing DNS. **`search_site` gets the same per-request layer in httpx form**: `_reject_private_httpx_request`
is installed as a request hook on the seeder's own client, so every robots/sitemap/`<head>`
fetch and every redirect hop is re-checked at the moment it is sent (fresh-eye review 2026-09-13;
until then the seeder had layer 1 only, and a sitemap listing a loopback URL was fetched). Verified 2026-09-13 against `crawl4ai==0.9.0` source (`async_crawler_strategy.py`), and re-verified 2026-09-17 against the now-installed **0.9.2**, where the hook is still called with the live context (`async_crawler_strategy.py:615`) and the live redirect-SSRF test passed against real Chromium. The extra floats (`crawl4ai>=0.5.0`), so this citation is dated on purpose — it read as a claim about what *is* installed until `SEC-R3` confirming the `on_page_context_created` hook receives the live Playwright `page` object, and against the Chromium/Playwright network stack — where subresources do route through the request-interception path but **redirects do not**, which is why the handler resolves them itself (see the correction above).

**Path-traversal hardening (defense in depth):** the domain extracted from a URL is used to build a filesystem path (`profiles_dir / domain`, for locating and writing saved login profiles). `local_browser._safe_domain` explicitly rejects any domain containing `..`, `/`, or `\`, or that is empty, before it reaches a path join — independent of upstream URL validation, so it can't be silently reopened by a future change elsewhere.

**Own-subscriptions-only design:** paywall access via Crawl4AI never stores credentials. `python -m ibkr_core_mcp.local_browser create-profile <site>` opens a real (human-driven) browser for a one-time interactive login; only the resulting cookie/session profile is saved locally under `Config.crawl4ai_profiles_dir`, one subdirectory per domain. This is a manual, operator-only CLI path — not reachable from any LLM tool input.

### TLS Policy

| Connection | TLS verification |
|---|---|
| IBKR Client Portal Gateway (`localhost:5055`) — Python REST (`IBKRClient`, `GatewayManager` polls) | `verify=False` — intentional; self-signed cert on loopback only; the client constructor refuses any non-loopback URL |
| IBKR Client Portal Gateway — WebSocket (`IBKRWebSocket`) | `ssl.CERT_NONE` — same certificate; `connect()` refuses any non-loopback URL before sending the cookie |
| IBKR Client Portal Gateway — container-internal (`healthcheck.sh`) | `curl -sk` — verification disabled; self-signed cert on loopback within the Docker network |
| IBKR Flex Web Service (`ndcdyn.interactivebrokers.com`) | Standard TLS, no overrides |
| Google Drive API | Standard TLS via Google client library |

No external IBKR or third-party connections are made with verification disabled.

### Rate Limiting and Retry Safety

`rate_limiter.py` provides these properties relevant to security:

0. **Requests are paced before they are sent** — `EndpointPacer` holds each endpoint to
   IBKR's published limit using a sliding window, so the package does not earn the 429 in
   the first place. This matters beyond politeness: a 429 puts the **IP** in a
   fifteen-minute penalty box covering every endpoint, so one component's burst denies
   service to all the others. Added 2026-09-16, after `get_market_history_paginated` was
   measured at 284 requests/minute against a published ceiling of 50. It is bounded — see
   `_MAX_PACING_WAIT` — so it degrades to a warning rather than becoming a self-inflicted
   hang.

The `with_retry` wrapper adds:

1. **401 is never retried** — an unauthenticated response raises `IBKRAuthError` immediately. This prevents credential stuffing or accidental brute-force against the gateway.
2. **429/503 use exponential backoff** — bounded at `max_retries` (default 3) with `backoff = 1.0 × 2^attempt` seconds. This protects IBKR from accidental DoS.
3. **All 2xx are accepted as success** — `200 ≤ status < 300` avoids treating HTTP 201 (Created) or 204 (No Content) as errors, which could cause write endpoints to be retried unnecessarily.

---

## Data Security

### SQL Injection Prevention

All SQL queries in `SQLiteStore` use parameterized queries with `?` placeholders — never f-strings or string concatenation with user-supplied values:

```python
query = "SELECT * FROM trades WHERE 1=1"
params: list[Any] = []
if symbol:
    query += " AND symbol = ?"
    params.append(symbol.upper())
...
conn.execute(query, params)
```

LLM-supplied `symbol`, `start`, and `end` values from `get_trades` are passed as bind parameters only. `account_id` is validated via regex before reaching any query.

### External API Response Handling

`IBKRClient` returns IBKR's JSON — as plain dicts from most endpoints, and through a Pydantic model from 29 of them (`client.py`'s module docstring names each, and a test derives the list from `models.py`). Every model derives from `IBKRResponse`, which keeps the payload as sent and serves it through the mapping protocol, so a typed return narrows nothing; `bars_to_dataframe` normalises history bars. **Two claims in this paragraph were false until 2026-09-17** (API-R3): it said `IBKRClient` returns plain dicts, which stopped being true when API-11's first tranche landed on 2026-09-16, and that *nothing in the package calls `model_validate`* — `models.parse_one` does, which is how a payload that fails validation is handed back untouched instead of raising. Before 2026-09-13 it claimed the opposite, that every response was validated; that was false too. **Neither correction makes response validation a boundary control.** `parse_one` catches `ValidationError` and returns the payload exactly as it arrived — measured 2026-09-17: a malformed `accountId` comes back as the original `dict`, not as a rejection — so nothing is refused on validation and the list that follows is still the whole of it. The actual boundary controls on response data are: identifiers that come *back* from IBKR and are re-used in URLs pass the same regexes as model-supplied ones; reply messages rendered on Gate 2 are HTML-stripped; `IBKRAPIError` carries at most 400 bytes of a gateway body and never reaches the model except through `_safe_error` (status code only); web content is never parsed as instructions by this package — it is returned to the model, which is why the four web tools flag thin or blocked pages (`assess_quality`) rather than presenting them as content.

### XML Parsing

`defusedxml.ElementTree` replaces stdlib `xml.etree.ElementTree` for all Flex XML parsing:

```python
import defusedxml.ElementTree as ET
root = ET.fromstring(resp.content)
```

The stdlib parser does not resolve external entities (no XXE) but does process entity expansion, making it vulnerable to billion-laughs-style memory exhaustion. `defusedxml` blocks both classes of XML attack.

### SQLite Store

Trades, signals, backtest results, and position snapshots are stored in a local SQLite database. No encryption at rest is applied — **OS filesystem permissions are the primary control**, which makes them a control this package must enforce rather than recommend.

Until 2026-08-05 this section read *"should be stored in a user-owned directory with `0o600` permissions"* and nothing implemented it. The live store was `0644` — 53 MB holding every trade the account had ever made, readable by any user on the machine. It was found by the `claudia_ui` security audit, not by this package. A documented control with no enforcement is the failure mode being fixed here, not the file mode itself.

`SQLiteStore` now holds the permissions itself:

| Path | Mode | Where |
|---|---|---|
| `~/.ibkr_core/` (the `sqlite_path` parent) | `0700` | `__init__` — `mkdir(mode=0o700)` for the create case, plus an explicit `_restrict` for the far more common existing-directory case |
| `store.db` | `0600` | `_connect()` |
| `store.db-wal`, `store.db-shm` | `0600` | `_connect()` |

Three properties are deliberate and should not be "simplified" away:

- **The WAL sidecars are in scope.** `store.db-wal` holds committed transactions that have not been checkpointed, so it carries the same content as the database. Securing the main file alone would leave the most recent writes readable.
- **The repair is self-healing, not create-time-only.** `sqlite3.connect()` creates the database with `0666 & ~umask`, and neither `mkdir(mode=…)` nor an `O_CREAT` mode affects a path that already exists. Every install predating this code has a `0644` database and a `0755` directory, so a create-time fix would reach none of them. This is why the chmod lives in `_connect()` and runs unconditionally.
- **It never raises.** A failed chmod logs a warning and continues. Refusing to open the database because a permission repair failed would trade a confidentiality gap for an availability outage; a read that would have succeeded at `0644` still succeeds. It is logged rather than swallowed, because a chmod that silently never lands is indistinguishable from a control that was never written.

The mode is compared before chmod'ing, so the steady state is three `stat` calls per connection and no syscall churn.

Guarded by four tests in `tests/test_store.py` (`test_database_file_is_not_world_readable`, `test_wal_sidecars_are_not_world_readable`, `test_permission_repair_is_self_healing`, `test_parent_directory_is_owner_only`). The last two assert against a path deliberately set back to `0644`/`0755` first — the create path is the easy half and a temp-dir fixture exercises it for free, so a test that only covered creation would have passed against the unfixed code. It was written that way first, and did.

### Google Drive Parquet Cache

Market data parquet files are stored in a user-specified Google Drive folder. The OAuth token file is `chmod 0o600` after write. `GDRIVE_TOKEN_FILE` and `GDRIVE_CREDENTIALS_FILE` paths must never be committed to version control.

---

## Security Architecture — Defense in Depth

No single control is the sole barrier. Each threat has layered mitigations:

| Threat | Primary control | Secondary control |
|---|---|---|
| LLM triggers order execution | No order-write tools in `ClaudeToolkit` — asserted by `test_tool_capabilities.py` (no `ORDER_EXECUTION`) and `test_order_write_boundary.py` (no reference in the model layer) | Two-gate human auth enforced at innermost call site, its shape read from the source by the same test |
| LLM supplies malicious account ID | `_validate_account_id` regex (`^[A-Z0-9]{4,12}$`) | `_safe_error` prevents exception details reaching LLM |
| Prompt injection via exception messages | `_safe_error` maps all exceptions to controlled strings | `redact_error` bounds and scrubs the channels that need detail; `test_error_redaction.py` finds any raw `{exc}` |
| Sandbox escape via file I/O | Attribute allowlist on every pandas/numpy object and class (`_sandboxed_getattr`) — no `to_*` writer, no `style`, no `plot` | Safe `SimpleNamespace` wrappers for `pd`/`np`; `_write_guard` blocks namespace mutation; child process; canary tests |
| Browser tab drives the MCP server (DNS rebinding) | SSE transport bound to `127.0.0.1` | `TransportSecuritySettings`: foreign `Host` → 421, foreign `Origin` → 403 |
| Another local process drives the SSE server | `_BearerTokenGate`: every request to `/sse` and `/messages/` presents this launch's token or gets 401, checked with `hmac.compare_digest` before Host/Origin | stdio is the default and has no HTTP surface at all; SSE is opt-in and loopback-only; order execution and credentials stay unreachable whatever the caller |
| A fetched page instructs the model to send account data to an attacker's host | No credential or order capability is reachable by any chain (`test_tool_capabilities.py`, `test_order_write_boundary.py`) | Every fetch tool carries `openWorldHint=true` for clients that confirm outbound calls; the URL is visible in the transcript — accepted composition risk (§ Tool composition) |
| Malformed tool arguments reach a handler over MCP | `inputSchema` validation before `_dispatch`, `validate_input=True` stated explicitly and held by `test_tool_input_validation.py`, which also holds that every routed name is a listed one | Handlers coerce what they read and `_safe_error` bounds any failure |
| Sandbox DoS (infinite loop / large allocation) | 10-second execution timeout | 4,096-character code length cap |
| SSRF via Flex URL field | Domain allowlist prefix check | HTTPS enforced on all external connections |
| SSRF via the local browser (`fetch_page` / `crawl_site`) or the seeder (`search_site`) | `_validate_public_url` blocks private/loopback/link-local/reserved/shared-range hosts before anything is constructed, parsing decimal/hex/octal literals locally; the validate-before-reach order is asserted by `test_ssrf_boundary.py` | `_reject_private_requests` re-checks every request Chromium actually makes (navigation, redirects, subresources) at the Playwright level; `_reject_private_httpx_request` does the same on the seeder's httpx client for `search_site`. Crawl4AI is also an opt-in extra (`pip install ibkr_core_mcp[scraper]`) — base install has no local-fetch surface at all |
| Path traversal via crafted domain (`profiles_dir / domain`) | `_safe_domain` explicitly rejects `..`, `/`, `\`, and empty domains before any path join, in both `Crawl4AIScraper.scrape_batch()` and `create_profile()` | `create_profile()` is CLI-only (human-typed argument, no LLM/tool-input path) |
| The operator's username leaks through a path in a tool result **or a log line** | `redaction.collapse_home` rewrites the home directory as `~`, applied by `redact_error`, by `_import_flex_file`'s refusal and — since 2026-09-17, SEC-10 — by the SSE token-file line and `store._restrict`'s chmod warning | Canaries in `test_error_redaction.py`: the real handler's blocked-path message, plus both log surfaces driven under a throwaway `HOME` |
| Credential exposure in logs or tool results | `repr=False` on `flex_token` and `firecrawl_api_key` (no model credential exists in `Config` to expose, by test); every logged or shown exception passes `redact_error` | Credentials loaded from env vars only, never hardcoded; `gitleaks` in CI; unit tests never load `.env` |
| Vulnerable dependency in the resolved tree | `pip-audit` over `[dev,server,scraper]`, per push and weekly, fixable findings block | Dependabot alerts on the manifest's direct dependencies |
| OAuth token readable by other users | `os.chmod(token_file, 0o600)` after write | Token file path user-configurable, not world-accessible by default |
| Trade store readable by other users | `SQLiteStore._connect()` holds `store.db` and both WAL sidecars at `0600` on every connection — self-healing, so installs created before 2026-08-05 are repaired rather than left at `0644` | `__init__` holds the `~/.ibkr_core/` parent at `0700`, covering the Flex XML archive and the Drive OAuth token in the same directory |
| XML bomb DoS | `defusedxml` blocks entity expansion | Flex polling bounded to 5 retries |
| SQL injection | Parameterized queries throughout `store.py` | LLM input validated before reaching query construction |
| Unauthenticated session on cookie failure | `warnings.warn` on extraction error (not silent) | `browser_cookie3` access restricted to allowlisted browser names |
| Session credential exposure in 401 retry | 401 raises `IBKRAuthError` immediately, never retried | — |
| Docker supply chain (IBKR zip download) | HTTPS with server cert verification from IBKR's official distribution server | Accepted risk: same class as `pip install` without a separately-verified hash |
| Cross-origin browser requests to gateway | `allowCredentials: false` prevents session cookie forwarding in CORS requests | IP allowlist (`127.*`, `192.168.*`, `172.16.*`–`172.31.*`, `131.216.*`, fixed 2026-07-11) restricts inbound connections to loopback and the actual RFC 1918 private ranges |
| Gateway container compromise / escape | Loopback-only port exposure (`-p 127.0.0.1:5055:5055`, fixed 2026-07-11), no `--privileged`, no host volume mounts | Standard Docker isolation; gateway has no access to host filesystem or other containers |

---

## Contributor Security Rules

The following rules are enforced at PR review. Any PR that violates them will be rejected:

1. **Never add a bypass flag or a session cache** to `require_touch_id` or any order confirmation function. An `OrderWriteAuthorization` is not a cache: it is bound to one write's account and body, expires in 300 s, is verified at the write and at every reply, and fails closed — never widen it.
2. **Never move the gates out of `IBKRClient`** — enforcement must be at the innermost call site inside `place_order`, `modify_order`, `cancel_order`, `reply_order`.
3. **Never make an authorization global or persistent, and never let a reply skip its dialog** — one biometric per order write, one dialog per message. The device-password fallback under `LAPolicyDeviceOwnerAuthentication` is Apple's recovery path and stays.
4. **Never add order-write tools to `ClaudeToolkit`** — the LLM must not have a path to order execution. Every new tool declares its `capabilities`; `ORDER_EXECUTION` may never appear, and a handler that touches a sink its declaration omits fails `tests/security/test_tool_capabilities.py`.
5. **Never forward raw exception messages to the LLM or a log** — `_safe_error` for tool error returns; `redact_error` wherever detail is needed. `tests/security/test_error_redaction.py` fails on a bare `{exc}`, `str(exc)` or `log.warning(..., exc)` in `claude_tools.py` / `mcp_server.py`.
6. **Never pass unsanitized LLM input to URLs or SQL** — validate with `_validate_account_id` or equivalent before use.
7. **Never use string concatenation in SQL queries** — all user-supplied values must be passed as bind parameters.
8. **Never use stdlib `xml.etree.ElementTree` for external XML** — use `defusedxml.ElementTree`.
9. **Never widen the sandbox by accident** — a name added to `backtest._PANDAS_ALLOWED_ATTRS` / `_NUMPY_ALLOWED_ATTRS`, or an object added to `build_sandbox()`, is a security change: check it accepts no path, buffer, callable or string resolved as a name, and update the frozen sets in `tests/security/test_sandbox_boundary.py` in the same commit.
10. **Never spawn a process outside `order_confirm`, `gateway/manager` and `backtest`** without adding the module to `tests/security/test_subprocess_boundary.py` with the reason; never `shell=True`.
11. **Never let a fetch reach a model-supplied host before `_validate_public_url`**, and install `_install_ssrf_guard` on every browser this package opens.
12. **Never register the MCP call handler with `validate_input=False`**, and add every new server-local tool to `_ALL_TOOL_DEFS` as well as to `_dispatch` — the SDK validates only tools it has listed. Give any future tool that returns structured content an `outputSchema`. `tests/security/test_tool_input_validation.py` holds the first two; the third is a rule until a structured tool exists.
13. **Never give `build_sse_app`'s `token` a default, and never print the token** — a default makes an unauthenticated server reachable by forgetting an argument, and a terminal is not a secret store. The file is 0600 under `~/.ibkr_core/`; only its path is logged.
14. **Never show the model an absolute path built from `Path.home()`** — pass it through `redaction.collapse_home` so the message names the root, not the account.

---

## Audit History

| Date | Commit | Scope | Outcome |
|---|---|---|---|
| 2026-05-25 | `4dbe6ad` | All production modules | 2 Critical, 5 High, 5 Medium resolved. 3 Low/Info accepted. |
| 2026-05-25 | `5f7b5ab` | `flex_query.py` | URL validation, datetime error handling hardened. |
| 2026-06-10 | `bc8032b` | `gateway/` module — `GatewayManager`, `Dockerfile`, `tickler.sh`, `healthcheck.sh`, `conf.yaml` | 5 Low/Informational findings (GW-01 – GW-05) accepted. No code changes required. All subprocess calls use list form; no user input reaches shell. Docker container exposed on localhost only, no privileged mode. |
| 2026-06-10 | `015e379` | All 14 production modules — full codebase audit (security + code quality) | 3 High, 7 Medium, 9 Low resolved. 5 Informational (dead code, style) cleaned up. 4 code-quality refactors (duplicate patterns extracted). |
| 2026-06-10 | `6d246ab` | Publish readiness pass | 3 new Medium findings resolved (stream-loop logger leak S-1, `max_results` unbound S-2, `urllib3` CVE floor S-3). Backtest sandbox docstring corrected (S-4). PyPI metadata complete; LICENSE added; CI workflow added; GatewayManager tests added; account_id and PineScript injection tests added. |
| 2026-06-27 | `pending` | v1.0 pre-release full audit — all 22 source files across 12 attack categories | 6 findings: 4 Medium, 2 Low. 4 fixed in code (path traversal in `import_flex_file`, SSRF decimal/hex IP bypass, `FlexQueryError` message leakage, `preview_order` input validation). 1 documented residual (backtest thread non-termination — architectural, tracked for v2.0). 1 confirmed mitigated (DataFrame I/O in sandbox — write-only OHLCV, already in residual risk section). No Critical or High findings. All SQL injection, command injection, shell=True, pickle, credential logging, and MCP order gate bypass checks passed. |
| 2026-07-01 | `eece77b` | New Crawl4AI fallback surface — `local_browser.py` (new), `claude_tools.py` (`_validate_public_url`, `_scrape_with_fallback`) | 2 candidate SSRF findings identified, each independently re-verified against the actual code by a separate filtering pass: DNS-rebinding TOCTOU between `_validate_public_url`'s validation-time DNS resolution and Crawl4AI/Chromium's independent fetch-time resolution (confidence 7/10); unvalidated-redirect-based bypass (confidence 3/10, downgraded per open-redirect precedent but confirmed as a real code gap on read-through). Both fixed in code rather than accepted as residual risk — see `_reject_private_requests` in the SSRF Prevention section above (Playwright-level per-request guard via Crawl4AI's `on_page_context_created` hook, closing both gaps at the actual fetch layer). Path-traversal via a crafted hostname (`profiles_dir / domain`) also hardened: `_safe_domain` now explicitly rejects `..`/`/`/`\`, replacing what had been an incidental block via `_validate_public_url`'s IDNA-encoding failure. No credential exposure or command injection issues found. |
| 2026-09-13 | `c4b4ba8..e57aabb` | Security *architecture* audit — whether the boundaries are enforceable and whether a lint-clean, typed, green change (possibly by a coding agent) could violate one silently. Read-only trace of every tool to its sinks, then live probes. | 3 confirmed: sandbox arbitrary file **read** (`Styler.from_custom_template` through the un-redacted error channel) and **write** (`to_csv` and five by-name forms) from strategy code — both demonstrated by execution, fixed with an attribute allowlist; SSE transport without Host/Origin validation (SDK default) — fixed. 9 architectural weaknesses closed with structural tests: `tests/security/` (9 files, 138 tests, each structural checker proven to fire on a violating snippet), `capabilities` on all 46 tools, `redact_error`, `.env` isolation, `inet_aton` literal parsing + `100.64.0.0/10`, dict copy before the gates, subprocess allowlist. CI gained `pip-audit` (first run caught nltk PYSEC-2026-3740, no fix, ignored with re-check) and `gitleaks`. GitHub's default CodeQL setup evaluated on its record and kept as a non-gate. Design written up as `docs/security-architecture.md`. A fresh-eye multi-angle code review the same day found the first sandbox fix still reachable through the exposed classes (`pd.Series.apply(series, 'to_csv', …)`) and through dict views, and two pandas idioms it had broken (`df.close`, named aggregation); the transport allowlist refusing a port-less `Host`; the redaction rules letting `refresh_token=` through; the seeder with no per-request guard; the session-wide socket block skipping the first live module's fixtures; and the `mcp` floor too low for `transport_security`. All fixed the same day with the reproducing tests first (audit Addendum D). |
| 2026-09-14 | `c03e038` | Security guidance recalibration against the OWASP GenAI Security Project's *A Practical Guide for Secure MCP Server Development* v1.0 (Feb 2026), retrieved in full with Firecrawl and archived under `docs/audits/audit-evidence/scrapes/`; the official MCP best-practices page re-read as served (2026-07-28 revision) | 49 OWASP items classified: 21 apply and are covered or exceeded, 8 apply in part, 20 do not apply to a local single-operator deployment. OWASP adopted as the principal external baseline; the six-row MCP mapping retired — two of its rows had come to cite sections that now mean something else (OAuth token scopes; a renamed hijacking section about server-minted handles). Three changes, each test-first. **Invariant 11** (new): MCP argument validation against `inputSchema` held only by SDK default and untested, with `mcp<2` capped because 2.0 removes the decorator carrying that default — now asserted through `_dispatch`, together with the fact the SDK validates only listed tools. **Invariant 10** (widened): the SSE transport gained a per-launch bearer token, first written down as an accepted residual and implemented the same day once the review found no consumer that would break. **Path disclosure**: `redaction.collapse_home` rewrites the operator's home directory as `~` for every model-facing message, closing something the 2026-07-11 audit had noted and left. The read-then-fetch exfiltration chain under prompt injection was investigated and accepted, with what bounds it named. Full matrix, including everything rejected and why: `docs/audits/owasp-mcp-guide-applicability-2026-09-14.md`. |
| 2026-07-11 | `4e38655..e587695` | Full codebase — 6-agent parallel audit (one per risk cluster: auth/order gates; backtest sandbox + store; network/SSRF/Drive/Flex; IBKR client + MCP server; `claude_tools.py` LLM-tool layer; gateway Docker/shell infra), every finding independently re-verified by a second adversarial agent before inclusion | 6 findings, all fixed: 4 High — RCE via `DataFrame.eval`/`.query` in the backtest sandbox (H-1); `order_id`/`alert_id` path traversal letting the ungated `delete_alert` tool's URL collapse to `cancel_order`'s (bypassing Touch ID + confirmation dialog) (H-2); gateway Docker container published on all host interfaces instead of loopback (H-3); SSRF guard's IPv4-only DNS resolution failing open on AAAA-only hosts (H-4). 2 Medium — gateway IP allowlist matching full `/8` blocks instead of actual RFC 1918 ranges (M-1); `import_flex_file`'s path-prefix check admitting sibling directories via string-prefix matching instead of a path-boundary check (M-2). 1 candidate finding (Gate-2 dialog/order-dict TOCTOU in `place_order`/`modify_order`) investigated and dropped at verification — no reachable caller in this repo. Each fix went through implementer + independent spec-compliance + independent code-quality review before acceptance; two review rounds found real follow-up issues (a Unicode-digit regex gap in H-2's `_ORDER_ID_RE`, a second stale doc reference for H-3), both fixed forward in separate commits rather than folded silently into the original ones. |

Full audit reports: [`docs/audits/security-audit-2026-05-25.md`](docs/audits/security-audit-2026-05-25.md) · [`docs/audits/security-audit-2026-06-10.md`](docs/audits/security-audit-2026-06-10.md) · [`docs/audits/security-audit-2026-07-11.md`](docs/audits/security-audit-2026-07-11.md) · [`docs/audits/security-architecture-audit-2026-09-13.md`](docs/audits/security-architecture-audit-2026-09-13.md) · [`docs/audits/owasp-mcp-guide-applicability-2026-09-14.md`](docs/audits/owasp-mcp-guide-applicability-2026-09-14.md). The living design behind these controls: [`docs/security-architecture.md`](docs/security-architecture.md).
