# Pi Touch-UI — Live-Instrument Home Card (W-11) — Design Spec

| | |
|---|---|
| **Author** | Iris (UI/UX) |
| **Date** | 2026-07-27 |
| **Status** | **REVIEWED — CIO-locked 2026-07-27** (2 review rounds; may revisit after a few drives). Atlas contract Qs + DELTA-1 arbiter routed. Build sequences after US-478 IMU bring-up. |
| **Brief** | Marcus 2026-07-27 (`inbox/2026-07-27-from-marcus-live-cards-plus-polish-design-brief.md`) |
| **Companion** | `proposals/2026-07-27-pi-live-instrument-card.html` + hosted artifact |
| **Consumes** | `states/imu` (US-478, mirrors the `states/light` bridge) + OBD-derived gear (Spool) |
| **Palette** | `specs/UI/tokens.css` |

## 0. What this is
The **driving twin** of the shipped idle card. Same carousel home slot: **parked → idle card,
driving → live card.** No separate drive-mode (CIO, W-11). It is a calm live *instrument* — the
alerts (coolant/knock/voltage + DTC STOP) ride the separate unified alert layer (DELTA-1), on top.

Layout is the June-18 walkthrough's "live2" that the CIO already approved, now grounded against
the real IMU contract, the shipped tokens/chrome, and Spool's semantics.

## 1. Layout (480×320, "live2")
```
┌─ topbar: BT ⇅ ⚡           V0.29.x  ⋮ ─┐
│ LIVE · DRIVE 34  ●REC                  │
│ ┌───────────────┬───────┬───────────┐ │
│ │ HEADING       │ GEAR  │  G-FORCE   │ │
│ │  ‹compass tape›│       │  ╆ rings   │ │
│ │   247° WSW    │   3   │  · trail   │ │
│ │ GRADE +3°  ∿∿ │       │ 0.3 / 0.1  │ │
│ └───────────────┴───────┴───────────┘ │
│              • • • •                    │
└─────────────────────────────────────────┘
```
- **Compass tape (heading):** a horizontal scrolling tape (degree ticks + N/NE/E/… letters)
  under a fixed center caret; the numeric heading + cardinal below it.
- **Gear:** big glyph. **Spool owns it** — `--` when ambiguous (speed<5 km/h, rpm<900, ratio>15%
  off nearest), `N` rolling-neutral, ≥2 s debounce. **Never a wrong number.** 4th/5th are at the
  OBD sample-rate edge (Spool) → the display must render `--` gracefully there, not guess.
- **Grade:** current **road grade %** (= tan(pitch°)×100 — CIO 2026-07-27) + a ~15-min rolling
  grade-trend sparkline (live; scrolls as the road rises/falls). Informational (Spool: no alarm).
  Titles minimal ("GRADE" / "G-FORCE").
- **Altitude — DERIVED, shown as an approximate fun-fact (CIO 2026-08-01).** The ICM-20948 has no
  baro and there's no GPS yet, so there is **no measured** altitude. CIO's call: **altitude is not
  safety-critical — it's a "fun fact" while driving — so show the DERIVED value now**, honestly
  labeled approximate, and swap the source to GPS when the sensor arrives.
  - **Source now = derived** `altitude = PI_HOME_ELEVATION_M (209 m) + ∫ sin(pitch)·speed dt`
    (IMU grade + OBD speed), **re-anchored to home elevation on every successful server sync**
    (drift bounded to one drive — CIO). Spool owns the derivation math/quality
    (`tuner/inbox/2026-08-01-...interim-grade-speed-altitude.md`); the display renders it.
  - **Honest label:** show it as **`≈ NNN m`** (a leading `≈` / "derived" cue), never as a precise
    fix — it's approximate and drifts. If the derivation is unavailable (no grade/speed), fall back
    to **"— no source"**, never zeroed.
  - **Source later = GPS** (I2C Adafruit PA1010D #4415 → `states/gps`, Atlas contract): swaps the
    feed to absolute altitude (±10–20 m) and **drops the `≈`**; also brings **true speed / heading /
    position** (the speed answers the deferred "what else earns the glance"). The display is a pure
    consumer — a `source` field flips derived→gps with no layout change.
- **G-force:** a cross-haired meter with concentric rings, a live dot at (lat, lon) g, and a
  fading **~35 s trail**. Informational, never a takeover (Spool). **Amber ring/dot at 0.6 g**
  (Spool) — which doubles as an aged-tire lat-load nudge, advisory not alarm.

## 2. Honest-instrument rules
- **No fabricated motion.** If `states/imu` is **absent or stale**, the home slot **falls back to
  the idle card** (brief) — never a frozen or zeroed live instrument implying "stationary".
  A visible freshness marker; a stale feed degrades, it doesn't lie.
- **Display never fuses sensors.** Heading (from mag), pitch/grade (from the accel gravity
  vector), and g (tilt-compensated horizontal accel) are **derived by the reader**, not the
  display. The display is a pure consumer of already-derived fields (SSOT / Atlas DELTA-2). See §3.
- **Gear is OBD/Spool, not IMU.** IMU may sharpen it later, but the number is Spool's derivation.
- **Alarms are not on this card.** Live engine/motion 🔴/🟡 belong to the unified alert layer
  (DELTA-1); a 🔴 there is full-brightness + un-dismissable-while-active (Spool). This card stays calm.

## 3. Data contract — `states/imu` (routes to Atlas, DELTA-2 class)
US-478 brings the ICM-20948 up on the EDR bus and mirrors `raw.imu.*` → `states/imu`, exactly like
`raw.light.lux` → `states/light`. Two questions for Atlas, both mirroring his DELTA-2 ruling:

- **Q-A — derived vs raw fields.** The raw table is `accel_x/y/z` (m/s², gravity incl.),
  `gyro_x/y/z` (rad/s), `mag_x/y/z` (µT), `temp_c`. The display needs **display-ready derived**
  values: `headingDeg`, `pitchDeg`/`gradePct`, `gLat`/`gLon`/`gMag`, + `ts`/freshness. **Proposal:**
  the `states/imu` reader (owner) computes and publishes these; the display never does fusion.
  Confirm the reader owns the derivation (same seam as the light bridge).
- **Q-B — refresh rate / transport.** A compass tape + a 35 s g-trail will **not** animate at the
  1 Hz card poll (Atlas already flagged this DELTA-2 open item). **Proposal:** a higher-rate
  STREAM/SSE topic for the live view (decided in the EDR-bus design), distinct from the 1 Hz card
  poll the other cards use. Flagging so the contract is settled before build.

*(Full-bleed letterbox already covers this card — it's a carousel card, no new scaling work.)*

## 4. Acceptance criteria (Argus-style booleans)
1. **Driving → live, parked → idle:** with a fresh `states/imu` feed the home card is the live
   instrument; when the feed goes absent/stale it falls back to the idle card. ✅/❌
2. **No fabricated motion:** a stale/absent feed never shows a frozen/zeroed live instrument as if
   live; freshness is visible. ✅/❌
3. **Gear honesty:** ambiguous conditions render `--`/`N` per Spool, never a wrong gear number. ✅/❌
4. **G semantics:** the dot/ring cross to amber at 0.6 g (Spool); g is never a takeover. ✅/❌
5. **Pure consumer:** the display reads derived fields from `states/imu`; it performs no sensor
   fusion and never opens I²C/the bus itself. ✅/❌
6. **Alarm separation:** a live 🔴 shows via the unified alert layer (full brightness), not as a
   recolor of this calm card. ✅/❌

## 5. Routing / next steps
- **Atlas (design-gate, loop EARLY):** Q-A derived-field contract for `states/imu`; Q-B live
  refresh-rate/transport; **and the DELTA-1 unified-alert arbiter contract** (brief item 2 — its
  own note). All EDR-gated; design proceeds now, build sequences after US-478.
- **Spool:** semantics already delivered (g 0.6 g, grade/gear, light floor) — consuming, nothing
  owed. Confirm only if the heading/grade *derivation* needs his grounding.
- **Ralph:** builds after US-478 + CIO/Atlas review (design-before-build; my review is the gate).
- **Marcus:** grooms into the live-cards sprint (sequences after US-478 IMU foundation).

## 6. Open design decisions (for the CIO review)
- **Compass tape vs dial** — tape (approved June-18) reads a heading change directionally; a round
  dial is more familiar. Keeping the tape unless you prefer the dial.
- **Grade: ° vs %** — ✅ RESOLVED (CIO 2026-07-27): **road-grade %**.
- **G-force rail (CIO 2026-07-27):** title moved inside the chart; chart spans heading-top →
  grade-bottom; larger g-circle; display fonts bumped. ✅ applied.
- **What else earns the glance** — speed on the card? coolant/voltage minis here or alert-layer
  only? **DEFERRED post-drive (CIO 2026-07-27):** design locked as-is; revisit after a few real
  drives inform what's actually missing at a glance.
