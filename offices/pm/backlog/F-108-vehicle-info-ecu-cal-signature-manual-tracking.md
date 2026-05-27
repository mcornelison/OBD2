---
id: F-108
parent: E-OPS
status: pending
renamedFrom: B-108
createdAt: 2026-05-27
updatedAt: 2026-05-27
---

# B-108: vehicle_info ECU + Calibration Signature Manual-Tracking Field

| Field        | Value                  |
|--------------|------------------------|
| Priority     | Medium (V0.28+; needed once a SECOND ECU/EPROM has been on the car -- already true as of 2026-05-22 swap; lineage data we need to start capturing) |
| Status       | Pending (V0.28 grooming candidate; weaves into B-076 schema-normalization epic per Atlas 2026-05-22) |
| Category     | server / schema / vehicle-identity |
| Size         | S (one schema field + manual stamp CLI + analytics join surface) |
| Related PRD  | None yet; design context in Atlas's 2026-05-22 Mode22/Mode09 ECU-lineage note + Spool's 2026-05-22 capability-probe findings |
| Dependencies | B-076 V0.28 schema-normalization epic (sibling under that umbrella); coordinates with B-107 + B-106 + B-109 as one coherent V0.28 schema pass |
| Created      | 2026-05-22 (Atlas + Spool joint flag following CIO ECU swap mid-session) |

## Description

The 1998 Eclipse GST ECU returns **NO RESPONSE** to Mode 09 PIDs (VIN, Calibration ID, CVN, ECU Name) per Spool's 2026-05-22 OBD capability probe. **Cannot auto-fingerprint ECU or EPROM via OBD-II on this hardware path.** Same is likely true for any 1990s-era OBD-II vehicle without modern Mode 09 support.

This is a **permanent fact of this hardware path**, not a today-only condition. Any ECU/calibration lineage tracking we want must be a **manual** `vehicle_info.ecu_signature` / `vehicle_info.cal_signature` field — CIO-input or operator stamp at the time of swap.

CIO swapped from prior modified-EPROM ECU to a different modified-EPROM ECU on 2026-05-22 after V0.27.18 drill PASS. **As of today, two ECUs have been on the car within the data history.** Without lineage tracking, all per-ECU calibration drift (e.g., B-106 derived odometer + B-076 SPEED-PID-per-ECU calibration column) loses the join key. **B-108 is the join key.**

## Acceptance Criteria

- [ ] `vehicle_info` table on server adds `ecu_signature TEXT NOT NULL` (free-form CIO-provided identifier; e.g., "stock-modified-EPROM-2024-prior", "ECMLink-V3-friendly-modified-EPROM-2026-05-22")
- [ ] `vehicle_info` table adds `cal_signature TEXT NULL` (optional finer-grained calibration version when applicable; e.g., "tune-v2.3-93oct"; NULL when same as default for the ECU)
- [ ] `vehicle_info` adds `ecu_install_timestamp_utc TIMESTAMP NOT NULL` + `ecu_removal_timestamp_utc TIMESTAMP NULL` (NULL = currently installed)
- [ ] Constraint: exactly one row per (`ecu_signature`, install timestamp) has `ecu_removal_timestamp_utc = NULL` (the currently-active ECU)
- [ ] CLI: `python -m server.cli.stamp_ecu_swap --signature "<id>" --cal-signature "<id-or-null>" --as-of "YYYY-MM-DD"` records a swap event (closes prior row + opens new row)
- [ ] CLI: `python -m server.cli.show_ecu_lineage` lists all historical ECU stamps
- [ ] Backfill seeded with 2 known rows: (a) the prior ECU active before 2026-05-22 swap, (b) the current new ECU active from 2026-05-22 onward
- [ ] Server analytics join surface: `drive_summary` joins `vehicle_info` on `drive_summary.start_time_utc BETWEEN vehicle_info.ecu_install_timestamp_utc AND COALESCE(vehicle_info.ecu_removal_timestamp_utc, NOW())` — so any per-drive analytics can identify which ECU was active
- [ ] Spool sign-off on the signature naming convention before backfill (his lane: ECU/cal/tune identity semantics)

## Validation Script Requirements

- **Input**: Backfill seed with 2 rows (prior ECU + new ECU 2026-05-22 swap); existing drives 1-24 join to prior ECU; drives 25+ join to new ECU
- **Expected Output**: `SELECT drive_id, ecu_signature FROM drive_summary JOIN vehicle_info ON ...` returns expected partition (drives 1-24 = prior, drives 25+ = new)
- **Database State**: `vehicle_info` has exactly one row with `ecu_removal_timestamp_utc = NULL` at any point in time
- **Test Program**: stamp-ECU-swap CLI exercises round-trip; idempotent re-run produces zero diff

## Cross-references

| Item | Relationship |
|---|---|
| **B-076 V0.28 schema-normalization epic** | Atlas 2026-05-22: "One coherent V0.28 schema pass" includes B-076 + B-107 + B-108 + B-109 + Spool's `drive_summary.drive_id` smell. Same surface area; should land together. |
| **B-106 derived signals (acceleration + odometer)** | B-106 acceptance criterion now depends on B-108: derivations must look up active ECU to apply correct calibration factor. |
| **B-107 DriveDetector dual-attribution** | Sibling V0.28.0 schema pass; same migration cycle. |
| **B-076 SPEED-PID-per-ECU calibration column** (proposed by Spool 2026-05-22) | The SPEED-PID calibration table keys off `ecu_signature` field this item adds. |
| **Spool's 2026-05-22 capability-probe note** | Source of the "Mode 09 NO RESPONSE → manual tracking required" finding |
| **Atlas's 2026-05-22 ECU-lineage grooming FYI** | Architectural framing; concur on one-coherent-pass approach |

## Notes

- **Free-form text, not enum**: ECU/EPROM identifiers are not standardized across the modder community. CIO writes whatever identifies the configuration to him. Spool reviews semantics.
- **Spool's separate observation flagged for B-076 PRD**: `drive_summary.drive_id` NULL on new-compute-path rows + `drive_statistics.drive_id` is actually `summary_id` (FK to `drive_summary.id`). Same schema-pass surface area. PM Rule 10 design-gate territory at sprint time.
- **NOT in scope here**: ECU MIL state, DTC history, freeze-frame capture (those belong to B-109 + Mode 02/03/07 work).
- Filed per Atlas + Spool joint flag 2026-05-22 following CIO ECU swap mid-session.
