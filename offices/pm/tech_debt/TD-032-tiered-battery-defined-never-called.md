# TD-032: `tiered_battery.py` defined but never called (dead in alert module)

| Field        | Value                     |
|--------------|---------------------------|
| Priority     | Low                       |
| Status       | Resolved 2026-05-01 (US-250) |
| Category     | code cleanup              |
| Affected     | `src/pi/alert/tiered_battery.py` (225 LOC) |
| Filed By     | Marcus (PM), from Spool audit 2026-04-21 |
| Surfaced In  | `offices/pm/inbox/2026-04-21-from-spool-power-audit.md` Section "Latent bugs found during audit" TD-C (continuation of Session 3 finding) |
| Filed        | 2026-04-21                |
| Closed       | 2026-05-01 by Rex (Ralph) Session 122 via US-250 — Option 1 (delete) |

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

## Resolution (2026-05-01, US-250, Rex / Session 122)

Option 1 (delete) executed. US-216 SOC ladder + US-217 `battery_health_log` cover the battery-protection domain; the dead voltage-tier path is no longer needed.

**Deletions:**
- `src/pi/alert/tiered_battery.py` (225 LOC, entire module) — removed via `git rm`
- `tests/test_battery_voltage_thresholds.py` (entire test file, ~620 LOC, 30+ tests) — removed via `git rm`
- `src/pi/alert/tiered_thresholds.py` — removed `BatteryVoltageThresholds`, `evaluateBatteryVoltage`, `loadBatteryVoltageThresholds` from imports + `__all__` + module docstring
- `src/pi/alert/tiered_core.py` — removed `tiered_battery` mention from docstring
- `config.json` — removed `pi.tieredThresholds.batteryVoltage` block (13 keys); also removed dangling pointer in BATTERY_V parameter `caveat` ("Thresholds live at pi.tieredThresholds.batteryVoltage" — pointed to deleted section)

**Audit findings (pre-deletion grep):**
- Symbol `evaluateBatteryVoltage`: 0 production callers (only the dead handler module + the now-deleted test file referenced it)
- Symbol `loadBatteryVoltageThresholds`: 0 production callers
- Symbol `BatteryVoltageThresholds`: 0 production callers
- Re-export site `tiered_thresholds.py` was a facade only — never consumed downstream by `__init__.py` or any importer

**Verification:**
- Post-deletion `rg "tiered.?battery|tieredBattery|evaluateBatteryVoltage|loadBatteryVoltageThresholds|BatteryVoltageThresholds" src/ tests/ config.json` returns only mod-history entries documenting the deletion.
- Targeted regression on remaining tiered + display tests (8 files, 279 tests) — all PASS.
- `python validate_config.py` — OK.

**Out of scope (filed for future):**
- `offices/pm/tech_debt/TD-alert-coverage-stft-battery-iat-timing.md` references `evaluateBatteryVoltage` at `src/alert/tiered_thresholds.py:443` (stale path) — this TD is now partially obsolete (the battery branch is dead-and-deleted). Marcus may wish to re-scope or close that TD's battery section.

**Mirror pattern:** Sprint 17 US-223 (TD-031, BatteryMonitor delete) — same execution shape (audit + git rm + sweep imports + close TD).
