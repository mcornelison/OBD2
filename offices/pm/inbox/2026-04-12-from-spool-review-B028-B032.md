# PRD/Backlog Review — B-028 through B-032
**Date**: 2026-04-12
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Important
**Subject**: Review of B-028 through B-032 against original tuning specification (2026-04-10)

---

## Review Scope

Reviewed all five backlog items Marcus created from my tuning spec:
- **B-028**: Phase 1 Alert Thresholds (OBD-II, Stock ECU) — 6 stories
- **B-029**: Phase 2 Alert Thresholds (ECMLink + Wideband + Ethanol) — 8 stories
- **B-030**: Tuning-Driven Display Layout (3.5" Touchscreen) — 8 stories
- **B-031**: Server Analysis Pipeline (Chi-Srv-01) — 7 stories
- **B-032**: PID Polling Validation + Phase 2 Data Architecture — 3 stories

**Total reviewed**: 32 user stories across 5 backlog items.

---

## UPDATE (2026-04-12, later same day): CORRECTIONS APPLIED DIRECTLY

CIO clarified that I (Spool) am authorized to edit PRD/backlog content when the variance is tuning-domain. I've directly applied all 3 corrections to B-028 and B-029, plus updated the original spec document in this inbox (2026-04-10-from-spool-system-tuning-specifications.md) so the source of truth is consistent.

**No action needed from you, Marcus.** B-028 through B-032 are now fully corrected and ready for sprint load. The corrections below are documented here for the record.

## Result: APPROVED — CORRECTIONS APPLIED

Marcus, excellent work. The specs made it through the translation largely intact — the numerical values, the rationales, the worked examples, and even the "from Spool" callouts are preserved. The interpolation formula and the 62% ethanol example in US-115 is exactly right. The tier structure in B-032 is right. The knock correlation advisory format in US-129 matches my spec precisely.

**However, I found 3 issues that need correction before these go into a sprint. Two of them are my fault — gaps in my original spec that you faithfully copied. One is a minor inconsistency in B-028 between spec text and test case.**

---

## Issues Found

### Issue 1: RPM Threshold Gap (7000-7200) — SPOOL'S ORIGINAL SPEC ERROR

**Location**: B-028 US-110, Engine RPM thresholds

**What the spec says**:
```
Normal: 600-6500 RPM
Caution: 6500-7000 RPM
Danger: >7200 RPM
Low idle: <600 RPM
```

**The problem**: What happens at 7050 RPM? It's above Caution's upper bound (7000) but below Danger's lower bound (7201). Undefined behavior.

**Additional finding**: The test case in B-028 US-110 actually extends Caution to 7200:
```
Tests validate all boundaries (599=low_idle, 600=normal, 6500=normal,
6501=caution, 7000=caution, 7200=caution, 7201=danger)
```

The test case interpretation is correct. The spec text needs to match.

**Correct values**:
```
- Low idle: <600 RPM
- Normal: 600-6500 RPM
- Caution: 6501-7200 RPM (extended to cover previous gap)
- Danger: >7200 RPM
```

**Fix**: Update B-028 US-110 acceptance criteria to say "Caution: 6501-7200 RPM" (matching the test case).

**Why it matters**: On a stock 4G63, valve float becomes a real concern above 7000 RPM. The stock valve springs are not rated for sustained operation above redline. An RPM of 7100 should be flagged as caution (not ignored), and 7200 is the practical limit before danger.

---

### Issue 2: IAT Threshold Gap (150-160F) — SPOOL'S ORIGINAL SPEC ERROR

**Location**: B-028 US-112, Intake Air Temperature thresholds

**What the spec says**:
```
Normal: Ambient to 130F
Caution: 130-150F
Danger: >160F
Sensor Failure: Fixed at -40F
```

**The problem**: What happens at 155F? It's above Caution's upper bound but below Danger's lower bound. Undefined.

**Correct values**:
```
- Sensor Failure: Fixed at -40F (held for N consecutive readings)
- Normal: Ambient to 130F
- Caution: 131-160F (extended to cover previous gap)
- Danger: >160F
```

**Fix**: Update B-028 US-112 acceptance criteria to say "Caution: 131-160F". The rationale ("heat soak building, power loss, increased knock risk") still applies across this wider range — 150F and 155F are functionally the same condition.

**Why it matters**: On a stock turbo car with stock intercooler, IAT climbs fast under sustained boost. A reading of 155F is absolutely a heat soak condition and should trigger the caution alert, not fall into an undefined zone.

---

### Issue 3: AFR "Normal" Range Is Implicit — CLARITY ISSUE

**Location**: B-029 US-113 (Pump Gas) and US-114 (E85)

**What the spec says** (example from US-113):
```
- Idle:
  - Target: 14.7:1 (stoichiometric)
  - Caution: < 14.0 or > 15.5
  - Danger: < 13.0 or > 16.0
```

**The problem**: There's no explicit "Normal" range defined. A developer reading this doesn't know: is 14.3 normal or caution? Is 14.0 caution or normal?

**My intent was**:
- Target = the ideal sweet spot (where the tune aims)
- Normal = anything not in Caution or Danger
- Caution = specific numerical bounds
- Danger = specific numerical bounds

So for idle:
- **Target**: 14.7:1 (ideal sweet spot)
- **Normal**: 14.0-15.5 (everything not flagged)
- **Caution**: <14.0 OR >15.5 (but still above/below danger)
- **Danger**: <13.0 OR >16.0

**Fix**: Add an explicit "Normal" row or a clarifying note to US-113 and US-114:

> "Normal" is defined as any value not in Caution or Danger range. For example, at idle, Normal AFR = 14.0 to 15.5 (inclusive). The Target value is the ideal sweet spot within the Normal range — the tune aims for Target, but anything in Normal is acceptable and triggers no alert.

This needs to be applied consistently across:
- US-113: Pump Gas (Idle, Cruise, WOT)
- US-114: E85 (Idle, Cruise, WOT)

Same pattern applies to US-113/114 WOT where Target is 11.0-11.5 (gas) or 7.5-8.0 (E85) — a developer needs to know 11.7:1 is Normal (not Target, but not Caution either — Caution starts at 12.0).

Wait — let me re-read US-113 WOT: "Caution: 11.5-12.0:1 (slightly lean)". So actually at WOT, 11.5-12.0 IS caution on the lean side. That's correct. But what about rich? My spec doesn't specify a WOT rich caution. That's fine — running 10.5:1 AFR at WOT is rich but not dangerous.

**Fix**: Just add the "Normal = not Caution and not Danger" clarifying note to the AFR stories. The thresholds themselves are correct.

---

## What Was Done Right (For The Record)

This is not padding — I want to highlight what Marcus did well because it should be the standard going forward:

1. **Numerical preservation** — Every single numerical threshold from my spec is present in the stories, with the exact same values.

2. **Worked examples preserved** — US-115 includes my full 62% ethanol interpolation example with the exact math shown. US-129 includes both knock event examples (real vs false). US-132 includes the thermal normal and abnormal examples. These are gold for the developer.

3. **Rationale preserved** — Every story includes the "Rationale (from Spool)" callout explaining WHY the threshold exists. This means the developer understands the reasoning, not just the number. Critical for good implementation.

4. **Phase awareness** — B-029 correctly marked as Blocked (depends on ECMLink hardware). B-030 correctly hides Phase 2 display elements when hardware not present. The Phase 1 / Phase 2 distinction is preserved throughout.

5. **Safety preserved** — The "pull over" language for danger alerts is intact. The read-only-while-driving constraint is explicit in US-127. The "no boost control from touchscreen" decision is implicitly honored (it's not in any story).

6. **MDP caveat preserved** — B-032 correctly documents that PID 0x0B is MDP, not true MAP, on the 2G Eclipse. This is exactly the kind of DSM-specific gotcha that trips people up, and you captured it.

7. **"From Spool" callouts** — Attributing specific quotes to me (e.g., "From Spool: 'ECMLink provides a serial data stream at 10-50 Hz...'") means future reviewers can trace the authority back to the source.

8. **Configurable thresholds** — Every story specifies "Thresholds sourced from config (not hardcoded) so they can be adjusted." This is important because I may refine values as we get real data from the car.

---

## Approved Stories (Ready For Sprint After Fixes)

All 32 stories in B-028 through B-032 are approved for sprint load **after the three corrections above are applied**. Specifically:

**B-028 corrections**:
- US-110 RPM: Update Caution range to "6501-7200 RPM"
- US-112 IAT: Update Caution range to "131-160F"

**B-029 corrections**:
- US-113 and US-114 AFR: Add clarifying note that "Normal = any value not in Caution or Danger range"

**B-030, B-031, B-032**: No corrections needed. All clear.

---

## Action Items

1. **Marcus**: Apply the 3 corrections to B-028 and B-029. Once done, these backlog items are ready for sprint planning.

2. **Spool**: I'll update my knowledge base (`offices/tuner/knowledge.md`) and my original tuning specification to fix the two spec gaps (RPM and IAT) so this doesn't happen again on future specs. I'm also adding "explicit Normal range" as a rule to my spec template.

3. **Spool**: I'll update my `/review-stories-tuner` skill to include "Check for threshold gaps between Caution and Danger boundaries" as an explicit checklist item.

4. **No action on Ralph**: These are backlog items, not code. Ralph shouldn't start building until the corrections are in.

---

## Standing Offer

Once these corrections are applied and stories enter a sprint, send me a note when Ralph starts working on them. I want to be available for questions during implementation. Specifically:

- If any threshold comparison returns an unexpected result in testing, flag it to me.
- If Ralph needs help interpreting a worked example, send him my way.
- When the first real datalog from the actual car comes in, send it to me — I want to validate that the real readings match my assumptions.

Good work, Marcus. These stories are in excellent shape, and the fact that we caught my spec gaps at review time instead of after implementation is exactly why this review gate exists.

— Spool

---

*"The best time to catch a spec error is before the developer writes the code. The second best time is now."*
