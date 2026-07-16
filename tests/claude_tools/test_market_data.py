from unittest.mock import patch

import pytest

pytestmark = pytest.mark.market_data


def test_execute_check_cache_hit(toolkit):
    toolkit._cache.check.return_value = True
    text, fig = toolkit.execute(
        "check_cache", {"symbol": "AAPL", "timeframe": "1D", "period": "1Y", "end": "2026-05-22"}
    )
    assert "HIT" in text
    assert fig is None


def test_execute_check_cache_miss(toolkit):
    toolkit._cache.check.return_value = False
    text, fig = toolkit.execute(
        "check_cache", {"symbol": "AAPL", "timeframe": "1D", "period": "1Y", "end": "2026-05-22"}
    )
    assert "MISS" in text


# ============================================================================
# _list_cache
# ============================================================================


def test_list_cache_empty(toolkit):
    """Returns 'cache is empty' when Drive has no entries."""
    toolkit._cache.list_cached.return_value = []
    text, fig = toolkit.execute("list_cache", {})
    assert "empty" in text.lower()
    assert fig is None


def test_list_cache_happy_path(toolkit):
    """Returns one line per cached dataset with key, row count, and date."""
    toolkit._cache.list_cached.return_value = [
        {"key": "AAPL_1D_1Y_2026-06-30", "rows": 252, "cached_at": "2026-06-30T12:00:00"},
        {"key": "MSFT_1D_6M_2026-06-30", "rows": 126, "cached_at": "2026-06-29T08:00:00"},
    ]
    text, fig = toolkit.execute("list_cache", {})
    assert fig is None
    assert "Cached datasets (2)" in text
    assert "AAPL_1D_1Y_2026-06-30" in text
    assert "252 bars" in text
    assert "2026-06-30" in text


def test_execute_add_indicators(toolkit):
    import numpy as np
    import pandas as pd

    n = 100
    np.random.seed(0)
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    df = pd.DataFrame(
        {
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": np.ones(n) * 1e6,
        },
        index=pd.date_range("2025-01-01", periods=n, freq="B"),
    )
    toolkit._cache.check.return_value = True
    toolkit._cache.load.return_value = df
    text, fig = toolkit.execute(
        "add_indicators", {"symbol": "AAPL", "timeframe": "1D", "period": "1Y", "end": "2026-05-22"}
    )
    assert len(text) > 0
    assert fig is None


def test_execute_get_market_snapshot_warns_on_partial_resolution(toolkit):
    # AAPL resolves; BADTICKER does not — output must name the skipped symbol
    def search_side_effect(sym, sec_type):
        if sym == "AAPL":
            return [{"conid": 265598, "exchange": "NASDAQ"}]
        return []

    toolkit._client.search_contract.side_effect = search_side_effect
    toolkit._client.get_market_snapshot.return_value = [{"conid": 265598, "31": "185.0"}]
    text, fig = toolkit.execute("get_market_snapshot", {"symbols": ["AAPL", "BADTICKER"]})
    assert "BADTICKER" in text
    assert "omitted" in text.lower() or "could not resolve" in text.lower()
    assert fig is None


def test_execute_get_market_snapshot_invalid_conid_skipped(toolkit):
    toolkit._client.search_contract.return_value = [{"conid": "N/A"}]
    toolkit._client.get_market_snapshot.return_value = []
    text, fig = toolkit.execute("get_market_snapshot", {"symbols": ["AAPL"]})
    assert "Could not resolve" in text
    toolkit._client.get_market_snapshot.assert_not_called()


def test_execute_get_market_snapshot_fut_uses_futures_endpoint_not_search(toolkit):
    """FUT must resolve via /trsrv/futures, not /iserver/secdef/search.

    /iserver/secdef/search only documents STK, IND, BOND support.
    Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#sec-search
    """
    toolkit._client.get_futures.return_value = [
        {"symbol": "ES", "conid": 111, "expirationDate": 20260918},
        {"symbol": "ES", "conid": 222, "expirationDate": 20260619},
    ]
    toolkit._client.get_market_snapshot.return_value = [{"conid": 222, "31": "5800.0", "6509": "R"}]
    text, fig = toolkit.execute("get_market_snapshot", {"symbols": ["ES"], "sec_type": "FUT"})
    toolkit._client.search_contract.assert_not_called()
    toolkit._client.get_market_snapshot.assert_called_once_with([222])
    assert "5800.0" in text


def test_execute_get_market_snapshot_fut_no_contracts_found(toolkit):
    toolkit._client.get_futures.return_value = []
    text, fig = toolkit.execute("get_market_snapshot", {"symbols": ["ZZFUT"], "sec_type": "FUT"})
    assert "Could not resolve" in text
    toolkit._client.get_market_snapshot.assert_not_called()


def test_execute_get_market_snapshot_exchange_filter_selects_listing(toolkit):
    """International equities: search_contract may return multiple listings.

    exchange param filters to the requested venue instead of always taking [0].
    """
    toolkit._client.search_contract.return_value = [
        {"conid": 1, "exchange": "NYSE"},
        {"conid": 2, "exchange": "AMS"},
    ]
    toolkit._client.get_market_snapshot.return_value = [{"conid": 2, "31": "700.0", "6509": "D"}]
    text, fig = toolkit.execute("get_market_snapshot", {"symbols": ["ASML"], "exchange": "AMS"})
    toolkit._client.get_market_snapshot.assert_called_once_with([2])
    assert "700.0" in text


def test_execute_get_market_snapshot_exchange_filter_no_match_falls_back(toolkit):
    """If no listing matches the requested exchange, fall back to first result
    rather than failing outright — better to return something resolvable."""
    toolkit._client.search_contract.return_value = [{"conid": 1, "exchange": "NYSE"}]
    toolkit._client.get_market_snapshot.return_value = [{"conid": 1, "31": "100.0", "6509": "R"}]
    text, fig = toolkit.execute("get_market_snapshot", {"symbols": ["GE"], "exchange": "NONEXISTENT"})
    toolkit._client.get_market_snapshot.assert_called_once_with([1])


def test_resolve_snapshot_conid_stk_falls_back_to_con_id_key(toolkit):
    """STK/IND/BOND resolution must apply the .get("conid") or .get("con_id")
    fallback — some IBKR responses key it "con_id" instead of "conid"
    (CLAUDE.md convention). This branch omitted the fallback."""
    toolkit._client.search_contract.return_value = [{"con_id": 42, "exchange": "SMART"}]
    conid, err = toolkit._resolve_snapshot_conid("AAPL", "STK", None)
    assert err is None
    assert conid == 42


def test_execute_get_market_snapshot_cash_uses_currency_pairs_not_search(toolkit):
    """CASH must resolve via /iserver/currency/pairs, not /iserver/secdef/search.

    secType=CASH is not in the documented STK/IND/BOND list for secdef/search.
    Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#get-currency-pairs
    """
    toolkit._client.get_currency_pairs.return_value = [
        {"symbol": "EUR.USD", "conid": 12087792, "ccyPair": "USD"},
        {"symbol": "EUR.JPY", "conid": 28201823, "ccyPair": "JPY"},
    ]
    toolkit._client.get_market_snapshot.return_value = [{"conid": 12087792, "31": "1.0850", "6509": "R"}]
    text, fig = toolkit.execute("get_market_snapshot", {"symbols": ["EUR.USD"], "sec_type": "CASH"})
    toolkit._client.get_currency_pairs.assert_called_once_with("EUR")
    toolkit._client.search_contract.assert_not_called()
    toolkit._client.get_market_snapshot.assert_called_once_with([12087792])
    assert "1.0850" in text


def test_execute_get_market_snapshot_cash_invalid_format_rejected(toolkit):
    text, fig = toolkit.execute("get_market_snapshot", {"symbols": ["EURUSD"], "sec_type": "CASH"})
    assert "Could not resolve" in text
    toolkit._client.get_currency_pairs.assert_not_called()
    toolkit._client.get_market_snapshot.assert_not_called()


def test_execute_get_market_snapshot_cash_pair_not_found(toolkit):
    toolkit._client.get_currency_pairs.return_value = [
        {"symbol": "EUR.JPY", "conid": 28201823, "ccyPair": "JPY"},
    ]
    text, fig = toolkit.execute("get_market_snapshot", {"symbols": ["EUR.USD"], "sec_type": "CASH"})
    assert "Could not resolve" in text
    toolkit._client.get_market_snapshot.assert_not_called()


def test_fetch_market_data_live_path(toolkit):
    import numpy as np
    import pandas as pd

    n = 50
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    df = pd.DataFrame(
        {
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": np.ones(n) * 1e6,
        },
        index=pd.date_range("2025-01-01", periods=n, freq="B"),
    )

    toolkit._cache.check.return_value = False
    toolkit._client.search_contract.return_value = [{"conid": 265598}]
    # Simulate IBKR raw response that bars_to_dataframe can parse
    data_rows = [
        {
            "t": int(ts.timestamp() * 1000),
            "o": r["open"],
            "h": r["high"],
            "l": r["low"],
            "c": r["close"],
            "v": r["volume"],
        }
        for ts, r in df.iterrows()
    ]
    toolkit._client.get_market_history_paginated.return_value = {"data": data_rows}

    text, fig = toolkit.execute("fetch_market_data", {"symbol": "AAPL", "period": "1Y", "bar": "1d"})
    assert "AAPL" in text
    assert "IBKR" in text
    toolkit._cache.save.assert_called_once()


def test_fetch_market_data_no_contract(toolkit):
    toolkit._cache.check.return_value = False
    toolkit._client.search_contract.return_value = []
    text, fig = toolkit.execute("fetch_market_data", {"symbol": "FAKE", "period": "1Y", "bar": "1d"})
    assert "Could not resolve conid" in text


def test_fetch_market_data_empty_data(toolkit):
    """Paginated endpoint returning empty → error message with 'no data'."""
    toolkit._cache.check.return_value = False
    toolkit._client.search_contract.return_value = [{"conid": 265598}]
    toolkit._client.get_market_history_paginated.return_value = {"data": []}
    with patch("time.sleep"):
        text, fig = toolkit.execute("fetch_market_data", {"symbol": "AAPL", "period": "1Y", "bar": "1d"})
    assert "no data" in text.lower()


# ============================================================================
# _search_contract
# ============================================================================


def test_search_contract_happy_path(toolkit):
    """Returns JSON-formatted contract list."""
    toolkit._client.search_contract.return_value = [
        {"conid": 265598, "symbol": "AAPL", "secType": "STK", "exchange": "NASDAQ"},
    ]
    text, fig = toolkit.execute("search_contract", {"symbol": "aapl"})
    assert fig is None
    assert "265598" in text
    assert "AAPL" in text


def test_search_contract_default_sec_type(toolkit):
    """sec_type defaults to STK when omitted."""
    toolkit._client.search_contract.return_value = [{"conid": 265598}]
    toolkit.execute("search_contract", {"symbol": "AAPL"})
    toolkit._client.search_contract.assert_called_once_with("AAPL", "STK")


def test_search_contract_no_results(toolkit):
    """Returns 'no contracts found' message when IBKR returns empty list."""
    toolkit._client.search_contract.return_value = []
    text, fig = toolkit.execute("search_contract", {"symbol": "XYZ99"})
    assert fig is None
    assert "No contracts found" in text
    assert "XYZ99" in text


# ============================================================================
# _get_futures
# ============================================================================


def test_get_futures_happy_path(toolkit):
    """Returns JSON-formatted futures contracts."""
    toolkit._client.get_futures.return_value = [
        {"symbol": "ESZ6", "conid": 551601958, "expirationDate": 20261218},
        {"symbol": "ESH7", "conid": 551601959, "expirationDate": 20270319},
    ]
    text, fig = toolkit.execute("get_futures", {"symbols": ["ES"]})
    assert fig is None
    assert "ESZ6" in text
    assert "551601958" in text


def test_get_futures_symbols_uppercased(toolkit):
    """Symbols are uppercased before passing to the client."""
    toolkit._client.get_futures.return_value = [{"symbol": "ESZ6", "conid": 12345}]
    toolkit.execute("get_futures", {"symbols": ["es", "nq"]})
    toolkit._client.get_futures.assert_called_once_with(["ES", "NQ"])


def test_get_futures_no_results(toolkit):
    """Returns 'no futures found' message when IBKR returns empty list."""
    toolkit._client.get_futures.return_value = []
    text, fig = toolkit.execute("get_futures", {"symbols": ["ZZZ"]})
    assert fig is None
    assert "No futures found" in text
    assert "ZZZ" in text


# ── _sync_flex_trades — missing token ────────────────────────────────────────


def test_get_contract_info_happy_path(toolkit):
    """Returns JSON contract details when conid resolves."""
    toolkit._client.search_contract.return_value = [{"conid": 265598}]
    toolkit._client.get_contract_info_and_rules.return_value = {"symbol": "AAPL", "secType": "STK", "currency": "USD"}
    text, fig = toolkit.execute("get_contract_info", {"symbol": "AAPL"})
    assert fig is None
    assert "AAPL" in text
    assert "STK" in text


def test_get_contract_info_no_contract(toolkit):
    """Returns error when search_contract finds nothing."""
    toolkit._client.search_contract.return_value = []
    text, fig = toolkit.execute("get_contract_info", {"symbol": "FAKESYM"})
    assert fig is None
    assert "Could not resolve conid" in text


def test_get_contract_info_error(toolkit):
    """Propagates client exception through _safe_error."""
    toolkit._client.search_contract.return_value = [{"conid": 265598}]
    toolkit._client.get_contract_info_and_rules.side_effect = RuntimeError("timeout")
    text, fig = toolkit.execute("get_contract_info", {"symbol": "AAPL"})
    assert fig is None
    assert "unexpected" in text.lower()


# ============================================================================
# _get_option_chain
# ============================================================================


def test_get_option_chain_happy_path(toolkit):
    """Returns JSON chain from the reimplemented search→strikes client flow."""
    toolkit._client.get_option_chain.return_value = {
        "symbol": "AAPL",
        "conid": 265598,
        "months": ["JAN26", "FEB26"],
        "month": "JAN26",
        "call": [185.0, 190.0],
        "put": [180.0, 185.0],
    }
    text, fig = toolkit.execute("get_option_chain", {"symbol": "AAPL"})
    assert fig is None
    assert "months" in text
    assert "185.0" in text
    toolkit._client.get_option_chain.assert_called_once_with("AAPL", month=None, exchange="SMART")


def test_get_option_chain_passes_month_and_exchange(toolkit):
    """month (MMMYY) and exchange are forwarded to the client."""
    toolkit._client.get_option_chain.return_value = {"call": [], "put": []}
    toolkit.execute(
        "get_option_chain",
        {
            "symbol": "SPX",
            "month": "FEB26",
            "exchange": "CBOE",
        },
    )
    toolkit._client.get_option_chain.assert_called_once_with("SPX", month="FEB26", exchange="CBOE")


def test_get_option_chain_error(toolkit):
    """Propagates exception through _safe_error."""
    toolkit._client.get_option_chain.side_effect = RuntimeError("chain unavailable")
    text, fig = toolkit.execute("get_option_chain", {"symbol": "AAPL"})
    assert fig is None
    assert "unexpected" in text.lower()


# ============================================================================
# _run_scanner
# ============================================================================


def test_run_scanner_happy_path(toolkit):
    """Returns formatted scanner results."""
    toolkit._client.run_iserver_scanner.return_value = [
        {"symbol": "AAPL", "contractDescription": {"exchange": "NASDAQ"}},
        {"symbol": "MSFT", "contractDescription": {"exchange": "NASDAQ"}},
    ]
    text, fig = toolkit.execute("run_scanner", {"scan_code": "TOP_VOLUME_RATE", "instrument": "STK"})
    assert fig is None
    assert "AAPL" in text
    assert "MSFT" in text
    assert "2 results" in text


def test_run_scanner_no_results(toolkit):
    """Returns 'no results' message when scanner is empty."""
    toolkit._client.run_iserver_scanner.return_value = []
    text, fig = toolkit.execute("run_scanner", {"scan_code": "TOP_VOLUME_RATE"})
    assert fig is None
    assert "no results" in text.lower()


def test_run_scanner_error(toolkit):
    """Propagates exception through _safe_error."""
    toolkit._client.run_iserver_scanner.side_effect = RuntimeError("scanner down")
    text, fig = toolkit.execute("run_scanner", {"scan_code": "TOP_VOLUME_RATE"})
    assert fig is None
    assert "unexpected" in text.lower()


# ============================================================================
# _get_watchlists
# ============================================================================


def test_get_trading_schedule_happy_path(toolkit):
    """Returns JSON trading schedule."""
    toolkit._client.get_trading_schedule.return_value = {
        "tradingScheduleDate": [{"prop": [{"name": "TRADING_HOURS", "value": "0930-1600"}]}]
    }
    text, fig = toolkit.execute("get_trading_schedule", {"symbol": "AAPL"})
    assert fig is None
    assert "TRADING_HOURS" in text
    toolkit._client.get_trading_schedule.assert_called_once_with("STK", "AAPL", "SMART")


def test_get_trading_schedule_custom_params(toolkit):
    """Passes custom asset_class and exchange to client."""
    toolkit._client.get_trading_schedule.return_value = {}
    toolkit.execute("get_trading_schedule", {"symbol": "CL", "asset_class": "FUT", "exchange": "NYMEX"})
    toolkit._client.get_trading_schedule.assert_called_once_with("FUT", "CL", "NYMEX")


def test_get_trading_schedule_error(toolkit):
    """Propagates exception through _safe_error."""
    toolkit._client.get_trading_schedule.side_effect = RuntimeError("schedule unavailable")
    text, fig = toolkit.execute("get_trading_schedule", {"symbol": "AAPL"})
    assert fig is None
    assert "unexpected" in text.lower()


# ============================================================================
# _get_allocation
# ============================================================================


def test_delete_cache_happy_path(toolkit):
    """Deletes cache entry and returns confirmation."""
    toolkit._cache.check.return_value = True
    text, fig = toolkit.execute(
        "delete_cache", {"symbol": "AAPL", "timeframe": "1D", "period": "1Y", "end": "2026-05-22"}
    )
    assert fig is None
    assert "Deleted" in text
    assert "AAPL" in text
    toolkit._cache.delete.assert_called_once_with("AAPL", "1D", "1Y", "2026-05-22")


def test_delete_cache_miss(toolkit):
    """Returns 'No cached entry' when the entry does not exist."""
    toolkit._cache.check.return_value = False
    text, fig = toolkit.execute(
        "delete_cache", {"symbol": "FAKE", "timeframe": "1D", "period": "1Y", "end": "2026-05-22"}
    )
    assert fig is None
    assert "No cached entry" in text
    toolkit._cache.delete.assert_not_called()


# ============================================================================
# _modify_price_alert
# ============================================================================
