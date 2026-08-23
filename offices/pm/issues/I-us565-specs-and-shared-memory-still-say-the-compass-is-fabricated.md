# I-us565 — Three shared-surface facts go stale the moment US-565 deploys

**Filed by:** Rex (Ralph) — 2026-08-21, closing US-565
**Type:** Documentation / shared-knowledge drift (not a code defect)
**Routing:** `specs/` is read-only for Ralph; shared memory is PM's lane. Three
items, all outside my write access, all made stale by the same change.

---

## 1. `specs/architecture.md` §10.8 — the IMU acquisition path changed

The EDR sensor-bus section describes the ICM-20948 as a single 9-DoF device read
through one driver handle. As of US-565 the magnetometer is acquired on a
**different path**: the ICM's auxiliary-I2C master is disabled, `BYPASS_EN` is
set, and the AK09916 is read as its own I2C device at **0x0C** on the primary
bus. Accel and gyro still come from 0x69 and are unaffected.

This matters to anyone touching the bus later, because **0x0C is now an occupied
address** and the ICM's own `.magnetic` property is deliberately no longer the
source of the mag channel.

Suggested text is available in the `src/pi/sensors/ak09916_bypass.py` module
header, which carries the full measurement trail.

Flagging this explicitly because of the design-gate DoD (PM Rule 10): a sprint
touching a load-bearing subsystem updates its `specs/architecture.md` section
in-sprint or Atlas BLOCKs. I cannot make that edit from my lane.

## 2. Shared memory — "COMPASS IS FABRICATED" needs re-scoping, not deleting

`MEMORY.md` currently reads:

> **🔴 COMPASS IS FABRICATED — `headingDeg` is not a reading** … Discard
> `headingDeg` + the compass tape + direction ribbon for ALL drives ≤41. …
> **Fix = US-565.**

Two halves, and they need different treatment:

- **"Discard for all drives ≤41" — STILL TRUE and must stay.** Those drives were
  captured with the broken acquisition path. Nothing retroactively fixes them.
- **"Fix = US-565" — now landed.** The channel varies (measured on the shipping
  code path: 350 distinct 3-vectors in 500 stationary samples, longest
  bit-identical run 2, against 1 distinct in 20,000 the same day).

**Do not simply delete the entry** — the drive-≤41 caveat is load-bearing for
Spool's analysis. Re-scope it to "fixed from V0.29.30 forward; discard for drives
≤41", and see **TD-087**: the heading is a real reading now but is *uncalibrated*,
so it should not be trusted to the tenth of a degree the card prints.

## 3. Upstream library defect — worth reporting, per Atlas

`adafruit-circuitpython-icm20x` 2.1.10, `adafruit_icm20x.py`:

```python
@property
def magnetometer_data_rate(self):
    # read mag DR register
    self._read_mag_register(_AK09916_CNTL2)     # <- no return statement
```

The getter discards the value and returns `None` for every possible mode. Atlas
recommended reporting it upstream; that is a CIO/PM action, not mine.

**A second, larger upstream finding from US-565's characterization**, which I
believe is the actual root cause and is worth including in any report: the
driver's cyclic slave0 shadow readout performs **one transfer and then stops** on
this Pi. Measured over a 12 s window — mag changed exactly once, at sample index
1, then held for 270 more samples while accel changed 265 times on the same die.
The chip itself was fine throughout: polled directly with the shadow quiesced it
was converting and dithering normally. `_write_mag_register` also returns a
completion flag that the driver discards at every call site, which is why a
configuration that never reached the chip looked identical to one that did.
