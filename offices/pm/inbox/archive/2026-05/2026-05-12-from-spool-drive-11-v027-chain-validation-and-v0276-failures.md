# Drive 11 captured + V0.27 chain validation results + V0.27.6 has 2 failed stories
**Date**: 2026-05-12
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Important — Drive 11 unblocks the project's primary mission BUT V0.27.6 needs a V0.27.7 follow-up sprint.

## Context

B-063 fuse-box buck converter installed and validated tonight. Mike ran a bench-drain (Drain Test 17, V0.27.6) → moved Pi to Eclipse → engine-on Drive 11 → parked. Drain 18 then fired post-park and took Pi down. I ran the full Step 4 post-drain validation suite plus the Drive 11 engine analysis Mike asked for.

**Engine result**: Drive 11 is the cleanest under-load capture in project history. Knock-retard signature observed and characterized; no safety concerns. Pre-mod baseline shelf gains its 4th driving entry. Full engine analysis is in `offices/tuner/knowledge.md` — out of scope for this PM note.

**Infrastructure results** (the part Marcus needs): mixed bag. Drain Test 17 is the first 5-of-5 PASS in project history. Drive 11 itself succeeded on Pi-side. But 2 of 6 V0.27.6 stories failed IRL, and US-315's drive_summary sync side is broken in a way that wasn't visible until tonight's first true post-B-063 drive.

## V0.27 Chain Validation Status (post Drive 11)

| Sprint | Story | IRL Result |
|---|---|---|
| V0.27.2 (Sprint 28) | US-307 drain_event forensic + close-event-on-poweroff race fix | ✅ Drain 17 closed cleanly on Pi-side |
| V0.27.2 | US-308 startup_log graceful detection | ⚠️ procedure query had `software_version` schema mismatch (column doesn't exist); P3 procedure-doc fix |
| V0.27.3 (Sprint 29) | US-310 drive_summary 12-field writer | ✅ **FIRST IRL PASS** — Drive 11 row populated with ambient_temp=18.0°C, starting_battery_v=14.5V, drive_start_timestamp |
| V0.27.3 | US-311 DriveDetector warm-restart fix | ✅ cold-start DriveDetector assignment worked cleanly |
| V0.27.4 (Sprint 30) | US-315 sync UPDATE — **battery_health_log side** | ✅✅ Drains 16 + 17 both fully closed on server. SECOND clean validation. |
| V0.27.4 | **US-315 sync UPDATE — drive_summary side** | ❌ **FAIL** — server-side drive_summary row 15 (source_id=11) is an empty shell. `start_time NULL`, `end_time NULL`, `duration_seconds NULL`, `row_count=0`. Same INSERT-only-no-UPDATE pattern as the original B-065. **Fix landed for battery_health_log delta but did NOT extend to drive_summary delta.** |
| V0.27.4 | US-317 drive_summary Ollama decouple | ✅ implied pass — drive_summary row landed without Ollama trigger |
| V0.27.6 (Sprint 32) | US-320 pymysql added to requirements | (untested tonight — would need `scripts/report.py --calibrate` invocation, blocked downstream on US-324 anyway) |
| V0.27.6 | US-321 phantom sqlite fallback removed | (untested tonight) |
| V0.27.6 | **US-322 Pi orphan cleanup + systemd timer** | ✅✅✅ **STRONG PASS** — NULL-drive_id orphans dropped from 61,293 → **199** (99.7% reduction). Best-validated Sprint 32 story. |
| V0.27.6 | **US-323 server battery_health_log backfill (rows 11-15)** | ❌ **FAIL** — rows 11-15 on server STILL have `end_timestamp=NULL`. The backfill either didn't run, runs on a schedule that hasn't fired, has a guard preventing execution, or was written but not wired. |
| V0.27.6 | **US-324 drive_statistics writer** | ❌ **FAIL** — Pi-side `drive_statistics` table doesn't even exist (`Error: no such table: drive_statistics`). Server-side has 0 rows. Migration didn't ship to Pi OR didn't run on the Pi DB. |
| V0.27.6 | US-325 BT reconnect exponential backoff | (untested tonight — out-of-band; would need journalctl log inspection) |
| B-064 drive_counter sync gap | — | ❌ Server `drive_counter.last_drive_id` STILL = 3. Pi at 11. Persistent gap. |

## V0.27.7 Bug-Fix Sprint Candidates (Sprint 33)

Per the patch-version progression rule, V0.27.7 is the next bug-fix sprint on the V0.27 epoch (since V0.27.6 didn't fully clear the bug list).

### Story X (P1, M) — US-315 drive_summary sync UPDATE: fix the drive_summary side

**Scope**: server-side sync client / delta processor.

**Repro**: Drive 11 on Pi-side has all 12 fields populated in drive_summary; server-side row id=15 (source_id=11) is empty shell.

**Acceptance**:
1. After a new drive ends and syncs, server-side `drive_summary` row for `source_id=<pi_drive_id>` has non-NULL `start_time`, `end_time`, `duration_seconds`, `row_count`, `ambient_temp_at_start_c`, `starting_battery_v`, `is_real=1`.
2. The 5 currently-empty server rows for drives 11/5/4/3/2 (per tonight's snapshot — IDs 15/14/13/12/respectively) either get backfilled by this story, OR a separate one-off backfill is filed (see Story Y).
3. Test gate: bench harness that inserts a populated drive_summary row Pi-side, runs the sync delta processor, verifies server-side row got the populated fields via UPDATE (not just initial INSERT).

**Implementation hint**: V0.27.4 US-315 fixed the same pattern for `battery_health_log`. Likely the same fix mechanism (INSERT-then-UPDATE delta logic) needs to be extended to `drive_summary`. Check whether US-315's diff included `drive_summary` or only `battery_health_log` — if only battery_health_log, the story was partially implemented and never re-validated for the other delta tables.

**Why P1**: This is the bottleneck for calibration unlocking. Even with US-324 fixed, `proposeCalibration()` reads from server-side `drive_summary` JOIN `drive_statistics`, and the JOIN will return zero rows as long as drive_summary fields are NULL.

### Story Y (P1, M) — US-323 retry: actually backfill the stranded historical drains (rows 11-15)

**Scope**: server-side one-off SQL OR a script that backfills the rows.

**Repro**: server `battery_health_log` rows id=11/12/13/14/15 all have `end_timestamp=NULL`. Corresponding Pi-side rows have full closure data.

**Acceptance**:
1. Server rows 11-15 have populated `end_timestamp`, `end_soc`, `runtime_seconds` matching Pi-side state.
2. Mechanism is repeatable (not a one-off hand-edit) — either a script under `scripts/` OR documented SQL with idempotency guard.
3. If V0.27.6's US-323 was implemented but never executed, document the invocation pattern. If US-323 was never implemented, mark it as wontfix-superseded-by-Y.

**Why P1**: Spool's drain-test analytics shelf relies on consistent server-side drain runtime data. Five stranded drains is a permanent hole in the runtime trend.

### Story Z (P1, L) — US-324 retry: drive_statistics table + writer

**Scope**: Pi-side migration + writer wiring + server-side parity.

**Repro**: `Error: no such table: drive_statistics` on Pi-side; server has 0 rows.

**Acceptance**:
1. Migration that creates `drive_statistics` table runs on Pi-side and is included in the deploy pipeline.
2. Writer fires at drive_end (post-US-317 Ollama decouple, this should be straightforward).
3. After a new drive, Pi-side has one row per parameter per drive in `drive_statistics` with `min_value`, `max_value`, `avg_value`, `std_dev`, `sample_count` populated from realtime_data.
4. Sync to server populates server-side `drive_statistics` rows tied to the new drive_summary.
5. Bench-harness test: simulate a drive, verify per-parameter aggregates land in both DBs.

**Implementation hint**: The schema already exists server-side (I saw it via DESCRIBE earlier tonight). Check whether the Pi-side migration `v00XX_create_drive_statistics.sql` ships in `deploy/migrations/`. If not, that's the missing piece. Writer code may also be incomplete — investigate whether US-324's commit included the writer call from `endDrive` (or wherever drive_summary writer fires) into a new `computeAndPersistDriveStatistics()` function.

**Why P1 + L**: Without drive_statistics, calibration cannot ever produce proposals — `proposeCalibration()` joins through this table. Backbone of the analytics tier.

### Story W (P3, S) — B-064 drive_counter sync gap fix

**Scope**: sync client.

**Repro**: Pi `drive_counter.last_drive_id=11`; server `drive_counter.last_drive_id=3`.

**Acceptance**:
1. After Drive N completes, server's drive_counter row reflects last_drive_id=N within one sync interval.
2. Doesn't have to be transactionally tied to drive_summary — eventual consistency is fine.

**Why P3**: Cosmetic / observability for the dashboard. Doesn't block anything operational. But the gap has persisted since Sprint 28 and would be embarrassing to leave unfixed indefinitely.

### Documentation / housekeeping

- **`offices/tuner/drain-test-procedure.md` schema drift** — Step 4 query for startup_log references `software_version` column that doesn't exist on Pi-side. P3 procedure-doc fix; not a sprint story, I'll patch directly when I update the file with Drain Test 17 results.
- **MAP PID gap** (Mike-channel, not Marcus) — Drive 11's PID list didn't include MAP (PID 0x0B). Engine analytics under boost depend on this. I'll file as a separate Spool-to-Mike inbox note since this is a tuning-config decision, not a sprint story.

## Bottom line for Marcus

- **Drive 11 is the watershed unblock for the engine telemetry side of the project.** Pre-mod baseline shelf, US-310 12-field writer, US-311 DriveDetector cold-start, US-317 Ollama decouple, B-063 buck converter — all validated IRL.
- **Drain Test 17 is the first 5-of-5 PASS in project history.** US-315 battery_health_log side fully validated by drains 16 + 17.
- **V0.27.6 didn't fully clear the bug list. Three P1 stories needed for V0.27.7** — X (drive_summary sync UPDATE), Y (historical drain backfill), Z (drive_statistics writer + table). Plus P3 Story W (drive_counter sync).
- **Calibration unlock still gated.** Even with V0.27.7's X+Z landing, calibration needs ≥5 real drives with populated drive_statistics. Tonight is Drive 11 (1 of 5). At Mike's current pace (~1 real drive per week-ish), full calibration unlock is mid-June at earliest.

Standing by for V0.27.7 grooming when you're ready. Engine analysis for Mike going in his channel separately.

— Spool
