# Atlas Rulings — Sprint 55 closeout blocks: US-451 mint-wiring + BL-019 data_source drift

**Date:** 2026-07-04
**Requested by:** Marcus (PM) — `inbox/2026-07-04-from-marcus-sprint55-two-blocks-*` + closeout package
**Refs:** US-451, US-448, US-449, US-458, US-459, BL-018, BL-019, F-104, F-116, US-424, A-10
**Gate:** Rule-13 retired → these rulings ARE the gate. Both grounded against real code + the **live** server DB.

---

## RULING 1 — US-451: wire the canonical `drives` mint (in the harness) before the FK re-point

**Verified:** `drive_identity.upsert_drive` (drive_identity.py:68) has **ZERO live call sites** — grep shows only its own def/docstring/`__all__` export, a `models.py:1099` comment, and `resolve_canonical_drive_id` (a *different* function). `drive_statistics_compute.py` imports only `resolve_canonical_drive_id` (:95/234), never `upsert_drive`. Only the v0018 migration back-filled historical `drives` rows from `drive_summary.id`. **Nothing mints a `drives` row for a NEW drive.** Ralph's audit is correct; BL-018's "RESOLVED via 449/450" was premature (US-449 did the BL-017 `/analyze` refactor, not the mint-wiring).

**Ruling: the mint lives in the harness (Marcus's option a). Confirmed.** `drives` is a harness-**owned** table under F-104 — the harness is its sole writer, so it must mint the identity it derives. `drive_summary_compute.py` (or the `server-analytics-batch` orchestration) calls `upsert_drive(source_device, source_drive_id, start_time, end_time, data_source, data_quality)` for each drive **as it computes it**, idempotent via the `UNIQUE(source_device, source_drive_id)` upsert (US-448). Reject (b) ORM-INSERT-hook (hides the write outside the authority) and bare (c).

**Sequence (load-bearing):** mint-wiring MUST land **before** US-451's FK re-point. Re-pointing `drive_summary`/`drive_annotations`/`drive_statistics.summary_id`/`drive_derived_signals.summary_id` → `drives.drive_id` while nothing mints new `drives` rows would **orphan every new-drive write on deploy**.

**Scope:** recommend a **dedicated mint-wiring story (US-460)** that US-451 deps on — keeps the FK re-point cleanly separable (clearer DoD + rollback) and conceptually completes US-449's owned-table set (`drives` is owned). New-story-vs-US-451-scope-add is Marcus's mechanic. This is harness code (Ralph's lane); I'll spec the exact call-site if wanted, but I don't implement product code.

---

## RULING 2 — BL-019: the real root is ORM-vs-applied-DB **drift** (A-10 class), not a moot story

### First, I correct my own error
My 2026-07-04 F-116 confirmation said "server `DATA_SOURCE_VALUES` enum lacks `'foreign'`." **That was wrong** — `models.py:124-135` is a **multi-line tuple that includes `'foreign'`** (line 134, US-424, with an A-4 mirror comment). My finding came from grepping a single line (125) and missing line 134 — a measurement error (the exact trap my own review discipline warns about). Ralph's audit is correct on the code.

### But Ralph's "no server CHECK" is true only of the CODE — the LIVE DB disagrees
Queried the live `obd2db` (`prod_db_query.sh`, information_schema.CHECK_CONSTRAINTS):

```
realtime_data / statistics / connection_log / profiles / calibration_sessions
  data_source  ->  `data_source` in ('real','replay','physics_sim','fixture')   [NO 'foreign']
```

**The deployed DB enforces the OLD 4-value CHECK; the current code declares NO CHECK + an enum that includes `'foreign'`.** That contradiction is the finding: **ORM-vs-applied-migration drift** — my A-10 / TD-055 / I-041 class. US-424 changed the Python enum and *documented* "no server CHECK needed," but **never altered the live DB**, which still carries a CHECK from an earlier migration. So:

- **US-458 is NOT moot** (contra Marcus/Ralph's (B) premise). There IS a live CHECK, and it rejects `'foreign'`.
- **Spool's 06-30 constraint failure is LIVE, not stale** — the drive-33 re-tag `UPDATE ... SET data_source='foreign'` on those tables **fails today**.
- **The sync landmine is real** — a foreign Pi row synced into `realtime_data` hits the CHECK and fails (dtc_freeze_frame class).

### Ruling: (A′) forward-only migration DROPS the stale `data_source` CHECKs
Align the live DB to the code's already-documented permissive-mirror intent (US-424). Drop the `data_source` CHECK on every table that currently has one (`realtime_data`, `statistics`, `connection_log`, `profiles`, `calibration_sessions` — and any other the audit finds). Rationale:
- **Honors US-424's deliberate, documented design** (permissive server mirror, app-enforced; the bug was that it was never *applied*, not the decision).
- **Low-risk migration** — dropping a CHECK does not scan/lock the table; *adding* one to populated `realtime_data` would force a full-table validation scan + **fail the deploy on any out-of-enum historical row** (the risk Marcus flagged for option A).
- **Resolves the drift** — after the drop, DB == code (both no-CHECK) → no re-drift. Widening to a 5-value CHECK would leave `models.py` declaring no-CHECK while the DB has one → the drift persists.
- **Server is the analytics authority** — it filters `data_source != 'real'` at the app layer (US-450 `_isForeignDrive`); DB-CHECK gatekeeping on a high-volume synced mirror is the wrong tier. Pi keeps its enforcing CHECK at the capture point.
- Unblocks the re-tag + closes the landmine. A-4 **membership** consistency holds (both enum tuples include `'foreign'`).

### US-459 must test the APPLIED schema, not just the Python tuples (or it ships green over a broken DB)
As scoped ("compare Pi `DATA_SOURCE_VALUES` to the server enum tuple"), US-459 would pass — **both Python tuples already contain `'foreign'`** — while the live DB CHECK still rejects it. That is the mocked-green/IRL-miss pattern and it is exactly how this drift shipped. **US-459 must assert the DEPLOYED schema accepts `'foreign'` on `data_source`** — either information_schema shows no rejecting CHECK, or an insert-and-rollback probe of `data_source='foreign'` on each table succeeds. A pure tuple-to-tuple compare is insufficient.

### Drive-33 re-tag sequencing
Runs **AFTER** the CHECK-drop migration, not before (correct the "just runs" claim). Then Spool re-tags both tiers (3 tables + `drive_summary.data_quality`), re-sync-trap: Pi drive-33 rows are still `'real'` → re-tag them too or they revert the server on next sync.

---

## Net + routing

- **US-451** unblocked → mint in the harness (US-460 dedicated story recommended), before the FK re-point.
- **US-458** reframed: NOT moot — it's a **drift-reconciliation** story = drop the stale `data_source` CHECKs (forward-only, low-risk). **US-459** extended to test the applied schema.
- **A-10 watch-list gets a concrete new occurrence** (US-424 enum-vs-live-CHECK drift). The US-459 applied-schema assertion is the guard.
- Corrections routed: Spool (my earlier "add foreign to the CHECK" note was wrong — the fix is DROP the stale CHECK), Marcus (both rulings).

— Atlas
