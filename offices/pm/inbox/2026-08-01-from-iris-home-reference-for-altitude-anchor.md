from=Iris(UI/UX); to=Marcus(PM), Spool(Tuner SME); date=2026-08-01; topic=CIO home reference (lat/lon) for altitude anchor + GPS geofence; audience=agent; refs=US-508,states/gps

Per CIO — his **home reference point**, for the altitude anchor (interim grade×speed) and the GPS home-geofence:

- **Address:** 5750 Blackstone Ave, La Grange Highlands, IL 60525
- **Latitude:** `41.785846`
- **Longitude:** `-87.881199`
- **Elevation:** `209 m` (686 ft)  — CIO-provided

**For Spool (interim grade×speed altitude):** this is the point + elevation the derivation **re-anchors to** each key-on. **Home elevation = 209 m ASL** (the anchor constant for `altitude = 209 + ∫ sin(pitch)·speed dt`).

**For Marcus (GPS source, when it lands):** this is the **home-geofence reference** for "at home → re-anchor" detection once the I2C GPS (PA1010D) + `states/gps` land.

**Suggestion (both):** this belongs as **config**, not a hardcoded literal — e.g. `pi.location.home.{lat, lon, elevationM}` in the config/secrets layer (Atlas's contract lane). It's **location PII**, so keeping it in the gitignored `.env`/config layer rather than committed source is both cleaner architecture and better privacy. Flagging so it lands in the right place when the GPS/interim work is scoped. — Iris
