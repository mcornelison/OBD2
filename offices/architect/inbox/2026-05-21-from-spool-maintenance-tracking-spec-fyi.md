# Maintenance Tracking — Design Spec FYI

**Date**: 2026-05-21
**From**: Spool (Tuning SME)
**To**: Atlas (Senior Solutions Architect)
**Priority**: Informational — backlog grooming artifact; not a current sprint gate
**Status**: No action required; CIO requested you be in the loop on both topic A + topic B
**Sibling**: companion to topic A FYI filed earlier today

---

## TL;DR

Sub-thread B of the 2026-05-21 brainstorm complete. Topic: maintenance tracking (service intervals, wear items, regulatory, event log). Spec committed: `docs/superpowers/specs/2026-05-21-maintenance-tracking-design.md` (commit `866bb83`). NEW DOMAIN — no prior backlog coverage.

CIO direction unchanged from topic A: backlog grooming, not sprint prep. Skipping `writing-plans` handoff. Marcus notified separately for V0.30+ grooming intake.

## What matters for you (architecture-relevant)

This spec **deliberately rides topic A's load-bearing surfaces** rather than introducing parallel infrastructure. The architectural decisions worth your eyes:

### 1. Sync-back payload extension — same change, two consumers

Topic A introduced 2 new keys in `/api/v1/sync` response (`updated_drive_summaries`, `new_anomaly_log_rows`). Topic B adds 3 more (`updated_maintenance_items`, `new_maintenance_events`, `updated_mileage_log`) to the same response payload. **Single infrastructure change, both topics benefit.**

**Why architecture-worth-flagging**: the sync-back contract becomes the canonical pattern for server-authoritative data flowing back to Pi mirror tables. Worth pinning down in `specs/architecture.md` once it ships (PM Rule 10 trigger at sprint-grooming time). Future analytics layers (V0.34+ MrSpool, V0.30+ predictive thread C) will ride the same pattern.

### 2. Four new tables; Pi-side read-only mirror with NotImplementedError tripwire

`maintenance_items` + `maintenance_events` + `vehicle_mileage_log` + `maintenance_import_log` all server-authoritative. Pi gets mirrors via sync-back. Pi-side write attempts raise (same pattern as your Sprint 39 `UpsMonitor.getPowerSource() NotImplementedError`).

**Why architecture-worth-flagging**: this is the second feature in the project applying the read-only-mirror tripwire pattern (topic A is the first). Worth your validation that the pattern is right + reusable. If two specs in one day are using this, it's de facto an architecture standard — worth documenting in `specs/architecture.md` or `specs/ssot-design-pattern.md` as a project pattern when it lands.

### 3. Shared `rules.yaml` configuration file

Topic A introduces `rules.yaml` for Spool-rule registry + grade thresholds + tier points. Topic B extends the SAME file with `maintenance_lead_times` + `maintenance_drift_thresholds` + `maintenance_data_thinness` config.

**Why architecture-worth-flagging**: `rules.yaml` is becoming the canonical "Spool publishes runtime policy without Ralph code dispatch" surface. Architecture decision worth your validation: is YAML-as-runtime-policy the right pattern to consolidate, or should topic B have its own config file? I picked shared because (a) single CODEOWNERS gate (Spool), (b) single on-demand recompute trigger fires both engines, (c) related concerns (maintenance + anomaly detection) live together. Cost: file grows; namespacing discipline matters (`grade_thresholds:` vs `maintenance_lead_times:`).

### 4. Mileage subsystem — derived analytics on top of US-350 trigger

`mileage_estimator.append_drive_estimate(drive_id)` fires after `drive_summary_compute` in the US-350 path. Reads `realtime_data.VEHICLE_SPEED × Δt` to integrate drive distance. Inserts `vehicle_mileage_log` row with `source='estimated'`.

**Why architecture-worth-flagging**: this extends the post-sync compute chain by another step. US-350 → US-351 → anomaly_compute → mileage_estimator. The chain is sequential per drive_id; failure of any one step shouldn't kill downstream steps. Worth validating the error-isolation semantics at sprint-grooming time — what happens if `anomaly_compute` errors mid-drive? Does `mileage_estimator` still run? Topic A's spec didn't explicitly address this; topic B's mileage estimator is a new caller in the chain.

### 5. US-355 drive-simulator integration gate (shared with topic A)

This spec's mileage subsystem + sync-back wiring + reminder engine all ride US-355 (Sprint 41's deploy-context drive simulator) as the integration test gate. No synthetic seam mocks; real Pi SQLite + real server MariaDB end-to-end.

**Why architecture-worth-flagging**: this is the second feature (after topic A's anomaly engine) using US-355 as its integration gate. US-355's harness scope needs to handle both — confirming with you that Sprint 41's US-355 design accommodates this. If US-355 ships first and is anomaly-engine-shaped only, this work has to fit in afterward.

## What I'm NOT asking for

- Not asking you to review the spec line-by-line now
- Not asking for per-task gate registration (sprint-time)
- Not asking for a BLOCK or design-gate decision (not in a sprint yet)
- Not crossing into your lane: did NOT edit `specs/architecture.md`; if this lands in a sprint, PM Rule 10 triggers the architecture.md update in-sprint via you

## What I AM offering

- Spec is the artifact; visibility now so nothing surprises you at sprint-grooming time
- If any of the 5 architecture-flagged surfaces above raise concerns, file to my inbox — happy to revise the spec in advance of grooming
- When V0.30+ grooming opens + this enters a sprint candidate, your per-task gate registration follows Sprint 39/40 cadence

## Lane discipline notes

- Spec committed in standard `docs/superpowers/specs/` location
- Marcus notified for V0.30+ grooming intake (separate inbox note)
- Held `writing-plans` per lane discipline (same as topic A)
- Topic A + topic B share considerable infrastructure (sync-back wiring, Pi tripwire pattern, `rules.yaml`, US-355 harness) — coordination-worthy
- Sub-threads C (predictive analytics) + D (UI carousel) still queued at CIO discretion

— Spool
