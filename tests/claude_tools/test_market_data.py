import json
from unittest.mock import patch

import pytest

from ibkr_core_mcp.claude_tools import _TODAY, _today_date

from .conftest import assert_tool_failed, assert_tool_succeeded


def _dated(days: int) -> int:
    """A YYYYMMDD int `days` from today. Dates are computed, never hardcoded: a fixture
    pinned to 20260918 silently changed meaning the day that contract expired (gap #58)."""
    from datetime import timedelta

    return int((_today_date() + timedelta(days=days)).strftime("%Y%m%d"))


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
    text, _fig = toolkit.execute(
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
        {
            "key": "AAPL_1D_1Y_2026-06-30_RTH",
            "rows": 252,
            "cached_at": "2026-06-30T12:00:00",
            "outside_rth": False,
            "listing": {"conid": 265598, "name": "APPLE INC", "exchange": "NASDAQ", "currency": "USD"},
        },
        {"key": "ESZ6_1D_6M_2026-10-03_ALL", "rows": 126, "cached_at": "2026-10-03T14:00:00", "outside_rth": True},
        {"key": "MSFT_1D_6M_2026-06-30", "rows": 126, "cached_at": "2026-06-29T08:00:00"},
    ]
    text, fig = toolkit.execute("list_cache", {})
    assert fig is None
    assert "Cached datasets (3)" in text
    assert (
        "AAPL_1D_1Y_2026-06-30_RTH: 252 bars, regular hours, cached 2026-06-30 — APPLE INC, NASDAQ, USD, conid 265598"
        in text
    )
    assert "ESZ6_1D_6M_2026-10-03_ALL: 126 bars, all hours, cached 2026-10-03" in text
    # A row written before 2.2.0 has no hours field and no reachable key; it is named as such.
    assert "MSFT_1D_6M_2026-06-30: 126 bars, legacy (pre-2.2.0 key, unreachable from 2.2.0), cached 2026-06-29" in text


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
    assert_tool_succeeded(text)
    assert fig is None
    assert "RSI" in text


def test_execute_get_market_snapshot_warns_on_partial_resolution(toolkit):
    # AAPL resolves; BADTICKER does not — output must name the skipped symbol
    def stocks_side_effect(syms):
        if syms == ["AAPL"]:
            return [
                {
                    "name": "APPLE INC",
                    "assetClass": "STK",
                    "contracts": [{"conid": 265598, "exchange": "NASDAQ", "isUS": True}],
                }
            ]
        return []

    toolkit._client.get_stocks.side_effect = stocks_side_effect
    toolkit._client.get_market_snapshot.return_value = [{"conid": 265598, "31": "185.0"}]
    text, fig = toolkit.execute("get_market_snapshot", {"symbols": ["AAPL", "BADTICKER"]})
    assert "BADTICKER" in text
    assert "omitted" in text.lower() or "could not resolve" in text.lower()
    assert fig is None


def test_execute_get_market_snapshot_invalid_conid_skipped(toolkit):
    toolkit._client.get_stocks.return_value = [
        {"name": "APPLE INC", "assetClass": "STK", "contracts": [{"conid": "N/A", "exchange": "NASDAQ", "isUS": True}]}
    ]
    toolkit._client.get_market_snapshot.return_value = []
    text, _fig = toolkit.execute("get_market_snapshot", {"symbols": ["AAPL"]})
    assert "Could not resolve" in text
    toolkit._client.get_market_snapshot.assert_not_called()


def test_execute_get_market_snapshot_fut_uses_futures_endpoint_not_search(toolkit):
    """FUT must resolve via /trsrv/futures, not /iserver/secdef/search.

    /iserver/secdef/search only documents STK, IND, BOND support.
    Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/contract/search-contract-by-symbol.md
    """
    toolkit._client.get_futures.return_value = [
        {"symbol": "ES", "conid": 111, "expirationDate": _dated(90), "ltd": _dated(90)},
        {"symbol": "ES", "conid": 222, "expirationDate": _dated(30), "ltd": _dated(30)},
    ]
    toolkit._client.get_market_snapshot.return_value = [{"conid": 222, "31": "5800.0", "6509": "R"}]
    text, _fig = toolkit.execute("get_market_snapshot", {"symbols": ["ES"], "sec_type": "FUT"})
    toolkit._client.search_contract.assert_not_called()
    toolkit._client.get_market_snapshot.assert_called_once_with([222])
    assert "5800.0" in text


def test_execute_get_market_snapshot_fut_no_contracts_found(toolkit):
    toolkit._client.get_futures.return_value = []
    text, _fig = toolkit.execute("get_market_snapshot", {"symbols": ["ZZFUT"], "sec_type": "FUT"})
    assert "Could not resolve" in text
    toolkit._client.get_market_snapshot.assert_not_called()


def test_execute_get_market_snapshot_exchange_filter_selects_listing(toolkit):
    """An explicit exchange pins the listing instead of taking whatever came first.

    Resolution goes through /trsrv/stocks, where `exchange` is a real field. The old
    path filtered /iserver/secdef/search results on a key that endpoint never returns
    (the code was `c.get("exchange")`; the exchange code lives in `description`), so
    this filter matched nothing in production and silently fell through — a defect this
    very test hid by mocking a field shape the API does not produce.
    """
    toolkit._client.get_stocks.return_value = [
        {
            "name": "ASML HOLDING NV",
            "assetClass": "STK",
            "contracts": [
                {"conid": 1, "exchange": "NYSE", "isUS": True},
                {"conid": 2, "exchange": "AMS", "isUS": False},
            ],
        }
    ]
    toolkit._client.get_market_snapshot.return_value = [{"conid": 2, "31": "700.0", "6509": "D"}]
    text, _fig = toolkit.execute("get_market_snapshot", {"symbols": ["ASML"], "exchange": "AMS"})
    toolkit._client.get_market_snapshot.assert_called_once_with([2])
    assert "700.0" in text


def test_execute_get_market_snapshot_exchange_filter_no_match_asks_instead_of_substituting(toolkit):
    """Inverted 2026-07-28. This test used to assert the opposite — "fall back to first
    result rather than failing outright — better to return something resolvable" — which
    is precisely the assumption that let a US ETF be priced in pesos. A listing the user
    did not ask for is not a lesser answer than none; it is a plausible number for the
    wrong instrument, and nothing about it looks wrong.

    No price may be returned, and the message must name what does exist so the user can
    be asked."""
    toolkit._client.get_stocks.return_value = [
        {"name": "GENERAL ELECTRIC", "assetClass": "STK", "contracts": [{"conid": 1, "exchange": "NYSE", "isUS": True}]}
    ]
    text, _fig = toolkit.execute("get_market_snapshot", {"symbols": ["GE"], "exchange": "NONEXISTENT"})
    toolkit._client.get_market_snapshot.assert_not_called()
    assert "no listing on NONEXISTENT" in text
    assert "NYSE" in text
    assert "Ask the user" in text


def test_resolve_snapshot_conid_ind_falls_back_to_con_id_key(toolkit):
    """IND/BOND still resolve via /iserver/secdef/search, which needs the
    .get("conid") or .get("con_id") fallback — some IBKR responses key it "con_id"
    (CLAUDE.md convention).

    Retargeted from STK to IND on 2026-07-28: STK now resolves via /trsrv/stocks, whose
    documented response keys the field "conid" and never "con_id"."""
    toolkit._client.search_contract.return_value = [{"con_id": 42, "description": "SMART"}]
    resolved = toolkit._resolve_snapshot_conid("SPX", "IND", None)
    assert resolved.error is None
    assert resolved.conid == 42


# ── Ambiguous tickers: a ticker is not a unique key ──────────────────────────
#
# Every fixture below is the real /trsrv/stocks response shape, captured from the live
# gateway on 2026-07-28. IGV is the case that motivated all of this: iShares Expanded
# Tech-Software trades on BATS in USD and on MEXI in MXN, and the SAME ticker is also an
# unrelated Italian company. The old resolver took /iserver/secdef/search's first result,
# which for IGV is the Mexican listing — so a US ETF was reported at an MXN price, off by
# the USD/MXN rate. AAPL's first result happens to be NASDAQ, so the same code was right
# by luck there, which is why this went unnoticed.

IGV_LISTINGS = [
    {
        "name": "ISHARES EXPANDED TECH-SOFTWA",
        "assetClass": "STK",
        "contracts": [
            {"conid": 12658199, "exchange": "BATS", "isUS": True},
            {"conid": 325209548, "exchange": "MEXI", "isUS": False},
        ],
    },
    {
        "name": "I GRANDI VIAGGI SPA",
        "assetClass": "STK",
        "contracts": [
            {"conid": 195853874, "exchange": "BVME", "isUS": False},
        ],
    },
]


def test_ambiguous_ticker_resolves_to_the_us_listing_not_the_first_result(toolkit):
    """The IGV regression. A bare ticker is a US ticker by convention, so the single
    isUS listing wins — and the Mexican one, which /iserver/secdef/search returned
    first, must not be chosen."""
    toolkit._client.get_stocks.return_value = IGV_LISTINGS
    toolkit._client.get_secdef_info.return_value = [{"conid": 12658199, "currency": "USD"}]

    resolved = toolkit._resolve_snapshot_conid("IGV", "STK", None)

    assert resolved.error is None
    assert resolved.conid == 12658199  # BATS/USD
    assert resolved.conid != 325209548  # MEXI/MXN — the old answer
    assert resolved.currency == "USD"


def test_explicit_exchange_selects_the_non_us_listing(toolkit):
    """Non-US is reachable, but only when the user names it — never by default."""
    toolkit._client.get_stocks.return_value = IGV_LISTINGS
    toolkit._client.get_secdef_info.return_value = [{"conid": 325209548, "currency": "MXN"}]

    resolved = toolkit._resolve_snapshot_conid("IGV", "STK", "MEXI")

    assert resolved.error is None
    assert resolved.conid == 325209548
    assert resolved.currency == "MXN"


def test_no_us_listing_asks_instead_of_picking(toolkit):
    """Zero US listings is a question, not a default. No conid, and the message must
    name every candidate WITH its company, since the same ticker can be a different
    issuer entirely."""
    toolkit._client.get_stocks.return_value = [
        {
            "name": "I GRANDI VIAGGI SPA",
            "assetClass": "STK",
            "contracts": [
                {"conid": 195853874, "exchange": "BVME", "isUS": False},
            ],
        },
    ]

    resolved = toolkit._resolve_snapshot_conid("IGV", "STK", None)

    assert resolved.conid == 0
    assert resolved.ambiguous is True
    assert "no US listing" in resolved.error
    assert "BVME" in resolved.error
    assert "I GRANDI VIAGGI SPA" in resolved.error
    assert "Ask the user" in resolved.error


def test_several_us_listings_asks_instead_of_picking(toolkit):
    """Two US listings is the other side of the same rule — 'default to US' does not
    decide between two US answers, so it must ask rather than take the first."""
    toolkit._client.get_stocks.return_value = [
        {
            "name": "SOME CO",
            "assetClass": "STK",
            "contracts": [
                {"conid": 111, "exchange": "NASDAQ", "isUS": True},
                {"conid": 222, "exchange": "ARCA", "isUS": True},
            ],
        },
    ]

    resolved = toolkit._resolve_snapshot_conid("DUP", "STK", None)

    assert resolved.conid == 0
    assert resolved.ambiguous is True
    assert "NASDAQ" in resolved.error and "ARCA" in resolved.error
    assert "do not report a price" in resolved.error


def test_ambiguity_reaches_the_user_and_no_price_is_fetched(toolkit):
    """End to end: the question must survive to the tool output, and no market-data
    call may be made for a symbol whose listing is undetermined."""
    toolkit._client.get_stocks.return_value = [
        {
            "name": "I GRANDI VIAGGI SPA",
            "assetClass": "STK",
            "contracts": [
                {"conid": 195853874, "exchange": "BVME", "isUS": False},
            ],
        },
    ]

    text, _fig = toolkit.execute("get_market_snapshot", {"symbols": ["IGV"]})

    toolkit._client.get_market_snapshot.assert_not_called()
    assert "no US listing" in text
    assert "Ask the user" in text


def test_snapshot_always_states_the_currency(toolkit):
    """A price without its unit is not terser, it is ambiguous — the IGV failure was
    readable as a plausible USD number."""
    toolkit._client.get_stocks.return_value = IGV_LISTINGS
    toolkit._client.get_secdef_info.return_value = [{"conid": 12658199, "currency": "USD"}]
    toolkit._client.get_market_snapshot.return_value = [{"conid": 12658199, "31": "95.0", "6509": "R"}]

    text, _fig = toolkit.execute("get_market_snapshot", {"symbols": ["IGV"]})

    assert '"_currency": "USD"' in text


def test_snapshot_says_unknown_rather_than_omitting_the_currency(toolkit):
    """When secdef/info cannot be read the key must still be present. An absent
    currency is indistinguishable from USD; 'UNKNOWN' is not."""
    from ibkr_core_mcp.exceptions import IBKRAPIError

    toolkit._client.get_stocks.return_value = IGV_LISTINGS
    toolkit._client.get_secdef_info.side_effect = IBKRAPIError("boom")
    toolkit._client.get_market_snapshot.return_value = [{"conid": 12658199, "31": "95.0", "6509": "R"}]

    text, _fig = toolkit.execute("get_market_snapshot", {"symbols": ["IGV"]})

    assert '"_currency": "UNKNOWN"' in text


def test_execute_get_market_snapshot_cash_uses_currency_pairs_not_search(toolkit):
    """CASH must resolve via /iserver/currency/pairs, not /iserver/secdef/search.

    secType=CASH is not in the documented STK/IND/BOND list for secdef/search.
    Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/contract/currency-pairs.md
    """
    toolkit._client.get_currency_pairs.return_value = [
        {"symbol": "EUR.USD", "conid": 12087792, "ccyPair": "USD"},
        {"symbol": "EUR.JPY", "conid": 28201823, "ccyPair": "JPY"},
    ]
    toolkit._client.get_market_snapshot.return_value = [{"conid": 12087792, "31": "1.0850", "6509": "R"}]
    text, _fig = toolkit.execute("get_market_snapshot", {"symbols": ["EUR.USD"], "sec_type": "CASH"})
    toolkit._client.get_currency_pairs.assert_called_once_with("EUR")
    toolkit._client.search_contract.assert_not_called()
    toolkit._client.get_market_snapshot.assert_called_once_with([12087792])
    assert "1.0850" in text


def test_execute_get_market_snapshot_cash_invalid_format_rejected(toolkit):
    text, _fig = toolkit.execute("get_market_snapshot", {"symbols": ["EURUSD"], "sec_type": "CASH"})
    assert "Could not resolve" in text
    toolkit._client.get_currency_pairs.assert_not_called()
    toolkit._client.get_market_snapshot.assert_not_called()


def test_execute_get_market_snapshot_cash_pair_not_found(toolkit):
    toolkit._client.get_currency_pairs.return_value = [
        {"symbol": "EUR.JPY", "conid": 28201823, "ccyPair": "JPY"},
    ]
    text, _fig = toolkit.execute("get_market_snapshot", {"symbols": ["EUR.USD"], "sec_type": "CASH"})
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

    text, _fig = toolkit.execute("fetch_market_data", {"symbol": "AAPL", "period": "1Y", "bar": "1d"})
    assert "AAPL" in text
    assert "IBKR" in text
    toolkit._cache.save.assert_called_once()


def test_fetch_market_data_no_contract(toolkit):
    toolkit._cache.check.return_value = False
    # STK resolves via /trsrv/stocks since 2026-07-28, not /iserver/secdef/search.
    toolkit._client.get_stocks.return_value = []
    text, _fig = toolkit.execute("fetch_market_data", {"symbol": "FAKE", "period": "1Y", "bar": "1d"})
    assert "Could not resolve conid" in text


def test_fetch_market_data_empty_data(toolkit):
    """Paginated endpoint returning empty → error message with 'no data'."""
    toolkit._cache.check.return_value = False
    toolkit._client.search_contract.return_value = [{"conid": 265598}]
    toolkit._client.get_market_history_paginated.return_value = {"data": []}
    with patch("time.sleep"):
        text, _fig = toolkit.execute("fetch_market_data", {"symbol": "AAPL", "period": "1Y", "bar": "1d"})
    assert "no data" in text.lower()


# ── Market-data batch step 1 (2026-10-02): the result says what was fetched ────────────────

_IGV_BATS = {"conid": 12658199, "name": "ISHARES EXPANDED TECH-SOFTWA", "exchange": "BATS", "currency": "USD"}


def _two_daily_bars():
    return {
        "data": [{"t": 1_758_000_000_000 + i * 86_400_000, "o": 1, "h": 1, "l": 1, "c": 1, "v": 1} for i in range(2)]
    }


def test_the_fetch_result_names_the_listing_and_the_end_date_it_was_given(toolkit):
    """IGV's Mexican listing in pesos was served as IGV: the result never said which listing,
    in which currency, the bars came from. It now names the listing the resolver chose — the
    fields it already had in hand — and hands the same to the cache beside the bars."""
    toolkit._cache.check.return_value = False
    toolkit._client.get_stocks.return_value = _igv_stocks()
    toolkit._client.get_secdef_info.return_value = [{"conid": 12658199, "currency": "USD"}]
    toolkit._client.get_market_history_paginated.return_value = _two_daily_bars()

    text, _ = toolkit.execute("fetch_market_data", {"symbol": "IGV", "period": "6m", "end": "2026-09-30"})

    assert "ISHARES EXPANDED TECH-SOFTWA" in text and "BATS" in text and "USD" in text and "conid 12658199" in text
    assert "(6m) ending 2026-09-30 (as given), regular trading hours (by default for STK), from IBKR" in text, text
    assert toolkit._cache.save.call_args.kwargs["listing"] == _IGV_BATS


def test_a_fetch_without_an_end_date_says_it_used_today(toolkit):
    """The fetch filled `end` in silently while the indicator and backtest tools require it,
    so a model that fetched without one could not know which value to pass them next."""
    toolkit._cache.check.return_value = False
    toolkit._client.get_market_history_paginated.return_value = _two_daily_bars()

    text, _ = toolkit.execute("fetch_market_data", {"symbol": "AAPL", "period": "6m"})

    assert (
        f"(6m) ending {_TODAY()} (today, by default), regular trading hours (by default for STK), from IBKR" in text
    ), text


def test_a_cache_hit_names_the_listing_the_entry_records_or_says_none_is_recorded(toolkit):
    """A hit is where a wrong listing hid longest — served as a normal hit until flushed."""
    import pandas as pd

    toolkit._cache.check.return_value = True
    toolkit._cache.load.return_value = pd.DataFrame({"close": [1.0, 2.0]}, index=pd.date_range("2026-09-01", periods=2))

    toolkit._cache.entry.return_value = {"symbol": "IGV", "listing": _IGV_BATS}
    named, _ = toolkit.execute("fetch_market_data", {"symbol": "IGV", "period": "6m", "end": "2026-09-30"})
    toolkit._cache.entry.return_value = {"symbol": "IGV"}
    unnamed, _ = toolkit.execute("fetch_market_data", {"symbol": "IGV", "period": "6m", "end": "2026-09-30"})

    assert "ISHARES EXPANDED TECH-SOFTWA" in named and "BATS" in named and "USD" in named, named
    assert "listing not recorded" in unnamed and "ISHARES" not in unnamed, unnamed


@pytest.mark.parametrize("tool", ["add_indicators", "run_backtest", "get_analytics"])
def test_a_cache_miss_lists_what_is_cached_for_the_symbol(toolkit, tool):
    """ "No cached data … fetch it first" sent the model back to repeat the fetch it had just
    made under another end date. The miss now lists the symbol's cached windows so the model
    can match one, and when there is none, says what end the fetch defaults to."""
    toolkit._cache.check.return_value = False
    inputs = {"symbol": "IGV", "timeframe": "1D", "period": "6m", "end": "2026-09-30", "code": "df['signal'] = 1"}

    toolkit._cache.list_cached.return_value = [
        {"key": "IGV_1D_6M_2026-10-02", "symbol": "IGV", "timeframe": "1D", "period": "6m", "end": "2026-10-02"},
        {"key": "AAPL_1D_6M_2026-10-02", "symbol": "AAPL", "timeframe": "1D", "period": "6m", "end": "2026-10-02"},
    ]
    listed, _ = toolkit.execute(tool, inputs)
    toolkit._cache.list_cached.return_value = []
    empty, _ = toolkit.execute(tool, inputs)

    assert "No cached data for IGV 1D 6m ending 2026-09-30" in listed, listed
    assert "IGV 1D 6m ending 2026-10-02" in listed and "AAPL" not in listed, listed
    assert "Nothing is cached for IGV" in empty and "defaults to today" in empty, empty


# ── Market-data batch step 2 (2026-10-03): security type, one contract per key, the hours ────
#
# Probe evidence (claudia_ui/docs/plans/2026-10-03-outside-rth-probe/): IBKR's daily stock bar
# changes with outsideRth on 20 of 20 days; a futures all-hours daily bar is stamped at its
# session OPEN (18:00 ET the evening before; Sunday's stamp is Monday's session); the day
# session is stamped 09:30 ET on the session's own date.


def _es_contract_info(local_symbol="ESZ6", month="202612", maturity=None, exchange="CME"):
    return {
        "local_symbol": local_symbol,
        "contract_month": month,
        "maturity_date": maturity if maturity is not None else _dated(76),
        "company_name": "E-mini S&P 500",
        "multiplier": "50",
        "exchange": exchange,
        "currency": "USD",
    }


def _front_month_es(toolkit):
    """Two ES rows: one past its last trade date, one live — the resolver must take the live one."""
    expired, live = _dated(-15), _dated(76)
    toolkit._client.get_futures.return_value = [
        {"symbol": "ES", "conid": 649180671, "expirationDate": expired, "ltd": expired},
        {"symbol": "ES", "conid": 515416632, "expirationDate": live, "ltd": live},
    ]
    toolkit._client.get_contract_info.return_value = _es_contract_info()
    toolkit._client.get_secdef_info.return_value = [{"conid": 515416632, "currency": "USD"}]


def test_a_futures_root_fetches_the_front_month_and_caches_it_under_the_contracts_own_symbol(toolkit):
    """Point 1 and 2 of step 2: `ES` means the front-month contract's own bars, named in IB's
    strings, cached under its local symbol so ESU6 and ESZ6 never share an entry and a roll
    produces a new key by itself; all hours by default for a future, stated."""
    _front_month_es(toolkit)
    toolkit._cache.check.return_value = False
    toolkit._client.get_market_history_paginated.return_value = _two_daily_bars()

    text, _ = toolkit.execute("fetch_market_data", {"symbol": "ES", "period": "6m", "sec_type": "FUT"})

    toolkit._cache.check.assert_called_once_with("ESZ6", "1D", "6m", _TODAY(), outside_rth=True)
    toolkit._client.get_market_history_paginated.assert_called_once_with(
        515416632, period="6m", bar="1d", outside_rth=True
    )
    saved = toolkit._cache.save.call_args
    assert saved.args[1] == "ESZ6" and saved.kwargs["outside_rth"] is True
    assert saved.kwargs["listing"] == {
        "conid": 515416632,
        "name": f"E-mini S&P 500 · ESZ6 · DEC26 · expires {_iso(_dated(76))}",
        "exchange": "CME",
        "currency": "USD",
        "root": "ES",
    }
    assert "Fetched ESZ6 FUT 1D (6m)" in text and "all trading hours (by default for FUT)" in text, text
    assert "E-mini S&P 500 · ESZ6 · DEC26" in text and "CME, USD, conid 515416632" in text, text
    assert "under ESZ6" in text and "outside_rth=true" in text and "ESU6" not in text, text


def _iso(yyyymmdd: int) -> str:
    t = str(yyyymmdd)
    return f"{t[:4]}-{t[4:6]}-{t[6:]}"


def test_a_pinned_conid_fetches_that_contract_and_an_expired_one_says_so(toolkit):
    """Point 1's addition: `conid` pins one contract, skipping the front-month rule — an expired
    contract's history is exactly what it is for, and the result says "expired". IBKR serves
    it for about a year (ESU5 at 12 months, ESM5 refused at 15 — 2026-09-25)."""
    toolkit._cache.check.return_value = False
    toolkit._client.get_contract_info.return_value = _es_contract_info("ESU6", "202609", _dated(-15))
    toolkit._client.get_secdef_info.return_value = [{"conid": 649180671, "currency": "USD"}]
    toolkit._client.get_market_history_paginated.return_value = _two_daily_bars()

    text, _ = toolkit.execute(
        "fetch_market_data", {"symbol": "ES", "period": "6m", "sec_type": "FUT", "conid": 649180671}
    )

    toolkit._client.get_futures.assert_not_called()
    toolkit._client.get_contract_info.assert_called_with(649180671)
    assert toolkit._cache.save.call_args.args[1] == "ESU6"
    assert f"ESU6 · SEP26 · expired {_iso(_dated(-15))}" in text, text


def test_a_contract_ibkr_cannot_describe_fetches_nothing(toolkit):
    """Fail closed: no local symbol from /iserver/contract/{conid}/info means no key to cache
    under and no name to show — nothing is fetched, nothing is written."""
    toolkit._cache.check.return_value = False
    toolkit._client.get_contract_info.return_value = {"company_name": "E-mini S&P 500"}

    text, _ = toolkit.execute(
        "fetch_market_data", {"symbol": "ES", "period": "6m", "sec_type": "FUT", "conid": 649180671}
    )

    toolkit._client.get_market_history_paginated.assert_not_called()
    toolkit._cache.save.assert_not_called()
    assert "could not" in text.lower() and "649180671" in text and "nothing" in text.lower(), text


def test_the_hours_are_stated_by_default_and_as_given_and_reach_the_key(toolkit):
    """Point 4: STK defaults to regular hours, every result says which hours and why."""
    toolkit._cache.check.return_value = False
    toolkit._client.get_market_history_paginated.return_value = _two_daily_bars()

    default, _ = toolkit.execute("fetch_market_data", {"symbol": "AAPL", "period": "6m"})
    toolkit._client.get_market_history_paginated.assert_called_with(265598, period="6m", bar="1d", outside_rth=False)
    assert "AAPL STK (by default)" in default and "regular trading hours (by default for STK)" in default, default
    assert toolkit._cache.save.call_args.kwargs["outside_rth"] is False

    given, _ = toolkit.execute("fetch_market_data", {"symbol": "AAPL", "period": "6m", "outside_rth": True})
    toolkit._client.get_market_history_paginated.assert_called_with(265598, period="6m", bar="1d", outside_rth=True)
    assert "all trading hours (as given)" in given and "under AAPL (all hours)" in given, given
    assert toolkit._cache.save.call_args.kwargs["outside_rth"] is True


@pytest.mark.parametrize(
    "inputs, expect",
    [
        ({"symbol": "SPX", "period": "6m", "sec_type": "IND"}, "STK, FUT"),
        ({"symbol": "IGV", "period": "6m", "conid": 325209548}, "futures contract"),
    ],
    ids=["type-not-offered", "conid-on-a-stock"],
)
def test_a_type_outside_the_offer_and_a_conid_on_a_stock_are_refused_before_any_read(toolkit, inputs, expect):
    """Point 3: the enum is IB's codes and lists only what this tool serves; the handler
    refuses the rest itself, since the schema is not enforced server-side."""
    text, _ = toolkit.execute("fetch_market_data", inputs)
    assert expect in text, text
    toolkit._client.get_stocks.assert_not_called()
    toolkit._client.get_futures.assert_not_called()
    toolkit._cache.check.assert_not_called()


def test_all_hours_futures_bars_are_printed_as_opens_in_et_with_the_reading_rule(toolkit):
    """Point 4, the trap: an all-hours futures daily bar is stamped at its session open, 18:00 ET
    the evening before. The stamp is IBKR's and is kept; the result prints it as an open, in
    ET, with the rule for reading it — never a bare date one day early."""
    _front_month_es(toolkit)
    toolkit._cache.check.return_value = False
    # Thursday 2026-10-01 22:00 UTC = 18:00 ET: the open of Friday's session.
    thursday_open_ms = 1_790_892_000_000
    toolkit._client.get_market_history_paginated.return_value = {
        "data": [
            {"t": thursday_open_ms - 86_400_000, "o": 1, "h": 1, "l": 1, "c": 1, "v": 1},
            {"t": thursday_open_ms, "o": 1, "h": 1, "l": 1, "c": 1, "v": 1},
        ]
    }

    text, _ = toolkit.execute("fetch_market_data", {"symbol": "ES", "period": "6m", "sec_type": "FUT"})

    assert "stamped at their open (ET)" in text and "2026-10-01 18:00" in text, text
    assert "Thursday 18:00 is Friday's session" in text, text
    assert "2026-10-02" not in text, text


# ============================================================================
# _search_contract
# ============================================================================


def _igv_stocks(us_conids=(12658199,)):
    """A /trsrv/stocks response for IGV: the US/BATS listing plus the Mexican one.

    The live shape, measured 2026-08-05. `isUS` is the field that makes this endpoint —
    and not /iserver/secdef/search — able to answer which listing was meant.
    """
    return [
        {
            "name": "ISHARES EXPANDED TECH-SOFTWA",
            "assetClass": "STK",
            "contracts": [
                {"conid": 325209548, "exchange": "MEXI", "isUS": 325209548 in us_conids},
                {"conid": 12658199, "exchange": "BATS", "isUS": 12658199 in us_conids},
            ],
        }
    ]


def test_search_contract_resolves_stk_to_exactly_one_listing(toolkit):
    """One contract, with its currency — not a list to choose from.

    The tool's description tells the model to use it to discover conids, so returning
    several is the ambiguity, not a service. Currency is included because `_Resolved`
    carries it; /iserver/secdef/search has no currency field at all, so the shape this
    replaced could not have stated one.
    """
    toolkit._client.get_stocks.return_value = _igv_stocks()
    with patch.object(toolkit, "_listing_currency", return_value="USD"):
        payload = json.loads(toolkit.execute("search_contract", {"symbol": "igv"})[0])

    assert payload == {
        "symbol": "IGV",
        "sec_type": "STK",
        "conid": 12658199,
        "currency": "USD",
        "exchange": "US listing (default)",
    }


def test_search_contract_does_not_use_secdef_search_for_stk(toolkit):
    """Delegation is the point: one definition of 'which listing', not two that drift.

    /iserver/secdef/search returns neither isUS nor a currency and its order is
    undocumented — contracts[0] for IGV is the Mexican listing.
    """
    toolkit._client.get_stocks.return_value = _igv_stocks()
    with patch.object(toolkit, "_listing_currency", return_value="USD"):
        toolkit.execute("search_contract", {"symbol": "IGV"})
    toolkit._client.search_contract.assert_not_called()


def test_search_contract_asks_instead_of_ranking_when_ambiguous(toolkit):
    """Two US listings is a question. The reply must carry NO conid to lift.

    Ranking the candidates US-first was tried and rejected: it still left the pick to the
    model, so correctness depended on it reading a flag rather than on the code.
    """
    toolkit._client.get_stocks.return_value = [
        {
            "name": "AMBIG CO",
            "assetClass": "STK",
            "contracts": [
                {"conid": 111, "exchange": "NASDAQ", "isUS": True},
                {"conid": 222, "exchange": "ARCA", "isUS": True},
            ],
        }
    ]
    text, fig = toolkit.execute("search_contract", {"symbol": "AMB"})

    assert fig is None
    assert "ambiguous" in text.lower() and "Ask the user" in text
    assert "NASDAQ" in text and "ARCA" in text, "candidates must be named"
    assert not text.lstrip().startswith("{"), "a question is prose, not a liftable payload"


def test_search_contract_asks_when_there_is_no_us_listing(toolkit):
    """A foreign-only ticker must never be silently resolved to its foreign listing."""
    toolkit._client.get_stocks.return_value = [
        {
            "name": "I GRANDI VIAGGI SPA",
            "assetClass": "STK",
            "contracts": [{"conid": 195853874, "exchange": "BVME", "isUS": False}],
        }
    ]
    text, _ = toolkit.execute("search_contract", {"symbol": "IGV"})

    assert "no US listing" in text
    assert "BVME" in text and "Ask the user" in text


def test_search_contract_exchange_pins_a_named_listing(toolkit):
    """The answer to the tool's own question: re-call naming the market."""
    toolkit._client.get_stocks.return_value = _igv_stocks()
    with patch.object(toolkit, "_listing_currency", return_value="MXN"):
        payload = json.loads(toolkit.execute("search_contract", {"symbol": "IGV", "exchange": "MEXI"})[0])

    assert payload["conid"] == 325209548
    assert payload["currency"] == "MXN", "a non-US listing must still state its currency"
    assert payload["exchange"] == "MEXI"


def test_search_contract_states_unknown_currency_rather_than_omitting_it(toolkit):
    """A missing unit reads as 'the usual currency', which is the assumption to remove."""
    toolkit._client.get_stocks.return_value = _igv_stocks()
    with patch.object(toolkit, "_listing_currency", return_value=None):
        payload = json.loads(toolkit.execute("search_contract", {"symbol": "IGV"})[0])
    assert payload["currency"] == "UNKNOWN"


def test_search_contract_ind_still_returns_raw_matches(toolkit):
    """/trsrv/stocks is stocks-only, so IND/BOND keep the unranked passthrough."""
    toolkit._client.search_contract.return_value = [{"conid": "416904", "symbol": "SPX"}]
    rows = json.loads(toolkit.execute("search_contract", {"symbol": "SPX", "sec_type": "IND"})[0])
    toolkit._client.search_contract.assert_called_once_with("SPX", "IND")
    toolkit._client.get_stocks.assert_not_called()
    assert rows[0]["conid"] == "416904"


def test_search_contract_ind_no_results(toolkit):
    """Returns 'no contracts found' when IBKR returns an empty list."""
    toolkit._client.search_contract.return_value = []
    text, fig = toolkit.execute("search_contract", {"symbol": "XYZ99", "sec_type": "IND"})
    assert fig is None
    assert "No contracts found" in text
    assert "XYZ99" in text


# ============================================================================
# _get_futures
# ============================================================================


def test_get_futures_happy_path(toolkit):
    """Returns JSON-formatted futures contracts."""
    toolkit._client.get_futures.return_value = [
        {"symbol": "ESZ6", "conid": 551601958, "expirationDate": _dated(90), "ltd": _dated(90)},
        {"symbol": "ESH7", "conid": 551601959, "expirationDate": _dated(180), "ltd": _dated(180)},
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
    """Returns error when the symbol resolves to no listing."""
    # STK resolves via /trsrv/stocks since 2026-07-28, not /iserver/secdef/search.
    toolkit._client.get_stocks.return_value = []
    text, fig = toolkit.execute("get_contract_info", {"symbol": "FAKESYM"})
    assert fig is None
    assert "Could not resolve conid" in text


def test_get_contract_info_error(toolkit):
    """Propagates client exception through _safe_error."""
    toolkit._client.search_contract.return_value = [{"conid": 265598}]
    toolkit._client.get_contract_info_and_rules.side_effect = RuntimeError("timeout")
    text, fig = toolkit.execute("get_contract_info", {"symbol": "AAPL"})
    assert fig is None
    assert_tool_failed(text, containing="unexpected error")


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
    assert_tool_failed(text, containing="unexpected error")


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
    assert_tool_failed(text, containing="unexpected error")


# ============================================================================
# _get_watchlists
# ============================================================================


def test_get_trading_schedule_happy_path(toolkit):
    """Returns JSON trading schedule.

    Asserted `("STK", "AAPL", "SMART")` until 2026-09-16. That was the handler's default and
    it returns an empty list from the real endpoint, so this test pinned the defect
    (TOOL-R1). The payload below is also invented — `tradingScheduleDate` is a key inside a
    `schedules[]` entry, not a top-level one — which is why a shape test could not notice;
    it is now the shape the wire actually returns.
    """
    toolkit._client.get_trading_schedule.return_value = [
        {
            "id": "p102082",
            "exchange": "ISLAND",
            "timezone": "America/New_York",
            "schedules": [{"tradingScheduleDate": "20260917", "sessions": [{"prop": "LIQUID"}]}],
        }
    ]
    text, fig = toolkit.execute("get_trading_schedule", {"symbol": "AAPL"})
    assert fig is None
    assert "LIQUID" in text
    toolkit._client.get_trading_schedule.assert_called_once_with("STK", "AAPL", "")


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
    assert_tool_failed(text, containing="unexpected error")


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
    toolkit._cache.delete.assert_called_once_with("AAPL", "1D", "1Y", "2026-05-22", outside_rth=False)


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


def test_get_futures_is_sorted_by_expiry_and_flags_the_front_month(toolkit):
    """claudia_ui gap #37 (2026-09-10): /trsrv/futures listed Dec 2026 first and the model
    read list position as a volume ranking. Rows come back sorted per root symbol with the
    earliest flagged, so the front month is stated, not inferred."""
    near, far = _dated(30), _dated(120)
    toolkit._client.get_futures.return_value = [
        {"symbol": "ES", "conid": 515416632, "expirationDate": far, "ltd": far},
        {"symbol": "NQ", "conid": 3, "expirationDate": far, "ltd": far},
        {"symbol": "ES", "conid": 649180671, "expirationDate": near, "ltd": near},
        {"symbol": "NQ", "conid": 4, "expirationDate": near, "ltd": near},
    ]
    text, _fig = toolkit.execute("get_futures", {"symbols": ["ES", "NQ"]})
    rows = json.loads(text)
    assert [(r["symbol"], r["conid"], r["front_month"]) for r in rows] == [
        ("ES", 649180671, True),
        ("ES", 515416632, False),
        ("NQ", 4, True),
        ("NQ", 3, False),
    ]


def test_front_month_skips_a_contract_whose_last_trade_date_has_passed(toolkit):
    """Gap #58, measured live 2026-09-20 two days after the Sep roll: /trsrv/futures still
    returned ESU6 (ltd 20260918) among 22 ES rows, and "earliest expiry" picked it. IBKR then
    answers an order with `{"error":"Order is already expired."}` — but only after Gate 1 and
    Gate 2 — while get_market_snapshot quietly returned the dead contract's stale price."""
    expired, live = _dated(-2), _dated(90)
    toolkit._client.get_futures.return_value = [
        {"symbol": "ES", "conid": 649180671, "expirationDate": expired, "ltd": expired},
        {"symbol": "ES", "conid": 515416632, "expirationDate": live, "ltd": live},
    ]
    rows = json.loads(toolkit.execute("get_futures", {"symbols": ["ES"]})[0])
    flagged = [r for r in rows if r["front_month"]]
    assert [r["conid"] for r in flagged] == [515416632], "the expired contract must not be the front month"


def test_a_contract_past_its_ltd_is_not_front_month_while_its_expiration_date_is_ahead(toolkit):
    """The ES shape: Dec-26 reports expirationDate 20261218 and ltd 20261217 (measured
    2026-09-20), so `ltd` is the earlier date and the one that decides. (Named "prefers ltd"
    until F16 showed the CL shape runs the other way — the earlier date decides, whichever.)"""
    live = _dated(60)
    toolkit._client.get_futures.return_value = [
        # Expiry still in the future, but trading has already stopped.
        {"symbol": "ES", "conid": 111, "expirationDate": _dated(1), "ltd": _dated(-1)},
        {"symbol": "ES", "conid": 222, "expirationDate": live, "ltd": live},
    ]
    rows = json.loads(toolkit.execute("get_futures", {"symbols": ["ES"]})[0])
    assert [r["conid"] for r in rows if r["front_month"]] == [222]


# One rule must decide. `_last_trade_key` reads the earlier of `ltd` and `expirationDate` —
# it read `ltd` first until F16 — and settles tradeability; `_expiration_key` read
# `expirationDate` ALONE and settled both the ordering
# and which row gets flagged, so the two disagreed about what "has a date" even means:
#
#   * a tradeable row reporting only `ltd` was never flagged front month, because
#     `_expiration_key` returned 0 for it;
#   * where `ltd` and `expirationDate` rank differently, the front month was chosen by
#     `expirationDate` — the field this code's own docstring says does NOT decide;
#   * worst, `_resolve_snapshot_conid` picked `min(tradeable, key=_expiration_key)`, and an
#     undated row keys to 0, so a row with NO date beat every dated one and became the
#     contract a bare root resolves to.
#
# Not observed live — IBKR sends both fields for ES — so this is a latent inconsistency
# rather than a measured defect, and it is fixed because the two functions must agree, not
# because a wire shape was seen.


def test_front_month_is_flagged_on_a_row_that_reports_only_ltd(toolkit):
    """`ltd` is one of the two dates that decide tradeability, so a row carrying only `ltd`
    is dated for every purpose."""
    toolkit._client.get_futures.return_value = [
        {"symbol": "ES", "conid": 555, "ltd": _dated(30)},
        {"symbol": "ES", "conid": 666, "ltd": _dated(120)},
    ]
    rows = json.loads(toolkit.execute("get_futures", {"symbols": ["ES"]})[0])
    assert [r["conid"] for r in rows if r["front_month"]] == [555], rows


def test_front_month_ORDERING_follows_the_earlier_date_when_ltd_is_it(toolkit):
    """Both tradeable; `ltd` ranks them one way and `expirationDate` the other, and `ltd` is
    the earlier date on each row (the ES shape), so `ltd` chooses the front month."""
    toolkit._client.get_futures.return_value = [
        {"symbol": "XX", "conid": 777, "ltd": _dated(10), "expirationDate": _dated(90)},
        {"symbol": "XX", "conid": 888, "ltd": _dated(40), "expirationDate": _dated(50)},
    ]
    rows = json.loads(toolkit.execute("get_futures", {"symbols": ["XX"]})[0])
    assert [r["conid"] for r in rows if r["front_month"]] == [777], rows


# Neither field alone is the last trade date for every root (claudia_ui gap #71, register F16,
# measured live 2026-09-24). For ES, `ltd` is the earlier field (Dec-26: `expirationDate`
# 20261218, `ltd` 20261217). For NYMEX energy it is the LATER one: CLV6 reported
# `expirationDate` 20260922 and `ltd` 20261001 — there `ltd` is the first day of the contract
# month, after trading has stopped — so "`ltd`, falling back to `expirationDate`" kept the
# expired October CL as the front month after the roll, for as long as IBKR still listed it (two
# days after expiry it did, by day seven it no longer did), and a bare `CL` resolved to a
# contract whose quote was a prior close with no bid or ask. The earlier of the two is right
# for both shapes and, by construction, can never keep a contract past either date.


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        pytest.param({"expirationDate": 20261218, "ltd": 20261217}, 20261217, id="ES: ltd earlier"),
        pytest.param({"expirationDate": 20260922, "ltd": 20261001}, 20260922, id="CL: expirationDate earlier"),
        pytest.param({"expirationDate": 20261214, "ltd": 20261214}, 20261214, id="equal (DX reports them equal)"),
        pytest.param({"ltd": 20261217}, 20261217, id="only ltd"),
        pytest.param({"expirationDate": 20261218}, 20261218, id="only expirationDate"),
        pytest.param({"expirationDate": "not a date", "ltd": None}, 0, id="nothing usable"),
        pytest.param({}, 0, id="undated"),
    ],
)
def test_the_last_trade_key_is_the_earlier_of_ltd_and_expiration_date(row, expected):
    """One definition — the same as claudia_ui's `order_flow._last_trade_key` (gap #71)."""
    from ibkr_core_mcp.claude_tools import _last_trade_key

    assert _last_trade_key(row) == expected


def test_front_month_skips_a_contract_past_its_expiration_date_even_while_ltd_is_ahead(toolkit):
    """The CL case of 2026-09-24: two days after CLV6 stopped trading (its `expirationDate`),
    its `ltd` still lay a week ahead, so the rule that trusted `ltd` flagged the dead contract."""
    toolkit._client.get_futures.return_value = [
        {"symbol": "CL", "conid": 304037496, "expirationDate": _dated(-2), "ltd": _dated(7)},
        {"symbol": "CL", "conid": 304037511, "expirationDate": _dated(28), "ltd": _dated(37)},
    ]
    rows = json.loads(toolkit.execute("get_futures", {"symbols": ["CL"]})[0])
    assert [r["conid"] for r in rows if r["front_month"]] == [304037511], rows


def test_a_bare_root_never_resolves_to_a_contract_past_its_expiration_date(toolkit):
    """The same rows through `_resolve_snapshot_conid` — the path `get_market_snapshot` and
    `preview_order` take, where the dead contract's quote was a prior close, no bid, no ask."""
    toolkit._client.get_futures.return_value = [
        {"symbol": "CL", "conid": 304037496, "expirationDate": _dated(-2), "ltd": _dated(7)},
        {"symbol": "CL", "conid": 304037511, "expirationDate": _dated(28), "ltd": _dated(37)},
    ]
    resolved = toolkit._resolve_snapshot_conid("CL", "FUT", None)
    assert resolved.conid == 304037511, f"resolved the expired contract: {resolved}"


def test_front_month_ORDERING_follows_the_earlier_date_when_expiration_date_is_it(toolkit):
    """The mirror of the `ltd` ordering test above: both tradeable, and now `expirationDate`
    is the earlier field on each row. The earlier date orders them, whichever field it is."""
    toolkit._client.get_futures.return_value = [
        {"symbol": "XX", "conid": 777, "expirationDate": _dated(10), "ltd": _dated(90)},
        {"symbol": "XX", "conid": 888, "expirationDate": _dated(50), "ltd": _dated(40)},
    ]
    rows = json.loads(toolkit.execute("get_futures", {"symbols": ["XX"]})[0])
    assert [r["conid"] for r in rows if r["front_month"]] == [777], rows


def test_resolving_a_bare_root_never_prefers_an_UNDATED_contract(toolkit):
    """`min(..., key=_expiration_key)` keyed an undated row to 0, so it beat every dated one
    and a bare root resolved to the contract we know least about."""
    toolkit._client.get_futures.return_value = [
        {"symbol": "ES", "conid": 999},  # no date at all
        {"symbol": "ES", "conid": 649180671, "expirationDate": _dated(30), "ltd": _dated(30)},
    ]
    resolved = toolkit._resolve_snapshot_conid("ES", "FUT", None)
    assert resolved.conid == 649180671, f"resolved the undated contract: {resolved}"


def test_a_contract_with_no_usable_date_is_kept_not_silently_dropped(toolkit):
    """An unknown date is not a claim that the contract expired. Dropping it would make a
    tradeable contract invisible, which is worse than the ordering being imperfect."""
    toolkit._client.get_futures.return_value = [
        {"symbol": "ES", "conid": 333},
        {"symbol": "ES", "conid": 444, "expirationDate": _dated(60), "ltd": _dated(60)},
    ]
    rows = json.loads(toolkit.execute("get_futures", {"symbols": ["ES"]})[0])
    assert {r["conid"] for r in rows} == {333, 444}, "a row with no date must still be listed"


_ES_INFO = {
    "local_symbol": "ESU6",
    "contract_month": "202609",
    "maturity_date": "20260918",
    "company_name": "E-mini S&P 500",
    "multiplier": "50",
}


def test_fut_snapshot_names_the_resolved_contract_once_per_conid(toolkit):
    """A futures quote carries `_contract` — IBKR's local symbol, month token, expiry and
    name (measured 2026-09-10 on ES 649180671) — read once per conid and cached."""
    toolkit._client.get_futures.return_value = [
        {"symbol": "ES", "conid": 515416632, "expirationDate": _dated(120), "ltd": _dated(120)},
        {"symbol": "ES", "conid": 649180671, "expirationDate": _dated(30), "ltd": _dated(30)},
    ]
    toolkit._client.get_contract_info.return_value = _ES_INFO
    toolkit._client.get_market_snapshot.return_value = [{"conid": 649180671, "31": "7601.0", "6509": "R"}]
    text, _fig = toolkit.execute("get_market_snapshot", {"symbols": ["ES"], "sec_type": "FUT"})
    assert '"local_symbol": "ESU6"' in text
    assert '"month": "SEP26"' in text
    assert '"expires": "2026-09-18"' in text
    assert '"name": "E-mini S&P 500"' in text
    assert '"multiplier": 50.0' in text
    toolkit.execute("get_market_snapshot", {"symbols": ["ES"], "sec_type": "FUT"})
    toolkit._client.get_contract_info.assert_called_once_with(649180671)


def test_stk_snapshot_carries_no_contract_block(toolkit):
    """A stock quote is unchanged: no `_contract`, no contract-info read."""
    toolkit._client.get_market_snapshot.return_value = [{"conid": 265598, "31": "185.0", "6509": "R"}]
    text, _fig = toolkit.execute("get_market_snapshot", {"symbols": ["AAPL"]})
    assert "_contract" not in text
    toolkit._client.get_contract_info.assert_not_called()


def test_fut_snapshot_omits_the_contract_block_when_the_read_fails(toolkit):
    """A failed contract-info read leaves the block out — never a guessed name."""
    from ibkr_core_mcp.exceptions import IBKRAPIError

    toolkit._client.get_futures.return_value = [
        {"symbol": "ES", "conid": 649180671, "expirationDate": _dated(30), "ltd": _dated(30)}
    ]
    toolkit._client.get_contract_info.side_effect = IBKRAPIError("HTTP 500")
    toolkit._client.get_market_snapshot.return_value = [{"conid": 649180671, "31": "7601.0", "6509": "R"}]
    text, _fig = toolkit.execute("get_market_snapshot", {"symbols": ["ES"], "sec_type": "FUT"})
    assert "7601.0" in text and "_contract" not in text


def test_get_futures_names_the_front_month_in_ibkr_terms(toolkit):
    """claudia_ui gap #37(a): with no local symbol in /trsrv/futures, the model derived `ESU6`
    from the month-code convention and wrote "front month confirmed" (2026-09-10). The
    front-month row now carries the same `_contract` block a FUT quote does, from the
    per-conid cache — one contract-info call for the one row the model quotes, not one per
    expiry — so both paths quote a measured string."""
    toolkit._client.get_futures.return_value = [
        {"symbol": "ES", "conid": 515416632, "expirationDate": _dated(120), "ltd": _dated(120)},
        {"symbol": "ES", "conid": 649180671, "expirationDate": _dated(30), "ltd": _dated(30)},
    ]
    toolkit._client.get_contract_info.return_value = {
        "local_symbol": "ESU6",
        "contract_month": "202609",
        "maturity_date": "20260918",
        "company_name": "E-mini S&P 500",
        "multiplier": "50",
        "exchange": "CME",
    }
    text, _fig = toolkit.execute("get_futures", {"symbols": ["ES"]})
    front, back = json.loads(text)
    assert front["front_month"] and front["_contract"] == {
        "local_symbol": "ESU6",
        "month": "SEP26",
        "expires": "2026-09-18",
        "name": "E-mini S&P 500",
        "exchange": "CME",  # kept since 2.2.0 — the market-data result names the contract's exchange
        "multiplier": 50.0,
    }
    assert "_contract" not in back
    toolkit._client.get_contract_info.assert_called_once_with(649180671)
    toolkit.execute("get_futures", {"symbols": ["ES"]})
    assert toolkit._client.get_contract_info.call_count == 1  # cached per conid


def test_get_futures_omits_the_contract_block_rather_than_guess(toolkit):
    """A failed or empty contract-info read leaves the row without `_contract` — never a
    derived symbol — and the sort and flag are unaffected."""
    from ibkr_core_mcp.exceptions import IBKRCoreError

    toolkit._client.get_futures.return_value = [
        {"symbol": "ES", "conid": 649180671, "expirationDate": _dated(30), "ltd": _dated(30)}
    ]
    toolkit._client.get_contract_info.side_effect = IBKRCoreError("down")
    (row,) = json.loads(toolkit.execute("get_futures", {"symbols": ["ES"]})[0])
    assert row["front_month"] and "_contract" not in row


def test_snapshot_names_the_price_fields_and_drops_the_numeric_ids(toolkit):
    """Live 2026-09-11: with IBKR's numeric field ids in the result the model swapped the
    pairs — reported the day's low/high (`71`/`70`) as "Bid / Ask" and the bid/ask
    (`84`/`86`) as "Day High / Low", then reasoned about a spread that did not exist. The
    tool names the fields from the package's one map and keeps the ids and the server
    noise out of the model's view (Anthropic, writing-tools-for-agents: resolve cryptic
    identifiers to meaningful names; return only high-signal information)."""
    toolkit._client.get_stocks.return_value = IGV_LISTINGS
    toolkit._client.get_secdef_info.return_value = [{"conid": 12658199, "currency": "USD"}]
    toolkit._client.get_market_snapshot.return_value = [
        {
            "conid": 12658199,
            "conidEx": "12658199",
            "55": "IGV",
            "6509": "R",
            "6119": "q2",
            "server_id": "q2",
            "_updated": 1789159026300,
            "31": "100.35",
            "84": "100.33",
            "86": "100.34",
            "70": "104.46",
            "71": "98.48",
            "82": "-2.13",
            "83": -2.08,
            "87": "371K",
            "87_raw": 371000.0,
        }
    ]

    text, _fig = toolkit.execute("get_market_snapshot", {"symbols": ["IGV"]})
    import json

    quote = json.loads(text)[0]
    assert quote["last"] == "100.35"
    assert quote["bid"] == "100.33"
    assert quote["ask"] == "100.34"
    assert quote["high"] == "104.46"
    assert quote["low"] == "98.48"
    assert quote["change"] == "-2.13"
    assert quote["change_pct"] == -2.08
    assert quote["volume"] == "371K"
    assert quote["volume_raw"] == 371000.0
    assert quote["conid"] == 12658199
    assert quote["_data_status"] == "Live (Real-Time)"
    for gone in (
        "31",
        "84",
        "86",
        "70",
        "71",
        "82",
        "83",
        "87",
        "87_raw",
        "55",
        "6509",
        "6119",
        "server_id",
        "conidEx",
        "_updated",
    ):
        assert gone not in quote, gone


def _indicator_frame(n, freq, start="2025-01-02 09:30"):
    """OHLCV frame with a real DatetimeIndex at the requested bar size."""
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(3)
    close = 100 + np.cumsum(rng.normal(0, 0.5, n))
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": np.ones(n) * 1e6,
        },
        index=pd.date_range(start, periods=n, freq=freq),
    )


def test_add_indicators_reports_vwap_only_for_intraday_timeframes(toolkit):
    """VWAP measures one trading session, so on daily bars each session holds a
    single bar and VWAP collapses to that bar's typical price. StockCharts states
    it plainly: "VWAP is not defined for daily, weekly, or monthly periods due to
    the nature of the calculation." Printing a number there reads as a real level
    and is not one, so the daily output says so instead."""
    toolkit._cache.check.return_value = True
    toolkit._cache.load.return_value = _indicator_frame(120, "B")

    text, _ = toolkit.execute(
        "add_indicators", {"symbol": "AAPL", "timeframe": "1D", "period": "1Y", "end": "2026-05-22"}
    )

    assert_tool_succeeded(text)
    vwap_line = next(line for line in text.splitlines() if "VWAP" in line)
    assert "intraday" in vwap_line.lower(), vwap_line
    assert "n/a" in vwap_line.lower(), vwap_line


def test_add_indicators_prints_a_vwap_number_on_intraday_bars(toolkit):
    """The counter-case: on 5-minute bars VWAP is exactly what it is defined for,
    so a real figure must appear. Without this, "never print VWAP" would satisfy
    the test above."""
    toolkit._cache.check.return_value = True
    toolkit._cache.load.return_value = _indicator_frame(120, "5min")

    text, _ = toolkit.execute(
        "add_indicators", {"symbol": "AAPL", "timeframe": "5min", "period": "1D", "end": "2026-05-22"}
    )

    assert_tool_succeeded(text)
    vwap_line = next(line for line in text.splitlines() if "VWAP" in line)
    assert "n/a" not in vwap_line.lower(), vwap_line
    assert any(ch.isdigit() for ch in vwap_line.split("VWAP")[1]), vwap_line


def _framework_frame():
    """Five bars whose hl2 is 6, 8, 10, 12, 14 and whose closes sit one above — small enough
    to work the averages, the deviation and the distance in deviations by hand, and no number on `close`
    equals its counterpart on `hl2`."""
    import pandas as pd

    hl2 = [6.0, 8.0, 10.0, 12.0, 14.0]
    return pd.DataFrame(
        {
            "open": hl2,
            "high": [v + 2 for v in hl2],
            "low": [v - 2 for v in hl2],
            "close": [v + 1 for v in hl2],
            "volume": 1.0,
        },
        index=pd.date_range("2026-05-18", periods=5, freq="B"),
    )


def _indicator_line(text, label):
    """The value part of the one output line that starts with `label`."""
    (line,) = [ln for ln in text.splitlines() if ln.strip().startswith(label)]
    return line.split(label, 1)[1].strip()


_AAPL_WINDOW = {"symbol": "AAPL", "timeframe": "1D", "period": "1Y", "end": "2026-05-22"}


def test_add_indicators_reports_the_framework_in_tradingviews_labels_with_every_setting_named(toolkit):
    """The operator's chart, 2026-10-05: `SMA 200 hl2` and `BB 200 SMA hl2 2.5` — averages and
    bands of (high + low)/2, and where the last close sits in standard deviations. Worked by
    hand on the last three bars: hl2 10, 12, 14 → SMA 12; population deviation sqrt(8/3) = 1.633;
    bands 12 ± 1.633 and 12 ± 2.5 × 1.633; close 15 = +1.84 deviations. On `close` the average would be
    13, so a source that is named and not used cannot pass. hl2 is the default here and is
    said to be; RSI and MACD stay on `close` and say so."""
    toolkit._cache.check.return_value = True
    toolkit._cache.load.return_value = _framework_frame()

    text, _ = toolkit.execute(
        "add_indicators", {**_AAPL_WINDOW, "ma_periods": [3], "band_period": 3, "band_stds": [1, 2.5]}
    )

    assert_tool_succeeded(text)
    assert "source: hl2 = (high + low)/2 (by default)" in text, text
    assert _indicator_line(text, "SMA 3 hl2:") == "12.00"
    assert _indicator_line(text, "BB 3 SMA hl2 1:") == "12.00 / 13.63 / 10.37 (basis / upper / lower)"
    assert _indicator_line(text, "BB 3 SMA hl2 2.5:") == "12.00 / 16.08 / 7.92 (basis / upper / lower)"
    assert "last close 15.00 = SMA 3 hl2 + 1.84 StdDev (1 StdDev = 1.63:" in text, text
    assert "RSI and MACD — source: close (by default)" in text, text
    assert _indicator_line(text, "RSI(14) close:") and _indicator_line(text, "MACD(12,26,9) close:")


def test_add_indicators_never_prints_nan_and_says_how_many_bars_it_needs(toolkit):
    """A 200-bar average cannot exist on a 5-bar window. `nan` reads as a broken tool; the
    line says what is missing and what to do, on every line that has no value."""
    toolkit._cache.check.return_value = True
    toolkit._cache.load.return_value = _framework_frame()

    text, _ = toolkit.execute("add_indicators", {**_AAPL_WINDOW, "ma_periods": [200]})

    assert_tool_succeeded(text)
    assert _indicator_line(text, "SMA 200 hl2:") == "n/a — 5 bars in the window, 200 needed; fetch a longer period"
    assert "nan" not in text.lower(), text


@pytest.mark.parametrize(
    ("offset", "label", "expected"),
    [
        # Drawn one bar to the right: the last bar shows the average as of the bar before, (8+10+12)/3.
        (1, "SMA 3 hl2 offset 1:", "10.00"),
        # Drawn one bar to the left: the line stops short of the last bar.
        (-1, "SMA 3 hl2 offset -1:", "nothing is drawn on the last bar — the line ends 1 bar(s) earlier"),
    ],
)
def test_add_indicators_offset_reports_what_tradingview_draws_on_the_last_bar(toolkit, offset, label, expected):
    """TradingView's Offset moves the line "Forwards or Backwards relative to the current
    market"; Pine's `plot` "Shifts the plot to the left or to the right on the given number of
    bars". The values are unchanged — what changes is which one sits on the last bar."""
    toolkit._cache.check.return_value = True
    toolkit._cache.load.return_value = _framework_frame()

    text, _ = toolkit.execute("add_indicators", {**_AAPL_WINDOW, "source": "hl2", "ma_periods": [3], "offset": offset})

    assert _indicator_line(text, label) == expected
    assert "source: hl2 = (high + low)/2 (as given)" in text, text


@pytest.mark.parametrize(
    ("setting", "names"),
    [
        ({"source": "typical"}, "open, high, low, close, hl2, hlc3, ohlc4, hlcc4"),
        ({"oscillator_source": "mid"}, "open, high, low, close, hl2, hlc3, ohlc4, hlcc4"),
        ({"ma_type": "HMA"}, "SMA, EMA, SMMA (RMA), WMA, VWMA"),
        ({"ma_periods": [0]}, "ma_periods"),
        ({"band_period": 0}, "band_period"),
        ({"band_stds": []}, "band_stds"),
        ({"band_stds": [0]}, "band_stds"),
        ({"offset": 1.5}, "offset"),
    ],
)
def test_add_indicators_refuses_a_setting_it_cannot_honour(toolkit, setting, names):
    """A source or type outside TradingView's lists is refused with the list — never computed
    on `close` under the name that was asked for."""
    toolkit._cache.check.return_value = True
    toolkit._cache.load.return_value = _framework_frame()

    text, _ = toolkit.execute("add_indicators", {**_AAPL_WINDOW, **setting})

    assert "Nothing computed" in text, text
    assert names in text, text


def test_add_indicators_computes_rsi_and_macd_on_the_source_it_names(toolkit):
    """Flat closes under a rising midpoint. On `close`, the default, RSI has no value — 0/0,
    which no source defines — and the line says so rather than printing `nan`; on `hl2` it is
    100. A line labelled `hl2` and computed on `close` would print the first under the
    second's name."""
    import pandas as pd

    rising = [float(i) for i in range(40)]
    toolkit._cache.check.return_value = True
    toolkit._cache.load.return_value = pd.DataFrame(
        {"open": 100.0, "high": [101.0 + 2 * r for r in rising], "low": 99.0, "close": 100.0, "volume": 1.0},
        index=pd.date_range("2026-03-02", periods=40, freq="B"),
    )

    on_close, _ = toolkit.execute("add_indicators", _AAPL_WINDOW)
    on_hl2, _ = toolkit.execute("add_indicators", {**_AAPL_WINDOW, "oscillator_source": "hl2"})

    assert _indicator_line(on_close, "RSI(14) close:") == "n/a — undefined on the last bar"
    assert "nan" not in on_close.lower(), on_close
    assert _indicator_line(on_hl2, "RSI(14) hl2:") == "100.0"
    assert _indicator_line(on_hl2, "MACD(12,26,9) hl2:") != _indicator_line(on_close, "MACD(12,26,9) close:")


def test_add_indicators_prints_no_vwap_for_an_all_hours_series(toolkit):
    """This VWAP restarts on the UTC day. A regular US session sits inside one; an all-hours
    session does not — a futures session opens at 18:00 New York and crosses midnight UTC
    (measured 2026-09-17 on ES minute bars: the figure restarted mid-session, DATA-R6). Since
    2.2.0 an all-hours series can be cached, so the line says why there is no figure instead
    of printing that one. The regular-hours test above is the counter-case."""
    toolkit._cache.check.return_value = True
    toolkit._cache.load.return_value = _indicator_frame(120, "5min")

    text, _ = toolkit.execute(
        "add_indicators",
        {"symbol": "ESZ6", "timeframe": "5min", "period": "1D", "end": "2026-05-22", "outside_rth": True},
    )

    vwap_line = _indicator_line(text, "VWAP:")
    assert vwap_line.startswith("n/a") and "all-hours" in vwap_line, vwap_line


def _history_payload(n_bars, start_ms, step_ms, warning=None):
    """A get_market_history_paginated return value, optionally flagged incomplete."""
    payload = {
        "data": [{"t": start_ms + i * step_ms, "o": 1.0, "h": 1.0, "l": 1.0, "c": 1.0, "v": 1.0} for i in range(n_bars)]
    }
    if warning:
        payload["ibkr_core_warning"] = warning
    return payload


def test_fetch_market_data_refuses_a_period_outside_ibkrs_grammar(toolkit):
    """`period="ytd"` was sent twice by the model; IBKR answered with a window of its own and
    the result named `ytd` as if it had been honoured, under a cache key that says `YTD`. The
    period is refused with the grammar before anything is resolved, read or cached."""
    text, _ = toolkit.execute("fetch_market_data", {"symbol": "AAPL", "period": "ytd"})

    assert "period 'ytd'" in text and "min, h, d, w, m" in text and "Nothing was read" in text, text
    toolkit._client.get_stocks.assert_not_called()
    toolkit._cache.check.assert_not_called()
    toolkit._client.get_market_history_paginated.assert_not_called()


def test_fetch_market_data_refuses_to_cache_a_truncated_window(toolkit):
    """A partial window saved under the requested period is the dangerous half of API-02.

    The Drive cache is shared across machines and long-lived, and its key is
    (symbol, timeframe, period, end) — so 33% of a year stored under '1y' answers every
    later request for a year, on every machine, with no second chance to notice. This
    repo has already paid for that once: the 2026-08-05 `startTime` incident needed a
    cache purge because "a code fix is not sufficient — `_fetch_market_data` returns
    'Cache HIT' and serves the stored parquet without re-fetching".

    So a flagged-incomplete result is reported and NOT saved.
    """
    warning = "INCOMPLETE: asked for 1y of 5min bars but stopped at the 120-chunk safety guard."
    toolkit._cache.check.return_value = False
    toolkit._client.get_market_history_paginated.return_value = _history_payload(
        500, 1_700_000_000_000, 300_000, warning=warning
    )

    text, _ = toolkit.execute(
        "fetch_market_data", {"symbol": "AAPL", "period": "1y", "bar": "5min", "end": "2026-09-16"}
    )

    assert "INCOMPLETE" in text, text
    toolkit._cache.save.assert_not_called()
    assert "not" in text.lower() and "cache" in text.lower(), text


def test_fetch_market_data_still_caches_a_complete_window(toolkit):
    """The counter-case: without it, "never cache" would satisfy the test above."""
    toolkit._cache.check.return_value = False
    toolkit._client.get_market_history_paginated.return_value = _history_payload(500, 1_700_000_000_000, 300_000)

    text, _ = toolkit.execute(
        "fetch_market_data", {"symbol": "AAPL", "period": "5d", "bar": "5min", "end": "2026-09-16"}
    )

    assert "INCOMPLETE" not in text, text
    toolkit._cache.save.assert_called_once()
    assert "Saved to Drive cache" in text, text


# ── TOOL-R1: the tool's default exchange returned nothing ─────────────────────


def test_get_trading_schedule_omits_exchange_rather_than_defaulting_to_smart(toolkit):
    """`symbol` is this tool's ONLY required input, and the handler defaulted `exchange`
    to `"SMART"` — which returns an empty list, because SMART is IBKR's order router and
    not a venue with published hours.

    So the minimal documented call returned `[]` for every equity. Measured live
    2026-09-16 on AAPL: `SMART` **0 rows**, `exchange` omitted **141 rows**, `ISLAND` 125.
    Omitting it returns the most complete answer and is what IBKR's API Reference marks
    optional, so the default is now "send nothing".
    """
    toolkit._client.get_trading_schedule.return_value = [{"id": "p1", "exchange": "ISLAND"}]

    toolkit.execute("get_trading_schedule", {"symbol": "AAPL"})

    toolkit._client.get_trading_schedule.assert_called_once_with("STK", "AAPL", "")


def test_get_trading_schedule_still_forwards_an_explicit_exchange(toolkit):
    """The counter-case: an exchange the caller asked for is passed through untouched.
    Without this, "omit the default" and "ignore the parameter" are indistinguishable."""
    toolkit._client.get_trading_schedule.return_value = [{"id": "p1", "exchange": "NYMEX"}]

    toolkit.execute("get_trading_schedule", {"symbol": "CL", "asset_class": "FUT", "exchange": "NYMEX"})

    toolkit._client.get_trading_schedule.assert_called_once_with("FUT", "CL", "NYMEX")


def test_get_trading_schedule_description_does_not_promise_a_next_trading_date(toolkit):
    """The description promised "regular trading hours, pre/post-market sessions, and next
    trading date". The endpoint returns none of those as named fields — there is no
    next-trading-date key anywhere in IBKR's response object or on the wire."""
    tool = next(t for t in toolkit.tools if t["name"] == "get_trading_schedule")

    assert "next trading date" not in tool["description"].lower()
    assert "default: SMART" not in tool["description"]
    assert "SMART" in tool["description"], "the SMART trap should be named, not silently dropped"


@pytest.mark.parametrize("tool", ["add_indicators", "run_backtest", "get_analytics"])
def test_the_readers_take_the_hours_and_state_them(toolkit, tool):
    """Step 2: the hours are a key part, so each cache reader takes `outside_rth` (default
    false — it has no security type to default from) and says which hours it read."""
    import pandas as pd

    toolkit._cache.check.return_value = True
    toolkit._cache.entry.return_value = {"outside_rth": True}
    toolkit._cache.load.return_value = pd.DataFrame(
        {"open": 1.0, "high": 1.0, "low": 1.0, "close": [1.0 + i / 100 for i in range(60)], "volume": 1.0},
        index=pd.date_range("2026-07-01", periods=60, freq="B"),
    )
    base = {"symbol": "ESZ6", "timeframe": "1D", "period": "6m", "end": "2026-10-03", "code": "df['signal'] = 1"}

    given, _ = toolkit.execute(tool, {**base, "outside_rth": True})
    toolkit._cache.check.assert_called_with("ESZ6", "1D", "6m", "2026-10-03", outside_rth=True)
    toolkit._cache.load.assert_called_with("ESZ6", "1D", "6m", "2026-10-03", outside_rth=True)
    assert "all trading hours (as given)" in given, given

    default, _ = toolkit.execute(tool, base)
    toolkit._cache.check.assert_called_with("ESZ6", "1D", "6m", "2026-10-03", outside_rth=False)
    assert "regular trading hours (by default)" in default, default


def test_add_indicators_prints_an_all_hours_futures_last_bar_as_its_open_in_et(toolkit):
    """The stamp is IBKR's session open; "last bar: 2026-10-01" would read as Thursday's bar
    when it is Friday's session. The row knows the series is an all-hours future."""
    import pandas as pd

    toolkit._cache.check.return_value = True
    toolkit._cache.entry.return_value = {"outside_rth": True, "listing": {"root": "ES", "conid": 515416632}}
    idx = pd.to_datetime(
        [1_790_892_000_000 - 86_400_000 * i for i in range(59, -1, -1)], unit="ms"
    )  # last = Thu 18:00 ET
    toolkit._cache.load.return_value = pd.DataFrame(
        {"open": 1.0, "high": 1.0, "low": 1.0, "close": [1.0 + i / 100 for i in range(60)], "volume": 1.0}, index=idx
    )
    text, _ = toolkit.execute(
        "add_indicators",
        {"symbol": "ESZ6", "timeframe": "1D", "period": "6m", "end": "2026-10-03", "outside_rth": True},
    )
    assert "last bar stamped 2026-10-01 18:00 ET (its session open)" in text, text
    assert "last bar: 2026-10-01" not in text


def test_a_cache_miss_names_the_hours_and_points_a_root_at_its_cached_contracts(toolkit):
    """A miss under the wrong hours lists what IS cached with its hours; a root (`ES`) is not a
    cache symbol, and the miss points at the contracts cached for it rather than saying nothing."""
    toolkit._cache.check.return_value = False
    toolkit._cache.list_cached.return_value = [
        {
            "key": "ESZ6_1D_6M_2026-10-03_ALL",
            "symbol": "ESZ6",
            "timeframe": "1D",
            "period": "6m",
            "end": "2026-10-03",
            "outside_rth": True,
            "listing": {"root": "ES", "conid": 515416632},
        },
    ]
    wrong_hours, _ = toolkit.execute(
        "add_indicators", {"symbol": "ESZ6", "timeframe": "1D", "period": "6m", "end": "2026-10-03"}
    )
    assert "No cached data for ESZ6 1D 6m ending 2026-10-03 (regular hours)" in wrong_hours, wrong_hours
    assert "ESZ6 1D 6m ending 2026-10-03 (all hours)" in wrong_hours, wrong_hours

    root, _ = toolkit.execute(
        "add_indicators", {"symbol": "ES", "timeframe": "1D", "period": "6m", "end": "2026-10-03"}
    )
    assert "Nothing is cached under ES" in root and "root" in root, root
    assert "ESZ6 1D 6m ending 2026-10-03 (all hours" in root, root

    # Live 2026-10-03: `ES` the stock was cached too, and the miss listed it without its name
    # and without a word about the contracts cached for the root. Every window is named, and
    # a symbol that is also a root of cached contracts says so.
    toolkit._cache.list_cached.return_value.append(
        {
            "key": "ES_1D_3M_2026-10-03_RTH",
            "symbol": "ES",
            "timeframe": "1D",
            "period": "3m",
            "end": "2026-10-03",
            "outside_rth": False,
            "listing": {"name": "EVERSOURCE ENERGY", "conid": 182880167},
        },
    )
    both, _ = toolkit.execute(
        "add_indicators", {"symbol": "ES", "timeframe": "1D", "period": "6m", "end": "2026-10-03"}
    )
    assert "ES 1D 3m ending 2026-10-03 (regular hours — EVERSOURCE ENERGY)" in both, both
    assert "ES is also the root of cached contracts: ESZ6 1D 6m ending 2026-10-03 (all hours" in both, both


def test_check_cache_takes_the_hours(toolkit):
    toolkit._cache.check.return_value = True
    text, _ = toolkit.execute(
        "check_cache", {"symbol": "ESZ6", "timeframe": "1D", "period": "6m", "end": "2026-10-03", "outside_rth": True}
    )
    toolkit._cache.check.assert_called_once_with("ESZ6", "1D", "6m", "2026-10-03", outside_rth=True)
    assert "HIT" in text and "all hours" in text, text
