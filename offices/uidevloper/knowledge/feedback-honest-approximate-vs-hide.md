---
name: feedback-honest-approximate-vs-hide
description: Honest-instrument does NOT mean "hide any value you can't measure precisely." For a non-safety-critical readout, the CIO prefers showing a DERIVED/approximate value clearly LABELED as approximate (a leading ≈) over showing nothing. Reserve "no source"/hide for when even a derivation is unavailable, or when a wrong value could mislead a safety decision.
metadata:
  type: feedback
---

# Honest-approximate: show a labeled estimate, don't just hide it

When altitude turned out to have **no measured source** (no baro on the ICM-20948, no GPS yet,
Atlas 2026-07-31), my first instinct was the strict honest-instrument move: render **"no source"**.
The CIO (2026-08-01) chose differently: *"there is nothing critical that is altitude based, it is
more a FYI fun fact as I am driving"* → **show the DERIVED value now** (grade×speed dead-reckoning),
**labeled approximate** (`≈NNN m`), and swap to the real GPS feed later.

**Why:** honest-instrument is about **not misleading**, not about **withholding**. A value that is
(a) not safety-critical and (b) clearly marked as an estimate does not mislead — it informs. Hiding
a useful fun-fact is worse UX than showing an honest approximation. The dishonesty to avoid is an
*unlabeled* estimate that reads as a precise measurement, or a *fabricated* value where none exists.

**How to apply — the decision:**
- **Measured, trustworthy** → show it plainly.
- **Derived / approximate, NON-critical** → **show it, labeled** (`≈`, "derived", a caveat line).
  Give it a `source` field so the feed can swap derived→measured later with no layout change.
- **Safety-critical AND uncertain** → do NOT show a soft number (a wrong coolant/knock/voltage value
  can drive a bad decision) — degrade to an honest state, per Spool's damage-in-progress rules.
- **No value at all** (no source AND no derivation) → "— no source", grayed, never zeroed.

Ask **"could a wrong-ish value here cause harm?"** — if no, prefer honest-approximate over hiding.
Refines charter §3 principle 2 (honest instruments) and pairs with [[pattern-ui-as-ssot-consumer]].
