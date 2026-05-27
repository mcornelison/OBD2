---
id: F-076
parent: E-002
status: pending
renamedFrom: B-076
createdAt: 2026-05-27
updatedAt: 2026-05-27
---

# B-076: Server schema normalization epic (V0.28+ -- the CIO 2026-05-12 obd2db review)

| Field | Value |
|---|---|
| Priority | High (P1 for V0.28+; NOT a patch-sprint item) |
| Status | Pending (V0.28+ EPIC -- needs its own ORM-model + sync-mapping + migration plan + a Drive-N re-validation) |
| Category | server / schema / migration |
| Size | XL (multi-table coordinated migration) |
| Related | CIO 2026-05-12 obd2db review note (`offices/tester/inbox/db review fom Mike.txt`); tester 2026-05-12 db-review note (`offices/pm/inbox/2026-05-12-from-tester-db-review-validation-bug-vs-techdebt.md`); BL-016 (US-329 deferred here); B-075 (drive_statistics Approach 2 rides this) |
| Created | 2026-05-12 |

## Description

The CIO's 2026-05-12 obd2db review is a coordinated multi-table schema refactor of the server-side database. Per CIO 2026-05-12 + tester confirmation: this is a **separate V0.28+ epic** -- it does NOT belong in a V0.27.X bug-fix patch sprint (constraint: V0.27.X = bug-fixes only). It needs its own ORM-model rewrite, sync-payload mapping changes (Pi <-> server wire protocol), a migration plan (Alembic chain), and a Drive-N + Drain-N re-validation pass after it lands.

## The migration list (from the CIO note + tester's distillation)

**Renames / FK standardization**:
- `vehicle_info` -> `vehicles`; drop `source_id`; add `display_name`; going forward `vehicles.id == devices.id`
- `drive_summary` -> `drives`; `device_id` -> `vehicle_id` (FK -> `vehicles`)
- Standardize `source_id` -> `vehicle_id` (FK -> `vehicles`) across: `ai_recommendations`, `alert_log`, `calibration_sessions`, `battery_health_log`, `dtc_log`, `profiles`, `realtime_data`, `statistics`
- Drop `source_device` column from: `ai_recommendations`, `alert_log`, `calibration_sessions`, `battery_health_log`, `drive_annotations`, `dtc_log`, `profiles`, `realtime_data`, `statistics`, `drive_summary`(->`drives`)
- `connection_log`: rename `source_id` -> `device_id` (FK -> `devices`); drop `source_device`
- `sync_history`: `device_id` varchar -> int (FK -> `devices`); if a string value must be preserved, add a `devices` row + link by id
- `statistics`: `profile_id` varchar -> int (FK -> `profiles`); reconcile `statistics.drive_id` (bigint) vs `drive_statistics.drive_id` (int) -- pick one type
- `drive_statistics.drive_id`, `drive_annotations.drive_id`: FK -> `drives`
- `devices`: add columns `ip_address`, `os`, `os_version`
- `trend_snapshots`: add `vehicle_id` (FK -> `vehicles`)
- **DROP TABLE `drive_counter`** (SERVER-SIDE ONLY -- this is the deferred US-329 fix). NOTE: the **Pi-side** `drive_counter` SQLite table STAYS -- it mints `nextDriveId` and is the source of truth for drive ids (US-200). Server consumers compute "drives done = N" via `SELECT COUNT(*)` / `SELECT MAX(drive_id) FROM drives`. The Pi stops POSTing the `driveCounter` snapshot (remove `pushDriveCounter` call + `DriveCounterData` from `SyncRequest` -- coordinated two-ended change; `SyncRequest` is `extra="forbid"` so the server must accept-then-ignore the field for one release before the Pi drops it).

**One-time data cleanup as part of the migration**:
- Remove the 3 ghost `drive_summary` rows (id 12/13/14, `drive_id` NULL, `is_real` 0)
- Re-derive the Drive-11 row once the analytics writer is correct (post-US-326)
- Truncate `connection_log` (the idle OBD-reconnect noise -- see B-077)
- Prune `sync_history` ("should only be one sync after a drive" -- see B-078)

## Why this is its own epic, not patch-sprint work

- Touches ~15 tables + the Pi<->server sync payload contract + the ORM models + a migration chain
- Requires a coordinated Pi + server deploy ordering (wire-protocol fields can't be removed one-ended)
- Needs a full Drive-N + Drain-N re-validation after it lands (it touches `realtime_data`, `battery_health_log`, `drive_summary`->`drives` -- the core capture path)
- Per CIO 2026-05-12 + the V0.27.X-is-bug-fixes-only standing rule: schema architecture refactors are V0.28+

## Dependencies / sequencing

- Land AFTER the V0.27 chain is validated + merged to main (so the bug-fixes are stable before the schema churns)
- B-075 (drive_statistics Pi-side writer / Approach 2) naturally rides this epic
- B-077 (connection_log truncate) + B-078 (sync_history prune) overlap with the "one-time data cleanup" step here -- could be folded in or shipped first

## Acceptance Criteria (high-level; full grooming when this becomes a V0.28+ sprint)

- [ ] Migration plan documented (Alembic chain, ordering, rollback)
- [ ] ORM models updated to the new shape
- [ ] Pi<->server sync payload mapping updated (with the accept-then-ignore transition for `driveCounter`)
- [ ] All FK constraints in place + verified
- [ ] One-time data cleanup script (ghost rows, re-derive Drive 11, truncate connection_log, prune sync_history)
- [ ] Drive-N + Drain-N re-validation pass green post-migration
- [ ] `drive_counter` table dropped server-side; consumers compute from `drives`; Pi stops POSTing the snapshot

## Source

- CIO 2026-05-12 obd2db review (`offices/tester/inbox/db review fom Mike.txt`)
- Tester 2026-05-12 db-review note (`offices/pm/inbox/2026-05-12-from-tester-db-review-validation-bug-vs-techdebt.md`) -- bug/tech-debt split + the migration list above
- BL-016 resolution 2026-05-12 (US-329 deferred here)

---

## V0.28 Expansion 2026-05-22 — Coherent Schema-Pass Additions (Atlas + Spool joint flag)

Three additional items surfaced post-V0.27.18 deploy + CIO ECU swap mid-session. Atlas 2026-05-22: "**One coherent V0.28 schema pass touches all three (B-076 + B-107 + B-108 + B-109 + the smells below) — same surface area.**"

### 1. SPEED-PID-per-ECU calibration table

**Trigger**: Spool's 2026-05-22 OBD capability probe + Drive 26 telemetry on new modified-EPROM ECU surfaced **SPEED PID reads ~2× actual ground speed** on new ECU (modified EPROM has different VSS calibration constants). Prior ECU SPEED PID was correctly calibrated (Drive 18 RPM 3937 / SPEED 60 = 3rd-gear math fit). Each modified EPROM may have its own VSS calibration.

**Schema addition** (proposed):

```
CREATE TABLE speed_pid_calibration (
  id INT PRIMARY KEY AUTO_INCREMENT,
  ecu_signature VARCHAR(...) NOT NULL,         -- FK to vehicle_info.ecu_signature (B-108)
  correction_factor DOUBLE NOT NULL,            -- multiplicative; OBD-reported × factor = ground truth
  capture_method ENUM('gps_correlation','gear_math','vendor_spec','default'),
  captured_at_timestamp_utc TIMESTAMP NOT NULL,
  captured_by VARCHAR(...) NULL,                -- e.g., 'cio_gps_correlation_2026-05-22'
  notes TEXT NULL                               -- e.g., 'tire size 205/55R16; speedometer reads true at 60'
);
```

**Use**: analytics queries that aggregate SPEED (`drive_summary.estimated_distance_m` per B-106; future avg-speed / gear-inference) JOIN to this table on `ecu_signature` (via B-108) for the drive's time window and apply the correction factor before integration.

**Default**: factor = 1.0 (assume OEM calibration) until a per-ECU correction is captured.

**Seed**: prior ECU = 1.0 (verified Drive 18 gear math). New ECU = ~0.5 (initial 2× estimate from Drive 26; GPS-correlation refinement on CIO's next drive).

### 2. `drive_summary.drive_id` NULL smell (B-104 Step 1 surface, V0.28 cleanup)

Spool 2026-05-22 flagged: after B-104 Step 1 deploy, **new server-compute drive_summary rows have `drive_id` NULL** (only `source_id` is set; server computes its own row id). Survives functionally because compute paths use `summary_id` to join `drive_statistics`. **Will bite future authors** who assume `drive_summary.drive_id` is meaningful.

**Decision per V0.28 grooming**: either (a) backfill `drive_summary.drive_id` from `source_id` (Pi-assigned drive number) so the column remains semantically meaningful, OR (b) drop the column server-side entirely (rely on `summary_id` + `source_id`). Atlas + Spool flagged; PM lean undecided at filing time.

### 3. `drive_statistics.drive_id = summary_id` confusion

Spool 2026-05-22 flagged: `drive_statistics.drive_id` is actually `drive_summary.id` (server PK), NOT the Pi-assigned `drive_id`. Naming is misleading.

**Decision per V0.28 grooming**: rename column to `summary_id` (FK to `drive_summary.id`) for clarity. Touches B-104 Step 1 compute paths + any consumers; coordinated rename via Alembic migration.

### V0.28 schema-pass coordination summary

The V0.28 schema-normalization sprint should touch all of:

| Sub-item | Source | New surface? |
|---|---|---|
| Original 12 migration steps (table renames, FK standardization) | CIO 2026-05-12 obd2db review | -- |
| Ghost-row cleanup + Drive-11 re-derive + connection_log/sync_history prune | CIO 2026-05-12 + B-077/B-078 | -- |
| **B-107 DriveDetector dual-attribution + tripwire** | Atlas 2026-05-22 + V0.27.18 IRL drill | YES (`data_quality='attribution_anomaly'` enum addition) |
| **B-108 `vehicle_info.ecu_signature`** | Atlas + Spool 2026-05-22 | YES (new columns + manual-stamp CLI) |
| **B-109 Mode 02 freeze-frame storage** | Atlas + Spool 2026-05-22 | YES (new `dtc_freeze_frame` table) |
| **SPEED-PID-per-ECU calibration table** (this section) | Spool 2026-05-22 ECU swap | YES (new `speed_pid_calibration` table) |
| **drive_summary.drive_id NULL cleanup** | Spool 2026-05-22 | YES (decision + migration) |
| **drive_statistics.drive_id → summary_id rename** | Spool 2026-05-22 | YES (column rename) |

V0.28 PRD grooming opens post `/chain-validated`. Expected V0.28.0 sprint scope = first slice of this epic (probably B-107 tripwire + B-108 ECU lineage + speed-pid calibration as MVP slice); rest of B-076 follows in V0.28.X sub-sprints.
