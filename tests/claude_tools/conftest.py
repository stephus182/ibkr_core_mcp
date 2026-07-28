from unittest.mock import MagicMock

import pytest


@pytest.fixture
def toolkit(mock_config):
    from ibkr_core_mcp.claude_tools import ClaudeToolkit

    client = MagicMock()
    # A single unambiguous US listing — the shape /trsrv/stocks returns for an ordinary
    # ticker. Set here rather than in each test because most tests that resolve a symbol
    # are not *about* resolution (preview_order, pa_transactions, alerts); a bare
    # MagicMock would make them fail on the resolver's structure instead of on their own
    # subject. Tests that ARE about resolution override it.
    client.get_stocks.return_value = [
        {
            "name": "TEST CO",
            "assetClass": "STK",
            "contracts": [{"conid": 265598, "exchange": "NASDAQ", "isUS": True}],
        }
    ]
    # Currency is read once per resolved conid; keep it a real string so output
    # assertions see "USD" rather than a MagicMock repr.
    client.get_secdef_info.return_value = [{"conid": 265598, "currency": "USD"}]
    cache = MagicMock()
    store = MagicMock()
    return ClaudeToolkit(client, cache, store, mock_config)
