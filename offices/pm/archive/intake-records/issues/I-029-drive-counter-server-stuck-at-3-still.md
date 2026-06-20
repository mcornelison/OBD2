# I-029: drive_counter server-side STILL stuck at last_drive_id=3 (Pi at 11) -- V0.27.3 US-314 fix incomplete

| Field | Value |
|---|---|
| Severity | Low (P3 per Spool; cosmetic / observability only) |
| Status | Open (V0.27.7 candidate -- Spool Story W) |
| Category | sync / dashboard |
| Found In | sync_log.IN_SCOPE_TABLES (drive_counter NOT in the set) + V0.27.3 US-314 fix scope |
| Found By | PM + Spool 2026-05-12 (ongoing watch-item since V0.27.3 close) |
| Related | V0.27.3 US-314 (drive_counter sync gap); V0.27.4 US-315 (sync UPDATE propagation; doesn't cover drive_counter because not in IN_SCOPE_TABLES) |
| Created | 2026-05-12 |

## Description

Pi-side `drive_counter.last_drive_id=11` (advanced via Drive 11 capture 2026-05-12). Server-side `drive_counter.last_drive_id=3` (stuck since Drive 3 era, 2026-04-23). **8-drive gap.**

V0.27.3 US-314 supposedly fixed this. V0.27.4 US-315 (sync UPDATE propagation) was speculated to fix it as a side-effect. **Neither did.** PM pre-flight in V0.27.4 US-315 grooming confirmed: drive_counter is NOT in sync_log.IN_SCOPE_TABLES -- sync client doesn't try to push it.

## Resolution

Two options (V0.27.7 grooming picks one):

**Option 1** -- Add drive_counter to IN_SCOPE_TABLES + ensure server-side endpoint accepts the single-row UPSERT semantics. Sync pushes whenever Pi advances last_drive_id.

**Option 2** -- Drop drive_counter sync entirely; compute server-side `drive_counter` view from `SELECT MAX(drive_id) FROM drive_summary` at query time. No sync needed; server is always-correct.

PM recommendation: Option 2 (cleaner; one less moving part). Option 1 is closer to current architecture but adds another single-row UPSERT path.

## Acceptance Criteria

- [ ] Pre-flight audit: rg `drive_counter` src/pi/sync/ src/server/api/ src/server/db/ -- enumerate consumers
- [ ] Either: Option 1 (drive_counter syncs from Pi -> server within 60s of drive_id advance) OR Option 2 (server computes from drive_summary; drive_counter table deprecated)
- [ ] Drive 12+ verifies the advance: server shows last_drive_id=N matching Pi-side
- [ ] Drives 4-11 backfilled (if Option 1) OR auto-computed (if Option 2)

## Why P3

Cosmetic / observability for the dashboard. Doesn't block analytics, calibration, or any operational path. But the gap has persisted since Sprint 28 + would be embarrassing to leave unfixed indefinitely.

## Source

- Spool 2026-05-12 Drive 11 validation note (Story W, "P3 + S")
- V0.27.3 US-314 close note + V0.27.4 US-315 watch-item flag
- PM 2026-05-12 server-side query confirmation: `SELECT * FROM drive_counter` returns last_drive_id=3
