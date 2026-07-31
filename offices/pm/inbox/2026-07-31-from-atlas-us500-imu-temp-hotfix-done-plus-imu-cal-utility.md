from=Atlas(Architect); to=Marcus(PM); date=2026-07-31; topic=US-500 IMU temp hotfix DONE (dev a6aa088) + new IMU-calibration-utility item to groom; audience=agent; refs=US-500,US-478,US-497,sensor_reader.py

# US-500 hotfix = DONE on `dev` (`a6aa088`). Redeploy + validate. Plus: a new IMU-calibration item from the CIO.

## US-500 — fixed, committed to `dev` (`a6aa088`)
Verified your diagnosis **live on the Pi first** (journal: `'ICM20948' object has no attribute 'temperature' -- no sample this poll`, every poll). Root: in `_readAndPublish` the temp read sits in the atomic burst BEFORE any publish, so the `AttributeError` dropped the whole accel/gyro/mag burst → `states/imu` never written.

Fix (`sensor_reader.py`): guarded the temp read → honest-null (`except (AttributeError, TypeError, ValueError): temp = None`, mirroring `_readLux`). temp is NOT in the states/imu display contract + `edr_imu_sample.temp_c` is nullable, so a missing temp degrades to null (never fabricated) and no longer drops the critical trio.

**Second-half (you flagged it) — downstream confirmed None-safe:** bus publishes `temp=None` (same as the Light reader's `lux=None`); `imu_state_bridge` tests green (card uses accel/gyro/mag, not temp); EDR persist has no non-None assumption (`temp_c REAL` nullable). No second edit needed.

**Verification:** TDD RED→GREEN (`FakeImuNoTemp` reproduces the live crash → zero samples, then green); full `sensor_reader` + `imu_state_bridge` + `edr_end_to_end` suites green; ruff clean. **UNVALIDATED on the live board** — on your redeploy over the wired `.9`, confirm: `states/imu` present with live accel/gyro/mag, no `imu read failed` warnings, US-497 card renders g-force/compass. That retires the US-478/497 on-Pi validation + closes US-500.

## NEW — IMU calibration utility (CIO ask, future / car-gated). Please groom as a backlog Feature under the EDR/IMU epic.
The CIO wants a small utility to **periodically calibrate the IMU once it's permanently mounted in the car**. Rationale: he can't hand-level the sensor perfectly, so the raw reading carries a real mounting offset (honest data — the sensor isn't wrong). Calibration captures that offset so the DISPLAY reads correctly. Three parts (analogous to the SPEED-PID GPS-cal pattern I built — capture → stored calibration SSOT → bridge applies):
1. **Accel level/mounting offset** (static, parked, seconds): the at-rest gravity vector → pitch/roll mount offset, so grade% / tilt read ~0 when parked-level.
2. **Gyro zero-rate bias** (static, at rest): the non-zero at-rest gyro → subtract at runtime (prevents heading drift).
3. **Magnetometer hard/soft-iron** (dynamic — the important one): the car's steel + electronics distort the field; needs mag samples across headings (slow full-circle drive) → ellipsoid fit → offset+scale. Without it a vehicle compass is off by tens of degrees; the environment can change, hence *periodic* re-cal.
Output = a **calibration SSOT** (an `imu_calibration` table/file; A-4 versioned if it syncs); the `states/imu` bridge reads it + applies it to gLat/gLon/headingDeg/gradePct.

**Load-bearing refinement to US-478 (do now, small):** the `states/imu` bridge should include a **calibration seam** — read a calibration SSOT and apply an offset, **defaulting to identity/zero** — so the future utility just populates it with **zero re-architecture** (A-11: don't paint into a corner). The utility itself is future + needs a proper design pass (I'll design-gate it when it grooms); only the seam is in scope for US-478.

— Atlas
