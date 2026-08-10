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

---

## 7. Live end-to-end verification (same day, after the code changes)

Run against the real gateway and the real Flex Web Service, to confirm the fetch path
still works and lands what IBKR actually has. Database backed up first to
`~/.ibkr_core/backups/store-20260810-pre-live-flex-sync.db` (`integrity_check: ok`).

### The fetch is provably complete

32 fills were captured from the CP API (`/iserver/account/trades?days=7`) **before** the
sync, as an independent reference, then matched against `flex_trade` by IBKR's own
execution id — not by date, which cannot work: CL and ES futures trade nearly around the
clock, so a fill's wall-clock date and its `tradeDate` routinely differ.

| | |
|---|---|
| Live fills matched in `flex_trade` | **26 of 32** |
| Not matched | **6 — every one dated 2026-08-10 (today)** |

That is the correct result, not a gap: Flex is T+1, so today's fills cannot appear in any
statement yet. Every historical fill IBKR showed live is present.

Per-day counts differ from the CP API (Aug 6: 4 vs 5, Aug 7: 10 vs 8) purely because of
the trading-day boundary described above. Matching on execution id is the only sound
comparison; matching on date would report phantom discrepancies.

### What the sync brought in

| | before | after |
|---|---|---|
| `flex_trade` (`source='flex'`) | 1,117 | **1,131** (+14) |
| `flex_trade` (`source='live'`) | 0 | 0 |
| legacy `trades` | 1,213 | 1,227 (+14) |
| `flex_import_log` | 22 | 23 (+1) |
| Newest settled date | 2026-08-05 | **2026-08-07** |
| Rows dated 2026-08-10 | — | **0** (correct: T+1) |

The archive write succeeded — `stored 1799 rows across 13 element types` — so no refusal
warning was emitted, which is the correct behaviour of the Phase 6 change on a healthy
sync. The staleness note also cleared on its own, having correctly read
`DATA STALE (settled through 2026-08-05, 5d)` beforehand.

### Check 0b earned itself back within the hour

The sync uploads its statement to Drive but does not refresh the local archive, so the
gate immediately went to **40/46** with the *same five* failures seen at the start of the
day — 1,131 rows vs 1,117 in XML, two element counts, two distribution mismatches.

The difference is that the first line now says why:

```
[FAIL] 0b. archive holds every statement the import log recorded
       — 1 missing: ['flex_U1675699_2026-08-10_6523460410.xml']
```

That morning the same five failures appeared with no explanation and took a full
investigation to attribute. `fetch_flex_archive.py` then downloaded the file (verified
against Drive's md5) and the gate returned to **46/46, exit 0**.

**Operational consequence: `sync_flex_trades` leaves the local archive one statement
behind. Refresh it before running or trusting the gate.**

### Final state

| | |
|---|---|
| Gate | **46/46, exit 0** |
| `PRAGMA integrity_check` | ok |
| Annual reconciliations 2020–2025 | still **exact to the cent**, all six |
| Realised P&L identity (trades == lots + wash-sale) | holds: −11,367.35 == −26,768.40 + 15,401.05 |
| Archive | 23 files, **23/23 verified against Drive md5** |
| Unenriched live rows | 0 |

Realised P&L moved −13,229.51 → **−11,367.35** on the 14 new trades. The entire +1,862.16
change falls in 2026 (−23,571.92 → −21,709.76); every prior year is unchanged, which the
six annual reconciliations independently confirm.
