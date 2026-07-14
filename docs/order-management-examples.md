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
    # place_order_and_confirm() is the recommended entry point: it calls
    # place_order(), then loops Touch ID + a dialog showing the real IBKR
    # message through every chained reply, until a terminal response.
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

**IBKR order constraints:**
- Trade history via API limited to last 7 days (current + 6 previous) — `SQLiteStore` persists indefinitely
- Orders require `conid` — resolve via `client.search_contract(symbol)`
