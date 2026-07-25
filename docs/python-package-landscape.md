# Python Package Landscape — Charting, Quant & Stats

Audit of where `ibkr_core_mcp` (and its consumer, `claudia_ui`) sits relative to the
common Python charting / quant-finance / statistics ecosystem. **Documentation only —
no packages listed here have been added to `pyproject.toml`.** Verified by grepping
`ibkr_core_mcp/`, `docs/`, `pyproject.toml`, `.venv/`, and `claudia_ui/pyproject.toml`
on 2026-07-19; re-verified 2026-07-25 after `claudia_ui` migrated from Chainlit to
Panel. Nothing below is assumed from memory.

## Why this doc exists, and why it doesn't install anything

`plotly` was added to this package early on, never wired to any tool, and later
**removed** for exactly that reason (`CHANGELOG.md`: "`plotly` removed from package
dependencies — was never used"; `docs/plans/2026-06-27-publication-readiness.md`: "was
never used, no claudia code referenced it"). `execute()`'s return type was tightened
from `tuple[str, Figure | None]` to `tuple[str, None]` at the same time, since every
one of the 42+ tool handlers returned `None` for the figure slot.

That's the standing precedent for this codebase: a dependency is added in the same PR
as the code that uses it, not ahead of it. This doc is the inventory that makes future
"should we add X" decisions fast — it doesn't pre-empt them.

## Current state: charting lives in `claudia_ui`, on Bokeh — not in this package

`ibkr_core_mcp` still declares **no** charting library, and none are importable in its
`.venv`. That part is unchanged: this package produces data, not figures.

What changed on 2026-07-24/25 is the consumer. `claudia_ui` migrated from Chainlit to
**Panel**, and in doing so it acquired a real charting stack:

- `claudia_ui/pyproject.toml` declares `panel>=1.9` **and** `bokeh>=3.7` — the latter as
  a deliberate direct dependency, not a transitive one, because `claudia/panel_chart.py`
  imports `bokeh.plotting` itself.
- `claudia/panel_chart.py` renders a **Bokeh candlestick pane** (a high/low `segment` for
  the wicks plus two `vbar` glyphs, teal up / red down, partitioned on `close >= open`),
  fed by the Drive parquet cache with an IBKR fetch on miss.

So the seam question is settled by fact rather than prediction: **the chart surface is
`claudia_ui`, and its rendering engine is Bokeh via Panel.** A chart-producing tool in
this package would still not return a figure object — `execute()`'s return type was
tightened to `tuple[str, None]` (`ibkr_core_mcp/claude_tools.py:1051`) precisely because
every handler returns `None` in the figure slot. `claudia_ui` reads the cached OHLCV
DataFrame and builds the figure on its own side.

## A. General-purpose visualization

| Package | Status | Notes |
|---|---|---|
| Bokeh | **Installed in `claudia_ui`** (not here) | `bokeh>=3.7`, a direct dependency of the consumer. Backs the candlestick pane in `claudia/panel_chart.py`. Panel's native rendering engine, so it needs no bridging element. |
| Matplotlib | Not installed | No static-plot rendering anywhere in the pipeline. Panel *can* host it via `pn.pane.Matplotlib`, but Bokeh is already the native path. |
| Altair | Not installed | Declarative/Vega-Lite. Panel supports it (`pn.pane.Vega`), but it would be a second charting stack alongside Bokeh for no current gain. |
| Plotly | Not installed (removed) | See history above. Panel supports it via `pn.pane.Plotly`, but the earlier "natural pick" reasoning was based on Chainlit's `cl.Plotly` element and no longer applies — Bokeh now holds that position by virtue of being Panel's native engine and already shipping. |
| ECharts (`pyecharts`) | Not installed | Panel *is* a JS-frontend surface (BokehJS in the browser), so the old "no JS surface to host it" objection is void. It is still unclaimed for the simpler reason that Bokeh already covers the interactivity we need. |
| deck.gl (`pydeck`) | Not installed, not applicable | Geospatial/large-scale WebGL visualization — no geospatial data anywhere in this domain (equities/options trading). |

**Recommendation:** none of these are missing gaps today, and the question is now
narrower than it was. Charting is solved in `claudia_ui` with Bokeh via Panel. If a
further chart is built (e.g. the equity-curve or P&L chart referenced as a "future" item
in `docs/plans/2026-06-27-v2-architecture-plan.md:178`), **extend the existing Bokeh pane
rather than introducing a second charting library** — and build it in `claudia_ui`, since
this package deliberately returns data, never figures. Adding a charting dependency
*here* would repeat the original `plotly` mistake described above.

## B. Technical analysis & financial charting

| Package | Status | What we have instead |
|---|---|---|
| TA-Lib | Not installed | `ibkr_core_mcp/indicators.py` hand-rolls 14 indicators in pandas (SMA, EMA, RSI, MACD, VWAP, Bollinger Bands, ATR, Stochastic, Williams %R, Keltner Channels, OBV, volume SMA/ratio, `add_all`). TA-Lib also requires a compiled C library (not pip-installable standalone on most platforms), which cuts against this package's pure-pip, cross-platform install story. |
| pandas-ta | Not installed | Same coverage overlap as TA-Lib — `indicators.py` already is the "Pythonic pandas extension" role pandas-ta would fill. |
| Lightweight Charts Python | Not installed | No interactive candlestick rendering surface exists (see charting section above — this would live in `claudia_ui`, not here). |
| mplfinance | Not installed | Static OHLC/candlestick plotting — same gap as Lightweight Charts, not currently a product requirement. |

**Recommendation:** skip. `indicators.py` already covers this category's compute side,
and the charting side is blocked on the same "no chart tool exists yet" gap as
Section A. Revisit TA-Lib/pandas-ta only if a specific indicator not in
`indicators.py` is needed and hand-rolling it is more error-prone than the dependency
(TA-Lib's C core matters mainly at very high indicator-call volume, which this
package's per-request tool-call pattern doesn't hit).

## C. Quantitative finance & backtesting

| Package | Status | What we have instead |
|---|---|---|
| Vectorbt | Not installed | `ibkr_core_mcp/backtest.py` is a **subprocess-isolated `RestrictedPython` sandbox** (`run_backtest`) — a deliberate security boundary (untrusted strategy code from Claude/users must not get real filesystem/network access), not a speed-optimization tool. Vectorbt's Numba-vectorized design assumes trusted code; it doesn't provide sandboxing and wouldn't replace the security property `backtest.py` exists for. |
| Backtrader | Not installed | Same conflict: event-driven backtesting frameworks execute arbitrary strategy code directly, no sandbox. `docs/plans/2026-05-22-ibkr-core-mcp-design.md` explicitly scopes the backtest engine's allowed imports (`pandas`, `numpy`, `plotly`) — the RestrictedPython design is intentional, not a placeholder for a "real" backtesting library. |
| Quantstats | Not installed | `ibkr_core_mcp/analytics.py` already implements the performance-metrics subset this project needs: Sharpe, Sortino, max drawdown (+ duration), CAGR, Calmar, win rate, profit factor, avg win/loss ratio, `trade_summary`/`full_report`. Quantstats' main additive value — auto-generated HTML tear sheets — has no consumer today (no notebook/report-viewing surface). |
| PyPortfolioOpt | Not installed | No portfolio-construction/optimization tool exists — current `claude_tools.py` handlers read/report on IBKR positions and analyze historical performance, they don't propose allocations. This is a genuine capability gap, not a duplicate of existing code. |

**Recommendation:** skip Vectorbt/Backtrader (would require reopening the sandboxing
design decision — see `docs/plans/2026-05-24-human-auth-order-security-plan.md` and
the backtest subprocess-isolation history in memory) and skip Quantstats (metrics
already covered, tear-sheet HTML has no viewer). **PyPortfolioOpt is the one real gap**
in this category — flag it if/when a "suggest portfolio weights" or
"optimize allocation" tool is scoped; it wouldn't compete with any existing module.

## D. Statistical analysis & regressions

| Package | Status | Notes |
|---|---|---|
| Statsmodels | Not installed | No OLS/ARIMA/time-series-modeling tool exists. Genuine gap if econometric analysis (e.g. regressing returns against a factor) becomes an actual tool requirement. |
| Arch | Not installed | No volatility-forecasting (GARCH) tool exists. `indicators.py`'s ATR is a simple realized-range measure, not a conditional-volatility model — not a duplicate, just a different, much simpler need. |
| Scikit-learn | Not installed | No ML-based tool exists in `claude_tools.py`. Would only apply if a predictive/classification tool were scoped — nothing today calls for it. |
| Prophet | Not installed | No time-series forecasting tool exists. Heaviest dependency of this group (pulls in Stan/cmdstanpy) — would need a concrete forecasting tool to justify the install cost. |

**Recommendation:** skip all four for now — none have a consuming tool, and the
project's own convention (see `CLAUDE.md`: "Don't add features... beyond what the task
requires") argues against installing statistical libraries speculatively. Statsmodels
and Arch are the most likely to become relevant first, given this is a trading-focused
package (factor regressions, volatility modeling are closer to the domain than generic
ML/forecasting).

## Summary

| Category | Genuine gaps | Duplicative of existing code | Blocked on a missing consumer |
|---|---|---|---|
| Visualization | — | — | Matplotlib, Altair, Plotly, pyecharts, pydeck (no chart tool exists yet) |
| TA & financial charting | — | TA-Lib, pandas-ta (`indicators.py`) | Lightweight Charts, mplfinance (no chart tool exists yet) |
| Quant/backtesting | PyPortfolioOpt | Quantstats (`analytics.py`), Vectorbt/Backtrader (conflict with sandbox design) | — |
| Stats/regressions | Statsmodels, Arch, Scikit-learn, Prophet (no tool consumes any of them yet) | — | — |

**If you want to move on any of these next:** the fastest-to-justify additions are
**Plotly** (paired with a first chart-emitting tool) and **PyPortfolioOpt** (paired
with a portfolio-optimization tool) — both fill a real, currently-empty capability
rather than duplicating `indicators.py`/`analytics.py` or fighting the backtest
sandbox's security model. Add the dependency in the same PR as the tool that uses it,
per the plotly precedent above.
