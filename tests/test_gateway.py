"""Unit tests for GatewayManager — all Docker/network calls mocked."""
from __future__ import annotations

import platform
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import requests

from ibkr_core_mcp.exceptions import GatewayError
from ibkr_core_mcp.gateway import GatewayManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_result(returncode: int, stdout: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout)


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
        ):
            with pytest.raises(GatewayError, match="Docker is not running"):
                gm.ensure_docker_running()

    def test_raises_on_macos_if_docker_never_becomes_ready(self) -> None:
        gm = GatewayManager()
        with (
            patch.object(gm, "is_docker_available", return_value=False),
            patch("platform.system", return_value="Darwin"),
            patch("subprocess.run"),
            patch("time.sleep"),
            patch("time.monotonic", side_effect=[0, 999]),  # deadline passed immediately
        ):
            with pytest.raises(GatewayError, match="did not become ready"):
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


# ---------------------------------------------------------------------------
# start / stop / restart
# ---------------------------------------------------------------------------

class TestStart:
    def test_stops_existing_container_before_starting(self) -> None:
        gm = GatewayManager()
        with (
            patch.object(gm, "ensure_docker_running"),
            patch.object(gm, "is_running", return_value=True),
            patch.object(gm, "stop") as mock_stop,
            patch.object(gm, "image_exists", return_value=True),
            patch("subprocess.run"),
        ):
            gm.start()
        mock_stop.assert_called_once()

    def test_builds_image_when_missing(self) -> None:
        gm = GatewayManager()
        with (
            patch.object(gm, "ensure_docker_running"),
            patch.object(gm, "is_running", return_value=False),
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
            patch.object(gm, "is_running", return_value=False),
            patch.object(gm, "image_exists", return_value=True),
            patch("subprocess.run") as mock_run,
        ):
            gm.start()
        args = mock_run.call_args.args[0]
        joined = " ".join(str(a) for a in args)
        assert "5055:5055" in joined
        assert "GATEWAY_PORT=5055" in joined
        assert "TICKLE_INTERVAL=60" in joined


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
    def test_calls_stop_then_start(self) -> None:
        gm = GatewayManager()
        with (
            patch.object(gm, "stop") as mock_stop,
            patch.object(gm, "start") as mock_start,
        ):
            gm.restart()
        assert mock_stop.call_count == 1
        assert mock_start.call_count == 1


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
    def test_returns_true_on_200(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("requests.post", return_value=mock_resp):
            assert GatewayManager().is_gateway_reachable() is True

    def test_returns_true_on_any_http_response(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 401  # gateway up but session not auth'd
        with patch("requests.post", return_value=mock_resp):
            assert GatewayManager().is_gateway_reachable() is True

    def test_returns_false_on_connection_error(self) -> None:
        with patch("requests.post", side_effect=requests.ConnectionError()):
            assert GatewayManager().is_gateway_reachable() is False


class TestIsAuthenticated:
    def test_returns_true_when_authenticated_flag_set(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"authenticated": True}
        with patch("requests.get", return_value=mock_resp):
            assert GatewayManager().is_authenticated() is True

    def test_returns_false_when_not_authenticated(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"authenticated": False}
        with patch("requests.get", return_value=mock_resp):
            assert GatewayManager().is_authenticated() is False

    def test_returns_false_on_exception(self) -> None:
        with patch("requests.get", side_effect=Exception("network error")):
            assert GatewayManager().is_authenticated() is False

    def test_returns_false_on_non_200_status(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        with patch("requests.get", return_value=mock_resp):
            assert GatewayManager().is_authenticated() is False


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
        assert args[3] == 90                        # timeout
        assert args[4] == 2                         # poll_interval

    def test_wait_for_auth_delegates_to_poll_until(self) -> None:
        gm = GatewayManager()
        with patch.object(gm, "_poll_until", return_value=False) as mock_poll:
            result = gm.wait_for_auth(timeout=120, poll_interval=3)
        assert result is False
        args = mock_poll.call_args.args
        assert args[0] == gm.is_authenticated  # check function
        assert args[3] == 120                   # timeout
        assert args[4] == 3                     # poll_interval
