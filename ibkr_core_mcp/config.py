"""Environment-driven configuration for every ibkr_core_mcp service.

A single `Config` dataclass carries the gateway URL, Anthropic key, Drive folder
and credential paths, and SQLite location. `Config.from_env()` is the only intended
constructor in application code; it reads a `.env` via python-dotenv and falls back
to process environment variables.

Missing values resolve to empty strings rather than raising, which is deliberate:
it lets a caller construct a partial `Config` and have the *feature* that needs a
given variable report "not configured" at the point of use, instead of making an
unrelated import fail. See the standalone-dev note in `CLAUDE.md`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

_DEFAULT_CRAWL4AI_PROFILES_DIR = "~/.ibkr_core/crawl4ai_profiles"


def crawl4ai_profiles_dir_from_env(dotenv_path: str | None = None) -> Path:
    """Resolve the saved-browser-profile root **without** building a full `Config`.

    `Config.from_env()` raises when `ANTHROPIC_API_KEY` is unset, which is right for
    application startup and wrong for the two profile CLIs: creating or listing a
    saved browser login needs nothing from Anthropic, and routing them through
    `from_env()` made `create-profile` fail with "ANTHROPIC_API_KEY is required but
    not set" — an error naming a key the operation never uses. (Observed 2026-07-28
    on the first real run.)

    Reads the same `.env` and the same `CRAWL4AI_PROFILES_DIR` variable as
    `Config.crawl4ai_profiles_dir`, and shares its default, so the two can never
    disagree about where profiles live.

    Args:
        dotenv_path: Optional explicit `.env` to load, matching `Config.from_env()`.

    Returns:
        The profiles root, with `~` expanded. The directory is not created here.
    """
    load_dotenv(dotenv_path, override=False)
    return Path(os.environ.get("CRAWL4AI_PROFILES_DIR", _DEFAULT_CRAWL4AI_PROFILES_DIR)).expanduser()


@dataclass
class Config:
    """Configuration for all ibkr_core_mcp services.

    Load from environment variables with Config.from_env(). All fields map
    directly to environment variables (see from_env docstring for the mapping).

    Required env vars: ANTHROPIC_API_KEY.
    Optional with defaults: IBKR_GATEWAY_URL, IBKR_SQLITE_PATH, GDRIVE_TOKEN_FILE,
    GDRIVE_CREDENTIALS_FILE. All others default to empty string (feature disabled).
    """

    gateway_url: str
    anthropic_api_key: str = field(repr=False)
    gdrive_folder_id: str
    sqlite_path: Path
    gdrive_token_file: Path
    gdrive_credentials_file: Path
    flex_token: str = field(default="", repr=False)
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
    # Firecrawl REST API key (fc-...). If empty, firecrawl_search and firecrawl_crawl
    # return a "not available" error string to the LLM rather than raising.
    firecrawl_api_key: str = field(default="", repr=False)
    # Drive folder ID to use as the web_docs/ root. Auto-creates 'web_docs/' under
    # gdrive_folder_id if empty.
    gdrive_web_docs_folder_id: str = ""
    # Local directory holding Crawl4AI browser profiles (saved logins for paywalled
    # sites). One subfolder per domain, created via `python -m ibkr_core_mcp.scrape_fallback
    # create-profile <url>`.
    crawl4ai_profiles_dir: Path = field(default_factory=lambda: crawl4ai_profiles_dir_from_env())

    @classmethod
    def from_env(cls, dotenv_path: str | None = None) -> Config:
        """Load configuration from environment variables (with optional .env file).

        Environment variable → field mapping:
          ANTHROPIC_API_KEY          → anthropic_api_key   (required)
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

        Raises ConfigError if ANTHROPIC_API_KEY is not set.
        """
        load_dotenv(dotenv_path, override=False)

        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            from ibkr_core_mcp.exceptions import ConfigError

            raise ConfigError("ANTHROPIC_API_KEY is required but not set")

        return cls(
            gateway_url=os.environ.get("IBKR_GATEWAY_URL", "https://localhost:5055/v1/api"),
            anthropic_api_key=api_key,
            gdrive_folder_id=os.environ.get("GOOGLE_DRIVE_FOLDER_ID", ""),
            sqlite_path=Path(os.environ.get("IBKR_SQLITE_PATH", "~/.ibkr_core/store.db")).expanduser(),
            gdrive_token_file=Path(os.environ.get("GDRIVE_TOKEN_FILE", "~/.ibkr_core/token.json")).expanduser(),
            gdrive_credentials_file=Path(
                os.environ.get("GDRIVE_CREDENTIALS_FILE", "~/.ibkr_core/credentials.json")
            ).expanduser(),
            flex_token=os.environ.get("IBKR_FLEX_TOKEN", ""),
            flex_query_id=os.environ.get("IBKR_FLEX_QUERY_ID", ""),
            gdrive_cache_folder_id=os.environ.get("GDRIVE_CACHE_FOLDER_ID", ""),
            gdrive_db_folder_id=os.environ.get("GDRIVE_DB_FOLDER_ID", ""),
            gdrive_account_folder_id=os.environ.get("GDRIVE_ACCOUNT_FOLDER_ID", ""),
            firecrawl_api_key=os.environ.get("FIRECRAWL_API_KEY", ""),
            gdrive_web_docs_folder_id=os.environ.get("GDRIVE_WEB_DOCS_FOLDER_ID", ""),
            crawl4ai_profiles_dir=crawl4ai_profiles_dir_from_env(dotenv_path),
        )
