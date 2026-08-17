# Maintenance Tracking — Design Spec Ready for V0.30+ Grooming Queue

**Date**: 2026-05-21
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Routine — backlog grooming intake; not Sprint 41 candidate
**Status**: No action required until V0.30+ grooming opens
**Sibling**: companion to topic A spec filed earlier today (post-drive anomaly engine)

---

## TL;DR

Sub-thread B of the 2026-05-21 brainstorm complete. Topic: **maintenance tracking** — service intervals, wear items, regulatory dates, event log; all owner-helpful data we don't currently collect. NEW DOMAIN — zero backlog coverage before this brainstorm. Spec committed to `docs/superpowers/specs/2026-05-21-maintenance-tracking-design.md` (commit `866bb83`).

Same lane discipline as topic A: this is backlog grooming, not sprint preparation. Skipping `writing-plans` per the topic A precedent. Marcus owns sprint planning at sprint-spin time; Atlas separately notified for architecture awareness.

## Spec summary

**Scope**: V1.0 MVP = 5 catalog items covering all 4 categories + critical-tier example (oil_change, timing_belt, brake_pads_front, registration_renewal, modification_install) fully wired end-to-end → V1.0 Full = catalog expansion → V2+ = web UI + receipt attachments + automated wear-item thresholds.

**Key design choices**:
- 4 new tables (`maintenance_items` catalog, `maintenance_events` history, `vehicle_mileage_log` hybrid subsystem, `maintenance_import_log` audit trail)
- Server-authoritative per B-104; Pi-side read-only mirror with `NotImplementedError` write tripwire
- **Rides topic A's sync-back wiring** — both topics extend the same `/api/v1/sync` response payload; single infrastructure change, both topics benefit
- Hybrid mileage: manual entry (CIO logs at fill-ups) + speed-integration estimate during drives + drift detection at 5% over 90+ days; future Telegram proactive prompts via B-099
- Entry surface: CLI primary + Telegram conversational secondary (B-099-gated); web UI deferred to V2
- Reminder engine: 3-tier (UP-TO-DATE / DUE-SOON / OVERDUE) + NO-HISTORY edge tier; criticality-scaled lead times (timing belt gets 180-day / 5,000-mi warning window)
- `rules.yaml` shared with topic A — `maintenance_lead_times` + `maintenance_drift_thresholds` + `maintenance_data_thinness` config; same Spool sign-off discipline via CODEOWNERS
- Bulk YAML seed (`seed_maintenance.yaml`) for 28-year historical import; SHA-256 `file_hash` idempotency
- Pi parked-mode tile mirrors topic A pattern (SUMMARY + DETAIL states; auto-snap red flashing on critical OVERDUE — e.g., timing belt overdue)

**Counts**: 16 acceptance criteria, 7 open questions, 6 related backlog items, 9 sections totaling 989 lines.

## Cross-link suggestions for the backlog

This spec is NEW DOMAIN — no existing backlog item to cross-link to as an implementation. But it relates to several existing items:

| Existing item | Relationship |
|---|---|
| **B-086** GEM-1 warnings-first quiet UI | Pi maintenance tile lives in this carousel (sibling to topic A's anomaly tile). Single carousel-cell ownership coordination needed. |
| **B-094** GEM-9 MrSpool RAG digital twin | V0.34+ consumes maintenance state as RAG context. The `status --json` output schema is the input shape. |
| **B-099** Telegram driver-context bidirectional | Infrastructure dependency for conversational entry + proactive nudges. V1 can ship CLI-only if B-099 delays. |
| **B-104** Server-side analytics authority | Architectural foundation (server-writer + Pi-mirror pattern). Same as topic A. |
| **US-355** Sprint 41 deploy-context drive simulator | Integration test gate (shared with topic A). Mileage subsystem validation rides this harness. |

PM lean (your call): worth filing as a NEW umbrella **B-### Maintenance Tracking Subsystem** backlog item with the design spec as primary doc + the 5 MVP items as sub-items? Or keep as a single spec referenced by future grooming work. Either works; I have no preference.

## Open questions captured in the spec (PRD-grooming time)

1. Web UI deferred to V2 — at what V version does it land?
2. Telegram dependency on B-099 — does B-099 land before or after this work? V1 can ship CLI-only if delayed
3. Multi-vehicle escape hatch — if a second car ever enters the picture, schema migration adds `vehicle_id`
4. Automated measurement-threshold checks for wear items — v1 shows last measurement; v2 could auto-flag below-threshold
5. Receipt scan attachments — `attachments_json` reserved; v2 wires actual storage
6. Default catalog seed — should the project ship `default_4g63_catalog.yaml` for any user, or stay project-specific
7. Proactive Telegram nudge cadence — every 30 days for mileage? Quarterly? After N drives?

## Other sub-threads remaining (CIO direction)

The 2026-05-21 brainstorm covered sub-threads **A** (post-drive anomaly engine, spec already filed) + **B** (this one). Two more remain queued at CIO discretion:

- **C**: AI-driven predictive analytics ("your car best performs when...") — pattern mining over historical drives; distinct from B-087 (per-drive Ollama explanation) and B-094 (Q&A RAG)
- **D**: UI carousel refinement (95% full-screen + alert auto-snap; specs/samples mockups) — extends B-086

CIO will direct timing. No PM action needed.

## Lane discipline notes

- Spec lives in `docs/superpowers/specs/` (standard location)
- Did NOT cross-link spec into B-086/B-094/B-099/B-104 myself — that's PM lane
- Did NOT invoke `writing-plans` — backlog grooming, not sprint prep
- Spec touches load-bearing server analytics surfaces (sync-back wiring extension, new Pi-mirror tables, shared `rules.yaml` config); PM Rule 10 design-gate territory at sprint time; Atlas separately notified
- Topic A + topic B share considerable infrastructure (sync-back wiring, Pi tripwire pattern, `rules.yaml`, US-355 test harness) — recommend Marcus group them for grooming OR explicitly note the dependency at PRD time

## What I need from you (eventually, not now)

- At V0.30+ grooming opens: review spec + decide whether to file new umbrella B-### or treat as referenced design only
- Loop me in for `/review-stories-tuner` before Ralph dispatch (Sprint 39/40 cadence)
- Coordinate with topic A — they share infrastructure; landing them in the same sprint or back-to-back sprints maximizes the shared-wiring benefit
- No urgency. V0.27 chain merge + topic A + Sprint 41 in-flight work all come first.

— Spool
