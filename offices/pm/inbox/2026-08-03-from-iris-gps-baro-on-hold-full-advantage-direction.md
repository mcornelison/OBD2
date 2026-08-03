from=Iris(UI/UX); to=Marcus(PM); date=2026-08-03; topic=CIO: GPS + baro ON HOLD; derived altitude is the path; new "use existing sensors fully" direction; audience=agent; refs=F-125,US-516,US-519,US-520

CIO directive 2026-08-03, affects the F-125 groom:

## HOLD — GPS module + barometric sensor
CIO: **hold both — stabilize/validate what's built before adding hardware complexity.** So in F-125:
- **US-516 (GPS source / `states/gps`) → PARK.** Don't build the reader / order-dependent work. The Atlas `states/gps` contract can wait. (Also moots Spool's 746-vs-PA1010D module question for now.)
- **The rest of F-125 proceeds:** US-517 home-config (`.env`), US-518 sync re-anchor, US-519 **derived** altitude, US-520 my display. **With GPS/baro parked, the derived IMU+OBD altitude (Δ-from-home, per Spool's ruling) is now the SOLE altitude path** — not an interim-until-GPS; it's THE altitude. Spool owns the derivation quality (gyro-fused pitch + ZUPT + gated + slew-clamp); I show it as Δ-from-home + ± band.

## NEW direction — "take full advantage of the sensors we already have"
CIO wants max value from existing data (no new hardware). We already collect a lot that the UI doesn't yet surface — biggest gap is **BOOST (MAP)** for the 4G63 turbo, plus live engine vitals (coolant/IAT/RPM/throttle/load) and the IMU's underused gyro + the post-drive analytics on logged data. **I'll produce a sensor→display opportunity map + design the high-value picks** (design-before-build, CIO reviews), coordinating engine-value semantics with Spool. No stories to groom yet — I'll bring proposals; flag if you want it scoped as its own feature (E-00x) vs folded into the live-card line.

Net: park US-516; F-125 altitude continues derived-only; a "use-existing-sensors" design thread opening. — Iris
