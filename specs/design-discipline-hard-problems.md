# Hard-Problem Design Discipline — the V0.27.15 pattern

> **Saved 2026-05-20** at CIO directive after Sprint 39 / V0.27.15 closed
> a 13-sprint rabbit hole in **one bounded sprint** (10 tasks + 2 bench
> gates + 3 IRL cycles, zero rework outside the gate-and-ratify loop).
> Atlas-owned discipline. Reusable for any future "small feature that has
> become a sophisticated mess" problem. Marcus orchestrates a sprint that
> follows it; Ralph implements under it; Atlas gates against it; CIO ratifies.

## When to reach for this pattern

A problem qualifies as a "hard problem" when ≥2 of these are true:

- It has been worked on for ≥3 sprints with the chain still blocked.
- The work has produced shipped regressions (or near-bricks) in real hardware.
- Documentation and reality have visibly diverged on a load-bearing subsystem.
- The dev iteration is "fix a symptom → discover another symptom → fix that"
  with no structural endpoint in view.
- Someone — CIO, PM, dev — uses the words *rabbit hole* or *over-engineered*.

If the problem is small and bounded (a single-file bug, a contained refactor),
the regular sprint workflow handles it. This pattern is for the cases where
the **regular workflow keeps producing more rabbit hole**.

## The shape

```
  CIO reframes the problem at the architectural altitude
    └─→ Atlas runs a retrospective (sprint-by-sprint, evidence-grounded)
        └─→ brainstorming skill: explore intent, propose 2–3 approaches
            └─→ CIO chooses options at the architecture level
                └─→ Atlas writes the SPEC (docs/superpowers/specs/)
                    └─→ CIO reviews + approves spec
                        └─→ Atlas writes the PLAN (docs/superpowers/plans/)
                            └─→ Bite-sized TDD tasks, each
                                with a pre-registered gate
                            └─→ Marcus lands spec + plan; sprints it
                                └─→ Ralph executes task-by-task
                                    └─→ Atlas gates EACH task
                                        └─→ Bench observations (CIO)
                                            └─→ IRL acceptance (CIO)
                                                └─→ Tester validates the chain
                                                    └─→ Sprint merge
```

**One iteration of this loop produced a clean sprint after 13 sprints of
churn.** That isn't because the team is better — it's because the discipline
caught failure modes the team had been re-entering on every sprint.

## The non-negotiable disciplines (the 10 things)

These are what *makes* the loop above work. Without them, the same loop
produces a 14th rabbit hole. Each one is grounded in a specific moment from
the V0.27.15 sprint where it caught a real failure.

### 1. Process skill first; brainstorming before any creative work

Use the `brainstorming` skill at the start. NOT optional. NOT skippable. The
output is shared understanding before code, which prevents the "let me start
exploring the codebase" reflex that produces rabbit holes.

### 2. Retrospective grounded in git, not narrative

The retrospective at the start of the redesign is *evidence-based*: read git
log, read commits, read memory files. Quote the actual diffs. The handoff
docs and the dev's memory are point-in-time and often wrong about which
commit caused what. **Trust the system over the narrative — including
prior handoffs and these notes themselves.**

### 3. Pre-registered gate criteria

For every task in the plan, Atlas writes the PASS criteria **before Ralph
starts the task**. Criteria are objective (exact greps, exact test commands,
exact assertions). This prevents post-hoc rationalization: at submission
time, the result either meets the bar or it doesn't.

When Ralph contested a pre-registered criterion at submission (Task 2 SSOT
argument), the gate held precisely because the criterion was set in
writing beforehand. *Gates that can be renegotiated by argument at
submission are not gates.*

### 4. Evidence-based gating (verify, don't trust)

When Ralph routes a task-complete note, Atlas independently re-runs the
verification: `git show` the actual diff, `grep` the actual greps, `pytest`
the actual tests, read the actual source. Never sign off on "tests pass"
without seeing the exit code + the dot output yourself.

This caught:
- Bench Check A: a single static `hi` line vs. the multi-cycle flip that
  actually proved GPIO6 toggled with power.
- Bench Check B: a "I did" without the EEPROM grep + power-cycle confirm.
- Task 4 "complete": no commit, no diff, no code — a false-done that the
  next gate-poll caught because the architect refused to certify on assertion.

### 5. Positive execution evidence — not absence-of-error

Exit code 0 doesn't prove anything ran. A test must produce a positive
artifact (marker file written, log line emitted, output captured) that the
chain *only writes if it actually executed*. The systemd-parity test (T7)
is the project's instance: it spawns `python -m src.pi.power.power_watch`
under the unit's exact PYTHONPATH and asserts a marker file the chain wrote
during a stubbed poweroff, not just "process exited 0."

This is the DOA tripwire. Sprint 28's ancestor of this test was already in
the suite when V0.27.12 shipped DOA — **because it wasn't actually RUN
before deploy**. The tripwire must run, not just exist.

### 6. Flag-and-route over silent improvisation

When the dev finds the plan is wrong or ambiguous, they STOP and route the
question back to the architect for a ruling. They do not silently fix it.
They do not guess. They do not "improve" the plan unilaterally.

When this happens, the architect:
- Verifies the dev's evidence against source.
- Owns the plan defect honestly (no ego).
- Issues a ruling on the merits, not by authority.
- Ratifies the dev's correction if it's right, or directs a different fix.

Ralph caught THREE Atlas plan defects this sprint (`_FakePld` test double
mismodeled the real PldSensor; T4 Step 3/4 contradictory against real code;
`@runtime_checkable` missing from the Protocol so `isinstance` would fail).
Each one was disclosed before submission, ratified on merits, and the plan-
of-record updated. **The architect catching their own mistakes via the
dev's discipline is the system working as designed.**

### 7. No-broken-intermediate / additive migration scaffolds

Renames and refactors are *additive + deprecated alias*, never hard
replace, when consumers are spread across multiple tasks. The alias carries
a written death date matching the consumer-rename task. Every commit stays
green.

Counter-example that was held against: Ralph's initial Task 2 SSOT
argument for a hard rename would have left the powerwatch suite red from
T2 through T5. The gate held; he re-committed additive; the alias died on
its stated date at T5. Suite stayed green across all four tasks.

The architectural distinction: **SSOT governs durable divergent
authoritative sources**, not transitional rename scaffolds. A same-sprint-
removed deprecated alias is a safe migration mechanism, NOT an SSOT
violation. Knowing which is which prevents over-applying the principle.

### 8. SSOT applied to facts, not just code

For any system fact (power source, identity, state), there is exactly ONE
authoritative provider. UI and trigger and logging all consume that ONE
provider — they differ only by the policy they apply on top. See
`specs/ssot-design-pattern.md`.

### 9. Honest empirically-gated language

When a fact rests on empirical hardware behavior, never assert certainty
beyond the evidence. The pattern: state what is **locked** (a decision),
what is **N-cycle confirmed** (empirical to date), what is **pending**, and
that **empirical drill is the sole arbiter**. F-6 was a documented
guarantee replaced *not* by a new guarantee but by this honest structure.

If your doc/script/test asserts something hardware-dependent, the assertion
includes its empirical provenance and its open-question scope. Otherwise
you've manufactured the next F-6.

### 10. Same-sprint Rule-10 spec updates

Any sprint touching a load-bearing subsystem updates that subsystem's
`specs/architecture.md` section IN-SPRINT. Not "follow-up." Not "later."
That's part of DoD; Atlas BLOCKs the sprint merge if it's missing. The
13-sprint power-doc staleness that produced F-6 happens *because* doc
updates are deferred. Don't defer.

## Orchestration-integrity corollaries (from this sprint's lessons)

- **Validation instruments must be specified against the target's ACTUAL
  deployed state**, not the repo branch. Bench Check A v1 used `from
  src.pi.hardware.pld_sensor import PldSensor` — the module didn't exist
  on the deployed Pi (V0.27.14 predates the hotfix that created it). The
  bench check was DOA against deployed state. Lesson: any validation
  instrument is itself code that must run *as wired in production* —
  identical discipline to T7.

- **Tripwire tests must RUN before deploy**, not just EXIST in the suite.
  The deploy gate must require `pytest -m "not slow"` exit-0 captured-as-
  evidence before `/sprint-deploy-pm`.

- **Bench/IRL gates are separate evidentiary tiers from code gates.**
  Code gates verify "did the dev implement the spec?" Bench/IRL gates
  verify "does the architecture actually work on real hardware?" Both
  are needed; neither substitutes for the other.

## The architect's posture

- **On-demand.** Don't drive the sprint; gate it.
- **Verify, don't trust.** Even the dev you trust. Even your own plan.
- **Own your plan defects** when the dev catches them. Ratify on merits.
- **Engage the principle on its merits** when the dev pushes back.
  Authority is not a substitute for argument. (If both the merits and
  the procedure point the same way — they did at the Task 2 gate — say
  so; that's the strongest ruling and the easiest to internalize.)
- **Refuse to certify what isn't there.** A "Ralph finished task 4" message
  without a commit, a diff, or a note is not Task 4. Say so calmly.
- **Decisive when evidence is decisive.** Skepticism that tracks evidence
  in *both* directions — hold the gate when evidence is thin, pass
  promptly when it's decisive. Reflexive doubt is its own failure mode.

## What this pattern does NOT solve

- **Hardware risk.** This pattern proves the architecture is *grounded*. It
  does not prove the hardware will behave the same in 6 months, in the car
  vs. on the bench, or after a deploy that triggers some integration we
  didn't think to test. The 3 (or 5) cycle IRL is necessary; it isn't
  sufficient against environmental edge cases.

- **Configuration tuning.** Spool's BL-018 work — empirical battery-runtime
  tuning of the smoothingSec / windowCapSec / vcellFloorVolts bounds — sits
  outside this pattern. The pattern produces a *configurable* system; what
  the right configs are for real long-haul battery behavior is the SME's
  job, gated behind the integrated system being known-correct.

- **Re-entry into rabbit holes.** Nothing prevents the team from skipping
  the discipline next time. The pattern only works when applied. Atlas's
  job, in part, is to recognize when the team is sliding back into the old
  failure mode and reframe at the architectural altitude before another
  sprint is consumed.

## How to invoke this pattern next time

When a CIO directive looks like *"we've been working on X for too long;
bring me a new perspective"*:

1. **Run the retrospective**, evidence-grounded.
2. **Invoke `brainstorming`** explicitly. State that you are doing so.
3. **Propose 2–3 architectural approaches** with trade-offs and a
   recommendation grounded in the retrospective.
4. **Lock the CIO's choices** in writing as the spec.
5. **Write the plan** in bite-sized TDD tasks with pre-registered gate
   criteria for each.
6. **Hand off to Marcus** with the spec, plan, and explicit Atlas-design-
   gate Rule-10 callout on the load-bearing-subsystem sections to update.
7. **Gate Ralph's tasks one at a time**, with the disciplines above.
8. **Bench gate** anything hardware-coupled (CIO runs; Atlas verifies).
9. **IRL acceptance** with the CIO's ratified cycle count.
10. **Hand off to Tester** (sprint-validated) and Marcus (chain merge).

Done correctly, a hard problem closes in one sprint — not because the
problem was easier than it looked, but because the discipline didn't let
it re-enter rabbit-hole mode.
