"""IBKR Client Portal Gateway lifecycle management.

Packages the official IBKR gateway as a Docker image (`Dockerfile`, `conf.yaml`,
`run_gateway.sh`, `healthcheck.sh` ship as package data), exposes `GatewayManager`
to build, run and reach it, and — since register F45, step 2 — the session's one owner,
`get_session()` (`gateway/session.py`): the only code that opens a login, posts to a session
endpoint or restarts a container holding a session.

⚠ **The caller must run its own keepalive. There is no tickler in the container.**

`tickler.sh` was removed from the image on 2026-08-06 and this docstring used to say the
opposite — that the bundled tickler kept the session alive "so callers do not need their
own keepalive loop". That is now false, and it is the reassuring half of the claim, which
is the worst half to get wrong: a caller believing it would run no keepalive and watch
sessions time out with nothing to explain why.

It was removed because it could not be silenced. IBKR renews a session on **any** request
(https://www.interactivebrokers.com/docs/web-api/v1/endpoints/session/ping-the-server), so a login
or a deliberate session-clear requires every actor to go quiet — and a loop inside the
container cannot see the host-side flag that coordinates that. Renewal is now the host's
job, from outside the container, by a loop that honours the host-side suspend lock.

**Changing anything that ships into the image requires `docker rmi -f ibkr-core-gateway`
before the change takes effect** (`-f` because the gateway's container, stopped or not, still
uses the image and Docker refuses a plain `rmi` — measured 2026-11-07). `GatewayManager.start()` builds only when the image is
absent, so a restart alone will keep running the old one — that is exactly how the tickler
survived its own removal for a day.
"""

from ibkr_core_mcp.gateway.manager import GatewayManager, LoginWindow
from ibkr_core_mcp.gateway.session import GatewaySession, SessionPhase, SessionState, SuspendLock, get_session

__all__ = [
    "GatewayManager",
    "GatewaySession",
    "LoginWindow",
    "SessionPhase",
    "SessionState",
    "SuspendLock",
    "get_session",
]
