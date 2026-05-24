# Finding: HardwareManager `_displayUpdateLoop` `KeyError: 'powerSource'`

**Date**: 2026-05-20
**Severity**: Low (journal noise) / Med (degraded display + masks real display-loop failures in the noise)
**Layer/Component**: Pi-side `src/pi/hardware/hardware_manager.py:491`
**Status**: Pre-existing, NOT Sprint-39-introduced

---

## Summary

The Pi's `HardwareManager._displayUpdateLoop` throws `KeyError: 'powerSource'`
on every poll iteration (~every 5 seconds = ~12 errors/min sustained). The
error originates from a direct dict subscript `telemetry['powerSource']` at
line 491 with no `.get()` fallback or guard. The exception is caught by the
loop's outer try/except (logged as ERROR, loop continues), so display is
silently degraded — power source indicator never updates — and the journal
fills with ERROR-level noise.

This is **pre-existing**, not Sprint 39 / V0.27.15 introduced — confirmed by
journal grep against pre-deploy window (2026-05-19 23:46Z onward before
V0.27.15 deployed at 2026-05-20 05:09:15Z).

## Evidence

### Journal occurrence counts

```bash
# Pre-V0.27.15 deploy window (V0.27.14 era, before 05:09Z deploy today):
ssh chi-eclipse-01 "journalctl -u eclipse-obd.service --since='2026-05-19' --until='2026-05-20 05:00' --no-pager | grep -c \"display update loop: 'powerSource'\""
# → 624

# Current boot (V0.27.15, started 14:12:59 CDT):
journalctl -u eclipse-obd.service -b --no-pager | grep -c "display update loop: 'powerSource'"
# → 2518 (and growing every 5s)

# Earlier boots today (V0.27.15, before current boot):
journalctl -u eclipse-obd.service --since='2026-05-20' --until='2026-05-20 09:48' --no-pager | grep -c "display update loop: 'powerSource'"
# → 1551
```

### Sample journal lines (current boot)

```
May 20 09:50:58 Chi-Eclips-01 python[1205]: 2026-05-20 09:50:58 | ERROR | pi.hardware.hardware_manager | _displayUpdateLoop | Error in display update loop: 'powerSource'
May 20 09:51:03 Chi-Eclips-01 python[1205]: 2026-05-20 09:51:03 | ERROR | pi.hardware.hardware_manager | _displayUpdateLoop | Error in display update loop: 'powerSource'
... (continues at 5s intervals)
```

### Code reference

`src/pi/hardware/hardware_manager.py:491`:

```python
# Update power source
powerSource = telemetry['powerSource']        # ← KeyError when 'powerSource' missing
if powerSource == PowerSource.EXTERNAL:
    self._statusDisplay.updatePowerSource('external')
elif powerSource == PowerSource.BATTERY:
    self._statusDisplay.updatePowerSource('battery')
else:
    ...
```

Same dict subscript pattern at line 586 (`getStatus()` reporter).

## Impact

- **Journal pollution**: ~17,000 ERROR rows per day per device. Masks real
  display-loop issues; makes journal harder to triage during incident
  response.
- **Degraded display**: `_statusDisplay.updatePowerSource(...)` never runs in
  the path where `'powerSource'` is missing; if `StatusDisplay` was supposed
  to show external-vs-battery, that's broken — though display itself is
  optional hardware so user impact may be zero on headless deployments.
- **NOT chain-merge-blocking**: not Sprint 39 introduced; orthogonal to the
  Shutdown Sequencer scope.

## Root Cause (likely)

Without code-deep-dive, the symptom-level diagnosis: the upstream `telemetry`
dict (likely from `UpsMonitor.getStatus()` or similar) does not always
include a `'powerSource'` key. Two non-exclusive hypotheses:

1. **Pre-existing race**: `_displayUpdateLoop` starts polling before
   `UpsMonitor` has produced its first reading; early ticks see an empty or
   partial dict; the error logs but no one ever fixes the consumer pattern.
2. **SSOT refactor side-effect (long-running)**: an earlier refactor moved
   `'powerSource'` populating out of `UpsMonitor` into `PowerSourceProvider`
   (Sprint 39 effectively retired `UpsMonitor.getPowerSource()` to
   `NotImplementedError`), but the consumer at `hardware_manager.py:491`
   still expects the old key — and since the error has been there since at
   least V0.27.14, the migration may have been partial across multiple
   sprints.

A 5-line code-read of `UpsMonitor.getStatus()` (or whatever populates
`telemetry`) would disambiguate quickly.

## Recommended Action

Cheap fix at the consumer:

```python
powerSource = telemetry.get('powerSource')
if powerSource is None:
    return  # display update skipped this tick
```

Or harden the producer (preferred per SSOT design directive
[[ssot-design-pattern]]): ensure `telemetry` always contains `'powerSource'`,
even if value is `PowerSource.UNKNOWN` during pre-first-reading state.

Either is a small surgical fix. NOT chain-merge-blocking; flag to PM for
Sprint 40 or later inclusion based on Marcus's capacity.

## Cross-references

- Tester knowledge: `offices/tester/knowledge/feedback-tester-validate-deploy-fixes-irl-not-just-code.md`
  (validation discipline applies — when this gets a "fix" story, the
  acceptance gate must include "grep eclipse-obd journal for `'powerSource'`
  ERROR over 5 min → require zero occurrences").
