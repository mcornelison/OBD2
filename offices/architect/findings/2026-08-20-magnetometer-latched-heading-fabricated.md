# Finding — The magnetometer is LATCHED: `headingDeg` is a fabricated reading (physically confirmed)

**Author:** Atlas (Architect)
**Date:** 2026-08-20
**Reported by:** CIO — *"I did not see the direction ribbon and heading information change... but that
might have been because of the screen freeze, but not 100% sure."*
**Severity:** **HIGH** — a confident, precise-looking value with zero information behind it.
**Class:** same as F-5 (`2026-08-17-ui-ssot-audit-five-unbacked-facts.md`) — a non-measurement persisted
and displayed as `data_source='real'`.

---

## 1. Verdict

**The AK09916 magnetometer inside the ICM-20948 returns a value latched at session init and re-serves it
for every subsequent sample.** Accelerometer and gyroscope are unaffected and working correctly.
`states/imu.headingDeg` — and therefore the UI compass/direction ribbon — is **fabricated**.

## 2. Evidence from the 2026-08-20 two-leg drive

```
drive 39   30,300 samples   mag_x  -29.5 -> -29.5    mag_y  -0.1  -> -0.1
drive 40   29,148 samples   mag_x  -26.7 -> -26.7    mag_y -28.3  -> -28.3
drive 41   10,041 samples   mag_x  -30.4 -> -30.4    mag_y  -0.1  -> -0.1
```

Zero variation across 24 minutes of real driving. The CONTROL, same rows, same drives:

```
drive 40   accel_x -16.93 .. 12.83   1,292 DISTINCT   gyro_z -3.92 .. 7.53 rad/s   mag_x: 1 DISTINCT
drive 41   accel_x  -4.11 ..  3.80   1,229 DISTINCT   gyro_z -0.34 .. 0.41 rad/s   mag_x: 1 DISTINCT
```

`gyro_z` up to **7.5 rad/s** proves the vehicle was genuinely turning. A working compass MUST have moved.

**Note the value differs BETWEEN drives but never WITHIN one** — the signature of latch-at-init, not of a
constant environment.

## 3. PHYSICAL CONFIRMATION — the CIO's magnetic-interference hypothesis, tested and excluded

The CIO asked a good question: the unit sits on the passenger floor, so could the **steel body** be
interfering? Hard-iron and soft-iron distortion are real and DO affect vehicle magnetometers.

**But interference distorts a reading; it cannot freeze one.** Tested directly — CIO manually rotated
the device through free air inside the car while the reader ran:

```
last 90 s, 1,845 samples:   accel_x DISTINCT = 743      <- tracking his rotation
                            mag_x   DISTINCT = 1
                            mag_y   DISTINCT = 1
   19:30:34  mag  -7.95  -12.30  -0.15
   19:30:34  mag  -7.95  -12.30  -0.15   (identical while physically spinning)
```

**Conclusive.** No magnetic environment can freeze one channel bit-exactly while its neighbour ON THE
SAME DIE responds normally to the identical physical motion.

**The decisive argument is noise:** every real sensor dithers ±1 LSB from thermal noise and ADC
quantization even in a perfectly constant field. Thousands of consecutive BIT-EXACT readings are not a
quiet measurement — they are a cached value being re-served. Even full mu-metal shielding would give a
near-ZERO field WITH noise, not a frozen non-zero constant.

**Car exonerated. The fault is in the data path.**

## 4. Likely mechanism (hypothesis, not verified)

The AK09916 is **not on the main I²C bus**. It is a slave behind the ICM-20948's **internal I²C master**,
surfaced through the `EXT_SLV_SENS_DATA` registers. If the aux master is not configured for continuous
cyclic polling, those registers **retain the last successful transfer indefinitely** — every subsequent
host read returns the same latched bytes, indistinguishable from a live read. This is a well-known
ICM-20948 trap.

Consistent with observation: value latches at init, differs per session, never varies within one.

**To verify:** check whether the reader/driver puts the AK09916 in continuous-measurement mode and
enables the ICM's I²C-master cyclic sampling. Cross-ref the unpinned-dependency finding
(`2026-08-17 §4`) — `adafruit-circuitpython-icm20x` is at **2.1.10** against a `>=1.0.0` constraint, a
MAJOR-version jump; aux-master behaviour is exactly the kind of thing that changes across such a
boundary.

## 5. The honest-instrument violation

`states/imu` currently publishes:

```
"headingDeg": 236.9      (and gradePct / pitchDeg derived alongside)
```

**A heading to a tenth of a degree, from a frozen input.** Maximum apparent precision, zero information.
The bridge's honest-availability layer cannot catch this because the value is *fresh, finite and
plausible* — it simply never changes. **Absence of variation is not currently a checked property.**

Third instance of this class today, in a third subsystem: `syncPending=0`; the IMU all-zero frames
(F-5); and now the latched magnetometer. **All three are non-measurements wearing `data_source='real'`.**

## 6. Fix shape (design owed to Atlas before grooming)

1. **Fix the acquisition** — configure the AK09916 for continuous measurement + ICM aux-master cyclic
   sampling so the registers actually refresh.
2. **Add a staleness/variance gate** — the same plausibility-gate story as F-5, extended: a channel that
   returns an IDENTICAL value for N consecutive samples is not reading. Publish silence + a typed reason
   (`sensor_stale` / `latched`), never a derived `headingDeg`.
3. **`headingDeg` must go typed-NA when its input is stale** — do not derive a precise bearing from a
   frozen vector.
4. **AFTER acquisition works: hard-iron / soft-iron calibration is genuinely required.** The CIO's
   instinct is correct on accuracy even though it did not explain the freeze — a floor-mounted compass in
   a steel unibody, near the transmission tunnel, floor wiring and seat rails, will need a 360°
   calibration or headings will be tens of degrees off. **Do not calibrate before §6.1 lands** — you
   cannot calibrate a sensor that is not reading. The permanent mount location is also worth revisiting.

## 7. Scope note

Accel + gyro are **healthy and trustworthy** — 1,292 distinct accel values per drive, real gyro rates.
`gMag`, `pitchDeg` and the g-trail are fine. **Only the magnetometer-derived fields (`headingDeg`, the
compass tape, the direction ribbon) are affected.**
