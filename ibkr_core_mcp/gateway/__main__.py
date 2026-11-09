"""`python -m ibkr_core_mcp.gateway` — the operator's command line over the gateway session.

    python -m ibkr_core_mcp.gateway preflight [--release] [--env-file PATH]   exit: the verdict's code, 0–6
    python -m ibkr_core_mcp.gateway diagnose  [--env-file PATH]               exit: 0 on READY or FREE, else 3
    python -m ibkr_core_mcp.gateway up        [--wait-timeout S] [--allow-restart] [--env-file PATH]
                                                                              exit: 0 LIVE, 1 DOWN, 3 otherwise
    python -m ibkr_core_mcp.gateway reset     [--force] [--env-file PATH]     exit: the after verdict's code; 1 when refused
    python -m ibkr_core_mcp.gateway keepalive [--print-url] [--interval S] [--env-file PATH]
                                                                              runs until Ctrl-C or SIGTERM; 1 on an unusable URL

Presentation only. Every decision about the session — what a reading means, whether a login
may start, whether a restart may happen — belongs to `preflight` (the readings and the rule)
and to the session owner (`session`, register F45 step 2); this module turns them into lines
and exit codes a shell can branch on, so a script, a button and a hand on the keyboard cannot
drift apart. It constructs a `GatewayManager` and hands it to the owner; it drives none.

`preflight` prints one verdict block: the one word in brackets, the headline, the guidance,
then the flags of a reachable reading; after a FREE reading the gateway's own log refines it
(`manager.read_login_events`, the one process spawn, which lives in the manager — this module
never imports `subprocess`). Run it before touching the login page: only one brokerage session
exists per username across Client Portal, TWS and IBKR Mobile, and a needless re-login is
what escalates into the IB Key challenge/response. `--release` posts `/logout` first — the one
opt-in logout in the package, never run without the flag, and possibly ending an IBKR Mobile
session too (its scope is undocumented) — then re-reads.

`diagnose` prints the headline, the guidance, the flags and the login timeline — time, event
and code per line, from the newest login — and touches nothing: two GETs and one log read.

`up` is the owner's whole sequence — Docker, the container only when none runs, the reading,
the login page only from FREE with every tickler suspended, the wait until confirmed — and
there is no `--no-wait`: opening the page suspends every tickler, and a suspension has to be
bounded by whoever declared it. `--allow-restart` lets a BORROWED session be cleared by a
restart; off by default, since a restart destroys a session.

`reset` prints the verdict, asks the owner to clear the session by restarting the container,
and prints the verdict again. The guard inside `GatewayManager.start()` is what refuses — a
LIVE, REFUSED or VALIDATING session — and this command only prints its reason and exits 1;
`--force` overrides. On a FREE after-reading it says to log in now, while the slot is clear.

`keepalive` is the host-side tickler — the one renewer a login cannot silence in-process, so it
honours the suspend lock — with the `caffeinate -i` assertion held only while the gateway
answers. A launchd or systemd unit runs it with the venv's Python; `--print-url` prints what it
would tickle and contacts nothing. SIGTERM (`launchctl bootout`) is turned into `SystemExit` so
the assertion is released on the way out.

`--env-file` is the path `Config.from_env` reads (a host's `.env`); the default is the loader's
own search. A gateway URL that is not loopback is printed and exits 1 **before any request**.
Nothing here prints the IBKR user id; the username appears only in a BORROWED verdict, where
it says whose session the gateway is holding. Every line is flushed: under launchd or a
redirected shell stdout is block-buffered, and a command silent for its whole wait is
indistinguishable from a hang.
"""

from __future__ import annotations

import argparse
import signal
import sys
from collections.abc import Sequence
from types import FrameType

from ibkr_core_mcp.exceptions import ConfigError
from ibkr_core_mcp.gateway.manager import _RESTART_REFUSED_CODES, GatewayManager, KeepAwake, read_login_events
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
from ibkr_core_mcp.gateway.session import KEEPALIVE_INTERVAL, SessionPhase, get_session, keepalive_loop, release_session
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


def _preflight_command(url: str, args: argparse.Namespace) -> int:
    """`preflight`, with the opt-in `--release` first."""
    if args.release:
        _say("Releasing the gateway's held session (POST /logout)…\n")
        released, detail = release_session(url)
        _say(f"  released={released}  {detail}\n")
        _say("Re-checking:\n")
    return _preflight(url)


def _diagnose(url: str, args: argparse.Namespace) -> int:
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


def _up(url: str, args: argparse.Namespace) -> int:
    """The owner's sequence, rendered; 0 LIVE, 1 DOWN, 3 for everything that blocks a login —
    "opened the login page and it was never completed" is a real outcome and must not look
    like success."""
    result = get_session().establish(
        GatewayManager(),
        url=url,
        emit=_say,
        allow_restart=args.allow_restart,
        login_timeout=args.wait_timeout,
    )
    _say()
    _say(f"  {result.phase.value.upper()} — {result.detail}")
    _say()
    if result.phase is SessionPhase.DOWN:
        return 1
    if result.phase is SessionPhase.LIVE:
        return 0
    return 3


def _reset(url: str, args: argparse.Namespace) -> int:
    """The before verdict, the owner's recovery, the after verdict; exit = the after code, 1 when
    the guard inside `start()` refused (its reason is the owner's line)."""
    _say("── Before ─────────────────────────────────────────────────────────")
    before = _preflight(url)
    _say()
    get_session().recover(GatewayManager(), url=url, emit=_say, force=args.force)
    if before in _RESTART_REFUSED_CODES and not args.force:
        return 1
    _say()
    _say("── After ──────────────────────────────────────────────────────────")
    after = _preflight(url)
    if after == EXIT_FREE:
        login_url = url.removesuffix("/v1/api")
        _say(
            "\nThe slot is clear. Log in NOW, while it is:\n\n"
            f"  1. Open {login_url}\n"
            '  2. Complete the login through to "Client login succeeds"\n'
            "  3. Keep IBKR Mobile logged out until you are done\n\n"
            "Then confirm with:  python -m ibkr_core_mcp.gateway preflight\n"
            "It should read [OK] Session is LIVE."
        )
    else:
        _say(
            "\nStill not free. Re-read the verdict above — if it names another CLIENT_APP, that\n"
            "app must be logged out from its own Log Out menu item (closing it is not enough)."
        )
    return after


def _exit_on_sigterm(signum: int, frame: FrameType | None) -> None:
    """`launchctl bootout` sends SIGTERM; raising lets the loop's `finally` release `caffeinate`."""
    raise SystemExit(0)


def _keepalive(url: str, args: argparse.Namespace) -> int:
    """The tickler, or with `--print-url` the URL it would tickle and nothing contacted."""
    if args.print_url:
        _say(f"{url}/tickle")
        return 0
    signal.signal(signal.SIGTERM, _exit_on_sigterm)
    keepalive_loop(url, interval=args.interval, awake=KeepAwake(), say=_say)
    return 0


def build_parser() -> argparse.ArgumentParser:
    """The command line: one subcommand per operation, each taking `--env-file`."""
    parser = argparse.ArgumentParser(
        prog="python -m ibkr_core_mcp.gateway",
        description="The IBKR Client Portal Gateway session, from the operator's side: read it before touching it.",
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="command")

    def add(name: str, run: object, help_text: str) -> argparse.ArgumentParser:
        command = commands.add_parser(name, help=help_text, description=help_text)
        command.add_argument(
            "--env-file",
            metavar="PATH",
            default=None,
            help="the .env Config.from_env reads (default: the loader's own search)",
        )
        command.set_defaults(run=run)
        return command

    preflight = add(
        "preflight",
        _preflight_command,
        "read the session (two GETs; the gateway's log after a FREE reading) and exit with the verdict's code",
    )
    preflight.add_argument(
        "--release",
        action="store_true",
        help="POST /logout first — drop the session the gateway holds — then re-read; opt-in, and possibly "
        "ending an IBKR Mobile session too (its scope is undocumented)",
    )
    add(
        "diagnose",
        _diagnose,
        "the reading, its guidance, the flags and the login timeline; exit 0 on READY or FREE, else 3",
    )
    up = add(
        "up", _up, "bring the session to LIVE through the owner, or say why it cannot; exit 0 LIVE, 1 DOWN, 3 otherwise"
    )
    up.add_argument(
        "--wait-timeout",
        type=float,
        default=300.0,
        help="seconds to wait for a login to complete (default 300). There is no --no-wait: opening the login "
        "page suspends every tickler in the system, and a suspension has to be bounded by whoever declared it",
    )
    up.add_argument(
        "--allow-restart",
        action="store_true",
        help="clear a session borrowed from another IBKR app by restarting the container; off by default, "
        "since a restart destroys a session",
    )
    reset = add(
        "reset",
        _reset,
        "clear the session by restarting the container — refused on a LIVE, REFUSED or VALIDATING one; "
        "exit: the after verdict's code, 1 when refused",
    )
    reset.add_argument("--force", action="store_true", help="restart even where the guard refuses")
    keepalive = add(
        "keepalive",
        _keepalive,
        "tickle the gateway every 55 s from outside any host process, honouring the suspend lock, with "
        "caffeinate held while it answers; runs until Ctrl-C or SIGTERM",
    )
    keepalive.add_argument(
        "--print-url", action="store_true", help="print the URL it would tickle and exit; nothing contacted"
    )
    keepalive.add_argument(
        "--interval", type=float, default=KEEPALIVE_INTERVAL, metavar="S", help="seconds between tickles (default 55)"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse, read the URL through the one loader, run the subcommand; its exit code."""
    args = build_parser().parse_args(argv)
    try:
        url = gateway_api_url(args.env_file)
    except ConfigError as exc:
        _say(redact_error(exc), err=True)
        return 1
    result: int = args.run(url, args)
    return result


if __name__ == "__main__":
    sys.exit(main())
