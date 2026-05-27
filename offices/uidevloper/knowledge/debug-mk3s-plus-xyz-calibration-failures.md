---
name: debug-mk3s-plus-xyz-calibration-failures
description: Diagnostic ladder for MK3S+ "calibration failed - check the axes" error during XYZ Calibration wizard. Captures the failure-mode order most likely on a brand-new first-time setup, what each cause looks like, and the manual section references. Companion to reference-mk3s-plus-first-print-guide.md.
metadata:
  type: reference
---

# Debug — MK3S+ XYZ calibration "check the axes" error

**Manual source:** §6.3.5 Calibrate XYZ + §6.3.5.1 error resolution
(specs/vendor/prusa3d_manual_mk3s_en.pdf, p.19–21).
**Captured:** 2026-05-25 (Iris), live debug with CIO.

## The error

LCD message variants (firmware-dependent):
- "XYZ calibration failed. Bed calibration point was not found."
- "XYZ calibration failed. Please consult the manual."
- "Calibration failed! Check the axes and run again." (newer firmware
  shortened wording — same root cause family)

All three map to manual case 1) or 2) — calibration points missing or
found in geometrically-impossible positions.

## Diagnostic ladder (try in order)

### Cause 1 — Plastic debris on nozzle tip (MOST COMMON on new printer)

Factory test leaves residue. First preheat oozes it. Tiny bead pushes
bed away from SuperPINDA probe.

**Test:** Look at brass nozzle tip from below. Clean cone with clear
hole = good. Black/clear blob = culprit.

**Fix:** Heat nozzle to 240°C, wipe outside with paper towel or
pliers-gripped cloth (HOT — don't touch), cool to 0°C, re-run cal.

### Cause 2 — SuperPINDA probe not aligned over bed sensor points

Bed has 4 small circular indentations near corners (~5mm dia, recessed).
Probe must sit directly above each one to trigger. Probe can be
offset from shipping bump, loose belt, shifted holder.

**Test:** Power OFF printer. Manually move print head to each of 4
bed corners. Verify SuperPINDA probe (black cylinder right of nozzle)
sits directly above the bed sensor mark at each corner.

**Fix:**
- If consistent offset (all 4 in same direction): X or Y belt tension /
  pulley grub-screw — check belts on respective axis
- If probe-holder loose: M3 screw on probe holder, re-align,
  re-tighten
- If skewed: Calibrate XYZ §6.3.5 wizard will report skew if it
  completes; if persistent fail, frame may need re-squaring

### Cause 3 — SuperPINDA probe height wrong relative to nozzle

Probe must always be *higher* than nozzle tip (§6.3.10.2). Too low =
probe catches on prints / bed. Too high = no trigger / weak trigger.

**Test:** Power off. Manually move print head down until nozzle ~0.5mm
above bare bed. Probe should be ~0.5–1mm above bed too (not touching).

**Fix:** Loosen M3 screw on probe holder, slide probe up or down,
re-tighten. Then re-run Calibrate Z + Calibrate XYZ.

### Cause 4 — Axes don't move freely

Belt too tight = drag; belt too loose = pulley slip mid-move. Either
causes "found in wrong positions" reports.

**Test:** Power OFF. Push bed forward/back by hand — should glide
with light, even resistance, no binding. Push print head left/right —
same.

**Fix:** Adjust belt tensioner screws per assembly manual. Belts
should feel like medium-tension guitar strings — twang, not slack.

### Cause 5 — Printer on unstable surface

Vibration / give in table = probe readings inconsistent run-to-run.

**Test:** Press down on each corner of the printer frame. Does it
rock? Does the table compress?

**Fix:** Move to rigid table (wood, metal, granite). Carpet/foam/
cardboard = unreliable.

### Cause 6 — Steel sheet was on during round 1 (rare user error)

Manual §6.3.5: first round is WITHOUT steel sheet (probe reads bare
aluminum bed); third round is WITH steel sheet. If sheet was left on
during round 1, geometry math fails.

**Test:** Wizard tells you when to remove/replace sheet. Re-run with
sheet OFF until prompted.

### Cause 7 — SuperPINDA temperature drift

Cold start vs warm start changes SuperPINDA's effective trigger
distance slightly. Manual mentions "printer checks the temperature of
the SuperPINDA probe" — but no user-actionable fix; if reproducible
cold-vs-warm, contact Prusa support.

**Test:** Try the wizard immediately after a cold power-on (probe
cold). If it then works after a few minutes of warmup, this is the
cause.

## Mesh bed leveling errors (related but different — §6.3.5.1 cont.)

These happen AFTER XYZ cal succeeds, during mesh bed leveling:

- "Bed leveling failed. Sensor disconnected or cable broken." → check
  SuperPINDA cable into EINSY RAMBo board, or replace probe
- "Bed leveling failed. Sensor didn't trigger. Debris on nozzle?" →
  cause 1 above; also check if printer moved (re-run Z cal)
- "Bed leveling failed. Sensor triggered too high." → cause 3 above
  (probe too high) OR printer moved to uneven surface

## Sensor info — useful diagnostic

LCD Menu → **Support → Sensor info** shows live SuperPINDA state.
With nothing under the probe = "0" (not triggered). With finger or
metal under probe = "1" (triggered). If reading is stuck at 1 with
nothing under probe = probe failure; if stuck at 0 with finger
directly under = probe failure or cable.

## Notes for future-me

- This debug session was CIO's first-ever 3D print attempt — error
  rate on first-cal is high; expect to walk through 2–3 of these
  causes per new operator
- The "check the axes" phrasing is misleading to newcomers; almost
  always actually a nozzle or probe-alignment issue, not literal axis
  failure
- Always start with Cause 1 (nozzle clean) before any mechanical
  investigation — fastest test, highest hit rate
- If user reports clean nozzle + good Z homing rattle, jump to Cause
  2 (probe alignment) next — skip ahead in the ladder
