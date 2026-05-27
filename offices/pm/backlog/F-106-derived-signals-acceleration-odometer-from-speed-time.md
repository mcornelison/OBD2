---
id: F-106
parent: E-OPS
status: pending
renamedFrom: B-106
createdAt: 2026-05-27
updatedAt: 2026-05-27
---

# B-106: Derived Signals From Speed + Time — Acceleration + Estimated Odometer (with CIO Factual Recalibration)

| Field        | Value                  |
|--------------|------------------------|
| Priority     | Medium (placeholder while OBD-II doesn't expose; high-value once data accumulates) |
| Status       | Pending (V0.30+ candidate; lands with or alongside Spool's Topic B Maintenance Tracking spec) |
| Category     | server / analytics / derived-signals |
| Size         | M (server compute + Pi event log + CIO entry CLI + calibration logic) |
| Related PRD  | None yet; design lives in `docs/superpowers/specs/2026-05-21-maintenance-tracking-design.md` (Spool's `vehicle_mileage_log` subsystem covers the odometer half) + new design owed for acceleration half |
| Dependencies | B-104 Step 1 (server analytics authority) DEPLOYED ✓; ideally lands with or shortly after Maintenance Tracking umbrella |
| Created      | 2026-05-22 (CIO directive) |

## Description

The OBD-II PID set on the 1998 Eclipse GST does not expose acceleration or odometer directly. **But we have speed (VSS PID 0x0D) and we have time (timestamp_utc on every realtime_data row).** Per CIO 2026-05-22: derive both signals analytically and calibrate the odometer against CIO-provided factual readings (weekly or monthly fill-up reads).

Two derived signals, one item:

### 1. Acceleration (NEW signal — not in Spool's existing spec catalogue)

- Server-computed from realtime_data: `acceleration_mps2 = (speed[t+1] - speed[t]) / (timestamp[t+1] - timestamp[t])` in m/s² (or G's).
- Polling rate is ~4-5 Hz per OBD-II constraints (ISO 9141-2; see `specs/obd2-research.md`); sample spacing should be smoothed across N samples to avoid bouncy values at K-Line jitter.
- Useful for: 0-60 capture per drive, jerk (d²speed/dt²), tuning correlation (acceleration vs. RPM + load + AFR), and feeds Spool's anomaly engine (Topic A) as a sibling envelope to LTFT / knock-retard.
- Persisted in `drive_summary` (peak / avg / 0-60 best / acceleration distribution) and/or `drive_statistics` per parameter envelope.

### 2. Estimated odometer (overlap with Spool's Topic B — see below)

- Per-drive distance: `distance_m = Σ (speed[t] × Δt)` across the drive (numerical integration).
- Cumulative odometer: running sum of per-drive distances, anchored to a CIO-provided starting fact ("odometer at install date = N miles").
- **Calibration loop**: CIO provides periodic factual readings (weekly or monthly fill-ups; e.g., "odometer at 2026-06-01 = N miles"). System computes drift = `(estimated - fact) / fact` and applies a multiplicative correction factor for the post-recalibration window. Tracks drift trend across recalibrations so we can quantify the estimate's confidence interval over time.
- **This is already partially designed**: Spool's Topic B Maintenance Tracking spec includes `vehicle_mileage_log` as a hybrid subsystem with **manual entry (CIO logs at fill-ups) + speed-integration estimate during drives + drift detection at 5% over 90+ days + future Telegram proactive prompts via B-099**. The architectural shape, table design, and entry surface are already spec'd there.
- The acceleration half here is the genuinely new addition; the odometer half is best implemented as part of Topic B's `vehicle_mileage_log` subsystem (don't duplicate).

CIO acknowledged it won't be perfect: "if the OBD2 doesn't have it, this would be a good placeholder."

## Acceptance Criteria

- [ ] **Acceleration**: Server compute path derives per-row `acceleration_mps2` from `realtime_data.speed_kph` + `timestamp_utc` for each drive; smoothing window documented + Spool-reviewed for tuning-noise tradeoff.
- [ ] **Acceleration**: `drive_summary` columns added — `peak_acceleration_mps2`, `avg_acceleration_mps2`, `peak_deceleration_mps2`, `best_0_to_60_seconds` (NULL when drive never reached 60 mph).
- [ ] **Acceleration**: `drive_statistics` row written per drive for `acceleration_mps2` parameter (min/max/avg/std_dev + outlier envelopes via `computeBasicStats` 2σ per Spool FLAG-1 disposition).
- [ ] **Odometer**: Per-drive `estimated_distance_m` computed via numerical integration of speed × Δt; persisted in `drive_summary` (NEW column).
- [ ] **Odometer**: Cumulative odometer estimate computed across all drives, anchored to a single CIO-provided starting fact (e.g., "odometer_anchor": {"odometer_miles": 145000, "as_of_timestamp_utc": "2026-05-22T00:00:00Z"}); stored in a project-config table (new `vehicle_odometer_calibration` or rolled into Spool's `vehicle_mileage_log` if Topic B lands first).
- [ ] **Calibration**: CLI accepts CIO factual readings — `python -m server.cli.log_odometer_fact --miles N --as-of YYYY-MM-DD`. Calibration record persists with computed drift% at time of entry.
- [ ] **Calibration**: Drift correction factor applied to estimates in the window between two calibration events (multiplicative scaling within window; not retroactive across all history).
- [ ] **Calibration**: Drift trend tracked — N calibration events produce a confidence band on the current estimate (e.g., "estimated odometer 152,300 ± 1.8% based on 6 recalibrations over 8 months").
- [ ] **Validation**: Backfill across existing drives 11-24 produces sensible cumulative distance + a per-drive distance distribution Spool reviews against his car-knowledge mental model.
- [ ] **Telegram (optional, B-099-gated)**: Proactive nudge "remind CIO to log odometer monthly" — defer if B-099 delayed.

## Validation Script Requirements

- **Input**: A backfill recompute over drives 11-24 (post-Sprint-41-deploy state, where all 14 drives have realtime_data + per-row speed + timestamps).
- **Expected Output**: 14 drive_summary rows with non-NULL `estimated_distance_m` + `peak_acceleration_mps2` etc.; cumulative odometer estimate produced; arithmetic verification against a hand-computed 1-2 reference drives.
- **Database State**: `drive_summary` rows have non-NULL derived-signal columns; `vehicle_odometer_calibration` (or Topic B's `vehicle_mileage_log`) has 1+ anchor row from CIO + any subsequent factual readings.
- **Test Program**: A `compute_drive_signals.py` CLI that re-runs derivation; idempotent re-run produces identical output (per US-350 idempotency pattern).
- **Reference drives for hand-verification**: Drive 11 (knock-retard reference, 10,839 rows, 23m24s duration — produces a clean reference distance/acceleration profile).

## Cross-references to existing backlog + design specs

| Item | Relationship |
|---|---|
| **Spool's Topic B Maintenance Tracking spec** (`docs/superpowers/specs/2026-05-21-maintenance-tracking-design.md`) | **Owns the odometer half via `vehicle_mileage_log` subsystem**. Manual entry + speed-integration estimate + 5%/90-day drift detection are already spec'd there. This B-106 item should land WITH or alongside Topic B for shared infrastructure (entry CLI, drift table, optional Telegram nudge). The acceleration half is the genuinely new addition. |
| **B-074** MAP PID 0x0B addition | Adds another derived-signal opportunity (load-band sharpening) sibling to this work. |
| **B-083** Mahalanobis baseline scoring | Acceleration becomes another envelope dimension feeding the multivariate distance metric when B-083 lands V0.28+. |
| **B-089** GEM-4 engine grade per drive | Acceleration peaks could be a weighted input to grade computation. |
| **B-099** Telegram bidirectional | Calibration prompts ride this infrastructure when it lands. |
| **B-104 Step 1** | Architectural foundation; this is Step 2+ work (server-side compute over raw realtime_data). |

## ⚠ Material complication discovered 2026-05-22 afternoon (post-filing): SPEED PID calibration drift per-ECU

CIO swapped to a different modified-EPROM ECU mid-session (post-V0.27.18 deploy, post-Argus drill PASS). Spool's OBD capability probe + Drive 26 telemetry surfaced: **the new ECU's SPEED PID reads approximately 2× actual ground speed.** Likely cause: modified EPROM has different VSS calibration constants (non-OEM tire-size / speedometer-gear assumption).

**Impact on B-106 derivations:**

- **Acceleration**: a = d(speed)/dt; if speed is 2× off, so is acceleration. Direct propagation.
- **Per-drive distance**: `Σ (speed × Δt)` will be 2× over-reported on Drive 25+ until calibration captured.
- **Cumulative odometer**: drifts at ~2× rate until next CIO factual recalibration absorbs the drift.

**Why the calibration-loop design absorbs this gracefully (not by design but by accident)**: the multiplicative correction factor + drift-trend tracking the spec already calls for **will compensate** for per-ECU SPEED calibration drift over time. Each CIO factual reading recalibrates the post-recalibration window. The system's confidence interval widens during the unknown-calibration window then sharpens after recalibration.

**Why the calibration-loop is NOT sufficient on its own**: across ECU swap events, the correction factor is discontinuous. A single drift trend across ECU boundaries will look noisy/wrong. The fix: a **SPEED-PID-per-ECU calibration column** (proposed for B-076 schema normalization epic — see Spool's 2026-05-22 ECU-swap note) that lets analytics auto-apply a multiplicative correction factor based on which ECU was active during a drive. Cross-link below.

**Acceleration is similarly affected** but the fix is identical (apply the same per-ECU correction factor to derived signals).

**Acceptance criterion addition (V0.30+ PRD time):**

- [ ] **Per-ECU calibration awareness**: derivation queries the active `vehicle_info.ecu_signature` (B-108 manual tracking; see V0.28 grooming anchors) for each drive AND the SPEED-PID-calibration table (B-076 expansion) to apply the appropriate correction factor before integration
- [ ] **GPS-correlation seed value for new ECU**: CIO captures GPS ground-speed vs OBD-reported-speed on next drive; correction factor seeded in calibration table; Spool reviews + signs

## Notes

- **PM lean (CIO call at grooming time)**: Best landing strategy is probably to merge this into Spool's Topic B Maintenance Tracking umbrella when that gets a B-### filed, treating odometer as one subsystem and acceleration as a sibling derived-signals subsystem. Avoids fragmenting the shared infrastructure (drift table, entry CLI, recalibration logic). Alternatively, keep separate and explicitly note the shared-wiring dependency at PRD time. **CIO ratified 2026-05-22: defer split-decision to grooming.**
- **Spool review owed at grooming**: Spool owns tuning thresholds + the smoothing window for acceleration (sample-count + jitter handling); his `[EXACT:]` discipline applies if numeric thresholds appear in the spec.
- **PM Rule 10 design-gate territory** when this enters a sprint — server analytics surface change; `specs/architecture.md` Data Pipeline section update owed in-sprint.
- **Honest scope**: This is a "placeholder while OBD-II doesn't expose it" feature per CIO 2026-05-22. The accelerometer + true odometer signals will become available if/when CIO adds dedicated hardware (e.g., MPU6050 accelerometer over I²C, GPS module for speed cross-check). Future hardware would supersede this analytical estimate rather than compete with it. ECMLink V3 (summer 2026 planned) may also expose richer signals.
- **Filed per CIO 2026-05-22 verbal directive in PM Session 42** (V0.27.18 deploy session). No design spec yet; one is owed before sprint dispatch.
