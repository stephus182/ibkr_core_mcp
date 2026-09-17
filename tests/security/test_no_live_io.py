"""Security constitution §7 — unit tests cannot open sockets, resolve names, or see the
operator's credentials.

The socket half has been enforced by `tests/conftest.py::_no_real_io` (pytest-socket)
since 2026-07-08. The credential half was not: constructing `Config(...)` in a unit test
ran `load_dotenv()` through the `crawl4ai_profiles_dir` default factory, which walks up
from `config.py` and loads the repository's real `.env` into `os.environ` — probed on
2026-09-13, `FIRECRAWL_API_KEY` and `GDRIVE_*` appeared
(docs/audits/security-architecture-audit-2026-09-13.md, B6).
"""

from __future__ import annotations

import os
import re
import socket
from pathlib import Path

import pytest
from pytest_socket import SocketBlockedError

from ibkr_core_mcp.config import Config

from .structural import PACKAGE_DIR

pytestmark = pytest.mark.security

_ENV_READ = re.compile(r"""os\.(?:environ\.get|getenv|environ\[)\(?\s*["']([A-Z0-9_]+)["']""")


def _variables_the_package_reads() -> set[str]:
    """Every environment variable named in package source — derived, so a new one is
    covered the day it is added (the first version was a hand-typed 7-name subset that
    already missed IBKR_AUTH_BROWSER; review 2026-09-13)."""
    names: set[str] = set()
    for path in PACKAGE_DIR.rglob("*.py"):
        names |= set(_ENV_READ.findall(path.read_text()))
    return names


SECRET_ENV_VARS = sorted(_variables_the_package_reads())


def test_the_variable_scan_finds_the_known_readers():
    """Vacuity guard on the scan: it must still find the variables the package really reads.

    `ANTHROPIC_API_KEY` was in this set until 2026-09-17 and is not any more — the package
    stopped reading it when `Config.anthropic_api_key` was removed (TOOL-07). That is the
    scan working, not the scan breaking: it is derived from package source on purpose.
    `conftest._SECRET_ENV_PREFIXES` still scrubs `ANTHROPIC_` from every unit test, by
    prefix and for a different reason, which `test_the_scrubber_still_removes_a_key_the_package_no_longer_reads`
    below holds.
    """
    found = set(SECRET_ENV_VARS)
    assert {
        "FIRECRAWL_API_KEY",
        "IBKR_FLEX_TOKEN",
        "IBKR_AUTH_BROWSER",
        "GDRIVE_TOKEN_FILE",
    } <= found
    assert "ANTHROPIC_API_KEY" not in found, (
        "the package reads ANTHROPIC_API_KEY again — TOOL-07 removed the only reader; "
        "if that is deliberate, Config is carrying a model credential again and "
        "test_config_carries_no_model_vendor_credential should have caught it first"
    )
    # 14 since TOOL-07 removed ANTHROPIC_API_KEY's only reader; it was 15 before.
    assert len(found) >= 14


def test_the_scrubber_still_removes_a_key_the_package_no_longer_reads(monkeypatch):
    """`ANTHROPIC_API_KEY` is still the operator's most valuable secret and still lives in
    the `.env` that `load_dotenv` can pull in. The scrubber keeps it out of unit tests
    whether or not this package consumes it, so removing the prefix as "unused" would be a
    security regression rather than a tidy-up (TOOL-07, 2026-09-17)."""
    from tests.conftest import _SECRET_ENV_PREFIXES

    assert "ANTHROPIC_" in _SECRET_ENV_PREFIXES
    # The autouse fixture has already run for this test.
    assert "ANTHROPIC_API_KEY" not in os.environ, "the operator's Anthropic key reached a unit test"


def test_name_resolution_is_blocked_inside_a_unit_test():
    with pytest.raises(SocketBlockedError):
        socket.getaddrinfo("example.com", 443)


def test_a_tcp_connection_is_blocked_inside_a_unit_test():
    with pytest.raises(SocketBlockedError):
        socket.create_connection(("127.0.0.1", 9), timeout=0.1)


def test_no_secret_variable_is_visible_to_a_unit_test():
    present = [name for name in SECRET_ENV_VARS if name in os.environ]
    assert not present, f"secret env vars visible during a unit test: {present}"


def test_constructing_a_config_does_not_load_the_repository_dotenv(tmp_path):
    Config(
        gateway_url="https://localhost:5055/v1/api",
        gdrive_folder_id="f",
        sqlite_path=tmp_path / "x.db",
        gdrive_token_file=tmp_path / "t",
        gdrive_credentials_file=tmp_path / "c",
    )
    present = [name for name in SECRET_ENV_VARS if name in os.environ]
    assert not present, f"Config() pulled {present} into the environment"


def test_config_from_env_sees_only_what_the_test_set(monkeypatch):
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-test-only")
    cfg = Config.from_env()
    assert cfg.firecrawl_api_key == "fc-test-only"
    assert cfg.flex_token == ""
    assert cfg.gdrive_token_file == Path("~/.ibkr_core/token.json").expanduser()
