---
sprint: 74
version: V0.29.29  # renumbered from V0.29.27 (deploys after V0.29.28); filename kept
status: draft
createdAt: 2026-08-08
createdBy: Marcus (PM)
selectedStories: [US-539, US-540-a, US-540-b, US-541, US-542, US-552]
forksFrom: dev @ (recorded at prd_to_sprint.py conversion; forks from dev AFTER V0.29.26)
sprintJsonPath: offices/ralph/sprint.json
epics: E-001 (UI/UX Polish)
features: F-127 (Pi 3.5in legibility + card-set overhaul)
theme: "3.5in legibility pass. CIO: dashboard fonts are 2-4x too small to read at arm's length in the car. Fix = a type SCALE (tokens) + larger tiles + fewer facts/card, pushing the card set 4->6 (partly reverses US-507/508 -- legibility outranks screen-count on a 3.5in panel). Iris-designed + CIO-reviewed; Atlas design-gates the structural parts."
atlasReview: "PASS 2026-08-10 (SOUND, no BLOCK). 3 structural items APPROVED: (a) screen-count 4->6 (7 w/Engine) -- carousel verified count-agnostic; (b) US-482 stage/scale confirmed font-independent (computeStageScale pure geometry); (c) idle-face retirement SSOT-correct (DTC-since-key-off -> Alerts; IMU-parked renders REAL, OBD bits typed-NA). Downsampling RULED: deploy pins NO output mode -> likely 1080p->480x320 downsample softens glyphs -> added US-552 (pin KMS output to native) as a distinct legibility lever; US-540-a re-verifies values AFTER mode confirmed. DoDs pinned (no CSS card-count cap; parked-logic reads system-status not data-face)."
irisReview: "DELIVERED 2026-08-07/08 (CIO-reviewed). Spec + interactive mockup: offices/uidevloper/proposals/2026-08-07-pi-3p5in-legibility-and-layout.{md,html}. Build to it."
---

# PRD: V0.29.27 -- Pi 3.5in legibility + card-set overhaul

| Field | Value |
|---|---|
| Version | V0.29.27 (patch on dev; forks after V0.29.26) |
| Origin | CIO reviewed the live UI on the 3.5in panel: fonts too small to read at arm's length in the car (compass heading, %-values, g-force, the CHECK-ENGINE line all illegible). Iris arithmetic confirms it: ~165 PPI, ~34px glance floor, shipped values 13-15px = 2-4x under. |
| Stories | US-539..542 (4). P2 Engine card + P3/P4 sensor prototypes queued separately (see below). |
| Deploy | from dev; **acceptance is IN-CAR** (read at arm's length, seated normally), not a bench check. |

## Goal

Make the 3.5in dashboard legible at arm's length in the car. The mechanism is a **type scale in tokens** (there is none today -- 83 hardcoded px in dashboard.css), then larger tiles with fewer facts per card, which pushes the card set back up (4 -> 6). Legibility outranks screen-count on this panel.

## The finding (Iris, so the groom is sized right)

- 480x320 at 3.5in = ~165 PPI = 0.154 mm/px. At ~650mm glance distance the legibility floor is ~34px (comfort) / ~28px (floor). Shipped values are 13-15px, labels 8-11px -- **2-4x under**. The only two elements already >=34px are the two the CIO did NOT complain about (report + arithmetic agree independently).
- **No type-scale lever exists yet** -- `tokens.css` has font families but no size scale; `dashboard.css` has 83 hardcoded px. "Bump the fonts" = 83 edits that drift back. **Tokenize first (US-539), then set the scale (US-540).**

## Stories (full DoD in backlog.json)

| Story | Size | Summary | Gate |
|---|---|---|---|
| US-539 | M | Extract the type scale into tokens.css (closes W-3); replace 83 hardcoded px -- pure refactor, no visual change | none |
| US-540 | L | Set the scale (44/34/26/20/15) + re-lay cards; floor >=34px for driver-must-read; card set 4->6; Health retires | **Atlas** (screen-count + US-482 stage) |
| US-541 | M | Atlas's 3 requests: IMU-always-on Home face, reorder Home.Alerts.System..., auto-rotate-off verify | **Atlas** (IMU-always-on) |
| US-542 | S | Idle-face retirement: STANDBY removed, clock->top bar, DTC-since-key-off -> Alerts card | **Atlas** (cross-card move) |

## Sequencing / gates

- **US-539 before US-540 (hard)** -- tokenize, then set the scale. US-541 is independent; US-542 pairs with US-541#1 (IMU-always-on).
- **Atlas structural design-gate** (Iris filed it 2026-08-08): US-540 screen-count 4->6 + US-482 letterbox-stage; US-541 IMU-always-on (US-508 face); US-542 cross-card move. The rest is presentation, no gate.
- **Reverses part of US-507/508** (the 6->4 consolidation) -- intended, documented here so it does not read as drift.

## Acceptance (in-car, honest)

- Read every card at arm's length, seated normally, in the car -- driver-must-read elements legible (>=34px effective). **Not a bench check.**
- **Unverified caveat (do NOT bake values as final):** the Pi outputs 1080p into a 480x320 native panel; if it downsamples, small text is resampled AND small, pushing the floor UP. Routed to Atlas/Rex. It can only move the floor higher, so it does not block the groom -- but re-verify the 44/34/26/20/15 values on real hardware before declaring them final.

## Queued next (NOT this sprint -- filed / to groom)

- **W-16 sensor prototypes** (Iris, CIO-approved): **P2 Engine card** (MAF arc gauge + vitals -- unblocked, display-only; becomes card 7 in this set; bake the ~2.5s-per-PID step + LTFT-idle rules into acceptance). **BOOST IS DEAD** (INTAKE_PRESSURE unsupported + wired to the MDP/EGR sensor -- no software fix). P3 post-drive review (Atlas analytics contract first). P4 attitude card (small states/imu roll+yaw add).
- F-126 Settings (V0.29.26) knock-on already handled in Iris's design (one key autoRotateS, default off, "applies on restart").
- I-043 / I-044 (splash terminal reason, kiosk XDG_RUNTIME_DIR %U).

## Note

This is the design artifact for F-127 (per PM Rule 4). Iris's mockup is the visual spec; this PRD + backlog stories are the contract.
