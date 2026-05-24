# Single Source of Truth (SSOT) — project-wide design pattern

**Standing CIO directive, 2026-05-18.** Stated during the power-management
reframe; prototyped in the Shutdown Sequencer (V0.27.15); **carry project-wide**.

## The rule

- **One authoritative provider per *fact*.** Not three code paths each making
  a possibly-different system call for the same fact. *One version of the
  truth.*
- **Consumers apply policy, never their own acquisition.** Different consumers
  may apply different tolerance on top of the *same* source (e.g. a UI renders
  the instantaneous value and tolerates a blip; a safety trigger smooths the
  same source before acting) — but they read ONE provider.
- **Separate facts that get conflated.** Two different questions are two
  different facts with two different providers. The power saga's original sin
  was inferring *"am I on external power?"* (source) from *"how much charge is
  left?"* (a VCELL charge *trend*). Different facts → different providers.

## Why

The V0.27.2–.15 power rabbit hole + near-bricking traced largely to **three
divergent power-source acquisition paths** (`UpsMonitor.getPowerSource`
VCELL-trend heuristic, `PldSensor` GPIO6, `PowerManager`) that could disagree
— and to a *UI-grade* signal being reused as a *trigger-grade* signal.
**Divergent truth is the bug class.**

## How to apply

Before writing any code that reads or derives a system fact, ask:

> "Is there already an authoritative provider for this fact?"

- **If yes:** consume it. Apply your own policy. Do *not* re-acquire.
- **If no:** create *exactly one* provider, then route everything through it.

This is **enforceable under the Atlas design gate** for load-bearing facts.
For non-load-bearing facts (UI niceties, telemetry), the same principle
applies as good practice but isn't gate-enforced.

## Prototype reference

`PowerSourceProvider` (the power-source fact, wrapping the X1209 GPIO6 PLD
line). See:

- `specs/architecture.md` §2 (power-source detection — SSOT narrative)
- `docs/superpowers/specs/2026-05-18-pi-shutdown-sequencer-design.md` §2
- `docs/superpowers/plans/2026-05-18-pi-shutdown-sequencer.md` T3/T4
- The retired heuristic is retained as a **`NotImplementedError` tripwire** so
  any future reintroduction fails loudly at the call site. That's the SSOT
  enforcement mechanism: when there's one provider, there's also one loud
  failure surface guarding against reintroduction of competing providers.

## Cross-references

- Atlas (architect) — owns the design gate that enforces this; office
  `offices/architect/`
- `feedback-spool-role-boundaries` — analogous stay-in-lane / file-comms rule
- Memory: `~/.claude/projects/.../memory/project_ssot_design_pattern.md`
  (this file's canonical project-spec form)
