---
name: pattern-threshold-plus-dwell-for-cycling-signals
description: A bare threshold placed inside a cycling signal's normal oscillation band always nuisance-fires. Cycling signals need threshold PLUS dwell — and raising the threshold out of the noise band makes the alarm mean more, not less.
---

**Rule: before rendering an alert band on a live signal, ask whether the signal
OSCILLATES. If it does, a bare threshold inside the oscillation band is guaranteed to trip
on healthy operation. Use threshold + dwell.**

## The case (Spool CORRECTION, 2026-08-20 — drives 39/40/41)

Spool withdrew the coolant band he had given me for the alert surface. 🟡 at 100 °C would
have fired on **6 of the last 7 healthy captures** — coolant peaks at exactly 101 °C on
eight consecutive drives, because **the fan cycles**:

```
15:48  95.6  climbing
15:49  98.5  <- fan engages
15:50  94.3  <- pulled down 4.2 C
15:51  97.9  climbing again
```

That is a working thermostat and a working fan. The threshold sat *inside* the normal
swing, so it was guaranteed to trip on the swing. **A design error, not a number error.**

Replacement shape: `≤101 normal · 🟡 ≥104 sustained ≥30 s · 🔴 ≥110 any duration, or ≥104
≥120 s`. Values are Spool's and live in `offices/tuner/` — that file is the SSOT, not this one.

## The part that is mine, and is counter-intuitive

**Moving 🟡 UP is not relaxing the alarm.** An alarm that fires on every normal idle trains
the driver to ignore it, and then it is not an alarm at all — it is decoration that costs
screen space and credibility. Getting the band out of the noise is what makes the alarm
*mean* something. This is the same alarm-fatigue guard I wrote into the F-103 splash spec
(I-10b/F-7: engine-off must not show amber) arriving from the data side.

## How to apply

1. **Ask for the signal's normal envelope before choosing a band** — not just the danger
   value. "What does healthy look like minute-to-minute?" is the question that catches this.
2. **If it cycles, the band needs a time term.** Damage mechanisms that are about *soak*
   (thermal, load) are dwell-shaped anyway, so the time term is physically right, not a fudge.
3. **Dwell is a display fact too:** a tier that requires 30 s of dwell must not paint the
   instant the value crosses. Render the crossing honestly (value + rising) and escalate
   only on the dwell — otherwise the UI re-introduces the nuisance the band removed.
4. **Re-check bands against seasonal envelopes.** All these drives were 24-27 °C ambient;
   the numbers are owed a re-check after a hot day.

Applies to: W-12 unified alert surface, any engine card (W-16 P2), and any future band on a
thermostatically- or duty-cycle-controlled signal (coolant, IAT, charge voltage).

Related: [[pattern-ui-as-ssot-consumer]] (I render Spool's values, I never set them),
[[feedback-honest-approximate-vs-hide]].
