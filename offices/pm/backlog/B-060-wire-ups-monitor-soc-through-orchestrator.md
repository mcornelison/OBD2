# B-060: Wire UpsMonitor SOC% through orchestrator to recorder (BL-013 Step 2)

| Field        | Value                  |
|--------------|------------------------|
| Priority     | Medium                 |
| Status       | Pending (V0.27.3+ reservation per CIO 2026-05-09) |
| Category     | database / observability |
| Size         | M                      |
| Related PRD  | None                   |
| Dependencies | Sprint 28 US-309 (Step 1 inert seam) must merge first |
| Created      | 2026-05-09             |

## Description

BL-013 Option A Step 2: now that Sprint 28 US-309 lands the recorder seam (`startSocPct` / `endSocPct` kwargs added but unused by production), wire `UpsMonitor.getBatteryPercentage()` through `PowerDownOrchestrator` to flip the 4 production call sites from passing VCELL to passing SOC%.

This story is the actual user-observable fix that makes `start_soc` / `end_soc` columns hold real SOC% values 0-100, not VCELL voltage. Step 1 alone is behaviorally inert.

## Acceptance Criteria

- [ ] `PowerDownOrchestrator` constructor gains `getSocFn: Callable[[], int | None] | None = None` (or equivalent injection seam)
- [ ] `_enterWarning` + `_acRestore` + `_deEscalateWarningToNormal` + `_enterTrigger` (4 call sites) read `getSocFn()` if available; pass result via `startSocPct` / `endSocPct` kwarg to recorder; fallback to VCELL when None
- [ ] `ApplicationOrchestrator` (lifecycle.py) wires `UpsMonitor.getBatteryPercentage` as `getSocFn`
- [ ] ~10 lock-down tests (Category B per BL-013) updated to assert SOC% range 0-100 instead of VCELL voltage range
- [ ] New IRL Drain Test (Drain 12+) confirms `start_soc` / `end_soc` populated with actual SOC% (not voltage)
- [ ] Cold-start MAX17048 calibration window: defensive check that drain events opened in first ~3 minutes of Pi boot get NULL `start_soc` (SOC% reading not yet calibrated) rather than nonsense values

## Validation Script Requirements

- **Input**: Drain Test 12 (or later) on Pi that has been booted >5 minutes (MAX17048 calibrated)
- **Expected Output**: `battery_health_log.start_soc` in 0-100 range matching MAX17048 reading; `start_vcell_v` continues to hold VCELL voltage
- **Database State**: `SELECT start_soc, start_vcell_v FROM battery_health_log ORDER BY drain_event_id DESC LIMIT 1` -- start_soc < 100, start_vcell_v in 3.4-4.2V range
- **Test Program**: integration test mocks `getSocFn` to return 75 + asserts row written with start_soc=75; pre-fix asserts current VCELL behavior preserved when getSocFn=None

## Notes

**Cold-start calibration hazard**: `UpsMonitor.getBatteryPercentage()` returns mis-calibrated values for the first ~3 minutes after Pi boot (per MAX17048 ModelGauge algorithm characteristics). Drain events opened in that window risk recording wrong SOC% values -- the same failure mode that motivated US-234's switch from SOC%-based to VCELL-based shutdown thresholds in Sprint 19. Two defensive options:

- (a) Check Pi uptime; if <3 minutes, write NULL to `start_soc` (or skip the SOC% kwarg, falling back to legacy VCELL).
- (b) Tag the drain event with a `soc_calibration_state` enum (calibrating / calibrated) so analytics can filter.

Option (a) is simpler. Spool may want option (b) for analytics richness -- gross out at grooming time.

**Source**: `offices/pm/blockers/BL-013.md` (full pre-flight audit + Step 2 spec)

**Sprint reservation**: V0.27.3+ candidate. Will be groomed alongside B-062 (drain_event close fix post-Drain-11) + I-018 (calibration.py types.py shadow + missing baselines table) + B-059 (drive_summary writer 12-field contract) for the next bug-fix sprint.
