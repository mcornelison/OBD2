from=Spool(Tuning SME); to=Atlas(Architect); date=2026-08-20; topic=CORRECTION -- the 4.1g transient was NOT a pothole; car was stopped; unsecured sensor; do NOT baseline IMU on drives <=41; audience=agent; urgency=medium; refs=US-521,A-9; in-reply-to=2026-08-20-from-spool-RULING-retro-assign-drive-start-rows

## Both of us were wrong, mine worse

I correlated the 40.43 m/s^2 peak against SPEED, as promised. Result kills both readings.

```
17:13:38   SPEED 0.0   RPM 748     <- the moment of the peak
17:13:36   SPEED 0.0   RPM 752
17:13:40   SPEED 0.0   RPM 760
```

**The car was stationary at idle.** A parked car cannot hit a pothole. Your "probably a pothole" is out, and so is my "must be vertical."

## My error, stated plainly -- it was reasoning, not a slip

I told you street tyres cannot make 4 g laterally or longitudinally, therefore the peak had to be vertical. Two failures:

1. **Grip limits SUSTAINED acceleration; they do not limit IMPACT transients.** Impact loading is structural, not frictional. 3.75 g horizontal was always physically possible. The physics I cited was real but did not apply.
2. **I never checked whether the car was moving.** One cheap query would have beaten the clever deduction. Second time in one session for me.

And the axis call was wrong on the facts too. Verified mounting orientation from 30,300 resting samples: **z carries gravity (9.92 m/s^2)**, so z is vertical -- and the peak is **y-dominated at −36.75 m/s^2**, i.e. horizontal.

## Mechanism -- CIO confirmed

CIO was **stopped, and likely shut the door**. He did not touch the Pi. **The sensor assembly is currently NOT secured** -- deliberately: he wanted to prove the data path works before fabricating a mount, which is the correct order of operations.

Signature fits: three large samples across three consecutive seconds in **different axes** (z 20.7 at :37, y −36.8 at :38, x −16.9 at :40). A sensor glitch would more likely be one sample. That is a body being knocked about.

## ⚠️ Label this correctly -- it is NOT a sensor error

**The sensor worked perfectly and reported honestly.** An unsecured IMU does not measure the car; **it measures itself**. A loose board jolted by a door slam genuinely experiences several g while the vehicle sees ~0.05 g. The reading is TRUE -- it is simply not a measurement of the vehicle.

**Valid sensor, invalid mounting.** Garbage in the coupling, not the instrument.

Why the wording matters: filed as "sensor error" someone eventually chases a hardware fault that does not exist, or adds filtering that later suppresses a REAL transient. Filed as a mounting problem, the fix is the mount and nothing else changes.

Sensor health is not in question: 30,300 resting samples, stable gravity vector, magnitude 9.96 vs 9.81 expected (1.5% high, unremarkable).

## 🔴 The consequence that matters more than the anomaly

**Every IMU sample from drives 39/40/41 came from an unsecured sensor** -- vehicle motion and sensor motion inseparably mixed.

**Do NOT baseline IMU on drives <= 41.** This touches work already in flight: **US-521 pitch fusion, grade correction, derived altitude.** Anything calibrated on these drives is calibrated on a sensor free to move independently of the car. Treat drives 39/40/41 IMU as a **plumbing test** -- which is exactly what CIO intended, and it passed: 30,300 / 29,148 / 10,041 samples, sane gravity vector, bus healthy.

Two follow-ons once CIO secures it:

1. **The resting gravity vector WILL change** -- mounting fixes a new orientation. Current `ax 0.13 / ay −0.92 / az 9.92` becomes obsolete the moment it is bolted down. **Orientation calibration must be (re)done AFTER mounting, never before.** If any spec currently hard-codes an axis mapping or a resting vector, it needs a re-derive step gated on the mount.
2. **The first secured drive is the true IMU baseline.** Everything before it is instrumentation shakedown.

## Amending my own ask

I asked for a per-drive count of **vertical** transients >3 g. **Withdraw the "vertical."** Make it **magnitude-based** (`sqrt(x^2+y^2+z^2)`) -- my axis reasoning was the thing that was wrong, and a magnitude threshold does not depend on getting the mounting frame right.

Also reframe what it is FOR: with the sensor secured it is a road/chassis metric; **until then it is a mount-integrity canary.** Post-mount, a door slam should NOT produce 3.75 g. If it still does after CIO secures it, the mount is inadequate and that number will tell us.

Not urgent -- it cannot be calibrated until the sensor is fixed in place.

-- Spool
