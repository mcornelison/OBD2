# US-227 blocked: Pi has not been re-deployed; Drive 3 still stranded

**From:** Rex (Ralph Agent 1)
**To:** Marcus (PM), Spool (Tuner SME)
**Date:** 2026-04-27
**Re:** Sprint 18 / US-227 (Pi + server operational truncate)

## Findings (deterministic, repeatable)

Pre-flight audit per US-227 acceptance #1 + verification commands. Live SSH to
chi-eclipse-01 (10.27.27.28) on 2026-04-27 05:56 CDT:

```
sync_log:
  realtime_data | last_synced_id=149   | last_synced_at=2026-04-19T13:48:05Z | ok
  statistics    | last_synced_id=11    | last_synced_at=2026-04-19T13:48:05Z | ok
  connection_log| last_synced_id=16    | last_synced_at=2026-04-19T13:48:05Z | ok

realtime_data row groups:
  drive_id=NULL data_source=physics_sim   171
  drive_id=NULL data_source=real          413
  drive_id=1    data_source=real     2,939,090   <- US-227 target
  drive_id=2    data_source=physics_sim 1,853
  drive_id=3    data_source=real        6,089   <- DRIVE 3, stranded

drive_id=3 id range: 3,433,872 .. 3,439,960
drive_id=3 timestamp range: 2026-04-23T16:36:50Z .. 2026-04-23T18:35:44Z
```

Auto-sync code on the running Pi (grep on the live deploy):

```
src/pi/obdii/orchestrator/core.py     : _maybeTriggerIntervalSync   = 0 matches
src/pi/obdii/orchestrator/lifecycle.py: _initializeSyncClient        = 0 matches
```

Both US-226 markers are absent. `eclipse-obd.service` is `active (running)`
but on pre-Sprint-18 code. Service is in a BT-reconnect loop (engine off →
"Adapter connected, but the ignition is off") — expected for the pre-US-229
ELM_VOLTAGE keepalive behavior.

## Diagnosis

US-226's source-tree fix (auto-sync via interval + drive_end triggers in
`orchestrator.runLoop`) has not been deployed. The 2026-04-19 sync cursor is
the manual `sync_now.py` push from Session 23 — exactly what the US-226
completionNotes flagged would happen ("Real-world verification deferred to
CIO/Ralph running deploy-pi.sh + observing 'Interval sync:' log lines in
journalctl").

This is the same blocker the previous Ralph session (Session 103, US-233
close) flagged: "US-227 (still blocked on CIO deploy + Drive 3
server-landing)." No code-only path clears it from a windows-dev session.

## What I did NOT do (and why)

- Did NOT pre-build `scripts/truncate_drive_id_1_pollution.py`. The script
  needs to consult `sync_log.last_synced_id` to gate the DELETE — building it
  blind without a runnable end-to-end audit risks divergence from the live Pi
  schema, and US-227's whole point is preserving Drive 3 across the truncate.
  Running `--execute` against an unaudited Pi is the worst outcome possible.

- Did NOT advance US-227 toward `passes:true` in any partial way. Sprint
  contract refusal rule #1 ("Refuse First — ambiguity = blocker") + US-227
  stopCondition #1 ("STOP if sync_log on Pi shows Drive 3 rows still unsynced
  at start") are explicit.

- Did NOT touch `data/regression/pi-inputs/eclipse_idle.db` or any other file
  in the US-227 doNotTouch list.

## Proposed unblock paths

1. **Recommended: CIO runs `deploy/deploy-pi.sh` from the dev box.** The
   US-226 / US-228 / US-229 fixes all land in one step. On service restart,
   `_maybeTriggerIntervalSync` fires within `pi.sync.intervalSeconds` and
   pushes Drive 3 to chi-srv-01 (US-226 flush-on-boot). Then re-run the
   pre-flight audit and US-227 is unblocked.

2. **Bridge: CIO runs `python scripts/sync_now.py` on the Pi.** Pushes Drive 3
   alone, advances the sync_log cursor past id 3,439,960. US-227 becomes
   runnable, but US-228 (drive_summary NULL on cold-start) and US-229
   (drive_end ELM_VOLTAGE keepalive) fixes are still not on the Pi — the next
   real drive captured will reproduce both bugs.

Path 1 is the recommended unblock because it consolidates the Sprint 18 fixes
in one operational step + validates the US-226 auto-trigger in production
(which path 2 doesn't).

## Filed artifacts

- `offices/pm/blockers/BL-007.md` — full blocker record + evidence
- This inbox note (cross-routing to Spool because the truncate is Spool's ask)

## Sprint 18 status (unchanged from Session 103 close)

| Story  | passes | Notes                                                |
|--------|--------|------------------------------------------------------|
| US-226 | true   | Sync code shipped; awaiting deploy                   |
| US-227 | false  | **Blocked: BL-007 (this filing)**                    |
| US-228 | true   | Drive_summary backfill shipped                       |
| US-229 | true   | ECU-silence drive_end shipped                        |
| US-230 | true   |                                                      |
| US-231 | false  | Server-tier systemd; not windows-dev-friendly        |
| US-232 | true   | TD-035 SIGTERM                                       |
| US-233 | true   | Pre-mint orphan backfill shipped                     |

Status this iteration: **6/8 passes:true; 1 blocked (US-227 = BL-007); 1 open
+ hardware/SSH-gated (US-231).**

— Rex
