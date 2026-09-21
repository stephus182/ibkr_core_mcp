# Integration-suite audit — 2026-09-20

First run of the integration suite against a live gateway since the `v2.0.1` PyPI release
(2026-09-19). Four findings, all in code or tests that CI cannot reach, all fixed here.

**The common thread, and the reason to read this file rather than the diffs:** none of these
could fail in CI. The integration suite needs a live gateway, CI has none, so `pytest -m "not
integration"` is green with every one of them present. They are found only when someone runs
the whole suite on a machine with an authenticated gateway — which had not happened since the
API-11 typing work (2026-09-17) and the release. `tests/test_client_live.py` already carried a
comment saying exactly this, after seven tests of the same kind were fixed on 2026-09-17; two
were missed, and this audit is the tail of that cleanup.

---

## 1. `preview_order` sent `extOperator`, so every futures whatif was rejected (M7)

`claude_tools._preview_order` set `extOperator = "ClaudIA"` for `FUT`/`FOP`. That is the exact
non-empty value the 2026-07-23 field-8089 finding proved IBKR rejects on this account class,
and it is why `place_order` had already stopped sending it. Preview and place therefore
disagreed: the placement path worked, and every futures preview meant to preview it failed.

**Measured live, 2026-09-20.** Two whatifs on ES Dec-26 (conid `515416632`), bodies identical
but for the one field, so a price-band refusal could not be mistaken for the rejection:

| Body | Result |
|---|---|
| without `extOperator` | accepted — full margin impact, `"error": null` |
| with `extOperator: "ClaudIA"` | `HTTP 500 {"error":"Can not contain field # 8089"}` |

`manualIndicator` alone is accepted, so CME Rule 536-B compliance is unaffected.

Two stale prose copies of the reversed conclusion were corrected in the same commit, both of
which instructed the opposite of what the code does — `place_order`'s docstring told callers
to include `extOperator="<user>"` and claimed HTTP 400 without it, and the display-key comment
said "manualIndicator / extOperator … caller adds them for futures". A reversed conclusion
leaves copies, and the docstring next to the code is corrected last and trusted first.

Fixed in `3941046`. This unblocks the attached-profit-taker Phase 0 whatif probe
(claudia_ui Known Gaps #36), which cannot run while futures previews are rejected.

## 2 & 3. Two live tests still asserted `dict` against typed returns

`test_get_brokerage_accounts` and `test_get_mta_alert` asserted `isinstance(result, dict)`
while the client returns `BrokerageSession` and `MTAAlert`. Both are API-11 debt: the typed
returns landed 2026-09-17, seven tests in this file were migrated that day, these two were not.

The assertions now name the model, as the file's own header comment requires — a typed method
answers with its model, or with the raw payload when `parse_one` could not validate what
arrived, and live that second case is the interesting one, because it means the model has
stopped matching the wire. Asserting `dict` accepts precisely the failure the models exist to
catch. The substance of each original assertion was kept (`result.accounts` non-empty;
`result.account or result.order_id`).

## 4. The crawl error-page guard was testing nothing, for two independent reasons

`test_crawl_site_refuses_to_archive_an_error_page` guards the third instance of "a page count
is not evidence of content". It was failing, and neither cause was a regression in the guard.

**(a) The premise died.** The target was `docs.crawl4ai.com/core/`, a directory prefix nginx
answered `403` with a 44-byte body. Measured 2026-09-20, that URL returns `404` with a
**31,608-byte** styled mkdocs page. The guard refuses only when *every* page assesses as
`"fallback"`; 31 KB of real markdown does not, so the guard correctly declined to fire. The
test depended on one host's incidental error styling, which was never that host's job to keep.
Repointed at `httpbin.org/status/403`, which is purpose-built to return the status asked of it.

**(b) The failure message was about the scaffolding, not the subject.** The docstring promises
"nothing reached Drive: `save_crawl` must never be called", but the store was left real, so
with no `credentials.json` in the test tmp dir the reply became *"Crawl completed (1 pages) but
Drive save failed: FileNotFoundError"*. The test failed on Drive configuration and said nothing
about the guard — and worse, that message is what a genuine guard regression would also have
produced, since reaching the save step at all is the defect. The store is now stubbed with a
`save_crawl` that raises, so the promise is asserted directly and a Drive misconfiguration can
never again stand in front of the subject.

If the new target ever stops returning a thin error body, the test **skips with that reason**
rather than failing as though the guard regressed. A test that cannot tell "my premise moved"
from "the code broke" reports on neither.

---

## Verification

Run on the fix commit, with an authenticated gateway present:

| Gate | Result |
|---|---|
| `ruff check` | passed |
| `ruff format --check` | 126 files formatted |
| `mypy` | 126 source files, no issues |
| `pytest -m "not integration"` (what CI runs) | 1,696 passed |
| `pytest` (full, incl. integration) | **1,784 passed, 14 skipped** |

Each of the three test failures was confirmed **pre-existing** before being touched, by
stashing the M7 change and re-running them — first evidence is not a conclusion, and "my change
broke it" and "my change revealed it" are different claims.

`docs/test-coverage.md` was re-measured with its own commands rather than hand-edited:
1,696 unit / 102 integration / 1,798 total, coverage unchanged at 89%.

## What would catch this class earlier

Nothing here is exotic; all four rotted because the suite that covers them is invisible to CI.
The cheapest guard is to run the full suite whenever a gateway happens to be authenticated —
at minimum before and after a release — and to treat a green `not integration` run as what it
is: evidence about the part of the suite CI can see, and silence about the rest.
