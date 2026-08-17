# Aside — `pi.powerWatch.smoothingSec` 5→10 Tuning Bump on Sprint 40 Branch

**From**: Atlas
**To**: Marcus (PM)
**Date**: 2026-05-21 (just past midnight after the 2026-05-20 live drill)
**Priority**: Informational (NOT a finding, NOT chain-blocking)
**Tone**: Heads-up so Sprint 40 branch state stays unambiguous

---

## What happened

During the post-drill conversation tonight, CIO asked how to bump `smoothingSec` from
the Sprint 39 design value of 5 sec to ~10-15 sec to give the in-car
crank-transient false-trigger more abort headroom. I gave the exact `config.json`
edit; CIO applied it directly:

```json
    "powerWatch": {
      "smoothingSec": 10,
      "smoothingPollSec": 1
    },
```

(Added under `pi`, alongside the existing `powerMonitoring` block. Validator default
was 5; explicit override is now 10. `smoothingPollSec` is unchanged from validator
default — kept in the JSON for clarity.)

This edit is on the working tree of `sprint/sprint40-bugfixes-V0.27.16` branch (the
sprint Ralph is currently working). CIO will commit it shortly — not bundling into
a Ralph story since it's a tuning override, not a bug-fix deliverable.

JSON parses, `python validate_config.py` passes, sequencer will pick it up at next
`systemctl restart eclipse-powerwatch` (or full Pi deploy via `deploy-pi.sh`). New
journal startup line will read `smoothing=10s`.

## Why I'm filing this

Three reasons:

1. **Branch hygiene** — when Ralph commits Sprint 40 deliverables, this config diff
   shouldn't surprise anyone reviewing the branch. The commit message will mark it
   as CIO interim tuning, but the inbox note makes the intent visible without
   anyone having to git-archaeology it.

2. **Spool's lane** — `smoothingSec` is a Spool-owned tuning parameter (BL-018
   territory). The 5→10 change was made tonight under in-car-tuning-need urgency,
   not via BL-018's empirical-validation path. Spool gets a heads-up note from me
   too (separate filing) so he can fold it into BL-018 once chain merge clears.
   No corrective action needed from PM — just noting the lane crossing.

3. **PM Rule 10 NOT triggered** — this is a config-only tuning override, not a
   load-bearing code change to `power_watch`. `specs/architecture.md` §10.6 does
   NOT need an in-sprint update for this bump (Sprint 40's T3 spec amendment is for
   the F-7 fix logic, not this tuning value). I want that lane-call recorded so
   it doesn't get conflated with Rule-10 work.

## Sprint 40 status from where I sit

Per shared memory update CIO landed: branch `sprint/sprint40-bugfixes-V0.27.16` is
spun, 4 stories US-344..US-347, sprint.json clean, Ralph dispatched. Atlas gates
per-task when Ralph routes completions. Same cadence as Sprint 39.

No action required from PM on this note. Just keeping the workspace state
transparent.

— Atlas
