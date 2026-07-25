# Bug: `get_watchlists` returns empty when the account has watchlists

**Found:** 2026-07-23, during claudia_ui Panel-migration live testing (real IBKR gateway).
**Severity:** Medium — data-completeness bug (silent under-report, not a crash, not a
fabrication). No wrong *action* results, but the user is told "no watchlists" when they have 8.
**Status:** Open — filing note, not yet fixed.

## Symptom

Asking ClaudIA "show me my watchlists" → tool `get_watchlists` returns
`"No watchlists found in IBKR account."`, but the account actually has **8 user watchlists**.
(ClaudIA itself behaved correctly — it honestly relayed the empty tool result and did **not**
fabricate, unlike an earlier 2026-06-26 Chainlit run that invented 3 fake watchlists. The
fabrication path is fixed; the tool-parsing bug is what remains.)

## Evidence

Raw gateway `GET /iserver/watchlists` (no `SC` param) → **HTTP 200**, body shape:

```json
{"data": {"scanners_only": false,
          "system_lists": [ {"name": "US Indices and ETFs", "id": "NAMED_USINDETF", ...}, ... 28 total ],
          "user_lists":   [ {"name": "Favorites", "id": "103"},
                            {"name": "(1) Commodity Futures", "id": "105"},
                            {"name": "Index Futures", "id": "104"},
                            {"name": "FX", "id": "106"},
                            {"name": "Futures", "id": "101"},
                            {"name": "us", "id": "-7171512622707682541"},
                            {"name": "Favoris", "id": "-2848335496026461312"},
                            {"name": "Favorites", "id": "10"} ] }}
```

The `get_watchlists` tool result stored in the conversation DB: `"No watchlists found in IBKR account."`

## Root cause

`IBKRClient.get_watchlists()` (`ibkr_core_mcp/client.py:1053`):

```python
def get_watchlists(self) -> list[dict[str, Any]]:
    data = self._get("/iserver/watchlists", {"SC": "USER_WATCHLIST"})
    return data if isinstance(data, list) else []
```

The response is a **nested dict** (`{"data": {"user_lists": [...], "system_lists": [...]}}`),
not a top-level list. So `isinstance(data, list)` is always `False` → the method always
returns `[]` → `claude_tools._get_watchlists` (`claude_tools.py:2582-2584`) reports
"No watchlists found." The `{"SC": "USER_WATCHLIST"}` query param does not change the response
into a list either.

## Suggested fix (verify against official docs per "API Docs First" before implementing)

Parse the nested structure, e.g.:

```python
def get_watchlists(self) -> list[dict[str, Any]]:
    resp = self._get("/iserver/watchlists", {"SC": "USER_WATCHLIST"})
    data = resp.get("data", {}) if isinstance(resp, dict) else {}
    user_lists = data.get("user_lists") or []
    return user_lists if isinstance(user_lists, list) else []
```

Decisions to confirm before coding:
- Whether to include `system_lists` (read-only named lists like "US Indices and ETFs") or
  only `user_lists`. The tool description says "all IBKR watchlists"; user_lists is the
  minimum correct fix, system_lists optional.
- Whether the `SC=USER_WATCHLIST` param is correct / needed — the raw call *without* it
  returned both lists; confirm what `SC` filters.
- Scrape the official endpoint doc
  (`https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#all-watchlists`) to
  confirm the response schema before changing the parse — do not assume from this one live
  sample.
- Add a regression test with the real nested-dict response shape (the existing tests must
  have used a list-shaped fixture, which is why this wasn't caught).

## Related

- `claudia_ui/docs/project-status.md` — live-test §, pending doc verification **item 11**
  ("correct IBKR CP API watchlist endpoint path"). Previously the endpoint was seen as HTTP
  404; it now returns 200, so the open question shifts from "wrong path" to "wrong response
  parsing." This note resolves the *what* for item 11.
