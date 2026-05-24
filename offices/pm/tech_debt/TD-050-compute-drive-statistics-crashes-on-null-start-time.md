# TD-050: computeDriveStatistics crashes on a drive_summary row with NULL start_time

| Field        | Value                     |
|--------------|---------------------------|
| Priority     | Low                       |
| Status       | Open                      |
| Category     | code                      |
| Affected     | `src/server/analytics/basic.py:computeDriveStatistics` (`_collectReadings`); reached via `src/server/services/analysis.py:_buildAnalyticsContext` -> `runAnalysis` |
| Introduced   | Pre-existing since US-158 (Sprint 9) -- never exercised because no test/path passed a NULL-start_time drive until US-324 surfaced it |
| Created      | 2026-05-11 (during US-324 / I-024) |

## Description

`computeDriveStatistics(session, driveId)` builds its realtime_data window
filter in `_collectReadings` with `RealtimeData.timestamp >= drive.start_time`
(and `<= drive.end_time` when `end_time` is not None). When the
`drive_summary` row's `start_time` is `None` -- which happens for a
Pi-sync-only stub row, or a `drive_start`/`drive_end` pair that captured zero
realtime readings -- SQLAlchemy raises:

```
sqlalchemy.exc.ArgumentError: Only '=', '!=', 'is_()', 'is_not()',
'is_distinct_from()', 'is_not_distinct_from()' operators can be used with
None/True/False
```

The new US-324 writer (`analysis._ensureDriveStatistics`) guards this case
locally (short-circuits to 0 rows when `drive.start_time is None`), so the
sync write path is safe. But the **other** caller --
`runAnalysis -> _buildAnalyticsContext -> computeDriveStatistics(drive.id)` --
is unguarded. If `enqueueAutoAnalysisForSync` writes a stub `drive_summary`
row (no realtime data) and Ollama is up, `_safeRunAnalysis` is scheduled for
that drive, `runAnalysis` calls `_buildAnalyticsContext`, and the
ArgumentError is raised -- then caught by `_safeRunAnalysis`'s blanket
`except`, logged as ERROR, and swallowed. So it's noisy, not fatal.

## Why It Was Accepted

US-324's scope fence only covered `src/server/services/analysis.py`,
`src/server/db/models.py`, the new test, and `scripts/backfill_drive_statistics.py`.
`src/server/analytics/basic.py` was explicitly out of scope (`doNotTouch`
implied -- not in `filesToTouch`), so the guard was added at the
`_ensureDriveStatistics` call site instead of fixing the root cause in
`computeDriveStatistics`. The `runAnalysis` path is unchanged by US-324 and
was already exposed to this; documenting rather than scope-creeping.

## Risk If Not Addressed

Low. Likelihood: only when a drive completes with zero realtime readings
(OBD never connected mid-drive) **and** Ollama is reachable at sync time.
Impact: one ERROR log line per such drive in the server journal; the AI
analysis for that drive silently doesn't run (which is the right outcome
anyway -- there's nothing to analyze). No data corruption.

## Remediation Plan

In `src/server/analytics/basic.py:_collectReadings`, return an empty bucket
dict early when `drive.start_time is None` (and likewise treat a NULL
`device_id` as "no rows"). Then `_ensureDriveStatistics`'s local guard
becomes redundant and can be removed, leaving one source of truth. Also
consider having `_buildAnalyticsContext` short-circuit to "no data" when the
drive's `start_time` is NULL, mirroring the existing `if not stats: return None`
branch. ~10 LOC + a regression test. Bundle into the next server-analytics
bug-fix sprint; no B- item filed yet.
