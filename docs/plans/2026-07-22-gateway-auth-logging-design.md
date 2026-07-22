# Design: Fix silent exception-swallowing in `GatewayManager`

**Date:** 2026-07-22
**Status:** Approved, ready for implementation plan

## Problem

`GatewayManager.is_authenticated()` and `GatewayManager.is_gateway_reachable()`
(`ibkr_core_mcp/gateway/manager.py`) both catch broad exceptions and silently
return `False`, with no logging at all. Flagged in the 2026-07-15 code-quality
audit (`is_authenticated()` only) and re-verified directly on 2026-07-22
(`docs/audits/...` — see [[project_code_quality_audit_2026_07_15]] memory):

```python
def is_gateway_reachable(self) -> bool:
    try:
        resp = requests.post(f"{self._api_url}/tickle", verify=False, timeout=3)
        return 200 <= resp.status_code < 600
    except Exception:
        return False

def is_authenticated(self) -> bool:
    with contextlib.suppress(Exception):
        resp = requests.get(f"{self._api_url}/iserver/auth/status", verify=False, timeout=5)
        if resp.status_code == 200:
            return bool(resp.json().get("authenticated", False))
    return False
```

A DNS blip, a connection refused, a malformed response body, and a genuinely
dead IBKR session are all indistinguishable to anyone debugging a failed
`wait_for_auth()` timeout — every path collapses to the same silent `False`.

## Scope confirmation — what this does NOT touch

Explicitly verified before starting, because losing gateway keepalive would be
a serious regression:

- **`caffeinate` sleep-prevention** lives entirely in the sibling `claudia_ui`
  repo (`scripts/ibkr-keepalive.sh`), a standalone bash script that `curl`s
  `/tickle` directly. It never imports `ibkr_core_mcp` or calls any Python in
  this package.
- **`ConnectivityChecker`**'s 60s keepalive poll (claudia_ui) calls
  `IBKRClient.tickle()` / `IBKRClient.get_auth_status()` in
  `ibkr_core_mcp/client.py` — a different file and class from what this design
  touches.
- **`tickler.sh`** (runs inside the gateway's own Docker container, launched
  by `run_gateway.sh`) is a plain shell script using `curl` directly — no
  Python, no `GatewayManager` involvement.

`GatewayManager.is_authenticated()` / `is_gateway_reachable()` are called only
by `GatewayManager`'s own one-time bring-up flow: `startup()` (its fast-path
check and its final retry check) and `wait_for_auth()` / `wait_for_gateway()`
(via `_poll_until`). None of the three keepalive mechanisms above call either
method. This fix cannot affect long-running session keepalive.

## Design decisions (confirmed with the project owner)

1. **Scope:** fix both `is_authenticated()` and `is_gateway_reachable()` —
   identical anti-pattern, same file; fixing one and leaving the other stale
   just moves the gap next door.
2. **Return contract: unchanged.** Both stay `-> bool`. No caller — including
   `_poll_until`'s `Callable[[], bool]` parameter, `startup()`, or any
   downstream consumer (claudia_ui) — needs to change. This is a pure
   observability fix, not an API change.
3. **Logging, split by what the failure actually means:**

   | Condition | Level | Rationale |
   |---|---|---|
   | `requests.exceptions.RequestException` (connection refused, timeout, DNS failure) | `log.debug` | Expected/routine while a gateway container is still coming up — `wait_for_auth()` polls every 5s for up to 300s (~60 calls), so this must not be noisy by default |
   | Non-200 HTTP status from `/iserver/auth/status` (currently silent — not even an exception path today) | `log.warning` | The gateway responded but not with success; worth surfacing by default, not routine |
   | Any other exception (malformed JSON body, unexpected response shape) | `log.warning` | Genuinely unexpected — the original audit's core complaint |
   | 200 + `authenticated: false` | *(no log)* | The correct, unambiguous "not authenticated yet" signal. Not opaque — nothing to add. Test asserts explicitly that this path logs nothing, locking in that this is a deliberate omission, not an oversight |

   `is_gateway_reachable()` gets the same two-tier split
   (`RequestException` → debug, anything else → warning). It has no
   JSON-parsing step, so there's no third "unexpected shape" branch there —
   its return logic (`200 <= status < 600`) already treats any HTTP response
   at all as "reachable."

4. **Why no rate-limiting/state-transition dedup** (unlike claudia_ui's
   `ibkr-keepalive.sh`, which deliberately logs only on OK↔WARN transitions):
   that script runs indefinitely under `launchd`, so unbounded per-tick
   logging would grow a log file forever. `wait_for_auth()` is bounded —
   worst case ~60 log lines over one 300s bring-up attempt, then it returns.
   That's not log spam by any reasonable standard, so no dedup logic is
   introduced here. Noted explicitly so a future reader doesn't wonder why
   the two mechanisms differ.

## Implementation

```python
def is_gateway_reachable(self) -> bool:
    """True if the Java process is accepting HTTP (not necessarily authenticated).

    Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
    Endpoint: POST /tickle
    """
    try:
        resp = requests.post(
            f"{self._api_url}/tickle",
            verify=False,
            timeout=3,
        )
        return 200 <= resp.status_code < 600
    except requests.exceptions.RequestException as exc:
        log.debug("Gateway not reachable yet: %s", exc)
        return False
    except Exception as exc:
        log.warning("Unexpected error checking gateway reachability: %s", exc)
        return False

def is_authenticated(self) -> bool:
    """True if the gateway holds an active authenticated IBKR session.

    Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
    Endpoint: GET /iserver/auth/status
    """
    try:
        resp = requests.get(
            f"{self._api_url}/iserver/auth/status",
            verify=False,
            timeout=5,
        )
    except requests.exceptions.RequestException as exc:
        log.debug("Auth status check failed (gateway unreachable): %s", exc)
        return False
    except Exception as exc:
        log.warning("Unexpected error checking auth status: %s", exc)
        return False

    if resp.status_code != 200:
        log.warning("Auth status endpoint returned HTTP %d", resp.status_code)
        return False

    try:
        return bool(resp.json().get("authenticated", False))
    except Exception as exc:
        log.warning("Auth status response was not valid JSON: %s", exc)
        return False
```

`import contextlib` is removed from the top of `gateway/manager.py` — its only
use (the `with contextlib.suppress(Exception):` in the old `is_authenticated`)
disappears. Ruff would flag it as unused (`F401`) otherwise.

Exception-clause ordering matters: `requests.exceptions.RequestException` must
be caught before the bare `Exception` fallback in each `try`, since Python
evaluates `except` clauses top-to-bottom and `RequestException` is itself a
subclass of `Exception`.

## Test plan

No existing test in this repo asserts on log output (`caplog` is unused
anywhere in `tests/`) — this introduces that pattern for the first time, using
pytest's built-in `caplog` fixture, scoped to
`caplog.at_level(logging.DEBUG, logger="ibkr_core_mcp.gateway.manager")` so
assertions target this module's logger specifically.

`tests/test_gateway.py` — `TestIsGatewayReachable`:
- `test_returns_true_on_200` — unchanged.
- `test_returns_true_on_any_http_response` — unchanged.
- `test_returns_false_on_connection_error` — extend: assert the returned
  `False` **and** assert exactly one `DEBUG`-level record was emitted, none at
  `WARNING` or above.
- New: `test_returns_false_and_warns_on_unexpected_exception` — mock
  `requests.post` to raise a non-`RequestException` (e.g. `ValueError`);
  assert `False` **and** a `WARNING`-level record.

`tests/test_gateway.py` — `TestIsAuthenticated`:
- `test_returns_true_when_authenticated_flag_set` — unchanged.
- `test_returns_false_when_not_authenticated` — extend: assert `False` **and**
  assert **no** log records at all were emitted for this call — locks in that
  the 200+`authenticated:false` path is deliberately silent, not an oversight.
- `test_returns_false_on_exception` — replaced by two tests, since the old
  bare `Exception("network error")` mock doesn't distinguish the two new
  branches:
  - `test_returns_false_and_debug_logs_on_connection_error` — mock
    `requests.get` with `side_effect=requests.ConnectionError()` (a real
    `RequestException`); assert `False` + one `DEBUG` record, no `WARNING`.
  - `test_returns_false_and_warns_on_unexpected_get_exception` — mock
    `requests.get` with `side_effect=RuntimeError("boom")` (not a
    `RequestException`); assert `False` + one `WARNING` record.
- New: `test_returns_false_and_warns_on_malformed_json` — mock a 200 response
  whose `.json()` raises (e.g. `side_effect=ValueError("bad json")`); assert
  `False` + one `WARNING` record. Exercises the inner try/except around
  `resp.json()` specifically, distinct from the outer `requests.get()`
  exception handler.
- `test_returns_false_on_non_200_status` — extend: assert `False` **and** one
  `WARNING` record (this is the previously-silent branch the original audit
  flagged as opaque).

## Verification

1. `ruff check .` clean (confirms `contextlib` import removal doesn't leave
   anything else unused, and no other lint regressions).
2. `mypy` clean (no type changes, but re-run as part of the standard safety
   net).
3. `pytest tests/test_gateway.py -v` — all tests pass, including the new/split
   ones.
4. `pytest -m "not integration" -q` — full suite green, count at or above the
   current 747 baseline. Net new: the old `test_returns_false_on_exception`
   splits into 2 tests (+1 net), plus 2 wholly new tests
   (`test_returns_false_and_warns_on_unexpected_exception` in
   `TestIsGatewayReachable`, `test_returns_false_and_warns_on_malformed_json`
   in `TestIsAuthenticated`) — **750 total, +3 net**.
5. Manual read-through confirming no caller of either method changed
   (`_poll_until`, `startup()`, `wait_for_gateway()`, `wait_for_auth()`) — this
   is a zero-behavior-change, logging-only fix.

## Out of scope

- Changing `is_authenticated()`/`is_gateway_reachable()`'s return type to a
  richer status enum — explicitly declined; would be a breaking API change
  for every caller including claudia_ui, disproportionate to what this fix
  needs.
- Any change to `claudia_ui`'s `ibkr-keepalive.sh`, `ConnectivityChecker`, or
  `tickler.sh` — none of them call the methods this design touches.
- Rate-limiting or state-transition-dedup logging (see decision 4 above) — not
  needed given `wait_for_auth()`'s bounded call count.
