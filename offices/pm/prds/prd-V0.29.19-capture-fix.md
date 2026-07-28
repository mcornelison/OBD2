---
sprint: 65
version: V0.29.19
status: draft
createdAt: 2026-07-28
createdBy: Marcus (PM)
selectedStories: [US-493]
forksFrom: dev
sprintJsonPath: offices/ralph/sprint.json
epic: E-OPS
feature: F-117 (OBD-capture reliability)
theme: P0 -- fix the OBD connect-path regression, restore live capture (BL-025)
priority: P0 (top project blocker)
status_gate: BUILD-BLOCKED on Atlas bisect of US-441/US-432 (do not dispatch until the culprit is named)
---

# PRD: V0.29.19 -- P0 OBD capture-restore fix (BL-025)

**The blocker:** OBD capture dead since 2026-07-03 (25 days, 0 rows; PM-verified). Regression in `obd_connection.py` connect path from US-441 (_ioLock/epoch-fence) + US-432 (connect-time supported-PID probe). Full detail: `offices/pm/blockers/BL-025-*`.

**One story -- US-493** (full DoD in `backlog.json`): fix the named culprit so the service connects AND pulls live PIDs, preserving the legit intent of US-441 (no A-17 race) + US-432 (BL-016 RPM-mask). Prime suspect (Spool): the US-432 probe poisons the key-off `supported_commands` cache.

**Gate:** BUILD-BLOCKED until **Atlas bisects** US-441/US-432 and names the exact culprit — then this freezes + dispatches immediately. **Close gate is IRL** (Spool: a real captured drive, `realtime_data` grows), not a bench pass.

**Everything else is parked behind this** — the UI live-cards line is moot if the car captures nothing.
