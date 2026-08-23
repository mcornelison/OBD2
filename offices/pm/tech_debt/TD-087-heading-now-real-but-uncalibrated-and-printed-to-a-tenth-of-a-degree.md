# TD-087 — `headingDeg` is now a REAL reading, but uncalibrated and still printed to 0.1°

**Filed by:** Rex (Ralph) — 2026-08-21, during US-565
**Severity:** Medium — an honest-precision problem, not a fabrication
**Related:** US-565 (acquisition fix), US-564 (plausibility gate), F-135

## What changed under this

US-565 fixed magnetometer *acquisition*: the AK09916 is now read directly over
I2C bypass and genuinely varies (measured on the shipping code path,
chi-eclipse-01, 2026-08-21 — 350 distinct 3-vectors in 500 stationary samples,
longest bit-identical run 2). Before the fix it served 1 distinct value across
20,000 samples.

So `states/imu.headingDeg` stops being typed-NA and starts publishing numbers
again. **Those numbers are now measurements. They are not yet accurate ones.**

## The debt

Measured field magnitude on the bench, from the same run:

```
mag = (-59.25, 67.95, -0.3) uT   ->   |B| ~= 90.2 uT
Earth's total field at this latitude ~= 52 uT
```

The excess is a **hard-iron offset of roughly the same magnitude as the field
being measured** — expected, since the sensor sits on a Pi next to a display, a
buck converter and vehicle steel. An offset that size does not shift a bearing by
a few degrees; it can swing it by tens of degrees and the error is
direction-dependent, so it does not average out.

`imu_state_bridge` publishes `headingDeg` as `0..359` and the card renders it to
a tenth of a degree. **A tenth of a degree is a precision claim the underlying
measurement cannot support.** That is a milder cousin of the defect this whole
sprint has been closing: not a non-measurement wearing `data_source='real'`, but
a real measurement wearing more confidence than it earned.

## Why it was not fixed in US-565

Out of scope by explicit instruction. US-565's `conditionalOutcomes`:

> Compass CALIBRATION is meaningless before this lands — explicitly out of scope.

Atlas's finding says the same, and he is right about the ordering: you cannot
calibrate a sensor that is not reading. The sensor now reads. **The calibration
story is no longer blocked, and this TD exists so that transition is not silent.**

## Suggested disposition

Groom a calibration story (hard-iron offset + soft-iron scale, captured from a
figure-8 or a slow full turn, persisted and applied in `imu_state_bridge`).
Until then, consider whether the render should drop to whole degrees or a cardinal
octant — a bearing that is accurate to "roughly north-east" should not be printed
as `43.7`.

**Do NOT re-suppress `headingDeg`.** It is a real reading now, and hiding a real
measurement is the opposite failure to the one the sprint fixed. The question is
how precisely to state it, not whether to state it.

## Evidence

- `offices/ralph/scripts/characterize_magnetometer.py` — reproducible probe
- `tests/fixtures/mag_bypass_90s_2026-08-21.csv` — the 90 s capture, with its own
  provenance header
- `src/pi/sensors/ak09916_bypass.py` module header — the full measurement trail
