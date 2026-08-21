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

## The rule, extended (CIO directive, 2026-08-20)

Two further clauses, stated by the CIO after a day in which BOTH were found violated in production.
**Normative, project-wide.**

### A. Land what you read

**If we read any data, we land it.** Every acquisition is persisted — not only sensor and vehicle data
but **metadata and log data too**. An unlanded read is unreproducible: it cannot be audited, diagnosed,
or re-derived, and it evaporates the moment the surface that displayed it repaints.

**Worked example, 2026-08-20 — this rule is what made a diagnosis possible.** The ICM-20948
magnetometer was found latched (one value re-served forever). It was provable ONLY because 29,148
samples had been landed in `edr_imu_sample`: "1 distinct value across 29,148 rows" is a statement you
can only make about data that was *kept*. Had the magnetometer merely been published to the UI, each
reading would have overwritten the last and the defect would have been invisible — exactly as it was
invisible on screen, where a frozen compass looks like a stationary one.

**Corollary — landing must not manufacture a reading.** "Land everything" means *never let acquired
data evaporate*; it does NOT mean *write a row regardless*. If a read failed, or returned an implausible
or invariant value, no value was acquired — land the **typed absence and its reason**, never a
fabricated measurement. The three 2026-08-20 fabrications (`syncPending=0`, all-zero IMU frames, the
latched magnetometer) are what this corollary forbids. See *Honest availability* below.

### B. Read once → persist → publish → subscribe

**Never read the same source twice, and never acquire it separately for two display locations.**
The pipeline is one-directional:

```
   ONE reader  →  persist  →  publish  →  N subscribers (UI, sync, triggers, analytics)
```

Two surfaces needing the same fact is **not** a reason for two acquisitions. It is the reason the
published topic exists.

**Worked example 1 — the sharpest one this project has produced.** `PldSensor` (the X1209 GPIO6
power-present line) was constructed in **two separate processes**: `lifecycle.py:2342` (`eclipse-obd`)
and `power_watch/__main__.py:376` (`eclipse-powerwatch`). A GPIO line is an **exclusive OS resource**, so
the second process to start received `GPIO busy` and silently degraded to a fallback — every boot.

Note what distinguishes this from ordinary drift: **a duplicated *config* read merely diverges; a
duplicated *exclusive-hardware* read fails by construction.** The operating system enforced the contract
the software did not. Most SSOT violations are quiet; this one could not be.

**Worked example 2.** The version chip is served from **two providers** — the dashboard reads
`.deploy-version`, while splash and shutdown read `version.txt`. Both derive from `RELEASE_VERSION`, but
at different deploy steps with a failure gate between them, so a failed restart-verification leaves the
two surfaces displaying **different versions** — in precisely the scenario where knowing the true
running version matters most.

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

3. **Raw-sensor schema fact (cross-tier EDR persistence).** The EDR raw-sensor
   tables (`edr_imu_sample` / `edr_light_sample`) are a fact both tiers need: the
   Pi creates SQLite tables now, and the future server MariaDB migration (F-115)
   must match column-for-column. Left to hand-written DDL per tier, this is the
   *same* bug class as the A-15 server-address mirrors — divergent copies of one
   fact. Cure (A-4 / A-14 gate #4): the DDL is authored **once** in a versioned
   `src/common/edr/sensor_schema.py` contract (`SCHEMA_VERSION` bare-int stamped
   into every row, mirroring `power_watch.RECORD_SCHEMA_VERSION`) and both tiers
   *derive* from it — neither hand-writes its own copy, so the Pi↔server drift
   cannot arise. The Pi wires the contract by importing `EDR_SCHEMAS`/`EDR_INDEXES`
   and splatting them into its existing `CREATE IF NOT EXISTS` loop; the server
   table, when F-115 lands, is generated from the same module. This is SSOT
   applied *ahead* of the consumers for a cross-tier schema — one source, both
   tiers reference. Built Sprint 50 / V0.29.4 (US-408). See `specs/architecture.md`
   §10.8.2 and the ADR
   `docs/superpowers/specs/2026-06-30-edr-sensor-reader-schema-bus-adr.md` §2.

4. **Server-analytics authority — the *derived-data* boundary (server tier, F-104).**
   Drive identity had fragmented into an id-family — the Pi-minted `drive_id`, the
   de-facto server identity `drive_summary.id`, and scattered FKs — and a persisted
   analytic (`drive_statistics`) had **two** writers (the B-104 compute-harness and
   the `/analyze` path) that could disagree, last-writer-wins. **Same bug class**
   as the address mirrors and the power-source saga: N divergent copies of one
   fact. **Cure (F-104):** one canonical server-minted `drives.drive_id` **SSOT for
   drive identity** (subsuming `drive_summary.id`, anchored by
   `UNIQUE(source_device, source_drive_id)` + an idempotent upsert-by-natural-key
   mint that never renumbers); one **sole-writer compute-harness** that derives
   every persisted-analytics table **from synced raw** (idempotent — re-run = 0
   owned-row diffs); Pi ids demoted to advisory `source_*` (compute-locally-for-UI,
   thrown away). The **boundary rule** is the derived-data generalization of "one
   provider per fact": *a fact is server-authoritative iff the server can reproduce
   it from raw → server sole-writer; irreproducible → raw, the Pi emits it
   first-class; no derived state the Pi transmits.* The **loud failure surfaces**
   this pattern requires: the `attribution_anomaly` tripwire (kept **detecting on
   the raw** Pi id so a dual-mint still trips — the backstop is not blinded by the
   deduped server identity) + the `NotImplementedError` trigger-seam tripwire
   (`enqueueAutoAnalysisForSync`) guarding against re-introducing a Pi-side writer.
   *Status (Sprint 55 / V0.29.9):* the identity SSOT (US-448) + idempotency proof
   are **landed**; formalizing the harness as the *sole* writer is in progress —
   the second `drive_statistics` writer via `/analyze` (`basic.py`) is an open
   reconciliation (BL-017), the exact "N divergent writers of one fact" this
   pattern exists to kill, pending an Atlas ruling. See `specs/architecture.md`
   §10.7.3 + the F-104 ADR
   `offices/architect/reports/2026-07-04-f104-server-analytics-authority-design-gate-ruling.md`.

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

## Honest availability — the *unavailable-source → typed-NA* pattern

> **STATUS: NORMATIVE (CIO-directed 2026-07-01).** The honest-instrument
> corollary of SSOT for a live data surface. Applies to every consumer that
> displays or records source data (carousel emitters, EDR-bus display
> subscribers, any status surface). Owning gate: Atlas.

**The rule.** A live display/record surface must **always show real data or an
explicit "not available" — never a blank, a stale value, or a fabricated one —
from one SSOT.** Two sub-rules make it honest:

1. **Availability is a property of the SOURCE, not the parameter — one truth per
   source.** When the OBD link is down (car off / disconnected), *every* OBD
   parameter is unavailable *together*. So each source (OBD link, IMU, light,
   UPS) owns exactly **one availability fact** — a retained STATE topic
   `state.source.<x> = available | unavailable`, written by that source's reader.
   Every parameter from that source inherits it. Do not compute availability
   per-parameter (that re-imports the "N divergent copies of one fact" bug this
   whole doc kills).

2. **NA is a TYPED absence (NULL + a reason), NEVER a numeric sentinel.** In the
   data / bus / DB, an unavailable value is **NULL plus a status** (`unavailable`
   / `sensor_absent` / `stale` / `no_drive` / `na_this_vehicle`), *never* a magic
   number (`-1`, `0`, `9999`). A numeric NA silently corrupts aggregations
   (`AVG` over `-1`s) and gets rendered as if real — the exact class of the
   `pd_stage = -1` sentinel pain (US-276/277) and the reason `data_source` /
   `data_quality` are enums and `drive_id` goes NULL not `0`. The **display**
   *renders* "NA" / "—" (a visual, derived from NULL + the reason); the **datum
   stays NULL** so analytics never counts it. The reason travels with it so the
   surface is honest about *why* ("OBD: off" vs "sensor not installed" vs "stale
   — last seen 40s ago") — a driver reads those very differently.

**Layering (where the NA is resolved).** Keep the raw bus **real-or-silent** —
`raw.<source>.*` STREAM topics carry real numbers or nothing; do **not** put NA
onto the raw bus (that would force `Sample.value: float | tuple | None` and drag
NA through the analytics path). Instead the **transform / display-state tier**
(the emitters that write the state a UI reads) resolves *value + source-
availability → real-or-typed-NA* **once**, so every consumer shows the same
thing — this is the "shared transform before publish" of the EDR-bus direction
above, applied to the derived "what does the operator see" fact. And it must be
**fresh every tick**: the emitter writes real-or-NA on each cycle and never
leaves the last real value sitting stale when the source drops. *(Putting NA on
the raw bus is a real fork; decide it when the EDR bus grooms. Default: don't —
keep raw analytics pristine.)*

**Worked example.** Pi on wall power, car off → `state.source.obd = unavailable`
→ the System Status card shows "OBD: off" and every engine parameter shows
"NA (no OBD)", all fresh, none fabricated. Meanwhile a wired IMU / light sensor
has `state.source.imu = available` → those show **real** data on the same
screen. The display is an honest mosaic — real where the source is live,
typed-NA-with-reason where it isn't — from one SSOT. (Compare the current splash
"eclipse-obd: not ready" — same idea, generalized to every card.)

**Anti-patterns this forbids:** green-when-source-down; a card frozen on the last
real value after the link dropped; a numeric NA sentinel in a table/analytic; a
takeover/alert firing on an empty/absent state (an absent DTC source must read
`unavailable`, not "no codes → all-clear" and not a mis-fired alert).

### Detecting it — a non-measurement can look perfectly valid, so test for VARIANCE

Honest availability says *what to publish* when a source is unavailable. This is *how to notice*, because
the hard cases do not announce themselves.

**Two checks, both on the SUCCESS path** (the absence and error paths are usually already honest — a read
that raises is easy):

1. **Implausible magnitude.** A value outside what physics permits is not a reading. A resting
   accelerometer must read ~9.81 m/s²; an all-zero frame is not a quiet measurement, it is no measurement.
2. **Invariance.** A channel returning **N consecutive BIT-IDENTICAL samples** is not reading.

#### Test bit-identity, NOT "low variance" — this distinction is the whole rule

The intuitive implementation is *"flag a channel whose variance falls below threshold X."* **That is
wrong twice over:** it needs a tuned magic number, and it **will** false-positive on a legitimately
stationary system, whose readings really are nearly constant.

**Bit-identity has neither problem.** Every real sensor dithers ±1 LSB from thermal noise and ADC
quantization **even in a perfectly constant field**. So N consecutive bit-identical samples cannot occur
naturally, at any threshold, in any environment. The test needs no calibration and cannot cry wolf.

**Measured proof (2026-08-20).** A device held stationary, then hand-rotated, sampled 90 s:

```
accelerometer : 743 distinct values      <- dithering normally, tracking motion
magnetometer  :   1 distinct value       <- latched; bit-identical throughout
```

Same die, same instant, same physical motion. **The noise floor IS the detector.**

#### The property may live ACROSS samples, not IN one

This is why per-sample validation is insufficient. The magnetometer's `-26.7 µT` was **fresh, finite and
physically plausible** — every individual sample passed inspection. The defect existed only in the
*sequence*. A gate that asks only *"is this value possible?"* will pass a latched channel forever; it must
also ask *"is this channel actually varying?"*

#### Corollary — derived fields go NA with their input

Never derive a precise value from a stale one. A heading printed to 0.1° from a frozen magnetic vector is
maximum apparent precision over zero information. When a source channel is gated, every field derived from
it publishes typed NULL + reason.

### Config-time corollary — an unresolved `${VAR}` placeholder is a string sentinel

> **STATUS: NORMATIVE (Atlas ruling 2026-08-02, verified in code).** The
> config-load analog of sub-rule 2. Verified: `secrets_loader._resolveString`
> (`src/common/config/secrets_loader.py:151-153`) returns the **literal
> placeholder string verbatim** when the env var is unset *and* the key carries
> no inline `${VAR:default}` — a warning is logged, nothing raises.

Consequence: for a `${VAR}`-bound optional key with the env var unset, the
validated config holds a **truthy `"${PI_HOME_LAT}"` string**, so the validator's
`None` default **never fires** (the key is already "present"). A downstream
consumer that reads the key directly gets that literal string — a *confident
wrong value* masquerading as data. This is the numeric-sentinel failure mode of
sub-rule 2, in string form, moved to config-load time.

**The rule.** For any placeholder-bound key that may legitimately be unset
(optional secrets, PII like location, hardware not yet installed):

1. The key's **provider normalizes** an unresolved `${...}` literal to typed-NA
   (`None` + reason), exactly as `HomeLocationProvider` does (US-517) — the same
   "resolve availability once, at the provider, not at each consumer" discipline
   as the live-surface rule above. Never leave a raw consumer to discover the
   literal.
2. **OR** the key carries an inline `${VAR:default}` — but only when a committed
   default is honest. It is **not** honest for PII or a fabricated physical
   anchor (a coordinate/altitude in source is both committed PII *and* a made-up
   fact); those stay `${VAR}`-bare and rely on rule 1.

A future config lint could flag placeholder-bound keys read without NA-
normalization — routed as a candidate, not built here.

## Cross-references

- Atlas (architect) — owns the design gate that enforces this; office
  `offices/architect/`
- `feedback-spool-role-boundaries` — analogous stay-in-lane / file-comms rule
- Memory: `~/.claude/projects/.../memory/project_ssot_design_pattern.md`
  (this file's canonical project-spec form)
