"""Unit tests for GatewayManager — all Docker/network calls mocked."""

from __future__ import annotations

import logging
import platform
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import requests

from ibkr_core_mcp.exceptions import GatewayError
from ibkr_core_mcp.gateway import GatewayManager, LoginWindow
from ibkr_core_mcp.gateway.manager import _LOGIN_WINDOW_ENV, _find_chrome

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
    def test_stops_existing_container_before_starting(self) -> None:
        gm = GatewayManager()
        with (
            patch.object(gm, "ensure_docker_running"),
            patch.object(gm, "container_exists", return_value=True),
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
