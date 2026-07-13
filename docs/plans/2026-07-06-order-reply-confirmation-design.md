# Order Reply-Confirmation Fix — Design

**Status:** Design approved 2026-07-06; **implemented and verified 2026-07-06** —
`ibkr_core_mcp` commits `62e7e8b` (auto-resolve chained replies, show real IBKR
text) and `251ef54` (tighten HTML-strip regex, normalizer tests); the consuming
project switched its one call site. All design decisions matched exactly (see
`docs/claude-tools-audit-2026-07.md` register item 14 for the verification
detail). 613 `ibkr_core_mcp` unit tests + 31 consuming-project order_flow tests green.
**Scope repos:** `ibkr_core_mcp` (new orchestrating methods + dialog fix) and the consuming
project (one call-site update).

## Problem

A live order-flow test on 2026-07-06 (`BUY 1 AAPL, LMT @ $100.00, GTC` — see
`docs/claude-tools-audit-2026-07.md`, Appendix B "Live order-flow test" findings, and
register item 14) surfaced three real gaps:

1. **The consuming project's `order_flow.py`'s `execute_staged_order`** calls `IBKRClient.place_order()`
   and immediately declares "Order staged successfully" — it never checks whether the
   response requires a reply (`{"id", "message", ...}`) and never calls `reply_order()`.
   Confirmed live: the order sat `Inactive`/`Pending Submit` on IBKR's side while the UI
   reported success.
2. **`reply_order()`'s own response can require another reply.** The test order needed
   3 sequential confirmations (price-band 3% `o163` → no-market-data `o354` →
   mandatory-cap-price `o10153`, the last with different button labels: `Decline`/
   `Accept and Continue` vs. the first two's `Yes`/`No`) before reaching `Submitted`.
   Official docs: a pending reply must be answered immediately or IBKR invalidates it
   (503 on the next attempt).
3. **`ibkr_core_mcp/order_confirm.py`'s `confirm_reply_dialog()`** shows only
   `"Reply ID: <uuid>"` — never the actual IBKR warning text. This violates CLAUDE.md's
   own Gate 2 principle ("full order details") and was called out explicitly by the
   package owner: the human must read, understand, and validate the real message before
   confirming, every time.

## Constraints (non-negotiable, per CLAUDE.md)

- Never bypass or weaken Gate 1 (Touch ID) or Gate 2 (visual confirmation).
- Enforcement stays at the innermost call site (`IBKRClient`), not pushed up to the consuming project.
- No password/PIN fallback; no session cache for the gates.
- `ClaudeToolkit` continues to expose no tool for any of these methods — order execution
  remains UI-layer only, triggered by a physical button click.

## Approved design

### 1. New orchestrating methods in `ibkr_core_mcp/client.py`

```python
def place_order_and_confirm(self, account_id: str, order: dict[str, Any]) -> list[dict[str, Any]]:
    """Place an order and resolve its full reply chain.

    Loops place_order -> reply_order -> reply_order... until a terminal response
    (no 'id'/'message') is returned. Each step fires Gate 1 (Touch ID) + Gate 2
    (dialog showing the REAL IBKR message text) independently -- no reply is
    auto-confirmed, and no IBKR-native suppression (isSuppressible) is used.
    """

def modify_order_and_confirm(self, account_id: str, order_id: str, order: dict[str, Any]) -> dict[str, Any]:
    """Same loop/display/decline semantics as place_order_and_confirm(), for modify.

    Added proactively: modify_order() has the identical never-replies bug shape as
    place_order() did, though this was not verified live (no live modify test run
    yet) -- see docs/claude-tools-audit-2026-07.md register item 14.
    """
```

Both call the existing `place_order()`/`modify_order()`/`reply_order()` primitives
internally — those stay exactly as they are today (already correctly gated
individually) and remain directly usable for callers who want manual control.

**Loop body, each iteration:**
1. Extract `message` (join the `message: list[str]` array) and `messageOptions`
   from the response.
2. Call `require_touch_id(...)` (Gate 1).
3. Call `confirm_reply_dialog(reply_id, message, options)` (Gate 2 — see below).
   - On confirm: proceed to step 4 with `confirmed=True`.
   - On decline/cancel: `self._post(f"/iserver/reply/{reply_id}", {"confirmed": False})`
     **then** raise `HumanAuthError("User declined IBKR order reply")`. (This is the
     one behavior change vs. today's `reply_order()`: today a cancelled dialog raises
     `HumanAuthError` without ever contacting IBKR, leaving the order ambiguous.)
4. `POST /iserver/reply/{reply_id}` with `{"confirmed": confirmed}`.
5. If the new response still has `id`/`message`, repeat from step 1. Otherwise return it.

**Timing discipline:** nothing else may run between receiving a reply's response and
either showing the next dialog or sending the next reply — no incidental logging or
store writes inside the loop body, since IBKR invalidates (503) a pending reply left
too long or interleaved with other requests.

### 2. `confirm_reply_dialog()` signature change

`ibkr_core_mcp/order_confirm.py`:

```python
def confirm_reply_dialog(reply_id: str, message: str, options: list[str] | None = None) -> None:
    """Gate 2 for reply_order. Shows the ACTUAL IBKR warning text, not just the reply_id."""
```

- Strip basic HTML from `message` before display (tonight's mandatory-cap-price
  message contained `<h4>...</h4>` — the AppKit/tkinter dialogs are plain text).
- Button labels stay the package's own consistent **Confirm** / **Decline** —
  do not surface IBKR's varying `Yes`/`No` vs. `Decline`/`Accept and Continue`
  wording as actual button labels; map internally to `confirmed=True/False`.
- `_show_confirm_dialog`'s existing `details` dict gains a `"Message"` key
  carrying the (HTML-stripped) text, displayed prominently.

### 3. Consuming-project update

One call site: `order_flow.py:255`, `ibkr.place_order(...)` →
`ibkr.place_order_and_confirm(...)`. Downstream result handling (extracting
`orderId`, logging the staged-order decision) adapts to the guaranteed-terminal
response shape — no more risk of "success" being reported on a non-terminal reply.

No `modify_order` UI call site exists yet in the consuming project — `modify_order_and_confirm`
ships ready for when that UI is built.

### 4. Testing (TDD)

Extend the existing gate-testing pattern already in `tests/test_client.py`
(`place_order`/`reply_order` tests mock `require_touch_id` + the dialog functions
cleanly — same pattern applies here). New cases:

- `place_order_and_confirm`: 0 replies (straight through), 1 reply, 3 chained replies
  (matching tonight's real shape) — each terminates correctly.
- Decline mid-chain: confirms `{"confirmed": False}` is POSTed, then `HumanAuthError`
  raised.
- `confirm_reply_dialog` receives the correct `message`/`options` at each step.
- HTML-stripping in the dialog display path.
- `modify_order_and_confirm` mirrors the same cases.
- Consuming project: `execute_staged_order` calls the new method (mock-level test, matching
  existing `order_flow.py` test conventions if any exist — check before assuming).

## Out of scope

- `cancel_order()` — does not have a reply-confirmation step in the current API
  (single call, no `{"id", "message"}` response pattern observed or documented).
- Live-testing `modify_order_and_confirm` end-to-end (would require another real
  order modification) — ship it correctly per the same design, verify live opportunistically
  on a future session rather than blocking this fix on it.
- Any change to Touch ID (Gate 1) itself.

## References

- Live order-flow test findings: `docs/claude-tools-audit-2026-07.md`, Appendix B
  ("Live order-flow test (2026-07-06) — findings") and register item 14.
- IBKR reply confirmation contract: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#place-order-reply
- GTC quarter-end auto-cancel (unrelated finding from the same test, already fixed/documented):
  `ibkr_core_mcp/client.py` `place_order()` docstring, commit `6b413d6`.
