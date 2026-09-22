# Design Patterns — Eclipse OBD-II

**Last Updated: 2026-09-21** · Owner: Atlas (architect) · Authored to the CIO's charter
amendment of 2026-09-20: *identify patterns, catalogue them, and route Ralph to them by name
in every design-gate review.*

## The membership test — this is the whole gate

    applies in ONE place    -> it is an IMPLEMENTATION. It belongs in the ticket.
    applies in TWO or more  -> it is a PATTERN. It belongs here.

**A one-time-use approach is not a pattern.** Every entry states: the pattern · **when it
applies** · **at least two real instances from this project** · the anti-pattern it prevents.
An entry that cannot produce two instances gets deleted, not defended.

🔴 **In a review, name the pattern by name** — *"use threshold + dwell (§1)"* — not a
re-explanation. That is the routing duty; re-explaining is how one rule ends up in two
wordings.

---

## 1. Threshold + Dwell — never a bare threshold on a noisy signal

**Pattern.** A numeric threshold does not count as crossed until it has *stayed* crossed for a
named interval. The dwell carries its own clock. Where the action is irreversible, add
hysteresis: the level that *enters* a state is not the level that *leaves* it.

**When it applies.** Any comparison of a live sensor value against a limit where the resulting
action is expensive or irreversible.

**Instances.**
1. 🔴 **The cutover spike.** Measured `VCELL 4.1063 → 3.6787 V in 114 ms` at a wall-power cut
   on a nearly-full pack. **Any bare threshold in that window fires on a healthy battery.**
   Now a requirement in `specs/shutdown-orchestration-design.md`.
2. **`smoothingSec` in the shutdown sequencer.** A transient blip must never command a
   poweroff — one that did bricked the Pi on 2026-05-18. The debounce *is* the dwell.
3. **The SOC→VCELL trigger switch (US-234)** shipped `3.70 / 3.55 / 3.45 V` **with 0.05 V
   hysteresis**, for exactly this reason.

**Anti-pattern prevented.** A transient reading triggering an irreversible action — and its
mirror, a threshold that flaps a state back and forth at the boundary.

⚠️ **Dwell is not free: it is a LATENCY you must be able to afford.** `smoothingSec = 7` needs
7 s of life; measured survival has been **0–956 ms**. **A dwell longer than the survival
window is an inert guard (§6).** Size it from measured capability (§4).

---

## 2. Crash-only — durable at write, never at shutdown

**Pattern.** Every write is made durable when it is made. Nothing depends on an orderly
shutdown path executing. Recovery is the *normal* start path, not an exceptional one.

**When it applies.** Any component that can lose power or be killed at an arbitrary instant —
on the Pi, that is everything.

**Instances.**
1. 🔴 **The shutdown ceremony does not run.** Across three in-car key-offs:
   `prior_boot_last_stage = RUNNING`, **zero** `battery_health_log` drain events, no
   `CLEAN_COMPLETE`. Survival measured **0–956 ms** against a sequence needing 7 s.
2. **The fsync'd witness rigs.** `hb_witness.py` and the `h2_*` family write, flush and
   `fsync` **every line before the next sample**, because the journal buffers and **loses its
   own tail** — which is why every earlier attempt witnessed nothing.
3. **`power_loss_heartbeat`** uses `synchronous = FULL` and is deliberately Pi-local.

**Anti-pattern prevented.** Deferring durability to a path that demonstrably does not execute,
then recording its output as a guarantee.

**External grounding.** Candea & Fox, *Crash-Only Software* (HotOS IX, 2003): a crash-only
system has **one way to stop and one way to start**, and such systems often recover faster than
they shut down and restart. SQLite supplies the mechanism — WAL plus `PRAGMA synchronous=FULL`
for writes that must survive power loss — and SQLite **never assumes page writes are atomic**,
so it recovers from torn pages by construction.
⚠️ Those guarantees assume the storage honours locking, write-order and sync. **Cheap or
failing flash controllers violate them**, which matters here: our data is single-copy on an SD
card.

---

## 3. Provider/consumer SSOT with decimation

**Pattern.** One acquisition, one authoritative rate. Consumers **decimate** from it; they
never re-acquire and never claim a rate above their source. Where a rate is clamped, **the
clamp is logged** — a silent clamp is a lie in the config.

**When it applies.** Any fact with more than one consumer at different cadences.

**Instances.**
1. 🔴 **The IMU triple**, ruled `sampleHz 4 / persistHz 2 / stateHz 1` (CIO, 2026-09-21).
   `_decimationFactor = max(1, round(sampleHz/persistHz))`
   (`src/pi/bus/edr_persistence_subscriber.py:122-136`) is **integer** rounding, so `4 → 2 → 1`
   is exact while `5 → 2` silently becomes 2.5 Hz. 🔴 **At 5 Hz the triple cannot be expressed
   without a config field that lies. At 4 Hz it can.**
2. **The prior defect this fixes:** `persistHz 25` above a `sampleHz` of 5 makes the factor
   return 1 — no decimation — so **the config states a rate the system cannot deliver and
   nothing reports it.**
3. **`states/` publication** — the sequencer writes state and consumers react; the sequencer
   never names a consumer (F-103 decoupling).

**Anti-pattern prevented.** Two components independently sampling one source and disagreeing;
and a configured rate that is silently unachievable.

---

## 4. Derive every budget from MEASURED CAPABILITY — never from an observed failure

**Pattern.** A timeout, reserve, threshold or rate is derived from what the system has been
*measured* able to do — never from the value at which it was last seen to fail, and never from
a number a different operating condition paid for.

**When it applies.** Every constant with a unit.

**Instances.**
1. 🔴 **An early `shutdown-orchestration-design` draft sized the shutdown budget from the
   0.49 s death.** That would have written the bug in as a requirement. **0.49 s is a symptom,
   not a budget** — the same pack runs minutes at the same voltage.
2. 🔴 **`smoothingSec = 7` was sized to fit a 7.5 s splash animation** that is now shed. A UX
   duration became a safety constant.
3. 🔴 **"It sustained 5.716 W, so draw is not the killer."** Wrong: that peak occurred **on
   wall power**, which paid for it. Only the final 821 ms was on battery.
4. **`sampleHz 50` was chosen from what the sensor *can* do**, not what the analysis needs —
   the root of the entire rate problem.

**Anti-pattern prevented.** Encoding a symptom, a cosmetic duration, or another regime's number
as an engineering limit.

⚠️ **A measured capability is only transferable with its conditions.** Sub-cliff UPS runtimes
span **10× at the same load** (`1.64 W → 162 s`, `1.65 W → 76 s`, `~1.8 W → 762 s`) — and
starting voltage does not explain it either (`4.2012 → 762 s`, `4.1763 → 76 s`,
`4.1413 → 162 s`, non-monotonic). ⇒ **Record the TRIPLE with every power run: starting VCELL,
mean load, terminal VCELL** (Spool, 2026-09-21). A capability without its conditions is not a
budget input.

---

## 5. Distinguishable failure states — *unreachable* ≠ *unreadable* ≠ *not yet attempted*

**Pattern.** Every distinct way a thing can fail gets a distinct, recorded value. Never
collapse two failures into one flag, and never let *"I could not look"* render as *"there is
nothing there."*

**When it applies.** Any predicate read from something that can be absent, silent, broken, or
simply not asked yet.

**Instances.**
1. 🔴 **`_readLink` fails OPEN** (`src/pi/bus/edr_log_gate.py:159-180`), so *"the ECU is
   silent"* and *"the link is unreadable"* land on the same branch — and the gate records
   everything, which is how **96.6 % of stored EDR data became orphaned.** A third case exists
   and was unnamed: **not yet attempted**, which on a cold boot in a parked car also opens the
   gate.
2. 🔴 **The S41 snapshot hunt.** Missing snapshots were diagnosed as *unreachable over SMB* for
   two days. They were **non-existent** — Btrfs-only on an ext4 volume. *A visibility problem
   was debugged because the thing being hunted was assumed to be there.*
3. **Scanned manual pages are IMAGES.** A text fetcher returns an empty page, which reads as a
   dead end rather than "wrong tool" — that cost 17 days on a purge-solenoid spec.
4. **`data_quality` as a two-valued attribution flag** (Watch List A-21) — the same collapse,
   in a column.

**Anti-pattern prevented.** A confident negative produced by an inability to look.
⚠️ **Corollary: "what would falsify this?" applies to ABSENT evidence too.**

---

## 6. 🔴 The inert guard — a check that is present and enforces nothing

**Pattern.** **The presence of a check is evidence about intent, never about enforcement.** A
guard is trusted only once it has been **seen to fail** on a deliberately broken input. A green
run on an unmodified tree is not evidence that a test works.

**When it applies.** Every test, acceptance criterion, validator and documented precondition.

**Instances.**
1. 🔴 **"Confirm a recent snapshot exists before any bulk edit"** — sat in the document
   defining everyone's safety model, and **nobody could ever satisfy it**: ext4 volume,
   Snapshot Replication needs Btrfs, no snapshot had ever been taken.
2. 🔴 **A sprint's deploy gate checked for the PREVIOUS sprint's version string** — so
   deploying the sibling sprint passed it with none of the intended sprint present. In a bullet
   whose own rationale was a past version-skew incident.
3. 🔴 **An acceptance criterion that passes on unmodified code**, because the thing it asked for
   was already shipped.
4. **A documented value clamp** that a reader assumes is universal while another code path
   writes an out-of-range value.
5. **`pi.power.mode` in `config.local.json`** — removed by US-668, still present, silently
   ignored. A permanently dead toggle.

**Anti-pattern prevented.** A guarantee inferred from the existence of a guard.

**External grounding.** This is what **mutation testing** measures: break the code deliberately
and see whether any test notices. A **surviving mutant** marks an assertion that should have
caught a regression and did not. The documented shapes — **assertion-free tests**, tautological
tests, mock-asserting tests, unreviewed snapshots — all achieve coverage while being **unable to
fail**. Industrial case studies found tests that opened and closed network connections **without
ever verifying the connection worked**.

⇒ 🔴 **RULE: every new guard's acceptance must include "shown to FAIL when X is deliberately
broken."** Coverage without the ability to fail is theatre.

---

## 7. Pin the DIRECTION, not the MEMBERSHIP

**Pattern.** A structural test asserts an invariant that legitimate growth cannot violate — a
dependency *direction*, an ordering, a relationship. It does not enumerate a membership list
that correct new work will break.

**When it applies.** Any test guarding architecture rather than behaviour.

**Instances.**
1. 🔴 **The `EdrLogGate` dependency test.** `edr_log_gate.py` importing nothing from `pi.obdii`
   is the clause that keeps the re-arm safe, and it holds (`:31-36` is stdlib-only; `LinkSignal`
   is a structural `Protocol`). *"`pi.obdii.*` must not import `edr_log_gate`"* is **false on
   correct code** — the composition root legitimately does — so a developer would narrow it
   until it asserted nothing.
2. **A pinned table COUNT** (30, needing a bump to 32). A count is a membership assertion: it
   fails on every legitimate addition, gets bumped reflexively, and thereafter means nothing.
3. **The magnetometer ordering fix.** The invariant is *bypass BEFORE the gyro check* — an
   ordering, not a list of participants.

**Anti-pattern prevented.** A structural test that breaks on correct work, is weakened to pass,
and thereafter enforces nothing (§6).

---

## 8. 🔴 Every measurement states its QUANTITY, and the instrument must be able to discriminate

**Pattern.** A number carries **the name of what it measures**, not just a value and a unit.
Before trusting an instrument, state what it **cannot** show. Before comparing two numbers,
confirm they are the same quantity.

**When it applies.** Every recorded measurement, and every experiment design.

**Instances.**
1. 🔴 **time-to-DEATH vs time-to-COMMANDED-POWEROFF.** `power_loss_heartbeat` shows three
   events terminating at **exactly 7.0 s = `smoothingSec`** — deliberate shutdowns, not battery
   exhaustion. That figure circulated as a *survival* time in `load_shed.py`'s WHY table, cost
   a phantom RCA, and **cost two retractions on 2026-09-21 — one made while disputing the very
   story that fixes the mislabelling.**
2. 🔴 **`CRATE` reads `0xFFFF`** — unpopulated. Decoded through the signed scale that becomes a
   **plausible −0.208 %/hr**. Logging the decoded value would have "shown" a discharging battery
   and sent us to the wrong repair. **Log the RAW value so absence stays visible.**
3. 🔴 **`h2_sys_witness.py` exists only because a per-process CPU sampler excluded child
   processes**, reporting "CPU idle" while a rail pulled 2.4 W. *The contradiction was the
   instrument, not a finding.*
4. 🔴 **`RAIL_W` is the SoC rail sum only** — `vcgencmd pmic_read_adc` has **no EXT5V current
   channel**, so the display and USB are invisible. Every derived current, resistance and mAh
   figure is therefore a **BOUND, not a measurement** — and reading one as a measurement
   produced a retracted "degraded cell" claim.
5. **`VCELL = 3.6463`** appears while the Pi sits on **wall power at 5.2 V** and recurs across
   unrelated logs — a probable gauge artefact that several runs were described as "dying at."

🔴 **AND THE META-INSTANCE (Spool, 2026-09-21): the MAX17048 now has THREE registers producing
plausible non-readings** — `CRATE = 0xFFFF`, `SOC` anti-correlated with capability, and
`VCELL = 3.6463`. **At three, the instrument's credibility is the finding, not any one
register.** ⇒ **Count an instrument's known-bad channels. Past two, stop patching around them
and replace or externally corroborate the instrument.**

**Anti-pattern prevented.** A confident answer the instrument never earned; and comparing two
numbers that were never the same kind of thing.

🔴 **Three corollaries, all paid for:**
- **"Could my instrument CAUSE the failure?" is a different question from "is my instrument
  LYING?"** A 10 Hz I²C reader of the MAX17048 ran in four power-loss tests; the observations it
  was compared against had none of it.
- **A confound you have NAMED and declined to test is not controlled — it is documented.** A
  46-minute interval difference was written down, discounted on plausibility, and overturned a
  headline result on the one pull that tested it.
- **An instrument that dies with the thing it measures cannot witness the moment of death.**
  Every internal rig here shares that limit; the decisive measurement is external.

---

## 9. A constant carries its BASIS — express a relationship, not a frozen absolute

**Pattern.** A constant whose correct value depends on a measurable property is expressed as a
**relationship to that property**, and records what it was derived from. A frozen absolute is
correct only for the conditions that produced it, and it does not announce when those change —
**it just becomes quietly wrong.**

**When it applies.** Any constant derived from a measurement of a part, a bus, a corpus or a
vehicle — i.e. anything that can wear, grow, be replaced or be re-fitted.

**Instances.**
1. 🔴 **The OBD speed scale factor (Spool, 2026-09-21).** A measured **+1.50 %** speed-high
   reading is explained by **tyre TREAD WEAR** — a worn tyre is smaller, so the wheel turns
   faster for the same road speed. **Do NOT ship a software speed correction:** it would be
   calibrated against worn tyres and become **silently wrong the day they are replaced.** If
   a scale factor is ever needed it must be **derived from tread state**, not frozen.
2. 🔴 **`3.4712 V` hardened into "the pack cutoff."** It is not a cutoff — it is where **one
   run's load** lost the 5 V rail. Four runs ended at **3.39 / 3.46 / 3.63 / 4.19 V**. The
   constant recorded a *number* and dropped the *condition that produced it*.
3. 🔴 **`smoothingSec = 7` was sized to a 7.5 s splash animation** that is now shed. The basis
   disappeared; the constant did not.
4. 🔴 **`parkDwellSec = 20` was floored by a "13 s worst in-drive bus gap."** A wider corpus
   measured **18 s over 71 drives** — the earlier figure came from 5. **The floor moved 38 %
   because the sample grew; the constant stayed put**, leaving an 11 % margin above a maximum
   that is still growing with sample size.
5. **`sampleHz 50` was chosen from what the sensor CAN do**, not from a named phenomenon — an
   absolute with no basis recorded at all.

**Anti-pattern prevented.** A constant that was right once, is wrong now, and cannot say so.

🔴 **The test for this pattern: name what the constant was derived FROM, and state what would
invalidate it.** If you cannot, it is a magic number regardless of how carefully it was chosen.
That is the `void if` discipline (`facts/README.md` rule 7) applied to code rather than to facts
— and instance 4 is a **ruling** that needed one and did not have one.

⚠️ **A maximum measured over a finite corpus is a LOWER BOUND on the true maximum.** It grows
with sample size. A threshold placed just above it is §1's anti-pattern wearing a measurement
as justification.

⏸️ **FORWARD NOTE, NOT A WORK ITEM — deferred by the CIO 2026-09-21** (*"before we worry about
the BMW, lets get the pi and eclipse working 100%"*). Spool ruled that **no Eclipse timing
constant ports to another protocol**: the Eclipse is K-line at 10,400 bps with a measured
**2.21–2.25 s** per-PID period; CAN is 24–48× faster. `pi.gear.maxAgeSec = 3.0` is 1.33× the
Eclipse period but would be **~1000× too large on CAN — it would never trip, so a frozen
reading would render as LIVE for three seconds.** A fabricated reading (§8), not a tuning
looseness. **Recorded here because it is the cleanest statement of this pattern we have. Do
not act on it until the Eclipse platform is signed off.**

## Cross-references

- `specs/anti-patterns.md` — the catalogue of defect *shapes*; this file is the catalogue of
  *remedies*. Where they overlap, anti-patterns describes the failure and this file names the
  pattern that prevents it.
- `specs/ssot-design-pattern.md` — §3 here is its acquisition-path specialisation.
- `specs/design-discipline-hard-problems.md` · `specs/rule-13-audit-discipline.md`
- `facts/power-and-battery.md`, `facts/data-rates.md` — the measurements §1, §4 and §8 cite.
  🔴 **Cite them; do not restate their numbers here.**

## Sources

Candea & Fox, *Crash-Only Software*, HotOS IX 2003 · SQLite *Atomic Commit* and *Powersafe
Overwrite* documentation, and its power-loss guidance for SD/flash storage · hysteresis and
dwell (`for:`) practice from alarm and monitoring engineering · mutation-testing literature on
surviving mutants and assertion-free tests.
