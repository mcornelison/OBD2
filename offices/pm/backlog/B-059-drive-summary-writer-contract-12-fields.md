# B-059: drive_summary writer 12-field contract enforcement (Spec 3)

| Field        | Value                  |
|--------------|------------------------|
| Priority     | High                   |
| Status       | Pending (V0.27.3 reservation per CIO 2026-05-09) |
| Category     | database / analytics   |
| Size         | M                      |
| Related PRD  | None                   |
| Dependencies | V0.27.2 must merge first (US-304 fixed Pi-side metadata path; this story fixes the server-side analytics writer) |
| Created      | 2026-05-09             |

## Description

Spool 2026-05-09 Spec 3: defines what `drive_summary` *correct* looks like from a tuner consumer's perspective. The 12-field contract is the non-negotiable bar for the analytics writer.

**Why a separate story (not amended into V0.27.2 US-304)**: V0.27.2 US-304 fixed the Pi-side defer-INSERT cold-start metadata path (`ambient_temp_at_start_c` / `starting_battery_v` / `barometric_kpa_at_start` now populate). But there's a SECOND failure layer Ralph didn't address: the SERVER-side analytics writer (`src.server.services.analysis._ensureDriveSummary` per Spool's pointer) that's supposed to populate fields 3-8 (`start_time` / `end_time` / `duration_seconds` / `row_count` / `is_real` / `data_source`).

Spool's housekeeping note Item 2 (P1 reclassification, 2026-05-09): drives 3+4+5 currently have rows where ALL the analytics columns are NULL. The Pi-sync side wrote keys; the analytics path that fills the rest never ran.

Per CIO 2026-05-09 directive: split this into V0.27.3 to keep V0.27.2 focused on the bug-fixes already in flight.

## Required behavior at drive-end (Spool's spec, frozen)

When a drive ends, the analytics writer MUST populate (in this order, atomically if possible):

1. `device_id` - the Pi
2. `drive_id` - the Pi-local counter (already present)
3. `start_time` - timestamp of first realtime_data row for this drive
4. `end_time` - timestamp of last realtime_data row for this drive
5. `duration_seconds` - (end_time - start_time) in seconds
6. `row_count` - COUNT(*) from realtime_data WHERE drive_id = N
7. `is_real` - TRUE if >95% of rows in drive carry data_source='real', FALSE otherwise
8. `data_source` - dominant value across rows (mode, not avg)
9. `drive_start_timestamp` - Pi-captured cranking entry timestamp (Pi-sync writes; analytics doesn't override)
10. `ambient_temp_at_start_c` - Pi-captured at cranking entry (V0.27.2 US-304 fixed)
11. `starting_battery_v` - Pi-captured at cranking entry (V0.27.2 US-304 fixed)
12. `barometric_kpa_at_start` - Pi-captured at cranking entry (V0.27.2 US-304 fixed)

## Race / partial state semantics (Spool's spec, frozen)

The Pi-sync path writes columns 1-2 + 9-12 first; analytics writes 3-8 second. Both paths MUST respect `_PRESERVE_ON_UPDATE` (per existing `sync.py` contract) so Pi-sync re-syncing later doesn't clobber analytics columns.

If analytics fires BEFORE Pi-sync (race), analytics inserts a fully-populated row with NULLs in 9-12; Pi-sync later UPSERTs into the same row by `(source_device, source_id)` and only overwrites NULLs in its own columns.

## Insufficient-data semantics

If `row_count < 100`:
- Still write the row.
- Set `is_real` = NULL (not FALSE - distinguishes "skipped" from "tested and failed").
- Spool's grading queries treat `row_count < 100 OR is_real IS NULL` as "drive not gradable, skip."

If `start_time IS NULL` after analytics fires (no realtime_data rows exist for this drive):
- Drive_summary row is effectively a stub. Set all stats columns to NULL, `is_real = FALSE`, write a row anyway.
- Spool's grading queries treat this as "data capture failed, escalate."

## Acceptance Criteria

- [ ] Server-side `_ensureDriveSummary` (or whichever analytics writer Rex finds) populates fields 3-8 for every drive_summary row within 30s of drive_end (or sync arrival, whichever is later)
- [ ] All 5 existing drive_summary rows (drives 3, 4, 5, 6, 7) get repopulated correctly when the writer fix ships
- [ ] A future drive captured post-fix has all 12 fields populated by drive_end + sync round-trip completion
- [ ] `_PRESERVE_ON_UPDATE` race-handling preserved -- Pi-sync re-sync doesn't clobber analytics columns + analytics first-write doesn't clobber Pi-sync columns
- [ ] Insufficient-data semantics: `row_count < 100` writes `is_real=NULL`; `start_time IS NULL` writes stub row with `is_real=FALSE`
- [ ] Integration test asserts Spool-spec 12-field contract end-to-end (Pi capture -> sync -> analytics -> 12 fields populated)
- [ ] Backfill script repopulates the 5 existing drives' rows (drive_id 3-7) without losing pre-existing keys

## Validation Script Requirements

- **Input**: completed drive (Drive 9 or later post-V0.27.3 deploy)
- **Expected Output**: drive_summary row with all 12 fields non-NULL where data is available
- **Database State**: `SELECT * FROM drive_summary WHERE drive_id = N` returns full per-drive context; JOIN with realtime_data filtered on drive_id matches `row_count`
- **Test Program**: integration test exercises Pi capture -> sync to chi-srv-01 -> analytics writer -> 12-field assertion

## What this contract DOES NOT cover

- The downstream `drive_statistics` writer (separate consumer; spec it later)
- Anomaly detection in `anomaly_log` (depends on baselines table existing first; see I-018)
- AI prompting in `analysis_history` (depends on drive_summary being correct; separate spec for prompt construction)

## V0.27.3 Sprint reservation

Per CIO 2026-05-09: V0.27.3 will be "yet another bug-fix sprint" continuing the patch-version chain (V0.27.0 feature -> V0.27.1 hotfix -> V0.27.2 6-bug fix -> V0.27.3 follow-up). B-059 is the LOAD-BEARING P0 of V0.27.3. Other V0.27.3 candidates currently filed:

- I-018 calibration.py stdlib types.py shadow + missing baselines table (P1; two-part fix)
- B-058 connection_log noise re-profile (P3; passive audit, may not need code change)

Plus whatever else surfaces in V0.27.2 IRL validation (Drive 8) or post-deploy.

## Notes

**Source**: `offices/pm/inbox/archive/2026-05/2026-05-09-from-spool-three-specs-mod-state-drive-annotations-drive-summary-contract.md` Spec 3 + `2026-05-09-from-spool-post-cleanup-housekeeping-findings.md` Item 2 (P1 reclassification).

**Spec 3 is consumer-defined** (what tuning analysis NEEDS) rather than implementation-prescribed (HOW to write it). Ralph's V0.27.3 implementation follows the contract; the contract doesn't dictate which file the writer lives in. Ralph runs pre-flight audit to find the actual writer and applies the standing rule (lock at the resource owner, not the caller).

**Pointer for Ralph's investigation** (per Spool): `src.server.services.analysis._ensureDriveSummary` is supposed to fire at drive-end via the auto-analysis trigger. Either the trigger isn't wired, the function bails early, or the auto-analysis path is dead. Pre-flight audit confirms which.

**Why this matters now**: Without drive_summary 12-field correctness, downstream is blocked:
- `analysis_history` = 0 rows (AI analysis blind)
- `drive_statistics` = 0 rows (per-drive per-parameter stats don't exist)
- Any "Spool, grade Drive 8" workflow joining `realtime_data` with `drive_summary` gets nulls

V0.27.3 unblocks the analytics + AI path.
