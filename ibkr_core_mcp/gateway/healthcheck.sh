#!/bin/sh
# Returns 0 when the Java gateway process is accepting connections.
# Auth state is NOT checked — that requires browser login.
STATUS=$(curl -sk -o /dev/null -w "%{http_code}" \
  -X POST -H "Content-Length: 0" \
  "https://localhost:${GATEWAY_PORT}/v1/api/tickle" 2>/dev/null)

if echo "$STATUS" | grep -qE "^[2-5]"; then
  exit 0
fi
exit 1
