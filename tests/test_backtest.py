import numpy as np
import pandas as pd
import pytest


def _crash_mid_flush_child(code, df, conn):
    """Test-only spawn target: simulate an OOM-kill / SIGKILL landing mid-flush.

    Stands in for backtest._execute_in_subprocess (same 3-arg signature) so the
    parent's reader logic can be exercised against a crash that happens *while a
    result is being written*. Writes a valid multiprocessing wire header claiming
    a large body, then only a few body bytes, then dies via os._exit() — leaving
    a *partial* message in the pipe with the writer process gone. That is exactly
    the on-wire state a real crash-during-send produces.

    Uses raw os.write on the connection fd, not conn.send(): conn.send() is
    atomic and can never leave a half-written message, whereas a genuine
    mid-flush crash must. The 4-byte big-endian length prefix is
    multiprocessing.connection's documented wire format. This is deliberately NOT
    strategy code — the sandbox denies os/fd access — it is a trusted module-level
    helper, picklable by the spawn context, used only by the test below.
    """
    import os
    import struct

    fd = conn.fileno()
    os.write(fd, struct.pack("!i", 50_000_000))  # header: claim a 50MB body...
    os.write(fd, b"partial")  # ...but send only 7 bytes of it
    os._exit(137)  # die mid-message, as an OOM-kill / external SIGKILL would


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
    from ibkr_core_mcp.backtest import BacktestResult, run_backtest
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


# ---------------------------------------------------------------------------
# Safety boundary tests
# ---------------------------------------------------------------------------

def test_code_length_limit_raises(ohlcv):
    from ibkr_core_mcp.backtest import _MAX_CODE_LEN, BacktestSyntaxError, run_backtest
    too_long = "x = 1\n" * (_MAX_CODE_LEN // 6 + 1)
    with pytest.raises(BacktestSyntaxError, match="character limit"):
        run_backtest(too_long, ohlcv)


def test_missing_signal_column_raises(ohlcv):
    """Strategy that never sets df['signal'] must raise, not silently return wrong metrics."""
    from ibkr_core_mcp.backtest import BacktestRuntimeError, run_backtest
    with pytest.raises(BacktestRuntimeError, match="signal"):
        run_backtest("# no signal set", ohlcv)


def test_sandbox_cannot_mutate_shared_pd_namespace(ohlcv):
    """Strategy code must not be able to poison the shared pd/np SimpleNamespace."""
    from ibkr_core_mcp.backtest import BacktestRuntimeError, run_backtest
    # Attempt to overwrite pd.DataFrame — _write_guard should block this
    code = "pd.DataFrame = None\ndf['signal'] = 0"
    with pytest.raises((BacktestRuntimeError, TypeError)):
        run_backtest(code, ohlcv)


def test_sandbox_cannot_import_os(ohlcv):
    """import os is transformed by RestrictedPython but __import__ is not in sandbox namespace."""
    from ibkr_core_mcp.backtest import BacktestRuntimeError, run_backtest
    code = "import os\ndf['signal'] = 0"
    with pytest.raises(BacktestRuntimeError, match="__import__"):
        run_backtest(code, ohlcv)


def test_sandbox_blocks_dataframe_eval(ohlcv):
    """df.eval() runs pandas' OWN expression engine outside RestrictedPython's
    compiled-bytecode boundary — it can reach __globals__/sys.modules/os and
    achieve RCE. Must be blocked at the sandbox's _getattr_ hook.
    See docs/audits/security-audit-2026-07-11.md H-1."""
    from ibkr_core_mcp.backtest import BacktestRuntimeError, run_backtest
    code = (
        "leak = df.eval(\"@df.__init__.__func__.__globals__['sys'].modules['os'].popen('id').read()\")\n"
        "df['signal'] = 0\n"
    )
    with pytest.raises(BacktestRuntimeError, match="eval"):
        run_backtest(code, ohlcv)


def test_sandbox_blocks_dataframe_query(ohlcv):
    """df.query() uses the same unsandboxed expression engine as df.eval()."""
    from ibkr_core_mcp.backtest import BacktestRuntimeError, run_backtest
    code = "df.query(\"close > 0\")\ndf['signal'] = 0\n"
    with pytest.raises(BacktestRuntimeError, match="query"):
        run_backtest(code, ohlcv)


def test_sandbox_still_allows_ordinary_dataframe_methods(ohlcv):
    """Denying eval/query must not break normal indicator-style strategy code."""
    from ibkr_core_mcp.backtest import run_backtest
    code = "df['signal'] = (df['close'] > df['close'].rolling(5).mean()).astype(int)"
    result = run_backtest(code, ohlcv)
    assert isinstance(result.total_return, float)


def test_timeout_actually_kills_runaway_process(ohlcv, monkeypatch):
    """A strategy that never returns must be killed, not merely abandoned.

    Regression test for the ThreadPoolExecutor-era bug where Future.cancel()
    could not stop an already-running thread: `while True: pass` would survive
    the timeout and burn CPU in an orphaned thread forever — and could even
    block the whole host process from exiting, since ThreadPoolExecutor
    registers a non-daemon-thread join in its interpreter-shutdown hook.
    If this fix ever regresses back to something unkillable, this test will
    hang instead of failing cleanly — a hang here IS the failure signal.
    """
    import multiprocessing
    import time

    from ibkr_core_mcp import backtest
    from ibkr_core_mcp.backtest import BacktestRuntimeError, run_backtest

    monkeypatch.setattr(backtest, "_EXEC_TIMEOUT", 0.5)
    monkeypatch.setattr(backtest, "_KILL_GRACE_S", 0.2)

    start = time.monotonic()
    with pytest.raises(BacktestRuntimeError, match="timed out"):
        run_backtest("while True: pass", ohlcv)
    elapsed = time.monotonic() - start

    assert elapsed < 5.0, (
        f"took {elapsed:.1f}s — kill sequence did not terminate the process promptly"
    )
    assert multiprocessing.active_children() == [], "runaway strategy process was not cleaned up"


def test_large_result_does_not_false_timeout():
    """A fast strategy returning a large DataFrame must not be misreported as timed out.

    Regression test for a pipe-deadlock bug: a multiprocessing.Queue's child-side
    feeder thread blocks the child's actual process exit until every put() payload
    is fully flushed through the OS pipe. The previous implementation called
    process.join(_EXEC_TIMEOUT) *before* draining the queue — for a result
    DataFrame larger than the OS pipe buffer (commonly ~64KB), the feeder thread
    would block on write() (since nothing was reading yet), which blocked the
    child from exiting, so join() never observed the child as exited no matter how
    fast the strategy itself computed — producing a false "timed out" error even
    for a near-instant strategy. Uses the real (unpatched) default _EXEC_TIMEOUT
    so this reproduces the exact failure mode reported against production code.
    """
    import time

    from ibkr_core_mcp.backtest import run_backtest

    n = 50_000  # ~2MB pickled — comfortably past any common OS pipe buffer size
    np.random.seed(1)
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    high = close + np.random.uniform(0.1, 1.0, n)
    low = close - np.random.uniform(0.1, 1.0, n)
    open_ = close + np.random.randn(n) * 0.2
    volume = np.random.randint(500_000, 2_000_000, n).astype(float)
    idx = pd.date_range("2025-01-01", periods=n, freq="min")
    big_df = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx
    )

    start = time.monotonic()
    result = run_backtest("df['signal'] = 1", big_df)  # trivial, near-instant strategy
    elapsed = time.monotonic() - start

    assert isinstance(result.total_return, float)
    assert elapsed < 8.0, (
        f"took {elapsed:.1f}s — a fast strategy with a large result should complete in "
        "well under the default _EXEC_TIMEOUT (10s), not stall on a pipe deadlock"
    )


def test_crash_during_flush_does_not_hang(ohlcv, monkeypatch):
    """A child that dies mid-flush must be detected promptly, never hang forever.

    Regression test for a hang found in code review of 23c03be. That fix switched
    the reader to Queue.get(timeout=...), but once the first bytes of a result are
    readable, recv()/_recv_bytes runs with NO timeout. If the child died part-way
    through sending a large result (e.g. an over-allocating strategy the OS
    OOM-kills), the parent's own still-open write-fd kept the pipe from ever
    signalling EOF, so recv() blocked FOREVER — unbounded, immune to _EXEC_TIMEOUT.
    Strictly worse than the pre-23c03be false-timeout it replaced: no exception,
    ever, versus a wrong-but-bounded one.

    The fix (raw Pipe + parent closes its write-fd + wait([reader, sentinel]))
    turns the same event into a prompt EOF/OSError and a clean crash report.
    _EXEC_TIMEOUT is left at its 10s default on purpose so a pass here proves
    detection is fast (via EOF/sentinel), not merely "eventually times out".

    If the fix ever regresses to the unbounded hang, this test hangs rather than
    failing cleanly — a hang here IS the failure signal (run under a hang guard).
    """
    import multiprocessing
    import time

    from ibkr_core_mcp import backtest
    from ibkr_core_mcp.backtest import BacktestRuntimeError, run_backtest

    monkeypatch.setattr(backtest, "_execute_in_subprocess", _crash_mid_flush_child)

    start = time.monotonic()
    with pytest.raises(BacktestRuntimeError, match="exited unexpectedly"):
        run_backtest("df['signal'] = 1", ohlcv)
    elapsed = time.monotonic() - start

    assert elapsed < 3.0, (
        f"took {elapsed:.1f}s — a crash-during-flush must be detected promptly via the "
        "child's death, not by waiting out _EXEC_TIMEOUT (10s)"
    )
    assert multiprocessing.active_children() == [], "crashed strategy process was not reaped"
