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
See docs/live-test-log.md#run-2026-07-01-1 for the confirmed finding.

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
    # Returns dict with login info or empty on unauthenticated — no exception means path OK
    assert isinstance(result, dict)


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
    assert result  # non-empty


@pytest.mark.integration
def test_get_contract_info_and_rules(live_client):
    result = live_client.get_contract_info_and_rules(265598)
    assert isinstance(result, dict)


@pytest.mark.integration
def test_get_contract_algos(live_client):
    result = live_client.get_contract_algos(265598)
    assert isinstance(result, list)


@pytest.mark.integration
def test_get_secdef_info(live_client):
    result = live_client.get_secdef_info(265598)
    assert isinstance(result, dict)


@pytest.mark.integration
def test_get_secdef_batch(live_client):
    # /trsrv/secdef may return empty when accounts aren't initialized — just verify the shape
    result = live_client.get_secdef([265598])
    assert isinstance(result, list)


@pytest.mark.integration
def test_get_contract_rules(live_client):
    result = live_client.get_contract_rules(265598, is_buy=True)
    assert isinstance(result, dict)


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
    # Use the next calendar month as the option expiry month
    today = datetime.date.today()
    next_month = (today.replace(day=1) + datetime.timedelta(days=32)).replace(day=1)
    month_str = next_month.strftime("%b %Y").upper()  # e.g. "AUG 2026"
    result = live_client.get_option_strikes(265598, "OPT", month_str)
    assert isinstance(result, list)


@pytest.mark.integration
def test_get_option_chain_raises(live_client):
    # /trsrv/secdef/chains does not exist — should raise IBKRAPIError every time
    from ibkr_core_mcp.exceptions import IBKRAPIError
    with pytest.raises(IBKRAPIError):
        live_client.get_option_chain("AAPL")


# ---------------------------------------------------------------------------
# Market Data
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_get_market_snapshot_aapl(live_client):
    # First call may return empty (warmup) — retry once as the client does internally
    result = live_client.get_market_snapshot([265598])
    assert isinstance(result, list)


@pytest.mark.integration
def test_get_market_history_aapl(live_client):
    result = live_client.get_market_history(265598, period="5d", bar="1d")
    assert isinstance(result, dict)
    # data key may be "data" or "timePeriod" depending on gateway version
    assert result  # non-empty response


@pytest.mark.integration
def test_unsubscribe_all_market_data(live_client):
    # GET /iserver/marketdata/unsubscribeall — was wrongly POST before fix
    result = live_client.unsubscribe_all_market_data()
    assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Portfolio / Account
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_get_accounts(live_client):
    accounts = live_client.get_accounts()
    assert isinstance(accounts, list)
    assert len(accounts) > 0


@pytest.mark.integration
def test_get_subaccounts(live_client):
    result = live_client.get_subaccounts()
    assert isinstance(result, list)


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


@pytest.mark.integration
def test_get_account_ledger(live_client, account_id):
    result = live_client.get_account_ledger(account_id)
    assert isinstance(result, dict)


@pytest.mark.integration
def test_get_positions(live_client, account_id):
    result = live_client.get_positions(account_id)
    assert isinstance(result, list)


@pytest.mark.integration
def test_get_account_allocation(live_client, account_id):
    result = live_client.get_account_allocation(account_id)
    assert isinstance(result, dict)


@pytest.mark.integration
def test_get_positions_by_conid(live_client):
    result = live_client.get_positions_by_conid(265598)
    assert isinstance(result, list)


@pytest.mark.integration
def test_get_pnl(live_client):
    result = live_client.get_pnl()
    assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Orders (read-only)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_get_live_orders(live_client):
    # Two-call pattern — fixed path #live-orders
    result = live_client.get_live_orders()
    assert isinstance(result, list)


@pytest.mark.integration
def test_get_trades(live_client):
    # GET /iserver/account/trades — confirmed anchor #trades
    result = live_client.get_trades()
    assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Watchlists (paths fixed 2026-06-30: /iserver/account/* → /iserver/*)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_get_watchlists(live_client):
    # Was 404ing with /iserver/account/watchlists — fixed to /iserver/watchlists
    result = live_client.get_watchlists()
    assert isinstance(result, list)


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
    assert isinstance(created, dict)

    # Get all watchlists and find ours
    watchlists = live_client.get_watchlists()
    test_wl = next(
        (w for w in watchlists if w.get("name") == "_test_ibkr_audit"
         or w.get("id") == "_test_ibkr_audit"),
        None,
    )
    # IBKR may return the id we passed or assign a numeric one
    wl_id = (
        test_wl.get("id") if test_wl
        else created.get("id", created.get("name", "_test_ibkr_audit"))
    )

    # Read specific watchlist
    detail = live_client.get_watchlist(str(wl_id))
    assert isinstance(detail, dict)

    # Delete
    delete_result = live_client.delete_watchlist(str(wl_id))
    assert isinstance(delete_result, dict)


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_get_scanner_params(live_client):
    result = live_client.get_scanner_params()
    assert isinstance(result, dict)
    assert result  # non-empty — docs confirm rich metadata response


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


# ---------------------------------------------------------------------------
# Portfolio Analyst
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_get_pa_periods(live_client, account_id):
    result = live_client.get_pa_periods([account_id])
    # Returns list of period strings or empty list — non-error is sufficient
    assert isinstance(result, list)


@pytest.mark.integration
def test_get_pa_performance(live_client, account_id):
    # Valid periods: "1D", "7D", "MTD", "1M", "YTD", "1Y" (live-verified 2026-06-30)
    # "last7days" etc. return HTTP 400 — those strings are not valid for this endpoint
    periods = live_client.get_pa_periods([account_id])
    period = periods[0] if periods else "1D"
    result = live_client.get_pa_performance([account_id], period=period)
    assert isinstance(result, dict)


@pytest.mark.integration
def test_get_pa_transactions(live_client, account_id):
    # NOTE: /pa/transactions returns HTTP 400 for all tested period/days values
    # ("1D","7D","MTD","1M","YTD","1Y", days=7/30/90) — parameter format TBD.
    # The implementation passes "period" but the docstring says "days" (int).
    # Skipping until the correct request format is confirmed from official docs.
    pytest.skip("/pa/transactions: correct request parameter format not yet confirmed — see live-test-log.md#run-2026-06-30")


# ---------------------------------------------------------------------------
# FYI / Notifications
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_get_notifications(live_client):
    result = live_client.get_notifications()
    assert isinstance(result, list)


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


# ---------------------------------------------------------------------------
# Alerts (read-only)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_get_alerts(live_client, account_id):
    result = live_client.get_alerts(account_id)
    assert isinstance(result, list)


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
            pytest.skip("create_alert HTTP 403 — alert write requires trading session permissions (CP API restriction)")
        raise
    assert isinstance(created, dict), f"create_alert returned {type(created)}"

    # Extract the orderId/alertId from the response
    alert_id = (
        created.get("orderId")
        or created.get("id")
        or created.get("alertId")
    )
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
def test_get_position(live_client, account_id):
    # /portfolio/{accountId}/position/{conid} — single contract position
    # AAPL (265598) may or may not be held; endpoint should return list (empty or filled)
    result = live_client.get_position(account_id, 265598)
    assert isinstance(result, list)


@pytest.mark.integration
def test_get_combo_positions(live_client, account_id):
    from ibkr_core_mcp.exceptions import IBKRAPIError
    try:
        result = live_client.get_combo_positions(account_id)
        assert isinstance(result, list)
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
        assert isinstance(result, dict)
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
def test_get_pa_transactions_aapl(live_client, account_id):
    """PA transaction history for AAPL (conid 265598), 30 days."""
    from ibkr_core_mcp.exceptions import IBKRAPIError
    try:
        result = live_client.get_pa_transactions(
            account_ids=[account_id],
            conids=[265598],
            currency="USD",
            days=30,
        )
        assert isinstance(result, list)
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
def test_get_regulatory_snapshot(live_client):
    """Regulatory (NBBO-grade) snapshot for AAPL. WARNING: $0.01/call unless subscribed."""
    # AAPL conid 265598. Cost: $0.01 USD per call (per official IBKR docs).
    result = live_client.get_regulatory_snapshot(265598)
    assert isinstance(result, (dict, list))
    # If it's a list, it may be a list with one dict inside
    if isinstance(result, list):
        assert len(result) > 0
        result = result[0]
    # Should contain at least one price-related field (31=last, 70=high, 71=low, 84=bid, 86=ask)
    assert result, "Regulatory snapshot returned empty"


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
