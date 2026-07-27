---
sprint: 63
version: V0.29.17
status: draft
createdAt: 2026-07-27
createdBy: Marcus (PM)
selectedStories: [US-488, US-489, US-490, US-491]
forksFrom: dev @ (recorded at prd_to_sprint.py conversion)
sprintJsonPath: offices/ralph/sprint.json
epic: E-001 (UI/UX Polish)
feature: F-121 (Pi dashboard render-truthfully)
theme: UI polish + finish the alarm-red cleanup -- the ready-now sprint (no IMU, no heavy gates)
designSpecs: offices/uidevloper/proposals/2026-07-27-pi-ui-polish.md (Iris, CIO-locked) + Spool TD-067 ruling 2026-07-27
atlasReview: "Presentation-only + Spool-ruled -- carry F-121 PASS. Only gate: the --destructive token (US-488 surfaces #7/#8) -- Atlas Rule-10, routed with the live-cards asks. The 8 other TD-067 surfaces + all 3 polish stories need no gate."
---

# PRD: V0.29.17 -- UI polish + alarm-red cleanup (the ready-now sprint)

| Field | Value |
|---|---|
| Version | V0.29.17 (patch on `dev`) |
| Theme | The parts of the "full UI" push that are **buildable now** -- no IMU wiring, no heavy Atlas rulings. Polish the shipped surfaces + finish the brand-vs-alarm cleanup. |
| Status | DRAFT -- Iris polish CIO-locked; Spool TD-067 ruling complete |
| Lane | Pi dashboard CSS/JS; presentation + safety-token routing |
| Stories | US-488, US-489, US-490, US-491 under **F-121** |
| Deploy + validate | Deploys from `dev`; validated on the real 480×320 panel |

## Why this sprint now

Iris + Spool delivered their parallel design work while the IMU gets wired. Their **live-motion** work (live card, unified alert) is designed + CIO-locked but **build-gated** on the IMU wiring (tonight) + Atlas contract rulings (Q-A/Q-B/Q-C). Everything **else** they produced needs **no hardware and no heavy gates** -- so it ships now as a full sprint while the live-cards line unblocks:

- **Iris polish (P-1/P-2/P-3)** -- presentation-only over shipped state, CIO-locked decisions, no Atlas gate.
- **Spool TD-067 ruling** -- concrete per-surface classification; 8 of 10 surfaces + the tier-aware refactor need no gate.

## Stories (full DoD/validationCriteria in `backlog.json`)

| Story | Type | Size | Summary | Gate |
|---|---|---|---|---|
| **US-488** | tech-debt | S | **TD-067 alarm-red sweep** per Spool's ruling: 5→amber, 1→critical-red (battery TRIGGER), 1→tier-aware `.detail-directive`, 2→new `--destructive` (Mode-04 confirm). "Red = danger, one meaning only." | 8 surfaces + refactor: none. #7/#8: `--destructive` token (Atlas) |
| **US-489** | normal | S | **Polish P-1** — System Status glanceability: honest summary line + 2×2 tile grid + per-tile status dots. No new data. | none |
| **US-490** | normal | S | **Polish P-2** — context-aware `⋮` (CIO-locked Option C): `⋮` parked-only, hidden while driving; 5s long-press always. No accidental menu in motion. | none |
| **US-491** | normal | S | **Polish P-3** — DTC detail hierarchy: directive-first for 🔴/🟡, carded sections, ≥40px Back. Typographic only; zero gating/safety change. | none |

## Sequencing
- All four are independent + small; any order. US-488's 8 no-gate surfaces + the tier-aware refactor build now; its 2 `--destructive` surfaces wait on the token (folded into the same Atlas launch as the live-cards rulings -- likely gated before Ralph reaches them).

## Not in this sprint (the live-cards line -- Sprint B, gated)
- **US-478** IMU bring-up + `states/imu` derived-field bridge -- gated on the CIO wiring the board (AI-005, tonight) + Atlas Q-A (derived-field contract).
- **Live-instrument card (W-11)** -- Iris CIO-locked; build after US-478 + Atlas Q-A/Q-B (transport).
- **Unified alert layer (DELTA-1)** -- Iris designed; build after Atlas Q-C (arbiter contract graduates).
- All three are **designed + CIO-locked**, waiting on the IMU + Atlas rulings, not on more design.
