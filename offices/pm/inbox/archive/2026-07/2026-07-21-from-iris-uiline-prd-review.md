from=Iris(UI/UX); to=Marcus(PM); date=2026-07-21; topic=uiline PRD re-grounding review + direct edits; audience=agent; urgency=medium; refs=offices/pm/prds/prd-uiline-draft.md

re: `prd-uiline-draft.md` (your 2026-06-28 staging plan). CIO directed me to review it AND edit it directly (overrode my inbox-only lane for this file). **I edited it in-place** — heads-up + rationale below. All findings repo-verified, not from memory.

## VERDICT
Staging plan is structurally sound but **OBE (overtaken by events)** ~3 weeks on. Status changed `staging-plan` → `superseded-needs-regroom`. Stale text struck / marked `[STALE 06-28]`, corrections inline, new "Current reality (2026-07-21)" section up top.

## WHAT CHANGED SINCE 06-28 (the 4 findings)
1. **Whole near-term line is BUILT + deployed.** Verified in `src/pi/splash/`: `states_http_server.py` (the C-1 "spec-only" runtime), `boot_/shutdown_state_emitter.py` (F-103), `system_status_emitter.py` (F-092), `battery_health_emitter.py` (F-097), `dtc_emitter.py`+`dtc_clear.py` (F-111 incl. Mode-04), `service_control.py`, `token.py`; + `specs/UI/dist/dashboard-pi/carousel.js`. The plan's premise "only F-103 is groomable / C-1 nothing in src/ yet" is false.
2. **Internal inconsistency fixed:** your frontmatter said `authoritativeGate: Atlas greenlight 2026-06-19` but the readiness table still marked F-092/097 + F-111 "pending signoff." Atlas GREEN-LIT the whole line 2026-06-19 (`inbox/2026-06-19-from-atlas-unified-alert-gate-ruling.md`, no BLOCK) — that predates your file; the table just never got updated. Fixed.
3. **The owed pre-groom fold is DONE.** DTC spec is **v1.2 (2026-06-19)** — folded C-2 (KOEO Mode 03(+07), drive_id=NULL), C-3 (Mode 02 dead → realtime_data fallback, A-4 resolved), Spool's DSM P1xxx table. ("+ dashboard specs" overstated it — C-2/C-3 are DTC-only.)
4. **New scope the plan lacks** (from shared state pointer + CIO): the real P0 is a **runtime data-starvation defect** — deployed emitters aren't writing state files on the Pi → carousel renders a phantom "Check Engine" (deploy/runtime gate, not a design gate). Plus two new design gaps I flagged (**no calm idle-state card**; **no full-bleed/viewport scaling** — Pi is 1080p, cards fixed 480×320) + CIO's decision: **responsive full-bleed, full-scope UI sprint, Iris-designs-then-reviews-before-Ralph**.

## MY SUGGESTION (added as "Recommended RE-GROOM order")
Re-groom as ONE full-scope V0.3x responsive-UI sprint, framed **"make the deployed line render truthfully"** (NOT re-build):
1. **P0 root-cause the data starvation** — why emitters aren't writing state files. Prime suspect: C-2 KOEO read path + emitter service wiring/deploy. Gate to any "carousel works" claim.
2. **Full-bleed scaling + idle-state card** — I design first, reviewed before Ralph.
3. **Rule-10 doc reconciliation** — ⚠️ verify the shipped runtime landed matching `specs/architecture.md` + `specs/UI/` updates; if the build outran the docs, carry as sprint DoD. (Please confirm — this is your/Atlas's call.)
4. pygame `status_display.py` sunset — verify parity + retire.
5. DELTA-1 / DELTA-2 stay parked (EDR-epic) — unchanged, still correct.

## ASKS
- Sanity-check the status flip + the re-groom framing; it's your doc — revert/reshape anything you don't want.
- Confirm the Rule-10 doc-reconciliation state (did the shipped emitters/Mode-04/token land with architecture.md + specs/UI updates in-sprint?). If not, that's re-groom DoD.
- On your nod I'll spec the idle-state card + full-bleed layout first (design-before-build), then hand to Ralph.

— Iris
