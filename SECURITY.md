# Security Policy — ibkr_core_mcp

This document describes the security model, threat mitigations, and responsible disclosure process for `ibkr_core_mcp`. The package connects a Claude AI agent to live brokerage infrastructure; security is treated as a first-class architectural concern throughout, not an afterthought.

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

## Threat Model

`ibkr_core_mcp` sits at the boundary between an LLM agent (Claude) and a live IBKR brokerage account. Two principals operate the system with different trust levels:

| Principal | Trusted for | Explicitly not trusted for |
|---|---|---|
| **Human operator** | Configuration, credential management, order approval | Unattended automation of order writes |
| **LLM / Claude agent** | Read operations, analysis, strategy generation | Order execution, credential access, arbitrary code execution |

This separation is enforced **architecturally**, not by policy. No combination of prompt, tool call, or LLM-generated input can bypass the human-in-the-loop controls — they require physical presence at the machine.

The secondary threat surface is the LLM tool boundary: data flowing from external APIs (IBKR, Flex XML) back to the LLM must be sanitized to prevent injection attacks.

---

## MCP Security Best Practices — Mapping

The following table maps each attack class from the [MCP Security Best Practices](https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices) to the controls implemented in `ibkr_core_mcp`.

| MCP Attack Class | ibkr_core_mcp Control | Location |
|---|---|---|
| **Confused Deputy** | LLM has no order-write tools; `account_id` regex blocks path manipulation | `claude_tools.py`, `_validate_account_id` |
| **Token Passthrough** | `_safe_error` maps all exceptions to controlled strings; raw API responses never forwarded to LLM | `claude_tools.py`, `_safe_error` |
| **SSRF** | Flex `<Url>` validated against domain allowlist before any HTTP request | `flex_query.py`, `_ALLOWED_URL_PREFIX` |
| **Session Hijacking** | Session cookie re-read from browser on each use; gateway bound to localhost; no persistent session store | `auth.py`, `client.py` |
| **Local Server Compromise** | RestrictedPython sandbox with safe namespaces, 4 096-char limit, 10-second execution timeout | `backtest.py` |
| **Scope Minimization** | Claude tool surface is read-only; order writes require biometric + visual human confirmation | `claude_tools.py`, `client.py` |

Each of these is detailed in the sections below.

---

## Order Execution Security — Two-Gate System

**All order write operations require two sequential human-in-the-loop validations. There is no bypass, no fallback, and no session cache.**

### Gate 1 — Biometric Authentication (Touch ID)

| Property | Value |
|---|---|
| Mechanism | Apple `LocalAuthentication` — `LAPolicyDeviceOwnerAuthenticationWithBiometrics` |
| Password / PIN fallback | **None** — explicitly prohibited by policy; the biometric-only policy is set at the API call, not as a preference |
| Timeout | 60 seconds; raises `HumanAuthError` on expiry |
| On denial | `HumanAuthError` raised immediately; IBKR endpoint is never contacted |
| Location | `ibkr_core_mcp/human_auth.py` |

`LAPolicyDeviceOwnerAuthenticationWithBiometrics` is distinct from `LAPolicyDeviceOwnerAuthentication`. The system cannot offer a password fallback even if the user attempts it — the OS enforces this at the API level.

### Gate 2 — Visual Order Confirmation Dialog

| Property | Value |
|---|---|
| Mechanism | `tkinter` modal displaying full order details and a live-order disclaimer |
| Confirmation | Explicit mouse click on "Confirm" — Enter key does not confirm |
| Auto-cancel | 60-second countdown ticker; raises `HumanAuthError` on expiry |
| Rationale for timeout | Prevents an unattended dialog on a locked screen from being confirmed by physical access |
| Location | `ibkr_core_mcp/order_confirm.py` |

### Enforcement Location

Both gates are applied at the **innermost call site** inside `IBKRClient`, not at the tool layer or any middleware. This ensures no code path can bypass them by calling the method differently.

```
place_order()   ──► require_touch_id() ──► confirm_dialog() ──► POST /iserver/account/{id}/orders
modify_order()  ──► require_touch_id() ──► modify_dialog()  ──► POST /iserver/account/{id}/orders/{orderId}
cancel_order()  ──► require_touch_id() ──► cancel_dialog()  ──► DELETE /iserver/account/{id}/order/{orderId}
reply_order()   ──► require_touch_id() ──► reply_dialog()   ──► POST /iserver/reply/{replyId}
```

### Gated vs. Ungated Endpoints

**Gated (Touch ID → confirmation dialog required before any network call):**

| `IBKRClient` method | Dialog shown |
|---|---|
| `place_order` | Full order details + live-order disclaimer |
| `modify_order` | Change summary (old → new) |
| `cancel_order` | Cancellation confirmation |
| `reply_order` | IBKR reply confirmation |

**Explicitly ungated (read-only; no execution risk):**

| `IBKRClient` method | Reason |
|---|---|
| `get_order_preview` | IBKR `whatif` endpoint — simulates, never executes |
| `get_live_orders` / `get_order_status` | Read-only |
| `create_alert` / `delete_alert` / `activate_alert` | Price notifications, not order execution |

---

## LLM / AI Boundary Controls

### Scope Minimization — No Order Writes in Tool Surface

`ClaudeToolkit` exposes **20 read-only tools** to the LLM. None of them can write to IBKR. The complete tool surface is:

| Category | Tools |
|---|---|
| Market data | `fetch_market_data`, `check_cache`, `list_cache` |
| Account | `get_account_summary`, `get_positions`, `get_ledger`, `get_allocation` |
| Trades | `get_trades`, `sync_flex_trades` |
| Orders (read-only) | `get_live_orders` |
| Analysis | `get_pa_performance`, `get_pa_transactions`, `get_contract_info`, `get_option_chain`, `run_scanner` |
| Notifications | `get_notifications` |
| Analytics & backtest | `add_indicators`, `run_backtest`, `generate_pinescript`, `get_analytics` |

`sync_flex_trades` writes to the local SQLite store and GDrive cache, not to IBKR. Order placement must go through `IBKRClient` directly, which enforces both gates.

This directly implements the [MCP scope minimization principle](https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices#scope-minimization): the LLM's initial and maximum scope covers only low-risk read/analysis operations; order-write elevation requires out-of-band human authentication that the LLM cannot trigger.

### Confused Deputy Prevention

The [confused deputy attack](https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices#confused-deputy-problem) occurs when a trusted intermediary is manipulated into using its elevated privileges on behalf of an attacker. In this system:

- The LLM (deputy) has no path to order execution regardless of instruction — no tool exists for it to call.
- `account_id` values from LLM-generated tool input are validated with a strict regex before use in URLs or database queries, preventing path-manipulation attacks:

```python
_ACCOUNT_ID_RE = re.compile(r"^[A-Z0-9]{4,12}$")
# Blocks values like "../../iserver/auth/status", "../.env", etc.
```

### Token Passthrough Prevention

The [token passthrough anti-pattern](https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices#token-passthrough) applies here as **data passthrough**: raw API responses, exception messages, and external service errors must not be forwarded to the LLM without sanitization, as they may contain attacker-controlled content from IBKR responses or strategy code.

All tool errors go through `_safe_error`, which maps exception types to controlled strings:

```python
def _safe_error(tool: str, exc: Exception) -> str:
    if isinstance(exc, IBKRAuthError):
        return f"Tool '{tool}' failed: IBKR session not authenticated. ..."
    if isinstance(exc, BacktestError):
        return f"Tool '{tool}' failed: {exc}"   # BacktestError messages are authored by us
    if isinstance(exc, FlexQueryError):
        return f"Tool '{tool}' failed: Flex query error."
    if isinstance(exc, IBKRAPIError):
        return f"Tool '{tool}' failed: IBKR API error."
    ...
    return f"Tool '{tool}' encountered an unexpected error."
```

Adversarial strategy code that raises exceptions with embedded payloads cannot inject text into the model context through this path. Raw IBKR API error bodies, Flex XML content, and Python runtime exception messages are never forwarded.

---

## Code Execution Security — Backtest Sandbox

Agent-submitted strategy code runs in a `RestrictedPython` sandbox. This implements the [MCP local server compromise mitigations](https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices#local-mcp-server-compromise): restricted file system access, restricted network access, and explicit resource limits.

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

This prevents reading arbitrary files via `pd.read_parquet`, writing files via `df.to_csv` on shared state, and poisoning the process-level module singletons.

### Resource limits

| Limit | Value | Error on breach |
|---|---|---|
| Code length | 4,096 characters | `BacktestSyntaxError` |
| Execution timeout | 10 seconds | `BacktestRuntimeError` (via `ThreadPoolExecutor.submit(...).result(timeout=10)`) |

### Residual risk

Strategy code can call `df.to_csv()` on its own DataFrame copy — this can write OHLCV data to a file but cannot access credentials or read arbitrary paths. Full elimination requires a subprocess with OS-level restrictions (`seccomp`, macOS sandbox, or Docker). The current implementation is appropriate for protecting against accidental or naive misuse by the LLM.

---

## Session Security

### Gateway Session

The IBKR Client Portal Gateway is bound to `localhost` by design — no cloud deployment is supported. This limits the session hijacking surface: an attacker must have local machine access.

Mitigations against [session hijacking](https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices#session-hijacking):

- `BrowserCookieAuth` re-reads the session cookie from Chrome's store on each client instantiation — there is no persistent server-side session store that can be enumerated or guessed.
- `TokenAuth` (headless mode) holds the cookie as a Python `str` in process memory. It is not written to disk.
- The cookie is not logged or included in any `repr()` output.
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

## Secrets Management

### API Keys and Tokens in Config

`anthropic_api_key` and `flex_token` are declared `field(repr=False)` in the `Config` dataclass:

```python
@dataclass
class Config:
    anthropic_api_key: str = field(repr=False)
    flex_token:        str = field(default="", repr=False)
```

Both fields are excluded from `repr()`, preventing accidental exposure in logs, tracebacks, and debug output.

### Credentials Never in Version Control

`.env`, `token.json`, and `credentials.json` must never be committed to the repository. The package loads credentials from environment variables only — never hardcoded defaults.

### OAuth Token File Permissions

The Google Drive OAuth refresh token file is written with `0o600` permissions immediately after creation:

```python
Path(self._config.gdrive_token_file).write_text(creds.to_json())
os.chmod(self._config.gdrive_token_file, 0o600)
```

This restricts read access to the file owner, preventing other local users from reading the refresh token.

### In-Memory Secrets

The IBKR session cookie is held in process memory as a Python `str`. Core dumps or heap inspections could expose it. This is unavoidable in Python without native memory management — no practical mitigation exists short of OS-level memory protection. Operators should ensure core dumps are disabled in production environments.

---

## Network Security

### SSRF Prevention (Flex Web Service)

The IBKR Flex Web Service returns a `<Url>` element used in a subsequent HTTP request. A MitM attacker or compromised IBKR endpoint could return `<Url>https://attacker.com/</Url>`, causing the Flex token to be sent as a query parameter to an attacker-controlled server.

Mitigation — strict allowlist prefix check before any request is made:

```python
_ALLOWED_URL_PREFIX = "https://gdcdyn.interactivebrokers.com/"

if not url.startswith(_ALLOWED_URL_PREFIX):
    raise FlexQueryError(f"Flex SendRequest returned unexpected URL: {url!r}")
```

This directly addresses the [SSRF attack class](https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices#server-side-request-forgery-ssrf) described in the MCP security guide, where attacker-controlled metadata is used to redirect HTTP requests to internal or credential-harvesting endpoints.

### TLS Policy

| Connection | TLS verification |
|---|---|
| IBKR Client Portal Gateway (`localhost:5055`) | `verify=False` — intentional; self-signed cert on loopback only |
| IBKR Flex Web Service (`gdcdyn.interactivebrokers.com`) | Standard TLS, no overrides |
| Google Drive API | Standard TLS via Google client library |

No external IBKR gateway connections are made with verification disabled.

### Rate Limiting and Retry Safety

The `with_retry` wrapper in `rate_limiter.py` provides two safety properties relevant to security:

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

### External API Response Validation

All IBKR API responses consumed by the package are validated through Pydantic v2 schemas in `models.py` before further processing:

```python
contract = Contract.model_validate(raw_dict)   # strict field types, alias normalization
position = Position.model_validate(raw_dict)
summary  = AccountSummary.model_validate(raw_dict)
```

This provides a typed boundary between untrusted external data and internal business logic.

### XML Parsing

`defusedxml.ElementTree` replaces stdlib `xml.etree.ElementTree` for all Flex XML parsing:

```python
import defusedxml.ElementTree as ET
root = ET.fromstring(resp.content)
```

The stdlib parser does not resolve external entities (no XXE) but does process entity expansion, making it vulnerable to billion-laughs-style memory exhaustion. `defusedxml` blocks both classes of XML attack.

### SQLite Store

Trades, signals, backtest results, and position snapshots are stored in a local SQLite database. No encryption at rest is applied — OS filesystem permissions are the primary control. The database file should be stored in a user-owned directory (e.g., `~/.ibkr_core/`) with `0o600` permissions.

### Google Drive Parquet Cache

Market data parquet files are stored in a user-specified Google Drive folder. The OAuth token file is `chmod 0o600` after write. `GDRIVE_TOKEN_FILE` and `GDRIVE_CREDENTIALS_FILE` paths must never be committed to version control.

---

## Security Architecture — Defense in Depth

No single control is the sole barrier. Each threat has layered mitigations:

| Threat | Primary control | Secondary control |
|---|---|---|
| LLM triggers order execution | No order-write tools in `ClaudeToolkit` | Two-gate human auth enforced at innermost call site |
| LLM supplies malicious account ID | `_validate_account_id` regex (`^[A-Z0-9]{4,12}$`) | `_safe_error` prevents exception details reaching LLM |
| Prompt injection via exception messages | `_safe_error` maps all exceptions to controlled strings | `BacktestError` messages authored by the package itself |
| Sandbox escape via file I/O | Safe `SimpleNamespace` wrappers for `pd`/`np` | Custom `_write_guard` blocks namespace mutation |
| Sandbox DoS (infinite loop / large allocation) | 10-second execution timeout | 4,096-character code length cap |
| SSRF via Flex URL field | Domain allowlist prefix check | HTTPS enforced on all external connections |
| Credential exposure in logs | `repr=False` on `anthropic_api_key`, `flex_token` | Credentials loaded from env vars only, never hardcoded |
| OAuth token readable by other users | `os.chmod(token_file, 0o600)` after write | Token file path user-configurable, not world-accessible by default |
| XML bomb DoS | `defusedxml` blocks entity expansion | Flex polling bounded to 5 retries |
| SQL injection | Parameterized queries throughout `store.py` | LLM input validated before reaching query construction |
| Unauthenticated session on cookie failure | `warnings.warn` on extraction error (not silent) | `browser_cookie3` access restricted to allowlisted browser names |
| Session credential exposure in 401 retry | 401 raises `IBKRAuthError` immediately, never retried | — |

---

## Contributor Security Rules

The following rules are enforced at PR review. Any PR that violates them will be rejected:

1. **Never add a bypass flag, session cache, or fallback** to `require_touch_id` or any order confirmation function.
2. **Never move the gates out of `IBKRClient`** — enforcement must be at the innermost call site inside `place_order`, `modify_order`, `cancel_order`, `reply_order`.
3. **Never add a password or PIN fallback** — `LAPolicyDeviceOwnerAuthenticationWithBiometrics` is the required policy.
4. **Never add order-write tools to `ClaudeToolkit`** — the LLM must not have a path to order execution.
5. **Never forward raw exception messages to the LLM** — use `_safe_error` for all tool error returns.
6. **Never pass unsanitized LLM input to URLs or SQL** — validate with `_validate_account_id` or equivalent before use.
7. **Never use string concatenation in SQL queries** — all user-supplied values must be passed as bind parameters.
8. **Never use stdlib `xml.etree.ElementTree` for external XML** — use `defusedxml.ElementTree`.

---

## Audit History

| Date | Commit | Scope | Outcome |
|---|---|---|---|
| 2026-05-25 | `4dbe6ad` | All production modules | 2 Critical, 5 High, 5 Medium resolved. 3 Low/Info accepted. |
| 2026-05-25 | `5f7b5ab` | `flex_query.py` | URL validation, datetime error handling hardened. |

Full audit report: [`docs/security-audit-2026-05-25.md`](docs/security-audit-2026-05-25.md)
