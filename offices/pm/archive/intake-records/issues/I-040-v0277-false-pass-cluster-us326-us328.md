# I-040 — V0.27.7 False-Pass Cluster (US-326 drive_summary + US-328 drive_statistics)

> **PM note 2026-05-20 evening**: Renumbered from I-039 → I-040 by Marcus to resolve
> ID collision. I-039 was concurrently filed earlier this evening for F-8
> (`boot-progress-finalize.service` ExecStop never fires; root cause of
> CLEAN_COMPLETE instrument honesty) and committed in `5596df0` before Tester's
> file was pulled. Substance unchanged; only the ID + filename were bumped.

**Filed**: 2026-05-20 (Tester)
**Severity**: Med (not chain-blocking; corrupts every drive's analytics surface)
**Status**: Empirically confirmed across drives 11-18 incl. 2 fresh real drives (17+18) today
**Owner**: PM (Marcus) to triage Sprint 40 grooming
**Related**:
- Atlas F-8 (`boot-progress-finalize.service` ExecStop never fires) — covers US-330; do NOT double-file.
- I-031 / I-032 (US-331 false-pass) — same pattern, different surface.
- I-037 (US-330 canary false-positive) — same pattern, different surface.

---

## Summary

Two V0.27.7 stories that shipped `passes:true` in Sprint 33 do not actually
deliver their stated behavior in production. Same "synthetic test passed, real
path never runs" shape as I-031 + I-037. Discovered 2026-05-20 while pulling
Drive-12-gate evidence after CIO's IRL drive 17+18.

US-330 (also V0.27.7, also false-pass) is **separately covered** by Atlas's
parallel F-8 finding (`offices/architect/findings/2026-05-20-startup-log-marker-broken-empirical.md`).
This issue covers only US-326 + US-328.

---

## Evidence

### US-326 — drive_summary server analytics writer

**Story claim (Sprint 33, V0.27.7)**: When Pi syncs a new `drive_summary` row,
the server analytics writer derives `start_time`, `end_time`, `duration_seconds`,
`row_count`, `is_real` (and `drive_id` when missing) from the linked
`realtime_data` rows on drive_end.

**Query (2026-05-20, chi-srv-01 obd2db)**:

```sql
SELECT id, source_id, drive_id, start_time, end_time, duration_seconds,
       row_count, is_real, drive_start_timestamp, ambient_temp_at_start_c,
       starting_battery_v
FROM drive_summary
WHERE drive_id >= 16 OR id >= 14
ORDER BY id DESC LIMIT 8;
```

**Result (every row, 8 of 8)**: `start_time` / `end_time` / `duration_seconds` /
`row_count` / `is_real` ALL NULL. Pi-synced fields
(`drive_start_timestamp`, `ambient_temp_at_start_c`, `starting_battery_v`,
`source_id`) arrive correctly. `drive_id` populated on ~half of rows (drives
12, 13, 15), NULL on the other half (drives 11, 14, 16, 17, 18) — inconsistent.

Rows include today's drives 17+18 from CIO's real IRL drive — proving the
writer doesn't fire on a fresh sync round-trip.

### US-328 — drive_statistics Pi-side writer (Option C hybrid)

**Story claim (Sprint 33, V0.27.7)**: Pi computes per-parameter aggregates
(min/max/avg/std_dev/outlier bounds) and writes them to a new Pi-side
`drive_statistics` table on `drive_end`.

**Query (2026-05-20, Pi obd.db)**:

```sql
SELECT drive_id, COUNT(*) AS pid_count
FROM drive_statistics GROUP BY drive_id ORDER BY drive_id DESC;
```

**Result**: zero rows. Table schema present (verified `.schema drive_statistics`
returns the expected CREATE TABLE with `drive_id`, `parameter_name`, `min_value`,
`max_value`, `avg_value`, `std_dev`, `outlier_min`, `outlier_max`, etc.), but
no rows for any drive ever. Includes drives 17+18 captured today.

---

## Impact

- **F-005 (drive_summary INSERT fires on drive_end)** stays REGRESSED. The
  long-awaited Drive-12 gate that V0.27.7's stories were supposed to flip:
  Drive 12 happened (server `id=16`), Drive 17 + 18 happened today; all NULL.
- **Calibration CLI / `baselines`** stays blocked. `baselines` needs the
  US-328 drive_statistics rows; with 0 rows ever, `baselines=0` permanently.
- **No downstream chain-merge implication if PM ratifies** that the chain-merge
  gate is Sprint 39 (Atlas's verdict) and not the V0.27 chain bigDoD
  Drive-12-validation framing from 2026-05-11. Recommend explicit ratification
  either way at Sprint 40 grooming so the framing is unambiguous.

---

## Recommended Action

PM triage at Sprint 40 grooming:

1. **Add US-326-redo to Sprint 40** (alongside Atlas F-7 fix). Strategy: don't
   re-author from spec; instead require deploy-then-IRL-exercise validation
   gate (run a real drive end-to-end, verify computed fields land in
   `drive_summary` post-sync). See `offices/tester/knowledge/feedback-tester-validate-deploy-fixes-irl-not-just-code.md`
   for the discipline lesson.
2. **Add US-328-redo to Sprint 40** with the same validation discipline.
3. **OR defer both to V0.28** if Sprint 40 scope is locked tight on F-7/F-8.
   Mark this issue OPEN-DEFERRED, not closed.

Per Tester role boundary (no story authoring) — PM owns whether these ride
Sprint 40, get their own bug-fix sprint, or defer.

---

## How to verify the fix landed

Per the discipline lesson: the acceptance criteria must include a real-drive
round-trip + DB read-back, not a synthetic test that mocks the writer's
trigger seam. Concretely:

1. Deploy fix.
2. CIO does a real drive (engine on > 10s for `drive_start`; key off for
   `drive_end`).
3. After sync, query server-side `drive_summary` for the new row: assert
   `start_time` / `end_time` / `duration_seconds` / `row_count` / `is_real`
   are all NON-NULL and arithmetically consistent with the `realtime_data`
   rows for that `drive_id`.
4. Query Pi-side `drive_statistics` for the new `drive_id`: assert ≥1 row per
   `parameter_name` present in the drive's `realtime_data`, with sensible
   min/max/avg values.
5. Only then mark `passes:true`.
