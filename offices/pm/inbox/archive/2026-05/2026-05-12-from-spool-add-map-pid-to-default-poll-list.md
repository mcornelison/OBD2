# Add MAP (PID 0x0B) to the default realtime poll list
**Date**: 2026-05-12
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Important (tuning analytics gap, not a bug)

## Context

Drive 11 (2026-05-12T01:10:41Z, captured tonight post-B-063) is the project's first clean car-coupled under-load capture. Engine analysis revealed strong knock-retard signature in the 4500-5000 RPM range — exactly the 4G63 mid-range detonation zone. **The ECU's response to boost-induced knock is the single most important signal for ongoing tuning decisions on this platform.**

Quantifying that response requires correlating timing-retard events with **actual boost pressure**. Right now we can't measure boost — only infer it from MAF and engine_load. That's a gap.

## The ask

Add **MAP (Manifold Absolute Pressure, PID 0x0B)** to the default OBD-II poll list under `parameter_name='MAP'`, `unit='kPa'`.

## Why MAP specifically

| PID | What it tells us | Current capture |
|---|---|---|
| **MAP (0x0B)** | Actual manifold pressure in kPa. Above ~100 kPa = boost (psi above atmospheric = (MAP_kPa − BARO_kPa) × 0.145). THE primary boost-pressure signal on any forced-induction engine. | **NOT CAPTURED** ← this ask |
| ENGINE_LOAD (already captured) | ECU's calculated load %. Hits 100% at WOT — useful but doesn't quantify boost pressure | ✓ captured |
| MAF (already captured) | Air mass flow rate. Useful but doesn't directly give pressure | ✓ captured |
| BAROMETRIC (PID 0x33) | Atmospheric pressure. Already captured ONCE at drive_start (`drive_summary.barometric_kpa_at_start`). For boost math, want continuous (BARO drifts slightly with weather/altitude during a drive). | Captured at drive_start only |

Without MAP, I cannot answer questions like:
- "What boost pressure was running when the ECU pulled 16° of timing at 01:22:30Z?"
- "Did MAP saturate (hit ECU's max-readable boost ceiling)?"
- "Is the wastegate holding target boost or creeping?"
- "How does boost ramp vs. RPM/MAF correlate at 91 octane vs. 93 octane?"

These are core 4G63-tuning questions. MAP is the canonical answer for all of them.

## Scope estimate

**XS, S at most.** Single PID addition to the polling list. Probable changes:

1. PID config file (likely `src/pi/obdii/pids.py` or `src/pi/obdii/poll_config.py` or wherever the polling list lives — Ralph will know).
2. Smoke-test confirming the 2G ECU responds to Mode 01 PID 0x0B (almost certainly does — MAP is one of the most universally-supported OBD-II PIDs, and the 2G's K-line implementation is standard).
3. Verification that `MAP` flows into `realtime_data.parameter_name='MAP'` cleanly through the existing pipeline (no schema changes needed — realtime_data is parameter-key-value).

**No analytics changes required for this sprint.** Once MAP is being captured, Spool can build the boost analytics in `knowledge.md` and feed forward to `drive_statistics` when that's working (V0.27.7 Story Z).

## How to schedule this

Two paths, Marcus picks:

**Option A — Ride along with V0.27.7** if there's capacity. The change is genuinely XS. Risk to bug-fix-sprint focus is low because it's a new-parameter ADD, not a modification of existing logic. Pro: MAP starts flowing for Drive 12+, expanding the engine-side baseline shelf faster. Con: scope creep on a bug-fix sprint.

**Option B — File as V0.28.0 feature** alongside whatever the next feature-sprint theme is. Per the patch-version rule, V0.27.7 is bug-fix only; MAP is a feature ADD. Pro: keeps bug-fix sprint disciplined. Con: MAP doesn't flow until V0.28.0 ships (probably mid-late May).

**My recommendation: Option A** if you can fit it. The XS scope + the analytics-unlock-leverage argues for landing it now. But I defer to your judgment on sprint discipline. Either way works for me.

## Related (do NOT request this round)

For completeness, future PIDs Spool would eventually want — **filed here as backlog candidates, NOT for V0.27.7**:

- **AMBIENT_AIR_TEMP (PID 0x46)** — distinct from IAT (which is captured). Lets us track IAT-vs-ambient delta (heat-soak detection). Less reliably supported on early 2G ECUs; needs a Mode 01 PID 0x00 supported-PIDs probe first.
- **FUEL_RAIL_PRESSURE (PID 0x22 / 0x23)** — fuel system health. May not be supported on 2G DSM.
- **EVAP_VAPOR_PRESSURE (PID 0x32)** — emissions diagnostics. Unlikely supported on 2G but worth probing.

None of these are urgent. MAP is the one that unlocks immediate tuning-domain analytics.

## Sources

- Drive 11 captured 2026-05-12T01:10:41Z — Pi-side + server-side realtime_data both have 10,839 rows but `MAP` is not in the PID inventory
- Spool engine analysis (provided to Mike in conversation tonight 2026-05-12) flagged the gap explicitly: "Without MAP we can't quantify your actual boost pressure (psi over atmospheric). We're inferring boost from MAF + load, but direct measurement is much more useful."
- Mike approved sending this to you: "yes send the new pid request to Marcus" — 2026-05-12.

— Spool
