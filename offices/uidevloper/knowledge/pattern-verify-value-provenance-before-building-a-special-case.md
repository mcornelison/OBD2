---
name: pattern-verify-value-provenance-before-building-a-special-case
description: Before baking a peer's magic number into a UI special-case, check WHICH hardware baseline it was observed on — an SME's own SSOT can carry an observation scoped to superseded hardware while labeled as applying to all of it.
---

# Check a value's provenance before you build a branch around it

When an SME hands over a characteristic value — "this engine locks LTFT ≈ −6.25 % at warm
idle, so offset the band or it false-alarms at every stoplight" — **ask which hardware
baseline that observation came from before designing a special-case around it.**

Spool issued exactly that rule on 2026-08-07 and **withdrew it the same day**. The figure
came from drives 3/5/6 on the **old ECU** (MD346675); the car has run **MD326328** since
2026-05-22. His own card carried the observation tagged `ecu: both` — it wasn't both. Once
re-baselined against the current ECU (drives 25–38, n≈2,700) LTFT ran **−3.9 % to +3.1 %**
with warm idle at **−2.6 %** — comfortably inside the ±5 % green band, *including the exact
case the warning was about*.

**Why this matters more for UI than for analysis.** A wrong number in a report is wrong
once and gets corrected. A wrong number that becomes a **special-case branch** becomes
*code*: a suppression rule, an offset, an `if (idling)` path. It outlives the value that
justified it, nobody remembers why it's there, and it silently masks the real signal it was
supposed to protect. **A branch is the most expensive possible place to put an unverified
number.**

## How to apply

1. **Any magic number that would create a branch** → ask the SME for its provenance:
   which ECU / drive range / date? On this project the **ECU identity changed mid-history**
   (MD346675 → MD326328, 2026-05-22), so any observation from drives ≤24 is suspect for
   current-behaviour claims.
2. **Prefer no branch.** If the straight band works on current data, build the straight
   band. Absence of a special-case is a feature.
3. **When a value IS withdrawn, sweep every copy.** Mine had propagated to 9 places across
   4 files — including live logic in the mockup that actually implemented the suppression,
   and **two already-delivered peer notes where I'd recommended it as acceptance criteria.**
   Grep for the number *and* the paraphrase; a delivered note can't be edited, so it needs
   an explicit correction note.
4. **Watch for poisoned fixtures too.** Same session: drives 35/36 report LTFT exactly
   0.00 across 232 samples, zero variance — unresolved between a genuine adaptive-memory
   reset and a decode artifact. Never baseline a "healthy" mock on data whose validity is
   still open.

Related: [[pattern-ui-as-ssot-consumer]] (I render the SSOT, I don't redefine it — but
rendering it faithfully includes rendering the *right version* of it) ·
[[pattern-ground-in-existing-implementation]] · [[pattern-defects-first-existing-artifact-review]]

**The general form:** config membership is not evidence of PID support; a card tagged
`both` is not evidence of both. Both errors this month were the same shape — **a label
asserting scope, believed without checking the underlying observation.**
