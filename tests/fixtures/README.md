# Live IBKR response shapes

`ibkr_live_shapes.json` holds **verbatim responses from the real IBKR Client Portal
Gateway**, captured 2026-09-16 against a live authenticated session (build 2023-04-24).
Account numbers are the only thing rewritten (`U1234567`); every key, every type and
every value is exactly what came off the wire.

**Why it exists.** `tests/test_models.py` fed every model a dict invented to match that
model, so the tests passed while the models did not work. Measured against these
captures, two models raised and two returned all-empty objects. A fixture whose shape
you chose cannot tell you whether the shape is right — only the wire can.

**Rules.**

- Never edit a payload to make a test pass. If a model disagrees with this file, the
  model is wrong; this is what IBKR sent.
- Re-capture, do not hand-patch, if IBKR changes a shape — and say so in the commit.
- `positions`, `live_orders`, `trades` and `alerts` reflect one particular account at
  one moment. Assert on *keys and types*, not on the specific instruments or values.

Captured by `scripts/audit/capture_live_response_shapes.py`.

**Two payloads are not verbatim, and are labelled in the file:**

- `scanner_params` is truncated to the first two entries of every list (the real response
  is 218 KB of static reference data). Its key structure is intact.
- `market_snapshot` came back as `{"conid", "conidEx"}` with no price fields. That is the
  response itself, not a capture error: IBKR's first snapshot call primes the subscription
  and returns metadata only. Do not treat it as evidence that quote fields are absent.
