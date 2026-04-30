# US-235 BATTERY-detection fix shipped (2026-04-29)

**From:** Rex (Ralph Agent 1, Session 107)
**To:** Spool (Tuning SME)
**CC:** Marcus (PM)
**Sprint:** 19 (2/8 complete after this story; pairs with US-234)
**Status:** passes:true, awaiting CIO drain test 5 to validate live

## What changed

`UpsMonitor.getPowerSource()` rebuilt per your sprint19-consolidated note Section P0 #1 second candidate. Three substantive changes:

1. **CRATE rule deleted entirely.** The polarity branch (`if CRATE < -0.05 %/hr -> BATTERY`) is gone. CRATE register is still readable via `getChargeRatePercentPerHour()` for the `chargeRatePctPerHr` telemetry field — just not on the decision path. Your audit confirmed CRATE returns `0xFFFF` (disabled) on this MAX17048 variant across all 4 drain tests; the rule never could fire.
2. **VCELL sustained-threshold rule added (your primary recommendation).** If VCELL stays continuously below `vcellBatteryThresholdVolts` (default **3.95V**) for `vcellBatteryThresholdSustainedSeconds` (default **30s**), `getPowerSource()` returns BATTERY. The threshold sits comfortably above the LiPo discharge knee (~3.7V) and below a healthy AC-fed float (~4.10V). 30s of continuous sub-threshold suppresses voltage-noise false positives.
3. **Slope rule tuned -0.02 -> -0.005 V/min.** Per Marcus's grooming + the drain-test data showing real drift was around -0.01 to -0.015 V/min — comfortably past the new threshold but invisible to the old one.

Either rule firing returns BATTERY. If neither fires AND there's decisive non-BATTERY evidence (most recent VCELL >= threshold OR slope computable >= threshold), return EXTERNAL. Otherwise return cached.

## Synthetic test discriminator

`tests/pi/hardware/test_ups_monitor_battery_detection.py::test_getPowerSource_oldSlopeThresholdMisses_newCatches` is the runtime-validation-required gate: VCELL falls 0.01V over 60s (slope = -0.01 V/min). Pre-US-235 default slope threshold was -0.02 V/min so this slope did NOT fire BATTERY there — the exact failure mode you saw across drains 1-4 in the wild. New threshold -0.005 V/min so this slope DOES fire. The test would fail against the pre-US-235 code, proving it catches the actual bug class.

`test_getPowerSource_crateBelowOldThreshold_doesNotFireBatteryAlone` is the symmetric proof for CRATE deletion: CRATE returning -1.04 %/hr (well below the legacy -0.05 threshold) with VCELL flat at 4.20V no longer fires BATTERY. Pre-US-235 code would have returned BATTERY purely from CRATE polarity.

Mocks operate at `I2cClient.readWord` level (real MAX17048 chip-read entry) so the real `getBatteryVoltage() -> recordHistorySample() -> getPowerSource()` pipeline is exercised, same fidelity pattern as US-234.

## What this means for drain test 5

Once CIO redeploys and runs drain test 5:
- **Expected**: `getPowerSource()` returns BATTERY shortly after wall-power removal (within 30-60s of VCELL crossing 3.95V on the discharge knee approach, depending on how fast VCELL actually drops on this hardware).
- **Then**: PowerDownOrchestrator (US-234) sees `currentSource == BATTERY` and starts evaluating VCELL thresholds, firing WARNING/IMMINENT/TRIGGER stages and finally `systemctl poweroff`.
- **Then**: `battery_health_log` row populates for the first time across 4 drains.

If those things happen, US-216 finally works end-to-end. If they don't, the reason will be observable (`battery_health_log` empty + journald shows whether `getPowerSource()` flipped). One more drain test should be ground truth.

## Schema/config notes

- `config.json` `pi.hardware.upsMonitor` now has `vcellBatteryThresholdVolts: 3.95`, `vcellBatteryThresholdSustainedSeconds: 30`, `vcellSlopeThresholdVoltsPerMinute: -0.005` (was -0.02). `crateThresholdPercentPerHour` removed.
- `src/common/config/validator.py` mirrors above.
- `specs/architecture.md` Section 2 power-source-detection paragraph rewritten with the new rule set + abandonment justification for CRATE.

## Stop conditions hit

None. Story shipped clean against all stop conditions:
- Synthetic test does FAIL against the pre-US-235 code (proves discriminator strength).
- Slope detection is rolling-window-based; no false-positive flap in the synthetic recovery test.
- Wall-power-flicker edge case (VCELL drops then recovers within 30s) is documented as a follow-up; the current story does NOT fire BATTERY on a sub-30s flicker, which is correct per your spec.

## Files actually touched

Production: `config.json`, `src/common/config/validator.py`, `src/pi/hardware/ups_monitor.py`, `specs/architecture.md`.

Tests: `tests/pi/hardware/test_ups_monitor_power_source.py` (existing, CRATE-rule tests removed), `tests/pi/hardware/test_ups_monitor_degradation.py` (existing, comment cleanup on the telemetry-keys test), `tests/pi/hardware/test_ups_monitor_battery_detection.py` (NEW), `tests/pi/hardware/test_ups_monitor_battery_detection_recovery.py` (NEW).

Verification: 12/12 new tests pass, 90/90 hardware tests pass, full fast suite 3366 passed / 0 failed, ruff clean, validate_config OK, sprint_lint 0 errors.

— Rex
