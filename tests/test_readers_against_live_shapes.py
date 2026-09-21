"""Every reader is run against the SHAPE IBKR actually sends, and may not miss a key.

## Why this file exists

On 2026-09-21 `claude_tools._preview_order` was found reading four keys the whatif does not
send — `commission`, `equity.amount`, `initMarginChange`, `maintMarginChange`, where the
response carries `amount.commission`, `equity.current`, `initial.change` and
`maintenance.change`. Four of its five rendered lines were therefore `N/A` on every real
call, and it read neither `error` nor `warns`, so a preview IBKR **refused** rendered
identically to one it accepted.

Nothing caught it for as long as it existed, and the reason is worth stating plainly: the
tests mocked a response invented to match the reader, and asserted the *request* payload
plus the literal string `"Order Preview"` — never a rendered figure. A double easier than
the real thing keeps a broken path green forever.

`tests/fixtures/ibkr_live_shapes.json` already held 40 endpoints captured from a live
gateway and redacted by `scripts/audit/redact_live_payload.py`. The whatif was not among
them, and deliberately so: the capture script is read-only and says
`get_order_preview` "simulates but still POSTs an order body, so it is captured only with
the owner present and asking for it". That condition was met on 2026-09-21 and it is now
captured.

## What this file asserts, and why it is a CLASS-level control

A reader is run against the real captured shape through a mapping that **records every key
lookup that missed**. Values are irrelevant — the fixture's are all `REDACTED` / `1111.11`
— because the defect was never about values. It was about indexing into keys that are not
there, which a redacted shape proves exactly as well as a live one.

So this does not test "the preview formatter works". It asserts a property no reader may
violate: *you may not read a key IBKR does not send*. Adding a reader to `READERS` below
buys that guarantee; forgetting to is the only way to escape it, which is why the list is
held against the module by `test_every_registered_reader_is_still_callable`.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest

from ibkr_core_mcp.claude_tools import _format_order_preview

FIXTURES = Path(__file__).parent / "fixtures" / "ibkr_live_shapes.json"


class KeyWatcher(Mapping[str, Any]):
    """A read-only view over a captured payload that records lookups which MISSED.

    Nested mappings are wrapped too, so `result["equity"]["amount"]` is recorded as
    `equity.amount` rather than silently yielding `None` two levels down — which is the
    exact shape of the defect this file exists to prevent.

    `.get()` still returns the default on a miss and `__getitem__` still raises, so a
    reader behaves normally; the miss is recorded rather than forced into a failure, and
    the assertion is made once, at the end, over everything that missed.
    """

    def __init__(self, data: Mapping[str, Any], path: str = "", missed: list[str] | None = None) -> None:
        self._data = data
        self._path = path
        self.missed: list[str] = [] if missed is None else missed

    def _wrap(self, key: str, value: Any) -> Any:
        if isinstance(value, Mapping):
            return KeyWatcher(value, f"{self._path}{key}.", self.missed)
        return value

    def __getitem__(self, key: str) -> Any:
        if key not in self._data:
            self.missed.append(f"{self._path}{key}")
            raise KeyError(key)
        return self._wrap(key, self._data[key])

    def get(self, key: str, default: Any = None) -> Any:
        if key not in self._data:
            self.missed.append(f"{self._path}{key}")
            return default
        return self._wrap(key, self._data[key])

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)


def _run_preview(shape: Mapping[str, Any]) -> str:
    return _format_order_preview(shape, "Order Preview: BUY 1 AAPL (LMT)")


# (fixture endpoint, human name, the reader). One row per reader that consumes a captured
# IBKR response. A reader absent from this list is simply unguarded — see the module
# docstring.
READERS: list[tuple[str, str, Any]] = [
    ("order_preview", "claude_tools._format_order_preview", _run_preview),
]


@pytest.mark.parametrize(("endpoint", "name", "reader"), READERS, ids=[r[1] for r in READERS])
def test_a_reader_looks_up_no_key_ibkr_does_not_send(endpoint: str, name: str, reader: Any) -> None:
    """The control. Fails the moment a reader indexes a key absent from the live shape."""
    shape = json.loads(FIXTURES.read_text())[endpoint]
    watcher = KeyWatcher(shape)
    reader(watcher)
    assert not watcher.missed, (
        f"{name} read {len(watcher.missed)} key(s) absent from the live `{endpoint}` shape: "
        f"{watcher.missed}. Either IBKR renamed them, or the reader was written against a "
        f"shape IBKR does not send — which is how the 2026-09-21 preview defect survived."
    )


def test_the_watcher_actually_catches_a_missing_key() -> None:
    """The control must be able to fail, or the test above passes for free.

    This reproduces the 2026-09-21 defect exactly: the four keys the old reader used.
    """
    shape = json.loads(FIXTURES.read_text())["order_preview"]
    watcher = KeyWatcher(shape)
    # Verbatim the reads `_preview_order` performed before the fix.
    watcher.get("commission", "N/A")
    watcher.get("equity", {}).get("amount", "N/A")
    watcher.get("initMarginChange", "N/A")
    watcher.get("maintMarginChange", "N/A")
    watcher.get("equity", {}).get("change", "N/A")  # the one that WAS correct
    assert watcher.missed == ["commission", "equity.amount", "initMarginChange", "maintMarginChange"], watcher.missed


def test_the_watcher_records_nothing_when_every_key_is_present() -> None:
    """The discriminating half: a correct reader must leave `missed` empty."""
    shape = json.loads(FIXTURES.read_text())["order_preview"]
    watcher = KeyWatcher(shape)
    watcher.get("amount", {}).get("commission")
    watcher.get("initial", {}).get("change")
    watcher.get("maintenance", {}).get("change")
    watcher.get("equity", {}).get("current")
    watcher.get("error")
    watcher.get("warns")
    assert watcher.missed == []


def test_every_registered_reader_is_still_callable() -> None:
    """A row whose endpoint left the fixture, or whose reader was renamed, must fail here
    rather than quietly stop guarding anything."""
    payload = json.loads(FIXTURES.read_text())
    for endpoint, name, reader in READERS:
        assert endpoint in payload, f"{name} is registered against `{endpoint}`, which is not in the fixture"
        assert callable(reader), name


# ---------------------------------------------------------------------------------------
# Readers whose endpoint is DOCUMENTED but not live-captured
# ---------------------------------------------------------------------------------------
# `_cancel_dialog_details` was added on 2026-09-21 — in the same release as the control
# above — and indexes fourteen keys of `GET /iserver/account/order/status/{orderId}`. That
# endpoint is not in `ibkr_live_shapes.json` and cannot be: the capture script is read-only
# and this response needs a resting order to exist, so there is nothing for it to capture on
# demand. Registering it against the live fixture is therefore impossible, and leaving it
# unguarded would mean the release that built a class-level control shipped a new reader
# outside it.
#
# So the shape is pinned from IBKR's own published response object instead — the same
# fallback the changelog records for `modify_order` ("Its shape is pinned from IBKR's
# documented example"). A documented shape is weaker evidence than a captured one and is
# labelled as such; it still answers the question this control asks, which is whether a
# reader indexes a key the endpoint does not carry.
#
# Source: https://www.interactivebrokers.com/docs/web-api/v1/endpoints/order-monitoring/order-status.md
#         (fetched 2026-09-21, 5,977 B, with a fabricated control URL in the same batch
#         returning 440 B "# Page Not Found")
_ORDER_STATUS_DOC_SHAPE: dict[str, Any] = {
    "sub_type": None,
    "request_id": "209",
    "server_id": "0",
    "order_id": 1799796559,
    "conidex": "265598",
    "conid": 265598,
    "symbol": "AAPL",
    "side": "S",
    "contract_description_1": "AAPL",
    "listing_exchange": "NASDAQ.NMS",
    "option_acct": "c",
    "company_name": "APPLE INC",
    "size": "0.0",
    "total_size": "5.0",
    "currency": "USD",
    "account": "U1234567",
    "order_type": "MARKET",
    "cum_fill": "5.0",
    "order_status": "Filled",
    "order_ccp_status": "2",
    "order_status_description": "Order Filled",
    "tif": "DAY",
    "fg_color": "#FFFFFF",
    "bg_color": "#000000",
    "order_not_editable": True,
    "editable_fields": "",
    "cannot_cancel_order": True,
    "deactivate_order": False,
    "sec_type": "STK",
    "available_chart_periods": "#R|1",
    "order_description": "Sold 5 Market, Day",
    "order_description_with_contract": "Sold 5 AAPL Market, Day",
    "alert_active": 1,
    "child_order_type": "0",
    "order_clearing_account": "U1234567",
    "size_and_fills": "5",
    "exit_strategy_display_price": "193.12",
    "exit_strategy_chart_description": "Sold 5 @ 192.26",
    "average_price": "192.26",
    "exit_strategy_tool_availability": "1",
    "allowed_duplicate_opposite": True,
    "order_time": "231211180049",
}

# Keys a reader may look up that IBKR's documentation does NOT list, each with the evidence
# that they are nonetheless real. An entry here is a claim about the live wire, so it carries
# its measurement; an unexplained entry is how an allow-list becomes an escape hatch.
_MEASURED_BUT_UNDOCUMENTED: dict[str, str] = {
    "limit_price": (
        "Measured live 2026-09-04 on three resting orders — '150.00', '7660.00' on limit "
        "orders — and recorded in claudia_ui's order_flow._price_readback_fields. Absent "
        "from both the field list and the example on IBKR's order-status page."
    ),
    "stop_price": (
        "Measured the same day on a stop ('7732.00', with limit_price ''), same source, "
        "also absent from IBKR's documented response."
    ),
}


def _run_cancel_dialog_details(shape: Mapping[str, Any]) -> Any:
    """Drive the reader with `get_order_status` answering the watched shape."""
    from unittest.mock import patch

    from ibkr_core_mcp.auth import NoAuth
    from ibkr_core_mcp.client import IBKRClient
    from ibkr_core_mcp.config import Config

    client = IBKRClient(
        Config(
            gateway_url="https://localhost:5055/v1/api",
            gdrive_folder_id="x",
            sqlite_path=Path("/tmp/unused.db"),
            gdrive_token_file=Path("/tmp/unused-token.json"),
            gdrive_credentials_file=Path("/tmp/unused-creds.json"),
        ),
        auth=NoAuth(),
    )
    client._accounts_initialized = True
    with patch.object(client, "get_order_status", return_value=shape):
        return client._cancel_dialog_details("1799796559")


DOC_SHAPE_READERS: list[tuple[str, dict[str, Any], Any]] = [
    ("client._cancel_dialog_details", _ORDER_STATUS_DOC_SHAPE, _run_cancel_dialog_details),
]


@pytest.mark.parametrize(("name", "shape", "reader"), DOC_SHAPE_READERS, ids=[r[0] for r in DOC_SHAPE_READERS])
def test_a_reader_of_a_documented_shape_looks_up_no_key_outside_it(
    name: str, shape: dict[str, Any], reader: Any
) -> None:
    """Same property as the live-shape control, against IBKR's published shape."""
    watcher = KeyWatcher(shape)
    reader(watcher)
    unexplained = [key for key in watcher.missed if key not in _MEASURED_BUT_UNDOCUMENTED]
    assert not unexplained, (
        f"{name} read {len(unexplained)} key(s) that IBKR neither documents nor is measured "
        f"to send: {unexplained}. Either the key is wrong, or it is real and belongs in "
        f"_MEASURED_BUT_UNDOCUMENTED with the measurement that proves it."
    )


def test_the_cancel_dialog_reader_actually_PRODUCES_detail_from_that_shape() -> None:
    """The discriminating half, and the one that matters most here.

    A reader that read nothing at all would satisfy the assertion above for free — no
    lookups, no misses. This requires the shape to come out the other end as real rows, so
    the control cannot pass by the reader having done nothing.

    It also pins the `Mapping`-not-`dict` property: `KeyWatcher` is a `collections.abc.
    Mapping` and is not a `dict`, exactly like a typed `IBKRResponse`. Against the
    `isinstance(status, dict)` this reader shipped with, it returns None here.
    """
    details = _run_cancel_dialog_details(KeyWatcher(_ORDER_STATUS_DOC_SHAPE))
    assert details is not None, "the reader produced nothing — the control above would pass vacuously"
    assert details["ticker"] == "AAPL"
    assert details["side"] == "SELL"
    assert details["quantity"] == "5.0"
    assert "Filled" in details["_current_description"]


def test_the_doc_shape_control_catches_a_key_that_is_neither_documented_nor_measured() -> None:
    """The vacuity check. A reader inventing a key must fail, or the control above is
    decoration — and the allow-list must not be what lets it through."""
    watcher = KeyWatcher(_ORDER_STATUS_DOC_SHAPE)
    watcher.get("limitPrice")  # the camelCase spelling this endpoint does not use
    watcher.get("orderDescription")
    unexplained = [key for key in watcher.missed if key not in _MEASURED_BUT_UNDOCUMENTED]
    assert unexplained == ["limitPrice", "orderDescription"], unexplained


def test_every_allow_listed_key_carries_its_evidence() -> None:
    """An allow-list entry is a claim about the live wire. One without a measurement behind
    it is an escape hatch, which is how the redaction guard went vacuous on 2026-09-21."""
    for key, why in _MEASURED_BUT_UNDOCUMENTED.items():
        assert "Measured" in why or "measured" in why, f"{key} is allow-listed with no measurement: {why!r}"
