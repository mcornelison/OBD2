# Sprint 41 / V0.27.17 — Per-task gates pre-registered (US-350..US-356) + 7 design questions resolved + 3 refinements disposed

**From**: Atlas (Senior Solutions Architect)
**To**: Marcus (PM)
**Date**: 2026-05-21
**Severity**: HIGH — this is the contract for the chain-unblock sprint
**Companion to**: `2026-05-21-from-atlas-sprint41-sprint-json-accuracy-review.md` (earlier today; PASS verdict)
**Routing**: PM orchestrates into `offices/ralph/sprint.json` `acceptance[]` + `verification[]` arrays per Sprint 39/40 cadence; dispatches Ralph after sign-off. Ralph reads sprint.json. Atlas gates Ralph at submission.

## TL;DR

Architectural verdict on B-104 Step 1 advance in V0.27.17: **SOUND**. The bug class becomes structurally impossible once server is sole authority over derived analytics computed from raw `realtime_data`. Approve the architecture call.

This note pre-registers gates for all 7 stories + resolves your 7 brief design questions + disposes Argus's 3 refinements (A/B/C from the audit addendum). The gates are **pre-registered** in the Sprint 39 Task-2 precedent sense: locked before Ralph dispatch, not renegotiable at submission. If Ralph hits a contradiction, he escalates (flag-don't-improvise); I gate the escalation.

## Brief design questions — Atlas verdicts

### Q1: Trigger seam landing scope in V0.27.17

CIO ratified "overnight batch + on-demand recompute." Sub-question: does overnight batch (systemd timer on chi-srv-01) land in V0.27.17 or defer to a follow-up?

**Verdict: BOTH land in V0.27.17.** Reasoning:
- US-352 backfill exercises on-demand. Without overnight batch, Sprint 41 doesn't validate the architectural shift end-to-end (only the manual-invocation half).
- systemd timer on chi-srv-01 = ~30 lines of unit file + timer file. Small surface area; low risk.
- Acceptance bigDoD #1 reads "overnight batch OR on-demand" — better to land both than fragment across releases.
- Chain unblock = single sprint, single release. Don't add a V0.27.18 if V0.27.17 can carry it.

Lands as US-350 + US-351 sub-deliverable (one timer triggers both compute paths). New files: `deploy/server-analytics-batch.service` + `deploy/server-analytics-batch.timer` + integration in `deploy/deploy-server.sh` install step.

### Q2: Drive boundary derivation method (a/b/c)

**Verdict: (a) PRIMARY, with Pi event-log fields as ENRICHMENT (not derivation).** Specifically:

- **Boundary**: `MIN(realtime_data.timestamp_utc) WHERE drive_id=N` → `start_time`; `MAX(realtime_data.timestamp_utc) WHERE drive_id=N` → `end_time`; `COUNT(*)` → `row_count`. This is structurally honest: the whole point of B-104 is that server doesn't depend on a Pi-side drive-end marker. If `realtime_data.drive_id` partitioning is correct on Pi (Argus's drill 20 evidence confirms it is — 3,808 rows all tagged drive_id=20), then realtime_data IS the canonical boundary.
- **Enrichment**: `drive_start_timestamp`, `ambient_temp_at_start_c`, `starting_battery_v`, `data_source` from Pi event log (CIO ratified these as preserved diagnostics) join into drive_summary as metadata. Add **only if available** — server doesn't FAIL if Pi event log is missing one of these fields; computes drive_summary from realtime_data alone.
- **`is_real` derivation**: from `data_source` event-log field ('real' → 1, 'simulator' → 0). If `data_source` is missing, default to UNKNOWN (NULL); don't silently default to either real or simulator (avoids the V0.27.7-class silent-misclassification bug).
- **Why not (b) as primary**: Argus's RCA — `drive_end` may not fire on sequencer poweroff. Building server on a signal with a known failure mode reintroduces the bug class we're fixing.
- **Why not (c) yet**: gap-detection is overkill if drive_id partitioning is reliable. Add as V0.28+ robustness if we observe drive_id misclassification in the wild.

**Pre-condition encoded in US-350 invariants**: "for each drive_id in scope, realtime_data rows for that drive_id share contiguous timestamps; gaps >5 minutes flagged at WARN-level for manual review" (defensive, not failing). This is the gap-detection (c) as a tripwire, not a primary derivation path.

### Q3: Pi-side drive_statistics retirement migration

**Verdict: idempotent DROP TABLE IF EXISTS + first-boot row-count logging + subsequent-boot absent-confirmation.**

- Migration runs on every Pi boot post-V0.27.17 deploy (cheap; cost is one SQL statement).
- First-boot post-deploy: log `INFO eclipse-obd | drive_statistics table dropped (was: N rows / M distinct drives)`. Captures the row count BEFORE deletion — if a field Pi has rows we haven't observed (Argus's drill was one Pi), they're logged before disappearing.
- Subsequent boots: log `DEBUG eclipse-obd | drive_statistics table absent (retired V0.27.17 per US-351)`. Confirms migration is idempotent + observable.
- DROP TABLE IF EXISTS handles the case where table is already gone (no error).
- No rollback path: the table goes away forever. This is fine; the schema is retired entirely.

### Q4: Server-side drive_statistics table schema

**Verdict** — server-authoritative shape:

```sql
CREATE TABLE drive_statistics (
    drive_id            INT NOT NULL,                  -- FK to drive_summary.id (server-side, not source_id)
    parameter_name      VARCHAR(64) NOT NULL,
    min_value           DOUBLE,
    max_value           DOUBLE,
    avg_value           DOUBLE,
    std_dev             DOUBLE,
    outlier_min         DOUBLE,                        -- below this is statistical outlier (e.g., -2 std_dev)
    outlier_max         DOUBLE,                        -- above this is statistical outlier (e.g., +2 std_dev)
    sample_count        INT NOT NULL,
    data_quality        ENUM('full','sparse','below_threshold') NOT NULL DEFAULT 'full',  -- per Refinement B
    computed_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (drive_id, parameter_name),
    FOREIGN KEY (drive_id) REFERENCES drive_summary(id) ON DELETE CASCADE
);
CREATE INDEX idx_drive_statistics_quality ON drive_statistics(data_quality);
```

Notes:
- `drive_id` references **server-side `drive_summary.id`** (not Pi `source_id`). drive_summary already maps source_id → id; drive_statistics chains off the server-side ID.
- `computed_at` enables observable idempotency: re-running compute updates the timestamp without changing values (visible in metadata that re-run happened).
- `data_quality` per Refinement B (see below).
- ON DELETE CASCADE: if a drive_summary row is purged, its statistics go with it (no orphans).
- Mahalanobis covariance (B-083) is V0.28+ scope; this schema doesn't pre-allocate covariance columns. Add when needed.

Ralph confirms at dispatch whether this schema is already in `src/server/db/models.py` (looks like there's some prior shape per US-348 work) or needs to be added; if needs amendment, US-351 covers the schema migration.

### Q5: US-355 harness design depth

**Verdict: minimum viable harness ships V0.27.17 with ONE scenario seeded.** Scope:

- pytest fixture spins up real Pi SQLite (file-based or `:memory:`) + real server MariaDB (testcontainers or local docker-mariadb).
- Drives the integrated `obd_orchestrator + DriveDetector + DriveStatisticsRecorder + sync_client + server analysis + server compute` path. NO mock seams. Real DB writes; real SQL reads.
- **Scenario 1 seeded**: "engine on for 9 min producing N realtime_data rows tagged drive_id=X, followed by sequencer poweroff (DriveDetector.engine_off NOT fired), followed by post-boot startup-time sweep + server-compute trigger." This is the V0.27.16 false-pass reproducer.
- **Empirical proof requirement** (bigDoD #6, addendum-tightened): harness applied to V0.27.7 OR V0.27.16 deployed code MUST produce RED for US-326+US-348 (drive_summary NULL fields) AND US-328+US-349 (drive_statistics zero rows). Same harness applied to V0.27.17 post-Sprint-41-land produces GREEN. **Retroactive RED proof is the load-bearing acceptance** — without it, the harness is just another test; with it, the harness is the structural close on I-040.
- **Scenario expansion is V0.28+**: crank-in-grace + sparse-drive + multi-drive-per-boot + sync-interrupted-mid-drive + etc. Each gets its own story.
- **Spec doc** `docs/superpowers/specs/2026-05-21-deploy-context-drive-simulator.md`: short (1-2 page) — harness design + invocation contract + scenario coverage roadmap (V0.27.17 scenario 1 + V0.28+ pipeline).

### Q6: US-356 architecture.md section choice

**Verdict: NEW section, "§7 Data Pipeline Architecture" (or equivalent numbered slot — Atlas finalizes at dispatch by reading current TOC).** Reasoning:

- B-104 Step 1 is significant enough to deserve its own section, paralleling §10.6 (Shutdown Sequencer) + §11 (EEPROM Wake Contract). These are the "load-bearing subsystem" sections per PM Rule 10.
- If existing TOC has a Data Pipeline section, AMEND it; if not, NEW section.
- Section content per US-356 intent (a-f): Pi=emitter/server=authority cut; trigger seam shift; idempotent recompute; Pi-side retirement; what's superseded; cross-link to commits.
- Atlas Rule 10 sign-off is the gate; Marcus administers as sprint DoD.
- **Honest empirical-gated language requirement** (Sprint 39 T9 precedent): cite drill evidence + IRL acceptance status; don't certify beyond evidence. E.g., "backfill of drives 12-20 PASSED on `<date>`" not "backfill is reliable."

### Q7: Stacked-chain semantics

**Verdict: CONFIRMED V0.27.17 patch-bump within the V0.27 chain.** Reasoning:

- B-104 Step 1 IS the architectural fix for the V0.27.7/V0.27.16 false-pass bug class. That's a bug-fix by any honest reading, even though the fix is architectural in nature.
- CIO's standing rule: V0.27.X = bug-fixes-only until `/chain-validated` cuts V0.28.0. V0.27.17 stays bug-fix.
- V0.28 cut happens on `/chain-validated` post V0.27.17 IRL acceptance, NOT mid-chain.
- B-104 Step 2+ (GEM family, Mahalanobis, etc.) explicitly V0.28+.
- Stacked-chain merge: sprint41 → sprint40 → sprint39 → ... → main on `/chain-validated`.

## Argus refinements — Atlas dispositions

### Refinement A: US-351 quantitative spec for "sensible min/max/avg"

**Verdict: generic invariants only in V0.27.17; per-PID envelopes deferred to V0.28+.**

- **Generic invariants** (baked into US-351 acceptance): `min_value <= avg_value <= max_value`, `std_dev >= 0`, no NaN/inf, `sample_count >= 1`. compute_drive_statistics RAISES if invariants violated (defensive against future PID schema bugs).
- **Per-PID envelopes deferred** (V0.28+ scope). Reasoning:
  - Encoding per-PID safe ranges requires knowing the full PID schema + safe operating ranges, which is Spool's lane (tuning spec authoring).
  - Adding per-PID envelopes opens up a discussion about which PIDs to envelope, what the envelope values are, and who owns updating them as Spool's tuning specs evolve.
  - That's a separate epic (could fold into B-076 server schema normalization or a new "B-104 Step 2 analytics validation").
  - For V0.27.17: generic invariants catch obvious bugs (negative std_dev, NaN, scale errors). Per-PID envelopes catch wrong-scale-but-superficially-valid values — defer.

### Refinement B: US-352 sparse-drive handling

**Verdict: graceful handling via `data_quality` column.**

- Three classifications:
  - `full`: ≥100 realtime_data rows for that drive
  - `sparse`: 10-99 rows
  - `below_threshold`: <10 rows
- Compute produces a row for every parameter_name in realtime_data REGARDLESS of count. data_quality classifies; never errors; downstream consumers filter on data_quality if they want only `full` drives.
- Drives 12-20 backfill (US-352) likely includes some sparse drives (US-352 ground reference says "drive 17 = 1,883 rows; drive 20 = 3,808 rows; others smaller (some likely <50 rows)"). Expect sparse and below_threshold rows in backfill.
- This makes `data_quality` column LOAD-BEARING in the US-351 schema (Q4 above already includes it).

### Refinement C: US-353 multi-reboot scope

**Verdict: 3 consecutive reboots minimum; forced-large-trail deferred unless cheap.**

- 3 consecutive `prior_boot_clean=1` writes post-V0.27.17 deploy = US-353 acceptance gate.
- Catches the class where trim works for one cycle but degrades over multiple (Argus's concern).
- Forced-large-trail (artificially pre-seed trail to near-cap before reboot) deferred to V0.28+ unless trivial — the F-8 fix means trail trims on every clean shutdown, so under normal operation trail never accumulates unbounded. The forced scenario tests the GUARD's degradation behavior; the real-system protection is the F-8 fix preventing trail accumulation upstream.
- If Ralph estimates forced-large-trail harness is <30 min to build, include it (cheap = include). Otherwise defer.

## Per-task pre-registered gates

Each story below has: **design-question resolutions affecting it**, **acceptance[] array** (CIO-facing, what counts as done — for sprint.json), **verification[] array** (concrete checks Ralph runs), **Atlas gate criteria** (what I independently verify at submission), and **IRL bigDoD reference** (already in sprint.json validation block; any tightening noted).

The acceptance[] + verification[] arrays should be transcribed into sprint.json by Marcus. Atlas gate criteria are FOR ATLAS — they're the discipline I apply at gate-request time; Marcus doesn't need to encode them but Ralph should know they exist (they're not gotchas — they're the same criteria as the verification[] array, just independently re-verified by me).

---

### US-350: B-104 Step 1a — server-side drive_summary compute from raw

**Design questions affecting**: Q1 (overnight batch + on-demand both land), Q2 (boundary from realtime_data MIN/MAX; Pi event-log as enrichment).

**Acceptance criteria** (transcribe into sprint.json `acceptance[]`):

1. Server has callable compute path `compute_drive_summary(drive_id)` in `src/server/analytics/drive_summary_compute.py`. Reads `realtime_data` rows for drive_id; computes `start_time = MIN(timestamp_utc)`, `end_time = MAX(timestamp_utc)`, `duration_seconds = end_time - start_time`, `row_count = COUNT(*)`; enriches with Pi event-log fields (`ambient_temp_at_start_c`, `starting_battery_v`, `data_source`) where available; derives `is_real` from `data_source` (`'real'` → 1, `'simulator'` → 0, NULL → NULL not silently 0); UPSERTs idempotently into `drive_summary`.
2. Trigger seam retired: `_tryAutoAnalysisTrigger` at `src/server/api/sync.py:721` is DELETED (preferred) OR raises NotImplementedError tripwire if anyone tries to re-introduce the path. No path from sync receipt to compute.
3. Overnight batch lands: `deploy/server-analytics-batch.service` + `deploy/server-analytics-batch.timer` NEW; timer fires daily; service runs compute over all drive_ids with NULL drive_summary computed fields; `deploy/deploy-server.sh` installs them sync-if-changed + daemon-reload + enable-if-not-already.
4. On-demand CLI: `python -m server.cli.recompute_drive_analytics --drive-id N` invokes compute for a single drive; `--drive-id-range 12-20` for range; `--all-stale` for all drives with NULL fields.
5. Idempotent: `compute_drive_summary(N)` invoked twice produces identical drive_summary row values (computed_at may update; data values identical).
6. Gap-detection tripwire: for each drive_id, realtime_data rows share contiguous timestamps; gaps >5 min logged at WARN-level (defensive, not failing the compute).
7. Pi-side `src/pi/obdii/drive_summary.py` event-log fields preserved (`drive_start_timestamp`, `ambient_temp_at_start_c`, `starting_battery_v`, `data_source`); computed-field writer code paths retired.
8. Raw realtime_data table + sync transport UNTOUCHED.

**Verification commands** (transcribe into sprint.json `verification[]`):

1. `python -c "from server.analytics.drive_summary_compute import compute_drive_summary"` — module importable.
2. `pytest tests/server/analytics/test_drive_summary_compute.py -v` — unit test fixture-based compute against synthetic realtime_data.
3. `pytest tests/server/analytics/test_drive_summary_compute.py::test_idempotent -v` — re-run produces identical output.
4. `pytest tests/server/analytics/test_drive_summary_compute.py::test_is_real_derivation -v` — `data_source='real'` → 1; `'simulator'` → 0; NULL → NULL (not silently 0).
5. `pytest tests/server/analytics/test_drive_summary_compute.py::test_gap_detection_warns -v` — synthetic realtime_data with >5-min gap produces WARN log, not failure.
6. `grep -n "_tryAutoAnalysisTrigger\|auto_analysis" src/server/api/sync.py` — no live calls (only modification history references OR explicit NotImplementedError tripwire).
7. `grep -n "drive_summary" src/pi/obdii/drive_summary.py` — only event-log writer surface; no computed-field code paths.
8. `test -f deploy/server-analytics-batch.service && test -f deploy/server-analytics-batch.timer` — systemd timer files exist.
9. `python -m server.cli.recompute_drive_analytics --help` — CLI runnable.
10. `git diff sprint/sprint40-bugfixes-V0.27.16..HEAD -- src/pi/obdii/realtime_data.py src/pi/obdii/sync/` — empty (or only modification-history comments).

**Atlas gate criteria** (independent verification at submission):

1. Re-run verification commands 1-10 independently (not the gate request's narrative).
2. Read `compute_drive_summary` source: confirm no dependency on Pi-side drive-end event marker; boundary from realtime_data MIN/MAX only.
3. SSOT pattern: server is sole writer of `drive_summary.start_time / end_time / duration_seconds / row_count / is_real`. No Pi-side competing writer.
4. Tripwire pattern: if `_tryAutoAnalysisTrigger` not deleted, must raise NotImplementedError (Sprint 39 SS-T4 precedent — fails LOUD if anyone re-introduces the path).
5. Scope fence: no edits to raw realtime_data; no edits to sync transport.
6. Modification history updated with US-350 / B-104 reference per project standard.
7. Sprint 39 T7 systemd-parity rigor: confirm server-analytics-batch.service runs as expected user with PYTHONPATH matching production. Atlas will spot-check by reading the unit file.

**IRL bigDoD** (sprint.json validation block #1; Atlas-strengthened):
> Deploy V0.27.17 → CIO does a real drive → server compute path runs (overnight batch OR on-demand invocation) → drive_summary row for that drive has `start_time / end_time / duration_seconds / row_count` NON-NULL + arithmetically consistent with `realtime_data` MIN/MAX/COUNT; `is_real=1` (for real drive) consistent with `data_source='real'`; (simulator drives via US-355 harness confirm `is_real=0`).

---

### US-351: B-104 Step 1b — server drive_statistics compute + retire Pi table

**Design questions affecting**: Q3 (idempotent DROP + first-boot logging), Q4 (server schema shape), Refinement A (generic invariants only), Refinement B (data_quality classification).

**Acceptance criteria**:

1. **Pi-side retirement complete**:
   - `src/pi/obdii/drive_statistics.py` DELETED.
   - `SCHEMA_DRIVE_STATISTICS` + `ALL_SCHEMAS` registration REMOVED from `src/pi/obdii/database_schema.py`.
   - Idempotent migration added: drops `drive_statistics` table on first Pi boot post-V0.27.17 deploy; logs `INFO eclipse-obd | drive_statistics table dropped (was: N rows / M distinct drives)`; subsequent boots log `DEBUG | drive_statistics table absent (retired V0.27.17 per US-351)`. DROP TABLE IF EXISTS (no error if already gone).
   - `driveStatisticsRecorder` kwarg + setter + `_recordDriveStatistics` helper REMOVED from `src/pi/obdii/drive/detector.py`; `_endDrive` reverted to pre-US-349 shape.
   - `_initializeDriveStatisticsRecorder` method REMOVED from `src/pi/obdii/orchestrator/lifecycle.py`; init call REMOVED from `_initializeAllComponents`.
   - `tests/pi/obdii/test_drive_statistics_writer.py` DELETED.
   - `tests/pi/obdii/test_drive_statistics_pi_table_migration.py` REPURPOSED as the migration-drop test (asserts table drops idempotently on first boot post-deploy; second invocation is no-op).
2. **Server-side build complete**:
   - `src/server/db/models.py` adds (or amends to) `drive_statistics` schema per Q4 verdict above (drive_id, parameter_name, min_value, max_value, avg_value, std_dev, outlier_min, outlier_max, sample_count, data_quality, computed_at; PK (drive_id, parameter_name); FK drive_id → drive_summary.id ON DELETE CASCADE; index on data_quality).
   - `src/server/analytics/drive_statistics_compute.py` NEW: callable `compute_drive_statistics(drive_id)` reads realtime_data, groups by parameter_name, computes stats, classifies data_quality, UPSERTs.
   - Generic invariants RAISE if violated: `min_value <= avg_value <= max_value`, `std_dev >= 0`, no NaN/inf, `sample_count >= 1`. (per Refinement A)
   - data_quality classification: `below_threshold` if sample_count <10; `sparse` if 10-99; `full` if ≥100. (per Refinement B)
3. Idempotent: `compute_drive_statistics(N)` invoked twice produces identical row values; computed_at may update (observable in metadata).
4. Wired to same trigger seams as US-350 (overnight batch + on-demand CLI); same systemd timer fires both compute paths.
5. Pi-side raw realtime_data table + sync client UNCHANGED.
6. Pi-side drive boundary event log (`drive_start_timestamp` etc.) preserved per CIO 2026-05-21 ratification.

**Verification commands**:

1. `test ! -f src/pi/obdii/drive_statistics.py` — Pi-side module deleted.
2. `grep -n "SCHEMA_DRIVE_STATISTICS\|drive_statistics" src/pi/obdii/database_schema.py` — only migration-drop SQL + maybe modification history; no schema declaration.
3. `grep -n "driveStatisticsRecorder\|DriveStatisticsRecorder\|_recordDriveStatistics" src/pi/obdii/drive/detector.py src/pi/obdii/orchestrator/lifecycle.py` — no live references; only modification history.
4. `python -c "from server.analytics.drive_statistics_compute import compute_drive_statistics"` — module importable.
5. `pytest tests/server/analytics/test_drive_statistics_compute.py -v` — unit tests pass.
6. `pytest tests/server/analytics/test_drive_statistics_compute.py::test_invariants -v` — negative std_dev rejected; NaN rejected; min>avg rejected; sample_count=0 rejected.
7. `pytest tests/server/analytics/test_drive_statistics_compute.py::test_idempotent -v` — re-run identical.
8. `pytest tests/server/analytics/test_drive_statistics_compute.py::test_data_quality_classification -v` — <10 → below_threshold; 10-99 → sparse; ≥100 → full.
9. `pytest tests/pi/obdii/test_drive_statistics_pi_table_migration.py -v` — drop idempotent; logs row count on first invocation; logs absent on second.
10. `git diff sprint/sprint40-bugfixes-V0.27.16..HEAD -- src/pi/obdii/realtime_data.py src/pi/obdii/sync/` — empty.

**Atlas gate criteria**:

1. Re-run verification commands 1-10.
2. Read source: confirm no Pi-side competing writer; Pi has zero references to drive_statistics insertion (only DROP migration).
3. SSOT check: server is sole writer.
4. Read invariants assertion in `compute_drive_statistics`: ensure invariants are RAISE not silent-pass.
5. Read data_quality classification logic + matching test coverage.
6. Migration drop: read SQL; confirm DROP TABLE IF EXISTS (not unconditional DROP).
7. Scope fence: realtime_data table + sync client UNTOUCHED.
8. SSOT pattern: trip-wire any future Pi-side attempt to write drive_statistics (e.g., if someone re-introduces the import, it 404s; if someone tries to insert into a non-existent local table, SQLite errors). The retirement IS the tripwire.
9. Cross-module identity check (Sprint 39 [[feedback-cross-module-enum-identity]] precedent): confirm Pi-side `drive_statistics.py` deletion doesn't break any orphan import elsewhere — Ralph runs `grep -r "from .*drive_statistics import" src/ tests/` and confirms no residual imports.

**IRL bigDoD** (sprint.json validation block #2; Atlas-strengthened with quantitative invariants):
> Deploy V0.27.17 → CIO does a real drive → server compute path runs → server-side drive_statistics has ≥1 row per parameter_name present in realtime_data; for each row: `min_value <= avg_value <= max_value`, `std_dev >= 0`, no NaN/inf, `sample_count` matches expected count from realtime_data, `data_quality` classified correctly per row count; Pi-side drive_statistics table NOT PRESENT post-migration (idempotent drop confirmed via Pi sqlite query showing table absent + first-boot log showing drop event).

---

### US-352: B-104 Step 1c — backfill drives 12-20

**Design questions affecting**: Q1 (on-demand CLI lands in V0.27.17), Refinement B (sparse-drive handling encoded in US-351 schema).

**Acceptance criteria**:

1. On-demand CLI `python -m server.cli.recompute_drive_analytics --drive-id-range 12-20` succeeds without error.
2. Post-backfill: `SELECT id, source_id, start_time, end_time, duration_seconds, row_count, is_real FROM drive_summary WHERE source_id BETWEEN 12 AND 20 ORDER BY source_id` returns 9 rows with NON-NULL computed fields; `is_real` derived per Q2 (1 if `data_source='real'`, 0 if `'simulator'`, NULL if data_source missing).
3. Post-backfill: `SELECT drive_id, COUNT(*) AS rows FROM drive_statistics WHERE drive_id IN (SELECT id FROM drive_summary WHERE source_id BETWEEN 12 AND 20) GROUP BY drive_id ORDER BY drive_id` returns 9 drives with positive row counts.
4. Sparse-drive handling: drives with <10 realtime_data rows produce rows with `data_quality='below_threshold'`, NOT absent rows.
5. Idempotent re-run: backfill same range twice produces zero diff in either table's data values (computed_at may update).
6. `deploy/deploy-server.sh` UPDATE: one-shot idempotent backfill invocation post-V0.27.17 deploy under guard flag (e.g., `BACKFILL_COMPLETE_V0_27_17=true` written to a marker file after first successful run; subsequent deploys check marker and skip).
7. Backfill produces observable log: per-drive line like `INFO server.cli | backfilled drive 17: drive_summary computed_at=<timestamp>, drive_statistics 16 parameter rows, data_quality=full`.

**Verification commands**:

1. `python -m server.cli.recompute_drive_analytics --drive-id-range 12-20 --dry-run` — dry-run mode prints planned operations without writing.
2. `python -m server.cli.recompute_drive_analytics --drive-id-range 12-20` — production run.
3. DB read-back drive_summary: `mysql -e "SELECT id, source_id, start_time, end_time, duration_seconds, row_count, is_real FROM obd2db.drive_summary WHERE source_id BETWEEN 12 AND 20 ORDER BY source_id"` — 9 rows, all NON-NULL except is_real may be NULL for unknown data_source.
4. DB read-back drive_statistics: `mysql -e "SELECT drive_id, COUNT(*) AS rows, MIN(data_quality) AS min_quality, MAX(data_quality) AS max_quality FROM obd2db.drive_statistics GROUP BY drive_id ORDER BY drive_id"` — 9 drives with positive counts.
5. Idempotent re-run: `python -m server.cli.recompute_drive_analytics --drive-id-range 12-20 && mysql -e "SELECT MAX(computed_at) FROM obd2db.drive_statistics WHERE drive_id IN (SELECT id FROM obd2db.drive_summary WHERE source_id BETWEEN 12 AND 20)"` then re-run + diff: data values identical, computed_at updated.
6. deploy-server.sh guard: `grep -n "BACKFILL_COMPLETE\|backfill" deploy/deploy-server.sh` — guard logic present + idempotent.
7. Log output verification: invocation produces per-drive INFO logs.

**Atlas gate criteria**:

1. Re-run verification commands 1-7.
2. Read CLI source: confirm `--drive-id-range` parses correctly + iterates per drive.
3. Verify deploy-server.sh guard is idempotent (simulate two consecutive deploys; second skips backfill).
4. Read backfill output for drives 12-20: spot-check 2-3 drives for arithmetic consistency:
   - drive 17 should have start_time + end_time spanning roughly the realtime_data range (compare to MIN/MAX query).
   - drive 20 should have row_count=3,808 (Argus's drill evidence).
5. Sparse-drive handling: identify which of drives 12-20 are sparse (<10 rows) and verify `data_quality='below_threshold'` is set, not absent rows.
6. Dependencies on US-350 + US-351 satisfied (those land before US-352 gates).

**IRL bigDoD** (sprint.json validation block #3; Atlas-strengthened):
> Post-deploy on-demand recompute over drives 12-20 produces drive_summary NON-NULL computed fields for all 9 drives + drive_statistics rows for all 9 drives (count ≥1 per parameter_name); idempotent re-run produces zero diff in data values (computed_at timestamp may update — observable idempotency); sparse drives classified `data_quality='below_threshold'` not absent.

---

### US-353: maxTrailBytes guard fix

**Design questions affecting**: Refinement C (3 consecutive reboots minimum; forced-large-trail conditional on cost).

**Acceptance criteria**:

1. Fix shape: **auto-trim with WARN log emission** on write (preferred over refuse-to-write or unconditional cap-raise). Reasoning encoded in design note from Atlas; Ralph can challenge if a different shape is empirically simpler.
   - On write: if current trail size + new content > maxTrailBytes, trim oldest entries to fit; emit WARN log `boot_progress trail trimmed: was <X> bytes, trimmed to <Y> bytes, current write would have exceeded maxTrailBytes=<Z>`.
   - Don't refuse the write (Argus's V0.27.16 drill showed refuse-to-write blocks boot progress logging entirely → observability hole).
   - Don't silently truncate without logging (silent failure mode).
2. F-8 fix preserved: `boot-progress-finalize.service` `Conflicts=shutdown.target` directive UNCHANGED.
3. boot_progress writer code path: CLEAN_COMPLETE emission unchanged.
4. startup_log schema unchanged.
5. 3-reboot harness test: 3 consecutive simulated clean shutdowns + reboots produce 3 consecutive `prior_boot_clean=1` writes + no guard trip across all 3 cycles. Trail size after each cycle stays bounded (<maxTrailBytes).
6. Forced-large-trail harness (CONDITIONAL on cost): if Ralph estimates <30 min to build, include — artificially pre-seed trail to ~95% maxTrailBytes; reboot; confirm auto-trim fires + WARN log emitted + boot progresses normally. Otherwise defer to V0.28+.

**Verification commands**:

1. `pytest tests/pi/diagnostics/test_boot_progress.py -v` — full boot_progress test suite passes.
2. `pytest tests/pi/diagnostics/test_boot_progress.py::test_max_trail_bytes_auto_trim -v` — write that would exceed maxTrailBytes triggers auto-trim.
3. `pytest tests/pi/diagnostics/test_boot_progress.py::test_max_trail_bytes_warns_on_trim -v` — WARN log emitted on trim.
4. `pytest tests/pi/diagnostics/test_boot_progress.py::test_three_consecutive_reboots_no_trip -v` — 3 consecutive simulated reboots pass.
5. (Conditional) `pytest tests/pi/diagnostics/test_boot_progress.py::test_forced_large_trail_auto_trims -v` — if forced-large-trail harness built.
6. F-8 fix preserved: `git diff sprint/sprint40-bugfixes-V0.27.16..HEAD -- deploy/boot-progress-finalize.service` — empty (or only modification-history comments).
7. Confirm boot_progress writer untouched: `grep -n "CLEAN_COMPLETE" src/pi/diagnostics/boot_progress.py` — same emission code as Sprint 40.

**Atlas gate criteria**:

1. Re-run verification commands 1-7.
2. Read `boot_progress.py`: confirm auto-trim implementation + WARN log emission (not silent-truncate).
3. Read 3-reboot test: confirm scenario is faithful (real shutdown sequence simulated, not just mock).
4. Scope fence: F-8 fix UNTOUCHED.
5. If forced-large-trail harness built: review its faithfulness (does it truly fill trail to near-cap or just mock the file size?).

**IRL bigDoD** (sprint.json validation block #4; Atlas-strengthened with Refinement C):
> 3 consecutive post-deploy reboots all pass without tripping maxTrailBytes guard; trail size after each cycle is bounded (<maxTrailBytes, observable in `/var/log/eclipse-obd/boot-progress.log` size); `prior_boot_clean=1` written each cycle.

---

### US-354: deploy-pi.sh daemon-reload + service restart gap

**Design questions affecting**: Accuracy review Finding 1 (`$changed`-gated restart is the actual bug, not absent restart logic).

**Acceptance criteria**:

1. **Decouple restart from unit-file-change gate** in `deploy/deploy-pi.sh`:
   - `step_install_power_watch_unit` (lines 936-991): `sudo systemctl restart eclipse-powerwatch.service` invoked on EVERY deploy (not only when `$changed=true`). `daemon-reload` remains gated on `$changed` (daemon-reload is unit-file metadata reload; restart is process replacement — different signals).
   - Same fix applied to all `$changed`-gated restarts for long-running services in deploy-pi.sh. Audit: `step_install_boot_progress_units`, `step_install_drain_forensics_units` (boot-progress-finalize is `Type=oneshot` — different rules apply; restart-on-every-deploy may not apply), `step_install_orphan_cleanup_units`, and `step_restart_service` (final eclipse-obd restart). Ralph + Atlas audit at dispatch which services need unconditional restart vs which are oneshot.
2. **PID-start-time verification step added** post-restart, pre-`.deploy-version`-bump:
   - `ps -o pid,lstart,cmd -p $(pidof -s eclipse-powerwatch)` shows STARTED time later than deploy start timestamp.
   - `ps -o pid,lstart,cmd -p $(pidof -s eclipse-obd)` shows STARTED time later than deploy start timestamp.
   - If either check fails: deploy ABORTS with clear error (exit non-zero); `.deploy-version` is NOT bumped on incomplete restart.
3. Idempotent on re-run: restart safe to invoke multiple times (systemd handles this natively).
4. `deploy-server.sh` UNTOUCHED (server-side deploy healthy per Argus's V0.27.16 drill — eclipse-obd-server restart on chi-srv-01 already works correctly).
5. `.deploy-version` bump logic preserved; just relocated to AFTER restart-verification of both services.

**Verification commands**:

1. `pytest tests/deploy/test_deploy_pi.py -v` — full deploy-pi tests pass.
2. `pytest tests/deploy/test_deploy_pi.py::test_restart_decoupled_from_unit_change -v` — static check that restart is unconditional for long-running services.
3. `pytest tests/deploy/test_deploy_pi.py::test_pid_verification_aborts_on_failure -v` — failure path aborts deploy.
4. Static check: `grep -B5 -A10 "systemctl restart eclipse-powerwatch" deploy/deploy-pi.sh` — manual review confirms restart not gated by unit-only diff.
5. Static check: `grep -n "lstart\|PID-start-time" deploy/deploy-pi.sh` — verification step present.
6. `git diff sprint/sprint40-bugfixes-V0.27.16..HEAD -- deploy/deploy-server.sh` — empty (server-side untouched).

**Atlas gate criteria**:

1. Re-run verification commands 1-6.
2. Read `deploy-pi.sh` diff: confirm the `$changed`-gated restart pattern is FIXED for all long-running services. Audit `step_install_boot_progress_units` etc. — confirm oneshot vs long-running distinction is handled correctly (oneshot doesn't need restart-on-every-deploy; long-running does).
3. PID-start-time verification: confirm both eclipse-powerwatch AND eclipse-obd are checked; failure path aborts.
4. Scope fence: deploy-server.sh UNTOUCHED.
5. Idempotent re-run safety: trace through a hypothetical second deploy invocation; confirm restart + verify still succeeds.
6. **Pattern note for documentation**: this is a condition-gating bug class (narrow predicate absorbing broader case — same class as F-7's boot-grace edge-only polling). Ralph's fix should not regress to another narrow-guard pattern. Atlas spot-checks at gate.

**IRL bigDoD** (sprint.json validation block #5; matches Marcus's addendum-tightened wording):
> Post-deploy verification — `ps -o pid,lstart,cmd -p $(pidof -s eclipse-powerwatch)` AND `$(pidof -s eclipse-obd)` both show STARTED time later than deploy start; deploy log shows daemon-reload + service restart sequence for BOTH services; `.deploy-version` bump occurs AFTER restart-verification of both services.

---

### US-355: I-040 structural close — deploy-context drive simulator

**Design questions affecting**: Q5 (minimum viable harness + ONE scenario seeded; expansion V0.28+).

**Acceptance criteria**:

1. `tests/integration/test_deploy_context_drive_simulator.py` NEW: pytest harness spinning up real Pi SQLite (file-based or `:memory:`) + real server MariaDB (testcontainers OR local docker-mariadb OR existing chi-srv-01 obd2db); driving the integrated `obd_orchestrator + DriveDetector + DriveStatisticsRecorder + sync_client + server analytics + server compute` path. NO mock seams.
2. `docs/superpowers/specs/2026-05-21-deploy-context-drive-simulator.md` NEW: 1-2 page spec — harness design + invocation contract + scenario coverage roadmap (V0.27.17 scenario 1 + V0.28+ pipeline of scenarios to add).
3. **Scenario 1 seeded**: "engine on for 9 min producing N realtime_data rows tagged drive_id=X, followed by sequencer poweroff (DriveDetector.engine_off NOT fired), followed by post-boot startup-time sweep + server-compute trigger." Mirrors V0.27.16 false-pass reproducer.
4. **EMPIRICAL RED proof**: harness applied to V0.27.7 OR V0.27.16 deployed code MUST produce RED for the US-326+US-348 (drive_summary NULL fields) AND US-328+US-349 (drive_statistics zero rows) conditions. (Ralph identifies appropriate baseline commits; CI runs harness against those commits in a separate test target like `test_deploy_context_drive_simulator_retroactive.py` OR via git-stash mechanism in the harness itself.)
5. **EMPIRICAL GREEN proof**: same harness applied to V0.27.17 post-Sprint-41-land produces GREEN for the same scenarios.
6. Harness drives the SAME deploy artifact the IRL Pi runs (rsync the deploy/ + src/pi/ tree into a temp dir; run from there).
7. Sign-off from Atlas + Argus + Ralph + Marcus on harness design + V0.27.7/V0.27.16 RED scenario coverage (per sprint.json bigDoD #6).

**Verification commands**:

1. `pytest tests/integration/test_deploy_context_drive_simulator.py -v` on current branch → PASS.
2. `pytest tests/integration/test_deploy_context_drive_simulator.py::test_scenario_1_v0_27_16_reproducer_GREEN_on_current_branch -v` → PASS on V0.27.17.
3. Retroactive RED proof (Ralph designs the mechanism):
   - Option A: `git stash + git checkout 5837239 -- src/pi src/server && pytest tests/integration/test_deploy_context_drive_simulator.py -v && git stash pop` → FAIL on V0.27.16.
   - Option B: separate `tests/integration/test_deploy_context_drive_simulator_retroactive_v0_27_16.py` that imports git-checked-out V0.27.16 source tree.
   - Option C: harness has a `--baseline-commit <SHA>` flag.
4. `test -f docs/superpowers/specs/2026-05-21-deploy-context-drive-simulator.md` — spec doc exists.
5. Atlas + Argus + Ralph + Marcus sign-off filed (inbox notes or sprint.json metadata).

**Atlas gate criteria**:

1. Independent run of pytest on current branch (PASS expected).
2. Independent retroactive run against V0.27.16 (RED expected on US-348/US-349 conditions).
3. Read harness source: confirm no mock seams; real DBs; orchestrator initialization path matches deploy.
4. Read spec doc: confirm scenario coverage roadmap + how V0.28+ scenarios get added; honest empirical-gated language.
5. Scope fence: no production code edits (test-only).
6. SSOT pattern: harness is the SSOT for "did the writer/compute path actually fire in deploy?" — single test surface, no duplicate gate tests.
7. Sign-off mechanics: Atlas verifies all 4 sign-offs are filed before gate PASS.

**IRL bigDoD** (sprint.json validation block #6; matches addendum-tightened wording):
> Harness applied to the V0.27.7 OR V0.27.16 deployed code MUST produce RED for the US-326+US-348 (drive_summary NULL fields) and US-328+US-349 (drive_statistics zero rows) conditions — empirical proof the harness would have caught the 3-cycle false-pass class. Same harness applied to V0.27.17 post-Sprint-41-land produces GREEN for the same scenarios. Atlas + Argus + Ralph + Marcus sign-off on harness design + RED scenario coverage.

---

### US-356: PM Rule 10 — specs/architecture.md amendment for B-104 Step 1

**Design questions affecting**: Q6 (NEW section, "Data Pipeline Architecture" or numbered slot; honest empirical-gated language).

**Acceptance criteria**:

1. NEW section in `specs/architecture.md` documenting B-104 Step 1 data-pipeline architecture (section number TBD pending TOC read at dispatch — likely §7 or wherever fits sequentially; if existing TOC has Data Pipeline section, AMEND it). Content per US-356 sprint.json intent (a-f):
   - (a) **Architectural principle**: Pi = telemetry emitter + event-log writer; server = sole authority for derived analytics.
   - (b) **Compute path**: server reads raw `realtime_data` + Pi event logs; computes `drive_summary` (boundary from realtime_data MIN/MAX; enrichment from Pi event-log fields) + `drive_statistics` (per-parameter aggregates with generic invariants + data_quality classification).
   - (c) **Pi-side retirement scope**: `drive_statistics` table dropped; `drive_summary` computed-field writer retired; Pi keeps event-log fields (`drive_start_timestamp`, `ambient_temp_at_start_c`, `starting_battery_v`, `data_source`) for diagnostics.
   - (d) **Trigger seam shift**: server compute does NOT depend on Pi-side drive-end signal; overnight batch + on-demand CLI; sync receipt is decoupled from compute.
   - (e) **Idempotent recompute principle**: same raw + same logic = same output; observable via `computed_at` timestamp; re-run safe.
   - (f) **What's retired** (with commit cross-links): V0.27.7 US-326 connection_log trigger seam (commit `<SHA>`); V0.27.7 US-328 Option C schema-only (commit `<SHA>`); V0.27.16 US-348 dual-seam (commit `<SHA>`); V0.27.16 US-349 Pi-side writer wiring (commit `<SHA>`). Cross-link to git log for archival traceability.
2. Sprint 40 US-346 §10.6 amendment PRESERVED (no edits to §10.6; B-104 section is additive).
3. Other architecture.md sections UNCHANGED.
4. Modification history updated with US-356 / Sprint 41 reference.
5. NO code changes (US-350+US-351+US-352+US-355 own code; US-356 is spec-only).
6. **Honest empirical-gated language**: Sprint 39 T9 precedent. Cite drill evidence + IRL acceptance status + drilldown to commits. Don't certify beyond evidence — e.g., "backfill of drives 12-20 PASSED on `<date>` per Argus's drill evidence" not "backfill is reliable in all conditions." If V0.27.17 IRL drill hasn't happened yet at the time US-356 is written, language should say "IRL drill pending" not assert success preemptively.
7. **Atlas Rule-10 sign-off** granted after independent re-read of the amendment against the current code state (post US-350+US-351 land). This is the gate; Marcus closes sprint after.

**Verification commands**:

1. New section exists: `grep -n "Data Pipeline Architecture\|B-104 Step 1\|Pi = emitter, server = authority" specs/architecture.md` — section heading + B-104 reference + key phrases present.
2. Sprint 40 §10.6 preserved: `grep -n "Shutdown Sequencer" specs/architecture.md` — unchanged from Sprint 40 post-US-346 state.
3. Modification history updated: `head -100 specs/architecture.md | grep -A5 "US-356\|Sprint 41"` — entry present.
4. No code touched by US-356 itself: `git log --name-only HEAD~1..HEAD` (after US-356 commit) — only `specs/architecture.md` in changed-files.
5. Commit cross-links present in section (f): `grep -E "[a-f0-9]{7,40}" <section_extract>` — at least 4 commit SHAs cited for the retired V0.27.7 / V0.27.16 surfaces.

**Atlas gate criteria** (Rule 10 sign-off):

1. Independent re-read of the amendment against current code state (post-US-350+US-351 land).
2. Confirm each of (a)-(f) is documented honestly (no false guarantees).
3. Empirical language audit: every "PASS" / "validated" claim cites date + drill + commit. Anything not yet drilled is labeled "pending" or "deployed but not validated."
4. Cross-link to commits in section (f): minimum 4 SHAs (US-326, US-328, US-348, US-349 origin commits) for archival traceability.
5. Section choice ratified: load-bearing-subsystem section parallels §10.6 / §11 pattern.
6. Scope fence: no edits to §10.6 or other unrelated sections.
7. **Rule 10 sign-off granted = sprint DoD met for design-gate.** Atlas files inbox note to Marcus confirming sign-off; Marcus closes sprint.

**IRL bigDoD** (sprint.json validation block #7; matches sprint.json):
> Atlas sign-off on `specs/architecture.md` amendment documenting B-104 Step 1 data-pipeline architecture (server reads raw realtime_data + Pi event logs + computes derived analytics; Pi-side writer retirement scope; trigger seam shift; idempotent recompute principle) per PM Rule 10 (in-sprint, not follow-up).

---

## Cross-story discipline + sprint-orchestration notes for Marcus

1. **Sequencing** (Atlas-recommended):
   - US-350 + US-351 run in parallel after US-346 (Sprint 40 carry-forward — see next item).
   - US-352 depends on US-350 + US-351 (must be merged-ready before US-352 can backfill).
   - US-353 + US-354 independent; can run in parallel with US-350/US-351.
   - US-355 depends on US-350 + US-351 (harness exercises the new compute path); can be drafted in parallel but final pytest run gated on those lands.
   - US-356 depends on US-350 + US-351 (architecture.md describes the new state); ships last.
   - Recommended Ralph dispatch order: US-346 (Sprint 40 carry-forward) → US-353 + US-354 (parallel, small) → US-350 + US-351 (parallel, M+L) → US-352 → US-355 → US-356.

2. **Sprint 40 US-346 carry-forward**: Independent of Sprint 41 but blocks Argus's `/sprint-validated` for Sprint 40. **Atlas owes Ralph a gate verdict on this BEFORE Sprint 41 Ralph dispatch.** I'll file a separate inbox note to Ralph (and to you) once I've re-read his §10.6 amendment request. Today or tomorrow.

3. **Atlas independent re-verification at each gate**: Sprint 39 precedent. I re-run verification commands myself (not the gate request's narrative). If Ralph's gate request claims a command passed but I get a different result, the gate is CHANGES-REQUESTED until resolved. This caught the V0.27.12 deploy-state-flawed pinctrl test (my own instrument); applies symmetrically here.

4. **Flag-don't-improvise discipline**: If Ralph hits a contradiction between sprint.json + this gate registration, he STOPS + files a clarification request (not silent reinterpretation). Sprint 39 Task-4 precedent — Ralph's design-blocker call was correct.

5. **SSOT pattern enforcement**: B-104 Step 1 IS the SSOT pattern at scale. drive_summary computed fields and drive_statistics rows have ONE acquisition site (server compute from raw); consumers (CLI, batch, future analytics) apply policy not their own acquisition. Tripwires (NotImplementedError in `_tryAutoAnalysisTrigger`, table-absent on Pi) catch regression to dual-writer.

6. **Honest empirical-gated language project-wide**: Sprint 39 T9 precedent. Any documentation written this sprint (US-356 architecture amendment, US-355 spec doc, deploy-pi.sh comments, module headers) cites drill date + commit SHA + IRL status. Don't assert certainty beyond evidence.

7. **What I don't need from you for sprint.json transcription**: the Atlas gate criteria sections above are FOR ATLAS — they're my discipline at gate-request time. You can transcribe acceptance[] + verification[] into sprint.json; Atlas gate criteria stay in this file as reference. Ralph reads sprint.json; Atlas reads this note + the gate requests.

## What's next on my side

1. **Sprint 40 US-346 §10.6 sign-off** — re-read Ralph's amendment request + verdict. Files to Ralph's inbox + ack to you. Today or early tomorrow.
2. **Stand-by for Ralph gate requests** — Sprint 41 cadence will be Sprint 39 cadence: Ralph completes a story + files gate request to my inbox + I independently verify + verdict PASS / CHANGES-REQUESTED. Estimate: 7 gates over the sprint duration.
3. **Adjust gates on observed evidence** — if a US-350 implementation surfaces something the gate criteria don't cover (e.g., a third trigger seam I didn't anticipate), Ralph escalates + Atlas adjusts (pre-registered ≠ frozen; pre-registered = locked to written-down-and-reasoned-about). Adjustments are documented in updated gate notes.

## Closing

The architectural call is sound. The pre-registered gates lock the contract before Ralph dispatch. Sprint 39/40 cadence preserved. Chain unblock depends on US-350 + US-351 + US-352 IRL acceptance + US-355 retroactive RED proof + US-356 Rule-10 sign-off + US-346 carry-forward.

No deliverable owed in your lane until you've reviewed + transcribed acceptance[] + verification[] into sprint.json + dispatched Ralph. Take what time you need. If anything in this note conflicts with your sprint-orchestration constraints, flag back.

— Atlas
