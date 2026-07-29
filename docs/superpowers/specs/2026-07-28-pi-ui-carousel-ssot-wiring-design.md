# Design: Pi UI carousel — wire Iris's screens to a single source of truth

**Date:** 2026-07-28
**Author:** Atlas (Architect), from a brainstorming interview with the CIO
**Status:** Design — pending CIO review, then route to Marcus (PM) for story grooming
**Refs:** A-16 (deploy/UI drift), honest-availability SSOT pattern (`specs/ssot-design-pattern.md`), US-480/US-481/US-490 (carousel/idle/menu), F-092/F-097/F-111 (emitters), F-121 (F-121 carousel review)
**Grounding:** full code-map of the V0.29.19 display wiring (boot splash, states server, emitters, `carousel.js`/`dashboard.css`) — findings embedded below.

---

## 1. Problem (observed on the bench, V0.29.19)

Iris designed a well-formed carousel UI, but on a real Pi boot it is unusable:

- **Symptom 1 — splash pinned.** Boot shows a chromium splash reading *"Eclipse ODB2 … not ready (starting)"* (V0.29.19) and never transitions to the dashboard.
- **Symptom 2 — dead DTC takeover.** Killing the splash reveals a dashboard with a gray ⚠ triangle, a red "CHECK ENGINE" box, and overlapping half-in/half-out buttons (Cancel / Clear All / View Details / Dismiss). Nothing is clickable; nothing works.

The CIO's goal: **wire Iris's screens to a single source of truth, make them functional, and get a bench-validatable milestone first** — then the vehicle pieces.

## 2. Root causes (both are genuine repo code defects, verified — not merely stale assets)

- **Symptom 1 = boot-state emitter stub.** `boot_state_emitter.py` assesses the `eclipse-obd` tier through an injected `obdProbeFn`, but `main()`/the systemd unit never inject a real one, so it defaults to `lambda: OBD_STARTING` ("starting") **forever** (`boot_state_emitter.py:229,301`; unit `deploy/eclipse-boot-state.service:54`). → tier never terminal → `progress` caps at 2/3 → `healthy` never true → splash never `window.close()`s → the unit's `OnSuccess=eclipse-dashboard.service` never fires → dashboard never auto-starts. After a 12 s cap it degrades to the literal string *"eclipse-obd: not ready (starting)"* and pins there until reboot.
- **Symptom 2 = missing `[hidden]` guard in CSS.** The five full-screen overlays (`#dtc-takeover`, `#dtc-detail`, `#clear-confirm`, `#confirm-modal`, `#setup-menu`) set `display:flex` via ID selectors with **no `[hidden]{display:none}` guard** (`dashboard.css:331,428,482,565,719`). Author-origin `display` beats the UA `[hidden]` rule, so the `hidden` attribute (and every JS `.hidden=true`) is **inert** → all five overlays paint at once, stacked, unclickable. **Iris's JS is correct** — by data it would *not* show a phantom Check Engine; the CSS defeats it.
- **Compounding: deploy asset drift.** Kiosks load from `/opt/splash` and `/opt/dashboard`, copied by `deploy-pi.sh`. The bench wordmark "Eclipse ODB2" vs repo "ECLIPSE OBD-II" indicates the deployed assets are older than the repo. Fixes must force-refresh these.

## 3. Single source of truth (SSOT)

The **states HTTP server** (`states_http_server.py`, `127.0.0.1:9899`) serves one JSON state file per source from `/run/eclipse-obd/states/`. Every card reads exactly **one** state file. All producers follow the **honest-availability pattern**: one availability truth per source; an unavailable source renders a **typed "unavailable / gray"** state — never a fake number, never a false alert. This rule applies **recursively inside a card** too: a card whose source is live but which has a sub-field with no producer (e.g. altitude) grays *that field*, not the card.

## 4. Card model (final)

Two tiers:

| Card | Tier | State file | Producer today | Action |
|---|---|---|---|---|
| **Pi Health** (WiFi + BT/OBD link + power + uptime) | Always-present, gray-if-offline | `system-status` | ✅ runs (orchestrator) | keep |
| **Battery** | Always-present, gray-if-offline | `battery-health` | ✅ runs | keep |
| **Light** | Always-present, gray-if-offline | `light` | ✅ runs (behind `pi.bus.enabled`+`pi.sensors.light.enabled`) | flip flags on |
| **IMU live-instrument** (G-force + compass; altitude field) | Always-present, gray-if-offline | `imu` (new) | ❌ none | **build emitter+card** |
| **DTC / Check-Engine** | Always-present, **gray-if-no-data** | `dtc` | ✅ runs | keep (CSS fix removes phantom) |
| **Live Engine Data** | **Hidden until vehicle connected** | live PIDs | (vehicle slice) | Slice 2 |
| **LTFT** (long-term fuel trim) | vehicle-dependent | `ltft-trend` | 🪦 orphaned emitter | **remove from carousel now**; revisit in Slice 2 (fold into Live Engine Data or wire then, per Spool) |

**Decisions locked with the CIO:**
- **Flow:** splash → live carousel (Iris's design is the target; this is wiring, not a redesign).
- **Input:** touchscreen; **auto-cycle while driving, tap-to-interact only when parked** (US-490).
- **Availability:** always-present + gray-if-offline for Pi-local cards + DTC; **hide** only the live-engine card(s) until the vehicle is connected.
- **Splash handoff:** hand off when **Pi core/UI is up** (states server + Pi-local emitters), **not** when the vehicle is connected.
- **IMU:** in scope; feeds the G-force / compass / altimeter live-instrument card; lights up when the CIO physically wires the ICM-20948; grays until then.
- **Altitude:** the ICM-20948 has **no barometer** → cannot produce altitude. The altimeter field grays "no source" until an altitude producer exists. Optional future add: a BMP280-class baro sensor on the same I²C bus (small EDR hardware item), or a future GPS. **Does not block** the IMU card (g-force + compass are fully functional).
- **LTFT:** removed from the always-present carousel now (dead card); revisited in Slice 2.

## 5. Story sequence

**Slice 1 — bench, no car (the CIO's first milestone):**
- **S1 — Splash handoff fix.** Boot-state readiness bar = "Pi core/UI up," not "vehicle connected." Report the eclipse-obd tier's *actual* service state (or exclude it from the handoff gate); splash hands off as soon as the states server + Pi-local emitters are ready. *Bench-validatable: splash → carousel on boot with no vehicle.*
- **S2 — Overlay CSS fix + asset refresh.** Add `[hidden]{display:none}` guards to the five overlays in `dashboard.css`; force-refresh `/opt/splash` + `/opt/dashboard` on deploy. *Bench-validatable: no phantom takeover; overlays appear only when invoked.*
- **S3 — Pi-local cards live + honest gray.** Verify Pi Health (WiFi/BT/power/uptime), Battery, Light render **live** on the bench; DTC card grays "no data" (no red alert); each honest-availability. Flip `pi.sensors.light.enabled` on. *Bench-validatable.*
- **S4 — IMU live-instrument card + emitter.** New `imu` emitter (reads 9-DoF off the EDR bus, honest-availability, altitude field typed-NA until a baro/GPS source exists) + the g-force/compass/altimeter card. Grays until the CIO wires the sensor; lights up when fed. *Bench-validatable once the IMU is physically wired.*
- **S5 — UI-render regression test.** A test that exercises **CSS-cascade layout** (jsdom/palette tests do not) so the `[hidden]`-override class of bug can't ship again. Assert the overlays are not visible with the `hidden` attribute set.

**Slice 2 — needs the car:**
- **S6 — Live Engine Data card.** Hidden until the vehicle is connected; appears with live PIDs (RPM/boost/temps…). Depends on the A-17 capture fix (78f6bc8/V0.29.19) validating on a drive.
- **S7 — DTC card with real data + parked interactions.** Real MIL/codes; parked-only View Details / Clear (via `/dtc-clear`) / Dismiss validated in-car.
- **S8 — LTFT disposition.** With the car + Spool's input: fold LTFT into Live Engine Data or wire it as its own card; retire the orphaned emitter or connect it.

## 6. Cross-cutting

- **Honest-availability everywhere** (per `specs/ssot-design-pattern.md`): sources gray, never fake; sub-fields with no producer gray individually.
- **Deploy = distinct gate** (A-16 lesson): "merged to dev" ≠ "renders on hardware." Each slice's DoD includes a clean deploy + on-Pi render check, not just unit-green.
- **Lane / handoff:** Atlas produces this design + the story sequence. **Marcus (PM)** grooms it into stories/sprint mechanics; **Ralph** builds; **Iris** owns visual polish; validation drives are Spool + the car. Atlas design-gates the resulting PRD.

## 7. Out of scope (YAGNI)

- No carousel redesign — Iris's screens are the target.
- No new interaction model — parked-only tap (US-490) already designed.
- Altitude hardware (baro/GPS) is a separate future EDR item, not part of this UI wiring.
