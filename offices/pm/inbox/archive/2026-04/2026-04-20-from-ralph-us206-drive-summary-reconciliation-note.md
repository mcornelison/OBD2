# US-206 — drive_summary dual-writer reconciliation note

**Date**: 2026-04-20
**From**: Rex (Ralph)
**To**: Marcus (PM)
**Priority**: Informational (Sprint 16 grooming input — not a blocker for US-206 ship)

## Context

US-206 (Spool Data v2 Story 4 — drive-metadata capture) specified:

> src/server/models/__init__.py (DriveSummary SQLAlchemy model mirroring Pi schema; drive_id BIGINT PK, metadata columns, unique(source_device, drive_id))

The existing server model `src/server/db/models.py::DriveSummary` is
already active: analytics path writers (`services/analysis._ensureDriveSummary`
keyed by `(device_id, start_time)`) and readers (`reports/drive_report`,
`analytics/calibration` via `is_real=True` filter, `analytics/advanced`
via `DriveStatistic` join on `DriveSummary.id`) all depend on its current
shape.

Spool's original gap note (2026-04-19) explicitly anticipated this:

> Story 4: Drive-metadata capture … New `drive_summary` columns or fields.
> (S size if `drive_summary` already exists; it does on server.)

## Decision I made to ship US-206

Rather than (a) rename the Pi table to avoid the collision — which violates
the spec's explicit "drive_summary" name — or (b) rename / replace the
existing analytics DriveSummary — which touches analytics code outside
US-206 scope — I **extended** the existing server `DriveSummary` model
with nullable US-206 columns + `UNIQUE(source_device, source_id)` for
the Pi-sync path. This keeps both writers happy without touching the
analytics code:

- **Analytics writer** (pre-existing): inserts/finds rows keyed by
  `(device_id, start_time)`; leaves all US-206 columns NULL.
- **Pi-sync writer** (new): upserts rows keyed by `(source_device,
  source_id)` where `source_id = drive_id`; leaves
  `start_time`/`duration_seconds`/`row_count`/`is_real` NULL.

The two keys never collide because SQL standard treats NULL as distinct
in UNIQUE constraints. To enable the Pi path, `device_id`, `start_time`,
and `is_real` had to be made nullable — a silent widening that's
backward-compatible with existing analytics writers (they still insert
populated values).

## Why this matters to you

**Two rows per drive** until a reconciliation story lands:

1. Analytics writer creates one row with `device_id`, `start_time`,
   `end_time`, `duration_seconds`, `is_real`, `row_count`.
2. Pi-sync writer creates another row with `source_device`, `source_id`,
   `drive_start_timestamp`, ambient/battery/baro, `drive_id`.

Downstream consumers that need the unified view (e.g., a CIO-facing
report that shows *"drive N: started at T, ambient was X°C, lasted
Y min"*) must currently UNION the two row families by `(device_id ==
source_device) AND (drive_id == drive_id from Pi-sync)` — brittle and
requires the drive_id to have propagated to analytics (it hasn't:
`_ensureDriveSummary` doesn't know about drive_id).

## Proposed Sprint 16 reconciliation story

**Story intent**: merge the two writer paths into one row per drive.

**Options**:

1. **Pi writes first, analytics updates.** Pi-sync creates the row with
   `drive_id` + `source_device` + metadata. Analytics updates the
   same row (found via `(source_device, drive_id)`) with
   `start_time`/`end_time`/etc. Requires `_ensureDriveSummary` to
   know the drive's source_device and drive_id at analytics-run
   time — which it does (server has been receiving drive_id via
   sync since US-200).

2. **Analytics writes first, Pi upserts.** Analytics creates a stub
   row; Pi-sync upsert fills in metadata. Same end shape, different
   ownership — weaker than option 1 because the metadata is
   drive-start-only and analytics runs only on drive-end.

3. **Separate tables entirely.** Rename existing analytics table to
   `drive_stats` or `drive_window`; keep `drive_summary` for the
   Pi-synced metadata. Matches the original spec most literally
   but requires touching all analytics consumers (calibration,
   reports, advanced). Largest scope.

My recommendation: **Option 1**, sized M. Clean single source of
truth per drive; leverages the drive_id propagation already shipped
in US-200; smallest analytics-code touch.

## Current state (what US-206 ships)

- Pi `drive_summary` table: drive_id PK + 3 metadata columns + timestamp +
  data_source.  `ensureDriveSummaryTable` migration idempotent via
  `ObdDatabase.initialize()`.
- `SummaryRecorder.captureDriveStart(driveId, snapshot, fromState)`:
  cold-start ambient rule, upsert-by-drive_id, no new ECU polls.
- `ObdDataLogger.getLatestReadings()`: thread-safe snapshot API; no
  new polls.
- `DriveDetector._startDrive → _captureDriveStartSummary()`: recorder
  fires after drive_id is minted; failures logged and swallowed.
- Server `DriveSummary` model extended with US-206 columns; registered
  in `sync.py::_TABLE_REGISTRY`; Pi sync via `PK_COLUMN['drive_summary']
  = 'drive_id'`.
- Config flag `pi.driveSummary.enabled` (default true) for opt-out.
- 51 new tests, all green. Fast suite 2755 → 2806 (+51), 0 regressions.

## Not addressed in US-206 (reconciliation story candidates)

- `_ensureDriveSummary` does not consult `source_device` / `source_id`.
- `DriveStatistic.drive_id` points at `DriveSummary.id` (server PK),
  not the Pi `drive_id`. A future query wanting per-drive stats +
  metadata needs a 3-way join until reconciliation lands.
- `is_real=True` filter in calibration / advanced analytics continues
  to exclude Pi-synced rows (is_real is NULL for them); calibration
  baselines still only see analytics-created rows.

— Rex
