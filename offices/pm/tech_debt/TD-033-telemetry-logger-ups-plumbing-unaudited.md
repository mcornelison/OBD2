# TD-033: `telemetry_logger.py` ↔ UpsMonitor plumbing not audited (20-min verify)

| Field        | Value                     |
|--------------|---------------------------|
| Priority     | Low (verify; may be nothing, may be another dead-wire) |
| Status       | Open                      |
| Category     | code audit                |
| Affected     | `src/pi/hardware/telemetry_logger.py` + `hardware_manager.py:339` |
| Filed By     | Marcus (PM), from Spool audit 2026-04-21 |
| Surfaced In  | `offices/pm/inbox/2026-04-21-from-spool-power-audit.md` Section "Latent bugs" TD-E |
| Filed        | 2026-04-21                |

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
