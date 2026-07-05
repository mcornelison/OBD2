# BL-017: US-449 sole-writer blocked — live `drive_statistics` dual-write in the `/analyze` AI flow

| Field        | Value                     |
|--------------|---------------------------|
| Severity     | High                      |
| Status       | RESOLVED (RESOLVED 2026-07-04 -- Atlas ruled Option A (harness sole wr...)                    |
| Blocking     | US-449 (AC2/VC2 "sole writer / no dual-write"); cascades to US-450, US-452 (dep US-449) |
| Waiting On   | Atlas architectural ruling (routed via Marcus/PM) |
| Created      | 2026-07-04                |

## Description

US-449 asks to formalize the B-104 server-analytics harness
(`drive_summary_compute.py` + `drive_statistics_compute.py` +
`derived_signals_compute.py` + `server-analytics-batch.timer`) as the **sole
writer** of its owned tables, with **no dual-write path** (AC2, VC2).

During the sole-writer audit I found `drive_statistics` has a **second, live
writer** distinct from the harness:

- **Harness writer (intended authority):**
  `src/server/analytics/drive_statistics_compute.py::compute_drive_statistics`
  — invoked by the on-demand CLI (`recompute_drive_analytics`) + nightly timer.
  Groups by `realtime_data.drive_id == driveId` (Pi-local drive id).
- **Second live writer:**
  `src/server/analytics/basic.py::computeDriveStatistics` (`basic.py:56`, does
  `session.add(DriveStatistic(...))` + `session.commit()` at `basic.py:108/124`)
  — reached in production via `POST /api/v1/analyze`
  (`src/server/api/analyze.py:140`) → `services/analysis.py::runAnalysis`
  → `_buildAnalyticsContext` (`analysis.py:269`) → `computeDriveStatistics`.

Both write the `drive_statistics` table keyed on `summary_id`
(`= drive_summary.id`), **but with different row-selection semantics**:

- Harness: filters raw rows by `realtime_data.drive_id`.
- `basic.py`: filters by the drive's **time window + `source_device`** (reads
  `drive_summary.start_time/end_time/device_id`, `basic.py:62-68`).

So for the same drive the two writers can produce **different** per-parameter
rows, and whichever ran last wins (last-writer-wins divergence).

This also **contradicts a documented claim**: `services/analysis.py` header
(lines 72-75) states *"US-351 (B-104 Step 1b) retires the parallel
drive_statistics trigger + writer + Pi table."* The trigger-seam writer was
retired, but the `/analyze` → `basic.py` write path was **not** — it is still
live.

## Impact

- **US-449 cannot honestly close.** AC2 "the harness is the SOLE writer of its
  owned tables … no dual-write path exists" and VC2 "each persisted-analytics
  table has exactly one writer (the harness); no dual-write path exists" are
  unmet while `basic.py` writes `drive_statistics` via `/analyze`.
- **Cascade:** US-450 (`drive_statistics` re-key, dep US-449) and US-452
  (`statistics` vs `drive_statistics` no-dual-write, dep US-450) sit downstream.
- The **owned-table manifest** (AC1) was deferred: its shape depends on whether
  `drive_statistics` is declared cleanly sole-owned (post-fix) or contested.

## Attempted Solutions

- Delivered the **ruling-independent** half of US-449 as committed progress:
  `tests/server/analytics/test_harness_idempotency.py` proves AC2/AC4
  "re-run = 0 owned-row diffs" (3 tests green, ruff clean, commit `674b063`).
  This makes **no** sole-writer claim, so it is honest under the blocker.
- Did **not** modify `analysis.py` / `basic.py` / `api/analyze.py`: those are
  the load-bearing `/analyze` AI flow, are **outside** US-449's enumerated
  harness scope, and the reconciliation is an architectural decision that
  routes to Atlas per the CLAUDE.md role boundary (Refusal Rule 1 + Rule 3).

## Proposed Resolution

Atlas to rule on how `/analyze` obtains per-parameter stats. Two options:

- **(A) Recommended — make `/analyze` a pure consumer (faithful to F-104).**
  Change `_buildAnalyticsContext` to **read** the harness-written
  `drive_statistics` rows instead of calling the writing
  `computeDriveStatistics`. The harness becomes the true sole writer.
  - *Behavior change to weigh:* if the harness has not yet processed the drive,
    `drive_statistics` is empty → `/analyze` would hit its existing "no data"
    short-circuit instead of computing stats on the fly. Also the harness uses
    `drive_id` filtering vs `basic.py`'s time-window+device filtering, so the
    stats `/analyze` sees would change to the harness definition.
  - Likely its own story (touches `analysis.py`, `basic.py`, and their tests).
- **(B) Keep the dual-write, reconcile explicitly.** Declare one writer
  authoritative for the persisted table and make the other in-memory-only, or
  fold the reconciliation into **US-452** ("no independent dual-write"). Update
  the false "retired the parallel writer" claim in `analysis.py`'s header
  either way.

Once ruled, the follow-up story lands the fix, then US-449's manifest (AC1) +
sole-writer test can be completed and US-449 closed.

## Resolution

[Fill in when resolved] What unblocked the work and when.
