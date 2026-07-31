---
sprint: 67
version: V0.29.23
status: draft
createdAt: 2026-07-31
createdBy: Marcus (PM)
selectedStories: [US-501, US-502, US-503, US-504, US-505, US-506, US-507, US-508, US-509, US-510, US-511, US-512, US-513]
forksFrom: dev @ (recorded at prd_to_sprint.py conversion; AFTER the V0.29.22 capture hotfix lands + deploys)
sprintJsonPath: offices/ralph/sprint.json
epics: E-001 (UI/UX Polish) + E-OPS (F-120 BT reliability)
features: F-123 (dashboard truthfulness wiring), F-124 (round-2 UI design), F-120 (BT connectivity reliability)
theme: One combined sprint (CIO 2026-07-31) — UI round 2 (Iris F-124 design + F-123 wiring, reconciled) + BL-025 capture hardening (#3/#4). Will likely /resize-split.
designSpecs: offices/uidevloper/proposals/2026-07-31-pi-ui-round2-f124.md (Iris, CIO-locked) + 2026-07-27-pi-live-instrument-card.md; triage SSOT offices/pm/decisions/2026-07-31-ui-feedback-round2-triage.md
atlasReview: PENDING — design-gate review requested; two rulings gate US-508 (states/imu contract) + US-510 (TD-065 token values); Atlas offered to gate the BL-025 #3/#4 stories too.
---

# PRD: V0.29.23 — UI round 2 + capture hardening (combined sprint)

| Field | Value |
|---|---|
| Version | V0.29.23 (patch on `dev`; forks AFTER the V0.29.22 capture hotfix deploys) |
| Origin | CIO bench review of the shipped V0.29.21 UI (15 items) + Atlas's BL-025 breakthrough work-list. CIO chose ONE combined sprint + staying on Bluetooth. |
| Threads | (1) Iris F-124 design · (2) F-123 dashboard wiring · (3) F-120 BT capture hardening |
| Sizing | 13 stories — **expected to /resize-split** (candidate: 67a ship-ahead UI + wiring, 67b Atlas-gated UI + capture hardening) |
| Deploy | from `dev`; validated on the real 480×320 panel + (capture) the engine-on drive |

## Context
The capture P0 (BL-025) root cause was found + fixed live 2026-07-31 (persistent BT rfkill soft-block). Its two P0 durability fixes (deploy-bake + `pair_obdlink.sh`) are CIO-directed direct hotfixes already with Ralph → they ship as **V0.29.22** (a hotfix deploy, NOT in this sprint). This sprint carries the *remaining* capture hardening (#3/#4) plus the full UI round-2 line.

## Stories (full DoD/validationCriteria in `backlog.json`)

### Thread 1 — Iris F-124 design (E-001)
| Story | Size | Summary | Gate |
|---|---|---|---|
| US-506 | L | Carousel nav: wrap (skip gated) + auto-rotate 8s + velocity swipe-pause (≥0.6 px/ms) + 45s resume | none |
| US-507 | M | Consolidate 6→4 screens — Battery+Light+Fuel Trim → "Health"; retitle LTFT→"Fuel Trim" | none |
| US-508 | L | Live/motion card re-issue (compass tape, gear, 0.6g amber) + home-slot idle↔live swap | **Atlas states/imu contract** |
| US-509 | M | System-Status "N ISSUE" drill-down overlay (worst-first, Back) | none |
| US-510 | M | Fidelity: restore ECLIPSE OBD-II wordmark/footer + `--font-display` face + TD-065 tokens | **partial: Atlas token values** |
| US-511 | S | Debounced "parked" signal so the kebab stops flickering on OBD blips | none (display-side) |

### Thread 2 — F-123 dashboard wiring (E-001)
| Story | Size | Summary | Gate |
|---|---|---|---|
| US-501 | S | Version chip → inject real `.deploy-version` (#1) | none |
| US-502 | M | Power-source reader → fixes grayed bolt (#2) + "unavailable" tile (#6), one root | seam-confirm |
| US-503 | S | Idle clock → 12h AM/PM (#3) | none |
| US-504 | M | Battery-Health truthfulness (#5/#8): remove no-source TEMP + wire HEALTH verdict + last-health-check | Spool verdict source; **seq after US-507** |
| US-505 | M | Last-drive-summary producer (#4) | last-drive source-confirm |

### Thread 3 — F-120 BT capture hardening (E-OPS)
| Story | Size | Summary | Gate |
|---|---|---|---|
| US-512 | M | Durable bond + reconnect-transport-reset (BL-025 #3) | Atlas design-gate; live acceptance = engine-on drive |
| US-513 | S | RCA: why BT soft-blocked ~07-03 (BL-025 #4) | none |

## Sequencing
- **Consolidation-first:** US-507 (merge to Health card) lands before US-504 (battery wiring) so the wiring targets the merged card. US-506 nav can land alongside.
- **Ship-ahead (no external gate):** US-506, US-507, US-509, US-511, the copy/font/existing-token half of US-510, and US-501/502/503; US-513.
- **Gated (hold until ruled):** US-508 (Atlas states/imu contract), US-510's `--bg`/`--surface`/`--destructive` literals (Atlas Rule-10 token values), US-504 (Spool health-verdict source), US-505 (last-drive source-confirm). US-512 wants Atlas's design-gate.

## Not in this sprint
- **V0.29.22 capture hotfix** (rfkill-unblock deploy-bake + `pair_obdlink.sh` fix) — CIO-directed direct hotfixes with Ralph; PM bumps + deploys separately.
- **BL-025 #5 wired USB adapter** — CIO declined (staying on Bluetooth), so #3 reconnect-reset stays in scope.
- **BL-025 #6 engine-on validation drive** — the live acceptance for capture; a CIO drive, not a dev story.

## Open gates to clear before dispatch
1. **Atlas** — `states/imu` derived-field contract + >1Hz transport (US-508); `--bg`/`--surface` + 2 `--destructive` token values (US-510); design-gate on US-512 + the PRD.
2. **Spool** — battery-health HEALTH verdict + last-health-check source (US-504; already asked).
3. **PM** — confirm the Pi's authoritative last-drive source (US-505).
