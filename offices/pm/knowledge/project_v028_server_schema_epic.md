---
name: V0.28+ server schema normalization epic owed
description: When V0.28.0 grooming starts, remind Mike (CIO) about the deferred obd2db schema-normalization epic. Don't let it get lost behind the V0.27 chain.
type: project
originSessionId: 069dbac4-0805-4c13-b136-6ea5fc23af10
---
**Reminder for V0.28.0**: surface this to Mike when V0.27 finishes and V0.28 grooming begins.

On 2026-05-12 Mike did a full review of the server `obd2db` schema (notes captured at `offices/tester/inbox/db review fom Mike.txt`) and split the work: the data-flow **bugs** (drive_summary server-side analytics fields NULL, drive_statistics empty + no Pi table, drive_counter stale, startup_log prior_boot_clean regression, US-323 backfill not wired, plus the chatty connection_log / sync_history loops) go in **V0.27.7** (sprint33, US-326..330 + possible B-NEW-1/2/3); the **schema-architecture refactor** is its own **V0.28+ "server schema normalization" epic** — V0.27.X is bug-fixes-only.

The epic's scope (from Mike's note, as relayed to Marcus in `offices/pm/inbox/2026-05-12-from-tester-db-review-validation-bug-vs-techdebt.md`):
- Rename `vehicle_info` → `vehicles`; drop `source_id`; add `display_name`; going forward `vehicles.id == devices.id`.
- Rename `drive_summary` → `drives`; `device_id` → `vehicle_id` (FK → vehicles).
- Standardize `source_id` → `vehicle_id` (FK → vehicles) across ai_recommendations, alert_log, calibration_sessions, battery_health_log, dtc_log, profiles, realtime_data, statistics.
- Drop `source_device` column everywhere it appears (the string device name).
- `connection_log`: `source_id` → `device_id` (FK → devices); drop `source_device`.
- `sync_history.device_id`: varchar → int (FK → devices).
- `statistics.profile_id`: varchar → int (FK → profiles); reconcile `statistics.drive_id` (bigint) vs `drive_statistics.drive_id` (int).
- `drive_statistics.drive_id`, `drive_annotations.drive_id`: FK → drives.
- `devices`: add `ip_address`, `os`, `os_version`.
- `trend_snapshots`: add `vehicle_id` (FK → vehicles).
- **DROP TABLE `drive_counter`** — server-side only. The **Pi-side** `drive_counter` SQLite table stays (it mints `nextDriveId`); only the perpetually-stale server mirror is dropped. Reconcile with V0.27.7 US-329 (currently "compute from drive_summary"): retarget US-329 to "stop maintaining server counter; consumers use MAX(drive_id) FROM drives", and the DROP TABLE lands in this epic.
- One-time data cleanup: remove the 3 ghost `drive_summary` rows (id 12/13/14, drive_id NULL, is_real 0) + re-derive the partial Drive-11 row; truncate `connection_log`; prune `sync_history`.

This is a coordinated multi-table migration that touches the server ORM models, the Pi→server sync column mappings (US-194 `_renamePkToId` etc.), and both tiers — needs its own migration plan + a Drive-N re-validation. Marcus was asked to file it as a backlog item; verify it exists when V0.28 grooming starts, and ping Mike either way.

## Open design discussion to revisit at V0.28 (Mike, 2026-05-12)

Mike's position to carry into the V0.28 DB-arch / design-best-practices discussion:

- **`drive_counter` (BOTH Pi-side and server-side) probably shouldn't exist at all.** Its only job is "what's the next drive id" — and `drive_summary` (→ `drives`), if set up correctly, already provides that: the `drive_id` column should be an auto-increment PK, so the next id is implicit. "Next drive?" = `SELECT MAX(drive_id) FROM drives` (or just let the INSERT auto-assign). So the counter table is redundant on both tiers. (This goes further than what was relayed to Marcus — that note kept the Pi-side counter; Mike now questions that too. Resolve at V0.28.)
- **`drives` needs a `vehicle_id` column, and `(drive_id, vehicle_id)` should be the uniqueness constraint** — not `drive_id` alone. I.e. two rows with `drive_id = 1` are fine as long as they're different `vehicle_id`s. (Implication: `drive_id` is per-vehicle, not global; whatever mints it must scope by vehicle. This interacts with how the Pi assigns drive ids and how the sync maps them server-side.)
- Don't refactor any of this before V0.28 — V0.27.X is bug-fixes only. When V0.28 grooming starts: have this discussion (drive_counter removal both sides, the composite-uniqueness key, broader DB arch + design best practices) WITH Mike before designing the migration.

## Additional V0.28 candidates from the 2026-05-12 data-profiling pass

(Full detail: `offices/tester/findings/2026-05-12-obd2db-data-profile-additional-findings.md`. These are *on top of* Mike's DB-review list above.)

Bugs/hygiene: (N-1) `sync_history` is 42% failed rows (8,505 — historical, root causes fixed by migration 0006 + a since-resolved `realtime_data` "Record has changed" optimistic-lock race; fold the failed-row removal into the sync_history prune; verify the race fix is durable). (N-2) `connection_log.mac_address='profile:daily'` on 19 rows (Pi-side write bug, propagated to server) — fix the logging + clean the rows. (N-3) Pi has NO `schema_migrations` table — give it one, populated retroactively, so Pi schema drift is trackable. (N-4) Pi still has the zombie `battery_log` table (server dropped it via migration 0003) — drop it on the Pi. (N-5) `pi_state.no_new_drives` flag exists but isn't wired to gate sync — wiring it IS the V0.27.7 sync-chattiness fix (B-NEW-2). (N-6) server `battery_health_log.start_soc`/`end_soc` hold VCELL voltage not SOC% (Pi renamed to `start_vcell_v`/`end_vcell_v` in US-289; server didn't) — rename server cols to match. (N-7) `statistics` has 63/84 rows with NULL `drive_id`, and `statistics.drive_id` is bigint vs `drive_statistics.drive_id` int. (N-8) `drive_summary.profile_id` NULL on every row.

Design smells: `statistics` vs `drive_statistics` overlap (statistics works, drive_statistics empty — consolidate, or US-328 just wires the existing aggregation to also emit drive-scoped rows); `connection_log` mixes BT-connection events with `drive_start`/`drive_end` lifecycle events; parameter-name inconsistency (`O2_B1S1` vs `O2_BANK1_SENSOR2_V`); `unit` column overloaded as enum label for `FUEL_SYSTEM_STATUS`/`MIL_ON`; Pi `static_data` table empty (purpose?); **the entire analysis-output tier is empty after 11 drives** — `ai_recommendations`/`analysis_history`/`anomaly_log`/`alert_log`/`trend_snapshots`/`calibration_sessions`/`baselines`/`drive_statistics` all 0 rows — confirm the Ollama analysis pipeline is even wired (D-6); `power_log`/`startup_log`/`pi_state`/`static_data` are Pi-only and never sync — decide whether `power_log`/`startup_log` should reach the server; `drive_summary` carries 3 overlapping column families (`device_id`/`source_device`/`source_id`/`drive_id`, `start_time`/`drive_start_timestamp`) and `drive_annotations.drive_id` (Pi id) can't currently be joined to server `drive_summary.drive_id` (NULL; Pi id is in `source_id`).
