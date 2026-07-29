---
sprint: 66
version: V0.29.20
status: draft
createdAt: 2026-07-29
createdBy: Marcus (PM)
selectedStories: [US-494, US-495, US-496, US-478, US-497, US-498, US-499]
forksFrom: dev
sprintJsonPath: offices/ralph/sprint.json
epic: E-001 (UI/UX Polish)
feature: F-103 + F-111 + F-121 + F-113
theme: Wire Iris's carousel to the states SSOT + make it functional (bench-first)
designSpec: docs/superpowers/specs/2026-07-28-pi-ui-carousel-ssot-wiring-design.md (Atlas, CIO-approved)
atlasReview: "PENDING -- Atlas will design-gate this PRD (he authored the CIO-approved design)."
priority: HIGH -- CIO active bench focus
---

# PRD: V0.29.20 -- Pi carousel SSOT-wiring (Slice 1, bench-first)

| Field | Value |
|---|---|
| Version | V0.29.20 (patch on `dev`) |
| Theme | Make the deployed carousel **actually work + honest** on the bench: fix the pinned splash + the dead overlapping DTC overlay, wire the Pi-local cards + IMU card to the states SSOT, add the shutdown splash, + a render-regression backstop |
| Status | DRAFT -- Atlas design done + CIO-approved; routed for his PRD design-gate |
| Lane | Pi UI (splash + carousel CSS/JS + emitters) + deploy asset-refresh; **A-16: DoD requires clean-deploy + on-Pi render check, not just unit-green** |
| Stories | US-494/495/496/497/498/499 + US-478 (S4-emitter) |
| Deploy + validate | Deploys from `dev`; **bench-validatable** (S4/IMU needs the sensor wired -- AI-005). Slice 2 (live engine, in-car DTC, LTFT) is car-gated, deferred. |

## Why now
CIO booted V0.29.19 on the bench: the boot splash pins at "not ready (starting)" + never reaches the dashboard; killing it reveals a broken unclickable DTC takeover (overlapping half-boxes). Atlas design-gated the fix (`2026-07-28-pi-ui-carousel-ssot-wiring-design.md`, CIO-approved). Two real code defects + stale-asset drift.

## Stories (full DoD in `backlog.json`)

| Story | Size | Summary |
|---|---|---|
| **US-494** (S1) | S | Splash handoff fix -- readiness = **Pi-core-up**, not vehicle-connected (`boot_state_emitter` never gets its `obdProbeFn` -> stuck OBD_STARTING). Splash reaches the dashboard. |
| **US-495** (S2) | S | Overlay **`[hidden]{display:none}` guard** (5 overlays paint at once, unclickable) + **`/opt/*` asset force-refresh** (the "Eclipse ODB2" stale-asset drift). Kills the dead DTC takeover. |
| **US-496** (S3) | M | Pi-local cards live + **honest-gray** -- Pi Health / Battery / Light always present (gray-if-offline, per-field); DTC = gray "no data" (never a red alert idle); Live Engine Data hidden until vehicle connects. |
| **US-478** (S4-emitter) | M | IMU bring-up + `states/imu` emitter -- g-force + compass live; **altitude typed-NA** (no barometer). *Needs the IMU wired @0x69 (AI-005).* |
| **US-497** (S4-card) | M | IMU live-instrument card (Iris design) -- consumes `states/imu`; g-force + compass; altitude "no source"; parked/absent -> idle card. |
| **US-498** (S5) | S | **Shutdown/closeout splash** (new, CIO-requested) -- wire `splash-grace` -> `shutdown.html` renders honestly; guard the reverse-animation blank-trap. |
| **US-499** (S6) | S | **UI-render regression test** -- catches the CSS-cascade class (overlapping overlays / pinned splash) the current jsdom/palette tests miss. The A-16 automated backstop. |

## Sequencing / gates
- S1 + S2 make the UI **usable** immediately; do them first. S6 depends on S1/S2. S4-card depends on US-478.
- **S4 (US-478 + US-497) needs the IMU wired** (AI-005, CIO) for live validation -- the card + emitter build now against a fixture; the on-Pi live check waits for `0x69`. Everything else is fully bench-validatable.
- **Every story's DoD requires a clean deploy + on-Pi render check** (A-16). Coordinate S4 visuals with Iris.

## Not in this sprint (Slice 2 -- car-gated)
- S7 Live Engine Data card (depends on the A-17 capture fix validating on a drive) · S8 in-car DTC with real MIL/Clear/Dismiss · S9 LTFT disposition (Spool).
