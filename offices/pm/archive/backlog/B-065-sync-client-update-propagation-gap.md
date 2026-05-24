# B-065: Sync-client UPDATE propagation gap (Pi -> server) for battery_health_log close-events

| Field        | Value                  |
|--------------|------------------------|
| Priority     | Medium (P2)            |
| Status       | Complete (archived 2026-05-14) — V0.27.4 US-315 shipped |
| Category     | sync / database hygiene |
| Size         | M                      |
| Related PRD  | None                   |
| Dependencies | None (independent of V0.27.3 stories; investigation may overlap with US-314 drive_counter sync) |
| Created      | 2026-05-10             |

## Description

Spool 2026-05-10 follow-up to my Drain Test 14 verification: Pi-side `battery_health_log` rows for drains 10/11/12/13/14 ALL show populated `end_timestamp`. **Server-side `obd2db.battery_health_log` shows NULL on `end_timestamp` for all 5.** INSERT propagation fires within 2-5 seconds; UPDATE propagation has NEVER fired since V0.27.2 deployed.

This refines the bug Spool originally reported as "4 of 4 drains unclosed" -- which was wrong-shaped (he queried server-side only and concluded a Pi-tier close-event race existed). Empirical truth: Pi closes correctly; server doesn't sync the close-event UPDATE.

## Evidence (Spool's reproducible 5-of-5 sample, 2026-05-10)

| drain_id | Pi end_timestamp | Server end_timestamp | Server synced_at (INSERT row) |
|---:|---|---|---|
| 10 | 2026-05-10T00:12:33Z ✓ | NULL | 2026-05-10 00:00:59 (2s after INSERT) |
| 11 | 2026-05-10T00:52:28Z ✓ | NULL | 2026-05-10 00:46:16 (4s after INSERT) |
| 12 | 2026-05-10T01:12:43Z ✓ | NULL | 2026-05-10 01:12:30 (2s after INSERT) |
| 13 | 2026-05-10T02:34:59Z ✓ | NULL | 2026-05-10 02:24:47 (5s after INSERT) |
| 14 | 2026-05-10T03:47:44Z ✓ | NULL | 2026-05-10 03:35:42 (4s after INSERT) |

**Pattern**: Every drain INSERT propagates within 2-5s. Zero drain UPDATEs propagate.

## Diagnostic hypothesis

Sync client appears to be **INSERT-only / source_id-monotone**: it picks up new rows fast (high-water-mark cursor advance) but doesn't propagate UPDATEs to existing rows. Two possible architectures:

1. **By design**: sync client never re-syncs already-pushed rows. Bug = server-side close-event UPDATEs (Pi UPDATE on existing row) need a different propagation mechanism.
2. **By implementation gap**: sync client SHOULD propagate UPDATEs but doesn't (e.g., the cursor-advance logic skips rows whose source_id is <= last_synced).

Investigation phase resolves which.

## Why this matters (not just data hygiene)

- Server-side analytics on `battery_health_log` (battery-health trending, drain-runtime decay analysis, baseline calibration) get bad data -- every drain looks unclosed.
- **Drive_summary 12-field contract (B-059 / V0.27.3 US-310) is at risk**: if Pi later UPDATEs a drive_summary row's metadata fields (rare but possible), those updates won't sync. Worth checking proactively as part of B-065 investigation.
- Drive 9's NULL `end_timestamp` on Pi (May 9 morning, Pi died mid-drain) is REAL; every other unclosed-on-server row is a sync artifact. We can't tell those apart without checking Pi directly. That's a bad operational signal -- "show me drains that didn't close cleanly" gives false positives.
- Likely same family as B-064 (drive_counter Pi=10 / server=3) -- another UPDATE-not-syncing case.

## Acceptance Criteria

- [ ] Pre-flight audit: `rg "INSERT INTO|UPDATE.*SET" src/pi/sync/ src/pi/data/sync_log.py` -- map current sync coverage; confirm INSERT vs UPDATE handling
- [ ] Investigation phase confirms hypothesis 1 (by-design INSERT-only) vs hypothesis 2 (implementation gap); document in completionNotes
- [ ] Fix scope per identified hypothesis: hypothesis 1 = add UPDATE propagation pass (e.g., periodic stale-row recheck); hypothesis 2 = correct cursor-advance to detect updated rows
- [ ] Server-side `battery_health_log.end_timestamp` populates within 60s of Pi-side close-event for next drain
- [ ] Backfill server-side `end_timestamp` / `runtime_seconds` for drains 10-14 from Pi-side row data (one-shot script)
- [ ] Regression test: drain test produces Pi close + sync fires + server-side row shows close-event fields populated within 60s; would FAIL pre-fix on the UPDATE propagation gap

## Validation Script Requirements

- **Input**: drain test goes to TRIGGER -> graceful poweroff -> wake-on-power boot -> next sync round-trip
- **Expected Output**: server-side `battery_health_log` row for the new drain has non-NULL `end_timestamp` + `runtime_seconds` + `end_vcell_v` matching Pi-side values within 60s of sync completion
- **Database State**: Pi + server state for the same drain_event_id should match on close-event fields
- **Test Program**: integration test mocks Pi-side close-event -> sync trigger -> server-side row fetch + assert UPDATE propagated

## Notes

**Why filed as V0.27.4 candidate (not V0.27.3)**: V0.27.3 was groomed + shipped + deployed by Ralph 2026-05-10. Adding a story mid-deploy violates branch-discipline + scope-stability. B-065 will groom into V0.27.4 (next bug-fix sprint in the V0.27 chain) once V0.27.3 deploys + Drain Test 15 ratifies.

**Spool's procedure update**: Spool's adding Step 4.6 "verify server-side sync of close-event UPDATE row" to `offices/tuner/drain-test-procedure.md`. Going forward, drain-test post-mortem will check Pi + server in parallel + flag UPDATE-propagation gap immediately.

**Potential overlap with US-314 (V0.27.3 drive_counter sync gap)**: US-314 may be a special case of B-065. Pre-flight on US-314 may surface that the fix is broader than just drive_counter -- if so, US-314's filesActuallyTouched + completionNotes will document scope expansion + B-065 may close as "subsumed by US-314 fix" depending on what Ralph found.

## Source

- `offices/pm/inbox/archive/2026-05/2026-05-10-from-spool-correction-server-side-sync-gap-on-drain-closures.md` (Spool's empirical 5-of-5 evidence + reproduction queries + recommended action)
- B-062 wontfix decision (was previously thought to cover this; doesn't -- B-062 is Pi-tier close-event race, B-065 is server-side sync UPDATE gap)
- Cross-reference: B-064 drive_counter sync gap (V0.27.3 US-314) -- likely related family
