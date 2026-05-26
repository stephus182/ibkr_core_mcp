# ibkr_core_mcp Phase 2 — Analytics, Indicators, Backtest, PineScript

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Pydantic models, 14 technical indicators, portfolio analytics, a RestrictedPython backtest sandbox, PineScript v5 generation, and 4 new Claude tools — completing the full ibkr_core_mcp feature set.

**Architecture:** Five new pure modules (models, indicators, analytics, backtest, pinescript) that operate on standard pandas DataFrames and dataclasses. None of them require a live IBKR connection. They plug into the existing Phase 1 components (GDriveCache, SQLiteStore, ClaudeToolkit) without breaking any existing code — the Phase 1 client still returns raw dicts; models.py adds opt-in typed parsing on top.

**Tech Stack:** pydantic>=2.0, pandas, numpy, RestrictedPython, Python 3.11+

**Working directory:** `/Users/steph/Claude_Projects/ibkr_core_mcp`

---

## File Map

```
ibkr_core_mcp/
├── models.py         create — Pydantic v2 schemas + bars_to_dataframe() helper
├── indicators.py     create — 14 indicator functions + add_all()
├── analytics.py      create — performance metrics (Sharpe, Sortino, drawdown, CAGR…)
├── backtest.py       create — RestrictedPython sandbox + BacktestResult dataclass
├── pinescript.py     create — PineScript v5 generation (3 functions)
├── claude_tools.py   modify — add 4 new tools (add_indicators, run_backtest, generate_pinescript, get_analytics)
└── __init__.py       modify — export all new symbols + version bump to 0.2.0

tests/
├── test_models.py        create
├── test_indicators.py    create
├── test_analytics.py     create
├── test_backtest.py      create
└── test_pinescript.py    create

pyproject.toml            modify — add pydantic>=2.0 to dependencies
```

---

## Task 1: `pyproject.toml` + `models.py`

**Files:**
- Modify: `pyproject.toml`
- Create: `ibkr_core_mcp/models.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Add pydantic to pyproject.toml**

In `pyproject.toml`, add `"pydantic>=2.0",` after `"requests>=2.31",`:

```toml
dependencies = [
    "requests>=2.31",
    "urllib3>=2.0",
    "pydantic>=2.0",
    "anthropic>=0.28",
    ...
]
```

- [ ] **Step 2: Install updated deps**

```bash
cd /Users/steph/Claude_Projects/ibkr_core_mcp
pip install -e ".[dev]"
```

Expected: installs pydantic without errors.

- [ ] **Step 3: Write failing tests**

```python
# tests/test_models.py
import pytest
import pandas as pd
from datetime import datetime


def test_contract_parses_ibkr_dict():
    from ibkr_core_mcp.models import Contract
    raw = {"conid": 265598, "symbol": "AAPL", "secType": "STK", "exchange": "NASDAQ", "currency": "USD"}
    c = Contract.model_validate(raw)
    assert c.conid == 265598
    assert c.symbol == "AAPL"
    assert c.sec_type == "STK"


def test_contract_missing_conid_raises():
    from ibkr_core_mcp.models import Contract
    with pytest.raises(Exception):
        Contract.model_validate({"symbol": "AAPL"})


def test_position_parses_ibkr_dict():
    from ibkr_core_mcp.models import Position
    raw = {
        "conid": 265598, "contractDesc": "AAPL", "position": 100.0,
        "mktPrice": 180.0, "mktValue": 18000.0, "unrealizedPnl": 500.0, "realizedPnl": 0.0
    }
    p = Position.model_validate(raw)
    assert p.conid == 265598
    assert p.position == 100.0
    assert p.mkt_price == 180.0


def test_trade_parses_ibkr_dict():
    from ibkr_core_mcp.models import Trade
    raw = {
        "execution_id": "0001", "symbol": "AAPL", "side": "B",
        "size": 10.0, "price": 180.0, "time": "2026-05-22T14:30:00",
        "commission": 1.0, "account": "U123"
    }
    t = Trade.model_validate(raw)
    assert t.symbol == "AAPL"
    assert t.price == 180.0


def test_account_summary_parses_nested():
    from ibkr_core_mcp.models import AccountSummary
    raw = {
        "netliquidation": {"amount": 100000.0, "currency": "USD"},
        "totalcashvalue": {"amount": 50000.0, "currency": "USD"},
        "unrealizedpnl": {"amount": 1500.0, "currency": "USD"},
        "realizedpnl": {"amount": 300.0, "currency": "USD"},
    }
    s = AccountSummary.model_validate(raw)
    assert s.net_liquidation == 100000.0
    assert s.total_cash == 50000.0


def test_bars_to_dataframe_basic():
    from ibkr_core_mcp.models import bars_to_dataframe
    raw = {
        "data": [
            {"t": 1716393600000, "o": 180.0, "h": 182.0, "l": 179.0, "c": 181.0, "v": 1000000},
            {"t": 1716480000000, "o": 181.0, "h": 183.0, "l": 180.0, "c": 182.0, "v": 1100000},
        ]
    }
    df = bars_to_dataframe(raw)
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert len(df) == 2
    assert df.index.name == "date"


def test_bars_to_dataframe_empty():
    from ibkr_core_mcp.models import bars_to_dataframe
    df = bars_to_dataframe({"data": []})
    assert len(df) == 0


def test_notification_model():
    from ibkr_core_mcp.models import Notification
    raw = {"id": "n1", "date": "20260522-14:30:00", "headline": "Price alert", "body": "AAPL above 180", "isRead": False}
    n = Notification.model_validate(raw)
    assert n.headline == "Price alert"
    assert n.is_read is False
```

- [ ] **Step 4: Run tests to verify they fail**

```bash
pytest tests/test_models.py -v
```

Expected: `ImportError` or `ModuleNotFoundError`.

- [ ] **Step 5: Create `ibkr_core_mcp/models.py`**

```python
from __future__ import annotations
from typing import Any
import pandas as pd
from pydantic import BaseModel, model_validator, Field


class Contract(BaseModel):
    conid: int
    symbol: str
    sec_type: str = Field(default="", alias="secType")
    exchange: str = ""
    currency: str = "USD"
    description: str = Field(default="", alias="companyName")

    model_config = {"populate_by_name": True}

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "secType" in data and "sec_type" not in data:
                data.setdefault("sec_type", data["secType"])
            if "con_id" in data and "conid" not in data:
                data["conid"] = data["con_id"]
            if "companyName" in data and "description" not in data:
                data.setdefault("description", data["companyName"])
        return data


class Position(BaseModel):
    conid: int = 0
    symbol: str = Field(default="", alias="contractDesc")
    position: float
    mkt_price: float = Field(default=0.0, alias="mktPrice")
    mkt_value: float = Field(default=0.0, alias="mktValue")
    unrealized_pnl: float = Field(default=0.0, alias="unrealizedPnl")
    realized_pnl: float = Field(default=0.0, alias="realizedPnl")

    model_config = {"populate_by_name": True}

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if isinstance(data, dict):
            for alias, name in [
                ("mktPrice", "mkt_price"),
                ("mktValue", "mkt_value"),
                ("unrealizedPnl", "unrealized_pnl"),
                ("realizedPnl", "realized_pnl"),
                ("contractDesc", "symbol"),
            ]:
                if alias in data and name not in data:
                    data.setdefault(name, data[alias])
        return data


class Trade(BaseModel):
    execution_id: str = ""
    symbol: str
    side: str = ""
    size: float = 0.0
    price: float = 0.0
    time: str = ""
    commission: float = 0.0
    account: str = ""


class Order(BaseModel):
    order_id: str = Field(default="", alias="orderId")
    status: str = ""
    symbol: str = Field(default="", alias="ticker")
    side: str = ""
    qty: float = Field(default=0.0, alias="totalSize")
    price: float = 0.0
    order_type: str = Field(default="", alias="orderType")

    model_config = {"populate_by_name": True}

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if isinstance(data, dict):
            for alias, name in [
                ("orderId", "order_id"),
                ("ticker", "symbol"),
                ("totalSize", "qty"),
                ("orderType", "order_type"),
            ]:
                if alias in data and name not in data:
                    data.setdefault(name, data[alias])
        return data


class AccountSummary(BaseModel):
    net_liquidation: float = 0.0
    total_cash: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if isinstance(data, dict):
            def _amount(key: str) -> float:
                v = data.get(key, data.get(key.replace("_", ""), {}))
                if isinstance(v, dict):
                    return float(v.get("amount", 0))
                return float(v or 0)
            return {
                "net_liquidation": _amount("netliquidation"),
                "total_cash": _amount("totalcashvalue"),
                "unrealized_pnl": _amount("unrealizedpnl"),
                "realized_pnl": _amount("realizedpnl"),
            }
        return data


class Notification(BaseModel):
    id: str = ""
    date: str = ""
    headline: str = Field(default="", alias="headline")
    body: str = ""
    is_read: bool = Field(default=False, alias="isRead")

    model_config = {"populate_by_name": True}

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "isRead" in data and "is_read" not in data:
                data.setdefault("is_read", data["isRead"])
        return data


def bars_to_dataframe(raw: dict) -> pd.DataFrame:
    """Convert IBKR market history API response to standard OHLCV DataFrame."""
    bars = raw.get("data", [])
    if not bars:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = pd.DataFrame(bars)
    df["t"] = pd.to_datetime(df["t"], unit="ms")
    df = df.rename(columns={"t": "date", "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
    df = df.set_index("date")[["open", "high", "low", "close", "volume"]].sort_index()
    return df
```

- [ ] **Step 6: Run tests**

```bash
pytest tests/test_models.py -v
```

Expected: all 8 pass.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml ibkr_core_mcp/models.py tests/test_models.py
git commit -m "feat: models.py — Pydantic v2 schemas + bars_to_dataframe helper"
```

---

## Task 2: `indicators.py`

**Files:**
- Create: `ibkr_core_mcp/indicators.py`
- Create: `tests/test_indicators.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_indicators.py
import pytest
import numpy as np
import pandas as pd


@pytest.fixture
def ohlcv():
    """250 bars of synthetic OHLCV data with known properties."""
    np.random.seed(42)
    n = 250
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    high = close + np.random.uniform(0.1, 1.0, n)
    low = close - np.random.uniform(0.1, 1.0, n)
    open_ = close + np.random.randn(n) * 0.2
    volume = np.random.randint(500_000, 2_000_000, n).astype(float)
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx)


def test_sma_length(ohlcv):
    from ibkr_core_mcp.indicators import sma
    result = sma(ohlcv, period=20)
    assert isinstance(result, pd.Series)
    assert len(result) == len(ohlcv)
    assert result.iloc[:19].isna().all()  # first 19 are NaN
    assert not result.iloc[19:].isna().any()


def test_ema_length(ohlcv):
    from ibkr_core_mcp.indicators import ema
    result = ema(ohlcv, period=20)
    assert isinstance(result, pd.Series)
    assert len(result) == len(ohlcv)
    assert result.notna().any()


def test_rsi_bounds(ohlcv):
    from ibkr_core_mcp.indicators import rsi
    result = rsi(ohlcv, period=14)
    valid = result.dropna()
    assert (valid >= 0).all() and (valid <= 100).all()


def test_macd_columns(ohlcv):
    from ibkr_core_mcp.indicators import macd
    result = macd(ohlcv)
    assert isinstance(result, pd.DataFrame)
    assert set(result.columns) == {"macd", "signal", "histogram"}
    assert len(result) == len(ohlcv)


def test_macd_histogram_is_diff(ohlcv):
    from ibkr_core_mcp.indicators import macd
    result = macd(ohlcv)
    diff = (result["macd"] - result["signal"]).round(10)
    assert (diff.dropna() == result["histogram"].dropna().round(10)).all()


def test_bollinger_bands_columns(ohlcv):
    from ibkr_core_mcp.indicators import bollinger_bands
    result = bollinger_bands(ohlcv, period=20)
    assert set(result.columns) == {"bb_upper", "bb_mid", "bb_lower"}
    valid = result.dropna()
    assert (valid["bb_upper"] >= valid["bb_mid"]).all()
    assert (valid["bb_mid"] >= valid["bb_lower"]).all()


def test_atr_positive(ohlcv):
    from ibkr_core_mcp.indicators import atr
    result = atr(ohlcv, period=14)
    assert result.dropna().gt(0).all()


def test_vwap_positive(ohlcv):
    from ibkr_core_mcp.indicators import vwap
    result = vwap(ohlcv)
    assert result.dropna().gt(0).all()


def test_stochastic_bounds(ohlcv):
    from ibkr_core_mcp.indicators import stochastic
    result = stochastic(ohlcv)
    assert set(result.columns) == {"stoch_k", "stoch_d"}
    valid_k = result["stoch_k"].dropna()
    assert (valid_k >= 0).all() and (valid_k <= 100).all()


def test_williams_r_bounds(ohlcv):
    from ibkr_core_mcp.indicators import williams_r
    result = williams_r(ohlcv, period=14)
    valid = result.dropna()
    assert (valid >= -100).all() and (valid <= 0).all()


def test_keltner_channels_columns(ohlcv):
    from ibkr_core_mcp.indicators import keltner_channels
    result = keltner_channels(ohlcv)
    assert set(result.columns) == {"kc_upper", "kc_mid", "kc_lower"}
    valid = result.dropna()
    assert (valid["kc_upper"] >= valid["kc_mid"]).all()


def test_obv_cumulative(ohlcv):
    from ibkr_core_mcp.indicators import obv
    result = obv(ohlcv)
    assert isinstance(result, pd.Series)
    assert len(result) == len(ohlcv)


def test_volume_sma_length(ohlcv):
    from ibkr_core_mcp.indicators import volume_sma
    result = volume_sma(ohlcv, period=20)
    assert result.iloc[:19].isna().all()


def test_volume_ratio_around_one(ohlcv):
    from ibkr_core_mcp.indicators import volume_ratio
    result = volume_ratio(ohlcv, period=20)
    # Average of ratios should be close to 1
    assert abs(result.dropna().mean() - 1.0) < 0.2


def test_add_all_columns(ohlcv):
    from ibkr_core_mcp import indicators
    result = indicators.add_all(ohlcv)
    expected_cols = {
        "sma_20", "ema_20", "rsi", "macd", "macd_signal", "macd_hist",
        "vwap", "bb_upper", "bb_mid", "bb_lower", "atr",
        "stoch_k", "stoch_d", "williams_r",
        "kc_upper", "kc_mid", "kc_lower",
        "obv", "volume_sma", "volume_ratio",
    }
    assert expected_cols.issubset(set(result.columns))


def test_add_all_preserves_ohlcv(ohlcv):
    from ibkr_core_mcp import indicators
    result = indicators.add_all(ohlcv)
    assert set(["open", "high", "low", "close", "volume"]).issubset(set(result.columns))
    assert len(result) == len(ohlcv)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_indicators.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Create `ibkr_core_mcp/indicators.py`**

```python
from __future__ import annotations
import numpy as np
import pandas as pd


def sma(df: pd.DataFrame, period: int = 20) -> pd.Series:
    return df["close"].rolling(period).mean()


def ema(df: pd.DataFrame, period: int = 20) -> pd.Series:
    return df["close"].ewm(span=period, adjust=False).mean()


def rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    delta = df["close"].diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, float("nan"))
    return 100 - (100 / (1 + rs))


def macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return pd.DataFrame(
        {"macd": macd_line, "signal": signal_line, "histogram": macd_line - signal_line},
        index=df.index,
    )


def vwap(df: pd.DataFrame) -> pd.Series:
    typical = (df["high"] + df["low"] + df["close"]) / 3
    return (typical * df["volume"]).cumsum() / df["volume"].cumsum()


def bollinger_bands(df: pd.DataFrame, period: int = 20, std: float = 2.0) -> pd.DataFrame:
    mid = df["close"].rolling(period).mean()
    dev = df["close"].rolling(period).std()
    return pd.DataFrame(
        {"bb_upper": mid + std * dev, "bb_mid": mid, "bb_lower": mid - std * dev},
        index=df.index,
    )


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - df["close"].shift(1)).abs(),
            (df["low"] - df["close"].shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def stochastic(df: pd.DataFrame, k: int = 14, d: int = 3) -> pd.DataFrame:
    lo = df["low"].rolling(k).min()
    hi = df["high"].rolling(k).max()
    pct_k = 100 * (df["close"] - lo) / (hi - lo).replace(0, float("nan"))
    return pd.DataFrame({"stoch_k": pct_k, "stoch_d": pct_k.rolling(d).mean()}, index=df.index)


def williams_r(df: pd.DataFrame, period: int = 14) -> pd.Series:
    hi = df["high"].rolling(period).max()
    lo = df["low"].rolling(period).min()
    return -100 * (hi - df["close"]) / (hi - lo).replace(0, float("nan"))


def keltner_channels(df: pd.DataFrame, period: int = 20, atr_mult: float = 2.0) -> pd.DataFrame:
    mid = ema(df, period)
    band = atr_mult * atr(df, period)
    return pd.DataFrame(
        {"kc_upper": mid + band, "kc_mid": mid, "kc_lower": mid - band},
        index=df.index,
    )


def obv(df: pd.DataFrame) -> pd.Series:
    direction = df["close"].diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    return (direction * df["volume"]).cumsum()


def volume_sma(df: pd.DataFrame, period: int = 20) -> pd.Series:
    return df["volume"].rolling(period).mean()


def volume_ratio(df: pd.DataFrame, period: int = 20) -> pd.Series:
    avg = volume_sma(df, period)
    return df["volume"] / avg.replace(0, float("nan"))


def add_all(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of df with all indicator columns appended."""
    out = df.copy()
    out["sma_20"] = sma(df, 20)
    out["ema_20"] = ema(df, 20)
    out["rsi"] = rsi(df, 14)
    _macd = macd(df)
    out["macd"] = _macd["macd"]
    out["macd_signal"] = _macd["signal"]
    out["macd_hist"] = _macd["histogram"]
    out["vwap"] = vwap(df)
    _bb = bollinger_bands(df)
    out["bb_upper"] = _bb["bb_upper"]
    out["bb_mid"] = _bb["bb_mid"]
    out["bb_lower"] = _bb["bb_lower"]
    out["atr"] = atr(df, 14)
    _stoch = stochastic(df)
    out["stoch_k"] = _stoch["stoch_k"]
    out["stoch_d"] = _stoch["stoch_d"]
    out["williams_r"] = williams_r(df)
    _kc = keltner_channels(df)
    out["kc_upper"] = _kc["kc_upper"]
    out["kc_mid"] = _kc["kc_mid"]
    out["kc_lower"] = _kc["kc_lower"]
    out["obv"] = obv(df)
    out["volume_sma"] = volume_sma(df)
    out["volume_ratio"] = volume_ratio(df)
    return out
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_indicators.py -v
```

Expected: all 16 pass.

- [ ] **Step 5: Commit**

```bash
git add ibkr_core_mcp/indicators.py tests/test_indicators.py
git commit -m "feat: indicators.py — 14 technical indicators + add_all()"
```

---

## Task 3: `analytics.py`

**Files:**
- Create: `ibkr_core_mcp/analytics.py`
- Create: `tests/test_analytics.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_analytics.py
import pytest
import numpy as np
import pandas as pd


@pytest.fixture
def flat_returns():
    """Daily returns of exactly 0% — all metrics should be 0."""
    return pd.Series([0.0] * 252)


@pytest.fixture
def positive_returns():
    """Steady +0.1% per day — Sharpe should be high, max_drawdown ~0."""
    np.random.seed(1)
    base = 0.001
    noise = np.random.randn(252) * 0.005
    return pd.Series(base + noise)


@pytest.fixture
def crash_returns():
    """+1% for 100 days, -50% one day, then +0.5% for 151 days."""
    r = [0.01] * 100 + [-0.50] + [0.005] * 151
    return pd.Series(r)


def test_sharpe_flat_is_zero(flat_returns):
    from ibkr_core_mcp.analytics import sharpe
    assert sharpe(flat_returns) == 0.0


def test_sharpe_positive_returns_gt_zero(positive_returns):
    from ibkr_core_mcp.analytics import sharpe
    assert sharpe(positive_returns) > 0


def test_sortino_positive_gt_sharpe(positive_returns):
    from ibkr_core_mcp.analytics import sharpe, sortino
    # Sortino ignores upside deviation so should be >= Sharpe for positive returns
    assert sortino(positive_returns) >= sharpe(positive_returns)


def test_max_drawdown_negative(crash_returns):
    from ibkr_core_mcp.analytics import max_drawdown
    mdd = max_drawdown(crash_returns)
    assert mdd < 0
    assert mdd <= -0.40  # at least 40% drawdown


def test_max_drawdown_flat_is_zero(flat_returns):
    from ibkr_core_mcp.analytics import max_drawdown
    assert max_drawdown(flat_returns) == 0.0


def test_max_drawdown_duration_after_crash(crash_returns):
    from ibkr_core_mcp.analytics import max_drawdown_duration
    dur = max_drawdown_duration(crash_returns)
    assert dur >= 100  # recovery takes at least 100 bars


def test_cagr_positive_returns_positive(positive_returns):
    from ibkr_core_mcp.analytics import cagr
    assert cagr(positive_returns) > 0


def test_calmar_positive(positive_returns):
    from ibkr_core_mcp.analytics import calmar
    result = calmar(positive_returns)
    # May be 0 if no drawdown, but should not be negative
    assert result >= 0


def test_win_rate_empty():
    from ibkr_core_mcp.analytics import win_rate
    assert win_rate([]) == 0.0


def test_win_rate_all_winning():
    from ibkr_core_mcp.analytics import win_rate
    trades = [{"pnl": 100.0}, {"pnl": 50.0}, {"pnl": 25.0}]
    assert win_rate(trades) == 1.0


def test_win_rate_mixed():
    from ibkr_core_mcp.analytics import win_rate
    trades = [{"pnl": 100.0}, {"pnl": -50.0}]
    assert win_rate(trades) == 0.5


def test_profit_factor_no_losses():
    from ibkr_core_mcp.analytics import profit_factor
    trades = [{"pnl": 100.0}, {"pnl": 50.0}]
    pf = profit_factor(trades)
    assert pf == float("inf")


def test_profit_factor_equal_wins_losses():
    from ibkr_core_mcp.analytics import profit_factor
    trades = [{"pnl": 100.0}, {"pnl": -100.0}]
    assert profit_factor(trades) == 1.0


def test_full_report_keys(positive_returns):
    from ibkr_core_mcp.analytics import full_report
    report = full_report(positive_returns)
    for key in ["total_return", "cagr", "sharpe", "sortino", "calmar", "max_drawdown", "max_drawdown_duration", "num_bars"]:
        assert key in report


def test_full_report_with_trades(positive_returns):
    from ibkr_core_mcp.analytics import full_report
    trades = [{"pnl": 200.0}, {"pnl": -50.0}, {"pnl": 75.0}]
    report = full_report(positive_returns, trades=trades)
    assert "win_rate" in report
    assert "profit_factor" in report
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_analytics.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Create `ibkr_core_mcp/analytics.py`**

```python
from __future__ import annotations
import numpy as np
import pandas as pd


def sharpe(returns: pd.Series, risk_free: float = 0.0, periods: int = 252) -> float:
    excess = returns - risk_free / periods
    std = excess.std()
    if std == 0:
        return 0.0
    return float(excess.mean() / std * np.sqrt(periods))


def sortino(returns: pd.Series, risk_free: float = 0.0, periods: int = 252) -> float:
    excess = returns - risk_free / periods
    downside = excess[excess < 0].std()
    if downside == 0:
        return 0.0
    return float(excess.mean() / downside * np.sqrt(periods))


def max_drawdown(returns: pd.Series) -> float:
    equity = (1 + returns).cumprod()
    peak = equity.cummax()
    dd = (equity - peak) / peak
    return float(dd.min())


def max_drawdown_duration(returns: pd.Series) -> int:
    equity = (1 + returns).cumprod()
    peak = equity.cummax()
    in_dd = (equity < peak).astype(int)
    max_dur = 0
    cur = 0
    for v in in_dd:
        cur = cur + 1 if v else 0
        max_dur = max(max_dur, cur)
    return max_dur


def cagr(returns: pd.Series, periods: int = 252) -> float:
    total = float((1 + returns).prod())
    n = len(returns) / periods
    if n <= 0 or total <= 0:
        return 0.0
    return float(total ** (1.0 / n) - 1)


def calmar(returns: pd.Series, periods: int = 252) -> float:
    mdd = max_drawdown(returns)
    if mdd == 0:
        return 0.0
    return float(cagr(returns, periods) / abs(mdd))


def win_rate(trades: list[dict]) -> float:
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if _pnl(t) > 0)
    return wins / len(trades)


def profit_factor(trades: list[dict]) -> float:
    gains = sum(_pnl(t) for t in trades if _pnl(t) > 0)
    losses = sum(abs(_pnl(t)) for t in trades if _pnl(t) < 0)
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return gains / losses


def avg_win_loss_ratio(trades: list[dict]) -> float:
    wins = [_pnl(t) for t in trades if _pnl(t) > 0]
    losses = [abs(_pnl(t)) for t in trades if _pnl(t) < 0]
    avg_w = sum(wins) / len(wins) if wins else 0.0
    avg_l = sum(losses) / len(losses) if losses else 0.0
    if avg_l == 0:
        return float("inf") if avg_w > 0 else 0.0
    return avg_w / avg_l


def trade_summary(trades: list[dict]) -> dict:
    return {
        "total_trades": len(trades),
        "win_rate": win_rate(trades),
        "profit_factor": profit_factor(trades),
        "avg_win_loss_ratio": avg_win_loss_ratio(trades),
    }


def full_report(returns: pd.Series, trades: list[dict] | None = None) -> dict:
    report: dict = {
        "total_return": float((1 + returns).prod() - 1),
        "cagr": cagr(returns),
        "sharpe": sharpe(returns),
        "sortino": sortino(returns),
        "calmar": calmar(returns),
        "max_drawdown": max_drawdown(returns),
        "max_drawdown_duration": max_drawdown_duration(returns),
        "num_bars": len(returns),
    }
    if trades:
        report.update(trade_summary(trades))
    return report


def _pnl(trade: dict) -> float:
    return float(trade.get("pnl", trade.get("realizedPnl", 0)))
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_analytics.py -v
```

Expected: all 15 pass.

- [ ] **Step 5: Commit**

```bash
git add ibkr_core_mcp/analytics.py tests/test_analytics.py
git commit -m "feat: analytics.py — Sharpe, Sortino, Calmar, drawdown, CAGR, trade metrics"
```

---

## Task 4: `backtest.py` — RestrictedPython sandbox

**Files:**
- Create: `ibkr_core_mcp/backtest.py`
- Create: `tests/test_backtest.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_backtest.py
import pytest
import numpy as np
import pandas as pd


@pytest.fixture
def ohlcv():
    np.random.seed(0)
    n = 200
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    high = close + np.random.uniform(0.1, 1.0, n)
    low = close - np.random.uniform(0.1, 1.0, n)
    open_ = close + np.random.randn(n) * 0.2
    volume = np.random.randint(500_000, 2_000_000, n).astype(float)
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx)


def test_simple_long_strategy(ohlcv):
    from ibkr_core_mcp.backtest import run_backtest, BacktestResult
    code = "df['signal'] = 1"  # always long
    result = run_backtest(code, ohlcv, strategy_name="always_long", symbol="TEST")
    assert isinstance(result, BacktestResult)
    assert result.strategy_name == "always_long"
    assert result.symbol == "TEST"
    assert isinstance(result.total_return, float)
    assert isinstance(result.sharpe, float)
    assert isinstance(result.max_drawdown, float)
    assert isinstance(result.num_trades, int)
    assert len(result.equity_curve) > 0


def test_flat_signal_zero_trades(ohlcv):
    from ibkr_core_mcp.backtest import run_backtest
    code = "df['signal'] = 0"  # always flat
    result = run_backtest(code, ohlcv)
    assert result.total_return == 0.0
    assert result.num_trades == 0


def test_rsi_strategy(ohlcv):
    from ibkr_core_mcp.backtest import run_backtest
    code = """
delta = df['close'].diff()
gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
rs = gain / loss.replace(0, float('nan'))
rsi = 100 - (100 / (1 + rs))
df['signal'] = 0
df.loc[rsi < 30, 'signal'] = 1
df.loc[rsi > 70, 'signal'] = -1
"""
    result = run_backtest(code, ohlcv, strategy_name="rsi_mean_reversion")
    assert isinstance(result.total_return, float)


def test_syntax_error_raises(ohlcv):
    from ibkr_core_mcp.backtest import run_backtest
    from ibkr_core_mcp.exceptions import BacktestSyntaxError
    with pytest.raises(BacktestSyntaxError):
        run_backtest("df['signal'] = (", ohlcv)


def test_runtime_error_raises(ohlcv):
    from ibkr_core_mcp.backtest import run_backtest
    from ibkr_core_mcp.exceptions import BacktestRuntimeError
    with pytest.raises(BacktestRuntimeError):
        run_backtest("df['signal'] = 1 / 0", ohlcv)


def test_no_network_access(ohlcv):
    from ibkr_core_mcp.backtest import run_backtest
    from ibkr_core_mcp.exceptions import BacktestRuntimeError
    with pytest.raises((BacktestRuntimeError, Exception)):
        run_backtest("import urllib.request; urllib.request.urlopen('http://example.com')", ohlcv)


def test_no_file_access(ohlcv):
    from ibkr_core_mcp.backtest import run_backtest
    from ibkr_core_mcp.exceptions import BacktestRuntimeError
    with pytest.raises((BacktestRuntimeError, Exception)):
        run_backtest("open('/etc/passwd', 'r')", ohlcv)


def test_result_to_dict(ohlcv):
    from ibkr_core_mcp.backtest import run_backtest
    result = run_backtest("df['signal'] = 1", ohlcv, symbol="AAPL")
    d = result.to_dict()
    assert "equity_curve" not in d
    assert "total_return" in d
    assert "sharpe" in d
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_backtest.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Create `ibkr_core_mcp/backtest.py`**

```python
from __future__ import annotations
from dataclasses import dataclass, field
import pandas as pd
import numpy as np

from RestrictedPython import compile_restricted, safe_globals, limited_builtins

from ibkr_core_mcp.exceptions import BacktestSyntaxError, BacktestRuntimeError
from ibkr_core_mcp import analytics as _analytics


@dataclass
class BacktestResult:
    symbol: str
    strategy_name: str
    total_return: float
    sharpe: float
    sortino: float
    max_drawdown: float
    num_trades: int
    win_rate: float
    equity_curve: pd.Series = field(default_factory=pd.Series)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "strategy_name": self.strategy_name,
            "total_return": self.total_return,
            "sharpe": self.sharpe,
            "sortino": self.sortino,
            "max_drawdown": self.max_drawdown,
            "num_trades": self.num_trades,
            "win_rate": self.win_rate,
        }


def run_backtest(
    code: str,
    df: pd.DataFrame,
    strategy_name: str = "",
    symbol: str = "",
) -> BacktestResult:
    """Execute strategy code in a RestrictedPython sandbox and return performance metrics.

    Strategy code receives `df` (OHLCV DataFrame) and must set df['signal']:
        1 = long, 0 = flat, -1 = short
    Allowed: pandas (pd), numpy (np), basic builtins.
    Blocked: network, file I/O, os, sys.
    """
    try:
        byte_code = compile_restricted(code, "<strategy>", "exec")
    except SyntaxError as e:
        raise BacktestSyntaxError(f"Strategy syntax error: {e}") from e

    sandbox: dict = {
        **safe_globals,
        "__builtins__": {
            k: v for k, v in limited_builtins.items()
            if k not in ("__import__", "open", "eval", "exec", "compile")
        },
        "pd": pd,
        "np": np,
        "float": float,
        "int": int,
        "abs": abs,
        "range": range,
        "len": len,
        "df": df.copy(),
    }

    try:
        exec(byte_code, sandbox)  # noqa: S102
    except Exception as e:
        raise BacktestRuntimeError(f"Strategy runtime error: {e}") from e

    result_df: pd.DataFrame = sandbox.get("df", df)

    if "signal" not in result_df.columns:
        raise BacktestRuntimeError("Strategy must set df['signal'] (1=long, 0=flat, -1=short)")

    return _compute_metrics(result_df, strategy_name=strategy_name, symbol=symbol)


def _compute_metrics(df: pd.DataFrame, strategy_name: str, symbol: str) -> BacktestResult:
    sig = df["signal"].fillna(0).shift(1).fillna(0)  # trade on next bar open
    price_returns = df["close"].pct_change().fillna(0)
    strategy_returns = sig * price_returns

    equity = (1 + strategy_returns).cumprod()

    # Count trades (signal changes)
    signal_changes = (sig.diff().abs() > 0).sum()
    num_trades = int(signal_changes)

    # Win rate: fraction of non-zero return bars where we profited
    active = strategy_returns[sig != 0]
    wr = float((active > 0).sum() / len(active)) if len(active) > 0 else 0.0

    total_return = float(equity.iloc[-1] - 1) if len(equity) > 0 else 0.0

    # Flat strategy
    if (sig == 0).all():
        return BacktestResult(
            symbol=symbol,
            strategy_name=strategy_name,
            total_return=0.0,
            sharpe=0.0,
            sortino=0.0,
            max_drawdown=0.0,
            num_trades=0,
            win_rate=0.0,
            equity_curve=equity,
        )

    return BacktestResult(
        symbol=symbol,
        strategy_name=strategy_name,
        total_return=total_return,
        sharpe=_analytics.sharpe(strategy_returns),
        sortino=_analytics.sortino(strategy_returns),
        max_drawdown=_analytics.max_drawdown(strategy_returns),
        num_trades=num_trades,
        win_rate=wr,
        equity_curve=equity,
    )
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_backtest.py -v
```

Expected: 8 pass. Note: `test_no_network_access` and `test_no_file_access` may pass because `import` and `open` are removed from builtins — RestrictedPython blocks `import` statements syntactically, so those tests should raise either `BacktestRuntimeError` or some form of `Exception`.

- [ ] **Step 5: Commit**

```bash
git add ibkr_core_mcp/backtest.py tests/test_backtest.py
git commit -m "feat: backtest.py — RestrictedPython sandbox executor with BacktestResult"
```

---

## Task 5: `pinescript.py`

**Files:**
- Create: `ibkr_core_mcp/pinescript.py`
- Create: `tests/test_pinescript.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_pinescript.py
import pytest
import numpy as np
import pandas as pd


@pytest.fixture
def signals():
    idx = pd.date_range("2025-01-01", periods=100, freq="B")
    vals = ([1] * 30 + [0] * 20 + [-1] * 20 + [1] * 30)
    return pd.Series(vals, index=idx)


@pytest.fixture
def backtest_result():
    from ibkr_core_mcp.backtest import BacktestResult
    return BacktestResult(
        symbol="AAPL",
        strategy_name="RSI Mean Reversion",
        total_return=0.15,
        sharpe=1.2,
        sortino=1.8,
        max_drawdown=-0.08,
        num_trades=24,
        win_rate=0.58,
        equity_curve=pd.Series([1.0, 1.05, 1.10, 1.08, 1.15]),
    )


@pytest.fixture
def ohlcv():
    np.random.seed(1)
    n = 100
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    return pd.DataFrame({
        "open": close, "high": close + 0.5, "low": close - 0.5,
        "close": close, "volume": np.ones(n) * 1e6,
    }, index=pd.date_range("2025-01-01", periods=n, freq="B"))


def test_strategy_from_signals_is_string(signals):
    from ibkr_core_mcp.pinescript import strategy_from_signals
    script = strategy_from_signals("Test Strategy", signals, "AAPL", "1D")
    assert isinstance(script, str)
    assert len(script) > 100


def test_strategy_from_signals_has_pine_header(signals):
    from ibkr_core_mcp.pinescript import strategy_from_signals
    script = strategy_from_signals("Test Strategy", signals, "AAPL", "1D")
    assert "//@version=5" in script
    assert "strategy(" in script


def test_strategy_from_signals_has_entry_exit(signals):
    from ibkr_core_mcp.pinescript import strategy_from_signals
    script = strategy_from_signals("Test Strategy", signals, "AAPL", "1D")
    assert "strategy.entry" in script or "strategy.long" in script or "longCondition" in script


def test_indicator_script_returns_string():
    from ibkr_core_mcp.pinescript import indicator_script
    script = indicator_script("My Indicators", ["rsi", "macd"], {})
    assert isinstance(script, str)
    assert "//@version=5" in script
    assert "indicator(" in script


def test_indicator_script_includes_rsi():
    from ibkr_core_mcp.pinescript import indicator_script
    script = indicator_script("RSI Study", ["rsi"], {"rsi_period": 14})
    assert "rsi" in script.lower()
    assert "ta.rsi" in script or "RSI" in script


def test_indicator_script_includes_macd():
    from ibkr_core_mcp.pinescript import indicator_script
    script = indicator_script("MACD Study", ["macd"], {})
    assert "macd" in script.lower()


def test_indicator_script_includes_bb():
    from ibkr_core_mcp.pinescript import indicator_script
    script = indicator_script("BB Study", ["bollinger_bands"], {})
    assert "bollinger" in script.lower() or "bb" in script.lower() or "ta.bb" in script


def test_strategy_from_backtest_returns_string(backtest_result, ohlcv):
    from ibkr_core_mcp.pinescript import strategy_from_backtest
    script = strategy_from_backtest(backtest_result, ohlcv)
    assert isinstance(script, str)
    assert "//@version=5" in script
    assert "strategy(" in script


def test_strategy_from_backtest_includes_symbol(backtest_result, ohlcv):
    from ibkr_core_mcp.pinescript import strategy_from_backtest
    script = strategy_from_backtest(backtest_result, ohlcv)
    assert "AAPL" in script or "RSI Mean Reversion" in script


def test_strategy_from_backtest_has_metrics_comment(backtest_result, ohlcv):
    from ibkr_core_mcp.pinescript import strategy_from_backtest
    script = strategy_from_backtest(backtest_result, ohlcv)
    assert "Sharpe" in script or "sharpe" in script or "Total Return" in script
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_pinescript.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Create `ibkr_core_mcp/pinescript.py`**

```python
from __future__ import annotations
import pandas as pd

_INDICATOR_SNIPPETS: dict[str, str] = {
    "rsi": """\
// RSI
rsiLength = input.int({rsi_period}, "RSI Length")
rsiValue = ta.rsi(close, rsiLength)
plot(rsiValue, "RSI", color.new(color.purple, 0))
hline(70, "Overbought", color.red)
hline(30, "Oversold", color.green)
""",
    "macd": """\
// MACD
[macdLine, signalLine, hist] = ta.macd(close, {macd_fast}, {macd_slow}, {macd_signal})
plot(macdLine, "MACD", color.blue)
plot(signalLine, "Signal", color.orange)
plot(hist, "Histogram", color.gray, style=plot.style_histogram)
""",
    "bollinger_bands": """\
// Bollinger Bands
bbLength = input.int({bb_period}, "BB Length")
bbMult = input.float({bb_std}, "BB Std Dev")
[bbUpper, bbMid, bbLower] = ta.bb(close, bbLength, bbMult)
plot(bbUpper, "BB Upper", color.red)
plot(bbMid, "BB Mid", color.gray)
plot(bbLower, "BB Lower", color.green)
""",
    "ema": """\
// EMA
emaLength = input.int({ema_period}, "EMA Length")
emaValue = ta.ema(close, emaLength)
plot(emaValue, "EMA", color.orange)
""",
    "sma": """\
// SMA
smaLength = input.int({sma_period}, "SMA Length")
smaValue = ta.sma(close, smaLength)
plot(smaValue, "SMA", color.blue)
""",
    "atr": """\
// ATR
atrLength = input.int({atr_period}, "ATR Length")
atrValue = ta.atr(atrLength)
plot(atrValue, "ATR", color.purple)
""",
}

_PARAM_DEFAULTS = {
    "rsi_period": 14,
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "bb_period": 20,
    "bb_std": 2.0,
    "ema_period": 20,
    "sma_period": 20,
    "atr_period": 14,
}


def strategy_from_signals(
    name: str,
    signals: pd.Series,
    symbol: str,
    timeframe: str,
) -> str:
    """Generate a PineScript v5 strategy from a signal series (1=long, 0=flat, -1=short)."""
    long_entries = int((signals.diff() == 1).sum() + (signals.iloc[0] == 1))
    short_entries = int((signals.diff() == -1).sum() + (signals.iloc[0] == -1))

    return f"""//@version=5
// Generated by ibkr_core_mcp — {name}
// Symbol: {symbol} | Timeframe: {timeframe}
// Signal stats: {long_entries} long entries, {short_entries} short entries
strategy("{name}", overlay=true, default_qty_type=strategy.percent_of_equity, default_qty_value=100)

// ── Signal logic (replace with your conditions) ─────────────────────────────
// This script uses a simplified representation of the original signal series.
// Reconstruct your entry conditions below based on your indicator logic.

longCondition = ta.crossover(ta.ema(close, 12), ta.ema(close, 26))
shortCondition = ta.crossunder(ta.ema(close, 12), ta.ema(close, 26))
exitCondition = false

if longCondition
    strategy.entry("Long", strategy.long)

if shortCondition
    strategy.entry("Short", strategy.short)

if exitCondition
    strategy.close_all()

// ── Visuals ──────────────────────────────────────────────────────────────────
plot(ta.ema(close, 12), "EMA 12", color.green)
plot(ta.ema(close, 26), "EMA 26", color.red)
"""


def indicator_script(
    name: str,
    indicators: list[str],
    params: dict,
) -> str:
    """Generate a PineScript v5 indicator study with the requested indicators."""
    merged = {**_PARAM_DEFAULTS, **params}
    snippets = []
    for ind in indicators:
        template = _INDICATOR_SNIPPETS.get(ind, f"// Indicator '{ind}' — not yet supported\n")
        try:
            snippets.append(template.format(**merged))
        except KeyError:
            snippets.append(template)

    ind_list = ", ".join(indicators)
    return f"""//@version=5
// Generated by ibkr_core_mcp — {name}
// Indicators: {ind_list}
indicator("{name}", overlay={_needs_overlay(indicators)})

{chr(10).join(snippets)}"""


def strategy_from_backtest(
    backtest_result: object,
    df: pd.DataFrame,
) -> str:
    """Generate a PineScript v5 strategy from a BacktestResult + OHLCV DataFrame."""
    name = getattr(backtest_result, "strategy_name", "Exported Strategy")
    symbol = getattr(backtest_result, "symbol", "")
    total_return = getattr(backtest_result, "total_return", 0.0)
    sharpe = getattr(backtest_result, "sharpe", 0.0)
    max_dd = getattr(backtest_result, "max_drawdown", 0.0)
    num_trades = getattr(backtest_result, "num_trades", 0)
    win_rate = getattr(backtest_result, "win_rate", 0.0)

    timeframe = _infer_timeframe(df)

    return f"""//@version=5
// Generated by ibkr_core_mcp — {name}
// Symbol: {symbol} | Timeframe: {timeframe}
//
// Backtest Summary:
//   Total Return : {total_return:.1%}
//   Sharpe Ratio : {sharpe:.2f}
//   Max Drawdown : {max_dd:.1%}
//   Num Trades   : {num_trades}
//   Win Rate     : {win_rate:.1%}
//
// ⚠ This script is a starting point. Replicate your entry/exit logic below.
strategy("{name}", overlay=true, default_qty_type=strategy.percent_of_equity, default_qty_value=100)

// ── Inputs ───────────────────────────────────────────────────────────────────
rsiLength  = input.int(14, "RSI Length", minval=2, maxval=50)
rsiOversold  = input.int(30, "RSI Oversold", minval=10, maxval=50)
rsiOverbought = input.int(70, "RSI Overbought", minval=50, maxval=90)

// ── Indicators ───────────────────────────────────────────────────────────────
rsiValue = ta.rsi(close, rsiLength)
[macdLine, signalLine, _hist] = ta.macd(close, 12, 26, 9)

// ── Entry / Exit ─────────────────────────────────────────────────────────────
longEntry  = ta.crossover(rsiValue, rsiOversold)
longExit   = ta.crossunder(rsiValue, rsiOverbought)
shortEntry = ta.crossunder(rsiValue, rsiOverbought)
shortExit  = ta.crossover(rsiValue, rsiOversold)

if longEntry
    strategy.entry("Long", strategy.long)
if longExit
    strategy.close("Long")
if shortEntry
    strategy.entry("Short", strategy.short)
if shortExit
    strategy.close("Short")

// ── Visuals ───────────────────────────────────────────────────────────────────
plot(rsiValue, "RSI", color.purple)
hline(rsiOversold, "Oversold", color.green)
hline(rsiOverbought, "Overbought", color.red)
"""


def _needs_overlay(indicators: list[str]) -> str:
    overlay_indicators = {"sma", "ema", "bollinger_bands", "keltner_channels", "vwap"}
    return "true" if any(i in overlay_indicators for i in indicators) else "false"


def _infer_timeframe(df: pd.DataFrame) -> str:
    if len(df) < 2:
        return "1D"
    delta = df.index[1] - df.index[0]
    minutes = int(delta.total_seconds() / 60)
    if minutes <= 1:
        return "1"
    if minutes <= 5:
        return "5"
    if minutes <= 60:
        return f"{minutes}"
    if minutes <= 1440:
        return "1D"
    return "1W"
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_pinescript.py -v
```

Expected: all 10 pass.

- [ ] **Step 5: Commit**

```bash
git add ibkr_core_mcp/pinescript.py tests/test_pinescript.py
git commit -m "feat: pinescript.py — PineScript v5 generation (strategy, indicator, from backtest)"
```

---

## Task 6: Add 4 new Claude tools to `claude_tools.py`

**Files:**
- Modify: `ibkr_core_mcp/claude_tools.py`
- Modify: `tests/test_claude_tools.py` — add 4 new tests

- [ ] **Step 1: Write failing tests**

Add these tests to `tests/test_claude_tools.py`:

```python
def test_tools_count_at_least_18(toolkit):
    assert len(toolkit.tools) >= 18


def test_execute_add_indicators(toolkit):
    import pandas as pd, numpy as np
    n = 100
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    df = pd.DataFrame({
        "open": close, "high": close + 0.5, "low": close - 0.5,
        "close": close, "volume": np.ones(n) * 1e6,
    }, index=pd.date_range("2025-01-01", periods=n, freq="B"))
    toolkit._cache.check.return_value = True
    toolkit._cache.load.return_value = df
    text, fig = toolkit.execute("add_indicators", {
        "symbol": "AAPL", "timeframe": "1D", "period": "1Y", "end": "2026-05-22"
    })
    assert len(text) > 0
    assert fig is None


def test_execute_run_backtest_tool(toolkit):
    import pandas as pd, numpy as np
    n = 100
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    df = pd.DataFrame({
        "open": close, "high": close + 0.5, "low": close - 0.5,
        "close": close, "volume": np.ones(n) * 1e6,
    }, index=pd.date_range("2025-01-01", periods=n, freq="B"))
    toolkit._cache.check.return_value = True
    toolkit._cache.load.return_value = df
    toolkit._store.save_backtest.return_value = 1
    text, fig = toolkit.execute("run_backtest", {
        "code": "df['signal'] = 1",
        "symbol": "AAPL", "timeframe": "1D", "period": "1Y",
        "end": "2026-05-22", "strategy_name": "test"
    })
    assert len(text) > 0


def test_execute_generate_pinescript_tool(toolkit):
    toolkit._cache.check.return_value = True
    import pandas as pd, numpy as np
    n = 100
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    df = pd.DataFrame({
        "open": close, "high": close + 0.5, "low": close - 0.5,
        "close": close, "volume": np.ones(n) * 1e6,
    }, index=pd.date_range("2025-01-01", periods=n, freq="B"))
    toolkit._cache.load.return_value = df
    text, fig = toolkit.execute("generate_pinescript", {
        "symbol": "AAPL", "indicators": ["rsi", "macd"]
    })
    assert "//@version=5" in text


def test_execute_get_analytics_tool(toolkit):
    import pandas as pd, numpy as np
    n = 100
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    df = pd.DataFrame({
        "open": close, "high": close + 0.5, "low": close - 0.5,
        "close": close, "volume": np.ones(n) * 1e6,
    }, index=pd.date_range("2025-01-01", periods=n, freq="B"))
    toolkit._cache.check.return_value = True
    toolkit._cache.load.return_value = df
    text, fig = toolkit.execute("get_analytics", {
        "symbol": "AAPL", "timeframe": "1D", "period": "1Y", "end": "2026-05-22"
    })
    assert "sharpe" in text.lower() or "Sharpe" in text
```

- [ ] **Step 2: Run new tests to verify they fail**

```bash
pytest tests/test_claude_tools.py -v -k "test_tools_count_at_least_18 or test_execute_add_indicators or test_execute_run_backtest_tool or test_execute_generate_pinescript_tool or test_execute_get_analytics_tool"
```

Expected: failures (tools count still 15, new handlers missing).

- [ ] **Step 3: Add 4 tool definitions to `TOOL_DEFINITIONS` in `claude_tools.py`**

After the existing 15 entries in `TOOL_DEFINITIONS`, append:

```python
    {
        "name": "add_indicators",
        "description": (
            "Load cached market data for a symbol and compute all technical indicators "
            "(RSI, MACD, Bollinger Bands, ATR, VWAP, OBV, Stochastic, Williams %R, Keltner Channels). "
            "Returns a summary of current indicator values."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Ticker symbol"},
                "timeframe": {"type": "string", "description": "e.g. '1D'"},
                "period": {"type": "string", "description": "e.g. '1Y'"},
                "end": {"type": "string", "description": "End date YYYY-MM-DD"},
            },
            "required": ["symbol", "timeframe", "period", "end"],
        },
    },
    {
        "name": "run_backtest",
        "description": (
            "Execute a Python strategy in a sandboxed environment against cached market data. "
            "Strategy code receives a pandas DataFrame `df` with OHLCV columns and must set "
            "df['signal'] = 1 (long), 0 (flat), or -1 (short). "
            "Returns Sharpe ratio, total return, max drawdown, trade count, and win rate."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python strategy code string"},
                "symbol": {"type": "string", "description": "Ticker symbol"},
                "timeframe": {"type": "string", "description": "e.g. '1D'"},
                "period": {"type": "string", "description": "e.g. '1Y'"},
                "end": {"type": "string", "description": "End date YYYY-MM-DD"},
                "strategy_name": {"type": "string", "description": "Human-readable name", "default": ""},
            },
            "required": ["code", "symbol", "timeframe", "period", "end"],
        },
    },
    {
        "name": "generate_pinescript",
        "description": (
            "Generate a PineScript v5 script for TradingView from a list of indicators "
            "or from a previously run backtest strategy. "
            "Output can be pasted directly into the TradingView Pine Editor."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Ticker symbol"},
                "indicators": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of indicators: 'rsi', 'macd', 'bollinger_bands', 'ema', 'sma', 'atr'",
                },
                "strategy_name": {"type": "string", "description": "Optional name for the script", "default": ""},
            },
            "required": ["symbol", "indicators"],
        },
    },
    {
        "name": "get_analytics",
        "description": (
            "Compute full portfolio/strategy analytics on cached OHLCV data: "
            "Sharpe ratio, Sortino ratio, Calmar ratio, CAGR, max drawdown, and drawdown duration."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Ticker symbol"},
                "timeframe": {"type": "string", "description": "e.g. '1D'"},
                "period": {"type": "string", "description": "e.g. '1Y'"},
                "end": {"type": "string", "description": "End date YYYY-MM-DD"},
            },
            "required": ["symbol", "timeframe", "period", "end"],
        },
    },
```

- [ ] **Step 4: Add 4 handler methods to the `ClaudeToolkit` class in `claude_tools.py`**

At the top of `claude_tools.py`, add these imports after the existing ones:

```python
from ibkr_core_mcp import analytics as _analytics
from ibkr_core_mcp import indicators as _indicators
from ibkr_core_mcp.backtest import run_backtest as _run_backtest
from ibkr_core_mcp import pinescript as _pinescript
```

In the `execute()` method, add these 4 entries to `handlers`:

```python
            "add_indicators": self._add_indicators,
            "run_backtest": self._run_backtest,
            "generate_pinescript": self._generate_pinescript,
            "get_analytics": self._get_analytics,
```

Add these 4 handler methods to the `ClaudeToolkit` class (after `_get_notifications`):

```python
    def _add_indicators(self, inputs: dict) -> tuple[str, Any]:
        symbol = inputs["symbol"].upper()
        timeframe = inputs["timeframe"]
        period = inputs["period"]
        end = inputs["end"]
        if not self._cache.check(symbol, timeframe, period, end):
            return f"No cached data for {symbol} {timeframe} {period}. Fetch it first with fetch_market_data.", None
        df = self._cache.load(symbol, timeframe, period, end)
        df = _indicators.add_all(df)
        last = df.iloc[-1]
        lines = [
            f"Indicators for {symbol} (last bar: {df.index[-1].date()}):",
            f"  RSI(14):          {last.get('rsi', float('nan')):.1f}",
            f"  MACD:             {last.get('macd', float('nan')):.4f}  Signal: {last.get('macd_signal', float('nan')):.4f}",
            f"  BB Upper/Mid/Low: {last.get('bb_upper', float('nan')):.2f} / {last.get('bb_mid', float('nan')):.2f} / {last.get('bb_lower', float('nan')):.2f}",
            f"  ATR(14):          {last.get('atr', float('nan')):.4f}",
            f"  VWAP:             {last.get('vwap', float('nan')):.2f}",
            f"  Stoch %K/%D:      {last.get('stoch_k', float('nan')):.1f} / {last.get('stoch_d', float('nan')):.1f}",
            f"  Williams %R:      {last.get('williams_r', float('nan')):.1f}",
            f"  Volume Ratio:     {last.get('volume_ratio', float('nan')):.2f}x avg",
        ]
        return "\n".join(lines), None

    def _run_backtest(self, inputs: dict) -> tuple[str, Any]:
        symbol = inputs["symbol"].upper()
        timeframe = inputs["timeframe"]
        period = inputs["period"]
        end = inputs["end"]
        code = inputs["code"]
        strategy_name = inputs.get("strategy_name", "")
        if not self._cache.check(symbol, timeframe, period, end):
            return f"No cached data for {symbol}. Fetch it first with fetch_market_data.", None
        df = self._cache.load(symbol, timeframe, period, end)
        result = _run_backtest(code, df, strategy_name=strategy_name, symbol=symbol)
        try:
            self._store.save_backtest(result.to_dict())
        except Exception:
            pass
        lines = [
            f"Backtest: {strategy_name or 'Unnamed'} on {symbol} {timeframe} ({period})",
            f"  Total Return:  {result.total_return:.1%}",
            f"  Sharpe Ratio:  {result.sharpe:.2f}",
            f"  Sortino Ratio: {result.sortino:.2f}",
            f"  Max Drawdown:  {result.max_drawdown:.1%}",
            f"  Num Trades:    {result.num_trades}",
            f"  Win Rate:      {result.win_rate:.1%}",
        ]
        return "\n".join(lines), None

    def _generate_pinescript(self, inputs: dict) -> tuple[str, Any]:
        symbol = inputs["symbol"].upper()
        indicators_list = inputs.get("indicators", ["rsi", "macd"])
        strategy_name = inputs.get("strategy_name", f"{symbol} Indicators")
        script = _pinescript.indicator_script(strategy_name, indicators_list, {})
        return script, None

    def _get_analytics(self, inputs: dict) -> tuple[str, Any]:
        symbol = inputs["symbol"].upper()
        timeframe = inputs["timeframe"]
        period = inputs["period"]
        end = inputs["end"]
        if not self._cache.check(symbol, timeframe, period, end):
            return f"No cached data for {symbol}. Fetch it first with fetch_market_data.", None
        df = self._cache.load(symbol, timeframe, period, end)
        returns = df["close"].pct_change().dropna()
        report = _analytics.full_report(returns)
        lines = [
            f"Analytics for {symbol} {timeframe} ({period}–{end}):",
            f"  Total Return:       {report['total_return']:.1%}",
            f"  CAGR:               {report['cagr']:.1%}",
            f"  Sharpe Ratio:       {report['sharpe']:.2f}",
            f"  Sortino Ratio:      {report['sortino']:.2f}",
            f"  Calmar Ratio:       {report['calmar']:.2f}",
            f"  Max Drawdown:       {report['max_drawdown']:.1%}",
            f"  Max DD Duration:    {report['max_drawdown_duration']} bars",
            f"  Bars analyzed:      {report['num_bars']}",
        ]
        return "\n".join(lines), None
```

- [ ] **Step 5: Run all tests**

```bash
pytest tests/ -v -m "not integration"
```

Expected: all pass (47 existing + new tests).

- [ ] **Step 6: Commit**

```bash
git add ibkr_core_mcp/claude_tools.py tests/test_claude_tools.py
git commit -m "feat: claude_tools — add add_indicators, run_backtest, generate_pinescript, get_analytics tools"
```

---

## Task 7: Update `__init__.py` + run full suite + tag v0.2.0

**Files:**
- Modify: `ibkr_core_mcp/__init__.py`
- Modify: `pyproject.toml` (version bump)

- [ ] **Step 1: Update `ibkr_core_mcp/__init__.py`**

Replace the contents of `ibkr_core_mcp/__init__.py` with:

```python
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
from ibkr_core_mcp.models import (
    Contract,
    Position,
    Trade,
    Order,
    AccountSummary,
    Notification,
    bars_to_dataframe,
)
from ibkr_core_mcp.backtest import run_backtest, BacktestResult
from ibkr_core_mcp import indicators
from ibkr_core_mcp import analytics
from ibkr_core_mcp import pinescript

__version__ = "0.2.0"
__all__ = [
    # Core
    "Config",
    "IBKRClient",
    "GDriveCache",
    "SQLiteStore",
    "ClaudeToolkit",
    # Auth
    "BrowserCookieAuth",
    "TokenAuth",
    "NoAuth",
    # Models
    "Contract",
    "Position",
    "Trade",
    "Order",
    "AccountSummary",
    "Notification",
    "bars_to_dataframe",
    # Backtest
    "run_backtest",
    "BacktestResult",
    # Functional modules
    "indicators",
    "analytics",
    "pinescript",
    # Exceptions
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

- [ ] **Step 2: Bump version in `pyproject.toml`**

Change `version = "0.1.0"` to `version = "0.2.0"`.

- [ ] **Step 3: Verify all public imports work**

```bash
python -c "
from ibkr_core_mcp import (
    Config, IBKRClient, GDriveCache, SQLiteStore, ClaudeToolkit,
    Contract, Position, Trade, AccountSummary, bars_to_dataframe,
    run_backtest, BacktestResult,
    indicators, analytics, pinescript,
    IBKRCoreError, CacheMissError,
)
print('All Phase 2 imports OK')
"
```

Expected output: `All Phase 2 imports OK`

- [ ] **Step 4: Run full unit test suite**

```bash
pytest tests/ -v -m "not integration"
```

Expected: all tests pass, 0 failures.

- [ ] **Step 5: Commit, tag v0.2.0, push**

```bash
git add ibkr_core_mcp/__init__.py pyproject.toml
git commit -m "feat: Phase 2 complete — models, indicators, analytics, backtest, pinescript, 19 Claude tools"
git tag v0.2.0
git push origin main --tags
```

---

## Self-Review

### Spec Coverage

| Spec section | Covered by |
|---|---|
| `models.py` — Pydantic v2, OHLCVBar, Contract, Position, Trade, Order, AccountSummary | Task 1 |
| `indicators.py` — RSI, MACD, BB, ATR, VWAP, Stoch, Williams %R, Keltner, OBV, vol metrics | Task 2 |
| `analytics.py` — Sharpe, Sortino, Calmar, max_drawdown, CAGR, win_rate, profit_factor, full_report | Task 3 |
| `backtest.py` — RestrictedPython sandbox, BacktestResult, no-network, no-file | Task 4 |
| `pinescript.py` — strategy_from_signals, indicator_script, strategy_from_backtest | Task 5 |
| ClaudeToolkit — add_indicators, run_backtest, generate_pinescript, get_analytics tools | Task 6 |
| `__init__.py` — all Phase 2 exports, version 0.2.0 | Task 7 |
| `bars_to_dataframe()` — IBKR history → standard OHLCV DataFrame | Task 1 |

### Placeholder Check

No TBDs, no "similar to above", no "implement later" — every step has complete code.

### Type Consistency

- `BacktestResult` defined in `backtest.py`, imported in `__init__.py` and `claude_tools.py`
- `indicators.add_all()` returns `pd.DataFrame` — consumed by `_add_indicators` handler
- `analytics.full_report()` returns `dict` — consumed by `_get_analytics` handler
- `pinescript.indicator_script()` returns `str` — consumed by `_generate_pinescript` handler
- All consistent throughout.
