from pathlib import Path


def test_from_env_reads_required_vars(monkeypatch):
    monkeypatch.setenv("IBKR_GATEWAY_URL", "https://localhost:5055/v1/api")
    monkeypatch.setenv("GOOGLE_DRIVE_FOLDER_ID", "folder123")
    monkeypatch.delenv("IBKR_SQLITE_PATH", raising=False)
    monkeypatch.delenv("GDRIVE_TOKEN_FILE", raising=False)
    monkeypatch.delenv("GDRIVE_CREDENTIALS_FILE", raising=False)

    from ibkr_core_mcp.config import Config

    cfg = Config.from_env()

    assert cfg.gateway_url == "https://localhost:5055/v1/api"
    assert cfg.gdrive_folder_id == "folder123"
    assert isinstance(cfg.sqlite_path, Path)


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


def test_crawl4ai_profiles_dir_reads_from_env(monkeypatch):
    """The paywall profile root — the only Crawl4AI setting left after the Cloud rung
    was removed (2026-07-28). `crawl4ai_api_key` and `crawl4ai_profiles_dir` were
    adjacent fields with near-identical names, and only the first one was the cloud
    rung's; this and the test below are what keep the survivor covered.
    """
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


# ---------------------------------------------------------------------------
# TOOL-07 — this package makes no model calls, so it carries no model credentials
# ---------------------------------------------------------------------------


def test_config_carries_no_model_vendor_credential():
    """The rule is deliberately not "remove Anthropic's key".

    `anthropic_api_key` was a **required** field from the first `Config` commit
    (`182e483`, 2026-05-23) until 2026-09-17, and nothing in the package ever read it:
    zero attribute reads, and `anthropic` never entered `sys.modules` even with
    `claude_tools` and `mcp_server` imported (audit finding TOOL-07). `config.py`'s own
    docstring gave the reason as "a toolkit with no key cannot do anything at all", which
    was false — `ClaudeToolkit` reads `flex_token`, `gateway_url`, `firecrawl_api_key` and
    `crawl4ai_profiles_dir`, never this one.

    The owner's rule, 2026-09-17: *"this field should not exist in either shape."* A
    package that never calls a model has no business holding one vendor's credential, so
    this is written as a property rather than a deletion — adding `openai_api_key` or
    `gemini_api_key` later fails here too, without anyone having to remember why.
    """
    import dataclasses

    from ibkr_core_mcp.config import Config

    vendors = ("anthropic", "openai", "gemini", "claude", "llm", "model")
    secrets = ("key", "token", "secret", "credential")
    offenders = [
        f.name
        for f in dataclasses.fields(Config)
        if any(v in f.name.lower() for v in vendors) and any(s in f.name.lower() for s in secrets)
    ]

    assert not offenders, (
        f"Config carries model-vendor credentials: {offenders}. This package makes no model "
        "calls — ClaudeToolkit is a tool *definition* layer and the host app owns the model "
        "client. A credential nothing reads is a required secret, a startup failure and a "
        "plaintext key in someone's config file, for nothing."
    )


def test_from_env_does_not_require_an_anthropic_key(monkeypatch):
    """The startup failure this removes, stated as the behaviour rather than the field.

    `mcp_server.main()` calls `Config.from_env()`, so the MCP server refused to start
    without a key no part of it uses — and the requirement had already been routed around
    three times in two repositories (`crawl4ai_profiles_dir_from_env` here, and
    `gateway_preflight.gateway_url` in claudia_ui) rather than removed.
    """
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("IBKR_GATEWAY_URL", "https://localhost:5055/v1/api")

    from ibkr_core_mcp.config import Config

    cfg = Config.from_env()  # must not raise
    assert cfg.gateway_url == "https://localhost:5055/v1/api"
