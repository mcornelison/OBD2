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
proposes, which is corroboration that 5 Hz is sufficient for the display path.

---

## 1. Why this exists

The project acquires data over two independent paths — **Bluetooth → OBD dongle → ECU**, and
the **I²C bus** — at rates chosen from what each device is *capable* of rather than from what
the analysis *needs*. The cost is measured, not theoretical:

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

**The existing IMU chain is already the correct shape and should be the template:**

    sampleHz 50  ->  persistHz 25  ->  stateHz 10
    one acquisition   DB consumer     display consumer

One acquisition, two decimations, consumers applying policy. **Only the root number is
wrong.** `_decimationFactor` is `max(1, round(sampleHz / persistHz))`, so a consumer rate at
or above the acquisition rate degrades safely to "keep every sample" — **lowering `sampleHz`
alone is safe and requires no code change.**

## 4. How a rate is derived — the rule that makes "50 Hz because it can" impossible

Two different questions get confused, and separating them is the whole design:

| | What it is | Set by |
|---|---|---|
| **Correlation grain** | how finely a fact can be tied to vehicle state | **the anchor: 0.43 Hz** |
| **Signal bandwidth** | how fast the phenomenon itself changes | the physics being measured |

🔴 **RULE — every acquisition rate is derived, in writing, from a NAMED PHENOMENON, and is
justified against the anchor. A rate justified by device capability is rejected at review.**

    rate = enough to resolve the slowest phenomenon we actually analyse
           NEVER "what the part supports"

**Consequences:**

- Sampling **faster than the anchor** is legitimate only when a named phenomenon occurs
  *between* ECU samples and we analyse it (braking, cornering, grade change). The extra
  samples then describe what happened inside one 2.3 s correlation window.
- Sampling faster than the phenomenon requires is **waste by definition**, and this project
  has measured what that waste costs: 96.6% orphan rate and a 2.8 GB database.
- **A rate with no named phenomenon is a defect**, not a preference.

### The rates, as ratified

**CIO, 2026-09-20:** *"this is a device that's going to be polling during normal driving
operations, so anything more frequent than four or five times a second isn't very
meaningful."*

| Path | Now | Target | Named phenomenon |
|---|---|---:|---|
| ECU / OBD | 0.43 Hz | **0.43 Hz** (anchor) | dongle+ECU round trip; not ours to set |
| IMU | 50 Hz | **5 Hz** | braking, cornering, grade change — ~0.5–2 s events; ~10 samples each |
| Light | 1 Hz | **1 Hz** | ambient change for display dimming; slow |
| UPS gauge | 0.2 Hz | **0.2 Hz** | pack state; slow. ⚠️ see §7 |

⚠️ **5 Hz is a starting point derived from a stated phenomenon, not a proven optimum.** If an
analysis later needs finer resolution it may be raised — **by naming the phenomenon that
requires it**, and recording the change here.

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

## 6. Correlation — the coupling rule

🔴 **I²C facts are only meaningful tied to ECU facts** (CIO, 2026-09-20). L3 owns that join,
and the existing ruling governs the window:

> Sync and retain drive-coupled data **only inside a drive window**. **The window closes at
> POWEROFF, not at the last ECU row** — a strict reading would delete the key-off and UPS
> evidence. **Lead-in covers `bootGrace`** so engine crank is captured. Wall-power data is
> development-only. *(CIO, 2026-09-19.)*

**Implemented by `src/pi/bus/edr_log_gate.py` (US-767), shipped V0.29.58 — collapses EDR
volume ~29×.** ⚠️ Its predicate currently reads `ConnectionStatus.connected` — the **Bluetooth
link**, not ECU reachability. The dongle has constant power and is lit at key-out, so a link
can exist in a parked car and reach no ECU. **US-793 moves the predicate to ECU reachability**;
see that story for the fail-open trap ("unreachable" must be a readable `False`, distinct
from "signal unreadable").

**Rate reduction and gating are independent and compose.** 5 Hz cuts rows ~10×; the log gate
cuts ~29×. Neither substitutes for the other.

## 7. ⚠️ One open risk this design touches

**`/dev/i2c-1` carries the IMU (0x69), the magnetometer (0x0C), the light sensor (0x29) and
the MAX17048 fuel gauge (0x36) — the UPS's own instrument.**

Our I²C handling is **measured to wedge devices on that bus**: ARCH-032, n=20 per arm, Fisher
p=0.000017 — a pure *read* of the gyro collapses the AK09916 bypass hand-over from ~70% to
~10%, leaving the magnetometer refusing its own address.

⚠️ Reducing IMU acquisition from 50 Hz to 5 Hz cuts traffic on that bus ~10×. **That is a
justified change on its own merits and must NOT be presented as a fix for anything else.**
The sub-second shutdown deaths remain unexplained (see `facts/power-and-battery.md` for the
ten candidates already ruled out). If rate reduction changes that behaviour, it is a
**finding to investigate**, not a fix to claim.

## 8. Gates — enforceable at review

1. **Every provider declares a rate and the phenomenon justifying it.** No phenomenon, no merge.
2. **No consumer acquires.** A consumer calling a device, or a second provider for the same
   fact, is rejected.
3. **Only L3 joins across transports.**
4. **No rate is justified by device capability.**
5. **A failed read lands a typed absence**, never a substituted or defaulted value.
6. **A new sensor requires no change to orchestration, correlation or decimation.** If it
   does, the abstraction is wrong.
7. **Rates are reviewed against the anchor when the anchor changes.** A faster dongle or ECU
   profile moves the correlation grain and every derived rate with it.

## 9. Open items

| Item | Owner | Blocks |
|---|---|---|
| Confirm 5 Hz against a real drive — do braking/cornering events resolve? | Atlas | the constant only, not the design |
| `persistHz` / `stateHz` re-derived beneath a 5 Hz root | Atlas | the build |
| Is the 0.43 Hz anchor a dongle limit, an ECU limit, or our polling? Worth knowing — it may be raisable | Atlas | nothing; informational |

## 10. Out of scope

- The unexplained sub-second shutdown deaths (§7).
- Sync protocol, server-side storage, retention.
- The ARCH-035 shutdown orchestration itself.
- Any change to `PowerSourceProvider`, which is already a correct SSOT provider.
- GPS. It fits this model as an L2 provider when it lands; no design change expected.
