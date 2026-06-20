---
sprint: 46
version: V0.29.0
status: converted
createdAt: 2026-06-19
createdBy: Marcus (PM)
selectedStories: [US-380, US-381, US-382, US-383, US-384, US-385]
argusReviewRequired: true
convertedAt: 2026-06-19T14:35:21Z
forksFrom: dev @ 9b3924b
sprintJsonPath: offices/ralph/sprint.json
bigDoDHash: 17bc9d6f0f67fcdc
epic: E-006
feature: F-110
atlasRule13: PASS
atlasRule13At: 2026-06-19
atlasRule13Ref: offices/architect/reports/2026-06-19-rule13-signoff-sprint46-v0.29.0-edr-bus-slice1.md
---

# PRD — Sprint 46 / V0.29.0 — EDR Dedicated-Reader Internal Bus (Slice 1)

## Summary

Gate #1 of the **EDR / Black-Box Recorder** epic (E-006, Atlas Watch List A-14):
a new `src/pi/bus/` package implementing a dedicated-reader → in-process pub/sub
bus → subscriber pipeline, with a `PersistenceSubscriber` that writes
`realtime_data` by **reusing the existing `ObdDataLogger.logReading()`** write
path, and a publish seam in `RealtimeDataLogger` — all wired behind a
`pi.bus.enabled` config flag that **defaults off**.

This is the first incremental step toward the CIO's single-reader / SSOT-bus
direction (one threaded reader → bus → consumers: vault, display, triggers, and
server-sync as just-another-subscriber). It is a **strangler-fig** slice: display,
drive detector, and the sync transport are untouched (later slices 2–5).

## Why this sprint is low-risk to ship now

- **Ships DARK.** `pi.bus.enabled` defaults `false` → merging changes nothing on
  the running system until someone flips the flag.
- **Byte-identical gate.** A golden-master test proves the bus path writes
  `realtime_data` rows identical to today's inline `logReading` path; the full
  fast suite must stay green with the flag off (zero behavioral change on merge).
- **Hardware-independent.** stdlib only, no new dependencies, uses the existing
  OBD path — does **not** wait on the IMU/light sensors (arriving ~late July) or
  the ECMLink spike. Buildable immediately.

## Authoritative design

- **Spec:** `docs/superpowers/specs/2026-06-18-edr-dedicated-reader-bus-contract-design.md`
- **TDD plan (complete code, 9 tasks):** `docs/superpowers/plans/2026-06-18-edr-bus-slice1-dedicated-reader.md`
- **Architecture ruling (EDR vs B-104):** `offices/architect/reports/2026-06-16-edr-vs-b104-architecture-ruling.md`
- **Epic tracking brief:** `offices/pm/inbox/2026-06-16-from-atlas-edr-epic-backlog-tracking-brief.md`

Atlas owns the architecture; this PRD packages his spec + plan into the Ralph
sprint contract. The Story-level detail (goal / DoD / validation criteria /
conditional outcomes) is the single source of truth in `backlog.json` and the
`offices/pm/backlog/US-38x-*.md` files, generated from it.

## Stories (build order follows `deps`)

| Story | Size | What it adds |
|-------|------|--------------|
| **US-380** | M | Bus data types: `Sample` (frozen), `QoS`, `topicMatches`, `Subscription` (bounded queue + QoS overflow + stats) |
| **US-381** | S | `SampleBus` core — subscribe/publish STREAM fan-out; producer never blocks |
| **US-382** | S | STATE retained topics (last-value-cache) + `event.integrity.gap` markers on LOSSLESS overflow |
| **US-383** | M | `PersistenceSubscriber` — writes `realtime_data` via reused `ObdDataLogger.logReading` (byte-identical golden master) |
| **US-384** | M | `RealtimeDataLogger` publish seam + `pi.bus.enabled` flag (default off) |
| **US-385** | M | Orchestrator wiring behind the flag — slice-1 ships-dark cutover |

US-380 and US-381 are the foundation; US-383/384 depend on them; US-385 depends
on all five.

## Verify-before-implement flags (Ralph, per the TDD plan)

The plan calls these out at their task; Ralph must verify the real signatures
before coding rather than assume:
- exact `ObdDataLogger.__init__` signature (US-383),
- `createRealtimeLoggerFromConfig` signature — add/forward `bus` (US-384/385),
- orchestrator class + attribute names in `lifecycle.py` (US-385),
- whether `utcIsoNow` / `getCurrentDriveId` are already imported in `realtime.py` (US-384).

## Validation (Argus)

- **Golden master:** `realtime_data` rows written via the bus path equal rows
  written via the existing inline `logReading` path (excluding `id` + write-time
  timestamp).
- **Ships dark:** `pytest tests/ -m "not slow"` green with `pi.bus.enabled=false`
  (zero regression).
- The frozen `validation.bigDefinitionOfDone` (12 clauses) aggregates each
  Story's validation criteria; see `sprint.json`.

## Design-gate DoD (PM Rule 10)

`src/pi/bus/` is a new load-bearing subsystem. If the slice lands as designed,
the architecture-doc surface for the bus contract is the Atlas spec itself
(committed on `dev`); a `specs/architecture.md` pointer/section update is in scope
if Ralph's implementation diverges from the spec. Atlas confirms at Rule 13 /
Rule 10 review.

## Post-merge deploy gate (separate; PM/CIO call)

Flipping `pi.bus.enabled=true` on the Pi and confirming byte-identical
`realtime_data` + healthy sync is a **separate** deploy-time validation, not part
of this sprint's merge — same verify-on-deploy rigor as the chi-srv-01 fix.

## Sequencing note

Does not overlap the US-367 ECU-backfill spine or the A-9 DriveDetector RCA — can
run independently. This sprint opens the **V0.29.0 chain** (forks from `dev`; the
V0.28 chain is already merged to `main` at `V0.28.2`).
