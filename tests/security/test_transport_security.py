"""Security constitution §10 — the HTTP transport validates Host and Origin and requires
the per-launch bearer token, so neither a browser tab nor another local process can become
an MCP client.

`_run_sse` built `SseServerTransport("/messages/")` with no security settings. In mcp
1.29.0 that substitutes `TransportSecuritySettings(enable_dns_rebinding_protection=False)`
"for backwards compatibility", so Host and Origin were never checked. uvicorn binding
127.0.0.1 stops the LAN, not the operator's own browser: a page on attacker.example whose
DNS answer flips to 127.0.0.1 becomes same-origin with the server, opens /sse, reads the
session id, and POSTs JSON-RPC to /messages/ — every tool, from an unattended tab
(docs/audits/security-architecture-audit-2026-09-13.md, A3).

Host/Origin validation stops the browser and the LAN; it says nothing about another
*process* on the same machine, which needs no DNS trick and no browser — it can simply
open the port. That half was documented as a residual on 2026-09-14 and closed the same
day once the review established that no SSE consumer exists to break (OWASP §1 "still
utilize explicit authorization/authentication"; the MCP best-practices page's "require an
authorization token"; the transports specification's "SHOULD implement proper
authentication"). See docs/audits/owasp-mcp-guide-applicability-2026-09-14.md § Phase 3 A.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient

from ibkr_core_mcp.mcp_server import build_server, build_sse_app

pytestmark = pytest.mark.security

#: Stands in for the `secrets.token_urlsafe(32)` a real launch mints.
TOKEN = "test-token-not-a-real-secret"


@pytest.fixture
def app(mock_config):
    from ibkr_core_mcp.claude_tools import ClaudeToolkit
    from ibkr_core_mcp.store import SQLiteStore

    toolkit = ClaudeToolkit(MagicMock(), MagicMock(), MagicMock(), mock_config)
    server = build_server(toolkit, SQLiteStore(mock_config))
    return build_sse_app(server, TOKEN)


def _post(client: TestClient, **headers: str):
    """POST /messages/ the way a real client does — with the launch's bearer token, unless
    a test overrides `Authorization` to say what happens without it."""
    headers.setdefault("Authorization", f"Bearer {TOKEN}")
    return client.post("/messages/?session_id=00000000000000000000000000000000", headers=headers, json={})


# ── Host and Origin (2026-09-13) ──────────────────────────────────────────────


def test_a_foreign_host_header_is_rejected_before_any_session_lookup(app):
    """DNS rebinding: the browser sends the attacker's hostname as Host."""
    with TestClient(app) as client:
        resp = _post(client, Host="attacker.example")
    assert resp.status_code == 421


def test_a_loopback_origin_without_a_port_is_accepted(app):
    """Review 2026-09-13: the allowlists held only `host:*` wildcards, which the SDK matches
    with `startswith(base + ":")` — a port-less Host (`--port 80`) or Origin was refused."""
    with TestClient(app) as client:
        resp = _post(client, Host="127.0.0.1", Origin="http://127.0.0.1")
    assert resp.status_code == 404


def test_a_foreign_origin_is_rejected(app):
    with TestClient(app) as client:
        resp = _post(client, Host="127.0.0.1:5174", Origin="https://attacker.example")
    assert resp.status_code == 403


@pytest.mark.parametrize(
    "host", ["127.0.0.1:5174", "localhost:5174", "127.0.0.1:9999", "127.0.0.1", "localhost", "[::1]:5174"]
)
def test_loopback_hosts_reach_the_session_layer(app, host):
    """The check must stop rebinding, not the real client: a loopback Host passes the
    security layer and fails later on the unknown session id (404), proving it got through."""
    with TestClient(app) as client:
        resp = _post(client, Host=host)
    assert resp.status_code == 404


# ── The per-launch bearer token (2026-09-14) ──────────────────────────────────


def test_a_post_without_the_token_is_refused(app):
    """The local-process case: no DNS trick, no browser — just an open port."""
    with TestClient(app) as client:
        resp = _post(client, Authorization="")
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "presented",
    [
        "",
        "Bearer ",
        "Bearer wrong-token",
        f"Bearer {TOKEN}x",  # a prefix of the real token must not pass
        f"bearer {TOKEN}",  # the scheme is compared verbatim, like the token
        TOKEN,  # the bare token without the scheme
        f"Basic {TOKEN}",
    ],
)
def test_no_near_miss_credential_is_accepted(app, presented):
    with TestClient(app) as client:
        resp = _post(client, Authorization=presented)
    assert resp.status_code == 401


def test_the_token_is_checked_before_host_and_origin(app):
    """An unauthenticated caller learns nothing about the Host/Origin policy: the 401 comes
    first, whatever else the request carries."""
    with TestClient(app) as client:
        resp = _post(client, Authorization="", Host="attacker.example", Origin="https://attacker.example")
    assert resp.status_code == 401


def test_the_stream_endpoint_is_gated_too(app):
    """/sse is where a client reads the session id, so gating only /messages/ would leave
    the interesting half open."""
    with TestClient(app) as client:
        resp = client.get("/sse", headers={"Authorization": ""})
    assert resp.status_code == 401


def test_a_valid_token_reaches_the_transport_security_layer_on_the_stream_endpoint(app):
    """The gate must let the real client through, not merely refuse everyone.

    Asserted with a foreign Host so the SDK's own check answers 421 at once — a valid
    loopback GET would open the event stream and block. `raise_server_exceptions=False`
    because `connect_sse` sends the 421 and *then* raises `ValueError` (mcp 1.29.0,
    sse.py:137); 421 is what a real client sees on the wire, and reaching that code path at
    all is the proof the bearer gate passed the request through.
    """
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/sse", headers={"Authorization": f"Bearer {TOKEN}", "Host": "attacker.example"})
    assert resp.status_code == 421


def test_the_app_cannot_be_built_without_a_token():
    """`build_sse_app(server)` must not be a legal call: an optional token would make an
    unauthenticated server the default again, one forgotten argument at a time."""
    import inspect

    params = inspect.signature(build_sse_app).parameters
    assert "token" in params
    assert params["token"].default is inspect.Parameter.empty
