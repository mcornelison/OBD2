# BL-028: US-504a battery-health drain writer blocked on two unanswered rulings

| Field        | Value                     |
|--------------|---------------------------|
| Severity     | Medium                    |
| Status       | Active                    |
| Blocking     | US-504a (Sprint 69 / V0.29.24) -- the LAST open story in the sprint |
| Waiting On   | (1) PM/Atlas: orphan policy for the drain-event writer (touches the shutdown path). (2) Spool: the qualifying-gate / band overlap in his US-504 verdict spec. |
| Created      | 2026-08-02                |

## Description

US-504a builds the production drain-event writer that makes `battery_health_log`
grow again. It carries `"status": "needs-ruling"` and its own `conditionalOutcomes`
say **"BLOCKED ON TWO RULINGS"**. Neither ruling arrived during Sprint 69, so the
story was never startable. Filing this as a formal blocker because the sprint
contract requires a documented blocker to back the stop condition, and the
routing so far lives only in inbox notes and the story body.

**Ruling 1 -- orphan policy (PM / Atlas).** US-442 requires a production writer
to open+close a drain event as a single unit OR guarantee the close on the
shutdown path. But the drain most worth measuring is the one that ENDS in a
cutoff shutdown, which is exactly where a deferred close is most likely to be
lost. Three options are on the table (A: open-at-loss + close-at-restore-or-
shutdown + boot reaper; B: single INSERT at close with the drain held in memory;
C: A with the ShutdownSequencer close primary and the reaper as backstop).
Ralph recommends **C**. This touches the shutdown path, so it is a design-gate
call, not a dev call.

**Ruling 2 -- gate/band overlap (Spool).** Found and filed by US-504b: his
qualifying gate (`runtime_seconds >= [EXACT:600]`) sits entirely ABOVE both
sub-good bands (degraded 436-582 s, replace <436 s). Every row that survives the
gate is therefore always "good", so through the real pipeline **degraded and
replace are unreachable**, and a pack genuinely dying at 500 s is discarded as a
partial drain rather than reported as degraded. The verdict silently cannot
degrade -- it fails safe toward reassurance, the wrong direction for an honest
instrument. If Spool moves to a depth/cutoff-reached gate, **this writer is what
has to record that signal**, so his answer changes what US-504a must write.

## Impact

- **1 story stalled**: US-504a. It is the only story in Sprint 69 not at
  `passes: true` (10 of 11 complete as of 2026-08-02).
- **Sprint 69 cannot reach COMPLETE** without either the rulings or a PM
  decision to carry US-504a into V0.29.25.
- **Downstream**: the Health card correctly reads `unknown` + last-check
  `2026-05-16` and will keep doing so PERMANENTLY, not "until fresh drains
  exist" -- there is zero production caller writing rows since US-442/TD-058
  retired the auto-open path. US-504b (the verdict producer) is DONE and green;
  it is not blocked by this, it simply has nothing new to consume.

## Attempted Solutions

- US-504 was **carved** into US-504a (writer) + US-504b (producer) on its own
  `conditionalOutcome`, precisely so the producer would not stall behind the
  writer's rulings. That worked: US-504b shipped.
- Both rulings were routed on 2026-08-02:
  - `offices/pm/inbox/2026-08-02-from-ralph-us504-carved-504a-writer-504b-producer.md`
    (orphan policy, 3 options + recommendation C)
  - `offices/tuner/inbox/2026-08-02-from-ralph-us504-gate-band-overlap-and-writer-gap.md`
    (gate/band overlap)
- No reply to either as of this filing.

## Proposed Resolution

Recommended: **carry US-504a into the next sprint** rather than hold Sprint 69
open. The other 10 stories are complete and committed, and the V0.29.24 deploy +
IRL drill does not depend on the drain writer.

The two rulings can then be resolved in grooming order:
1. Spool first -- his gate answer determines *what gets written*, so answering
   the orphan policy before it risks specifying the wrong lifecycle.
2. PM/Atlas orphan policy second, with the shutdown-path implications settled.

**LOAD-BEARING TRAP to carry forward** (from the story body, do not lose it): if
a boot reaper is built it MUST NOT close orphans via `endDrainEvent`, which
computes `runtime_seconds` from the timestamp delta. Across a reboot that
manufactures a runtime spanning the whole downtime, clears the 600 s gate, and
poisons the verdict median with a fabricated multi-hour "drain". The reaper must
stamp `end_timestamp` and leave `runtime_seconds` NULL so the row can never
qualify.

## Resolution

[Open]
