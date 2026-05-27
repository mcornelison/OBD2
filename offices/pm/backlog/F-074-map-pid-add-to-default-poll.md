---
id: F-074
parent: E-003
status: pending
renamedFrom: B-074
createdAt: 2026-05-27
updatedAt: 2026-05-27
---

# B-074: Add MAP (PID 0x0B) to default OBD-II poll list (Spool tuning gap)

| Field | Value |
|---|---|
| Priority | High (P1 for tuning analytics) |
| Status | Pending (V0.28+ feature sprint candidate; deferred per V0.27.X bug-fix-only rule) |
| Category | obdii / poll-config |
| Size | XS-S |
| Related PRD | None |
| Dependencies | None |
| Created | 2026-05-12 |

## Description

Spool 2026-05-12 ask after Drive 11 engine analysis: Drive 11 revealed strong knock-retard signature in 4500-5000 RPM range (4G63 mid-range detonation zone). **Quantifying the ECU's response to boost-induced knock requires correlating timing-retard events with actual boost pressure.** Right now we can't measure boost -- only infer it from MAF and engine_load. Gap.

## The Ask

Add **MAP (Manifold Absolute Pressure, PID 0x0B)** to the default OBD-II poll list under `parameter_name='MAP'`, `unit='kPa'`.

| PID | What it tells us | Current state |
|---|---|---|
| **MAP (0x0B)** | Actual manifold pressure in kPa. Above ~100 kPa = boost (psi = (MAP_kPa - BARO_kPa) x 0.145). THE primary boost-pressure signal on any forced-induction engine. | **NOT CAPTURED** |
| ENGINE_LOAD | ECU's calculated load %. Hits 100% at WOT but doesn't quantify pressure | Captured |
| MAF | Air mass flow rate. Useful but doesn't directly give pressure | Captured |
| BAROMETRIC (0x33) | Atmospheric pressure. Captured ONCE at drive_start. For boost math, want continuous. | drive_start snapshot only |

## Why deferred to V0.28+

Per CIO standing rule (`feedback_pm_patch_version_bug_fix_sprint_pattern.md` + V0.27.X = bug-fixes only): V0.27 chain = bug fixes; features defer to V0.28+ stable feature sprint. MAP is a new-parameter ADD (feature shape), not a bug fix.

Spool offered Option A (ride-along V0.27.7) vs Option B (defer V0.28). PM chose B for sprint discipline + the patch-version pattern. MAP starts flowing post-V0.28.0; tuning analytics unlock follows.

## Scope estimate (XS-S)

1. PID config file (likely `src/pi/obdii/pids.py` or `src/pi/obdii/poll_config.py` -- Ralph identifies at pre-flight)
2. Smoke-test confirming 2G ECU responds to Mode 01 PID 0x0B (almost certainly does; MAP universally supported)
3. Verification: `MAP` flows into `realtime_data.parameter_name='MAP'` cleanly through existing pipeline (no schema changes; realtime_data is parameter-key-value)

**No analytics changes required for this story.** Once MAP captured, Spool builds boost analytics in `knowledge.md` + `drive_statistics` consumers.

## Related (also V0.28+ candidates from Spool 2026-05-12 note)

- AMBIENT_AIR_TEMP (PID 0x46) -- IAT-vs-ambient delta (heat-soak detection); needs Mode 01 PID 0x00 supported-PIDs probe first
- FUEL_RAIL_PRESSURE (PID 0x22/0x23) -- fuel system health; may not be supported on 2G DSM
- EVAP_VAPOR_PRESSURE (PID 0x32) -- emissions diagnostics; unlikely supported on 2G

## Acceptance Criteria (when groomed for V0.28+)

- [ ] Pre-flight: rg `pids|poll_config` src/pi/obdii/ -- locate poll list source
- [ ] Mode 01 PID 0x00 supported-PIDs probe confirms 2G ECU supports 0x0B (smoke test before adding)
- [ ] MAP added to default poll list with `parameter_name='MAP'`, `unit='kPa'`, decoder mapping raw byte to kPa
- [ ] Drive captures MAP in realtime_data with parameter_name='MAP'
- [ ] No regression on existing PIDs (timing budget on K-line still meets ~5 PIDs/sec rate)

## Source

- Spool 2026-05-12 inbox note `2026-05-12-from-spool-add-map-pid-to-default-poll-list.md`
- CIO 2026-05-12: "yes send the new pid request to Marcus"
- Drive 11 engine analysis: knock-retard signature observed; MAP needed to quantify
