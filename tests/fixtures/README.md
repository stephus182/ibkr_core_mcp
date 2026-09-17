# Live IBKR response shapes

`ibkr_live_shapes.json` holds the **shape of real responses from the IBKR Client Portal
Gateway**, captured 2026-09-16 against a live authenticated session (build 2023-04-24).
Every key, every nesting level and every scalar *type* is exactly what came off the wire.
**The values are not.**

This file said "account numbers are the only thing rewritten … every value is exactly what
came off the wire", and that was true. It was committed to a PUBLIC repository carrying the
account holder's legal name, net liquidation value, cash balance, buying power, both open
positions with their average costs, four executed futures fills with their IBKR execution
IDs, a resting order and every watchlist name (finding SEC-13, 2026-09-16).

**What is redacted, and what is not.** `scripts/audit/redact_live_payload.py` holds the
rules. Eight endpoints returning public contract and market reference data — the same bytes
for every IBKR customer — keep their values. In every other endpoint the default is to
replace, and the exemptions are named: `currency`, `secType`, `assetClass`, `type`, `key`,
`secondkey`, `rowType`, `isNull`, `severity`, `group`, `model`. Replacements preserve the
*domain* as well as the type, because IBKR sends `price` and `commission` as numeric
strings and `R` as a 0/1 int that Pydantic reads as a bool — a redaction that ignored that
broke twelve of this fixture's own tests.

`tests/security/test_published_identifiers.py` holds these properties against the committed
file, so the capture script's assertion is no longer the only thing between a live capture
and a public commit. That is the actual lesson: the old assertion was real, and its scope
was one field class of ten.

**Why it exists.** `tests/test_models.py` fed every model a dict invented to match that
model, so the tests passed while the models did not work. Measured against these
captures, two models raised and two returned all-empty objects. A fixture whose shape
you chose cannot tell you whether the shape is right — only the wire can.

**Rules.**

- Never edit a payload to make a test pass. If a model disagrees with this file, the
  model is wrong; this is what IBKR sent.
- Re-capture, do not hand-patch, if IBKR changes a shape — and say so in the commit.
- Assert on *keys and types*, never on values. The values are placeholders; a test that
  pins one is asserting against the redactor, not against IBKR.
- If you re-capture, run the script — never hand-edit. The script redacts and then checks
  its own output, and a hand-edited file has had neither done to it.

Captured by `scripts/audit/capture_live_response_shapes.py`.

**Two payloads are not verbatim, and are labelled in the file:**

- `scanner_params` is truncated to the first two entries of every list (the real response
  is 218 KB of static reference data). Its key structure is intact.
- `market_snapshot` came back as `{"conid", "conidEx"}` with no price fields. That is the
  response itself, not a capture error: IBKR's first snapshot call primes the subscription
  and returns metadata only. Do not treat it as evidence that quote fields are absent.
