# B-075: drive_statistics Pi-side writer + sync (Spool's Approach 2 -- V0.28+ feature)

| Field | Value |
|---|---|
| Priority | Medium (P2 for V0.28+ feature sprint) |
| Status | Pending (V0.28+ feature sprint candidate; deferred per V0.27.X bug-fix-only rule) |
| Category | analytics / sync architecture |
| Size | L (architectural reversal) |
| Related PRD | None |
| Dependencies | V0.27 chain merged to main (`/chain-validated`); B-074 (MAP PID, sibling V0.28 candidate) |
| Created | 2026-05-12 |

## Description

Spool's 2026-05-12 Story Z spec frame says: "Pi-side has one row per parameter per drive in drive_statistics with min/max/avg/std/sample_count populated from realtime_data... Sync to server populates server-side drive_statistics rows tied to the new drive_summary." That is **full Approach 2** (Pi computes at drive_end, Pi-side table populated, sync pushes those rows, server stops computing and ingests Pi-computed rows).

V0.27.7 US-328 shipped **Option C (hybrid)** instead per BL-015 resolution: Pi-side `CREATE TABLE IF NOT EXISTS` only, no writer, no sync change. Server-side keeps Approach 1 (server computes from synced realtime_data). The Pi-side table exists but stays empty.

B-075 is the V0.28+ enhancement that closes that gap: ship the Pi-side writer + add `drive_statistics` to the Pi sync registry so per-parameter rows compute Pi-side at drive_end and flow to the server (server stops computing).

## Why V0.28+ (not V0.27.X)

- Architectural reversal -- Approach 1 (server-computed) -> Approach 2 (Pi-computed + sync) is a redesign, not a bug fix
- V0.27.X = bug-fixes-only standing rule (`feedback_pm_patch_version_bug_fix_sprint_pattern.md`)
- ~6-8 files touched: Pi writer (new module), database_schema.py (new INSERT path), sync_log.py (add to `DELTA_SYNC_TABLES` + `PK_COLUMN`), server-side `_ensureDriveStatistics` retired or behind a feature flag, ingestion path on server-side sync handler, integration tests
- The `_renamePkToId` + `source_id` sync mapping + the server-side `drive_statistics.drive_id = DriveSummary.id` keying all need re-thinking: Pi sends Pi-local drive_id, server must remap

## Why we may not even need it

US-326 (V0.27.7) very likely cured the server-side "0 rows for Drive 11" symptom. Pre-US-326, `_ensureDriveSummary` raised `IntegrityError` -> `_writeDriveAnalytics` transaction rolled back -> drive_statistics never committed. Post-US-326, the transaction commits and Approach 1 produces rows. If Drive 12 validates this empirically and calibration runs cleanly, the user-facing motivation for Approach 2 (Spool's spec) narrows to: (a) symmetry with drive_summary writer location, (b) less server-side compute on sync, (c) data integrity if server-side sync is delayed. Worth re-evaluating after V0.27 chain validation completes.

## Scope estimate (L)

1. New `src/pi/analytics/drive_statistics_writer.py` -- computes per-parameter aggregates from `realtime_data` at drive_end; mirrors server-side `computeDriveStatistics` shape
2. Wire writer into drive_end handler (orchestrator or DriveDetector terminal callback)
3. New idempotent migration: ALTER TABLE drive_statistics if Pi-side V0.27.7 table differs from final V0.28 shape
4. Add `drive_statistics` to `src/pi/data/sync_log.DELTA_SYNC_TABLES` + `PK_COLUMN`
5. Server-side: `_ensureDriveStatistics` retired or behind feature-flag (no longer computes from realtime_data on sync); server-side sync handler ingests Pi-computed rows
6. Server-side: remap Pi `drive_id` -> server `DriveSummary.id` on ingestion (mirror of `_ensureDriveSummary` lookup pattern from US-326)
7. Integration tests (Pi-side writer + sync round-trip + server ingestion)

## Acceptance Criteria (when groomed for V0.28+)

- [ ] Pre-flight: validate V0.27 chain merged to main + Drive 12 produced server-side rows via Approach 1 (confirm no urgency)
- [ ] Pi-side writer fires at drive_end; per-parameter rows populated Pi-side
- [ ] Sync round-trip: Pi writes -> Pi-side rows -> sync delta -> server-side rows
- [ ] Server-side `_ensureDriveStatistics` (current Approach 1 writer) retired or feature-flagged off
- [ ] No regression on calibration CLI (`scripts/report.py --calibrate`) -- still reads from `drive_statistics`
- [ ] Bench-harness e2e test covers Pi-compute -> sync -> server-ingest path

## Source

- Spool 2026-05-12 inbox note `2026-05-12-from-spool-drive-11-v027-chain-validation-and-v0276-failures.md` (Story Z spec frame)
- BL-015 resolution 2026-05-12 (CIO Option C; deferred Approach 2 to B-075)
- V0.27.7 US-328 shipped Option C hybrid
