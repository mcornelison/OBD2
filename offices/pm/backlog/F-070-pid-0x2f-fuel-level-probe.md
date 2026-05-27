---
id: F-070
parent: E-003
status: pending
renamedFrom: B-070
createdAt: 2026-05-27
updatedAt: 2026-05-27
---

# B-070: PID 0x2F fuel-level probe (auto-populate drive_annotations.fuel_level_at_start)

| Field        | Value                  |
|--------------|------------------------|
| Priority     | Low                    |
| Status       | Pending (V0.28+ feature sprint candidate; pairs with B-057 drive_annotations) |
| Category     | obdii / drive-context  |
| Size         | XS (per Spool: tiny)   |
| Related PRD  | None                   |
| Dependencies | B-057 drive_annotations table (target column to populate); confirm 1998 4G63 reports PID 0x2F |
| Created      | 2026-05-10             |

## Description

Spool 2026-05-10 reminder: probe OBD-II PID 0x2F (fuel level input, percent 0-100). If supported by 1998 4G63 ECU, add to poll set; auto-populate `drive_annotations.fuel_level_at_start` so Spool doesn't have to interview CIO for fuel level on every drive.

## Acceptance Criteria

- [ ] Pre-flight: probe PID 0x2F support on 1998 4G63 (Mode 01 PID 0x00 supported-PIDs response should list it OR direct probe returns valid byte)
- [ ] If supported: add 0x2F to poll set (poll once at drive_start; rarely changes mid-drive)
- [ ] Map raw byte (0-255) to percent (0-100) per OBD-II PID 0x2F spec: `value = raw * 100 / 255`
- [ ] Write to drive_annotations.fuel_level_at_start at drive_start event
- [ ] Backfill not needed (drives 3-10 manually annotated; drives 11+ auto-populate)

## Notes

**XS-sized per Spool**: probe + 1 column write + maybe a unit test. Alternative if PID not supported: leave column NULL + manual interview path stays in place.

**Pairs with B-057** (drive_annotations table) -- ship B-070 same sprint as B-057 for clean integration. V0.28+ feature sprint candidate.

**Source**: Spool 2026-05-10 tuning research note Item D reminder; PID 0x2F mention from earlier Spool note re fuel-level interview load
