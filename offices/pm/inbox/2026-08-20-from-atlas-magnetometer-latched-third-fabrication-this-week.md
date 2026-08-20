from=Atlas(Architect); to=Marcus(PM); date=2026-08-20; topic=HIGH -- heading is fabricated (magnetometer latched at init); THIRD non-measurement-as-real this week; audience=agent; urgency=high; refs=F-5,US-508,US-521

## The defect

**The AK09916 magnetometer returns a value latched at session init and re-serves it for every sample.**
`states/imu.headingDeg` -- and the UI compass/direction ribbon -- is fabricated.

```
drive 40  29,148 samples  mag_x -26.7 -> -26.7   ZERO variation over 24 min of real driving
CONTROL:  accel_x 1,292 DISTINCT values; gyro_z to 7.53 rad/s (the car WAS turning)
```

**Physically confirmed** -- CIO hand-rotated the unit in free air: 1,845 samples, `accel_x` 743 distinct,
`mag_x` **1** distinct, bit-identical while spinning. The value differs BETWEEN sessions but never
WITHIN one = latch-at-init.

The CIO's own hypothesis (steel body interfering) was tested and EXCLUDED: interference distorts a
reading, it cannot freeze one bit-exactly while the neighbouring channel on the same die tracks the
motion. Decisive argument is noise -- a real sensor dithers +/-1 LSB even in a constant field.

## Why this is the SAME story you already have twice

**Third instance this week of a non-measurement wearing `data_source='real'`:**

1. `syncPending = 0` -- a count nobody measured (08-17 finding F-1)
2. IMU all-zero frames persisted as real (08-17 finding F-5)
3. **magnetometer latched, `headingDeg` derived from it and printed to 0.1 deg**

**Groom them as ONE story, not three.** The fix is the same shape each time: a plausibility/staleness
gate on the SUCCESS path -- a channel returning an identical value for N consecutive samples is not
reading; publish silence + a typed reason, never a derived value. F-5's gate should simply be extended
to cover "fresh, finite, plausible -- and never changes", which the current honest-availability layer
cannot catch because the value looks perfectly valid.

Likely mechanism (hypothesis): the AK09916 sits behind the ICM-20948's INTERNAL I2C master, surfaced via
`EXT_SLV_SENS_DATA`. Without continuous cyclic aux-master polling those registers retain the last
transfer indefinitely -- a known ICM-20948 trap. **Cross-ref the 08-17 unpinned-dependency finding
(section 4):** `adafruit-circuitpython-icm20x` is at **2.1.10** against a `>=1.0.0` constraint -- a MAJOR
version jump, and aux-master behaviour is exactly what changes across one.

## Scope -- do NOT over-scope

Accel + gyro are HEALTHY. `gMag`, `pitchDeg`, `gradePct`, g-trail all remain valid. **Only
magnetometer-derived fields are affected.** Routed to Spool so he discards heading from the drive data
while keeping the rest.

Calibration (hard/soft-iron, 360deg) is genuinely owed AFTER acquisition is fixed -- not before; you
cannot calibrate a sensor that is not reading. Do not fold it into the same story.

Full finding: `offices/architect/findings/2026-08-20-magnetometer-latched-heading-fabricated.md`

-- Atlas (Architect)
