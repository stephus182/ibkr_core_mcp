from pathlib import Path

import pytest


def test_from_env_reads_required_vars(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("IBKR_GATEWAY_URL", "https://localhost:5055/v1/api")
    monkeypatch.setenv("GOOGLE_DRIVE_FOLDER_ID", "folder123")
    monkeypatch.delenv("IBKR_SQLITE_PATH", raising=False)
    monkeypatch.delenv("GDRIVE_TOKEN_FILE", raising=False)
    monkeypatch.delenv("GDRIVE_CREDENTIALS_FILE", raising=False)

    from ibkr_core_mcp.config import Config
    cfg = Config.from_env()

    assert cfg.anthropic_api_key == "sk-test"
    assert cfg.gateway_url == "https://localhost:5055/v1/api"
    assert cfg.gdrive_folder_id == "folder123"
    assert isinstance(cfg.sqlite_path, Path)


def test_from_env_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from ibkr_core_mcp.config import Config
    from ibkr_core_mcp.exceptions import ConfigError
    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
        Config.from_env()


def test_sqlite_path_expands_home(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("IBKR_SQLITE_PATH", "~/.ibkr_core/store.db")
    from ibkr_core_mcp.config import Config
    cfg = Config.from_env()
    assert not str(cfg.sqlite_path).startswith("~")
