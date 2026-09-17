"""Environment-driven configuration for every ibkr_core_mcp service.

A single `Config` dataclass carries the gateway URL, Drive folder
and credential paths, and SQLite location. `Config.from_env()` is the only intended
constructor in application code; it reads a `.env` via python-dotenv and falls back
to process environment variables.

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

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

_DEFAULT_CRAWL4AI_PROFILES_DIR = "~/.ibkr_core/crawl4ai_profiles"


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

    No env var is required. Optional with defaults: IBKR_GATEWAY_URL, IBKR_SQLITE_PATH, GDRIVE_TOKEN_FILE,
    GDRIVE_CREDENTIALS_FILE. All others default to empty string (feature disabled).
    """

    gateway_url: str
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
    # Firecrawl REST API key (fc-...). If empty, firecrawl_search returns a "not
    # available" error string to the LLM rather than raising. It is the ONLY tool that
    # needs a key: fetch_page, crawl_site and search_site are a local browser and
    # public sitemaps.
    firecrawl_api_key: str = field(default="", repr=False)
    # Drive folder ID to use as the web_docs/ root. Auto-creates 'web_docs/' under
    # gdrive_folder_id if empty.
    gdrive_web_docs_folder_id: str = ""
    # Local directory holding Crawl4AI browser profiles (saved logins for paywalled
    # sites). One subfolder per domain, created via `python -m ibkr_core_mcp.local_browser
    # create-profile <url>`.
    crawl4ai_profiles_dir: Path = field(default_factory=lambda: crawl4ai_profiles_dir_from_env())

    @classmethod
    def from_env(cls, dotenv_path: str | None = None) -> Config:
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
        """
        load_dotenv(dotenv_path, override=False)

        return cls(
            gateway_url=os.environ.get("IBKR_GATEWAY_URL", "https://localhost:5055/v1/api"),
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
