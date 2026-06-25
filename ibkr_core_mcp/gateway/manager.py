"""
IBKR Client Portal Gateway manager.

Builds and runs the official IBKR gateway as a Docker container, then guides
the user through browser login + 2FA before the session can be used by
IBKRClient.

Quick start (CLI)::

    from ibkr_core_mcp.gateway import GatewayManager
    gm = GatewayManager()
    gm.startup()          # interactive: starts container, opens browser, waits for auth

Programmatic (non-interactive, e.g. Chainlit)::

    gm = GatewayManager()
    gm.start()                    # build image + run container
    gm.wait_for_gateway()         # wait up to 120s for Java process
    gm.open_login_page()          # open https://localhost:5055 in browser
    # … user logs in …
    gm.wait_for_auth(timeout=300) # poll until authenticated
"""
from __future__ import annotations

import contextlib
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

_DOCKER_DIR = Path(__file__).parent  # Dockerfile and scripts live here


class GatewayManager:
    """Manages the IBKR Client Portal Gateway Docker container."""

    IMAGE_NAME = "ibkr-core-gateway"
    CONTAINER_NAME = "ibkr_core_gateway"
    DEFAULT_PORT = 5055

    def __init__(self, port: int = DEFAULT_PORT) -> None:
        self._port = port
        self._base_url = f"https://localhost:{port}"
        self._api_url = f"{self._base_url}/v1/api"

    # ── Docker availability ──────────────────────────────────────────────────

    def is_docker_available(self) -> bool:
        """True if the Docker daemon is running and reachable."""
        return subprocess.run(
            ["docker", "info"],
            capture_output=True,
        ).returncode == 0

    def ensure_docker_running(self, timeout: int = 60) -> None:
        """Start Docker Desktop (macOS) and wait for it to be ready.

        Raises GatewayError on non-macOS if Docker is not already running.
        """
        if self.is_docker_available():
            return
        if platform.system() != "Darwin":
            raise GatewayError(
                "Docker is not running. Start Docker Desktop and retry."
            )
        log.info("Docker not running — launching Docker Desktop")
        subprocess.run(["open", "-a", "Docker"], check=True)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.is_docker_available():
                log.info("Docker Desktop is ready")
                return
            time.sleep(2)
        raise GatewayError(
            f"Docker Desktop did not become ready within {timeout}s"
        )

    # ── Image management ─────────────────────────────────────────────────────

    def image_exists(self) -> bool:
        """True if the gateway Docker image has already been built."""
        return subprocess.run(
            ["docker", "image", "inspect", self.IMAGE_NAME],
            capture_output=True,
        ).returncode == 0

    def build_image(self) -> None:
        """Build the gateway Docker image from the bundled Dockerfile.

        Downloads ~60 MB of the IBKR Client Portal zip on first build.
        Subsequent builds use the Docker layer cache and are instant.
        """
        log.info("Building IBKR gateway image '%s' ...", self.IMAGE_NAME)
        subprocess.run(
            ["docker", "build", "-t", self.IMAGE_NAME, str(_DOCKER_DIR)],
            check=True,
        )
        log.info("Image built: %s", self.IMAGE_NAME)

    # ── Container lifecycle ──────────────────────────────────────────────────

    def is_running(self) -> bool:
        """True if the gateway container is currently running."""
        result = subprocess.run(
            [
                "docker", "inspect", "--format", "{{.State.Running}}",
                self.CONTAINER_NAME,
            ],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0 and "true" in result.stdout

    def container_exists(self) -> bool:
        """True if the container exists in any state (running, stopped, or exited)."""
        return subprocess.run(
            ["docker", "inspect", "--format", "{{.Name}}", self.CONTAINER_NAME],
            capture_output=True,
        ).returncode == 0

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
        subprocess.run(
            [
                "docker", "run", "-d",
                "--name", self.CONTAINER_NAME,
                "-p", f"{self._port}:{self._port}",
                # Pass env vars used by tickler.sh inside the container
                "-e", f"GATEWAY_PORT={self._port}",
                "-e", "TICKLE_INTERVAL=60",
                "-e", f"TICKLE_BASE_URL=https://host.docker.internal:{self._port}/v1/api",
                "-e", "TICKLE_ENDPOINT=/tickle",
                self.IMAGE_NAME,
            ],
            check=True,
        )
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
        """True if the Java process is accepting HTTP (not necessarily authenticated)."""
        try:
            resp = requests.post(
                f"{self._api_url}/tickle",
                verify=False,
                timeout=3,
            )
            return 200 <= resp.status_code < 600
        except Exception:
            return False

    def is_authenticated(self) -> bool:
        """True if the gateway holds an active authenticated IBKR session."""
        with contextlib.suppress(Exception):
            resp = requests.get(
                f"{self._api_url}/iserver/auth/status",
                verify=False,
                timeout=5,
            )
            if resp.status_code == 200:
                return bool(resp.json().get("authenticated", False))
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
        self.start()

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
