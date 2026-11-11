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
| 1.2 Trusted source, authenticity verified | PARTIAL | **PARTIAL → verified here, recipe published** | `pypi-attestations verify pypi --repository https://github.com/stephus182/ibkr_core_mcp` → `OK` for the 2.1.0 wheel and sdist (2026-11-09, tool 0.0.31); the recipe is in `docs/consumers.md`. What remains is the consumer's CI step at the pin — outside this repository |
| 1.3 SBOM, CVE scan, hash pinning, blocking | PARTIAL | **YES, with one accepted gap** | `ci.yml` `sbom`: CycloneDX 1.6 of `.[server,scraper]`, 112 components locally; `pip-audit` blocking already. Hash pinning stays declined: version floors by the 2026-09-13 decision, PyPI artifacts immutable, the attestation covers the integrity gap |
| 2.2 SAST, DAST, SCA, secrets, container scanning | PARTIAL | **PARTIAL → image scan added** | `ci.yml` `gateway-image-scan`: `trivy` over the built gateway image, CRITICAL + HIGH, informational on its first run, then blocking on CRITICAL. DAST stays N/A (nothing exposed by default) |
| 7.1 Secrets in a vault | PARTIAL | **YES** | `ibkr_core_mcp.secret_store` over `keyring`: the OS keychain (macOS Keychain, Windows Credential Locker, Linux Secret Service) read by `Config.from_env` between the environment and the `.env` file; the operator lifted the 2026-10-16 deferral the same day ("7.1 yes"). A command line that never prints a value (`set` / `list` / `import-env` / `delete`); door 7 in the test suite; five mutations red. The Drive OAuth token and the SSE token stay 0600 files the package writes itself; the `.env` route stays as the fallback for a machine without a keychain |
| 5.4 Gateway CORS origin | PARTIAL | **YES** | `gateway/conf.yaml` `cors.origin.allowed` `"*"` → `"https://localhost:5055"`, `allowCredentials` stays `false`; held in source by `test_documented_controls.py` (no wildcard, an https loopback origin, SECURITY.md quoting the same value). IBKR documents the key, not its semantics. **The first pass above was wrong to call the wildcard "mitigated by the credentials flag"** — measured 12:52 EST on the live gateway, before the rebuild: a foreign origin's preflight was approved (`Access-Control-Allow-Origin: *`, `POST,GET,OPTIONS,DELETE,PUT`), and a request with no cookie and that origin was served on the authenticated session (`/tickle` `authenticated = True`). The session is the gateway's, not a cookie's. After the rebuild, measured 13:07 EST on the rebuilt image (built 2026-11-09 18:03 UTC) after a fresh login through the gateway's own page, which authenticated: the foreign origin's preflight **and** its plain `GET` are refused by the gateway itself, `403 CORS Rejected - Invalid origin`, so such a request never reaches the session; the gateway's own origin is approved (`204`, `Access-Control-Allow-Origin: https://localhost:5055`); a request with no `Origin` — how every client of this package calls — is served (`200`). |

## Follow-up 2026-11-11 — the login window's profile, read against three items

An addition; the tables above are left as written. The login window's Chrome profile
(`~/.ibkr_core/login-chrome`, register F44) was read on 2026-11-11 — what it keeps at rest, the
lock Chrome leaves after a close, and what that Chrome sends to Google (`SECURITY.md` § The login
window's profile; the sources in `audit-evidence/scrapes/manifest.json`). No answer changes;
three gain a line:

| Item | Answer | Added |
|---|---|---|
| 3.2 Network segmentation, egress allow-list | PARTIAL, unchanged | One more egress, undeclared until now: the login window's Chrome contacts Google by itself at launch (a `NID` cookie created in the launch second; components fetched into the profile). It is Chrome's documented signed-out traffic; which request sets the cookie, and whether crash reports are enabled in that profile, were not determined. No switch is passed against it, by decision |
| 4.3 Short-lived, replay-protected tokens | PARTIAL, unchanged | The gateway's login pages leave cookies in that profile: four session cookies still on disk after the window is closed, and three that are long-lived by IBKR's choice (`SBID` 400 days, `device.info` 394, `TABID` 1). The gateway serves data reads without any of them (register F46) |
| 7.1 Secrets in a vault | YES, unchanged | The profile is a second place session material rests, outside the keychain: cookie values encrypted by Chrome, files `0600` in a `0700` profile — modes that are Chrome's, not set or repaired by this package. No password, autofill entry or card is saved in it (0 / 0 / 0, measured) |

3.4 (minimal interface, no unused listener) is unaffected: the socket Chrome leaves behind has
nothing listening on it.

## Appendix (added 2026-11-11) — the checklist as shared, in full

An addition, on the operator's word of 2026-11-11: the checklist's text may live in this
repository; the spreadsheet itself stays out of it (`security/*.xlsx` is ignored). This appendix
is the sheet, cell for cell, generated from the file. For the wording it supersedes the
"condensed" questions and the "summarised, not reproduced" columns of the sections above; their
answers are unchanged. Two things here are not the sheet's own. The item IDs: the file stores
them as dates (1.1 as 1 January), so each is restored from its row's section and position and
checked against that date. And one phrase of item 6.2's best practice: where the sheet names an
organisation, this reads "the project's" — the checklist is generic, and here it is applied to
this project (operator, 2026-11-11). The sheet's answer and comment columns are
empty. Its scores agree with the sections above for all 29 items (checked when this was
generated). Wording, spelling and punctuation are the sheet's.

### 0. Framing questions

- **0.0** Is the MCP server developed internally (Make) or acquired from a third party (Buy)? (include vendor details and ownership responsibilities)
- **0.1** How many users access the MCP server, and what are the user types (internal vs. external, standard vs. privileged users, service accounts, etc.)?
- **0.2** List the tools and functions provided by the MCP server and describe the actions they enable (panel "List of tools").
- **0.3** What is the "Security rating" and Sensitivity Level handled by the MCP server?

### 1. Origin & Integrity

- **1.1** (score 2) — Has the MCP server vendor (and the underlying tool providers it federates) completed the enterprise Third-Party Risk Management (TPRM) process including the MCP server itself?
  - Best practice (how to implement):
    - Require formal security attestations (SOC 2 Type II, ISO 27001) covering the AI/LLM perimeter.
    - Maintain an allow-list of approved MCP servers and OSS repositories.
    - Apply binary authorization to block execution of unsigned or unverified code.
  - Expected risk (if not complied):
    - Supply chain compromise introducing backdoors into the data processing infrastructure.
    - Silent installation of malicious components via unvetted third-party dependencies.
  - Deployment pattern: Vendor-hosted SaaS | Enterprise-hosted server
  - Server provenance / trust label: Provided by a vendor
- **1.2** (score 3) — Is the MCP server installed from a trusted source with appropriate controls to verify its authenticity and prevent the use of unverified software?
  - Best practice (how to implement):
    - Use cryptographic signatures (Sigstore, GPG) to validate authenticity and provenance before installation.
    - Verify remote attestations (SLSA L3+) to ensure code integrity prior to deployment.
    - Pin by content digest, not by mutable version tag.
  - Expected risk (if not complied):
    - Download and execution of a malicious package impersonating a legitimate component (typosquatting).
    - Substitution of a legitimate tool with a tampered version during the build process.
  - Deployment pattern: Enterprise-hosted server
  - Server provenance / trust label: Provided by a vendor | Adopted from open source | Unverified origin
- **1.3** (score 3) — Is a Software Bill of Materials (SBOM) maintained, with automated CVE scanning, hash-pinned dependencies, and a build-blocking policy on critical CVEs?
  - Best practice (how to implement):
    - Implement SBOM (SPDX / CycloneDX) tracking for all MCP components.
    - Pin dependencies using cryptographic hash pinning rather than version ranges.
    - Automatically scan for CVEs in all MCP server dependencies and block the pipeline on critical findings.
  - Expected risk (if not complied):
    - Exploitation of a known public vulnerability present in an unpatched third-party library.
    - Privilege escalation or remote code execution on the application host.
  - Deployment pattern: Enterprise-hosted server
  - Server provenance / trust label: Built internally | Provided by a vendor | Adopted from open source

### 2. Application Security

- **2.1** (score 2) — Has a manual secure code review been performed by AppSec engineers, with explicit coverage of MCP-specific patterns ( Enforced Input type validation, MCP tool hint declarations (readOnly, destructive, openWorld, idempotent), authentication discovery setup correctly (./well-known paths)?
  - Best practice (how to implement):
    - Apply strict code reviews targeting file path canonicalization and absence of unparameterized SQL or shell queries.
    - Require sign-off from an AppSec reviewer for any MCP-relevant change.
    - Block the pipeline on any critical injection vulnerability (Command, SQL, Path Traversal).
  - Expected risk (if not complied):
    - Introduction of injection flaws or improper input handling.
    - Discovery of exploitable vulnerabilities by internal or external attackers.
  - Deployment pattern: Enterprise-hosted server
  - Server provenance / trust label: Built internally | Adopted from open source
- **2.2** (score 3) — Are automated AppSec controls (SAST, DAST, SCA, secret scanning, container scanning) integrated into CI/CD with blocking thresholds on critical findings?
  - Best practice (how to implement):
    - Automate a full SDLC pipeline: SAST for code, DAST on exposed endpoints, SCA for dependencies, secret scanning, and container image scanning.
    - Enforce code signature verification and version upgrade policies.
    - Block deployment on critical or unresolved high findings.
  - Expected risk (if not complied):
    - Rushed deployment of a new version introducing major security regressions.
    - Bypass of preventive controls through a misconfigured production pipeline.
  - Deployment pattern: Enterprise-hosted server
  - Server provenance / trust label: Built internally | Adopted from open source
- **2.3** (score 2) — Have penetration tests or red team exercises covered MCP-specific attack vectors (MITRE ATLAS / OWASP API/ OWASP MCP)?
  - Best practice (how to implement):
    - Include scenarios simulating indirect prompt injection and tool poisoning in penetration test scope.
    - Use AI-specific attack frameworks (MITRE ATLAS, OWASP LLM Top 10) to evaluate resilience.
    - Re-test after material changes to tools or prompts.
  - Expected risk (if not complied):
    - Security blind spot on attack vectors unique to autonomous agent architectures.
    - No evaluation of system resilience against malicious instructions injected via external data sources.
  - Deployment pattern: Enterprise-hosted server | Vendor-hosted SaaS
  - Server provenance / trust label: Built internally | Provided by a vendor | Adopted from open source | Unverified origin

### 3. Environment

- **3.1** (score 3) — Is the MCP server running in a secure sandboxed environment, with additional Trusted Execution Environment (TEE) protections applied when handling highly sensitive data?
  - Best practice (how to implement):
    - Replace standard containers (e.g., Docker) with hardened sandboxes such as gVisor, Kata Containers, or strict SELinux/AppArmor profiles.
    - For maximum isolation, run within Trusted Execution Environments (TEEs) such as Intel TDX or AMD-SEV/SNP.
  - Expected risk (if not complied):
    - Full compromise of the host machine if a vulnerability is successfully exploited.
    - Privilege escalation granting the attacker access to adjacent processes or the entire host system.
  - Deployment pattern: Enterprise-hosted server
  - Server provenance / trust label: Built internally | Provided by a vendor | Adopted from open source
- **3.2** (score 3) — Is the MCP server isolated through network segmentation, with access limited to required resources only through a default-deny policy and allow-list, and is admin access secured with enterprise IAM and MFA?
  - Best practice (how to implement):
    - Implement Kubernetes NetworkPolicies / VPC SGs with default-deny.
    - Constrain outbound egress to an explicit allow-list (LLM provider, data sources, identity provider).
    - Apply Zero-Trust network access controls.
  - Expected risk (if not complied):
    - Unauthorized lateral movement across internal network segments.
    - Exposure of sensitive internal resources due to overly permissive network access.
  - Deployment pattern: Enterprise-hosted server | Vendor-hosted SaaS
  - Server provenance / trust label: Built internally | Provided by a vendor | Adopted from open source | Unverified origin
- **3.3** (score 2) — Are development, test, and production environments strictly separated, with no production data, secrets, or identities accessible from lower environments (synthetic or fully anonymized data only)?
  - Best practice (how to implement):
    - Maintain strict logical and physical separation between dev, test, and prod networks.
    - Ensure no production credentials, tokens, or databases are accessible from lower environments.
    - Use synthetic or fully anonymized data in non-prod.
  - Expected risk (if not complied):
    - Accidental or compromised processing of production data in a less-secured test environment.
    - Production compromise by pivoting from a vulnerability left open in the development environment.
  - Deployment pattern: Enterprise-hosted server
  - Server provenance / trust label: Built internally | Provided by a vendor | Adopted from open source
- **3.4** (score 2) — Does the server bind only to the minimal required network interface (loopback 127.0.0.1 for local stdio; explicit private interface for remote), with all unused listeners and debug endpoints disabled in production?
  - Best practice (how to implement):
    - For local transports: enforce binding exclusively to the loopback interface (127.0.0.1).
    - For remote transports: implement strict NetworkPolicies with a default-deny posture.
    - Disable unused listeners and debug endpoints in production.
  - Expected risk (if not complied):
    - Unintended exposure of the service on the corporate network, making it discoverable by internal attackers.
    - Exploitation of a local development machine via DNS rebinding attacks from a browser.
  - Deployment pattern: Local workstation | Enterprise-hosted server
  - Server provenance / trust label: Built internally | Provided by a vendor | Adopted from open source | Unverified origin
- **3.5** (score 2) — Is an emergency shutdown / kill-switch mechanism available, regularly tested (≥ quarterly), and operable within minutes by the SOC without requiring developer involvement?
  - Best practice (how to implement):
    - Implement rapid rollback and an emergency shutdown process for malicious or malfunctioning MCP components.
    - Integrate a circuit-breaker mechanism controllable via API Gateway or feature flagging.
    - Test the kill-switch quarterly via tabletop or live exercise.
  - Expected risk (if not complied):
    - Inability to stop an ongoing data exfiltration or malicious propagation in real time.
    - Collateral damage requiring broad system shutdowns to isolate a single failing component.
  - Deployment pattern: Enterprise-hosted server | Vendor-hosted SaaS
  - Server provenance / trust label: Built internally | Provided by a vendor | Adopted from open source | Unverified origin

### 4. Authentication & Authorization

- **4.1** (score 3) — Is OAuth 2.1 (or equivalent) used for authorization with PKCE, refresh-token rotation, and no implicit or password grant flows?
  - Best practice (how to implement):
    - Deploy OAuth 2.1 for secure delegation with short-lived tokens.
    - Support DPoP (proof-of-possession) to prevent token replay.
    - Perform Token Exchange (RFC 8693) to maintain auditability of delegated actions.
  - Expected risk (if not complied):
    - Unauthorized access to service resources via interception of unprotected requests.
    - Fraudulent impersonation of a legitimate user by a malicious third-party application.
  - Deployment pattern: Enterprise-hosted server | Vendor-hosted SaaS
  - Server provenance / trust label: Built internally | Provided by a vendor | Adopted from open source | Unverified origin
- **4.2** (score 4) — Is end-user authentication delegated to the enterprise IdP (Entra ID) via OIDC with mandatory phishing-resistant MFA, and is local/anonymous authentication disabled?
  - Best practice (how to implement):
    - Authenticate users via OIDC with mandatory phishing-resistant MFA.
    - Assign AI agents and servers cryptographic workload identities (SPIFFE / SPIRE).
    - Block any local or anonymous authentication path.
  - Expected risk (if not complied):
    - Inability to audit and attribute actions to a specific individual or system with certainty.
    - Privilege escalation via misuse of a service account with overly permissive rights.
  - Deployment pattern: Enterprise-hosted server | Vendor-hosted SaaS
  - Server provenance / trust label: Built internally | Provided by a vendor | Adopted from open source | Unverified origin
- **4.3** (score 3) — Are access tokens short-lived (≤1h), sender-constrained (DPoP or mTLS-bound), and replay-protected, with refresh tokens rotated and revocable in real time?
  - Best practice (how to implement):
    - Issue access tokens (JWT) with the shortest possible lifetime.
    - Implement DPoP or mTLS-bound tokens to prevent replay.
    - Restrict scopes to the strict minimum required.
  - Expected risk (if not complied):
    - Immediate reuse of a stolen access token to initiate an undetectable illegitimate session.
    - Prolonged session hijacking following a temporary access compromise.
  - Deployment pattern: Enterprise-hosted server | Vendor-hosted SaaS
  - Server provenance / trust label: Built internally | Provided by a vendor | Adopted from open source | Unverified origin
- **4.4** (score 4) — Are token claims (aud, iss, scope, sub) strictly verified server-side, with audience binding enforced and tokens issued for other services categorically rejected (anti confused-deputy)?
  - Best practice (how to implement):
    - On the target server, decode the JWT and strictly verify the 'aud' and 'iss' claims.
    - Reject any token whose audience does not exactly match the target server's identifier.
    - Enforce scope-based authorization on every request.
  - Expected risk (if not complied):
    - Fraudulent reuse of a legitimate token (issued for a low-privilege service) to access a critical service.
    - Confused Deputy vulnerability where an intermediate component acts illegitimately on behalf of another.
  - Deployment pattern: Enterprise-hosted server | Vendor-hosted SaaS
  - Server provenance / trust label: Built internally | Provided by a vendor | Adopted from open source | Unverified origin
- **4.5** (score 4) — Are roles, scopes, and permissions managed centrally (RBAC / ABAC via OPA, Cedar, OpenFGA) and enforced at the tool-parameter level (not just the endpoint), with least-privilege defaults?
  - Best practice (how to implement):
    - Externalize access control using policy engines (OPA, Cedar, OpenFGA).
    - Define fine-grained permission models restricting actions at the tool-parameter level.
    - Default to read-only when write access is not functionally justified.
  - Expected risk (if not complied):
    - Exploitation of critical tools (e.g., data modification) without justified business need.
    - Historically over-permissive default permissions violating the least-privilege principle.
  - Deployment pattern: Enterprise-hosted server | Vendor-hosted SaaS
  - Server provenance / trust label: Built internally | Provided by a vendor | Adopted from open source | Unverified origin
- **4.6** (score 4) — Is multi-tenancy enforced with strict isolation of data, sessions, tool access, vector indexes, and cryptographic material between tenants (validated by periodic cross-tenant pentests)?
  - Best practice (how to implement):
    - Cryptographically separate data using tenant-specific encryption keys.
    - Prevent any sharing of memory, secrets, vector partitions, or execution contexts between tenants.
    - Validate isolation through periodic cross-tenant penetration testing.
  - Expected risk (if not complied):
    - Cross-tenant data leak allowing tenant A to read tenant B's private context or raw data.
    - Immediate breach of legal compliance obligations under cloud trust agreements.
  - Deployment pattern: Shared / multi-tenant platform
  - Server provenance / trust label: Provided by a vendor | Adopted from open source

### 5. Communications

- **5.1** (score 3) — Are all communications encrypted using TLS 1.2 or higher, with weak ciphers and protocol downgrade explicitly disabled?
  - Best practice (how to implement):
    - Enforce TLS 1.2 for all HTTP transport communications.
    - For server-to-server communications, apply a Service Mesh (e.g., Istio) for automatic mTLS.
    - Disable TLS ≤1.1 and weak cipher suites at the load balancer.
  - Expected risk (if not complied):
    - Passive interception or active modification of data in transit by a network-positioned attacker.
    - Theft of authentication tokens or confidential business data transmitted in cleartext.
  - Deployment pattern: Enterprise-hosted server | Vendor-hosted SaaS
  - Server provenance / trust label: Built internally | Provided by a vendor | Adopted from open source | Unverified origin
- **5.2** (score 3) — Are TLS certificates fully validated (chain, hostname, expiration, revocation via OCSP stapling or CRL) with no exceptions in production code, and is mutual TLS used for server-to-server links?
  - Best practice (how to implement):
    - Apply mutual authentication (mTLS) to cryptographically verify the identity of both ends of each connection.
    - Automate certificate lifecycle management and alert on imminent expiration.
    - Forbid TLS-verification bypass in production code.
  - Expected risk (if not complied):
    - Imperceptible traffic redirection to an attacker-controlled destination.
    - Successful endpoint impersonation leading to exfiltration of client system requests.
  - Deployment pattern: Enterprise-hosted server | Vendor-hosted SaaS
  - Server provenance / trust label: Built internally | Provided by a vendor | Adopted from open source | Unverified origin
- **5.3** (score 2) — For HTTP/SSE and Streamable HTTP transports, are CSRF protections (anti-CSRF tokens, Origin/Referer validation, SameSite cookies) in place?
  - Best practice (how to implement):
    - Enable anti-CSRF controls on all HTTP/SSE-exposed interfaces.
    - Validate the 'Origin' or 'Referer' header against a strict allow-list at the load balancer or application layer.
    - Use SameSite=Strict cookies for session state.
  - Expected risk (if not complied):
    - Silent execution of harmful actions via a manipulated or deceived user's browser.
    - Submission of malicious requests exploiting the victim's active session.
  - Deployment pattern: Enterprise-hosted server | Vendor-hosted SaaS
  - Server provenance / trust label: Built internally | Provided by a vendor | Adopted from open source | Unverified origin
- **5.4** (score 2) — Are CORS policies strictly configured to an explicit allow-list of enterprise origins, with no wildcard (*) and no Access-Control-Allow-Credentials with wildcard in any environment?
  - Best practice (how to implement):
    - Restrict CORS policies to prevent data leakage to unauthorized domains.
    - Configure the reverse proxy to return 'Access-Control-Allow-Origin' only for validated enterprise domains.
    - Forbid wildcard CORS in any environment exposed to the internet.
  - Expected risk (if not complied):
    - Unauthorized harvesting of confidential data by scripts hosted on non-affiliated web domains.
    - Bypass of browser-native protection mechanisms.
  - Deployment pattern: Enterprise-hosted server | Vendor-hosted SaaS
  - Server provenance / trust label: Built internally | Provided by a vendor | Adopted from open source | Unverified origin

### 6. Action Security

- **6.1** (score 4) — Are inputs and outputs validated and sanitized to prevent tool-parameter injection, and classical code injection (SQL, command, path traversal, SSRF)?
  - Best practice (how to implement):
    - Apply strict allow-lists on all inputs.
    - Sanitize file path parameters and use context-appropriate output encoding (SQL, shell, HTML).
    - Use parameterized queries or an ORM to prevent SQL injection.
  - Expected risk (if not complied):
    - Unrestricted execution of arbitrary system commands on the hosting infrastructure.
    - Critical database compromise or unauthorized access to restricted filesystem directories.
  - Deployment pattern: Local workstation | Enterprise-hosted server | Vendor-hosted SaaS
  - Server provenance / trust label: Built internally | Provided by a vendor | Adopted from open source | Unverified origin
- **6.2** (score 4) — Are critical or irreversible MCP tool actions (financial, contractual, destructive, mass-mutation) subject to non-bypassable Human-in-the-Loop (HITL) confirmation with full context shown to the approver?
  - Best practice (how to implement):
    - Enforce HITL validation that cannot be disabled by an unprivileged user (destructive hint present in the tool decoration)
    - Explicitely check the tools to verify consistency with the project's risk based evaluation (risk appetite may defer from editor's proposition)
    - Request approval via server-side Elicitation for any critical or irreversible action.
    - Display the full tool call, parameters, and downstream effect to the approver.
  - Expected risk (if not complied):
    - Unexpected triggering of destructive actions (deletion, mass mutation) from an erroneous AI decision.
    - Complete inability to halt a damaging sequence initiated without user awareness.
  - Deployment pattern: Enterprise-hosted server | Vendor-hosted SaaS
  - Server provenance / trust label: Built internally | Provided by a vendor | Adopted from open source | Unverified origin
- **6.3** (score 2) — Are resource limits enforced (token budget, payload size, request rate, tool-call recursion depth, agent loop bound) to prevent denial-of-service and denial-of-wallet?
  - Best practice (how to implement):
    - Apply strict quotas (token bucket) on payload sizes and token budgets at the API Gateway.
    - Limit tool-call recursion depth and agent loop iterations in application code.
    - Alert on per-tenant budget overruns in real time.
  - Expected risk (if not complied):
    - General service disruption and outage caused by deliberate saturation of compute or network capacity.
    - Uncontrolled explosion of cloud service billing under relentless API call loops.
  - Deployment pattern: Shared / multi-tenant platform | Vendor-hosted SaaS
  - Server provenance / trust label: Built internally | Provided by a vendor | Adopted from open source | Unverified origin

### 7. Secrets & Identities

- **7.1** (score 3) — Are all secrets (API keys, tokens, certificates, DB credentials) stored in a centralized cyber validated secrets vault? Never in code, config files, or environment variables baked into images?
  - Best practice (how to implement):
    - Deliver API keys and secrets via encrypted channels exclusively to attested MCP clients.
    - Categorically prohibit hardcoded credentials in source code, configuration files, or environment variables.
    - Inject secrets at runtime from the vault using short-lived tokens.
  - Expected risk (if not complied):
    - Immediate exfiltration of master keys during a breach occurring in a routine log file.
    - Cascading failure of all dependent third-party systems relying on the exposed credentials.
  - Deployment pattern: Enterprise-hosted server
  - Server provenance / trust label: Built internally | Provided by a vendor | Adopted from open source

### 8. Monitoring & Audit

- **8.1** (score 3) — Are all actions fully logged with the minimum required fields, with sensitive data redacted: timestamp, human user ID, agent ID, client ID, tool name, parameters, response summary, decision (allowed/denied), and correlation ID?
  - Best practice (how to implement):
    - Create structured logs covering all actions and authorization decisions.
    - Integrate OpenTelemetry to provide end-to-end traceability of agent decisions and tool calls.
    - Capture both request and response metadata with consistent schemas.
  - Expected risk (if not complied):
    - Inability to reconstruct an incident timeline.
    - Direct non-compliance finding during audits verifying the organization's ability to preserve log integrity.
  - Deployment pattern: Enterprise-hosted server | Vendor-hosted SaaS
  - Server provenance / trust label: Built internally | Provided by a vendor | Adopted from open source | Unverified origin
- **8.2** (score 2) — Are MCP audit logs centralized in the enterprise SIEM with normalized schemas and full correlation, while ensuring integrity protection and tamper evidence throughout the collection pipeline?
  - Best practice (how to implement):
    - Route all log streams to the enterprise SIEM via a log agent (Fluentd, Logstash, OTel collector).
    - Use MCP gateways to centralize logging of all model interactions.
    - Normalize logs to a common schema (e.g., OCSF, ECS).
  - Expected risk (if not complied):
    - Investigation fragmentation due to inability to correlate related security incidents.
    - Detection gaps between MCP-layer and downstream-system events.
  - Deployment pattern: Enterprise-hosted server | Vendor-hosted SaaS
  - Server provenance / trust label: Built internally | Provided by a vendor | Adopted from open source | Unverified origin
- **8.3** (score 2) — Is real-time alerting in place for MCP-specific anomalies (unusual tool-call sequences, output policy violations, abnormal egress, repeated authorization failures)?
  - Best practice (how to implement):
    - Create correlation rules in the SIEM for abnormal request volumes or repeated 403 errors.
    - Implement detection for Shadow IT deployments and covert agent activity.
    - Add MCP-specific detections for injection signatures and tool-call anomalies.
  - Expected risk (if not complied):
    - Delayed awareness of a slow-moving data exfiltration operating below standard thresholds.
    - Silent attacker consolidation within the system without triggering any SOC response.
  - Deployment pattern: Enterprise-hosted server | Vendor-hosted SaaS
  - Server provenance / trust label: Built internally | Provided by a vendor | Adopted from open source | Unverified origin
- **8.4** (score 2) — Is access to raw logs and the SIEM gated by RBAC with strict separation of duties (security analysts ≠ MCP operators) and approval workflows for high-sensitivity queries?
  - Best practice (how to implement):
    - Apply RBAC on the SIEM/log platform: only authorized analysts query raw logs.
    - Enforce separation of duties between MCP operators and log auditors.
    - Require approval and audit trail for queries touching highly sensitive fields.
  - Expected risk (if not complied):
    - Unauthorized personnel reading sensitive operational or personal data from audit trails.
    - Insider threat using log access to cover tracks or exfiltrate intelligence.
  - Deployment pattern: Enterprise-hosted server | Vendor-hosted SaaS
  - Server provenance / trust label: Built internally | Provided by a vendor | Adopted from open source | Unverified origin
