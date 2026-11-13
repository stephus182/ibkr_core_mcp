"""Tests for `ibkr_core_mcp.secret_store` — the OS keychain behind the one loader (MCP security
checklist 7.1, 2026-11-09).

A secret read from the keychain never enters the process environment (invariant 12 holds for
this source as for the file); the environment the user set still wins, the file is the fallback;
the command line never prints a value; and no unit test can reach the operator's keychain — the
conftest sets `keyring`'s null backend from `pytest_configure`, and a test of the store sets an
in-memory stand-in for its own duration.
"""

from __future__ import annotations

import os
from pathlib import Path

import keyring
import keyring.backends.null
import pytest
from keyring.errors import KeyringError, NoKeyringError
from pydantic import SecretStr

from ibkr_core_mcp import secret_store
from ibkr_core_mcp.config import Config


class _Memory(keyring.backend.KeyringBackend):
    """An in-memory keyring for one test: nothing reaches the operator's."""

    priority = 1

    def __init__(self) -> None:
        super().__init__()
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.values.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.values[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        del self.values[(service, username)]


class _Broken(keyring.backend.KeyringBackend):
    """A keyring that cannot be used — the shape of a workstation with none."""

    priority = 1

    def get_password(self, service: str, username: str) -> str | None:
        raise NoKeyringError("No recommended backend was available")

    def set_password(self, service: str, username: str, password: str) -> None:
        raise KeyringError("cannot store")

    def delete_password(self, service: str, username: str) -> None:
        raise KeyringError("cannot delete")


@pytest.fixture
def memory():
    """An in-memory backend for the test's duration; the null door is put back after."""
    previous = keyring.get_keyring()
    backend = _Memory()
    keyring.set_keyring(backend)
    try:
        yield backend
    finally:
        keyring.set_keyring(previous)


@pytest.fixture
def broken():
    previous = keyring.get_keyring()
    keyring.set_keyring(_Broken())
    try:
        yield
    finally:
        keyring.set_keyring(previous)


def _env_file(tmp_path: Path, text: str) -> Path:
    path = tmp_path / ".env"
    path.write_text(text)
    path.chmod(0o600)
    return path


# ── The door ─────────────────────────────────────────────────────────────────────


def test_no_unit_test_can_reach_the_operators_keychain():
    """Door 7: under pytest the backend is keyring's null one, from `pytest_configure` on — a
    store or a read in a test touches nothing of the operator's and nothing prompts."""
    assert isinstance(keyring.get_keyring(), keyring.backends.null.Keyring)
    assert secret_store.read_secret("IBKR_FLEX_TOKEN") is None


# ── The store ────────────────────────────────────────────────────────────────────


def test_a_stored_secret_reads_back_as_a_secret_str_and_never_in_clear(memory):
    secret_store.store_secret("IBKR_FLEX_TOKEN", "not-a-real-token")
    got = secret_store.read_secret("IBKR_FLEX_TOKEN")
    assert isinstance(got, SecretStr) and got.get_secret_value() == "not-a-real-token"
    assert "not-a-real-token" not in repr(got)
    assert memory.values == {(secret_store.SERVICE, "IBKR_FLEX_TOKEN"): "not-a-real-token"}


def test_an_absent_secret_reads_as_none_and_held_names_only_the_present(memory):
    secret_store.store_secret("FIRECRAWL_API_KEY", "fc-not-a-real-key")
    assert secret_store.read_secret("IBKR_FLEX_TOKEN") is None
    assert secret_store.held(("IBKR_FLEX_TOKEN", "FIRECRAWL_API_KEY", "HOST_SECRET")) == {"FIRECRAWL_API_KEY"}


def test_delete_removes_the_entry_and_is_idempotent(memory):
    secret_store.store_secret("IBKR_FLEX_TOKEN", "x")
    assert secret_store.delete_secret("IBKR_FLEX_TOKEN") is True
    assert secret_store.delete_secret("IBKR_FLEX_TOKEN") is False
    assert secret_store.read_secret("IBKR_FLEX_TOKEN") is None


def test_a_keychain_that_cannot_be_used_reads_as_none_not_an_error(broken, caplog):
    """A workstation without a keyring still runs from the file: the failure is one DEBUG line."""
    import logging

    with caplog.at_level(logging.DEBUG, logger="ibkr_core_mcp.secret_store"):
        assert secret_store.read_secret("IBKR_FLEX_TOKEN") is None
        assert secret_store.held(("IBKR_FLEX_TOKEN",)) == set()
    assert any("keychain" in r.getMessage().lower() for r in caplog.records)
    assert all(r.levelno <= logging.DEBUG for r in caplog.records)


# ── Precedence in Config.from_env: environment → keychain → file ─────────────────


def test_the_keychain_outranks_the_file_and_the_environment_outranks_the_keychain(memory, tmp_path, monkeypatch):
    monkeypatch.delenv("IBKR_FLEX_TOKEN", raising=False)
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    path = _env_file(tmp_path, "IBKR_FLEX_TOKEN=from-the-file\nFIRECRAWL_API_KEY=fc-from-the-file\n")
    secret_store.store_secret("IBKR_FLEX_TOKEN", "from-the-keychain")

    cfg = Config.from_env(dotenv_path=str(path))
    assert cfg.flex_token.get_secret_value() == "from-the-keychain"
    assert cfg.firecrawl_api_key.get_secret_value() == "fc-from-the-file"

    monkeypatch.setenv("IBKR_FLEX_TOKEN", "from-the-environment")
    cfg = Config.from_env(dotenv_path=str(path))
    assert cfg.flex_token.get_secret_value() == "from-the-environment"


def test_a_keychain_secret_never_enters_the_environment(memory, tmp_path, monkeypatch):
    """Invariant 12, for this source as for the file."""
    monkeypatch.delenv("IBKR_FLEX_TOKEN", raising=False)
    secret_store.store_secret("IBKR_FLEX_TOKEN", "from-the-keychain")
    Config.from_env(dotenv_path=str(_env_file(tmp_path, "IBKR_GATEWAY_URL=https://localhost:5055/v1/api\n")))
    assert "IBKR_FLEX_TOKEN" not in os.environ


def test_a_hosts_own_secret_name_is_read_from_the_keychain_too(memory, tmp_path, monkeypatch):
    """The consumer's `ANTHROPIC_API_KEY`-style names come through `secret_names`, as for the file."""
    monkeypatch.delenv("HOST_SECRET", raising=False)
    secret_store.store_secret("HOST_SECRET", "host-from-the-keychain")
    path = _env_file(tmp_path, "HOST_SECRET=host-from-the-file\n")
    from ibkr_core_mcp.config import SECRET_NAMES, load_env_file

    env = load_env_file(path, secret_names=(*SECRET_NAMES, "HOST_SECRET"))
    assert env.secrets["HOST_SECRET"].get_secret_value() == "host-from-the-file"
    stored = secret_store.resolve("HOST_SECRET", env)
    assert stored is not None and stored.get_secret_value() == "host-from-the-keychain"
    assert "HOST_SECRET" not in os.environ


# ── The command line never prints a value ────────────────────────────────────────


def test_set_reads_the_value_without_echo_and_stores_it(memory, monkeypatch, capsys):
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "typed-not-a-real-token")
    assert secret_store.main(["set", "IBKR_FLEX_TOKEN"]) == 0
    assert memory.values[(secret_store.SERVICE, "IBKR_FLEX_TOKEN")] == "typed-not-a-real-token"
    out = capsys.readouterr().out
    assert "typed-not-a-real-token" not in out and "IBKR_FLEX_TOKEN" in out


def test_set_refuses_a_name_it_does_not_know_unless_named(memory, monkeypatch, capsys):
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "v")
    assert secret_store.main(["set", "NOT_A_SECRET_NAME"]) == 2
    assert secret_store.main(["set", "HOST_SECRET", "--names", "HOST_SECRET"]) == 0
    assert "NOT_A_SECRET_NAME" in capsys.readouterr().err


def test_list_names_where_each_secret_is_held_and_prints_no_value(memory, tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("IBKR_FLEX_TOKEN", raising=False)
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    secret_store.store_secret("IBKR_FLEX_TOKEN", "k-not-a-real-token")
    path = _env_file(tmp_path, "IBKR_FLEX_TOKEN=f-not-a-real-token\n")
    assert secret_store.main(["list", "--env-file", str(path)]) == 0
    out = capsys.readouterr().out
    assert "IBKR_FLEX_TOKEN" in out and "keychain" in out and ".env" in out
    assert "FIRECRAWL_API_KEY" in out and "nowhere" in out
    assert "not-a-real-token" not in out


def test_import_env_stores_every_secret_of_the_file_and_names_the_lines_to_remove(
    memory, tmp_path, monkeypatch, capsys
):
    monkeypatch.delenv("IBKR_FLEX_TOKEN", raising=False)
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    path = _env_file(
        tmp_path,
        "IBKR_GATEWAY_URL=https://localhost:5055/v1/api\nIBKR_FLEX_TOKEN=f-not-a-real-token\nFIRECRAWL_API_KEY=fc-not-a-real-key\n",
    )
    assert secret_store.main(["import-env", str(path)]) == 0
    assert memory.values == {
        (secret_store.SERVICE, "IBKR_FLEX_TOKEN"): "f-not-a-real-token",
        (secret_store.SERVICE, "FIRECRAWL_API_KEY"): "fc-not-a-real-key",
    }
    out = capsys.readouterr().out
    assert "IBKR_FLEX_TOKEN" in out and "FIRECRAWL_API_KEY" in out and "remove" in out.lower()
    assert "not-a-real" not in out
    assert path.read_text().count("not-a-real") == 2  # the file is the operator's to edit


def test_delete_from_the_command_line(memory, capsys):
    secret_store.store_secret("IBKR_FLEX_TOKEN", "x")
    assert secret_store.main(["delete", "IBKR_FLEX_TOKEN"]) == 0
    assert secret_store.main(["delete", "IBKR_FLEX_TOKEN"]) == 1
    assert memory.values == {}


def test_a_keychain_that_cannot_store_is_an_error_the_operator_sees(broken, monkeypatch, capsys):
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "v")
    assert secret_store.main(["set", "IBKR_FLEX_TOKEN"]) == 1
    assert "keychain" in capsys.readouterr().err.lower()
