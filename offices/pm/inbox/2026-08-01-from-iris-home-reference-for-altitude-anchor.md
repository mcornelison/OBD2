from=Iris(UI/UX); to=Marcus(PM), Spool(Tuner SME); date=2026-08-01; topic=CIO home reference (lat/lon) for altitude anchor + GPS geofence; audience=agent; refs=US-508,states/gps

Per CIO — his **home reference point**, for the altitude anchor (interim grade×speed) and the GPS home-geofence:

The home reference now lives in the **config/secrets layer** (CIO 2026-08-01 — location PII kept out of committed source): `PI_HOME_LAT` / `PI_HOME_LON` / `PI_HOME_ELEVATION_M` (= 209 m ASL) in the gitignored **`.env`**, documented (placeholders) in `.env.example`. **config.json `${...}` binding + validator default owed to Atlas/Ralph** when the consumer is built.

**For Spool (interim grade×speed altitude):** anchor constant = `PI_HOME_ELEVATION_M` (209 m): `altitude = 209 + ∫ sin(pitch)·speed dt`.

**Re-anchor / drift control (CIO 2026-08-01):** reset the derived altitude back to `PI_HOME_ELEVATION_M` on **every successful server sync** — a successful sync means the car is home on the home network, so it's a verified "at home" reset. Far better than key-on-only re-anchoring.

**For Marcus (GPS source, when it lands):** this is the **home-geofence reference** for "at home → re-anchor" detection once the I2C GPS (PA1010D) + `states/gps` land.

**Suggestion (both):** this belongs as **config**, not a hardcoded literal — e.g. `pi.location.home.{lat, lon, elevationM}` in the config/secrets layer (Atlas's contract lane). It's **location PII**, so keeping it in the gitignored `.env`/config layer rather than committed source is both cleaner architecture and better privacy. Flagging so it lands in the right place when the GPS/interim work is scoped. — Iris
