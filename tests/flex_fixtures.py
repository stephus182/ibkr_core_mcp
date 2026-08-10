"""Synthetic Flex statement builders shared by the import and script test suites.

Every account id, symbol, price and identifier here is **fabricated**. Real statements
carry live account data and this package is published, so no archived statement is ever
committed to the repo.

The builders derive their attribute set from :mod:`ibkr_core_mcp.flex_schema` rather than
hardcoding one. That matters: a statement fixture frozen as a static ``.xml`` file would
silently stop exercising the schema the day ``scripts/audit_flex_xml.py`` regenerates it,
and "the fixture no longer matches the schema" is exactly the drift these tests exist to
catch. Building from ``ELEMENTS`` means the fixture cannot rot.

Two byte-literals are the deliberate exception, because their *exact shape* is the thing
under test rather than their contents: :data:`WARN_1019_XML` (what IBKR actually returns
while a statement is still generating) and :data:`TRUNCATED_XML`.
"""

from __future__ import annotations

from ibkr_core_mcp.flex_schema import ELEMENTS

# ── Payloads that are not statements ────────────────────────────────────────────

#: What IBKR returns while a report is still being built. Reproduced from a real
#: response observed 2026-07-02 and archived to Drive by the pre-fix fetch path, with
#: the account number replaced. `flex_query.py` now retries this at fetch time, but a
#: copy of one is still reachable from Drive, so every consumer must refuse it.
#: Official text confirmed against
#: https://www.ibkrguides.com/clientportal/performanceandstatements/flex3error.htm
WARN_1019_XML = (
    "<FlexStatementResponse timestamp='02 July, 2026 08:05 PM EDT'>\n"
    "<Status>Warn</Status>\n"
    "<ErrorCode>1019</ErrorCode>\n"
    "<ErrorMessage>Statement generation in progress. Please try again shortly.</ErrorMessage>\n"
    "</FlexStatementResponse>\n"
)

#: A statement cut off mid-write — the disk-full / interrupted-download shape.
TRUNCATED_XML = '<FlexQueryResponse queryName="Synthetic" type="AF"><FlexStatements count="1"><FlexStatement'


# ── Statement builders ──────────────────────────────────────────────────────────

_TRADE_DEFAULTS = {
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


def element(tag: str, **overrides: str) -> str:
    """Render one element of `tag` carrying every attribute the schema knows.

    Attributes not overridden are emitted empty, which is what IBKR itself does for
    inapplicable fields.
    """
    attrs = dict.fromkeys(ELEMENTS[tag]["columns"], "")
    attrs.update(overrides)
    body = " ".join(f'{k}="{v}"' for k, v in attrs.items())
    return f"<{tag} {body} />"


def trade(**overrides: str) -> str:
    """Render a `<Trade>` with all of the schema's attributes, overridable per test."""
    attrs = dict.fromkeys(ELEMENTS["Trade"]["columns"], "")
    attrs.update(_TRADE_DEFAULTS)
    attrs.update(overrides)
    body = " ".join(f'{k}="{v}"' for k, v in attrs.items())
    return f"<Trade {body} />"


def statement(
    inner: str = "",
    *,
    account_id: str = "U0000000",
    from_date: str = "20260601",
    to_date: str = "20260630",
    when_generated: str = "20260701;120000",
    query_name: str = "Synthetic",
    query_type: str = "AF",
) -> str:
    """Wrap rendered elements in a `<FlexQueryResponse>` envelope.

    `parse_statement` walks the tree with `root.iter(tag)`, so the real per-section
    containers (`<Trades>`, `<OpenPositions>`, …) are not required and are omitted.
    """
    return (
        f'<FlexQueryResponse queryName="{query_name}" type="{query_type}">'
        '<FlexStatements count="1">'
        f'<FlexStatement accountId="{account_id}" fromDate="{from_date}" toDate="{to_date}"'
        f' period="" whenGenerated="{when_generated}">'
        f"{inner}"
        "</FlexStatement></FlexStatements></FlexQueryResponse>"
    )


def annual_statement(
    year: int,
    *,
    trade_ids: tuple[int, ...] = (),
    pnl_per_trade: float = 0.0,
    from_date: str | None = None,
    to_date: str | None = None,
) -> str:
    """A statement shaped like IBKR's annual one: first trading day → last.

    `audit_flex_dataset.annual_windows` recognises an annual statement from its dates
    alone (opens on/before Jan 7, closes on/after Dec 24), so the defaults here sit
    inside that window deliberately. Pass `from_date`/`to_date` to fall outside it.

    A matching `<SymbolSummary>` carrying the same total is emitted so the calendar-year
    reconciliation (check 17c) has both sides to compare, and one `<Lot>` per trade so
    the realised-P&L identity (check 17: trades == lots + wash-sale disallowed) balances
    the way a real statement does. Each Lot points at its trade's `transactionID`, which
    is what check 17f requires.
    """
    start = from_date or f"{year}0102"
    end = to_date or f"{year}1231"
    rows = []
    for tid in trade_ids:
        rows.append(
            trade(
                tradeID=str(tid),
                transactionID=str(tid + 100_000_000),
                ibExecID=f"0000aaaa.{tid:08d}.01.01",
                tradeDate=f"{year}0615",
                dateTime=f"{year}0615;093001",
                reportDate=f"{year}0615",
                fifoPnlRealized=str(pnl_per_trade),
                openCloseIndicator="C",
            )
        )
        rows.append(
            element(
                "Lot",
                accountId="U0000000",
                symbol="TEST",
                assetCategory="STK",
                transactionID=str(tid + 100_000_000),
                tradeID=str(tid),
                tradeDate=f"{year}0615",
                fifoPnlRealized=str(pnl_per_trade),
            )
        )
    rows.append(
        element(
            "SymbolSummary",
            accountId="U0000000",
            symbol="TEST",
            assetCategory="STK",
            fifoPnlRealized=str(pnl_per_trade * len(trade_ids)),
            tradeDate=f"{year}0615",
        )
    )
    return statement(
        "".join(rows),
        from_date=start,
        to_date=end,
        when_generated=f"{year + 1}0102;120000",
    )
