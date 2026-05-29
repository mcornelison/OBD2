# US-369 DONE — two routed items for PM

**From:** Rex (Dev) · **To:** Marcus (PM) · **Date:** 2026-05-28 · **Re:** US-369 (F-109 server sync + `show_dtc_freeze_frame` CLI)

US-369 is `passes: true` (Sprint 43 / V0.28.0). Both-tier, all dev-runnable validation GREEN (server 948 passed / Pi 1549 passed, ruff clean, changes UNSTAGED). Two items need PM/cross-story handling — neither blocks the story.

## 1. US-369 added a `notes` column to `dtc_freeze_frame` → US-373 §5.X should document the FINAL landed shape

US-368 created `dtc_freeze_frame` with a Pi-side `notes` column but **no** server-side `notes` column. US-369 needed it for a faithful round-trip and for `show_dtc_freeze_frame`'s graceful-degradation path (conditionalOutcome 2: "freeze-frame captured but Mode 02 PIDs unavailable + notes"). So this story added:

- `DtcFreezeFrame.notes` (`Text`, nullable) in `src/server/db/models.py`
- `notes TEXT` in the v0010 `CREATE_DTC_FREEZE_FRAME_DDL`

The table is brand-new this sprint (`CREATE TABLE IF NOT EXISTS`, not yet deployed), so the DDL add is clean — no separate migration substep. **Ask:** US-373's §5.X (V0.28 schema-pass) documents schema surfaces in their FINAL landed state (US-373 conditionalOutcome: "document FINAL landed state not PRD-planned state"). The `dtc_freeze_frame` surface should reflect the **synced columns + `notes`** as landed by US-368 **and** US-369.

## 2. IRL freeze-frame sync round-trip belongs on the sprint validationMethod drill checklist

US-369's unit validation runs against in-memory SQLite + real ORM (no seam mocks, post-I-040 discipline) and covers V-1…V-5 on the dev box. The **actual** Pi→chi-srv-01 sync of a real captured freeze-frame, then `python -m server.cli.show_dtc_freeze_frame --dtc-log-id N` against prod `obd2db`, is IRL-only and not runnable from the Windows dev box. Same precedent as US-362 V-5 and US-363 (deferred to the sprint IRL drill). **Ask:** add a line item to the V0.28.0 sprint validationMethod / IRL-drill checklist:

> Trigger a MIL_ON freeze-frame on the Pi, sync to chi-srv-01, run `show_dtc_freeze_frame --dtc-log-id <N>` — confirm 16 PIDs intact + `vehicle_info` joins to the ECU active at capture time (Q4 round-trip).

## Notes for completeness

- No PM Rule 10 / Atlas Rule 10 gate is named in US-369's own ACs (unlike US-365/368). The schema touch (`notes` col) folds into US-373's §5.X + the sprint-wide Atlas Rule 10 sign-off already pending there.
- Files touched: `src/pi/data/sync_log.py`, `src/server/api/sync.py`, `src/server/db/models.py`, the v0010 migration, new `src/server/cli/show_dtc_freeze_frame.py`, + 6 test files (3 new, 3 guard-updates). Full detail in `sprint.json` US-369 `completionNotes` + `progress.txt`.
