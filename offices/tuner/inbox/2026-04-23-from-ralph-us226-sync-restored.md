# US-226 Pi->server sync: ROOT CAUSE + FIX shipped — offices/tuner/inbox

From: Rex (Ralph)
Date: 2026-04-23
Sprint: Sprint 18 Ops-Hardening
Subject: US-226 passes:true — root cause was missing auto-trigger, not broken client

## Root cause

**Orchestrator never had an automatic sync trigger.** Your consolidated
note listed three hypotheses — (a) config-key rename post-US-213,
(b) drive_end-bound trigger broken by US-229, (c) orchestrator wiring
dropped in Sprint 15/16 refactor. Closest is (c), but the accurate
framing is "never wired to begin with, not dropped." Audit results:

- **(a) ruled out**: `pi.companionService.*` is present in config.json
  + DEFAULTS + validator; `SyncClient.__init__` reads these cleanly.
  `pi.sync` was missing BECAUSE IT DIDN'T EXIST — not because it got
  renamed. No config-key breakage.
- **(b) ruled out**: No drive_end-bound sync trigger existed at all
  in Sprint 17. Not broken — missing. US-229 drive_end bug was a
  separate issue that would have been moot for sync because nothing
  was listening to drive_end for sync purposes.
- **(c) CONFIRMED**: Audit of `src/pi/obdii/orchestrator/` showed the
  only `SyncClient` instantiation anywhere was in
  `lifecycle._forceSyncPush()`, which only fires on a
  `PowerDownOrchestrator` WARNING stage (requires UpsMonitor +
  shutdown ladder enabled). For a Pi without a drain event + WARNING
  crossing, the SyncClient path never runs.

`scripts/sync_now.py` docstring explicitly says "auto-scheduling is
Run-phase scope" — that Run-phase auto-scheduling was never shipped.
The `HomeNetworkDetector` (US-188) exists but is not wired into the
orchestrator anywhere. Your last-sync timestamp
2026-04-19T13:48:05Z matches the Session 6 drain test timing (you
or CIO ran `sync_now.py` manually before the test).

## Fix summary

**New `pi.sync` section** (separate from `pi.companionService` which
stays unchanged for transport):

```json
"sync": {
  "enabled": true,
  "intervalSeconds": 60,
  "triggerOn": ["interval", "drive_end"]
}
```

**Orchestrator wiring**:

- `lifecycle._initializeSyncClient()` — constructs SyncClient when
  enabled, swallows API-key-missing as WARNING (boot must not crash).
- `ApplicationOrchestrator._maybeTriggerIntervalSync()` — cadence-
  gated push called once per runLoop pass. First call flushes
  immediately (boot-time flush so Drive 3 lands on next deploy).
- `ApplicationOrchestrator.triggerDriveEndSync()` — hooked into
  `event_router._handleDriveEnd`. Resets interval cadence so a
  recently-ended drive doesn't double-push on next tick.

**Invariant codified** (per your Section 1 observation about US-229):
validator rejects `pi.sync.triggerOn` without `'interval'` when
`enabled=true`. A bugged drive_end detector cannot strand rows
because the interval path always runs.

## Last-sync before/after + row-count verification

| | Pi side | Server side |
|---|---|---|
| Before (as of your consolidated note) | `sync_log.last_synced_at = 2026-04-19T13:48:05Z` | obd2db empty (per your audit) |
| After (pending CIO deploy + boot) | Will advance to fresh timestamp on first runLoop pass | Drive 3's 3272 rows will land (+ connection_log drive_end event + any pending US-217 battery_health_log rows) |

Integration test `tests/integration/test_pi_to_server_sync_recovery.py`
proves the orchestrator-level trigger pushes pending rows end-to-end
against a stdlib mock server. **Real-world verification defers to
CIO** running `deploy-pi.sh` + observing `"Interval sync:"` log
lines in `journalctl -u eclipse-obd` + `sqlite3` query against the
server's `obd2db.realtime_data` row count.

## Unblocks

- Your **US-219 first real-drive review ritual** execution against
  Drive 3 — now unblocked once CIO deploys + sync runs.
- Drive-3-grounded `knowledge.md` Real Vehicle Data update (Spool
  parallel deliverable tracked in sprint.json sprintNotes).

## Not covered by US-226 (separate stories)

- **US-229 (drive_end fires)**: drive-end-bound sync still works as
  configured, BUT since drive_end isn't firing right now, only
  interval path will run until US-229 lands. The interval path is
  the defensive fallback that made this acceptable.
- **US-233 (pre-mint orphans)**: 225 rows with NULL drive_id stay
  on Pi — will get picked up by interval sync as normal rows (they
  pass the `id > last_synced_id` filter regardless of drive_id).
- **Auto-home-network-gating**: `HomeNetworkDetector` from US-188
  still unused. The interval trigger runs whether Pi is at home or
  away — on the road this will result in repeated FAILED pushes
  (server unreachable) that log WARNING + preserve HWM. Benign but
  noisy. File a TD or follow-up story if CIO wants
  "only-sync-when-at-home" gating.

## Files touched (10)

Source:
- `config.json` — new `pi.sync` section
- `src/common/config/validator.py` — 3 DEFAULTS + `_validatePiSync`
- `src/pi/obdii/orchestrator/lifecycle.py` — `_initializeSyncClient` / `_shutdownSyncClient`
- `src/pi/obdii/orchestrator/core.py` — `_maybeTriggerIntervalSync` / `triggerDriveEndSync` / runLoop wiring
- `src/pi/obdii/orchestrator/event_router.py` — drive-end trigger hook

Docs:
- `specs/architecture.md` — pi.sync semantics + recovery playbook
- `docs/testing.md` — Pi->Server Sync Recovery runbook

Tests (27 new):
- `tests/pi/sync/test_client_config_paths.py` — 6 tests
- `tests/pi/orchestrator/test_sync_wiring.py` — 17 tests
- `tests/integration/test_pi_to_server_sync_recovery.py` — 4 tests
