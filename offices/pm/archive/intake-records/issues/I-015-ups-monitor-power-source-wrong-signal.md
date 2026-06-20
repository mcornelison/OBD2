# I-015: UpsMonitor.getPowerSource() uses wrong signal — EXT5V is regulated by the HAT, doesn't change on unplug

| Field        | Value                     |
|--------------|---------------------------|
| Severity     | Medium                    |
| Status       | Resolved (2026-04-18, US-184 / Sprint 11, Ralph Session 46) |
| Affected     | src/pi/hardware/ups_monitor.py (readExt5vVoltageFromVcgencmd + getPowerSource) |
| Discovered   | 2026-04-18 Session 21 — CIO physical unplug drill for US-180 AC #6 |
| Fix owner    | US-184 (Sprint 11)        |

## Symptom

CIO ran the AC #6 unplug drill post-merge: baseline `ext5v ~5.2V, source=external`, then physically unplugged USB-C from wall. Pi kept running (UPS works correctly) but the `watch` display **did not change** — `ext5v` stayed ~5.2V and `source` stayed `external`. Expected: `ext5v` drops <4.5V and `source` flips to `battery`.

## Root cause hypothesis

The Geekworm X1209 UPS HAT regulates 5V to the Pi in both wall-power AND UPS-boost-from-LiPo modes. That's literally what a UPS does — it hides the source transition from the downstream device. Evidence from Session 20 MEMORY.md: *"EXT5V=5.22V regulated to Pi"* captured under UPS backup mode (not just wall-power mode).

Session 44's `readExt5vVoltageFromVcgencmd()` reads the Pi 5 PMIC's EXT5V_V ADC rail — which measures the voltage the HAT delivers. That rail stays ~5V regardless of whether the HAT is passing through wall power or boosting from LiPo. It's a false signal.

Session 44 unit tests covered the function as designed (graceful degradation on vcgencmd failures, threshold logic) — but never exercised the physical unplug-drill scenario because that required Pi hardware + unplug coordination. The tests passed against the wrong premise.

## Correct distinguishing signals (per Session 20 live data)

The real source-transition signals on MAX17048 + X1209:

1. **CRATE polarity** — signed %/hr charge rate. Positive = charging (wall power, SOC rising). Negative = discharging (UPS backup, SOC falling). Session 20 saw `CRATE=-0.21%/hr` under UPS discharge. **Caveat**: on the live chip this session, `CRATE` returned 0xFFFF (disabled variant). Not available.

2. **VCELL trend over a window** — LiPo cell voltage drops under discharge, is stable/recovering on wall power. Session 20 saw `V=4.181V full charge → V=3.66V discharge`. Window-based trend detection (e.g., last N readings, slope < -0.02V/min ⇒ BATTERY) is robust.

3. **SOC trend** — same shape as VCELL but coarser (whole percent steps). Works when CRATE is disabled.

4. **Geekworm X1209 may expose a GPIO "PLD" (power-loss-detect) line** — worth checking the datasheet. If present, it's the cleanest signal; otherwise software-derived trend is the fallback.

## Impact

- `UpsMonitor.getPowerSource()` always returns EXTERNAL on this chip variant. The graceful-shutdown path that depends on power-source transitions (US-181's optional UPS-loss AC, US-169 UPS behavior validation) will never fire via this method.
- US-180 shipped with AC #6 marked DONE based on Ralph's software tests — but the physical drill now proves the signal is wrong. The AC phrasing referenced "derive power source from vcgencmd pmic_read_adc EXT5V_V" which Ralph implemented correctly against the spec — the spec itself was wrong about what signal distinguishes source.

## Resolution

Resolved 2026-04-18 by US-184 (Ralph Session 46). Code delivered:

- `UpsMonitor.getPowerSource()` rewritten around a VCELL-trend + CRATE
  heuristic over a rolling window (default 60 s). CRATE polarity wins
  when the chip variant populates it (`CRATE < -0.05 %/hr -> BATTERY`);
  otherwise a VCELL slope `< -0.02 V/min` declares BATTERY. EXTERNAL
  fires when neither signal is in the BATTERY regime.
- `readExt5vVoltageFromVcgencmd()` retained and now exposed via
  `getDiagnosticExt5vVoltage()` → telemetry field `ext5v_v`. EXT5V is
  **no longer on the source-detection path** (as demanded by this
  issue) — it's purely a diagnostic "is the HAT delivering power?"
  observability field.
- `PowerSource.UNKNOWN` preserved as the enum value returned when no
  signal is available; `getPowerSource()` prefers falling through to
  the cached last source rather than returning UNKNOWN when any prior
  decision has been made (prevents false-positive shutdown-cancel).
- Rolling history buffer prunes entries older than
  `historyWindowSeconds` (configurable) — pruning is time-based, so
  the buffer doesn't grow unbounded regardless of poll interval.
- Config surface: `pi.hardware.upsMonitor.{historyWindowSeconds,
  vcellSlopeThresholdVoltsPerMinute, crateThresholdPercentPerHour}`
  added with validator defaults.
- Telemetry field surface updated: `getTelemetry()` now returns
  `ext5vVoltage` alongside `voltage/percentage/chargeRatePctPerHr/
  powerSource`. TelemetryLogger JSON gained `ext5v_v`.
- `specs/architecture.md` power-source detection paragraph updated —
  explains why EXT5V was wrong (HAT regulates the rail in both modes)
  and names the new heuristic.
- Shutdown-handler / hardware-manager consumers already handle
  `PowerSource.UNKNOWN` safely as "don't trigger shutdown" — no
  changes required.
- Test coverage:
  - `tests/pi/hardware/test_ups_monitor_power_source.py` (new, 14
    tests) — full decision-tree coverage: CRATE branch, VCELL-slope
    branch, fall-through-to-cached, EXT5V-no-longer-influences-source
    regression guard, buffer pruning.
  - `tests/pi/hardware/test_ups_monitor_degradation.py` (reshaped) —
    EXT5V-based source tests converted to diagnostic-helper tests;
    change-callback test now drives VCELL-slope transitions through
    the real polling loop.

CIO physical unplug drill checklist delivered at
`offices/pm/drills/US-184-unplug-drill-checklist.md` — runnable end-to-end
on `chi-eclipse-01` in ~5 minutes; evidence goes to
`offices/pm/drills/US-184-unplug-drill-run.md` for PM review.

## Related

- BL-005 resolution (in-place US-180 scope expansion) — this issue is a follow-on finding from that decision path; does NOT retroactively invalidate BL-005 resolution since VCELL/SOC/CRATE reads are correct.
- Session 20 MEMORY.md — ground truth that EXT5V stays regulated under UPS backup.
- Session 44 Ralph completion notes — implementation built correctly against the spec as written; spec was wrong.
- US-184 completion notes (Ralph Session 46) — this commit.
