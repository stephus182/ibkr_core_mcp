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

# A ticker is not a listing, and this conid is what the order buys. Resolve a stock through
# /trsrv/stocks and its `isUS` flag and stop when it is not unique — never the first match of a
# symbol search, whose order IBKR does not document (for IGV it is the Mexican listing, in MXN).
us = [c for r in client.get_stocks(["AAPL"]) for c in r["contracts"] if c.get("isUS")]
if len(us) != 1:
    raise SystemExit(f"AAPL: {len(us)} US listings — name the exchange rather than pick one")
order = {
    "conid":     int(us[0]["conid"]),
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
    # A reply that is not confirmed — declined, or nobody answered the dialog —
    # POSTs {"confirmed": False} to IBKR before raising ReplyNotConfirmedError
    # (a HumanAuthError; its message says which, and quotes IBKR's question) —
    # unlike bare reply_order() below, which raises without ever telling IBKR,
    # leaving the order ambiguous on IBKR's side.
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

# A futures or futures-option cancel made by a person: state the CME Rule 536-B tag,
# as the place and modify bodies do with "manualIndicator": True.
try:
    client.cancel_order(account_id, futures_order_id, manual_indicator=True)
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

# Read-only first — ungated. Both legs are sent so the ARRAY is validated as one unit,
# but IBKR prices the FIRST ticket only: measured live 2026-09-22, a whatif of the parent
# alone comes back byte-identical to a whatif of the full bracket. A clean preview is no
# evidence about the child — see the note under this block.
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

## Time in force — what IBKR accepts, where it says so, and what this package does with it

Read from IBKR's own pages and from its contract rules on 2026-09-24 (read-only), for
claudia_ui gap #70. **The values come from three places, and the three do not agree** — so no
single list here is "the" list, and the authority for one order is that contract's own rules.

**1. Where IBKR states TIF values**

| Where | Values | Source |
|---|---|---|
| The order body's `tif` — "Time in force of the order ticket", an enum, required | `DAY`, `IOC`, `GTC`, `OPG`, `PAX` (on `PAX`, see below) | [submit-new-order](https://www.interactivebrokers.com/docs/web-api/api-reference/trading/trading-orders/submit-new-order); the same five on [get-order-status](https://www.interactivebrokers.com/docs/web-api/api-reference/trading/trading-orders/get-order-status) and in IBKR's OpenAPI document (v2.40.0) |
| Overnight orders — "submitting the affiliated Time-In-Force value" | `OVT` (Overnight), `OND` (Overnight + DAY) | [overnight-order-submission](https://www.interactivebrokers.com/docs/web-api/v1/endpoints/orders/overnight-order-submission). **Not in the enum above** |
| Per contract — `POST /iserver/contract/rules`, `tifTypes`: "Indicates allowed tif types supported for the contract" | Whatever that contract accepts — measured below. Includes `GTD`, **which is in neither list above** | [search-contract-rules](https://www.interactivebrokers.com/docs/web-api/v1/endpoints/contract/search-contract-rules) |

**2. What two contracts return** — `tifTypes`, both sides identical, 2026-09-24:

| TIF | F — a US stock (conid 9599491) | ES Dec-26 — a CME future (conid 515416632) |
|---|---|---|
| `DAY` | ✅ | ✅ |
| `GTC` | ✅ | ✅ |
| `IOC` | ✅ | ✅ |
| `GTD` | ✅ | ✅ |
| `OPG` | ✅ `OPG/LIMIT,MARKET,a` | — |
| `OVT` | ✅ `OVT/o,a,LIMIT` | — |
| `OND` | ✅ `OND/o,a,LIMIT` | — |

Each entry is the TIF, a slash, and a list (`"GTC/o,a"`, `"OND/o,a,LIMIT"`). IBKR's page does
not define the list; in the measured values it names order types and the letters `o` and `a`.
**Two contracts are two measurements, not a rule per asset class** — read the rules of the
contract in hand: `client.get_contract_rules(conid, is_buy)["tifTypes"]`.

**3. Reading a TIF back**

| Endpoint | Field | What it returned for a DAY order |
|---|---|---|
| `/iserver/account/order/status/{id}` | `tif` — "Returns the time in force of the order." | `DAY` |
| `/iserver/account/orders` | `timeInForce` — "Returns the time in force (tif) of the order." | **`CLOSE`** — a stock and a future alike; `GTC` orders read `GTC`. `CLOSE` is in none of the lists above and does **not** mean a closing-auction order (`docs/ibkr-api-behaviors-reference.md`) |
| same | `orderDesc` | IBKR's own sentence, which states it: `Buy 1 F Limit 5.10, Day` |

**4. What this package does**

| Surface | Behaviour |
|---|---|
| `place_order`, `modify_order` and their `_and_confirm` forms | Send the body's `tif` **exactly as given**. No list is applied and no default is added: a value IBKR does not accept is answered by IBKR. |
| Gate 2 dialog | Shows the `tif` being sent; a body with none shows `— (not sent)`, never `DAY`. |
| `get_contract_rules` | Returns the contract's `tifTypes` (typed as `tif_types`), entries as IBKR sends them. **No `ClaudeToolkit` tool exposes it.** |
| `preview_order` (tool) | Offers `DAY`, `GTC`, `IOC`, `OPG` — four of the enum's five. `PAX`, `GTD`, `OVT` and `OND` cannot be previewed through it, although a contract's rules may accept the last three. Left out, the preview is for `DAY` and says so. It does not read the contract's rules: `OPG` on a contract that does not list it is answered by IBKR's preview, not refused here. |
| `get_live_orders` (tool) | Quotes `orderDesc`; never prints the row's `timeInForce` as the TIF. |
| `get_order_status` (tool) | Returns the status endpoint's `tif`. |
| Price alerts | A different vocabulary: `GTC` or `GTD` only — IBKR documents no `DAY` for an alert (`docs/tools-reference.md`, `create_price_alert`). |

**5. Auction orders — the close is an order type, the open is a TIF**

| Order | Body, per IBKR's order-type pages | Here |
|---|---|---|
| Market-on-open | `orderType: "MKT"`, `tif: "OPG"` ([MOO](https://www.interactivebrokers.com/docs/general/order-types/market-orders/market-on-open)) | Expressible; `preview_order` takes it |
| Limit-on-open | `orderType: "LMT"` + `price`, `tif: "OPG"` ([LOO](https://www.interactivebrokers.com/docs/general/order-types/basic-orders/limit-orders/limit-on-open)) | Expressible; `preview_order` takes it |
| Market-on-close | `orderType: "MOC"`, `tif: "DAY"` ([MOC](https://www.interactivebrokers.com/docs/general/order-types/market-orders/market-on-close)) | The client sends a body as given; `preview_order` does not offer `MOC` |
| Limit-on-close | `orderType: "LOC"` + `price` ([LOC](https://www.interactivebrokers.com/docs/general/order-types/basic-orders/limit-orders/limit-on-close)) | Same; `preview_order` does not offer `LOC` |

`MOC` and `LOC` are **documented for the Web API on those pages and absent from the OpenAPI
`orderType` enum** (`MKT`, `LMT`, `STP`, `STOP_LIMIT`, `MIDPRICE`, `TRAIL`, `TRAILLMT`). F's
rules list them (`marketonclose`, `limitonclose` in `orderTypes`); ES's rules list neither,
although IBKR's MOC page names FUT among its products.

**`PAX` — listed by IBKR, defined by IBKR nowhere found.** Researched 2026-10-05 at the
operator's question ("what is it?"):

| Where it was looked for | What is there |
|---|---|
| IBKR's OpenAPI document (v2.40.0) | `PAX` is the fifth value of the `tif` enum of the order ticket (`singleOrderSubmissionRequest` — submit and modify) and of `orderStatus`. The description is "Time in force of the order ticket."; no value is described. A third order endpoint in the same document, *Submit New Model Portfolio Order*, lists four: `DAY`, `GTC`, `OPG`, `IOC` |
| [submit-new-order](https://www.interactivebrokers.com/docs/web-api/api-reference/trading/trading-orders/submit-new-order), [get-order-status](https://www.interactivebrokers.com/docs/web-api/api-reference/trading/trading-orders/get-order-status) | "Allowed values: `DAY`, `IOC`, `GTC`, `OPG`, `PAX`" — the list, no definitions |
| IBKR's legacy Client Portal Web API reference (v1.0.0, https://www.interactivebrokers.com/api/doc.json) | Defines four and has no `PAX`: "GTC - use Good-Till-Cancel for orders to remain active until it executes or cancelled. OPG - use Open-Price-Guarantee for Limit-On-Open (LOO) or Market-On-Open (MOO) orders. DAY - if not executed a Day order will automatically cancel at the end of the markets regular trading hours. IOC - any portion of an Immediate-or-Cancel order that is not filled as soon as it becomes available in the market is cancelled." |
| IBKR Campus Web API pages ([trading](https://www.interactivebrokers.com/campus/ibkr-api-page/web-api-trading/), [documentation](https://www.interactivebrokers.com/campus/ibkr-api-page/webapi-doc/)) | No `PAX` |
| [TWS API order reference](https://interactivebrokers.github.io/tws-api/classIBApi_1_1Order.html) | `DAY`, `GTC`, `IOC`, `GTD`, `OPG`, `FOK`, `DTC` — no `PAX` |
| Contract rules, measured (part 2) | Neither F's nor ES's `tifTypes` lists `PAX` |
| IBKR's [Cryptocurrency Trading](https://www.interactivebrokers.com/docs/general/order-types/notes-limitations/cryptocurrency-trading) page | In the pages read, the letters occur otherwise only in **PAXOS**, one of the two venues IBKR's cryptocurrency orders are routed to. That page lists the times in force of a cryptocurrency order — `DAY`, `GTC`, `IOC` for a limit order, `IOC` only for a market order, "Minutes" on the TWS API — and `PAX` is not among them |

So: **what `PAX` does is not established.** That it belongs to orders routed to PAXOS is a
guess from the name, which IBKR's own cryptocurrency page does not support, and it is not
stated here as more than that. What is established is narrower and enough to act on: the
stock and the future measured do not accept it. **This package** sends a body's `tif` as
given, so a caller can send `PAX`; `preview_order` does not offer it — a tool that offered it
would be naming a time in force nobody here can describe, for contracts whose rules do not
list it. One read-only call would settle where it applies: the contract rules of a contract
that lists `PAX` in `tifTypes`.

**Not established** — stated rather than guessed:

- What `PAX` is (above).
- What `o` and `a` mean in a `tifTypes` entry.
- Whether the gateway accepts `MOC` / `LOC` on place (never sent; a `whatif` would settle it
  without a write).
- How a `GTD` order's expiry is given: contract rules return `GTD`, and neither of IBKR's two
  place-order pages (`v1/endpoints/orders/place-order`, `api-reference/…/submit-new-order`)
  mentions the value or a field for its date.
- When an Overnight + Day order ends. IBKR's
  [lesson](https://www.interactivebrokers.com/campus/trading-lessons/overnight-trading-using-limit-order/)
  says of "Overnight + Day": "stay active until either filled or 4pm the next day"; its
  [overnight page](https://www.interactivebrokers.com/en/trading/us-overnight-trading.php)
  says "the SMART + OVERNIGHT order type keeps your orders working from the overnight session
  through 8:00 PM the next day". Whether those describe the same order is not stated either.

Evidence: scrapes and read-only captures of 2026-09-24 in
`claudia_ui/.firecrawl/order-tif/` (git-ignored; `SOURCES.md` indexes them); the `CLOSE`
readings are dated in `docs/ibkr-api-behaviors-reference.md`.

**IBKR order constraints:**
- Trade history via API limited to last 7 days (current + 6 previous) — `SQLiteStore` persists indefinitely
- Orders require `conid` — for a stock, resolve it through `client.get_stocks` and its `isUS`
  flag, as in Setup. Never take the first match of `client.search_contract(symbol)`: its order is
  undocumented and it carries neither `isUS` nor a currency (`docs/symbology-reference.md` § 2)
