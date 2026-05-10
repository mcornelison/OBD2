# B-062: drain_event close-on-poweroff targeted fix (post-Drain-Test-11 evidence)

| Field        | Value                  |
|--------------|------------------------|
| Priority     | -- (was Medium / P2; now wontfix) |
| Status       | **WONTFIX 2026-05-10 (CIO approved) -- empirical evidence refutes premise** -- Drain Test 11 (drain_event 14, 2026-05-10 22:35-22:47 CDT on stable wall power) closed cleanly with end_timestamp populated. Historical DB review of drain_events 10/11/12/13/14 shows ALL FIVE recent drains have populated end_timestamps; Spool's earlier "4 of 4 unclosed" report did not match DB state at PM verification time. No reproducible bug to fix. US-307 forensic instrumentation (shipped V0.27.2) stands-watch for any future occurrence; if ever fires IRL with a NULL end_timestamp + WARNING log, file fresh story with concrete evidence. |
| Category     | observability / data integrity |
| Size         | S-M (depends on which hypothesis the evidence confirms) |
| Related PRD  | None                   |
| Dependencies | Sprint 28 US-307 (forensic instrumentation must ship + Drain Test 11 must run + evidence captured) |
| Created      | 2026-05-09             |

## Description

BL-012 Option A follow-up: Sprint 28 US-307 ships forensic instrumentation only (enriched log line in `_closeDrainEvent` except handler). Post-deploy, CIO runs **Drain Test 11** (controlled drain-to-TRIGGER on bench, no AC restore) and captures evidence:

- `journalctl --boot=-1` from the post-Drain-11 boot (the new WARNING log line carries `type(e).__name__` + `drain_event_id` + caller context if exception fired)
- `power_log` rows for the Drain-11 drain_event_id (presence of `stage_trigger` row discriminates Hypothesis C from A/B)
- `battery_health_log` row for the drain_event_id (presence/absence of `end_timestamp` confirms close fired or not)

Rex inspects the evidence and identifies which hypothesis matches Drain 9's missing close:

| Hypothesis | Evidence pattern | Targeted fix |
|---|---|---|
| **A** (fsync timing race) | `_closeDrainEvent` never raised; `endDrainEvent` returned cleanly; row missing post-poweroff | Add explicit `os.sync()` between `_closeDrainEvent` and `_shutdownAction()`; explicit `conn.commit()` + `os.fsync(db_fd)` inside `endDrainEvent`; SQLite `PRAGMA synchronous=FULL` if not already |
| **B** (silent exception swallow) | New WARNING log line shows `type(e).__name__` (e.g. `OperationalError` from sqlite3 lock contention) | Loud-bail upgrade: WARNING -> ERROR with `_activeDrainEventId` cleared but failure surfaced to journal-monitor; possibly retry logic |
| **C** (Pi killed before TRIGGER) | `power_log` has NO `stage_trigger` row for drain_event_id=9 | `_enterTrigger` was never called; problem is upstream (orchestrator tick(), VCELL observation, or kernel halt before tick fires); separate investigation |

The targeted fix shipped in V0.27.3 once root cause is empirically known.

## Acceptance Criteria

- [ ] Drain Test 11 evidence reviewed by Rex; hypothesis A / B / C identified
- [ ] If Hypothesis A: ship explicit `os.sync()` + `os.fsync()` defense; regression test simulates fsync race via fault injection
- [ ] If Hypothesis B: loud-bail logger.error + monitoring path so silent failures become observable; backfill drain_event_id=9 from `power_log` evidence (Spool's recommended path)
- [ ] If Hypothesis C: file separate investigation story; this story closes as "different bug class than originally hypothesized"
- [ ] In all cases: drain_event_id=9 historical row backfilled with `end_timestamp` from `power_log.stage_trigger` row (if Hypothesis A or B)

## Validation Script Requirements

- **Input**: Drain Test 12 (post-V0.27.3-deploy controlled drain-to-TRIGGER on bench, no AC restore)
- **Expected Output**: `battery_health_log` row with `end_timestamp` populated (NOT NULL) within 5s of `power_log.stage_trigger` row
- **Database State**: drain_event_id N has end_timestamp matching stage_trigger fire time; runtime_seconds matches start_timestamp - end_timestamp delta
- **Test Program**: scenario depends on which hypothesis confirmed; fault-injection or loud-bail discriminator

## Notes

**Drain Test 11 protocol** (Mike runs post-V0.27.2 deploy):
1. Pi running normally on AC; trigger drain by unplugging UPS battery feed (existing test rig)
2. Let drain run all the way to V0.24.1 ladder TRIGGER stage; do NOT restore AC
3. Pi powers off via systemctl poweroff; wait for full halt
4. Restore AC; Pi boots
5. Capture: `journalctl --boot=-1 > /tmp/drain11-boot-1.log`; `sqlite3 data/obd.db ".dump power_log battery_health_log" > /tmp/drain11-tables.sql`
6. Send both files to Rex inbox

**Why P2 not P1**: Drain analytics integrity matters but no safety/data-loss exposure (the safety-critical path -- ladder firing + systemctl poweroff -- works correctly per Sprint 27 in-vehicle Drain 8 validation). The fix unblocks long-term drain trending for Spool but doesn't gate near-term work.

**Source**: `offices/pm/blockers/BL-012.md` (full pre-flight audit + 3 hypotheses + Option A spec) + Spool 2026-05-09 housekeeping note Item 4 (5 of 9 drains with NULL `end_timestamp`)

**Sprint reservation**: V0.27.3 candidate alongside B-059 (drive_summary 12-field contract), B-060 (UpsMonitor SOC% wire-through), I-018 (calibration.py types.py shadow + baselines table), and any other bugs surfacing in V0.27.2 IRL validation.
