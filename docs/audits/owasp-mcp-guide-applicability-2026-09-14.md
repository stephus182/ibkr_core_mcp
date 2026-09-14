# OWASP MCP Guide — Applicability to ibkr_core_mcp — 2026-09-14

**Kind.** Security guidance recalibration, not an audit. The 2026-09-13 architecture audit
(`security-architecture-audit-2026-09-13.md`) is taken as mature; this document maps the
OWASP GenAI Security Project's *A Practical Guide for Secure MCP Server Development* (v1.0,
February 2026) onto that architecture, decides section by section whether each recommendation
applies to this deployment, and records what changed as a result. Like every file in
`docs/audits/`, it is dated evidence and is not edited retroactively.

**Primary sources, retrieved 2026-09-14 with Firecrawl (paid tier).**

| Source | URL | Retrieval |
|---|---|---|
| OWASP landing page | https://genai.owasp.org/resource/a-practical-guide-for-secure-mcp-server-development/ | `firecrawl scrape --format markdown,links`; the guide is the `Download` link (`/download/52676/`) |
| OWASP guide, complete | the `Download` link above (PDF) | `firecrawl scrape` of the PDF → 20,398 B of markdown, verified complete (title page, licence, TOC, all eight sections, minimum-bar checklist, acknowledgements, sponsors, supporters). A direct `curl` of the same link returned an HTML page, not the PDF; the Firecrawl parse is the copy used. |

Every retrieval above is archived verbatim under `docs/audits/audit-evidence/scrapes/`, with
its byte count, timestamp and method in that directory's `manifest.json` — including the failed
`curl`, so the record shows why the Firecrawl parse is the copy quoted. The OWASP guide is
licensed CC BY-SA 4.0 and is kept whole, licence block included.

| Archived as | Source |
|---|---|
| `owasp-mcp-guide-landing.md` | the landing page |
| `owasp-secure-mcp-server-development-v1.md` | the guide |
| `mcp-security-best-practices.md` | the MCP best-practices page |
| `mcp-transports-spec.md` | the MCP transports specification |
| MCP security best practices | https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices (served as the `2026-07-28` revision) | `firecrawl scrape --only-main-content`, 46,902 B |
| MCP transports specification | https://modelcontextprotocol.io/specification/2025-06-18/basic/transports | `firecrawl scrape --only-main-content`, 15,609 B |

Page numbers below are the guide's own (TOC: Introduction p. 4, Landscape p. 5, §1 p. 6,
§2 p. 7, §3 p. 8, §4 p. 9, §5 p. 10, §6 p. 11, §7 p. 12, §8 p. 13, Minimum Bar p. 14). No
secondary source was used as evidence.

**Result.** The OWASP guide is adopted as the principal external baseline (`SECURITY.md`
§ External Baselines). Of its 49 recommendations as itemised below, 21 apply and are covered
or exceeded by an existing control, 8 apply in part, and 20 do not apply to a local
single-operator deployment or to an architecture that removes the condition they address.

Mostly this was a documentation recalibration, as expected. Three things were not:

1. **Invariant 11, new.** Argument validation against `inputSchema` on the MCP transport was
   true only as an SDK default and had no test — while `mcp` is the one dependency with a hard
   ceiling, precisely because 2.0 removes the decorator that carries that default. Now stated
   explicitly in `build_server` and held by `tests/security/test_tool_input_validation.py`
   (§ Phase 3 B).
2. **Invariant 10, widened: an SSE bearer token.** Loopback binding and Host/Origin validation
   stop the browser and the LAN, not another process on the machine. This was first written up
   here as an accepted residual with the fix "presented for the owner's decision", on the
   assumption that existing SSE clients would break. The review checked the assumption instead
   of repeating it: there are no SSE consumers, and the SDK's own client already accepts
   headers. Implemented the same day (§ Phase 3 A).
3. **Filesystem paths in model-facing messages.** OWASP §6 lists them beside tokens; the Flex
   import's refusal spelled out the operator's home directory, something the 2026-07-11 audit
   had noticed and left. One function, `redaction.collapse_home`, now serves both surfaces.

One composition risk is recorded as investigated, reachable and accepted (§ Phase 3 E).
Everything else the guide asks for is either already held, held more strongly, or does not
apply; the rejected items and their reasons are listed at the end, so a later reader can tell a
decision from an oversight.

---

## The deployment model this is read through

The canonical statement of this is `docs/security-architecture.md` § 1, with the control-level
summary in `SECURITY.md` § Security Scope and Deployment Model. Repeated in brief here because
every applicability call below turns on it.

One operator; one personal macOS workstation; local processes only. The IBKR Client Portal
Gateway runs on the same machine (Docker, published on loopback only). The MCP server runs as
the operator's own process because two of its controls cannot run anywhere else: Gate 1 is
Touch ID on that machine, Gate 2 is a dialog on that screen, and the IBKR session is read
from that user's browser cookie store. The natural trust path is the stdio transport, where
the client is the process that spawned the server. `--transport sse` is optional and binds
`127.0.0.1`. There is no public endpoint, no second tenant, no delegated identity, no
service account shared between users, no Kubernetes, no marketplace of third-party tools:
the tool set is the installed package version.

Consequently an OWASP recommendation is a gap here only if the failure class it names is
reachable in that picture. "NOT APPLICABLE — deployment model" and "NOT APPLICABLE —
architecture removes the condition" are conclusions, not deficiencies.

---

## Phase 1 — Applicability matrix

Legend. *Relevant here?*: YES · PARTIAL · NO-D (deployment model) · NO-A (architecture removes
the condition). *Gap?*: covered · stronger (the existing control exceeds the recommendation)
· partial · defense in depth · confirmed missing · n/a. Evidence names the mechanism and the
test that holds it; invariant numbers are `docs/security-architecture.md` § 5.

### Current Vulnerability Landscape (p. 5)

| OWASP item | Relevant? | Existing control | Evidence | Gap? | Action |
|---|---|---|---|---|---|
| Tool poisoning (hidden instructions in prompts or tool metadata) | YES | Tool descriptions are source-controlled text in `claude_tools.TOOL_DEFINITIONS`; the injection vector that exists is web content, which is trusted for nothing and flagged by `assess_quality` when thin or blocked | `SECURITY.md` § Threat Model; `docs/security-architecture.md` § 1 | covered | none; composition of that vector with fetch tools is § Phase 3 E |
| Dynamic tool instability ("rug pulls") | NO-A | No dynamic or third-party tool loading; the registry is the installed package (`pip install …@vX.Y.Z`) | `mcp_server._ALL_TOOL_DEFS` is a module constant; invariant 3 holds dispatch and definitions equal | n/a | none |
| Code injection & unsafe execution | YES | RestrictedPython + attribute allowlist + spawn child + watchdog (inv. 4); no shell, three spawn sites (inv. 8); identifier regexes (inv. 9); bound SQL parameters | `test_sandbox_boundary.py`, `test_subprocess_boundary.py`, `test_client.py` | stronger | none |
| Credential leakage & token misuse | YES | `redact_error` on every model-facing or logged exception (inv. 6); `repr=False` on keys; token files 0600; `gitleaks` in CI; unit tests cannot see `.env` (inv. 7) | `test_error_redaction.py`, `test_no_live_io.py`, `.gitleaks.toml` | covered | none |
| Excessive permissions | YES | Capability declaration on all 46 tools from a vocabulary that cannot spell `ORDER_EXECUTION`; the honesty test derives each handler's sinks from its source (inv. 3) | `test_tool_capabilities.py` | stronger | none |
| Insufficient isolation — compute | YES | Model-written code runs in a spawn child with the operator's uid and the allowlist as boundary; OS-level sandbox is the documented next layer | `docs/security-architecture.md` § 6.3, § 9 | covered (known limit recorded) | none |
| Insufficient isolation — session, identity | NO-D | One principal; no per-user data exists to leak between sessions | § Phase 3 G | n/a | none |

### §1 Secure MCP Architecture (p. 6)

| OWASP item | Relevant? | Existing control | Evidence | Gap? | Action |
|---|---|---|---|---|---|
| Local servers: prefer STDIO | YES | stdio is the default transport and has no HTTP surface | `mcp_server.main`, `docs/mcp-server-reference.md` | covered | state the preference explicitly in `SECURITY.md` (done) |
| Local HTTP: bind only 127.0.0.1 | YES | `uvicorn.Config(host="127.0.0.1")` | `mcp_server._run_sse` | covered | none |
| Local HTTP: validate the Origin header | YES | `TransportSecuritySettings` with loopback-only `allowed_hosts`/`allowed_origins`; the SDK validates on both `GET /sse` and `POST /messages/` (inv. 10) | `test_transport_security.py`; `mcp/server/sse.py` `validate_request` on both handlers, verified 2026-09-14 | covered | none |
| Local HTTP: "still utilize explicit authorization/authentication" | YES | `_BearerTokenGate`: every request to `/sse` and `/messages/` must present this launch's `secrets.token_urlsafe(32)`, written 0600 to `~/.ibkr_core/mcp_sse_token` and never printed; checked with `hmac.compare_digest` before Host/Origin (inv. 10) | `test_transport_security.py`: 11 bearer cases, both routes | **confirmed missing on the day; fixed the same day** | **implemented** (§ Phase 3 A) — first deferred as an accepted residual, then implemented once the premise for deferring turned out to be false |
| Run the server in an isolated subprocess or container with minimal privileges | NO-A | The server must run as the operator (Touch ID, the dialog, the cookie store); what *is* isolated is the model-written code | § 6.3 | n/a | none |
| Remote: TLS 1.2+, strict JSON-RPC schema validation | NO-D | No remote transport; JSON-RPC parsing is the SDK's pydantic models | — | n/a | none |
| Trusted client connections: allowlists / mTLS / OAuth 2.1 for dynamic clients | YES | stdio: the client is the parent process — a hard-coded static relationship, which is the first option OWASP lists. SSE: the per-launch bearer token, above | `mcp_server.main`; `_BearerTokenGate` | covered | none; the clients are not dynamic, so OAuth buys nothing a per-launch secret does not |
| Isolate users and sessions; no globals for user-specific data | NO-D | One principal. The toolkit's process-wide lazy singletons (`_crawl4ai`, `_web_docs`, `_contract_identity`) hold no per-user data | `ClaudeToolkit.__init__`; § Phase 3 G | n/a | none |
| Strict lifecycle management (flush handles, temp storage, cached tokens on session end) | NO-D | Nothing is cached per session; `OrderWriteAuthorization` is frame-local and expires in 300 s | `human_auth.py` | n/a | none |
| Per-session resource quotas | NO-D | The bounds that exist are per operation, not per session: sandbox 10 s / 4,096 chars; crawl ≤ 100 pages, depth ≤ 5; seeder ≤ 1,000 URLs; IBKR rate limiter 10 rps; Flex polls ≤ 5 | `backtest.py:23-24`, `local_browser.py:704-705, 78`, `rate_limiter.py` | n/a | none |

### §2 Safe Tool Design (p. 7)

| OWASP item | Relevant? | Existing control | Evidence | Gap? | Action |
|---|---|---|---|---|---|
| Cryptographic tool manifests, verified at load time | NO-A | There is no load-time trust decision: tools are code in the installed package, integrity is the git tag the operator pinned | — | n/a | none; reconsider only if dynamic or third-party tool loading is ever introduced |
| Strict onboarding: SAST, dynamic testing, SCA, manual review | YES | ruff `S`, CodeQL default setup, the `ast` tests (SAST-shaped); live suites (`test_web_tools_live.py`, `test_client_live.py`) as dynamic testing; `pip-audit` (SCA); fresh-eye review as a standing step | `.github/workflows/ci.yml`; CLAUDE.md | covered (single maintainer; review is a practice, not a gate) | none |
| Validate descriptions vs. behaviour; flag a tool performing actions not in its description | YES | `test_every_sink_a_handler_touches_is_declared` reads each handler's source and requires every sink to be declared; `ToolAnnotations` derive from the same set | `test_tool_capabilities.py` | stronger (mechanical, from source, on every run — OWASP asks for manual checks and LLM scans) | none |
| Tool structure validation: expose only minimal fields to the model | YES | `ClaudeToolkit.tools` strips `capabilities`; the model sees name, description, input schema | `test_the_schemas_handed_to_the_model_carry_no_capabilities_key` | covered | none |

### §3 Data Validation & Resource Management (p. 8)

| OWASP item | Relevant? | Existing control | Evidence | Gap? | Action |
|---|---|---|---|---|---|
| Resource usage limits, timeouts, isolated compute budgets | PARTIAL | See the quotas row of §1: per-operation bounds exist; per-session quotas do not apply | as above | covered for what applies | none |
| JSON Schema for every tool's inputs; reject non-matching requests | YES | MCP path: `call_tool(validate_input=True)` runs `jsonschema.validate` before the handler, now stated explicitly rather than inherited; every routed name is a listed tool, since the SDK validates no others. Anthropic-API path: handlers coerce and any exception becomes a fixed `_safe_error` sentence | mcp 1.29.0 `server.py`; `claude_tools.execute` | **was untested and SDK-implicit** | **`tests/security/test_tool_input_validation.py` added; invariant 11** |
| JSON Schema for every tool's outputs | PARTIAL | All 46 tools return unstructured text (`TextContent`); no tool declares `outputSchema`, so there is nothing to validate | `mcp_server.handle_call_tool` | partial by design | rule recorded in `SECURITY.md`: a future tool that returns structured content declares and validates an `outputSchema`; no schemas invented for text tools |
| Sanitize inputs and outputs against classic injection (XSS, SQLi, RCE) | YES | Bound SQL parameters; identifier regexes; no shell; HTML stripped from IBKR reply text before Gate 2; AppleScript literal escaping | `SECURITY.md` § Data Security; audit 2026-09-13 § D | covered | none |
| Enforce size limits on all outputs from tools | PARTIAL | Measured rather than assumed: `fetch_page` returns whole-page markdown with no cap (typical 5–35 KB; 144,125 characters is the largest recorded, `docs/web-scraper-reference.md` § 5); list outputs are capped (50 rows from `get_trades`' store branch, 20 from its CP-API-session branch, 50 from `get_pa_transactions`, 10 page URLs); the sandbox error channel is capped twice — 300 characters in the child, re-capped at 1,000 by the handler so a multi-violation RestrictedPython list survives whole | `claude_tools.py:1713, 1756, 2297, 2404, 3660`; `redaction._MAX_LEN`; `backtest.py:416` | partial by decision | no cap imposed: the page is untrusted at any size and a silent clip would hide content from the operator; revisit with explicit, marked truncation if a host reports context exhaustion |

### §4 Prompt Injection Controls (p. 9)

| OWASP item | Relevant? | Existing control | Evidence | Gap? | Action |
|---|---|---|---|---|---|
| Structured (JSON) tool invocation | YES | Native to both hosts; no free-text command path exists | `TOOL_DEFINITIONS` | covered | none |
| Human-in-the-loop for high-risk actions (e.g. MCP elicitation) | YES | Two gates inside `IBKRClient`: Touch ID then a dialog with an explicit button, before any network call (inv. 1) | `test_order_write_boundary.py` | stronger — the checkpoint is out-of-band and server-side; an MCP elicitation is answered through the client, which a compromised client could answer for the user | none |
| LLM-as-a-judge in a separate session for high-risk actions | NO-A | The high-risk action has a human judge; the package makes no model calls by design (CLAUDE.md § Conventions) | — | n/a | none |
| One task, one session (reset sessions on context switch) | NO-D | Client-side behaviour; the server holds no conversation state | — | n/a | none |

### §5 Authentication & Authorization (p. 10)

| OWASP item | Relevant? | Existing control | Evidence | Gap? | Action |
|---|---|---|---|---|---|
| OAuth 2.1 / OIDC mandatory for remote servers | NO-D | No remote server | — | n/a | none |
| Token delegation (RFC 8693); prohibit token passthrough | NO-A | The server receives no client token to delegate or pass through. It holds its own credentials (IBKR cookie read from the browser store, Flex token, Firecrawl key, Google OAuth) and no tool returns one | `auth.py`; `test_error_redaction.py` | n/a | none |
| Short-lived, scoped tokens, revalidated per call | NO-D | The IBKR session is IBKR's, re-read per client instantiation, 401 never retried; the Google refresh token is long-lived by Google's design and held at 0600 | `SECURITY.md` § Session Security | n/a | none |
| Treat sessions as state, not identity; re-check authorization before sensitive actions | YES | The SSE session id is transport state only; the one authorization in the system (`OrderWriteAuthorization`) binds to a human act and a body hash, not to a session | `human_auth.py`, `client._authorize_order_write` | covered (the SSE residual is §1's row) | none |
| Centralize policy enforcement | YES | One dispatch (`execute`), one capability registry, gates at the innermost call site | inv. 1, 3 | covered | none |

### §6 Secure Deployment & Updates (p. 11)

| OWASP item | Relevant? | Existing control | Evidence | Gap? | Action |
|---|---|---|---|---|---|
| Secrets in vaults; never in env vars, logs or code; never reachable by the LLM | NO-D (vault) / YES (rest) | Read once by `Config.from_env()`; `repr=False` on every key; never logged (`redact_error`); `gitleaks` in CI; unit tests cannot see them; no tool returns a config value. This machine's `.env` is 0600 (checked 2026-09-14) but that is the operator's doing — nothing in the package creates or enforces that mode, unlike the SQLite store, the Drive token and the new SSE token file, which it does hold | `test_no_live_io.py`, `.gitleaks.toml`, `store.py`, `gdrive_auth.py`, `mcp_server._issue_sse_token` | covered for what applies | none; a mode the package cannot enforce is not claimed as a control |
| Containerize and harden the server, non-root | NO-A | The server must run as the operator; the gateway *is* containerized, loopback-published, unprivileged, no host mounts | `SECURITY.md` § Docker Gateway Isolation | n/a | none |
| Network segmentation, firewall / NetworkPolicy | NO-D | Loopback binds are the local equivalent | — | n/a | none |
| Supply chain: version-pin and scan; signed images; AIBOM | PARTIAL | `pip-audit` per push and weekly over `[dev,server,scraper]`, `--strict`, reasoned ignores only; floors not ceilings by decision; GitHub Actions pinned to major tags, not SHAs | `ci.yml`; `security/pip-audit-ignores.txt` | defense in depth (Actions SHA-pinning) | **not done**: `gh secret list` is empty and every job has `permissions: contents: read`, so a compromised action gains a read-only token to a public repository; revisit the day CI holds a write-capable secret (a publish token). Signed images / AIBOM: n/a |
| CI/CD security gates that fail the build | YES | ruff → format → mypy strict → pytest incl. `tests/security/`; `dependency-audit`; `secret-scan`; the same four steps as a pre-push hook | `ci.yml`, `.githooks/pre-push` | covered | none |
| Safe error handling: no stack traces, tokens, paths, tool internals to the model | YES | `_safe_error` (type → sentence); `redact_error` (first line, secrets scrubbed by shape, home collapsed to `~`, 300 chars) (inv. 6); `collapse_home` also builds `_import_flex_file`'s refusal, the one model-facing path message not made from an exception | `test_error_redaction.py`, including the real handler's blocked-path message | **paths were a confirmed divergence; fixed** | **`redaction.collapse_home` added**; the 2026-07-11 audit had noted the disclosure and left it |

### §7 Governance (p. 12)

| OWASP item | Relevant? | Existing control | Evidence | Gap? | Action |
|---|---|---|---|---|---|
| Cryptographic signing and pinning of tools, dependencies, registry manifests | NO-A | See §2 manifests; dependencies: pip-audit plus floors, ceilings rejected (decision log 2026-09-13) | — | n/a | none |
| Security-focused peer review before any tool or major change goes live | PARTIAL | Single maintainer; the standing fresh-eye review and the structural tests (a reviewer that never forgets a boundary) | CLAUDE.md; memory | covered for a one-person repository | none |
| Audit logs of every tool invocation with parameters; field-level allowlists | NO-D | The MCP client's transcript is the operator's audit trail; the package logs failures only, through `redact_error` | § Phase 3 F | n/a by decision | no per-call log added |
| Non-human identity governance | NO-D | No NHI: one human, whose own credentials the process uses | — | n/a | none |

### §8 Tools & Continuous Validation (p. 13)

| OWASP item | Relevant? | Existing control | Evidence | Gap? | Action |
|---|---|---|---|---|---|
| SAST with MCP rules; Invariant MCP-Scan; SCA (`pip audit`, OSV) | YES | ruff `S`, CodeQL default, `ast` tests; `pip-audit --vulnerability-service osv` | `ci.yml` | covered; MCP-Scan (a tool-description scanner) not adopted — descriptions are source-controlled text | none |
| Runtime protections: seccomp, AppArmor, context-protector, mcp-watch | NO-A | macOS host; `sandbox-exec` for the backtest child is the documented next layer if the allowlist ever proves insufficient | decision log 2026-09-13 | n/a | none |
| Feed audit logs to a SIEM; real-time alerts | NO-D | — | — | n/a | none |
| OpenSSF Scorecard; monitor OSV | PARTIAL | OSV via pip-audit weekly; Scorecard not run (its checks — branch protection, SHA-pinning, fuzzing — are organisation-scale) | — | n/a | none |

### Minimum Bar checklist (p. 14) — where each line lands

| Checklist line | Disposition |
|---|---|
| 1. Remote servers use OAuth 2.1/OIDC; short-lived scoped tokens; no passthrough; centralized policy | NO-D / NO-A except "centralized policy", which holds. The local analogue of a short-lived scoped token is the per-launch SSE bearer, added 2026-09-14 |
| 2. Users, sessions, execution contexts isolated; no shared user state; cleanup and quotas | NO-D for users/sessions; compute isolation holds (inv. 4); per-operation bounds instead of quotas |
| 3. Tools signed, pinned, approved; descriptions validated against behaviour; minimal fields to the model | Signing NO-A; validation and minimal fields hold, mechanically (inv. 3) |
| 4. Messages, inputs, outputs schema-validated; sanitized, size-limited, untrusted; structured invocation; containerized non-root | Inputs: holds and is now tested (inv. 11); outputs: text only, rule for future structured tools; size: measured, no page cap by decision; containerized: NO-A |
| 5. Secrets in vaults, never exposed to the LLM; CI gates, audit logs, monitoring | Vault NO-D (redaction, gitleaks, `repr=False`, 0600 files the package does hold); never exposed holds; CI gates hold; audit log = the client transcript; monitoring NO-D |

---

## Phase 2 — Reconciling the previous MCP best-practices mapping

`SECURITY.md` carried a six-row table mapping the official MCP best-practices page's attack
classes onto this package. Reading the page as served today (`2026-07-28` revision) alongside
the OWASP guide:

| Former row | What the MCP section is actually about (2026-07-28 text) | OWASP relationship | Disposition |
|---|---|---|---|
| Confused Deputy | OAuth proxy servers skipping user consent when a static client ID is reused | The repository's meaning — the *model* as a deputy with no order path — is OWASP Landscape "Excessive Permissions" and §4 HITL. The MCP section is a distinct risk that does not arise here | Keep the control text; drop the MCP citation; re-home under the LLM boundary section |
| Token Passthrough | Forwarding a client's OAuth token to downstream APIs | OWASP §5 says the same and it does not apply (no client token). The repository had used the row for *error and payload* sanitization, which is OWASP §6 "Safe Error Handling" and §3 sanitization — a materially broader and better-fitting home | Re-home under error handling; drop the MCP citation |
| SSRF | Servers and server-side clients fetching attacker-influenced URLs; explicit notes on DNS TOCTOU, redirect targets, encoding tricks | OWASP has no SSRF section — the MCP page is the more specific source | **Keep the MCP citation** as the supporting reference for the SSRF controls |
| Session Hijacking | Renamed *State Handle Hijacking*: server-minted handles presented as arguments; the old text now lives only at the `2025-11-25` versioned URL | Neither applies: this server mints no handles and has one principal. OWASP §5 "sessions as state, not identity" states the general principle | Drop the mapping; keep the gateway-cookie controls under Session Security with a one-line note |
| Local Server Compromise | Client-side consent for one-click installs; servers meant to run locally SHOULD use stdio, and restrict HTTP with an authorization token or IPC | OWASP §1 local guidance says the same, more compactly; the MCP text adds the concrete "authorization token / unix socket" options | **Keep the MCP citation** beside OWASP §1 for the transport decision |
| Scope Minimization | OAuth token scopes: minimal, task-scoped access tokens | The repository had used it for tool-surface minimization, which is OWASP Landscape "Excessive Permissions" and §2 "minimal fields" | Drop the MCP citation |

Net: the OWASP guide subsumes four of the six rows for this repository's purposes and is
broader on two; the MCP page stays as the protocol-specific supporting reference for SSRF
and for local-transport hardening, and as the source of the transports specification's
security warning (Origin validation MUST, localhost bind SHOULD, authentication SHOULD).
The six-row matrix is replaced by one compact applicability summary in `SECURITY.md`; the
implementation details stay described once, in the sections that already held them.

---

## Phase 3 — The additive questions

### Phase 3 A — Transport and authentication

**stdio.** The client is the process that spawned the server and owns its pipes. No
authentication concept changes that: there is no third party to authenticate. OWASP §1
"prefer STDIO" and the MCP page's "use the stdio transport to limit access to just the MCP
client" both describe the shape already in place. Conclusion: documented as the preferred
transport.

**SSE.** Verified: uvicorn binds `127.0.0.1`; `TransportSecuritySettings` rejects a foreign
`Host` (421) and `Origin` (403) on both the `GET /sse` handshake and `POST /messages/`
(`mcp/server/sse.py` calls `validate_request` in both handlers); a loopback client with or
without a port passes. That closes the browser (DNS rebinding) and the LAN. It does not
close *another process on the same machine*: any local process — any user account, any
sandboxed app allowed to reach loopback — can `GET /sse`, read the session id from the
`endpoint` event, and drive all 46 tools. What it gets: account reads (positions, balances,
trade history, P&L), price-alert writes on the IBKR account, Drive and SQLite writes,
sandboxed compute, and web fetches from the operator's browser profiles. What it cannot get,
by construction: an order write (`ORDER_EXECUTION` has no spelling; invariant 1) or a
credential (no tool returns one; invariant 6).

Which attacker does an authentication step stop? An unprivileged local process that is
*not* the operator's MCP client. Malware running as the operator is already out of scope
(it has the cookie store, subject to the keychain prompt, and the `.env`); a second local
user account or a loopback-capable sandboxed app is in scope and today pays nothing to reach
the tool surface. OWASP §1 ("still utilize explicit authorization/authentication"), the MCP
page ("require an authorization token, use unix domain sockets") and the transports
specification ("SHOULD implement proper authentication for all connections") all name the
control.

**First conclusion, and why it was wrong.** This section originally recommended a per-launch
bearer token but stopped short of implementing it, on the ground that it "changes what every
SSE consumer must send" and that the consumers should be checked first. That was a deferral
dressed as a finding: the check was one grep, and the answer is that there are no consumers.
`claudia_ui` states outright that it does not run this server
(`docs/trading-data-reference.md`); Claude Desktop and Claude Code use stdio; no launch agent
starts it; the only "consumers" named anywhere are the generic words "dashboard and chatbots"
in `docs/mcp-server-reference.md`, with no program behind them. And the SDK's own
`mcp.client.sse.sse_client` already takes `headers=`, so even a future consumer costs one
line. The standing rule in this repository is to fix rather than document where a fix is
feasible, and the cost here was zero.

**Implemented, 2026-09-14, test-first.** `tests/security/test_transport_security.py` gained
eleven cases (absent, empty, wrong, prefix-of-real, case-altered scheme, bare token, wrong
scheme; both routes; token-before-Host; a valid token reaching the SDK's own check; and the
signature carrying no default) — all red first. Then:

| Piece | Decision |
|---|---|
| Token | `secrets.token_urlsafe(32)`, fresh per launch — nothing to configure or rotate, and it dies with the server |
| Storage | `~/.ibkr_core/mcp_sse_token`, 0600, in the directory `SQLiteStore` already holds at 0700. Only the path is logged. Not printed: a terminal is scrolled, screen-shared and often captured |
| Scope | The whole app. Gating only `/messages/` would leave `/sse` — which hands out the session id — open |
| Comparison | `hmac.compare_digest` over the whole header value, scheme included |
| Order | Before the SDK's Host/Origin check, so an unauthenticated caller learns nothing about the loopback policy |
| Mechanism | `_BearerTokenGate`, pure ASGI. A Starlette `BaseHTTPMiddleware` buffers the response and would break the event stream |
| Signature | `build_sse_app(server, token)`, token required — the same reasoning that removed `ORDER_EXECUTION` from the capability vocabulary rather than asserting nobody declares it |

Invariant 10 is widened to name it. What the token does not defend against: code running as
the operator, which can read the file — the same boundary as the `.env` and the browser cookie
store. A unix socket would be the stronger answer if a consumer ever cannot send a header;
the SDK's SSE transport does not offer one today.

### Phase 3 B — Tool input validation

Question: can malformed MCP arguments reach `_dispatch()` or a privileged handler? On mcp
1.29.0, no: `Server.call_tool()` defaults to `validate_input=True` and runs
`jsonschema.validate(arguments, tool.inputSchema)` before the registered function, returning
`isError` with "Input validation error: …" on failure (verified in the installed SDK source
and by test). `build_server` registers with the bare decorator, so the default applies.

Does the guarantee depend on SDK behaviour that could change? Yes, and that dependency was
already known in another form — `pyproject.toml` caps `mcp<2` because 2.0 removed the very
decorator that carries the default. No existing test sent a malformed argument, so a port
that lost validation would have stayed green. `tests/security/test_tool_input_validation.py`
now drives four malformed argument sets (wrong type, missing required, enum violation, wrong
type on a server-local tool) through the real request handler and asserts the handler is
never reached; a well-formed set is; the decorator carries no `validate_input=False`
(structural); and a guard-on-the-guard proves the probe fires when validation is switched
off. No second validation framework was added.

The Anthropic-API path (`ClaudeToolkit.execute`) has no schema step and never did; handlers
coerce (`str(inputs.get(...))`, `int(...)`) and any exception is one fixed sentence. That is
adequate for its failure class (a wrong type becomes a controlled error, never an unhandled
one) and is covered by the handler tests.

### Phase 3 C — Tool behaviour and trust

Verified: every one of the 46 definitions declares a non-empty capability set from the
vocabulary; the honesty test derives each handler's sinks from its own source (client writes,
store writes, cache writes, sandbox, browser, seeder, Firecrawl, Flex) and fails on an
undeclared one; `ToolAnnotations` derive from the same set; `ORDER_EXECUTION` is not a legal
spelling; there is no dynamic loading. This is **stronger than OWASP §2's manifest guidance**
for a static tool set: a signed manifest attests that a description has not changed since
signing; the honesty test attests, on every run, that the *code* does not touch a sink the
declaration omits. Signed manifests are not implemented and should not be while tools are
static and source-controlled.

### Phase 3 D — Tool output validation

1. *Structured-output schemas*: none of the 46 tools returns structured content, so there is
   no `outputSchema` to validate; the SDK would validate one if declared. Rule adopted: a
   future tool that returns structured content declares and validates an `outputSchema`.
2. *Semantic validation*: the web tools already refuse or flag output that is not what it
   claims to be (`assess_quality` — a 44-byte 403 is not "one page saved"). That is the
   semantic check that matters here; nothing added.
3. *Size*: measured, not assumed — see the §3 row. No cap; revisit with explicit, marked
   truncation if a host reports context exhaustion.
4. *Hostile external content*: trusted for nothing, returned to the model as content, flagged
   when thin or blocked; the package never parses it as instructions. The composition
   consequence is E.
5. *Secret redaction*: invariant 6, unchanged.

### Phase 3 E — Chained tool / capability composition

Question: can individually permitted tools compose into something more privileged than any
declaration suggests? Concretely, under prompt injection from a fetched page:

| Chain | Reachable? | Effect | Bound |
|---|---|---|---|
| `fetch_page` (hostile page) → `get_positions` / `get_account_summary` / `get_trades` / `get_pnl` → `fetch_page` / `crawl_site` / `search_site` with the data in the URL, or `firecrawl_search` with it in the query | **Yes.** Every step is a permitted tool; the fetch tools accept any public host | Exfiltration of account data (positions, balances, history) to an attacker-chosen host | No credential leaves (no tool returns one); no order is placed; the destination must be public (SSRF guard) |
| hostile page → `create_price_alert` / `delete_alert` / `activate_alert` | Yes | Nuisance changes to IBKR-side alerts, visible to the operator | `ACCOUNT_STATE`, ungated by design; no financial effect |
| hostile page → `delete_cache` / `crawl_site` (Drive writes) | Yes | Cache deletion; hostile content archived to Drive and re-read later (stored injection) | Content stays untrusted on re-read |
| hostile page → `run_backtest` | Yes | Sandboxed compute only | Invariant 4 |
| hostile page → `import_flex_file` | Yes, path under `~/.ibkr_core` only | Re-import of the operator's own archive | Path-under-root check |
| any chain → an order write | **No** | — | Invariant 1 |

The first row is the classic private-data + untrusted-content + outbound-channel triad, and
it is real. It is not closable inside this package without breaking the web tools: any
public URL can carry data, and a query-string or length filter is trivially routed around.
The controls are (a) what the chain *cannot* reach — credentials and order execution — which
are the two invariants the suite holds; (b) every fetch tool carries `openWorldHint=true`,
derived from its declaration, so an MCP client that gates confirmation on hints prompts
before the outbound step; (c) the operator sees the URL in the client transcript. Recorded
as **investigated, reachable, accepted** in `SECURITY.md` and `docs/security-architecture.md`
§ 9, so a future reader does not mistake the capability registry for a composition control.
No hypothetical chains beyond the table were invented.

### Phase 3 F — Auditability

Current logs: `claude_tools` logs failures (`log.warning` through `redact_error`);
`mcp_server` logs resource failures and stream reconnects; there is no per-invocation log.
OWASP §7 asks for every invocation with parameters. For one operator whose MCP client
renders every call and result in the conversation, that transcript *is* the audit trail;
a package-side log with parameters would duplicate it and would carry model-supplied URLs
and file paths into a log that `redact_error` does not cover. A parameter-free line
(timestamp, tool, capabilities, ok/fail, elapsed) would add debugging convenience only.
Decision: not added; the reasoning is in the decision log.

### Phase 3 G — Session isolation

Checked the four local concerns. *Stale authorization state*: none persists —
`OrderWriteAuthorization` is frame-local and expires closed. *Mutable privilege objects*:
none exist beyond that value. *State shared between MCP connections*: one `Server` and one
`ClaudeToolkit` serve every SSE session; the shared state is a browser handle, a Drive
client, and a conid→identity cache, all belonging to the one operator. *One client
influencing another*: only through that shared state, which holds nothing sensitive; the
documented hazard (unlocked lazy singletons under a multithreaded host) is a correctness
note, not an isolation one. Conclusion: NOT APPLICABLE — deployment model; nothing built.

### Phase 3 H — Supply chain

Compared: `pip-audit` (`--strict`, OSV, every extra, per push and weekly, reasoned ignores
only) against OWASP §6/§8 — matches, including the guide's own example tool. `gitleaks` —
covered. Static registry — covered (C). GitHub Actions — tag-pinned (`checkout@v5`,
`setup-python@v6`, `gitleaks-action@v2`), not SHA-pinned. SHA-pinning closes a distinct
class (a moved tag). Its value here is bounded by what a compromised action could take:
`gh secret list` returns nothing, every job runs with `permissions: contents: read`, and the
repository is public — the token is worth nothing. Not done; revisit the day CI holds a
write-capable secret. SBOM/AIBOM/signing: not applicable.

---

## Phase 4 — A new invariant?

Question: does the baseline expose a consequential property that could silently become false
while the suite stays green? One: MCP argument validation (B).

It was first folded into invariant 9 to avoid renumbering. That was wrong on its own terms.
Invariant 9 is specifically about path-interpolated identifiers in `client.py`; the two
properties fail independently, are held by different files, and have different change recipes,
so one row would have carried two mechanisms, two enforcements and two recipes joined by
semicolons — and the "ten invariants" wording elsewhere would have hidden a property rather
than named it. It is **invariant 11**:

> 11. On the MCP transport an argument set that fails the tool's `inputSchema` never reaches a
> handler.

Its mechanism is the SDK's `call_tool(validate_input=True)`, now written out explicitly in
`build_server`, plus the second fact the property rests on: the SDK validates only tools it has
listed (`if validate_input and tool`), so every name `_dispatch` routes must be a listed tool —
asserted in the same file.

The SSE bearer token is **not** a new invariant either: it is the same boundary invariant 10
already names, so invariant 10 is widened to "validates `Host` and `Origin`, and admits only
the holder of this launch's bearer token".

The composition channel (E) is not an invariant: no property of the package flips when it is
exploited — every tool behaves as declared — and the enforcement point (per-call approval)
lives in the client. It is a documented known limit.

---

## Changes made in this pass

| File | Change |
|---|---|
| `ibkr_core_mcp/mcp_server.py` | `_BearerTokenGate` (pure ASGI) and `_issue_sse_token`; `build_sse_app` takes a required `token`; `validate_input=True` stated explicitly |
| `ibkr_core_mcp/redaction.py` | `collapse_home`, applied by `redact_error` before the length cap |
| `ibkr_core_mcp/claude_tools.py` | `_import_flex_file`'s refusal names the root through `collapse_home` |
| `tests/security/test_transport_security.py` | Eleven bearer-token cases added; existing Host/Origin cases now send the token, as a real client does |
| `tests/security/test_tool_input_validation.py` | New: 9 tests — 4 malformed sets never reach `_dispatch`, 1 well-formed does, no package call passes `validate_input=False`, every routed name is a listed tool, and the probe reaches the handler for all 4 sets with validation off |
| `tests/security/test_error_redaction.py` | Three canaries: the home directory collapses, the real blocked-import message carries no username, a pathological `HOME=/` is left alone |
| `tests/security/structural.py` | `keyword_literal_lines`, the general form of `shell_true_keywords`, so the `validate_input=False` scan is a proven checker rather than inline AST |
| `SECURITY.md` | New § Security Scope and Deployment Model; § External Baselines replaces the six-row MCP mapping; § MCP Transports gains the token; input/output validation and the composition channel stated; MCP citations kept only where that page is the more specific source (SSRF, local transport hardening); suite table, defence-in-depth rows and contributor rules 12–14; audit-history row |
| `docs/security-architecture.md` | Principal row for another local process; invariant 10 widened and 11 added (§ 5, and the counts in § 7); § 6.6 rewritten; § 8 decisions dated 2026-09-14; § 9 known limits; § 11 cross-reference |
| `docs/external-docs-reference.md` | The OWASP guide and the two MCP pages as official security references |
| `docs/mcp-server-reference.md` | § SSE bearer token, with the client snippet |
| `docs/audits/audit-evidence/scrapes/` | The four retrievals above, plus manifest entries |
| `CLAUDE.md`, `docs/README.md`, `CHANGELOG.md` | Pointer to this document; invariant counts; Gate 2's dialog named correctly; a changelog pointer re-aimed at the design doc that still holds the mechanism |

## Rejected in this pass, with the reason

- Signed tool manifests — no load-time trust decision exists (C).
- OAuth / token-based client authentication on stdio — no third party to authenticate (A).
- Output schemas for text tools — nothing to validate; rule for future structured tools (D).
- An output size cap — measured; a silent clip hides content; revisit with a marked truncation (D).
- Per-invocation audit log — the client transcript is the trail; would log model-supplied text (F).
- Session/tenant isolation machinery — one principal (G).
- SHA-pinning GitHub Actions — no CI secret to protect; revisit when there is one (H).
- Hoisting the duplicated `toolkit`/`store` fixtures and a shared request-dispatch helper across
  the test files — real duplication, pre-dating this pass and not caused by it; out of scope for
  a security recalibration and better done as its own change.
- SBOM / AIBOM / image signing, SIEM, seccomp/AppArmor, OPA, MCP-Scan, OpenSSF Scorecard — deployment model or platform.
