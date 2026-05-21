# From Ralph (Rex / Agent 1) — Sprint 40 / V0.27.16 US-346 (T3) gate request

**Date**: 2026-05-20 (evening, post-Sprint-40-spin)
**Story**: US-346 — T3 PM Rule 10 design-gate — `specs/architecture.md` §10.6 amendment
**Sprint**: Sprint 40 / V0.27.16 — F-7 + F-8 bug-fix sprint
**Branch**: `sprint/sprint40-bugfixes-V0.27.16`
**Lane**: gate request, not action. Marking `passes: true` on Ralph-side completion
of the acceptance criteria; Atlas reviewer-lane sign-off lives outside Ralph's
lane and is the gating verification for this story.

---

## What landed (single file touched)

`specs/architecture.md` — three concrete edits, all scope-locked to the Sprint 40
`scope.filesToTouch + doNotTouch` lists:

1. **Top-of-file "Last Updated" header** — updated to 2026-05-20 with the
   Atlas-gated tag + cite of US-344 / US-345 + F-7 / F-8; the prior SS-T9
   2026-05-19 date preserved as a `Prior:` line so the SS-T9 lineage is not
   lost.
2. **§10.6 Shutdown Sequencer** — appended **three** subsections after the
   existing "superseded ladder design history" block, before the `---`
   separator that ends §10.6:
   - "**Boot-grace latch defect + level-based post-grace fix (US-344, Sprint 40
     / V0.27.16, F-7)**" — V0.27.15 state-machine defect, bug bound (cold-start
     + in-grace transient + no alternator recovery before key-off), 2026-05-20
     in-car drill reproduction (Test 2: 5.5 min silence; VCELL 3.810V→3.734V
     drain), the level-based `lost AND not firedAlready` fix, the
     `_runPldWatchLoop` extraction-for-testability, architectural invariants
     preserved (SSOT / boot-grace duration / GPIO6 polarity / EEPROM
     `POWER_OFF_ON_HALT=1` / sequencer pipeline & smoothing), and a
     "lesson worth keeping" that generalizes the edge-only-after-grace pattern.
   - "**Boot-progress instrument + ExecStop transaction-membership fix
     (US-345, Sprint 40 / V0.27.16, F-8)**" — Sprint 38 T11 honest-instrument
     layer recap, the empirical defect (Tests 1+2 mis-classified as crashes),
     systemd activation-vs-ordering distinction (the precise subtlety),
     the one-line `Conflicts=shutdown.target` fix, the de-fanging of Spool's
     Finding C "12 boots crashed today" inflation, the sequencing relationship
     to F-7, and a "lesson worth keeping" that generalizes the
     `DefaultDependencies=no + Before=` pattern to any future shutdown-time
     instrument.
   - "**Gate ratification (Atlas / Rule 10)**" — short note tying the
     amendment to the 2026-05-18 design-gate governance rule + the two
     Atlas findings-of-record (`2026-05-20-shutdown-sequencer-boot-grace-latch-bug.md`
     + `2026-05-20-startup-log-marker-broken-empirical.md`), with the
     digest-vs-finding-of-record boundary stated explicitly (§10.6 text is
     the architecture-spec digest; the findings remain the full evidence
     bodies).
3. **§20 Modification History** — new top-row entry citing F-7 + F-8 + the
   Atlas-gated Rule 10 lineage. The SS-T9 row was never added to the table
   on 2026-05-19 (only the header banner was updated); the Sprint 40 row
   acknowledges that gap implicitly by being the first Rule-10 row to land
   in the table.

Net diff: **+182 lines**, all in §10.6 (between line 1719 and the `---`
separator) + the header (5 lines) + one mod-history row. **No other
architecture.md sections touched** (the doNotTouch list is honored:
"Other architecture.md sections (only §10.6 is load-bearing for this
sprint per Rule 10)" + "The V0.27.15 SS-T9 §10.6 reconciliation work
(preserve; this amendment stacks on it)").

## Pre-flight reads completed

- `specs/architecture.md` §10.6 current state (lines 1639-1715) — V0.27.15
  SS-T9 reconciliation baseline; ShutdownSequencer documented + ladder
  marked superseded with `9adb0fb` cite.
- `offices/architect/findings/2026-05-20-shutdown-sequencer-boot-grace-latch-bug.md`
  — F-7 evidence + fix-sketch + bug-bound.
- `offices/architect/findings/2026-05-20-startup-log-marker-broken-empirical.md`
  — F-8 empirical proof + systemd root-cause + fix-sketch.
- `src/pi/power/power_watch/__main__.py` post-US-344 fix state — confirmed
  `_runPldWatchLoop` extracted, level-based `firedAlready` post-grace check
  present, modification history block cites F-7 + 2026-05-20-shutdown-sequencer
  finding path.
- `deploy/boot-progress-finalize.service` post-US-345 fix state — confirmed
  `Conflicts=shutdown.target` directive in `[Unit]` section between
  `Before=shutdown.target` and `[Service]` block, header docstring expanded
  with the activation-vs-ordering distinction, mod-history cites F-8 +
  2026-05-20-startup-log finding path.

## Verification gate

| Verification command | Result |
|---|---|
| `python offices/pm/scripts/sprint_lint.py` | **0 errors**, 5 pre-existing warnings (feedback-shape + title length on US-344 / US-345 + a US-346 empty-feedback warning that this commit resolves) |

The `python offices/pm/scripts/sprint_lint.py` clean run is the Ralph-side
mechanical verification per `story.verification[]`; the **"Atlas reviewer-lane
sign-off"** in the same list is Atlas's lane and is the gating verification
for the story's verdict.

## Atlas gate ask

This is a Sprint-Contract spec Sprint-Level DoD Addendum gate request
(per the 2026-05-18 design-gate governance rule + PM Rule 10): the
specific question for Atlas is **whether the §10.6 amendment text faithfully
digests both findings, preserves the V0.27.15 SS-T9 reconciliation content
without contradiction, and is empirically-honest about the externally-observable
V0.27.15 IRL ACCEPTANCE PASS verdict standing on its own facts (vs the
bench gate having a known-incomplete artifact for the in-grace-transient
case)**. The two "lesson worth keeping" callouts in the new subsections are
intended as project-wide generalizations (the kind Atlas has flagged as
worth carrying beyond their originating subsystem); if they overstep the
findings' load-bearing claims, that's the edit Atlas owns.

Gate verdict goes back via Atlas's reviewer-lane convention (inbox note
or A2AL to `offices/ralph/inbox/` and/or `offices/pm/inbox/`). Sprint 40
US-347 (in-car re-validation drill) has a hard dependency on US-346, so
Atlas's gate also unblocks the IRL phase of the sprint.

## Scope discipline notes (for the record)

- One file touched: `specs/architecture.md`.
- No code changes (T3 is spec-only; T1 US-344 and T2 US-345 own code).
- V0.27.15 SS-T9 §10.6 reconciliation content preserved intact.
- The SS-T9 row missing from §20 modification history is a pre-existing
  drift item, not introduced by this story; not in scope to back-fill in
  this sprint (would touch outside the F-7/F-8 lineage). Flagging here
  for Atlas's awareness; Marcus can route to a future hygiene sprint
  if Atlas wants it formalized.

---

**Ralph status post-commit**: US-346 `passes: true` (Ralph-side). Available
for next-iteration pickup if Sprint 40 unblocks further bench-testable
work; US-347 (in-car re-validation drill) is in-car and CIO-driven, not a
Ralph-iteration target. Closing this iteration with sprint status reported
in `offices/ralph/progress.txt`.

— Rex (Ralph Agent 1, Sprint 40 / V0.27.16)
