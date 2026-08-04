"""Tests for the complete-capture Flex import path.

The fixture is **synthetic**. Every account id, symbol, price and identifier is
fabricated. Real statements contain live account data and this package is published, so
no archived statement is committed here — the fixture instead reproduces, by hand, each
edge case the 2026-08-04 archive audit actually found:

* a `dateTime` with no time component (one `BookTrade` in six years of statements)
* `openCloseIndicator="C;O"` — a position flip, which must not read as a plain close
* an empty `openCloseIndicator` on a forex row
* a blank `ibExecID` (exactly one trade in the archive has none)
* multi-valued semicolon-delimited `notes`
* byte-identical sibling rows inside one statement (`Lot`, `WashSale`)
* IBKR's negative commission convention
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from ibkr_core_mcp.flex_import import (
    STATEMENT_CODES,
    FlexImportError,
    execution_key_for,
    live_trade_rows,
    normalise_datetime,
    parse_notes,
    parse_statement,
)
from ibkr_core_mcp.flex_schema import ELEMENTS
from ibkr_core_mcp.flex_store import create_flex_tables, table_columns, upsert_flex_rows


def _trade(**overrides: str) -> str:
    """Render a <Trade> with all 85 attributes, overridable per test."""
    attrs = dict.fromkeys(ELEMENTS["Trade"]["columns"], "")
    attrs.update(
        {
            "accountId": "U0000000",
            "currency": "USD",
            "fxRateToBase": "1",
            "assetCategory": "STK",
            "symbol": "TEST",
            "description": "TEST INSTRUMENT",
            "conid": "11111111",
            "multiplier": "1",
            "reportDate": "20260601",
            "dateTime": "20260601;093001",
            "tradeDate": "20260601",
            "settleDateTarget": "20260602",
            "transactionType": "ExchTrade",
            "exchange": "TESTEX",
            "quantity": "10",
            "tradePrice": "100.5",
            "tradeMoney": "1005",
            "proceeds": "-1005",
            "taxes": "0",
            "ibCommission": "-1.25",
            "ibCommissionCurrency": "USD",
            "netCash": "-1006.25",
            "closePrice": "101",
            "cost": "1006.25",
            "fifoPnlRealized": "0",
            "mtmPnl": "5",
            "buySell": "BUY",
            "ibOrderID": "900000001",
            "transactionID": "800000001",
            "ibExecID": "0000aaaa.60000001.01.01",
            "tradeID": "700000001",
            "levelOfDetail": "EXECUTION",
            "openCloseIndicator": "O",
            "changeInPrice": "0",
            "changeInQuantity": "0",
            "isAPIOrder": "N",
            "accruedInt": "0",
            "fineness": "0.0",
            "weight": "0.0",
            "origOrderID": "0",
            "origTransactionID": "0",
            "origTradePrice": "0",
            "exchOrderId": "N/A",
            "extExecID": "aa.bb.cc",
            "orderTime": "20260601;092955",
            "orderType": "LMT",
            "brokerageOrderID": "0000.0001.0002.0003",
            "listingExchange": "TESTEX",
        }
    )
    attrs.update(overrides)
    body = " ".join(f'{k}="{v}"' for k, v in attrs.items())
    return f"<Trade {body} />"


def _element(tag: str, **overrides: str) -> str:
    attrs = dict.fromkeys(ELEMENTS[tag]["columns"], "")
    attrs.update(overrides)
    body = " ".join(f'{k}="{v}"' for k, v in attrs.items())
    return f"<{tag} {body} />"


def _statement(inner: str) -> str:
    return (
        '<FlexQueryResponse queryName="Synthetic" type="AF">'
        '<FlexStatements count="1">'
        '<FlexStatement accountId="U0000000" fromDate="20260601" toDate="20260630"'
        ' period="" whenGenerated="20260701;120000">'
        f"<Trades>{inner}</Trades>"
        "</FlexStatement></FlexStatements></FlexQueryResponse>"
    )


# ── the invariant that makes this whole design checkable ────────────────────────


def test_every_attribute_in_the_xml_has_a_column():
    """No attribute IBKR emits may be silently dropped — the original defect."""
    xml = _statement(_trade())
    parsed = parse_statement(xml, "synthetic.xml")
    row = parsed.rows["Trade"][0]
    columns = set(table_columns("Trade"))
    for attr, (column, _type) in ELEMENTS["Trade"]["columns"].items():
        assert column in columns, f"{attr} has no column"
        assert column in row, f"{attr} produced no value"
    assert len(json.loads(row["raw_attrs"])) == len(ELEMENTS["Trade"]["columns"])


def test_unknown_attribute_is_a_hard_error_not_a_silent_drop():
    """If IBKR adds a field, the import must fail loudly rather than discard it."""
    xml = _statement(_trade().replace("<Trade ", '<Trade brandNewIBKRField="42" '))
    with pytest.raises(FlexImportError, match="brandNewIBKRField"):
        parse_statement(xml, "synthetic.xml")


def test_reserved_column_collision_is_rejected(monkeypatch):
    """An attribute snake_casing onto a meta column must raise, not overwrite it."""
    spec = dict(ELEMENTS["Trade"])
    spec["columns"] = {**spec["columns"], "srcFile": ("src_file", "TEXT")}
    monkeypatch.setitem(ELEMENTS, "Trade", spec)
    with pytest.raises(ValueError, match="reserved column"):
        table_columns("Trade")


# ── edge cases the real archive contained ───────────────────────────────────────


def test_date_only_datetime_parses_to_midnight():
    """One BookTrade in six years has a date with no time; it used to be skipped."""
    assert normalise_datetime("20260601") == "2026-06-01T00:00:00"
    assert normalise_datetime("20260601;093001") == "2026-06-01T09:30:01"
    assert normalise_datetime("") is None


def test_unparseable_datetime_raises_rather_than_skipping():
    with pytest.raises(FlexImportError, match="Unrecognised Flex dateTime"):
        normalise_datetime("June 1st")


def test_position_flip_and_forex_open_close_are_preserved_verbatim():
    xml = _statement(
        _trade(tradeID="1", ibExecID="e1", openCloseIndicator="C;O")
        + _trade(tradeID="2", ibExecID="e2", openCloseIndicator="", assetCategory="CASH")
    )
    rows = parse_statement(xml, "s.xml").rows["Trade"]
    assert rows[0]["open_close_indicator"] == "C;O"
    assert rows[1]["open_close_indicator"] is None


def test_blank_ib_exec_id_falls_back_to_trade_id():
    assert execution_key_for({"ibExecID": "abc", "tradeID": "999"}) == "abc"
    assert execution_key_for({"ibExecID": "", "tradeID": "999"}) == "flex:999"
    with pytest.raises(FlexImportError):
        execution_key_for({"ibExecID": "", "tradeID": ""})


def test_notes_are_split_and_every_code_is_documented():
    assert parse_notes("IA;P") == ["IA", "P"]
    assert parse_notes("") == []
    for code in ("P", "IA", "L", "R", "O", "C"):
        assert code in STATEMENT_CODES
    assert STATEMENT_CODES["L"] == "Ordered by IB (Margin Violation)"


def test_commission_sign_is_preserved_not_absolute():
    """IBKR reports a charge as negative; abs() would erase charge-vs-rebate."""
    row = parse_statement(_statement(_trade()), "s.xml").rows["Trade"][0]
    assert row["ib_commission"] == -1.25


def test_error_response_is_rejected_with_its_ibkr_message():
    xml = (
        "<FlexStatementResponse><Status>Warn</Status><ErrorCode>1019</ErrorCode>"
        "<ErrorMessage>Statement generation in progress.</ErrorMessage></FlexStatementResponse>"
    )
    with pytest.raises(FlexImportError, match="1019"):
        parse_statement(xml, "err.xml")


# ── de-duplication semantics ────────────────────────────────────────────────────


def test_identical_sibling_rows_in_one_statement_are_both_kept():
    """Lot and WashSale genuinely contain byte-identical siblings; a plain content
    hash would silently drop them."""
    lot = _element("Lot", symbol="TEST", quantity="5", fifoPnlRealized="-10")
    parsed = parse_statement(_statement(lot + lot), "s.xml")
    uids = [r["row_uid"] for r in parsed.rows["Lot"]]
    assert len(uids) == 2 and uids[0] != uids[1]


def test_the_same_statement_imported_twice_does_not_duplicate():
    xml = _statement(_trade() + _element("Lot", symbol="TEST", quantity="5"))
    conn = sqlite3.connect(":memory:")
    create_flex_tables(conn)
    for _ in range(2):
        parsed = parse_statement(xml, "s.xml")
        for tag, rows in parsed.rows.items():
            upsert_flex_rows(conn, tag, rows)
    assert conn.execute("SELECT COUNT(*) FROM flex_trade").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM flex_lot").fetchone()[0] == 1
    conn.close()


# ── the live/Flex merge — the defect that produced 75 duplicate rows ─────────────


def _live(exec_id: str = "0000aaaa.60000001.01.01", side: str = "SELL") -> list[dict]:
    return [
        {
            "execution_id": exec_id,
            "symbol": "TEST",
            "side": side,
            "size": 10,
            "price": 100.5,
            "trade_time": "20260601;093001",
            "account": "U0000000",
            "commission": 1.25,
        }
    ]


def test_live_quantity_is_signed_from_side():
    assert live_trade_rows(_live(side="SELL"))[0]["quantity"] == -10
    assert live_trade_rows(_live(side="BUY"))[0]["quantity"] == 10


def test_live_and_flex_derive_the_same_execution_key():
    flex = parse_statement(_statement(_trade()), "s.xml").rows["Trade"][0]
    live = live_trade_rows(_live())[0]
    assert live["execution_key"] == flex["execution_key"]


@pytest.mark.parametrize("live_first", [True, False])
def test_live_and_flex_converge_on_one_row_in_either_order(live_first):
    """Live-then-Flex must enrich; Flex-then-live must not clobber."""
    flex = parse_statement(_statement(_trade(fifoPnlRealized="-154.43")), "s.xml").rows["Trade"][0]
    live = live_trade_rows(_live())[0]
    conn = sqlite3.connect(":memory:")
    create_flex_tables(conn)
    order = [live, flex] if live_first else [flex, live]
    for row in order:
        upsert_flex_rows(conn, "Trade", [row])
    count, source, pnl = conn.execute("SELECT COUNT(*), source, fifo_pnl_realized FROM flex_trade").fetchone()
    assert count == 1, "the same fill was stored twice"
    assert source == "flex", "Flex data must win regardless of arrival order"
    assert pnl == -154.43
    conn.close()


def test_client_portal_timestamp_format_parses():
    """The CP API uses YYYYMMDD-HH:MM:SS; Flex uses YYYYMMDD;HHMMSS. Both must parse.

    The colon form failed silently at first, storing every live fill with a NULL
    timestamp.
    """
    assert normalise_datetime("20260804-19:57:03") == "2026-08-04T19:57:03"
    assert normalise_datetime("20260804;195703") == "2026-08-04T19:57:03"


def test_live_rows_do_not_guess_a_trading_day():
    """The CP timestamp is UTC; a 21:00 ET fill is already tomorrow in UTC, so deriving
    trade_date from it would file the fill under the wrong session. IBKR supplies the
    authoritative tradeDate T+1 onto the same row."""
    row = live_trade_rows(_live())[0]
    assert row["date_time_iso"] == "2026-06-01T09:30:01"
    assert row["trade_date"] is None
    assert row["trade_date_iso"] is None
