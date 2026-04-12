---
name: review-stories-tuner
description: "Spool reviews PM-created user stories against original tuning specifications before they enter a sprint. Use after Marcus creates stories from Spool's specs, before Ralph starts building. Catches lost thresholds, wrong units, missing edge cases, and spec drift."
---

# Tuning Specification Review — Story Validation Pass

Spool reviews user stories created by the PM to ensure nothing was lost in translation from the original tuning specifications. This is a quality gate before stories enter a sprint.

---

## When To Use

- After Marcus (PM) creates user stories from Spool's tuning specs
- Before stories are loaded into a sprint for Ralph (developer)
- When CIO asks Spool to review stories or backlog items
- Anytime stories touch: PIDs, thresholds, alert logic, display values, analysis formulas, sensor data, or tuning parameters

## The Flow

```
Spool sends specs → PM creates stories → THIS REVIEW → PM loads sprint → Ralph builds
```

---

## Step 1: Gather Inputs

Read these files:
1. **The original spec** — find the most recent Spool note in `offices/pm/inbox/` that the stories were based on
2. **The stories** — read `offices/ralph/stories.json` or the specific backlog items in `offices/pm/backlog/`
3. **Spool's knowledge base** — `offices/tuner/knowledge.md` for authoritative threshold values
4. **Any related PRDs** — check `offices/pm/prds/` if the PM created a PRD from the specs

---

## Step 2: Run The Checklist

For each user story that touches tuning domain knowledge, verify ALL of the following:

### Numbers and Values
- [ ] Are all threshold values present and match the original spec exactly?
- [ ] Are there specific numbers in acceptance criteria, not vague language? ("alert at 220F" not "alert at high temp")
- [ ] Do min/max/caution/danger ranges match knowledge.md?
- [ ] Are default values specified where applicable?
- [ ] **Threshold gap check**: For every parameter with Normal/Caution/Danger levels, is there ANY undefined range between consecutive levels? (e.g., Caution ending at 150F but Danger starting at >160F leaves 151-160F undefined — this is a bug)
- [ ] **Vehicle-specific value check**: For any threshold that depends on vehicle model/year/trim, is the value correct for the CIO's specific car? The 1998 Eclipse GST is a 97-99 2G with 7000 RPM factory redline (NOT 7500, which is the 95-96 2G). Model-year-specific values must be verified against the actual vehicle.
- [ ] **Code impact check**: Does this threshold already exist in `src/obd_config.json` with a different value? If so, the correction requires a code change (config + tests), not just a doc update. Flag as a code impact item in the review.

### Units
- [ ] Temperature in Fahrenheit (not Celsius) — project standard
- [ ] AFR as ratio (11.5:1) not Lambda (0.78)
- [ ] Boost in psi (not kPa, not bar)
- [ ] Fuel trim as percentage with sign (+5%, -3%)
- [ ] Injector duty cycle as percentage
- [ ] Ethanol content as percentage

### Formulas and Calculations
- [ ] Is the ethanol interpolation formula captured? (linear interpolation between gas and E85 values by ethanol %)
- [ ] Are statistical calculations specified? (mean, std dev, trend slope)
- [ ] Are comparison methods defined? (baseline ± 2 std dev = anomaly)

### Edge Cases
- [ ] What happens when a sensor is disconnected or returns invalid data?
- [ ] What happens at 0% ethanol (pure gas)? At 100% ethanol?
- [ ] What happens when the wideband is not installed (Phase 1)?
- [ ] What happens when ECMLink is not available (OBD-II only mode)?
- [ ] Are IAT sensor failure quirks noted? (constant -40F = known 2G failure mode)

### Phase Awareness
- [ ] Does the story specify which phase it belongs to? (Phase 1 = OBD-II only, Phase 2 = ECMLink)
- [ ] Are Phase 2 features gated so they don't break Phase 1?
- [ ] Are the correct parameters used for each phase? (no knock count in Phase 1 — it's not available)

### Safety
- [ ] Are danger-level alerts clearly distinguished from caution-level?
- [ ] Is the "pull over" language preserved for critical alerts (coolant >220F, AFR lean under boost)?
- [ ] Are hard limits defined that cannot be overridden from the UI?
- [ ] Does the story preserve the "no E85 without proper tune" safety rule?

### Display
- [ ] Are display values specified with exact format? ("185F" not "185 degrees Fahrenheit")
- [ ] Is color coding defined? (green/yellow/red matching threshold levels)
- [ ] Is the status indicator logic clear? (worst-case-wins: if ANY param is red, indicator is red)
- [ ] Are touch interactions limited to safe operations? (read-only while driving)

### Analysis
- [ ] Are analysis inputs and outputs both specified?
- [ ] Do the example outputs match the examples in the original spec?
- [ ] Are trend analysis windows defined? (minimum 5 drives, slope calculation method)
- [ ] Is the advisory output format specified? (finding → possible causes → recommended action)

### Internal Consistency (Spool's Own Work)
- [ ] If this review recommends corrections, does every recommended value match any direct file edits Spool is also making?
- [ ] Are the numbers in the review note IDENTICAL to the numbers in the fixed file? (An earlier review had 6501-7200 in the note but 6501-7000 in the file edit — PM caught the inconsistency)
- [ ] Is the Spool spec itself internally consistent? (Does the table match the test case? Does the rationale match the value?)

---

## Step 3: Write The Review

Create a note in the PM's inbox: `offices/pm/inbox/YYYY-MM-DD-from-spool-story-review.md`

### If All Clear:
```markdown
# Story Review — APPROVED
**Date**: YYYY-MM-DD
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Routine

## Review Scope
[Which stories/backlog items were reviewed]

## Result: APPROVED
All tuning specifications are accurately captured. Thresholds, units, formulas, and edge cases
match the original spec. Stories are ready for sprint.

## Notes
[Any minor observations that don't block approval]
```

### If Corrections Needed:
```markdown
# Story Review — CORRECTIONS NEEDED
**Date**: YYYY-MM-DD
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Important

## Review Scope
[Which stories/backlog items were reviewed]

## Result: CORRECTIONS NEEDED
[Count] issues found. Stories should not enter sprint until corrected.

## Issues

### Issue 1: [Story ID] — [Brief description]
**What the story says**: [Quote the incorrect/missing part]
**What it should say**: [The correct specification with exact values]
**Why it matters**: [What goes wrong if this ships as-is]

### Issue 2: [Story ID] — [Brief description]
...

## Approved Stories
[List any stories that passed review and can proceed]
```

---

## Step 4: Log The Review

Add a brief entry to `offices/tuner/sessions.md` under the current session:
```
### Story Reviews
- Reviewed [N] stories from [backlog item/sprint]
- Result: APPROVED / CORRECTIONS NEEDED ([count] issues)
- [One-line summary of most significant finding, if any]
```

---

## What This Review Does NOT Cover

- Story format, point estimates, sprint sizing — PM's domain
- Implementation approach, code structure — developer's domain
- Database schema, API design — architect's domain
- Test strategy, test coverage — tester's domain

**Spool reviews the WHAT (tuning accuracy), not the HOW (implementation approach).**

---

## Red Flags — Immediate Rejection

If any of these appear in a story, reject it immediately:

- Threshold values with no specific number ("alert when too hot")
- Wrong units (Celsius instead of Fahrenheit, Lambda instead of AFR ratio)
- Phase 2 features without Phase 1 fallback behavior
- Safety alerts that can be dismissed or overridden without limits
- Boost control from the touchscreen UI (CIO and Spool agreed: read-only for safety-critical params)
- Any reference to catless exhaust (Illinois emissions compliance)
- AFR targets that don't account for ethanol content

$ARGUMENTS
