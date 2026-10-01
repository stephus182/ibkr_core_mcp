import pytest

from ibkr_core_mcp.claude_tools import _parse_live_trades

pytestmark = pytest.mark.trades


def test_execute_get_trades(toolkit):
    toolkit._client.get_trades.return_value = [
        {"execution_id": "E1", "symbol": "AAPL", "side": "BUY", "size": 10, "price": 180, "time": "2026-05-22T10:00:00"}
    ]
    toolkit._store.upsert_trades.return_value = None
    text, fig = toolkit.execute("get_trades", {"source": "live"})
    assert "AAPL" in text
    assert fig is None


# --- _parse_live_trades unit tests ---


def _raw(overrides: dict[str, object]) -> dict[str, object]:
    base = {
        "execution_id": "EX1",
        "symbol": "AAPL",
        "side": "B",
        "size": 10,
        "price": 180.0,
        "time": "2026-05-22T10:00:00",
        "commission": -1.0,
        "account": "U123456",
    }
    base.update(overrides)
    return base


def test_parse_live_trades_side_normalization():
    parsed, skipped = _parse_live_trades([_raw({"side": "B"}), _raw({"side": "S", "execution_id": "EX2"})])
    assert skipped == 0
    assert parsed[0]["side"] == "BUY"
    assert parsed[1]["side"] == "SELL"


def test_parse_live_trades_already_normalized_side():
    parsed, skipped = _parse_live_trades([_raw({"side": "BUY"}), _raw({"side": "SELL", "execution_id": "EX2"})])
    assert skipped == 0
    assert parsed[0]["side"] == "BUY"
    assert parsed[1]["side"] == "SELL"


def test_parse_live_trades_commission_abs():
    parsed, _ = _parse_live_trades([_raw({"commission": -2.5})])
    assert parsed[0]["commission"] == 2.5


def test_parse_live_trades_skips_missing_execution_id():
    # No fallback to loop index — record must be skipped
    t = _raw({})
    del t["execution_id"]
    parsed, skipped = _parse_live_trades([t])
    assert len(parsed) == 0
    assert skipped == 1


def test_parse_live_trades_skips_missing_symbol():
    parsed, skipped = _parse_live_trades([_raw({"symbol": "", "ticker": ""})])
    assert len(parsed) == 0
    assert skipped == 1


def test_parse_live_trades_skips_invalid_side():
    parsed, skipped = _parse_live_trades([_raw({"side": "X"})])
    assert len(parsed) == 0
    assert skipped == 1


def test_parse_live_trades_skips_missing_time():
    t = _raw({"time": "", "trade_time": ""})
    parsed, skipped = _parse_live_trades([t])
    assert len(parsed) == 0
    assert skipped == 1


def test_parse_live_trades_alternate_field_names():
    # IBKR API uses different field names in different endpoints
    t = {
        "execId": "EX99",
        "ticker": "CL",
        "side": "B",
        "filledQuantity": 5,
        "avgPrice": 78.5,
        "trade_time": "2026-05-22T14:30:00",
        "commission": -0.85,
        "acctID": "U999999",
    }
    parsed, skipped = _parse_live_trades([t])
    assert skipped == 0
    assert parsed[0]["execution_id"] == "EX99"
    assert parsed[0]["symbol"] == "CL"
    assert parsed[0]["side"] == "BUY"
    assert parsed[0]["size"] == 5
    assert parsed[0]["price"] == 78.5
    assert parsed[0]["commission"] == 0.85
    assert parsed[0]["account"] == "U999999"


def test_parse_live_trades_upsert_error_surfaced(toolkit):
    toolkit._client.get_trades.return_value = [
        {"execution_id": "E1", "symbol": "AAPL", "side": "B", "size": 10, "price": 180, "time": "2026-05-22T10:00:00"}
    ]
    toolkit._store.upsert_trades.side_effect = RuntimeError("DB locked")
    text, _fig = toolkit.execute("get_trades", {"source": "live"})
    # Raw exception must NOT leak to LLM — only a controlled message appears
    assert "DB locked" not in text
    assert "could not be saved" in text.lower()


# --- get_trades(source='store'): the Flex statements, one read path (register F20) ---
#
# The toolkit fixture's store is a MagicMock, and that is the point of the first test: this
# branch does not go through `SQLiteStore` at all. The dataset is built in the fixture's
# temporary database by the real parser and writer.


def _statement_trade(n, day, symbol, asset, pnl, **over):
    from tests.flex_fixtures import trade

    compact = day.replace("-", "")
    attrs = {
        "tradeID": str(9_000_000 + n),
        "transactionID": str(9_500_000 + n),
        "ibExecID": f"0000bbbb.{n:08d}.01.01",
        "tradeDate": compact,
        "reportDate": compact,
        "dateTime": f"{compact};11{n:04d}"[:15],
        "symbol": symbol,
        "assetCategory": asset,
        "fifoPnlRealized": str(pnl),
    }
    attrs.update(over)
    return trade(**attrs)


def _seed_statements(toolkit, *rows):
    from tests.flex_fixtures import seed_flex_dataset, statement

    seed_flex_dataset(toolkit._config, statement("".join(rows), from_date="20260801", to_date="20260806"))


_THREE = (
    (1, "2026-08-03", "ESU6", "FUT", -100.50),
    (2, "2026-08-04", "TEST", "STK", 40.25),
    (3, "2026-08-04", "TEST", "STK", 0.0),
)


def test_get_trades_store_lists_the_statement_executions_and_their_realised_total(toolkit):
    _seed_statements(
        toolkit, *(_statement_trade(*row, quantity="-2" if row[0] == 1 else "10", buySell="SELL") for row in _THREE)
    )

    text, fig = toolkit.execute("get_trades", {"source": "store"})

    assert fig is None
    lines = text.splitlines()
    # The statement's own toDate (2026-08-06), not the newest trade (2026-08-04): a weekday
    # with no fills still has a statement, and the listing is complete through it (#79).
    assert (
        lines[0] == "Trade history — Flex statements through 2026-08-06 (3 executions, all origins incl. mobile/TWS):"
    )
    assert lines[1] == "- 2026-08-04 TEST [STK] BUY 10.0 @ 100.5 comm=1.25 pnl=+0.00"  # newest first
    assert lines[3] == "- 2026-08-03 ESU6 [FUT] SELL 2.0 @ 100.5 comm=1.25 pnl=-100.50"
    assert "Total realized P&L: -60.25 USD" in lines
    assert "By asset class: FUT -100.50, STK +40.25" in lines
    assert lines[-1].startswith("Fills since the last statement are not in this list")


def test_get_trades_store_does_not_touch_the_legacy_store_object(toolkit):
    """F20: the realised total used to be summed from `SQLiteStore.get_trades()` — the legacy
    table. The branch now reads the Flex dataset and calls nothing on the store."""
    _seed_statements(toolkit, *(_statement_trade(*row) for row in _THREE))

    toolkit.execute("get_trades", {"source": "store"})

    assert toolkit._store.method_calls == []


def test_get_trades_store_total_is_the_readers_window_to_the_cent(toolkit):
    """The litmus in miniature: what the tool reports is what `FlexDataset.realised_window`
    reports — the figure a host's dashboard shows for the same window."""
    from datetime import date

    from ibkr_core_mcp.flex_dataset import FlexDataset

    _seed_statements(toolkit, *(_statement_trade(*row) for row in _THREE))
    with FlexDataset.open(toolkit._config.sqlite_path) as flex:
        window = flex.realised_window(date(2026, 8, 4), date(2026, 8, 4))

    text, _ = toolkit.execute("get_trades", {"source": "store", "start": "2026-08-04", "end": "2026-08-04"})

    assert f"Total realized P&L: {window.total:+.2f} USD" in text.splitlines()
    assert "(2 executions" in text and window.trade_count == 2


def test_get_trades_store_end_date_includes_that_day(toolkit):
    """The legacy reader compared `end` with a timestamp, so the end day itself dropped out."""
    _seed_statements(toolkit, *(_statement_trade(*row) for row in _THREE))

    text, _ = toolkit.execute("get_trades", {"source": "store", "end": "2026-08-03"})

    assert "(1 executions" in text and "ESU6" in text and "TEST" not in text


def test_get_trades_store_filters_by_the_statement_symbol(toolkit):
    _seed_statements(toolkit, *(_statement_trade(*row) for row in _THREE))

    text, _ = toolkit.execute("get_trades", {"source": "store", "symbol": "esu6"})
    assert "(1 executions" in text and "Total realized P&L: -100.50 USD" in text

    root, _ = toolkit.execute("get_trades", {"source": "store", "symbol": "ES"})
    assert root.startswith("No trades found in Flex store"), "a future is listed under its contract symbol"


def test_get_trades_store_counts_an_execution_once_when_it_was_captured_live_first(toolkit):
    """F20's second defect: the legacy table held a live-captured fill and its statement row
    under two ids. Here the statement lands on the placeholder — one execution, one line."""
    from ibkr_core_mcp.store import SQLiteStore

    SQLiteStore(toolkit._config).upsert_flex_trades_from_live(
        [
            {
                "execution_id": "0000bbbb.00000001.01.01",
                "symbol": "ESU6",
                "side": "S",
                "size": 2,
                "price": 100.5,
                "time": "20260803-15:00:00",
                "commission": 1.25,
                "account": "U0000000",
            }
        ]
    )
    before, _ = toolkit.execute("get_trades", {"source": "store"})
    assert before.startswith("No trades found in Flex store"), "a placeholder is not a statement execution"

    _seed_statements(toolkit, _statement_trade(*_THREE[0]))
    text, _ = toolkit.execute("get_trades", {"source": "store"})

    assert "(1 executions" in text
    assert text.count("ESU6") == 1


def test_get_trades_store_labels_a_total_across_currencies(toolkit):
    _seed_statements(
        toolkit,
        _statement_trade(1, "2026-08-03", "TEST", "STK", -10.0),
        _statement_trade(2, "2026-08-04", "SAP", "STK", 5.0, currency="EUR"),
    )

    text, _ = toolkit.execute("get_trades", {"source": "store"})

    assert "Total realized P&L: -5.00 (mixed currencies: EUR, USD — a sum across them, not one currency)" in text


def test_get_trades_store_caps_the_listing_and_not_the_total(toolkit):
    _seed_statements(toolkit, *(_statement_trade(n, "2026-08-04", "TEST", "STK", 1.0) for n in range(1, 56)))

    text, _ = toolkit.execute("get_trades", {"source": "store"})

    assert "(55 executions, all origins incl. mobile/TWS)  (showing first 50 of 55):" in text
    assert sum(1 for line in text.splitlines() if line.startswith("- ")) == 50
    assert "Total realized P&L: +55.00 USD" in text


def test_get_trades_store_says_when_the_period_holds_nothing(toolkit):
    _seed_statements(toolkit, *(_statement_trade(*row) for row in _THREE))

    text, _ = toolkit.execute("get_trades", {"source": "store", "start": "2026-09-01"})

    assert text.startswith("No trades found in Flex store for the requested period.")


def test_get_trades_store_says_when_there_is_no_dataset_at_all(toolkit):
    """No store file: a sentence naming the remedy, not the generic store-error text."""
    text, _ = toolkit.execute("get_trades", {"source": "store"})

    assert text.startswith("No Flex dataset in the local store yet.")
    assert "sync_flex_trades" in text


def test_get_trades_store_refuses_a_date_it_cannot_read(toolkit):
    _seed_statements(toolkit, *(_statement_trade(*row) for row in _THREE))

    text, _ = toolkit.execute("get_trades", {"source": "store", "start": "03/08/2026"})

    assert text == "start and end must be dates in YYYY-MM-DD form."
