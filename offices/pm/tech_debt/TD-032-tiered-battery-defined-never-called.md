# TD-032: `tiered_battery.py` defined but never called (dead in alert module)

| Field        | Value                     |
|--------------|---------------------------|
| Priority     | Low                       |
| Status       | Open                      |
| Category     | code cleanup              |
| Affected     | `src/pi/alert/tiered_battery.py` (225 LOC) |
| Filed By     | Marcus (PM), from Spool audit 2026-04-21 |
| Surfaced In  | `offices/pm/inbox/2026-04-21-from-spool-power-audit.md` Section "Latent bugs found during audit" TD-C (continuation of Session 3 finding) |
| Filed        | 2026-04-21                |

## Description

`src/pi/alert/tiered_battery.py` defines `evaluateBatteryVoltage()` and `loadBatteryVoltageThresholds()`. Grep confirms zero production callers — the functions are exported but not wired into `AlertManager` or any alert dispatch path.

Voltage tiers (12.0 / 12.5 / 14.5 / 15.0V) are correct for a 12V car battery but not for the MAX17048 1S LiPo UPS (which operates 3.0–4.3V). Even if wired, the thresholds don't match the hardware.

## Options

1. **Delete** — tiered_battery.py + its tests + any config references. US-216's SOC ladder + US-217's battery_health_log cover the battery-protection domain.
2. **Wire** — connect to AlertManager's evaluate path, but requires threshold rewrite for MAX17048 (same problem as TD-031).

**Recommend Option 1 (delete)** once US-216 ships and US-217's battery_health_log is producing rows. AlertManager doesn't need a voltage-tier path separate from the SOC ladder.

## Priority rationale

Low. Dead code doesn't hurt anything; cleanup is hygiene not safety.

## Related

- TD-031 (BatteryMonitor dead + wrong thresholds) has the same deletion recommendation once US-216 ships.
- TD-030 (config key path mismatch) same audit batch.
