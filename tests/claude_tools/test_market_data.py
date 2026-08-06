import json
from unittest.mock import patch

import pytest

from ibkr_core_mcp.exceptions import IBKRCoreError

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
    text, fig = toolkit.execute("get_market_snapshot", {"symbols": ["ASML"], "exchange": "AMS"})
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
    text, fig = toolkit.execute("get_market_snapshot", {"symbols": ["GE"], "exchange": "NONEXISTENT"})
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

    text, fig = toolkit.execute("get_market_snapshot", {"symbols": ["IGV"]})

    toolkit._client.get_market_snapshot.assert_not_called()
    assert "no US listing" in text
    assert "Ask the user" in text


def test_snapshot_always_states_the_currency(toolkit):
    """A price without its unit is not terser, it is ambiguous — the IGV failure was
    readable as a plausible USD number."""
    toolkit._client.get_stocks.return_value = IGV_LISTINGS
    toolkit._client.get_secdef_info.return_value = [{"conid": 12658199, "currency": "USD"}]
    toolkit._client.get_market_snapshot.return_value = [{"conid": 12658199, "31": "95.0", "6509": "R"}]

    text, fig = toolkit.execute("get_market_snapshot", {"symbols": ["IGV"]})

    assert '"_currency": "USD"' in text


def test_snapshot_says_unknown_rather_than_omitting_the_currency(toolkit):
    """When secdef/info cannot be read the key must still be present. An absent
    currency is indistinguishable from USD; 'UNKNOWN' is not."""
    from ibkr_core_mcp.exceptions import IBKRAPIError

    toolkit._client.get_stocks.return_value = IGV_LISTINGS
    toolkit._client.get_secdef_info.side_effect = IBKRAPIError("boom")
    toolkit._client.get_market_snapshot.return_value = [{"conid": 12658199, "31": "95.0", "6509": "R"}]

    text, fig = toolkit.execute("get_market_snapshot", {"symbols": ["IGV"]})

    assert '"_currency": "UNKNOWN"' in text


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
    # STK resolves via /trsrv/stocks since 2026-07-28, not /iserver/secdef/search.
    toolkit._client.get_stocks.return_value = []
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


# ── US-listing ordering (_us_listings_first) ────────────────────────────────
#
# The live IGV shape, measured 2026-08-05: /iserver/secdef/search returns the MEXICAN
# listing first and the US one second, and its order is not documented as meaningful.

# `sections` is carried because the live rows carry it and the code keys on it: a fixture
# without it would be easier to satisfy than the real response, which is how a mock keeps a
# broken path green.
_IGV_MEXI = {
    "conid": "325209548",
    "companyName": "ISHARES EXPANDED TECH-SOFTWA",
    "symbol": "IGV",
    "description": "MEXI",
    "sections": [{"secType": "STK", "exchange": "MEXI;"}],
}
_IGV_BATS = {
    "conid": "12658199",
    "companyName": "ISHARES EXPANDED TECH-SOFTWA",
    "symbol": "IGV",
    "description": "BATS",
    "sections": [{"secType": "STK"}],
}


def _igv_stocks(us_conids=(12658199,)):
    """A /trsrv/stocks response marking the given conids as US listings."""
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


def test_search_contract_puts_the_us_listing_first(toolkit):
    """The whole point: a bare ticker is a US ticker, so the US row must lead.

    Guards the defect measured live — contracts[0] for IGV was the Mexican listing, and
    the tool description invited the model to use it to discover a conid for an order.
    """
    toolkit._client.search_contract.return_value = [_IGV_MEXI, _IGV_BATS]
    toolkit._client.get_stocks.return_value = _igv_stocks()

    text, _ = toolkit.execute("search_contract", {"symbol": "IGV"})
    rows = json.loads(text)

    assert [r["conid"] for r in rows] == ["12658199", "325209548"]
    assert rows[0]["_is_us"] is True and rows[1]["_is_us"] is False


def test_search_contract_leaves_non_stk_alone(toolkit):
    """/trsrv/stocks is stocks-only — IND/BOND must not pay for a lookup that cannot apply."""
    toolkit._client.search_contract.return_value = [{"conid": "416904", "symbol": "SPX"}]
    toolkit.execute("search_contract", {"symbol": "SPX", "sec_type": "IND"})
    toolkit._client.get_stocks.assert_not_called()


def test_search_contract_returns_every_listing_when_the_us_check_fails(toolkit):
    """A search that still returns all listings beats one that raises on enrichment."""
    toolkit._client.search_contract.return_value = [_IGV_MEXI, _IGV_BATS]
    toolkit._client.get_stocks.side_effect = IBKRCoreError("trsrv down")

    rows = json.loads(toolkit.execute("search_contract", {"symbol": "IGV"})[0])

    assert [r["conid"] for r in rows] == ["325209548", "12658199"]  # untouched order
    assert not any("_is_us" in r for r in rows), "unchecked rows must not be tagged"


def test_search_contract_tags_all_rows_or_none(toolkit):
    """Partial knowledge is worse than none: an untagged row under tagged ones reads as
    'checked, not US'. One unknown conid must leave the whole response alone."""
    toolkit._client.search_contract.return_value = [
        _IGV_MEXI,
        _IGV_BATS,
        # A genuine STK listing /trsrv/stocks does not know — not a bond aggregate.
        {"conid": "999", "symbol": "IGV", "description": "LSE", "sections": [{"secType": "STK"}]},
    ]
    toolkit._client.get_stocks.return_value = _igv_stocks()

    rows = json.loads(toolkit.execute("search_contract", {"symbol": "IGV"})[0])

    assert not any("_is_us" in r for r in rows)
    assert [r["conid"] for r in rows] == ["325209548", "12658199", "999"]


def test_search_contract_ignores_the_bond_aggregate_row(toolkit):
    """A STK search returns non-stock rows, and they must not veto the whole enrichment.

    Measured live 2026-08-05: AAPL and VOD each come back with a "Corporate Fixed Income"
    row (conid 2147483647, null symbol, BOND-only section). /trsrv/stocks does not know it
    because it is not a stock, so the all-or-nothing rule fired on the two most ordinary
    tickers there are and the US ordering silently did nothing for them.
    """
    bond_row = {
        "conid": "2147483647",
        "companyHeader": "Corporate Fixed Income",
        "symbol": None,
        "bondid": 4,
        "sections": [{"secType": "BOND"}],
    }
    stk = dict(_IGV_BATS, sections=[{"secType": "STK"}])
    mexi = dict(_IGV_MEXI, sections=[{"secType": "STK", "exchange": "MEXI;"}])
    toolkit._client.search_contract.return_value = [mexi, bond_row, stk]
    toolkit._client.get_stocks.return_value = _igv_stocks()

    rows = json.loads(toolkit.execute("search_contract", {"symbol": "IGV"})[0])

    assert [r["conid"] for r in rows] == ["12658199", "325209548", "2147483647"]
    assert rows[0]["_is_us"] is True and rows[1]["_is_us"] is False
    assert "_is_us" not in rows[2], "a bond row cannot answer a stock-listing question"


def test_search_contract_keeps_ibkrs_own_order_within_a_group(toolkit):
    """The sort is stable on purpose. IBKR's ordering is undocumented, so inventing a
    secondary key would swap one unfounded order for another."""
    us_a = {"conid": "111", "symbol": "X", "description": "NASDAQ"}
    us_b = {"conid": "222", "symbol": "X", "description": "ARCA"}
    toolkit._client.search_contract.return_value = [us_a, us_b]
    toolkit._client.get_stocks.return_value = [
        {
            "name": "X CO",
            "assetClass": "STK",
            "contracts": [{"conid": 111, "isUS": True}, {"conid": 222, "isUS": True}],
        }
    ]

    rows = json.loads(toolkit.execute("search_contract", {"symbol": "X"})[0])
    assert [r["conid"] for r in rows] == ["111", "222"]


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
