import pytest
from pathlib import Path
import tempfile
import os

@pytest.fixture
def tmp_db(tmp_path):
    """Temporary SQLite database path."""
    return tmp_path / "test_store.db"

@pytest.fixture
def mock_config(tmp_path, tmp_db):
    """Config with safe defaults for unit tests."""
    from ibkr_core_mcp.config import Config
    return Config(
        gateway_url="https://localhost:5055/v1/api",
        anthropic_api_key="test-key",
        gdrive_folder_id="test-folder-id",
        sqlite_path=tmp_db,
        gdrive_token_file=tmp_path / "token.json",
        gdrive_credentials_file=tmp_path / "credentials.json",
    )
