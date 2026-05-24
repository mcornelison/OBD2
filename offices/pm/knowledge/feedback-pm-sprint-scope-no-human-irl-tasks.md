---
name: feedback-pm-sprint-scope-no-human-irl-tasks
description: Sprint stories must be Ralph-pickable code work; never include human IRL tasks as stories. Human IRL gates live in validation.bigDefinitionOfDone (checklist clauses), not stories[]. The post-deploy IRL outcomes drive what the NEXT sprint contract contains.
metadata:
  type: feedback
---

# Sprint scope = code work only; never include human IRL tasks as stories

**Source**: CIO directive 2026-05-21 (during /sprint-deploy-pm for V0.27.16 Sprint 40)

> "remember when you write a sprint. do not include human IRL tasks. Those are always post deploy IRL test and the outcomes drive what the next sprint looks like"

## The rule

Sprint stories in `offices/ralph/sprint.json` `stories[]` are **strictly Ralph-pickable units of code work**. Human IRL tasks NEVER go in `stories[]`. They go in `validation.bigDefinitionOfDone` (a checklist that CIO + Atlas work through post-deploy).

## Why

1. **Post-deploy outcomes drive next sprint scope.** If the IRL drill exposes new findings (the way Sprint 39's drill surfaced F-7 + F-8), those findings ARE the next sprint contract. Treating IRL drills as in-sprint stories blurs the boundary between "what code is in this release" and "what we learn after we ship".

2. **Sprint-close mechanics break.** `/sprint-deploy-pm` Phase 0 halts on `passes:false AND status:pending` (signals "sprint not actually done"). A human-IRL story with `passes:false + status:pending` by design will trip the halt every sprint and force a manual override OR contract restructure. The deploy ritual was designed assuming Ralph-only stories.

3. **Lane discipline.** Ralph cannot drive a car, run a drill, or sign off on hardware-validated behavior. Putting CIO+Atlas+Tester work in `stories[]` violates the agent-lane separation the project is built on.

4. **Chain-merge clarity.** The `validation.bigDefinitionOfDone` block IS the chain-merge gate per Mike 2026-05-08. Its clauses are the validation contract — what real-hardware drill must pass before `/sprint-validated` + `/chain-validated`. Duplicating those clauses as `stories[]` entries muddles the source of truth.

## How to apply

When writing a new `sprint.json`:

- **`stories[]`**: each entry is a code-only unit Ralph can pick + ship + mark `passes:true` via tests + sprint_lint. Sizes S/M/L per Ralph's standard contract.
- **`validation.bigDefinitionOfDone`**: an itemized checklist of IRL gates CIO + Atlas + Tester work through post-`/sprint-deploy-pm`. Each clause cites the relevant US-### that produced the code being IRL-validated. Format: `"US-XXX IRL: <gate description>"` or `"US-XXX design-gate: <design-review gate description>"`.

If Atlas (or any reviewer) proposes a "task spine" that includes an IRL drill task (the way Atlas's Sprint 40 proposal had T1..T4 with T4 = drill), translate that drill task into a `bigDefinitionOfDone` clause — NOT a `stories[]` entry. The reviewer's "T-N" naming is fine for proposal-doc purposes; the sprint contract must split T-N tasks between `stories[]` (code) and `bigDefinitionOfDone` (IRL).

## Reference incident

Sprint 40 / V0.27.16 was written with US-347 as a separate story for the in-car drill (mirroring Atlas's T4 naming). `/sprint-deploy-pm` Phase 0 halted because US-347 had `passes:false + status:pending` by design. CIO had to pick "remove US-347 from stories[]" mid-deploy to clear the halt. The bigDefinitionOfDone clauses already covered the drill content — US-347 as a story was strictly redundant. Lesson booked here so Sprint 41+ contracts don't repeat the mistake.

## Related

- [[feedback-sprint-scope-dev-only]] — Sprint 18+ rule: dev-only sprint scope; human actions go on separate action-items list. Same principle, prior framing.
- [[feedback-runtime-validation-required]] — Sprint 19+: runtime-only-verifiable bugs require live-drill gate. The drill is the gate, not a story.
- `/sprint-deploy-pm` skill Phase 0 stop conditions (offices/pm/.claude/commands/sprint-deploy-pm.md)
