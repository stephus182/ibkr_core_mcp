#!/usr/bin/env python3
"""List the half days the calendar library holds, beside the page each exchange publishes.

`SQLiteStore.get_market_calendar_context` states a half day from `exchange_calendars`
(`early_closes_today`). The library is the data; **the exchange's own page is the witness**.
Run this once a year, or before a release, and read each line against its page:

    python scripts/calendar_half_days.py

It prints, for every exchange of the default list, each early close from today to the end of
the library's range, in the exchange's own time. Nothing is fetched: the pages publish in a
table (London, Sydney, CME, Istanbul), a footnote (New York, Toronto), a PDF (Euronext), a
circular still to come (Frankfurt) and a JavaScript calendar (Hong Kong), so the comparison
is made by reading.

Last compared 2026-10-02 (library 4.13.2), eight exchanges: the DATE agreed on 17 of 17
checks; the TIME agreed for New York, London, Sydney and Toronto, differed for Istanbul
(library 12:30, the exchange "Until 13:00"), ran ahead of the exchange for Frankfurt
(2026-12-30 14:00 against "deviating trading hours may apply"), and was not read for Paris.
CME's hours differ by product group and are never taken from the library.
"""

from __future__ import annotations

from datetime import date

import exchange_calendars as ec
from pandas import Timestamp

from ibkr_core_mcp.store import SQLiteStore

# Each exchange's own page, checked to resolve on 2026-10-02. None: not looked for yet.
OFFICIAL_PAGES: dict[str, str] = {
    "XNYS": "https://www.nyse.com/markets/hours-calendars",
    "CME": "https://www.cmegroup.com/tools-information/holiday-calendar.html",
    "XLON": "https://www.londonstockexchange.com/equities-trading/business-days",
    "XETR": "https://www.cashmarket.deutsche-boerse.com/cash-en/trading/trading-calendar-and-trading-hours",
    "XPAR": "https://www.euronext.com/en/trading/trading-hours-holidays",
    "XMIL": "https://www.euronext.com/en/trading/trading-hours-holidays",
    "XHKG": "https://www.hkex.com.hk/News/HKEX-Calendar?sc_lang=en",
    "XASX": "https://www.asx.com.au/markets/market-resources/trading-hours-calendar/cash-market-trading-hours/trading-calendar",
    "XTSE": "https://www.tsx.com/en/trading/calendars-and-trading-hours/calendar",
    "XIST": "https://www.borsaistanbul.com/en/official-holidays",
}


def main() -> None:
    """Print each exchange's early closes from today, with the page to read them against."""
    today = Timestamp(date.today())
    for code in SQLiteStore.get_market_calendar_context()["holidays_by_exchange"]:
        calendar = ec.get_calendar(code)
        half_days = [day for day in calendar.early_closes if day >= today]
        print(
            f"{code}  (library data through {calendar.last_session.date()})  {OFFICIAL_PAGES.get(code, 'no page recorded')}"
        )
        for day in half_days:
            close = calendar.session_close(day).tz_convert(calendar.tz)
            print(f"    {day.date()}  closes {close:%H:%M} {calendar.tz}")
        if not half_days:
            print("    no early close listed")


if __name__ == "__main__":
    main()
