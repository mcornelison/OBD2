# B-049: drive_detect idle-poll gap — engine-on never detected in idle-poll

| Field        | Value                  |
|--------------|------------------------|
| Priority     | High (P0 for Sprint 20) |
| Status       | Pending grooming       |
| Category     | obd / pi-collector     |
| Size         | M                      |
| Related PRD  | None (Sprint 20 candidate; couples with B-050, B-051 — possibly bundled) |
| Dependencies | None                   |
| Filed By     | Marcus from Spool inverted-power drill 2026-04-29 |
| Created      | 2026-04-29             |

## Description

During Spool's 2026-04-29 inverted-power drill, the engine ran ~1 minute with full alternator-charging signature visible at the OBD adapter level (BATTERY_V=14.4V, cranking dip 11.4V), the BT/OBD adapter was connected throughout, **but `drive_start` never fired and zero ECU PIDs were captured**.

Root cause: the orchestrator's idle-poll mode only queries `BATTERY_V` (via ELM_VOLTAGE / ATRV — adapter-level, ECU-independent). The drive_detector fires `drive_start` when ECU-dependent PIDs (RPM, COOLANT_TEMP, etc.) start responding — but in idle-poll mode, those PIDs are never queried, so the signal never appears.

This is a **chicken-and-egg gap**: between drives, the orchestrator doesn't query the ECU. So even if the engine starts, the orchestrator doesn't ask the ECU about it, so it doesn't notice. drive_start fires only after the orchestrator already noticed engine-on, which it can't notice without querying the ECU.

**Why this matters for production (post-B-043 wiring):** every key-on = Pi power-on (cold boot or near-cold). On boot, the orchestrator goes service-start → BT-connect → first health check → idle-poll. There's a window where the engine is already running but the orchestrator hasn't yet escalated. Currently that window is unbounded — the orchestrator stays in idle-poll forever unless something kicks it out. **Result: every drive would silently lose all ECU data.**

This is bigger than a Sprint 20 nice-to-have. It's a **silent data-loss bug that activates the moment B-043 wiring lands**.

## Acceptance Criteria

- [ ] Orchestrator escalates idle-poll → active-poll automatically when engine-on is detected (no operator action)
- [ ] drive_start fires within N seconds of engine-on (suggested target ≤30s)
- [ ] First ECU PID values land in `realtime_data` within N seconds of engine-on
- [ ] In bench/idle scenario (no engine), idle-poll stays idle — no spurious drive_start, no K-line flooding
- [ ] Synthetic test mocks alternator-active BATTERY_V signature OR mocks an ECU PID arriving and asserts escalation fires (per `feedback_runtime_validation_required.md` — mocks must operate at hardware-signal level, not at orchestrator-state-machine level)

## Recommended Fix Shape (per Spool — Rex iterates)

Two viable approaches (Spool leans (a)):

**(a) BATTERY_V threshold trigger**: when `BATTERY_V > 13.8V sustained for N samples` (alternator-active signature), escalate idle-poll → active-poll AND probe ECU PIDs.
- Pros: uses existing data, no extra polling cost during off-state.
- Cons: 13.8V threshold is car-specific. Drive 5 baseline shows this car's alternator hits 14.0V on bulk-charge so 13.8V is safe; other cars vary. Per-vehicle config key.

**(b) Periodic ECU probe in idle-poll**: every N seconds (suggested 30s — slow enough not to flood K-line, fast enough to catch engine-start within a tolerable window), query a single ECU-dependent PID (RPM is the canonical choice). If response received, escalate. If timeout, stay idle.
- Pros: more robust, doesn't depend on voltage thresholds.
- Cons: K-line probe activity even when Pi sits idle for hours. Theoretical battery-drain contribution; small but non-zero.

Spool's recommendation: (a) for this car because BATTERY_V is already polled and the alternator signature is unmissable (14.4V vs 12.7V is huge). (b) is the "more correct" architecture but heavier implementation.

## BATTERY_V signature reference (this car, from Drive 5 + 2026-04-29 drill)

| State | BATTERY_V |
|---|---|
| Engine off, battery rest | 12.7-12.8V |
| Cranking dip | ~11.4V (single sample) |
| Engine on, alternator bulk-charge | 14.4V |
| Engine on, alternator float | 13.5-13.7V |

Threshold of `>13.8V sustained` cleanly distinguishes engine-on from any engine-off state.

## Validation Script Requirements

- **Input**: Pi running in idle-poll mode (post-boot, pre-engine-start). Engine starts.
- **Expected Output**: within ≤30s, drive_start fires, drive_id minted, ECU PIDs (RPM, COOLANT_TEMP, MAF) appear in `realtime_data`.
- **Database State**: new `connection_log` entry with `event_type='drive_start'`. New `drive_summary` row (note: depends on B-051 / US-228 fix shipping — until then drive_summary may still NULL out metadata).
- **Test Program**: synthetic test with mocked `getBatteryVoltage()` returning [12.7, 12.7, 11.4, 14.4, 14.4, 14.4] over time → assert orchestrator transitions idle→active and probes ECU.

## Related

- **B-043** (Pi auto-sync + conditional shutdown) — silent data-loss activates on B-043 wiring
- **B-050** (PowerMonitor DB-write activation) — sister Sprint 20 candidate; possibly bundle
- **B-051** (UpsMonitor slow-drain + flap-debounce / US-235 rescope) — sister Sprint 20 candidate
- **US-216** (Power-Down Orchestrator) — orchestrator's idle-poll mode is the same code path that needs fixing here
- **US-200** (drive_id minting / engine_state machine) — drive_detector this story modifies
- **Source note**: `offices/pm/inbox/2026-04-29-from-spool-inverted-power-drill-findings-and-us235-correction.md` Section 5

## Notes

- **Bundle decision** for Sprint 20: Spool suggests B-049, B-050, B-051 may go as a single "power-mgmt revision bundle". PM grooms at Sprint 20 load.
- **Pre-condition for meaningful drain test**: until B-049 + B-050 land, drain tests will continue to look identical to the 4 prior drains — Pi never sees a real drive, never escalates, never fires staged shutdown.
