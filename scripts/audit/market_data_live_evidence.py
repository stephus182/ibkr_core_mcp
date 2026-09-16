"""Live evidence for the market-data path — run against a real authenticated gateway.

Why this exists. API-01 (`1d`/`1min` returning 69.4% of a trading day) was graded Critical
and fixed on 2026-09-16, and its verification was driven against a *stub* that truncates the
way IBKR was measured truncating. A stub encodes what we believe the endpoint does. It
cannot discover that the belief is wrong, which is the failure mode this package keeps
finding. This script asserts the same properties against the real endpoint.

Every check is relative to something the endpoint itself returned, never to a hardcoded bar
count: a live partial session (this runs fine mid-session) would make any absolute
expectation wrong, and that would look like a defect in the code rather than in the test.

Run:
    set -a; source /path/to/.env; set +a
    .venv/bin/python scripts/audit/market_data_live_evidence.py

Results are recorded in docs/audits/live-test-log.md and summarised in
docs/ibkr-api-behaviors-reference.md.
"""

from __future__ import annotations

import itertools
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ibkr_core_mcp import Config, IBKRClient
from ibkr_core_mcp.client import _MAX_CHUNKS, _MAX_POINTS, _parse_period_days

CONID_AAPL = 265598

_BAR_SECONDS = {"1min": 60, "2min": 120, "5min": 300, "15min": 900, "1h": 3600, "1d": 86400, "1w": 604800}


def _stamps(payload: dict[str, Any]) -> list[int]:
    return sorted(b["t"] for b in (payload.get("data") or []) if b.get("t") is not None)


def _span_days(stamps: list[int]) -> float:
    return (stamps[-1] - stamps[0]) / 86_400_000 if len(stamps) > 1 else 0.0


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%d %H:%M")


def _modal_interval(stamps: list[int]) -> int:
    """Most common gap between consecutive bars, in seconds — the bar size actually served."""
    if len(stamps) < 3:
        return 0
    deltas = [(b - a) // 1000 for a, b in itertools.pairwise(stamps)]
    return int(Counter(deltas).most_common(1)[0][0])


def check_single_call_cap(client: IBKRClient) -> list[int]:
    """The 1000-point cap, asserted against the endpoint rather than quoted from the docs."""
    print("\n" + "=" * 78)
    print("1. The 1000-point cap on a single un-paginated call")
    print("=" * 78)
    raw = client.get_market_history(CONID_AAPL, period="1d", bar="1min", outside_rth=True)
    stamps = _stamps(raw)
    print(f"   1d/1min outsideRth=true -> {len(stamps)} bars, cap is {_MAX_POINTS}")
    print(f"   window {_iso(stamps[0])} .. {_iso(stamps[-1])}  ({_span_days(stamps) * 24:.1f} h)")
    verdict = "AT THE CAP" if len(stamps) == _MAX_POINTS else "under the cap"
    print(f"   -> {verdict}")
    return stamps


def check_pagination_beats_a_single_call(client: IBKRClient, raw_stamps: list[int]) -> None:
    """The API-01 property, live: paginating must be a SUPERSET of one raw call.

    This is the check a stub cannot make. It needs no expected bar count — the raw call
    supplies the baseline, so a partial trading session cannot skew it.
    """
    print("\n" + "=" * 78)
    print("2. API-01 live: paginated 1d/1min vs a single raw call")
    print("=" * 78)
    paged = client.get_market_history_paginated(CONID_AAPL, period="1d", bar="1min", outside_rth=True)
    paged_stamps = _stamps(paged)
    raw_set, paged_set = set(raw_stamps), set(paged_stamps)
    missing = raw_set - paged_set
    print(f"   raw single call : {len(raw_stamps):>5} bars  {_iso(raw_stamps[0])} .. {_iso(raw_stamps[-1])}")
    print(f"   paginated       : {len(paged_stamps):>5} bars  {_iso(paged_stamps[0])} .. {_iso(paged_stamps[-1])}")
    print(f"   bars the raw call had and pagination lost : {len(missing)}")
    print(f"   extra bars pagination recovered           : {len(paged_set - raw_set)}")
    print(f"   -> {'PASS' if not missing and len(paged_stamps) >= len(raw_stamps) else 'FAIL'}")


def check_matrix(client: IBKRClient) -> None:
    """Coverage, bar-size fidelity, duplicates and truncation flags across real combinations."""
    print("\n" + "=" * 78)
    print("3. Coverage / fidelity matrix (outsideRth=false, i.e. regular session)")
    print("=" * 78)
    print(
        f"   {'request':>12} {'chunks':>7} {'bars':>7} {'span':>9} {'asked':>7} {'cover':>7} "
        f"{'bar_ok':>7} {'dupes':>6} {'flag':>5}"
    )
    combos = [
        ("1d", "1min"),
        ("2d", "1min"),
        ("5d", "5min"),
        ("30d", "5min"),
        ("30d", "1h"),
        ("1y", "1d"),
        ("5y", "1w"),
    ]
    for period, bar in combos:
        calls: list[float] = []
        real_get = client._get

        def counting(
            path: str,
            params: dict[str, Any] | None = None,
            _real: Any = real_get,
            _calls: list[float] = calls,
            **kw: Any,
        ) -> Any:
            if path == "/iserver/marketdata/history":
                _calls.append(time.monotonic())
            return _real(path, params, **kw)

        client._get = counting  # type: ignore[method-assign]
        try:
            out = client.get_market_history_paginated(CONID_AAPL, period=period, bar=bar, outside_rth=False)
        finally:
            client._get = real_get  # type: ignore[method-assign]

        stamps = _stamps(out)
        if not stamps:
            print(f"   {period + '/' + bar:>12} {len(calls):>7} {'NO DATA':>7}")
            continue
        asked = _parse_period_days(period) or 0.0
        span = _span_days(stamps)
        modal = _modal_interval(stamps)
        expected = _BAR_SECONDS.get(bar, 0)
        # Intraday bars only trade during the session, so the modal gap is the bar size;
        # for daily/weekly the modal gap is one calendar step, which weekends distort.
        bar_ok = "yes" if modal == expected else f"{modal}s"
        dupes = len(stamps) - len(set(stamps))
        flag = "yes" if out.get("ibkr_core_warning") else "-"
        print(
            f"   {period + '/' + bar:>12} {len(calls):>7} {len(stamps):>7} {span:>8.1f}d "
            f"{asked:>6.0f}d {span / asked:>6.0%} {bar_ok:>7} {dupes:>6} {flag:>5}"
        )


def check_starttime_semantics(client: IBKRClient) -> None:
    """`startTime` is the END of the window, and direction=1 does not work.

    Documented in docs/ibkr-api-behaviors-reference.md from a 2026-08-05 measurement on a
    different conid. Re-measured here because a behaviour recorded once is a claim about
    that day.
    """
    print("\n" + "=" * 78)
    print("4. startTime semantics, re-measured")
    print("=" * 78)
    anchor = "20260601-00:00:00"
    base = {"conid": CONID_AAPL, "period": "10d", "bar": "1d", "outsideRth": "false"}
    variants: list[tuple[str, dict[str, Any]]] = [
        ("startTime omitted", {}),
        (f"startTime={anchor}", {"startTime": anchor}),
        (f"startTime={anchor} direction=-1", {"startTime": anchor, "direction": -1}),
        (f"startTime={anchor} direction=1", {"startTime": anchor, "direction": 1}),
    ]
    for label, extra in variants:
        res = client._get("/iserver/marketdata/history", {**base, **extra})
        if isinstance(res, dict) and res.get("error"):
            print(f"   {label:>38} -> ERROR: {res['error']}")
            continue
        stamps = _stamps(res if isinstance(res, dict) else {})
        if not stamps:
            print(f"   {label:>38} -> no bars")
            continue
        print(f"   {label:>38} -> {len(stamps):>3} bars  {_iso(stamps[0])} .. {_iso(stamps[-1])}")


def main() -> None:
    """Run every live market-data check and print the evidence."""
    client = IBKRClient(Config.from_env())
    status = client.get_auth_status()
    print(
        f"gateway authenticated: {status.get('authenticated')}   "
        f"now: {datetime.now(UTC):%Y-%m-%d %H:%M} UTC   _MAX_CHUNKS={_MAX_CHUNKS}"
    )
    raw_stamps = check_single_call_cap(client)
    check_pagination_beats_a_single_call(client, raw_stamps)
    check_matrix(client)
    check_starttime_semantics(client)


if __name__ == "__main__":
    main()
