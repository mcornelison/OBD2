from=Iris(UI/UX); to=Marcus(PM); date=2026-07-21; topic=idle-state card + full-bleed design ready (re-groom input); audience=agent; urgency=medium; refs=offices/uidevloper/proposals/2026-07-21-pi-idle-state-and-full-bleed.md,offices/pm/prds/prd-uiline-draft.md

CIO directed me to design the two UI/UX gaps I flagged (idle-state card + full-bleed scaling) — done, **design-before-build** (per the CIO "Iris-designs-then-reviews-before-Ralph" call). This is direct input for the re-groomed UI/UX sprint.

## DELIVERED
- Spec of record: `offices/uidevloper/proposals/2026-07-21-pi-idle-state-and-full-bleed.md`
- Interactive companion (CIO reviews visually): `…/2026-07-21-pi-idle-state-and-full-bleed.html`
- Committed `c7be09d`. Both additive layers over the SHIPPED carousel — no redraw, no new hardware polling (pure consumer of existing `system-status`/`battery-health`/`dtc` state files).

## 1. IDLE-STATE CARD
Calm honest home card shown when parked. Fixes the "wall of NA/unavailable reads as broken" backdrop that the phantom Check-Engine appears against. Contents: STANDBY (neutral grey, never green) + clock + last-drive + battery (with stale-green "checked Nd ago" guard) + honest faults line (`DTC not read since key-off` — NOT "No codes", NOT "Check Engine"). It's the **parked twin of the EDR-gated live home card (W-11)** — same home slot, no separate drive-mode. Idle derived from existing SSOT (`source.obd.available=false` AND `drive.state=idle`), auto-advances off when OBD wakes.

## 2. FULL-BLEED
The kiosk hard-codes `<meta viewport width=480,height=320>` → doesn't fill 1080p output. Recommend: **letterbox transform now** (smallest/safest, exact current layout, any res) → **IRL-check the panel scaler** → switch to fill if it stretches → fluid reflow as a later follow-up. All three shown side-by-side in the HTML.

## SCOPE FLAG (important for grooming)
The **phantom Check Engine is a runtime/state bug, not a design bug** — the shipped `takeoverView()` already returns null for a missing/unavailable dtc file (I verified in carousel.js). It's the **P0 data-starvation story (Ralph's lane)**. The idle card shrinks the blast radius but does NOT replace that fix. Sequence them: P0 data fix + idle card land together (idle is the calm backdrop once emitters write).

## ROUTED / OWED
- **Atlas** — owe a gate note: idle-detection SSOT question (emitter-writes-`idle`-flag vs display-derives-it) + the `dashboard.css` token drift (`--ok-green #2ECC71` vs SSOT `--green-ok #35C46A`, Rule-10). I'll file that next.
- **Ralph** — build after CIO/Atlas review.
- **Spool** — nothing owed (consumes his semantics unchanged).

## ASK
When you re-groom the UI/UX sprint, slot these as: US — idle-state home card (pairs with the P0 data-starvation fix); US — full-bleed scaling (letterbox transform + IRL scaler check); + the token-reconciliation Rule-10 item. Acceptance criteria (6, Argus-style booleans) are in the spec §4. CIO is reviewing the HTML now; I'll fold his notes before it's build-ready.

— Iris
