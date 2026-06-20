# TD-031: BatteryMonitor voltage thresholds wrong for MAX17048 hardware (dead today, critical if enabled)

| Field        | Value                     |
|--------------|---------------------------|
| Priority     | Low (dead code today); BECOMES CRITICAL if someone enables the subsystem |
| Status       | **Closed 2026-04-23 via US-223 (Sprint 17)** |
| Category     | code / config             |
| Affected     | `src/pi/power/battery.py` (BatteryMonitor, 690 LOC) + `config.json pi.batteryMonitoring` section |
| Filed By     | Marcus (PM), from Spool audit 2026-04-21 |
| Surfaced In  | `offices/pm/inbox/2026-04-21-from-spool-power-audit.md` Section "Latent bugs found during audit" TD-B |
| Filed        | 2026-04-21                |
| Closed By    | Rex (Ralph Agent 1), US-223 |
| Closed       | 2026-04-23                |

## Closure (2026-04-23 / US-223)

Closed via the deletion path recommended by Spool's audit.  US-216
(Sprint 16 PowerDownOrchestrator) + US-217 (battery_health_log)
jointly cover the battery-protection domain on the actual MAX17048
hardware via SOC (not voltage) thresholds, so BatteryMonitor has no
remaining value.  What was removed:

- `src/pi/power/battery.py` (690 LOC, entire file)
- `BatteryMonitorError` from `src/pi/power/exceptions.py`
  (BatteryError + BatteryConfigurationError retained -- still raised by
  voltage readers in `src/pi/power/readers.py`)
- Battery-only types: `BatteryState`, `VoltageReading`, `BatteryStats`
  from `src/pi/power/types.py`
- Battery-only constants: `DEFAULT_WARNING_VOLTAGE`,
  `DEFAULT_CRITICAL_VOLTAGE`, `DEFAULT_BATTERY_POLLING_INTERVAL_SECONDS`,
  `BATTERY_LOG_EVENT_VOLTAGE/WARNING/CRITICAL/SHUTDOWN` from `types.py`
- 5 helper functions from `src/pi/power/helpers.py`:
  `createBatteryMonitorFromConfig`, `getBatteryMonitoringConfig`,
  `isBatteryMonitoringEnabled`, `getDefaultBatteryConfig`,
  `validateBatteryConfig`
- `pi.batteryMonitoring` config section from `config.json` + the
  matching four DEFAULTS keys in `src/pi/obdii/config/loader.py` + the
  `batteryMonitoring` field on the `PiConfig` dataclass in
  `src/common/config/schema.py`
- `SCHEMA_BATTERY_LOG` + `INDEX_BATTERY_LOG_TIMESTAMP` +
  `INDEX_BATTERY_LOG_EVENT_TYPE` from `src/pi/obdii/database_schema.py`
  (+ their entries in `ALL_SCHEMAS` / `ALL_INDEXES`)
- The `battery_log` table itself: Pi side stops being created on every
  `initialize()`; server side gets a new idempotent migration
  `src/server/migrations/versions/v0003_us223_drop_battery_log.py` that
  probes `INFORMATION_SCHEMA.TABLES` first and only emits
  `DROP TABLE IF EXISTS battery_log` on hosts where the table was
  created out-of-band (the canonical server never had it because
  sync_log's `IN_SCOPE_TABLES` whitelist excluded it).
- BatteryMonitor-specific test block + one parametrize tuple
  (`('battery_log', 'timestamp')`) + one
  `_CAPTURE_WRITE_FUNCTIONS` entry from
  `tests/pi/data/test_timestamp_format.py`
- battery_log assertions from `tests/pi/data/test_sync_log.py` +
  `tests/pi/data/test_sync_log_pk_variants.py`
- battery_log from expected-tables lists in
  `tests/test_sqlite_connection.py` +
  `tests/scripts/test_seed_pi_fixture.py`
- `specs/architecture.md` references: Section 3 `power/` classes list,
  Section 6.2 database table list + Excluded Pi-only sentence, ERD box,
  Indexes(16) → Indexes(14), Data Source Tagging scope list

Left intentionally untouched (scope-fence per US-223 `doNotTouch`):

- `src/pi/power/orchestrator.py` line 11 comment referencing
  BatteryMonitor as "dead code" -- US-225 owns the orchestrator; the
  stale symbol name is a comment-only staleness, not a functional
  reference.
- `src/pi/power/power.py` (PowerMonitor): still has a
  `setBatteryMonitor(batteryMonitor: Any)` method + `batteryMonitor`
  constructor parameter + `hasBatteryMonitor` flag.  PowerMonitor was
  flagged by Spool's audit as also-dead (filed as a future TD, not
  this one); deleting PowerMonitor is out of scope for US-223.  The
  parameter is typed `Any` so the deleted class name only appears in
  docstrings; no import break.


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
