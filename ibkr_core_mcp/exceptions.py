"""Exception hierarchy for ibkr_core_mcp.

Every error this package *raises for itself* derives from `IBKRCoreError`, so a caller can
catch the whole surface with one `except` and still discriminate on the subclass
when it needs to. The split exists because the recovery differs per class:
`IBKRAuthError` means re-authenticate, `IBKRRateLimitError` means back off,
`HumanAuthError` means a security gate was declined and must not be retried
automatically, and `ConfigError` means the caller's environment is wrong.

**A dependency's exception is a different thing, and this sentence used to cover it by
implication.** It read "Every error raised by this package" until 2026-09-17, while a 200
response carrying a non-JSON body — the HTML page the Client Portal Gateway serves once its
session lapses — left `IBKRClient` as `requests.exceptions.JSONDecodeError`, outside this
hierarchy, with a message naming neither the endpoint nor what arrived (audit finding
API-15). That one is converted at the boundary now: `client._decode` is the single place a
response is decoded, and it raises `IBKRAPIError`. Where this package wraps a dependency
whose failure the caller must act on, wrap it at the boundary and add the subclass here
rather than widening this claim.
"""


class IBKRCoreError(Exception):
    """Base exception for all ibkr_core_mcp errors."""


class IBKRAuthError(IBKRCoreError):
    """Session not authenticated or cookie extraction failed."""


class IBKRRateLimitError(IBKRCoreError):
    """Gateway returned 429 or 503 and retries are exhausted; `.status_code` says which.

    On a 429 the IP is in IBKR's fifteen-minute penalty box, for every endpoint. The pacer that
    should have prevented it (`rate_limiter.EndpointPacer`) budgets per process while IBKR
    counts per IP, so the first suspect is another process on this machine — a script, a test
    run, the MCP server — talking to the same gateway; the second is this process having been
    warned that a call was over the limit and sent anyway (the pacer never holds a call longer
    than 65 s). A 503 is the gateway being unavailable and means neither.
    """

    def __init__(self, message: str, status_code: int = 0) -> None:
        """Record the message and the HTTP status that exhausted the retries.

        Args:
            message: Human-readable description of the failure.
            status_code: 429 or 503 from the gateway; 0 when unknown, so callers can branch
                on it without it ever being None — the same contract as `IBKRAPIError`.
        """
        super().__init__(message)
        self.status_code = status_code


class IBKRAPIError(IBKRCoreError):
    """Non-auth HTTP error from the IBKR gateway."""

    def __init__(self, message: str, status_code: int = 0) -> None:
        """Record the message and the originating HTTP status.

        Args:
            message: Human-readable description of the failure.
            status_code: HTTP status from the gateway; 0 when unknown, so callers
                can branch on the code without it ever being None.
        """
        super().__init__(message)
        self.status_code = status_code


class CacheError(IBKRCoreError):
    """Base cache error."""


class CacheMissError(CacheError):
    """Requested data not in Drive cache."""


class CacheWriteError(CacheError):
    """Failed to write to Drive cache."""


class StoreError(IBKRCoreError):
    """SQLite store error."""


class BacktestError(IBKRCoreError):
    """Base backtest error."""


class BacktestSyntaxError(BacktestError):
    """Strategy code has a syntax error."""


class BacktestRuntimeError(BacktestError):
    """Strategy code raised an exception at runtime."""


class ConfigError(IBKRCoreError):
    """Missing or invalid configuration."""


class HumanAuthError(IBKRCoreError):
    """Raised when Touch ID is denied, times out, unavailable, or the user cancels the confirmation dialog."""


class OrderValidationError(IBKRCoreError, ValueError):
    """Raised when this package refuses an order write because it would break a safety rule.

    Not a broker rejection and not a human declining: the library itself is refusing to send
    the request. Today that means H1 — a bracket child may never be larger than the position
    its parent actually created (`IBKRClient.modify_order`).

    **It inherits from both `IBKRCoreError` and `ValueError` on purpose**, and each parent is
    load-bearing:

    - `IBKRCoreError` is the base `exceptions.py` tells every caller to catch, and a refusal
      that escaped it would surface as an unhandled crash in a host app.
    - `ValueError` is what `IBKRClient._bracket_tickets` already raises for the SAME rule at
      submission time, and what `docs/order-management-examples.md` shows callers catching.
      One rule broken on two paths must not need two `except` clauses.

    The distinct NAME matters as much as the bases. Raising `HumanAuthError` here would have
    been type-correct — it is an `IBKRCoreError`, and `confirm_bracket_dialog` uses it for
    this very rule — but a consuming app classifies failures by exception type name, and
    claudia_ui's would have reported this refusal to the operator as "Touch ID authentication
    failed or was cancelled" (`order_flow._FAILURE_PATTERNS`, read 2026-09-22). The human
    authenticated perfectly well; the library declined the order. A wrong explanation on a
    refused order write sends the operator to debug the wrong thing.
    """


class FlexQueryError(IBKRCoreError):
    """Raised when a Flex Query request fails, times out, or returns unexpected XML."""


class StreamingError(IBKRCoreError):
    """Raised when the IBKR WebSocket connection fails or returns an unexpected message."""


class GatewayError(IBKRCoreError):
    """Raised when the IBKR Client Portal Gateway cannot be started or reached."""
