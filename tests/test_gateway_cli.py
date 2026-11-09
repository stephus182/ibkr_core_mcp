"""Tests for `python -m ibkr_core_mcp.gateway` — the operator's command line over the gateway.

Presentation only. Every decision about the session belongs to `preflight` (the readings and
the rule) and, from step 2, to the owner; this module turns them into lines and exit codes a
shell can branch on. Step 1 (register F45): `preflight` and `diagnose`, the consumer's two
read-only commands, their tests moved here with the module names changed. `up`, `reset` and
`keepalive` arrive with step 2.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from ibkr_core_mcp.gateway import __main__ as cli
from ibkr_core_mcp.gateway.__main__ import main
from ibkr_core_mcp.gateway.preflight import EXIT_READY, EXIT_REFUSED, GatewayState, LoginEvent
from tests.security.structural import spawn_sites

_MOD = "ibkr_core_mcp.gateway.__main__"
_LIVE = GatewayState(reachable=True, authenticated=True, connected=True)
_FREE = GatewayState(reachable=True)
_REFUSED = [
    LoginEvent("2026-10-07 18:00:00", "login", ""),
    LoginEvent("2026-10-07 18:00:01", "validate", "401"),
    LoginEvent("2026-10-07 18:00:13", "giving up", ""),
]
_A_REFUSAL_AFTER_A_GOOD_LOGIN = [
    LoginEvent("2026-10-07 17:00:00", "login", ""),
    LoginEvent("2026-10-07 17:00:00", "authenticated", ""),
    LoginEvent("2026-10-07 18:13:51", "login", ""),
    LoginEvent("2026-10-07 18:13:51", "validate", "401"),
    LoginEvent("2026-10-07 18:13:51", "retry", "7"),
    LoginEvent("2026-10-07 18:13:51", "giving up", ""),
]


# ── preflight ────────────────────────────────────────────────────────────────


def test_preflight_exits_with_the_refined_verdict(capsys):
    """`python -m ibkr_core_mcp.gateway preflight` is the runbook's first step; a shell branches on
    its exit code, and after a FREE reading the gateway's own log refines it."""
    with (
        patch(f"{_MOD}.read_state", return_value=_FREE),
        patch(f"{_MOD}.read_login_events", return_value=(_REFUSED, "")),
    ):
        assert main(["preflight"]) == EXIT_REFUSED
    assert capsys.readouterr().out.startswith("[REFUSED] IBKR refused the last gateway login")


def test_a_reading_that_is_not_free_runs_no_log_read():
    """The `docker exec` runs only where it can change the answer."""
    with (
        patch(f"{_MOD}.read_state", return_value=_LIVE),
        patch(f"{_MOD}.read_login_events") as read,
    ):
        assert main(["preflight"]) == EXIT_READY
    read.assert_not_called()


def test_preflight_prints_the_verdict_block_and_the_flags(capsys):
    """The one word in brackets, the headline, the guidance paragraphs indented, then the flags of a
    reachable reading — the lines the consumer's command printed, word for word."""
    with (
        patch(f"{_MOD}.read_state", return_value=_FREE),
        patch(f"{_MOD}.read_login_events", return_value=([], "")),
    ):
        main(["preflight"])
    out = capsys.readouterr().out
    assert out.startswith("[FREE] The gateway holds no session\n")
    assert "  The gateway's log records no login." in out
    assert "  authenticated=False  connected=False  competing=False  collision=False" in out


# ── diagnose ─────────────────────────────────────────────────────────────────


def test_diagnose_touches_nothing(capsys):
    """A diagnostic that can change the thing it inspects is not a diagnostic: two GETs, one log
    read, no POST, no manager."""
    with (
        patch(f"{_MOD}.read_state", return_value=_FREE),
        patch(f"{_MOD}.read_login_events", return_value=([], "")),
        patch("ibkr_core_mcp.gateway.preflight.requests.post") as post,
    ):
        assert main(["diagnose"]) == 0
    post.assert_not_called()
    assert "The gateway holds no session" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("events", "problem", "block"),
    [
        (
            _A_REFUSAL_AFTER_A_GOOD_LOGIN,
            "",
            [
                "Gateway log — the last login and what followed (4 events; 2 earlier not shown):",
                "  2026-10-07 18:13:51 UTC  login",
                "  2026-10-07 18:13:51 UTC  validate 401",
                "  2026-10-07 18:13:51 UTC  retry 7",
                "  2026-10-07 18:13:51 UTC  giving up",
            ],
        ),
        (
            [LoginEvent("2026-10-09 19:51:22", "giving up", "")],
            "",
            [
                "Gateway log — no login recorded; the last 1 events:",
                "  2026-10-09 19:51:22 UTC  giving up",
            ],
        ),
        (
            None,
            "Error response from daemon: No such container: x",
            ["The gateway's own log could not be read: Error response from daemon: No such container: x"],
        ),
    ],
    ids=["from-the-newest-login", "no-login-recorded", "unreadable"],
)
def test_diagnose_prints_the_last_login_and_what_followed(capsys, events, problem, block):
    """Not the raw log: the consumer's first diagnostic printed its last 60 lines minus DEBUG, and
    on 2026-10-12 two of the 39 it would have printed carried the account number. The timeline is
    time, event and code, from the newest login — where the answer is."""
    with (
        patch(f"{_MOD}.read_state", return_value=_FREE),
        patch(f"{_MOD}.read_login_events", return_value=(events, problem)),
    ):
        main(["diagnose"])
    out = capsys.readouterr().out
    assert "\n".join(f"  {line}" for line in block) in out


def test_diagnose_never_prints_the_user_id_and_its_flags_line_no_username(capsys):
    """The user id nowhere (no reader acts on the number, and this output is pasted into records);
    the username only where a BORROWED verdict says whose session it is — the flags line reads
    both as set or empty."""
    state = GatewayState(reachable=True, user_id=12345678, sso_user="synthetic_user", sso_valid=True)
    with (
        patch(f"{_MOD}.read_state", return_value=state),
        patch(f"{_MOD}.read_login_events", return_value=([], "")),
    ):
        main(["diagnose"])
    out = capsys.readouterr().out
    flags = next(line for line in out.splitlines() if line.lstrip().startswith("reachable="))
    assert "12345678" not in out
    assert "synthetic_user" not in flags
    assert "user_id=set" in flags and "sso_user=set" in flags


def test_diagnose_reads_a_free_gateway_through_its_log():
    """The refinement the preflight applies, applied here too: a FREE reading whose last login IBKR
    refused is REFUSED, and `diagnose`'s rule maps it to 3 — something blocks a login."""
    with (
        patch(f"{_MOD}.read_state", return_value=_FREE),
        patch(f"{_MOD}.read_login_events", return_value=(_A_REFUSAL_AFTER_A_GOOD_LOGIN, "")),
    ):
        assert main(["diagnose"]) == 3


# ── --env-file, the URL, and the shape of the module ─────────────────────────


@pytest.mark.parametrize("command", ["preflight", "diagnose"])
def test_env_file_is_the_one_url_read_and_a_non_loopback_url_exits_1_before_any_request(
    command, tmp_path, monkeypatch, capsys
):
    """`--env-file` is what `Config.from_env` reads; a URL that is not loopback is printed and exits 1
    with nothing sent (condition C, at the command line)."""
    monkeypatch.delenv("IBKR_GATEWAY_URL", raising=False)
    env = tmp_path / ".env"
    env.write_text("IBKR_GATEWAY_URL=https://gateway.example.invalid/v1/api\n")
    env.chmod(0o600)
    with patch(f"{_MOD}.read_state") as read:
        assert main([command, "--env-file", str(env)]) == 1
    read.assert_not_called()
    assert "localhost" in capsys.readouterr().err


def test_env_file_names_the_gateway_the_readings_go_to(tmp_path, monkeypatch):
    monkeypatch.delenv("IBKR_GATEWAY_URL", raising=False)
    env = tmp_path / ".env"
    env.write_text("IBKR_GATEWAY_URL=https://127.0.0.1:5056/v1/api/\n")
    env.chmod(0o600)
    with (
        patch(f"{_MOD}.read_state", return_value=_LIVE) as read,
        patch(f"{_MOD}.read_login_events", return_value=([], "")),
    ):
        main(["preflight", "--env-file", str(env)])
    assert read.call_args.args[0] == "https://127.0.0.1:5056/v1/api"


def test_help_exits_zero_and_names_the_subcommands(capsys):
    with pytest.raises(SystemExit) as raised:
        main(["--help"])
    assert raised.value.code == 0
    out = capsys.readouterr().out
    assert "preflight" in out and "diagnose" in out


def test_no_subcommand_is_a_usage_error():
    with pytest.raises(SystemExit) as raised:
        main([])
    assert raised.value.code == 2


def test_the_command_line_spawns_nothing_itself():
    """The spawn stays in `gateway/manager.py` (`ALLOWED_SPAWN_MODULES`): the command line imports
    `read_login_events` and never `subprocess`."""
    source = Path(cli.__file__).read_text()
    assert spawn_sites(source) == set()
    assert "subprocess" not in {n.id for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Name)}


def test_every_line_is_flushed():
    """Under launchd or a redirected shell stdout is block-buffered, and a command that sits silent
    for its whole wait is indistinguishable from a hang (measured 2026-08-06 by the consumer): every
    `print` in the module passes `flush=True`."""
    source = Path(cli.__file__).read_text()
    prints = [
        n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "print"
    ]
    assert prints, "no print call found — the check would be vacuous"
    unflushed = [n.lineno for n in prints if not any(kw.arg == "flush" for kw in n.keywords)]
    assert unflushed == [], unflushed


def test_the_module_reads_no_environment_but_through_the_loader():
    """No `os.environ` read in the command line: the URL comes through `gateway_api_url`."""
    source = Path(cli.__file__).read_text()
    assert "environ" not in source
    assert os.environ is not None  # the import above is for the assertion's reader
