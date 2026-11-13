"""The gateway session's readings and the rule that turns one into a verdict — read-only.

    python -m ibkr_core_mcp.gateway preflight      # the verdict, before touching the login page

## Why this exists

Only **one** brokerage session exists per username across all IBKR services — Client
Portal, TWS and IBKR Mobile all claim the same one
(https://www.interactivebrokers.com/docs/web-api/authentication/multiple-sessions.md). Repeated logins
are what escalate into the IB Key challenge/response, so the cheapest fix is to stop
logging in when you do not have to. Every function here is a read; the one rule is
`verdict`, and the session owner's `classify` is its mirror.

## What this diagnosed, 2026-08-05

A login that failed every time for days, with a correctly-formatted 8-digit response code
and the right username. `/tickle` alone could not explain it and actively misled:

    userId      populated        -> looks like a good session
    ssoExpires  renewing         -> looks alive
    competing   FALSE            -> looks uncontested
    authStatus  authenticated:false, connected:false

`/sso/validate` gave the answer in one field: ``CLIENT_APP: "IBKRMOBILE_000.a-000"``. The
gateway was holding a session **issued to the phone**, which it cannot authenticate as, so
every retry was doomed before it started. `competing` was false because the gateway never
got far enough to register a claim — the flag describes a fight, and there was no fight.

Two follow-ons, both measured rather than reasoned about:

* `POST /iserver/auth/ssodh/init` moved `connected` False->True and left `authenticated`
  False, twice. It raises the bridge; it cannot supply an authentication that never
  happened.
* `POST /logout` returned ``{"status": true}`` and the session came straight back with a
  full 10-minute window — because three separate ticklers (the gateway container's own
  `tickler.sh`, a host launchd keepalive, and the host's connectivity poll) each renewed it
  every 60 seconds. The keepalive built to protect a good session cannot tell a good one
  from a borrowed one, and had been preserving an unusable session all day. What cleared
  it was a restart of the container (`python -m ibkr_core_mcp.gateway reset`).

## What this CANNOT see — measured 2026-08-06

**A session held by another IBKR app is invisible here until the gateway itself holds
one.** With a live IBKR Mobile login in progress on the same username, `/tickle` and
`/sso/validate` both answered **401** and this check reported **FREE**.

That is not the same condition as `EXIT_BORROWED`, and conflating them would be a
serious misreading:

| Condition | What holds the session | Visible before a login? |
|---|---|---|
| `EXIT_BORROWED` | the **gateway**, holding an SSO session stamped `CLIENT_APP: IBKRMOBILE…` | yes, in `/sso/validate` |
| Another app logged in | **that app**, independently; the gateway holds nothing | **no** |

So `EXIT_FREE` means "the gateway holds nothing", never "a login will succeed" — the
wording of its guidance says exactly that, and must keep saying it. IBKR's own advice for
the collision is to log out of the other app first — which is a step this check can
recommend but can never verify in advance.

## What the HTTP side cannot see and the gateway's own log can — 2026-10-12

**A login IBKR refused.** `/tickle` and `/sso/validate` answer 401 after it exactly as when
nobody has logged in, so the HTTP verdict is FREE: during the five refused logins of
2026-10-07/08 this check read FREE ("a login can proceed"). The gateway's own log records the
refusal, and the callers read it after a FREE reading — `refine_with_log` over the manager's
`read_login_events`, where the process spawn lives — to answer `EXIT_REFUSED` or
`EXIT_VALIDATING`. `verdict` itself never reads the log and never returns either, so it stays
the mirror of the owner's `classify`.

## Read-only, and pinned

`read_state` issues **two GETs and nothing else** — `/tickle` for whether *a* session is
authenticated, `/sso/validate` for **whose** it is. It never posts, which
`test_read_state_reads_both_endpoints_and_writes_to_neither` pins: a check that can
establish or destroy a session is not a check, and re-authenticating speculatively is what
breaks a fresh login. `confirm_session` is the third read, `GET /portfolio/accounts`: the
data half's own prerequisite, and the proof a session serves data.

The one side effect the GETs do have is benign: `/tickle` resets the keepalive timer,
exactly as every other request does. Reading can extend a session's life, never shorten it.

Every request here disables certificate verification — the gateway serves a self-signed
certificate on this machine — so every request is preceded by `require_loopback_url`
(register F45, condition C; `tests/security/test_tls_policy.py`), and every exception that
becomes a reading passes `redact_error` (condition G): a `requests` error carries its URL.
"""

from __future__ import annotations

import logging
import os
import re
import warnings
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, NamedTuple

import requests
import urllib3

from ibkr_core_mcp.config import Config, require_loopback_url
from ibkr_core_mcp.redaction import redact_error

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class GatewayState:
    """One reading of the gateway's session, typed. Fields default to "unknown", not False.

    Merges the two endpoints because neither answers the question alone: `/tickle` supplies
    `authenticated`/`connected`/`competing`/`collision`, and `/sso/validate` supplies
    `client_app`/`sso_user`/`sso_valid`.

    `reachable` False means the HTTP call never produced a usable body, so every other
    field is meaningless — the caller must check it first. "The gateway said no session" and
    "the gateway did not answer" are opposite claims and lead to opposite actions.

    An unreadable `/sso/validate` degrades to empty strings rather than failing the whole
    read: the `/tickle` half is still worth having, and a missing owner simply means the
    borrowed-session verdict cannot fire — never that it fires wrongly.

    `user_id` and `sso_user` are carried for the rule and never printed by anything in this
    package: the user id has no reader who acts on it, and the username appears only in the
    BORROWED verdict, where it says whose session the gateway is holding.
    """

    reachable: bool
    authenticated: bool = False
    connected: bool = False
    competing: bool = False
    collision: bool = False
    user_id: int | None = None
    sso_expires_ms: int | None = None
    detail: str = ""
    # From /sso/validate. `client_app` is the field that actually explains a stuck login:
    # measured 2026-08-05 it read "IBKRMOBILE_000.a-000" while the gateway sat at
    # authenticated=False — the gateway was holding the phone's SSO session, which it
    # cannot authenticate as. Nothing in /tickle exposes this, which is why every other
    # signal looked contradictory (userId set, ssoExpires renewing, competing=false).
    client_app: str = ""
    sso_user: str = ""
    sso_valid: bool = False


# Exit codes — distinct so this can gate a shell script, not just inform a human.
EXIT_READY = 0  # a working session already exists; do NOT log in again
EXIT_UNREACHABLE = 1  # gateway process is not answering at all
EXIT_FREE = 2  # nothing holds the session; a login now should succeed
EXIT_CONTESTED = 3  # another IBKR client holds it; logging in now starts a fight
EXIT_BORROWED = 4  # the gateway holds an SSO session issued to a different client app
# The two below refine a FREE reading from the gateway's own log (`refine_with_log`);
# `verdict` never returns them, so it stays the HTTP reading's mirror of the owner's `classify`.
EXIT_REFUSED = 5  # IBKR refused the last login; a website login, then one gateway login
EXIT_VALIDATING = 6  # IBKR is still answering the last login; do NOT log in again

_MARK = {
    EXIT_READY: "OK",
    EXIT_UNREACHABLE: "DOWN",
    EXIT_FREE: "FREE",
    EXIT_CONTESTED: "BUSY",
    EXIT_BORROWED: "BORROWED",
    EXIT_REFUSED: "REFUSED",
    EXIT_VALIDATING: "VALIDATING",
}
"""Each code's one word, as the command line prints it in brackets — kept beside the codes."""


def read_state(gateway_url: str, timeout: float = 5.0) -> GatewayState:
    """Read the session state. Never writes; never raises for a gateway condition.

    Args:
        gateway_url: Base URL including the `/v1/api` suffix, e.g. `gateway_api_url()`.
        timeout: Seconds to wait. Short — an unreachable gateway is a normal answer here,
            not an exceptional one.

    Returns:
        A `GatewayState`. On any failure to reach or parse, `reachable` is False and `detail`
        carries the reason (through `redact_error`), rather than an exception reaching the
        caller: this runs when things are already broken, so it has to survive that.

    Raises:
        ConfigError: `gateway_url` is not a loopback host — a programming error, since the URL
            came from `gateway_api_url` or a `Config`; raised before any request.
    """
    require_loopback_url(gateway_url)
    try:
        # The gateway serves a self-signed cert on localhost; the warning it raises is
        # noise on every single call and would bury the caller's actual output.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", urllib3.exceptions.InsecureRequestWarning)
            resp = requests.get(f"{gateway_url}/tickle", timeout=timeout, verify=False)  # noqa: S501 - localhost gateway, self-signed cert; pinned above (SECURITY.md § TLS Policy)
    except Exception as exc:
        return GatewayState(reachable=False, detail=redact_error(exc))

    if resp.status_code == 401:
        # 401 is the gateway ANSWERING, not failing: it is alive and holds no authenticated
        # session — exactly the state a freshly started or freshly logged-out gateway is in,
        # and the best possible moment to log in. Folding it into `reachable=False` told the
        # user "Gateway is NOT answering. Start it first" about a gateway that was running
        # perfectly and waiting for them (measured 2026-08-05, straight after a container
        # restart). "Did not answer" and "answered, saying no session" are opposite claims
        # and lead to opposite actions.
        return GatewayState(reachable=True, detail="HTTP 401 — no session yet")
    if resp.status_code != 200:
        return GatewayState(reachable=False, detail=f"HTTP {resp.status_code}")
    try:
        body = resp.json()
    except Exception as exc:
        return GatewayState(reachable=False, detail=f"unparseable body: {redact_error(exc)}")

    auth = (body.get("iserver") or {}).get("authStatus") or {}
    sso = _read_sso(gateway_url, timeout)
    return GatewayState(
        reachable=True,
        authenticated=bool(auth.get("authenticated")),
        connected=bool(auth.get("connected")),
        competing=bool(auth.get("competing")),
        # IBKR spells it "collission" on the wire. Kept verbatim on the read side and
        # corrected on ours, rather than propagating a typo through the codebase.
        collision=bool(body.get("collission")),
        user_id=body.get("userId"),
        sso_expires_ms=body.get("ssoExpires"),
        client_app=str(sso.get("CLIENT_APP") or ""),
        sso_user=str(sso.get("USER_NAME") or ""),
        sso_valid=bool(sso.get("RESULT")),
    )


def _read_sso(gateway_url: str, timeout: float) -> dict[str, Any]:
    """`GET /sso/validate`, or `{}` if it cannot be read. Read-only.

    Separate from `/tickle` because it answers a different question: `/tickle` says whether
    *a* session is authenticated, this says **whose** it is. That distinction is the whole
    reason a stuck login is diagnosable at all.
    """
    require_loopback_url(gateway_url)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", urllib3.exceptions.InsecureRequestWarning)
            resp = requests.get(f"{gateway_url}/sso/validate", timeout=timeout, verify=False)  # noqa: S501 - localhost gateway, self-signed cert; pinned above (SECURITY.md § TLS Policy)
        if resp.status_code != 200:
            return {}
        body = resp.json()
        # `resp.json()` returns whatever parsed — a bare string or list is valid JSON, and
        # calling `.get` on one raised AttributeError straight out of `read_state`, whose
        # contract is that it never raises. An unexpected shape is exactly what a gateway
        # in a strange state emits, which is when this runs.
        return body if isinstance(body, dict) else {}
    except Exception:
        return {}


def confirm_session(url: str, timeout: float = 10.0) -> tuple[bool, str]:
    """Prove the session serves data, and satisfy the portfolio prerequisite in one call.

    `authStatus.authenticated` describes the brokerage session. The portfolio endpoints
    are a different subsystem with their own documented precondition:

        "/portfolio/accounts or /portfolio/subaccounts must be called prior to this
        endpoint."
        — https://www.interactivebrokers.com/docs/web-api/v1/endpoints/portfolio/portfolio-ledger.md

    So this one GET does double duty: it is the evidence that a login produced something
    usable rather than merely an authenticated flag, and it is that prerequisite call,
    made deliberately at login time instead of implicitly by whichever poll happened to
    run first.

    Returns `(ok, detail)` and never raises for a gateway condition — a half-established
    session is an ordinary outcome here, and the caller has to report it rather than crash
    on it. The detail names the account ids found: they are the operator's own and not
    secrets under this package's policy. A non-loopback `url` raises `ConfigError` before
    any request, as `read_state` does.
    """
    require_loopback_url(url)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", urllib3.exceptions.InsecureRequestWarning)
            resp = requests.get(f"{url}/portfolio/accounts", timeout=timeout, verify=False)  # noqa: S501 - localhost gateway, self-signed cert; pinned above (SECURITY.md § TLS Policy)
    except Exception as exc:
        return False, redact_error(exc)
    if resp.status_code != 200:
        return False, f"/portfolio/accounts returned HTTP {resp.status_code}"
    try:
        body = resp.json()
    except Exception as exc:
        return False, f"/portfolio/accounts body was not JSON: {redact_error(exc)}"
    if not isinstance(body, list) or not body:
        return False, "/portfolio/accounts returned no accounts"
    ids = [str(a.get("accountId") or "") for a in body if isinstance(a, dict)]
    return True, f"account(s) {', '.join(i for i in ids if i) or 'unnamed'}"


def verdict(state: GatewayState) -> tuple[int, str, str]:
    """Turn a state into (exit code, headline, what to do next).

    Ordered most-actionable first. The `authenticated and connected` case is checked
    before everything else on purpose: it is the one where the correct action is to do
    *nothing*, and it is the one a person is most likely to override out of habit.
    """
    if not state.reachable:
        return (
            EXIT_UNREACHABLE,
            "Gateway is NOT answering",
            f"{state.detail}. Start it first — the login page will not load either.",
        )

    if state.authenticated and state.connected:
        return (
            EXIT_READY,
            "Session is LIVE — do not log in again",
            "Everything is already authenticated. Opening the login page now would "
            "re-authenticate for nothing, and a needless re-login is what escalates into "
            "the IB Key challenge/response.",
        )

    if state.competing or state.collision:
        return (
            EXIT_CONTESTED,
            "Another IBKR client holds the session",
            "IBKR Mobile, TWS or a Client Portal tab is using the single brokerage "
            "session this username gets. Fully close it, re-run this check, and log in "
            "only once it reads FREE — logging in now evicts it and starts the tug-of-war.",
        )

    # Checked before the generic not-authenticated cases: when a valid SSO session exists
    # but the gateway is not authenticated, *whose* session it is explains the whole
    # failure, and no amount of retrying the login page fixes it.
    if state.sso_valid and not state.authenticated and state.client_app:
        return (
            EXIT_BORROWED,
            f"SSO session belongs to {state.client_app}",
            f"The gateway is holding a session that was issued to {state.client_app} "
            f"(user {state.sso_user or 'unknown'}), so it cannot authenticate as itself — "
            "which is why the login is rejected however many times it is retried. Log out "
            "of that app properly (the Log Out menu item; closing or swiping it away "
            "leaves the server-side session alive), then re-run this. If it persists, "
            "`python -m ibkr_core_mcp.gateway reset` restarts the container, which is what "
            "cleared a borrowed session on 2026-08-05 — `POST /logout` did not.",
        )

    if state.connected and not state.authenticated:
        return (
            EXIT_FREE,
            "Bridge up, but NOT authenticated",
            "IBKR's documented soft-timeout signature. The gateway is talking to IBKR but "
            "the login has not completed. `ssodh/init` raises the bridge and nothing more "
            "— it cannot supply an authentication that never happened, so this state still "
            "needs the login page. Measured 2026-08-05: two inits moved connected "
            "False->True and left authenticated False both times.",
        )

    if state.user_id and not state.connected:
        return (
            EXIT_FREE,
            "SSO alive, brokerage session NOT established",
            # The user id is not printed (2026-10-12): no reader acts on the number, and this
            # text is pasted into records. The username stays where it is shown — it says
            # whose session a borrowed one is.
            "IBKR knows your user but no brokerage session exists, and "
            "nothing is competing for it. This is the good moment to log in: complete the "
            "page through to 'Client login succeeds'.",
        )

    return (
        EXIT_FREE,
        "The gateway holds no session",
        "Nothing here holds a session, so a login can proceed. Note that a session held "
        "by another IBKR app is NOT visible from here — measured 2026-08-06, a live IBKR "
        "Mobile login left /tickle and /sso/validate both answering 401 and this check "
        "reading FREE. Only one brokerage session exists per username, so if the login "
        "is rejected, close TWS / IBKR Mobile / any Client Portal tab and try once more.",
    )


# ── Was the last login refused? The gateway's internal log ──────────────────────────────
#
# Nothing on the HTTP side tells a login IBKR refused from no login at all: `/tickle` and
# `/sso/validate` answer 401 in both, so the verdict above reads FREE ("a login can
# proceed") straight after a refusal — the 2026-10-07/08 incident, five refused logins. The
# only evidence is the gateway's own log, read in-container by the manager's
# `read_login_events` and reduced here to time, event and code.

LOGIN_PHRASES = {
    "Client login succeeds": "login",
    "sso/validate?gw=1,": "validate",
    "authentication to cp failed, retry": "retry",
    "authenticated to cp": "authenticated",
    "giving up": "giving up",
    "ssodh/init,": "ssodh/init",
}
"""The six phrases a login leaves in the gateway's log, verbatim, each with its event name.

Measured 2026-10-12 over the incident container's own files (2026-10-07 → 10-13) and the
redacted archive, which agree event for event: no line carries two of them, and every line
that carries one starts with its time. A refused login is `login → validate 401 → retry 1…5
→ giving up` within 13 s (a repeat attempt gives up at once, the retry counter carrying
on); a good one is `login → validate 200 → authenticated`, then `ssodh/init 200` about 5 s
later. "Client login succeeds" is written one second BEFORE IBKR is asked, so it is not a
session. No phrase contains another ("authentication to cp failed" is not "authenticated
to cp"), so a line matches at most one and the order of this table decides nothing.
"""

_LOG_LINE = re.compile(r"gw\.(\d{4}-\d{2}-\d{2})\.log:(\d{2}:\d{2}:\d{2})")
# `grep -H` prefixes each line with its file, `gw.<UTC date>.log`; the line starts with its UTC time.


class LoginEvent(NamedTuple):
    """One phrase from the gateway's log, reduced to when, what and its code. Nothing else."""

    at: str  # "YYYY-MM-DD HH:MM:SS" UTC: the file's date and the line's time
    event: str  # a value of `LOGIN_PHRASES`
    code: str  # the HTTP status of validate / ssodh/init, the retry number, else ""


def login_events(grep_output: str) -> list[LoginEvent]:
    """Reduce `grep -HF` output over the gateway's dated log files to `LoginEvent`s.

    The log carries the username, a numeric user id, session cookies, a MAC address and
    device ids, verbatim. This is where they stop: each line becomes its date, time, event
    and code, and the rest of it is dropped here, before anything can log, print or store it
    (OWASP Logging Cheat Sheet, "Data to exclude"). Returned in time order, whatever order
    the files were read in.

    Raises:
        ValueError: A line carries a phrase but no leading time. All 93 measured do, so the
            format has changed — and skipping the line would let `last_login` answer about an
            older login (a fresh refusal read as the previous login's "validated"). The
            message names the event, never the line.
    """
    events = []
    for line in grep_output.splitlines():
        stamp = _LOG_LINE.search(line)
        if stamp is None:
            unplaced = next((e for p, e in LOGIN_PHRASES.items() if p in line), None)
            if unplaced is not None:
                raise ValueError(f"gateway log format not recognised: a '{unplaced}' line has no leading time")
            continue
        for phrase, event in LOGIN_PHRASES.items():
            i = line.find(phrase)
            if i < 0:
                continue
            rest = line[i + len(phrase) :]
            if event == "retry":
                number = re.match(r"\s*(\d+)", rest)
                code = number.group(1) if number else ""
            elif event in ("validate", "ssodh/init"):
                code = rest[:3] if rest[:3].isdigit() else ""
            else:
                code = ""
            events.append(LoginEvent(f"{stamp.group(1)} {stamp.group(2)}", event, code))
            break
    # `grep -r` reads the files in directory order (measured 2026-10-12); a stable sort keeps
    # each file's own order within a second.
    return sorted(events, key=lambda e: e.at)


def newest_login_index(events: Sequence[LoginEvent]) -> int | None:
    """Where the newest `login` event sits in `events` (time-ordered), or None if there is none.
    One definition, for the rule below and the command line's timeline."""
    return max((i for i, e in enumerate(events) if e.event == "login"), default=None)


class LastLogin(NamedTuple):
    """The newest login in the gateway's log and what became of it."""

    at: str  # the login line's "YYYY-MM-DD HH:MM:SS" UTC
    outcome: Literal["validated", "refused", "validating"]


def last_login(events: Sequence[LoginEvent]) -> LastLogin | None:
    """What became of the newest login: validated, refused, or still being validated.

    Anchored on the newest `login` line, whatever its age. A container restart did not clear
    IBKR's refusal (2026-10-08: started 15:47:49 UTC, refused again at 15:49:37), so a window
    "since the start" would read a gateway as free that IBKR is refusing; and a "giving up"
    with no login before it is no refusal (2026-10-09 19:51 and 20:37 UTC: a validation that
    lapsed by itself, a burst of 500s that recovered). After the login, `authenticated to cp`
    means validated — a later lapse is the HTTP reading's to see — else `giving up` means
    refused, else IBKR has not answered yet (measured: at most 13 s). None when the log holds
    no login line, as in a re-created container.
    """
    newest = newest_login_index(events)
    if newest is None:
        return None
    after = {e.event for e in events[newest + 1 :]}
    if "authenticated" in after:
        return LastLogin(events[newest].at, "validated")
    if "giving up" in after:
        return LastLogin(events[newest].at, "refused")
    return LastLogin(events[newest].at, "validating")


REFUSED_GUIDANCE = (
    'The page read "Client login succeeds", then IBKR refused the gateway\'s validation and the '
    "gateway gave up — the page writes its success before IBKR is asked, so it is not a session. "
    "Logging in to the gateway again has not cleared this, and neither has a container restart "
    "(2026-10-07/08: five refused logins, one of them under two minutes after a restart). First "
    "log in once on IBKR's website in your browser and log out; then log in to the gateway once. "
    'Runbook: docs/gateway-auth-reference.md § Refused after "Client login succeeds".'
)

_VALIDATING_GUIDANCE = (
    'The page read "Client login succeeds" and the gateway is still waiting for IBKR\'s '
    "validation. A good login has been answered within a second, a refusal within 13 seconds "
    "(measured). Do not log in again — re-run this check in a few seconds. If it still reads "
    "this, the gateway stopped mid-validation: see docs/gateway-auth-reference.md § Runbook: a "
    "login that will not take."
)


def refine_with_log(
    found: tuple[int, str, str], events: Sequence[LoginEvent] | None, problem: str
) -> tuple[int, str, str]:
    """A FREE verdict refined by the gateway's own log; any other verdict, unchanged.

    FREE is the one reading the log can change: the HTTP side looks the same after a login
    IBKR refused, during one it is still answering, and when nobody has logged in. A refused
    or unanswered last login replaces it (`EXIT_REFUSED`, `EXIT_VALIDATING`); otherwise FREE
    stands with one line of what the log showed — including that it could not be read, which
    is never left silent. Wording reviewed with the operator on the real log, 2026-10-12.

    Args:
        found: `verdict(state)`.
        events: The manager's `read_login_events` events, or None when unreadable.
        problem: Why the log could not be read; "" when it was.
    """
    code, headline, guidance = found
    if code != EXIT_FREE:
        return found
    if events is None:
        return (
            code,
            headline,
            f"{guidance}\n\nThe gateway's own log could not be read ({problem}), so a login "
            "IBKR refused would not show here.",
        )
    last = last_login(events)
    if last is None:
        return code, headline, f"{guidance}\n\nThe gateway's log records no login."
    if last.outcome == "refused":
        return (
            EXIT_REFUSED,
            f"IBKR refused the last gateway login ({last.at} UTC)",
            REFUSED_GUIDANCE,
        )
    if last.outcome == "validating":
        return (
            EXIT_VALIDATING,
            f"IBKR has not answered the last login yet ({last.at} UTC)",
            _VALIDATING_GUIDANCE,
        )
    return (
        code,
        headline,
        f"{guidance}\n\nThe last login in the gateway's log ({last.at} UTC) was validated by IBKR.",
    )


def gateway_api_url(env_file: str | os.PathLike[str] | None = None) -> str:
    """The gateway's API base URL — `Config.gateway_url`, without a trailing slash, pinned.

    Read through `Config.from_env`, the package's one loader (register F48): a secret beside
    the URL in the file stays out of the environment, and a host whose `.env` lies elsewhere
    passes its path. The consumer's version of this read called `load_dotenv`, which
    invariant 12's test refuses here (F45 probe M5).

    Args:
        env_file: The `.env` to read, or None for the loader's own search.

    Returns:
        The URL, e.g. `https://localhost:5055/v1/api`.

    Raises:
        ConfigError: The URL is not a loopback host — before any request is made with it.
    """
    config = Config.from_env(os.fspath(env_file) if env_file is not None else None)
    return require_loopback_url(config.gateway_url.rstrip("/"))
