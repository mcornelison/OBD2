---
id: F-084
parent: E-OPS
status: pending
renamedFrom: B-084
createdAt: 2026-05-27
updatedAt: 2026-05-27
---

# B-084: Pre-flight PID probe session + opt-in additional PIDs (OIL_TEMP, FUEL_RATE, FUEL_RAIL_PRESSURE, ETHANOL_PERCENT, AMBIENT_AIR_TEMP, ABSOLUTE_LOAD)

| Field        | Value         |
|--------------|---------------|
| Priority     | Medium (P2 — Ralph recommendation: MEDIUM for V0.28.x patch sprint)    |
| Status       | Pending (V0.28+ candidate) |
| Category     | (see body)    |
| Size         | S (probe) + S-M per adopted PID        |
| Dependencies | (see body)    |
| Created      | 2026-05-14    |

## Description

One-time probe session on the 2G 4G63 ECM to determine which of these PIDs return real values vs `null`/`not supported`. We currently use ~10 of the 90 standard PIDs the `python-obd` library supports.

**Candidate PIDs:**
- `OIL_TEMP` (PID 0x5C) — directly useful for turbo tuning + thermal-runaway warnings
- `FUEL_RATE` (PID 0x5E) — enables real-time fuel-consumption + instant-MPG readout on the display
- `FUEL_RAIL_PRESSURE` (PID 0x22/0x23) — direct knock-margin / lean-condition indicator on E85
- `ETHANOL_PERCENT` (PID 0x52) — automates pump-gas/E85 dual-map switching detection if supported
- `AMBIENT_AIR_TEMP` (PID 0x46) — better cold-start semantics than IAT-at-startup
- `ABSOLUTE_LOAD` (PID 0x43) — alternative to MAF-derived load; more accurate at WOT

**Workflow:** US-199 supported-PID probe infrastructure already exists. Run the probe. Then file individual stories for each supported PID with writer + display + Spool prompt update.

**Source:** Ralph (Rex) PM note 2026-05-14 — research dive into `brendan-w/python-OBD` library. Approved by CIO for backlog entry.


## Acceptance Criteria

To be detailed at PRD grooming. See source notes for evidence + thresholds + rationale.
