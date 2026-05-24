# I-028: V0.27.6 US-324 drive_statistics ship incomplete -- Pi-side table missing + server writer not firing

| Field | Value |
|---|---|
| Severity | High (P1, L) |
| Status | Open (V0.27.7 candidate -- Spool Story Z) |
| Category | sync / analytics / migration |
| Found In | Pi-side schema (no `drive_statistics` table) + server-side `_ensureDriveStatistics` (V0.27.6 US-324) |
| Found By | Spool 2026-05-12 Drive 11 validation |
| Related | V0.27.6 US-324; V0.27.4 US-315 + IN_SCOPE_TABLES; V0.27.3 US-310 + US-317 pattern |
| Created | 2026-05-12 |

## Description

V0.27.6 US-324 built `_ensureDriveStatistics` server-side writer per the US-317 Ollama-decouple pattern. Ralph's progress.txt explicitly noted: "models.py NOT touched -- the DriveStatistic ORM model already exists + matches schema". But empirically:

**Pi-side**: `Error: no such table: drive_statistics`. Pi schema doesn't have the table. sync_log.IN_SCOPE_TABLES expects to push drive_statistics from Pi to server, but Pi has nothing to push.

**Server-side**: 0 rows in drive_statistics for Drive 11 (and all prior drives). Either `_ensureDriveStatistics` didn't fire OR it fired but couldn't write.

## Two-part scope (Spool's framing)

**Part 1 — Pi-side migration**: Ship `drive_statistics` table on Pi. Migration in `src/pi/obdii/database_schema.py` OR new migration helper. Idempotent CREATE TABLE IF NOT EXISTS for existing Pi DBs.

**Part 2 — Writer wiring (architectural decision)**: Spool's spec says "Pi-side has one row per parameter per drive in drive_statistics... Sync to server populates server-side rows tied to new drive_summary." That's **Pi-side computed at drive_end** (Approach 2 from US-324 grooming, NOT the Approach 1 Ralph implemented).

V0.27.6 US-324 went with Approach 1 (server-side computed at sync-time). Spool now wants Approach 2 (Pi-side computed). Possibilities:

- (a) Architectural reversal: re-implement as Pi-side writer (consumes realtime_data locally; sync pushes computed rows)
- (b) Keep Approach 1: investigate WHY server-side `_ensureDriveStatistics` didn't fire for Drive 11
- (c) Hybrid: Pi-side migration ships table for sync support; server-side writer stays; investigate why server didn't fire

## Pre-flight (Ralph determines actual architecture)

- rg `drive_statistics` src/pi/ tests/pi/ -- confirm no Pi-side writer code exists currently
- Check `src/pi/obdii/database_schema.py` for drive_statistics SCHEMA -- absent confirms Part 1 missing
- Server journalctl for `_ensureDriveStatistics` log lines around Drive 11 sync (2026-05-12 01:10-01:35Z) -- absent means trigger didn't fire; present means it fired but didn't write

## Acceptance Criteria (L story; CIO pmSignOff required)

- [ ] Pre-flight audit identifies architecture: Approach 1 (server-side) vs Approach 2 (Pi-side) vs hybrid; PM approves direction before scope finalization
- [ ] Pi-side `drive_statistics` table exists (idempotent CREATE TABLE IF NOT EXISTS in database_schema.py)
- [ ] Writer fires at drive_end (or sync-time, per chosen architecture)
- [ ] After new drive: per-parameter rows present (one per `parameter_name` per `drive_id`) with min/max/avg/std/sample_count populated from realtime_data
- [ ] Sync propagates Pi-side rows to server (Approach 2) OR server-side computes from synced realtime_data (Approach 1)
- [ ] Drives 11 (+ optionally 3/4/5 backfill) populated post-fix
- [ ] Bench-harness integration test: simulate drive -> verify per-parameter aggregates in BOTH Pi DB and server DB

## Why P1 + L

Without drive_statistics, calibration cannot ever produce proposals — `proposeCalibration()` joins through this table. Backbone of the analytics tier. Also: architectural decision needed (Approach 1 vs 2) means more files touched than original US-324 scope.

## Source

- Spool 2026-05-12 Drive 11 validation note (Story Z, "P1 + L")
- V0.27.6 US-324 ship note (Ralph progress.txt) -- server-side writer + new TD-050 for NULL-start_time NULL-guard
- TD-050 (V0.27.6) -- `computeDriveStatistics` crashes on NULL start_time via other caller; may interact
