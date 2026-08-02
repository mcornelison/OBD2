---
name: feedback-honest-approximate-vs-hide
description: Honest-instrument does NOT mean "hide any value you can't measure precisely." For a non-safety-critical readout, the CIO prefers a DERIVED/approximate value clearly LABELED as approximate over showing nothing. Spool refined it: label it as Δ-from-a-known-anchor with an uncertainty band, not a specific-looking absolute. Reserve "no source"/hide for when even a trustworthy derivation is unavailable, or when a wrong value could mislead a safety decision.
metadata:
  type: feedback
---

# Honest-approximate: show a labeled estimate, don't just hide it

When altitude turned out to have **no measured source** (no baro, no GPS yet, Atlas 2026-07-31), my
instinct was the strict move: render **"no source"**. The CIO (2026-08-01) chose differently:
*"nothing critical is altitude based, it is more a FYI fun fact as I am driving"* → **show the
DERIVED value now**, labeled approximate, swap to real GPS later.

**Why:** honest-instrument is about **not misleading**, not **withholding**. A value that is (a) not
safety-critical and (b) clearly marked as an estimate informs without lying. Hiding a useful fun-fact
is worse UX than an honest approximation. The dishonesty to avoid is an *unlabeled* estimate that
reads as precise, or a *fabricated* value where none exists.

**Spool's refinement (the HOW is his lane, 2026-08-01):** even an approximate value must clear the
project's honesty bar. Don't show a specific-looking absolute (`≈ 312 m`) — show **Δ-from-a-known
anchor with an uncertainty band** (`≈ +4 m from home · ±35 m`), where the band **widens with the
error's real driver** (for dead-reckoned altitude: `σ_pitch × distance`, so it visibly loses
confidence over a drive). Δ-from-anchor is also the quantity the derivation actually produces;
quoting absolute borrows credibility from the anchor the derived part hasn't earned.

**How to apply — the decision:**
- **Measured, trustworthy** → show it plainly.
- **Derived/approximate, NON-critical** → **show it, labeled**, as Δ-from-anchor + a widening ± band;
  give it a `source` field so the feed swaps derived→measured later with the band disappearing.
- **Safety-critical AND uncertain** → do NOT show a soft number (a wrong coolant/knock/voltage can
  drive a bad decision) — degrade to an honest state (Spool's damage-in-progress rules).
- **No value AND no trustworthy derivation** → "— no source", grayed, never zeroed.

Ask **"could a wrong-ish value here cause harm?"** — if no, prefer honest-approximate over hiding,
and prefer Δ+band over a specific absolute. Refines charter §3 principle 2; pairs with
[[pattern-ui-as-ssot-consumer]].
