"""Security constitution §4 — strategy code cannot read or write the filesystem, spawn
processes, or reach the network, and what it can touch is a frozen, tested allowlist.

Every probe here was run against the sandbox as it stood on 2026-09-13 and SUCCEEDED
(docs/audits/security-architecture-audit-2026-09-13.md, A1/A2): `df.style
.from_custom_template(dir, file)` rendered any file through jinja2 and the un-redacted
runtime-error channel carried it back to the model; `df.to_csv(path, header=False)` wrote
attacker-chosen bytes to any path as the operator; `df.to_clipboard()` spawned `pbcopy`;
`df.apply("to_csv", args=(path,))` reached a writer by name through pandas' own
`getattr`. The two-name denylist (`eval`, `query`) could not see any of it.

The fixes are an attribute *allowlist* for pandas/numpy objects, a name check on the
string-function argument of `apply`/`agg`/`transform`, and a capped, single-line error
channel. These tests hold each of those closed.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ibkr_core_mcp.backtest import _SAFE_NP, _SAFE_PD, build_sandbox, run_backtest
from ibkr_core_mcp.exceptions import BacktestRuntimeError

pytestmark = pytest.mark.security

_CANARY = "SECRET-CANARY-42"


@pytest.fixture
def ohlcv():
    n = 60
    rng = np.random.default_rng(0)
    close = 100 + np.cumsum(rng.standard_normal(n))
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 1000.0},
        index=idx,
    )


@pytest.fixture
def canary(tmp_path):
    path = tmp_path / "canary.txt"
    path.write_text(_CANARY + "\n")
    return path


def _blocked(code: str, ohlcv: pd.DataFrame) -> str:
    """Run `code`; return the sandbox's error text, asserting it did raise."""
    with pytest.raises(BacktestRuntimeError) as info:
        run_backtest(code, ohlcv)
    return str(info.value)


# ── Reads ─────────────────────────────────────────────────────────────────────


def test_strategy_cannot_read_a_file_through_the_styler_template_loader(ohlcv, canary):
    """A1: `Styler.from_custom_template` builds a jinja2 FileSystemLoader on any directory."""
    code = (
        f"cls = df.style.from_custom_template({str(canary.parent)!r}, {canary.name!r})\n"
        "raise ValueError(cls(df).to_html())\n"
    )
    text = _blocked(code, ohlcv)
    assert _CANARY not in text
    assert "style" in text


# ── Writes ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("writer", ["to_csv", "to_pickle", "to_json", "to_parquet", "to_html"])
def test_strategy_cannot_write_a_file_through_a_dataframe_writer(ohlcv, tmp_path, writer):
    """A2: every `to_*` writer takes a path and runs with the operator's uid."""
    target = tmp_path / f"written.{writer}"
    code = f"pd.DataFrame({{'a': ['echo pwned >> ~/.zshrc']}}).{writer}({str(target)!r})\ndf['signal'] = 0\n"
    text = _blocked(code, ohlcv)
    assert not target.exists()
    assert writer in text


def test_strategy_cannot_write_a_file_through_a_numpy_array(ohlcv, tmp_path):
    target = tmp_path / "written.bin"
    code = f"df['close'].to_numpy().tofile({str(target)!r})\ndf['signal'] = 0\n"
    text = _blocked(code, ohlcv)
    assert not target.exists()
    assert "tofile" in text


def test_strategy_cannot_reach_the_clipboard(ohlcv):
    """`to_clipboard` spawns `pbcopy` — a subprocess from inside the sandbox."""
    text = _blocked("pd.DataFrame({'a': ['x']}).to_clipboard()\ndf['signal'] = 0\n", ohlcv)
    assert "to_clipboard" in text


# ── pandas' own getattr: string-named functions ───────────────────────────────


_STRING_FUNC_FORMS = {
    "df.apply": "df.apply('to_csv', path_or_buf={p!r})",
    "df.agg": "df.agg('to_csv', path_or_buf={p!r})",
    "df.transform": "df.transform('to_csv', path_or_buf={p!r})",
    "series.apply": "df['close'].apply('to_csv', args=({p!r},))",
    "series.agg": "df['close'].agg('to_csv', path_or_buf={p!r})",
    "series.transform": "df['close'].transform('to_csv', path_or_buf={p!r})",
    "df.pipe": "df.pipe(pd.DataFrame.to_csv, {p!r})",
}


@pytest.mark.parametrize("form", sorted(_STRING_FUNC_FORMS))
def test_a_function_named_by_string_or_class_cannot_reach_a_denied_method(ohlcv, tmp_path, form):
    """`df.apply("to_csv", path_or_buf=path)` resolves the name with pandas' own unguarded
    getattr, bypassing the sandbox hook entirely; `df.pipe(pd.DataFrame.to_csv, path)` reads
    the writer off the class. Each of these seven forms wrote a file on 2026-09-13 (the
    pandas error they then raise comes *after* the write). The name must face the same
    allowlist whether it arrives as an attribute, a string, or a class attribute."""
    target = tmp_path / f"via_{form}.csv"
    code = _STRING_FUNC_FORMS[form].format(p=str(target)) + "\ndf['signal'] = 0\n"
    text = _blocked(code, ohlcv)
    assert not target.exists()
    assert "to_csv" in text


def test_a_named_aggregation_keyword_faces_the_allowlist_too(ohlcv):
    """`Series.agg(out="to_csv")` is pandas named aggregation: every keyword value is a
    function name resolved with pandas' own getattr. Found by probe after the first fix —
    no path can travel that way, so nothing was written, but the name reached the writer."""
    text = _blocked("r = df['close'].agg(out='to_csv')\nraise ValueError(repr(r))\n", ohlcv)
    assert "to_csv" in text and "close" not in text  # the allowlist message, not the CSV text


def test_a_string_named_function_may_still_name_an_allowed_method(ohlcv):
    """The guard checks names, it does not ban strings: `agg("mean")` is ordinary pandas."""
    code = "m = df['close'].agg('mean')\nlst = df[['close', 'volume']].agg(['mean', 'std'])\ndf['signal'] = (df['close'] > m).astype(int)\n"
    result = run_backtest(code, ohlcv)
    assert isinstance(result.total_return, float)


# ── The error channel ─────────────────────────────────────────────────────────


def test_runtime_error_text_is_single_line_and_capped(ohlcv):
    """The runtime-error string is returned to the model un-redacted so it can fix its own
    code. That channel must not be a bulk exfiltration path: one line, bounded length."""
    payload = ("line of secret material\n" * 60).strip()  # ~1,400 chars, under the 4,096 code limit
    text = _blocked(f"raise ValueError({payload!r})\n", ohlcv)
    assert "\n" not in text
    assert len(text) <= 400


# ── Frozen exposure ───────────────────────────────────────────────────────────


def test_sandbox_globals_are_exactly_the_documented_set(ohlcv):
    """A new name handed to strategies is a new capability; it must be added here on purpose."""
    expected = {
        "_write_",
        "_getattr_",
        "_getitem_",
        "_getiter_",
        "pd",
        "np",
        "float",
        "int",
        "abs",
        "range",
        "len",
        "df",
    }
    from RestrictedPython import safe_globals

    keys = set(build_sandbox(ohlcv)) - set(safe_globals)
    assert keys == expected


def test_safe_pandas_namespace_is_exactly_the_documented_set():
    assert set(vars(_SAFE_PD)) == {"DataFrame", "Series", "concat", "to_datetime", "isna", "notna", "NaT", "NA"}


def test_safe_numpy_namespace_has_no_io_or_loading_functions():
    names = set(vars(_SAFE_NP))
    assert not any(
        n.startswith(("load", "save", "from", "gen")) or n in {"memmap", "fromfile", "tofile"} for n in names
    )
    assert names == {
        "array", "zeros", "ones", "nan", "inf", "where", "isnan", "isinf", "mean", "std", "sum",
        "cumsum", "cumprod", "diff", "log", "log2", "exp", "sqrt", "abs", "maximum", "minimum",
        "clip", "percentile", "arange", "linspace", "sign", "floor", "ceil", "round", "argmax", "argmin",
    }  # fmt: skip


# ── The allowlist must not break real strategies ──────────────────────────────


def test_ordinary_indicator_strategies_still_run(ohlcv):
    """Guard against the allowlist being tightened past what documented strategies use:
    rolling/ewm/shift/diff/clip/where/loc/astype/cumsum/np.where/pct_change/std/max/min."""
    code = """
c = df['close']
sma = c.rolling(5).mean()
ema = c.ewm(span=5, adjust=False).mean()
delta = c.diff()
gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
rsi = 100 - 100 / (1 + gain / loss.replace(0, float('nan')))
ret = c.pct_change().fillna(0)
vol = ret.rolling(10).std()
hi = df['high'].rolling(10).max()
lo = df['low'].rolling(10).min()
tr = pd.concat([df['high'] - df['low'], (df['high'] - c.shift(1)).abs(), (df['low'] - c.shift(1)).abs()], axis=1).max(axis=1)
atr = tr.rolling(14).mean()
obv = (np.sign(delta.fillna(0)) * df['volume']).cumsum()
signal = np.where(c > sma, 1, np.where(c < sma, -1, 0))
df['signal'] = pd.Series(signal, index=df.index).where(rsi.notna(), 0).astype(int)
df.loc[c > hi.shift(1), 'signal'] = 1
n = len(df)
last = c.iloc[-1]
cols = df.columns
arr = c.to_numpy()
peak = arr.max()
"""
    result = run_backtest(code, ohlcv)
    assert isinstance(result.total_return, float)
