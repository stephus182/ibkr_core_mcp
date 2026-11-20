"""The OS keychain behind the one loader — secrets at rest (MCP security checklist 7.1).

    python -m ibkr_core_mcp.secret_store set IBKR_FLEX_TOKEN        # typed, never echoed, never an argument
    python -m ibkr_core_mcp.secret_store list [--env-file PATH]     # where each secret is held — never a value
    python -m ibkr_core_mcp.secret_store import-env PATH            # move a .env's secrets into the keychain
    python -m ibkr_core_mcp.secret_store delete NAME

Until 2026-11-09 the package's secrets — `IBKR_FLEX_TOKEN`, `FIRECRAWL_API_KEY`, and the names a
host adds — lived in a `.env` file: 0600, refused if accessible to others, never exported to the
environment (register F48), but plain text on disk. The operator deferred encryption at rest on
2026-10-16 and lifted the deferral on 2026-11-09: the store is the operating system's own — macOS
Keychain, Windows Credential Locker, the Secret Service on Linux — through the `keyring` library,
one entry per secret name under the service `ibkr_core_mcp`. OWASP's MCP guide: "Utilize secrets
storage vaults for client credentials and API keys. Do not store secrets in environment
variables, logs or plain-text in code."

**Precedence in `Config.from_env`:** the environment the user set (the documented contract for
the MCP server) → the keychain → the `.env` file. `config.py` stays the one reader of the
environment and `load_env_file` the one reader of files (invariant 12); the keychain is a second
*store*, and like the file it is never a sink to the environment. A workstation without a usable keychain runs from the file as before: every keychain
error reads as "absent", with one DEBUG line.

**Under pytest no keychain is reachable.** `tests/conftest.py` sets `keyring`'s null backend from
`pytest_configure` (door 7), and a test of this module sets an in-memory stand-in for its own
duration. `keyring` is imported here and nowhere else in the package (`test_no_live_io.py`).

**The command line never prints a value.** `set` reads it with `getpass`; `list` prints names and
where each is held; `import-env` names the lines to remove from the file and leaves the file to
the operator.
"""

from __future__ import annotations

import argparse
import getpass
import logging
import sys
from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING

from pydantic import SecretStr

from ibkr_core_mcp.redaction import redact_error

if TYPE_CHECKING:
    from ibkr_core_mcp.config import EnvFile

log = logging.getLogger(__name__)

SERVICE = "ibkr_core_mcp"
"""The keychain entry's service name; the secret's variable name is its account."""


def read_secret(name: str) -> SecretStr | None:
    """The secret `name` from the keychain, or None — absent, empty, or no usable keychain."""
    try:
        import keyring

        value = keyring.get_password(SERVICE, name)
    except Exception as exc:  # NoKeyringError, KeyringError, or a backend's own failure
        log.debug("The OS keychain could not be read for %s: %s", name, redact_error(exc))
        return None
    return SecretStr(value) if value else None


def store_secret(name: str, value: str) -> None:
    """Store `value` under `name`. Raises `keyring.errors.KeyringError` when the keychain cannot."""
    import keyring

    keyring.set_password(SERVICE, name, value)


def delete_secret(name: str) -> bool:
    """Remove `name`; False when there was nothing to remove or the keychain cannot."""
    import keyring

    try:
        if keyring.get_password(SERVICE, name) is None:
            return False
        keyring.delete_password(SERVICE, name)
    except Exception as exc:
        log.debug("The OS keychain could not delete %s: %s", name, redact_error(exc))
        return False
    return True


def held(names: Iterable[str]) -> set[str]:
    """Which of `names` the keychain holds."""
    return {name for name in names if read_secret(name) is not None}


def resolve(name: str, env: EnvFile | None = None) -> SecretStr | None:
    """A secret from the stores at rest, in the order `Config.from_env` reads them after the
    environment: the keychain, then the file. None when neither holds it.

    The environment itself is read in `config.py`, by literal name, as every variable the
    package reads is — that is what lets `tests/security/test_no_live_io.py` derive the list
    of names a unit test must never see.

    Args:
        name: The secret's variable name.
        env: What `load_env_file` read, for the file's value; None when no file was read.
    """
    from_keychain = read_secret(name)
    if from_keychain is not None:
        return from_keychain
    if env is not None:
        return env.secrets.get(name)
    return None


# ── The command line ─────────────────────────────────────────────────────────────


def _known(extra: Sequence[str] | None) -> tuple[str, ...]:
    from ibkr_core_mcp.config import SECRET_NAMES

    return (*SECRET_NAMES, *(extra or ()))


def _set(name: str, names: tuple[str, ...]) -> int:
    if name not in names:
        print(
            f"{name} is not a secret name this package reads ({', '.join(names)}); pass --names {name} to store it anyway.",
            file=sys.stderr,
        )
        return 2
    value = getpass.getpass(f"{name} (not echoed): ")
    if not value:
        print("Nothing typed; nothing stored.", file=sys.stderr)
        return 2
    try:
        store_secret(name, value)
    except Exception as exc:
        print(f"The OS keychain could not store {name}: {redact_error(exc)}", file=sys.stderr)
        return 1
    print(f"Stored {name} in the OS keychain (service {SERVICE}). Remove it from .env if it is there.")
    return 0


def _list(names: tuple[str, ...], env_file: str | None) -> int:
    from ibkr_core_mcp.config import load_env_file

    env = load_env_file(env_file, secret_names=names)
    in_keychain = held(names)
    for name in names:
        places = []
        if name in in_keychain:
            places.append("keychain")
        if name in env.secrets:
            places.append(".env")
        print(f"  {name:<24} {' + '.join(places) if places else 'nowhere'}")
    if env.refused:
        print(f"  ({env.refused})")
    return 0


def _import_env(path: str, names: tuple[str, ...]) -> int:
    from ibkr_core_mcp.config import load_env_file

    env = load_env_file(path, secret_names=names)
    if env.path is None:
        print(f"No file at {path}.", file=sys.stderr)
        return 2
    if env.refused:
        print(env.refused, file=sys.stderr)
        return 1
    stored: list[str] = []
    for name, value in env.secrets.items():
        try:
            store_secret(name, value.get_secret_value())
        except Exception as exc:
            print(f"The OS keychain could not store {name}: {redact_error(exc)}", file=sys.stderr)
            return 1
        stored.append(name)
    if not stored:
        print(f"{path} holds none of {', '.join(names)}.")
        return 0
    print(f"Stored {len(stored)} in the OS keychain (service {SERVICE}): {', '.join(stored)}.")
    print(
        f"Now remove these lines from {path} — the keychain is read before the file: {', '.join(f'{n}=…' for n in stored)}"
    )
    return 0


def _delete(name: str) -> int:
    if delete_secret(name):
        print(f"Removed {name} from the OS keychain.")
        return 0
    print(f"{name} is not in the OS keychain.", file=sys.stderr)
    return 1


def build_parser() -> argparse.ArgumentParser:
    """The command line: four subcommands, each taking `--names` for a host's own secret names."""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--names", nargs="*", metavar="NAME", default=None, help="a host's own secret names, beside the package's"
    )
    parser = argparse.ArgumentParser(
        prog="python -m ibkr_core_mcp.secret_store",
        description="The package's secrets in the OS keychain: stored, listed by name, imported from a .env, removed. Never printed.",
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="command")
    p_set = commands.add_parser("set", parents=[common], help="store one secret, typed without echo")
    p_set.add_argument("name")
    p_list = commands.add_parser(
        "list", parents=[common], help="where each secret is held — keychain, .env, both, nowhere; never a value"
    )
    p_list.add_argument("--env-file", metavar="PATH", default=None)
    p_import = commands.add_parser(
        "import-env", parents=[common], help="store every secret a .env holds, then name the lines to remove"
    )
    p_import.add_argument("path")
    p_delete = commands.add_parser("delete", parents=[common], help="remove one secret")
    p_delete.add_argument("name")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse and run; the exit code (0 done, 1 the keychain refused, 2 a usage error)."""
    args = build_parser().parse_args(argv)
    names = _known(args.names)
    if args.command == "set":
        return _set(args.name, names)
    if args.command == "list":
        return _list(names, args.env_file)
    if args.command == "import-env":
        return _import_env(args.path, names)
    return _delete(args.name)


if __name__ == "__main__":
    sys.exit(main())
