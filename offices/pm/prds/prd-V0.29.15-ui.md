---
sprint: 61
version: V0.29.15
status: draft
createdAt: 2026-07-21
createdBy: Marcus (PM)
selectedStories: [US-480-a, US-480-b, US-481, US-482, US-483, US-484, US-485, US-486, US-487]
pmFinalSizing: "APPROVED 2026-07-21 (Marcus). 5-dim sizing run; US-480 split (2 Red: files+concerns) -> US-480-a (wire emitters to run) + US-480-b (deploy-install + reboot-persistence + Rule-10), zero info loss. 8 stories, all Green (US-481/483 accepted single-Yellow). Under the 10-story limit. Dispatch order rec: ungated Green first (US-482/485/486/481) while Atlas rules the run-model (Q-1/US-480-a) + Q-2/US-484 + Q-4/US-483."
forksFrom: dev @ (recorded at prd_to_sprint.py conversion)
sprintJsonPath: offices/ralph/sprint.json
epic: E-001 (UI/UX Polish) + F-080 (US-486 startup_log guard)
feature: F-121 (Pi dashboard render-truthfully) + F-080
theme: Make the deployed Pi dashboard render truthfully -- wire the emitters, calm idle state, full-bleed letterbox, light-feed, token + startup_log cleanup
designSpec: offices/uidevloper/proposals/2026-07-21-pi-idle-state-and-full-bleed.md (Iris, REVIEWED + CIO-locked 9da4af5)
atlasReview: "PASS 2026-07-21 (inbox 2026-07-21-from-atlas-f121-...). No BLOCK. Rulings folded into backlog: Q-1 run-model = OBD emitters ORCHESTRATOR-INVOKED (not standalone units -> would reopen the port + reintroduce the A-17 race) + idle-SSOT (b) emitter-writes-boolean; Q-2 token = green name+value fork + text-primary SSOT-add + critical-red SAFETY item (Spool value + Atlas gate + repoint STOP off brand-red); Q-4 light contract APPROVED (build curve+fallback now, live lux EDR-gated). GAP CLOSED: the phantom-CE was STALE deployed carousel.js (deploy drift), already resolved by the V0.29.14 redeploy (Pi /opt/dashboard/carousel.js now md5-matches dev) -> US-480-a acceptance re-grounded to measure emitter-wiring, not the phantom. Added US-487 (US-479 pre-drive hardening, Atlas post-hoc). Issue-1 §3.5 = Atlas DONE (45a54d1)."
reclaims: "V0.29.15 was the shelved F-120 BT-reliability slot; reclaimed for this UI sprint (F-120 dead)."
---

# PRD: V0.29.15 -- Pi dashboard render-truthfully (UI/UX sprint)

| Field | Value |
|---|---|
| Version | V0.29.15 (patch on `dev`; reclaims the shelved F-120 slot) |
| Theme | The F-092/097/111 carousel is **built + deployed but renders wrong** on the real Pi. Make it render truthfully -- additive layers over the shipped carousel, **no redraw**. |
| Status | DRAFT -- Iris design REVIEWED + CIO-locked; routed to Atlas for the design-gate + 3 data-contract nods |
| Lane | Pi UI/dashboard + emitter runtime + deploy; **load-bearing** (emitter run-model + token SSOT) |
| Stories | US-480..485 under **F-121** + US-486 under **F-080** |
| Deploy + validate | Deploys from `dev`; full-bleed + idle validate on the real 1080p Pi; live data validates on the same drive-35 window |

## Context

CIO directed a UI sprint (Pi on the bench). We ran the live carousel: it renders **tiny** (corner of a 1080p output) and shows a **phantom "Check Engine"** with the car off. Diagnosis (grounded):
- **P0 data starvation (root cause, PM-verified on the live Pi):** the F-092/097/111 emitter *code* shipped but was **never wired to execute** -- no service unit, no orchestrator invocation, no deploy install. Only `eclipse-boot-state.service` runs, so `/run/eclipse-obd/states/` holds only `boot-state`. The cards starve; the shipped `takeoverView()` (which correctly returns null for a missing dtc file) never gets data to hide the static placeholder. **This is Ralph's lane, not a design bug.**
- **Two design gaps** Iris flagged + designed + CIO-locked 2026-07-21 (`9da4af5`): a calm **idle-state home card**, and **full-bleed LETTERBOX** scaling. Iris spec of record: `offices/uidevloper/proposals/2026-07-21-pi-idle-state-and-full-bleed.md`.
- CIO scope decision: **one big full-scope UI sprint** (not split). BT-reliability F-120 shelved.

## Stories (full DoD/validationCriteria in `backlog.json`)

| Story | Type | Size | Summary | Gate |
|---|---|---|---|---|
| **US-480** | issue | M | **P0 emitter-execution wiring** -- wire system-status/battery-health/dtc emitters to RUN + write state (service units / orchestrator) + **deploy-installs it**; states dir populates on a clean boot; phantom Check Engine disappears. The gate to "carousel works." | Atlas run-model ruling (rides Iris Q-1) |
| **US-481** | normal | M | **Idle-state home card** -- calm honest parked view (STANDBY grey, never green; last-drive / battery-with-age / honest faults `DTC not read since key-off`); auto-advances off when OBD wakes; a real STOP code still wins. Pairs with US-480. | existing-SSOT consumer (no data gate) |
| **US-482** | normal | S | **Full-bleed LETTERBOX** -- `#stage{480x320}` scaled uniformly to fill the panel + resize handler; no `dashboard.css` layout rewrite; black bars. Own story, **not blocked behind P0**. | presentation-only (no gate); IRL Pi check |
| **US-483** | normal | M | **Light-feed brightness consumer** -- auto-dim from a `light` lux state file (pure consumer) + **honest fixed fallback** (no fake "auto") + **alarm floor** (never dim a STOP below legible). Live lux EDR-gated (W-9). | **Atlas Q-4** (light state-file contract) |
| **US-484** | tech-debt | S | **Rule-10 token reconciliation** -- `dashboard.css :root` drift vs `specs/UI/tokens.css` SSOT (`--ok-green`→`--green-ok #35C46A`, etc.). | **Atlas Q-2** (SSOT token additions) |
| **US-485** | tech-debt | S | **pygame `status_display.py` sunset** -- verify carousel parity (preserve US-264 VCELL rule) then retire the dead path. | — |
| **US-486** | issue | S | **startup_log schema guard fix (F-080)** -- US-419 shipped an 8th `data_quality` column but the US-263 guard asserts 7 → 2 red tests. Bump to 8 (don't relax); update US-263 spec. Ralph-filed Issue 2, Sprint 60. | quick PM/Atlas "canonical vs separate table" nod |

## Sequencing
1. **US-480 (P0)** first -- the data fix gates any "carousel works" claim. US-481 (idle) pairs with it (idle is the calm backdrop once emitters write).
2. **US-482 (letterbox)** parallel -- independent, own small story.
3. US-483/484 gated on Atlas Q-4/Q-2; US-485/486 independent.

## Pre-dispatch gates (Atlas)
Iris routed 3 data-contract questions to Atlas (her `architect/inbox` note): **Q-1** idle-detection SSOT / emitter run-model (rides US-480), **Q-2** token drift (US-484), **Q-4** `light` state-file contract (US-483). US-481 (idle card) + US-482 (letterbox) are presentation / existing-SSOT and don't strictly need his gate -- they can groom ahead. On Atlas's PRD review + those nods → generate `sprint.json` → dispatch.

## Not in this sprint
- **Issue 1 (`I-arch-spec-3.5`)** -- a `specs/architecture.md §3.5` doc-update owed for US-474 (add the DTC caller to the threading-model wrapper list + reference the new test). `specs/` is read-only for Ralph → **routed to Atlas**, not a Ralph story.
- Live-instrument home card (W-11) + unified alert layer (DELTA-1) -- EDR-gated, parked.
