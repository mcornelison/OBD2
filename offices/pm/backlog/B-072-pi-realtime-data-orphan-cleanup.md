# B-072: Pi-side realtime_data NULL-drive_id orphan rows cleanup (61,293 rows since Session 10)

| Field        | Value                  |
|--------------|------------------------|
| Priority     | Low (P3)               |
| Status       | Pending (V0.27.6 candidate) |
| Category     | data hygiene           |
| Size         | S                      |
| Related PRD  | None                   |
| Dependencies | None                   |
| Created      | 2026-05-11             |

## Description

Spool 2026-05-11 audit: Pi-side `realtime_data` has accumulated **61,293 NULL-drive_id rows** since Session 10's cleanup (which dropped ~58,885 NULL rows). Sources:

- Reconnect-loop polling (engine-off / no-ECU response moments)
- I-019 DriveDetector warm-restart-cranking gap (1,078 rows for the 5/9 around-the-block test alone)
- Pre-DriveDetector-start grace period rows

**Not poison** -- Spool's tuning analytics filter on `drive_id IS NOT NULL` anyway, so rows are noise rather than data corruption.

## Two fix approaches (Sprint 32 grooming decides)

### Approach 1 — Periodic cleanup task (script-based)

`scripts/cleanup_orphan_realtime_data.py` runs nightly via systemd timer; deletes NULL-drive_id rows older than 24h. Trade-off: rows that surface during a slow drive cycle (e.g., DriveDetector takes >24h to assign drive_id, unlikely but possible) get dropped.

### Approach 2 — Writer-side guard (preventive)

Modify writer to drop engine-off polls before they hit realtime_data. Pros: addresses root cause. Cons: harder to identify "engine-off" cleanly at write time; risks dropping legitimate pre-drive-start rows.

**Recommendation**: Approach 1 for V0.27.6 (simpler, reversible). Approach 2 can follow if Approach 1 surfaces issues.

## Acceptance Criteria

- [ ] Pre-flight: `sqlite3 data/obd.db "SELECT COUNT(*) FROM realtime_data WHERE drive_id IS NULL"` -- confirm current count baseline
- [ ] One-time cleanup script run + verified: NULL-drive_id rows older than 24h removed
- [ ] Periodic cleanup mechanism (cron OR systemd timer) installed; runs nightly without manual intervention
- [ ] Cleanup is idempotent + logs row count before/after
- [ ] Integration test asserts: insert N synthetic NULL-drive_id rows with old timestamps -> run cleanup -> N rows removed

## Validation Script Requirements

- **Input**: Pi-side data/obd.db with mix of NULL-drive_id orphans + valid drive-tagged rows
- **Expected Output**: NULL-drive_id rows older than 24h removed; valid rows preserved
- **Database State**: `SELECT COUNT(*) FROM realtime_data WHERE drive_id IS NULL AND timestamp_ms < NOW() - 24h` returns 0 post-cleanup
- **Test Program**: integration test seeds DB + runs cleanup + asserts counts

## Source

`offices/pm/inbox/archive/2026-05/2026-05-11-from-spool-calibration-cli-pymysql-missing.md` Story C
