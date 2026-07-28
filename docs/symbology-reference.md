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
- **`get_secdef()` is broken**: `/trsrv/secdef` is a **POST** endpoint (IBKR's own rate-limit
  table lists `/trsv/secdef | POST | 200 conids/request`) and the wrapper issues a GET, so it
  returns nothing. Currency is therefore read one conid at a time via
  `/iserver/secdef/info`. Fixing `get_secdef` would allow batching. Not done here — it is a
  separate defect with its own blast radius.
- Currency costs one extra call per resolved conid. Acceptable for correctness; revisit if
  a batch path appears.
