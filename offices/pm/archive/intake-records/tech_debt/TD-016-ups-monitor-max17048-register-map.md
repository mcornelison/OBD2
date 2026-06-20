# TD-016: UpsMonitor register map does not match actual X1209 chip (MAX17048)

| Field        | Value                     |
|--------------|---------------------------|
| Priority     | High                      |
| Status       | **Resolved** (2026-04-18 Session 21 via US-180 Session 44) |
| Category     | code                      |
| Affected     | src/pi/hardware/ups_monitor.py, src/pi/hardware/i2c_client.py, src/pi/hardware/telemetry_logger.py, specs/architecture.md:747 |
| Introduced   | 2026-01-25 (ups_monitor.py initial implementation for US-RPI-006) — register map was defined before the real X1209 hardware was ever on a bench. Chip semantics were not verified against a datasheet or a live device until Session 41. |
| Created      | 2026-04-17                |
| Resolved     | 2026-04-18 — US-180 Session 44 applied the full MAX17048 register-map rewrite per BL-005 Option A variant. VCELL/SOC/CRATE all decoded correctly on live hardware. `getBatteryCurrent()` replaced by `getChargeRatePercentPerHour()`. `getPowerSource()` derived from `vcgencmd pmic_read_adc EXT5V_V` with 4.5V threshold. specs/architecture.md lines 95 + 747 updated. See BL-005.md for delivery details. |

## Description

`src/pi/hardware/ups_monitor.py:90-94` defines:

```python
REGISTER_VOLTAGE = 0x02          # Battery voltage in mV (16-bit word)
REGISTER_CURRENT = 0x04          # Battery current in mA (16-bit signed)
REGISTER_PERCENTAGE = 0x06       # Battery percentage (8-bit)
REGISTER_POWER_SOURCE = 0x08     # Power source (8-bit: 0=external, 1=battery)
```

This register map is fiction. The actual chip on the X1209 HAT is a **MAX17048-family fuel gauge** (identified Session 41 via register-fingerprint probe: VERSION=0x0002 big-endian, CONFIG=0x0097/0x9700 matches datasheet default 0x971C family pattern, CRATE register present at 0x16).

Actual MAX17048 register map:

| Reg  | Name    | Type    | Meaning |
|------|---------|---------|---------|
| 0x02 | VCELL   | RO word | 78.125 µV/LSB, big-endian |
| 0x04 | SOC     | RO word | high byte = integer %, low byte = 1/256 % |
| 0x06 | MODE    | WO word | sleep/quickstart/etc. (reads 0) |
| 0x08 | VERSION | RO word | chip version |
| 0x0C | CONFIG  | RW word | alert/compensation config |
| 0x14 | VALRT   | RW word | voltage alert thresholds |
| 0x16 | CRATE   | RO word | signed, 0.208 %/hr/LSB (may be N/A on some variants) |
| 0xFE | CMD     | WO word | POR command register |

Additional semantic errors in the existing code:

1. **`I2cClient.readWord` returns SMBus little-endian** — the MAX17048 is big-endian, so every word read needs a byte-swap. Fix options: add `readWordBigEndian` to `I2cClient` (cleanest), or byte-swap inline in `UpsMonitor`.
2. **`getBatteryCurrent()` is infeasible on this chip.** MAX17048 has no current register. The closest substitute is CRATE (charge rate %/hr). Callers (TelemetryLogger, HardwareManager) must be refactored to stop expecting a `current_mA` field.
3. **`getPowerSource()` is infeasible on this chip.** MAX17048 has no AC-vs-battery sense pin. Options: (a) derive from EXT5V rail on Pi 5 via `vcgencmd pmic_read_adc EXT5V_V`, (b) voltage-trend heuristic over a sample window, (c) drop the API entirely and let HardwareManager own the AC/battery notion from a PMIC poll.
4. **Readings currently returned by the broken code** (captured Session 41 on live X1209 with a 4.19V LiPo attached): V=20.691V, I=+22357 mA, SOC=0%, source=external. All four values are wrong or uninformative.

## Why It Was Accepted

The register map was defined in January 2026 during a pre-hardware sprint (US-RPI-006). The intent was to land the I2C scaffolding and a mockable `UpsMonitor` surface so the orchestrator could be wired up before the HAT arrived. The 32 unit tests that cover `UpsMonitor` mock the `I2cClient` and never exercised real-chip semantics — so the register-map fiction went undetected for three months. Rex Session 36 flagged the specs/code inconsistency (specs/architecture.md:747 said "INA219 at 0x36" while code used vague "MAX17048-family semantics") but did not resolve it because the bench chip had zero I2C presence until Session 20/41.

## Risk If Not Addressed

- `UpsMonitor` is permanently returning nonsense values on the real Pi → `TelemetryLogger` writes garbage rows → downstream analytics/alerts/shutdown logic will all see bogus inputs if they ever consume UPS telemetry in production.
- The DEBUG-level "skip" log pattern (TD-015) means operators will not see the failure at INFO level — it stays silent in journald.
- A future US-181-style shutdown-on-battery-loss design will fail because `onPowerSourceChange` callback fires zero times (the VERSION register never changes value).
- Likelihood: 100% when HAT is attached. Impact: high for any flow that consumes UPS fields; currently zero for US-181 because that story was rescoped to SIGTERM + pushbutton and does not depend on UpsMonitor.

## Remediation Plan

Tracked in **BL-005**. Remediation options A/B/C outlined there. Recommended option: Option A, a new story (e.g. US-184) that rewrites `UpsMonitor` for the actual chip, updates `TelemetryLogger`, adds big-endian word reads to `I2cClient`, and updates `specs/architecture.md:747` to name the real chip. Estimated size M.

Meanwhile the 32 existing software tests stay green (they mock `I2cClient`) and represent the correct error-handling behavior — they should be preserved through the rewrite with updated fixtures.
