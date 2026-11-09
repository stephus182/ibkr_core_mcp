# MCP security checklist — first pass against this package (2026-11-09)

**Status: first pass, written between step 1 and step 2 of register F45; a deeper dive is
planned.** Point-in-time record, not retroactively edited. Every answer below names the file
or test that makes it true, or says plainly that it is not true here.

**Source.** An enterprise MCP security checklist shared by the operator on 2026-11-09: four
framing questions and 29 items in eight sections, each item carrying a best practice, an
expected risk if not complied with, the deployment patterns and server provenances it applies
to, and an importance score from 2 to 4. The questions are transcribed in condensed form; the
best-practice and risk columns are summarised, not reproduced; the organisation named in one
item's wording is not reproduced (this repository is public).

**How this package reads against the checklist's own axes.**

| Axis | This package |
|---|---|
| Deployment pattern | **Local workstation.** One operator, one personal machine. stdio is the default transport (the client is the process that spawned the server); `--transport sse` is optional, binds `127.0.0.1`, validates `Host`/`Origin` and requires a per-launch bearer token. The one network service is the IBKR Client Portal Gateway, in a Docker container published on loopback only |
| Server provenance | **Built internally** (MIT, public repository) on **open-source dependencies** from PyPI, with **one vendor component**: IBKR's Client Portal Gateway zip, downloaded at image build from IBKR's distribution server |
| Users | One human operator; one model (Claude, through `ClaudeToolkit` in the host application or any MCP client over stdio). No external users, no service accounts, no second tenant |
| Sensitivity | A live brokerage account — positions, trades, P&L, the IBKR session cookie — plus the Flex token, the Firecrawl key and the Google Drive OAuth token. Order writes need a fingerprint and a click (`SECURITY.md` § Two-Gate System) |

The principal external baseline stays OWASP's *Practical Guide for Secure MCP Server
Development* v1.0 (`owasp-mcp-guide-applicability-2026-09-14.md`); this checklist is read
beside it, and where the two ask the same question the earlier mapping's answer is cited.

**Answers.** YES = held, with the test or file named. PARTIAL = held in part, the gap named.
NO = not held; where that is a dated decision the decision is cited. N/A = the item presumes a
deployment this is not (a remote transport, enterprise identity, several tenants, a SOC); each
N/A names the condition that would make it apply.

| | YES | PARTIAL | NO | N/A | Total |
|---|---|---|---|---|---|
| Items | 4 | 16 | 2 | 7 | 29 |
| Of which scored 4 | 2 (6.1, 6.2) | 1 (4.5) | 0 | 3 (4.2, 4.4, 4.6) | 6 |
| Of which scored 3 | 0 | 9 | 1 (8.1) | 1 (4.1) | 11 |

## 0. Framing questions

| ID | Question | Answer |
|---|---|---|
| 0.0 | Make or buy? Vendor and ownership | **Make.** Built and owned by the operator (public repository, MIT). Dependencies are open source from PyPI, audited by `pip-audit` per push and weekly. The one bought component is IBKR's gateway, downloaded over HTTPS at image build with no separate checksum (`SECURITY.md` § Supply Chain — Dockerfile, accepted) |
| 0.1 | Users and user types | One human operator on one workstation, and one model. The model is a principal trusted for reads, analysis and *proposing* orders, never for executing one (`docs/security-architecture.md` § 1). No external, privileged or service users |
| 0.2 | Tools and the actions they enable | 44 tools through `ClaudeToolkit`, 46 through the MCP server (two local price-alert tools); every one carries a `capabilities` set from a vocabulary in which `ORDER_EXECUTION` has no spelling. The full table: `SECURITY.md` § No order writes in the tool surface; tiers: `docs/security-architecture.md` § 2 |
| 0.3 | Security rating and sensitivity | The operator's call. The data is a live brokerage account and three credentials; the controls are those of `SECURITY.md`, held by `tests/security/` (thirteen invariants) |

## 1. Origin & Integrity

| ID | Question (condensed) | Score | Answer | Evidence · gap |
|---|---|---|---|---|
| 1.1 | Has the MCP server vendor completed the enterprise third-party risk process? | 2 | **N/A** | No vendor MCP server: built internally. The one vendor component (IBKR's gateway zip) is fetched over HTTPS from IBKR's own server without a checksum, an accepted risk in the class of `pip install` without a verified hash (`SECURITY.md` § Supply Chain). Applies if a third-party MCP server is ever federated |
| 1.2 | Installed from a trusted source, authenticity verified, unverified software prevented? | 3 | **PARTIAL** | Releases go to PyPI by Trusted Publishing from `publish.yml`, behind a reviewed `pypi` environment and a `v*` tag rule (`docs/security-architecture.md` § 7 Publishing); **PyPI holds a PEP 740 provenance attestation for the 2.1.0 wheel and sdist** (checked 2026-11-09 against `pypi.org/integrity/…/provenance`: one bundle, GitHub publisher `stephus182/ibkr_core_mcp`, workflow `publish.yml`). The consumer pins one exact version and compares the artifact with its git tag (`core-ref.txt` records the method). **Gaps:** the attestation is not verified at install time (pip does not; a `pypi-attestations verify` step in the consumer's CI would); pinned by version, not content digest (a PyPI artifact is immutable, so the gap is the comparison, not the pin) |
| 1.3 | SBOM maintained, automated CVE scanning, hash-pinned dependencies, build blocked on critical CVEs? | 3 | **PARTIAL** | `pip-audit --strict` over a **fresh resolve** of `.[dev,server,scraper]`, per push and weekly, blocking on every fixable finding; no-fix findings only in `security/pip-audit-ignores.txt` with a reason and a re-check date (`ci.yml` `dependency-audit`); Dependabot alerts on the manifest; `gitleaks` on the pushed range. **Gaps:** no SBOM artifact (SPDX/CycloneDX); dependencies are version floors, not hashes — deliberate (`docs/security-architecture.md` § 8, 2026-09-13: "no dependency ceilings"), and a hash-pinned lock for CI would not contradict it |

## 2. Application Security

| ID | Question (condensed) | Score | Answer | Evidence · gap |
|---|---|---|---|---|
| 2.1 | Manual secure code review with MCP-specific coverage (input typing, tool hints, auth discovery)? | 2 | **PARTIAL** | Six dated security reviews (`SECURITY.md` § Audit History: 2026-05-25 → 09-17), the 2026-09-13 architecture audit that produced `tests/security/`, the 2026-09-16 release-readiness audit (175 findings, each with its closing test). MCP-specific: every argument set is validated against the tool's `inputSchema` before a handler runs (invariant 11); `readOnlyHint`, `destructiveHint` and `openWorldHint` are derived from each tool's capability set (`mcp_server.py`; `idempotentHint` is not set); every path-interpolated identifier is validated (invariant 9). `.well-known` authentication discovery: N/A, no OAuth. **Gap:** the reviewer is the maintainer, with model-driven audits — no independent AppSec sign-off |
| 2.2 | SAST, DAST, SCA, secret scanning, container scanning in CI with blocking thresholds? | 3 | **PARTIAL** | Blocking: `ruff` with the flake8-bandit `S` rules (SAST-lite), `pip-audit` (SCA), `gitleaks` (secrets), the thirteen structural security tests. Reporting only: CodeQL default setup (structurally blind to tool inputs, § 7). **Gaps:** no DAST — nothing is exposed by default; no image scan of the gateway image (`eclipse-temurin` + IBKR's zip) — a `trivy`/`grype` step is cheap |
| 2.3 | Penetration tests or red-team exercises on MCP-specific vectors (ATLAS, OWASP API/MCP)? | 2 | **PARTIAL** | Internal adversarial probing is the method here: 22 sandbox-escape forms against the attribute allowlist, a twenty-row SSRF table plus redirect-to-private against real Chromium, mutation runs on every guard (`docs/audits/security-architecture-audit-2026-09-13.md`); the read-then-fetch exfiltration chain under prompt injection analysed and accepted (`docs/security-architecture.md` § 8, 2026-09-14). **Gap:** no external penetration test, no MITRE ATLAS exercise |

## 3. Environment

| ID | Question (condensed) | Score | Answer | Evidence · gap |
|---|---|---|---|---|
| 3.1 | Sandboxed execution, TEE for highly sensitive data? | 3 | **PARTIAL** | The server runs as the operator on the workstation — by necessity: Gate 1 is Touch ID on that machine, Gate 2 a dialog on that screen, the IBKR session comes from that user's browser (§ 1). Model-written strategy code runs under RestrictedPython in a spawned child with an attribute allowlist, a watchdog and a bounded error channel (§ 6.3). The gateway runs in Docker on the default runtime, loopback-published. **Gaps, documented:** no OS-level sandbox for the server (§ 9, "the sandbox child runs as the operator"; `sandbox-exec` is the next layer if the allowlist proves insufficient), no gVisor, no TEE |
| 3.2 | Network segmentation, default-deny with an allow-list, admin behind IAM and MFA? | 3 | **PARTIAL** | Inbound: nothing listens by default; SSE is loopback with a bearer token; the gateway container is `-p 127.0.0.1:5055:5055` with an IP allow-list in `conf.yaml`. Outbound: the loopback gateway, the Flex Web Service on an allow-listed URL prefix, Google, Firecrawl — and **any public URL** through the four web tools, which is their purpose; private, loopback, link-local, reserved and shared ranges are refused in two layers (§ 6.4). **Gaps:** no default-deny egress (open world by design, `openWorldHint=true` on those tools); "admin" is the operator's OS account — a fingerprint for order writes, no IdP |
| 3.3 | Dev, test and prod strictly separated; no production data, secrets or identities in lower environments? | 2 | **PARTIAL** | One machine is both. What is separated is the test suite from production: a unit test cannot open a socket, resolve a name, see a credential, touch `~/.ibkr_core`, reach a person or start `docker`, `open` or `caffeinate` (invariant 7, `tests/conftest.py`'s doors, `test_no_live_io.py`, `test_no_real_data_io.py`, `test_no_human_reached.py`, `test_no_desktop_reached.py`). **Gap, by design:** the integration suite runs against the live account (`-m integration`, opt-in, run by hand) |
| 3.4 | Binds only to the minimal interface; unused listeners and debug endpoints disabled? | 2 | **YES** | stdio by default — no listener. SSE binds `127.0.0.1`, `TransportSecuritySettings` accepts loopback `Host`/`Origin` only (421/403), and `_BearerTokenGate` requires this launch's token on `/sse` and `/messages/` (invariant 10, `test_transport_security.py`). The gateway publishes on loopback only (`test_docker_run_binds_port_to_loopback_only`). No debug endpoint exists |
| 3.5 | Emergency shutdown / kill switch, tested quarterly, SOC-operable in minutes? | 2 | **PARTIAL** | The operator can end the server process, stop the container (`docker stop`), revoke the Drive token and rotate the `.env` secrets within minutes; the host application's gateway button and `python -m ibkr_core_mcp.gateway` give one place to act. **Gaps:** no SOC and no circuit breaker (single operator); no scheduled drill |

## 4. Authentication & Authorization

| ID | Question (condensed) | Score | Answer | Evidence · gap |
|---|---|---|---|---|
| 4.1 | OAuth 2.1 with PKCE, rotating refresh tokens, no implicit/password grants? | 3 | **N/A** | No remote client and no delegated identity: stdio's client is the spawning process; SSE admits the holder of a per-launch `secrets.token_urlsafe(32)` compared with `hmac.compare_digest` (§ 6.6). OWASP's § 5 (OAuth/OIDC) was classified not applicable on 2026-09-14 for the same reason. Applies if a remote transport is ever added — then OAuth, not a stronger token |
| 4.2 | End-user authentication delegated to the enterprise IdP with phishing-resistant MFA; local/anonymous auth disabled? | 4 | **N/A** | One operator, no IdP. The compensating controls are IBKR's own login and IB Key 2FA for the brokerage session, and Touch ID (`LAPolicyDeviceOwnerAuthentication`) once per order write. Applies with a second user |
| 4.3 | Access tokens short-lived (≤1 h), sender-constrained, replay-protected; refresh tokens rotated and revocable? | 3 | **PARTIAL** | The SSE token lives as long as the launch, in a 0600 file, never printed; the IBKR session is IBKR's and expires without activity (the keepalive exists to prevent that); the Drive refresh token is Google's library's, 0600. **Gap:** no sender constraint (DPoP/mTLS) — meaningful only for a remote transport |
| 4.4 | Token claims (aud, iss, scope, sub) verified server-side; foreign-audience tokens rejected? | 4 | **N/A** | No JWT is issued or accepted. The SSE token is compared whole, scheme included; `Host`/`Origin` must be loopback. The confused-deputy class is addressed where it exists here — the model as deputy: identifier regexes, path-under-root, the SSRF layers (`SECURITY.md` § The model as a confused deputy) |
| 4.5 | Roles and permissions managed centrally (OPA/Cedar/OpenFGA) and enforced at tool-parameter level, least-privilege defaults? | 4 | **PARTIAL** | Policy is code held by test, not an external engine: every tool declares a `capabilities` frozenset, `ORDER_EXECUTION` cannot be spelled, `READ_ONLY` is exclusive, and an honesty test derives each handler's real sinks from its source (invariant 3). Tool-parameter level: account/order/conid regexes, `_DELIVERY_OPTIONS`, path-under-root, input allow-lists (invariants 9, 11, 4). Least privilege: no order tool exists; the gateway package is model-unreachable (invariant 13, 2026-11-09). **Gap:** one principal, one policy — no central engine, no per-user roles; applies with a second principal |
| 4.6 | Multi-tenancy with strict isolation, validated by cross-tenant tests? | 4 | **N/A** | Single tenant by construction (`SECURITY.md` § Security Scope and Deployment Model). Applies if the package ever serves two accounts from one process |

## 5. Communications

| ID | Question (condensed) | Score | Answer | Evidence · gap |
|---|---|---|---|---|
| 5.1 | TLS ≥ 1.2 everywhere, weak ciphers and downgrade disabled? | 3 | **PARTIAL** | External connections (Flex, Google, Firecrawl, the web tools) use `requests`/`httpx` with Python's `ssl` defaults; nothing in the package lowers them, and nothing pins a minimum version or cipher policy either (`grep` 2026-11-09: one `ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)` in `streaming.py`, no `minimum_version`). The loopback gateway is TLS with a self-signed certificate (verification off, pinned to loopback). SSE is plain HTTP on loopback. **Deep dive:** measure the negotiated versions and set `TLSVersion.TLSv1_2` as the minimum on the one context that is ours |
| 5.2 | Certificates fully validated with no exceptions in production code; mTLS server-to-server? | 3 | **PARTIAL** | External connections are verified by default (chain, hostname, expiry; no OCSP/CRL beyond the platform's). **The exception exists by design and is held by test:** every function that disables verification pins its URL to `localhost`/`127.0.0.1`/`::1` on a line before it does, and the set of such functions is exactly the declared allowlist (`tests/security/test_tls_policy.py`, 2026-11-09; `SECURITY.md` § TLS Policy). No server-to-server links, so no mTLS |
| 5.3 | CSRF protections on HTTP/SSE transports (tokens, Origin/Referer validation, SameSite)? | 2 | **YES** | No cookie carries the SSE session; every request to `/sse` and `/messages/` must carry this launch's bearer token, and `Host`/`Origin` are validated against loopback before the SDK sees the request (invariant 10; `test_transport_security.py`: absent, wrong, prefix, case- and scheme-altered credentials → 401) |
| 5.4 | CORS restricted to an explicit allow-list; no wildcard, no credentials with wildcard? | 2 | **PARTIAL** | The MCP SSE application sets no CORS header at all (verified 2026-11-09: no CORS middleware in `mcp_server.py`), so a browser's same-origin policy applies and the token gate stands behind it. **The vendor component does not comply:** IBKR's gateway ships `cors.origin.allowed: "*"` with `allowCredentials: false`, kept as IBKR's default and mitigated by the credentials flag (`SECURITY.md` § conf.yaml). **Deep dive:** measure whether the login page still works with the origin restricted to `https://localhost:5055` |

## 6. Action Security

| ID | Question (condensed) | Score | Answer | Evidence · gap |
|---|---|---|---|---|
| 6.1 | Inputs and outputs validated against tool-parameter and classical injection (SQL, command, path traversal, SSRF)? | 4 | **YES** | Path identifiers by regex or named exemption (invariant 9); MCP arguments against `inputSchema` (11); SQL parameterised throughout `store.py`; XML through `defusedxml`; file paths resolved under `~/.ibkr_core` and domains through `_safe_domain`; URLs through two SSRF layers (5); processes list-form from three modules with constant arguments (8); strategy code behind an attribute allowlist (4); outputs through one redaction function (6) |
| 6.2 | Critical or irreversible actions behind non-bypassable human-in-the-loop confirmation with full context? | 4 | **YES** | Every order write — place, modify, cancel, reply, bracket, attach — runs Touch ID and then a dialog showing the full order, inside the client method, with no bypass flag and no cache (invariant 1; `test_order_write_boundary.py` drives each write with a denied gate and asserts no order request left). A dialog timeout sends nothing. The model has no order tool at all. MCP clients see `destructiveHint` derived from capabilities. **Note:** price alerts, watchlists and notification settings are ungated `ACCOUNT_STATE` writes by design — not financial, not irreversible (§ 2) |
| 6.3 | Resource limits: token budget, payload size, rate, recursion depth, loop bound? | 2 | **PARTIAL** | IBKR calls are paced per endpoint before sending and backed off on 429 (`rate_limiter.EndpointPacer`); strategy code is capped at 4,096 characters, 10 s with SIGKILL after, a 300-character error line (§ 6.3). **Gaps:** no payload or token cap on tool output — a measured decision (§ 8, 2026-09-14: pages are whole, 144,125 characters the largest on record); recursion depth and the agent loop belong to the host |

## 7. Secrets & Identities

| ID | Question (condensed) | Score | Answer | Evidence · gap |
|---|---|---|---|---|
| 7.1 | All secrets in a centralised vault; never in code, config files or environment variables? | 3 | **PARTIAL** | Never in code (`gitleaks` per push; `test_published_identifiers.py` over every tracked file); never in the process environment (invariant 12: `load_env_file` returns secrets as `SecretStr` and exports none; a `.env` accessible to group or others has its secrets refused); the SSE token and the Drive token are written 0600. **Gap:** the secrets live in a 0600 file, not a vault, and are not encrypted at rest — deferred by the operator on 2026-10-16 with the OS keychain as the candidate, and only `load_env_file` would change (§ 9) |

## 8. Monitoring & Audit

| ID | Question (condensed) | Score | Answer | Evidence · gap |
|---|---|---|---|---|
| 8.1 | Every action logged with timestamp, user, agent, client, tool, parameters, response summary, decision, correlation id, sensitive data redacted? | 3 | **NO** | A dated decision: "No per-invocation audit log — the client transcript is the operator's trail; a parameter log would carry model-supplied URLs and paths into a channel `redact_error` does not cover" (§ 8, 2026-09-14), revisit "a host without a transcript consumes the server". Python logging exists, redacted in the model layer and the gateway package (invariant 6). **Deep dive:** with the gateway owner joining the package (F45), a structured, redacted per-call record of order writes and session writes is the first candidate |
| 8.2 | Audit logs centralised in a SIEM, normalised, tamper-evident? | 2 | **N/A** | No SIEM: one operator, local logs. Applies with an operations team |
| 8.3 | Real-time alerting on MCP-specific anomalies? | 2 | **NO** | Nothing alerts on tool-call sequences, egress or authorization failures. The order path's "alert" is the human at the dialog. Applies more as the host grows; the gateway's refused-login detection (`preflight`, 2026-10-12) is the one anomaly surfaced today |
| 8.4 | Log access gated by RBAC with separation of duties? | 2 | **N/A** | One person. Applies with a second |

## What the first pass says, and what is next

- **No item scored 4 is a NO.** Two are YES (input/output validation; human-in-the-loop on every
  order write), one PARTIAL (centralised policy — here, policy as tested code for one principal),
  three N/A for a single-operator local deployment (IdP, token claims, multi-tenancy).
- **The two NOs are 8.1 (score 3) and 8.3 (score 2)**, both monitoring, one of them a dated
  decision. The sixteen PARTIALs split into gaps that are deliberate and documented (3.1, 3.2,
  3.3, 6.3, 7.1), gaps that are cheap to close in CI (1.2's attestation verification in the
  consumer's CI, 1.3's SBOM, 2.2's image scan), and gaps to measure before deciding (5.1's TLS
  minimum, 5.4's gateway CORS).
- **Deep dive, in this order** (score × gap): 8.1 a redacted per-call record of order and session
  writes; 1.2 + 1.3 attestation verification, an SBOM, a hash-pinned lock for CI; 2.2 a gateway
  image scan; 5.1 measure negotiated TLS and pin a minimum on our one context; 5.4 measure a
  restricted gateway CORS origin; 7.1 the keychain (the operator's deferral stands until asked).
  One sentence to re-verify on the way: § 8's 2026-09-14 row says GitHub Actions stay tag-pinned,
  while `ci.yml` pins `gitleaks-action` by SHA — one of the two is stale.
- **Method.** Each answer was checked against the file or test it names on 2026-11-09, on the
  `release/2.2.0` worktree at step 1 of F45; the PyPI attestation was read from PyPI's integrity
  endpoint, the CORS and TLS facts by grep of the source. Nothing was run against the live gateway.

## Follow-up, later the same day (2026-11-09, between F45's two steps)

The operator's call on the first pass: fix now, without overkill. Status changes, each with its
commit on `release/2.2.0`:

| Item | Was | Now | How |
|---|---|---|---|
| 5.1 TLS ≥ 1.2 | PARTIAL | **YES** | `IBKRWebSocket.connect` pins `minimum_version = TLSv1_2` on the one context the package builds, held in source by `test_tls_policy.py`; every other connection is `requests` over urllib3 ≥ 2.2.2, whose documented default minimum is TLS 1.2 (`SECURITY.md` § TLS Policy). Measured first: the interpreter's default was already 1.2 |
| 8.1 Per-call audit record | NO | **YES** | `ibkr_core_mcp.audit`: one redacted JSON line per tool call (`execute`, the two server-local tools) and per gated order write (`@_audited_write` on all seven `GATED_OWNERS`), with `ts`, correlation `id`, `kind`, `actor`, `client`, `agent`, tool/action, redacted `params`, `decision`, `outcome` (type only), `summary` (a length), `duration_ms`; 0600 in 0700, one rotation, fail-open. Session writes record from F45 step 2. `SECURITY.md` § Audit Record |
| 1.3 SBOM · 2.2 image scan · 1.2 attestation recipe | PARTIAL | pending in this series | CI jobs and the consumers recipe, next commits |
| 5.4 gateway CORS · 7.1 secrets at rest | PARTIAL | awaiting the operator | a rebuilt image and a fresh login; the 2026-10-16 deferral |
