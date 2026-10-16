import os
from pathlib import Path

import pytest


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
    assert cfg.firecrawl_api_key.get_secret_value() == "fc-abc123"
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
    assert cfg.firecrawl_api_key.get_secret_value() == ""
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


# ── Secrets out of the process environment (register F48; claudia_ui gap #103) ──────────


def _write_env(path, text, mode=0o600):
    path.write_text(text, encoding="utf-8")
    path.chmod(mode)
    return path


def test_load_env_file_exports_a_setting_and_holds_a_secret_back(tmp_path, monkeypatch):
    """Design test 1. The setting reaches `os.environ`; the secret does not, comes back as a
    `SecretStr`, and prints masked. Break: the loader exporting the secret (drop the
    `in secret` branch) — red."""
    from pydantic import SecretStr

    from ibkr_core_mcp.config import load_env_file

    monkeypatch.delenv("IBKR_GATEWAY_URL", raising=False)
    monkeypatch.delenv("IBKR_FLEX_TOKEN", raising=False)
    path = _write_env(
        tmp_path / ".env",
        "IBKR_GATEWAY_URL=https://example.invalid/v1/api\nIBKR_FLEX_TOKEN=flex-secret-value\nBARE_NAME\n",
    )

    env = load_env_file(path)

    assert os.environ["IBKR_GATEWAY_URL"] == "https://example.invalid/v1/api"
    assert "BARE_NAME" not in os.environ  # a line with no `=`: python-dotenv yields None, and None is not a value
    assert "IBKR_FLEX_TOKEN" not in os.environ
    assert env.path == path and env.refused is None
    assert isinstance(env.secrets["IBKR_FLEX_TOKEN"], SecretStr)
    assert env.secrets["IBKR_FLEX_TOKEN"].get_secret_value() == "flex-secret-value"
    assert "flex-secret-value" not in f"{env!r} {env.secrets['IBKR_FLEX_TOKEN']}"


def test_load_env_file_does_not_override_a_setting_the_user_set(tmp_path, monkeypatch):
    """`load_dotenv(override=False)`'s rule for the non-secrets, kept. Break: dropping the
    `not in os.environ` check — red."""
    from ibkr_core_mcp.config import load_env_file

    monkeypatch.setenv("IBKR_GATEWAY_URL", "https://already.set/v1/api")
    load_env_file(_write_env(tmp_path / ".env", "IBKR_GATEWAY_URL=https://from.file/v1/api\n"))

    assert os.environ["IBKR_GATEWAY_URL"] == "https://already.set/v1/api"


@pytest.mark.skipif(os.name != "posix", reason="permission bits are POSIX")
@pytest.mark.parametrize("mode", [0o640, 0o604, 0o601], ids=["group-read", "other-read", "other-exec"])
def test_secrets_are_refused_when_the_file_is_accessible_to_others(tmp_path, monkeypatch, mode):
    """Design test 2. Any bit of 0o077 refuses the secrets, names `chmod 600 <path>`, never
    the value; the setting still loads. Break: the mask narrowed to 0o007 — the group case
    goes red."""
    from ibkr_core_mcp.config import load_env_file

    monkeypatch.delenv("IBKR_GATEWAY_URL", raising=False)
    path = _write_env(
        tmp_path / ".env",
        "IBKR_GATEWAY_URL=https://example.invalid/v1/api\nIBKR_FLEX_TOKEN=flex-secret-value\n",
        mode,
    )

    env = load_env_file(path)

    assert env.secrets == {}
    assert env.refused is not None
    assert f"chmod 600 {path}" in env.refused
    assert "flex-secret-value" not in env.refused
    assert os.environ["IBKR_GATEWAY_URL"] == "https://example.invalid/v1/api"


def test_a_missing_file_loads_nothing_and_refuses_nothing(tmp_path):
    from ibkr_core_mcp.config import load_env_file

    env = load_env_file(tmp_path / "absent.env")

    assert env.path is None and env.secrets == {} and env.refused is None


def test_from_env_reads_a_secret_the_user_set_and_writes_none_back(tmp_path, monkeypatch):
    """Design test 3: the MCP server and README contract. A secret in the real environment is
    still read (it wins over the file, as `override=False` always had it); a secret from the
    file reaches the `Config` and not the environment. Breaks: (a) `from_env` exporting the
    file's secret — red on the `not in os.environ` line; (b) file-over-environment — red on
    the first value."""
    from ibkr_core_mcp.config import Config

    monkeypatch.setenv("IBKR_FLEX_TOKEN", "from-the-environment")
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    path = _write_env(tmp_path / ".env", "IBKR_FLEX_TOKEN=from-the-file\nFIRECRAWL_API_KEY=fc-from-file\n")

    cfg = Config.from_env(dotenv_path=str(path))

    assert cfg.flex_token.get_secret_value() == "from-the-environment"
    assert cfg.firecrawl_api_key.get_secret_value() == "fc-from-file"
    assert "FIRECRAWL_API_KEY" not in os.environ
    assert "fc-from-file" not in repr(cfg)


def test_a_config_built_with_a_plain_string_secret_holds_a_secret_str(tmp_path):
    """A consumer that builds `Config(flex_token="…")` by hand keeps working. Break: delete
    `__post_init__` — red."""
    from pydantic import SecretStr

    from ibkr_core_mcp.config import Config

    cfg = Config(
        gateway_url="https://localhost:5055/v1/api",
        gdrive_folder_id="",
        sqlite_path=tmp_path / "store.db",
        gdrive_token_file=tmp_path / "token.json",
        gdrive_credentials_file=tmp_path / "credentials.json",
        flex_token="tok",  # type: ignore[arg-type]  # the plain-string form this test is about
        crawl4ai_profiles_dir=tmp_path / "profiles",
    )

    assert isinstance(cfg.flex_token, SecretStr)
    assert cfg.flex_token.get_secret_value() == "tok"
    assert isinstance(cfg.firecrawl_api_key, SecretStr) and not cfg.firecrawl_api_key


def test_from_env_holds_back_a_hosts_extra_secret_name(tmp_path, monkeypatch):
    """A host's own secret — claudia_ui's `ANTHROPIC_API_KEY` — is no `Config` field, and
    `from_env` must not export it as a setting: the host passes its names through to the
    loader. Found live on 2026-10-16: the key claudia_ui had removed at startup came back
    the moment the toolkit's `Config` was built. Break: the parameter not handed to
    `load_env_file` — red."""
    from ibkr_core_mcp.config import SECRET_NAMES, Config

    monkeypatch.delenv("HOST_SECRET", raising=False)
    monkeypatch.delenv("IBKR_GATEWAY_URL", raising=False)
    path = _write_env(
        tmp_path / ".env", "HOST_SECRET=host-secret-value\nIBKR_GATEWAY_URL=https://example.invalid/v1/api\n"
    )

    Config.from_env(dotenv_path=str(path), secret_names=(*SECRET_NAMES, "HOST_SECRET"))

    assert "HOST_SECRET" not in os.environ
    assert os.environ["IBKR_GATEWAY_URL"] == "https://example.invalid/v1/api"
