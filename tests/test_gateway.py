"""Unit tests for GatewayManager — all Docker/network calls mocked."""

from __future__ import annotations

import inspect
import json
import logging
import os
import platform
import subprocess
from collections.abc import Callable
from itertools import pairwise
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import requests

from ibkr_core_mcp.exceptions import GatewayError
from ibkr_core_mcp.gateway import GatewayManager, LoginWindow
from ibkr_core_mcp.gateway.manager import _LOGIN_WINDOW_ENV, GATEWAY_LOG_DIR, _find_chrome, read_login_events
from ibkr_core_mcp.gateway.preflight import LOGIN_PHRASES, LoginEvent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_result(returncode: int, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


_IMAGE_ID = "sha256:" + "1" * 64
"""What `docker image inspect --format {{.Id}}` reports for the gateway image in these tests."""


def _fake_docker(
    container: dict[str, object] | None, restart_rc: int = 0
) -> tuple[Callable[..., SimpleNamespace], list[list[str]]]:
    """A `subprocess.run` for the docker commands `start()` issues; every argv is recorded.

    `container` is what `docker container inspect` reports (`None`: there is none — rc 1 and
    `[]`, measured 2026-11-07); the image is present, as `_IMAGE_ID`; `docker restart` answers
    `restart_rc`; every other command succeeds.
    """
    calls: list[list[str]] = []

    def run(argv: list[str], **_kwargs: object) -> SimpleNamespace:
        calls.append(argv)
        if argv[1:3] == ["container", "inspect"]:
            return _run_result(1, "[]") if container is None else _run_result(0, json.dumps([container]))
        if argv[1:3] == ["image", "inspect"]:
            return _run_result(0, _IMAGE_ID + "\n")
        if argv[1] == "inspect":  # container_exists()
            return _run_result(1 if container is None else 0)
        if argv[1] == "restart":
            return _run_result(restart_rc, stderr="Error response from daemon" if restart_rc else "")
        return _run_result(0)

    return run, calls


def _container_made_by(gm: GatewayManager) -> dict[str, object]:
    """What `docker container inspect` reports for the container `gm.start()` runs on a host that
    has none: the image's id, the label the base image brings (the live container carries
    Ubuntu's OCI labels, read 2026-11-07) and every label `start()` set, kept byte for byte
    (measured the same day)."""
    run, calls = _fake_docker(None)
    with patch("subprocess.run", side_effect=run):
        gm.start()
    argv = next(argv for argv in calls if argv[1] == "run")
    labels = {"org.opencontainers.image.title": "ubuntu"}
    for flag, value in pairwise(argv):
        if flag == "--label":
            key, _, text = value.partition("=")
            labels[key] = text
    return {"Image": _IMAGE_ID, "Config": {"Labels": labels}}


def _published_beyond_loopback(made: dict[str, object]) -> dict[str, object]:
    """`made` with one option changed alone: its recorded publish on every interface, not loopback."""
    config = made["Config"]
    assert isinstance(config, dict)
    labels = {key: text.replace("127.0.0.1:", "0.0.0.0:") for key, text in config["Labels"].items()}
    assert labels != config["Labels"], "no label records a loopback publish: this case would test nothing"
    return made | {"Config": {"Labels": labels}}


def _verbs(calls: list[list[str]]) -> list[str]:
    """The docker sub-commands issued, in order, among those that keep or replace a container."""
    return [argv[1] for argv in calls if argv[1] in {"restart", "stop", "rm", "run"}]


# ---------------------------------------------------------------------------
# is_docker_available
# ---------------------------------------------------------------------------


class TestIsDockerAvailable:
    def test_returns_true_when_docker_info_succeeds(self) -> None:
        with patch("subprocess.run", return_value=_run_result(0)):
            assert GatewayManager().is_docker_available() is True

    def test_returns_false_when_docker_info_fails(self) -> None:
        with patch("subprocess.run", return_value=_run_result(1)):
            assert GatewayManager().is_docker_available() is False


# ---------------------------------------------------------------------------
# ensure_docker_running
# ---------------------------------------------------------------------------


class TestEnsureDockerRunning:
    def test_no_op_when_already_running(self) -> None:
        gm = GatewayManager()
        with patch.object(gm, "is_docker_available", return_value=True) as mock_check:
            gm.ensure_docker_running()
        mock_check.assert_called_once()

    @pytest.mark.skipif(platform.system() != "Darwin", reason="macOS-only launch path")
    def test_launches_docker_desktop_and_polls_on_macos(self) -> None:
        gm = GatewayManager()
        # Unavailable on first call, available on second (after launch)
        side_effects = [False, True]
        with (
            patch.object(gm, "is_docker_available", side_effect=side_effects),
            patch("subprocess.run") as mock_run,
            patch("time.sleep"),
        ):
            gm.ensure_docker_running(timeout=10)
        # open -a Docker must have been called
        calls = [c.args[0] for c in mock_run.call_args_list]
        assert ["open", "-a", "Docker"] in calls

    def test_raises_on_non_macos_when_docker_not_running(self) -> None:
        gm = GatewayManager()
        with (
            patch.object(gm, "is_docker_available", return_value=False),
            patch("platform.system", return_value="Linux"),
            pytest.raises(GatewayError, match="Docker is not running"),
        ):
            gm.ensure_docker_running()

    def test_raises_on_macos_if_docker_never_becomes_ready(self) -> None:
        gm = GatewayManager()
        with (
            patch.object(gm, "is_docker_available", return_value=False),
            patch("platform.system", return_value="Darwin"),
            patch("subprocess.run"),
            patch("time.sleep"),
            patch("time.monotonic", side_effect=[0, 999]),  # deadline passed immediately
            pytest.raises(GatewayError, match="did not become ready"),
        ):
            gm.ensure_docker_running(timeout=5)


# ---------------------------------------------------------------------------
# image_exists
# ---------------------------------------------------------------------------


class TestImageExists:
    def test_returns_true_when_inspect_succeeds(self) -> None:
        with patch("subprocess.run", return_value=_run_result(0)):
            assert GatewayManager().image_exists() is True

    def test_returns_false_when_inspect_fails(self) -> None:
        with patch("subprocess.run", return_value=_run_result(1)):
            assert GatewayManager().image_exists() is False


# ---------------------------------------------------------------------------
# build_image
# ---------------------------------------------------------------------------


class TestBuildImage:
    def test_calls_docker_build_with_correct_args(self) -> None:
        gm = GatewayManager()
        with patch("subprocess.run") as mock_run:
            gm.build_image()
        args = mock_run.call_args.args[0]
        assert args[0] == "docker"
        assert args[1] == "build"
        assert "-t" in args
        assert GatewayManager.IMAGE_NAME in args

    def test_build_image_wraps_called_process_error_as_gateway_error(self) -> None:
        import subprocess

        gm = GatewayManager()
        with (
            patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "docker")),
            pytest.raises(GatewayError, match="build"),
        ):
            gm.build_image()

    def test_start_wraps_called_process_error_as_gateway_error(self) -> None:
        import subprocess

        gm = GatewayManager()
        with (
            patch.object(gm, "ensure_docker_running"),
            patch.object(gm, "_is_current", return_value=False),
            patch.object(gm, "container_exists", return_value=False),
            patch.object(gm, "image_exists", return_value=True),
            patch("subprocess.run", side_effect=subprocess.CalledProcessError(125, "docker")),
            pytest.raises(GatewayError, match="port"),
        ):
            gm.start()


# ---------------------------------------------------------------------------
# start / stop / restart
# ---------------------------------------------------------------------------


class TestStart:
    def test_a_current_container_is_restarted_in_place(self) -> None:
        """Nothing is removed or run anew, so the container's own files — the gateway's log, the
        one place a refused login shows — are kept (register F43). `docker restart`, not `docker
        start`: it gives a running container a new process too (measured 2026-11-07), and
        `start()` ends on a clean, unauthenticated session either way."""
        gm = GatewayManager()
        run, calls = _fake_docker(_container_made_by(gm))
        with patch("subprocess.run", side_effect=run):
            gm.start()
        assert ["docker", "restart", "ibkr_core_gateway"] in calls
        assert _verbs(calls) == ["restart"], calls

    @pytest.mark.parametrize(
        "made",
        [
            pytest.param(
                lambda: _container_made_by(GatewayManager()) | {"Image": "sha256:" + "0" * 64},
                id="an-older-image",
            ),
            pytest.param(lambda: _container_made_by(GatewayManager(port=5056)), id="other-run-options"),
            pytest.param(
                lambda: _published_beyond_loopback(_container_made_by(GatewayManager())),
                id="published-beyond-loopback",
            ),
            pytest.param(
                lambda: {"Image": _IMAGE_ID, "Config": {"Labels": {"org.opencontainers.image.title": "ubuntu"}}},
                id="not-this-label",
            ),
            pytest.param(lambda: {"Image": _IMAGE_ID, "Config": {"Labels": None}}, id="no-labels-at-all"),
        ],
    )
    def test_a_container_that_is_not_current_is_removed_and_run_anew(
        self, made: Callable[[], dict[str, object]]
    ) -> None:
        """Docker Compose's rule: recreate when "the service's configuration or image was changed
        after the container's creation" (docs.docker.com/reference/cli/docker/compose/up/). The
        image by id, so a rebuild takes effect; the run options by the label `start()` writes, so
        a changed port, binding or variable does too. A container without that label — every one
        made before 2.2.0, or one made by hand — is never taken for current."""
        gm = GatewayManager()
        run, calls = _fake_docker(made())
        with patch("subprocess.run", side_effect=run):
            gm.start()
        assert _verbs(calls) == ["stop", "rm", "run"], calls

    def test_the_label_records_every_option_the_container_is_run_with(self) -> None:
        """One list feeds `docker run` and the label, so nothing reaches the container unrecorded:
        an option added beside that list would never be compared, and a container made without it
        would be restarted in place as current."""
        run, calls = _fake_docker(None)
        with patch("subprocess.run", side_effect=run):
            GatewayManager().start()
        argv = next(argv for argv in calls if argv[1] == "run")
        label = argv[argv.index("--label") + 1]
        recorded = label.partition("=")[2]
        assert argv == [
            "docker",
            "run",
            "-d",
            "--name",
            "ibkr_core_gateway",
            "--label",
            label,
            *recorded.split(" "),
            "ibkr-core-gateway",
        ]

    def test_a_container_docker_will_not_restart_is_removed_and_run_anew(self) -> None:
        """So reusing a container never leaves the gateway down where recreating it would not."""
        gm = GatewayManager()
        run, calls = _fake_docker(_container_made_by(gm), restart_rc=1)
        with patch("subprocess.run", side_effect=run):
            gm.start()
        assert _verbs(calls) == ["restart", "stop", "rm", "run"], calls

    def test_builds_image_when_missing(self) -> None:
        gm = GatewayManager()
        with (
            patch.object(gm, "ensure_docker_running"),
            patch.object(gm, "_is_current", return_value=False),
            patch.object(gm, "container_exists", return_value=False),
            patch.object(gm, "image_exists", return_value=False),
            patch.object(gm, "build_image") as mock_build,
            patch("subprocess.run"),
        ):
            gm.start()
        mock_build.assert_called_once()

    def test_docker_run_includes_port_and_env_vars(self) -> None:
        gm = GatewayManager(port=5055)
        with (
            patch.object(gm, "ensure_docker_running"),
            patch.object(gm, "_is_current", return_value=False),
            patch.object(gm, "container_exists", return_value=False),
            patch.object(gm, "image_exists", return_value=True),
            patch("subprocess.run") as mock_run,
        ):
            gm.start()
        args = mock_run.call_args.args[0]
        joined = " ".join(str(a) for a in args)
        assert "GATEWAY_PORT=5055" in joined

    def test_no_tickle_env_reaches_the_container(self) -> None:
        """Nothing in the image reads a TICKLE_* variable, so nothing may pass one.

        Until 2026-08-07 `start()` passed TICKLE_BASE_URL / TICKLE_INTERVAL /
        TICKLE_ENDPOINT and this suite *asserted* one of them was there — pinning dead
        behaviour in place. `tickler.sh` was removed from the image on 2026-08-06 and
        deleted outright on 2026-08-07; renewal is the caller's, because a loop inside
        the container cannot see the host-side suspend flag that coordinates a login.

        Asserted as an absence over every argument rather than on a count, so a
        reintroduction under any of the three names fails here.
        """
        gm = GatewayManager(port=5055)
        with (
            patch.object(gm, "ensure_docker_running"),
            patch.object(gm, "_is_current", return_value=False),
            patch.object(gm, "container_exists", return_value=False),
            patch.object(gm, "image_exists", return_value=True),
            patch("subprocess.run") as mock_run,
        ):
            gm.start()
        joined = " ".join(str(a) for a in mock_run.call_args.args[0])
        assert "TICKLE" not in joined.upper(), joined

    def test_docker_run_binds_port_to_loopback_only(self) -> None:
        """The gateway holds an authenticated IBKR session with no gate enforcement
        of its own — publishing beyond loopback makes it reachable from the LAN.
        See docs/audits/security-audit-2026-07-11.md H-3."""
        gm = GatewayManager(port=5055)
        with (
            patch.object(gm, "ensure_docker_running"),
            patch.object(gm, "_is_current", return_value=False),
            patch.object(gm, "container_exists", return_value=False),
            patch.object(gm, "image_exists", return_value=True),
            patch("subprocess.run") as mock_run,
        ):
            gm.start()
        args = mock_run.call_args.args[0]
        assert "-p" in args
        p_value = args[args.index("-p") + 1]
        assert p_value == "127.0.0.1:5055:5055", f"expected loopback-only publish, got {p_value!r}"


class TestStop:
    def test_calls_docker_stop_and_rm(self) -> None:
        gm = GatewayManager()
        with patch("subprocess.run") as mock_run:
            gm.stop()
        commands = [c.args[0] for c in mock_run.call_args_list]
        assert any("stop" in cmd for cmd in commands)
        assert any("rm" in cmd for cmd in commands)

    def test_stop_is_idempotent_even_when_not_running(self) -> None:
        gm = GatewayManager()
        # capture_output=True means returncode is ignored — no exception expected
        with patch("subprocess.run", return_value=_run_result(1)):
            gm.stop()  # should not raise


class TestRestart:
    def test_restart_restarts_a_current_container_in_place(self) -> None:
        """`restart()` is `start()`: a `stop()` first would remove the container — and the log
        register F43 keeps — for nothing, since `start()` already ends on a fresh process."""
        gm = GatewayManager()
        run, calls = _fake_docker(_container_made_by(gm))
        with patch("subprocess.run", side_effect=run):
            gm.restart()
        assert _verbs(calls) == ["restart"], calls


# ---------------------------------------------------------------------------
# is_running
# ---------------------------------------------------------------------------


class TestIsRunning:
    def test_returns_true_when_container_running(self) -> None:
        with patch("subprocess.run", return_value=_run_result(0, stdout="true\n")):
            assert GatewayManager().is_running() is True

    def test_returns_false_when_container_stopped(self) -> None:
        with patch("subprocess.run", return_value=_run_result(0, stdout="false\n")):
            assert GatewayManager().is_running() is False

    def test_returns_false_when_container_not_found(self) -> None:
        with patch("subprocess.run", return_value=_run_result(1, stdout="")):
            assert GatewayManager().is_running() is False


# ---------------------------------------------------------------------------
# is_gateway_reachable / is_authenticated
# ---------------------------------------------------------------------------


class TestIsGatewayReachable:
    """The health probe must not renew the session it is asking about.

    Changed from POST to GET on 2026-08-06. `/tickle` is documented as "pings the server
    to prevent the session from ending", so a POST here was a session-affecting write
    dressed as a health check — and `wait_for_gateway` calls it in a polling loop, so
    merely asking "is it up?" renewed the keepalive timer. That is precisely the traffic
    the host-side suspend flag exists to stop during a login or a recovery.
    """

    def test_uses_get_not_post(self) -> None:
        """The regression guard: a POST here writes to the session."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("requests.get", return_value=mock_resp) as get, patch("requests.post") as post:
            assert GatewayManager().is_gateway_reachable() is True
        get.assert_called_once()
        post.assert_not_called()

    def test_returns_true_on_200(self) -> None:
        """The ordinary healthy case."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("requests.get", return_value=mock_resp):
            assert GatewayManager().is_gateway_reachable() is True

    def test_returns_true_on_401(self) -> None:
        """401 is the gateway ANSWERING, not failing.

        It means the process is alive and holds no authenticated session — the best
        moment to log in. Treating it as down told a user "start it first" about a
        gateway that was running perfectly (measured 2026-08-05).
        """
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        with patch("requests.get", return_value=mock_resp):
            assert GatewayManager().is_gateway_reachable() is True

    def test_returns_false_on_connection_error(self, caplog: pytest.LogCaptureFixture) -> None:
        """A refused connection is the one real "not reachable", and is logged at DEBUG."""
        with (
            patch("requests.get", side_effect=requests.ConnectionError()),
            caplog.at_level(logging.DEBUG, logger="ibkr_core_mcp.gateway.manager"),
        ):
            assert GatewayManager().is_gateway_reachable() is False
        debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
        warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert len(debug_records) == 1
        assert warning_records == []

    def test_returns_false_and_warns_on_unexpected_exception(self, caplog: pytest.LogCaptureFixture) -> None:
        """An unexpected exception type is worth a WARNING, unlike a refused connection."""
        with (
            patch("requests.get", side_effect=ValueError("boom")),
            caplog.at_level(logging.DEBUG, logger="ibkr_core_mcp.gateway.manager"),
        ):
            assert GatewayManager().is_gateway_reachable() is False
        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warning_records) == 1


class TestIsAuthenticated:
    def test_returns_true_when_authenticated_flag_set(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"authenticated": True}
        with patch("requests.get", return_value=mock_resp):
            assert GatewayManager().is_authenticated() is True

    def test_returns_false_when_not_authenticated(self, caplog: pytest.LogCaptureFixture) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"authenticated": False}
        with (
            patch("requests.get", return_value=mock_resp),
            caplog.at_level(logging.DEBUG, logger="ibkr_core_mcp.gateway.manager"),
        ):
            assert GatewayManager().is_authenticated() is False
        assert caplog.records == []

    def test_returns_false_and_debug_logs_on_connection_error(self, caplog: pytest.LogCaptureFixture) -> None:
        with (
            patch("requests.get", side_effect=requests.ConnectionError()),
            caplog.at_level(logging.DEBUG, logger="ibkr_core_mcp.gateway.manager"),
        ):
            assert GatewayManager().is_authenticated() is False
        debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
        warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert len(debug_records) == 1
        assert warning_records == []

    def test_returns_false_and_warns_on_unexpected_get_exception(self, caplog: pytest.LogCaptureFixture) -> None:
        with (
            patch("requests.get", side_effect=RuntimeError("boom")),
            caplog.at_level(logging.DEBUG, logger="ibkr_core_mcp.gateway.manager"),
        ):
            assert GatewayManager().is_authenticated() is False
        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warning_records) == 1

    def test_returns_false_and_warns_on_malformed_json(self, caplog: pytest.LogCaptureFixture) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.side_effect = ValueError("bad json")
        with (
            patch("requests.get", return_value=mock_resp),
            caplog.at_level(logging.DEBUG, logger="ibkr_core_mcp.gateway.manager"),
        ):
            assert GatewayManager().is_authenticated() is False
        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warning_records) == 1

    def test_returns_false_on_non_200_status(self, caplog: pytest.LogCaptureFixture) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        with (
            patch("requests.get", return_value=mock_resp),
            caplog.at_level(logging.DEBUG, logger="ibkr_core_mcp.gateway.manager"),
        ):
            assert GatewayManager().is_authenticated() is False
        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warning_records) == 1


# ---------------------------------------------------------------------------
# _poll_until
# ---------------------------------------------------------------------------


class TestPollUntil:
    def test_returns_true_when_check_succeeds_immediately(self) -> None:
        gm = GatewayManager()
        result = gm._poll_until(
            check=lambda: True,
            ready_msg="ready",
            timeout_msg="timed out",
            timeout=10,
            poll_interval=1,
        )
        assert result is True

    def test_returns_false_when_check_never_succeeds(self) -> None:
        gm = GatewayManager()
        with patch("time.sleep"), patch("time.monotonic", side_effect=[0, 1, 2, 99]):
            result = gm._poll_until(
                check=lambda: False,
                ready_msg="ready",
                timeout_msg="timed out",
                timeout=5,
                poll_interval=1,
            )
        assert result is False

    def test_returns_true_on_second_check(self) -> None:
        gm = GatewayManager()
        call_count = {"n": 0}

        def flaky() -> bool:
            call_count["n"] += 1
            return call_count["n"] >= 2

        with patch("time.sleep"), patch("time.monotonic", side_effect=[0, 1, 2, 3]):
            result = gm._poll_until(
                check=flaky,
                ready_msg="ready",
                timeout_msg="timed out",
                timeout=10,
                poll_interval=1,
            )
        assert result is True
        assert call_count["n"] == 2


# ---------------------------------------------------------------------------
# wait_for_gateway / wait_for_auth  (wrapper defaults)
# ---------------------------------------------------------------------------


class TestWaitWrappers:
    def test_wait_for_gateway_delegates_to_poll_until(self) -> None:
        gm = GatewayManager()
        with patch.object(gm, "_poll_until", return_value=True) as mock_poll:
            result = gm.wait_for_gateway(timeout=90, poll_interval=2)
        assert result is True
        # _poll_until is called with positional args: check, ready_msg, timeout_msg, timeout, poll_interval
        args = mock_poll.call_args.args
        assert args[0] == gm.is_gateway_reachable  # check function
        assert args[3] == 90  # timeout
        assert args[4] == 2  # poll_interval

    def test_wait_for_auth_delegates_to_poll_until(self) -> None:
        gm = GatewayManager()
        with patch.object(gm, "_poll_until", return_value=False) as mock_poll:
            result = gm.wait_for_auth(timeout=120, poll_interval=3)
        assert result is False
        args = mock_poll.call_args.args
        assert args[0] == gm.is_authenticated  # check function
        assert args[3] == 120  # timeout
        assert args[4] == 3  # poll_interval


# ---------------------------------------------------------------------------
# The login window (register F44)
# ---------------------------------------------------------------------------


class TestFindChrome:
    """Where Chrome is: a fixed table per platform, then `PATH`; nothing found → `None`."""

    def test_the_macos_app_bundle_when_it_exists(self) -> None:
        """The install measured on 2026-10-13."""
        with (
            patch("platform.system", return_value="Darwin"),
            patch("ibkr_core_mcp.gateway.manager.Path.is_file", return_value=True),
        ):
            assert _find_chrome() == "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

    def test_a_chrome_on_path_when_no_known_install_exists(self) -> None:
        """Linux has no fixed install path; the names are looked up on `PATH`."""
        with (
            patch("platform.system", return_value="Linux"),
            patch(
                "ibkr_core_mcp.gateway.manager.shutil.which",
                side_effect=lambda name: "/usr/bin/chromium" if name == "chromium" else None,
            ),
        ):
            assert _find_chrome() == "/usr/bin/chromium"

    def test_none_when_no_chrome_is_installed(self) -> None:
        """The caller falls back to a browser tab."""
        with (
            patch("platform.system", return_value="Darwin"),
            patch("ibkr_core_mcp.gateway.manager.Path.is_file", return_value=False),
            patch("ibkr_core_mcp.gateway.manager.shutil.which", return_value=None),
        ):
            assert _find_chrome() is None


class TestLoginWindow:
    """`close()` ends the Chrome process `open_login_page()` started, and says whether it did."""

    def test_close_ends_a_running_window_and_says_so(self) -> None:
        """The normal close, at authentication."""
        process = MagicMock(spec=subprocess.Popen)
        process.poll.return_value = None
        assert LoginWindow(process).close() is True
        process.terminate.assert_called_once_with()
        process.kill.assert_not_called()

    def test_close_touches_nothing_when_the_process_had_already_exited(self) -> None:
        """Measured 2026-10-13: a launch on a profile already running exits by itself (rc 0) and
        the running instance opens the window — this handle cannot reach it. Or the operator
        quit it. Either way there is nothing of ours to end."""
        process = MagicMock(spec=subprocess.Popen)
        process.poll.return_value = 0
        assert LoginWindow(process).close() is False
        process.terminate.assert_not_called()

    def test_close_kills_a_window_that_ignores_terminate(self) -> None:
        """Never left hanging: ten seconds, then a kill."""
        process = MagicMock(spec=subprocess.Popen)
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired("chrome", 10), 0]
        assert LoginWindow(process).close() is True
        process.kill.assert_called_once_with()


class TestOpenLoginPage:
    """The login opens in a small Chrome window of its own; no Chrome → today's browser tab."""

    def test_opens_a_login_window_of_its_own(self) -> None:
        """The exact launch, list form: own profile, app mode, the measured 540×680."""
        with (
            patch("ibkr_core_mcp.gateway.manager._find_chrome", return_value="/opt/chrome"),
            patch("ibkr_core_mcp.gateway.manager.Path.home", return_value=Path("/Users/someone")),
            patch("subprocess.Popen") as popen,
            patch("webbrowser.open") as tab,
        ):
            window = GatewayManager(port=5055).open_login_page()
        assert isinstance(window, LoginWindow)
        tab.assert_not_called()
        args, kwargs = popen.call_args
        assert args[0] == [
            "/opt/chrome",
            "--user-data-dir=/Users/someone/.ibkr_core/login-chrome",
            "--no-first-run",
            "--no-default-browser-check",
            "--app=https://localhost:5055",
            "--window-size=540,680",
        ]
        assert kwargs["start_new_session"] is True
        assert "shell" not in kwargs

    def test_the_window_gets_no_secret_from_the_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Only named variables reach Chrome — a host's API keys stay in the host."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-a-key")
        monkeypatch.setenv("PATH", "/usr/bin:/bin")
        with (
            patch("ibkr_core_mcp.gateway.manager._find_chrome", return_value="/opt/chrome"),
            patch("subprocess.Popen") as popen,
            patch("webbrowser.open"),
        ):
            GatewayManager().open_login_page()
        env = popen.call_args.kwargs["env"]
        assert "ANTHROPIC_API_KEY" not in env
        assert env["PATH"] == "/usr/bin:/bin"
        assert set(env) <= set(_LOGIN_WINDOW_ENV)

    @pytest.mark.parametrize(
        ("chrome", "popen_error"),
        [(None, None), ("/opt/chrome", OSError("not executable"))],
        ids=["no-chrome", "chrome-will-not-start"],
    )
    def test_falls_back_to_a_browser_tab(self, chrome: str | None, popen_error: Exception | None) -> None:
        """Today's behaviour, and no handle: there is no window of ours to close."""
        with (
            patch("ibkr_core_mcp.gateway.manager._find_chrome", return_value=chrome),
            patch("subprocess.Popen", side_effect=popen_error),
            patch("webbrowser.open") as tab,
        ):
            assert GatewayManager(port=5055).open_login_page() is None
        tab.assert_called_once_with("https://localhost:5055")


class TestStartupClosesTheLoginWindow:
    """`startup()` closes the window it opened once the session is verified, and only then."""

    @staticmethod
    def _run(*, verified: bool, on_retry: bool, ours: bool = True) -> MagicMock:
        gm = GatewayManager()
        window = MagicMock(spec=LoginWindow)
        window.close.return_value = ours
        with (
            patch.object(gm, "ensure_docker_running"),
            patch.object(gm, "is_running", return_value=True),
            patch.object(gm, "is_authenticated", side_effect=[False, on_retry]),
            patch.object(gm, "wait_for_gateway", return_value=True),
            patch.object(gm, "open_login_page", return_value=window),
            patch.object(gm, "wait_for_auth", return_value=verified),
            patch("builtins.input", return_value=""),
        ):
            gm.startup()
        return window

    @pytest.mark.parametrize(
        ("verified", "on_retry"),
        [(True, False), (False, True)],
        ids=["verified", "verified-on-retry"],
    )
    def test_a_verified_session_closes_the_window(self, verified: bool, on_retry: bool) -> None:
        """Authenticated → the window's job is done."""
        assert self._run(verified=verified, on_retry=on_retry).close.call_count == 1

    def test_an_unverified_session_leaves_the_window_open(self) -> None:
        """A failed login stays on screen, as a tab did (operator 2026-10-13: "Do not auto-close
        if it fails")."""
        assert self._run(verified=False, on_retry=False).close.call_count == 0

    def test_a_window_that_was_not_ours_to_close_is_named(self, capsys: pytest.CaptureFixture[str]) -> None:
        """The launch went to a Chrome already running on the login profile, or the operator
        quit it: said, not hidden."""
        self._run(verified=True, on_retry=False, ours=False)
        assert "Close the login window yourself" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# The gateway's own log, read in-container (register F45, condition D)
# ---------------------------------------------------------------------------
#
# Moved from the consumer that wrote the read (its `read_login_events` took the container's name
# as an argument); here the command is built from `GatewayManager.CONTAINER_NAME` and the module's
# constants only, so no caller can hand `docker exec` a name — or an option — of its own.

_PHRASE_LINE = "/app/api_gateway/logs/gw.2026-10-07.log:17:53:14.123 filler Client login succeeds\n"


class TestReadLoginEvents:
    def test_the_log_read_is_one_shell_free_bounded_command(self) -> None:
        """List form, never a shell: here not even inside the container, because grep's own
        `--include` picks the dated files (measured 2026-10-12: the same 93 lines as the shell
        glob) — and a command that ends on its own, the timeout only a backstop (stopping a
        `docker exec` client leaves its command running in the container, measured that day)."""
        with patch("subprocess.run") as run:
            run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            read_login_events()

        phrases = [arg for phrase in LOGIN_PHRASES for arg in ("-e", phrase)]
        assert run.call_args.args[0] == [
            "docker",
            "exec",
            "ibkr_core_gateway",
            "grep",
            "-rHF",
            "--include=gw.[0-9]*.log",
            *phrases,
            "/app/api_gateway/logs",
        ]
        assert run.call_args.kwargs["timeout"] > 0
        assert "shell" not in run.call_args.kwargs

    def test_the_command_is_built_from_constants_and_takes_no_container_argument(self) -> None:
        """Condition D. The container is the class constant and the directory the module's; the one
        parameter is the timeout. A `container` parameter would be a value a caller — one day a
        model-derived one — could hand to `docker exec`, and a value beginning with `-` is read by
        docker as an option (OS Command Injection cheat sheet: every command injection is also an
        argument injection)."""
        assert list(inspect.signature(read_login_events).parameters) == ["timeout"]
        assert GATEWAY_LOG_DIR == "/app/api_gateway/logs"

    def test_the_docker_cli_gets_path_home_and_docker_variables_only(self) -> None:
        """The spawn recipe's explicit environment: nothing of the host's — an API key included —
        reaches the child. Measured 2026-10-12: PATH alone runs `docker exec` here; HOME holds
        the CLI's configuration, DOCKER_* choose a daemon."""
        environment = {
            "PATH": "/usr/bin",
            "HOME": "/home/operator",
            "DOCKER_HOST": "unix:///probe.sock",
            "ANTHROPIC_API_KEY": "sk-not-a-real-key",
            "IBKR_GATEWAY_URL": "https://localhost:5055/v1/api",
        }
        with patch.dict(os.environ, environment, clear=True), patch("subprocess.run") as run:
            run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            read_login_events()

        assert run.call_args.kwargs["env"] == {
            "PATH": "/usr/bin",
            "HOME": "/home/operator",
            "DOCKER_HOST": "unix:///probe.sock",
        }

    @pytest.mark.parametrize(
        ("outcome", "expected"),
        [
            (
                MagicMock(returncode=0, stdout=_PHRASE_LINE, stderr=""),
                ([LoginEvent("2026-10-07 17:53:14", "login", "")], ""),
            ),
            (MagicMock(returncode=1, stdout="", stderr=""), ([], "")),
            (
                MagicMock(
                    returncode=1,
                    stdout="",
                    stderr="Error response from daemon: No such container: ibkr_core_gateway\n",
                ),
                (None, "Error response from daemon: No such container: ibkr_core_gateway"),
            ),
            (
                MagicMock(
                    returncode=2,
                    stdout=_PHRASE_LINE,
                    stderr="grep: /app/api_gateway/logs/x.log: No such file or directory\n",
                ),
                (None, "grep: /app/api_gateway/logs/x.log: No such file or directory"),
            ),
            (
                MagicMock(
                    returncode=0,
                    stdout="/app/api_gateway/logs/gw.2026-10-07.log:no time giving up\n",
                    stderr="",
                ),
                # Condition G: the format refusal passes `redact_error` too, so its type name leads.
                (None, "ValueError: gateway log format not recognised: a 'giving up' line has no leading time"),
            ),
            (
                OSError(2, "No such file or directory", "docker"),
                # Condition G: the OSError's text passes `redact_error` — its type name leads.
                (None, "docker could not be run: FileNotFoundError: [Errno 2] No such file or directory: 'docker'"),
            ),
            (subprocess.TimeoutExpired(["docker"], 15), (None, "docker did not answer within 15 s")),
        ],
        ids=[
            "read",
            "no-line-matched-is-no-login",
            "no-such-container-also-exits-1",
            "a-partial-read-is-not-parsed",
            "a-line-without-a-time",
            "no-docker-program",
            "timed-out",
        ],
    )
    def test_the_log_read_fails_open_with_its_reason(self, outcome: object, expected: object) -> None:
        """The exit rule, measured 2026-10-12 against the real container: 0 → parse; 1 with an
        empty stderr → nothing matched; anything else → unreadable, stderr's first line the reason.
        Exit 1 alone cannot tell "no line matched" from "no such container" — only stderr does —
        and a partial read prints lines AND exits 2: those lines are never used, since what the
        missing file held is exactly what would make the verdict answer about an older login."""
        effect = {"side_effect": outcome} if isinstance(outcome, BaseException) else {"return_value": outcome}
        with patch("subprocess.run", **effect):
            assert read_login_events() == expected
