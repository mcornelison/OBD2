---
sprint: 60
version: V0.29.14
status: draft
createdAt: 2026-07-15
createdBy: Marcus (PM)
selectedStories: [US-386, US-387, US-388, US-389, US-390, US-474]
forksFrom: dev @ (recorded at prd_to_sprint.py conversion)
sprintJsonPath: offices/ralph/sprint.json
epic: E-002
feature: F-107 (DriveDetector Dual-Attribution + Pi-Side Drive Lifecycle Hardening) + F-117 (OBD-capture reliability, US-474 A-17 hardening)
theme: A-9 data integrity + A-17 capture reliability -- kill the DriveDetector close-signal defect AND harden the live capture-race fix, both validated on the one drive-35 re-gate
supersedes: prd-V0.29.1.md (Session-49 draft of the same F-107 work; version + scope refreshed -- 5-story chain, not the 7-story 386..392 draft)
atlasReview: "PENDING -- routed 2026-07-15 (inbox 2026-07-15-from-marcus-sprint59-60-prd-review-request.md). US-388 build-gated on Atlas acceptance of the US-387 RCA (in-sprint gate)."
---

# PRD: V0.29.14 -- DriveDetector data-integrity (F-107, A-9)

| Field | Value |
|---|---|
| Version | V0.29.14 (patch on `dev`, forks from V0.29.13) |
| Theme | Reproduce → root-cause → fix → lock the drives-28/29 DriveDetector defect (a drive never closes; a second `drive_id` opens over an open one → overlap + multi-day stale-open leak) |
| Status | DRAFT (pending Atlas review). Stories authored in `backlog.json` since Session 49; refreshed to current version this session. |
| Lane | Pi drive-lifecycle + server tripwire backstop; **load-bearing** (Atlas design-gate applies — US-388/389 update `specs/architecture.md` in-sprint). |
| Stories | US-386→390 (5) under **F-107** |
| Deploy + validate | Deploys from `dev`; **IRL-gated** — final acceptance needs the A-9 car re-gate (a single clean drive proving one `drive_id`, correct close, no absorption). |

## Why now

A-9 / F-107 is the open data-integrity wound in the V0.29 chain. Per Atlas's 2026-06-19 RCA ruling + Spool's 2-table corroboration (`connection_log` shows `drive_start`=29 / `drive_end`=18, zero `drive_id` on any comms failure): **comms-drop is ruled out** — the K-line is stable mid-drive; the drive simply never closes because the DriveDetector close-signal state machine doesn't fire. That produces (1) drives that never close and (2) a later key-on minting a *new* `drive_id` that overlaps the stale-open one (ids out of temporal order, multi-day absorption). The V0.28.0 server tripwire (`detect_overlapping_drives`) catches it *after the fact* (stamps `data_quality=attribution_anomaly`); this sprint fixes it *at the Pi source* and locks the regression permanently.

**Root 1 vs Root 2 (Atlas ruling):** Root 1 (concurrent-process dual-attribution) was already mitigated out-of-band (single-instance guard `d6d8b05` + `RuntimeDirectory` `fae7ee7` + Pi deploy). US-389 makes that durable + tested. Root 2 (stale-open-close leak) is the substantive fix (US-388).

## Stories (full DoD/validationCriteria in `backlog.json`)

| Story | Type | Size | Summary | Gate |
|---|---|---|---|---|
| **US-386** | issue | M | Deterministic **in-process reproducer** (synthetic engine-state — no car): short drive, back-to-back drives, key-on-after-missed-close. Asserts one `drive_id`/drive, each closes, no absorption. FAILS RED on current `detector.py`. | — |
| **US-387** | research | M | **RCA**: name the exact code path + mechanism (file:line) for BOTH defects; confirm/refute the one-root hypothesis with the reproducer + Spool's `connection_log` finding. No fix. | Atlas review → root accepted (gates US-388) |
| **US-388** | issue | M | **Root-2 FIX** (shape pending RCA): guaranteed-close + stamp `drive_id` ONLY when RUNNING + gap-fence the latch (idle/KOEO → NULL so a stale-open can't absorb a later key-on). Reproducer → GREEN. Updates `specs/architecture.md` DriveDetector section in-sprint. | **BUILD-BLOCKED until US-387 RCA accepted by Atlas** (in-sprint) |
| **US-389** | issue | S | **Root-1 closure**: bake single-instance guard + `RuntimeDirectory` as a *matched-pair* tested deploy invariant (Atlas C-5) + confirm the 06-06 spawn trigger (C-3) + fold into a proper version stamp. Updates boot-path `specs/architecture.md`. | independent (sprint-ready) |
| **US-390** | issue | S | **Regression lock**: reproducer → permanent fast-suite/manifest; confirm the server `detect_overlapping_drives` tripwire still stamps `attribution_anomaly` on synthetic overlap (belt-and-suspenders). | deps US-388 |
| **US-474** | issue | M | **A-17 capture-fix hardening (Atlas R1, F-117):** make the live A-17 DTC-read serialization (`4a17bc1`) a **typed** `ObdConnectionLike.query()` contract (kill the runtime `getattr` fallback) + add a **non-mocked connect-edge concurrency regression** (the exact GAP-1 F-117 missed) + full pi suite. Fix is live; this is durable hardening. | independent (fix already deployed) |

## Sequencing (in-sprint)

```
US-386 (reproducer RED) ──┬─→ US-387 (RCA) ──[Atlas accepts]──→ US-388 (Root-2 fix, GREEN) ──→ US-390 (lock)
                          └─→ (US-389 Root-1 closure runs independently in parallel)
```

- **US-388 is deliberately shape-pending**: do NOT code the fix before Atlas accepts the US-387 RCA (per A-11). If the RCA reveals the fix is architectural (id-minting concurrency, detector re-entrancy), route back to Atlas for a design ruling before coding.
- This is why the sprint carries the RCA (US-387) *inside* it rather than gating dispatch on it — the in-sprint Atlas checkpoint sequences the fix.

## Validation (IRL-gated)

Reproducer + suites go green on the bench, but **final acceptance is the A-9 car re-gate**: one clean drive on the fixed Pi producing exactly one `drive_id`, correct close on key-off, no absorption of a later key-on, tripwire clean. This is the **same drive** that re-gates OBD-capture (F-117/BL-016) — bundle them into one CIO drive. Until that passes, US-388/390 are `deployed — awaiting validation`, not `/sprint-validated`.

## Notes

- Rule-13 retired → Atlas's PRD review IS the gate; no post-freeze re-gate.
- Supersedes the stale `prd-V0.29.1.md` (Session-49 draft, same F-107 work). Scope this session = the 5-story F-107 chain (386→390); US-391 (dtc quarantine, F-076) + US-392 (config de-dup) from the old 7-story draft are **out** of this sprint (separable; groom later if wanted).
- On Atlas PASS: generate `sprint.json` → `sprint_lint` → branch `sprint/sprint60-V0.29.14` → CIO runs `ralph.sh` (US-386 first).
