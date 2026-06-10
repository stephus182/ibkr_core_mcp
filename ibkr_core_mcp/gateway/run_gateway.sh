#!/bin/bash
# Start the IBKR gateway then the keepalive tickler.

cd /app/api_gateway
sh bin/run.sh root/conf.yaml &

echo "Waiting for gateway to become reachable..."
while ! /usr/local/bin/healthcheck.sh > /dev/null 2>&1; do
  echo "  gateway not ready yet..."
  sleep 2
done

echo "Gateway is ready — starting tickler"
/app/tickler.sh &

wait
