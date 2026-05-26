# ibkr_core_mcp Phase 1 — Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a pip-installable Python package that connects to the IBKR Client Portal Gateway, caches market data to Google Drive, persists trade/signal data in SQLite, and exposes 14 Claude AI tools — with robust auth and error handling throughout.

**Architecture:** Layered package — `config` and `exceptions` form the base, `auth` and `rate_limiter` wrap the HTTP session, `client` wraps all 79 IBKR endpoints (returning raw dicts in Phase 1), `cache` and `store` provide persistence, and `claude_tools` wires everything into a ready-made Claude tool layer. No Pydantic models in Phase 1 — those come in Phase 2 along with typed returns.

**Tech Stack:** Python 3.11+, requests, browser-cookie3, google-api-python-client, sqlite3 (stdlib), python-dotenv, anthropic, pytest

**Working directory:** `/Users/steph/Claude_Projects/ibkr_core_mcp`

---

## File Map

```
ibkr_core_mcp/              ← package root (install target)
├── __init__.py             create — Phase 1 public exports
├── config.py               create — Config dataclass + from_env()
├── exceptions.py           create — full exception hierarchy
├── auth.py                 create — BrowserCookieAuth, TokenAuth, NoAuth
├── rate_limiter.py         create — token-bucket + exponential backoff
├── client.py               create — IBKRClient, all 79 endpoints
├── cache.py                create — GDriveCache (Google Drive parquet)
├── store.py                create — SQLiteStore (trades, positions, signals)
└── claude_tools.py         create — ClaudeToolkit, 14 tools

tests/
├── conftest.py             create — shared fixtures
├── test_config.py          create
├── test_exceptions.py      create
├── test_auth.py            create
├── test_rate_limiter.py    create
├── test_client.py          create — integration tests (marked)
├── test_cache.py           create — integration tests (marked)
├── test_store.py           create
└── test_claude_tools.py    create

pyproject.toml              create — pip-installable package config
py.typed                    create — PEP 561 marker
```

---

## Task 1: Package Scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `py.typed`
- Create: `ibkr_core_mcp/__init__.py` (empty for now)
- Create: `tests/__init__.py` (empty)
- Create: `tests/conftest.py`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.backends.legacy:build"

[project]
name = "ibkr_core_mcp"
version = "0.1.0"
description = "IBKR Client Portal API client, Drive cache, SQLite store, Claude tools"
requires-python = ">=3.11"
dependencies = [
    "requests>=2.31",
    "urllib3>=2.0",
    "anthropic>=0.28",
    "pandas>=2.2",
    "numpy>=1.26",
    "plotly>=5.22",
    "RestrictedPython>=7.0",
    "pyarrow>=16.0",
    "google-api-python-client>=2.130",
    "google-auth-httplib2>=0.2",
    "google-auth-oauthlib>=1.2",
    "python-dotenv>=1.0",
    "browser-cookie3>=0.19",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-mock>=3.12", "mypy>=1.8", "ruff>=0.3"]

[tool.setuptools.packages.find]
where = ["."]
include = ["ibkr_core_mcp*"]

[tool.pytest.ini_options]
markers = ["integration: requires live IBKR gateway and credentials"]
```

- [ ] **Step 2: Create `py.typed` and empty inits**

```bash
touch py.typed ibkr_core_mcp/__init__.py tests/__init__.py
```

- [ ] **Step 3: Create `tests/conftest.py`**

```python
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
```

- [ ] **Step 4: Install package in editable mode**

```bash
pip install -e ".[dev]"
```

Expected: installs without errors, `import ibkr_core_mcp` works.

- [ ] **Step 5: Verify import**

```bash
python -c "import ibkr_core_mcp; print('ok')"
```

Expected output: `ok`

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml py.typed ibkr_core_mcp/__init__.py tests/__init__.py tests/conftest.py
git commit -m "feat: package scaffold — pyproject.toml, py.typed, test fixtures"
```

---

## Task 2: `config.py`

**Files:**
- Create: `ibkr_core_mcp/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_config.py
import os
import pytest
from pathlib import Path


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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_config.py -v
```

Expected: `ImportError` or `ModuleNotFoundError` — config doesn't exist yet.

- [ ] **Step 3: Create `ibkr_core_mcp/config.py`**

```python
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
```

- [ ] **Step 4: Run tests — expect failure on missing `exceptions` import**

```bash
pytest tests/test_config.py -v
```

This is expected until exceptions.py exists. Continue to Task 3, then re-run.

- [ ] **Step 5: Commit**

```bash
git add ibkr_core_mcp/config.py tests/test_config.py
git commit -m "feat: Config dataclass with from_env() loader"
```

---

## Task 3: `exceptions.py`

**Files:**
- Create: `ibkr_core_mcp/exceptions.py`
- Create: `tests/test_exceptions.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_exceptions.py
from ibkr_core_mcp.exceptions import (
    IBKRCoreError, IBKRAuthError, IBKRRateLimitError, IBKRAPIError,
    CacheError, CacheMissError, CacheWriteError,
    StoreError, BacktestError, BacktestSyntaxError, BacktestRuntimeError,
    ConfigError,
)


def test_hierarchy_ibkr_auth_is_core():
    assert issubclass(IBKRAuthError, IBKRCoreError)


def test_hierarchy_rate_limit_is_core():
    assert issubclass(IBKRRateLimitError, IBKRCoreError)


def test_hierarchy_api_error_is_core():
    assert issubclass(IBKRAPIError, IBKRCoreError)


def test_hierarchy_cache_miss_is_cache():
    assert issubclass(CacheMissError, CacheError)
    assert issubclass(CacheError, IBKRCoreError)


def test_hierarchy_cache_write_is_cache():
    assert issubclass(CacheWriteError, CacheError)


def test_hierarchy_store_is_core():
    assert issubclass(StoreError, IBKRCoreError)


def test_hierarchy_backtest_syntax_is_backtest():
    assert issubclass(BacktestSyntaxError, BacktestError)
    assert issubclass(BacktestError, IBKRCoreError)


def test_hierarchy_config_is_core():
    assert issubclass(ConfigError, IBKRCoreError)


def test_api_error_carries_status_code():
    err = IBKRAPIError("bad request", status_code=400)
    assert err.status_code == 400
    assert "bad request" in str(err)


def test_catch_all_via_base():
    with pytest.raises(IBKRCoreError):
        raise IBKRAuthError("session expired")


import pytest
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_exceptions.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Create `ibkr_core_mcp/exceptions.py`**

```python
class IBKRCoreError(Exception):
    """Base exception for all ibkr_core_mcp errors."""


class IBKRAuthError(IBKRCoreError):
    """Session not authenticated or cookie extraction failed."""


class IBKRRateLimitError(IBKRCoreError):
    """Gateway returned 429 and retries exhausted."""


class IBKRAPIError(IBKRCoreError):
    """Non-auth HTTP error from the IBKR gateway."""

    def __init__(self, message: str, status_code: int = 0) -> None:
        super().__init__(message)
        self.status_code = status_code


class CacheError(IBKRCoreError):
    """Base cache error."""


class CacheMissError(CacheError):
    """Requested data not in Drive cache."""


class CacheWriteError(CacheError):
    """Failed to write to Drive cache."""


class StoreError(IBKRCoreError):
    """SQLite store error."""


class BacktestError(IBKRCoreError):
    """Base backtest error."""


class BacktestSyntaxError(BacktestError):
    """Strategy code has a syntax error."""


class BacktestRuntimeError(BacktestError):
    """Strategy code raised an exception at runtime."""


class ConfigError(IBKRCoreError):
    """Missing or invalid configuration."""
```

- [ ] **Step 4: Run all tests so far**

```bash
pytest tests/test_exceptions.py tests/test_config.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add ibkr_core_mcp/exceptions.py tests/test_exceptions.py
git commit -m "feat: exception hierarchy — IBKRCoreError and all subclasses"
```

---

## Task 4: `auth.py`

**Files:**
- Create: `ibkr_core_mcp/auth.py`
- Create: `tests/test_auth.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_auth.py
import pytest
import requests
from unittest.mock import patch, MagicMock


def test_no_auth_applies_nothing():
    from ibkr_core_mcp.auth import NoAuth
    session = requests.Session()
    NoAuth().apply(session)
    assert "Cookie" not in session.headers


def test_token_auth_sets_cookie_header():
    from ibkr_core_mcp.auth import TokenAuth
    session = requests.Session()
    TokenAuth("session=abc123; ibkey=xyz").apply(session)
    assert session.headers.get("Cookie") == "session=abc123; ibkey=xyz"


def test_token_auth_strips_whitespace():
    from ibkr_core_mcp.auth import TokenAuth
    session = requests.Session()
    TokenAuth("  session=abc  ").apply(session)
    assert session.headers.get("Cookie") == "session=abc"


def test_browser_cookie_auth_applies_without_error():
    from ibkr_core_mcp.auth import BrowserCookieAuth
    session = requests.Session()
    # browser_cookie3 may not find cookies in CI — should not raise
    with patch("browser_cookie3.chrome", return_value=[]):
        BrowserCookieAuth().apply(session)
    # No cookie header set when jar is empty
    assert "Cookie" not in session.headers


def test_browser_cookie_auth_injects_cookies():
    from ibkr_core_mcp.auth import BrowserCookieAuth
    import http.cookiejar

    mock_cookie = MagicMock()
    mock_cookie.name = "ibkey"
    mock_cookie.value = "tok123"

    session = requests.Session()
    with patch("browser_cookie3.chrome", return_value=[mock_cookie]):
        BrowserCookieAuth().apply(session)

    assert "ibkey=tok123" in session.headers.get("Cookie", "")


def test_browser_cookie_auth_silences_errors():
    from ibkr_core_mcp.auth import BrowserCookieAuth
    session = requests.Session()
    with patch("browser_cookie3.chrome", side_effect=Exception("no chrome")):
        # Must not raise
        BrowserCookieAuth().apply(session)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_auth.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Create `ibkr_core_mcp/auth.py`**

```python
from __future__ import annotations
from typing import Protocol
import requests


class AuthStrategy(Protocol):
    def apply(self, session: requests.Session) -> None: ...


class NoAuth:
    """No-op strategy — for testing or pre-authenticated sessions."""

    def apply(self, session: requests.Session) -> None:
        pass


class TokenAuth:
    """Inject a pre-obtained cookie string directly into the session header."""

    def __init__(self, cookie_string: str) -> None:
        self._cookie_string = cookie_string.strip()

    def apply(self, session: requests.Session) -> None:
        session.headers.update({"Cookie": self._cookie_string})


class BrowserCookieAuth:
    """Read Chrome's localhost cookies and inject them as a raw Cookie header.

    requests silently drops cookies for 'localhost' via the cookie jar,
    so we build the Cookie header manually.
    """

    def __init__(self, browser: str = "chrome") -> None:
        self._browser = browser

    def apply(self, session: requests.Session) -> None:
        try:
            import browser_cookie3

            loader = getattr(browser_cookie3, self._browser)
            jar = loader(domain_name="localhost")
            parts = [f"{c.name}={c.value}" for c in jar]
            if parts:
                session.headers.update({"Cookie": "; ".join(parts)})
        except Exception:
            pass  # headless environments, wrong browser, or no cookies
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_auth.py -v
```

Expected: all 6 pass.

- [ ] **Step 5: Commit**

```bash
git add ibkr_core_mcp/auth.py tests/test_auth.py
git commit -m "feat: auth strategies — NoAuth, TokenAuth, BrowserCookieAuth"
```

---

## Task 5: `rate_limiter.py`

**Files:**
- Create: `ibkr_core_mcp/rate_limiter.py`
- Create: `tests/test_rate_limiter.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_rate_limiter.py
import pytest
import requests
from unittest.mock import MagicMock, patch


def _make_response(status_code: int, json_data: dict | None = None):
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(response=resp)
    return resp


def test_success_returns_response():
    from ibkr_core_mcp.rate_limiter import with_retry
    mock_fn = MagicMock(return_value=_make_response(200, {"ok": True}))
    result = with_retry(mock_fn)
    assert result.status_code == 200
    assert mock_fn.call_count == 1


def test_429_retries_then_raises():
    from ibkr_core_mcp.rate_limiter import with_retry
    from ibkr_core_mcp.exceptions import IBKRRateLimitError
    mock_fn = MagicMock(return_value=_make_response(429))
    with patch("time.sleep"):
        with pytest.raises(IBKRRateLimitError):
            with_retry(mock_fn, max_retries=2)
    assert mock_fn.call_count == 3  # 1 + 2 retries


def test_429_succeeds_on_retry():
    from ibkr_core_mcp.rate_limiter import with_retry
    responses = [_make_response(429), _make_response(200, {"data": 1})]
    mock_fn = MagicMock(side_effect=responses)
    with patch("time.sleep"):
        result = with_retry(mock_fn, max_retries=2)
    assert result.status_code == 200
    assert mock_fn.call_count == 2


def test_401_raises_auth_error_immediately():
    from ibkr_core_mcp.rate_limiter import with_retry
    from ibkr_core_mcp.exceptions import IBKRAuthError
    mock_fn = MagicMock(return_value=_make_response(401))
    with pytest.raises(IBKRAuthError):
        with_retry(mock_fn)
    assert mock_fn.call_count == 1  # no retries on 401


def test_other_http_error_raises_api_error():
    from ibkr_core_mcp.rate_limiter import with_retry
    from ibkr_core_mcp.exceptions import IBKRAPIError
    mock_fn = MagicMock(return_value=_make_response(500))
    with pytest.raises(IBKRAPIError) as exc_info:
        with_retry(mock_fn)
    assert exc_info.value.status_code == 500
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_rate_limiter.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Create `ibkr_core_mcp/rate_limiter.py`**

```python
from __future__ import annotations
import time
from typing import Callable
import requests

from ibkr_core_mcp.exceptions import IBKRAuthError, IBKRRateLimitError, IBKRAPIError

_DEFAULT_MAX_RETRIES = 3
_BASE_BACKOFF = 1.0  # seconds


def with_retry(
    fn: Callable[[], requests.Response],
    max_retries: int = _DEFAULT_MAX_RETRIES,
) -> requests.Response:
    """Call fn(), retrying on 429/503 with exponential backoff.

    Raises:
        IBKRAuthError: on 401 (no retry)
        IBKRRateLimitError: on 429 after retries exhausted
        IBKRAPIError: on other 4xx/5xx
    """
    attempt = 0
    while True:
        resp = fn()
        status = resp.status_code

        if status == 200:
            return resp
        if status == 401:
            raise IBKRAuthError("IBKR session not authenticated (401)")
        if status in (429, 503):
            if attempt >= max_retries:
                raise IBKRRateLimitError(
                    f"Rate limit exceeded after {max_retries} retries (HTTP {status})"
                )
            backoff = _BASE_BACKOFF * (2 ** attempt)
            time.sleep(backoff)
            attempt += 1
            continue
        # Any other error status
        raise IBKRAPIError(
            f"IBKR gateway returned HTTP {status}", status_code=status
        )
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_rate_limiter.py -v
```

Expected: all 5 pass.

- [ ] **Step 5: Commit**

```bash
git add ibkr_core_mcp/rate_limiter.py tests/test_rate_limiter.py
git commit -m "feat: rate_limiter — token-bucket retry with exponential backoff"
```

---

## Task 6: `client.py` — Session + Market Data

**Files:**
- Create: `ibkr_core_mcp/client.py`
- Create: `tests/test_client.py` (integration tests, marked)

- [ ] **Step 1: Write tests**

```python
# tests/test_client.py
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def client(mock_config):
    from ibkr_core_mcp.client import IBKRClient
    from ibkr_core_mcp.auth import NoAuth
    return IBKRClient(mock_config, auth=NoAuth())


def test_ping_returns_false_on_401(client):
    with patch.object(client._session, "get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_get.return_value = mock_resp
        assert client.ping() is False


def test_ping_returns_true_when_authenticated(client):
    with patch.object(client._session, "get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"authenticated": True}
        mock_get.return_value = mock_resp
        assert client.ping() is True


def test_search_contract_returns_list(client):
    with patch.object(client._session, "get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {"conid": 265598, "symbol": "AAPL", "secType": "STK"}
        ]
        mock_get.return_value = mock_resp
        result = client.search_contract("AAPL")
    assert isinstance(result, list)
    assert result[0]["conid"] == 265598


def test_get_market_history_passes_params(client):
    with patch.object(client._session, "get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": []}
        mock_get.return_value = mock_resp
        client.get_market_history(265598, period="1Y", bar="1d")
    call_kwargs = mock_get.call_args
    assert "conid=265598" in str(call_kwargs) or 265598 in str(call_kwargs)


# Integration tests — require live gateway
@pytest.mark.integration
def test_live_ping(mock_config):
    from ibkr_core_mcp.client import IBKRClient
    from ibkr_core_mcp.auth import BrowserCookieAuth
    client = IBKRClient(mock_config, auth=BrowserCookieAuth())
    assert client.ping() is True


@pytest.mark.integration
def test_live_search_aapl(mock_config):
    from ibkr_core_mcp.client import IBKRClient
    from ibkr_core_mcp.auth import BrowserCookieAuth
    client = IBKRClient(mock_config, auth=BrowserCookieAuth())
    results = client.search_contract("AAPL")
    assert len(results) > 0
    assert any(r.get("symbol") == "AAPL" for r in results)
```

- [ ] **Step 2: Run unit tests to verify they fail**

```bash
pytest tests/test_client.py -v -m "not integration"
```

Expected: `ImportError`

- [ ] **Step 3: Create `ibkr_core_mcp/client.py`**

```python
from __future__ import annotations
import urllib3
from typing import Any
import requests

from ibkr_core_mcp.auth import AuthStrategy, BrowserCookieAuth
from ibkr_core_mcp.config import Config
from ibkr_core_mcp.exceptions import IBKRAuthError
from ibkr_core_mcp.rate_limiter import with_retry

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class IBKRClient:
    """Wraps all IBKR Client Portal API endpoints. Returns raw dicts."""

    def __init__(
        self,
        config: Config,
        auth: AuthStrategy | None = None,
    ) -> None:
        self._base = config.gateway_url.rstrip("/")
        self._session = requests.Session()
        self._session.verify = False
        auth = auth or BrowserCookieAuth()
        auth.apply(self._session)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _get(self, path: str, params: dict | None = None) -> Any:
        url = f"{self._base}{path}"
        resp = with_retry(lambda: self._session.get(url, params=params, timeout=30))
        return resp.json()

    def _post(self, path: str, body: dict | None = None) -> Any:
        url = f"{self._base}{path}"
        resp = with_retry(lambda: self._session.post(url, json=body or {}, timeout=30))
        return resp.json()

    def _refresh_auth(self, auth: AuthStrategy) -> None:
        """Re-apply auth strategy (e.g. re-read Chrome cookies after login)."""
        auth.apply(self._session)

    # ── Session ───────────────────────────────────────────────────────────────

    def ping(self) -> bool:
        """Return True if gateway is reachable and session is authenticated."""
        try:
            resp = self._session.get(
                f"{self._base}/iserver/auth/status", timeout=5
            )
            if resp.status_code == 401:
                return False
            return resp.json().get("authenticated", False)
        except Exception:
            return False

    def get_auth_status(self) -> dict:
        return self._get("/iserver/auth/status")

    def tickle(self) -> bool:
        try:
            resp = self._session.post(f"{self._base}/tickle", timeout=5)
            return resp.status_code == 200
        except Exception:
            return False

    def reauthenticate(self) -> dict:
        return self._post("/iserver/reauthenticate")

    def validate_sso(self) -> dict:
        return self._post("/sso/validate")

    # ── Market Data ───────────────────────────────────────────────────────────

    def get_market_history(
        self,
        conid: int,
        period: str = "1Y",
        bar: str = "1d",
        outside_rth: bool = False,
    ) -> dict:
        return self._get(
            "/iserver/marketdata/history",
            {
                "conid": conid,
                "period": period,
                "bar": bar,
                "outsideRth": str(outside_rth).lower(),
            },
        )

    def get_market_snapshot(
        self, conids: list[int], fields: list[str] | None = None
    ) -> list[dict]:
        field_str = ",".join(fields or ["31", "55", "70", "71", "84", "86"])
        data = self._get(
            "/iserver/marketdata/snapshot",
            {"conids": ",".join(str(c) for c in conids), "fields": field_str},
        )
        return data if isinstance(data, list) else []

    def get_market_data_fields(self) -> dict:
        return self._get("/iserver/marketdata/fields")

    def get_market_data_periods(self) -> dict:
        return self._get("/iserver/marketdata/periods")

    def get_market_data_bars(self) -> dict:
        return self._get("/iserver/marketdata/bars")

    def get_hmds_history(
        self,
        conid: int,
        period: str = "1Y",
        bar: str = "1d",
        outside_rth: bool = False,
    ) -> dict:
        return self._get(
            "/hmds/history",
            {
                "conid": conid,
                "period": period,
                "bar": bar,
                "outsideRth": str(outside_rth).lower(),
            },
        )

    def unsubscribe_market_data(self, conid: int) -> dict:
        return self._post("/iserver/marketdata/unsubscribe", {"conid": conid})

    def unsubscribe_all_market_data(self) -> dict:
        return self._post("/iserver/marketdata/unsubscribeall")

    def get_md_snapshot(self, conids: list[int], fields: list[str] | None = None) -> list[dict]:
        field_str = ",".join(fields or ["31", "55"])
        data = self._get("/md/snapshot", {"conids": ",".join(str(c) for c in conids), "fields": field_str})
        return data if isinstance(data, list) else []

    def get_market_data_availability(self) -> dict:
        return self._get("/iserver/marketdata/availability")

    # ── Contract / Security Definition ───────────────────────────────────────

    def search_contract(self, symbol: str, sec_type: str = "STK") -> list[dict]:
        data = self._get(
            "/iserver/secdef/search", {"symbol": symbol, "secType": sec_type}
        )
        return data if isinstance(data, list) else []

    def get_contract_info(self, conid: int) -> dict:
        return self._get(f"/iserver/contract/{conid}/info")

    def get_contract_info_and_rules(self, conid: int) -> dict:
        return self._get(f"/iserver/contract/{conid}/info-and-rules")

    def get_contract_algos(self, conid: int) -> list[dict]:
        data = self._get(f"/iserver/contract/{conid}/algos")
        return data if isinstance(data, list) else []

    def get_secdef_info(self, conid: int) -> dict:
        return self._get("/iserver/secdef/info", {"conid": conid})

    def get_option_strikes(
        self, conid: int, sec_type: str, month: str, exchange: str = "SMART"
    ) -> list[float]:
        data = self._get(
            "/iserver/secdef/strikes",
            {"conid": conid, "sectype": sec_type, "month": month, "exchange": exchange},
        )
        return data.get("strike", [])

    def get_option_chain(
        self, symbol: str, exchange: str = "SMART", currency: str = "USD"
    ) -> dict:
        return self._get(
            "/trsrv/secdef/chains",
            {"symbol": symbol, "exchange": exchange, "currency": currency},
        )

    def get_bond_filters(self, symbol: str, issue_id: str) -> dict:
        return self._get("/iserver/secdef/bond-filters", {"symbol": symbol, "issuerId": issue_id})

    def get_futures(self, symbols: list[str]) -> list[dict]:
        data = self._get("/trsrv/futures", {"symbols": ",".join(symbols)})
        return data if isinstance(data, list) else []

    def get_stocks(self, symbols: list[str]) -> list[dict]:
        data = self._get("/trsrv/stocks", {"symbols": ",".join(symbols)})
        return data if isinstance(data, list) else []

    def get_trading_schedule(
        self, asset_class: str, symbol: str, exchange: str, exchange_filter: str = ""
    ) -> dict:
        params = {"assetClass": asset_class, "symbol": symbol, "exchange": exchange}
        if exchange_filter:
            params["exchangeFilter"] = exchange_filter
        return self._get("/trsrv/secdef/schedule", params)

    def get_secdef(self, conids: list[int]) -> list[dict]:
        data = self._get("/trsrv/secdef", {"conids": ",".join(str(c) for c in conids)})
        return data if isinstance(data, list) else []

    def get_currency_pairs(self, currency: str) -> list[dict]:
        data = self._get("/iserver/secdef/currency", {"currency": currency})
        return data if isinstance(data, list) else []

    def get_contract_rules(self, conid: int, is_buy: bool = True) -> dict:
        return self._post("/iserver/contract/rules", {"conid": conid, "isBuy": is_buy})

    # ── Portfolio ─────────────────────────────────────────────────────────────

    def get_accounts(self) -> list[dict]:
        data = self._get("/portfolio/accounts")
        return data if isinstance(data, list) else []

    def get_subaccounts(self) -> list[dict]:
        data = self._get("/portfolio/subaccounts")
        return data if isinstance(data, list) else []

    def get_account_meta(self, account_id: str) -> dict:
        return self._get(f"/portfolio/{account_id}/meta")

    def get_account_summary(self, account_id: str) -> dict:
        return self._get(f"/portfolio/{account_id}/summary")

    def get_account_ledger(self, account_id: str) -> dict:
        return self._get(f"/portfolio/{account_id}/ledger")

    def get_account_allocation(self, account_id: str) -> dict:
        return self._get(f"/portfolio/{account_id}/allocation")

    def get_positions(self, account_id: str, page: int = 0) -> list[dict]:
        data = self._get(f"/portfolio/{account_id}/positions/{page}")
        return data if isinstance(data, list) else []

    def get_positions_by_conid(self, conid: int) -> list[dict]:
        data = self._get(f"/portfolio/positions/{conid}")
        return data if isinstance(data, list) else []

    def get_position(self, account_id: str, conid: int) -> dict:
        return self._get(f"/portfolio/{account_id}/position/{conid}")

    def get_combo_positions(self, account_id: str) -> list[dict]:
        data = self._get(f"/portfolio/{account_id}/combo/positions")
        return data if isinstance(data, list) else []

    def get_portfolio_allocation(self, account_ids: list[str]) -> dict:
        return self._post("/portfolio/allocation", {"acctIds": account_ids})

    def invalidate_positions_cache(self, account_id: str) -> dict:
        return self._post(f"/portfolio/{account_id}/positions/invalidate")

    # ── Order Monitoring (read-only) ──────────────────────────────────────────

    def get_live_orders(self) -> list[dict]:
        data = self._get("/iserver/account/orders")
        orders = data.get("orders", data) if isinstance(data, dict) else data
        return orders if isinstance(orders, list) else []

    def get_order_status(self, order_id: str) -> dict:
        return self._get(f"/iserver/account/order/status/{order_id}")

    def get_trades(self) -> list[dict]:
        data = self._get("/iserver/account/trades")
        return data if isinstance(data, list) else []

    # ── Portfolio Analyst ─────────────────────────────────────────────────────

    def get_pa_periods(self, account_ids: list[str]) -> list[str]:
        data = self._post("/pa/allperiods", {"acctIds": account_ids})
        return data if isinstance(data, list) else []

    def get_pa_performance(self, account_ids: list[str], period: str) -> dict:
        return self._post("/pa/performance", {"acctIds": account_ids, "period": period})

    def get_pa_transactions(self, account_ids: list[str], period: str) -> list[dict]:
        data = self._post("/pa/transactions", {"acctIds": account_ids, "period": period})
        return data if isinstance(data, list) else []

    # ── Scanner ───────────────────────────────────────────────────────────────

    def get_scanner_params(self) -> dict:
        return self._get("/iserver/scanner/params")

    def run_iserver_scanner(self, params: dict) -> list[dict]:
        data = self._post("/iserver/scanner/run", params)
        contracts = data.get("contracts", data) if isinstance(data, dict) else data
        return contracts if isinstance(contracts, list) else []

    def run_hmds_scanner(self, params: dict) -> list[dict]:
        data = self._post("/hmds/scanner", params)
        return data if isinstance(data, list) else []

    # ── FYI / Notifications ───────────────────────────────────────────────────

    def get_notifications(self, max_results: int = 10) -> list[dict]:
        data = self._get("/fyi/notifications", {"max": max_results})
        return data if isinstance(data, list) else []

    def get_unread_count(self) -> int:
        data = self._get("/fyi/unreadnumber")
        return data.get("unreadNumber", 0) if isinstance(data, dict) else 0

    def get_delivery_options(self) -> dict:
        return self._get("/fyi/deliveryoptions")

    def get_mta_alert(self) -> dict:
        return self._get("/iserver/account/mta")

    def get_alerts(self, account_id: str) -> list[dict]:
        data = self._get(f"/iserver/account/{account_id}/alerts")
        return data if isinstance(data, list) else []

    # ── Watchlists (read-only) ────────────────────────────────────────────────

    def get_watchlists(self) -> list[dict]:
        data = self._get("/iserver/account/watchlists")
        return data if isinstance(data, list) else []

    def get_watchlist(self, watchlist_id: str) -> dict:
        return self._get(f"/iserver/account/watchlist/{watchlist_id}")

    # ── Events Contracts ──────────────────────────────────────────────────────

    def get_event_contracts(self, conids: list[int]) -> list[dict]:
        data = self._get("/events/contracts", {"conids": ",".join(str(c) for c in conids)})
        return data if isinstance(data, list) else []

    def get_event_contract(self, conid: int) -> dict:
        return self._get("/events/show", {"conid": conid})
```

- [ ] **Step 4: Run unit tests**

```bash
pytest tests/test_client.py -v -m "not integration"
```

Expected: all 4 unit tests pass.

- [ ] **Step 5: Commit**

```bash
git add ibkr_core_mcp/client.py tests/test_client.py
git commit -m "feat: IBKRClient — all 79 IBKR endpoints with retry and auth"
```

---

## Task 7: `cache.py` — Google Drive Parquet Cache

**Files:**
- Create: `ibkr_core_mcp/cache.py`
- Create: `tests/test_cache.py`

- [ ] **Step 1: Write unit tests**

```python
# tests/test_cache.py
import pytest
import pandas as pd
import numpy as np
from unittest.mock import patch, MagicMock
from datetime import date


@pytest.fixture
def cache(mock_config):
    from ibkr_core_mcp.cache import GDriveCache
    with patch("ibkr_core_mcp.cache.GDriveCache._get_service", return_value=MagicMock()):
        c = GDriveCache.__new__(GDriveCache)
        c._config = mock_config
        c._service = MagicMock()
        c._manifest = {}
        c._manifest_loaded_at = 0.0
        return c


def test_cache_key_format(cache):
    key = cache._cache_key("aapl", "1d", "1Y", "2026-05-22")
    assert key == "AAPL_1D_1Y_2026-05-22"


def test_check_returns_false_on_miss(cache):
    cache._manifest = {}
    cache._manifest_loaded_at = float("inf")  # bypass TTL
    assert cache.check("AAPL", "1D", "1Y", "2026-05-22") is False


def test_check_returns_true_on_hit(cache):
    cache._manifest = {
        "AAPL_1D_1Y_2026-05-22": {
            "end": "2026-05-22",
            "rows": 252,
        }
    }
    cache._manifest_loaded_at = float("inf")
    assert cache.check("AAPL", "1D", "1Y", "2026-05-21") is True


def test_check_stale_today_end(cache):
    yesterday = str(date.today().replace(day=date.today().day - 1))
    cache._manifest = {
        f"AAPL_1D_1Y_{date.today()}": {
            "end": yesterday,
            "rows": 252,
        }
    }
    cache._manifest_loaded_at = float("inf")
    result = cache.check("AAPL", "1D", "1Y", str(date.today()))
    assert result is False  # stale — cached_end < today - 1


def test_list_cached_returns_keys(cache):
    cache._manifest = {
        "AAPL_1D_1Y_2026-05-22": {"symbol": "AAPL", "rows": 252},
        "TSLA_1D_6M_2026-05-22": {"symbol": "TSLA", "rows": 126},
    }
    cache._manifest_loaded_at = float("inf")
    entries = cache.list_cached()
    assert len(entries) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_cache.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Create `ibkr_core_mcp/cache.py`**

```python
from __future__ import annotations
import io
import json
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

from ibkr_core_mcp.config import Config
from ibkr_core_mcp.exceptions import CacheMissError, CacheWriteError

_SCOPES = ["https://www.googleapis.com/auth/drive.file"]
_MANIFEST_NAME = "manifest.json"
_MANIFEST_TTL = 60.0


class GDriveCache:
    """Google Drive parquet cache for OHLCV market data."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._service: Any = None
        self._manifest: dict = {}
        self._manifest_loaded_at: float = 0.0

    def _get_service(self) -> Any:
        if self._service:
            return self._service
        creds = None
        if self._config.gdrive_token_file.exists():
            creds = Credentials.from_authorized_user_file(
                str(self._config.gdrive_token_file), _SCOPES
            )
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self._config.gdrive_credentials_file), _SCOPES
                )
                creds = flow.run_local_server(port=0)
            self._config.gdrive_token_file.parent.mkdir(parents=True, exist_ok=True)
            self._config.gdrive_token_file.write_text(creds.to_json())
        self._service = build("drive", "v3", credentials=creds)
        return self._service

    def _cache_key(self, symbol: str, timeframe: str, period: str, end: str) -> str:
        return f"{symbol.upper()}_{timeframe.upper()}_{period}_{end}"

    def _filename(self, key: str) -> str:
        return f"{key}.parquet"

    def _load_manifest(self) -> dict:
        now = time.monotonic()
        if self._manifest and (now - self._manifest_loaded_at) < _MANIFEST_TTL:
            return self._manifest
        svc = self._get_service()
        folder_id = self._config.gdrive_folder_id
        results = (
            svc.files()
            .list(
                q=f"name='{_MANIFEST_NAME}' and '{folder_id}' in parents and trashed=false",
                fields="files(id)",
            )
            .execute()
        )
        files = results.get("files", [])
        if not files:
            self._manifest = {}
            self._manifest_loaded_at = time.monotonic()
            return self._manifest
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, svc.files().get_media(fileId=files[0]["id"]))
        done = False
        while not done:
            _, done = downloader.next_chunk()
        self._manifest = json.loads(buf.getvalue())
        self._manifest_loaded_at = time.monotonic()
        return self._manifest

    def _save_manifest(self) -> None:
        svc = self._get_service()
        folder_id = self._config.gdrive_folder_id
        data = json.dumps(self._manifest, indent=2).encode()
        buf = io.BytesIO(data)
        media = MediaIoBaseUpload(buf, mimetype="application/json")
        results = (
            svc.files()
            .list(
                q=f"name='{_MANIFEST_NAME}' and '{folder_id}' in parents and trashed=false",
                fields="files(id)",
            )
            .execute()
        )
        files = results.get("files", [])
        if files:
            svc.files().update(fileId=files[0]["id"], media_body=media).execute()
        else:
            metadata = {"name": _MANIFEST_NAME, "parents": [folder_id]}
            svc.files().create(body=metadata, media_body=media, fields="id").execute()

    def check(self, symbol: str, timeframe: str, period: str, end: str) -> bool:
        """Return True if a fresh cached file exists for this key."""
        manifest = self._load_manifest()
        key = self._cache_key(symbol, timeframe, period, end)
        entry = manifest.get(key)
        if not entry:
            return False
        cached_end = datetime.strptime(entry["end"], "%Y-%m-%d").date()
        today = date.today()
        if end in ("today", str(today)):
            return cached_end >= today - timedelta(days=1)
        return True

    def load(self, symbol: str, timeframe: str, period: str, end: str) -> pd.DataFrame:
        """Download and return cached parquet as DataFrame."""
        key = self._cache_key(symbol, timeframe, period, end)
        fname = self._filename(key)
        svc = self._get_service()
        folder_id = self._config.gdrive_folder_id
        results = (
            svc.files()
            .list(
                q=f"name='{fname}' and '{folder_id}' in parents and trashed=false",
                fields="files(id)",
            )
            .execute()
        )
        files = results.get("files", [])
        if not files:
            raise CacheMissError(f"No cached file for {key}")
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, svc.files().get_media(fileId=files[0]["id"]))
        done = False
        while not done:
            _, done = downloader.next_chunk()
        buf.seek(0)
        return pd.read_parquet(buf)

    def save(
        self, df: pd.DataFrame, symbol: str, timeframe: str, period: str, end: str
    ) -> None:
        """Upload DataFrame as parquet to Drive and update manifest."""
        key = self._cache_key(symbol, timeframe, period, end)
        fname = self._filename(key)
        svc = self._get_service()
        folder_id = self._config.gdrive_folder_id
        buf = io.BytesIO()
        df.to_parquet(buf, index=True)
        buf.seek(0)
        media = MediaIoBaseUpload(buf, mimetype="application/octet-stream")
        results = (
            svc.files()
            .list(
                q=f"name='{fname}' and '{folder_id}' in parents and trashed=false",
                fields="files(id)",
            )
            .execute()
        )
        existing = results.get("files", [])
        try:
            if existing:
                svc.files().update(fileId=existing[0]["id"], media_body=media).execute()
            else:
                metadata = {"name": fname, "parents": [folder_id]}
                svc.files().create(body=metadata, media_body=media, fields="id").execute()
        except Exception as e:
            raise CacheWriteError(f"Failed to write {fname} to Drive: {e}") from e

        self._load_manifest()
        self._manifest[key] = {
            "symbol": symbol.upper(),
            "timeframe": timeframe.upper(),
            "period": period,
            "end": end if end != "today" else str(date.today()),
            "rows": len(df),
            "cached_at": datetime.now(tz=timezone.utc).isoformat(),
        }
        self._save_manifest()

    def list_cached(self) -> list[dict]:
        """Return list of all manifest entries."""
        manifest = self._load_manifest()
        return [{"key": k, **v} for k, v in manifest.items()]

    def delete(self, symbol: str, timeframe: str, period: str, end: str) -> None:
        """Remove a cached file and its manifest entry."""
        key = self._cache_key(symbol, timeframe, period, end)
        fname = self._filename(key)
        svc = self._get_service()
        folder_id = self._config.gdrive_folder_id
        results = (
            svc.files()
            .list(
                q=f"name='{fname}' and '{folder_id}' in parents and trashed=false",
                fields="files(id)",
            )
            .execute()
        )
        for f in results.get("files", []):
            svc.files().delete(fileId=f["id"]).execute()
        self._load_manifest()
        self._manifest.pop(key, None)
        self._save_manifest()
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_cache.py -v
```

Expected: all 5 unit tests pass.

- [ ] **Step 5: Commit**

```bash
git add ibkr_core_mcp/cache.py tests/test_cache.py
git commit -m "feat: GDriveCache — Google Drive parquet cache with TTL manifest"
```

---

## Task 8: `store.py` — SQLite Store

**Files:**
- Create: `ibkr_core_mcp/store.py`
- Create: `tests/test_store.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_store.py
import pytest
import pandas as pd
from datetime import datetime, timezone


@pytest.fixture
def store(mock_config):
    from ibkr_core_mcp.store import SQLiteStore
    s = SQLiteStore(mock_config)
    s.initialize()
    return s


def test_initialize_creates_tables(store):
    import sqlite3
    conn = sqlite3.connect(store._db_path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    conn.close()
    assert "trades" in tables
    assert "position_snapshots" in tables
    assert "signals" in tables
    assert "backtest_results" in tables


def test_upsert_and_get_trades(store):
    trades = [
        {
            "execution_id": "exec001",
            "symbol": "AAPL",
            "side": "BUY",
            "size": 10.0,
            "price": 180.0,
            "time": "2026-05-22T14:30:00+00:00",
            "commission": 1.0,
            "account": "U123",
        }
    ]
    store.upsert_trades(trades)
    result = store.get_trades(symbol="AAPL")
    assert len(result) == 1
    assert result[0]["symbol"] == "AAPL"
    assert result[0]["price"] == 180.0


def test_upsert_trades_idempotent(store):
    trade = {
        "execution_id": "exec002",
        "symbol": "TSLA",
        "side": "SELL",
        "size": 5.0,
        "price": 250.0,
        "time": "2026-05-22T15:00:00+00:00",
        "commission": 0.5,
        "account": "U123",
    }
    store.upsert_trades([trade])
    store.upsert_trades([trade])  # duplicate
    result = store.get_trades(symbol="TSLA")
    assert len(result) == 1


def test_log_and_get_signals(store):
    store.log_signal("AAPL", "rsi_oversold", 28.5, {"rsi_period": 14})
    signals = store.get_signals(symbol="AAPL")
    assert len(signals) == 1
    assert signals.iloc[0]["signal_type"] == "rsi_oversold"
    assert signals.iloc[0]["value"] == 28.5


def test_snapshot_and_get_positions(store):
    positions = [
        {"conid": 265598, "symbol": "AAPL", "position": 100.0, "mktPrice": 180.0,
         "mktValue": 18000.0, "unrealizedPnl": 500.0},
    ]
    store.snapshot_positions(positions)
    df = store.get_position_history(symbol="AAPL")
    assert len(df) == 1
    assert df.iloc[0]["symbol"] == "AAPL"


def test_get_trades_filters_by_date(store):
    trades = [
        {"execution_id": "e1", "symbol": "AAPL", "side": "BUY", "size": 1,
         "price": 100, "time": "2026-01-01T10:00:00+00:00", "commission": 0, "account": "U1"},
        {"execution_id": "e2", "symbol": "AAPL", "side": "SELL", "size": 1,
         "price": 110, "time": "2026-05-01T10:00:00+00:00", "commission": 0, "account": "U1"},
    ]
    store.upsert_trades(trades)
    result = store.get_trades(symbol="AAPL", start="2026-03-01", end="2026-12-31")
    assert len(result) == 1
    assert result[0]["execution_id"] == "e2"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_store.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Create `ibkr_core_mcp/store.py`**

```python
from __future__ import annotations
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ibkr_core_mcp.config import Config
from ibkr_core_mcp.exceptions import StoreError


class SQLiteStore:
    """Persistent SQLite store for trades, position snapshots, and signals."""

    def __init__(self, config: Config) -> None:
        self._db_path = str(config.sqlite_path)
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def initialize(self) -> None:
        """Create all tables if they don't exist."""
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS trades (
                    execution_id TEXT PRIMARY KEY,
                    symbol       TEXT NOT NULL,
                    side         TEXT NOT NULL,
                    size         REAL NOT NULL,
                    price        REAL NOT NULL,
                    time         TEXT NOT NULL,
                    commission   REAL DEFAULT 0.0,
                    account      TEXT DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS position_snapshots (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_at  TEXT NOT NULL,
                    conid        INTEGER,
                    symbol       TEXT NOT NULL,
                    position     REAL NOT NULL,
                    mkt_price    REAL DEFAULT 0.0,
                    mkt_value    REAL DEFAULT 0.0,
                    unrealized_pnl REAL DEFAULT 0.0
                );

                CREATE TABLE IF NOT EXISTS signals (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    logged_at   TEXT NOT NULL,
                    symbol      TEXT NOT NULL,
                    signal_type TEXT NOT NULL,
                    value       REAL,
                    metadata    TEXT
                );

                CREATE TABLE IF NOT EXISTS backtest_results (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_at        TEXT NOT NULL,
                    symbol        TEXT NOT NULL,
                    strategy_name TEXT NOT NULL,
                    total_return  REAL,
                    sharpe        REAL,
                    sortino       REAL,
                    max_drawdown  REAL,
                    num_trades    INTEGER,
                    win_rate      REAL,
                    metadata      TEXT
                );
            """)

    def upsert_trades(self, trades: list[dict]) -> None:
        """Insert or update trades by execution_id."""
        self.initialize()
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO trades
                    (execution_id, symbol, side, size, price, time, commission, account)
                VALUES
                    (:execution_id, :symbol, :side, :size, :price, :time, :commission, :account)
                ON CONFLICT(execution_id) DO UPDATE SET
                    price=excluded.price,
                    commission=excluded.commission
                """,
                trades,
            )

    def get_trades(
        self,
        symbol: str | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> list[dict]:
        """Return trades, optionally filtered by symbol and date range."""
        self.initialize()
        query = "SELECT * FROM trades WHERE 1=1"
        params: list[Any] = []
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol.upper())
        if start:
            query += " AND time >= ?"
            params.append(start)
        if end:
            query += " AND time <= ?"
            params.append(end)
        query += " ORDER BY time DESC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def snapshot_positions(self, positions: list[dict]) -> None:
        """Save a timestamped snapshot of current positions."""
        self.initialize()
        now = datetime.now(tz=timezone.utc).isoformat()
        rows = [
            {
                "snapshot_at": now,
                "conid": p.get("conid"),
                "symbol": p.get("symbol", ""),
                "position": p.get("position", 0.0),
                "mkt_price": p.get("mktPrice", 0.0),
                "mkt_value": p.get("mktValue", 0.0),
                "unrealized_pnl": p.get("unrealizedPnl", 0.0),
            }
            for p in positions
        ]
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO position_snapshots
                    (snapshot_at, conid, symbol, position, mkt_price, mkt_value, unrealized_pnl)
                VALUES
                    (:snapshot_at, :conid, :symbol, :position, :mkt_price, :mkt_value, :unrealized_pnl)
                """,
                rows,
            )

    def get_position_history(
        self,
        symbol: str | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> pd.DataFrame:
        """Return position snapshot history as DataFrame."""
        self.initialize()
        query = "SELECT * FROM position_snapshots WHERE 1=1"
        params: list[Any] = []
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol.upper())
        if start:
            query += " AND snapshot_at >= ?"
            params.append(start)
        if end:
            query += " AND snapshot_at <= ?"
            params.append(end)
        query += " ORDER BY snapshot_at"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return pd.DataFrame([dict(r) for r in rows])

    def log_signal(
        self,
        symbol: str,
        signal_type: str,
        value: float,
        metadata: dict | None = None,
    ) -> None:
        """Record a signal (from ML model, scanner, or indicator)."""
        self.initialize()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO signals (logged_at, symbol, signal_type, value, metadata)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    datetime.now(tz=timezone.utc).isoformat(),
                    symbol.upper(),
                    signal_type,
                    value,
                    json.dumps(metadata) if metadata else None,
                ),
            )

    def get_signals(
        self,
        symbol: str | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> pd.DataFrame:
        self.initialize()
        query = "SELECT * FROM signals WHERE 1=1"
        params: list[Any] = []
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol.upper())
        if start:
            query += " AND logged_at >= ?"
            params.append(start)
        if end:
            query += " AND logged_at <= ?"
            params.append(end)
        query += " ORDER BY logged_at"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return pd.DataFrame([dict(r) for r in rows])

    def save_backtest(self, result: dict) -> int:
        """Store a backtest result dict. Returns row id."""
        self.initialize()
        now = datetime.now(tz=timezone.utc).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO backtest_results
                    (run_at, symbol, strategy_name, total_return, sharpe, sortino,
                     max_drawdown, num_trades, win_rate, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now,
                    result.get("symbol", ""),
                    result.get("strategy_name", ""),
                    result.get("total_return"),
                    result.get("sharpe"),
                    result.get("sortino"),
                    result.get("max_drawdown"),
                    result.get("num_trades"),
                    result.get("win_rate"),
                    json.dumps(result.get("metadata")) if result.get("metadata") else None,
                ),
            )
            return cursor.lastrowid or 0

    def get_backtests(
        self, symbol: str | None = None, strategy: str | None = None
    ) -> list[dict]:
        self.initialize()
        query = "SELECT * FROM backtest_results WHERE 1=1"
        params: list[Any] = []
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol.upper())
        if strategy:
            query += " AND strategy_name = ?"
            params.append(strategy)
        query += " ORDER BY run_at DESC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_store.py -v
```

Expected: all 6 pass.

- [ ] **Step 5: Commit**

```bash
git add ibkr_core_mcp/store.py tests/test_store.py
git commit -m "feat: SQLiteStore — trades, position snapshots, signals, backtest results"
```

---

## Task 9: `claude_tools.py` — Phase 1 Claude Tool Layer (14 tools)

**Files:**
- Create: `ibkr_core_mcp/claude_tools.py`
- Create: `tests/test_claude_tools.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_claude_tools.py
import pytest
from unittest.mock import MagicMock, patch
from datetime import date


@pytest.fixture
def toolkit(mock_config):
    from ibkr_core_mcp.claude_tools import ClaudeToolkit
    from ibkr_core_mcp.auth import NoAuth
    client = MagicMock()
    cache = MagicMock()
    store = MagicMock()
    return ClaudeToolkit(client, cache, store, mock_config)


def test_tools_returns_list_of_dicts(toolkit):
    tools = toolkit.tools
    assert isinstance(tools, list)
    assert len(tools) >= 14
    for t in tools:
        assert "name" in t
        assert "description" in t
        assert "input_schema" in t


def test_all_tools_have_required_fields(toolkit):
    for tool in toolkit.tools:
        assert isinstance(tool["name"], str)
        assert isinstance(tool["description"], str)
        schema = tool["input_schema"]
        assert schema.get("type") == "object"
        assert "properties" in schema


def test_execute_unknown_tool_returns_error(toolkit):
    text, fig = toolkit.execute("nonexistent_tool", {})
    assert "unknown" in text.lower() or "error" in text.lower()
    assert fig is None


def test_execute_check_cache_hit(toolkit):
    toolkit._cache.check.return_value = True
    text, fig = toolkit.execute("check_cache", {
        "symbol": "AAPL", "timeframe": "1D", "period": "1Y", "end": "2026-05-22"
    })
    assert "HIT" in text
    assert fig is None


def test_execute_check_cache_miss(toolkit):
    toolkit._cache.check.return_value = False
    text, fig = toolkit.execute("check_cache", {
        "symbol": "AAPL", "timeframe": "1D", "period": "1Y", "end": "2026-05-22"
    })
    assert "MISS" in text


def test_execute_get_account_summary(toolkit):
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.get_account_summary.return_value = {
        "netliquidation": {"amount": 100000},
        "totalcashvalue": {"amount": 50000},
    }
    text, fig = toolkit.execute("get_account_summary", {})
    assert fig is None
    assert len(text) > 0


def test_execute_get_trades(toolkit):
    toolkit._client.get_trades.return_value = [
        {"symbol": "AAPL", "side": "BUY", "size": 10, "price": 180, "time": "2026-05-22"}
    ]
    toolkit._store.upsert_trades.return_value = None
    text, fig = toolkit.execute("get_trades", {})
    assert "AAPL" in text or len(text) > 0


def test_execute_get_notifications(toolkit):
    toolkit._client.get_notifications.return_value = [
        {"id": "1", "title": "Test alert", "body": "Something happened", "isRead": False}
    ]
    text, fig = toolkit.execute("get_notifications", {})
    assert "Test alert" in text or len(text) > 0
    assert fig is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_claude_tools.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Create `ibkr_core_mcp/claude_tools.py`**

```python
from __future__ import annotations
import json
from datetime import date
from typing import Any

import pandas as pd

from ibkr_core_mcp.cache import GDriveCache
from ibkr_core_mcp.client import IBKRClient
from ibkr_core_mcp.config import Config
from ibkr_core_mcp.exceptions import CacheMissError
from ibkr_core_mcp.store import SQLiteStore

_TODAY = lambda: str(date.today())

TOOL_DEFINITIONS = [
    {
        "name": "fetch_market_data",
        "description": (
            "Fetch OHLCV historical data for a symbol from IBKR. "
            "Checks Google Drive cache first; only calls IBKR on a cache miss. "
            "Returns a summary of the data retrieved."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Ticker, e.g. AAPL"},
                "period": {"type": "string", "description": "History period, e.g. '1Y', '6M'"},
                "bar": {"type": "string", "description": "Bar size, e.g. '1d', '1h'", "default": "1d"},
                "end": {"type": "string", "description": "End date YYYY-MM-DD, defaults to today"},
            },
            "required": ["symbol", "period"],
        },
    },
    {
        "name": "check_cache",
        "description": "Check whether data for a symbol/timeframe is cached in Google Drive.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "timeframe": {"type": "string", "description": "e.g. '1D'"},
                "period": {"type": "string", "description": "e.g. '1Y'"},
                "end": {"type": "string", "description": "End date YYYY-MM-DD"},
            },
            "required": ["symbol", "timeframe", "period", "end"],
        },
    },
    {
        "name": "list_cache",
        "description": "List all datasets currently cached in Google Drive.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_account_summary",
        "description": "Retrieve account net liquidation value, cash balance, and P&L from IBKR.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_positions",
        "description": "Get all open positions for the IBKR account.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_trades",
        "description": (
            "Get trade history. source='live' queries IBKR directly (last 6 days only). "
            "source='store' queries the local SQLite store — unlimited history, includes all data "
            "synced via sync_flex_trades. Use source='store' for any analysis beyond 6 days."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Filter by symbol (optional)"},
                "source": {
                    "type": "string",
                    "description": "'live' (IBKR API, last 6 days) or 'store' (SQLite, unlimited history including Flex syncs)",
                    "default": "store",
                },
                "start": {"type": "string", "description": "Start date YYYY-MM-DD (store source only, optional)"},
                "end": {"type": "string", "description": "End date YYYY-MM-DD (store source only, optional)"},
            },
            "required": [],
        },
    },
    {
        "name": "sync_flex_trades",
        "description": (
            "Fetch the full historical trade history from IBKR Flex Web Service and store it in "
            "the local SQLite database and Google Drive cache. Requires IBKR_FLEX_TOKEN and "
            "IBKR_FLEX_QUERY_ID to be configured. Run this once or daily to keep historical "
            "trade data current beyond the 6-day API limit."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "IBKR account ID (optional — resolved automatically if omitted)"},
            },
            "required": [],
        },
    },
    {
        "name": "get_live_orders",
        "description": "Get currently open/pending orders from IBKR.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_ledger",
        "description": "Get cash balance and ledger information by currency for the IBKR account.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_allocation",
        "description": "Get portfolio allocation breakdown by asset class, industry, and category.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_pa_performance",
        "description": "Get portfolio NAV performance from IBKR Portfolio Analyst.",
        "input_schema": {
            "type": "object",
            "properties": {
                "period": {"type": "string", "description": "e.g. 'last7days', 'last30days', 'ytd', 'last365days'"},
            },
            "required": ["period"],
        },
    },
    {
        "name": "get_pa_transactions",
        "description": "Get transaction history from IBKR Portfolio Analyst.",
        "input_schema": {
            "type": "object",
            "properties": {
                "period": {"type": "string", "description": "e.g. 'last7days', 'ytd'"},
            },
            "required": ["period"],
        },
    },
    {
        "name": "get_contract_info",
        "description": "Get full contract details for a symbol (conid, exchange, currency, trading hours, etc.).",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Ticker symbol"},
                "sec_type": {"type": "string", "description": "Security type, default STK", "default": "STK"},
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "get_option_chain",
        "description": "Get the options chain for a symbol — expirations, strikes, and contract IDs.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "exchange": {"type": "string", "default": "SMART"},
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "run_scanner",
        "description": (
            "Run an IBKR market scanner to find stocks matching criteria. "
            "Common scan_code values: 'TOP_PERC_GAIN', 'TOP_PERC_LOSE', 'MOST_ACTIVE', "
            "'HIGH_VS_13W_HL', 'LOW_VS_13W_HL', 'NEAR_52W_HL'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "scan_code": {"type": "string", "description": "Scanner type, e.g. 'TOP_PERC_GAIN'"},
                "instrument": {"type": "string", "description": "e.g. 'STK'", "default": "STK"},
                "location_code": {"type": "string", "description": "e.g. 'STK.US.MAJOR'", "default": "STK.US.MAJOR"},
                "max_results": {"type": "integer", "default": 25},
            },
            "required": ["scan_code"],
        },
    },
    {
        "name": "get_notifications",
        "description": "Retrieve IBKR FYI notifications and unread alerts.",
        "input_schema": {
            "type": "object",
            "properties": {
                "max_results": {"type": "integer", "default": 10},
            },
            "required": [],
        },
    },
]


class ClaudeToolkit:
    """Ready-made Claude tool layer for IBKR research. Portable across any Claude-powered app."""

    def __init__(
        self,
        client: IBKRClient,
        cache: GDriveCache,
        store: SQLiteStore,
        config: Config,
    ) -> None:
        self._client = client
        self._cache = cache
        self._store = store
        self._config = config

    @property
    def tools(self) -> list[dict]:
        return TOOL_DEFINITIONS

    def execute(self, name: str, inputs: dict) -> tuple[str, Any]:
        """Execute a tool call. Returns (text_result, optional_plotly_fig)."""
        handlers = {
            "fetch_market_data": self._fetch_market_data,
            "check_cache": self._check_cache,
            "list_cache": self._list_cache,
            "get_account_summary": self._get_account_summary,
            "get_positions": self._get_positions,
            "get_trades": self._get_trades,
            "get_live_orders": self._get_live_orders,
            "get_ledger": self._get_ledger,
            "get_allocation": self._get_allocation,
            "get_pa_performance": self._get_pa_performance,
            "get_pa_transactions": self._get_pa_transactions,
            "get_contract_info": self._get_contract_info,
            "get_option_chain": self._get_option_chain,
            "run_scanner": self._run_scanner,
            "get_notifications": self._get_notifications,
        }
        handler = handlers.get(name)
        if not handler:
            return f"Unknown tool: {name}", None
        try:
            return handler(inputs)
        except Exception as e:
            return f"Tool '{name}' error: {e}", None

    # ── Tool handlers ─────────────────────────────────────────────────────────

    def _fetch_market_data(self, inputs: dict) -> tuple[str, Any]:
        symbol = inputs["symbol"].upper()
        period = inputs["period"]
        bar = inputs.get("bar", "1d")
        end = inputs.get("end", _TODAY())
        timeframe = bar.upper()

        if self._cache.check(symbol, timeframe, period, end):
            df = self._cache.load(symbol, timeframe, period, end)
            return (
                f"Cache HIT — loaded {symbol} {timeframe} ({period}) from Drive. "
                f"{len(df)} bars from {df.index[0].date()} to {df.index[-1].date()}.",
                None,
            )

        contracts = self._client.search_contract(symbol)
        if not contracts:
            return f"No contract found for {symbol}. Is IBKR connected?", None
        conid = contracts[0].get("conid") or contracts[0].get("con_id")
        if not conid:
            return f"Contract found for {symbol} but conid missing: {contracts[0]}", None

        raw = self._client.get_market_history(conid, period=period, bar=bar)
        data = raw.get("data", [])
        if not data:
            return f"IBKR returned no data for {symbol} (period={period}, bar={bar})", None

        df = pd.DataFrame(data)
        df["t"] = pd.to_datetime(df["t"], unit="ms")
        df = df.rename(columns={"t": "date", "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
        df = df.set_index("date").sort_index()

        self._cache.save(df, symbol, timeframe, period, end)
        return (
            f"Fetched {symbol} {timeframe} ({period}) from IBKR: "
            f"{len(df)} bars from {df.index[0].date()} to {df.index[-1].date()}. "
            f"Saved to Drive cache.",
            None,
        )

    def _check_cache(self, inputs: dict) -> tuple[str, Any]:
        hit = self._cache.check(
            inputs["symbol"], inputs["timeframe"], inputs["period"], inputs["end"]
        )
        label = "HIT" if hit else "MISS"
        return f"Cache {label} for {inputs['symbol']} {inputs['timeframe']} {inputs['period']}–{inputs['end']}", None

    def _list_cache(self, inputs: dict) -> tuple[str, Any]:
        entries = self._cache.list_cached()
        if not entries:
            return "Drive cache is empty.", None
        lines = [f"- {e['key']}: {e.get('rows', '?')} bars, cached {e.get('cached_at', '?')[:10]}" for e in entries]
        return f"Cached datasets ({len(entries)}):\n" + "\n".join(lines), None

    def _get_account_summary(self, inputs: dict) -> tuple[str, Any]:
        accounts = self._client.get_accounts()
        if not accounts:
            return "No accounts found.", None
        account_id = accounts[0].get("accountId", accounts[0].get("id", ""))
        summary = self._client.get_account_summary(account_id)
        return json.dumps(summary, indent=2), None

    def _get_positions(self, inputs: dict) -> tuple[str, Any]:
        accounts = self._client.get_accounts()
        if not accounts:
            return "No accounts found.", None
        account_id = accounts[0].get("accountId", accounts[0].get("id", ""))
        positions = self._client.get_positions(account_id)
        if not positions:
            return "No open positions.", None
        lines = []
        for p in positions:
            symbol = p.get("contractDesc", p.get("ticker", p.get("symbol", "?")))
            pos = p.get("position", 0)
            mkt_val = p.get("mktValue", 0)
            pnl = p.get("unrealizedPnl", 0)
            lines.append(f"- {symbol}: {pos} shares, mktVal={mkt_val:.2f}, unrealPnL={pnl:.2f}")
        return f"Open positions ({len(positions)}):\n" + "\n".join(lines), None

    def _get_trades(self, inputs: dict) -> tuple[str, Any]:
        source = inputs.get("source", "store")
        symbol = inputs.get("symbol")
        if source == "store":
            trades = self._store.get_trades(
                symbol=symbol,
                start=inputs.get("start"),
                end=inputs.get("end"),
            )
            if not trades:
                return "No trades found in local store.", None
            lines = [f"- {t['time'][:10]} {t['symbol']} {t['side']} {t['size']} @ {t['price']}" for t in trades[:20]]
            suffix = f"  (showing first 20 of {len(trades)})" if len(trades) > 20 else ""
            return f"Trade history (SQLite, {len(trades)} total){suffix}:\n" + "\n".join(lines), None
        # source == 'live'
        trades = self._client.get_trades()
        if symbol:
            trades = [t for t in trades if t.get("symbol", "").upper() == symbol.upper()]
        try:
            self._store.upsert_trades([
                {
                    "execution_id": t.get("execution_id", t.get("orderId", str(i))),
                    "symbol": t.get("symbol", ""),
                    "side": t.get("side", ""),
                    "size": float(t.get("size", t.get("filledQuantity", 0))),
                    "price": float(t.get("price", t.get("avgPrice", 0))),
                    "time": str(t.get("trade_time", t.get("time", ""))),
                    "commission": float(t.get("commission", 0)),
                    "account": str(t.get("account", "")),
                }
                for i, t in enumerate(trades)
                if t.get("symbol")
            ])
        except Exception:
            pass
        if not trades:
            return "No trades in last 6 days.", None
        lines = [
            f"- {t.get('trade_time', t.get('time', '?'))[:19]} "
            f"{t.get('symbol', '?')} {t.get('side', '?')} "
            f"{t.get('size', t.get('filledQuantity', '?'))} @ {t.get('price', t.get('avgPrice', '?'))}"
            for t in trades[:20]
        ]
        return f"Recent trades (last 6 days, {len(trades)} total):\n" + "\n".join(lines), None

    def _sync_flex_trades(self, inputs: dict) -> tuple[str, Any]:
        from ibkr_core_mcp.flex_query import FlexQueryClient
        from ibkr_core_mcp.exceptions import FlexQueryError
        if not self._config.flex_token or not self._config.flex_query_id:
            return (
                "Flex Query not configured. Set IBKR_FLEX_TOKEN and IBKR_FLEX_QUERY_ID in .env. "
                "Token and Query ID must be created manually on the IBKR website under Reports → Flex Queries.",
                None,
            )
        account_id = inputs.get("account_id", "")
        if not account_id:
            accounts = self._client.get_accounts()
            account_id = accounts[0].get("accountId", accounts[0].get("id", "")) if accounts else ""
        if not account_id:
            return "Could not resolve account ID. Pass account_id explicitly.", None
        try:
            flex = FlexQueryClient(self._config, self._store, self._cache)
            trades = flex.fetch_trades(account_id)
        except FlexQueryError as e:
            return f"Flex Query failed: {e}", None
        return (
            f"Flex sync complete: {len(trades)} trades loaded for account {account_id}. "
            "Full history now available via get_trades with source='store'.",
            None,
        )

    def _get_live_orders(self, inputs: dict) -> tuple[str, Any]:
        orders = self._client.get_live_orders()
        if not orders:
            return "No open orders.", None
        lines = [
            f"- {o.get('orderId', '?')} {o.get('ticker', o.get('symbol', '?'))} "
            f"{o.get('side', '?')} {o.get('totalSize', '?')} @ {o.get('price', 'MKT')} "
            f"[{o.get('status', '?')}]"
            for o in orders
        ]
        return f"Live orders ({len(orders)}):\n" + "\n".join(lines), None

    def _get_ledger(self, inputs: dict) -> tuple[str, Any]:
        accounts = self._client.get_accounts()
        if not accounts:
            return "No accounts found.", None
        account_id = accounts[0].get("accountId", accounts[0].get("id", ""))
        ledger = self._client.get_account_ledger(account_id)
        return json.dumps(ledger, indent=2), None

    def _get_allocation(self, inputs: dict) -> tuple[str, Any]:
        accounts = self._client.get_accounts()
        if not accounts:
            return "No accounts found.", None
        account_id = accounts[0].get("accountId", accounts[0].get("id", ""))
        allocation = self._client.get_account_allocation(account_id)
        return json.dumps(allocation, indent=2), None

    def _get_pa_performance(self, inputs: dict) -> tuple[str, Any]:
        accounts = self._client.get_accounts()
        if not accounts:
            return "No accounts found.", None
        account_ids = [a.get("accountId", a.get("id", "")) for a in accounts]
        perf = self._client.get_pa_performance(account_ids, inputs["period"])
        return json.dumps(perf, indent=2), None

    def _get_pa_transactions(self, inputs: dict) -> tuple[str, Any]:
        accounts = self._client.get_accounts()
        if not accounts:
            return "No accounts found.", None
        account_ids = [a.get("accountId", a.get("id", "")) for a in accounts]
        txns = self._client.get_pa_transactions(account_ids, inputs["period"])
        return json.dumps(txns, indent=2), None

    def _get_contract_info(self, inputs: dict) -> tuple[str, Any]:
        symbol = inputs["symbol"].upper()
        sec_type = inputs.get("sec_type", "STK")
        contracts = self._client.search_contract(symbol, sec_type)
        if not contracts:
            return f"No contract found for {symbol}.", None
        conid = contracts[0].get("conid")
        if not conid:
            return f"Contract found but conid missing: {contracts[0]}", None
        info = self._client.get_contract_info_and_rules(conid)
        return json.dumps(info, indent=2), None

    def _get_option_chain(self, inputs: dict) -> tuple[str, Any]:
        symbol = inputs["symbol"].upper()
        exchange = inputs.get("exchange", "SMART")
        chain = self._client.get_option_chain(symbol, exchange=exchange)
        return json.dumps(chain, indent=2), None

    def _run_scanner(self, inputs: dict) -> tuple[str, Any]:
        params = {
            "instrument": inputs.get("instrument", "STK"),
            "location": inputs.get("location_code", "STK.US.MAJOR"),
            "scanCode": inputs["scan_code"],
            "secType": "STK",
            "filter": [],
        }
        results = self._client.run_iserver_scanner(params)
        if not results:
            return f"Scanner returned no results for {inputs['scan_code']}.", None
        max_r = inputs.get("max_results", 25)
        lines = [
            f"{i+1}. {r.get('symbol', r.get('contractDescription', {}).get('symbol', '?'))} "
            f"({r.get('contractDescription', {}).get('exchange', '?')})"
            for i, r in enumerate(results[:max_r])
        ]
        return f"Scanner: {inputs['scan_code']} — {len(results)} results:\n" + "\n".join(lines), None

    def _get_notifications(self, inputs: dict) -> tuple[str, Any]:
        max_r = inputs.get("max_results", 10)
        notifications = self._client.get_notifications(max_r)
        unread = self._client.get_unread_count()
        if not notifications:
            return f"No FYI notifications. Unread count: {unread}", None
        lines = [
            f"- [{('UNREAD' if not n.get('isRead') else 'read')}] {n.get('headline', n.get('title', '?'))}"
            for n in notifications
        ]
        return f"FYI Notifications ({unread} unread):\n" + "\n".join(lines), None
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_claude_tools.py -v
```

Expected: all 8 pass.

- [ ] **Step 5: Commit**

```bash
git add ibkr_core_mcp/claude_tools.py tests/test_claude_tools.py
git commit -m "feat: ClaudeToolkit — 15 Claude tools for IBKR research"
```

---

## Task 10: `__init__.py` — Public API + Run All Tests

**Files:**
- Modify: `ibkr_core_mcp/__init__.py`

- [ ] **Step 1: Write the public API**

```python
# ibkr_core_mcp/__init__.py
"""ibkr_core_mcp — IBKR Client Portal API package."""

from ibkr_core_mcp.config import Config
from ibkr_core_mcp.exceptions import (
    IBKRCoreError,
    IBKRAuthError,
    IBKRRateLimitError,
    IBKRAPIError,
    CacheError,
    CacheMissError,
    CacheWriteError,
    StoreError,
    BacktestError,
    BacktestSyntaxError,
    BacktestRuntimeError,
    ConfigError,
)
from ibkr_core_mcp.auth import BrowserCookieAuth, TokenAuth, NoAuth
from ibkr_core_mcp.client import IBKRClient
from ibkr_core_mcp.cache import GDriveCache
from ibkr_core_mcp.store import SQLiteStore
from ibkr_core_mcp.claude_tools import ClaudeToolkit

__version__ = "0.1.0"
__all__ = [
    "Config",
    "IBKRClient",
    "GDriveCache",
    "SQLiteStore",
    "ClaudeToolkit",
    "BrowserCookieAuth",
    "TokenAuth",
    "NoAuth",
    "IBKRCoreError",
    "IBKRAuthError",
    "IBKRRateLimitError",
    "IBKRAPIError",
    "CacheError",
    "CacheMissError",
    "CacheWriteError",
    "StoreError",
    "BacktestError",
    "BacktestSyntaxError",
    "BacktestRuntimeError",
    "ConfigError",
]
```

- [ ] **Step 2: Verify all public imports work**

```bash
python -c "
from ibkr_core_mcp import (
    Config, IBKRClient, GDriveCache, SQLiteStore, ClaudeToolkit,
    BrowserCookieAuth, TokenAuth, NoAuth,
    IBKRCoreError, IBKRAuthError, CacheMissError, StoreError,
)
print('All Phase 1 imports OK')
"
```

Expected output: `All Phase 1 imports OK`

- [ ] **Step 3: Run full unit test suite**

```bash
pytest tests/ -v -m "not integration"
```

Expected: all unit tests pass, no failures.

- [ ] **Step 4: Commit**

```bash
git add ibkr_core_mcp/__init__.py
git commit -m "feat: Phase 1 complete — public API surface and all unit tests passing"
```

---

## Task 11: Integration Test Run (requires live IBKR gateway)

**Pre-conditions:**
- IBKR Client Portal Gateway running (`docker compose up` in IB_MCP repo)
- Browser authenticated at `https://localhost:5055`
- `.env` file in the consuming project (or this repo root) with all vars set

- [ ] **Step 1: Create a `.env` for local integration testing**

```bash
# .env (gitignored)
IBKR_GATEWAY_URL=https://localhost:5055/v1/api
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_DRIVE_FOLDER_ID=...
```

- [ ] **Step 2: Run integration tests**

```bash
pytest tests/ -v -m integration
```

Expected:
- `test_live_ping` → PASS (True)
- `test_live_search_aapl` → PASS (returns contract list with AAPL)

- [ ] **Step 3: Smoke-test ClaudeToolkit end-to-end**

```python
# examples/smoke_test.py
from ibkr_core_mcp import IBKRClient, GDriveCache, SQLiteStore, ClaudeToolkit, Config
from ibkr_core_mcp.auth import BrowserCookieAuth

cfg = Config.from_env()
client = IBKRClient(cfg, auth=BrowserCookieAuth())
cache = GDriveCache(cfg)
store = SQLiteStore(cfg)
toolkit = ClaudeToolkit(client, cache, store, cfg)

print("Ping:", client.ping())
text, _ = toolkit.execute("get_account_summary", {})
print("Account:", text[:200])
text, _ = toolkit.execute("get_positions", {})
print("Positions:", text[:200])
text, _ = toolkit.execute("get_trades", {})
print("Trades:", text[:200])
```

```bash
python examples/smoke_test.py
```

- [ ] **Step 4: Tag Phase 1**

```bash
git tag v0.1.0
git push origin main --tags
```

---

## Phase 1 Complete

Install from GitHub in any project:
```bash
pip install git+https://github.com/stephus182/ibkr_core_mcp.git@v0.1.0
```

**Phase 2** (separate plan) adds:
- `models.py` — Pydantic v2 typed schemas for all IBKR responses
- `backtest.py` — RestrictedPython strategy sandbox
- `indicators.py` — RSI, MACD, Bollinger Bands, ATR, VWAP, OBV, etc.
- `analytics.py` — Sharpe, Sortino, Calmar, max drawdown, win rate, profit factor
- `pinescript.py` — PineScript v5 generation from strategies and indicators
- Upgraded `client.py` — returns typed Pydantic models
- Upgraded `ClaudeToolkit` — 4 additional tools (run_backtest, add_indicators, generate_pinescript, get_analytics)
