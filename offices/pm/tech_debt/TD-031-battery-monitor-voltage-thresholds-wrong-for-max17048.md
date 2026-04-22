# TD-031: BatteryMonitor voltage thresholds wrong for MAX17048 hardware (dead today, critical if enabled)

| Field        | Value                     |
|--------------|---------------------------|
| Priority     | Low (dead code today); BECOMES CRITICAL if someone enables the subsystem |
| Status       | Open                      |
| Category     | code / config             |
| Affected     | `src/pi/power/battery.py` (BatteryMonitor, 690 LOC) + `config.json pi.batteryMonitoring` section |
| Filed By     | Marcus (PM), from Spool audit 2026-04-21 |
| Surfaced In  | `offices/pm/inbox/2026-04-21-from-spool-power-audit.md` Section "Latent bugs found during audit" TD-B |
| Filed        | 2026-04-21                |

## Description

`config.json pi.batteryMonitoring.warningVoltage=11.5` and `criticalVoltage=11.0` are thresholds for a 12V-class battery (lead-acid or 3S Li). The Pi UPS uses a MAX17048 chip polling a 1S LiPo battery (3.0–4.3V operational range). At 11.0V/11.5V these thresholds are physically impossible — the voltage never reaches those numbers.

If an operator flips `pi.batteryMonitoring.enabled=true` expecting protection, they get none — the thresholds cannot fire on the actual hardware.

## Recommended fix

**Delete BatteryMonitor + `src/pi/power/battery.py` + `battery_log` table** once US-216 ships and proves the SOC-based ladder (30/25/20%) covers the protection domain. The MAX17048-based ladder via US-216 fully supersedes the voltage-threshold approach BatteryMonitor would have provided.

If deletion is too aggressive, alternative: rewrite BatteryMonitor thresholds to 1S LiPo values (e.g., `warningVoltage=3.5, criticalVoltage=3.3`) but this still duplicates US-216's coverage.

## Priority rationale

- Low today: `pi.batteryMonitoring.enabled=false` by default per audit; no one hits this.
- Critical if enabled: dead-silent protection failure on the actual hardware.
- Best answer: delete once US-216 lands.

## Related

- Spool audit recommends "delete BatteryMonitor + battery.py + battery_log table once US-216 proves the SOC ladder covers this protection."
- US-216 (Sprint 16) implements the SOC ladder that supersedes this.
