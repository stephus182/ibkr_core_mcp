# Quote Access Matrix — Asset Classes × Resolution Endpoints — 2026-06-30

**Scope:** Verification of `get_market_snapshot` conid resolution for every IBKR asset class
(STK, IND, FUT, CASH, BOND, OPT) used by `claude_tools.py → _resolve_snapshot_conid()`, against
official IBKR Client Portal API documentation. Triggered by a false "Delayed" assessment on
live-subscribed symbols, which led to a full audit of how every asset class resolves a ticker
to a conid before requesting a snapshot.

**Previous audit:** `docs/security-audit-2026-06-25.md`

---

## Summary

| Asset class | Resolution endpoint | Status before this audit | Status after |
|---|---|---|---|
| STK | `GET /iserver/secdef/search` | Correct | Correct — added optional `exchange` filter for multi-listing tickers |
| IND | `GET /iserver/secdef/search` | Correct | Correct |
| BOND | `GET /iserver/secdef/search` | Correct | Correct |
| FUT | was routed through `/iserver/secdef/search` (undocumented for FUT) | **Bug** — wrong endpoint, no front-month logic | **Fixed** — `GET /trsrv/futures`, front-month by lowest `expirationDate` |
| CASH (FX) | was routed through `/iserver/secdef/search` (undocumented for CASH) | **Bug** — wrong endpoint | **Fixed** — `GET /iserver/currency/pairs`, `'BASE.QUOTE'` exact match |
| OPT | not implemented in `get_market_snapshot` | Out of scope | Still out of scope — documented multi-step flow (see below) |

A second, independent bug was found and fixed in the same pass: `get_currency_pairs()` in
`client.py` called an undocumented endpoint (`/iserver/secdef/currency`) that does not appear
anywhere in the official cpapi-v1 docs, and its response-parsing logic expected a bare list
when the real response is a dict keyed by currency — so the method always silently returned
`[]`, independent of which endpoint it called. See "Root cause" below.

---

## Per-asset-class resolution (verified against official docs)

### STK / IND / BOND — `/iserver/secdef/search`

**Official doc:** `secType: String. Valid Values: "STK", "IND", "BOND"`
Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#sec-search

This is the only secType list documented for this endpoint — FUT, OPT, CASH, CFD are not
listed despite earlier in-repo docstrings claiming otherwise (see "Root cause").

For international listings (e.g. ASML on Euronext Amsterdam vs. a US ADR), the same symbol can
return multiple contracts across exchanges. `_resolve_snapshot_conid()` accepts an optional
`exchange` parameter: if provided, results are filtered to `contract["exchange"].upper() ==
exchange.upper()`; if no match is found, it falls back to the unfiltered first result rather
than failing outright (a near-miss exchange code is still resolvable to *something*, which is
preferable to a hard failure on a parameter mismatch).

### FUT — `/trsrv/futures`

**Official doc:** documented endpoint, returns all non-expired contracts for one or more root
symbols as a dict keyed by root symbol: `{"ES": [{...}, {...}], "CL": [{...}]}`.
Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/

Front-month selection: the contract with the lowest `expirationDate` in the returned list.
Symbol must be the **root only** (`"ES"`, not `"ESH25"`) — expiry-qualified symbols are not
accepted by this endpoint.

### CASH (FX) — `/iserver/currency/pairs`

**Official doc:** documented endpoint, response keyed by the requested currency:
`{"USD": [{"symbol": "USD.SGD", "conid": 37928772, "ccyPair": "SGD"}, ...]}`.
Source: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#get-currency-pairs

Symbol format: `'BASE.QUOTE'` (e.g. `'EUR.USD'`). Resolution splits on `.`, queries
`get_currency_pairs(base)`, then matches the full `'BASE.QUOTE'` symbol exactly against the
`symbol` field of the returned pairs. IBKR routes FX execution through IDEALPRO; this endpoint
only resolves the conid, it does not select a routing venue.

An adjacent endpoint, `GET /iserver/exchangerate?source=USD&target=AUD` (returns `{"rate":
float}`), was discovered during the same doc scrape but is not a conid-resolution path — it
returns a computed rate, not a contract. Not wired into any tool; noted here for future
reference only.

### OPT — out of scope for `get_market_snapshot`

**Official doc confirms** options require a separate multi-step flow, not a single search call:
1. `search_contract(underlying_symbol, "STK")` (or `"IND"`) to resolve the underlying.
2. `get_secdef_info(conid)` (`GET /iserver/secdef/info`) with strike/expiry/right parameters to
   resolve the specific option contract's conid.
3. Pass the resolved option conid directly to `get_market_snapshot`.

`get_market_snapshot`'s tool description instructs the caller (Claude) to do this explicitly:
call `search_contract` first, then pass the resolved conid — not a ticker — to
`get_market_snapshot`. This was already correctly documented in the tool description before
this audit; not modified.

---

## Root cause: two independent endpoint bugs, same failure pattern

Both bugs follow the same shape as the previously-documented Flex Web Service `gdcdyn` →
`ndcdyn` bug (see CLAUDE.md "API Reference — Docs First"): an endpoint was assumed correct from
memory/convention rather than verified against the official docs, and went undetected because
the failure mode was silent (empty result, not an error).

**Bug 1 — FUT/CASH resolved through the wrong endpoint.** `_resolve_snapshot_conid` (the
dispatch added by this fix) previously did not exist; `get_market_snapshot` resolved every
sec_type — including FUT and CASH — through `search_contract()`, i.e.
`/iserver/secdef/search`. That endpoint's documented `secType` values are `STK`, `IND`, `BOND`
only. For FUT and CASH this either silently returned wrong/empty results or relied on
undocumented endpoint tolerance that is not guaranteed to hold across IBKR API versions.

**Bug 2 — `get_currency_pairs()` called a nonexistent endpoint.** Independent of Bug 1,
`client.py`'s `get_currency_pairs()` called `GET /iserver/secdef/currency` — an endpoint that
does not appear anywhere in the official cpapi-v1 docs page (confirmed by full-page endpoint
enumeration: every `GET`/`POST`/`DELETE` path string on the page was extracted and searched).
The documented endpoint is `GET /iserver/currency/pairs`. Compounding the wrong-URL bug, the
method's response-parsing logic (`isinstance(data, list)`) assumed a bare list response; the
real response (confirmed from docs) is a dict keyed by the requested currency. Even if the
correct URL had been used, the old parsing logic would have silently discarded every result,
because `isinstance({"USD": [...]}, list)` is `False`.

**Why this matters for the original report:** the user observed `GE`/`EEM` quotes labeled
"Delayed" when live data was expected. That specific issue was a separate, already-resolved
6509-field interpretation bug (see CLAUDE.md principle: 6509 `N` means no data at all, not
"delayed" — fixed in the prior session). This audit was the *follow-up* instruction — "verify
quote access for all asset classes... I must be able to access any ticker anywhere" — to check
whether the same class of endpoint-assumption bug existed elsewhere in the resolution path. It
did, in FUT and CASH.

---

## Fixes applied

1. **`claude_tools.py`** — added `_resolve_snapshot_conid(sym, sec_type, exchange)`, dispatching
   per sec_type to the correct documented endpoint (STK/IND/BOND via `search_contract` +
   exchange filter; FUT via `get_futures` + front-month selection; CASH via
   `get_currency_pairs` + `'BASE.QUOTE'` matching). `_get_market_snapshot()`'s resolution loop
   now calls this helper per symbol instead of always calling `search_contract`.
2. **`client.py`** — fixed `get_currency_pairs()`: corrected URL to `/iserver/currency/pairs`,
   corrected response parsing to flatten the dict-of-lists shape (same pattern as
   `get_futures()`/`get_stocks()`).
3. **`client.py`** — corrected `search_contract()`'s docstring, which previously listed
   `"STK", "FUT", "OPT", "FX", "IND", "CFD", "BOND"` as valid `secType` values. Only
   `STK`/`IND`/`BOND` are documented; the corrected docstring states this and points to the
   correct method for each unsupported type.
4. **`docs/api-reference.md`** — same corrections applied to the human-readable reference doc
   for `search_contract()` and `get_currency_pairs()`.

---

## Test coverage added

| Test file | New tests | What they verify |
|---|---|---|
| `tests/test_claude_tools.py` | `test_execute_get_market_snapshot_fut_uses_futures_endpoint_not_search` | FUT resolves via `get_futures`, never calls `search_contract` |
| | `test_execute_get_market_snapshot_fut_no_contracts_found` | Empty `get_futures()` result → clean failure, no snapshot call |
| | `test_execute_get_market_snapshot_exchange_filter_selects_listing` | `exchange` param selects the matching listing among multiple results |
| | `test_execute_get_market_snapshot_exchange_filter_no_match_falls_back` | No matching exchange → falls back to first result instead of failing |
| | `test_execute_get_market_snapshot_cash_uses_currency_pairs_not_search` | CASH resolves via `get_currency_pairs`, never calls `search_contract` |
| | `test_execute_get_market_snapshot_cash_invalid_format_rejected` | Non-`'BASE.QUOTE'` CASH symbol rejected before any client call |
| | `test_execute_get_market_snapshot_cash_pair_not_found` | Pair not present in `get_currency_pairs()` result → clean failure |
| `tests/test_client.py` | `test_get_currency_pairs_handles_dict_response` | Dict-of-lists response correctly flattened |
| | `test_get_currency_pairs_returns_empty_on_unexpected_type` | Non-list/non-dict response → `[]`, no exception |

All 494 unit tests pass (`pytest -m "not integration" -q`).

---

## Known limitations / not yet covered

- **Live verification against the real IBKR gateway is still pending.** All fixes and tests in
  this audit are unit-level with a mocked `IBKRClient`. No live call has confirmed FUT
  front-month selection, CASH/FX pair resolution, or exchange filtering against actual IBKR
  responses for the 20-exchange list in CLAUDE.md's Market Calendar section.
- **Exchange-by-exchange live spot-check across all 20 exchanges has not been performed.** This
  audit verified the *resolution mechanism* (which endpoint, which response shape) against
  official docs for each asset class; it did not individually query a representative ticker on
  each of the 20 exchanges (NYSE, CME, LSE, Xetra, Eurex, Euronext Paris, Borsa Italiana, TSE
  Tokyo, HKEX, SSE Shanghai, BSE Mumbai, KRX Seoul, ASX Sydney, TSX Toronto, B3 São Paulo, BMV
  Mexico City, JSE Johannesburg, Tadawul, IDX Jakarta, Borsa Istanbul). The `exchange` filter
  mechanism is generic and exchange-code-agnostic, so it should work for any IBKR-recognized
  exchange code, but this has not been empirically confirmed per-exchange.
- **OPT (options) is not implemented inside `get_market_snapshot`.** The multi-step
  `search_contract` → `get_secdef_info` flow is documented in the tool description as something
  the calling agent (Claude) must perform itself before calling `get_market_snapshot` with a
  resolved conid. No dedicated single-call options-quote tool exists.
