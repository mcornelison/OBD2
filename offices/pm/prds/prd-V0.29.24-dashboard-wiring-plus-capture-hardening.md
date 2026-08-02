---
sprint: 69
version: V0.29.24
status: draft
createdAt: 2026-08-01
createdBy: Marcus (PM)
selectedStories: [US-501, US-502, US-503, US-504, US-505, US-512, US-513, US-517, US-518, US-521]
forksFrom: dev @ (recorded at prd_to_sprint.py conversion; forks from dev AFTER V0.29.23 deployed)
sprintJsonPath: offices/ralph/sprint.json
epics: E-001 (UI/UX Polish) + E-OPS (F-120 BT reliability) + E-006 (EDR)
features: F-123 (dashboard truthfulness wiring), F-120 (BT connectivity reliability), F-125 (GPS + honest altitude foundation)
theme: "FULL sprint (CIO 2026-08-01). Dashboard truthfulness WIRING (F-123, incl US-504 re-groomed to Spool's spec) + BL-025 capture HARDENING (F-120) + honest-altitude FOUNDATION (F-125 -- home config + sync re-anchor + gyro-fused pitch). The altitude DISPLAY (US-519/520) + real GPS (US-516) are DEFERRED (Spool sigma-sizing / hardware TBD not ordered)."
atlasReview: "PASS 2026-07-31 (F-123/F-120) + F-125 contract/seams ruled 2026-08-01 (abfc03f: states/gps contract, US-517 home-config seam, US-518 sync-reanchor seam). Spool rulings folded: US-504 verdict spec (writer-fix-first + [EXACT] thresholds + honest-unknown + never-red); US-521 gyro-fused pitch + ZUPT required before any altitude integration; US-502 power tile -> PowerModeProvider SSOT; US-505 Pi-local last-drive; US-512 transport-reset shape (bond from V0.29.22)."
---

# PRD: V0.29.24 -- dashboard wiring + capture hardening (Sprint B of the split)

| Field | Value |
|---|---|
| Version | V0.29.24 (patch on dev; forks after V0.29.23 / Sprint A lands) |
| Origin | Sprint B of the /resize-split of the 13-story combined round (was >10 hard limit). Sprint A = F-124 UI (V0.29.23). |
| Stories | US-501, US-502, US-503, US-504, US-505 (F-123) + US-512, US-513 (F-120) -- 7, all Green/Yellow zone |
| Deploy | from dev; validated on the Pi (wiring) + engine-on drive (US-512 capture) |

## Stories (full DoD/validationCriteria in backlog.json)
| Story | Size | Summary | Gate |
|---|---|---|---|
| US-501 | S | Version chip -> inject real .deploy-version | none |
| US-502 | M | Power reader -> fixes grayed bolt + 'unavailable' tile (one root); wire to PowerModeProvider SSOT | none (seam ruled) |
| US-503 | S | Idle clock -> 12h AM/PM | none |
| US-504 | M | Battery-Health truthfulness (remove no-source TEMP + wire HEALTH verdict + last-health-check) on the consolidated Health card | **Spool health-verdict source** + seq after US-507 (Sprint A) |
| US-505 | M | Last-drive-summary producer (reads Pi-local obd.db/connection_log per Atlas) | none (source ruled) |
| US-512 | M | Durable bond + reconnect-transport-reset (BL-025 #3) | Atlas shape ruled; live = engine-on drive (Spool) |
| US-513 | S | RCA: why BT soft-blocked ~07-03 (BL-025 #4) | none |

## Sequencing / gates
- **After Sprint A:** US-504 wires the *consolidated* Health card (US-507), so A lands first.
- **Only open gate: US-504's HEALTH verdict source** -- routed to Spool (offices/tuner/inbox 2026-07-31). When Spool answers, US-504 is dev-ready; if a producer must be built, scope it in-story or carve a sub-story.
- **US-512** is buildable now (the durable bond shipped in V0.29.22); its full acceptance is the engine-on validation drive (Spool) -- same drive that closes BL-025.

## Not in this sprint
- F-124 UI round 2 -> Sprint A / V0.29.23.
- BL-025 #5 wired USB adapter -- CIO declined (staying on Bluetooth).
