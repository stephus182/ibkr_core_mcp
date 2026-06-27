from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


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

        Raises ConfigError if ANTHROPIC_API_KEY is not set.
        """
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
        )
