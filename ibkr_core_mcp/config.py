from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


@dataclass
class Config:
    """Configuration for all ibkr_core_mcp services. Use Config.from_env() to load from environment variables."""

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

    @classmethod
    def from_env(cls, dotenv_path: str | None = None) -> Config:
        load_dotenv(dotenv_path, override=False)

        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            from ibkr_core_mcp.exceptions import ConfigError
            raise ConfigError("ANTHROPIC_API_KEY is required but not set")

        return cls(
            gateway_url=os.environ.get(
                "IBKR_GATEWAY_URL", "https://localhost:5055/v1/api"
            ),
            anthropic_api_key=api_key,
            gdrive_folder_id=os.environ.get("GOOGLE_DRIVE_FOLDER_ID", ""),
            sqlite_path=Path(
                os.environ.get("IBKR_SQLITE_PATH", "~/.ibkr_core/store.db")
            ).expanduser(),
            gdrive_token_file=Path(
                os.environ.get("GDRIVE_TOKEN_FILE", "~/.ibkr_core/token.json")
            ).expanduser(),
            gdrive_credentials_file=Path(
                os.environ.get(
                    "GDRIVE_CREDENTIALS_FILE", "~/.ibkr_core/credentials.json"
                )
            ).expanduser(),
            flex_token=os.environ.get("IBKR_FLEX_TOKEN", ""),
            flex_query_id=os.environ.get("IBKR_FLEX_QUERY_ID", ""),
            gdrive_cache_folder_id=os.environ.get("GDRIVE_CACHE_FOLDER_ID", ""),
            gdrive_db_folder_id=os.environ.get("GDRIVE_DB_FOLDER_ID", ""),
            gdrive_account_folder_id=os.environ.get("GDRIVE_ACCOUNT_FOLDER_ID", ""),
            firecrawl_api_key=os.environ.get("FIRECRAWL_API_KEY", ""),
            gdrive_web_docs_folder_id=os.environ.get("GDRIVE_WEB_DOCS_FOLDER_ID", ""),
        )
