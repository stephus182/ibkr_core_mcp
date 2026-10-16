"""Environment-driven configuration for every ibkr_core_mcp service.

A single `Config` dataclass carries the gateway URL, Drive folder
and credential paths, and SQLite location. `Config.from_env()` is the only intended
constructor in application code; it reads a `.env` through `load_env_file` — settings
into the environment where unset, secrets into the `Config` as `SecretStr` and nowhere
else — and falls back to process environment variables.

Missing values resolve to empty strings rather than raising, which is deliberate:
it lets a caller construct a partial `Config` and have the *feature* that needs a
given variable report "not configured" at the point of use, instead of making an
unrelated import fail. See the standalone-dev note in `CLAUDE.md`.

**There is no exception, since 2026-09-17.** `from_env` used to raise `ConfigError`
when `ANTHROPIC_API_KEY` was missing, and this docstring gave the reason as "a toolkit
with no key cannot do anything at all". That was false: `ClaudeToolkit` reads
`flex_token`, `gateway_url`, `firecrawl_api_key` and `crawl4ai_profiles_dir` and never
touched the Anthropic key, nothing in the package imported the `anthropic` SDK, and the
field had zero readers from the day it was written (`182e483`, 2026-05-23; audit finding
TOOL-07). It cost the MCP server its ability to start, and was routed around three times
in two repositories rather than removed.

**This package makes no model calls, so it carries no model credentials — from any
vendor.** `ClaudeToolkit` defines tools; the host application owns the model client and
gets its own credential from its own environment. `openai_api_key` would be as wrong here
as `anthropic_api_key` was, which is why
`test_config_carries_no_model_vendor_credential` states the rule as a property rather
than a deletion.
"""

from __future__ import annotations

import logging
import os
import stat
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values, find_dotenv
from pydantic import SecretStr

from ibkr_core_mcp.redaction import collapse_home

log = logging.getLogger(__name__)

_DEFAULT_CRAWL4AI_PROFILES_DIR = "~/.ibkr_core/crawl4ai_profiles"

SECRET_NAMES: tuple[str, ...] = ("IBKR_FLEX_TOKEN", "FIRECRAWL_API_KEY")
"""The variables this package reads as secrets.

`load_env_file` never places one of these in the process environment: a child process
inherits the whole environment (CWE-526), and nothing this package starts — the Gate 2
dialog, `osascript`, the docker CLI — needs a token. A host adds its own names
(`load_env_file(..., secret_names=SECRET_NAMES + (...,))`).
"""

# Our mask: any permission bit for group or others. OpenSSH's man page asks the same of a
# private key file — "not accessible by others" — and ignores one that is.
_OTHERS_MASK = 0o077


@dataclass(frozen=True)
class EnvFile:
    """What `load_env_file` read: the file, the secrets it holds, and why they were refused.

    `path` is None when no file was found. `secrets` is empty when the file holds none, or
    when `refused` says why none were loaded. A `SecretStr` prints as `**********`; the value
    is reached with `.get_secret_value()` at the one place that sends it.
    """

    path: Path | None
    secrets: Mapping[str, SecretStr]
    refused: str | None = None


def _too_open(path: Path) -> str | None:
    """The refusal message when `path` is accessible to group or others; None where it is not.

    POSIX only: Windows synthesises these bits, so there the check would refuse every file.
    """
    if os.name != "posix":
        return None  # pragma: no cover - Windows has no POSIX permission bits to read
    mode = path.stat().st_mode
    if not mode & _OTHERS_MASK:
        return None
    # A log line, and a sentence the operator will paste: the home directory is `~` in it,
    # never the account name — `collapse_home`'s inventory (SEC-10) has this call site.
    shown = collapse_home(str(path))
    return (
        f"{shown} is accessible to other users (mode {stat.filemode(mode)}), so its secrets "
        f"were not loaded. Fix: chmod 600 {shown}"
    )


def load_env_file(
    dotenv_path: str | os.PathLike[str] | None = None,
    *,
    secret_names: Iterable[str] = SECRET_NAMES,
) -> EnvFile:
    """Read a `.env`: settings into `os.environ` where unset, secrets returned, never exported.

    The one loader of this package (register F48, 2026-10-16). It replaced two calls of
    `load_dotenv(override=False)`, which copied the whole file — `IBKR_FLEX_TOKEN` and
    `FIRECRAWL_API_KEY` included — into the environment of this process and so of every
    child it starts. For the non-secret entries nothing changes: each is set only where the
    environment does not already hold it, as before. A secret entry comes back in
    `EnvFile.secrets` as a `SecretStr` and is written nowhere.

    With no `dotenv_path` the file is found as `load_dotenv` found it: python-dotenv's
    `find_dotenv`, walking up from this package's directory. A host whose `.env` lies
    elsewhere passes the path (claudia_ui does).

    On POSIX a file accessible to group or others (any bit of 0o077) has its secrets
    REFUSED, not loaded: `refused` carries the message, with `chmod 600 <path>`, and the
    settings still load, so each feature needing the missing secret reports "not
    configured" at its point of use. The message never carries a value.

    Args:
        dotenv_path: The file, or None for the default search.
        secret_names: The names treated as secrets; `SECRET_NAMES` by default.

    Returns:
        An `EnvFile`; `path` None when no file was found.
    """
    found = os.fspath(dotenv_path) if dotenv_path is not None else find_dotenv()
    if not found or not Path(found).is_file():
        return EnvFile(path=None, secrets={})
    path = Path(found)
    secret = frozenset(secret_names)
    secrets: dict[str, SecretStr] = {}
    for name, value in dotenv_values(path).items():
        if value is None:
            continue
        if name in secret:
            if value:
                secrets[name] = SecretStr(value)
        elif name not in os.environ:
            os.environ[name] = value
    refused = _too_open(path)
    if refused is not None:
        log.warning(refused)
        return EnvFile(path=path, secrets={}, refused=refused)
    return EnvFile(path=path, secrets=secrets)


def crawl4ai_profiles_dir_from_env(dotenv_path: str | None = None) -> Path:
    """Resolve the saved-browser-profile root **without** building a full `Config`.

    Written 2026-07-28 because `Config.from_env()` raised when `ANTHROPIC_API_KEY` was
    unset, and `create-profile` then failed with "ANTHROPIC_API_KEY is required but not
    set" — an error naming a key the operation never uses, seen on the first real run.
    **That requirement is gone (TOOL-07, 2026-09-17)**, so this is no longer a workaround;
    it is kept because it is still the narrower thing to call. The two profile CLIs need
    one directory, not a whole `Config`, and a function that reads one variable cannot
    fail for a reason belonging to another.

    Reads the same `.env` and the same `CRAWL4AI_PROFILES_DIR` variable as
    `Config.crawl4ai_profiles_dir`, and shares its default, so the two can never
    disagree about where profiles live — through `load_env_file`, so a secret in that
    file is never exported here either.

    Args:
        dotenv_path: Optional explicit `.env` to load, matching `Config.from_env()`.

    Returns:
        The profiles root, with `~` expanded. The directory is not created here.
    """
    load_env_file(dotenv_path)
    return Path(os.environ.get("CRAWL4AI_PROFILES_DIR", _DEFAULT_CRAWL4AI_PROFILES_DIR)).expanduser()


def _secret(from_environment: str | None, from_file: SecretStr | None) -> SecretStr:
    """A secret as `from_env` resolves it: the user's own environment first — the documented
    contract for the MCP server and any other client — then the file, else empty."""
    if from_environment:
        return SecretStr(from_environment)
    return from_file if from_file is not None else SecretStr("")


@dataclass
class Config:
    """Configuration for all ibkr_core_mcp services.

    Load from environment variables with Config.from_env(). All fields map
    directly to environment variables (see from_env docstring for the mapping).

    No env var is required. Optional with defaults: IBKR_GATEWAY_URL, IBKR_SQLITE_PATH, GDRIVE_TOKEN_FILE,
    GDRIVE_CREDENTIALS_FILE. All others default to empty string (feature disabled).
    """

    gateway_url: str
    gdrive_folder_id: str
    sqlite_path: Path
    gdrive_token_file: Path
    gdrive_credentials_file: Path
    flex_token: SecretStr = field(default_factory=lambda: SecretStr(""), repr=False)
    flex_query_id: str = ""
    # Optional dedicated folder for OHLCV Parquet cache files.
    # If empty, GDriveCache auto-creates a 'market_data/' subfolder inside gdrive_folder_id.
    gdrive_cache_folder_id: str = ""
    # Optional dedicated folder for claudia.db.
    # If empty, GDriveSync auto-creates a 'db/' subfolder inside gdrive_folder_id.
    gdrive_db_folder_id: str = ""
    # Optional dedicated folder for account-level data (flex XMLs, etc.).
    # If empty, GDriveCache auto-creates an 'account_data/' subfolder inside gdrive_folder_id.
    gdrive_account_folder_id: str = ""
    # Firecrawl REST API key (fc-...). If empty, firecrawl_search returns a "not
    # available" error string to the LLM rather than raising. It is the ONLY tool that
    # needs a key: fetch_page, crawl_site and search_site are a local browser and
    # public sitemaps.
    firecrawl_api_key: SecretStr = field(default_factory=lambda: SecretStr(""), repr=False)
    # Drive folder ID to use as the web_docs/ root. Auto-creates 'web_docs/' under
    # gdrive_folder_id if empty.
    gdrive_web_docs_folder_id: str = ""
    # Local directory holding Crawl4AI browser profiles (saved logins for paywalled
    # sites). One subfolder per domain, created via `python -m ibkr_core_mcp.local_browser
    # create-profile <url>`.
    crawl4ai_profiles_dir: Path = field(default_factory=lambda: crawl4ai_profiles_dir_from_env())

    def __post_init__(self) -> None:
        """A plain string given for a secret field becomes a `SecretStr`.

        The fields are typed `SecretStr` (register F48), and the two consumers unwrap them
        with `.get_secret_value()`; a `Config` built by hand with a string would otherwise
        fail at the Flex request or the Firecrawl client, far from the construction. A
        dataclass validates nothing, so this is where the type is made true.
        """
        for name in ("flex_token", "firecrawl_api_key"):
            value = getattr(self, name)
            if isinstance(value, str):
                setattr(self, name, SecretStr(value))

    @classmethod
    def from_env(cls, dotenv_path: str | None = None, *, secret_names: Iterable[str] = SECRET_NAMES) -> Config:
        """Load configuration from environment variables (with optional .env file).

        Environment variable → field mapping:
          IBKR_GATEWAY_URL           → gateway_url         (default: https://localhost:5055/v1/api)
          GOOGLE_DRIVE_FOLDER_ID     → gdrive_folder_id    (required for Drive features)
          IBKR_SQLITE_PATH           → sqlite_path         (default: ~/.ibkr_core/store.db)
          GDRIVE_TOKEN_FILE          → gdrive_token_file   (default: ~/.ibkr_core/token.json)
          GDRIVE_CREDENTIALS_FILE    → gdrive_credentials_file (default: ~/.ibkr_core/credentials.json)
          IBKR_FLEX_TOKEN            → flex_token          (required for Flex sync)
          IBKR_FLEX_QUERY_ID         → flex_query_id       (required for Flex sync)
          GDRIVE_CACHE_FOLDER_ID     → gdrive_cache_folder_id  (optional; auto-created as market_data/)
          GDRIVE_DB_FOLDER_ID        → gdrive_db_folder_id     (optional; auto-created as db/)
          GDRIVE_ACCOUNT_FOLDER_ID   → gdrive_account_folder_id (optional; auto-created as account_data/)
          FIRECRAWL_API_KEY          → firecrawl_api_key       (optional; enables web scraper)
          GDRIVE_WEB_DOCS_FOLDER_ID  → gdrive_web_docs_folder_id (optional; auto-created as web_docs/)
          CRAWL4AI_PROFILES_DIR      → crawl4ai_profiles_dir   (default: ~/.ibkr_core/crawl4ai_profiles)

        Raises nothing: every value resolves to a default or an empty string, and the
        feature that needs one reports "not configured" at the point of use. `ANTHROPIC_API_KEY`
        was the single exception until 2026-09-17 — see the module docstring (TOOL-07).

        A secret (`IBKR_FLEX_TOKEN`, `FIRECRAWL_API_KEY`) is read from the environment if the
        user set it there, else from the file, and is never written to the environment
        (register F48). A host with secrets of its own in the same file passes their names in
        `secret_names` (its own list, which should include `SECRET_NAMES`), so that none of
        them is exported as a setting either — claudia_ui's `ANTHROPIC_API_KEY` was, the
        moment its toolkit's `Config` was built, until 2026-10-16.
        """
        env = load_env_file(dotenv_path, secret_names=secret_names)

        return cls(
            gateway_url=os.environ.get("IBKR_GATEWAY_URL", "https://localhost:5055/v1/api"),
            gdrive_folder_id=os.environ.get("GOOGLE_DRIVE_FOLDER_ID", ""),
            sqlite_path=Path(os.environ.get("IBKR_SQLITE_PATH", "~/.ibkr_core/store.db")).expanduser(),
            gdrive_token_file=Path(os.environ.get("GDRIVE_TOKEN_FILE", "~/.ibkr_core/token.json")).expanduser(),
            gdrive_credentials_file=Path(
                os.environ.get("GDRIVE_CREDENTIALS_FILE", "~/.ibkr_core/credentials.json")
            ).expanduser(),
            flex_token=_secret(os.environ.get("IBKR_FLEX_TOKEN"), env.secrets.get("IBKR_FLEX_TOKEN")),
            flex_query_id=os.environ.get("IBKR_FLEX_QUERY_ID", ""),
            gdrive_cache_folder_id=os.environ.get("GDRIVE_CACHE_FOLDER_ID", ""),
            gdrive_db_folder_id=os.environ.get("GDRIVE_DB_FOLDER_ID", ""),
            gdrive_account_folder_id=os.environ.get("GDRIVE_ACCOUNT_FOLDER_ID", ""),
            firecrawl_api_key=_secret(os.environ.get("FIRECRAWL_API_KEY"), env.secrets.get("FIRECRAWL_API_KEY")),
            gdrive_web_docs_folder_id=os.environ.get("GDRIVE_WEB_DOCS_FOLDER_ID", ""),
            crawl4ai_profiles_dir=Path(
                os.environ.get("CRAWL4AI_PROFILES_DIR", _DEFAULT_CRAWL4AI_PROFILES_DIR)
            ).expanduser(),
        )
