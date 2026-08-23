# TD-085 — The TSL2591's dither has never been measured, so US-564's gate cannot enrol it

**Filed by:** Rex (Ralph) during US-564
**Date:** 2026-08-21
**Severity:** Low (a coverage gap that is currently the CORRECT state, not a defect)
**Type:** Missing measurement — blocks a deliberate scope decision

## What

US-564's invariance check refuses a channel that returns **N consecutive bit-identical
samples**. It is enrolled per channel, by explicit declaration:

- `ImuReader.channelPolicies` — `raw.imu.accel`, `raw.imu.gyro`, `raw.imu.mag` all enrolled.
- `LightReader.channelPolicies` — **deliberately empty.**

## Why the light channel is NOT enrolled

The whole reason bit-identity beats `variance < threshold` is a **measurement**: on
2026-08-20 a stationary vehicle's accelerometer produced 743 distinct values in 90 s
while the magnetometer produced 1. That measurement was taken on the ICM-20948. It says
nothing about the TSL2591.

And the TSL2591 has a physical reason it might legitimately be invariant: it counts
photons. In real darkness `visible` / `infrared` / `full_spectrum` can all sit at a
bit-exact 0 indefinitely — a **correct** reading from a **working** sensor. Enrolling
that channel on the assumption that "all sensors dither" would gate a healthy sensor
every night, which is precisely the unmeasured-assumption failure US-564 exists to
delete. Substituting one plausible-sounding hardware belief for another is how the
fabricated `PANEL_MODES` fixture (US-560/BL-034) and the latched magnetometer both got
past review.

So: **not enrolling it is the honest state today**, and it is pinned by test
(`TestLightReaderIsDeliberatelyUnenrolled`) — behaviourally *and* structurally, so
nobody enrols it later without meaning to.

## What is actually owed

One cheap capture, then a one-line decision:

1. With the light sensor connected, capture `edr_light_sample` across a genuinely dark
   period (garage, doors shut, night) **and** a normal daylight period.
2. Count distinct values per channel per minute in each condition.
3. If the raw counts dither even in darkness → enrol
   `raw.light.raw` with `ChannelPolicy(invariance=True)`, one line in
   `LightReader.channelPolicies`, and the gate covers the light sensor too.
4. If they sit bit-exact at 0 in darkness → record that as the reason it stays
   unenrolled, and consider whether a *daylight-only* enrolment is meaningful (probably
   not — a gate that only works in conditions where the fault is least likely is not
   worth the false-positive risk).

`raw.light.lux` is a derived float and should be judged on whatever the raw counts do —
it cannot dither if its inputs do not.

## Note on the IMU temp channel

`raw.imu.temp` is unenrolled for the same reason plus two more: it is coarse and
slowly-varying by nature, and it feeds no displayed or derived field (it is already
best-effort honest-null since US-500). It is a lower priority than the light channel.

## Related

- US-564 (the gate itself), US-565 (magnetometer acquisition)
- `specs/ssot-design-pattern.md` — the variance-detection rule (bit-identity, not low variance)
- BL-034 / US-560 — the fabricated-hardware-fixture precedent this note is guarding against
