from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from .conftest import assert_tool_failed, assert_tool_succeeded

pytestmark = pytest.mark.account


def test_execute_get_account_summary(toolkit):
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.get_account_summary.return_value = {
        "netliquidation": {"amount": 100000},
        "totalcashvalue": {"amount": 50000},
    }
    text, fig = toolkit.execute("get_account_summary", {})
    assert fig is None
    assert_tool_succeeded(text)
    assert "Net Liquidation" in text
    assert "100,000" in text


def test_get_account_summary_omits_pnl_fields(toolkit):
    """/portfolio/{accountId}/summary never returns unrealizedpnl/realizedpnl keys
    (confirmed live 2026-07-17 + official IBKR docs) — the formatter must not
    claim to show them. Real P&L data comes from get_ledger/get_pnl instead."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U123"}]
    toolkit._client.get_account_summary.return_value = {
        "netliquidation": {"amount": 100000},
        "totalcashvalue": {"amount": 50000},
        "grosspositionvalue": {"amount": 20000},
        "buyingpower": {"amount": 80000},
    }
    text, fig = toolkit.execute("get_account_summary", {})
    assert fig is None
    assert "Unrealized P&L" not in text
    assert "Realized P&L" not in text
    assert "Net Liquidation" in text


def test_execute_get_notifications(toolkit):
    toolkit._client.get_notifications.return_value = [
        {"id": "1", "title": "Test alert", "body": "Something happened", "isRead": False}
    ]
    toolkit._client.get_unread_count.return_value = 1
    text, fig = toolkit.execute("get_notifications", {})
    assert_tool_succeeded(text)
    assert fig is None
    assert "Test alert" in text


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


def test_get_positions_renders_as_table_with_dollar_signs_and_bold_pnl(toolkit):
    """Cosmetic tweak requested 2026-07-17: positions render as a markdown
    table; mktVal/unrealPnL get $ + comma formatting, and unrealPnL is
    bolded with an explicit +/- sign so it stands out from the other
    columns (Chainlit escapes raw HTML, so color isn't available — bold
    + sign is the agreed substitute)."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U1234"}]
    toolkit._client.get_positions.return_value = [
        {"contractDesc": "GLD", "position": 100.0, "mktValue": 36840.0, "unrealizedPnl": -1487.09},
        {"contractDesc": "IGV", "position": 125.0, "mktValue": 11648.75, "unrealizedPnl": 564.06},
    ]
    text, fig = toolkit.execute("get_positions", {})
    assert fig is None
    assert "| Symbol | Qty | Mkt Val | Unrealized P&L |" in text
    assert "$36,840.00" in text
    assert "**-$1,487.09**" in text
    assert "**+$564.06**" in text


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
    # assert_tool_succeeded first: every assertion below is an absence check, and an
    # error string is absent everything. Without it this passed even when the handler
    # raised on every call.
    assert_tool_succeeded(text)
    assert "Cash Balance" in text, "the rows that should survive must actually be there"
    assert "Futures Market Value" not in text
    assert "Futures P&L" not in text


def test_get_ledger_empty(toolkit):
    toolkit._client.get_accounts.return_value = [{"accountId": "U1234"}]
    toolkit._client.get_account_ledger.return_value = {}
    text, fig = toolkit.execute("get_ledger", {})
    assert "No ledger data" in text


def test_get_ledger_dollar_signs_and_bold_pnl(toolkit):
    """Cosmetic tweak requested 2026-07-17: every dollar figure gets a $
    prefix; Net Liquidation Value and all three P&L rows (Unrealized,
    Realized, Futures) are bolded with an explicit +/- sign. Cash Balance
    and Stock Market Value are plain — not P&L, not explicitly called out."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U1234"}]
    toolkit._client.get_account_ledger.return_value = {
        "USD": {
            "netliquidationvalue": 63166.84,
            "cashbalance": 16045.96,
            "stockmarketvalue": 47131.85,
            "futuresonlymv": 0,
            "unrealizedpnl": -8107.13,
            "realizedpnl": 461.56,
            "futuresonlypnl": 475.00,
        }
    }
    text, fig = toolkit.execute("get_ledger", {})
    assert "**$63,166.84**" in text
    assert "$16,045.96" in text
    assert "**$16,045.96**" not in text
    assert "$47,131.85" in text
    assert "**-$8,107.13**" in text
    assert "**+$461.56**" in text
    assert "**+$475.00**" in text


# ── _get_pnl — official /iserver/account/pnl/partitioned response shape ──────
# Shape verified against https://ibkrcampus.com/docs/web-api/v1/endpoints/accounts/account-profit-and-loss.md
# (scraped 2026-07-02, re-verified 2026-07-07): {"upnl": {"<acct>.Core": {rowType,
# dpl, nl, upl, el, mv}}} — account/model-partition level, NOT per-position/conid.
# The old tests below invented a {account: {conid: {ticker, uPnl, dPnl}}} shape
# that never matched IBKR's real response — see docs/audits/claude-tools-audit-2026-07.md.


def test_get_pnl_empty(toolkit):
    """Empty first response now triggers a priming attempt before giving up.

    _prime_pnl_subscription is patched out so this stays a pure unit test (no
    real WS/network activity) — it still exercises the "still empty after
    priming" path since get_pnl.return_value (not side_effect) returns the
    same empty shape on the retry call too.
    """
    toolkit._client.get_pnl.return_value = {}
    with patch.object(toolkit, "_prime_pnl_subscription") as mock_prime, patch("time.sleep"):
        text, fig = toolkit.execute("get_pnl", {})
    mock_prime.assert_called_once()
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
    """A response with no 'upnl' key (e.g. an unexpected shape) must not crash.

    _prime_pnl_subscription is patched out (same reasoning as test_get_pnl_empty
    above) — this is now the expected code path for this fixture too.
    """
    toolkit._client.get_pnl.return_value = {"unexpected": {}}
    with patch.object(toolkit, "_prime_pnl_subscription") as mock_prime, patch("time.sleep"):
        text, fig = toolkit.execute("get_pnl", {})
    mock_prime.assert_called_once()
    assert "No P&L" in text


def test_get_pnl_retries_after_priming_when_first_call_empty(toolkit):
    """First REST call comes back empty (cold-gateway quirk, live-verified
    2026-07-17) -> _get_pnl primes the spl WS subscription once and retries
    the REST call, which then returns real data."""
    real_data = {
        "upnl": {
            "U1675699.Core": {
                "rowType": 1,
                "dpl": 663.8,
                "nl": 62990.0,
                "upl": -8270.0,
                "el": 45750.0,
                "mv": 46970.0,
            }
        }
    }
    toolkit._client.get_pnl.side_effect = [{"upnl": {}}, real_data]
    with patch.object(toolkit, "_prime_pnl_subscription") as mock_prime, patch("time.sleep"):
        text, fig = toolkit.execute("get_pnl", {})
    mock_prime.assert_called_once()
    assert toolkit._client.get_pnl.call_count == 2
    assert "U1675699.Core" in text
    assert "-8270.00" in text


def test_get_pnl_skips_priming_when_first_call_has_data(toolkit):
    """Priming must not run at all when the first REST call already has data."""
    toolkit._client.get_pnl.return_value = {
        "upnl": {
            "U1.Core": {"rowType": 1, "dpl": 1.0, "nl": 1000.0, "upl": 2.0, "el": 1000.0, "mv": 0.0},
        }
    }
    with patch.object(toolkit, "_prime_pnl_subscription") as mock_prime:
        text, fig = toolkit.execute("get_pnl", {})
    mock_prime.assert_not_called()
    assert toolkit._client.get_pnl.call_count == 1
    assert "U1.Core" in text


# ── _prime_pnl_subscription — best-effort spl WS warm-up touch ───────────────


def test_prime_pnl_subscription_touches_ws(toolkit):
    """Happy path: connect -> subscribe_pnl -> unsubscribe_pnl -> disconnect,
    all awaited, and the call returns None without raising."""
    mock_ws_instance = MagicMock()
    mock_ws_instance.connect = AsyncMock()
    mock_ws_instance.subscribe_pnl = AsyncMock()
    mock_ws_instance.unsubscribe_pnl = AsyncMock()
    mock_ws_instance.disconnect = AsyncMock()
    with (
        patch("ibkr_core_mcp.streaming.IBKRWebSocket", return_value=mock_ws_instance) as mock_ws_cls,
        patch("ibkr_core_mcp.auth.BrowserCookieAuth") as mock_auth_cls,
    ):
        mock_auth_cls.return_value.apply = MagicMock()
        result = toolkit._prime_pnl_subscription()
    assert result is None
    mock_ws_cls.assert_called_once()
    mock_ws_instance.connect.assert_awaited_once()
    mock_ws_instance.subscribe_pnl.assert_awaited_once()
    mock_ws_instance.unsubscribe_pnl.assert_awaited_once()
    mock_ws_instance.disconnect.assert_awaited_once()


def test_prime_pnl_subscription_swallows_ws_failure(toolkit, caplog):
    """Core robustness contract: a WS hiccup must never propagate out of
    _prime_pnl_subscription — it degrades to a logged warning instead."""
    mock_ws_instance = MagicMock()
    mock_ws_instance.connect = AsyncMock(side_effect=Exception("WS boom"))
    mock_ws_instance.subscribe_pnl = AsyncMock()
    mock_ws_instance.unsubscribe_pnl = AsyncMock()
    mock_ws_instance.disconnect = AsyncMock()
    with (
        patch("ibkr_core_mcp.streaming.IBKRWebSocket", return_value=mock_ws_instance),
        patch("ibkr_core_mcp.auth.BrowserCookieAuth") as mock_auth_cls,
        caplog.at_level("WARNING"),
    ):
        mock_auth_cls.return_value.apply = MagicMock()
        result = toolkit._prime_pnl_subscription()
    assert result is None
    mock_ws_instance.disconnect.assert_awaited_once()
    assert any("WS boom" in record.message for record in caplog.records)


# ── _preview_order — LMT includes price in order payload ─────────────────────


def test_get_watchlists_happy_path(toolkit):
    """Returns watchlist summary and raw JSON.

    The list endpoint returns metadata only, so the handler fetches each
    watchlist's instruments separately — see `_get_watchlists`.
    """
    toolkit._client.get_watchlists.return_value = [{"id": "wl1", "name": "My Watchlist", "read_only": False}]
    toolkit._client.get_watchlist.return_value = {
        "id": "wl1",
        "name": "My Watchlist",
        "instruments": [{"conid": 265598, "fullName": "AAPL"}, {"conid": 76792991, "fullName": "TSLA"}],
    }
    text, fig = toolkit.execute("get_watchlists", {})
    assert fig is None
    assert "My Watchlist" in text
    assert "AAPL" in text
    assert "TSLA" in text


def test_get_watchlists_fetches_contents_per_watchlist(toolkit):
    """The tool promises contents, so it must call get_watchlist for each id."""
    toolkit._client.get_watchlists.return_value = [
        {"id": "a", "name": "Alpha"},
        {"id": "b", "name": "Beta"},
    ]
    toolkit._client.get_watchlist.side_effect = [
        {"instruments": [{"fullName": "AAPL"}]},
        {"instruments": [{"fullName": "MSFT"}]},
    ]
    text, _ = toolkit.execute("get_watchlists", {})
    assert [c.args[0] for c in toolkit._client.get_watchlist.call_args_list] == ["a", "b"]
    assert "AAPL" in text and "MSFT" in text


def test_get_watchlists_survives_a_failed_contents_fetch(toolkit):
    """One unreadable watchlist must not blank out the whole listing."""
    toolkit._client.get_watchlists.return_value = [
        {"id": "a", "name": "Alpha"},
        {"id": "b", "name": "Beta"},
    ]
    toolkit._client.get_watchlist.side_effect = [RuntimeError("boom"), {"instruments": [{"fullName": "MSFT"}]}]
    text, _ = toolkit.execute("get_watchlists", {})
    assert "Alpha" in text and "Beta" in text
    assert "MSFT" in text
    assert "could not be read" in text


def test_get_watchlists_marks_ib_created_lists_read_only(toolkit):
    """system_lists arrive with read_only=True and must be distinguishable."""
    toolkit._client.get_watchlists.return_value = [
        {"id": "u1", "name": "Mine", "read_only": False},
        {"id": "s1", "name": "US Indices and ETFs", "read_only": True},
    ]
    toolkit._client.get_watchlist.return_value = {"instruments": []}
    text, _ = toolkit.execute("get_watchlists", {})
    assert "read-only" in text


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
    assert_tool_failed(text, containing="unexpected error")


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
    assert_tool_failed(text, containing="unexpected error")


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


def test_get_ledger_renders_an_unparseable_value_as_unknown_not_zero(toolkit):
    """`_f` returned 0.0 for anything float() choked on, so a value IBKR never
    reported — or reported with a thousands separator — rendered as a bolded
    "**$0.00**". Zero is a plausible, actionable number for a brokerage account;
    unknown is not zero, and nothing in the reply distinguished them."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U1234"}]
    toolkit._client.get_account_ledger.return_value = {
        "USD": {
            "netliquidationvalue": "n/a",
            "cashbalance": 0,
            "stockmarketvalue": 1000.0,
        }
    }
    text, _ = toolkit.execute("get_ledger", {})

    assert_tool_succeeded(text)
    assert "Net Liquidation Value : **—**" in text, "unreported must not read as zero"
    assert "Cash Balance          : $0.00" in text, "a genuine zero must still read as zero"


def test_get_ledger_parses_a_value_with_thousands_separators(toolkit):
    """IBKR has been observed returning "1,234,567.89"; float() raises on that."""
    toolkit._client.get_accounts.return_value = [{"accountId": "U1234"}]
    toolkit._client.get_account_ledger.return_value = {"USD": {"netliquidationvalue": "1,234,567.89"}}

    text, _ = toolkit.execute("get_ledger", {})

    assert "$1,234,567.89" in text


def test_get_watchlists_caps_contents_fetches_and_says_so(toolkit):
    """The real account has 8 user + 28 IB-created lists.

    Fetching contents for all of them is one API call each. The handler bounds that
    fan-out, and — per this repo's no-silent-caps rule — states what it skipped rather
    than quietly returning partial data that reads as complete.
    """
    from ibkr_core_mcp.claude_tools import _WATCHLIST_CONTENTS_LIMIT

    n = _WATCHLIST_CONTENTS_LIMIT + 6
    toolkit._client.get_watchlists.return_value = [{"id": str(i), "name": f"WL{i}"} for i in range(n)]
    toolkit._client.get_watchlist.return_value = {"instruments": [{"fullName": "AAPL"}]}
    text, _ = toolkit.execute("get_watchlists", {})

    assert toolkit._client.get_watchlist.call_count == _WATCHLIST_CONTENTS_LIMIT
    # Every watchlist is still listed — the cap limits contents, not visibility.
    assert f"({n} found)" in text
    assert "WL0" in text and f"WL{n - 1}" in text
    assert "contents not fetched" in text
