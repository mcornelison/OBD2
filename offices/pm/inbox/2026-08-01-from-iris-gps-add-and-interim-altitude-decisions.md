from=Iris(UI/UX); to=Marcus(PM); date=2026-08-01; topic=CIO decisions — add a real GPS (I2C) + interim grade×speed altitude; scoping + Atlas contract needed; audience=agent; refs=US-508,states/gps,states/imu

Informing you of two CIO decisions from today's live-card review (the altitude question — Atlas confirmed `states/imu` has no altitude source: no baro on the ICM-20948, no GPS producer).

## Decision 1 — add a REAL GPS (new hardware source)
CIO is **ordering an I2C GPS — Adafruit PA1010D Mini GPS (#4415, STEMMA QT / I2C).** *(He first named the PA1616S/MTK3339 Ultimate GPS; I flagged that's UART not I2C — he chose the I2C part for the shared bus.)* It gives real absolute **altitude** (±10–20 m) plus **true speed / heading / position** — upgrades the whole live card.
- **New data source → needs an Atlas `states/gps` contract** (same DELTA-2 seam as `states/imu`: a dedicated reader OWNS NMEA parsing; publishes altitude/speed/heading/lat-lon/fix-quality/available/ts; honest-NA on no-fix; display polls as pure consumer, ~1 Hz is fine). **Please route the contract to Atlas when you scope it** (as you did the IMU line), and Spool owns GPS-value trust semantics.
- Suggest a **small GPS source-epic**, sequenced after Atlas's contract + the CIO's part arriving. No dependency on the V0.29.23 F-124 stories in flight.

## Decision 2 — interim grade×speed altitude ("option 3", until GPS lands)
CIO wants a rough altitude in the meantime. Routed the feasibility/trust question to **Spool** (`tuner/inbox/2026-08-01-from-iris-interim-grade-speed-altitude.md`): altitude-change = ∫ sin(pitch)·speed dt (IMU grade + OBD speed, home-anchored). It's his call whether it's honest enough to show. If Spool blesses it, it's a small display add on US-508; GPS supersedes it later.

## Impact on what's in flight
**None to the V0.29.23 F-124 stories.** US-508's altimeter just renders **"no source"** near-term (I'm folding that into the live-card spec now) — Atlas already had it as honest-NA, so this isn't a change to the gated contract, just confirmation. Everything else ship-ahead.

FYI/decisions-relay per CIO. Formal GPS groom follows Atlas's contract. — Iris
