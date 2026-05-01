# TD-033: `telemetry_logger.py` ↔ UpsMonitor plumbing not audited (20-min verify)

| Field        | Value                     |
|--------------|---------------------------|
| Priority     | Low (verify; may be nothing, may be another dead-wire) |
| Status       | **Resolved 2026-05-01 (US-251) — LIVE outcome, documented in specs/architecture.md §13** |
| Category     | code audit                |
| Affected     | `src/pi/hardware/telemetry_logger.py` + `hardware_manager.py:417` (post-Sprint-19 line shift) |
| Filed By     | Marcus (PM), from Spool audit 2026-04-21 |
| Surfaced In  | `offices/pm/inbox/2026-04-21-from-spool-power-audit.md` Section "Latent bugs" TD-E |
| Filed        | 2026-04-21                |
| Resolved By  | Rex (Ralph), Sprint 20 US-251, 2026-05-01 |

## Description

`hardware_manager.py:339` wires `telemetryLogger.setUpsMonitor(upsMonitor)`. Spool's power-mgmt audit did NOT inspect `telemetry_logger.py` — that's a separate module outside the 7-file audit scope.

## What needs verifying

Two possibilities:

1. **telemetry_logger IS logging during drain events** — then there's a data trail from the 2026-04-20 23:49 drain test we haven't checked. Could give more detail on where the power system flipped and when.
2. **telemetry_logger is another dead-wire** — the setUpsMonitor call lands but nothing reads the UpsMonitor references. Another cleanup candidate.

Spool estimated "~20 min of work" to verify.

## Action

Short follow-up audit: read `telemetry_logger.py`, trace where `setUpsMonitor` is consumed, determine if telemetry from drain events is present. Update this TD file with findings + action (close or add to cleanup backlog).

## Priority rationale

Low. Either answer is fine:
- If logging → we get better post-mortem data
- If dead → we get a small cleanup candidate

Not urgent; file so it doesn't get lost.

## Related

- TD-030/031/032 same audit batch.
- Spool audit Section "Latent bugs" TD-E.

## Resolution (2026-05-01, US-251 — LIVE outcome)

### Audit findings

Pre-flight grep (`setUpsMonitor` + `TelemetryLogger`):

| Call site | Status |
|-----------|--------|
| `src/pi/hardware/hardware_manager.py:417` `_telemetryLogger.setUpsMonitor(self._upsMonitor)` | LIVE — fires inside `_wireComponents()` |
| `src/pi/hardware/hardware_manager.py:251` `_initializeTelemetryLogger()` | LIVE — instantiated inside `HardwareManager.start()` |
| `src/pi/hardware/hardware_manager.py:458` `_telemetryLogger.start()` | LIVE — daemon thread spawned inside `_startComponents()` |
| `src/pi/hardware/telemetry_logger.py:392` `self._upsMonitor.getTelemetry()` | LIVE — real consumer; called every 10 s in `_loggingLoop` |
| `tests/pi/hardware/test_telemetry_logger_rotation.py:132,168` | TEST — covers wiring + rotation invariants |

Activation chain (production):

```
core.runLoop (core.py:726)
  -> _startHardwareManager (lifecycle.py:823)
  -> HardwareManager.start (hardware_manager.py:234)
     -> _initializeTelemetryLogger / _wireComponents / _startComponents
```

Pi-only gate: `isRaspberryPi() AND pi.hardware.enabled (default True)` (lifecycle.py:629–649). On non-Pi (Windows / CI) the `_initializeHardwareManager` short-circuits at line 634 and `_telemetryLogger` is never constructed — exactly as designed.

### Conclusion

**LIVE.** TelemetryLogger is the canonical 10-second-resolution **out-of-database** trail of `power_source` / `battery_v` / `battery_pct` / `battery_charge_rate_pct_per_hr` on the Pi. It is the file you reach for when `power_log` (US-243, in-DB) and `battery_health_log` (US-217 + US-216 drain-event row) are unavailable due to a SQLite lock, sync outage, or database FK cascade.

### Path forward (executed in this audit)

1. `specs/architecture.md` §13 — added "TelemetryLogger Data Trail" subsection documenting activation chain + rotation policy + JSON shape + drain-forensic value. Modification History entry added.
2. TD-033 marked **Resolved 2026-05-01**.
3. No code changed. No deletions. No new TD filed.

### Why the 2026-04-20 drain "didn't have a data trail"

Spool's TD-E flagged "we haven't checked" — that's a **runtime / ops** question (was `/var/log/carpi/telemetry.log` populated during the drain on Pi `chi-eclipse-01`?), separate from this **code-audit** question (does the wiring fire end-to-end?). The latter is now answered: yes. The former is an ops follow-up — `ssh chi-eclipse-01 'ls -la /var/log/carpi/'` will reveal whether the file exists and whether the `telemetry.log.1` rotation timestamp brackets the 2026-04-20 23:49 drain. That investigation is out of scope for US-251 (audit-only, no Pi access from this Windows session) and can be performed by Marcus or Spool when reviewing this resolution.
