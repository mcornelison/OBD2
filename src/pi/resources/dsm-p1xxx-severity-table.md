# DSM P1xxx Severity Table — Spool SSOT (DTC viewer S-1 / S-3 data)

**Author**: Spool (Tuning SME) · **Date**: 2026-06-05 · **Vehicle**: 1998 Eclipse GST, 4G63 turbo, **manual F5M33**, ECU MD326328 (ECMLink)
**Consumed by**: DTC viewer feature (`severity` + `clear_eligible` + `suggested_fix` + `fix_provenance` columns). Companion to `dtc-display-clear-safety-advisory.md`.
**Grounding**: code list = [troublecodes.net Mitsubishi](https://www.troublecodes.net/mitsu/) (scoped to "95 Eclipse Turbo / 96–98"), cross-checked vs DSM community knowledge. Severity / clearable / suggested-fix columns are **Spool-validated** (`fix_provenance = spool-validated`). Descriptions are the manufacturer text python-obd can't supply for P1xxx.

> **Why this matters**: python-obd's `DTC_MAP` returns an EMPTY string for every P1xxx (manufacturer-specific). Without this table a DSM-specific code shows on the Pi as a bare `P1xxx` with no text, severity, or fix. This is the curated subset.

---

## Engine-relevant P1xxx (CAN set on our manual 4G63)

| Code | Description (mfr) | Severity | Clearable | Suggested fix (Spool) |
|---|---|---|---|---|
| **P1103** | Turbocharger Wastegate **Actuator** | 🟡 WATCH → **🔴 if overboost** | No¹ | Boost-control fault. Inspect wastegate actuator can + rod + its vacuum line. **Don't WOT** until diagnosed — a stuck-closed actuator overboosts the TD04 into detonation. Pull over if boost climbs/surges. |
| **P1104** | Turbocharger Wastegate **Solenoid** (boost-control solenoid) | 🟡 WATCH → **🔴 if overboost** | No¹ | Check the boost-control solenoid + its vacuum lines + connector (commonly disturbed during intake work). Usually fails to wastegate spring pressure (low boost = safe), but verify boost isn't spiking. |
| **P1105** | Fuel Pressure Solenoid | 🟡 WATCH → **🔴 if lean under load** | No¹ | Fuel-pressure control fault. You run an aftermarket FPR + lines — check its wiring/vacuum + fuel pressure. A lean condition under boost = detonation; watch trims, don't WOT until verified. |
| **P1300** | Ignition Timing Adjustment circuit | 🟡 WATCH → **🔴 if knock** | No¹ | Timing-adjustment connector/circuit. Verify base timing is set and ignition timing is sane — a timing reference fault can advance into knock under load. |
| **P1400** | Manifold Differential Pressure (MDP) Sensor circuit | 🟡 WATCH | No¹ | EGR-system pressure sensor. Emissions/driveability, not an engine-damage path. Check MDP sensor + EGR plumbing. *If EGR is deleted/disabled in the ECMLink tune, this may be config noise.* |
| **P1500** | Alternator FR Terminal circuit | 🟡 WATCH | No¹ | Charging-system monitor. Check alternator + charging; watch `BATTERY_V` (healthy 13.5–14.5 V running). Not engine-damaging but a dead alternator eventually strands you. |
| **P1600** | Serial Communication Link | 🟡 WATCH | No¹ | ECU↔TCM/diagnostic comms. Affects diagnostics, not engine protection. Check comms wiring/connectors. |

¹ **None of these are "clear-and-forget."** P1xxx are circuit/system faults — clearing (Mode 04) only blanks the light; the code returns next drive cycle until the underlying fault is fixed. The clear button stays **disabled** while any of these is stored (they're 🟡, above MINOR). Fix first, then the light clears itself.

## Automatic-transmission P1xxx — **N/A on this car** (manual F5M33)

These exist in the Mitsubishi P1xxx namespace but **cannot set on our manual-transmission car** — flag them as not-applicable if ever seen (would indicate a misread or wrong-vehicle data, not a real fault):

| Code | Description (mfr) | Disposition |
|---|---|---|
| P1715 | Pulse Generator Assembly (A/T) | N/A — auto-trans only |
| P1750 | Solenoid Assembly (A/T) | N/A — auto-trans only |
| P1751 | A/T Control Relay | N/A — auto-trans only |
| P1791 | Engine Coolant Temp Level Input → TCM | N/A — auto-trans only |
| P1795 | Throttle Position Input → TCM | N/A — auto-trans only |

---

## Notes for the feature
- **Condition-dependent severity** (P1103/P1104/P1105/P1300): base tier 🟡, escalates to 🔴 under a specific condition (overboost / lean-at-load / knock). This is exactly the "severity chip + caveat line" Iris built into the detail view — render the caveat, don't flatten to a bare tier.
- **No 🟢 MINOR / clearable P1xxx** here — the clearable-once-logged codes on this car are generic evap (P0440/P0442/P0455, e.g. the P0443 we just cleared), which carry their own python-obd descriptions.
- **ECMLink caveat**: the loaded tune can suppress/alter EGR (P1400) and boost-control behavior. Treat this table as the *factory* meaning; ECMLink config may change which codes are live.
- **Extensible**: this is the confirmed vehicle-class subset. Add codes only when grounded in an authoritative source (factory manual / ECMtuning / DSMtuners) — never fabricate a P1xxx meaning ([[feedback-pin-units-before-magnitude-claims]]).
