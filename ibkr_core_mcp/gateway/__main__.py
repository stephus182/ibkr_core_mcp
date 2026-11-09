"""`python -m ibkr_core_mcp.gateway` — the operator's command line over the gateway session.

    python -m ibkr_core_mcp.gateway preflight [--env-file PATH]    exit: the verdict's code, 0–6
    python -m ibkr_core_mcp.gateway diagnose  [--env-file PATH]    exit: 0 on READY or FREE, else 3

Presentation only. Every decision about the session — what a reading means, whether a login
may start — belongs to `preflight` (the readings and the rule) and, from step 2 of register
F45, to the session owner; this module turns them into lines and exit codes a shell can branch
on, so a script, a button and a hand on the keyboard cannot drift apart.

`preflight` prints one verdict block: the one word in brackets, the headline, the guidance,
then the flags of a reachable reading; after a FREE reading the gateway's own log refines it
(`manager.read_login_events`, the one process spawn, which lives in the manager — this module
never imports `subprocess`). Run it before touching the login page: only one brokerage session
exists per username across Client Portal, TWS and IBKR Mobile, and a needless re-login is
what escalates into the IB Key challenge/response.

`diagnose` prints the headline, the guidance, the flags and the login timeline — time, event
and code per line, from the newest login — and touches nothing: two GETs and one log read.

`--env-file` is the path `Config.from_env` reads (a host's `.env`); the default is the loader's
own search. A gateway URL that is not loopback is printed and exits 1 **before any request**.
Nothing here prints the IBKR user id; the username appears only in a BORROWED verdict, where
it says whose session the gateway is holding. Every line is flushed: under launchd or a
redirected shell stdout is block-buffered, and a command silent for its whole wait is
indistinguishable from a hang.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from ibkr_core_mcp.exceptions import ConfigError
from ibkr_core_mcp.gateway.manager import read_login_events
from ibkr_core_mcp.gateway.preflight import (
    _MARK,
    EXIT_FREE,
    EXIT_READY,
    GatewayState,
    LoginEvent,
    gateway_api_url,
    newest_login_index,
    read_state,
    refine_with_log,
    verdict,
)
from ibkr_core_mcp.redaction import redact_error


def _say(line: str = "", *, err: bool = False) -> None:
    """Print one line and flush it — the only way this module writes."""
    print(line, file=sys.stderr if err else sys.stdout, flush=True)


def _report(state: GatewayState, found: tuple[int, str, str]) -> int:
    """Print one verdict block — `found`, read from `state` — and return its exit code."""
    code, headline, guidance = found
    _say(f"[{_MARK[code]}] {headline}\n")
    _say("\n\n".join(f"  {paragraph}" for paragraph in guidance.split("\n\n")) + "\n")
    if state.reachable:
        _say(
            f"  authenticated={state.authenticated}  connected={state.connected}  "
            f"competing={state.competing}  collision={state.collision}"
        )
        if state.client_app:
            _say(f"  sso owner={state.client_app}  user={state.sso_user}")
        if state.sso_expires_ms is not None:
            _say(f"  sso expires in ~{state.sso_expires_ms / 60000:.1f} min")
    return code


def _flags(state: GatewayState) -> str:
    """A reading's flags for `diagnose` — not `repr(state)`, which would carry the IBKR user id
    and the username. Those two read only "set" or "empty"; a field added to `GatewayState`
    later is not printed until named here."""
    return (
        f"reachable={state.reachable} authenticated={state.authenticated} "
        f"connected={state.connected} competing={state.competing} collision={state.collision} "
        f"sso_valid={state.sso_valid} client_app={state.client_app or '—'} "
        f"sso_expires_ms={state.sso_expires_ms} "
        f"user_id={'set' if state.user_id is not None else 'empty'} "
        f"sso_user={'set' if state.sso_user else 'empty'} detail={state.detail!r}"
    )


def login_timeline(events: Sequence[LoginEvent] | None, problem: str) -> list[str]:
    """`diagnose`'s view of the gateway's log: the newest login and what followed it.

    Time, event and code per line — never a line of the log, which carries the username,
    cookies and device ids (and, in the consumer's first diagnostic, the account number in 2
    of 39 printed lines, 2026-10-12). With no login recorded, the last 20 events are shown — a
    refused sequence is 12 at most, measured.
    """
    if events is None:
        return [f"The gateway's own log could not be read: {problem}"]
    newest = newest_login_index(events)
    if newest is None:
        shown = list(events[-20:])
        head = f"Gateway log — no login recorded; the last {len(shown)} events:"
    else:
        shown = list(events[newest:])
        head = (
            f"Gateway log — the last login and what followed ({len(shown)} events; "
            f"{len(events) - len(shown)} earlier not shown):"
        )
    return [head] + [f"  {e.at} UTC  {e.event}{' ' + e.code if e.code else ''}" for e in shown]


def _preflight(url: str) -> int:
    """The verdict, refined by the gateway's own log after a FREE reading; exit = its code."""
    state = read_state(url)
    found = verdict(state)
    if found[0] == EXIT_FREE:
        found = refine_with_log(found, *read_login_events())
    return _report(state, found)


def _diagnose(url: str) -> int:
    """The reading, the guidance, the flags and the login timeline; 0 on READY or FREE, else 3."""
    state = read_state(url)
    events, problem = read_login_events()
    code, headline, guidance = refine_with_log(verdict(state), events, problem)
    _say(f"  {headline}")
    for paragraph in guidance.split("\n\n"):
        _say(f"  {paragraph}")
    _say()
    _say(f"  {_flags(state)}")
    _say()
    _say("─" * 72)
    for line in login_timeline(events, problem):
        _say(f"  {line}")
    return 0 if code in (EXIT_READY, EXIT_FREE) else 3


def build_parser() -> argparse.ArgumentParser:
    """The command line: one subcommand per operation, each taking `--env-file`."""
    parser = argparse.ArgumentParser(
        prog="python -m ibkr_core_mcp.gateway",
        description="The IBKR Client Portal Gateway session, from the operator's side: read it before touching it.",
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="command")
    for name, run, help_text in (
        (
            "preflight",
            _preflight,
            "read the session (two GETs; the gateway's log after a FREE reading) and exit with the verdict's code",
        ),
        (
            "diagnose",
            _diagnose,
            "the reading, its guidance, the flags and the login timeline; exit 0 on READY or FREE, else 3",
        ),
    ):
        command = commands.add_parser(name, help=help_text, description=help_text)
        command.add_argument(
            "--env-file",
            metavar="PATH",
            default=None,
            help="the .env Config.from_env reads (default: the loader's own search)",
        )
        command.set_defaults(run=run)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse, read the URL through the one loader, run the subcommand; its exit code."""
    args = build_parser().parse_args(argv)
    try:
        url = gateway_api_url(args.env_file)
    except ConfigError as exc:
        _say(redact_error(exc), err=True)
        return 1
    result: int = args.run(url)
    return result


if __name__ == "__main__":
    sys.exit(main())
