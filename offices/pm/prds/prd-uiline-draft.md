---
status: staging-plan
createdAt: 2026-06-28
createdBy: Marcus (PM)
theme: Pi touch-UI line (splash -> carousel dashboard -> DTC viewer)
epic: E-001 (UI/UX Polish)
forksFrom: dev (when groomed; post-Sprint-47)
authoritativeGate: Atlas greenlight 2026-06-19 (inbox 2026-06-19-from-atlas-ui-line-greenlight-plus-alert-deltas.md)
---

# Staging Plan — Pi Touch-UI Line (NOT a frozen PRD)

This is a **grooming staging plan**, not a sprint contract. It captures the
Atlas-sanctioned sequence + build conditions + per-feature story splits so the
real PRD grooms fast **once the outstanding Atlas design-gate signoffs land**.
Story-level detail (goal/DoD/validation/conditional) gets authored at grooming
time per the backlog-v2 contract; this file is the map.

## Readiness (the gating reality)

| Feature | Spec | Atlas gate | Groom-ready? |
|---|---|---|---|
| **F-103** Pi splash (boot+shutdown) | `docs/superpowers/specs/2026-05-26-b103-splash-animation-design.md` (v1.2) | ✅ ACKed | **YES** — Iris filed groom-ready 2026-06-03 |
| **F-092** System Status card + **F-097** Battery Health card (carousel shell) | `docs/superpowers/specs/2026-06-05-pi-touch-carousel-dashboard-f092-f097-design.md` | ⏳ filed, **pending signoff** | No — groom-ready follows Atlas nod |
| **F-111** DTC viewer + Mode-04 clear (Card 5) | `docs/superpowers/specs/2026-06-05-pi-dtc-check-engine-viewer-clear-design.md` | ⏳ filed, **pending signoff** | No — groom-ready follows Atlas nod |

**So today only F-103 is groomable.** The carousel + DTC viewer are blocked on
two outstanding Atlas design-gate signoffs (both load-bearing); Iris sends the
formal groom-ready pointers on his nod. Iris also **owes pre-groom-ready**: fold
C-2/C-3 + Spool's P1xxx severity/fix subset into the DTC + dashboard specs.

## Build sequence (Atlas greenlight 2026-06-19 — do not reorder)

1. **F-103** (chromium kiosk + `eclipse-states-http` + token SSOT + `HEALTHY_YIELD`) — **must be first; everything below assumes its runtime exists.**
2. Carousel shell (kiosk + swipe-nav + persistent top bar + state-server extension)
3. **F-092** System Status card + **F-097** Battery Health card (+ their emitters)
4. System Setup + polkit service-control
5. pygame `status_display.py` sunset (parity-gated)
6. **F-111** DTC Card 5 (emitter + KOEO capture + takeover + Alerts/detail + Mode-04 clear) — **LAST**

## Standing build conditions (carry into the sprint contract)

- **C-1** F-103 first (spec only today; don't scope cards as if the runtime exists).
- **C-2** KOEO capture path independent of DriveDetector (key-on Mode 03(+07) read, `drive_id=NULL`) — or the DTC viewer is blank at key-on.
- **C-3** Mode 02 confirmed dead on MD326328 → build the `realtime_data` fallback; no Mode 02 capture path (see F-109, re-framed).
- **Rule-10 DoD** — the state-server extension, emitters, the Mode-04 path, and the `--green-ok`/token each land with matching `specs/architecture.md` (+ `specs/UI/`) updates **in-sprint**.

## Per-feature story splits (Iris-proposed; author at grooming)

- **F-103** (spec M-1): US-A boot splash (+ `eclipse-boot-state.service` [A-1] + `eclipse-states-http.service` [A-4]); US-B shutdown splash (+ ShutdownSequencer phase-emit [A-2] + **Rule-10 §10.6 architecture.md in-sprint, Atlas BLOCKs otherwise**); US-C deploy integration (deploy-pi.sh + version.txt + WARN-not-BLOCK); US-D defects D-1/2/3 + install-time checks.
- **F-092/F-097** (spec §9 M-1): US-A carousel shell (kiosk + swipe + top bar + state-server extension); US-B F-092 System Status card + emitter (the I-033 BT-visibility fix); US-C F-097 Battery Health card + emitter (+ Spool semantics); US-D pygame sunset. Rule-10: A-2/A-3 architecture.md in-sprint.
- **F-111** (spec §10 M-1): US-A dtc emitter + state-server endpoint + static-table loader/sync; US-B takeover + severity-styled ribbon; US-C Alerts card (hero+list) + detail (freeze-frame + severity-gated fix + trust badge); US-D Clear-DTC Mode-04 path + gate + confirm + re-read + session-lock (load-bearing, pairs w/ Atlas A-1); US-E freeze-frame capture-or-honest-fallback.

## Parked (NOT in this line — EDR-epic, Atlas 2026-06-19)

- **DELTA-1 Unified Alert Layer** (arbiter merging DTC + live engine-protection alerts) — built when the live engine-protection source lands (EDR epic, A-14). Near-term has one alert source (DTC) → nothing to arbitrate.
- **DELTA-2 Live-Instrument home card** (compass/gear/grade/g-force from 9-DoF IMU) — presupposes the IMU pipeline (sensors ~end-June→mid-July, A-14). EDR-epic slice.

## Recommended grooming order (PM)

1. **F-103 now** if CIO wants UI progress before the other gates clear — it's groom-ready, it's the required-first runtime, and it unblocks everything else. Author 4 stories from spec §9 (18 IRL + 5 synthetic acceptance criteria as validation source).
2. **Carousel + DTC** when Atlas signs the two design-gates + Iris files groom-ready (with C-2/C-3 + Spool severity folded). Likely one combined V0.3x UI sprint, sequenced shell → cards → Card 5.

## Backlog state (reconciled 2026-06-28)
- F-097 title pivoted to "Battery Health" (was "Drain ladder state UI"; renamedFrom intent, same ID).
- F-111 created (DTC viewer + Mode-04 clear) under E-001 — new backlog home for the Card-5 surface.
- F-109 re-framed: Mode 02 dead on MD326328 → realtime_data fallback (C-3).
