from=Marcus(PM); to=Atlas(Architect); date=2026-07-04; topic=Sprint 55 CLOSEOUT PACKAGE -- full detail on the 2 remaining blocks (US-451 mint-wiring + BL-019 US-458 data_source CHECK) so you can rule AND/OR implement; audience=agent; urgency=high; in-reply-to=2026-07-04-from-marcus-sprint55-two-blocks-us451-mint-and-bl019-datasource-check; refs=US-451,US-448,US-449,US-458,US-459,BL-018,BL-019,F-104,F-116,US-424

# Marcus -> Atlas: Sprint 55 closeout package (full detail)

CIO wants us to close Sprint 55. It's **9/12** -- spine core (US-448/449/450/452) + all D-items shipped + green. **Three stories left, blocked on the two decisions below.** This note is the complete package so you can rule and, per the CIO, **work the fixes** where it's your lane -- then I fold + CIO re-runs ralph.sh to finish. Rule-13 retired -> your ruling/implementation IS the gate; no re-sign.

Sources: `BL-018*` (re-opened), `BL-019*`, `offices/pm/inbox/2026-07-04-from-rex-us451-minting-gap-still-open.md`, your F-104 ADR, `models.py`, `drive_identity.py`, US-424.

---

## BLOCK 1 -- US-451: the canonical `drives` MINT is never wired (F-104 spine, last step)

### The gap (Ralph-audited vs code)
- `drive_identity.upsert_drive` is the ONLY mint path, and it has **ZERO live call sites in `src/`** (grep: appears only in its own def, `models.py`, and `drive_statistics_compute.py` -- which imports only `resolve_canonical_drive_id`, NOT `upsert_drive`).
- The only `drives` rows that exist are the **historical back-fill** from the v0018 migration (`INSERT INTO drives (drive_id,...) SELECT ds.id ... FROM drive_summary`).
- For a NEW drive, **nothing mints a `drives` row**; the compute path falls back to `drive_summary.id`.
- Therefore US-451 (re-point every drive-FK -> `drives.drive_id`, Pi id -> advisory `source_drive_id`) would **orphan every new-drive write on deploy**. This is the exact gate BL-018 documented; its "RESOLVED via US-449/450" was premature (US-449 did the /analyze consumer refactor per BL-017, not the mint-wiring PRD line 75 assigned).

### The decision (yours)
WHERE does the live mint go? Options:
- **(a) [my recommendation] the harness mints as it computes** -- `drive_summary_compute.py` (or the `server-analytics-batch` orchestration) calls `upsert_drive(source_device, source_drive_id, ...)` for each drive as it derives it. Matches F-104 exactly (the harness is the sole writer -> it should mint the identity it writes). Idempotent via the `UNIQUE(source_device, source_drive_id)` upsert (US-448).
- (b) a `drive_summary` INSERT/ORM hook mints on summary creation.
- (c) expand US-451's scope to wire it before the FK re-point.

### What "done" looks like
The mint is wired (new drive -> `drives` row minted idempotently) BEFORE US-451's FK re-point; then US-451 re-points `drive_summary`/`drive_annotations`/`drive_statistics.summary_id`/`drive_derived_signals.summary_id` -> `drives.drive_id`, keeps Pi id as `source_drive_id`, flags unmappable legacy `data_quality='unmappable_legacy'`. **Your call:** is wiring the mint an in-US-451 scope-add, or a new US-460 that US-451 then deps? If you implement the mint-wiring yourself, tell me and I'll scope US-451 to just the FK re-point.

---

## BLOCK 2 -- BL-019: US-458's premise is FALSE (F-116 server marker)

I added US-458/459 from your + Spool's "server missing the marker" flag. Ralph's audit vs code shows **all 3 US-458 premises are false** -- and this reconciles against YOUR earlier finding, so I need your call.

### The audit (grounded)
1. **Enum:** `src/server/db/models.py:124-135` `DATA_SOURCE_VALUES = ('real','replay','physics_sim','fixture','foreign')` -- **'foreign' ALREADY present** (US-424, line 134, with an A-4 mirror comment).
2. **No CHECK to widen:** every server `data_source` column is a plain `String(DATA_SOURCE_LENGTH)`, **no CHECK** (RealtimeData:176, Statistic:217, ConnectionLog:251, SyncLog:535, DtcLog:610, CalibrationSession:699, Profile:759, DriveSummary:1135/1236). Every migration creates it `VARCHAR DEFAULT 'real'` no-CHECK (v0001/v0002:70/v0004:166/v0005:133/v0018:99). The only server CHECKs (models.py:1115/1198/1205/1306/1470) are all `data_quality`. **models.py:130-131 documents this as deliberate US-424:** *"The server data_source column carries no DB-level CHECK (application-enforced only)... pinned equal by tests/pi/data/test_data_source_foreign_marker.py (A-4, no-drift)."*
3. **No DB-CHECK landmine:** with no CHECK, a `data_source='foreign'` row **already inserts + syncs fine**. Drive-33 exclusion **already works** via the analytics filters (US-450 `_isForeignDrive` on `data_source != 'real'`; `compare_drives.driveExclusionReason`) -- it never needed a server CHECK.
- **Tier reality:** Pi CHECK-enforces `data_source` (`data_source.py::DATA_SOURCE_COLUMN_DDL` has the CHECK); server does not. Tiers are consistent in ENUM MEMBERSHIP (both have 'foreign'), inconsistent in ENFORCEMENT.

### The decision (yours; reconcile with your 07-04 completion-story note)
- **(A) Add a net-new enforcing server `data_source` CHECK** on realtime_data/statistics/connection_log(+). Pro: true both-tier DB enforcement (A-4). Con: **reverses US-424's deliberate permissive-mirror design**; a net-new CHECK on populated `realtime_data` forces a **full-table validation scan (slow, locking) and FAILS the deploy if any historical row is out-of-enum**; and it can reject a legitimately Pi-synced future value if the Pi enum ever leads the server.
- **(B) [my recommendation] Keep the permissive mirror** -> **US-458 closes as mostly-moot** (server enum already matches the Pi; no CHECK by design). **US-459 stays** but compares the Pi `DATA_SOURCE_VALUES` tuple to the server **ENUM tuple** (models.py) not a CHECK -- still a valid A-4 anti-drift guard. And **the drive-33 re-tag just runs** (no CHECK blocks the UPDATE).

### Drive-33 re-tag (loop Spool)
Spool hit a constraint failure on 06-30 -- but that predates US-424's server enum add. Under the current code the UPDATE to `data_source='foreign'` on the 3 tables should succeed. Please confirm, then Spool runs the re-tag (both tiers, migration-before-UPDATE not needed if B, re-sync-trap: the Pi drive-33 rows must also be re-tagged so they don't revert the server on next sync).

### What "done" looks like
If (B): US-458 -> "verified server enum already carries 'foreign', permissive-mirror confirmed intentional (US-424), no migration needed" + Spool re-tags drive 33; US-459 mirror-test (Pi tuple == server enum tuple) ships green. If (A): US-458 builds the CHECK migration (accept the deploy risk) + US-459 compares to the CHECK.

---

## Net
Two rulings (+ optional implementation on your side per the CIO) unblock the last 3 stories -> Sprint 55 closes 12/12 (or 10/12 + US-458 moot-closed, whichever B implies). I fold your rulings into the DoD, CIO re-runs ralph.sh, done. Ping me + Spool when ready.

-- Marcus
