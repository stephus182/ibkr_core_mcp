"""Strip the account holder out of a captured IBKR payload, keeping its shape exactly.

The first version of this lived inline in `capture_live_response_shapes.py` and rewrote
**account numbers only**. Its post-write assertion checked account numbers only too, so it
passed while the fixture published the holder's legal name, net liquidation value, cash
balance, buying power, open positions, four executed futures fills with their IBKR
execution IDs, a resting order and every watchlist name.

So the rule here is inverted. In an owner-scoped payload **every scalar is replaced**
unless its key is on `STRUCTURAL` below — IBKR's own vocabulary and public reference data,
which the models parse and which is identical for every IBKR customer. A new field IBKR
adds tomorrow is therefore redacted by default rather than published by default.

Types are preserved exactly (int stays int, float stays float, str stays str, bool and
None are structural), because `tests/test_models_live_shapes.py` asserts model fields
against the raw payload and needs the shape, never the values.
"""

from __future__ import annotations

import re
from typing import Any

ACCOUNT_ID_RE = re.compile(r"U\d{6,9}(?!\d)")
PLACEHOLDER_ACCOUNT = "U1234567"

# Endpoints that return the same bytes to every IBKR customer: contract reference data and
# market metadata. Nothing in them names or describes the account holder.
PUBLIC_ENDPOINTS = frozenset(
    {
        "search_contract",
        "contract_info",
        "secdef",
        "stocks",
        "currency_pairs",
        "trading_schedule",
        "market_snapshot",
        "scanner_params",
    }
)

# Keys whose values are IBKR vocabulary or public reference data, kept so the fixture stays
# usable as evidence of what IBKR sends. Every one is a value that is the same for any
# customer looking at the same contract.
STRUCTURAL = frozenset(
    {
        # Pure vocabulary: the same token for every customer, and the models parse them.
        "currency",
        "cashccy",
        "sectype",
        "sec_type",
        "assetclass",
        "type",
        # Envelope scaffolding in /portfolio/{id}/ledger and /portfolio/{id}/summary.
        "key",
        "secondkey",
        "rowtype",
        "isnull",
        "severity",
        "group",
        "model",
        # The capture script's own marker, not IBKR data.
        "__truncated__",
    }
)

# Deliberately NOT structural, though a first pass had them there: `conid`, `conidex`,
# `fullname`, `contractdesc`, `symbol`, `ticker`, `undconid`, `undsym`, `tradingclass`,
# `expiry`, `strike`, `putorcall`, `multiplier`, `exchange`, `listingexchange`,
# `allexchanges`. Each is IBKR vocabulary in the abstract — and inside a POSITIONS or
# TRADES payload each one names what the account holder owns or traded. `fullname` is how
# `GLD` and `IGV` survived the first run of this redactor: exempted as reference data,
# published as a holding.

# Deterministic stand-ins, chosen to be obviously fictional on sight.
_FAKE_STR = "REDACTED"
_FAKE_NUMERIC_STR = "1111.11"
_FAKE_INT = 1111111
_FAKE_FLOAT = 1111.11


def _is_numeric_string(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True


def _redact_scalar(value: Any) -> Any:
    """Replace a scalar with a fake of the same type AND the same domain.

    Type alone is not enough, and a first pass that only preserved type broke twelve of
    the fixture's own tests. IBKR sends `price` and `commission` as numeric STRINGS, so
    `"7658.5"` -> `"REDACTED"` is a string for a string and still unparseable by the
    model; and `R` (the FYI read flag) is an int that Pydantic coerces to bool, so
    `0` -> `1111111` is an int for an int and no longer a boolean.

    A fixture that no longer validates is not a redacted fixture, it is a deleted one.
    """
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, str):
        return _FAKE_NUMERIC_STR if _is_numeric_string(value) else _FAKE_STR
    if isinstance(value, int):
        # 0 and 1 are flags and enum members across every IBKR payload, never an amount,
        # a quantity or an identifier. Keeping them preserves the boolean domain; they
        # cannot describe the account holder.
        return value if value in (0, 1) else _FAKE_INT
    if isinstance(value, float):
        return _FAKE_FLOAT
    return value


def _mask_accounts(value: Any) -> Any:
    """Account numbers are rewritten even inside a structural or public value — they appear
    as dict KEYS in `/pnl/partitioned` and `/iserver/accounts`, which the first redactor
    missed until it was corrected on 2026-09-16."""
    if isinstance(value, str):
        return ACCOUNT_ID_RE.sub(PLACEHOLDER_ACCOUNT, value)
    return value


def redact_owner_data(obj: Any, *, key: str | None = None) -> Any:
    """Recursively redact an owner-scoped payload, preserving keys, nesting and types."""
    if isinstance(obj, dict):
        return {_mask_accounts(k): redact_owner_data(v, key=k if isinstance(k, str) else None) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact_owner_data(v, key=key) for v in obj]
    if key is not None and key.lower() in STRUCTURAL:
        return _mask_accounts(obj)
    return _mask_accounts(_redact_scalar(obj))


def redact_capture(captured: dict[str, Any]) -> dict[str, Any]:
    """Apply the endpoint split: public reference data keeps its values, everything else
    is reduced to shape."""
    out: dict[str, Any] = {}
    for endpoint, payload in captured.items():
        if endpoint in PUBLIC_ENDPOINTS:
            out[endpoint] = _mask_only(payload)
        else:
            out[endpoint] = redact_owner_data(payload)
    return out


def _mask_only(obj: Any) -> Any:
    """Public endpoints: rewrite account numbers if any appear, change nothing else."""
    if isinstance(obj, dict):
        return {_mask_accounts(k): _mask_only(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_mask_only(v) for v in obj]
    return _mask_accounts(obj)
