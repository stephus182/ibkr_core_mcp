# Windows Setup Guide

This guide covers installing and running `ibkr_core_mcp` on Windows. All read-only features work without modification. Order execution requires an additional step (see [Touch ID gate](#touch-id-gate-blocker)).

---

## Prerequisites

### 1. WSL2 (Windows Subsystem for Linux 2)

Required for Docker Desktop and recommended for a zsh terminal.

```powershell
# Run in PowerShell as Administrator
wsl --install
```

Reboot after installation. WSL2 installs Ubuntu by default.

To add zsh inside WSL2:
```bash
sudo apt update && sudo apt install -y zsh
chsh -s $(which zsh)
```

### 2. Docker Desktop

Download from [docker.com](https://www.docker.com/products/docker-desktop/). During installation, ensure **Use WSL2 instead of Hyper-V** is selected.

Verify:
```bash
docker --version
docker compose version
```

### 3. Python 3.11+

Download the installer from [python.org](https://www.python.org/downloads/). During installation:
- Check **Add python.exe to PATH**
- Check **Install pip**

Verify in PowerShell or WSL2:
```bash
python --version   # must be 3.11+
```

### 4. Chrome

Required for `BrowserCookieAuth` to read the IBKR gateway session cookie automatically. Install from [google.com/chrome](https://www.google.com/chrome/).

`browser_cookie3` also supports Edge and Firefox — pass `browser="edge"` or `browser="firefox"` to `BrowserCookieAuth()` if preferred.

---

## Install

```bash
# Editable dev install (run in PowerShell or WSL2 terminal)
pip install -e ".[dev]"

# Or from GitHub
pip install git+https://github.com/stephus182/ibkr_core_mcp.git
```

---

## Environment Variables

Create `.env` in your consuming project (same as macOS):

```
IBKR_GATEWAY_URL=https://localhost:5055/v1/api
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_DRIVE_FOLDER_ID=1abc...xyz
IBKR_SQLITE_PATH=~/.ibkr_core/store.db
GDRIVE_TOKEN_FILE=~/.ibkr_core/token.json
GDRIVE_CREDENTIALS_FILE=~/.ibkr_core/credentials.json
```

Python expands `~` correctly on Windows.

---

## IBKR Gateway

Same Docker workflow as macOS:

```bash
# From the IB_MCP repo
docker compose up
```

Open `https://localhost:5055` in Chrome, log in with IBKR credentials + 2FA. The package reads the session cookie automatically once authenticated.

---

## Google Drive — Portability Architecture

ClaudIA is designed to restore itself automatically on any machine. All persistent state lives under one Drive root folder (`GOOGLE_DRIVE_FOLDER_ID`):

```
<GOOGLE_DRIVE_FOLDER_ID>/
  context.md                 ← ClaudIA persona (cloud-authoritative)
  principles.md              ← trading rules (cloud-authoritative)
  db/
    claudia.db               ← conversation history (download at start, upload at end)
  market_data/
    *.parquet                ← OHLCV cache (shared across machines)
  account_data/
    flex_U*_*.xml            ← Flex XML archives (re-importable to SQLite)
    store.db                 ← trade store backup
```

**Minimum credentials for a new machine** (nothing else needed):

| Env var | What it unlocks |
|---|---|
| `GOOGLE_DRIVE_FOLDER_ID` | Root folder — all subfolders auto-created on first use |
| `GDRIVE_TOKEN_FILE` | OAuth2 token |
| `GDRIVE_CREDENTIALS_FILE` | OAuth2 credentials |
| `ANTHROPIC_API_KEY` | Claude API |
| `IBKR_FLEX_TOKEN` + `IBKR_FLEX_QUERY_ID` | Re-sync full trade history from IBKR |

`claudia.db` (conversation history) is downloaded automatically at session start. `store.db` rebuilds from the Flex XML archives in `account_data/` via `sync_flex_archive`.

**OAuth2 flow** is browser-based — works identically on Windows. On first use, a browser window opens for Google sign-in. The token is saved to `GDRIVE_TOKEN_FILE`.

---

## Touch ID Gate (Blocker)

`ibkr_core_mcp` requires **fingerprint authentication** before any order reaches IBKR (`place_order`, `modify_order`, `cancel_order`, `reply_order`). On macOS this uses Apple's `LocalAuthentication` framework.

On Windows, `LocalAuthentication` is unavailable. Calling any order write method raises:

```
HumanAuthError: Touch ID unavailable: pyobjc-framework-LocalAuthentication not installed
```

**All read-only operations are unaffected.** This includes:
- Market data, OHLCV history, snapshots
- Positions, account summary, ledger, PnL
- Live orders (read), order preview (`whatif`), trades
- Portfolio analytics, backtesting, PineScript generation
- Scanners, watchlists, alerts (read), FYI notifications
- All 22 MCP server tools

### Options for order execution on Windows

| Option | Effort | Security |
|---|---|---|
| **Windows Hello biometric** | Medium — requires custom `require_windows_hello()` using Windows Hello API | Equivalent to Touch ID |
| **Credential prompt** | Low — `pywin32` `CredUIPromptForCredentials` PIN/password dialog | Weaker (no biometric) |
| **Visual confirmation only** | Zero code change — remove biometric gate, keep tkinter dialog | Gate 2 only |

The tkinter visual confirmation dialog (Gate 2) works on Windows without any changes.

A Windows Hello implementation has not been built yet. Contributions welcome — see [CLAUDE.md](../CLAUDE.md) for contributor rules on the auth gate.

---

## What Works on Windows (Summary)

| Feature | Status |
|---|---|
| Market data & OHLCV history | ✅ |
| Google Drive parquet cache | ✅ |
| SQLite store | ✅ |
| Positions, PnL, account summary | ✅ |
| Portfolio analytics | ✅ |
| Technical indicators | ✅ |
| Backtesting (RestrictedPython sandbox) | ✅ |
| PineScript generation | ✅ |
| Flex Query historical trades | ✅ |
| Scanners | ✅ |
| MCP server (stdio + SSE) | ✅ |
| Live WebSocket quotes | ✅ |
| Price alerts | ✅ |
| Order placement / modify / cancel | ❌ Touch ID gate (see above) |
| `browser_cookie3` (Chrome/Edge/Firefox) | ✅ |
| tkinter order confirmation dialog | ✅ (Gate 2 only) |
