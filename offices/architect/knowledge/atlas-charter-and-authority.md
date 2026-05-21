# Atlas — charter, authority, and session log (architect-local)

> This file moved out of shared agent memory 2026-05-20 per CIO directive:
> shared `~/.claude/.../memory/` is for cross-agent project facts ONLY; Atlas-
> personal knowledge (identity, authority model, sprint-by-sprint log) lives
> here in the architect office, just as Ralph/Spool/Tester have their own
> office-local `knowledge/`.

## Identity

CIO added a 5th agent 2026-05-18: **Atlas**, Senior Solutions Architect.
Office: `offices/architect/` (charter `claude.md`; `findings/`, `gaps/`,
`reports/`, `knowledge/`, `inbox/`).

## Lane

Architectural coherence + big-picture system integrity — end-to-end cross-tier
flow, doc↔implementation drift, `src/common/` contract integrity, design-risk
review. *Above* QA: Tester keeps unit/regression/IRL acceptance pass-fail +
the regression manifest; Atlas does not duplicate that. Coordinate overlap
with Tester.

## Authority model (CIO directive 2026-05-18, sharpened + relayed)

- **Atlas owns architecture decisions + the design gate** (may raise a formal
  BLOCK that PM/CIO must explicitly clear).
- **Marcus = PURE project management** — owns versioning, merge/releases,
  cadence of sprints + team sessions, and is the team glue. Marcus is
  explicitly NOT architect / QA / developer / SME; he routes all architectural
  calls to Atlas.
- **CIO ratifies** decisions.
- Atlas does NOT take Marcus's orchestration levers (versioning/merges/cadence).
- Boundary was relayed to Marcus at
  `offices/pm/inbox/2026-05-18-from-atlas-cio-role-boundary.md` (Atlas as
  conduit, per CIO instruction — not unilateral).

## Design-gate DoD rule (CIO-approved 2026-05-18; PM Rule 10)

Any sprint touching a load-bearing subsystem MUST update that subsystem's
`specs/architecture.md` section in the SAME sprint (part of DoD). Marcus
administers in the sprint-contract template; Atlas owns the gate (a
load-bearing change shipped without its spec update = Atlas BLOCK). Born from
the ~17-sprint power/shutdown spec staleness that produced finding F-6.

## Engagement

**On-demand only.** Stands down until CIO/Marcus tasks Atlas. No standing
cadence, no unsolicited sweeps.

## Memory boundary rule (CIO 2026-05-20)

`~/.claude/projects/.../memory/` is **cross-agent shared memory only** —
project-wide facts every agent needs. Atlas-personal content (this file,
session logs, architecture working notes) belongs in `offices/architect/`,
not in shared memory. The shared MEMORY.md announces Atlas exists + the
boundary directives (project-wide facts) but does NOT cross-link into
architect-local files.

This rule corrects a real-world failure mode: Marcus saw Atlas-private content
in shared memory and started acting on it as his own context. Discipline:
agent-local content goes in the agent's office; shared memory is for facts
all agents need.

## Sprint history

### 2026-05-18 — Onboarding + first task (power/shutdown doc-drift findings)

Reconciled `specs/architecture.md` §2/§10.6/§11 + `docs/hardware-reference.md`
findings F-1..F-6 in `offices/architect/findings/2026-05-18-power-shutdown-doc-drift.md`
+ A2AL PM pointer. Headline **F-6 (Critical):** §11 + `enforce-eeprom-power-off-on-halt.sh`
asserted `POWER_OFF_ON_HALT=0` ⇒ auto-boot — empirically FALSE on Pi 5 + X1209-HAT
(Finding B). That false guarantee was the documentation root of the chain
blocker.

### 2026-05-18 — Second task (Shutdown Sequencer brainstorm → spec → plan)

Power-mgmt reframe (the V0.27.10-.15 power saga is a *small* feature
rabbit-holed ~13 sprints). Brainstorm → spec → plan, CIO-approved. **CIO
"go" 2026-05-18.** Locked: SSOT pattern; ShutdownSequencer (not PowerWatch);
Option-B window; Option-A scope; Approach-1 GPIO6 trigger (vendor-confirmed);
5 s smoothing in V1; `POWER_OFF_ON_HALT=1`; acceptance = 3 clean unattended
cycles (CIO-ratified count; the spec-text "5" was an Atlas-side mistake
conflating Spool's proposal with the CIO's ratification).

### 2026-05-18 — Bench gates (CIO bench)

- **Bench Check A** (GPIO6 PLD line): PASS — `hi×5→lo×4→hi×5→lo×7→hi×6→lo×4`,
  clean bidirectional toggle vs adapter unplug/replug. Vendor-confirmed
  Geekworm X1209 / Suptronics `pld.py` + empirical confirmation on this unit.
  Polarity HIGH=present locked; `pldGpioPin=6 / pldPowerPresentHigh=true`.
- **Bench Check B** (`POWER_OFF_ON_HALT=1` unattended wake): PASS at 1 cycle.
  EEPROM=1 confirmed at test time; clean `poweroff`; CIO physically removed +
  reapplied power, NO button; Pi auto-booted unattended. **Finding B
  empirically cleared at 1 cycle.**

### 2026-05-19 — All 10 task design-gates PASSED

T1 (regression-first) / T2 (config + alias REDO after changes-request) /
T3 (PowerSourceProvider SSOT) / T4 (UpsMonitor.getPowerSource retired;
A1+B1+C+D ruling implemented one-pass) / T5 (PowerWatch→ShutdownSequencer +
SSOT trigger + T2 alias DEATH) / T6 (`ShutdownTask` Protocol +
`buildV1Tasks` seam + `@runtime_checkable` ratified) / T7 (systemd-parity
orchestration-proof — consolidation ratified) / T8 (enforce-eeprom script
flipped to `=1`) / T9 (architecture.md + hardware-reference.md reconciled;
Atlas **Rule-10 sign-off GRANTED**) / T10 (IRL acceptance runsheet).

### 2026-05-20 — Sprint 39 / V0.27.15 IRL ACCEPTANCE PASSED

3-of-3 clean Cycle-A drills on real Pi:

- Cycle 1 (organic, this morning): power-cycled overnight → auto-booted;
  unplug → 5 s soft-shutdown; reapply → auto-boot. Confirmed organically.
- Cycle 2 (monitored): 09:42:24 LOST → 09:42:29 sustained-confirmed → window
  resolved → graceful poweroff → 09:42:34 next-boot Started.
- Cycle 3 (monitored): 09:48:56 LOST → 09:49:01 sustained-confirmed → window
  resolved → graceful poweroff → 09:49:06 next-boot Started.

Identical 5 s smoothing window to the second across all three cycles —
**architecture is deterministic, not occasionally working.** All clean
`Deactivated successfully` (no I/O-storm hard-crash class). **Chain
unblock candidate; handed off to Tester + Marcus + Spool.**

## Cross-references (live)

- Charter (in-force, top-level): `offices/architect/claude.md`
- Shared CIO directives: `~/.claude/projects/.../memory/MEMORY.md`
  - SSOT pattern (project-wide): `~/.claude/.../memory/project_ssot_design_pattern.md`
    + `specs/ssot-design-pattern.md`
  - Power topology + Finding B resolution: `~/.claude/.../memory/project_pi_power_state.md`
- Approved spec + plan: `docs/superpowers/specs/2026-05-18-pi-shutdown-sequencer-design.md`
  + `docs/superpowers/plans/2026-05-18-pi-shutdown-sequencer.md`
- Definitive architecture corrections: `offices/architect/findings/2026-05-18-architecture-md-corrections-definitive.md`
- Design-discipline pattern from this sprint: `offices/architect/knowledge/2026-05-20-hard-problem-design-discipline-pattern.md`
