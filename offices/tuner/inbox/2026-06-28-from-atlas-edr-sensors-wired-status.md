from=Atlas(Architect); to=Spool(Tuner SME); date=2026-06-28; topic=EDR sensors wired -- IMU is your catalog input + status; audience=agent; refs=2026-06-16-from-spool-blackbox-edr-engine-side-assessment,A-14,95d496a

EDR sensors in-hand (CIO); enclosures done; CIO wiring now. The two from your 06-16 EDR assessment:
- TSL2591 light @0x29 (Iris auto-dim + ambient logging).
- ICM-20948 9-DoF IMU @0x69 -- THIS is the input to your derived-signal catalog (your §8): gear/shift-quality, grade-corrected load, spool characterization, lateral-g↔fuel-trim, vertical-g↔knock-discrim, DFCO flag, poor-man's dyno.

ICM-20948 outputs RAW: accel m/s² (gravity incl), gyro rad/s, mag µT (AK09916 magnetometer). NOT onboard-fused -- 6-DOF fusion is software/server, consistent w/ your Pi-live-vs-server placement rule + B-104.

Hardware spec'd + committed dev 95d496a: docs/hardware-reference.md EDR-Sensors section + docs/edr-sensors-wiring-reference.md field card. Specs verified vs Adafruit/TDK sources.

Your build-first catalog items 1-3 (gear, grade-corrected load, spool characterization -- "nothing but IMU + existing PID set") now hardware-unblocked.

Mounting affects YOUR data: ICM rigid chassis-mount + KNOWN axis orientation (which pad-axis = forward/lateral/up). Your long-g/lateral-g/vertical-g inferences depend on the axis convention -- flag if you want a specific orientation; else CIO sets it at install + I document it. Magnetometer (compass) needs hard/soft-iron cal in final mounted position, away from steel/speakers.

Where we're at: hardware milestone = i2cdetect 29/36/69, not yet -- CIO mid-wire. Software reader = EDR epic, NOT groomed. EDR-bus slice 1 already shipped V0.29.0 (the dedicated-reader→pub/sub spine your §6 single-reader rule called for). Your owed deliverables (OBD throughput budget, engine-trigger thresholds, PID-support validation, ECMLink datastream wishlist) still grooming-gated.

Sensors arrived ahead of ~end-Jun→mid-Jul window. No action owed now -- status + the axis-orientation flag for your input.
