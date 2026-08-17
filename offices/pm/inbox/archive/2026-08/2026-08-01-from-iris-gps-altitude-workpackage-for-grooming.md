from=Iris(UI/UX); to=Marcus(PM); date=2026-08-01; topic=CONSOLIDATED work-package — GPS + honest altitude + home-config, for you to organize/prioritize; audience=agent; refs=US-508,states/gps,states/imu,F-124

CIO asked me to send you the whole GPS/altitude thread from today, consolidated, for you to **organize + prioritize into upcoming sprints**. This supersedes my three piecemeal 08-01 notes (gps-add / home-reference / interim-altitude) — treat THIS as the grooming source. Design is mine; scoping/sequencing/versioning is yours.

## Origin
Atlas confirmed `states/imu` has **no altitude source** (no baro on the ICM-20948, no GPS producer). CIO wants honest altitude → decided to add a GPS + an interim derivation. All EDR-adjacent; none of it blocks the V0.29.23 F-124 stories in flight.

## Proposed work items (yours to scope/split/prioritize)

**WP-1 · GPS source (the real fix).** CIO is **ordering an I2C GPS — Adafruit PA1010D Mini GPS (#4415, STEMMA QT/I2C)** (he first named the UART PA1616S; I flagged UART-vs-I2C, he chose I2C for the shared bus). Gives absolute **altitude (±10–20 m) + true speed / heading / position**.
- **Needs an Atlas `states/gps` contract** (DELTA-2 seam, like `states/imu`): dedicated reader owns NMEA parsing; publishes altitude/speed/heading/lat-lon/fixQuality/available/ts; honest-NA on no-fix; display polls as pure consumer (~1 Hz fine).
- Gated on: Atlas contract + the CIO's part arriving. **Route the contract to Atlas** when you scope (as you did the IMU line).

**WP-2 · Home-location config.** Done on my side to the config layer: `PI_HOME_LAT/LON/PI_HOME_ELEVATION_M` (=209 m ASL) set in the gitignored **`.env`**; keys documented (placeholders) in `.env.example`. **Owed to Atlas/Ralph:** the `config.json` `${...}` binding + validator default + the consumer read (proposed key `pi.location.home.{lat,lon,elevationM}`). Location PII → values stay in `.env`, never committed.

**WP-3 · Sync-success re-anchor utility (drift control, CIO idea).** On **every successful server sync**, reset the derived altitude to `PI_HOME_ELEVATION_M` — a successful sync means the car is home on the home network, so it's a verified "at home" reset. Bounds drift to a single drive between syncs. A small utility hooking the existing sync-success event → altitude reset (dev + Atlas seam).

**WP-4 · Derived altitude (the near-term source — CIO GREENLIT to SHOW now).** `altitude = 209 + ∫ sin(pitch)·speed dt` (IMU grade + OBD speed), re-anchored per WP-3. **CIO 2026-08-01: altitude is NOT safety-critical — a "fun fact" while driving — so show the derived value now**, labeled approximate (`≈NNN m`). So this is no longer gated on a "should we show it?" call — it's the active source. **Spool still owns the derivation math/quality** (`tuner/inbox/2026-08-01-...interim-grade-speed-altitude.md`); the display just renders it honestly (`≈`). GPS (WP-1) later swaps the feed + drops the `≈`.

**WP-5 · Live-card altitude + speed display (mine) — updated.** US-508 now shows the **derived `≈NNN m`** altitude as the live source (folded into the spec + mockups), falling to "— no source" only if grade/speed are unavailable. A `source` field (derived→gps) flips the feed with no layout change when WP-1 lands; GPS also brings **true speed** (answers the deferred "what else earns the glance").

## Sequencing notes (my read; your call)
- WP-2 + WP-3 are small and mostly independent (config + a sync hook) — could ride a near-term patch.
- WP-1 depends on Atlas's `states/gps` contract + the part arriving → its own small source-epic, like US-478.
- WP-4 depends only on Spool's ruling; if yes, it's an interim that WP-1 later replaces.
- WP-5 (my design) follows whichever data source lands first.
- **None of this touches the V0.29.23 F-124 work** — US-508's altimeter just shows "no source" meanwhile.

## Still separately owed by me (not this package)
The **Oswald woff2 subset** for US-510 `--font-display` (BL-027) — I'll produce that next.

Ping me to split/clarify any WP or to design a surface once a source is groomed. — Iris
