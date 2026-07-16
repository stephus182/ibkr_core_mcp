import pytest

pytestmark = pytest.mark.account


def test_execute_get_account_summary(toolkit):
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.get_account_summary.return_value = {
        "netliquidation": {"amount": 100000},
        "totalcashvalue": {"amount": 50000},
    }
    text, fig = toolkit.execute("get_account_summary", {})
    assert fig is None
    assert len(text) > 0


def test_execute_get_notifications(toolkit):
    toolkit._client.get_notifications.return_value = [
        {"id": "1", "title": "Test alert", "body": "Something happened", "isRead": False}
    ]
    toolkit._client.get_unread_count.return_value = 1
    text, fig = toolkit.execute("get_notifications", {})
    assert len(text) > 0
    assert fig is None


def test_get_positions_empty(toolkit):
    toolkit._client.get_accounts.return_value = [{"accountId": "U1234"}]
    toolkit._client.get_positions.return_value = []
    text, fig = toolkit.execute("get_positions", {})
    assert "No open positions" in text


def test_get_positions_filters_zero_size(toolkit):
    """position=0 means flat — excluded regardless of instrument type."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U1234"}]
    toolkit._client.get_positions.return_value = [
        {"contractDesc": "AAPL", "position": 100, "mktValue": 18000.0, "unrealizedPnl": 500.0},
        {"contractDesc": "CLOSED_STOCK", "position": 0, "mktValue": 0.0, "unrealizedPnl": 0.0},
        {"contractDesc": "CLOSED_FUTURE", "position": 0, "mktValue": 0.0, "unrealizedPnl": 0.0},
        {"contractDesc": "CLOSED_OPTION", "position": 0, "mktValue": 0.0, "unrealizedPnl": 0.0},
    ]
    text, fig = toolkit.execute("get_positions", {})
    assert "AAPL" in text
    assert "CLOSED_STOCK" not in text
    assert "CLOSED_FUTURE" not in text
    assert "CLOSED_OPTION" not in text
    assert "Open positions (1)" in text


def test_get_positions_all_zero_returns_empty(toolkit):
    """All-zero portfolio returns 'No open positions'."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U1234"}]
    toolkit._client.get_positions.return_value = [
        {"contractDesc": "FLAT_A", "position": 0, "mktValue": 0.0, "unrealizedPnl": 0.0},
        {"contractDesc": "FLAT_B", "position": 0, "mktValue": 0.0, "unrealizedPnl": 0.0},
    ]
    text, fig = toolkit.execute("get_positions", {})
    assert "No open positions" in text


def test_get_positions_field_fallback(toolkit):
    """Position summary should use contractDesc → ticker → symbol in that order."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U1234"}]
    toolkit._client.get_positions.return_value = [
        {"contractDesc": "AAPL", "position": 100, "mktValue": 18000.0, "unrealizedPnl": 500.0},
        {"ticker": "TSLA", "position": 10, "mktValue": 2500.0, "unrealizedPnl": -50.0},
        {"symbol": "GOOG", "position": 5, "mktValue": 7500.0, "unrealizedPnl": 100.0},
    ]
    text, fig = toolkit.execute("get_positions", {})
    assert "AAPL" in text
    assert "TSLA" in text
    assert "GOOG" in text


# ── _get_ledger ───────────────────────────────────────────────────────────────


def test_get_ledger_formats_usd(toolkit):
    """Ledger formats key fields from the USD currency block."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U1234"}]
    toolkit._client.get_account_ledger.return_value = {
        "USD": {
            "netliquidationvalue": 67516.82,
            "cashbalance": 22637.43,
            "stockmarketvalue": 44879.61,
            "futuresonlymv": 1150.0,
            "unrealizedpnl": -10359.37,
            "realizedpnl": 1145.50,
            "futuresonlypnl": 1150.0,
            "accruals": -44.22,
            "dividends": 44.0,
        }
    }
    text, fig = toolkit.execute("get_ledger", {})
    assert "67,516.82" in text
    assert "22,637.43" in text
    assert "USD" in text
    assert "Futures Market Value" in text
    assert "1,150.00" in text
    assert fig is None


def test_get_ledger_omits_zero_futures(toolkit):
    """Futures rows are suppressed when futures market value and P&L are zero."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U1234"}]
    toolkit._client.get_account_ledger.return_value = {
        "USD": {
            "netliquidationvalue": 50000.0,
            "cashbalance": 10000.0,
            "stockmarketvalue": 40000.0,
            "futuresonlymv": 0,
            "unrealizedpnl": -500.0,
            "realizedpnl": 0,
            "futuresonlypnl": 0,
        }
    }
    text, fig = toolkit.execute("get_ledger", {})
    assert "Futures Market Value" not in text
    assert "Futures P&L" not in text


def test_get_ledger_empty(toolkit):
    toolkit._client.get_accounts.return_value = [{"accountId": "U1234"}]
    toolkit._client.get_account_ledger.return_value = {}
    text, fig = toolkit.execute("get_ledger", {})
    assert "No ledger data" in text


# ── _get_pnl — official /iserver/account/pnl/partitioned response shape ──────
# Shape verified against https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#account-pnl
# (scraped 2026-07-02, re-verified 2026-07-07): {"upnl": {"<acct>.Core": {rowType,
# dpl, nl, upl, el, mv}}} — account/model-partition level, NOT per-position/conid.
# The old tests below invented a {account: {conid: {ticker, uPnl, dPnl}}} shape
# that never matched IBKR's real response — see docs/audits/claude-tools-audit-2026-07.md.


def test_get_pnl_empty(toolkit):
    toolkit._client.get_pnl.return_value = {}
    text, fig = toolkit.execute("get_pnl", {})
    assert "No P&L" in text or "P&L" in text


def test_get_pnl_reports_account_partition_totals(toolkit):
    toolkit._client.get_pnl.return_value = {
        "upnl": {
            "U1675699.Core": {
                "rowType": 1,
                "dpl": 15.7,
                "nl": 10000.0,
                "upl": 607.0,
                "el": 10000.0,
                "mv": 0.0,
            }
        }
    }
    text, fig = toolkit.execute("get_pnl", {})
    assert "U1675699.Core" in text
    assert "607.00" in text  # unrealized
    assert "15.70" in text  # daily


def test_get_pnl_multiple_account_partitions(toolkit):
    toolkit._client.get_pnl.return_value = {
        "upnl": {
            "U1.Core": {"rowType": 1, "dpl": 10.0, "nl": 5000.0, "upl": 20.0, "el": 5000.0, "mv": 0.0},
            "U2.Core": {"rowType": 1, "dpl": -5.0, "nl": 2000.0, "upl": -8.0, "el": 2000.0, "mv": 0.0},
        }
    }
    text, fig = toolkit.execute("get_pnl", {})
    assert "U1.Core" in text and "U2.Core" in text
    assert "+12.00" in text  # total unrealized: 20 + -8
    assert "+5.00" in text  # total daily: 10 + -5


def test_get_pnl_skips_non_numeric(toolkit):
    toolkit._client.get_pnl.return_value = {
        "upnl": {
            "U1234.Core": {"rowType": 1, "dpl": "N/A", "nl": 10000.0, "upl": "N/A", "el": 10000.0, "mv": 0.0},
        }
    }
    text, fig = toolkit.execute("get_pnl", {})
    # Should not raise; malformed partition skipped, totals still print
    assert "Total" in text


def test_get_pnl_missing_upnl_key_returns_no_data_message(toolkit):
    """A response with no 'upnl' key (e.g. an unexpected shape) must not crash."""
    toolkit._client.get_pnl.return_value = {"unexpected": {}}
    text, fig = toolkit.execute("get_pnl", {})
    assert "No P&L" in text


# ── _preview_order — LMT includes price in order payload ─────────────────────


def test_get_watchlists_happy_path(toolkit):
    """Returns watchlist summary and raw JSON."""
    toolkit._client.get_watchlists.return_value = [
        {
            "id": "wl1",
            "name": "My Watchlist",
            "rows": [{"ST": "AAPL"}, {"ST": "TSLA"}],
        }
    ]
    text, fig = toolkit.execute("get_watchlists", {})
    assert fig is None
    assert "My Watchlist" in text
    assert "AAPL" in text
    assert "TSLA" in text


def test_get_watchlists_empty(toolkit):
    """Returns 'No watchlists' when IBKR returns empty list."""
    toolkit._client.get_watchlists.return_value = []
    text, fig = toolkit.execute("get_watchlists", {})
    assert fig is None
    assert "No watchlists" in text


def test_get_watchlists_error(toolkit):
    """Propagates exception through _safe_error."""
    toolkit._client.get_watchlists.side_effect = RuntimeError("watchlist timeout")
    text, fig = toolkit.execute("get_watchlists", {})
    assert fig is None
    assert "unexpected" in text.lower()


# ============================================================================
# _get_trading_schedule
# ============================================================================


def test_get_allocation_happy_path(toolkit):
    """Returns JSON allocation data."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.get_account_allocation.return_value = {"assetClass": {"long": {"STK": 0.85, "CASH": 0.15}}}
    text, fig = toolkit.execute("get_allocation", {})
    assert fig is None
    assert "assetClass" in text
    assert "STK" in text


def test_get_allocation_error(toolkit):
    """Propagates exception through _safe_error."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.get_account_allocation.side_effect = RuntimeError("allocation unavailable")
    text, fig = toolkit.execute("get_allocation", {})
    assert fig is None
    assert "unexpected" in text.lower()


# ============================================================================
# _get_order_status
# ============================================================================


def test_get_positions_tolerates_null_value_fields(toolkit):
    """IBKR can send present-but-null mktValue/unrealizedPnl — must render as 0.00,
    not crash into _safe_error (audit Appendix C minor, lines 1099-1101)."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U1234"}]
    toolkit._client.get_positions.return_value = [
        {"contractDesc": "GLD", "position": 100, "mktValue": None, "unrealizedPnl": None},
    ]
    text, fig = toolkit.execute("get_positions", {})
    assert "GLD" in text
    assert "0.00" in text
    assert "error" not in text.lower()
