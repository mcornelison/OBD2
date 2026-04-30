# B-048: MAX17048 SOC% calibration learning run protocol + scripts

| Field      | Value                                                              |
|------------|--------------------------------------------------------------------|
| Status     | Pending PRD grooming                                               |
| Priority   | P1 (Sprint 19+ candidate; precondition for SOC%-based ladder if we ever revert from VCELL)   |
| Filed By   | Marcus (PM), 2026-04-29 from Spool consolidated note               |
| Filed Date | 2026-04-29                                                         |

## Why

Spool's 4 drain tests across 9 days produced a quantified calibration gap:

| Moment | SOC% reported | VCELL measured | Reality |
|---|---|---|---|
| Drain 4 start | 73% | 3.720V | Already partially discharged |
| Drain 4 end | 57% | 3.376V | At/past LiPo knee |
| Post-replug recharge | 64% | 4.202V | Full charge, gauge stuck |
| Drive 5 start | 60% | 4.200V | Full charge, **40-pt error** |
| Drive 5 end | 71% | 4.201V | Gauge slowly creeping up |

40-percentage-point divergence between gauge SOC% and reality (VCELL truth) means SOC%-based shutdown thresholds (US-216's WARNING/IMMINENT/TRIGGER at 30/25/20%) cannot work — the gauge could read "73%" while the real battery is at 3.72V (true ~50% on a 1S LiPo).

Sprint 19 will switch US-216's trigger to VCELL (Spool recommendation, B-048-related). This backlog item captures the LONG-TERM fix: run the MAX17048 ModelGauge learning sequence so SOC% becomes trustworthy on this specific hardware setup. After learning, future stories could revert to SOC%-based thresholds if desired (more user-friendly than VCELL volts).

## Scope (preliminary — full PRD pending Spool spec)

### US-X (S, Spool authors spec)
**Calibration procedure spec.**
- Spool authors detailed procedure: full-charge target (4.20V terminal), controlled discharge to known endpoint (~3.30V), full-recharge with specific MAX17048 register writes to enable ModelGauge learning.
- Output: a runbook in `offices/tuner/` describing the procedure step-by-step.

### US-Y (M, Ralph implements scripts)
**Calibration drill scripts.**
- `scripts/calibrate_max17048.py` — wraps the procedure: monitors VCELL/SOC during full-charge, controlled discharge, recharge cycle. Writes register configuration values per Spool's spec. Logs everything to `battery_health_log` with `load_class='calibration'`.
- `scripts/verify_calibration.py` — post-procedure verification: read register state, compare gauge SOC% vs VCELL truth at known points, report drift.
- Tests: simulate the procedure path against a Fake MAX17048 reader; verify register-write sequence.

### Action items (NOT sprint stories per Sprint 18 rule)
- CIO physically runs the procedure: ~several hours per cycle, multiple cycles for ModelGauge convergence.
- May need to coordinate with car-accessory wiring (B-043 hardware task) so calibration runs against the production power source.

## Dependencies

- **Sprint 19 US-216 trigger-source change SOC→VCELL** — interim fix. After it ships, US-216 works on VCELL while B-048 calibration is in progress.
- **CIO time** — multiple hours of monitored Pi runtime; non-trivial.

## Open design questions

1. **Where does calibration data land?** `battery_health_log` with `load_class='calibration'`? Or a new `calibration_log` table? Recommend `battery_health_log` with the existing enum extended.
2. **Procedure cadence** — once-and-done at deployment time, or recurring (annual, after replacement)? LiPo cells drift over time. Recommend: one initial calibration to fix today's gauge; revisit if drift returns.
3. **Failure recovery** — if calibration procedure is interrupted (Pi crash, power loss), the register state may be partial. Need a verify-and-resume path. Or just re-run from scratch (safer, longer).

## Related

- US-184 (UpsMonitor power-source detection) — Sprint 11; current heuristic uses CRATE + VCELL slope; CRATE register confirmed unreliable per Spool drain tests, this story may eliminate CRATE usage entirely
- US-216 (Power-Down Orchestrator) — Sprint 16; uses SOC% thresholds today, will switch to VCELL in Sprint 19 (interim) until B-048 lands the calibration that makes SOC% trustworthy again
- B-043 (Pi auto-sync + conditional shutdown) — gated on car-accessory wiring; B-048 calibration may want to coordinate with B-043's wiring to test against production power source
- TD-031 / US-223 (deleted dead BatteryMonitor) — Sprint 17 cleared the wrong-threshold dead code; B-048 fills the calibration gap that made BatteryMonitor wrong in the first place
