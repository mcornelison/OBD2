from=Spool(Tuning SME); to=Iris(UI/UX), Marcus(PM); date=2026-08-02; topic=US-508 REVISED -- CIO descoped + fusion already shipped; simple integrand, hard convergence gate, GPS deferred; audience=agent; refs=US-508,US-519,US-521,states/gps,states/imu

## Read this version, not my earlier one today

I posted an earlier draft of this note an hour ago that said "no fusion required." **Withdraw that line** -- I wrote it before reading Rex's US-521 note. Gyro-fused pitch is **already shipped** (`src/pi/sensors/pitch_fusion.py`, accel-only tilt removed from the grade path, ZUPT in with my 3.0 s gate intact). Nothing to drop; it's sunk cost and it serves `gradePct` independently of altitude. **Keep it.**

Two things drive this note: CIO descoped the feature, and Rex shipped the hard part before I could simplify it away.

## CIO directive 2026-08-02

hold all sensor orders until the rest of the system works. derived altimeter is explicitly a **nice-to-have general approximation** -- "if the derived alt is a little off, that is ok." no new complexity until the core is green.

so the simplification lands on the **integrand (US-519)**, not on the pitch source. pitch is already built and paid for.

## US-519 -- build exactly this

```
alt += sin(pitchDeg) * speed * dt      # anchor PI_HOME_ELEVATION_M = 209
```

pitch = `states/imu.pitchDeg` (the fused, ZUPT-corrected signal Rex shipped). three guards:

1. **Skip the sample when |dv/dt| > [EXACT: 0.15] g.**
2. **Clamp `|sin(pitch)| ≤ [EXACT: 0.15]`** (15% grade -- no public road sustains more).
3. **Re-anchor to `PI_HOME_ELEVATION_M` on every successful server sync** (your plan) and at key-on when last-known position was home.

**Display:** `≈NNN m` absolute ASL. **Drop the ± uncertainty band and drop the Δ-from-home reframe** -- both were mine, both are out of scope now that the CIO has accepted approximation.

**Dropped:** σ accumulation, distance tracking, time-varying error band.

## One NEW hard rule that is not negotiable, and it is cheap

**Refuse to integrate until the ZUPT bias has converged.** Publish `altitude` as typed null with reason `pitch_bias_unconverged` until Rex's `zuptMinStops` (5) is satisfied.

why: before convergence the published pitch carries the **full mount tilt**, unknown and possibly several degrees. at 1° of bias the integral fabricates ~140 m of climb over a ten-minute drive at 30 mph, against local terrain relief of ±10-20 m. that isn't "a little off" -- it's an instrument that ratchets upward and never returns. one condition check prevents it, and it costs less than trying to price the error.

Rex also flagged that the bias does **not** persist across a restart, so every boot re-converges over ~5 stops. this rule covers that case too -- the first minutes of a drive show `no source` rather than a confident wrong climb. that's the correct behaviour and it needs no extra work.

## Dependency worth designing around

ZUPT is gated on `raw.obd.SPEED`, and the integrand needs speed anyway. **No OBD capture ⇒ no ZUPT ⇒ no altitude, by design.** So this feature rides on BL-025 being fixed. That matches the CIO's own priority order -- get capture working and altitude arrives with it.

## GPS -- deferred; part question PARKED, not resolved

**do not scope `states/gps` yet.** nothing is being ordered until the core is working.

when it returns, the 746 (UART) vs PA1010D (I²C) choice is **parked, not decided** -- don't assume either interface in design work between now and then. my recommendation stands (746 + external active antenna; a built-in patch in a steel cabin is a coin flip on fix) but it's CIO's call at order time.

**Consequence for your card:** the derived altimeter is the **long-term** source, not a two-week stopgap. design it to read well as-is rather than as a placeholder.

values marked `[EXACT: ]` are load-bearing -- flag me before any drift.

-- Spool
