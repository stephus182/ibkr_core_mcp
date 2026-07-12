# Security & Code Quality Audit — ibkr_core_mcp

**Date:** 2026-07-11
**Scope:** Full codebase (`ibkr_core_mcp/` + `ibkr_core_mcp/gateway/`) — no pending PR diff existed at audit time, so this covers the shipped code on `main`, not a changeset.
**Auditor:** Claude Sonnet 5 (multi-agent parallel static analysis — 6 independent domain agents, each finding independently re-verified by a second adversarial agent against source before inclusion)
**Status:** All 6 findings resolved (4 High, 2 Medium). Fixes: `4e38655..e587695` on branch `security-fixes-2026-07-11`, one commit per finding (plus 3 small follow-up commits from code-review loops) — see [`docs/plans/2026-07-11-security-fixes-plan.md`](plans/2026-07-11-security-fixes-plan.md) for implementation detail on each. Every fix and its tests were independently reviewed for spec compliance and code quality before being accepted; two review rounds (H-2's regex, H-3's second stale doc reference) found real issues that were fixed forward in follow-up commits.

---

## Summary

| Severity | Found | Confidence bar |
|---|---|---|
| High | 4 | ≥8/10, independently re-verified |
| Medium | 2 | ≥8/10, independently re-verified |
| Dropped (false positive) | 1 | TOCTOU order-dict mutation — no reachable caller in this repo, see below |

Method: 6 parallel discovery agents each audited an independent risk cluster (auth/order gates; backtest sandbox + store; network/SSRF/Drive/Flex; IBKR client + MCP server; the `claude_tools.py` LLM-tool layer; gateway Docker/shell infra). Every candidate finding was then re-verified by a second, adversarial agent working only from the claim and the source — instructed to independently reproduce the technical mechanism, not trust the first agent's confidence score. One finding (client.py:1109 TOCTOU) was dropped at the verification stage.

---

## Findings

### High

---

**H-1 — RestrictedPython sandbox escape via `DataFrame.eval`/`.query` — full RCE (`backtest.py:152`)**

`run_backtest` binds a real, unrestricted `pandas.DataFrame` (`df.copy()`) into the RestrictedPython exec namespace. Unlike `pd`/`np` (wrapped in stripped `SimpleNamespace`s), `df` keeps its full method surface. `eval`/`query` are ordinary public method names that `safer_getattr` doesn't block (it only blocks leading-underscore/dunder names), and this RestrictedPython version has no `_call_` hook to intercept a plain method call. Once inside `df.eval("...")`/`df.query("...")`, pandas runs its own independent expression engine (`pandas/core/computation/expr.py`) — never compiled through `compile_restricted`, unfiltered `getattr`/`getitem`/call resolution, and supports `@varname` to reach the sandbox's own local scope.

**Verified exploit** (confirmed against installed pandas 3.0.3 / RestrictedPython 8.1 source, not merely asserted):

```python
leak = df.eval("@df.__init__.__func__.__globals__['sys'].modules['os'].popen('id').read()")
raise Exception(leak)
```

`@df` → sandbox's own `df` local → `.__init__.__func__.__globals__` → `pandas/core/frame.py`'s real module globals (imports `sys`) → `sys.modules['os']` → `.popen(...)`. `run_backtest`'s runtime-error handler returns exception text verbatim to the tool caller (`claude_tools.py:1909-1922`) — a full, interactive RCE oracle through the `run_backtest` tool, no further authentication required. Directly contradicts `SECURITY.md`'s "Residual risk" claim that strategy code "cannot access credentials, read arbitrary paths, or make network calls."

**Recommended fix:** deny `eval`/`query` in the sandbox's `_getattr_` hook before falling through to `safer_getattr` (see fix plan Task 1).

---

**H-2 — Unvalidated `alert_id` lets the ungated `delete_alert` tool collapse to the gated `cancel_order` endpoint (`claude_tools.py:2445`, `client.py:1302-1311`)**

`_delete_alert` passes an unconstrained, LLM-controlled `alert_id` string straight to `client.delete_alert()`, which builds the request URL by raw f-string with no validation or encoding. `client.py` already has `_ACCOUNT_ID_RE` specifically to prevent path traversal in URLs (applied to `account_id`), but it was never extended to `order_id`/`alert_id`, which sit in structurally identical f-strings across `get_order_status`, `get_alert`, `delete_alert`, `modify_order`, `cancel_order`, `reply_order`.

**Verified exploit mechanism** (proven with a live call against this repo's installed `requests`/`urllib3`, not assumed):

```python
>>> requests.Request('DELETE', 'https://localhost:5055/v1/api/iserver/account/DU1234567/alert/../order/987654321').prepare().url
'https://localhost:5055/v1/api/iserver/account/DU1234567/order/987654321'
```

`urllib3.util.url.parse_url()` performs RFC 3986 dot-segment normalization client-side on any absolute URL string passed to `session.delete()` — deterministic, no dependency on IBKR gateway behavior. `delete_alert` (deliberately ungated — "alerts are not orders") one path segment away collapses to `cancel_order`'s exact URL (Touch ID + visual confirmation, "no bypass" per CLAUDE.md). This bug class was already found and fixed once for `account_id` (`docs/security-audit-2026-05-25.md` M-2, `docs/security-audit-2026-06-10.md` M-2) — the fix was never extended to the sibling `order_id`/`alert_id` parameter in the same statement.

**Exploit path:** discover a live `orderId` via the always-ungated `get_live_orders`, then call `delete_alert(alert_id="../order/<orderId>")` — cancels a live order with zero Touch ID and zero confirmation dialog.

**Recommended fix:** add `_ORDER_ID_RE = re.compile(r"^\d+$")` (doc-verified against IBKR's CP API reference — order/alert IDs are numeric) and validate before URL construction in all affected methods; add a separate `_REPLY_ID_RE` for `reply_order`'s `reply_id`, which IBKR documents as a hex/hyphen string, not numeric (see fix plan Task 2).

---

**H-3 — Gateway Docker container published on all host network interfaces, not loopback (`gateway/manager.py:160`)**

`GatewayManager.start()` launches the container with `"-p", f"{self._port}:{self._port}"` — no host-IP prefix, which Docker binds to `0.0.0.0` by default. This directly contradicts explicit claims in `SECURITY.md:215`, `SECURITY.md:249`, and `README.md:358` that the gateway is "bound to `localhost`... unreachable from outside the machine." The existing test (`tests/test_gateway.py::test_docker_run_includes_port_and_env_vars`) only does a substring check (`"5055:5055" in joined`), which passes identically with or without a host-IP prefix — nothing currently guards against this. Order-write gating (Touch ID + dialog) is enforced only in this Python library's call sites, not by the Java gateway process — anything on the same network segment reaching the gateway's HTTP port with a valid session cookie can call order endpoints directly.

**Recommended fix:** bind explicitly to loopback (`"-p", f"127.0.0.1:{self._port}:{self._port}"`); fix the test to assert the exact value; correct `SECURITY.md`/`README.md` (see fix plan Task 3).

---

**H-4 — SSRF guard resolves hostnames via IPv4-only `socket.gethostbyname`, fails open on AAAA-only hosts (`scrape_fallback.py:106`)**

`is_private_host()` resolves non-literal hostnames with `socket.gethostbyname(host)`, which only queries IPv4 `A` records. An AAAA-only hostname pointing at an internal IPv6 address (e.g. `::1`) raises `socket.gaierror`, caught and treated as "unresolvable, therefore safe" — but the host **is** resolvable, just not via this IPv4-restricted method, and the actual fetch (headless Chromium, standard dual-stack resolution) will succeed over IPv6. This single function backs both documented SSRF layers (`ClaudeToolkit._validate_public_url` and `scrape_fallback._reject_private_requests`), so both share the identical blind spot — confirmed no IP-pinning exists between the Python-level guard and the actual browser fetch. `_handle_firecrawl_search` feeds externally-sourced URLs into this exact path. Every existing SSRF-guard test mocks `socket.gethostbyname` only; one test explicitly asserts the current fail-open behavior as correct.

**Recommended fix:** replace `socket.gethostbyname(host)` with `socket.getaddrinfo(host, None)` and reject if any returned address (IPv4 or IPv6) is private/loopback/link-local/reserved (see fix plan Task 4).

---

### Medium

---

**M-1 — Gateway `conf.yaml` IP allowlist uses bare first-octet wildcards, far broader than the RFC 1918 ranges it's documented to enforce (`gateway/conf.yaml:24-29`)**

`ips.allow` lists `192.*` and `172.*`, which glob-match the full `192.0.0.0/8` (256× broader than RFC 1918's `192.168.0.0/16`) and `172.0.0.0/8` (16× broader than `172.16.0.0/12`) — including public IPv4 space. `SECURITY.md:284`/`:489` describe this as enforcing "RFC 1918 private ranges," which is inaccurate. (`127.*` is correctly scoped — full loopback per RFC 1122 — this is not a blanket criticism.) This is the compensating control that matters once H-3 makes the gateway reachable beyond loopback; note fixing this alone does not fix H-3, since a correctly-scoped allowlist still legitimately admits real LAN devices (that's what RFC 1918 ranges are for) — both need independent fixes.

**Recommended fix:** replace `192.*` with `192.168.*`, and `172.*` with the 16 discrete `172.16.*`–`172.31.*` entries (bare-octet-glob syntax, not CIDR); update `SECURITY.md` (see fix plan Task 5).

---

**M-2 — Flex-XML file-import path allowlist uses prefix string matching instead of a path-boundary check (`claude_tools.py:1384`)**

`_import_flex_file` validates the LLM-suppliable `path` argument with `str(resolved).startswith(str(allowed_root))`, where `allowed_root = Path.home() / ".ibkr_core"`. `Path.__str__()` never appends a trailing separator, so this is a raw string-prefix comparison with no segment boundary — any resolved path whose name is a *superstring* of `.ibkr_core` (e.g. `~/.ibkr_core_backup`, `~/.ibkr_coreEVIL` — empirically confirmed, literally any suffix) incorrectly passes. Git history (`74cb466`) confirms this was a deliberate fix for a prior arbitrary-file-read finding, now incompletely implemented. Exploitability is not bounded by "requires a coincidental pre-existing sibling folder" as it might first appear: the same threat actor can self-create the precondition through the already-exposed `run_backtest` tool's accepted-residual-risk `DataFrame.to_csv()` write primitive (pandas' own `os.path.expanduser()` will tilde-expand and write to an arbitrary `~/.ibkr_core*`-prefixed path), and the function's own error message discloses the exact home-directory path on any invalid probe. A related, independent bug: the function validates `resolved` but passes the raw, unexpanded `path` string to `flex.import_from_file()` — the two should be the same value.

**Recommended fix:** replace with `resolved.is_relative_to(allowed_root)`; pass `resolved` (not `path`) to `import_from_file()` (see fix plan Task 6).

---

### Investigated, not reported

**Gate-2 dialog / network-payload TOCTOU (`client.py:1109`)** — `place_order`/`modify_order` re-read the caller's live `order` dict after the confirmation dialog returns rather than using the dialog's frozen snapshot, so a caller that mutates the dict during the Touch-ID-plus-dialog window could send different values than what the human approved. Dropped at verification (confidence 2/10): no code path in this repo calls `place_order`/`modify_order` at all (order execution is UI-layer only, per the method's own docstring, and confirmed empirically via grep of `claude_tools.py`/`mcp_server.py`); the one known real caller (a sibling `claudia_ui` repo) is a single straight-line flow with no evidence of concurrent dict mutation. A cheap defensive-coding improvement (`order = dict(order)` at the top of both methods) is worth doing opportunistically but does not rise to a reportable finding — no reachable exploit exists in this codebase today.

`client.py`, `mcp_server.py`, `streaming.py`, `store.py`, `pinescript.py`, `models.py`, `auth.py`, `human_auth.py`, `order_confirm.py`, `_order_dialog.py`, `gdrive_auth.py`, `flex_query.py`, `cache.py`, `rate_limiter.py`, `config.py`, and the gateway shell scripts/Dockerfile produced no findings meeting the ≥8/10 confidence bar.

---

## Audit History

Full prior audit reports: [`docs/security-audit-2026-05-25.md`](security-audit-2026-05-25.md) · [`docs/security-audit-2026-05-26.md`](security-audit-2026-05-26.md) · [`docs/security-audit-2026-05-27.md`](security-audit-2026-05-27.md) · [`docs/security-audit-2026-06-10.md`](security-audit-2026-06-10.md) · [`docs/security-audit-2026-06-23.md`](security-audit-2026-06-23.md)
