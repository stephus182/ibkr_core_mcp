# Symbology Reference — how a ticker becomes a contract

**A ticker is not a unique key.** This document exists because treating it as one shipped a
real defect: `IGV` was reported at a Mexican-peso price for a US ETF, off by the USD/MXN
rate, and nothing about the number looked wrong.

Everything below is either quoted from IBKR's documentation or captured from the live
gateway on 2026-07-28. Nothing here is inferred.

---

## 1. What IBKR documents

> *"The following endpoint is designed specifically for resolving stock symbols into
> `conids`. Note that it accepts a comma-separated list, and returns all matching results
> accordingly."* — `GET /trsrv/stocks?symbols=AAPL`

> *"For a single product trading in multiple markets, IB will assign distinct `conids` for
> each combination of product and currency. For instance, AAPL stock trading in USD in the
> United States has a different `conid` than the same AAPL stock trading in MXN. A single
> instrument that is traded in multiple markets will have its records grouped together."*

Source: <https://www.interactivebrokers.com/campus/ibkr-api-page/web-api-staging/>
(Contracts → Equities. Scraped 2026-07-28 via Crawl4AI — the page 403s a plain fetch and
Firecrawl thins it to nothing, so the local browser scraper is the route that works.)

Two consequences, both load-bearing:

1. **`/trsrv/stocks` is the stock resolver**, by IBKR's own designation.
   `/iserver/secdef/search` is presented as the general-purpose endpoint for finding
   relationships between underliers and their derivatives — not for picking a listing.
2. **conid is per (product, currency)**. So "the conid for IGV" is not a well-formed
   question until a venue is chosen.

### Response shape

```json
{ "IGV": [ { "name": "ISHARES EXPANDED TECH-SOFTWA",
             "assetClass": "STK",
             "contracts": [ { "conid": 12658199,  "exchange": "BATS", "isUS": true  },
                            { "conid": 325209548, "exchange": "MEXI", "isUS": false } ] } ] }
```

`isUS` is the only US-listing signal any contract endpoint returns. **Use it rather than
maintaining a list of US exchange codes** — a hand-kept list is a second source of truth
that silently rots as IBKR adds venues.

---

## 2. What the gateway actually returns

Live probe, 2026-07-28. `search_contract()` is `/iserver/secdef/search`; index `[0]` is what
the old resolver used.

| Ticker | `[0]` was | Reality |
|---|---|---|
| **IGV** | **MEXI**, conid 325209548, **MXN** | BATS/USD (12658199) is the US listing. BVME (195853874, EUR) is **I GRANDI VIAGGI SPA** — a different company. |
| AAPL | NASDAQ, USD | Correct — *by luck*. Also MEXI, EBS, and a TSE **CDR** (a different instrument). |
| SOXX | NASDAQ, USD | Correct. Also MEXI. |
| SPY | ARCA, USD | Correct. Also MEXI, ASX. |
| VOD | NASDAQ | That is the **ADR**. VOD/LSE is the ordinary share; VOD/JSE is **VODACOM**, a different company. |

**The ordering is not documented as meaningful, and it is not consistently wrong — it is
inconsistent.** That is worse than being always wrong, because it works in testing.

Also observed on `/iserver/secdef/search` results: the keys are `companyHeader`,
`companyName`, `conid`, `description`, `restricted`, `sections`, `symbol`. **There is no
`exchange` key** — the exchange code is in `description`. Any filter written against
`c["exchange"]` matches nothing and silently falls through.

`/iserver/secdef/info?conid=` returns `currency` (verified: MXN / USD / EUR for the three
IGV listings) and `listingExchange`. It returns a **list**, despite the wrapper's `dict`
annotation.

---

## 3. The rule implemented

`ClaudeToolkit._resolve_stock_conid`. Deliberately universal — **no instrument-specific
branches.** A rule derived from IGV must hold for every ticker or it is not a rule.

1. **An explicit `exchange` wins.** No listing on it is an **error naming what exists**,
   never a substitution.
2. **Otherwise prefer the US listing.** A bare ticker is a US ticker by convention. Exactly
   one `isUS: true` contract resolves.
3. **Zero or several US listings is a question, not a default.** Return the candidates —
   each with its exchange, company name and conid — so the user is asked. No price is
   reported until they answer.
4. **Always state the currency.** `_Resolved` carries it beside the conid so a handler
   cannot report a price without it, and an unreadable currency surfaces as `UNKNOWN`
   rather than being omitted. An absent currency reads as "the usual one", which is the
   assumption that produced the original defect.

### Why ask rather than guess

A wrong listing does not fail — it returns a plausible number for the wrong instrument.
That is worse than no number, because nothing about it invites checking. Asking costs one
round trip; the alternative costs a decision made on a price from another country.

---

## 4. Scope and known gaps

- `/trsrv/stocks` is **STK only**. IND and BOND still resolve via `/iserver/secdef/search`
  (now filtering on `description`, and erroring rather than substituting).
- **`get_secdef()` was broken — but not for the reason first recorded here.** Corrected
  2026-07-28. The original note claimed `/trsrv/secdef` is a POST endpoint called with GET,
  inferred from the *Additional Usage Limits* table (`/trsv/secdef | POST | 200
  conids/request` — note IBKR's own path typo). **That inference was wrong.** The endpoint
  reference documents `GET /trsrv/secdef?conids=…` and shows `requests.get(...)`. A
  usage-limits table is not a method specification.

  The actual defect was the **response shape**: the body is `{"secdef": [ … ]}`, an object
  wrapping the array, and the wrapper returned `data if isinstance(data, list) else []` —
  so every call silently returned `[]`. Identical in shape and cause to the
  `get_currency_pairs` defect fixed 2026-06-30. Fixed by unwrapping the `secdef` key.

  Source: <https://www.interactivebrokers.com/docs/web-api/web-api-v-1-0-documentation/endpoints/contract/search-the-security-definition-by-contract-id>

  **Live-verified 2026-07-28** against an authenticated gateway, first call:
  `get_secdef([12658199, 325209548, 195853874])` returned **3 rows, not `[]`**, the raw body
  really is `{"secdef": [ … ]}` rather than a bare list, and the currencies came back
  **USD / MXN / EUR** exactly as predicted, with `isUS`, `listingExchange`, `countryCode`
  and `name` all present. The documentation-only fix is now executed, not merely read.

- **Currency is still read one conid at a time** via `/iserver/secdef/info`. Now that
  `get_secdef` is live-verified, it is the batch path — one call for up to 200 conids,
  returning `currency`, `listingExchange`, `countryCode`, `isUS` and `name` together.
  Switching the resolver to it is a straightforward follow-up; the blocker (an unexecuted
  fix) is cleared as of 2026-07-28.

- **A ticker's listings can be different companies, and this is live-proven, not
  hypothetical.** The same `get_secdef` call returned conid `195853874` (BVME) as
  **I GRANDI VIAGGI SPA** — an Italian travel operator — under the ticker `IGV`, alongside
  the iShares ETF on BATS and MEXI. Any resolution path that picks a listing without asking
  can therefore price the wrong *issuer*, not merely the wrong venue or currency.

- **FIXED 2026-07-28 — two live defects, one root cause: the model is told only what the
  tool *description* says.** `tools` returns `TOOL_DEFINITIONS` verbatim and nothing
  appends `__doc__`, so a rule written in a handler docstring never reaches Claude. The
  description named `_data_status` and `_quote_time` and said *"Always report both"* — and
  ClaudIA reported both in every single answer. `_currency` appeared nowhere in it, only in
  the docstring. Both live failures followed from that one omission:

  1. **Currency went unnamed for USD.** Foreign listings were always spelled out
     ("MXN 1,603.98", "€59.54") because the venue made the currency salient; USD was
     rendered as a bare `$91.42`. `$` is written by USD, MXN, CAD, AUD, HKD and SGD alike,
     so the one case the IGV regression is about was the one case the unit was omitted.
  2. **The resolver stopped guessing, so the agent started.** Asked "What's BMW trading
     at?" with no exchange, ClaudIA called `get_market_snapshot{exchange: "ETR"}`, received
     the correct ambiguity refusal listing IBIS and TSE with *"Ask the user which one they
     mean — do not substitute another exchange"*, and then **issued a second call with
     `exchange: "IBIS"` and priced a listing the user never chose**. The question was being
     consumed as a hint instead of surfaced.

  The description now names `_currency` as one of three fields to always report, requires
  the **ISO code** and forbids a bare `$`, states that without `exchange` the US listing is
  selected, and directs that the ambiguity question be **put to the user rather than
  answered by re-calling with an exchange of the model's own choosing** — citing IGV
  (iShares ETF on BATS, I Grandi Viaggi SpA on BVME) as why choosing can price the wrong
  issuer. Three description tests pin all of it, including the removal of the stale
  "Without exchange, the first result is used" claim.

  **Live-verified after the change** (fresh process — a stale one had already produced one
  false failure this session): `IGV` → *"Last: **USD 91.71**"* plus an unprompted
  issuer-collision warning; `VOD` → *"Last: **USD 16.38**"*, so the ISO rule generalises
  rather than keying on IGV; `BMW` → **one** tool call, **no price**, and *"I need you to
  pick the listing… IBIS (Xetra) — conid 14094, trades in EUR; TSE (Tokyo) — conid
  758555570, trades in JPY. Which one do you want?"*
