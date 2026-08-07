"""IBKR Client Portal Gateway manager.

Builds and runs the official IBKR gateway as a Docker container, then guides
the user through browser login + 2FA before the session can be used by
IBKRClient.

Quick start (CLI)::

    from ibkr_core_mcp.gateway import GatewayManager
    gm = GatewayManager()
    gm.startup()          # interactive: starts container, opens browser, waits for auth

Programmatic (non-interactive, e.g. from a web UI such as ClaudIA)::

    gm = GatewayManager()
    gm.start()                    # build image + run container
    gm.wait_for_gateway()         # wait up to 120s for Java process
    gm.open_login_page()          # open https://localhost:5055 in browser
    # … user logs in …
    gm.wait_for_auth(timeout=300) # poll until authenticated
"""

from __future__ import annotations

import logging
import platform
import subprocess
import time
import webbrowser
from collections.abc import Callable
from pathlib import Path

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from ibkr_core_mcp.exceptions import GatewayError  # noqa: E402

log = logging.getLogger(__name__)

_DOCKER_DIR = Path(__file__).resolve().parent
"""The Docker build context — **resolved through symlinks, and that is load-bearing.**

`Path(__file__).parent` was wrong under the install this project mandates. A strict
editable install (`--config-settings editable_mode=strict`, required for mypy — see
claudia_ui/CLAUDE.md) puts a symlink farm at
`build/__editable__…/ibkr_core_mcp/gateway/`, so `__file__` lives there and its parent is
that farm. Every entry in it, `Dockerfile` included, is a symlink to an absolute path
outside the directory.

**Docker does not follow a symlink that leaves the build context.** It tars the context
and hands it to the daemon, which sees an unresolvable link. Measured 2026-08-06:

    context = build/__editable__…/ibkr_core_mcp/gateway
      -> ERROR: failed to read dockerfile: open Dockerfile: no such file or directory
    context = ibkr_core_mcp/gateway            (this, after .resolve())
      -> #1 transferring dockerfile: 811B done

So `build_image()` could not run at all in a normal development environment. It went
unnoticed because `start()` only builds when the image is absent, and the image had been
present since 2026-07-22 — which also meant the in-container tickler removed from
`run_gateway.sh` on 2026-08-06 could never take effect. Two defects, one cause: nothing
ever rebuilt, and nothing could have.
"""


class GatewayManager:
    """Manages the IBKR Client Portal Gateway Docker container."""

    IMAGE_NAME = "ibkr-core-gateway"
    CONTAINER_NAME = "ibkr_core_gateway"
    DEFAULT_PORT = 5055

    def __init__(self, port: int = DEFAULT_PORT) -> None:
        """Derive the gateway's base and REST URLs from the host port.

        Args:
            port: Host port to publish the container on. Must match the port in
                the bundled `conf.yaml`; the gateway is always reached over
                `https://localhost` because the browser used to authenticate has
                to run on the same machine.
        """
        self._port = port
        self._base_url = f"https://localhost:{port}"
        self._api_url = f"{self._base_url}/v1/api"

    # ── Docker availability ──────────────────────────────────────────────────

    def is_docker_available(self) -> bool:
        """True if the Docker daemon is running and reachable."""
        return (
            subprocess.run(
                ["docker", "info"],
                capture_output=True,
            ).returncode
            == 0
        )

    def ensure_docker_running(self, timeout: int = 60) -> None:
        """Start Docker Desktop (macOS) and wait for it to be ready.

        Raises GatewayError on non-macOS if Docker is not already running.
        """
        if self.is_docker_available():
            return
        if platform.system() != "Darwin":
            raise GatewayError("Docker is not running. Start Docker Desktop and retry.")
        log.info("Docker not running — launching Docker Desktop")
        try:
            subprocess.run(["open", "-a", "Docker"], check=True)
        except subprocess.CalledProcessError as exc:
            raise GatewayError("Failed to launch Docker Desktop.") from exc
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.is_docker_available():
                log.info("Docker Desktop is ready")
                return
            time.sleep(2)
        raise GatewayError(f"Docker Desktop did not become ready within {timeout}s")

    # ── Image management ─────────────────────────────────────────────────────

    def image_exists(self) -> bool:
        """True if the gateway Docker image has already been built."""
        return (
            subprocess.run(
                ["docker", "image", "inspect", self.IMAGE_NAME],
                capture_output=True,
            ).returncode
            == 0
        )

    def build_image(self) -> None:
        """Build the gateway Docker image from the bundled Dockerfile.

        Downloads ~60 MB of the IBKR Client Portal zip on first build.
        Subsequent builds use the Docker layer cache and are instant.
        """
        log.info("Building IBKR gateway image '%s' ...", self.IMAGE_NAME)
        try:
            subprocess.run(
                ["docker", "build", "-t", self.IMAGE_NAME, str(_DOCKER_DIR)],
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            raise GatewayError(
                f"Failed to build Docker image '{self.IMAGE_NAME}'. "
                "Check that Docker is running and the Dockerfile is intact."
            ) from exc
        log.info("Image built: %s", self.IMAGE_NAME)

    # ── Container lifecycle ──────────────────────────────────────────────────

    def is_running(self) -> bool:
        """True if the gateway container is currently running."""
        result = subprocess.run(
            [
                "docker",
                "inspect",
                "--format",
                "{{.State.Running}}",
                self.CONTAINER_NAME,
            ],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0 and "true" in result.stdout

    def container_exists(self) -> bool:
        """True if the container exists in any state (running, stopped, or exited)."""
        return (
            subprocess.run(
                ["docker", "inspect", "--format", "{{.Name}}", self.CONTAINER_NAME],
                capture_output=True,
            ).returncode
            == 0
        )

    def start(self) -> None:
        """Build image if needed, then start the gateway container.

        Any existing container (running or stopped) is removed first so the
        new container starts with a clean unauthenticated session.
        """
        self.ensure_docker_running()
        if self.container_exists():
            log.info("Removing existing gateway container for clean restart")
            self.stop()
        if not self.image_exists():
            self.build_image()
        log.info("Starting IBKR gateway on port %d ...", self._port)
        try:
            subprocess.run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    self.CONTAINER_NAME,
                    "-p",
                    f"127.0.0.1:{self._port}:{self._port}",
                    # GATEWAY_PORT is the only variable anything in the image reads:
                    # run_gateway.sh's wait loop and healthcheck.sh both build their URL
                    # from it. Three TICKLE_* variables were passed here until
                    # 2026-08-07, addressed to a tickler.sh that had been out of the
                    # image since 2026-08-06 and is now deleted outright. Do not add
                    # them back: session renewal is the caller's, because a loop inside
                    # the container cannot see the host-side suspend flag that
                    # coordinates a login. Guarded by a test asserting their absence.
                    "-e",
                    f"GATEWAY_PORT={self._port}",
                    self.IMAGE_NAME,
                ],
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            raise GatewayError(
                f"Failed to start gateway container on port {self._port}. "
                "Port may be in use or the Docker image may be missing."
            ) from exc
        log.info("Gateway container started: %s", self.CONTAINER_NAME)

    def stop(self) -> None:
        """Stop and remove the gateway container (idempotent — safe to call when not running)."""
        subprocess.run(["docker", "stop", self.CONTAINER_NAME], capture_output=True)
        subprocess.run(["docker", "rm", self.CONTAINER_NAME], capture_output=True)
        log.info("Gateway container stopped: %s", self.CONTAINER_NAME)

    def restart(self) -> None:
        """Stop then start — resets to a clean unauthenticated session."""
        self.stop()
        self.start()

    # ── Gateway health ────────────────────────────────────────────────────────

    def is_gateway_reachable(self) -> bool:
        """True if the Java process is accepting HTTP (not necessarily authenticated).

        Uses **GET**, not POST, since 2026-08-06. The endpoint is documented as
        "pings the server to prevent the session from ending", so a POST here is a
        session-affecting write dressed as a health check — and this method is called in
        a polling loop by `wait_for_gateway`. Merely asking "is it up?" therefore renewed
        the keepalive timer, which is exactly the traffic the suspend flag exists to stop
        during a login or a recovery.

        HTTP 401 still counts as reachable, and deliberately: it means the gateway is
        answering and holds no authenticated session — the best possible moment to log in.
        Treating it as "down" told a user "start it first" about a gateway that was
        running perfectly (measured 2026-08-05).

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/session/ping-the-server.md
        Endpoint: GET /tickle
        """
        try:
            resp = requests.get(
                f"{self._api_url}/tickle",
                verify=False,
                timeout=3,
            )
            return 200 <= resp.status_code < 600
        except requests.exceptions.RequestException as exc:
            log.debug("Gateway not reachable yet: %s", exc)
            return False
        except Exception as exc:
            log.warning("Unexpected error checking gateway reachability: %s", exc)
            return False

    def is_authenticated(self) -> bool:
        """True if the gateway holds an active authenticated IBKR session.

        Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/session/authentication-status.md
        Endpoint: GET /iserver/auth/status
        """
        try:
            resp = requests.get(
                f"{self._api_url}/iserver/auth/status",
                verify=False,
                timeout=5,
            )
        except requests.exceptions.RequestException as exc:
            log.debug("Auth status check failed (gateway unreachable): %s", exc)
            return False
        except Exception as exc:
            log.warning("Unexpected error checking auth status: %s", exc)
            return False

        if resp.status_code != 200:
            log.warning("Auth status endpoint returned HTTP %d", resp.status_code)
            return False

        try:
            return bool(resp.json().get("authenticated", False))
        except Exception as exc:
            log.warning("Auth status response was not valid JSON: %s", exc)
            return False

    # ── Polling helper ────────────────────────────────────────────────────────

    def _poll_until(
        self,
        check: Callable[[], bool],
        ready_msg: str,
        timeout_msg: str,
        timeout: int,
        poll_interval: int,
    ) -> bool:
        """Call `check` every `poll_interval` seconds until it is true or time runs out.

        Shared by `wait_for_gateway` and `wait_for_auth` so the two cannot drift in how
        they time out or what they log. Returns True the moment `check` succeeds, False
        if the deadline passes — never raises, because both callers treat "not ready yet"
        as an ordinary answer they have to branch on rather than an error.

        Args:
            check: The condition, polled repeatedly. Must not raise.
            ready_msg: Logged at INFO when `check` first returns true.
            timeout_msg: Logged at WARNING when the deadline passes.
            timeout: Total seconds to wait.
            poll_interval: Seconds slept between attempts.

        Returns:
            Whether `check` became true within `timeout`.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if check():
                log.info(ready_msg)
                return True
            time.sleep(poll_interval)
        log.warning(timeout_msg)
        return False

    def wait_for_gateway(self, timeout: int = 120, poll_interval: int = 3) -> bool:
        """Block until the gateway Java process is reachable.

        Returns True if ready within *timeout* seconds, False otherwise.
        """
        log.info("Waiting for IBKR gateway (timeout=%ds) ...", timeout)
        return self._poll_until(
            self.is_gateway_reachable,
            "Gateway is reachable",
            f"Gateway did not become reachable within {timeout}s",
            timeout,
            poll_interval,
        )

    def wait_for_auth(self, timeout: int = 300, poll_interval: int = 5) -> bool:
        """Block until the session is authenticated.

        Returns True if authenticated within *timeout* seconds, False otherwise.
        """
        log.info("Waiting for IBKR authentication (timeout=%ds) ...", timeout)
        return self._poll_until(
            self.is_authenticated,
            "IBKR session authenticated",
            f"IBKR session not authenticated within {timeout}s",
            timeout,
            poll_interval,
        )

    # ── Auth flow ─────────────────────────────────────────────────────────────

    def open_login_page(self) -> None:
        """Open the IBKR Client Portal login page in the system default browser."""
        log.info("Opening IBKR login page: %s", self._base_url)
        webbrowser.open(self._base_url)

    # ── Full interactive startup ──────────────────────────────────────────────

    def startup(self) -> bool:
        """Full interactive startup sequence for CLI use.

        Fast path (normal ClaudIA restart):
          If the container is already running and authenticated, returns immediately.
          The IBKR session is preserved — no login required.

        Full path (first start or after session loss):
          1. Ensure Docker is running (launches Docker Desktop on macOS if needed)
          2. Remove any existing container and start a fresh one
          3. Wait for Java process to become reachable
          4. Open login page in browser
          5. Wait for user to complete login + 2FA
          6. Verify authentication

        Returns True if the session is authenticated and ready.
        """
        print("▶ Ensuring Docker is running...")
        self.ensure_docker_running()

        # If the gateway is already up and authenticated, nothing to do.
        # This is the normal case when restarting ClaudIA without touching IB.
        if self.is_running() and self.is_authenticated():
            print("  ✔ IBKR gateway already running and authenticated — skipping startup.")
            return True

        print("▶ Starting IBKR gateway container...")
        # Start ONLY when nothing is running. `start()` removes any existing container,
        # which destroys whatever session it held — and until 2026-08-06 that ran on every
        # launch where the gateway was not already authenticated, throwing away sessions
        # that a pre-flight would have found perfectly usable and forcing a fresh 2FA.
        #
        # A container that is absent or stopped cannot hold a session (it lives in the
        # Java process), so recreating one is free. A RUNNING container is left alone.
        #
        # NOTE: claudia_ui no longer calls this method at all — it goes through
        # claudia.gateway_session, which owns the sequencing and pre-flights first. This
        # guard exists so the CLI path here cannot destroy a session either.
        if not self.is_running():
            self.start()
        else:
            print("  ✔ Container already running — leaving it alone.")

        print("▶ Waiting for gateway to be reachable...")
        if not self.wait_for_gateway():
            print("  ✕ Gateway did not start within timeout.")
            return False

        print("▶ Opening IBKR login page in browser...")
        self.open_login_page()
        print()
        print("  Complete the login in your browser:")
        print("    1. Enter your IBKR username and password")
        print("    2. Complete 2FA (challenge code → IBKR Mobile → response code)")
        print("    3. Wait for 'Client login succeeds'")
        print()
        input("Press Enter here once Chrome shows 'Client login succeeds'... ")
        print()

        print("▶ Verifying IBKR session...")
        if self.wait_for_auth(timeout=60):
            print("  ✔ IBKR session active and ready.")
            return True

        print("  ✕ Session not verified.")
        print("    Reload the login page, log in again, then retry.")
        input("Press Enter to retry verification... ")
        if self.is_authenticated():
            print("  ✔ IBKR session active.")
            return True

        print("  ✕ Still not authenticated.")
        print("    Starting anyway — IBKR tools will error until you log in.")
        return False
