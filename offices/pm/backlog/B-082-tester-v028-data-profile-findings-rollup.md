# B-082: Tester's V0.28+ data-profile findings — rollup (8 bugs + 8 design smells)

| Field        | Value         |
|--------------|---------------|
| Priority     | Mixed (1 Medium, rest Low) |
| Status       | Pending (V0.28+ schema-normalization epic; folds into B-076 work) |
| Category     | data quality / schema hygiene / multi-item rollup |
| Size         | L (16 sub-items across the rollup; not all need to ship together) |
| Dependencies | B-076 (server schema normalization epic) is the natural home for most sub-items |
| Created      | 2026-05-14    |
| Source       | `offices/tester/findings/2026-05-12-obd2db-data-profile-additional-findings.md` |

## Description

The tester profiled all 21 server tables + the Pi-side schema 2026-05-12 and surfaced 16 items the V0.27 chain didn't already cover. Per the tester's own verdict: **none block V0.27.7; all V0.28+ candidates**. Rather than file 16 individual B-items, this rollup B-item is the index — full detail lives in the findings file.

## Sub-items (see findings file for full evidence per item)

### Bugs / data-quality

| Tag | Sev | Title |
|---|---|---|
| N-1 | Medium | `sync_history` 42% failed rows (8,505 historical); resolved structurally by migration 0006 — needs prune |
| N-2 | Low | `connection_log.mac_address = 'profile:daily'` on 19 rows (Pi-side write bug; cleanup) |
| N-3 | Low | Pi has no `schema_migrations` table; symmetric to server's 8-version table |
| N-4 | Low | Pi still has empty `battery_log` table; migration 0003 missed Pi side |
| N-5 | Low | `pi_state.no_new_drives` written but not consumed — **DEDUP: already filed as B-078** (skip in rollup) |
| N-6 | Low | Server `battery_health_log.start_soc`/`end_soc` hold VCELL voltage (US-289 fixed Pi side; server didn't follow) |
| N-7 | Low | `statistics` 63 of 84 rows have NULL drive_id + int/bigint type mismatch with `drive_statistics` |
| N-8 | Low | `drive_summary.profile_id` NULL on every row — extend US-326 server writer |

### Design smells

| Tag | Sev | Title |
|---|---|---|
| D-1 | Low | `statistics` (per-PID-per-profile) vs `drive_statistics` (per-PID-per-drive) overlap — design call gates B-075 |
| D-2 | Low | `connection_log` mixes BT-connection + drive-lifecycle events; drive-lifecycle should move to `drives` |
| D-3 | Low | Parameter-name inconsistency in `realtime_data` (`O2_B1S1` vs `O2_BANK1_SENSOR2_V`) |
| D-4 | Low | `unit` column overloaded as enum label for FUEL_SYSTEM_STATUS, MIL_ON |
| D-5 | Low | Pi `static_data` table empty (0 rows) — decide populate or drop |
| D-6 | **Important** | **Entire analysis-output tier empty after 11 drives** (ai_recommendations, analysis_history, anomaly_log, alert_log, trend_snapshots, calibration_sessions, baselines, drive_statistics). Is this whole feature wired? **Discover-first item.** |
| D-7 | Low | `power_log`/`startup_log`/`pi_state`/`static_data` are Pi-only; decide if they should sync |
| D-8 | Low | `drive_summary` overlapping column families (device_id/source_device/source_id/drive_id + start_time/drive_start_timestamp); drive_annotations FK gap |

## Acceptance Criteria (when this rollup ships)

- Each shipped sub-item references its tag (N-X or D-X) and the findings file as source
- Sub-items that fold into B-076 don't need separate B-### IDs — they become stories under B-076's PRD
- The findings file becomes the canonical spec for sub-item scope; PR descriptions link back
- D-6 (analysis-tier verify) may need to ship FIRST since it's a "discover-first" question, not a fix

## Notes

- Tester's two items "worth acting on outside V0.28 epic": N-5 (already in B-078) and D-6 (analysis-tier verify). Everything else rides B-076.
- This rollup B-item exists for **traceability** so the findings file isn't orphaned in `offices/tester/findings/`; when B-076's PRD is groomed, this rollup's sub-items get absorbed as stories.
