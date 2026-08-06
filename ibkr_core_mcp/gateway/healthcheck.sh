#!/bin/sh
# Returns 0 when the Java gateway process is accepting connections.
# Auth state is NOT checked — that requires browser login.
#
# GET, not POST, since 2026-08-06. /tickle is documented as "pings the server to prevent
# the session from ending", so a POST here is a session-affecting write dressed as a
# health check. Today that is bounded — run_gateway.sh calls this only in its startup
# wait loop, on a container that holds no session yet — but a Docker HEALTHCHECK
# instruction added later would silently turn it into a recurring renewer that no
# host-side suspend flag can reach, which is precisely why the in-container tickler had
# to be removed. GatewayManager.is_gateway_reachable was fixed the same way on the same
# day. Any 2xx-5xx still counts as reachable: HTTP 401 means the gateway is answering and
# holds no session, which is the best possible moment to log in.
STATUS=$(curl -sk -o /dev/null -w "%{http_code}" \
  "https://localhost:${GATEWAY_PORT}/v1/api/tickle" 2>/dev/null)

if echo "$STATUS" | grep -qE "^[2-5]"; then
  exit 0
fi
exit 1
