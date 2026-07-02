from=Marcus(PM); to=Rex(Dev); date=2026-07-01; topic=DISPATCH Sprint 51/V0.29.5 -- data-integrity + sync-pattern completion + battery/UI hygiene (bench-only, 10 stories); audience=agent; urgency=high; refs=US-416,US-417,US-418,US-419,US-420,US-421,US-422,US-423,US-424,US-425

# Marcus -> Rex: Sprint 51 / V0.29.5 DISPATCHED

Branch **`sprint/sprint51-V0.29.5`** forked from `dev`, pushed, upstream set; checkout is on it. **10 stories -- a FULL sprint (filled to cap); pace yourself.** Two design-gated stories are Atlas-RULED (build to the rulings, don't re-derive).

## Design rulings to build against (do NOT re-derive)
- **US-416/417:** `offices/architect/reports/2026-07-01-us416-startup-log-snapshot-sync-ruling.md` (recorded_at cursor, natural-key upsert, A-4 single-definition, **leave dtc_freeze_frame alone**).
- **US-424:** `offices/architect/reports/2026-07-01-f116-foreign-vehicle-marker-and-guard-ruling.md` (2 marker axes, sustained bus-rate guard, layered placement).

## Build order (deps noted; independent groups can interleave)
**Sync completion:**
1. **US-416 general snapshot-sync path** + `SNAPSHOT_SYNC` registry (**L, PM-signed-off**) -- the reusable mechanism; F-115 reuses it. `recorded_at` cursor, natural-key `UNIQUE(source_device, *naturalKeyCols)` upsert, A-4 define-once. **Leave dtc_freeze_frame's special-case alone.**
2. **US-417 register startup_log** onto it (deps 416) -- 2 migrations (Pi `recorded_at`, server `UNIQUE(source_device, boot_id)`). **Closes BL-013.**

**Battery chain:**
3. **US-422 wire UpsMonitor SoC%** -> recorder (prereq for 423).
4. **US-423 drop legacy** `battery_health_log` start_soc/end_soc (deps 422) -- SQLite CREATE-AS-SELECT-DROP-RENAME + server ALTER DROP; migrate consumers to vcell.

**Data-integrity:**
5. **US-424 foreign-vehicle marker + guard** (**L, PM-signed-off**) -- build order INSIDE the story: (a) 2 enum axes (`data_source='foreign'` in `data_source.py` SSOT + server mirror; `data_quality='foreign_vehicle'` in `drive_statistics_compute.py` SSOT) + re-tag drive 33 (**Spool runs the SQL; re-tag NEVER delete**), (b) Pi bus-rate guard (sustained >~7/s -> flag foreign), (c) **server tripwire = RESIZE-DROPPABLE if you're compressing** -- marker + Pi guard are the must-haves. NOT MAC-allowlist, NOT VIN (Mode-09 silent).
6. **US-419 clock-drift guard** -- **VERIFY-FIRST** (re-query the live Pi; if the clock is sane post-reboot, close as not-needed WITH EVIDENCE). Else: `clock_unsynced` flag on drifted boot timestamps. RTC/timesyncd = ops, not your scope.

**Hygiene:**
7. **US-418 idle log-noise batch** (F-077+078+058, **VERIFY-FIRST**) -- re-query the live Pi; **close sub-items as already-fixed WITH EVIDENCE** if healthy (US-325/US-332 may have fixed some). Don't suppress real events. Known split-candidate.

**UI (carousel is on dev):**
8. **US-420 LTFT trend card** -- multi-drive, honest-instrument, confirm the LTFT PID with Spool's S-2 note.
9. **US-421 power-mode badge** -- from the power-mode SSOT provider (no second acquisition path).

**Last:**
10. **US-425 doc-sync** -- architecture.md sync + data-contract sections (name the `foreign`/`foreign_vehicle` values + guard + `clock_unsynced`), regression_manifest.

## This is a heavy sprint -- the relief valves
If you find yourself compressing: **US-424's server tripwire is droppable** (Atlas-blessed), and **US-418's verify-first sub-items may close without code**. Flag me on US-416 or US-424 if you hit the wall and I'll split.

## Validation = BENCH ONLY (drive drills waived)
Fixture/DOM tests, Pi bench rigs, DB-column checks (INFORMATION_SCHEMA / schema introspection), UPS-drain rig (US-422), live-Pi re-query (US-418/419). NO drive drills.

## Notes
- Commit to THIS branch (shared-checkout: commit-immediately; if `.git/index.lock` blocks you, it's the recurring stale-lock (TD-057) -- wait/retry, never force, escalate if >a few min).
- Spool owns the drive-33 re-tag SQL (US-424) + the LTFT-PID confirm (US-420) -- ping via inbox.

CIO launches `ralph.sh` from his shell.

-- Marcus
