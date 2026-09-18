"""Proactive per-endpoint pacing — the behaviour three documents already claimed.

`rate_limiter.py` reacted to a 429 and never prevented one. Measured live against the
gateway on 2026-09-16, `get_market_history_paginated` issued chunk requests at **284
requests/minute** against a documented ceiling of 50, and the 120-chunk runaway guard
would have completed in ~25 seconds — 2.4x the per-minute allowance inside half a minute.
IBKR's documented answer to that is HTTP 429 plus a fifteen-minute penalty box on the IP,
which applies to every endpoint and not just the one that broke the limit, against a
reactive retry budget of 1 + 2 + 4 = 7 seconds.

Every test here drives an injected clock, so nothing sleeps for real.
"""

import pytest


def _pacer(**kw):
    """EndpointPacer on a fake clock: time only advances when the pacer sleeps."""
    from ibkr_core_mcp.rate_limiter import EndpointPacer

    state = {"now": 1_000.0}
    slept = []

    def clock():
        return state["now"]

    def sleep(seconds):
        slept.append(seconds)
        state["now"] += seconds

    pacer = EndpointPacer(clock=clock, sleep=sleep, **kw)
    return pacer, state, slept


def test_history_is_held_to_fifty_requests_per_minute():
    """The limit that the live measurement broke. IBKR publishes
    "/iserver/marketdata/history | GET | 10 req/sec or 50 req/min"
    https://www.interactivebrokers.com/docs/web-api/v1/pacing-limitations

    Fifty requests inside the window are free; the fifty-first must wait for the
    oldest to age out, and not a moment longer.
    """
    pacer, state, _slept = _pacer()
    start = state["now"]

    for _ in range(50):
        pacer.acquire("/iserver/marketdata/history")

    # The per-second limit spaces these out, but none of them waits on the minute rule.
    assert state["now"] - start < 60.0
    at_fiftieth = state["now"]

    pacer.acquire("/iserver/marketdata/history")

    assert state["now"] >= start + 60.0, "51st request must wait out the 60s window"
    assert state["now"] - at_fiftieth == pytest.approx(start + 60.0 - at_fiftieth)


def test_history_also_respects_the_ten_per_second_limit():
    """Two limits are published for this endpoint and both bind. Ten in a second are
    free; the eleventh waits ~1s, nowhere near the 60s the minute rule would impose."""
    pacer, state, _slept = _pacer()
    start = state["now"]

    for _ in range(11):
        pacer.acquire("/iserver/marketdata/history")

    elapsed = state["now"] - start
    assert 0.9 <= elapsed <= 1.1, f"expected ~1s of pacing, got {elapsed}"


def test_an_unlisted_endpoint_gets_the_documented_global_limit():
    """ "Any endpoint not listed in the table below follows the global restriction of
    10 requests per second." — same page."""
    pacer, state, _slept = _pacer()
    start = state["now"]

    for _ in range(11):
        pacer.acquire("/portfolio/U123/positions/0")

    assert 0.9 <= state["now"] - start <= 1.1


def test_path_parameters_match_the_table_entry():
    """The published table writes placeholders (`/fyi/notifications/{notificationId}`)
    while the client sends real ids. Without placeholder matching every such call would
    silently fall through to the laxer global limit."""
    pacer, state, _slept = _pacer()
    start = state["now"]

    pacer.acquire("/fyi/notifications/12345")
    pacer.acquire("/fyi/notifications/67890")

    assert state["now"] - start == pytest.approx(1.0), "1 req/sec applies to both ids"


def test_separate_endpoints_do_not_share_a_budget():
    """A tickle must not be delayed by a burst of history calls."""
    pacer, state, _slept = _pacer()

    for _ in range(10):
        pacer.acquire("/iserver/marketdata/history")
    before = state["now"]
    pacer.acquire("/tickle")

    assert state["now"] == before, "unrelated endpoint paid for another's budget"


def test_a_window_that_has_expired_costs_nothing():
    """Pacing is a sliding window, not a fixed one: calls spaced beyond the window
    never wait."""
    pacer, state, slept = _pacer()

    pacer.acquire("/iserver/account/orders")  # 1 req/5 secs
    state["now"] += 5.0
    pacer.acquire("/iserver/account/orders")

    assert slept == [], "a request outside the window must not be paced"


def test_orders_endpoint_waits_its_documented_five_seconds():
    pacer, _state, slept = _pacer()

    pacer.acquire("/iserver/account/orders")
    pacer.acquire("/iserver/account/orders")

    assert slept == [pytest.approx(5.0)]


def test_a_wait_beyond_the_cap_warns_and_proceeds_rather_than_hanging():
    """`/pa/summary` is 1 req/15 mins. Blocking a tool call for fifteen minutes would
    be worse than the 429 this is trying to avoid, and raising would fail a request
    that succeeds today. The honest behaviour is to proceed and say so — the caller
    learns it is over the limit without losing the call."""
    pacer, _state, slept = _pacer(max_wait=65.0)

    pacer.acquire("/pa/summary")
    with pytest.warns(UserWarning, match="1 request per 900"):
        pacer.acquire("/pa/summary")

    assert slept == [], "must not block for the full 15-minute window"


def test_the_limits_table_is_the_only_copy():
    """API-03 was a stale row in a prose table duplicating the real values: IBKR changed
    /iserver/marketdata/history from "5 concurrent requests" to "10 req/sec or 50
    req/min", and the 2026-08-11 link repointing updated the citation URL without
    re-reading the page. One executable table cannot drift from itself, so the prose
    copy is gone — this test fails if it comes back."""
    import inspect

    from ibkr_core_mcp import rate_limiter

    source = inspect.getsource(rate_limiter)
    assert "5 concurrent requests" not in source, "the stale value is back"
    # The old prose table listed each endpoint with a literal limit beside it.
    assert "1 req/sec\n" not in source, "a second, non-executable copy of the table exists"
    assert rate_limiter.ENDPOINT_LIMITS[("/iserver/marketdata/history", "GET")] == (
        (10, 1.0),
        (50, 60.0),
    )


def test_every_documented_endpoint_is_reachable_by_the_matcher():
    """A table entry nobody can match is dead weight, and the placeholder rewriting is
    exactly the part most likely to be wrong. Each key must match a concrete path built
    from itself."""
    from ibkr_core_mcp.rate_limiter import ENDPOINT_LIMITS, EndpointPacer

    pacer = EndpointPacer()
    for (pattern, _method), limits in ENDPOINT_LIMITS.items():
        concrete = "/".join("7" if seg.startswith("{") else seg for seg in pattern.split("/"))
        assert pacer.limits_for(concrete) == limits, f"{pattern} unreachable via {concrete}"


def test_a_query_string_does_not_let_a_path_escape_its_limit():
    """`get_live_orders` sends `/iserver/account/orders?force=true` followed by
    `/iserver/account/orders` — IBKR's documented subscription warmup. Matching the
    raw string would charge the first to the global 10/sec default and only the second
    to the endpoint's 1-req/5-secs budget, so the pair would slip through at exactly the
    rate the limit exists to prevent. The query string is not part of the endpoint.
    """
    from ibkr_core_mcp.rate_limiter import EndpointPacer

    pacer = EndpointPacer()

    assert pacer.limits_for("/iserver/account/orders?force=true") == ((1, 5.0),)
    assert pacer.limits_for("/iserver/marketdata/history?conid=265598&period=1d") == (
        (10, 1.0),
        (50, 60.0),
    )


def test_the_warmup_pair_shares_one_budget():
    """Both halves of the warmup must land in the same bucket, not merely match."""
    pacer, _state, slept = _pacer()

    pacer.acquire("/iserver/account/orders?force=true")
    pacer.acquire("/iserver/account/orders")

    assert slept == [pytest.approx(5.0)]


def test_expiry_frees_the_budget_rather_than_merely_zeroing_the_wait():
    """A sliding window must DROP old calls, not just compute a non-positive wait.

    `test_a_window_that_has_expired_costs_nothing` does not prove this: with a
    1-request limit, `history[0] + window - now` is already <= 0 at the boundary, so
    an implementation that never expires anything passes it. Mutation testing caught
    exactly that — the "window never expires" mutant survived the whole file.

    The difference shows up only once a full budget has been spent, the window has
    passed, and a second full budget is spent inside the new window. With expiry the
    next call waits; without it the deque still leads with a timestamp from the first
    batch, every wait computes negative, and the limit stops applying at all — while
    the deque grows without bound.
    """
    pacer, state, slept = _pacer()

    for _ in range(10):  # fills the 10-per-second bucket at t0
        pacer.acquire("/iserver/marketdata/history")
    assert slept == [], "ten inside one second are free"

    state["now"] += 2.0  # the whole window passes

    for _ in range(10):  # a fresh budget, all free
        pacer.acquire("/iserver/marketdata/history")
    assert slept == [], "the expired batch must not still be charged"

    before = state["now"]
    pacer.acquire("/iserver/marketdata/history")

    assert state["now"] > before, "11th call in the new window must wait"
    assert slept == [pytest.approx(1.0)]


def test_spent_calls_do_not_accumulate_for_ever():
    """The same defect seen as a leak: a long-lived client must not grow a deque entry
    per request for the life of the process.

    The bound is each limit's own count, not a small constant — a first version of this
    test asserted <= 2 and failed against correct code, because calls two seconds apart
    still sit inside history's SIXTY-second window, where thirty of them legitimately
    coexist. What must never happen is a deque outgrowing the limit it enforces.
    """
    pacer, state, _slept = _pacer()

    for _ in range(200):
        pacer.acquire("/iserver/marketdata/history")
        state["now"] += 2.0

    for (_key, count, window), history in pacer._calls.items():
        assert len(history) <= count, (
            f"limit of {count} per {window}s retained {len(history)} timestamps "
            "after 200 calls — expired entries are never dropped"
        )


def test_two_verbs_on_one_path_pool_their_limits_deliberately():
    """`ENDPOINT_LIMITS` is keyed by (path, method), as IBKR's table is; the pacer keys its
    budget by PATH, and until 2026-09-17 did so silently — the first verb listed supplied
    the limits and any other verb's were dropped (API-R11).

    Sharing is the conservative direction: if IBKR counts a path's verbs separately, a
    pooled budget costs at most one needless wait; if it counts them together, separate
    budgets earn the fifteen-minute penalty box. So one bucket per path is the decision,
    and every listed verb's limits apply to it — the stricter window binds.
    """
    from unittest.mock import patch

    from ibkr_core_mcp import rate_limiter

    probe = {("/probe/{id}", "GET"): ((1, 1.0),), ("/probe/{id}", "PUT"): ((1, 5.0),)}
    with patch.dict(rate_limiter.ENDPOINT_LIMITS, probe):
        pacer, _state, slept = _pacer()

    assert pacer.limits_for("/probe/7") == ((1, 1.0), (1, 5.0))

    pacer.acquire("/probe/7")
    pacer.acquire("/probe/7")

    assert slept == [5.0], "the stricter verb's window must bind, not the first one listed"
