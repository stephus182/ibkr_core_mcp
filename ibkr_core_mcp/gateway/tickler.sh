#!/bin/sh
# Keeps the IBKR gateway session alive with periodic POST /tickle calls.
echo "[tickler] started"
while true; do
  curl -sk -X POST "${TICKLE_BASE_URL}${TICKLE_ENDPOINT}" \
    -H "Content-Type: application/json" -d "{}" \
    -w " HTTP %{http_code}\n"
  sleep "${TICKLE_INTERVAL}"
done
