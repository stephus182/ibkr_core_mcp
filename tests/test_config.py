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


def test_firecrawl_api_key_reads_from_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-abc123")
    monkeypatch.setenv("GDRIVE_WEB_DOCS_FOLDER_ID", "webdocs-folder-id")
    from ibkr_core_mcp.config import Config

    cfg = Config.from_env()
    assert cfg.firecrawl_api_key == "fc-abc123"
    assert cfg.gdrive_web_docs_folder_id == "webdocs-folder-id"


def test_firecrawl_config_defaults_to_empty(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    monkeypatch.delenv("GDRIVE_WEB_DOCS_FOLDER_ID", raising=False)
    from ibkr_core_mcp.config import Config

    # Explicit nonexistent dotenv_path: this repo may have its own local, gitignored
    # .env for standalone-dev Drive/Firecrawl testing (see CLAUDE.md's "Standalone dev
    # exception") — load_dotenv()'s default search would otherwise pick that up and
    # defeat this test's "no key configured" scenario.
    cfg = Config.from_env(dotenv_path=str(tmp_path / "nonexistent.env"))
    assert cfg.firecrawl_api_key == ""
    assert cfg.gdrive_web_docs_folder_id == ""


def test_crawl4ai_cloud_config_reads_from_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("CRAWL4AI_API_KEY", "crawl4ai-fake-key-for-tests")
    monkeypatch.setenv("CRAWL4AI_API_URL", "https://staging.crawl4ai.example")
    from ibkr_core_mcp.config import Config

    cfg = Config.from_env()
    assert cfg.crawl4ai_api_key == "crawl4ai-fake-key-for-tests"
    assert cfg.crawl4ai_api_url == "https://staging.crawl4ai.example"


def test_crawl4ai_cloud_config_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("CRAWL4AI_API_KEY", raising=False)
    monkeypatch.delenv("CRAWL4AI_API_URL", raising=False)
    from ibkr_core_mcp.config import Config

    # Explicit nonexistent dotenv_path, for the same reason as
    # test_firecrawl_config_defaults_to_empty above: this repo ships a gitignored
    # .env holding a real CRAWL4AI_API_KEY, and load_dotenv's default search would
    # find it and defeat this test's "no key configured" scenario.
    cfg = Config.from_env(dotenv_path=str(tmp_path / "nonexistent.env"))
    assert cfg.crawl4ai_api_key == ""
    assert cfg.crawl4ai_api_url == "https://api.crawl4ai.com"


def test_crawl4ai_api_key_never_appears_in_repr(monkeypatch, tmp_path):
    """repr(Config) must not leak the cloud key, matching firecrawl_api_key's repr=False."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("CRAWL4AI_API_KEY", "crawl4ai-fake-key-for-tests")
    from ibkr_core_mcp.config import Config

    cfg = Config.from_env()
    # Assert the field is actually populated first: without this the repr check below
    # passes vacuously on a Config that has no such field at all.
    assert cfg.crawl4ai_api_key == "crawl4ai-fake-key-for-tests"
    assert "crawl4ai-fake-key-for-tests" not in repr(cfg)


def test_crawl4ai_profiles_dir_reads_from_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("CRAWL4AI_PROFILES_DIR", "/tmp/my-profiles")
    from ibkr_core_mcp.config import Config

    cfg = Config.from_env()
    assert cfg.crawl4ai_profiles_dir == Path("/tmp/my-profiles")


def test_crawl4ai_profiles_dir_defaults_and_expands_home(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("CRAWL4AI_PROFILES_DIR", raising=False)
    from ibkr_core_mcp.config import Config

    cfg = Config.from_env()
    assert cfg.crawl4ai_profiles_dir == Path("~/.ibkr_core/crawl4ai_profiles").expanduser()
