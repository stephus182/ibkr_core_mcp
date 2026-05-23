from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv


@dataclass
class Config:
    gateway_url: str
    anthropic_api_key: str
    gdrive_folder_id: str
    sqlite_path: Path
    gdrive_token_file: Path
    gdrive_credentials_file: Path

    @classmethod
    def from_env(cls, dotenv_path: str | None = None) -> "Config":
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
        )
