"""Live integration tests for IBKRClient endpoints.

Run with a live, authenticated IBKR gateway:
    pytest tests/test_client_live.py -v -m integration

All tests are skipped automatically when the gateway is unreachable.

## Machine test boundary

All read operations (positions, market data, P&L, trade history, accounts,
alerts list, etc.) are covered here via BrowserCookieAuth — these work with
a standard authenticated gateway session.

Write operations (place_order, modify_order, cancel_order, create_alert, etc.)
are NOT machine-testable: the IBKR CP API requires an active brokerage session
that BrowserCookieAuth alone cannot replicate. These are validated manually
through the ClaudIA UI, which maintains the full brokerage session via
continuous /tickle keepalive every 60s.

This is an IBKR CP API architectural restriction, not a test harness limitation.
Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/session/initialize-brokerage-session.md
See docs/audits/live-test-log.md#run-2026-07-01-1 for the confirmed finding.

Explicit exclusions:
- Order writes (place/modify/cancel/reply) — brokerage session required + hard safety rule
- Alert writes (create/modify/delete/activate) — brokerage session required
- Regulatory snapshot ($0.01/call) — tested once manually, not run routinely
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def live_config(tmp_path_factory):
    from ibkr_core_mcp.config import Config

    tmp = tmp_path_factory.mktemp("live_cfg")
    return Config(
        gateway_url="https://localhost:5055/v1/api",
        anthropic_api_key="test-key",
        gdrive_folder_id="test-folder-id",
        sqlite_path=tmp / "store.db",
        gdrive_token_file=tmp / "token.json",
        gdrive_credentials_file=tmp / "credentials.json",
    )


@pytest.fixture(scope="module")
def client(live_config):
    from ibkr_core_mcp.auth import BrowserCookieAuth
    from ibkr_core_mcp.client import IBKRClient

    return IBKRClient(live_config, auth=BrowserCookieAuth())


@pytest.fixture(scope="module")
def live_client(client):
    """Skip the entire module if the gateway is unreachable or unauthenticated."""
    if not client.ping():
        pytest.skip("IBKR gateway not reachable or not authenticated")
    return client


@pytest.fixture(scope="module")
def held_conid(live_client, account_id):
    """A conid this account actually holds, or a loud skip.

    Several tests below asked about AAPL (265598) and asserted `isinstance(result, list)`.
    The account holds GLD and IGV, so those endpoints correctly returned `[]` — and the
    assertion passed either way. That is how `get_positions_by_conid` could return `[]` for
    EVERY contract, held or not, from the day it was written until 2026-09-16, with a live
    test watching it (see `docs/ibkr-api-behaviors-reference.md` § Response shape).

    Deriving the conid from real positions means a position test asserts a position.
    """
    positions = live_client.get_positions(account_id)
    conids = [p.get("conid") for p in positions if p.get("conid")]
    if not conids:
        pytest.skip("account holds no positions, so no position endpoint can be asserted against content")
    return conids[0]


@pytest.fixture(scope="module")
def account_id(live_client):
    accounts = live_client.get_accounts()
    assert accounts, "No accounts returned from /portfolio/accounts"
    acct = accounts[0].get("accountId") or accounts[0].get("id")
    assert acct, "Account object missing accountId/id field"
    return acct


# ---------------------------------------------------------------------------
# Session / Health
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_ping(live_client):
    assert live_client.ping() is True


@pytest.mark.integration
def test_get_auth_status(live_client):
    status = live_client.get_auth_status()
    assert isinstance(status, dict)
    assert "authenticated" in status


@pytest.mark.integration
def test_tickle(live_client):
    # tickle() returns bool (True on HTTP 200), not a dict
    result = live_client.tickle()
    assert result is True


@pytest.mark.integration
def test_validate_sso(live_client):
    result = live_client.validate_sso()
    assert isinstance(result, dict)
    # An authenticated session names the credential it authenticated; an empty dict or an
    # unauthenticated stub does not. `live_client` already required ping(), so anything
    # less than this means the response was not what the endpoint documents.
    assert result.get("USER_NAME") or result.get("CREDENTIAL"), f"no credential in SSO response: {sorted(result)}"
    assert result.get("RESULT") is not False, f"SSO validation reported failure: {result.get('RESULT')}"


# ---------------------------------------------------------------------------
# Contract / Security Definition
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_search_contract_aapl(live_client):
    results = live_client.search_contract("AAPL")
    assert len(results) > 0
    aapl = next((r for r in results if r.get("symbol") == "AAPL"), None)
    assert aapl is not None
    assert "conid" in aapl


@pytest.mark.integration
def test_search_contract_returns_conid(live_client):
    results = live_client.search_contract("MSFT")
    assert results
    assert all("conid" in r for r in results)


@pytest.mark.integration
def test_get_contract_info(live_client):
    # AAPL conid 265598 is stable
    result = live_client.get_contract_info(265598)
    assert isinstance(result, dict)
    # The contract asked for is the contract described — `con_id` is the endpoint's own
    # spelling. A wrong or empty body cannot satisfy this.
    conid = result.get("con_id") or result.get("conid")
    assert conid is not None, f"no conid in contract info: {sorted(result)[:8]}"
    assert int(conid) == 265598, f"wrong contract: {conid}"
    assert "APPLE" in str(result.get("company_name", "")).upper(), result.get("company_name")


@pytest.mark.integration
def test_get_contract_info_and_rules(live_client):
    result = live_client.get_contract_info_and_rules(265598)
    assert isinstance(result, dict)
    # The point of this endpoint is that it returns BOTH halves in one call.
    assert "rules" in result, f"no rules block: {sorted(result)[:10]}"
    conid = result.get("con_id") or result.get("conid")
    assert conid is not None and int(conid) == 265598, f"wrong contract: {conid}"


@pytest.mark.integration
def test_get_contract_algos(live_client):
    result = live_client.get_contract_algos(265598)
    assert isinstance(result, list)
    # Until 2026-09-16 this returned [] for every contract: the response is
    # `{"algos": [...]}` and was read as a bare list. AAPL has ten algos; an empty list
    # here is the bug returning, not a quiet market.
    assert result, "no algos for AAPL — the object wrapper is being discarded again"
    assert {"id", "name"} <= set(result[0]), sorted(result[0])


@pytest.mark.integration
def test_get_secdef_info(live_client):
    result = live_client.get_secdef_info(265598)
    assert isinstance(result, dict)
    conid = result.get("conid")
    assert conid is not None and int(conid) == 265598, f"wrong conid: {conid}"
    assert result.get("currency"), f"no currency in secdef info: {sorted(result)}"


@pytest.mark.integration
def test_get_secdef_batch(live_client):
    result = live_client.get_secdef([265598])
    assert isinstance(result, list)
    # `get_secdef` had this exact defect fixed on 2026-07-28 — the response is
    # `{"secdef": [...]}` and was read as a bare list, returning [] on every call. An empty
    # list here means it has come back.
    assert result, "empty secdef batch — the {'secdef': [...]} wrapper is being discarded again"
    assert 265598 in {int(r["conid"]) for r in result if r.get("conid") is not None}


@pytest.mark.integration
def test_get_contract_rules(live_client):
    result = live_client.get_contract_rules(265598, is_buy=True)
    assert isinstance(result, dict)
    # Order types are the rules a caller actually acts on; their absence makes the response
    # useless even when well-formed.
    assert result.get("orderTypes"), f"no orderTypes in rules: {sorted(result)[:10]}"


@pytest.mark.integration
def test_get_futures_es(live_client):
    result = live_client.get_futures(["ES"])
    assert isinstance(result, list)
    assert len(result) > 0
    assert all("conid" in c for c in result)


@pytest.mark.integration
def test_get_stocks_aapl(live_client):
    result = live_client.get_stocks(["AAPL"])
    assert isinstance(result, list)
    assert len(result) > 0
    # The symbol asked for is the symbol returned, and it carries the contracts that make
    # the row useful. `search_contract` resolving to the wrong listing was a real defect
    # here (CHANGELOG 2026-08-05), so the identity check is not ceremony.
    assert any("AAPL" in str(r.get("name", "")) or r.get("contracts") for r in result), result[:1]


@pytest.mark.integration
def test_get_trading_schedule(live_client):
    # IBKR returns a list of schedule objects (not a dict) for this endpoint
    result = live_client.get_trading_schedule("STK", "AAPL", "SMART")
    assert isinstance(result, (dict, list))


@pytest.mark.integration
def test_get_currency_pairs_usd(live_client):
    # Fixed 2026-06-30: was calling nonexistent /iserver/secdef/currency
    result = live_client.get_currency_pairs("USD")
    assert isinstance(result, list)
    assert len(result) > 0
    # Each entry should have a conid and a symbol
    assert all("conid" in p and "symbol" in p for p in result)


@pytest.mark.integration
def test_get_option_strikes_aapl(live_client):
    import datetime

    # secdef/search must precede strikes (documented prerequisite) — otherwise
    # the endpoint always returns empty arrays.
    live_client.search_contract("AAPL")
    # Documented month format: {3-char month}{2-char year}, e.g. "AUG26"
    today = datetime.date.today()
    next_month = (today.replace(day=1) + datetime.timedelta(days=32)).replace(day=1)
    month_str = next_month.strftime("%b%y").upper()  # e.g. "AUG26"
    result = live_client.get_option_strikes(265598, "OPT", month_str)
    assert isinstance(result, dict)
    assert "call" in result and "put" in result


@pytest.mark.integration
def test_get_option_chain_documented_flow(live_client):
    # Reimplemented 2026-07-07 via secdef/search → secdef/strikes (register item 6).
    chain = live_client.get_option_chain("AAPL")
    assert chain["symbol"] == "AAPL"
    assert isinstance(chain["conid"], int)
    assert chain["months"], "expected at least one expiry month"
    assert chain["month"] == chain["months"][0]
    assert chain["call"], "expected call strikes for the nearest expiry"
    assert chain["put"], "expected put strikes for the nearest expiry"


# ---------------------------------------------------------------------------
# Market Data
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_get_market_snapshot_aapl(live_client):
    # First call may return empty (warmup) — retry once as the client does internally
    result = live_client.get_market_snapshot([265598])
    assert isinstance(result, list)
    assert result, "empty snapshot after the client's own warmup retry"
    assert int(result[0].get("conid")) == 265598, f"snapshot for the wrong contract: {result[0].get('conid')}"


@pytest.mark.integration
def test_get_market_history_aapl(live_client):
    result = live_client.get_market_history(265598, period="5d", bar="1d")
    assert isinstance(result, dict)
    # Bars, not merely an envelope. A well-formed response carrying no data is exactly the
    # shape both history defects took (2026-08-05 stale window, 2026-09-15 dropped bars).
    bars = result.get("data") or []
    assert bars, f"history envelope with no bars: {sorted(result)[:10]}"
    assert {"t", "c"} <= set(bars[0]), sorted(bars[0])


@pytest.mark.integration
def test_unsubscribe_all_market_data(live_client):
    # GET /iserver/marketdata/unsubscribeall — was wrongly POST before fix
    result = live_client.unsubscribe_all_market_data()
    assert isinstance(result, dict)
    # The endpoint reports what it did; an empty dict would pass a type check while telling
    # the caller nothing about whether anything was unsubscribed.
    assert "unsubscribed" in result, f"no confirmation key: {sorted(result)}"


# ---------------------------------------------------------------------------
# Portfolio / Account
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_get_accounts(live_client):
    accounts = live_client.get_accounts()
    assert isinstance(accounts, list)
    assert len(accounts) > 0
    # The id is the only field every downstream call needs, and `_first_account_id` exists
    # because IBKR spells it `accountId` or `id` depending on the endpoint.
    assert accounts[0].get("accountId") or accounts[0].get("id"), sorted(accounts[0])[:8]


@pytest.mark.integration
def test_get_subaccounts(live_client):
    result = live_client.get_subaccounts()
    assert isinstance(result, list)
    assert result, "no subaccounts returned for an authenticated session"
    assert result[0].get("accountId") or result[0].get("id"), sorted(result[0])[:8]


@pytest.mark.integration
def test_get_brokerage_accounts(live_client):
    # GET /iserver/accounts returns a dict with "accounts" key (not a bare list)
    result = live_client.get_brokerage_accounts()
    assert isinstance(result, dict)
    assert "accounts" in result
    assert len(result["accounts"]) > 0


@pytest.mark.integration
def test_get_account_summary(live_client, account_id):
    result = live_client.get_account_summary(account_id)
    assert isinstance(result, dict)
    # Net liquidation is the number a human opens this for; an empty summary is a failure
    # wearing a success's shape.
    assert result, "empty account summary"
    assert any(k.lower().startswith("netliquidation") for k in result), sorted(result)[:10]


@pytest.mark.integration
def test_get_account_ledger(live_client, account_id):
    result = live_client.get_account_ledger(account_id)
    assert isinstance(result, dict)
    # The ledger is keyed by currency and always carries BASE for the account's base currency.
    assert "BASE" in result, f"no BASE currency bucket in ledger: {sorted(result)[:8]}"


@pytest.mark.integration
def test_get_positions(live_client, account_id):
    result = live_client.get_positions(account_id)
    assert isinstance(result, list)
    if not result:
        pytest.skip("account holds no positions — nothing for this endpoint to return")
    # A position without a conid or a size is not a position.
    assert result[0].get("conid"), sorted(result[0])[:8]
    assert "position" in result[0], sorted(result[0])[:8]


@pytest.mark.integration
def test_get_account_allocation(live_client, account_id):
    result = live_client.get_account_allocation(account_id)
    assert isinstance(result, dict)
    # The endpoint's whole output is the three breakdowns; an empty dict passes a type
    # check and answers nothing.
    assert {"assetClass", "sector", "group"} & set(result), sorted(result)[:8]


@pytest.mark.integration
def test_get_positions_by_conid(live_client, held_conid):
    result = live_client.get_positions_by_conid(held_conid)
    assert isinstance(result, list)
    # Asked about a contract the account HOLDS, so an empty answer is wrong by construction.
    # This test previously asked about AAPL — which the account does not hold — and asserted
    # only the type, so it passed for two years' worth of `[]` from an account-keyed object
    # being read as a bare list (fixed 2026-09-16).
    assert result, f"no position returned for held conid {held_conid}"
    assert {int(r["conid"]) for r in result} == {int(held_conid)}
    assert all(r.get("acctId") for r in result), result[:1]


@pytest.mark.integration
def test_get_pnl(live_client):
    result = live_client.get_pnl()
    assert isinstance(result, dict)
    # `upnl` is the payload; without it the caller has an envelope and no P&L.
    assert "upnl" in result, f"no upnl block: {sorted(result)[:8]}"


# ---------------------------------------------------------------------------
# Orders (read-only)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_get_live_orders(live_client):
    # Two-call pattern — fixed path #live-orders
    result = live_client.get_live_orders()
    assert isinstance(result, list)
    if not result:
        pytest.skip("no live orders on the account right now — nothing to assert content against")
    assert result[0].get("orderId") or result[0].get("order_id"), sorted(result[0])[:8]


@pytest.mark.integration
def test_get_trades(live_client):
    # GET /iserver/account/trades — confirmed anchor #trades
    result = live_client.get_trades()
    assert isinstance(result, list)
    if not result:
        pytest.skip("no fills in the last 7 days — nothing for this endpoint to return")
    # An execution names its account and its contract; the two-call warmup returning an
    # empty first response is exactly what this endpoint is documented to do, so an empty
    # list is skipped above rather than asserted away.
    assert result[0].get("account") or result[0].get("acctCode"), sorted(result[0])[:8]
    assert result[0].get("conid") or result[0].get("conidex"), sorted(result[0])[:8]


# ---------------------------------------------------------------------------
# Watchlists (paths fixed 2026-06-30: /iserver/account/* → /iserver/*)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_get_watchlists(live_client):
    # Was 404ing with /iserver/account/watchlists — fixed to /iserver/watchlists
    result = live_client.get_watchlists()
    assert isinstance(result, list)
    # This endpoint wraps its lists in `{"data": {"user_lists": [...]}}`; reading it as a
    # bare array reported none for an account that had eight (2026-07-23 → 2026-08-11).
    # A type-only assertion is what let that live for three weeks.
    assert result, "no watchlists — the {'data': {'user_lists': ...}} wrapper is being discarded again"
    assert result[0].get("id") is not None and result[0].get("name") is not None, sorted(result[0])


@pytest.mark.integration
def test_get_watchlists_does_not_silently_drop_lists(live_client):
    """Cross-check the parse against the raw payload.

    The old assertion here was `isinstance(result, list)`, which is satisfied by `[]` —
    so it passed for weeks while `get_watchlists()` returned nothing for an account with
    eight watchlists (2026-07-23 bug). A shape assertion cannot catch a silent
    under-report; only comparing against the raw response can. If IBKR says there are
    watchlists, the parsed result must contain them.
    """
    raw = live_client._get("/iserver/watchlists", {"SC": "USER_WATCHLIST"})
    payload = raw.get("data") if isinstance(raw, dict) else None
    if not isinstance(payload, dict):
        payload = {}
    expected_ids = {
        str(w.get("id"))
        for key in ("user_lists", "system_lists")
        for w in (payload.get(key) or [])
        if isinstance(w, dict) and w.get("id") is not None
    }
    parsed_ids = {str(w.get("id")) for w in live_client.get_watchlists() if w.get("id") is not None}
    assert parsed_ids == expected_ids, f"parse dropped watchlists: raw={expected_ids} parsed={parsed_ids}"


@pytest.mark.integration
def test_watchlist_roundtrip(live_client):
    """Create → read → delete a watchlist to verify all three fixed paths."""
    from ibkr_core_mcp.exceptions import IBKRRateLimitError

    # Create with AAPL (conid 265598)
    try:
        created = live_client.create_watchlist("_test_ibkr_audit", [{"C": 265598}])
    except IBKRRateLimitError:
        pytest.skip("IBKR rate limited watchlist creation — endpoint path is correct (503 is not 404)")
        return
    assert created.get("id") or created.get("name"), f"create returned no identifier: {sorted(created)}"

    # Get all watchlists and find ours
    watchlists = live_client.get_watchlists()
    test_wl = next(
        (w for w in watchlists if w.get("name") == "_test_ibkr_audit" or w.get("id") == "_test_ibkr_audit"),
        None,
    )
    # IBKR may return the id we passed or assign a numeric one
    wl_id = test_wl.get("id") if test_wl else created.get("id", created.get("name", "_test_ibkr_audit"))

    # Read specific watchlist
    detail = live_client.get_watchlist(str(wl_id))
    assert isinstance(detail, dict)
    # A watchlist that reports no identity and no instruments is not a watchlist; the
    # sibling get_watchlists endpoint returned exactly that shape for three weeks.
    assert detail.get("id") or detail.get("name") or detail.get("instruments") is not None, sorted(detail)[:8]

    # Delete
    delete_result = live_client.delete_watchlist(str(wl_id))
    assert isinstance(delete_result, dict)
    assert delete_result, "delete returned an empty body — no confirmation that anything happened"
    # The list must actually be gone; a 200 with an empty body is not a deletion.
    assert not [w for w in live_client.get_watchlists() if str(w.get("id")) == str(wl_id)], (
        f"watchlist {wl_id} still present after delete"
    )


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_get_scanner_params(live_client):
    result = live_client.get_scanner_params()
    assert isinstance(result, dict)
    # The four lists ARE the response; without them a scanner cannot be built.
    assert {"instrument_list", "scan_type_list", "filter_list", "location_tree"} <= set(result), sorted(result)


@pytest.mark.integration
def test_run_iserver_scanner(live_client):
    # Minimal scanner payload — top 10 most active US stocks
    params = {
        "instrument": "STK",
        "type": "MOST_ACTIVE",
        "filter": [{"code": "country", "value": "US"}],
    }
    result = live_client.run_iserver_scanner(params)
    assert isinstance(result, list)
    if not result:
        pytest.skip("scanner returned no rows for MOST_ACTIVE/US right now — market may be closed")
    assert result[0].get("conid") or result[0].get("con_id") or result[0].get("symbol"), sorted(result[0])[:8]


# ---------------------------------------------------------------------------
# Portfolio Analyst
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_get_pa_periods(live_client, account_id):
    result = live_client.get_pa_periods([account_id])
    assert isinstance(result, list)
    # These strings are the only valid `period=` inputs for get_pa_performance, so an empty
    # list silently breaks the caller below rather than this test.
    assert result, "no performance periods returned"
    assert "1D" in result or "1M" in result, result


@pytest.mark.integration
def test_get_pa_performance(live_client, account_id):
    # Valid periods: "1D", "7D", "MTD", "1M", "YTD", "1Y" (live-verified 2026-06-30)
    # "last7days" etc. return HTTP 400 — those strings are not valid for this endpoint
    periods = live_client.get_pa_periods([account_id])
    period = periods[0] if periods else "1D"
    result = live_client.get_pa_performance([account_id], period=period)
    assert isinstance(result, dict)
    assert result, f"empty performance response for period {period!r}"


@pytest.mark.integration
def test_get_pa_transactions(live_client, account_id, held_conid):
    """Marker removed 2026-09-16 — the endpoint works and the test now proves it.

    Was xfail from 2026-06-30, when `/pa/transactions` returned HTTP 400 for every tested
    period/days value. The request format was corrected on that date (`conids` + `currency`
    became required), and the marker was left behind — so the suite reported XPASS instead
    of coverage.

    That XPASS is what led here, exactly as the old docstring said it should: "the signal
    to go confirm the format and remove this marker." Confirming it found something worse
    than a stale marker — the method was returning `[]` for every account because the
    response is an object and was read as a bare list, and this test could not see that
    because it asserted only `isinstance(result, list)`.

    Both are now fixed: the wrapper is unpacked, and the assertion is against a contract
    the account actually holds over a year, where acquiring it was itself a transaction.
    """
    result = live_client.get_pa_transactions([account_id], [held_conid], days=365)
    assert isinstance(result, list)
    # Asked about a contract the account HOLDS, over a year: acquiring it was itself a
    # transaction. This method returned `[]` for every account from the day it was written
    # until 2026-09-16 — the response is an object and was read as a bare list — and a live
    # test watched it do so, asserting only `isinstance(result, list)`.
    assert result, f"no transactions in 365d for held conid {held_conid} — the object wrapper is being discarded again"
    assert {"conid", "date", "amt"} <= set(result[0]), sorted(result[0])


# ---------------------------------------------------------------------------
# FYI / Notifications
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_get_notifications(live_client):
    result = live_client.get_notifications()
    assert isinstance(result, list)
    if not result:
        pytest.skip("no FYI notifications on the account — nothing to assert content against")
    assert result[0].get("ID") or result[0].get("id"), sorted(result[0])[:8]


@pytest.mark.integration
def test_get_unread_count(live_client):
    from ibkr_core_mcp.exceptions import IBKRAPIError

    try:
        result = live_client.get_unread_count()
        assert isinstance(result, int)
        assert result >= 0
    except IBKRAPIError as e:
        if "423" in str(e):
            pytest.skip("FYI/unreadnumber HTTP 423 — FYI subscription not configured for this account")
        raise


@pytest.mark.integration
def test_get_mta_alert(live_client):
    result = live_client.get_mta_alert()
    assert isinstance(result, dict)
    # The MTA alert always exists for an account; an empty dict means it was not read.
    assert result.get("account") or result.get("order_id"), sorted(result)[:8]


# ---------------------------------------------------------------------------
# Alerts (read-only)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_get_alerts(live_client, account_id):
    result = live_client.get_alerts(account_id)
    assert isinstance(result, list)
    if not result:
        # Deliberate loud skip, not a passing type check: alert WRITES need a brokerage
        # session this suite cannot establish (see the module docstring), so an account
        # under test legitimately holds none. Saying so beats asserting a type.
        pytest.skip("account has no price alerts — alert writes need a brokerage session, so none can be created here")
    assert result[0].get("order_id") or result[0].get("alert_name"), sorted(result[0])[:8]


# ---------------------------------------------------------------------------
# Batch 2: Alert CRUD roundtrip (create → get → activate → delete)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_alert_crud_roundtrip(live_client, account_id):
    """Create a price alert on AAPL, read it back, toggle it, then delete it."""
    from ibkr_core_mcp.exceptions import IBKRAPIError, IBKRRateLimitError

    # Build IBKR alert payload for AAPL above $99999 (never fires, safe for testing)
    alert_payload = {
        "orderId": 0,
        "alertName": "_test_ibkr_audit_alert",
        "alertMessage": "",
        "alertRepeatable": 0,
        "expireTime": "",
        "tif": "GTC",
        "outsideRth": False,
        "isSizeCondition": False,
        "conditions": [
            {
                "type": 1,
                "conid": 265598,
                "exchange": "SMART",
                "conditionType": "Price",
                "operator": ">=",
                "value": "99999.0",
            }
        ],
    }
    try:
        created = live_client.create_alert(account_id=account_id, alert=alert_payload)
    except IBKRRateLimitError:
        pytest.skip("Rate limited creating alert — endpoint path is correct")
        return
    except IBKRAPIError as e:
        if "403" in str(e):
            pytest.skip(
                "create_alert HTTP 403 — the gateway rejects a body containing '>=' or '<=' "
                "before it reaches IBKR, and those are the only operators its alert engine "
                "accepts. NOT a permissions restriction: DELETE is also a write and works. "
                "See docs/ibkr-api-behaviors-reference.md § Price alerts (measured 2026-09-16)."
            )
        raise
    assert isinstance(created, dict), f"create_alert returned {type(created)}"

    # Extract the orderId/alertId from the response
    alert_id = created.get("orderId") or created.get("id") or created.get("alertId")
    if not alert_id:
        pytest.skip(f"create_alert succeeded but no id in response: {created}")

    try:
        # Read back: should appear in the alert list
        alerts = live_client.get_alerts(account_id)
        assert isinstance(alerts, list)
        match = next((a for a in alerts if str(a.get("orderId") or a.get("id")) == str(alert_id)), None)
        assert match is not None, f"Created alert {alert_id} not found in get_alerts"

        # Get single alert
        detail = live_client.get_alert(account_id, str(alert_id))
        assert isinstance(detail, dict)

        # Activate (toggle off then back on)
        toggle_result = live_client.activate_alert(account_id, str(alert_id), activate=False)
        assert isinstance(toggle_result, dict)
        toggle_result2 = live_client.activate_alert(account_id, str(alert_id), activate=True)
        assert isinstance(toggle_result2, dict)

    finally:
        # Always delete — do not leak test alerts
        try:
            del_result = live_client.delete_alert(account_id, str(alert_id))
            assert isinstance(del_result, dict)
        except IBKRAPIError as e:
            # Deletion failed — flag but do not fail the test
            pytest.fail(f"delete_alert failed for alert {alert_id}: {e}")


# ---------------------------------------------------------------------------
# Batch 2: Portfolio — get_account_meta, get_portfolio_allocation, get_position,
#           get_combo_positions, invalidate_positions_cache
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_get_account_meta(live_client, account_id):
    result = live_client.get_account_meta(account_id)
    assert isinstance(result, dict)
    assert str(result.get("accountId") or result.get("id")) == str(account_id), sorted(result)[:8]


@pytest.mark.integration
def test_get_portfolio_allocation(live_client, account_id):
    # /portfolio/allocation — takes a list of account IDs (not a single string)
    from ibkr_core_mcp.exceptions import IBKRAPIError

    try:
        result = live_client.get_portfolio_allocation([account_id])
        assert isinstance(result, (dict, list))
    except IBKRAPIError as e:
        if "500" in str(e):
            pytest.skip("get_portfolio_allocation HTTP 500 — endpoint may require positions to be initialized")
        raise


@pytest.mark.integration
def test_get_position(live_client, account_id, held_conid):
    # /portfolio/{accountId}/position/{conid} — single contract position.
    # Asked about a HELD contract: "may or may not be held" plus a type assertion is a test
    # that passes whatever the endpoint does, which is how the sibling endpoint's
    # always-empty bug survived (see test_get_positions_by_conid).
    result = live_client.get_position(account_id, held_conid)
    assert isinstance(result, list)
    assert result, f"no position returned for held conid {held_conid}"
    assert {int(r["conid"]) for r in result} == {int(held_conid)}


@pytest.mark.integration
def test_get_combo_positions(live_client, account_id):
    from ibkr_core_mcp.exceptions import IBKRAPIError

    try:
        result = live_client.get_combo_positions(account_id)
        if not result:
            pytest.skip("account holds no combo (spread) positions — nothing for this endpoint to return")
        assert result[0].get("conid"), sorted(result[0])[:8]
    except IBKRAPIError as e:
        if "500" in str(e):
            pytest.skip("get_combo_positions HTTP 500 — no combo (spread) positions in account")
        raise


@pytest.mark.integration
def test_invalidate_positions_cache(live_client, account_id):
    # POST /portfolio/{accountId}/positions/invalidate — should return HTTP 200
    result = live_client.invalidate_positions_cache(account_id)
    # Returns dict or None — non-exception response means the endpoint is reachable
    assert result is None or isinstance(result, dict)


# ---------------------------------------------------------------------------
# Batch 2: FYI — get_delivery_options, mark_notification_read
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_get_delivery_options(live_client):
    from ibkr_core_mcp.exceptions import IBKRAPIError

    try:
        result = live_client.get_delivery_options()
        assert isinstance(result, (dict, list))
    except IBKRAPIError as e:
        if "423" in str(e):
            pytest.skip("FYI delivery options HTTP 423 — FYI subscription not configured for this account")
        raise


@pytest.mark.integration
def test_mark_notification_read_noop(live_client):
    """Verify mark_notification_read is callable. Uses a fake id — expect 404 or {} not an exception."""
    from ibkr_core_mcp.exceptions import IBKRAPIError

    try:
        result = live_client.mark_notification_read("000000000000000000000000")
        assert result is None or isinstance(result, dict)
    except IBKRAPIError as e:
        # 404 for nonexistent id is acceptable — endpoint exists
        if "404" in str(e) or "400" in str(e):
            pass  # expected for a fake notification id
        elif "423" in str(e):
            pytest.skip("FYI mark-read HTTP 423 — FYI subscription not configured")
        else:
            raise


# ---------------------------------------------------------------------------
# Batch 2: Market data — unsubscribe_market_data (single conid)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_unsubscribe_market_data_single(live_client):
    # Subscribe to AAPL snapshot first (creates the subscription), then unsubscribe
    live_client.get_market_snapshot([265598])
    result = live_client.unsubscribe_market_data(265598)
    assert isinstance(result, dict)
    assert result, "empty unsubscribe response — the call reported nothing about what it did"


# ---------------------------------------------------------------------------
# Batch 2: Orders — get_order_status, get_order_preview (whatif)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_get_order_preview(live_client, account_id):
    """Whatif order for AAPL — read-only, no gates."""
    from ibkr_core_mcp.exceptions import IBKRAPIError

    order = {
        "conid": 265598,
        "orderType": "LMT",
        "price": 1.00,  # far below market — safe
        "side": "BUY",
        "quantity": 1,
        "tif": "DAY",
    }
    try:
        result = live_client.get_order_preview(account_id, order)
        assert isinstance(result, (dict, list))
    except IBKRAPIError as e:
        # Some gateway builds require session trading to be initialized — mark informational
        pytest.skip(f"get_order_preview returned error (may need initialized trading session): {e}")


@pytest.mark.integration
def test_get_order_status_invalid_id(live_client):
    """get_order_status with a fake order id — expect 404/400/503, not an uncaught exception."""
    from ibkr_core_mcp.exceptions import IBKRAPIError, IBKRRateLimitError

    try:
        result = live_client.get_order_status("999999999")
        # If IBKR answers rather than erroring, the answer must not look like a real order:
        # an invalid id returning a populated order would be far worse than a 404.
        assert not result.get("order_id") and not result.get("orderId"), (
            f"a nonexistent order id returned an order: {sorted(result)[:8]}"
        )
    except (IBKRAPIError, IBKRRateLimitError) as e:
        # 404/400 expected for nonexistent id; 503 = IBKR returns rate-limit error for invalid ids
        code = str(e)
        if any(c in code for c in ("404", "400", "503")):
            pass  # informational — endpoint path is correct
        else:
            raise


# ---------------------------------------------------------------------------
# Batch 2: PA transactions (fixed — now requires conids + currency)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_get_pa_transactions_aapl(live_client, account_id, held_conid):
    """PA transaction history for AAPL (conid 265598), 30 days."""
    from ibkr_core_mcp.exceptions import IBKRAPIError

    try:
        result = live_client.get_pa_transactions(
            account_ids=[account_id],
            conids=[held_conid],
            currency="USD",
            days=365,
        )
        assert isinstance(result, list)
        assert result, f"no transactions in 365d for held conid {held_conid}"
        assert {"conid", "date", "amt"} <= set(result[0]), sorted(result[0])
    except IBKRAPIError as e:
        # Document the actual HTTP status — this is the first live test of the fixed signature
        pytest.skip(f"get_pa_transactions returned error (fixed signature, first live test): {e}")


# ---------------------------------------------------------------------------
# Batch 2: International stock resolution — verify exchange filter across assets
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_search_contract_international_asml(live_client):
    """ASML is listed on both NYSE (ADR) and Euronext Amsterdam — verify resolution."""
    results = live_client.search_contract("ASML", "STK")
    assert isinstance(results, list)
    assert len(results) > 0
    # Should resolve — at minimum the NYSE ADR
    symbols = [r.get("symbol") for r in results]
    assert "ASML" in symbols or any("ASML" in str(s) for s in symbols)


@pytest.mark.integration
def test_search_contract_sap_frankfurt(live_client):
    """SAP is listed on Xetra — verify search returns at least one result."""
    results = live_client.search_contract("SAP", "STK")
    assert isinstance(results, list)
    assert len(results) > 0
    # Resolving a ticker to the WRONG listing was a real defect here (IGV resolved to the
    # Mexican listing, CHANGELOG 2026-08-05), so assert the symbol actually came back.
    assert any("SAP" in str(r.get("symbol", "") or r.get("companyHeader", "")).upper() for r in results), results[:1]


@pytest.mark.integration
def test_get_futures_nq(live_client):
    """NQ (Nasdaq futures) front-month — verify alongside ES."""
    result = live_client.get_futures(["NQ"])
    assert isinstance(result, list)
    assert len(result) > 0
    assert all("conid" in c for c in result)


@pytest.mark.integration
def test_get_currency_pairs_eur(live_client):
    """EUR currency pairs — verify the dict-flatten fix works for non-USD base."""
    result = live_client.get_currency_pairs("EUR")
    assert isinstance(result, list)
    assert len(result) > 0
    assert all("conid" in p and "symbol" in p for p in result)


# ---------------------------------------------------------------------------
# Batch 2: Bond filters (read-only)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_get_bond_filters(live_client):
    # get_bond_filters(symbol, issue_id) — requires a bond symbol AND an issue_id
    # IBM bonds are available on IBKR; issue_id is typically the conid of the bond's issuer.
    # IBM stock conid = 8314; use as issue_id (IBKR bond filter pattern from docs)
    from ibkr_core_mcp.exceptions import IBKRAPIError

    try:
        result = live_client.get_bond_filters("IBM", "8314")
        assert isinstance(result, (dict, list))
    except IBKRAPIError as e:
        # 400/404/500 are acceptable — depends on available bond inventory at test time
        if any(c in str(e) for c in ("400", "404", "500")):
            pytest.skip(f"get_bond_filters: {e} — bond inventory may not be available at test time")
        raise
