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

## Worked examples

The pattern has now bitten — and been enforced — at two different tiers. Both
are the *same* bug class (divergent copies of one fact) with the *same* cure
(one canonical source; everything else derives or references; a loud gate guards
against re-divergence).

1. **Power-source fact (Pi runtime).** Three acquisition paths
   (`UpsMonitor.getPowerSource` VCELL-trend, `PldSensor` GPIO6, `PowerManager`)
   could disagree → near-bricking. Cure: one `PowerSourceProvider` (GPIO6 SSOT),
   competing paths retired to a `NotImplementedError` tripwire. (See Prototype
   reference above.)

2. **Server-address fact (config / deploy).** The chi-srv-01 address was held as
   a literal in three sanctioned mirrors — `config.json`, `validator.py`
   DEFAULTS, `deploy/addresses.sh` — that the B-044 audit *exempts*, plus
   `config.json` triplicated it internally. The 2026-06-18 `.10 → .120` box move
   updated some copies and not others → sync broke. This is **"documented
   duplication," not SSOT.** Cure (Watch item A-15): a mirror-consistency gate
   (`scripts/audit_address_mirrors.py` + `tests/lint/test_address_mirror_consistency.py`)
   that fails when any copy diverges — the loud failure surface this pattern
   requires. Lesson reinforced: *an audit's guarantee is only as wide as what it
   inspects.* "No new stray literal" (B-044) and "the blessed copies still agree"
   (A-15) are two different guarantees; you need both gates.

## Emerging direction — SSOT for *derived* data, enforced at a broker (EDR bus)

> **STATUS: DRAFT — current CIO thought process, NOT yet ratified.** Captured
> here so the direction is visible and consistent with the rule above; do **not**
> treat the bus specifics below as gate-enforced until the CIO firms it. Owning
> gate: Atlas A-14 #4. Sources: `offices/architect/reports/2026-06-16-edr-vs-b104-architecture-ruling.md`;
> `docs/superpowers/specs/2026-06-18-edr-dedicated-reader-bus-contract-design.md`.

The EDR epic generalizes SSOT from *raw* facts to *derived* ones. The shape:

- **One dedicated reader-service** reads every source (K-line, 9-DoF IMU, light)
  at its needed rate and **publishes to an internal bus / pub-sub** — one
  acquisition path per source, not one per consumer (the §"How to apply" rule,
  applied to acquisition).
- **Consumers subscribe and apply their own policy** (FDR vault, UI/display,
  triggers, server-sync) — the consumer-applies-policy rule, unchanged.
- **Any transform more than one consumer needs goes in a shared transformation
  layer *before* publish** — so SSOT holds for *derived* data too, enforced at
  the broker rather than re-computed divergently downstream. (This is the
  conceptual extension: today SSOT covers raw facts; the bus extends it to
  computed ones.)
- **Server-sync is a uniform subscriber**, not a special path — it subscribes to
  raw + marker topics, persists locally, hands to the server on upload. This
  makes the "raw still goes to the server, server keeps persisted-analytics
  authority" rule a *subscription filter*, not a remembered exception, and forces
  **per-subscriber QoS** (lossless/durable for sync + safety; lossy-OK for
  display).

Why this belongs with the rule: the A-15 address drift and the power-source saga
are both "one fact, N divergent copies." The bus is the same cure applied
*ahead* of the consumers and *for derived data* — one transform, one published
value, everyone else subscribes. When the CIO ratifies, this section graduates
from draft to normative and the EDR contract artifacts become its prototype
reference.

## Cross-references

- Atlas (architect) — owns the design gate that enforces this; office
  `offices/architect/`
- `feedback-spool-role-boundaries` — analogous stay-in-lane / file-comms rule
- Memory: `~/.claude/projects/.../memory/project_ssot_design_pattern.md`
  (this file's canonical project-spec form)
