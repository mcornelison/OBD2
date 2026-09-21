# Data Acquisition Architecture — design

**Status:** approved in design, not yet built · **Owner:** Atlas (Architect) ·
**Ratified by:** the CIO, 2026-09-20 · **Ticket:** ARCH-036
**Companion:** `specs/shutdown-orchestration-design.md` (ARCH-035) — a provider defined here
is also a shutdown participant there. Same contract shape, deliberately.
**Builds on:** `specs/ssot-design-pattern.md` (CIO directive, 2026-05-18). This document
extends that pattern to **acquisition rate**, which it did not previously cover.

**Relationship to `specs/architecture.md`:** that file records the system **as built** —
`pi.sensors.imu.sampleHz (50)` at `:3853`. This file is the **target design**. They
deliberately disagree until the build lands, at which point `architecture.md` is updated **in
the same sprint** (PM Rule 10 design-gate DoD) and this file becomes the rationale for the
values there. 🔴 **Neither file is stale; do not "fix" one to match the other before the
build.** ⚠️ Note also `architecture.md:3786`: the carousel display consumer already polls at
`POLL_MS = 250` (4 Hz) off the 50 Hz stream — a consumer decimating to roughly the rate §4
proposes, which is corroboration that a low single-digit Hz rate is sufficient for the display path.

---

## 1. Why this exists

### What the system is FOR, right now

🔴 **CIO, 2026-09-20 — the priority ordering, and it decides how every story here is scoped:**

> *"The goal is to pair that ECU/OBD2 data with all of the sensory data and then do analytics
> later in a future version. Right now our core goal is data capture and making sure it is
> synced up to the server so that I can drive anytime any day without worrying about it."*

**Capture and trustworthy sync are the product NOW. Analytics is a later version.** That
reframes `specs/storage-retention-custody.md` (ARCH-037) and the A-40 vehicle-currency work as
**the deliverable**, not as plumbing beneath one. A story that improves analysis at the cost of
capture or custody is scoped against the wrong goal.

### The defect this document corrects

The project acquires data over two independent paths — **Bluetooth → OBD dongle → ECU**, and
the **I²C bus** — at rates chosen from what each device is *capable* of, rather than from what
can be **paired**. The cost is measured, not theoretical:

- **`edr_imu_sample`: 5,791,276 rows, 196,428 drive-coupled. 96.6% orphaned.**
- **`obd.db` reached 2.8 GB.** Two entire days were 100% orphaned — the car never moved and
  the Pi wrote ~1.7M rows each day.
- The IMU samples at **116× the rate the ECU answers**.

🔴 **The framing measurement (2026-09-20, within-drive, drives 81/82/83, every parameter):**

    the ECU answers at 0.43 Hz   ~2.3 s per sample

⚠️ Measure that **within a drive**. Across all history it computes to 0.002 Hz because the
span includes months of parked time — a meaningless number that looks authoritative.

## 2. The layer model

    L4  ANALYSIS      correlation, verdicts, alerts.        consumes L3 only.
        ^
    L3  CORRELATION   joins I2C facts to ECU facts on the drive/time axis.
        ^             THE ONLY LAYER THAT JOINS ACROSS PATHS.
    L2  PROVIDERS     one per FACT. Owns acquisition. Publishes a stream.
        ^             Applies no policy beyond validity.
    L1  TRANSPORT     Bluetooth/OBD link; I2C bus. Device access, retries, health.
        ^
    L0  DEVICES       ECU, ICM-20948, AK09916, TSL2591, MAX17048, GPS, ...

**Rules between layers:**

1. **A layer may only call the layer directly beneath it.** L4 never touches a device. L2
   never joins facts.
2. 🔴 **Only L3 joins across paths.** An I²C fact and an ECU fact are correlated in exactly
   one place. A provider that reaches for another provider's data is a layering violation.
3. **L1 owns the bus, not the schedule.** Transport reports health and enforces access; it
   does not decide how often anything is read.

## 3. The SSOT rule, extended to rate

`specs/ssot-design-pattern.md` already requires **one authoritative provider per fact**, with
consumers applying policy rather than their own acquisition. This adds:

🔴 **SSOT GOVERNS THE RATE, NOT ONLY THE SOURCE.**

> A fact is acquired **once**, at **one rate**, by **one provider**. Every consumer —
> display, database, analysis, alerting — subscribes to that stream and **decimates**.
> **No consumer re-acquires, and no consumer picks its own rate.**

Two subsystems reading the same device at different frequencies is the same defect as two
subsystems holding different values for the same fact. It is merely harder to see.

**The existing IMU chain is already the correct SHAPE and should be the template:**

    sampleHz 50  ->  persistHz 25  ->  stateHz 10
    one acquisition   DB consumer     display consumer

One acquisition, two decimations, consumers applying policy. **The shape is right; all three
numbers are wrong** — every one of them sits above the 4 Hz ceiling (§4).

`_decimationFactor` is `max(1, round(sampleHz / persistHz))`, so a consumer rate at or above
the acquisition rate degrades safely to "keep every sample". **Lowering `sampleHz` alone is
therefore safe and needs no code change** — but it is not sufficient: a `persistHz` or
`stateHz` left above the root is a publish rate that cannot carry new data, which is why the
ceiling applies to the whole triple rather than to the root alone.

## 4. What may be captured, and therefore how fast

### 4.1 🔴 THE PRIMARY RULE — pairing, not rate

**CIO, 2026-09-20:**

> *"If I have data coming in faster than the ECU, it is not very helpful… we should not be
> capturing rows that do not line up with ECU data."*

🔴 **A row that cannot pair with ECU data is not product data.**

**Rate is a CONSEQUENCE of that rule, not a rule of its own.** Sampling faster than the ECU
answers does not produce better data — it **manufactures rows that can never be paired**. The
project has already measured exactly what that costs: **96.6% orphaned** (5,791,276 IMU rows,
196,428 coupled) and a 2.8 GB database.

⇒ **Ask "can this row be paired?" first. The rate falls out of the answer.**

⚠️ **"Pair" means paired to a DRIVE, not to an individual ECU row.** That distinction is
load-bearing and is settled in §6.3 — read it before applying this rule.

### 4.2 The 4 Hz ceiling — a hard cap

🔴 **CIO, 2026-09-21 — TIGHTENED FROM 5 Hz TO 4 Hz:** *"max 4 per second and must align with
ECU data... this is a flight/drive data recorder not a garage data recorder."*

    ~~5 Hz~~  ->  4 Hz HARD CAP

⚠️ **The 5 Hz below was faithfully recorded, not a mis-transcription.** The 2026-09-20 quote is
preserved verbatim because it is the real record of that ruling; this is a **tightening**, not a
correction of a bad reading.

🟢 **AND 4 IS ARCHITECTURALLY BETTER THAN 5, INDEPENDENTLY OF THE RULING.**
`_decimationFactor = max(1, round(sampleHz / persistHz))` uses **INTEGER** rounding
(`src/pi/bus/edr_persistence_subscriber.py:122-136`):

    4 Hz:   4 -> 2 -> 1     every factor an EXACT integer
    5 Hz:   5 -> 2          round(2.5) = 2, effective 2.5 Hz while the config says 2

🔴 **At 5 Hz the IMU triple cannot be expressed without a config field that lies. At 4 Hz it
can.** Use that as the justification, not merely the ruling. See §1 of
`specs/design-patterns.md` — *provider/consumer SSOT with decimation*.

#### 4.2.1 The superseded 5 Hz ruling, preserved

**CIO, 2026-09-20:** *"Nothing needs to run faster than 5 Hz for our current application. If
the battery is only at 1 Hz, that is fine. If the light sensor is only at 1 Hz, that is fine."*

🔴 **4 Hz is a CEILING on every acquisition rate in the system.** It is a practicality derived
from §4.1, not an engineering limit: above it, rows accumulate faster than they can be paired.

### 4.3 How the ceiling and the derivation fit together

🔴 **Two rules, one job each. The ceiling BOUNDS; the derivation CHOOSES.** They do not
compete, and the spec must not be read as carrying two answers:

| | Governs | To exceed / justify |
|---|---|---|
| **The 4 Hz ceiling** | the maximum any rate may take | **CIO-level justification.** Not an architect's call. |
| **The derivation rule** | the actual value, at or below the cap | **a NAMED PHENOMENON**, in writing |

🔴 **RULE — every acquisition rate is declared in writing with the phenomenon that justifies
it, and sits at or below the ceiling. A rate justified by DEVICE CAPABILITY is rejected at
review.**

    rate = enough to resolve the slowest phenomenon we actually analyse,
           capped at 4 Hz
           NEVER "what the part supports"

Two questions stay separate underneath this, and confusing them is what produced 50 Hz:

| | What it is | Set by |
|---|---|---|
| **Correlation grain** | how finely a fact can be tied to vehicle state | **the anchor: 0.43 Hz** |
| **Signal bandwidth** | how fast the phenomenon itself changes | the physics being measured |

- Sampling **faster than the anchor** is legitimate — up to the ceiling — only when a named
  phenomenon occurs *between* ECU samples and we intend to analyse it (braking, cornering,
  grade change). Those samples describe what happened inside one 2.3 s correlation window.
- Sampling faster than the phenomenon requires is **waste by definition**.
- **A rate with no named phenomenon is a defect**, not a preference.

### 4.4 The rates, as ratified

**Measured against the ceiling — the IMU triple is the only thing above it.** Light and the UPS
gauge already comply and do not move.

| Path | Now | vs ceiling | Target | Named phenomenon |
|---|---|---|---:|---|
| ECU / OBD | 0.43 Hz | — | **0.43 Hz** (anchor) | dongle+ECU round trip; not ours to set |
| IMU `sampleHz` | 50 Hz | **12.5× over** | **4 Hz** | braking, cornering, grade change — ~0.5–2 s events; ~10 samples each |
| IMU `persistHz` | 25 Hz | **6.25× over** | **2 Hz** | DB consumer; cannot exceed the root. Factor `_decimationFactor(4,2)=2`, EXACT |
| IMU `stateHz` | 10 Hz | **2.5× over** | **1 Hz** | display consumer; a publish rate above the sample rate carries no new data. Factor `_decimationFactor(4,1)=4`, EXACT |
| Light `sampleHz` | 1 Hz | compliant | **1 Hz** | ambient change for display dimming; slow |
| UPS gauge | 0.2 Hz | compliant | **0.2 Hz** | pack state; slow. ⚠️ see §7 |

🔴 **The ceiling applies to the whole IMU triple, not to `sampleHz` alone.** Ruled 2026-09-21: **`sampleHz 4 / persistHz 2 / stateHz 1`.** A `persistHz` or
`stateHz` left above the root publishes samples that cannot carry new data.

⚠️ **4 Hz is a cap, not a target to aim at.** A rate *below* it needs only its named
phenomenon. A rate *above* it is a CIO decision — it cannot be unlocked by naming a
phenomenon, because the constraint is what can be paired, not what can be resolved.

## 5. The provider contract — how a new sensor is added

Every L2 provider implements:

```python
descriptor() -> ProviderDescriptor
    # fact name, unit, acquisition rate, the NAMED PHENOMENON justifying it,
    # transport, device address. Machine-readable; the rate audit reads this.

read() -> Sample | TypedAbsence
    # one acquisition. NEVER fabricates: a failed or implausible read returns a
    # TYPED ABSENCE with its reason, never a substituted value.

health() -> Health
    # device reachable / degraded / absent. Reported, never acted on here.
```

Plus the ARCH-035 shutdown contract (`readyToShutdown` / `prepareForShutdown` / `abandon`),
because a provider is a Tier-1 capture participant.

**Adding a sensor is then:** write the provider, declare the descriptor with its phenomenon,
register it. **No new orchestration, no new correlation logic, no new decimation code.** If
adding a sensor requires any of those, the abstraction is wrong and that is the review finding.

### Typed absence, not substitution

🔴 **Landing must never MANUFACTURE a reading** (CIO data rule, 2026-08-20, unchanged). A
failed read lands a typed absence and its reason. The project has a live example of why:
`CRATE` (MAX17048 reg 0x16) reads `0xFFFF` and decodes through its signed scale to a
**plausible −0.208 %/hr** — a fabricated discharge that never happened.

## 6. Correlation — what "paired" actually means

§4.1 states the rule. This section defines the **unit of pairing** and owns the mechanics.
L3 owns the join.

### 6.1 The drive window

> Sync and retain drive-coupled data **only inside a drive window**. **The window closes at
> POWEROFF, not at the last ECU row** — a strict reading would delete the key-off and UPS
> evidence. **Lead-in covers `bootGrace`** so engine crank is captured. Wall-power data is
> development-only. *(CIO, 2026-09-19.)*

### 6.2 Implementation, and the one defect in it

**Implemented by `src/pi/bus/edr_log_gate.py` (US-767), shipped V0.29.58 — collapses EDR
volume ~29×.** ⚠️ Its predicate currently reads `ConnectionStatus.connected` — the **Bluetooth
link**, not ECU reachability. The dongle has constant power and is lit at key-out, so a link
can exist in a parked car and reach no ECU. **US-793 moves the predicate to ECU reachability**;
see that story for the fail-open trap ("unreachable" must be a readable `False`, distinct
from "signal unreadable").

🟢 **The gate itself is the right mechanism. Only its predicate is wrong.**

**Rate reduction and gating are independent and compose.** 4 Hz cuts rows ~12.5×; the log gate
cuts ~29×. Neither substitutes for the other.

### 6.3 🔴 PAIR TO THE DRIVE, NOT TO THE ROW

Two CIO rulings meet here, and a literal reading of either one destroys something:

| | Ruling |
|---|---|
| **2026-09-20** | *"we should not be capturing rows that do not line up with ECU data"* |
| **2026-09-19** | the drive window *"closes at POWEROFF, not at the last ECU row"* — ruled explicitly when Atlas raised that a strict reading would delete the key-off/UPS evidence |

🔴 **At key-off the ECU is silent BY DEFINITION.** A literal row-level pairing rule would
therefore delete **exactly the shutdown evidence currently under investigation** — the
`power_loss_heartbeat` rows, the drain events, the UPS telemetry that every open power question
depends on.

🔴 **RESOLUTION — the unit of pairing is the DRIVE WINDOW, not the individual ECU row.**

    drive window  =  bootGrace lead-in  ->  POWEROFF

- **Inside the window**, a row is product data **even when the ECU is momentarily silent**.
  Engine crank, a dropped link mid-drive, and the entire key-off tail all stay.
- **Outside the window**, there is no drive to pair to, and the row is development-only (§6.4).

**The single test is therefore: is there a drive window around this row?** Not: is there an ECU
row beside it.

⚠️ **Do not "simplify" this to row-level pairing.** It reads tighter and it deletes the tail of
every drive.

### 6.4 The bench / development case

**Pi powered, no ECU, no drive window ⇒ development data.**

This is **not a defect and not a failure** — it is the normal state of a bench. But it is also
**not product data**: it is never retained as such, and it must be **typed at CAPTURE**, not
sorted out afterwards by inference.

🟢 **The mechanism already exists** — `data_source` (`real` / `replay` / `physics_sim` /
`fixture` / `foreign`) and `load_class` (`production` / `test` / `sim`). **This is labelling
discipline, not new machinery.**

⚠️ **Typing after the fact does not work**, and the project has measured why: two entire days
(09-17, 09-18) were **100% orphaned** — ~1.7M rows each day — and were only distinguishable
from product data by reconstructing, later, that the car had never moved.

**Rules out:** inferring development data from row counts or timestamps after capture; and
treating an empty ECU stream on a bench as an error condition.

## 7. ⚠️ One open risk this design touches

**`/dev/i2c-1` carries the IMU (0x69), the magnetometer (0x0C), the light sensor (0x29) and
the MAX17048 fuel gauge (0x36) — the UPS's own instrument.**

Our I²C handling is **measured to wedge devices on that bus**: ARCH-032, n=20 per arm, Fisher
p=0.000017 — a pure *read* of the gyro collapses the AK09916 bypass hand-over from ~70% to
~10%, leaving the magnetometer refusing its own address.

⚠️ Reducing IMU acquisition from 50 Hz to 4 Hz cuts traffic on that bus ~12.5×. **That is a
justified change on its own merits and must NOT be presented as a fix for anything else.**
The sub-second shutdown deaths remain unexplained (see `facts/power-and-battery.md` for the
ten candidates already ruled out). If rate reduction changes that behaviour, it is a
**finding to investigate**, not a fix to claim.

## 8. Gates — enforceable at review

1. 🔴 **No rate exceeds the 4 Hz ceiling without CIO-level justification.** A named phenomenon
   does not unlock it — the constraint is what can be paired, not what can be resolved.
2. **Every provider declares a rate and the phenomenon justifying it.** No phenomenon, no merge.
3. **No consumer acquires.** A consumer calling a device, or a second provider for the same
   fact, is rejected.
4. **Only L3 joins across transports.**
5. **No rate is justified by device capability.**
6. 🔴 **Pairing is assessed against the DRIVE WINDOW, never against an individual ECU row.**
   A row-level pairing test is rejected at review: it deletes the key-off tail.
7. **Data captured with no drive window is TYPED as development at capture**, not inferred
   afterwards.
8. **A failed read lands a typed absence**, never a substituted or defaulted value.
9. **A new sensor requires no change to orchestration, correlation or decimation.** If it
   does, the abstraction is wrong.
10. **Rates are reviewed against the anchor when the anchor changes.** A faster dongle or ECU
    profile moves the correlation grain and every derived rate with it.

## 9. Open items

| Item | Owner | Blocks |
|---|---|---|
| Confirm 4 Hz against a real drive — do braking/cornering events resolve? | Atlas | the constant only, not the design |
| Is the 0.43 Hz anchor a dongle limit, an ECU limit, or our polling? Worth knowing — it may be raisable | Atlas | nothing; informational |

🟢 **CLOSED 2026-09-21:** ~~`persistHz` / `stateHz` re-derived beneath a 4 Hz root~~ — ruled `4 / 2 / 1` — answered
by the ceiling (§4.2), which applies to the whole triple rather than to the root alone. Kept
here, struck, rather than deleted, so it is not re-opened as an unanswered question.

## 10. Out of scope

- The unexplained sub-second shutdown deaths (§7).
- Sync protocol, server-side storage, retention — **owned by
  `specs/storage-retention-custody.md` (ARCH-037)**. ⚠️ Out of scope *of this document* only:
  per §1, capture and trustworthy sync are the current product goal, so ARCH-037 is not
  lower-priority work — it is the other half of the same deliverable.
- The ARCH-035 shutdown orchestration itself.
- Any change to `PowerSourceProvider`, which is already a correct SSOT provider.
- GPS. It fits this model as an L2 provider when it lands; no design change expected.


---

## 11. Recorded dissent on the ruled triple (Atlas, 2026-09-21)

The CIO ruled **`sampleHz 4 / persistHz 2 / stateHz 1`** and that ruling stands. **One
objection was raised once and decided against; it is recorded so nobody reopens it blind.**

⚠️ **Sampling at 4 Hz while storing at 2 Hz DISCARDS HALF THE ACQUIRED DATA.** Against the
standing purpose — *"land all variables unless there is a good reason not to"*, for correlation
analysis — the dropped samples cost power and yield nothing. Either `sampleHz` should be 2, or
`persistHz` should be 4. **Sampling faster than you store is the "device capability, not
analysis need" shape §4.3 rejects at review**, so the config and this section disagree on that
one point until one of them moves.

🔴 **Decided by the CIO. Do not re-litigate.** `stateHz 1` is a UX call and is his.
**This is the open thread if rate policy is ever reopened.**
