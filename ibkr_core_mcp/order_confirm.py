"""Gate 2 of the order-write security model: visual order confirmation.

After Touch ID (Gate 1, `human_auth.py`) succeeds, the user is shown a modal dialog
carrying the full order details and a live-order disclaimer, and must click to
confirm. The Enter key deliberately does not confirm — the gate exists to defeat
reflexive acceptance, so it requires a pointed, explicit action. Any cancellation
or timeout raises `HumanAuthError` and the IBKR endpoint is never contacted.

Three backends, but never three in one sequence — the platform picks the pair. On macOS:
an AppKit `NSAlert` run in a subprocess (colour-coded by side; see `_order_dialog.py` for
why it must be a subprocess), falling back to an AppleScript `display dialog` if that
subprocess fails. Everywhere else: a tkinter modal, which macOS never reaches. A host with
no backend available fails closed rather than proceeding unconfirmed. This paragraph read
"tried in order: ... AppKit, a tkinter modal, and an AppleScript fallback" until 2026-09-17,
an order that occurs on no platform (audit finding SEC-R5); `_show_confirm_dialog`'s own
docstring had it right all along.
"""

from __future__ import annotations

import contextlib
import html
import json as _json
import math
import re
import subprocess
import sys
from decimal import Decimal, DecimalException, InvalidOperation
from pathlib import Path
from typing import Any

try:
    import tkinter as tk
except ImportError:  # Python without Tk support (CI, headless, Python 3.14 Homebrew)
    tk = None  # type: ignore[assignment]
from ibkr_core_mcp.exceptions import HumanAuthError

_DIALOG_TIMEOUT_S = 60  # auto-cancels if unattended


def _quantity_text(qty: Any) -> str:
    """The order's quantity as a human writes it.

    IBKR's order status reports `size` as a string — `'1.0'` for one contract — so the
    cancel dialog showed `Quantity: 1.0` while the modify dialog, fed from the proposal,
    showed `1` (claudia_ui gap #42, read live 2026-09-10). Anything unparseable is shown
    unchanged rather than guessed at.

    Args:
        qty: The quantity from a proposal or from an IBKR status row.

    Returns:
        The quantity as text, without a trailing `.0`.
    """
    try:
        value = float(qty)
    except (TypeError, ValueError):
        return str(qty)
    return str(int(value)) if value.is_integer() else str(value)


def _contract_size_suffix(order: dict[str, Any], multiplier: float | None) -> str:
    """` (×50 per contract)` for a future with a known multiplier, ` (multiplier unknown)`
    when the caller could not learn it, and nothing for a stock — a stock's quantity is
    plain shares (claudia_ui gap #45, 2026-09-11)."""
    if multiplier is not None:
        return f" (×{multiplier:g} per contract)"
    if order.get("_multiplier_unknown"):
        return " (multiplier unknown)"
    return ""


def _asset_class(sec_type: Any) -> str:
    """The asset class out of IBKR's `secType`, which carries the conid in front of it.

    IBKR's place-order body spells this field `"265598@STK"` (their Python example) and
    `"265598:STK"` (their JSON example) — the conid, a separator, then the class. The
    `api-reference` field table calls it "IB asset class identifier" and shows no format,
    so those two examples are the only statement IBKR makes about it.

    Comparing the whole string to `FUT`/`FOP` therefore matched no documented body at all:
    an ES order carrying `secType: "649180671:FUT"` was not recognised as a future and
    printed `Total (est.): 7,300.00` for a contract standing for 365,000 (review
    2026-09-21). A bare `"FUT"` is still accepted — a caller may send one, and every
    spelling names one asset class.

    Source: https://www.interactivebrokers.com/docs/web-api/v1/endpoints/orders/place-order.md
            https://www.interactivebrokers.com/docs/web-api/api-reference/trading/trading-orders/submit-new-order.md

    Args:
        sec_type: The body's `secType`, in any of IBKR's spellings.

    Returns:
        The asset class in upper case, or `""` when the field is absent or empty.
    """
    return re.split(r"[:@]", str(sec_type or "").strip().upper())[-1]


# Body keys `_order_rows` already reads into a typed row, in every spelling it accepts. A key
# here is not "missing" from the screen — it IS the screen, under a human label.
_CONSUMED_BODY_KEYS = frozenset(
    {
        "ticker", "symbol", "companyName", "side", "Side", "Action", "quantity",
        "orderType", "order_type", "price", "auxPrice", "tif", "timeInForce",
        "currency", "outsideRTH",
    }
)  # fmt: skip

# Identity, routing and compliance keys, deliberately kept OFF the screen (claudia_ui gap
# #40): the dialog is the most legible surface before an irreversible action, not a body
# dump. `manualIndicator` is CME Rule 536-B metadata and
# `test_every_order_dialog_shows_only_typed_rows_and_the_order_id_once` asserts its absence.
#
# This list is deliberately SHORT. Everything not named here and not consumed above reaches
# the screen, because the failure direction matters: an unrecognised execution attribute
# that is invisible is the defect this mechanism exists to close, and one that is merely
# ugly is not. Adding a key here is a decision to hide something from the last human screen.
_SUPPRESSED_BODY_KEYS = frozenset(
    {"conid", "conidex", "acctId", "accountId", "cOID", "parentId", "secType", "manualIndicator"}
)

# Human labels for the execution attributes IBKR documents on its order-body field table.
# A key absent from this map is still SHOWN — under its own raw name — because the point is
# that nothing execution-affecting is silent, not that this map is complete.
#
# `outsideRth` is IBKR's own spelling in the curl example on its place-order page, beside
# `outsideRTH` in the Python example on the SAME page. Only the capitalised form gets the
# typed `Outside RTH` row, so before this mechanism a caller copying IBKR's curl example
# sent a real attribute that no dialog mentioned (2026-09-22).
# Source: https://www.interactivebrokers.com/docs/web-api/api-reference/trading/trading-orders/submit-new-order.md
#         https://www.interactivebrokers.com/docs/web-api/v1/endpoints/orders/place-order.md
_EXECUTION_ATTR_LABELS = {
    "allOrNone": "All-or-None",
    "cashQty": "Cash quantity",
    "fxQty": "FX quantity",
    "isCcyConv": "Currency conversion",
    "isSingleGroup": "OCA group (isSingleGroup)",
    "listingExchange": "Listing exchange",
    "outsideRth": "Outside RTH (IBKR's lowercase spelling)",
    "strategy": "Algo strategy",
    "strategyParameters": "Algo parameters",
    "trailingAmt": "Trailing amount",
    "trailingType": "Trailing type",
    "useAdaptive": "Adaptive algo",
}


def _execution_attribute_rows(order: dict[str, Any]) -> dict[str, str]:
    """Every execution-affecting body key that no typed row above already shows.

    The class this closes: a non-`_` key survives the strip in `client.place_order`, is sent
    to IBKR verbatim, and appears on no dialog row — so the human authorises an order whose
    execution differs from the one on screen. Measured 2026-09-22: a body carrying
    `allOrNone`, `trailingAmt` and `trailingType` produced a row set byte-identical to a body
    carrying none of them.

    **Unknown fails TOWARD the screen.** A key this module has never heard of is shown under
    its own name rather than hidden, which is the opposite of an allow-list and is the whole
    point: the attributes that matter are the ones nobody thought to enumerate. Gate 1's
    scope hash already covers every one of these keys (`client._order_write_scope`), so
    before this the fingerprint bound values the screen never showed.

    A `None` value is skipped, not rendered: `{"limit_price": None}` is an absent field
    spelled out, and the same rule the `outsideRTH` row applies — a present None is not a
    value.

    Args:
        order: The IBKR-shaped body, plus the display-only `_`-prefixed keys callers add.

    Returns:
        `{label: value}` for each such key, sorted by key so one order renders one way.
    """
    rows: dict[str, str] = {}
    for key in sorted(order, key=str):
        name = str(key)
        if name.startswith("_") or name in _CONSUMED_BODY_KEYS or name in _SUPPRESSED_BODY_KEYS:
            continue
        value = order[key]
        if value is None:  # a present None is not a value — see the docstring
            continue
        rows[_EXECUTION_ATTR_LABELS.get(name, name)] = str(_yes_no(value))
    return rows


def _order_rows(order: dict[str, Any], account_id: str) -> dict[str, str]:
    """The typed rows every Gate 2 dialog shows for an order (place, modify, cancel).

    `order` is an IBKR-shaped body plus the display-only `_`-prefixed keys the callers add
    (`_companyName`, `_multiplier`, `_multiplier_unknown`, `_currency`). Raw body keys never
    reach the screen: until 2026-09-10 the modify and cancel dialogs forwarded their dict
    verbatim — `orderType`, `manualIndicator: True`, `limit_price: None`, a reason blob, the
    order id twice — so the last human-readable surface before an irreversible action was
    the least legible one (claudia_ui gap #40).
    """
    # `or`, not `.get(key, default)`: the default applies only when the key is ABSENT, so a
    # body carrying `ticker: None` rendered `Symbol: None` — and with a company name,
    # `Symbol: None — APPLE INC` (measured 2026-09-22). The same rule the `Outside RTH` row
    # states: a present None is not a value. The conid is the fallback rather than a bare
    # `UNKNOWN` because it is a checkable identifier the human can look up, and the dialog
    # is holding it either way; resolving it to a name would be a network call at the gate,
    # which SEC-02 forbids.
    symbol = order.get("ticker") or order.get("symbol")
    if not symbol:
        conid = order.get("conid") or order.get("conidex")
        symbol = f"UNKNOWN (conid {conid})" if conid else "UNKNOWN"
    company_name = order.get("_companyName") or order.get("companyName") or ""
    symbol_str = f"{symbol} — {company_name}" if company_name else str(symbol)
    # IBKR-shaped bodies say `side`; a live-order dict from another caller may say
    # `Side`; a pre-built row set says `Action`. All three feed the banner colour.
    side = order.get("side", order.get("Side", order.get("Action", "?")))
    qty = order.get("quantity", "?")
    # No default of "MARKET": that filled in a field the caller never sent, and since the
    # 2026-09-14 price change it decides whether a missing price is normal or a gap — so a
    # body IBKR would reject for having no `orderType` rendered as a complete market order
    # (review 2026-09-14). An absent type is shown as absent, like every other unknown here.
    order_type = order.get("orderType", order.get("order_type")) or None
    order_type_str = str(order_type) if order_type is not None else "— (not sent)"
    price = order.get("price")
    aux_price = order.get("auxPrice")
    tif = order.get("tif", order.get("timeInForce", "DAY"))
    multiplier = order.get("_multiplier")
    # Currency is displayed only when the caller established one, and always as an ISO
    # code. Until 2026-08-13 this rendered f"${price}" and a hardcoded "USD": "$" is
    # shared by USD/MXN/CAD/AUD/HKD/SGD, and this account holds EUR-denominated equities,
    # so the last surface before an irreversible action asserted a currency nothing had
    # established. A wrong-currency price is dangerous precisely because it reads as
    # ordinary. No currency in the order means no currency shown — never a guess.
    currency = str(order.get("_currency") or order.get("currency") or "").strip().upper()
    ccy = f" {currency}" if currency else ""
    # The same formatter as the Changes row, so one dialog cannot show one number two
    # ways: live 2026-09-10 it read `Price: 6945.0 USD` four lines above
    # `limit price 6,995.00 → 6,945.00` (claudia_ui gap #46).
    # A futures price is quoted in the contract's own units — index points for ES — not
    # in currency; the money figure is the multiplied total. `Price: 7,900.00 USD` was wrong
    # (user, 2026-09-11). No unit is printed rather than a guessed one: no IB field names
    # the quotation unit, and "points" would be wrong for crude or a bond future.
    # Four independent signals, because relying on the display keys alone made this
    # blind to a futures order whose caller simply did not set them — reproduced live
    # 2026-09-21, printing `Total (est.): 7,300.00` for one ES contract worth 365,000.
    # `manualIndicator` is CME Rule 536-B and is FUT/FOP-only; `secType` is IBKR's own
    # field, read through `_asset_class` because IBKR spells it `"649180671:FUT"` rather
    # than `"FUT"` — matching the whole string recognised no documented body at all
    # (review 2026-09-21). Either establishes the instrument class without the caller
    # volunteering a display key. A body carrying NONE of the four is still unrecognised —
    # narrowed, not closed, and said so rather than implied.
    is_future = (
        multiplier is not None
        or bool(order.get("_multiplier_unknown"))
        or _asset_class(order.get("secType")) in ("FUT", "FOP")
        or bool(order.get("manualIndicator"))
    )
    price_ccy = "" if is_future else ccy
    # "MARKET" belongs to the one order type that legitimately sends no price. Applied to
    # every type, it described an order the body did not carry: a LMT with a null price read
    # `Price: MARKET` four rows under `Order Type: LMT` (claudia_ui audit 2026-09-13, A-2).
    # The dialog names the gap instead of guessing, the same rule as the unknown multiplier.
    #
    # It names the gap and nothing else. The first version of this fix read `a {type} order
    # needs one`, which is untrue of every type that legitimately carries no price — MIDPRICE
    # above all, whose `limit_price` this package documents as an optional cap, and which
    # `_preview_order` builds without one. Asserting a requirement about the order is the
    # same defect A-2 fixed, pointed the other way (review 2026-09-14).
    is_market = str(order_type).strip().upper() in ("MKT", "MARKET") if order_type else False
    if price is not None:
        price_str = f"{change_value_text('limit_price', price)}{price_ccy}"
    elif is_market:
        price_str = "MARKET"
    else:
        price_str = "— (no price sent)"
    try:
        if order.get("_multiplier_unknown") or (is_future and multiplier is None):
            # A futures order whose multiplier the caller could not learn. price × qty here
            # is not an estimate, it is wrong by the multiplier — live 2026-09-04 it printed
            # 7,735.00 for one ES contract standing for 386,750 USD. Say so instead.
            total_str = "— (contract multiplier unknown; not price × quantity)"
        elif price is not None and multiplier is not None:
            # Futures: notional = price × qty × multiplier
            notional = float(price) * float(qty) * float(multiplier)
            total_str = f"{notional:,.2f}{ccy} (×{multiplier:g} multiplier)"
        elif price is not None:
            total_str = f"{float(price) * float(qty):,.2f}{ccy}"
        elif is_market:
            total_str = "Market"
        else:
            total_str = "—"
    except (TypeError, ValueError):
        total_str = "—"
    rows = {
        "Account": account_id,
        "Action": side,
        "Symbol": symbol_str,
        # Size sits with size (claudia_ui gap #45): the multiplier belongs beside the
        # quantity it scales, not on the Symbol line where it read as part of the name.
        "Quantity": _quantity_text(qty) + _contract_size_suffix(order, multiplier),
        "Order Type": order_type_str,
        "Price": price_str,
    }
    if aux_price is not None:
        # A stop-limit's trigger lives in auxPrice; no dialog showed it before 2026-09-10.
        rows["Stop"] = f"{change_value_text('stop_price', aux_price)}{price_ccy}"
    rows["TIF"] = tif
    # The outside-RTH attribute decides WHEN a stop on a US future can trigger (IBKR
    # simulates those stops and fires them only in RTH unless it is set), so it belongs on
    # the last screen before the send. Shown only when the caller sent it — an absent
    # attribute means IBKR's default applies, and the dialog claims nothing it was not
    # given (2026-09-04).
    if isinstance(order.get("outsideRTH"), bool):  # a present None is not a value
        rows["Outside RTH"] = "Yes" if order["outsideRTH"] else "No"
    # Everything else the caller is sending that changes how the order executes. Added
    # 2026-09-22: `outsideRTH` above was the ONLY execution attribute on the screen, and it
    # is one of many IBKR accepts — so the dialog showed one and passed the rest through in
    # silence. `Total (est.)` is set after this so a body key can never displace it.
    rows.update(_execution_attribute_rows(order))
    rows["Total (est.)"] = total_str
    return rows


# Proposal field → the replacement-body key(s) carrying its new value, first present wins.
# `stop_price` sits in `auxPrice` on a stop-limit and in `price` on a plain stop (IBKR's
# field spec; see claudia_ui order_flow's body construction).
_CHANGE_FIELD_KEYS: dict[str, tuple[str, ...]] = {
    "limit_price": ("price",),
    "stop_price": ("auxPrice", "price"),
    "quantity": ("quantity",),
    "tif": ("tif",),
    "order_type": ("orderType",),
    "outside_rth": ("outsideRTH",),
    "action": ("side",),
}


def _yes_no(value: Any) -> Any:
    """Booleans read as Yes/No on a dialog; every other value passes through."""
    return ("Yes" if value else "No") if isinstance(value, bool) else value


_PRICE_CHANGE_FIELDS = ("limit_price", "stop_price")

# Past every instrument quoted anywhere: the finest tick handled here is 6E at five
# decimals. It exists to bound a hostile or malformed *string* price, not to round.
_MAX_PRICE_DECIMALS = 12


def price_text(value: Any) -> str:
    """A price as it should be read by a human about to authorise it: exactly.

    Thousands separators and a floor of two decimals, but never a ceiling of two. The
    2026-09-14 correction (claudia_ui audit 2026-09-13, finding A-3): `f"{float(v):,.2f}"`
    silently rounded every price on the last screen before Touch ID, while the body carried
    the full value. Most of what this account trades does not tick in cents — 6E is
    0.00005, NG 0.001, ZN a 1/64 of a point — so `1.08455` read `1.08` and two prices a
    full tick apart rendered as the same string.

    `Decimal(str(value))` rather than `Decimal(value)`: `str()` of a float is its shortest
    round-tripping form, so a price parsed from the model's JSON literal renders as the
    literal rather than as the binary expansion (`0.1` stays `0.10`, not `0.1000…0055511`).

    Args:
        value: A number, or a numeric string (IBKR sends both).

    Returns:
        The value with a comma group separator and its own number of decimals, minimum two.

    Raises:
        InvalidOperation: `value` is not numeric, or is NaN/Infinity — callers fall back to
            `str(value)` rather than printing a number-shaped non-number.
    """
    number = Decimal(str(value))
    exponent = number.as_tuple().exponent
    if not isinstance(exponent, int):
        # NaN or Infinity: `as_tuple().exponent` is 'n'/'N'/'F' there, and a price row
        # reading "NaN" would be worse than one reading the raw value the caller sent.
        raise InvalidOperation(f"{value!r} is not a finite price")
    # Capped: a *string* price carries any exponent it likes, and `price_text("1e-10000000")`
    # returned a ten-million-character string that `change_value_text` would have handed to
    # the dialog as one row (review 2026-09-14). Twelve decimals is far past every quoted
    # instrument — the finest here is 6E at five — so the cap never rounds a real price.
    places = min(max(2, -exponent), _MAX_PRICE_DECIMALS)
    return f"{number:,.{places}f}"


def price_text_safe(value: Any) -> str:
    """`price_text`, but total: a value it cannot parse comes back unchanged.

    Every *display* surface needs this form. A render that raises while formatting a price
    is how a proposal card disappears, and the values that reach a display are not the
    schema-typed ones: an order-status payload can carry a string that already has a
    thousands separator, and a `number`-typed field admits NaN. The strict `price_text` is
    for a caller that must refuse to print a non-number; this is for one that must print
    *something* and must not lie about it, so the fallback is the value as it was sent.

    One definition, both repos. Before 2026-09-14 there were three implementations of this
    rule: this one, `claudia/execution_listener._plain_number` for the fill line, and a
    numbro format string for the dashboard's browser-side tables — which disagreed on
    trailing zeros and on how many decimals survive. The first two are now this function;
    the third cannot be (it runs in the browser) and is documented as its twin.

    Args:
        value: A price, from a proposal or from any IBKR payload.

    Returns:
        The price exactly, or `str(value)` when it is not a finite number.
    """
    try:
        return price_text(value)
    except (TypeError, ValueError, DecimalException):
        return str(value)


def change_value_text(field: str, value: Any) -> str:
    """One rendering of a changed field's value, shared by every surface that shows a diff.

    A diff exists to be compared at a glance, so the two sides of the arrow have to be
    formatted alike. Until 2026-09-10 they were not: on order 1793215935 one stop-price
    change rendered as `stop_price: 7900.0 -> 7950` in the chat card and `stop price
    7900.0 -> 7950.0` on Gate 2, because each surface printed whatever type the value
    happened to arrive as — a float from the proposal's `previous_value`, an int from the
    model's replacement. Public so claudia_ui's approval text uses this definition rather
    than a third copy, the same reason `reply_message_text` is public.

    Prices go through `price_text`: thousands separators and **at least** two decimals, more
    when the instrument ticks finer than a cent; a whole quantity loses its `.0`; booleans
    read Yes/No; None renders `?` rather than the string "None", matching `_format_changes`'s
    rule that an unknown is never a guess.

    Args:
        field: The changed field's name, from `propose_modify`'s `changes[].field` enum.
        value: That field's value, before or after.

    Returns:
        The value as it should appear on a dialog or in the approval text.
    """
    if value is None:
        return "?"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if field in _PRICE_CHANGE_FIELDS:
        return price_text_safe(value)
    if field == "quantity":
        return _quantity_text(value)
    return str(value)


def _format_changes(order: dict[str, Any]) -> str:
    """Render `order["_changes"]` as one `<field> <previous> → <new>` line per entry, "" if none.

    The new value is read from the replacement body itself, so the row can never disagree
    with what is about to be sent; an unknown field renders `?` rather than a guess.
    """
    lines: list[str] = []
    for change in order.get("_changes") or []:
        if not isinstance(change, dict) or not change.get("field"):
            continue
        field = str(change["field"])
        new: Any = "?"
        for key in _CHANGE_FIELD_KEYS.get(field, ()):
            if order.get(key) is not None:
                new = order[key]
                break
        previous = change_value_text(field, change.get("previous_value"))
        lines.append(f"{field.replace('_', ' ')} {previous} → {change_value_text(field, new)}")
    return "\n".join(lines)


def confirm_order_dialog(order: dict[str, Any], account_id: str) -> None:
    """Gate 2 for place_order. Raises HumanAuthError if user does not confirm.

    Shows an AppKit colored dialog (green=BUY, red=SELL) with full order details,
    a DO NOT SEND button, and a SEND TO IBKR button. Auto-cancels after 60 seconds.
    Falls back to osascript if the AppKit subprocess fails; tkinter on non-macOS.
    Futures notional uses the _multiplier display field: price × qty × multiplier. When the
    caller sets _multiplier_unknown instead, no number is printed at all (2026-09-04).

    Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/orders/place-order.md
    """
    _show_confirm_dialog(
        title="⚠  LIVE ORDER CONFIRMATION",
        details=_order_rows(order, account_id),
        disclaimer=(
            "This is a LIVE order. It will be sent to Interactive Brokers "
            "and may result in real financial transactions that cannot be undone."
        ),
        confirm_label="SEND TO IBKR",
        abandon_label="DO NOT SEND",
    )


# Display-only keys that describe the CONTRACT rather than the ticket. A bracket's child is
# the same contract as its parent by construction (the child's conid, sec_type and quantity
# are derived, not asked for), so a child carrying none of its own inherits these.
#
# Measured 2026-09-21, rendering one ES bracket both ways through `_order_rows`: without
# inheritance the child's Symbol row drops to `ES` where the parent reads
# `ES — ESU6 · SEP26`, and its Quantity to `1` where the parent reads `1 (×50 per
# contract)`. One instrument, one dialog, two descriptions — and the leg missing its month
# and multiplier is the one the human has never seen before. (The price rows do NOT diverge:
# a bare child carries no `_currency` either, so both render `7,7xx.00`. An earlier version
# of this comment claimed a `USD` suffix on the child's price; that was wrong, and the
# measurement above is what replaced it.)
#
# Inheritance fills gaps only — a key the child carries always wins — and it runs only AFTER
# the conid check below, because inheriting a contract label onto a child that is NOT that
# contract would hide the mismatch behind the parent's own name.
_CONTRACT_DISPLAY_KEYS = ("_companyName", "_multiplier", "_multiplier_unknown", "_currency")

# The other two signals `_order_rows` uses to decide an instrument's class. Unlike the four
# above these are REAL IBKR body fields, not `_`-prefixed display keys, and they are
# inherited for exactly the same reason: a bracket's legs are one instrument, so a leg that
# does not inherit the class is described differently from its own parent.
#
# Added 2026-09-21 with the signals themselves. Without them one ES bracket rendered
# `Parent — Price 7,300.00` beside `Profit taker — Price 7,400.00 USD` — index points
# labelled as dollars on the leg the human has never seen before, which is the divergence
# the list above exists to prevent and which the comment above claimed was measured not to
# happen. That measurement was taken with `_multiplier` set, before these two doors existed.
#
# They are merged into a LOCAL copy used only to build display rows. Nothing here is sent:
# `place_bracket_and_confirm` posts the tickets `_bracket_tickets` built from the caller's
# own dicts, and `test_the_dialogs_inherited_keys_never_reach_the_wire` holds that.
#
# `ticker` joined them 2026-09-22, for the same reason and after the same kind of
# measurement. THIS PACKAGE'S OWN documented bracket example
# (`docs/order-management-examples.md`) puts `"ticker": "AAPL"` on the parent and none on
# either child — the children are the same contract by construction, so a caller has no
# reason to repeat it. Rendered through the real AppKit Gate 2 dialog, that example printed
# `Parent — Symbol: AAPL` above `Profit taker — Symbol: UNKNOWN` and `Stop loss — Symbol:
# UNKNOWN`: the two legs the human has never seen before were the two with no name on them,
# on the last screen before an irreversible write. A bracket child IS its parent's contract
# — `_bracket_tickets` and this function both REFUSE a child whose conid differs — so
# inheriting the label asserts nothing that was not already enforced.
_CONTRACT_CLASS_KEYS = ("secType", "manualIndicator", "ticker")

_HELD_UNTIL_PARENT_FILLS = "held by IBKR until the parent fills"


def confirm_bracket_dialog(parent: dict[str, Any], children: list[dict[str, Any]], account_id: str) -> None:
    """Gate 2 for a bracket: ONE dialog carrying the parent and every child.

    One dialog, not one per leg, is the whole point (design decision D4): two dialogs would
    permit the parent to be sent with the child declined, which is precisely the state a
    bracket exists to prevent — a resting position with no exit. The human approves the pair
    as one instruction or sends nothing.

    Every value on screen is formatted by `_order_rows`, the same builder the place, modify
    and cancel dialogs use, so the currency rule (ISO code or nothing), the price precision
    rule, the futures-notional rule and the missing-price wording cannot drift between a
    single order and a bracket leg. This function composes and labels; it formats nothing.

    The child is shown as **held**, never as working. `PreSubmitted` is a working state for a
    single order and a held one for a bracket child, and the difference is the only thing the
    human needs to understand about the second leg.

    Exactly one notional row is shown and it names whose it is. A bracket's legs are opposite,
    so a row called `Total` would be read as their sum; the child's notional is left off
    rather than printed beside the parent's and mentally added (review 2026-09-08 item 8).

    Args:
        parent: The parent ticket in IBKR body shape, carrying `cOID`, plus display-only keys.
        children: One or more child tickets, each `parentId`-linked to the parent's `cOID`.
        account_id: The account the bracket will be sent to.

    Raises:
        HumanAuthError: The user did not confirm, or the pair is not a bracket — no child, a
            parent with no side, a parent with no `cOID`, a child on the parent's own side, a
            child carrying no `parentId`, a child linked to some other order, a child carrying
            its own `cOID`, a child naming a different contract from the parent, or a child
            larger than the parent (H1) including one whose quantity cannot be compared with
            the parent's. Each is a refusal, never a correction: order parameters are
            immutable, and a "bracket" that fails these is a different instruction from the
            one the human was shown.

            Every one of these is also refused by `client._bracket_tickets`, before Gate 1.
            The two lists are kept identical on purpose: the only reason to repeat a rule
            here is that this function is public API callable without that helper, and a
            rule missing from one of the two is enforced on neither path when the other is
            taken. Three of them had an escape clause here and not there until 2026-09-21.

    Sources: https://ibkrcampus.com/docs/web-api/v1/endpoints/orders/bracket-orders-oca-groups.md,
        https://ibkrcampus.com/docs/web-api/v1/endpoints/order-monitoring/order-status-value.md
    """
    if not children:
        raise HumanAuthError("Bracket confirmation refused: no child order in the bracket")
    parent_side = str(parent.get("side", "")).strip().upper()
    if not parent_side:
        raise HumanAuthError("Bracket confirmation refused: the parent carries no side")
    # A parent with no cOID makes the link check below unevaluable, and until 2026-09-21
    # that silently DISABLED it (`if parent_coid and ...`): a child whose `parentId` named
    # someone else's resting order rendered as a normal bracket on the last screen before
    # the write. Attaching to another order is worse than being standalone, not better.
    # `_bracket_tickets` has required this since it shipped; this is the same rule on the
    # other reachable path.
    parent_coid = str(parent.get("cOID") or "").strip()
    if not parent_coid:
        raise HumanAuthError(
            "Bracket confirmation refused: the parent carries no cOID, so a child's parentId "
            "cannot be checked against it"
        )
    inherited = {key: parent[key] for key in (*_CONTRACT_DISPLAY_KEYS, *_CONTRACT_CLASS_KEYS) if key in parent}

    parent_rows = _order_rows(parent, account_id)
    details: dict[str, Any] = {
        "Account": parent_rows.pop("Account"),
        "Action": parent_rows.pop("Action"),  # the PARENT's side — it decides the banner colour
    }
    notional = parent_rows.pop("Total (est.)", None)
    for key, value in parent_rows.items():
        details[f"Parent — {key}"] = value
    if notional is not None:
        details["Parent notional (est.)"] = notional

    seen: dict[str, int] = {}
    for child in children:
        child_side = str(child.get("side", "")).strip().upper()
        if not child_side or child_side == parent_side:
            raise HumanAuthError("Bracket confirmation refused: a child must be the opposite side of the parent")
        link = child.get("parentId")
        if link is None or not str(link).strip():
            raise HumanAuthError(
                "Bracket confirmation refused: a child carries no parentId, so it would reach "
                "IBKR as a standalone order and be live immediately"
            )
        # Compared RAW, exactly as `_bracket_tickets` does, and deliberately not through
        # `str(...).strip()`. IBKR links a child to its parent by matching this value to the
        # parent's `cOID` literally, so a difference that survives to the wire is a child
        # that will not attach. Normalising here approved two pairs the builder refused —
        # `parentId=" C-1 "` against `cOID="C-1"`, and a str `"1"` against an int `1` — on
        # the one path this dialog exists to cover, the standalone call (parity harness,
        # 2026-09-21). Gate 2 must not be more permissive than the check before Gate 1.
        if link != parent.get("cOID"):
            raise HumanAuthError("Bracket confirmation refused: a child's parentId does not name this parent")
        # IBKR: a cOID "should not be set for the child of a bracket order". `_bracket_tickets`
        # refuses one; this did not, so the rule held on one of two reachable paths.
        # Source: https://ibkrcampus.com/docs/web-api/api-reference/trading/trading-orders/submit-new-order.md
        if child.get("cOID"):
            raise HumanAuthError(
                "Bracket confirmation refused: a child carries its own cOID, which IBKR forbids on a bracket child"
            )
        # A child on the wrong instrument, refused here as well as in `client._bracket_tickets`,
        # which checks it with the other structural rules so a place is refused before Touch ID.
        # This copy is defence in depth and is not redundant: this dialog is public API and can
        # be called without that method, and the check must run BEFORE the display keys are
        # inherited a few lines below — inheriting the parent's `_companyName` onto a mismatched
        # child would print the parent's own contract name on the child's rows and hide the
        # mismatch on the last screen before the send.
        #
        # Neither copy can be dropped in favour of the preview. Measured live 2026-09-20: a
        # child on a DIFFERENT instrument returns a whatif response byte-identical to a valid
        # one, because the preview reads the first ticket and discards the rest (claudia_ui
        # gap #36, Phase 0). A mismatched bracket previews clean.
        #
        # A child carrying no conid is normal — it is derived from the parent — so only a
        # STATED mismatch is refused, never an absence.
        parent_conid, child_conid = parent.get("conid"), child.get("conid")
        if parent_conid is not None and child_conid is not None and str(child_conid) != str(parent_conid):
            raise HumanAuthError("Bracket confirmation refused: a child is on a different contract from the parent")
        # H1 — a child is never larger than the parent (user hard rule, 2026-09-21). Repeated
        # here for the same reason as the link and contract rules above: this function is public
        # API and callable without `_bracket_tickets`, and it is the LAST screen before an
        # irreversible write. Only a stated violation is refused; a child carrying no quantity
        # is derived from the parent and is normal.
        #
        # The parent's quantity is NOT part of that "only a stated violation" allowance. It
        # was until 2026-09-21 — `and parent.get("quantity") is not None` — which meant a
        # parent stating no quantity turned H1 off entirely rather than making the pair
        # unverifiable, and a child of 5 or of "abc" sailed through. `_bracket_tickets`
        # states the principle this broke: a quantity that cannot be compared is refused
        # rather than assumed compliant, so the rule cannot be walked through by a
        # malformed value. `float(None)` raises TypeError, which is the refusal.
        child_qty, parent_qty = child.get("quantity"), parent.get("quantity")
        if child_qty is not None:
            try:
                if parent_qty is None:
                    raise ValueError("the parent states no quantity to compare against")
                child_size, parent_size = float(child_qty), float(parent_qty)
                # NaN defeats every comparison — `nan > 1.0` is False — so it is the one
                # quantity that literally cannot be compared, and it walked through H1 here
                # AND in `_bracket_tickets` until 2026-09-21. Both said uncomparable values
                # are refused; neither did it, which is why a parity check between the two
                # would have agreed and proved nothing.
                if not (math.isfinite(child_size) and math.isfinite(parent_size)):
                    raise ValueError("a leg's quantity is not a finite number")
                oversized = child_size > parent_size
            except (TypeError, ValueError):
                raise HumanAuthError(
                    "Bracket confirmation refused: a leg's quantity is missing or not a number, so the "
                    "child cannot be shown to be no larger than the parent"
                ) from None
            if oversized:
                raise HumanAuthError("Bracket confirmation refused: a child is larger than the parent")
        # LMT reads as the profit taker; anything else is the protective leg. The label is
        # cosmetic — the link and the side are what were just checked.
        kind = "Profit taker" if str(child.get("orderType") or "").strip().upper() in ("LMT", "LIMIT") else "Stop loss"
        seen[kind] = seen.get(kind, 0) + 1
        if seen[kind] > 1:
            # Two legs of one kind (a scale-out) must not collapse onto one set of rows: the
            # rows are keyed by this label, so the second would overwrite the first and the
            # human would authorise two live children having been shown one.
            kind = f"{kind} {seen[kind]}"
        rows = _order_rows({**inherited, **child}, account_id)
        rows.pop("Account", None)
        rows.pop("Total (est.)", None)
        details[kind] = _HELD_UNTIL_PARENT_FILLS
        for key, value in rows.items():
            details[f"{kind} — {key}"] = value

    # No `action=`: a bracket IS a placement, so the banner stays the parent's side and colour
    # — the exposure being opened — exactly as the place dialog's does. `_banner` special-cases
    # only CANCEL and MODIFY, the two acts whose verb must beat the side. The word BRACKET is
    # carried by the title, and each leg is named on its own rows.
    _show_confirm_dialog(
        title="⚠  LIVE BRACKET ORDER CONFIRMATION",
        details=details,
        disclaimer=(
            "This is a LIVE bracket. The parent order is sent to Interactive Brokers now; "
            "each child becomes live the moment the parent fills. Real financial transactions "
            "may result that cannot be undone."
        ),
        confirm_label="SEND TO IBKR",
        abandon_label="DO NOT SEND",
    )


def confirm_modify_dialog(order_id: str, order: dict[str, Any], account_id: str) -> None:
    """Gate 2 for modify_order. Raises HumanAuthError if the user does not confirm.

    `order` is the fresh replacement body the caller dispatches plus display-only keys:
    `_changes` (the proposal's `{"field", "previous_value"}` list) renders one `Changes`
    line per field as `<field> <previous> → <new>`, and `_current_description` (IBKR's own
    `order_description_with_contract` from a status read) renders as `Currently at IBKR`.
    Before 2026-09-10 the dict was forwarded verbatim — `orderType`, `manualIndicator:
    True`, `outsideRTH: True` — with no month, notional, currency or before/after
    (claudia_ui gap #40). The side is read as `side`, so the banner colour is right for
    SELL modifies (before 2026-09 every SELL modify rendered green).

    Source: https://ibkrcampus.com/docs/web-api/v1/endpoints/orders/modify-order.md
    """
    details = _order_rows(order, account_id)
    details["Order ID"] = order_id
    changes = _format_changes(order)
    if changes:
        details["Changes"] = changes
    current = order.get("_current_description")
    if current:
        details["Currently at IBKR"] = str(current)
    _show_confirm_dialog(
        title="⚠  MODIFY ORDER CONFIRMATION",
        details=details,
        disclaimer="This will MODIFY a live order at Interactive Brokers.",
        confirm_label="MODIFY ORDER",
        abandon_label="LEAVE UNCHANGED",
        action="MODIFY",
    )


def confirm_cancel_dialog(order_id: str, account_id: str, order: dict[str, Any] | None = None) -> None:
    """Gate 2 for cancel_order.

    `order` is optional display-only detail in the IBKR body shape (`side`, `quantity`,
    `orderType`, `price`/`auxPrice`, `tif`, `outsideRTH`, `ticker`, plus the `_`-prefixed
    display keys); `_current_description` — IBKR's `order_description_with_contract` —
    renders as `Currently at IBKR`. None keeps the order-id-only dialog for a caller
    without detail. Found missing live 2026-07-10 (user-flagged hard requirement); rendered
    as the raw proposal dict until 2026-09-10 — `order_id` and `Order ID` both,
    `limit_price: None`, the reason blob (claudia_ui gaps #27(b–e), #40).
    """
    if order:
        details = _order_rows(order, account_id)
        details["Order ID"] = order_id
        current = order.get("_current_description")
        if current:
            details["Currently at IBKR"] = str(current)
    else:
        # An order id is not human-checkable. With several orders resting, nothing here
        # distinguishes a disposable test order from the stop protecting a real position,
        # and a cancel cannot be undone. The id-only shape is not the defect — being
        # SILENT about it is (user-flagged 2026-09-21, after a caller reproduced it live).
        details = {
            "Order ID": order_id,
            "Account": account_id,
            "Order detail": "NOT AVAILABLE — symbol, side, quantity and price could not be read",
        }
    _show_confirm_dialog(
        title="⚠  CANCEL ORDER CONFIRMATION",
        details=details,
        disclaimer="This will CANCEL a live order at Interactive Brokers.",
        confirm_label="CANCEL ORDER",
        abandon_label="KEEP ORDER",
        action="CANCEL",
    )


def confirm_reply_dialog(
    reply_id: str,
    message: str = "",
    options: list[str] | None = None,
    *,
    order_label: str | None = None,
) -> None:
    """Gate 2 for reply_order. Shows the ACTUAL IBKR warning text, not just the reply_id.

    `message` defaults to "" so the standalone reply_order() call site (which only ever
    had a bare reply_id to work with) keeps showing a blank message exactly as before —
    that call site is unchanged by this task. place_order_and_confirm() /
    modify_order_and_confirm() are the callers that pass a real `message`.

    `options` (IBKR's messageOptions, e.g. varying button wording like "Yes"/"No" vs.
    "Decline"/"Accept and Continue") is accepted for signature completeness only — it is
    NOT surfaced as actual dialog button labels. The dialog keeps this package's own
    consistent confirm_label / abandon_label wording.

    HTML tags are stripped and entities unescaped (`reply_message_text`) before display
    since the AppKit/tkinter/osascript dialogs are plain text and IBKR reply messages have
    been observed containing tags (e.g. "<h4>...</h4>", verified live 2026-07-06) and
    entities (`&nbsp;` between every sentence of the Stop Variant disclosure, 2026-09-10).

    `order_label` (2026-09-11): with Gate 1 once per order write, this dialog is the only
    gate on a reply, so its title names the order — `⚠  CONFIRM ORDER REPLY — BUY 1 ES`.
    The standalone `reply_order()` path passes none and keeps the bare title.
    """
    # `options` is intentionally unused below — reserved for a future caller that wants
    # to log/inspect IBKR's messageOptions; never rendered as dialog button labels (see
    # docstring above).
    details: dict[str, Any] = {"Reply ID": reply_id}
    if message:
        details["Message"] = reply_message_text(message)
    title = "⚠  CONFIRM ORDER REPLY" + (f" — {order_label}" if order_label else "")
    _show_confirm_dialog(
        title=title,
        details=details,
        disclaimer="This will CONFIRM a pending order at Interactive Brokers.",
        confirm_label="CONFIRM REPLY",
        abandon_label="DO NOT REPLY",
    )


# Block-level elements end a line in HTML, so deleting them outright fuses the text on
# either side. Measured live 2026-09-10: IBKR sent "…on the market price. <h4>Confirm
# Mandatory Cap Price</h4>To avoid trading…" — correct HTML — and the dialog read
# "Cap PriceTo avoid" (claudia_ui gap #39, whose recorded cause blamed IBKR's own text).
_BLOCK_TAG = re.compile(
    r"</?(?:br|p|div|h[1-6]|li|ul|ol|tr|table|blockquote|hr)(?:\s[^<>]*)?/?>",
    re.IGNORECASE,
)


def _strip_html(text: str) -> str:
    """Strip HTML tags from IBKR reply message text for display in plain-text dialogs.

    Block-level tags become a newline; every other tag is removed. Only well-formed tags
    match (e.g. "<h4>", "</h4>", "<br/>", '<span class="x">') — NOT a bare "<" or ">" that
    isn't part of a tag. A naive r"<[^>]+>" would delete everything between an unrelated
    "<" (e.g. a message reading "price must be < 100.50") and the next unrelated ">"
    anywhere later in the string, corrupting real content.

    Leading and trailing newlines are trimmed — a message ending in "<br/>" would otherwise
    gain a blank last line — but only newlines: IBKR indents with `&nbsp;`, which
    `str.strip()` would eat.
    """
    text = _BLOCK_TAG.sub("\n", text)
    text = re.sub(r"</?[a-zA-Z][a-zA-Z0-9]*(?:\s[^<>]*)?/?>", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip("\n")


def reply_message_text(message: str) -> str:
    """IBKR reply text as a human should read it: tags stripped, then entities unescaped.

    The order matters: unescaping first would turn a literal `&lt;b&gt;` into `<b>`, which
    the tag stripper would then delete. Live 2026-09-10 the Stop Variant disclosure reached
    the dialog with `&nbsp;&nbsp;&nbsp;` between every sentence (claudia_ui gap #39). Used by
    the reply dialog and by the reply record `IBKRClient` hands back to callers.
    """
    return html.unescape(_strip_html(message))


_SIDE_KEYS = ("Action", "side", "Side")


def _extract_side(details: dict[str, Any]) -> str | None:
    """Return the order side from whichever key carries it, or None if none does.

    Three sources disagree on the key. Since 2026-09-10 all three order dialogs build
    their rows through `_order_rows`, which folds `side`/`Side` into `Action`; a caller
    handing a raw dict straight to this renderer may still say `side` or `Side`; and
    `confirm_reply_dialog` has no side at all. Reading only
    `Action` — as this did until 2026-08-07 — meant three of the four Gate 2 dialogs
    reached `_order_dialog` with no side, where the default was a confident green
    "BUY ORDER" banner over what could be a live sell.

    Returning None rather than a guess is the point. The banner is the pre-attentive
    cue, read before any text, so an unknown side must render as unknown; the caller
    must not be able to mistake "nobody told us" for "it is a buy".

    Args:
        details: The display dict handed to the dialog.

    Returns:
        The uppercased side, or None when no key carries one (and when a key is
        present but empty, which is equally uninformative).
    """
    for key in _SIDE_KEYS:
        raw = details.get(key)
        if raw is not None and str(raw).strip():
            return str(raw).upper()
    return None


def _show_confirm_dialog(
    title: str,
    details: dict[str, Any],
    disclaimer: str,
    confirm_label: str,
    abandon_label: str,
    action: str | None = None,
) -> None:
    """Render a modal confirmation dialog. Raises HumanAuthError if user cancels or closes.

    macOS primary path: AppKit colored dialog (green BUY, red SELL, amber when the side
    is unknown) via subprocess.
    macOS fallback: osascript plain dialog if AppKit subprocess fails.
    Non-macOS: tkinter fallback.

    `abandon_label` is a required parameter, not a default, because this renderer is shared
    by all four Gate 2 dialogs and it used to hardcode "CANCEL" for the abandon button.
    On the *cancel* dialog that produced "CANCEL ORDER" (perform it) beside "CANCEL"
    (abandon it): two adjacent buttons, same first word, opposite meanings, on a live
    order. Found by looking at the rendered dialog live on 2026-08-13 (B3) — no amount of
    code reading had caught it. Making the caller state the label is what stops a future
    dialog from silently inheriting a word that contradicts its own confirm button;
    `test_no_gate2_dialog_offers_two_buttons_sharing_a_first_word` enforces it over the class.
    """
    if sys.platform == "darwin":
        side = _extract_side(details)
        try:
            _show_appkit_dialog(title, details, disclaimer, confirm_label, side, abandon_label, action)
            return
        except HumanAuthError:
            raise  # user decision — do not fall back
        except Exception:  # noqa: S110 - AppKit subprocess failed; fall back to plain osascript
            pass
        _show_osascript_dialog(title, details, disclaimer, confirm_label, abandon_label)
    elif tk is not None:
        _show_tkinter_dialog(title, details, disclaimer, confirm_label, abandon_label)
    else:
        raise HumanAuthError("No GUI dialog available: not on macOS and tkinter is not installed.")


def _show_appkit_dialog(
    title: str,
    details: dict[str, Any],
    disclaimer: str,
    confirm_label: str,
    side: str | None,
    abandon_label: str,
    action: str | None = None,
) -> None:
    """Colored macOS confirmation dialog via AppKit, run as a subprocess.

    The subprocess gets its own main thread so NSApplication can run without
    conflicting with the host application's asyncio event loop (e.g. the
    Panel/Bokeh Tornado loop in ClaudIA).

    Green banner for BUY, red for SELL, amber "REVIEW ORDER" when `side` is None —
    cancel and reply dialogs genuinely have no side, and colouring those green would
    assert something no caller established.

    Raises HumanAuthError if user cancels/times out.
    Raises RuntimeError if the subprocess itself fails (caller falls back to osascript).
    """
    payload = _json.dumps(
        {
            "title": title,
            "details": details,
            "disclaimer": disclaimer,
            "confirm_label": confirm_label,
            "abandon_label": abandon_label,
            "side": side,
            "action": action,
            "timeout_s": _DIALOG_TIMEOUT_S,
        }
    )
    dialog_script = Path(__file__).parent / "_order_dialog.py"
    try:
        proc = subprocess.run(
            [sys.executable, str(dialog_script)],
            input=payload,
            capture_output=True,
            text=True,
            timeout=_DIALOG_TIMEOUT_S + 10,
        )
    except subprocess.TimeoutExpired as exc:
        raise HumanAuthError("Confirmation dialog timed out") from exc

    if proc.returncode != 0:
        raise RuntimeError(f"AppKit dialog failed: {proc.stderr.strip() or 'unknown error'}")

    output = proc.stdout.strip()
    if output != "CONFIRMED":
        raise HumanAuthError("Order cancelled by user")


def _show_osascript_dialog(
    title: str, details: dict[str, Any], disclaimer: str, confirm_label: str, abandon_label: str
) -> None:
    """Native macOS confirmation dialog via osascript.

    Uses AppleScript 'display dialog' with caution icon, two buttons (abandon / confirm),
    and a hard timeout. The default button is the abandon one so accidental Enter does nothing.

    Source: https://developer.apple.com/library/archive/documentation/AppleScript/Conceptual/AppleScriptLangGuide/reference/ASLR_cmds.html#//apple_ref/doc/uid/TP40000983-CH216-SW12
    """
    detail_lines = "\n".join(f"{k}: {v}" for k, v in details.items())
    message = f"{detail_lines}\n\n{disclaimer}"

    script = (
        f"set dlg to display dialog {_as_str(message)} "
        f"with title {_as_str(title)} "
        f"buttons {{{_as_str(abandon_label)}, {_as_str(confirm_label)}}} "
        f"default button {_as_str(abandon_label)} "
        f"giving up after {_DIALOG_TIMEOUT_S} "
        f"with icon caution\n"
        f"if gave up of dlg then\n"
        f'    return "timeout"\n'
        f"else\n"
        f"    return button returned of dlg\n"
        f"end if"
    )
    try:
        proc = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=_DIALOG_TIMEOUT_S + 5,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        raise HumanAuthError(f"Confirmation dialog failed: {exc}") from exc

    output = proc.stdout.strip()
    if proc.returncode != 0 or output in ("", "timeout", abandon_label):
        raise HumanAuthError("Order cancelled by user")
    if output != confirm_label:
        raise HumanAuthError(f"Unexpected dialog response: {output!r}")


def _as_str(text: str) -> str:
    """Escape a Python string for AppleScript: wrap in quotes, escape backslashes and quotes."""
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _show_tkinter_dialog(
    title: str, details: dict[str, Any], disclaimer: str, confirm_label: str, abandon_label: str
) -> None:
    """Fallback tkinter dialog for non-macOS environments.

    Must be called from the main thread. Auto-cancels after _DIALOG_TIMEOUT_S seconds.

    Security note: on_confirm runs inside the same process as all pip dependencies.
    A compromised dependency with access to tk._default_root could call root.after(0, on_confirm)
    to synthetically confirm without user interaction. Touch ID (Gate 1) already ran before
    this dialog, providing defense-in-depth.
    """
    confirmed: dict[str, Any] = {"value": False}

    root = tk.Tk()
    root.withdraw()

    dialog = tk.Toplevel(root)
    dialog.title(title)
    dialog.attributes("-topmost", True)
    dialog.resizable(False, False)
    dialog.grab_set()

    title_frame = tk.Frame(dialog, bg="#c0392b", pady=8)
    title_frame.pack(fill="x")
    tk.Label(
        title_frame,
        text=title,
        bg="#c0392b",
        fg="white",
        font=("Helvetica", 13, "bold"),
    ).pack()

    detail_frame = tk.Frame(dialog, padx=20, pady=10)
    detail_frame.pack(fill="x")
    for i, (key, val) in enumerate(details.items()):
        tk.Label(detail_frame, text=f"{key}:", font=("Helvetica", 11, "bold"), anchor="w").grid(
            row=i, column=0, sticky="w", pady=2
        )
        tk.Label(detail_frame, text=str(val), font=("Helvetica", 11), anchor="w").grid(
            row=i, column=1, sticky="w", padx=(10, 0), pady=2
        )

    disc_frame = tk.Frame(dialog, bg="#ffeaa7", padx=15, pady=10)
    disc_frame.pack(fill="x", padx=10, pady=5)
    tk.Label(
        disc_frame,
        text=disclaimer,
        bg="#ffeaa7",
        wraplength=340,
        font=("Helvetica", 10),
        justify="left",
    ).pack()

    btn_frame = tk.Frame(dialog, pady=10)
    btn_frame.pack()

    remaining: dict[str, Any] = {"secs": _DIALOG_TIMEOUT_S}
    _after_id: dict[str, Any] = {"id": None}

    def _cancel_tick() -> None:
        if _after_id["id"] is not None:
            with contextlib.suppress(Exception):
                dialog.after_cancel(_after_id["id"])
            _after_id["id"] = None

    def on_cancel() -> None:
        _cancel_tick()
        confirmed["value"] = False
        dialog.destroy()
        root.destroy()

    def on_confirm() -> None:
        _cancel_tick()
        confirmed["value"] = True
        dialog.destroy()
        root.destroy()

    tk.Button(btn_frame, text=abandon_label, command=on_cancel, width=16, bg="#bdc3c7", font=("Helvetica", 11)).pack(
        side="left", padx=10
    )
    tk.Button(
        btn_frame,
        text=confirm_label,
        command=on_confirm,
        width=18,
        bg="#e74c3c",
        fg="white",
        font=("Helvetica", 11, "bold"),
    ).pack(side="left", padx=10)

    countdown_var = tk.StringVar(value=f"Auto-cancels in {remaining['secs']}s")
    tk.Label(dialog, textvariable=countdown_var, fg="#888888", font=("Helvetica", 9)).pack(pady=(0, 6))

    def _tick() -> None:
        remaining["secs"] -= 1
        if remaining["secs"] <= 0:
            on_cancel()
        else:
            countdown_var.set(f"Auto-cancels in {remaining['secs']}s")
            _after_id["id"] = dialog.after(1000, _tick)

    _after_id["id"] = dialog.after(1000, _tick)
    dialog.protocol("WM_DELETE_WINDOW", on_cancel)
    dialog.update_idletasks()
    w, h = dialog.winfo_width(), dialog.winfo_height()
    x = (dialog.winfo_screenwidth() - w) // 2
    y = (dialog.winfo_screenheight() - h) // 2
    dialog.geometry(f"+{x}+{y}")
    root.mainloop()

    if not confirmed["value"]:
        raise HumanAuthError("Order cancelled by user")
