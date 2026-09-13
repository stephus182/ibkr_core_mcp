"""Security constitution §10 — the HTTP transport validates Host and Origin, so a browser
tab cannot become an MCP client.

`_run_sse` built `SseServerTransport("/messages/")` with no security settings. In mcp
1.29.0 that substitutes `TransportSecuritySettings(enable_dns_rebinding_protection=False)`
"for backwards compatibility", so Host and Origin were never checked. uvicorn binding
127.0.0.1 stops the LAN, not the operator's own browser: a page on attacker.example whose
DNS answer flips to 127.0.0.1 becomes same-origin with the server, opens /sse, reads the
session id, and POSTs JSON-RPC to /messages/ — every tool, from an unattended tab
(docs/audits/security-architecture-audit-2026-09-13.md, A3).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient

from ibkr_core_mcp.mcp_server import build_server, build_sse_app

pytestmark = pytest.mark.security


@pytest.fixture
def app(mock_config):
    from ibkr_core_mcp.claude_tools import ClaudeToolkit
    from ibkr_core_mcp.store import SQLiteStore

    toolkit = ClaudeToolkit(MagicMock(), MagicMock(), MagicMock(), mock_config)
    server = build_server(toolkit, SQLiteStore(mock_config))
    return build_sse_app(server)


def _post(client: TestClient, **headers: str):
    return client.post("/messages/?session_id=00000000000000000000000000000000", headers=headers, json={})


def test_a_foreign_host_header_is_rejected_before_any_session_lookup(app):
    """DNS rebinding: the browser sends the attacker's hostname as Host."""
    with TestClient(app) as client:
        resp = _post(client, Host="attacker.example")
    assert resp.status_code == 421


def test_a_foreign_origin_is_rejected(app):
    with TestClient(app) as client:
        resp = _post(client, Host="127.0.0.1:5174", Origin="https://attacker.example")
    assert resp.status_code == 403


@pytest.mark.parametrize("host", ["127.0.0.1:5174", "localhost:5174", "127.0.0.1:9999"])
def test_loopback_hosts_reach_the_session_layer(app, host):
    """The check must stop rebinding, not the real client: a loopback Host passes the
    security layer and fails later on the unknown session id (404), proving it got through."""
    with TestClient(app) as client:
        resp = _post(client, Host=host)
    assert resp.status_code == 404
