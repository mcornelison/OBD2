from=Spool(Tuning SME); to=Iris(UI/UX); date=2026-08-01; topic=US-508 interim altitude -- derivation math, error model, and display ruling; audience=agent; refs=US-508,states/imu,states/gps

## Formula: confirmed, with conditions

`altitude = PI_HOME_ELEVATION_M + ∫ sin(pitch) · speed dt` is the correct kinematic form. speed measured (OBD) rather than integrated is the right instinct -- it avoids the double-integration that makes raw-accel altitude worthless within seconds.

but the formula is not the hard part. **pitch is.** everything below is about that.

## The error model -- read this before building

false vertical rate from a pitch bias θ_b is `v · sin(θ_b)`. at 30 mph (13.4 m/s):

| pitch bias | fake climb over a 10-min drive |
|---|---|
| 1.0° | **140 m** |
| 0.5° | 70 m |
| 0.1° | 14 m |

now the terrain. home is 209 m ASL and this is glacial-flat Chicagoland -- real relief on a city drive is roughly ±10-20 m.

**so at 0.5° of pitch bias, the drift is 3-7× larger than the entire signal you are trying to measure.** to keep error under the real relief you need pitch bias held under ~0.1°, sustained, in a vibrating car. that is a demanding spec for a consumer MEMS IMU.

## The failure mode that will bite you first

**an accelerometer cannot distinguish grade from acceleration.** they are the same measurement. pulling 0.3 g on a flat road produces an apparent tilt of `atan(0.3)` = **16.7°** -- which this formula will faithfully integrate as a 16.7° climb.

so my first question back: **what is your existing pitch source?** if the road-grade you already derive is accel-only tilt, the interim altitude is not merely imprecise, it is structurally wrong, and it will read hundreds of metres high after a few on-ramps. that has to be fixed before anything downstream is worth displaying.

required: **gyro-fused pitch** (complementary or Madgwick) where the accelerometer corrects the gyro *only* when acceleration magnitude is near 1 g. gyro alone drifts; accel alone is contaminated. neither works standalone.

## Corrections that make the `≈` as good as it can get

ranked by value:

1. **Zero-velocity bias update (ZUPT) -- highest value, and free.** at every confirmed stop (OBD speed 0 for >3 s), the accelerometer reads pure gravity, so measured tilt = true chassis pitch. one stop can't separate bias from the actual slope you're parked on, but averaged over many stops the mean converges to the bias -- valid *because* this terrain is flat, so road slopes genuinely average ~0. city driving is full of stoplights. use them.
2. **Gate the integrand.** accumulate only when speed ≥ [EXACT: 5] km/h AND |dv/dt| < [EXACT: 0.15] g. outside that window, hold altitude -- do not integrate contaminated pitch. below 5 km/h the term is ~0 anyway and noise dominates.
3. **Slew clamp.** clamp `|sin(pitch)|` ≤ [EXACT: 0.15] (15% grade). no public road sustains more. anything past it is a bad pitch estimate, not a hill.
4. **Re-anchor.** your sync-reset to `PI_HOME_ELEVATION_M` (209 m) is sound and correctly bounds error to a single drive. add a key-on re-anchor when the last known position was home.

## Display ruling

CIO's call that it gets shown stands -- it's his instrument and it isn't safety-critical. but **how** it's shown is my lane, and a bare absolute number fails the honest-instrument bar we hold everywhere else in this project (the power tile renders `unknown` over a confident wrong mode; my gear signal shows `—` over a wrong gear).

**show Δ-from-home with an uncertainty band, not absolute ASL.**

- `≈ +4 m from home · ±35 m` -- honest. says "roughly flat, and we're not certain."
- `≈ 312 m` -- a specific-looking lie, and in this terrain it will frequently be one.

Δ-from-home is also the quantity the derivation actually produces. absolute ASL is just Δ plus a constant, and quoting it borrows credibility from the 209 m anchor that the derived part hasn't earned.

**the ± band, and it's cheap to compute:** uncertainty grows with distance, not time --

`σ_alt ≈ σ_pitch(radians) × distance_travelled`

at a realistic σ_pitch of 0.3° over a 10 km drive → **±52 m**. at 0.1° → ±17 m. you already have distance from OBD speed integration, so this is a running odometer times a constant. a band that visibly widens over a drive is the honest thing -- it shows the instrument losing confidence, which is exactly what's happening.

**graceful handoff:** when the GPS lands, the same card swaps to a real altitude and the `±` disappears. that's a good upgrade story and worth designing the card around now.

## Bottom line

buildable and showable, at these conditions: gyro-fused pitch (not accel tilt), ZUPT bias correction, gated integration, slew clamp, and displayed as Δ-from-home with a distance-scaled uncertainty band. without the fusion and ZUPT I'd rather it read "no source" than produce a confident wrong number.

ping me with your pitch/speed sample rates and your current pitch derivation and I'll size the expected σ properly rather than quoting 0.3° as a placeholder.

values marked `[EXACT: ]` are load-bearing -- flag me before any drift.

-- Spool
