---
id: F-081
parent: E-OPS
status: pending
renamedFrom: B-081
createdAt: 2026-05-27
updatedAt: 2026-05-27
---

# B-081: ELM ATRV alternator-voltage proxy for engine-on/off detection

| Field        | Value         |
|--------------|---------------|
| Priority     | Low (P3)      |
| Status       | Pending (V0.28+ candidate) |
| Category     | obdii / engine-state detection / forensic |
| Size         | S-M           |
| Dependencies | (none — independent of I-033 fix; complementary not substitute) |
| Created      | 2026-05-14    |
| Source       | Spool A2AL PM note 2026-05-13 (`offices/pm/inbox/archive/2026-05-13-from-spool-drive-12-analysis-bt-reconnect-bug.md`) |

## Description

Poll `ELM ATRV` (adapter-level battery-voltage probe; doesn't require ECU comms) at a low cadence (e.g. every 10-30 s) even when `DriveDetector` is idle / `ObdConnection` is between drives. Use the result as a **positive engine-state indicator** independent of BT-link state and ECU response:

- `ATRV >= 13.0V` sustained N samples → engine running (alternator charging)
- `ATRV < 13.0V` sustained N samples → engine off
- Adapter unreachable (timeout / null) → unknown

Today the only Pi-side engine-on signal is the existing US-242 / B-049 `BATTERY_V > 13.80V × 3 samples` escalation, which requires a working ECU query path. When the BT link drops (e.g. mid-trip engine cycle, see I-033) the ECU path is dead but the ELM adapter itself still answers ATRV. Adding ATRV as an alternate signal closes the forensic gap.

## Rationale

Per Spool's 2026-05-13 PM note: "fuse-box wiring erased the Pi-side engine-on/off forensic signal; `power_log` AC blips ambiguous; need positive engine-state indicator independent of BT-state." Also applies to **debug/wall-power scenarios** (Pi powered without an engine cycle in scope), confirmed by CIO 2026-05-13.

Complementary to **I-033** (BT-no-reconnect after engine cycle, US-338 in Sprint 36). I-033 fixes the missing reconnect path; B-081 adds the engine-state evidence even when the reconnect path is healthy, so we can audit "did the engine actually cycle?" from the Pi-side data alone.

## Acceptance Criteria

- [ ] Pre-flight: confirm ELM ATRV query latency is bounded (< 1 s) and survives adapter-without-ECU state
- [ ] Add `_pollElmAtrvCadence` (configurable interval, default 15-30 s) that fires when DriveDetector is in idle / between-drives state
- [ ] Persist ATRV samples + derived `inferred_engine_state` to a new column on an existing low-rate table (likely `power_log` or a new `adapter_voltage_log`)
- [ ] Synthetic regression test exercises: engine-on inferred when 3 consecutive ATRV >= 13.0V; engine-off inferred when 3 consecutive ATRV < 13.0V; unknown when adapter unreachable
- [ ] IRL gate: post-deploy, query the new table after a 2-leg trip and confirm the engine-cycle is visible in the ATRV trace (one of the V0.27.10 follow-up validation drives is sufficient)

## Cross-references

- I-033 (BT-no-reconnect; US-338 in Sprint 36 / V0.27.10) — complementary fix
- B-049 / US-242 (existing `BATTERY_V > 13.80V` escalation; ECU-path-dependent)
- B-076 (V0.28 schema normalization epic — may want to coordinate the new column or table with that work)
