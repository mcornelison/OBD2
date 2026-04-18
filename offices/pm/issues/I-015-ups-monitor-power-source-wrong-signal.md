# I-015: UpsMonitor.getPowerSource() uses wrong signal — EXT5V is regulated by the HAT, doesn't change on unplug

| Field        | Value                     |
|--------------|---------------------------|
| Severity     | Medium                    |
| Status       | Open                      |
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

Tracked as **US-184** in Sprint 11. Scope:

- Replace `getPowerSource()` implementation with a VCELL-trend or SOC-trend heuristic over a rolling window (~60s). Keep `readExt5vVoltageFromVcgencmd()` as a diagnostic (still useful signal for "HAT is delivering power" sanity) but remove it from source-detection.
- Investigate Geekworm X1209 docs for a GPIO PLD line; if present, prefer that.
- Re-run CIO unplug drill as the passing AC.
- Update specs/architecture.md power-source detection note.
- Keep existing US-180 ACs 1–5 passed (VCELL/SOC/CRATE/VERSION reads all still correct).

## Related

- BL-005 resolution (in-place US-180 scope expansion) — this issue is a follow-on finding from that decision path; does NOT retroactively invalidate BL-005 resolution since VCELL/SOC/CRATE reads are correct.
- Session 20 MEMORY.md — ground truth that EXT5V stays regulated under UPS backup.
- Session 44 Ralph completion notes — implementation built correctly against the spec as written; spec was wrong.
