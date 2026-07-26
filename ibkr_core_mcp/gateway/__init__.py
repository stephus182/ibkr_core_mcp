"""IBKR Client Portal Gateway lifecycle management.

Packages the official IBKR gateway as a Docker image (`Dockerfile`, `conf.yaml`,
`run_gateway.sh`, `tickler.sh`, `healthcheck.sh` ship as package data) and exposes
`GatewayManager` to build, run, and authenticate it. The bundled `tickler.sh` keeps
the session alive from inside the container, so callers do not need their own
keepalive loop unless they manage a gateway separately.
"""

from ibkr_core_mcp.gateway.manager import GatewayManager

__all__ = ["GatewayManager"]
