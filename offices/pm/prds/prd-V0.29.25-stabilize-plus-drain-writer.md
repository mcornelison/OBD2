---
sprint: 70
version: V0.29.25
status: draft
createdAt: 2026-08-02
createdBy: Marcus (PM)
selectedStories: [US-522, US-523, US-524, US-525, US-526, US-527, US-528, US-529]
forksFrom: dev @ (recorded at prd_to_sprint.py conversion; forks from dev AFTER V0.29.24 deployed)
sprintJsonPath: offices/ralph/sprint.json
epics: E-001 (UI/UX Polish) + E-OPS (F-119 hygiene)
features: F-124 (Pi UI carousel), F-103 (splash), F-123 (dashboard truthfulness wiring / battery health), F-119 (ops hygiene)
theme: "FULL sprint. STABILIZE the V0.29.24 deploy (Pi UI froze on the bench + splash not rendering) + land the CARRIED battery-health drain writer. Headline: Atlas-RCA'd chromium GPU command-buffer freeze (A-16 family) -- the deployed UI is unusable under sustained use until the kiosk GPU-raster fix lands. Plus splash render fix (I-042), US-504a drain writer + US-504b depth-gate remap (BL-028/TD-074), and 2 branch-red cleanups (I-041, TD-073)."
atlasReview: "PENDING. Design-gate items for Atlas's PRD review: (1) US-522 kiosk GPU-config fix (his RCA #1, he offered to design-gate); (2) US-525 splash read (the 401 bare-route question -- confirm bug vs by-design before touching the auth/route layer); (3) US-526 orphan-policy A-vs-C CONFIRM (Spool's depth-gate ruling already narrowed it -- option B disqualified, reaper hygiene-only; Ralph recommends C)."
---

# PRD: V0.29.25 -- stabilize the V0.29.24 deploy + carried drain writer

| Field | Value |
|---|---|
| Version | V0.29.25 (patch on dev; forks after V0.29.24 deployed) |
| Origin | V0.29.24 deployed 2026-08-02 but is NOT validated: UI froze on the bench (Atlas RCA: chromium GPU command-buffer hot-loop) + boot/shutdown splash did not render (I-042). Plus the carried US-504a drain writer (BL-028) whose gating rulings have now landed. |
| Stories | US-522..US-529 -- 8, all bench/unit-validatable (no car needed except the drain-writer's live folds into the same engine-on drive) |
| Deploy | from dev; bench-validated (GPU freeze gone + splash renders); US-526 live-folds into the BL-025 engine-on drive |

## Why this sprint (context)

V0.29.24 shipped 10/11 and deployed to both targets, but the first sustained on-Pi use surfaced two display regressions and left one story carried:

1. **UI freeze (HIGH).** Atlas RCA (CONFIRMED): chromium's GPU process lost its command-buffer context and hot-loops on `AllocateRingBuffer()` (~6M errors/boot, no crash, no recovery) -> renderer + GPU-process CPU pegged -> frozen display. Cause: the Pi 5 v3d GPU (64 MiB CMA) driving the animated carousel with **GPU rasterization ON** + permanent composited layers + two always-on `infinite` CSS animations. **A-16 family: renders-on-desktop != survives the Pi's GPU.** Live-mitigated by a dashboard restart; recurs under sustained use until fixed.
2. **Splash not rendering (I-042).** Neither boot nor shutdown splash appeared. PM evidence: the state server returns 401 on bare routes `/boot` `/shutdown` (200 on `/` and `/shutdown.html`); US-501's `_injectHtml` change is the prime suspect. Boot splash also self-closes at HEALTHY_YIELD (US-494) and may flash too fast to see.
3. **Carried US-504a** (drain writer) -- both gating rulings have now landed (Spool depth gate + Atlas orphan-policy narrowed to A-vs-C), so it is ready to build.

## Stories (full DoD/validationCriteria in backlog.json)

| Story | Parent | Size | Summary | Gate |
|---|---|---|---|---|
| US-522 | F-124 | S | Kiosk GPU-raster fix -- drop `--enable-gpu-rasterization` (kills the freeze class) | **Atlas design-gate** (RCA #1) |
| US-523 | F-124 | M | Kiosk watchdog -- auto-restart eclipse-dashboard on renderer wedge (honest-instrument) | none |
| US-524 | F-124 | S | Raise CMA to 256M -- GPU headroom (complements #1, not standalone) | none (box-config boundary in conditionalOutcome) |
| US-525 | F-103 | M | Splash render fix -- boot visibility + shutdown 401 route | **Atlas read** (401 by-design vs bug) |
| US-526 | F-123 | M | US-504a production drain writer (depth-gate, option C, reaper-NULL trap) | **Atlas orphan-policy A-vs-C confirm** |
| US-527 | F-123 | S | US-504b verdict band-remap to depth gate (degraded/replace reachable) | Spool [EXACT] band values (429a3ed) |
| US-528 | F-123 | S | I-041 fix -- system_status_emitter exact-shape tests + pin lastDrive | none |
| US-529 | F-119 | S | TD-073 fix -- ralph promise-tag contract (prompt.md <-> ralph.sh) | none |

## Sequencing / gates

- **US-522 is the headline** -- the deployed UI is unusable under sustained use until it lands. It is small and doubles as the hypothesis test (freeze gone with GPU raster off = cause confirmed). US-523 (watchdog) is defense-in-depth behind it; US-524 (CMA) is optional headroom.
- **US-526 + US-527 land together** -- US-527's depth-gate remap is latent until US-526's writer produces qualifying rows; splitting them risks a verdict that silently cannot degrade (fails toward reassurance). Iris's page-side animation fix (Atlas RCA #3) is routed by Atlas directly, not a Ralph story here.
- **US-528 + US-529** clear the two branch-red cleanups that would otherwise trip the integration gate (both pre-existing on the V0.29.24 branch, filed I-041 + TD-073).

## Open gates for Atlas's PRD review (design-gate)

1. **US-522** -- Atlas offered to design-gate the kiosk GPU-config change.
2. **US-525** -- confirm whether the 401 on bare routes is by-design (only `*.html` served) or a US-501 regression, before touching the route/auth layer.
3. **US-526** -- confirm orphan-policy A-vs-C (Spool's depth gate already disqualified option B + demoted the reaper to hygiene-only; Ralph recommends C).

## Validation (bench-gated; no car except the drain-writer live-fold)

- **Freeze:** under sustained carousel navigation, `journalctl -u eclipse-dashboard | grep -c AllocateRingBuffer` ~0 + chromium CPU low over a multi-minute session.
- **Splash:** reboot -> boot splash visibly shown then hands off; shutdown -> reverse splash renders.
- **Drain writer:** an AC<->battery transition writes real vcell/soc + runtime_seconds; an interrupted drain leaves an orphan with `runtime_seconds` NULL (never fabricated). Live fold: the BL-025 engine-on drive.
- **Verdict:** seeded depth-band rows -> degraded + replace reachable.
- **Cleanups:** tests/pi/splash green (I-041); promise-tag lint green (TD-073).

## Deferred / not in this sprint

- Iris page-side animation gating (Atlas RCA #3) -- Atlas routes to Iris directly.
- F-125 altitude DISPLAY (US-519/520) + real GPS (US-516) -- Spool sigma-sizing / hardware TBD (not ordered).
- F-111 DTC viewer -- groom-ready, deferred to keep this sprint focused on stabilization.

## Action items (human/CIO, not sprint stories)

- **BL-025 engine-on validation drive** (car + Spool) -- still owed; closes capture + validates US-512/US-526 live.
- **cma=256M** -- if US-524 finds it outside deploy write-scope, CIO applies the one-line boot-config change.
