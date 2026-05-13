# Finding: obd2db data profile — additional issues for V0.28.0 (beyond CIO's review)

**Date**: 2026-05-12
**Severity**: Mixed (one Medium, rest Low) — none block V0.27.7; all candidates for the V0.28+ schema-normalization epic.
**Component**: server `obd2db` + Pi `obd.db` — full data-profiling pass
**Context**: CIO asked for a profile of every data table and an honest answer on what *else* needs fixing, beyond the items already in his 2026-05-12 DB review (`offices/tester/inbox/db review fom Mike.txt`) and beyond what V0.27.7 (sprint33, US-326..330) already covers.

## Summary

Profiled all 21 server tables + the Pi-side schema. Data values are physically sane (no garbage, no future-dated rows, no out-of-range telemetry — Drive 11's realtime_data is dense and balanced, ~676 samples/PID over ~23.5 min). The issues are structural/hygiene, not corrupt data. **Eight new bugs/quirks and eight new design smells** the CIO's review didn't already cover, listed below. The one that warrants the most attention is the historical sync-failure rate (resolved now, but informative).

---

## NEW — bugs / data-quality (not in CIO's review, not in V0.27.7)

### N-1 (Medium, mostly historical) — `sync_history` is 42% failed rows
8,505 of 20,283 `sync_history` rows have `status='failed'` (and `tables_synced=NULL`). Two failure modes:
- `(1364, "Field 'start_time' doesn't have a default value")` on `drive_summary` INSERTs — 2026-05-01 — **resolved** by migration `0006` (made the server-side legacy analytics columns `NULL DEFAULT NULL`). This is also the structural reason I-026 exists: the sync only writes the Pi columns, so after `0006` the INSERT succeeds but `start_time`/`end_time`/`duration_seconds`/`row_count`/`is_real`/`profile_id` stay NULL — the server analytics writer is supposed to fill them.
- `(1020, "Record has changed since last read in table 'realtime_data'")` — optimistic-lock / concurrent-modification on the `ON DUPLICATE KEY UPDATE` — last seen 2026-05-08. **Apparently resolved** (0 failures since). But it's a race that can recur under concurrent sync sweeps; worth a glance that the fix is durable.
- **Net**: syncs have been 100% `completed` since 2026-05-08 (3,290 on 2026-05-11 alone, 0 failed). So not currently broken — but those 8,505 failed rows are pure noise; fold their removal into the `sync_history` prune CIO already wants.

### N-2 (Low) — `connection_log.mac_address = 'profile:daily'` on 19 rows (both Pi and server)
19 `connection_log` rows have the string `'profile:daily'` in the `mac_address` column (which otherwise holds `00:04:3E:85:0D:FB`). Looks like a profile-change event being logged into `connection_log` with the profile name jammed into the wrong column. It's a Pi-side write bug that propagated to the server via sync. Pi has 19, server has 19 (same rows). Fix the Pi-side logging; clean the rows in the V0.28 cleanup.

### N-3 (Low, structural) — the Pi has no `schema_migrations` table at all
Server-side has 8 tracked migrations (`schema_migrations`, versions 0001-0008). The Pi's `obd.db` has **no migration-history table** — the Pi schema evolves via `CREATE TABLE IF NOT EXISTS` + ad-hoc scripts, with no recorded version. So Pi schema drift (code-expected vs Pi-actual) is invisible, and there's no way for a deploy to know what's pending on the Pi. (This is the structural form of the old "manual SQL fix not in migration history" concern.) Recommend the Pi get a `schema_migrations` table too, populated retroactively to its current state, so future migrations are tracked symmetrically.

### N-4 (Low) — Pi still has the `battery_log` table (empty); server dropped it
Migration `0003` ("drop battery_log — dead Pi-only BatteryMonitor table; superseded by battery_health_log") ran server-side. The Pi never dropped it — `battery_log` still exists on the Pi with 0 rows. Schema drift; remove it on the Pi in the V0.28 cleanup.

### N-5 (Low, but it's the hook for the V0.27.7 sync-chattiness fix) — `pi_state.no_new_drives` exists but isn't gating sync
The Pi has a `pi_state` table with one row: `no_new_drives = 0`. That's exactly the flag CIO wants ("if sync successful and no new drive, no need to sync"). But it's `0` and the sync keeps running every ~26 s (3,290 sweeps on 2026-05-11). So the mechanism is half-built — the flag is written, not consumed. The B-NEW-2 fix (sync cadence not idling) has a concrete hook: wire `pi_state.no_new_drives` into the sync trigger so it short-circuits when there's nothing new since the last successful sync.

### N-6 (Low, schema semantics) — server `battery_health_log.start_soc`/`end_soc` hold VCELL voltage, not SOC%
Server `start_soc`/`end_soc` values are 3.4-4.2 (LiPo cell voltage). The Pi-side renamed these to `start_vcell_v`/`end_vcell_v` in US-289 to fix exactly this semantic, but the server schema still calls them `start_soc`/`end_soc` — so the sync maps `start_vcell_v` → `start_soc`, and anyone querying the server expecting a 0-100 percentage gets a voltage. CIO's review covered `source_id`/`source_device` on this table but not this. Rename the server columns to `start_vcell_v`/`end_vcell_v` to match the Pi (or compute a real SOC% from a discharge curve and keep both).

### N-7 (Low) — `statistics`: 63 of 84 rows have NULL `drive_id`; type mismatch with `drive_statistics`
75% of `statistics` rows (per-PID-per-profile aggregates) aren't tied to a drive. Also `statistics.drive_id` is `bigint(20)` while `drive_statistics.drive_id` is `int(11)` — pick one type when these get FK'd to `drives`.

### N-8 (Low) — `drive_summary.profile_id` is NULL on every row
No drive records which profile it ran under, even though the Pi knows it (`statistics.profile_id='daily'`, realtime_data carries `profile_id`). Part of the I-026 server-analytics-fields-not-populated cluster — flag for US-326 to also populate `profile_id`.

---

## NEW — design smells for the V0.28 DB-arch discussion (no fix needed now, just noting)

- **D-1**: `statistics` (per-PID-per-profile, has `analysis_date`) and `drive_statistics` (per-PID-per-drive, has `computed_at`) overlap conceptually. `statistics` is populated and working (84 rows, recent); `drive_statistics` is empty. US-328 may just need to wire the existing aggregation to *also* emit drive-scoped rows — or the two should be consolidated. Worth deciding before building a separate `drive_statistics` writer.
- **D-2**: `connection_log` mixes BT-connection events (`connect_attempt`/`connect_failure`/`connect_success`/`disconnect`) with drive-lifecycle events (`drive_start`/`drive_end`). That's why it carries a `drive_id` column. Drive lifecycle arguably belongs in `drives`.
- **D-3**: parameter-name inconsistency in `realtime_data` — `O2_B1S1` (shorthand) vs `O2_BANK1_SENSOR2_V` (longhand + `_V` suffix) for the two O2 sensors. Normalize.
- **D-4**: the `unit` column is overloaded as an enum label for some PIDs — `FUEL_SYSTEM_STATUS` has `unit` ∈ {`CL`, `OL`, `OL-drive`} (status, not a unit); `MIL_ON` has `unit='OFF'`. Plus minor capitalization drift (`O2_B1S1` unit `volt` vs `O2_BANK1_SENSOR2_V` unit `V`). If the status-vs-unit overload is intentional (it's how python-obd represents these), at least make it consistent.
- **D-5**: `static_data` table on the Pi is empty (0 rows). What's it for? Remove or populate.
- **D-6**: the **entire analysis-output tier is empty** — `ai_recommendations`, `analysis_history`, `anomaly_log`, `alert_log`, `trend_snapshots`, `calibration_sessions`, `baselines`, `drive_statistics` = 8 tables, 0 rows total, after 11 drives + DTC probing. CIO flagged `baselines` + `drive_statistics`; the other 6 are equally empty. Some of this is expected (calibration needs ≥5 real drives), but `analysis_history` / `anomaly_log` / `trend_snapshots` being empty after this much data suggests the analysis pipeline (Spool's Ollama-driven layer) has never actually run end-to-end on a real drive. Worth confirming whether it's wired at all — separate from the V0.28 schema work, but it's the biggest "is this tier even alive?" question in the system.
- **D-7**: `power_log` + `startup_log` + `pi_state` + `static_data` are Pi-only — they never sync to the server. `battery_health_log` (the drain *summary*) syncs, but the granular `power_log` (every power-source transition, every drain stage event) and `startup_log` (boot reasons) stay on the Pi. If the server is meant to be the system-of-record / analysis hub, that forensic data is stranded. Decide whether `power_log`/`startup_log` should sync too.
- **D-8**: `drive_summary` carries 3 overlapping column families — `device_id`(varchar) / `source_device`(varchar) / `source_id`(int) / `drive_id`(int), and `start_time` / `drive_start_timestamp`. Untangling which column the analytics writer should populate is part of US-326's pre-flight; collapsing them is part of the V0.28 `drive_summary`→`drives` rename. Related: `drive_annotations.drive_id` references the *Pi* drive id (3-10), but server `drive_summary.drive_id` is NULL (the Pi id lives in `source_id`), so `drive_annotations` currently can't be joined to `drive_summary` on `drive_id`. The I-026 fix (populating `drive_summary.drive_id`) repairs that join.

---

## Verdict on "is there anything else?"

Yes — the eight N-items and eight D-items above. None of them is a fire (the live data is clean, syncs are succeeding, Drive 11 captured well). They're the long tail of a schema that grew organically across 30+ sprints. The two I'd actually act on outside the V0.28 epic: **N-5** (it's the concrete fix for the V0.27.7 sync-chattiness bug) and a quick look at **D-6** (confirm the analysis tier is wired — that's a "does a whole feature exist" question, not cosmetics). Everything else rides the V0.28 schema-normalization epic.

Filed to the tester findings/; cross-referenced in the PM follow-up `offices/pm/inbox/2026-05-12-from-tester-db-review-validation-bug-vs-techdebt.md` lineage and the V0.28 memory note.
