# US-339 / I-034 — SQLite `disk I/O error` flood; escalates to full Pi network drop (P1)

**From:** Marcus (PM)
**To:** Ralph (Developer)
**Date:** 2026-05-13
**Sprint:** V0.27.10 bug-fix patch (interactive — no sprint.json this time; CIO will work with you live)
**Branch:** `sprint/sprint36-bugfixes-V0.27.10` (already created)
**Priority:** P1 (sync stops, realtime_data writes drop, Pi may become unreachable)
**Size estimate:** M (PM read; Ralph to confirm — mechanism investigation may push to L)

---

## What broke

After ~38 minutes of uptime (today's PID 1181 booted 19:00:30 UTC, ran clean through drive 12 capture + sync at 19:30:49 UTC), the long-lived `eclipse-obd` python process began throwing `sqlite3.OperationalError: disk I/O error` on **every** `sync_log` read AND **every** `realtime_data` write. The errors fire on each heartbeat tick (~5-10s) until the service restarts.

**The data on disk is fine.** `PRAGMA integrity_check` returns `ok`. 98 GB free on `/`. No `mmcblk` / EXT4 errors in `dmesg`. The failure is in the running process's connection state, not in the database file or the storage layer.

Today's redeploy + service restart cleared the symptom immediately (verified post-restart: zero `disk I/O error` lines in journal). So **process restart heals it** — which strongly implicates a **stale file descriptor or stuck WAL** in the long-lived `sqlite3.Connection` object held by the orchestrator.

## Today's escalation (the part that made this P1 not P2)

~1h12m after the disk-I/O errors started (~20:50 UTC), the Pi disappeared from the network entirely. `ping 10.27.27.28` → `Destination host unreachable` from gateway; SSH timed out. CIO had to physically intervene. **This network-drop component is being tracked separately as I-035 / US-340** (likely WiFi-layer cause, not SQLite-layer cause) — DO NOT try to fix the network-drop part in this story. This story is JUST the SQLite lockup.

## Forensic sample (1 of MANY identical occurrences)

```
ERROR | pi.obdii.orchestrator | _maybeTriggerIntervalSync | Interval sync push crashed: disk I/O error
Traceback (most recent call last):
  File ".../src/pi/obdii/orchestrator/core.py", line 872, in _maybeTriggerIntervalSync
    results = self._syncClient.pushAllDeltas()
  File ".../src/pi/sync/client.py", line 599, in pushAllDeltas
    results.append(self.pushDelta(tableName))
  File ".../src/pi/sync/client.py", line 458, in pushDelta
    lastId, _, _, _ = sync_log.getHighWaterMark(conn, tableName)
  File ".../src/pi/data/sync_log.py", line 511, in getHighWaterMark
    row = conn.execute(
        "SELECT last_synced_id, last_synced_at, last_batch_id, status "
        "FROM sync_log WHERE table_name = ?",
        (tableName,),
    ).fetchone()
sqlite3.OperationalError: disk I/O error
```

Same fire pattern on `_logReadingSafe` (realtime_data writes) and other sync paths. All three sites use the orchestrator's long-lived `sqlite3.Connection`.

## Acceptance (PM-level)

1. **Pre-flight audit:** `rg "sqlite3.connect|isolation_level|wal_checkpoint|OperationalError" src/pi/` — map all DB connection lifecycles. Identify which connections are long-lived vs per-call.

2. **Recovery path in code:** on `sqlite3.OperationalError: disk I/O error`, the orchestrator should:
   - Close + reopen all SQLite connections held by the failing component
   - Resume operation without requiring service restart
   - Log a single WARNING (with a counter) per recovery rather than spamming an ERROR per failed tick
   - Test: synthetic harness that forces a disk-I/O error in the middle of a sync; assert recovery happens within N seconds and subsequent syncs succeed

3. **Investigate + fix the root cause:** likely candidates (Ralph's call to pursue one or both):
   - **WAL checkpoint never fires** — the long-lived connection's WAL grows / stalls; add periodic `PRAGMA wal_checkpoint(TRUNCATE)` from the orchestrator (every N minutes OR every N writes)
   - **File-descriptor leak** — the orchestrator opens transient connections somewhere that don't get closed; check `lsof -p <pid>` growth over time; fix the leak
   - **WAL file ownership / permissions issue** — verify `obd.db-wal` and `obd.db-shm` are owned by `mcornelison` and writable; today's `obd.db-wal` was 0 bytes which is suspicious

4. **Defense-in-depth (recommended even if root cause is fixed):** make `eclipse-obd.service` self-heal via systemd. Add `Restart=on-failure` + `WatchdogSec=` to the unit file so the service dies + respawns automatically rather than degrading silently. This alone would have prevented today's escalation to network drop.

5. **Synthetic regression test:** run the orchestrator (or a tight orchestrator-stub harness) for N simulated hours / N thousand sync cycles; assert zero `disk I/O error` AND zero monotonic fd-count growth.

6. **IRL gate (post-deploy, CIO-runs):** leave Pi idle on wall power for 6+ hours after V0.27.10 deploy; assert journal has zero `disk I/O error` lines AND Pi remains pingable throughout. (The 24h+ version of this gate is in US-340/I-035 too — they can share an IRL gate.)

## What is NOT in scope for this story

- The WiFi-soft-off / network drop component — that's US-340 / I-035
- The BT-reconnect bug — that's US-338 / I-033
- The server-side `drive_summary` analytics-fields-NULL observation from today's drive 12 (start_time/end_time/row_count empty for id=16) — that's a side-effect of this bug (sync stopped before the analytics writer could rollup); once this bug is fixed and a sync runs, expect those fields to populate. **If they don't,** that's a separate follow-up bug for V0.28+. PM will verify post-deploy.

## Cross-references

- `offices/pm/issues/I-034-sqlite-disk-io-lockup-on-long-uptime.md` — PM bug paper (full forensic timeline + mechanism candidates)
- I-030 (V0.27.7 `startup_log prior_boot_clean` regression under SD-card I/O contention at boot) — SAME family of SD-card / SQLite pressure issues but at the boot end of process lifetime; this bug is the long-uptime analog
- B-080 (Pi clock drift ~23h post-reboot — Spool's Bug 5) — adjacent symptom; same long-uptime pressure family
- I-033, I-035 (sibling V0.27.10 stories)

## Ack expected

Confirm: (a) recovery-path-in-code approach acceptable, (b) which root-cause direction you'll pursue first (WAL checkpoint vs fd leak), (c) systemd defense-in-depth landing as part of this story or split out. Then commit + push when first cut is ready.
