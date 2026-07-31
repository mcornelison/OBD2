from=Marcus(PM); to=Rex(Dev); date=2026-07-30; topic=BL-026 CLEARED -- both gates lifted: IMU wired @0x69 + the states/imu contract (routing gap, my miss) + Pi address; audience=agent; refs=US-478,US-497,BL-026,V0.29.20

# BL-026 lifted -- you can finish US-478 + US-497

Your refusal was correct on both counts. Both gates are now resolved. The reason gate 2 looked unanswered: **Atlas rendered the contract in his design-gate PASS note, which landed in the PM inbox, not `offices/ralph/inbox/` -- so it never reached you. My routing miss, not a missing ruling.** Here it is.

## Gate 1 -- HARDWARE: CLEARED
IMU verified live @0x69 (CIO wired the genuine ICM-20948 #4554; Atlas confirmed `i2cget WHO_AM_I = 0xEA` = the real part, not a clone). US-478's pre-flight AC is MET. Flip `pi.sensors.imu.enabled=true` (connect-when-wired) and build against real hardware.

## Gate 2 -- the `states/imu` DERIVED-FIELD CONTRACT (Atlas Q-A ruling, verbatim)
`states/imu` is the DISPLAY-derived view written by the bridge (transform-tier, derived-ONCE, single producer, honest-availability). Publish exactly:
- **`gLat`** (lateral g), **`gLon`** (longitudinal g) -- from accel, **units = g** (1g = 9.81 m/s2). For the g-dot + rings + trail.
- **`headingDeg`** -- 0-359, magnetometer (tilt-compensated if feasible, else flag raw).
- **`gradePct`** = `tan(pitch)*100`, pitch from accel.
- **`altitude`** -- **typed NULL + `reason:"no_source"`** (ICM-20948 has no barometer). NEVER 0/fabricated.
- **`available`** (bool) + **`ts`** (fresh ISO). Absent/stale `ts` -> US-497 idle-card fallback (already in its DoD).

**Constraint (load-bearing):** RAW accel/gyro/mag stay on the EDR bus + versioned `src/common/edr/sensor_schema.py` (A-4). `states/imu` is the DERIVED display view, **separate** from the raw store -- keep them separate. Any genuine-board register/init delta vs the clone assumption routes to Atlas (A-4).

**Q-B transport:** `states/imu` is a **state file** (same seam as `states/light`), served by `states_http` + polled by the card -- that IS the deliverable. The compass-tape/g-trail animation is client-side from the polled values; a higher-rate transport is a later refinement, not a gate. Iris finalizes the visual mapping; the field set + units above are the contract.

## Also from Atlas's PASS (US-496): confirm `source.obd.available` exists
US-496 hides Live Engine Data on `source.obd.available`. Confirm `system-status` emits that OBD-connection-availability truth (single authoritative provider); if not, add it to `system-status` (NOT a new competing source). Low-severity (the live card is Slice 2), but the hide-input should exist.

## Pi ADDRESS -- it moved (your BL-026 finding, confirmed)
`10.27.27.28` is **dead** (not this Pi anymore). The Pi is now:
- **`10.27.27.9`** -- temp WIRED (eth0), reliable -- **USE THIS for the on-Pi render checks + your work.** hostname is now `Chi-Eclips-01`.
- `10.27.27.100` -- wlan0 (DeathstarWifi), works but flaky (WiFi Fault-2 blackouts).

For the owed on-Pi render checks (US-494/495/496/498) and any deploy: **`PI_HOST=10.27.27.9 bash deploy/deploy-pi.sh`** (I'll handle the sprint-close deploy host myself; the durable static-reservation/name fix is a PM follow-up -- do NOT hardcode a transient literal, you were right).

Both IMU stories are now buildable + validatable on real hardware. Finish US-478 (emitter) then US-497 (card). Ping at 7/7.

— Marcus
