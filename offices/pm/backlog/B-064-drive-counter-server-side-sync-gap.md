# B-064: drive_counter server-side sync gap (Pi at 10, server still says 3)

| Field        | Value                  |
|--------------|------------------------|
| Priority     | Low (P3 -- background cleanup; not blocking) |
| Status       | Deferred to B-076 V0.28 schema-normalization epic per BL-016 (2026-05-12) |
| Category     | sync / database hygiene |
| Size         | S                      |
| Related PRD  | None                   |
| Dependencies | None (independent of other V0.27.3 stories) |
| Created      | 2026-05-10             |

## Description

Spool 2026-05-10 housekeeping finding: `obd2db.drive_counter` table on chi-srv-01 says `last_drive_id=3`, but the Pi has minted up through `drive_id=10` (as of 2026-05-09 evening). The mirror writer for that table either isn't running or isn't covered by sync.

**Not blocking**: server can still ingest realtime_data + connection_log just fine. But anyone querying `drive_counter` would get a stale signal.

**Last good sync**: Drive 3 era (2026-04-23 timestamp). Six drives have been minted since (4, 5, 6, 7, 8, 9, 10) without the server-side counter advancing.

## Acceptance Criteria

- [ ] Pre-flight audit: `rg drive_counter src/pi/sync/ src/server/` -- map current sync coverage; identify why mirror isn't firing
- [ ] Pi-side sync: `drive_counter` table covered by SyncClient delta push (or equivalent mirror mechanism)
- [ ] Server-side: `obd2db.drive_counter.last_drive_id` updates on each Pi sync; current value reflects Pi's high-water mark within 60s of sync
- [ ] Backfill: server `drive_counter` updated to current Pi value (10) on next sync after fix
- [ ] Regression test asserts the table appears in sync list + value propagates

## Validation Script Requirements

- **Input**: Pi mints drive_id=N; sync triggers
- **Expected Output**: server `drive_counter.last_drive_id = N` within 60s of sync completion
- **Database State**: `SELECT last_drive_id FROM drive_counter;` on chi-srv-01 matches Pi's most recent drive
- **Test Program**: integration test triggers sync after a synthetic drive completes; asserts server-side value advances

## Notes

**Why P3**: Cosmetic / observability concern. Server's actual data ingestion (realtime_data, connection_log, drive_summary, statistics, dtc_log) is independent of this counter.

**Investigation pointer**: this is likely the same Sweep-5 wiring drift family as US-304 (drive_summary) and US-306 (statistics drive_id NULL). May share root cause (sync table list missing this entry, OR Pi-side writer never updating the row).

**Sprint reservation**: V0.27.3+ candidate alongside other P3 hygiene items. Could fold into the broader "post-V0.27.2 IRL validation hygiene" sweep.

## Source

`offices/pm/inbox/archive/2026-05/2026-05-10-from-spool-three-drives-tonight-power-blocker-drive-counter-clarification.md` (Drive_counter sync gap section)
