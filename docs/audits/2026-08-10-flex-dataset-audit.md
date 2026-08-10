# Flex dataset audit — 2026-08-10

Companion to `docs/plans/2026-08-07-flex-audit-handoff.md`, which covers the code changes.
This file records what was found in, and done to, the **live database and archive**.

Database: `~/.ibkr_core/store.db`. Archive: `~/.ibkr_core/flex_archive`.

---

## 1. The dataset was, and is, correct

The gate was run read-only against production before any change (`audit_flex_dataset.py`
opens `mode=ro`). Stronger evidence than the gate alone: a copy of the production database
was rebuilt from scratch out of the refreshed archive, and the resulting audit output
**differs from production only in the database-path line**. The `flex_trade`
`(trade_id, fifo_pnl_realized)` digest is identical (`814dc973d4633ca0`).

| Figure | Value |
|---|---|
| `flex_trade` rows (`source='flex'`) | 1,117 |
| Realised P&L (the figure to report) | −13,229.51 USD |
| Closed lots, pre-wash-sale | −28,630.56 USD |
| Wash-sale loss disallowed | 15,401.05 USD |
| Legacy `trades` rows | 1,213 |
| Annual reconciliations 2020–2025 | all exact, to the cent |

## 2. The archive was one statement stale — and it produced a false RED

The first baseline run reported **5 failures** and printed *"do not ship this dataset"*.
All five were the same 7 rows, and none was a data defect:

`flex_U1675699_2026-08-06_4602951826.xml` (112 trades, imported 2026-08-06 per
`flex_import_log` id 29) was **not in the local archive**, which had last been fetched
2026-08-05 08:25. The audit was comparing a correct database against an out-of-date source
of truth.

Refetching resolved it — and the downloaded file's SHA-256 (`9c14a4cfcc9a…`) matched the
value `flex_import_log` had recorded on the day of import, independently confirming both
sides. Baseline went to **42/42**.

**This was a live data-loss window, not a reporting curiosity.** Running
`scripts/rebuild_flex_dataset.py` that day would have dropped `flex_trade` and re-imported
only what the stale archive held, permanently destroying 7 real trades:

| trade_id | date | symbol | realised P&L |
|---|---|---|---|
| 1252588883 | 20260805 | CLU6 | −6,064.72 |
| 1252589021 | 20260805 | CLU6 | −6,324.72 |
| 1252898281 | 20260805 | CLU6 | −834.72 |
| 1252968172 | 20260805 | ESU6 | +1,078.54 |
| 1252862756 / 1252882064 / 1252935928 | 20260805 | CLU6 / ESU6 | 0.00 (opens) |

Check **`0b. archive holds every statement the import log recorded`** now catches this
condition directly, and `rebuild` refuses before dropping anything.

## 3. Archive change — the ErrorCode 1019 payload

`flex_U1675699_2026-07-02_2928480049.xml` was 226 bytes of:

```xml
<FlexStatementResponse timestamp='02 July, 2026 08:05 PM EDT'>
<Status>Warn</Status><ErrorCode>1019</ErrorCode>
<ErrorMessage>Statement generation in progress. Please try again shortly.</ErrorMessage>
</FlexStatementResponse>
```

Not a statement. `1019` confirmed verbatim against
<https://www.ibkrguides.com/clientportal/performanceandstatements/flex3error.htm>.
`flex_query._get_statement` has retried this condition since the incident, so the file is a
fossil of the pre-fix code path, not evidence of a live bug.

- **Deleted** from `~/.ibkr_core/flex_archive/` on 2026-08-10 (owner decision — no value; a
  source statement can be re-requested if ever needed).
- **Preserved** as evidence at `~/.ibkr_core/backups/flex_U1675699_2026-07-02_2928480049.xml`.
- **Still present on Drive.** A local delete is not durable: the very next
  `fetch_flex_archive.py` run downloaded it straight back. `fetch_flex_archive.py` is
  read-only against Drive by design and stays that way, so it now *refuses to write* any
  payload whose root element is not `<FlexQueryResponse>`, reports it, and exits 1. Deleting
  the Drive copy would clear that warning; nothing depends on it either way.

## 4. Database change — one row deleted from `flex_import_log`

**The only write made to production in this session.**

```sql
DELETE FROM flex_import_log WHERE id = 13;
```

The row claimed the 1019 payload above had been imported *and verified*:

```
id=13  filename=flex_U1675699_2026-07-02_2928480049.xml
sha256=7ee13b7cbfa5342b85cb70f77df07373ef6fd4770d5356610dffbd5fd8f2db06
trade_id_count=0  raw_trade_count=0  source=auto
imported_at=2026-07-03T00:05:55Z  verified_at=2026-07-23T01:32:20Z
```

Left over from the 2026-07-02 silent-empty-sync incident. Five checks before the write:

1. **The row describes the error payload.** Its `sha256` matches the preserved file byte for
   byte — not an inference from the filename.
2. **It contributed nothing.** Zero rows across all 14 `flex_*` tables carry that `src_file`.
3. **Deletion is safe.** No foreign key anywhere references `flex_import_log`.
4. **It is the only row check `0b` flags** — the sole logged filename absent from the archive.
5. **It is the only row in the table with `raw_trade_count = 0`.** Every other row of the 23
   imported between 18 and 506 trades.

**Why delete rather than loosen the check.** The alternative — having `0b` ignore rows with
`raw_trade_count = 0` — was rejected. That column counts *trades only*, so the exception
would also silence a legitimately trade-free statement carrying hundreds of cash
transactions, creating exactly the blind spot this audit exists to remove. The row is false
data in an audit log: it asserts an import and a verification that never happened.

### Before / after

| | before | after |
|---|---|---|
| `flex_import_log` | 23 | **22** |
| `trades` | 1,213 | 1,213 |
| `flex_trade` | 1,117 | 1,117 |
| `flex_lot` / `flex_wash_sale` | 712 / 59 | 712 / 59 |
| Realised P&L (trades / lots / wash) | −13,229.51 / −28,630.56 / 15,401.05 | unchanged |
| `flex_trade` digest | `814dc973d4633ca0` | `814dc973d4633ca0` |
| `PRAGMA integrity_check` | ok | ok |
| Gate | 45/46 | **46/46, exit 0** |

### Backups

| File | What |
|---|---|
| `~/.ibkr_core/backups/store-2026-08-10-pre-flex-session.db` | Start of session; bit-identical to production throughout the code work |
| `~/.ibkr_core/backups/store-20260810-pre-import-log-delete.db` | Taken immediately before the `DELETE`; `integrity_check: ok` |
| `~/.ibkr_core/backups/pre-import-log-delete.20260810.txt` | Full pre/post state snapshot, all 23 log rows listed |
| `~/.ibkr_core/backups/flex_U1675699_2026-07-02_2928480049.xml` | The deleted payload itself |

## 5. Archive integrity, now actually verified

`fetch_flex_archive.py` previously hashed whatever bytes were on disk and compared them to
nothing — for an already-present file it read the local copy, hashed it, and recorded that
as truth. `md5Checksum` was never requested from Drive (zero occurrences repo-wide).

It is now requested (`cache.py`) and compared for **both** the cached and downloaded paths;
a mismatch refuses and writes no manifest. Current state: **22 of 22 files verified against
Drive's own `md5Checksum`** — the first time the docstring's "verifiable set of bytes" has
been true.

## 6. Standing note

The production dataset was **not** rebuilt, by owner decision. The value delivered is the
guards; the data was already correct, and a rebuild carries risk with no offsetting benefit.
Before anyone runs `rebuild_flex_dataset.py` in future: refresh the archive first, then use
`--dry-run`. The script now refuses on an unparseable archive, refuses while unenriched
`source='live'` rows exist, backs up before dropping, and returns the audit gate's exit code.
