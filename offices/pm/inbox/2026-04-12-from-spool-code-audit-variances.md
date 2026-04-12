# Code Audit — Variance Report (Sprint 1/2 Tuning Values)
**Date**: 2026-04-12
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Important
**Subject**: Tuning-domain audit of delivered code. Multiple variances found in legacy profile threshold system.

---

## Audit Scope

At CIO's request, I audited all delivered code in `src/` for tuning-domain values and compared them against my corrected spec. Scope was limited to my lane:
- Numerical threshold values
- Tuning logic correctness
- Vehicle-specific values (97-99 2G, stock turbo, stock internals)
- Units, ranges, and boundary behavior

**Not in scope**: Code structure, style, architecture, dual-system design decisions. I'll note structural observations but I'm not recommending architecture changes — that's your domain and the architect's.

---

## Key Finding

The codebase has **two parallel threshold systems** running at the same time:

1. **Tiered threshold system** (`obd_config.json` → `tieredThresholds` section, loaded by `src/alert/tiered_thresholds.py`): Uses Normal/Caution/Danger levels with explicit min/max boundaries. **Mostly correct** after our recent RPM hotfix.

2. **Profile-level simple threshold system** (`obd_config.json` → `profiles.availableProfiles[*].alertThresholds`, loaded by `src/alert/thresholds.py`): Uses single "critical" values per parameter. **Multiple wrong values, did NOT receive the RPM hotfix, and the parameter names are misleading.**

I'm flagging both as variances where the values are wrong regardless of which system is authoritative. Whether to consolidate/deprecate one of these systems is an architecture call for you and the architect.

---

## CRITICAL Variances (Actively Wrong Runtime Values)

### Variance 1: `coolantTempCritical: 110` — WRONG in 6 files

**Locations:**
- `src/alert/thresholds.py:139`
- `src/alert/manager.py:72`
- `src/profile/types.py:45`
- `src/obd_config.json:108` (daily profile)
- `src/obd_config.json:119` (performance profile, value = 115)
- `src/obd/obd_config_loader.py:350`
- `src/obd/config/loader.py:350`

**The problem:** The value `110` has no unit attached in most of these files. If it's meant to be Fahrenheit, `110°F` is **cold engine temperature** (engines run 180-210°F normally). An alert for "critical" coolant temperature at 110°F would fire every time the engine is warming up. If it's meant to be Celsius, `110°C = 230°F` — this IS above my danger threshold of 220°F, but the code doesn't specify units so a developer reading `110` in a field called `coolantTempCritical` has no way to know what it means.

**Compare to tiered system**: The `tieredThresholds.coolantTemp` section in `obd_config.json` has `unit: "fahrenheit"` explicitly stated with `normalMin: 180`, `cautionMin: 210`, `dangerMin: 220`. **These are correct.** The legacy profile system is out of sync.

**Correct value (per my spec):** `220` (Fahrenheit, with unit explicit).

**Root cause (my assessment):** The legacy profile threshold system was built before the tiered threshold system existed. When the tiered system was added, the legacy values weren't updated to match. Or the `110` is stale placeholder data from very early development.

**Fix options** (your call, Marcus):
- **Option A (simple)**: Update all 6 `coolantTempCritical: 110` values to `220` with explicit unit comment
- **Option B (better)**: Deprecate the legacy profile threshold system entirely. The tiered system is richer and more accurate. Profile "alertThresholds" becomes unnecessary.
- **Option C (minimal)**: Document the inconsistency as tech debt (TD-###) and handle in a future sprint

I'd recommend B, but it's a scope call you should make.

---

### Variance 2: Performance Profile `rpmRedline: 7200` — HOTFIX MISSED THIS

**Location:** `src/obd_config.json:118`

**The problem:** US-139 (the RPM hotfix) updated `tieredThresholds.rpm.dangerMin` from 7200 → 7000. **It did not update the legacy profile system.** The performance profile still has `rpmRedline: 7200`.

**Correct value:** `7000` (97-99 2G factory redline).

**Fix:** Update `src/obd_config.json:118` from `"rpmRedline": 7200` to `"rpmRedline": 7000`. Also update any tests that validate performance profile values.

**Why this happened:** US-139's scope was `src/obd_config.json` → `tieredThresholds.rpm.dangerMin` and the associated test file. The profile section wasn't in scope because we didn't know the legacy system existed. This is the dual-system problem biting us.

---

### Variance 3: Performance Profile `boostPressureMax: 18` — TOO AGGRESSIVE FOR STOCK TURBO

**Location:** `src/obd_config.json:121` and `src/alert/thresholds.py:140`

**The problem:** The CIO's Eclipse has a stock TD04-13G turbo. My spec caps stock turbo at 14-15 psi with danger starting at >15 psi. The code has `boostPressureMax: 18` psi as the alert ceiling, which is:
- 3 psi above the stock turbo's safe operating ceiling
- Into compressor surge territory
- Above turbo efficiency range (EGTs climb rapidly)

If boost ever hit 18 psi on the stock turbo, the system should have been screaming long before — but this threshold says "alert at 18." That's too late.

**Correct value (stock turbo):** `15` psi as the "danger" ceiling. Anything above 15 psi on the stock TD04-13G is unsafe.

**Future consideration:** When the CIO upgrades to a 16G or 20G, this threshold will change. But that's a future story — for the current stock-turbo state, 15 is correct.

**Fix:** Update `src/obd_config.json:121` to `"boostPressureMax": 15`. Update `src/alert/thresholds.py:140` default to match.

---

### Variance 4: Display Boost Stub Defaults — WRONG BY A LOT

**Location:** `src/display/screens/boost_detail.py:36-37`

```python
BOOST_CAUTION_DEFAULT = 18.0   # psi
BOOST_DANGER_DEFAULT = 22.0    # psi
```

**The problem:** These are stub defaults for the Phase 2 (ECMLink) boost detail screen. Even as stubs, they're dangerously wrong:
- `18 psi caution` is above where I'd flag danger on stock turbo
- `22 psi danger` is in "you're about to blow the head gasket" territory even on a built motor

A developer implementing Phase 2 would see these stubs and assume they're reasonable ballpark values. They're not.

**Correct values (stock turbo):**
```python
BOOST_CAUTION_DEFAULT = 14.0   # psi — approaching stock turbo efficiency limit
BOOST_DANGER_DEFAULT = 15.0    # psi — above stock turbo safe range
```

**Fix:** Update both constants. Add a comment noting these are stock turbo values and will change with turbo upgrades.

---

### Variance 5: Display Fuel Stub — Injector Caution Wrong

**Location:** `src/display/screens/fuel_detail.py:38`

```python
INJECTOR_CAUTION_DEFAULT = 80.0  # %
```

**The problem:** My spec says injector duty cycle caution starts at **75%**. The code has 80%.

My IDC thresholds:
- Normal: 0-75%
- Caution: 75-85%
- Danger: >85%
- Static flow limit: >95%

The danger default (`INJECTOR_DANGER_DEFAULT = 85.0`) on line 39 is correct. Only the caution is wrong.

**Fix:** Update `src/display/screens/fuel_detail.py:38` to `INJECTOR_CAUTION_DEFAULT = 75.0`.

---

## MINOR Variances (Ambiguous But Not Broken)

### Variance 6: Battery Voltage Boundary at 15.0V

**Location:** `src/obd_config.json:205, 207`

```json
"cautionHighMax": 15.0,
"dangerHighMin": 15.0,
```

**The problem:** At exactly 15.0V, both boundaries apply. Behavior at exactly 15.0 is ambiguous.

**Root cause:** My original spec had a gap (caution ended at 14.8V, danger started at >15.0V, leaving 14.8-15.0 undefined). Ralph correctly closed the gap by extending caution to 15.0. But now the boundary is ambiguous.

**Fix options:**
- `cautionHighMax: 14.99, dangerHighMin: 15.00` (inclusive/exclusive consistency)
- OR: Document which boundary wins in code comments
- OR: Use `<` vs `<=` consistently and document the convention

Not blocking any sprint. Nice to fix when Ralph touches this file next.

---

### Variance 7: `profile_manager.py` Docstring Example — Stale Reference

**Location:** `src/obd/profile_manager.py:47`

```python
alertThresholds={'rpmRedline': 7500},
```

**The problem:** This is inside a module docstring example, not runtime code. But `7500` is the **95-96 2G DSM redline** — completely wrong for the CIO's 1998 Eclipse GST (97-99 2G, redline 7000). A developer reading this docstring as an example would get the wrong vehicle spec.

**Fix:** Change the docstring example to `alertThresholds={'rpmRedline': 7000}`. Or better, use a generic value like `7200` with a comment that redline is vehicle-specific — this is example code, not real config.

**Impact:** Zero runtime impact. Documentation hygiene only. But it's the exact class of error (wrong vehicle year) that we just fixed, so worth cleaning up.

---

## NON-Variances (Code Is Correct)

For the record, these are all correct and need no changes:

- `tieredThresholds.coolantTemp`: 180/210/220 ✓
- `tieredThresholds.stft`: 5/15 ✓ (closes my original spec gap correctly)
- `tieredThresholds.rpm`: 600/6500/7000 ✓ (after US-139 hotfix)
- `tieredThresholds.batteryVoltage`: 13.5-14.5 normal, 12.5 caution low, 12.0 danger low ✓
- `tieredThresholds.iat`: 130/160 ✓ (after my correction)
- `tieredThresholds.timingAdvance`: 5° drop, 0° under load ✓
- All 4 polling tiers with correct PIDs at correct frequencies ✓
- PID 0x0B MDP caveat correctly documented in config ✓
- `src/obd/simulator/profiles/eclipse_gst.json`: `redlineRpm: 7000` ✓ (maxRpm: 7500 is simulator ceiling, intentional)
- Display thermal trend thresholds: 60-sec window, ±0.5°F/min slope, 200°F time-at-temp ✓
- `src/analysis/calculations.py`: standard deviation and outlier formulas correct
- `src/ai/data_preparation.py`: O2 rich/lean thresholds (0.5V/0.4V) correct for narrowband
- Drive detection: 500 RPM start threshold, 60-second idle end threshold ✓
- Timing advance baseline learning: 500 RPM bins, 10% load bins ✓

---

## Post-Mortem Note

This audit confirms what I flagged in my previous review note: **sprint 1 and sprint 2 work was built against specs I wrote without the review gate.** The variances above are exactly the class of error I predicted:

- Wrong values from early drafts that never got corrected
- Dual systems where one got updated and the other didn't
- Stale values that don't match vehicle specifics
- Display stubs with ballpark-wrong numbers

**This is not Ralph's fault.** He built exactly what the specs said (or in some cases, inherited stub defaults that needed values). The review gate didn't exist when sprint 1/2 ran. Now that it does, these variances get caught and fixed.

**Going forward:** Every sprint from sprint 3 onward should go through my review gate before Ralph writes code. And we should schedule a one-time audit of sprint 1/2 outputs (which this report is the start of) so we don't keep finding drift.

---

## Recommended Actions

### Hotfix stories (new backlog items needed):

**US-140: Fix Legacy Profile Coolant Critical Threshold**
- Update `coolantTempCritical` from `110` to `220` (Fahrenheit) in all 6 locations
- Add explicit unit specification (`fahrenheit`) to the profile threshold schema
- Update any tests asserting the old values
- Consider: should legacy profile thresholds be deprecated in favor of tiered system? (Architecture call)

**US-141: Complete RPM Hotfix in Legacy Profile System**
- Update `src/obd_config.json:118` performance profile `rpmRedline` from `7200` to `7000`
- Update tests
- This completes what US-139 started

**US-142: Correct Stock Turbo Boost Pressure Limits**
- Update `src/obd_config.json:121` `boostPressureMax` from `18` to `15`
- Update `src/alert/thresholds.py:140` default from `18` to `15`
- Add code comment noting this is stock turbo value; will change with upgrade
- Update tests

**US-143: Fix Phase 2 Display Stub Defaults**
- `src/display/screens/boost_detail.py`: `BOOST_CAUTION_DEFAULT` 18.0→14.0, `BOOST_DANGER_DEFAULT` 22.0→15.0
- `src/display/screens/fuel_detail.py`: `INJECTOR_CAUTION_DEFAULT` 80.0→75.0
- Add comments noting values are stock-turbo-specific and will be finalized in B-029 (Phase 2)

**US-144: Clean Up Profile Manager Docstring Example**
- `src/obd/profile_manager.py:47`: Change `rpmRedline: 7500` example to `7000` or use a generic placeholder
- Documentation only, no runtime impact

### Sprint Planning Note
All 5 stories above are small (XS or S). They could bundle into a single "Legacy Threshold Cleanup" sprint or be distributed. Your call on organization.

---

## Standing Offer

As with the previous review, if Ralph runs into unexpected behavior while implementing any of these fixes, send him my way. The legacy/tiered dual system might have some subtle interactions I can help untangle from a tuning perspective.

Also — once these fixes are in, I'd like to be notified when the first real datalog comes off the car this summer. I want to verify the alert system fires correctly against real readings, not simulator data.

Thanks, Marcus.

— Spool

*"The review gate works best when it catches errors before they ship. This audit is what happens when it couldn't — still finding them, just later."*
