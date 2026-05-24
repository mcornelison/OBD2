# I-034: SQLite `disk I/O error` flood on long-running eclipse-obd process; escalates to full Pi network drop

| Field        | Value                     |
|--------------|---------------------------|
| Severity     | High (P1)                 |
| Status       | Open (V0.27.10 or V0.28.0 candidate) |
| Category     | infrastructure / sqlite / sd-card / long-running-process |
| Found In     | `src/pi/sync/client.py:458` (`pushDelta`), `src/pi/data/sync_log.py:511` (`getHighWaterMark`), `src/pi/obdii/data/realtime.py` (`_logReadingSafe`) -- symptoms in all three sites, all reading from / writing to `~/Projects/Eclipse-01/data/obd.db` |
| Found By     | Marcus (PM) 2026-05-13 during Drive-12 analysis -- journal review post-trip |
| Related B-   | B-080 (Pi clock drift -- Spool's Bug 5; same boot, different symptom; both V0.27.6 US-322 orphan-cleanup ladder area); chain-stub to V0.27.7 I-030 (`startup_log prior_boot_clean` race under SD-card I/O contention) -- same SD-card-pressure family |
| Created      | 2026-05-13                |

## Description

The long-running `eclipse-obd` python process starts returning `sqlite3.OperationalError: disk I/O error` on every `sync_log` read and every `realtime_data` write after some uptime threshold. Today's observation: PID 1181 booted at 19:00:30 UTC, ran cleanly for ~38 minutes (drive 12 captured + synced through 19:30:49 UTC), then disk-I/O errors began at ~19:38 UTC and continued indefinitely.

Filesystem and DB state are **fine on disk**:
- `PRAGMA integrity_check` returns `ok` (queried via fresh CLI sqlite3 session)
- 98 GB free on `/` (`df -h` shows 13% used)
- No `mmcblk` / EXT4 errors in `dmesg`
- `obd.db` file is 509 MB, last-modified within minutes of the failure
- `obd.db-wal` is 0 bytes (suspicious — should have content during active writes OR be checkpointed)

Strongly suggests a **stale file-descriptor or stuck-WAL** in the long-lived Python `sqlite3.Connection` object held by the orchestrator. The process is broken; the data is not.

## Steps to Reproduce

(Today's repro is the only one on record; full repro path TBD pending Ralph investigation.)

1. Boot Pi; start eclipse-obd
2. Drive (~8 min capture + sync activity)
3. Engine off; Pi stays powered (B-063 fuse-box scenario)
4. Wait ~30+ minutes
5. Observe `journalctl -u eclipse-obd -f`

Today's symptom escalation:

| Time (UTC) | Event |
|---|---|
| 19:00:30 | Pi boot, eclipse-obd starts (PID 1181) |
| 19:01:59 - 19:10:24 | Drive 12 captured (3591 rows) -- DB writes clean |
| 19:30:49 | Last successful sync (`realtime_data` last_synced_id=3549529) |
| ~19:38 (14:38 CDT in journal) | `sqlite3.OperationalError: disk I/O error` flood begins -- on EVERY `pushDelta`, EVERY `_logReadingSafe` write, EVERY `sync_log.getHighWaterMark` read |
| ~20:50 (1h12m after errors started) | Pi disappears from network entirely -- `ping 10.27.27.28` returns "Destination host unreachable" from gateway; SSH connection refused with timeout |

## Expected Behavior

Long-running process maintains valid SQLite connections indefinitely. WAL is auto-checkpointed. If a transient I/O error occurs, process recovers (closes + reopens connection) without manual restart. Pi remains network-reachable regardless of DB layer health.

## Actual Behavior

After ~38 min uptime, every DB operation by PID 1181 fails with `disk I/O error`. Sample stack trace from today's journal (one of many identical occurrences):

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

The error fires on every heartbeat (5-10 sec intervals) until either the service restarts or the Pi reboots. Today the escalation went further: Pi dropped off the network entirely 1h12m after errors started (unable to SSH or ping from PM workstation). May or may not be related to the same underlying SD-card / fs / fd exhaustion -- unknown without on-Pi access.

## Impact

- **All sync to server stops** until restart -- no realtime_data, no battery_health_log, no statistics propagate.
- **All realtime_data writes drop** -- on top of the BT-reconnect issue (I-033), this means even rows that WOULD have been written get lost.
- **Pi may become unreachable** -- today's escalation to network-down means no remote recovery; CIO must physically reach Pi for power-cycle. Defeats the entire B-063 fuse-box "always-on telemetry" model.
- **Likely recurring** -- Spool's Bug 5 (B-080) noted similar disk-pressure-after-reboot behavior, and V0.27.7 I-030 fixed a separate SD-card-contention race in the same family. Pattern: long-running orchestrator + US-322 orphan-cleanup ladder + sync write pressure = SD card and/or SQLite layer cannot keep up.

## Validation gate impact

This bug + I-033 together explain why Drive 12 -- which was supposed to be the IRL validation gate for the V0.27 chain merge -- cannot be cleanly validated:

- I-033 lost leg 2 of the trip.
- I-034 stopped sync ~8 min after drive 12 completed, leaving server-side `drive_summary.start_time / end_time / row_count` NULL and creating doubt about whether US-326 (server analytics writer) + US-317 (Ollama-decouple) actually work end-to-end (they MAY work and just need the next sync to fire -- impossible to confirm with Pi unreachable).

Recommend gating `/chain-validated` for V0.27 until both this bug and I-033 have at least workarounds.

## Resolution -- direction

PM read; Ralph will refine. Two possible mechanisms to investigate:

1. **Stuck WAL / shared-memory file** -- the long-lived `sqlite3.Connection` is in WAL mode; if a checkpoint stalls or fails, subsequent operations may see `disk I/O error` even though the underlying disk is healthy. Check WAL checkpointing cadence + add periodic `PRAGMA wal_checkpoint(TRUNCATE)` from the orchestrator.

2. **File-descriptor exhaustion in long-running process** -- the `sqlite3.Connection` may leak handles over hours of operation, eventually hitting an fd limit. Check `lsof` on the orchestrator process when symptoms appear. Add a connection-recycling watchdog.

Either way, an orchestrator-side recovery path is needed: detect `disk I/O error` → close all SQLite connections → reopen → continue. Should NOT require service restart.

Parallel mitigation: the eclipse-obd systemd unit could add `Restart=on-failure` + `WatchdogSec=` so the service self-heals even before the code-level fix lands.

## Acceptance Criteria (PM-level)

- [ ] Pre-flight audit: rg `sqlite3.connect|isolation_level|wal_checkpoint|OperationalError` src/pi/ -- map all DB connection lifecycles
- [ ] Repro confirmed in a synthetic harness: run orchestrator for N hours; assert no `disk I/O error` AND no monotonic-growing fd count
- [ ] Recovery path: on `disk I/O error`, orchestrator closes + reopens DB connections + continues; no restart required
- [ ] Optional defense-in-depth: `eclipse-obd.service` gains `Restart=on-failure` + `WatchdogSec=` so a stuck process is killed and respawned
- [ ] Real-world validation gate: leave Pi idle (no drives, just heartbeat sync) for 6+ hours post-fix; assert journal has zero `disk I/O error` lines AND Pi remains pingable

## Cross-references

- B-080 (Pi clock drift ~23h post-reboot -- Spool Bug 5; same SD-card-pressure family)
- I-030 (V0.27.7 `startup_log prior_boot_clean` regression under SD-card I/O contention at boot; this bug is the long-uptime analog at the other end of the process lifetime)
- US-322 (V0.27.6 orphan-cleanup; identified as the source of SD-card pressure that I-030 raced with)
- I-033 (BT-no-reconnect; same Drive 12 analysis session; orthogonal bug)

## Source

Marcus (PM) journal review during Drive-12 analysis 2026-05-13. Disk-I/O error sample captured from journalctl 14:38 CDT (19:38 UTC) onward; Pi network drop confirmed by ping from PM workstation ~20:50 UTC.
