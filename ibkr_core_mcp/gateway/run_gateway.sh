#!/bin/bash
# Start the IBKR gateway then the keepalive tickler.

cd /app/api_gateway
sh bin/run.sh root/conf.yaml &

echo "Waiting for gateway to become reachable..."
while ! /usr/local/bin/healthcheck.sh > /dev/null 2>&1; do
  echo "  gateway not ready yet..."
  sleep 2
done

echo "Gateway is ready"

# NO in-container tickler. Removed 2026-08-06.
#
# It POSTed /tickle every 60s for the life of the container, which made it the one
# renewer that could not be silenced: the suspend flag that stops every other actor
# during a login or a recovery lives on the HOST
# (~/.ibkr_core/session.suspend, written by claudia/gateway_session.py :: SuspendLock),
# and nothing inside this container can read it.
#
# That mattered because IBKR renews a session on ANY request, not just /tickle
# (https://ibkrcampus.com/docs/web-api/v1/endpoints/session/ping-the-server.md), so a
# single un-suspendable renewer is enough to defeat a deliberate attempt to clear a
# session — measured 2026-08-05, when three ticklers kept a borrowed session alive
# through `POST /logout` all day.
#
# Keeping the session alive is now the host keepalive's job
# (claudia_ui/scripts/ibkr-keepalive.sh, installed as a launchd agent with RunAtLoad +
# KeepAlive). It honours the suspend flag, and it also holds the `caffeinate` assertion
# that stops the Mac sleeping the session away — something this script never did.
#
# ⚠ If that daemon is not installed, nothing renews an idle session. Install it with
# claudia_ui/scripts/install-ibkr-keepalive-daemon.sh.

wait
