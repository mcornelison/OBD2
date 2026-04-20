# I-016: Coolant temperature stayed at 73-74°C (163-165°F) — below full op temp during Session 23 capture

| Field        | Value                     |
|--------------|---------------------------|
| Severity     | Medium (potential hardware concern; not yet confirmed — could be capture-window artifact) |
| Status       | Open — awaiting more data (next live drill) |
| Affected     | Physical vehicle (1998 Eclipse GST) — possibly stuck-open thermostat. Code side: none. |
| Discovered   | 2026-04-19 Session 23 first-light drill, preserved in `data/regression/pi-inputs/eclipse_idle.db` |
| Filed by     | Ralph (Rex), Session 71, 2026-04-20, at CIO direction during Tier 1 knowledge read |

## Symptom

During Session 23's first-light Eclipse OBD drill, coolant temp read **73-74°C (163-165°F) flat** across the ~110-second captured window. Full operating temperature for a 4G63 is 88-93°C (190-200°F) with a stock 190°F thermostat.

`specs/grounded-knowledge.md` (Warm-Idle Fingerprint section, line 151) flagged the value at drill-close:

> "⚠ Below full op temp (180°F+). Capture window was short; flag for next drill — if still below 180°F after sustained warmup, investigate thermostat."

Per-parameter Session 23 measurement (grounded-knowledge.md §"Measured Eclipse 4G63 Idle Values"):

| Parameter | Samples | Min (°C) | Max (°C) | Avg (°C) |
|-----------|---------|----------|----------|----------|
| COOLANT_TEMP | 14 | 73.0 | 74.0 | 73.7 |

14 samples over ~110 seconds, all within a 1°C band — no warming trend observed within the window.

## Root cause hypothesis (three candidates)

1. **Capture-window artifact** (most likely benign). Engine-on wall-clock for Session 23 was ~10 minutes total; OBD-connected window was ~3.5 minutes (per TD-027 Thread 1 investigation); actual steady-state idle within that was shorter. Engine may not have reached full op temp before the drill ended — especially in a Chicago spring ambient (reported 14°C IAT). Coolant on a cold start can plateau below thermostat-open temperature for several minutes before opening.

2. **Thermostat stuck open** (hardware concern). On 2G DSMs, a thermostat that fails open is a known failure mode — the engine circulates coolant through the radiator continuously, never reaching op temp in mild ambient conditions. DSMTuners community has multiple threads on this. Symptoms: coolant plateaus at ambient+~50°C indefinitely, heater output is weak in winter, fuel economy suffers, and the ECU runs rich (open-loop-below-op-temp map) longer than it should.

3. **Thermostat missing entirely** (less common but documented for 2G). Some prior-owner maintenance yanks the thermostat to "fix" overheating; the actual symptom is the opposite.

## Impact

- **Tuning accuracy**: Spool's interpretation of Session 23's data (in `offices/tuner/knowledge.md` "This Car's Empirical Baseline" + `offices/pm/inbox/2026-04-19-from-spool-real-data-review.md`) was made with the coolant value as-measured. If the engine was actually cold when Spool graded the fingerprint as "warm idle," later recommendations built on that baseline carry the error forward.
- **Future drills**: every subsequent drill comparing coolant trend against this baseline will look anomalous until the thermostat question is resolved.
- **Summer 2026 E85 conversion**: E85 runs cooler (more efficient latent heat of vaporization) and raises the bar on cooling-system verification before adding more fuel. A cooling-system audit is implicit in the E85 prep regardless; this issue sharpens the scope.

## Suggested action

**Near-term** (can be handled during Sprint 15 US-208 "first-drive + post-drive analytics" story, activity-gated on CIO driving):
1. During US-208 first-drive drill, run engine at idle (or at operating RPM) for **at least 10-15 minutes sustained**, not stopping for OBD-connection churn. Target: enough warmup time that thermostat should definitely have opened if functional.
2. Log coolant trend across the whole window. If coolant plateaus ≥180°F (82°C) and stays there, thermostat is fine — Session 23 was just a too-short-window artifact, and this issue can close as benign.
3. If coolant stays below 180°F after 15+ minutes sustained, promote to confirmed hardware concern:
   - File a diagnostic plan (cooling-system audit: thermostat, radiator fan operation, coolant level, sensor verification via known-good reference thermometer).
   - Coordinate with Spool to re-grade the Session 23 fingerprint with the correction in mind (warm-idle becomes "cold engine" and affected parameter interpretations get re-anchored).

**Longer-term** (summer 2026 E85 prep): bundle thermostat verification into the cooling-system readiness check that's implicit in adding E85 capability.

## Tracking

- grounded-knowledge.md line 151 is the symptom record; this file is the investigation record.
- Spool's pending-research list (auto-memory `project_spool_pending_research.md`) already has "2G thermostat diagnostic" as a deferred item. This issue supersedes that in concreteness.
- US-208 (Sprint 15) first-drive + post-drive analytics is the natural venue to collect the confirmation/refutation data. No separate story needed today — attaching to US-208's acceptance would overshoot. Log the extended warmup as a drill-protocol addendum when Marcus finalizes the US-208 contract.
