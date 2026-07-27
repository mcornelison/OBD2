---
sprint: 62
version: V0.29.16
status: draft
createdAt: 2026-07-26
createdBy: Marcus (PM)
selectedStories: [US-484-a, US-484-b]
forksFrom: dev @ (recorded at prd_to_sprint.py conversion)
sprintJsonPath: offices/ralph/sprint.json
epic: E-001 (UI/UX Polish)
feature: F-121 (Pi dashboard render-truthfully)
theme: Finish F-121 -- SSOT token reconciliation + the DTC STOP-tier safety treatment (Spool §6d)
pmFinalSizing: "APPROVED 2026-07-26 (Marcus). US-484 (was M, all-or-nothing, safety-mixed) SPLIT per the 5-dim matrix: mechanical token work vs a multi-channel safety implementation are different risk profiles. -> US-484-a (S, token reconciliation, buildable now) + US-484-b (M, STOP safety treatment per Spool §6d). Both Green post-split. 2-story focused safety sprint."
atlasReview: "PASS carried from F-121 (2026-07-21). Values now decided: --text-primary #DDDDDD + --green-ok #35C46A GATED in tokens.css (Atlas 2026-07-25). --critical-red #D32F2F assigned by Spool (2026-07-25 + §6d ruling); Atlas owes the one-line token gate (routed) before US-484-b's repoint."
---

# PRD: V0.29.16 -- Finish F-121 (token reconciliation + STOP-tier safety treatment)

| Field | Value |
|---|---|
| Version | V0.29.16 (patch on `dev`; completes F-121, which shipped 9/9 in V0.29.15 with US-484 pulled) |
| Theme | Close the last F-121 story: reconcile the SSOT tokens + fix the brand-vs-alarm **safety** collision on the DTC STOP tier |
| Status | DRAFT -- values decided; ready pending Atlas's `--critical-red` token gate (one line) |
| Lane | Pi dashboard CSS/JS + SSOT tokens; **US-484-b is safety-signal-integrity** |
| Stories | US-484-a, US-484-b under **F-121** |
| Deploy + validate | Deploys from `dev`; STOP treatment validated on the real 480×320 panel |

## Why this sprint

US-484 was pulled from V0.29.15 (CIO 2026-07-22) blocked on two design inputs (BL-024). Both are now in:
- **`--text-primary #DDDDDD`** + **`--green-ok #35C46A`** — Atlas gated into `specs/UI/tokens.css` (2026-07-25).
- **`--critical-red #D32F2F`** — Spool assigned the value **and** the load-bearing safety ruling (§6d): a hex swap alone is **insufficient** (saturation-only delta from brand red, weak on the narrow-gamut panel), so STOP integrity is carried by **area + motion + "PULL OVER" text + near-black bg + full-brightness-always**, with color as the *third* reinforcement.

That safety ruling is why US-484 **split**: the token reconciliation is mechanical; the STOP treatment is a real multi-channel safety implementation.

## Stories (full DoD/validationCriteria in `backlog.json`)

| Story | Type | Size | Summary | Gate |
|---|---|---|---|---|
| **US-484-a** | tech-debt | S | **SSOT token reconciliation** — `dashboard.css --ok-green #2ECC71 → --green-ok #35C46A` + align `--text-primary → #DDDDDD`. Mechanical, no visual regression, no STOP touch. | none — buildable now |
| **US-484-b** | issue | M | **DTC STOP-tier SAFETY treatment (Spool §6d)** — repoint STOP off brand `--red-light` onto `--critical-red #D32F2F`, **plus** the multi-channel treatment: full-bleed area + pulsing motion + "PULL OVER" text + near-black bg + white copy + **full-brightness-always** (independent of the US-483-b auto-dim). WATCH/MINOR unchanged; deeper-darker axis (no orange). | Atlas one-line `--critical-red` token gate (value decided) |

## Sequencing
- **US-484-a first** (mechanical, unblocks nothing else, fast). **US-484-b** needs the `--critical-red` token line in `tokens.css` — Atlas owes it (value is Spool's #D32F2F); I've routed the reminder. It's a near-instant gate, not a substantive block.

## Optional additions (flagged, not included)
- **V0.29.13 housekeeping** (US-472 Node-pin, US-473 hostname sweep) remain sprint-ready but un-shipped; US-473 is prereq-gated on the Pi OS rename (AI-003). Could bundle here if desired — left out to keep this a focused safety sprint.

## Not in this sprint
- EDR next-line work (Spool's 2026-07-26 EDR PRD review + PID-priority notes) — separate grooming, future sprint.
- IRL re-gate (A-9/A-17/A-16-Bug3/BL-016) — car-gated, owed regardless.
