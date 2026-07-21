---
status: superseded-needs-regroom
createdAt: 2026-06-28
createdBy: Marcus (PM)
revisedAt: 2026-07-21
revisedBy: Iris (UI/UX) — CIO-directed re-grounding review
theme: Pi touch-UI line (splash -> carousel dashboard -> DTC viewer)
epic: E-001 (UI/UX Polish)
forksFrom: dev (when groomed; post-Sprint-47)
authoritativeGate: Atlas greenlight 2026-06-19 (inbox 2026-06-19-from-atlas-ui-line-greenlight-plus-alert-deltas.md)
---

# Staging Plan — Pi Touch-UI Line (NOT a frozen PRD)

> **⚠️ RE-GROUNDING BANNER — Iris, 2026-07-21 (CIO-directed).** This plan is
> ~3 weeks stale and **overtaken by events**. Verified against the repo:
> the entire near-term line is **already built and deployed** (all emitters +
> `states_http_server.py` + `dtc_clear.py` in `src/pi/splash/` + `carousel.js`),
> the Atlas greenlight it was waiting for **landed 2026-06-19** (before this file
> was even written), and the owed C-2/C-3 + P1xxx fold is **done** (DTC spec v1.2).
> Sections below are corrected in-place; **stale-original text is struck or marked
> `[STALE 06-28]`**. The real current work is captured in the new
> **"Current reality (2026-07-21)"** section — read that first. Full review +
> evidence: A2AL `offices/pm/inbox/2026-07-21-from-iris-uiline-prd-review.md`.

This was a **grooming staging plan**, not a sprint contract. It captured the
Atlas-sanctioned sequence + build conditions + per-feature story splits so the
real PRD would groom fast once the Atlas design-gate signoffs landed. Those
signoffs have since landed and the line was built ahead of formal grooming —
so this file now needs a **re-groom against build-complete reality**, not a
first groom. Story-level detail gets (re-)authored at grooming time per the
backlog-v2 contract.

## Current reality (2026-07-21 — Iris re-grounding)

The line was **built and deployed ahead of formal grooming.** The gate/spec/fold
work this plan tracks is all resolved; the live problem is a **runtime data
defect**, plus **two new design gaps** and a **process/scope decision** that
postdate this file.

**Built + deployed (verified in `src/pi/splash/` + `specs/UI/dist/`):**
- `states_http_server.py`, `token.py`, `source_availability.py` — the C-1
  "spec-only" runtime **exists**.
- `boot_state_emitter.py` + `shutdown_state_emitter.py` (F-103).
- `system_status_emitter.py` (F-092), `battery_health_emitter.py` (F-097).
- `dtc_emitter.py` **and `dtc_clear.py`** — F-111 incl. the Mode-04 clear the
  DTC spec still lists as "net-new".
- `service_control.py` (System Setup) · `specs/UI/dist/dashboard-pi/carousel.js`.

**The actual current blocker (P0) — data starvation, not a gate.** The carousel
is deployed but **starves for data**: the emitters aren't writing their state
files on the Pi, so the kiosk renders a **phantom "Check Engine"**. This is a
deploy/runtime gate (cf. the "deploy validation is a distinct gate" lesson),
NOT a design or Atlas-signoff gate. It is the thing a re-groomed sprint must
open on.

**Two new design gaps (Iris-flagged; not in the 06-28 plan):**
- **No calm idle-state card** — nothing sensible to show when the car is off /
  no live data. Contributes to the phantom-alert feel.
- **No full-bleed / viewport scaling** — Pi outputs 1080p but cards are fixed
  480×320. Needs responsive full-bleed layout.

**Scope + process decision (CIO):** **responsive full-bleed + full-scope UI
sprint**, run **Iris-designs-then-reviews-before-Ralph** (design lands + gets
reviewed before dev builds).

## Readiness (as of 2026-06-28 — CORRECTED 2026-07-21)

| Feature | Spec | Atlas gate | Build state (2026-07-21) |
|---|---|---|---|
| **F-103** Pi splash (boot+shutdown) | `docs/superpowers/specs/2026-05-26-b103-splash-animation-design.md` (v1.2) | ✅ ACKed | **BUILT + deployed** (`boot_state_emitter.py`, `shutdown_state_emitter.py`, splash HTML) |
| **F-092** System Status card + **F-097** Battery Health card (carousel shell) | `docs/superpowers/specs/2026-06-05-pi-touch-carousel-dashboard-f092-f097-design.md` | ✅ **GREEN-LIT 2026-06-19** (was "pending" — the greenlight predates this file; table was never updated) | **BUILT + deployed** (`system_status_emitter.py`, `battery_health_emitter.py`, `carousel.js`) — **but data-starved at runtime (P0)** |
| **F-111** DTC viewer + Mode-04 clear (Card 5) | `docs/superpowers/specs/2026-06-05-pi-dtc-check-engine-viewer-clear-design.md` (**v1.2** — C-2/C-3 + P1xxx folded 2026-06-19) | ✅ **GREEN-LIT 2026-06-19** (CONDITIONAL PASS, no BLOCK) | **BUILT** (`dtc_emitter.py`, `dtc_clear.py`) |

> **[STALE 06-28]** ~~So today only F-103 is groomable. The carousel + DTC viewer
> are blocked on two outstanding Atlas design-gate signoffs; Iris sends the formal
> groom-ready pointers on his nod. Iris also owes pre-groom-ready: fold C-2/C-3 +
> Spool's P1xxx into the DTC + dashboard specs.~~
> **CORRECTION:** Atlas GREEN-LIT the whole near-term line **2026-06-19**
> (`inbox/2026-06-19-from-atlas-unified-alert-gate-ruling.md`). The owed fold is
> **DONE** — DTC spec is **v1.2 (2026-06-19)**, which folded C-2 (KOEO Mode 03(+07),
> `drive_id=NULL`), C-3 (Mode 02 dead → `realtime_data` fallback), and Spool's DSM
> P1xxx table. (C-2/C-3 don't apply to the F-092/F-097 dashboard spec, so "+ dashboard
> specs" overstated the outstanding work.)

## Build sequence (Atlas greenlight 2026-06-19) — RETROSPECTIVE as of 2026-07-21

This sequence was **followed and is now built.** Kept for the record; it is no
longer forward-looking work.

1. ✅ **F-103** (chromium kiosk + `eclipse-states-http` + token SSOT + `HEALTHY_YIELD`) — built.
2. ✅ Carousel shell (kiosk + swipe-nav + persistent top bar + state-server extension) — built (`carousel.js`).
3. ✅ **F-092** System Status card + **F-097** Battery Health card (+ emitters) — built (**runtime data-starved — P0**).
4. ✅ System Setup + polkit service-control — built (`service_control.py`).
5. ⏳ pygame `status_display.py` sunset (parity-gated) — verify against src/ at re-groom.
6. ✅ **F-111** DTC Card 5 (emitter + takeover + Alerts/detail + Mode-04 clear) — built (`dtc_emitter.py`, `dtc_clear.py`).

## Standing build conditions — STATUS (2026-07-21)

- **C-1** F-103 first — ✅ **SATISFIED.** The runtime exists in `src/pi/splash/`
  (`states_http_server.py` + emitters). The "spec only today" caveat is obsolete.
- **C-2** KOEO capture path independent of DriveDetector (key-on Mode 03(+07),
  `drive_id=NULL`) — ✅ **folded into DTC spec v1.2** (DTC-A9); verify the built
  `dtc_emitter.py` actually implements the KOEO read at re-groom (this is a prime
  suspect for the runtime data-starvation defect).
- **C-3** Mode 02 confirmed dead on MD326328 → `realtime_data` fallback — ✅
  **folded (spec v1.2, A-4 resolved).**
- **Rule-10 DoD** — ⚠️ **STILL BINDING + verify.** Confirm the shipped state-server
  extension, emitters, Mode-04 path, and `--green-ok`/token each landed with matching
  `specs/architecture.md` (+ `specs/UI/`) updates. If the build outran the docs,
  the re-groom sprint carries the doc reconciliation.

## Per-feature story splits (Iris-proposed; author at grooming)

> **[STALE 06-28 — retrospective]** These greenfield "build the feature" splits
> describe work that is **now built**. They remain useful as a map of what shipped,
> but a re-groom sprint's stories should be framed as **"make-it-render-truthfully"**
> (fix data starvation, add idle-state card, add full-bleed scaling, reconcile
> Rule-10 docs), NOT re-build. See "Current reality" above + the re-groom order below.

- **F-103** (spec M-1): US-A boot splash (+ `eclipse-boot-state.service` [A-1] + `eclipse-states-http.service` [A-4]); US-B shutdown splash (+ ShutdownSequencer phase-emit [A-2] + **Rule-10 §10.6 architecture.md in-sprint, Atlas BLOCKs otherwise**); US-C deploy integration (deploy-pi.sh + version.txt + WARN-not-BLOCK); US-D defects D-1/2/3 + install-time checks.
- **F-092/F-097** (spec §9 M-1): US-A carousel shell (kiosk + swipe + top bar + state-server extension); US-B F-092 System Status card + emitter (the I-033 BT-visibility fix); US-C F-097 Battery Health card + emitter (+ Spool semantics); US-D pygame sunset. Rule-10: A-2/A-3 architecture.md in-sprint.
- **F-111** (spec §10 M-1): US-A dtc emitter + state-server endpoint + static-table loader/sync; US-B takeover + severity-styled ribbon; US-C Alerts card (hero+list) + detail (freeze-frame + severity-gated fix + trust badge); US-D Clear-DTC Mode-04 path + gate + confirm + re-read + session-lock (load-bearing, pairs w/ Atlas A-1); US-E freeze-frame capture-or-honest-fallback.

## Parked (NOT in this line — EDR-epic, Atlas 2026-06-19)

- **DELTA-1 Unified Alert Layer** (arbiter merging DTC + live engine-protection alerts) — built when the live engine-protection source lands (EDR epic, A-14). Near-term has one alert source (DTC) → nothing to arbitrate.
- **DELTA-2 Live-Instrument home card** (compass/gear/grade/g-force from 9-DoF IMU) — presupposes the IMU pipeline (sensors ~end-June→mid-July, A-14). EDR-epic slice.

## Recommended RE-GROOM order (2026-07-21 — Iris)

> Supersedes the [STALE 06-28] "F-103 now / then carousel+DTC" order below — both
> are built. Frame the sprint as **make the deployed line render truthfully**, one
> combined full-scope V0.3x responsive-UI sprint, **Iris-designs-then-reviews-before-Ralph**:
>
> 1. **P0 — data-starvation defect.** Root-cause why the deployed emitters aren't
>    writing state files on the Pi (→ phantom "Check Engine"). Prime suspects: the
>    C-2 KOEO read path + emitter service wiring / deploy. This is the gate to any
>    "carousel works" claim.
> 2. **Responsive full-bleed scaling** (480×320 fixed → 1080p viewport) + **idle-state
>    card** — Iris designs first, reviewed before Ralph builds.
> 3. **Rule-10 doc reconciliation** — confirm the shipped runtime's `specs/architecture.md`
>    + `specs/UI/` updates exist; carry any gap as sprint DoD.
> 4. **pygame `status_display.py` sunset** — verify parity + retire (seq step 5, unconfirmed).
> 5. Keep **DELTA-1 / DELTA-2 parked** (EDR-epic, below) — unchanged.

### [STALE 06-28] Original grooming order (both items now built)

1. ~~**F-103 now** if CIO wants UI progress before the other gates clear — groom-ready, required-first runtime.~~
2. ~~**Carousel + DTC** when Atlas signs the two design-gates + Iris files groom-ready.~~

## Backlog state (reconciled 2026-06-28)
- F-097 title pivoted to "Battery Health" (was "Drain ladder state UI"; renamedFrom intent, same ID).
- F-111 created (DTC viewer + Mode-04 clear) under E-001 — new backlog home for the Card-5 surface.
- F-109 re-framed: Mode 02 dead on MD326328 → realtime_data fallback (C-3).
