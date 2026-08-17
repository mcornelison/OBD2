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

## The general form — now 3 for 3

Every data error on this line in August 2026 was the same shape: **a document asserting a
fact, believed without checking the observation underneath it.**

| # | The artifact believed | What it actually was | Whose error |
|---|---|---|---|
| 1 | `config.json` **poll list** membership | a *request* to poll, not proof of support (2 dead PIDs in Tier 4, eating NO_DATA) | mine |
| 2 | a tuning card tagged **`ecu: both`** | an old-ECU observation, mislabelled | Spool's |
| 3 | a probe reporting **"16 PIDs supported"** + a Tier-4 **allocation** doc | a count without an enumeration, and a *proposal* — he "read a proposal as a capability", his words | Spool's |

#3 is the instructive one: **the SME caught himself making the identical error he had just
corrected in me**, one week later, in his own SSOT. This is not a competence problem — it is
what happens when planning documents and evidence documents look alike. Neither of us is
immune, so the defence has to be structural, not vigilance.

## The structural defence

**For a display readout, the only acceptable evidence is the parameter observed returning a
real value in `realtime_data`.** Rank the artifacts and never promote one:

```
evidence   : observed in realtime_data / live capture   <- the ONLY thing that earns a tile
weaker     : a probe COUNT without an enumeration
weaker     : a tier / priority ALLOCATION doc
weaker     : config.json poll-list membership
weakest    : a scope label on a card (`ecu: both`)
```

When a peer hands over a green-light, ask **"observed where?"** — and if the answer is a
document rather than a capture, treat it as a plan. Cheap to ask; the alternative is a tile
that renders nothing, or a branch defending against a condition that no longer occurs.
