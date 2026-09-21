# Order Management — Usage Examples

> **All write operations require fingerprint (Touch ID) + visual confirmation — the rules
> themselves live in CLAUDE.md's Security & Fingerprint Authentication section, not here.**
> This doc is the "how to call it" code walkthrough.

**Setup (used by every snippet below — see `docs/api-usage-examples.md` for the full `Config`/`IBKRClient` walkthrough):**
```python
from ibkr_core_mcp import IBKRClient, Config, HumanAuthError

cfg        = Config.from_env()
client     = IBKRClient(cfg)
account_id = client.get_accounts()[0]["accountId"]

contracts = client.search_contract("AAPL")
order = {
    "conid":     contracts[0]["conid"],
    "ticker":    "AAPL",
    "side":      "BUY",
    "quantity":  10,
    "orderType": "LIMIT",
    "price":     182.50,
    "tif":       "DAY",
}
```

**Read-only — no auth required:**
```python
# List open orders
orders = client.get_live_orders()
for o in orders:
    print(f"{o.get('orderId')}  {o.get('ticker')}  {o.get('side')}  qty={o.get('remainingQuantity')}")

# Preview an order before placing (whatif — never executes)
preview = client.get_order_preview(account_id, order)
print(f"Estimated cost: {preview.get('equity', '?')}")
```

**Place a live order — Gate 1 (Touch ID) + Gate 2 (confirmation dialog), full reply chain resolved automatically:**
```python
try:
    # place_order_and_confirm() is the recommended entry point: one Touch ID
    # up front covers the whole chain (an OrderWriteAuthorization bound to this
    # account and body's hash, 300 s), then it calls place_order() and loops a dialog
    # showing the real IBKR message through every chained reply, until a
    # terminal response. One fingerprint, one dialog per reply.
    # Verified live 2026-07-06: a single order needed 3 sequential replies
    # (price-band %, no-market-data, mandatory-cap-price) before Submitted.
    # Declining any reply mid-chain POSTs {"confirmed": False} to IBKR before
    # raising HumanAuthError — unlike bare reply_order() below, which raises
    # without ever telling IBKR, leaving the order ambiguous on IBKR's side.
    result = client.place_order_and_confirm(account_id, order)
except HumanAuthError as e:
    print(f"Order not sent: {e}")
```

**Manual control — call `place_order`/`reply_order` yourself instead of `place_order_and_confirm`:**
```python
try:
    responses = client.place_order(account_id, order)
    # A reply can chain into ANOTHER reply requirement — loop until terminal.
    # Must run immediately, back-to-back — IBKR invalidates (503) a reply left
    # pending while other requests are made. Show the human the text they're
    # agreeing to before confirming — IBKR sends "message" as a list of strings,
    # not a single string, so join it first (place_order_and_confirm's internal
    # _resolve_one_reply does the same join before displaying it in Gate 2).
    while responses and "id" in responses[0]:
        message = " ".join(responses[0].get("message", []))
        print(message)  # show the human what they're confirming
        responses = client.reply_order(responses[0]["id"])
except HumanAuthError as e:
    print(f"Order not sent: {e}")
```

**GTC orders are not indefinite:** they auto-cancel at the end of the calendar
quarter *following* the current one (placed in Q3 → cancels end of Q4; placed in
Q1 → cancels end of Q2) — not simply "year-end." Confirmed live 2026-07-06: an
order placed in Q3 returned "will be automatically canceled at 20261231 16:00:00
EST" (end of Q4), matching IBKR's documented convention exactly. Source:
https://www.interactivebrokers.com/campus/trading-lessons/mosaic-good-till-cancelled-gtc-order-type/

**Modify — `modify_order_and_confirm()` resolves any reply chain the same way `place_order_and_confirm()` does (not yet live-verified to require chained replies, but shares `modify_order`'s response shape); cancel has no reply chain:**
```python
order_id = result[0]["order_id"]  # from a previously placed order, e.g. result above

try:
    client.modify_order_and_confirm(account_id, order_id, {"price": 180.00, "tif": "DAY"})
except HumanAuthError as e:
    print(f"Modification not sent: {e}")

try:
    client.cancel_order(account_id, order_id)
except HumanAuthError as e:
    print(f"Cancellation not sent: {e}")
```

**Bracket — a parent plus its held children in ONE request, behind one Touch ID and one dialog:**

A bracket is not two orders placed in sequence. One POST of a ticket array makes the pair
atomic at IBKR, so there is no window in which the child is live alone; two independent
orders are never a substitute, because a standalone opposite-side limit is live immediately
and can *open* the wrong position rather than close one. The parent carries a `cOID`, each
child carries `parentId` equal to it and no `cOID` of its own.

```python
parent = {
    "conid": conid,
    "cOID": "MY-BRACKET-1",       # unique for 24 h, max 64 chars
    "orderType": "LMT",
    "side": "BUY",
    "quantity": 1,
    "price": 180.00,
    "tif": "GTC",
    "ticker": "AAPL",
}
children = [
    {   # profit taker — opposite side, never larger than the parent
        "conid": conid,
        "parentId": "MY-BRACKET-1",
        "orderType": "LMT",
        "side": "SELL",
        "quantity": 1,
        "price": 190.00,
        "tif": "GTC",
    },
    {   # protective stop
        "conid": conid,
        "parentId": "MY-BRACKET-1",
        "orderType": "STP",
        "side": "SELL",
        "quantity": 1,
        "price": 172.00,
        "tif": "GTC",
    },
]

# Read-only first — ungated, and it prices BOTH legs.
preview = client.get_bracket_preview(account_id, parent, children)

try:
    # ONE Touch ID bound to the whole array, ONE dialog showing every leg, then every
    # ticket's reply chain resolved — not just the parent's.
    entries = client.place_bracket_and_confirm(account_id, parent, children)
except ValueError as e:
    # Refused BEFORE Touch ID: the pair is not a bracket (link, contract, side or size).
    print(f"Not a bracket, nothing sent: {e}")
except HumanAuthError as e:
    print(f"Bracket not sent: {e}")
else:
    # IBKR's response is NOT index-aligned with the submission — two live sends both
    # returned [child, parent] for a [parent, child] array. Pair by identifier.
    pairing = pair_bracket_response([parent, *children], entries)
    if not pairing.ok:
        for problem in pairing.problems:
            print(f"bracket did not pair cleanly: {problem}")
    parent_order_id = pairing.parent["order_id"] if pairing.parent else None
```

`pair_bracket_response` and `BracketPairing` import from `ibkr_core_mcp`, like the rest of
the package's public API — they are module-level names, not methods on `IBKRClient`. The pairing
is checked and logged by `place_bracket_and_confirm` itself, so a caller that never calls it
still leaves a record; calling it yourself is how you get the order ids.

**What the bracket path refuses, before any gate** (`ValueError` from `_bracket_tickets`,
repeated by `confirm_bracket_dialog` because that function is public API and callable on its
own): no parent `cOID`; no children; a child whose `parentId` does not name the parent; a
child carrying its own `cOID`; a child naming a different contract; a child on the parent's
own side, or carrying no side; and a child larger than the parent. Each is a refusal and
never a correction — silently shrinking a leg would break order-parameter immutability.

Note that a preview cannot substitute for these checks: measured live 2026-09-20, a child on
a *different instrument* returns a whatif response byte-identical to a valid one, because
IBKR previews the first ticket and discards the rest. **A mismatched bracket previews clean.**

**IBKR order constraints:**
- Trade history via API limited to last 7 days (current + 6 previous) — `SQLiteStore` persists indefinitely
- Orders require `conid` — resolve via `client.search_contract(symbol)`
