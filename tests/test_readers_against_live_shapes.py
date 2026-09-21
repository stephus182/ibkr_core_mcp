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
