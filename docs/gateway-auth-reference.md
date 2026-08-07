# Gateway Authentication & Session — Full Reference

The IBKR Client Portal Gateway must run on the **same machine** as the browser used to authenticate. No cloud deployment possible.

`BrowserCookieAuth` (default) reads Chrome's cookie store for `localhost`. On first use:

1. Start the gateway using the built-in `GatewayManager` (see below)
2. Open `https://localhost:5055` in Chrome
3. Log in with IBKR credentials + 2FA (challenge code shown in-browser → IBKR Mobile → enter the response code)
4. Wait for "Client login succeeds" in browser
5. The package reads the session cookie automatically

**Starting the gateway:**
```python
from ibkr_core_mcp import GatewayManager

gm = GatewayManager()
gm.startup()   # builds Docker image on first run, then opens browser for login
```

Or from a script:
```bash
python -c "from ibkr_core_mcp import GatewayManager; GatewayManager().startup()"
```

The gateway Docker image (`ibkr-core-gateway`) is built from assets bundled
inside `ibkr_core_mcp/gateway/`. No external repo is required.

For headless use (ML batch jobs), pass a pre-extracted cookie string:
```python
from ibkr_core_mcp import IBKRClient, TokenAuth, Config

client = IBKRClient(Config.from_env(), auth=TokenAuth("cookie_string_here"))
```

**Session constraints:**

- Session expires without activity, and **nothing in the container renews it — you must run
  your own keepalive.** This paragraph said the opposite until 2026-08-07: that a bundled
  `tickler.sh` POSTed `/tickle` every 60 s so callers did not need one. That was the
  reassuring half of the claim, and a caller who believed it ran no keepalive and watched
  sessions expire with nothing to explain why. The in-container tickler was removed on
  2026-08-06 and the script deleted on 2026-08-07; the same false claim was corrected in
  `gateway/__init__.py` on 2026-08-06 and this page was missed.
  Renewal cannot live in the container: a loop in there cannot see the host-side suspend
  flag that coordinates a login, and on 2026-08-05 three such ticklers renewed a **borrowed**
  session every 60 s, defeating every attempt to clear it — `POST /logout` could not, only
  `docker restart` could. Call `client.tickle()` from the host, and pause it while a login
  is in flight.
- Rate limit: IBKR's documented global limit is **10 requests/second** for any endpoint not in
  its per-endpoint table (several endpoints are far stricter — e.g. `/iserver/account/orders`
  and `/iserver/account/trades` are 1 req/5s, `/tickle` is 1 req/s). `rate_limiter.py` does not
  proactively pace requests to this limit; it reactively retries 429/503 with exponential
  backoff (1s, 2s, 4s over 3 attempts) and raises `IBKRRateLimitError` if still failing.
  Source: https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/pacing-limitations
  (full per-endpoint table in `rate_limiter.py`'s docstring).
